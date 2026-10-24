"""Open a saved dragon .blend in a fresh Blender process and collect geometry statistics.

Usage:
  blender -b <model.blend> --python shared/inspect_model.py -- --out <stats.json>
Successfully reaching the end of this script is the "file opens" verification.
"""
import argparse
import json
import os
import sys

import bpy
import bmesh
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camera_setup  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--cage", action="store_true", help="measure with Subdivision Surface modifiers disabled")
args = ap.parse_args(argv)

settings = camera_setup.load_settings()
col = bpy.data.collections.get(settings["collections"]["model"])
objs = [o for o in col.all_objects if o.type == "MESH"] if col else []
if args.cage:
    for o in objs:
        for m in o.modifiers:
            if m.type == "SUBSURF":
                m.show_viewport = m.show_render = False
dg = bpy.context.evaluated_depsgraph_get()


def count_shells(bm):
    seen, shells = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        shells += 1
        stack = [v]
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
    return shells


per_obj, all_co = [], []
tot = {"vertices": 0, "edges": 0, "polygons": 0, "triangles": 0, "base_vertices": 0, "base_polygons": 0,
       "shells": 0, "non_manifold_edges": 0, "boundary_edges": 0}
materials = set()
for o in objs:
    oe = o.evaluated_get(dg)
    me = oe.to_mesh()
    me.calc_loop_triangles()
    n = len(me.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    mw = np.array(o.matrix_world)
    co = co @ mw[:3, :3].T + mw[:3, 3]
    all_co.append(co)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.index_update()
    nm = sum(1 for e in bm.edges if not e.is_manifold)
    bd = sum(1 for e in bm.edges if e.is_boundary)
    shells = count_shells(bm)
    bm.free()
    rec = {"name": o.name, "vertices": n, "edges": len(me.edges), "polygons": len(me.polygons),
           "triangles": len(me.loop_triangles), "base_vertices": len(o.data.vertices),
           "base_polygons": len(o.data.polygons), "shells": shells, "non_manifold_edges": nm,
           "boundary_edges": bd, "modifiers": [m.type for m in o.modifiers],
           "uv_layers": len(o.data.uv_layers),
           "materials": [s.material.name for s in o.material_slots if s.material]}
    materials.update(rec["materials"])
    oe.to_mesh_clear()
    for k in tot:
        tot[k] += rec[k]
    per_obj.append(rec)

def buried_surface(objects, depsgraph, eps=0.0015):
    """Approximate share of surface hidden inside *other* closed shells of the model.

    For every face, a point 1.5 mm outside it along its normal is tested against every
    other shell whose bounding box contains it, using ray-parity (odd hit count = inside).
    Open shells make parity approximate, so this is reported as an estimate.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    direction = Vector((0.123, 0.456, 0.881)).normalized()
    shells, faces = [], []
    for o in objects:
        me = o.evaluated_get(depsgraph).to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(o.matrix_world)
        bm.normal_update()
        bm.faces.ensure_lookup_table()
        sid = [-1] * len(bm.faces)
        for f0 in bm.faces:
            if sid[f0.index] >= 0:
                continue
            key, stack, members = len(shells), [f0], []
            sid[f0.index] = key
            while stack:
                f = stack.pop()
                members.append(f)
                for v in f.verts:
                    for g in v.link_faces:
                        if sid[g.index] < 0:
                            sid[g.index] = key
                            stack.append(g)
            vmap, verts, polys = {}, [], []
            for f in members:
                idx = []
                for v in f.verts:
                    if v.index not in vmap:
                        vmap[v.index] = len(verts)
                        verts.append(v.co.copy())
                    idx.append(vmap[v.index])
                polys.append(idx)
                faces.append((f.calc_center_median() + f.normal * eps, f.calc_area(), key))
            xs, ys, zs = zip(*verts)
            shells.append((BVHTree.FromPolygons(verts, polys), (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))))
        bm.free()
        o.evaluated_get(depsgraph).to_mesh_clear()
    buried_n, buried_a, total_a = 0, 0.0, 0.0
    for p, area, own in faces:
        total_a += area
        for k, (tree, mn, mx) in enumerate(shells):
            if k == own or not all(mn[i] <= p[i] <= mx[i] for i in range(3)):
                continue
            hits, origin = 0, p
            while True:
                loc, _, _, _ = tree.ray_cast(origin, direction)
                if loc is None:
                    break
                hits += 1
                origin = loc + direction * 1e-5
            if hits % 2 == 1:
                buried_n += 1
                buried_a += area
                break
    return {"buried_faces": buried_n, "total_faces": len(faces),
            "buried_face_pct": round(100.0 * buried_n / max(len(faces), 1), 1),
            "buried_area_pct": round(100.0 * buried_a / max(total_a, 1e-12), 1)}


bbox = None
if all_co:
    allc = np.vstack(all_co)
    mn, mx = allc.min(axis=0), allc.max(axis=0)
    bbox = {"min": [round(float(x), 4) for x in mn], "max": [round(float(x), 4) for x in mx],
            "size": [round(float(x), 4) for x in (mx - mn)]}

path = bpy.data.filepath
stats = {
    "file": os.path.basename(path),
    "file_opens": True,
    "blender_version": bpy.app.version_string,
    "file_size_bytes": os.path.getsize(path),
    "mesh_object_count": len(objs),
    "material_count": len(materials),
    "materials": sorted(materials),
    "totals": tot,
    "bbox_world": bbox,
    "reference_bbox": settings["reference_bbox"],
    "buried_surface_estimate": buried_surface(objs, dg) if objs else None,
    "objects": per_obj,
}
with open(camera_setup._long_path(args.out), "w", encoding="utf-8") as fh:
    json.dump(stats, fh, indent=2)
print("[bench] stats written:", args.out)
