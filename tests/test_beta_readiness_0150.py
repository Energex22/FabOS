import os,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace

from fabos_core.db.database import Database
import fabos_core.db.migrations as migration_module
from fabos_core.services.backup import BackupService
from fabos_core.services.error_log import ErrorLogService
from fabos_core.services.supplies import SupplyService
from fabos_core.services.gcode_verification import GCodeVerificationService
from fabos_core.services.cura_integration import CuraIntegrationService
from fabos_core.services.customers import CustomerService
from fabos_core.services.quotes import QuoteService
from fabos_core.services.orders import OrderService
from fabos_core.services.production import ProductionService
from fabos_core.services.manufacturing import ManufacturingService
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.recovery import RecoveryService

class BetaReadiness0150Tests(unittest.TestCase):
    def migrated_db(self,td):
        db=Database(Path(td)/"fabos.sqlite3");db.initialize();migration_module.migrate(db)
        return db

    def test_schema_35_is_installed_on_clean_database(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.migrated_db(td)
            with db.connect() as c:
                version=c.execute("SELECT MAX(version) FROM app_migrations").fetchone()[0]
                tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertGreaterEqual(version,35)
            self.assertIn("gcode_verifications",tables)
            self.assertIn("supply_items",tables)
            self.assertIn("app_runtime_state",tables)

    def test_upgrade_from_schema_34_to_35(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/"fabos.sqlite3");db.initialize()
            original=migration_module.MIGRATIONS
            try:
                migration_module.MIGRATIONS=[x for x in original if x[0]<=34]
                migration_module.migrate(db)
                with db.connect() as c:self.assertEqual(c.execute("SELECT MAX(version) FROM app_migrations").fetchone()[0],34)
                migration_module.MIGRATIONS=original
                migration_module.migrate(db)
            finally:
                migration_module.MIGRATIONS=original
            with db.connect() as c:
                self.assertEqual(c.execute("SELECT MAX(version) FROM app_migrations").fetchone()[0],35)
                self.assertIsNotNone(c.execute("SELECT name FROM sqlite_master WHERE name='supply_items'").fetchone())

    def test_backup_is_created_and_restorable(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.migrated_db(td);backup=BackupService(db.path,Path(td)/"Backups")
            path=backup.create("test")
            result=backup.validate_backup(path)
            self.assertTrue(result["valid"],result["detail"])

    def test_error_log_records_structured_error(self):
        with tempfile.TemporaryDirectory() as td:
            log=ErrorLogService(Path(td)/"Logs")
            try:raise ValueError("beta-test")
            except Exception as exc:log.error("Synthetic failure",exc,{"page":"Test"})
            rows=log.recent()
            self.assertEqual(rows[0]["level"],"ERROR")
            self.assertIn("beta-test",rows[0]["detail"])

    def test_supply_inventory_adjusts_and_warns_low(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.migrated_db(td);svc=SupplyService(db)
            sid=svc.create("6x9 Mailer","Packaging","ea",10,55,3)
            svc.adjust(sid,-8,"order","O-TEST","Used for orders")
            row=next(r for r in svc.list() if r["id"]==sid)
            self.assertEqual(row["quantity"],2)
            self.assertEqual(len(svc.low()),1)

    def test_gcode_verification_expires_when_file_changes(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.migrated_db(td)
            cura=CuraIntegrationService(td)
            verify=GCodeVerificationService(db,cura)
            path=Path(td)/"safe.gcode"
            path.write_text("M140 S60\nM104 S200\nG28\nG90\nG1 X10 Y10 E1\n",encoding="utf-8")
            result=verify.verify(path,material_hint="PLA",printer_name="Vyper")
            self.assertTrue(result["valid"])
            self.assertIsNotNone(verify.current(path))
            path.write_text(path.read_text()+"G1 X20 Y20 E2\n",encoding="utf-8")
            self.assertIsNone(verify.current(path))

    def test_recovery_marker_distinguishes_unclean_session(self):
        with tempfile.TemporaryDirectory() as td:
            app=SimpleNamespace(settings=SimpleNamespace(data_dir=Path(td)))
            first=RecoveryService(app)
            self.assertFalse(first.previous_unclean)
            second=RecoveryService(app)
            self.assertTrue(second.previous_unclean)
            second.clean_shutdown()
            self.assertFalse((Path(td)/"runtime_session.json").exists())

    def test_end_to_end_order_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.migrated_db(td)
            customers=CustomerService(db);quotes=QuoteService(db);orders=OrderService(db)
            production=ProductionService(db);mfg=ManufacturingService(db)
            invoices=InvoiceService(db,td);fulfillment=FulfillmentService(db)

            customer=customers.save({"name":"Beta Customer","email":"beta@example.com"})
            pid=str(uuid.uuid4())
            with db.connect() as c:
                c.execute("""INSERT INTO products(id,name,sku,price_cents,license_status,estimated_minutes,estimated_filament_g)
                             VALUES(?,?,?,?,?,?,?)""",(pid,"Beta Lizard","BETA-LIZ",2500,"verified",120,50))
                c.commit()
            qid=quotes.save({"customer_id":customer,"status":"approved"},
                            [{"product_id":pid,"description":"Beta Lizard","quantity":1,
                              "unit_price_cents":2500,"material":"PETG","color":"Black",
                              "estimated_minutes":120,"estimated_filament_g":50}])
            oid=quotes.convert_to_order(qid)

            jid=str(uuid.uuid4())
            with db.connect() as c:
                c.execute("""INSERT INTO print_jobs(id,order_id,product_id,status,estimated_minutes,estimated_filament_g)
                             VALUES(?,?,?,?,?,?)""",(jid,oid,pid,"printing",120,50))
                c.commit()
            production.set_status(jid,"completed")
            mfg.ensure_qc(oid,jid)
            qcrow=mfg.qc_list()[0]
            mfg.qc_save(qcrow["id"],{"dimensions":"pass","finish":"pass"},"Looks good",True)
            self.assertEqual(orders.get(oid)[0]["status"],"ready")

            iid,_created=invoices.create_from_order(oid)
            inv=invoices.get(iid)[0]
            invoices.record_payment(iid,inv["total_cents"],"Cash","BETA")
            fulfillment.save(oid,"shipping","shipped","USPS","TESTTRACK",8,500,"Test Address",
                             length_in=6,width_in=4,height_in=2)
            self.assertEqual(orders.get(oid)[0]["status"],"shipped")
            # Shipping charge is added after the initial payment, so settle the new balance.
            inv_after_shipping=invoices.get(iid)[0]
            balance=int(inv_after_shipping["total_cents"] or 0)-int(inv_after_shipping["paid_cents"] or 0)
            if balance>0:invoices.record_payment(iid,balance,"Cash","BETA-SHIP")
            fulfillment.save(oid,"shipping","delivered","USPS","TESTTRACK",8,500,"Test Address",
                             length_in=6,width_in=4,height_in=2)
            self.assertEqual(orders.get(oid)[0]["status"],"completed")

if __name__=="__main__":
    unittest.main()
