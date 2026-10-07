"""Customer-facing design proof and revision workflow.

A proof is an immutable review checkpoint tied to a quote's customer-uploaded design.
Only the customer owning the quote can approve/request changes, and production checks
the latest proof before creating print jobs.
"""
import json
import logging
import uuid
from datetime import datetime

from fabos_core.services import notifications

logger = logging.getLogger(__name__)


class DesignProofService:
    VALID_STATUSES = {"draft", "sent", "changes_requested", "approved", "superseded"}

    def __init__(self, database, design_vault):
        self.database = database
        self.design_vault = design_vault
        self._ensure_schema()

    def _ensure_schema(self):
        with self.database.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS design_proofs(
                id TEXT PRIMARY KEY,
                quote_id TEXT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
                design_id TEXT NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
                design_version INTEGER NOT NULL,
                asset_id TEXT REFERENCES design_assets(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                notes TEXT NOT NULL DEFAULT '',
                customer_note TEXT NOT NULL DEFAULT '',
                customer_comment TEXT NOT NULL DEFAULT '',
                sent_at TEXT,
                approved_at TEXT,
                approved_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_design_proofs_quote ON design_proofs(quote_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_design_proofs_status ON design_proofs(status,updated_at)")
            conn.commit()

    def _quote_design(self, quote_id):
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT q.id quote_id,q.customer_id,qd.design_id,d.current_version,d.name design_name
                   FROM quotes q JOIN quote_designs qd ON qd.quote_id=q.id
                   JOIN designs d ON d.id=qd.design_id WHERE q.id=?""", (quote_id,)
            ).fetchone()
        if not row:
            raise KeyError("No customer design is attached to this quote.")
        return row

    def _row(self, proof_id):
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT p.*,q.customer_id,q.quote_number,d.name design_name,
                          a.original_name,a.stored_path,a.kind,a.bytes,a.width_mm,a.depth_mm,a.height_mm
                   FROM design_proofs p
                   JOIN quotes q ON q.id=p.quote_id
                   JOIN designs d ON d.id=p.design_id
                   LEFT JOIN design_assets a ON a.id=p.asset_id
                   WHERE p.id=?""", (proof_id,)
            ).fetchone()
        if not row:
            raise KeyError("Design proof not found.")
        return row

    def _public(self, row):
        # Customer-safe projection. ``notes`` is staff-authored (set by the
        # admin-only proof create/upload routes) and must never reach
        # customers; the customer-visible fields are ``customer_note`` (the
        # staff-approved per-revision note, set at send time) and
        # ``customer_comment`` (the customer's own change-request text).
        # ``customer_note`` falls back to "" for partial rows (e.g. unit-test
        # fakes); every real query selects p.* so the column is present.
        keys = row.keys() if hasattr(row, "keys") else ()
        return {
            "id": row["id"], "quote_id": row["quote_id"], "quote_number": row["quote_number"],
            "design_id": row["design_id"], "design_version": row["design_version"],
            "asset_id": row["asset_id"], "status": row["status"],
            "customer_note": row["customer_note"] if "customer_note" in keys else "",
            "customer_comment": row["customer_comment"], "sent_at": row["sent_at"],
            "approved_at": row["approved_at"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "design_name": row["design_name"],
            "asset_name": row["original_name"], "asset_kind": row["kind"],
            "dimensions_mm": {
                "width": row["width_mm"], "depth": row["depth_mm"], "height": row["height_mm"]
            },
        }

    def _admin(self, row):
        # Admin projection: everything customers see plus staff notes.
        payload = self._public(row)
        payload["notes"] = row["notes"]
        return payload

    def create(self, quote_id, *, notes="", customer_note="", status="draft"):
        link = self._quote_design(quote_id)
        status = str(status or "draft").strip().lower()
        if status not in {"draft", "sent"}:
            raise ValueError("A new proof must be draft or sent.")
        with self.database.connect() as conn:
            # A new proof supersedes any prior review checkpoint.
            conn.execute(
                "UPDATE design_proofs SET status='superseded',updated_at=CURRENT_TIMESTAMP "
                "WHERE quote_id=? AND status IN ('draft','sent','changes_requested')",
                (quote_id,),
            )
            asset = conn.execute(
                """SELECT id FROM design_assets WHERE design_id=? AND version_id=(
                     SELECT id FROM design_versions WHERE design_id=? AND version=?
                   ) AND kind IN ('STL','3MF','STEP','IMAGE')
                   ORDER BY is_primary DESC,created_at DESC LIMIT 1""",
                (link["design_id"], link["design_id"], link["current_version"]),
            ).fetchone()
            proof_id = str(uuid.uuid4())
            sent_at = datetime.utcnow().isoformat(timespec="seconds") if status == "sent" else None
            conn.execute(
                """INSERT INTO design_proofs(
                   id,quote_id,design_id,design_version,asset_id,status,notes,customer_note,sent_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (proof_id,quote_id,link["design_id"],link["current_version"],
                 asset["id"] if asset else None,status,str(notes or "").strip(),
                 str(customer_note or "").strip(),sent_at),
            )
            conn.commit()
        return self._row(proof_id)

    def send(self, proof_id, notes=None, customer_note=None):
        row = self._row(proof_id)
        if row["status"] not in {"draft", "changes_requested"}:
            raise ValueError("Only a draft or revised proof can be sent.")
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE design_proofs SET status='sent',notes=?,customer_note=?,sent_at=CURRENT_TIMESTAMP,"
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["notes"] if notes is None else str(notes or "").strip(),
                 row["customer_note"] if customer_note is None else str(customer_note or "").strip(),
                 proof_id),
            )
            conn.commit()
        return self._row(proof_id)

    def list_for_admin(self, quote_id=None, status=None):
        with self.database.connect() as conn:
            where, args = [], []
            if quote_id:
                where.append("p.quote_id=?"); args.append(quote_id)
            if status and status != "All":
                where.append("p.status=?"); args.append(str(status).lower())
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            rows = conn.execute(
                """SELECT p.*,q.customer_id,q.quote_number,d.name design_name,
                          a.original_name,a.kind,a.bytes,a.width_mm,a.depth_mm,a.height_mm
                   FROM design_proofs p
                   JOIN quotes q ON q.id=p.quote_id
                   JOIN designs d ON d.id=p.design_id
                   LEFT JOIN design_assets a ON a.id=p.asset_id""" + clause +
                " ORDER BY p.created_at DESC", args
            ).fetchall()
        return [self._admin(row) for row in rows]

    def latest_for_quote(self, quote_id):
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT p.*,q.customer_id,q.quote_number,d.name design_name,
                          a.original_name,a.kind,a.bytes,a.width_mm,a.depth_mm,a.height_mm
                   FROM design_proofs p
                   JOIN quotes q ON q.id=p.quote_id
                   JOIN designs d ON d.id=p.design_id
                   LEFT JOIN design_assets a ON a.id=p.asset_id
                   WHERE p.quote_id=? ORDER BY p.created_at DESC LIMIT 1""",
                (quote_id,),
            ).fetchone()
        return self._public(row) if row else None

    def get_for_customer(self, user_id, proof_id):
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT p.*,q.customer_id,q.quote_number,d.name design_name,
                          a.original_name,a.kind,a.bytes,a.width_mm,a.depth_mm,a.height_mm
                   FROM design_proofs p
                   JOIN quotes q ON q.id=p.quote_id
                   JOIN designs d ON d.id=p.design_id
                   LEFT JOIN design_assets a ON a.id=p.asset_id
                   JOIN customer_accounts ca ON ca.customer_id=q.customer_id
                   WHERE p.id=? AND ca.user_id=?""", (proof_id,user_id)
            ).fetchone()
        if not row:
            raise KeyError("Design proof not found.")
        return self._public(row)

    def list_for_customer(self, user_id):
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT p.*,q.customer_id,q.quote_number,d.name design_name,
                          a.original_name,a.kind,a.bytes,a.width_mm,a.depth_mm,a.height_mm
                   FROM design_proofs p
                   JOIN quotes q ON q.id=p.quote_id
                   JOIN designs d ON d.id=p.design_id
                   LEFT JOIN design_assets a ON a.id=p.asset_id
                   JOIN customer_accounts ca ON ca.customer_id=q.customer_id
                   WHERE ca.user_id=? AND p.status IN ('sent','approved','changes_requested')
                   ORDER BY p.created_at DESC""", (user_id,)
            ).fetchall()
        return [self._public(row) for row in rows]

    def _customer_action(self, user_id, proof_id, action, comment=""):
        row = self.get_for_customer(user_id, proof_id)
        if row["status"] != "sent":
            raise ValueError("This proof is no longer awaiting customer review.")
        now = datetime.utcnow().isoformat(timespec="seconds")
        status = "approved" if action == "approve" else "changes_requested"
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE design_proofs SET status=?,customer_comment=?,approved_at=?,approved_by=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (status,str(comment or "").strip(),now if status == "approved" else None,
                 user_id if status == "approved" else None,proof_id),
            )
            conn.commit()
        updated = self._row(proof_id)
        if status == "changes_requested":
            # Phase 1 notification hook (Phase 2 consumes it for staff
            # alerts). Never let the hook break the customer's action.
            try:
                notifications.notify_proof_changes_requested(updated)
            except Exception:
                logger.exception("proof changes_requested hook failed for proof %s", proof_id)
        return updated

    def approve(self, user_id, proof_id, comment=""):
        return self._customer_action(user_id, proof_id, "approve", comment)

    def request_changes(self, user_id, proof_id, comment):
        comment = str(comment or "").strip()
        if not comment:
            raise ValueError("Please describe the requested changes.")
        return self._customer_action(user_id, proof_id, "changes", comment)

    def production_gate(self, order_id):
        with self.database.connect() as conn:
            order = conn.execute("SELECT quote_id FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order or not order["quote_id"]:
                return {"required": False, "approved": True, "reason": None}
            design = conn.execute(
                "SELECT design_id FROM quote_designs WHERE quote_id=?", (order["quote_id"],)
            ).fetchone()
            if not design:
                return {"required": False, "approved": True, "reason": None}
            proof = conn.execute(
                "SELECT * FROM design_proofs WHERE quote_id=? ORDER BY created_at DESC LIMIT 1",
                (order["quote_id"],),
            ).fetchone()
        if not proof:
            return {"required": True, "approved": False, "reason": "Customer design proof is required before production."}
        if proof["status"] != "approved":
            return {"required": True, "approved": False, "reason": "Customer has not approved the latest design proof."}
        return {"required": True, "approved": True, "reason": None, "proof_id": proof["id"], "design_version": proof["design_version"]}
