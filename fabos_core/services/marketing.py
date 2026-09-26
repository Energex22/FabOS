"""Marketing and channel orchestration for FabOS.

The service is deliberately provider-neutral: it owns campaigns, drafts, schedules,
channel connections, and normalized sales snapshots. Platform-specific publishers
can be added later without changing the core data model.
"""
import json
import uuid
from datetime import datetime, timezone


CHANNELS = ("website", "etsy", "ebay", "facebook", "instagram", "tiktok", "pinterest", "email",
            "amazon", "shopify", "walmart", "google_business", "linkedin", "threads", "other")

PROVIDER_CATALOG = {
    "website": {"name": "FABVEX Website", "credential_env": None, "supports_publish": True, "supports_sales_import": True},
    "etsy": {"name": "Etsy", "credential_env": "FABOS_ETSY_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "ebay": {"name": "eBay", "credential_env": "FABOS_EBAY_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "facebook": {"name": "Facebook", "credential_env": "FABOS_META_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "instagram": {"name": "Instagram", "credential_env": "FABOS_META_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "tiktok": {"name": "TikTok", "credential_env": "FABOS_TIKTOK_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "pinterest": {"name": "Pinterest", "credential_env": "FABOS_PINTEREST_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "email": {"name": "Email", "credential_env": "FABOS_EMAIL_CREDENTIALS", "supports_publish": True, "supports_sales_import": False},
    "amazon": {"name": "Amazon Marketplace", "credential_env": "FABOS_AMAZON_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "shopify": {"name": "Shopify", "credential_env": "FABOS_SHOPIFY_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "walmart": {"name": "Walmart Marketplace", "credential_env": "FABOS_WALMART_CREDENTIALS", "supports_publish": True, "supports_sales_import": True},
    "google_business": {"name": "Google Business Profile", "credential_env": "FABOS_GOOGLE_BUSINESS_CREDENTIALS", "supports_publish": True, "supports_sales_import": False},
    "linkedin": {"name": "LinkedIn", "credential_env": "FABOS_LINKEDIN_CREDENTIALS", "supports_publish": True, "supports_sales_import": False},
    "threads": {"name": "Threads", "credential_env": "FABOS_META_CREDENTIALS", "supports_publish": True, "supports_sales_import": False},
    "other": {"name": "Other", "credential_env": None, "supports_publish": False, "supports_sales_import": True},
}

STATUSES = ("draft", "scheduled", "publishing", "published", "failed", "cancelled")


def _id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex)


class MarketingService:
    def __init__(self, database, products, shop_settings):
        self.db = database
        self.products = products
        self.shop_settings = shop_settings

    def provider_catalog(self):
        import os
        return {
            channel_type: dict(meta, credential_configured=bool(meta.get("credential_env") and os.environ.get(meta["credential_env"])))
            for channel_type, meta in PROVIDER_CATALOG.items()
        }

    def connection_status(self):
        providers = self.provider_catalog()
        rows = {row["channel_type"]: row for row in self.channels()}
        result = []
        for channel_type, meta in providers.items():
            row = rows.get(channel_type)
            configured = bool(row and (row["account_label"] or row["profile_url"] or row["credential_ref"]))
            credential_ready = bool(meta["credential_configured"] or channel_type == "website")
            result.append({
                "channel_type": channel_type,
                "name": meta["name"],
                "enabled": bool(row and int(row["active"])),
                "configured": configured,
                "credential_ready": credential_ready,
                "ready_for_api": bool(row and int(row["active"]) and configured and credential_ready and meta["supports_publish"]),
                "supports_publish": meta["supports_publish"],
                "supports_sales_import": meta["supports_sales_import"],
                "credential_env": meta["credential_env"],
            })
        return result

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

    def generate_post_variants(self, product_id):
        product = self.products.get(product_id) if self.products else None
        if not product:
            raise ValueError("Product not found")
        name = product["name"]
        description = (product["description"] or "").strip()
        price_cents = int(product["price_cents"] or 0) if "price_cents" in product.keys() else 0
        price = "$%.2f" % (price_cents / 100.0)
        base = description or ("A new FABVEX 3D-printed product: %s." % name)
        return {
            "facebook": {"title": name, "body": "New from FABVEX: %s\\n\\n%s\\n\\nAvailable for %s." % (name, base, price)},
            "instagram": {"title": name, "body": "%s ✨\\n\\n%s\\n\\n#FABVEX #3DPrinting #MadeToOrder" % (name, base)},
            "tiktok": {"title": name, "body": "Meet the %s from FABVEX. %s #FABVEX #3DPrinting" % (name, base)},
            "pinterest": {"title": name, "body": "%s — %s. FABVEX 3D-printed design." % (name, base)},
            "etsy": {"title": name, "body": base},
            "ebay": {"title": name, "body": base},
        }

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
                "sales": self.sales_summary(30), "external_sales": self.external_sales_summary(30)}


    def import_external_sale(self, channel_id, external_order_id, order_status="new",
                             customer_name="", customer_email="", total_cents=0, currency="USD",
                             items=None, raw=None, ordered_at=None):
        if not channel_id or not external_order_id:
            raise ValueError("channel_id and external_order_id are required")
        sale_id = _id("sale")
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM marketing_external_orders WHERE channel_id=? AND external_order_id=?",
                (channel_id, str(external_order_id))).fetchone()
            if existing:
                sale_id = existing["id"]
                conn.execute("""UPDATE marketing_external_orders SET order_status=?,customer_name=?,
                                customer_email=?,total_cents=?,currency=?,items_json=?,raw_json=?,
                                ordered_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                             (order_status, customer_name, customer_email, int(total_cents or 0), currency,
                              json.dumps(items or []), json.dumps(raw or {}), ordered_at, sale_id))
            else:
                conn.execute("""INSERT INTO marketing_external_orders
                    (id,channel_id,external_order_id,order_status,customer_name,customer_email,
                     total_cents,currency,items_json,raw_json,ordered_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (sale_id, channel_id, str(external_order_id), order_status, customer_name,
                     customer_email, int(total_cents or 0), currency, json.dumps(items or []),
                     json.dumps(raw or {}), ordered_at))
            conn.commit()
        return self.external_sale(sale_id)

    def external_sale(self, sale_id):
        with self.db.connect() as conn:
            return conn.execute("SELECT * FROM marketing_external_orders WHERE id=?", (sale_id,)).fetchone()

    def external_sales(self, channel_id=None, limit=100):
        sql = "SELECT * FROM marketing_external_orders"
        args = []
        if channel_id:
            sql += " WHERE channel_id=?"
            args.append(channel_id)
        sql += " ORDER BY COALESCE(ordered_at,imported_at) DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self.db.connect() as conn:
            return conn.execute(sql, tuple(args)).fetchall()

    def external_sales_summary(self, days=30):
        with self.db.connect() as conn:
            rows = conn.execute("""SELECT c.channel_type channel,COUNT(*) orders,
                                          COALESCE(SUM(s.total_cents),0) revenue_cents
                                   FROM marketing_external_orders s
                                   LEFT JOIN marketing_channels c ON c.id=s.channel_id
                                   WHERE s.order_status NOT IN ('cancelled','refunded')
                                     AND date(COALESCE(s.ordered_at,s.imported_at))>=date('now',?)
                                   GROUP BY c.channel_type ORDER BY revenue_cents DESC""",
                                ("-%d days" % int(days),)).fetchall()
        return [dict(row) for row in rows]
