import sqlite3
import tempfile
import unittest
from pathlib import Path

from fabos_core.services.products import ProductService


class SqliteTestDatabase:
    def __init__(self):
        self.path = Path(tempfile.mkstemp(suffix=".db")[1])
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                "CREATE TABLE products(id TEXT PRIMARY KEY, sku TEXT, name TEXT, category TEXT, description TEXT, "
                "designer TEXT, source_url TEXT, license_name TEXT, license_status TEXT, price_cents INTEGER, "
                "estimated_minutes INTEGER, estimated_filament_g REAL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE product_images(id TEXT PRIMARY KEY, product_id TEXT, path TEXT, source_url TEXT, "
                "attribution TEXT, is_primary INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE product_files(id TEXT PRIMARY KEY, product_id TEXT, path TEXT, filename TEXT, file_type TEXT)"
            )
            conn.commit()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def cleanup(self):
        try:
            self.path.unlink()
        except OSError:
            pass


class StorefrontPublicationEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.db = SqliteTestDatabase()
        self.service = ProductService(self.db)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO products(id,sku,name,license_status,price_cents) VALUES(?,?,?,?,?)",
                ("p1", "SKU-1", "Test Product", "verified", 2000),
            )
            conn.execute(
                "INSERT INTO product_files(id,product_id,path,filename,file_type) VALUES(?,?,?,?,?)",
                ("f1", "p1", "models/test.stl", "test.stl", "stl"),
            )
            conn.commit()

    def tearDown(self):
        self.db.cleanup()

    def test_published_product_requires_real_model_and_positive_price(self):
        self.service.save_storefront("p1", {"visibility": "published"})
        self.assertTrue(self.service.is_customer_eligible("p1"))

        with self.db.connect() as conn:
            conn.execute("UPDATE products SET price_cents=0 WHERE id='p1'")
            conn.commit()
        self.assertFalse(self.service.is_customer_eligible("p1"))
        with self.assertRaises(ValueError):
            self.service.save_storefront("p1", {"visibility": "published"})

    def test_blocked_license_cannot_be_published(self):
        with self.db.connect() as conn:
            conn.execute("UPDATE products SET license_status='blocked' WHERE id='p1'")
            conn.commit()
        self.assertFalse(self.service.is_customer_eligible("p1"))
        with self.assertRaises(ValueError):
            self.service.save_storefront("p1", {"visibility": "published"})

    def test_unpublished_product_never_enters_customer_catalog(self):
        self.service.save_storefront("p1", {"visibility": "draft"})
        self.assertEqual(self.service.customer_catalog(), [])

    def test_customer_catalog_requires_both_publication_and_readiness(self):
        self.service.save_storefront("p1", {"visibility": "published"})
        self.assertEqual(len(self.service.customer_catalog()), 1)
        with self.db.connect() as conn:
            conn.execute("DELETE FROM product_files WHERE product_id='p1'")
            conn.commit()
        self.assertEqual(self.service.customer_catalog(), [])


if __name__ == "__main__":
    unittest.main()
