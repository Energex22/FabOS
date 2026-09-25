class ShopSettingsService:
    DEFAULTS = {
        "shop_name": "WireVault FabOS", "shop_owner_name": "", "shop_email": "", "shop_phone": "",
        "shop_address": "", "business_hours": "", "timezone": "America/Chicago", "currency_code": "USD", "currency_symbol": "$",
        "invoice_prefix": "INV", "invoice_due_days": "14", "default_tax_percent": "0", "quote_valid_days": "14",
        "machine_hourly_cost": "0.35", "default_packaging_cost": "0.50", "target_margin_percent": "60",
        "minimum_order_cents": "0", "rush_multiplier": "1.00", "quantity_discount_enabled": "false", "quantity_discount_percent": "0",
        "default_material_cost_per_g": "0", "labor_hourly_rate": "0", "setup_labor_hourly_rate": "0",
        "post_process_labor_hourly_rate": "0", "qc_labor_hourly_rate": "0", "overhead_percent": "0",
        "payment_fee_percent": "0", "payment_fee_fixed_cents": "0",
        "filament_low_threshold_g": "250", "filament_reorder_days": "14", "filament_waste_percent": "5",
        "backup_retention": "30", "backup_enabled": "true", "backup_frequency_hours": "24",
        "default_slicer": "Cura", "cura_engine_path": "", "cura_petg_profile_path": "", "cura_fdmprinter_path": "", "cura_fdmextruder_path": "",
        "customer_update_signature": "", "customer_registration_enabled": "true", "custom_work_enabled": "true",
        "storefront_enabled": "true", "storefront_ordering_enabled": "true", "storefront_default_visibility": "draft",
        "custom_upload_max_mb": "25", "custom_upload_extensions": "stl,3mf,obj,step,stp",
        "default_turnaround_days": "7", "rush_turnaround_days": "3", "shipping_mode": "calculated", "shipping_flat_cents": "0",
        "shipping_calculated_base_cents": "0", "shipping_calculated_per_kg_cents": "0", "free_shipping_threshold_cents": "0",
        "payment_provider": "stripe", "payment_test_mode": "true", "online_payment_required": "true",
        "notification_order_received": "true", "notification_payment_received": "true", "notification_production_started": "true",
        "notification_qc_required": "true", "notification_shipped": "true", "notification_low_inventory": "true",
        "console_lock_enabled": "true", "console_idle_timeout_minutes": "15", "console_local_only": "true",
        "marketing_enabled": "true", "marketing_require_approval": "true", "marketing_default_publish_mode": "manual", "marketing_timezone": "America/Chicago",
        "marketing_etsy_shop_id": "", "marketing_etsy_credential_ref": "", "marketing_ebay_account_ref": "",
        "marketing_facebook_page_id": "", "marketing_facebook_credential_ref": "", "marketing_instagram_account_ref": "",
        "marketing_tiktok_account_ref": "", "marketing_pinterest_account_ref": "", "marketing_email_provider_ref": "",
        "production_automation_enabled": "true", "production_auto_assign": "true", "production_auto_start": "false", "production_automation_interval_seconds": "10",
    }

    META = {
        "business": {
            "shop_name": "Business display name", "shop_owner_name": "Owner/contact name", "shop_email": "Business email", "shop_phone": "Business phone",
            "shop_address": "Business mailing address", "business_hours": "Customer-facing business hours", "timezone": "Business timezone", "currency_code": "Currency code", "currency_symbol": "Currency display symbol",
        },
        "sales": {
            "invoice_prefix": "Invoice number prefix", "invoice_due_days": "Default invoice due period", "default_tax_percent": "Default tax percentage", "quote_valid_days": "Quote validity period",
            "minimum_order_cents": "Minimum order amount in cents", "default_turnaround_days": "Normal turnaround in days", "rush_turnaround_days": "Rush turnaround in days",
        },
        "pricing": {
            "machine_hourly_cost": "Internal machine cost per hour", "default_material_cost_per_g": "Default material cost per gram when no spool cost is available",
            "labor_hourly_rate": "General hands-on labor rate", "setup_labor_hourly_rate": "Setup/slicing labor rate", "post_process_labor_hourly_rate": "Post-processing labor rate",
            "qc_labor_hourly_rate": "Quality-control labor rate", "default_packaging_cost": "Default packaging cost", "overhead_percent": "Production overhead percentage",
            "target_margin_percent": "Target selling margin percentage", "payment_fee_percent": "Payment processing fee percentage", "payment_fee_fixed_cents": "Fixed payment fee in cents",
            "rush_multiplier": "Rush pricing multiplier", "quantity_discount_enabled": "Enable quantity discount rules", "quantity_discount_percent": "Quantity discount percentage for large orders",
        },
        "inventory": {
            "filament_low_threshold_g": "Low-stock warning threshold in grams", "filament_reorder_days": "Expected replenishment period", "filament_waste_percent": "Estimated material waste percentage",
        },
        "storefront": {
            "storefront_enabled": "Allow Fabvex storefront operation", "storefront_ordering_enabled": "Allow customer ordering", "customer_registration_enabled": "Allow customer account registration",
            "custom_work_enabled": "Allow customer custom-work requests", "storefront_default_visibility": "Default new storefront publication state",
            "custom_upload_max_mb": "Maximum custom upload size", "custom_upload_extensions": "Allowed custom model extensions",
        },
        "payments": {
            "payment_provider": "Primary online payment provider", "payment_test_mode": "Use payment provider test mode", "online_payment_required": "Require online payment for checkout",
        },
        "shipping": {
            "shipping_mode": "Shipping calculation mode", "shipping_flat_cents": "Flat shipping amount", "shipping_calculated_base_cents": "Calculated shipping base amount", "shipping_calculated_per_kg_cents": "Calculated shipping per kilogram", "free_shipping_threshold_cents": "Order amount that qualifies for free shipping",
        },
        "reliability": {
            "backup_enabled": "Enable scheduled backups", "backup_frequency_hours": "Backup interval in hours", "backup_retention": "Backup retention period in days",
        },
        "security": {
            "console_lock_enabled": "Require the local FabOS console to lock when inactive",
            "console_idle_timeout_minutes": "Minutes of console inactivity before automatic lock",
            "console_local_only": "Reject console logins from Windows Remote Desktop and SSH sessions",
        },
        "notifications": {
            "notification_order_received": "Notify when an order is received", "notification_payment_received": "Notify when payment is received", "notification_production_started": "Notify when production starts",
            "notification_qc_required": "Notify when QC is required", "notification_shipped": "Notify when an order ships", "notification_low_inventory": "Notify on low inventory",
        },
        "automation": {
            "production_automation_enabled": "Run the production automation worker continuously",
            "production_auto_assign": "Automatically assign compatible printers and filament to queued jobs",
            "production_auto_start": "Automatically start eligible prints (keep off for physical printers until explicitly enabled)",
            "production_automation_interval_seconds": "Automation check interval in seconds",
        },
        "marketing": {
            "marketing_enabled": "Enable the marketing and sales hub", "marketing_require_approval": "Require owner/admin approval before external publishing",
            "marketing_default_publish_mode": "Default channel publishing mode", "marketing_timezone": "Timezone used for scheduled marketing posts", "marketing_etsy_shop_id": "Etsy shop identifier", "marketing_etsy_credential_ref": "Secret-store/environment reference for Etsy OAuth credentials",
            "marketing_ebay_account_ref": "Secret-store/environment reference for eBay credentials", "marketing_facebook_page_id": "Facebook Page identifier", "marketing_facebook_credential_ref": "Secret-store/environment reference for Meta credentials",
            "marketing_instagram_account_ref": "Instagram account reference", "marketing_tiktok_account_ref": "TikTok account reference", "marketing_pinterest_account_ref": "Pinterest account reference", "marketing_email_provider_ref": "Email provider configuration reference",
        },
        "production": {
            "default_slicer": "Default slicer", "cura_engine_path": "Cura engine executable", "cura_petg_profile_path": "PETG Cura profile", "cura_fdmprinter_path": "Cura printer definition", "cura_fdmextruder_path": "Cura extruder definition",
        },
    }

    BOOL_KEYS = {key for group in META.values() for key in group if key.endswith("_enabled") or key.endswith("_required")}
    ENUMS = {
        "storefront_default_visibility": {"draft", "review", "published", "retired"},
        "shipping_mode": {"calculated", "flat", "free"},
        "payment_provider": {"stripe", "square", "none"},
        "marketing_default_publish_mode": {"manual", "webhook", "api"},
    }
    NUMERIC_KEYS = {
        "invoice_due_days", "default_tax_percent", "quote_valid_days", "machine_hourly_cost", "default_material_cost_per_g", "labor_hourly_rate",
        "setup_labor_hourly_rate", "post_process_labor_hourly_rate", "qc_labor_hourly_rate", "default_packaging_cost", "overhead_percent", "target_margin_percent",
        "minimum_order_cents", "rush_multiplier", "quantity_discount_percent", "payment_fee_percent", "payment_fee_fixed_cents", "filament_low_threshold_g", "filament_reorder_days", "filament_waste_percent", "backup_retention",
        "backup_frequency_hours", "custom_upload_max_mb", "console_idle_timeout_minutes", "default_turnaround_days", "rush_turnaround_days", "shipping_flat_cents",
        "shipping_calculated_base_cents", "shipping_calculated_per_kg_cents", "free_shipping_threshold_cents", "production_automation_interval_seconds",
    }

    def __init__(self, db):
        self.db = db

    def get(self, key, default=None):
        with self.db.connect() as c:
            row = c.execute("SELECT value FROM shop_settings WHERE key=?", (key,)).fetchone()
        if row:
            return row["value"]
        if key in self.DEFAULTS:
            return self.DEFAULTS[key]
        return default

    def set(self, key, value):
        self.set_validated(key, value)

    def set_validated(self, key, value):
        key = str(key).strip()
        if key not in self.DEFAULTS:
            raise KeyError("Unknown shop setting: %s" % key)
        value = str(value)
        if key in self.ENUMS and value not in self.ENUMS[key]:
            raise ValueError("Invalid value for %s" % key)
        if key in self.NUMERIC_KEYS:
            try:
                number = float(value)
            except ValueError:
                raise ValueError("Setting %s must be numeric" % key)
            if number < 0:
                raise ValueError("Setting %s cannot be negative" % key)
        if key == "rush_multiplier" and float(value) < 1:
            raise ValueError("rush_multiplier must be at least 1")
        if key in {"default_tax_percent", "target_margin_percent", "filament_waste_percent", "overhead_percent", "payment_fee_percent", "quantity_discount_percent"} and float(value) > 100:
            raise ValueError("Setting %s cannot exceed 100" % key)
        if key == "custom_upload_extensions":
            extensions = [item.strip().lower().lstrip(".") for item in value.split(",") if item.strip()]
            allowed = {"stl", "3mf", "obj", "step", "stp"}
            if not extensions or any(item not in allowed for item in extensions):
                raise ValueError("custom_upload_extensions contains an unsupported extension")
            value = ",".join(dict.fromkeys(extensions))
        with self.db.connect() as c:
            c.execute("""INSERT INTO shop_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
              ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""", (key, value))
            c.commit()

    def update(self, values):
        for key, value in values.items():
            self.set_validated(key, value)

    def snapshot(self):
        result = dict(self.DEFAULTS)
        with self.db.connect() as c:
            for row in c.execute("SELECT key,value FROM shop_settings"):
                if row["key"] in self.DEFAULTS:
                    result[row["key"]] = row["value"]
        return result

    def metadata(self):
        return dict(self.META)
