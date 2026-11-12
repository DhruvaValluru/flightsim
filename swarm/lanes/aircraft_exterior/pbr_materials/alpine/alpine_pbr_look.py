"""Alpine aircraft PBR look: the constants, the tier table and the Python twin
of shaders/alpine_detail.hlsl. Stdlib only (it also runs inside UnrealEditor's
Python). VISUAL-ONLY: nothing here touches a -quality=measure render, a label
or the flight model.

What the lane adds to the class masters (scripts/aircraft_look.py CLASS_SCALARS)
for the alpine scenario (snow ground, cold, thin air):

* one baked, tileable RGBA detail texture sampled by object-space projection,
  replacing per-pixel procedural noise on the integrated GPU:
  R roughness breakup, G flow-aligned grime, B frost threshold noise,
  A low-frequency albedo modulation;
* from tier 1, a baked oil-canning normal map (shallow, never tier 0: round 23
  traced the dark airframes to shading normals, so the stable tier keeps the
  mesh's own normal);
* a hard albedo contract: the lane can darken a base colour by at most
  :data:`MAX_DARKENING` and the result stays inside the class's range.

Every look number is a look choice, UNCALIBRATED until a probe render on the
Windows laptop sets it, unless it says "measured" (then it is the repo's
vendored Physically Based database value, read by scripts/aircraft_look.py).
"""

from __future__ import annotations

UNCALIBRATED = "UNCALIBRATED: set by probe render on the render machine"
SCHEMA = "flightsim-swarm-alpine-pbr/1"
LANE_ID = "aircraft_exterior.pbr_materials.alpine"

# -- texture layout ---------------------------------------------------------
#: One tile of either texture covers this many centimetres of skin. U runs
#: along the body X axis (the airflow), so the grime streaks run aft.
TILE_CM = 240.0
#: Panel bays per tile for the oil-canning dishes: 30 cm x 15 cm bays.
BAYS_U, BAYS_V = 8, 16
#: Dish depth, cm (0.8 mm: a stressed-skin dimple; from memory, UNCALIBRATED).
OILCAN_DEPTH_CM = 0.08
#: The normal map stores slope x this gain (a 1 degree slope is 2 LSB at 8
#: bits otherwise); the shader divides it back out.
NORMAL_STORE_GAIN = 6.0
#: The shader's side/top projection switch on |N_local.z|.
TOP_PROJECTION_NZ = 0.7

# -- albedo contract (linear sRGB) ------------------------------------------
#: Per class: (floor, cap) of the base colour the lane may output. Paint cap
#: 0.9 is aircraft_look.py's AlbedoMax; rubber floor 0.023 is the measured
#: tyre (Physically Based "Tire"); paint floor 0.03 is a black enamel, from
#: memory. A bare metal's base colour is its F0, so only a floor applies.
ALBEDO_RANGE = {
    "paint": (0.03, 0.90),
    "bare_metal": (0.30, 1.00),
    "rubber": (0.023, 0.90),
}
#: A = 0 multiplies the base colour by this, A = 1 by 1.
ALBEDO_MOD_MIN = 0.88
#: Full grime (G = 1, GrimeAmount = 1) multiplies by 1 - this.
GRIME_DARKEN_MAX = 0.40
#: GrimeAmount is clamped to this in the shader, so the worst case is fixed.
GRIME_AMOUNT_MAX = 0.25
#: The lane's worst-case multiplier on any base colour: the no-dark-aircraft
#: bound the test and the pixel gate both read.
MAX_DARKENING = ALBEDO_MOD_MIN * (1.0 - GRIME_DARKEN_MAX * GRIME_AMOUNT_MAX)  # 0.792

# -- frost (rime on forward-facing skin; visual-only) -----------------------
FROST_ALBEDO = 0.75      # aged rime, below fresh snow; from memory
FROST_ROUGHNESS = 0.85
FROST_SOFTNESS = 0.08    # smoothstep width on the B channel
ROUGHNESS_MIN = 0.045    # UE's own clamp floor region; avoids a mirror lobe
GRIME_ROUGHNESS_ADD = 0.20

#: The alpine overrides on the class defaults. Everything else stays what
#: scripts/aircraft_look.py CLASS_SCALARS says.
ALPINE_SCALARS = {
    "paint": {"GrimeAmount": 0.10, "AlbedoModAmount": 1.0, "FrostAmount": 0.35,
              "FrostOpacity": 0.8, "RoughnessBreakup": 0.12, "AlpineNormalAmount": 1.5},
    "bare_metal": {"GrimeAmount": 0.12, "AlbedoModAmount": 0.5, "FrostAmount": 0.35,
                   "FrostOpacity": 0.8, "RoughnessBreakup": 0.20, "AlpineNormalAmount": 2.0},
    "rubber": {"GrimeAmount": 0.0, "AlbedoModAmount": 0.0, "FrostAmount": 0.0,
               "FrostOpacity": 0.0, "RoughnessBreakup": 0.08, "AlpineNormalAmount": 0.0},
}

# -- tiers ------------------------------------------------------------------
#: Block-compressed 8 bits per pixel (BC3/BC5/BC7 all are) plus a full mip
#: chain (x 4/3). ESTIMATES, not measurements.


def texture_mb(size: int) -> float:
    return size * size * (4.0 / 3.0) / (1024.0 * 1024.0)


