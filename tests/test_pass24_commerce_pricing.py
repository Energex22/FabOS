import unittest

from fabos_core.services.commerce_pricing import CommercePricingService


class StubProducts:
    def is_customer_eligible(self, product_id):
        return product_id in {"p1"}

    def variants(self, product_id):
        return []

    def get(self, product_id):
        rows = {
            "p1": {"id": "p1", "name": "Test Part", "price_cents": 1250, "estimated_filament_g": 100},
        }
        return rows.get(product_id)


class StubSettings:
    values = {
        "default_tax_percent": "8.25",
        "shipping_mode": "flat",
        "shipping_flat_cents": "599",
        "shipping_calculated_base_cents": "299",
        "shipping_calculated_per_kg_cents": "400",
        "currency_symbol": "$",
        "tax_state": "MO",
        "tax_rate_source": "state_default",
    }

    def get(self, key, default=None):
        return self.values.get(key, default)


class Pass24CommercePricingTests(unittest.TestCase):
    def setUp(self):
        self.service = CommercePricingService(StubProducts(), StubSettings())

    def test_server_side_price_tax_and_flat_shipping(self):
        result = self.service.estimate([{"product_id": "p1", "quantity": 2}])
        self.assertEqual(result["subtotal_cents"], 2500)
        self.assertEqual(result["tax_cents"], 206)
        self.assertEqual(result["shipping_cents"], 599)
        self.assertEqual(result["total_cents"], 3305)
        self.assertEqual(result["items"][0]["unit_price_cents"], 1250)
        self.assertEqual(result["tax_state"], "MO")
        self.assertEqual(result["tax_rate_source"], "state_default")

    def test_calculated_shipping_uses_server_known_weight(self):
        result = self.service.estimate(
            [{"product_id": "p1", "quantity": 2}], shipping_mode="calculated"
        )
        self.assertEqual(result["shipping_weight_g"], 200)
        self.assertEqual(result["shipping_cents"], 379)

    def test_missing_product_is_rejected(self):
        with self.assertRaises(KeyError):
            self.service.estimate([{"product_id": "missing", "quantity": 1}])


if __name__ == "__main__":
    unittest.main()
