import uuid

class InventoryProfitService:
 def __init__(self,db):self.db=db

 def setting(self,key,default=None):
  with self.db.connect() as c:r=c.execute("SELECT value FROM shop_settings WHERE key=?",(key,)).fetchone()
  return r["value"] if r else default

 def set_setting(self,key,value):
  with self.db.connect() as c:
   c.execute("""INSERT INTO shop_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",(key,str(value)));c.commit()

 def spools(self,query="",active_only=True):
  needle="%%%s%%"%query.strip()
  sql="""SELECT s.*,
   CASE WHEN initial_g>0 THEN ROUND(remaining_g*100.0/initial_g,1) ELSE 0 END pct_remaining,
   CASE WHEN initial_g>0 THEN cost_cents*1.0/initial_g ELSE 0 END cost_per_g_cents,
   COALESCE((SELECT SUM(-quantity) FROM inventory_transactions t
     WHERE t.item_type='filament' AND t.item_id=s.id AND t.transaction_type='consume'
     AND t.created_at>=datetime('now','-30 days')),0) used_30d
   FROM filament_spools s
   WHERE (?='' OR s.material LIKE ? OR COALESCE(s.brand,'') LIKE ? OR COALESCE(s.color,'') LIKE ?)
  """
  args=[query.strip(),needle,needle,needle]
  if active_only:sql+=" AND s.active=1"
  sql+=" ORDER BY s.material,s.color,s.brand"
  with self.db.connect() as c:return c.execute(sql,args).fetchall()

 def add_spool(self,material,brand,color,initial_g,cost_cents,location="",lot_number=""):
  sid=str(uuid.uuid4())
  with self.db.connect() as c:
   c.execute("""INSERT INTO filament_spools(id,material,brand,color,initial_g,remaining_g,cost_cents,location,lot_number,active)
    VALUES(?,?,?,?,?,?,?,?,?,1)""",(sid,material,brand,color,float(initial_g),float(initial_g),int(cost_cents),location,lot_number))
   c.execute("""INSERT INTO inventory_transactions(id,item_type,item_id,transaction_type,quantity,unit,notes)
    VALUES(?,?,?,?,?,?,?)""",(str(uuid.uuid4()),"filament",sid,"purchase",float(initial_g),"g","Spool added"))
   c.commit()
  return sid

 def adjust_spool(self,sid,new_remaining,notes="Manual adjustment"):
  with self.db.connect() as c:
   old=c.execute("SELECT remaining_g FROM filament_spools WHERE id=?",(sid,)).fetchone()
   if not old:raise KeyError("Spool not found")
   delta=float(new_remaining)-float(old["remaining_g"])
   c.execute("UPDATE filament_spools SET remaining_g=? WHERE id=?",(float(new_remaining),sid))
   c.execute("""INSERT INTO inventory_transactions(id,item_type,item_id,transaction_type,quantity,unit,notes)
    VALUES(?,?,?,?,?,?,?)""",(str(uuid.uuid4()),"filament",sid,"adjust",delta,"g",notes))
   c.commit()

 def record_consumption(self,sid,grams,job_id):
  if not sid or not grams:return
  with self.db.connect() as c:
   exists=c.execute("""SELECT 1 FROM inventory_transactions
    WHERE item_type='filament' AND item_id=? AND reference_type='print_job' AND reference_id=? AND transaction_type='consume'""",
    (sid,job_id)).fetchone()
   if exists:return
   c.execute("UPDATE filament_spools SET remaining_g=MAX(0,remaining_g-?) WHERE id=?",(float(grams),sid))
   c.execute("""INSERT INTO inventory_transactions(id,item_type,item_id,transaction_type,quantity,unit,reference_type,reference_id,notes)
    VALUES(?,?,?,?,?,?,?,?,?)""",(str(uuid.uuid4()),"filament",sid,"consume",-float(grams),"g","print_job",job_id,"Automatic print consumption"))
   c.commit()

 def record_failed_waste(self,job_id):
  with self.db.connect() as c:
   j=c.execute("""SELECT j.*,COALESCE(p.simulation_progress,0) progress
      FROM print_jobs j LEFT JOIN printers p ON p.id=j.printer_id WHERE j.id=?""",(job_id,)).fetchone()
   if not j or not j["spool_id"]:return 0
   existing=c.execute("""SELECT 1 FROM inventory_transactions WHERE reference_type='failed_print'
      AND reference_id=? AND transaction_type='waste'""",(job_id,)).fetchone()
   if existing:return 0
   estimated=float(j["estimated_filament_g"] or 0)
   progress=float(j["progress"] or 0)
   fallback=float(self.setting("failed_print_waste_factor","0.50") or .50)
   ratio=max(0.0,min(1.0,progress/100.0)) if progress>0 else fallback
   grams=estimated*ratio
   if grams<=0:return 0
   c.execute("UPDATE filament_spools SET remaining_g=MAX(0,remaining_g-?) WHERE id=?",(grams,j["spool_id"]))
   c.execute("""INSERT INTO inventory_transactions(
      id,item_type,item_id,transaction_type,quantity,unit,reference_type,reference_id,notes)
      VALUES(?,?,?,?,?,?,?,?,?)""",
      (str(uuid.uuid4()),"filament",j["spool_id"],"waste",-grams,"g","failed_print",job_id,
       "Estimated failed-print waste at %.0f%% progress"%(ratio*100)))
   spool=c.execute("SELECT cost_cents,initial_g FROM filament_spools WHERE id=?",(j["spool_id"],)).fetchone()
   material_cost=round((float(spool["cost_cents"] or 0)/max(float(spool["initial_g"] or 1),1))*grams) if spool else 0
   actual_minutes=max(1,int(round(float(j["estimated_minutes"] or 0)*ratio))) if j["estimated_minutes"] else None
   hourly=float(self.setting("machine_hourly_cost","0.35") or .35)
   machine_cost=round(hourly*100*((actual_minutes or 0)/60.0))
   c.execute("""UPDATE print_jobs SET actual_filament_g=COALESCE(actual_filament_g,?),
      actual_minutes=COALESCE(actual_minutes,?),filament_deducted=1,material_cost_cents=?,
      machine_cost_cents=?,packaging_cost_cents=0,profit_cents=? WHERE id=?""",
      (grams,actual_minutes,material_cost,machine_cost,-(material_cost+machine_cost),job_id))
   c.commit()
  return grams

 def calculate_job_cost(self,job_id):
  hourly=float(self.setting("machine_hourly_cost","0.35") or 0)
  packaging=float(self.setting("default_packaging_cost","0.50") or 0)
  with self.db.connect() as c:
   j=c.execute("""SELECT j.*,s.cost_cents spool_cost,s.initial_g spool_initial,
      o.total_cents order_total,
      (SELECT COUNT(*) FROM print_jobs x WHERE x.order_id=j.order_id) order_job_count
      FROM print_jobs j
      LEFT JOIN filament_spools s ON s.id=j.spool_id
      LEFT JOIN orders o ON o.id=j.order_id WHERE j.id=?""",(job_id,)).fetchone()
   if not j:return None
   grams=float(j["actual_filament_g"] or j["estimated_filament_g"] or 0)
   mins=float(j["actual_minutes"] or j["estimated_minutes"] or 0)
   material=round((float(j["spool_cost"] or 0)/float(j["spool_initial"] or 1))*grams)
   machine=round(hourly*100*(mins/60.0))
   pack=round(packaging*100)
   revenue=round(float(j["order_total"] or 0)/max(int(j["order_job_count"] or 1),1))
   profit=revenue-material-machine-pack
   c.execute("""UPDATE print_jobs SET material_cost_cents=?,machine_cost_cents=?,
    packaging_cost_cents=?,profit_cents=? WHERE id=?""",(material,machine,pack,profit,job_id));c.commit()
  return {"material":material,"machine":machine,"packaging":pack,"revenue":revenue,"profit":profit}

 def recommendations(self):
  low=float(self.setting("filament_low_threshold_g","250") or 250)
  days=int(float(self.setting("filament_reorder_days","14") or 14))
  out=[]
  for s in self.spools():
   used=float(s["used_30d"] or 0)
   daily=used/30.0
   days_left=(float(s["remaining_g"])/daily) if daily>0 else None
   if float(s["remaining_g"])<=low:
    out.append({"severity":"high","text":"%s %s is low: %.0fg remaining."%(s["material"],s["color"] or "",s["remaining_g"])})
   elif days_left is not None and days_left<=days:
    out.append({"severity":"medium","text":"%s %s may run out in about %d days at current usage."%(s["material"],s["color"] or "",max(1,int(days_left)))})
  return out

 def business_profit_summary(self,days=None):
  with self.db.connect() as c:
   if days:
    modifier='-%d days'%int(days)
    paid=c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE datetime(paid_at)>=datetime('now',?)",(modifier,)).fetchone()[0]
    costs=c.execute("""SELECT COALESCE(SUM(material_cost_cents+machine_cost_cents+packaging_cost_cents),0)
      FROM print_jobs WHERE datetime(COALESCE(completed_at,started_at,created_at))>=datetime('now',?)""",(modifier,)).fetchone()[0]
    shipping=c.execute("""SELECT COALESCE(SUM(shipping_cost_cents),0) FROM fulfillments
      WHERE datetime(COALESCE(shipped_at,updated_at,created_at))>=datetime('now',?)""",(modifier,)).fetchone()[0]
    supplies=c.execute("""SELECT COALESCE(SUM((-st.quantity)*si.unit_cost_cents),0)
      FROM supply_transactions st JOIN supply_items si ON si.id=st.supply_id
      WHERE st.quantity<0 AND datetime(st.created_at)>=datetime('now',?)""",(modifier,)).fetchone()[0]
    jobs=c.execute("""SELECT COUNT(*) total,
      SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
      SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
      COALESCE(SUM(COALESCE(actual_minutes,estimated_minutes,0)),0) mins
      FROM print_jobs WHERE datetime(COALESCE(completed_at,started_at,created_at))>=datetime('now',?)""",(modifier,)).fetchone()
   else:
    paid=c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments").fetchone()[0]
    costs=c.execute("""SELECT COALESCE(SUM(material_cost_cents+machine_cost_cents+packaging_cost_cents),0)
      FROM print_jobs""").fetchone()[0]
    shipping=c.execute("SELECT COALESCE(SUM(shipping_cost_cents),0) FROM fulfillments").fetchone()[0]
    supplies=c.execute("""SELECT COALESCE(SUM((-st.quantity)*si.unit_cost_cents),0)
      FROM supply_transactions st JOIN supply_items si ON si.id=st.supply_id WHERE st.quantity<0""").fetchone()[0]
    jobs=c.execute("""SELECT COUNT(*) total,
      SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
      SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
      COALESCE(SUM(COALESCE(actual_minutes,estimated_minutes,0)),0) mins FROM print_jobs""").fetchone()
  net=int(paid or 0)-int(costs or 0)-int(shipping or 0)-int(supplies or 0)
  margin=(net*100.0/int(paid)) if int(paid or 0)>0 else 0.0
  total=int(jobs["total"] or 0);failed=int(jobs["failed"] or 0)
  return {"revenue_cents":int(paid or 0),"manufacturing_cost_cents":int(costs or 0),
          "shipping_cost_cents":int(shipping or 0),"supply_cost_cents":int(supplies or 0),
          "net_profit_cents":net,"margin_percent":margin,"jobs":total,
          "completed_jobs":int(jobs["completed"] or 0),"failed_jobs":failed,
          "failure_rate_percent":(failed*100.0/total) if total else 0.0,
          "print_hours":float(jobs["mins"] or 0)/60.0}

 def profitability(self):
  with self.db.connect() as c:
   return c.execute("""SELECT p.id,p.name,p.sku,
    COUNT(j.id) jobs,
    COALESCE(SUM(CASE WHEN j.status='completed' THEN 1 ELSE 0 END),0) completed,
    COALESCE(SUM(j.material_cost_cents+j.machine_cost_cents+j.packaging_cost_cents),0) costs_cents,
    COALESCE(SUM(j.profit_cents),0) profit_cents,
    COALESCE(AVG(CASE WHEN j.status='completed' THEN j.actual_minutes END),0) avg_minutes
    FROM products p LEFT JOIN print_jobs j ON j.product_id=p.id
    GROUP BY p.id ORDER BY profit_cents DESC,p.name COLLATE NOCASE""").fetchall()
