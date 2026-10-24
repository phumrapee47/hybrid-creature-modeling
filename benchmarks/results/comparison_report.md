# Dragon Modeling Benchmark: Final Comparison

**Date:** 2026-10-24. **Blender:** 5.2.2 LTS (Windows 11, RTX 4050 Laptop, CUDA).
**Experiments:** all five completed. None was blocked. Experiment 4 completed under constraints: one of three generation attempts succeeded, the other two were refused by free-tier GPU limits.

![main comparison](comparison_sheet_main.png)

## 1. Summary

| Rank | Experiment | Total / 60 | One-line verdict |
|---|---|---|---|
| 1 | **Exp 5 Hybrid** | **46** | Lofted proportions + fused, sculpted surface + light game mesh with baked detail. Best overall; most complex. |
| 2 | Exp 2 Advanced procedural (lofting) | 40 | Best silhouette and topology per line of code. Fast, headless, deterministic. Junctions overlap; little surface detail. |
| 3 | Exp 3 Sculpting (scripted) | 38 | Best surface anatomy and continuity, but blockout-limited proportions, heavy mesh, GUI-only, and fragile mesh preparation |
| 4 | Exp 4 AI generation (TRELLIS, repaired) | 33 (original 28) | Complete 8.3k-triangle asset in 27 s, but reconstructs a supplied design, with coarse details, colour drift and quota-limited access |
| 5 | Exp 1 Basic procedural | 22 | Reliable blockout, not a final asset |

**Recommendation for the future AI 3D modeling skill:** a **loft-first hybrid pipeline** (§7).
- **Backbone:** deterministic, headless cross-section lofting (Exp 2).
- **Added only where measured defects require:** voxel fusion with crease smoothing for joints; restrained, closed-loop sculpt detail; curve-sweep inserts; deviation-gated mesh preparation with a normal-map bake.
- **Wrapper:** mandatory render-and-measure verification loops.
- **AI generation** is an optional, user-approved side path for quick concept or LOD meshes, not the primary method.

## 2. Evaluation method

**Identical environment.**
- All final models were rendered by the same script ([shared/render_views.py](../shared/render_views.py)) with identical cameras, lights, world, floor, Cycles 128 samples with OpenImageDenoise, and the "Standard" view transform.
- Consistency was verified for this report: background, sky and floor pixel means are identical across all five experiments' renders, to within 0.5 of 255.
- The rig was calibrated once, during Exp 1 (lights ×0.35, lenses). Exp 1's final renders were made after that calibration.

**Measurements.**
- Every final `.blend` was re-opened in a fresh Blender process by [shared/inspect_model.py](../shared/inspect_model.py) (all opened).
- Triangles, vertices and polygons are summed from the **evaluated** meshes, after modifiers.
- Buried surface is a ray-parity estimate of faces hidden inside other shells.
- Definitions are in [benchmark_settings.json](../shared/benchmark_settings.json). Collected values are in [metrics.json](metrics.json) (via [collect_metrics.py](collect_metrics.py)).

**Scores.**
- Each 1–10 score is a judgement by the evaluating agent from the standardized renders and measured geometry. One evidence sentence per score is in [scorecard.csv](scorecard.csv), via [make_scorecard.py](make_scorecard.py).
- These are **not** measurements. With a single evaluator, expect about ±1 per category. **The 2-point gap between Exp 2 (40) and Exp 3 (38) is within that uncertainty.** The gaps to Exp 5 (46), Exp 4 (33) and Exp 1 (22) are not.
- Polygon count was never used as a quality proxy: the heaviest model (Exp 3, 505k triangles) does not score highest.

**Caveats.**
1. **Exp 4's design is inherited.** Its input image was a render of the Exp 3 model, so its silhouette and anatomy scores measure *reconstruction* fidelity, not design ability.
2. **Exp 3 and Exp 5 need a Blender GUI session** for sculpt mode (Blender 5.2.2 crashes in background mode). They are still fully automated: no manual input.
3. **Mixed shading conventions in the material views.** Exp 5's material renders include a normal map baked from its own high-res sculpt, which is geometry-derived detail, not a procedural bump. The clay views show its 24k-triangle game body without it. Exp 4's material renders use its AI-painted texture.

## 3. Scorecard (from [scorecard.csv](scorecard.csv))

