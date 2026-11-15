#!/usr/bin/env python3
"""atmosphere_clouds.volumetric_cloud_types.storm: the offline bake (Mac).

Bakes what the Intel integrated GPU should not compute per frame:

* ``storm_cloud_types.json``  three storm cloud types (cumulonimbus core,
  nimbostratus deck, scud), their extinction, phase and multiple-scattering
  numbers, the tiers, the gate's expected values and the shared parameters.
* ``storm_underdeck_256x64.hdr``  tier 0: the under-deck radiance of the cell
  as an upper-hemisphere panorama (two-stream diffuse transmission of the
  column above each point of the base, then a Koschmieder veil whose
  airlight is lit by the column above each point of the sight line). Normalised so
  its cosine-weighted integral is pi: SkyLight intensity x pi = horizontal lux,
  the same convention as lighting_exposure.physical_light_units.storm.
* ``storm_weather_128.tga``  tiers 1-3: R = column optical depth / max,
  G = cloud-top fraction, B = rain-shaft mask. 32 km square, 250 m a texel.
* ``storm_noise_{32,64}_atlas.tga``  tiers 1-3: tileable Worley erosion noise
  as 8-wide slice atlases for a volume texture.

VISUAL-ONLY: the cell's shape is procedural (an integer-hash noise, no
weather data). The radiometry is closed-form and named in PROVENANCE.json.
UNMEASURED: nothing here was rendered. Needs numpy (.venv). Deterministic.

    .venv/bin/python swarm/lanes/atmosphere_clouds/volumetric_cloud_types/storm/generate.py
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np

LANE = Path(__file__).resolve().parent
BAKED = LANE / "baked"
ITEM = "atmosphere_clouds.volumetric_cloud_types.storm"

# --- held to the scenario's other lanes (lighting_exposure...storm/baked/storm_plu.json)
CLEAR_SKY_HORIZONTAL_LUX = 50193.6   # SkyAtmosphere reference: sun 28 deg + sky, no cloud
DECK_FRACTION = 0.25                 # the look's deck illuminance fraction
SKYLIGHT_CD_M2 = 3395.1              # dome share of the under-deck illuminance / pi
DIRECTIONAL_GROUND_HORIZONTAL_LUX = 1882.3
EXPOSURE_EV100 = 12.5
SUN_ELEVATION_DEG = 28.0
VISIBILITY_M = 3000.0
GROUND_ALBEDO_WET = 0.085
SKY_COLOUR_TEMPERATURE_K = 7000.0

# --- this lane's own choices (visual-only within the cited literature ranges)
WATER_DENSITY_KG_M3 = 1000.0
DOMAIN_M = 32000.0
MAP_N = 128
CLOUD_BASE_M = 600.0
DECK_TOP_M = 3000.0
CELL_TOP_M = 11000.0
CELL_RADIUS_M = 5000.0
OBSERVER_ALT_M = 300.0
OBSERVER_TO_CORE_M = 6000.0
PANO_W, PANO_H = 256, 64
PANO_MAX_RANGE_M = 14000.0
AIRLIGHT_SAMPLES = 32
DROPLET_DIAMETER_UM = 20.0
#: name: (base m, top m, liquid water content g/m3, effective radius um)
CLOUD_TYPES: Dict[str, Tuple[float, float, float, float]] = {
    "cumulonimbus_core": (CLOUD_BASE_M, CELL_TOP_M, 1.0, 10.0),
    "nimbostratus_deck": (CLOUD_BASE_M, DECK_TOP_M, 0.4, 9.0),
    "scud_fractus": (300.0, 500.0, 0.1, 5.0),
}
#: Wrenninge 2013 octaves: L = sum_i b^i * Lss(a^i * sigma, c^i * g)
MS_A, MS_B, MS_C = 0.5, 0.5, 0.5


# ------------------------------------------------------------------ radiometry
def extinction_per_m(lwc_g_m3: float, r_eff_um: float) -> float:
    """Geometric-optics droplet extinction, Q_ext = 2: 3 LWC / (2 rho r_eff)."""
    return 3.0 * (lwc_g_m3 * 1e-3) / (2.0 * WATER_DENSITY_KG_M3 * r_eff_um * 1e-6)


def two_stream_transmittance(tau, g: float):
    """Diffuse transmittance of a conservative slab: 2 / (2 + (1 - g) tau)."""
    return 2.0 / (2.0 + (1.0 - g) * np.asarray(tau, dtype=np.float64))


def mie_fit(d_um: float) -> Dict[str, float]:
    """HG + Draine blend parameters, Jendersie & d'Eon 2023, 5 <= d <= 50 um."""
    if not 5.0 <= d_um <= 50.0:
        raise ValueError("fit is for droplet diameters of 5 to 50 um")
    return {
        "g_hg": math.exp(-0.0990567 / (d_um - 1.67154)),
        "g_d": math.exp(-2.20679 / (d_um + 3.91029) - 0.428934),
        "alpha": math.exp(3.62489 - 8.29288 / (d_um + 5.52825)),
        "w_d": math.exp(-0.599085 / (d_um - 0.641583) - 0.665888),
    }


