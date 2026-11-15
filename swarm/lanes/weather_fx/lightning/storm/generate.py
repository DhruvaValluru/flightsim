#!/usr/bin/env python3
"""weather_fx.lightning.storm: bake the lightning channel's rain glow on the Mac.

What the project draws today: every cloud-to-ground channel as a camera-facing
ribbon at least 1.5 pixels wide (assets/shaders/weather/lightning_emissive.hlsl)
and one shadow-casting point light. A bolt seen through kilometres of heavy
rain is not a hard line: the direct beam is cut by e^-T and the light scattered
out of it arrives as a halo around the channel. That halo is the atmospheric
point spread function of Narasimhan & Nayar (CVPR 2003), a Legendre series
that is far too heavy for a pixel shader on an integrated GPU. This script
sums the series offline and writes two 64 x 32 16-bit look-up tables the
render path only samples:

* ``lightning_apsf_line_64x32.png``  the APSF integrated along a line source
  (the channel): the glow's radiance across the ribbon, per lux/rad of channel;
* ``lightning_apsf_point_64x32.png`` the point-source APSF (per lux), for the
  flash's centroid and for any other lane's lights seen through the same rain.

Kernel: K(T, angle) = (1 - e^-T) * shape(T, angle) / N(T), N(T) = 4 pi / T^2
the series' integral over the sphere. The (1 - e^-T) scale says the light
removed from the direct beam reappears as glow (single-scattering albedo 1,
water in the visible); that energy statement is an approximation made here,
not Narasimhan & Nayar's. The series is valid for T > 1; below T_MIN the
shader keeps the T_MIN shape and scales it by (1 - e^-T) / (1 - e^-T_MIN).

Visual-only. Nothing here was rendered: every luminance in the table is
arithmetic from the project's own stroke energy (core/scene/lightning.py) and
the storm look of lighting_exposure.physical_light_units.storm.

Run:  .venv/bin/python swarm/lanes/weather_fx/lightning/storm/generate.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from numpy.polynomial import legendre
from PIL import Image

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]
BAKED = LANE / "baked"

# -- the LUT's axes ---------------------------------------------------------
LUT_W, LUT_H = 64, 32
T_MIN, T_MAX = 1.05, 16.0           # optical thickness camera -> channel (log axis)
PHI_MAX_RAD = 0.5                   # angle from the channel (u = sqrt(phi / PHI_MAX))
SERIES_TERMS = 400                  # T_MIN^-400 = 3e-9: the series has converged
LINE_HALF_ANGLE_RAD = math.pi / 2   # the line integral's reach either side
LINE_STEPS = 600

#: Forward-scattering parameter q of the APSF (the phase function's g). Narasimhan &
#: Nayar give rain as 0.9 .. 1.0; 0.9 is the wide end (a calibration, stated).
RAIN_Q = 0.9

# -- the look other lanes must share (lighting_exposure.physical_light_units.storm)
VISIBILITY_M = 3000.0               # that lane's assumed_visibility_m
KOSCHMIEDER = 3.912                 # sigma = 3.912 / V (2 % contrast threshold)
EXPOSURE_EV100 = 12.5
SKY_HORIZON_CD_M2 = 1455.1
SATURATION_CD_M2 = 6951.1
LIGHTNING_K = 8000.0
TINT = (0.86, 0.92, 1.0)            # M_LightningChannel's tint (divided by 0.913 there)

# -- assumptions for the by-distance table only (not settings) --------------
SHUTTER_S = 1.0 / 60.0              # 30 fps, 180 degree shutter (the card's exposure wins)
PIXEL_ANGLE_RAD = math.radians(60.0) / 1280.0   # 60 deg across the budget's 1280 px
CHANNEL_RADIUS_M = 0.05             # WeatherChannelRadiusCm
PIXEL_FLOOR = 0.75                  # lightning_offset.hlsl
DISTANCES_M = (1000.0, 2000.0, 3000.0, 5000.0, 8000.0)

AMBIENT_HORIZONTAL_LUX = 12548.4    # that lane's horizontal_illuminance_lux
CHANNEL_LENGTH_M = 5000.0           # that lane's channel_length_m_assumed

TIERS = (
    {"tier": 0, "est_vram_mb": 0.0, "glow": "none", "flash_light": "none",
     "summary": "the channel ribbon as today, no flash light actor at all (today's is a "
                "shadow-casting movable point light of 30 km reach); the flash still reaches rain, "
                "splashes, cloud glow and the sky pulse through the FlashLux scalar. Adds no "
                "texture and no draw; removes a cube shadow pass on stroke frames"},
    {"tier": 1, "est_vram_mb": 0.01, "glow": "none", "flash_light": "one unshadowed point light",
     "summary": "tier 0 plus the flash as one unshadowed point light, and the optional rain "
                "transmittance e^-T on the channel core (RainSigmaPerM)"},
    {"tier": 2, "est_vram_mb": 0.02, "glow": "one additive quad per lit flash, line LUT",
     "flash_light": "one unshadowed point light",
     "summary": "tier 1 plus the baked rain glow: one additive quad per lit flash sampling the "
                "4 KB line LUT out to 0.5 rad (about a third of the frame in overdraw on stroke "
                "frames only)"},
    {"tier": 3, "est_vram_mb": 12.0, "glow": "line LUT quad + point LUT billboard at the centroid",
     "flash_light": "one shadow-casting point light (today's code path)",
     "summary": "tier 2 plus today's shadow-casting flash light (a 1024 px cube shadow map, "
                "estimated 12 MB) and engine bloom on the core"},
)


def _project_lightning():
    """core/scene/lightning.py, read only (its stroke energy and efficacy)."""
    spec = importlib.util.spec_from_file_location("swarm_wx_project_lightning",
                                                  REPO / "core/scene/lightning.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# -- Narasimhan & Nayar 2003 ------------------------------------------------

def apsf_coefficients(t: float, q: float = RAIN_Q, terms: int = SERIES_TERMS) -> np.ndarray:
    """c_m = g_m(T) + g_{m+1}(T), g_0 = 0, g_m = exp(-beta_m T - alpha_m ln T),
    alpha_m = m + 1, beta_m = (2m + 1) / m * (1 - q^(m-1))."""
    m = np.arange(1, terms + 2, dtype=np.float64)
    beta = (2.0 * m + 1.0) / m * (1.0 - q ** (m - 1.0))
    g = np.concatenate(([0.0], np.exp(-beta * t - (m + 1.0) * math.log(t))))
    return g[:-1] + g[1:]


def apsf(t: float, angle_rad: np.ndarray, q: float = RAIN_Q) -> np.ndarray:
    """I(T, cos angle) for I0 = 1: the glow's shape about the source."""
    mu = np.cos(np.clip(angle_rad, 0.0, math.pi))
    return np.maximum(legendre.legval(mu, apsf_coefficients(t, q)), 0.0)


