"""Experiment 3 - Sculpting workflow driven by script, using Blender's real sculpt mode.

Pipeline
  Phase 0  Blockout: ellipsoid / capsule masses (clay-blocking), fused into ONE shell by Voxel Remesh.
  Phase 1  Primary forms: cavity-masked Smooth filter (fillets the blockout seams), Surface Smooth filter,
           then brush strokes (Inflate/Deflate, Clay Strips, Flatten/Contrast, Smooth) on chest, waist,
           hips, skull and neck.
  Phase 2  Secondary forms: brow ridges, eye sockets, eyelid crease, nostrils, mouth/jaw line, cheekbones,
           neck/shoulder/pectoral/thigh/calf muscle groups, elbow/knee/heel knobs, wing joints.
  Phase 3  Tertiary (restrained): ventral scutes on throat and belly, neck folds, dorsal ridge pinch.
  Phase 4  Mesh preparation study (separate script mesh_prep.py, background mode): QuadriFlow retopology,
           Decimate, Multires re-projection, deviation measurements.
  Inserts  (NOT sculpted, procedural, disclosed): eyeballs, horns, dorsal spikes, claws, wing membranes.

Every stroke is a real `bpy.ops.sculpt.brush_stroke` call with an Essentials brush asset. The script
positions the 3D viewport like a sculptor would (orthographic view facing the surface), ray-casts the
stroke path onto the current surface, converts world radius to screen pixels and submits the dabs.

Requires the Blender GUI: in Blender 5.2.2, entering sculpt mode with `-b` crashes (access violation).
Run:  blender --factory-startup --window-geometry 0 0 1400 1000 --python dragon_sculpt.py
The script runs from a timer, saves its outputs and quits Blender by itself.
"""
import json
import math
import os
import sys
import time
import traceback

T_START = time.perf_counter()

import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from bpy_extras import view3d_utils  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402
import material_palette as mp  # noqa: E402
import proc_mesh as pm  # noqa: E402

SCRIPT_REVISION = 3  # rev 2: brush px size, closed-loop passes, smooth shading, seam fillet; rev 3: eye ref, Clay + polish, belly blend
VOXEL = 0.005

OUT_BLEND = os.path.join(HERE, "dragon_sculpt.blend")

PHASE_DIR = os.path.join(HERE, "phases")
V = Vector
LOG = {"experiment": "03_sculpting", "script_revision": SCRIPT_REVISION, "blender": bpy.app.version_string,
       "voxel_size": VOXEL, "phases": [], "strokes": [], "filters": [], "errors": []}


def rad(d):
    return math.radians(d)


def dirn(*v):
    return V(v).normalized()


def mx(p, s):
    return V((p[0] * s, p[1], p[2]))


SIDE, FRONT, TOP, BELOW, BACK = dirn(-1, 0, 0), dirn(0, 1, 0), dirn(0, 0, -1), dirn(0, 0, 1), dirn(0, -1, 0)

# =========================================================================== skeleton / landmarks (left side, x > 0)
NECK = [(0, -0.42, 0.77), (0, -0.57, 0.88), (0, -0.635, 1.01), (0, -0.70, 1.12), (0, -0.77, 1.18)]
NECK_R = [0.15, 0.115, 0.09, 0.08, 0.075]
TAIL = [(0, 0.50, 0.66), (0, 0.78, 0.58), (0.06, 1.06, 0.43), (0.16, 1.32, 0.28), (0.25, 1.54, 0.18), (0.30, 1.72, 0.13)]
TAIL_R = [0.14, 0.10, 0.068, 0.044, 0.024, 0.005]
F_S, F_E, F_W, F_PAW = V((0.20, -0.31, 0.57)), V((0.245, -0.21, 0.33)), V((0.25, -0.325, 0.10)), V((0.25, -0.37, 0.035))
H_H, H_K, H_A, H_F, H_PAW = V((0.19, 0.40, 0.60)), V((0.25, 0.25, 0.37)), V((0.25, 0.47, 0.17)), V((0.25, 0.385, 0.05)), V((0.25, 0.35, 0.035))
W_ROOT, W_B, W_E, W_W = V((0.10, -0.20, 0.80)), V((0.15, -0.18, 0.88)), V((0.48, 0.02, 1.10)), V((0.86, -0.26, 1.40))
W_TIPS = [V((1.32, -0.08, 1.52)), V((1.30, 0.30, 1.10)), V((1.04, 0.56, 0.86)), V((0.66, 0.60, 0.80))]
TOE_TIPS = []  # (tip, direction, radius) for claws, left side


def finger_mid(T):
    return W_W.lerp(T, 0.5) + dirn(0.0, 0.3, -0.5) * 0.022


# =========================================================================== Phase 0: blockout
def bo_ellipsoid(bm, c, radii, rot=(0, 0, 0), segs=32, rings=16):
    m = Matrix.Translation(c) @ Euler(rot).to_matrix().to_4x4() @ Matrix.Diagonal((*radii, 1.0))
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=1.0, matrix=m)


