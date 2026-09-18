import unittest
from fabos_core.services.error_log import ErrorLogService

class ErrorLogSecurityTests(unittest.TestCase):
    def test_log_redacts_credentials(self):
        import tempfile
        service = ErrorLogService(tempfile.mkdtemp())
        record = service.info(
            "request",
            "Authorization: Bearer super-secret password=hunter2",
            {"api_key": "private-key", "safe": "ok"},
        )
        text = str(record)
        self.assertNotIn("super-secret", text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("private-key", text)
        self.assertIn("***REDACTED***", text)
        recent = str(service.recent())
        self.assertNotIn("super-secret", recent)

if __name__ == "__main__":
    unittest.main()
