from fabos_core.api import _customer_payload, _order_payload, _order_item_payload, _payment_payload, _quote_payload, _quote_item_payload, _user_payload


def test_user_and_customer_payloads_exclude_internal_fields():
    user = _user_payload({"id": "u1", "name": "Jane", "email": "jane@example.com", "account_type": "customer", "password_hash": "secret"})
    customer = _customer_payload({"id": "c1", "name": "Jane", "email": "jane@example.com", "phone": "555", "notes": "internal"})
    assert user == {"name": "Jane", "email": "jane@example.com"}
    assert customer == {"name": "Jane", "email": "jane@example.com", "phone": "555"}


def test_quote_payloads_exclude_internal_identifiers():
    quote = _quote_payload({"id": "q1", "quote_number": "Q-1", "status": "draft", "customer_id": "c1", "internal_note": "secret", "created_at": "now"})
    item = _quote_item_payload({"id": "qi1", "description": "Part", "quantity": 1, "unit_price_cents": 100, "product_id": "p1"})
    assert "customer_id" not in quote
    assert "internal_note" not in quote
    assert quote["quote_number"] == "Q-1"
    assert "product_id" not in item


def test_order_payloads_exclude_internal_identifiers():
    order = _order_payload({"id": "o1", "order_number": "O-1", "status": "pending", "customer_id": "c1", "invoice_id": "inv1", "created_at": "now"})
    item = _order_item_payload({"id": "oi1", "product_name": "Part", "quantity": 1, "unit_price_cents": 100, "product_id": "p1", "quote_id": "q1"})
    assert "customer_id" not in order
    assert "invoice_id" not in order
    assert "product_id" not in item
    assert "quote_id" not in item


def test_payment_payload_exposes_only_customer_checkout_fields():
    payment = _payment_payload({"status": "pending", "checkout_url": "https://pay.example/session", "payment_id": "internal", "provider_payment_id": "secret"})
    assert payment == {"status": "pending", "checkout_url": "https://pay.example/session"}