def bo_capsule(bm, p0, p1, r0, r1, segs=20):
    p0, p1 = V(p0), V(p1)
    d = p1 - p0
    m = Matrix.Translation((p0 + p1) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r0, radius2=r1, depth=d.length, matrix=m)
    bo_ellipsoid(bm, p0, (r0, r0, r0), segs=segs, rings=segs // 2)
    bo_ellipsoid(bm, p1, (r1, r1, r1), segs=segs, rings=segs // 2)


def bo_chain(bm, pts, radii, segs=20):
    for a, b, ra, rb in zip(pts, pts[1:], radii, radii[1:]):
        bo_capsule(bm, a, b, ra, rb, segs)


def bo_along(bm, p0, p1, r_lat, r_perp, extend=0.0):
    p0, p1 = V(p0), V(p1)
    d = p1 - p0
    m = Matrix.Translation((p0 + p1) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4() @ Matrix.Diagonal((r_lat, r_perp, d.length / 2 + extend, 1.0))
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=1.0, matrix=m)


def build_blockout():
    bm = bmesh.new()
    # torso masses
    bo_ellipsoid(bm, (0, -0.30, 0.67), (0.21, 0.30, 0.25), rot=(rad(-10), 0, 0), segs=48, rings=24)   # chest
    bo_ellipsoid(bm, (0, 0.05, 0.625), (0.165, 0.30, 0.19), segs=48, rings=24)                          # abdomen
    bo_ellipsoid(bm, (0, 0.36, 0.66), (0.185, 0.24, 0.205), rot=(rad(6), 0, 0), segs=48, rings=24)     # hips
    bo_chain(bm, NECK, NECK_R, segs=28)
    bo_chain(bm, TAIL, TAIL_R, segs=24)
    # head masses
    bo_ellipsoid(bm, (0, -0.83, 1.225), (0.098, 0.115, 0.09), segs=40, rings=20)                       # cranium
    bo_ellipsoid(bm, (0, -1.00, 1.19), (0.060, 0.16, 0.052), rot=(rad(6), 0, 0), segs=40, rings=20)     # muzzle
    bo_ellipsoid(bm, (0, -1.115, 1.20), (0.045, 0.05, 0.04), segs=24, rings=12)                        # nose pad
    bo_ellipsoid(bm, (0, -0.955, 1.14), (0.052, 0.13, 0.03), rot=(rad(10), 0, 0), segs=32, rings=16)    # lower jaw
    for s in (1, -1):
        bo_ellipsoid(bm, mx((0.06, -0.84, 1.16), s), (0.045, 0.06, 0.05), segs=24, rings=12)          # jaw angle
        bo_ellipsoid(bm, mx((0.16, -0.30, 0.62), s), (0.09, 0.13, 0.14), segs=32, rings=16)           # shoulder mass
        # front leg
        bo_along(bm, mx(F_S, s), mx(F_E, s), 0.07, 0.08, extend=0.03)
        bo_chain(bm, [mx(F_S, s), mx(F_E, s), mx(F_W, s)], [0.075, 0.052, 0.034])
        # hind leg
        bo_along(bm, mx(H_H, s), mx(H_K, s), 0.095, 0.12, extend=0.06)
        bo_chain(bm, [mx(H_H, s), mx(H_K, s), mx(H_A, s), mx(H_F, s)], [0.095, 0.06, 0.04, 0.034])
        for paw, fa, toe_len, back in ((F_PAW, 8, 0.065, False), (H_PAW, 6, 0.072, True)):
            c = mx(paw, s)
            bo_ellipsoid(bm, c, (0.058, 0.08, 0.03), segs=24, rings=12)
            fwd = V((s * math.sin(rad(fa)), -math.cos(rad(fa)), 0))
            dirs = [Matrix.Rotation(rad(a * s), 3, "Z") @ fwd for a in (-26, 0, 26)]
            if back:
                dirs.append(Matrix.Rotation(rad(12 * s), 3, "Z") @ -fwd)
            for d in dirs:
                ln = toe_len * (0.55 if d.dot(fwd) < 0 else 1.0)
                tip = c + d * ln + V((0, 0, -0.008))
                bo_capsule(bm, c + d * 0.02, tip, 0.02, 0.015, segs=12)
                if s == 1:
                    TOE_TIPS.append((tip, d, 0.013))
        # wing frame
        bo_along(bm, mx(W_ROOT, s), mx(W_E, s), 0.055, 0.06, extend=-0.12)
        bo_chain(bm, [mx(W_ROOT, s), mx(W_B, s), mx(W_E, s), mx(W_W, s)], [0.055, 0.05, 0.034, 0.026], segs=16)
        bo_ellipsoid(bm, mx(W_W, s), (0.03, 0.03, 0.03), segs=16, rings=8)
        for T in W_TIPS:
            bo_chain(bm, [mx(W_W, s), mx(finger_mid(T), s), mx(T, s)], [0.019, 0.015, 0.008], segs=12)
    return bm


# =========================================================================== sculpt driver
def view3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                return win, area, next(r for r in area.regions if r.type == "WINDOW")
    raise RuntimeError("No VIEW_3D area: this script needs the Blender GUI (not -b)")


def coords(me):
    a = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


class Sculptor:
    def __init__(self, ob):
        self.ob = ob
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
        LOG["filters"].append({"phase": self.phase, "type": ftype, **kw, "result": str(res)})

    def stroke(self, spec):
        """Closed-loop stroke: repeat passes (like an artist going over an area again) until the
        measured peak displacement reaches spec['target'] mm, adapting strength between passes."""
        me = self.ob.data
        start = coords(me)
        strength, done, passes = spec["strength"], 0.0, []
        max_passes = spec["passes"] if spec["target"] is None else 6
        for _ in range(max_passes):
            rec = self._pass(spec["brush"], spec["r"], strength, spec["view"], spec["pts"], spec["mode"], spec["sym"], spec["label"])
            passes.append(rec)
            if rec.get("max_disp_mm") is None:
                break
            done = float(np.linalg.norm(coords(me) - start, axis=1).max()) * 1000
            if spec["target"] is None:
                continue  # fixed number of passes
            if done >= 0.75 * spec["target"]:
                break
            gain = (spec["target"] - done) / max(rec["max_disp_mm"], 0.05)
            strength = min(1.0, strength * min(max(gain, 1.0), 3.0))
        LOG["strokes"].append({"phase": self.phase, "label": spec["label"], "brush": spec["brush"], "radius": spec["r"],
                               "mode": spec["mode"], "target_mm": spec["target"], "passes": len(passes),
                               "final_strength": round(strength, 3), "achieved_mm": round(done, 2),
                               "dabs": passes[0].get("dabs"), "px_size": passes[0].get("px_size"),
                               "verts_moved_last_pass": passes[-1].get("verts_moved"), "result": passes[-1].get("result")})

    def _pass(self, brush, radius, strength, view, points, mode="NORMAL", sym=True, label="", reach=0.3):
        view = V(view).normalized()
        me = self.ob.data
        tree = self.bvh()
        pts = [V(p) for p in points]
        # densify the path (dab spacing ~ 30% of radius)
        dense = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            n = max(1, int((b - a).length / max(radius * 0.30, 0.0015)))
            dense += [a.lerp(b, (i + 1) / n) for i in range(n)]
        if len(dense) == 1:
            dense = [dense[0]] * 4
        hits = []
        for p in dense:
            loc, _, _, dist = tree.ray_cast(p - view * reach, view, reach * 2)
            if loc is not None:
                hits.append(loc)
        rec = {"strength": strength, "dabs": len(hits), "requested": len(dense)}
        if not hits:
            rec["result"] = "no surface hit"
            return rec
        center = sum(hits, V()) / len(hits)
        extent = max((h - center).length for h in hits)
        # zoom so the brush is ~40 px wide in screen space while the whole path stays in view
        self.set_view(view, center, dist=max(radius * 20.0, extent * 2.2, 0.08))
        right = self.rv3d.view_rotation @ V((1, 0, 0))
        p0 = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, center)
        p1 = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, center + right * 0.1)
        px = radius * (p1 - p0).length / 0.1
        elems = []
        for i, h in enumerate(hits):
            m = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, h)
            if m is None:
                continue
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
                LOG["errors"].append(rec["result"] + f" for {label}")
                return rec
            br.strength = strength
            # rev 1 finding: the stroke element "size" alone does not set the brush radius;
            # set the brush (and disable unified) size explicitly in pixels
            ups = ts.sculpt.unified_paint_settings
            ups.use_unified_size = False
            ups.use_unified_strength = False
            br.use_locked_size = "VIEW"
            br.size = max(2, int(round(px)))
            res = bpy.ops.sculpt.brush_stroke(stroke=elems, mode=mode)
        disp = np.linalg.norm(coords(me) - before, axis=1)
        rec.update(result=str(res), px_size=round(px, 1), verts_moved=int((disp > 1e-4).sum()),
                   max_disp_mm=round(float(disp.max()) * 1000, 2))
        return rec


