"""Raptor - a stylized bipedal dromaeosaur built with creature_kit (skill test creature #2 after the dragon).

Anatomy choices (checked as numbers, see SKILL.md step 1):
  bipedal, body horizontal, hips over the feet, stiff tail as counterbalance; digitigrade legs (thigh forward,
  shin back, metatarsus forward); toe II raised with a sickle claw, toes III/IV bear weight, small hallux;
  three-fingered grasping arms; long low skull, lower jaw reaching to 1.3 cm behind the snout tip at 87-90 %
  of the upper jaw's width, mouth open 14 degrees; forward-tilted large eyes under brow ridges with small
  lacrimal horns; low dorsal osteoderm row; olive-brown with dorsal bands and a sand belly.

  GUI:     blender --factory-startup --window-geometry 0 0 1400 1000 --python raptor.py
  Dry run: CREATURE_DRY_RUN=1 blender -b --factory-startup --python raptor.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# the kit: CREATURE_KIT_DIR if this file was copied into a project, else the skill's own scripts/ folder
sys.path.insert(0, os.environ.get("CREATURE_KIT_DIR") or os.path.normpath(os.path.join(HERE, "..", "..", "scripts")))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402

import creature_kit as ck  # noqa: E402
import proc_mesh as pm  # noqa: E402
import sculpt_driver as sd  # noqa: E402
from creature_kit import V, X, Y, Z, SIDE, TOP, dirn, rad  # noqa: E402

TRUNK_PTS = [(0, -0.78, 1.205), (0, -0.70, 1.13), (0, -0.62, 1.04), (0, -0.53, 0.975), (0, -0.40, 0.945), (0, -0.20, 0.935),
             (0, 0.02, 0.945), (0, 0.22, 0.965), (0, 0.45, 0.95), (0.02, 0.72, 0.90), (0.05, 1.02, 0.83), (0.08, 1.32, 0.76),
             (0.10, 1.58, 0.71), (0.11, 1.80, 0.68)]
TRUNK_SHAPES = [(0.058, 0.060, 0.064, 2.0, 0.0, 0.0), (0.058, 0.058, 0.066, 2.1, 0.0, 0.003), (0.062, 0.060, 0.072, 2.2, 0.0, 0.004),
                (0.078, 0.072, 0.092, 2.2, 0.004, 0.005), (0.125, 0.110, 0.165, 2.3, 0.016, 0.006),
                (0.145, 0.128, 0.170, 2.4, 0.010, 0.008), (0.128, 0.122, 0.135, 2.4, 0.0, 0.008),
                (0.165, 0.122, 0.122, 2.4, 0.0, 0.008), (0.112, 0.100, 0.092, 2.3, 0.0, 0.007),
                (0.072, 0.070, 0.060, 2.2, 0.0, 0.006), (0.046, 0.047, 0.040, 2.1, 0.0, 0.004),
                (0.029, 0.030, 0.026, 2.0, 0.0, 0.003), (0.016, 0.017, 0.015, 2.0, 0.0, 0.001), (0.003, 0.003, 0.003, 2.0, 0.0, 0.0)]
HEAD_PTS = [V(p) for p in [(0, -1.150, 1.157), (0, -1.125, 1.160), (0, -1.04, 1.172), (0, -0.96, 1.186), (0, -0.89, 1.202),
                           (0, -0.83, 1.214), (0, -0.78, 1.214), (0, -0.745, 1.205), (0, -0.725, 1.20)]]
HEAD_SHAPES = [(0.010, 0.010, 0.010, 2.0, 0.0, 0.0, 0.0), (0.026, 0.024, 0.020, 2.4, 0.0, 0.0, 0.0),
               (0.034, 0.032, 0.026, 2.6, 0.0, 0.0, 0.0), (0.042, 0.040, 0.032, 2.6, 0.004, 0.002, 0.0),
               (0.056, 0.052, 0.040, 2.6, 0.016, 0.008, 0.003), (0.068, 0.060, 0.048, 2.5, 0.010, 0.014, 0.004),
               (0.066, 0.058, 0.052, 2.4, 0.002, 0.010, 0.0), (0.048, 0.046, 0.046, 2.2, 0.0, 0.0, 0.0),
               (0.008, 0.008, 0.008, 2.0, 0.0, 0.0, 0.0)]
JAW_HINGE, JAW_OPEN = V((0, -0.80, 1.165)), 14.0
_JAW = [(0, -1.137, 1.130), (0, -1.115, 1.127), (0, -1.04, 1.128), (0, -0.96, 1.132), (0, -0.89, 1.140), (0, -0.82, 1.152), (0, -0.79, 1.160)]
JAW_PTS = [JAW_HINGE + Matrix.Rotation(rad(JAW_OPEN), 3, "X") @ (V(p) - JAW_HINGE) for p in _JAW]
JAW_SHAPES = [(0.010, 0.009, 0.009, 2.0), (0.023, 0.012, 0.010, 2.4), (0.030, 0.014, 0.014, 2.6), (0.037, 0.016, 0.018, 2.6),
              (0.049, 0.019, 0.024, 2.5), (0.060, 0.024, 0.032, 2.4), (0.010, 0.010, 0.010, 2.0)]
ARM_PTS = [(0.05, -0.43, 0.90), (0.10, -0.42, 0.86), (0.135, -0.37, 0.78), (0.145, -0.33, 0.72), (0.14, -0.37, 0.675),
           (0.13, -0.44, 0.645), (0.125, -0.47, 0.635)]
ARM_SHAPES = [(0.060, 0.070, 0.070, 2.2), (0.048, 0.054, 0.054, 2.2), (0.036, 0.040, 0.040, 2.2), (0.030, 0.033, 0.031, 2.2),
              (0.026, 0.027, 0.026, 2.2), (0.022, 0.020, 0.022, 2.2), (0.020, 0.018, 0.020, 2.2)]
LEG_PTS = [(0.09, 0.24, 0.93), (0.15, 0.21, 0.85), (0.175, 0.14, 0.72), (0.18, 0.08, 0.58), (0.178, 0.10, 0.52),
           (0.175, 0.18, 0.38), (0.172, 0.26, 0.24), (0.17, 0.275, 0.20), (0.17, 0.255, 0.12), (0.17, 0.22, 0.05)]
LEG_SHAPES = [(0.100, 0.125, 0.125, 2.2), (0.100, 0.135, 0.130, 2.3), (0.090, 0.120, 0.110, 2.3), (0.066, 0.070, 0.066, 2.2),
              (0.056, 0.060, 0.056, 2.2), (0.048, 0.054, 0.046, 2.2), (0.034, 0.036, 0.034, 2.2), (0.036, 0.040, 0.036, 2.2),
              (0.028, 0.030, 0.028, 2.2), (0.030, 0.026, 0.028, 2.2)]
WRIST = V(ARM_PTS[-1])
FINGERS = [(-0.28, 0.045), (0.0, 0.060), (0.26, 0.050)]  # lateral spread, length
BROW, CHEEK = rad(55), rad(-15)


def finger_dir(spread):
    return (dirn(0, -0.75, -0.66) + X * spread).normalized()


class Raptor(ck.Creature):
    name = "raptor"
    prefix = "RAP_"
    settings = os.path.join(HERE, "raptor_settings.json")
    palette = {"skin": {"hex": "#5A4E2E"}, "belly": {"hex": "#C4B48A"}, "horn_base": {"hex": "#3E3122"},
               "horn_tip": {"hex": "#8A7350"}, "spike_base": {"hex": "#4A3D28"}, "spike_tip": {"hex": "#7D6A4A"},
               "claw_base": {"hex": "#3A3530"}, "claw_tip": {"hex": "#0F0E0D"}, "eye": {"hex": "#E0A526"},
               "tooth": {"hex": "#E8E0C8"}, "gum": {"hex": "#7A3A3E"}, "tongue": {"hex": "#8E4552"}}
    stripes = {"period": 0.11, "darkness": 0.55, "width": 0.30}
    head_y, head_z, tail_y = (-0.79, -0.74), (0.98, 1.04), (0.50, 0.75)
    mouth = {"head_pts": HEAD_PTS, "head_shapes": HEAD_SHAPES, "y_back": JAW_HINGE.y,
             "teeth": {"spacing": 0.017, "upper": 0.017, "lower": 0.014, "fangs_upper": (1,), "fangs_lower": (), "fang_scale": 1.35},
             "tongue": {"width": 0.014, "reach": 0.45, "fork": 0.0, "min_gap": 0.016}}
    eye = {"radius": 0.019, "sink": 0.003, "lid_up": (20, 47), "lid_lo": (15, 42)}

    def spine(self):
        return [HEAD_PTS[0], V((0, -1.0, 1.18)), V((0, -0.85, 1.21))] + [V(p) for p in TRUNK_PTS[1:]]

    def field_chains(self):
        return [("front", [V(p) for p in ARM_PTS[1:]]), ("hind", [V(p) for p in LEG_PTS[1:]])]

    def build_base(self):
        trunk = pm.Part("trunk")
        self.info["trunk_path"] = trunk.sweep(TRUNK_PTS, TRUNK_SHAPES, "skin", N=32, step=0.022, start="cap", end="tip", tip=1.5,
                                              bumps=[(1.5 * math.pi, 0.35, 4), (0.5 * math.pi, 0.22, 5)])
        head = pm.Part("head")
        head.sweep(HEAD_PTS, HEAD_SHAPES, "skin", N=44, step=0.006, start="tip", end="tip",
                   bumps=[(BROW, 0.28, 4), (math.pi - BROW, 0.28, 4), (CHEEK, 0.40, 5), (math.pi - CHEEK, 0.40, 5), (0.5 * math.pi, 0.15, 6)])
        head.sweep(JAW_PTS, JAW_SHAPES, "skin", N=26, step=0.008, start="tip", end="tip")
        limbs = pm.Part("limbs")
        limbs.sweep(ARM_PTS, ARM_SHAPES, "skin", N=16, step=0.014, frame="hint", hint=X, start="cap", end="cap")
        for spread, L in FINGERS:  # grasping hand: three fingers, fused (18 mm thick = 5 voxels)
            d = finger_dir(spread)
            chain = [WRIST - d * 0.01, WRIST + d * L * 0.5 + V((0, 0, -0.004)), WRIST + d * L + V((0, 0, -0.010))]
            limbs.sweep(chain, [(0.010, 0.010, 0.010, 2.2), (0.0095, 0.009, 0.009, 2.2), (0.0075, 0.007, 0.007, 2.2)],
                        "skin", N=10, step=0.008, start="cap", end="tip", tip=0.8)
            self.toe_chains.append(chain)
            self.toe_tips.append((chain[-1] + d * 0.002, (d + V((0, -0.5, 0.25))).normalized(), 0.0068, 0.027))
        limbs.sweep(LEG_PTS, LEG_SHAPES, "skin", N=20, step=0.016, frame="hint", hint=X, start="cap", end="cap")
        limbs.sweep([V(LEG_PTS[4]) + V((0.0, -0.03, 0.0)), V(LEG_PTS[4]) + V((0.0, 0.01, 0.0))],
                    [(0.050, 0.040, 0.040, 2.0), (0.046, 0.036, 0.036, 2.0)], "skin", N=14, step=0.01, start="tip", end="tip", tip=0.7)  # kneecap
        ck.paw(self, limbs, (0.17, 0.20, 0.028), (math.sin(rad(6)), -math.cos(rad(6)), 0),
               toes=[{"angle": -24, "length": 0.050, "radius": 0.016, "claw": 0.075, "lift": 0.045},   # II: raised sickle claw
                     {"angle": 0, "length": 0.090, "radius": 0.018, "claw": 0.034},                    # III
                     {"angle": 22, "length": 0.078, "radius": 0.017, "claw": 0.030}],                  # IV
               palm_scale=0.95,
               back_toe={"direction": -150, "length": 0.022, "radius": 0.009, "claw": 0.016, "offset": (-0.02, 0.035, 0.045), "down": -0.3})
        limbs.mirror_x()
        bm = bmesh.new()
        for part in (trunk, head, limbs):
            me = bpy.data.meshes.new("tmp")
            part.bm.to_mesh(me)
            part.bm.free()
            bm.from_mesh(me)
            bpy.data.meshes.remove(me)
        return bm

    def strokes(self):
        S = sd.spec
        return [
            ("junctions", [
                S("Smooth", 0.06, 0.6, SIDE, [(0.20, 0.15, 0.90), (0.22, 0.25, 0.88), (0.20, 0.35, 0.86)], "hip-thigh junction", passes=3),
                S("Smooth", 0.04, 0.6, SIDE, [(0.12, -0.45, 0.88), (0.14, -0.40, 0.84)], "shoulder-arm junction", passes=3),
                S("Smooth", 0.04, 0.6, dirn(-1, 0.3, -0.3), [(0.06, -0.76, 1.16), (0.05, -0.72, 1.20)], "neck-skull junction", passes=3),
                S("Smooth", 0.025, 0.6, SIDE, [(0.19, 0.21, 0.05), (0.19, 0.24, 0.10)], "ankle-foot junction", passes=3)]),
            ("secondary", [
                S("Clay Strips", 0.012, 0.5, dirn(-0.6, 0.6, -0.5), [(0.03, -0.92, 1.245), (0.05, -0.89, 1.245), (0.065, -0.86, 1.24)], "brow ridge", target=3.0),
                S("Crease Sharp", 0.010, 0.4, dirn(-1, 0, 0.35), [(0.05, -0.86, 1.12), (0.06, -0.81, 1.13)], "jaw angle", target=2.5),
                S("Inflate/Deflate", 0.018, 0.3, SIDE, [(0.07, -0.83, 1.17), (0.07, -0.80, 1.18)], "masseter", target=3.5),
                S("Clay", 0.022, 0.4, SIDE, [(0.06, -0.75, 1.15), (0.06, -0.67, 1.06), (0.07, -0.58, 0.99), (0.10, -0.50, 0.96)], "neck muscle", target=3.0),
                S("Inflate/Deflate", 0.035, 0.3, dirn(-0.4, 1, 0.3), [(0.03, -0.50, 0.80), (0.08, -0.47, 0.80), (0.11, -0.42, 0.82)], "pectoral", target=5.0),
                S("Clay", 0.016, 0.25, SIDE, [(0.15, -0.30, 0.98), (0.15, -0.26, 0.84)], "rib 1", target=2.0),
                S("Clay", 0.016, 0.25, SIDE, [(0.15, -0.20, 0.99), (0.15, -0.16, 0.85)], "rib 2", target=2.0),
                S("Clay", 0.016, 0.25, SIDE, [(0.145, -0.10, 0.99), (0.14, -0.06, 0.86)], "rib 3", target=2.0),
                S("Inflate/Deflate", 0.045, 0.3, SIDE, [(0.24, 0.20, 0.86), (0.25, 0.15, 0.75), (0.24, 0.11, 0.65)], "thigh (iliotibialis)", target=6.0),
                S("Inflate/Deflate", 0.040, 0.3, dirn(-1, -0.3, 0), [(0.17, 0.32, 0.88), (0.15, 0.45, 0.90), (0.12, 0.60, 0.89)], "caudofemoralis", target=5.0),
                S("Inflate/Deflate", 0.030, 0.3, dirn(-1, -0.4, 0), [(0.21, 0.14, 0.48), (0.20, 0.20, 0.38)], "gastrocnemius", target=4.0),
                S("Inflate/Deflate", 0.020, 0.3, SIDE, [(0.16, -0.40, 0.83), (0.17, -0.36, 0.77)], "biceps", target=3.0),
                S("Clay", 0.030, 0.35, TOP, [(0.05, 0.48, 1.03), (0.05, 0.65, 0.97)], "tail root muscle", target=3.0)]),
            ("polish", [
                S("Smooth", 0.05, 0.35, dirn(-0.4, 1, 0.3), [(0.03, -0.50, 0.80), (0.09, -0.46, 0.80), (0.12, -0.40, 0.84)], "polish chest", passes=2),
                S("Smooth", 0.05, 0.35, SIDE, [(0.15, -0.30, 0.95), (0.14, -0.05, 0.95), (0.15, 0.10, 0.95)], "polish flank", passes=2),
                S("Smooth", 0.05, 0.35, SIDE, [(0.24, 0.20, 0.85), (0.25, 0.14, 0.72), (0.23, 0.10, 0.62)], "polish thigh", passes=2)]),
            ("tertiary", [
                S("Crease Sharp", 0.006, 0.25, SIDE, [(0.06, -0.70, 1.16), (0.065, -0.67, 1.12), (0.06, -0.64, 1.09)], "neck fold 1", target=2.0),
                S("Crease Sharp", 0.006, 0.25, SIDE, [(0.065, -0.66, 1.09), (0.07, -0.62, 1.05), (0.065, -0.59, 1.02)], "neck fold 2", target=2.0),
                S("Crease Sharp", 0.007, 0.3, dirn(0, 0.68, 0.73), [(0.0, -0.745, 1.090), (0.035, -0.738, 1.097), (0.05, -0.722, 1.115)], "gular fold 1", target=2.0),
                S("Crease Sharp", 0.007, 0.3, dirn(0, 0.75, 0.66), [(0.0, -0.705, 1.045), (0.035, -0.698, 1.052), (0.052, -0.682, 1.070)], "gular fold 2", target=2.0),
                S("Crease Sharp", 0.007, 0.3, SIDE, [(0.13, -0.33, 0.86), (0.14, -0.31, 0.80)], "axillary fold", target=2.0),
                S("Crease Sharp", 0.008, 0.3, SIDE, [(0.17, 0.08, 0.92), (0.19, 0.06, 0.84), (0.21, 0.07, 0.76)], "inguinal fold", target=2.5),
                S("Crease Sharp", 0.006, 0.25, dirn(-1, 0.5, 0), [(0.20, 0.06, 0.58), (0.20, 0.05, 0.53)], "knee fold", target=1.5),
                S("Draw", 0.006, 0.3, dirn(0, -1, -0.3), [(0.172, 0.245, 0.33), (0.171, 0.285, 0.26), (0.17, 0.30, 0.21)], "Achilles tendon", target=1.5)]),
        ]

    def features(self, tree):
        sh = ck.surface_hit
        return [{"name": "eye", "ref": sh(tree, (0.0, -0.875, 1.215), ck.lateral(12, 12)), "radius": 0.023, "depth": 0.008, "rim": 0.004, "upper": 2.0},
                {"name": "nostril", "ref": sh(tree, (0.0, -1.112, 1.165), ck.lateral(55, 25)), "radius": 0.008, "depth": 0.007, "rim": 0.002},
                {"name": "ear", "ref": sh(tree, (0.0, -0.772, 1.205), ck.lateral(5, 0)), "radius": 0.010, "depth": 0.003, "rim": 0.001}]

    def inserts(self, ctx):
        tree, rng = ctx["tree"], ctx["rng"]
        horns = pm.Part(self.prefix + "Horns")  # small lacrimal horns over the eyes
        base, nrm = ck.surface_hit(tree, (0.0, -0.865, 1.245), ck.lateral(50, -5))
        d = (nrm * 0.55 + Y * 0.65 + Z * 0.35).normalized()
        base = base - nrm * 0.004
        horns.sweep([base, base + d * 0.016 + nrm * 0.002, base + d * 0.032], [(0.007, 0.010, 0.010, 2.0), (0.005, 0.006, 0.006, 2.0), (0.0008, 0.0008, 0.0008, 2.0)],
                    "horn", N=10, step=0.005, frame="hint", hint=Z, tip=1.0)
        spikes = pm.Part(self.prefix + "DorsalScutes")
        self.log["dorsal_scutes"] = ck.spikes_along(spikes, tree, self.info["trunk_path"], [(0.0, 0.008), (0.15, 0.014), (0.35, 0.018), (0.55, 0.014), (0.85, 0.006), (0.95, 0.003)],
                                                    0.05, rng, alternate=0.7, rake=0.4)
        claws = pm.Part(self.prefix + "Claws")
        self.log["claw_drop"] = [round(ck.claw(claws, tip, d, cl, r), 3) for tip, d, r, cl in self.toe_tips]
        return [(horns, True), (spikes, False), (claws, True)]


if __name__ == "__main__":
    ck.run(Raptor(), __file__)
