import json

from fabos_core.db.database import Database
from fabos_core.services.price_history import PriceHistoryService
from fabos_core.services.quotes import QuoteService


def make_db(tmp_path):
    db = Database(tmp_path / "fabos.db")
    db.initialize()
    PriceHistoryService(db)
    return db


def test_quote_snapshot_records_calculated_pricing_breakdown(tmp_path):
    db = make_db(tmp_path)
    quotes = QuoteService(db)
    with db.connect() as conn:
        conn.execute("INSERT INTO customers(id,name) VALUES(?,?)", ("c1", "Customer"))
        conn.commit()

    quote_id = quotes.save(
        {"customer_id": "c1", "status": "draft"},
        [{
            "product_id": None,
            "description": "Custom",
            "quantity": 1,
            "unit_price_cents": 1234,
            "pricing_mode": "manual",
        }],
    )
    with db.connect() as conn:
        row = conn.execute(
            "SELECT unit_price_cents,pricing_mode,calculation_json FROM quote_price_snapshots WHERE quote_id=?",
            (quote_id,),
        ).fetchone()
    assert row["unit_price_cents"] == 1234
    assert row["pricing_mode"] == "manual"
    assert row["calculation_json"] is None


def test_order_snapshot_preserves_variant_price_after_quote_changes(tmp_path):
    db = make_db(tmp_path)
    quotes = QuoteService(db)
    with db.connect() as conn:
        conn.execute("INSERT INTO customers(id,name) VALUES(?,?)", ("c1", "Customer"))
        conn.execute("INSERT INTO products(id,name,price_cents) VALUES(?,?,?)", ("p1", "Widget", 2000))
        conn.execute(
            "INSERT INTO product_variants(id,product_id,name,price_cents,material,color,active) VALUES(?,?,?,?,?,?,1)",
            ("v1", "p1", "PETG Black", 2500, "PETG", "Black"),
        )
        conn.commit()

    quote_id = quotes.save(
        {"customer_id": "c1", "status": "approved"},
        [{
            "product_id": "p1",
            "variant_id": "v1",
            "description": "Widget · PETG Black",
            "quantity": 2,
            "unit_price_cents": 2500,
            "material": "PETG",
            "color": "Black",
        }],
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO orders(id,order_number,customer_id,quote_id,total_cents) VALUES(?,?,?,?,?)",
            ("o1", "O-TEST-0002", "c1", quote_id, 5000),
        )
        conn.execute("UPDATE product_variants SET price_cents=? WHERE id=?", (3000, "v1"))
        conn.execute("UPDATE quote_items SET unit_price_cents=? WHERE quote_id=?", (3000, quote_id))
        conn.commit()

    history = PriceHistoryService(db)
    rows = history.order_items("o1")
    assert len(rows) == 1
    assert rows[0]["variant_id"] == "v1"
    assert rows[0]["unit_price_cents"] == 2500
    assert rows[0]["quantity"] == 2

    variant_history = history.variant("v1")
    assert len(variant_history) == 1
    assert variant_history[0]["old_price_cents"] == 2500
    assert variant_history[0]["new_price_cents"] == 3000


def test_quote_update_creates_new_snapshot_without_rewriting_old_snapshot(tmp_path):
    db = make_db(tmp_path)
    quotes = QuoteService(db)
    with db.connect() as conn:
        conn.execute("INSERT INTO customers(id,name) VALUES(?,?)", ("c1", "Customer"))
        conn.commit()

    quote_id = quotes.save(
        {"customer_id": "c1", "status": "draft"},
        [{"description": "Widget", "quantity": 1, "unit_price_cents": 2000}],
    )
    quotes.save(
        {"customer_id": "c1", "status": "sent"},
        [{"description": "Widget", "quantity": 1, "unit_price_cents": 2400}],
        quote_id=quote_id,
    )

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT unit_price_cents FROM quote_price_snapshots WHERE quote_id=? ORDER BY created_at,rowid",
            (quote_id,),
        ).fetchall()
    assert [row["unit_price_cents"] for row in rows] == [2000, 2400]
