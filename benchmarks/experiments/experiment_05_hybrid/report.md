# Experiment 5: Hybrid Modeling Workflow

**Status:** Complete and verified. The final version is v3. **Date:** 2026-10-24. **Blender:** 5.2.2 LTS.
**Manual work:** none. Like Experiment 3, the script needs a Blender GUI session for its sculpt phase.

![final contact sheet](renders/hybrid_contact_sheet.png)
![v1 vs final](renders/v1_vs_final.png)
![Exp 2 / 3 / 5](renders/exp2_exp3_vs_exp5.png)

## 1. Technique per component, and the problem each one solves

| Component | Technique | Problem it solves (evidence from earlier experiments) |
|---|---|---|
| Torso, neck, tail, limbs, skull, jaw (primary forms) | Controlled cross-section **lofts** (Exp 2 rev 4 shape data) | Exp 2 had the best proportions and silhouette; Exp 3's primitive blockout left lumpy masses that strokes could not reshape |
| Junctions (limb roots, neck/skull, wing root, wrist/paw) | Lofts subdivided (Catmull-Clark ×2) → **voxel-fused** into one shell (5 mm) → **cavity-masked smoothing** | Exp 2 left interpenetration creases and 21 % buried faces at these joints; Exp 3 showed fusion plus a cavity fillet removes them |
| Secondary forms (muscles, ribs, brow, mouth, jaw angle, horn boss) | **Closed-loop scripted sculpt strokes** ([shared/sculpt_driver.py](../shared/sculpt_driver.py), extracted from Exp 3) | Lofts can't express muscle groups; Exp 3's strokes could |
| Tertiary detail (throat and belly scutes, neck folds) | Restrained sculpt creases, carried to the game mesh by a **baked normal map** | Detail without thousands of polygons |
| Eye sockets with lids, nostrils | **Procedural displacement** on the fused mesh, with the eyeball placed from the surface recorded before carving | Exp 2 rev 4 gave the most precise sockets; Exp 3 showed the eyeball must reference the pre-carve surface |
| Wings | Arm (humerus and forearm) fused into the body; **fingers kept as separate lofts**; membranes as **ruled and Coons patches** with scallops and billow | Exp 2's strongest part. Thin fingers (4–19 mm) would be degraded by 5 mm voxels. |
| Horns, dorsal spikes, claws, eyeballs | Curve-sweep inserts ([shared/proc_mesh.py](../shared/proc_mesh.py)) | Hard, thin forms are better modelled than sculpted (Exp 2 and 3) |
| Game mesh | QuadriFlow **gated by measured deviation** (max ≤ 12 mm and mean ≤ 2 mm per region), with **Decimate fallback** | Exp 3: QuadriFlow silently loses thin parts; Decimate stays accurate |
| Materials | Shared palette; belly as a smooth per-vertex weight blending palette skin and belly; normal map from the sculpt | Exp 3: voxel topology can't carry clean per-face material zones |

AI generation (Exp 4) was **not** used as a component. It would add a dependency on a quota-limited external service, and its geometry was coarser than what the lofts already provide.

## 2. Pipeline (single script, about 36 s)

[dragon_hybrid.py](dragon_hybrid.py): `blender --factory-startup --python dragon_hybrid.py` (GUI; it quits itself).

| Step | Time into run | Result |
|---|---|---|
| Lofts built and subdivided | 2.9 s | 14,836 loft faces → 233,824 after Catmull-Clark ×2 |
| Voxel fusion | 4.6 s | **1 shell**, 211,032 faces |
| Sculpt: cavity fillet (30 iterations), 6 junction smooths, 17 secondary strokes, 5 polish strokes, 25 tertiary strokes | 23.5 s | 53 strokes / 158 passes; **37 of 42 targeted strokes reached ≥ 75 % of target**; the 5 misses are belly scutes hit at grazing ray angles |
| Eye sockets and nostrils (procedural), belly weight, inserts, wing fingers, membranes | 25.9 s | 39 spikes; 248/249/49/49 vertices displaced |
| High-res file saved | 26.1 s | [dragon_hybrid_highres.blend](dragon_hybrid_highres.blend) |
| Game mesh: QuadriFlow tried → **rejected by gate** (tail error up to 1,179 mm) → Decimate accepted (max 1.2 mm, mean 0.13 mm); smart UV; normal bake 2048² (1.45 s) | 35.8 s | [dragon_hybrid.blend](dragon_hybrid.blend) |

