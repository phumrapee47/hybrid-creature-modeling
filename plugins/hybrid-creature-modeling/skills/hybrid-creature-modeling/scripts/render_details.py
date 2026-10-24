"""Render detail close-ups from a saved .blend (any creature, any version, for before/after).

Usage:
  blender -b <model.blend> --python render_details.py -- --out <dir> --prefix <name> [--samples N] [--only id ...]
Views come from the settings file's "detail_views" (see camera_setup.SETTINGS_PATH / CREATURE_SETTINGS);
the dragon set below is the default. Each view:
  {"id", "target": [x, y, z] | {"object": name, "xmin"/"xmax"/"ymin"/"ymax"/"zmin"/"zmax": bounds, "x": override},
   "offset": [dx, dy, dz] camera position relative to the target, "lens": mm, "purpose": text,
   "backlight": [x, y, z] (optional extra area light aimed at the target, this view only)}
Targets measured from the model's own inserts keep before/after shots framed on the same part.
Lighting is otherwise the standard rig. The .blend is never saved.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camera_setup  # noqa: E402

V = Vector
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--prefix", required=True)
ap.add_argument("--samples", type=int, default=None)
ap.add_argument("--only", nargs="*", default=None)
args = ap.parse_args(argv)

DRAGON_VIEWS = [
    {"id": "d1_eye", "target": {"object": "DRG_Eyes", "xmin": 0}, "offset": [0.30, -0.20, 0.08], "lens": 100,
     "purpose": "Eye: iris, slit pupil, cornea gloss, lids, socket"},
    {"id": "d2_mouth", "target": {"object": "DRG_Teeth", "xmin": 0, "x": 0.02}, "offset": [0.38, -0.52, -0.06], "lens": 60,
     "purpose": "Open mouth: teeth, gums, tongue, lips"},
    {"id": "d3_flank_scales", "target": [0.21, -0.05, 0.70], "offset": [0.48, -0.22, 0.12], "lens": 100,
     "purpose": "Flank/ribcage scales and countershading"},
    {"id": "d4_belly", "target": [0.0, 0.05, 0.50], "offset": [0.55, 0.10, -0.36], "lens": 60,
     "purpose": "Ventral scutes and chest from below"},
    {"id": "d5_forefoot", "target": {"object": "DRG_Claws", "xmin": 0, "ymax": 0, "zmax": 0.12}, "offset": [0.30, -0.32, 0.16],
     "lens": 85, "purpose": "Forefoot: toe scutes, claws, dewclaw, ground contact"},
    {"id": "d6_wing_backlit", "target": [0.95, 0.12, 1.15], "offset": [0.90, -1.50, -0.55], "lens": 50,
     "backlight": [1.0, 2.6, 2.0], "purpose": "Wing membrane against a back light: veins, translucency"},
    {"id": "d7_tail", "target": [0.20, 1.20, 0.33], "offset": [0.55, -0.25, 0.25], "lens": 85,
     "purpose": "Tail whorl scales and dorsal spikes"},
    {"id": "d8_horn", "target": {"object": "DRG_Horns", "xmin": 0, "zmin": 1.25}, "offset": [0.30, 0.05, 0.22], "lens": 85,
     "purpose": "Horn growth rings, base-to-tip gradient, cheek spikes"},
]


def resolve(target):
    if isinstance(target, (list, tuple)):
        return V(target), "point"
    ob = bpy.data.objects.get(target["object"])
    if ob is None:
        return None, f"object {target['object']} missing"
    mw = ob.matrix_world
    lim = {k: target[k] for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax") if k in target}

    def ok(p):
        return all((p[i] >= lim[a + "min"] if a + "min" in lim else True) and (p[i] <= lim[a + "max"] if a + "max" in lim else True)
                   for i, a in enumerate("xyz"))
    pts = [p for p in (mw @ v.co for v in ob.data.vertices) if ok(p)]
    if not pts:
        return None, f"no vertices of {target['object']} inside the bounds"
    c = (V([min(p[i] for p in pts) for i in range(3)]) + V([max(p[i] for p in pts) for i in range(3)])) / 2
    if "x" in target:
        c.x = target["x"]
    return c, "bbox centre of " + target["object"]


settings = camera_setup.load_settings()
views = settings.get("detail_views", DRAGON_VIEWS)
scene = bpy.context.scene
camera_setup.build_rig(scene)
device = camera_setup.configure_render(scene, samples=args.samples)
cam_data = bpy.data.cameras.new("DET_Cam")
cam = bpy.data.objects.new("DET_Cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
back = bpy.data.objects.new("DET_BackLight", bpy.data.lights.new("DET_BackLight", "AREA"))
back.data.energy, back.data.size = 900.0, 2.0
scene.collection.objects.link(back)
os.makedirs(camera_setup._long_path(args.out), exist_ok=True)
tmp_dir = tempfile.mkdtemp(prefix="crtdet_")
log = []
for v in views:
    if args.only and v["id"] not in args.only:
        continue
    target, how = resolve(v["target"])
    if target is None:
        log.append({"view": v["id"], "skipped": how})
        print(f"[bench] skipped {v['id']}: {how}")
        continue
    cam.location = target + V(v["offset"])
    camera_setup.look_at(cam, target)
    cam_data.lens = v["lens"]
    cam_data.clip_start = 0.01
    back.hide_render = "backlight" not in v
    if "backlight" in v:
        back.location = V(v["backlight"])
        camera_setup.look_at(back, target)
    tmp = os.path.join(tmp_dir, f"{args.prefix}_{v['id']}.png")
    scene.render.filepath = tmp
    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    dst = os.path.join(args.out, os.path.basename(tmp))
    shutil.move(tmp, camera_setup._long_path(dst))
    log.append({"view": v["id"], "purpose": v.get("purpose", ""), "target": [round(x, 4) for x in target], "target_from": how,
                "lens": v["lens"], "render_seconds": round(time.perf_counter() - t0, 2), "file": os.path.basename(dst)})
    print(f"[bench] rendered {v['id']}")
shutil.rmtree(tmp_dir, ignore_errors=True)
with open(camera_setup._long_path(os.path.join(args.out, f"{args.prefix}_details_log.json")), "w", encoding="utf-8") as fh:
    json.dump({"device": device, "samples": scene.cycles.samples, "views": log}, fh, indent=1)
