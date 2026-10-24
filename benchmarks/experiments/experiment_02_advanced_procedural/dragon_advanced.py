"""Experiment 2 - Advanced procedural modeling (controlled cross-section lofting).

Construction:
  * Trunk: ONE continuous loft (neck -> chest -> abdomen -> hips -> tail tip) of
    superellipse cross-sections with keel / dorsal-ridge bumps.
  * Head: custom loft (snout -> occiput) with brow and cheek bumps, carved eye sockets
    and nostrils (vertex displacement), plus a separate lofted lower jaw.
  * Limbs: lofts along joint chains with per-joint cross-sections (muscle masses,
    elbow/heel knobs), flared roots that blend into the trunk; lofted paws and toes.
  * Horns, dorsal spikes, claws: curve-driven sweeps (Catmull-Rom spline paths with
    tapered elliptical / blade profiles).
  * Wings: lofted bone frame + membrane surfaces built as Coons / ruled patches
    between the finger curves, with billow and scalloped trailing edges, solidified.
  * Smooth shading everywhere; Subdivision Surface level 1 on organic parts only.
  * Loft UVs come from the loft parameterisation and are shelf-packed per object.

Run:  blender -b --factory-startup --python dragon_advanced.py
"""
import bisect
import json
import math
import os
import sys
import time

T_START = time.perf_counter()

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402
import material_palette as mp  # noqa: E402

SCRIPT_REVISION = 4  # rev 2: head/eyelids, limbs, wing billow; rev 3: skull shaping; rev 4: zero-normal bug fix
OUT_BLEND = os.path.join(HERE, "dragon_advanced.blend")
V = Vector
TAU = 2 * math.pi
Z = V((0, 0, 1))
X = V((1, 0, 0))
COUNTS = {"sweeps": 0, "membrane_patches": 0, "displacements": 0, "uv_spheres_eyes": 0}


def rad(d):
    return math.radians(d)


# --------------------------------------------------------------------------- curves
def cr(p0, p1, p2, p3, t):
    return 0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3)


class Path:
    """Catmull-Rom spline through control points, arc-length parameterised."""

    def __init__(self, pts, dense=48):
        P = [V(p) for p in pts]
        ext = [2 * P[0] - P[1]] + P + [2 * P[-1] - P[-2]]
        self.n = len(P)
        self.samples = []
        for i in range(self.n - 1):
            for k in range(dense):
                t = k / dense
                self.samples.append((cr(ext[i], ext[i + 1], ext[i + 2], ext[i + 3], t), i + t))
        self.samples.append((P[-1], float(self.n - 1)))
        self.arc = [0.0]
        for a, b in zip(self.samples, self.samples[1:]):
            self.arc.append(self.arc[-1] + (b[0] - a[0]).length)
        self.length = self.arc[-1]

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        i = min(max(bisect.bisect_left(self.arc, s), 1), len(self.arc) - 1)
        a0, a1 = self.arc[i - 1], self.arc[i]
        f = (s - a0) / (a1 - a0) if a1 > a0 else 0.0
        p0, u0 = self.samples[i - 1]
        p1, u1 = self.samples[i]
        return p0.lerp(p1, f), (p1 - p0).normalized(), u0 + (u1 - u0) * f

    def arc_at_u(self, u):
        for k, (_, uu) in enumerate(self.samples):
            if uu >= u:
                return self.arc[k]
        return self.length


def shape_at(shapes, u):
    n = len(shapes)
    i = min(int(u), n - 2)
    f = u - i
    g = lambda k: shapes[min(max(k, 0), n - 1)]  # noqa: E731
    a, b, c, d = g(i - 1), g(i), g(i + 1), g(i + 2)
    return [cr(a[m], b[m], c[m], d[m], f) for m in range(len(b))]


def frame_axes(t, mode, hint):
    if mode == "h":
        side = t.cross(Z)
    else:
        side = hint - t * t.dot(hint)
    side.normalize()
    return side, side.cross(t)


def ring(center, side, up, w, ap, an, ex, N, bumps=()):
    """Superellipse section. Angle 0 = ventral midline (UV seam), pi/2 = +side, pi = dorsal."""
    pts, e = [], 2.0 / max(ex, 0.5)
    for j in range(N):
        th = 1.5 * math.pi + TAU * j / N
        c, s = math.cos(th), math.sin(th)
        x = w * math.copysign(abs(c) ** e, c)
        y = (ap if s >= 0 else an) * math.copysign(abs(s) ** e, s)
        extra = 0.0
        for ang, width, amp in bumps:
            if amp:
                d = (th - ang + math.pi) % TAU - math.pi
                extra += amp * math.exp(-(d / width) ** 2)
        if extra:
            L = math.hypot(x, y) or 1.0
            x, y = x + x / L * extra, y + y / L * extra
        pts.append(center + side * x + up * y)
    return pts


