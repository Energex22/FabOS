"""Provider-independent FabOS API boundary.

This package exposes the existing FabOS business services without creating a
second business-logic layer. It is intentionally dependency-free so the core
remains compatible with the project's Python 3.8 baseline.
"""
from fabos_api.app import FabOSAPI, create_wsgi_app

__all__ = ["FabOSAPI", "create_wsgi_app"]