def phase_hg(g: float, mu):
    mu = np.asarray(mu, dtype=np.float64)
    return (1.0 - g * g) / (4.0 * math.pi * (1.0 + g * g - 2.0 * g * mu) ** 1.5)


def phase_draine(g: float, alpha: float, mu):
    mu = np.asarray(mu, dtype=np.float64)
    return phase_hg(g, mu) * (1.0 + alpha * mu * mu) / (1.0 + alpha * (1.0 + 2.0 * g * g) / 3.0)


def phase_mie(fit: Dict[str, float], mu):
    return (1.0 - fit["w_d"]) * phase_hg(fit["g_hg"], mu) + fit["w_d"] * phase_draine(fit["g_d"], fit["alpha"], mu)


def draine_mean_cosine(g: float, alpha: float) -> float:
    return g * (1.0 + alpha * (3.0 + 2.0 * g * g) / 5.0) / (1.0 + alpha * (1.0 + 2.0 * g * g) / 3.0)


def mie_mean_cosine(fit: Dict[str, float]) -> float:
    return (1.0 - fit["w_d"]) * fit["g_hg"] + fit["w_d"] * draine_mean_cosine(fit["g_d"], fit["alpha"])


def octave_transmission(tau: float, octaves: int) -> float:
    """Unscattered-light proxy of the octave sum: sum_i b^i exp(-a^i tau)."""
    return sum(MS_B ** i * math.exp(-(MS_A ** i) * tau) for i in range(octaves))


# ----------------------------------------------------------------------- noise
def _hash(*coords, seed: int):
    h = np.full(np.broadcast(*coords).shape, (seed * 2246822519) & 0xFFFFFFFF, dtype=np.uint64)
    for c, k in zip(coords, (374761393, 668265263, 3266489917)):
        h = (h + np.asarray(c, dtype=np.uint64) * np.uint64(k)) & np.uint64(0xFFFFFFFF)
        h = ((h ^ (h >> np.uint64(13))) * np.uint64(1274126177)) & np.uint64(0xFFFFFFFF)
    h ^= h >> np.uint64(16)
    return h.astype(np.float64) / 4294967296.0


def value_noise(n: int, cells: int, seed: int):
    u = np.arange(n, dtype=np.float64) * cells / n
    i0 = np.floor(u).astype(np.int64)
    f = u - i0
    s = f * f * (3.0 - 2.0 * f)
    a, b = i0 % cells, (i0 + 1) % cells
    lat = lambda i, j: _hash(i[:, None], j[None, :], seed=seed)
    sx, sy = s[:, None], s[None, :]
    return (lat(a, a) * (1 - sx) * (1 - sy) + lat(b, a) * sx * (1 - sy)
            + lat(a, b) * (1 - sx) * sy + lat(b, b) * sx * sy)