# --------------------------------------------------------------------------- parts
class Part:
    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.verify()
        self.mats = []
        self.islands = []

    def mi(self, key):
        if key not in self.mats:
            self.mats.append(key)
        return self.mats.index(key)

    def sweep(self, pts, shapes, mat="skin", N=24, step=0.02, frame="h", hint=X, start="cap", end="cap",
              bumps=None, scale_fn=None, mat_fn=None, tip=0.6):
        COUNTS["sweeps"] += 1
        path = Path(pts)
        n = max(2, round(path.length / step))
        rings, recs = [], []
        for k in range(n + 1):
            s = path.length * k / n
            pos, t, u = path.at(s)
            vals = shape_at(shapes, u)
            w, ap, an, ex = (max(vals[0], 0.0008), max(vals[1], 0.0008), max(vals[2], 0.0008), vals[3])
            if scale_fn:
                sc = scale_fn(s, path.length)
                w, ap, an = w * sc, ap * sc, an * sc
            side, up = frame_axes(t, frame, hint)
            bl = [(ang, width, vals[idx]) for ang, width, idx in bumps] if bumps else ()
            rings.append(ring(pos, side, up, w, ap, an, ex, N, bl))
            recs.append({"pos": pos, "t": t, "side": side, "up": up, "s": s, "u": u, "r": (w + ap + an) / 3})
        faces = self._loft(rings, recs, mat, start, end, mat_fn, tip)
        return path, recs, rings, faces

    def _loft(self, rings, recs, mat, start, end, mat_fn, tip):
        bm, uv = self.bm, self.uv
        N = len(rings[0])
        perim = sum(sum((r[j] - r[(j + 1) % N]).length for j in range(N)) for r in rings) / len(rings)
        vs = [[bm.verts.new(p) for p in r] for r in rings]
        mdef = self.mi(mat)
        faces = []
        for k in range(len(rings) - 1):
            for j in range(N):
                jn = (j + 1) % N
                f = bm.faces.new((vs[k][j], vs[k][jn], vs[k + 1][jn], vs[k + 1][j]))
                f.material_index = self.mi(mat_fn(k, j, recs[k])) if mat_fn else mdef
                f.smooth = True
                for loop, (jj, kk) in zip(f.loops, ((j, k), (j + 1, k), (j + 1, k + 1), (j, k + 1))):
                    loop[uv].uv = (jj / N * perim, recs[kk]["s"])
                faces.append(f)
        for which, mode in (("start", start), ("end", end)):
            if mode is None:
                continue
            k = 0 if which == "start" else len(rings) - 1
            rec = recs[k]
            sign = -1 if which == "start" else 1
            c = rec["pos"] + rec["t"] * (sign * tip * rec["r"] if mode == "tip" else 0.0)
            pole = bm.verts.new(c)
            for j in range(N):
                jn = (j + 1) % N
                f = bm.faces.new((vs[k][j], vs[k][jn], pole))
                f.material_index = mdef
                f.smooth = True
                for loop, uvc in zip(f.loops, ((j / N * perim, rec["s"]), ((j + 1) / N * perim, rec["s"]),
                                               ((j + 0.5) / N * perim, rec["s"] + sign * 0.01))):
                    loop[uv].uv = uvc
                faces.append(f)
        self.islands.append(faces)
        return faces

    def sphere(self, center, radius, mat, segs=24, rings_=12):
        COUNTS["uv_spheres_eyes"] += 1
        m = Matrix.Translation(center) @ Matrix.Diagonal((radius, radius, radius, 1.0))
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=segs, v_segments=rings_, radius=1.0, matrix=m, calc_uvs=True)
        faces = list({f for v in res["verts"] for f in v.link_faces})
        for f in faces:
            f.material_index = self.mi(mat)
            f.smooth = True
        self.islands.append(faces)
        return faces

    def ellipsoid_axes(self, center, ax, ay, az, mat, segs=12, rings_=8):
        m = Matrix.Identity(4)
        for col, axis in enumerate((ax, ay, az)):
            for row in range(3):
                m[row][col] = axis[row]
        m.translation = center
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=segs, v_segments=rings_, radius=1.0, matrix=m, calc_uvs=True)
        faces = list({f for v in res["verts"] for f in v.link_faces})
        for f in faces:
            f.material_index = self.mi(mat)
            f.smooth = True
        self.islands.append(faces)
        return faces

    def pack_uvs(self, margin=0.02):
        """Simple shelf packer: each loft island keeps metric proportions."""
        uv, items = self.uv, []
        for faces in self.islands:
            us = [lp[uv].uv.copy() for f in faces for lp in f.loops]
            mnu, mnv = min(p.x for p in us), min(p.y for p in us)
            items.append([faces, mnu, mnv, max(p.x for p in us) - mnu, max(p.y for p in us) - mnv])
        if not items:
            return
        total = sum(it[3] * it[4] for it in items)
        width = max(max(it[3] for it in items), math.sqrt(total) * 1.25)
        x = y = shelf = 0.0
        place = []
        for it in sorted(items, key=lambda it: -it[4]):
            if x + it[3] > width:
                x, y, shelf = 0.0, y + shelf + margin, 0.0
            place.append((it, x, y))
            x += it[3] + margin
            shelf = max(shelf, it[4])
        size = max(width, y + shelf)
        for (faces, mnu, mnv, _, _), px, py in place:
            for f in faces:
                for lp in f.loops:
                    u, v = lp[uv].uv
                    lp[uv].uv = ((u - mnu + px) / size, (v - mnv + py) / size)

    def mirror_x(self):
        geom = self.bm.verts[:] + self.bm.edges[:] + self.bm.faces[:]
        bmesh.ops.mirror(self.bm, geom=geom, matrix=Matrix.Identity(4), merge_dist=0.0, axis="X")

    def to_object(self, collection, parent, subsurf=0):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        for key in self.mats:
            me.materials.append(mp.get_material(key))
        ob = bpy.data.objects.new(self.name, me)
        collection.objects.link(ob)
        ob.parent = parent
        if subsurf:
            mod = ob.modifiers.new("Subdivision", "SUBSURF")
            mod.levels = mod.render_levels = subsurf
        return ob


