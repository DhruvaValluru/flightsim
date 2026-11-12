"""Offline bake (Mac): sun and exposure against time of day, coastal scenario.

Visual-only. Writes ``coastal_sun_tod.json``, ``coastal_sun_tod_curve.csv``
(keyed by sun elevation) and ``coastal_day_curve.csv`` (a stated site and
date, keyed by clock time) next to this file. The render path does no
metering on tier 0: one CPU lookup per shot gives a fixed manual EV100.

    .venv/bin/python swarm/lanes/lighting_exposure/sun_time_of_day/coastal/bake_coastal_sun_tod.py

Models (all named, none fetched):
  sun position    core.scenario.solar.solar_position (Meeus 1998), imported.
  direct normal   core.scenario.solar.illuminance_lux (Bird & Hulstrom 1981)
                  with a MARINE atmosphere: aerosol optical depth 0.25 at
                  500 nm, 0.287 at 380 nm (Angstrom exponent 0.5), water
                  3.0 cm. STATED, UNCALIBRATED.
  sea haze        Koschmieder: visibility = 3.912 / extinction, the aerosol
                  in a 1 km well-mixed marine layer; AOD 0.25 gives ~15 km.
  sky diffuse     IES RP-21 clear sky E = A + B sin(el)^C klx (the constants
                  core/scene/beauty_look.py states) plus HAZE_FORWARD_SHARE
                  of the direct beam the extra marine aerosol removed (it is
                  scattered, mostly forward, not absorbed). MODEL, UNCALIBRATED.
  sun colour      5778 K Planck spectrum through Rayleigh (Hansen & Travis
                  1974) and Angstrom aerosol optical depth at the Kasten air
                  mass; CIE 1931 xy by the Wyman, Sloan & Shirley 2013
                  analytic fit; CCT by McCamy 1992. Ozone is left out.
                  REFERENCE ONLY for lanes that tint by hand: the engine's
                  SkyAtmosphere already reddens the directional light.
  meter           ISO 2720 incident meter, C = 250.
  sensor          scene-linear 1.0 == 1.2 * 2^EV100 cd/m2 (Lagarde & de
                  Rousiers 2014).
  white guard     a white hull / foam / sand face (albedo 0.80) turned to the
                  low sun may reach scene-linear 2.0; exposure is pulled down
                  by at most 0.7 stop to hold it. UNCALIBRATED look constants.
  sea glitter     Cox & Munk 1954 slope variance at 5 m/s, Fresnel n = 1.34:
                  peak glitter luminance, recorded so nobody tries to expose
                  for it (it clips, as it does on film).

Every number is a MODEL value; nothing here is a rendered or measured result.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]

PLAN_VERSION = 1
SCENARIO = "coastal"

METER_C = 250.0
SENSOR_K = 1.2
IES_CLEAR_DIFFUSE_KLX = (0.8, 15.5, 0.5)
SUN_OUTER_SPACE_LUX = 120000.0
GATE_EV = 0.3

#: Marine boundary-layer atmosphere. STATED, UNCALIBRATED.
MARINE_AOD_500NM = 0.25
MARINE_ANGSTROM = 0.5
MARINE_AOD_380NM = round(MARINE_AOD_500NM * (380.0 / 500.0) ** -MARINE_ANGSTROM, 3)
MARINE_WATER_CM = 3.0
MARINE_LAYER_KM = 1.0
RAYLEIGH_EXTINCTION_550_PER_KM = 0.0116
#: Share of the aerosol-removed direct beam that reaches the ground as sky light.
HAZE_FORWARD_SHARE = 0.6

SUN_PLANCK_K = 5778.0
WHITE_ALBEDO = 0.80
WHITE_SUN_FACING_CEILING = 2.0
WHITE_PROTECT_MAX_EV = 0.7
SEA_ALBEDO = 0.06
WATER_IOR = 1.34
COX_MUNK_WIND_M_S = 5.0

ELEVATIONS_DEG = (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0)
#: The row the other coastal lanes already proposed (sun 12 deg, low over the sea).
NOMINAL_ELEVATION_DEG = 12.0
#: Stated site for the clock-time curve: a west-facing Pacific shore, so the
#: evening sun is over the water. Any shot with its own place and time uses
#: sun_for_time() instead.
SITE = {"name": "Half Moon Bay, California (stated example site)", "latitude_deg": 37.50,
        "longitude_deg": -122.50, "year": 2026, "day_of_year": 265, "utc_offset_h": -7.0}

LOOKUP_KEYS = ("target_ev100", "meter_ev100", "sun_direct_normal_lux",
               "sky_diffuse_horizontal_lux", "global_horizontal_lux",
               "sun_colour_temperature_k", "sun_to_sky_ratio")


def _solar():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from core.scenario import solar
    return solar


def meter_ev100(horizontal_lux: float) -> float:
    return math.log2(max(horizontal_lux, 1e-6) * 100.0 / METER_C)


def scene_linear(luminance_cd_m2: float, ev100: float) -> float:
    return luminance_cd_m2 / (SENSOR_K * 2.0 ** ev100)


def visibility_km(aod_500: float = MARINE_AOD_500NM) -> float:
    aod_550 = aod_500 * (550.0 / 500.0) ** -MARINE_ANGSTROM
    return 3.912 / (aod_550 / MARINE_LAYER_KM + RAYLEIGH_EXTINCTION_550_PER_KM)


# ---- sun colour ---------------------------------------------------------

def _g(lam: float, mu: float, s1: float, s2: float) -> float:
    s = s1 if lam < mu else s2
    return math.exp(-0.5 * ((lam - mu) / s) ** 2)


def cie_xyz_bar(lam_nm: float):
    """Wyman, Sloan & Shirley 2013 multi-lobe fit to the CIE 1931 observer."""
    x = (1.056 * _g(lam_nm, 599.8, 37.9, 31.0) + 0.362 * _g(lam_nm, 442.0, 16.0, 26.7)
         - 0.065 * _g(lam_nm, 501.1, 20.4, 26.2))
    y = 0.821 * _g(lam_nm, 568.8, 46.9, 40.5) + 0.286 * _g(lam_nm, 530.9, 16.3, 31.1)
    z = 1.217 * _g(lam_nm, 437.0, 11.8, 36.0) + 0.681 * _g(lam_nm, 459.0, 26.0, 13.8)
    return x, y, z


def _planck(lam_nm: float, kelvin: float) -> float:
    lam = lam_nm * 1e-9
    return 1.0 / (lam ** 5 * (math.exp(0.014387769 / (lam * kelvin)) - 1.0))


def rayleigh_tau(lam_nm: float, pressure_ratio: float = 1.0) -> float:
    u = lam_nm / 1000.0
    return pressure_ratio * 0.008569 * u ** -4 * (1.0 + 0.0113 * u ** -2 + 0.00013 * u ** -4)


def aerosol_tau(lam_nm: float, aod_500: float = MARINE_AOD_500NM) -> float:
    return aod_500 * (lam_nm / 500.0) ** -MARINE_ANGSTROM


def sun_colour(elevation_deg: float, aod_500: float = MARINE_AOD_500NM) -> Dict[str, Any]:
    """xy, CCT and a max-normalised linear sRGB tint of the direct beam."""
    m = _solar().kasten_air_mass(90.0 - elevation_deg)
    X = Y = Z = 0.0
    for lam in range(380, 781, 5):
        e = _planck(lam, SUN_PLANCK_K) * math.exp(-m * (rayleigh_tau(lam) + aerosol_tau(lam, aod_500)))
        xb, yb, zb = cie_xyz_bar(lam)
        X, Y, Z = X + e * xb, Y + e * yb, Z + e * zb
    x, y = X / (X + Y + Z), Y / (X + Y + Z)
    n = (x - 0.3320) / (0.1858 - y)
    cct = 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z
    g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z
    b = 0.0557 * X - 0.2040 * Y + 1.0570 * Z
    top = max(r, g, b)
    return {"xy": [round(x, 4), round(y, 4)], "cct_k": round(cct, 0),
            "linear_srgb_tint": [round(max(c, 0.0) / top, 4) for c in (r, g, b)]}


# ---- sea glitter --------------------------------------------------------

def fresnel_unpolarised(incidence_deg: float, n: float = WATER_IOR) -> float:
    ci = math.cos(math.radians(incidence_deg))
    st = math.sin(math.radians(incidence_deg)) / n
    ct = math.sqrt(max(0.0, 1.0 - st * st))
    rs = ((ci - n * ct) / (ci + n * ct)) ** 2
    rp = ((n * ci - ct) / (n * ci + ct)) ** 2
    return 0.5 * (rs + rp)


def glitter_peak_luminance(direct_normal_lux: float, elevation_deg: float) -> float:
    """Cox & Munk 1954: specular-direction glitter luminance, isotropic slopes."""
    sigma2 = 0.003 + 0.00512 * COX_MUNK_WIND_M_S
    cos_v = math.sin(math.radians(elevation_deg))        # viewer mirrors the sun
    return (direct_normal_lux * fresnel_unpolarised(90.0 - elevation_deg)
            / (4.0 * math.pi * sigma2 * cos_v))


# ---- the table ----------------------------------------------------------

def row(elevation_deg: float) -> Dict[str, Any]:
    solar = _solar()
    s = math.sin(math.radians(elevation_deg))
    marine = solar.illuminance_lux(elevation_deg, aod_500nm=MARINE_AOD_500NM,
                                   aod_380nm=MARINE_AOD_380NM, water_cm=MARINE_WATER_CM).illuminance_lux
    clear = solar.illuminance_lux(elevation_deg).illuminance_lux
    a, b, c = IES_CLEAR_DIFFUSE_KLX
    ies = 1000.0 * (a + b * s ** c)
    diffuse = ies + HAZE_FORWARD_SHARE * max(0.0, clear - marine) * s
    horizontal = marine * s + diffuse
    repo_horizontal = clear * s + ies                       # beauty_look.clear_sky_horizontal_lux

    ev_meter = meter_ev100(horizontal)
    white_facing = WHITE_ALBEDO * (marine + diffuse) / math.pi
    over = scene_linear(white_facing, ev_meter) / WHITE_SUN_FACING_CEILING
    protect = min(WHITE_PROTECT_MAX_EV, max(0.0, math.log2(over)))
    ev = ev_meter + protect
    colour = sun_colour(elevation_deg)
    glitter = glitter_peak_luminance(marine, elevation_deg)
    return {
        "sun_elevation_deg": elevation_deg,
        "sun_direct_normal_lux": round(marine, 1),
        "sun_direct_normal_lux_repo_clear": round(clear, 1),
        "sky_diffuse_horizontal_lux": round(diffuse, 1),
        "global_horizontal_lux": round(horizontal, 1),
        "sun_to_sky_ratio": round(marine * s / diffuse, 3),
        "sky_mean_luminance_cd_m2": round(diffuse / math.pi, 1),
        "sun_colour_temperature_k": colour["cct_k"],
        "sun_xy": colour["xy"],
        "sun_linear_srgb_tint": colour["linear_srgb_tint"],
        "meter_ev100": round(ev_meter, 3),
        "white_protect_ev": round(protect, 3),
        "target_ev100": round(ev, 3),
        "repo_model_meter_ev100": round(meter_ev100(repo_horizontal), 3),
        "sea_glitter_peak_cd_m2": round(glitter, 0),
        "expected_scene_linear": {
            "grey_18_flat": round(scene_linear(0.18 * horizontal / math.pi, ev), 4),
            "white_sun_facing": round(scene_linear(white_facing, ev), 4),
            "sea_diffuse": round(scene_linear(SEA_ALBEDO * horizontal / math.pi, ev), 4),
            "sea_glitter_peak": round(scene_linear(glitter, ev), 2),
        },
    }


def lookup(plan: Dict[str, Any], elevation_deg: float) -> Dict[str, float]:
    """Linear lookup, clamped to the table. The whole render-side cost."""
    rows: List[Dict[str, Any]] = plan["rows"]
    v = min(max(float(elevation_deg), rows[0]["sun_elevation_deg"]), rows[-1]["sun_elevation_deg"])
    for lo, hi in zip(rows, rows[1:]):
        if lo["sun_elevation_deg"] <= v <= hi["sun_elevation_deg"]:
            t = (v - lo["sun_elevation_deg"]) / (hi["sun_elevation_deg"] - lo["sun_elevation_deg"])
            return {k: lo[k] * (1 - t) + hi[k] * t for k in LOOKUP_KEYS}
    return {k: rows[-1][k] for k in LOOKUP_KEYS}


def sun_for_time(plan: Dict[str, Any], latitude_deg: float, longitude_deg: float, year: int,
                 day_of_year: int, hour_utc: float) -> Optional[Dict[str, float]]:
    """Clock time -> sun direction + the table row. None below the lowest row
    (2 deg): the repo's elevation band stands there, twilight is not modelled."""
    pos = _solar().solar_position(latitude_deg, longitude_deg, year, day_of_year, hour_utc)
    if pos.elevation_deg < plan["rows"][0]["sun_elevation_deg"]:
        return None
    out = lookup(plan, pos.elevation_deg)
    out["sun_elevation_deg"] = pos.elevation_deg
    out["sun_azimuth_deg"] = pos.azimuth_deg
    return out


