"""Skill tests (headless, no sculpting): surface plan schema, backward compatibility, scale field, examples.

  blender -b --factory-startup --python tests/run_tests.py
  blender -b --factory-startup --python tests/run_tests.py -- --make-golden <scale_field.py to record>

Exit code 0 when every test passes, 1 otherwise. The golden file pins scale_field's displacement on a synthetic
mesh so a change that alters existing creatures is caught (record it from the version you trust).
"""
import hashlib
import importlib.util
import json
import math
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import bpy  # noqa: E402
import numpy as np  # noqa: E402

import scale_field  # noqa: E402
import surface_plan as sp  # noqa: E402

GOLDEN = os.path.join(HERE, "golden_scale_field.json")
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
RESULTS = []


def test(fn):
    try:
        fn()
        RESULTS.append((fn.__name__, True, ""))
    except Exception as e:  # noqa: BLE001
        RESULTS.append((fn.__name__, False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"))
    return fn


# ------------------------------------------------------------------ synthetic mesh with body-field attributes
def synthetic_mesh():
    """A 0.6 m sphere (about 1.6 mm edges near the front) with deterministic body fields standing in for
    creature_kit.body_fields: s along -Y, t around, girth 1, region weights as smooth bands."""
    me = bpy.data.meshes.new("t_sphere")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=192, v_segments=96, radius=0.3)
    bm.to_mesh(me)
    bm.free()
    me.update()
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    x, y, z = co[:, 0], co[:, 1], co[:, 2]
    ang = np.arctan2(z, x)
    s = y + 0.3
    t = (ang + math.pi) * 0.3
    td = np.abs(np.arctan2(x, z)) * 0.3
    ss = lambda e0, e1, v: np.clip((v - e0) / (e1 - e0), 0, 1) ** 2 * (3 - 2 * np.clip((v - e0) / (e1 - e0), 0, 1))  # noqa: E731
    attrs = {"w_up": 0.5 + 0.5 * z / 0.3, "w_dorsal": ss(0.12, 0.22, z), "w_belly": ss(0.12, 0.22, -z),
             "w_head": ss(0.15, 0.25, -y), "w_tail": ss(0.15, 0.25, y), "w_foot": ss(0.20, 0.28, x),
             "w_lip": ss(0.22, 0.28, -x) * ss(0.0, 0.1, -y), "w_mouth": np.zeros(n), "w_limb": ss(0.18, 0.26, -x) * 0.5,
             "w_limbdir": ss(0.18, 0.26, -x), "w_spine": 1.0 - ss(0.15, 0.25, -y)}
    for name, val in attrs.items():
        a = me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", np.clip(val, 0, 1).astype(np.float32))
    for name, val in (("girth", np.ones(n)), ("body_u", s)):
        a = me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", val.astype(np.float32))
    st = me.attributes.new("body_st", "FLOAT_VECTOR", "POINT")
    st.data.foreach_set("vector", np.stack([s, t, td], 1).astype(np.float32).ravel())
    return me


DRAGONISH = {"seed": 7, "head": {"size": 0.009, "height": 0.0013}, "head_plates": {"size": 0.017, "height": 0.0022}}
CASES = {"defaults": None, "dragon_v12": DRAGONISH}


GOLDEN_NPZ = os.path.join(HERE, "golden_scale_field.npz")
FLOAT32_M = 1e-7     # Blender keeps float32 coordinates: ~3e-8 m resolution at 0.3 m; compare displacements at 0.1 um


def displacement_hash(module, spec, with_array=False):
    me = synthetic_mesh()
    n = len(me.vertices)
    before = np.empty(n * 3)
    me.vertices.foreach_get("co", before)
    module.apply(me, spec)
    after = np.empty(n * 3)
    me.vertices.foreach_get("co", after)
    d = np.round((after - before) * 1e6).astype(np.int64)          # micrometres
    bpy.data.meshes.remove(me)
    out = hashlib.sha256(d.tobytes()).hexdigest()[:16], round(float(np.abs(after - before).max()) * 1000, 3)
    return out + ((after - before).astype(np.float32),) if with_array else out


# ------------------------------------------------------------------ tests: surface plan schema
@test
def plan_default_is_valid():
    errors, warnings = sp.validate([dict(sp.FIELD_DEFAULTS, **r) for r in sp.DEFAULT_PLAN])
    assert not errors, errors


@test
def plan_accepts_every_surface_type():
    for i, stype in enumerate(sp.SURFACE_TYPES):
        plan, warnings = sp.resolve([{"region_id": f"custom_{i}", "surface_type": stype}])
        assert plan[-1]["surface_type"] == stype
        if stype in sp.PLANNED_ONLY:
            assert any("planned only" in w for w in warnings), (stype, warnings)


@test
def plan_rejects_bad_values():
    bad = [{"region_id": "x", "surface_type": "glitter"}, {"region_id": "x", "coverage_density": 1.5},
           {"region_id": "x", "geometry_strategy": "scale_field:nonexistent"}, {"region_id": "x", "geometry_strategy": "magic"},
           {"region_id": "x", "surface_orientation": "sideways"}, {"region_id": "x", "deformation_requirements": "melt"},
           {"region_id": "x", "detail_scale": -1}]
    for o in bad:
        try:
            sp.resolve([o])
        except ValueError:
            continue
        raise AssertionError(f"accepted invalid region {o}")
    errors, _ = sp.validate([{"region_id": "a", **sp.FIELD_DEFAULTS}, {"region_id": "a", **sp.FIELD_DEFAULTS}])
    assert any("duplicate" in e for e in errors)


@test
def plan_overrides_merge_by_id():
    plan, _ = sp.resolve([{"region_id": "dorsal", "detail_scale": 0.03}, {"region_id": "mane", "surface_type": "mane",
                                                                          "geometry_strategy": "fur_groom"}])
    by = {r["region_id"]: r for r in plan}
    assert by["dorsal"]["detail_scale"] == 0.03 and by["dorsal"]["geometry_strategy"] == "scale_field:dorsal"
    assert by["mane"]["coverage_density"] == 1.0 and plan[-1]["region_id"] == "mane"
    assert len(plan) == len(sp.DEFAULT_PLAN) + 1


# ------------------------------------------------------------------ tests: backward compatibility of the scale spec
@test
def scale_spec_unchanged_without_plan_overrides():
    plan, _ = sp.resolve(None)
    assert sp.scale_spec(plan, None) is None
    assert sp.scale_spec(plan, True) is None
    for spec in (DRAGONISH, {"seed": 11, "limb_plates": {"height": 0.0}, "flank_rows": {"enabled": True}}):
        assert sp.scale_spec(plan, spec) == spec, sp.scale_spec(plan, spec)


@test
def scale_spec_from_explicit_plan_choices():
    plan, _ = sp.resolve([{"region_id": "flank", "enabled": True, "scale": {"size": (0.016, 0.014)}},
                          {"region_id": "paravertebral", "coverage_density": 0}])
    spec = sp.scale_spec(plan, {"seed": 3, "flank_rows": {"height": 0.002}})
    assert spec["flank_rows"] == {"size": (0.016, 0.014), "enabled": True, "height": 0.002}, spec["flank_rows"]
    assert spec["paravertebral"]["height"] == 0.0 and spec["seed"] == 3


# ------------------------------------------------------------------ tests: scale field
@test
def worley_edge_distance_is_continuous():
    u = np.linspace(0.0, 6.0, 6001)
    v = np.full_like(u, 0.37)
    e, _, _ = scale_field.worley2(u, v, 5, 0.8, 0.0)
    step = u[1] - u[0]
    assert np.abs(np.diff(e)).max() <= 3 * step, np.abs(np.diff(e)).max()
    P = np.stack([u, np.full_like(u, 0.21), np.full_like(u, 0.53)], 1)
    e3, _, _ = scale_field.worley3(P, 5, 0.8)
    assert np.abs(np.diff(e3)).max() <= 3 * step, np.abs(np.diff(e3)).max()


@test
def scale_field_matches_golden():
    golden = json.load(open(GOLDEN, encoding="utf-8"))
    arrays = np.load(GOLDEN_NPZ)
    for case, spec in CASES.items():
        h, mx, d = displacement_hash(scale_field, spec, with_array=True)
        if h != golden[case]["hash"]:       # a value on a micrometre rounding edge can flip; compare the arrays
            diff = float(np.abs(d - arrays[case]).max())
            assert diff <= FLOAT32_M, f"{case}: displacement differs from golden by {diff * 1e6:.3f} um (max {mx} mm vs {golden[case]['max_mm']})"
    # negative control: the check must notice a real change (flank rows switched on)
    h, _, d = displacement_hash(scale_field, dict(DRAGONISH, flank_rows={"enabled": True}), with_array=True)
    assert h != golden["dragon_v12"]["hash"] and float(np.abs(d - arrays["dragon_v12"]).max()) > 100 * FLOAT32_M, \
        "golden check did not detect a changed displacement"


@test
def flank_rows_only_change_the_spine_region():
    me = synthetic_mesh()
    n = len(me.vertices)
    w = np.empty(n, np.float32)
    me.attributes["w_spine"].data.foreach_get("value", w)
    base = np.empty(n * 3)
    me.vertices.foreach_get("co", base)
    bpy.data.meshes.remove(me)
    outs = []
    for spec in (DRAGONISH, dict(DRAGONISH, flank_rows={"enabled": True})):
        m = synthetic_mesh()
        scale_field.apply(m, spec)
        c = np.empty(n * 3)
        m.vertices.foreach_get("co", c)
        outs.append(c.reshape(-1, 3))
        bpy.data.meshes.remove(m)
    changed = np.linalg.norm(outs[0] - outs[1], axis=1) > 1e-7
    assert changed.any(), "flank_rows enabled changed nothing"
    assert not (changed & (w < 1e-3)).any(), "flank_rows changed vertices outside w_spine"


# ------------------------------------------------------------------ tests: v1.3-E fur interface
@test
def fur_interface_validates_and_reports_without_building():
    plan, warnings = sp.resolve([{"region_id": "mane", "surface_type": "mane", "geometry_strategy": "fur_groom",
                                  "weight": "w_dorsal", "fur": {"length": 0.12, "clump": 0.6, "root_hex": "#3A2A1A"}}])
    assert any("planned only" in w for w in warnings), warnings
    req = sp.fur_requests(plan)
    assert len(req) == 1 and req[0]["fur"]["length"] == 0.12 and req[0]["fur"]["curl"] == sp.FUR_FIELDS["curl"][0], req
    assert "no fur generator" in req[0]["status"]
    assert sp.fur_requests(sp.resolve(None)[0]) == [], "the default plan must not request fur"
    for bad in ({"length": -1}, {"clump": 2.0}, {"root_hex": "brown"}, "long"):
        try:
            sp.resolve([{"region_id": "mane", "surface_type": "mane", "fur": bad}])
        except ValueError:
            continue
        raise AssertionError(f"accepted invalid fur {bad!r}")


@test
def hair_api_smoke():
    """Blender API the fur interface targets: hair Curves on a surface and the bundled hair node groups."""
    import bmesh
    path = os.path.join(bpy.utils.system_resource("DATAFILES"), "assets", "nodes", "procedural_hair_node_assets.blend")
    assert os.path.isfile(path), path
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        groups = set(src.node_groups)
    missing = {v[3] for v in sp.FUR_FIELDS.values()} - groups
    assert not missing, f"hair node groups missing in this Blender: {missing}"
    me = bpy.data.meshes.new("t_scalp")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.1)
    bm.to_mesh(me)
    bm.free()
    scalp = bpy.data.objects.new("t_scalp", me)
    hair = bpy.data.hair_curves.new("t_hair")
    hair.add_curves([5] * 8)
    hair.surface = scalp
    ob = bpy.data.objects.new("t_hair", hair)
    assert ob.type == "CURVES" and len(hair.curves) == 8 and len(hair.points) == 40 and hair.surface == scalp
    bpy.data.objects.remove(ob)
    bpy.data.hair_curves.remove(hair)
    bpy.data.objects.remove(scalp)
    bpy.data.meshes.remove(me)


