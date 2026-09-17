from fabos_core.db.database import Database
from fabos_core.services.price_history import PriceHistoryService


def make_db(tmp_path):
    db = Database(tmp_path / "fabos.db")
    db.initialize()
    return db


def test_product_price_changes_are_recorded(tmp_path):
    db = make_db(tmp_path)
    history = PriceHistoryService(db)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO products(id,name,price_cents) VALUES(?,?,?)",
            ("p1", "Widget", 2000),
        )
        conn.execute("UPDATE products SET price_cents=? WHERE id=?", (2400, "p1"))
        conn.commit()

    rows = history.product("p1")
    assert len(rows) == 1
    assert rows[0]["old_price_cents"] == 2000
    assert rows[0]["new_price_cents"] == 2400


def test_order_captures_purchase_price_snapshot(tmp_path):
    db = make_db(tmp_path)
    history = PriceHistoryService(db)
    with db.connect() as conn:
        conn.execute("INSERT INTO customers(id,name) VALUES(?,?)", ("c1", "Customer"))
        conn.execute(
            "INSERT INTO products(id,name,price_cents) VALUES(?,?,?)",
            ("p1", "Widget", 2000),
        )
        conn.execute(
            "INSERT INTO quotes(id,quote_number,customer_id,total_cents) VALUES(?,?,?,?)",
            ("q1", "Q-TEST-0001", "c1", 4000),
        )
        conn.execute(
            "INSERT INTO quote_items(id,quote_id,product_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("qi1", "q1", "p1", "Widget", 2, 2000, "PETG", "Black", 60, 40.0),
        )
        conn.execute(
            "INSERT INTO orders(id,order_number,customer_id,quote_id,total_cents) VALUES(?,?,?,?,?)",
            ("o1", "O-TEST-0001", "c1", "q1", 4000),
        )
        conn.execute("UPDATE products SET price_cents=? WHERE id=?", (2600, "p1"))
        conn.execute("UPDATE quote_items SET unit_price_cents=? WHERE id=?", (2600, "qi1"))
        conn.commit()

    rows = history.order_items("o1")
    assert len(rows) == 1
    assert rows[0]["unit_price_cents"] == 2000
    assert rows[0]["quantity"] == 2
    assert rows[0]["product_id"] == "p1"


def test_variant_price_changes_are_recorded(tmp_path):
    db = make_db(tmp_path)
    history = PriceHistoryService(db)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO products(id,name,price_cents) VALUES(?,?,?)",
            ("p1", "Widget", 2000),
        )
        conn.execute(
            "INSERT INTO product_variants(id,product_id,name,price_cents) VALUES(?,?,?,?)",
            ("v1", "p1", "PETG Black", 2200),
        )
        conn.execute("UPDATE product_variants SET price_cents=? WHERE id=?", (2500, "v1"))
        conn.commit()

    rows = history.variant("v1")
    assert len(rows) == 1
    assert rows[0]["old_price_cents"] == 2200
    assert rows[0]["new_price_cents"] == 2500
