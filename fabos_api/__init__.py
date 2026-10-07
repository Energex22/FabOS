"""Provider-independent FabOS API boundary."""
from urllib.parse import urlsplit

from fabos_api.app import FabOSAPI, _mapping, create_wsgi_app
from fabos_core.services.checkout import CheckoutService
from fabos_core.services.commerce_pricing import CommercePricingService
from fabos_core.services.customer_accounts import CustomerAccountService

_original_request = FabOSAPI.request

# Shipping mode is server-authoritative: the storefront may display estimates,
# but the checkout charge must always come from shop settings. Never trust a
# client-supplied shipping_mode (H1: a customer posting {"shipping_mode":"free"}
# would otherwise zero out shipping on the WSGI checkout path).
_ALLOWED_SHIPPING_MODES = {"calculated", "flat", "free"}


def _server_shipping_mode(core):
    settings = getattr(core, "shop_settings", None)
    raw = settings.get("shipping_mode", "flat") if settings else "flat"
    mode = str(raw or "flat").strip().lower()
    return mode if mode in _ALLOWED_SHIPPING_MODES else "flat"


def _api_request(self, method, path, body=None, headers=None, raw_body=None):
    parsed_url = urlsplit(path or "/")
    parsed = [part for part in parsed_url.path.strip("/").split("/") if part]
    method = (method or "GET").upper()

    if parsed == ["api", self.VERSION, "auth", "register"] and method == "POST":
        try:
            service = CustomerAccountService(
                self.core.database, self.core.accounts, self.core.auth, getattr(self.core, "shop_settings", None)
            )
            result = service.register(body.get("name"), body.get("email"), body.get("password"), body.get("phone", ""))
            # Project the raw auth result into the FastAPI register shape
            # ({"token","expires_at","user":{"name","email"},"customer":{...}});
            # never expose the nested account summary rows.
            return self._response(201, self._project_auth_response(result))
        except ValueError as exc:
            # Includes the racy duplicate-registration IntegrityError, which
            # the service converts to a duplicate-email ValueError.
            if "already exists" in str(exc):
                return self._response(409, {"error": str(exc)})
            return self._error(exc)
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
            # Shipping weight is always recomputed server-side from the
            # catalog items; a client-supplied weight must never influence
            # the estimate (it only ever affected the displayed number, but
            # ignoring it removes the divergence entirely).
            return self._response(200, service.estimate(body.get("items"), _server_shipping_mode(self.core)))
        except Exception as exc:
            return self._error(exc)

    if parsed == ["api", self.VERSION, "checkout", "order"] and method == "POST":
        try:
            context = self._context(headers)
            if context.get("account_type") != "customer":
                raise PermissionError("Customer account required")
            service = CheckoutService(self.core.database, self.core.accounts, self.core.products, self.core.shop_settings)
            result = service.create_order(context["id"], body.get("items"), body.get("shipping_address"), body.get("notes", ""), _server_shipping_mode(self.core))
            return self._response(201, {"order": result})
        except Exception as exc:
            return self._error(exc)

    return _original_request(self, method, path, body, headers, raw_body=raw_body)


FabOSAPI.request = _api_request

__all__ = ["FabOSAPI", "create_wsgi_app"]
