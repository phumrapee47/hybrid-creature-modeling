"""creature_kit - the reusable hybrid creature pipeline.

A creature script subclasses `Creature`, fills in data (spine, lofts, strokes, features, mouth, eye) and a few
builders, then calls `run(MyCreature())`. The kit does the rest, in this order:

  lofts -> Catmull-Clark 2 -> voxel fuse -> cavity fillet -> sculpt phases (GUI) -> procedural features
  -> mouth profile -> body fields (+ mouth/lip weights) -> detail material -> inserts (eyes/cornea/lids,
  teeth, tongue, creature extras) -> save high-res -> gated retopology / decimate -> UV -> bake -> save game

Run modes
  GUI (sculpt):  blender --factory-startup --window-geometry 0 0 1400 1000 --python my_creature.py
  Dry run:       CREATURE_DRY_RUN=1 blender -b --factory-startup --python my_creature.py
                 (no sculpt, 512 px bakes, output to a temp folder; catches most bugs in about a minute)
Output folder: CREATURE_OUT_DIR, else Creature.out_dir, else the creature script's folder (never build inside an
installed skill: the high-poly .blend is several hundred MB).
The process exits with code 1 if the build logged an error (Blender's own quit always returns 0).
Settings (rig, reference box, collection name, detail views): CREATURE_SETTINGS=<json> or the creature's
`settings` attribute; default is benchmark_settings.json next to this file.
"""
import json
import math
import os
import shutil
import sys
import tempfile
import time
import traceback

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import camera_setup  # noqa: E402
import surface_plan  # noqa: E402
import detail_materials as dm  # noqa: E402
import proc_mesh as pm  # noqa: E402
import sculpt_driver as sd  # noqa: E402

V, X, Y, Z = Vector, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
DRY_RUN = os.environ.get("CREATURE_DRY_RUN") == "1"
SIDE, FRONT, TOP, BELOW, BEHIND = V((-1, 0, 0)), V((0, 1, 0)), V((0, 0, -1)), V((0, 0, 1)), V((0, -1, 0))
T0 = time.perf_counter()


# =========================================================================== small helpers
def rad(d):
    return math.radians(d)


def dirn(*v):
    return V(v).normalized()


def mx(p, s):
    return V((p[0] * s, p[1], p[2]))


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def seg_dist(c, a, b):
    ab = b - a
    t = np.clip(((c - a) @ ab) / (ab @ ab), 0, 1)
    p = a + t[:, None] * ab
    return np.linalg.norm(c - p, axis=1), p, t


def dense(pts, step):
    path = pm.Path(pts)
    n = max(2, int(path.length / step))
    return [path.at(path.length * k / n)[0] for k in range(n + 1)]


def follow_chains(p, pairs, full=0.08, fade=0.16):
    """Carry a point with a re-posed chain (v1.3, from the dragon's follow_limbs). pairs: [(old_pts, new_pts)] of
    equal length. The point moves with the displacement of the nearest old segment, fully within `full` metres of it
    and fading to nothing at `fade`. Use it for anatomy anchors and stroke points when limb chains change."""
    p = V(p)
    for old, new in pairs:
        best = None
        for i in range(len(old) - 1):
            a, b = V(old[i]), V(old[i + 1])
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
            d = (p - (a + ab * t)).length
            if best is None or d < best[0]:
                best = (d, i, t)
        d, i, t = best
        w = max(0.0, min(1.0, (fade - d) / (fade - full)))
        if w > 0:
            p = p + (V(new[i]).lerp(V(new[i + 1]), t) - V(old[i]).lerp(V(old[i + 1]), t)) * w
    return p


def apply_collars(me, collars, smooth_m=0.006):
    """Skin swelling around insert bases (v1.3) so horns, spikes and claws grow out of the skin instead of looking
    stuck into it. collars: [(base, direction, radius, height or None, mirrored)]. Each is a smooth bump over 2.2 x
    the insert radius, centred on the base (its middle is hidden under the insert); height defaults to 0.35 x radius,
    clamped to 1.5-8 mm. Returns the vertices moved.
    - Skin moves along its normal smoothed over ~smooth_m: raw normals follow every scale and crumple the skin.
    - Each vertex is weighted by how much that normal faces the insert direction, so skin beside the insert (a toe's
      top under a claw) does not slide along it into a sleeve.
    - Overlapping collars (neighbouring claws) take the larger swelling instead of adding up into a ridge."""
    co = sd.coords(me)
    n_v = len(co)
    vn = np.empty(n_v * 3)
    me.vertices.foreach_get("normal", vn)
    vn = vn.reshape(-1, 3)
    ed = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ed)
    ed = ed.reshape(-1, 2)
    if len(ed):
        edge = float(np.median(np.linalg.norm(co[ed[:, 0]] - co[ed[:, 1]], axis=1)))
        deg = np.maximum(np.bincount(ed.ravel(), minlength=n_v), 1).astype(float)
        for _ in range(int(np.clip(round((smooth_m / max(edge, 1e-6)) ** 2), 2, 60))):
            acc = np.stack([np.bincount(ed[:, 0], vn[ed[:, 1], k], n_v) + np.bincount(ed[:, 1], vn[ed[:, 0], k], n_v)
                            for k in range(3)], 1)
            vn = 0.5 * vn + 0.5 * acc / deg[:, None]
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-12)[:, None]
    off = np.zeros(n_v)
    for base, normal, radius, height, mirror in collars:
        h0 = min(0.008, max(0.0015, 0.35 * radius)) if height is None else height
        reach = radius * 2.2
        for s in ((1, -1) if mirror else (1,)):
            c, n = np.array(mx(base, s)), np.array(mx(normal, s), float)
            n /= np.linalg.norm(n)
            r_all = np.linalg.norm(co - c, axis=1)
            sel = np.where(r_all < reach)[0]
            o = h0 * (1 - (r_all[sel] / reach) ** 2) ** 2 * np.clip(vn[sel] @ n, 0.0, 1.0)
            off[sel] = np.maximum(off[sel], o)
    co += vn * off[:, None]
    me.vertices.foreach_set("co", co.ravel())
    me.update()
    return int((off > 1e-5).sum())


def collar(me, base, normal, radius, height=None):
    """One skin collar (see apply_collars)."""
    return apply_collars(me, [(base, normal, radius, height, False)])


def surface_hit(tree, target, direction, reach=0.4):
    """Ray from outside (target - direction * reach) along direction; returns (location, outward normal)."""
    direction = V(direction).normalized()
    loc, nrm, _, _ = tree.ray_cast(V(target) - direction * reach, direction, reach * 2.5)
    if loc is None:
        raise RuntimeError(f"surface miss at {tuple(round(v, 3) for v in target)}")
    if nrm.length < 0.5:
        raise RuntimeError("zero normal (bm.normal_update missing?)")
    return loc, (nrm if nrm.dot(direction) < 0 else -nrm)


def lateral(deg_up=0.0, deg_fwd=0.0):
    """Inward ray direction for a feature on the left (+X) side: tilted up and forward from pure lateral."""
    out = V((math.cos(rad(deg_up)) * math.cos(rad(deg_fwd)), -math.cos(rad(deg_up)) * math.sin(rad(deg_fwd)), math.sin(rad(deg_up))))
    return -out