| Experiment | Silhouette | Volume and form | Anatomy | Mesh and shading | Materials and detail | Real-time | **Total** |
|---|---|---|---|---|---|---|---|
| Exp 1 basic procedural | 5 | 3 | 4 | 3 | 4 | 3 | **22** |
| Exp 2 advanced procedural | **8** | 6 | 7 | **7** | 6 | 6 | **40** |
| Exp 3 sculpting | 7 | 7 | 7 | 6 | 7 | 4 | **38** |
| Exp 4 AI, *original* (info) | 6 | 5 | 5 | 3 | 4 | 5 | *28* |
| Exp 4 AI, repaired | 6 | 5 | 5 | 5 | 5 | **7** | **33** |
| Exp 5 hybrid | **8** | **8** | **8** | **7** | **8** | **7** | **46** |

Key evidence (the full sentences are in the CSV):
- **Silhouette.** Exp 2 and Exp 5 share the cleanest continuous S-line and the best wings ([form sheet](comparison_sheet_form.png), silhouette column). Exp 3 keeps blockout lumps; Exp 4 has ragged frills and an open jaw; Exp 1's torso reads as three bumps.
- **Volume.** Exp 5 combines Exp 2's proportions with fused, filleted joints and sculpted masses. Exp 2's limbs are tubes; Exp 1 is balloons.
- **Anatomy.** Exp 5's head has skull planes, carved sockets with lids, slit pupils, nostrils, a mouth crease and throat scutes. Exp 4's eyes are painted dots.
- **Mesh.** Exp 2 has quad loops that follow the anatomy; Exp 5 has one shell and 0 non-manifold edges but a triangulated game body. Exp 1 has 156 interpenetrating shells and 42 % buried faces.
- **Materials.** Every experiment uses the shared palette except Exp 4, whose AI texture drifted and was aligned during repair. Exp 5 adds baked sculpt detail.
- **Real-time.** Exp 4 has the best budget (8.3k triangles, one material). Exp 5 is 44.6k triangles, fully UV-mapped, with a normal map. Neither has edge loops for skinning, and neither was tested in an engine.

## 4. Answers to the project questions

| Question | Answer | Evidence |
|---|---|---|
| Best silhouette | **Exp 2 and Exp 5 (tie)**: both come from the controlled lofts | Silhouette column of the form sheet |
| Most convincing 3D volume | **Exp 5**, then Exp 3 | Fused, filleted joints plus sculpted masses on lofted proportions (clay three-quarter column) |
| Most coherent anatomy | **Exp 5** | Head close-up column; anatomy checklist complete in Exp 2/3/5; Exp 4 lacks eyes and sockets |
| Best geometry and shading | **Exp 2** for topology (quad loops, UVs from the loft); **Exp 5** for surface continuity (1 shell, 0 non-manifold, no faceting) | Wireframe column; inspection metrics |
| Best materials and surface details | **Exp 5** | Palette plus attribute belly plus normal-mapped scutes, folds and muscles |
| Best quality vs performance balance | **Exp 5 game version**: 46/60 at 44.6k triangles. Exp 4 is the cheapest (8.3k) but scores 33 and depends on an external service. | §5 metrics |
| Most suitable for AI-skill automation | **Exp 2's lofting core**, extended with Exp 5's gated steps | Headless, deterministic, 0.4 s, parametric, measurable, scores 40 alone; each Exp 5 addition targets a measured defect |

## 5. Performance and workflow metrics

