"""Provider-independent FabOS API boundary.

This package exposes the existing FabOS business services without creating a
second business-logic layer. It is intentionally dependency-free so the core
remains compatible with the project's Python 3.8 baseline.
"""
from fabos_api.app import FabOSAPI, create_wsgi_app

# The security boundary returns a structured {user, session} context. The API
# transport historically consumed the actor fields at the top level. Keep the
# adapter compatible with both shapes while the transport is expanded.
_original_context = FabOSAPI._context


def _api_context(self, headers, permission=None):
    context = _original_context(self, headers, permission)
    if "id" not in context and isinstance(context.get("user"), dict):
        context = dict(context)
        context["id"] = context["user"].get("id")
        context["account_type"] = context["user"].get("account_type")
    return context


FabOSAPI._context = _api_context

__all__ = ["FabOSAPI", "create_wsgi_app"]