# =========================================================================== stroke programme
def scutes():
    out = []
    for z in np.arange(0.88, 1.10, 0.035):   # throat (seen from the front)
        t = (z - 0.77) / (1.18 - 0.77)
        y = -0.57 - 0.2 * t
        out.append(([(0.0, y - 0.3, z), (0.045, y - 0.3, z)], FRONT))
    for y in np.arange(-0.55, 0.32, 0.05):   # chest and belly (seen from below)
        w = 0.12 if y < 0.0 else 0.10
        out.append(([(0.0, y, 0.3), (w, y, 0.3)], BELOW))
    return out


PHASE1 = [
    ("Smooth", 0.06, 0.6, FRONT, [(0.0, -0.58, 0.80), (0.10, -0.52, 0.84)], "NORMAL", "neck-chest junction"),
    ("Smooth", 0.05, 0.6, SIDE, [(0.24, -0.40, 0.60), (0.25, -0.30, 0.66), (0.24, -0.22, 0.60)], "NORMAL", "shoulder junction"),
    ("Smooth", 0.06, 0.6, SIDE, [(0.20, 0.30, 0.72), (0.22, 0.42, 0.74), (0.22, 0.52, 0.66)], "NORMAL", "thigh junction"),
    ("Smooth", 0.045, 0.6, TOP, [(0.12, -0.26, 0.86), (0.17, -0.18, 0.90), (0.12, -0.10, 0.86)], "NORMAL", "wing root junction"),
    ("Smooth", 0.05, 0.6, dirn(-1, 0.3, -0.3), [(0.07, -0.76, 1.14), (0.06, -0.72, 1.20)], "NORMAL", "neck-skull junction"),
    ("Inflate/Deflate", 0.08, 0.30, dirn(-0.3, 1, -0.2), [(0.06, -0.60, 0.62), (0.13, -0.55, 0.58)], "NORMAL", "chest fullness"),
    ("Inflate/Deflate", 0.07, 0.30, SIDE, [(0.17, -0.02, 0.66), (0.17, 0.14, 0.66)], "INVERT", "narrow waist"),
    ("Clay", 0.05, 0.40, dirn(-0.5, 0, -1), [(0.10, 0.24, 0.84), (0.13, 0.42, 0.82)], "NORMAL", "hip crest"),
    ("Flatten/Contrast", 0.045, 0.40, TOP, [(0.0, -1.10, 1.25), (0.0, -0.95, 1.27)], "NORMAL", "muzzle top plane"),
    ("Inflate/Deflate", 0.04, 0.30, SIDE, [(0.09, -0.86, 1.19), (0.09, -0.80, 1.19)], "NORMAL", "skull width at jaw angle"),
    ("Clay", 0.04, 0.35, dirn(-1, 0.3, -0.6), [(0.05, -0.72, 1.17), (0.06, -0.62, 1.04), (0.08, -0.52, 0.90)], "NORMAL", "neck dorsal muscle"),
]

