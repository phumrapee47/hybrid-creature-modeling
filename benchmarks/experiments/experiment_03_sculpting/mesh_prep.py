"""Experiment 3, Phase 4 - mesh preparation study on the finished sculpt (no GUI needed).

Run:  blender -b dragon_sculpt.blend --python mesh_prep.py
Produces
  dragon_sculpt_quadriflow.blend  QuadriFlow quad retopology (16k target) + shrinkwrap projection
  dragon_sculpt_decimated.blend          Decimate (collapse) to 5 % of the sculpt, triangles
  mesh_prep_log.json                     timings, counts, deviation from the sculpt per region, Multires test
Each variant file keeps the same inserts (eyes, horns, spikes, claws, membranes) and the belly colour
weight transferred from the sculpt.
"""
import json
import os
import shutil
import sys
import tempfile
import time

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402
import material_palette as mp  # noqa: E402

SOURCE = os.path.join(HERE, "dragon_sculpt.blend")
LOG = {"source": os.path.basename(SOURCE), "variants": {}}
REGION_TESTS = {
    "wing_fingers": lambda v: np.abs(v[:, 0]) > 0.55,
    "tail": lambda v: v[:, 1] > 0.45,
    "toes_feet": lambda v: v[:, 2] < 0.06,
    "head": lambda v: v[:, 1] < -0.72,
}


def dg():
    return bpy.context.evaluated_depsgraph_get()


def coords(me):
    a = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def ctx(ob):
    return dict(active_object=ob, object=ob, selected_objects=[ob], selected_editable_objects=[ob])


def duplicate(src, name):
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = ob.data.name = name
    for col in src.users_collection:
        col.objects.link(ob)
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    return ob


def apply_modifiers(ob):
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg()))
    name = ob.data.name
    ob.modifiers.clear()
    ob.data = me
    me.name = name


def deviation(sculpt_v, ob):
    """Distance from (every 5th) sculpt vertex to the nearest point of `ob`: missing or distorted volume."""
    tree = BVHTree.FromObject(ob, dg())
    d = np.array([tree.find_nearest(p)[3] for p in sculpt_v]) * 1000.0
    rest = np.ones(len(sculpt_v), bool)
    out = {}
    for name, test in REGION_TESTS.items():
        m = test(sculpt_v)
        rest &= ~m
        out[name] = {"max_mm": round(float(d[m].max()), 1), "mean_mm": round(float(d[m].mean()), 2)}
    out["torso_legs_rest"] = {"max_mm": round(float(d[rest].max()), 1), "mean_mm": round(float(d[rest].mean()), 2)}
    out["all"] = {"max_mm": round(float(d.max()), 1), "mean_mm": round(float(d.mean()), 2),
                  "p99_mm": round(float(np.percentile(d, 99)), 1)}
    return out


def transfer_belly(sculpt, ob):
    """Copy the sculpt's per-vertex belly weight to `ob` (nearest sculpt face, vertex average)."""
    tree = BVHTree.FromObject(sculpt, dg())
    src_w = np.empty(len(sculpt.data.vertices), np.float32)
    sculpt.data.attributes["belly_w"].data.foreach_get("value", src_w)
    polys = sculpt.data.polygons
    w = np.empty(len(ob.data.vertices), np.float32)
    for i, v in enumerate(ob.data.vertices):
        idx = tree.find_nearest(v.co)[2]
        w[i] = src_w[list(polys[idx].vertices)].mean() if idx is not None else 0.0
    attr = ob.data.attributes.get("belly_w") or ob.data.attributes.new("belly_w", "FLOAT", "POINT")
    attr.data.foreach_set("value", w)
    ob.data.materials.clear()
    ob.data.materials.append(mp.get_blend_material("skin", "belly", "belly_w"))


def smart_uv(ob):
    with bpy.context.temp_override(**ctx(ob)):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        res = bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.003)
        bpy.ops.object.mode_set(mode="OBJECT")
    return str(res)


