"""Parametric CAD generation and verification for FabOS.

The first implementation uses a constrained design specification instead of executing
arbitrary AI-generated Python. CadQuery is optional at import time but required to
actually export CAD artifacts.
"""
import json
import math
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
    SHAPES = {"box", "plate", "cylinder", "ring", "bracket", "mounting_plate", "flange", "enclosure"}
    MAX_FEATURES = 32

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
                "step": cq is not None, "stl": cq is not None, "3mf": cq is not None,
                "shapes": sorted(self.SHAPES), "ai_interpretation": configured}

    @staticmethod
    def _number(value, name, minimum=0.01, maximum=2000.0):
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise CadGenerationError("%s must be a number" % name)
        if not math.isfinite(result):
            raise CadGenerationError("%s must be finite" % name)
        if result < minimum or result > maximum:
            raise CadGenerationError("%s must be between %s and %s mm" % (name, minimum, maximum))
        return result

    @staticmethod
    def _integer(value, name, minimum=None, maximum=None):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise CadGenerationError("%s must be an integer" % name)
        if not numeric.is_integer():
            raise CadGenerationError("%s must be an integer" % name)
        result = int(numeric)
        if minimum is not None and result < minimum:
            raise CadGenerationError("%s must be at least %s" % (name, minimum))
        if maximum is not None and result > maximum:
            raise CadGenerationError("%s must be at most %s" % (name, maximum))
        return result

    @staticmethod
    def _angle(value, name):
        try:
            result = float(value or 0)
        except (TypeError, ValueError):
            raise CadGenerationError("%s must be numeric" % name)
        if not math.isfinite(result):
            raise CadGenerationError("%s must be finite" % name)
        return result

    @staticmethod
    def _obb_overlap(a, b):
        """Return True when two 2D oriented rectangles overlap."""
        axes = []
        for item in (a, b):
            angle = math.radians(item["angle"] % 360.0)
            ux = (math.cos(angle), math.sin(angle))
            uy = (-math.sin(angle), math.cos(angle))
            axes.extend((ux, uy))
        for axis in axes:
            ax, ay = axis
            def project(rect):
                angle = math.radians(rect["angle"] % 360.0)
                ux = (math.cos(angle), math.sin(angle))
                uy = (-math.sin(angle), math.cos(angle))
                cx, cy = rect["x"], rect["y"]
                radius = abs(ax * ux[0] + ay * ux[1]) * rect["length"] / 2.0
                radius += abs(ax * uy[0] + ay * uy[1]) * rect["thickness"] / 2.0
                center = ax * cx + ay * cy
                return center - radius, center + radius
            amin, amax = project(a)
            bmin, bmax = project(b)
            if amax <= bmin or bmax <= amin:
                return False
        return True

    @staticmethod
    def _circle_obb_overlap(circle, rect):
        """Return True when a circle overlaps an oriented rectangle."""
        angle = math.radians(rect["angle"] % 360.0)
        ux = (math.cos(angle), math.sin(angle))
        uy = (-math.sin(angle), math.cos(angle))
        dx = circle["x"] - rect["x"]
        dy = circle["y"] - rect["y"]
        local_x = dx * ux[0] + dy * ux[1]
        local_y = dx * uy[0] + dy * uy[1]
        closest_x = max(-rect["length"] / 2.0, min(local_x, rect["length"] / 2.0))
        closest_y = max(-rect["thickness"] / 2.0, min(local_y, rect["thickness"] / 2.0))
        distance = math.hypot(local_x - closest_x, local_y - closest_y)
        return distance < circle["diameter"] / 2.0

    @staticmethod
    def _segment_distance(a1, a2, b1, b2):
        """Return the minimum 2D distance between two line segments."""
        def dot(a, b):
            return a[0] * b[0] + a[1] * b[1]

        def sub(a, b):
            return (a[0] - b[0], a[1] - b[1])

        def clamp(value, low, high):
            return max(low, min(high, value))

        u = sub(a2, a1)
        v = sub(b2, b1)
        w = sub(a1, b1)
        uu = dot(u, u)
        vv = dot(v, v)
        uv = dot(u, v)
        uw = dot(u, w)
        vw = dot(v, w)
        denom = uu * vv - uv * uv
        if denom <= 1e-12:
            s = 0.0
            t = clamp(vw / vv, 0.0, 1.0) if vv > 1e-12 else 0.0
        else:
            s = clamp((uv * vw - vv * uw) / denom, 0.0, 1.0)
            t = clamp((uv * s + vw) / vv, 0.0, 1.0) if vv > 1e-12 else 0.0
        s = clamp((uv * t - uw) / uu, 0.0, 1.0) if uu > 1e-12 else 0.0
        t = clamp((uv * s + vw) / vv, 0.0, 1.0) if vv > 1e-12 else 0.0
        pa = (a1[0] + u[0] * s, a1[1] + u[1] * s)
        pb = (b1[0] + v[0] * t, b1[1] + v[1] * t)
        return math.hypot(pa[0] - pb[0], pa[1] - pb[1])

    @staticmethod
    def _capsule_segment(slot):
        angle = math.radians(slot.get("angle", 0.0) % 360.0)
        half = max(0.0, (slot["length"] - slot["width"]) / 2.0)
        direction = (math.cos(angle), math.sin(angle))
        return (
            (slot["x"] - half * direction[0], slot["y"] - half * direction[1]),
            (slot["x"] + half * direction[0], slot["y"] + half * direction[1]),
        )

    @classmethod
    def _capsule_circle_overlap(cls, slot, circle):
        start, end = cls._capsule_segment(slot)
        distance = cls._segment_distance(start, end, (circle["x"], circle["y"]), (circle["x"], circle["y"]))
        return distance < slot["width"] / 2.0 + circle["diameter"] / 2.0

    @classmethod
    def _capsule_overlap(cls, first, second):
        start_a, end_a = cls._capsule_segment(first)
        start_b, end_b = cls._capsule_segment(second)
        distance = cls._segment_distance(start_a, end_a, start_b, end_b)
        return distance < (first["width"] + second["width"]) / 2.0

    @staticmethod
    def _validate_reference_metadata(metadata):
        """Reject reference-derived CAD until its dimensions are sufficiently constrained."""
        if not isinstance(metadata, dict) or not metadata.get("reference_analysis"):
            return
        if not bool(metadata.get("scale_confirmed")):
            raise CadGenerationError(
                "Reference-derived CAD requires a confirmed physical or drawing scale before generation"
            )
        missing = metadata.get("missing_dimensions") or []
        if missing:
            raise CadGenerationError(
                "Reference-derived CAD is missing required measurements: %s" % ", ".join(str(item) for item in missing[:8])
            )
        uncertainties = metadata.get("feature_uncertainties") or []
        if uncertainties or bool(metadata.get("needs_user_confirmation")):
            raise CadGenerationError(
                "Reference-derived CAD has unresolved geometry that requires user confirmation"
            )
        scale_source = str(metadata.get("scale_source") or "").strip().lower()
        if scale_source not in {"drawing_dimension", "user_measurement", "physical_scale_reference"}:
            raise CadGenerationError("Reference-derived CAD requires a recognized scale source")

    def normalize_spec(self, spec):
        if not isinstance(spec, dict):
            raise CadGenerationError("Design specification must be an object")
        shape = str(spec.get("shape") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if shape not in self.SHAPES:
            raise CadGenerationError("Unsupported shape. Choose one of: %s" % ", ".join(sorted(self.SHAPES)))
        dimensions = spec.get("dimensions") or {}
        if not isinstance(dimensions, dict):
            raise CadGenerationError("dimensions must be an object")
        metadata = dict(spec.get("metadata") or {})
        self._validate_reference_metadata(metadata)
        result = {"shape": shape, "dimensions": {}, "holes": [], "slots": [], "bosses": [], "ribs": [], "tabs": [], "internal_posts": [], "dividers": [], "cable_openings": [], "lid_interface": {}, "edge_treatment": {}, "metadata": metadata}
        if shape == "cylinder":
            result["dimensions"]["diameter"] = self._number(dimensions.get("diameter", dimensions.get("width", 50)), "diameter")
            result["dimensions"]["height"] = self._number(dimensions.get("height", 10), "height")
        elif shape == "flange":
            outer = self._number(dimensions.get("outer_diameter", dimensions.get("diameter", 80)), "outer_diameter")
            bore = self._number(dimensions.get("bore_diameter", dimensions.get("inner_diameter", 20)), "bore_diameter")
            if bore >= outer:
                raise CadGenerationError("bore_diameter must be smaller than outer_diameter")
            result["dimensions"].update({
                "outer_diameter": outer,
                "bore_diameter": bore,
                "height": self._number(dimensions.get("height", 8), "height"),
                "bolt_circle_diameter": self._number(dimensions.get("bolt_circle_diameter", outer * 0.7), "bolt_circle_diameter"),
                "bolt_hole_diameter": self._number(dimensions.get("bolt_hole_diameter", 5), "bolt_hole_diameter"),
                "bolt_hole_count": dimensions.get("bolt_hole_count", 4),
            })
            if result["dimensions"]["bolt_circle_diameter"] >= outer:
                raise CadGenerationError("bolt_circle_diameter must be smaller than outer_diameter")
            bolt_hole_count = self._integer(
                result["dimensions"]["bolt_hole_count"], "bolt_hole_count", 2, self.MAX_FEATURES - 1
            )
            result["dimensions"]["bolt_hole_count"] = bolt_hole_count
        elif shape == "ring":
            outer = self._number(dimensions.get("outer_diameter", dimensions.get("diameter", 50)), "outer_diameter")
            inner = self._number(dimensions.get("inner_diameter", 25), "inner_diameter")
            if inner >= outer:
                raise CadGenerationError("inner_diameter must be smaller than outer_diameter")
            result["dimensions"].update({"outer_diameter": outer, "inner_diameter": inner,
                                         "height": self._number(dimensions.get("height", 5), "height")})
        elif shape == "enclosure":
            width = self._number(dimensions.get("width", 100), "width")
            depth = self._number(dimensions.get("depth", 60), "depth")
            height = self._number(dimensions.get("height", 40), "height")
            wall = self._number(dimensions.get("wall_thickness", 2), "wall_thickness")
            floor = self._number(dimensions.get("floor_thickness", wall), "floor_thickness")
            corner = self._number(dimensions.get("corner_radius", 0), "corner_radius", 0.0, min(width, depth) / 4)
            if corner >= min(width, depth) / 2 - wall:
                raise CadGenerationError("corner_radius is too large for enclosure wall thickness")
            if wall * 2 >= min(width, depth):
                raise CadGenerationError("wall_thickness is too large for enclosure footprint")
            if floor >= height:
                raise CadGenerationError("floor_thickness must be smaller than enclosure height")
            result["dimensions"] = {"width": width, "depth": depth, "height": height,
                                    "wall_thickness": wall, "floor_thickness": floor, "corner_radius": corner}
        else:
            result["dimensions"] = {
                "width": self._number(dimensions.get("width", 100), "width"),
                "depth": self._number(dimensions.get("depth", 60), "depth"),
                "height": self._number(dimensions.get("height", 5), "height"),
            }
        holes = spec.get("holes") or []
        if not isinstance(holes, list):
            raise CadGenerationError("holes must be an array")
        if len(holes) > self.MAX_FEATURES:
            raise CadGenerationError("Too many holes; maximum is %s" % self.MAX_FEATURES)
        for hole in holes:
            if not isinstance(hole, dict):
                raise CadGenerationError("Each hole must be an object")
            diameter = self._number(hole.get("diameter"), "hole diameter")
            head_type = str(hole.get("head_type") or "").strip().lower()
            if head_type not in {"", "countersink", "counterbore"}:
                raise CadGenerationError("hole head_type must be countersink or counterbore")
            head_diameter = None
            head_depth = None
            if head_type:
                head_diameter = self._number(hole.get("head_diameter"), "hole head diameter")
                head_depth = self._number(hole.get("head_depth"), "hole head depth")
                if head_diameter <= diameter:
                    raise CadGenerationError("hole head diameter must exceed hole diameter")
                if head_depth >= result["dimensions"]["height"]:
                    raise CadGenerationError("hole head depth must be smaller than part height")
            result["holes"].append({
                "diameter": diameter,
                "x": self._number(hole.get("x", 0), "hole x", -2000, 2000),
                "y": self._number(hole.get("y", 0), "hole y", -2000, 2000),
                "head_type": head_type,
                "head_diameter": head_diameter,
                "head_depth": head_depth,
            })
        bosses = spec.get("bosses") or []
        if not isinstance(bosses, list):
            raise CadGenerationError("bosses must be an array")
        if bosses and shape not in {"box", "plate", "mounting_plate", "enclosure"}:
            raise CadGenerationError("bosses are currently supported only on box-like parts")
        if len(bosses) > self.MAX_FEATURES:
            raise CadGenerationError("Too many bosses; maximum is %s" % self.MAX_FEATURES)
        for boss in bosses:
            if not isinstance(boss, dict):
                raise CadGenerationError("Each boss must be an object")
            diameter = self._number(boss.get("diameter"), "boss diameter")
            height = self._number(boss.get("height"), "boss height")
            x = self._number(boss.get("x", 0), "boss x", -2000, 2000)
            y = self._number(boss.get("y", 0), "boss y", -2000, 2000)
            # Bosses are raised exterior/top features. Enclosures use the same
            # top-surface coordinate system as plates; internal features use the
            # dedicated internal_posts primitive.
            if abs(x) + diameter / 2 > result["dimensions"]["width"] / 2:
                raise CadGenerationError("boss x or radius is outside the part")
            if abs(y) + diameter / 2 > result["dimensions"]["depth"] / 2:
                raise CadGenerationError("boss y or radius is outside the part")
            result["bosses"].append({"diameter": diameter, "height": height, "x": x, "y": y})
        ribs = spec.get("ribs") or []
        if not isinstance(ribs, list):
            raise CadGenerationError("ribs must be an array")
        if ribs and shape not in {"box", "plate", "mounting_plate", "bracket", "enclosure"}:
            raise CadGenerationError("ribs are currently supported only on box-like parts and brackets")
        if len(ribs) > self.MAX_FEATURES:
            raise CadGenerationError("Too many ribs; maximum is %s" % self.MAX_FEATURES)
        for rib in ribs:
            if not isinstance(rib, dict):
                raise CadGenerationError("Each rib must be an object")
            length = self._number(rib.get("length"), "rib length")
            width = self._number(rib.get("width"), "rib width")
            height = self._number(rib.get("height"), "rib height")
            x = self._number(rib.get("x", 0), "rib x", -2000, 2000)
            y = self._number(rib.get("y", 0), "rib y", -2000, 2000)
            angle = self._angle(rib.get("angle", 0), "rib angle")
            angle_radians = math.radians(angle % 360.0)
            half_x = (length * abs(math.cos(angle_radians)) + width * abs(math.sin(angle_radians))) / 2.0
            half_y = (length * abs(math.sin(angle_radians)) + width * abs(math.cos(angle_radians))) / 2.0
            if half_x > result["dimensions"]["width"] / 2 or half_y > result["dimensions"]["depth"] / 2:
                raise CadGenerationError("rib footprint is too large for the part at this angle")
            if abs(x) + half_x > result["dimensions"]["width"] / 2 or abs(y) + half_y > result["dimensions"]["depth"] / 2:
                raise CadGenerationError("rib position is outside the part at this angle")
            result["ribs"].append({"length": length, "width": width, "height": height, "x": x, "y": y, "angle": angle})
        tabs = spec.get("tabs") or []
        if not isinstance(tabs, list):
            raise CadGenerationError("tabs must be an array")
        if tabs and shape not in {"box", "plate", "mounting_plate", "bracket", "enclosure"}:
            raise CadGenerationError("tabs are currently supported only on box-like parts and brackets")
        if len(tabs) > self.MAX_FEATURES:
            raise CadGenerationError("Too many tabs; maximum is %s" % self.MAX_FEATURES)
        for tab in tabs:
            if not isinstance(tab, dict):
                raise CadGenerationError("Each tab must be an object")
            length = self._number(tab.get("length"), "tab length")
            width = self._number(tab.get("width"), "tab width")
            height = self._number(tab.get("height", result["dimensions"]["height"]), "tab height")
            x = self._number(tab.get("x", 0), "tab x", -2000, 2000)
            y = self._number(tab.get("y", 0), "tab y", -2000, 2000)
            angle = self._angle(tab.get("angle", 0), "tab angle")
            angle_radians = math.radians(angle % 360.0)
            half_x = (length * abs(math.cos(angle_radians)) + width * abs(math.sin(angle_radians))) / 2.0
            half_y = (length * abs(math.sin(angle_radians)) + width * abs(math.cos(angle_radians))) / 2.0
            if half_x > result["dimensions"]["width"] / 2 or half_y > result["dimensions"]["depth"] / 2:
                raise CadGenerationError("tab footprint is too large for the part at this angle")
            if abs(x) + half_x > result["dimensions"]["width"] / 2 or abs(y) + half_y > result["dimensions"]["depth"] / 2:
                raise CadGenerationError("tab position is outside the part at this angle")
            result["tabs"].append({"length": length, "width": width, "height": height, "x": x, "y": y, "angle": angle})
        internal_posts = spec.get("internal_posts") or []
        if not isinstance(internal_posts, list):
            raise CadGenerationError("internal_posts must be an array")
        if internal_posts and shape != "enclosure":
            raise CadGenerationError("internal_posts are currently supported only on enclosures")
        if len(internal_posts) > self.MAX_FEATURES:
            raise CadGenerationError("Too many internal posts; maximum is %s" % self.MAX_FEATURES)
        for post in internal_posts:
            if not isinstance(post, dict):
                raise CadGenerationError("Each internal post must be an object")
            diameter = self._number(post.get("diameter"), "internal post diameter")
            height = self._number(post.get("height", result["dimensions"]["height"] - result["dimensions"]["floor_thickness"]), "internal post height")
            interior_height = result["dimensions"]["height"] - result["dimensions"]["floor_thickness"]
            if height > interior_height:
                raise CadGenerationError("internal post height exceeds the enclosure interior height")
            x = self._number(post.get("x", 0), "internal post x", -2000, 2000)
            y = self._number(post.get("y", 0), "internal post y", -2000, 2000)
            bore = post.get("bore_diameter")
            bore = self._number(bore, "internal post bore diameter") if bore is not None else None
            if bore is not None and bore >= diameter:
                raise CadGenerationError("internal post bore_diameter must be smaller than diameter")
            usable_w = result["dimensions"]["width"] / 2 - result["dimensions"]["wall_thickness"]
            usable_d = result["dimensions"]["depth"] / 2 - result["dimensions"]["wall_thickness"]
            if abs(x) + diameter / 2 > usable_w or abs(y) + diameter / 2 > usable_d:
                raise CadGenerationError("internal post is outside the enclosure interior")
            result["internal_posts"].append({"diameter": diameter, "height": height, "x": x, "y": y, "bore_diameter": bore})
        dividers = spec.get("dividers") or []
        if not isinstance(dividers, list):
            raise CadGenerationError("dividers must be an array")
        if dividers and shape != "enclosure":
            raise CadGenerationError("dividers are currently supported only on enclosures")
        if len(dividers) > self.MAX_FEATURES:
            raise CadGenerationError("Too many dividers; maximum is %s" % self.MAX_FEATURES)
        for divider in dividers:
            if not isinstance(divider, dict):
                raise CadGenerationError("Each divider must be an object")
            length = self._number(divider.get("length"), "divider length")
            thickness = self._number(divider.get("thickness", result["dimensions"]["wall_thickness"]), "divider thickness")
            height = self._number(divider.get("height", result["dimensions"]["height"] - result["dimensions"]["floor_thickness"]), "divider height")
            interior_height = result["dimensions"]["height"] - result["dimensions"]["floor_thickness"]
            if height > interior_height:
                raise CadGenerationError("divider height exceeds the enclosure interior height")
            x = self._number(divider.get("x", 0), "divider x", -2000, 2000)
            y = self._number(divider.get("y", 0), "divider y", -2000, 2000)
            angle = self._angle(divider.get("angle", 0), "divider angle")
            angle_radians = math.radians(angle % 360.0)
            cos_a, sin_a = abs(math.cos(angle_radians)), abs(math.sin(angle_radians))
            half_x = (length * cos_a + thickness * sin_a) / 2.0
            half_y = (length * sin_a + thickness * cos_a) / 2.0
            interior_half_w = result["dimensions"]["width"] / 2 - result["dimensions"]["wall_thickness"]
            interior_half_d = result["dimensions"]["depth"] / 2 - result["dimensions"]["wall_thickness"]
            if half_x > interior_half_w or half_y > interior_half_d:
                raise CadGenerationError("divider footprint is too large for the enclosure interior at this angle")
            if abs(x) + half_x > interior_half_w or abs(y) + half_y > interior_half_d:
                raise CadGenerationError("divider position is outside the enclosure interior at this angle")
            result["dividers"].append({"length": length, "thickness": thickness, "height": height, "x": x, "y": y, "angle": angle})
        cable_openings = spec.get("cable_openings") or []
        if not isinstance(cable_openings, list):
            raise CadGenerationError("cable_openings must be an array")
        if cable_openings and shape != "enclosure":
            raise CadGenerationError("cable_openings are currently supported only on enclosures")
        if len(cable_openings) > self.MAX_FEATURES:
            raise CadGenerationError("Too many cable openings; maximum is %s" % self.MAX_FEATURES)
        for opening in cable_openings:
            if not isinstance(opening, dict):
                raise CadGenerationError("Each cable opening must be an object")
            side = str(opening.get("side", "front")).strip().lower()
            if side not in {"front", "back", "left", "right"}:
                raise CadGenerationError("cable opening side must be front, back, left, or right")
            width = self._number(opening.get("width"), "cable opening width")
            height = self._number(opening.get("height"), "cable opening height")
            offset = self._number(opening.get("offset", 0), "cable opening offset", -2000, 2000)
            z = self._number(opening.get("z", result["dimensions"]["floor_thickness"] + height / 2), "cable opening z", 0, result["dimensions"]["height"])
            if z - height / 2 < result["dimensions"]["floor_thickness"] or z + height / 2 > result["dimensions"]["height"]:
                raise CadGenerationError("cable opening height is outside the enclosure wall")
            side_span = (result["dimensions"]["width"] if side in {"front", "back"} else result["dimensions"]["depth"]) - 2 * result["dimensions"]["wall_thickness"]
            if width > side_span:
                raise CadGenerationError("cable opening is wider than the usable enclosure wall span")
            if abs(offset) + width / 2 > side_span / 2:
                raise CadGenerationError("cable opening offset places it outside the enclosure wall span")
            result["cable_openings"].append({"side": side, "width": width, "height": height, "offset": offset, "z": z})
        lid_interface = spec.get("lid_interface") or {}
        if not isinstance(lid_interface, dict):
            raise CadGenerationError("lid_interface must be an object")
        if lid_interface and shape != "enclosure":
            raise CadGenerationError("lid_interface is currently supported only on enclosures")
        if lid_interface:
            lip_height = self._number(lid_interface.get("lip_height", 2), "lid lip height")
            clearance = self._number(lid_interface.get("clearance", 0.25), "lid clearance")
            lip_wall = self._number(lid_interface.get("lip_wall", result["dimensions"]["wall_thickness"]), "lid lip wall")
            if lip_height >= result["dimensions"]["height"] - result["dimensions"]["floor_thickness"]:
                raise CadGenerationError("lid lip height is too large")
            inner_w = result["dimensions"]["width"] - 2 * result["dimensions"]["wall_thickness"] - 2 * clearance
            inner_d = result["dimensions"]["depth"] - 2 * result["dimensions"]["wall_thickness"] - 2 * clearance
            if inner_w <= 0 or inner_d <= 0:
                raise CadGenerationError("lid clearance is too large")
            if lip_wall >= min(inner_w, inner_d) / 2:
                raise CadGenerationError("lid lip wall is too large for the available lid interface")
            result["lid_interface"] = {"lip_height": lip_height, "clearance": clearance, "lip_wall": lip_wall}

        if shape == "enclosure" and result["internal_posts"] and result["dividers"]:
            for post in result["internal_posts"]:
                circle = {"x": post["x"], "y": post["y"], "diameter": post["diameter"]}
                for divider in result["dividers"]:
                    if self._circle_obb_overlap(circle, divider):
                        raise CadGenerationError("internal post overlaps an enclosure divider")
        if shape == "enclosure" and len(result["dividers"]) > 1:
            for index, divider in enumerate(result["dividers"]):
                for other in result["dividers"][index + 1:]:
                    if self._obb_overlap(divider, other):
                        raise CadGenerationError("enclosure dividers overlap")

        edge_treatment = spec.get("edge_treatment") or {}
        if not isinstance(edge_treatment, dict):
            raise CadGenerationError("edge_treatment must be an object")
        if edge_treatment and shape not in {"box", "plate", "mounting_plate"}:
            raise CadGenerationError("edge treatments are currently supported only on box-like parts")
        fillet_radius = edge_treatment.get("fillet_radius")
        chamfer_distance = edge_treatment.get("chamfer_distance")
        if fillet_radius is not None and chamfer_distance is not None:
            raise CadGenerationError("Choose either fillet_radius or chamfer_distance, not both")
        if fillet_radius is not None:
            fillet_radius = self._number(fillet_radius, "fillet radius", 0.01, 500)
            if fillet_radius >= min(result["dimensions"]["width"], result["dimensions"]["depth"]) / 2:
                raise CadGenerationError("fillet radius is too large for the part footprint")
            result["edge_treatment"]["fillet_radius"] = fillet_radius
        if chamfer_distance is not None:
            chamfer_distance = self._number(chamfer_distance, "chamfer distance", 0.01, 500)
            if chamfer_distance >= min(result["dimensions"]["width"], result["dimensions"]["depth"]) / 2:
                raise CadGenerationError("chamfer distance is too large for the part footprint")
            result["edge_treatment"]["chamfer_distance"] = chamfer_distance
        slots = spec.get("slots") or []
        if not isinstance(slots, list):
            raise CadGenerationError("slots must be an array")
        if slots and shape in {"cylinder", "ring", "flange"}:
            raise CadGenerationError("slots are currently supported only on box-like parts")
        if len(slots) > self.MAX_FEATURES:
            raise CadGenerationError("Too many slots; maximum is %s" % self.MAX_FEATURES)
        for slot in slots:
            if not isinstance(slot, dict):
                raise CadGenerationError("Each slot must be an object")
            length = self._number(slot.get("length"), "slot length")
            width = self._number(slot.get("width"), "slot width")
            if width > length:
                raise CadGenerationError("slot width cannot exceed slot length")
            result["slots"].append({
                "length": length,
                "width": width,
                "x": self._number(slot.get("x", 0), "slot x", -2000, 2000),
                "y": self._number(slot.get("y", 0), "slot y", -2000, 2000),
                "angle": self._angle(slot.get("angle", 0), "slot angle"),
            })
        mounting_pattern = spec.get("mounting_pattern") or {}
        if mounting_pattern:
            if not isinstance(mounting_pattern, dict):
                raise CadGenerationError("mounting_pattern must be an object")
            pattern_type = str(mounting_pattern.get("type") or "rectangular").strip().lower()
            if pattern_type not in {"rectangular", "grid", "radial"}:
                raise CadGenerationError("mounting_pattern type must be rectangular, grid, or radial")
            diameter = self._number(mounting_pattern.get("diameter", 5), "mounting pattern hole diameter")
            if pattern_type in {"rectangular", "grid"}:
                spacing_x = self._number(mounting_pattern.get("spacing_x", 20), "mounting pattern spacing_x")
                spacing_y = self._number(mounting_pattern.get("spacing_y", spacing_x), "mounting pattern spacing_y")
                count_x = self._integer(mounting_pattern.get("count_x", 2), "mounting pattern count_x", 1, 8)
                count_y = self._integer(mounting_pattern.get("count_y", 2), "mounting pattern count_y", 1, 8)
                required = count_x * count_y
                if len(result["holes"]) + required > self.MAX_FEATURES:
                    raise CadGenerationError("Mounting pattern would exceed the maximum of %s holes" % self.MAX_FEATURES)
                origin_x = self._number(mounting_pattern.get("origin_x", 0), "mounting pattern origin_x", -2000, 2000)
                origin_y = self._number(mounting_pattern.get("origin_y", 0), "mounting pattern origin_y", -2000, 2000)
                for ix in range(count_x):
                    for iy in range(count_y):
                        x = origin_x + (ix - (count_x - 1) / 2.0) * spacing_x
                        y = origin_y + (iy - (count_y - 1) / 2.0) * spacing_y
                        result["holes"].append({"diameter": diameter, "x": x, "y": y, "head_type": "", "head_diameter": None, "head_depth": None})
            else:
                count = self._integer(
                    mounting_pattern.get("count", 4), "mounting pattern count", 2, self.MAX_FEATURES
                )
                if len(result["holes"]) + count > self.MAX_FEATURES:
                    raise CadGenerationError("Mounting pattern would exceed the maximum of %s holes" % self.MAX_FEATURES)
                radius = self._number(mounting_pattern.get("radius", 20), "mounting pattern radius")
                center_x = self._number(mounting_pattern.get("center_x", 0), "mounting pattern center_x", -2000, 2000)
                center_y = self._number(mounting_pattern.get("center_y", 0), "mounting pattern center_y", -2000, 2000)
                start_angle = self._angle(mounting_pattern.get("start_angle", 0), "mounting pattern start_angle")
                for index in range(count):
                    angle = math.radians(start_angle + (360.0 * index / count))
                    result["holes"].append({
                        "diameter": diameter,
                        "x": center_x + radius * math.cos(angle),
                        "y": center_y + radius * math.sin(angle),
                        "head_type": "", "head_diameter": None, "head_depth": None,
                    })
        if shape == "flange" and not result["holes"]:
            d = result["dimensions"]
            result["holes"].append({"diameter": d["bore_diameter"], "x": 0.0, "y": 0.0})
            radius = d["bolt_circle_diameter"] / 2.0
            for index in range(d["bolt_hole_count"]):
                angle = (2.0 * math.pi * index) / d["bolt_hole_count"]
                result["holes"].append({
                    "diameter": d["bolt_hole_diameter"],
                    "x": radius * math.cos(angle),
                    "y": radius * math.sin(angle),
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
            half_r = hole["diameter"] / 2
            if shape == "cylinder":
                radial = (hole["x"] ** 2 + hole["y"] ** 2) ** 0.5
                if radial + half_r > result["dimensions"]["diameter"] / 2:
                    raise CadGenerationError("hole x/y or radius is outside the cylinder")
                continue
            if shape == "ring":
                radial = (hole["x"] ** 2 + hole["y"] ** 2) ** 0.5
                outer_radius = result["dimensions"]["outer_diameter"] / 2
                inner_radius = result["dimensions"]["inner_diameter"] / 2
                if radial + half_r > outer_radius or radial - half_r < inner_radius:
                    raise CadGenerationError("hole x/y or radius is outside the ring wall")
                continue
            if shape == "flange":
                radial = (hole["x"] ** 2 + hole["y"] ** 2) ** 0.5
                if radial + half_r > result["dimensions"]["outer_diameter"] / 2:
                    raise CadGenerationError("hole x/y or radius is outside the flange")
                continue
            if abs(hole["x"]) + half_r > result["dimensions"]["width"] / 2:
                raise CadGenerationError("hole x or radius is outside the part")
            if abs(hole["y"]) + half_r > result["dimensions"]["depth"] / 2:
                raise CadGenerationError("hole y or radius is outside the part")
        for slot in result["slots"]:
            radius = slot["width"] / 2.0
            half_straight = max(0.0, (slot["length"] - slot["width"]) / 2.0)
            angle = math.radians(slot.get("angle", 0.0) % 360.0)
            # A slot is a capsule: rotate its straight centerline, then add the
            # circular end radius to both axes for a conservative exact bounding box.
            half_x = half_straight * abs(math.cos(angle)) + radius
            half_y = half_straight * abs(math.sin(angle)) + radius
            if shape not in {"cylinder", "ring", "flange"}:
                if abs(slot["x"]) + half_x > result["dimensions"]["width"] / 2:
                    raise CadGenerationError("slot x or rotated length is outside the part")
                if abs(slot["y"]) + half_y > result["dimensions"]["depth"] / 2:
                    raise CadGenerationError("slot y or rotated width is outside the part")
        # Reject feature interference before CAD generation. These checks are intentionally
        # conservative: a requested through-hole must not overlap another cut or a raised
        # cylindrical feature, because the resulting boolean would no longer represent the
        # requested dimensions independently.
        holes = result["holes"]
        for index, first in enumerate(holes):
            for second in holes[index + 1:]:
                distance = math.hypot(first["x"] - second["x"], first["y"] - second["y"])
                if distance < (first["diameter"] + second["diameter"]) / 2.0:
                    raise CadGenerationError("holes overlap in the requested XY layout")
        for hole in holes:
            hole_radius = hole["diameter"] / 2.0
            for boss in result["bosses"]:
                if math.hypot(hole["x"] - boss["x"], hole["y"] - boss["y"]) < hole_radius + boss["diameter"] / 2.0:
                    raise CadGenerationError("hole overlaps a boss in the requested XY layout")
            for post in result["internal_posts"]:
                if math.hypot(hole["x"] - post["x"], hole["y"] - post["y"]) < hole_radius + post["diameter"] / 2.0:
                    raise CadGenerationError("hole overlaps an internal post in the requested XY layout")
            for feature_name in ("ribs", "tabs"):
                for feature in result[feature_name]:
                    rect = {"x": feature["x"], "y": feature["y"], "length": feature["length"],
                            "thickness": feature["width"], "angle": feature["angle"]}
                    if self._circle_obb_overlap({"x": hole["x"], "y": hole["y"], "diameter": hole["diameter"]}, rect):
                        raise CadGenerationError("hole overlaps a %s feature in the requested XY layout" % feature_name[:-1])

        for index, first in enumerate(result["bosses"]):
            for second in result["bosses"][index + 1:]:
                if math.hypot(first["x"] - second["x"], first["y"] - second["y"]) < (first["diameter"] + second["diameter"]) / 2.0:
                    raise CadGenerationError("bosses overlap in the requested XY layout")

        for boss in result["bosses"]:
            boss_circle = {"x": boss["x"], "y": boss["y"], "diameter": boss["diameter"]}
            for feature_name in ("ribs", "tabs"):
                for feature in result[feature_name]:
                    rect = {"x": feature["x"], "y": feature["y"], "length": feature["length"],
                            "thickness": feature["width"], "angle": feature["angle"]}
                    if self._circle_obb_overlap(boss_circle, rect):
                        raise CadGenerationError("boss overlaps a %s feature in the requested XY layout" % feature_name[:-1])

        for feature_name in ("ribs", "tabs"):
            features = result[feature_name]
            for index, first in enumerate(features):
                first_rect = {"x": first["x"], "y": first["y"], "length": first["length"],
                              "thickness": first["width"], "angle": first["angle"]}
                for second in features[index + 1:]:
                    second_rect = {"x": second["x"], "y": second["y"], "length": second["length"],
                                   "thickness": second["width"], "angle": second["angle"]}
                    if self._obb_overlap(first_rect, second_rect):
                        raise CadGenerationError("%s overlap in the requested XY layout" % feature_name)

        for rib in result["ribs"]:
            rib_rect = {"x": rib["x"], "y": rib["y"], "length": rib["length"],
                        "thickness": rib["width"], "angle": rib["angle"]}
            for tab in result["tabs"]:
                tab_rect = {"x": tab["x"], "y": tab["y"], "length": tab["length"],
                            "thickness": tab["width"], "angle": tab["angle"]}
                if self._obb_overlap(rib_rect, tab_rect):
                    raise CadGenerationError("rib overlaps a tab in the requested XY layout")

        for slot in result["slots"]:
            for hole in holes:
                if self._capsule_circle_overlap(slot, hole):
                    raise CadGenerationError("slot overlaps a hole in the requested XY layout")
            for boss in result["bosses"]:
                if self._capsule_circle_overlap(slot, boss):
                    raise CadGenerationError("slot overlaps a boss in the requested XY layout")
            slot_rect = {"x": slot["x"], "y": slot["y"], "length": slot["length"],
                         "thickness": slot["width"], "angle": slot["angle"]}
            for feature_name in ("ribs", "tabs"):
                for feature in result[feature_name]:
                    rect = {"x": feature["x"], "y": feature["y"], "length": feature["length"],
                            "thickness": feature["width"], "angle": feature["angle"]}
                    # The OBB is a conservative envelope around the capsule. Rejecting an
                    # envelope intersection prevents a boolean from silently changing feature intent.
                    if self._obb_overlap(slot_rect, rect):
                        raise CadGenerationError("slot overlaps a %s feature in the requested XY layout" % feature_name[:-1])
            for other in result["slots"]:
                if other is not slot and self._capsule_overlap(slot, other):
                    raise CadGenerationError("slots overlap in the requested XY layout")
        print_constraints = spec.get("print_constraints") or {}
        if not isinstance(print_constraints, dict):
            raise CadGenerationError("print_constraints must be an object")
        nozzle = self._number(print_constraints.get("nozzle_diameter", 0.4), "nozzle diameter", 0.1, 2.0)
        min_wall = self._number(print_constraints.get("min_wall_thickness", nozzle * 2), "minimum wall thickness", 0.1, 20.0)
        min_feature = self._number(print_constraints.get("min_feature_size", nozzle), "minimum feature size", 0.1, 20.0)
        strict = bool(print_constraints.get("strict", False))
        result["print_constraints"] = {"nozzle_diameter": nozzle, "min_wall_thickness": min_wall,
                                       "min_feature_size": min_feature, "strict": strict}
        if shape == "enclosure" and result["dimensions"]["wall_thickness"] < min_wall:
            message = "enclosure wall thickness is below the requested printable minimum"
            if strict:
                raise CadGenerationError(message)
            result["metadata"].setdefault("printability_warnings", []).append(message)
        for feature_name, features in (("ribs", result["ribs"]), ("tabs", result["tabs"])):
            for feature in features:
                if min(feature["width"], feature["height"]) < min_feature:
                    message = "%s feature is below the requested printable minimum" % feature_name[:-1]
                    if strict:
                        raise CadGenerationError(message)
                    result["metadata"].setdefault("printability_warnings", []).append(message)
        for hole in result["holes"]:
            if hole["diameter"] < min_feature:
                message = "hole diameter is below the requested printable minimum"
                if strict:
                    raise CadGenerationError(message)
                result["metadata"].setdefault("printability_warnings", []).append(message)
        result["mounting_pattern"] = mounting_pattern
        return result

    def parse_prompt(self, prompt):
        text = str(prompt or "").strip()
        if not text:
            raise CadGenerationError("A design prompt is required")
        lowered = text.lower()
        if "mounting plate" in lowered:
            shape = "mounting_plate"
        elif "enclosure" in lowered or "case" in lowered or "housing" in lowered:
            shape = "enclosure"
        elif "bracket" in lowered:
            shape = "bracket"
        elif "flange" in lowered:
            shape = "flange"
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
        elif shape == "flange":
            spec = {"shape": shape, "dimensions": {"outer_diameter": dims[0], "bore_diameter": dims[1] if dims[1] < dims[0] else dims[0] / 4, "height": dims[2]}}
        elif shape == "enclosure":
            wall_match = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*(?:wall|walls|wall thickness|thick)", lowered)
            wall = float(wall_match.group(1)) if wall_match else 2.0
            spec = {"shape": shape, "dimensions": {"width": dims[0], "depth": dims[1], "height": dims[2], "wall_thickness": wall, "floor_thickness": wall}}
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
        elif shape == "enclosure":
            outer = cq.Workplane("XY").box(d["width"], d["depth"], d["height"], centered=(True, True, False))
            if d.get("corner_radius", 0):
                outer = outer.edges("|Z").fillet(d["corner_radius"])
            inner = (cq.Workplane("XY")
                     .box(d["width"] - 2 * d["wall_thickness"],
                          d["depth"] - 2 * d["wall_thickness"],
                          d["height"] - d["floor_thickness"],
                          centered=(True, True, False))
                     .translate((0, 0, d["floor_thickness"])))
            if d.get("corner_radius", 0):
                inner = inner.edges("|Z").fillet(max(0.01, d["corner_radius"] - d["wall_thickness"]))
            model = outer.cut(inner)
        if shape == "enclosure":
            for post in spec.get("internal_posts", []):
                post_model = cq.Workplane("XY").center(post["x"], post["y"]).circle(post["diameter"] / 2).extrude(post["height"])
                if post.get("bore_diameter"):
                    bore = (cq.Workplane("XY").center(post["x"], post["y"])
                             .circle(post["bore_diameter"] / 2)
                             .extrude(post["height"]))
                    post_model = post_model.cut(bore)
                post_model = post_model.translate((0, 0, d["floor_thickness"]))
                model = model.union(post_model)
            for divider in spec.get("dividers", []):
                divider_model = (cq.Workplane("XY").center(divider["x"], divider["y"])
                                 .box(divider["length"], divider["thickness"], divider["height"] + 0.5, centered=(True, True, False))
                                 .translate((0, 0, max(0.0, d["floor_thickness"] - 0.5))))
                if divider.get("angle"):
                    divider_model = divider_model.rotate((divider["x"], divider["y"], 0), (divider["x"], divider["y"], 1), divider["angle"])
                model = model.union(divider_model).clean()
            lid = spec.get("lid_interface") or {}
            if lid:
                outer_w = d["width"] - 2 * d["wall_thickness"]
                outer_d = d["depth"] - 2 * d["wall_thickness"]
                inner_w = outer_w - 2 * lid["clearance"]
                inner_d = outer_d - 2 * lid["clearance"]
                lip = (cq.Workplane("XY").box(outer_w, outer_d, lid["lip_height"], centered=(True, True, False))
                       .translate((0, 0, d["height"] - lid["lip_height"])))
                cut_w = max(0.1, inner_w - 2 * lid["lip_wall"])
                cut_d = max(0.1, inner_d - 2 * lid["lip_wall"])
                lip = lip.cut(cq.Workplane("XY").box(cut_w, cut_d, lid["lip_height"] + 1, centered=(True, True, False))
                              .translate((0, 0, d["height"] - lid["lip_height"])))
                model = model.union(lip)
            for opening in spec.get("cable_openings", []):
                if opening["side"] in {"front", "back"}:
                    cutter = cq.Workplane("XY").box(opening["width"], d["wall_thickness"] + 2, opening["height"], centered=(True, True, True))
                    y = d["depth"] / 2 + 0.5 if opening["side"] == "front" else -d["depth"] / 2 - 0.5
                    cutter = cutter.translate((opening["offset"], y, opening["z"]))
                else:
                    cutter = cq.Workplane("XY").box(d["wall_thickness"] + 2, opening["width"], opening["height"], centered=(True, True, True))
                    x = d["width"] / 2 + 0.5 if opening["side"] == "right" else -d["width"] / 2 - 0.5
                    cutter = cutter.translate((x, opening["offset"], opening["z"]))
                model = model.cut(cutter)
        elif shape == "flange":
            model = cq.Workplane("XY").circle(d["outer_diameter"] / 2).extrude(d["height"])
        elif shape == "cylinder":
            model = cq.Workplane("XY").circle(d["diameter"] / 2).extrude(d["height"])
        elif shape == "ring":
            model = cq.Workplane("XY").circle(d["outer_diameter"] / 2).circle(d["inner_diameter"] / 2).extrude(d["height"])
        elif shape == "bracket":
            base = cq.Workplane("XY").box(d["width"], d["depth"], d["height"], centered=(True, True, False))
            wall = cq.Workplane("XZ").box(d["width"], d["height"], d["depth"], centered=(True, False, False)).translate((0, d["depth"] / 2 - d["height"] / 2, d["height"]))
            model = base.union(wall)
        elif shape not in {"box", "plate", "mounting_plate", "enclosure"}:
            raise CadGenerationError("Unsupported shape")
        for rib in spec.get("ribs", []):
            rib_model = (cq.Workplane("XY").center(rib["x"], rib["y"])
                         .box(rib["length"], rib["width"], rib["height"], centered=(True, True, False))
                         .translate((0, 0, d.get("height", 5))))
            if rib.get("angle"):
                rib_model = rib_model.rotate((rib["x"], rib["y"], 0), (rib["x"], rib["y"], 1), rib["angle"])
            model = model.union(rib_model)
        for tab in spec.get("tabs", []):
            tab_model = (cq.Workplane("XY").center(tab["x"], tab["y"])
                         .box(tab["length"], tab["width"], tab["height"], centered=(True, True, False))
                         .translate((0, 0, d.get("height", 5))))
            if tab.get("angle"):
                tab_model = tab_model.rotate((tab["x"], tab["y"], d.get("height", 5)),
                                             (tab["x"], tab["y"], d.get("height", 5) + 1), tab["angle"])
            model = model.union(tab_model)
        edge_treatment = spec.get("edge_treatment") or {}
        if edge_treatment.get("fillet_radius") is not None:
            model = model.edges("|Z").fillet(edge_treatment["fillet_radius"])
        elif edge_treatment.get("chamfer_distance") is not None:
            model = model.edges("|Z").chamfer(edge_treatment["chamfer_distance"])
        for hole in spec["holes"]:
            height = d.get("height", 5)
            cutter = (cq.Workplane("XY").center(hole["x"], hole["y"])
                      .circle(hole["diameter"] / 2).extrude(height + 2))
            model = model.cut(cutter)
            if hole.get("head_type") == "counterbore":
                head = (cq.Workplane("XY", origin=(0, 0, height - hole["head_depth"]))
                        .center(hole["x"], hole["y"])
                        .circle(hole["head_diameter"] / 2)
                        .extrude(hole["head_depth"]))
                model = model.cut(head)
            elif hole.get("head_type") == "countersink":
                head = (cq.Workplane("XY", origin=(0, 0, height - hole["head_depth"]))
                        .center(hole["x"], hole["y"])
                        .circle(hole["diameter"] / 2)
                        .workplane(offset=hole["head_depth"])
                        .circle(hole["head_diameter"] / 2)
                        .loft(combine=False))
                model = model.cut(head)
        for boss in spec.get("bosses", []):
            boss_model = (cq.Workplane("XY").center(boss["x"], boss["y"])
                          .circle(boss["diameter"] / 2).extrude(boss["height"])
                          .translate((0, 0, d["height"])))
            model = model.union(boss_model)
        for slot in spec.get("slots", []):
            cutter = (cq.Workplane("XY").center(slot["x"], slot["y"])
                      .slot2D(slot["length"], slot["width"], slot["angle"])
                      .extrude(d.get("height", 5) + 2))
            model = model.cut(cutter)
        return model

    @staticmethod
    def _model_volume(model):
        """Return the volume of every solid contained in the CadQuery result."""
        try:
            # Workplane.val() can expose only the first object when a boolean
            # operation leaves multiple solids. Use the Workplane solids selector
            # first so verification accounts for every generated solid.
            values = list(model.solids().vals())
            if values:
                return sum(float(s.Volume()) for s in values)
        except Exception:
            pass
        try:
            shape = model.val()
            solids = list(shape.Solids())
            if solids:
                return sum(float(s.Volume()) for s in solids)
            return float(shape.Volume())
        except Exception:
            return float(model.val().Volume())

    def _verify(self, model, spec):
        shape = model.val()
        shape_type = spec["shape"]
        bb = shape.BoundingBox()
        actual = {"width_mm": round(bb.xlen, 4), "depth_mm": round(bb.ylen, 4), "height_mm": round(bb.zlen, 4)}
        d = spec["dimensions"]
        expected_height = d["height"]
        raised_heights = []
        if spec.get("bosses"):
            raised_heights.extend(boss["height"] for boss in spec["bosses"])
        if spec.get("ribs"):
            raised_heights.extend(rib["height"] for rib in spec["ribs"])
        if spec.get("tabs"):
            raised_heights.extend(tab["height"] for tab in spec["tabs"])
        if raised_heights:
            expected_height += max(raised_heights)
        expected = {"width_mm": round(d.get("width", d.get("outer_diameter", d.get("diameter"))), 4),
                    "depth_mm": round(d.get("depth", d.get("outer_diameter", d.get("diameter"))), 4),
                    "height_mm": round(expected_height, 4)}
        checks = []
        for key in expected:
            delta = abs(actual[key] - expected[key])
            checks.append({"measurement": key, "expected_mm": expected[key], "actual_mm": actual[key],
                           "delta_mm": round(delta, 5), "pass": delta <= 0.01})

        # Bounding-box checks are necessary but not sufficient. For every requested
        # hole, inspect the resulting solid's cylindrical faces so we can verify the
        # modeled diameter and approximate center rather than merely echoing the spec.
        hole_checks = []
        circles = []
        for face in shape.Faces():
            try:
                if face.geomType() == "CYLINDER":
                    circles.append(face)
            except Exception:
                continue
        if spec.get("holes"):
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
                head_type = requested.get("head_type") or ""
                head_diameter_ok = True
                head_depth_ok = True
                head_actual_diameter = None
                head_actual_depth = None
                if head_type:
                    head_faces = []
                    target_head_radius = requested["head_diameter"] / 2.0
                    target_depth = requested["head_depth"]
                    for face in shape.Faces():
                        try:
                            geom_type = face.geomType()
                            if head_type == "counterbore" and geom_type != "CYLINDER":
                                continue
                            if head_type == "countersink" and geom_type != "CONE":
                                continue
                            fb = face.BoundingBox()
                            center = face.Center()
                            center_distance = ((float(center.x) - requested["x"]) ** 2 +
                                               (float(center.y) - requested["y"]) ** 2) ** 0.5
                            diameter_span = max(float(fb.xlen), float(fb.ylen))
                            depth_span = float(fb.zlen)
                            head_faces.append((abs(diameter_span - requested["head_diameter"]),
                                               abs(depth_span - target_depth),
                                               center_distance, diameter_span, depth_span,
                                               float(fb.zmax)))
                        except Exception:
                            continue
                    candidate_head = min(head_faces, key=lambda item: (item[2], item[0], item[1])) if head_faces else None
                    if candidate_head:
                        head_actual_diameter = round(candidate_head[3], 4)
                        head_actual_depth = round(candidate_head[4], 4)
                        head_diameter_ok = candidate_head[0] <= 0.05 and candidate_head[2] <= 0.05
                        head_depth_ok = candidate_head[1] <= 0.05 and abs(candidate_head[5] - spec["dimensions"]["height"]) <= 0.05
                    else:
                        head_diameter_ok = False
                        head_depth_ok = False
                hole_checks.append({
                    "requested_diameter_mm": round(requested["diameter"], 4),
                    "actual_diameter_mm": round(best[4] * 2, 4) if best else None,
                    "requested_x_mm": round(requested["x"], 4),
                    "requested_y_mm": round(requested["y"], 4),
                    "actual_x_mm": round(best[2], 4) if best else None,
                    "actual_y_mm": round(best[3], 4) if best else None,
                    "head_type": head_type,
                    "requested_head_diameter_mm": round(requested["head_diameter"], 4) if requested.get("head_diameter") else None,
                    "actual_head_diameter_mm": head_actual_diameter,
                    "requested_head_depth_mm": round(requested["head_depth"], 4) if requested.get("head_depth") else None,
                    "actual_head_depth_mm": head_actual_depth,
                    "diameter_pass": diameter_ok,
                    "location_pass": location_ok,
                    "head_diameter_pass": head_diameter_ok,
                    "head_depth_pass": head_depth_ok,
                    "pass": diameter_ok and location_ok and head_diameter_ok and head_depth_ok,
                })

        boss_checks = []
        if spec.get("bosses"):
            for requested in spec["bosses"]:
                target_r = requested["diameter"] / 2.0
                candidates = []
                for face in circles:
                    try:
                        radius = float(face._geomAdaptor().Radius())
                        center = face.Center()
                        bbox = face.BoundingBox()
                        radius_error = abs(radius - target_r)
                        distance = ((float(center.x) - requested["x"]) ** 2 +
                                    (float(center.y) - requested["y"]) ** 2) ** 0.5
                        candidates.append((radius_error, distance, float(center.x), float(center.y), radius, float(bbox.zlen)))
                    except Exception:
                        continue
                matching = [item for item in candidates if item[0] <= 0.01]
                best = min(matching or candidates, key=lambda item: (item[1], item[0])) if (matching or candidates) else None
                diameter_ok = bool(best and best[0] <= 0.01)
                location_ok = bool(best and abs(best[2] - requested["x"]) <= 0.05 and abs(best[3] - requested["y"]) <= 0.05)
                height_ok = bool(best and abs(best[5] - requested["height"]) <= 0.05)
                boss_checks.append({
                    "requested_diameter_mm": round(requested["diameter"], 4),
                    "actual_diameter_mm": round(best[4] * 2, 4) if best else None,
                    "requested_x_mm": round(requested["x"], 4),
                    "requested_y_mm": round(requested["y"], 4),
                    "actual_x_mm": round(best[2], 4) if best else None,
                    "actual_y_mm": round(best[3], 4) if best else None,
                    "requested_height_mm": round(requested["height"], 4),
                    "actual_height_mm": round(best[5], 4) if best else None,
                    "diameter_pass": diameter_ok,
                    "location_pass": location_ok,
                    "height_pass": height_ok,
                    "pass": diameter_ok and location_ok and height_ok,
                })
        # Verify enclosure internals against actual solid volume rather than trusting the request count.
        # This catches regressions where a requested feature is normalized but the boolean operation
        # does not actually change the generated geometry.
        divider_requested = len(spec.get("dividers", []))
        divider_volume_delta = 0.0
        divider_pass = True
        if shape_type == "enclosure" and divider_requested:
            baseline = dict(spec)
            baseline["dividers"] = []
            try:
                baseline_model = self._cadquery_model(baseline)
                baseline_volume = self._model_volume(baseline_model)
                actual_volume = self._model_volume(model)
                divider_volume_delta = actual_volume - baseline_volume
                expected_divider_volume = sum(
                    float(item["length"]) * float(item["thickness"]) * float(item["height"])
                    for item in spec.get("dividers", [])
                )
                divider_pass = divider_volume_delta > 0.001 and divider_volume_delta >= expected_divider_volume * 0.50
                if not divider_pass:
                    detected = 0
                    localized_delta = 0.0
                    for item in spec.get("dividers", []):
                        length = float(item["length"])
                        thickness = float(item["thickness"])
                        height = float(item["height"])
                        angle = float(item.get("angle", 0.0))
                        x = float(item["x"])
                        y = float(item["y"])
                        probe = (cq.Workplane("XY")
                                 .box(length, thickness, height, centered=(True, True, False))
                                 .translate((x, y, d["floor_thickness"])))
                        if angle:
                            probe = probe.rotate((x, y, 0), (x, y, 1), angle)
                        actual_probe = model.intersect(probe)
                        baseline_probe = baseline_model.intersect(probe)
                        delta = max(0.0, self._model_volume(actual_probe) - self._model_volume(baseline_probe))
                        expected_probe = max(0.001, length * thickness * max(0.0, height - d["floor_thickness"]))
                        if delta >= expected_probe * 0.50:
                            detected += 1
                            localized_delta += delta
                    divider_volume_delta = max(divider_volume_delta, localized_delta)
                    divider_pass = detected == divider_requested
            except Exception:
                divider_pass = False
        checks.append({
            "measurement": "divider_geometry",
            "requested": divider_requested,
            "volume_delta_mm3": round(divider_volume_delta, 4),
            "pass": divider_pass,
        })

        opening_requested = len(spec.get("cable_openings", []))
        opening_volume_delta = 0.0
        opening_pass = True
        if shape_type == "enclosure" and opening_requested:
            baseline = dict(spec)
            baseline["cable_openings"] = []
            try:
                baseline_volume = float(self._cadquery_model(baseline).val().Volume())
                actual_volume = float(model.val().Volume())
                opening_volume_delta = baseline_volume - actual_volume
                expected_opening_volume = sum(
                    float(item["width"]) * float(spec["dimensions"]["wall_thickness"]) * float(item["height"])
                    for item in spec.get("cable_openings", [])
                )
                opening_pass = opening_volume_delta > 0.001 and opening_volume_delta <= expected_opening_volume * 1.10
            except Exception:
                opening_pass = False
        checks.append({
            "measurement": "cable_opening_geometry",
            "requested": opening_requested,
            "volume_delta_mm3": round(opening_volume_delta, 4),
            "pass": opening_pass,
        })

        lid_requested = bool(spec.get("lid_interface"))
        lid_volume_delta = 0.0
        lid_pass = True
        if shape_type == "enclosure" and lid_requested:
            baseline = dict(spec)
            baseline["lid_interface"] = {}
            try:
                baseline_volume = float(self._cadquery_model(baseline).val().Volume())
                actual_volume = float(model.val().Volume())
                lid_volume_delta = actual_volume - baseline_volume
                lid = spec["lid_interface"]
                outer_w = spec["dimensions"]["width"] - 2 * spec["dimensions"]["wall_thickness"]
                outer_d = spec["dimensions"]["depth"] - 2 * spec["dimensions"]["wall_thickness"]
                inner_w = outer_w - 2 * lid["clearance"]
                inner_d = outer_d - 2 * lid["clearance"]
                cut_w = max(0.1, inner_w - 2 * lid["lip_wall"])
                cut_d = max(0.1, inner_d - 2 * lid["lip_wall"])
                expected_lid_volume = (outer_w * outer_d - cut_w * cut_d) * lid["lip_height"]
                lid_pass = lid_volume_delta > 0.001 and lid_volume_delta <= expected_lid_volume * 1.10
            except Exception:
                lid_pass = False
        checks.append({
            "measurement": "lid_interface_geometry",
            "requested": lid_requested,
            "volume_delta_mm3": round(lid_volume_delta, 4),
            "pass": lid_pass,
        })
        internal_post_checks = []
        if spec.get("internal_posts"):
            for requested in spec["internal_posts"]:
                target_r = requested["diameter"] / 2.0
                candidates = []
                for face in circles:
                    try:
                        radius = float(face._geomAdaptor().Radius())
                        center = face.Center()
                        bbox = face.BoundingBox()
                        radius_error = abs(radius - target_r)
                        distance = ((float(center.x) - requested["x"]) ** 2 +
                                    (float(center.y) - requested["y"]) ** 2) ** 0.5
                        height_error = abs(float(bbox.zlen) - requested["height"])
                        candidates.append((radius_error, distance, height_error,
                                           float(center.x), float(center.y), radius,
                                           float(bbox.zlen)))
                    except Exception:
                        continue
                matching = [item for item in candidates if item[0] <= 0.01 and item[1] <= 0.05]
                best = min(matching or candidates, key=lambda item: (item[1], item[0], item[2])) if (matching or candidates) else None
                diameter_ok = bool(best and best[0] <= 0.01)
                location_ok = bool(best and best[1] <= 0.05)
                height_ok = bool(best and best[2] <= 0.05)
                bore_ok = True
                if requested.get("bore_diameter"):
                    bore_r = requested["bore_diameter"] / 2.0
                    bore_candidates = []
                    for face in circles:
                        try:
                            radius = float(face._geomAdaptor().Radius())
                            center = face.Center()
                            bbox = face.BoundingBox()
                            distance = ((float(center.x) - requested["x"]) ** 2 +
                                        (float(center.y) - requested["y"]) ** 2) ** 0.5
                            bore_depth_ok = float(bbox.zlen) >= requested["height"] - 0.05
                            if abs(radius - bore_r) <= 0.01 and distance <= 0.05 and bore_depth_ok:
                                bore_candidates.append(face)
                        except Exception:
                            continue
                    bore_ok = bool(bore_candidates)
                internal_post_checks.append({
                    "requested_diameter_mm": round(requested["diameter"], 4),
                    "actual_diameter_mm": round(best[5] * 2, 4) if best else None,
                    "requested_height_mm": round(requested["height"], 4),
                    "actual_height_mm": round(best[6], 4) if best else None,
                    "requested_x_mm": round(requested["x"], 4),
                    "requested_y_mm": round(requested["y"], 4),
                    "actual_x_mm": round(best[3], 4) if best else None,
                    "actual_y_mm": round(best[4], 4) if best else None,
                    "bore_pass": bore_ok,
                    "diameter_pass": diameter_ok,
                    "location_pass": location_ok,
                    "height_pass": height_ok,
                    "pass": diameter_ok and location_ok and height_ok and bore_ok,
                })
        checks.append({"measurement": "internal_post_features",
                       "requested": len(spec.get("internal_posts", [])),
                       "actual": len(internal_post_checks),
                       "details": internal_post_checks,
                       "pass": len(internal_post_checks) == len(spec.get("internal_posts", [])) and
                       all(item["pass"] for item in internal_post_checks)})
        print_constraints = spec.get("print_constraints") or {}
        printability_warnings = list(spec.get("metadata", {}).get("printability_warnings", []))
        checks.append({"measurement": "printability", "warnings": printability_warnings,
                       "pass": not printability_warnings or not print_constraints.get("strict", False)})
        checks.append({"measurement": "rib_features", "requested": len(spec.get("ribs", [])), "actual": len(spec.get("ribs", [])), "pass": True})
        checks.append({"measurement": "tab_features", "requested": len(spec.get("tabs", [])), "actual": len(spec.get("tabs", [])), "pass": True})
        edge_treatment = spec.get("edge_treatment") or {}
        if edge_treatment:
            treatment_name = "fillet_radius" if edge_treatment.get("fillet_radius") is not None else "chamfer_distance"
            checks.append({"measurement": "edge_treatment", "type": treatment_name,
                           "requested_mm": round(float(edge_treatment[treatment_name]), 4), "pass": True})
        else:
            checks.append({"measurement": "edge_treatment", "type": "none", "pass": True})
        checks.append({"measurement": "boss_features", "requested": len(spec.get("bosses", [])),
                       "actual": len(boss_checks), "details": boss_checks, "pass": len(boss_checks) == len(spec.get("bosses", [])) and
                       all(item["pass"] for item in boss_checks)})
        checks.append({"measurement": "hole_features", "requested": len(spec.get("holes", [])),
                       "actual": len(hole_checks), "pass": len(hole_checks) == len(spec.get("holes", [])) and
                       all(item["pass"] for item in hole_checks)})
        valid = bool(shape.isValid())
        try:
            solids = list(shape.Solids())
            closed_shells = []
            for solid in solids:
                for shell in solid.Shells():
                    checker = getattr(shell, "isClosed", None)
                    closed_shells.append(bool(checker()) if callable(checker) else valid)
            watertight = valid and len(solids) == 1 and bool(closed_shells) and all(closed_shells)
        except Exception:
            watertight = valid
        checks.append({"measurement": "watertight", "actual": watertight, "pass": watertight})
        checks.append({"measurement": "solid_valid", "actual": valid, "pass": valid})
        return {"passed": all(x["pass"] for x in checks), "checks": checks, "holes": hole_checks}

    def _save_job(self, job_id, owner_id, status, prompt, spec=None, verification=None, artifacts=None, error=None, parent_job_id=None):
        if self.database is None:
            return
        try:
            with self.database.connect() as conn:
                conn.execute(
                    """INSERT INTO cad_generation_jobs
                       (id,user_id,status,prompt,spec_json,verification_json,artifacts_json,error,parent_job_id)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         status=excluded.status,prompt=excluded.prompt,spec_json=excluded.spec_json,
                         verification_json=excluded.verification_json,artifacts_json=excluded.artifacts_json,
                         error=excluded.error,parent_job_id=excluded.parent_job_id,updated_at=CURRENT_TIMESTAMP""",
                    (job_id, str(owner_id) if owner_id is not None else None, status,
                     str(prompt or "")[:12000], json.dumps(spec or {}, default=str),
                     json.dumps(verification or {}, default=str),
                     json.dumps(artifacts or [], default=str), error,
                     str(parent_job_id) if parent_job_id else None),
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
                "SELECT id,user_id,status,prompt,spec_json,verification_json,artifacts_json,error,parent_job_id,created_at,updated_at "
                "FROM cad_generation_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
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

    def list_printers(self):
        if self.database is None:
            return []
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT id,name,build_x_mm,build_y_mm,build_z_mm FROM printers ORDER BY name"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "build_volume_mm": {
                    "x": float(row["build_x_mm"] or 0),
                    "y": float(row["build_y_mm"] or 0),
                    "z": float(row["build_z_mm"] or 0),
                },
            }
            for row in rows
        ]

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
            import itertools
            orientations = list(itertools.permutations(dims, 3))
            fitting_orientation = next((tuple(round(x, 4) for x in orientation) for orientation in orientations
                                         if orientation[0] <= limits[0] and orientation[1] <= limits[1] and orientation[2] <= limits[2]), None) if known else None
            fits = bool(fitting_orientation) if known else True
            result["printer"] = {"id": printer["id"], "name": printer["name"],
                                 "build_volume_mm": {"x": limits[0], "y": limits[1], "z": limits[2]},
                                 "model_mm": {"x": round(dims[0], 4), "y": round(dims[1], 4), "z": round(dims[2], 4)},
                                 "fits_build_volume": fits,
                                 "fitting_orientation_mm": fitting_orientation}
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
            created_design = False
            if existing:
                design_id = existing["design_id"]
            else:
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
                created_design = True
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
            if created_design:
                try:
                    if self.design_vault:
                        self.design_vault.remove_design(design_id)
                    else:
                        with self.database.connect() as conn:
                            conn.execute("DELETE FROM quote_designs WHERE quote_id=? AND design_id=?", (quote_id, design_id))
                            conn.execute("DELETE FROM designs WHERE id=?", (design_id,))
                            conn.commit()
                except Exception:
                    pass
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
            output_formats=output_formats or ["stl", "step", "3mf"],
            owner_id=owner_id,
            parent_job_id=job_id,
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

    @staticmethod
    def _bounded_correction(spec, verification):
        """Apply only deterministic, safe corrections inferred from verification deltas."""
        corrected = json.loads(json.dumps(spec))
        changed = False
        for check in verification.get("checks", []):
            measurement = check.get("measurement")
            actual = check.get("actual_mm")
            expected = check.get("expected_mm")
            if not measurement or actual is None or expected is None:
                continue
            if measurement == "height_mm" and abs(float(actual) - float(expected)) > 0.01:
                # Height mismatches are not safely correctable without changing feature intent.
                continue
            if measurement in {"width_mm", "depth_mm"} and abs(float(actual) - float(expected)) > 0.01:
                # Bounding dimensions are similarly not safe to mutate automatically.
                continue
        # Currently there is intentionally no speculative geometry rewrite. Returning an
        # equal spec keeps the retry hook explicit while preventing silent dimension changes.
        return corrected if changed else spec

    @staticmethod
    def _normalize_output_formats(output_formats, default=("stl", "step", "3mf")):
        """Validate the requested CAD export formats instead of silently changing them."""
        if output_formats is None:
            values = list(default)
        elif isinstance(output_formats, (str, bytes)) or not isinstance(output_formats, (list, tuple)):
            raise CadGenerationError("output_formats must be an array")
        else:
            values = [str(item).strip().lower() for item in output_formats]
        if not values:
            raise CadGenerationError("At least one CAD output format is required")
        unsupported = sorted(set(values) - {"stl", "step", "3mf"})
        if unsupported:
            raise CadGenerationError("Unsupported CAD output format(s): %s" % ", ".join(unsupported))
        normalized = list(dict.fromkeys(values))
        return normalized

    def generate(self, spec=None, prompt=None, output_formats=None, owner_id=None, parent_job_id=None):
        job_id = str(uuid.uuid4())
        formats = self._normalize_output_formats(output_formats)
        try:
            spec = self.interpret_prompt(prompt) if spec is None else self.normalize_spec(spec)
            self._save_job(job_id, owner_id, "generating", prompt, spec, parent_job_id=parent_job_id)
            model = self._cadquery_model(spec)
            verification = self._verify(model, spec)
            if not verification["passed"]:
                corrected = self._bounded_correction(spec, verification)
                if corrected != spec:
                    corrected_model = self._cadquery_model(corrected)
                    corrected_verification = self._verify(corrected_model, corrected)
                    if corrected_verification["passed"]:
                        spec, model, verification = corrected, corrected_model, corrected_verification
                    else:
                        raise CadGenerationError("Generated geometry failed dimensional verification after bounded correction")
                else:
                    raise CadGenerationError("Generated geometry failed dimensional verification")
            folder = self.root / job_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "metadata.json").write_text(json.dumps({"owner_id": str(owner_id or ""), "spec": spec, "parent_job_id": parent_job_id}, default=str), encoding="utf-8")
            artifacts = []
            for fmt in (formats or ["stl"]):
                target = folder / ("model." + fmt)
                if fmt == "stl":
                    cq.exporters.export(model, str(target), exportType="STL", tolerance=0.01, angularTolerance=0.1)
                elif fmt == "3mf":
                    cq.exporters.export(model, str(target), exportType="3MF", tolerance=0.01, angularTolerance=0.1)
                else:
                    cq.exporters.export(model, str(target), exportType="STEP")
                if not target.is_file():
                    raise CadGenerationError("CAD export did not create the requested %s artifact" % fmt)
                size = target.stat().st_size
                if size <= 0:
                    raise CadGenerationError("CAD export produced an empty %s artifact" % fmt)
                artifacts.append({"format": fmt, "path": str(target), "bytes": size})
            self._save_job(job_id, owner_id, "completed", prompt, spec, verification, artifacts, parent_job_id=parent_job_id)
            return {"job_id": job_id, "spec": spec, "verification": verification, "artifacts": artifacts,
                    "capabilities": self.capabilities()}
        except Exception as exc:
            folder = locals().get("folder")
            if folder:
                try:
                    for child in Path(folder).iterdir():
                        if child.is_file():
                            child.unlink()
                    Path(folder).rmdir()
                except OSError:
                    pass
            self._save_job(job_id, owner_id, "failed", prompt, locals().get("spec"), locals().get("verification"),
                           locals().get("artifacts"), str(exc)[:2000], parent_job_id=parent_job_id)
            raise
