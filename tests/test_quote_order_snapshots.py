import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.quotes import QuoteService


class QuoteOrderSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        self.quotes = QuoteService(self.db)
        with self.db.connect() as conn:
            conn.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)", ("customer-1", "Test Customer", "quote@example.com"))
            conn.execute("INSERT INTO products(id,sku,name,description,category,price_cents) VALUES(?,?,?,?,?,?)", ("product-1", "TEST-001", "Test Part", "Test", "Test", 2500))
            conn.execute("INSERT INTO product_variants(id,product_id,name,material,color,price_cents,estimated_minutes,estimated_filament_g,active) VALUES(?,?,?,?,?,?,?,?,?)", ("variant-1", "product-1", "PETG Black", "PETG", "Black", 3000, 35, 140, 1))
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_convert_to_order_copies_item_snapshot(self):
        quote_id = self.quotes.save(
            {"customer_id": "customer-1", "status": "approved"},
            [{
                "product_id": "product-1",
                "variant_id": "variant-1",
                "description": "Test Part · PETG Black",
                "quantity": 2,
                "unit_price_cents": 3000,
                "material": "PETG",
                "color": "Black",
                "estimated_minutes": 35,
                "estimated_filament_g": 140,
            }],
        )
        order_id = self.quotes.convert_to_order(quote_id)
        with self.db.connect() as conn:
            item = conn.execute("SELECT product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g FROM order_items WHERE order_id=?", (order_id,)).fetchone()
            quote_status = conn.execute("SELECT status FROM quotes WHERE id=?", (quote_id,)).fetchone()[0]
            order_status = conn.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()[0]
        self.assertIsNotNone(item)
        self.assertEqual(dict(item), {
            "product_id": "product-1",
            "variant_id": "variant-1",
            "description": "Test Part · PETG Black",
            "quantity": 2,
            "unit_price_cents": 3000,
            "material": "PETG",
            "color": "Black",
            "estimated_minutes": 35,
            "estimated_filament_g": 140.0,
        })
        self.assertEqual(quote_status, "approved")
        self.assertEqual(order_status, "pending")

    def test_convert_to_order_is_idempotent_without_duplicate_items(self):
        quote_id = self.quotes.save(
            {"customer_id": "customer-1"},
            [{"product_id": None, "description": "Custom item", "quantity": 1, "unit_price_cents": 4200}],
        )
        first = self.quotes.convert_to_order(quote_id)
        second = self.quotes.convert_to_order(quote_id)
        with self.db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id=?", (first,)).fetchone()[0]
        self.assertEqual(first, second)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
