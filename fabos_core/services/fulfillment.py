import uuid
from datetime import datetime

class FulfillmentService:
 def __init__(self,db):self.db=db

 def ensure(self,order_id,method="pickup"):
  with self.db.connect() as c:
   row=c.execute("SELECT * FROM fulfillments WHERE order_id=?",(order_id,)).fetchone()
   if row:return row["id"]
   if not c.execute("SELECT id FROM orders WHERE id=?",(order_id,)).fetchone():
    raise KeyError("Order not found.")
   fid=str(uuid.uuid4())
   c.execute("INSERT INTO fulfillments(id,order_id,method,status) VALUES(?,?,?,'pending')",
             (fid,order_id,method));c.commit();return fid

 def get_for_order(self,order_id):
  with self.db.connect() as c:return c.execute("SELECT * FROM fulfillments WHERE order_id=?",(order_id,)).fetchone()

 def save(self,order_id,method,status,carrier="",tracking="",weight_oz=None,
          shipping_cost_cents=0,destination="",notes="",length_in=None,width_in=None,height_in=None):
  fid=self.ensure(order_id,method);now=datetime.now().isoformat(timespec="seconds")
  shipped=now if status=="shipped" else None
  delivered=now if status=="delivered" else None
  picked=now if status=="picked_up" else None
  with self.db.connect() as c:
   c.execute("""UPDATE fulfillments SET method=?,status=?,carrier=?,tracking_number=?,
      package_weight_oz=?,shipping_cost_cents=?,destination=?,notes=?,
      package_length_in=?,package_width_in=?,package_height_in=?,
      shipped_at=COALESCE(?,shipped_at),delivered_at=COALESCE(?,delivered_at),
      picked_up_at=COALESCE(?,picked_up_at),updated_at=CURRENT_TIMESTAMP WHERE id=?""",
      (method,status,carrier,tracking,weight_oz,int(shipping_cost_cents),destination,notes,
       length_in,width_in,height_in,shipped,delivered,picked,fid))
   inv=c.execute("""SELECT id,subtotal_cents,tax_cents,discount_cents,paid_cents,status
      FROM invoices WHERE order_id=? AND status<>'void' ORDER BY created_at DESC LIMIT 1""",(order_id,)).fetchone()
   if inv:
    total=max(0,int(inv['subtotal_cents'] or 0)+int(inv['tax_cents'] or 0)+int(shipping_cost_cents)-int(inv['discount_cents'] or 0))
    new_status='paid' if int(inv['paid_cents'] or 0)>=total and total>0 else ('partial' if int(inv['paid_cents'] or 0)>0 else 'open')
    c.execute("UPDATE invoices SET shipping_cents=?,total_cents=?,status=? WHERE id=?",
              (int(shipping_cost_cents),total,new_status,inv['id']))
   if status=="shipped":
    c.execute("UPDATE orders SET status='shipped' WHERE id=?",(order_id,))
   elif status in ("delivered","picked_up"):
    inv=c.execute("""SELECT * FROM invoices WHERE order_id=? AND status<>'void'
                     ORDER BY created_at DESC LIMIT 1""",(order_id,)).fetchone()
    if inv and int(inv["paid_cents"] or 0)>=int(inv["total_cents"] or 0):
     c.execute("UPDATE orders SET status='completed' WHERE id=?",(order_id,))
    else:
     # Keep unpaid delivered/picked-up orders in History without pretending billing is complete.
     c.execute("UPDATE orders SET status='shipped' WHERE id=?",(order_id,))
   c.commit()
  return fid
