# Experiment 2: Advanced Procedural Modeling (Controlled Cross-Section Lofting)

**Status:** Complete and verified. The final model is script revision 4.
**Date:** 2026-10-23. **Blender:** 5.2.2 LTS (headless). **Manual Blender UI work:** none.
The shared rig, cameras, lights and material palette are the same as in Experiment 1. Nothing in `shared/benchmark_settings.json` changed except two new statistic definitions.

![contact sheet](renders/advanced_contact_sheet.png)

![Exp 1 vs Exp 2](renders/exp1_vs_exp2.png)

## 1. Construction method

Everything is built in [dragon_advanced.py](dragon_advanced.py). No primitives are stacked to form anatomy. The only primitive left is a UV sphere for each eyeball.

| Component | Technique |
|---|---|
| **Trunk: neck → chest → abdomen → hips → tail tip** | One continuous loft: 118 superellipse cross-sections × 32 vertices along a Catmull-Rom spine. Each section has its own half-width, dorsal height, ventral depth and squareness, plus a sternum keel bump and a dorsal ridge bump. One closed shell. |
| **Skull and muzzle** | Custom loft (snout → occiput) with boxy muzzle sections, a pronounced stop, brow, cheekbone and sagittal-crest bumps. Eye sockets with eyelid rims, and nostrils, are carved by vertex displacement along the surface normal. |
| **Lower jaw** | A separate lofted wedge that deepens toward the hinge. The mouth line is the small gap between the jaw and the upper muzzle. |
| **Limbs** | Lofts along joint chains (shoulder, elbow, wrist; hip, knee, hock, foot), with control points either side of each joint so the joint stays sharp, plus elbow and heel knobs and muscle masses. Roots flare inside the trunk to form shoulder and hip masses. |
| **Paws and toes** | Lofted flattened palms; each toe is a lofted tube with a knuckle bulge |
| **Horns, dorsal spikes, claws** | Curve-driven sweeps: Catmull-Rom paths with tapered elliptical profiles. Horns have growth ridges, spikes are laterally flattened blades swept backward, claws are hooked. Spike bases sit exactly on the trunk's dorsal vertex column. |
| **Wings** | A lofted bone frame (humerus, elbow knob, forearm, wrist knuckle, four fingers with knuckle bulges, thumb claw). Membranes are parametric surfaces: ruled patches between finger curves with scalloped trailing edges and billow, a Coons patch for the inner membrane (arm, finger 4, trailing edge, and a body attachment line projected onto the trunk), and a leading-edge patch. Seams are welded, then the membrane is solidified to 6 mm. |
| **Smoothing and normals** | Smooth shading everywhere and recalculated outward normals. **Subdivision Surface level 1** only on Body, Head, Legs and WingFrames; spikes, horns, claws, membranes and eyes have none. |
| **Materials** | The belly is assigned by angular column in each loft (ventral ±52°), so one continuous stripe runs from throat to tail tip. The jaw underside matches. |
| **UVs** | Each loft produces its own metric UV island (around × along), and islands are shelf-packed per object. Left/right parts share UVs because the left side is mirrored. |

Disclosure on "curves": horns, spikes and claws use the script's own spline-path sweeps, not Blender Curve objects. Unlike Experiment 1's round curve bevels, this allows non-circular, flattened and ridged profiles.

Build time is **0.40 s** excluding the save (0.47 s including it): 69 sweeps, 5 membrane patches, 4 displacements, 39 spikes.

## 2. Geometry statistics

These come from [geometry_stats.json](geometry_stats.json) (evaluated, with subdivision) and [geometry_stats_cage.json](geometry_stats_cage.json) (base mesh). Both were produced by `shared/inspect_model.py` in a fresh Blender process that opened the saved file, which also confirms the file opens.

