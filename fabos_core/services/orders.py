class OrderService:
    SORT_COLUMNS={"number":"o.order_number","customer":"customer_name COLLATE NOCASE","status":"o.status","due":"o.due_at","total":"o.total_cents","created":"o.created_at"}
    def __init__(self,database): self.database=database
    def list(self,query="",status="All",sort_column="created",descending=True,group="all"):
        col=self.SORT_COLUMNS.get(sort_column,"o.created_at"); direction="DESC" if descending else "ASC"; like="%%%s%%"%query.strip()
        where=["(?='' OR o.order_number LIKE ? OR COALESCE(c.name,'') LIKE ?)"]; args=[query.strip(),like,like]

        # Orders leave the active workspace once they are shipped. Delivered/picked-up,
        # completed and cancelled records remain in history.
        if group=="active":
            where.append("""o.status NOT IN ('completed','cancelled','shipped')
                AND COALESCE(f.status,'') NOT IN ('shipped','delivered','picked_up')""")
        elif group=="history":
            where.append("""(o.status IN ('completed','cancelled','shipped')
                OR COALESCE(f.status,'') IN ('shipped','delivered','picked_up'))""")

        if status and status!="All":
            requested=status.lower()
            if requested=='shipped':
                where.append("(o.status='shipped' OR COALESCE(f.status,'')='shipped')")
            elif requested in ('delivered','picked_up'):
                where.append("COALESCE(f.status,'')=?");args.append(requested)
            else:
                where.append("o.status=?");args.append(requested)

        sql=("SELECT o.*,COALESCE(c.name,'No customer') customer_name,"
             "COALESCE(q.quote_number,'') quote_number,COALESCE(f.status,'') fulfillment_status,"
             "COALESCE(f.method,'') fulfillment_method,COALESCE(f.carrier,'') carrier,"
             "COALESCE(f.tracking_number,'') tracking_number,"
             "CASE WHEN COALESCE(f.status,'') IN ('shipped','delivered','picked_up') "
             "THEN f.status ELSE o.status END display_status "
             "FROM orders o LEFT JOIN customers c ON c.id=o.customer_id "
             "LEFT JOIN quotes q ON q.id=o.quote_id "
             "LEFT JOIN fulfillments f ON f.order_id=o.id WHERE "+" AND ".join(where)+
             " ORDER BY "+col+" "+direction)
        with self.database.connect() as conn:return conn.execute(sql,args).fetchall()
    def get(self,order_id):
        with self.database.connect() as conn:
            row=conn.execute("SELECT o.*,COALESCE(c.name,'No customer') customer_name,COALESCE(q.quote_number,'') quote_number FROM orders o LEFT JOIN customers c ON c.id=o.customer_id LEFT JOIN quotes q ON q.id=o.quote_id WHERE o.id=?",(order_id,)).fetchone()
            if not row: raise KeyError("Order not found")
            items=conn.execute("SELECT qi.*,p.name product_name FROM quote_items qi LEFT JOIN products p ON p.id=qi.product_id WHERE qi.quote_id=?",(row["quote_id"],)).fetchall() if row["quote_id"] else []
        return row,items
    def set_status(self,order_id,status):
        with self.database.connect() as conn: conn.execute("UPDATE orders SET status=? WHERE id=?",(status,order_id)); conn.commit()

    def dossier(self, order_id):
        with self.database.connect() as conn:
            order=conn.execute("""SELECT o.*,COALESCE(c.name,'No customer') customer_name,
              COALESCE(c.email,'') customer_email,COALESCE(c.phone,'') customer_phone,
              COALESCE(q.quote_number,'') quote_number
              FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
              LEFT JOIN quotes q ON q.id=o.quote_id WHERE o.id=?""",(order_id,)).fetchone()
            if not order:raise KeyError("Order not found")
            items=conn.execute("""SELECT qi.*,p.name product_name FROM quote_items qi
              LEFT JOIN products p ON p.id=qi.product_id WHERE qi.quote_id=?""",
              (order["quote_id"],)).fetchall() if order["quote_id"] else []
            jobs=conn.execute("""SELECT j.*,COALESCE(p.name,'Custom Job') product_name,
              COALESCE(pr.name,'Unassigned') printer_name FROM print_jobs j
              LEFT JOIN products p ON p.id=j.product_id LEFT JOIN printers pr ON pr.id=j.printer_id
              WHERE j.order_id=? ORDER BY j.created_at""",(order_id,)).fetchall()
            qc=conn.execute("""SELECT q.*,COALESCE(p.name,'Custom Job') product_name FROM qc_inspections q
              LEFT JOIN print_jobs j ON j.id=q.print_job_id LEFT JOIN products p ON p.id=j.product_id
              WHERE q.order_id=? ORDER BY q.created_at""",(order_id,)).fetchall()
            invoices=conn.execute("""SELECT i.*,(i.total_cents-i.paid_cents) balance_cents
              FROM invoices i WHERE i.order_id=? ORDER BY i.created_at DESC""",(order_id,)).fetchall()
            payments=conn.execute("""SELECT p.*,i.invoice_number FROM payments p
              JOIN invoices i ON i.id=p.invoice_id WHERE i.order_id=? ORDER BY p.paid_at DESC""",(order_id,)).fetchall()
            fulfillment=conn.execute("SELECT * FROM fulfillments WHERE order_id=?",(order_id,)).fetchone()
        total_jobs=len(jobs);completed_jobs=sum(1 for j in jobs if j["status"]=="completed")
        qc_total=len(qc);qc_passed=sum(1 for q in qc if q["status"]=="passed")
        paid=sum(int(p["amount_cents"] or 0) for p in payments)
        active_invoice=next((i for i in invoices if i["status"]!="void"),None)
        if order["status"]=="cancelled":next_action="Cancelled"
        elif total_jobs==0:next_action="Create production jobs"
        elif completed_jobs<total_jobs:next_action="Finish production"
        elif qc_total==0 or qc_passed<qc_total:next_action="Complete QC"
        elif not active_invoice:next_action="Create invoice"
        elif int(active_invoice["balance_cents"] or 0)>0:next_action="Collect payment"
        elif not fulfillment:next_action="Set fulfillment"
        elif fulfillment["status"] not in ("delivered","picked_up"):next_action="Complete fulfillment"
        else:next_action="Complete order"
        return {"order":order,"items":items,"jobs":jobs,"qc":qc,"invoices":invoices,"payments":payments,
                "fulfillment":fulfillment,"total_jobs":total_jobs,"completed_jobs":completed_jobs,
                "qc_total":qc_total,"qc_passed":qc_passed,"paid_cents":paid,"next_action":next_action}

