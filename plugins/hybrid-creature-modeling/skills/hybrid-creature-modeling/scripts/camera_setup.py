"""Standardized evaluation environment for the dragon benchmark.

build_rig()     -> cameras, lights, world, floor and reference box (collection Benchmark_Rig)
render_views()  -> renders the eight standard views defined in benchmark_settings.json

Every experiment calls build_rig() before saving its .blend, and the renders are
produced by shared/render_views.py from the saved file, so all experiments share
identical cameras, lights, background and render settings.
"""
import json
import os
import shutil
import tempfile
import time

import bpy
import bmesh
from mathutils import Vector

import material_palette as mp

SHARED_DIR = os.path.dirname(os.path.abspath(__file__))
# CREATURE_SETTINGS overrides the rig/reference file (per-creature bbox, landmarks, cameras, detail views)
SETTINGS_PATH = os.environ.get("CREATURE_SETTINGS") or os.path.join(SHARED_DIR, "benchmark_settings.json")
RIG_PREFIX = "RIG_"


def load_settings():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_collection(name, scene=None):
    scene = scene or bpy.context.scene
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    if col.name not in scene.collection.children:
        scene.collection.children.link(col)
    return col


def _long_path(path):
    """Prefix absolute Windows paths with \\\\?\\ so file ops work past 260 chars."""
    path = os.path.abspath(path)
    if os.name == "nt" and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + path
    return path


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _select_device(scene, order):
    cprefs = bpy.context.preferences.addons["cycles"].preferences
    for dev_type in order:
        if dev_type == "CPU":
            break
        try:
            cprefs.compute_device_type = dev_type
        except TypeError:
            continue
        try:
            cprefs.refresh_devices()
        except AttributeError:
            cprefs.get_devices()
        devs = [d for d in cprefs.devices if d.type == dev_type]
        if devs:
            for d in cprefs.devices:
                d.use = d.type == dev_type
            scene.cycles.device = "GPU"
            return f"{dev_type}: " + ", ".join(d.name for d in devs)
    scene.cycles.device = "CPU"
    return "CPU"


