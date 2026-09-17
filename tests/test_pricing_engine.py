import unittest

from fabos_core.services.pricing_engine import PricingEngineService
from fabos_core.services.quotes import QuoteService


class FakeSettings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class PricingEngineTests(unittest.TestCase):
    def test_full_cost_model_includes_configured_cost_layers(self):
        settings = FakeSettings({
            "machine_hourly_cost": "12",
            "default_material_cost_per_g": "0.05",
            "filament_waste_percent": "10",
            "labor_hourly_rate": "20",
            "setup_labor_hourly_rate": "30",
            "post_process_labor_hourly_rate": "25",
            "qc_labor_hourly_rate": "20",
            "default_packaging_cost": "2",
            "overhead_percent": "10",
            "target_margin_percent": "50",
            "payment_fee_percent": "0",
            "payment_fee_fixed_cents": "0",
            "rush_multiplier": "1",
            "quantity_discount_enabled": "false",
        })
        result = PricingEngineService(settings).estimate(60, 100, 1, setup_minutes=10, post_process_minutes=20, qc_minutes=5)
        self.assertAlmostEqual(result["material_grams"], 110.0, places=2)
        self.assertEqual(result["material_cost"], 5.5)
        self.assertEqual(result["machine_cost"], 12.0)
        self.assertEqual(result["setup_cost"], 5.0)
        self.assertEqual(result["post_process_cost"], 8.33)
        self.assertEqual(result["qc_cost"], 1.67)
        self.assertEqual(result["packaging_cost"], 2.0)
        self.assertGreater(result["unit_price"], result["unit_cost"])

    def test_rush_and_quantity_discount_are_settings_driven(self):
        settings = FakeSettings({
            "machine_hourly_cost": "10", "default_material_cost_per_g": "0.05", "filament_waste_percent": "0",
            "labor_hourly_rate": "0", "default_packaging_cost": "0", "overhead_percent": "0",
            "target_margin_percent": "0", "payment_fee_percent": "0", "payment_fee_fixed_cents": "0",
            "rush_multiplier": "1.5", "quantity_discount_enabled": "true", "quantity_discount_percent": "10",
        })
        normal = PricingEngineService(settings).estimate(60, 100, 1)
        rush = PricingEngineService(settings).estimate(60, 100, 1, rush=True)
        bulk = PricingEngineService(settings).estimate(60, 100, 10)
        self.assertAlmostEqual(rush["unit_price"], normal["unit_price"] * 1.5, places=2)
        self.assertAlmostEqual(bulk["unit_price"], normal["unit_price"] * 0.9, places=2)

    def test_calculated_quote_item_uses_pricing_service(self):
        class FakePricing:
            def estimate(self, **kwargs):
                self.kwargs = kwargs
                return {"unit_price": 17.345, "total_price": 17.345}

        pricing = FakePricing()
        service = QuoteService(None, pricing)
        items = service._resolve_items([{
            "description": "Calculated part",
            "quantity": 2,
            "unit_price_cents": 0,
            "estimated_minutes": 90,
            "estimated_filament_g": 42.5,
            "pricing_mode": "calculated",
            "rush": True,
            "setup_minutes": 10,
            "post_process_minutes": 5,
            "qc_minutes": 3,
        }])
        self.assertEqual(items[0]["unit_price_cents"], 1734)
        self.assertEqual(pricing.kwargs["estimated_minutes"], 90)
        self.assertEqual(pricing.kwargs["estimated_filament_g"], 42.5)
        self.assertTrue(pricing.kwargs["rush"])


if __name__ == "__main__":
    unittest.main()
