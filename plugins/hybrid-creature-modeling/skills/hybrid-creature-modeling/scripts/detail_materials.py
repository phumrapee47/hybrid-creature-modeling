"""Experiment 6 detail-pass shaders. Colours come from the shared palette; detail is procedural.

Body skin reads per-vertex attributes written by dragon_detail.py:
  body_st  (vector)  s = arc length along the nearest body chain (m), t = arc length around it (m)
  w_up     0 ventral .. 1 dorsal (countershading)
  w_dorsal, w_belly, w_head, w_tail, w_foot, w_lip, w_mouth   region weights
Scale patterns (all in body coordinates, so they follow the body's flow):
  granular flank/limb scales, keeled dorsal osteoderm scales, transverse ventral scutes,
  ring scales on the tail, head plates, toe scutes, labial (lip) scales; smooth wet gums in the mouth.
"""
import math

import bpy

import material_palette as mp

PFX = "DRG6_"
PAL = dict(mp.PALETTE)   # reset to mp.PALETTE and updated per creature by build_all(palette=...)
GEO_SCALES = False       # True: scales are geometry (scale_field); the shader follows scale_h / scale_tint
STRIPES = None           # e.g. {"period": 0.12, "darkness": 0.55, "width": 0.35}; dorsal/flank bands across the body axis

# v1.3 material profiles: a surface-plan region's material_profile is a build_all key ("claw", v1.2 look) or a
# variant of one ("claw:matte"), which changes only the parameters listed here.
VARIANTS = {
    "claw:matte": {"rough": 0.42, "coat": 0.06},     # dry keratin; v1.2 claws (rough 0.28, coat 0.35) read as lacquered
    "horn:matte": {"rough": 0.55, "coat": 0.0},
    "spike:matte": {"rough": 0.55, "coat": 0.0},
    "tooth:enamel": {"rough": 0.30, "coat": 0.25, "sss": 0.25},
    "body:sss": {"sss": 0.06, "sss_radius": (1.0, 0.35, 0.2), "sss_scale": 0.004},   # light through thin skin
}
PROFILE = {}             # material key -> variant parameters, set by build_all(profiles=...)


def sss_inputs(key):
    """Principled inputs for the profile's subsurface scattering ({} when the profile has none)."""
    v = PROFILE.get(key, {})
    if not v.get("sss"):
        return {}
    return {"Subsurface Weight": v["sss"], "Subsurface Radius": v.get("sss_radius", (0.6, 0.45, 0.3)),
            "Subsurface Scale": v.get("sss_scale", 0.004)}


def lin(hex_str):
    return (*mp.hex_to_linear(hex_str), 1.0)


def sock(coll, key):
    for s in coll:
        if s.enabled and (s.identifier == key or s.name == key):
            return s
    raise KeyError(key)


