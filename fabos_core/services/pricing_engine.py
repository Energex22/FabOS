"""Configurable full-cost pricing engine for FabOS.

The engine estimates future selling prices without changing historical orders or
pricing snapshots. Business defaults live in ShopSettingsService so operators can
adjust the model without code changes.
"""


class PricingEngineService:
    def __init__(self, shop_settings):
        self.shop_settings = shop_settings

    def _number(self, key, default=0.0):
        try:
            return float(self.shop_settings.get(key, str(default)) or default)
        except (TypeError, ValueError):
            return float(default)

    def _enabled(self, key, default=False):
        value = str(self.shop_settings.get(key, "true" if default else "false") or "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    def estimate(self, estimated_minutes=0, estimated_filament_g=0, quantity=1,
                 rush=False, setup_minutes=0, post_process_minutes=0,
                 qc_minutes=0, overhead_percent=None):
        """Return a transparent cost/price estimate for a future quote or product."""
        minutes = max(0.0, float(estimated_minutes or 0))
        grams = max(0.0, float(estimated_filament_g or 0))
        qty = max(1, int(quantity or 1))

        machine_hourly = self._number("machine_hourly_cost", 0.35)
        material_cost_per_g = self._number("default_material_cost_per_g", 0.0)
        waste_percent = max(0.0, self._number("filament_waste_percent", 5.0))
        labor_hourly = self._number("labor_hourly_rate", 0.0)
        setup_rate = self._number("setup_labor_hourly_rate", labor_hourly)
        post_rate = self._number("post_process_labor_hourly_rate", labor_hourly)
        qc_rate = self._number("qc_labor_hourly_rate", labor_hourly)
        packaging = self._number("default_packaging_cost", 0.50)
        overhead = self._number("overhead_percent", 0.0) if overhead_percent is None else max(0.0, float(overhead_percent))
        margin = max(0.0, min(99.99, self._number("target_margin_percent", 60.0)))
        rush_multiplier = max(1.0, self._number("rush_multiplier", 1.0)) if rush else 1.0
        payment_fee_percent = max(0.0, self._number("payment_fee_percent", 0.0))
        payment_fee_fixed = max(0.0, self._number("payment_fee_fixed_cents", 0.0)) / 100.0

        material_grams = round(grams * (1.0 + waste_percent / 100.0), 2)
        material_cost = material_grams * material_cost_per_g
        machine_cost = (minutes / 60.0) * machine_hourly
        setup_cost = (max(0.0, float(setup_minutes or 0)) / 60.0) * setup_rate
        post_cost = (max(0.0, float(post_process_minutes or 0)) / 60.0) * post_rate
        qc_cost = (max(0.0, float(qc_minutes or 0)) / 60.0) * qc_rate
        packaging_cost = packaging

        direct_cost = material_cost + machine_cost + setup_cost + post_cost + qc_cost + packaging_cost
        overhead_cost = direct_cost * overhead / 100.0
        unit_cost = direct_cost + overhead_cost
        margin_divisor = max(0.0001, 1.0 - margin / 100.0)
        pre_fee_price = unit_cost / margin_divisor
        payment_fee = pre_fee_price * payment_fee_percent / 100.0 + payment_fee_fixed
        unit_price = (pre_fee_price + payment_fee) * rush_multiplier

        if self._enabled("quantity_discount_enabled") and qty >= 10:
            discount = max(0.0, min(50.0, self._number("quantity_discount_percent", 0.0)))
            unit_price *= 1.0 - discount / 100.0

        return {
            "quantity": qty,
            "material_grams": material_grams,
            "material_cost": round(material_cost, 2),
            "machine_cost": round(machine_cost, 2),
            "setup_cost": round(setup_cost, 2),
            "post_process_cost": round(post_cost, 2),
            "qc_cost": round(qc_cost, 2),
            "packaging_cost": round(packaging_cost, 2),
            "overhead_cost": round(overhead_cost, 2),
            "unit_cost": round(unit_cost, 2),
            "target_margin_percent": margin,
            "payment_fee": round(payment_fee, 2),
            "rush_multiplier": rush_multiplier,
            "unit_price": round(unit_price, 2),
            "total_price": round(unit_price * qty, 2),
        }
