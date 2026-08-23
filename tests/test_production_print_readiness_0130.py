import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.production import ProductionService
from fabos_desktop.product_print_ui import ProductPrintMixin

class ProductionReadiness0130Tests(unittest.TestCase):
 def setup_data(self,td,material="PETG"):
  db=Database(td/"x.sqlite3");db.initialize();migrate(db)
  pid=str(uuid.uuid4());jid=str(uuid.uuid4());prid=str(uuid.uuid4());sid=str(uuid.uuid4())
  with db.connect() as c:
   c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Lizard","verified"))
   c.execute("""INSERT INTO printers(id,name,model,status,build_x_mm,build_y_mm,build_z_mm)
                VALUES(?,?,?,?,?,?,?)""",(prid,"Anycubic Vyper","Anycubic Vyper","idle",245,245,260))
   c.execute("""INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active)
                VALUES(?,?,?,?,?,1)""",(sid,material,"Black",1000,1000))
   c.execute("""INSERT INTO print_jobs(id,product_id,printer_id,spool_id,status)
                VALUES(?,?,?,?,?)""",(jid,pid,prid,sid,"scheduled"))
   c.commit()
  return db,pid,jid,DesignVaultService(db,td/"vault"),ProductionService(db)

 def test_matching_petg_gcode_is_job_ready(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,jid,vault,production=self.setup_data(td,"PETG")
   g=td/"petg.gcode";g.write_text(";MATERIAL_TYPE:PETG\n;MACHINE_NAME:Anycubic Vyper\nM140 S80\nM104 S235\n",encoding="utf-8")
   vault.import_product_print_files(pid,[g])
   r=production.job_print_readiness(jid,vault)
   self.assertTrue(r["ready"]);self.assertEqual(r["state"],"gcode");self.assertTrue(r["gcode"])

 def test_wrong_material_gcode_only_needs_attention(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,jid,vault,production=self.setup_data(td,"PLA")
   g=td/"petg.gcode";g.write_text(";MATERIAL_TYPE:PETG\n;MACHINE_NAME:Anycubic Vyper\nM140 S80\nM104 S235\n",encoding="utf-8")
   vault.import_product_print_files(pid,[g])
   r=production.job_print_readiness(jid,vault)
   self.assertFalse(r["ready"]);self.assertEqual(r["state"],"attention")

 def test_best_gcode_prefers_matching_material(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,jid,vault,production=self.setup_data(td,"PETG")
   pla=td/"pla.gcode";pla.write_text(";MATERIAL_TYPE:PLA\n;MACHINE_NAME:Anycubic Vyper\n",encoding="utf-8")
   petg=td/"petg.gcode";petg.write_text(";MATERIAL_TYPE:PETG\n;MACHINE_NAME:Anycubic Vyper\n",encoding="utf-8")
   vault.import_product_print_files(pid,[pla,petg])
   best=vault.best_gcode_for(pid,"PETG","Anycubic Vyper")
   self.assertEqual(best["original_name"],"petg.gcode")

 def test_print_ui_accepts_production_preference(self):
  import inspect
  self.assertIn("preferred_gcode",inspect.signature(ProductPrintMixin._print_selected_product).parameters)

if __name__=="__main__":unittest.main()