# ------------------------------------------------------------------ tests: v1.3-D material profiles
def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


@test
def material_profiles_default_to_v12_and_apply_variants():
    import detail_materials as dm
    import material_palette as mp
    plan, _ = sp.resolve(None)
    mats = dm.build_all(prefix="T13_", profiles=[r["material_profile"] for r in plan])
    claw, body = _principled(mats["claw"]), _principled(mats["body"])
    assert abs(claw.inputs["Roughness"].default_value - 0.28) < 1e-6 and abs(claw.inputs["Coat Weight"].default_value - 0.35) < 1e-6
    assert body.inputs["Subsurface Weight"].default_value == 0.0 and not dm.PROFILE, dm.PROFILE   # v1.2 look
    plan, _ = sp.resolve([{"region_id": "claws", "material_profile": "claw:matte"},
                          {"region_id": "skin_base", "material_profile": "body:sss"}])
    mats = dm.build_all(prefix="T13_", profiles=[r["material_profile"] for r in plan])
    claw, body = _principled(mats["claw"]), _principled(mats["body"])
    assert abs(claw.inputs["Roughness"].default_value - 0.42) < 1e-6 and abs(claw.inputs["Coat Weight"].default_value - 0.06) < 1e-6
    assert abs(body.inputs["Subsurface Weight"].default_value - 0.06) < 1e-6
    try:
        dm.build_all(prefix="T13_", profiles=["claw:glitter"])
        raise AssertionError("unknown variant accepted")
    except ValueError:
        pass
    dm.build_all(prefix="T13_", palette={"skin": {"hex": "#FF0000"}})            # one creature's palette ...
    dm.build_all(prefix="T13_")                                                    # ... must not leak into the next
    assert dm.PAL["skin"]["hex"] == mp.PALETTE["skin"]["hex"], dm.PAL["skin"]
    for m in [m for m in bpy.data.materials if m.name.startswith("T13_")]:
        bpy.data.materials.remove(m)


