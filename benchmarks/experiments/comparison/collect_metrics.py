"""Collect the measured metrics of every final model into comparison/metrics.json.

Reads only files produced by the experiments (fresh-process inspection JSONs, build/render logs).
Run:  python collect_metrics.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return json.load(fh)


MODELS = [
    # id, label, blend, stats json, render log, build seconds source
    ("exp1", "Exp 1 basic procedural", "experiment_01_basic_procedural/dragon_basic.blend",
     "experiment_01_basic_procedural/geometry_stats.json", "experiment_01_basic_procedural/renders/basic_render_log.json"),
    ("exp2", "Exp 2 advanced procedural (evaluated, subsurf L1)", "experiment_02_advanced_procedural/dragon_advanced.blend",
     "experiment_02_advanced_procedural/geometry_stats.json", "experiment_02_advanced_procedural/renders/advanced_render_log.json"),
    ("exp2_base", "Exp 2 base mesh (no subsurf)", "experiment_02_advanced_procedural/dragon_advanced.blend",
     "experiment_02_advanced_procedural/geometry_stats_cage.json", None),
    ("exp3", "Exp 3 sculpt (high-res)", "experiment_03_sculpting/dragon_sculpt.blend",
     "experiment_03_sculpting/geometry_stats_sculpt.json", "experiment_03_sculpting/renders/sculpt_render_log.json"),
    ("exp3_decimated", "Exp 3 decimated variant", "experiment_03_sculpting/dragon_sculpt_decimated.blend",
     "experiment_03_sculpting/geometry_stats_sculpt_decimated.json", None),
    ("exp4_original", "Exp 4 AI original (as generated)", "experiment_04_ai_generation/dragon_ai_original.blend",
     "experiment_04_ai_generation/geometry_stats_ai_original.json", "experiment_04_ai_generation/renders/original/ai_original_render_log.json"),
    ("exp4", "Exp 4 AI repaired", "experiment_04_ai_generation/dragon_ai_generated.blend",
     "experiment_04_ai_generation/geometry_stats_ai_generated.json", "experiment_04_ai_generation/renders/generated/ai_generated_render_log.json"),
    ("exp5", "Exp 5 hybrid (game version)", "experiment_05_hybrid/dragon_hybrid.blend",
     "experiment_05_hybrid/geometry_stats_hybrid.json", "experiment_05_hybrid/renders/hybrid_render_log.json"),
    ("exp5_highres", "Exp 5 hybrid high-res (bake source)", "experiment_05_hybrid/dragon_hybrid_highres.blend",
     "experiment_05_hybrid/geometry_stats_hybrid_highres.json", None),
]

BUILD_SECONDS = {  # measured inside each build script (perf_counter); see the experiment logs
    "exp1": load("experiment_01_basic_procedural/build_log.json")["build_seconds_including_save"],
    "exp2": load("experiment_02_advanced_procedural/build_log.json")["build_seconds_including_save"],
    "exp3": load("experiment_03_sculpting/sculpt_log.json")["total_seconds"],
    "exp3_decimated": load("experiment_03_sculpting/mesh_prep_log.json")["total_seconds"],
    "exp4_original": load("experiment_04_ai_generation/generation_settings.json")["total_seconds"],
    "exp5": load("experiment_05_hybrid/hybrid_log.json")["total_seconds"],
}

out = []
for mid, label, blend, stats_rel, render_rel in MODELS:
    s = load(stats_rel)
    t = s["totals"]
    rec = {"id": mid, "label": label, "file": blend, "file_opens": s["file_opens"],
           "file_size_mb": round(s["file_size_bytes"] / 1048576, 2), "mesh_objects": s["mesh_object_count"],
           "materials": s["material_count"], "triangles": t["triangles"], "polygons": t["polygons"],
           "vertices": t["vertices"], "shells": t["shells"], "non_manifold_edges": t["non_manifold_edges"],
           "bbox_size_m": s["bbox_world"]["size"], "bbox_min_z": s["bbox_world"]["min"][2],
           "buried_face_pct": (s.get("buried_surface_estimate") or {}).get("buried_face_pct"),
           "buried_area_pct": (s.get("buried_surface_estimate") or {}).get("buried_area_pct"),
           "uv_on_all_objects": all(o["uv_layers"] > 0 for o in s["objects"]),
           "build_seconds": BUILD_SECONDS.get(mid)}
    if render_rel:
        rec["render_seconds_8_views"] = load(render_rel)["total_render_seconds"]
    out.append(rec)

with open(os.path.join(HERE, "metrics.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1)
cols = ["id", "triangles", "vertices", "mesh_objects", "materials", "shells", "non_manifold_edges", "buried_face_pct",
        "uv_on_all_objects", "file_size_mb", "build_seconds", "render_seconds_8_views", "bbox_min_z"]
print(" | ".join(cols))
for r in out:
    print(" | ".join(str(r.get(c)) for c in cols))
