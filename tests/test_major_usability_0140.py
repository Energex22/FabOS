import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.operations_hub import OperationsHubService
from fabos_core.services.inventory_profit import InventoryProfitService
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.octoprint_print import OctoPrintPrintService

class StubSettings:
 def __init__(self,vals=None):self.vals=vals or {}
 def get(self,key,default=None):return self.vals.get(key,default)

class StubProducts:
 def list(self,*args,**kwargs):return []

class StubVault:
 def product_print_status_map(self,ids):return {x:{'ready':True} for x in ids}

class StubProduction:
 def job_print_readiness(self,jid,vault):return {'ready':True,'reason':'G-code Ready','gcode':'ready.gcode'}

class StubReliability:
 def health(self):return [{'name':'Database','status':'pass','detail':'ok'}]

class FakeApp:
 def __init__(self,db):
  self.database=db;self.shop_settings=StubSettings({'filament_low_threshold_g':'250'})
  self.products=StubProducts();self.design_vault=StubVault();self.production=StubProduction();self.reliability=StubReliability()

class FakeManufacturing:
 def __init__(self):self.calls=[]
 def octo(self,base,key,path,method='GET',body=None):
  self.calls.append((path,method,body));return {}

class MajorUsability0140Tests(unittest.TestCase):
 def new_db(self,td):
  db=Database(Path(td)/'x.sqlite3');db.initialize();migrate(db);return db

 def test_action_center_and_notifications(self):
  with tempfile.TemporaryDirectory() as td:
   db=self.new_db(td)
   pid=str(uuid.uuid4());sid=str(uuid.uuid4());oid=str(uuid.uuid4());iid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO printers(id,name,model,status,build_x_mm,build_y_mm,build_z_mm,connection_mode,octoprint_state_text) VALUES(?,?,?,?,?,?,?,?,?)",
              (pid,'Vyper','Anycubic Vyper','offline',245,245,260,'octoprint','Printer Not Responding'))
    c.execute("INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,cost_cents,active) VALUES(?,?,?,?,?,?,1)",
              (sid,'PETG','Black',1000,120,2000))
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,'ORD-1','ready',2500))
    c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,total_cents,paid_cents,subtotal_cents) VALUES(?,?,?,?,?,?,?)",
              (iid,'INV-1',oid,'open',2500,0,2500))
    c.commit()
   hub=OperationsHubService(FakeApp(db))
   titles={x['title'] for x in hub.action_items()}
   self.assertIn('Printer needs attention',titles)
   self.assertIn('Low filament',titles)
   self.assertIn('Ready to pack / ship',titles)
   self.assertIn('Unpaid invoice',titles)
   self.assertGreaterEqual(hub.unread_count(),4)

 def test_workflow_reconcile_expires_quotes_and_advances_qc(self):
  with tempfile.TemporaryDirectory() as td:
   db=self.new_db(td);app=FakeApp(db);hub=OperationsHubService(app)
   cid=str(uuid.uuid4());qid=str(uuid.uuid4());pid=str(uuid.uuid4());oid=str(uuid.uuid4());jid=str(uuid.uuid4());qc=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO customers(id,name) VALUES(?,?)",(cid,'Customer'))
    c.execute("INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,expires_at) VALUES(?,?,?,?,?,?)",(qid,'Q-1',cid,'sent',1000,'2020-01-01'))
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,'Widget','verified'))
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,'O-QC','production'))
    c.execute("INSERT INTO print_jobs(id,order_id,product_id,status) VALUES(?,?,?,?)",(jid,oid,pid,'completed'))
    c.execute("INSERT INTO qc_inspections(id,order_id,print_job_id,status,checklist_json) VALUES(?,?,?,?,?)",(qc,oid,jid,'passed','[]'))
    c.commit()
   hub.reconcile_workflows()
   with db.connect() as c:
    self.assertEqual(c.execute("SELECT status FROM quotes WHERE id=?",(qid,)).fetchone()['status'],'expired')
    self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()['status'],'ready')
    self.assertEqual(c.execute("SELECT COUNT(*) FROM notifications WHERE dedupe_key=?",('event:quoteexpired:'+qid,)).fetchone()[0],1)

 def test_print_next_picks_earliest_runnable_job(self):
  with tempfile.TemporaryDirectory() as td:
   db=self.new_db(td);app=FakeApp(db);hub=OperationsHubService(app)
   product=str(uuid.uuid4());printer=str(uuid.uuid4());spool=str(uuid.uuid4())
   order1=str(uuid.uuid4());order2=str(uuid.uuid4());j1=str(uuid.uuid4());j2=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(product,'Widget','verified'))
    c.execute("INSERT INTO printers(id,name,model,status,build_x_mm,build_y_mm,build_z_mm) VALUES(?,?,?,?,?,?,?)",
              (printer,'Vyper','Anycubic Vyper','idle',245,245,260))
    c.execute("INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,cost_cents,active) VALUES(?,?,?,?,?,?,1)",
              (spool,'PETG','Black',1000,800,2000))
    c.execute("INSERT INTO orders(id,order_number,status,due_at,total_cents) VALUES(?,?,?,?,0)",(order1,'O-LATE','production','2030-02-01'))
    c.execute("INSERT INTO orders(id,order_number,status,due_at,total_cents) VALUES(?,?,?,?,0)",(order2,'O-EARLY','production','2030-01-01'))
    c.execute("INSERT INTO print_jobs(id,order_id,product_id,printer_id,spool_id,status,estimated_filament_g) VALUES(?,?,?,?,?,?,?)",
              (j1,order1,product,printer,spool,'scheduled',50))
    c.execute("INSERT INTO print_jobs(id,order_id,product_id,printer_id,spool_id,status,estimated_filament_g) VALUES(?,?,?,?,?,?,?)",
              (j2,order2,product,printer,spool,'scheduled',50))
    c.commit()
   choice=hub.print_next();self.assertIsNotNone(choice);self.assertEqual(choice['job']['id'],j2)

 def test_failed_print_waste_and_cost(self):
  with tempfile.TemporaryDirectory() as td:
   db=self.new_db(td);pid=str(uuid.uuid4());sid=str(uuid.uuid4());jid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO printers(id,name,model,status,build_x_mm,build_y_mm,build_z_mm,simulation_progress) VALUES(?,?,?,?,?,?,?,?)",
              (pid,'Vyper','Vyper','idle',245,245,260,50))
    c.execute("INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,cost_cents,active) VALUES(?,?,?,?,?,?,1)",
              (sid,'PETG','Black',1000,1000,2000))
    c.execute("INSERT INTO print_jobs(id,printer_id,spool_id,status,estimated_filament_g,estimated_minutes) VALUES(?,?,?,?,?,?)",
              (jid,pid,sid,'failed',100,120));c.commit()
   svc=InventoryProfitService(db);grams=svc.record_failed_waste(jid)
   self.assertAlmostEqual(grams,50,places=2)
   with db.connect() as c:
    spool=c.execute("SELECT remaining_g FROM filament_spools WHERE id=?",(sid,)).fetchone()
    job=c.execute("SELECT actual_filament_g,material_cost_cents,machine_cost_cents,profit_cents FROM print_jobs WHERE id=?",(jid,)).fetchone()
   self.assertAlmostEqual(spool['remaining_g'],950,places=2)
   self.assertAlmostEqual(job['actual_filament_g'],50,places=2)
   self.assertLess(job['profit_cents'],0)

 def test_payment_waits_for_fulfillment_before_completion(self):
  with tempfile.TemporaryDirectory() as td:
   db=self.new_db(td);oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,'O-1','ready',2500));c.commit()
   invoices=InvoiceService(db,Path(td));iid,_=invoices.create_from_order(oid);invoices.record_payment(iid,2500,'Cash')
   with db.connect() as c:self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()['status'],'ready')
   FulfillmentService(db).save(oid,'shipping','delivered','UPS','1Z',12,0,'Customer',length_in=8,width_in=6,height_in=4)
   with db.connect() as c:self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()['status'],'completed')

 def test_shipping_cost_updates_invoice_and_package_dimensions(self):
  with tempfile.TemporaryDirectory() as td:
   db=self.new_db(td);oid=str(uuid.uuid4())
   with db.connect() as c:c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,'O-2','ready',1000));c.commit()
   inv=InvoiceService(db,Path(td));iid,_=inv.create_from_order(oid)
   FulfillmentService(db).save(oid,'shipping','shipped','USPS','TRACK',16,500,'Somewhere',length_in=10,width_in=8,height_in=6)
   with db.connect() as c:
    f=c.execute("SELECT * FROM fulfillments WHERE order_id=?",(oid,)).fetchone()
    i=c.execute("SELECT shipping_cents,total_cents FROM invoices WHERE id=?",(iid,)).fetchone()
   self.assertEqual(i['shipping_cents'],500);self.assertEqual(i['total_cents'],1500)
   self.assertEqual((f['package_length_in'],f['package_width_in'],f['package_height_in']),(10,8,6))

 def test_octoprint_pause_resume_cancel_commands(self):
  m=FakeManufacturing();svc=OctoPrintPrintService(m,None);p={'octoprint_url':'http://octo','api_key_ref':'k'}
  svc.pause(p);svc.resume(p);svc.cancel(p)
  self.assertIn(('/api/job','POST',{'command':'pause','action':'pause'}),m.calls)
  self.assertIn(('/api/job','POST',{'command':'pause','action':'resume'}),m.calls)
  self.assertIn(('/api/job','POST',{'command':'cancel'}),m.calls)

 def test_major_ui_features_are_wired(self):
  root=Path(__file__).resolve().parents[1]
  main=(root/'fabos_desktop/main.py').read_text(encoding='utf-8')
  printer=(root/'fabos_desktop/printer_ui.py').read_text(encoding='utf-8')
  system=(root/'fabos_desktop/system_ui.py').read_text(encoding='utf-8')
  commerce=(root/'fabos_desktop/commerce_ui.py').read_text(encoding='utf-8')
  self.assertIn('Action Center',main);self.assertIn('PRINT NEXT',main);self.assertIn('notification_button',main)
  self.assertIn('def _product_card_gallery',main);self.assertIn('<Control-p>',main);self.assertIn('def _build_activity_page',main)
  self.assertIn('Pause / Resume',printer);self.assertIn('Cancel Print',printer)
  self.assertIn('def _run_setup_wizard',system);self.assertIn('package_length_in',commerce)

if __name__=='__main__':unittest.main()
