class ShopSettingsService:
    DEFAULTS={
        "shop_name":"WireVault FabOS","shop_owner_name":"","shop_email":"","shop_phone":"",
        "shop_address":"","invoice_prefix":"INV","invoice_due_days":"14","default_tax_percent":"0",
        "quote_valid_days":"14","currency_symbol":"$","machine_hourly_cost":"0.35",
        "default_packaging_cost":"0.50","target_margin_percent":"60",
        "filament_low_threshold_g":"250","filament_reorder_days":"14",
        "backup_retention":"30","default_slicer":"Cura","cura_engine_path":"",
        "cura_petg_profile_path":"","cura_fdmprinter_path":"","cura_fdmextruder_path":"",
        "customer_update_signature":""
    }
    def __init__(self,db):self.db=db

    def get(self,key,default=None):
        with self.db.connect() as c:
            row=c.execute("SELECT value FROM shop_settings WHERE key=?",(key,)).fetchone()
        if row:return row["value"]
        if key in self.DEFAULTS:return self.DEFAULTS[key]
        return default

    def set(self,key,value):
        with self.db.connect() as c:
            c.execute("""INSERT INTO shop_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
              ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
              (str(key),str(value)))
            c.commit()

    def update(self,values):
        with self.db.connect() as c:
            for key,value in values.items():
                c.execute("""INSERT INTO shop_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP""",
                  (str(key),str(value)))
            c.commit()

    def snapshot(self):
        result=dict(self.DEFAULTS)
        with self.db.connect() as c:
            for row in c.execute("SELECT key,value FROM shop_settings"):
                result[row["key"]]=row["value"]
        return result