| Metric | Exp 1 (final) | **Exp 2 base mesh** | **Exp 2 evaluated (subsurf L1)** |
|---|---|---|---|
| Mesh objects | 9 | 9 | 9 |
| Polygons | 20,034 | 29,332 | 86,232 |
| Triangles | 38,940 | 56,312 | 171,256 |
| Vertices | 19,862 | 28,344 | 85,816 |
| Materials | 7 | 7 | 7 |
| Dimensions X×Y×Z (m) | 2.65 × 2.87 × 1.52 | 2.65 × 2.90 × 1.53 | 2.65 × 2.90 × 1.53 |
| File size | 3.03 MB | 3.67 MB (3,665,333 B) | (same file) |
| Script time | 1.65 s | 0.40 s | — |
| Render time (8 views) | 63 s | — | 111 s (CUDA, no fallbacks) |
| Separate shells | 156 | 102 | 102 (**trunk = 1 shell**) |
| Non-manifold edges | 192 (open tube ends) | 10 | 10 (membrane leading-edge patch collapses at shoulder and wrist) |
| Buried surface (estimate) | 42.1 % faces / 30.5 % area | 22.5 % / 19.7 % | 21.0 % / 18.8 % |
| UVs | Overlapping per primitive, unusable | One packed layout per object, metric loft islands, mirrored halves overlap by design | same |
| Iterations | 3 | 4 | — |
| Manual intervention | none | none | — |

Evaluated triangles by object: WingFrames 52.5 k, Legs 44.3 k, Body 30.3 k, Head 25.3 k, everything else under 7 k.

## 3. Iteration log (render → inspect → fix)

| Rev | Change | Evidence that drove it | Outcome |
|---|---|---|---|
| 1 | First build | — | Continuous body and strong wings. Head reads as a duck/lizard with an eyeball stuck on; limbs look like noodles; hunched wing root in side view. |
| 2 | Bigger cranium, stronger brow, eyelid rim, deeper jaw, thinner upper neck; joint-flanking control points and thicker limbs and paws; inner membrane billows outward | Rev 1 renders | **Barely visible.** A pixel diff found only 2,692 changed pixels in the side view. The parameter changes were too small to survive subdivision smoothing at this camera distance. |
| 3 | Much stronger skull shaping: pronounced stop, overhanging brow, wide cheek and jaw mass, sagittal crest, eye tucked under the brow | Rev 2 pixel diff plus head close-up | Brow and crest now read, but the eye **still** looked like a ball stuck on the surface, and no pupil was visible |
| 4 | **Bug fix.** `BVHTree.FromBMesh` returns the BMesh's stored face normals, which are zero until `bm.normal_update()` is called. Socket and nostril displacement therefore moved vertices along a zero vector, the eyeball was centred on the surface, and the pupil collapsed into a flat disc inside the eyeball. Added normal updates and an assertion. | Numeric inspection of the saved file: the pupil's x-extent was 0.0 | Eye now sits in a carved socket with lids and a slit pupil under the brow |

Revisions 1–3 (`.blend` plus renders) are kept in [iterations/](iterations/). The final rev-4 renders are in [renders/](renders/). The extra base-mesh wireframe is [renders/extra/advanced_cage_05_wireframe.png](renders/extra/advanced_cage_05_wireframe.png).

## 4. Comparison with Experiment 1

| Criterion | Experiment 1 (primitive assembly) | Experiment 2 (lofting) | Verdict |
|---|---|---|---|
| Silhouette | Reads as a dragon, but the torso outline is lumpy (three balloons) and the joints bulge | Smooth, continuous S-line from snout to tail tip. The thigh and shoulder masses flow out of the trunk, and the wings have a scalloped trailing edge with billow. | **Exp 2 clearly better** |
| Volume and form | Every mass is a convex ellipsoid with hard intersection creases | Chest is broad and deep, the waist narrows, the hips are defined, all in one surface with no creases along the trunk. Elliptical, squarer sections give a sense of a back plane and a belly plane. | **Exp 2 clearly better** |
| Anatomy | Ball-jointed doll limbs; cartoon head with no sockets | Joint chains with elbow and heel knobs; digitigrade hind legs; a skull with stop, brow, crest, cheekbones, socket, lids and a jaw angle | **Exp 2 better**, but Exp 1's head is more *expressive* (bigger eyes and brows) even though it is cruder |
| Mesh and shading | 156 intersecting shells, 42 % buried faces, UV-sphere poles, open tube ends | Quad loops follow the anatomy (cage view); trunk is one closed shell; buried faces halved; 10 non-manifold edges | **Exp 2 clearly better** |
| Materials | Belly zones discontinuous across primitives | One continuous belly stripe from throat to tail; matching jaw underside; palette identical | **Exp 2 better** (same shader, cleaner zones) |
| Efficiency | 39 k triangles, of which about 40 % are hidden | 56 k triangles base and 171 k evaluated; wing bones are overbuilt | **Exp 1 lighter, Exp 2 better value per triangle.** Neither is game-budgeted. |
| Effort and reliability | Easy to write; 3 iterations | Much more code (curve, frame, loft, patch, UV-packing infrastructure); 4 iterations, including a silent bug | Exp 2 costs more to engineer, but builds faster (0.4 s) |

