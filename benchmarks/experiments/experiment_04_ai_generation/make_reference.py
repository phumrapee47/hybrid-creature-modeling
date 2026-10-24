"""Experiment 4, Phase 1 - concept reference images for image-to-3D generation.

The references are rendered from the Experiment 3 sculpt (shared character concept, palette
materials) so the AI generator receives the same anatomy, proportions, wing structure and colours.
Square 1024 px, transparent background, no floor, even lighting.

Run:  blender -b ../experiment_03_sculpting/dragon_sculpt.blend --python make_reference.py
"""
import os
import shutil
import sys
import tempfile

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "shared")))
import camera_setup  # noqa: E402

OUT = os.path.join(HERE, "reference")
VIEWS = {  # name: (type, location, target, lens or ortho_scale)
    "ref_three_quarter": ("PERSP", (3.9, -4.6, 2.3), (0.0, 0.25, 0.80), 55),
    "ref_front": ("ORTHO", (0.0, -10.0, 0.80), (0.0, 0.0, 0.80), 2.95),
    "ref_left": ("ORTHO", (10.0, 0.28, 0.80), (0.0, 0.28, 0.80), 3.15),
    "ref_back": ("ORTHO", (0.0, 10.0, 0.80), (0.0, 0.0, 0.80), 2.95),
}

scene = bpy.context.scene
camera_setup.build_rig(scene)
camera_setup.configure_render(scene, samples=96)
scene.render.resolution_x = scene.render.resolution_y = 1024
scene.render.film_transparent = True
scene.render.image_settings.color_mode = "RGBA"
bpy.data.objects[camera_setup.RIG_PREFIX + "Floor"].hide_render = True
os.makedirs(camera_setup._long_path(OUT), exist_ok=True)
tmp = tempfile.mkdtemp(prefix="drgref_")
for name, (kind, loc, target, val) in VIEWS.items():
    cd = bpy.data.cameras.new(name)
    if kind == "ORTHO":
        cd.type = "ORTHO"
        cd.ortho_scale = val
    else:
        cd.lens = val
    cam = bpy.data.objects.new(name, cd)
    scene.collection.objects.link(cam)
    cam.location = loc
    camera_setup.look_at(cam, Vector(target))
    scene.camera = cam
    scene.render.filepath = os.path.join(tmp, name + ".png")
    bpy.ops.render.render(write_still=True)
    shutil.move(scene.render.filepath, camera_setup._long_path(os.path.join(OUT, name + ".png")))
    print("[bench] reference", name)
shutil.rmtree(tmp, ignore_errors=True)
