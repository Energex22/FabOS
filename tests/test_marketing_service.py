import sqlite3
import unittest
from types import SimpleNamespace

from fabos_core.services.marketing import MarketingService


class MarketingServiceTest(unittest.TestCase):
    def setUp(self):
        self.db = SimpleNamespace(connect=lambda: self.conn)
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
        CREATE TABLE marketing_channels(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,channel_type TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,publish_mode TEXT NOT NULL DEFAULT 'manual',
          account_label TEXT,profile_url TEXT,webhook_url TEXT,credential_ref TEXT,notes TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE marketing_campaigns(
          id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT,status TEXT NOT NULL DEFAULT 'draft',
          start_at TEXT,end_at TEXT,budget_cents INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE marketing_posts(
          id TEXT PRIMARY KEY,title TEXT,body TEXT NOT NULL DEFAULT '',product_id TEXT,campaign_id TEXT,
          media_json TEXT NOT NULL DEFAULT '[]',scheduled_at TEXT,status TEXT NOT NULL DEFAULT 'draft',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE marketing_post_channels(
          post_id TEXT NOT NULL,channel_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',
          published_at TEXT,external_id TEXT,error TEXT,PRIMARY KEY(post_id,channel_id));
        CREATE TABLE orders(
          id TEXT PRIMARY KEY,total_cents INTEGER,checkout_channel TEXT,status TEXT,created_at TEXT);
        """)
        self.service = MarketingService(self.db, None, None)

    def tearDown(self):
        self.conn.close()

    def test_channel_campaign_post_and_approval_flow(self):
        channel = self.service.save_channel(name="Etsy", channel_type="etsy")
        self.assertEqual(channel["channel_type"], "etsy")

        campaign = self.service.save_campaign(name="Launch")
        self.assertEqual(campaign["status"], "draft")

        post, channels = self.service.create_post(
            title="Launch", body="New product", campaign_id=campaign["id"],
            channel_ids=[channel["id"]]
        )
        self.assertEqual(post["status"], "draft")
        self.assertEqual(len(channels), 1)

        self.conn.execute("UPDATE marketing_posts SET status='scheduled' WHERE id=?", (post["id"],))
        self.conn.commit()
        self.service.queue_due_posts()  # future-dated/no scheduled_at means no-op
        self.assertEqual(self.service.post(post["id"])[0]["status"], "scheduled")

    def test_sales_summary_groups_channels(self):
        self.conn.executemany(
            "INSERT INTO orders(id,total_cents,checkout_channel,status,created_at) VALUES(?,?,?,?,datetime('now'))",
            [("1", 2500, "etsy", "completed"), ("2", 1000, "website", "completed")]
        )
        self.conn.commit()
        rows = {row["channel"]: row["revenue_cents"] for row in self.service.sales_summary(30)}
        self.assertEqual(rows["etsy"], 2500)
        self.assertEqual(rows["website"], 1000)


if __name__ == "__main__":
    unittest.main()
