from pathlib import Path
import hashlib,json,uuid

class GCodeVerificationService:
    def __init__(self,db,cura):self.db=db;self.cura=cura

    @staticmethod
    def sha256(path):
        h=hashlib.sha256()
        with Path(path).open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        return h.hexdigest()

    def verify(self,path,product_id=None,asset_id=None,material_hint=None,printer_name=None):
        path=Path(path)
        digest=self.sha256(path)
        validation=self.cura.validate_print_gcode(path)
        hints=self.cura.gcode_profile_hints(path)
        meta=self.cura.gcode_metadata(path,material_hint or hints.get("material") or "PLA")
        bounds=validation.get("bounds") or {}
        vid=str(uuid.uuid4())
        with self.db.connect() as c:
            c.execute("""INSERT INTO gcode_verifications(
              id,product_id,asset_id,file_path,file_sha256,printer_name,material,nozzle_temp,bed_temp,
              layer_height,nozzle_mm,min_x,max_x,min_y,max_y,estimated_minutes,filament_g,valid,problems_json)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(file_path,file_sha256) DO UPDATE SET
                product_id=excluded.product_id,asset_id=excluded.asset_id,printer_name=excluded.printer_name,
                material=excluded.material,nozzle_temp=excluded.nozzle_temp,bed_temp=excluded.bed_temp,
                layer_height=excluded.layer_height,nozzle_mm=excluded.nozzle_mm,min_x=excluded.min_x,
                max_x=excluded.max_x,min_y=excluded.min_y,max_y=excluded.max_y,
                estimated_minutes=excluded.estimated_minutes,filament_g=excluded.filament_g,
                valid=excluded.valid,problems_json=excluded.problems_json,verified_at=CURRENT_TIMESTAMP""",
              (vid,product_id,asset_id,str(path),digest,printer_name or hints.get("machine"),
               (material_hint or hints.get("material")),hints.get("hotend"),hints.get("bed"),
               hints.get("layer_height"),hints.get("nozzle_mm"),bounds.get("min_x"),bounds.get("max_x"),
               bounds.get("min_y"),bounds.get("max_y"),meta.get("estimated_minutes"),meta.get("filament_g"),
               1 if validation.get("valid") else 0,json.dumps(validation.get("problems") or [])))
            c.commit()
        return {"valid":bool(validation.get("valid")),"sha256":digest,"validation":validation,
                "hints":hints,"metadata":meta}

    def current(self,path):
        path=Path(path)
        if not path.exists():return None
        digest=self.sha256(path)
        with self.db.connect() as c:
            row=c.execute("""SELECT * FROM gcode_verifications WHERE file_path=? AND file_sha256=?
              ORDER BY verified_at DESC LIMIT 1""",(str(path),digest)).fetchone()
        return row

    def stale(self,path):
        path=Path(path)
        if not path.exists():return True
        return self.current(path) is None
