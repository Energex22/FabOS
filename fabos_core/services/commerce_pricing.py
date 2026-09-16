"""Server-side storefront pricing boundary.

The website may display estimates, but it never becomes the source of truth for
product prices, tax, or shipping. All monetary values returned here are integer
cents so checkout can use the same values when an order is created later.
"""


class CommercePricingService:
    def __init__(self, products, shop_settings):
        self.products = products
        self.shop_settings = shop_settings

    @staticmethod
    def _money(value):
        try:
            return max(0, int(round(float(value))))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _quantity(value):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            raise ValueError("Quantity must be a positive integer")

    def _shipping_cents(self, mode=None, weight_g=0):
        mode = (mode or self.shop_settings.get("shipping_mode", "flat") or "flat").strip().lower()
        if mode == "free":
            return 0
        if mode == "flat":
            return self._money(self.shop_settings.get("shipping_flat_cents", "0"))
        if mode == "calculated":
            base = self._money(self.shop_settings.get("shipping_calculated_base_cents", "0"))
            per_kg = self._money(self.shop_settings.get("shipping_calculated_per_kg_cents", "0"))
            try:
                weight = max(0.0, float(weight_g or 0))
            except (TypeError, ValueError):
                weight = 0.0
            kilograms = weight / 1000.0
            return base + self._money(kilograms * per_kg)
        raise ValueError("Unsupported shipping mode")

    def estimate(self, items, shipping_mode=None, shipping_weight_g=0):
        if not isinstance(items, (list, tuple)) or not items:
            raise ValueError("At least one cart item is required")
        normalized = []
        subtotal = 0
        total_weight = 0
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Cart items must be objects")
            product_id = item.get("product_id") or item.get("id")
            if not product_id:
                raise ValueError("Cart item product_id is required")
            quantity = self._quantity(item.get("quantity", 1))
            product = self.products.get(product_id)
            if product is None:
                raise KeyError("Product not found: %s" % product_id)
            unit_cents = self._money(product["price_cents"])
            line_cents = unit_cents * quantity
            weight = self._money(product["estimated_filament_g"] or 0) * quantity
            subtotal += line_cents
            total_weight += weight
            normalized.append({
                "product_id": product_id,
                "name": product["name"],
                "quantity": quantity,
                "unit_price_cents": unit_cents,
                "line_total_cents": line_cents,
                "estimated_filament_g": weight,
            })
        if shipping_weight_g in (None, "", 0):
            shipping_weight_g = total_weight
        shipping = self._shipping_cents(shipping_mode, shipping_weight_g)
        try:
            tax_percent = max(0.0, float(self.shop_settings.get("default_tax_percent", "0") or 0))
        except (TypeError, ValueError):
            tax_percent = 0.0
        tax = self._money(subtotal * tax_percent / 100.0)
        return {
            "items": normalized,
            "subtotal_cents": subtotal,
            "tax_percent": tax_percent,
            "tax_cents": tax,
            "shipping_mode": (shipping_mode or self.shop_settings.get("shipping_mode", "flat") or "flat").strip().lower(),
            "shipping_weight_g": total_weight if shipping_weight_g in (None, "", 0) else float(shipping_weight_g),
            "shipping_cents": shipping,
            "total_cents": subtotal + tax + shipping,
            "currency": self.shop_settings.get("currency_symbol", "$"),
        }