class NB:
    """Tiny node-tree builder."""

    def __init__(self, name):
        self.mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        self.mat.use_nodes = True
        self.nt = self.mat.node_tree
        self.nt.nodes.clear()
        self.out = self.nt.nodes.new("ShaderNodeOutputMaterial")

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, src, dst):
        self.nt.links.new(src, dst)

    def val(self, x):
        if isinstance(x, (int, float)):
            n = self.node("ShaderNodeValue")
            n.outputs[0].default_value = x
            return n.outputs[0]
        return x

    def set_in(self, n, key, x):
        s = sock(n.inputs, key)
        if isinstance(x, (int, float, tuple)):
            s.default_value = x
        else:
            self.link(x, s)

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, x in enumerate((a, b, c)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                self.link(x, n.inputs[i])
        return n.outputs[0]

    def mixf(self, f, a, b):  # a + (b - a) * f
        return self.math("MULTIPLY_ADD", f, self.math("SUBTRACT", b, a), a)

    def mixc(self, f, a, b):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX")
        for key, x in (("Factor_Float", f), ("A_Color", a), ("B_Color", b)):
            self.set_in(n, key, x)
        return sock(n.outputs, "Result_Color")

    def mulc(self, a, f):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        self.set_in(n, "Factor_Float", 1.0)
        self.set_in(n, "A_Color", a)
        g = self.node("ShaderNodeCombineColor")
        for i in range(3):
            self.link(f, g.inputs[i]) if not isinstance(f, (int, float)) else setattr(g.inputs[i], "default_value", f)
        self.link(g.outputs[0], sock(n.inputs, "B_Color"))
        return sock(n.outputs, "Result_Color")

    def attr(self, name):
        return self.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=name)

    def smooth(self, x, lo, hi, out_lo=0.0, out_hi=1.0):
        n = self.node("ShaderNodeMapRange", interpolation_type="SMOOTHSTEP")
        self.link(x, sock(n.inputs, "Value"))
        for key, v in (("From Min", lo), ("From Max", hi), ("To Min", out_lo), ("To Max", out_hi)):
            sock(n.inputs, key).default_value = v
        return sock(n.outputs, "Result")

    def vec(self, x, y, z=0.0):
        n = self.node("ShaderNodeCombineXYZ")
        for i, c in enumerate((x, y, z)):
            if isinstance(c, (int, float)):
                n.inputs[i].default_value = c
            else:
                self.link(c, n.inputs[i])
        return n.outputs[0]

    def voronoi(self, vector, scale, feature="DISTANCE_TO_EDGE", randomness=1.0, dims="2D"):
        n = self.node("ShaderNodeTexVoronoi", voronoi_dimensions=dims, feature=feature)
        self.link(vector, sock(n.inputs, "Vector"))
        sock(n.inputs, "Scale").default_value = scale
        sock(n.inputs, "Randomness").default_value = randomness
        return n

    def brick(self, vector, width, row, mortar, smooth=0.5, offset=0.5):
        n = self.node("ShaderNodeTexBrick", offset=offset, offset_frequency=2, squash=1.0, squash_frequency=2)
        self.link(vector, sock(n.inputs, "Vector"))
        for key, v in (("Scale", 1.0), ("Mortar Size", mortar), ("Mortar Smooth", smooth), ("Bias", 0.0),
                       ("Brick Width", width), ("Row Height", row)):
            sock(n.inputs, key).default_value = v
        return self.math("SUBTRACT", 1.0, sock(n.outputs, "Fac"))

    def principled(self, **kw):
        p = self.node("ShaderNodeBsdfPrincipled")
        for k, v in kw.items():
            self.set_in(p, k, v)
        return p

    def finish(self, shader_out):
        self.link(shader_out, self.out.inputs["Surface"])
        return self.mat


def _sep(b, v, idx, kind):
    n = b.node("ShaderNodeSeparateXYZ" if kind == "xyz" else "ShaderNodeSeparateColor")
    b.link(v, n.inputs[0])
    return n.outputs[idx]


# scale sizes (m); the dragon is ~3 m long, so these are large-reptile sizes
SCALE = {"granular": 0.008, "dorsal_s": 0.022, "dorsal_t": 0.018, "tail_t": 0.018, "tail_s": 0.020,
         "belly_row": 0.034, "head": 0.011, "toe_row": 0.009, "lip_y": 0.012, "lip_z": 0.011}


