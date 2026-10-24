---
name: hybrid-creature-modeling
description: Build production-quality organic creatures and characters (dragons, beasts, monsters, animals, reptiles) in Blender with Python using a benchmark-proven hybrid pipeline - lofted cross-sections for proportions, voxel fusion for joints, closed-loop scripted sculpting for muscles and folds, procedural displacement and curve-sweep inserts for precise parts (eyes, lids, teeth, tongue, horns, claws, wing membranes), procedural scale/skin shaders driven by body-coordinate fields, and a deviation-gated game mesh with baked normal/colour/roughness/AO maps - all checked by standard renders and geometry measurements. Use this skill whenever the user asks to model, generate, sculpt, rebuild or add realism/anatomy/detail to a 3D creature, animal or character in Blender or bpy, asks for scales, teeth, skin, muscles or anatomically correct parts, or wants a game-ready creature asset, even if they do not name a technique.
---

# Hybrid Creature Modeling (Blender + Python)

Build organic creatures by assigning each technique to the size of detail it handles best, and prove every step with renders and measurements. The pipeline came out of a controlled five-method benchmark on one dragon (same spec, same render rig, same palette), followed by a sixth detail pass:

| Method tested | Score /60 | Verdict |
|---|---|---|
| **Hybrid (this skill)** | **46** | Best or tied best in all six categories |
| Advanced procedural lofting | 40 | Best silhouette per line of code; junctions overlap; no surface detail |
| Scripted sculpting only | 38 | Best surface anatomy; proportions stuck at blockout; heavy, no UVs |
| AI image-to-3D (repaired) | 33 | Fast and cheap, but coarse, no real eyes, colour/PBR drift, quota-limited |
| Primitive assembly | 22 | Blockout only |

**Generality test:** a bipedal raptor built with `creature_kit` from about 230 lines of data. Its first dry run passed; 4 defects found in the preview renders were fixed in data. The GUI build ran with 0 errors: all 28 strokes on target, a 32k-triangle body within 0.9 mm of the sculpt, 4K bakes, claws above the ground and 1.7 % buried surface (`examples/raptor/`).

Core idea: **proportions first (lofts), unification second (voxel fuse), anatomy third (sculpt + displacement + inserts), surface last (shaders + bake), and a verification gate after every stage.**

## Ground rules (always)

1. **Never claim success without evidence.** "Done" means the file reopens in a fresh Blender process, the renders exist and you have looked at them, and the measurements pass. Report failures with the actual output.
2. **One defect per fix, diagnose before fixing.** Measure the cause, not only the look of a render. A fix diagnosed from a render alone was wrong once in the benchmark and needed a further revision.
3. **Archive every full run** that you replace (`iterations/v1`, `v2`, ...) with its log, and keep the previous versions' files.
4. **Disclose substitutions.** If a requested technique is replaced (e.g. a shader instead of sculpted scales, Decimate instead of retopology), say so in the report.
5. **No installs, paid services, uploads or downloads without the user's explicit approval.** AI generation services are an optional side path (see the last section).
6. **Model against references, not from memory.** Before modelling, find the most realistic existing models of the creature and of the real animals it borrows from, and compare every iteration against them (step R). Internal gates only compare a model with its own previous version.
7. **Anatomy is checked as data, not by eye.** An open mouth exposes what a closed one hid. Measure head, jaw, limb and digit relations with numbers (checklist in step 1).

## Bundled files

- `scripts/creature_kit.py`: **the pipeline as a library.** A creature is a `Creature` subclass with data plus a few builders, and `ck.run(MyCreature(), __file__)` runs every stage, logging and gating as it goes. It includes:
  - `paw` (toes, raised toes, back toes, dewclaws);
  - ground-clamped `claw`;
  - `spikes_along`;
  - mouth profile, teeth and tongue;
  - eyes, cornea and lids;
  - body fields;
  - gated game mesh and bake;
  - dry-run and GUI run modes, with an honest exit code.
