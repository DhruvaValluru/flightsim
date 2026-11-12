"""Offline bake (Mac): physical light units for the alpine scenario.

Visual-only. Writes ``alpine_plu.json`` and ``alpine_plu_curve.csv`` next to
this file: for every (altitude, sun elevation) the clear-sky illuminances in
lux, the manual-exposure EV100 that lands them, and the snow luminances the
render must reproduce. The render path does no metering at all on tier 0: it
looks one row up and sets a fixed EV100, which removes the histogram pass.

    .venv/bin/python swarm/lanes/lighting_exposure/physical_light_units/alpine/bake_alpine_plu.py

Models (all named, none fetched):
  direct normal   core.scenario.solar.illuminance_lux (Bird & Hulstrom 1981,
                  ISA pressure at altitude) -- the repo's own model, imported.
  sky diffuse     IES RP-21 clear sky E = A + B sin(el)^C klx (the constants
                  core/scene/beauty_look.py IES_CLEAR_DIFFUSE_KLX states),
                  scaled by p/p0: single-scattered skylight follows the air
                  column above the surface. MODEL, UNCALIBRATED.
  meter           ISO 2720 incident meter, C = 250: E = 2.5 * 2^EV100.
  sensor          saturation-based: scene-linear 1.0 is 1.2 * 2^EV100 cd/m2
                  (Lagarde & de Rousiers 2014, "Moving Frostbite to PBR",
                  the convention UE's manual exposure follows).
  snow            Lambertian, visible albedo 0.90 (inside Wiscombe & Warren
                  1980's range for clean snow). UNCALIBRATED pick.

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
SCENARIO = "alpine"

#: ISO 2720 incident-light meter constant (lux * s), the repo's METER_CALIBRATION_C.
METER_C = 250.0
#: Saturation-based sensor: scene-linear 1.0 == SENSOR_K * 2^EV100 cd/m2.
SENSOR_K = 1.2
#: IES RP-21 clear-sky horizontal diffuse, klx (beauty_look.IES_CLEAR_DIFFUSE_KLX).
IES_CLEAR_DIFFUSE_KLX = (0.8, 15.5, 0.5)
#: ISA sea-level pressure, hPa.
P0_HPA = 1013.25
#: The beauty sun's outer-space illuminance (core/sky/plan.py SUN_ILLUMINANCE_LUX);
#: the engine's per-pixel transmittance dims it. Restated for the record and
#: test-checked against the repo's constant.
SUN_OUTER_SPACE_LUX = 120000.0

#: Clean alpine snow, visible albedo. UNCALIBRATED (Wiscombe & Warren 1980 range).
SNOW_ALBEDO = 0.90
#: Scene-linear value (before the tonemapper) that sun-facing snow may reach
#: before exposure is pulled down. 2.0 is one stop over sensor saturation, in
#: the filmic shoulder but short of flat white. UNCALIBRATED look constant.
SNOW_SUN_FACING_CEILING = 2.0
#: The most the snow guard may darken the frame, stops. UNCALIBRATED.
SNOW_PROTECT_MAX_EV = 1.0
#: The scenario gate: exposure within this many stops of the table.
GATE_EV = 0.3

#: Zermatt valley floor, glacier plateau, Matterhorn summit, the scenario's
#: flight level (scripts/run_test_scenarios.py scenario 11: "at 5000 m").
ALTITUDES_M = (1600.0, 3000.0, 4478.0, 5000.0)
#: Up to the highest sun the Matterhorn sees (90 - 45.98 + 23.44 = 67.5 deg).
ELEVATIONS_DEG = (2.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 60.0, 67.0)
#: The row other alpine lanes should agree on when the card states no sun.
NOMINAL = {"altitude_m": 5000.0, "sun_elevation_deg": 30.0}


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


def row(altitude_m: float, elevation_deg: float) -> Dict[str, Any]:
    solar = _solar()
    pressure = solar.isa_pressure_hpa(altitude_m)
    ratio = pressure / P0_HPA
    s = math.sin(math.radians(elevation_deg))
    direct_normal = solar.illuminance_lux(elevation_deg, altitude_m=altitude_m).illuminance_lux
    a, b, c = IES_CLEAR_DIFFUSE_KLX
    diffuse_sea = 1000.0 * (a + b * s ** c)
    diffuse = diffuse_sea * ratio
    horizontal = direct_normal * s + diffuse
    repo_horizontal = direct_normal * s + diffuse_sea  # beauty_look.clear_sky_horizontal_lux

    ev_meter = meter_ev100(horizontal)
    # Snow whose normal faces the sun: full direct beam plus the sky.
    snow_facing_lum = SNOW_ALBEDO * (direct_normal + diffuse) / math.pi
    snow_flat_lum = SNOW_ALBEDO * horizontal / math.pi
    snow_shade_lum = SNOW_ALBEDO * diffuse / math.pi
    over = scene_linear(snow_facing_lum, ev_meter) / SNOW_SUN_FACING_CEILING
    protect = min(SNOW_PROTECT_MAX_EV, max(0.0, math.log2(over)))
    ev = ev_meter + protect

    return {
        "altitude_m": altitude_m,
        "sun_elevation_deg": elevation_deg,
        "pressure_hpa": round(pressure, 2),
        "sun_direct_normal_lux": round(direct_normal, 1),
        "sky_diffuse_horizontal_lux": round(diffuse, 1),
        "global_horizontal_lux": round(horizontal, 1),
        "sun_to_sky_ratio": round(direct_normal * s / diffuse, 3),
        "sky_mean_luminance_cd_m2": round(diffuse / math.pi, 1),
        "snow_bounce_luminance_cd_m2": round(snow_flat_lum, 1),
        "meter_ev100": round(ev_meter, 3),
        "snow_protect_ev": round(protect, 3),
        "target_ev100": round(ev, 3),
        "repo_model_meter_ev100": round(meter_ev100(repo_horizontal), 3),
        "expected_scene_linear": {
            "grey_18_flat": round(scene_linear(0.18 * horizontal / math.pi, ev), 4),
            "snow_flat_sunlit": round(scene_linear(snow_flat_lum, ev), 4),
            "snow_sun_facing": round(scene_linear(snow_facing_lum, ev), 4),
            "snow_in_shade": round(scene_linear(snow_shade_lum, ev), 4),
        },
    }


def lookup(plan: Dict[str, Any], altitude_m: float, elevation_deg: float) -> Dict[str, float]:
    """Bilinear lookup of the exposure and light columns, clamped to the table.
    This is the whole render-side cost: one lookup per shot, on the CPU."""
    alts, els = plan["altitudes_m"], plan["sun_elevations_deg"]
    grid = {(r["altitude_m"], r["sun_elevation_deg"]): r for r in plan["rows"]}

    def bracket(axis: List[float], v: float):
        v = min(max(v, axis[0]), axis[-1])
        for lo, hi in zip(axis, axis[1:]):
            if lo <= v <= hi:
                return lo, hi, (v - lo) / (hi - lo)
        return axis[-1], axis[-1], 0.0

    a0, a1, ta = bracket(alts, float(altitude_m))
    e0, e1, te = bracket(els, float(elevation_deg))
    out = {}
    for key in ("target_ev100", "meter_ev100", "sun_direct_normal_lux",
                "sky_diffuse_horizontal_lux", "global_horizontal_lux",
                "snow_bounce_luminance_cd_m2", "sky_mean_luminance_cd_m2"):
        lo = grid[(a0, e0)][key] * (1 - te) + grid[(a0, e1)][key] * te
        hi = grid[(a1, e0)][key] * (1 - te) + grid[(a1, e1)][key] * te
        out[key] = lo * (1 - ta) + hi * ta
    return out


def build() -> Dict[str, Any]:
    rows = [row(a, e) for a in ALTITUDES_M for e in ELEVATIONS_DEG]
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
            "snow_albedo": SNOW_ALBEDO,
            "snow_sun_facing_ceiling_scene_linear": SNOW_SUN_FACING_CEILING,
            "snow_protect_max_ev": SNOW_PROTECT_MAX_EV,
            "gate_ev": GATE_EV,
            "uncalibrated": ["snow_albedo", "snow_sun_facing_ceiling_scene_linear",
                             "snow_protect_max_ev", "sky diffuse p/p0 scaling"],
        },
        "altitudes_m": list(ALTITUDES_M),
        "sun_elevations_deg": list(ELEVATIONS_DEG),
        "rows": rows,
    }
    plan["nominal"] = dict(NOMINAL, **{k: round(v, 3) for k, v in lookup(
        plan, NOMINAL["altitude_m"], NOMINAL["sun_elevation_deg"]).items()})
    return plan


def write(out_dir: Path = LANE) -> Dict[str, str]:
    plan = build()
    text = json.dumps(plan, indent=1, sort_keys=True) + "\n"
    (out_dir / "alpine_plu.json").write_text(text)
    # The curve a UE CurveTable / the commandlet reads: one line per row.
    with (out_dir / "alpine_plu_curve.csv").open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(["altitude_m", "sun_elevation_deg", "target_ev100", "sky_diffuse_horizontal_lux",
                    "snow_bounce_luminance_cd_m2", "sun_direct_normal_lux"])
        for r in plan["rows"]:
            w.writerow([r["altitude_m"], r["sun_elevation_deg"], r["target_ev100"],
                        r["sky_diffuse_horizontal_lux"], r["snow_bounce_luminance_cd_m2"],
                        r["sun_direct_normal_lux"]])
    return {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
            for name in ("alpine_plu.json", "alpine_plu_curve.csv")}


if __name__ == "__main__":
    for name, digest in write().items():
        print(f"{digest}  {name}")
