"""Marketing and channel orchestration for FabOS.

The service is deliberately provider-neutral: it owns campaigns, drafts, schedules,
channel connections, and normalized sales snapshots. Platform-specific publishers
can be added later without changing the core data model.
"""
import json
import uuid
from datetime import datetime, timezone


CHANNELS = ("website", "etsy", "ebay", "facebook", "instagram", "tiktok", "pinterest", "email", "other")
STATUSES = ("draft", "scheduled", "publishing", "published", "failed", "cancelled")


def _id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex)


class MarketingService:
    def __init__(self, database, products, shop_settings):
        self.db = database
        self.products = products
        self.shop_settings = shop_settings

    def channels(self, active_only=False):
        sql = "SELECT * FROM marketing_channels"
        args = ()
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY name"
        with self.db.connect() as c:
            return c.execute(sql, args).fetchall()

    def save_channel(self, channel_id=None, name="", channel_type="other", active=True,
                     publish_mode="manual", account_label="", profile_url="", webhook_url="",
                     credential_ref="", notes=""):
        if channel_type not in CHANNELS:
            raise ValueError("Unsupported marketing channel")
        channel_id = channel_id or _id("channel")
        with self.db.connect() as c:
            c.execute("""INSERT INTO marketing_channels
                (id,name,channel_type,active,publish_mode,account_label,profile_url,webhook_url,credential_ref,notes,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,channel_type=excluded.channel_type,
                active=excluded.active,publish_mode=excluded.publish_mode,account_label=excluded.account_label,
                profile_url=excluded.profile_url,webhook_url=excluded.webhook_url,credential_ref=excluded.credential_ref,
                notes=excluded.notes,updated_at=CURRENT_TIMESTAMP""",
                (channel_id, str(name).strip(), channel_type, int(bool(active)), publish_mode,
                 account_label, profile_url, webhook_url, credential_ref, notes))
            c.commit()
        return self.channel(channel_id)

    def channel(self, channel_id):
        with self.db.connect() as c:
            return c.execute("SELECT * FROM marketing_channels WHERE id=?", (channel_id,)).fetchone()

    def campaigns(self, status=None):
        sql = "SELECT * FROM marketing_campaigns"
        args = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY created_at DESC"
        with self.db.connect() as c:
            return c.execute(sql, args).fetchall()

    def save_campaign(self, campaign_id=None, name="", description="", status="draft",
                      start_at=None, end_at=None, budget_cents=0):
        campaign_id = campaign_id or _id("campaign")
        with self.db.connect() as c:
            c.execute("""INSERT INTO marketing_campaigns
                (id,name,description,status,start_at,end_at,budget_cents,updated_at)
                VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
                status=excluded.status,start_at=excluded.start_at,end_at=excluded.end_at,
                budget_cents=excluded.budget_cents,updated_at=CURRENT_TIMESTAMP""",
                (campaign_id, name.strip(), description, status, start_at, end_at, int(budget_cents or 0)))
            c.commit()
        return self.campaign(campaign_id)

    def campaign(self, campaign_id):
        with self.db.connect() as c:
            return c.execute("SELECT * FROM marketing_campaigns WHERE id=?", (campaign_id,)).fetchone()

    def create_post(self, body="", title="", product_id=None, campaign_id=None, channel_ids=None,
                    media_json=None, scheduled_at=None, status="draft"):
        if status not in STATUSES:
            raise ValueError("Invalid post status")
        post_id = _id("post")
        with self.db.connect() as c:
            c.execute("""INSERT INTO marketing_posts
                (id,title,body,product_id,campaign_id,media_json,scheduled_at,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                (post_id, title, body, product_id, campaign_id,
                 json.dumps(media_json or []), scheduled_at, status))
            for channel_id in channel_ids or []:
                if c.execute("SELECT 1 FROM marketing_channels WHERE id=?", (channel_id,)).fetchone():
                    c.execute("""INSERT OR IGNORE INTO marketing_post_channels(post_id,channel_id,status)
                                 VALUES(?,?,?)""", (post_id, channel_id, "draft"))
            c.commit()
        return self.post(post_id)

    def post(self, post_id):
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM marketing_posts WHERE id=?", (post_id,)).fetchone()
            if not row:
                return None
            channels = c.execute("""SELECT c.*,pc.status post_channel_status,pc.published_at,pc.external_id,pc.error
                                   FROM marketing_post_channels pc JOIN marketing_channels c ON c.id=pc.channel_id
                                   WHERE pc.post_id=? ORDER BY c.name""", (post_id,)).fetchall()
        return row, channels

    def posts(self, status=None, limit=100):
        sql = "SELECT * FROM marketing_posts"
        args = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY COALESCE(scheduled_at,created_at) DESC LIMIT ?"
        with self.db.connect() as c:
            return c.execute(sql, args + (max(1, min(int(limit), 500)),)).fetchall()

    def queue_due_posts(self):
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.db.connect() as c:
            rows = c.execute("""SELECT id FROM marketing_posts
                                WHERE status='scheduled' AND scheduled_at IS NOT NULL
                                AND datetime(scheduled_at)<=datetime(?)""", (now,)).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                c.executemany("UPDATE marketing_posts SET status='publishing',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                              [(item,) for item in ids])
                c.commit()
        return ids

    def record_result(self, post_id, channel_id, success, external_id=None, error=None):
        with self.db.connect() as c:
            status = "published" if success else "failed"
            c.execute("""UPDATE marketing_post_channels
                         SET status=?,published_at=CASE WHEN ?='published' THEN CURRENT_TIMESTAMP ELSE published_at END,
                             external_id=?,error=? WHERE post_id=? AND channel_id=?""",
                      (status, status, external_id, error, post_id, channel_id))
            remaining = c.execute("""SELECT COUNT(*) FROM marketing_post_channels
                                    WHERE post_id=? AND status NOT IN ('published')""", (post_id,)).fetchone()[0]
            failed = c.execute("""SELECT COUNT(*) FROM marketing_post_channels
                                  WHERE post_id=? AND status='failed'""", (post_id,)).fetchone()[0]
            if remaining == 0:
                post_status = "published"
            elif failed:
                post_status = "failed"
            else:
                post_status = "publishing"
            c.execute("UPDATE marketing_posts SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                      (post_status, post_id))
            c.commit()

    def sales_summary(self, days=30):
        with self.db.connect() as c:
            rows = c.execute("""SELECT checkout_channel channel,COUNT(*) orders,
                                       COALESCE(SUM(total_cents),0) revenue_cents
                                FROM orders
                                WHERE status NOT IN ('cancelled')
                                  AND date(created_at)>=date('now',?)
                                GROUP BY checkout_channel ORDER BY revenue_cents DESC""",
                             ("-%d days" % int(days),)).fetchall()
        return [dict(row) for row in rows]

    def dashboard(self):
        with self.db.connect() as c:
            campaigns = c.execute("SELECT COUNT(*) FROM marketing_campaigns WHERE status IN ('draft','active')").fetchone()[0]
            scheduled = c.execute("SELECT COUNT(*) FROM marketing_posts WHERE status='scheduled'").fetchone()[0]
            published = c.execute("SELECT COUNT(*) FROM marketing_posts WHERE status='published'").fetchone()[0]
            failed = c.execute("SELECT COUNT(*) FROM marketing_posts WHERE status='failed'").fetchone()[0]
            channels = c.execute("SELECT COUNT(*) FROM marketing_channels WHERE active=1").fetchone()[0]
        return {"active_campaigns": campaigns, "scheduled_posts": scheduled,
                "published_posts": published, "failed_posts": failed, "active_channels": channels,
                "sales": self.sales_summary(30)}