- `scripts/proc_mesh.py`: Catmull-Rom paths, superellipse lofts with bumps, patches, sphere/ellipsoid, UV packing and mirroring. Every Part has a `tip_t` vertex layer (0 at a sweep's start, 1 at its end).
- `scripts/sculpt_driver.py`: closed-loop sculpt strokes with real brushes (GUI only).
- `scripts/detail_materials.py`: procedural skin/scale, keratin, eye, cornea, membrane and tongue shaders. `build_all(palette=..., stripes=...)` sets the colours per creature.
- Rendering and checking:
  - `scripts/camera_setup.py` and `scripts/benchmark_settings.json`: the rig and reference. Override them per creature with a settings JSON (`Creature.settings` or `CREATURE_SETTINGS`).
  - `render_views.py`: the 8 standard views.
  - `render_details.py`: close-ups, from the settings file's `detail_views`.
  - `inspect_model.py`: stats from a fresh process.
  - `make_contact_sheet.py`: contact sheets (Pillow).
  - `material_palette.py`: the shared palette.
- `examples/raptor/`: **start here.** A bipedal raptor built with the kit (about 230 lines of data and builders) plus its settings, close-up views, renders and log. It was built correctly on the first dry run.
- `examples/dragon/`: **the benchmark dragon on the kit**, with the anatomy layer (26 volumes per side), the high-poly stage, wings, and settings with reference-style close-up views. Use it for any winged or quadruped creature.
- `scripts/scale_field.py`: **geometric scales** (Phase B). Level 1 plates and Level 2 scales are displacement of the high-poly surface, driven by the body fields. Turn them on with `Creature.scales = True` or a dict of overrides (step 7b).
- `scripts/reference_search.py`: finds realistic 3D models by other people to use as reference (step R). It reads public Sketchfab metadata anonymously, downloads nothing, and writes a candidate list plus a thumbnail contact sheet.
- `scripts/quality_metrics.py`: geometry-only measurements. Shader bump and normal maps are invisible to it.
  - mesh resolution;
  - relief bands: fine, medium, secondary;
  - with `--ref <name>_primary.blend`, the **added form**: how far the final sculpt stands off the primary lofts, in total and per region. Every kit build writes the primary file.
- `render_details.py --clay`: renders any close-up without materials. Forms must read in clay before any surface detail counts.
- `examples/dragon_detail.py`: the original long-form dragon (about 1,000 lines, written before the kit). Use it as a reference for wings, membranes, head scaling and jaw rebuilding.

## Quick start: a new creature

0. Gather references (step R): 2–3 realistic sculpts of the same kind of creature and 2–3 scans of the real animals it borrows from. Write the gap list before writing any data.
1. Copy `examples/raptor/` into the user's project folder (keep it a short path on Windows). Set the environment variable `CREATURE_KIT_DIR` to this skill's `scripts/` folder, then rename the class, `name` and `prefix`. Outputs go next to the creature script, never into the skill folder.
2. Write the data in this order:
   - the spine (snout to tail tip);
   - trunk stations;
   - head and jaw stations. Build the jaw closed, then rotate it about the hinge to open it, and check the jaw rules in step 1;
   - limb chains;
   - feet via `ck.paw`.
3. Fill in the hooks:
   - `build_base()`: lofts to be fused; mirror the limbs.
   - `anatomy(tree)`: muscle bellies, tendons, bony ridges and knobs (step 3b).
   - `field_chains()`: limb chains for the scale fields.
   - `strokes()`: phases → `sd.spec(..., target=mm)`.
   - `features(tree)`: eye, nostril and ear references via `ck.surface_hit(tree, axis_point, ck.lateral(up_deg, fwd_deg))`.
   - `mouth` / `eye` dicts.
   - `inserts(ctx)`: horns, spikes, claws (`ck.claw` for every entry in `self.toe_tips`), wings.
   - Class attributes: `palette`, `stripes`, and the `head_y`, `head_z`, `tail_y` region bands.
4. Settings JSON: the reference bbox, camera framing for the creature's size, a collection name, and 8 `detail_views` that target its own inserts.
5. Set `CREATURE_OUT_DIR` to a working folder: the high-poly file is about 300 MB, and builds must never write into the skill folder. Run `CREATURE_DRY_RUN=1 blender -b --factory-startup --python my_creature.py`. Then render previews with `CREATURE_SETTINGS=<json>` at 24 samples. Look at them, fix the data, and repeat.
6. GUI run, then the full renders, `inspect_model.py`, review, and archive or iterate.

## R. References: compare with the best existing models

Building from the prompt alone gives forms that are plausible but generic. In the benchmark, the Phase B dragon gained real anatomy and geometric scales and met most of its internal gates, yet next to a professional sculpt it read as slender and toy-like:
- stilt legs;
- a domed head;
- small wings;
- shallow scales that ignored the body's rows.

Only a reference shows what "realistic" means for each region.

**Two kinds of reference, both required:**

| Kind | What it gives | Where to find it |
|---|---|---|
| Real animals | Ground truth for anatomy, skin folds, scale size and rows, and how scales wrap muscles | Museum scans on Sketchfab (Natural History Museum Vienna, witmerlab, UF Herpetology, RISD Nature Lab), Smithsonian 3D, MorphoSource |
| Artist sculpts | The production bar for a fantasy creature: mass, plate design, horn sets, wing membranes | Sketchfab staff picks and most-liked sculpts in Characters & Creatures; ArtStation |

For a dragon, the real animals are crocodilians (dorsal scutes, flank rows, belly plates), monitor lizards (neck folds, bead scales), bats (wing membrane, finger bones), and big cats or horses (limb mass).

**1. Find.** Run the search script:
```
python scripts/reference_search.py --out <work>/refs --kind artist --query dragon wyvern "dragon sculpt"
python scripts/reference_search.py --out <work>/refs --kind real --query "komodo dragon" crocodile alligator
```
- It writes `reference_candidates_<kind>.json` and an `.html` contact sheet.
- The built-in browser may refuse `file://` pages. Serve the folder instead (`python -m http.server 8765 --directory <work>/refs`) and open `http://localhost:8765/`.
- The rank is popularity and polycount, not realism. Filter by eye: drop stylised models, humanoid "dragon girls", props and packs.

**2. Choose** 2–3 of each kind:
- the same body plan (four legs plus wings, wyvern, or serpent);
- realistic, not stylised;
- at least about 1M faces for sculpts, so close-ups hold;
- clay or a neutral material if possible, so the forms show.

**3. Look closely** in the browser, at the regions of your own close-up views:
- Open `https://sketchfab.com/models/<uid>/embed?autostart=1&ui_infos=0&ui_controls=0&ui_watermark=0&ui_hint=0` and wait about 20 s for the model to load.
- Double-click a part to orbit around it, then scroll to zoom.
- Capture full body, head, flank and shoulder, back, belly, limbs, wing and tail.
- Copy the screenshots to `<work>/refs/captures/<kind>_<model>_<region>.jpg`.

**4. Record** each reference in `<work>/refs/references.json`:
- name, author, URL, licence, kind;
- captures;
- observations per region, in words.

**5. Write the gap list:** per region, what the references have that the model lacks.
- Give each gap a measurable target where possible, for example "each wing at least as long as snout-to-hip", "flank scales in rows along the body rings", or "8–12 neck folds".
- Proportion gaps go into the data (step 1), never into the sculpt.
- The gap list is the next iteration's work list, ordered by how much each gap changes the read at 3 m.

**Result on the dragon (step R v1).** Gaps 1–2 were fixed in the data, measured on the high-poly mesh:
- forearm and shin +26–31%;
- tail base +21–26%;
- neck +14%;
- elbows 6 cm and knees 4 cm further out;
- wing reach 0.90 → 1.08× snout-to-hip;
- membrane area +43%, with knuckled bones and wrinkles.

Anatomy anchors and strokes follow the moved limbs through `follow_limbs`.

**Gap 3, the head (step R v2):**
- brow overhang past the eye 14 → 26 mm (target 30 missed);
- dome index 0.73 → 0.57;
- head added form p90 7.6 → 11.4 mm;
- a crown of 3 horns and 3 jaw spikes per side.

**Head pass 2 (step R v3):**
- main horns straightened: bend 0.21 → 0.02, 29° above horizontal, base radius 34 → 49 mm;
- head scales 13 → 9 mm and top plates 28 → 17 mm (dragon `scales` override), so the bony ridges read.

Still short of the reference: the brow (26 mm, target 30) and smaller, fewer crown spikes. Plates still cover the ridges, only smaller; there is no curvature mask.

**Rules:**
- **Reference, never copy.** Do not trace, import or reproduce a reference's geometry, textures or distinctive design. Take principles: proportions, how forms work, scale size and flow.
- **Viewing is free; downloading is not.** Viewing a public model in the browser is fine. Downloading a model file needs all three:
  - the user's approval;
  - a licence that allows it;
  - on Sketchfab, the user's own account. Never log in for them.

  Models that are editorial, store-only or without a download licence are view only.
- **Captures are third-party work.** Keep them in the working folder. Never commit them to a public repository or publish them; link to the model page with author and licence instead. Credit the authors in the report.
- **Measured comparison is not built yet.** Running `quality_metrics.py` on a downloaded reference mesh is untested. Until it is tested, comparisons are visual, and any reference proportion read off a screenshot must be called an estimate.

## 0. Environment and run modes

- Units are metres. +Z is up, the creature faces -Y, its left side is +X, and the ground is z = 0. Fix a reference bounding box and landmarks in the settings file before modelling.
- **Sculpt mode needs the Blender GUI.** Blender 5.2 crashes when sculpt mode is entered with `-b`. Run the build with a timer and quit at the end:
  ```
  blender --factory-startup --window-geometry 0 0 1400 1000 --python build.py
  ```
  ```python
  if DRY_RUN: tick()                      # headless test of everything except sculpt
  elif bpy.app.background: raise SystemExit("needs the GUI")
  else: bpy.app.timers.register(tick, first_interval=2.0)   # tick(): run(); write log; bpy.ops.wm.quit_blender()
  ```
- **Always provide a dry-run mode**, for example an environment variable that:
  - skips sculpting,
  - uses 512 px bakes,
  - writes to a temp folder.

  Run it headless first: it catches most bugs in about a minute. Render a few preview views from it before starting the GUI run. With the kit, set `CREATURE_DRY_RUN=1`.
- **Exit codes:** Blender's `quit_blender()` always returns 0. The kit calls `os._exit(1)` after writing the log if any error was logged, so scripted runs can trust the exit code.
- Environment guards:
  - If OptiX fails, fall back to CUDA, then CPU.
  - Windows paths over 260 characters break Blender's file writers and `--python` loading. Save and render to a short temp path, then move the file with a `\\?\` long path, and keep throwaway scripts in a short folder.
  - Render Cycles views before Workbench ones, because switching engines back and forth can exhaust a 4 GB GPU.
  - Wrap renders in try/except and fall back to CPU if the GPU fails.

## 1. Spec → anatomy data

Encode the creature as data before any geometry:
- a spine chain from the snout tip to the tail tip,
- head, jaw, limb, digit and wing chains,
- per-station cross-sections: `(width, top depth, bottom depth, superellipse exponent, bump amplitudes...)`.

Put proportion fixes in this data, never in the sculpt.

**Anatomy checklist** (verify numerically, not just by eye):

| Part | Rule | Benchmark lesson |
|---|---|---|
| Head vs neck | The head must read as heavier than the neck's top. | The benchmark head looked small, and scaling it ×1.12 about the skull/neck pivot fixed it. Scale every head-relative item with it: strokes, sockets, eyes, horns. |
| Lower jaw | Its tip ends within about 3% of head length behind the snout tip. At every station its half-width is 85–90% of the upper jaw's, and its depth is about half the snout's. | An inherited jaw that was 5 cm short and 60–69% wide was hidden while the mouth was closed, and obvious once it was opened. |
| Jaw hinge | Behind and below the eye, under the back of the skull. To open the mouth, rotate the jaw stations about the hinge before lofting. | 12° gives a readable open mouth. |
| Snout tip | Tapers. Avoid boxy exponents (about 3) at the front stations. | A boxy tip reads as a bulbous knob overhanging the jaw. |
| Teeth | Upper row at the jaw margin, lower row just inside it, each tooth curving back. Fangs in positions 2–3. Length ≤ 0.62 × the gap measured at that tooth. | |
| Eyes | On the sides in carved sockets under a brow ridge, with upper and lower lids. Predators have slit pupils. | The iris fills most of the visible eye. |
| Nostrils, ears | Nostrils are on top of the snout front. The ear opening (tympanum) sits behind the eye, above the jaw joint. | |
| Flyers | Deep keeled chest and broad shoulders (pectoralis, supracoracoideus). The wing is the forelimb: arm and forearm plus fingers. The membrane attaches to the flank and thigh. | |
| Limbs | Digitigrade hind feet. The forefoot has a raised dewclaw. Every claw tip must stay above the ground plane (z ≥ 0). | Claws were 6.6 mm below the ground until the hook drop was clamped. |
| Tail, spikes | The tail tapers continuously. Dorsal spikes grow and shrink along the spine and alternate major/minor with about ±8% seeded jitter. | |
| Folds, tendons | Skin folds at the axilla, groin, throat (gular) and wing root. Tendons at the Achilles and forearm flexors. A jaw muscle (masseter) behind the eye. | |

## 2. Primary forms: cross-section lofts (headless, deterministic)

Use `proc_mesh.Part.sweep(points, shapes, material, N, step, frame, hint, start, end, scale_fn, tip, bumps)`:
- **Path:** Catmull-Rom through the control points, sampled by arc length.
- **Ring:** a superellipse `(w, ap, an, n)` plus Gaussian radial bumps for features such as the brow, cheek and keel.
- **Frame:** `"h"` for horizontal bodies; `"hint"` with an axis for vertical limbs and teeth.
- **Ends:** `"cap"`, `"tip"` or `None`.

Rules:
- **One section tuple per control point.** Sections are interpolated by control-point index. Passing 4 sections for 9 points extrapolated a tongue into a metre-long slab. If the point count varies, resample the sections with `np.interp`.
- Add joint-flank control points at the elbow, knee and wrist so joints don't read as tubes.
- Parameter changes must survive subdivision. Verify each one with a pixel diff between before and after renders.
- Build the trunk, head, jaw, limbs, palms, toes, dewclaws, wing arm and elbow knob as lofts. Mirror the limbs.

## 3. Unification: subdivide → voxel remesh → crease removal

1. **Catmull-Clark level 2 on the joined lofts first.** Voxel remesh faithfully reproduces raw loft facets as stripes.
2. **Voxel remesh.** Set `voxel_size` to about half the smallest sculpted feature radius: 3.5 mm on a 3 m creature with 6–8 mm folds gives about 440k faces. Use adaptivity 0, fix poles, preserve volume, then `shade_smooth()`.
3. **Cavity-masked smoothing** removes interpenetration creases: `sculpt.mask_from_cavity(factor=2.5, blur_steps=3)`, then `sculpt.mesh_filter(type="SMOOTH", strength=1, iteration_count=30)`, then clear the mask.
4. Keep **thin parts out of the fusion**: wing fingers, membranes, teeth, tongue, claws, horns and spikes. Anything thinner than about 2 voxels erodes.

After `apply`-style operations, re-fetch `ob.data`: the old mesh reference is stale.

## 3b. Anatomy layer: secondary forms as fused volumes

Lofts give proportions but read as smooth tubes in clay. Muscles, tendons and bony landmarks are built as volumes anchored to the base surface, then fused, so they become one surface. Inflate strokes give soft blobs; volumes have origins, insertions and separations.

- **Spec:** `Creature.anatomy(tree)` returns a list of `dict(name, kind, a=(target, ray_dir[, reach]), b=(...), width, protrude, depth=0.45, n=8, tol=0.12)`, for the left side only (the kit mirrors them).

  | Kind | Shape along its length |
  |---|---|
  | `muscle` | Fusiform: tapers into tendons at both ends |
  | `tendon` | Narrow cord |
  | `ridge` | Flat top with soft ends (brow, zygomatic arch, ribs, crests) |
  | `knob` | Short and round. Avoid it where several volumes meet: it pinches into a nub |

- **Anchoring:** both ends are ray-cast onto the base lofts, the way features are. Each intermediate station is projected back onto the surface along the interpolated normal. Each station's centre sits `half-depth - protrusion` below the surface, so exactly `protrude` stands proud at the belly and both ends are buried.
- **Guards** (each skips the volume and logs why; it never guesses):
  - an anchor lands more than `tol` from its target. Head anchors aim from the skull axis, so use `tol` ≈ 0.16 there;
  - a projected station leaves the chord by more than `max(15 mm, 0.2 × chord)`. With an open mouth, lip-line volumes otherwise jump to the other jaw and bridge the gape;
  - a ray that starts inside another limb hits the wrong surface. Give those anchors a short `reach` (third tuple element).
- **Two-stage fusion:**
  1. Fuse the lofts.
  2. Run the base cavity fillet (30 iterations).
  3. Fuse the volumes in a second voxel remesh, with a light fillet of their own (`anatomy_fillet`, 14 iterations).

  Fusing everything at once let the 30-iteration fillet erase the muscle separations.
- **Size, for a 3 m creature** (exaggerated, as fantasy creature sculpts are):

  | Form | Protrusion | Width |
  |---|---|---|
  | Major limb and girdle muscles | 14–22 mm | 40–70 mm |
  | Bony ridges | 6–14 mm | 16–22 mm |
  | Brow | 20 mm | 30 mm |
  | Tendons | 5–6 mm | 12–14 mm |

  Muscles at 5–12 mm (Phase A v1) were invisible in clay. A `depth` of 0.6 gave steep sides that read as stuck-on ovals; 0.45 blends better.
- Drop the Inflate/Clay strokes for any muscle that a volume now builds; doubling the same form doubles it.

## 4b. High-poly stage

After the secondary sculpt at the base voxel size (3.5 mm), the kit keeps a copy of that mesh. It then subdivides the sculpt (`hipoly_subdiv`, Catmull-Clark: 450k → 1.8M faces, about 1.6 mm) and sculpts the `hipoly_phases` (tertiary folds and creases) on the dense mesh.
- Body fields are written before the subdivision, and the subdivision interpolates them.
- The kept mesh is the source for retopology/decimation. The bake reads the high-poly.
- Deliverables: `<name>_highres.blend` (high-poly sculpt with inserts, about 300 MB), `<name>.blend` (game version) and `<name>_primary.blend` (lofts only, the metric reference).

## 4. Sculpt: closed-loop strokes with real brushes (GUI)

Use `sculpt_driver.Sculptor(ob, log)` with `stroke(spec(...))`. What it does, and why each part matters:
- **Activates the brush asset:**
  ```python
  bpy.ops.brush.asset_activate(asset_library_type="ESSENTIALS",
      relative_asset_identifier="brushes/essentials_brushes-mesh_sculpt.blend/Brush/<Name>")
  ```
  It then verifies that the active brush has that name, and never sculpts with the wrong brush silently.
- **Sets the radius in pixels:** `brush.size`. The stroke element's `size` alone is ignored. It also disables unified size and strength.
- **Aims an orthographic viewport** facing the surface (`view` is the direction the camera looks). It ray-casts the stroke path onto the current surface and submits dabs with `bpy.ops.sculpt.brush_stroke(stroke=elements)`.
- **Closed loop:** it repeats passes until the measured peak displacement reaches about 75% of `target` mm (strength gain capped at 3×, at most 6 passes). Every stroke is logged: passes, achieved mm, result.

Brush choice:

| Purpose | Brush | Typical (3 m creature) |
|---|---|---|
| Junction fillet, polish | Smooth | r 30–60 mm, 2–3 passes, no target |
| Convex muscle masses (pectoral, deltoid, quadriceps, masseter) | **Inflate/Deflate** | r 20–45 mm, target 3–7 mm |
| Flat planes (scapula, neck muscle, ribs) | Clay | r 18–30 mm, target 2.5–4 mm |
| Brow ridge | Clay Strips | r ≈ 16 mm, target 4 mm |
| Bosses (horn base) | Blob | target 5 mm |
| Folds, creases (neck, gular, axillary, inguinal, wing root) | Crease Sharp | r 6–8 mm, target 2–2.5 mm |
| Tendons | Draw | r 6–7 mm, target 1.2–1.5 mm |

Rules:
- Order: junctions → secondary masses → polish → detail masses → tertiary folds and tendons.
- **Never use Clay on strongly convex limbs**: its plane flattening dents them at the stroke ends. Use Inflate.
- **Pass `target=` by keyword.** In the spec signature, the 7th positional argument is the target in mm, not a pass count.
- Points only need to be near the surface, but `view` must face it. Grazing rays miss, so for undersides (belly, throat) look along the body frame's dorsal axis.
- Accept a stroke if it achieves 70–160% of its target. Re-aim the strokes outside that range.

## 5. Precise features: procedural displacement

Ray-cast from inside the head axis outward to find each reference point and its normal, **before** carving anything. Then displace the vertices within a radius along the normal:
- a quartic falloff for the depression,
- a Gaussian rim,
- an optional upper-rim boost, which forms the lid or brow.

Mirror the left-side result to the right.

Benchmark values on a 0.5 m head:

| Feature | Radius | Depth | Rim | Upper boost |
|---|---|---|---|---|
| Eye socket | 27 mm | 10 mm | 5.6 mm | 2.5 |
| Nostril | 12 mm | 10 mm | 2.5 mm | – |
| Ear opening | 12 mm | 3.5 mm | 1.2 mm | – |

## 6. Inserts (separate objects)

General rules:
- **Create every bmesh custom-data layer before creating geometry.** Adding a layer later invalidates all Python element references (`ReferenceError: BMVert has been removed`).
- **Pack UVs before `remove_doubles`.** Welding collapses cap poles and invalidates the stored island faces.
- Recalculate normals before converting a part to a mesh. Assign materials from your shader dictionary.

Parts:
- **Eyeball:** a UV sphere, sunk so it protrudes about 3 mm from the pre-socket surface. Write a `FLOAT_VECTOR` attribute `eye_local` (side, up, gaze; unit radius) for the iris shader.
- **Cornea:** a spherical cap (about 52°) at 1.035 × the eye radius. Use a **Fresnel-mixed glossy + transparent** shader, not refractive glass: glass blocks shadow rays and the iris renders dark.
- **Eyelids:** two spherical caps at 1.07 × the eye radius, solidified to 2.4 mm.
  - Upper lid: axis tilted 20° from up toward the gaze, cap angle about 48°.
  - Lower lid: axis tilted 15°, cap angle about 42°.
  - The back of each cap sinks into the head.
- **Mouth profile:** for about 26 stations along the head axis:
  1. Ray down from inside the head. The first exit, which faces down, is the palate. Accept it only if it lies within 1.25 × the local underside depth.
  2. Ray down again. A hit facing up is the jaw floor.
  3. Keep only the contiguous open stations, at least 6 mm apart, from the front backwards.
- **Teeth:** for each tooth station:
  1. Find the jaw half-width with a horizontal ray, and place the tooth at 0.8 of it.
  2. Ray from the mid-gap height to the jaw margin to place the root, embedded 3.5 mm.
  3. Measure the opposite gap and cap the length at 0.62 × gap. If no opposite jaw lies below the tooth, use the nominal length.
  4. Curve the tooth back (+Y in the creature frame) and flatten it sideways.

  Lower teeth are offset half a spacing from the upper ones.
- **Tongue:** points ray-cast onto the jaw floor along the midline, only where the gap is at least 20 mm, raised 4.5 mm. Fork the tip into two diverging prongs.
- **Horns, spikes, cheek spikes:**
  - **Horns:** sweeps with a periodic bulge (`scale_fn`) for growth ridges.
  - **Dorsal spikes:** placed by ray-casting down the dorsal axis of the trunk path, sized by a curve along it, alternating major/minor.
- **Claws:** a hooked sweep whose drop is clamped to `(base.z - 1.5 mm) / length`, so the tip stays above the ground. Add a dewclaw on the inner back of the wrist.
- **Wing:** finger sweeps plus membrane patches.
  - Membranes are Coons/ruled patches between finger paths and the arm/flank lines.
  - **Panels that share an edge must sample it identically**, or the chords diverge and leave a crack.
  - Then weld, dissolve degenerate faces, solidify to 6 mm and smooth.

## 7. Surface detail: body-coordinate fields + procedural shaders

Don't retopologise for UVs just to orient scales. Write per-vertex fields on the high-res body and let the shaders read them.

**Fields.** For each vertex, find the nearest segment of every chain: spine, front limbs, hind limbs, wing arms, toes and palms, densified to 6–30 mm segments.
- `body_st = (s, t)`:
  - `s` is the arc length along the nearest chain.
  - `t` is `|angle from the chain's ventral direction| × distance`. It is mirror-symmetric, so neither midline has a seam.
- **Membership** = `1 - smoothstep(0.80, 0.95, d_nearest / d_second_group)`. Oriented patterns fade to isotropic scales wherever two chains compete, which hides the discontinuities at limb, neck and tail roots.
- Region weights:

  | Weight | Definition |
  |---|---|
  | `w_up` | Countershading (0.5 + 0.5 × radial · up) |
  | `w_belly` | Ventral 43–57° × spine membership |
  | `w_dorsal` | Dorsal band |
  | `w_tail` | y beyond the hips |
  | `w_head` | Head region |
  | `w_foot` | Toe membership × top side |
  | `w_mouth` | Surface **seen from the mouth's inner axis and facing it** (ray visibility plus facing ≥ 0.05–0.35) |
  | `w_lip` | Band within 4–16 mm of the mouth surface |

**Shader recipes** (`detail_materials.py`). Sizes are for a 3 m creature: scale them with body length.

| Region | Pattern | Technique | Size |
|---|---|---|---|
| Flanks, limbs | Granular, domed | 3D Voronoi distance-to-edge in object space (no seams) | 8 mm |
| Back | Keeled dorsal scales | 2D Voronoi on `body_st` plus a keel ridge from the F1 position | 22 × 18 mm |
| Belly, throat | Transverse ventral scutes | Brick on (t + 0.3, s), one brick across | 34 mm rows |
| Tail | Whorls | Brick on (t, s), offset rows | 18 × 20 mm |
| Head | Plates | 3D Voronoi, randomness 0.75 | 11 mm |
| Toes | Transverse scutes | Brick on toe `body_st` | 9 mm rows |
| Lips | Labial scales | Brick on object (y, z) | 12 × 11 mm |
| Mouth | Smooth wet gums | Gum colour, roughness 0.22, coat 0.5 | – |

Look rules from the review iterations:
- **Scales are domed, not flat plateaus.** Use smoothstep(0, 0.22–0.30) on the edge distance. Narrow plateaus read as cracked mud.
- Keep groove darkening ≤ 25% and the bump distance about 1.2 mm.
- Add per-scale tint (F1 cell colour ±8%) and large blotches (noise ±12%).
- Countershading: about ×1.15 on the low flank, ×0.78 along the back.
- **Keratin** (horns, spikes, claws, teeth):
  - Base-to-tip colour along `tip_t`, and matte (coat ≤ 0.1, roughness about 0.46) for horns.
  - Growth rings only on horns (`sin(tip_t × 2π × 22)`, fading toward the tip). On small spikes, rings look like screw threads.
  - Longitudinal fibre striations from a UV wave across the sweep.
  - Teeth get slight subsurface scattering.
- **Eye iris:**
  - Radial noise streaks and a dark limbal ring.
  - A vertical slit pupil (x / 0.07, y / 0.55) on the front hemisphere.
  - A dark sclera hidden in the socket.
- **Membrane:**
  - Main veins as thin crests of a distorted wave running along the fingers. Plain Voronoi edges read as a leaf-cell network.
  - Faint Voronoi capillaries at about 35%.
  - Translucent mix of 0.3. Judge it against a back light.
- Keep palette colours as the base for every material, and add new palette keys explicitly (for example tooth, gum, tongue).

## 7b. Geometric scales (Phase B): Levels 1–2 as real geometry

Shader-only scales vanish in clay and leave the silhouette smooth. With `Creature.scales` set, `scale_field.apply` displaces the high-poly surface after the tertiary sculpt.

**Cells.** Every scale is a cell of a jittered Worley lattice:
- oriented scales use girth-normalised body coordinates: `body_u` integrates `ds / girth` along each chain, and `t / girth` runs around it, so scales shrink with the body toward the neck, tail tip and ankles;
- isotropic scales use object space.

**Edge distance needs two passes:**
1. find the nearest feature point;
2. take the minimum bisector distance over the points around *that point's* cell.

The one-pass "second-nearest" shortcut jumps by half a cell and would tear the surface. Unit-test continuity with `max |Δedge| ≈ sample spacing` before any build.

**Profiles:**

| Profile | Shape |
|---|---|
| **Pillow** | Rounded edges falling into the groove |
| **Shingle** | Rises toward the posterior (+s: tail-ward, or distal on limbs) edge and drops steeply there, so rows read as overlapping. Normal displacement cannot undercut: overlap is approximated, so say so |
| **Keel** | A ridge along the scale's long axis |

Each cell also gets ±15% random height.

**Default layers** (for a 3 m creature; `size_scale` rescales them):

| Level | Region (weight) | Pattern | Size | Height |
|---|---|---|---|---|
| 2 | Everywhere (base) | Granular, 3D | 10 mm | 1.5 mm |
| 2 | Limbs, all round (`w_limbdir`) | Oriented rows overlapping distally | 16 × 14 mm | 1.5 mm |
| 1 | Outer limbs (`w_limb`) | Oriented plates | 28 × 24 mm | 2.6 mm |
| 2 | Back and neck (`w_dorsal`) | Keeled imbricate | 24 × 20 mm | 2.6 mm |
| 1 | Paravertebral rows (dorsal arc 12–85 mm × girth) | Keeled osteoderms | 44 × 32 mm | 5 mm |
| 1 | Belly (`w_belly`) | Transverse plates in rows | 34 mm rows | 2.2 mm |
| 2 | Tail (`w_tail`) | Staggered whorls | 20 × 18 mm | 2 mm |
| 2 + 1 | Head (`w_head`) | Plates; large cranial plates on top | 13 mm; 28 mm | 1.5 mm; 3 mm |
| 2 | Toes (`w_foot`) | Transverse scutes | 10 mm rows | 1.2 mm |
| 2 | Lips (`w_lip`) | Labial scales | 12 × 11 mm | 1 mm |
| – | Mouth (`w_mouth`) | None | – | – |

**Rules:**
- **Resolution:** at the 1.6 mm high-poly, Level 2 scales smaller than about 8 mm turn to mush. Leave those to Level 3 (shader).
- **Material:** with geometric scales the material switches to `GEO_SCALES` mode. Colour, groove darkening and roughness read the real `scale_h` and `scale_tint`, and the bump carries only Level 3 micro relief (0.35 mm). Shader patterns no longer fight the geometry.
- **Game mesh:** it is built from the pre-scale mesh, and the scales go into its normal map. The deviation gate therefore measures against the **pre-scale** surface; the log also records the deviation to the scaled surface, for information.

## 8. Game version

1. **Retopology gate:** QuadriFlow (target about 12k faces) plus shrinkwrap. Accept it only if every region (head, toes, tail, wing arm, rest) stays within **max 12 mm and mean 2 mm** of the sculpt. QuadriFlow silently lost the tail and fingers in the benchmark; the gate caught it.
2. **Fallback:** Decimate (collapse, triangulate) to 24–32k body triangles. The benchmark reached max 1.5 mm and mean 0.1 mm.
3. Remove the field attributes from the low mesh. Run Smart UV project (angle 1.15 rad, island margin 0.003) and shade smooth.
4. **Bake selected-to-active** from the high-res body with its detail shader (cage extrusion 0.015, max ray 0.05):

   | Map | Bake type | Size | Samples | Margin | Colour space |
   |---|---|---|---|---|---|
   | Normal | NORMAL, tangent | 4096 | – | 16 px | Non-Color |
   | Colour | DIFFUSE, `pass_filter={"COLOR"}` | 4096 | – | 16 px | sRGB |
   | Roughness | ROUGHNESS | 2048 | – | 8 px | Non-Color |
   | AO | AO | 2048 | 64 | 8 px | Non-Color |

   The normal bake includes the shader bump. Make the target image node active before each bake, and pack the images.
5. Game material: colour × AO → Base Color; roughness map; normal map node.
6. Benchmark results:
   - Body: 32k triangles. Inserts: about 44k triangles, which is heavy because of the eyelid caps and wing fingers. Total 76.5k.
   - The bakes took about 40 s on an RTX 4050.
   - Known gap: the body has no edge loops for skinning. The next thing to test is shrinkwrapping the subdivided loft quad cage onto the sculpt, which gives rig-friendly loops and UVs.

Inserts keep their procedural materials. Before shipping to an engine, bake them or convert `tip_t` to vertex colours, and say so in the report.

## 9. Verification loop (every iteration)

1. **Dry run headless**, render previews (24 samples), fix, then run in the GUI.
2. **Read the build log**:
   - no errors;
   - every stroke within its target band;
   - mouth stations found;
   - teeth and tongue counts;
   - claw drop values;
   - QuadriFlow gate result and decimation deviation;
   - bake results and the mean pixel values (a black or empty bake is a failure).
3. **Measure the forms:** run `quality_metrics.py --ref <name>_primary.blend` on the high-poly. The added form (90th percentile, per region) must rise when anatomy work is added; flat regions show as near 0. Do not use a whole-body relief percentile for muscles: it is dominated by thin parts and could not see 15 mm muscles (Phase A v2 measured *lower* than the baseline while the clay showed clear gains).
4. **Reopen each .blend in a fresh process** (`inspect_model.py`) and check:
   - evaluated triangles;
   - shells;
   - non-manifold edges (expected only on deliberate open caps);
   - buried surface %;
   - bounding box against the reference box;
   - lowest z ≥ 0.
5. **Render the 8 standard views** with the identical rig: front and side ortho clay, three-quarter material, head close-up, wireframe, silhouette, three-quarter clay, rear three-quarter.
6. **Render clay close-ups first** (`render_details.py --clay`): head, shoulder and wing, forelimb, hind limb, flank. Then render the 8 material close-ups: eye, open mouth, flank scales, belly, forefoot, back-lit wing, tail, horn. Camera targets come from the model's own inserts, so before/after shots frame the same part.
7. **Compare with the references** (step R). Put each clay close-up next to the reference capture of the same region: `make_contact_sheet.py --images ours.png ref.jpg ... --labels ...`. Per region, check:
   - mass and silhouette;
   - secondary forms (muscles, folds);
   - scale size and flow;
   - plates and spikes.

   Update the gap list. A region that passes every internal gate but still loses clearly to the reference is not done.
8. **Look at every image yourself.** Build contact sheets and before/after sheets (previous version vs new). Ask:
   - Do the jaws match?
   - Do the scales read as scales at 1 m, not as noise or cracks?
   - Is anything floating, intersecting, or below the floor?
   - Do the patterns have seams at the junctions?
   - Is the iris lit?
   - Do the veins read as veins?
9. Fix the top 1–3 defects, taken from the reference gap list first. Archive the replaced run in `iterations/vN`. Repeat.

## 10. Pitfalls already paid for

| Symptom | Cause | Fix |
|---|---|---|
| Blender crashes entering sculpt with `-b` | Background mode | GUI run with a timer, plus a dry-run mode for the rest |
| Stroke has no effect / wrong radius | Element `size` ignored | Set `brush.size` in px and disable unified size |
| Stroke smaller than the voxel | Sub-voxel effect | Closed-loop target depth, finer voxel |
| Stripes along the limbs after fusion | Raw loft facets | Subdivide before the voxel remesh |
| Faceted voxel mesh | Flat shading | `shade_smooth()` |
| Eyes or inserts in the wrong place, plausibly | `BVHTree.FromBMesh` without `bm.normal_update()` (zero normals) | Call `normal_update()`, assert the normal length is > 0.5 |
| `ReferenceError: BMVert has been removed` | Layer added after geometry | Create layers in the Part constructor |
| Giant slab / exploded loft | Fewer sections than control points | One section per control point |
| Teeth or tongue misplaced | `np.interp` with descending x | Keep profiles in ascending y |
| Strokes far too strong or weak | Positional target vs passes confusion | Keyword `target=` / `passes=` |
| Retopology lost the tail or fingers | QuadriFlow on thin parts | Per-region deviation gate plus Decimate fallback |
| Crack in the wing membrane | Shared edge sampled at different counts | Identical sampling on shared edges |
| Claws through the floor | Fixed hook drop | Clamp the drop by base height |
| Lower jaw short and narrow | Data built for a closed mouth | Jaw rules in step 1; open the mouth in the dry run early |
| Dark eye under the cornea | Refractive glass blocks shadow rays | Fresnel glossy over transparent |
| Skin looks like cracked mud | Flat-topped Voronoi plateaus, heavy grooves | Domed profile, ≤ 25% groove darkening |
| Ribbed "screw" spikes | Horn growth rings on small spikes | A separate spike material without rings |
| Veins look like plant cells | Voronoi edges as main veins | Wave crests along the fingers plus faint capillaries |
| File won't save, script won't load | Windows path > 260 characters | Temp path then move; short script folder |
| Stripes or bands come out about 3× too dense | The Wave texture computes `sin(20 · scale · x)` | `scale = 2π / (20 · period)` |
| Thighs look like slabs from the front | The first thigh station is above the back line | Keep the thigh top below the hip's dorsal surface; widen the hips |
| Blender can't open a `.blend` or `--python` script in a deep folder | Paths over 260 characters (renders included) | Build and render from a short working folder (the kit warns); copy the results back |
| Render crash after switching engines | 4 GB GPU memory | Cycles views first, Workbench last; CPU fallback |
| A skin-coloured column bridges the open jaws | An anatomy volume's surface path jumped across the gape | Path guard (skip the volume); keep lip-line volumes out of open mouths |
| A pinched nub at the knee | A `knob` where three volumes meet | Leave the knee to the loft, or use a broad low `muscle` |
| Muscles look like stuck-on ovals | Cross-section too deep (steep sides) | `depth` 0.45, two-stage fusion with an anatomy fillet |
| Anatomy volumes vanish after fusion | Base fillet (30 iterations) smoothed their separations | Fuse the volumes after the base fillet |
| Relief metric unchanged although the clay shows muscles | Whole-body smoothing percentile is dominated by thin parts | Added form against `<name>_primary.blend`, per region |
| Scales tear along lines | One-pass Worley edge distance ("second nearest") is discontinuous | Two-pass edge distance; test continuity numerically |
| Tail scales the same size at the tip as at the base | Lattice in raw arc length | Girth-normalised `body_u` and `t / girth` per chain group |
| Limb scales look like cracked leather | Isotropic cells on limbs | Oriented rows along the limb chain, overlapping distally |
| Game mesh "deviates" by up to 9 mm after scales | Gate measured against the scaled surface | Gate against the pre-scale surface; scales live in the normal map |
| A wing "looked" 0.6x the body next to a reference; measured, it was 0.9x | Proportions read off a perspective screenshot | Measure your own model (sections, reach, area) before and after; call reference numbers estimates |
| Thicker or re-posed limbs leave anatomy volumes and strokes behind | Anchors are absolute points | Keep the old chain as `*_B3`, derive the new one, and carry nearby anchors with it (`follow_limbs` in the dragon example) |
| Dark marks on a membrane after raising its grid density | Patches sharing an edge sampled it differently (48 vs 36), so `remove_doubles` could not weld the seam and the sheets overlapped | Sample shared edges with one count (`N_FINGER`, `N_ARM` in the dragon); check layering by ray-counting sheets along the normal |
| A stronger brow only made the skull more domed | The brow bump sat at 55° from horizontal, above the eye, so it raised the top | Put the brow edge just above the eye (38° for an eye at 16°) and measure the overhang past the eye |
| A tooth root lands outside the cheek | A widened cheek moved the jaw-width ray | Bound the tooth row by the inner cheek wall (kit does this) |

## 11. Reporting

Write `report.md` per version with:
- the techniques used per detail size, and every substitution disclosed;
- what changed since the previous version, and why (the measured defect);
- metrics: triangles, objects, materials, file sizes, timings, stroke log summary, gate and deviation results, bake sizes and times;
- render and contact-sheet links;
- known limitations.

Scores are judgements: state about ±1 uncertainty, and never use polygon count as a quality proxy.

## Optional: AI image-to-3D side path

Use it only with explicit user approval, on free tiers, and with no uploads of private material without consent. It is good for quick concepts or distant LODs, not as the primary method:
- it reconstructs a supplied design;
- it lacks real eyes and sockets;
- it drifts colours and PBR flags;
- access is quota-limited.

Repair the result before use:
- weld the UV-seam splits;
- set the PBR flags (non-metal) and smooth shading;
- align region colours to the palette with capped gains;
- gate it by the same checks as step 9.

Never present it as procedural modelling, and never substitute it silently.