PHASE2 = [
    ("Clay Strips", 0.018, 0.60, dirn(-0.6, 0.6, -0.5), [(0.035, -0.96, 1.275), (0.065, -0.925, 1.27), (0.085, -0.885, 1.26)], "NORMAL", "brow ridge"),
    ("Draw", 0.020, 0.50, dirn(-0.85, 0.45, -0.15), [(0.08, -0.905, 1.235)], "INVERT", "eye socket"),
    ("Crease Sharp", 0.008, 0.35, dirn(-0.85, 0.45, -0.15), [(0.07, -0.925, 1.255), (0.085, -0.905, 1.258), (0.095, -0.885, 1.25)], "NORMAL", "upper lid crease"),
    ("Draw", 0.009, 0.50, dirn(-0.3, 0.8, -0.5), [(0.022, -1.14, 1.225)], "INVERT", "nostril"),
    ("Crease Sharp", 0.012, 0.50, SIDE, [(0.04, -1.135, 1.168), (0.05, -1.06, 1.163), (0.06, -0.98, 1.162), (0.07, -0.90, 1.165), (0.075, -0.86, 1.17)], "NORMAL", "mouth line"),
    ("Clay Strips", 0.015, 0.45, SIDE, [(0.085, -0.94, 1.20), (0.095, -0.86, 1.20), (0.09, -0.80, 1.19)], "NORMAL", "cheekbone"),
    ("Crease Sharp", 0.012, 0.40, dirn(-1, 0, 0.35), [(0.06, -0.87, 1.12), (0.07, -0.80, 1.13)], "NORMAL", "jaw angle"),
    ("Clay", 0.025, 0.45, SIDE, [(0.07, -0.76, 1.12), (0.08, -0.66, 1.00), (0.10, -0.56, 0.86), (0.13, -0.47, 0.76)], "NORMAL", "neck muscle"),
    ("Clay", 0.035, 0.45, dirn(-0.4, 1, 0), [(0.04, -0.60, 0.60), (0.11, -0.56, 0.56), (0.16, -0.48, 0.52)], "NORMAL", "pectoral"),
    ("Clay", 0.035, 0.45, SIDE, [(0.22, -0.40, 0.62), (0.25, -0.31, 0.62), (0.24, -0.22, 0.56)], "NORMAL", "deltoid"),
    ("Clay", 0.030, 0.35, TOP, [(0.10, -0.40, 0.90), (0.13, -0.28, 0.92), (0.14, -0.18, 0.90)], "NORMAL", "scapula"),
    ("Clay", 0.018, 0.25, SIDE, [(0.20, -0.20, 0.75), (0.19, -0.12, 0.55)], "NORMAL", "rib 1"),
    ("Clay", 0.018, 0.25, SIDE, [(0.19, -0.10, 0.76), (0.18, -0.02, 0.57)], "NORMAL", "rib 2"),
    ("Clay", 0.018, 0.25, SIDE, [(0.18, 0.00, 0.76), (0.17, 0.08, 0.58)], "NORMAL", "rib 3"),
    ("Clay", 0.035, 0.45, SIDE, [(0.27, 0.30, 0.58), (0.29, 0.27, 0.48), (0.28, 0.26, 0.40)], "NORMAL", "quadriceps"),
    ("Clay", 0.030, 0.40, dirn(-1, -0.4, 0), [(0.25, 0.50, 0.62), (0.27, 0.45, 0.48)], "NORMAL", "hamstring"),
    ("Blob", 0.025, 0.50, dirn(-0.6, -0.8, 0), [(0.25, -0.17, 0.33)], "NORMAL", "elbow"),
    ("Blob", 0.028, 0.40, dirn(-0.6, 0.8, 0), [(0.26, 0.22, 0.37)], "NORMAL", "knee"),
    ("Blob", 0.022, 0.50, dirn(-0.6, -0.8, 0), [(0.26, 0.50, 0.17)], "NORMAL", "heel"),
    ("Clay", 0.022, 0.35, SIDE, [(0.27, -0.22, 0.30), (0.27, -0.28, 0.18)], "NORMAL", "forearm"),
    ("Clay", 0.025, 0.35, dirn(-1, -0.3, 0), [(0.27, 0.30, 0.32), (0.27, 0.38, 0.24)], "NORMAL", "calf"),
    ("Inflate/Deflate", 0.040, 0.30, TOP, [(0.15, -0.19, 0.90)], "NORMAL", "wing shoulder"),
    ("Blob", 0.025, 0.40, dirn(0, -0.5, -1), [(0.48, 0.02, 1.10)], "NORMAL", "wing elbow"),
    ("Blob", 0.022, 0.40, TOP, [(0.86, -0.26, 1.40)], "NORMAL", "wing wrist"),
    ("Clay", 0.030, 0.35, TOP, [(0.04, 0.52, 0.80), (0.04, 0.70, 0.68)], "NORMAL", "tail root muscle"),
]