def body_skin():
    """Fused body: one material, patterns and colours switched by the region weights."""
    b = NB(PFX + "body_skin")
    st = b.node("ShaderNodeSeparateXYZ")
    b.link(b.attr("body_st").outputs["Vector"], st.inputs[0])
    s, t = st.outputs[0], st.outputs[1]
    obj = b.node("ShaderNodeTexCoord").outputs["Object"]
    osep = b.node("ShaderNodeSeparateXYZ")
    b.link(obj, osep.inputs[0])
    w = {k: b.attr(k).outputs["Fac"] for k in ("w_up", "w_dorsal", "w_belly", "w_head", "w_tail", "w_foot", "w_lip", "w_mouth")}

    if GEO_SCALES:
        # geometric scales (scale_field): the sculpt carries Levels 1-2; read its height and cell id so colour and
        # roughness follow the real scales, and add only Level 3 micro relief as bump
        h = b.attr("scale_h").outputs["Fac"]
        cell_rand = b.attr("scale_tint").outputs["Fac"]
        micro = b.smooth(sock(b.voronoi(obj, 1 / 0.0026, dims="3D").outputs, "Distance"), 0.0, 0.35)
        fine = b.node("ShaderNodeTexNoise")
        b.link(obj, sock(fine.inputs, "Vector"))
        sock(fine.inputs, "Scale").default_value = 900.0
        bump = b.node("ShaderNodeBump")
        sock(bump.inputs, "Strength").default_value = 1.0
        sock(bump.inputs, "Distance").default_value = 0.00035
        b.link(b.math("ADD", b.math("MULTIPLY", micro, 0.7), b.math("MULTIPLY", sock(fine.outputs, "Fac"), 0.3)), sock(bump.inputs, "Height"))
    else:
        # --- scale height fields (0 = groove between scales, 1 = scale top)
        # granular and head scales are isotropic: 3D Voronoi in object space has no seams anywhere
        gran = b.voronoi(obj, 1 / SCALE["granular"], dims="3D")
        h_gran = b.smooth(sock(gran.outputs, "Distance"), 0.0, 0.30)
        gran_cell = b.voronoi(obj, 1 / SCALE["granular"], feature="F1", dims="3D")
        h_head = b.smooth(sock(b.voronoi(obj, 1 / SCALE["head"], randomness=0.75, dims="3D").outputs, "Distance"), 0.0, 0.22)
        # oriented scales follow the body chains (body_st); their weights fade out at chain junctions
        dvec = b.vec(b.math("DIVIDE", s, SCALE["dorsal_s"]), b.math("DIVIDE", t, SCALE["dorsal_t"]))
        d_edge = b.smooth(sock(b.voronoi(dvec, 1.0).outputs, "Distance"), 0.0, 0.24)
        d_cell = b.voronoi(dvec, 1.0, feature="F1")
        across = b.math("SUBTRACT", b.math("DIVIDE", t, SCALE["dorsal_t"]), b._sep_y(sock(d_cell.outputs, "Position")))
        keel = b.math("SUBTRACT", 1.0, b.math("MULTIPLY", b.math("ABSOLUTE", across), 3.5), clamp=True)
        h_dors = b.math("MULTIPLY", d_edge, b.mixf(keel, 0.62, 1.0))
        h_tail = b.brick(b.vec(t, s), SCALE["tail_t"], SCALE["tail_s"], 0.0018)          # whorls of rectangular scales
        h_belly = b.brick(b.vec(b.math("ADD", t, 0.3), s), 0.6, SCALE["belly_row"], 0.0024, smooth=0.6, offset=0.0)
        h_toe = b.brick(b.vec(b.math("ADD", t, 0.015), s), 0.03, SCALE["toe_row"], 0.0012, offset=0.0)
        h_lip = b.brick(b.vec(osep.outputs[1], osep.outputs[2]), SCALE["lip_y"], SCALE["lip_z"], 0.0012, offset=0.0)
        h = h_gran
        for weight, pattern in ((w["w_dorsal"], h_dors), (w["w_tail"], h_tail), (w["w_belly"], h_belly),
                                (w["w_head"], h_head), (w["w_foot"], h_toe), (w["w_lip"], h_lip), (w["w_mouth"], 0.55)):
            h = b.mixf(weight, h, pattern)
        amp = b.math("ADD", 1.0, b.math("ADD", b.math("MULTIPLY", w["w_dorsal"], 0.8),
                                        b.math("ADD", b.math("MULTIPLY", w["w_belly"], 0.6), b.math("MULTIPLY", w["w_tail"], 0.4))))
        amp = b.math("MULTIPLY", amp, b.math("SUBTRACT", 1.0, w["w_mouth"]))
        bump = b.node("ShaderNodeBump")
        sock(bump.inputs, "Strength").default_value = 1.0
        sock(bump.inputs, "Distance").default_value = 0.0012
        b.link(b.math("MULTIPLY", h, amp), sock(bump.inputs, "Height"))
        cell_rand = b._sep_r(sock(gran_cell.outputs, "Color"))

    # --- albedo: palette skin, countershading, belly, lips, gums, per-scale tint, groove darkening
    skin = b.node("ShaderNodeRGB")
    skin.outputs[0].default_value = lin(PAL["skin"]["hex"])
    counter = b.mixf(w["w_up"], 1.15, 0.78)  # lighter low on the flanks, darker along the back
    blotch = b.node("ShaderNodeTexNoise")
    b.link(obj, sock(blotch.inputs, "Vector"))
    sock(blotch.inputs, "Scale").default_value = 4.0
    tint = b.math("MULTIPLY", b.mixf(sock(blotch.outputs, "Fac"), 0.88, 1.12),
                  b.mixf(cell_rand, 0.92, 1.08))
    col = b.mulc(skin.outputs[0], b.math("MULTIPLY", counter, tint))
    belly = b.node("ShaderNodeRGB")
    belly.outputs[0].default_value = lin(PAL["belly"]["hex"])
    col = b.mixc(w["w_belly"], col, b.mulc(belly.outputs[0], tint))
    col = b.mixc(b.math("MULTIPLY", w["w_lip"], 0.6), col, b.mulc(skin.outputs[0], 1.3))
    if STRIPES:
        # transverse bands along s, wobbled by noise, on the back and upper flanks only
        wav = b.node("ShaderNodeTexWave", wave_type="BANDS", bands_direction="X")
        b.link(b.vec(s, t), sock(wav.inputs, "Vector"))
        # Wave BANDS computes sin(20 * scale * x): period = 2*pi / (20 * scale)
        for key, val in (("Scale", 2 * math.pi / (20.0 * STRIPES["period"])), ("Distortion", 6.0), ("Detail", 2.0), ("Detail Scale", 0.6)):
            sock(wav.inputs, key).default_value = val
        lo = 1.0 - STRIPES.get("width", 0.35)
        band = b.smooth(sock(wav.outputs, "Fac"), lo, lo + 0.12)
        band = b.math("MULTIPLY", band, b.math("MULTIPLY", b.smooth(w["w_up"], 0.40, 0.62), b.math("SUBTRACT", 1.0, w["w_head"])))
        col = b.mulc(col, b.mixf(band, 1.0, STRIPES["darkness"]))
    gum = b.node("ShaderNodeRGB")
    gum.outputs[0].default_value = lin(PAL["gum"]["hex"])
    col = b.mixc(w["w_mouth"], col, gum.outputs[0])
    col = b.mulc(col, b.mixf(w["w_mouth"], b.mixf(h, 0.74, 1.0), 1.0))
    rough = b.mixf(w["w_mouth"], b.mixf(h, 0.70, 0.48), 0.22)
    p = b.principled(**{"Base Color": col, "Roughness": rough, "Normal": sock(bump.outputs, "Normal"),
                        "Coat Weight": b.math("MULTIPLY", w["w_mouth"], 0.5)}, **sss_inputs("body"))
    return b.finish(p.outputs[0])


