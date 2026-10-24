"""Experiment 4, Phases 3-4 - import the AI-generated GLB into Blender, inspect it, repair it.

Run:  blender -b --factory-startup --python import_and_repair.py
Outputs
  dragon_ai_original.blend   the generated asset, UNMODIFIED except for a uniform scale + translation
                             (no rotation needed) that fits it to the shared benchmark frame
  dragon_ai_generated.blend  the repaired asset (deliverable)
  ai_inspection.json         defect measurements before and after repair, and the repair log
"""
import json
import math
import os
import shutil
import sys
import tempfile

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402

SOURCE_GLB = os.path.join(HERE, "original_asset", "single_view", "trellis_output_2_sample.glb")
TARGET_Y_EXTENT = 2.885   # snout -> tail tip, same as Experiments 2/3 (shared spec ~2.9 m)
TARGET_Y_MIN = -1.164     # snout position used by the other experiments
WELD_DIST = 0.0005        # metres, after scaling (weld vertices split along UV seams)
TINY_SHELL_AREA = 0.0005  # m^2: floating fragments smaller than this (~2.2 x 2.2 cm) are removed
HOLE_MAX_SIDES = 16       # fill only small holes
LOG = {"source": os.path.relpath(SOURCE_GLB, HERE)}


def save_blend(path):
    tmp = os.path.join(tempfile.mkdtemp(prefix="drgai_"), os.path.basename(path))
    bpy.ops.wm.save_as_mainfile(filepath=tmp, compress=False)
    shutil.move(tmp, camera_setup._long_path(path))


def shells(bm):
    bm.verts.index_update()
    bm.faces.ensure_lookup_table()
    seen, out = set(), []
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack, members = [f0], []
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            members.append(f)
            for e in f.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        stack.append(g)
        out.append(members)
    return out


def inspect(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.index_update()
    sh = shells(bm)
    areas = sorted((sum(f.calc_area() for f in s), len(s)) for s in sh)
    boundary = [e for e in bm.edges if e.is_boundary]
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    # holes = boundary loops
    loops, used = [], set()
    for e in boundary:
        if e.index in used:
            continue
        loop, stack = 0, [e]
        used.add(e.index)
        while stack:
            cur = stack.pop()
            loop += 1
            for v in cur.verts:
                for e2 in v.link_edges:
                    if e2.is_boundary and e2.index not in used:
                        used.add(e2.index)
                        stack.append(e2)
        loops.append(loop)
    # normal consistency: how many faces flip when normals are recalculated
    before = [f.normal.copy() for f in bm.faces]
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    flipped = sum(1 for f, n in zip(bm.faces, before) if f.normal.dot(n) < 0)
    degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-10)
    total_area = sum(a for a, _ in areas)
    bm.free()
    me.calc_loop_triangles()
    return {"vertices": len(me.vertices), "triangles": len(me.loop_triangles), "faces": len(me.polygons),
            "shells": len(sh), "largest_shell_area_pct": round(100 * areas[-1][0] / total_area, 2),
            "shells_below_tiny_area": sum(1 for a, _ in areas if a < TINY_SHELL_AREA),
            "tiny_shell_area_pct": round(100 * sum(a for a, _ in areas if a < TINY_SHELL_AREA) / total_area, 3),
            "boundary_edges": len(boundary), "boundary_loops": len(loops),
            "holes_le_16_edges": sum(1 for n in loops if n <= HOLE_MAX_SIDES), "largest_boundary_loop": max(loops) if loops else 0,
            "non_manifold_edges": nonman, "faces_flipped_by_recalc": flipped, "degenerate_faces": degenerate,
            "uv_layers": [u.name for u in me.uv_layers], "surface_area_m2": round(total_area, 4)}


def material_info(me):
    out = []
    for m in me.materials:
        imgs = [n.image for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image] if m and m.node_tree else []
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.node_tree else None
        linked = [i.name for i in bsdf.inputs if i.is_linked] if bsdf else []
        out.append({"material": m.name, "images": [{"name": i.name, "size": list(i.size)} for i in imgs],
                    "bsdf_linked_inputs": linked,
                    "metallic": round(bsdf.inputs["Metallic"].default_value, 3) if bsdf else None,
                    "roughness": round(bsdf.inputs["Roughness"].default_value, 3) if bsdf else None})
    return out


