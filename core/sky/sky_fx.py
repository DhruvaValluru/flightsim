"""High-sky effects lane (2026-11-15): the beauty-only rainbow and the in-cloud
lightning flash. The Python twin of the pure laws in
ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimSkyFx.h
(namespace FlightSimSkyFxPure) and the constants pasted into
assets/shaders/world/rainbow.hlsl; tests/test_sky_fx.py compiles the C++ with
g++ and compares, and pins the shader's tables to this module.

BEAUTY ONLY. Neither effect touches a label, ID, depth, mask or keypoint pass,
the measure outputs or the physics:

* the rainbow is one additive, unlit, two-sided sphere (M_FlightSimRainbow) in
  FFlightSimVisualScene.BeautyOnlyActors, no depth, no custom depth, no shadow,
  no collision, built by ApplyBeautySkyFx (FlightSimSkyFx.cpp), which only
  FFlightSimVisualScene::ApplyBeautyWeatherLook calls (-quality=beauty);
* the cloud flash only sets the storm cell material's existing Flash and
  FlashRelCm parameters (storm_glow.hlsl's law) when the cell is drawn and no
  real flash of the weather's own schedule is in the exposure, and only after
  FFlightSimWeather::ApplyBeautyStormVantage (beauty only) armed it.

Switches (the command line, then FLIGHTSIM_RENDER_SWITCHES):

* ``-look-rainbow=on|off`` (on): off builds no sphere (the old sky).
* ``-look-cloud-flash=off|schedule|on`` (schedule): off is the old storm;
  schedule lights an intracloud flash in the share of frames the card's own
  flash rate gives; on lights one in every beauty frame (for the A/B).
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

# -- rainbow -------------------------------------------------------------------

RAINBOW_SWITCH = "-look-rainbow"
RAINBOW_MODES = ("on", "off")

#: The wavelengths the bow is summed over, nm (400-700 nm in nine bands).
RAINBOW_WAVELENGTHS_NM: Tuple[float, ...] = (410.0, 440.0, 470.0, 500.0, 530.0, 560.0, 600.0, 640.0, 680.0)

#: Water's refractive index, n = A + B / lambda^2 (lambda in nm), fitted through
#: Hale & Querry (1973) at 400 nm (1.339) and 700 nm (1.331); it gives 1.3347 at
#: 500 nm and 1.3324 at 600 nm against their 1.335 and 1.332.
WATER_N_A = 1.3271
WATER_N_B = 1900.6

#: The sun's angular diameter, 0.533 deg, as a uniform disc has sigma 0.133 deg;
#: the Airy broadening of 0.5-1 mm rain drops is about 0.4 deg (Lee 1998, Applied
#: Optics 37:1506, "Mie theory, Airy theory, and the natural rainbow"). The
#: ring's gaussian sigma is their quadrature sum.
SUN_DISC_SIGMA_DEG = 0.133
DROP_AIRY_SIGMA_DEG = 0.4
RAINBOW_SIGMA_DEG = round(math.hypot(SUN_DISC_SIGMA_DEG, DROP_AIRY_SIGMA_DEG), 4)

#: The secondary bow's luminance against the primary's: about 0.43 (Lee 1998).
RAINBOW_SECONDARY_RATIO = 0.43

#: Rain's visible extinction, beta = A R^B km^-1 (R in mm/h): the common fit
#: 0.25 R^0.63 for visibility in rain. The bow is seen through the rain between
#: the camera and the curtain's far side, RAINBOW_PATH_KM.
RAIN_EXTINCTION_A = 0.25
RAIN_EXTINCTION_B = 0.63
RAINBOW_PATH_KM = 2.0

#: The engine sphere's radius about the scene origin (the aircraft's start, as
#: the weather look's shafts are placed), km; the camera is inside it.
RAINBOW_RADIUS_KM = 8.0
#: The bow fades out over this height above the cloud base (no rain above it), m.
RAINBOW_TOP_FADE_M = 300.0
#: Without a cloud layer on the card, the rain's top (the weather look's own
#: DefaultCloudBaseM).
RAINBOW_DEFAULT_RAIN_TOP_M = 1200.0

#: The look (UNCALIBRATED, set by look-dev probe): the primary's peak radiance as
#: a share of a white Lambertian surface under the sun (E / pi); the brightening
#: inside the primary (the bow's white inner skirt) as a share of that peak, and
#: its e-folding angle inside the bow.
RAINBOW_LOOK: Dict[str, float] = {
    "PrimaryPeak": 0.05,
    "InnerGlow": 0.25,
    "InnerFoldDeg": 6.0,
}


def water_index(wavelength_nm: float) -> float:
    return WATER_N_A + WATER_N_B / (wavelength_nm * wavelength_nm)


def bow_radius_deg(n: float, k: int) -> float:
    """Descartes' rainbow: the angular radius about the antisolar point of the
    k-internal-reflection bow (k = 1 primary, k = 2 secondary) at minimum
    deviation, cos i = sqrt((n^2 - 1) / (k (k + 2)))."""
    cos_i = math.sqrt((n * n - 1.0) / (k * (k + 2)))
    i = math.acos(cos_i)
    r = math.asin(math.sin(i) / n)
    deviation = 2.0 * (i - r) + k * (math.pi - 2.0 * r)
    return 180.0 - math.degrees(deviation) if k == 1 else math.degrees(deviation) - 180.0


def bow_radii(k: int) -> Tuple[float, ...]:
    return tuple(round(bow_radius_deg(water_index(w), k), 4) for w in RAINBOW_WAVELENGTHS_NM)


def _g(x: float, mu: float, s1: float, s2: float) -> float:
    t = (x - mu) / (s1 if x < mu else s2)
    return math.exp(-0.5 * t * t)


def cie_xyz(wavelength_nm: float) -> Tuple[float, float, float]:
    """The CIE 1931 2-degree colour matching functions, the multi-lobe fit of
    Wyman, Sloan & Shirley (2013, JCGT 2(2))."""
    x = (1.056 * _g(wavelength_nm, 599.8, 37.9, 31.0) + 0.362 * _g(wavelength_nm, 442.0, 16.0, 26.7)
         - 0.065 * _g(wavelength_nm, 501.1, 20.4, 26.2))
    y = 0.821 * _g(wavelength_nm, 568.8, 46.9, 40.5) + 0.286 * _g(wavelength_nm, 530.9, 16.3, 31.1)
    z = 1.217 * _g(wavelength_nm, 437.0, 11.8, 36.0) + 0.681 * _g(wavelength_nm, 459.0, 26.0, 13.8)
    return x, y, z


def xyz_to_linear_srgb(x: float, y: float, z: float) -> Tuple[float, float, float]:
    return (3.2406 * x - 1.5372 * y - 0.4986 * z,
            -0.9689 * x + 1.8758 * y + 0.0415 * z,
            0.0557 * x - 0.2040 * y + 1.0570 * z)


def band_colours() -> Tuple[Tuple[float, float, float], ...]:
    """Each band's linear-sRGB colour, negatives clipped (out of gamut), then each
    channel scaled so the nine bands sum to white (1, 1, 1): a bow with every band
    on one ring is the sun's colour at unit gain."""
    raw = [tuple(max(c, 0.0) for c in xyz_to_linear_srgb(*cie_xyz(w))) for w in RAINBOW_WAVELENGTHS_NM]
    sums = [sum(band[c] for band in raw) for c in range(3)]
    return tuple(tuple(round(band[c] / sums[c], 5) for c in range(3)) for band in raw)


