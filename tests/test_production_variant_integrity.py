import tempfile
import unittest
import uuid
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.production import ProductionService


class ProductionVariantIntegrityTests(unittest.TestCase):
    def test_create_jobs_keeps_variants_separate(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            product_id = str(uuid.uuid4())
            variant_a = str(uuid.uuid4())
            variant_b = str(uuid.uuid4())
            customer_id = str(uuid.uuid4())
            quote_id = str(uuid.uuid4())
            order_id = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name,price_cents) VALUES(?,?,?)", (product_id, "Test Product", 1000))
                c.executemany(
                    "INSERT INTO product_variants(id,product_id,name,price_cents,active) VALUES(?,?,?,?,1)",
                    [(variant_a, product_id, "Black", 1100), (variant_b, product_id, "Green", 1200)],
                )
                c.execute("INSERT INTO customers(id,name) VALUES(?,?)", (customer_id, "Test Customer"))
                c.execute("INSERT INTO quotes(id,quote_number,customer_id,status) VALUES(?,?,?,'confirmed')", (quote_id, "Q-TEST", customer_id))
                c.executemany(
                    """INSERT INTO quote_items
                    (id,quote_id,product_id,variant_id,description,quantity,unit_price_cents)
                    VALUES(?,?,?,?,?,?,?)""",
                    [
                        (str(uuid.uuid4()), quote_id, product_id, variant_a, "Black", 2, 1100),
                        (str(uuid.uuid4()), quote_id, product_id, variant_b, "Green", 1, 1200),
                    ],
                )
                c.execute(
                    "INSERT INTO orders(id,order_number,customer_id,quote_id,status,total_cents) VALUES(?,?,?,?,?,?)",
                    (order_id, "O-TEST", customer_id, quote_id, "confirmed", 3400),
                )
                c.commit()

            created = ProductionService(db).create_jobs_from_order(order_id)
            self.assertEqual(len(created), 3)
            with db.connect() as c:
                rows = c.execute(
                    "SELECT variant_id FROM print_jobs WHERE order_id=? ORDER BY rowid",
                    (order_id,),
                ).fetchall()
            self.assertEqual([r["variant_id"] for r in rows].count(variant_a), 2)
            self.assertEqual([r["variant_id"] for r in rows].count(variant_b), 1)

    def test_create_jobs_is_idempotent_per_variant(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            product_id = str(uuid.uuid4())
            variant_id = str(uuid.uuid4())
            customer_id = str(uuid.uuid4())
            quote_id = str(uuid.uuid4())
            order_id = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name,price_cents) VALUES(?,?,?)", (product_id, "Test Product", 1000))
                c.execute("INSERT INTO product_variants(id,product_id,name,price_cents,active) VALUES(?,?,?,?,1)", (variant_id, product_id, "Black", 1100))
                c.execute("INSERT INTO customers(id,name) VALUES(?,?)", (customer_id, "Test Customer"))
                c.execute("INSERT INTO quotes(id,quote_number,customer_id,status) VALUES(?,?,?,'confirmed')", (quote_id, "Q-TEST", customer_id))
                c.execute(
                    """INSERT INTO quote_items
                    (id,quote_id,product_id,variant_id,description,quantity,unit_price_cents)
                    VALUES(?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), quote_id, product_id, variant_id, "Black", 2, 1100),
                )
                c.execute(
                    "INSERT INTO orders(id,order_number,customer_id,quote_id,status,total_cents) VALUES(?,?,?,?,?,?)",
                    (order_id, "O-TEST", customer_id, quote_id, "confirmed", 2200),
                )
                c.commit()

            svc = ProductionService(db)
            self.assertEqual(len(svc.create_jobs_from_order(order_id)), 2)
            self.assertEqual(len(svc.create_jobs_from_order(order_id)), 0)


if __name__ == "__main__":
    unittest.main()
