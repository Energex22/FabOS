from fabos_core.services.beta_self_test import BetaSelfTestService
from fabos_core.services.diagnostics import DiagnosticsService
from fabos_core.services.recovery import RecoveryService
from fabos_core.services.gcode_verification import GCodeVerificationService
from fabos_core.services.supplies import SupplyService
from fabos_core.services.error_log import ErrorLogService
from fabos_core.config import load_settings,ensure_directories
from fabos_core.db.database import Database
from fabos_core.events.bus import EventBus
from fabos_core.events.store import SqliteEventStore
from fabos_core.automation.engine import AutomationEngine
from fabos_core.services.backup import BackupService
from fabos_core.services.products import ProductService
from fabos_core.services.customers import CustomerService
from fabos_core.services.quotes import QuoteService
from fabos_core.services.orders import OrderService
from fabos_core.services.production import ProductionService
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.manufacturing import ManufacturingService
from fabos_core.services.printer_automation import PrinterAutomationService
from fabos_core.services.inventory_profit import InventoryProfitService
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.customer_updates import CustomerUpdateService
from fabos_core.services.reliability import ReliabilityService
from fabos_core.services.shop_settings import ShopSettingsService
from fabos_core.services.global_search import GlobalSearchService
from fabos_core.services.octoprint_print import OctoPrintPrintService
from fabos_core.services.model_plate import ModelPlateService
from fabos_core.services.cura_integration import CuraIntegrationService
from fabos_core.services.product_print import ProductPrintService
from fabos_core.db.migrations import migrate
from pathlib import Path
from fabos_core.services.operations_hub import OperationsHubService
class FabOSApplication:
    def __init__(self):
        self.settings=load_settings(); ensure_directories(self.settings); self.error_log=ErrorLogService(self.settings.log_dir); self.database=Database(self.settings.database_path); self.database.initialize(); self.event_bus=EventBus(); self.event_store=SqliteEventStore(self.database); self.automation=AutomationEngine(self.database); self.backups=BackupService(self.settings.database_path,self.settings.backup_dir); migrate(self.database,self.backups); self.backups.create_daily_if_needed(); self.products=ProductService(self.database); self.customers=CustomerService(self.database); self.quotes=QuoteService(self.database); self.orders=OrderService(self.database); self.production=ProductionService(self.database,self.event_bus); self.production.ensure_default_vyper(); self.design_vault=DesignVaultService(self.database,self.settings.data_dir); self.manufacturing=ManufacturingService(self.database); self.printer_automation=PrinterAutomationService(self.database,self.production,self.manufacturing); self.inventory_profit=InventoryProfitService(self.database); self.shop_settings=ShopSettingsService(self.database); self.global_search=GlobalSearchService(self.database); self.invoices=InvoiceService(self.database,self.settings.data_dir); self.fulfillment=FulfillmentService(self.database); self.customer_updates=CustomerUpdateService(self.database); self.reliability=ReliabilityService(self); self.cura=CuraIntegrationService(self.settings.data_dir); self.product_print=ProductPrintService(self.database,self.products,self.design_vault,self.manufacturing,self.settings.data_dir); self.model_plate=ModelPlateService(self.design_vault,self.settings.data_dir); self.octoprint_print=OctoPrintPrintService(self.manufacturing,self.product_print); self.operations=OperationsHubService(self); self.supplies=SupplyService(self.database); self.gcode_verification=GCodeVerificationService(self.database,self.cura); self.diagnostics=DiagnosticsService(self); self.recovery=RecoveryService(self); self.beta_self_test=BetaSelfTestService(self); self.event_bus.subscribe('*',self.event_store.append); self.event_bus.subscribe('*',self.automation.handle); self.products.import_catalog_if_empty(Path(__file__).resolve().parents[1] / 'data' / 'catalog' / 'Top_100_Catalog.csv'); self._install_default_cura_profile(); self._recover_previous_session()
    def _recover_previous_session(self):
        self.recovered_jobs=[]
        try:
            recovered=self.recovery.reconcile()
            self.recovered_jobs=list(recovered or [])
            if recovered:
                self.error_log.warning("Recovered active print jobs after unclean shutdown",
                                       "%d job(s) reconciled"%len(recovered))
        except Exception as exc:
            self.error_log.error("Crash recovery failed",exc)

    def _install_default_cura_profile(self):
        try:
            bundled=Path(__file__).resolve().parents[1]/"data"/"cura_profiles"/"Vyper PETG.curaprofile"
            if bundled.exists():
                installed=self.cura.install_profile(bundled)
                saved=self.inventory_profit.setting("cura_petg_profile_path","")
                if not saved or not Path(saved).exists():
                    self.inventory_profit.set_setting("cura_petg_profile_path",str(installed))
                if not self.inventory_profit.setting("default_slicer",""):
                    self.inventory_profit.set_setting("default_slicer","Cura")
        except Exception:
            pass

    def summary(self):
        try:threshold=float(self.shop_settings.get('filament_low_threshold_g','250') or 250)
        except Exception:threshold=250
        with self.database.connect() as c:
            return {
                'products':c.execute('SELECT COUNT(*) FROM products').fetchone()[0],
                'orders':c.execute("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled')").fetchone()[0],
                'queued_jobs':c.execute("SELECT COUNT(*) FROM print_jobs WHERE status IN ('queued','scheduled')").fetchone()[0],
                'printers':c.execute('SELECT COUNT(*) FROM printers').fetchone()[0],
                'low_spools':c.execute('SELECT COUNT(*) FROM filament_spools WHERE active=1 AND remaining_g<?',(threshold,)).fetchone()[0]
            }