# rev 3: polish pass over the muscle areas (softens stroke edges and remaining blockout seams)
PHASE2_POLISH = [
    ("Smooth", 0.06, 0.35, dirn(-0.4, 1, 0), [(0.03, -0.62, 0.66), (0.12, -0.56, 0.58), (0.18, -0.46, 0.52)], "NORMAL", "polish chest"),
    ("Smooth", 0.06, 0.35, SIDE, [(0.21, -0.36, 0.72), (0.20, -0.14, 0.70), (0.18, 0.08, 0.68)], "NORMAL", "polish flank"),
    ("Smooth", 0.05, 0.35, SIDE, [(0.27, 0.34, 0.62), (0.28, 0.28, 0.48), (0.28, 0.26, 0.38)], "NORMAL", "polish thigh"),
    ("Smooth", 0.04, 0.35, SIDE, [(0.24, -0.36, 0.60), (0.25, -0.26, 0.46), (0.26, -0.22, 0.34)], "NORMAL", "polish upper arm"),
    ("Smooth", 0.04, 0.35, SIDE, [(0.07, -0.74, 1.12), (0.09, -0.62, 0.96), (0.12, -0.50, 0.80)], "NORMAL", "polish neck"),
    ("Smooth", 0.06, 0.35, TOP, [(0.08, -0.40, 0.90), (0.10, -0.10, 0.86), (0.10, 0.30, 0.86)], "NORMAL", "polish back"),
]

PHASE3 = [("Crease Sharp", 0.006, 0.20, v, pts, "NORMAL", "ventral scute") for pts, v in scutes()] + [
    ("Crease Sharp", 0.006, 0.25, SIDE, [(0.07, -0.70, 1.10), (0.075, -0.66, 1.06), (0.07, -0.63, 1.03)], "NORMAL", "neck fold 1"),
    ("Crease Sharp", 0.006, 0.25, SIDE, [(0.075, -0.68, 1.04), (0.08, -0.64, 1.00), (0.075, -0.61, 0.97)], "NORMAL", "neck fold 2"),
    ("Pinch/Magnify", 0.020, 0.30, TOP, [(0.0, -0.45, 0.95), (0.0, -0.10, 0.90), (0.0, 0.25, 0.90), (0.0, 0.50, 0.84)], "NORMAL", "dorsal ridge"),
]

# rev 2: intended peak depth per stroke in mm (closed loop) or (None, fixed passes)
TARGETS = {
    "neck-chest junction": (None, 3), "shoulder junction": (None, 3), "thigh junction": (None, 3),
    "wing root junction": (None, 3), "neck-skull junction": (None, 3),
    "chest fullness": (8, 0), "narrow waist": (10, 0), "hip crest": (6, 0), "muzzle top plane": (4, 0),
    "skull width at jaw angle": (6, 0), "neck dorsal muscle": (5, 0),
    "brow ridge": (7, 0), "eye socket": (8, 0), "upper lid crease": (2, 0), "nostril": (4, 0), "mouth line": (4, 0),
    "cheekbone": (4, 0), "jaw angle": (3, 0), "neck muscle": (4, 0), "pectoral": (6, 0), "deltoid": (6, 0),
    "scapula": (4, 0), "rib 1": (2.5, 0), "rib 2": (2.5, 0), "rib 3": (2.5, 0), "quadriceps": (7, 0),
    "hamstring": (5, 0), "elbow": (6, 0), "knee": (6, 0), "heel": (6, 0), "forearm": (4, 0), "calf": (4, 0),
    "wing shoulder": (4, 0), "wing elbow": (5, 0), "wing wrist": (5, 0), "tail root muscle": (4, 0),
    "ventral scute": (1.5, 0), "neck fold 1": (2, 0), "neck fold 2": (2, 0), "dorsal ridge": (3, 0),
    "polish chest": (None, 2), "polish flank": (None, 2), "polish thigh": (None, 2),
    "polish upper arm": (None, 2), "polish neck": (None, 2), "polish back": (None, 2),
}
EYE_TARGET, EYE_VIEW = V((0.08, -0.905, 1.235)), dirn(-0.85, 0.45, -0.15)
EYE_REF = []  # surface point + normal at the eye BEFORE the socket is carved (rev 3)


