import uuid

class CustomerService:
    SORT_COLUMNS = {
        "name": "c.name COLLATE NOCASE",
        "email": "c.email COLLATE NOCASE",
        "phone": "c.phone COLLATE NOCASE",
        "quotes": "quote_count",
        "orders": "order_count",
        "value": "lifetime_value",
        "created": "c.created_at",
    }

    def __init__(self, database):
        self.database = database

    def list(self, query="", sort_column="name", descending=False):
        order = self.SORT_COLUMNS.get(sort_column, self.SORT_COLUMNS["name"])
        direction = "DESC" if descending else "ASC"
        like = "%{}%".format(query.strip())
        sql = """
            SELECT c.*,
              (SELECT COUNT(*) FROM quotes q WHERE q.customer_id=c.id) AS quote_count,
              (SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) AS order_count,
              COALESCE((SELECT SUM(o.total_cents) FROM orders o WHERE o.customer_id=c.id),0) AS lifetime_value
            FROM customers c
            WHERE (?='' OR c.name LIKE ? OR COALESCE(c.email,'') LIKE ? OR COALESCE(c.phone,'') LIKE ?)
            ORDER BY {} {}
        """.format(order, direction)
        with self.database.connect() as conn:
            return conn.execute(sql, (query.strip(), like, like, like)).fetchall()

    def get(self, customer_id):
        with self.database.connect() as conn:
            row=conn.execute("SELECT * FROM customers WHERE id=?",(customer_id,)).fetchone()
            if row is None: raise KeyError("Customer not found")
            return row

    def save(self, data, customer_id=None):
        name=(data.get("name") or "").strip()
        if not name: raise ValueError("Customer name is required.")
        values=(name,(data.get("email") or "").strip(),(data.get("phone") or "").strip(),(data.get("notes") or "").strip())
        with self.database.connect() as conn:
            if customer_id:
                conn.execute("UPDATE customers SET name=?,email=?,phone=?,notes=? WHERE id=?", values+(customer_id,))
            else:
                customer_id=str(uuid.uuid4())
                conn.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",(customer_id,)+values)
            conn.commit()
        return customer_id

    def delete(self, customer_id):
        with self.database.connect() as conn:
            linked=conn.execute("SELECT (SELECT COUNT(*) FROM quotes WHERE customer_id=?)+(SELECT COUNT(*) FROM orders WHERE customer_id=?)",(customer_id,customer_id)).fetchone()[0]
            if linked:
                raise ValueError("This customer has linked quotes or orders and cannot be deleted. Archive support will be added later.")
            conn.execute("DELETE FROM customers WHERE id=?",(customer_id,)); conn.commit()

    def activity(self, customer_id):
        with self.database.connect() as conn:
            quotes=conn.execute("SELECT quote_number,status,total_cents,created_at FROM quotes WHERE customer_id=? ORDER BY created_at DESC",(customer_id,)).fetchall()
            orders=conn.execute("SELECT order_number,status,total_cents,created_at FROM orders WHERE customer_id=? ORDER BY created_at DESC",(customer_id,)).fetchall()
        return quotes, orders
