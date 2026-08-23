import tempfile,unittest
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.events.bus import EventBus,Event
from fabos_core.automation.engine import AutomationEngine
class Tests(unittest.TestCase):
 def test_db(self):
  with tempfile.TemporaryDirectory() as d:
   db=Database(Path(d)/'x.db');db.initialize()
   with db.connect() as c:n={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   self.assertIn('products',n);self.assertIn('print_jobs',n)
 def test_event(self):
  b=EventBus();x=[];b.subscribe('done',x.append);b.publish(Event('done',payload={'x':1}));self.assertEqual(x[0].payload['x'],1)
 def test_match(self):self.assertTrue(AutomationEngine._matches({'status':'completed'},{'status':'completed'}))
if __name__=='__main__':unittest.main()
