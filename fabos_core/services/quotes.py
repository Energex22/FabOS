import json
import uuid
from datetime import date, timedelta


class QuoteService:
    SORT_COLUMNS={"number":"q.quote_number","customer":"customer_name COLLATE NOCASE","status":"q.status","total":"q.total_cents","expires":"q.expires_at","created":"q.created_at"}
    def __init__(self,database,pricing=None): self.database=database; self.pricing=pricing; self._ensure_snapshot_schema() if self.database is not None else None
    def _ensure_snapshot_schema(self):
        with self.database.connect() as conn:
            columns={str(row[1]) for row in conn.execute("PRAGMA table_info(quote_items)").fetchall()}
            if "variant_id" not in columns:
                conn.execute("ALTER TABLE quote_items ADD COLUMN variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL")
            conn.execute("CREATE TABLE IF NOT EXISTS quote_price_snapshots(id TEXT PRIMARY KEY,quote_id TEXT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,quote_item_id TEXT NOT NULL,unit_price_cents INTEGER NOT NULL,pricing_mode TEXT NOT NULL DEFAULT 'manual',calculation_json TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quote_price_snapshots_quote ON quote_price_snapshots(quote_id,created_at)")
            conn.commit()
    def list(self,query="",status="All",sort_column="created",descending=True,group="all"):
        col=self.SORT_COLUMNS.get(sort_column,"q.created_at"); direction="DESC" if descending else "ASC"; like="%%%s%%"%query.strip(); where=["(?='' OR q.quote_number LIKE ? OR COALESCE(c.name,'') LIKE ?)"]; args=[query.strip(),like,like]
        if group == "active": where.append("q.status IN ('draft','sent')")
        elif group == "history": where.append("q.status IN ('approved','declined','expired')")
        if status and status!="All": where.append("q.status=?"); args.append(status.lower())
        sql=("SELECT q.*,COALESCE(c.name,'No customer') customer_name,(SELECT COUNT(*) FROM quote_items qi WHERE qi.quote_id=q.id) item_count FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE "+" AND ".join(where)+" ORDER BY "+col+" "+direction)
        with self.database.connect() as conn: return conn.execute(sql,args).fetchall()
    def get(self,quote_id):
        with self.database.connect() as conn:
            row=conn.execute("SELECT q.*,COALESCE(c.name,'No customer') customer_name FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE q.id=?",(quote_id,)).fetchone()
            if not row: raise KeyError("Quote not found")
            items=conn.execute("SELECT qi.*,p.name product_name FROM quote_items qi LEFT JOIN products p ON p.id=qi.product_id WHERE qi.quote_id=? ORDER BY qi.rowid",(quote_id,)).fetchall()
        return row,items
    def list_for_user(self,user_id,query="",status="All",sort_column="created",descending=True,group="all"):
        with self.database.connect() as conn:
            linked=conn.execute("SELECT customer_id FROM customer_accounts WHERE user_id=?",(user_id,)).fetchone()
        if not linked:return []
        customer_id=linked[0]; col=self.SORT_COLUMNS.get(sort_column,"q.created_at"); direction="DESC" if descending else "ASC"; like="%%%s%%"%query.strip(); where=["q.customer_id=?","(?='' OR q.quote_number LIKE ? OR COALESCE(c.name,'') LIKE ?)"]; args=[customer_id,query.strip(),like,like]
        if group == "active": where.append("q.status IN ('draft','sent')")
        elif group == "history": where.append("q.status IN ('approved','declined','expired')")
        if status and status!="All": where.append("q.status=?"); args.append(status.lower())
        sql=("SELECT q.*,COALESCE(c.name,'No customer') customer_name,(SELECT COUNT(*) FROM quote_items qi WHERE qi.quote_id=q.id) item_count FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE "+" AND ".join(where)+" ORDER BY "+col+" "+direction)
        with self.database.connect() as conn:return conn.execute(sql,args).fetchall()
    def get_for_user(self,user_id,quote_id):
        with self.database.connect() as conn:
            linked=conn.execute("SELECT customer_id FROM customer_accounts WHERE user_id=?",(user_id,)).fetchone()
            if not linked:raise PermissionError("Quote access denied")
            row=conn.execute("SELECT q.*,COALESCE(c.name,'No customer') customer_name FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE q.id=? AND q.customer_id=?",(quote_id,linked[0])).fetchone()
            if not row:raise KeyError("Quote not found")
            items=conn.execute("SELECT qi.*,p.name product_name FROM quote_items qi LEFT JOIN products p ON p.id=qi.product_id WHERE qi.quote_id=? ORDER BY qi.rowid",(quote_id,)).fetchall()
        return row,items
    def next_number(self,conn):
        prefix="Q-"+date.today().strftime("%Y%m")+"-"; row=conn.execute("SELECT quote_number FROM quotes WHERE quote_number LIKE ? ORDER BY quote_number DESC LIMIT 1",(prefix+"%",)).fetchone(); seq=int(row[0].split("-")[-1])+1 if row else 1; return prefix+("%04d"%seq)
    def _resolve_items(self,items):
        resolved=[]
        for item in items:
            row=dict(item)
            if str(row.get("pricing_mode") or "").lower()=="calculated":
                if self.pricing is None:raise RuntimeError("Pricing service is required for calculated quote items")
                estimate=self.pricing.estimate(estimated_minutes=row.get("estimated_minutes",0),estimated_filament_g=row.get("estimated_filament_g",0),quantity=row.get("quantity",1),rush=bool(row.get("rush",False)),setup_minutes=row.get("setup_minutes",0),post_process_minutes=row.get("post_process_minutes",0),qc_minutes=row.get("qc_minutes",0))
                row["unit_price_cents"]=int(round(estimate["unit_price"]*100)); row["pricing_breakdown"]=estimate
            if int(row.get("unit_price_cents",0) or 0)<0:raise ValueError("Quote item price cannot be negative")
            resolved.append(row)
        return resolved
    def save(self,data,items,quote_id=None):
        if not data.get("customer_id"):raise ValueError("Select a customer.")
        if not items:raise ValueError("Add at least one quote item.")
        items=self._resolve_items(items); total=sum(int(i["quantity"])*int(i["unit_price_cents"]) for i in items)
        with self.database.connect() as conn:
            if quote_id:
                conn.execute("UPDATE quotes SET customer_id=?,status=?,total_cents=?,expires_at=?,notes=? WHERE id=?",(data["customer_id"],data.get("status","draft"),total,data.get("expires_at") or None,data.get("notes",""),quote_id)); conn.execute("DELETE FROM quote_items WHERE quote_id=?",(quote_id,))
            else:
                quote_id=str(uuid.uuid4()); conn.execute("INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,expires_at,notes) VALUES(?,?,?,?,?,?,?)",(quote_id,self.next_number(conn),data["customer_id"],data.get("status","draft"),total,data.get("expires_at") or None,data.get("notes","")))
            for i in items:
                item_id=str(uuid.uuid4()); conn.execute("INSERT INTO quote_items(id,quote_id,product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(item_id,quote_id,i.get("product_id"),i.get("variant_id"),i.get("description") or "Custom item",int(i.get("quantity",1)),int(i.get("unit_price_cents",0)),i.get("material",""),i.get("color",""),int(i.get("estimated_minutes") or 0),float(i.get("estimated_filament_g") or 0)))
                conn.execute("INSERT INTO quote_price_snapshots(id,quote_id,quote_item_id,unit_price_cents,pricing_mode,calculation_json) VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),quote_id,item_id,int(i.get("unit_price_cents",0)),str(i.get("pricing_mode") or "manual"),json.dumps(i.get("pricing_breakdown"),sort_keys=True) if i.get("pricing_breakdown") is not None else None))
            conn.commit()
        return quote_id
    def convert_to_order(self,quote_id):
        with self.database.connect() as conn:
            q=conn.execute("SELECT * FROM quotes WHERE id=?",(quote_id,)).fetchone()
            if not q:raise KeyError("Quote not found")
            existing=conn.execute("SELECT id FROM orders WHERE quote_id=?",(quote_id,)).fetchone()
            if existing:return existing[0]
            prefix="O-"+date.today().strftime("%Y%m")+"-"; row=conn.execute("SELECT order_number FROM orders WHERE order_number LIKE ? ORDER BY order_number DESC LIMIT 1",(prefix+"%",)).fetchone(); seq=int(row[0].split("-")[-1])+1 if row else 1; oid=str(uuid.uuid4())
            conn.execute("INSERT INTO orders(id,order_number,customer_id,quote_id,status,due_at,total_cents) VALUES(?,?,?,?,?,?,?)",(oid,prefix+("%04d"%seq),q["customer_id"],quote_id,"new",(date.today()+timedelta(days=7)).isoformat(),q["total_cents"])); conn.execute("UPDATE quotes SET status='approved' WHERE id=?",(quote_id,)); conn.commit()
        return oid
