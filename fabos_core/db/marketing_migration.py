"""Reserved schema payload for marketing migration tooling."""
MARKETING_MIGRATION_SQL = """CREATE TABLE IF NOT EXISTS marketing_channels(
id TEXT PRIMARY KEY,name TEXT NOT NULL,channel_type TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
publish_mode TEXT NOT NULL DEFAULT 'manual',account_label TEXT,profile_url TEXT,webhook_url TEXT,
credential_ref TEXT,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS marketing_campaigns(
id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT,status TEXT NOT NULL DEFAULT 'draft',
start_at TEXT,end_at TEXT,budget_cents INTEGER NOT NULL DEFAULT 0,
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS marketing_posts(
id TEXT PRIMARY KEY,title TEXT,body TEXT NOT NULL DEFAULT '',product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
campaign_id TEXT REFERENCES marketing_campaigns(id) ON DELETE SET NULL,media_json TEXT NOT NULL DEFAULT '[]',
scheduled_at TEXT,status TEXT NOT NULL DEFAULT 'draft',
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS marketing_post_channels(
post_id TEXT NOT NULL REFERENCES marketing_posts(id) ON DELETE CASCADE,
channel_id TEXT NOT NULL REFERENCES marketing_channels(id) ON DELETE CASCADE,
status TEXT NOT NULL DEFAULT 'draft',published_at TEXT,external_id TEXT,error TEXT,
PRIMARY KEY(post_id,channel_id));
CREATE INDEX IF NOT EXISTS idx_marketing_posts_status ON marketing_posts(status,scheduled_at);
CREATE INDEX IF NOT EXISTS idx_marketing_posts_product ON marketing_posts(product_id);
CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_status ON marketing_campaigns(status);
CREATE TABLE IF NOT EXISTS marketing_sales_snapshots(
id TEXT PRIMARY KEY,channel_type TEXT NOT NULL,orders INTEGER NOT NULL DEFAULT 0,
revenue_cents INTEGER NOT NULL DEFAULT 0,period_start TEXT,period_end TEXT,
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
"""