| Metric | Exp 1 | Exp 2 | Exp 3 | Exp 4 (original → repaired) | Exp 5 (game) |
|---|---|---|---|---|---|
| Triangles (evaluated) | 38,940 | 171,256 (56,312 base) | 505,342 (decimated variant 42,996) | 8,337 | **44,600** (high-res 442,664) |
| Vertices | 19,862 | 85,816 (28,344 base) | 252,783 | 6,149 → 4,155 | 22,448 |
| Mesh objects / materials | 9 / 7 | 9 / 7 | 6 / 6 | 1 / 1 | 7 / 7 |
| File size (MiB) | 2.89 | 3.50 | 18.47 (decimated 3.41) | 2.47 → 4.16 | 4.83 (high-res 22.03) |
| Generation / build time | 1.7 s | **0.47 s** | 47.7 s + 13.7 s mesh prep | 26.9 s server + 3.2 s repair | 35.9 s |
| Render, 8 views | 63 s | 111 s | 83 s | 101 s → 79 s | 106 s |
| Shells / non-manifold edges | 156 / 192 | 102 / 10 | 64 / 10 | 211 / 3,565 → 2 / 9 | 74 / **0** |
| Buried surface | 42.1 % | 21.0 % | 3.5 % | (artefact) → 0 % | 10.0 % (insert bases) |
| UVs | overlapping, unusable | packed loft islands | none on sculpt | auto-unwrap | all objects |
| Iterations | 3 revisions + rig calibration | 4 revisions | 3 revisions / 6 runs + mesh-prep rework | 3 generation attempts (1 OK) + 3 repair iterations | v1 → v2 → v3 |
| Manual intervention | none | none | none (GUI session) | none (user chose the service) | none (GUI session) |
| External tools | none | none | Blender GUI | Hugging Face Space (free, quota-limited) | Blender GUI |
| Repair effort | — | — | — | Low (integrity), medium (materials), high/unrepaired (design) | — |
| Key technical limitations | Primitive look; no unification | Junction overlaps; tube limbs; overbuilt wing frames | GUI-only sculpt; brush calibration needed; QuadriFlow lost thin parts; no UVs | GPU caps/quota; inherited design; coarse texture; no eyes | GUI-only; complexity; triangulated body without edge loops; claws 6.6 mm below ground |

## 6. Strengths and weaknesses by method

**Exp 1: Basic procedural (primitive assembly)**
- Strengths: trivial to script and verify numerically; readable silhouette; 1.7 s.
- Weaknesses: balloon and ball-joint forms; interpenetrating shells (42 % hidden geometry); unusable UVs; cartoon head. Useful only as a blockout.

**Exp 2: Advanced procedural (lofting)**
- Strengths: best silhouette and proportions; continuous trunk surface; quad loops and UVs come free from the parameterisation; headless and deterministic; fastest build (0.47 s).
- Weaknesses: limb, neck and wing roots overlap rather than merge; limbs read as tubes; surface anatomy needs extra techniques. Small parameter changes vanish under subdivision unless checked by pixel diff. A zero-normal bug produced plausible-looking wrong eyes for three revisions.

**Exp 3: Sculpting (scripted sculpt mode)**
- Strengths: true single-shell organic surface; cavity-masked smoothing fillets seams automatically; strokes produce muscles, ribs, folds and scutes; the closed-loop depth control works (53 of 59 targets).
- Weaknesses:
  - GUI-only, and brushes needed calibration: stroke size is ignored unless the brush pixel size is set.
  - Large masses can't be reshaped by strokes, so blockout lumps survive.
  - Heavy mesh with no UVs.
  - **Automatic quad retopology silently failed** on the tail and fingers; Decimate worked.
  - Colour zones need vertex attributes rather than per-face materials.

**Exp 4: AI generation (TRELLIS image-to-3D)**
- Strengths: a complete, textured, game-sized asset in under 30 s for free; integrity repairs are trivial (most "defects" were UV-seam vertex splits).
- Weaknesses:
  - Needs a concept image; we supplied our own model, so it doesn't show design ability.
  - Coarse details: no eyes, spike frills, open jaw.
  - Wrong metallic flag and colour drift.
  - Low texture resolution and triangle topology.
  - **Fragile access:** one endpoint exceeded the free GPU cap, the daily quota ran out after one run, and errors could be silent.

**Exp 5: Hybrid**
- Strengths: highest or tied-highest score in all six categories, outright highest in volume, anatomy and materials; every component technique fixes a defect measured earlier; a retopology gate caught QuadriFlow's failure automatically; normal bake keeps sculpt detail at 24k body triangles; 36 s end to end.
- Weaknesses: largest codebase (about 650 lines plus about 400 shared) and GUI dependency. The game body still lacks edge loops. Residual chest dimple; claws below the ground plane; 5 belly-scute strokes missed (grazing rays). One v2 fix was misdiagnosed and needed v3.

## 7. Recommended workflow for an AI 3D modeling skill

The ordering follows the evidence: proportions first (lofting), unification second, detail last, and every stage gated by measurements.

1. **Spec → parametric data.**
   - Encode landmarks, a spine and limb chains, and per-station cross-sections (superellipse width, top and bottom depth, squareness, bumps) as data. That's Exp 2's shape tables.
   - Fix units, orientation and a reference box up front (shared settings).