def displace(part, center, normal, radius, depth, rim, upper_boost=0.0):
    """Carve a smooth dish (eye socket / nostril) with a raised rim into a part's mesh.
    upper_boost thickens the rim on the upper side (heavy upper lid / brow overhang)."""
    COUNTS["displacements"] += 1
    up = (Z - normal * normal.dot(Z)).normalized()
    for v in part.bm.verts:
        d = v.co - center
        h = d.dot(normal)
        if d.length > radius * 1.6 or h < -0.04:
            continue
        planar = d - normal * h
        r = planar.length
        off = 0.0
        if r < radius:
            off -= depth * (1 - (r / radius) ** 2) ** 2
        lid = 1.0 + upper_boost * max(0.0, planar.normalized().dot(up)) if r > 1e-6 else 1.0
        off += rim * lid * math.exp(-((r - radius * 0.95) / (radius * 0.28)) ** 2)
        v.co += normal * off


def surface_point(bvh, origin, direction):
    """Ray from outside (origin - direction*0.4) along direction; returns hit and outward normal."""
    loc, nrm, _, _ = bvh.ray_cast(origin - direction * 0.4, direction, 1.0)
    if loc is None:
        raise RuntimeError(f"surface_point missed at {origin}")
    if nrm.length < 0.5:  # rev 4: guard against zero normals
        raise RuntimeError("surface_point got a zero normal; call bm.normal_update() before FromBMesh")
    if nrm.dot(direction) > 0:
        nrm = -nrm
    return loc, nrm


def belly_fn(N, half_width_deg, s_min=0.0, s_max=1e9):
    hw = rad(half_width_deg)

    def fn(k, j, rec):
        phi = TAU * (j + 0.5) / N
        phi = min(phi, TAU - phi)
        return "belly" if phi < hw and s_min <= rec["s"] <= s_max else "skin"
    return fn


# --------------------------------------------------------------------------- scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
DRAGON = camera_setup.ensure_collection("Dragon", scene)
root = bpy.data.objects.new("DRG_Root", None)
root.empty_display_type = "PLAIN_AXES"
DRAGON.objects.link(root)

# =========================================================================== TRUNK
# spine head -> tail; shapes: (half-width, dorsal height, ventral depth, superellipse n, keel, ridge)
TRUNK_PTS = [(0, -0.80, 1.19), (0, -0.73, 1.115), (0, -0.67, 1.005), (0, -0.61, 0.895), (0, -0.51, 0.795),
             (0, -0.36, 0.72), (0, -0.18, 0.685), (0, 0.05, 0.655), (0, 0.30, 0.67), (0, 0.50, 0.655),
             (0, 0.74, 0.58), (0.04, 1.00, 0.45), (0.13, 1.26, 0.30), (0.22, 1.50, 0.19), (0.30, 1.73, 0.13)]
