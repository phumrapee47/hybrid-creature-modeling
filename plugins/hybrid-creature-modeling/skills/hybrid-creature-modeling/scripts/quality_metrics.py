"""Geometric quality metrics for a creature .blend (used by the audit and the quality gates).

Usage:
  blender -b <model.blend> --python quality_metrics.py -- --out <metrics.json> [--objects NAME ...]

Per mesh object (evaluated, world space):
  triangles, median edge length (mm)          -> how much detail the mesh can hold at all
  relief_fine_mm / relief_medium_mm            -> how much sculpted form exists at two wavelengths:
      distance (along the normal) between the surface and a Taubin-smoothed copy of itself.
      fine   = 8 Taubin iterations   (removes features up to roughly 4-6 edge lengths: scales, wrinkles)
      medium = 60 Taubin iterations  (removes features up to roughly 10-15x the edge length: muscles, plates)
      fine - (a smooth surface) is ~0; a deeply scaled sculpt shows millimetres everywhere.
  relief by region (bands along +Y, the body axis) so a detailed head cannot hide a smooth tail.
Shader bump and normal maps are invisible here by design: this measures geometry only.
"""
import argparse
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--objects", nargs="*", default=None)
ap.add_argument("--ref-edge-mm", type=float, default=3.2, help="edge length the iteration counts are calibrated for")
ap.add_argument("--ref", default=None, help="<name>_primary.blend from the kit: also report form added on top of the primary lofts")
args = ap.parse_args(argv)


def mesh_arrays(ob, depsgraph):
    ev = ob.evaluated_get(depsgraph)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(ob.matrix_world)
    co = co @ mw[:3, :3].T + mw[:3, 3]
    nr = np.empty(n * 3)
    me.vertices.foreach_get("normal", nr)
    nr = nr.reshape(-1, 3) @ mw[:3, :3].T
    nr /= np.maximum(np.linalg.norm(nr, axis=1), 1e-12)[:, None]
    ed = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ed)
    ed = ed.reshape(-1, 2)
    me.calc_loop_triangles()
    tris = len(me.loop_triangles)
    ev.to_mesh_clear()
    return co, nr, ed, tris


def taubin(co, ed, iters, lam=0.5, mu=-0.53):
    n = len(co)
    deg = np.bincount(ed.ravel(), minlength=n).astype(float)
    deg = np.maximum(deg, 1)
    p = co.copy()
    for _ in range(iters):
        for f in (lam, mu):
            acc = np.zeros_like(p)
            for k in range(3):
                acc[:, k] = np.bincount(ed[:, 0], p[ed[:, 1], k], n) + np.bincount(ed[:, 1], p[ed[:, 0], k], n)
            p = p + f * (acc / deg[:, None] - p)
    return p


def secondary_relief(ob, dg, co_full, nr_full, wavelength=0.15, target_faces=60000):
    """Forms of muscle/plate scale (roughly 3-15 cm): distance from the full surface to a heavily smoothed,
    decimated copy. Run on a decimated copy because the needed smoothing would take thousands of iterations
    at full resolution."""
    tmp = ob.copy()
    tmp.data = ob.data.copy()
    bpy.context.scene.collection.objects.link(tmp)
    m = tmp.modifiers.new("dec", "DECIMATE")
    m.ratio = min(1.0, target_faces / max(len(tmp.data.polygons), 1))
    dg.update()
    ev = tmp.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    mw = np.array(tmp.matrix_world)
    co = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    ed = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", ed)
    ed = ed.reshape(-1, 2)
    me.calc_loop_triangles()
    tri = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    ev.to_mesh_clear()
    bpy.data.objects.remove(tmp)
    elen = float(np.median(np.linalg.norm(co[ed[:, 0]] - co[ed[:, 1]], axis=1)))
    iters = int(min(max(round((wavelength / (1.7 * elen)) ** 2), 10), 400))
    sm = taubin(co, ed, iters)
    tree = BVHTree.FromPolygons([Vector(p) for p in sm], tri.reshape(-1, 3).tolist())
    step = max(1, len(co_full) // 150000)
    d = []
    for p in co_full[::step]:
        loc, nrm, _, _ = tree.find_nearest(Vector(p))
        if loc is not None:
            d.append((Vector(p) - loc).dot(nrm))
    return np.array(d), {"coarse_edge_mm": round(elen * 1000, 1), "iterations": iters, "samples": len(d)}


def pct(a):
    a = np.abs(a) * 1000.0
    return {"p50": round(float(np.percentile(a, 50)), 2), "p90": round(float(np.percentile(a, 90)), 2),
            "p99": round(float(np.percentile(a, 99)), 2)}


def load_reference(path):
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.endswith("Body_Primary")]
    ob = dst.objects[0]
    me = ob.data
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    me.calc_loop_triangles()
    tri = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    return BVHTree.FromPolygons([Vector(p) for p in co.reshape(-1, 3)], tri.reshape(-1, 3).tolist())