def fbm(n: int, seed: int, octaves=(4, 8, 16, 32)):
    out, norm = np.zeros((n, n)), 0.0
    for k, cells in enumerate(octaves):
        out += 0.5 ** k * value_noise(n, cells, seed + k)
        norm += 0.5 ** k
    return out / norm


def worley(n: int, cells: int, seed: int):
    """Tileable inverted Worley noise in [0, 1], n^3."""
    u = np.arange(n, dtype=np.float64) * cells / n
    p = np.stack(np.meshgrid(u, u, u, indexing="ij"))
    base = np.floor(p).astype(np.int64)
    best = np.full((n, n, n), 9.0)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                c = base + np.array([dx, dy, dz], dtype=np.int64)[:, None, None, None]
                w = c % cells
                d2 = np.zeros((n, n, n))
                for axis in range(3):
                    feat = c[axis] + _hash(w[0], w[1], w[2], seed=seed + axis)
                    d2 += (p[axis] - feat) ** 2
                best = np.minimum(best, d2)
    return 1.0 - np.minimum(np.sqrt(best), 1.0)


def erosion_noise(n: int):
    return 0.625 * worley(n, 4, 11) + 0.375 * worley(n, 8, 23)


# ------------------------------------------------------------------- the cell
def storm_columns() -> Dict[str, Any]:
    """Column optical depth, top height and rain mask of the 32 km domain."""
    n = MAP_N
    x = (np.arange(n) + 0.5) / n * DOMAIN_M - DOMAIN_M / 2.0
    r2 = x[:, None] ** 2 + x[None, :] ** 2
    core = np.exp(-r2 / (2.0 * CELL_RADIUS_M ** 2)) * (0.7 + 0.6 * fbm(n, 101))
    core = np.clip(core, 0.0, 1.0)
    deck = 0.35 + 1.3 * fbm(n, 202)
    top_m = DECK_TOP_M + (CELL_TOP_M - DECK_TOP_M) * np.sqrt(core)
    s_cb = extinction_per_m(*CLOUD_TYPES["cumulonimbus_core"][2:])
    s_ns = extinction_per_m(*CLOUD_TYPES["nimbostratus_deck"][2:])
    tau_phys = s_ns * (DECK_TOP_M - CLOUD_BASE_M) * deck + s_cb * (top_m - CLOUD_BASE_M) * core
    for _ in range(2):  # horizontal diffusion of light inside the slab, ~1 texel
        tau_phys = (2 * tau_phys + np.roll(tau_phys, 1, 0) + np.roll(tau_phys, -1, 0)) / 4
        tau_phys = (2 * tau_phys + np.roll(tau_phys, 1, 1) + np.roll(tau_phys, -1, 1)) / 4
    t = np.clip((core - 0.3) / 0.4, 0.0, 1.0)
    return {"tau_phys": tau_phys, "top_m": top_m, "rain": t * t * (3 - 2 * t), "core": core}


def calibrate_extinction_scale(tau_phys, g: float, target: float = DECK_FRACTION) -> float:
    """k such that the area-mean two-stream transmittance of k * tau is target."""
    lo, hi = 1e-6, 1e3
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if float(two_stream_transmittance(mid * tau_phys, g).mean()) > target:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def _bilinear_periodic(img, fx, fy):
    n = img.shape[0]
    x0, y0 = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
    tx, ty = fx - x0, fy - y0
    g = lambda a, b: img[a % n, b % n]
    return (g(x0, y0) * (1 - tx) * (1 - ty) + g(x0 + 1, y0) * tx * (1 - ty)
            + g(x0, y0 + 1) * (1 - tx) * ty + g(x0 + 1, y0 + 1) * tx * ty)


def pano_axes():
    el = (PANO_H - 0.5 - np.arange(PANO_H)) / PANO_H * (math.pi / 2.0)  # row 0 = zenith
    az = (np.arange(PANO_W) + 0.5) / PANO_W * 2.0 * math.pi             # 0 = toward the core
    return el, az


