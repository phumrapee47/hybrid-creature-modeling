"""Anatomy-aware surface planning (v1.3): WHAT surface belongs WHERE, decided before any geometry is generated.

A plan is a list of regions. Each region names a body area (bound to a body-field weight written by
creature_kit.body_fields, or to an insert object) and describes its intended surface:

  region_id                 unique name ("dorsal", "flank", "horns", ...)
  anatomical_role           what the area does ("dorsal armour over the spine", "grasping claw", ...)
  primary_form              the form underneath ("trunk loft", "limb chain", "insert sweep", ...)
  surface_type              one of SURFACE_TYPES
  detail_scale              typical feature size in metres (scale or plate length, hair length), or None
  coverage_density          0..1: how much of the region carries the surface (0 switches it off)
  surface_orientation       one of ORIENTATIONS
  material_profile          key of the material that renders it (detail_materials.build_all keys)
  geometry_strategy         one of STRATEGIES, "scale_field:<layer>" or "insert:<name>"
  deformation_requirements  one of DEFORMATIONS (used to reduce detail near flexible joints)

Optional: weight (body-field attribute the region is bound to), scale (overrides for its scale_field layer),
enabled (False skips the region), notes.

Every field except region_id is optional; missing fields come from the default region of the same id or from
FIELD_DEFAULTS. A creature without `surface_plan` gets DEFAULT_PLAN, which describes exactly what v1.2 already
generates, so existing creatures build unchanged. Surface types without a generator yet (fur, mane, whiskers,
feathers) are accepted and reported as planned, never silently faked.
"""
import copy

SURFACE_TYPES = ("exposed_skin", "reptilian_scales", "armor_plates", "spines", "horn", "claw", "teeth", "eye", "tongue",
                 "membrane", "fur", "mane", "whiskers", "feathers", "custom")
ORIENTATIONS = ("isotropic", "along_chain", "around_chain", "rows_along_body", "transverse_rows", "radial",
                "growth_direction", "not_applicable")
DEFORMATIONS = ("rigid", "flexible", "stretch", "fold")
STRATEGIES = ("shader_only", "sculpt", "none", "fur_groom")          # plus "scale_field:<layer>", "insert:<name>"
SCALE_LAYERS = ("granular", "flank_rows", "limb", "limb_plates", "dorsal", "paravertebral", "ventral", "tail", "head",
                "head_plates", "toe", "labial")
# surface types whose generator does not exist yet: the plan records them, the build reports them as planned
PLANNED_ONLY = ("fur", "mane", "whiskers", "feathers")
FIELDS = ("region_id", "anatomical_role", "primary_form", "surface_type", "detail_scale", "coverage_density",
          "surface_orientation", "material_profile", "geometry_strategy", "deformation_requirements")
OPTIONAL = ("weight", "scale", "enabled", "notes", "fur")
# v1.3 fur interface (no generator yet): a fur/mane/whiskers/feathers region may carry a `fur` dict. The build
# validates it and logs it under fur_planned; nothing is generated. Each field names the Blender 5.2 bundled hair
# node group (datafiles/assets/nodes/procedural_hair_node_assets.blend) a future generator should drive, checked by
# the hair API smoke test. Random cones or spikes are not an acceptable stand-in for fur.
FUR_FIELDS = {   # name: (default, minimum, maximum, Blender node group)
    "length": (0.03, 1e-4, 2.0, "Generate Hair Curves"),            # metres
    "density": (20.0, 0.01, 2000.0, "Interpolate Hair Curves"),     # strands per cm2 (children around guides)
    "guide_spacing": (0.02, 1e-3, 0.5, "Generate Hair Curves"),     # metres between groomed guide curves
    "clump": (0.3, 0.0, 1.0, "Clump Hair Curves"),
    "curl": (0.0, 0.0, 1.0, "Curl Hair Curves"),
    "frizz": (0.1, 0.0, 1.0, "Frizz Hair Curves"),
    "root_width": (0.0004, 1e-5, 0.01, "Set Hair Curve Profile"),   # metres
}
FUR_COLOURS = ("root_hex", "tip_hex")
FIELD_DEFAULTS = {"anatomical_role": "", "primary_form": "", "surface_type": "custom", "detail_scale": None,
                  "coverage_density": 1.0, "surface_orientation": "not_applicable", "material_profile": "body",
                  "geometry_strategy": "none", "deformation_requirements": "rigid", "weight": None, "scale": None,
                  "enabled": True, "notes": ""}


