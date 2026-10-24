"""Experiment 1 - Basic procedural modeling (primitive assembly).

The dragon is assembled from:
  * UV spheres (uniform / non-uniformly scaled ellipsoids)
  * cones and truncated cones (cylinders with two radii)
  * Bezier curve primitives with a round bevel and per-point radius (neck, tail, horns)
  * small hand-placed basic meshes (wing membrane fans, thickened with bmesh solidify)
Parts overlap; nothing is merged, lofted, sculpted or booleaned. That is the method under test.

Run:  blender -b --factory-startup --python dragon_basic.py
"""
import json
import math
import os
import sys
import time

T_START = time.perf_counter()

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402
import material_palette as mp  # noqa: E402

SCRIPT_REVISION = 3  # rev 2: tube belly rule, sunk horn bases, shorter jaw; rev 3: fix ventral direction
OUT_BLEND = os.path.join(HERE, "dragon_basic.blend")
V = Vector
SIDES = (1, -1)  # +X = dragon's left, -X = dragon's right
COUNTS = {"uv_sphere": 0, "cone": 0, "bezier_curve": 0, "basic_mesh": 0}


def rad(deg):
    return math.radians(deg)


class Part:
    """Accumulates world-space primitives into one bmesh with its own material slots."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.verify()
        self.mats = []

    def _mi(self, key):
        if key not in self.mats:
            self.mats.append(key)
        return self.mats.index(key)

    def _finish(self, faces, mat, smooth=True, belly_rule=None):
        mi = self._mi(mat)
        bi = self._mi("belly") if belly_rule else None
        for f in faces:
            f.material_index = mi
            f.smooth = smooth
            if belly_rule:
                f.normal_update()
                if belly_rule(f.normal, f.calc_center_median()):
                    f.material_index = bi
        return faces

    def ellipsoid(self, center, radii, rot=(0, 0, 0), mat="skin", segs=32, rings=16, belly_rule=None):
        m = Matrix.Translation(center) @ Euler(rot).to_matrix().to_4x4() @ Matrix.Diagonal((*radii, 1.0))
        return self._sphere(m, mat, segs, rings, belly_rule)

    def ellipsoid_axes(self, center, x_axis, y_axis, z_axis, mat="skin", segs=24, rings=12):
        """Ellipsoid from three already-scaled, right-handed axis vectors."""
        m = Matrix.Identity(4)
        for col, axis in enumerate((x_axis, y_axis, z_axis)):
            for row in range(3):
                m[row][col] = axis[row]
        m.translation = center
        return self._sphere(m, mat, segs, rings, None)

    def ellipsoid_along(self, p0, p1, r_lat, r_perp, extend=0.0, mat="skin", segs=24, rings=12):
        """Ellipsoid whose long axis runs from p0 to p1 (muscle masses)."""
        p0, p1 = V(p0), V(p1)
        d = p1 - p0
        rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        m = Matrix.Translation((p0 + p1) / 2) @ rot @ Matrix.Diagonal((r_lat, r_perp, d.length / 2 + extend, 1.0))
        return self._sphere(m, mat, segs, rings, None)

    def _sphere(self, m, mat, segs, rings, belly_rule):
        COUNTS["uv_sphere"] += 1
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=segs, v_segments=rings, radius=1.0, matrix=m, calc_uvs=True)
        faces = {f for v in res["verts"] for f in v.link_faces}
        return self._finish(faces, mat, belly_rule=belly_rule)

    def sphere(self, center, r, mat="skin", segs=20, rings=10):
        return self.ellipsoid(center, (r, r, r), mat=mat, segs=segs, rings=rings)

    def cone(self, p0, p1, r0, r1, mat="skin", segs=20):
        """Truncated cone (cylinder when r0 == r1) from p0 (radius r0) to p1 (radius r1)."""
        COUNTS["cone"] += 1
        p0, p1 = V(p0), V(p1)
        d = p1 - p0
        m = Matrix.Translation((p0 + p1) / 2) @ d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs,
                                    radius1=r0, radius2=max(r1, 0.0008), depth=d.length, matrix=m, calc_uvs=True)
        faces = {f for v in res["verts"] for f in v.link_faces}
        return self._finish(faces, mat)

    def add_mesh(self, me, mat, smooth=True, belly_rule=None):
        n0 = len(self.bm.faces)
        self.bm.from_mesh(me)
        self.bm.faces.ensure_lookup_table()
        faces = [self.bm.faces[i] for i in range(n0, len(self.bm.faces))]
        bpy.data.meshes.remove(me)
        return self._finish(faces, mat, smooth=smooth, belly_rule=belly_rule)

    def to_object(self, collection, parent):
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        for key in self.mats:
            me.materials.append(mp.get_material(key))
        ob = bpy.data.objects.new(self.name, me)
        collection.objects.link(ob)
        ob.parent = parent
        return ob


def curve_tube(points, radii, bevel_res=5, res_u=12):
    """Bezier curve primitive with round bevel + per-point radius, converted to a mesh."""
    COUNTS["bezier_curve"] += 1
    cu = bpy.data.curves.new("tmp_curve", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_mode = "ROUND"
    cu.bevel_depth = 1.0
    cu.bevel_resolution = bevel_res
    cu.resolution_u = res_u
    cu.use_fill_caps = True
    cu.twist_mode = "MINIMUM"
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(points) - 1)
    for bp, p, r in zip(sp.bezier_points, points, radii):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
        bp.radius = r
    ob = bpy.data.objects.new("tmp_curve", cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.curves.remove(cu)
    return me


def catmull_rom(points, n_per=12):
    P = [V(p) for p in points]
    P = [P[0]] + P + [P[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(n_per):
            t = k / n_per
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2])
    return out


def piecewise(x, table):
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


# --------------------------------------------------------------------------- scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
DRAGON = camera_setup.ensure_collection("Dragon", scene)
root = bpy.data.objects.new("DRG_Root", None)
root.empty_display_type = "PLAIN_AXES"
DRAGON.objects.link(root)

# Shape data (metres; dragon faces -Y, stands on Z=0)
NECK = [(0, -0.40, 0.76), (0, -0.57, 0.88), (0, -0.63, 1.02), (0, -0.70, 1.13), (0, -0.78, 1.19)]
NECK_R = [0.16, 0.125, 0.10, 0.088, 0.08]
TAIL = [(0, 0.48, 0.67), (0, 0.78, 0.58), (0.06, 1.08, 0.42), (0.17, 1.34, 0.27), (0.26, 1.56, 0.17), (0.30, 1.72, 0.13)]
TAIL_R = [0.15, 0.11, 0.075, 0.048, 0.024, 0.003]
SPINE_MID = [(0, -0.15, 0.70), (0, 0.10, 0.66), (0, 0.38, 0.68)]


def belly_torso(n, c):
    return n.z < -0.45


def tube_belly(points_head_to_tail, half_angle_deg):
    """Rev 2/3: belly faces chosen by angle around the tube's own centerline, so the
    boundary follows the curve's face columns instead of stair-stepping across them.
    Points must run head -> tail; ventral = t x side, side = horizontal lateral axis."""
    line = catmull_rom(points_head_to_tail, n_per=16)
    cos_thr = math.cos(rad(half_angle_deg))

    def rule(n, c):
        k = min(range(len(line)), key=lambda i: (line[i] - c).length_squared)
        a, b = line[max(k - 1, 0)], line[min(k + 1, len(line) - 1)]
        t = (b - a).normalized()
        side = t.cross(V((0, 0, 1))).normalized()
        ventral = t.cross(side).normalized()
        r = c - line[k]
        r = (r - t * r.dot(t)).normalized()
        return r.dot(ventral) > cos_thr
    return rule


belly_neck = tube_belly(list(reversed(NECK)), 55)  # rev 3: NECK is stored chest -> head
belly_tail = tube_belly(TAIL, 50)


# --------------------------------------------------------------------------- body
body = Part("DRG_Body")
body.ellipsoid((0, -0.30, 0.66), (0.23, 0.31, 0.25), rot=(rad(-10), 0, 0), segs=48, rings=24, belly_rule=belly_torso)  # chest
body.ellipsoid((0, 0.05, 0.615), (0.18, 0.30, 0.20), segs=48, rings=24, belly_rule=belly_torso)                        # abdomen
body.ellipsoid((0, 0.38, 0.65), (0.20, 0.24, 0.215), rot=(rad(6), 0, 0), segs=48, rings=24, belly_rule=belly_torso)     # hips
for s in SIDES:
    body.ellipsoid((s * 0.165, -0.30, 0.62), (0.10, 0.14, 0.15), segs=32, rings=16)                                    # shoulder mass
body.add_mesh(curve_tube(NECK, NECK_R), "skin", belly_rule=belly_neck)
body.add_mesh(curve_tube(TAIL, TAIL_R, res_u=16), "skin", belly_rule=belly_tail)

# --------------------------------------------------------------------------- dorsal spikes (ray-cast onto body)
spikes = Part("DRG_DorsalSpikes")
bvh = BVHTree.FromBMesh(body.bm)
spine = catmull_rom(list(reversed(NECK)) + SPINE_MID + TAIL, n_per=12)
arc = [0.0]
for a, b in zip(spine, spine[1:]):
    arc.append(arc[-1] + (b - a).length)
total = arc[-1]
SIZE = [(0.0, 0.03), (0.15, 0.05), (0.28, 0.07), (0.45, 0.065), (0.6, 0.05), (1.0, 0.018)]
s_pos = 0.10
while s_pos < total - 0.18:
    i = next(k for k in range(1, len(arc)) if arc[k] >= s_pos)
    f = (s_pos - arc[i - 1]) / max(arc[i] - arc[i - 1], 1e-9)
    p = spine[i - 1].lerp(spine[i], f)
    t = (spine[i] - spine[i - 1]).normalized()
    dorsal = V((0, -t.z, t.y)).normalized()
    hit, n, _, _ = bvh.ray_cast(p + dorsal * 0.6, -dorsal, 1.0)
    if hit:
        n = n if n.dot(dorsal) > 0 else -n
        h = piecewise(s_pos / total, SIZE)
        base = hit - n * 0.008
        direction = (n + t * 0.9).normalized()
        spikes.cone(base, base + direction * h, 0.42 * h, 0.0, mat="horn", segs=10)
    s_pos += 0.075

# --------------------------------------------------------------------------- head
head = Part("DRG_Head")
head.ellipsoid((0, -0.82, 1.23), (0.10, 0.12, 0.095), segs=40, rings=20)                                  # cranium
head.ellipsoid((0, -1.00, 1.20), (0.068, 0.15, 0.058), rot=(rad(8), 0, 0), segs=40, rings=20)             # muzzle
head.ellipsoid((0, -1.10, 1.215), (0.048, 0.05, 0.038), segs=24, rings=12)                                # nose pad
head.ellipsoid((0, -0.955, 1.145), (0.055, 0.125, 0.030), rot=(rad(10), 0, 0), segs=32, rings=16,
               belly_rule=lambda n, c: n.z < -0.5)                                                        # lower jaw (rev 2: shorter)
for s in SIDES:
    head.ellipsoid((s * 0.065, -0.83, 1.16), (0.04, 0.06, 0.05), segs=24, rings=12)                       # jaw hinge
    head.ellipsoid((s * 0.07, -0.88, 1.20), (0.045, 0.075, 0.05), segs=24, rings=12)                      # cheek
    head.ellipsoid((s * 0.062, -0.925, 1.285), (0.035, 0.065, 0.022), rot=(rad(-10), 0, rad(15 * s)),
                   segs=24, rings=12)                                                                     # brow ridge

# --------------------------------------------------------------------------- eyes
eyes = Part("DRG_Eyes")
for s in SIDES:
    c = V((s * 0.072, -0.935, 1.252))
    eyes.sphere(c, 0.027, mat="eye", segs=24, rings=12)
    out = V((s * 0.85, -0.50, 0.15)).normalized()
    up = (V((0, 0, 1)) - out * out.z).normalized()
    eyes.ellipsoid_axes(c + out * 0.025, out * 0.004, up.cross(out) * 0.0065, up * 0.018, mat="pupil", segs=12, rings=8)

# --------------------------------------------------------------------------- horns
horns = Part("DRG_Horns")
for s in SIDES:
    # rev 2: first point sunk inside the cranium so the flat start cap is hidden
    pts = [(s * 0.04, -0.81, 1.25), (s * 0.055, -0.79, 1.30), (s * 0.075, -0.70, 1.355), (s * 0.095, -0.60, 1.375),
           (s * 0.11, -0.51, 1.35), (s * 0.115, -0.45, 1.30)]
    horns.add_mesh(curve_tube(pts, [0.032, 0.030, 0.024, 0.016, 0.009, 0.002], bevel_res=3), "horn")

# --------------------------------------------------------------------------- legs + claws
legs = Part("DRG_Legs")
claws = Part("DRG_Claws")


def foot(part_leg, part_claw, center, s, forward_angles, back_toe):
    c = V(center)
    part_leg.ellipsoid(c, (0.058, 0.08, 0.032), segs=24, rings=12)
    dirs = [V((s * math.sin(rad(a)), -math.cos(rad(a)), 0)) for a in forward_angles]
    if back_toe:
        dirs.append(V((0, 1, 0)))
    for d in dirs:
        reach = 0.06 if d.y > 0 else 0.095
        tip = c + d * reach + V((0, 0, -0.004))
        part_leg.cone(c + d * 0.03, tip, 0.021, 0.015, segs=12)
        part_leg.sphere(tip, 0.016, segs=12, rings=6)
        cd = (d + V((0, 0, -0.55))).normalized()
        part_claw.cone(tip + d * 0.004, tip + d * 0.004 + cd * 0.05, 0.014, 0.0, mat="claw", segs=10)


for s in SIDES:
    # front leg: shoulder -> elbow (back) -> wrist (forward)
    S, E, W = V((s * 0.21, -0.30, 0.56)), V((s * 0.25, -0.21, 0.33)), V((s * 0.26, -0.33, 0.085))
    legs.ellipsoid_along(S, E, 0.075, 0.085, extend=0.03)
    legs.cone(S, E, 0.075, 0.052)
    legs.sphere(E, 0.055)
    legs.cone(E, W, 0.05, 0.033)
    legs.sphere(W, 0.036)
    foot(legs, claws, (s * 0.26, -0.37, 0.035), s, (-28, 0, 28), back_toe=False)
    # hind leg: hip -> knee (forward) -> hock (back) -> foot (forward), digitigrade
    H, K, A, F = V((s * 0.20, 0.40, 0.58)), V((s * 0.26, 0.25, 0.37)), V((s * 0.26, 0.47, 0.17)), V((s * 0.26, 0.38, 0.05))
    legs.ellipsoid_along(H, K, 0.095, 0.12, extend=0.06)
    legs.cone(H, K, 0.095, 0.06)
    legs.sphere(K, 0.062)
    legs.cone(K, A, 0.058, 0.04)
    legs.sphere(A, 0.042)
    legs.cone(A, F, 0.04, 0.034)
    foot(legs, claws, (s * 0.26, 0.35, 0.035), s, (-25, 0, 25), back_toe=True)

# --------------------------------------------------------------------------- wings
wing_objs = []
for s, label in ((1, "L"), (-1, "R")):
    wing = Part(f"DRG_Wing_{label}")
    B, WE, WW = V((s * 0.12, -0.20, 0.86)), V((s * 0.48, 0.02, 1.10)), V((s * 0.86, -0.26, 1.40))
    tips = [V((s * 1.32, -0.08, 1.52)), V((s * 1.30, 0.30, 1.10)), V((s * 1.04, 0.56, 0.86)), V((s * 0.66, 0.60, 0.80))]
    A, C = V((s * 0.15, 0.30, 0.76)), V((s * 0.15, 0.05, 0.72))
    # bones
    wing.ellipsoid_along(B, WE, 0.055, 0.06, extend=0.02)
    wing.cone(B, WE, 0.05, 0.032)
    wing.sphere(WE, 0.034)
    wing.cone(WE, WW, 0.032, 0.024)
    wing.sphere(WW, 0.03)
    for t in tips:
        wing.cone(WW, t, 0.02, 0.006, segs=12)
    td = V((s * 0.25, -0.75, 0.6)).normalized()
    claws.cone(WW + td * 0.025, WW + td * 0.075, 0.013, 0.0, mat="claw", segs=10)
    # membrane: triangle fan from the wrist over an outline with scalloped trailing edge
    def scallop(a, b, k=0.22):
        return a.lerp(b, 0.5).lerp(WW, k)
    outline = [tips[0], scallop(tips[0], tips[1]), tips[1], scallop(tips[1], tips[2]), tips[2],
               scallop(tips[2], tips[3]), tips[3], scallop(tips[3], A, 0.12), A, C, B, WE]
    mb = bmesh.new()
    vw = mb.verts.new(WW)
    vs = [mb.verts.new(p) for p in outline]
    for a, b in zip(vs, vs[1:]):
        mb.faces.new((vw, a, b))
    bmesh.ops.solidify(mb, geom=mb.faces[:], thickness=0.008)
    bmesh.ops.recalc_face_normals(mb, faces=mb.faces[:])
    mme = bpy.data.meshes.new("tmp_membrane")
    mb.to_mesh(mme)
    mb.free()
    COUNTS["basic_mesh"] += 1
    wing.add_mesh(mme, "membrane", smooth=False)
    wing_objs.append(wing)

# --------------------------------------------------------------------------- objects
parts = [body, head, eyes, horns, spikes, legs, claws] + wing_objs
objects = [p.to_object(DRAGON, root) for p in parts]

camera_setup.build_rig(scene)
build_seconds = time.perf_counter() - T_START
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=False)

log = {
    "experiment": "01_basic_procedural",
    "script_revision": SCRIPT_REVISION,
    "blender": bpy.app.version_string,
    "build_seconds_excluding_save": round(build_seconds, 3),
    "build_seconds_including_save": round(time.perf_counter() - T_START, 3),
    "primitive_counts": COUNTS,
    "objects": [o.name for o in objects],
    "output": os.path.basename(OUT_BLEND),
}
with open(os.path.join(HERE, "build_log.json"), "w", encoding="utf-8") as fh:
    json.dump(log, fh, indent=2)
print("[bench] built", OUT_BLEND, json.dumps(COUNTS))