def cosine_mean(pano) -> float:
    """Cosine-weighted hemisphere mean: integral(L cos) dOmega / pi."""
    el, _ = pano_axes()
    w = np.sin(el) * np.cos(el)
    return float((pano.mean(axis=1) * w).sum() / w.sum())


def underdeck_panorama(trans) -> Dict[str, Any]:
    """Relative luminance of the cloud base from below, veiled, cosine mean 1."""
    el, az = pano_axes()
    dh = CLOUD_BASE_M - OBSERVER_ALT_M
    horiz = np.minimum(dh / np.tan(el), PANO_MAX_RANGE_M)[:, None]
    slant = (dh / np.sin(el))[:, None]
    texel = DOMAIN_M / MAP_N
    ox = (-OBSERVER_TO_CORE_M + DOMAIN_M / 2.0) / texel - 0.5
    oy = (DOMAIN_M / 2.0) / texel - 0.5
    base = _bilinear_periodic(trans, ox + horiz * np.cos(az)[None, :] / texel,
                              oy + horiz * np.sin(az)[None, :] / texel)
    far = (dh / np.tan(el) > PANO_MAX_RANGE_M)[:, None]
    base = np.where(far, float(trans.mean()), base)
    sigma = 3.912 / VISIBILITY_M                      # Koschmieder, 2 % contrast
    reach = np.minimum(slant, PANO_MAX_RANGE_M / np.cos(el)[:, None])
    keep = np.exp(-sigma * reach)
    # Airlight: each point of the sight line is lit by the column above it, so
    # the veil toward the core is darker. Equal-weight samples of
    # integral(sigma exp(-sigma s) T(s)) ds along the path below the base.
    u = (np.arange(AIRLIGHT_SAMPLES) + 0.5) / AIRLIGHT_SAMPLES
    s = -np.log(1.0 - u[None, None, :] * (1.0 - keep[:, :, None])) / sigma
    hs = s * np.cos(el)[:, None, None] / texel
    lit = _bilinear_periodic(trans, ox + hs * np.cos(az)[None, :, None], oy + hs * np.sin(az)[None, :, None])
    airlight = cosine_mean(base)
    pano = base * keep + lit.mean(axis=2) * (1.0 - keep)
    return {"rel": pano / cosine_mean(pano), "unveiled_cosine_mean_transmittance": airlight,
            "haze_extinction_per_m": sigma}


# -------------------------------------------------------------------- writers
def rgbe_bytes(grey) -> bytes:
    h, w = grey.shape
    m, e = np.frexp(np.maximum(grey, 0.0))
    mant = np.clip(np.floor(m * 256.0), 0, 255).astype(np.uint8)
    expo = np.where(grey > 1e-32, e + 128, 0).astype(np.uint8)
    mant = np.where(grey > 1e-32, mant, 0).astype(np.uint8)
    px = np.stack([mant, mant, mant, expo], axis=-1)
    head = f"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y {h} +X {w}\n".encode("ascii")
    return head + px.tobytes()


def tga_bytes(img) -> bytes:
    """Uncompressed TGA, top-left origin; (h, w) grey or (h, w, 3) RGB uint8."""
    h, w = img.shape[:2]
    grey = img.ndim == 2
    head = struct.pack("<BBBHHBHHHHBB", 0, 0, 3 if grey else 2, 0, 0, 0, 0, 0, w, h, 8 if grey else 24, 0x20)
    return head + (img if grey else img[:, :, ::-1]).astype(np.uint8).tobytes()


def atlas(vol, cols: int = 8):
    n = vol.shape[0]
    rows = n // cols
    q = np.clip(np.rint(vol * 255.0), 0, 255).astype(np.uint8)
    return q.reshape(rows, cols, n, n).transpose(0, 2, 1, 3).reshape(rows * n, cols * n)


def _q8(a):
    return np.clip(np.rint(np.asarray(a) * 255.0), 0, 255).astype(np.uint8)


