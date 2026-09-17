import unittest

from fabos_core.services.pricing_engine import PricingEngineService
from fabos_core.services.shop_settings import ShopSettingsService


class FakeSettings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class PricingEdgeCaseTests(unittest.TestCase):
    BASE = {
        "machine_hourly_cost": "10",
        "default_material_cost_per_g": "0.05",
        "filament_waste_percent": "0",
        "labor_hourly_rate": "0",
        "setup_labor_hourly_rate": "0",
        "post_process_labor_hourly_rate": "0",
        "qc_labor_hourly_rate": "0",
        "default_packaging_cost": "0",
        "overhead_percent": "0",
        "target_margin_percent": "0",
        "payment_fee_percent": "0",
        "payment_fee_fixed_cents": "0",
        "rush_multiplier": "1",
        "quantity_discount_enabled": "false",
        "quantity_discount_percent": "0",
    }

    def engine(self, **overrides):
        values = dict(self.BASE)
        values.update({k: str(v) for k, v in overrides.items()})
        return PricingEngineService(FakeSettings(values))

    def test_zero_work_produces_zero_unit_cost_and_price(self):
        result = self.engine().estimate(0, 0, 1)
        self.assertEqual(result["unit_cost"], 0)
        self.assertEqual(result["unit_price"], 0)
        self.assertEqual(result["total_price"], 0)

    def test_material_waste_is_applied_before_material_cost(self):
        result = self.engine(filament_waste_percent=25).estimate(0, 80, 1)
        self.assertEqual(result["material_grams"], 100.0)
        self.assertEqual(result["material_cost"], 5.0)

    def test_margin_is_applied_as_gross_margin_not_markup(self):
        result = self.engine(target_margin_percent=50).estimate(60, 0, 1)
        self.assertEqual(result["unit_cost"], 10.0)
        self.assertEqual(result["unit_price"], 20.0)

    def test_rush_does_not_change_non_rush_price(self):
        engine = self.engine(rush_multiplier=1.75)
        normal = engine.estimate(60, 0, 1)
        rush = engine.estimate(60, 0, 1, rush=True)
        self.assertEqual(normal["unit_price"], 10.0)
        self.assertEqual(rush["unit_price"], 17.5)

    def test_quantity_discount_only_applies_when_enabled_and_threshold_reached(self):
        engine = self.engine(quantity_discount_enabled="true", quantity_discount_percent=20)
        nine = engine.estimate(60, 0, 9)
        ten = engine.estimate(60, 0, 10)
        self.assertEqual(nine["unit_price"], 10.0)
        self.assertEqual(ten["unit_price"], 8.0)

    def test_payment_fee_is_included_in_breakdown(self):
        result = self.engine(payment_fee_percent=10, payment_fee_fixed_cents=50).estimate(60, 0, 1)
        self.assertEqual(result["pre_fee_price"], 10.0)
        self.assertEqual(result["payment_fee"], 1.5)
        self.assertEqual(result["unit_price"], 11.5)

    def test_invalid_negative_work_is_clamped(self):
        result = self.engine().estimate(-60, -100, 1, setup_minutes=-10, post_process_minutes=-5, qc_minutes=-1)
        self.assertEqual(result["machine_cost"], 0)
        self.assertEqual(result["material_grams"], 0)
        self.assertEqual(result["setup_cost"], 0)
        self.assertEqual(result["post_process_cost"], 0)
        self.assertEqual(result["qc_cost"], 0)


class ShopSettingsValidationTests(unittest.TestCase):
    def setUp(self):
        self.db = type("DB", (), {})()

    def test_known_keys_and_defaults_are_complete(self):
        defaults = ShopSettingsService.DEFAULTS
        self.assertIn("storefront_enabled", defaults)
        self.assertIn("storefront_ordering_enabled", defaults)
        self.assertIn("target_margin_percent", defaults)
        self.assertIn("payment_fee_percent", defaults)
        self.assertIn("shipping_mode", defaults)

    def test_numeric_constraints_reject_negative_values(self):
        self.assertIn("target_margin_percent", ShopSettingsService.NUMERIC_KEYS)
        self.assertIn("rush_multiplier", ShopSettingsService.NUMERIC_KEYS)

    def test_enum_sets_include_safe_operational_values(self):
        self.assertEqual(ShopSettingsService.ENUMS["shipping_mode"], {"calculated", "flat", "free"})
        self.assertEqual(ShopSettingsService.ENUMS["payment_provider"], {"stripe", "square", "none"})
        self.assertIn("published", ShopSettingsService.ENUMS["storefront_default_visibility"])


if __name__ == "__main__":
    unittest.main()
