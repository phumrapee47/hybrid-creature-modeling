"""Experiment 6 - Detail pass on the Experiment 5 hybrid dragon (anatomy + surface detail).

Starts from a copy of experiment_05_hybrid/dragon_hybrid.py (rev 3; that file is unchanged) and adds,
with each technique assigned by detail size:

  Proportion fixes (lofts)   head x1.12 (Exp 5 head read small for the neck), jaw opened 12 degrees,
                             fuller chest/back for the flight muscles
  Geometry inserts           teeth (ray-cast roots along both jaws, recurved, fangs), forked tongue,
                             eyeballs with a gloss cornea cap, upper/lower eyelids, cheek spikes,
                             front dewclaws, varied dorsal spikes, claws clamped above the ground
  Sculpt (closed loop)       flight muscles, masseter, tendons, axillary/inguinal/gular/wing-root folds
  Procedural displacement    eye sockets, deeper nostrils, ear openings (tympanum)
  Body field attributes      per-vertex body coordinates (s along the nearest body chain, t around it)
                             and region weights, used by the scale shader in place of UV retopology
  Procedural shaders         (detail_materials.py) granular/keeled dorsal/ventral scute/tail whorl/head
                             plate/toe scute/labial scales, countershading, gums, iris with slit pupil,
                             membrane veins + translucency, keratin base-to-tip gradients with rings
  Game version               gated retopology (Decimate fallback) + bake of normal and colour (4096),
                             roughness and AO (2048) from the high-res sculpt with its shaders

Sculpted belly/throat scute creases from Exp 5 are dropped: the shader's ventral scutes replace them.
Needs the Blender GUI (sculpt mode crashes Blender 5.2.2 in background mode):
  blender --factory-startup --window-geometry 0 0 1400 1000 --python dragon_detail.py
Writes dragon_detail.blend (game version), dragon_detail_highres.blend, detail_log.json, then quits.
Test mode: DRG6_DRY_RUN=1 runs headless without the sculpt phase, 512 px bakes, output to a temp folder.
"""
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback

T0 = time.perf_counter()

import bpy  # noqa: E402
import bmesh  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402
from mathutils.kdtree import KDTree  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
sys.path.insert(0, HERE)
import camera_setup  # noqa: E402
import detail_materials as dm  # noqa: E402
import proc_mesh as pm  # noqa: E402
import sculpt_driver as sd  # noqa: E402

REVISION = 2  # v1 inherited the Exp 2 lower jaw (built to hide under a closed mouth); v2 rebuilds jaw + snout tip
VOXEL = 0.0035                 # Exp 5: 0.005; finer so tendons and folds (6-8 mm radius) survive
RETOPO_TARGET_FACES = 12000
DECIMATE_TARGET_TRIS = 32000
GATE_MAX_MM, GATE_MEAN_MM = 12.0, 2.0
BAKE = {"normal": 4096, "color": 4096, "roughness": 2048, "ao": 2048}
DRY_RUN = os.environ.get("DRG6_DRY_RUN") == "1"
OUT = tempfile.mkdtemp(prefix="drg6dry_") if DRY_RUN else HERE
if DRY_RUN:
    BAKE = {k: 512 for k in BAKE}
HEAD_SCALE, HEAD_PIVOT = 1.12, Vector((0.0, -0.75, 1.20))
JAW_OPEN_DEG, JAW_HINGE = 12.0, Vector((0.0, -0.80, 1.16))
V, X, Y, Z = Vector, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
LOG = {"experiment": "06_detail_pass", "revision": REVISION, "blender": bpy.app.version_string, "voxel_size": VOXEL,
       "head_scale": HEAD_SCALE, "jaw_open_deg": JAW_OPEN_DEG, "timings": {}, "strokes": [], "filters": [], "errors": []}
DM = {}


def rad(d):
    return math.radians(d)


def dirn(*v):
    return V(v).normalized()


def mx(p, s):
    return V((p[0] * s, p[1], p[2]))


def hx(p):
    """Head enlargement about the skull/neck pivot."""
    return HEAD_PIVOT + (V(p) - HEAD_PIVOT) * HEAD_SCALE


def jaw_open(p):
    h = hx(JAW_HINGE)
    return h + Matrix.Rotation(rad(JAW_OPEN_DEG), 3, "X") @ (V(p) - h)


def mark(name):
    LOG["timings"][name] = round(time.perf_counter() - T0, 2)
    print(f"[bench] {name} @ {LOG['timings'][name]} s")


SIDE, FRONT, TOP, BELOW, BEHIND = dirn(-1, 0, 0), dirn(0, 1, 0), dirn(0, 0, -1), dirn(0, 0, 1), dirn(0, -1, 0)

# =========================================================================== shape data (Exp 2 rev 4 / Exp 5)
TRUNK_PTS = [(0, -0.80, 1.19), (0, -0.73, 1.115), (0, -0.67, 1.005), (0, -0.61, 0.895), (0, -0.51, 0.795),
             (0, -0.36, 0.72), (0, -0.18, 0.685), (0, 0.05, 0.655), (0, 0.30, 0.67), (0, 0.50, 0.655),
             (0, 0.74, 0.58), (0.04, 1.00, 0.45), (0.13, 1.26, 0.30), (0.22, 1.50, 0.19), (0.30, 1.73, 0.13)]
# chest stations 4-6 enlarged (Exp 5 values 0.130/0.110/0.150, 0.215/0.200/0.260, 0.205/0.205/0.245):
# a flier needs a deep keel chest and broad shoulders for the pectoral and supracoracoideus muscles
TRUNK_SHAPES = [(0.062, 0.070, 0.072, 2.0, 0.0, 0.0), (0.058, 0.062, 0.070, 2.1, 0.0, 0.004),
                (0.066, 0.066, 0.080, 2.2, 0.0, 0.006), (0.088, 0.082, 0.105, 2.2, 0.0, 0.007),
                (0.136, 0.116, 0.158, 2.3, 0.005, 0.008), (0.228, 0.220, 0.276, 2.5, 0.020, 0.010),
                (0.215, 0.222, 0.255, 2.5, 0.015, 0.012), (0.165, 0.190, 0.175, 2.4, 0.0, 0.012),
                (0.190, 0.200, 0.175, 2.5, 0.0, 0.012), (0.140, 0.150, 0.130, 2.3, 0.0, 0.010),
                (0.095, 0.100, 0.085, 2.2, 0.0, 0.008), (0.066, 0.068, 0.058, 2.1, 0.0, 0.006),
                (0.043, 0.044, 0.038, 2.0, 0.0, 0.004), (0.024, 0.025, 0.021, 2.0, 0.0, 0.002),
                (0.003, 0.003, 0.003, 2.0, 0.0, 0.0)]
_HEAD_PTS = [(0, -1.165, 1.168), (0, -1.135, 1.174), (0, -1.05, 1.180), (0, -0.97, 1.190), (0, -0.905, 1.212),
             (0, -0.845, 1.222), (0, -0.785, 1.218), (0, -0.745, 1.206), (0, -0.722, 1.198)]
# v2: snout stations 1-2 slimmer and less boxy (v1/Exp 5: 0.044/0.040/0.030 n2.6, 0.056/0.046/0.036 n3.2 read as a
# bulbous knob overhanging the jaw once the mouth was open)
_HEAD_SHAPES = [(0.012, 0.012, 0.012, 2.0, 0.0, 0.0, 0.0), (0.038, 0.034, 0.028, 2.5, 0.0, 0.0, 0.0),
                (0.052, 0.044, 0.034, 2.8, 0.0, 0.0, 0.0), (0.066, 0.056, 0.040, 3.0, 0.006, 0.004, 0.0),
                (0.086, 0.082, 0.050, 2.8, 0.042, 0.010, 0.006), (0.108, 0.096, 0.064, 2.6, 0.014, 0.034, 0.010),
                (0.104, 0.090, 0.070, 2.4, 0.004, 0.030, 0.008), (0.070, 0.066, 0.058, 2.2, 0.0, 0.006, 0.0),
                (0.008, 0.008, 0.008, 2.0, 0.0, 0.0, 0.0)]