def configure_render(scene=None, settings=None, samples=None):
    scene = scene or bpy.context.scene
    settings = settings or load_settings()
    r = settings["render"]
    scene.unit_settings.system = settings["units"]["system"]
    scene.unit_settings.scale_length = settings["units"]["scale_length"]
    scene.render.engine = "CYCLES"
    device = _select_device(scene, r["device_preference"])
    scene.cycles.samples = samples or r["samples"]
    scene.cycles.use_denoising = r["denoise"]
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.max_bounces = r["max_bounces"]
    scene.render.resolution_x, scene.render.resolution_y = r["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.use_motion_blur = False
    scene.view_settings.view_transform = r["view_transform"]
    scene.view_settings.look = r["look"]
    scene.view_settings.exposure = r["exposure"]
    scene.view_settings.gamma = 1.0
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    return device


def _rig_objects(col):
    return {o.name: o for o in col.objects}


def build_rig(scene=None):
    """(Re)create the benchmark rig. Only touches objects in Benchmark_Rig."""
    scene = scene or bpy.context.scene
    s = load_settings()
    col = ensure_collection(s["collections"]["rig"], scene)
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # World: flat neutral grey, low strength (ambient only)
    world = bpy.data.worlds.get("Benchmark_World") or bpy.data.worlds.new("Benchmark_World")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    wc = tuple(mp.srgb_to_linear(c) for c in s["world"]["color_srgb"])
    bg.inputs["Color"].default_value = (*wc, 1.0)
    bg.inputs["Strength"].default_value = s["world"]["strength"]
    world.color = wc
    scene.world = world

    # Floor
    fs = s["floor"]["size"] / 2
    me = bpy.data.meshes.new(RIG_PREFIX + "Floor")
    me.from_pydata([(-fs, -fs, 0), (fs, -fs, 0), (fs, fs, 0), (-fs, fs, 0)], [], [(0, 1, 2, 3)])
    floor = bpy.data.objects.new(RIG_PREFIX + "Floor", me)
    floor.data.materials.append(mp.make_flat_material(RIG_PREFIX + "FloorMat", s["floor"]["color_srgb"], s["floor"]["roughness"]))
    col.objects.link(floor)

    # Reference bounding box (viewport only)
    mn, mx = Vector(s["reference_bbox"]["min"]), Vector(s["reference_bbox"]["max"])
    bm = bmesh.new()
    corners = [bm.verts.new((x, y, z)) for x in (mn.x, mx.x) for y in (mn.y, mx.y) for z in (mn.z, mx.z)]
    for a, b in [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]:
        bm.edges.new((corners[a], corners[b]))
    me = bpy.data.meshes.new(RIG_PREFIX + "ReferenceBox")
    bm.to_mesh(me)
    bm.free()
    box = bpy.data.objects.new(RIG_PREFIX + "ReferenceBox", me)
    box.display_type = "WIRE"
    box.hide_render = True
    box.hide_select = True
    col.objects.link(box)

    # Lights
    for L in s["lights"]:
        ld = bpy.data.lights.new(RIG_PREFIX + L["name"], L["type"])
        ld.energy = L["energy"]
        ld.color = L["color"]
        if L["type"] == "AREA":
            ld.shape = "SQUARE"
            ld.size = L["size"]
        lo = bpy.data.objects.new(RIG_PREFIX + L["name"], ld)
        lo.location = L["location"]
        look_at(lo, L["target"])
        col.objects.link(lo)

    # Cameras
    cams = {}
    for name, c in s["cameras"].items():
        cd = bpy.data.cameras.new(RIG_PREFIX + "Cam_" + name)
        cd.clip_start, cd.clip_end = 0.05, 100.0
        if c["type"] == "ORTHO":
            cd.type = "ORTHO"
            cd.ortho_scale = c["ortho_scale"]
        else:
            cd.lens = c["lens"]
        cd.sensor_width = 36.0
        cd.dof.use_dof = False
        co = bpy.data.objects.new(RIG_PREFIX + "Cam_" + name, cd)
        co.location = c["location"]
        look_at(co, c["target"])
        col.objects.link(co)
        cams[name] = co
    scene.camera = cams["three_quarter"]
    configure_render(scene, s)
    return cams


# ---------------------------------------------------------------- render passes

def _dragon_meshes(settings):
    col = bpy.data.collections.get(settings["collections"]["model"])
    if col is None:
        raise RuntimeError("Dragon collection missing")
    return [o for o in col.all_objects if o.type == "MESH" and not o.hide_render]


def _pass_wireframe_enter(settings, scene):
    w = settings["wireframe"]
    base = mp.make_flat_material(RIG_PREFIX + "WireBase", w["base_color_srgb"], 0.6)
    wire = mp.make_flat_material(RIG_PREFIX + "WireLine", w["wire_color_srgb"], 0.6)
    saved, copies = [], []
    for obj in _dragon_meshes(settings):
        slots = [(sl.link, sl.material) for sl in obj.material_slots]
        saved.append((obj, slots))
        if not obj.material_slots:
            obj.data.materials.append(None)
        for sl in obj.material_slots:
            sl.link = "OBJECT"
            sl.material = base
        cp = obj.copy()
        cp.name = obj.name + "__wire"
        for col in obj.users_collection:
            col.objects.link(cp)
        for sl in cp.material_slots:
            sl.material = wire
        mod = cp.modifiers.new("BenchWire", "WIREFRAME")
        mod.thickness = w["thickness"]
        mod.use_replace = True
        mod.use_even_offset = True
        mod.use_relative_offset = False
        mod.offset = 0.0
        copies.append(cp)
    return saved, copies


def _pass_wireframe_exit(state):
    saved, copies = state
    for cp in copies:
        bpy.data.objects.remove(cp, do_unlink=True)
    for obj, slots in saved:
        for sl, (link, mat) in zip(obj.material_slots, slots):
            sl.material = None
            sl.link = link
            if link == "OBJECT":
                sl.material = mat


def render_views(out_dir, prefix, samples=None, only=None):
    settings = load_settings()
    scene = bpy.context.scene
    # Always rebuild the rig from the current settings so every experiment is
    # rendered with identical cameras/lights even if its .blend holds an older rig.
    build_rig(scene)
    device = configure_render(scene, settings, samples)
    os.makedirs(_long_path(out_dir), exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="drgbench_")
    floor = bpy.data.objects[RIG_PREFIX + "Floor"]
    clay = mp.make_flat_material(RIG_PREFIX + "Clay", settings["clay"]["color_srgb"], settings["clay"]["roughness"])
    vl = scene.view_layers[0]
    log, fallbacks = [], []
    # Cycles views first, Workbench (silhouette) last: switching engines back and
    # forth exhausted the 4 GB laptop GPU during the first test run.
    ordered = sorted(settings["views"], key=lambda v: v["shading"] == "silhouette")
    for view in ordered:
        if only and view["id"] not in only:
            continue
        scene.camera = bpy.data.objects[RIG_PREFIX + "Cam_" + view["camera"]]
        shading = view["shading"]
        state = None
        scene.render.engine = "CYCLES"
        vl.material_override = None
        floor.hide_render = False
        if shading == "clay":
            vl.material_override = clay
        elif shading == "wireframe":
            state = _pass_wireframe_enter(settings, scene)
        elif shading == "silhouette":
            sil = settings["silhouette"]
            scene.render.engine = sil["engine"]
            sh = scene.display.shading
            sh.light = "FLAT"
            sh.color_type = "SINGLE"
            sh.single_color = sil["model_color"]
            sh.show_shadows = False
            sh.show_cavity = False
            sh.show_object_outline = False
            sh.show_specular_highlight = False
            scene.display.render_aa = "16"
            state = tuple(scene.world.color)
            scene.world.color = sil["background"]
            floor.hide_render = sil["hide_floor"]
        path = os.path.join(out_dir, f"{prefix}_{view['id']}.png")
        # Blender's image writer is not long-path aware on Windows (>260 chars),
        # so render into a short temp dir and move the file afterwards.
        tmp_path = os.path.join(tmp_dir, os.path.basename(path))
        scene.render.filepath = tmp_path
        t0 = time.perf_counter()
        try:
            bpy.ops.render.render(write_still=True)
        except RuntimeError as exc:
            if scene.render.engine != "CYCLES" or scene.cycles.device != "GPU":
                raise
            fallbacks.append({"view": view["id"], "error": str(exc).strip()})
            scene.cycles.device = "CPU"
            device = "CPU (GPU fallback)"
            bpy.ops.render.render(write_still=True)
        dt = time.perf_counter() - t0
        shutil.move(tmp_path, _long_path(path))
        if shading == "wireframe":
            _pass_wireframe_exit(state)
        elif shading == "silhouette":
            scene.world.color = state
        vl.material_override = None
        floor.hide_render = False
        log.append({"view": view["id"], "camera": view["camera"], "shading": shading,
                    "file": os.path.basename(path), "exists": os.path.isfile(_long_path(path)),
                    "render_seconds": round(dt, 2)})
        print(f"[bench] rendered {view['id']} in {dt:.1f}s")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    log.sort(key=lambda r: r["view"])
    return {"device": device, "engine_main": "CYCLES", "samples": scene.cycles.samples,
            "gpu_fallbacks": fallbacks, "views": log}