def multires_test(base, sculpt):
    """Subdivide the retopo with Multires twice and re-project the sculpt onto it (reshape)."""
    rec, t = {}, time.perf_counter()
    test = duplicate(base, "DRG_MultiresTest")
    mod = test.modifiers.new("Multires", "MULTIRES")
    with bpy.context.temp_override(**ctx(test)):
        for _ in range(2):
            bpy.ops.object.multires_subdivide(modifier="Multires", mode="CATMULL_CLARK")
    dense = bpy.data.meshes.new_from_object(test.evaluated_get(dg()))
    tgt = bpy.data.objects.new("DRG_MultiresTarget", dense)
    bpy.context.scene.collection.objects.link(tgt)
    sw = tgt.modifiers.new("Project", "SHRINKWRAP")
    sw.target = sculpt
    sw.wrap_method = "NEAREST_SURFACEPOINT"
    apply_modifiers(tgt)
    with bpy.context.temp_override(active_object=test, object=test, selected_objects=[test, tgt],
                                   selected_editable_objects=[test, tgt]):
        rec["reshape"] = str(bpy.ops.object.multires_reshape(modifier="Multires"))
    rec["levels"] = mod.total_levels
    rec["top_level_faces"] = len(dense.polygons)
    sv = coords(sculpt.data)[::5]
    rec["deviation_top_level"] = deviation(sv, test)["all"]
    rec["seconds"] = round(time.perf_counter() - t, 2)
    bpy.data.objects.remove(tgt)
    bpy.data.objects.remove(test)
    return rec


def build_variant(kind):
    bpy.ops.wm.open_mainfile(filepath=SOURCE)
    bpy.context.preferences.filepaths.save_version = 0
    sculpt = bpy.data.objects["DRG_Sculpt"]
    sv = coords(sculpt.data)[::5]
    rec, t = {}, time.perf_counter()
    if kind == "quadriflow":
        ob = duplicate(sculpt, "DRG_Retopo")
        with bpy.context.temp_override(**ctx(ob)):
            rec["quadriflow"] = str(bpy.ops.object.quadriflow_remesh(target_faces=16000, use_mesh_symmetry=False,
                                                                     use_preserve_sharp=False, use_preserve_boundary=False,
                                                                     seed=0, mode="FACES"))
        rec["deviation_raw"] = deviation(sv, ob)
        sw = ob.modifiers.new("Project", "SHRINKWRAP")
        sw.target = sculpt
        sw.wrap_method = "NEAREST_SURFACEPOINT"
        apply_modifiers(ob)
        out = os.path.join(HERE, "dragon_sculpt_quadriflow.blend")
    else:
        ob = duplicate(sculpt, "DRG_Decimated")
        mod = ob.modifiers.new("Decimate", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = 0.05
        mod.use_collapse_triangulate = True
        apply_modifiers(ob)
        out = os.path.join(HERE, "dragon_sculpt_decimated.blend")
    rec["build_seconds"] = round(time.perf_counter() - t, 2)
    rec["faces"] = len(ob.data.polygons)
    ob.data.calc_loop_triangles()
    rec["triangles"] = len(ob.data.loop_triangles)
    rec["quads"] = sum(1 for p in ob.data.polygons if len(p.vertices) == 4)
    rec["deviation"] = deviation(sv, ob)
    transfer_belly(sculpt, ob)
    rec["smart_uv"] = smart_uv(ob)
    ob.data.shade_smooth()
    if kind == "quadriflow":
        try:
            rec["multires_test"] = multires_test(ob, sculpt)
        except Exception as exc:  # noqa: BLE001
            rec["multires_test"] = {"error": repr(exc)}
    bpy.data.objects.remove(sculpt)
    # Blender cannot write paths over 260 chars on Windows: save to a short temp path, then move
    tmp = os.path.join(tempfile.mkdtemp(prefix="drgprep_"), os.path.basename(out))
    bpy.ops.wm.save_as_mainfile(filepath=tmp, compress=False)
    shutil.move(tmp, camera_setup._long_path(out))
    rec["file"] = os.path.basename(out)
    LOG["variants"][kind] = rec
    print(f"[bench] {kind}: {rec['triangles']} tris, deviation {rec['deviation']['all']}")


t0 = time.perf_counter()
for kind in ("quadriflow", "decimate"):
    build_variant(kind)
LOG["total_seconds"] = round(time.perf_counter() - t0, 2)
with open(camera_setup._long_path(os.path.join(HERE, "mesh_prep_log.json")), "w", encoding="utf-8") as fh:
    json.dump(LOG, fh, indent=1)
print("[bench] mesh prep done")