# v2 lower jaw. The Exp 2 jaw ended 4.7 cm (5.3 cm scaled) behind the snout tip and was 59-69 % of the upper jaw's
# width: invisible with the mouth closed, wrong once open. Reptile mandibles (crocodilians, monitors) reach the snout
# tip and carry their tooth row just inside the upper one, so: tip 1.3 cm behind the snout, width 86-89 % of the
# upper jaw at every station, depth kept at roughly half the snout (the upper skull also holds nasal passages/eyes).
_JAW_PTS = [(0, -1.152, 1.134), (0, -1.128, 1.130), (0, -1.05, 1.127), (0, -0.97, 1.129), (0, -0.89, 1.136),
            (0, -0.815, 1.150), (0, -0.79, 1.158)]
_JAW_SHAPES = [(0.012, 0.010, 0.010, 2.0), (0.034, 0.018, 0.016, 2.6), (0.048, 0.020, 0.022, 2.8), (0.058, 0.023, 0.028, 2.7),
               (0.078, 0.027, 0.036, 2.6), (0.094, 0.034, 0.050, 2.4), (0.012, 0.012, 0.012, 2.0)]
_HORN_PTS = [(0.042, -0.80, 1.265), (0.058, -0.755, 1.315), (0.083, -0.67, 1.352), (0.103, -0.575, 1.36),
             (0.115, -0.495, 1.335), (0.119, -0.45, 1.295)]
_HORN_R = [0.030, 0.026, 0.019, 0.012, 0.006, 0.001]


def _scale_shape(sh):
    return tuple(v * HEAD_SCALE if i != 3 else v for i, v in enumerate(sh))  # index 3 = superellipse exponent


HEAD_PTS = [hx(p) for p in _HEAD_PTS]
HEAD_SHAPES = [_scale_shape(s) for s in _HEAD_SHAPES]
JAW_PTS = [jaw_open(hx(p)) for p in _JAW_PTS]
JAW_SHAPES = [_scale_shape(s) for s in _JAW_SHAPES]
HORN_PTS = [hx(p) for p in _HORN_PTS]
HORN_R = [r * HEAD_SCALE for r in _HORN_R]
FRONT_PTS = [(0.10, -0.30, 0.68), (0.19, -0.31, 0.56), (0.225, -0.255, 0.44), (0.24, -0.215, 0.35),
             (0.245, -0.205, 0.32), (0.248, -0.225, 0.29), (0.25, -0.28, 0.19), (0.25, -0.325, 0.10), (0.25, -0.355, 0.05)]
FRONT_SHAPES = [(0.100, 0.120, 0.120, 2.2), (0.088, 0.095, 0.095, 2.3), (0.070, 0.072, 0.078, 2.3),
                (0.056, 0.062, 0.054, 2.2), (0.054, 0.070, 0.050, 2.2), (0.050, 0.058, 0.050, 2.2),
                (0.047, 0.048, 0.050, 2.3), (0.036, 0.036, 0.038, 2.2), (0.038, 0.032, 0.038, 2.2)]
HIND_PTS = [(0.10, 0.38, 0.74), (0.18, 0.40, 0.60), (0.23, 0.33, 0.47), (0.245, 0.265, 0.39), (0.25, 0.245, 0.36),
            (0.25, 0.26, 0.33), (0.25, 0.36, 0.25), (0.25, 0.45, 0.18), (0.25, 0.47, 0.16), (0.25, 0.462, 0.135),
            (0.25, 0.43, 0.10), (0.25, 0.385, 0.05)]
HIND_SHAPES = [(0.125, 0.155, 0.155, 2.2), (0.115, 0.125, 0.145, 2.3), (0.100, 0.095, 0.125, 2.3),
               (0.070, 0.065, 0.075, 2.2), (0.064, 0.060, 0.068, 2.2), (0.058, 0.056, 0.056, 2.2),
               (0.054, 0.056, 0.048, 2.3), (0.042, 0.046, 0.036, 2.2), (0.040, 0.050, 0.034, 2.2),
               (0.037, 0.040, 0.034, 2.2), (0.034, 0.034, 0.034, 2.2), (0.036, 0.032, 0.036, 2.2)]
W_ROOT, W_E, W_W = V((0.07, -0.21, 0.80)), V((0.48, 0.02, 1.10)), V((0.86, -0.26, 1.40))
W_TIPS = [V((1.32, -0.08, 1.52)), V((1.30, 0.30, 1.10)), V((1.04, 0.56, 0.86)), V((0.66, 0.60, 0.80))]
EYE_R = 0.02 * HEAD_SCALE
TOE_TIPS = []    # (tip, direction, claw radius, claw length) on the left side
TOE_CHAINS = []  # toe and palm centre lines (left side) for the body fields
BROW, CHEEK = rad(55), rad(-15)


def finger_mid(T):
    return W_W.lerp(T, 0.5) + dirn(0.0, 0.3, -0.5) * 0.022


def surface_hit(tree, target, direction, reach=0.4):
    direction = V(direction).normalized()
    loc, nrm, _, _ = tree.ray_cast(V(target) - direction * reach, direction, reach * 2.5)
    if loc is None:
        raise RuntimeError(f"surface miss at {tuple(target)}")
    if nrm.length < 0.5:
        raise RuntimeError("zero normal (bm.normal_update missing?)")
    return loc, (nrm if nrm.dot(direction) < 0 else -nrm)


def arc_at_u(path, u):
    for k, (_, uu) in enumerate(path.samples):
        if uu >= u:
            return path.arc[k]
    return path.length


# =========================================================================== Phase 1: lofted primary forms
def paw(part, center, fwd, toe_angles, toe_len, toe_r, claw_len, back_toe, dewclaw=False):
    fwd, c = V(fwd).normalized(), V(center)
    palm = [c - fwd * 0.05 + V((0, 0, 0.006)), c + V((0, 0, 0.002)), c + fwd * 0.042, c + fwd * 0.056]
    part.sweep(palm, [(0.036, 0.026, 0.020, 2.6), (0.055, 0.028, 0.020, 2.8), (0.057, 0.022, 0.018, 2.8), (0.033, 0.015, 0.012, 2.4)],
               "skin", N=16, step=0.012, start="tip", end="tip", tip=0.5)
    TOE_CHAINS.append(palm)
    dirs = [(Matrix.Rotation(rad(a), 3, "Z") @ fwd, toe_len, toe_r, claw_len) for a in toe_angles]
    if back_toe:
        dirs.append((Matrix.Rotation(rad(12), 3, "Z") @ -fwd, toe_len * 0.5, toe_r * 0.8, claw_len * 0.7))
    for d, ln, r0, cl in dirs:
        base = c + d * (0.022 if d.dot(fwd) > 0 else 0.03) + V((0, 0, -0.002 if d.dot(fwd) > 0 else 0.0))
        tip = base + d * ln + V((0, 0, -0.006))
        chain = [base - d * 0.012, base + d * ln * 0.5 + V((0, 0, 0.004)), tip]
        part.sweep(chain, [(r0, r0 * 0.9, r0 * 0.9, 2.2), (r0 * 1.08, r0, r0, 2.2), (r0 * 0.82, r0 * 0.75, r0 * 0.75, 2.2)],
                   "skin", N=10, step=0.012, start="cap", end="tip", tip=0.8)
        TOE_CHAINS.append(chain)
        TOE_TIPS.append((tip + d * 0.002 + V((0, 0, 0.004)), d, r0 * 0.72, cl))
    if dewclaw:
        # first digit of the forefoot: short, raised on the inner back of the wrist, never touches the ground
        d = (Matrix.Rotation(rad(-120), 3, "Z") @ fwd + V((0, 0, -0.35))).normalized()
        base = c + V((-0.026, 0.012, 0.042))
        tip = base + d * 0.026
        chain = [base - d * 0.012, base + d * 0.013, tip]
        part.sweep(chain, [(0.012, 0.011, 0.011, 2.2), (0.012, 0.011, 0.011, 2.2), (0.009, 0.008, 0.008, 2.2)],
                   "skin", N=10, step=0.008, start="cap", end="tip", tip=0.8)
        TOE_CHAINS.append(chain)
        TOE_TIPS.append((tip + d * 0.002, d, 0.0085, 0.024))


