"""Experiment 5 - Hybrid modeling workflow (each technique assigned to the problem it solves).

  Proportions/primary forms  controlled cross-section lofts (Exp 2: best silhouette and proportions)
  Junctions                  voxel fusion of all body lofts + cavity-masked smoothing (Exp 3: removes
                             the interpenetration creases Exp 2 left at limb/neck/wing roots)
  Secondary/tertiary forms   closed-loop scripted sculpt strokes (Exp 3: best surface anatomy)
  Eye sockets, nostrils      procedural displacement (Exp 2 rev 4: precise sockets with lids)
  Wings                      lofted finger frame + Coons/ruled membrane patches (Exp 2), kept separate
                             from the fused body so thin fingers are not lost to voxel resolution
  Horns, spikes, claws, eyes curve-sweep inserts
  Game mesh                  retopology gated by a measured deviation check, Decimate fallback (Exp 3)
  Small surface detail       normal map baked from the high-res sculpt onto the game mesh
  Materials                  shared palette; belly as a smooth vertex weight (Exp 3), palette roughness

Needs the Blender GUI (sculpt mode crashes Blender 5.2.2 in background mode):
  blender --factory-startup --window-geometry 0 0 1400 1000 --python dragon_hybrid.py
Writes dragon_hybrid.blend (game version), dragon_hybrid_highres.blend, hybrid_log.json, then quits.
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402
import material_palette as mp  # noqa: E402
import proc_mesh as pm  # noqa: E402
import sculpt_driver as sd  # noqa: E402

REVISION = 3  # v1 initial; v2 fixes the three most important v1 defects; v3 fixes the misdiagnosed membrane crack
VOXEL = 0.005
RETOPO_TARGET_FACES = 12000
DECIMATE_TARGET_TRIS = 24000
GATE_MAX_MM, GATE_MEAN_MM = 12.0, 2.0     # retopology accepted only if every region stays within these
NORMAL_MAP_SIZE = 2048
V, X, Z = Vector, Vector((1, 0, 0)), Vector((0, 0, 1))
LOG = {"experiment": "05_hybrid", "revision": REVISION, "blender": bpy.app.version_string, "voxel_size": VOXEL,
       "timings": {}, "strokes": [], "filters": [], "errors": []}


def rad(d):
    return math.radians(d)


def dirn(*v):
    return V(v).normalized()


def mx(p, s):
    return V((p[0] * s, p[1], p[2]))


def mark(name):
    LOG["timings"][name] = round(time.perf_counter() - T0, 2)
    print(f"[bench] {name} @ {LOG['timings'][name]} s")


SIDE, FRONT, TOP, BELOW = dirn(-1, 0, 0), dirn(0, 1, 0), dirn(0, 0, -1), dirn(0, 0, 1)

# =========================================================================== shape data (Exp 2 rev 4)
TRUNK_PTS = [(0, -0.80, 1.19), (0, -0.73, 1.115), (0, -0.67, 1.005), (0, -0.61, 0.895), (0, -0.51, 0.795),
             (0, -0.36, 0.72), (0, -0.18, 0.685), (0, 0.05, 0.655), (0, 0.30, 0.67), (0, 0.50, 0.655),
             (0, 0.74, 0.58), (0.04, 1.00, 0.45), (0.13, 1.26, 0.30), (0.22, 1.50, 0.19), (0.30, 1.73, 0.13)]
TRUNK_SHAPES = [(0.062, 0.070, 0.072, 2.0, 0.0, 0.0), (0.058, 0.062, 0.070, 2.1, 0.0, 0.004),
                (0.066, 0.066, 0.080, 2.2, 0.0, 0.006), (0.088, 0.082, 0.105, 2.2, 0.0, 0.007),
                (0.130, 0.110, 0.150, 2.3, 0.005, 0.008), (0.215, 0.200, 0.260, 2.5, 0.020, 0.010),
                (0.205, 0.205, 0.245, 2.5, 0.015, 0.012), (0.165, 0.190, 0.175, 2.4, 0.0, 0.012),
                (0.190, 0.200, 0.175, 2.5, 0.0, 0.012), (0.140, 0.150, 0.130, 2.3, 0.0, 0.010),
                (0.095, 0.100, 0.085, 2.2, 0.0, 0.008), (0.066, 0.068, 0.058, 2.1, 0.0, 0.006),
                (0.043, 0.044, 0.038, 2.0, 0.0, 0.004), (0.024, 0.025, 0.021, 2.0, 0.0, 0.002),
                (0.003, 0.003, 0.003, 2.0, 0.0, 0.0)]
HEAD_PTS = [(0, -1.165, 1.168), (0, -1.135, 1.174), (0, -1.05, 1.180), (0, -0.97, 1.190), (0, -0.905, 1.212),
            (0, -0.845, 1.222), (0, -0.785, 1.218), (0, -0.745, 1.206), (0, -0.722, 1.198)]
HEAD_SHAPES = [(0.012, 0.012, 0.012, 2.0, 0.0, 0.0, 0.0), (0.044, 0.040, 0.030, 2.6, 0.0, 0.0, 0.0),
               (0.056, 0.046, 0.036, 3.2, 0.0, 0.0, 0.0), (0.066, 0.056, 0.040, 3.0, 0.006, 0.004, 0.0),
               (0.086, 0.082, 0.050, 2.8, 0.042, 0.010, 0.006), (0.108, 0.096, 0.064, 2.6, 0.014, 0.034, 0.010),
               (0.104, 0.090, 0.070, 2.4, 0.004, 0.030, 0.008), (0.070, 0.066, 0.058, 2.2, 0.0, 0.006, 0.0),
               (0.008, 0.008, 0.008, 2.0, 0.0, 0.0, 0.0)]
JAW_PTS = [(0, -1.118, 1.130), (0, -1.085, 1.127), (0, -0.99, 1.128), (0, -0.89, 1.138), (0, -0.815, 1.152), (0, -0.79, 1.158)]
JAW_SHAPES = [(0.010, 0.010, 0.010, 2.0), (0.030, 0.020, 0.018, 2.6), (0.044, 0.024, 0.026, 2.8),
              (0.062, 0.027, 0.036, 2.6), (0.070, 0.032, 0.048, 2.4), (0.010, 0.010, 0.010, 2.0)]
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
HORN_PTS = [(0.042, -0.80, 1.265), (0.058, -0.755, 1.315), (0.083, -0.67, 1.352), (0.103, -0.575, 1.36),
            (0.115, -0.495, 1.335), (0.119, -0.45, 1.295)]
HORN_R = [0.030, 0.026, 0.019, 0.012, 0.006, 0.001]
TOE_TIPS = []  # (tip, direction, claw radius) on the left side
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
def paw(part, center, fwd, toe_angles, toe_len, toe_r, claw_len, back_toe):
    fwd, c = V(fwd).normalized(), V(center)
    part.sweep([c - fwd * 0.05 + V((0, 0, 0.006)), c + V((0, 0, 0.002)), c + fwd * 0.042, c + fwd * 0.056],
               [(0.036, 0.026, 0.020, 2.6), (0.055, 0.028, 0.020, 2.8), (0.057, 0.022, 0.018, 2.8), (0.033, 0.015, 0.012, 2.4)],
               "skin", N=16, step=0.012, start="tip", end="tip", tip=0.5)
    dirs = [(Matrix.Rotation(rad(a), 3, "Z") @ fwd, toe_len, toe_r, claw_len) for a in toe_angles]
    if back_toe:
        dirs.append((Matrix.Rotation(rad(12), 3, "Z") @ -fwd, toe_len * 0.5, toe_r * 0.8, claw_len * 0.7))
    for d, ln, r0, cl in dirs:
        base = c + d * (0.022 if d.dot(fwd) > 0 else 0.03) + V((0, 0, -0.002 if d.dot(fwd) > 0 else 0.0))
        tip = base + d * ln + V((0, 0, -0.006))
        part.sweep([base - d * 0.012, base + d * ln * 0.5 + V((0, 0, 0.004)), tip],
                   [(r0, r0 * 0.9, r0 * 0.9, 2.2), (r0 * 1.08, r0, r0, 2.2), (r0 * 0.82, r0 * 0.75, r0 * 0.75, 2.2)],
                   "skin", N=10, step=0.012, start="cap", end="tip", tip=0.8)
        TOE_TIPS.append((tip + d * 0.002 + V((0, 0, 0.004)), d, r0 * 0.72, cl))


def build_body_base():
    trunk = pm.Part("trunk")
    trunk_path = trunk.sweep(TRUNK_PTS, TRUNK_SHAPES, "skin", N=32, step=0.025, start="cap", end="tip", tip=1.5,
                             bumps=[(1.5 * math.pi, 0.35, 4), (0.5 * math.pi, 0.22, 5)])
    trunk.bm.normal_update()
    tbvh = BVHTree.FromBMesh(trunk.bm)
    inward = dirn(-0.5, 0, -0.87)
    B = surface_hit(tbvh, (0.15, -0.19, 0.90), inward)[0] + inward * 0.004
    head = pm.Part("head")
    head.sweep(HEAD_PTS, HEAD_SHAPES, "skin", N=40, step=0.008, start="tip", end="tip",
               bumps=[(BROW, 0.28, 4), (math.pi - BROW, 0.28, 4), (CHEEK, 0.40, 5), (math.pi - CHEEK, 0.40, 5),
                      (0.5 * math.pi, 0.15, 6)])
    head.sweep(JAW_PTS, JAW_SHAPES, "skin", N=24, step=0.01, start="tip", end="tip")
    limbs = pm.Part("limbs")
    limbs.sweep(FRONT_PTS, FRONT_SHAPES, "skin", N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
    limbs.sweep(HIND_PTS, HIND_SHAPES, "skin", N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
    paw(limbs, (0.25, -0.37, 0.03), (math.sin(rad(8)), -math.cos(rad(8)), 0), (-26, 0, 26), 0.062, 0.020, 0.047, False)
    paw(limbs, (0.25, 0.36, 0.03), (math.sin(rad(6)), -math.cos(rad(6)), 0), (-24, 0, 24), 0.072, 0.022, 0.052, True)
    # wing arm (humerus + forearm) is fused into the body: thick enough for the voxel resolution
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


# =========================================================================== sculpt programme (Phases 2/4/5)
def throat_scutes():
    neck = pm.Path(TRUNK_PTS[:6])
    out = []
    for z in np.arange(0.86, 1.10, 0.035):
        p = min((s for s, _ in neck.samples), key=lambda q: abs(q.z - z))
        out.append(sd.spec("Crease Sharp", 0.006, 0.2, FRONT, [(0.0, p.y - 0.25, z), (0.045, p.y - 0.25, z)], "throat scute", 1.5))
    return out


def belly_scutes():
    return [sd.spec("Crease Sharp", 0.006, 0.2, BELOW, [(0.0, y, 0.3), (0.12 if y < 0 else 0.10, y, 0.3)], "belly scute", 1.5)
            for y in np.arange(-0.45, 0.32, 0.05)]


S1_JUNCTIONS = [
    sd.spec("Smooth", 0.05, 0.6, SIDE, [(0.24, -0.40, 0.60), (0.25, -0.30, 0.66), (0.24, -0.22, 0.60)], "shoulder junction", passes=3),
    sd.spec("Smooth", 0.06, 0.6, SIDE, [(0.20, 0.30, 0.72), (0.22, 0.42, 0.74), (0.22, 0.52, 0.66)], "thigh junction", passes=3),
    sd.spec("Smooth", 0.045, 0.6, TOP, [(0.12, -0.26, 0.88), (0.17, -0.18, 0.92), (0.12, -0.10, 0.88)], "wing root junction", passes=3),
    sd.spec("Smooth", 0.05, 0.6, dirn(-1, 0.3, -0.3), [(0.07, -0.76, 1.14), (0.06, -0.72, 1.20)], "neck-skull junction", passes=3),
    sd.spec("Smooth", 0.03, 0.6, SIDE, [(0.27, -0.37, 0.06), (0.27, -0.33, 0.11)], "front wrist-paw junction", passes=3),
    sd.spec("Smooth", 0.03, 0.6, SIDE, [(0.27, 0.41, 0.06), (0.27, 0.43, 0.11)], "hind ankle-paw junction", passes=3),
]
S2_SECONDARY = [
    sd.spec("Clay Strips", 0.016, 0.5, dirn(-0.6, 0.6, -0.5), [(0.035, -0.96, 1.285), (0.065, -0.93, 1.28), (0.085, -0.89, 1.27)], "brow ridge", 4),
    sd.spec("Crease Sharp", 0.010, 0.5, SIDE, [(0.04, -1.12, 1.152), (0.05, -1.05, 1.149), (0.06, -0.98, 1.150), (0.07, -0.91, 1.156), (0.075, -0.86, 1.165)], "mouth line", 3),
    sd.spec("Crease Sharp", 0.012, 0.4, dirn(-1, 0, 0.35), [(0.06, -0.87, 1.11), (0.07, -0.80, 1.12)], "jaw angle", 3),
    sd.spec("Blob", 0.024, 0.4, dirn(-0.3, 0.3, -1), [(0.05, -0.79, 1.30)], "horn boss", 5),
    sd.spec("Clay", 0.025, 0.45, SIDE, [(0.07, -0.76, 1.12), (0.08, -0.66, 1.00), (0.10, -0.56, 0.86), (0.13, -0.47, 0.76)], "neck muscle", 4),
    sd.spec("Clay", 0.035, 0.45, dirn(-0.4, 1, 0), [(0.04, -0.60, 0.60), (0.11, -0.56, 0.56), (0.16, -0.48, 0.52)], "pectoral", 6),
    sd.spec("Clay", 0.035, 0.45, SIDE, [(0.22, -0.40, 0.62), (0.25, -0.31, 0.62), (0.24, -0.22, 0.56)], "deltoid", 6),
    sd.spec("Clay", 0.030, 0.35, TOP, [(0.10, -0.40, 0.90), (0.13, -0.28, 0.92), (0.14, -0.18, 0.90)], "scapula", 4),
    sd.spec("Clay", 0.018, 0.25, SIDE, [(0.20, -0.20, 0.75), (0.19, -0.12, 0.55)], "rib 1", 2.5),
    sd.spec("Clay", 0.018, 0.25, SIDE, [(0.19, -0.10, 0.76), (0.18, -0.02, 0.57)], "rib 2", 2.5),
    sd.spec("Clay", 0.018, 0.25, SIDE, [(0.18, 0.00, 0.76), (0.17, 0.08, 0.58)], "rib 3", 2.5),
    sd.spec("Clay", 0.035, 0.45, SIDE, [(0.27, 0.30, 0.58), (0.29, 0.27, 0.48), (0.28, 0.26, 0.40)], "quadriceps", 6),
    sd.spec("Clay", 0.030, 0.40, dirn(-1, -0.4, 0), [(0.25, 0.50, 0.62), (0.27, 0.45, 0.48)], "hamstring", 5),
    sd.spec("Clay", 0.022, 0.35, SIDE, [(0.27, -0.22, 0.30), (0.27, -0.28, 0.18)], "forearm", 3),
    sd.spec("Clay", 0.025, 0.35, dirn(-1, -0.3, 0), [(0.27, 0.30, 0.32), (0.27, 0.38, 0.24)], "calf", 3),
    sd.spec("Inflate/Deflate", 0.040, 0.30, TOP, [(0.15, -0.19, 0.92)], "wing shoulder", 4),
    sd.spec("Clay", 0.030, 0.35, TOP, [(0.04, 0.52, 0.80), (0.04, 0.70, 0.68)], "tail root muscle", 4),
]
CONVEX_MUSCLES = {"pectoral": 5, "deltoid": 5, "quadriceps": 5, "hamstring": 4, "calf": 3, "forearm": 3}
if REVISION >= 2:
    # v2 fix 3: Clay's planar flattening cut dents into strongly convex limbs at stroke ends (chest dimple,
    # notch above the knee in v1). Rounded muscle masses on limbs use Inflate/Deflate; Clay stays on flat areas.
    S2_SECONDARY = [sd.spec("Inflate/Deflate", s["r"], 0.3, s["view"], s["pts"], s["label"], CONVEX_MUSCLES[s["label"]])
                    if s["label"] in CONVEX_MUSCLES else s for s in S2_SECONDARY]
S2_POLISH = [
    sd.spec("Smooth", 0.06, 0.35, dirn(-0.4, 1, 0), [(0.03, -0.62, 0.66), (0.12, -0.56, 0.58), (0.18, -0.46, 0.52)], "polish chest", passes=2),
    sd.spec("Smooth", 0.06, 0.35, SIDE, [(0.21, -0.36, 0.72), (0.20, -0.14, 0.70), (0.18, 0.08, 0.68)], "polish flank", passes=2),
    sd.spec("Smooth", 0.05, 0.35, SIDE, [(0.27, 0.34, 0.62), (0.28, 0.28, 0.48), (0.28, 0.26, 0.38)], "polish thigh", passes=2),
    sd.spec("Smooth", 0.04, 0.35, SIDE, [(0.24, -0.36, 0.60), (0.25, -0.26, 0.46), (0.26, -0.22, 0.34)], "polish upper arm", passes=2),
    sd.spec("Smooth", 0.06, 0.35, TOP, [(0.08, -0.40, 0.90), (0.10, -0.10, 0.86), (0.10, 0.30, 0.86)], "polish back", passes=2),
]
S3_TERTIARY = throat_scutes() + belly_scutes() + [
    sd.spec("Crease Sharp", 0.006, 0.25, SIDE, [(0.07, -0.70, 1.10), (0.075, -0.66, 1.06), (0.07, -0.63, 1.03)], "neck fold 1", 2),
    sd.spec("Crease Sharp", 0.006, 0.25, SIDE, [(0.075, -0.68, 1.04), (0.08, -0.64, 1.00), (0.075, -0.61, 0.97)], "neck fold 2", 2),
]


# =========================================================================== procedural sockets, belly weight
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
    return np.linalg.norm(c - p, axis=1), p


SPINE = [(0, -1.12, 1.18), (0, -0.98, 1.17), (0, -0.84, 1.18)] + TRUNK_PTS[1:]
LIMB_CHAINS = [[V(p) for p in FRONT_PTS[1:]], [V(p) for p in HIND_PTS[1:]], [W_ROOT, W_E, W_W]]


def belly_weight(me, half_deg=50):
    c = sd.coords(me)
    n = len(c)
    spine = [np.array(p, float) for p, _ in pm.Path(SPINE).samples[::6]]
    best, vdot = np.full(n, 1e9), np.zeros(n)
    for a, b in zip(spine, spine[1:]):
        d, p = seg_dist(c, a, b)
        t = (b - a) / np.linalg.norm(b - a)
        side = np.cross(t, [0, 0, 1.0])
        side /= np.linalg.norm(side)
        r = c - p
        r -= np.outer(r @ t, t)
        r /= np.maximum(np.linalg.norm(r, axis=1), 1e-9)[:, None]
        closer = d < best
        best = np.where(closer, d, best)
        vdot = np.where(closer, r @ np.cross(t, side), vdot)
    limb = np.full(n, 1e9)
    for s in (1, -1):
        for chain in LIMB_CHAINS:
            for a, b in zip(chain, chain[1:]):
                limb = np.minimum(limb, seg_dist(c, np.array(mx(a, s)), np.array(mx(b, s)))[0])
    w = smoothstep(math.cos(rad(half_deg + 7)), math.cos(rad(half_deg - 7)), vdot)
    w *= 1.0 - smoothstep(0.8, 0.95, best / np.maximum(limb, 1e-9))
    attr = me.attributes.get("belly_w") or me.attributes.new("belly_w", "FLOAT", "POINT")
    attr.data.foreach_set("value", w.astype(np.float32))
    return int((w > 0.5).sum())


# =========================================================================== inserts and wings
def build_inserts(collection, parent, tree, trunk_path, arm_path, B, eye_ref):
    eyes = pm.Part("DRG_Eyes")
    ep, en = eye_ref
    eye_r = 0.02
    c = ep - en * (eye_r - 0.003)
    eyes.sphere(c, eye_r, "eye")
    up = (Z - en * en.dot(Z)).normalized()
    eyes.ellipsoid_axes(c + en * (eye_r - 0.0015), en * 0.003, up.cross(en) * 0.0055, up * 0.015, "pupil")

    horns = pm.Part("DRG_Horns")
    horns.sweep(HORN_PTS, [(r * 0.85, r, r, 2.0) for r in HORN_R], "horn", N=12, step=0.008, tip=1.0,
                scale_fn=lambda s, L: 1.0 + 0.07 * max(0.0, math.sin(2 * math.pi * s / 0.028)) ** 2 * max(0.0, 1 - s / (0.75 * L)))

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
        h = float(np.interp(s_pos / trunk_path.length, [a for a, _ in sizes], [b for _, b in sizes]))
        base = base - nrm * 0.006
        spikes.sweep([base, base + nrm * h * 0.45 + t * h * 0.12, base + nrm * h * 0.92 + t * h * 0.55],
                     [(0.15 * h, 0.42 * h, 0.42 * h, 2.0), (0.10 * h, 0.24 * h, 0.30 * h, 2.0), (0.003, 0.004, 0.004, 2.0)],
                     "horn", N=8, step=max(h / 4, 0.006), frame="hint", hint=side, tip=1.0)
        n_spk += 1
        s_pos += 0.07 if s_pos < trunk_path.length * 0.5 else 0.065
    LOG["dorsal_spikes"] = n_spk

    claws = pm.Part("DRG_Claws")
    for tip, d, r, cl in TOE_TIPS:
        pm.claw(claws, tip, d, cl, r)
    pm.claw(claws, W_W + V((0.0, -0.03, 0.025)), V((0.15, -0.75, 0.55)), 0.06, 0.012)

    frames = pm.Part("DRG_WingFingers")  # thin parts stay lofts (not voxel-fused)
    frames.sweep([W_W + V((-0.03, 0.01, -0.02)), W_W + V((0.03, -0.01, 0.02))],
                 [(0.032, 0.032, 0.032, 2.0), (0.030, 0.030, 0.030, 2.0)], "skin", N=14, step=0.012, start="tip", end="tip", tip=0.7)
    fpaths = []
    for T in W_TIPS:
        frames.sweep([W_W, finger_mid(T), T], [(0.019, 0.019, 0.019, 2.0), (0.014, 0.015, 0.015, 2.0), (0.004, 0.004, 0.004, 2.0)],
                     "skin", N=10, step=0.03, start="cap", end="tip", tip=1.0,
                     scale_fn=lambda s, L: 1.0 + 0.18 * math.exp(-((s / L - 0.42) / 0.06) ** 2))
        fpaths.append(pm.Path([W_W, finger_mid(T), T]))

    memb = pm.Part("DRG_WingMembranes")
    inward = dirn(-0.5, 0, -0.87)
    if REVISION >= 2:
        # v2 fix 2: project five points along the flank (v1 projected only three, and the spline between
        # them floated off the curved flank, leaving a visible gap under the inner membrane)
        guesses = [(0.17, -0.06, 0.84), (0.18, 0.06, 0.78), (0.18, 0.19, 0.78), (0.17, 0.32, 0.80)]
        attach = [surface_hit(tree, g, inward)[0] + inward * 0.006 for g in guesses]
    else:
        attach = [surface_hit(tree, g, inward)[0] + inward * 0.004 for g in [(0.18, 0.06, 0.78), (0.17, 0.32, 0.80)]]
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
    # v3: panels that share an edge must sample it identically, or the chords diverge and leave a crack
    # (v2 crack along finger 4: inner panel used 12 segments, the finger panel 16; arm edge 12 vs 18)
    memb.patch(inner, 18, 16 if REVISION >= 3 else 12, (W_W - B).length, (A - B).length, "membrane")

    def front(u, v):
        lead = B.lerp(W_W, u) + (W_E - B.lerp(W_W, 0.5)).normalized() * 0.05 * math.sin(math.pi * u)
        return lead.lerp(arm(u), v)
    memb.patch(front, 18 if REVISION >= 3 else 12, 4, (W_W - B).length, 0.1, "membrane")
    memb.pack_uvs()
    bmesh.ops.remove_doubles(memb.bm, verts=memb.bm.verts[:], dist=1e-5)
    bmesh.ops.dissolve_degenerate(memb.bm, dist=1e-6, edges=memb.bm.edges[:])
    bmesh.ops.solidify(memb.bm, geom=memb.bm.faces[:], thickness=0.006)
    for f in memb.bm.faces:
        f.smooth = True

    objs = []
    for part, mirror in ((eyes, True), (horns, True), (spikes, False), (claws, True), (frames, True), (memb, True)):
        if part is not memb:
            part.pack_uvs()
        if mirror:
            part.mirror_x()
        objs.append(part.to_object(collection, parent))
    return objs


# =========================================================================== Phase 7: game mesh + bake
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
    for o in bpy.context.scene.objects:  # view_layer.objects can hold stale None entries after deletions
        if o is not None:
            o.select_set(False)
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or obs[0]


def build_game_mesh(high, col, ov):
    sample = sd.coords(high.data)[::6]
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
                           "seconds": round(time.perf_counter() - t, 2),
                           "deviation": deviation(sample, low)}
    low.name = low.data.name = "DRG_Body"
    select_only(low)
    with bpy.context.temp_override(**dict(ov, active_object=low, object=low, selected_objects=[low], selected_editable_objects=[low])):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        rec["smart_uv"] = str(bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.002))
        bpy.ops.object.mode_set(mode="OBJECT")
    low.data.shade_smooth()
    rec["belly_vertices"] = belly_weight(low.data)
    # bake tangent-space normals from the high-res sculpt
    img = bpy.data.images.new("DRG_Body_Normal", NORMAL_MAP_SIZE, NORMAL_MAP_SIZE, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    mat = mp.get_blend_material("skin", "belly", "belly_w").copy()
    mat.name = "DRG_skin_belly_blend_baked"
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.nodes.active = tex
    low.data.materials.clear()
    low.data.materials.append(mat)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.bake.margin = 8
    select_only(high, low, active=low)
    t = time.perf_counter()
    with bpy.context.temp_override(**dict(ov, active_object=low, object=low, selected_objects=[high, low],
                                          selected_editable_objects=[high, low])):
        rec["bake"] = str(bpy.ops.object.bake(type="NORMAL", use_selected_to_active=True, cage_extrusion=0.015,
                                              max_ray_distance=0.05, normal_space="TANGENT"))
    rec["bake_seconds"] = round(time.perf_counter() - t, 2)
    img.pack()
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(tex.outputs["Color"], nmap.inputs["Color"])
    for b in (n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"):
        nt.links.new(nmap.outputs["Normal"], b.inputs["Normal"])
    camera_setup.configure_render(scene)
    low.data.calc_loop_triangles()
    rec["low_triangles"] = len(low.data.loop_triangles)
    return low, rec


def save_blend(path):
    tmp = os.path.join(tempfile.mkdtemp(prefix="drghy_"), os.path.basename(path))
    bpy.ops.wm.save_as_mainfile(filepath=tmp, compress=False, copy=True)
    shutil.move(tmp, camera_setup._long_path(path))


# =========================================================================== pipeline
def run():
    bpy.context.preferences.filepaths.save_version = 0
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
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
    if REVISION >= 2:
        # v2 fix 1: Catmull-Clark the lofts before fusing; v1 fused the raw ring facets, which the voxel
        # remesh reproduced faithfully as stripes along limbs and flanks
        sub = high.modifiers.new("Subdivision", "SUBSURF")
        sub.levels = sub.render_levels = 2
        apply_mods(high)
        LOG["subdivided_loft_faces"] = len(high.data.polygons)
    mark("lofts_built")
    sc = sd.Sculptor(high, LOG)
    me = high.data  # apply_mods() replaced the mesh datablock
    me.remesh_voxel_size = VOXEL
    me.remesh_voxel_adaptivity = 0.0
    for prop in ("use_remesh_fix_poles", "use_remesh_preserve_volume"):
        if hasattr(me, prop):
            setattr(me, prop, True)
    with bpy.context.temp_override(**sc.ov()):
        bpy.ops.object.voxel_remesh()
    high.data.shade_smooth()
    LOG["fused_faces"] = len(high.data.polygons)
    mark("voxel_fused")

    # Phases 2-5: sculpted junctions, secondary and tertiary forms
    sc.mode("SCULPT")
    sc.phase = "junctions"
    sc.cavity_fillet(iterations=30)
    for s in S1_JUNCTIONS:
        sc.stroke(s)
    sc.phase = "secondary"
    for s in S2_SECONDARY + S2_POLISH:
        sc.stroke(s)
    sc.phase = "tertiary"
    for s in S3_TERTIARY:
        sc.stroke(s)
    sc.mode("OBJECT")
    mark("sculpted")

    # procedural eye sockets and nostrils (precise, deterministic)
    high.data.update()
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    eye_dir = -(V((math.cos(rad(16)), 0, math.sin(rad(16)))))
    eye_ref = surface_hit(tree, V((0.0, -0.90, 1.212)), eye_dir, reach=0.4)  # head axis at the eye station
    nos_dir = -(V((math.cos(rad(64)), 0, math.sin(rad(64)))))
    nos_ref = surface_hit(tree, V((0.0, -1.115, 1.175)), nos_dir, reach=0.4)
    for (p, n), (rad_, dep, rim, ub) in ((eye_ref, (0.024, 0.009, 0.005, 2.5)), (nos_ref, (0.011, 0.006, 0.0015, 0.0))):
        for s in (1, -1):
            LOG.setdefault("displaced_vertices", []).append(displace(high.data, mx(p, s), mx(n, s), rad_, dep, rim, ub))
    LOG["belly_vertices_high"] = belly_weight(high.data)
    high.data.materials.append(mp.get_blend_material("skin", "belly", "belly_w"))
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    inserts = build_inserts(dragon, root, tree, trunk_path, arm_path, B, eye_ref)
    mark("inserts_built")
    save_blend(os.path.join(HERE, "dragon_hybrid_highres.blend"))
    mark("highres_saved")

    # Phase 7: game mesh (gated retopology / decimate) + normal bake
    low, rec = build_game_mesh(high, dragon, sc.ov())
    low.parent = root
    LOG["game_mesh"] = rec
    mark("game_mesh_baked")
    bpy.data.objects.remove(high)
    save_blend(os.path.join(HERE, "dragon_hybrid.blend"))
    mark("game_saved")
    LOG["objects"] = [o.name for o in dragon.objects]


def tick():
    try:
        run()
    except Exception:  # noqa: BLE001
        LOG["errors"].append(traceback.format_exc())
        print(traceback.format_exc())
    LOG["total_seconds"] = round(time.perf_counter() - T0, 2)
    with open(camera_setup._long_path(os.path.join(HERE, "hybrid_log.json")), "w", encoding="utf-8") as fh:
        json.dump(LOG, fh, indent=1, default=str)
    bpy.ops.wm.quit_blender()


if bpy.app.background:
    raise SystemExit("dragon_hybrid.py needs the Blender GUI (sculpt mode crashes Blender 5.2.2 with -b).")
bpy.app.timers.register(tick, first_interval=2.0)