def arc_at_u(path, u):
    for k, (_, uu) in enumerate(path.samples):
        if uu >= u:
            return path.arc[k]
    return path.length


def sections(key, n):
    """Resample a short list of loft sections to one per control point (sweeps interpolate by point index)."""
    f = np.linspace(0, 1, n)
    kf = np.linspace(0, 1, len(key))
    return [tuple(float(np.interp(x, kf, [k[m] for k in key])) for m in range(len(key[0]))) for x in f]


def displace(me, center, normal, radius, depth, rim, upper_boost=0.0):
    """Socket-style depression with a Gaussian rim; upper_boost raises the rim above the centre (lid/brow)."""
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


# =========================================================================== creature spec
class Creature:
    """Subclass and override. Units metres; +Z up; faces -Y; left side +X; ground z = 0."""
    name = "creature"
    prefix = "CRT_"
    settings = None                 # path to a settings json (rig, reference box, detail views)
    out_dir = None                  # default: folder of the creature script
    voxel = 0.0035
    retopo_faces, decimate_tris = 12000, 32000
    gate_max_mm, gate_mean_mm = 12.0, 2.0
    bake = {"normal": 4096, "color": 4096, "roughness": 2048, "ao": 2048}
    palette = None                  # {"skin": {"hex": ...}, ...} overrides the shared palette
    stripes = None                  # {"period": m, "darkness": 0..1, "width": 0..1}
    mirrored_groups = ("front", "hind", "arm", "toe")
    head_y = (-0.78, -0.72)         # head region fades in below head_y[1] ...
    head_z = (1.00, 1.07)           # ... and above head_z
    tail_y = (0.55, 0.80)
    mouth = None                    # dict(head_pts, head_shapes, y_back, teeth={...}, tongue={...}) for an open mouth
    eye = None                      # dict(radius, sink, lid_up=(tilt, cap), lid_lo=(tilt, cap))
    hipoly_subdiv = 1               # Catmull-Clark levels applied after the secondary sculpt (the high-poly stage)
    anatomy_fillet = 14             # cavity-fillet iterations after the anatomy volumes are fused (base fillet: 30)
    surface_plan = None             # v1.3: list of region overrides for surface_plan.DEFAULT_PLAN (what surface goes where)
    insert_collars = False          # v1.3: swell the skin around insert bases recorded in ctx["collars"]
    joint_relief = 0.0              # v1.3: fraction of scale height removed at limb joints (flexible plan regions)
    scales = None                   # geometric scales (Phase B): None = shader-only scales; True or a dict of overrides
                                    # for scale_field.DEFAULTS (sizes for a ~3 m creature; "size_scale" rescales them)
    hipoly_phases = ("tertiary",)   # stroke phases sculpted on the high-poly mesh instead of the base mesh

    def __init__(self):
        self.log = {"creature": self.name, "blender": bpy.app.version_string, "dry_run": DRY_RUN, "voxel_size": self.voxel,
                    "timings": {}, "strokes": [], "filters": [], "errors": []}
        self.toe_chains, self.toe_tips = [], []
        self.info = {}

    # ---- required
    def spine(self):
        """Centre line from snout tip to tail tip (body fields)."""
        raise NotImplementedError

    def build_base(self):
        """Return a bmesh with every lofted part that should be voxel-fused (mirror limbs yourself)."""
        raise NotImplementedError

    # ---- optional
    def field_chains(self):
        """[(group, points)] for the left side; groups in mirrored_groups are mirrored. Toe chains are added."""
        return []

    def strokes(self):
        """[(phase name, [sd.spec(...)]), ...] in order: junctions, secondary, polish, detail, tertiary."""
        return []

    def features(self, tree):
        """[dict(name, ref=(point, outward normal), radius, depth, rim, upper)] carved after sculpting; the one
        named "eye" also places the eyeball. Use surface_hit(tree, axis_point, lateral(...))."""
        return []

    def anatomy(self, tree):
        """Anatomy layer: [dict(name, kind, a=(target, ray_dir), b=(target, ray_dir), width, protrude, depth=0.6,
        n=8, tol=0.12)] for the left side (mirrored). kind: "muscle" (fusiform belly), "tendon", "ridge" (bony
        crest/arch/rib), "knob" (olecranon, patella, malleolus). Anchors are ray-cast onto the base lofts like
        features; the volumes are fused by the voxel remesh, so they become secondary forms of one surface."""
        return []

    def inserts(self, ctx):
        """[(pm.Part, mirror)] for horns, spikes, claws, wings ... ctx: tree, prof, eye_ref, info, rng."""
        return []

    def regions(self):
        """Deviation-gate regions for the game mesh."""
        return {"head": lambda v: v[:, 1] < self.head_y[1], "feet": lambda v: v[:, 2] < 0.06,
                "tail": lambda v: v[:, 1] > self.tail_y[0]}

    # ---- shared helpers for builders
    def mark(self, name):
        self.log["timings"][name] = round(time.perf_counter() - T0, 2)
        print(f"[bench] {name} @ {self.log['timings'][name]} s")


# =========================================================================== anatomy layer
def _profile(kind, t):
    """(width factor, protrusion factor) along a volume, t in 0..1."""
    sn = math.sin(math.pi * t)
    if kind == "muscle":   # fusiform belly tapering into tendons at origin and insertion
        return 0.35 + 0.65 * sn ** 0.8, sn ** 0.9
    if kind == "tendon":   # narrow cord, nearly constant relief
        return 0.6 + 0.4 * sn, min(1.0, 3.0 * sn)
    if kind == "ridge":    # bony crest / arch / rib: long flat top, soft ends
        return 0.6 + 0.4 * sn, 1.0 - abs(2.0 * t - 1.0) ** 3
    if kind == "knob":     # olecranon, patella, malleolus
        return max(0.3, sn ** 0.5), sn ** 0.5
    raise ValueError(f"unknown anatomy kind {kind}")


