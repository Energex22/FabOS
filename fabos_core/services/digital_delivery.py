"""Digital product delivery for the FABVEX shop.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path


import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path


class DigitalDeliveryService:
    PRODUCT_TYPES = ("physical", "digital")
    DESIGN_TYPES = {
        "3d_print": "3D print",
        "cnc": "CNC",
        "laser": "Laser",
    }
    # Fallbacks when the shop_settings keys are missing (e.g. a database
    # that predates migration 61 and hasn't run it yet). The settings keys
    # are authoritative; these only keep old databases working.
    DEFAULT_EXTENSIONS = {
        "3d_print": ("stl", "3mf", "step", "zip"),
        "cnc": ("dxf", "svg", "nc", "gcode", "tap", "crv"),
        "laser": ("svg", "lbrn", "lbrn2", "dxf", "pdf"),
    }
    EXTENSION_SETTING_KEYS = {
        "3d_print": "digital_extensions_3d_print",
        "cnc": "digital_extensions_cnc",
        "laser": "digital_extensions_laser",
    }
    TOKEN_BYTES = 32

    def __init__(self, database, data_dir=None, shop_settings=None):
        self.database = database
        self.data_dir = Path(data_dir) if data_dir else None
        self.shop_settings = shop_settings
        self._root = None
        if self.data_dir:
            self._root = self.data_dir / "digital_downloads"
            self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # settings helpers
    # ------------------------------------------------------------------
    def _setting(self, key, default=""):
        getter = getattr(self.shop_settings, "get", None)
        if callable(getter):
            try:
                value = getter(key, default)
                return default if value in (None, "") else value
            except Exception:
                return default
        try:
            with self.database.connect() as conn:
                row = conn.execute("SELECT value FROM shop_settings WHERE key=?", (key,)).fetchone()
                return row["value"] if row and row["value"] not in (None, "") else default
        except Exception:
            return default

    def _int_setting(self, key, default):
        try:
            return int(float(self._setting(key, default)))
        except (TypeError, ValueError):
            return default

    def allowed_extensions(self, design_type):
        """Configured allowed extensions for a design type (lowercase, no dots)."""
        design_type = str(design_type or "3d_print").lower()
        setting_key = self.EXTENSION_SETTING_KEYS.get(design_type)
        raw = self._setting(setting_key, "") if setting_key else ""
        extensions = [part.strip().lower().lstrip(".") for part in str(raw).split(",") if part.strip()]
        extensions = [ext for ext in extensions if ext]
        if extensions:
            return list(dict.fromkeys(extensions))
        return list(self.DEFAULT_EXTENSIONS.get(design_type, self.DEFAULT_EXTENSIONS["3d_print"]))

    def download_validity_days(self):
        return max(1, self._int_setting("digital_download_days", 7))

    def download_limit(self):
        """Max downloads per token; 0/negative means unlimited."""
        return max(0, self._int_setting("digital_download_max", 10))

    def max_upload_bytes(self):
        mb = self._int_setting("digital_upload_max_mb", 500)
        return max(1, mb) * 1024 * 1024

    # ------------------------------------------------------------------
    # product type / design type / licenses
    # ------------------------------------------------------------------
    def _columns(self, conn, table):
        try:
            return {str(row[1]) for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        except Exception:
            return set()

    def product_type_of(self, product_id):
        with self.database.connect() as conn:
            if "product_type" not in self._columns(conn, "products"):
                return "physical"
            row = conn.execute("SELECT product_type FROM products WHERE id=?", (product_id,)).fetchone()
        return str(row["product_type"] or "physical").lower() if row else "physical"

    def design_type_of(self, product_id):
        with self.database.connect() as conn:
            if "design_type" not in self._columns(conn, "products"):
                return "3d_print"
            row = conn.execute("SELECT design_type FROM products WHERE id=?", (product_id,)).fetchone()
        design = str(row["design_type"] or "3d_print").lower() if row else "3d_print"
        return design if design in self.DESIGN_TYPES else "3d_print"

    def is_digital_product(self, product_id):
        return self.product_type_of(product_id) == "digital"

    def configure_product(self, product_id, product_type="digital", design_type="3d_print", licenses=None):
        """Admin: set a product's type/design type and its license options."""
        product_type = str(product_type or "physical").lower()
        if product_type not in self.PRODUCT_TYPES:
            raise ValueError("product_type must be 'physical' or 'digital'")
        design_type = str(design_type or "3d_print").lower()
        if design_type not in self.DESIGN_TYPES:
            raise ValueError("design_type must be one of: %s" % ", ".join(sorted(self.DESIGN_TYPES)))
        with self.database.connect() as conn:
            product = conn.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
            if not product:
                raise KeyError("Product not found.")
            cols = self._columns(conn, "products")
            if "product_type" in cols:
                conn.execute("UPDATE products SET product_type=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (product_type, product_id))
            if "design_type" in cols:
                conn.execute("UPDATE products SET design_type=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (design_type, product_id))
            conn.commit()
        if licenses is not None:
            self.set_license_options(product_id, licenses)
        return self.get_config(product_id)

    def set_license_options(self, product_id, options):
        """Replace a product's license options. Each option: license_key,
        label, price_cents, active (default True), sort_order."""
        cleaned = []
        seen = set()
        for index, option in enumerate(options or []):
            if not isinstance(option, dict):
                raise ValueError("License options must be objects")
            key = str(option.get("license_key") or "").strip().lower()
            if not key or not key.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Each license option needs a slug-like license_key")
            if key in seen:
                raise ValueError("Duplicate license_key: %s" % key)
            seen.add(key)
            label = str(option.get("label") or key.replace("_", " ").title()).strip()
            try:
                price_cents = int(round(float(option.get("price_cents", option.get("price", 0)) or 0)))
            except (TypeError, ValueError):
                raise ValueError("License price for %s must be numeric" % key)
            if price_cents < 0:
                raise ValueError("License price for %s cannot be negative" % key)
            cleaned.append({
                "license_key": key,
                "label": label,
                "price_cents": price_cents,
                "active": 1 if option.get("active", True) else 0,
                "sort_order": int(option.get("sort_order", index) or 0),
            })
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
                raise KeyError("Product not found.")
            conn.execute("DELETE FROM product_digital_licenses WHERE product_id=?", (product_id,))
            for option in cleaned:
                conn.execute(
                    """INSERT INTO product_digital_licenses
                       (id,product_id,license_key,label,price_cents,sort_order,active)
                       VALUES(?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), product_id, option["license_key"], option["label"],
                     option["price_cents"], option["sort_order"], option["active"]),
                )
            # Keep the product's base price in sync with the cheapest active
            # license so the existing storefront price display and the
            # "has_price" readiness check keep working unchanged.
            active_prices = [option["price_cents"] for option in cleaned if option["active"] and option["price_cents"] > 0]
            if active_prices and "price_cents" in self._columns(conn, "products"):
                conn.execute("UPDATE products SET price_cents=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (min(active_prices), product_id))
            conn.commit()
        return self.license_options(product_id, active_only=False)

    def license_options(self, product_id, active_only=True):
        with self.database.connect() as conn:
            if not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='product_digital_licenses'"
            ).fetchone():
                return []
            sql = "SELECT * FROM product_digital_licenses WHERE product_id=?"
            if active_only:
                sql += " AND active=1"
            sql += " ORDER BY sort_order, label"
            return [dict(row) for row in conn.execute(sql, (product_id,)).fetchall()]

    def get_license(self, product_id, license_key):
        for option in self.license_options(product_id, active_only=True):
            if str(option["license_key"]) == str(license_key or "").strip().lower():
                return option
        return None

    def get_config(self, product_id):
        return {
            "product_id": product_id,
            "product_type": self.product_type_of(product_id),
            "design_type": self.design_type_of(product_id),
            "design_type_label": self.DESIGN_TYPES.get(self.design_type_of(product_id), "3D print"),
            "allowed_extensions": self.allowed_extensions(self.design_type_of(product_id)),
            "licenses": self.license_options(product_id, active_only=False),
            "files": self.list_files(product_id),
        }

    # ------------------------------------------------------------------
    # digital file attachments
    # ------------------------------------------------------------------
    def _resolve_stored_path(self, stored_path):
        if not self._root:
            return None
        candidate = (self._root / str(stored_path or "")).resolve()
        try:
            candidate.relative_to(self._root.resolve())
        except ValueError:
            return None
        return candidate

    def list_files(self, product_id):
        with self.database.connect() as conn:
            if not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='digital_product_files'"
            ).fetchone():
                return []
            return [dict(row) for row in conn.execute(
                "SELECT * FROM digital_product_files WHERE product_id=? ORDER BY sort_order, created_at",
                (product_id,)).fetchall()]

    def digital_file_count(self, product_id):
        with self.database.connect() as conn:
            if not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='digital_product_files'"
            ).fetchone():
                return 0
            return int(conn.execute(
                "SELECT COUNT(*) FROM digital_product_files WHERE product_id=?", (product_id,)).fetchone()[0])

    def add_file(self, product_id, filename, file_bytes):
        """Validate and store one digital file for a product."""
        if not self.is_digital_product(product_id):
            raise ValueError("Digital files can only be attached to digital products")
        original = Path(str(filename or "")).name.strip()
        if not original:
            raise ValueError("A file name is required")
        extension = Path(original).suffix.lower().lstrip(".")
        design_type = self.design_type_of(product_id)
        allowed = self.allowed_extensions(design_type)
        if not extension or extension not in allowed:
            raise ValueError(
                "File type .%s is not allowed for %s products (allowed: %s)"
                % (extension or "?", self.DESIGN_TYPES.get(design_type, design_type), ", ".join("." + ext for ext in allowed))
            )
        data = bytes(file_bytes or b"")
        if not data:
            raise ValueError("The uploaded file is empty")
        if len(data) > self.max_upload_bytes():
            raise ValueError("File exceeds the %d MB upload limit" % (self.max_upload_bytes() // (1024 * 1024)))
        if self._root is None:
            raise RuntimeError("Digital download storage is not configured")
        file_id = str(uuid.uuid4())
        stored_name = "%s.%s" % (file_id, extension)
        stored_relative = "%s/%s" % (product_id, stored_name)
        target = self._resolve_stored_path(stored_relative)
        if target is None:
            raise RuntimeError("Invalid storage path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        with self.database.connect() as conn:
            sort_order = int(conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM digital_product_files WHERE product_id=?",
                (product_id,)).fetchone()[0])
            conn.execute(
                """INSERT INTO digital_product_files
                   (id,product_id,original_name,stored_path,size_bytes,sha256,sort_order)
                   VALUES(?,?,?,?,?,?,?)""",
                (file_id, product_id, original, stored_relative, len(data), digest, sort_order),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM digital_product_files WHERE id=?", (file_id,)).fetchone()
        return dict(row)

    def delete_file(self, product_id, file_id):
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM digital_product_files WHERE id=? AND product_id=?", (file_id, product_id)).fetchone()
            if not row:
                raise KeyError("Digital file not found.")
            conn.execute("DELETE FROM digital_product_files WHERE id=?", (file_id,))
            conn.commit()
            stored_path = row["stored_path"]
        target = self._resolve_stored_path(stored_path)
        if target and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
        return True

    # ------------------------------------------------------------------
    # order helpers
    # ------------------------------------------------------------------
    def _order_item_rows(self, conn, order_id):
        cols = self._columns(conn, "order_items")
        select_license = ", oi.license_key" if "license_key" in cols else ", NULL AS license_key"
        has_type = "product_type" in self._columns(conn, "products")
        type_select = ", p.product_type" if has_type else ", 'physical' AS product_type"
        return conn.execute(
            """SELECT oi.* %s, o.customer_id %s
               FROM order_items oi
               JOIN orders o ON o.id = oi.order_id
               LEFT JOIN products p ON p.id = oi.product_id
               WHERE oi.order_id=? ORDER BY oi.rowid"""
            % (select_license, type_select),
            (order_id,)).fetchall()

    def is_digital_only_order(self, order_id):
        with self.database.connect() as conn:
            rows = self._order_item_rows(conn, order_id)
        if not rows:
            return False
        return all(str(row["product_type"] or "physical").lower() == "digital" for row in rows)

    def order_has_digital_items(self, order_id):
        with self.database.connect() as conn:
            rows = self._order_item_rows(conn, order_id)
        return any(str(row["product_type"] or "physical").lower() == "digital" for row in rows)

    # ------------------------------------------------------------------
    # token grants (called when the order's invoice is paid)
    # ------------------------------------------------------------------
    def _mint_token(self):
        return secrets.token_urlsafe(self.TOKEN_BYTES)

    def grant_for_order(self, order_id):
        """Grant download tokens for every digital line item on an order.

        Idempotent: already-granted (order_item, file) pairs are skipped, so
        repeat payment notifications never mint duplicate tokens.
        Returns the list of tokens granted by this call.
        """
        granted = []
        with self.database.connect() as conn:
            rows = self._order_item_rows(conn, order_id)
            digital_items = [row for row in rows
                             if str(row["product_type"] or "physical").lower() == "digital"]
            if not digital_items:
                return []
            days = self.download_validity_days()
            limit = self.download_limit()
            expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
            for item in digital_items:
                files = [dict(r) for r in conn.execute(
                    "SELECT * FROM digital_product_files WHERE product_id=? ORDER BY sort_order, created_at",
                    (item["product_id"],)).fetchall()] if item["product_id"] else []
                for digital_file in files:
                    existing = conn.execute(
                        """SELECT id FROM digital_download_tokens
                           WHERE order_item_id=? AND file_id=? AND revoked=0 LIMIT 1""",
                        (item["id"], digital_file["id"])).fetchone()
                    if existing:
                        continue
                    token_id = str(uuid.uuid4())
                    token = self._mint_token()
                    label = str(item["license_key"] or "").strip()
                    conn.execute(
                        """INSERT INTO digital_download_tokens
                           (id,order_item_id,customer_id,product_id,file_id,token,label,expires_at,max_downloads)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (token_id, item["id"], item["customer_id"], item["product_id"],
                         digital_file["id"], token, label, expires_at, limit if limit > 0 else None),
                    )
                    granted.append({
                        "id": token_id, "token": token,
                        "order_item_id": item["id"], "file_id": digital_file["id"],
                        "original_name": digital_file["original_name"],
                    })
            conn.commit()
        return granted

    # ------------------------------------------------------------------
    # customer-facing reads
    # ------------------------------------------------------------------
    def _token_payload(self, row):
        data = dict(row)
        remaining = None
        if data.get("max_downloads") is not None:
            remaining = max(0, int(data["max_downloads"]) - int(data["download_count"] or 0))
        data["downloads_remaining"] = remaining
        data["is_expired"] = bool(data.get("expires_at") and str(data["expires_at"]) < datetime.utcnow().isoformat(timespec="seconds"))
        data["is_revoked"] = bool(data.get("revoked"))
        data["is_active"] = not data["is_revoked"] and not data["is_expired"] and (remaining is None or remaining > 0)
        data["design_type"] = data.get("design_type") or "3d_print"
        data["design_type_label"] = self.DESIGN_TYPES.get(data["design_type"], "3D print")
        return data

    def tokens_for_customer(self, customer_id, include_inactive=False):
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT t.*, p.name AS product_name, p.design_type,
                          f.original_name AS file_name, f.size_bytes,
                          o.order_number, oi.license_key, oi.description AS item_description
                   FROM digital_download_tokens t
                   LEFT JOIN products p ON p.id = t.product_id
                   LEFT JOIN digital_product_files f ON f.id = t.file_id
                   LEFT JOIN orders o ON o.id = (SELECT order_id FROM order_items WHERE id = t.order_item_id)
                   LEFT JOIN order_items oi ON oi.id = t.order_item_id
                   WHERE t.customer_id=?
                   ORDER BY t.created_at DESC""",
                (customer_id,)).fetchall()
        payloads = [self._token_payload(row) for row in rows]
        if not include_inactive:
            payloads = [payload for payload in payloads if payload["is_active"]]
        return payloads

    def tokens_for_order(self, order_id):
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT t.*, p.name AS product_name, f.original_name AS file_name, oi.license_key
                   FROM digital_download_tokens t
                   LEFT JOIN products p ON p.id = t.product_id
                   LEFT JOIN digital_product_files f ON f.id = t.file_id
                   LEFT JOIN order_items oi ON oi.id = t.order_item_id
                   WHERE t.order_item_id IN (SELECT id FROM order_items WHERE order_id=?)
                   ORDER BY t.created_at""",
                (order_id,)).fetchall()
        return [self._token_payload(row) for row in rows]

    # ------------------------------------------------------------------
    # redemption / revocation
    # ------------------------------------------------------------------
    def redeem(self, token):
        """Validate a bearer token and consume one download.

        Returns (token_row, file_row, absolute_path). Raises KeyError when
        the token is unknown, PermissionError when it is revoked/expired/
        exhausted, and FileNotFoundError when the stored file is gone.
        """
        token = str(token or "").strip()
        if not token:
            raise KeyError("Download link not found.")
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM digital_download_tokens WHERE token=?", (token,)).fetchone()
            if not row:
                raise KeyError("Download link not found.")
            payload = self._token_payload(row)
            if payload["is_revoked"]:
                raise PermissionError("This download link has been revoked.")
            if payload["is_expired"]:
                raise PermissionError("This download link has expired.")
            if payload["downloads_remaining"] is not None and payload["downloads_remaining"] <= 0:
                raise PermissionError("This download link has reached its download limit.")
            file_row = conn.execute(
                "SELECT * FROM digital_product_files WHERE id=?", (row["file_id"],)).fetchone()
            if not file_row:
                raise FileNotFoundError("The purchased file is no longer available.")
            conn.execute(
                """UPDATE digital_download_tokens
                   SET download_count = download_count + 1, last_downloaded_at = CURRENT_TIMESTAMP
                   WHERE id=?""",
                (row["id"],))
            conn.commit()
        target = self._resolve_stored_path(file_row["stored_path"])
        if target is None or not target.is_file():
            raise FileNotFoundError("The purchased file is no longer available.")
        return payload, dict(file_row), target

    def revoke(self, token_id):
        with self.database.connect() as conn:
            row = conn.execute("SELECT id FROM digital_download_tokens WHERE id=?", (token_id,)).fetchone()
            if not row:
                raise KeyError("Download token not found.")
            conn.execute("UPDATE digital_download_tokens SET revoked=1 WHERE id=?", (token_id,))
            conn.commit()
        return True

    def regenerate(self, token_id):
        """Mint a fresh token for the same purchase, revoking the old one."""
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM digital_download_tokens WHERE id=?", (token_id,)).fetchone()
            if not row:
                raise KeyError("Download token not found.")
            new_id = str(uuid.uuid4())
            new_token = self._mint_token()
            days = self.download_validity_days()
            limit = self.download_limit()
            expires_at = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
            conn.execute("UPDATE digital_download_tokens SET revoked=1 WHERE id=?", (token_id,))
            conn.execute(
                """INSERT INTO digital_download_tokens
                   (id,order_item_id,customer_id,product_id,file_id,token,label,expires_at,max_downloads)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (new_id, row["order_item_id"], row["customer_id"], row["product_id"], row["file_id"],
                 new_token, row["label"], expires_at, limit if limit > 0 else None),
            )
            conn.commit()
            created = conn.execute("SELECT * FROM digital_download_tokens WHERE id=?", (new_id,)).fetchone()
        return self._token_payload(created)
