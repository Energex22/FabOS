import unittest
from pathlib import Path

from fabos_core.services.shop_settings import ShopSettingsService


class AdministrationSettingsTests(unittest.TestCase):
    def test_settings_cover_business_storefront_payments_and_reliability(self):
        defaults = ShopSettingsService.DEFAULTS
        for key in (
            "shop_name", "default_tax_percent", "machine_hourly_cost", "storefront_enabled",
            "custom_upload_max_mb", "payment_provider", "shipping_mode", "backup_enabled",
            "notification_order_received", "default_turnaround_days",
        ):
            self.assertIn(key, defaults)

    def test_setting_validation_rejects_unknown_and_invalid_values(self):
        class FakeDB:
            def connect(self):
                raise AssertionError("No database write should occur for invalid settings")
        service = ShopSettingsService(FakeDB())
        with self.assertRaises(KeyError):
            service.set_validated("not_a_real_setting", "x")
        with self.assertRaises(ValueError):
            service.set_validated("payment_provider", "unknown")
        with self.assertRaises(ValueError):
            service.set_validated("default_tax_percent", "101")
        with self.assertRaises(ValueError):
            service.set_validated("custom_upload_extensions", "exe,stl")

    def test_application_wires_settings_and_permission_services(self):
        text = (Path(__file__).resolve().parents[1] / "fabos_core" / "application.py").read_text(encoding="utf-8")
        self.assertIn("self.permissions=PermissionService(", text)
        self.assertIn("self.auth=AuthService(", text)
        self.assertIn("self.shop_settings=ShopSettingsService(", text)
        self.assertIn("self.customer_commerce=CustomerCommerceService(", text)

    def test_admin_api_is_registered_and_protected_by_administrator_dependency(self):
        root = Path(__file__).resolve().parents[1]
        api = (root / "fabos_core" / "services" / "admin_api.py").read_text(encoding="utf-8")
        http_api = (root / "fabos_core" / "api.py").read_text(encoding="utf-8")
        self.assertIn("/api/v1/admin/users", api)
        self.assertIn("/api/v1/admin/settings", api)
        self.assertIn("Depends(administrator_user)", api)
        self.assertIn("/api/v1/admin/permissions", api)
        self.assertIn("register_admin_routes", http_api)
        self.assertIn("register_admin_routes(app, get_application, administrator_user)", http_api)
        self.assertIn('"PUT", "DELETE"', http_api)


if __name__ == "__main__":
    unittest.main()