def day_curve(plan: Dict[str, Any], site: Dict[str, Any] = SITE, step_h: float = 0.25) -> List[Dict[str, Any]]:
    out = []
    for i in range(int(24 / step_h)):
        local = i * step_h
        utc = local - site["utc_offset_h"]
        doy, hour = site["day_of_year"] + int(utc // 24), utc % 24
        r = sun_for_time(plan, site["latitude_deg"], site["longitude_deg"], site["year"], doy, hour)
        if r is None:
            continue
        out.append({"local_hour": local, "sun_elevation_deg": round(r["sun_elevation_deg"], 2),
                    "sun_azimuth_deg": round(r["sun_azimuth_deg"], 2),
                    "target_ev100": round(r["target_ev100"], 3),
                    "sun_colour_temperature_k": round(r["sun_colour_temperature_k"], 0),
                    "sun_direct_normal_lux": round(r["sun_direct_normal_lux"], 0),
                    "sky_diffuse_horizontal_lux": round(r["sky_diffuse_horizontal_lux"], 0)})
    return out


def build() -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "version": PLAN_VERSION,
        "scenario": SCENARIO,
        "label": "visual-only; every value is a MODEL value, UNMEASURED on the render machine",
        "units": {"illuminance": "lux", "luminance": "cd/m2", "exposure": "EV100 (ISO 100)"},
        "constants": {
            "meter_calibration_c": METER_C, "sensor_saturation_k": SENSOR_K,
            "sun_outer_space_lux": SUN_OUTER_SPACE_LUX,
            "sun_transmittance_owner": "engine_per_pixel",
            "marine_aod_500nm": MARINE_AOD_500NM, "marine_aod_380nm": MARINE_AOD_380NM,
            "marine_angstrom_exponent": MARINE_ANGSTROM, "marine_water_cm": MARINE_WATER_CM,
            "marine_layer_km": MARINE_LAYER_KM,
            "sea_haze_visibility_km": round(visibility_km(), 1),
            "haze_forward_share": HAZE_FORWARD_SHARE,
            "white_albedo": WHITE_ALBEDO,
            "white_sun_facing_ceiling_scene_linear": WHITE_SUN_FACING_CEILING,
            "white_protect_max_ev": WHITE_PROTECT_MAX_EV,
            "sea_albedo": SEA_ALBEDO, "water_ior": WATER_IOR,
            "cox_munk_wind_m_s": COX_MUNK_WIND_M_S, "gate_ev": GATE_EV,
            "uncalibrated": ["marine_aod_500nm", "marine_angstrom_exponent", "marine_water_cm",
                             "marine_layer_km", "haze_forward_share", "white_albedo",
                             "white_sun_facing_ceiling_scene_linear", "white_protect_max_ev",
                             "sea_albedo", "cox_munk_wind_m_s"],
        },
        "sun_elevations_deg": list(ELEVATIONS_DEG),
        "rows": [row(e) for e in ELEVATIONS_DEG],
        "site": dict(SITE),
    }
    plan["nominal"] = {"sun_elevation_deg": NOMINAL_ELEVATION_DEG,
                       **{k: round(v, 3) for k, v in lookup(plan, NOMINAL_ELEVATION_DEG).items()}}
    curve = day_curve(plan)
    evening = [r for r in curve if r["local_hour"] > 12 and r["sun_elevation_deg"] <= NOMINAL_ELEVATION_DEG]
    plan["nominal"]["site_evening_local_hour"] = evening[0]["local_hour"] if evening else None
    plan["nominal"]["site_evening_sun_azimuth_deg"] = evening[0]["sun_azimuth_deg"] if evening else None
    return plan


def _csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    with path.open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([r[c] for c in columns])


def write(out_dir: Path = LANE) -> Dict[str, str]:
    plan = build()
    (out_dir / "coastal_sun_tod.json").write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n")
    _csv(out_dir / "coastal_sun_tod_curve.csv", plan["rows"],
         ["sun_elevation_deg", "target_ev100", "sun_direct_normal_lux",
          "sky_diffuse_horizontal_lux", "sun_colour_temperature_k"])
    _csv(out_dir / "coastal_day_curve.csv", day_curve(plan),
         ["local_hour", "sun_elevation_deg", "sun_azimuth_deg", "target_ev100",
          "sun_colour_temperature_k", "sun_direct_normal_lux", "sky_diffuse_horizontal_lux"])
    return {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
            for name in ("coastal_sun_tod.json", "coastal_sun_tod_curve.csv", "coastal_day_curve.csv")}


if __name__ == "__main__":
    for name, digest in write().items():
        print(f"{digest}  {name}")
