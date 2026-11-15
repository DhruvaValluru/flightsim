#!/usr/bin/env python3
"""lighting_exposure.eye_adaptation.night_ifr: the offline bake (Mac, stdlib only).

The calibrated look for a night scene is the project's own rule,
core/sky/plan.py ev100_for(): one EV100 for the clip, from the moon's and the
night sky's horizontal illuminance, falling at half the meter's rate below
400 lx. The gate is +/-0.3 EV of that number.

So the "eye" here is a BOUNDED excursion around the look, computed on the CPU
and applied as a manual exposure: no GPU histogram, no readback, nothing for
the laptop to lose a device over. It opens by up to 0.25 EV inside the cloud
deck, with a fast close and a slow open. It WOULD close by up to 0.25 EV as
the approach and runway lights fill the eye (Allard's law), but that needs
the lights' candela, and the project has none: core/scene/runway.py
PHOTOMETRY["candela"] is None ("named as missing, never invented"). So this
bake carries NO light intensities and its curve has no light term; the
light sum is a function that takes the intensities as an argument, and the
bake states the eye illuminance at which the eye would start and finish
closing, which does not depend on them.

Writes baked/night_ifr_eye.json and baked/night_ifr_eye_curve.csv.
Deterministic. UNMEASURED: no frame was rendered.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
BAKED = HERE / "baked"

# -- copied from core/sky/plan.py; the test cross-checks them ----------------
DAYLIGHT_LUX = 400.0
NIGHT_SKY_LUX = 5.0e-4
MOON_GROUND_LUX = 0.27          # full moon at the ground, normal incidence
CAMERA_EV100 = math.log2(4.0 ** 2 * 60.0)   # f/4, 1/60 s, ISO 100
EV100_RANGE = (-4.0, 16.0)

GATE_EV = 0.3
#: The eye never leaves the look by more than this; 0.05 EV inside the gate.
MAX_EXCURSION_EV = 0.25

# -- the scenario. VISUAL-ONLY choices, not weather or airport data ----------
MOON_RELATIVE_BRIGHTNESS = 1.0   # full
MOON_ELEVATION_DEG = 40.0
DECK_TOP_M = 600.0               # AGL
DECK_BASE_M = 90.0               # AGL (about 300 ft)
DECK_TRANSMITTANCE = 0.25        # the project's storm deck fraction, reused
VISIBILITY_MOR_M = 2400.0        # below the deck
GLIDESLOPE_DEG = 3.0
THRESHOLD_CROSSING_HEIGHT_M = 15.0
GROUND_SPEED_M_S = 72.0          # 140 kt
START_DISTANCE_M = 12000.0

# -- the eye's timing. VISUAL-ONLY --------------------------------------------
TAU_CLOSE_S = 0.5                # towards brighter
TAU_OPEN_S = 4.0                 # towards darker
SIM_DT_S = 1.0 / 30.0
CSV_EVERY_S = 0.5


def ev100_for(horizontal_lux: float) -> float:
    """core/sky/plan.py ev100_for, restated."""
    e = max(horizontal_lux, 1e-6)
    if e >= DAYLIGHT_LUX:
        ev = math.log2(e / 2.5)
    else:
        ev = math.log2(DAYLIGHT_LUX / 2.5) + 0.5 * math.log2(e / DAYLIGHT_LUX)
    return min(max(ev, EV100_RANGE[0]), EV100_RANGE[1])


def look_lux(moon_rel: float = MOON_RELATIVE_BRIGHTNESS,
             moon_el_deg: float = MOON_ELEVATION_DEG) -> float:
    moon = MOON_GROUND_LUX * moon_rel * math.sin(math.radians(moon_el_deg)) if moon_el_deg > 0 else 0.0
    return moon + NIGHT_SKY_LUX


def extinction_per_m(mor_m: float = VISIBILITY_MOR_M) -> float:
    """Koschmieder with the 5 % contrast threshold of the MOR definition."""
    return math.log(20.0) / mor_m


def eye_lux_from_lights(distance_m: float, height_m: float, sigma: float,
                        field: List[Dict[str, float]]) -> float:
    """Allard's law, E = I exp(-sigma d) / d^2, summed over the lights ahead.

    ``field`` is the caller's: dicts of x (m along the runway from the
    threshold, negative = approach side), y (m across) and cd. This lane
    ships no such list (no sourced photometry).
    """
    total = 0.0
    for light in field:
        dx = light["x"] + distance_m          # the eye is at x = -distance
        if dx <= 1.0:
            continue
        d = math.sqrt(dx * dx + light["y"] ** 2 + height_m ** 2)
        total += light["cd"] * math.exp(-sigma * d) / (d * d)
    return total


def phase(height_m: float) -> str:
    if height_m > DECK_TOP_M:
        return "above_deck"
    if height_m > DECK_BASE_M:
        return "in_cloud"
    return "below_deck"


def target_offset_ev(eye_lux: float, reference_lux: float) -> float:
    """Half-rate, as the look's own rule below 400 lx, clamped to the excursion."""
    raw = 0.5 * math.log2(max(eye_lux, 1e-9) / reference_lux)
    return min(max(raw, -MAX_EXCURSION_EV), MAX_EXCURSION_EV)


