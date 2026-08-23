import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.shop_settings import ShopSettingsService
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.customer_updates import CustomerUpdateService
from fabos_desktop.main import FabOSDesktop

class SettingsCenterTests(unittest.TestCase):
 def test_settings_and_invoice_defaults(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   settings=ShopSettingsService(db)
   settings.update({"invoice_prefix":"WV","invoice_due_days":"30","default_tax_percent":"10","shop_name":"WireVault Prints"})
   oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,total_cents,status) VALUES(?,?,?,?)",(oid,"O-SET",1000,"ready"));c.commit()
   invoices=InvoiceService(db,Path(td))
   iid,_=invoices.create_from_order(oid)
   inv,_,_=invoices.get(iid)
   self.assertTrue(inv["invoice_number"].startswith("WV-"))
   self.assertEqual(inv["subtotal_cents"],1000)
   self.assertEqual(inv["tax_cents"],100)
   self.assertEqual(inv["total_cents"],1100)

 def test_customer_signature(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   settings=ShopSettingsService(db);settings.set("customer_update_signature","Thanks, WireVault")
   cid=str(uuid.uuid4());oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO customers(id,name) VALUES(?,?)",(cid,"Alex"))
    c.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,0)",(oid,"O-SIG",cid,"new"));c.commit()
   msg=CustomerUpdateService(db).generate(oid)
   self.assertIn("Thanks, WireVault",msg["body"])

 def test_settings_ui_wired(self):
  self.assertTrue(hasattr(FabOSDesktop,"_build_settings_page"))
  self.assertTrue(hasattr(FabOSDesktop,"_settings_save_all"))

if __name__=="__main__":unittest.main()
