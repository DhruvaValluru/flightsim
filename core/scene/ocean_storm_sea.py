"""A float64 twin of M_FlightSimOceanBeauty's generation-5 storm sea (BEAUTY ONLY).

The three ocean shaders (assets/shaders/world/ocean_*.hlsl) share one
FOceanSurface block; this module re-derives the parts generation 5 added or
touched -- the storm ramp, the storm swell, the storm foam, the body colour and
the foam blend -- in numpy, with every constant READ FROM THE SHADER TEXT, so
the twin cannot drift from what the engine compiles. The texture-sampled wave
octaves (Waves) are not re-derived: their outputs (tilt, variance, crest) are
inputs here, as they are to every generation-5 term.

Two things are proved with it (tests/test_ocean_storm_sea.py):

* the calm sea is generation 4's. At WindSpeedMS <= STORM_WIND_LOW_MS the storm
  share is exactly 0 and every storm term is a product with it, so the
  generation-5 normal, base colour and foam equal generation 4's at the same
  inputs. Stated tolerance: 1e-9 in float64 (the HLSL evaluates the same
  products in float32, where 0 * finite is 0 exactly; the only non-zero path
  difference is none).
* the storm foam is footprint-filtered: at a fine footprint each layer's mean
  cover over a sea patch is its stated MEAN constant (the far pixel's value),
  and at a coarse footprint the per-pixel foam is that constant exactly, with
  no variance (no speckle), not zero (no vanishing).

Nothing here touches a label: the material draws only the beauty sea cap.
Every amount is UNCALIBRATED (no frame rendered yet).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
SHADER = REPO / "assets" / "shaders" / "world" / "ocean_colour.hlsl"

#: Generation 4's body colour and foam albedo (the reference the calm sea is
#: held to), as ocean_colour.hlsl stated them before generation 5.
GEN4_WATER_RGB = np.array([0.003, 0.010, 0.020])
GEN4_FOAM_ALBEDO = 0.6
#: The calm sea's tolerance: at and below STORM_WIND_LOW_MS (8 m/s) the
#: generation-5 outputs equal generation 4's within this, in float64.
CALM_TOLERANCE = 1e-9

_U32 = np.uint64(0xFFFFFFFF)


def shader_constants(path: Path = SHADER) -> Dict[str, object]:
    """Every `const float NAME = v;` and `const float3 NAME = float3(a, b, c);`
    in the shader, as floats / 3-arrays."""
    text = path.read_text(encoding="utf-8")
    out: Dict[str, object] = {}
    for name, value in re.findall(r"^const float (\w+) = ([-0-9.e]+);", text, re.M):
        out[name] = float(value)
    for name, a, b, c in re.findall(r"^const float3 (\w+) = float3\(([-0-9.e]+), ([-0-9.e]+), ([-0-9.e]+)\);",
                                    text, re.M):
        out[name] = np.array([float(a), float(b), float(c)])
    return out


# -- the shared block, in float64 -------------------------------------------------

def hash2(p: np.ndarray) -> np.ndarray:
    """FOceanSurface::Hash2: (uint2)(int2)floor(p), two multiplies, two mixes,
    in exact uint32 arithmetic."""
    q = np.floor(p).astype(np.int64).astype(np.uint64) & _U32
    h = ((q[..., 0] * np.uint64(1597334677)) & _U32) ^ ((q[..., 1] * np.uint64(3812015801)) & _U32)
    h = ((h ^ (h >> np.uint64(16))) * np.uint64(2246822519)) & _U32
    return (h ^ (h >> np.uint64(13))).astype(np.float64) / 4294967296.0


def value2(p: np.ndarray) -> np.ndarray:
    i = np.floor(p)
    f = p - i
    u = f * f * (3.0 - 2.0 * f)
    a = hash2(i)
    b = hash2(i + np.array([1.0, 0.0]))
    c = hash2(i + np.array([0.0, 1.0]))
    d = hash2(i + np.array([1.0, 1.0]))
    lerp = lambda x, y, t: x + (y - x) * t  # noqa: E731
    return lerp(lerp(a, b, u[..., 0]), lerp(c, d, u[..., 0]), u[..., 1])


def macro(pm: np.ndarray, metres: float) -> np.ndarray:
    q = pm / metres
    qx, qy = q[..., 0], q[..., 1]
    a = value2(q)
    b = value2(np.stack([0.8 * qx - 0.6 * qy, 0.6 * qx + 0.8 * qy], -1) * 2.03 + np.array([17.1, 3.7]))
    c = value2(np.stack([0.28 * qx + 0.96 * qy, -0.96 * qx + 0.28 * qy], -1) * 4.11 + np.array([5.3, 29.9]))
    return (a + 0.5 * b + 0.25 * c) / 1.75


def smoothstep(e0: float, e1: float, x) -> np.ndarray:
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def saturate(x) -> np.ndarray:
    return np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)


def slope_variance(wind_ms: float) -> float:
    """Cox & Munk (1954), clean sea."""
    return 0.003 + 0.00512 * max(wind_ms, 0.0)


def storm_factor(wind_ms, k: Dict[str, object]) -> np.ndarray:
    return smoothstep(k["STORM_WIND_LOW_MS"], k["STORM_WIND_HIGH_MS"], wind_ms)


def _turned(wind_dir: np.ndarray, turn: float) -> np.ndarray:
    s, c = np.sin(turn), np.cos(turn)
    return np.array([c * wind_dir[0] - s * wind_dir[1], s * wind_dir[0] + c * wind_dir[1]])


def swell(pm: np.ndarray, wind_dir: np.ndarray, time_s: float, footprint_m) -> np.ndarray:
    """Generation 3's Swell (unchanged by generation 5): the calm swell's tilt."""
    lengths, slopes, turns = (310.0, 190.0, 120.0), (0.022, 0.018, 0.014), (0.0, 0.45, -0.35)
    warp = 12.566 * macro(pm, 1800.0)
    tilt = np.zeros(pm.shape[:-1] + (2,))
    for i in range(3):
        seen = 1.0 - smoothstep(lengths[i] / 10.0, lengths[i] / 4.0, footprint_m)
        d = _turned(wind_dir, turns[i])
        k = 6.2831853 / lengths[i]
        phase = k * (pm @ d) - np.sqrt(9.81 * k) * time_s + warp * (0.6 + 0.3 * i)
        envelope = 0.4 + 1.0 * macro(pm + np.array([731.0 * i, 293.0 * i]), 1200.0)
        tilt -= (seen * envelope * slopes[i] * np.cos(phase))[..., None] * d
    return tilt


def storm_swell(pm: np.ndarray, wind_dir: np.ndarray, time_s: float, footprint_m, storm,
                k: Dict[str, object]) -> Tuple[np.ndarray, np.ndarray]:
    """Generation 5's StormSwell: (tilt, crestKey)."""
    lengths, slopes, turns = (420.0, 260.0), (0.08, 0.06), (0.18, -0.28)
    warp = 9.42 * macro(pm + np.array([451.0, -173.0]), 2600.0)
    tilt = np.zeros(pm.shape[:-1] + (2,))
    crest = np.zeros(pm.shape[:-1])
    storm = np.asarray(storm, dtype=np.float64)
    for i in range(2):
        seen = 1.0 - smoothstep(lengths[i] / 10.0, lengths[i] / 4.0, footprint_m)
        d = _turned(wind_dir, turns[i])
        kk = 6.2831853 / lengths[i]
        phase = kk * (pm @ d) - np.sqrt(9.81 * kk) * time_s + warp * (0.7 + 0.4 * i)
        envelope = 0.5 + 0.8 * macro(pm + np.array([-389.0 * (i + 1), 617.0 * (i + 1)]), 1500.0)
        tilt -= (seen * storm * envelope * slopes[i] * np.cos(phase))[..., None] * d
        sp = saturate(np.sin(phase))
        crest = crest + 0.5 * seen * envelope * sp * sp * sp
    return tilt, saturate(crest)