def sphere_norm(t: float) -> float:
    """N(T) = int I dOmega = 4 pi c_0 = 4 pi g_1 = 4 pi / T^2."""
    return 4.0 * math.pi / (t * t)


def point_kernel(t: float, angle_rad: np.ndarray, q: float = RAIN_Q) -> np.ndarray:
    """Glow radiance per lux of unattenuated irradiance from a point source (1/sr)."""
    return (1.0 - math.exp(-t)) * apsf(t, angle_rad, q) / sphere_norm(t)


def line_kernel(t: float, phi_rad: np.ndarray, q: float = RAIN_Q) -> np.ndarray:
    """Glow radiance per (lux per radian of channel) at angle phi from a line source (1/rad)."""
    s = np.linspace(0.0, 1.0, LINE_STEPS + 1)
    psi = LINE_HALF_ANGLE_RAD * s ** 3          # dense near the channel, where the APSF peaks
    rho = np.sqrt(np.asarray(phi_rad, dtype=np.float64)[:, None] ** 2 + psi[None, :] ** 2)
    shape = apsf(t, rho, q)
    integral = 2.0 * np.sum(0.5 * (shape[:, 1:] + shape[:, :-1]) * np.diff(psi)[None, :], axis=1)
    return (1.0 - math.exp(-t)) * integral / sphere_norm(t)