NB._sep_y = lambda self, v: _sep(self, v, 1, "xyz")
NB._sep_r = lambda self, v: _sep(self, v, 0, "rgb")


def simple_skin():
    """Skin for separate inserts (wing fingers, eyelids): palette skin + small granular scales."""
    b = NB(PFX + "simple_skin")
    tc = b.node("ShaderNodeTexCoord")
    vor = b.voronoi(tc.outputs["Object"], 1 / 0.005, dims="3D")
    h = b.smooth(sock(vor.outputs, "Distance"), 0.0, 0.16)
    bump = b.node("ShaderNodeBump")
    sock(bump.inputs, "Distance").default_value = 0.0008
    b.link(h, sock(bump.inputs, "Height"))
    skin = b.node("ShaderNodeRGB")
    skin.outputs[0].default_value = lin(PAL["skin"]["hex"])
    col = b.mulc(skin.outputs[0], b.mixf(h, 0.7, 1.0))
    return b.finish(b.principled(**{"Base Color": col, "Roughness": b.mixf(h, 0.66, 0.5),
                                    "Normal": sock(bump.outputs, "Normal")}).outputs[0])


def membrane():
    """Wing membrane: palette colour, branching veins, fine wrinkles along the fingers, translucency."""
    b = NB(PFX + "membrane")
    uv = b.node("ShaderNodeUVMap")
    sep = b.node("ShaderNodeSeparateXYZ")
    b.link(uv.outputs["UV"], sep.inputs[0])
    u, v = sep.outputs[0], sep.outputs[1]
    main = b.node("ShaderNodeTexWave", wave_type="BANDS", bands_direction="Y")
    b.link(uv.outputs["UV"], sock(main.inputs, "Vector"))
    for key, val in (("Scale", 6.0), ("Distortion", 5.0), ("Detail", 3.0), ("Detail Scale", 1.0)):
        sock(main.inputs, key).default_value = val
    main_v = b.smooth(sock(main.outputs, "Fac"), 0.935, 0.995)
    vor = b.voronoi(b.vec(b.math("MULTIPLY", u, 10.0), b.math("MULTIPLY", v, 26.0)), 1.0, randomness=0.9)
    cap = b.math("SUBTRACT", 1.0, b.smooth(sock(vor.outputs, "Distance"), 0.0, 0.03))
    veins = b.math("MAXIMUM", main_v, b.math("MULTIPLY", cap, 0.35))
    wav = b.node("ShaderNodeTexWave", wave_type="BANDS", bands_direction="Y")
    b.link(uv.outputs["UV"], sock(wav.inputs, "Vector"))
    sock(wav.inputs, "Scale").default_value = 160.0
    sock(wav.inputs, "Distortion").default_value = 4.0
    height = b.math("ADD", b.math("MULTIPLY", veins, 0.7), b.math("MULTIPLY", sock(wav.outputs, "Fac"), 0.15))
    bump = b.node("ShaderNodeBump")
    sock(bump.inputs, "Distance").default_value = 0.0006
    b.link(height, sock(bump.inputs, "Height"))
    base = b.node("ShaderNodeRGB")
    base.outputs[0].default_value = lin(PAL["membrane"]["hex"])
    vein_col = b.node("ShaderNodeRGB")
    vein_col.outputs[0].default_value = lin("#26331F")
    col = b.mixc(b.math("MULTIPLY", veins, 0.6), base.outputs[0], vein_col.outputs[0])
    p = b.principled(**{"Base Color": col, "Roughness": 0.55, "Normal": sock(bump.outputs, "Normal")})
    tr = b.node("ShaderNodeBsdfTranslucent")
    glow = b.node("ShaderNodeRGB")
    glow.outputs[0].default_value = lin("#5E7A3A")
    b.link(b.mixc(veins, glow.outputs[0], vein_col.outputs[0]), tr.inputs["Color"])
    mix = b.node("ShaderNodeMixShader")
    mix.inputs[0].default_value = 0.3
    b.link(p.outputs[0], mix.inputs[1])
    b.link(tr.outputs[0], mix.inputs[2])
    return b.finish(mix.outputs[0])


