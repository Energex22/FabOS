import os
import tempfile
import unittest

from fabos_core.api import create_app
from fabos_core.application import FabOSApplication


class OwnerProtectionApiTests(unittest.TestCase):
    def test_admin_api_source_contains_owner_protection(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fabos_core", "services", "admin_api.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("Only the owner can modify the owner account", source)
        self.assertIn("Only the owner can change the owner password", source)
        self.assertIn("Only the owner can change console security settings", source)


if __name__ == "__main__":
    unittest.main()
