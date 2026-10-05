import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.quotes import QuoteService
from fabos_core.services.orders import OrderService


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

    def test_quote_design_remains_visible_from_order_dossier(self):
        quote_id = self.quotes.save(
            {"customer_id": "customer-1", "status": "approved"},
            [{"product_id": None, "description": "Customer CAD design", "quantity": 1, "unit_price_cents": 6500}],
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO designs(id,product_id,name,current_version,notes) VALUES(?,?,?,?,?)",
                ("design-1", None, "Customer CAD", 1, "Generated customer design"),
            )
            conn.execute(
                "INSERT INTO design_versions(id,design_id,version,label,notes) VALUES(?,?,?,?,?)",
                ("version-1", "design-1", 1, "Generated", "Verified CAD artifact"),
            )
            conn.execute("INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)", (quote_id, "design-1"))
            conn.commit()

        order_id = self.quotes.convert_to_order(quote_id)
        dossier = OrderService(self.db).dossier(order_id)
        self.assertEqual(order_id, dossier["order"]["id"])
        self.assertEqual(len(dossier["designs"]), 1)
        self.assertEqual(dossier["designs"][0]["id"], "design-1")
        self.assertEqual(dossier["designs"][0]["design_version"], 1)
        self.assertEqual(dossier["designs"][0]["design_version_label"], "Generated")

    def test_quote_versions_record_each_saved_price_revision(self):
        quote_id = self.quotes.save(
            {"customer_id": "customer-1", "status": "draft", "notes": "Initial"},
            [{"product_id": None, "description": "Custom item", "quantity": 1, "unit_price_cents": 4200}],
        )
        self.quotes.save(
            {"customer_id": "customer-1", "status": "sent", "notes": "Final quote"},
            [{"product_id": None, "description": "Custom item", "quantity": 1, "unit_price_cents": 4750}],
            quote_id=quote_id,
        )
        versions = self.quotes.versions(quote_id)
        self.assertEqual([row["version"] for row in versions], [2, 1])
        self.assertEqual(versions[0]["status"], "sent")
        self.assertEqual(versions[0]["total_cents"], 4750)

    def test_quote_status_transition_rejects_unknown_status(self):
        quote_id = self.quotes.save(
            {"customer_id": "customer-1", "status": "draft"},
            [{"product_id": None, "description": "Custom item", "quantity": 1, "unit_price_cents": 4200}],
        )
        with self.assertRaises(ValueError):
            self.quotes.set_status(quote_id, "customer_approved_themselves")


if __name__ == "__main__":
    unittest.main()
