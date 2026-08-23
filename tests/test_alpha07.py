import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.manufacturing import ManufacturingService
class T(unittest.TestCase):
 def test_vault_and_gcode(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/'x.db');db.initialize();migrate(db);pid=str(uuid.uuid4())
   with db.connect() as c:c.execute('INSERT INTO products(id,name) VALUES(?,?)',(pid,'Cube'));c.commit()
   v=DesignVaultService(db,td);did=v.ensure_product(pid);f=Path(td)/'x.stl';f.write_text('solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 10\nendloop\nendfacet\nendsolid x');self.assertTrue(v.import_file(did,f));a=v.assets(did)[0];self.assertEqual(round(a['width_mm']),10);self.assertFalse(v.import_file(did,f))
   g=Path(td)/'x.gcode';g.write_text('; estimated printing time (normal mode) = 2h 14m 30s\n; filament used [g] = 42.5');m=ManufacturingService(db);meta=m.attach_gcode('missing',g);self.assertEqual(meta['estimated_minutes'],135);self.assertEqual(meta['filament_g'],42.5)
if __name__=='__main__':unittest.main()
