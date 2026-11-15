"""Offline bake (Mac): physical light units for the coastal scenario.

Visual-only. Writes ``coastal_plu.json`` and ``coastal_plu_curve.csv`` next to
this file: for every (sea-haze visibility, sun elevation) the sea-level
illuminances in lux, the manual-exposure EV100 that lands them, and the
luminances of the sea, the haze and the sun glitter the render must
reproduce. On tier 0 the render path does no metering: it looks one row up
and sets a fixed EV100, which removes the histogram pass.

    .venv/bin/python swarm/lanes/lighting_exposure/physical_light_units/coastal/bake_coastal_plu.py

Models (all named, none fetched):
  haze            Koschmieder 1924: extinction(550 nm) = 3.912 / visibility
                  (2 % contrast threshold). Minus Rayleigh 0.0116 /km, times an
                  aerosol scale height, is the aerosol optical depth; Angstrom's
                  law carries it to 500 and 380 nm. Scale height and exponent
                  are UNCALIBRATED picks.
  direct normal   core.scenario.solar.illuminance_lux (Bird & Hulstrom 1981)
                  with that aerosol optical depth -- the repo's own model.
  sky diffuse     IES RP-21 clear sky (beauty_look.IES_CLEAR_DIFFUSE_KLX) plus
                  the share of the beam the haze removed and scattered forward:
                  Ba * (1 - K1) * (direct at the repo's default aerosol - direct
                  in haze) * sin(el), Ba = 0.84 and K1 = 0.1 from Bird &
                  Hulstrom 1981. MODEL, UNCALIBRATED.
  meter           ISO 2720 incident meter, C = 250: E = 2.5 * 2^EV100.
  sensor          saturation-based: scene-linear 1.0 is 1.2 * 2^EV100 cd/m2
                  (Lagarde & de Rousiers 2014).
  sea             Lambert-equivalent albedo 0.06 away from the sun (the value
                  the coastal PBR lane proposed); sun glitter peak from Cox &
                  Munk 1954 slope variance and Fresnel reflectance, n = 1.34.
  white guard     a sun-facing white surface (albedo 0.90, the airframe
                  material's AlbedoMax) under a low sun receives far more than
                  the horizontal meter reads; exposure is pulled down until it
                  sits at the ceiling. UNCALIBRATED look constants.

Every number here is a MODEL value. Nothing in this file is a rendered or
measured result; see INTEGRATION.md for the Windows command that measures.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]

PLAN_VERSION = 1
SCENARIO = "coastal"

METER_C = 250.0            # ISO 2720 incident meter (beauty_look.METER_CALIBRATION_C)
SENSOR_K = 1.2             # scene-linear 1.0 == SENSOR_K * 2^EV100 cd/m2
IES_CLEAR_DIFFUSE_KLX = (0.8, 15.5, 0.5)
SUN_OUTER_SPACE_LUX = 120000.0   # core/sky/plan.py SUN_ILLUMINANCE_LUX
GATE_EV = 0.3

KOSCHMIEDER = 3.912              # ln(1 / 0.02)
RAYLEIGH_EXT_550_PER_KM = 0.0116  # sea-level molecular extinction at 550 nm
#: Aerosol scale height, km. UNCALIBRATED pick for a marine boundary layer.
AEROSOL_SCALE_HEIGHT_KM = 1.2
#: Angstrom exponent of the sea haze. UNCALIBRATED pick (coarse salt aerosol
#: is low, continental haze is 1.3).
ANGSTROM_EXPONENT = 0.7
#: Bird & Hulstrom 1981: forward-scatter share Ba and aerosol absorptance K1.
FORWARD_SCATTER_BA = 0.84
AEROSOL_ABSORPTANCE_K1 = 0.1

#: Sea away from the glitter, Lambert-equivalent. Matches the coastal PBR lane.
WATER_ALBEDO = 0.06
WATER_IOR = 1.34
#: Cox & Munk 1954: mean-square slope = 0.003 + 0.00512 * U (m/s at 12.5 m).
WIND_M_S = 5.0
#: Brightest paint the airframe material allows (coastal PBR lane AlbedoMax).
WHITE_ALBEDO = 0.90
#: Scene-linear value a sun-facing white surface may reach. UNCALIBRATED.
WHITE_SUN_FACING_CEILING = 2.0
#: The most the white guard may darken the frame, stops. UNCALIBRATED.
WHITE_PROTECT_MAX_EV = 1.0

VISIBILITIES_KM = (8.0, 15.0, 30.0, 60.0)
ELEVATIONS_DEG = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0)
#: The row other coastal lanes should agree on when the card states no sun
#: (sun 12 deg, visibility 15 km: the coastal PBR lane's proposal).
NOMINAL = {"visibility_km": 15.0, "sun_elevation_deg": 12.0}

LOOKUP_KEYS = ("target_ev100", "meter_ev100", "sun_direct_normal_lux",
               "sky_diffuse_horizontal_lux", "global_horizontal_lux",
               "sky_mean_luminance_cd_m2", "sea_luminance_cd_m2")


def _solar():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from core.scenario import solar
    return solar


def meter_ev100(horizontal_lux: float) -> float:
    return math.log2(max(horizontal_lux, 1e-6) * 100.0 / METER_C)


def scene_linear(luminance_cd_m2: float, ev100: float) -> float:
    """The pre-tonemap pixel value of a luminance at a manual EV100."""
    return luminance_cd_m2 / (SENSOR_K * 2.0 ** ev100)


def haze(visibility_km: float) -> Dict[str, float]:
    """Extinction and aerosol optical depths for a horizontal visibility."""
    ext = KOSCHMIEDER / visibility_km
    aerosol = max(0.0, ext - RAYLEIGH_EXT_550_PER_KM)
    aod550 = aerosol * AEROSOL_SCALE_HEIGHT_KM
    return {
        "extinction_550_per_km": ext,
        "aod_550": aod550,
        "aod_500": aod550 * (500.0 / 550.0) ** -ANGSTROM_EXPONENT,
        "aod_380": aod550 * (380.0 / 550.0) ** -ANGSTROM_EXPONENT,
    }


def fresnel_unpolarised(cos_i: float, n: float = WATER_IOR) -> float:
    sin_t = math.sqrt(max(0.0, 1.0 - cos_i * cos_i)) / n
    cos_t = math.sqrt(max(0.0, 1.0 - sin_t * sin_t))
    rs = ((cos_i - n * cos_t) / (cos_i + n * cos_t)) ** 2
    rp = ((n * cos_i - cos_t) / (n * cos_i + cos_t)) ** 2
    return 0.5 * (rs + rp)


def glitter_peak_luminance(direct_normal_lux: float, elevation_deg: float) -> float:
    """Luminance of the centre of the sun's glitter path seen at the mirror
    angle: E * F * p(0) / (4 * cos(view zenith)), p(0) = 1 / (pi * sigma^2),
    isotropic Cox & Munk slopes. Shadowing is ignored, so the lowest suns
    overstate it; the value is capped at the sun's own disc luminance."""
    s = math.sin(math.radians(elevation_deg))
    sigma2 = 0.003 + 0.00512 * WIND_M_S
    lum = direct_normal_lux * fresnel_unpolarised(s) / (4.0 * s * math.pi * sigma2)
    sun_disc = direct_normal_lux / 6.8e-5  # solid angle of the sun, sr
    return min(lum, sun_disc)