2. **Primary forms: controlled lofts, headless** ([proc_mesh.py](../shared/proc_mesh.py) sweeps).
   - Add joint-flank control points.
   - Changes must be large enough to survive subdivision: verify with a pixel diff.
3. **Unification: subdivide, then voxel-fuse, then remove creases.**
   - Catmull-Clark first, because raw loft facets survive fusion (Exp 5 v1).
   - Then voxel remesh, then cavity-masked smoothing.
   - In a headless environment, replace the sculpt-mode filter with a curvature-masked Laplacian smooth (not tested here).
4. **Secondary and tertiary detail.**
   - **Procedural** for precise features: sockets, nostrils.
   - **Closed-loop sculpt strokes** for muscles and folds, with a target depth per stroke and measured displacement ([sculpt_driver.py](../shared/sculpt_driver.py)). Inflate, not Clay, on convex limbs.
   - Skip strokes whose rays hit the surface at grazing angles.
5. **Inserts.** Horns, spikes, claws, eyeballs and membrane patches as curve sweeps and parametric patches. Panels that share an edge must sample it identically.
6. **Game mesh.**
   - Quad retopology only if a **per-region deviation gate** passes; otherwise Decimate.
   - **Next to test:** subdivide the loft quad cage and shrinkwrap it onto the sculpt. That would give edge loops and UVs for rigging.
   - Bake a normal map from the high-res mesh.
7. **Materials.** Palette entries; colour zones as smooth vertex attributes; validate PBR flags. For AI assets, add region-median colour alignment with capped gains.
8. **Verification loop (mandatory every iteration).**
   - Standard renders.
   - Pixel diff against the previous revision.
   - Geometric invariants: non-zero normals, shell count, non-manifold edges, buried %, reference-box fit, ground contact (claw tips must have Z ≥ 0).
   - Stroke displacement log; per-region deviation for derived meshes.
   - Then fix the top three defects, and diagnose before fixing: one Exp 5 fix was misdiagnosed from a render alone.
9. **Environment guards** found in this benchmark:
   - OptiX can fail (CUDA fallback).
   - Windows paths over 260 characters break Blender's file writers (save to a temp path, then move).
   - The GPU can run out of memory when switching render engines.
   - Sculpt mode requires the GUI.
   - Background-mode crashes.
   - External AI services need quota or token handling and **explicit user approval** for uploads, downloads or paid tiers.
10. **Optional AI path.** Image-to-3D for rapid concepts or distant LODs: weld, check normals and PBR, align colours, gate by the same checks. Never substitute it for the spec-driven pipeline without disclosure.

## 8. Limitations of this benchmark

- **One character, one evaluator.** Scores are expert-style judgements with about ±1 uncertainty, not a user study.
- **No real-time validation.** No rig, skinning test, LOD or game-engine import was performed. Real-time scores reflect budget, UVs and topology only.
- **Exp 4 is under-sampled.** It tested one generator and one seed (quotas); its input was our own render.
- **Scripted sculpting is not hand sculpting.** It shows what an agent can automate, not what a human artist achieves.
- **Lighting suits mid-tones.** Neutral studio lighting at a fixed exposure favours mid-tone materials; all models shared it.

## 9. Files

| File | Content |
|---|---|
| [comparison_sheet_main.png](comparison_sheet_main.png) | All models: side clay, three-quarter, head close-up, rear (identical cameras) |
| [comparison_sheet_form.png](comparison_sheet_form.png) | All models: front clay, three-quarter clay, silhouette, wireframe |
| [scorecard.csv](scorecard.csv) | Scores, totals, metrics and evidence per category ([make_scorecard.py](make_scorecard.py)) |
| [metrics.json](metrics.json) | Measured metrics of every final model ([collect_metrics.py](collect_metrics.py)) |
| [make_comparison_sheets.py](make_comparison_sheets.py) | Rebuilds the comparison sheets |
| Experiment reports | [Exp 1](../experiment_01_basic_procedural/report.md), [Exp 2](../experiment_02_advanced_procedural/report.md), [Exp 3](../experiment_03_sculpting/report.md), [Exp 4](../experiment_04_ai_generation/report.md), [Exp 5](../experiment_05_hybrid/report.md) |
