"""Internal workflow for turning a customer custom design into a storefront product."""
import uuid
from pathlib import Path


class CustomProductWorkflowService:
    def __init__(self, database, products, design_vault):
        self.database = database
        self.products = products
        self.design_vault = design_vault

    def _model_asset(self, design_id):
        assets = list(self.design_vault.assets(design_id))
        allowed = {".stl", ".3mf", ".obj", ".step", ".stp"}
        for asset in assets:
            if Path(str(asset["original_name"] or "")).suffix.lower() in allowed:
                return asset
        return None

    def promote_quote_design(self, quote_id, values):
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValueError("Product name is required")
        price = float(values.get("price") or 0)
        if price <= 0:
            raise ValueError("Product price must be greater than zero")
        license_status = str(values.get("license_status") or "review_required").strip().lower()
        visibility = str(values.get("visibility") or "draft").strip().lower()
        if visibility not in {"draft", "review", "published", "retired"}:
            raise ValueError("Invalid storefront visibility")

        with self.database.connect() as conn:
            link = conn.execute("""SELECT q.id quote_id,q.customer_id,q.quote_number,qd.design_id,d.product_id
                FROM quote_designs qd JOIN quotes q ON q.id=qd.quote_id
                JOIN designs d ON d.id=qd.design_id
                WHERE qd.quote_id=?""", (quote_id,)).fetchone()
        if not link:
            raise KeyError("No uploaded design is attached to this quote")

        design = self.design_vault.get(link["design_id"])
        if not design:
            raise KeyError("Design not found")
        model = self._model_asset(link["design_id"])
        if not model:
            raise ValueError("A printable model is required before this custom design can become a product")
        if visibility == "published" and license_status in {"blocked", "prohibited", "commercially_prohibited", "review_required"}:
            raise ValueError("A published product needs a commercially cleared license status")

        product_id = link["product_id"] or str(uuid.uuid4())
        existing_product = self.products.get(product_id) if link["product_id"] else None
        sku = values.get("sku") or (existing_product["sku"] if existing_product else None) or "CUSTOM-%s" % uuid.uuid4().hex[:8].upper()
        product_id = self.products.save({
            "sku": sku,
            "name": name,
            "category": values.get("category") or "Custom Designs",
            "description": values.get("description") or "",
            "designer": values.get("designer") or "",
            "source_url": "",
            "license_name": values.get("license_name") or "Customer-origin design",
            "license_status": license_status,
            "price": price,
            "hours": values.get("hours") or 0,
            "filament": values.get("filament") or 0,
        }, product_id=product_id)
        with self.database.connect() as conn:
            conn.execute("UPDATE designs SET product_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (product_id, link["design_id"]))
            conn.commit()

        storefront = self.products.save_storefront(product_id, {
            "visibility": visibility,
            "origin_type": "customer_custom",
            "source_customer_id": link["customer_id"],
            "customer_title": values.get("customer_title") or name,
            "customer_description": values.get("customer_description") or values.get("description") or "",
        })
        return {
            "product_id": product_id,
            "quote_id": quote_id,
            "quote_number": link["quote_number"],
            "design_id": link["design_id"],
            "customer_id": link["customer_id"],
            "model_asset_id": model["id"],
            "storefront": storefront,
            "customer_eligible": self.products.is_customer_eligible(product_id),
        }