def row(visibility_km: float, elevation_deg: float) -> Dict[str, Any]:
    solar = _solar()
    h = haze(visibility_km)
    s = math.sin(math.radians(elevation_deg))
    direct_ref = solar.illuminance_lux(elevation_deg).illuminance_lux
    direct = solar.illuminance_lux(elevation_deg, aod_500nm=h["aod_500"],
                                   aod_380nm=h["aod_380"]).illuminance_lux
    a, b, c = IES_CLEAR_DIFFUSE_KLX
    diffuse_clear = 1000.0 * (a + b * s ** c)
    scattered = (FORWARD_SCATTER_BA * (1.0 - AEROSOL_ABSORPTANCE_K1)
                 * max(0.0, direct_ref - direct) * s)
    diffuse = diffuse_clear + scattered
    horizontal = direct * s + diffuse
    repo_horizontal = direct_ref * s + diffuse_clear  # beauty_look.clear_sky_horizontal_lux

    ev_meter = meter_ev100(horizontal)
    # A vertical white surface facing the sun: the beam at cos(el) incidence
    # plus half the sky (uniform-sky vertical illuminance).
    white_facing_lum = WHITE_ALBEDO * (direct * math.cos(math.radians(elevation_deg))
                                       + 0.5 * diffuse) / math.pi
    over = scene_linear(white_facing_lum, ev_meter) / WHITE_SUN_FACING_CEILING
    protect = min(WHITE_PROTECT_MAX_EV, max(0.0, math.log2(over)))
    ev = ev_meter + protect

    sea_lum = WATER_ALBEDO * horizontal / math.pi
    glitter = glitter_peak_luminance(direct, elevation_deg)
    return {
        "visibility_km": visibility_km,
        "sun_elevation_deg": elevation_deg,
        "haze_extinction_550_per_km": round(h["extinction_550_per_km"], 5),
        "aerosol_optical_depth_550": round(h["aod_550"], 4),
        "sun_direct_normal_lux": round(direct, 1),
        "sky_diffuse_horizontal_lux": round(diffuse, 1),
        "global_horizontal_lux": round(horizontal, 1),
        "sun_to_sky_ratio": round(direct * s / diffuse, 3),
        "sky_mean_luminance_cd_m2": round(diffuse / math.pi, 1),
        "sea_luminance_cd_m2": round(sea_lum, 1),
        "glitter_peak_luminance_cd_m2": round(glitter, 1),
        "meter_ev100": round(ev_meter, 3),
        "white_protect_ev": round(protect, 3),
        "target_ev100": round(ev, 3),
        "repo_model_meter_ev100": round(meter_ev100(repo_horizontal), 3),
        "expected_scene_linear": {
            "grey_18_flat": round(scene_linear(0.18 * horizontal / math.pi, ev), 4),
            "white_sun_facing": round(scene_linear(white_facing_lum, ev), 4),
            "sea_away_from_sun": round(scene_linear(sea_lum, ev), 4),
            "sky_mean": round(scene_linear(diffuse / math.pi, ev), 4),
        },
        # How far over sensor saturation the glitter centre sits. Positive:
        # it clips whatever the exposure, and the water lane must clamp it.
        "glitter_over_saturation_stops": round(math.log2(max(scene_linear(glitter, ev), 1e-9)), 2),
    }


