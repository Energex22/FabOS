from pathlib import Path


API_SOURCE = Path("fabos_core/api.py").read_text(encoding="utf-8")


def test_customer_api_uses_customer_safe_identity():
    assert 'title="Customer API"' in API_SOURCE
    assert '"service": "customer-api"' in API_SOURCE
    assert 'title="FabOS Customer API"' not in API_SOURCE
    assert '"service": "FabOS Customer API"' not in API_SOURCE


def test_customer_api_docs_are_opt_in():
    assert 'FABOS_API_DOCS' in API_SOURCE
    assert 'docs_url="/docs" if docs_enabled else None' in API_SOURCE
    assert 'redoc_url="/redoc" if docs_enabled else None' in API_SOURCE
    assert 'openapi_url="/openapi.json" if docs_enabled else None' in API_SOURCE
