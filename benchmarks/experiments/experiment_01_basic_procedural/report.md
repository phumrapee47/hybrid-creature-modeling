# Experiment 1: Basic Procedural Modeling (Primitive Assembly)

**Status:** Complete and verified. The final model is script revision 3.
**Date:** 2026-10-23. **Blender:** 5.2.2 LTS (headless, `blender -b`). **Manual Blender UI work:** none.

![contact sheet](renders/basic_contact_sheet.png)

## 1. What was built and how

A Blender Python script ([dragon_basic.py](dragon_basic.py)) builds the whole dragon from primitives. It uses no lofting, sculpting, booleans, external assets or AI geometry.

| Construction element | Count | Used for |
|---|---|---|
| UV spheres, scaled into ellipsoids | 55 | Chest, abdomen and hips; shoulder and thigh masses; skull, muzzle, jaw, cheeks and brows; eyes and pupils; joints; feet; toe knuckles |
| Cones and truncated cones (cylinders with two radii) | 87 | Limb segments, toes, claws, dorsal spikes, wing bones |
| Bezier curve primitives (round bevel, per-point radius) | 4 | Neck, tail, two horns. These are converted to mesh. |
| Basic hand-placed meshes | 2 | Wing membranes: a triangle fan from the wrist over a scalloped outline, thickened 8 mm with `bmesh.ops.solidify` |

Disclosures about technique:
- **Curves.** The neck, tail and horns are Bezier *curve primitives* with a round bevel whose radius varies per control point. The brief allows "curves" for Experiment 1. No custom cross-sections or lofting were used; every cross-section is a circle.
- **Spike placement.** Dorsal spikes are placed by ray-casting from an approximate spine line onto the body surface. This is a *placement* helper only; each spike is still a plain cone.
- **Belly colour.** The underbelly is a per-face material assignment on the existing primitives. On the torso it uses the face normal. On the neck and tail it uses the angle around the tube's centreline (revisions 2 and 3).
- **Joining.** Parts are combined into 9 mesh objects by component, but their geometry is **not** merged. Each object holds many overlapping closed shells.

Build time: **1.65 s** for the script excluding the save, 1.73 s including it. Timing uses `time.perf_counter()` inside Blender ([build_log.json](build_log.json)).

## 2. Standardized evaluation environment (shared by all experiments)

All shared files are in [../shared/](../shared/).

| Item | Setting |
|---|---|
| Orientation and scale | Metres; Z up; the dragon faces −Y with its left side at +X; feet on Z = 0. Reference box X ±1.40, Y −1.25…1.80, Z 0…1.65. |
| Renderer | Cycles, 128 samples, OpenImageDenoise, "Standard" view transform (so palette colours are shown faithfully), 1600×1200 |
| Device | CUDA on an RTX 4050 Laptop GPU. OptiX fails on this machine with `OPTIX_ERROR_INTERNAL_COMPILER_ERROR`, so it is excluded. |
| Lighting | Three neutral white square area lights (key, fill, rim) plus a flat grey world at strength 0.55. No depth of field, bloom or motion blur. |
| Silhouette | Workbench engine, flat black model on a white background, floor hidden |
| Clay | View-layer material override with a neutral grey (sRGB 0.62), roughness 0.55 |
| Wireframe | A dark Wireframe modifier (2.2 mm) on copies of each object, over a light clay base. It shows the final evaluated mesh. |
| Materials | [material_palette.py](../shared/material_palette.py): Principled BSDF plus low-amplitude value noise. No bump or normal maps. |

Each view is rendered from the saved `.blend` by [render_views.py](../shared/render_views.py), which rebuilds the rig from [benchmark_settings.json](../shared/benchmark_settings.json) every time.

| View | Camera | Shading | File |
|---|---|---|---|
| 01 Front orthographic | front_ortho | clay | [basic_01_front_ortho.png](renders/basic_01_front_ortho.png) |
| 02 Side orthographic | side_ortho | clay | [basic_02_side_ortho.png](renders/basic_02_side_ortho.png) |
| 03 Three-quarter perspective | three_quarter (70 mm) | material | [basic_03_three_quarter.png](renders/basic_03_three_quarter.png) |
| 04 Head close-up | head_closeup (55 mm) | material | [basic_04_head_closeup.png](renders/basic_04_head_closeup.png) |
| 05 Wireframe | three_quarter | wireframe | [basic_05_wireframe.png](renders/basic_05_wireframe.png) |
| 06 Silhouette | side_ortho | black on white | [basic_06_silhouette.png](renders/basic_06_silhouette.png) |
| 07 Neutral clay | three_quarter, same camera as 03 | clay | [basic_07_clay.png](renders/basic_07_clay.png) |
| 08 Material | rear_three_quarter (70 mm) | material | [basic_08_material.png](renders/basic_08_material.png) |

Views 03 and 07 share a camera so that material and clay can be compared directly. View 08 shows the back, wings, spikes and tail, which the front views hide. Total render time was 63.4 s with no GPU→CPU fallbacks ([render log](renders/basic_render_log.json)).

