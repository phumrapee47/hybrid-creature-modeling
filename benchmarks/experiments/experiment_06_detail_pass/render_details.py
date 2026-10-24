"""Render the eight Experiment 6 detail close-ups from a saved .blend (any experiment, for before/after).

Usage:
  blender -b <model.blend> --python render_details.py -- --out <dir> --prefix <name> [--samples N] [--only id ...]
Lighting is the standard benchmark rig. Exception: d6_wing_backlit adds one area light behind the wing
(only for that view) so membrane translucency can be judged. Camera targets that depend on the model
(eye, horn, mouth, forefoot) are measured from the model's own inserts, so a smaller Exp 5 head is
framed the same way as the Exp 6 head. The .blend is never saved.
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

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared")))
import camera_setup  # noqa: E402

V = Vector
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--prefix", required=True)
ap.add_argument("--samples", type=int, default=None)
ap.add_argument("--only", nargs="*", default=None)
args = ap.parse_args(argv)


def verts_world(name, test):
    ob = bpy.data.objects.get(name)
    if ob is None:
        return []
    mw = ob.matrix_world
    return [mw @ v.co for v in ob.data.vertices if test(mw @ v.co)]


def center(pts, fallback):
    if not pts:
        return V(fallback)
    lo = V([min(p[i] for p in pts) for i in range(3)])
    hi = V([max(p[i] for p in pts) for i in range(3)])
    return (lo + hi) / 2


def targets():
    eye = center(verts_world("DRG_Eyes", lambda p: p.x > 0), (0.08, -0.90, 1.24))
    horn = center(verts_world("DRG_Horns", lambda p: p.x > 0 and p.z > 1.25), (0.09, -0.62, 1.34))
    teeth = verts_world("DRG_Teeth", lambda p: p.x > 0)
    mouth = center(teeth, (0.0, -1.0, 1.14)) if teeth else V((0.03, -1.0, 1.15))
    mouth.x = 0.02
    foot = center(verts_world("DRG_Claws", lambda p: p.x > 0 and p.y < 0 and p.z < 0.12), (0.25, -0.40, 0.04))
    return {"eye": eye, "horn": horn, "mouth": mouth, "foot": foot}


# id: (target key or fixed point, camera offset from target, lens mm, purpose)
VIEWS = [
    ("d1_eye", "eye", (0.30, -0.20, 0.08), 100, "Eye: iris, slit pupil, cornea gloss, lids, socket"),
    ("d2_mouth", "mouth", (0.38, -0.52, -0.06), 60, "Open mouth: teeth, gums, tongue, lips"),
    ("d3_flank_scales", (0.21, -0.05, 0.70), (0.48, -0.22, 0.12), 100, "Flank/ribcage scales and countershading"),
    ("d4_belly", (0.0, 0.05, 0.50), (0.55, 0.10, -0.36), 60, "Ventral scutes and chest from below"),
    ("d5_forefoot", "foot", (0.30, -0.32, 0.16), 85, "Forefoot: toe scutes, claws, dewclaw, ground contact"),
    ("d6_wing_backlit", (0.95, 0.12, 1.15), (0.90, -1.50, -0.55), 50, "Wing membrane against a back light: veins, translucency"),
    ("d7_tail", (0.20, 1.20, 0.33), (0.55, -0.25, 0.25), 85, "Tail whorl scales and dorsal spikes"),
    ("d8_horn", "horn", (0.30, 0.05, 0.22), 85, "Horn growth rings, base-to-tip gradient, cheek spikes"),
]

scene = bpy.context.scene
camera_setup.build_rig(scene)
device = camera_setup.configure_render(scene, samples=args.samples)
tg = targets()
cam_data = bpy.data.cameras.new("DET_Cam")
cam = bpy.data.objects.new("DET_Cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
back = bpy.data.objects.new("DET_BackLight", bpy.data.lights.new("DET_BackLight", "AREA"))
back.data.energy, back.data.size = 900.0, 2.0
back.location = V((1.0, 2.6, 2.0))
camera_setup.look_at(back, (0.95, 0.12, 1.15))
scene.collection.objects.link(back)
os.makedirs(camera_setup._long_path(args.out), exist_ok=True)
tmp_dir = tempfile.mkdtemp(prefix="drg6det_")
log = []
for vid, tkey, off, lens, purpose in VIEWS:
    if args.only and vid not in args.only:
        continue
    target = tg[tkey] if isinstance(tkey, str) else V(tkey)
    cam.location = target + V(off)
    camera_setup.look_at(cam, target)
    cam_data.lens = lens
    cam_data.clip_start = 0.01
    back.hide_render = vid != "d6_wing_backlit"
    tmp = os.path.join(tmp_dir, f"{args.prefix}_{vid}.png")
    scene.render.filepath = tmp
    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    dst = os.path.join(args.out, os.path.basename(tmp))
    shutil.move(tmp, camera_setup._long_path(dst))
    log.append({"view": vid, "purpose": purpose, "target": [round(v, 4) for v in target], "lens": lens,
                "render_seconds": round(time.perf_counter() - t0, 2), "file": os.path.basename(dst)})
    print(f"[bench] rendered {vid}")
shutil.rmtree(tmp_dir, ignore_errors=True)
with open(camera_setup._long_path(os.path.join(args.out, f"{args.prefix}_details_log.json")), "w", encoding="utf-8") as fh:
    json.dump({"device": device, "samples": scene.cycles.samples, "views": log}, fh, indent=1)