def _r(region_id, role, form, stype, size, orient, material, strategy, deform, weight=None, **kw):
    d = dict(region_id=region_id, anatomical_role=role, primary_form=form, surface_type=stype, detail_scale=size,
             coverage_density=1.0, surface_orientation=orient, material_profile=material, geometry_strategy=strategy,
             deformation_requirements=deform, weight=weight)
    d.update(kw)
    return d


# The v1.2 surfaces, written down. Sizes are scale_field.DEFAULTS (a ~3 m creature); the layer parameters stay in
# scale_field, so this plan changes nothing by itself. Layer order and blending are scale_field's.
DEFAULT_PLAN = [
    _r("skin_base", "everywhere not claimed by a later region", "fused body", "reptilian_scales", 0.010, "isotropic",
       "body", "scale_field:granular", "stretch"),
    _r("flank", "trunk, neck and tail sides between back and belly", "trunk loft", "reptilian_scales", 0.015,
       "rows_along_body", "body", "scale_field:flank_rows", "stretch", "w_spine", enabled=False,
       notes="off unless the creature enables scales.flank_rows"),
    _r("limbs", "limb skin all round", "limb chains", "reptilian_scales", 0.016, "along_chain", "body",
       "scale_field:limb", "flexible", "w_limbdir"),
    _r("limb_outer", "outer shoulders, forearms, thighs", "limb chains", "armor_plates", 0.028, "along_chain", "body",
       "scale_field:limb_plates", "flexible", "w_limb"),
    _r("dorsal", "back, neck top, tail base", "trunk loft", "reptilian_scales", 0.024, "along_chain", "body",
       "scale_field:dorsal", "stretch", "w_dorsal"),
    _r("paravertebral", "osteoderm rows either side of the spine", "trunk loft", "armor_plates", 0.044,
       "transverse_rows", "body", "scale_field:paravertebral", "rigid", "w_dorsal"),
    _r("belly", "ventral plates on throat, chest and belly", "trunk loft", "armor_plates", 0.034, "transverse_rows",
       "body", "scale_field:ventral", "fold", "w_belly"),
    _r("tail", "tail whorls", "trunk loft (tail)", "reptilian_scales", 0.020, "around_chain", "body",
       "scale_field:tail", "flexible", "w_tail"),
    _r("head", "head skin", "head and jaw lofts", "reptilian_scales", 0.013, "isotropic", "body",
       "scale_field:head", "rigid", "w_head"),
    _r("head_top", "cranial plates on top of the skull", "head loft", "armor_plates", 0.028, "isotropic", "body",
       "scale_field:head_plates", "rigid", "w_head"),
    _r("toes", "toe scutes", "paw toes", "reptilian_scales", 0.010, "transverse_rows", "body", "scale_field:toe",
       "flexible", "w_foot"),
    _r("lips", "labial scales along the mouth margin", "head and jaw lofts", "reptilian_scales", 0.012,
       "rows_along_body", "body", "scale_field:labial", "fold", "w_lip"),
    _r("mouth", "gums and mouth lining", "mouth profile", "exposed_skin", None, "not_applicable", "body", "none",
       "stretch", "w_mouth"),
    # inserts: separate objects with their own materials
    _r("eyes", "eyeballs, cornea and lids", "eye insert", "eye", None, "not_applicable", "eye", "insert:eyes", "rigid"),
    _r("teeth", "tooth rows", "mouth profile", "teeth", None, "not_applicable", "tooth", "insert:teeth", "rigid"),
    _r("tongue", "tongue", "mouth profile", "tongue", None, "not_applicable", "tongue", "insert:tongue", "flexible"),
    _r("horns", "horns, crown and cheek spikes", "insert sweeps", "horn", None, "not_applicable", "horn",
       "insert:horns", "rigid"),
    _r("spines", "dorsal spikes or scutes", "insert sweeps", "spines", None, "not_applicable", "spike",
       "insert:spikes", "rigid"),
    _r("claws", "claws", "insert sweeps", "claw", None, "not_applicable", "claw", "insert:claws", "rigid"),
    _r("wing_membrane", "wing membranes", "membrane patches", "membrane", None, "not_applicable", "membrane",
       "insert:membranes", "stretch"),
]


