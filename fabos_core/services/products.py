import csv
import uuid
import os
from pathlib import Path
from typing import Dict, List, Optional


class ProductService:
    def __init__(self, database):
        self.database = database
        self._ensure_storefront_schema()

    def _ensure_storefront_schema(self):
        with self.database.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS product_storefront(
                    id TEXT PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
                    visibility TEXT NOT NULL DEFAULT 'draft',
                    origin_type TEXT NOT NULL DEFAULT 'catalog_import',
                    source_customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    customer_title TEXT,
                    customer_description TEXT,
                    published_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_product_storefront_visibility ON product_storefront(visibility,sort_order);
                CREATE INDEX IF NOT EXISTS idx_product_storefront_origin ON product_storefront(origin_type,source_customer_id);
            """)
            conn.commit()

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

    def _table_columns(self, conn, table):
        try:
            return {str(row[1]) for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        except Exception:
            return set()

    def _model_file_count(self, conn, product_id):
        model_exts = ("%.stl", "%.3mf", "%.obj", "%.step", "%.stp")
        count = 0
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product_files'").fetchone():
            cols = self._table_columns(conn, "product_files")
            usable = [c for c in ("path", "file_path", "filename", "original_name", "name", "file_type", "mime_type", "kind") if c in cols]
            if usable:
                clauses = []
                for col in usable:
                    clauses.extend(["LOWER(CAST(%s AS TEXT)) LIKE ?" % col for _ in model_exts])
                args = [product_id]
                for _ in usable:
                    args.extend(model_exts)
                count += conn.execute("SELECT COUNT(*) FROM product_files WHERE product_id=? AND (" + " OR ".join(clauses) + ")", args).fetchone()[0]
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='designs'").fetchone():
            asset_cols = self._table_columns(conn, "design_assets")
            if asset_cols and "design_id" in asset_cols:
                path_col = "stored_path" if "stored_path" in asset_cols else ("original_name" if "original_name" in asset_cols else None)
                if path_col:
                    clauses = ["LOWER(CAST(a.%s AS TEXT)) LIKE ?" % path_col for _ in model_exts]
                    args = [product_id] + list(model_exts)
                    count += conn.execute(
                        "SELECT COUNT(*) FROM design_assets a JOIN designs d ON d.id=a.design_id WHERE d.product_id=? AND (" + " OR ".join(clauses) + ")",
                        args,
                    ).fetchone()[0]
        return int(count)

    def storefront_state(self, product_id):
        self._ensure_storefront_schema()
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM product_storefront WHERE id=?", (product_id,)).fetchone()
            model_count = self._model_file_count(conn, product_id)
            product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            return None
        return {
            "visibility": str(row["visibility"] if row else "draft"),
            "origin_type": str(row["origin_type"] if row else "catalog_import"),
            "customer_title": row["customer_title"] if row else None,
            "customer_description": row["customer_description"] if row else None,
            "model_file_count": model_count,
            "has_model": model_count > 0,
            "has_price": int(product["price_cents"] or 0) > 0,
            "license_status": str(product["license_status"] or "").lower(),
            "has_real_image": self.has_real_image(product_id),
        }

    def storefront_publication_readiness(self, product_id):
        state = self.storefront_state(product_id)
        if not state:
            return {"ready": False, "reasons": ["Product does not exist."], "state": None}
        reasons = []
        if not state["has_model"]:
            reasons.append("A usable STL, 3MF, OBJ, STEP, or STP model is required.")
        if not state["has_price"]:
            reasons.append("A positive customer price is required.")
        if state["license_status"] in {"blocked", "prohibited", "commercially_prohibited", "review_required"}:
            reasons.append("The current license status does not permit public storefront publication.")
        return {"ready": not reasons, "reasons": reasons, "state": state}

    def is_customer_eligible(self, product_id):
        state = self.storefront_state(product_id)
        if not state:
            return False
        if state["visibility"] != "published":
            return False
        return self.storefront_publication_readiness(product_id)["ready"]

    def customer_catalog(self, query="", category="All", order_by="name", descending=False):
        rows = self.list(query=query, category=category, order_by=order_by, descending=descending)
        if not rows:
            return []
        readiness = self._readiness_map([row["id"] for row in rows])
        return [(row, readiness[row["id"]]) for row in rows if readiness.get(row["id"], {}).get("ready")]

    def _readiness_map(self, product_ids):
        ids = list(product_ids or [])
        if not ids:
            return {}
        try:
            from fabos_core.services.design_vault import DesignVaultService
            return DesignVaultService(self.database, self.database.path.parent).product_print_status_map(ids)
        except Exception:
            return {}

    def save_storefront(self, product_id, values):
        self._ensure_storefront_schema()
        allowed_visibility = {"draft", "review", "published", "retired"}
        visibility = str(values.get("visibility") or "draft").lower()
        if visibility not in allowed_visibility:
            raise ValueError("Invalid storefront visibility")
        if visibility == "published":
            readiness = self.storefront_publication_readiness(product_id)
            if not readiness["ready"]:
                raise ValueError("Product is not ready for storefront publication: " + " ".join(readiness["reasons"]))
        origin = str(values.get("origin_type") or "catalog_import")
        source_customer_id = values.get("source_customer_id")
        title = values.get("customer_title")
        description = values.get("customer_description")
        with self.database.connect() as conn:
            existing = conn.execute("SELECT id FROM product_storefront WHERE id=?", (product_id,)).fetchone()
            published_at = "CURRENT_TIMESTAMP" if visibility == "published" else "NULL"
            if existing:
                conn.execute(
                    "UPDATE product_storefront SET visibility=?,origin_type=?,source_customer_id=?,customer_title=?,customer_description=?,published_at=" + published_at + ",updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (visibility, origin, source_customer_id, title, description, product_id),
                )
            else:
                conn.execute(
                    "INSERT INTO product_storefront(id,visibility,origin_type,source_customer_id,customer_title,customer_description,published_at) VALUES(?,?,?,?,?,?," + published_at + ")",
                    (product_id, visibility, origin, source_customer_id, title, description),
                )
            conn.commit()
        return self.storefront_state(product_id)

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
        self._ensure_storefront_schema()
        return product_id

    def delete(self, product_id):
        with self.database.connect() as conn:
            conn.execute("DELETE FROM products WHERE id=?", (product_id,)); conn.commit()
