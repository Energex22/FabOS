"""Customer-facing commerce operations for the public FabOS API."""

import json
import logging
import os
import sqlite3
import tempfile
import uuid
import hashlib
import re
from pathlib import Path
from datetime import date, timedelta

from fabos_core.services.commerce_pricing import calculated_shipping_cents

logger = logging.getLogger(__name__)


def _is_digital_product(products, product_id):
    """Whether a product is digital. Tolerates product services that predate
    digital support (e.g. test fakes) — those only ever sell physical goods."""
    checker = getattr(products, "is_digital", None)
    return bool(checker(product_id)) if callable(checker) else False


def _digital_license_options(products, product_id):
    getter = getattr(products, "digital_license_options", None)
    return list(getter(product_id) or []) if callable(getter) else []


class CustomerCommerceService:
    def __init__(self, database, accounts, products, quotes, shop_settings, auth=None, invoices=None):
        self.database = database
        self.accounts = accounts
        self.products = products
        self.quotes = quotes
        self.shop_settings = shop_settings
        self.auth = auth
        # Optional InvoiceService, wired by FabOSApplication. When present,
        # order creation auto-creates the order's invoice (best-effort: a
        # failed invoice must never break the order itself).
        self.invoices = invoices

    def register_customer(self, name, email, password, phone=""):
        if self.auth is None:
            raise RuntimeError("Authentication service is required")
        if str(self.shop_settings.get("storefront_enabled", "true")).lower() != "true":
            raise PermissionError("Storefront is currently unavailable")
        if str(self.shop_settings.get("customer_registration_enabled", "true")).lower() != "true":
            raise PermissionError("Customer registration is currently disabled")
        name = str(name or "").strip()
        email = str(email or "").strip().lower()
        phone = str(phone or "").strip()
        if not name:
            raise ValueError("Name is required")
        if not email or "@" not in email:
            raise ValueError("A valid email is required")
        if self.accounts.get_by_email(email):
            raise ValueError("An account with that email already exists")
        customer_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        username = "customer-" + user_id
        password_hash = self.auth.hash_password(password)
        try:
            with self.database.connect() as conn:
                conn.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", (customer_id, name, email, phone, ""))
                conn.execute("INSERT INTO users(id,username,password_hash,email,account_type,active) VALUES(?,?,?,?,?,1)", (user_id, username, password_hash, email, "customer"))
                conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)", (user_id, customer_id))
                conn.commit()
        except sqlite3.IntegrityError as exc:
            # The get_by_email pre-check races with concurrent registrations.
            # Re-check before reporting: only a genuine duplicate becomes a
            # graceful 409, anything else still surfaces as an error.
            if self.accounts.get_by_email(email):
                raise ValueError("An account with that email already exists") from exc
            raise
        result = self.auth.login(email, password)
        if not result:
            raise RuntimeError("Customer account could not be authenticated after creation")
        return result

    def _ensure_public_quote_files_schema(self):
        with self.database.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quote_request_files(
                    id TEXT PRIMARY KEY,
                    quote_id TEXT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quote_request_files_quote ON quote_request_files(quote_id)")
            conn.commit()

    def create_public_quote_request(self, name, email, project, file_name="", file_bytes=None):
        """Create a storefront lead/quote without requiring an account."""
        self._require_storefront()
        name = str(name or "").strip()
        email = str(email or "").strip().lower()
        if not name:
            raise ValueError("Name is required")
        if not email or "@" not in email:
            raise ValueError("A valid email is required")
        project = project if isinstance(project, dict) else {}
        idea = str(project.get("idea") or "").strip()
        if not idea:
            raise ValueError("Project idea is required")
        quantity = self._positive_quantity(project.get("quantity", 1))
        dimensions = str(project.get("dimensions") or "").strip()
        material = str(project.get("material") or "").strip()
        notes = str(project.get("notes") or "").strip()
        description_parts = [idea]
        if dimensions:
            description_parts.append("Dimensions: " + dimensions)
        if material:
            description_parts.append("Material: " + material)
        if notes:
            description_parts.append("Notes: " + notes)
        # Validate the reference file before creating any records so a rejected
        # file cannot leave an orphaned customer + draft quote behind.
        validated_file = None
        if file_bytes:
            allowed = {".stl", ".3mf", ".obj", ".step", ".stp"}
            original = Path(str(file_name or "reference_model")).name
            suffix = Path(original).suffix.lower()
            if suffix not in allowed:
                raise ValueError("Unsupported reference file type")
            if len(file_bytes) > 25 * 1024 * 1024:
                raise ValueError("Reference file exceeds the 25 MB limit")
            # Structural validation mirrors the FastAPI multipart upload path
            # (customer_api_writes._validate_model_file): stage the decoded
            # bytes in a temp file and reject empty/malformed/zip-bomb files
            # before any customer or quote rows are written.
            from fabos_core.services.customer_api_writes import _validate_model_file
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            try:
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(file_bytes)
                _validate_model_file(tmp_path, suffix)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", original).strip("._") or "reference_model"
            validated_file = (original, safe)
        with self.database.connect() as conn:
            customer = conn.execute("SELECT * FROM customers WHERE lower(email)=?", (email,)).fetchone()
        if customer is None:
            customer_id = str(uuid.uuid4())
            with self.database.connect() as conn:
                conn.execute(
                    "INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",
                    (customer_id, name, email, str(project.get("phone") or "").strip(), ""),
                )
                conn.commit()
        else:
            customer_id = customer["id"]
        quote_id = self.quotes.save(
            {"customer_id": customer_id, "status": "draft", "notes": notes},
            [{
                "product_id": None,
                "description": "\n".join(description_parts),
                "quantity": quantity,
                "unit_price_cents": 0,
                "material": material,
                "color": "",
                "estimated_minutes": 0,
                "estimated_filament_g": 0,
            }],
        )
        self._ensure_public_quote_files_schema()
        if validated_file:
            original, safe = validated_file
            root = Path(self.database.path).resolve().parent / "Quote Uploads"
            root.mkdir(parents=True, exist_ok=True)
            target = root / (quote_id + "_" + safe)
            target.write_bytes(file_bytes)
            digest = hashlib.sha256(file_bytes).hexdigest()
            with self.database.connect() as conn:
                conn.execute(
                    "INSERT INTO quote_request_files(id,quote_id,original_name,stored_path,bytes,sha256) VALUES(?,?,?,?,?,?)",
                    (str(uuid.uuid4()), quote_id, original, str(target), len(file_bytes), digest),
                )
                conn.commit()
        return self.quotes.get(quote_id)

    def _customer(self, user_id):
        user = self.accounts.get_user(user_id)
        if not user or not int(user["active"]):
            raise PermissionError("Authenticated user is inactive or not found")
        if user["account_type"] != "customer":
            raise PermissionError("Customer account required")
        customer = self.accounts.customer_for_user(user_id)
        if not customer:
            raise PermissionError("Customer account is not linked")
        return customer

    def _require_storefront(self, ordering=False):
        if str(self.shop_settings.get("storefront_enabled", "true")).lower() != "true":
            raise PermissionError("Storefront is currently unavailable")
        if ordering and str(self.shop_settings.get("storefront_ordering_enabled", "true")).lower() != "true":
            raise PermissionError("Customer ordering is currently disabled")

    @staticmethod
    def _positive_quantity(value):
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            raise ValueError("Quantity must be a positive integer")
        if quantity < 1 or quantity > 1000:
            raise ValueError("Quantity must be between 1 and 1000")
        return quantity

    @staticmethod
    def _shipping_address(value):
        if not isinstance(value, dict):
            raise ValueError("Shipping address is required")
        address = {
            "address": str(value.get("address") or "").strip(),
            "city": str(value.get("city") or "").strip(),
            "state": str(value.get("state") or "").strip(),
            "zip": str(value.get("zip") or "").strip(),
        }
        if not all(address.values()):
            raise ValueError("Complete shipping address is required")
        return address

    def create_quote_request(self, user_id, project):
        self._require_storefront()
        customer = self._customer(user_id)
        idea = str(project.get("idea") or "").strip()
        if not idea:
            raise ValueError("Project idea is required")
        quantity = self._positive_quantity(project.get("quantity", 1))
        dimensions = str(project.get("dimensions") or "").strip()
        material = str(project.get("material") or "").strip()
        notes = str(project.get("notes") or "").strip()
        description_parts = [idea]
        if dimensions:
            description_parts.append("Dimensions: " + dimensions)
        if material:
            description_parts.append("Material: " + material)
        if notes:
            description_parts.append("Notes: " + notes)
        quote_id = self.quotes.save({"customer_id": customer["id"], "status": "draft", "notes": notes}, [{"product_id": None, "description": "\n".join(description_parts), "quantity": quantity, "unit_price_cents": 0, "material": material, "color": "", "estimated_minutes": 0, "estimated_filament_g": 0}])
        return self.quotes.get_for_user(user_id, quote_id)

    def _resolve_order_item(self, requested):
        """Validate one requested cart item and resolve its price.

        Returns (resolved_item_dict, is_digital). Digital products require a
        valid license_key (personal vs commercial pricing); the license price
        becomes the unit price and the license_key is recorded on the line
        item. Raises ValueError on anything invalid.
        """
        if not isinstance(requested, dict):
            raise ValueError("Invalid order item")
        product_id = str(requested.get("productId") or requested.get("product_id") or "").strip()
        if not product_id:
            raise ValueError("Each order item requires a productId")
        product = self.products.get(product_id)
        if not product or not self.products.is_customer_eligible(product_id):
            raise ValueError("Product is not available for customer ordering")
        is_digital = _is_digital_product(self.products, product_id)
        quantity = self._positive_quantity(requested.get("quantity", 1))
        variant_id = str(requested.get("variantId") or requested.get("variant_id") or "").strip()
        configuration = requested.get("configuration") or {}
        if not isinstance(configuration, dict):
            raise ValueError("Item configuration must be an object")
        material = str(configuration.get("material") or requested.get("material") or "").strip()
        color = str(configuration.get("color") or requested.get("color") or "").strip()
        unit_price_cents = int(product["price_cents"] or 0)
        estimated_minutes = int(product["estimated_minutes"] or 0)
        estimated_filament_g = float(product["estimated_filament_g"] or 0)
        description = str(product["name"])
        license_key = None
        if is_digital:
            if variant_id:
                raise ValueError("Product variants do not apply to digital products")
            license_key = str(requested.get("license") or requested.get("license_key") or requested.get("licenseKey") or "").strip().lower()
            option = next((candidate for candidate in _digital_license_options(self.products, product_id)
                           if str(candidate["license_key"]) == license_key), None)
            if not option:
                raise ValueError("A valid license option is required for this digital product")
            unit_price_cents = int(option["price_cents"] or 0)
            description += " · " + str(option["label"] or option["license_key"])
            material, color, estimated_minutes, estimated_filament_g = "", "", 0, 0.0
        elif variant_id:
            variant = next((candidate for candidate in self.products.variants(product_id) if str(candidate["id"]) == variant_id), None)
            if not variant or not int(variant["active"]):
                raise ValueError("Product variant not found")
            unit_price_cents = int(variant["price_cents"] or 0)
            material = material or str(variant["material"] or "")
            color = color or str(variant["color"] or "")
            estimated_minutes = int(variant["estimated_minutes"] or estimated_minutes)
            estimated_filament_g = float(variant["estimated_filament_g"] or estimated_filament_g)
            description += " · " + str(variant["name"])
        if unit_price_cents <= 0:
            raise ValueError("Product price is not available for customer ordering")
        return ({
            "product_id": product_id, "variant_id": variant_id or None, "description": description,
            "quantity": quantity, "unit_price_cents": unit_price_cents, "material": material,
            "color": color, "estimated_minutes": estimated_minutes,
            "estimated_filament_g": estimated_filament_g, "license_key": license_key,
            "is_digital": is_digital,
        }, is_digital)

    def _calculate_totals(self, user_id, items, shipping_address, notes=""):
        """Shared validation + totals math for create_order and preview.

        Runs every order-creation guard (storefront enabled, customer account,
        shipping address, item resolution, minimum order amount) and computes
        subtotal/shipping/tax/total WITHOUT persisting anything. create_order
        and preview_order_totals both funnel through here so the preview can
        never drift from what checkout will actually charge.
        Returns (customer, shipping_address, resolved_items, subtotal_cents,
        shipping_cents, tax_cents, total_cents).
        """
        self._require_storefront(ordering=True)
        customer = self._customer(user_id)
        if not isinstance(items, list) or not items:
            raise ValueError("At least one order item is required")
        if len(items) > 100:
            raise ValueError("An order may contain at most 100 line items")
        resolved = [self._resolve_order_item(requested) for requested in items]
        resolved_items = [item for item, _ in resolved]
        all_digital = all(is_digital for _, is_digital in resolved)
        if all_digital:
            # Digital-only orders need no shipping address and are never
            # charged shipping — the files are delivered as downloads.
            shipping_address = {"address": "", "city": "", "state": "", "zip": ""}
        else:
            shipping_address = self._shipping_address(shipping_address)
        subtotal_cents = 0
        for item in resolved_items:
            subtotal_cents += int(item["unit_price_cents"]) * int(item["quantity"])
        minimum_order_cents = int(float(self.shop_settings.get("minimum_order_cents", "0") or 0))
        if subtotal_cents < minimum_order_cents:
            raise ValueError("Order subtotal is below the configured minimum order amount")
        if all_digital:
            shipping_cents = 0
        else:
            shipping_mode = str(self.shop_settings.get("shipping_mode", "calculated") or "calculated").lower()
            if shipping_mode == "free":
                shipping_cents = 0
            elif shipping_mode == "flat":
                shipping_cents = int(float(self.shop_settings.get("shipping_flat_cents", "0") or 0))
            else:
                weight_kg = sum(float(item["estimated_filament_g"] or 0) * int(item["quantity"]) for item in resolved_items) / 1000.0
                # Shared helper with CommercePricingService so the estimate and the
                # charged shipping always agree to the cent (L5).
                shipping_cents = calculated_shipping_cents(
                    self.shop_settings.get("shipping_calculated_base_cents", "0"),
                    self.shop_settings.get("shipping_calculated_per_kg_cents", "0"),
                    weight_kg,
                )
                free_threshold = int(float(self.shop_settings.get("free_shipping_threshold_cents", "0") or 0))
                if free_threshold > 0 and subtotal_cents >= free_threshold:
                    shipping_cents = 0
        tax_percent = float(self.shop_settings.get("default_tax_percent", "0") or 0)
        tax_cents = int(round(subtotal_cents * max(0.0, tax_percent) / 100.0))
        total_cents = subtotal_cents + max(0, shipping_cents) + tax_cents
        return customer, shipping_address, resolved_items, subtotal_cents, shipping_cents, tax_cents, total_cents

    def preview_order_totals(self, user_id, items, shipping_address, notes=""):
        """Dry-run of create_order: validate the inputs and return the item
        totals + tax + shipping WITHOUT creating a quote, order, or invoice."""
        _, _, resolved_items, subtotal_cents, shipping_cents, tax_cents, total_cents = self._calculate_totals(
            user_id, items, shipping_address, notes)
        return {
            "items": [
                {"product_id": item["product_id"], "variant_id": item["variant_id"],
                 "description": item["description"], "quantity": item["quantity"],
                 "unit_price_cents": item["unit_price_cents"],
                 "line_total_cents": int(item["quantity"]) * int(item["unit_price_cents"]),
                 "license_key": item.get("license_key"), "is_digital": bool(item.get("is_digital"))}
                for item in resolved_items
            ],
            "subtotal_cents": subtotal_cents,
            "shipping_cents": max(0, shipping_cents),
            "tax_cents": tax_cents,
            "total_cents": total_cents,
            "currency": str(self.shop_settings.get("currency_code", "USD") or "USD"),
        }

    def _auto_create_invoice(self, order_id):
        """Phase 3: every order gets its invoice at birth (best-effort)."""
        if self.invoices is None:
            return None
        try:
            return self.invoices.auto_create_for_order(order_id)
        except Exception:
            logger.warning("invoice auto-creation failed for order %s", order_id, exc_info=True)
            return None

    def create_order(self, user_id, items, shipping_address, notes=""):
        customer, shipping_address, resolved_items, subtotal_cents, shipping_cents, tax_cents, total_cents = self._calculate_totals(
            user_id, items, shipping_address, notes)
        quote_id = self.quotes.save({"customer_id": customer["id"], "status": "approved", "notes": str(notes or "").strip()}, resolved_items)
        order_id = str(uuid.uuid4())
        prefix = "O-" + date.today().strftime("%Y%m") + "-"
        turnaround_days = int(float(self.shop_settings.get("default_turnaround_days", "7") or 7))
        due_at = (date.today() + timedelta(days=max(0, turnaround_days))).isoformat()
        try:
            with self.database.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT order_number FROM orders WHERE order_number LIKE ? ORDER BY order_number DESC LIMIT 1", (prefix + "%",)).fetchone()
                sequence = int(row[0].split("-")[-1]) + 1 if row else 1
                order_number = prefix + ("%04d" % sequence)
                conn.execute("""INSERT INTO orders
                    (id,order_number,customer_id,quote_id,status,due_at,total_cents,tax_cents,shipping_cents,shipping_address_json,checkout_notes,checkout_channel)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (order_id, order_number, customer["id"], quote_id, "pending", due_at, total_cents, tax_cents, shipping_cents, json.dumps(shipping_address), str(notes or "").strip(), "website"))
                # The trg_order_price_snapshot trigger (installed at app boot)
                # already copied the quote's line items — including license_key
                # — into order_items when the order row was inserted. Only
                # insert manually where that trigger is absent (e.g. test
                # databases); otherwise every line item would duplicate.
                trigger_copied = conn.execute(
                    "SELECT COUNT(*) FROM order_items WHERE order_id=?", (order_id,)
                ).fetchone()[0]
                for item in resolved_items:
                    if trigger_copied:
                        break
                    item_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO order_items
                        (id,order_id,product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g,license_key)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            item_id,
                            order_id,
                            item["product_id"],
                            item["variant_id"],
                            item["description"],
                            item["quantity"],
                            item["unit_price_cents"],
                            item["material"],
                            item["color"],
                            item["estimated_minutes"],
                            item["estimated_filament_g"],
                            item.get("license_key"),
                        ),
                    )
                conn.commit()
        except Exception:
            # The quote is created before the order transaction so it can carry
            # the resolved price snapshot. If the order transaction fails,
            # remove the approved quote rather than leaving an orphan.
            with self.database.connect() as cleanup:
                cleanup.execute("DELETE FROM quotes WHERE id=?", (quote_id,))
                cleanup.commit()
            raise
        # Phase 3: the order's invoice is created at birth (idempotent,
        # best-effort — a failed invoice must never break the order).
        self._auto_create_invoice(order_id)
        row, saved_items = self._order_for_customer(user_id, order_id)
        return row, saved_items, subtotal_cents, shipping_cents, tax_cents, total_cents

    def _order_for_customer(self, user_id, order_id):
        customer = self._customer(user_id)
        with self.database.connect() as conn:
            row = conn.execute("SELECT o.*,COALESCE(q.quote_number,'') quote_number FROM orders o LEFT JOIN quotes q ON q.id=o.quote_id WHERE o.id=? AND o.customer_id=?", (order_id, customer["id"])).fetchone()
            if not row:
                raise KeyError("Order not found")
            items = conn.execute("SELECT oi.*,p.name product_name,v.name variant_name FROM order_items oi LEFT JOIN products p ON p.id=oi.product_id LEFT JOIN product_variants v ON v.id=oi.variant_id WHERE oi.order_id=? ORDER BY oi.rowid", (order_id,)).fetchall()
        return row, items
