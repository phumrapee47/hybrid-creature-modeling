"""Geometric scales: per-vertex displacement of the high-poly surface (Phase B).

Level 1 (large plates) and Level 2 (individually readable scales) are real geometry: every scale is a cell of a
jittered (Worley) lattice, laid out in body coordinates for oriented scales (s along the nearest body chain, t
around it, from the body_st attribute) or in object space for isotropic ones (granular scales, head plates).
Level 3 (micro detail) stays in the material.

Each cell gets a 3D profile:
  pillow   rounded edges falling into the groove between scales (rim = groove width as a fraction of the cell)
  shingle  imbricate rows: the scale rises toward its posterior (tail-ward, +s) edge and drops steeply there, so
           rows read as overlapping. Displacement along the normal cannot undercut, so overlap is approximated.
  keel     a ridge along the scale's long axis (dorsal scales, osteoderms)
plus per-cell random height (+-15 %). The creature's region weights (w_dorsal, w_belly, ...) blend the patterns;
the oriented weights already fade to granular where two body chains compete, which hides parameterisation seams.

Writes attributes `scale_h` (0 groove .. 1 crown, for groove darkening) and `scale_tint` (per-cell random).
Sizes are for a ~3 m creature: scale them with body length (`size_scale`).
"""
import numpy as np

DEFAULTS = {
    "seed": 7,
    "size_scale": 1.0,
    "joint_relief": 0.0,     # v1.3: fraction of scale height removed at limb joints (body field w_joint)
    # Level 2, isotropic (object space): flanks, limbs, joints
    "granular": {"size": 0.010, "height": 0.0015, "rim": 0.30, "jitter": 0.9},     # v2 1.2 mm
    # Level 2, oriented along the limb chains: rows that overlap distally (v2 limbs were isotropic)
    "limb": {"size": (0.016, 0.014), "height": 0.0015, "rim": (0.22, 0.10), "rise": 0.45, "keel": 0.15, "keel_w": 0.12, "jitter": 0.7},
    # Level 2, oriented (body coordinates): keeled dorsal scales on neck, back and tail base
    "dorsal": {"size": (0.024, 0.020), "height": 0.0026, "rim": (0.22, 0.10), "rise": 0.45, "keel": 0.35, "keel_w": 0.12, "jitter": 0.75},
    # Level 1: two rows of osteoderm plates either side of the spine (dorsal arc distance band, m)
    "paravertebral": {"size": (0.044, 0.032), "height": 0.0050, "rim": (0.18, 0.08), "rise": 0.40, "keel": 0.6, "keel_w": 0.10,
                      "jitter": 0.35, "band": (0.012, 0.022, 0.065, 0.085)},
    # Level 1: transverse ventral plates (one plate across the belly band per row)
    "ventral": {"row": 0.034, "height": 0.0022, "rim": (0.30, 0.08), "rise": 0.55},
    # Level 2: tail whorls (staggered rows of rectangular scales; v1 jitter 0.25 read as a regular honeycomb)
    "tail": {"size": (0.020, 0.018), "height": 0.0020, "rim": (0.20, 0.08), "rise": 0.50, "jitter": 0.45, "stagger": 0.5},
    # Level 1: larger oriented plates on the outer limbs (shoulders, forearms, thighs)
    "limb_plates": {"size": (0.028, 0.024), "height": 0.0026, "rim": (0.18, 0.08), "rise": 0.40, "keel": 0.3, "keel_w": 0.12, "jitter": 0.6},
    # Level 2 + Level 1 on the head: small plates everywhere, large cranial plates on top
    "head": {"size": 0.013, "height": 0.0015, "rim": 0.25, "jitter": 0.8},
    "head_plates": {"size": 0.028, "height": 0.0030, "rim": 0.12, "jitter": 0.7, "top": (0.55, 0.75)},
    # Level 2: transverse toe scutes along each toe
    "toe": {"row": 0.010, "height": 0.0012, "rim": (0.30, 0.10), "rise": 0.50},
    # Level 2, optional: scales in rows along the body rings on the trunk, neck and tail flanks (w_spine), replacing
    # the isotropic granular cells there (crocodilian flanks). Off by default so existing creatures are unchanged.
    "flank_rows": {"enabled": False, "size": (0.015, 0.013), "height": 0.0020, "rim": (0.22, 0.12), "rise": 0.35,
                   "keel": 0.0, "keel_w": 0.12, "jitter": 0.30, "stagger": 0.15},
    # Level 2: labial (lip) scales in object (y, z)
    "labial": {"size": (0.012, 0.011), "height": 0.0010, "rim": 0.25, "jitter": 0.3},
}


