import os

from fabos_core.api import create_app


def _paths(app):
    return {getattr(route, "path", "") for route in app.routes}


def test_customer_api_hides_framework_docs_by_default(monkeypatch):
    monkeypatch.delenv("FABOS_API_DOCS", raising=False)
    app = create_app(object())

    paths = _paths(app)
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths
    assert app.title == "Customer API"


def test_customer_api_docs_can_be_enabled_for_local_development(monkeypatch):
    monkeypatch.setenv("FABOS_API_DOCS", "1")
    app = create_app(object())

    paths = _paths(app)
    assert "/docs" in paths
    assert "/redoc" in paths
    assert "/openapi.json" in paths
    assert app.title == "Customer API"


def test_health_response_uses_customer_safe_service_name(monkeypatch):
    monkeypatch.delenv("FABOS_API_DOCS", raising=False)
    app = create_app(object())
    health_route = next(route for route in app.routes if getattr(route, "path", "") == "/api/v1/health")

    result = health_route.endpoint()
    assert result == {"status": "ok", "service": "customer-api", "version": "1.2"}
    assert "FabOS" not in str(result)