def spec(t):
    brush, r, st, view, pts, mode, label = t
    target, passes = TARGETS.get(label, (None, 1))
    return {"brush": brush, "r": r, "strength": st, "view": view, "pts": pts, "mode": mode, "label": label,
            "target": target, "passes": max(passes, 1), "sym": True}


# =========================================================================== materials (belly) on a voxel mesh
SPINE_HEAD_TO_TAIL = [(0, -1.12, 1.18), (0, -0.98, 1.17), (0, -0.84, 1.18)] + list(reversed(NECK)) + \
    [(0, -0.30, 0.67), (0, 0.05, 0.63), (0, 0.36, 0.66)] + TAIL
LIMB_SEGS = []
for s in (1, -1):
    for chain in ([F_S, F_E, F_W, F_PAW], [H_H, H_K, H_A, H_F, H_PAW], [W_ROOT, W_B, W_E, W_W]):
        LIMB_SEGS += [(mx(a, s), mx(b, s)) for a, b in zip(chain, chain[1:])]
    LIMB_SEGS += [(mx(W_W, s), mx(T, s)) for T in W_TIPS]


def seg_dist(c, a, b):
    ab = b - a
    t = np.clip(((c - a) @ ab) / (ab @ ab), 0, 1)
    p = a + t[:, None] * ab
    return np.linalg.norm(c - p, axis=1), p


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def assign_belly(ob, half_deg=50):
    """rev 3: smooth per-vertex belly weight ("belly_w") blended in one palette material.
    Per-face assignment on a voxel mesh produced a visible staircase boundary in rev 2."""
    me = ob.data
    me.materials.clear()
    me.materials.append(mp.get_blend_material("skin", "belly", "belly_w"))
    me.polygons.foreach_set("material_index", np.zeros(len(me.polygons), np.int32))
    c = coords(me)
    n = len(c)
    spine = [np.array(p, float) for p, _ in pm.Path(SPINE_HEAD_TO_TAIL).samples[::6]]
    best = np.full(n, 1e9)
    vdot = np.zeros(n)
    for a, b in zip(spine, spine[1:]):
        d, p = seg_dist(c, a, b)
        t = (b - a) / np.linalg.norm(b - a)
        side = np.cross(t, [0, 0, 1.0])
        side /= np.linalg.norm(side)
        ventral = np.cross(t, side)
        r = c - p
        r -= np.outer(r @ t, t)
        r /= np.maximum(np.linalg.norm(r, axis=1), 1e-9)[:, None]
        closer = d < best
        best = np.where(closer, d, best)
        vdot = np.where(closer, r @ ventral, vdot)
    limb = np.full(n, 1e9)
    for a, b in LIMB_SEGS:
        d, _ = seg_dist(c, np.array(a, float), np.array(b, float))
        limb = np.minimum(limb, d)
    w = smoothstep(math.cos(rad(half_deg + 7)), math.cos(rad(half_deg - 7)), vdot)
    w *= 1.0 - smoothstep(0.8, 0.95, best / np.maximum(limb, 1e-9))
    attr = me.attributes.get("belly_w") or me.attributes.new("belly_w", "FLOAT", "POINT")
    attr.data.foreach_set("value", w.astype(np.float32))
    return int((w > 0.5).sum())


