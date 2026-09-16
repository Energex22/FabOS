"""Customer-facing commerce operations for the public FabOS API."""

import uuid
from datetime import date


class CustomerCommerceService:
    def __init__(self, database, accounts, products, quotes, shop_settings):
        self.database = database
        self.accounts = accounts
        self.products = products
        self.quotes = quotes
        self.shop_settings = shop_settings

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

    @staticmethod
    def _positive_quantity(value):
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            raise ValueError("Quantity must be a positive integer")
        if quantity < 1 or quantity > 1000:
            raise ValueError("Quantity must be between 1 and 1000")
        return quantity

    def create_quote_request(self, user_id, project):
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
        quote_id = self.quotes.save(
            {"customer_id": customer["id"], "status": "draft", "notes": notes},
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
        return self.quotes.get_for_user(user_id, quote_id)

    def create_order(self, user_id, items, notes=""):
        customer = self._customer(user_id)
        if not isinstance(items, list) or not items:
            raise ValueError("At least one order item is required")
        resolved_items = []
        subtotal_cents = 0
        for requested in items:
            if not isinstance(requested, dict):
                raise ValueError("Invalid order item")
            product_id = str(requested.get("productId") or requested.get("product_id") or "").strip()
            if not product_id:
                raise ValueError("Each order item requires a productId")
            product = self.products.get(product_id)
            if not product:
                raise ValueError("Product not found")
            quantity = self._positive_quantity(requested.get("quantity", 1))
            variant_id = str(requested.get("variantId") or requested.get("variant_id") or "").strip()
            configuration = requested.get("configuration") or {}
            material = str(configuration.get("material") or requested.get("material") or "").strip()
            color = str(configuration.get("color") or requested.get("color") or "").strip()
            unit_price_cents = int(product["price_cents"] or 0)
            if variant_id:
                variant = next((candidate for candidate in self.products.variants(product_id) if str(candidate["id"]) == variant_id), None)
                if not variant or not int(variant["active"]):
                    raise ValueError("Product variant not found")
                unit_price_cents = int(variant["price_cents"] or 0)
                material = material or str(variant["material"] or "")
                color = color or str(variant["color"] or "")
            subtotal_cents += unit_price_cents * quantity
            resolved_items.append({
                "product_id": product_id,
                "description": str(product["name"]),
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "material": material,
                "color": color,
                "estimated_minutes": int(product["estimated_minutes"] or 0),
                "estimated_filament_g": float(product["estimated_filament_g"] or 0),
            })
        quote_id = self.quotes.save(
            {"customer_id": customer["id"], "status": "approved", "notes": str(notes or "").strip()},
            resolved_items,
        )
        shipping_cents = int(float(self.shop_settings.get("shipping_flat_cents", "0") or 0))
        total_cents = subtotal_cents + max(0, shipping_cents)
        order_id = str(uuid.uuid4())
        prefix = "O-" + date.today().strftime("%Y%m") + "-"
        with self.database.connect() as conn:
            row = conn.execute("SELECT order_number FROM orders WHERE order_number LIKE ? ORDER BY order_number DESC LIMIT 1", (prefix + "%",)).fetchone()
            sequence = int(row[0].split("-")[-1]) + 1 if row else 1
            order_number = prefix + ("%04d" % sequence)
            conn.execute("INSERT INTO orders(id,order_number,customer_id,quote_id,status,due_at,total_cents) VALUES(?,?,?,?,?,?,?)", (order_id, order_number, customer["id"], quote_id, "pending", None, total_cents))
            conn.commit()
        row, saved_items = self._order_for_customer(user_id, order_id)
        return row, saved_items, subtotal_cents, shipping_cents, total_cents

    def _order_for_customer(self, user_id, order_id):
        customer = self._customer(user_id)
        with self.database.connect() as conn:
            row = conn.execute("SELECT o.*,COALESCE(q.quote_number,'') quote_number FROM orders o LEFT JOIN quotes q ON q.id=o.quote_id WHERE o.id=? AND o.customer_id=?", (order_id, customer["id"])).fetchone()
            if not row:
                raise KeyError("Order not found")
            items = conn.execute("SELECT qi.*,p.name product_name FROM quote_items qi LEFT JOIN products p ON p.id=qi.product_id WHERE qi.quote_id=? ORDER BY qi.rowid", (row["quote_id"],)).fetchall()
        return row, items