def anatomy_volumes(cr, bm):
    """Build the creature's anatomy volumes on the base lofts (left side, mirrored). Returns (bmesh or None, record).

    Each volume follows the surface between two ray-cast anchors; its centre line sits (half-depth - protrusion)
    below the surface so exactly `protrude` metres stand proud at the belly and the ends are buried. The voxel
    remesh then unions them with the base. v2: they are fused in a second remesh *after* the base cavity fillet, with
    only a light fillet of their own, so muscle separations survive (v1 fused them first and the 30-iteration fillet
    smoothed most of them away)."""
    bm.normal_update()
    tree = BVHTree.FromBMesh(bm)
    specs = cr.anatomy(tree)
    rec = {"placed": [], "skipped": []}
    if not specs:
        return None, rec
    part = pm.Part("anatomy")
    for v in specs:
        try:
            (pa, na), (pb, nb) = surface_hit(tree, *v["a"]), surface_hit(tree, *v["b"])
        except RuntimeError as exc:
            rec["skipped"].append(f"{v['name']}: {exc}")
            continue
        far = max((pa - V(v["a"][0])).length, (pb - V(v["b"][0])).length)
        if far > v.get("tol", 0.12):  # the ray hit some other part (a leg, the wing arm): do not guess
            rec["skipped"].append(f"{v['name']}: anchor {far * 1000:.0f} mm from its target")
            continue
        axis = pb - pa
        if axis.length < 1e-4:
            rec["skipped"].append(f"{v['name']}: anchors coincide")
            continue
        n, kind = v.get("n", 8), v.get("kind", "muscle")
        pts, shapes, leaves = [], [], None
        dev_tol = max(0.015, 0.2 * axis.length)
        for k in range(n + 1):
            t = k / n
            p, nn = pa.lerp(pb, t), na.lerp(nb, t).normalized()
            loc, nrm, _, _ = tree.ray_cast(p + nn * 0.06, -nn, 0.15)
            if loc is None or nrm.length < 0.5:
                loc, nrm = p, nn
            elif nrm.dot(nn) < 0:
                nrm = -nrm
            if (loc - p).length > dev_tol:  # the projection jumped to another surface (e.g. across an open mouth)
                leaves = t
                break
            wf, pf = _profile(kind, t)
            w = v["width"] * wf
            d = w * v.get("depth", 0.45)  # v1/v2 0.6: steeper sides read as stuck-on ovals
            pts.append(loc + nrm * (v["protrude"] * pf - d))
            shapes.append((w, d, d, 2.0))
        if leaves is not None:
            rec["skipped"].append(f"{v['name']}: path leaves the surface at t={leaves:.2f}")
            continue
        hint = axis.normalized().cross((na + nb).normalized())
        part.sweep(pts, shapes, "skin", N=16, step=max(min(v["width"] * 0.35, axis.length / 10), 0.004), frame="hint",
                   hint=hint.normalized(), start="tip", end="tip", tip=0.6)
        rec["placed"].append({"name": v["name"], "kind": kind, "length_mm": round(axis.length * 1000),
                              "protrude_mm": round(v["protrude"] * 1000, 1)})
    part.mirror_x()
    return part.bm, rec


# =========================================================================== feet and claws
def paw(cr, part, center, fwd, toes, palm_scale=1.0, back_toe=None, dewclaw=None):
    """Foot: palm loft + toes (+ optional hallux/back toe and raised dewclaw), recording chains and claw tips.

    toes: [dict(angle, length, radius, claw, lift=0.0)]. lift raises the toe tip off the ground (e.g. a
    raptor's sickle-claw toe II). back_toe / dewclaw: dict(direction deg, length, radius, claw, offset (x, y, z)).
    """
    fwd, c, k = V(fwd).normalized(), V(center), palm_scale
    palm = [c - fwd * 0.05 * k + V((0, 0, 0.006 * k)), c + V((0, 0, 0.002)), c + fwd * 0.042 * k, c + fwd * 0.056 * k]
    part.sweep(palm, [(0.036 * k, 0.026 * k, 0.020 * k, 2.6), (0.055 * k, 0.028 * k, 0.020 * k, 2.8),
                      (0.057 * k, 0.022 * k, 0.018 * k, 2.8), (0.033 * k, 0.015 * k, 0.012 * k, 2.4)],
               "skin", N=16, step=0.012, start="tip", end="tip", tip=0.5)
    cr.toe_chains.append(palm)
    for t in toes:
        d = Matrix.Rotation(rad(t["angle"]), 3, "Z") @ fwd
        lift = t.get("lift", 0.0)
        base = c + d * 0.022 * k + V((0, 0, -0.002))
        tip = base + d * t["length"] + V((0, 0, lift - 0.006))
        chain = [base - d * 0.012, base + d * t["length"] * 0.5 + V((0, 0, 0.004 + lift * 0.75)), tip]
        r0 = t["radius"]
        part.sweep(chain, [(r0, r0 * 0.9, r0 * 0.9, 2.2), (r0 * 1.08, r0, r0, 2.2), (r0 * 0.82, r0 * 0.75, r0 * 0.75, 2.2)],
                   "skin", N=10, step=0.012, start="cap", end="tip", tip=0.8)
        cr.toe_chains.append(chain)
        cr.toe_tips.append((tip + d * 0.002 + V((0, 0, 0.004)), d, r0 * 0.72, t["claw"]))
    for extra in (back_toe, dewclaw):
        if not extra:
            continue
        d = (Matrix.Rotation(rad(extra["direction"]), 3, "Z") @ fwd + V((0, 0, extra.get("down", 0.0)))).normalized()
        base = c + V(extra.get("offset", (0, 0, 0)))
        tip = base + d * extra["length"]
        chain = [base - d * 0.012, base + d * extra["length"] * 0.5, tip]
        r0 = extra["radius"]
        part.sweep(chain, [(r0, r0 * 0.92, r0 * 0.92, 2.2), (r0, r0 * 0.92, r0 * 0.92, 2.2), (r0 * 0.75, r0 * 0.7, r0 * 0.7, 2.2)],
                   "skin", N=10, step=0.008, start="cap", end="tip", tip=0.8)
        cr.toe_chains.append(chain)
        cr.toe_tips.append((tip + d * 0.002, d, r0 * 0.72, extra["claw"]))


def claw(part, base, d, length, r0, material="claw", collars=None):
    """Hooked tapering claw whose drop is clamped so the tip stays 1.5 mm above the ground. Returns the drop.
    collars: list to record a skin collar at the claw base (v1.3, applied when Creature.insert_collars)."""
    d = V(d).normalized()
    if collars is not None:
        collars.append((V(base), d, r0 * 1.25, None, True))
    drop = min(0.62, max(0.12, (base.z - 0.0015) / length))
    down = V((0, 0, -1))
    pts = [base - d * 0.004, base + d * length * 0.45 + down * length * drop * 0.1,
           base + d * length * 0.8 + down * length * drop * 0.48, base + d * length * 0.95 + down * length * drop]
    part.sweep(pts, [(r0 * 0.8, r0, r0, 2.0), (r0 * 0.62, r0 * 0.8, r0 * 0.8, 2.0),
                     (r0 * 0.35, r0 * 0.45, r0 * 0.45, 2.0), (0.0008, 0.0008, 0.0008, 2.0)],
               material, N=8, step=max(length / 7, 0.005), frame="hint", hint=X if abs(d.x) < 0.7 else Y,
               start="cap", end="tip", tip=0.5)
    return drop


def spikes_along(part, tree, path, sizes, spacing, rng, material="spike", start=0.08, end_frac=0.92, alternate=0.74,
                 jitter=0.08, rake=0.55, sink=0.006, collars=None):
    """Dorsal spikes/scutes placed by ray-casting down the dorsal axis of a loft path.
    sizes: [(fraction of path length, height m)]; alternates major/minor with seeded jitter."""
    s_pos, n = start, 0
    while s_pos < path.length * end_frac:
        p, t, _ = path.at(s_pos)
        side = t.cross(Z).normalized()
        dorsal = side.cross(t).normalized()
        try:
            base, nrm = surface_hit(tree, p + dorsal * 0.2, -dorsal)
        except RuntimeError:
            s_pos += spacing
            continue
        h = float(np.interp(s_pos / path.length, [a for a, _ in sizes], [b for _, b in sizes]))
        h *= (1.0 if n % 2 == 0 else alternate) * (1.0 + rng.uniform(-jitter, jitter))
        rk = rake + rng.uniform(-0.1, 0.1)
        if collars is not None:                  # midline spikes are not mirrored
            collars.append((V(base), V(nrm), 0.42 * h, None, False))
        base = base - nrm * sink
        part.sweep([base, base + nrm * h * 0.45 + t * h * 0.12, base + nrm * h * 0.92 + t * h * rk],
                   [(0.15 * h, 0.42 * h, 0.42 * h, 2.0), (0.10 * h, 0.24 * h, 0.30 * h, 2.0), (0.003, 0.004, 0.004, 2.0)],
                   material, N=8, step=max(h / 5, 0.004), frame="hint", hint=side, tip=1.0)
        n += 1
        s_pos += spacing
    return n


