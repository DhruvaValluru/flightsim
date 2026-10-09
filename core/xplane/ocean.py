"""Water shading rules transcribed from the simulator's ocean shaders.

Source: the SPIR-V ``ocean_shading`` and ``ocean_meta_data`` modules under
``assets/physical_renders/Resources/shaders``; the decoded, adversarially
checked formulas are in ``assets/logic_reports/shader_decode.json``
(chain ``ocean_shading``, ids F1-F4; chain ``ocean_waves`` for the
spectrum). Constants marked *proposal* are CPU-set uniforms the shaders
only read; their values come from the cited papers, not the simulator.

* F3 depth opacity: ``k = 0.1 * 10**(2*a)`` per metre from the per-degree
  water PNG alpha ``a`` in [0, 1]; ``opacity = 1 - exp(-k * thickness)``
  with ``thickness`` the metres of water along the view ray.
* F4 mean Fresnel (Bruneton, Neyret, Holzschuch 2010):
  ``F = 0.02 + 0.98 * (1 - cosV)**(5*exp(-2.69*sV)) / (1 + 22.7*sV**1.5)``.
* F2 deep colour: ``deep = base * (sky_ambient + T_sun*E_sun*max(sun_y, 0))
  * deep_luminance_ratio``. There is no depth tint: shallow water shows the
  ground through the opacity alone.
* F1 composite: ``water = sun_spec + F*reflection + (1-F)*deep``, foam
  mixed over it, alpha = opacity.
"""
from __future__ import annotations

import math
from typing import Dict, Sequence, Tuple

import numpy as np

FRESNEL_F0 = 0.02                 # literal in the shader (F4)
SLOPE_VARIANCE_FLOOR = 2e-5       # FMax floor on the variance LUT (F4)
GRAVITY = 9.81
JONSWAP_GAMMA = 3.3               # Hasselmann et al. 1973 mean (proposal)
DEFAULT_FETCH_M = 100_000.0       # proposal
CHOPPINESS = 1.0                  # Tessendorf 2001 lambda (proposal)
CASCADE_LENGTHS_M = (250.0, 17.0, 5.0)   # proposal, published FFT-ocean defaults


def extinction_per_m(alpha: np.ndarray) -> np.ndarray:
    """F3: the PNG alpha (0..1) as an extinction coefficient, 0.1..10 /m."""
    return 0.1 * np.power(10.0, 2.0 * np.asarray(alpha, dtype=np.float64))


def depth_opacity(alpha: np.ndarray, thickness_m: np.ndarray) -> np.ndarray:
    """F3: opacity of ``thickness_m`` metres of water (along the view ray)."""
    t = np.maximum(np.asarray(thickness_m, dtype=np.float64), 0.0)
    return 1.0 - np.exp(-extinction_per_m(alpha) * t)


def mean_fresnel(cos_v: np.ndarray, sigma_v: np.ndarray = 0.0) -> np.ndarray:
    """F4: Fresnel averaged over the sub-pixel slope distribution.

    ``cos_v`` is dot(view, normal); ``sigma_v`` the slope standard deviation
    along the view. With ``sigma_v == 0`` this is Schlick with F0 = 0.02."""
    c = np.clip(np.asarray(cos_v, dtype=np.float64), 0.0, 1.0)
    s = np.maximum(np.asarray(sigma_v, dtype=np.float64), 0.0)
    mf = np.power(1.0 - c, 5.0 * np.exp(-2.69 * s)) / (1.0 + 22.7 * s ** 1.5)
    return FRESNEL_F0 + (1.0 - FRESNEL_F0) * mf


def view_slope_sigma(view: Sequence[float],
                     slope_variance_xz: Sequence[float]) -> float:
    """F4: sigma_V from the view direction (y up) and the x/z slope
    variances, floored as the shader floors its LUT read."""
    vx, vy, vz = (float(c) for c in view)
    denom = max(1.0 - vy * vy, 1e-12)
    sx, sz = (max(float(v), SLOPE_VARIANCE_FLOOR) for v in slope_variance_xz)
    return math.sqrt((vx * vx * sx + vz * vz * sz) / denom)


def deep_colour(base_rgb: np.ndarray, sky_ambient: np.ndarray,
                sun_rgb: np.ndarray, sun_dir_y: float,
                deep_luminance_ratio: float = 1.0) -> np.ndarray:
    """F2: linear radiance of the water body (before the 1-F weight).

    ``sun_rgb`` is T_sun * E_sun; the sun term uses the sun's elevation,
    not N.L (irradiance on a flat plane)."""
    e = (np.asarray(sky_ambient, dtype=np.float64)
         + np.asarray(sun_rgb, dtype=np.float64) * max(float(sun_dir_y), 0.0))
    return np.asarray(base_rgb, dtype=np.float64) * e * deep_luminance_ratio


def composite(deep: np.ndarray, reflection: np.ndarray, fresnel: np.ndarray,
              sun_spec: np.ndarray = 0.0, foam: np.ndarray = 0.0,
              foam_rgb: np.ndarray = 0.0, opacity: np.ndarray = 1.0
              ) -> Tuple[np.ndarray, np.ndarray]:
    """F1: (unpremultiplied rgb, alpha). The shader writes rgb*alpha; a
    translucent engine material wants the colour and alpha separately."""
    f = np.asarray(fresnel, dtype=np.float64)[..., None] if np.ndim(fresnel) else float(fresnel)
    water = (np.asarray(sun_spec, dtype=np.float64)
             + np.asarray(reflection, dtype=np.float64) * f
             + np.asarray(deep, dtype=np.float64) * (1.0 - f))
    fm = np.asarray(foam, dtype=np.float64)
    fm = fm[..., None] if fm.ndim else float(fm)
    rgb = water * (1.0 - fm) + np.asarray(foam_rgb, dtype=np.float64) * fm
    return rgb, np.clip(np.asarray(opacity, dtype=np.float64), 0.0, 1.0)


def jonswap(wind_speed_ms: float, fetch_m: float = DEFAULT_FETCH_M
            ) -> Dict[str, float]:
    """The spectrum uniforms the wave shaders read (proposal values: the
    wind-to-spectrum mapping is CPU-side and not in the shaders).
    Hasselmann et al. 1973: alpha = 0.076 (U^2/gF)^0.22,
    omega_p = 22 (g^2/(U F))^(1/3)."""
    u = max(float(wind_speed_ms), 0.1)
    f = max(float(fetch_m), 1.0)
    return {
        "alpha": 0.076 * (u * u / (GRAVITY * f)) ** 0.22,
        "peak_omega": 22.0 * (GRAVITY * GRAVITY / (u * f)) ** (1.0 / 3.0),
        "gamma": JONSWAP_GAMMA,
        "choppiness": CHOPPINESS,
    }


def water_material_parameters(alpha_8bit: int, wind_speed_ms: float = 5.0
                              ) -> Dict[str, float]:
    """Scalars an engine water material needs to reproduce F1-F4 for one
    tile: extinction from the tile's PNG alpha, F0, and the wave spectrum."""
    spec = jonswap(wind_speed_ms)
    return {
        "ExtinctionPerM": float(extinction_per_m(int(alpha_8bit) / 255.0)),
        "FresnelF0": FRESNEL_F0,
        "JonswapAlpha": spec["alpha"],
        "PeakOmega": spec["peak_omega"],
        "Gamma": spec["gamma"],
        "Choppiness": spec["choppiness"],
    }
