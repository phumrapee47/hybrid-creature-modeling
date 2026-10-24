# Shared Character Specification — Small Fantasy Dragon

All five experiments build this same character. Numeric values live in
`benchmark_settings.json`; this document explains them.

## Concept
A small dragon for a high-quality **stylized fantasy adventure game**.
Carefully designed proportions, convincing volume, distinctive silhouette,
polished appearance. Not photorealistic, and must not read as a crude
collection of spheres, cylinders and cubes.

## Anatomy checklist
| # | Feature | Requirement |
|---|---------|-------------|
| A1 | Legs | Four legs; front legs plantigrade-ish, hind legs digitigrade |
| A2 | Wings | Two wings, half-raised, with arm, wrist, supporting fingers and membranes |
| A3 | Torso | Elongated; broad chest, narrower abdomen, defined hips |
| A4 | Neck | Curved (S-curve), transitions into chest and skull |
| A5 | Head | Distinct skull and muzzle, defined jaw, brow, eyes |
| A6 | Horns | Two, backward-curving |
| A7 | Tail | Long, tapered, deliberate curve, pointed tip |
| A8 | Dorsal spikes | Small, along neck, back and tail |
| A9 | Claws | Individual claws on every foot (+ wing thumb claws) |

## Appearance (material keys in `material_palette.py`)
| Key | Use | Colour |
|-----|-----|--------|
| `skin` | Main skin | Dark forest green |
| `belly` | Underbelly, throat, under-tail | Muted olive / lighter green |
| `horn` | Horns, dorsal spikes | Muted bronze |
| `claw` | Claws | Dark charcoal |
| `eye` | Eyes | Amber |
| `pupil` | Slit pupils | Near-black |
| `membrane` | Wing membranes | Dark green, subtle variation |

## World-space conventions (identical in every experiment)
* Units: metres, scale 1.0. Z is up.
* The dragon **faces −Y** (snout toward the front camera). Its left side is +X.
* It stands on the ground plane Z = 0, body centred on the world origin in X/Y.
* All dragon geometry lives in a collection named **`Dragon`**; the benchmark
  cameras, lights, floor and reference box live in **`Benchmark_Rig`**.

## Reference proportions (metres)
| Measure | Target |
|---------|--------|
| Snout tip → tail tip (along Y) | ≈ 2.9 (Y −1.15 … +1.75) |
| Wingspan (X, half-raised) | ≈ 2.6 |
| Top of wings (Z) | ≈ 1.55 |
| Top of skull (Z) | ≈ 1.30 |
| Shoulder height (Z) | ≈ 0.90 (top of back) |
| Chest width | ≈ 0.46 |
| Abdomen width | ≈ 0.36 |
| Hip width | ≈ 0.40 |
| Head length (back of skull → snout) | ≈ 0.45 |

Reference bounding box: X −1.40…1.40, Y −1.25…1.80, Z 0…1.65.

## Landmarks (approximate, used for camera targets and consistency)
| Landmark | Position (x, y, z) |
|----------|--------------------|
| Head centre | (0, −0.93, 1.21) |
| Chest centre | (0, −0.30, 0.66) |
| Abdomen centre | (0, 0.05, 0.62) |
| Hip centre | (0, 0.38, 0.65) |
| Front shoulder joints | (±0.21, −0.30, 0.56) |
| Hip joints | (±0.20, 0.40, 0.58) |
| Wing roots | (±0.12, −0.20, 0.86) |
| Tail tip | (≈0.30, 1.72, 0.13) |
