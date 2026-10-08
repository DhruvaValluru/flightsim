"""The thunderstorm cell a render draws: the cumulonimbus, its anvil, its rain shaft.

The storm the physics flies is the microburst at the downburst block's
centre (core/environment/downburst.py: a Vicroy outflow under a downdraft
core of ``core_radius_m``) plus the gust front and the turbulence of the
thunderstorm composition. This module gives that storm a BODY, placed and
sized by the same numbers, so the cloud a viewer sees is the cloud the
aircraft is flying into:

* the TOWER: a cylinder of TOWER_RADII downburst core radii (never under
  TOWER_RADIUS_MIN_M) from the cloud base to the tropopause, widening
  upward, with an overshooting dome above the top;
* the ANVIL: the outflow spread at the tropopause, ANVIL_TOWERS tower
  radii, thinning to its edge and carried downwind of the tower by the
  stated wind (its direction; the speed aloft is not on any card, so the
  displacement is ANVIL_OFFSET_FRACTION of the anvil radius, stated);
* the RAIN SHAFT: under the base, the radius of the downdraft core (the
  rain is what drives a wet microburst's downdraft [unverified here]),
  with the Atlas 1953 extinction of the shaft's rain rate -- the same law
  the fog row and core/scene/precipitation.py use.

Extinction is physical, not artistic. A cloud of liquid water content
LWC whose droplets have effective radius r_e has, in geometric optics,

    sigma = 3 LWC / (2 rho r_e)   (1/m)

(Stephens 1978 [unverified here]): CORE_LWC_G_M3 of water droplets of
CORE_RE_UM gives ~0.19 /m -- a few tens of metres of visibility inside the
tower and the near-black base of a real storm; the anvil's ice
(ANVIL_IWC_G_M3, ANVIL_RE_UM) gives ~0.005 /m, the translucent veil.

The density field. The material (assets/shaders/weather/storm_cell.hlsl)
evaluates the SAME function as :func:`extinction_at` here, constant for
constant: a smooth shape (tower, overshoot, anvil, shaft) eroded by value
noise (PCG32 lattice hash, quintic interpolation, NOISE_OCTAVES of fBm at
BILLOW_M), the tower's noise advected UP at the updraft speed so the
towers boil, the anvil's carried downwind at the stated wind. tests/test_weather.py pins the
shader's constants to these.

Coordinates: metres, east / north / up, the cell centre at the origin on
the scene datum (engine Z = 0). The host places the origin at the
downburst block's centre.

Not claimed: the cell's evolution (it does not grow or decay over a run),
mammatus, the wall cloud and shelf cloud, hail; the anvil's displacement is
stated, not the wind aloft's; the cloud's extinction is per metre and
whether the engine's volumetric cloud reads its Extinction output per
metre is the first Windows measurement (docs/WEATHER.md).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence

from . import precipitation as rain_model
from .rain_particles import pcg32

#: The tower, the anvil, the base.
TOWER_RADII = 2.5
TOWER_RADIUS_MIN_M = 2500.0
TOWER_FLARE = 0.25
ANVIL_TOWERS = 4.0
ANVIL_DEPTH_M = 2500.0
ANVIL_OFFSET_FRACTION = 0.5
OVERSHOOT_M = 1000.0
OVERSHOOT_RADIUS_FRACTION = 0.5
CLOUD_BASE_AGL_M = 1000.0
#: The tropopause: 16 km at the equator, 11 km at the poles (stated).
TROPOPAUSE_EQUATOR_M = 16000.0
TROPOPAUSE_POLE_M = 11000.0
#: Microphysics (Stephens 1978's sigma = 3 LWC / (2 rho r_e)).
RHO_WATER = 1000.0
RHO_ICE = 917.0
CORE_LWC_G_M3 = 1.5
CORE_RE_UM = 12.0
ANVIL_IWC_G_M3 = 0.1
ANVIL_RE_UM = 25.0
ALBEDO = 0.98
UPDRAFT_MPS = 15.0
#: A thunderstorm with no stated rain rate rains this hard in its shaft.
STORM_RAIN_RATE_MMH = 50.0
#: The noise.
BILLOW_M = 600.0
NOISE_OCTAVES = 4
NOISE_GAIN = 0.5
NOISE_LACUNARITY = 2.03
EROSION = 0.45
#: The noise seed travels to the shader as a float: 24 bits are exact.
NOISE_SEED_MASK = 0xFFFFFF
SHAFT_NOISE_STRETCH = 8.0
#: The lightning glow's spread through the cloud (stated).
GLOW_DIFFUSION_M = 1500.0
#: The shape's soft edges (m).
EDGE_M = 250.0

#: The card's ``weather.cell`` keys, in their fixed order.
CARD_KEYS = ("centre", "base_m", "top_m", "overshoot_m", "tower_radius_m", "anvil_radius_m",
             "anvil_bottom_m", "anvil_offset_enu_m", "anvil_drift_enu_mps", "updraft_mps",
             "extinction_core_per_m", "extinction_anvil_per_m", "albedo", "shaft", "noise",
             "glow_diffusion_m", "basis")

REFERENCES = (
    "Stephens, G. L. 1978, J. Atmos. Sci. 35, 2123 (sigma = 3 LWC / (2 rho r_e)) [unverified here]",
    "Atlas, D. 1953 (the shaft's rain extinction; core/scene/precipitation.py)",
    "Schneider, A. 2015, 'The real-time volumetric cloudscapes of Horizon Zero Dawn', "
    "SIGGRAPH Advances (shape eroded by noise) [unverified here]",
)

NOT_CLAIMED = (
    "the cell does not grow or decay over a run",
    "no mammatus, wall cloud, shelf cloud or hail",
    "the anvil offset is stated (ANVIL_OFFSET_FRACTION), not the wind aloft's",
    "whether the engine reads the Extinction output per metre is measured on Windows",
)


def extinction_per_m(water_g_m3: float, radius_um: float, rho: float) -> float:
    """sigma = 3 LWC / (2 rho r_e), LWC in kg/m^3 and r_e in m."""
    return 3.0 * float(water_g_m3) * 1e-3 / (2.0 * float(rho) * float(radius_um) * 1e-6)


def tropopause_m(latitude_deg: float) -> float:
    s = abs(math.sin(math.radians(float(latitude_deg))))
    return TROPOPAUSE_EQUATOR_M - (TROPOPAUSE_EQUATOR_M - TROPOPAUSE_POLE_M) * s


def card_block(downburst_core_radius_m: float, latitude_deg: float, datum_m: float,
               wind_from_deg: float, wind_speed_mps: float, rate_mmh: Optional[float],
               seed: int) -> Dict[str, Any]:
    """``weather.cell`` in CARD_KEYS order."""
    tower = max(TOWER_RADIUS_MIN_M, TOWER_RADII * float(downburst_core_radius_m))
    anvil = ANVIL_TOWERS * tower
    top = tropopause_m(latitude_deg) - float(datum_m)
    base = CLOUD_BASE_AGL_M
    if top <= base + ANVIL_DEPTH_M:
        raise ValueError(f"weather.cell: a tropopause {top:.0f} m above the datum leaves no "
                         f"room for a storm over a {base:.0f} m base")
    to = math.radians(float(wind_from_deg) + 180.0)
    if float(wind_speed_mps) > 0.0:
        offset = [ANVIL_OFFSET_FRACTION * anvil * math.sin(to),
                  ANVIL_OFFSET_FRACTION * anvil * math.cos(to), 0.0]
    else:
        offset = [0.0, 0.0, 0.0]
    drift = [float(wind_speed_mps) * math.sin(to), float(wind_speed_mps) * math.cos(to)]
    stated = rate_mmh is not None
    rate = float(rate_mmh) if stated else STORM_RAIN_RATE_MMH
    rain = rain_model.rain(rate)
    return {
        "centre": "downburst",
        "base_m": base,
        "top_m": round(top, 3),
        "overshoot_m": OVERSHOOT_M,
        "tower_radius_m": round(tower, 3),
        "anvil_radius_m": round(anvil, 3),
        "anvil_bottom_m": round(top - ANVIL_DEPTH_M, 3),
        "anvil_offset_enu_m": [round(v, 3) for v in offset],
        "anvil_drift_enu_mps": [round(v, 6) for v in drift],
        "updraft_mps": UPDRAFT_MPS,
        "extinction_core_per_m": extinction_per_m(CORE_LWC_G_M3, CORE_RE_UM, RHO_WATER),
        "extinction_anvil_per_m": extinction_per_m(ANVIL_IWC_G_M3, ANVIL_RE_UM, RHO_ICE),
        "albedo": ALBEDO,
        "shaft": {"radius_m": float(downburst_core_radius_m), "rate_mmh": rate,
                  "rate_source": "stated" if stated else "storm_default",
                  "extinction_per_m": rain["extinction_per_m"]},
        "noise": {"seed": int(seed) & NOISE_SEED_MASK, "billow_m": BILLOW_M,
                  "octaves": NOISE_OCTAVES, "gain": NOISE_GAIN,
                  "lacunarity": NOISE_LACUNARITY, "erosion": EROSION},
        "glow_diffusion_m": GLOW_DIFFUSION_M,
        "basis": (f"tower {TOWER_RADII:g} downburst core radii (min {TOWER_RADIUS_MIN_M:g} m), "
                  f"base {base:g} m AGL (stated), top the latitude's tropopause (stated "
                  f"{TROPOPAUSE_EQUATOR_M:g}..{TROPOPAUSE_POLE_M:g} m), anvil "
                  f"{ANVIL_TOWERS:g} tower radii offset {ANVIL_OFFSET_FRACTION:g} anvil radii "
                  f"downwind of the stated wind"),
    }


# -- the density field (the shader's twin) ----------------------------------

def _smoothstep(e0: float, e1: float, x: float) -> float:
    if e0 == e1:
        return 0.0 if x < e0 else 1.0
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def lattice(ix: int, iy: int, iz: int, seed: int) -> float:
    """The lattice value in [0, 1]: pcg32(x + pcg32(y + pcg32(z + seed))) / 2^32,
    the integers taken as unsigned 32-bit (HLSL asuint)."""
    m = 0xFFFFFFFF
    h = pcg32((iz + seed) & m)
    h = pcg32((iy + h) & m)
    h = pcg32((ix + h) & m)
    return h / 4294967296.0


def value_noise(x: float, y: float, z: float, seed: int) -> float:
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = _fade(x - ix), _fade(y - iy), _fade(z - iz)

    def v(dx: int, dy: int, dz: int) -> float:
        return lattice(ix + dx, iy + dy, iz + dz, seed)

    x00 = v(0, 0, 0) + (v(1, 0, 0) - v(0, 0, 0)) * fx
    x10 = v(0, 1, 0) + (v(1, 1, 0) - v(0, 1, 0)) * fx
    x01 = v(0, 0, 1) + (v(1, 0, 1) - v(0, 0, 1)) * fx
    x11 = v(0, 1, 1) + (v(1, 1, 1) - v(0, 1, 1)) * fx
    y0 = x00 + (x10 - x00) * fy
    y1 = x01 + (x11 - x01) * fy
    return y0 + (y1 - y0) * fz


def fbm(x: float, y: float, z: float, seed: int) -> float:
    """NOISE_OCTAVES of value noise, normalised to [0, 1]."""
    total = 0.0
    amp = 1.0
    norm = 0.0
    freq = 1.0
    for _ in range(NOISE_OCTAVES):
        total += amp * value_noise(x * freq, y * freq, z * freq, seed)
        norm += amp
        amp *= NOISE_GAIN
        freq *= NOISE_LACUNARITY
    return total / norm


def shapes(cell: Dict[str, Any], e: float, n: float, u: float) -> Dict[str, float]:
    """The smooth shapes (0..1) before erosion: tower, anvil, shaft."""
    base = float(cell["base_m"])
    top = float(cell["top_m"])
    tower_r = float(cell["tower_radius_m"])
    r = math.hypot(e, n)
    # The tower, flaring upward, with an overshooting dome over the top.
    f = min(1.0, max(0.0, (u - base) / (top - base)))
    radius = tower_r * (1.0 - TOWER_FLARE * 0.5 + TOWER_FLARE * f)
    tower = (_smoothstep(radius, radius - EDGE_M * 2.0, r) * _smoothstep(base, base + EDGE_M, u)
             * _smoothstep(top + EDGE_M, top - EDGE_M, u))
    over = float(cell["overshoot_m"])
    if top - EDGE_M < u < top + over:
        h = (u - top) / over
        dome = OVERSHOOT_RADIUS_FRACTION * tower_r * math.sqrt(max(0.0, 1.0 - max(h, 0.0) ** 2))
        tower = max(tower, _smoothstep(dome, dome - EDGE_M, r))
    # The anvil: displaced downwind with height, thinning toward its edge.
    bottom = float(cell["anvil_bottom_m"])
    lift = min(1.0, max(0.0, (u - bottom) / (top - bottom)))
    off = cell["anvil_offset_enu_m"]
    ra = math.hypot(e - off[0] * lift, n - off[1] * lift)
    anvil_r = float(cell["anvil_radius_m"])
    floor = bottom + (top - bottom) * 0.6 * (ra / anvil_r) ** 2
    anvil = (_smoothstep(anvil_r, anvil_r - EDGE_M * 4.0, ra)
             * _smoothstep(floor, floor + EDGE_M, u)
             * _smoothstep(top + EDGE_M, top - EDGE_M, u))
    # The shaft: from the ground to the base, the downdraft core's radius.
    shaft_r = float(cell["shaft"]["radius_m"])
    shaft = (_smoothstep(shaft_r, shaft_r * 0.6, r)
             * _smoothstep(base + EDGE_M * 0.5, base - EDGE_M * 0.5, u))
    return {"tower": tower, "anvil": anvil, "shaft": shaft}


def extinction_at(cell: Dict[str, Any], e: float, n: float, u: float, t: float = 0.0) -> float:
    """The cell's extinction (1/m) at a point at run time t -- the shader's
    function, constant for constant."""
    s = shapes(cell, e, n, u)
    noise = cell["noise"]
    seed = int(noise["seed"])
    billow = float(noise["billow_m"])
    w = float(cell["updraft_mps"])
    drift_v = cell["anvil_drift_enu_mps"]
    rise = fbm(e / billow, n / billow, (u - w * t) / billow, seed)
    drift = fbm((e - drift_v[0] * t) / billow, (n - drift_v[1] * t) / billow, u / billow,
                seed + 1)
    curtain = fbm(e / billow, n / billow, u / (billow * SHAFT_NOISE_STRETCH), seed + 2)
    erosion = float(noise["erosion"])

    def eroded(shape: float, value: float) -> float:
        return min(1.0, max(0.0, (shape - (1.0 - value) * erosion) / (1.0 - erosion)))

    return (float(cell["extinction_core_per_m"]) * eroded(s["tower"], rise)
            + float(cell["extinction_anvil_per_m"]) * eroded(s["anvil"], drift)
            + float(cell["shaft"]["extinction_per_m"]) * s["shaft"] * (0.6 + 0.4 * curtain))


def transmittance(cell: Dict[str, Any], start: Sequence[float], end: Sequence[float],
                  steps: int = 400, t: float = 0.0) -> float:
    """exp(-int sigma ds) along a straight line, midpoint rule."""
    length = math.dist(start, end)
    h = length / steps
    tau = 0.0
    for i in range(steps):
        f = (i + 0.5) / steps
        p = [start[k] + f * (end[k] - start[k]) for k in range(3)]
        tau += extinction_at(cell, p[0], p[1], p[2], t) * h
    return math.exp(-tau)


def glow_illuminance_lux(intensity_cd: float, distance_m: float) -> float:
    """The lightning glow a cloud point receives: I / d^2 spread by diffusion,
    exp(-d / GLOW_DIFFUSION_M), d floored at EDGE_M (the shader's form)."""
    d = max(float(distance_m), EDGE_M)
    return float(intensity_cd) / (d * d) * math.exp(-d / GLOW_DIFFUSION_M)
