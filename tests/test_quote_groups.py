import tempfile
import unittest
import uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.services.quotes import QuoteService

class QuoteGroupTests(unittest.TestCase):
    def test_active_and_history_groups(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/"fabos.sqlite3")
            db.initialize()
            with db.connect() as conn:
                cid=str(uuid.uuid4())
                conn.execute("INSERT INTO customers(id,name) VALUES(?,?)",(cid,"Test Customer"))
                for status in ("draft","sent","approved","declined","expired"):
                    conn.execute(
                        "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,0)",
                        (str(uuid.uuid4()),"Q-"+status,cid,status)
                    )
                conn.commit()
            svc=QuoteService(db)
            self.assertEqual({r["status"] for r in svc.list(group="active")},{"draft","sent"})
            self.assertEqual({r["status"] for r in svc.list(group="history")},{"approved","declined","expired"})

if __name__=="__main__":
    unittest.main()
