"""Customer checkout orchestration over the existing quote/order pipeline."""
import json
import uuid
from datetime import date, timedelta

from fabos_core.services.commerce_pricing import CommercePricingService
from fabos_core.services.quotes import ensure_quote_audit_schema


class CheckoutService:
    """Create real FabOS orders without making the storefront the source of truth."""

    def __init__(self, database, accounts, products, shop_settings):
        self.database = database
        self.accounts = accounts
        self.products = products
        self.shop_settings = shop_settings

    def _customer(self, user_id):
        user = self.accounts.get_user(user_id)
        if not user or not user["active"] or user["account_type"] != "customer":
            raise PermissionError("Customer account required")
        customer = self.accounts.customer_for_user(user_id)
        if not customer:
            raise PermissionError("Customer account is not linked to a customer record")
        return customer

    def _require_storefront(self):
        if str(self.shop_settings.get("storefront_enabled", "true")).lower() != "true":
            raise PermissionError("Storefront is currently unavailable")
        if str(self.shop_settings.get("storefront_ordering_enabled", "true")).lower() != "true":
            raise PermissionError("Customer ordering is currently disabled")

    def create_order(self, user_id, items, shipping_address, notes="", shipping_mode=None):
        self._require_storefront()
        customer = self._customer(user_id)
        if not isinstance(shipping_address, dict):
            raise ValueError("Shipping address is required")
        required = ("address", "city", "state", "zip")
        if any(not str(shipping_address.get(key, "")).strip() for key in required):
            raise ValueError("Complete shipping address is required")

        pricing = CommercePricingService(self.products, self.shop_settings)
        estimate = pricing.estimate(items, shipping_mode)
        # Converge with CustomerCommerceService.create_order: enforce the same
        # configured order guards (minimum order amount, free-shipping threshold).
        subtotal_cents = int(estimate["subtotal_cents"] or 0)
        minimum_order_cents = int(float(self.shop_settings.get("minimum_order_cents", "0") or 0))
        if subtotal_cents < minimum_order_cents:
            raise ValueError("Order subtotal is below the configured minimum order amount")
        shipping_cents = int(estimate["shipping_cents"] or 0)
        free_threshold_cents = int(float(self.shop_settings.get("free_shipping_threshold_cents", "0") or 0))
        if free_threshold_cents > 0 and subtotal_cents >= free_threshold_cents:
            shipping_cents = 0
        total_cents = subtotal_cents + int(estimate["tax_cents"] or 0) + max(0, shipping_cents)
        clean_items = []
        for item in items or []:
            product_id = str(item.get("product_id") or item.get("productId") or "").strip()
            product = self.products.get(product_id)
            if product is None or not self.products.is_customer_eligible(product_id):
                raise ValueError("Product is not available for customer ordering")
            quantity = int(item.get("quantity", 0))
            if quantity <= 0 or quantity > 1000:
                raise ValueError("Quantity must be between 1 and 1000")
            variant_id = str(item.get("variant_id") or item.get("variantId") or "").strip()
            row = dict(product)
            unit_price = int(row.get("price_cents") or 0)
            material = row.get("material") or ""
            color = row.get("color") or ""
            minutes = int(row.get("estimated_minutes") or 0)
            filament = float(row.get("estimated_filament_g") or 0)
            description = row.get("name") or "Product"
            if variant_id:
                variant = next((candidate for candidate in self.products.variants(product_id) if str(candidate["id"]) == variant_id), None)
                if not variant or not int(variant["active"]):
                    raise ValueError("Product variant not found")
                unit_price = int(variant["price_cents"] or 0)
                material = variant["material"] or material
                color = variant["color"] or color
                minutes = int(variant["estimated_minutes"] or minutes)
                filament = float(variant["estimated_filament_g"] or filament)
                description += " · " + str(variant["name"])
            if unit_price <= 0:
                raise ValueError("Product price is not available for customer ordering")
            clean_items.append({
                "product_id": row["id"],
                "variant_id": variant_id or None,
                "description": description,
                "quantity": quantity,
                "unit_price_cents": unit_price,
                "material": material,
                "color": color,
                "estimated_minutes": minutes,
                "estimated_filament_g": filament,
            })

        with self.database.connect() as conn:
            # BEGIN IMMEDIATE serializes the order-number sequence so concurrent
            # checkouts cannot mint the same order number (mirrors
            # CustomerCommerceService.create_order).
            ensure_quote_audit_schema(self.database)
            conn.execute("BEGIN IMMEDIATE")
            prefix = "O-" + date.today().strftime("%Y%m") + "-"
            row = conn.execute(
                "SELECT order_number FROM orders WHERE order_number LIKE ? ORDER BY order_number DESC LIMIT 1",
                (prefix + "%",),
            ).fetchone()
            seq = int(row[0].split("-")[-1]) + 1 if row else 1
            quote_id = str(uuid.uuid4())
            order_id = str(uuid.uuid4())
            quote_number_prefix = "Q-" + date.today().strftime("%Y%m") + "-"
            qrow = conn.execute(
                "SELECT quote_number FROM quotes WHERE quote_number LIKE ? ORDER BY quote_number DESC LIMIT 1",
                (quote_number_prefix + "%",),
            ).fetchone()
            qseq = int(qrow[0].split("-")[-1]) + 1 if qrow else 1
            quote_number = quote_number_prefix + ("%04d" % qseq)
            order_number = prefix + ("%04d" % seq)
            quote_expires_at = (date.today() + timedelta(days=14)).isoformat()
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,expires_at,notes) VALUES(?,?,?,?,?,?,?)",
                (quote_id, quote_number, customer["id"], "approved", total_cents,
                 quote_expires_at, notes or ""),
            )
            for item in clean_items:
                quote_item_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO quote_items(id,quote_id,product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (quote_item_id, quote_id, item["product_id"], item["variant_id"], item["description"], item["quantity"],
                     item["unit_price_cents"], item["material"], item["color"], item["estimated_minutes"],
                     item["estimated_filament_g"]),
                )
                # Audit trail: mirror QuoteService.save so checkout-created
                # quotes carry the same price snapshots and version history
                # as quotes created through the quote workflow.
                conn.execute(
                    "INSERT INTO quote_price_snapshots(id,quote_id,quote_item_id,unit_price_cents,pricing_mode,calculation_json) VALUES(?,?,?,?,?,?)",
                    (str(uuid.uuid4()), quote_id, quote_item_id, int(item["unit_price_cents"] or 0), "manual", None),
                )
            snapshot = {
                "customer_id": customer["id"],
                "status": "approved",
                "total_cents": total_cents,
                "expires_at": quote_expires_at,
                "notes": notes or "",
                "items": [dict(item) for item in clean_items],
            }
            conn.execute(
                "INSERT INTO quote_versions(id,quote_id,version,status,total_cents,expires_at,notes,snapshot_json) VALUES(?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), quote_id, 1, "approved", total_cents, quote_expires_at,
                 notes or "", json.dumps(snapshot, sort_keys=True, default=str)),
            )
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,quote_id,status,due_at,total_cents,tax_cents,shipping_cents,shipping_address_json,checkout_notes,checkout_channel) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (order_id, order_number, customer["id"], quote_id, "pending",
                 (date.today() + timedelta(days=7)).isoformat(), total_cents,
                 estimate["tax_cents"], shipping_cents, json.dumps(shipping_address, sort_keys=True),
                 notes or "", "website"),
            )
            for item in clean_items:
                conn.execute(
                    "INSERT INTO order_items(id,order_id,product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), order_id, item["product_id"], item["variant_id"], item["description"],
                     item["quantity"], item["unit_price_cents"], item["material"], item["color"],
                     item["estimated_minutes"], item["estimated_filament_g"]),
                )
            conn.commit()
        return {
            "id": order_id,
            "order_number": order_number,
            "status": "pending",
            "subtotal_cents": estimate["subtotal_cents"],
            "tax_cents": estimate["tax_cents"],
            "shipping_cents": shipping_cents,
            "total_cents": total_cents,
            "currency": estimate.get("currency", "USD"),
        }