# =========================================================================== mouth
def mouth_profile(tree, head_pts, head_shapes, y_back, stations=26):
    """Open-mouth stations along the head axis: palate height zu and jaw-floor height zl on the midline."""
    head = pm.Path(head_pts)
    out = []
    for y in np.linspace(V(head_pts[1]).y + 0.012, y_back, stations):
        c, u = min(head.samples, key=lambda q: abs(q[0].y - y))
        an = pm.shape_at(head_shapes, u)[2]
        loc, nrm, _, _ = tree.ray_cast(V((0.0, y, c.z)), -Z, 0.3)
        ok = loc is not None and nrm.z < -0.2 and c.z - loc.z < 1.25 * an + 0.01
        if ok:
            loc2, nrm2, _, _ = tree.ray_cast(loc - Z * 0.0015, -Z, 0.10)
            ok = loc2 is not None and nrm2.z > 0.2 and loc.z - loc2.z >= 0.006
        if not ok:
            if out:
                break
            continue
        out.append({"y": float(y), "zu": loc.z, "zl": loc2.z, "zm": 0.5 * (loc.z + loc2.z)})
    if len(out) < 4:
        raise RuntimeError(f"mouth profile found only {len(out)} open stations (jaw closed or rays outside the head?)")
    return out


def prof_at(prof, y, key):
    return float(np.interp(y, [p["y"] for p in prof], [p[key] for p in prof]))


def half_width(tree, y, z):
    loc, _, _, _ = tree.ray_cast(V((0.5, y, z)), -X, 0.5)
    return None if loc is None else loc.x


def build_teeth(tree, prof, name, spacing=0.021, upper=0.021, lower=0.018, fangs_upper=(1, 2), fangs_lower=(1,), fang_scale=1.7,
                gap_frac=0.62, taper=0.35):
    teeth = pm.Part(name)
    y_front, y_back = prof[0]["y"] + 0.004, prof[-1]["y"]
    stats = {"upper": 0, "lower": 0, "skipped": 0, "longest_mm": 0.0}
    for jaw, nominal, offset, fangs in (("upper", upper, 0.0, fangs_upper), ("lower", lower, spacing / 2, fangs_lower)):
        ys = np.arange(y_front + offset, y_back, spacing)
        for k, y in enumerate(ys):
            zm = prof_at(prof, y, "zm")
            zprobe = prof_at(prof, y, "zu" if jaw == "upper" else "zl") + (0.004 if jaw == "upper" else -0.004)
            w = half_width(tree, y, zprobe)
            inner, _, _, _ = tree.ray_cast(V((0.0, y, zm)), X, 0.3)
            if inner is not None and (w is None or inner.x < w):
                w = inner.x  # cheeks close the gape near the corner: never place a root outside the inner wall
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
            L = min(nominal * (1.0 - taper * k / max(len(ys) - 1, 1)) * (fang_scale if k in fangs else 1.0), gap_frac * gap)
            if L < 0.005:
                stats["skipped"] += 1
                continue
            d = (-out * 0.96 + Y * 0.22 + V((0.06, 0, 0))).normalized()
            base = root + out * 0.0035
            rb = min(0.24 * L, 0.0065)
            teeth.sweep([base, base + d * L * 0.55, base + d * L * 0.95 + Y * 0.06 * L],
                        [(rb * 0.72, rb, rb, 2.0), (rb * 0.55, rb * 0.78, rb * 0.78, 2.0), (0.0006, 0.0006, 0.0006, 2.0)],
                        "tooth", N=10, step=max(L / 6, 0.003), frame="hint", hint=X, start="cap", end="tip", tip=1.0)
            stats[jaw] += 1
            stats["longest_mm"] = max(stats["longest_mm"], round(L * 1000, 1))
    return teeth, stats


def build_tongue(tree, prof, name, width=0.018, reach=0.40, fork=0.034, min_gap=0.02):
    deep = [p["y"] for p in prof if p["zu"] - p["zl"] >= min_gap]
    if not deep:
        raise RuntimeError(f"tongue: mouth gap under {min_gap * 1000:.0f} mm everywhere")
    y_back = max(deep)
    y_tip = prof[0]["y"] + reach * (y_back - prof[0]["y"])
    pts = []
    for y in np.linspace(y_back, y_tip, 9):
        loc, nrm, _, _ = tree.ray_cast(V((0.0, y, prof_at(prof, y, "zm"))), -Z, 0.12)
        if loc is not None and nrm.z > 0.2:
            pts.append(loc + Z * 0.0045)
    if len(pts) < 4:
        raise RuntimeError("tongue: jaw floor not found")
    tongue = pm.Part(name)
    w = width
    tongue.sweep(pts, sections([(w, 0.0055, 0.0055, 2.4), (w * 1.05, 0.006, 0.0055, 2.4), (w * 0.95, 0.0055, 0.005, 2.4),
                                (w * 0.67, 0.0045, 0.004, 2.2)], len(pts)), "tongue", N=16, step=0.006, frame="h",
                 start="cap", end="cap" if fork > 0 else "tip", tip=0.8)
    F, f = pts[-1], (pts[-1] - pts[-2]).normalized()
    for s in ((1, -1) if fork > 0 else ()):  # fork=0: plain rounded tip (most non-squamates)
        tip = F + f * fork + V((0.010 * s, 0, 0.002))
        tongue.sweep([F - f * 0.006, F + f * fork * 0.4 + V((0.004 * s, 0, 0.001)), tip],
                     [(0.0065, 0.004, 0.0035, 2.2), (0.004, 0.0028, 0.0025, 2.2), (0.0008, 0.0008, 0.0008, 2.0)],
                     "tongue", N=10, step=0.004, frame="h", start="cap", end="tip", tip=1.0)
    return tongue, round((pts[-1] - pts[0]).length + fork, 3)


