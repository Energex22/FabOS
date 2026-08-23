import uuid
class SupplyService:
    def __init__(self,db):self.db=db

    def list(self,active_only=True):
        with self.db.connect() as c:
            return c.execute("""SELECT * FROM supply_items %s ORDER BY category,name"""%
                             ("WHERE active=1" if active_only else "")).fetchall()

    def create(self,name,category="Packaging",unit="ea",quantity=0,unit_cost_cents=0,low_threshold=0,notes=""):
        sid=str(uuid.uuid4())
        with self.db.connect() as c:
            c.execute("""INSERT INTO supply_items(id,name,category,unit,quantity,unit_cost_cents,low_threshold,notes)
              VALUES(?,?,?,?,?,?,?,?)""",(sid,name,category,unit,float(quantity),int(unit_cost_cents),float(low_threshold),notes))
            c.commit()
        return sid

    def adjust(self,sid,quantity,reference_type="manual",reference_id="",notes=""):
        qty=float(quantity)
        with self.db.connect() as c:
            c.execute("UPDATE supply_items SET quantity=MAX(0,quantity+?),updated_at=CURRENT_TIMESTAMP WHERE id=?",(qty,sid))
            c.execute("""INSERT INTO supply_transactions(id,supply_id,quantity,reference_type,reference_id,notes)
              VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),sid,qty,reference_type,reference_id,notes))
            c.commit()

    def low(self):
        with self.db.connect() as c:
            return c.execute("""SELECT * FROM supply_items WHERE active=1 AND low_threshold>0
              AND quantity<=low_threshold ORDER BY quantity""").fetchall()

    def total_value_cents(self):
        with self.db.connect() as c:
            return int(c.execute("SELECT COALESCE(SUM(quantity*unit_cost_cents),0) FROM supply_items WHERE active=1").fetchone()[0] or 0)
