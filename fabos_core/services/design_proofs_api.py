"""HTTP routes for the customer design-proof review workflow."""
import os
import tempfile
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse


ALLOWED_PROOF_EXTENSIONS = {".stl", ".3mf", ".step", ".stp", ".obj", ".png", ".jpg", ".jpeg"}
MAX_PROOF_UPLOAD_BYTES = 25 * 1024 * 1024


class ProofCreateRequest(BaseModel):
    notes: str = Field(default="", max_length=4000)
    send: bool = False


class ProofComment(BaseModel):
    comment: str = Field(default="", max_length=4000)


def register_design_proof_routes(app, get_application, customer_user, administrator_user):
    @app.get("/api/v1/customer/proofs")
    def customer_proofs(user=Depends(customer_user), application=Depends(get_application)):
        return {"proofs": application.design_proofs.list_for_customer(user["id"])}

    @app.get("/api/v1/customer/proofs/{proof_id}")
    def customer_proof(proof_id: str, user=Depends(customer_user), application=Depends(get_application)):
        try:
            return {"proof": application.design_proofs.get_for_customer(user["id"], proof_id)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/customer/proofs/{proof_id}/file")
    def customer_proof_file(proof_id: str, user=Depends(customer_user), application=Depends(get_application)):
        try:
            proof = application.design_proofs.get_for_customer(user["id"], proof_id)
            row = application.design_proofs._row(proof_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not row["stored_path"]:
            raise HTTPException(status_code=404, detail="This proof has no review file.")
        path = Path(str(row["stored_path"])).resolve()
        root = Path(application.design_vault.root).resolve()
        try:
            inside = os.path.commonpath([str(path), str(root)]) == str(root)
        except ValueError:
            inside = False
        if not inside or not path.is_file():
            raise HTTPException(status_code=404, detail="Proof file is unavailable.")
        return FileResponse(str(path), filename=str(row["original_name"] or path.name))

    @app.post("/api/v1/customer/proofs/{proof_id}/approve")
    def approve_customer_proof(proof_id: str, payload: ProofComment, user=Depends(customer_user), application=Depends(get_application)):
        try:
            proof = application.design_proofs.approve(user["id"], proof_id, payload.comment)
            return {"proof": application.design_proofs._public(proof)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/customer/proofs/{proof_id}/request-changes")
    def request_customer_proof_changes(proof_id: str, payload: ProofComment, user=Depends(customer_user), application=Depends(get_application)):
        try:
            proof = application.design_proofs.request_changes(user["id"], proof_id, payload.comment)
            return {"proof": application.design_proofs._public(proof)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/admin/quotes/{quote_id}/proofs")
    def admin_quote_proofs(quote_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        return {"proofs": application.design_proofs.list_for_admin(quote_id=quote_id)}

    @app.post("/api/v1/admin/quotes/{quote_id}/proofs")
    def create_admin_proof(quote_id: str, payload: ProofCreateRequest, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            proof = application.design_proofs.create(quote_id, notes=payload.notes, status="sent" if payload.send else "draft")
            return {"proof": application.design_proofs._public(proof)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/admin/quotes/{quote_id}/proofs/upload")
    async def upload_admin_proof(
        quote_id: str,
        notes: str = File(default="", max_length=4000),
        file: UploadFile = File(...),
        user=Depends(administrator_user),
        application=Depends(get_application),
    ):
        filename = Path(file.filename or "").name
        extension = Path(filename).suffix.lower()
        if not filename or extension not in ALLOWED_PROOF_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Unsupported proof file type")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                temp_path = tmp.name
                size = 0
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_PROOF_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="Proof file must be 25 MB or smaller")
                    tmp.write(chunk)

            with application.database.connect() as conn:
                link = conn.execute(
                    "SELECT design_id FROM quote_designs WHERE quote_id=?", (quote_id,)
                ).fetchone()
            if not link:
                raise HTTPException(status_code=404, detail="No customer design is attached to this quote.")

            application.design_vault.new_version(link["design_id"])
            application.design_vault.import_file(link["design_id"], temp_path, make_primary=extension in {".stl", ".3mf", ".step", ".stp"})
            proof = application.design_proofs.create(quote_id, notes=notes, status="sent")
            return {"proof": application.design_proofs._public(proof), "file": {"name": filename, "bytes": size}}
        except HTTPException:
            raise
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="The proof could not be stored") from exc
        finally:
            try:
                if temp_path:
                    os.unlink(temp_path)
            except OSError:
                pass
            await file.close()

    @app.post("/api/v1/admin/proofs/{proof_id}/send")
    def send_admin_proof(proof_id: str, payload: ProofComment, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            proof = application.design_proofs.send(proof_id, payload.comment if payload.comment else None)
            return {"proof": application.design_proofs._public(proof)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