def axis_t() -> np.ndarray:
    return T_MIN * (T_MAX / T_MIN) ** (np.arange(LUT_H) / (LUT_H - 1.0))


def axis_angle() -> np.ndarray:
    return PHI_MAX_RAD * (np.arange(LUT_W) / (LUT_W - 1.0)) ** 2


def kernels() -> Dict[str, np.ndarray]:
    ang = axis_angle()
    return {"line": np.stack([line_kernel(t, ang) for t in axis_t()]),
            "point": np.stack([point_kernel(t, ang) for t in axis_t()])}


def encode(kernel: np.ndarray) -> Dict[str, Any]:
    """Natural log, scaled to 16 bits: K = exp(lerp(ln_min, ln_max, texel))."""
    ln = np.log(np.maximum(kernel, 1.0e-30))
    lo, hi = float(ln.min()), float(ln.max())
    texels = np.round((ln - lo) / (hi - lo) * 65535.0).astype(np.uint16)
    return {"ln_min": lo, "ln_max": hi, "texels": texels}


def decode(texels: np.ndarray, ln_min: float, ln_max: float) -> np.ndarray:
    return np.exp(ln_min + (ln_max - ln_min) * texels.astype(np.float64) / 65535.0)


def sample(kernel: np.ndarray, t: float, angle_rad: float) -> float:
    """Bilinear in the LUT's own axes, the low-T rule included (what the shader does)."""
    tc = min(max(t, T_MIN), T_MAX)
    v = math.log(tc / T_MIN) / math.log(T_MAX / T_MIN) * (LUT_H - 1)
    u = math.sqrt(min(max(angle_rad, 0.0), PHI_MAX_RAD) / PHI_MAX_RAD) * (LUT_W - 1)
    i0, j0 = min(int(v), LUT_H - 2), min(int(u), LUT_W - 2)
    fv, fu = v - i0, u - j0
    ln = np.log(np.maximum(kernel[i0:i0 + 2, j0:j0 + 2], 1.0e-30))
    value = math.exp((1 - fv) * ((1 - fu) * ln[0, 0] + fu * ln[0, 1])
                     + fv * ((1 - fu) * ln[1, 0] + fu * ln[1, 1]))
    if t < T_MIN:
        value *= (1.0 - math.exp(-max(t, 0.0))) / (1.0 - math.exp(-T_MIN))
    return value


def captured_fraction(t: float, half_angle_rad: float) -> float:
    """The share of the line glow's light inside +- half_angle, edge pedestal removed."""
    phi = np.linspace(0.0, half_angle_rad, 400)
    k = line_kernel(t, phi)
    drawn = 2.0 * float(np.sum(0.5 * (k[1:] + k[:-1] - 2.0 * k[-1]) * np.diff(phi)))
    return drawn / (1.0 - math.exp(-t))


# -- what the bolt is worth at this exposure --------------------------------