# --------------------------------------------------------------------------- hashing and Worley lattices
def _hash(seed, *ints):
    """Deterministic integer hash -> float in [0, 1) (splitmix64 finaliser)."""
    with np.errstate(over="ignore"):
        x = np.full(ints[0].shape, np.uint64(seed) * np.uint64(0x9E3779B97F4A7C15), dtype=np.uint64)
        for k, a in enumerate(ints):
            x ^= a.astype(np.int64).astype(np.uint64) * np.uint64((0xBF58476D1CE4E5B9 + 2 * k + 1) & 0xFFFFFFFFFFFFFFFF)
            x ^= x >> np.uint64(31)
            x *= np.uint64(0x94D049BB133111EB)
            x ^= x >> np.uint64(29)
    return (x >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def _pt2(cu, cv, seed, jitter, stagger):
    """Absolute lattice position of the feature point of cell (cu, cv)."""
    return np.stack([cu + 0.5 + stagger * (cv % 2) + jitter * (_hash(seed, cu, cv) - 0.5),
                     cv + 0.5 + jitter * (_hash(seed + 1, cu, cv) - 0.5)], 1)


def worley2(u, v, seed, jitter=0.8, stagger=0.0):
    """2D Worley in lattice units, two passes (continuous edge distance):
    1) nearest feature point; 2) minimum distance to the bisectors with every point around *that* point's cell.
    Returns (edge distance, offset of the sample from its own feature point, cell random).
    stagger shifts every other row by `stagger` cells (brick-like whorls)."""
    x = np.stack([u, v], 1)
    iu, iv = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    n = len(u)
    d1 = np.full(n, 1e9)
    best = np.zeros((n, 2))
    bu, bv = iu.copy(), iv.copy()
    span = (-2, -1, 0, 1, 2) if stagger else (-1, 0, 1)
    for b in (-1, 0, 1):
        for a in span:
            cu, cv = iu + a, iv + b
            q = _pt2(cu, cv, seed, jitter, stagger)
            d = np.linalg.norm(q - x, axis=1)
            m = d < d1
            d1 = np.where(m, d, d1)
            best = np.where(m[:, None], q, best)
            bu, bv = np.where(m, cu, bu), np.where(m, cv, bv)
    e = np.full(n, 1e9)
    for b in (-2, -1, 0, 1, 2):
        for a in (-2, -1, 0, 1, 2):
            if a == 0 and b == 0:
                continue
            q = _pt2(bu + a, bv + b, seed, jitter, stagger)
            dvec = q - best
            L = np.linalg.norm(dvec, axis=1)
            dist = (((best + q) * 0.5 - x) * dvec).sum(1) / np.maximum(L, 1e-9)
            e = np.minimum(e, dist)
    return np.clip(e, 0.0, None), x - best, _hash(seed + 2, bu, bv)


def _pt3(c, seed, jitter):
    return np.stack([c[:, 0] + 0.5 + jitter * (_hash(seed, c[:, 0], c[:, 1], c[:, 2]) - 0.5),
                     c[:, 1] + 0.5 + jitter * (_hash(seed + 1, c[:, 0], c[:, 1], c[:, 2]) - 0.5),
                     c[:, 2] + 0.5 + jitter * (_hash(seed + 3, c[:, 0], c[:, 1], c[:, 2]) - 0.5)], 1)


def worley3(p, seed, jitter=0.8):
    """3D Worley (isotropic, object space), two passes like worley2 (second pass over the 27 cells around the
    nearest point's cell; exact for jitter <= ~0.8). Returns (edge distance, offset, cell random)."""
    ip = np.floor(p).astype(np.int64)
    n = len(p)
    d1 = np.full(n, 1e9)
    best = np.zeros((n, 3))
    bc = ip.copy()
    offs = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]
    for o in offs:
        cc = ip + np.array(o)
        q = _pt3(cc, seed, jitter)
        d = np.linalg.norm(q - p, axis=1)
        m = d < d1
        d1 = np.where(m, d, d1)
        best = np.where(m[:, None], q, best)
        bc = np.where(m[:, None], cc, bc)
    e = np.full(n, 1e9)
    for o in offs:
        if o == (0, 0, 0):
            continue
        q = _pt3(bc + np.array(o), seed, jitter)
        dvec = q - best
        L = np.linalg.norm(dvec, axis=1)
        e = np.minimum(e, (((best + q) * 0.5 - p) * dvec).sum(1) / np.maximum(L, 1e-9))
    return np.clip(e, 0.0, None), p - best, _hash(seed + 2, bc[:, 0], bc[:, 1], bc[:, 2])