# ------------------------------------------------------------------ tests: v1.3-C joint relief, relief calibration
@test
def joint_relief_lowers_scales_only_at_joints():
    disp = []
    for spec in (DRAGONISH, dict(DRAGONISH, joint_relief=0.5)):
        me = synthetic_mesh()
        n = len(me.vertices)
        co = np.empty(n * 3)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        wj = np.clip(1.0 - np.linalg.norm(co - np.array([-0.3, 0.0, 0.0]), axis=1) / 0.08, 0, 1)   # a "knee" on -x
        me.attributes.new("w_joint", "FLOAT", "POINT").data.foreach_set("value", wj.astype(np.float32))
        scale_field.apply(me, spec)
        after = np.empty(n * 3)
        me.vertices.foreach_get("co", after)
        disp.append(np.linalg.norm(after.reshape(-1, 3) - co, axis=1))
        bpy.data.meshes.remove(me)
    at, away = wj > 0.999, wj == 0.0
    # Blender stores float32 coordinates: at 0.3 m their resolution is ~3e-8 m, so compare at 1e-7 m
    assert np.allclose(disp[1][away], disp[0][away], atol=1e-7), "joint relief changed skin away from joints"
    assert np.allclose(disp[1][at], disp[0][at] * 0.5, atol=1e-7), "joint relief did not halve the scales at the joint"
    plan, _ = sp.resolve(None)
    assert sp.scale_spec(plan, DRAGONISH, 0.5)["joint_relief"] == 0.5
    assert sp.scale_spec(plan, DRAGONISH, 0.0) == DRAGONISH                       # off by default: v1.2 spec
    plan, _ = sp.resolve([{"region_id": "limbs", "deformation_requirements": "rigid"},
                          {"region_id": "limb_outer", "deformation_requirements": "rigid"}])
    assert "joint_relief" not in sp.scale_spec(plan, DRAGONISH, 0.5), "rigid limbs must not get joint relief"


