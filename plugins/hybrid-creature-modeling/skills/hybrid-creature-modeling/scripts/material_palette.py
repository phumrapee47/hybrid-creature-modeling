"""Shared material palette for every dragon experiment.

Materials are deliberately simple: Principled BSDF + a low-amplitude value
variation from object-space noise. No bump or normal maps, so the material
render cannot hide geometry problems. Every experiment must use these keys.
"""
import bpy

MATERIAL_PREFIX = "DRG_"

# hex = sRGB colour; variation = +/- fraction of value modulation by noise
PALETTE = {
    "skin":     {"hex": "#2E4D2C", "roughness": 0.55, "variation": 0.10, "var_scale": 6.0},
    "belly":    {"hex": "#7F8A52", "roughness": 0.62, "variation": 0.06, "var_scale": 9.0},
    "horn":     {"hex": "#8C6A3C", "roughness": 0.42, "variation": 0.06, "var_scale": 14.0},
    "claw":     {"hex": "#2A2A2C", "roughness": 0.35, "variation": 0.0},
    "eye":      {"hex": "#E39A1F", "roughness": 0.12, "variation": 0.0, "coat": 0.6},
    "pupil":    {"hex": "#101010", "roughness": 0.20, "variation": 0.0},
    "membrane": {"hex": "#2C4632", "roughness": 0.60, "variation": 0.14, "var_scale": 3.5},
    # added for the Experiment 6 detail pass (mouth interior); not used by Experiments 1-5
    "tooth":    {"hex": "#E6DCC3", "roughness": 0.25, "variation": 0.0},
    "gum":      {"hex": "#6E3237", "roughness": 0.25, "variation": 0.0},
    "tongue":   {"hex": "#8C3F4A", "roughness": 0.30, "variation": 0.0},
}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(hex_str):
    h = hex_str.lstrip("#")
    return tuple(srgb_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


def get_material(key):
    """Return the shared material for `key`, creating it on first use."""
    name = MATERIAL_PREFIX + key
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    rgb = hex_to_linear(PALETTE[key]["hex"])
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*rgb, 1.0)  # viewport / workbench colour
    nt = mat.node_tree
    _setup_bsdf(nt, next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), key)
    return mat


def get_blend_material(key_a, key_b, attribute):
    """Two palette entries mixed by a per-vertex float attribute (0 = key_a, 1 = key_b).

    For meshes whose topology cannot carry clean per-face material boundaries
    (voxel-remeshed sculpts). Colours, roughness and variation are the palette's.
    """
    name = f"{MATERIAL_PREFIX}{key_a}_{key_b}_blend"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*hex_to_linear(PALETTE[key_a]["hex"]), 1.0)
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    bsdf_a = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    _setup_bsdf(nt, bsdf_a, key_a)
    bsdf_b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    _setup_bsdf(nt, bsdf_b, key_b)
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = attribute
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(attr.outputs["Fac"], mix.inputs["Fac"])
    nt.links.new(bsdf_a.outputs["BSDF"], mix.inputs[1])
    nt.links.new(bsdf_b.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def _setup_bsdf(nt, bsdf, key):
    spec = PALETTE[key]
    rgb = hex_to_linear(spec["hex"])
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = spec["roughness"]
    if spec.get("coat"):
        bsdf.inputs["Coat Weight"].default_value = spec["coat"]

    var = spec.get("variation", 0.0)
    if var > 0:
        coord = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = spec.get("var_scale", 6.0)
        noise.inputs["Detail"].default_value = 3.0
        rng = nt.nodes.new("ShaderNodeMapRange")
        rng.inputs["From Min"].default_value = 0.3
        rng.inputs["From Max"].default_value = 0.7
        rng.inputs["To Min"].default_value = 1.0 - var
        rng.inputs["To Max"].default_value = 1.0 + var
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Color"].default_value = (*rgb, 1.0)
        nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
        nt.links.new(noise.outputs["Fac"], rng.inputs["Value"])
        nt.links.new(rng.outputs["Result"], hsv.inputs["Value"])
        nt.links.new(hsv.outputs["Color"], bsdf.inputs["Base Color"])


def make_flat_material(name, rgb_srgb, roughness=0.5):
    """Plain neutral material used by the benchmark rig (clay, floor, wire)."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    rgb = tuple(srgb_to_linear(c) for c in rgb_srgb)
    mat.use_nodes = True
    mat.diffuse_color = (*rgb, 1.0)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat
