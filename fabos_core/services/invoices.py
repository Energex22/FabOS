import uuid,html
from datetime import datetime,timedelta
from pathlib import Path

class InvoiceService:
 SORT={
  "number":"i.invoice_number","customer":"customer_name COLLATE NOCASE",
  "order":"order_number","status":"i.status","total":"i.total_cents",
  "paid":"i.paid_cents","balance":"balance_cents","due":"i.due_at","created":"i.created_at"
 }
 def __init__(self,db,data_dir):
  self.db=db;self.export_dir=Path(data_dir)/"Invoices";self.export_dir.mkdir(parents=True,exist_ok=True)

 def _setting(self,c,key,default=""):
  row=c.execute("SELECT value FROM shop_settings WHERE key=?",(key,)).fetchone()
  return row["value"] if row else default

 def _next_number(self,c):
  prefix=(self._setting(c,"invoice_prefix","INV") or "INV")+"-"+datetime.now().strftime("%Y%m")+"-"
  row=c.execute("SELECT invoice_number FROM invoices WHERE invoice_number LIKE ? ORDER BY invoice_number DESC LIMIT 1",(prefix+"%",)).fetchone()
  n=1
  if row:
   try:n=int(row["invoice_number"].split("-")[-1])+1
   except ValueError:pass
  return prefix+("%04d"%n)

 def create_from_order(self,order_id,due_days=None):
  with self.db.connect() as c:
   existing=c.execute("SELECT id FROM invoices WHERE order_id=? AND status<>'void' ORDER BY created_at DESC LIMIT 1",(order_id,)).fetchone()
   if existing:return existing["id"],False
   order=c.execute("SELECT * FROM orders WHERE id=?",(order_id,)).fetchone()
   if not order:raise KeyError("Order not found.")
   iid=str(uuid.uuid4());subtotal=int(order["total_cents"] or 0)
   if due_days is None:due_days=int(float(self._setting(c,"invoice_due_days","14") or 14))
   tax_pct=float(self._setting(c,"default_tax_percent","0") or 0)
   tax=round(subtotal*tax_pct/100.0)
   total=subtotal+tax
   due=(datetime.now()+timedelta(days=int(due_days))).date().isoformat()
   c.execute("""INSERT INTO invoices(id,invoice_number,order_id,status,total_cents,paid_cents,due_at,subtotal_cents,tax_cents,shipping_cents,discount_cents)
    VALUES(?,?,?,'open',?,0,?,?,?,?,0)""",(iid,self._next_number(c),order_id,total,due,subtotal,tax,0))
   c.commit();return iid,True

 def reconcile(self,iid=None):
  with self.db.connect() as c:
   if iid:
    ids=[iid]
   else:
    ids=[r["id"] for r in c.execute("SELECT id FROM invoices")]
   for invoice_id in ids:
    inv=c.execute("SELECT total_cents,status FROM invoices WHERE id=?",(invoice_id,)).fetchone()
    if not inv:continue
    paid=int(c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=?",(invoice_id,)).fetchone()[0])
    if inv["status"]=="void":
     status="void"
    elif paid<=0:
     status="open"
    elif paid>=int(inv["total_cents"] or 0):
     status="paid"
    else:
     status="partial"
    c.execute("UPDATE invoices SET paid_cents=?,status=? WHERE id=?",(paid,status,invoice_id))
   c.commit()

 def finance_summary(self,days=None):
  self.reconcile()
  with self.db.connect() as c:
   if days:
    revenue=c.execute("""SELECT COALESCE(SUM(amount_cents),0) FROM payments
      WHERE datetime(paid_at)>=datetime('now',?)""",('-%d days'%int(days),)).fetchone()[0]
    paid_count=c.execute("""SELECT COUNT(DISTINCT invoice_id) FROM payments
      WHERE datetime(paid_at)>=datetime('now',?)""",('-%d days'%int(days),)).fetchone()[0]
   else:
    revenue=c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments").fetchone()[0]
    paid_count=c.execute("SELECT COUNT(*) FROM invoices WHERE status='paid'").fetchone()[0]
   row=c.execute("""SELECT
      COALESCE(SUM(CASE WHEN status IN ('open','partial') THEN MAX(total_cents-paid_cents,0) ELSE 0 END),0) outstanding_cents,
      COALESCE(SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END),0) partial_invoices,
      COALESCE(SUM(CASE WHEN status='open' THEN 1 ELSE 0 END),0) open_invoices
      FROM invoices WHERE status<>'void'""").fetchone()
   return {"paid_revenue_cents":int(revenue or 0),"outstanding_cents":int(row["outstanding_cents"] or 0),
           "paid_invoices":int(paid_count or 0),"partial_invoices":int(row["partial_invoices"] or 0),
           "open_invoices":int(row["open_invoices"] or 0)}

 def payment_history(self,limit=100,days=None):
  with self.db.connect() as c:
   where="WHERE datetime(p.paid_at)>=datetime('now',?)" if days else ""
   args=('-%d days'%int(days),int(limit)) if days else (int(limit),)
   return c.execute("""SELECT p.*,i.invoice_number,o.order_number,
      COALESCE(c.name,'No customer') customer_name
      FROM payments p
      JOIN invoices i ON i.id=p.invoice_id
      LEFT JOIN orders o ON o.id=i.order_id
      LEFT JOIN customers c ON c.id=o.customer_id
      %s ORDER BY p.paid_at DESC LIMIT ?"""%where,args).fetchall()

 def list(self,query="",status="All",sort="created",descending=True):
  self.reconcile()
  col=self.SORT.get(sort,"i.created_at");direction="DESC" if descending else "ASC"
  needle="%%%s%%"%query.strip();where=["(?='' OR i.invoice_number LIKE ? OR COALESCE(o.order_number,'') LIKE ? OR COALESCE(c.name,'') LIKE ?)"];args=[query.strip(),needle,needle,needle]
  if status and status!="All":where.append("i.status=?");args.append(status.lower())
  sql="""SELECT i.*,COALESCE(o.order_number,'—') order_number,COALESCE(c.name,'No customer') customer_name,
   (i.total_cents-i.paid_cents) balance_cents
   FROM invoices i LEFT JOIN orders o ON o.id=i.order_id LEFT JOIN customers c ON c.id=o.customer_id
   WHERE %s ORDER BY %s %s"""%(" AND ".join(where),col,direction)
  with self.db.connect() as c:return c.execute(sql,args).fetchall()

 def get(self,iid):
  self.reconcile(iid)
  with self.db.connect() as c:
   inv=c.execute("""SELECT i.*,o.order_number,o.quote_id,o.customer_id,c.name customer_name,c.email customer_email,c.phone customer_phone,
    (i.total_cents-i.paid_cents) balance_cents
    FROM invoices i LEFT JOIN orders o ON o.id=i.order_id LEFT JOIN customers c ON c.id=o.customer_id WHERE i.id=?""",(iid,)).fetchone()
   if not inv:raise KeyError("Invoice not found.")
   items=c.execute("SELECT * FROM quote_items WHERE quote_id=? ORDER BY rowid",(inv["quote_id"],)).fetchall() if inv["quote_id"] else []
   payments=c.execute("SELECT * FROM payments WHERE invoice_id=? ORDER BY paid_at DESC",(iid,)).fetchall()
   return inv,items,payments

 def update_charges(self,iid,tax_cents=0,shipping_cents=0,discount_cents=0,notes=""):
  with self.db.connect() as c:
   inv=c.execute("SELECT subtotal_cents FROM invoices WHERE id=?",(iid,)).fetchone()
   if not inv:raise KeyError("Invoice not found.")
   total=max(0,int(inv["subtotal_cents"] or 0)+int(tax_cents)+int(shipping_cents)-int(discount_cents))
   paid=int(c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=?",(iid,)).fetchone()[0])
   status="paid" if total>0 and paid>=total else ("partial" if paid>0 else "open")
   c.execute("""UPDATE invoices SET tax_cents=?,shipping_cents=?,discount_cents=?,notes=?,total_cents=?,paid_cents=?,status=? WHERE id=?""",
    (int(tax_cents),int(shipping_cents),int(discount_cents),notes,total,paid,status,iid));c.commit()

 def record_payment(self,iid,amount_cents,method="",reference="",notes=""):
  amount=int(amount_cents)
  if amount<=0:raise ValueError("Payment must be greater than $0.")
  with self.db.connect() as c:
   inv=c.execute("SELECT * FROM invoices WHERE id=?",(iid,)).fetchone()
   if not inv:raise KeyError("Invoice not found.")
   if inv["status"]=="void":raise ValueError("Cannot record payment on a void invoice.")
   c.execute("""INSERT INTO payments(id,invoice_id,amount_cents,method,reference,notes) VALUES(?,?,?,?,?,?)""",
    (str(uuid.uuid4()),iid,amount,method,reference,notes))
   paid=int(c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=?",(iid,)).fetchone()[0])
   status="paid" if paid>=int(inv["total_cents"] or 0) else "partial"
   c.execute("UPDATE invoices SET paid_cents=?,status=? WHERE id=?",(paid,status,iid))
   try:
    c.execute("""INSERT INTO activity_journal(id,event_type,title,detail,page,entity_id)
      VALUES(?,?,?,?,?,?)""",(str(uuid.uuid4()),'invoice.payment','Payment recorded',
      '$%.2f • %s'%(amount/100.0,method or 'Payment'),'Invoices',iid))
   except Exception:pass
   if status=="paid" and inv["order_id"]:
    fulfillment=c.execute("SELECT status FROM fulfillments WHERE order_id=?",(inv["order_id"],)).fetchone()
    if fulfillment and fulfillment["status"] in ("delivered","picked_up"):
     c.execute("UPDATE orders SET status='completed' WHERE id=?",(inv["order_id"],))
   c.commit()

 def void(self,iid):
  self.reconcile(iid)
  with self.db.connect() as c:
   inv=c.execute("SELECT paid_cents,status,total_cents FROM invoices WHERE id=?",(iid,)).fetchone()
   if not inv:raise KeyError("Invoice not found.")
   ledger_paid=int(c.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=?",(iid,)).fetchone()[0])
   if ledger_paid>0:
    raise ValueError("This invoice has $%.2f in recorded payments and cannot be voided until those payments are reversed/refunded."%(ledger_paid/100.0))
   c.execute("UPDATE invoices SET status='void',paid_cents=0 WHERE id=?",(iid,));c.commit()

 def export_html(self,iid):
  inv,items,payments=self.get(iid)
  item_rows=[]
  for x in items:
   line=int(x["quantity"] or 1)*int(x["unit_price_cents"] or 0)
   mat=("%s %s"%(x["material"] or "",x["color"] or "")).strip()
   item_rows.append("<tr><td>%s</td><td>%d</td><td>%s</td><td>$%.2f</td></tr>"%(
    html.escape(x["description"] or ""),int(x["quantity"] or 1),html.escape(mat),line/100.0))
  payment_rows="".join("<tr><td>%s</td><td>%s</td><td>$%.2f</td></tr>"%(
   html.escape(str(p["paid_at"])[:16]),html.escape(p["method"] or "Payment"),p["amount_cents"]/100.0) for p in payments) or "<tr><td colspan='3'>No payments recorded.</td></tr>"
  with self.db.connect() as c:
   shop_name=self._setting(c,"shop_name","WireVault FabOS")
   shop_email=self._setting(c,"shop_email","")
   shop_phone=self._setting(c,"shop_phone","")
   shop_address=self._setting(c,"shop_address","")
  seller="<h2>%s</h2><div class='muted'>%s%s%s</div>"%(html.escape(shop_name),
   html.escape(shop_address),("<br>"+html.escape(shop_email)) if shop_email else "",
   ("<br>"+html.escape(shop_phone)) if shop_phone else "")
  doc="""<!doctype html><html><head><meta charset='utf-8'><title>%s</title><style>
body{font-family:Arial,sans-serif;margin:42px;color:#222}h1{margin-bottom:4px}.muted{color:#666}
table{width:100%%;border-collapse:collapse;margin-top:20px}th,td{padding:9px;border-bottom:1px solid #ddd;text-align:left}
.summary{margin-left:auto;width:330px}.summary td{border:0}.total{font-size:20px;font-weight:bold}
@media print{button{display:none}}</style></head><body>%s<h1>%s</h1>
<div class='muted'>Order %s • Due %s</div><h3>Bill To</h3><div>%s<br>%s<br>%s</div>
<table><thead><tr><th>Item</th><th>Qty</th><th>Material</th><th>Line Total</th></tr></thead><tbody>%s</tbody></table>
<table class='summary'><tr><td>Subtotal</td><td>$%.2f</td></tr><tr><td>Tax</td><td>$%.2f</td></tr>
<tr><td>Shipping</td><td>$%.2f</td></tr><tr><td>Discount</td><td>-$%.2f</td></tr>
<tr class='total'><td>Total</td><td>$%.2f</td></tr><tr><td>Paid</td><td>$%.2f</td></tr>
<tr><td><b>Balance</b></td><td><b>$%.2f</b></td></tr></table>
<h3>Payments</h3><table><tbody>%s</tbody></table><p>%s</p><button onclick='window.print()'>Print Invoice</button></body></html>"""%(
 html.escape(inv["invoice_number"]),seller,html.escape(inv["invoice_number"]),html.escape(inv["order_number"] or "—"),html.escape(inv["due_at"] or "—"),
 html.escape(inv["customer_name"] or ""),html.escape(inv["customer_email"] or ""),html.escape(inv["customer_phone"] or ""),
 "".join(item_rows),inv["subtotal_cents"]/100.0,inv["tax_cents"]/100.0,inv["shipping_cents"]/100.0,inv["discount_cents"]/100.0,
 inv["total_cents"]/100.0,inv["paid_cents"]/100.0,inv["balance_cents"]/100.0,payment_rows,html.escape(inv["notes"] or ""))
  path=self.export_dir/(inv["invoice_number"]+".html");path.write_text(doc,encoding="utf-8");return path
