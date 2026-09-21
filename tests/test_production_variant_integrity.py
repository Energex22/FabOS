import tempfile
import unittest
import uuid
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.production import ProductionService
from fabos_core.services.manufacturing import ManufacturingService
from fabos_core.services.orders import OrderService


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

    def test_additional_copies_preserve_variant(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            product_id = str(uuid.uuid4())
            variant_id = str(uuid.uuid4())
            order_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name,price_cents) VALUES(?,?,?)", (product_id, "Test Product", 1000))
                c.execute("INSERT INTO product_variants(id,product_id,name,price_cents,active) VALUES(?,?,?,?,1)", (variant_id, product_id, "Green", 1200))
                c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)", (order_id, "O-COPY", "in_production", 1200))
                c.execute(
                    "INSERT INTO print_jobs(id,order_id,product_id,variant_id,status,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?)",
                    (job_id, order_id, product_id, variant_id, "completed", 10, 5),
                )
                c.commit()

            created = ProductionService(db).queue_additional_copies(job_id, 2)
            self.assertEqual(len(created), 2)
            with db.connect() as c:
                rows = c.execute("SELECT variant_id,quantity FROM print_jobs WHERE id IN (?,?)", created).fetchall()
            self.assertEqual([r["variant_id"] for r in rows], [variant_id, variant_id])
            self.assertEqual([r["quantity"] for r in rows], [1, 1])

    def test_attachable_job_requires_matching_variant_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            product_id = str(uuid.uuid4())
            variant_a = str(uuid.uuid4())
            variant_b = str(uuid.uuid4())
            order_id = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name,price_cents) VALUES(?,?,?)", (product_id, "Test Product", 1000))
                c.executemany(
                    "INSERT INTO product_variants(id,product_id,name,price_cents,active) VALUES(?,?,?,?,1)",
                    [(variant_a, product_id, "Black", 1100), (variant_b, product_id, "Green", 1200)],
                )
                c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)", (order_id, "O-ATTACH", "in_production", 1100))
                c.execute(
                    "INSERT INTO print_jobs(id,order_id,product_id,variant_id,status) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), order_id, product_id, variant_a, "queued"),
                )
                c.commit()
            svc = ProductionService(db)
            self.assertIsNotNone(svc.find_attachable_job(order_id, product_id, variant_a))
            self.assertIsNone(svc.find_attachable_job(order_id, product_id, variant_b))
            self.assertIsNotNone(svc.find_attachable_job(order_id, product_id))

    def test_reprint_preserves_variant_and_printer_material_context(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            product_id = str(uuid.uuid4())
            variant_id = str(uuid.uuid4())
            order_id = str(uuid.uuid4())
            printer_id = str(uuid.uuid4())
            spool_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name,price_cents) VALUES(?,?,?)", (product_id, "Test Product", 1000))
                c.execute("INSERT INTO product_variants(id,product_id,name,price_cents,active) VALUES(?,?,?,?,1)", (variant_id, product_id, "Green", 1200))
                c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)", (order_id, "O-REPRINT", "qc", 1200))
                c.execute("INSERT INTO printers(id,name,status) VALUES(?,?,?)", (printer_id, "Test Printer", "idle"))
                c.execute("INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)", (spool_id, "PETG", "Green", 1000, 1000))
                c.execute("INSERT INTO print_jobs(id,order_id,product_id,variant_id,printer_id,spool_id,status,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?,?,?)",
                          (job_id, order_id, product_id, variant_id, printer_id, spool_id, "failed", 10, 5))
                c.commit()
            new_id = ManufacturingService(db).reprint(job_id)
            with db.connect() as c:
                row = c.execute("SELECT variant_id,printer_id,spool_id,status FROM print_jobs WHERE id=?", (new_id,)).fetchone()
            self.assertEqual(row["variant_id"], variant_id)
            self.assertEqual(row["printer_id"], printer_id)
            self.assertEqual(row["spool_id"], spool_id)
            self.assertEqual(row["status"], "scheduled")

    def test_order_lifecycle_allows_production_to_qc_to_ready(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            order_id = str(uuid.uuid4())
            user_id = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO users(id,username,password_hash,account_type,active) VALUES(?,?,?,?,1)", (user_id, "admin", "x", "administrator"))
                c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)", (order_id, "O-LIFE", "in_production", 1000))
                c.commit()
            service = OrderService(db)
            service.set_status(order_id, "qc", user_id)
            self.assertEqual(service.get(order_id)[0]["status"], "qc")
            service.set_status(order_id, "ready", user_id)
            self.assertEqual(service.get(order_id)[0]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
