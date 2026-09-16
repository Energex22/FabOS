"""Internal workflow for turning a customer custom design into a storefront product."""
import uuid


class CustomProductWorkflowService:
    def __init__(self, database, products, design_vault):
        self.database = database
        self.products = products
        self.design_vault = design_vault

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
            link = conn.execute("""SELECT q.id quote_id,q.customer_id,q.quote_number,qd.design_id
                FROM quote_designs qd JOIN quotes q ON q.id=qd.quote_id
                WHERE qd.quote_id=?""", (quote_id,)).fetchone()
        if not link:
            raise KeyError("No uploaded design is attached to this quote")

        design = self.design_vault.get(link["design_id"])
        if not design:
            raise KeyError("Design not found")
        model = self.design_vault.primary_model_asset(link["design_id"])
        if not model:
            raise ValueError("A printable model is required before this custom design can become a product")
        if visibility == "published" and license_status in {"blocked", "prohibited", "commercially_prohibited", "review_required"}:
            raise ValueError("A published product needs a commercially cleared license status")

        product_id = self.products.save({
            "sku": values.get("sku") or "CUSTOM-%s" % uuid.uuid4().hex[:8].upper(),
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
        })
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
