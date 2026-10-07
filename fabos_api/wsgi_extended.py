"""Extended WSGI routes: admin workspace, customer CAD, and remaining customer routes.

These mirror the FastAPI routes in fabos_core/api.py,
fabos_core/services/admin_api.py, fabos_core/services/customer_api_writes.py,
fabos_core/services/design_proofs_api.py, and fabos_core/services/payment_api.py
by calling the same core services. They follow the pattern of the earlier
customer quote/proof WSGI routes: authenticate, check the account type or
permission, call the core service, and map errors onto the WSGI response shape.

Kept in a separate module so FabOSAPI.request() stays readable; the dispatcher
below is consulted for any route the main dispatcher does not handle.
"""

import base64
import json
import mimetypes
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fabos_core.services.cad_generation import CadGenerationError
from fabos_core.services.rate_limit import RateLimiter

# Mirrors the FastAPI CAD limiter (20 requests / 5 minutes per customer and
# operation) so the WSGI transport cannot be used to bypass it.
_cad_rate_limiter = RateLimiter(20, 300)

_JOB_ID_RE = re.compile(r"[0-9a-fA-F-]{20,80}")

_USER_FIELDS = ("id", "username", "email", "account_type", "role", "active",
                "created_at", "updated_at", "last_login_at")


def _q(query, name, default=""):
    values = (query or {}).get(name)
    if not values:
        return default
    return values[0]


def _q_int(query, name, default):
    try:
        return int(_q(query, name, default))
    except (TypeError, ValueError):
        raise ValueError("Invalid %s" % name)


def _rows(rows):
    return [dict(row) for row in (rows or [])]


def _admin(api, headers):
    """Require an administrator account (mirrors FastAPI administrator_user)."""
    context = api._context(headers)
    if str(context.get("account_type") or "").lower() != "administrator":
        raise PermissionError("Administrator account required")
    return context


def _operations(api, headers):
    """Require a team account with production.read (mirrors operations_user)."""
    context = api._context(headers)
    account_type = str(context.get("account_type") or "").lower()
    if account_type not in ("employee", "administrator"):
        raise PermissionError("Team account required")
    api.core.permissions.require(account_type, "production.read", user_id=context.get("id"))
    return context


def _customer(api, headers):
    """Require a customer account (mirrors the customer_* dependencies)."""
    context = api._context(headers)
    if str(context.get("account_type") or "").lower() != "customer":
        raise PermissionError("Customer account required")
    return context


def _cad_limit(api, user_id, operation):
    """Enforce the per-customer CAD rate limit; returns a 429 response or None."""
    key = "cad:%s:%s" % (user_id, operation)
    if not _cad_rate_limiter.allow(key):
        return api._response(429, {
            "error": "CAD request limit reached. Try again later.",
            "retry_after": _cad_rate_limiter.retry_after(key),
        })
    return None


def _sniff_reference_image_type(raw):
    """Detect a reference image's true type from magic bytes.

    Local copy of fabos_core.api._sniff_reference_image_type so this module
    does not import the FastAPI application module.
    """
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _project_user(row):
    keys = row.keys() if hasattr(row, "keys") else ()
    return {key: row[key] for key in _USER_FIELDS if key in keys}


def _cad_artifacts(api, job_id, artifacts):
    return [
        {"format": item.get("format"), "bytes": item.get("bytes"),
         "url": "/api/%s/customer/cad/artifacts/%s/%s" % (api.VERSION, job_id, item.get("format"))}
        for item in (artifacts or [])
        if item.get("format") in {"stl", "step", "3mf"}
    ]


def _parse_multipart_body(headers, raw_body):
    from fabos_api.app import _parse_multipart
    parsed = _parse_multipart(raw_body, (headers or {}).get("Content-Type", ""))
    if parsed is None:
        raise ValueError("Expected a multipart/form-data request")
    return parsed


