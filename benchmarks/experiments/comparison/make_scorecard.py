"""Write comparison/scorecard.csv: evaluator scores (1-10 per category, with evidence) joined to the
measured metrics in metrics.json (run collect_metrics.py first).

Scores are judgements by the evaluating agent from the standardized renders and the geometry
inspections; they are not measurements. Expected uncertainty: about +/-1 per category.
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CATS = ["silhouette", "volume_form", "anatomy_proportions", "mesh_shading", "materials_details", "realtime_suitability"]

ROWS = [
    {"id": "exp1", "method": "Basic procedural (primitive assembly)", "status": "complete", "ranked": "yes",
     "scores": [5, 3, 4, 3, 4, 3], "iterations": "3 model revisions (+1 rig calibration)",
     "manual": "none", "external": "none",
     "evidence": {
         "silhouette": "Reads instantly as a dragon (06_silhouette); torso outline is three bumps and wings read as a solid wedge in profile",
         "volume_form": "Convex ellipsoids with hard intersection creases; 'inflatable toy' torso and ball-jointed limbs (02/07)",
         "anatomy_proportions": "All parts present; cartoon head without sockets, sausage brows, doll limbs (04)",
         "mesh_shading": "156 interpenetrating shells, 42% buried faces, 192 open tube-end edges, faceted flat membranes",
         "materials_details": "Palette correct; belly zones discontinuous across primitives; round-cone spikes; no surface detail",
         "realtime_suitability": "38.9k tris but ~40% hidden; overlapping per-primitive UVs; intersecting parts cannot deform"}},
    {"id": "exp2", "method": "Advanced procedural (cross-section lofting)", "status": "complete", "ranked": "yes",
     "scores": [8, 6, 7, 7, 6, 6], "iterations": "4 revisions (incl. 1 zero-normal bug fix)",
     "manual": "none", "external": "none",
     "evidence": {
         "silhouette": "Cleanest continuous S-line snout-to-tail; fingered, scalloped, billowed wings (02/06/08)",
         "volume_form": "Distinct chest/waist/hips in one trunk surface; limbs remain smooth tubes; creases at limb/neck roots",
         "anatomy_proportions": "Skull with stop, brow, crest, sockets+lids (rev 4); jointed digitigrade limbs; head small for neck",
         "mesh_shading": "Quad loops follow anatomy (cage wireframe); subsurf shading clean; 21% buried at junction overlaps; 10 non-manifold",
         "materials_details": "Continuous column-aligned belly stripe; palette exact; almost no surface detail (no muscle/scale cues)",
         "realtime_suitability": "56k base / 171k subsurf tris; packed loft UVs; quad flow rig-friendly on trunk, but junction overlaps and 52k-tri wing frames"}},
    {"id": "exp3", "method": "Sculpting workflow (scripted sculpt mode)", "status": "complete", "ranked": "yes",
     "scores": [7, 7, 7, 6, 7, 4], "iterations": "3 script revisions over 6 runs + mesh-prep restructure",
     "manual": "none (GUI session required)", "external": "Blender GUI session (sculpt mode crashes with -b)",
     "evidence": {
         "silhouette": "Same concept as Exp 2 but blockout lumps survive (round snout blob, knee/shoulder bulges) (02/06)",
         "volume_form": "One fused shell with filleted seams; sculpted pectoral/deltoid/rib/thigh masses; blockout dominates proportions",
         "anatomy_proportions": "Brow furrows, jowls, socket, nostrils, mouth crease, throat scutes, neck folds; snout weaker than Exp 2",
         "mesh_shading": "Unified smooth voxel surface, 3.5% buried; some stroke noise; 486k tris, no edge flow, no UVs",
         "materials_details": "Richest geometric surface detail; smooth attribute-blended belly; same palette",
         "realtime_suitability": "Sculpt unusable in real time; QuadriFlow lost tail/fingers (up to 378 mm); decimated 43k variant accurate (1.7 mm) but triangle soup"}},
    {"id": "exp4_original", "method": "AI 3D generation (TRELLIS) - as generated", "status": "complete", "ranked": "info only",
     "scores": [6, 5, 5, 3, 4, 5], "iterations": "3 generation attempts (1 succeeded)",
     "manual": "none (user chose the service route)", "external": "Hugging Face Space trellis-community/TRELLIS (free ZeroGPU, quota-limited)",
     "evidence": {
         "silhouette": "Complete and on-model (design inherited from the Exp 3 reference image); ragged spike frills, open jaw, polygonal wing edges, wingspan 4 cm/side over reference box",
         "volume_form": "Plausible overall masses, soft and lumpy at 8.3k tris; reference muscle/brow forms softened",
         "anatomy_proportions": "All parts present incl. claws and fingers; painted eye dot (no eye/socket); jaw opened; spikes became frills",
         "mesh_shading": "100% flat-shaded facets; 211 UV-seam-split pieces, 3,565 open edges; inconsistent normals across pieces",
         "materials_details": "AI-painted colour zones on UVs, but declared metallic=1; horns drifted to pink; lighter skin; blurry 1024 texture",
         "realtime_suitability": "Only 8.3k tris + 1 texture, but split vertices, faceting and wrong PBR flags need fixing"}},
    {"id": "exp4", "method": "AI 3D generation (TRELLIS) - repaired", "status": "complete", "ranked": "yes (design inherited - see caveat)",
     "scores": [6, 5, 5, 5, 5, 7], "iterations": "3 repair iterations (weld/shade/material, colour fix, belly cap)",
     "manual": "none", "external": "Hugging Face Space trellis-community/TRELLIS (free ZeroGPU, quota-limited)",
     "evidence": {
         "silhouette": "Unchanged by repair (shape preserved): complete, on-model, ragged frills, open jaw",
         "volume_form": "Unchanged by repair; smooth shading removes faceting but low resolution remains",
         "anatomy_proportions": "Unchanged: no eye sockets/real eyes, frill spikes, inherited design",
         "mesh_shading": "Welded to 2 shells, 9 non-manifold, consistent normals; smooth-by-angle shading; polygonal silhouette edges",
         "materials_details": "Non-metal PBR; palette-aligned horns/skin/belly via HSV medians; still painted eyes, baked lighting, low texel density",
         "realtime_suitability": "Best budget: 8.3k tris, 1 material, UVs + texture; triangle soup (not rig-friendly); low texture resolution"}},
    {"id": "exp5", "method": "Hybrid (lofts + voxel fusion + sculpt + inserts + gated mesh prep + normal bake)", "status": "complete", "ranked": "yes",
     "scores": [8, 8, 8, 7, 8, 7], "iterations": "v1 -> v2 (3 fixes, 1 misdiagnosed) -> v3",
     "manual": "none (GUI session required)", "external": "Blender GUI session (sculpt phase)",
     "evidence": {
         "silhouette": "Exp 2-quality S-line, wings and horns; clean in all orthographic views; small head inherited",
         "volume_form": "Lofted proportions + fused, filleted joints + sculpted masses; forearms still tubular; small chest dimple",
         "anatomy_proportions": "Best head: skull planes, carved sockets with lids, slit pupils, nostrils, mouth crease, throat scutes; joint knobs; four-fingered wings",
         "mesh_shading": "One body shell, 0 non-manifold, no faceting (v2), membrane cracks closed (v3); game body is decimated triangles",
         "materials_details": "Palette throughout; smooth belly gradient; sculpt detail carried by a normal map baked from real geometry",
         "realtime_suitability": "44.6k tris, all UV-mapped, 2048 normal map, body within 1.2 mm of sculpt; no edge loops for skinning, no rig/LOD/engine test"}},
]

metrics = {m["id"]: m for m in json.load(open(os.path.join(HERE, "metrics.json"), encoding="utf-8"))}
extra_build = {"exp4": "26.9 s generation + 3.2 s repair"}
fields = ["experiment", "method", "status", "included_in_ranking"] + CATS + ["total_60", "triangles", "vertices",
          "mesh_objects", "materials", "file_size_MiB", "build_seconds", "render_seconds_8_views", "iterations",
          "manual_intervention", "external_tools"] + [f"evidence_{c}" for c in CATS]
with open(os.path.join(HERE, "scorecard.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(fields)
    for r in ROWS:
        m = metrics[r["id"]]
        build = extra_build.get(r["id"], m.get("build_seconds"))
        w.writerow([r["id"], r["method"], r["status"], r["ranked"], *r["scores"], sum(r["scores"]), m["triangles"],
                    m["vertices"], m["mesh_objects"], m["materials"], m["file_size_mb"], build,
                    m.get("render_seconds_8_views"), r["iterations"], r["manual"], r["external"],
                    *[r["evidence"][c] for c in CATS]])
for r in ROWS:
    print(f"{r['id']:14} {r['scores']} total={sum(r['scores'])}")
