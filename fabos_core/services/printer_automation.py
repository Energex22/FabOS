import uuid
from datetime import datetime
class PrinterAutomationService:
 def __init__(self,db,production,manufacturing):
  self.db=db;self.production=production;self.m=manufacturing
 def list(self):
  with self.db.connect() as c:return c.execute("""SELECT pr.*,
    (SELECT COUNT(*) FROM print_jobs j WHERE j.printer_id=pr.id AND j.status IN ('scheduled','printing','paused')) active_jobs
    FROM printers pr ORDER BY pr.name""").fetchall()
 def configure(self,pid,mode,url='',key=''):
  with self.db.connect() as c:
   c.execute('UPDATE printers SET connection_mode=?,octoprint_url=?,api_key_ref=? WHERE id=?',(mode,url,key,pid));c.commit()
 def active_job(self,pid):
  with self.db.connect() as c:return c.execute("""SELECT j.*,p.name product_name,o.order_number,
   fs.material spool_material,fs.color spool_color
   FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id LEFT JOIN orders o ON o.id=j.order_id
   LEFT JOIN filament_spools fs ON fs.id=j.spool_id
   WHERE j.printer_id=? AND j.status IN ('printing','paused','scheduled')
   ORDER BY CASE j.status WHEN 'printing' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,j.created_at DESC LIMIT 1""",(pid,)).fetchone()
 def start_simulation(self,pid,jid):
  with self.db.connect() as c:
   c.execute("UPDATE printers SET connection_mode='simulation',status='printing',simulation_progress=0,nozzle_temp=205,bed_temp=60,last_seen_at=? WHERE id=?",(datetime.now().isoformat(timespec='seconds'),pid));c.commit()
  self.production.set_status(jid,'printing')
 def simulation_tick(self,pid,step=10):
  job=self.active_job(pid)
  if not job or job['status']!='printing':return None
  with self.db.connect() as c:
   pr=c.execute('SELECT * FROM printers WHERE id=?',(pid,)).fetchone()
   progress=min(100,float(pr['simulation_progress'] or 0)+step)
   c.execute('UPDATE printers SET simulation_progress=?,nozzle_temp=205,bed_temp=60,last_seen_at=? WHERE id=?',(progress,datetime.now().isoformat(timespec='seconds'),pid));c.commit()
  if progress>=100:
   self.production.set_status(job['id'],'completed')
   self.m.complete_with_inventory(job['id'],job['estimated_minutes'],job['estimated_filament_g'])
   with self.db.connect() as c:c.execute("UPDATE printers SET status='idle',simulation_progress=100 WHERE id=?",(pid,));c.commit()
  return progress
 def sync_octoprint(self,pid):
  active_before=self.active_job(pid)
  with self.db.connect() as c:pr=c.execute('SELECT * FROM printers WHERE id=?',(pid,)).fetchone()
  if not pr or not pr['octoprint_url'] or not pr['api_key_ref']:raise ValueError('OctoPrint URL/API key not configured.')
  base=pr['octoprint_url'];key=pr['api_key_ref']
  try:
   connection=self.m.octo(base,key,'/api/connection')
   conn=(connection.get('current') or {});conn_state=str(conn.get('state') or 'Unknown')
  except Exception as exc:
   conn_state='OctoPrint Timeout' if 'timed out' in str(exc).lower() else 'OctoPrint Offline'
   with self.db.connect() as c:
    c.execute("""UPDATE printers SET status='offline',octoprint_state_text=?,last_seen_at=? WHERE id=?""",
      (conn_state,datetime.now().isoformat(timespec='seconds'),pid));c.commit()
   raise

  lower=conn_state.lower()
  if any(x in lower for x in ('closed','offline','error')):
   with self.db.connect() as c:
    c.execute("""UPDATE printers SET status='offline',simulation_progress=0,nozzle_temp=NULL,bed_temp=NULL,
      octoprint_current_file=NULL,print_time_seconds=NULL,print_time_left_seconds=NULL,
      octoprint_state_text=?,last_seen_at=? WHERE id=?""",
      ('Printer '+conn_state,datetime.now().isoformat(timespec='seconds'),pid));c.commit()
   return {'state':'Printer '+conn_state,'connection':connection}

  info=self.m.octo_job(base,key);state=info.get('state','Unknown');prog=(info.get('progress') or {}).get('completion')
  temps={};responsive=True
  try:
   pstate=self.m.octo(base,key,'/api/printer?history=true&limit=2')
   temps=pstate.get('temperature',{})
   history=temps.get('history') or []
   if history:
    newest=max(float(x.get('time') or 0) for x in history)
    import time as _time
    if newest and _time.time()-newest>20:responsive=False
  except Exception:
   responsive=False
  job_data=info.get('job') or {};file_data=job_data.get('file') or {};current_file=file_data.get('name')
  progress=info.get('progress') or {};print_time=progress.get('printTime');time_left=progress.get('printTimeLeft')
  if not responsive:
   mapped='offline';display_state='Printer Not Responding'
  else:
   mapped='printing' if state in ('Printing','Pausing') else ('paused' if state=='Paused' else 'idle')
   display_state=state
  with self.db.connect() as c:
   c.execute("""UPDATE printers SET status=?,simulation_progress=?,nozzle_temp=?,bed_temp=?,last_seen_at=?,
     octoprint_current_file=?,print_time_seconds=?,print_time_left_seconds=?,octoprint_state_text=? WHERE id=?""",
    (mapped,prog or 0,(temps.get('tool0') or {}).get('actual'),(temps.get('bed') or {}).get('actual'),
     datetime.now().isoformat(timespec='seconds'),current_file if responsive else None,print_time,time_left,display_state,pid))
   if current_file and responsive:
    row=c.execute("""SELECT * FROM print_jobs WHERE printer_id=? AND
      (octoprint_file=? OR gcode_path LIKE ?) ORDER BY created_at DESC LIMIT 1""",(pid,current_file,'%'+current_file)).fetchone()
    if row:
     jstatus='printing' if state in ('Printing','Pausing') else ('paused' if state=='Paused' else row['status'])
     c.execute('UPDATE print_jobs SET status=?,octoprint_state=?,octoprint_file=? WHERE id=?',(jstatus,state,current_file,row['id']))
     if state in ('Printing','Pausing') and not row['started_at']:
      c.execute('UPDATE print_jobs SET started_at=? WHERE id=?',(datetime.now().isoformat(timespec='seconds'),row['id']))
   c.commit()

  if responsive and active_before and active_before['status'] in ('printing','paused') and mapped=='idle':
   try:completion=float(prog) if prog is not None else None
   except Exception:completion=None
   try:left=float(time_left) if time_left is not None else None
   except Exception:left=None
   try:elapsed=float(print_time) if print_time is not None else None
   except Exception:elapsed=None
   same_file=(not active_before['octoprint_file'] or not current_file or
              str(active_before['octoprint_file'])==str(current_file))
   finished=(completion is not None and completion>=99.5) or (
       left is not None and left<=1 and elapsed is not None and elapsed>0)
   if same_file and finished:
    try:
     self.production.set_status(active_before['id'],'completed')
     actual_minutes=max(1,int(round(elapsed/60.0))) if elapsed else None
     self.m.complete_with_inventory(active_before['id'],actual_minutes,active_before['estimated_filament_g'])
     try:
      with self.db.connect() as c:
       c.execute("""INSERT INTO activity_journal(id,event_type,title,detail,page,entity_id)
        VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),'print.completed','Print completed',
        '%s • %s'%(active_before['product_name'] or 'Print',active_before['order_number'] or 'Personal'),'Production',active_before['id']))
       c.execute("""INSERT OR IGNORE INTO notifications(
        id,dedupe_key,severity,title,body,page,entity_id,is_read) VALUES(?,?,?,?,?,?,?,0)""",
        (str(uuid.uuid4()),'event:printcomplete:'+active_before['id'],'info','Print finished',
         '%s finished on the printer.'%(active_before['product_name'] or 'Print'),'Production',active_before['id']))
       c.commit()
     except Exception:pass
    except Exception:pass
  return info