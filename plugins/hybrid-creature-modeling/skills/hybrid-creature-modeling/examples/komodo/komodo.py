"""Komodo dragon (Varanus komodoensis) - skill test creature #3, built with creature_kit v1.2.0 and step R references.

References (step R, viewed in the browser, nothing downloaded):
  real: Komodo Dragon NHMW-ZOO-HS-23783, Natural History Museum Vienna (Sketchfab, CC BY-NC) - loose neck skin in
        deep folds, small bead scales in rings, larger smooth scales on the head, low heavy body.
  real: American Alligator NHMW-ZOO-HS-15682 (same museum) - how scales run in rings along the body.

Anatomy (checked as numbers, SKILL.md step 1): 2.67 m snout to tail tip (adult); tail about half the total length;
head 0.25 m, long and low with a rounded snout, the lower jaw reaching to 7 mm behind the snout tip at 87-90 % of
the upper jaw's width; mouth open 10 degrees with the long yellow forked tongue out; sprawling limbs (humerus and
femur run outward, elbow and knee out, forearm and shin down); five toes with long curved claws; body low in a walk
(belly about 0.19 m above the ground); loose skin folds on the neck and throat; small bead scales (Level 2 geometry
at 8 mm, finer in the shader), rings of scales on the tail, no dorsal crest or plates.

  GUI:     blender --factory-startup --window-geometry 0 0 1400 1000 --python komodo.py
  Dry run: CREATURE_DRY_RUN=1 blender -b --factory-startup --python komodo.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("CREATURE_KIT_DIR") or os.path.normpath(os.path.join(HERE, "..", "..", "scripts")))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402

import creature_kit as ck  # noqa: E402
import proc_mesh as pm  # noqa: E402
import sculpt_driver as sd  # noqa: E402
from creature_kit import V, X, Y, Z, SIDE, TOP, dirn, rad, lateral  # noqa: E402,F401

# --------------------------------------------------------------------------------------------- body (y forward = -)
TRUNK_PTS = [(0, -1.00, 0.355), (0, -0.92, 0.350), (0, -0.84, 0.345), (0, -0.76, 0.340), (0, -0.66, 0.335),
             (0, -0.54, 0.330), (0, -0.38, 0.328), (0, -0.20, 0.330), (0, -0.05, 0.335), (0, 0.08, 0.338),
             (0, 0.25, 0.315), (0, 0.45, 0.260), (0.02, 0.70, 0.185), (0.05, 0.95, 0.118), (0.08, 1.15, 0.076),
             (0.10, 1.32, 0.048), (0.11, 1.42, 0.036)]
# (half-width, top, bottom, exponent, belly bump, dorsal bump): wide flat belly, neck as thick as the head's back,
# tail laterally compressed toward the tip (height > width)
TRUNK_SHAPES_DRY1 = [(0.064, 0.060, 0.064, 2.0, 0.0, 0.0), (0.072, 0.064, 0.074, 2.1, 0.0, 0.002),
                     (0.080, 0.068, 0.084, 2.1, 0.0, 0.003), (0.094, 0.074, 0.094, 2.2, 0.0, 0.004),
                     (0.122, 0.086, 0.112, 2.3, 0.006, 0.005), (0.146, 0.092, 0.128, 2.4, 0.010, 0.006),
                     (0.160, 0.094, 0.136, 2.5, 0.012, 0.006), (0.164, 0.094, 0.134, 2.5, 0.012, 0.006),
                     (0.146, 0.092, 0.118, 2.4, 0.008, 0.006), (0.116, 0.088, 0.098, 2.3, 0.0, 0.006),
                     (0.088, 0.080, 0.082, 2.2, 0.0, 0.005), (0.066, 0.072, 0.068, 2.1, 0.0, 0.004),
                     (0.048, 0.062, 0.056, 2.0, 0.0, 0.003), (0.033, 0.048, 0.042, 2.0, 0.0, 0.002),
                     (0.022, 0.034, 0.030, 2.0, 0.0, 0.001), (0.012, 0.020, 0.018, 2.0, 0.0, 0.0), (0.003, 0.003, 0.003, 2.0, 0.0, 0.0)]
# dry run 1 next to the NHM Vienna scan: body too shallow (depth 0.34x shoulder-hip vs about 0.45-0.5x), thin neck
# and tail base. Belly depth (bottom) +32-40 % at the chest and belly, widths +8 %; neck +15 %; tail base +25 %.
_GROW = [(1.08, 1.0, 1.08), (1.15, 1.15, 1.15), (1.15, 1.15, 1.15), (1.12, 1.1, 1.15), (1.08, 1.0, 1.32), (1.08, 1.0, 1.36),
         (1.08, 1.0, 1.38), (1.08, 1.0, 1.40), (1.08, 1.0, 1.36), (1.1, 1.05, 1.28), (1.22, 1.2, 1.25), (1.26, 1.22, 1.25),
         (1.25, 1.2, 1.22), (1.2, 1.15, 1.15), (1.1, 1.08, 1.08), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)]
TRUNK_SHAPES = [(w * gw, t * gt, b * gb) + tuple(rest) for (w, t, b, *rest), (gw, gt, gb) in zip(TRUNK_SHAPES_DRY1, _GROW)]
# head: long, low, flat-topped, rounded snout; (w, top, bottom, n, brow, cheek, top bump)
HEAD_PTS = [V(p) for p in [(0, -1.250, 0.345), (0, -1.236, 0.348), (0, -1.200, 0.352), (0, -1.150, 0.357), (0, -1.100, 0.362),
                           (0, -1.060, 0.366), (0, -1.030, 0.368), (0, -1.005, 0.368), (0, -0.990, 0.367)]]
# dry run 1 read as an alligator (flat top, long tapering snout): blunter, rounder snout, deeper skull (+15 % top)
HEAD_SHAPES = [(0.014, 0.014, 0.014, 2.0, 0.0, 0.0, 0.0), (0.036, 0.026, 0.020, 2.3, 0.0, 0.0, 0.0),
               (0.046, 0.033, 0.024, 2.4, 0.0, 0.0, 0.0), (0.052, 0.039, 0.027, 2.5, 0.0, 0.002, 0.0),
               (0.058, 0.046, 0.030, 2.5, 0.004, 0.004, 0.0), (0.064, 0.053, 0.034, 2.5, 0.010, 0.006, 0.0),
               (0.068, 0.053, 0.038, 2.4, 0.006, 0.010, 0.0), (0.064, 0.050, 0.042, 2.3, 0.0, 0.006, 0.0),
               (0.010, 0.010, 0.010, 2.0, 0.0, 0.0, 0.0)]
JAW_HINGE, JAW_OPEN = V((0, -1.02, 0.340)), 10.0
_JAW = [(0, -1.243, 0.322), (0, -1.220, 0.320), (0, -1.160, 0.318), (0, -1.100, 0.318), (0, -1.050, 0.320),
        (0, -1.010, 0.326), (0, -0.990, 0.330)]
JAW_PTS = [JAW_HINGE + Matrix.Rotation(rad(JAW_OPEN), 3, "X") @ (V(p) - JAW_HINGE) for p in _JAW]
# lower jaw half-width 87-90 % of the upper jaw at the same station; deep jaw (Komodo bite muscles)
JAW_SHAPES = [(0.012, 0.010, 0.010, 2.0), (0.036, 0.011, 0.015, 2.3), (0.045, 0.013, 0.021, 2.4), (0.051, 0.015, 0.026, 2.4),
              (0.057, 0.017, 0.032, 2.4), (0.059, 0.021, 0.040, 2.3), (0.010, 0.010, 0.010, 2.0)]
# sprawling limbs (left side): humerus/femur outward, elbow/knee out and down, forearm/shin near vertical
FRONT_PTS = [(0.08, -0.62, 0.330), (0.16, -0.62, 0.300), (0.235, -0.600, 0.245), (0.250, -0.610, 0.200),
             (0.252, -0.625, 0.140), (0.255, -0.650, 0.075), (0.255, -0.665, 0.048)]
# dry run 1: legs read thin and long; the scan's limbs are heavy and muscular -> +20-32 % below the root
FRONT_SHAPES = [(0.070, 0.080, 0.080, 2.2), (0.066, 0.072, 0.072, 2.2), (0.060, 0.060, 0.065, 2.2), (0.056, 0.055, 0.059, 2.2),
                (0.052, 0.052, 0.053, 2.2), (0.041, 0.039, 0.041, 2.2), (0.037, 0.032, 0.037, 2.2)]
HIND_PTS = [(0.08, 0.06, 0.330), (0.17, 0.075, 0.300), (0.265, 0.040, 0.245), (0.280, 0.060, 0.200),
            (0.282, 0.090, 0.140), (0.284, 0.125, 0.075), (0.285, 0.140, 0.048)]
HIND_SHAPES = [(0.092, 0.102, 0.102, 2.2), (0.092, 0.098, 0.101, 2.2), (0.074, 0.073, 0.078, 2.2), (0.065, 0.064, 0.068, 2.2),
               (0.059, 0.058, 0.060, 2.2), (0.045, 0.041, 0.045, 2.2), (0.041, 0.034, 0.041, 2.2)]
BROW, CHEEK = rad(40), rad(-15)
FRONT_IN, BACK_IN = dirn(-0.7, 0.7, 0), dirn(-0.7, -0.7, 0)
HEAD_TOL = 0.10


def S(brush, r, strength, view, pts, label, target=None, passes=1, mode="NORMAL"):
    return sd.spec(brush, r, strength, view, pts, label, target=target, mode=mode, passes=passes)


def vol(name, kind, a, b, width, protrude, **kw):
    return dict(name=name, kind=kind, a=a, b=b, width=width, protrude=protrude, **kw)


def toes(spread, lengths, radius, claw):
    return [{"angle": a, "length": L, "radius": radius, "claw": claw} for a, L in zip(spread, lengths)]


class Komodo(ck.Creature):
    name = "komodo"
    prefix = "KMD_"
    settings = os.path.join(HERE, "komodo_settings.json")
    palette = {"skin": {"hex": "#6A6150"}, "belly": {"hex": "#8C8268"}, "horn_base": {"hex": "#3E3A32"},
               "horn_tip": {"hex": "#6E675A"}, "spike_base": {"hex": "#4A4538"}, "spike_tip": {"hex": "#6E675A"},
               "claw_base": {"hex": "#3A352E"}, "claw_tip": {"hex": "#1A1815"}, "eye": {"hex": "#8A5A22"},
               "tooth": {"hex": "#E2D8BE"}, "gum": {"hex": "#B76F6A"}, "tongue": {"hex": "#D9B13C"}}
    stripes = None
    head_y, head_z, tail_y = (-1.03, -0.98), (0.22, 0.27), (0.15, 0.35)
    mouth = {"head_pts": HEAD_PTS, "head_shapes": HEAD_SHAPES, "y_back": JAW_HINGE.y,
             "teeth": {"spacing": 0.011, "upper": 0.009, "lower": 0.007, "fangs_upper": (), "fangs_lower": (), "fang_scale": 1.0}}
    # build 1: an 11 mm eye in a 13 mm socket read as a ball in a hole; the eye now fills the socket and the lids close more
    eye = {"radius": 0.0135, "sink": 0.002, "lid_up": (22, 58), "lid_lo": (18, 52)}
    # Phase B scales for a 2.7 m monitor: small bead scales everywhere (8 mm is the geometric floor at the 1.6 mm
    # high-poly; finer beads stay in the shader), rings on the tail, small rectangular belly rows, no dorsal plates
    scales = {"seed": 11,
              "granular": {"size": 0.008, "height": 0.0011},
              "limb": {"size": (0.009, 0.008), "height": 0.0010},
              "limb_plates": {"height": 0.0},
              "dorsal": {"size": (0.010, 0.009), "height": 0.0012, "keel": 0.0},
              "paravertebral": {"height": 0.0},
              "ventral": {"row": 0.014, "height": 0.0011},
              "tail": {"size": (0.012, 0.011), "height": 0.0013, "jitter": 0.35},
              "head": {"size": 0.009, "height": 0.0012},
              "head_plates": {"size": 0.013, "height": 0.0015},
              "toe": {"row": 0.008, "height": 0.0009}}

    def spine(self):
        return [HEAD_PTS[0], V((0, -1.15, 0.357)), V((0, -1.06, 0.366))] + [V(p) for p in TRUNK_PTS]

    def field_chains(self):
        return [("front", [V(p) for p in FRONT_PTS[1:]]), ("hind", [V(p) for p in HIND_PTS[1:]])]

    def build_base(self):
        trunk = pm.Part("trunk")
        self.info["trunk_path"] = trunk.sweep(TRUNK_PTS, TRUNK_SHAPES, "skin", N=32, step=0.020, start="cap", end="tip", tip=1.5,
                                              bumps=[(1.5 * math.pi, 0.35, 4), (0.5 * math.pi, 0.22, 5)])
        head = pm.Part("head")
        head.sweep(HEAD_PTS, HEAD_SHAPES, "skin", N=44, step=0.006, start="tip", end="tip",
                   bumps=[(BROW, 0.28, 4), (math.pi - BROW, 0.28, 4), (CHEEK, 0.40, 5), (math.pi - CHEEK, 0.40, 5), (0.5 * math.pi, 0.15, 6)])
        head.sweep(JAW_PTS, JAW_SHAPES, "skin", N=26, step=0.007, start="tip", end="tip")
        limbs = pm.Part("limbs")
        limbs.sweep(FRONT_PTS, FRONT_SHAPES, "skin", N=18, step=0.014, frame="hint", hint=X, start="cap", end="cap")
        limbs.sweep(HIND_PTS, HIND_SHAPES, "skin", N=18, step=0.014, frame="hint", hint=X, start="cap", end="cap")
        # five toes with long claws; front feet turned 20 deg out, hind feet 35 deg out
        ffwd = V((math.sin(rad(20)), -math.cos(rad(20)), 0))
        ck.paw(self, limbs, (0.258, -0.690, 0.026), ffwd,
               toes((-48, -22, 0, 20, 42), (0.040, 0.056, 0.064, 0.058, 0.044), 0.0125, 0.040), palm_scale=0.85)
        hfwd = V((math.sin(rad(35)), -math.cos(rad(35)), 0))
        ck.paw(self, limbs, (0.292, 0.115, 0.026), hfwd,
               toes((-52, -24, 0, 22, 50), (0.044, 0.062, 0.072, 0.066, 0.046), 0.0135, 0.042), palm_scale=0.92)
        limbs.mirror_x()
        bm = bmesh.new()
        for part in (trunk, head, limbs):
            me = bpy.data.meshes.new("tmp")
            part.bm.to_mesh(me)
            part.bm.free()
            bm.from_mesh(me)
            bpy.data.meshes.remove(me)
        return bm

    def anatomy(self, tree):
        return [
            vol("jaw adductor", "muscle", ((0.0, -1.055, 0.352), lateral(5)), ((0.0, -1.012, 0.350), lateral(0)), 0.030, 0.009, tol=HEAD_TOL),
            vol("supraocular ridge", "ridge", ((0.0, -1.100, 0.378), lateral(42)), ((0.0, -1.040, 0.382), lateral(42)), 0.016, 0.006, tol=HEAD_TOL),
            vol("neck muscle", "muscle", ((0.0, -0.98, 0.385), lateral(25)), ((0.0, -0.76, 0.370), lateral(25)), 0.050, 0.010),
            vol("shoulder", "muscle", ((0.10, -0.68, 0.40), dirn(-0.4, 0, -0.9)), ((0.20, -0.62, 0.31), SIDE), 0.052, 0.014),
            vol("thigh", "muscle", ((0.12, 0.02, 0.41), dirn(-0.4, 0, -0.9)), ((0.22, 0.07, 0.31), SIDE), 0.064, 0.016),
            # (dry run 2: from y 0.12 the side ray hit the thicker thigh first; start behind it with a short ray)
            vol("caudofemoralis", "muscle", ((0.09, 0.19, 0.33), SIDE, 0.15), ((0.07, 0.44, 0.27), SIDE, 0.15), 0.050, 0.010),
        ]

    def strokes(self):
        # loose neck skin (reference: NHM Vienna scan). Build 1 used thin creases on straight lines and read as panel cuts
        # in a grid; the scan shows soft rolls with deep grooves between, wavy and unevenly spaced: raise the rolls, then
        # crease only the grooves between them
        rolls, grooves = [], []
        for i, (y, dy) in enumerate(((-0.962, 0.010), (-0.921, -0.008), (-0.882, 0.012), (-0.838, -0.006), (-0.796, 0.009))):
            rolls.append(S("Clay", 0.011, 0.35, SIDE, [(0.058, y, 0.410), (0.074, y + dy, 0.372), (0.080, y - dy * 0.6, 0.334), (0.068, y + dy * 0.4, 0.298)],
                           f"neck roll {i + 1}", target=3.0))
            if i:
                g = y + 0.021
                grooves.append(S("Crease Sharp", 0.008, 0.25, SIDE, [(0.060, g, 0.405), (0.076, g + dy * 0.5, 0.365), (0.080, g - dy * 0.4, 0.330), (0.068, g, 0.300)],
                                 f"neck groove {i}", target=1.8))
        neck_folds = rolls + grooves
        return [
            ("junctions", [
                S("Smooth", 0.05, 0.6, SIDE, [(0.17, -0.66, 0.31), (0.19, -0.62, 0.30), (0.17, -0.58, 0.30)], "shoulder junction", passes=3),
                S("Smooth", 0.06, 0.6, SIDE, [(0.17, 0.02, 0.32), (0.19, 0.07, 0.31), (0.17, 0.12, 0.31)], "thigh junction", passes=3),
                S("Smooth", 0.04, 0.6, dirn(-1, 0.3, -0.3), [(0.06, -1.02, 0.34), (0.06, -0.98, 0.38)], "neck-skull junction", passes=3),
                S("Smooth", 0.025, 0.6, SIDE, [(0.285, -0.665, 0.03), (0.285, -0.655, 0.07)], "front wrist-paw junction", passes=3),
                S("Smooth", 0.025, 0.6, SIDE, [(0.32, 0.14, 0.03), (0.32, 0.13, 0.07)], "hind ankle-paw junction", passes=3)]),
            ("secondary", [
                S("Clay Strips", 0.020, 0.35, SIDE, [(0.16, -0.50, 0.33), (0.168, -0.30, 0.33), (0.16, -0.10, 0.33)], "lateral fold line", target=2.5),
                S("Clay", 0.030, 0.35, TOP, [(0.05, 0.12, 0.42), (0.04, 0.30, 0.39)], "tail root muscle", target=3.0),
                S("Inflate/Deflate", 0.022, 0.3, dirn(-0.6, -0.3, -0.5), [(0.25, -0.60, 0.24), (0.27, -0.61, 0.20)], "forearm extensors", target=3.0),
                S("Inflate/Deflate", 0.026, 0.3, dirn(-0.6, 0.3, -0.5), [(0.29, 0.05, 0.24), (0.31, 0.08, 0.19)], "calf", target=3.0)]),
            ("polish", [
                S("Smooth", 0.06, 0.35, SIDE, [(0.15, -0.55, 0.36), (0.165, -0.30, 0.36), (0.15, -0.05, 0.36)], "polish flank", passes=2),
                S("Smooth", 0.05, 0.35, TOP, [(0.06, -0.60, 0.42), (0.06, -0.30, 0.42), (0.06, 0.00, 0.42)], "polish back", passes=2)]),
            ("tertiary", neck_folds + [
                S("Clay", 0.010, 0.3, SIDE, [(0.074, -0.95, 0.352), (0.082, -0.90, 0.346), (0.088, -0.86, 0.344)], "neck roll long 1", target=2.0),
                S("Clay", 0.010, 0.3, SIDE, [(0.088, -0.84, 0.322), (0.095, -0.80, 0.318), (0.100, -0.76, 0.320)], "neck roll long 2", target=2.0),
                S("Crease Sharp", 0.007, 0.3, dirn(0, 0.3, 1), [(0.0, -0.975, 0.292), (0.035, -0.968, 0.296), (0.058, -0.955, 0.310)], "gular fold 1", target=2.5),
                S("Crease Sharp", 0.007, 0.3, dirn(0, 0.3, 1), [(0.0, -0.925, 0.280), (0.040, -0.918, 0.285), (0.065, -0.905, 0.300)], "gular fold 2", target=2.5),
                S("Crease Sharp", 0.007, 0.3, dirn(0, 0.3, 1), [(0.0, -0.870, 0.265), (0.045, -0.862, 0.270), (0.072, -0.850, 0.288)], "gular fold 3", target=2.0),
                S("Crease Sharp", 0.008, 0.3, SIDE, [(0.15, -0.58, 0.28), (0.165, -0.55, 0.25)], "axillary fold", target=2.5),
                S("Crease Sharp", 0.008, 0.3, SIDE, [(0.15, 0.00, 0.28), (0.17, 0.03, 0.25)], "inguinal fold", target=2.5),
                S("Crease Sharp", 0.006, 0.25, dirn(-1, 0.3, 0), [(0.25, -0.585, 0.24), (0.255, -0.575, 0.21)], "elbow fold", target=1.5),
                S("Crease Sharp", 0.006, 0.25, dirn(-1, -0.3, 0), [(0.285, 0.025, 0.24), (0.29, 0.035, 0.21)], "knee fold", target=1.5)]),
        ]

    def features(self, tree):
        sh = ck.surface_hit
        return [{"name": "eye", "ref": sh(tree, (0.0, -1.068, 0.372), lateral(18, 8)), "radius": 0.0145, "depth": 0.004, "rim": 0.003, "upper": 2.2},
                {"name": "nostril", "ref": sh(tree, (0.0, -1.215, 0.356), lateral(28, 20)), "radius": 0.006, "depth": 0.006, "rim": 0.0015},
                {"name": "ear", "ref": sh(tree, (0.0, -0.995, 0.362), lateral(5, 0)), "radius": 0.010, "depth": 0.003, "rim": 0.001}]

    def inserts(self, ctx):
        claws = pm.Part(self.prefix + "Claws")
        self.log["claw_drop"] = [round(ck.claw(claws, tip, d, cl, r), 3) for tip, d, r, cl in self.toe_tips]
        # the long yellow forked tongue, flicked out of the slightly open mouth (the kit's tongue stays on the jaw floor)
        tongue = pm.Part(self.prefix + "Tongue")
        path = [V((0, -1.08, 0.316)), V((0, -1.18, 0.314)), V((0, -1.26, 0.311)), V((0, -1.33, 0.306))]
        tongue.sweep(path, [(0.011, 0.0045, 0.0045, 2.4), (0.010, 0.0042, 0.0042, 2.4), (0.008, 0.0036, 0.0036, 2.4),
                            (0.0065, 0.003, 0.003, 2.3)], "tongue", N=14, step=0.006, frame="h", start="cap", end="cap")
        F, f = path[-1], (path[-1] - path[-2]).normalized()
        for s in (1, -1):
            tip = F + f * 0.050 + V((0.016 * s, 0, -0.004))
            tongue.sweep([F - f * 0.006, F + f * 0.022 + V((0.006 * s, 0, -0.001)), tip],
                         [(0.0045, 0.0028, 0.0028, 2.2), (0.0032, 0.002, 0.002, 2.2), (0.0006, 0.0006, 0.0006, 2.0)],
                         "tongue", N=10, step=0.004, frame="h", start="cap", end="tip", tip=1.0)
        self.log["tongue_out_mm"] = round((F.y + 0.05 - HEAD_PTS[0].y) * -1000, 1)
        return [(claws, True), (tongue, False)]


if __name__ == "__main__":
    ck.run(Komodo(), __file__)