def keratin(name, base_hex, tip_hex, rough, rings=0.0, coat=0.2, sss=0.0, fibres=0.0):
    """Horns, spikes, claws, teeth: base-to-tip colour along tip_t, optional growth rings and fibre striations."""
    b = NB(PFX + name)
    t = b.attr("tip_t").outputs["Fac"]
    c0, c1 = b.node("ShaderNodeRGB"), b.node("ShaderNodeRGB")
    c0.outputs[0].default_value = lin(base_hex)
    c1.outputs[0].default_value = lin(tip_hex)
    col = b.mixc(b.smooth(t, 0.0, 1.0), c0.outputs[0], c1.outputs[0])
    kw = {"Roughness": rough, "Coat Weight": coat}
    height = None
    if rings:
        ring = b.math("MULTIPLY", b.math("SINE", b.math("MULTIPLY", t, rings * 6.2832)), b.math("SUBTRACT", 1.0, b.math("MULTIPLY", t, 0.8)))
        height = ring
        col = b.mulc(col, b.mixf(b.math("MULTIPLY", b.math("ADD", ring, 1.0), 0.5), 0.8, 1.0))
    if fibres:
        uv = b.node("ShaderNodeUVMap")
        fw = b.node("ShaderNodeTexWave", wave_type="BANDS", bands_direction="X")
        b.link(uv.outputs["UV"], sock(fw.inputs, "Vector"))
        for key, val in (("Scale", fibres), ("Distortion", 6.0), ("Detail", 4.0)):
            sock(fw.inputs, key).default_value = val
        f = sock(fw.outputs, "Fac")
        height = f if height is None else b.math("ADD", height, b.math("MULTIPLY", f, 0.6))
        col = b.mulc(col, b.mixf(f, 0.82, 1.06))
    if height is not None:
        bump = b.node("ShaderNodeBump")
        sock(bump.inputs, "Distance").default_value = 0.0012
        b.link(height, sock(bump.inputs, "Height"))
        kw["Normal"] = sock(bump.outputs, "Normal")
    if sss:
        kw["Subsurface Weight"] = sss
        kw["Subsurface Radius"] = (0.6, 0.45, 0.3)
        kw["Subsurface Scale"] = 0.004
    kw["Base Color"] = col
    return b.finish(b.principled(**kw).outputs[0])