def lookup(plan: Dict[str, Any], visibility_km: float, elevation_deg: float) -> Dict[str, float]:
    """Bilinear lookup, clamped to the table; visibility is interpolated in
    1/visibility (extinction), which the light is close to linear in. This is
    the whole render-side cost: one lookup per shot, on the CPU."""
    vis, els = plan["visibilities_km"], plan["sun_elevations_deg"]
    grid = {(r["visibility_km"], r["sun_elevation_deg"]): r for r in plan["rows"]}

    def bracket(axis: List[float], v: float, f=lambda x: x):
        v = min(max(v, axis[0]), axis[-1])
        for lo, hi in zip(axis, axis[1:]):
            if lo <= v <= hi:
                return lo, hi, (f(v) - f(lo)) / (f(hi) - f(lo))
        return axis[-1], axis[-1], 0.0

    v0, v1, tv = bracket(vis, float(visibility_km), lambda x: 1.0 / x)
    e0, e1, te = bracket(els, float(elevation_deg))
    out = {}
    for key in LOOKUP_KEYS:
        lo = grid[(v0, e0)][key] * (1 - te) + grid[(v0, e1)][key] * te
        hi = grid[(v1, e0)][key] * (1 - te) + grid[(v1, e1)][key] * te
        out[key] = lo * (1 - tv) + hi * tv
    return out


def build() -> Dict[str, Any]:
    rows = [row(v, e) for v in VISIBILITIES_KM for e in ELEVATIONS_DEG]
    plan: Dict[str, Any] = {
        "version": PLAN_VERSION,
        "scenario": SCENARIO,
        "label": "visual-only; every value is a MODEL value, UNMEASURED on the render machine",
        "units": {"illuminance": "lux", "luminance": "cd/m2", "exposure": "EV100 (ISO 100)"},
        "constants": {
            "meter_calibration_c": METER_C,
            "sensor_saturation_k": SENSOR_K,
            "sun_outer_space_lux": SUN_OUTER_SPACE_LUX,
            "sun_transmittance_owner": "engine_per_pixel",
            "aerosol_scale_height_km": AEROSOL_SCALE_HEIGHT_KM,
            "angstrom_exponent": ANGSTROM_EXPONENT,
            "forward_scatter_ba": FORWARD_SCATTER_BA,
            "aerosol_absorptance_k1": AEROSOL_ABSORPTANCE_K1,
            "water_albedo": WATER_ALBEDO,
            "water_ior": WATER_IOR,
            "wind_m_s": WIND_M_S,
            "white_albedo": WHITE_ALBEDO,
            "white_sun_facing_ceiling_scene_linear": WHITE_SUN_FACING_CEILING,
            "white_protect_max_ev": WHITE_PROTECT_MAX_EV,
            "gate_ev": GATE_EV,
            "uncalibrated": ["aerosol_scale_height_km", "angstrom_exponent",
                             "haze-scattered sky diffuse term", "water_albedo", "wind_m_s",
                             "white_sun_facing_ceiling_scene_linear", "white_protect_max_ev"],
        },
        "visibilities_km": list(VISIBILITIES_KM),
        "sun_elevations_deg": list(ELEVATIONS_DEG),
        "rows": rows,
    }
    plan["nominal"] = dict(NOMINAL, **{k: round(v, 3) for k, v in lookup(
        plan, NOMINAL["visibility_km"], NOMINAL["sun_elevation_deg"]).items()})
    return plan


CURVE_COLUMNS = ("visibility_km", "sun_elevation_deg", "target_ev100",
                 "sun_direct_normal_lux", "sky_diffuse_horizontal_lux",
                 "sea_luminance_cd_m2", "haze_extinction_550_per_km")


def write(out_dir: Path = LANE) -> Dict[str, str]:
    plan = build()
    (out_dir / "coastal_plu.json").write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
    # The curve a UE CurveTable / the commandlet reads: one line per row.
    with (out_dir / "coastal_plu_curve.csv").open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(CURVE_COLUMNS)
        for r in plan["rows"]:
            w.writerow([r[k] for k in CURVE_COLUMNS])
    return {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
            for name in ("coastal_plu.json", "coastal_plu_curve.csv")}


if __name__ == "__main__":
    for name, digest in write().items():
        print(f"{digest}  {name}")