## 5. Remaining defects (honest list)

1. **Limb-to-body and neck-to-head junctions are still interpenetrations.** Flared roots hide the seam well, but the topology is not unified: about 21 % of faces are buried, and skinning at shoulders, hips and occiput would expose or clip geometry. Merging these needs bridging or remeshing.
2. **Limbs are still smooth tubes.** Sweeps cannot easily make muscle separation, tendons or bony planes, so the legs look rubbery. A ring seam is visible where each wrist enters its paw.
3. **The head is coherent but generic and small.** The visible eye is small (eyeball radius 2 cm, mostly covered by the lids) and the face is less expressive than Experiment 1's. The mouth is only a slit between two lofts (no lip line or teeth).
4. **Density is spent badly.** Ring spacing is uniform and does not follow detail. WingFrames alone is 52 k of the 171 k evaluated triangles, because subdivision was applied to thin bones that do not need it. The model is **not game-ready**: there is no triangle budget, no LOD, no rig check and no normal-map bake.
5. **Claw tips pass 6.6 mm below the ground plane** (bounding-box min Z = −0.0066 m).
6. **10 non-manifold edges** where the leading-edge membrane patch collapses to a point at the shoulder and wrist.
7. **Mechanical repetition.** All 39 dorsal spikes share one profile and are evenly spaced; the horn ridges are perfectly periodic.

## 6. Answer to the evaluation focus

Does better geometric construction give better volume, silhouette and surface continuity? **Yes, decisively, for everything a sweep can express.**
- The trunk, tail, neck, wings, horns and spikes improve dramatically over primitive assembly.
- Topology becomes rig-friendly, and UVs come almost for free from the loft parameterisation.

The method stops improving at **junctions** (limb roots, head–neck) and **non-tubular anatomy** (muscle groups, facial planes). There, explicit sweeps either interpenetrate or need hand-tuned displacement. Those two areas are exactly what sculpting (Experiment 3) and hybrid workflows (Experiment 5) should target.

Lessons for an AI modeling skill, from this run:
- **Verify that a change landed.** Revision 2 changed many parameters and had almost no visible effect after subdivision. Checking the pixel diff between revisions caught it.
- **Assert geometric invariants.** A zero-normal bug produced plausible-looking but wrong eyes for three revisions. Visual inspection noticed "something off" but only numeric inspection found the cause. A skill should check: non-zero normals, the magnitude of displacements actually applied, that sub-parts have non-zero extents, and ground contact.
- **Lofting is a strong automation primitive.** It is deterministic, parametric and fast (0.4 s), and it yields topology and UVs together.

## 7. Files

| File | Purpose |
|---|---|
| [dragon_advanced.py](dragon_advanced.py) | Reproducible build: `blender -b --factory-startup --python dragon_advanced.py` |
| [dragon_advanced.blend](dragon_advanced.blend) | Final model (revision 4) plus the benchmark rig |
| [renders/](renders/) | The 8 standard views, contact sheet, the [Exp 1 vs Exp 2 sheet](renders/exp1_vs_exp2.png), render log, and `extra/` (cage wireframe) |
| [geometry_stats.json](geometry_stats.json), [geometry_stats_cage.json](geometry_stats_cage.json) | Evaluated and base-mesh statistics |
| [build_log.json](build_log.json) | Build timing and construction counts |
| [iterations/](iterations/) | Revisions 1–3 `.blend` files and renders |
| `*_stdout.txt` | Raw Blender console logs |

Shared-tool additions made during this experiment: a `--cage` option on both `shared/render_views.py` and `shared/inspect_model.py`. Both are optional; the standard views are unchanged.