TIERS = (
    {"tier": 0, "size": 256, "normal_map": False, "projection": "select (1 sample)",
     "texture_samples": 1, "clear_coat": False, "frost": True,
     "cvars": {"r.ClearCoatNormal": 0},
     "summary": "256 px detail pack only, one projected sample, mesh normal untouched, "
                "Default Lit (no clear coat lobe), frost by threshold"},
    {"tier": 1, "size": 512, "normal_map": True, "projection": "select (1 sample each)",
     "texture_samples": 2, "clear_coat": True, "frost": True,
     "cvars": {"r.ClearCoatNormal": 0},
     "summary": "512 px detail pack + oil-canning normal, two samples, clear coat on paint"},
    {"tier": 2, "size": 1024, "normal_map": True, "projection": "biplanar blend (2 samples each)",
     "texture_samples": 4, "clear_coat": True, "frost": True,
     "cvars": {"r.ClearCoatNormal": 0},
     "summary": "1024 px maps, side/top blended (no projection seam), four samples, clear coat"},
    {"tier": 3, "size": 2048, "normal_map": True, "projection": "biplanar blend (2 samples each)",
     "texture_samples": 4, "clear_coat": True, "frost": True,
     "cvars": {"r.ClearCoatNormal": 1},
     "summary": "2048 px maps, four samples, clear coat with its own bottom normal "
                "(r.ClearCoatNormal 1: the oil-canning under a smooth coat)"},
)


def tier_table():
    rows = []
    for t in TIERS:
        row = dict(t)
        row["est_vram_mb"] = round(texture_mb(t["size"]) * (2 if t["normal_map"] else 1), 3)
        row["est_vram_basis"] = "8 bpp block compression x 4/3 mip chain; ESTIMATE, never measured"
        row["sustained"] = "UNMEASURED"
        rows.append(row)
    return rows


# -- the shader's Python twin ------------------------------------------------

def _saturate(x):
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _lerp(a, b, t):
    return a + (b - a) * t


def _smoothstep(e0, e1, x):
    t = _saturate((x - e0) / (e1 - e0))
    return t * t * (3.0 - 2.0 * t)


def frost_mask(detail_b, frost_amount, frost_geo):
    """0..1 frost cover: B is rank-equalised by the bake, so the covered area
    fraction on forward-facing skin (frost_geo 1) is about frost_amount."""
    cover = _saturate(frost_amount) * _saturate(frost_geo)
    if cover <= 0.0:
        return 0.0
    edge = 1.0 - cover
    return _smoothstep(edge, edge + FROST_SOFTNESS, detail_b)


def shade(material_class, base, detail, roughness, metallic=0.0, clear_coat=0.0,
          frost_geo=0.0, scalars=None):
    """The twin of AlpineDetail() in shaders/alpine_detail.hlsl.

    base: linear RGB triple. detail: the RGBA texel, 0..1. Returns
    {"base", "roughness", "metallic", "clear_coat", "frost"}.
    """
    p = dict(ALPINE_SCALARS[material_class])
    if scalars:
        p.update(scalars)
    lo, hi = ALBEDO_RANGE[material_class]
    r_tex, g_tex, b_tex, a_tex = detail
    grime = _saturate(g_tex) * min(max(p["GrimeAmount"], 0.0), GRIME_AMOUNT_MAX)
    mod = _lerp(1.0, _lerp(ALBEDO_MOD_MIN, 1.0, _saturate(a_tex)), _saturate(p["AlbedoModAmount"]))
    mult = mod * (1.0 - GRIME_DARKEN_MAX * grime)
    frost = frost_mask(b_tex, p["FrostAmount"], frost_geo) * _saturate(p["FrostOpacity"])
    out = []
    for c in base:
        c0 = min(max(c, lo), hi)
        c1 = c0 * mult
        # frost only ever brightens: a white livery is not greyed by rime
        c2 = max(c1, _lerp(c1, FROST_ALBEDO, frost))
        out.append(min(max(c2, lo), hi))
    rough = roughness + (r_tex - 0.5) * 2.0 * p["RoughnessBreakup"] + grime * GRIME_ROUGHNESS_ADD
    rough = _lerp(min(max(rough, ROUGHNESS_MIN), 1.0), FROST_ROUGHNESS, frost)
    return {"base": tuple(out), "roughness": rough,
            "metallic": metallic * (1.0 - frost),
            "clear_coat": clear_coat * (1.0 - frost), "frost": frost}


def normal_from_texel(nx, ny, amount):
    """Decode a stored normal texel (0..1 channels) at AlpineNormalAmount."""
    sx = (nx * 2.0 - 1.0) * amount / NORMAL_STORE_GAIN
    sy = (ny * 2.0 - 1.0) * amount / NORMAL_STORE_GAIN
    inv = (sx * sx + sy * sy + 1.0) ** -0.5
    return (sx * inv, sy * inv, inv)


#: Look parameters the other alpine lanes must agree with. Proposals from this
#: lane, none measured; the integrator settles them.
SHARED_PARAMS = {
    "scenario": "alpine",
    "ground_albedo": 0.80,
    "ground_albedo_basis": "fresh/settled snow, broadband (Warren 1982 gives 0.8-0.9 for fresh "
                           "snow; from memory, not fetched)",
    "sun_elevation_deg": 35.0,
    "sun_elevation_basis": "late-winter midday at 46 N; assumption, the scenario card decides",
    "exposure_ev100": 15.0,
    "exposure_basis": "sunlit snow; assumption",
    "colour_temperature_k": 6500,
    "haze_density": 0.005,
    "haze_basis": "thin, clean air at 3-4.5 km; UE ExponentialHeightFog density units; assumption",
    "skylight_lower_hemisphere": "must carry the snow bounce (ground_albedo x a neutral-cool "
                                 "tint), never black: the airframe underside is lit by it",
    "aircraft_albedo_range_paint": list(ALBEDO_RANGE["paint"]),
    "aircraft_max_darkening": round(MAX_DARKENING, 4),
    "frost_albedo": FROST_ALBEDO,
    "frost_amount": 0.35,
    "detail_tile_cm": TILE_CM,
    "status": UNCALIBRATED,
}
