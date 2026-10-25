"""Scripted sculpting with Blender's real sculpt brushes (extracted from Experiment 3, unchanged logic).

Requires a Blender GUI session: Blender 5.2.2 crashes when sculpt mode is entered with `-b`.
A Sculptor aims the 3D viewport at the surface (orthographic, facing it), ray-casts the stroke
path onto the current surface, sets the brush radius in pixels, submits the dabs with
`bpy.ops.sculpt.brush_stroke`, and repeats passes until the measured peak displacement reaches
the stroke's target depth (closed loop). Every stroke is appended to `log["strokes"]`.

Stroke spec: {"brush", "r" (m), "strength", "view" (direction the camera looks), "pts" (approximate
3D path), "mode" ("NORMAL"/"INVERT"), "label", "target" (mm or None), "passes", "sym"}
"""
import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import Vector as V
from mathutils.bvhtree import BVHTree


def view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                return win, area, next(r for r in area.regions if r.type == "WINDOW")
    raise RuntimeError("No VIEW_3D area: scripted sculpting needs the Blender GUI (not -b)")


def coords(me):
    a = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


# v1.3 stroke guard: a stroke's rays start 0.3 m outside along the view, so a part in front (a thigh in front of the
# groin) catches them and the crease lands on the wrong form. Skip a stroke whose surface hits are, at the median,
# further from its requested points than GUARD_RATIO x the brush radius (at least GUARD_MIN_M), and log it. Relative to
# the radius because big Smooth/Clay strokes are often placed on a limb's axis, inside it, and land harmlessly on its
# skin (dragon and Komodo: offset <= 2.3 r), while misplaced creases land 5-20 r away and cut the wrong form.
GUARD_RATIO = 4.0
GUARD_MIN_M = 0.01


def guard_skips(offset_m, radius):
    """True when a stroke whose median hit lies offset_m from its points should be skipped (see GUARD_RATIO)."""
    return offset_m > max(GUARD_RATIO * radius, GUARD_MIN_M)


def spec(brush, r, strength, view, pts, label, target=None, mode="NORMAL", passes=1, sym=True, guard=True):
    return {"brush": brush, "r": r, "strength": strength, "view": V(view).normalized(), "pts": pts, "mode": mode,
            "label": label, "target": target, "passes": passes, "sym": sym, "guard": guard}


def surface_hits(tree, pts, view, reach=0.3):
    """Ray-cast each stroke point along the view from `reach` outside; returns (hits, distances from the requested
    points). A large distance means another part in front caught the ray (see GUARD_RATIO)."""
    hits, offs = [], []
    for p in pts:
        p = V(p)
        loc, _, _, _ = tree.ray_cast(p - view * reach, view, reach * 2)
        if loc is not None:
            hits.append(loc)
            offs.append((loc - p).length)
    return hits, offs


