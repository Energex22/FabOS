import uuid
from datetime import datetime

class CustomerUpdateService:
    def __init__(self,db):
        self.db=db

    def history(self,order_id):
        with self.db.connect() as c:
            return c.execute("""SELECT m.*,COALESCE(cu.name,'Customer') customer_name
                FROM customer_messages m
                LEFT JOIN customers cu ON cu.id=m.customer_id
                WHERE m.order_id=? ORDER BY m.created_at DESC""",(order_id,)).fetchall()

    def context(self,order_id):
        with self.db.connect() as c:
            o=c.execute("""SELECT o.*,COALESCE(c.name,'there') customer_name,
                COALESCE(c.email,'') customer_email,COALESCE(c.phone,'') customer_phone
                FROM orders o LEFT JOIN customers c ON c.id=o.customer_id WHERE o.id=?""",(order_id,)).fetchone()
            if not o:raise KeyError("Order not found.")
            f=c.execute("SELECT * FROM fulfillments WHERE order_id=?",(order_id,)).fetchone()
            inv=c.execute("""SELECT * FROM invoices WHERE order_id=? AND status<>'void'
                ORDER BY created_at DESC LIMIT 1""",(order_id,)).fetchone()
            jobs=c.execute("SELECT status FROM print_jobs WHERE order_id=?",(order_id,)).fetchall()
            qc=c.execute("SELECT status FROM qc_inspections WHERE order_id=?",(order_id,)).fetchall()
        return o,f,inv,jobs,qc

    def suggested_type(self,order_id):
        o,f,inv,jobs,qc=self.context(order_id)
        if o["status"]=="cancelled":return "cancelled"
        if f and f["status"]=="shipped":return "shipped"
        if f and f["status"]=="ready_for_pickup":return "ready_for_pickup"
        if f and f["status"]=="delivered":return "delivered"
        if f and f["status"]=="picked_up":return "picked_up"
        if inv and inv["status"]=="paid":return "payment_received"
        if inv and inv["status"] in ("open","partial"):return "invoice_ready"
        if qc and all(q["status"]=="passed" for q in qc):return "qc_passed"
        if jobs and any(j["status"]=="printing" for j in jobs):return "printing"
        if jobs:return "production"
        return "order_received"

    def generate(self,order_id,message_type=None):
        o,f,inv,jobs,qc=self.context(order_id)
        kind=message_type or self.suggested_type(order_id)
        name=o["customer_name"] or "there"
        number=o["order_number"]
        templates={
            "order_received":(
                "Order %s received"%number,
                "Hi %s, your order %s has been received and added to our production queue. "
                "I’ll keep you updated as it moves through printing, quality control, and fulfillment."%(name,number)),
            "production":(
                "Order %s is in production"%number,
                "Hi %s, a quick update on order %s: it is now in production. "
                "I’ll let you know when printing and quality control are complete."%(name,number)),
            "printing":(
                "Order %s is printing"%number,
                "Hi %s, order %s is currently printing. Once it finishes, it will go through quality control before being marked ready."%(name,number)),
            "qc_passed":(
                "Order %s passed quality control"%number,
                "Hi %s, order %s has finished production and passed quality control."%(name,number)),
            "invoice_ready":(
                "Invoice for order %s"%number,
                "Hi %s, your invoice for order %s is ready. The current balance is $%.2f."%(
                    name,number,((inv["total_cents"]-inv["paid_cents"])/100.0) if inv else 0)),
            "payment_received":(
                "Payment received for order %s"%number,
                "Hi %s, payment for order %s has been received. Thank you. "
                "I’ll update you again when the order is ready for pickup or ships."%(name,number)),
            "ready_for_pickup":(
                "Order %s is ready for pickup"%number,
                "Hi %s, order %s is finished and ready for pickup.%s"%(
                    name,number,(" "+f["notes"] if f and f["notes"] else ""))),
            "shipped":(
                "Order %s has shipped"%number,
                "Hi %s, order %s has shipped%s%s."%(
                    name,number,
                    (" with "+f["carrier"]) if f and f["carrier"] else "",
                    (" — tracking: "+f["tracking_number"]) if f and f["tracking_number"] else "")),
            "delivered":(
                "Order %s delivered"%number,
                "Hi %s, order %s is marked delivered. Thank you for your order."%(name,number)),
            "picked_up":(
                "Order %s picked up"%number,
                "Hi %s, order %s has been marked picked up. Thank you for your order."%(name,number)),
            "cancelled":(
                "Order %s cancelled"%number,
                "Hi %s, order %s has been cancelled. Please contact me if you have any questions."%(name,number)),
        }
        subject,body=templates.get(kind,templates["order_received"])
        with self.db.connect() as c:
            row=c.execute("SELECT value FROM shop_settings WHERE key='customer_update_signature'").fetchone()
        signature=(row["value"].strip() if row and row["value"] else "")
        if signature:body=body+"\n\n"+signature
        return {"message_type":kind,"subject":subject,"body":body,"email":o["customer_email"],"phone":o["customer_phone"]}

    def save(self,order_id,message_type,subject,body,channel="manual",status="draft"):
        with self.db.connect() as c:
            order=c.execute("SELECT customer_id FROM orders WHERE id=?",(order_id,)).fetchone()
            if not order:raise KeyError("Order not found.")
            mid=str(uuid.uuid4())
            sent=datetime.now().isoformat(timespec="seconds") if status=="sent" else None
            c.execute("""INSERT INTO customer_messages(
                id,order_id,customer_id,message_type,channel,subject,body,status,sent_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (mid,order_id,order["customer_id"],message_type,channel,subject,body,status,sent))
            c.commit()
            return mid

    def mark_sent(self,message_id,channel="manual"):
        with self.db.connect() as c:
            c.execute("""UPDATE customer_messages SET status='sent',channel=?,sent_at=CURRENT_TIMESTAMP
                         WHERE id=?""",(channel,message_id));c.commit()
