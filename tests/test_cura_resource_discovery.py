import tempfile,unittest
from pathlib import Path
from fabos_core.services.cura_integration import CuraIntegrationService

def make_resources(root):
    r=Path(root)
    (r/"definitions").mkdir(parents=True,exist_ok=True)
    (r/"extruders").mkdir(parents=True,exist_ok=True)
    (r/"definitions"/"fdmprinter.def.json").write_text("{}",encoding="utf-8")
    (r/"extruders"/"fdmextruder.def.json").write_text("{}",encoding="utf-8")
    return r

class CuraResourceDiscoveryTests(unittest.TestCase):
    def test_resources_directly_under_install(self):
        with tempfile.TemporaryDirectory() as td:
            install=Path(td)/"Ultimaker Cura 4.13.1"
            install.mkdir()
            engine=install/"CuraEngine.exe";engine.write_bytes(b"test")
            resources=make_resources(install/"resources")
            svc=CuraIntegrationService(Path(td)/"data")
            found=svc.find_cura(str(engine))
            self.assertEqual(found,engine)
            r,fdm,ext=svc.resources_for_engine(found)
            self.assertEqual(r,resources.resolve())
            self.assertTrue(fdm.exists());self.assertTrue(ext.exists())

    def test_share_cura_resources_layout(self):
        with tempfile.TemporaryDirectory() as td:
            install=Path(td)/"Ultimaker Cura 4.13.1"
            (install/"bin").mkdir(parents=True)
            engine=install/"bin"/"CuraEngine.exe";engine.write_bytes(b"test")
            resources=make_resources(install/"share"/"cura"/"resources")
            svc=CuraIntegrationService(Path(td)/"data")
            found=svc.find_cura(str(install))
            self.assertEqual(found,engine)
            r,_,_=svc.resources_for_engine(found)
            self.assertEqual(r,resources.resolve())

    def test_nonstandard_nested_resources_are_discovered(self):
        with tempfile.TemporaryDirectory() as td:
            install=Path(td)/"Ultimaker Cura 4.13.1"
            install.mkdir()
            engine=install/"CuraEngine.exe";engine.write_bytes(b"test")
            resources=make_resources(install/"app"/"cura"/"resources")
            svc=CuraIntegrationService(Path(td)/"data")
            r,_,_=svc.resources_for_engine(engine)
            self.assertEqual(r,resources.resolve())

    def test_diagnostic_reports_engine_and_resources(self):
        with tempfile.TemporaryDirectory() as td:
            install=Path(td)/"Ultimaker Cura 4.13.1"
            install.mkdir()
            engine=install/"CuraEngine.exe";engine.write_bytes(b"test")
            resources=make_resources(install/"resources")
            svc=CuraIntegrationService(Path(td)/"data")
            result=svc.installation_diagnostic(str(engine))
            self.assertTrue(result["ok"])
            self.assertEqual(Path(result["engine"]),engine)
            self.assertEqual(Path(result["resources"]),resources.resolve())

if __name__=="__main__":unittest.main()
