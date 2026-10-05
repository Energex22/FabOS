import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_proofs import DesignProofService
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.production import ProductionService


class DesignProofWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        self.vault = DesignVaultService(self.db, self.temp.name)
        self.proofs = DesignProofService(self.db, self.vault)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("customer-user", "customer", "unused", "customer", 1, "customer"),
            )
            conn.execute(
                "INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                ("customer-1", "Test Customer", "customer@example.com"),
            )
            conn.execute(
                "INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)",
                ("customer-user", "customer-1"),
            )
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("quote-1", "Q-TEST-0001", "customer-1", "accepted", 4200),
            )
            conn.execute(
                "INSERT INTO quote_items(id,quote_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?)",
                ("quote-item-1", "quote-1", "Custom part", 1, 4200),
            )
            conn.execute(
                "INSERT INTO designs(id,product_id,name,current_version) VALUES(?,?,?,?)",
                ("design-1", None, "Customer Part", 1),
            )
            conn.execute(
                "INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,?,?)",
                ("design-version-1", "design-1", 1, "Customer upload"),
            )
            conn.execute(
                "INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)",
                ("quote-1", "design-1"),
            )
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,quote_id,status,total_cents) VALUES(?,?,?,?,?,?)",
                ("order-1", "O-TEST-0001", "customer-1", "quote-1", "confirmed", 4200),
            )
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_customer_approval_is_required_before_production(self):
        proof = self.proofs.create("quote-1", notes="Review the final dimensions", status="sent")
        self.assertEqual(proof["status"], "sent")

        production = ProductionService(self.db)
        with self.assertRaisesRegex(ValueError, "proof must be approved"):
            production.create_jobs_from_order("order-1")

        approved = self.proofs.approve("customer-user", proof["id"], "Looks correct.")
        self.assertEqual(approved["status"], "approved")
        self.assertIsNotNone(approved["approved_at"])

        created = production.create_jobs_from_order("order-1")
        self.assertEqual(len(created), 1)

        # Customer-owned designs are printable without first being promoted to a storefront product.
        stl = Path(self.temp.name) / "customer-part.stl"
        stl.write_text("solid customer\\nendsolid customer\\n", encoding="utf-8")
        import hashlib
        sha = hashlib.sha256(stl.read_bytes()).hexdigest()
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO design_assets(
                   id,design_id,version_id,kind,original_name,stored_path,sha256,bytes,
                   width_mm,depth_mm,height_mm,triangle_count,is_primary)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("asset-1", "design-1", "design-version-1", "STL", stl.name, str(stl), sha,
                 stl.stat().st_size, 20, 20, 5, 12, 1),
            )
            conn.commit()

        readiness = production.job_print_readiness(created[0], self.vault)
        self.assertTrue(readiness["ready"])
        self.assertEqual(readiness["state"], "stl")
        self.assertEqual(readiness["gcode"], None)

    def test_customer_cannot_approve_another_customer_proof(self):
        proof = self.proofs.create("quote-1", status="sent")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("other-user", "other", "unused", "customer", 1, "customer"),
            )
            conn.commit()
        with self.assertRaises(KeyError):
            self.proofs.approve("other-user", proof["id"], "Not mine.")

    def test_request_changes_requires_comment(self):
        proof = self.proofs.create("quote-1", status="sent")
        with self.assertRaisesRegex(ValueError, "describe the requested changes"):
            self.proofs.request_changes("customer-user", proof["id"], "")
        changed = self.proofs.request_changes("customer-user", proof["id"], "Please change the hole diameter.")
        self.assertEqual(changed["status"], "changes_requested")
        self.assertEqual(changed["customer_comment"], "Please change the hole diameter.")


if __name__ == "__main__":
    unittest.main()