def storm_foam_layers(pm: np.ndarray, wind_dir: np.ndarray, footprint_m, dist_m, time_s: float, wind_ms: float,
                      crest_key, k: Dict[str, object]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """StormFoam's two layers before the blend: (fine, fineSeen, patch, patchSeen)."""
    along = pm @ wind_dir - k["FOAM_DRIFT_SHARE"] * max(wind_ms, 0.0) * time_s
    across = pm @ np.array([-wind_dir[1], wind_dir[0]])
    fine = macro(np.stack([along / k["STREAK_ALONG_M"], across / k["STREAK_ACROSS_M"]], -1), 1.0)
    fine = smoothstep(k["STREAK_THRESHOLD"], k["STREAK_THRESHOLD"] + 0.08, fine)
    fine_seen = ((1.0 - smoothstep(k["STREAK_ACROSS_M"] / 4.0, k["STREAK_ACROSS_M"], footprint_m))
                 * (1.0 - smoothstep(k["STREAK_FADE_START_M"], k["STREAK_FADE_END_M"], dist_m)))
    patch = macro(np.stack([along / k["PATCH_ALONG_M"] + 7.3, across / k["PATCH_ACROSS_M"] + 2.1], -1), 1.0)
    patch = smoothstep(k["PATCH_THRESHOLD"], k["PATCH_THRESHOLD"] + 0.1, patch) * (0.6 + 0.6 * np.asarray(crest_key))
    patch_seen = ((1.0 - smoothstep(k["PATCH_ACROSS_M"] / 4.0, k["PATCH_ACROSS_M"], footprint_m))
                  * (1.0 - smoothstep(k["PATCH_FADE_START_M"], k["PATCH_FADE_END_M"], dist_m)))
    return fine, fine_seen, patch, patch_seen


def storm_foam(pm, wind_dir, footprint_m, dist_m, time_s, wind_ms, crest_key, storm, k) -> np.ndarray:
    fine, fine_seen, patch, patch_seen = storm_foam_layers(pm, wind_dir, footprint_m, dist_m, time_s, wind_ms,
                                                           crest_key, k)
    cover = (k["STREAK_SHARE"] * (k["STREAK_MEAN"] + (fine - k["STREAK_MEAN"]) * fine_seen)
             + k["PATCH_SHARE"] * (k["PATCH_MEAN"] + (patch - k["PATCH_MEAN"]) * patch_seen))
    return np.asarray(storm) * saturate(cover)


# -- the two generations' tails --------------------------------------------------------

def up(pm3: np.ndarray) -> np.ndarray:
    v = pm3 + np.array([0.0, 0.0, 6371008.8])
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _normal(pm3, tilt):
    n = up(pm3) + np.concatenate([tilt, np.zeros(tilt.shape[:-1] + (1,))], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def _crest_foam(wind_ms: float, crest) -> np.ndarray:
    cover = float(np.clip(3.84e-6 * max(wind_ms, 0.0) ** 3.41, 1e-5, 0.2))
    edge = np.sqrt(-np.log(cover))
    return smoothstep(edge, edge + 0.5, crest)


def shade_gen4(pm3, wind_ms, wind_dir, time_s, footprint_m, wave_tilt, crest):
    """Generation 4's normal, base colour and foam (the reference)."""
    pm = pm3[..., :2]
    tilt = wave_tilt + swell(pm, wind_dir, time_s, footprint_m)
    foam = _crest_foam(wind_ms, crest)
    body = GEN4_WATER_RGB * (0.9 + 0.2 * macro(pm, 3000.0))[..., None]
    base = body + (GEN4_FOAM_ALBEDO - body) * foam[..., None]
    return _normal(pm3, tilt), base, foam


def shade_gen5(pm3, wind_ms, wind_dir, time_s, footprint_m, dist_m, wave_tilt, crest, k=None):
    """Generation 5's normal, base colour and foam, as the three shaders' tails."""
    k = k or shader_constants()
    pm = pm3[..., :2]
    storm = storm_factor(wind_ms, k)
    tilt = wave_tilt + swell(pm, wind_dir, time_s, footprint_m)
    storm_tilt, crest_key = storm_swell(pm, wind_dir, time_s, footprint_m, storm, k)
    tilt = tilt + storm_tilt
    crest_foam = _crest_foam(wind_ms, crest)
    foam = saturate(crest_foam * (1.0 - storm)
                    + storm_foam(pm, wind_dir, footprint_m, dist_m, time_s, wind_ms, crest_key, storm, k))
    body = k["WATER_RGB"] * (0.9 + 0.2 * macro(pm, 3000.0))[..., None]
    storm_body = k["STORM_RGB"] * (0.85 + 0.3 * macro(pm + np.array([911.0, -457.0]), 1500.0))[..., None]
    body = body + (storm_body - body) * np.asarray(storm)
    base = body + (k["FOAM_ALBEDO"] - body) * foam[..., None]
    return _normal(pm3, tilt), base, foam


def downwind_engine_xy(wind_from_deg: float) -> Tuple[float, float]:
    """FlightSimGoogleTiles.cpp ApplyBeautyGround's conversion: the bearing the
    wind blows FROM to the downwind unit vector in engine X east / Y north."""
    r = np.radians(wind_from_deg)
    return float(-np.sin(r)), float(-np.cos(r))


def card_wind_ms(wind_speed_kt: float) -> float:
    """The commandlet's knots to m/s (1852 m per nautical mile, 3600 s)."""
    return wind_speed_kt * (1852.0 / 3600.0)


# -- generation 6: the hyperreal sea (HyperSea = 1) --------------------------------

G = 9.81


def pm_peak_wavelength_m(wind_ms: float) -> float:
    """Pierson-Moskowitz (1964) peak: wp = 0.877 g / U, deep water L = 2 pi g / wp^2."""
    wp = 0.877 * G / max(wind_ms, 1.0)
    return 2.0 * np.pi * G / wp ** 2


def pm_component_steepness(ratios=(1.0, 0.7, 0.5), wind_ms: float = 7.0) -> np.ndarray:
    """ka of wind-sea components at ratios x Lp: amplitudes ~ sqrt(S_PM(w)), scaled
    so 4 sqrt(sum a^2 / 2) = Hs = 0.21 U^2 / g (fully developed)."""
    lp = pm_peak_wavelength_m(wind_ms)
    wp = 2.0 * np.pi / np.sqrt(2.0 * np.pi * lp / G)
    r = np.asarray(ratios, dtype=float)
    w = wp / np.sqrt(r)
    spec = w ** -5 * np.exp(-1.25 * (wp / w) ** 4)
    hs = 0.21 * max(wind_ms, 1.0) ** 2 / G
    a = np.sqrt(spec)
    a *= np.sqrt(2.0 * (hs / 4.0) ** 2 / np.sum(a ** 2))
    return 2.0 * np.pi / (lp * r) * a


def hyper_waves(pm: np.ndarray, wind_dir: np.ndarray, time_s: float, footprint_m, wind_ms: float, k=None):
    """FOceanSurface::HyperWaves in float64: (tilt, height, resolved variance)."""
    k = shader_constants() if k is None else k
    peak = k["HYPER_PEAK_PER_U2"] * max(wind_ms, 1.0) ** 2
    lengths = [k["HYPER_SWELL_M"], peak, 0.7 * peak, 0.5 * peak]
    kas = [k["HYPER_SWELL_KA"], k["HYPER_SEA_KA_1"], k["HYPER_SEA_KA_2"], k["HYPER_SEA_KA_3"]]
    turns = [0.6, 0.0, 0.4, -0.35]
    q = k["HYPER_GERSTNER_Q"]
    warp = 12.566 * value2(pm / 2200.0 + np.array([-0.0959, 0.2668]))
    group = value2(pm / 1400.0 + np.array([0.4379, -0.2479]))
    groups = (group, 1.0 - group)
    slope = np.zeros_like(pm)
    lift = np.zeros(pm.shape[0])
    h = np.zeros(pm.shape[0])
    hs = np.zeros(pm.shape[0])
    var = np.zeros(pm.shape[0])
    for i in range(4):
        seen = 1.0 - smoothstep(lengths[i] / 10.0, lengths[i] / 4.0, footprint_m)
        d = _turned(wind_dir, turns[i])
        kk = 2.0 * np.pi / lengths[i]
        phase = kk * (pm @ d) - np.sqrt(G * kk) * time_s + warp * (0.5 + 0.25 * i)
        env = 0.5 + groups[i & 1]
        ka = seen * env * kas[i]
        slope -= (ka * np.cos(phase))[:, None] * d[None, :]
        lift += q * ka * np.sin(phase)
        h += ka / kk * np.sin(phase)
        hs += seen * env * kas[i] / kk
        var += 0.5 * ka * ka
    return slope / np.maximum(1.0 - lift, 0.3)[:, None], h / np.maximum(hs, 1e-4), var


def cox_munk_upwind_share(wind_ms: float, k=None) -> float:
    """Cox & Munk (1954) clean surface: s_u^2 / (s_u^2 + s_c^2)."""
    k = shader_constants() if k is None else k
    u = k["CM_UPWIND_PER_MS"] * max(wind_ms, 0.0)
    return u / (k["CM_CROSS_BASE"] + (k["CM_UPWIND_PER_MS"] + k["CM_CROSS_PER_MS"]) * max(wind_ms, 0.0))


def whitecap_onset(wind_ms, k=None) -> np.ndarray:
    k = shader_constants() if k is None else k
    return smoothstep(k["HYPER_WHITECAP_ONSET_MS"], k["HYPER_WHITECAP_FULL_MS"], wind_ms)