# --------------------------------------------------------------------------- profiles
def pillow(e, rim):
    t = np.clip(e / np.maximum(rim, 1e-6), 0.0, 1.0)
    return 1.0 - (1.0 - t) ** 2


def oriented(e, off, cid, rim, rise=0.0, keel=0.0, keel_w=0.12):
    """Profile for oriented cells: off[:, 0] runs posterior (+s), off[:, 1] across."""
    rim_front, rim_back = rim if isinstance(rim, tuple) else (rim, rim)
    r = np.where(off[:, 0] > 0, rim_back, rim_front)        # steeper drop at the posterior edge
    h = pillow(e, r)
    if rise:
        h *= 1.0 - rise + rise * np.clip(0.5 + off[:, 0], 0.0, 1.0)
    if keel:
        h *= 1.0 + keel * np.exp(-(off[:, 1] / keel_w) ** 2)
    return h * (0.85 + 0.3 * cid)


def rows(x, rid_seed, rim, rise):
    """Transverse plates in rows along x (lattice units): edge distance = distance to the row boundary."""
    fx = x - np.floor(x)
    off = fx - 0.5
    e = np.minimum(fx, 1.0 - fx)
    rim_front, rim_back = rim
    h = pillow(e, np.where(off > 0, rim_back, rim_front)) * (1.0 - rise + rise * fx)
    rid = _hash(rid_seed, np.floor(x).astype(np.int64))
    return h * (0.9 + 0.2 * rid), rid


def _mix(w, a, b):
    return a + (b - a) * w


# --------------------------------------------------------------------------- driver
def _attr(me, name, n, vec=False):
    a = me.attributes.get(name)
    if a is None:
        return np.zeros((n, 3)) if vec else np.zeros(n)
    buf = np.empty(n * (3 if vec else 1), np.float32)
    a.data.foreach_get("vector" if vec else "value", buf)
    return buf.reshape(-1, 3).astype(np.float64) if vec else buf.astype(np.float64)


