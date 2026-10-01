"""Parametric CAD generation and verification for FabOS.

The first implementation uses a constrained design specification instead of executing
arbitrary AI-generated Python. CadQuery is optional at import time but required to
actually export CAD artifacts.
"""
import json
import re
import uuid
from pathlib import Path

try:
    import cadquery as cq
except Exception:
    cq = None


class CadGenerationError(ValueError):
    pass


class CadGenerationService:
    SHAPES = {"box", "plate", "cylinder", "ring", "bracket", "mounting_plate"}

    def __init__(self, settings=None, database=None, ai=None, design_vault=None):
        self.settings = settings
        self.database = database
        self.ai = ai
        self.design_vault = design_vault

    @property
    def root(self):
        data_dir = Path(getattr(self.settings, "data_dir", Path.cwd() / "data"))
        path = data_dir / "Generated CAD"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def capabilities(self):
        configured = False
        if self.ai:
            try:
                configured = bool(self.ai.status().get("configured"))
            except Exception:
                configured = False
        return {"enabled": cq is not None, "engine": "cadquery" if cq is not None else None,
                "step": cq is not None, "stl": cq is not None,
                "shapes": sorted(self.SHAPES), "ai_interpretation": configured}

    @staticmethod
    def _number(value, name, minimum=0.01, maximum=2000.0):
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise CadGenerationError("%s must be a number" % name)
        if result < minimum or result > maximum:
            raise CadGenerationError("%s must be between %s and %s mm" % (name, minimum, maximum))
        return result

    def normalize_spec(self, spec):
        if not isinstance(spec, dict):
            raise CadGenerationError("Design specification must be an object")
        shape = str(spec.get("shape") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if shape not in self.SHAPES:
            raise CadGenerationError("Unsupported shape. Choose one of: %s" % ", ".join(sorted(self.SHAPES)))
        dimensions = spec.get("dimensions") or {}
        if not isinstance(dimensions, dict):
            raise CadGenerationError("dimensions must be an object")
        result = {"shape": shape, "dimensions": {}, "holes": [], "metadata": dict(spec.get("metadata") or {})}
        if shape == "cylinder":
            result["dimensions"]["diameter"] = self._number(dimensions.get("diameter", dimensions.get("width", 50)), "diameter")
            result["dimensions"]["height"] = self._number(dimensions.get("height", 10), "height")
        elif shape == "ring":
            outer = self._number(dimensions.get("outer_diameter", dimensions.get("diameter", 50)), "outer_diameter")
            inner = self._number(dimensions.get("inner_diameter", 25), "inner_diameter")
            if inner >= outer:
                raise CadGenerationError("inner_diameter must be smaller than outer_diameter")
            result["dimensions"].update({"outer_diameter": outer, "inner_diameter": inner,
                                         "height": self._number(dimensions.get("height", 5), "height")})
        else:
            result["dimensions"] = {
                "width": self._number(dimensions.get("width", 100), "width"),
                "depth": self._number(dimensions.get("depth", 60), "depth"),
                "height": self._number(dimensions.get("height", 5), "height"),
            }
        holes = spec.get("holes") or []
        if not isinstance(holes, list):
            raise CadGenerationError("holes must be an array")
        for hole in holes[:32]:
            if not isinstance(hole, dict):
                raise CadGenerationError("Each hole must be an object")
            result["holes"].append({
                "diameter": self._number(hole.get("diameter"), "hole diameter"),
                "x": self._number(hole.get("x", 0), "hole x", -2000, 2000),
                "y": self._number(hole.get("y", 0), "hole y", -2000, 2000),
            })
        if shape == "mounting_plate" and not result["holes"]:
            w, d = result["dimensions"]["width"], result["dimensions"]["depth"]
            inset = min(w, d) * 0.125
            diameter = min(5.0, min(w, d) * 0.08)
            result["holes"] = [
                {"diameter": diameter, "x": -w / 2 + inset, "y": -d / 2 + inset},
                {"diameter": diameter, "x": w / 2 - inset, "y": -d / 2 + inset},
                {"diameter": diameter, "x": -w / 2 + inset, "y": d / 2 - inset},
                {"diameter": diameter, "x": w / 2 - inset, "y": d / 2 - inset},
            ]
        for hole in result["holes"]:
            if shape not in {"cylinder", "ring"}:
                half_r = hole["diameter"] / 2
                if abs(hole["x"]) + half_r > result["dimensions"]["width"] / 2:
                    raise CadGenerationError("hole x or radius is outside the part")
                if abs(hole["y"]) + half_r > result["dimensions"]["depth"] / 2:
                    raise CadGenerationError("hole y or radius is outside the part")
        return result

    def parse_prompt(self, prompt):
        text = str(prompt or "").strip()
        if not text:
            raise CadGenerationError("A design prompt is required")
        lowered = text.lower()
        if "mounting plate" in lowered:
            shape = "mounting_plate"
        elif "bracket" in lowered:
            shape = "bracket"
        elif "ring" in lowered or "washer" in lowered:
            shape = "ring"
        elif "cylinder" in lowered or "round post" in lowered:
            shape = "cylinder"
        elif "plate" in lowered or "flat" in lowered:
            shape = "plate"
        else:
            shape = "box"
        if "x" in lowered or "×" in lowered:
            nums = re.findall(r"\d+(?:\.\d+)?", lowered)
            dims = [float(x) for x in nums[:3]]
        else:
            dims = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", lowered)[:3]]
        while len(dims) < 3:
            dims.append([100.0, 60.0, 5.0][len(dims)])
        if shape == "cylinder":
            match = re.search(r"(\d+(?:\.\d+)?)\s*mm?\s*(?:diameter|dia)", lowered)
            spec = {"shape": shape, "dimensions": {"diameter": float(match.group(1)) if match else dims[0], "height": dims[-1]}}
        elif shape == "ring":
            spec = {"shape": shape, "dimensions": {"outer_diameter": dims[0], "inner_diameter": dims[1] if dims[1] < dims[0] else dims[0] / 2, "height": dims[2]}}
        else:
            spec = {"shape": shape, "dimensions": {"width": dims[0], "depth": dims[1], "height": dims[2]}}
            count = re.search(r"(\d+)\s*(?:mounting\s+)?holes?", lowered)
            dia = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*(?:diameter|dia)", lowered)
            if count and int(count.group(1)) == 4:
                w, d = dims[0], dims[1]
                inset = min(w, d) * 0.125
                diameter = float(dia.group(1)) if dia else 5.0
                spec["holes"] = [{"diameter": diameter, "x": sx * (w / 2 - inset), "y": sy * (d / 2 - inset)}
                                 for sx, sy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]]
        return self.normalize_spec(spec)

    def interpret_prompt(self, prompt):
        if self.ai and hasattr(self.ai, "design_spec_from_prompt"):
            try:
                result = self.ai.design_spec_from_prompt(prompt)
                if result:
                    return self.normalize_spec(result)
            except Exception:
                pass
        return self.parse_prompt(prompt)

    def _cadquery_model(self, spec):
        if cq is None:
            raise CadGenerationError("CadQuery is required for model generation.")
        d, shape = spec["dimensions"], spec["shape"]
        if shape in {"box", "plate", "mounting_plate"}:
            model = cq.Workplane("XY").box(d["width"], d["depth"], d["height"], centered=(True, True, False))
        elif shape == "cylinder":
            model = cq.Workplane("XY").circle(d["diameter"] / 2).extrude(d["height"])
        elif shape == "ring":
            model = cq.Workplane("XY").circle(d["outer_diameter"] / 2).circle(d["inner_diameter"] / 2).extrude(d["height"])
        elif shape == "bracket":
            base = cq.Workplane("XY").box(d["width"], d["depth"], d["height"], centered=(True, True, False))
            wall = cq.Workplane("XZ").box(d["width"], d["height"], d["depth"], centered=(True, False, False)).translate((0, d["depth"] / 2 - d["height"] / 2, d["height"]))
            model = base.union(wall)
        else:
            raise CadGenerationError("Unsupported shape")
        for hole in spec["holes"]:
            cutter = cq.Workplane("XY").center(hole["x"], hole["y"]).circle(hole["diameter"] / 2).extrude(d.get("height", 5) + 2)
            model = model.cut(cutter)
        return model

    def _verify(self, model, spec):
        shape = model.val()
        bb = shape.BoundingBox()
        actual = {"width_mm": round(bb.xlen, 4), "depth_mm": round(bb.ylen, 4), "height_mm": round(bb.zlen, 4)}
        d = spec["dimensions"]
        expected = {"width_mm": round(d.get("width", d.get("outer_diameter", d.get("diameter"))), 4),
                    "depth_mm": round(d.get("depth", d.get("outer_diameter", d.get("diameter"))), 4),
                    "height_mm": round(d["height"], 4)}
        checks = []
        for key in expected:
            delta = abs(actual[key] - expected[key])
            checks.append({"measurement": key, "expected_mm": expected[key], "actual_mm": actual[key],
                           "delta_mm": round(delta, 5), "pass": delta <= 0.01})

        # Bounding-box checks are necessary but not sufficient. For every requested
        # hole, inspect the resulting solid's cylindrical faces so we can verify the
        # modeled diameter and approximate center rather than merely echoing the spec.
        hole_checks = []
        if spec.get("holes"):
            circles = []
            for face in shape.Faces():
                try:
                    if face.geomType() == "CYLINDER":
                        circles.append(face)
                except Exception:
                    continue
            for requested in spec["holes"]:
                target_r = requested["diameter"] / 2.0
                candidates = []
                for face in circles:
                    try:
                        radius = float(face._geomAdaptor().Radius())
                        center = face.Center()
                        radius_error = abs(radius - target_r)
                        distance = ((float(center.x) - requested["x"]) ** 2 +
                                    (float(center.y) - requested["y"]) ** 2) ** 0.5
                        candidates.append((radius_error, distance, float(center.x), float(center.y), radius))
                    except Exception:
                        continue
                matching = [item for item in candidates if item[0] <= 0.01]
                best = min(matching or candidates, key=lambda item: (item[1], item[0])) if (matching or candidates) else None
                diameter_ok = bool(best and best[0] <= 0.01)
                location_ok = False
                if best:
                    location_ok = abs(best[2] - requested["x"]) <= 0.05 and abs(best[3] - requested["y"]) <= 0.05
                hole_checks.append({
                    "requested_diameter_mm": round(requested["diameter"], 4),
                    "actual_diameter_mm": round(best[4] * 2, 4) if best else None,
                    "requested_x_mm": round(requested["x"], 4),
                    "requested_y_mm": round(requested["y"], 4),
                    "actual_x_mm": round(best[2], 4) if best else None,
                    "actual_y_mm": round(best[3], 4) if best else None,
                    "diameter_pass": diameter_ok,
                    "location_pass": location_ok,
                    "pass": diameter_ok and location_ok,
                })

        checks.append({"measurement": "hole_features", "requested": len(spec.get("holes", [])),
                       "actual": len(hole_checks), "pass": len(hole_checks) == len(spec.get("holes", [])) and
                       all(item["pass"] for item in hole_checks)})
        checks.append({"measurement": "watertight", "actual": bool(shape.isValid()), "pass": bool(shape.isValid())})
        checks.append({"measurement": "solid_valid", "actual": bool(shape.isValid()), "pass": bool(shape.isValid())})
        return {"passed": all(x["pass"] for x in checks), "checks": checks, "holes": hole_checks}

    def _save_job(self, job_id, owner_id, status, prompt, spec=None, verification=None, artifacts=None, error=None):
        if self.database is None:
            return
        try:
            with self.database.connect() as conn:
                conn.execute(
                    """INSERT INTO cad_generation_jobs
                       (id,user_id,status,prompt,spec_json,verification_json,artifacts_json,error)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         status=excluded.status,prompt=excluded.prompt,spec_json=excluded.spec_json,
                         verification_json=excluded.verification_json,artifacts_json=excluded.artifacts_json,
                         error=excluded.error,updated_at=CURRENT_TIMESTAMP""",
                    (job_id, str(owner_id) if owner_id is not None else None, status,
                     str(prompt or "")[:12000], json.dumps(spec or {}, default=str),
                     json.dumps(verification or {}, default=str),
                     json.dumps(artifacts or [], default=str), error),
                )
                conn.commit()
        except Exception:
            return

    def _job_payload(self, row):
        data = dict(row) if hasattr(row, "keys") else dict(row)
        for field in ("spec_json", "verification_json", "artifacts_json"):
            raw = data.get(field)
            try:
                data[field[:-5] if field.endswith("_json") else field] = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                data[field[:-5] if field.endswith("_json") else field] = None
            data.pop(field, None)
        return data

    def list_jobs(self, owner_id, limit=50):
        if not owner_id:
            return []
        limit = max(1, min(int(limit or 50), 100))
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id,owner_id,status,prompt,spec_json,verification_json,artifacts_json,error,created_at,updated_at "
                "FROM cad_generation_jobs WHERE owner_id=? ORDER BY created_at DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
        return [self._job_payload(row) for row in rows]

    def get_job(self, job_id, owner_id=None):
        if self.database is None:
            return None
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM cad_generation_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        if owner_id is not None and str(row["user_id"] or "") != str(owner_id):
            return None
        return self._job_payload(row)

    def preflight(self, spec=None, prompt=None, printer_id=None):
        spec = self.interpret_prompt(prompt) if spec is None else self.normalize_spec(spec)
        model = self._cadquery_model(spec)
        verification = self._verify(model, spec)
        result = {"geometry": verification, "printer": None, "printable": verification["passed"], "warnings": []}
        if printer_id and self.database is not None:
            with self.database.connect() as conn:
                printer = conn.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
            if not printer:
                raise CadGenerationError("Printer not found")
            bb = model.val().BoundingBox()
            dims = (float(bb.xlen), float(bb.ylen), float(bb.zlen))
            limits = []
            for key in ("build_x_mm", "build_y_mm", "build_z_mm"):
                try:
                    limits.append(float(printer[key]))
                except (TypeError, ValueError):
                    limits.append(0.0)
            known = all(x > 0 for x in limits)
            fits = ((dims[0] <= limits[0] and dims[1] <= limits[1] and dims[2] <= limits[2]) or
                    (dims[1] <= limits[0] and dims[0] <= limits[1] and dims[2] <= limits[2])) if known else True
            result["printer"] = {"id": printer["id"], "name": printer["name"],
                                 "build_volume_mm": {"x": limits[0], "y": limits[1], "z": limits[2]},
                                 "model_mm": {"x": round(dims[0], 4), "y": round(dims[1], 4), "z": round(dims[2], 4)},
                                 "fits_build_volume": fits}
            result["printable"] = result["printable"] and fits
            if not fits:
                result["warnings"].append("Model exceeds the selected printer build volume.")
            if not known:
                result["warnings"].append("Printer build volume is not configured; build-volume check was skipped.")
        return result

    def attach_to_quote(self, job_id, quote_id, user_id):
        """Attach a completed customer CAD job to the customer's quote Design Vault."""
        job = self.get_job(job_id, owner_id=user_id)
        if not job:
            raise CadGenerationError("CAD job not found")
        if job.get("status") != "completed":
            raise CadGenerationError("Only completed CAD jobs can be attached to a quote")
        with self.database.connect() as conn:
            owner = conn.execute(
                "SELECT customer_id FROM customer_accounts WHERE user_id=?",
                (user_id,),
            ).fetchone()
            quote = conn.execute(
                "SELECT customer_id,quote_number FROM quotes WHERE id=?",
                (quote_id,),
            ).fetchone()
            if not owner or not quote or str(owner["customer_id"]) != str(quote["customer_id"]):
                raise CadGenerationError("Quote access denied")
            existing = conn.execute(
                "SELECT design_id FROM quote_designs WHERE quote_id=?",
                (quote_id,),
            ).fetchone()
            if existing:
                return {"quote_id": quote_id, "design_id": existing["design_id"], "attached": False}
            conn.execute(
                "CREATE TABLE IF NOT EXISTS quote_designs("
                "quote_id TEXT PRIMARY KEY REFERENCES quotes(id) ON DELETE CASCADE,"
                "design_id TEXT NOT NULL UNIQUE REFERENCES designs(id) ON DELETE CASCADE,"
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            design_id = str(uuid.uuid4())
            version_id = str(uuid.uuid4())
            name = "AI CAD " + str(quote["quote_number"])
            conn.execute(
                "INSERT INTO designs(id,product_id,name,current_version,notes) VALUES(?,?,?,?,?)",
                (design_id, None, name, 1, "AI-generated CAD job %s" % job_id),
            )
            conn.execute(
                "INSERT INTO design_versions(id,design_id,version,label,notes) VALUES(?,?,?,?,?)",
                (version_id, design_id, 1, "AI Generated", "Generated from customer CAD request"),
            )
            conn.execute(
                "INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)",
                (quote_id, design_id),
            )
            conn.commit()
        imported = []
        try:
            for artifact in job.get("artifacts") or []:
                path = Path(str(artifact.get("path") or ""))
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".stl", ".step", ".stp", ".3mf"}:
                    continue
                if self.design_vault:
                    self.design_vault.import_file(design_id, path, make_primary=not imported)
                imported.append(path.name)
            if not imported:
                raise CadGenerationError("Completed CAD job has no usable artifacts")
        except Exception:
            with self.database.connect() as conn:
                conn.execute("DELETE FROM quote_designs WHERE quote_id=?", (quote_id,))
                conn.execute("DELETE FROM designs WHERE id=?", (design_id,))
                conn.commit()
            raise
        return {"quote_id": quote_id, "design_id": design_id, "attached": True, "artifacts": imported}

    def revise(self, job_id, instruction, owner_id=None, output_formats=None):
        """Apply a natural-language revision to an existing parametric CAD job."""
        if not str(instruction or "").strip():
            raise CadGenerationError("A revision instruction is required")
        existing = self.get_job(job_id, owner_id=owner_id)
        if not existing:
            raise CadGenerationError("CAD job not found")
        current = existing.get("spec") or {}
        if self.ai and hasattr(self.ai, "design_spec_from_prompt"):
            prompt = (
                "Revise this existing CAD specification without changing unspecified features. "
                "Return the complete replacement JSON specification. Existing specification: "
                + json.dumps(current, default=str)
                + "\nRequested revision: " + str(instruction).strip()[:8000]
            )
            try:
                candidate = self.ai.design_spec_from_prompt(prompt)
                spec = self.normalize_spec(candidate)
            except Exception:
                spec = self._apply_simple_revision(current, instruction)
        else:
            spec = self._apply_simple_revision(current, instruction)
        return self.generate(
            spec=spec,
            prompt="Revision of %s: %s" % (job_id, str(instruction).strip()[:8000]),
            output_formats=output_formats or ["stl", "step"],
            owner_id=owner_id,
        )

    def _apply_simple_revision(self, original, instruction):
        spec = json.loads(json.dumps(original, default=str))
        text = str(instruction).lower()
        dimensions = spec.setdefault("dimensions", {})
        replacements = {
            "width": r"(?:width|wide)\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)\s*mm",
            "depth": r"(?:depth|deep)\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)\s*mm",
            "height": r"(?:height|tall|thick|thickness)\s*(?:is\s*)?(?:to|=|of)?\s*(\d+(?:\.\d+)?)\s*mm",
            "diameter": r"(?:diameter|dia)\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)\s*mm",
            "outer_diameter": r"(?:outer\s+diameter)\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)\s*mm",
            "inner_diameter": r"(?:inner\s+diameter)\s*(?:to|=|of)?\s*(\d+(?:\.\d+)?)\s*mm",
        }
        changed = False
        for key, pattern in replacements.items():
            match = re.search(pattern, text)
            if match:
                dimensions[key] = float(match.group(1))
                changed = True
        hole_match = re.search(r"(?:hole|holes).{0,40}(\d+(?:\.\d+)?)\s*mm", text)
        if hole_match and spec.get("holes"):
            diameter = float(hole_match.group(1))
            for hole in spec["holes"]:
                hole["diameter"] = diameter
            changed = True
        if not changed:
            raise CadGenerationError("The revision could not be mapped to a dimensional change. Please specify a dimension in millimeters.")
        return self.normalize_spec(spec)

    def generate(self, spec=None, prompt=None, output_formats=None, owner_id=None):
        job_id = str(uuid.uuid4())
        try:
            spec = self.interpret_prompt(prompt) if spec is None else self.normalize_spec(spec)
            self._save_job(job_id, owner_id, "generating", prompt, spec)
            model = self._cadquery_model(spec)
            verification = self._verify(model, spec)
            if not verification["passed"]:
                raise CadGenerationError("Generated geometry failed dimensional verification")
            folder = self.root / job_id
            folder.mkdir(parents=True, exist_ok=True)
            formats = [str(x).lower() for x in (output_formats or ["stl", "step"]) if str(x).lower() in {"stl", "step"}]
            (folder / "metadata.json").write_text(json.dumps({"owner_id": str(owner_id or ""), "spec": spec}, default=str), encoding="utf-8")
            artifacts = []
            for fmt in (formats or ["stl"]):
                target = folder / ("model." + fmt)
                if fmt == "stl":
                    cq.exporters.export(model, str(target), exportType="STL", tolerance=0.01, angularTolerance=0.1)
                else:
                    cq.exporters.export(model, str(target), exportType="STEP")
                artifacts.append({"format": fmt, "path": str(target), "bytes": target.stat().st_size})
            self._save_job(job_id, owner_id, "completed", prompt, spec, verification, artifacts)
            return {"job_id": job_id, "spec": spec, "verification": verification, "artifacts": artifacts,
                    "capabilities": self.capabilities()}
        except Exception as exc:
            self._save_job(job_id, owner_id, "failed", prompt, locals().get("spec"), locals().get("verification"),
                           locals().get("artifacts"), str(exc)[:2000])
            raise
