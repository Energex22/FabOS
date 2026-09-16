"""Provider-independent FabOS API boundary.

This package exposes the existing FabOS business services without creating a
second business-logic layer. It is intentionally dependency-free so the core
remains compatible with the project's Python 3.8 baseline.
"""
from fabos_api.app import FabOSAPI, create_wsgi_app

# The security boundary returns a structured {user, session} context. The API
# transport historically consumed actor fields at the top level. Keep the
# adapter compatible with both shapes while the transport is expanded.
_original_context = FabOSAPI._context


def _api_context(self, headers, permission=None):
    context = _original_context(self, headers, permission)
    if not isinstance(context, dict):
        return context

    normalized = dict(context)
    user = context.get("user")
    if isinstance(user, dict):
        normalized.setdefault("id", user.get("id"))
        normalized.setdefault("account_type", user.get("account_type"))

    # Older security/test adapters may return only an actor id. Resolve the
    # remaining account fields through the existing account service instead of
    # duplicating identity logic in the API transport.
    if normalized.get("id") and not normalized.get("account_type"):
        try:
            summary = self.core.accounts.account_summary(normalized["id"])
        except Exception:
            summary = None
        if isinstance(summary, dict):
            normalized.setdefault("account_type", summary.get("account_type"))

    return normalized


FabOSAPI._context = _api_context

__all__ = ["FabOSAPI", "create_wsgi_app"]