def handle_extended_routes(api, method, route, query, body, headers, raw_body):
    """Dispatch admin/CAD/extended customer routes.

    Returns a {"status", "data"} response dict, or None when no extended
    route matches (the caller then returns 404).
    """
    core = api.core
    body = body or {}
    v = api.VERSION

    # ------------------------------------------------------------------
    # Customer CAD routes (mirror fabos_core/api.py customer_cad_*)
    # ------------------------------------------------------------------
    if route == ["api", v, "customer", "cad", "capabilities"] and method == "GET":
        _customer(api, headers)
        return api._response(200, core.cad_generation.capabilities())

    if route == ["api", v, "customer", "cad", "printers"] and method == "GET":
        _customer(api, headers)
        return api._response(200, {"printers": core.cad_generation.list_printers()})

    if route == ["api", v, "customer", "cad", "generate"] and method == "POST":
        user = _customer(api, headers)
        limited = _cad_limit(api, user["id"], "generate")
        if limited:
            return limited
        prompt = body.get("prompt")
        spec = body.get("spec")
        if not prompt and not spec:
            raise ValueError("Provide a design prompt or structured specification")
        try:
            result = core.cad_generation.generate(
                spec=spec, prompt=prompt,
                output_formats=body.get("output_formats") or ["stl", "step", "3mf"],
                owner_id=user["id"],
            )
        except CadGenerationError as exc:
            return api._response(400, {"error": str(exc)})
        except Exception:
            return api._response(500, {"error": "CAD generation failed"})
        return api._response(200, {
            "job_id": result["job_id"], "spec": result["spec"],
            "verification": result["verification"],
            "artifacts": _cad_artifacts(api, result["job_id"], result["artifacts"]),
        })

    if route == ["api", v, "customer", "cad", "analyze-reference"] and method == "POST":
        user = _customer(api, headers)
        limited = _cad_limit(api, user["id"], "reference")
        if limited:
            return limited
        fields, files = _parse_multipart_body(headers, raw_body)
        uploads = [files[name] for name in sorted(files)]
        if not uploads:
            return api._response(400, {"error": "Upload at least one reference image"})
        if len(uploads) > 4:
            return api._response(400, {"error": "A maximum of 4 reference images is supported"})
        images = []
        for _filename, raw in uploads:
            if len(raw) > 5 * 1024 * 1024:
                return api._response(400, {"error": "Each reference image must be 5 MB or smaller"})
            # Never trust a client-supplied content type: only the sniffed
            # magic bytes decide, mirroring the FastAPI route.
            actual_type = _sniff_reference_image_type(raw)
            if actual_type not in {"image/png", "image/jpeg", "image/webp"}:
                return api._response(400, {"error": "Only PNG, JPEG, and WebP reference images are supported"})
            images.append("data:%s;base64,%s" % (actual_type, base64.b64encode(raw).decode("ascii")))
        try:
            result = core.ai.design_spec_from_images(images, reference_note=str(fields.get("reference_note", "") or ""))
        except Exception:
            return api._response(400, {"error": "Reference analysis failed"})
        metadata = result.get("metadata") or {}
        return api._response(200, {
            "spec": result,
            "scale_confirmed": bool(metadata.get("scale_confirmed")),
            "scale_source": metadata.get("scale_source", "none"),
            "reference_kind": metadata.get("reference_kind", "mixed"),
            "confidence": metadata.get("confidence", 0.0),
            "missing_dimensions": metadata.get("missing_dimensions", []),
            "feature_uncertainties": metadata.get("feature_uncertainties", []),
            "needs_user_confirmation": bool(metadata.get("needs_user_confirmation")),
        })

    if route == ["api", v, "customer", "cad", "preflight"] and method == "POST":
        user = _customer(api, headers)
        limited = _cad_limit(api, user["id"], "preflight")
        if limited:
            return limited
        prompt = body.get("prompt")
        spec = body.get("spec")
        if not prompt and not spec:
            raise ValueError("Provide a design prompt or structured specification")
        try:
            result = core.cad_generation.preflight(spec=spec, prompt=prompt, printer_id=body.get("printer_id"))
        except CadGenerationError as exc:
            return api._response(400, {"error": str(exc)})
        except Exception:
            return api._response(500, {"error": "CAD preflight failed"})
        return api._response(200, result)

    if len(route) == 7 and route[:4] == ["api", v, "customer", "cad"] and route[4] == "jobs" and route[6] == "revise" and method == "POST":
        user = _customer(api, headers)
        limited = _cad_limit(api, user["id"], "revise")
        if limited:
            return limited
        job_id = route[5]
        if not _JOB_ID_RE.fullmatch(job_id):
            return api._response(404, {"error": "CAD job not found"})
        instruction = str(body.get("instruction") or "")
        if not instruction:
            raise ValueError("A revision instruction is required")
        try:
            result = core.cad_generation.revise(
                job_id=job_id, instruction=instruction,
                output_formats=body.get("output_formats") or ["stl", "step"],
                owner_id=user["id"],
            )
        except CadGenerationError as exc:
            return api._response(400, {"error": str(exc)})
        except Exception:
            return api._response(500, {"error": "CAD revision failed"})
        return api._response(200, {
            "job_id": result["job_id"], "spec": result["spec"],
            "verification": result["verification"],
            "artifacts": _cad_artifacts(api, result["job_id"], result["artifacts"]),
        })

    if route == ["api", v, "customer", "cad", "jobs"] and method == "GET":
        user = _customer(api, headers)
        try:
            limit = int(_q(query, "limit", "50"))
        except (TypeError, ValueError):
            return api._response(400, {"error": "Invalid CAD history limit"})
        try:
            jobs = core.cad_generation.list_jobs(user["id"], limit=limit)
        except (TypeError, ValueError):
            return api._response(400, {"error": "Invalid CAD history limit"})
        for job in jobs:
            job["artifacts"] = _cad_artifacts(api, job["id"], job.get("artifacts"))
        return api._response(200, {"jobs": jobs})

    if len(route) == 6 and route[:5] == ["api", v, "customer", "cad", "jobs"] and method == "GET":
        user = _customer(api, headers)
        job_id = route[5]
        if not _JOB_ID_RE.fullmatch(job_id):
            return api._response(404, {"error": "CAD job not found"})
        result = core.cad_generation.get_job(job_id, owner_id=user["id"])
        if not result:
            return api._response(404, {"error": "CAD job not found"})
        result["artifacts"] = _cad_artifacts(api, job_id, result.get("artifacts"))
        return api._response(200, result)

    if len(route) == 7 and route[:4] == ["api", v, "customer", "cad"] and route[4] == "artifacts" and method == "GET":
        user = _customer(api, headers)
        job_id, fmt = route[5], route[6]
        if not _JOB_ID_RE.fullmatch(job_id):
            return api._response(404, {"error": "CAD artifact not found"})
        if fmt.lower() not in {"stl", "step", "3mf"}:
            return api._response(404, {"error": "CAD artifact not found"})
        # Same traversal guard as the FastAPI route: the artifact must live
        # directly inside the job folder under the CAD root, and the job must
        # belong to the requesting customer.
        root = core.cad_generation.root.resolve()
        target = (root / job_id / ("model." + fmt.lower())).resolve()
        try:
            if target.parent.parent != root or not target.is_file():
                return api._response(404, {"error": "CAD artifact not found"})
            metadata = json.loads((target.parent / "metadata.json").read_text(encoding="utf-8"))
            if str(metadata.get("owner_id") or "") != str(user["id"]):
                return api._response(404, {"error": "CAD artifact not found"})
        except (OSError, ValueError):
            return api._response(404, {"error": "CAD artifact not found"})
        return {
            "status": 200,
            "data": {"_wsgi_file": {
                "bytes": target.read_bytes(),
                "filename": target.name,
                "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            }},
        }

    # ------------------------------------------------------------------
    # Multipart public quote-request upload (mirrors the FastAPI
    # POST /api/v1/quote-requests/upload route).
    # ------------------------------------------------------------------
    if route == ["api", v, "quote-requests", "upload"] and method == "POST":
        # File uploads require an account; anonymous callers get a 401 from
        # _context, mirroring the FastAPI current_user dependency.
        api._context(headers)
        fields, files = _parse_multipart_body(headers, raw_body)
        if "file" not in files:
            raise ValueError("A model file is required")
        filename, file_bytes = files["file"]
        from fabos_core.services.customer_api_writes import (
            ALLOWED_CUSTOM_UPLOAD_EXTENSIONS, MAX_CUSTOM_UPLOAD_BYTES,
            _create_public_quote, _public_quote, _validate_model_file,
        )
        filename = Path(filename or "").name
        if not filename:
            return api._response(400, {"error": "A model filename is required"})
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_CUSTOM_UPLOAD_EXTENSIONS:
            return api._response(415, {"error": "Unsupported 3D model file type"})
        if len(file_bytes) > MAX_CUSTOM_UPLOAD_BYTES:
            return api._response(413, {"error": "3D model must be 25 MB or smaller"})
        name = str(fields.get("name", "") or "").strip()
        email = str(fields.get("email", "") or "").strip().lower()
        idea = str(fields.get("idea", "") or "").strip()
        if not name or not email or "@" not in email or not idea:
            raise ValueError("Name, a valid email, and a project idea are required")
        try:
            quantity = int(fields.get("quantity", 1))
        except (TypeError, ValueError):
            raise ValueError("Quantity must be a positive integer")
        if quantity < 1 or quantity > 1000:
            raise ValueError("Quantity must be between 1 and 1000")
        # Stage and validate the upload before creating customer/quote
        # records, mirroring the FastAPI route.
        temp_path = None
        quote_id = None
        design_id = None
        quote = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                temp_path = tmp.name
                tmp.write(file_bytes)
            try:
                _validate_model_file(temp_path, extension)
            except ValueError as exc:
                return api._response(400, {"error": str(exc)})
            existing = core.customers.list(query=email)
            customer_id = next(
                (str(row["id"]) for row in existing if str(row["email"] or "").lower() == email),
                None,
            )
            if not customer_id:
                customer_id = core.customers.save({
                    "name": name, "email": email, "phone": "",
                    "notes": "Public custom-work request",
                })
            project = {
                "idea": idea,
                "dimensions": str(fields.get("dimensions", "") or ""),
                "material": str(fields.get("material", "") or ""),
                "quantity": quantity,
                "notes": str(fields.get("notes", "") or ""),
            }
            project["notes"] = (project["notes"] or "").strip()
            project["notes"] += ("\n" if project["notes"] else "") + "File: " + filename
            quote_id = _create_public_quote(core, customer_id, project)
            quote = core.quotes.get(quote_id)[0]
            design_id = str(uuid.uuid4())
            version_id = str(uuid.uuid4())
            safe_name = "Custom Quote " + str(quote["quote_number"])
            with core.database.connect() as conn:
                conn.execute(
                    "INSERT INTO designs(id,product_id,name,current_version,notes) VALUES(?,?,?,1,?)",
                    (design_id, None, safe_name, "Customer custom quote %s" % quote["quote_number"]),
                )
                conn.execute(
                    "INSERT INTO design_versions(id,design_id,version,label,notes) VALUES(?,?,?,?,?)",
                    (version_id, design_id, 1, "Customer upload", "Uploaded with custom quote request"),
                )
                conn.execute("INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)", (quote_id, design_id))
                conn.commit()
            core.design_vault.import_file(design_id, temp_path, make_primary=True)
        except PermissionError as exc:
            _cleanup_quote_request(core, quote_id, design_id)
            return api._response(403, {"error": str(exc)})
        except (KeyError, ValueError) as exc:
            _cleanup_quote_request(core, quote_id, design_id)
            return api._response(400, {"error": str(exc)})
        except Exception:
            _cleanup_quote_request(core, quote_id, design_id)
            return api._response(500, {"error": "The model could not be stored"})
        finally:
            try:
                if temp_path:
                    os.unlink(temp_path)
            except OSError:
                pass
        return api._response(201, {
            "quote": _public_quote(quote),
            "request_number": str(quote["quote_number"]),
            "design_id": design_id,
            "file": {"name": filename, "bytes": len(file_bytes), "extension": extension},
        })

    # ------------------------------------------------------------------
    # Admin catalog (mirror fabos_core/api.py admin_catalog_*)
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "catalog"] and method == "GET":
        _admin(api, headers)
        rows = core.products.list(
            _q(query, "q"), _q(query, "category", "All"),
            _q(query, "sort", "name"),
            _q(query, "desc", "0") not in ("0", "false", "no"),
        )
        products = []
        for row in rows:
            products.append({
                "product": dict(row),
                "storefront": core.products.storefront_state(row["id"]),
                "customer_eligible": core.products.is_customer_eligible(row["id"]),
            })
        return api._response(200, {"products": products})

    if len(route) == 5 and route[:4] == ["api", v, "admin", "catalog"] and method == "GET":
        _admin(api, headers)
        row = core.products.get(route[4])
        if not row:
            return api._response(404, {"error": "Product not found"})
        return api._response(200, {
            "product": dict(row),
            "storefront": core.products.storefront_state(route[4]),
            "customer_eligible": core.products.is_customer_eligible(route[4]),
        })

    if len(route) == 6 and route[:4] == ["api", v, "admin", "catalog"] and route[5] == "storefront" and method == "PATCH":
        _admin(api, headers)
        product_id = route[4]
        row = core.products.get(product_id)
        if not row:
            return api._response(404, {"error": "Product not found"})
        values = {
            "visibility": str(body.get("visibility") or "draft"),
            "origin_type": str(body.get("origin_type") or "catalog_import"),
            "source_customer_id": body.get("source_customer_id"),
            "customer_title": body.get("customer_title"),
            "customer_description": body.get("customer_description"),
        }
        if values["visibility"].lower() == "published":
            state = core.products.storefront_state(product_id)
            reasons = []
            if not state["has_model"]:
                reasons.append("A printable 3D model is required")
            if not state["has_price"]:
                reasons.append("A customer price greater than zero is required")
            if state["license_status"] in {"blocked", "prohibited", "commercially_prohibited", "review_required"}:
                reasons.append("The license requires review or does not allow commercial publication")
            if reasons:
                return api._response(409, {"error": {"message": "Product is not ready to publish", "reasons": reasons}})
        state = core.products.save_storefront(product_id, values)
        return api._response(200, {
            "product": dict(row),
            "storefront": state,
            "customer_eligible": core.products.is_customer_eligible(product_id),
        })

    # ------------------------------------------------------------------
    # Admin quotes (mirror fabos_core/api.py admin_quotes_*)
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "quotes"] and method == "GET":
        _admin(api, headers)
        rows = core.quotes.list(
            query=_q(query, "q"), status=_q(query, "status", "All"),
            group=_q(query, "group", "all"),
        )
        return api._response(200, {"quotes": _rows(rows)})

    if len(route) == 5 and route[:4] == ["api", v, "admin", "quotes"] and method == "GET":
        _admin(api, headers)
        try:
            row, items = core.quotes.get(route[4])
        except KeyError:
            return api._response(404, {"error": "Quote not found"})
        return api._response(200, {
            "quote": dict(row), "items": _rows(items),
            "versions": _rows(core.quotes.versions(route[4])),
        })

    if len(route) == 5 and route[:4] == ["api", v, "admin", "quotes"] and method == "PUT":
        _admin(api, headers)
        quote_id = route[4]
        try:
            row, existing_items = core.quotes.get(quote_id)
        except KeyError:
            return api._response(404, {"error": "Quote not found"})
        requested_status = str(body.get("status") or row["status"] or "draft").lower()
        if requested_status in {"accepted", "approved", "declined"}:
            return api._response(409, {"error": "Customer decision states can only be changed by the customer workflow."})
        items = body.get("items")
        if not items:
            items = [dict(item) for item in existing_items]
        expires_at = body.get("expires_at", row["expires_at"])
        if requested_status == "sent" and not expires_at:
            expires_at = (datetime.utcnow().date() + timedelta(days=14)).isoformat()
        data = {
            "customer_id": row["customer_id"], "status": requested_status,
            "expires_at": expires_at, "notes": body.get("notes", row["notes"]),
        }
        try:
            core.quotes.save(data, items, quote_id=quote_id)
        except (KeyError, ValueError, RuntimeError) as exc:
            return api._response(400, {"error": str(exc)})
        updated, updated_items = core.quotes.get(quote_id)
        return api._response(200, {
            "quote": dict(updated), "items": _rows(updated_items),
            "versions": _rows(core.quotes.versions(quote_id)),
        })

    # ------------------------------------------------------------------
    # Admin customers / orders
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "customers"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {"customers": _rows(core.customers.list(query=_q(query, "q")))})

    if route == ["api", v, "admin", "customers"] and method == "POST":
        _admin(api, headers)
        try:
            customer_id = core.customers.save({
                "name": str(body.get("name") or "").strip(),
                "email": str(body.get("email") or "").strip().lower(),
                "phone": str(body.get("phone") or "").strip(),
                "notes": str(body.get("notes") or "").strip(),
            })
        except ValueError as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {
            "customer_id": customer_id,
            "customer": dict(core.customers.get(customer_id)),
        })

    if len(route) == 6 and route[:4] == ["api", v, "admin", "orders"] and route[5] == "start-production" and method == "POST":
        _admin(api, headers)
        order_id = route[4]
        try:
            created = core.production.create_jobs_from_order(order_id)
        except KeyError as exc:
            return api._response(404, {"error": str(exc)})
        except ValueError as exc:
            return api._response(409, {"error": str(exc)})
        return api._response(200, {"order_id": order_id, "jobs_created": created, "started": bool(created)})

    if route == ["api", v, "admin", "operations", "automation", "tick"] and method == "POST":
        _operations(api, headers)
        return api._response(200, core.production_automation.tick())

    # ------------------------------------------------------------------
    # Admin printers
    # ------------------------------------------------------------------
    if len(route) == 6 and route[:4] == ["api", v, "admin", "printers"] and method == "POST":
        _admin(api, headers)
        printer_id, action = route[4], route[5]
        with core.database.connect() as conn:
            printer = conn.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
        if not printer:
            return api._response(404, {"error": "Printer not found"})
        try:
            if action == "preflight":
                result = core.octoprint_print.preflight(printer)
            elif action == "preheat":
                hotend = body.get("hotend")
                bed = body.get("bed")
                if hotend is None and bed is None:
                    return api._response(400, {"error": "Set a hotend or bed target."})
                result = core.octoprint_print.preheat_together(printer, hotend, bed)
            elif action == "pause":
                result = core.octoprint_print.pause(printer)
            elif action == "resume":
                result = core.octoprint_print.resume(printer)
            elif action == "cancel":
                result = core.octoprint_print.cancel(printer)
            else:
                return api._response(400, {"error": "Unsupported printer action"})
        except (ValueError, RuntimeError) as exc:
            return api._response(409, {"error": str(exc)})
        payload = {"printer_id": printer_id, "result": result}
        if action in ("pause", "resume", "cancel"):
            payload["action"] = action
        return api._response(200, payload)

    # ------------------------------------------------------------------
    # Admin users & permissions
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "users"] and method == "GET":
        _admin(api, headers)
        users = []
        for row in core.accounts.list_users():
            item = _project_user(row)
            item["permissions"] = sorted(core.permissions.permissions_for_user(row["id"], row["account_type"]))
            users.append(item)
        return api._response(200, {"users": users})

    if len(route) == 5 and route[:4] == ["api", v, "admin", "users"] and method == "GET":
        _admin(api, headers)
        user_id = route[4]
        row = core.accounts.get_user(user_id)
        if not row:
            return api._response(404, {"error": "User not found"})
        summary = core.accounts.account_summary(user_id)
        return api._response(200, {
            "user": _project_user(row),
            "customer": dict(summary.get("customer")) if summary.get("customer") else None,
            "employee": dict(summary.get("employee")) if summary.get("employee") else None,
            "permissions": sorted(core.permissions.permissions_for_user(user_id, row["account_type"])),
        })

    if len(route) == 5 and route[:4] == ["api", v, "admin", "users"] and method == "PATCH":
        context = _admin(api, headers)
        user_id = route[4]
        row = core.accounts.get_user(user_id)
        if not row:
            return api._response(404, {"error": "User not found"})
        values = {key: body[key] for key in ("email", "account_type", "active") if key in body}
        row_keys = row.keys() if hasattr(row, "keys") else ()
        target_is_owner = str(row["role"] or "").lower() == "owner" if "role" in row_keys else False
        actor = core.accounts.get_user(context["id"])
        actor_keys = actor.keys() if actor is not None and hasattr(actor, "keys") else ()
        actor_is_owner = str(actor["role"] or "").lower() == "owner" if actor is not None and "role" in actor_keys else False
        if target_is_owner and not actor_is_owner:
            return api._response(403, {"error": "Only the owner can modify the owner account"})
        if user_id == context["id"] and (values.get("active") is False or values.get("account_type") not in (None, "administrator")):
            return api._response(409, {"error": "You cannot disable or demote your own administrator account"})
        if row["account_type"] == "administrator" and (values.get("active") is False or values.get("account_type") not in (None, "administrator")):
            administrators = core.accounts.list_users(account_type="administrator", active_only=True)
            if len(administrators) <= 1:
                return api._response(409, {"error": "At least one active administrator account must remain"})
        updated = core.accounts.update_account(user_id, **values)
        return api._response(200, {"user": _project_user(updated)})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "users"] and route[5] == "password" and method == "POST":
        context = _admin(api, headers)
        user_id = route[4]
        target = core.accounts.get_user(user_id)
        if not target:
            return api._response(404, {"error": "User not found"})
        actor = core.accounts.get_user(context["id"])
        target_keys = target.keys() if hasattr(target, "keys") else ()
        actor_keys = actor.keys() if actor is not None and hasattr(actor, "keys") else ()
        if "role" in target_keys and str(target["role"] or "").lower() == "owner" and str((actor or {}).get("role") or "").lower() != "owner":
            return api._response(403, {"error": "Only the owner can change the owner password"})
        password = str(body.get("password") or "")
        if len(password) < 8:
            return api._response(400, {"error": "Password must be at least 8 characters"})
        core.auth.set_password(user_id, password)
        revoked = core.auth.revoke_user_sessions(user_id)
        return api._response(200, {"updated": True, "sessions_revoked": revoked})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "users"] and route[5] == "revoke-sessions" and method == "POST":
        _admin(api, headers)
        user_id = route[4]
        if not core.accounts.get_user(user_id):
            return api._response(404, {"error": "User not found"})
        return api._response(200, {"sessions_revoked": core.auth.revoke_user_sessions(user_id)})

    if route == ["api", v, "admin", "permissions"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {
            "permissions": list(core.permissions.all_permissions()),
            "roles": {role: sorted(core.permissions.permissions_for_account_type(role))
                      for role in ("customer", "employee", "administrator")},
        })

    if len(route) == 6 and route[:4] == ["api", v, "admin", "users"] and route[5] == "permissions" and method == "GET":
        _admin(api, headers)
        user_id = route[4]
        row = core.accounts.get_user(user_id)
        if not row:
            return api._response(404, {"error": "User not found"})
        return api._response(200, {
            "user_id": user_id,
            "account_type": row["account_type"],
            "effective": sorted(core.permissions.permissions_for_user(user_id, row["account_type"])),
            "role_default": sorted(core.permissions.permissions_for_account_type(row["account_type"])),
        })

    if len(route) == 7 and route[:4] == ["api", v, "admin", "users"] and route[5] == "permissions" and method in ("PUT", "DELETE"):
        context = _admin(api, headers)
        user_id, permission = route[4], route[6]
        target = core.accounts.get_user(user_id)
        if not target:
            return api._response(404, {"error": "User not found"})
        actor = core.accounts.get_user(context["id"])
        target_keys = target.keys() if hasattr(target, "keys") else ()
        if "role" in target_keys and str(target["role"] or "").lower() == "owner" and str((actor or {}).get("role") or "").lower() != "owner":
            return api._response(403, {"error": "Only the owner can modify owner permissions"})
        if method == "PUT":
            allowed = body.get("allowed")
            if not isinstance(allowed, bool):
                return api._response(400, {"error": "allowed must be true or false"})
            try:
                core.permissions.set_user_permission(user_id, permission, allowed)
            except ValueError as exc:
                return api._response(400, {"error": str(exc)})
            return api._response(200, {"updated": True, "permission": permission, "allowed": allowed})
        try:
            core.permissions.clear_user_permission(user_id, permission)
        except ValueError as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {"updated": True, "permission": permission, "override": None})

    # ------------------------------------------------------------------
    # Admin settings & pricing
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "settings"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {
            "settings": core.shop_settings.snapshot(),
            "metadata": core.shop_settings.metadata(),
        })

    if route == ["api", v, "admin", "settings"] and method == "PUT":
        context = _admin(api, headers)
        key = str(body.get("key") or "")
        value = str(body.get("value") or "")
        if not key:
            raise ValueError("key is required")
        protected_keys = {"console_lock_enabled", "console_idle_timeout_minutes", "console_local_only"}
        actor = core.accounts.get_user(context["id"])
        if key in protected_keys and str((actor or {}).get("role") or "").lower() != "owner":
            return api._response(403, {"error": "Only the owner can change console security settings"})
        try:
            core.shop_settings.set_validated(key, value)
        except (KeyError, ValueError) as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {
            "key": key,
            "value": core.shop_settings.get(key),
            "metadata": core.shop_settings.metadata().get(key),
        })

    if route == ["api", v, "admin", "pricing", "estimate"] and method == "POST":
        _admin(api, headers)

        def _float(name, default=0.0):
            try:
                return float(body.get(name, default))
            except (TypeError, ValueError):
                raise ValueError("Invalid %s" % name)

        try:
            quantity = int(body.get("quantity", 1))
        except (TypeError, ValueError):
            raise ValueError("Invalid quantity")
        overhead = body.get("overhead_percent")
        result = core.pricing.estimate(
            estimated_minutes=_float("estimated_minutes"),
            estimated_filament_g=_float("estimated_filament_g"),
            quantity=quantity,
            rush=bool(body.get("rush", False)),
            setup_minutes=_float("setup_minutes"),
            post_process_minutes=_float("post_process_minutes"),
            qc_minutes=_float("qc_minutes"),
            overhead_percent=None if overhead is None else _float("overhead_percent"),
        )
        return api._response(200, result)

    if len(route) == 6 and route[:4] == ["api", v, "admin", "products"] and route[5] == "price-history" and method == "GET":
        _admin(api, headers)
        product_id = route[4]
        if not core.products.get(product_id):
            return api._response(404, {"error": "Product not found"})
        return api._response(200, {"history": _rows(core.price_history.product(product_id, _q_int(query, "limit", 100)))})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "variants"] and route[5] == "price-history" and method == "GET":
        _admin(api, headers)
        variant_id = route[4]
        with core.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM product_variants WHERE id=?", (variant_id,)).fetchone():
                return api._response(404, {"error": "Variant not found"})
        return api._response(200, {"history": _rows(core.price_history.variant(variant_id, _q_int(query, "limit", 100)))})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "quotes"] and route[5] == "price-snapshots" and method == "GET":
        _admin(api, headers)
        quote_id = route[4]
        with core.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM quotes WHERE id=?", (quote_id,)).fetchone():
                return api._response(404, {"error": "Quote not found"})
        return api._response(200, {"snapshots": _rows(core.price_history.quote_snapshots(quote_id, _q_int(query, "limit", 500)))})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "orders"] and route[5] == "price-snapshots" and method == "GET":
        _admin(api, headers)
        order_id = route[4]
        with core.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone():
                return api._response(404, {"error": "Order not found"})
        return api._response(200, {"items": _rows(core.price_history.order_items(order_id))})

    # ------------------------------------------------------------------
    # Admin AI
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "ai", "status"] and method == "GET":
        _admin(api, headers)
        return api._response(200, core.ai.status())

    if route == ["api", v, "admin", "ai", "chat"] and method == "POST":
        _admin(api, headers)
        try:
            return api._response(200, {"response": core.ai.chat(body.get("message", ""), body.get("context"))})
        except (TypeError, ValueError, RuntimeError) as exc:
            return api._response(400, {"error": str(exc)})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "ai", "products"] and route[5] == "marketing" and method == "POST":
        _admin(api, headers)
        product_id = route[4]
        try:
            return api._response(200, {"product_id": product_id, "response": core.ai.marketing_assistant(product_id)})
        except (ValueError, RuntimeError) as exc:
            return api._response(400, {"error": str(exc)})

    # ------------------------------------------------------------------
    # Admin marketing
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "marketing", "dashboard"] and method == "GET":
        _admin(api, headers)
        return api._response(200, core.marketing.dashboard())

    if route == ["api", v, "admin", "marketing", "providers"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {"providers": core.marketing.connection_status()})

    if route == ["api", v, "admin", "marketing", "channels"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {"channels": _rows(core.marketing.channels())})

    if len(route) == 6 and route[:5] == ["api", v, "admin", "marketing", "channels"] and method == "PUT":
        _admin(api, headers)
        data = dict(body or {})
        data["channel_id"] = route[5]
        try:
            row = core.marketing.save_channel(**data)
        except (TypeError, ValueError) as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {"channel": dict(row)})

    if route == ["api", v, "admin", "marketing", "channels"] and method == "POST":
        _admin(api, headers)
        try:
            row = core.marketing.save_channel(**dict(body or {}))
        except (TypeError, ValueError) as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {"channel": dict(row)})

    if route == ["api", v, "admin", "marketing", "campaigns"] and method == "GET":
        _admin(api, headers)
        status = _q(query, "status", None)
        return api._response(200, {"campaigns": _rows(core.marketing.campaigns(status))})

    if route == ["api", v, "admin", "marketing", "campaigns"] and method == "POST":
        _admin(api, headers)
        try:
            row = core.marketing.save_campaign(**dict(body or {}))
        except (TypeError, ValueError) as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {"campaign": dict(row)})

    if len(route) == 7 and route[:5] == ["api", v, "admin", "marketing", "products"] and route[6] == "variants" and method == "GET":
        _admin(api, headers)
        product_id = route[5]
        try:
            return api._response(200, {"product_id": product_id, "variants": core.marketing.generate_post_variants(product_id)})
        except ValueError as exc:
            return api._response(404, {"error": str(exc)})

    if route == ["api", v, "admin", "marketing", "posts"] and method == "GET":
        _admin(api, headers)
        status = _q(query, "status", None)
        return api._response(200, {"posts": _rows(core.marketing.posts(status, _q_int(query, "limit", 100)))})

    if route == ["api", v, "admin", "marketing", "posts"] and method == "POST":
        _admin(api, headers)
        try:
            row = core.marketing.create_post(**dict(body or {}))
        except (TypeError, ValueError) as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {"post": dict(row)})

    if len(route) == 7 and route[:5] == ["api", v, "admin", "marketing", "posts"] and route[6] == "approve" and method == "POST":
        _admin(api, headers)
        post_id = route[5]
        post = core.marketing.post(post_id)
        if not post:
            return api._response(404, {"error": "Post not found"})
        if not post[1]:
            return api._response(409, {"error": "Post has no channels"})
        with core.database.connect() as conn:
            conn.execute("UPDATE marketing_posts SET status='scheduled',updated_at=CURRENT_TIMESTAMP WHERE id=?", (post_id,))
            conn.execute("UPDATE marketing_post_channels SET status='scheduled' WHERE post_id=? AND status='draft'", (post_id,))
            conn.commit()
        return api._response(200, {"approved": True, "post_id": post_id})

    if route == ["api", v, "admin", "marketing", "posts", "queue-due"] and method == "POST":
        _admin(api, headers)
        return api._response(200, {"queued": core.marketing.queue_due_posts()})

    if len(route) == 6 and route[:5] == ["api", v, "admin", "marketing", "posts"] and method == "GET":
        _admin(api, headers)
        post_id = route[5]
        post = core.marketing.post(post_id)
        if not post:
            return api._response(404, {"error": "Post not found"})
        row, channels = post
        return api._response(200, {"post": dict(row), "channels": _rows(channels)})

    if route == ["api", v, "admin", "marketing", "sales"] and method == "GET":
        _admin(api, headers)
        days = max(1, min(_q_int(query, "days", 30), 3650))
        return api._response(200, {"days": days, "channels": core.marketing.sales_summary(days)})

    if route == ["api", v, "admin", "marketing", "sales", "external"] and method == "GET":
        _admin(api, headers)
        channel_id = _q(query, "channel_id", None)
        return api._response(200, {"sales": _rows(core.marketing.external_sales(channel_id, _q_int(query, "limit", 100)))})

    if route == ["api", v, "admin", "marketing", "sales", "external"] and method == "POST":
        _admin(api, headers)
        try:
            sale = core.marketing.import_external_sale(**dict(body or {}))
        except (TypeError, ValueError) as exc:
            return api._response(400, {"error": str(exc)})
        return api._response(200, {"sale": dict(sale)})

    # ------------------------------------------------------------------
    # Admin designs & QC
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "designs"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {"designs": _rows(core.design_vault.list(_q(query, "q")))})

    if len(route) == 5 and route[:4] == ["api", v, "admin", "designs"] and method == "GET":
        _admin(api, headers)
        design_id = route[4]
        design = core.design_vault.get(design_id)
        if not design:
            return api._response(404, {"error": "Design not found"})
        return api._response(200, {
            "design": dict(design),
            "versions": _rows(core.design_vault.versions(design_id)),
            "assets": _rows(core.design_vault.assets(design_id)),
            "model": core.design_vault.model_set_summary(design_id),
            "production_history": _rows(core.design_vault.production_history(design_id)),
        })

    if route == ["api", v, "admin", "qc"] and method == "GET":
        _admin(api, headers)
        return api._response(200, {"inspections": _rows(core.manufacturing.qc_list())})

    if len(route) == 5 and route[:4] == ["api", v, "admin", "qc"] and method == "GET":
        _admin(api, headers)
        inspection_id = route[4]
        rows = [dict(row) for row in core.manufacturing.qc_list() if str(row["id"]) == str(inspection_id)]
        if not rows:
            return api._response(404, {"error": "QC inspection not found"})
        item = rows[0]
        try:
            item["checklist"] = json.loads(item.get("checklist_json") or "[]")
        except Exception:
            item["checklist"] = []
        return api._response(200, {"inspection": item})

    if len(route) == 5 and route[:4] == ["api", v, "admin", "qc"] and method == "PUT":
        _admin(api, headers)
        inspection_id = route[4]
        try:
            core.manufacturing.qc_update(
                inspection_id, body.get("items") or [],
                str(body.get("notes") or ""), str(body.get("status") or "pending"),
            )
        except KeyError as exc:
            return api._response(404, {"error": str(exc)})
        except ValueError as exc:
            return api._response(409, {"error": str(exc)})
        rows = [dict(row) for row in core.manufacturing.qc_list() if str(row["id"]) == str(inspection_id)]
        return api._response(200, {"inspection": rows[0] if rows else None})

    if route == ["api", v, "admin", "qc", "reconcile"] and method == "POST":
        _admin(api, headers)
        return api._response(200, {"created": core.manufacturing.reconcile_qc()})

    # ------------------------------------------------------------------
    # Admin design proofs (mirror fabos_core/services/design_proofs_api.py)
    # ------------------------------------------------------------------
    if len(route) == 6 and route[:4] == ["api", v, "admin", "quotes"] and route[5] == "proofs" and method == "GET":
        _admin(api, headers)
        return api._response(200, {"proofs": _rows(core.design_proofs.list_for_admin(quote_id=route[4]))})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "quotes"] and route[5] == "proofs" and method == "POST":
        _admin(api, headers)
        quote_id = route[4]
        notes = str(body.get("notes") or "")
        if len(notes) > 4000:
            raise ValueError("Notes must be at most 4000 characters.")
        try:
            proof = core.design_proofs.create(quote_id, notes=notes, status="sent" if body.get("send") else "draft")
        except KeyError as exc:
            return api._response(404, {"error": str(exc)})
        except ValueError as exc:
            return api._response(409, {"error": str(exc)})
        return api._response(200, {"proof": core.design_proofs._admin(proof)})

    if len(route) == 7 and route[:4] == ["api", v, "admin", "quotes"] and route[5] == "proofs" and route[6] == "upload" and method == "POST":
        _admin(api, headers)
        quote_id = route[4]
        fields, files = _parse_multipart_body(headers, raw_body)
        if "file" not in files:
            raise ValueError("A proof file is required")
        filename, file_bytes = files["file"]
        from fabos_core.services.design_proofs_api import ALLOWED_PROOF_EXTENSIONS, MAX_PROOF_UPLOAD_BYTES
        filename = Path(filename or "").name
        extension = Path(filename).suffix.lower()
        if not filename or extension not in ALLOWED_PROOF_EXTENSIONS:
            return api._response(415, {"error": "Unsupported proof file type"})
        if len(file_bytes) > MAX_PROOF_UPLOAD_BYTES:
            return api._response(413, {"error": "Proof file must be 25 MB or smaller"})
        notes = str(fields.get("notes", "") or "")
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                temp_path = tmp.name
                tmp.write(file_bytes)
            with core.database.connect() as conn:
                link = conn.execute("SELECT design_id FROM quote_designs WHERE quote_id=?", (quote_id,)).fetchone()
            if not link:
                return api._response(404, {"error": "No customer design is attached to this quote."})
            core.design_vault.new_version(link["design_id"])
            core.design_vault.import_file(link["design_id"], temp_path, make_primary=extension in {".stl", ".3mf", ".step", ".stp"})
            proof = core.design_proofs.create(quote_id, notes=notes, status="sent")
            return api._response(200, {
                "proof": core.design_proofs._admin(proof),
                "file": {"name": filename, "bytes": len(file_bytes)},
            })
        except (KeyError, ValueError) as exc:
            return api._response(409, {"error": str(exc)})
        except Exception:
            return api._response(500, {"error": "The proof could not be stored"})
        finally:
            try:
                if temp_path:
                    os.unlink(temp_path)
            except OSError:
                pass

    if len(route) == 6 and route[:4] == ["api", v, "admin", "proofs"] and route[5] == "send" and method == "POST":
        _admin(api, headers)
        proof_id = route[4]
        comment = str(body.get("comment") or "")
        if len(comment) > 4000:
            raise ValueError("Comment must be at most 4000 characters.")
        try:
            proof = core.design_proofs.send(proof_id, comment if comment else None)
        except KeyError as exc:
            return api._response(404, {"error": str(exc)})
        except ValueError as exc:
            return api._response(409, {"error": str(exc)})
        return api._response(200, {"proof": core.design_proofs._admin(proof)})

    # ------------------------------------------------------------------
    # Admin physical payment + custom-quote promotion
    # ------------------------------------------------------------------
    if route == ["api", v, "admin", "payments", "physical"] and method == "POST":
        _admin(api, headers)
        from fabos_core.services.payments import PaymentProviderError, PaymentProviderNotConfigured
        try:
            payment = core.payments.record_physical_payment(
                str(body.get("order_id") or ""), str(body.get("source_id") or ""),
                str(body.get("provider") or "square"),
            )
        except KeyError as exc:
            return api._response(404, {"error": str(exc)})
        except PaymentProviderNotConfigured as exc:
            return api._response(503, {"error": str(exc)})
        except PaymentProviderError as exc:
            return api._response(502, {"error": str(exc)})
        except ValueError as exc:
            return api._response(409, {"error": str(exc)})
        return api._response(200, {"payment": payment})

    if len(route) == 6 and route[:4] == ["api", v, "admin", "quote-requests"] and route[5] == "product" and method == "POST":
        _admin(api, headers)
        quote_id = route[4]
        try:
            result = core.custom_product_workflow.promote_quote_design(quote_id, dict(body or {}))
        except KeyError as exc:
            return api._response(404, {"error": str(exc)})
        except ValueError as exc:
            return api._response(409, {"error": str(exc)})
        return api._response(200, result)

    return None


def _cleanup_quote_request(core, quote_id, design_id):
    """Remove a partially created quote request (mirrors the FastAPI route)."""
    if not quote_id:
        return
    try:
        with core.database.connect() as conn:
            conn.execute("DELETE FROM quote_designs WHERE quote_id=?", (quote_id,))
            if design_id:
                try:
                    core.design_vault.remove_design(design_id)
                except Exception:
                    conn.execute("DELETE FROM designs WHERE id=?", (design_id,))
            conn.commit()
    except Exception:
        pass
