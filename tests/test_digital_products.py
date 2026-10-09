"""Digital products: product types, licenses, file attachments, checkout,
paid-grant of download tokens, secure delivery, and fulfillment skipping."""
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from fabos_api import FabOSAPI
from fabos_core.db.database import Database
from fabos_core.db.migrations import MIGRATIONS, migrate
from fabos_core.services.digital_delivery import DigitalDeliveryService
from fabos_core.services.customer_commerce import CustomerCommerceService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.price_history import PriceHistoryService
from fabos_core.services.products import ProductService
from fabos_core.services.shop_settings import ShopSettingsService


def make_db(path):
    db = Database(path)
    db.initialize()
    migrate(db)
    return db


class _Accounts:
    def __init__(self, user_id="user-1", customer_id="customer-1"):
        self.user_id = user_id
        self.customer_id = customer_id

    def get_user(self, user_id):
        return {"id": self.user_id, "active": 1, "account_type": "customer"}

    def customer_for_user(self, user_id):
        return {"id": self.customer_id, "name": "Customer", "email": "customer@example.com"}


class _Quotes:
    def __init__(self, db):
        self.db = db

    def save(self, data, items):
        quote_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                (quote_id, "Q-%s" % uuid.uuid4().hex[:6], data["customer_id"], data.get("status", "approved"), 0),
            )
            for item in items:
                item_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO quote_items(id,quote_id,product_id,description,quantity,unit_price_cents,license_key) VALUES(?,?,?,?,?,?,?)",
                    (item_id, quote_id, item.get("product_id"), item.get("description"),
                     item.get("quantity"), item.get("unit_price_cents"), item.get("license_key")),
                )
            conn.commit()
        return quote_id


def make_digital_product(db, data_dir, product_id=None, name="Widget Files", design_type="3d_print",
                         licenses=(("personal", "Personal use", 1500), ("commercial", "Commercial use", 4500)),
                         filename=None, file_bytes=None):
    product_id = product_id or ("dp-%s" % uuid.uuid4().hex[:8])
    default_files = {"3d_print": ("widget.stl", b"solid fake stl"),
                     "cnc": ("part.dxf", b"dxf content"),
                     "laser": ("panel.svg", b"<svg/>")}
    default_name, default_bytes = default_files.get(design_type, default_files["3d_print"])
    filename = filename or default_name
    file_bytes = default_bytes if file_bytes is None else file_bytes
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO products(id,name,license_status,price_cents) VALUES(?,?,?,?)",
            (product_id, name, "verified", 1500),
        )
        conn.execute(
            "INSERT OR IGNORE INTO customers(id,name,email) VALUES(?,?,?)",
            ("customer-1", "Customer", "customer@example.com"),
        )
        conn.commit()
    service = DigitalDeliveryService(db, data_dir)
    service.configure_product(
        product_id, "digital", design_type,
        [{"license_key": key, "label": label, "price_cents": price} for key, label, price in licenses],
    )
    service.add_file(product_id, filename, file_bytes)
    ProductService(db).save_storefront(product_id, {"visibility": "published"})
    return service, product_id


def make_physical_product(db, product_id=None, price_cents=2000):
    product_id = product_id or ("pp-%s" % uuid.uuid4().hex[:8])
    products = ProductService(db)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO products(id,name,license_status,price_cents,estimated_filament_g) VALUES(?,?,?,?,?)",
            (product_id, "Widget Print", "verified", price_cents, 50.0),
        )
        # Real model file so storefront readiness passes without mocks.
        conn.execute(
            "INSERT INTO product_files(id,product_id,kind,path) VALUES(?,?,?,?)",
            (str(uuid.uuid4()), product_id, "model", "widget.stl"),
        )
        conn.commit()
    products.save_storefront(product_id, {"visibility": "published"})
    return products, product_id


