import json
import os
import tempfile
import unittest
import zipfile

from fabos_core.services.diagnostics import redact, DiagnosticsService


class DiagnosticsSecurityTests(unittest.TestCase):
    def test_redact_removes_sensitive_mapping_values(self):
        value = {
            "password_hash": "pbkdf2-secret",
            "api_key_ref": "octo-secret",
            "nested": {"access_token": "token-value"},
            "safe": "visible",
        }
        result = redact(value)
        self.assertEqual(result["password_hash"], "***REDACTED***")
        self.assertEqual(result["api_key_ref"], "***REDACTED***")
        self.assertEqual(result["nested"]["access_token"], "***REDACTED***")
        self.assertEqual(result["safe"], "visible")

    def test_redact_masks_sensitive_text(self):
        value = "Authorization: Bearer super-secret-token password=letmein token=abc123"
        result = redact(value)
        self.assertNotIn("super-secret-token", result)
        self.assertNotIn("letmein", result)
        self.assertNotIn("abc123", result)
        self.assertIn("***REDACTED***", result)

    def test_diagnostic_export_never_copies_raw_log(self):
        class Settings:
            data_dir = tempfile.gettempdir()
            log_dir = tempfile.gettempdir()

        class App:
            settings = Settings()

        app = App()
        log_path = os.path.join(tempfile.gettempdir(), "fabos.log")
        original = Settings.log_dir
        try:
            Settings.log_dir = os.path.dirname(log_path)
            with open(os.path.join(Settings.log_dir, "fabos.log"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"message": "ok", "token": "do-not-export"}) + "\n")
            app.shop_settings = type("ShopSettings", (), {"snapshot": lambda self: {"shop_name": "Fabvex", "api_secret": "hidden"}})()
            app.printer_automation = type("Printers", (), {"list": lambda self: [{"name": "Printer", "api_key_ref": "hidden-key"}]})()
            app.reliability = type("Reliability", (), {"health_safe": lambda self: []})()
            app.database = None
            service = DiagnosticsService(app)
            service.version_info = lambda: {"fabos_version": "test", "schema_version": 1}
            target = tempfile.mktemp(suffix=".zip")
            try:
                service.export(target)
                with zipfile.ZipFile(target) as archive:
                    log = archive.read("logs/fabos.log").decode("utf-8")
                    settings = archive.read("settings.json").decode("utf-8")
                    printers = archive.read("printers.json").decode("utf-8")
                self.assertNotIn("do-not-export", log)
                self.assertNotIn("hidden", settings)
                self.assertNotIn("hidden-key", printers)
            finally:
                try:
                    os.unlink(target)
                except OSError:
                    pass
        finally:
            Settings.log_dir = original
            try:
                os.unlink(log_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