TRUNK_SHAPES = [(0.062, 0.070, 0.072, 2.0, 0.0, 0.0),     # inside skull (rev 2: thinner upper neck)
                (0.058, 0.062, 0.070, 2.1, 0.0, 0.004),   # upper neck
                (0.066, 0.066, 0.080, 2.2, 0.0, 0.006),
                (0.088, 0.082, 0.105, 2.2, 0.0, 0.007),
                (0.130, 0.110, 0.150, 2.3, 0.005, 0.008),  # neck base
                (0.215, 0.200, 0.260, 2.5, 0.020, 0.010),  # broad, deep chest
                (0.205, 0.205, 0.245, 2.5, 0.015, 0.012),
                (0.165, 0.190, 0.175, 2.4, 0.0, 0.012),    # narrower abdomen / waist
                (0.190, 0.200, 0.175, 2.5, 0.0, 0.012),    # hips
                (0.140, 0.150, 0.130, 2.3, 0.0, 0.010),    # tail root
                (0.095, 0.100, 0.085, 2.2, 0.0, 0.008),
                (0.066, 0.068, 0.058, 2.1, 0.0, 0.006),
                (0.043, 0.044, 0.038, 2.0, 0.0, 0.004),
                (0.024, 0.025, 0.021, 2.0, 0.0, 0.002),
                (0.003, 0.003, 0.003, 2.0, 0.0, 0.0)]
TRUNK_N = 32
body = Part("DRG_Body")
trunk_path, trunk_recs, trunk_rings, _ = body.sweep(
    TRUNK_PTS, TRUNK_SHAPES, N=TRUNK_N, step=0.025, frame="h", start="cap", end="tip",
    bumps=[(1.5 * math.pi, 0.35, 4), (0.5 * math.pi, 0.22, 5)],
    mat_fn=belly_fn(TRUNK_N, 52, s_min=0.07), tip=1.5)
body.bm.normal_update()  # rev 4: FromBMesh reports stored face normals, zero until updated
body_bvh = BVHTree.FromBMesh(body.bm)

# =========================================================================== HEAD
HEAD_PTS = [(0, -1.165, 1.168), (0, -1.135, 1.174), (0, -1.05, 1.180), (0, -0.97, 1.190), (0, -0.905, 1.212),
            (0, -0.845, 1.222), (0, -0.785, 1.218), (0, -0.745, 1.206), (0, -0.722, 1.198)]
# (half-width, top, bottom, superellipse n, brow, cheek, sagittal crest)
# rev 3: pronounced stop + overhanging brow, wide cheek/jaw mass (wedge skull), crest, nose pad
HEAD_SHAPES = [(0.012, 0.012, 0.012, 2.0, 0.0, 0.0, 0.0),       # snout tip
               (0.044, 0.040, 0.030, 2.6, 0.0, 0.0, 0.0),       # nose pad
               (0.056, 0.046, 0.036, 3.2, 0.0, 0.0, 0.0),       # muzzle (boxy, flat top)
               (0.066, 0.056, 0.040, 3.0, 0.006, 0.004, 0.0),   # stop
               (0.086, 0.082, 0.050, 2.8, 0.042, 0.010, 0.006), # brow / eye station
               (0.108, 0.096, 0.064, 2.6, 0.014, 0.034, 0.010), # cranium + cheekbones
               (0.104, 0.090, 0.070, 2.4, 0.004, 0.030, 0.008),
               (0.070, 0.066, 0.058, 2.2, 0.0, 0.006, 0.0),
               (0.008, 0.008, 0.008, 2.0, 0.0, 0.0, 0.0)]       # occiput
BROW, CHEEK = rad(55), rad(-15)
head = Part("DRG_Head")
head_path, head_recs, _, _ = head.sweep(
    HEAD_PTS, HEAD_SHAPES, N=40, step=0.008, frame="h", start="tip", end="tip",
    bumps=[(BROW, 0.28, 4), (math.pi - BROW, 0.28, 4), (CHEEK, 0.40, 5), (math.pi - CHEEK, 0.40, 5),
           (0.5 * math.pi, 0.15, 6)])
