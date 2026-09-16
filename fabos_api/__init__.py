"""Provider-independent FabOS API boundary."""
from urllib.parse import urlsplit

from fabos_api.app import FabOSAPI, create_wsgi_app
from fabos_core.services.checkout import CheckoutService
from fabos_core.services.commerce_pricing import CommercePricingService
from fabos_core.services.customer_accounts import CustomerAccountService

_original_context = FabOSAPI._context
_original_request = FabOSAPI.request


def _mapping(value):
    if isinstance(value, dict):
        return value
    try:
        keys = value.keys()
    except AttributeError:
        keys = None
    if keys is not None:
        return {key: value[key] for key in keys}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return None


def _api_context(self, headers, permission=None):
    context = _original_context(self, headers, permission)
    if not isinstance(context, dict):
        return context
    normalized = dict(context)
    user = _mapping(context.get("user"))
    if user:
        normalized.setdefault("id", user.get("id"))
        normalized.setdefault("account_type", user.get("account_type"))
    if normalized.get("id") and not normalized.get("account_type"):
        try:
            summary = _mapping(self.core.accounts.account_summary(normalized["id"])) or {}
            summary_user = _mapping(summary.get("user"))
            if summary_user:
                normalized.setdefault("account_type", summary_user.get("account_type"))
            normalized.setdefault("account_type", summary.get("account_type"))
        except Exception:
            pass
    return normalized


def _api_request(self, method, path, body=None, headers=None):
    parsed_url = urlsplit(path or "/")
    parsed = [part for part in parsed_url.path.strip("/").split("/") if part]
    method = (method or "GET").upper()

    if parsed == ["api", self.VERSION, "auth", "register"] and method == "POST":
        try:
            service = CustomerAccountService(self.core.database, self.core.accounts, self.core.auth)
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
            return self._response(200, {"user": summary.get("user"), "customer": self.core.accounts.customer_for_user(context["id"])})
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
            context = self._context(headers, "order.manage")
            if context.get("account_type") != "customer":
                raise PermissionError("Customer account required")
            service = CheckoutService(self.core.database, self.core.accounts, self.core.products, self.core.shop_settings)
            result = service.create_order(context["id"], body.get("items"), body.get("shipping_address"), body.get("notes", ""), body.get("shipping_mode"))
            return self._response(201, {"order": result})
        except Exception as exc:
            return self._error(exc)

    return _original_request(self, method, path, body, headers)


FabOSAPI._context = _api_context
FabOSAPI.request = _api_request

__all__ = ["FabOSAPI", "create_wsgi_app"]
