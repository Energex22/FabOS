"""Provider-independent FabOS API boundary."""
from urllib.parse import urlsplit

from fabos_api.app import FabOSAPI, _mapping, create_wsgi_app
from fabos_core.services.checkout import CheckoutService
from fabos_core.services.commerce_pricing import CommercePricingService
from fabos_core.services.customer_accounts import CustomerAccountService

_original_request = FabOSAPI.request


def _api_request(self, method, path, body=None, headers=None):
    parsed_url = urlsplit(path or "/")
    parsed = [part for part in parsed_url.path.strip("/").split("/") if part]
    method = (method or "GET").upper()

    if parsed == ["api", self.VERSION, "auth", "register"] and method == "POST":
        try:
            service = CustomerAccountService(
                self.core.database, self.core.accounts, self.core.auth, getattr(self.core, "shop_settings", None)
            )
            result = service.register(body.get("name"), body.get("email"), body.get("password"), body.get("phone", ""))
            return self._response(201, result)
        except Exception as exc:
            return self._error(exc)

    if parsed == ["api", self.VERSION, "customer", "me"] and method == "GET":
        try:
            context = self._context(headers)
            if context.get("account_type") != "customer":
                raise PermissionError("Customer account required")
            summary = _mapping(self.core.accounts.account_summary(context["id"])) or {}
            return self._response(200, self._customer_safe_profile(summary))
        except Exception as exc:
            return self._error(exc)

    if parsed == ["api", self.VERSION, "checkout", "estimate"] and method == "POST":
        try:
            context = self._context(headers)
            if context.get("account_type") != "customer":
                raise PermissionError("Customer account required")
            service = CommercePricingService(self.core.products, self.core.shop_settings)
            return self._response(200, service.estimate(body.get("items"), body.get("shipping_mode"), body.get("shipping_weight_g", 0)))
        except Exception as exc:
            return self._error(exc)

    if parsed == ["api", self.VERSION, "checkout", "order"] and method == "POST":
        try:
            context = self._context(headers)
            if context.get("account_type") != "customer":
                raise PermissionError("Customer account required")
            service = CheckoutService(self.core.database, self.core.accounts, self.core.products, self.core.shop_settings)
            result = service.create_order(context["id"], body.get("items"), body.get("shipping_address"), body.get("notes", ""), body.get("shipping_mode"))
            return self._response(201, {"order": result})
        except Exception as exc:
            return self._error(exc)

    return _original_request(self, method, path, body, headers)


FabOSAPI.request = _api_request

__all__ = ["FabOSAPI", "create_wsgi_app"]