## 3. Geometry statistics

These come from [geometry_stats.json](geometry_stats.json), produced by [inspect_model.py](../shared/inspect_model.py) in a **fresh Blender process that opened the saved file**. That run is the "file opens" check, and it passed.

| Metric | Value | How it was calculated |
|---|---|---|
| Mesh objects | 9 (plus 1 empty root) | MESH objects in the `Dragon` collection |
| Polygons | 20,034 | Sum of evaluated mesh faces. There are no modifiers, so base = evaluated. |
| Triangles | 38,940 | Sum of `loop_triangles`, i.e. what a game engine would receive |
| Vertices | 19,862 | Sum of evaluated vertices |
| Materials | 7 | Distinct materials in use: skin, belly, horn, claw, eye, pupil, membrane |
| Dimensions (X × Y × Z) | 2.65 × 2.87 × 1.52 m | World-space bounding box of all vertices; it fits inside the reference box |
| File size | 3,028,641 bytes (2.89 MiB) | Uncompressed `.blend` |
| Script execution time | 1.65 s (1.73 s with save) | `perf_counter` inside the script |
| Render time (8 views) | 63.4 s | `perf_counter` around each render call |
| Separate shells | 156 | Connected components. Every primitive is its own closed or open shell. |
| Non-manifold / boundary edges | 192 / 192 | All are open ends of the curve tubes (neck, tail, horns): `use_fill_caps` did not cap the round-bevel tubes. Every hole is buried inside another part or is under 3 mm wide at a tip. |
| **Buried surface (estimate)** | **42.1 % of faces, 30.5 % of area** | Ray-parity test: is a point 1.5 mm outside each face inside another shell? This measures hidden, wasted geometry. |
| UV maps | Present but unusable | Every primitive has its own overlapping 0–1 UV layout; Body and Horns carry two UV layers. |
| Iterations | 3 model revisions + 1 rig calibration | See §5 |
| Manual intervention | None in Blender | All geometry is scripted. I (the agent) judged the renders and edited the script between runs. |

Per object:

| Object | Vertices | Faces | Triangles | Shells |
|---|---|---|---|---|
| DRG_Body (torso, neck, tail) | 6,158 | 6,320 | 12,176 | 11 |
| DRG_Head | 3,868 | 4,128 | 7,696 | 10 |
| DRG_Legs | 5,188 | 5,328 | 10,160 | 54 |
| DRG_Horns | 1,260 | 1,232 | 2,432 | 6 |
| DRG_Wing_L / DRG_Wing_R | 832 each | 823 each | 1,624 each | 10 each |
| DRG_Eyes | 704 | 768 | 1,392 | 4 |
| DRG_DorsalSpikes | 700 | 420 | 1,260 | 35 |
| DRG_Claws | 320 | 192 | 576 | 16 |

## 4. Visual evaluation against the specification

| # | Requirement | Result |
|---|---|---|
| A1 | Four legs | Present. Front legs bend backward at the elbow; hind legs are digitigrade with knee, hock and foot. The proportions read correctly in the side view. |
| A2 | Two wings with fingers and membranes | Present and the most successful part: four fingers, thumb claws, a scalloped trailing edge. The membranes are flat, though (see below). |
| A3 | Chest / abdomen / hips | All three volumes are present and the waist is narrower, but they read as **three separate balloons with hard intersection creases** (view 02) |
| A4 | Curved neck | An S-curve is present; the transition into the head is a lumpy interpenetration |
| A5 | Skull, muzzle, jaw | Recognisable but **cartoonish**: blob muzzle, sausage brows, bulging eyes with no sockets, and the mouth line is just the jaw ellipsoid intersecting the muzzle (view 04) |
| A6 | Backward-curving horns | Present and clean after revision 2 |
| A7 | Tapered tail with a pointed tip | Present; long, gradual taper with a slight lateral S-curve |
| A8 | Dorsal spikes | Present, 35 spikes. They read well in profile, but from behind (view 08) they look like round studs because they are circular cones. |
| A9 | Individual claws | Present: 16 foot claws plus 2 wing thumb claws |
| — | Palette | Correct hues. The olive throat and belly read well; the bronze, amber and charcoal accents are distinct. |
| — | Silhouette (view 06) | **Reads instantly as a dragon.** The horns, wings, spikes and tail taper all separate cleanly. The weak point is the wing, which reads as a solid wedge in profile. |

## 5. Iteration log

