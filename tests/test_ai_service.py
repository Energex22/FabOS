import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fabos_core.services.ai import AIService


class AIServiceTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE shop_settings(key TEXT PRIMARY KEY,value TEXT)")
        self.conn.executemany("INSERT INTO shop_settings(key,value) VALUES(?,?)", [
            ("ai_provider","openai_compatible"), ("ai_model","test-model"),
            ("ai_endpoint","https://example.invalid/v1"), ("ai_api_key_env","TEST_FABOS_KEY")
        ])
        self.conn.commit()
        self.db = SimpleNamespace(connect=lambda: self.conn)
        self.service = AIService(database=self.db)

    def tearDown(self):
        self.conn.close()

    def test_status_requires_configured_env_key(self):
        with patch.dict("os.environ", {"TEST_FABOS_KEY": "secret"}):
            status = self.service.status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["configured"])

    def test_chat_parses_openai_compatible_response(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"choices":[{"message":{"content":"Hello from FabOS"}}]}'
        with patch.dict("os.environ", {"TEST_FABOS_KEY": "secret"}), patch(
            "urllib.request.urlopen", return_value=FakeResponse()
        ):
            result = self.service.chat("Hello")
        self.assertEqual(result["response"], "Hello from FabOS")
        self.assertTrue(result["conversation_id"])

    def test_exposes_only_read_only_tools(self):
        names = [item["function"]["name"] for item in self.service.tool_definitions()]
        self.assertEqual(names, [
            "search_products", "get_product", "business_snapshot",
            "order_summary", "marketing_snapshot",
        ])
        self.assertNotIn("publish_post", names)
        self.assertNotIn("change_price", names)

if __name__ == "__main__":
    unittest.main()
