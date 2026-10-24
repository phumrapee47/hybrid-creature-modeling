"""Reusable procedural mesh helpers (spline sweeps, parametric patches, UV packing).

Extracted from experiment_02_advanced_procedural/dragon_advanced.py, which stays
self-contained and unchanged. Used by later experiments for non-sculpted inserts
(horns, spikes, claws, wing membranes).
"""
import bisect
import math

import bpy
import bmesh
from mathutils import Matrix, Vector

import material_palette as mp

V = Vector
TAU = 2 * math.pi
Z = V((0, 0, 1))
X = V((1, 0, 0))


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

    def point(self, frac):
        return self.at(frac * self.length)[0]


def shape_at(shapes, u):
    n = len(shapes)
    i = min(int(u), n - 2)
    f = u - i
    g = lambda k: shapes[min(max(k, 0), n - 1)]  # noqa: E731
    a, b, c, d = g(i - 1), g(i), g(i + 1), g(i + 2)
    return [cr(a[m], b[m], c[m], d[m], f) for m in range(len(b))]


def frame_axes(t, mode, hint):
    side = t.cross(Z) if mode == "h" else hint - t * t.dot(hint)
    side.normalize()
    return side, side.cross(t)


def ring(center, side, up, w, ap, an, ex, N, bumps=()):
    """Superellipse section; angle 0 = -up (ventral, UV seam), pi/2 = +side, pi = +up (dorsal).
    bumps: (angle, angular width, amplitude) radial bulges (brow, keel, crest...)."""
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