def _r(v: float, nd: int = 4) -> float:
    return round(float(v), nd)


# ----------------------------------------------------------------------- build
def build() -> Dict[str, bytes]:
    """Every baked file, name -> bytes."""
    fit = mie_fit(DROPLET_DIAMETER_UM)
    g = mie_mean_cosine(fit)
    cols = storm_columns()
    k = calibrate_extinction_scale(cols["tau_phys"], g)
    tau = k * cols["tau_phys"]
    trans = two_stream_transmittance(tau, g)
    pano = underdeck_panorama(trans)
    rel = pano["rel"]
    el, _ = pano_axes()
    seen = rel[np.degrees(el) >= 5.0]
    band = rel[(np.degrees(el) >= 5.0) & (np.degrees(el) <= 40.0)]
    p05, p50, p95 = (float(np.percentile(seen, q)) for q in (5, 50, 95))
    band_median = float(np.median(band))

    files: Dict[str, bytes] = {
        "storm_underdeck_256x64.hdr": rgbe_bytes(rel),
        "storm_weather_128.tga": tga_bytes(np.stack(
            [_q8(tau / tau.max()), _q8((cols["top_m"] - CLOUD_BASE_M) / (CELL_TOP_M - CLOUD_BASE_M)),
             _q8(cols["rain"])], axis=-1)),
        "storm_noise_64_atlas.tga": tga_bytes(atlas(erosion_noise(64))),
        "storm_noise_32_atlas.tga": tga_bytes(atlas(erosion_noise(32))),
    }

    dome_lux = SKYLIGHT_CD_M2 * math.pi
    types = {}
    for name, (base, top, lwc, r_eff) in CLOUD_TYPES.items():
        s = extinction_per_m(lwc, r_eff)
        types[name] = {
            "base_m": base, "top_m": top, "liquid_water_content_g_m3": lwc, "effective_radius_um": r_eff,
            "extinction_per_m_physical": _r(s, 5), "extinction_per_m_render": _r(s * k, 5),
            "optical_depth_physical": _r(s * (top - base), 1), "optical_depth_render": _r(s * k * (top - base), 1),
            "basis": "sigma = 3 LWC / (2 rho r_eff); LWC and r_eff are visual-only picks inside the literature range",
        }
    plan: Dict[str, Any] = {
        "item": ITEM, "scenario": "storm",
        "status": "UNMEASURED: baked on the Mac from named formulae; no frame was rendered",
        "visual_only": "the cell's shape (procedural noise) and every LWC / r_eff / octave pick",
        "cloud_types": types,
        "extinction_scale": {
            "value": _r(k, 5),
            "basis": "area-mean two-stream transmittance of the domain = the look's deck fraction 0.25; the physical "
                     "types alone would transmit less, the scale is the visual-only reconciliation with the exposure lane",
            "area_mean_transmittance": _r(trans.mean(), 5),
            "core_transmittance_min": _r(trans.min(), 5), "edge_transmittance_max": _r(trans.max(), 5),
            "column_optical_depth_render_max": _r(tau.max(), 1),
            "column_optical_depth_render_mean": _r(tau.mean(), 1),
        },
        "phase": {
            "droplet_diameter_um": DROPLET_DIAMETER_UM, **{n: _r(v, 6) for n, v in fit.items()},
            "mean_cosine": _r(g, 5),
            "ue_two_lobe": {"PhaseG": _r(fit["g_hg"], 4), "PhaseG2": _r(draine_mean_cosine(fit["g_d"], fit["alpha"]), 4),
                            "PhaseBlend": _r(fit["w_d"], 4),
                            "note": "the Draine lobe replaced by an HG of the same mean cosine (the engine's "
                                    "advanced volumetric output takes two HG lobes)"},
            "basis": "Jendersie & d'Eon 2023 fit constants as transcribed; NOT re-read against the PDF in this "
                     "session; checked here only by normalisation and by the mean cosine",
        },
        "multiple_scattering": {
            "a_extinction": MS_A, "b_contribution": MS_B, "c_eccentricity": MS_C,
            "ue": {"MultiScatteringContribution": MS_B, "MultiScatteringOcclusion": MS_A,
                   "MultiScatteringEccentricity": MS_C},
            "octave_transmission_at_tau_20": {str(n): float(f"{octave_transmission(20.0, n):.4g}") for n in (1, 2, 3)},
            "basis": "Wrenninge 2013 octave sum; the three 0.5s are the paper's customary starting point, visual-only",
        },
        "radiometry": {
            "skyatmosphere_reference_clear_horizontal_lux": CLEAR_SKY_HORIZONTAL_LUX,
            "under_deck_horizontal_lux": _r(CLEAR_SKY_HORIZONTAL_LUX * DECK_FRACTION, 1),
            "dome_horizontal_lux": _r(dome_lux, 1),
            "directional_patch_horizontal_lux": DIRECTIONAL_GROUND_HORIZONTAL_LUX,
            "budget_residual_fraction": _r((dome_lux + DIRECTIONAL_GROUND_HORIZONTAL_LUX)
                                           / (CLEAR_SKY_HORIZONTAL_LUX * DECK_FRACTION) - 1.0, 5),
            "lambert_ceiling_cd_m2": _r(CLEAR_SKY_HORIZONTAL_LUX / math.pi, 1),
            "panorama_max_cd_m2": _r(rel.max() * SKYLIGHT_CD_M2, 1),
            "panorama_min_cd_m2": _r(rel.min() * SKYLIGHT_CD_M2, 1),
            "panorama_zenith_cd_m2": _r(rel[0].mean() * SKYLIGHT_CD_M2, 1),
            "panorama_horizon_cd_m2": _r(rel[-1].mean() * SKYLIGHT_CD_M2, 1),
            "observer_unveiled_cosine_mean_transmittance": _r(pano["unveiled_cosine_mean_transmittance"], 5),
            "note": "the panorama is relative (cosine mean 1) and takes its absolute level from the exposure "
                    "lane's SkyLight 3395.1 cd/m2; the observer sits 6 km from the core, where the deck above "
                    "transmits the figure on the line above, against the domain's 0.25",
        },
        "panorama": {
            "file": "storm_underdeck_256x64.hdr", "width": PANO_W, "height": PANO_H,
            "encoding": "Radiance RGBE, flat scanlines, grey",
            "layout": "upper hemisphere only; row 0 = zenith, last row = horizon; column 0 = azimuth toward the "
                      "cell core, azimuth increasing counter-clockwise seen from above (x toward the core, y left)",
            "normalisation": "cosine-weighted hemisphere mean = 1",
            "observer_altitude_m": OBSERVER_ALT_M, "observer_to_core_m": OBSERVER_TO_CORE_M,
            "valid_for": "an observer below the cloud base; at or above 600 m tier 0 draws the in-cloud veil instead",
        },
        "weather_map": {"file": "storm_weather_128.tga", "size": MAP_N, "domain_m": DOMAIN_M,
                        "R": "column optical depth (render) / column_optical_depth_render_max",
                        "G": "(cloud top - base) / (11000 - 600)", "B": "rain-shaft mask", "srgb": False},
        "noise": {"storm_noise_64_atlas.tga": {"volume": 64, "tiles": "8 x 8"},
                  "storm_noise_32_atlas.tga": {"volume": 32, "tiles": "8 x 4"},
                  "kind": "inverted Worley, 0.625 x 4 cells + 0.375 x 8 cells, tileable", "srgb": False},
        "gate": {
            "expected_sky_over_ground_stops": _r(math.log2(band_median / GROUND_ALBEDO_WET), 3),
            "expected_sky_contrast_stops": _r(math.log2(p95 / p05), 3),
            "black_floor_relative_to_sky_median": _r(0.5 * float(seen.min()) / p50, 4),
            "sky_band_median_relative": _r(band_median, 4),
            "tolerance_stops": 1.0, "max_black_fraction": 0.02,
            "basis": "Lambert ground under the dome: L_ground = albedo x cosine-mean sky luminance; sky taken as "
                     "the panorama's median over elevations 5 to 40 deg; display-referred on the frame, so the "
                     "tone curve's compression is inside the 1-stop tolerance or it is not (UNMEASURED)",
        },
        "tiers": [
            {"tier": 0, "est_vram_mb": 0.2, "volumetric_cloud_component": False,
             "summary": "no ray march: the baked under-deck panorama on an unlit sky dome (256x64 RGBA16F) times "
                        "SkyLight 3395.1 cd/m2 and the 7000 K tint; exponential height fog as the in-cloud veil"},
            {"tier": 1, "est_vram_mb": 8.0, "volumetric_cloud_component": True, "noise": 32, "ms_octaves": 1,
             "view_sample_count_scale": 0.25, "shadow_view_sample_count_scale": 0.0, "tracing_max_km": 15.0,
             "cvars": {"r.VolumetricRenderTarget": 1, "r.VolumetricRenderTarget.Mode": 0,
                       "r.VolumetricCloud.ViewRaySampleMaxCount": 96, "r.VolumetricCloud.SkyAO": 0,
                       "r.VolumetricCloud.ShadowMap": 0},
             "summary": "M_StormCell march at quarter resolution, weather map + 32^3 noise, no cloud shadow map, "
                        "tier 0's panorama kept as the far field beyond 15 km"},
            {"tier": 2, "est_vram_mb": 14.0, "volumetric_cloud_component": True, "noise": 64, "ms_octaves": 2,
             "view_sample_count_scale": 0.5, "shadow_view_sample_count_scale": 0.25, "tracing_max_km": 25.0,
             "cvars": {"r.VolumetricRenderTarget": 1, "r.VolumetricRenderTarget.Mode": 0,
                       "r.VolumetricCloud.ViewRaySampleMaxCount": 192, "r.VolumetricCloud.SkyAO": 1,
                       "r.VolumetricCloud.ShadowMap": 0},
             "summary": "64^3 noise, two scattering octaves, sky AO on"},
            {"tier": 3, "est_vram_mb": 40.0, "volumetric_cloud_component": True, "noise": 64, "ms_octaves": 3,
             "view_sample_count_scale": 1.0, "shadow_view_sample_count_scale": 0.5, "tracing_max_km": 40.0,
             "cvars": {"r.VolumetricRenderTarget": 1, "r.VolumetricRenderTarget.Mode": 1,
                       "r.VolumetricCloud.ViewRaySampleMaxCount": 384, "r.VolumetricCloud.SkyAO": 1,
                       "r.VolumetricCloud.ShadowMap": 1},
             "summary": "half-resolution march, three octaves, cloud shadow map"},
        ],
        "tiers_note": "VRAM figures are estimates (render targets at 1280 wide plus the baked textures); cvar names "
                      "are from memory of UE 5.x and must be checked with `help` in the pinned build; no tier has "
                      "been run, none is known to hold",
        "shared_params": {
            "exposure_ev": EXPOSURE_EV100, "sun_elevation_deg": SUN_ELEVATION_DEG,
            "deck_illuminance_fraction": DECK_FRACTION, "skylight_intensity_cd_m2": SKYLIGHT_CD_M2,
            "sky_colour_temperature_k": SKY_COLOUR_TEMPERATURE_K, "ground_albedo": GROUND_ALBEDO_WET,
            "assumed_visibility_m": VISIBILITY_M, "haze_density_per_m": _r(pano["haze_extinction_per_m"], 6),
            "cloud_base_m": CLOUD_BASE_M, "deck_top_m": DECK_TOP_M, "cell_top_m": CELL_TOP_M,
            "cell_core_radius_m": CELL_RADIUS_M, "cell_core_distance_m": OBSERVER_TO_CORE_M,
            "scud_base_m": 300.0, "cloud_extinction_scale": _r(k, 5),
            "cloud_droplet_diameter_um": DROPLET_DIAMETER_UM, "cloud_phase_mean_cosine": _r(g, 5),
            "cloud_base_luminance_core_cd_m2": _r(rel.min() * SKYLIGHT_CD_M2, 1),
            "cloud_base_luminance_max_cd_m2": _r(rel.max() * SKYLIGHT_CD_M2, 1),
            "rain_shaft_mask": "storm_weather_128.tga B",
        },
    }
    files["storm_cloud_types.json"] = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return files


