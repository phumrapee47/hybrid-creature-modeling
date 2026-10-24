"""Render the eight standard benchmark views from a saved .blend.

Usage:
  blender -b <model.blend> --python shared/render_views.py -- --out <dir> --prefix <name> [--samples N] [--only id ...]
The .blend is never saved by this script, so render-pass overrides do not leak into it.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camera_setup  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--prefix", required=True)
ap.add_argument("--samples", type=int, default=None)
ap.add_argument("--only", nargs="*", default=None)
ap.add_argument("--cage", action="store_true",
                help="disable Subdivision Surface modifiers to inspect the base (cage) mesh")
args = ap.parse_args(argv)

if args.cage:
    import bpy
    col = bpy.data.collections.get(camera_setup.load_settings()["collections"]["model"])
    for ob in col.all_objects:
        for mod in getattr(ob, "modifiers", []):
            if mod.type == "SUBSURF":
                mod.show_render = mod.show_viewport = False

t0 = time.perf_counter()
result = camera_setup.render_views(args.out, args.prefix, args.samples, args.only)
result["total_render_seconds"] = round(time.perf_counter() - t0, 2)
with open(camera_setup._long_path(os.path.join(args.out, f"{args.prefix}_render_log.json")), "w", encoding="utf-8") as fh:
    json.dump(result, fh, indent=2)
print("[bench] render log written")