class Part:
    """bmesh accumulator with material slots, UV islands and sweep/patch builders."""

    def __init__(self, name):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.verify()
        # "tip_t": 0 at a sweep's start, 1 at its end (shaders use it for base-to-tip gradients). Created up
        # front: adding a bmesh layer later invalidates every Python reference to existing elements.
        self.tip = self.bm.verts.layers.float.new("tip_t")
        self.mats = []
        self.islands = []

    def mi(self, key):
        if key not in self.mats:
            self.mats.append(key)
        return self.mats.index(key)

    def sweep(self, pts, shapes, mat, N=12, step=0.01, frame="h", hint=X, start="cap", end="tip", scale_fn=None, tip=0.6,
              bumps=None):
        """Loft superellipse sections along a spline. Shape tuples: (w, ap, an, n, extra...);
        bumps: (angle, width, index into the shape tuple) for radial bulges."""
        path = Path(pts)
        n = max(2, round(path.length / step))
        rings, recs = [], []
        for k in range(n + 1):
            s = path.length * k / n
            pos, t, u = path.at(s)
            vals = shape_at(shapes, u)
            w, ap, an, ex = vals[:4]
            w, ap, an = max(w, 0.0008), max(ap, 0.0008), max(an, 0.0008)
            if scale_fn:
                sc = scale_fn(s, path.length)
                w, ap, an = w * sc, ap * sc, an * sc
            side, up = frame_axes(t, frame, hint)
            bl = [(ang, width, vals[idx]) for ang, width, idx in bumps] if bumps else ()
            rings.append(ring(pos, side, up, w, ap, an, ex, N, bl))
            recs.append({"pos": pos, "t": t, "s": s, "r": (w + ap + an) / 3})
        self._loft(rings, recs, mat, start, end, tip)
        return path

    def _loft(self, rings, recs, mat, start, end, tip):
        bm, uv = self.bm, self.uv
        N = len(rings[0])
        perim = sum(sum((r[j] - r[(j + 1) % N]).length for j in range(N)) for r in rings) / len(rings)
        vs = [[bm.verts.new(p) for p in r] for r in rings]
        tl = self.tip
        L = max(recs[-1]["s"], 1e-9)
        for ring_vs, rec in zip(vs, recs):
            for v in ring_vs:
                v[tl] = rec["s"] / L
        mdef = self.mi(mat)
        faces = []
        for k in range(len(rings) - 1):
            for j in range(N):
                jn = (j + 1) % N
                f = bm.faces.new((vs[k][j], vs[k][jn], vs[k + 1][jn], vs[k + 1][j]))
                f.material_index = mdef
                f.smooth = True
                for lp, (jj, kk) in zip(f.loops, ((j, k), (j + 1, k), (j + 1, k + 1), (j, k + 1))):
                    lp[uv].uv = (jj / N * perim, recs[kk]["s"])
                faces.append(f)
        for which, mode in (("start", start), ("end", end)):
            if mode is None:
                continue
            k = 0 if which == "start" else len(rings) - 1
            rec, sign = recs[k], (-1 if which == "start" else 1)
            pole = bm.verts.new(rec["pos"] + rec["t"] * (sign * tip * rec["r"] if mode == "tip" else 0.0))
            pole[tl] = 0.0 if which == "start" else 1.0
            for j in range(N):
                f = bm.faces.new((vs[k][j], vs[k][(j + 1) % N], pole))
                f.material_index = mdef
                f.smooth = True
                for lp, uvc in zip(f.loops, ((j / N * perim, rec["s"]), ((j + 1) / N * perim, rec["s"]),
                                             ((j + 0.5) / N * perim, rec["s"] + sign * 0.01))):
                    lp[uv].uv = uvc
                faces.append(f)
        self.islands.append(faces)

    def sphere(self, center, radius, mat, segs=24, rings_=12):
        m = Matrix.Translation(center) @ Matrix.Diagonal((radius, radius, radius, 1.0))
        return self._uvsphere(m, mat, segs, rings_)

    def ellipsoid_axes(self, center, ax, ay, az, mat, segs=12, rings_=8):
        m = Matrix.Identity(4)
        for col, axis in enumerate((ax, ay, az)):
            for row in range(3):
                m[row][col] = axis[row]
        m.translation = center
        return self._uvsphere(m, mat, segs, rings_)

    def _uvsphere(self, m, mat, segs, rings_):
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=segs, v_segments=rings_, radius=1.0, matrix=m, calc_uvs=True)
        faces = list({f for v in res["verts"] for f in v.link_faces})
        for f in faces:
            f.material_index = self.mi(mat)
            f.smooth = True
        self.islands.append(faces)
        return faces

    def patch(self, fn, nu, nv, lu, lv, mat):
        """Parametric surface grid P(u, v) for u, v in [0, 1] (membranes)."""
        bm, uv = self.bm, self.uv
        grid = [[bm.verts.new(fn(i / nu, k / nv)) for k in range(nv + 1)] for i in range(nu + 1)]
        faces = []
        for i in range(nu):
            for k in range(nv):
                f = bm.faces.new((grid[i][k], grid[i + 1][k], grid[i + 1][k + 1], grid[i][k + 1]))
                f.material_index = self.mi(mat)
                f.smooth = True
                for lp, (a, b) in zip(f.loops, ((i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1))):
                    lp[uv].uv = (a / nu * lu, b / nv * lv)
                faces.append(f)
        self.islands.append(faces)

    def pack_uvs(self, margin=0.02):
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

    def to_object(self, collection, parent=None, subsurf=0):
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


def claw(part, base, d, length, r0):
    """Hooked, tapered claw sweep along a curved path."""
    d = V(d).normalized()
    down = V((0, 0, -1))
    pts = [base - d * 0.004, base + d * length * 0.45 + down * length * 0.06,
           base + d * length * 0.8 + down * length * 0.3, base + d * length * 0.95 + down * length * 0.62]
    part.sweep(pts, [(r0 * 0.8, r0, r0, 2.0), (r0 * 0.62, r0 * 0.8, r0 * 0.8, 2.0),
                     (r0 * 0.35, r0 * 0.45, r0 * 0.45, 2.0), (0.0008, 0.0008, 0.0008, 2.0)],
               "claw", N=8, step=max(length / 7, 0.005), frame="hint", hint=X if abs(d.x) < 0.7 else V((0, 1, 0)),
               start="cap", end="tip", tip=0.5)