class DigitalMigrationTests(unittest.TestCase):
    def test_migration_61_applies_on_fresh_db(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT MAX(version) FROM app_migrations").fetchone()[0], 61)
                product_cols = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
                self.assertIn("product_type", product_cols)
                self.assertIn("design_type", product_cols)
                self.assertIn("license_key", {row[1] for row in conn.execute("PRAGMA table_info(order_items)")})
                self.assertIn("license_key", {row[1] for row in conn.execute("PRAGMA table_info(quote_items)")})
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("product_digital_licenses", tables)
                self.assertIn("digital_product_files", tables)
                self.assertIn("digital_download_tokens", tables)
                settings = dict(conn.execute("SELECT key,value FROM shop_settings WHERE key LIKE 'digital%'").fetchall())
            self.assertEqual(settings["digital_download_days"], "7")
            self.assertEqual(settings["digital_download_max"], "10")
            self.assertEqual(settings["digital_upload_max_mb"], "500")
            self.assertEqual(settings["digital_extensions_3d_print"], "stl,3mf,step,zip")
            self.assertEqual(settings["digital_extensions_cnc"], "dxf,svg,nc,gcode,tap,crv")
            self.assertEqual(settings["digital_extensions_laser"], "svg,lbrn,lbrn2,dxf,pdf")
            self.assertEqual(len({version for version, _ in MIGRATIONS}), len(MIGRATIONS))


class DigitalSettingsTests(unittest.TestCase):
    def test_extension_settings_are_admin_configurable(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            settings = ShopSettingsService(db)
            # META exposes the keys so the admin settings UI can edit them.
            meta_keys = {key for group in settings.metadata().values() for key in group}
            for key in ("digital_download_days", "digital_download_max", "digital_upload_max_mb",
                        "digital_extensions_3d_print", "digital_extensions_cnc", "digital_extensions_laser"):
                self.assertIn(key, meta_keys)
            # Admin can extend the allowlist without a code change...
            settings.set("digital_extensions_cnc", "dxf,svg,nc,gcode,tap,crv,eps")
            self.assertEqual(settings.get("digital_extensions_cnc"), "dxf,svg,nc,gcode,tap,crv,eps")
            # ...but garbage is rejected and normalized.
            with self.assertRaises(ValueError):
                settings.set("digital_extensions_laser", "svg, ../evil")
            with self.assertRaises(ValueError):
                settings.set("digital_extensions_3d_print", "")
            settings.set("digital_extensions_3d_print", "STL, 3MF")
            self.assertEqual(settings.get("digital_extensions_3d_print"), "stl,3mf")
            with self.assertRaises(ValueError):
                settings.set("digital_download_days", "not-a-number")


class DigitalDeliveryServiceTests(unittest.TestCase):
    def test_configure_product_and_licenses(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td)
            config = service.get_config(product_id)
            self.assertEqual(config["product_type"], "digital")
            self.assertEqual(config["design_type"], "3d_print")
            self.assertEqual(config["design_type_label"], "3D print")
            self.assertEqual(len(config["licenses"]), 2)
            self.assertEqual(len(config["files"]), 1)
            # Base price syncs to the cheapest active license.
            with db.connect() as conn:
                price = conn.execute("SELECT price_cents FROM products WHERE id=?", (product_id,)).fetchone()[0]
            self.assertEqual(price, 1500)
            with self.assertRaises(ValueError):
                service.configure_product(product_id, "digital", "submarine")
            with self.assertRaises(ValueError):
                service.configure_product(product_id, "ethereal")
            with self.assertRaises(KeyError):
                service.configure_product("nope", "digital")

    def test_license_option_validation(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td)
            with self.assertRaises(ValueError):
                service.set_license_options(product_id, [
                    {"license_key": "personal", "label": "P", "price_cents": 100},
                    {"license_key": "personal", "label": "Dupe", "price_cents": 200},
                ])
            with self.assertRaises(ValueError):
                service.set_license_options(product_id, [{"license_key": "bad key!", "price_cents": 100}])
            with self.assertRaises(ValueError):
                service.set_license_options(product_id, [{"license_key": "personal", "price_cents": -5}])
            # Clearing all licenses is allowed (product just becomes unorderable).
            self.assertEqual(service.set_license_options(product_id, []), [])

    def test_file_validation_uses_configured_extensions_per_design_type(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td, design_type="laser")
            # Laser defaults allow svg but not stl.
            service.add_file(product_id, "panel.svg", b"<svg/>")
            with self.assertRaises(ValueError) as ctx:
                service.add_file(product_id, "panel.stl", b"solid x")
            self.assertIn("not allowed", str(ctx.exception))
            # Admin extends the allowlist via settings — no code change needed.
            ShopSettingsService(db).set("digital_extensions_laser", "svg,lbrn,lbrn2,dxf,pdf,stl")
            service.add_file(product_id, "panel.stl", b"solid x")
            self.assertEqual(service.digital_file_count(product_id), 3)
            with self.assertRaises(ValueError):
                service.add_file(product_id, "empty.svg", b"")
            # CNC design type accepts toolpath formats.
            _, cnc_id = make_digital_product(db, td, design_type="cnc", filename="part.dxf", file_bytes=b"dxf")
            self.assertEqual(service.digital_file_count(cnc_id), 1)

    def test_file_upload_size_limit(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            ShopSettingsService(db).set("digital_upload_max_mb", "1")
            service, product_id = make_digital_product(db, td)
            with self.assertRaises(ValueError) as ctx:
                service.add_file(product_id, "big.stl", b"x" * (2 * 1024 * 1024))
            self.assertIn("exceeds", str(ctx.exception))

    def test_delete_file_removes_row_and_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td)
            file_id = service.list_files(product_id)[0]["id"]
            stored = Path(td) / "digital_downloads" / service.list_files(product_id)[0]["stored_path"]
            self.assertTrue(stored.is_file())
            service.delete_file(product_id, file_id)
            self.assertEqual(service.list_files(product_id), [])
            self.assertFalse(stored.exists())
            with self.assertRaises(KeyError):
                service.delete_file(product_id, file_id)

    def test_grant_is_idempotent_and_redeem_consumes(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td)
            order_id, item_id = self._order_with_item(db, product_id)
            first = service.grant_for_order(order_id)
            self.assertEqual(len(first), 1)
            token_value = first[0]["token"]
            self.assertTrue(len(token_value) >= 40)  # unguessable bearer token
            # Repeat grants (e.g. duplicate payment webhooks) mint nothing new.
            self.assertEqual(service.grant_for_order(order_id), [])
            payload, file_row, path = service.redeem(token_value)
            self.assertEqual(file_row["original_name"], "widget.stl")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), b"solid fake stl")
            with db.connect() as conn:
                count = conn.execute(
                    "SELECT download_count FROM digital_download_tokens WHERE token=?", (token_value,)).fetchone()[0]
            self.assertEqual(count, 1)
            with self.assertRaises(KeyError):
                service.redeem("no-such-token")

    def test_redeem_enforces_expiry_limit_and_revocation(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            settings = ShopSettingsService(db)
            settings.set("digital_download_days", "7")
            settings.set("digital_download_max", "1")
            service, product_id = make_digital_product(db, td)
            order_id, _ = self._order_with_item(db, product_id)
            (grant,) = service.grant_for_order(order_id)
            service.redeem(grant["token"])  # first download OK
            with self.assertRaises(PermissionError):
                service.redeem(grant["token"])  # limit reached
            regenerated = service.regenerate(grant["id"])
            self.assertNotEqual(regenerated["token"], grant["token"])
            with self.assertRaises(PermissionError):
                service.redeem(grant["token"])  # old token revoked by regenerate
            payload, _, _ = service.redeem(regenerated["token"])
            self.assertTrue(payload["is_active"])
            service.revoke(regenerated["id"])
            with self.assertRaises(PermissionError):
                service.redeem(regenerated["token"])
            # Expired token.
            order_id2, _ = self._order_with_item(db, product_id)
            (grant2,) = service.grant_for_order(order_id2)
            with db.connect() as conn:
                conn.execute("UPDATE digital_download_tokens SET expires_at='2000-01-01T00:00:00' WHERE id=?",
                             (grant2["id"],))
                conn.commit()
            with self.assertRaises(PermissionError):
                service.redeem(grant2["token"])

    def test_my_downloads_lists_active_only_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td, design_type="cnc")
            order_id, _ = self._order_with_item(db, product_id)
            (grant,) = service.grant_for_order(order_id)
            downloads = service.tokens_for_customer("customer-1")
            self.assertEqual(len(downloads), 1)
            self.assertEqual(downloads[0]["design_type"], "cnc")
            self.assertEqual(downloads[0]["design_type_label"], "CNC")
            self.assertTrue(downloads[0]["is_active"])
            service.revoke(grant["id"])
            self.assertEqual(service.tokens_for_customer("customer-1"), [])
            self.assertEqual(len(service.tokens_for_customer("customer-1", include_inactive=True)), 1)

    def test_digital_only_order_detection(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, digital_id = make_digital_product(db, td)
            _, physical_id = make_physical_product(db)
            digital_order, _ = self._order_with_item(db, digital_id)
            mixed_order, _ = self._order_with_item(db, digital_id)
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO order_items(id,order_id,product_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?,?)",
                    (str(uuid.uuid4()), mixed_order, physical_id, "print", 1, 2000),
                )
                conn.commit()
            self.assertTrue(service.is_digital_only_order(digital_order))
            self.assertFalse(service.is_digital_only_order(mixed_order))

    def _order_with_item(self, db, product_id, license_key="personal"):
        order_id, item_id = str(uuid.uuid4()), str(uuid.uuid4())
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                (order_id, "O-%s" % uuid.uuid4().hex[:8], "customer-1", "pending", 1500),
            )
            conn.execute(
                "INSERT INTO order_items(id,order_id,product_id,description,quantity,unit_price_cents,license_key) VALUES(?,?,?,?,?,?,?)",
                (item_id, order_id, product_id, "Widget Files · Personal use", 1, 1500, license_key),
            )
            conn.commit()
        return order_id, item_id


