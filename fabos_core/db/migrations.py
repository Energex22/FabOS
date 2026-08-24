import sys
MIGRATIONS=[
(1,"""CREATE TABLE IF NOT EXISTS app_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(2,"""CREATE TABLE IF NOT EXISTS designs(id TEXT PRIMARY KEY,product_id TEXT REFERENCES products(id) ON DELETE SET NULL,name TEXT NOT NULL,current_version INTEGER NOT NULL DEFAULT 1,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS design_versions(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,version INTEGER NOT NULL,label TEXT,notes TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(design_id,version));
CREATE TABLE IF NOT EXISTS design_assets(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,version_id TEXT REFERENCES design_versions(id),kind TEXT NOT NULL,original_name TEXT NOT NULL,stored_path TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL DEFAULT 0,width_mm REAL,depth_mm REAL,height_mm REAL,triangle_count INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS idx_design_hash ON design_assets(design_id,sha256);
CREATE TABLE IF NOT EXISTS print_profiles(id TEXT PRIMARY KEY,design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,name TEXT NOT NULL,material TEXT,nozzle_mm REAL DEFAULT .4,layer_height_mm REAL DEFAULT .2,infill_percent REAL DEFAULT 15,supports TEXT,slicer_profile_path TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(3,"""CREATE TABLE IF NOT EXISTS qc_inspections(id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(id) ON DELETE CASCADE,print_job_id TEXT REFERENCES print_jobs(id),status TEXT NOT NULL DEFAULT 'pending',checklist_json TEXT NOT NULL DEFAULT '[]',notes TEXT,photo_path TEXT,inspected_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS manufacturing_observations(id TEXT PRIMARY KEY,product_id TEXT REFERENCES products(id),print_job_id TEXT UNIQUE REFERENCES print_jobs(id),printer_id TEXT REFERENCES printers(id),estimated_minutes INTEGER,actual_minutes INTEGER,estimated_filament_g REAL,actual_filament_g REAL,success INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(4,"""ALTER TABLE print_jobs ADD COLUMN slicer_metadata_json TEXT;"""),
(5,"""ALTER TABLE print_jobs ADD COLUMN octoprint_state TEXT;"""),
(6,"""ALTER TABLE printers ADD COLUMN connection_mode TEXT NOT NULL DEFAULT 'simulation';"""),
(7,"""ALTER TABLE printers ADD COLUMN simulation_progress REAL NOT NULL DEFAULT 0;"""),
(8,"""ALTER TABLE printers ADD COLUMN nozzle_temp REAL;"""),
(9,"""ALTER TABLE printers ADD COLUMN bed_temp REAL;"""),
(10,"""ALTER TABLE printers ADD COLUMN last_seen_at TEXT;"""),
(11,"""ALTER TABLE print_jobs ADD COLUMN failure_reason TEXT;"""),
(12,"""ALTER TABLE print_jobs ADD COLUMN filament_deducted INTEGER NOT NULL DEFAULT 0;"""),
(13,"""ALTER TABLE print_jobs ADD COLUMN material_cost_cents INTEGER NOT NULL DEFAULT 0;"""),
(14,"""ALTER TABLE print_jobs ADD COLUMN machine_cost_cents INTEGER NOT NULL DEFAULT 0;"""),
(15,"""ALTER TABLE print_jobs ADD COLUMN packaging_cost_cents INTEGER NOT NULL DEFAULT 0;"""),
(16,"""ALTER TABLE print_jobs ADD COLUMN profit_cents INTEGER;"""),
(17,"""CREATE TABLE IF NOT EXISTS shop_settings(
 key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('machine_hourly_cost','0.35');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('default_packaging_cost','0.50');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('target_margin_percent','60');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('filament_low_threshold_g','250');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('filament_reorder_days','14');"""),
(18,"""CREATE TABLE IF NOT EXISTS inventory_transactions(
 id TEXT PRIMARY KEY,item_type TEXT NOT NULL,item_id TEXT NOT NULL,
 transaction_type TEXT NOT NULL,quantity REAL NOT NULL,unit TEXT,
 reference_type TEXT,reference_id TEXT,notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);"""),
(19,"""ALTER TABLE printers ADD COLUMN octoprint_current_file TEXT;"""),
(20,"""ALTER TABLE printers ADD COLUMN print_time_seconds REAL;"""),
(21,"""ALTER TABLE printers ADD COLUMN print_time_left_seconds REAL;"""),
(22,"""ALTER TABLE printers ADD COLUMN octoprint_state_text TEXT;"""),
(23,"""ALTER TABLE invoices ADD COLUMN subtotal_cents INTEGER NOT NULL DEFAULT 0;"""),
(24,"""ALTER TABLE invoices ADD COLUMN tax_cents INTEGER NOT NULL DEFAULT 0;"""),
(25,"""ALTER TABLE invoices ADD COLUMN shipping_cents INTEGER NOT NULL DEFAULT 0;"""),
(26,"""ALTER TABLE invoices ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0;"""),
(27,"""ALTER TABLE invoices ADD COLUMN notes TEXT;"""),
(28,"""CREATE TABLE IF NOT EXISTS payments(
 id TEXT PRIMARY KEY,
 invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
 amount_cents INTEGER NOT NULL,
 method TEXT,
 reference TEXT,
 notes TEXT,
 paid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);"""),
(29,"""CREATE TABLE IF NOT EXISTS fulfillments(
 id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 method TEXT NOT NULL DEFAULT 'pickup',
 status TEXT NOT NULL DEFAULT 'pending',
 carrier TEXT,
 tracking_number TEXT,
 package_weight_oz REAL,
 shipping_cost_cents INTEGER NOT NULL DEFAULT 0,
 destination TEXT,
 notes TEXT,
 shipped_at TEXT,
 delivered_at TEXT,
 picked_up_at TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fulfillment_order ON fulfillments(order_id);"""),
(30,"""CREATE TABLE IF NOT EXISTS customer_messages(
 id TEXT PRIMARY KEY,
 order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
 customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
 message_type TEXT NOT NULL DEFAULT 'status_update',
 channel TEXT NOT NULL DEFAULT 'manual',
 subject TEXT,
 body TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft',
 sent_at TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customer_messages_order ON customer_messages(order_id);
CREATE INDEX IF NOT EXISTS idx_customer_messages_sent ON customer_messages(sent_at);"""),
(31,"""INSERT OR IGNORE INTO shop_settings(key,value) VALUES
('shop_name','WireVault FabOS'),
('shop_owner_name',''),
('shop_email',''),
('shop_phone',''),
('shop_address',''),
('invoice_prefix','INV'),
('invoice_due_days','14'),
('default_tax_percent','0'),
('quote_valid_days','14'),
('currency_symbol','$'),
('backup_retention','30'),
('default_slicer','Cura'),
('customer_update_signature','');
"""),
(32,"""ALTER TABLE design_assets ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0;"""),
(33,"""ALTER TABLE designs ADD COLUMN model_mode TEXT NOT NULL DEFAULT 'single';
CREATE TABLE IF NOT EXISTS design_model_parts(
 id TEXT PRIMARY KEY,
 design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
 asset_id TEXT NOT NULL REFERENCES design_assets(id) ON DELETE CASCADE,
 part_name TEXT NOT NULL,
 quantity INTEGER NOT NULL DEFAULT 1,
 include_in_complete_set INTEGER NOT NULL DEFAULT 1,
 sort_order INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(design_id,asset_id)
);
CREATE INDEX IF NOT EXISTS idx_model_parts_design ON design_model_parts(design_id,sort_order);"""),
(34,"""CREATE TABLE IF NOT EXISTS notifications(
 id TEXT PRIMARY KEY,
 dedupe_key TEXT UNIQUE,
 severity TEXT NOT NULL DEFAULT 'info',
 title TEXT NOT NULL,
 body TEXT,
 page TEXT,
 entity_id TEXT,
 is_read INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read,created_at);

CREATE TABLE IF NOT EXISTS activity_journal(
 id TEXT PRIMARY KEY,
 event_type TEXT NOT NULL,
 title TEXT NOT NULL,
 detail TEXT,
 page TEXT,
 entity_id TEXT,
 undo_type TEXT,
 undo_payload_json TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_journal(created_at);

ALTER TABLE fulfillments ADD COLUMN package_length_in REAL;
ALTER TABLE fulfillments ADD COLUMN package_width_in REAL;
ALTER TABLE fulfillments ADD COLUMN package_height_in REAL;

INSERT OR IGNORE INTO shop_settings(key,value) VALUES('catalog_view_mode','list');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('dashboard_auto_refresh_seconds','5');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('failed_print_waste_factor','0.50');
"""),
(35,"""CREATE TABLE IF NOT EXISTS gcode_verifications(
 id TEXT PRIMARY KEY,
 product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
 asset_id TEXT REFERENCES design_assets(id) ON DELETE CASCADE,
 file_path TEXT NOT NULL,
 file_sha256 TEXT NOT NULL,
 printer_name TEXT,
 material TEXT,
 nozzle_temp REAL,
 bed_temp REAL,
 layer_height REAL,
 nozzle_mm REAL,
 min_x REAL,
 max_x REAL,
 min_y REAL,
 max_y REAL,
 estimated_minutes INTEGER,
 filament_g REAL,
 valid INTEGER NOT NULL DEFAULT 0,
 problems_json TEXT,
 verified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(file_path,file_sha256)
);
CREATE INDEX IF NOT EXISTS idx_gcode_verify_product ON gcode_verifications(product_id,verified_at);

CREATE TABLE IF NOT EXISTS supply_items(
 id TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT 'Packaging',
 unit TEXT NOT NULL DEFAULT 'ea',
 quantity REAL NOT NULL DEFAULT 0,
 unit_cost_cents INTEGER NOT NULL DEFAULT 0,
 low_threshold REAL NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1,
 notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_supply_active ON supply_items(active,category,name);

CREATE TABLE IF NOT EXISTS supply_transactions(
 id TEXT PRIMARY KEY,
 supply_id TEXT NOT NULL REFERENCES supply_items(id) ON DELETE CASCADE,
 quantity REAL NOT NULL,
 reference_type TEXT,
 reference_id TEXT,
 notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_supply_tx_item ON supply_transactions(supply_id,created_at);

CREATE TABLE IF NOT EXISTS app_runtime_state(
 key TEXT PRIMARY KEY,
 value TEXT,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO shop_settings(key,value) VALUES('auto_backup_on_shutdown','1');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('crash_recovery_enabled','1');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('diagnostic_log_retention_days','30');
INSERT OR IGNORE INTO shop_settings(key,value) VALUES('beta_channel','1');
"""),
]
def migrate(db,backup=None):
 with db.connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS app_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)');done={r[0] for r in c.execute('SELECT version FROM app_migrations')}
 pending=[x for x in MIGRATIONS if x[0] not in done]
 if pending and backup:
  try: backup.create()
  except Exception as exc:
   sys.stderr.write('FabOS: pre-migration backup failed: %s\n'%exc)
 for ver,sql in pending:
  with db.connect() as c:
   try:c.executescript(sql)
   except Exception as e:
    if 'duplicate column name' not in str(e).lower():raise
   c.execute('INSERT OR IGNORE INTO app_migrations(version,name) VALUES(?,?)',(ver,'migration_%03d'%ver));c.commit()
