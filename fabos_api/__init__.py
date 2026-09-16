"""Provider-independent FabOS API boundary."""
from fabos_api.app import FabOSAPI, create_wsgi_app
from fabos_core.services.customer_accounts import CustomerAccountService

_original_context = FabOSAPI._context
_original_request = FabOSAPI.request


def _api_context(self, headers, permission=None):
    context = _original_context(self, headers, permission)
    if not isinstance(context, dict):
        return context
    normalized = dict(context)
    user = context.get("user")
    if isinstance(user, dict):
        normalized.setdefault("id", user.get("id"))
        normalized.setdefault("account_type", user.get("account_type"))
    if normalized.get("id") and not normalized.get("account_type"):
        try:
            summary = self.core.accounts.account_summary(normalized["id"])
            if isinstance(summary, dict):
                normalized.setdefault("account_type", summary.get("account_type"))
        except Exception:
            pass
    return normalized


def _api_request(self, method, path, body=None, headers=None):
    parsed = path.split("?", 1)[0].strip("/").split("/")
    if parsed == ["api", self.VERSION, "auth", "register"] and (method or "GET").upper() == "POST":
        try:
            service = CustomerAccountService(self.core.database, self.core.accounts, self.core.auth)
            return self._response(201, service.register(body.get("name"), body.get("email"), body.get("password"), body.get("phone", "")))
        except Exception as exc:
            return self._error(exc)
    return _original_request(self, method, path, body, headers)


FabOSAPI._context = _api_context
FabOSAPI.request = _api_request

__all__ = ["FabOSAPI", "create_wsgi_app"]
