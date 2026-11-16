"""The beauty sky gradient (lane sky-atmosphere, 2026-11-15): ``-look-sky-gradient=on|off``.

The fault it fixes (Windows r99/r199 #13 and the look-dev base 3/13): the sky is
one flat grey-navy wash, darker than the haze at the horizon, with no blue
zenith, no pale horizon band and no glow round the sun. Two engine readings
(UE 5.7 source, pinned in scripts/check_bridge_api.sh):

1. The height fog is drawn OVER the sky atmosphere (DeferredShadingRenderer:
   RenderSkyAtmosphere, then RenderFog), and a sky pixel is not "infinitely
   far": with the reversed infinite projection the engine's DeviceZ -> depth
   transform subtracts 1e-8 (SceneView.cpp CreateInvDeviceZToWorldZTransform),
   so DeviceZ 0 decodes to 1 / 1e-8 cm = :data:`SKY_PIXEL_DEPTH_KM` (1000 km).
   Every sky pixel therefore takes the analytic fog's full ray (capped at the
   0.92 max opacity), coloured by the fog's in-scatter: under a ``-sky=`` plan
   (FlightSimSky.cpp) that is black plus the atmosphere's DISTANT SKY LIGHT,
   the mean radiance over the whole sphere sampled at 6 km
   (SkyAtmosphere.usf RenderDistantSkyLightLutCS, isotropic phase). That mean is
   darker and flatter than any real horizon, so the sky turned navy. The fog's
   own FogCutoffDistance ("useful for excluding skyboxes", HeightFogCommon.ush:
   ExpFogFactor = 1 past it) set to :data:`FOG_CUTOFF_KM` lets the sky pixels
   show the physical atmosphere alone (Rayleigh deep-blue zenith, Mie white
   aureole round the sun, a pale horizon) while every surface keeps its fog:
   the farthest tile ever visible is :func:`max_visible_distance_km` (an 8.85 km
   summit seen from 13.7 km, 754 km) < 950 km < 1000 km.

2. The fog that remains on surfaces saturates to that dim sphere-mean colour,
   so distant ground and sea fade to navy, darker than the sky above the
   horizon (the backwards contrast the brief reports). In real air the airlight
   of an infinitely deep horizontal path IS the horizon sky (Koschmieder), so
   the fog's ambient term is scaled by :func:`horizon_airlight_gain`: the
   ratio of the horizon's luminance (2 degrees up, azimuth mean) to the upper
   hemisphere's mean under the CIE standard clear sky (ISO 15469 / CIE S 011
   type 12: a=-1, b=-0.32, c=10, d=-3, e=0.45), 2.3 with the sun on the horizon
   to 1.12 at the zenith (:data:`AIRLIGHT_GAIN_TABLE`, the C++ copy is
   FlightSimWorldPure::HorizonAirlightGain), capped at :data:`AIRLIGHT_GAIN_MAX`
   and faded to 1 at civil twilight (-6 degrees).

Applied to the clear and hazy rows only (the rows whose fog has the Mie layer's
vertical profile, ``world_beauty.ATMOSPHERE[..]["fog_scale_height_km"] > 0``);
the weather rows keep the fog over the sky (a deck's grey column). The
atmosphere's own coefficients are set explicitly to the engine's Earth values
(Bruneton & Neyret 2008 / Hillaire 2020, the pinkpocketTV video's settings):
Rayleigh 5.802 / 13.558 / 33.1 per Mm at an 8 km scale height, Mie 3.996 per Mm
scattering (0.444 absorption) at 1.2 km, ozone 0.650 / 1.881 / 0.085 per Mm in a
tent at 25 km, 15 km wide -- identical to the component's defaults today, set so
a default change can never drift the beauty sky.

VISUAL ONLY: the fog cutoff and the ambient gain change no label, mask, depth
or measure pass (the measure quality never runs ApplyAtmosphere), no physics.
GPU cost: none -- FogCutoffDistance is a uniform the fog shader always reads
(one compare), the ambient scale a uniform multiply; no material, permutation
or pass is added. ``-look-sky-gradient=off`` is claude/hl-sky's sky exactly.
UNMEASURED on the iGPU until the Windows A/B.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

__all__ = [
    "SKY_GRADIENT_SWITCH", "SKY_GRADIENT_SWITCH_WORDS", "sky_gradient_mode",
    "SKY_PIXEL_DEPTH_KM", "FOG_CUTOFF_KM", "EARTH_RADIUS_KM", "max_visible_distance_km",
    "CIE_CLEAR_SKY", "cie_clear_sky_relative", "cie_horizon_to_mean",
    "AIRLIGHT_GAIN_TABLE", "AIRLIGHT_GAIN_MAX", "AIRLIGHT_TWILIGHT_DEG", "horizon_airlight_gain",
    "EARTH_ATMOSPHERE", "GRADIENT_PRESETS",
]

SKY_GRADIENT_SWITCH = "-look-sky-gradient"
SKY_GRADIENT_SWITCH_WORDS: Tuple[str, ...] = ("on", "off")

#: Where a sky pixel decodes to: 1 / 1e-8 cm (SceneView.cpp SubtractValue -= 1e-8).
SKY_PIXEL_DEPTH_KM = 1000.0
#: FogCutoffDistance (km): past every surface, short of every sky pixel.
FOG_CUTOFF_KM = 950.0
EARTH_RADIUS_KM = 6371.0
#: The highest summit (Everest, km) and the highest camera the host flies (FL450, km).
HIGHEST_TERRAIN_KM = 8.849
HIGHEST_CAMERA_KM = 13.716

#: CIE standard general sky type 12 (CIE clear sky, low turbidity).
CIE_CLEAR_SKY: Dict[str, float] = {"a": -1.0, "b": -0.32, "c": 10.0, "d": -3.0, "e": 0.45}

#: horizon / upper-hemisphere-mean luminance at sun elevation 0, 10, ... 90 degrees.
AIRLIGHT_GAIN_TABLE: Tuple[float, ...] = (2.313, 2.016, 1.717, 1.511, 1.371, 1.273, 1.204, 1.158, 1.131, 1.123)
AIRLIGHT_GAIN_MAX = 2.0
#: Below the horizon the gain fades to 1 at civil twilight (the plan dims the sun).
AIRLIGHT_TWILIGHT_DEG = -6.0

#: The engine's Earth atmosphere (per km, as the setters take them): the
#: component defaults (SkyAtmosphereComponent.cpp 96-124).
EARTH_ATMOSPHERE: Dict[str, object] = {
    "rayleigh_per_km": (0.005802, 0.013558, 0.033100),
    "rayleigh_scale_height_km": 8.0,
    "mie_scattering_per_km": 0.003996,
    "mie_absorption_per_km": 0.000444,
    "ozone_per_km": (0.000650, 0.001881, 0.000085),
    "ozone_tip_altitude_km": 25.0,
    "ozone_width_km": 15.0,
}

#: The world_beauty rows the gradient applies to (their fog has a vertical profile).
GRADIENT_PRESETS: Tuple[str, ...] = ("clear", "hazy")


def sky_gradient_mode(word: Optional[str]) -> str:
    """``on`` (the default, an empty word) or ``off``; any other word is the host's
    refusal ``world_beauty.sky_gradient``."""
    chosen = (word or "").strip() or "on"
    if chosen not in SKY_GRADIENT_SWITCH_WORDS:
        raise ValueError(f"world_beauty.sky_gradient: -look-sky-gradient={chosen} is not on or off")
    return chosen


def max_visible_distance_km(camera_km: float = HIGHEST_CAMERA_KM,
                            terrain_km: float = HIGHEST_TERRAIN_KM) -> float:
    """Geometric line of sight over a smooth Earth: sqrt(2 R h1) + sqrt(2 R h2)."""
    r = EARTH_RADIUS_KM
    return math.sqrt(2.0 * r * camera_km + camera_km ** 2) + math.sqrt(2.0 * r * terrain_km + terrain_km ** 2)


def cie_clear_sky_relative(zenith_rad: float, azimuth_rad: float, sun_zenith_rad: float) -> float:
    """CIE sky luminance up to a constant: f(gamma) x phi(Z)."""
    k = CIE_CLEAR_SKY
    cos_g = (math.cos(zenith_rad) * math.cos(sun_zenith_rad)
             + math.sin(zenith_rad) * math.sin(sun_zenith_rad) * math.cos(azimuth_rad))
    gamma = math.acos(max(-1.0, min(1.0, cos_g)))
    f = 1.0 + k["c"] * (math.exp(k["d"] * gamma) - math.exp(k["d"] * math.pi / 2.0)) + k["e"] * cos_g ** 2
    phi = 1.0 + k["a"] * math.exp(k["b"] / max(math.cos(zenith_rad), 1e-9))
    return f * phi


def cie_horizon_to_mean(sun_elevation_deg: float, n_zenith: int = 120, n_azimuth: int = 90) -> float:
    """Horizon (2 degrees up, azimuth mean) over the solid-angle mean of the upper hemisphere."""
    zs = math.radians(90.0 - max(1.0, min(90.0, sun_elevation_deg)))
    num = den = 0.0
    for i in range(n_zenith):
        z = (i + 0.5) * (math.pi / 2.0) / n_zenith
        w = math.sin(z)
        for j in range(n_azimuth):
            num += w * cie_clear_sky_relative(z, (j + 0.5) * 2.0 * math.pi / n_azimuth, zs)
            den += w
    mean = num / den
    zh = math.radians(88.0)
    horizon = sum(cie_clear_sky_relative(zh, (j + 0.5) * 2.0 * math.pi / n_azimuth, zs)
                  for j in range(n_azimuth)) / n_azimuth
    return horizon / mean


def horizon_airlight_gain(sun_elevation_deg: float) -> float:
    """The fog ambient's gain (C++ FlightSimWorldPure::HorizonAirlightGain): the table
    interpolated linearly, capped at AIRLIGHT_GAIN_MAX; below 0 degrees it fades to 1
    at AIRLIGHT_TWILIGHT_DEG and is 1 beyond."""
    el = float(sun_elevation_deg)
    table = AIRLIGHT_GAIN_TABLE
    if el < 0.0:
        top = min(table[0], AIRLIGHT_GAIN_MAX)
        t = max(0.0, min(1.0, el / AIRLIGHT_TWILIGHT_DEG))
        return top + (1.0 - top) * t
    x = min(el, 90.0) / 10.0
    i = min(int(x), len(table) - 2)
    f = x - i
    return min(table[i] + (table[i + 1] - table[i]) * f, AIRLIGHT_GAIN_MAX)