# ------------------------------------------------------------------ Phase 3: import + normalise (no shape change)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.preferences.filepaths.save_version = 0
scene = bpy.context.scene
tmp_glb = os.path.join(tempfile.mkdtemp(prefix="drgglb_"), "asset.glb")   # Blender cannot open the >260-char path
shutil.copyfile(camera_setup._long_path(SOURCE_GLB), tmp_glb)
bpy.ops.import_scene.gltf(filepath=tmp_glb)
meshes = [o for o in scene.objects if o.type == "MESH"]
LOG["imported_objects"] = [(o.name, o.type) for o in scene.objects]
ob = meshes[0]
ob.data.transform(ob.matrix_world)  # bake glTF node transforms (identity here)
for o in list(scene.objects):
    if o is not ob:
        bpy.data.objects.remove(o)
ob.matrix_world = Matrix.Identity(4)
co = np.array([v.co[:] for v in ob.data.vertices])
mn, mx = co.min(0), co.max(0)
s = TARGET_Y_EXTENT / (mx[1] - mn[1])
offset = Vector((-(mn[0] + mx[0]) / 2 * s, TARGET_Y_MIN - mn[1] * s, -mn[2] * s))
ob.data.transform(Matrix.Translation(offset) @ Matrix.Scale(s, 4))
LOG["normalisation"] = {"raw_bbox_min": mn.round(4).tolist(), "raw_bbox_max": mx.round(4).tolist(),
                        "uniform_scale": round(s, 5), "translation": [round(x, 4) for x in offset], "rotation": "none (already faces -Y)"}
dragon = camera_setup.ensure_collection("Dragon", scene)
root = bpy.data.objects.new("DRG_Root", None)
dragon.objects.link(root)
for col in list(ob.users_collection):
    col.objects.unlink(ob)
dragon.objects.link(ob)
ob.parent = root
ob.name = ob.data.name = "DRG_AI_Original"
LOG["original"] = inspect(ob.data)
LOG["original_materials"] = material_info(ob.data)
LOG["original_smooth_faces_pct"] = round(100 * sum(p.use_smooth for p in ob.data.polygons) / len(ob.data.polygons), 1)
camera_setup.build_rig(scene)
bpy.ops.file.pack_all()
save_blend(os.path.join(HERE, "dragon_ai_original.blend"))

