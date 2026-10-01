"""Parametric CAD generation and verification for FabOS.

The first implementation uses a constrained design specification instead of executing
arbitrary AI-generated Python. CadQuery is optional at import time but required to
actually export CAD artifacts.
"""
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

    def __init__(self, settings=None, database=None, ai=None):
        self.settings = settings
        self.database = database
        self.ai = ai

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
                if hole["x"] < -result["dimensions"]["width"] / 2 or hole["x"] > result["dimensions"]["width"] / 2:
                    raise CadGenerationError("hole x is outside the part")
                if hole["y"] < -result["dimensions"]["depth"] / 2 or hole["y"] > result["dimensions"]["depth"] / 2:
                    raise CadGenerationError("hole y is outside the part")
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
        bb = model.val().BoundingBox()
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
        return {"passed": all(x["pass"] for x in checks), "checks": checks}

    def generate(self, spec=None, prompt=None, output_formats=None):
        spec = self.interpret_prompt(prompt) if spec is None else self.normalize_spec(spec)
        model = self._cadquery_model(spec)
        verification = self._verify(model, spec)
        if not verification["passed"]:
            raise CadGenerationError("Generated geometry failed dimensional verification")
        job_id = str(uuid.uuid4())
        folder = self.root / job_id
        folder.mkdir(parents=True, exist_ok=True)
        formats = [str(x).lower() for x in (output_formats or ["stl", "step"]) if str(x).lower() in {"stl", "step"}]
        artifacts = []
        for fmt in (formats or ["stl"]):
            target = folder / ("model." + fmt)
            if fmt == "stl":
                cq.exporters.export(model, str(target), exportType="STL", tolerance=0.01, angularTolerance=0.1)
            else:
                cq.exporters.export(model, str(target), exportType="STEP")
            artifacts.append({"format": fmt, "path": str(target), "bytes": target.stat().st_size})
        return {"job_id": job_id, "spec": spec, "verification": verification, "artifacts": artifacts,
                "capabilities": self.capabilities()}