def by_distance(line: np.ndarray) -> List[Dict[str, Any]]:
    project = _project_lightning()
    lumen_s_per_m = (project.LUMINOUS_EFFICACY_LM_PER_W
                     * project.stroke_total_energy(project.FIRST_STROKE_PEAK_W_PER_M))
    mean_lm_per_m = lumen_s_per_m / SHUTTER_S
    sigma = KOSCHMIEDER / VISIBILITY_M
    flash_cd = mean_lm_per_m * CHANNEL_LENGTH_M / (4.0 * math.pi)   # lightning.py intensity_cd
    rows = []
    for d in DISTANCES_M:
        t = sigma * d
        width = max(2.0 * CHANNEL_RADIUS_M, 2.0 * PIXEL_FLOOR * PIXEL_ANGLE_RAD * d)
        core_clear = mean_lm_per_m / (math.pi ** 2 * width)
        core = core_clear * math.exp(-t)
        glow = mean_lm_per_m / (math.pi ** 2 * d) * sample(line, t, 0.0)
        rows.append({
            "distance_m": d, "optical_thickness": round(t, 3),
            "core_luminance_no_rain_cd_m2": round(core_clear, 1),
            "core_luminance_cd_m2": round(core, 2),
            "glow_peak_luminance_cd_m2": round(glow, 2),
            "core_over_sky_horizon": round(core / SKY_HORIZON_CD_M2, 4),
            "glow_over_sky_horizon": round(glow / SKY_HORIZON_CD_M2, 4),
            "glow_half_width_rad": round(_half_width(line, t), 4),
            "glow_fraction_inside_phi_max": round(
                captured_fraction(min(max(t, T_MIN), T_MAX), PHI_MAX_RAD), 3),
            "flash_mean_lux_no_rain": round(flash_cd / (d * d), 2),
            "flash_over_ambient": round(flash_cd / (d * d) / AMBIENT_HORIZONTAL_LUX, 5),
        })
    return rows


def _half_width(line: np.ndarray, t: float) -> float:
    """The angle where the line glow falls to half its on-channel value."""
    peak = sample(line, t, 0.0)
    lo, hi = 0.0, PHI_MAX_RAD
    if sample(line, t, hi) > 0.5 * peak:
        return PHI_MAX_RAD
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if sample(line, t, mid) > 0.5 * peak else (lo, mid)
    return 0.5 * (lo + hi)


def shared_params() -> Dict[str, Any]:
    return {
        "exposure_ev": EXPOSURE_EV100, "exposure_mode": "manual",
        "assumed_visibility_m": VISIBILITY_M,
        "rain_extinction_per_m": round(KOSCHMIEDER / VISIBILITY_M, 6),
        "rain_forward_scattering_q": RAIN_Q,
        "lightning_colour_temperature_k": LIGHTNING_K,
        "lightning_tint_linear": [round(c / 0.913, 4) for c in TINT],
        "sky_horizon_luminance_cd_m2": SKY_HORIZON_CD_M2,
        "saturation_luminance_cd_m2": SATURATION_CD_M2,
        "flash_light_casts_shadows_tier0": False,
        "flash_rate_per_min": 6.0, "ic_cg_ratio": 3.0,
    }


