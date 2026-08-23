import tempfile,unittest,sqlite3
from pathlib import Path
from types import SimpleNamespace
from fabos_core.services.backup import BackupService
from fabos_desktop.main import FabOSDesktop
from fabos_desktop.system_ui import SystemReliabilityMixin

class ReliabilityBackupTests(unittest.TestCase):
 def test_backup_create_integrity_and_restore(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=td/"live.sqlite3";backups=td/"backups"
   c=sqlite3.connect(str(db));c.execute("CREATE TABLE sample(value TEXT)");c.execute("INSERT INTO sample VALUES('before')");c.commit();c.close()
   svc=BackupService(db,backups)
   b=svc.create("test")
   self.assertTrue(b.exists());self.assertEqual(svc.integrity(b),"ok")
   c=sqlite3.connect(str(db));c.execute("DELETE FROM sample");c.execute("INSERT INTO sample VALUES('after')");c.commit();c.close()
   safety=svc.restore(b)
   self.assertTrue(safety.exists())
   c=sqlite3.connect(str(db));value=c.execute("SELECT value FROM sample").fetchone()[0];c.close()
   self.assertEqual(value,"before")

 def test_daily_backup_only_once(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=td/"live.sqlite3"
   sqlite3.connect(str(db)).close()
   svc=BackupService(db,td/"backups")
   first=svc.create_daily_if_needed()
   second=svc.create_daily_if_needed()
   self.assertIsNotNone(first);self.assertIsNone(second)

 def test_system_ui_is_wired(self):
  self.assertTrue(issubclass(FabOSDesktop,SystemReliabilityMixin))
  self.assertTrue(hasattr(FabOSDesktop,"_build_backup_health_page"))
  self.assertIn("Backup & Health",FabOSDesktop.WORKSPACES)

if __name__=="__main__":unittest.main()
