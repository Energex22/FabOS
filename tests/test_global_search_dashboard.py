import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.global_search import GlobalSearchService
from fabos_core.services.shop_settings import ShopSettingsService
from fabos_core.application import FabOSApplication
from fabos_desktop.main import FabOSDesktop

class GlobalSearchDashboardTests(unittest.TestCase):
 def test_global_search_multiple_record_types(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   cid=str(uuid.uuid4());pid=str(uuid.uuid4());oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)",(cid,"Search Person","search@example.com"))
    c.execute("INSERT INTO products(id,sku,name,category) VALUES(?,?,?,?)",(pid,"WV-SEARCH","Search Widget","Tools"))
    c.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,0)",(oid,"O-SEARCH",cid,"new"))
    c.commit()
   svc=GlobalSearchService(db)
   kinds={r["kind"] for r in svc.search("Search")}
   self.assertIn("Product",kinds);self.assertIn("Customer",kinds);self.assertIn("Order",kinds)

 def test_desktop_search_and_quick_add_are_wired(self):
  self.assertTrue(hasattr(FabOSDesktop,"global_search"))
  self.assertTrue(hasattr(FabOSDesktop,"_focus_search_result"))
  self.assertTrue(hasattr(FabOSDesktop,"quick_add"))

if __name__=="__main__":unittest.main()
