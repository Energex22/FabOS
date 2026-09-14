import unittest
from fabos_core.services.production_queue_decision import ProductionQueueDecision

class Orders(object):
    def get(self, oid): return {"id":oid}
class App(object):
    orders=Orders()

class Tests(unittest.TestCase):
    def test_ready(self):
        d=ProductionQueueDecision(App()).decide({"status":"queued","quantity":1,"printer_id":"P1","product_id":"X"})
        self.assertTrue(d["eligible"])
    def test_missing_printer(self):
        d=ProductionQueueDecision(App()).decide({"status":"queued","quantity":1,"product_id":"X"})
        self.assertFalse(d["eligible"])
        self.assertIn("No printer is assigned.",d["reasons"])
    def test_terminal(self):
        d=ProductionQueueDecision(App()).decide({"status":"completed","quantity":1,"printer_id":"P1","product_id":"X"})
        self.assertFalse(d["eligible"])
    def test_order_warning(self):
        class A(object):
            class orders(object):
                @staticmethod
                def get(oid): return None
        d=ProductionQueueDecision(A()).decide({"status":"queued","quantity":1,"printer_id":"P1","product_id":"X","order_id":"O"})
        self.assertTrue(d["eligible"]); self.assertTrue(d["warnings"])

if __name__=="__main__": unittest.main()
