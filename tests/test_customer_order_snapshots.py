import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService
from fabos_core.services.customer_commerce import CustomerCommerceService
from fabos_core.services.quotes import QuoteService


class FakeProducts:
    def __init__(self):
        self.product = {"id": "product-1", "name": "Test Part", "price_cents": 2500, "estimated_minutes": 30, "estimated_filament_g": 120}
        self.variant = {"id": "variant-1", "name": "PETG Black", "material": "PETG", "color": "Black", "price_cents": 3000, "estimated_minutes": 35, "estimated_filament_g": 140, "active": 1}

    def get(self, product_id):
        return self.product if product_id == self.product["id"] else None

    def is_customer_eligible(self, product_id):
        return product_id == self.product["id"]

    def variants(self, product_id):
        return [self.variant] if product_id == self.product["id"] else []


class CustomerOrderSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.auth = AuthService(self.db, self.accounts)
        self.products = FakeProducts()
        self.quotes = QuoteService(self.db)
        self.shop_settings = {"storefront_enabled": "true", "storefront_ordering_enabled": "true", "default_tax_percent": "7", "shipping_mode": "calculated", "shipping_calculated_base_cents": "500", "shipping_calculated_per_kg_cents": "1000"}
        self.commerce = CustomerCommerceService(self.db, self.accounts, self.products, self.quotes, self.shop_settings, auth=self.auth)
        result = self.commerce.register_customer("Test Customer", "order@example.com", "password123")
        self.user_id = result["user"]["user"]["id"]
        with self.db.connect() as conn:
            conn.execute("INSERT INTO products(id,sku,name,description,category,price_cents) VALUES(?,?,?,?,?,?)", ("product-1","TEST-001","Test Part","Test","Test",2500))
            conn.execute("INSERT INTO product_variants(id,product_id,name,material,color,price_cents,estimated_minutes,estimated_filament_g,active) VALUES(?,?,?,?,?,?,?,?,?)", ("variant-1","product-1","PETG Black","PETG","Black",3000,35,140,1))
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_customer_order_persists_variant_and_pricing_snapshot(self):
        row, items, subtotal, shipping, tax, total = self.commerce.create_order(self.user_id, [{"productId": "product-1", "variantId": "variant-1", "quantity": 2}], {"address": "1 Main St", "city": "Testville", "state": "MO", "zip": "00000"})
        self.assertEqual(subtotal, 6000)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["variant_id"], "variant-1")
        self.assertEqual(items[0]["unit_price_cents"], 3000)
        self.assertEqual(items[0]["quantity"], 2)
        self.assertEqual(row["total_cents"], total)
        with self.db.connect() as conn:
            saved = conn.execute("SELECT product_id,variant_id,quantity,unit_price_cents,material,color FROM order_items WHERE order_id=?", (row["id"],)).fetchone()
        self.assertEqual(dict(saved), {"product_id": "product-1", "variant_id": "variant-1", "quantity": 2, "unit_price_cents": 3000, "material": "PETG", "color": "Black"})


if __name__ == "__main__":
    unittest.main()