SOURCES = [
    {"name": "Bohren 1987, Multiple scattering of light and some of its observable consequences, Am. J. Phys. 55",
     "used_for": "two-stream diffuse transmittance of a conservative cloud, T = 2 / (2 + (1 - g) tau)",
     "licence": "published formula (no asset copied)"},
    {"name": "Stephens 1978, Radiation profiles in extended water clouds II, J. Atmos. Sci. 35",
     "used_for": "extinction from liquid water content and effective radius, sigma = 3 LWC / (2 rho r_eff)",
     "licence": "published formula (no asset copied)"},
    {"name": "Jendersie & d'Eon 2023, An Approximate Mie Scattering Function for Fog and Cloud Rendering",
     "url": "https://research.nvidia.com/labs/rtr/approximate-mie/",
     "used_for": "HG + Draine blend and its fit constants for 5-50 um droplets",
     "licence": "paper, formulas only; draine.hlsl (MIT) was NOT fetched or vendored",
     "note": "constants transcribed, not re-read against the PDF in this session"},
    {"name": "Wrenninge, Kulla & Lundqvist 2013, Oz: The Great and Volumetric (SIGGRAPH talk)",
     "url": "https://fpsunflower.github.io/ckulla/data/oz_volumes.pdf",
     "used_for": "octave multiple-scattering approximation", "licence": "paper, formulas only"},
    {"name": "Koschmieder 1924 visibility law (2 % contrast threshold)",
     "used_for": "haze extinction = 3.912 / visibility", "licence": "published formula (no asset copied)"},
    {"name": "lighting_exposure.physical_light_units.storm (this repository, baked/storm_plu.json)",
     "used_for": "SkyAtmosphere clear-sky reference 50193.6 lux, deck fraction 0.25, SkyLight 3395.1 cd/m2, EV100 12.5",
     "licence": "project's own"},
]