def tongue():
    b = NB(PFX + "tongue")
    tc = b.node("ShaderNodeTexCoord")
    vor = b.voronoi(tc.outputs["Object"], 1 / 0.0018, dims="3D")
    bump = b.node("ShaderNodeBump")
    sock(bump.inputs, "Distance").default_value = 0.0004
    b.link(b.smooth(sock(vor.outputs, "Distance"), 0.0, 0.3), sock(bump.inputs, "Height"))
    c = b.node("ShaderNodeRGB")
    c.outputs[0].default_value = lin(PAL["tongue"]["hex"])
    return b.finish(b.principled(**{"Base Color": c.outputs[0], "Roughness": 0.3, "Coat Weight": 0.5,
                                    "Subsurface Weight": 0.15, "Subsurface Scale": 0.003,
                                    "Normal": sock(bump.outputs, "Normal")}).outputs[0])


def eye_iris():
    """Eyeball: amber iris with radial streaks and dark limbal ring, vertical slit pupil, dark sclera.
    Reads attribute eye_local = position in the eye's frame (x side, y up, z gaze), unit radius."""
    b = NB(PFX + "eye_iris")
    sep = b.node("ShaderNodeSeparateXYZ")
    b.link(b.attr("eye_local").outputs["Vector"], sep.inputs[0])
    x, y, z = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    r = b.math("SQRT", b.math("ADD", b.math("MULTIPLY", x, x), b.math("MULTIPLY", y, y)))
    ang = b.math("ARCTAN2", y, x)
    streak = b.node("ShaderNodeTexNoise")
    sock(streak.inputs, "Scale").default_value = 9.0
    b.link(b.vec(b.math("MULTIPLY", ang, 3.0), b.math("MULTIPLY", r, 2.0)), sock(streak.inputs, "Vector"))
    inner, outer = b.node("ShaderNodeRGB"), b.node("ShaderNodeRGB")
    inner.outputs[0].default_value = lin("#F2B33A")
    outer.outputs[0].default_value = lin(PAL["eye"]["hex"])
    iris = b.mixc(b.smooth(r, 0.1, 0.72), inner.outputs[0], outer.outputs[0])
    iris = b.mulc(iris, b.mixf(sock(streak.outputs, "Fac"), 0.7, 1.15))
    limbal = b.smooth(r, 0.66, 0.80)  # dark ring at the iris edge
    iris = b.mulc(iris, b.mixf(limbal, 1.0, 0.25))
    pupil = b.math("ADD", b.math("MULTIPLY", b.math("DIVIDE", x, 0.07), b.math("DIVIDE", x, 0.07)),
                   b.math("MULTIPLY", b.math("DIVIDE", y, 0.55), b.math("DIVIDE", y, 0.55)))
    pupil_mask = b.math("MULTIPLY", b.math("LESS_THAN", pupil, 1.0), b.math("GREATER_THAN", z, 0.0))
    black = b.node("ShaderNodeRGB")
    black.outputs[0].default_value = lin("#060606")
    col = b.mixc(pupil_mask, iris, black.outputs[0])
    sclera = b.node("ShaderNodeRGB")
    sclera.outputs[0].default_value = lin("#3B2E1E")
    col = b.mixc(b.smooth(z, 0.50, 0.58), sclera.outputs[0], col)
    return b.finish(b.principled(**{"Base Color": col, "Roughness": 0.35}).outputs[0])


