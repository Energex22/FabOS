class PriceHistoryService:
    """Read immutable product prices and purchase-time line-item snapshots."""

    def __init__(self, database):
        self.database = database
        self.ensure_schema()

    def ensure_schema(self):
        with self.database.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS product_price_history(
                    id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    old_price_cents INTEGER NOT NULL,
                    new_price_cents INTEGER NOT NULL,
                    change_reason TEXT,
                    changed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_product_price_history_product ON product_price_history(product_id,created_at);
                CREATE TABLE IF NOT EXISTS product_variant_price_history(
                    id TEXT PRIMARY KEY,
                    variant_id TEXT NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
                    old_price_cents INTEGER NOT NULL,
                    new_price_cents INTEGER NOT NULL,
                    change_reason TEXT,
                    changed_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_product_variant_price_history_variant ON product_variant_price_history(variant_id,created_at);
                CREATE TABLE IF NOT EXISTS order_items(
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
                    variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL,
                    description TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    unit_price_cents INTEGER NOT NULL DEFAULT 0,
                    material TEXT,
                    color TEXT,
                    estimated_minutes INTEGER,
                    estimated_filament_g REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
                CREATE TABLE IF NOT EXISTS quote_price_snapshots(
                    id TEXT PRIMARY KEY,
                    quote_id TEXT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                    quote_item_id TEXT NOT NULL,
                    unit_price_cents INTEGER NOT NULL,
                    pricing_mode TEXT NOT NULL DEFAULT 'manual',
                    calculation_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_quote_price_snapshots_quote ON quote_price_snapshots(quote_id,created_at);
                CREATE TRIGGER IF NOT EXISTS trg_product_price_history
                AFTER UPDATE OF price_cents ON products
                WHEN OLD.price_cents <> NEW.price_cents
                BEGIN
                    INSERT INTO product_price_history(id,product_id,old_price_cents,new_price_cents)
                    VALUES(lower(hex(randomblob(16))),NEW.id,OLD.price_cents,NEW.price_cents);
                END;
                CREATE TRIGGER IF NOT EXISTS trg_product_variant_price_history
                AFTER UPDATE OF price_cents ON product_variants
                WHEN OLD.price_cents <> NEW.price_cents
                BEGIN
                    INSERT INTO product_variant_price_history(id,variant_id,old_price_cents,new_price_cents)
                    VALUES(lower(hex(randomblob(16))),NEW.id,OLD.price_cents,NEW.price_cents);
                END;
                CREATE TRIGGER IF NOT EXISTS trg_order_price_snapshot
                AFTER INSERT ON orders
                BEGIN
                    INSERT INTO order_items(id,order_id,product_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g)
                    SELECT lower(hex(randomblob(16))),NEW.id,qi.product_id,qi.description,qi.quantity,qi.unit_price_cents,qi.material,qi.color,qi.estimated_minutes,qi.estimated_filament_g
                    FROM quote_items qi WHERE qi.quote_id=NEW.quote_id;
                END;
            """)
            conn.commit()

    def product(self, product_id, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM product_price_history WHERE product_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?", (product_id, limit)).fetchall()

    def variant(self, variant_id, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM product_variant_price_history WHERE variant_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?", (variant_id, limit)).fetchall()

    def order_items(self, order_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY rowid", (order_id,)).fetchall()

    def latest_product_price(self, product_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT new_price_cents FROM product_price_history WHERE product_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (product_id,)).fetchone()