def apply(me, spec=None):
    """Displace `me` (high-poly body with body fields) by the scale height field. Returns stats for the log."""
    S = dict(DEFAULTS)
    if isinstance(spec, dict):
        for k, v in spec.items():
            S[k] = dict(S[k], **v) if isinstance(v, dict) and isinstance(S.get(k), dict) else v
    k = S["size_scale"]
    sd = S["seed"]
    n = len(me.vertices)
    co = np.empty(n * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    nr = np.empty(n * 3)
    me.vertices.foreach_get("normal", nr)
    nr = nr.reshape(-1, 3)
    st = _attr(me, "body_st", n, vec=True)
    s, t, td = st[:, 0], st[:, 1], st[:, 2]
    w = {name: _attr(me, name, n) for name in ("w_up", "w_dorsal", "w_belly", "w_head", "w_tail", "w_foot", "w_lip", "w_mouth", "w_limb",
                                               "w_limbdir", "w_spine")}
    # girth-normalised body coordinates: oriented scales shrink with the body (neck, tail tip) instead of keeping
    # one size everywhere (v1). u integrates ds / girth along the spine; around-coordinates divide by girth.
    g = _attr(me, "girth", n)
    g = np.where(g > 0, g, 1.0)
    u_b = _attr(me, "body_u", n) if me.attributes.get("body_u") else s
    tn, tdn = t / g, td / g

    def masked(mask, fn, *arrays):
        """Evaluate fn only on vertices where its region weight is non-zero; zeros elsewhere."""
        idx = np.where(mask)[0]
        p_, c_ = np.zeros(n), np.zeros(n)
        if len(idx):
            rp, rc = fn(*[a[idx] for a in arrays])
            p_[idx], c_[idx] = rp, rc
        return p_, c_

    def iso(key, seed):
        c = S[key]
        def fn(P):
            e, off, cid = worley3(P / (c["size"] * k), seed, c.get("jitter", 0.8))
            return pillow(e, c["rim"]) * (0.85 + 0.3 * cid), cid
        return fn

    def ori(key, seed):
        c = S[key]
        L, W = c["size"]
        def fn(u, v):
            e, off, cid = worley2(u / (L * k), v / (W * k), seed, c.get("jitter", 0.8), c.get("stagger", 0.0))
            return oriented(e, off, cid, c["rim"], c.get("rise", 0.0), c.get("keel", 0.0), c.get("keel_w", 0.12)), cid
        return fn

    def row(key, seed):
        c = S[key]
        return lambda x: rows(x / (c["row"] * k), seed, c["rim"], c["rise"])

    used = lambda name: w[name] > 1e-3  # noqa: E731
    a0, a1, a2, a3 = S["paravertebral"]["band"]
    tdn = td / np.where(_attr(me, "girth", n) > 0, _attr(me, "girth", n), 1.0)
    band = np.clip((tdn - a0) / (a1 - a0), 0, 1) * (1 - np.clip((tdn - a2) / (a3 - a2), 0, 1))
    top = np.clip((w["w_up"] - S["head_plates"]["top"][0]) / (S["head_plates"]["top"][1] - S["head_plates"]["top"][0]), 0, 1)
    # each pattern: normalised profile p (0 groove .. ~1 crown) and cell random; amplitudes (m) from the spec
    pg, cg = iso("granular", sd)(co)
    pd, cd = masked(used("w_dorsal"), ori("dorsal", sd + 10), u_b, tn)
    pp, cp = masked(used("w_dorsal") & (band > 1e-3), ori("paravertebral", sd + 20), u_b, tdn)
    pv, cv = masked(used("w_belly"), row("ventral", sd + 30), u_b)
    pt, ct = masked(used("w_tail"), ori("tail", sd + 40), u_b, tn)
    pm_, cm_ = masked(used("w_limbdir"), ori("limb", sd + 85), u_b, tn)
    pL, cL = masked(used("w_limb"), ori("limb_plates", sd + 90), u_b, tn)
    ph, ch = masked(used("w_head"), iso("head", sd + 50), co)
    pH, cH = masked(used("w_head") & (top > 1e-3), iso("head_plates", sd + 60), co)
    pf, cf = masked(used("w_foot"), row("toe", sd + 70), s)
    pl, cl = masked(used("w_lip"), ori("labial", sd + 80), co[:, 1], co[:, 2])
    rows_on = bool(S["flank_rows"].get("enabled"))
    pr_, cr_ = masked(used("w_spine"), ori("flank_rows", sd + 95), u_b, tn) if rows_on else (np.zeros(n), np.zeros(n))
    ag, ad, ap, at = S["granular"]["height"], S["dorsal"]["height"], S["paravertebral"]["height"], S["tail"]["height"]
    ah, aH, al = S["head"]["height"], S["head_plates"]["height"], S["labial"]["height"]

    # blend in the material's order (later regions override earlier ones); amplitudes blend with their profiles
    H = pg * ag
    P, C = pg.copy(), cg.copy()
    aL, am = S["limb_plates"]["height"], S["limb"]["height"]
    layers = [(w["w_spine"], pr_ * S["flank_rows"]["height"], pr_, cr_)] if rows_on else []
    layers += [
        (w["w_limbdir"], pm_ * am, pm_, cm_),
        (w["w_limb"], pL * aL, pL, cL),
        (w["w_dorsal"], _mix(band, pd * ad, pp * ap), _mix(band, pd, pp), _mix(band, cd, cp)),
        (w["w_tail"], pt * at, pt, ct),
        (w["w_belly"], pv * S["ventral"]["height"], pv, cv),
        (w["w_head"], _mix(top, ph * ah, pH * aH), _mix(top, ph, pH), _mix(top, ch, cH)),
        (w["w_foot"], pf * S["toe"]["height"], pf, cf),
        (w["w_lip"], pl * al, pl, cl),
    ]
    for wt, h_, p_, c_ in layers:
        H, P, C = _mix(wt, H, h_), _mix(wt, P, p_), _mix(wt, C, c_)
    jr = float(S.get("joint_relief") or 0.0)
    w_joint = _attr(me, "w_joint", n) if jr > 0 else np.zeros(n)
    if jr > 0:                       # flexible skin at elbows, knees and wrists carries lower scales
        H = H * (1.0 - jr * w_joint)
    keep = 1.0 - w["w_mouth"]
    H, P = H * keep, P * keep
    # displace the scale crowns outward, keeping grooves at the original surface
    co = co + nr * H[:, None]
    me.vertices.foreach_set("co", co.ravel())
    me.update()
    for name, val in (("scale_h", np.clip(P, 0, 1.2) / 1.2), ("scale_tint", C)):
        a = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", val.astype(np.float32))
    return {"vertices": n, "height_mm": {"p50": round(float(np.percentile(H, 50)) * 1000, 2),
                                         "p90": round(float(np.percentile(H, 90)) * 1000, 2),
                                         "max": round(float(H.max()) * 1000, 2)},
            "paravertebral_band_vertices": int((band * w["w_dorsal"] > 0.5).sum()),
            "joint_relief_vertices": int((w_joint > 0.5).sum())}
