class PriceHistoryService:
    """Read-only access to immutable product and order price history."""

    def __init__(self, database):
        self.database = database

    def product(self, product_id, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT * FROM product_price_history WHERE product_id=? ORDER BY created_at DESC LIMIT ?",
                (product_id, limit),
            ).fetchall()

    def variant(self, variant_id, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT * FROM product_variant_price_history WHERE variant_id=? ORDER BY created_at DESC LIMIT ?",
                (variant_id, limit),
            ).fetchall()

    def order_items(self, order_id):
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT * FROM order_items WHERE order_id=? ORDER BY rowid",
                (order_id,),
            ).fetchall()

    def latest_product_price(self, product_id):
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT new_price_cents FROM product_price_history WHERE product_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (product_id,),
            ).fetchone()