class Sculptor:
    def __init__(self, ob, log):
        self.ob, self.log = ob, log
        self.log.setdefault("strokes", [])
        self.log.setdefault("filters", [])
        self.log.setdefault("errors", [])
        self.win, self.area, self.region = view3d()
        self.rv3d = self.area.spaces.active.region_3d
        self.phase = "?"
        space = self.area.spaces.active
        space.shading.type = "SOLID"
        space.overlay.show_overlays = False

    def ov(self):
        return dict(window=self.win, area=self.area, region=self.region, active_object=self.ob, object=self.ob)

    def mode(self, m):
        with bpy.context.temp_override(**self.ov()):
            bpy.ops.object.mode_set(mode=m)

    def bvh(self):
        return BVHTree.FromObject(self.ob, bpy.context.evaluated_depsgraph_get())

    def set_view(self, view_dir, center, dist=1.0):
        r = self.rv3d
        r.view_perspective = "ORTHO"
        r.view_location = center
        r.view_rotation = (-view_dir).to_track_quat("Z", "Y")
        r.view_distance = dist
        r.update()

    def filter(self, ftype, **kw):
        with bpy.context.temp_override(**self.ov()):
            res = bpy.ops.sculpt.mesh_filter(type=ftype, start_mouse=(self.region.width // 2, self.region.height // 2), **kw)
        self.log["filters"].append({"phase": self.phase, "type": ftype, **kw, "result": str(res)})

    def cavity_fillet(self, iterations=30, factor=2.5, blur=3):
        """Smooth only concave areas (blockout/fusion seams): cavity mask + Smooth filter."""
        with bpy.context.temp_override(**self.ov()):
            bpy.ops.sculpt.mask_from_cavity(factor=factor, blur_steps=blur)
        self.filter("SMOOTH", strength=1.0, iteration_count=iterations)
        with bpy.context.temp_override(**self.ov()):
            bpy.ops.paint.mask_flood_fill(mode="VALUE", value=0.0)

    def stroke(self, s):
        me = self.ob.data
        start = coords(me)
        strength, done, passes = s["strength"], 0.0, []
        max_passes = s["passes"] if s["target"] is None else 6
        for _ in range(max_passes):
            rec = self._pass(s["brush"], s["r"], strength, s["view"], s["pts"], s["mode"], s["sym"], s["label"],
                             guard=s.get("guard", True))
            passes.append(rec)
            if rec.get("max_disp_mm") is None:
                break
            done = float(np.linalg.norm(coords(me) - start, axis=1).max()) * 1000
            if s["target"] is None:
                continue
            if done >= 0.75 * s["target"]:
                break
            gain = (s["target"] - done) / max(rec["max_disp_mm"], 0.05)
            strength = min(1.0, strength * min(max(gain, 1.0), 3.0))
        self.log["strokes"].append({"phase": self.phase, "label": s["label"], "brush": s["brush"], "radius": s["r"],
                                    "mode": s["mode"], "target_mm": s["target"], "passes": len(passes),
                                    "final_strength": round(strength, 3), "achieved_mm": round(done, 2),
                                    "dabs": passes[0].get("dabs"), "px_size": passes[0].get("px_size"),
                                    "hit_offset_mm": passes[0].get("hit_offset_mm"), "result": passes[-1].get("result")})
        if str(passes[0].get("result", "")).startswith("skipped"):
            self.log.setdefault("strokes_skipped", []).append((s["label"], passes[0]["result"]))

    def _pass(self, brush, radius, strength, view, points, mode="NORMAL", sym=True, label="", reach=0.3, guard=True):
        me = self.ob.data
        tree = self.bvh()
        pts = [V(p) for p in points]
        dense = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            n = max(1, int((b - a).length / max(radius * 0.30, 0.0015)))
            dense += [a.lerp(b, (i + 1) / n) for i in range(n)]
        if len(dense) == 1:
            dense = [dense[0]] * 4
        hits, offs = surface_hits(tree, dense, view, reach)
        rec = {"strength": strength, "dabs": len(hits), "requested": len(dense)}
        if not hits:
            rec["result"] = "no surface hit"
            return rec
        rec["hit_offset_mm"] = round(float(np.median(offs)) * 1000, 1)
        if guard and guard_skips(rec["hit_offset_mm"] / 1000, radius):
            rec["result"] = ("skipped: surface hit %.0f mm (%.1f x radius) from the requested points (another part in front?)"
                             % (rec["hit_offset_mm"], rec["hit_offset_mm"] / 1000 / radius))
            return rec
        center = sum(hits, V()) / len(hits)
        extent = max((h - center).length for h in hits)
        self.set_view(view, center, dist=max(radius * 20.0, extent * 2.2, 0.08))
        right = self.rv3d.view_rotation @ V((1, 0, 0))
        p0 = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, center)
        p1 = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, center + right * 0.1)
        px = radius * (p1 - p0).length / 0.1
        elems = []
        for i, h in enumerate(hits):
            m = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, h)
            if m is not None:
                elems.append({"name": "", "location": h, "mouse": m, "mouse_event": m, "pressure": 1.0, "size": px,
                              "time": i * 0.01, "is_start": i == 0, "x_tilt": 0.0, "y_tilt": 0.0})
        ts = bpy.context.tool_settings
        ts.sculpt.use_symmetry_x = sym
        me.use_mirror_x = sym
        before = coords(me)
        with bpy.context.temp_override(**self.ov()):
            bpy.ops.brush.asset_activate(asset_library_type="ESSENTIALS",
                                         relative_asset_identifier=f"brushes/essentials_brushes-mesh_sculpt.blend/Brush/{brush}")
            br = ts.sculpt.brush
            if br is None or br.name != brush:  # never sculpt with the wrong brush silently
                rec["result"] = f"brush activation failed (active: {br.name if br else None})"
                self.log["errors"].append(rec["result"] + f" for {label}")
                return rec
            br.strength = strength
            ups = ts.sculpt.unified_paint_settings
            ups.use_unified_size = False
            ups.use_unified_strength = False
            br.use_locked_size = "VIEW"
            br.size = max(2, int(round(px)))  # the stroke element "size" alone does not set the radius
            res = bpy.ops.sculpt.brush_stroke(stroke=elems, mode=mode)
        disp = np.linalg.norm(coords(me) - before, axis=1)
        rec.update(result=str(res), px_size=round(px, 1), verts_moved=int((disp > 1e-4).sum()),
                   max_disp_mm=round(float(disp.max()) * 1000, 2))
        return rec