def mouth_weights(me, tree, prof):
    """w_mouth: surface seen from the mouth's inner axis and facing it (palate, jaw floor, inner lips)."""
    c = sd.coords(me)
    nrm = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3)
    y0, y1 = prof[0]["y"] - 0.05, prof[-1]["y"] + 0.03
    zlo, zhi = min(p["zl"] for p in prof) - 0.12, max(p["zu"] for p in prof) + 0.12
    sel = np.where((c[:, 1] > y0) & (c[:, 1] < y1) & (np.abs(c[:, 0]) < 0.2) & (c[:, 2] > zlo) & (c[:, 2] < zhi))[0]
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
    idx = np.where(w_mouth > 0.5)[0]
    w = np.zeros(len(c))
    if len(idx) == 0:
        return w
    kd = KDTree(len(idx))
    for j, i in enumerate(idx):
        kd.insert(c[i], j)
    kd.balance()
    for i in np.where(head_mask)[0]:
        w[i] = (1.0 - float(smoothstep(0.004, 0.016, kd.find(c[i])[2]))) * (1.0 - w_mouth[i])
    return w


# =========================================================================== eyes
def sph(axis, e1, e2, theta, phi):
    return axis * math.cos(theta) + (e1 * math.cos(phi) + e2 * math.sin(phi)) * math.sin(theta)


def build_eyes(cr, eye_ref):
    """Eyeball (eye_local attribute for the iris shader), gloss cornea cap, upper and lower lid caps."""
    e = cr.eye
    r, sink = e["radius"], e.get("sink", 0.003)
    ep, en = eye_ref
    c = ep - en * (r - sink)
    up = (Z - en * en.dot(Z)).normalized()
    side = up.cross(en)
    eyes = pm.Part(cr.prefix + "Eyes")
    el = eyes.bm.verts.layers.float_vector.new("eye_local")  # before any geometry (layer creation invalidates refs)
    faces = eyes.sphere(c, r, "eye", segs=48, rings_=24)
    for v in {v for f in faces for v in f.verts}:
        d = (v.co - c) / r
        v[el] = V((d.dot(side), d.dot(up), d.dot(en)))
    cornea = pm.Part(cr.prefix + "Cornea")
    cornea.patch(lambda u, v: c + sph(en, side, up, rad(52) * u, 2 * math.pi * v) * r * 1.035, 8, 32, 0.02, 0.1, "cornea")
    cornea.pack_uvs()
    bmesh.ops.remove_doubles(cornea.bm, verts=cornea.bm.verts[:], dist=1e-6)
    lids = pm.Part(cr.prefix + "Eyelids")
    (t_up, a_up), (t_lo, a_lo) = e.get("lid_up", (20, 48)), e.get("lid_lo", (15, 42))
    for axis, alpha in (((up * math.cos(rad(t_up)) + en * math.sin(rad(t_up))).normalized(), rad(a_up)),
                        ((-up * math.cos(rad(t_lo)) + en * math.sin(rad(t_lo))).normalized(), rad(a_lo))):
        e1 = axis.cross(side).normalized()
        e2 = axis.cross(e1)
        # 6 x 24 is enough for a cap that is mostly buried in the head (Exp 6 used 10 x 40: 7k triangles)
        lids.patch(lambda u, v, a=axis, e1=e1, e2=e2, al=alpha: c + sph(a, e1, e2, rad(3) + (al - rad(3)) * u, 2 * math.pi * v) * r * 1.07,
                   6, 24, 0.03, 0.15, "skin")
    lids.pack_uvs()
    bmesh.ops.remove_doubles(lids.bm, verts=lids.bm.verts[:], dist=1e-6)
    bmesh.ops.solidify(lids.bm, geom=lids.bm.faces[:], thickness=0.11 * r)
    for f in lids.bm.faces:
        f.smooth = True
    eyes.pack_uvs()
    for part in (eyes, cornea, lids):
        part.packed = True
    return [(eyes, True), (cornea, True), (lids, True)], c


# =========================================================================== body fields
def body_fields(cr, me, w_mouth, w_lip):
    """Per-vertex body coordinates (body_st) and region weights for detail_materials.body_skin."""
    c = sd.coords(me)
    n = len(c)
    chains = [("spine", dense(cr.spine(), 0.02))]
    for g, pts in list(cr.field_chains()) + [("toe", ch) for ch in cr.toe_chains]:
        step = 0.006 if g == "toe" else 0.02
        sides = (1, -1) if g in cr.mirrored_groups else (1,)
        for s in sides:
            chains.append((g, [mx(p, s) for p in dense(pts, step)]))
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
            if L < 1e-9:
                continue
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
    member = 1.0 - smoothstep(0.80, 0.95, stack[0] / np.maximum(stack[1], 1e-9)) if len(groups) > 1 else np.ones(n)
    r = c - b_foot
    r -= (r * b_tan).sum(1)[:, None] * b_tan
    r /= np.maximum(np.linalg.norm(r, axis=1), 1e-9)[:, None]
    side = np.cross(b_tan, [0.0, 0.0, 1.0])
    weak = np.linalg.norm(side, axis=1) < 0.3
    side[weak] = np.array([1.0, 0, 0]) - (b_tan[weak] @ np.array([1.0, 0, 0]))[:, None] * b_tan[weak]
    side /= np.maximum(np.linalg.norm(side, axis=1), 1e-9)[:, None]
    up = np.cross(side, b_tan)
    cos_up = (r * up).sum(1)
    t_coord = np.arccos(np.clip(-cos_up, -1, 1)) * best
    is_spine = b_group == groups.index("spine")
    is_toe = (b_group == groups.index("toe")) if "toe" in groups else np.zeros(n, bool)
    m_spine, m_toe = member * is_spine, member * is_toe
    w_up = np.where(is_spine, 0.5 + 0.5 * cos_up, 0.5 + 0.5 * r[:, 2])
    w_head = (1.0 - smoothstep(cr.head_y[0], cr.head_y[1], c[:, 1])) * smoothstep(cr.head_z[0], cr.head_z[1], c[:, 2])
    # girth-normalised coordinates for scales that must shrink with the body (neck, tail): R(s) = median distance
    # from the spine axis in 2 cm bins, smoothed; body_u = integral of R_REF / R ds (metres at reference girth)
    # (per chain group: the spine, and limbs so scales also shrink from thigh to ankle; left/right chains share s)
    R_REF = 0.12
    girth, body_u = np.ones(n), b_s.copy()
    for g_name, bin_w, f_min in (("spine", 0.02, 0.4), ("front", 0.01, 0.5), ("hind", 0.01, 0.5), ("arm", 0.015, 0.5)):
        if g_name not in groups:
            continue
        in_g = b_group == groups.index(g_name)
        sp = in_g & (member > 0.5)
        if sp.sum() < 100:
            continue
        edges = np.arange(0.0, b_s[sp].max() + bin_w, bin_w)
        idx = np.clip(np.digitize(b_s[sp], edges) - 1, 0, len(edges) - 1)
        med = np.array([np.median(best[sp][idx == i]) if (idx == i).any() else np.nan for i in range(len(edges))])
        ok = ~np.isnan(med)
        med = np.interp(edges, edges[ok], med[ok])
        med = np.convolve(np.pad(med, 3, mode="edge"), np.ones(7) / 7, mode="valid")
        f = np.clip(med / R_REF, f_min, 1.3)
        U = np.concatenate([[0.0], np.cumsum(bin_w / f[:-1])])
        girth = np.where(in_g, np.interp(b_s, edges, f), girth)
        body_u = np.where(in_g, np.interp(b_s, edges, U), body_u)
    is_limb = np.isin(b_group, [groups.index(g) for g in ("front", "hind", "arm") if g in groups])
    outward = np.sign(c[:, 0]) * r[:, 0]
    w_limb = member * is_limb * smoothstep(0.15, 0.55, outward) * smoothstep(0.08, 0.2, c[:, 2])
    w_limbdir = member * is_limb                                  # oriented limb scales all around the limb
    # v1.3 joint weight: 1 at limb joints (chain nodes where the limb bends by more than 25 deg), fading out over
    # 0.8-1.8 local limb radii; scale_field lowers scale height there when the creature sets joint_relief
    w_joint = np.zeros(n)
    for g, pts in cr.field_chains():
        if g not in ("front", "hind", "arm") or g not in groups:
            continue
        in_g = (b_group == groups.index(g)) & (member > 0.5)
        P = [np.array(p, float) for p in pts]
        for i in range(1, len(P) - 1):
            a_, b_ = P[i] - P[i - 1], P[i + 1] - P[i]
            if a_ @ b_ > math.cos(rad(25)) * np.linalg.norm(a_) * np.linalg.norm(b_):
                continue
            for s in ((1, -1) if g in cr.mirrored_groups else (1,)):
                dj = np.linalg.norm(c - np.array(mx(P[i], s)), axis=1)
                near = in_g & (dj < 0.12)
                R = float(np.median(best[near])) if near.sum() > 20 else 0.05
                w_joint = np.maximum(w_joint, 1.0 - smoothstep(0.8 * R, 1.8 * R, dj))
    w_joint *= member * is_limb
    for name, val in (("girth", girth), ("body_u", body_u)):          # unclipped scale coordinates
        a_ = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
        a_.data.foreach_set("value", val.astype(np.float32))
    attrs = {"w_up": w_up, "w_limb": w_limb, "w_limbdir": w_limbdir, "w_spine": m_spine,   # w_spine: trunk, neck, tail
             "w_dorsal": smoothstep(0.30, 0.55, cos_up) * m_spine * (1 - w_head),
             "w_belly": smoothstep(math.cos(rad(57)), math.cos(rad(43)), -cos_up) * m_spine * (1 - w_mouth),
             "w_head": w_head * (1 - w_mouth),
             "w_tail": smoothstep(cr.tail_y[0], cr.tail_y[1], c[:, 1]) * m_spine,
             "w_foot": smoothstep(-0.35, 0.0, r[:, 2]) * m_toe,
             "w_lip": w_lip, "w_mouth": w_mouth, "w_joint": w_joint}
    for name, val in attrs.items():
        a = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", np.clip(val, 0, 1).astype(np.float32))
    st = me.attributes.get("body_st") or me.attributes.new("body_st", "FLOAT_VECTOR", "POINT")
    t_dorsal = np.arccos(np.clip(cos_up, -1, 1)) * best   # arc distance from the chain's dorsal line (osteoderm rows)
    st.data.foreach_set("vector", np.stack([b_s, t_coord, t_dorsal], 1).astype(np.float32).ravel())
    return {k: int((v > 0.5).sum()) for k, v in attrs.items()}