# ------------------------------------------------------------------ Phase 4: repair (keep shape, UVs and texture)
ob.name = ob.data.name = "DRG_AI_Repaired"
bm = bmesh.new()
bm.from_mesh(ob.data)
rep = {}
n0 = len(bm.verts)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=WELD_DIST)
rep["weld_removed_vertices"] = n0 - len(bm.verts)
bm.faces.index_update()
small = [s_ for s_ in shells(bm) if sum(f.calc_area() for f in s_) < TINY_SHELL_AREA]
rep["tiny_shells_removed"] = len(small)
rep["tiny_shell_faces_removed"] = sum(len(s_) for s_ in small)
bmesh.ops.delete(bm, geom=list({f for s_ in small for f in s_}), context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bnd = [e for e in bm.edges if e.is_boundary]
filled = bmesh.ops.holes_fill(bm, edges=bnd, sides=HOLE_MAX_SIDES)
rep["holes_filled_faces"] = len(filled["faces"])
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
bm.to_mesh(ob.data)
bm.free()
ob.data.shade_smooth()
ob.data.set_sharp_from_angle(angle=math.radians(50))  # smooth by angle: keeps claw/spike edges crisp
rep["shading"] = "smooth + sharp edges above 50 deg"
# material: the GLB declares a fully metallic surface (metallic 1, roughness 1, no MR texture), which
# renders as dark chrome. Keep the AI albedo texture, make it a non-metal with the palette skin roughness.
mat_orig = ob.data.materials[0]
mat = mat_orig.copy()
mat.name = "AI_Material_repaired"
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
bsdf.inputs["Metallic"].default_value = 0.0
bsdf.inputs["Roughness"].default_value = 0.55
ob.data.materials[0] = mat
rep["material"] = "kept AI albedo texture; metallic 1.0 -> 0.0, roughness 1.0 -> 0.55"

# texture colour alignment to the shared palette (keeps the AI's painted variation, moves region medians):
#  * horns/spikes: generator drifted bronze -> pink/red; pink/red texels get the palette bronze hue/saturation
#  * skin (green) and belly (yellow-olive): median hue/saturation/value matched to the palette entries
def rgb_to_hsv(rgb):
    mxc, mnc = rgb.max(1), rgb.min(1)
    d = np.maximum(mxc - mnc, 1e-6)
    r_, g_, b_ = rgb.T
    h_ = np.where(mxc == r_, ((g_ - b_) / d) % 6, np.where(mxc == g_, (b_ - r_) / d + 2, (r_ - g_) / d + 4)) / 6.0
    return np.stack([h_ % 1.0, np.where(mxc > 0, (mxc - mnc) / np.maximum(mxc, 1e-6), 0), mxc], 1)


def hsv_to_rgb(hsv):
    h_, s_, v_ = hsv.T
    i = np.floor(h_ * 6).astype(int) % 6
    f = h_ * 6 - np.floor(h_ * 6)
    p, q, t = v_ * (1 - s_), v_ * (1 - f * s_), v_ * (1 - (1 - f) * s_)
    table = [(v_, t, p), (q, v_, p), (p, v_, t), (p, q, v_), (t, p, v_), (v_, p, q)]
    out = np.zeros((len(h_), 3), np.float32)
    for k, (a, b, c) in enumerate(table):
        sel = i == k
        out[sel] = np.stack([a[sel], b[sel], c[sel]], 1)
    return out


def palette_hsv(hex_str):
    return rgb_to_hsv(np.array([[int(hex_str[i:i + 2], 16) / 255 for i in (1, 3, 5)]], np.float32))[0]


tex = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
src_img = tex.image
w, h = src_img.size
px = np.empty(w * h * 4, np.float32)
src_img.pixels.foreach_get(px)
px = px.reshape(-1, 4)
hsv = rgb_to_hsv(px[:, :3])
H, S, Vv = hsv[:, 0] * 360, hsv[:, 1], hsv[:, 2]
regions = {
    "horn_bronze": (((H >= 340) | (H <= 22)) & (S > 0.30) & (Vv > 0.15), "#8C6A3C"),
    "skin_green": ((H > 75) & (H < 165) & (S > 0.20) & (Vv > 0.05), "#2E4D2C"),
    "belly_olive": ((H > 40) & (H <= 75) & (S > 0.20) & (Vv > 0.05), "#7F8A52"),
}
rep["texture_alignment"] = {}
for name, (mask, hex_str) in regions.items():
    target = palette_hsv(hex_str)
    med = np.median(hsv[mask], 0)
    region = hsv[mask].copy()
    if name == "horn_bronze":  # hue jump across the red/pink wrap: set hue and saturation directly
        region[:, 0] = target[0]
        region[:, 1] = target[1]
        region[:, 2] *= target[2] / med[2]
    else:
        region[:, 0] = (region[:, 0] + (target[0] - med[0])) % 1.0
        region[:, 1] = np.clip(region[:, 1] * target[1] / med[1], 0, 1)
        # value gain capped: an uncapped x1.53 on the belly clipped highlights to a flat neon yellow
        region[:, 2] = np.clip(region[:, 2] * min(target[2] / med[2], 1.15), 0, 1)
    hsv[mask] = region
    rep["texture_alignment"][name] = {"texels_pct": round(100 * float(mask.mean()), 2), "palette": hex_str,
                                      "median_hsv_before": np.round(med, 3).tolist(), "palette_hsv": np.round(target, 3).tolist()}
px[:, :3] = hsv_to_rgb(hsv)
fixed = bpy.data.images.new("AI_Texture_repaired", w, h, alpha=True)
fixed.colorspace_settings.name = src_img.colorspace_settings.name
fixed.pixels.foreach_set(px.ravel())
fixed.pack()
tex.image = fixed
LOG["repair"] = rep
LOG["repaired"] = inspect(ob.data)
save_blend(os.path.join(HERE, "dragon_ai_generated.blend"))
with open(camera_setup._long_path(os.path.join(HERE, "ai_inspection.json")), "w", encoding="utf-8") as fh:
    json.dump(LOG, fh, indent=2, default=str)
print("[bench] original", json.dumps(LOG["original"]))
print("[bench] repair", json.dumps(rep))
print("[bench] repaired", json.dumps(LOG["repaired"]))