def hlsl(enc: Dict[str, Dict[str, Any]]) -> str:
    return f"""// GENERATED by swarm/lanes/weather_fx/lightning/storm/generate.py -- do not edit.
// The constants of the baked APSF look-up tables (Narasimhan & Nayar 2003, q = {RAIN_Q}).
// Visual-only. UNMEASURED: no frame has been rendered with this file.
#define FS_APSF_LUT_W {float(LUT_W):.1f}
#define FS_APSF_LUT_H {float(LUT_H):.1f}
#define FS_APSF_T_MIN {T_MIN!r}
#define FS_APSF_T_MAX {T_MAX!r}
#define FS_APSF_PHI_MAX {PHI_MAX_RAD!r}
#define FS_APSF_LINE_LN_MIN {enc['line']['ln_min']!r}
#define FS_APSF_LINE_LN_MAX {enc['line']['ln_max']!r}
#define FS_APSF_POINT_LN_MIN {enc['point']['ln_min']!r}
#define FS_APSF_POINT_LN_MAX {enc['point']['ln_max']!r}

// The kernel at optical thickness T and angle (rad) from the source. Lut is the G16
// texture imported linear (no sRGB), clamp addressing, bilinear, no mips.
float FsApsfKernel(Texture2D Lut, SamplerState LutSampler, float T, float Angle, float LnMin, float LnMax)
{{
    float tc = clamp(T, FS_APSF_T_MIN, FS_APSF_T_MAX);
    float u = sqrt(saturate(Angle / FS_APSF_PHI_MAX));
    float v = log(tc / FS_APSF_T_MIN) / log(FS_APSF_T_MAX / FS_APSF_T_MIN);
    float2 uv = float2((u * (FS_APSF_LUT_W - 1.0) + 0.5) / FS_APSF_LUT_W,
                       (v * (FS_APSF_LUT_H - 1.0) + 0.5) / FS_APSF_LUT_H);
    float k = exp(lerp(LnMin, LnMax, Lut.SampleLevel(LutSampler, uv, 0).r));
    // Below T_MIN the series is not valid: keep its shape, scale by the light scattered.
    return k * (1.0 - exp(-max(T, 0.0))) / (1.0 - exp(-tc));
}}
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> Dict[str, Any]:
    """Everything the bake states, without touching the disk."""
    ks = kernels()
    enc = {name: encode(k) for name, k in ks.items()}
    return {
        "item": "weather_fx.lightning.storm", "scenario": "storm",
        "status": "UNMEASURED: computed on the Mac from named formulae; no frame was rendered",
        "visual_only": True,
        "model": {
            "name": "atmospheric point spread function, Narasimhan & Nayar, CVPR 2003",
            "series": "I(T, mu) = sum_m (g_m + g_{m+1}) L_m(mu); g_m = exp(-beta_m T - (m+1) ln T); "
                      "beta_m = (2m+1)/m (1 - q^(m-1)); g_0 = 0",
            "q": RAIN_Q, "terms": SERIES_TERMS,
            "kernel": "K = (1 - e^-T) shape / N(T), N = 4 pi / T^2",
            "energy_statement": "the (1 - e^-T) scale is this lane's approximation, not the paper's",
            "formula_check": "written from the published series; not re-read against the PDF here",
        },
        "lut": {
            "width": LUT_W, "height": LUT_H, "format": "PNG 16-bit grey, linear, ln-encoded",
            "u": "sqrt(angle / phi_max), texel centres at i / (W - 1)",
            "v": "ln(T / T_min) / ln(T_max / T_min), texel centres at j / (H - 1)",
            "t_min": T_MIN, "t_max": T_MAX, "phi_max_rad": PHI_MAX_RAD,
            "line": {"file": "lightning_apsf_line_64x32.png", "unit": "1/rad",
                     "ln_min": enc["line"]["ln_min"], "ln_max": enc["line"]["ln_max"]},
            "point": {"file": "lightning_apsf_point_64x32.png", "unit": "1/sr",
                      "ln_min": enc["point"]["ln_min"], "ln_max": enc["point"]["ln_max"]},
        },
        "table_assumptions": {
            "shutter_s": SHUTTER_S, "ambient_horizontal_lux": AMBIENT_HORIZONTAL_LUX,
            "channel_length_m": CHANNEL_LENGTH_M, "pixel_angle_rad": PIXEL_ANGLE_RAD,
            "stroke": "the project's first return stroke, whole energy inside one exposure",
            "uniform_rain": "one extinction camera to channel (3.912 / visibility); the shaft is denser",
        },
        "by_distance": by_distance(ks["line"]),
        "tiers": [dict(t) for t in TIERS],
        "shared_params": shared_params(),
        "_kernels": ks, "_encoded": enc,
    }


def main() -> int:
    plan = build()
    ks, enc = plan.pop("_kernels"), plan.pop("_encoded")
    BAKED.mkdir(parents=True, exist_ok=True)
    for name in ("line", "point"):
        Image.fromarray(enc[name]["texels"]).save(BAKED / plan["lut"][name]["file"], optimize=False)
    (BAKED / "lightning_apsf.hlsl").write_text(hlsl(enc), encoding="utf-8")
    (BAKED / "lightning_glow.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8")
    for path in sorted(BAKED.iterdir()):
        print(f"{_sha(path)}  baked/{path.name}")
    for row in plan["by_distance"]:
        print(row["distance_m"], "m  T", row["optical_thickness"], " core", row["core_luminance_cd_m2"],
              " glow", row["glow_peak_luminance_cd_m2"], "cd/m2  half width", row["glow_half_width_rad"],
              "rad  flash/ambient", row["flash_over_ambient"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