class DigitalCheckoutTests(unittest.TestCase):
    def _commerce(self, db):
        return CustomerCommerceService(db, _Accounts(), ProductService(db), _Quotes(db), ShopSettingsService(db), auth=None)

    def test_digital_item_requires_valid_license(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, product_id = make_digital_product(db, td)
            commerce = self._commerce(db)
            with self.assertRaises(ValueError):
                commerce.preview_order_totals("user-1", [{"productId": product_id, "quantity": 1}], {}, "")
            with self.assertRaises(ValueError):
                commerce.preview_order_totals("user-1", [{"productId": product_id, "quantity": 1, "license": "enterprise"}], {}, "")

    def test_digital_checkout_uses_license_price_and_skips_shipping(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, product_id = make_digital_product(db, td)
            commerce = self._commerce(db)
            totals = commerce.preview_order_totals(
                "user-1", [{"productId": product_id, "quantity": 1, "license": "commercial"}], {}, "")
            self.assertEqual(totals["items"][0]["unit_price_cents"], 4500)
            self.assertEqual(totals["items"][0]["license_key"], "commercial")
            self.assertTrue(totals["items"][0]["is_digital"])
            self.assertEqual(totals["shipping_cents"], 0)
            # No shipping address needed for digital-only carts.
            row, saved_items, _, shipping_cents, _, total_cents = commerce.create_order(
                "user-1", [{"productId": product_id, "quantity": 1, "license": "personal"}], {}, "")
            self.assertEqual(shipping_cents, 0)
            with db.connect() as conn:
                item = conn.execute("SELECT license_key,unit_price_cents FROM order_items WHERE order_id=?",
                                    (row["id"],)).fetchone()
                quote_item = conn.execute("SELECT license_key FROM quote_items WHERE quote_id=?",
                                          (row["quote_id"],)).fetchone()
            self.assertEqual(item["license_key"], "personal")
            self.assertEqual(item["unit_price_cents"], 1500)
            self.assertEqual(quote_item["license_key"], "personal")
            self.assertGreater(total_cents, 0)

    def test_mixed_cart_still_requires_shipping_address(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, digital_id = make_digital_product(db, td)
            _, physical_id = make_physical_product(db)
            commerce = self._commerce(db)
            items = [{"productId": digital_id, "quantity": 1, "license": "personal"},
                     {"productId": physical_id, "quantity": 1}]
            with self.assertRaises(ValueError):
                commerce.preview_order_totals("user-1", items, {}, "")
            address = {"address": "1 Main St", "city": "Auxvasse", "state": "MO", "zip": "65231"}
            totals = commerce.preview_order_totals("user-1", items, address, "")
            self.assertEqual(totals["items"][0]["license_key"], "personal")
            self.assertIsNone(totals["items"][1]["license_key"])

    def test_digital_rejects_variants_and_unlicensed_products(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, product_id = make_digital_product(db, td)
            commerce = self._commerce(db)
            with self.assertRaises(ValueError):
                commerce.preview_order_totals(
                    "user-1", [{"productId": product_id, "quantity": 1, "license": "personal", "variantId": "v1"}], {}, "")
            # A digital product with no license options configured is unorderable.
            DigitalDeliveryService(db, td).set_license_options(product_id, [])
            with self.assertRaises(ValueError):
                commerce.preview_order_totals(
                    "user-1", [{"productId": product_id, "quantity": 1, "license": "personal"}], {}, "")

    def test_digital_readiness_requires_file_and_priced_license(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            products = ProductService(db)
            product_id = "dp-bare-%s" % uuid.uuid4().hex[:6]
            with db.connect() as conn:
                conn.execute("INSERT INTO products(id,name,license_status,price_cents) VALUES(?,?,?,?)",
                             (product_id, "Bare Files", "verified", 1000))
                conn.commit()
            DigitalDeliveryService(db, td).configure_product(product_id, "digital", "3d_print", [
                {"license_key": "personal", "label": "Personal", "price_cents": 1000}])
            readiness = products.storefront_publication_readiness(product_id)
            self.assertFalse(readiness["ready"])
            self.assertTrue(any("download file" in reason for reason in readiness["reasons"]))
            with self.assertRaises(ValueError):
                products.save_storefront(product_id, {"visibility": "published"})
            # Physical products still follow the old model-file rule.
            physical_products, physical_id = make_physical_product(db)
            self.assertTrue(physical_products.storefront_publication_readiness(physical_id)["ready"])


class DigitalPaidGrantTests(unittest.TestCase):
    def test_record_payment_grants_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td)
            order_id, _ = DigitalDeliveryServiceTests._order_with_item(self, db, product_id)
            invoices = InvoiceService(db, td)
            invoice_id = invoices.auto_create_for_order(order_id)
            self.assertTrue(invoice_id)
            self.assertEqual(service.tokens_for_customer("customer-1", include_inactive=True), [])
            invoices.record_payment(invoice_id, 1500, method="test", reference="ref-1")
            tokens = service.tokens_for_customer("customer-1")
            self.assertEqual(len(tokens), 1)
            self.assertTrue(tokens[0]["is_active"])
            # Re-running the grant (duplicate settlement) mints nothing new.
            self.assertEqual(service.grant_for_order(order_id), [])
            self.assertEqual(len(service.tokens_for_customer("customer-1", include_inactive=True)), 1)

    def test_physical_order_grants_no_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, physical_id = make_physical_product(db)
            with db.connect() as conn:
                conn.execute("INSERT INTO customers(id,name) VALUES(?,?)", ("customer-1", "Customer"))
                conn.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                             ("o-phys", "O-2", "customer-1", "pending", 2000))
                conn.execute("INSERT INTO order_items(id,order_id,product_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?,?)",
                             ("oi-phys", "o-phys", physical_id, "print", 1, 2000))
                conn.commit()
            invoices = InvoiceService(db, td)
            invoice_id = invoices.auto_create_for_order("o-phys")
            invoices.record_payment(invoice_id, 2000, method="test")
            service = DigitalDeliveryService(db, td)
            self.assertEqual(service.tokens_for_customer("customer-1", include_inactive=True), [])


class DigitalTriggerCompatTests(unittest.TestCase):
    """Checkout under the app-boot price triggers.

    PriceHistoryService.ensure_schema() installs trg_order_price_snapshot
    (copies quote_items -> order_items on order INSERT) and
    trg_order_items_immutable_update (aborts ANY UPDATE of order_items).
    Checkout must therefore record license_key at INSERT time and must not
    insert line items a second time when the trigger already copied them.
    """

    def _commerce(self, db):
        return CustomerCommerceService(db, _Accounts(), ProductService(db), _Quotes(db), ShopSettingsService(db), auth=None)

    def test_boot_triggers_keep_single_item_with_license(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            PriceHistoryService(db).ensure_schema()
            _, product_id = make_digital_product(db, td)
            commerce = self._commerce(db)
            row, _, _, shipping_cents, _, total_cents = commerce.create_order(
                "user-1", [{"productId": product_id, "quantity": 1, "license": "commercial"}], {}, "")
            self.assertEqual(shipping_cents, 0)
            with db.connect() as conn:
                items = conn.execute(
                    "SELECT license_key,unit_price_cents FROM order_items WHERE order_id=?",
                    (row["id"],)).fetchall()
                quote_items = conn.execute(
                    "SELECT license_key FROM quote_items WHERE quote_id=?",
                    (row["quote_id"],)).fetchall()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["license_key"], "commercial")
            self.assertEqual(items[0]["unit_price_cents"], 4500)
            self.assertEqual(len(quote_items), 1)
            self.assertEqual(quote_items[0]["license_key"], "commercial")
            self.assertGreater(total_cents, 0)

    def test_boot_triggers_grant_downloads_after_payment(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            PriceHistoryService(db).ensure_schema()
            service, product_id = make_digital_product(db, td)
            commerce = self._commerce(db)
            row, _, _, _, _, total_cents = commerce.create_order(
                "user-1", [{"productId": product_id, "quantity": 1, "license": "personal"}], {}, "")
            invoices = InvoiceService(db, td)
            invoice_id = invoices.auto_create_for_order(row["id"])
            invoices.record_payment(invoice_id, total_cents, method="test", reference="ref-boot")
            tokens = service.tokens_for_customer("customer-1")
            self.assertEqual(len(tokens), 1)
            self.assertTrue(tokens[0]["is_active"])


class DigitalFulfillmentTests(unittest.TestCase):
    def test_digital_only_orders_skip_fulfillment(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, digital_id = make_digital_product(db, td)
            _, physical_id = make_physical_product(db)
            fulfillment = FulfillmentService(db)
            with db.connect() as conn:
                conn.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                             ("o-dig", "O-3", "customer-1", "pending", 1500))
                conn.execute("INSERT INTO order_items(id,order_id,product_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?,?)",
                             ("oi-d1", "o-dig", digital_id, "files", 1, 1500))
                conn.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                             ("o-phys2", "O-4", "customer-1", "pending", 2000))
                conn.execute("INSERT INTO order_items(id,order_id,product_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?,?)",
                             ("oi-p1", "o-phys2", physical_id, "print", 1, 2000))
                conn.commit()
            with self.assertRaises(ValueError):
                fulfillment.ensure("o-dig", "shipping")
            fid = fulfillment.ensure("o-phys2", "pickup")
            self.assertTrue(fid)


class _Security:
    def context(self, token, permission=None):
        if token == "customer-token":
            return {"id": "user-1", "account_type": "customer"}
        raise PermissionError("Invalid or expired session")


class DigitalWsgiRouteTests(unittest.TestCase):
    def _api(self, db, td):
        core = SimpleNamespace(
            products=ProductService(db),
            accounts=_Accounts(),
            digital_delivery=DigitalDeliveryService(db, td),
            security=_Security(),
        )
        return FabOSAPI(core)

    def _auth(self):
        return {"Authorization": "Bearer customer-token"}

    def test_customer_downloads_list_and_file(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td, design_type="cnc")
            order_id, _ = DigitalDeliveryServiceTests._order_with_item(self, db, product_id)
            (grant,) = service.grant_for_order(order_id)
            api = self._api(db, td)
            result = api.request("GET", "/api/v1/customer/downloads", headers=self._auth())
            self.assertEqual(result["status"], 200)
            downloads = result["data"]["downloads"]
            self.assertEqual(len(downloads), 1)
            self.assertEqual(downloads[0]["design_type"], "cnc")
            self.assertIn("/api/v1/customer/downloads/", downloads[0]["download_url"])
            # Bearer file download serves the bytes; never a direct file URL.
            file_result = api.request("GET", "/api/v1/customer/downloads/%s/file" % grant["token"])
            self.assertEqual(file_result["status"], 200)
            self.assertEqual(file_result["data"]["_wsgi_file"]["bytes"], b"dxf content")
            self.assertEqual(file_result["data"]["_wsgi_file"]["filename"], "part.dxf")
            # Unknown token 404s; unauthenticated list 401s.
            missing = api.request("GET", "/api/v1/customer/downloads/nope/file")
            self.assertEqual(missing["status"], 404)
            denied = api.request("GET", "/api/v1/customer/downloads")
            self.assertEqual(denied["status"], 401)

    def test_catalog_design_type_filter(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            _, cnc_id = make_digital_product(db, td, design_type="cnc", name="CNC Files")
            _, laser_id = make_digital_product(db, td, design_type="laser", name="Laser Files")
            api = self._api(db, td)
            result = api.request("GET", "/api/v1/catalog?design_type=cnc")
            self.assertEqual(result["status"], 200)
            ids = [product["id"] for product in result["data"]["products"]]
            self.assertIn(cnc_id, ids)
            self.assertNotIn(laser_id, ids)
            product = next(p for p in result["data"]["products"] if p["id"] == cnc_id)
            self.assertEqual(product["product_type"], "digital")
            self.assertEqual(product["design_type"], "cnc")
            self.assertEqual(len(product["license_options"]), 2)

    def test_customer_order_detail_carries_downloads(self):
        with tempfile.TemporaryDirectory() as td:
            db = make_db(str(Path(td) / "fabos.db"))
            service, product_id = make_digital_product(db, td)
            order_id, item_id = DigitalDeliveryServiceTests._order_with_item(self, db, product_id)
            service.grant_for_order(order_id)

            class _Orders:
                def get_for_user(self, user_id, order_id):
                    with db.connect() as conn:
                        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
                        items = conn.execute(
                            "SELECT oi.*,p.name product_name FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?",
                            (order_id,)).fetchall()
                    return order, items

                def dossier(self, order_id):
                    return {"designs": []}

            core = SimpleNamespace(
                products=ProductService(db),
                accounts=_Accounts(),
                orders=_Orders(),
                digital_delivery=service,
                fulfillment=None,
                security=_Security(),
            )
            api = FabOSAPI(core)
            result = api.request("GET", "/api/v1/customer/orders/%s" % order_id, headers=self._auth())
            self.assertEqual(result["status"], 200)
            self.assertTrue(result["data"]["items"][0]["is_digital"])
            self.assertEqual(result["data"]["items"][0]["license_key"], "personal")
            self.assertEqual(len(result["data"]["downloads"]), 1)
            self.assertIn("/file", result["data"]["downloads"][0]["download_url"])


if __name__ == "__main__":
    unittest.main()