| Run | Change | Reason (observed in renders) |
|---|---|---|
| Pipeline fix | OptiX → CUDA | The OptiX kernel failed to compile (driver/toolkit issue on this machine) |
| Pipeline fix | Render into a short temp folder, then move | Blender's PNG writer cannot save to paths over 260 characters; this workspace path is 265 |
| Pipeline fix | Render the Workbench silhouette after all Cycles views, with CPU fallback | The 4 GB GPU ran out of memory when switching from Workbench back to Cycles |
| Rig calibration | Lights ×0.35; three-quarter and rear cameras 50 → 70 mm; head camera 85 → 55 mm with a re-centred target; floor 30 → 400 m | The first renders were overexposed (white floor, washed-out greens), the framing was too loose, the horns were cropped, and the floor corner was visible. **These settings are now frozen for Experiments 2–5.** |
| Rev 1 → 2 | Belly faces on neck and tail chosen by angle around the tube centreline; horn curves start inside the cranium; lower jaw shortened | Stair-stepped belly boundary on the throat; flat horn-base caps poking out of the skull; protruding "lip" |
| Rev 2 → 3 | Fixed the ventral direction for the neck: its points run chest → head, and the rule assumed head → tail | Revision 2 put the olive stripe on the back of the neck instead of the throat |

Earlier revisions (`.blend` plus all renders) are kept in [iterations/rev1](iterations/rev1) and [iterations/rev2](iterations/rev2).

## 6. Visual shortcomings: limits of primitive assembly

These are the evaluation focus. Items marked **inherent** cannot be fixed without leaving the method.

1. **"Inflatable toy" volume (inherent).** Every mass is a convex ellipsoid. There are no planes, no muscle insertions and no tapering transitions. Where two primitives meet, the surface gets a hard crease instead of a blended join. The torso reads as three stacked balloons and the thighs as round cushions (views 02 and 08).
2. **Doll-like, ball-jointed limbs (inherent).** Uniform cones plus joint spheres look like an action figure. Wrists and ankles cannot thin, and elbows and knees cannot form bony points. The feet are flat ellipsoid "slippers".
3. **Cartoon head instead of a stylized fantasy skull (mostly inherent).** No eye sockets (that would need booleans or sculpting), so the eyes sit on the surface. The brows are sausages. There are no cheekbone or jaw planes, and the mouth is an intersection seam. The dragon looks friendly rather than fantasy-adventure.
4. **Only round cross-sections on the neck and tail (inherent to curve bevels).** There is no dorsal or ventral flattening and no sense of a spine or throat structure.
5. **Discontinuous material zones (inherent).** The throat stripe ends abruptly where the neck tube enters the chest sphere, and the chest belly is a latitude cut on a sphere. Material boundaries depend on each primitive's own topology.
6. **Flat, faceted wing membranes.** Large flat-shaded fan triangles with no billow. The leading-edge membrane is one flat triangle, and in the side view the folds produce dark facets. More subdivision with displacement would help, but that would be custom mesh shaping (Experiment 2 territory).
7. **Wasteful topology.** An estimated 42 % of faces (30 % of area) are buried inside other parts. Density is uniform rather than placed where the silhouette needs it: a hidden torso sphere costs as much as the visible face. UV-sphere poles pinch at the ends of every ellipsoid (view 05).
8. **Not usable as a real-time asset without rework.**
   - There are 156 interpenetrating shells, so any skinning deformation would open gaps or cause clipping at every joint.
   - The UVs are overlapping per-primitive layouts.
   - The tube ends are open.
   - At 38.9 k triangles it is heavy for what it shows. Removing the buried faces alone would save roughly 40 %.
9. **What worked well.** The silhouette, overall proportions, wing structure, claws, horns and palette all read correctly. The build is fully reproducible in under 2 seconds. Primitive assembly is a fast and reliable **blockout** method; it fails at surface continuity and anatomical refinement.

## 7. Implications for an AI modeling skill (provisional)

- Primitive assembly is easy for an agent to script and to verify by numbers (bounding box, landmarks, counts). It suits a **blockout or proportion pass**, not final quality.
- Two failure classes surfaced that a skill should guard against automatically:
  - **Direction and sign conventions** in procedural rules. The revision 2 bug was only caught by looking at the render.
  - **Tool and platform limits:** OptiX failure, Windows path length, GPU memory.

  Mandatory render-and-inspect loops are necessary; a successful script run proved nothing about visual correctness.
- Useful automatic checks that came out of this experiment: buried-surface percentage, shell count, boundary-edge count and reference-box fit.

Scores for the six categories will be assigned in the final comparison so all models are scored together under one framework.

## 8. Files

| File | Purpose |
|---|---|
| [dragon_basic.py](dragon_basic.py) | Reproducible build script: `blender -b --factory-startup --python dragon_basic.py` |
| [dragon_basic.blend](dragon_basic.blend) | Final model (revision 3) plus the benchmark rig |
| [renders/](renders/) | The 8 standard views, contact sheet and render log |
| [geometry_stats.json](geometry_stats.json) | Full statistics, including per-object values |
| [build_log.json](build_log.json) | Build timing and primitive counts |
| [iterations/](iterations/) | Revision 1 and revision 2 `.blend` files and renders |
| `build_stdout.txt`, `render_stdout.txt`, `inspect_stdout.txt` | Raw Blender console logs |
