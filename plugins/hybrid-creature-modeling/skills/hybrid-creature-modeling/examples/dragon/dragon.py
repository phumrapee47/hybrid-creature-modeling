"""Dragon - the benchmark dragon (Exp 6 v2) on creature_kit, plus the Phase A anatomy layer.

Shape data, strokes and wing construction are copied verbatim from examples/dragon_detail.py (Exp 6 v2, which
stays unchanged as the long-form reference). New here:
  * anatomy(): 29 surface-anchored volumes per side - skull landmarks (brow, zygomatic arch, nasal and parietal
    ridges), masseter, neck muscles, pectoralis, deltoid, biceps/triceps, forearm, olecranon, scapula spine, ribs,
    iliac crest, quadriceps, hamstrings, gastrocnemius, patella, caudofemoralis, Achilles and flexor tendons,
    dorsal flight muscle. They replace the Exp 6 Inflate/Clay "muscle" strokes listed in REPLACED_BY_ANATOMY.
  * high-poly stage (kit): tertiary folds are sculpted on the subdivided mesh.
  * step R v1 (reference comparison): heavier limbs, neck and tail base, sprawled elbows and knees, wings 1.2x with
    thicker knuckled bones and wrinkled membranes. The Phase B v3 values stay in the data as *_B3 for comparison.
  * step R v2 (reference gap 3, the head): flatter, angular cranium, heavy brow over the eye, cheek and jaw plates,
    a crown of horns behind the main horns, spikes under the jaw, thicker main horns.
  * step R v3: main horns thick, swept back and nearly straight; smaller head scales and plates between the ridges.
  * step R v4 (remaining benchmark gaps): neck skin rolls, flank scales in rows, deeper scales, dorsal scutes in
    transverse rows, heavier brow, lower cranium, larger horn crown and cheek spikes, masseter above the gape.
  * v1.3-B: horns, spikes and claws sit in skin collars (insert_collars); limb anchors use ck.follow_chains.
  * v1.3-C/D: scales half as high at limb joints (joint_relief); matte claws, enamel teeth and subsurface skin
    through surface_plan material variants.

  GUI:     blender --factory-startup --window-geometry 0 0 1400 1000 --python dragon.py
  Dry run: CREATURE_DRY_RUN=1 blender -b --factory-startup --python dragon.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("CREATURE_KIT_DIR") or os.path.normpath(os.path.join(HERE, "..", "..", "scripts")))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import creature_kit as ck  # noqa: E402
import proc_mesh as pm  # noqa: E402
import sculpt_driver as sd  # noqa: E402
from creature_kit import V, X, Y, Z, SIDE, TOP, BEHIND, dirn, rad, mx, surface_hit, arc_at_u, lateral  # noqa: E402,F401

HEAD_SCALE, HEAD_PIVOT = 1.12, Vector((0.0, -0.75, 1.20))
JAW_OPEN_DEG, JAW_HINGE = 12.0, Vector((0.0, -0.80, 1.16))


def hx(p):
    """Head enlargement about the skull/neck pivot."""
    return HEAD_PIVOT + (V(p) - HEAD_PIVOT) * HEAD_SCALE


def jaw_open(p):
    h = hx(JAW_HINGE)
    return h + Matrix.Rotation(rad(JAW_OPEN_DEG), 3, "X") @ (V(p) - h)



# =========================================================================== shape data (Exp 2 rev 4 / Exp 5)
TRUNK_PTS = [(0, -0.80, 1.19), (0, -0.73, 1.115), (0, -0.67, 1.005), (0, -0.61, 0.895), (0, -0.51, 0.795),
             (0, -0.36, 0.72), (0, -0.18, 0.685), (0, 0.05, 0.655), (0, 0.30, 0.67), (0, 0.50, 0.655),
             (0, 0.74, 0.58), (0.04, 1.00, 0.45), (0.13, 1.26, 0.30), (0.22, 1.50, 0.19), (0.30, 1.73, 0.13)]
# chest stations 4-6 enlarged (Exp 5 values 0.130/0.110/0.150, 0.215/0.200/0.260, 0.205/0.205/0.245):
# a flier needs a deep keel chest and broad shoulders for the pectoral and supracoracoideus muscles
TRUNK_SHAPES = [(0.062, 0.070, 0.072, 2.0, 0.0, 0.0), (0.058, 0.062, 0.070, 2.1, 0.0, 0.004),
                (0.066, 0.066, 0.080, 2.2, 0.0, 0.006), (0.088, 0.082, 0.105, 2.2, 0.0, 0.007),
                (0.136, 0.116, 0.158, 2.3, 0.005, 0.008), (0.228, 0.220, 0.276, 2.5, 0.020, 0.010),
                (0.215, 0.222, 0.255, 2.5, 0.015, 0.012), (0.165, 0.190, 0.175, 2.4, 0.0, 0.012),
                (0.190, 0.200, 0.175, 2.5, 0.0, 0.012), (0.140, 0.150, 0.130, 2.3, 0.0, 0.010),
                (0.095, 0.100, 0.085, 2.2, 0.0, 0.008), (0.066, 0.068, 0.058, 2.1, 0.0, 0.006),
                (0.043, 0.044, 0.038, 2.0, 0.0, 0.004), (0.024, 0.025, 0.021, 2.0, 0.0, 0.002),
                (0.003, 0.003, 0.003, 2.0, 0.0, 0.0)]
_HEAD_PTS = [(0, -1.165, 1.168), (0, -1.135, 1.174), (0, -1.05, 1.180), (0, -0.97, 1.190), (0, -0.905, 1.212),
             (0, -0.845, 1.222), (0, -0.785, 1.218), (0, -0.745, 1.206), (0, -0.722, 1.198)]
# v2: snout stations 1-2 slimmer and less boxy (v1/Exp 5: 0.044/0.040/0.030 n2.6, 0.056/0.046/0.036 n3.2 read as a
# bulbous knob overhanging the jaw once the mouth was open)
_HEAD_SHAPES_B3 = [(0.012, 0.012, 0.012, 2.0, 0.0, 0.0, 0.0), (0.038, 0.034, 0.028, 2.5, 0.0, 0.0, 0.0),
                   (0.052, 0.044, 0.034, 2.8, 0.0, 0.0, 0.0), (0.066, 0.056, 0.040, 3.0, 0.006, 0.004, 0.0),
                   (0.086, 0.082, 0.050, 2.8, 0.042, 0.010, 0.006), (0.108, 0.096, 0.064, 2.6, 0.014, 0.034, 0.010),
                   (0.104, 0.090, 0.070, 2.4, 0.004, 0.030, 0.008), (0.070, 0.066, 0.058, 2.2, 0.0, 0.006, 0.0),
                   (0.008, 0.008, 0.008, 2.0, 0.0, 0.0, 0.0)]
# Step R v2. Measured on the R v1 high-poly: dome index 0.73 (cranium height above the eye / half-width at eye level),
# brow 14 mm past the eye; the reference skull is low and angular with a heavy brow shading the eye. Cranium top
# (ap) lowered 12-17 % at stations 4-7, brow bump (index 4, 55 deg) raised and carried back over the temple, midline
# top bump (index 6) made a shallow groove between the brows; widths, jaw-side depths (an) and exponents unchanged so the mouth profile is untouched.
_HEAD_SHAPES = [(0.012, 0.012, 0.012, 2.0, 0.0, 0.0, 0.0), (0.038, 0.034, 0.028, 2.5, 0.0, 0.0, 0.0),
                (0.052, 0.044, 0.034, 2.8, 0.0, 0.0, 0.0), (0.066, 0.056, 0.040, 3.0, 0.030, 0.004, 0.0),
                (0.086, 0.068, 0.050, 2.8, 0.066, 0.010, -0.006), (0.108, 0.068, 0.064, 2.6, 0.046, 0.040, -0.008),
                (0.104, 0.066, 0.070, 2.4, 0.014, 0.036, -0.004), (0.070, 0.058, 0.058, 2.2, 0.0, 0.006, 0.0),
                (0.008, 0.008, 0.008, 2.0, 0.0, 0.0, 0.0)]
# v2 lower jaw. The Exp 2 jaw ended 4.7 cm (5.3 cm scaled) behind the snout tip and was 59-69 % of the upper jaw's
# width: invisible with the mouth closed, wrong once open. Reptile mandibles (crocodilians, monitors) reach the snout
# tip and carry their tooth row just inside the upper one, so: tip 1.3 cm behind the snout, width 86-89 % of the
# upper jaw at every station, depth kept at roughly half the snout (the upper skull also holds nasal passages/eyes).
_JAW_PTS = [(0, -1.152, 1.134), (0, -1.128, 1.130), (0, -1.05, 1.127), (0, -0.97, 1.129), (0, -0.89, 1.136),
            (0, -0.815, 1.150), (0, -0.79, 1.158)]
_JAW_SHAPES = [(0.012, 0.010, 0.010, 2.0), (0.034, 0.018, 0.016, 2.6), (0.048, 0.020, 0.022, 2.8), (0.058, 0.023, 0.028, 2.7),
               (0.078, 0.027, 0.036, 2.6), (0.094, 0.034, 0.050, 2.4), (0.012, 0.012, 0.012, 2.0)]
_HORN_PTS_B3 = [(0.042, -0.80, 1.265), (0.058, -0.755, 1.315), (0.083, -0.67, 1.352), (0.103, -0.575, 1.36),
                (0.115, -0.495, 1.335), (0.119, -0.45, 1.295)]
# R v3: the B3 horn rose and curled down at the tip like a goat's. The reference horns are thick, swept back and
# nearly straight: about 29 deg above the horizontal, slope 0.69 -> 0.50 -> 0.56 along the length (a slight lift)
_HORN_PTS = [(0.042, -0.80, 1.262), (0.056, -0.745, 1.300), (0.074, -0.665, 1.345), (0.090, -0.585, 1.385),
             (0.102, -0.515, 1.420), (0.110, -0.465, 1.448)]
_HORN_R = [0.044, 0.038, 0.030, 0.021, 0.012, 0.002]   # R v3: thick to near the tip (R v2: 0.036 ... 0.007; B3: 0.030 ... 0.006)
# R v2 horn crown: smaller horns on the back rim of the skull, behind and below the main horns and above the ear
# (ear opening at 8 deg up, y -0.775): (y, degrees up from lateral, length) in head coordinates
# R v4: the reference crown has more and larger horns: four per side, 20 % longer (R v2/v3: 75/65/50 mm)
CROWN = [(-0.790, 38, 0.092), (-0.770, 26, 0.080), (-0.750, 34, 0.066), (-0.730, 22, 0.052)]
# R v2 spikes under the lower jaw, behind the tooth rows: (y, z of the jaw axis, length)
JAW_SPIKES = [(-0.90, 1.134, 0.045), (-0.86, 1.140, 0.055), (-0.82, 1.148, 0.048)]   # dry run 1: 28-34 mm


def _scale_shape(sh):
    return tuple(v * HEAD_SCALE if i != 3 else v for i, v in enumerate(sh))  # index 3 = superellipse exponent


HEAD_PTS = [hx(p) for p in _HEAD_PTS]
HEAD_SHAPES = [_scale_shape(s) for s in _HEAD_SHAPES]
JAW_PTS = [jaw_open(hx(p)) for p in _JAW_PTS]
JAW_SHAPES = [_scale_shape(s) for s in _JAW_SHAPES]
HORN_PTS = [hx(p) for p in _HORN_PTS]
HORN_R = [r * HEAD_SCALE for r in _HORN_R]
FRONT_PTS = [(0.10, -0.30, 0.68), (0.19, -0.31, 0.56), (0.225, -0.255, 0.44), (0.24, -0.215, 0.35),
             (0.245, -0.205, 0.32), (0.248, -0.225, 0.29), (0.25, -0.28, 0.19), (0.25, -0.325, 0.10), (0.25, -0.355, 0.05)]
FRONT_SHAPES = [(0.100, 0.120, 0.120, 2.2), (0.088, 0.095, 0.095, 2.3), (0.070, 0.072, 0.078, 2.3),
                (0.056, 0.062, 0.054, 2.2), (0.054, 0.070, 0.050, 2.2), (0.050, 0.058, 0.050, 2.2),
                (0.047, 0.048, 0.050, 2.3), (0.036, 0.036, 0.038, 2.2), (0.038, 0.032, 0.038, 2.2)]
HIND_PTS = [(0.10, 0.38, 0.74), (0.18, 0.40, 0.60), (0.23, 0.33, 0.47), (0.245, 0.265, 0.39), (0.25, 0.245, 0.36),
            (0.25, 0.26, 0.33), (0.25, 0.36, 0.25), (0.25, 0.45, 0.18), (0.25, 0.47, 0.16), (0.25, 0.462, 0.135),
            (0.25, 0.43, 0.10), (0.25, 0.385, 0.05)]
HIND_SHAPES = [(0.125, 0.155, 0.155, 2.2), (0.115, 0.125, 0.145, 2.3), (0.100, 0.095, 0.125, 2.3),
               (0.070, 0.065, 0.075, 2.2), (0.064, 0.060, 0.068, 2.2), (0.058, 0.056, 0.056, 2.2),
               (0.054, 0.056, 0.048, 2.3), (0.042, 0.046, 0.036, 2.2), (0.040, 0.050, 0.034, 2.2),
               (0.037, 0.040, 0.034, 2.2), (0.034, 0.034, 0.034, 2.2), (0.036, 0.032, 0.036, 2.2)]
# Step R v1. Next to a realistic sculpt and real reptile scans (skill step R), the Phase B dragon read as thin-limbed
# with light wings. Measured on the B3 high-poly: forearm 11 cm and shin 10 cm thick at z = 0.2, tail 21 cm wide at
# y = 0.8, wing reach 0.90x snout-to-hip, 0.95 m2 membrane per wing. Mass: lower limbs +30 %, upper limbs +10-20 %,
# neck +15-20 %, tail +25 %. Stance: elbows 6 cm and knees 4 cm further out (reptilian sprawl); feet stay put.
TRUNK_SHAPES_B3, FRONT_PTS_B3, FRONT_SHAPES_B3 = TRUNK_SHAPES, FRONT_PTS, FRONT_SHAPES
HIND_PTS_B3, HIND_SHAPES_B3 = HIND_PTS, HIND_SHAPES
TRUNK_GROW = [1.1, 1.2, 1.2, 1.15, 1.0, 1.0, 1.0, 1.0, 1.0, 1.07, 1.25, 1.27, 1.2, 1.1, 1.0]
FRONT_GROW, FRONT_OUT = [1.0, 1.12, 1.2, 1.3, 1.3, 1.3, 1.3, 1.25, 1.2], [0.0, 0.02, 0.045, 0.06, 0.06, 0.055, 0.04, 0.02, 0.0]
HIND_GROW = [1.0, 1.1, 1.2, 1.3, 1.3, 1.3, 1.3, 1.25, 1.25, 1.25, 1.2, 1.2]
HIND_OUT = [0.0, 0.015, 0.03, 0.04, 0.04, 0.035, 0.025, 0.01, 0.0, 0.0, 0.0, 0.0]


def _grow(shapes, factors):
    return [tuple(v * f if i != 3 else v for i, v in enumerate(sh)) for sh, f in zip(shapes, factors)]


def _out(pts, offsets):
    return [(x + d, y, z) for (x, y, z), d in zip(pts, offsets)]


TRUNK_SHAPES = _grow(TRUNK_SHAPES_B3, TRUNK_GROW)
FRONT_PTS, FRONT_SHAPES = _out(FRONT_PTS_B3, FRONT_OUT), _grow(FRONT_SHAPES_B3, FRONT_GROW)
HIND_PTS, HIND_SHAPES = _out(HIND_PTS_B3, HIND_OUT), _grow(HIND_SHAPES_B3, HIND_GROW)


def follow_limbs(p):
    """Carry a B3 point near a limb with the limb's new centre line (anatomy anchors, strokes); fades out 8-16 cm away.
    (v1.3: the maths moved into the kit as ck.follow_chains.)"""
    return ck.follow_chains(p, ((FRONT_PTS_B3, FRONT_PTS), (HIND_PTS_B3, HIND_PTS)), full=0.08, fade=0.16)


# Wings: the reference wing is broad with heavy, knuckled finger bones. Chain 1.2x about the root (reach 0.90x ->
# about 1.08x snout-to-hip), bones 1.25-1.35x, knuckles at two finger joints, wrinkles and folds in the membrane.
WING_SCALE = 1.2
W_ROOT = V((0.07, -0.21, 0.80))
W_E_B3, W_W_B3 = V((0.48, 0.02, 1.10)), V((0.86, -0.26, 1.40))
W_TIPS_B3 = [V((1.32, -0.08, 1.52)), V((1.30, 0.30, 1.10)), V((1.04, 0.56, 0.86)), V((0.66, 0.60, 0.80))]
W_E, W_W = [W_ROOT + (q - W_ROOT) * WING_SCALE for q in (W_E_B3, W_W_B3)]
W_TIPS = [W_ROOT + (q - W_ROOT) * WING_SCALE for q in W_TIPS_B3]
BONE = 1.3                     # wing bone thickness factor (B3 = 1)
# Patches that share an edge must sample it identically so remove_doubles welds them: N_FINGER along every finger
# (finger panels and the inner membrane's finger-4 edge), N_ARM along the arm (inner and leading-edge patches).
# Run 1 used 48 vs 36 and 44 vs 18: the unwelded seams overlapped and rendered as dark marks on the membrane.
N_FINGER, N_ARM = 48, 44
WRINKLE = (0.0022, 7, 0.008)   # membrane: wrinkle amplitude (m), wrinkles across a finger panel, fold amplitude (m)
# (dry run 1: one 3 mm, 8-wave sine read as a pleated folding fan; two drifting frequencies read as slack skin)
EYE_R = 0.02 * HEAD_SCALE
TOE_TIPS = []    # (tip, direction, claw radius, claw length) on the left side
TOE_CHAINS = []  # toe and palm centre lines (left side) for the body fields
# R v2: brow edge at 38 deg (B3: 55) so it shelves out over the eye (at 16 deg) instead of raising the dome
BROW, CHEEK = rad(38), rad(-15)


def finger_mid(T):
    return W_W.lerp(T, 0.5) + dirn(0.0, 0.3, -0.5) * 0.022


SPINE = [hx((0, -1.12, 1.18)), hx((0, -0.98, 1.17)), hx((0, -0.84, 1.18))] + [V(p) for p in TRUNK_PTS[1:]]


def S(brush, r, strength, view, pts, label, target=None, passes=1, mode="NORMAL"):
    return sd.spec(brush, r, strength, view, [follow_limbs(p) for p in pts], label, target=target, mode=mode, passes=passes)


S1_JUNCTIONS = [
    S("Smooth", 0.05, 0.6, SIDE, [(0.24, -0.40, 0.60), (0.25, -0.30, 0.66), (0.24, -0.22, 0.60)], "shoulder junction", passes=3),
    S("Smooth", 0.06, 0.6, SIDE, [(0.20, 0.30, 0.72), (0.22, 0.42, 0.74), (0.22, 0.52, 0.66)], "thigh junction", passes=3),
    S("Smooth", 0.045, 0.6, TOP, [(0.12, -0.26, 0.88), (0.17, -0.18, 0.92), (0.12, -0.10, 0.88)], "wing root junction", passes=3),
    S("Smooth", 0.05, 0.6, dirn(-1, 0.3, -0.3), [(0.07, -0.76, 1.14), (0.06, -0.72, 1.20)], "neck-skull junction", passes=3),
    S("Smooth", 0.03, 0.6, SIDE, [(0.27, -0.37, 0.06), (0.27, -0.33, 0.11)], "front wrist-paw junction", passes=3),
    S("Smooth", 0.03, 0.6, SIDE, [(0.27, 0.41, 0.06), (0.27, 0.43, 0.11)], "hind ankle-paw junction", passes=3),
]
S2_SECONDARY = [  # Exp 5 v2/v3 list; head strokes follow the enlarged head; the mouth-line crease is gone (mouth open)
    S("Clay Strips", 0.016 * HEAD_SCALE, 0.5, dirn(-0.6, 0.6, -0.5), [hx((0.035, -0.96, 1.285)), hx((0.065, -0.93, 1.28)), hx((0.085, -0.89, 1.27))], "brow ridge", target=4),
    S("Crease Sharp", 0.012, 0.4, dirn(-1, 0, 0.35), [hx((0.06, -0.87, 1.11)), hx((0.07, -0.80, 1.12))], "jaw angle", target=3),
    S("Blob", 0.024 * HEAD_SCALE, 0.4, dirn(-0.3, 0.3, -1), [hx((0.05, -0.79, 1.30))], "horn boss", target=5),
    S("Clay", 0.025, 0.45, SIDE, [(0.07, -0.76, 1.12), (0.08, -0.66, 1.00), (0.10, -0.56, 0.86), (0.13, -0.47, 0.76)], "neck muscle", target=4),
    S("Inflate/Deflate", 0.035, 0.3, dirn(-0.4, 1, 0), [(0.04, -0.60, 0.60), (0.11, -0.56, 0.56), (0.16, -0.48, 0.52)], "pectoral", target=5),
    S("Inflate/Deflate", 0.035, 0.3, SIDE, [(0.22, -0.40, 0.62), (0.25, -0.31, 0.62), (0.24, -0.22, 0.56)], "deltoid", target=5),
    S("Clay", 0.030, 0.35, TOP, [(0.10, -0.40, 0.90), (0.13, -0.28, 0.92), (0.14, -0.18, 0.90)], "scapula", target=4),
    S("Clay", 0.018, 0.25, SIDE, [(0.20, -0.20, 0.75), (0.19, -0.12, 0.55)], "rib 1", target=2.5),
    S("Clay", 0.018, 0.25, SIDE, [(0.19, -0.10, 0.76), (0.18, -0.02, 0.57)], "rib 2", target=2.5),
    S("Clay", 0.018, 0.25, SIDE, [(0.18, 0.00, 0.76), (0.17, 0.08, 0.58)], "rib 3", target=2.5),
    S("Inflate/Deflate", 0.035, 0.3, SIDE, [(0.27, 0.30, 0.58), (0.29, 0.27, 0.48), (0.28, 0.26, 0.40)], "quadriceps", target=5),
    S("Inflate/Deflate", 0.030, 0.3, dirn(-1, -0.4, 0), [(0.25, 0.50, 0.62), (0.27, 0.45, 0.48)], "hamstring", target=4),
    S("Inflate/Deflate", 0.022, 0.3, SIDE, [(0.27, -0.22, 0.30), (0.27, -0.28, 0.18)], "forearm", target=3),
    S("Inflate/Deflate", 0.025, 0.3, dirn(-1, -0.3, 0), [(0.27, 0.30, 0.32), (0.27, 0.38, 0.24)], "calf", target=3),
    S("Inflate/Deflate", 0.040, 0.30, TOP, [(0.15, -0.19, 0.92)], "wing shoulder", target=4),
    S("Clay", 0.030, 0.35, TOP, [(0.04, 0.52, 0.80), (0.04, 0.70, 0.68)], "tail root muscle", target=4),
]
S2_POLISH = [
    S("Smooth", 0.06, 0.35, dirn(-0.4, 1, 0), [(0.03, -0.62, 0.66), (0.12, -0.56, 0.58), (0.18, -0.46, 0.52)], "polish chest", passes=2),
    S("Smooth", 0.06, 0.35, SIDE, [(0.21, -0.36, 0.72), (0.20, -0.14, 0.70), (0.18, 0.08, 0.68)], "polish flank", passes=2),
    S("Smooth", 0.05, 0.35, SIDE, [(0.27, 0.34, 0.62), (0.28, 0.28, 0.48), (0.28, 0.26, 0.38)], "polish thigh", passes=2),
    S("Smooth", 0.04, 0.35, SIDE, [(0.24, -0.36, 0.60), (0.25, -0.26, 0.46), (0.26, -0.22, 0.34)], "polish upper arm", passes=2),
    S("Smooth", 0.06, 0.35, TOP, [(0.08, -0.40, 0.90), (0.10, -0.10, 0.86), (0.10, 0.30, 0.86)], "polish back", passes=2),
]
GULAR_UP = dirn(0, 0.73, 0.68)  # dorsal axis of the upper neck: looking along it views the throat from below-front
S2_DETAIL = [  # new in Exp 6: masses a flier and a biter need
    S("Inflate/Deflate", 0.045, 0.3, dirn(-0.5, 1, -0.1), [(0.05, -0.62, 0.68), (0.12, -0.55, 0.72), (0.17, -0.44, 0.78)], "pectoralis (flight)", target=6.0),
    S("Inflate/Deflate", 0.035, 0.3, TOP, [(0.09, -0.36, 0.95), (0.13, -0.26, 0.96), (0.13, -0.14, 0.93)], "dorsal flight muscle", target=5.0),
    S("Inflate/Deflate", 0.022, 0.3, SIDE, [hx((0.09, -0.845, 1.150)), hx((0.09, -0.805, 1.168))], "masseter", target=4.0),
    S("Inflate/Deflate", 0.018, 0.3, SIDE, [(0.19, -0.27, 0.80), (0.22, -0.22, 0.86)], "wing-root muscle", target=3.0),
]
# R v4 (reference gap 4): loose neck skin as rolls with grooves between, ringed across the sloping neck (the Komodo
# technique; three thin creases read as cuts). Rings sit across the neck axis from the skull junction to the chest.
NECK_A, NECK_B = V((0.0, -0.745, 1.135)), V((0.0, -0.575, 0.850))
NECK_D = (NECK_B - NECK_A).normalized()
NECK_UP = V((0.0, -NECK_D.z, NECK_D.y))     # across the axis, toward the back of the neck (z > 0 for this slope)


def _neck_ring(t, wobble, half):
    a = NECK_A.lerp(NECK_B, t)
    pts = []
    for x, h, k in ((0.62, 0.070, 0.6), (0.90, 0.028, -1.0), (1.0, -0.020, 0.8), (0.84, -0.068, -0.4)):
        q = a + NECK_UP * h + NECK_D * (wobble * k)
        pts.append((half * x, q.y, q.z))
    return pts


NECK_ROLLS = []
for i, (t, wob, half) in enumerate(((0.06, 0.008, 0.074), (0.24, -0.007, 0.080), (0.42, 0.010, 0.088), (0.60, -0.006, 0.097),
                                    (0.80, 0.009, 0.108))):
    NECK_ROLLS.append(S("Clay", 0.012, 0.35, SIDE, _neck_ring(t, wob, half), f"neck roll {i + 1}", target=3.0))
    if i:
        NECK_ROLLS.append(S("Crease Sharp", 0.008, 0.25, SIDE, _neck_ring(t - 0.09, wob * 0.5, half * 0.98), f"neck groove {i}", target=1.8))


S3_TERTIARY = [
] + NECK_ROLLS + [
    S("Crease Sharp", 0.007, 0.3, GULAR_UP, [(0.0, -0.781, 1.067), (0.04, -0.772, 1.078), (0.062, -0.752, 1.100)], "gular fold 1", target=2.5),
    S("Crease Sharp", 0.007, 0.3, GULAR_UP, [(0.0, -0.745, 1.030), (0.045, -0.737, 1.040), (0.066, -0.718, 1.062)], "gular fold 2", target=2.0),
    S("Crease Sharp", 0.008, 0.3, SIDE, [(0.20, -0.20, 0.58), (0.21, -0.17, 0.52), (0.22, -0.16, 0.46)], "axillary fold", target=2.5),
    S("Crease Sharp", 0.008, 0.3, SIDE, [(0.20, 0.25, 0.66), (0.21, 0.26, 0.58), (0.23, 0.28, 0.50)], "inguinal fold", target=2.5),
    S("Crease Sharp", 0.007, 0.3, TOP, [(0.13, -0.13, 0.87), (0.17, -0.12, 0.85)], "wing-root fold", target=2.0),
    S("Draw", 0.007, 0.3, dirn(0, -0.6, -0.8), [(0.25, 0.30, 0.37), (0.25, 0.38, 0.30), (0.25, 0.45, 0.235)], "Achilles tendon", target=1.5),
    S("Draw", 0.006, 0.3, BEHIND, [(0.25, -0.235, 0.26), (0.25, -0.25, 0.19), (0.25, -0.285, 0.11)], "forearm flexor tendon", target=1.2),
]

# Exp 6 strokes now produced by anatomy volumes (kept out of the stroke programme to avoid doubling the forms)
REPLACED_BY_ANATOMY = {"brow ridge", "pectoral", "deltoid", "scapula", "rib 1", "rib 2", "rib 3", "quadriceps", "hamstring",
                       "forearm", "calf", "pectoralis (flight)", "dorsal flight muscle", "masseter", "wing-root muscle",
                       "Achilles tendon", "forearm flexor tendon"}
FRONT_IN, BACK_IN = dirn(-0.7, 0.7, 0), dirn(-0.7, -0.7, 0)   # rays arriving from front-left / back-left


def vol(name, kind, a, b, width, protrude, **kw):
    a, b = (follow_limbs(a[0]),) + tuple(a[1:]), (follow_limbs(b[0]),) + tuple(b[1:])
    return dict(name=name, kind=kind, a=a, b=b, width=width, protrude=protrude, **kw)


def head(p, up=0.0, fwd=0.0):
    return (hx(p), lateral(up, fwd))


HEAD_TOL = 0.16  # head anchors aim from the skull axis, so the hit lies a half-width (up to ~0.12 m) from the target


ANATOMY_SPECS = [
    # skull landmarks (head coordinates scaled with the head)
    # R v2: brow longer, heavier and lower (B3: -0.96 to -0.865, 45 deg, 30 x 20 mm), zygomatic arch 22 x 14 -> 32 x 22 mm
    # R v4: brow 26 mm past the eye after R v3 (target 30): bump 0.058 -> 0.066, ridge protrusion 34 -> 40 mm.
    # R4b: heavier brows deepened the groove between them and the cavity fillet filled it, raising the midline
    # (dome 0.568 -> 0.576); the cranium top (ap) at stations 4-6 is lowered a further 8-11 %
    vol("brow ridge", "ridge", head((0.0, -0.975, 1.258), 34), head((0.0, -0.855, 1.262), 34), 0.040, 0.040, tol=HEAD_TOL),
    vol("zygomatic arch", "ridge", head((0.0, -0.93, 1.175), -5), head((0.0, -0.82, 1.18), -5), 0.032, 0.022, tol=HEAD_TOL),
    # (a postorbital bar behind the eye was tried in two dry runs and skipped both times: its path crosses the eye socket)
    vol("angular plate", "ridge", (jaw_open(hx((0.0, -0.93, 1.131))), lateral(-40)), (jaw_open(hx((0.0, -0.83, 1.146))), lateral(-40)),
        0.030, 0.016, tol=HEAD_TOL),
    vol("nasal ridge", "ridge", head((0.0, -1.10, 1.19), 70), head((0.0, -0.97, 1.23), 70), 0.016, 0.007, tol=HEAD_TOL),
    vol("parietal crest", "ridge", head((0.0, -0.85, 1.26), 70), head((0.0, -0.765, 1.24), 60), 0.020, 0.010, tol=HEAD_TOL),
    # R v4: the masseter path ran from behind the eye down across the open gape and left the surface (skipped in every
    # build since Phase A); the adductor bulge sits above the gape, in front of the ear
    vol("masseter", "muscle", head((0.0, -0.860, 1.190), 5), head((0.0, -0.805, 1.175), 0), 0.032, 0.012, tol=HEAD_TOL),
    vol("narial boss", "knob", head((0.0, -1.125, 1.18), 55), head((0.0, -1.095, 1.186), 55), 0.026, 0.009, tol=HEAD_TOL),
    # (v2 maxillary/mandible ridges removed: with the mouth open their surface path crossed the gape and bridged the
    # jaws; lip margins are a Phase B scale/labial task),
    # neck
    vol("sternocephalicus", "muscle", ((0.0, -0.76, 1.12), lateral(-10, 20)), ((0.0, -0.60, 0.86), lateral(-10, 30)), 0.030, 0.012),
    vol("splenius", "muscle", ((0.0, -0.76, 1.20), dirn(-0.6, -0.5, -0.6)), ((0.0, -0.57, 0.90), dirn(-0.6, -0.5, -0.6)), 0.030, 0.010),
    # shoulder girdle and forelimb
    vol("pectoralis", "muscle", ((0.03, -0.62, 0.62), dirn(0, 1, 0.15)), ((0.20, -0.40, 0.66), dirn(-1, 0.3, 0)), 0.070, 0.022, depth=0.5),
    vol("deltoid", "muscle", ((0.15, -0.32, 0.86), dirn(-0.5, 0, -0.85)), ((0.25, -0.33, 0.57), SIDE), 0.055, 0.018),
    vol("scapula spine", "ridge", ((0.10, -0.42, 0.90), dirn(-0.5, 0, -0.87)), ((0.16, -0.24, 0.86), dirn(-0.5, 0, -0.87)), 0.016, 0.008),
    vol("triceps", "muscle", ((0.22, -0.26, 0.62), BACK_IN), ((0.245, -0.19, 0.37), BACK_IN), 0.038, 0.014),
    vol("biceps", "muscle", ((0.235, -0.36, 0.56), FRONT_IN), ((0.245, -0.27, 0.40), FRONT_IN), 0.032, 0.011),
    vol("forearm extensors", "muscle", ((0.25, -0.235, 0.31), SIDE), ((0.25, -0.31, 0.13), SIDE), 0.030, 0.010),
    vol("olecranon", "knob", ((0.245, -0.19, 0.36), dirn(0, -1, 0), 0.12), ((0.245, -0.195, 0.31), dirn(0, -1, 0), 0.12), 0.026, 0.008),
    vol("forearm flexor tendon", "tendon", ((0.25, -0.235, 0.27), dirn(0, -1, 0)), ((0.25, -0.28, 0.12), dirn(0, -1, 0)), 0.012, 0.005),
    vol("dorsal flight muscle", "muscle", ((0.09, -0.36, 0.95), TOP), ((0.13, -0.14, 0.93), TOP), 0.045, 0.015),
    # trunk
    vol("rib 1", "ridge", ((0.20, -0.20, 0.75), SIDE), ((0.19, -0.12, 0.56), SIDE), 0.016, 0.006),
    vol("rib 2", "ridge", ((0.19, -0.10, 0.76), SIDE), ((0.18, -0.02, 0.57), SIDE), 0.016, 0.006),
    vol("rib 3", "ridge", ((0.18, 0.00, 0.76), SIDE), ((0.17, 0.08, 0.58), SIDE), 0.016, 0.006),
    vol("iliac crest", "ridge", ((0.12, 0.30, 0.84), dirn(-0.6, 0, -0.8)), ((0.13, 0.50, 0.80), dirn(-0.6, 0, -0.8)), 0.018, 0.008),
    # hind limb and tail base
    vol("quadriceps", "muscle", ((0.24, 0.34, 0.66), FRONT_IN), ((0.26, 0.27, 0.42), FRONT_IN), 0.062, 0.020),
    vol("hamstrings", "muscle", ((0.22, 0.50, 0.66), BACK_IN), ((0.255, 0.38, 0.40), BACK_IN), 0.056, 0.018),
    vol("gastrocnemius", "muscle", ((0.255, 0.31, 0.35), dirn(-0.6, -0.8, 0)), ((0.25, 0.44, 0.21), dirn(-0.6, -0.8, 0)), 0.040, 0.014),
    # (patella removed: where quadriceps, gastrocnemius and the kneecap meet it pinched into a nub in v1 and v2)
    vol("Achilles tendon", "tendon", ((0.25, 0.42, 0.26), dirn(-0.6, -0.8, 0)), ((0.25, 0.465, 0.17), dirn(-0.6, -0.8, 0)), 0.014, 0.006),
    vol("caudofemoralis", "muscle", ((0.12, 0.55, 0.72), SIDE), ((0.08, 0.88, 0.55), SIDE), 0.055, 0.014),
]


def build_wings(tree, arm_path, B):
    frames = pm.Part("DRG_WingFingers")
    frames.sweep([W_W + V((-0.03, 0.01, -0.02)), W_W + V((0.03, -0.01, 0.02))],
                 [(0.032 * BONE, 0.032 * BONE, 0.032 * BONE, 2.0), (0.030 * BONE, 0.030 * BONE, 0.030 * BONE, 2.0)],
                 "skin", N=14, step=0.012, start="tip", end="tip", tip=0.7)
    fpaths = []
    for T in W_TIPS:
        b0, b1 = 0.019 * BONE * 1.04, 0.0145 * BONE * 1.04
        frames.sweep([W_W, finger_mid(T), T], [(b0, b0, b0, 2.0), (b1, b1, b1, 2.0), (0.005, 0.005, 0.005, 2.0)],
                     "skin", N=12, step=0.02, start="cap", end="tip", tip=1.0,
                     scale_fn=lambda s, L: (1.0 + 0.26 * math.exp(-((s / L - 0.42) / 0.05) ** 2)      # knuckles
                                            + 0.16 * math.exp(-((s / L - 0.70) / 0.04) ** 2)))
        fpaths.append(pm.Path([W_W, finger_mid(T), T]))

    memb = pm.Part("DRG_WingMembranes")
    inward = dirn(-0.5, 0, -0.87)
    guesses = [(0.17, -0.06, 0.84), (0.18, 0.06, 0.78), (0.18, 0.19, 0.78), (0.17, 0.32, 0.80)]
    attach = [surface_hit(tree, g, inward)[0] + inward * 0.006 for g in guesses]
    A = attach[-1]
    s0 = arc_at_u(arm_path, 1.0)

    def arm(u):
        return arm_path.at(s0 + u * (arm_path.length - s0))[0]
    body_line = pm.Path([B] + attach)
    for i in range(3):
        Ti, Tj = W_TIPS[i], W_TIPS[i + 1]
        depth = 0.20 * (Ti - Tj).length
        toward = (W_W - Ti.lerp(Tj, 0.5)).normalized()
        nn = (Ti - W_W).cross(Tj - W_W).normalized()
        sag = (nn if nn.z < 0 else -nn) * 0.035

        wa, wn, fa = WRINKLE

        def fn(u, v, i=i, depth=depth, toward=toward, sag=sag, nn=nn):
            p = fpaths[i].point(u).lerp(fpaths[i + 1].point(u), v)
            sv = math.sin(math.pi * v)
            # wrinkles run from the wrist toward the trailing edge between the bones; a few broad folds across
            wr = wa * (0.6 * math.sin(2 * math.pi * (wn * v + 0.6 * u * u + 0.21 * i))
                       + 0.4 * math.sin(2 * math.pi * (1.73 * wn * v - 0.9 * u + 0.37 * i))) * min(1.0, 2.5 * u)
            fold = fa * math.sin(2 * math.pi * (1.4 * u + 0.37 * i)) * u
            return (p + toward * depth * sv * u ** 3 + sag * sv * math.sin(math.pi * u * 0.75)
                    + nn * sv * (wr + fold))
        memb.patch(fn, N_FINGER, 40, fpaths[i].length, (Ti - Tj).length, "membrane")
    T4 = W_TIPS[3]
    in_toward = (W_W - A.lerp(T4, 0.5)).normalized()
    nn = (T4 - W_W).cross(A - W_W).normalized()
    in_sag = (nn if nn.x > 0 else -nn) * 0.02

    def inner(u, v):
        c0, c1 = arm(u), A.lerp(T4, u) + in_toward * 0.16 * (T4 - A).length * math.sin(math.pi * u)
        d0, d1 = body_line.point(v), fpaths[3].point(v)
        bil = B * (1 - u) * (1 - v) + W_W * u * (1 - v) + A * (1 - u) * v + T4 * u * v
        suv = math.sin(math.pi * u) * math.sin(math.pi * v)
        wr = (WRINKLE[0] * (0.6 * math.sin(2 * math.pi * (7 * u + 0.5 * v)) + 0.4 * math.sin(2 * math.pi * (11.3 * u - 0.8 * v)))
              + WRINKLE[2] * 0.7 * math.sin(2 * math.pi * (1.2 * v + 0.2)))
        return (1 - v) * c0 + v * c1 + (1 - u) * d0 + u * d1 - bil + in_sag * suv + nn.normalized() * suv * wr
    memb.patch(inner, N_ARM, N_FINGER, (W_W - B).length, (A - B).length, "membrane")

    def front(u, v):
        lead = B.lerp(W_W, u) + (W_E - B.lerp(W_W, 0.5)).normalized() * 0.05 * math.sin(math.pi * u)
        return lead.lerp(arm(u), v)
    memb.patch(front, N_ARM, 4, (W_W - B).length, 0.1, "membrane")
    memb.pack_uvs()
    bmesh.ops.remove_doubles(memb.bm, verts=memb.bm.verts[:], dist=1e-5)
    bmesh.ops.dissolve_degenerate(memb.bm, dist=1e-6, edges=memb.bm.edges[:])
    bmesh.ops.solidify(memb.bm, geom=memb.bm.faces[:], thickness=0.006)
    for f in memb.bm.faces:
        f.smooth = True
    memb.packed = True  # UVs were packed before welding
    return frames, memb


class Dragon(ck.Creature):
    name = "dragon"
    prefix = "DRG_"
    settings = os.path.join(HERE, "dragon_settings.json")
    head_y = (hx((0, -0.78, 0)).y, hx((0, -0.72, 0)).y)
    head_z, tail_y = (1.00, 1.07), (0.55, 0.80)
    mouth = {"head_pts": HEAD_PTS, "head_shapes": HEAD_SHAPES, "y_back": hx(V((0, -0.80, 0))).y, "teeth": {}, "tongue": {}}
    eye = {"radius": EYE_R, "sink": 0.003 * HEAD_SCALE, "lid_up": (20, 48), "lid_lo": (15, 42)}
    # Phase B: geometric scales with scale_field.DEFAULTS (sized for this 3 m dragon). R v3: head scales 13 -> 9 mm and
    # top plates 28 -> 17 mm, so the brow, cheek and crest ridges read as bony forms instead of being covered by plates
    # R v4 (reference gaps 5-6, Phase B gate): flank scales in rows along the body rings (alligator), deeper grooves
    # everywhere (fine relief p90 was 0.41-0.53 mm against the 0.5 mm gate), keeled dorsal scutes in transverse rows,
    # larger plates at the shoulder and elbow. R v3: head 1.3 mm, head plates 2.2 mm, other layers at the defaults.
    insert_collars = True           # v1.3: horns, spikes and claws grow out of a swell of skin
    joint_relief = 0.5              # v1.3: scales half as high at elbows, knees and wrists (flexible skin)
    surface_plan = [                # v1.3 material profiles (the default plan keeps the v1.2 materials)
        {"region_id": "skin_base", "material_profile": "body:sss"},
        {"region_id": "claws", "material_profile": "claw:matte"},
        {"region_id": "teeth", "material_profile": "tooth:enamel"},
    ]
    scales = {"seed": 7, "head": {"size": 0.009, "height": 0.0016}, "head_plates": {"size": 0.017, "height": 0.0024},
              "flank_rows": {"enabled": True, "size": (0.016, 0.014), "height": 0.0022},
              "granular": {"height": 0.0018}, "limb": {"height": 0.0019}, "limb_plates": {"size": (0.032, 0.027), "height": 0.0030},
              "dorsal": {"height": 0.0030, "keel": 0.8, "keel_w": 0.08}, "ventral": {"height": 0.0030},
              "tail": {"height": 0.0024, "jitter": 0.30},
              # R4b: R4's scutes (keel 0.9, width 0.10) read as tiles; the alligator's keels are narrow, tall blades
              "paravertebral": {"size": (0.040, 0.030), "height": 0.0072, "keel": 1.6, "keel_w": 0.06, "jitter": 0.20, "stagger": 0.0,
                                "band": (0.008, 0.016, 0.100, 0.125)}}

    def spine(self):
        return SPINE

    def field_chains(self):
        return [("front", [V(p) for p in FRONT_PTS[1:]]), ("hind", [V(p) for p in HIND_PTS[1:]]), ("arm", [W_ROOT, W_E, W_W])]

    def regions(self):
        return {"tail": lambda v: v[:, 1] > 0.45, "toes_feet": lambda v: v[:, 2] < 0.06, "head": lambda v: v[:, 1] < -0.72,
                "wing_arm": lambda v: (abs(v[:, 0]) > 0.3) & (v[:, 2] > 0.85)}

    def build_base(self):
        trunk = pm.Part("trunk")
        trunk_path = trunk.sweep(TRUNK_PTS, TRUNK_SHAPES, "skin", N=32, step=0.025, start="cap", end="tip", tip=1.5,
                                 bumps=[(1.5 * math.pi, 0.35, 4), (0.5 * math.pi, 0.22, 5)])
        trunk.bm.normal_update()
        from mathutils.bvhtree import BVHTree
        inward = dirn(-0.5, 0, -0.87)
        B = surface_hit(BVHTree.FromBMesh(trunk.bm), (0.15, -0.19, 0.90), inward)[0] + inward * 0.004
        head = pm.Part("head")
        head.sweep(HEAD_PTS, HEAD_SHAPES, "skin", N=48, step=0.007, start="tip", end="tip",
                   bumps=[(BROW, 0.28, 4), (math.pi - BROW, 0.28, 4), (CHEEK, 0.40, 5), (math.pi - CHEEK, 0.40, 5),
                          (0.5 * math.pi, 0.15, 6)])
        head.sweep(JAW_PTS, JAW_SHAPES, "skin", N=28, step=0.009, start="tip", end="tip")
        limbs = pm.Part("limbs")
        limbs.sweep(FRONT_PTS, FRONT_SHAPES, "skin", N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
        limbs.sweep(HIND_PTS, HIND_SHAPES, "skin", N=20, step=0.018, frame="hint", hint=X, start="cap", end="cap")
        ck.paw(self, limbs, (0.25, -0.37, 0.03), (math.sin(rad(8)), -math.cos(rad(8)), 0),
               [{"angle": a, "length": 0.066, "radius": 0.023, "claw": 0.050} for a in (-26, 0, 26)],
               dewclaw={"direction": -120, "down": -0.35, "length": 0.028, "radius": 0.014, "claw": 0.026, "offset": (-0.030, 0.012, 0.046)})
        hfwd = V((math.sin(rad(6)), -math.cos(rad(6)), 0))
        ck.paw(self, limbs, (0.25, 0.36, 0.03), hfwd, [{"angle": a, "length": 0.076, "radius": 0.025, "claw": 0.055} for a in (-24, 0, 24)],
               back_toe={"direction": 192, "length": 0.036, "radius": 0.0176, "claw": 0.036,
                         "offset": tuple(Matrix.Rotation(rad(192), 3, "Z") @ hfwd * 0.03)})
        k = 1 + (BONE - 1) * 0.85
        arm_path = limbs.sweep([W_ROOT, B, W_E, W_W], [(0.060 * k, 0.060 * k, 0.060 * k, 2.0), (0.050 * k, 0.050 * k, 0.050 * k, 2.0),
                                                       (0.040 * k, 0.040 * k, 0.040 * k, 2.0), (0.028 * k, 0.030 * k, 0.030 * k, 2.0)],
                               "skin", N=16, step=0.02, start="cap", end="cap")
        ed = (W_E - B).normalized()
        limbs.sweep([W_E - ed * 0.03, W_E + ed * 0.03], [(0.040 * k, 0.044 * k, 0.040 * k, 2.0), (0.034 * k, 0.036 * k, 0.034 * k, 2.0)],
                    "skin", N=16, step=0.01, start="tip", end="tip", tip=0.7)  # elbow knob
        limbs.mirror_x()
        bm = bmesh.new()
        for part in (trunk, head, limbs):
            me = bpy.data.meshes.new("tmp")
            part.bm.to_mesh(me)
            part.bm.free()
            bm.from_mesh(me)
            bpy.data.meshes.remove(me)
        self.info.update(trunk_path=trunk_path, arm_path=arm_path, B=B)
        return bm

    def anatomy(self, tree):
        return ANATOMY_SPECS

    def strokes(self):
        keep = lambda specs: [s for s in specs if s["label"] not in REPLACED_BY_ANATOMY]  # noqa: E731
        return [("junctions", S1_JUNCTIONS), ("secondary", keep(S2_SECONDARY)), ("polish", S2_POLISH),
                ("secondary_detail", keep(S2_DETAIL)), ("tertiary", keep(S3_TERTIARY))]

    def features(self, tree):
        hs = HEAD_SCALE
        return [{"name": "eye", "ref": surface_hit(tree, hx((0.0, -0.90, 1.212)), lateral(16)), "radius": 0.024 * hs,
                 "depth": 0.009 * hs, "rim": 0.0025 * hs, "upper": 2.5},
                {"name": "nostril", "ref": surface_hit(tree, hx((0.0, -1.115, 1.175)), lateral(64)), "radius": 0.011 * hs,
                 "depth": 0.010, "rim": 0.0025},
                {"name": "ear", "ref": surface_hit(tree, hx((0.0, -0.775, 1.215)), lateral(8)), "radius": 0.012,
                 "depth": 0.0035, "rim": 0.0012}]

    def inserts(self, ctx):
        tree, rng = ctx["tree"], ctx["rng"]
        horns = pm.Part(self.prefix + "Horns")
        horns.sweep(HORN_PTS, [(r * 0.85, r, r, 2.0) for r in HORN_R], "horn", N=14, step=0.007, tip=1.0,
                    scale_fn=lambda s, L: 1.0 + 0.07 * max(0.0, math.sin(2 * math.pi * s / 0.028)) ** 2 * max(0.0, 1 - s / (0.75 * L)))
        collars = ctx["collars"]
        try:                                   # v1.3: where the main horn's axis leaves the skin
            hb, hn = surface_hit(tree, HORN_PTS[0], (HORN_PTS[0] - HORN_PTS[2]).normalized())
            collars.append((hb, hn, HORN_R[0], None, True))
        except RuntimeError:
            pass
        n_cheek = 0
        # R v4: cheek spikes 60 % longer plus a fourth (R v3: 32/25/20 mm, smaller and fewer than the reference's)
        for y, z, L in ((-0.80, 1.14, 0.050), (-0.775, 1.165, 0.042), (-0.825, 1.115, 0.034), (-0.85, 1.095, 0.026)):
            try:
                base, nrm = surface_hit(tree, hx((0.0, y, z)), SIDE)
            except RuntimeError:
                continue
            L *= HEAD_SCALE
            d = (nrm * 0.45 + Y * 0.85 - Z * 0.12).normalized()
            collars.append((base, nrm, 0.20 * L, None, True))
            base = base - nrm * 0.004
            horns.sweep([base, base + d * L * 0.5 + nrm * L * 0.06, base + d * L],
                        [(0.13 * L, 0.20 * L, 0.20 * L, 2.0), (0.08 * L, 0.12 * L, 0.12 * L, 2.0), (0.001, 0.001, 0.001, 2.0)],
                        "spike", N=8, step=max(L / 5, 0.004), frame="hint", hint=Z, tip=1.0)
            n_cheek += 1
        self.log["cheek_spikes_per_side"] = n_cheek

        def spike(base, nrm, d, L, stout=1.0):
            collars.append((base, nrm, 0.24 * L * stout, None, True))
            base = base - nrm * 0.005
            horns.sweep([base, base + d * L * 0.5 + nrm * L * 0.05, base + d * L],
                        [(0.16 * L * stout, 0.24 * L * stout, 0.24 * L * stout, 2.0),
                         (0.10 * L * stout, 0.15 * L * stout, 0.15 * L * stout, 2.0), (0.001, 0.001, 0.001, 2.0)],
                        "spike", N=8, step=max(L / 6, 0.004), frame="hint", hint=Z, tip=1.0)
        n_crown = n_jaw = 0
        for y, up, L in CROWN:                 # R v2: crown of horns on the back rim of the skull, swept back
            try:
                base, nrm = surface_hit(tree, hx((0.0, y, 1.222)), lateral(up))
            except RuntimeError:
                continue
            spike(base, nrm, (nrm * 0.55 + Y * 0.8 + Z * 0.25).normalized(), L * HEAD_SCALE, 1.25)
            n_crown += 1
        for y, z, L in JAW_SPIKES:             # R v2: spikes under the lower jaw, pointing down and back
            try:
                base, nrm = surface_hit(tree, jaw_open(hx((0.0, y, z))), lateral(-50))
            except RuntimeError:
                continue
            spike(base, nrm, (nrm * 0.45 - Z * 0.55 + Y * 0.7).normalized(), L * HEAD_SCALE)
            n_jaw += 1
        self.log["crown_horns_per_side"], self.log["jaw_spikes_per_side"] = n_crown, n_jaw
        spikes = pm.Part(self.prefix + "DorsalSpikes")
        self.log["dorsal_spikes"] = ck.spikes_along(spikes, tree, self.info["trunk_path"],
                                                    [(0.0, 0.026), (0.12, 0.04), (0.25, 0.066), (0.42, 0.062), (0.6, 0.046), (0.92, 0.014)],
                                                    0.068, rng, collars=collars)
        claws = pm.Part(self.prefix + "Claws")
        self.log["claw_drop"] = [round(ck.claw(claws, tip, d, cl, r, collars=collars), 3) for tip, d, r, cl in self.toe_tips]
        pm.claw(claws, W_W + V((0.0, -0.03, 0.025)), V((0.15, -0.75, 0.55)), 0.06, 0.012)
        frames, memb = build_wings(tree, self.info["arm_path"], self.info["B"])
        return [(horns, True), (spikes, False), (claws, True), (frames, True), (memb, True)]


if __name__ == "__main__":
    ck.run(Dragon(), __file__)
