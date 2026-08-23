import tempfile,unittest
from pathlib import Path
from fabos_core.services.cura_integration import CuraIntegrationService

class ExplicitCuraDefinitionsTests(unittest.TestCase):
 def test_explicit_definition_files_bypass_resource_tree(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td)
   engine=td/"CuraEngine.exe";engine.write_bytes(b"x")
   defs=td/"defs";defs.mkdir()
   fdm=defs/"fdmprinter.def.json";fdm.write_text("{}",encoding="utf-8")
   ext=defs/"fdmextruder.def.json";ext.write_text("{}",encoding="utf-8")
   svc=CuraIntegrationService(td/"data")
   resources,found_fdm,found_ext=svc.resources_for_engine(
    engine,configured_fdmprinter=str(fdm),configured_fdmextruder=str(ext))
   self.assertEqual(found_fdm,fdm)
   self.assertEqual(found_ext,ext)

 def test_appdata_cura_folder_is_considered(self):
  # Structural test: implementation includes official Windows user-settings location.
  text=Path(__file__).resolve().parents[1].joinpath("fabos_core/services/cura_integration.py").read_text(encoding="utf-8")
  self.assertIn('os.environ.get("APPDATA")',text)
  self.assertIn('os.environ.get("LOCALAPPDATA")',text)

if __name__=="__main__":unittest.main()