# =========================================================================== objects, game mesh, bake
def to_object(part, collection, parent, mats):
    bmesh.ops.recalc_face_normals(part.bm, faces=part.bm.faces[:])
    me = bpy.data.meshes.new(part.name)
    part.bm.to_mesh(me)
    part.bm.free()
    for key in part.mats:
        me.materials.append(mats[key])
    ob = bpy.data.objects.new(part.name, me)
    collection.objects.link(ob)
    ob.parent = parent
    return ob


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


def deviation(sample, ob, regions):
    tree = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    d = np.array([tree.find_nearest(p)[3] for p in sample]) * 1000.0
    out, rest = {}, np.ones(len(sample), bool)
    for name, test in regions.items():
        m = test(sample) & rest
        rest &= ~m
        if m.any():
            out[name] = {"max_mm": round(float(d[m].max()), 1), "mean_mm": round(float(d[m].mean()), 2)}
    if rest.any():
        out["rest"] = {"max_mm": round(float(d[rest].max()), 1), "mean_mm": round(float(d[rest].mean()), 2)}
    out["all"] = {"max_mm": round(float(d.max()), 1), "mean_mm": round(float(d.mean()), 2), "p99_mm": round(float(np.percentile(d, 99)), 1)}
    return out


def bake_maps(cr, high, low, ov, sizes):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    mat = bpy.data.materials.new(cr.prefix + "body_baked")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    texs, rec = {}, {}
    for key, size in sizes.items():
        img = bpy.data.images.new(f"{cr.prefix}Body_{key}", size, size, alpha=False, float_buffer=False)
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
        scene.render.bake.margin = 16 if sizes[key] >= 4096 else 8
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
                cr.log["errors"].append(f"bake {key}: {exc}")
        texs[key].image.pack()
        px = np.empty(sizes[key] * sizes[key] * 4, np.float32)
        texs[key].image.pixels.foreach_get(px)
        rec[key] = {"size": sizes[key], "result": res, "seconds": round(time.perf_counter() - t, 2),
                    "mean_rgb": [round(float(v), 3) for v in px.reshape(-1, 4)[:, :3].mean(0)]}
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type, mul.blend_type = "RGBA", "MULTIPLY"
    dm.sock(mul.inputs, "Factor_Float").default_value = 1.0
    nt.links.new(texs["color"].outputs["Color"], dm.sock(mul.inputs, "A_Color"))
    nt.links.new(texs["ao"].outputs["Color"], dm.sock(mul.inputs, "B_Color"))
    nt.links.new(dm.sock(mul.outputs, "Result_Color"), bsdf.inputs["Base Color"])
    nt.links.new(texs["roughness"].outputs["Color"], bsdf.inputs["Roughness"])
    for k, v in dm.sss_inputs("body").items():        # v1.3 body:sss carries over to the game material
        bsdf.inputs[k].default_value = v
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(texs["normal"].outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return rec


def build_game_mesh(cr, high, col, ov, sizes, src=None, sample=None):
    """Retopology gate / decimate from `src` (the secondary-form mesh, much lighter than the high-poly) and
    bake from `high`. The deviation gate is measured against the high-poly surface."""
    src = src or high
    scaled = sd.coords(high.data)[::max(8, len(high.data.vertices) // 120000)]
    if sample is None:  # gate against the surface the low mesh must follow (pre-scale when scales are geometry)
        sample = scaled
    regions = cr.regions()
    rec = {}
    q = duplicate(src, cr.prefix + "Body_QF", col)
    select_only(q)
    t = time.perf_counter()
    with bpy.context.temp_override(**dict(ov, active_object=q, object=q, selected_objects=[q], selected_editable_objects=[q])):
        try:
            bpy.ops.object.quadriflow_remesh(target_faces=cr.retopo_faces, use_mesh_symmetry=False, use_preserve_sharp=False,
                                             use_preserve_boundary=False, seed=0, mode="FACES")
        except RuntimeError as exc:
            rec["quadriflow_error"] = repr(exc)
    sw = q.modifiers.new("Project", "SHRINKWRAP")
    sw.target, sw.wrap_method = high, "NEAREST_SURFACEPOINT"
    apply_mods(q)
    dev = deviation(sample, q, regions)
    ok = all(v["max_mm"] <= cr.gate_max_mm and v["mean_mm"] <= cr.gate_mean_mm for k, v in dev.items() if k != "all")
    rec["quadriflow"] = {"faces": len(q.data.polygons), "seconds": round(time.perf_counter() - t, 2), "deviation": dev, "accepted": ok}
    if ok:
        low = q
    else:
        bpy.data.objects.remove(q)
        low = duplicate(src, cr.prefix + "Body_Decimated", col)
        t = time.perf_counter()
        ratio = cr.decimate_tris / (2.0 * len(src.data.polygons))
        m = low.modifiers.new("Decimate", "DECIMATE")
        m.decimate_type, m.use_collapse_triangulate, m.ratio = "COLLAPSE", True, ratio
        apply_mods(low)
        low.data.calc_loop_triangles()
        rec["decimate"] = {"ratio": round(ratio, 4), "triangles": len(low.data.loop_triangles),
                           "seconds": round(time.perf_counter() - t, 2), "deviation": deviation(sample, low, regions)}
        if scaled is not sample:  # informative: scale relief the normal map must carry
            rec["decimate"]["deviation_to_scaled_surface"] = deviation(scaled, low, regions)["all"]
    low.name = low.data.name = cr.prefix + "Body"
    for a in [a.name for a in low.data.attributes if a.name == "body_st" or a.name.startswith("w_")]:
        low.data.attributes.remove(low.data.attributes[a])
    select_only(low)
    with bpy.context.temp_override(**dict(ov, active_object=low, object=low, selected_objects=[low], selected_editable_objects=[low])):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        rec["smart_uv"] = str(bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.003))
        bpy.ops.object.mode_set(mode="OBJECT")
    low.data.shade_smooth()
    t = time.perf_counter()
    rec["bake"] = bake_maps(cr, high, low, ov, sizes)
    rec["bake_seconds"] = round(time.perf_counter() - t, 2)
    camera_setup.configure_render(bpy.context.scene)
    low.data.calc_loop_triangles()
    rec["low_triangles"] = len(low.data.loop_triangles)
    return low, rec


def save_blend(path):
    tmp = os.path.join(tempfile.mkdtemp(prefix="crt_"), os.path.basename(path))
    bpy.ops.wm.save_as_mainfile(filepath=tmp, compress=False, copy=True)
    shutil.move(tmp, camera_setup._long_path(path))


# =========================================================================== pipeline
def build(cr, out_dir):
    log = cr.log
    bpy.context.preferences.filepaths.save_version = 0
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    plan, log["surface_plan_warnings"] = surface_plan.resolve(cr.surface_plan)   # v1.3: what surface goes where
    log["fur_planned"] = surface_plan.fur_requests(plan)                         # interface only: nothing is built
    log["surface_plan"] = surface_plan.summary(plan)
    mats = dm.build_all(palette=cr.palette, stripes=cr.stripes, prefix=cr.prefix + "M_", geo_scales=bool(cr.scales),
                        profiles=[r["material_profile"] for r in plan if r.get("enabled", True)])
    log["material_profiles"] = {k: dict(v) for k, v in dm.PROFILE.items()}
    scene = bpy.context.scene
    settings = camera_setup.load_settings()
    col = camera_setup.ensure_collection(settings["collections"]["model"], scene)
    root = bpy.data.objects.new(cr.prefix + "Root", None)
    col.objects.link(root)
    camera_setup.build_rig(scene)

    bm = cr.build_base()
    vol_bm, log["anatomy"] = anatomy_volumes(cr, bm)
    me = bpy.data.meshes.new(cr.prefix + "Body_HighRes")
    bm.to_mesh(me)
    bm.free()
    high = bpy.data.objects.new(cr.prefix + "Body_HighRes", me)
    col.objects.link(high)
    high.parent = root
    select_only(high)
    log["loft_faces"] = len(me.polygons)
    sub = high.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = sub.render_levels = 2
    apply_mods(high)                         # Catmull-Clark first: voxel remesh reproduces raw loft facets
    cr.mark("lofts_built")
    sc = None if DRY_RUN else sd.Sculptor(high, log)
    ov = sc.ov() if sc else {"active_object": high, "object": high}
    me = high.data                           # apply_mods replaced the datablock
    me.remesh_voxel_size, me.remesh_voxel_adaptivity = cr.voxel, 0.0
    for prop in ("use_remesh_fix_poles", "use_remesh_preserve_volume"):
        if hasattr(me, prop):
            setattr(me, prop, True)
    with bpy.context.temp_override(**ov):
        bpy.ops.object.voxel_remesh()
    high.data.shade_smooth()
    log["fused_faces"] = len(high.data.polygons)
    primary = duplicate(high, cr.prefix + "Body_Primary", col)
    col.objects.unlink(primary)
    primary_path = os.path.join(out_dir, f"{cr.name}_primary.blend")
    bpy.data.libraries.write(camera_setup._long_path(primary_path) if len(primary_path) > 250 else primary_path, {primary},
                             fake_user=True)  # reference for the added-form metric (quality_metrics --ref)
    bpy.data.objects.remove(primary)
    cr.mark("voxel_fused")

    if sc:
        sc.mode("SCULPT")
        sc.phase = "fillet"
        sc.cavity_fillet(iterations=30)
    if vol_bm is not None:                  # second fusion: anatomy volumes on the cleaned base
        if sc:
            sc.mode("OBJECT")
        vme = bpy.data.meshes.new("tmp_anatomy")
        vol_bm.to_mesh(vme)
        vol_bm.free()
        vob = bpy.data.objects.new("tmp_anatomy", vme)
        col.objects.link(vob)
        vs = vob.modifiers.new("Subdivision", "SUBSURF")
        vs.levels = 2                       # loft facets would survive the remesh as stripes
        apply_mods(vob)
        merged = bmesh.new()
        merged.from_mesh(high.data)
        merged.from_mesh(vob.data)
        merged.to_mesh(high.data)
        merged.free()
        bpy.data.objects.remove(vob)
        with bpy.context.temp_override(**ov):
            bpy.ops.object.voxel_remesh()
        high.data.shade_smooth()
        log["anatomy_fused_faces"] = len(high.data.polygons)
        if sc:
            sc.mode("SCULPT")
            sc.phase = "anatomy_fillet"
            if cr.anatomy_fillet:
                sc.cavity_fillet(iterations=cr.anatomy_fillet)
    if sc:
        for phase, specs in cr.strokes():
            if phase in cr.hipoly_phases:
                continue
            sc.phase = phase
            for s in specs:
                sc.stroke(s)
        sc.mode("OBJECT")
    cr.mark("sculpted" if sc else "sculpt_skipped_dry_run")

    high.data.update()
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    feats = cr.features(tree)                # references taken before any carving
    eye_ref = None
    for f in feats:
        if f["name"] == "eye":
            eye_ref = f["ref"]
        p, nrm = f["ref"]
        for s in (1, -1):
            log.setdefault("displaced_vertices", {}).setdefault(f["name"], []).append(
                displace(high.data, mx(p, s), mx(nrm, s), f["radius"], f["depth"], f["rim"], f.get("upper", 0.0)))
    cr.mark("features_carved")

    high.data.update()
    tree = BVHTree.FromObject(high, bpy.context.evaluated_depsgraph_get())
    c = sd.coords(high.data)
    prof, w_mouth = None, np.zeros(len(c))
    if cr.mouth:
        prof = mouth_profile(tree, cr.mouth["head_pts"], cr.mouth["head_shapes"], cr.mouth["y_back"])
        log["mouth_profile"] = [{k: round(v, 4) for k, v in p.items()} for p in prof]
        w_mouth = mouth_weights(high.data, tree, prof)
    head_mask = (c[:, 1] < cr.head_y[1] + 0.02) & (c[:, 2] > cr.head_z[0] - 0.05)
    w_lip = lip_weights(c, w_mouth, head_mask)
    log["field_vertices_over_half"] = body_fields(cr, high.data, w_mouth, w_lip)
    log["surface_region_vertices"] = {r["region_id"]: log["field_vertices_over_half"].get(r["weight"])
                                      for r in plan if r.get("weight")}
    high.data.materials.append(mats["body"])
    cr.mark("fields_written")

    # high-poly stage: keep the secondary-form mesh for retopology/decimation, subdivide the sculpt for fine work
    mid = duplicate(high, cr.prefix + "Body_Mid", col)
    col.objects.unlink(mid)                  # kept in memory only (not rendered, not saved)
    log["mid_faces"] = len(mid.data.polygons)
    if cr.hipoly_subdiv:
        hs = high.modifiers.new("HiPoly", "SUBSURF")
        hs.levels = hs.render_levels = cr.hipoly_subdiv
        apply_mods(high)                     # generic attributes (body fields) are interpolated by the subdivision
        high.data.shade_smooth()
    log["hipoly_faces"] = len(high.data.polygons)
    cr.mark("hipoly_built")
    if sc:
        sc.mode("SCULPT")
        for phase, specs in cr.strokes():
            if phase not in cr.hipoly_phases:
                continue
            sc.phase = phase + "_hipoly"
            for s in specs:
                sc.stroke(s)
        sc.mode("OBJECT")
        log["strokes_off_target"] = [(s["label"], s["target_mm"], s["achieved_mm"]) for s in log["strokes"]
                                     if s["target_mm"] and not 0.7 * s["target_mm"] <= s["achieved_mm"] <= 1.6 * s["target_mm"]]
        cr.mark("hipoly_sculpted")
    pre_scale = None
    if cr.scales:                            # Phase B: Level 1 plates + Level 2 scales as real displacement
        import scale_field
        pre_scale = sd.coords(high.data)[::max(8, len(high.data.vertices) // 120000)]
        log["scales"] = scale_field.apply(high.data, surface_plan.scale_spec(plan, cr.scales, cr.joint_relief))
        high.data.update()
        cr.mark("scales_displaced")

    ctx = {"tree": tree, "prof": prof, "eye_ref": eye_ref, "info": cr.info, "rng": np.random.default_rng(6), "high": high,
           "collars": []}
    parts = []
    if cr.eye and eye_ref:
        eye_parts, centre = build_eyes(cr, eye_ref)
        parts += eye_parts
        log["eye_center"] = [round(v, 4) for v in centre]
    if prof:
        t = cr.mouth.get("teeth")
        if t is not None:
            teeth, log["teeth"] = build_teeth(tree, prof, cr.prefix + "Teeth", **t)
            parts.append((teeth, True))
        g = cr.mouth.get("tongue")
        if g is not None:
            tongue, log["tongue_length_m"] = build_tongue(tree, prof, cr.prefix + "Tongue", **g)
            parts.append((tongue, False))
    parts += cr.inserts(ctx)
    if cr.insert_collars and ctx["collars"]:          # v1.3: inserts grow out of the skin
        log["insert_collars"] = {"count": len(ctx["collars"]), "vertices_moved": apply_collars(high.data, ctx["collars"])}
    objs = []
    for part, mirror in parts:
        if not getattr(part, "packed", False):
            part.pack_uvs()
        if mirror:
            part.mirror_x()
        objs.append(to_object(part, col, root, mats))
    log["inserts"] = {o.name: len(o.data.polygons) for o in objs}
    claws_z = [min((o.matrix_world @ v.co).z for v in o.data.vertices) for o in objs if "Claw" in o.name]
    log["lowest_claw_z_mm"] = round(min(claws_z) * 1000, 2) if claws_z else None
    cr.mark("inserts_built")
    save_blend(os.path.join(out_dir, f"{cr.name}_highres.blend"))
    cr.mark("highres_saved")

    sizes = {k: 512 for k in cr.bake} if DRY_RUN else cr.bake
    low, rec = build_game_mesh(cr, high, col, ov, sizes, src=mid, sample=pre_scale)
    bpy.data.objects.remove(mid)
    low.parent = root
    log["game_mesh"] = rec
    cr.mark("game_mesh_baked")
    bpy.data.objects.remove(high)
    save_blend(os.path.join(out_dir, f"{cr.name}.blend"))
    cr.mark("game_saved")
    log["objects"] = [o.name for o in col.objects]


def run(cr, script_file):
    """Entry point for creature scripts: run(MyCreature(), __file__)."""
    if cr.settings:
        os.environ["CREATURE_SETTINGS"] = cr.settings
        camera_setup.SETTINGS_PATH = cr.settings
    out_dir = ((os.environ.get("CREATURE_DRY_DIR") or tempfile.mkdtemp(prefix=f"{cr.name}_dry_")) if DRY_RUN else
               os.environ.get("CREATURE_OUT_DIR") or cr.out_dir or os.path.dirname(os.path.abspath(script_file)))
    os.makedirs(out_dir, exist_ok=True)
    too_long = [p for p in (os.path.abspath(script_file), os.path.join(HERE, "material_palette.py")) if len(p) > 250]
    if too_long:  # Blender's file loaders and image writers fail past 260 characters on Windows
        print(f"[bench] WARNING paths near the Windows 260-character limit: {too_long}")

    def tick():
        try:
            build(cr, out_dir)
        except Exception:  # noqa: BLE001
            cr.log["errors"].append(traceback.format_exc())
            print(traceback.format_exc())
        cr.log["total_seconds"] = round(time.perf_counter() - T0, 2)
        cr.log["output_dir"] = out_dir
        with open(camera_setup._long_path(os.path.join(out_dir, f"{cr.name}_log.json")), "w", encoding="utf-8") as fh:
            json.dump(cr.log, fh, indent=1, default=str)
        print(f"[bench] log -> {out_dir}  errors: {len(cr.log['errors'])}")
        sys.stdout.flush()
        if cr.log["errors"]:
            os._exit(1)  # honest exit code (quit_blender always returns 0)
        bpy.ops.wm.quit_blender()

    if DRY_RUN:
        print(f"[bench] DRY RUN (no sculpt) -> {out_dir}")
        tick()
    elif bpy.app.background:
        raise SystemExit("Sculpt mode needs the Blender GUI; use CREATURE_DRY_RUN=1 for a headless test.")
    else:
        bpy.app.timers.register(tick, first_interval=2.0)
