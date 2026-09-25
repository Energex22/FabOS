import sqlite3
MIGRATIONS=[
(1,"""CREATE TABLE IF NOT EXISTS app_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(2,"""CREATE TABLE IF NOT EXISTS designs(id TEXT PRIMARY KEY,product_id TEXT REFERENCES products(id) ON DELETE SET NULL,name TEXT NOT NULL,current_version INTEGER NOT NULL DEFAULT 1,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS design_versions(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,version INTEGER NOT NULL,label TEXT,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(design_id,version));
CREATE TABLE IF NOT EXISTS design_assets(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,version_id TEXT REFERENCES design_versions(id),kind TEXT NOT NULL,original_name TEXT NOT NULL,stored_path TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL DEFAULT 0,width_mm REAL,depth_mm REAL,height_mm REAL,triangle_count INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS idx_design_hash ON design_assets(design_id,sha256);
CREATE TABLE IF NOT EXISTS print_profiles(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,name TEXT NOT NULL,material TEXT,nozzle_mm REAL DEFAULT .4,layer_height_mm REAL DEFAULT .2,infill_percent REAL DEFAULT 15,supports TEXT,slicer_profile_path TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(3,"""CREATE TABLE IF NOT EXISTS qc_inspections(id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(id) ON DELETE CASCADE,print_job_id TEXT REFERENCES print_jobs(id),status TEXT NOT NULL DEFAULT 'pending',checklist_json TEXT NOT NULL DEFAULT '[]',notes TEXT,photo_path TEXT,inspected_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS manufacturing_observations(id TEXT PRIMARY KEY,product_id TEXT REFERENCES products(id),print_job_id TEXT UNIQUE REFERENCES print_jobs(id),printer_id TEXT REFERENCES printers(id),estimated_minutes INTEGER,actual_minutes INTEGER,estimated_filament_g REAL,actual_filament_g REAL,success INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(4,"""ALTER TABLE print_jobs ADD COLUMN slicer_metadata_json TEXT;"""),(5,"""ALTER TABLE print_jobs ADD COLUMN octoprint_state TEXT;"""),(6,"""ALTER TABLE printers ADD COLUMN connection_mode TEXT NOT NULL DEFAULT 'simulation';"""),(7,"""ALTER TABLE printers ADD COLUMN simulation_progress REAL NOT NULL DEFAULT 0;"""),(8,"""ALTER TABLE printers ADD COLUMN nozzle_temp REAL;"""),(9,"""ALTER TABLE printers ADD COLUMN bed_temp REAL;"""),(10,"""ALTER TABLE printers ADD COLUMN last_seen_at TEXT;"""),(11,"""ALTER TABLE print_jobs ADD COLUMN failure_reason TEXT;"""),(12,"""ALTER TABLE print_jobs ADD COLUMN filament_deducted INTEGER NOT NULL DEFAULT 0;"""),(13,"""ALTER TABLE print_jobs ADD COLUMN material_cost_cents INTEGER NOT NULL DEFAULT 0;"""),(14,"""ALTER TABLE print_jobs ADD COLUMN machine_cost_cents INTEGER NOT NULL DEFAULT 0;"""),(15,"""ALTER TABLE print_jobs ADD COLUMN packaging_cost_cents INTEGER NOT NULL DEFAULT 0;"""),(16,"""ALTER TABLE print_jobs ADD COLUMN profit_cents INTEGER;"""),(17,"""CREATE TABLE IF NOT EXISTS shop_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('machine_hourly_cost','0.35');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('default_packaging_cost','0.50');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('target_margin_percent','60');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('filament_low_threshold_g','250');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('filament_reorder_days','14');"""),(18,"""CREATE TABLE IF NOT EXISTS inventory_transactions(id TEXT PRIMARY KEY,item_type TEXT NOT NULL,item_id TEXT NOT NULL,transaction_type TEXT NOT NULL,quantity REAL NOT NULL,unit TEXT,reference_type TEXT,reference_id TEXT,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),(19,"""ALTER TABLE printers ADD COLUMN octoprint_current_file TEXT;"""),(20,"""ALTER TABLE printers ADD COLUMN print_time_seconds REAL;"""),(21,"""ALTER TABLE printers ADD COLUMN print_time_left_seconds REAL;"""),(22,"""ALTER TABLE printers ADD COLUMN octoprint_state_text TEXT;"""),(23,"""ALTER TABLE invoices ADD COLUMN subtotal_cents INTEGER NOT NULL DEFAULT 0;"""),(24,"""ALTER TABLE invoices ADD COLUMN tax_cents INTEGER NOT NULL DEFAULT 0;"""),(25,"""ALTER TABLE invoices ADD COLUMN shipping_cents INTEGER NOT NULL DEFAULT 0;"""),(26,"""ALTER TABLE invoices ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0;"""),(27,"""ALTER TABLE invoices ADD COLUMN notes TEXT;"""),(28,"""CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,amount_cents INTEGER NOT NULL,method TEXT,reference TEXT,notes TEXT,paid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);"""),(29,"""CREATE TABLE IF NOT EXISTS fulfillments(id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,method TEXT NOT NULL DEFAULT 'pickup',status TEXT NOT NULL DEFAULT 'pending',carrier TEXT,tracking_number TEXT,package_weight_oz REAL,shipping_cost_cents INTEGER NOT NULL DEFAULT 0,destination TEXT,notes TEXT,shipped_at TEXT,delivered_at TEXT,picked_up_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fulfillment_order ON fulfillments(order_id);"""),(30,"""CREATE TABLE IF NOT EXISTS customer_messages(id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,message_type TEXT NOT NULL DEFAULT 'status_update',channel TEXT NOT NULL DEFAULT 'manual',subject TEXT,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',sent_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_customer_messages_order ON customer_messages(order_id);
CREATE INDEX IF NOT EXISTS idx_customer_messages_sent ON customer_messages(sent_at);"""),(31,"""INSERT OR IGNORE INTO shop_settings(key,value) VALUES('shop_name','WireVault FabOS'),('shop_owner_name',''),('shop_email',''),('shop_phone',''),('shop_address',''),('invoice_prefix','INV'),('invoice_due_days','14'),('default_tax_percent','0'),('quote_valid_days','14'),('currency_symbol','$'),('backup_retention','30'),('default_slicer','Cura'),('customer_update_signature','');"""),(32,"""ALTER TABLE design_assets ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;"""),(33,"""ALTER TABLE designs ADD COLUMN model_mode TEXT NOT NULL DEFAULT 'single';
CREATE TABLE IF NOT EXISTS design_model_parts(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,asset_id TEXT NOT NULL REFERENCES design_assets(id) ON DELETE CASCADE,part_name TEXT NOT NULL,quantity INTEGER NOT NULL DEFAULT 1,include_in_complete_set INTEGER NOT NULL DEFAULT 1,sort_order INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(design_id,asset_id));
CREATE INDEX IF NOT EXISTS idx_model_parts_design ON design_model_parts(design_id,sort_order);"""),(34,"""CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY,dedupe_key TEXT UNIQUE,severity TEXT NOT NULL DEFAULT 'info',title TEXT NOT NULL,body TEXT,page TEXT,entity_id TEXT,is_read INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read,created_at);
CREATE TABLE IF NOT EXISTS activity_journal(id TEXT PRIMARY KEY,event_type TEXT NOT NULL,title TEXT NOT NULL,detail TEXT,page TEXT,entity_id TEXT,undo_type TEXT,undo_payload_json TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_journal(created_at);
ALTER TABLE fulfillments ADD COLUMN package_length_in REAL;
ALTER TABLE fulfillments ADD COLUMN package_width_in REAL;
ALTER TABLE fulfillments ADD COLUMN package_height_in REAL;
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('catalog_view_mode','list'),('dashboard_auto_refresh_seconds','5'),('failed_print_waste_factor','0.50');"""),(35,"""CREATE TABLE IF NOT EXISTS gcode_verifications(id TEXT PRIMARY KEY,product_id TEXT REFERENCES products(id) ON DELETE CASCADE,asset_id TEXT REFERENCES design_assets(id) ON DELETE CASCADE,file_path TEXT NOT NULL,file_sha256 TEXT NOT NULL,printer_name TEXT,material TEXT,nozzle_temp REAL,bed_temp REAL,layer_height REAL,nozzle_mm REAL,min_x REAL,max_x REAL,min_y REAL,max_y REAL,estimated_minutes INTEGER,filament_g REAL,valid INTEGER NOT NULL DEFAULT 0,problems_json TEXT,verified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(file_path,file_sha256));
CREATE INDEX IF NOT EXISTS idx_gcode_verify_product ON gcode_verifications(product_id,verified_at);
CREATE TABLE IF NOT EXISTS supply_items(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL DEFAULT 'Packaging',unit TEXT NOT NULL DEFAULT 'ea',quantity REAL NOT NULL DEFAULT 0,unit_cost_cents INTEGER NOT NULL DEFAULT 0,low_threshold REAL NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_supply_active ON supply_items(active,category,name);
CREATE TABLE IF NOT EXISTS supply_transactions(id TEXT PRIMARY KEY,supply_id TEXT NOT NULL REFERENCES supply_items(id) ON DELETE CASCADE,quantity REAL NOT NULL,reference_type TEXT,reference_id TEXT,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_supply_tx_item ON supply_transactions(supply_id,created_at);
CREATE TABLE IF NOT EXISTS app_runtime_state(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('auto_backup_on_shutdown','1'),('crash_recovery_enabled','1'),('diagnostic_log_retention_days','30'),('beta_channel','1');"""),(36,"""ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN account_type TEXT NOT NULL DEFAULT 'administrator';
ALTER TABLE users ADD COLUMN updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE users ADD COLUMN last_login_at TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL AND email<>'';
CREATE TABLE IF NOT EXISTS customer_accounts(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,customer_id TEXT NOT NULL UNIQUE REFERENCES customers(id) ON DELETE CASCADE,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS employee_profiles(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,department TEXT,position TEXT,employment_status TEXT NOT NULL DEFAULT 'active',metadata_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_customer_accounts_customer ON customer_accounts(customer_id);
CREATE INDEX IF NOT EXISTS idx_employee_profiles_status ON employee_profiles(employment_status);
UPDATE users SET account_type=CASE WHEN lower(COALESCE(role,'')) IN ('owner','admin','administrator') THEN 'administrator' WHEN lower(COALESCE(role,'')) IN ('employee','staff') THEN 'employee' WHEN lower(COALESCE(role,''))='customer' THEN 'customer' ELSE 'administrator' END;"""),(37,"""CREATE TABLE IF NOT EXISTS permissions(key TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT);
CREATE TABLE IF NOT EXISTS role_permissions(account_type TEXT NOT NULL,permission TEXT NOT NULL REFERENCES permissions(key) ON DELETE CASCADE,PRIMARY KEY(account_type,permission));
CREATE TABLE IF NOT EXISTS user_permissions(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,permission TEXT NOT NULL REFERENCES permissions(key) ON DELETE CASCADE,allowed INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(user_id,permission));
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission ON role_permissions(permission);
CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON user_permissions(user_id);"""),(38,"""CREATE TABLE IF NOT EXISTS auth_sessions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,token_hash TEXT UNIQUE NOT NULL,expires_at TEXT NOT NULL,revoked_at TEXT,ip_address TEXT,user_agent TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id,revoked_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);
CREATE TABLE IF NOT EXISTS password_reset_tokens(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,token_hash TEXT UNIQUE NOT NULL,expires_at TEXT NOT NULL,used_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id,used_at);"""),
(39,"""ALTER TABLE orders ADD COLUMN tax_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN shipping_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN shipping_address_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE orders ADD COLUMN checkout_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN checkout_channel TEXT NOT NULL DEFAULT 'internal';
CREATE INDEX IF NOT EXISTS idx_orders_checkout_channel ON orders(checkout_channel);"""),
(40,"""UPDATE users SET role=CASE WHEN account_type='administrator' THEN role ELSE account_type END WHERE lower(COALESCE(role,''))='owner' AND lower(COALESCE(account_type,''))<>'administrator';
CREATE TRIGGER IF NOT EXISTS trg_users_default_role_guard AFTER INSERT ON users
WHEN lower(COALESCE(NEW.role,''))='owner' AND lower(COALESCE(NEW.account_type,''))<>'administrator'
BEGIN
    UPDATE users SET role=NEW.account_type,updated_at=CURRENT_TIMESTAMP WHERE id=NEW.id;
END;"""),
(41,"""CREATE TABLE IF NOT EXISTS order_items(id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,product_id TEXT REFERENCES products(id) ON DELETE SET NULL,variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL,description TEXT NOT NULL,quantity INTEGER NOT NULL DEFAULT 1,unit_price_cents INTEGER NOT NULL DEFAULT 0,material TEXT,color TEXT,estimated_minutes INTEGER,estimated_filament_g REAL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);"""),
(42,"""ALTER TABLE quote_items ADD COLUMN variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL;"""),
(43,"""ALTER TABLE print_jobs ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1;"""),
(44,"""ALTER TABLE print_jobs ADD COLUMN variant_id TEXT REFERENCES product_variants(id) ON DELETE SET NULL;"""),
(45,"""CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_invoice_reference ON payments(invoice_id,reference) WHERE reference IS NOT NULL AND reference<>'';"""),

(46,"""CREATE TABLE IF NOT EXISTS marketing_channels(id TEXT PRIMARY KEY,name TEXT NOT NULL,channel_type TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,publish_mode TEXT NOT NULL DEFAULT 'manual',account_label TEXT,profile_url TEXT,webhook_url TEXT,credential_ref TEXT,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS marketing_campaigns(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT,status TEXT NOT NULL DEFAULT 'draft',start_at TEXT,end_at TEXT,budget_cents INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS marketing_posts(id TEXT PRIMARY KEY,title TEXT,body TEXT NOT NULL DEFAULT '',product_id TEXT REFERENCES products(id) ON DELETE SET NULL,campaign_id TEXT REFERENCES marketing_campaigns(id) ON DELETE SET NULL,media_json TEXT NOT NULL DEFAULT '[]',scheduled_at TEXT,status TEXT NOT NULL DEFAULT 'draft',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS marketing_post_channels(post_id TEXT NOT NULL REFERENCES marketing_posts(id) ON DELETE CASCADE,channel_id TEXT NOT NULL REFERENCES marketing_channels(id) ON DELETE CASCADE,status TEXT NOT NULL DEFAULT 'draft',published_at TEXT,external_id TEXT,error TEXT,PRIMARY KEY(post_id,channel_id));
CREATE INDEX IF NOT EXISTS idx_marketing_posts_status ON marketing_posts(status,scheduled_at);
CREATE INDEX IF NOT EXISTS idx_marketing_posts_product ON marketing_posts(product_id);
CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_status ON marketing_campaigns(status);
CREATE TABLE IF NOT EXISTS marketing_sales_snapshots(id TEXT PRIMARY KEY,channel_type TEXT NOT NULL,orders INTEGER NOT NULL DEFAULT 0,revenue_cents INTEGER NOT NULL DEFAULT 0,period_start TEXT,period_end TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('marketing_enabled','true'),('marketing_require_approval','true'),('marketing_default_publish_mode','manual'),('marketing_timezone','America/Chicago');
INSERT OR IGNORE INTO marketing_channels(id,name,channel_type,active,publish_mode) VALUES
('channel_website','FABVEX Website','website',1,'api'),('channel_etsy','Etsy', 'etsy',0,'api'),('channel_ebay','eBay','ebay',0,'api'),('channel_facebook','Facebook','facebook',0,'api'),('channel_instagram','Instagram','instagram',0,'api'),('channel_tiktok','TikTok','tiktok',0,'api'),('channel_pinterest','Pinterest','pinterest',0,'api');"""),

(47,"""CREATE TABLE IF NOT EXISTS marketing_external_orders(id TEXT PRIMARY KEY,channel_id TEXT REFERENCES marketing_channels(id) ON DELETE SET NULL,external_order_id TEXT NOT NULL,order_status TEXT NOT NULL DEFAULT 'new',customer_name TEXT,customer_email TEXT,total_cents INTEGER NOT NULL DEFAULT 0,currency TEXT NOT NULL DEFAULT 'USD',items_json TEXT NOT NULL DEFAULT '[]',raw_json TEXT NOT NULL DEFAULT '{}',ordered_at TEXT,imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS idx_marketing_external_order ON marketing_external_orders(channel_id,external_order_id);
CREATE INDEX IF NOT EXISTS idx_marketing_external_status ON marketing_external_orders(order_status,ordered_at);
CREATE TABLE IF NOT EXISTS marketing_post_templates(id TEXT PRIMARY KEY,name TEXT NOT NULL,channel_type TEXT NOT NULL DEFAULT 'other',template TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),

(48,"""INSERT OR IGNORE INTO shop_settings(key,value) VALUES
('ai_provider','disabled'),('ai_model',''),('ai_endpoint',''),('ai_api_key_env','FABOS_AI_API_KEY'),
('ai_allow_customer_data','false'),('ai_require_action_approval','true');"""),
]
def migrate(db,backup=None):
 with db.connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS app_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)');done={r[0] for r in c.execute('SELECT version FROM app_migrations')}
 pending=[x for x in MIGRATIONS if x[0] not in done]
 if pending and backup:
  try: backup.create()
  except Exception: pass
 for ver,sql in pending:
  with db.connect() as c:
   statement=""
   try:
    for line in sql.splitlines(True):
     statement += line
     if sqlite3.complete_statement(statement):
      statement=statement.strip()
      if statement:
       try:
        c.execute(statement)
       except sqlite3.OperationalError as e:
        if 'duplicate column name' not in str(e).lower(): raise
      statement=""
    if statement.strip():
     c.execute(statement)
   except Exception:
    c.rollback()
    raise
   c.execute('INSERT OR IGNORE INTO app_migrations(version,name) VALUES(?,?)',(ver,'migration_%03d'%ver));c.commit()