def provenance(files: Dict[str, bytes]) -> Dict[str, Any]:
    return {
        "item": ITEM,
        "status": "UNMEASURED: generated on the Mac; no frame rendered, nothing downloaded, nothing vendored",
        "generated": [{"path": f"baked/{n}", "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b),
                       "by": "generate.py", "licence": "project's own (procedural, no third-party pixels)"}
                      for n, b in sorted(files.items())],
        "fetched_assets": [],
        "sources": SOURCES,
        "considered_not_adopted": [
            {"name": "PetrVevoda/pragueskymodel, Scroga/Altitude-Responsive-Sky-Model",
             "why": "clear and twilight sky model, not an under-deck storm sky; dataset licence unverified"},
            {"name": "CloudTomography/AT3D LES fields", "why": "GPL-3.0; shallow cumulus fields, not a cumulonimbus"},
            {"name": "fgarlin/skytracer aerosol tables", "why": "aerosol cross-sections; this item is droplet cloud"},
            {"name": "Poly Haven pure-sky HDRIs", "why": "partly cloudy daylight, would contradict the 0.25 deck"},
        ],
    }


def main() -> None:
    files = build()
    BAKED.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (BAKED / name).write_bytes(data)
    (LANE / "PROVENANCE.json").write_text(json.dumps(provenance(files), indent=2) + "\n", encoding="utf-8")
    for name, data in sorted(files.items()):
        print(f"{hashlib.sha256(data).hexdigest()[:16]}  {len(data):>8}  baked/{name}")


if __name__ == "__main__":
    main()