# =========================================================================== inserts (procedural, not sculpted)
def build_inserts(collection, parent, surface_bvh):
    def hit(origin, direction):
        loc, nrm, _, _ = surface_bvh.ray_cast(V(origin) - V(direction) * 0.4, V(direction), 1.0)
        if loc is None:
            raise RuntimeError(f"insert placement missed at {origin}")
        nrm = nrm if nrm.dot(direction) < 0 else -nrm
        return loc, nrm

    eyes = pm.Part("DRG_Eyes")
    # rev 3: place the eyeball relative to the surface as it was BEFORE the socket was carved,
    # so its front sits 3 mm proud of the original skin inside the socket (rev 2 eye was buried)
    ep, en = EYE_REF if EYE_REF else hit(EYE_TARGET, EYE_VIEW)
    eye_r = 0.02
    c = ep - en * (eye_r - 0.003)
    eyes.sphere(c, eye_r, "eye")
    up = (pm.Z - en * en.dot(pm.Z)).normalized()
    eyes.ellipsoid_axes(c + en * (eye_r - 0.0015), en * 0.003, up.cross(en) * 0.0055, up * 0.015, "pupil")

    horns = pm.Part("DRG_Horns")
    radii = [0.030, 0.026, 0.019, 0.012, 0.006, 0.001]
    horns.sweep([(0.042, -0.80, 1.25), (0.058, -0.755, 1.315), (0.083, -0.67, 1.352), (0.103, -0.575, 1.36),
                 (0.115, -0.495, 1.335), (0.119, -0.45, 1.295)], [(r * 0.85, r, r, 2.0) for r in radii], "horn", N=14, step=0.006,
                scale_fn=lambda s, L: 1.0 + 0.07 * max(0.0, math.sin(2 * math.pi * s / 0.028)) ** 2 * max(0.0, 1 - s / (0.75 * L)), tip=1.0)

    spikes = pm.Part("DRG_DorsalSpikes")
    spine = pm.Path(list(reversed(NECK)) + [(0, -0.30, 0.72), (0, 0.05, 0.66), (0, 0.36, 0.70)] + TAIL)
    sizes = [(0.0, 0.026), (0.12, 0.04), (0.25, 0.066), (0.42, 0.062), (0.6, 0.046), (0.92, 0.014)]
    s_pos, n_spk = 0.06, 0
    while s_pos < spine.length * 0.92:
        p, t, _ = spine.at(s_pos)
        side = t.cross(pm.Z).normalized()
        dorsal = side.cross(t).normalized()
        try:
            base, nrm = hit(p + dorsal * 0.3, -dorsal)
        except RuntimeError:
            s_pos += 0.07
            continue
        h = np.interp(s_pos / spine.length, [a for a, _ in sizes], [b for _, b in sizes])
        base = base - nrm * 0.006
        spikes.sweep([base, base + nrm * h * 0.45 + t * h * 0.12, base + nrm * h * 0.92 + t * h * 0.55],
                     [(0.15 * h, 0.42 * h, 0.42 * h, 2.0), (0.10 * h, 0.24 * h, 0.30 * h, 2.0), (0.003, 0.004, 0.004, 2.0)],
                     "horn", N=8, step=h / 5, frame="hint", hint=side, tip=1.0)
        n_spk += 1
        s_pos += 0.07 if s_pos < spine.length * 0.5 else 0.065
    LOG["dorsal_spikes"] = n_spk

    claws = pm.Part("DRG_Claws")
    for tip, d, r in TOE_TIPS:
        pm.claw(claws, tip + d * 0.004 + V((0, 0, 0.004)), d, 0.048, r)
    pm.claw(claws, W_W + V((0.0, -0.03, 0.025)), V((0.15, -0.75, 0.55)), 0.06, 0.012)

    # wing membranes between finger centre-lines (the fingers themselves are sculpted)
    memb = pm.Part("DRG_WingMembranes")
    fpaths = [pm.Path([W_W, finger_mid(T), T]) for T in W_TIPS]
    inward = dirn(-0.5, 0, -0.87)
    B = hit((0.15, -0.19, 0.90), inward)[0] + inward * 0.004
    C = hit((0.18, 0.06, 0.78), inward)[0] + inward * 0.004
    A = hit((0.17, 0.32, 0.80), inward)[0] + inward * 0.004
    arm = pm.Path([B, W_E, W_W])
    body_line = pm.Path([B, C, A])
    for i in range(3):
        Ti, Tj = W_TIPS[i], W_TIPS[i + 1]
        depth = 0.20 * (Ti - Tj).length
        toward = (W_W - Ti.lerp(Tj, 0.5)).normalized()
        n = (Ti - W_W).cross(Tj - W_W).normalized()
        sag = (n if n.z < 0 else -n) * 0.035

        def fn(u, v, i=i, depth=depth, toward=toward, sag=sag):
            p = fpaths[i].point(u).lerp(fpaths[i + 1].point(u), v)
            return p + toward * depth * math.sin(math.pi * v) * u ** 3 + sag * math.sin(math.pi * v) * math.sin(math.pi * u * 0.75)
        memb.patch(fn, 18, 8, fpaths[i].length, (Ti - Tj).length, "membrane")
    T4 = W_TIPS[3]
    in_toward = (W_W - A.lerp(T4, 0.5)).normalized()
    n = (T4 - W_W).cross(A - W_W).normalized()
    in_sag = (n if n.x > 0 else -n) * 0.02

    def inner(u, v):
        c0, c1 = arm.point(u), A.lerp(T4, u) + in_toward * 0.16 * (T4 - A).length * math.sin(math.pi * u)
        d0, d1 = body_line.point(v), fpaths[3].point(v)
        bil = B * (1 - u) * (1 - v) + W_W * u * (1 - v) + A * (1 - u) * v + T4 * u * v
        return (1 - v) * c0 + v * c1 + (1 - u) * d0 + u * d1 - bil + in_sag * math.sin(math.pi * u) * math.sin(math.pi * v)
    memb.patch(inner, 20, 14, (W_W - B).length, (A - B).length, "membrane")

    def front(u, v):
        lead = B.lerp(W_W, u) + (W_E - B.lerp(W_W, 0.5)).normalized() * 0.05 * math.sin(math.pi * u)
        return lead.lerp(arm.point(u), v)
    memb.patch(front, 14, 4, (W_W - B).length, 0.1, "membrane")
    memb.pack_uvs()
    bmesh.ops.remove_doubles(memb.bm, verts=memb.bm.verts[:], dist=1e-5)
    bmesh.ops.solidify(memb.bm, geom=memb.bm.faces[:], thickness=0.006)
    for f in memb.bm.faces:
        f.smooth = True

    objs = []
    for part, mirror in ((eyes, True), (horns, True), (spikes, False), (claws, True), (memb, True)):
        if part is not memb:
            part.pack_uvs()
        if mirror:
            part.mirror_x()
        objs.append(part.to_object(collection, parent))
    return objs