def _relief_functions():
    import ast
    src = open(os.path.join(SKILL, "scripts", "quality_metrics.py"), encoding="utf-8").read()
    fns = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name in ("taubin", "band_relief")]
    ns = {"np": np, "math": math}
    exec(compile(ast.Module(fns, []), "quality_metrics", "exec"), ns)
    return ns["taubin"], ns["band_relief"]


def _sine_grid(edge, wavelength, N=200):
    i, j = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    x, y = i.ravel() * edge, j.ravel() * edge
    idx = i * N + j
    ed = np.concatenate([np.stack([idx[:-1, :].ravel(), idx[1:, :].ravel()], 1),
                         np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], 1)])
    k = 2 * math.pi / wavelength
    z = 0.001 * np.sin(k * x) * np.sin(k * y)                                       # 1 mm skin bumps
    nr = np.stack([-0.001 * k * np.cos(k * x) * np.sin(k * y), -0.001 * k * np.sin(k * x) * np.cos(k * y), np.ones_like(x)], 1)
    nr /= np.linalg.norm(nr, axis=1)[:, None]
    inner = ((i > N // 4) & (i < 3 * N // 4) & (j > N // 4) & (j < 3 * N // 4)).ravel()
    return np.stack([x, y, z], 1), ed, nr, z, inner


@test
def relief_metrics_are_calibrated():
    """Known-height skin: what fraction of a feature's height each relief metric reports (p90 / true p90)."""
    taubin, band_relief = _relief_functions()
    edge = 0.00169                                                                   # dragon high-res edge
    fine_iters = int(round(8 * (3.2 / 1.69) ** 2))
    ratio = {}
    for wl in (0.005, 0.012, 0.020, 0.045):
        co, ed, nr, z, inner = _sine_grid(edge, wl)
        true = np.percentile(np.abs(z[inner]), 90)
        fine = ((co - taubin(co, ed, fine_iters)) * nr).sum(1)
        band, _ = band_relief(co, ed, nr, edge, 0.030)
        ratio[wl] = (np.percentile(np.abs(fine[inner]), 90) / true, np.percentile(np.abs(band[inner]), 90) / true)
        print(f"[calib] {wl * 1000:.0f} mm features: fine reports {ratio[wl][0]:.2f}, band_30mm {ratio[wl][1]:.2f} of their height")
    assert ratio[0.005][0] > 0.8 and ratio[0.020][0] < 0.1, ratio                   # fine = high-pass near 10 mm
    assert ratio[0.012][1] > 0.8 and ratio[0.045][1] < 0.1, ratio                   # band ends near 30 mm
    co, ed, nr, z, inner = _sine_grid(0.0032, 0.012)                                 # same band at 3.2 mm edges
    band, _ = band_relief(co, ed, nr, 0.0032, 0.030)
    assert np.percentile(np.abs(band[inner]), 90) / np.percentile(np.abs(z[inner]), 90) > 0.8
    assert band_relief(co, ed, nr, 0.0032, 0.015)[0] is None, "a band under 7 edges must be refused"


# ------------------------------------------------------------------ tests: v1.3-B kit helpers
def _old_follow_limbs(p, pairs):
    """The dragon's follow_limbs before v1.3 (reference implementation)."""
    from mathutils import Vector as V
    p = V(p)
    for old, new in pairs:
        best = None
        for i in range(len(old) - 1):
            a, b = V(old[i]), V(old[i + 1])
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
            d = (p - (a + ab * t)).length
            if best is None or d < best[0]:
                best = (d, i, t)
        d, i, t = best
        w = max(0.0, min(1.0, (0.16 - d) / 0.08))
        if w > 0:
            p = p + (V(new[i]).lerp(V(new[i + 1]), t) - V(old[i]).lerp(V(old[i + 1]), t)) * w
    return p


@test
def follow_chains_matches_dragon_follow_limbs():
    import creature_kit as ck
    old = [(0.10, -0.30, 0.68), (0.19, -0.31, 0.56), (0.225, -0.255, 0.44), (0.24, -0.215, 0.35), (0.25, -0.355, 0.05)]
    new = [(x + d, y, z) for (x, y, z), d in zip(old, (0.0, 0.02, 0.045, 0.06, 0.0))]
    rng = np.random.default_rng(1)
    for p in rng.uniform([-0.1, -0.6, 0.0], [0.5, 0.1, 0.8], (400, 3)):
        a, b = ck.follow_chains(p, ((old, new),), full=0.08, fade=0.16), _old_follow_limbs(p, ((old, new),))
        assert (a - b).length < 1e-12, (p, a, b)


@test
def collar_raises_skin_around_a_base():
    import bmesh
    import creature_kit as ck
    me = bpy.data.meshes.new("t_plane")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=200, y_segments=200, size=0.2)
    bm.to_mesh(me)
    bm.free()
    moved = ck.collar(me, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.02)
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    r = np.linalg.norm(co[:, :2], axis=1)
    assert moved > 0 and abs(co[:, 2].max() - 0.007) < 1e-4, co[:, 2].max()     # 0.35 x 20 mm = 7 mm at the base
    assert np.abs(co[r > 0.0441, 2]).max() < 1e-9, "collar spread past 2.2 x radius"
    bpy.data.meshes.remove(me)
    # a claw on the end of a toe (cylinder along +x): the end cap swells, the side wall does not slide along +x
    me = bpy.data.meshes.new("t_toe")
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=True, segments=48, radius1=0.012, radius2=0.012, depth=0.08)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y"))
    bmesh.ops.subdivide_edges(bm, edges=bm.edges, cuts=6, use_grid_fill=True)
    bm.to_mesh(me)
    bm.free()
    me.update()
    before = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", before)
    before = before.reshape(-1, 3)
    ck.collar(me, (0.04, 0.0, 0.0), (1.0, 0.0, 0.0), 0.009)
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    mv = co.reshape(-1, 3) - before
    side = (before[:, 0] < 0.035) & (before[:, 0] > 0.02)
    assert np.abs(mv[side, 0]).max() < 1e-4, np.abs(mv[side, 0]).max()            # no sliding along the claw
    assert mv[before[:, 0] > 0.0399, 0].max() > 0.002, mv[:, 0].max()              # the toe end swells outward
    bpy.data.meshes.remove(me)
    # scaled skin (0.5 mm bumps, 10 mm apart) and two overlapping collars (neighbouring claws)
    me = bpy.data.meshes.new("t_scaly")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=240, y_segments=240, size=0.2)
    for v in bm.verts:
        v.co.z = 0.0005 * math.sin(2 * math.pi * v.co.x / 0.01) * math.sin(2 * math.pi * v.co.y / 0.01)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()
    before = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", before)
    before = before.reshape(-1, 3)
    ck.apply_collars(me, [((-0.005, 0.0, 0.0), (0.0, 0.0, 1.0), 0.02, None, False),
                          ((0.005, 0.0, 0.0), (0.0, 0.0, 1.0), 0.02, None, False)])
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    mv = co.reshape(-1, 3) - before
    assert mv[:, 2].max() < 0.007 * 1.02, mv[:, 2].max()                           # overlap takes the larger, no ridge
    big = mv[:, 2] > 0.001
    lateral = np.linalg.norm(mv[big, :2], axis=1) / mv[big, 2]
    assert np.percentile(lateral, 99) < 0.03, np.percentile(lateral, 99)          # smoothed 0.004; near-raw normals 0.09 (crumpling)
    bpy.data.meshes.remove(me)


