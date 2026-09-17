import tempfile
import unittest
import uuid
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.products import ProductService


class ProductStorefrontPublicationTests(unittest.TestCase):
    def make(self, td, *, license_status="verified", price_cents=2500):
        db = Database(Path(td) / "storefront.sqlite3")
        db.initialize()
        migrate(db)
        product_id = str(uuid.uuid4())
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO products(id,name,license_status,price_cents) VALUES(?,?,?,?)",
                (product_id, "Test Product", license_status, price_cents),
            )
            conn.commit()
        service = ProductService(db)
        service._model_file_count = lambda conn, pid: 1 if pid == product_id else 0
        return service, product_id

    def test_published_product_requires_model_price_and_allowed_license(self):
        with tempfile.TemporaryDirectory() as raw:
            service, product_id = self.make(raw)
            state = service.storefront_publication_readiness(product_id)
            self.assertTrue(state["ready"])
            service.save_storefront(product_id, {"visibility": "published"})
            self.assertTrue(service.is_customer_eligible(product_id))

    def test_publication_rejects_missing_model(self):
        with tempfile.TemporaryDirectory() as raw:
            service, product_id = self.make(raw)
            service._model_file_count = lambda conn, pid: 0
            state = service.storefront_publication_readiness(product_id)
            self.assertFalse(state["ready"])
            self.assertTrue(any("model" in reason.lower() for reason in state["reasons"]))
            with self.assertRaises(ValueError):
                service.save_storefront(product_id, {"visibility": "published"})

    def test_publication_rejects_zero_price(self):
        with tempfile.TemporaryDirectory() as raw:
            service, product_id = self.make(raw, price_cents=0)
            state = service.storefront_publication_readiness(product_id)
            self.assertFalse(state["ready"])
            self.assertTrue(any("price" in reason.lower() for reason in state["reasons"]))

    def test_publication_rejects_blocked_license(self):
        with tempfile.TemporaryDirectory() as raw:
            service, product_id = self.make(raw, license_status="commercially_prohibited")
            state = service.storefront_publication_readiness(product_id)
            self.assertFalse(state["ready"])
            self.assertTrue(any("license" in reason.lower() for reason in state["reasons"]))
            with self.assertRaises(ValueError):
                service.save_storefront(product_id, {"visibility": "published"})


if __name__ == "__main__":
    unittest.main()
