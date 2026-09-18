import sqlite3
import tempfile
import unittest
from pathlib import Path
from fabos_core.services.customer_commerce import CustomerCommerceService


class _Db:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "fabos.db"
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE customers(id TEXT PRIMARY KEY,name TEXT,email TEXT,phone TEXT,notes TEXT);
            CREATE TABLE products(id TEXT PRIMARY KEY,name TEXT,price_cents INTEGER,estimated_minutes INTEGER,estimated_filament_g REAL);
            CREATE TABLE product_variants(id TEXT PRIMARY KEY,product_id TEXT,name TEXT,material TEXT,color TEXT,price_cents INTEGER,estimated_minutes INTEGER,estimated_filament_g REAL,active INTEGER);
            CREATE TABLE orders(
                id TEXT PRIMARY KEY, order_number TEXT UNIQUE, customer_id TEXT, quote_id TEXT,
                status TEXT, due_at TEXT, total_cents INTEGER, tax_cents INTEGER DEFAULT 0,
                shipping_cents INTEGER DEFAULT 0, shipping_address_json TEXT, checkout_notes TEXT,
                checkout_channel TEXT
            );
            CREATE TABLE order_items(
                id TEXT PRIMARY KEY, order_id TEXT, product_id TEXT, variant_id TEXT,
                description TEXT, quantity INTEGER, unit_price_cents INTEGER,
                material TEXT, color TEXT, estimated_minutes INTEGER, estimated_filament_g REAL
            );
            CREATE TABLE quotes(
                id TEXT PRIMARY KEY, quote_number TEXT UNIQUE, customer_id TEXT, status TEXT,
                total_cents INTEGER, expires_at TEXT, notes TEXT
            );
            CREATE TABLE quote_items(
                id TEXT PRIMARY KEY, quote_id TEXT, product_id TEXT, variant_id TEXT,
                description TEXT, quantity INTEGER, unit_price_cents INTEGER,
                material TEXT, color TEXT, estimated_minutes INTEGER, estimated_filament_g REAL
            );
            CREATE TABLE quote_price_snapshots(
                id TEXT PRIMARY KEY, quote_id TEXT, quote_item_id TEXT,
                unit_price_cents INTEGER, pricing_mode TEXT, calculation_json TEXT
            );
        """)
        conn.execute("INSERT INTO products VALUES(?,?,?,?,?)", ("product-1", "Cable Dock", 1800, 45, 80))
        conn.execute("INSERT INTO product_variants VALUES(?,?,?,?,?,?,?,?,?)", ("variant-black", "product-1", "Black PETG", "PETG", "Black", 2000, 50, 85, 1))
        conn.commit()
        conn.close()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def close(self):
        self.temp.cleanup()


class _Accounts:
    def __init__(self):
        self.user = {"id": "user-1", "active": 1, "account_type": "customer"}
        self.customer = {"id": "customer-1", "name": "Customer", "email": "customer@example.com"}

    def get_user(self, user_id):
        return self.user if user_id == self.user["id"] else None

    def customer_for_user(self, user_id):
        return self.customer if user_id == self.user["id"] else None


class _Products:
    def get(self, product_id):
        return {
            "id": product_id,
            "name": "Cable Dock",
            "price_cents": 1800,
            "estimated_minutes": 45,
            "estimated_filament_g": 80,
        } if product_id == "product-1" else None

    def is_customer_eligible(self, product_id):
        return product_id == "product-1"

    def variants(self, product_id):
        return [{
            "id": "variant-black",
            "name": "Black PETG",
            "material": "PETG",
            "color": "Black",
            "price_cents": 2000,
            "estimated_minutes": 50,
            "estimated_filament_g": 85,
            "active": 1,
        }]


class _Quotes:
    def __init__(self, database):
        self.database = database

    def save(self, data, items):
        quote_id = "quote-1"
        with self.database.connect() as conn:
            conn.execute(
                "INSERT INTO quotes VALUES(?,?,?,?,?,?,?)",
                (quote_id, "Q-202609-0001", data["customer_id"], data["status"], 4000, None, data.get("notes", "")),
            )
            for item in items:
                conn.execute(
                    "INSERT INTO quote_items VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    ("qi-1", quote_id, item["product_id"], item.get("variant_id"),
                     item["description"], item["quantity"], item["unit_price_cents"],
                     item.get("material", ""), item.get("color", ""),
                     item.get("estimated_minutes", 0), item.get("estimated_filament_g", 0)),
                )
            conn.execute(
                "INSERT INTO quote_price_snapshots VALUES(?,?,?,?,?,?)",
                ("snap-1", quote_id, "qi-1", items[0]["unit_price_cents"], "manual", None),
            )
            conn.commit()
        return quote_id

    def get_for_user(self, user_id, quote_id):
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
            items = conn.execute("SELECT * FROM quote_items WHERE quote_id=?", (quote_id,)).fetchall()
        return row, items


class _Settings:
    values = {
        "storefront_enabled": "true",
        "storefront_ordering_enabled": "true",
        "shipping_mode": "flat",
        "shipping_flat_cents": "600",
        "default_tax_percent": "8.25",
        "default_turnaround_days": "7",
        "minimum_order_cents": "0",
    }

    def get(self, key, default=None):
        return self.values.get(key, default)


class CustomerCommerceHardeningTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.service = CustomerCommerceService(
            self.db, _Accounts(), _Products(), _Quotes(self.db), _Settings()
        )

    def tearDown(self):
        self.db.close()

    def test_checkout_persists_order_items_and_uses_website_channel(self):
        row, items, subtotal, shipping, tax, total = self.service.create_order(
            "user-1",
            [{
                "productId": "product-1",
                "variantId": "variant-black",
                "quantity": 2,
                "configuration": {"material": "PETG", "color": "Black"},
            }],
            {"address": "123 Main St", "city": "Lenexa", "state": "KS", "zip": "66215"},
        )
        self.assertEqual(subtotal, 4000)
        self.assertEqual(shipping, 600)
        self.assertEqual(tax, 330)
        self.assertEqual(total, 4930)
        self.assertEqual(row["checkout_channel"], "website")
        with self.db.connect() as conn:
            saved = conn.execute("SELECT * FROM order_items WHERE order_id=?", (row["id"],)).fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["variant_id"], "variant-black")
        self.assertEqual(saved["unit_price_cents"], 2000)
        self.assertEqual(saved["quantity"], 2)

    def test_checkout_rejects_more_than_100_line_items(self):
        items = [{"productId": "product-1", "quantity": 1}] * 101
        with self.assertRaisesRegex(ValueError, "at most 100"):
            self.service.create_order(
                "user-1", items,
                {"address": "123 Main St", "city": "Lenexa", "state": "KS", "zip": "66215"},
            )

    def test_checkout_rejects_non_object_configuration(self):
        with self.assertRaisesRegex(ValueError, "configuration"):
            self.service.create_order(
                "user-1",
                [{"productId": "product-1", "quantity": 1, "configuration": "bad"}],
                {"address": "123 Main St", "city": "Lenexa", "state": "KS", "zip": "66215"},
            )


if __name__ == "__main__":
    unittest.main()
