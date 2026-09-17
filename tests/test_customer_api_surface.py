from pathlib import Path

from fabos_core.api import _customer_payload, _order_item_payload, _order_payload, _payment_payload, _public_product, _quote_item_payload, _quote_payload


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


def test_customer_payload_is_allowlisted():
    value = _customer_payload({"id": "cust-1", "name": "Alex", "email": "a@example.com", "phone": "555", "notes": "internal", "account_type": "customer"})
    assert value == {"name": "Alex", "email": "a@example.com", "phone": "555"}


def test_quote_payload_excludes_internal_fields():
    value = _quote_payload({"id": "q1", "quote_number": "Q-1", "status": "draft", "customer_id": "cust-1", "internal_cost_cents": 1234, "notes": "note"})
    assert value == {"id": "q1", "quote_number": "Q-1", "status": "draft", "notes": "note"}


def test_quote_item_payload_excludes_product_and_internal_ids():
    value = _quote_item_payload({"id": "qi1", "product_id": "p1", "description": "Custom", "quantity": 2, "unit_price_cents": 500, "material": "PLA", "color": "Black", "internal_cost_cents": 200})
    assert value == {"id": "qi1", "description": "Custom", "quantity": 2, "unit_price_cents": 500, "material": "PLA", "color": "Black"}


def test_order_payload_excludes_internal_and_payment_fields():
    value = _order_payload({"id": "o1", "order_number": "O-1", "status": "confirmed", "created_at": "2026-09-17", "customer_id": "cust-1", "payment_transaction_id": "pay-1", "invoice_id": "inv-1", "shipping_address_json": "{}", "total_cents": 1000})
    assert value == {"id": "o1", "order_number": "O-1", "status": "confirmed", "created_at": "2026-09-17", "shipping_address_json": "{}", "total_cents": 1000}


def test_order_item_payload_excludes_product_id():
    value = _order_item_payload({"id": "oi1", "product_id": "p1", "product_name": "Widget", "description": "Widget", "quantity": 1, "unit_price_cents": 900, "material": "PETG", "color": "Black", "gcode_path": "/internal/path"})
    assert value == {"id": "oi1", "product_name": "Widget", "description": "Widget", "quantity": 1, "unit_price_cents": 900, "material": "PETG", "color": "Black"}


def test_payment_payload_exposes_only_customer_checkout_fields():
    value = _payment_payload({"status": "pending", "checkout_url": "https://checkout.example", "provider": "stripe", "provider_payment_id": "pi-secret", "ledger_id": "ledger-1"})
    assert value == {"status": "pending", "checkout_url": "https://checkout.example"}


def test_public_product_does_not_expose_model_paths_or_license_fields():
    class Products:
        def images(self, _product_id):
            return [{"id": "img1", "path": "/catalog/widget.png", "is_primary": 1, "alt_text": "Widget", "filesystem_path": "/srv/data/widget.png"}]

        def variants(self, _product_id):
            return [{"id": "v1", "name": "Standard", "material": "PLA", "color": "Black", "price_cents": 1000, "active": 1, "gcode_path": "/srv/gcode/widget.gcode"}]

    row = {"id": "p1", "sku": "W-1", "name": "Widget", "description": "A widget", "category": "Tools", "subcategory": "Misc", "active": 1, "price_cents": 1000, "license_status": "approved", "model_path": "/srv/models/widget.stl"}
    value = _public_product(row, Products(), {"origin_type": "catalog_import", "model_file_count": 1})
    assert value["name"] == "Widget"
    assert value["price"] == 10.0
    assert "model_path" not in value
    assert "license_status" not in value
    assert "filesystem_path" not in value["images"][0]
    assert "gcode_path" not in value["variants"][0]
