class OrderService:
    """Order access and lifecycle boundary.

    Existing list/get/dossier behavior is preserved. New actor-aware methods make
    customer isolation and order lifecycle rules explicit without changing the
    underlying orders schema.
    """
    SORT_COLUMNS={"number":"o.order_number","customer":"customer_name COLLATE NOCASE","status":"o.status","due":"o.due_at","total":"o.total_cents","created":"o.created_at"}
    ORDER_TRANSITIONS={
        "pending": {"confirmed", "cancelled"},
        "confirmed": {"in_production", "cancelled"},
        "in_production": {"ready", "cancelled"},
        "ready": {"shipped", "completed", "cancelled"},
        "shipped": {"completed"},
        "completed": set(),
        "cancelled": set(),
    }
    TERMINAL_STATUSES={"completed","cancelled"}

    def __init__(self,database,accounts=None,permissions=None):
        self.database=database
        self.accounts=accounts
        self.permissions=permissions

    def list(self,query="",status="All",sort_column="created",descending=True,group="all"):
        col=self.SORT_COLUMNS.get(sort_column,"o.created_at"); direction="DESC" if descending else "ASC"; like="%%%s%%"%query.strip()
        where=["(?='' OR o.order_number LIKE ? OR COALESCE(c.name,'') LIKE ?)"]; args=[query.strip(),like,like]
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
                where.append("COALESCE(f.status)=?");args.append(requested)
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

    def _user(self,user_id):
        if not user_id:
            raise PermissionError("Authenticated user is required")
        if self.accounts is None:
            from fabos_core.services.accounts import AccountService
            self.accounts=AccountService(self.database)
        user=self.accounts.get_user(user_id)
        if not user or not user["active"]:
            raise PermissionError("Authenticated user is inactive or not found")
        return user

    def _require(self,user_id,permission):
        user=self._user(user_id)
        if self.permissions is None:
            from fabos_core.services.permissions import PermissionService
            self.permissions=PermissionService(self.database)
        self.permissions.require(user["account_type"],permission,user_id=user_id)
        return user

    def _customer_order_allowed(self,user_id,order_id):
        user=self._user(user_id)
        if user["account_type"] != "customer":
            return True
        customer=self.accounts.customer_for_user(user_id)
        if not customer:
            return False
        with self.database.connect() as conn:
            return bool(conn.execute("SELECT 1 FROM orders WHERE id=? AND customer_id=?",(order_id,customer["id"])).fetchone())

    def get_for_user(self,user_id,order_id):
        self._require(user_id,"order.read")
        if not self._customer_order_allowed(user_id,order_id):
            raise PermissionError("Order access denied")
        return self.get(order_id)

    def list_for_user(self,user_id,query="",status="All",sort_column="created",descending=True,group="all"):
        user=self._require(user_id,"order.read")
        if user["account_type"] != "customer":
            return self.list(query,status,sort_column,descending,group)
        customer=self.accounts.customer_for_user(user_id)
        if not customer:
            return []
        rows=self.list(query,status,sort_column,descending,group)
        customer_id=customer["id"]
        return [row for row in rows if row["customer_id"]==customer_id]

    def set_status(self,order_id,status,actor_user_id=None):
        user=self._require(actor_user_id,"order.manage")
        requested=(status or "").strip().lower()
        if requested not in self.ORDER_TRANSITIONS:
            raise ValueError("Unsupported order status")
        with self.database.connect() as conn:
            row=conn.execute("SELECT status FROM orders WHERE id=?",(order_id,)).fetchone()
            if not row: raise KeyError("Order not found")
            current=(row["status"] or "").strip().lower()
            if current==requested:
                return self.get(order_id)[0]
            allowed=self.ORDER_TRANSITIONS.get(current)
            if allowed is None:
                raise ValueError("Order has unsupported current status: %s" % current)
            if requested not in allowed:
                raise ValueError("Invalid order transition: %s -> %s" % (current,requested))
            conn.execute("UPDATE orders SET status=? WHERE id=?",(requested,order_id)); conn.commit()
        return self.get(order_id)[0]

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