def rain_optical_depth(rate_mmh: float, path_km: float = RAINBOW_PATH_KM) -> float:
    if rate_mmh <= 0.0:
        return 0.0
    return RAIN_EXTINCTION_A * rate_mmh ** RAIN_EXTINCTION_B * path_km


def rainbow_mode(word: Optional[str]) -> str:
    chosen = "on" if word is None or word == "" else word
    if chosen not in RAINBOW_MODES:
        raise ValueError(f"sky_fx.rainbow: {RAINBOW_SWITCH}={chosen} is not on or off")
    return chosen


def rainbow_strength(mode_on: bool, rate_mmh: float, sun_elevation_deg: float) -> float:
    """The bow's gain: 0 with the switch off, no rain or the sun at or below the
    horizon; else the share of sunlight the rain path scatters, 1 - exp(-tau)."""
    if not mode_on or rate_mmh <= 0.0 or sun_elevation_deg <= 0.0:
        return 0.0
    return 1.0 - math.exp(-rain_optical_depth(rate_mmh))


def rainbow_ring(theta_deg: float) -> Tuple[float, float, float]:
    """rainbow.hlsl's spectral ring at angle theta from the antisolar point, before
    the sun's radiance and the strength: primary + ratio * secondary + the inner
    skirt, each band a gaussian of RAINBOW_SIGMA_DEG about its radius."""
    colours = band_colours()
    look = RAINBOW_LOOK
    out = [0.0, 0.0, 0.0]
    for radius_p, radius_s, colour in zip(bow_radii(1), bow_radii(2), colours):
        tp = (theta_deg - radius_p) / RAINBOW_SIGMA_DEG
        ts = (theta_deg - radius_s) / RAINBOW_SIGMA_DEG
        w = math.exp(-0.5 * tp * tp) + RAINBOW_SECONDARY_RATIO * math.exp(-0.5 * ts * ts)
        for c in range(3):
            out[c] += w * colour[c]
    inner_edge = bow_radii(1)[0]
    skirt = look["InnerGlow"] * math.exp(-(inner_edge - theta_deg) / look["InnerFoldDeg"]) if theta_deg < inner_edge else 0.0
    return tuple(look["PrimaryPeak"] * (out[c] + skirt / 3.0) for c in range(3))


def rainbow_top_fade(height_m: float, rain_top_m: float) -> float:
    """1 below the rain's top, 0 RAINBOW_TOP_FADE_M above it, smoothstep between."""
    x = min(max((height_m - rain_top_m) / RAINBOW_TOP_FADE_M, 0.0), 1.0)
    return 1.0 - x * x * (3.0 - 2.0 * x)


# -- in-cloud lightning flash ----------------------------------------------------