def added_form(co, tree, regions):
    """Signed distance from the final surface to the primary-form surface (positive = built up)."""
    step = max(1, len(co) // 200000)
    pts = co[::step]
    d = np.zeros(len(pts))
    for i, p in enumerate(pts):
        loc, nrm, _, _ = tree.find_nearest(Vector(p))
        d[i] = (Vector(p) - loc).dot(nrm) if loc is not None else 0.0
    keep = pts[:, 2] > 0.08  # feet differ between builds (toe placement), measure the body
    res = {"all": pct(d[keep]), "built_up_p90_mm": round(float(np.percentile(np.clip(d[keep], 0, None), 90)) * 1000, 2)}
    y = pts[keep, 1]
    for nm, (a, b) in regions.items():
        m = (y >= a) & (y < b)
        if m.any():
            res[nm] = pct(d[keep][m])
    return res


dg = bpy.context.evaluated_depsgraph_get()
out = {"file": os.path.basename(bpy.data.filepath), "objects": {}}
ref_tree = load_reference(args.ref) if args.ref else None
for ob in bpy.data.objects:
    if ob.type != "MESH" or ob.name.startswith("RIG_") or (args.objects and ob.name not in args.objects):
        continue
    co, nr, ed, tris = mesh_arrays(ob, dg)
    if len(co) < 50:
        continue
    elen = np.linalg.norm(co[ed[:, 0]] - co[ed[:, 1]], axis=1)
    rec = {"triangles": tris, "vertices": len(co), "median_edge_mm": round(float(np.median(elen)) * 1000, 2)}
    if len(co) > 2000:
        # diffusion length ~ edge * sqrt(iterations): scale the iterations so the same physical wavelengths are
        # removed at any mesh resolution (calibrated at 3.2 mm edges: fine 8, medium 60)
        k = (args.ref_edge_mm / max(rec["median_edge_mm"], 0.1)) ** 2
        rec["taubin_iterations"] = [min(int(round(8 * k)), 600), min(int(round(60 * k)), 1500)]
        fine = ((co - taubin(co, ed, rec["taubin_iterations"][0])) * nr).sum(1)
        med = ((co - taubin(co, ed, rec["taubin_iterations"][1])) * nr).sum(1)
        rec["relief_fine_mm"], rec["relief_medium_mm"] = pct(fine), pct(med)
        if len(co) > 50000:
            sec, info = secondary_relief(ob, dg, co, nr)
            rec["relief_secondary_mm"], rec["relief_secondary_info"] = pct(sec), info
        y = co[:, 1]
        edges = np.quantile(y, [0, 0.2, 0.4, 0.6, 0.8, 1.0])
        names = ["front_20pct (head/neck)", "20-40pct (chest)", "40-60pct (body)", "60-80pct (hips/tail)", "rear_20pct (tail)"]
        rec["relief_fine_by_region_p90_mm"] = {nm: round(float(np.percentile(np.abs(fine[(y >= a) & (y <= b)]) * 1000, 90)), 2)
                                               for nm, a, b in zip(names, edges, edges[1:])}
    if ref_tree is not None and ob.name.endswith("Body_HighRes"):
        rec["added_form_mm"] = added_form(co, ref_tree, {"head (y<-0.72)": (-9, -0.72), "neck+chest": (-0.72, -0.2),
                                                         "body": (-0.2, 0.45), "tail": (0.45, 9)})
    out["objects"][ob.name] = rec
    print(f"[bench] {ob.name}: {rec.get('triangles')} tris, edge {rec['median_edge_mm']} mm, fine {rec.get('relief_fine_mm')}")
with open(args.out, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
print("[bench] metrics written")