def _check_strategy(s):
    if s in STRATEGIES:
        return None
    if s.startswith("scale_field:"):
        return None if s.split(":", 1)[1] in SCALE_LAYERS else f"unknown scale_field layer in {s!r}"
    if s.startswith("insert:") and len(s) > 7:
        return None
    return f"unknown geometry_strategy {s!r}"


def validate(plan):
    """Return (errors, warnings). Errors make the plan unusable; warnings are logged."""
    errors, warnings, seen = [], [], set()
    for i, r in enumerate(plan):
        rid = r.get("region_id")
        if not rid:
            errors.append(f"region {i}: region_id is required")
            continue
        if rid in seen:
            errors.append(f"{rid}: duplicate region_id")
        seen.add(rid)
        for k in r:
            if k not in FIELDS and k not in OPTIONAL:
                warnings.append(f"{rid}: unknown field {k!r} ignored")
        if r.get("surface_type") not in SURFACE_TYPES:
            errors.append(f"{rid}: surface_type {r.get('surface_type')!r} not in {SURFACE_TYPES}")
        if r.get("surface_orientation") not in ORIENTATIONS:
            errors.append(f"{rid}: surface_orientation {r.get('surface_orientation')!r} not in {ORIENTATIONS}")
        if r.get("deformation_requirements") not in DEFORMATIONS:
            errors.append(f"{rid}: deformation_requirements {r.get('deformation_requirements')!r} not in {DEFORMATIONS}")
        msg = _check_strategy(r.get("geometry_strategy", ""))
        if msg:
            errors.append(f"{rid}: {msg}")
        cov = r.get("coverage_density")
        if not isinstance(cov, (int, float)) or not 0.0 <= cov <= 1.0:
            errors.append(f"{rid}: coverage_density must be a number in 0..1")
        ds = r.get("detail_scale")
        if ds is not None and (not isinstance(ds, (int, float)) or ds <= 0):
            errors.append(f"{rid}: detail_scale must be positive metres or None")
        if r.get("scale") is not None and not str(r.get("geometry_strategy", "")).startswith("scale_field:"):
            warnings.append(f"{rid}: scale overrides given but the strategy is not scale_field")
        if r.get("surface_type") in PLANNED_ONLY and r.get("enabled", True):
            warnings.append(f"{rid}: {r['surface_type']} is planned only; no generator in this version (nothing is built)")
        fur = r.get("fur")
        if fur is not None:
            if not isinstance(fur, dict):
                errors.append(f"{rid}: fur must be a dict of {sorted(FUR_FIELDS)} and {FUR_COLOURS}")
                continue
            if r.get("surface_type") not in PLANNED_ONLY:
                warnings.append(f"{rid}: fur parameters on a {r.get('surface_type')} region are ignored")
            for k, v in fur.items():
                if k in FUR_COLOURS:
                    if not (isinstance(v, str) and v.startswith("#") and len(v) == 7):
                        errors.append(f"{rid}: fur.{k} must be a '#RRGGBB' colour")
                elif k not in FUR_FIELDS:
                    warnings.append(f"{rid}: unknown fur field {k!r} ignored")
                elif not isinstance(v, (int, float)) or not FUR_FIELDS[k][1] <= v <= FUR_FIELDS[k][2]:
                    errors.append(f"{rid}: fur.{k} must be a number in {FUR_FIELDS[k][1]}..{FUR_FIELDS[k][2]}")
    return errors, warnings


def fur_requests(plan):
    """Enabled fur-type regions with their fur parameters (defaults filled in), for the build log and a future
    generator. v1.3 builds none of them."""
    out = []
    for r in plan:
        if r.get("surface_type") in PLANNED_ONLY and r.get("enabled", True) and r.get("coverage_density", 1.0) > 0:
            fur = {k: v[0] for k, v in FUR_FIELDS.items()}
            fur.update(r.get("fur") or {})
            out.append({"region_id": r["region_id"], "surface_type": r["surface_type"], "weight": r.get("weight"),
                        "orientation": r.get("surface_orientation"), "fur": fur, "status": "planned: no fur generator in v1.3"})
    return out