CLOUD_FLASH_SWITCH = "-look-cloud-flash"
CLOUD_FLASH_MODES = ("off", "schedule", "on")
CLOUD_FLASH_OFF, CLOUD_FLASH_SCHEDULE, CLOUD_FLASH_ON = 0, 1, 2

#: A return stroke's radiated optical energy (0.4-1.1 um), J: Krider, Dawson &
#: Uman (1968, J. Geophys. Res. 73:3335), about 8.7e5 J for a single stroke.
CLOUD_FLASH_ENERGY_J = 8.7e5
#: The card's luminous efficacy (weather.lightning.light_curve, 80 lm/W).
CLOUD_FLASH_EFFICACY_LM_PER_W = 80.0
#: The shortest window the stroke's light is spread over, s (a stroke's luminous
#: phase is ~1 ms; a shorter shutter would see a brighter but partial stroke).
CLOUD_FLASH_MIN_WINDOW_S = 1.0e-3
#: An intracloud flash's visible duration, s (IC flashes last 0.2-0.5 s;
#: Mazur 2002, Ogawa & Brook 1964): the schedule's bin.
CLOUD_FLASH_VISIBLE_S = 0.3
#: Without a card rate: 6 per minute (the procedural weather's default storm).
CLOUD_FLASH_DEFAULT_RATE_PER_MIN = 6.0
CLOUD_FLASH_DEFAULT_IC_CG = 3.0
#: Where the flash sits in the tower: towards the camera at this share of the
#: tower radius, at this share of the way from the base to the top.
CLOUD_FLASH_RADIAL_SHARE = 0.6
CLOUD_FLASH_HEIGHT_SHARE = 0.3

_MASK64 = (1 << 64) - 1


def cloud_flash_mode(word: Optional[str]) -> int:
    chosen = "schedule" if word is None or word == "" else word
    if chosen not in CLOUD_FLASH_MODES:
        raise ValueError(f"sky_fx.cloud_flash: {CLOUD_FLASH_SWITCH}={chosen} is not off, schedule or on")
    return CLOUD_FLASH_MODES.index(chosen)


def cloud_flash_cd(shutter_s: float) -> float:
    """The flash's mean luminous intensity over the exposure, cd:
    E eta / (4 pi max(shutter, 1 ms))."""
    window = max(shutter_s, CLOUD_FLASH_MIN_WINDOW_S)
    return CLOUD_FLASH_ENERGY_J * CLOUD_FLASH_EFFICACY_LM_PER_W / (4.0 * math.pi * window)


def splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


def unit(seed: int, index: int) -> float:
    return (splitmix64((seed * 0x100000001B3 + index) & _MASK64) >> 11) * (1.0 / 9007199254740992.0)


def cloud_flash_share(rate_per_min: float, ic_cg: float) -> float:
    """The share of schedule bins with an intracloud flash: rate / 60 * IC share *
    the bin, at most 1."""
    rate = rate_per_min if rate_per_min > 0.0 else CLOUD_FLASH_DEFAULT_RATE_PER_MIN
    ratio = ic_cg if ic_cg >= 0.0 else CLOUD_FLASH_DEFAULT_IC_CG
    return min(rate / 60.0 * (ratio / (1.0 + ratio)) * CLOUD_FLASH_VISIBLE_S, 1.0)


def cloud_flash_lit(mode: int, seed: int, time_s: float, rate_per_min: float, ic_cg: float) -> bool:
    if mode == CLOUD_FLASH_ON:
        return True
    if mode != CLOUD_FLASH_SCHEDULE:
        return False
    bin_index = int(math.floor(max(time_s, 0.0) / CLOUD_FLASH_VISIBLE_S))
    return unit(seed & _MASK64, bin_index) < cloud_flash_share(rate_per_min, ic_cg)


def cloud_flash_rel_m(camera_east_m: float, camera_north_m: float, tower_radius_m: float,
                      base_m: float, top_m: float) -> Tuple[float, float, float]:
    """The flash's place relative to the drawn cell centre (east, north, up), m:
    on the camera's side of the tower, never past the camera."""
    d = math.hypot(camera_east_m, camera_north_m)
    up = base_m + CLOUD_FLASH_HEIGHT_SHARE * max(top_m - base_m, 0.0)
    if d <= 0.0:
        return 0.0, 0.0, up
    reach = min(CLOUD_FLASH_RADIAL_SHARE * tower_radius_m, 0.9 * d)
    return camera_east_m / d * reach, camera_north_m / d * reach, up


def record_basis() -> Dict[str, str]:
    return {
        "rainbow": "Descartes bows over water n(lambda) fitted to Hale & Querry 1973; CIE 1931 (Wyman 2013 fit); "
                   "secondary 0.43 of primary, sigma = sun disc + Airy (Lee 1998); gain 1 - exp(-0.25 R^0.63 * 2 km)",
        "cloud_flash": "storm_glow.hlsl's law at E eta / (4 pi shutter), E = 8.7e5 J (Krider et al. 1968), "
                       "IC share of the card's rate over 0.3 s bins",
    }


def table(values: Sequence[float]) -> str:
    return ", ".join(f"{v:.4f}" for v in values)