# =========================================================================== phase bookkeeping
def save_phase(name, sculptor):
    os.makedirs(PHASE_DIR, exist_ok=True)
    sculptor.mode("OBJECT")
    me = sculptor.ob.data
    LOG["phases"].append({"phase": name, "t_seconds": round(time.perf_counter() - T_START, 2),
                          "verts": len(me.vertices), "faces": len(me.polygons)})
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(PHASE_DIR, f"{name}.blend"), compress=True, copy=True)
    print(f"[bench] phase saved: {name}")


def run():
    bpy.context.preferences.filepaths.save_version = 0
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    scene = bpy.context.scene
    dragon = camera_setup.ensure_collection("Dragon", scene)
    root = bpy.data.objects.new("DRG_Root", None)
    dragon.objects.link(root)

    # ---- Phase 0: blockout + voxel remesh
    bm = build_blockout()
    me = bpy.data.meshes.new("DRG_Sculpt")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("DRG_Sculpt", me)
    dragon.objects.link(ob)
    ob.parent = root
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    camera_setup.build_rig(scene)
    sc = Sculptor(ob)
    LOG["blockout_faces"] = len(me.polygons)
    sc.phase = "phase0_blockout"
    save_phase("phase0_blockout", sc)
    me.remesh_voxel_size = VOXEL
    me.remesh_voxel_adaptivity = 0.0
    for prop in ("use_remesh_fix_poles", "use_remesh_preserve_volume"):
        if hasattr(me, prop):
            setattr(me, prop, True)
    with bpy.context.temp_override(**sc.ov()):
        bpy.ops.object.voxel_remesh()
    me = ob.data
    me.shade_smooth()  # rev 2: voxel remesh output is flat-shaded (terraced look in rev 1 renders)
    sc.phase = "phase0_voxel_remesh"
    save_phase("phase0_voxel_remesh", sc)

    # ---- Phase 1: primary forms
    sc.mode("SCULPT")
    sc.phase = "phase1_primary"
    with bpy.context.temp_override(**sc.ov()):
        bpy.ops.sculpt.mask_from_cavity(factor=2.5, blur_steps=3)
    sc.filter("SMOOTH", strength=1.0, iteration_count=30)          # fillet blockout seams (cavity-masked; rev 2: 12 -> 30)
    with bpy.context.temp_override(**sc.ov()):
        bpy.ops.paint.mask_flood_fill(mode="VALUE", value=0.0)
    sc.filter("SURFACE_SMOOTH", strength=1.0, iteration_count=3, surface_smooth_shape_preservation=0.6)
    for t in PHASE1:
        sc.stroke(spec(t))
    save_phase("phase1_primary", sc)

    # ---- Phase 2: secondary forms
    sc.mode("SCULPT")
    sc.phase = "phase2_secondary"
    for t in PHASE2:
        if t[6] == "eye socket":  # remember the skin surface before carving the socket
            loc, nrm, _, _ = sc.bvh().ray_cast(EYE_TARGET - EYE_VIEW * 0.4, EYE_VIEW, 1.0)
            EYE_REF[:] = [loc, nrm if nrm.dot(EYE_VIEW) < 0 else -nrm]
        sc.stroke(spec(t))
    for t in PHASE2_POLISH:
        sc.stroke(spec(t))
    save_phase("phase2_secondary", sc)

    # ---- Phase 3: tertiary (restrained)
    sc.mode("SCULPT")
    sc.phase = "phase3_tertiary"
    for t in PHASE3:
        sc.stroke(spec(t))
    sc.mode("OBJECT")
    LOG["belly_faces"] = assign_belly(ob)
    tree = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    inserts = build_inserts(dragon, root, tree)
    save_phase("phase3_tertiary", sc)
    LOG["sculpt_seconds"] = round(time.perf_counter() - T_START, 2)
    bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=False)
    print("[bench] saved", OUT_BLEND)

    # Phase 4 (mesh preparation study) lives in mesh_prep.py: it needs no GUI and is run
    # separately in background mode on dragon_sculpt.blend.


def tick():
    try:
        run()
    except Exception:  # noqa: BLE001
        LOG["errors"].append(traceback.format_exc())
        print(traceback.format_exc())
    LOG["total_seconds"] = round(time.perf_counter() - T_START, 2)
    with open(os.path.join(HERE, "sculpt_log.json"), "w", encoding="utf-8") as fh:
        json.dump(LOG, fh, indent=1, default=str)
    bpy.ops.wm.quit_blender()
    return None


if bpy.app.background:
    raise SystemExit("dragon_sculpt.py needs the Blender GUI: sculpt mode crashes Blender 5.2.2 in background mode.")
bpy.app.timers.register(tick, first_interval=2.0)