def cornea():
    """Wet cornea cap: Fresnel-weighted gloss over a transparent surface. Transparent (not refractive glass)
    so shadow rays reach the iris; a refractive cap would render the eye dark under area lights."""
    b = NB(PFX + "cornea")
    fres = b.node("ShaderNodeFresnel")
    fres.inputs["IOR"].default_value = 1.376
    gloss = b.node("ShaderNodeBsdfGlossy")
    gloss.inputs["Roughness"].default_value = 0.02
    clear = b.node("ShaderNodeBsdfTransparent")
    mix = b.node("ShaderNodeMixShader")
    b.link(b.smooth(fres.outputs[0], 0.0, 1.0, 0.25, 1.0), mix.inputs[0])
    b.link(clear.outputs[0], mix.inputs[1])
    b.link(gloss.outputs[0], mix.inputs[2])
    return b.finish(mix.outputs[0])


def build_all(palette=None, stripes=None, prefix=None, geo_scales=False, profiles=None):
    """palette: dict key -> {"hex": ...} overriding the shared palette (keys skin, belly, horn, claw, eye,
    membrane, tooth, gum, tongue; optional horn_base/horn_tip/claw_base/claw_tip). stripes: see STRIPES.
    profiles: material_profile values from the surface plan; "key:variant" entries apply VARIANTS (v1.3).
    The palette starts from mp.PALETTE on every call, so one creature's colours never leak into the next."""
    global STRIPES, PFX, GEO_SCALES
    GEO_SCALES = geo_scales
    PAL.clear()
    PAL.update(mp.PALETTE)
    if palette:
        PAL.update(palette)
    STRIPES = stripes
    if prefix:
        PFX = prefix
    PROFILE.clear()
    for name in profiles or []:
        if ":" not in name:
            continue
        if name not in VARIANTS:
            raise ValueError(f"unknown material profile {name!r}; known variants: {sorted(VARIANTS)}")
        PROFILE[name.split(":", 1)[0]] = VARIANTS[name]
    hx = lambda k, d: PAL[k]["hex"] if k in PAL else d  # noqa: E731

    def ker(key, base, tip, rough, **kw):
        v = PROFILE.get(key, {})
        kw.update({k: v[k] for k in ("coat", "sss") if k in v})
        return keratin(key, base, tip, v.get("rough", rough), **kw)
    return {
        "body": body_skin(), "skin": simple_skin(), "membrane": membrane(),
        "horn": ker("horn", hx("horn_base", "#6B4E2B"), hx("horn_tip", "#B39064"), 0.46, rings=22.0, coat=0.08, fibres=260.0),
        "spike": ker("spike", hx("spike_base", "#5A4426"), hx("spike_tip", "#A88A5E"), 0.46, coat=0.08, fibres=260.0),
        "claw": ker("claw", hx("claw_base", "#4A4440"), hx("claw_tip", "#121212"), 0.28, coat=0.35),
        "tooth": ker("tooth", "#C9B88A", PAL["tooth"]["hex"], 0.22, coat=0.4, sss=0.2),
        "tongue": tongue(), "eye": eye_iris(), "cornea": cornea(),
    }