def build_body_base():
    trunk = pm.Part("trunk")
    trunk_path = trunk.sweep(TRUNK_PTS, TRUNK_SHAPES, "skin", N=32, step=0.025, start="cap", end="tip", tip=1.5,
                             bumps=[(1.5 * math.pi, 0.35, 4), (0.5 * math.pi, 0.22, 5)])
    trunk.bm.normal_update()
    tbvh = BVHTree.FromBMesh(trunk.bm)
    inward = dirn(-0.5, 0, -0.87)
    B = surface_hit(tbvh, (0.15, -0.19, 0.90), inward)[0] + inward * 0.004
    head = pm.Part("head")
    head.sweep(HEAD_PTS, HEAD_SHAPES, "skin", N=48, step=0.007, start="tip", end="tip",
               bumps=[(BROW, 0.28, 4), (math.pi - BROW, 0.28, 4), (CHEEK, 0.40, 5), (math.pi - CHEEK, 0.40, 5),
                      (0.5 * math.pi, 0.15, 6)])
    head.sweep(JAW_PTS, JAW_SHAPES, "skin", N=28, step=0.009, start="tip", end="tip")
    limbs = pm.Part("limbs")
    limbs.sweep(FRONT_PTS, FRONT_SHAPES, "skin", N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
    limbs.sweep(HIND_PTS, HIND_SHAPES, "skin", N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
    paw(limbs, (0.25, -0.37, 0.03), (math.sin(rad(8)), -math.cos(rad(8)), 0), (-26, 0, 26), 0.062, 0.020, 0.047, False, dewclaw=True)
    paw(limbs, (0.25, 0.36, 0.03), (math.sin(rad(6)), -math.cos(rad(6)), 0), (-24, 0, 24), 0.072, 0.022, 0.052, True)
    arm_path = limbs.sweep([W_ROOT, B, W_E, W_W], [(0.060, 0.060, 0.060, 2.0), (0.050, 0.050, 0.050, 2.0),
                                                   (0.040, 0.040, 0.040, 2.0), (0.028, 0.030, 0.030, 2.0)],
                           "skin", N=16, step=0.02, start="cap", end="cap")
    ed = (W_E - B).normalized()
    limbs.sweep([W_E - ed * 0.03, W_E + ed * 0.03], [(0.040, 0.044, 0.040, 2.0), (0.034, 0.036, 0.034, 2.0)],
                "skin", N=16, step=0.01, start="tip", end="tip", tip=0.7)  # elbow knob
    limbs.mirror_x()
    bm = bmesh.new()
    for part in (trunk, head, limbs):
        me = bpy.data.meshes.new("tmp")
        part.bm.to_mesh(me)
        part.bm.free()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    return bm, trunk_path, arm_path, B


# =========================================================================== sculpt programme
def S(brush, r, strength, view, pts, label, target=None, passes=1, mode="NORMAL"):
    return sd.spec(brush, r, strength, view, pts, label, target=target, mode=mode, passes=passes)


S1_JUNCTIONS = [
    S("Smooth", 0.05, 0.6, SIDE, [(0.24, -0.40, 0.60), (0.25, -0.30, 0.66), (0.24, -0.22, 0.60)], "shoulder junction", passes=3),
    S("Smooth", 0.06, 0.6, SIDE, [(0.20, 0.30, 0.72), (0.22, 0.42, 0.74), (0.22, 0.52, 0.66)], "thigh junction", passes=3),
    S("Smooth", 0.045, 0.6, TOP, [(0.12, -0.26, 0.88), (0.17, -0.18, 0.92), (0.12, -0.10, 0.88)], "wing root junction", passes=3),
    S("Smooth", 0.05, 0.6, dirn(-1, 0.3, -0.3), [(0.07, -0.76, 1.14), (0.06, -0.72, 1.20)], "neck-skull junction", passes=3),
    S("Smooth", 0.03, 0.6, SIDE, [(0.27, -0.37, 0.06), (0.27, -0.33, 0.11)], "front wrist-paw junction", passes=3),
    S("Smooth", 0.03, 0.6, SIDE, [(0.27, 0.41, 0.06), (0.27, 0.43, 0.11)], "hind ankle-paw junction", passes=3),
]
S2_SECONDARY = [  # Exp 5 v2/v3 list; head strokes follow the enlarged head; the mouth-line crease is gone (mouth open)
    S("Clay Strips", 0.016 * HEAD_SCALE, 0.5, dirn(-0.6, 0.6, -0.5), [hx((0.035, -0.96, 1.285)), hx((0.065, -0.93, 1.28)), hx((0.085, -0.89, 1.27))], "brow ridge", target=4),
    S("Crease Sharp", 0.012, 0.4, dirn(-1, 0, 0.35), [hx((0.06, -0.87, 1.11)), hx((0.07, -0.80, 1.12))], "jaw angle", target=3),
    S("Blob", 0.024 * HEAD_SCALE, 0.4, dirn(-0.3, 0.3, -1), [hx((0.05, -0.79, 1.30))], "horn boss", target=5),
    S("Clay", 0.025, 0.45, SIDE, [(0.07, -0.76, 1.12), (0.08, -0.66, 1.00), (0.10, -0.56, 0.86), (0.13, -0.47, 0.76)], "neck muscle", target=4),
    S("Inflate/Deflate", 0.035, 0.3, dirn(-0.4, 1, 0), [(0.04, -0.60, 0.60), (0.11, -0.56, 0.56), (0.16, -0.48, 0.52)], "pectoral", target=5),
    S("Inflate/Deflate", 0.035, 0.3, SIDE, [(0.22, -0.40, 0.62), (0.25, -0.31, 0.62), (0.24, -0.22, 0.56)], "deltoid", target=5),
    S("Clay", 0.030, 0.35, TOP, [(0.10, -0.40, 0.90), (0.13, -0.28, 0.92), (0.14, -0.18, 0.90)], "scapula", target=4),
    S("Clay", 0.018, 0.25, SIDE, [(0.20, -0.20, 0.75), (0.19, -0.12, 0.55)], "rib 1", target=2.5),
    S("Clay", 0.018, 0.25, SIDE, [(0.19, -0.10, 0.76), (0.18, -0.02, 0.57)], "rib 2", target=2.5),
    S("Clay", 0.018, 0.25, SIDE, [(0.18, 0.00, 0.76), (0.17, 0.08, 0.58)], "rib 3", target=2.5),
    S("Inflate/Deflate", 0.035, 0.3, SIDE, [(0.27, 0.30, 0.58), (0.29, 0.27, 0.48), (0.28, 0.26, 0.40)], "quadriceps", target=5),
    S("Inflate/Deflate", 0.030, 0.3, dirn(-1, -0.4, 0), [(0.25, 0.50, 0.62), (0.27, 0.45, 0.48)], "hamstring", target=4),
    S("Inflate/Deflate", 0.022, 0.3, SIDE, [(0.27, -0.22, 0.30), (0.27, -0.28, 0.18)], "forearm", target=3),
    S("Inflate/Deflate", 0.025, 0.3, dirn(-1, -0.3, 0), [(0.27, 0.30, 0.32), (0.27, 0.38, 0.24)], "calf", target=3),
    S("Inflate/Deflate", 0.040, 0.30, TOP, [(0.15, -0.19, 0.92)], "wing shoulder", target=4),
    S("Clay", 0.030, 0.35, TOP, [(0.04, 0.52, 0.80), (0.04, 0.70, 0.68)], "tail root muscle", target=4),
]
S2_POLISH = [
    S("Smooth", 0.06, 0.35, dirn(-0.4, 1, 0), [(0.03, -0.62, 0.66), (0.12, -0.56, 0.58), (0.18, -0.46, 0.52)], "polish chest", passes=2),
    S("Smooth", 0.06, 0.35, SIDE, [(0.21, -0.36, 0.72), (0.20, -0.14, 0.70), (0.18, 0.08, 0.68)], "polish flank", passes=2),
    S("Smooth", 0.05, 0.35, SIDE, [(0.27, 0.34, 0.62), (0.28, 0.28, 0.48), (0.28, 0.26, 0.38)], "polish thigh", passes=2),
    S("Smooth", 0.04, 0.35, SIDE, [(0.24, -0.36, 0.60), (0.25, -0.26, 0.46), (0.26, -0.22, 0.34)], "polish upper arm", passes=2),
    S("Smooth", 0.06, 0.35, TOP, [(0.08, -0.40, 0.90), (0.10, -0.10, 0.86), (0.10, 0.30, 0.86)], "polish back", passes=2),
]
GULAR_UP = dirn(0, 0.73, 0.68)  # dorsal axis of the upper neck: looking along it views the throat from below-front
S2_DETAIL = [  # new in Exp 6: masses a flier and a biter need
    S("Inflate/Deflate", 0.045, 0.3, dirn(-0.5, 1, -0.1), [(0.05, -0.62, 0.68), (0.12, -0.55, 0.72), (0.17, -0.44, 0.78)], "pectoralis (flight)", target=6.0),
    S("Inflate/Deflate", 0.035, 0.3, TOP, [(0.09, -0.36, 0.95), (0.13, -0.26, 0.96), (0.13, -0.14, 0.93)], "dorsal flight muscle", target=5.0),
    S("Inflate/Deflate", 0.022, 0.3, SIDE, [hx((0.09, -0.845, 1.150)), hx((0.09, -0.805, 1.168))], "masseter", target=4.0),
    S("Inflate/Deflate", 0.018, 0.3, SIDE, [(0.19, -0.27, 0.80), (0.22, -0.22, 0.86)], "wing-root muscle", target=3.0),
]
S3_TERTIARY = [
    S("Crease Sharp", 0.006, 0.25, SIDE, [(0.07, -0.70, 1.10), (0.075, -0.66, 1.06), (0.07, -0.63, 1.03)], "neck fold 1", target=2),
    S("Crease Sharp", 0.006, 0.25, SIDE, [(0.075, -0.68, 1.04), (0.08, -0.64, 1.00), (0.075, -0.61, 0.97)], "neck fold 2", target=2),
    S("Crease Sharp", 0.006, 0.25, SIDE, [(0.085, -0.65, 0.97), (0.09, -0.61, 0.94), (0.085, -0.58, 0.91)], "neck fold 3", target=2.0),
    S("Crease Sharp", 0.007, 0.3, GULAR_UP, [(0.0, -0.781, 1.067), (0.04, -0.772, 1.078), (0.062, -0.752, 1.100)], "gular fold 1", target=2.5),
    S("Crease Sharp", 0.007, 0.3, GULAR_UP, [(0.0, -0.745, 1.030), (0.045, -0.737, 1.040), (0.066, -0.718, 1.062)], "gular fold 2", target=2.0),
    S("Crease Sharp", 0.008, 0.3, SIDE, [(0.20, -0.20, 0.58), (0.21, -0.17, 0.52), (0.22, -0.16, 0.46)], "axillary fold", target=2.5),
    S("Crease Sharp", 0.008, 0.3, SIDE, [(0.20, 0.25, 0.66), (0.21, 0.26, 0.58), (0.23, 0.28, 0.50)], "inguinal fold", target=2.5),
    S("Crease Sharp", 0.007, 0.3, TOP, [(0.13, -0.13, 0.87), (0.17, -0.12, 0.85)], "wing-root fold", target=2.0),
    S("Draw", 0.007, 0.3, dirn(0, -0.6, -0.8), [(0.25, 0.30, 0.37), (0.25, 0.38, 0.30), (0.25, 0.45, 0.235)], "Achilles tendon", target=1.5),
    S("Draw", 0.006, 0.3, BEHIND, [(0.25, -0.235, 0.26), (0.25, -0.25, 0.19), (0.25, -0.285, 0.11)], "forearm flexor tendon", target=1.2),
]


# =========================================================================== procedural displacement
def displace(me, center, normal, radius, depth, rim, upper_boost=0.0):
    co = sd.coords(me)
    c, n = np.array(center), np.array(normal)
    up = np.array(Z - V(normal) * V(normal).dot(Z))
    up /= np.linalg.norm(up)
    d = co - c
    h = d @ n
    sel = (np.linalg.norm(d, axis=1) < radius * 1.6) & (h > -0.04)
    planar = d[sel] - np.outer(h[sel], n)
    r = np.linalg.norm(planar, axis=1)
    off = np.where(r < radius, -depth * (1 - (r / radius) ** 2) ** 2, 0.0)
    lid = 1 + upper_boost * np.clip((planar @ up) / np.maximum(r, 1e-9), 0, None)
    off += rim * lid * np.exp(-((r - radius * 0.95) / (radius * 0.28)) ** 2)
    co[sel] += np.outer(off, n)
    me.vertices.foreach_set("co", co.ravel())
    me.update()
    return int(sel.sum())


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def seg_dist(c, a, b):
    ab = b - a
    t = np.clip(((c - a) @ ab) / (ab @ ab), 0, 1)
    p = a + t[:, None] * ab
    return np.linalg.norm(c - p, axis=1), p, t


# =========================================================================== mouth analysis
def mouth_profile(tree):
    """Stations along the open mouth: palate height zu and jaw-floor height zl on the midline."""
    head = pm.Path(HEAD_PTS)
    out = []
    for y in np.linspace(HEAD_PTS[1].y + 0.012, hx(V((0, -0.80, 0))).y, 26):
        c, u = min(head.samples, key=lambda q: abs(q[0].y - y))
        an = pm.shape_at(HEAD_SHAPES, u)[2]
        loc, nrm, _, _ = tree.ray_cast(V((0.0, y, c.z)), -Z, 0.3)
        ok = loc is not None and nrm.z < -0.2 and c.z - loc.z < 1.25 * an + 0.01  # palate: exit facing down, near the loft's own underside
        if ok:
            loc2, nrm2, _, _ = tree.ray_cast(loc - Z * 0.0015, -Z, 0.10)
            ok = loc2 is not None and nrm2.z > 0.2 and loc.z - loc2.z >= 0.006  # jaw floor facing up across an open gap
        if not ok:
            if out:
                break  # the mouth closes towards the hinge; keep the contiguous open part only
            continue
        out.append({"y": float(y), "zu": loc.z, "zl": loc2.z, "zm": 0.5 * (loc.z + loc2.z)})
    if len(out) < 4:
        raise RuntimeError(f"mouth profile found only {len(out)} open stations")
    return out


def prof_at(prof, y, key):
    return float(np.interp(y, [p["y"] for p in prof], [p[key] for p in prof]))


def half_width(tree, y, z):
    loc, _, _, _ = tree.ray_cast(V((0.4, y, z)), -X, 0.4)
    return None if loc is None else loc.x


def mouth_weights(me, tree, prof):
    """w_mouth: surface seen from the mouth's inner axis and facing it (palate, jaw floor, inner lips)."""
    c = sd.coords(me)
    nrm = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    y0, y1 = prof[0]["y"] - 0.05, prof[-1]["y"] + 0.03
    sel = np.where((c[:, 1] > y0) & (c[:, 1] < y1) & (np.abs(c[:, 0]) < 0.16) & (c[:, 2] > 0.95) & (c[:, 2] < 1.32))[0]
    axis = [np.array((0.0, prof[0]["y"] - 0.03, prof[0]["zm"]))] + [np.array((0.0, p["y"], p["zm"])) for p in prof]
    cs = c[sel]
    best, foot = np.full(len(sel), 1e9), np.zeros((len(sel), 3))
    for a, b in zip(axis, axis[1:]):
        d, p, _ = seg_dist(cs, a, b)
        closer = d < best
        best = np.where(closer, d, best)
        foot[closer] = p[closer]
    w = np.zeros(len(c))
    for k, i in enumerate(sel):
        v, a = V(c[i]), V(foot[k])
        dvec = v - a
        dist = dvec.length
        if dist < 1e-6:
            continue
        facing = V(nrm[i]).dot(-dvec) / dist
        if facing <= 0.05:
            continue
        loc, _, _, _ = tree.ray_cast(a, dvec / dist, dist + 0.002)
        if loc is not None and (loc - v).length < 0.0025:
            w[i] = float(smoothstep(0.05, 0.35, facing))
    return w


def lip_weights(c, w_mouth, head_mask):
    kd_pts = np.where(w_mouth > 0.5)[0]
    w = np.zeros(len(c))
    if len(kd_pts) == 0:
        return w
    kd = KDTree(len(kd_pts))
    for j, i in enumerate(kd_pts):
        kd.insert(c[i], j)
    kd.balance()
    for i in np.where(head_mask)[0]:
        d = kd.find(c[i])[2]
        w[i] = (1.0 - float(smoothstep(0.004, 0.016, d))) * (1.0 - w_mouth[i])
    return w


# =========================================================================== body fields (scale shader input)
SPINE = [hx((0, -1.12, 1.18)), hx((0, -0.98, 1.17)), hx((0, -0.84, 1.18))] + [V(p) for p in TRUNK_PTS[1:]]


def _dense(pts, step):
    path = pm.Path(pts)
    n = max(2, int(path.length / step))
    return [path.at(path.length * k / n)[0] for k in range(n + 1)]


def body_fields(me, w_mouth, w_lip):
    """Per-vertex body coordinates and region weights written as mesh attributes.

    body_st = (s, t): s = arc length along the nearest body chain, t = |angle from the chain's ventral
    direction| x distance from the chain (mirror-symmetric, so no seam on either midline).
    Oriented scale patterns are weighted by chain membership, which fades to 0 where two chains are
    nearly equidistant (limb/neck/tail roots), so pattern discontinuities at chain switches are hidden
    under isotropic granular scales.
    """
    c = sd.coords(me)
    n = len(c)
    chains = [("spine", _dense(SPINE, 0.02))]
    for s in (1, -1):
        chains.append(("front", [mx(p, s) for p in _dense(FRONT_PTS[1:], 0.02)]))
        chains.append(("hind", [mx(p, s) for p in _dense(HIND_PTS[1:], 0.02)]))
        chains.append(("arm", [mx(p, s) for p in _dense([W_ROOT, W_E, W_W], 0.03)]))
        for toe in TOE_CHAINS:
            chains.append(("toe", [mx(p, s) for p in _dense(toe, 0.006)]))
    groups = sorted({g for g, _ in chains})
    gmin = {g: np.full(n, 1e9) for g in groups}
    best = np.full(n, 1e9)
    b_group = np.zeros(n, int)
    b_s, b_foot, b_tan = np.zeros(n), np.zeros((n, 3)), np.zeros((n, 3))
    for g, pts in chains:
        P = [np.array(p, float) for p in pts]
        arc = 0.0
        for a, b in zip(P, P[1:]):
            L = float(np.linalg.norm(b - a))
            d, p, t = seg_dist(c, a, b)
            gmin[g] = np.minimum(gmin[g], d)
            closer = d < best
            best = np.where(closer, d, best)
            b_group[closer] = groups.index(g)
            b_s[closer] = arc + t[closer] * L
            b_foot[closer] = p[closer]
            b_tan[closer] = (b - a) / L
            arc += L
    stack = np.sort(np.stack([gmin[g] for g in groups]), axis=0)
    member = 1.0 - smoothstep(0.80, 0.95, stack[0] / np.maximum(stack[1], 1e-9))
    r = c - b_foot
    r -= (r * b_tan).sum(1)[:, None] * b_tan
    r /= np.maximum(np.linalg.norm(r, axis=1), 1e-9)[:, None]
    side = np.cross(b_tan, [0.0, 0.0, 1.0])
    weak = np.linalg.norm(side, axis=1) < 0.3            # near-vertical limb segments: frame from +X instead
    side[weak] = np.array([1.0, 0, 0]) - (b_tan[weak] @ np.array([1.0, 0, 0]))[:, None] * b_tan[weak]
    side /= np.maximum(np.linalg.norm(side, axis=1), 1e-9)[:, None]
    up = np.cross(side, b_tan)
    cos_up = (r * up).sum(1)
    t_coord = np.arccos(np.clip(-cos_up, -1, 1)) * best
    is_spine = b_group == groups.index("spine")
    is_toe = b_group == groups.index("toe")
    m_spine, m_toe = member * is_spine, member * is_toe
    w_up = np.where(is_spine, 0.5 + 0.5 * cos_up, 0.5 + 0.5 * r[:, 2])
    w_head = (1.0 - smoothstep(hx((0, -0.78, 0)).y, hx((0, -0.72, 0)).y, c[:, 1])) * smoothstep(1.00, 1.07, c[:, 2])
    w_belly = smoothstep(math.cos(rad(57)), math.cos(rad(43)), -cos_up) * m_spine * (1 - w_mouth)
    w_dorsal = smoothstep(0.30, 0.55, cos_up) * m_spine * (1 - w_head)
    w_tail = smoothstep(0.55, 0.80, c[:, 1]) * m_spine
    w_foot = smoothstep(-0.35, 0.0, r[:, 2]) * m_toe
    attrs = {"w_up": w_up, "w_dorsal": w_dorsal, "w_belly": w_belly, "w_head": w_head * (1 - w_mouth),
             "w_tail": w_tail, "w_foot": w_foot, "w_lip": w_lip, "w_mouth": w_mouth}
    for name, val in attrs.items():
        a = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", np.clip(val, 0, 1).astype(np.float32))
    st = me.attributes.get("body_st") or me.attributes.new("body_st", "FLOAT_VECTOR", "POINT")
    st.data.foreach_set("vector", np.stack([b_s, t_coord, np.zeros(n)], 1).astype(np.float32).ravel())
    return {k: int((v > 0.5).sum()) for k, v in attrs.items()}


# =========================================================================== inserts
def to_object(part, collection, parent):
    bmesh.ops.recalc_face_normals(part.bm, faces=part.bm.faces[:])
    me = bpy.data.meshes.new(part.name)
    part.bm.to_mesh(me)
    part.bm.free()
    for key in part.mats:
        me.materials.append(DM[key])
    ob = bpy.data.objects.new(part.name, me)
    collection.objects.link(ob)
    ob.parent = parent
    return ob


def sph(axis, e1, e2, theta, phi):
    return axis * math.cos(theta) + (e1 * math.cos(phi) + e2 * math.sin(phi)) * math.sin(theta)


def build_eyes(eye_ref):
    ep, en = eye_ref
    c = ep - en * (EYE_R - 0.003 * HEAD_SCALE)
    up = (Z - en * en.dot(Z)).normalized()
    side = up.cross(en)
    eyes = pm.Part("DRG_Eyes")
    el = eyes.bm.verts.layers.float_vector.new("eye_local")  # before any geometry (layer creation invalidates refs)
    faces = eyes.sphere(c, EYE_R, "eye", segs=48, rings_=24)
    for v in {v for f in faces for v in f.verts}:
        d = (v.co - c) / EYE_R
        v[el] = V((d.dot(side), d.dot(up), d.dot(en)))
    cornea = pm.Part("DRG_Cornea")
    cornea.patch(lambda u, v: c + sph(en, side, up, rad(52) * u, 2 * math.pi * v) * EYE_R * 1.035, 10, 40, 0.02, 0.1, "cornea")
    cornea.pack_uvs()
    bmesh.ops.remove_doubles(cornea.bm, verts=cornea.bm.verts[:], dist=1e-6)
    lids = pm.Part("DRG_Eyelids")
    for axis, alpha in (((up * math.cos(rad(20)) + en * math.sin(rad(20))).normalized(), rad(48)),
                        ((-up * math.cos(rad(15)) + en * math.sin(rad(15))).normalized(), rad(42))):
        e1 = axis.cross(side).normalized()
        e2 = axis.cross(e1)
        lids.patch(lambda u, v, a=axis, e1=e1, e2=e2, al=alpha: c + sph(a, e1, e2, rad(3) + (al - rad(3)) * u, 2 * math.pi * v) * EYE_R * 1.07,
                   10, 40, 0.03, 0.15, "skin")
    lids.pack_uvs()
    bmesh.ops.remove_doubles(lids.bm, verts=lids.bm.verts[:], dist=1e-6)
    bmesh.ops.solidify(lids.bm, geom=lids.bm.faces[:], thickness=0.0024)
    for f in lids.bm.faces:
        f.smooth = True
    eyes.pack_uvs()
    for part in (eyes, cornea, lids):
        part.packed = True
    return [eyes, cornea, lids], c


def claw_clamped(part, base, d, length, r0):
    """pm.claw with the hook drop limited so the claw tip stays 1.5 mm above the ground plane."""
    d = V(d).normalized()
    drop = min(0.62, max(0.12, (base.z - 0.0015) / length))
    down = V((0, 0, -1))
    pts = [base - d * 0.004, base + d * length * 0.45 + down * length * drop * 0.1,
           base + d * length * 0.8 + down * length * drop * 0.48, base + d * length * 0.95 + down * length * drop]
    part.sweep(pts, [(r0 * 0.8, r0, r0, 2.0), (r0 * 0.62, r0 * 0.8, r0 * 0.8, 2.0),
                     (r0 * 0.35, r0 * 0.45, r0 * 0.45, 2.0), (0.0008, 0.0008, 0.0008, 2.0)],
               "claw", N=8, step=max(length / 7, 0.005), frame="hint", hint=X if abs(d.x) < 0.7 else Y,
               start="cap", end="tip", tip=0.5)
    return drop


def build_teeth(tree, prof):
    """Teeth with roots ray-cast into the jaw margins; length limited by the measured local gap."""
    teeth = pm.Part("DRG_Teeth")
    y_front, y_back = prof[0]["y"] + 0.004, prof[-1]["y"]
    stats = {"upper": 0, "lower": 0, "skipped": 0, "longest_mm": 0.0}
    for jaw, spacing, nominal, offset in (("upper", 0.021, 0.021, 0.0), ("lower", 0.021, 0.018, 0.0105)):
        ys = np.arange(y_front + offset, y_back, spacing)
        for k, y in enumerate(ys):
            zm = prof_at(prof, y, "zm")
            zprobe = prof_at(prof, y, "zu" if jaw == "upper" else "zl") + (0.004 if jaw == "upper" else -0.004)
            w = half_width(tree, y, zprobe)
            if w is None:
                stats["skipped"] += 1
                continue
            x = (0.55 if k == 0 else 0.80) * w
            out = Z if jaw == "upper" else -Z
            root, rn, _, _ = tree.ray_cast(V((x, y, zm)), out, 0.12)
            far, _, _, _ = tree.ray_cast(V((x, y, zm)), -out, 0.12)
            if root is None or rn.dot(out) > -0.2:
                stats["skipped"] += 1
                continue
            gap = (root - far).length if far is not None else 0.1
            fang = (jaw == "upper" and k in (1, 2)) or (jaw == "lower" and k == 1)
            L = min(nominal * (1.0 - 0.35 * k / max(len(ys) - 1, 1)) * (1.7 if fang else 1.0), 0.62 * gap)
            if L < 0.006:
                stats["skipped"] += 1
                continue
            down = -out
            d = (down * 0.96 + Y * 0.22 + V((0.06, 0, 0))).normalized()
            base = root + out * 0.0035
            rb = min(0.24 * L, 0.0065)
            teeth.sweep([base, base + d * L * 0.55, base + d * L * 0.95 + Y * 0.06 * L],
                        [(rb * 0.72, rb, rb, 2.0), (rb * 0.55, rb * 0.78, rb * 0.78, 2.0), (0.0006, 0.0006, 0.0006, 2.0)],
                        "tooth", N=10, step=max(L / 6, 0.003), frame="hint", hint=X, start="cap", end="tip", tip=1.0)
            stats[jaw] += 1
            stats["longest_mm"] = max(stats["longest_mm"], round(L * 1000, 1))
    return teeth, stats


def build_tongue(tree, prof):
    tongue = pm.Part("DRG_Tongue")
    deep = [p["y"] for p in prof if p["zu"] - p["zl"] >= 0.02]
    if not deep:
        raise RuntimeError("tongue: mouth gap under 20 mm everywhere")
    y_back = max(deep)
    y_tip = prof[0]["y"] + 0.40 * (y_back - prof[0]["y"])
    pts = []
    for y in np.linspace(y_back, y_tip, 9):
        loc, nrm, _, _ = tree.ray_cast(V((0.0, y, prof_at(prof, y, "zm"))), -Z, 0.12)
        if loc is not None and nrm.z > 0.2:
            pts.append(loc + Z * 0.0045)
    if len(pts) < 4:
        raise RuntimeError("tongue: jaw floor not found")
    # one section per control point (sweep interpolates sections by control-point index; v1 passed 4 for 9
    # points and the Catmull-Rom extrapolation blew the tongue up into a metre-long slab)
    key = [(0.018, 0.0055, 0.0055, 2.4), (0.019, 0.006, 0.0055, 2.4), (0.017, 0.0055, 0.005, 2.4), (0.012, 0.0045, 0.004, 2.2)]
    f = np.linspace(0, 1, len(pts))
    shapes = [tuple(float(np.interp(x, np.linspace(0, 1, len(key)), [k[m] for k in key])) for m in range(4)) for x in f]
    tongue.sweep(pts, shapes, "tongue", N=16, step=0.006, frame="h", start="cap", end="cap")
    F, fwd = pts[-1], (pts[-1] - pts[-2]).normalized()
    for s in (1, -1):  # forked tip
        tip = F + fwd * 0.034 + V((0.010 * s, 0, 0.002))
        tongue.sweep([F - fwd * 0.006, F + fwd * 0.014 + V((0.004 * s, 0, 0.001)), tip],
                     [(0.0065, 0.004, 0.0035, 2.2), (0.004, 0.0028, 0.0025, 2.2), (0.0008, 0.0008, 0.0008, 2.0)],
                     "tongue", N=10, step=0.004, frame="h", start="cap", end="tip", tip=1.0)
    return tongue, round((pts[-1] - pts[0]).length + 0.034, 3)


def build_inserts(collection, parent, tree, trunk_path, arm_path, B, eye_ref, prof):
    rng = np.random.default_rng(6)
    eye_parts, eye_center = build_eyes(eye_ref)
    LOG["eye_center"] = tuple(round(v, 4) for v in eye_center)

    horns = pm.Part("DRG_Horns")
    horns.sweep(HORN_PTS, [(r * 0.85, r, r, 2.0) for r in HORN_R], "horn", N=14, step=0.007, tip=1.0,
                scale_fn=lambda s, L: 1.0 + 0.07 * max(0.0, math.sin(2 * math.pi * s / 0.028)) ** 2 * max(0.0, 1 - s / (0.75 * L)))
    # jugal (cheek) spikes behind the jaw angle, pointing back and out
    n_cheek = 0
    for y, z, L in ((-0.80, 1.14, 0.032), (-0.775, 1.165, 0.025), (-0.825, 1.115, 0.020)):
        try:
            base, nrm = surface_hit(tree, hx((0.0, y, z)), SIDE)
        except RuntimeError:
            continue
        L *= HEAD_SCALE
        d = (nrm * 0.45 + Y * 0.85 - Z * 0.12).normalized()
        base = base - nrm * 0.004
        horns.sweep([base, base + d * L * 0.5 + nrm * L * 0.06, base + d * L],
                    [(0.13 * L, 0.20 * L, 0.20 * L, 2.0), (0.08 * L, 0.12 * L, 0.12 * L, 2.0), (0.001, 0.001, 0.001, 2.0)],
                    "spike", N=8, step=max(L / 5, 0.004), frame="hint", hint=Z, tip=1.0)
        n_cheek += 1
    LOG["cheek_spikes_per_side"] = n_cheek

    spikes = pm.Part("DRG_DorsalSpikes")
    sizes = [(0.0, 0.026), (0.12, 0.04), (0.25, 0.066), (0.42, 0.062), (0.6, 0.046), (0.92, 0.014)]
    s_pos, n_spk = 0.08, 0
    while s_pos < trunk_path.length * 0.92:
        p, t, _ = trunk_path.at(s_pos)
        side = t.cross(Z).normalized()
        dorsal = side.cross(t).normalized()
        try:
            base, nrm = surface_hit(tree, p + dorsal * 0.2, -dorsal)
        except RuntimeError:
            s_pos += 0.07
            continue
        # alternating major/minor spikes with +/-8 % seeded jitter and varied rake (Exp 5: uniform series)
        h = float(np.interp(s_pos / trunk_path.length, [a for a, _ in sizes], [b for _, b in sizes]))
        h *= (1.0 if n_spk % 2 == 0 else 0.74) * (1.0 + rng.uniform(-0.08, 0.08))
        rake = 0.55 + rng.uniform(-0.1, 0.1)
        base = base - nrm * 0.006
        spikes.sweep([base, base + nrm * h * 0.45 + t * h * 0.12, base + nrm * h * 0.92 + t * h * rake],
                     [(0.15 * h, 0.42 * h, 0.42 * h, 2.0), (0.10 * h, 0.24 * h, 0.30 * h, 2.0), (0.003, 0.004, 0.004, 2.0)],
                     "spike", N=8, step=max(h / 5, 0.005), frame="hint", hint=side, tip=1.0)
        n_spk += 1
        s_pos += 0.07 if s_pos < trunk_path.length * 0.5 else 0.065
    LOG["dorsal_spikes"] = n_spk

    claws = pm.Part("DRG_Claws")
    LOG["claw_drop"] = [round(claw_clamped(claws, tip, d, cl, r), 3) for tip, d, r, cl in TOE_TIPS]
    pm.claw(claws, W_W + V((0.0, -0.03, 0.025)), V((0.15, -0.75, 0.55)), 0.06, 0.012)

    teeth, LOG["teeth"] = build_teeth(tree, prof)
    tongue, LOG["tongue_length_m"] = build_tongue(tree, prof)

    frames = pm.Part("DRG_WingFingers")
    frames.sweep([W_W + V((-0.03, 0.01, -0.02)), W_W + V((0.03, -0.01, 0.02))],
                 [(0.032, 0.032, 0.032, 2.0), (0.030, 0.030, 0.030, 2.0)], "skin", N=14, step=0.012, start="tip", end="tip", tip=0.7)
    fpaths = []
    for T in W_TIPS:
        frames.sweep([W_W, finger_mid(T), T], [(0.019, 0.019, 0.019, 2.0), (0.014, 0.015, 0.015, 2.0), (0.004, 0.004, 0.004, 2.0)],
                     "skin", N=12, step=0.025, start="cap", end="tip", tip=1.0,
                     scale_fn=lambda s, L: 1.0 + 0.18 * math.exp(-((s / L - 0.42) / 0.06) ** 2))
        fpaths.append(pm.Path([W_W, finger_mid(T), T]))

    memb = pm.Part("DRG_WingMembranes")
    inward = dirn(-0.5, 0, -0.87)
    guesses = [(0.17, -0.06, 0.84), (0.18, 0.06, 0.78), (0.18, 0.19, 0.78), (0.17, 0.32, 0.80)]
    attach = [surface_hit(tree, g, inward)[0] + inward * 0.006 for g in guesses]
    A = attach[-1]
    s0 = arc_at_u(arm_path, 1.0)

    def arm(u):
        return arm_path.at(s0 + u * (arm_path.length - s0))[0]
    body_line = pm.Path([B] + attach)
    for i in range(3):
        Ti, Tj = W_TIPS[i], W_TIPS[i + 1]
        depth = 0.20 * (Ti - Tj).length
        toward = (W_W - Ti.lerp(Tj, 0.5)).normalized()
        nn = (Ti - W_W).cross(Tj - W_W).normalized()
        sag = (nn if nn.z < 0 else -nn) * 0.035

        def fn(u, v, i=i, depth=depth, toward=toward, sag=sag):
            p = fpaths[i].point(u).lerp(fpaths[i + 1].point(u), v)
            return p + toward * depth * math.sin(math.pi * v) * u ** 3 + sag * math.sin(math.pi * v) * math.sin(math.pi * u * 0.75)
        memb.patch(fn, 16, 7, fpaths[i].length, (Ti - Tj).length, "membrane")
    T4 = W_TIPS[3]
    in_toward = (W_W - A.lerp(T4, 0.5)).normalized()
    nn = (T4 - W_W).cross(A - W_W).normalized()
    in_sag = (nn if nn.x > 0 else -nn) * 0.02

    def inner(u, v):
        c0, c1 = arm(u), A.lerp(T4, u) + in_toward * 0.16 * (T4 - A).length * math.sin(math.pi * u)
        d0, d1 = body_line.point(v), fpaths[3].point(v)
        bil = B * (1 - u) * (1 - v) + W_W * u * (1 - v) + A * (1 - u) * v + T4 * u * v
        return (1 - v) * c0 + v * c1 + (1 - u) * d0 + u * d1 - bil + in_sag * math.sin(math.pi * u) * math.sin(math.pi * v)
    memb.patch(inner, 18, 16, (W_W - B).length, (A - B).length, "membrane")

    def front(u, v):
        lead = B.lerp(W_W, u) + (W_E - B.lerp(W_W, 0.5)).normalized() * 0.05 * math.sin(math.pi * u)
        return lead.lerp(arm(u), v)
    memb.patch(front, 18, 4, (W_W - B).length, 0.1, "membrane")
    memb.pack_uvs()
    bmesh.ops.remove_doubles(memb.bm, verts=memb.bm.verts[:], dist=1e-5)
    bmesh.ops.dissolve_degenerate(memb.bm, dist=1e-6, edges=memb.bm.edges[:])
    bmesh.ops.solidify(memb.bm, geom=memb.bm.faces[:], thickness=0.006)
    for f in memb.bm.faces:
        f.smooth = True

    objs = []
    for part, mirror in ([(p, True) for p in eye_parts] + [(horns, True), (spikes, False), (claws, True), (teeth, True),
                                                          (tongue, False), (frames, True), (memb, True)]):
        if part is not memb and not getattr(part, "packed", False):
            part.pack_uvs()
        if mirror:
            part.mirror_x()
        objs.append(to_object(part, collection, parent))
    return objs


# =========================================================================== game mesh + bake
REGIONS = {"tail": lambda v: v[:, 1] > 0.45, "toes_feet": lambda v: v[:, 2] < 0.06, "head": lambda v: v[:, 1] < -0.72,
           "wing_arm": lambda v: (np.abs(v[:, 0]) > 0.3) & (v[:, 2] > 0.85)}


def deviation(sample, ob):
    tree = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    d = np.array([tree.find_nearest(p)[3] for p in sample]) * 1000.0
    out, rest = {}, np.ones(len(sample), bool)
    for name, test in REGIONS.items():
        m = test(sample)
        rest &= ~m
        out[name] = {"max_mm": round(float(d[m].max()), 1), "mean_mm": round(float(d[m].mean()), 2)}
    out["rest"] = {"max_mm": round(float(d[rest].max()), 1), "mean_mm": round(float(d[rest].mean()), 2)}
    out["all"] = {"max_mm": round(float(d.max()), 1), "mean_mm": round(float(d.mean()), 2), "p99_mm": round(float(np.percentile(d, 99)), 1)}
    return out


def gate_ok(dev):
    return all(v["max_mm"] <= GATE_MAX_MM and v["mean_mm"] <= GATE_MEAN_MM for k, v in dev.items() if k != "all")


def duplicate(src, name, col):
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = ob.data.name = name
    col.objects.link(ob)
    return ob


def apply_mods(ob):
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    ob.modifiers.clear()
    old = ob.data
    ob.data = me
    bpy.data.meshes.remove(old)


def select_only(*obs, active=None):
    for o in bpy.context.scene.objects:
        if o is not None:
            o.select_set(False)
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or obs[0]


def bake_maps(high, low, ov):
    """Bake normal, colour, roughness and AO from the high-res body (with its detail shader) onto the game mesh."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    mat = bpy.data.materials.new("DRG6_body_baked")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    texs, rec = {}, {}
    for key, size in BAKE.items():
        img = bpy.data.images.new(f"DRG6_Body_{key}", size, size, alpha=False, float_buffer=False)
        img.colorspace_settings.name = "sRGB" if key == "color" else "Non-Color"
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        texs[key] = tex
    low.data.materials.clear()
    low.data.materials.append(mat)
    jobs = [("normal", "NORMAL", 1, {}), ("color", "DIFFUSE", 1, {"pass_filter": {"COLOR"}}),
            ("roughness", "ROUGHNESS", 1, {}), ("ao", "AO", 64, {})]
    select_only(high, low, active=low)
    for key, btype, samples, extra in jobs:
        scene.cycles.samples = samples
        scene.render.bake.margin = 16 if BAKE[key] >= 4096 else 8
        nt.nodes.active = texs[key]
        t = time.perf_counter()
        kw = dict(type=btype, use_selected_to_active=True, cage_extrusion=0.015, max_ray_distance=0.05, **extra)
        if btype == "NORMAL":
            kw["normal_space"] = "TANGENT"
        with bpy.context.temp_override(**dict(ov, active_object=low, object=low, selected_objects=[high, low],
                                              selected_editable_objects=[high, low])):
            try:
                res = str(bpy.ops.object.bake(**kw))
            except RuntimeError as exc:
                res = f"failed: {exc}"
                LOG["errors"].append(f"bake {key}: {exc}")
        texs[key].image.pack()
        px = np.empty(BAKE[key] * BAKE[key] * 4, np.float32)
        texs[key].image.pixels.foreach_get(px)
        rec[key] = {"size": BAKE[key], "result": res, "seconds": round(time.perf_counter() - t, 2),
                    "mean_rgb": [round(float(v), 3) for v in px.reshape(-1, 4)[:, :3].mean(0)]}
    # game shader: colour x AO, roughness map, tangent-space normal map
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
    dm.sock(mul.inputs, "Factor_Float").default_value = 1.0
    nt.links.new(texs["color"].outputs["Color"], dm.sock(mul.inputs, "A_Color"))
    nt.links.new(texs["ao"].outputs["Color"], dm.sock(mul.inputs, "B_Color"))
    nt.links.new(dm.sock(mul.outputs, "Result_Color"), bsdf.inputs["Base Color"])
    nt.links.new(texs["roughness"].outputs["Color"], bsdf.inputs["Roughness"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(texs["normal"].outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return rec


def build_game_mesh(high, col, ov):
    sample = sd.coords(high.data)[::8]
    rec = {}
    q = duplicate(high, "DRG_Body_QF", col)
    select_only(q)
    t = time.perf_counter()
    with bpy.context.temp_override(**dict(ov, active_object=q, object=q, selected_objects=[q], selected_editable_objects=[q])):
        try:
            bpy.ops.object.quadriflow_remesh(target_faces=RETOPO_TARGET_FACES, use_mesh_symmetry=False, use_preserve_sharp=False,
                                             use_preserve_boundary=False, seed=0, mode="FACES")
        except RuntimeError as exc:
            rec["quadriflow_error"] = repr(exc)
    sw = q.modifiers.new("Project", "SHRINKWRAP")
    sw.target, sw.wrap_method = high, "NEAREST_SURFACEPOINT"
    apply_mods(q)
    rec["quadriflow"] = {"faces": len(q.data.polygons), "seconds": round(time.perf_counter() - t, 2), "deviation": deviation(sample, q)}
    rec["quadriflow"]["accepted"] = gate_ok(rec["quadriflow"]["deviation"])
    if rec["quadriflow"]["accepted"]:
        low = q
    else:
        bpy.data.objects.remove(q)
        low = duplicate(high, "DRG_Body_Decimated", col)
        t = time.perf_counter()
        ratio = DECIMATE_TARGET_TRIS / (2.0 * len(high.data.polygons))
        m = low.modifiers.new("Decimate", "DECIMATE")
        m.decimate_type, m.use_collapse_triangulate, m.ratio = "COLLAPSE", True, ratio
        apply_mods(low)
        low.data.calc_loop_triangles()
        rec["decimate"] = {"ratio": round(ratio, 4), "triangles": len(low.data.loop_triangles),
                           "seconds": round(time.perf_counter() - t, 2), "deviation": deviation(sample, low)}
    low.name = low.data.name = "DRG_Body"
    for a in [a.name for a in low.data.attributes if a.name in ("body_st", "w_up", "w_dorsal", "w_belly", "w_head",
                                                                  "w_tail", "w_foot", "w_lip", "w_mouth")]:
        low.data.attributes.remove(low.data.attributes[a])  # baked into textures; not needed on the game mesh
    select_only(low)
    with bpy.context.temp_override(**dict(ov, active_object=low, object=low, selected_objects=[low], selected_editable_objects=[low])):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        rec["smart_uv"] = str(bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.003))
        bpy.ops.object.mode_set(mode="OBJECT")
    low.data.shade_smooth()
    t = time.perf_counter()
    rec["bake"] = bake_maps(high, low, ov)
    rec["bake_seconds"] = round(time.perf_counter() - t, 2)
    camera_setup.configure_render(bpy.context.scene)
    low.data.calc_loop_triangles()
    rec["low_triangles"] = len(low.data.loop_triangles)
    return low, rec


def save_blend(path):
    tmp = os.path.join(tempfile.mkdtemp(prefix="drg6_"), os.path.basename(path))
    bpy.ops.wm.save_as_mainfile(filepath=tmp, compress=False, copy=True)
    shutil.move(tmp, camera_setup._long_path(path))


# =========================================================================== pipeline
def run():
    bpy.context.preferences.filepaths.save_version = 0
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    DM.update(dm.build_all())
    scene = bpy.context.scene
    dragon = camera_setup.ensure_collection("Dragon", scene)
    root = bpy.data.objects.new("DRG_Root", None)
    dragon.objects.link(root)
    camera_setup.build_rig(scene)

    # Phase 1: lofts -> one fused shell
    bm, trunk_path, arm_path, B = build_body_base()
    me = bpy.data.meshes.new("DRG_Body_HighRes")
    bm.to_mesh(me)
    bm.free()
    high = bpy.data.objects.new("DRG_Body_HighRes", me)
    dragon.objects.link(high)
    high.parent = root
    select_only(high)
    LOG["loft_faces"] = len(me.polygons)
    sub = high.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = sub.render_levels = 2
    apply_mods(high)
    LOG["subdivided_loft_faces"] = len(high.data.polygons)
    mark("lofts_built")
    sc = None if DRY_RUN else sd.Sculptor(high, LOG)
    ov = sc.ov() if sc else {"active_object": high, "object": high}
    me = high.data
    me.remesh_voxel_size = VOXEL
    me.remesh_voxel_adaptivity = 0.0
    for prop in ("use_remesh_fix_poles", "use_remesh_preserve_volume"):
        if hasattr(me, prop):
            setattr(me, prop, True)
    with bpy.context.temp_override(**ov):
        bpy.ops.object.voxel_remesh()
    high.data.shade_smooth()
    LOG["fused_faces"] = len(high.data.polygons)
    mark("voxel_fused")

    # sculpted junctions, secondary and tertiary forms
    if sc:
        sc.mode("SCULPT")
        sc.phase = "junctions"
        sc.cavity_fillet(iterations=30)
        for s in S1_JUNCTIONS:
            sc.stroke(s)
        sc.phase = "secondary"
        for s in S2_SECONDARY + S2_POLISH:
            sc.stroke(s)
        sc.phase = "secondary_detail"
        for s in S2_DETAIL:
            sc.stroke(s)
        sc.phase = "tertiary"
        for s in S3_TERTIARY:
            sc.stroke(s)
        sc.mode("OBJECT")
    mark("sculpted" if sc else "sculpt_skipped_dry_run")

    # procedural eye sockets, nostrils, ear openings
    high.data.update()
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    eye_ref = surface_hit(tree, hx((0.0, -0.90, 1.212)), -(V((math.cos(rad(16)), 0, math.sin(rad(16))))))
    nos_ref = surface_hit(tree, hx((0.0, -1.115, 1.175)), -(V((math.cos(rad(64)), 0, math.sin(rad(64))))))
    ear_ref = surface_hit(tree, hx((0.0, -0.775, 1.215)), -(V((math.cos(rad(8)), 0, math.sin(rad(8))))))
    hs = HEAD_SCALE
    for (p, n), (r_, dep, rim, ub) in ((eye_ref, (0.024 * hs, 0.009 * hs, 0.005 * hs, 2.5)),
                                       (nos_ref, (0.011 * hs, 0.010, 0.0025, 0.0)),
                                       (ear_ref, (0.012, 0.0035, 0.0012, 0.0))):
        for s in (1, -1):
            LOG.setdefault("displaced_vertices", []).append(displace(high.data, mx(p, s), mx(n, s), r_, dep, rim, ub))
    mark("displaced")

    # mouth analysis and body fields for the detail shader
    high.data.update()
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    prof = mouth_profile(tree)
    LOG["mouth_profile"] = [{k: round(v, 4) for k, v in p.items()} for p in prof]
    w_mouth = mouth_weights(high.data, tree, prof)
    c = sd.coords(high.data)
    head_mask = (c[:, 1] < hx((0, -0.70, 0)).y) & (c[:, 2] > 0.95)
    w_lip = lip_weights(c, w_mouth, head_mask)
    LOG["field_vertices_over_half"] = body_fields(high.data, w_mouth, w_lip)
    high.data.materials.append(DM["body"])
    mark("fields_written")
    inserts = build_inserts(dragon, root, tree, trunk_path, arm_path, B, eye_ref, prof)
    LOG["inserts"] = {o.name: len(o.data.polygons) for o in inserts}
    mark("inserts_built")
    save_blend(os.path.join(OUT, "dragon_detail_highres.blend"))
    mark("highres_saved")

    low, rec = build_game_mesh(high, dragon, ov)
    low.parent = root
    LOG["game_mesh"] = rec
    mark("game_mesh_baked")
    bpy.data.objects.remove(high)
    save_blend(os.path.join(OUT, "dragon_detail.blend"))
    mark("game_saved")
    LOG["objects"] = [o.name for o in dragon.objects]


def tick():
    try:
        run()
    except Exception:  # noqa: BLE001
        LOG["errors"].append(traceback.format_exc())
        print(traceback.format_exc())
    LOG["total_seconds"] = round(time.perf_counter() - T0, 2)
    LOG["output_dir"] = OUT
    with open(camera_setup._long_path(os.path.join(OUT, "detail_log.json")), "w", encoding="utf-8") as fh:
        json.dump(LOG, fh, indent=1, default=str)
    bpy.ops.wm.quit_blender()


if DRY_RUN:
    print(f"[bench] DRY RUN (no sculpt) -> {OUT}")
    tick()
elif bpy.app.background:
    raise SystemExit("dragon_detail.py needs the Blender GUI (sculpt mode crashes Blender 5.2.2 with -b).")
else:
    bpy.app.timers.register(tick, first_interval=2.0)
