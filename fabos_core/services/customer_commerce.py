"""Customer-facing commerce operations for the public FabOS API."""

import json
import uuid
from datetime import date, timedelta


class CustomerCommerceService:
    def __init__(self, database, accounts, products, quotes, shop_settings, auth=None):
        self.database = database
        self.accounts = accounts
        self.products = products
        self.quotes = quotes
        self.shop_settings = shop_settings
        self.auth = auth

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
        with self.database.connect() as conn:
            conn.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", (customer_id, name, email, phone, ""))
            conn.execute("INSERT INTO users(id,username,password_hash,email,account_type,active) VALUES(?,?,?,?,?,1)", (user_id, username, password_hash, email, "customer"))
            conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)", (user_id, customer_id))
            conn.commit()
        result = self.auth.login(email, password)
        if not result:
            raise RuntimeError("Customer account could not be authenticated after creation")
        return result

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

    def create_order(self, user_id, items, shipping_address, notes=""):
        self._require_storefront(ordering=True)
        customer = self._customer(user_id)
        shipping_address = self._shipping_address(shipping_address)
        if not isinstance(items, list) or not items:
            raise ValueError("At least one order item is required")
        if len(items) > 100:
            raise ValueError("An order may contain at most 100 line items")
        resolved_items = []
        subtotal_cents = 0
        for requested in items:
            if not isinstance(requested, dict):
                raise ValueError("Invalid order item")
            product_id = str(requested.get("productId") or requested.get("product_id") or "").strip()
            if not product_id:
                raise ValueError("Each order item requires a productId")
            product = self.products.get(product_id)
            if not product or not self.products.is_customer_eligible(product_id):
                raise ValueError("Product is not available for customer ordering")
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
            if variant_id:
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
            subtotal_cents += unit_price_cents * quantity
            resolved_items.append({"product_id": product_id, "variant_id": variant_id or None, "description": description, "quantity": quantity, "unit_price_cents": unit_price_cents, "material": material, "color": color, "estimated_minutes": estimated_minutes, "estimated_filament_g": estimated_filament_g})
        minimum_order_cents = int(float(self.shop_settings.get("minimum_order_cents", "0") or 0))
        if subtotal_cents < minimum_order_cents:
            raise ValueError("Order subtotal is below the configured minimum order amount")
        quote_id = self.quotes.save({"customer_id": customer["id"], "status": "approved", "notes": str(notes or "").strip()}, resolved_items)
        shipping_mode = str(self.shop_settings.get("shipping_mode", "calculated") or "calculated").lower()
        if shipping_mode == "free":
            shipping_cents = 0
        elif shipping_mode == "flat":
            shipping_cents = int(float(self.shop_settings.get("shipping_flat_cents", "0") or 0))
        else:
            base = int(float(self.shop_settings.get("shipping_calculated_base_cents", "0") or 0))
            per_kg = float(self.shop_settings.get("shipping_calculated_per_kg_cents", "0") or 0)
            weight_kg = sum(float(item["estimated_filament_g"] or 0) * int(item["quantity"]) for item in resolved_items) / 1000.0
            shipping_cents = int(round(base + per_kg * weight_kg))
            free_threshold = int(float(self.shop_settings.get("free_shipping_threshold_cents", "0") or 0))
            if free_threshold > 0 and subtotal_cents >= free_threshold:
                shipping_cents = 0
        tax_percent = float(self.shop_settings.get("default_tax_percent", "0") or 0)
        tax_cents = int(round(subtotal_cents * max(0.0, tax_percent) / 100.0))
        total_cents = subtotal_cents + max(0, shipping_cents) + tax_cents
        order_id = str(uuid.uuid4())
        prefix = "O-" + date.today().strftime("%Y%m") + "-"
        turnaround_days = int(float(self.shop_settings.get("default_turnaround_days", "7") or 7))
        due_at = (date.today() + timedelta(days=max(0, turnaround_days))).isoformat()
        with self.database.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT order_number FROM orders WHERE order_number LIKE ? ORDER BY order_number DESC LIMIT 1", (prefix + "%",)).fetchone()
            sequence = int(row[0].split("-")[-1]) + 1 if row else 1
            order_number = prefix + ("%04d" % sequence)
            conn.execute("""INSERT INTO orders
                (id,order_number,customer_id,quote_id,status,due_at,total_cents,tax_cents,shipping_cents,shipping_address_json,checkout_notes,checkout_channel)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (order_id, order_number, customer["id"], quote_id, "pending", due_at, total_cents, tax_cents, shipping_cents, json.dumps(shipping_address), str(notes or "").strip(), "website"))
            for item in resolved_items:
                conn.execute(
                    """INSERT INTO order_items
                    (id,order_id,product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), order_id, item["product_id"], item["variant_id"],
                     item["description"], item["quantity"], item["unit_price_cents"],
                     item["material"], item["color"], item["estimated_minutes"],
                     item["estimated_filament_g"]),
                )
            conn.commit()
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