Full log: [hybrid_log.json](hybrid_log.json).

## 3. Iteration (Phase 8): v1 → identify three defects → v2 → v3

| v1 defect (from renders) | Diagnosis | v2 fix | Outcome |
|---|---|---|---|
| **1. Faceted vertical stripes on limbs and flanks** | A render of the high-res file showed the same stripes, so the cause is geometry, not the bake: the raw loft ring facets were fused, and the voxel remesh reproduced them | Catmull-Clark ×2 on the lofts before fusion | **Fixed.** Smooth limbs and flanks ([crops](iterations/v2/v1_vs_v2_crops.png)) |
| **2. Dark notch near the wing root** (rear view) | Assumed to be a gap between the inner membrane and the flank | Project five points along the flank instead of three | **Misdiagnosed.** The notch remained. A zoom showed a hairline crack between two membrane panels along finger 4, because their shared edge was sampled with 16 vs 12 segments ([zoom](iterations/v2/v2_membrane_crack_zoom.png)). |
| **3. Sculpt dents at stroke ends** (chest dimple, notch above the knee) | Clay's plane flattening cuts into strongly convex limbs | Inflate/Deflate for the six convex-limb muscles; Clay kept for back and ribs | **Knee notch fixed; chest dimple reduced but still visible** |
| v3 (targeted) | The real cause of defect 2 | Panels sharing an edge use identical sampling (inner panel 12 → 16; front panel 12 → 18), so the weld closes them | **Fixed.** Crack gone. The final membranes have **0** non-manifold edges (Exp 2 and 3 had 10); degenerate patch corners are also dissolved. |

Pipeline bugs fixed along the way (not design iterations): a stale `None` in the view-layer object list; a stale mesh reference after subdivision.
Archived: [iterations/v1](iterations/v1), [iterations/v2](iterations/v2) (`.blend` files, renders, logs).

## 4. Geometry statistics

From a fresh-process inspection of both files: [geometry_stats_hybrid.json](geometry_stats_hybrid.json), [geometry_stats_hybrid_highres.json](geometry_stats_hybrid_highres.json).

| Metric | **Exp 5 game file** | Exp 5 high-res (bake source) | Exp 2 base / eval | Exp 3 sculpt / decimated | Exp 4 repaired |
|---|---|---|---|---|---|
| Mesh objects | 7 | 7 | 9 | 6 / 6 | 1 |
| Triangles | **44,600** | 442,664 | 56,312 / 171,256 | 505,342 / 42,996 | 8,337 |
| Polygons | 35,002 | 222,034 | 29,332 / 86,232 | 253,275 / 34,268 | 8,337 |
| Vertices | 22,448 | 221,480 | 28,344 / 85,816 | 252,783 / 21,610 | 4,155 |
| Materials | 7 (palette + 2048² normal map) | 7 | 7 | 6 | 1 (1024² texture) |
| Dimensions (m) | 2.65 × 2.90 × 1.53 | same | 2.65 × 2.90 × 1.53 | 2.65 × 2.89 × 1.53 | 2.89 × 2.89 × 1.61 |
| Body shells | **1** | 1 | 1 trunk + overlapping limbs | 1 | 1 (+1 tiny) |
| Non-manifold edges | **0** | 0 | 10 | 10 | 9 |
| Buried surface (faces / area) | 10.0 % / 9.4 % (insert bases) | 2.9 % / 9.4 % | 21.0 % / 18.8 % | 3.5 % / 8.6 % · 10.3 % / 8.5 % | 0 % |
| Body deviation from sculpt | max 1.2 mm, mean 0.13 mm | — | — | decimated 1.7 mm | — |
| UVs | all objects (smart UV body; loft UVs elsewhere) | inserts only | yes | decimated only | auto |
| File size | 5.07 MB | 23.1 MB | 3.67 MB | 19.4 / 3.57 MB | 4.36 MB |
| Build time | 35.9 s (GUI) | (same run) | 0.4 s | 47.6 s + 13.7 s | 27 s + 3 s |
| Render time (8 views) | 106 s | — | 111 s | 83 s | 79 s |