def step(offset: float, target: float, dt: float) -> float:
    """One frame of the eye: exponential, fast to close, slow to open."""
    tau = TAU_CLOSE_S if target > offset else TAU_OPEN_S
    return target + (offset - target) * math.exp(-dt / tau)


def curve(field: Optional[List[Dict[str, float]]] = None) -> List[Dict[str, Any]]:
    """The canonical approach. ``field`` None (the bake): no light term."""
    ref = look_lux()
    ev_look = ev100_for(ref)
    sigma = extinction_per_m()
    tan_gs = math.tan(math.radians(GLIDESLOPE_DEG))
    rows, offset, t = [], 0.0, 0.0
    frames_per_row = int(round(CSV_EVERY_S / SIM_DT_S))
    n = int(START_DISTANCE_M / GROUND_SPEED_M_S / SIM_DT_S) + 1
    for i in range(n):
        t = i * SIM_DT_S
        dist = max(START_DISTANCE_M - GROUND_SPEED_M_S * t, 0.0)
        h = dist * tan_gs + THRESHOLD_CROSSING_HEIGHT_M
        ph = phase(h)
        ambient = ref if ph == "above_deck" else ref * DECK_TRANSMITTANCE
        lit = eye_lux_from_lights(dist, h, sigma, field) if field and ph == "below_deck" else 0.0
        target = target_offset_ev(ambient + lit, ref)
        if i:
            offset = step(offset, target, SIM_DT_S)
        if i % frames_per_row == 0:
            ev = ev_look + offset
            rows.append({
                "t_s": round(t, 3), "distance_m": round(dist, 1), "height_m": round(h, 1),
                "phase": ph, "eye_lux_ambient": float(f"{ambient:.6g}"),
                "eye_lux_lights": float(f"{lit:.6g}"),
                "target_offset_ev": round(target, 4), "offset_ev": round(offset, 4),
                "ev100": round(ev, 4), "ue_exposure_bias": round(CAMERA_EV100 - ev, 4),
            })
    return rows


