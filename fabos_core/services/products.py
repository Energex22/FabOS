import csv
import uuid
import os
from pathlib import Path
from typing import Dict, List, Optional


class ProductService:
    def __init__(self, database):
        self.database = database

    def import_catalog_if_empty(self, csv_path: Path) -> int:
        with self.database.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count or not Path(csv_path).exists():
            return 0
        imported = 0
        with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                product_id = str(uuid.uuid4())
                verified = row.get("Verification", "").strip().lower().startswith("verified")
                status = "verified" if verified else "review_required"
                low = float(row.get("Price Low") or 0)
                high = float(row.get("Price High") or low)
                price_cents = int(round(((low + high) / 2.0) * 100))
                minutes = int(round(float(row.get("Est. Print Hours") or 0) * 60))
                grams = float(row.get("Est. Filament g") or 0)
                notes = row.get("Legal / Production Notes", "")
                custom = row.get("Customization Ideas", "")
                description = (custom + ("\n\n" + notes if notes else "")).strip()
                with self.database.connect() as conn:
                    conn.execute(
                        """INSERT INTO products
                        (id,sku,name,category,description,designer,source_url,license_name,
                         license_status,price_cents,estimated_minutes,estimated_filament_g)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (product_id, "CAT-%03d" % int(row.get("Rank") or imported + 1),
                         row.get("Product", "Unnamed Product"), row.get("Category", ""),
                         description, row.get("Designer", ""), row.get("Model / Search Link", ""),
                         row.get("License", ""), status, price_cents, minutes, grams),
                    )
                    image = row.get("Image File", "")
                    if image:
                        conn.execute(
                            "INSERT INTO product_images (id,product_id,path,source_url,attribution,is_primary) VALUES (?,?,?,?,?,1)",
                            (str(uuid.uuid4()), product_id, image, row.get("Model / Search Link", ""),
                             "Catalog preview card; replace with your own photo before public listing."),
                        )
                    conn.commit()
                imported += 1
        return imported

    def list(self, query="", category="All", license_status="All", order_by="name", descending=False):
        allowed = {
            "sku": "sku", "name": "name", "category": "category", "designer": "designer",
            "license": "license_name", "status": "license_status", "price": "price_cents",
            "time": "estimated_minutes", "filament": "estimated_filament_g", "updated": "updated_at",
        }
        column = allowed.get(order_by, "name")
        where, args = [], []
        if query:
            where.append("(name LIKE ? OR sku LIKE ? OR category LIKE ? OR designer LIKE ?)")
            needle = "%%%s%%" % query
            args.extend([needle] * 4)
        if category and category != "All":
            where.append("category=?"); args.append(category)
        if license_status and license_status != "All":
            where.append("license_status=?"); args.append(license_status)
        sql = "SELECT * FROM products"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY %s %s, name" % (column, "DESC" if descending else "ASC")
        with self.database.connect() as conn:
            return conn.execute(sql, args).fetchall()

    def categories(self):
        with self.database.connect() as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT category FROM products WHERE category<>'' ORDER BY category")]

    def get(self, product_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    def images(self, product_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC,created_at", (product_id,)).fetchall()


    def has_real_image(self, product_id):
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT path,attribution FROM product_images WHERE product_id=?",
                (product_id,),
            ).fetchall()
        for row in rows:
            raw = str(row["path"] or "").replace("\\", "/")
            attr = str(row["attribution"] or "").lower()
            if not raw.startswith("Catalog_Images/") and "catalog preview card" not in attr:
                return True
        return False

    def remove_placeholder_images(self, product_id, delete_files=True):
        removed = []
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id,path,attribution FROM product_images WHERE product_id=?",
                (product_id,),
            ).fetchall()
            for row in rows:
                raw = str(row["path"] or "").replace("\\", "/")
                attr = str(row["attribution"] or "").lower()
                if raw.startswith("Catalog_Images/") or "catalog preview card" in attr:
                    conn.execute("DELETE FROM product_images WHERE id=?", (row["id"],))
                    removed.append(str(row["path"] or ""))
            conn.commit()
        if delete_files:
            root = Path(__file__).resolve().parents[2]
            for raw in removed:
                candidates = []
                if raw.replace("\\", "/").startswith("Catalog_Images/"):
                    candidates.append(root / "data" / "catalog" / raw)
                path = Path(raw)
                candidates.extend([path, root / raw, root / "data" / raw])
                for candidate in candidates:
                    try:
                        if candidate.exists() and candidate.is_file():
                            candidate.unlink()
                            break
                    except OSError:
                        pass
        return len(removed)

    def add_image(self, product_id, path, source_url="", attribution="", make_primary=True):
        image_id = str(uuid.uuid4())
        with self.database.connect() as conn:
            if make_primary:
                conn.execute("UPDATE product_images SET is_primary=0 WHERE product_id=?", (product_id,))
            conn.execute(
                "INSERT INTO product_images (id,product_id,path,source_url,attribution,is_primary) VALUES (?,?,?,?,?,?)",
                (image_id, product_id, str(path), source_url or "", attribution or "", 1 if make_primary else 0),
            )
            conn.commit()
        return image_id

    def set_primary_image(self, product_id, image_id):
        with self.database.connect() as conn:
            conn.execute("UPDATE product_images SET is_primary=0 WHERE product_id=?", (product_id,))
            conn.execute("UPDATE product_images SET is_primary=1 WHERE id=? AND product_id=?", (image_id, product_id))
            conn.commit()

    def delete_image(self, product_id, image_id):
        with self.database.connect() as conn:
            row = conn.execute("SELECT path,is_primary FROM product_images WHERE id=? AND product_id=?", (image_id, product_id)).fetchone()
            conn.execute("DELETE FROM product_images WHERE id=? AND product_id=?", (image_id, product_id))
            if row and row["is_primary"]:
                next_row = conn.execute("SELECT id FROM product_images WHERE product_id=? ORDER BY created_at DESC LIMIT 1", (product_id,)).fetchone()
                if next_row:
                    conn.execute("UPDATE product_images SET is_primary=1 WHERE id=?", (next_row["id"],))
            conn.commit()

    def files(self, product_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM product_files WHERE product_id=? ORDER BY version DESC,created_at DESC", (product_id,)).fetchall()

    def variants(self, product_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM product_variants WHERE product_id=? ORDER BY name", (product_id,)).fetchall()

    def save(self, values: Dict[str, object], product_id: Optional[str] = None) -> str:
        product_id = product_id or str(uuid.uuid4())
        with self.database.connect() as conn:
            exists = conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone()
            payload = (
                values.get("sku") or None, values.get("name") or "Unnamed Product",
                values.get("category") or "", values.get("description") or "",
                values.get("designer") or "", values.get("source_url") or "",
                values.get("license_name") or "", values.get("license_status") or "review_required",
                int(round(float(values.get("price") or 0) * 100)),
                int(round(float(values.get("hours") or 0) * 60)),
                float(values.get("filament") or 0), product_id,
            )
            if exists:
                conn.execute("""UPDATE products SET sku=?,name=?,category=?,description=?,designer=?,source_url=?,
                    license_name=?,license_status=?,price_cents=?,estimated_minutes=?,estimated_filament_g=?,
                    updated_at=CURRENT_TIMESTAMP WHERE id=?""", payload)
            else:
                conn.execute("""INSERT INTO products
                    (sku,name,category,description,designer,source_url,license_name,license_status,
                     price_cents,estimated_minutes,estimated_filament_g,id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", payload)
            conn.commit()
        return product_id

    def delete(self, product_id):
        with self.database.connect() as conn:
            conn.execute("DELETE FROM products WHERE id=?", (product_id,)); conn.commit()