JAW_PTS = [(0, -1.118, 1.130), (0, -1.085, 1.127), (0, -0.99, 1.128), (0, -0.89, 1.138), (0, -0.815, 1.152), (0, -0.79, 1.158)]
JAW_SHAPES = [(0.010, 0.010, 0.010, 2.0), (0.030, 0.020, 0.018, 2.6), (0.044, 0.024, 0.026, 2.8),
              (0.062, 0.027, 0.036, 2.6), (0.070, 0.032, 0.048, 2.4), (0.010, 0.010, 0.010, 2.0)]  # rev 3: jaw angles down to hinge
head.sweep(JAW_PTS, JAW_SHAPES, N=24, step=0.01, frame="h", start="tip", end="tip", mat_fn=belly_fn(24, 55))
bmesh.ops.recalc_face_normals(head.bm, faces=head.bm.faces[:])
head.bm.normal_update()  # rev 4
head_bvh = BVHTree.FromBMesh(head.bm)


def head_surface(y_target, theta_deg):
    rec = min(head_recs, key=lambda r: abs(r["pos"].y - y_target))
    th = rad(theta_deg)
    direction = -(rec["side"] * math.cos(th) + rec["up"] * math.sin(th))
    return surface_point(head_bvh, rec["pos"] - direction * 0.0, direction)


def mirrored(p):
    return V((-p.x, p.y, p.z))


eyes = Part("DRG_Eyes")
eye_ps, eye_n = head_surface(-0.90, 16)  # rev 3: lower, tucked under the brow
nos_ps, nos_n = head_surface(-1.115, 64)
# rev 2/3: socket rim overlaps the eyeball edge (eyelids); heavy upper lid
for ps, n in ((eye_ps, eye_n), (mirrored(eye_ps), mirrored(eye_n))):
    displace(head, ps, n, radius=0.024, depth=0.009, rim=0.005, upper_boost=2.5)
for ps, n in ((nos_ps, nos_n), (mirrored(nos_ps), mirrored(nos_n))):
    displace(head, ps, n, radius=0.011, depth=0.006, rim=0.0015)
EYE_R = 0.020
eye_c = eye_ps - eye_n * 0.013
eyes.sphere(eye_c, EYE_R, "eye")
e_up = (Z - eye_n * eye_n.dot(Z)).normalized()
eyes.ellipsoid_axes(eye_c + eye_n * (EYE_R - 0.0015), eye_n * 0.003, e_up.cross(eye_n) * 0.0055, e_up * 0.015, "pupil")

# =========================================================================== HORNS (curve sweeps)
horns = Part("DRG_Horns")
HORN_PTS = [(0.042, -0.80, 1.265), (0.058, -0.755, 1.315), (0.083, -0.67, 1.352), (0.103, -0.575, 1.36),
            (0.115, -0.495, 1.335), (0.119, -0.45, 1.295)]
HORN_R = [0.030, 0.026, 0.019, 0.012, 0.006, 0.001]


def horn_ridges(s, L):
    return 1.0 + 0.07 * max(0.0, math.sin(TAU * s / 0.028)) ** 2 * max(0.0, 1 - s / (0.75 * L))


horns.sweep(HORN_PTS, [(r * 0.85, r, r, 2.0) for r in HORN_R], mat="horn", N=14, step=0.006,
            start="cap", end="tip", scale_fn=horn_ridges, tip=1.0)

# =========================================================================== DORSAL SPIKES (curve sweeps)
spikes = Part("DRG_DorsalSpikes")
SPIKE_SIZE = [(0.0, 0.026), (0.12, 0.04), (0.25, 0.068), (0.42, 0.064), (0.6, 0.048), (0.92, 0.014)]


def piecewise(x, table):
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


