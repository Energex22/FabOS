from pathlib import Path
from urllib.request import Request,urlopen
import re,json,uuid
from datetime import datetime
class ManufacturingService:
 def __init__(self,db):self.db=db
 def attach_gcode(self,jid,path):
  text=Path(path).read_text(encoding='utf-8',errors='ignore');mins=None;grams=None
  m=re.search(r';\s*estimated printing time.*?=\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?',text,re.I)
  if m:mins=int(m.group(1) or 0)*60+int(m.group(2) or 0)+(1 if int(m.group(3) or 0)>=30 else 0)
  g=re.search(r';\s*filament used \[g\]\s*=\s*([\d.]+)',text,re.I)
  if g:grams=float(g.group(1))
  meta={'estimated_minutes':mins,'filament_g':grams}
  with self.db.connect() as c:c.execute('UPDATE print_jobs SET gcode_path=?,estimated_minutes=COALESCE(?,estimated_minutes),estimated_filament_g=COALESCE(?,estimated_filament_g),slicer_metadata_json=? WHERE id=?',(str(path),mins,grams,json.dumps(meta),jid));c.commit()
  return meta
 def octo(self,base,key,path,method='GET',body=None):
  data=json.dumps(body).encode() if body is not None else None;h={'X-Api-Key':key,'Accept':'application/json'}
  if data:h['Content-Type']='application/json'
  with urlopen(Request(base.rstrip('/')+path,data=data,method=method,headers=h),timeout=12) as r:
   raw=r.read();return json.loads(raw.decode()) if raw else {}
 def octo_job(self,base,key):return self.octo(base,key,'/api/job')
 def octo_command(self,base,key,command,action=None):
  b={'command':command};
  if action:b['action']=action
  return self.octo(base,key,'/api/job','POST',b)
 def learn(self,jid):
  with self.db.connect() as c:
   j=c.execute('SELECT * FROM print_jobs WHERE id=?',(jid,)).fetchone()
   if not j or c.execute('SELECT 1 FROM manufacturing_observations WHERE print_job_id=?',(jid,)).fetchone():return
   c.execute('INSERT INTO manufacturing_observations(id,product_id,print_job_id,printer_id,estimated_minutes,actual_minutes,estimated_filament_g,actual_filament_g,success) VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),j['product_id'],jid,j['printer_id'],j['estimated_minutes'],j['actual_minutes'],j['estimated_filament_g'],j['actual_filament_g'],j['success']))
   if j['success'] and j['product_id'] and j['actual_minutes']:
    a=c.execute('SELECT AVG(actual_minutes),AVG(COALESCE(actual_filament_g,estimated_filament_g)) FROM manufacturing_observations WHERE product_id=? AND success=1 AND actual_minutes IS NOT NULL',(j['product_id'],)).fetchone();c.execute('UPDATE products SET estimated_minutes=?,estimated_filament_g=COALESCE(?,estimated_filament_g),updated_at=CURRENT_TIMESTAMP WHERE id=?',(int(round(a[0])),a[1],j['product_id']))
   c.execute('UPDATE print_jobs SET learning_recorded=1 WHERE id=?',(jid,));c.commit()
 def ensure_qc(self,order_id,jid):
  items=['Supports removed','Stringing/blobs cleaned','Surface finish acceptable','Dimensions/fit checked if applicable','Hardware/inserts installed if applicable','Customization verified','Finished-product photo taken','Packaging checked']
  with self.db.connect() as c:
   if c.execute('SELECT 1 FROM qc_inspections WHERE print_job_id=?',(jid,)).fetchone():return
   c.execute('INSERT INTO qc_inspections(id,order_id,print_job_id,checklist_json) VALUES(?,?,?,?)',(str(uuid.uuid4()),order_id,jid,json.dumps([{'text':x,'checked':False} for x in items])));c.commit()
 def qc_list(self):
  with self.db.connect() as c:return c.execute("""SELECT q.*,o.order_number,c.name customer_name,p.name product_name FROM qc_inspections q LEFT JOIN orders o ON o.id=q.order_id LEFT JOIN customers c ON c.id=o.customer_id LEFT JOIN print_jobs j ON j.id=q.print_job_id LEFT JOIN products p ON p.id=j.product_id ORDER BY q.created_at DESC""").fetchall()
 def qc_save(self,qid,items,notes,passed):
  with self.db.connect() as c:
   q=c.execute('SELECT * FROM qc_inspections WHERE id=?',(qid,)).fetchone();status='passed' if passed else 'pending';c.execute('UPDATE qc_inspections SET checklist_json=?,notes=?,status=?,inspected_at=? WHERE id=?',(json.dumps(items),notes,status,datetime.now().isoformat(timespec='seconds') if passed else None,qid))
   if passed and q and c.execute("SELECT COUNT(*) FROM qc_inspections WHERE order_id=? AND id<>? AND status<>'passed'",(q['order_id'],qid)).fetchone()[0]==0:c.execute("UPDATE orders SET status='ready' WHERE id=?",(q['order_id'],))
   c.commit()

 def complete_with_inventory(self,jid,actual_minutes=None,actual_filament_g=None):
  with self.db.connect() as c:
   j=c.execute('SELECT * FROM print_jobs WHERE id=?',(jid,)).fetchone()
   if not j:return
   grams=actual_filament_g if actual_filament_g is not None else j['estimated_filament_g']
   c.execute("""UPDATE print_jobs SET actual_minutes=COALESCE(?,actual_minutes),
     actual_filament_g=COALESCE(?,actual_filament_g),filament_deducted=1
     WHERE id=?""",(actual_minutes,grams,jid))
   c.commit()
  try:
   from fabos_core.services.inventory_profit import InventoryProfitService
   inv=InventoryProfitService(self.db)
   if j['spool_id'] and not j['filament_deducted'] and grams:
    inv.record_consumption(j['spool_id'],grams,jid)
   inv.calculate_job_cost(jid)
  except Exception:
   pass
  self.learn(jid)

 def fail_job(self,jid,reason):
  with self.db.connect() as c:
   c.execute("UPDATE print_jobs SET failure_reason=? WHERE id=?",(reason,jid));c.commit()

 def reprint(self,jid):
  with self.db.connect() as c:
   j=c.execute('SELECT * FROM print_jobs WHERE id=?',(jid,)).fetchone()
   if not j:raise KeyError('Print job not found')
   nid=str(uuid.uuid4())
   c.execute("""INSERT INTO print_jobs
    (id,order_id,product_id,printer_id,spool_id,status,gcode_path,octoprint_file,
     estimated_minutes,estimated_filament_g,slicer_metadata_json)
    VALUES(?,?,?,?,?,'scheduled',?,?,?,?,?)""",
    (nid,j['order_id'],j['product_id'],j['printer_id'],j['spool_id'],j['gcode_path'],
     j['octoprint_file'],j['estimated_minutes'],j['estimated_filament_g'],j['slicer_metadata_json']))
   c.commit();return nid
 def parse_gcode_file(self,path):
  text=Path(path).read_text(encoding='utf-8',errors='ignore');mins=None;grams=None
  m=re.search(r';\s*estimated printing time.*?=\s*(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?',text,re.I)
  if m:mins=int(m.group(1) or 0)*60+int(m.group(2) or 0)+(1 if int(m.group(3) or 0)>=30 else 0)
  g=re.search(r';\s*filament used \[g\]\s*=\s*([\d.]+)',text,re.I)
  if g:grams=float(g.group(1))
  return {'estimated_minutes':mins,'filament_g':grams}
 def qc_update(self,qid,items,notes="",status="pending"):
  allowed=("pending","rework","passed")
  if status not in allowed:raise ValueError("Invalid QC status.")
  with self.db.connect() as c:
   q=c.execute("SELECT * FROM qc_inspections WHERE id=?",(qid,)).fetchone()
   if not q:raise KeyError("QC inspection not found.")
   c.execute("""UPDATE qc_inspections SET checklist_json=?,notes=?,status=?,
      inspected_at=CASE WHEN ?='passed' THEN CURRENT_TIMESTAMP ELSE inspected_at END
      WHERE id=?""",(json.dumps(items),notes,status,status,qid))
   if status=="passed":
    remaining=c.execute("""SELECT COUNT(*) FROM qc_inspections
      WHERE order_id=? AND id<>? AND status<>'passed'""",(q["order_id"],qid)).fetchone()[0]
    if remaining==0:c.execute("UPDATE orders SET status='ready' WHERE id=?",(q["order_id"],))
   elif status=="rework":
    c.execute("UPDATE orders SET status='qc' WHERE id=?",(q["order_id"],))
   try:
    c.execute("""INSERT INTO activity_journal(id,event_type,title,detail,page,entity_id)
      VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),'qc.'+status,'QC '+status.replace('_',' ').title(),notes or 'Inspection updated','QC',qid))
   except Exception:pass
   c.commit()
 def reconcile_qc(self):
  created=0
  with self.db.connect() as c:
   rows=c.execute("""SELECT j.id job_id,j.order_id
    FROM print_jobs j JOIN orders o ON o.id=j.order_id
    WHERE j.order_id IS NOT NULL
      AND (j.status='completed' OR o.status='qc')
      AND NOT EXISTS(SELECT 1 FROM qc_inspections q WHERE q.print_job_id=j.id)
    ORDER BY j.created_at""").fetchall()
  for r in rows:
   self.ensure_qc(r['order_id'],r['job_id']);created+=1
  return created