**Triangle budget of the game file:**

| Part | Triangles |
|---|---|
| Body | 24,000 |
| Membranes | 5,808 |
| Wing fingers | 5,032 |
| Spikes | 3,376 |
| Horns | 2,496 |
| Claws | 2,496 |
| Eyes | 1,392 |

Phase 7 optimisations compared with Experiment 2:
- **Wing frame:** 52 k → 5 k triangles, by thinning the finger lofts and dropping subdivision.
- **Horns:** 3.9 k → 2.5 k.
- **Spikes:** 4.4 k → 3.4 k.
- **Body:** 24 k triangles with a baked normal map, instead of 30 k + 44 k subdivided lofts.

## 5. Evaluation

| Criterion | Assessment |
|---|---|
| Silhouette | Exp 2-quality S-line, fingered and scalloped wings, horns and spike row; clean in all orthographic views. Inherited proportions: the head is small relative to the neck. |
| Volume and form | Best combination so far: lofted proportions **plus** fused, filleted junctions **plus** sculpted chest, shoulder, rib and thigh masses. Forearms and shins are still fairly tubular. |
| Anatomy | Skull with stop, brow, crest and cheeks; carved sockets with heavy upper lids and slit pupils; nostrils, mouth crease, jaw angle; throat scutes and neck folds; joint knobs; four-fingered wings |
| Mesh and shading | One body shell, 0 non-manifold edges, no faceting after v2, membrane cracks closed in v3. Remaining: small chest dimple; claw tips 6.6 mm below the ground plane (inherited paw and claw placement). |
| Materials | Palette colours throughout; smooth belly gradient; sculpted detail via a normal map baked from real geometry (not procedural bump) |
| Real-time suitability | Budget-conscious (44.6 k triangles) and fully UV-mapped. **Not claimed game-ready:** the body is decimated triangles without edge loops (bad for skinning deformation), no rig, LODs or engine import were tested, and the smart-UV layout has many islands. |

### Is the hybrid better without unnecessary complexity?
**Better: yes.** Visually it is the most complete model, combining Exp 2's proportions, Exp 3's surface anatomy and joint continuity, and a game-sized mesh, and it fixes the worst defect of each:
- Exp 2's interpenetrating junctions;
- Exp 3's lumpy blockout proportions;
- Exp 3's unreliable retopology, now caught by the gate.

**Complexity: justified, but real.** It depends on four shared modules, needs a GUI session, and has about 650 lines of experiment code plus about 400 lines of shared modules. Every added technique maps to a defect measured in an earlier experiment; nothing was added for its own sake.

### Unresolved
1. **Rig-friendly topology.** The automatic quad retopology failed the deviation gate again: the tail collapses. A promising next step: subdivide the **loft quad mesh itself** and shrinkwrap it onto the sculpt as the game mesh. It already has edge loops at every joint and parametric UVs. Not attempted here.
2. 5 of 42 targeted sculpt strokes (belly scutes) did not register, because they met the surface at grazing angles.
3. A small chest dimple remains, and the claw tips penetrate the ground by 6.6 mm.

## 6. Files

| File | Purpose |
|---|---|
| [dragon_hybrid.py](dragon_hybrid.py) | The full hybrid pipeline (GUI session) |
| [dragon_hybrid.blend](dragon_hybrid.blend) | **Final game version** (v3): decimated body + baked normals + inserts + wings |
| [dragon_hybrid_highres.blend](dragon_hybrid_highres.blend) | Fused, sculpted high-res body + inserts (bake source) |
| [renders/](renders/) | Final 8 views, contact sheet, [v1 vs final](renders/v1_vs_final.png), [Exp 2/3/5 sheet](renders/exp2_exp3_vs_exp5.png), `highres/` reference views |
| [hybrid_log.json](hybrid_log.json) | Timings, every stroke, gate decision, deviations, bake |
| `geometry_stats_*.json` | Inspection results |
| [iterations/v1](iterations/v1), [iterations/v2](iterations/v2) | Initial and intermediate versions (`.blend`, renders, logs, diagnostic crops) |
| [../shared/sculpt_driver.py](../shared/sculpt_driver.py), [../shared/proc_mesh.py](../shared/proc_mesh.py) | Reusable components for the future skill (Experiment 2 and 3 scripts are unchanged) |