s_spike = 0.10
n_spikes = 0
while s_spike < trunk_path.length * 0.92:
    k = min(range(len(trunk_recs)), key=lambda i: abs(trunk_recs[i]["s"] - s_spike))
    rec = trunk_recs[k]
    top = trunk_rings[k][TRUNK_N // 2]
    up, t = rec["up"], rec["t"]
    h = piecewise(s_spike / trunk_path.length, SPIKE_SIZE)
    base = top - up * 0.008
    pts = [base, base + up * h * 0.45 + t * h * 0.12, base + up * h * 0.92 + t * h * 0.55]
    spikes.sweep(pts, [(0.15 * h, 0.42 * h, 0.42 * h, 2.0), (0.10 * h, 0.24 * h, 0.30 * h, 2.0), (0.003, 0.004, 0.004, 2.0)],
                 mat="horn", N=8, step=h / 5, frame="hint", hint=rec["side"], start="cap", end="tip", tip=1.0)
    n_spikes += 1
    s_spike += 0.07 if s_spike < trunk_path.length * 0.5 else 0.065

# =========================================================================== LEGS, PAWS, CLAWS (left; mirrored later)
legs = Part("DRG_Legs")
claws = Part("DRG_Claws")


def toe_and_claw(base, d, length, r0, claw_len):
    d = d.normalized()
    tip = base + d * length + V((0, 0, -0.006))
    legs.sweep([base - d * 0.012, base + d * length * 0.5 + V((0, 0, 0.004)), tip],
               [(r0, r0 * 0.9, r0 * 0.9, 2.2), (r0 * 1.08, r0, r0, 2.2), (r0 * 0.82, r0 * 0.75, r0 * 0.75, 2.2)],
               N=10, step=0.012, frame="h", start="cap", end="tip", tip=0.8)
    claw_curve(tip + d * 0.002 + V((0, 0, 0.004)), d, claw_len, r0 * 0.72)


def claw_curve(base, d, length, r0):
    d = d.normalized()
    down = V((0, 0, -1))
    pts = [base - d * 0.004, base + d * length * 0.45 + down * length * 0.06,
           base + d * length * 0.8 + down * length * 0.3, base + d * length * 0.95 + down * length * 0.62]
    claws.sweep(pts, [(r0 * 0.8, r0, r0, 2.0), (r0 * 0.62, r0 * 0.8, r0 * 0.8, 2.0),
                      (r0 * 0.35, r0 * 0.45, r0 * 0.45, 2.0), (0.0008, 0.0008, 0.0008, 2.0)],
                mat="claw", N=8, step=max(length / 7, 0.005), frame="hint", hint=X if abs(d.x) < 0.7 else V((0, 1, 0)),
                start="cap", end="tip", tip=0.5)


def paw(center, fwd, toe_angles, toe_len, toe_r, claw_len, back_toe):
    fwd = fwd.normalized()
    c = V(center)
    legs.sweep([c - fwd * 0.05 + V((0, 0, 0.006)), c + V((0, 0, 0.002)), c + fwd * 0.042, c + fwd * 0.056],
               [(0.036, 0.026, 0.020, 2.6), (0.055, 0.028, 0.020, 2.8), (0.057, 0.022, 0.018, 2.8), (0.033, 0.015, 0.012, 2.4)],
               N=16, step=0.012, frame="h", start="tip", end="tip", tip=0.5)
    for a in toe_angles:
        d = Matrix.Rotation(rad(a), 3, "Z") @ fwd
        toe_and_claw(c + d * 0.022 + V((0, 0, -0.002)), d, toe_len, toe_r, claw_len)
    if back_toe:
        d = Matrix.Rotation(rad(12), 3, "Z") @ -fwd
        toe_and_claw(c + d * 0.03, d, toe_len * 0.5, toe_r * 0.8, claw_len * 0.7)


# front leg: root inside chest -> shoulder -> biceps -> elbow (knob back) -> forearm -> wrist -> into paw
# rev 2: joint-flanking control points keep segments straight and joints defined (no "noodle" bends)
FRONT_PTS = [(0.10, -0.30, 0.68), (0.19, -0.31, 0.56), (0.225, -0.255, 0.44), (0.24, -0.215, 0.35),
             (0.245, -0.205, 0.32), (0.248, -0.225, 0.29), (0.25, -0.28, 0.19), (0.25, -0.325, 0.10),
             (0.25, -0.355, 0.05)]
FRONT_SHAPES = [(0.100, 0.120, 0.120, 2.2), (0.088, 0.095, 0.095, 2.3), (0.070, 0.072, 0.078, 2.3),
                (0.056, 0.062, 0.054, 2.2), (0.054, 0.070, 0.050, 2.2), (0.050, 0.058, 0.050, 2.2),
                (0.047, 0.048, 0.050, 2.3), (0.036, 0.036, 0.038, 2.2), (0.038, 0.032, 0.038, 2.2)]
legs.sweep(FRONT_PTS, FRONT_SHAPES, N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
paw((0.25, -0.37, 0.03), V((math.sin(rad(8)), -math.cos(rad(8)), 0)), (-26, 0, 26), 0.062, 0.020, 0.047, False)

# hind leg (digitigrade): root inside hips -> hip -> thigh -> knee -> shin -> hock (heel) -> metatarsus -> foot
HIND_PTS = [(0.10, 0.38, 0.74), (0.18, 0.40, 0.60), (0.23, 0.33, 0.47), (0.245, 0.265, 0.39), (0.25, 0.245, 0.36),
            (0.25, 0.26, 0.33), (0.25, 0.36, 0.25), (0.25, 0.45, 0.18), (0.25, 0.47, 0.16), (0.25, 0.462, 0.135),
            (0.25, 0.43, 0.10), (0.25, 0.385, 0.05)]
HIND_SHAPES = [(0.125, 0.155, 0.155, 2.2), (0.115, 0.125, 0.145, 2.3), (0.100, 0.095, 0.125, 2.3),
               (0.070, 0.065, 0.075, 2.2), (0.064, 0.060, 0.068, 2.2), (0.058, 0.056, 0.056, 2.2),
               (0.054, 0.056, 0.048, 2.3), (0.042, 0.046, 0.036, 2.2), (0.040, 0.050, 0.034, 2.2),
               (0.037, 0.040, 0.034, 2.2), (0.034, 0.034, 0.034, 2.2), (0.036, 0.032, 0.036, 2.2)]
legs.sweep(HIND_PTS, HIND_SHAPES, N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
paw((0.25, 0.36, 0.03), V((math.sin(rad(6)), -math.cos(rad(6)), 0)), (-24, 0, 24), 0.072, 0.022, 0.052, True)

# =========================================================================== WINGS (left; mirrored later)
wingf = Part("DRG_WingFrames")
wingm = Part("DRG_WingMembranes")
inward = V((-0.5, 0, -0.87)).normalized()
B = surface_point(body_bvh, V((0.15, -0.19, 0.90)), inward)[0] + inward * 0.004
C = surface_point(body_bvh, V((0.18, 0.06, 0.78)), inward)[0] + inward * 0.004
A = surface_point(body_bvh, V((0.17, 0.32, 0.80)), inward)[0] + inward * 0.004
WE, WW = V((0.48, 0.02, 1.10)), V((0.86, -0.26, 1.40))
TIPS = [V((1.32, -0.08, 1.52)), V((1.30, 0.30, 1.10)), V((1.04, 0.56, 0.86)), V((0.66, 0.60, 0.80))]
arm_path, _, _, _ = wingf.sweep([V((0.07, -0.21, 0.80)), B, WE, WW],
                                [(0.060, 0.060, 0.060, 2.0), (0.050, 0.050, 0.050, 2.0), (0.040, 0.040, 0.040, 2.0),
                                 (0.028, 0.030, 0.030, 2.0)],
                                N=16, step=0.02, frame="h", start="cap", end="cap")
wingf.sweep([WE + (WE - B).normalized() * -0.03, WE + (WE - B).normalized() * 0.03],
            [(0.040, 0.044, 0.040, 2.0), (0.034, 0.036, 0.034, 2.0)], N=16, step=0.01, start="tip", end="tip", tip=0.7)  # elbow knob
wingf.sweep([WW + V((-0.03, 0.01, -0.02)), WW + V((0.03, -0.01, 0.02))],
            [(0.032, 0.032, 0.032, 2.0), (0.030, 0.030, 0.030, 2.0)], N=16, step=0.01, start="tip", end="tip", tip=0.7)  # wrist knuckle
fingers = []
for i, T in enumerate(TIPS):
    mid = WW.lerp(T, 0.5) + V((0.0, 0.3, -0.5)).normalized() * 0.022
    fp, _, _, _ = wingf.sweep([WW, mid, T], [(0.019, 0.019, 0.019, 2.0), (0.014, 0.015, 0.015, 2.0), (0.004, 0.004, 0.004, 2.0)],
                              N=12, step=0.02, frame="h", start="cap", end="tip", tip=1.0,
                              scale_fn=lambda s, L: 1.0 + 0.18 * math.exp(-((s / L - 0.42) / 0.06) ** 2))
    fingers.append(fp)
claw_curve(WW + V((0.0, -0.03, 0.025)), V((0.15, -0.75, 0.55)), 0.06, 0.012)

s_arm0 = arm_path.arc_at_u(1.0)


def arm_at(u):
    return arm_path.at(s_arm0 + u * (arm_path.length - s_arm0))[0]


def finger_at(i, u):
    return fingers[i].at(u * fingers[i].length)[0]


body_path = Path([B, C, A])


def patch(fn, nu, nv, lu, lv):
    COUNTS["membrane_patches"] += 1
    bm, uv = wingm.bm, wingm.uv
    grid = [[bm.verts.new(fn(i / nu, k / nv)) for k in range(nv + 1)] for i in range(nu + 1)]
    faces = []
    for i in range(nu):
        for k in range(nv):
            f = bm.faces.new((grid[i][k], grid[i + 1][k], grid[i + 1][k + 1], grid[i][k + 1]))
            f.material_index = wingm.mi("membrane")
            f.smooth = True
            for lp, (a, b) in zip(f.loops, ((i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1))):
                lp[uv].uv = (a / nu * lu, b / nv * lv)
            faces.append(f)
    wingm.islands.append(faces)


def sag_dir(p, q):
    n = (p - WW).cross(q - WW).normalized()
    return n if n.z < 0 else -n


# finger panels with scalloped trailing edge + billow
for i in range(3):
    Ti, Tj = TIPS[i], TIPS[i + 1]
    depth = 0.20 * (Ti - Tj).length
    toward = (WW - Ti.lerp(Tj, 0.5)).normalized()
    sag = sag_dir(Ti, Tj) * 0.035

    def fn(u, v, i=i, depth=depth, toward=toward, sag=sag):
        p = finger_at(i, u).lerp(finger_at(i + 1, u), v)
        return p + toward * depth * math.sin(math.pi * v) * u ** 3 + sag * math.sin(math.pi * v) * math.sin(math.pi * u * 0.75)
    patch(fn, 18, 8, fingers[i].length, (Ti - Tj).length)

# inner panel: Coons patch between arm chain, finger 4, trailing edge and the body attachment line
T4 = TIPS[3]
in_toward = (WW - A.lerp(T4, 0.5)).normalized()
in_sag = (T4 - WW).cross(A - WW).normalized()
in_sag = (in_sag if in_sag.x > 0 else -in_sag) * 0.02  # rev 2: billow outward, away from the flank


def trailing(u):
    return A.lerp(T4, u) + in_toward * 0.16 * (T4 - A).length * math.sin(math.pi * u)


def body_line(v):
    return body_path.at(v * body_path.length)[0]


def inner(u, v):
    c0, c1 = arm_at(u), trailing(u)
    d0, d1 = body_line(v), finger_at(3, v)
    bil = (B * (1 - u) * (1 - v) + WW * u * (1 - v) + A * (1 - u) * v + T4 * u * v)
    return (1 - v) * c0 + v * c1 + (1 - u) * d0 + u * d1 - bil + in_sag * math.sin(math.pi * u) * math.sin(math.pi * v)


patch(inner, 20, 14, (WW - B).length, (A - B).length)

# leading-edge membrane (propatagium) between the arm chain and a bowed edge from shoulder to wrist


def front(u, v):
    lead = B.lerp(WW, u) + (WE - B.lerp(WW, 0.5)).normalized() * 0.05 * math.sin(math.pi * u)
    return lead.lerp(arm_at(u), v)


patch(front, 14, 4, (WW - B).length, 0.1)

# =========================================================================== finish parts
for p in (wingm,):
    p.pack_uvs()
    bmesh.ops.remove_doubles(p.bm, verts=p.bm.verts[:], dist=1e-5)
    bmesh.ops.solidify(p.bm, geom=p.bm.faces[:], thickness=0.006)
    for f in p.bm.faces:
        f.smooth = True
for p in (body, head, spikes, legs, claws, eyes, horns, wingf):
    p.pack_uvs()
for p in (legs, claws, eyes, horns, wingf, wingm):
    p.mirror_x()

objects = [body.to_object(DRAGON, root, subsurf=1),
           head.to_object(DRAGON, root, subsurf=1),
           legs.to_object(DRAGON, root, subsurf=1),
           wingf.to_object(DRAGON, root, subsurf=1),
           wingm.to_object(DRAGON, root),
           horns.to_object(DRAGON, root),
           spikes.to_object(DRAGON, root),
           claws.to_object(DRAGON, root),
           eyes.to_object(DRAGON, root)]

camera_setup.build_rig(scene)
build_seconds = time.perf_counter() - T_START
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=False)
log = {
    "experiment": "02_advanced_procedural",
    "script_revision": SCRIPT_REVISION,
    "blender": bpy.app.version_string,
    "build_seconds_excluding_save": round(build_seconds, 3),
    "build_seconds_including_save": round(time.perf_counter() - T_START, 3),
    "construction_counts": dict(COUNTS, dorsal_spikes=n_spikes),
    "objects": [o.name for o in objects],
    "output": os.path.basename(OUT_BLEND),
}
with open(os.path.join(HERE, "build_log.json"), "w", encoding="utf-8") as fh:
    json.dump(log, fh, indent=2)
print("[bench] built", OUT_BLEND, json.dumps(log["construction_counts"]))
