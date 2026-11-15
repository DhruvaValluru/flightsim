#!/usr/bin/env python3
"""Offline generator (runs on the Mac, stdlib only): physical light units for
the STORM scenario (thunderstorm cell, heavy rain, lightning, low visibility).

What it writes into ``baked/`` (deterministic: same bytes every run):

* ``storm_plu.json``  -- every light of the storm scene in physical units
  (lux, cd/m^2, cd, EV100, K), the tier ladder, and the numbers other lanes
  must agree with (``shared_params``).
* ``storm_overcast_sky_256x128.hdr`` -- a Radiance RGBE lat-long of the CIE
  standard overcast sky, NORMALISED so that a SkyLight whose intensity is
  ``sky.skylight_intensity_cd_m2`` lands exactly ``sky.horizontal_lux`` on a
  horizontal surface. Azimuthally symmetric, so the import orientation cannot
  be wrong (top row = zenith). The laptop only samples its mips.

Nothing here is a rendered or measured visual result. The calibrated look this
is held to is the project's own (core/scene/beauty_look.py, UNCALIBRATED
there): the numbers in ``PROJECT`` are copies, and
tests/test_swarm_lighting_exposure_physical_light_units_storm.py fails if the
project's move.

    python3 swarm/lanes/lighting_exposure/physical_light_units/storm/generate.py
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Dict, List, Tuple

LANE = Path(__file__).resolve().parent
BAKED = LANE / "baked"
ITEM = "lighting_exposure.physical_light_units.storm"

#: Copies of the project's storm look (the test cross-checks each against the
#: module named beside it). All UNCALIBRATED in the project too.
PROJECT: Dict[str, Any] = {
    "sun_elevation_deg": 28.0,            # hero_lighting.py INTENTS storm_soft_sheen
    "sun_relative_azimuth_deg": 20.0,     # same intent
    "sun_outer_space_lux": 120000.0,      # core/sky/plan.py SUN_ILLUMINANCE_LUX
    "clear_horizontal_lux": 50193.555,    # beauty_look.clear_sky_horizontal_lux(28, 0)
    "clear_direct_normal_lux": 82589.169,  # core/scenario/solar.illuminance_lux(28)
    "deck_fraction": 0.25,                # hero_lighting.OVERCAST_ILLUMINANCE_FRACTION
    "ev100_band": 14.5,                   # beauty_look.ev100_band(28)
    "ev100_look": 12.5,                   # beauty_look.exposure_target(band, scene_light, 0, 0)
    "meter_c": 250.0,                     # beauty_look.METER_CALIBRATION_C
    "meter_target_p90_srgb": 0.40,        # beauty_look.EXPOSURE_METER_TARGET_P90["storm"]
    "grade_white_temp_k": 6100.0,         # beauty_look.GRADES["storm"]["WhiteTemp"]
    "ground_albedo_dry": 0.17,            # hero_lighting surface "unspecified" (0.18, 0.17, 0.15)
    "lightning_peak_w_per_m": 6.0e5,      # lightning.FIRST_STROKE_PEAK_W_PER_M
    "lightning_lm_per_w": 80.0,           # lightning.LUMINOUS_EFFICACY_LM_PER_W
}

#: The gate: exposure within this many stops of the calibrated look.
GATE_EV = 0.3
#: Reflected-light meter constant K (ISO 2720), cd/m^2 at ISO 100.
METER_K = 12.5
#: Saturation-based sensor constant: L_max = 1.2 * 2^EV100 (ISO 12232 as used
#: by Lagarde & de Rousiers 2014, "Moving Frostbite to PBR", sec. 5.1.2; UE's
#: manual exposure follows the same 1.2 factor) [unverified against UE 5.7 here].
SATURATION_Q = 1.2

# ---- visual-only choices (no measurement behind them; labelled in the JSON) ----
#: Share of the under-deck horizontal illuminance carried by the directional
#: "bright patch" light; the rest is the sky dome. The SUM is the physical
#: quantity, so the exposure does not depend on this split (test-enforced).
DIRECTIONAL_SHARE = 0.15
#: Wet ground reflects about half of dry (Lekner & Dorf 1988, "Why some things
#: are darker when wet", Applied Optics 27(7)) [factor unverified here].
WET_ALBEDO_FACTOR = 0.5
#: Cloud asymmetry parameter for the two-stream cross-check.
CLOUD_G = 0.85
SKY_CCT_K = 7000.0          # overcast dome; between CIE D65 and D75 (visual-only)
SHEEN_CCT_K = 6500.0        # CIE D65 (visual-only)
LIGHTNING_CCT_K = 8000.0    # visual-only: a blue-white flash, not a channel temperature
LIGHTNING_CHANNEL_M = 5000.0  # assumed visible channel length for the cd figure
ASSUMED_VISIBILITY_M = 3000.0  # NOT owned here: the haze/rain lanes own it

HDR_W, HDR_H = 256, 128
HDR_NAME = "storm_overcast_sky_256x128.hdr"
PLU_NAME = "storm_plu.json"


# ------------------------------------------------------------------ photometry
def incident_ev100(horizontal_lux: float, c: float = PROJECT["meter_c"]) -> float:
    """Incident-meter EV100: E = C/100 * 2^EV (the project's meter_ev100)."""
    return math.log2(max(horizontal_lux, 1e-9) * 100.0 / c)


def reflected_ev100(luminance_cd_m2: float) -> float:
    """Reflected-light-meter EV100: L = K/100 * 2^EV."""
    return math.log2(max(luminance_cd_m2, 1e-9) * 100.0 / METER_K)


def cie_overcast_zenith_luminance(horizontal_lux: float) -> float:
    """CIE standard overcast sky (Moon & Spencer 1942; ISO 15469 / CIE S 011
    type 1): L(g) = Lz (1 + 2 sin g) / 3, whose horizontal illuminance is
    E = (7 pi / 9) Lz."""
    return 9.0 * horizontal_lux / (7.0 * math.pi)


def overcast_relative_luminance(elevation_deg: float) -> float:
    """Sky luminance over the mean (E / pi): cosine-weighted integral over
    the upper hemisphere is exactly pi."""
    s = math.sin(math.radians(max(elevation_deg, 0.0)))
    return (9.0 / 7.0) * (1.0 + 2.0 * s) / 3.0


def two_stream_optical_depth(transmittance: float, g: float = CLOUD_G) -> float:
    """Cloud optical depth that gives a diffuse transmittance T in the
    conservative two-stream model, T = 2 / (2 + tau (1 - g)) (Bohren 1987,
    "Multiple scattering of light and some of its observable consequences",
    Am. J. Phys. 55(6)) [formula recalled, unverified here]. A cross-check on
    the project's deck fraction, not an input to any light."""
    return 2.0 * (1.0 / transmittance - 1.0) / (1.0 - g)


def lightning_table() -> Dict[str, Any]:
    lumens = PROJECT["lightning_lm_per_w"] * PROJECT["lightning_peak_w_per_m"] * LIGHTNING_CHANNEL_M
    cd = lumens / (4.0 * math.pi)
    ambient = PROJECT["clear_horizontal_lux"] * PROJECT["deck_fraction"]
    rows = []
    for d in (1000.0, 2000.0, 5000.0, 10000.0):
        lux = cd / (d * d)  # facing the channel, no extinction: an upper bound in rain
        rows.append({"distance_m": d, "peak_lux_facing": round(lux, 1),
                     "peak_over_ambient": round(lux / ambient, 4),
                     "peak_stops_over_ambient": round(math.log2(1.0 + lux / ambient), 3)})
    return {
        "peak_intensity_cd": round(cd, 1),
        "channel_length_m_assumed": LIGHTNING_CHANNEL_M,
        "colour_temperature_k": LIGHTNING_CCT_K,
        "colour_temperature_basis": "visual-only",
        "by_distance": rows,
        "exposure_rule": ("the manual EV100 does NOT follow a flash (constant over the clip, the "
                          "project's no-breathing rule): a stroke is allowed to clip. Peak values "
                          "are instantaneous; the energy inside one shutter interval is "
                          "core/scene/lightning.py stroke_energy's, far below peak x shutter."),
        "basis": ("point source of K * P' * L / (4 pi) cd (core/scene/lightning.py intensity_cd) "
                  "with the project's first-stroke peak and luminous efficacy; inverse square, no "
                  "rain extinction"),
    }


def build() -> Dict[str, Any]:
    p = PROJECT
    sin_el = math.sin(math.radians(p["sun_elevation_deg"]))
    e_h = p["clear_horizontal_lux"] * p["deck_fraction"]        # under-deck global horizontal
    e_dir_h = DIRECTIONAL_SHARE * e_h
    e_sky_h = e_h - e_dir_h
    e_dir_normal = e_dir_h / sin_el                               # at the ground, on the light's normal
    atmos_t = p["clear_direct_normal_lux"] / p["sun_outer_space_lux"]  # engine per-pixel transmittance (model)
    light_lux = e_dir_normal / atmos_t                            # what goes on the light (outer-space lux)
    lz = cie_overcast_zenith_luminance(e_sky_h)
    wet = p["ground_albedo_dry"] * WET_ALBEDO_FACTOR
    card = 0.18 * e_h / math.pi
    ev_inc = incident_ev100(e_h)
    ev_refl = reflected_ev100(card)
    ev_look = p["ev100_look"]
    l_max = SATURATION_Q * 2.0 ** ev_look

    def cube_mb(n: int) -> float:  # RGBA16F cube with a full mip chain
        return round(6 * n * n * 8 * (4.0 / 3.0) / 1048576.0, 3)

    tiers: List[Dict[str, Any]] = [
        {"tier": 0, "est_vram_mb": cube_mb(32),
         "summary": ("constants only: manual EV100, directional light in lux (unshadowed fill of the "
                     "deck's bright patch), static SkyLight from the baked overcast cube at 32 px "
                     "(specified cubemap, no real-time sky capture), lightning as a one-frame "
                     "SkyLight intensity pulse; no new render targets, no light actors"),
         "skylight_cube_px": 32, "lightning": "skylight_pulse", "realtime_capture": False},
        {"tier": 1, "est_vram_mb": cube_mb(64),
         "summary": ("tier 0 with the 64 px cube and the lightning as ONE unshadowed, "
                     "inverse-square point light in candela (no shadow maps)"),
         "skylight_cube_px": 64, "lightning": "point_light_unshadowed", "realtime_capture": False},
        {"tier": 2, "est_vram_mb": cube_mb(128),
         "summary": ("tier 1 with the 128 px cube and the project's storm local-exposure block on "
                     "(beauty_look.LOCAL_EXPOSURE storm), so the flash keeps cloud detail"),
         "skylight_cube_px": 128, "lightning": "point_light_unshadowed", "realtime_capture": False},
        {"tier": 3, "est_vram_mb": cube_mb(256),
         "summary": ("tier 2 with the 256 px cube and bloom on the flash; still no real-time sky "
                     "capture, no Lumen, no shadowed flash"),
         "skylight_cube_px": 256, "lightning": "point_light_unshadowed_bloom", "realtime_capture": False},
    ]

    return {
        "item": ITEM,
        "scenario": "storm",
        "status": "UNMEASURED: computed on the Mac from named formulae; no frame was rendered",
        "calibrated_look": {
            "owner": "core/scene/beauty_look.py (UNCALIBRATED there)",
            "ev100": ev_look,
            "ev100_basis": "elevation band 14.5 at 28 deg + log2(0.25) deck stops",
            "frame_meter_target_p90_srgb_luma": p["meter_target_p90_srgb"],
            "gate_ev": GATE_EV,
        },
        "ambient": {
            "clear_sky_horizontal_lux": round(p["clear_horizontal_lux"], 1),
            "deck_fraction": p["deck_fraction"],
            "horizontal_lux": round(e_h, 1),
            "implied_cloud_optical_depth": round(two_stream_optical_depth(p["deck_fraction"]), 1),
            "implied_cloud_optical_depth_basis": (
                f"two-stream, g = {CLOUD_G}: a deck, not a cumulonimbus core (tau 100+ would "
                "transmit ~0.12 or less); cross-check only"),
        },
        "directional": {
            "role": "the deck's bright patch (storm_soft_sheen), not a sun disc",
            "share_of_horizontal": DIRECTIONAL_SHARE,
            "share_basis": "visual-only; exposure is independent of it",
            "elevation_deg": p["sun_elevation_deg"],
            "relative_azimuth_deg": p["sun_relative_azimuth_deg"],
            "ground_horizontal_lux": round(e_dir_h, 1),
            "ground_normal_lux": round(e_dir_normal, 1),
            "atmosphere_transmittance_model": round(atmos_t, 4),
            "light_lux_outer_space": round(light_lux, 1),
            "scale_of_project_sun": round(light_lux / p["sun_outer_space_lux"], 5),
            "colour_temperature_k": SHEEN_CCT_K,
            "colour_temperature_basis": "visual-only (CIE D65)",
            "cast_shadows": False,
            "note": ("light_lux_outer_space assumes the engine's per-pixel atmosphere transmittance "
                     "is the ONLY dimming of this light. If the drawn deck also shadows it, the "
                     "ground value is lower: read the -calibration quad (INTEGRATION.md)."),
        },
        "sky": {
            "model": "CIE standard overcast sky, L(g) = Lz (1 + 2 sin g) / 3",
            "horizontal_lux": round(e_sky_h, 1),
            "skylight_intensity_cd_m2": round(e_sky_h / math.pi, 1),
            "zenith_luminance_cd_m2": round(lz, 1),
            "horizon_luminance_cd_m2": round(lz / 3.0, 1),
            "cubemap": HDR_NAME,
            "cubemap_normalisation": "cosine-weighted upper-hemisphere integral = pi",
            "colour_temperature_k": SKY_CCT_K,
            "colour_temperature_basis": "visual-only (between CIE D65 and D75)",
            "lower_hemisphere_relative": round(wet / (1.0 - DIRECTIONAL_SHARE), 4),
            "lower_hemisphere_note": ("wet-ground luminance over the sky mean; the project's "
                                      "-storm-lower-hemisphere owner wins where it draws"),
        },
        "ground": {
            "albedo_dry": p["ground_albedo_dry"],
            "wet_factor": WET_ALBEDO_FACTOR,
            "albedo_wet": round(wet, 4),
            "albedo_wet_basis": "visual-only factor on the project's dry albedo",
            "luminance_wet_cd_m2": round(wet * e_h / math.pi, 1),
        },
        "exposure": {
            "method": "manual EV100, constant over the clip",
            "ev100": ev_look,
            "incident_meter_ev100": round(ev_inc, 3),
            "reflected_meter_grey_card_ev100": round(ev_refl, 3),
            "incident_minus_look_ev": round(ev_inc - ev_look, 3),
            "reflected_minus_look_ev": round(ev_refl - ev_look, 3),
            "grey_card_luminance_cd_m2": round(card, 1),
            "saturation_luminance_cd_m2": round(l_max, 1),
            "scene_linear_before_tonemap": {
                "grey_card_18pct": round(card / l_max, 4),
                "sky_zenith": round(lz / l_max, 4),
                "sky_horizon": round(lz / 3.0 / l_max, 4),
                "wet_ground": round(wet * e_h / math.pi / l_max, 4),
                "note": "L / (1.2 * 2^EV100); what the tonemapper does to these is UNMEASURED",
            },
            "fog_inscatter_ceiling_cd_m2": round(lz / 3.0, 1),
            "fog_note": ("a fog or rain veil lit by this sky cannot be brighter than the horizon "
                         "it hides; a brighter veil lifts the frame's p90 and the meter"),
        },
        "lightning": lightning_table(),
        "tiers": tiers,
        "shared_params": {
            "exposure_ev": ev_look,
            "exposure_mode": "manual",
            "sun_elevation_deg": p["sun_elevation_deg"],
            "sun_relative_azimuth_deg": p["sun_relative_azimuth_deg"],
            "horizontal_illuminance_lux": round(e_h, 1),
            "deck_illuminance_fraction": p["deck_fraction"],
            "directional_ground_normal_lux": round(e_dir_normal, 1),
            "directional_casts_shadows": False,
            "skylight_intensity_cd_m2": round(e_sky_h / math.pi, 1),
            "sky_zenith_luminance_cd_m2": round(lz, 1),
            "sky_horizon_luminance_cd_m2": round(lz / 3.0, 1),
            "fog_inscatter_ceiling_cd_m2": round(lz / 3.0, 1),
            "ground_albedo": round(wet, 4),
            "ground_albedo_dry": p["ground_albedo_dry"],
            "colour_temperature_k": p["grade_white_temp_k"],
            "sky_colour_temperature_k": SKY_CCT_K,
            "lightning_peak_intensity_cd": round(lightning_table()["peak_intensity_cd"], 1),
            "lightning_colour_temperature_k": LIGHTNING_CCT_K,
            "frame_meter_target_p90_srgb_luma": p["meter_target_p90_srgb"],
            "assumed_visibility_m": ASSUMED_VISIBILITY_M,
            "assumed_visibility_owner": "haze / rain lanes (an assumption here, not a setting)",
        },
    }


# ------------------------------------------------------------------ RGBE bake
def _rgbe(v: float) -> bytes:
    if v <= 1e-32:
        return b"\x00\x00\x00\x00"
    m, e = math.frexp(v)
    c = min(int(m * 256.0), 255)
    return bytes((c, c, c, e + 128))


def sky_rows(lower: float) -> List[float]:
    """Relative luminance per row, zenith first (row centres)."""
    rows = []
    for r in range(HDR_H):
        el = 90.0 - (r + 0.5) * 180.0 / HDR_H
        rows.append(overcast_relative_luminance(el) if el > 0.0 else lower)
    return rows


def hdr_bytes(lower: float) -> bytes:
    head = f"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y {HDR_H} +X {HDR_W}\n".encode("ascii")
    return head + b"".join(_rgbe(v) * HDR_W for v in sky_rows(lower))


def read_hdr_rows(data: bytes) -> Tuple[int, int, List[float]]:
    """Decode this generator's flat RGBE back to one luminance per row."""
    head, _, rest = data.partition(b"\n\n")
    dims, _, pixels = rest.partition(b"\n")
    _, h, _, w = dims.decode("ascii").split()
    w, h = int(w), int(h)
    rows = []
    for r in range(h):
        c, _, _, e = struct.unpack_from("4B", pixels, r * w * 4)
        rows.append(0.0 if e == 0 else (c + 0.5) / 256.0 * 2.0 ** (e - 128))
    return w, h, rows


def horizontal_integral(rows: List[float]) -> float:
    """Cosine-weighted integral of the upper hemisphere (pi for a unit sky)."""
    h = len(rows)
    d = math.pi / h
    total = 0.0
    for r, v in enumerate(rows):
        el = math.pi / 2.0 - (r + 0.5) * d
        if el > 0.0:
            total += v * math.sin(el) * math.cos(el) * d * 2.0 * math.pi
    return total


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    BAKED.mkdir(parents=True, exist_ok=True)
    plan = build()
    (BAKED / HDR_NAME).write_bytes(hdr_bytes(plan["sky"]["lower_hemisphere_relative"]))
    plan["baked"] = {HDR_NAME: {"sha256": sha256(BAKED / HDR_NAME), "width": HDR_W, "height": HDR_H,
                                "encoding": "Radiance RGBE, flat scanlines, grey"}}
    (BAKED / PLU_NAME).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name in (PLU_NAME, HDR_NAME):
        print(f"{sha256(BAKED / name)}  baked/{name}")
    e = plan["exposure"]
    print(f"EV100 look {e['ev100']}  incident {e['incident_meter_ev100']}  "
          f"reflected {e['reflected_meter_grey_card_ev100']}  gate +/-{GATE_EV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