@test
def stroke_guard_detects_a_part_in_front():
    import bmesh
    import sculpt_driver as sdr
    from mathutils import Vector as V
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    for x in (0.0, 0.15):                      # the target surface at x = 0 and an occluder (a "thigh") at x = 0.15
        g = bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=0.2)
        bmesh.ops.rotate(bm, verts=g["verts"], cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y"))
        bmesh.ops.translate(bm, verts=g["verts"], vec=(x, 0, 0))
    tree = BVHTree.FromBMesh(bm)
    pts = [(0.0, y, 0.0) for y in (-0.05, 0.0, 0.05)]
    view = V((-1.0, 0.0, 0.0))                 # looking from +x, like SIDE
    hits, offs = sdr.surface_hits(tree, pts, view, reach=0.3)
    assert len(hits) == 3 and sdr.guard_skips(np.median(offs), 0.008), offs          # an 8 mm crease caught by the occluder
    hits, offs = sdr.surface_hits(tree, [(0.15, 0.0, 0.0)], view, reach=0.3)
    assert not sdr.guard_skips(np.median(offs), 0.008), offs                         # a stroke on the occluder itself is fine
    hits, offs = sdr.surface_hits(tree, [(0.10, y, 0.0) for y in (-0.05, 0.0, 0.05)], view, reach=0.3)
    assert not sdr.guard_skips(np.median(offs), 0.05), offs     # a 5 cm Smooth placed 5 cm inside the "thigh" lands on its skin
    assert sdr.guard_skips(np.median(offs), 0.008), offs       # ... but the same offset is too far for an 8 mm crease
    bm.free()


# ------------------------------------------------------------------ tests: examples still load
@test
def examples_import_and_resolve_plans():
    for name, cls in (("dragon", "Dragon"), ("raptor", "Raptor"), ("komodo", "Komodo")):
        path = os.path.join(SKILL, "examples", name, f"{name}.py")
        spec = importlib.util.spec_from_file_location(f"ex_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cr = getattr(mod, cls)()
        plan, _ = sp.resolve(cr.surface_plan)
        sp.scale_spec(plan, cr.scales)
        assert cr.surface_plan is None or isinstance(cr.surface_plan, list)


def make_golden(module_path):
    spec = importlib.util.spec_from_file_location("golden_scale_field", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out, arrays = {}, {}
    for case, s in CASES.items():
        h, mx, arrays[case] = displacement_hash(mod, s, with_array=True)
        out[case] = {"hash": h, "max_mm": mx}
    out["_recorded_from"] = os.path.basename(os.path.dirname(module_path)) + "/" + os.path.basename(module_path)
    json.dump(out, open(GOLDEN, "w", encoding="utf-8"), indent=1)
    np.savez_compressed(GOLDEN_NPZ, **arrays)
    print("[tests] golden written:", out)


if __name__ == "__main__":
    if "--make-golden" in ARGV:
        make_golden(ARGV[ARGV.index("--make-golden") + 1])
        sys.exit(0)
    failed = [r for r in RESULTS if not r[1]]
    for name, ok, msg in RESULTS:
        print(f"[tests] {'PASS' if ok else 'FAIL'} {name}" + ("" if ok else f"\n{msg}"))
    print(f"[tests] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.stdout.flush()
    os._exit(1 if failed else 0)