def resolve(overrides=None):
    """Default plan merged with a creature's overrides (a list of region dicts, matched by region_id; new ids are
    appended). Missing fields come from the default region or FIELD_DEFAULTS. Raises ValueError on an invalid plan."""
    plan = {r["region_id"]: dict(FIELD_DEFAULTS, **copy.deepcopy(r)) for r in DEFAULT_PLAN}
    order = [r["region_id"] for r in DEFAULT_PLAN]
    for o in overrides or []:
        rid = o.get("region_id")
        if rid in plan:
            plan[rid].update(copy.deepcopy(o))
        else:
            plan[rid] = dict(FIELD_DEFAULTS, **copy.deepcopy(o))
            order.append(rid)
    out = [plan[k] for k in order]
    errors, warnings = validate(out)
    if errors:
        raise ValueError("surface plan invalid:\n  " + "\n  ".join(errors))
    return mark_explicit(out, overrides), warnings


def scale_spec(plan, scales, joint_relief=0.0):
    """scale_field spec for a creature: its `scales` dict (v1.2 behaviour) plus per-region overrides from the plan.

    Plan regions contribute only what they explicitly set: `scale` overrides for their layer, coverage_density 0 or
    enabled False (layer height 0; flank_rows enabled flag). The creature's own `scales` dict wins over the plan, so
    a creature without plan overrides gets exactly the v1.2 spec.
    joint_relief > 0 (Creature.joint_relief) lowers scales at limb joints (body field w_joint) by that fraction when
    an enabled limb region is planned as flexible."""
    spec = {}
    if joint_relief and any(r.get("deformation_requirements") == "flexible" and r.get("enabled", True)
                            and r.get("weight") in ("w_limb", "w_limbdir") for r in plan):
        spec["joint_relief"] = float(joint_relief)
    for r in plan:
        strat = r.get("geometry_strategy", "")
        if not strat.startswith("scale_field:"):
            continue
        layer = strat.split(":", 1)[1]
        o = dict(r.get("scale") or {})
        if layer == "flank_rows" and r.get("_explicit_enabled") is not None:
            o["enabled"] = bool(r["_explicit_enabled"])
        if r.get("_explicit_off"):
            o["height"] = 0.0
        if o:
            spec[layer] = o
    for k, v in (scales if isinstance(scales, dict) else {}).items():
        spec[k] = dict(spec.get(k, {}), **v) if isinstance(v, dict) and isinstance(spec.get(k), dict) else v
    return spec or (scales if isinstance(scales, dict) else None)


def mark_explicit(plan, overrides):
    """Flag regions whose creature override switched them on or off, so scale_spec only acts on explicit choices
    (the default plan's own enabled/coverage values describe v1.2 and must not change the spec)."""
    by_id = {o.get("region_id"): o for o in overrides or []}
    for r in plan:
        o = by_id.get(r["region_id"], {})
        if "enabled" in o:
            r["_explicit_enabled"] = o["enabled"]
        if o.get("enabled") is False or o.get("coverage_density") == 0:
            r["_explicit_off"] = True
    return plan


def summary(plan):
    """Compact per-region record for the build log."""
    return [{k: r.get(k) for k in ("region_id", "surface_type", "geometry_strategy", "surface_orientation", "detail_scale",
                                   "material_profile", "deformation_requirements", "weight", "enabled")} for r in plan]


def describe(plan):
    """Markdown table of the plan (for reports)."""
    rows = ["| region | surface | strategy | orientation | size | material | deformation |", "|---|---|---|---|---|---|---|"]
    for r in plan:
        size = f"{r['detail_scale'] * 1000:.0f} mm" if r.get("detail_scale") else "-"
        state = "" if r.get("enabled", True) else " (off)"
        rows.append(f"| {r['region_id']}{state} | {r['surface_type']} | {r['geometry_strategy']} | {r['surface_orientation']} | "
                    f"{size} | {r['material_profile']} | {r['deformation_requirements']} |")
    return "\n".join(rows)