def build() -> Dict[str, Any]:
    ref = look_lux()
    ev = ev100_for(ref)
    rows = curve()
    look_table = [
        {"moon_relative_brightness": rel, "moon_elevation_deg": el,
         "horizontal_lux": float(f"{look_lux(rel, el):.6g}"),
         "ev100": round(ev100_for(look_lux(rel, el)), 4)}
        for rel in (0.0, 0.1, 0.5, 1.0) for el in (10.0, 20.0, 40.0, 60.0)
    ]
    lo, hi = round(ev - MAX_EXCURSION_EV, 4), round(ev + MAX_EXCURSION_EV, 4)
    return {
        "item": "lighting_exposure.eye_adaptation.night_ifr",
        "status": "UNMEASURED: computed on the Mac, no frame rendered",
        "calibrated_look": {
            "rule": "core/sky/plan.py ev100_for(moon + night sky horizontal lux), constant over the clip",
            "horizontal_lux": float(f"{ref:.6g}"),
            "ev100": round(ev, 4),
            "camera_ev100": round(CAMERA_EV100, 4),
            "ue_exposure_bias": round(CAMERA_EV100 - ev, 4),
            "saturation_luminance_cd_m2": round(1.2 * 2.0 ** ev, 3),
            "gate_ev": GATE_EV,
        },
        "eye": {
            "max_excursion_ev": MAX_EXCURSION_EV,
            "ev100_min": lo, "ev100_max": hi,
            "tau_close_s": TAU_CLOSE_S, "tau_open_s": TAU_OPEN_S,
            "target": "clamp(0.5 * log2(eye_lux / look_lux), -0.25, +0.25); "
                      "eye_lux = ambient (x deck transmittance in or under the deck) + Allard sum of lights "
                      "(zero in this bake)",
            "step": "offset = target + (offset - target) * exp(-dt / tau); tau = close if target > offset else open",
            "timing_basis": "VISUAL-ONLY",
        },
        "scenario": {
            "basis": "VISUAL-ONLY choices, not weather or airport data",
            "moon_relative_brightness": MOON_RELATIVE_BRIGHTNESS,
            "moon_elevation_deg": MOON_ELEVATION_DEG,
            "deck_top_m_agl": DECK_TOP_M, "deck_base_m_agl": DECK_BASE_M,
            "deck_transmittance": DECK_TRANSMITTANCE,
            "visibility_mor_m": VISIBILITY_MOR_M,
            "extinction_per_m": float(f"{extinction_per_m():.6g}"),
            "glideslope_deg": GLIDESLOPE_DEG, "ground_speed_m_s": GROUND_SPEED_M_S,
            "start_distance_m": START_DISTANCE_M,
        },
        "runway_lights": {
            "status": "NO INTENSITIES: core/scene/runway.py PHOTOMETRY candela is None; "
                      "the baked curve has no light term and no closing distance is claimed",
            "formula": "eye_lux = sum over lights ahead of cd * exp(-sigma * d) / d^2 (Allard)",
            # Independent of any candela figure: where the target crosses 0 and the clamp.
            "eye_lux_from_lights_to_return_to_the_look": float(f"{ref * (1.0 - DECK_TRANSMITTANCE):.6g}"),
            "eye_lux_from_lights_to_reach_the_close_clamp": float(
                f"{ref * (2.0 ** (2.0 * MAX_EXCURSION_EV) - DECK_TRANSMITTANCE):.6g}"),
        },
        "curve_summary": {
            "rows": len(rows),
            "light_term": "none",
            "offset_min_ev": min(r["offset_ev"] for r in rows),
            "offset_max_ev": max(r["offset_ev"] for r in rows),
        },
        "look_table": look_table,
        "tiers": [
            {"tier": 0, "est_vram_mb": 0.0,
             "summary": "manual exposure; the host steps the eye on the CPU and sets the bias each frame",
             "ue": {"AutoExposureMethod": "AEM_Manual", "bias": "camera_ev100 - (look ev100 + offset_ev)"}},
            {"tier": 1, "est_vram_mb": 0.1,
             "summary": "engine basic auto exposure, clamped to the excursion band, engine speeds from the taus",
             "ue": {"AutoExposureMethod": "AEM_Basic", "AutoExposureMinBrightness": lo,
                    "AutoExposureMaxBrightness": hi, "AutoExposureSpeedUp": round(1 / TAU_CLOSE_S, 3),
                    "AutoExposureSpeedDown": round(1 / TAU_OPEN_S, 3)}},
            {"tier": 2, "est_vram_mb": 0.5,
             "summary": "engine histogram auto exposure (compute shader), same clamp, 10-90 % window",
             "ue": {"AutoExposureMethod": "AEM_Histogram", "AutoExposureMinBrightness": lo,
                    "AutoExposureMaxBrightness": hi, "AutoExposureLowPercent": 10.0,
                    "AutoExposureHighPercent": 90.0}},
            {"tier": 3, "est_vram_mb": 3.0,
             "summary": "tier 2 plus local exposure to hold the lit runway and the dark field together",
             "ue": {"LocalExposureHighlightContrastScale": 0.8, "LocalExposureShadowContrastScale": 0.8}},
        ],
    }


def write() -> Dict[str, str]:
    BAKED.mkdir(exist_ok=True)
    plan = build()
    rows = curve()
    (BAKED / "night_ifr_eye.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    cols = list(rows[0])
    lines = [",".join(cols)] + [",".join(str(r[c]) for c in cols) for r in rows]
    (BAKED / "night_ifr_eye_curve.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(BAKED.iterdir()) if p.is_file()}


if __name__ == "__main__":
    for name, digest in write().items():
        print(digest, name)
