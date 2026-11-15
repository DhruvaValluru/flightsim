#!/usr/bin/env python3
"""Offline sun/moon ephemeris + SkyAtmosphere reference radiometry, coastal.

Lane atmosphere_clouds.sun_moon_ephemeris.coastal. Runs on the Mac; the render
path only reads the constants it writes (tier 0 costs no GPU work at all).

What it bakes into out/:
  ephemeris_coastal.json      the evening track (sun and moon direction, phase,
                              top-of-atmosphere lux, SkyAtmosphere transmittance,
                              ground lux), the key low-sun instant, and the
                              reference table T(elevation, altitude).
  T_SunMoonTransmittance_64x16.png
                              the same table as a tiny linear texture
                              (sqrt-encoded) for tiers that tint a disc per pixel.
and PROVENANCE.json beside this file.

Positions come from the repository's own Meeus implementation (core/sky/astro.py);
nothing is fetched. The transmittance is a numerical integral through the
atmosphere UE's USkyAtmosphereComponent describes by default (coefficients
below). It is a REFERENCE for the Windows gate, not a measurement of the engine.

  python bake_ephemeris.py                 # bake
  python bake_ephemeris.py measure ...     # the pixel gate (Windows frames)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]
OUT = LANE / "out"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.scenario import solar  # noqa: E402
from core.sky import astro, plan as sky_plan  # noqa: E402

ITEM = "atmosphere_clouds.sun_moon_ephemeris.coastal"

# -- the scenario (a STATED choice of this lane: no coastal card exists yet) --
# Half Moon Bay (KHAF), a west-facing coast, so the low sun sets over the water.
# Coordinates recalled, not fetched; any coastal card's own lat/lon/date replace
# them through the CLI and everything below is recomputed.
SITE = {"name": "Half Moon Bay, California (KHAF)", "lat_deg": 37.5134,
        "lon_deg": -122.5011, "source": "lane's stated choice; coordinates recalled, not fetched"}
DATE = sky_plan.DEFAULT_DATE            # the repository's default scene date
KEY_SUN_ELEVATION_DEG = 12.0            # shared with the coastal glass / PBR lanes
HIGH_SUN_ELEVATION_DEG = 60.0           # the gate's second frame

# -- UE SkyAtmosphere defaults (1/km, km) -------------------------------------
# BottomRadius 6360 / AtmosphereHeight 60 and the Mie 0.003996 / 0.000444 pair
# are what FlightSimVisualScene.cpp sets and cites. The Rayleigh and ozone
# values are the engine defaults (Hillaire 2020; Bruneton & Neyret 2008),
# recalled, [unverified against the UE 5.7 source on this machine].
ATMOS = {
    "bottom_radius_km": 6360.0,
    "atmosphere_height_km": 60.0,
    "rayleigh_scattering_per_km": [0.005802, 0.013558, 0.033100],
    "rayleigh_scale_height_km": 8.0,
    "mie_scattering_per_km": 0.003996,
    "mie_absorption_per_km": 0.000444,
    "mie_scale_height_km": 1.2,
    "ozone_absorption_per_km": [0.000650, 0.001881, 0.000085],
    "ozone_tip_altitude_km": 25.0,
    "ozone_tent_half_width_km": 15.0,
}
REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])
TABLE_ELEVATIONS_DEG = [-2, -1, 0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 75, 90]
TABLE_ALTITUDES_KM = [0.0, 0.3, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0]
LUT_W, LUT_H = 64, 16
LUT_ELEV_MIN, LUT_ELEV_SPAN, LUT_ALT_MAX_KM = -3.0, 93.0, 15.0
INTEGRATION_STEPS = 2048

# -- gate thresholds ----------------------------------------------------------
GATE_CHROMA_STOPS = 0.15      # |log2(measured / reference)| on R/G and B/G
GATE_LEVEL_STOPS = 0.25       # same, on the green direct level (fixed exposure)


def transmittance(elevation_deg, altitude_km=0.0, mie_scale=1.0, steps=INTEGRATION_STEPS):
    """Linear RGB transmittance from ``altitude_km`` to the top of the
    atmosphere along a straight ray at ``elevation_deg`` (no refraction, like
    the engine). Zero where the ray meets the ground. Shape (..., 3)."""
    a = ATMOS
    rb = a["bottom_radius_km"]
    rt = rb + a["atmosphere_height_km"]
    el = np.atleast_1d(np.asarray(elevation_deg, dtype=float))
    r0 = rb + float(altitude_km)
    mu = np.sin(np.radians(el))
    hits_ground = (mu < 0.0) & (r0 * r0 * (mu * mu - 1.0) + rb * rb >= 0.0)
    d = -r0 * mu + np.sqrt(np.maximum(r0 * r0 * (mu * mu - 1.0) + rt * rt, 0.0))
    frac = (np.arange(steps) + 0.5) / steps
    t = d[:, None] * frac[None, :]
    h = np.sqrt(t * t + 2.0 * r0 * mu[:, None] * t + r0 * r0) - rb
    h = np.maximum(h, 0.0)
    dt = (d / steps)[:, None]
    ray = np.sum(np.exp(-h / a["rayleigh_scale_height_km"]) * dt, axis=1)
    mie = np.sum(np.exp(-h / a["mie_scale_height_km"]) * dt, axis=1)
    tent = np.maximum(0.0, 1.0 - np.abs(h - a["ozone_tip_altitude_km"]) / a["ozone_tent_half_width_km"])
    ozo = np.sum(tent * dt, axis=1)
    mie_ext = (a["mie_scattering_per_km"] + a["mie_absorption_per_km"]) * mie_scale
    tau = (ray[:, None] * np.array(a["rayleigh_scattering_per_km"])[None, :]
           + mie[:, None] * mie_ext
           + ozo[:, None] * np.array(a["ozone_absorption_per_km"])[None, :])
    out = np.exp(-tau)
    out[hits_ground] = 0.0
    return out if np.ndim(elevation_deg) else out[0]


def luminance(rgb) -> float:
    return float(np.dot(np.asarray(rgb, dtype=float), REC709_LUMA))


def cct_kelvin(rgb) -> float:
    """McCamy's CCT of a linear Rec.709 colour (a D65 white light tinted by
    ``rgb``). Three-band, so indicative only."""
    r, g, b = (float(v) for v in rgb)
    x_ = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y_ = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z_ = 0.0193 * r + 0.1192 * g + 0.9505 * b
    s = x_ + y_ + z_
    x, y = x_ / s, y_ / s
    n = (x - 0.3320) / (0.1858 - y)
    return 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33


def sun_toa_lux(distance_km: float) -> float:
    """Direct normal illuminance above the atmosphere: the repository's ASTM
    G173 figure at 1 AU, scaled by the day's Earth-sun distance."""
    return solar.SUN_LUX_MAX * (astro.AU_KM / distance_km) ** 2


def moon_toa_lux(phase_angle_deg: float, distance_km: float) -> float:
    """Moonlight before the atmosphere: the repository's full-moon lux, its
    phase law, and the inverse square of the moon's distance. FULL_MOON_LUX is
    used as an above-atmosphere figure; if it was meant at the ground the moon
    here is dim by its zenith transmittance (about 12 %)."""
    return (sky_plan.FULL_MOON_LUX * astro.moon_relative_brightness(phase_angle_deg)
            * (astro.MOON_MEAN_DISTANCE_KM / distance_km) ** 2)


def lookup(table: dict, elevation_deg: float, altitude_km: float = 0.0):
    """Bilinear read of the baked table (what core/sky/plan.py would call)."""
    els = np.array(table["elevations_deg"], dtype=float)
    alts = np.array(table["altitudes_km"], dtype=float)
    grid = np.array(table["rgb"], dtype=float)          # [alt][elev][3]
    e = float(np.clip(elevation_deg, els[0], els[-1]))
    h = float(np.clip(altitude_km, alts[0], alts[-1]))
    rows = np.stack([[np.interp(e, els, grid[i, :, c]) for c in range(3)] for i in range(len(alts))])
    return np.array([np.interp(h, alts, rows[:, c]) for c in range(3)])


def _utc(day: date, hours: float) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=hours)


def evening_instant(lat: float, lon: float, day: date, target_elevation_deg: float) -> datetime:
    """The UTC instant after local solar noon when the sun's apparent
    elevation falls through ``target_elevation_deg``."""
    def f(when):
        return astro.sun_position(when, lat, lon).elevation_deg - target_elevation_deg
    a = _utc(day, 12.0 - lon / 15.0)                    # local solar noon, roughly
    if f(a) <= 0.0:
        raise SystemExit(f"sun never reaches {target_elevation_deg} deg on {day} at this site")
    b = a
    for _ in range(12 * 60):
        b = b + timedelta(minutes=1)
        if f(b) <= 0.0:
            break
        a = b
    else:
        raise SystemExit("no evening crossing found (polar day?)")
    for _ in range(40):
        m = a + (b - a) / 2
        if f(m) > 0.0:
            a = m
        else:
            b = m
    return a + (b - a) / 2


def _r(x, n=4):
    return [round(float(v), n) for v in x] if np.ndim(x) else round(float(x), n)


def _cct_or_none(rgb):
    """McCamy is only meaningful from about 2000 K up; below that, no number."""
    if luminance(rgb) <= 1e-6:
        return None
    k = cct_kelvin(rgb)
    return _r(k, 0) if 2000.0 <= k <= 12500.0 else None


def body_row(when: datetime, lat: float, lon: float) -> dict:
    sun = astro.sun_position(when, lat, lon)
    moon = astro.moon_position(when, lat, lon)
    ts = transmittance(sun.elevation_deg)
    tm = transmittance(moon.elevation_deg)
    s_toa = sun_toa_lux(sun.distance_km)
    m_toa = moon_toa_lux(moon.phase_angle_deg, moon.distance_km)
    bird = solar.illuminance_lux(max(sun.elevation_deg, -90.0)).illuminance_lux if sun.elevation_deg > 0 else 0.0
    return {
        "utc": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sun": {
            "azimuth_deg": _r(sun.azimuth_deg, 3), "elevation_deg": _r(sun.elevation_deg, 3),
            "angular_radius_deg": _r(sun.angular_radius_deg, 4),
            "toa_lux": _r(s_toa, 1),
            "transmittance_rgb": _r(ts, 5),
            "ground_normal_lux_skyatmosphere": _r(s_toa * luminance(ts), 1),
            "ground_normal_lux_bird_hulstrom": _r(bird, 1),
            "tint_cct_k": _cct_or_none(ts),
        },
        "moon": {
            "azimuth_deg": _r(moon.azimuth_deg, 3), "elevation_deg": _r(moon.elevation_deg, 3),
            "angular_radius_deg": _r(moon.angular_radius_deg, 4),
            "phase_angle_deg": _r(moon.phase_angle_deg, 2),
            "illuminated_fraction": _r(moon.illuminated_fraction, 4), "waxing": bool(moon.waxing),
            "toa_lux": _r(m_toa, 6),
            "transmittance_rgb": _r(tm, 5),
            "ground_normal_lux_skyatmosphere": _r(m_toa * luminance(tm), 6),
        },
    }


def reference(low_deg=KEY_SUN_ELEVATION_DEG, high_deg=HIGH_SUN_ELEVATION_DEG) -> dict:
    """The numbers the gate compares a frame against."""
    lo, hi = transmittance(low_deg), transmittance(high_deg)
    return {
        "low_elevation_deg": low_deg, "high_elevation_deg": high_deg,
        "t_low_rgb": _r(lo, 5), "t_high_rgb": _r(hi, 5),
        "chroma_ratio_r_over_g": _r((lo[0] / lo[1]) / (hi[0] / hi[1]), 5),
        "chroma_ratio_b_over_g": _r((lo[2] / lo[1]) / (hi[2] / hi[1]), 5),
        # direct light on a HORIZONTAL neutral card, green channel, low / high
        "level_ratio_g_horizontal": _r((lo[1] * math.sin(math.radians(low_deg)))
                                       / (hi[1] * math.sin(math.radians(high_deg))), 5),
    }


def build(lat: float, lon: float, day: date, site_name: str, site_source: str) -> dict:
    key = evening_instant(lat, lon, day, KEY_SUN_ELEVATION_DEG)
    key = key.replace(microsecond=0)
    track = [body_row(key + timedelta(minutes=m), lat, lon) for m in range(-60, 125, 5)]
    events = {}
    for name, el in (("sunset_apparent_upper_limb", -0.2666), ("civil_dusk", -6.0),
                     ("nautical_dusk", -12.0), ("astronomical_dusk", -18.0)):
        events[name] = evening_instant(lat, lon, day, el).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    table = {
        "elevations_deg": TABLE_ELEVATIONS_DEG, "altitudes_km": TABLE_ALTITUDES_KM,
        "rgb": [[_r(v, 5) for v in transmittance(TABLE_ELEVATIONS_DEG, h)] for h in TABLE_ALTITUDES_KM],
        "layout": "rgb[altitude][elevation] = linear Rec.709 transmittance to the top of the atmosphere",
    }
    key_row = body_row(key, lat, lon)
    ks = key_row["sun"]
    t_zen = transmittance(90.0)
    t_key = np.array(ks["transmittance_rgb"])
    return {
        "item": ITEM,
        "measured": False,
        "status": "UNMEASURED: computed on the Mac. No frame rendered; the engine's own numbers are read on the Windows laptop.",
        "site": {"name": site_name, "lat_deg": lat, "lon_deg": lon, "source": site_source},
        "date": day.isoformat(),
        "ephemeris_source": "core/sky/astro.py (Meeus, Astronomical Algorithms 2nd ed.; apparent elevation, Bennett refraction)",
        "atmosphere": ATMOS,
        "key_instant": key_row,
        "events_utc": events,
        "track_step_min": 5,
        "track": track,
        "transmittance_table": table,
        "gate_reference": reference(),
        "findings": {
            # What the current scene set-up implies, as arithmetic. Each line is
            # a prediction for the Windows gate, not an observation.
            "sun_lux_convention": "an Atmosphere Sun Light's intensity is the illuminance ABOVE the atmosphere; "
                                  "SkyAtmosphere applies its own transmittance on the way down [recalled engine behaviour, unverified here]",
            "toa_lux": ks["toa_lux"],
            "bird_hulstrom_ground_lux": ks["ground_normal_lux_bird_hulstrom"],
            "sky_dim_factor_if_ground_lux_is_stated": _r(ks["ground_normal_lux_bird_hulstrom"] / ks["toa_lux"], 4),
            "min_light_elevation_90_tint_error_rgb": _r(t_zen / t_key, 4),
            "min_light_elevation_90_note": "FlightSimVisualScene.cpp sets TransmittanceMinLightElevationAngle = 90. If that clamps "
                                           "the elevation used for the light's ground transmittance (as recalled), a 12 deg sun lights "
                                           "the ground with the zenith tint: too bright and too blue by these factors.",
        },
        "shared_params": shared_params(key_row),
        "tiers": TIERS,
    }


def shared_params(key_row: dict) -> dict:
    s, m = key_row["sun"], key_row["moon"]
    return {
        "scenario": "coastal",
        "utc": key_row["utc"],
        "sun_elevation_deg": KEY_SUN_ELEVATION_DEG,
        "sun_azimuth_true_deg": s["azimuth_deg"],
        "sun_toa_lux": s["toa_lux"],
        "sun_ground_normal_lux": s["ground_normal_lux_skyatmosphere"],
        "sun_transmittance_linear_rgb": s["transmittance_rgb"],
        "colour_temperature_k": s["tint_cct_k"],
        "colour_temperature_note": "three-band estimate of the SkyAtmosphere tint on a D65 sun; the glass and PBR lanes state 4300 K, "
                                   "which this model gives at about 15 deg; the two agree to about 5 %, inside the estimate's error.",
        "moon_elevation_deg": m["elevation_deg"],
        "moon_azimuth_true_deg": m["azimuth_deg"],
        "moon_illuminated_fraction": m["illuminated_fraction"],
        "moon_ground_normal_lux": m["ground_normal_lux_skyatmosphere"],
        "mie_scale": 1.0,
        "haze_note": "engine-default Mie; the 15 km sea haze of the sibling lanes rides on the height fog row, as the bridge already does",
        "exposure_ev_bias": 0.0,
        "sea_albedo": 0.06,
    }


TIERS = [
    {"tier": 0, "est_vram_mb": 0.0,
     "summary": "CPU constants only: sun and moon direction from the baked track, sun intensity = top-of-atmosphere lux, "
                "SkyAtmosphere applies transmittance at the true elevation; moon disc tinted by one vector parameter. No texture, no pass."},
    {"tier": 1, "est_vram_mb": 0.1,
     "summary": "tier 0 + the moon as the second atmosphere light (index 1, no shadows) so the sky LUTs scatter moonlight at dusk."},
    {"tier": 2, "est_vram_mb": 0.2,
     "summary": "tier 1 + per-pixel atmosphere transmittance on the sun (one LUT read per lit pixel) and the 64x16 baked strip "
                "sampled across the sun and moon discs for the limb-to-limb reddening at the horizon."},
    {"tier": 3, "est_vram_mb": 8.0,
     "summary": "tier 2 + the moon casts shadows after dusk (2 cascades at 1024). Heaviest; only for the stress ladder."},
]

SOURCES = [
    {"name": "this repository: core/sky/astro.py, core/sky/plan.py, core/scenario/solar.py",
     "licence": "project's own",
     "used_for": "sun and moon positions (Meeus ch. 25 / 47), phase law, FULL_MOON_LUX, the 133 100 lx ASTM G173 "
                 "extraterrestrial sun, Bird & Hulstrom ground lux for comparison"},
    {"name": "Hillaire 2020, A Scalable and Production Ready Sky and Atmosphere Rendering Technique (EGSR); "
             "Bruneton & Neyret 2008, Precomputed Atmospheric Scattering",
     "url": "https://sebh.github.io/publications/egsr2020.pdf",
     "licence": "published coefficients (no asset copied)",
     "used_for": "the Rayleigh, Mie and ozone coefficients and profiles of UE's SkyAtmosphere defaults",
     "note": "Rayleigh and ozone values recalled, unverified against the UE 5.7 source here; Mie and radii match FlightSimVisualScene.cpp"},
    {"name": "McCamy 1992, Correlated color temperature as an explicit function of chromaticity coordinates, Color Res. Appl. 17(2)",
     "licence": "published formula (no asset copied)", "used_for": "the indicative CCT of the tint",
     "note": "formula recalled, unverified here"},
]

NOT_ADOPTED = [
    {"name": "PetrVevoda/pragueskymodel, Scroga/Altitude-Responsive-Sky-Model",
     "why": "sky radiance, not ephemeris; the dataset licence is unverified and the dataset is large. Not fetched."},
    {"name": "fgarlin/skytracer",
     "why": "its marine-aerosol cross-sections would give a coastal RGB Mie; unvetted and not fetched. The haze rides on the fog row today, "
            "so the engine-default Mie is the honest reference. Worth vetting for the aerial-perspective lane."},
    {"name": "AT3D, NVIDIA approximate Mie, Wrenninge 2013, Poly Haven pure skies",
     "why": "cloud and phase-function material, outside an ephemeris."},
]


def write_lut(path: Path) -> None:
    from PIL import Image
    u = (np.arange(LUT_W) + 0.5) / LUT_W
    v = (np.arange(LUT_H) + 0.5) / LUT_H
    elev = LUT_ELEV_MIN + LUT_ELEV_SPAN * u * u            # dense near the horizon
    img = np.zeros((LUT_H, LUT_W, 3))
    for j, alt in enumerate(v * LUT_ALT_MAX_KM):
        img[j] = transmittance(elev, alt, steps=1024)
    Image.fromarray(np.round(np.sqrt(img) * 255.0).astype(np.uint8)).save(path, optimize=False)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bake(args) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    day = date.fromisoformat(args.date) if args.date else DATE
    custom = args.lat is not None or args.lon is not None
    lat = SITE["lat_deg"] if args.lat is None else args.lat
    lon = SITE["lon_deg"] if args.lon is None else args.lon
    doc = build(lat, lon, day, "command line" if custom else SITE["name"],
                "command line" if custom else SITE["source"])
    jpath = OUT / "ephemeris_coastal.json"
    jpath.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    lpath = OUT / "T_SunMoonTransmittance_64x16.png"
    write_lut(lpath)
    prov = {
        "item": ITEM,
        "status": "UNMEASURED: generated on the Mac; no frame rendered, nothing downloaded, nothing vendored",
        "visual_only": False,
        "generated": [
            {"path": "out/ephemeris_coastal.json", "sha256": sha256(jpath), "by": "bake_ephemeris.py",
             "licence": "project's own (computed numbers)"},
            {"path": "out/T_SunMoonTransmittance_64x16.png", "sha256": sha256(lpath), "by": "bake_ephemeris.py",
             "licence": "project's own (computed numbers)",
             "encoding": "8-bit, value = sqrt(T); u -> elevation = -3 + 93 u^2 deg, v -> altitude = 15 v km; import linear (sRGB off), no mips, clamp"},
        ],
        "fetched_assets": [],
        "sources": SOURCES,
        "research_candidates_not_adopted": NOT_ADOPTED,
    }
    (LANE / "PROVENANCE.json").write_text(json.dumps(prov, indent=1) + "\n")
    k = doc["key_instant"]
    print(f"key instant {k['utc']}: sun az {k['sun']['azimuth_deg']} el {k['sun']['elevation_deg']}, "
          f"T {k['sun']['transmittance_rgb']}, toa {k['sun']['toa_lux']} lx, ground {k['sun']['ground_normal_lux_skyatmosphere']} lx "
          f"(Bird {k['sun']['ground_normal_lux_bird_hulstrom']}), cct {k['sun']['tint_cct_k']} K")
    print(f"moon az {k['moon']['azimuth_deg']} el {k['moon']['elevation_deg']} lit {k['moon']['illuminated_fraction']}")
    return 0


# -- the pixel gate (frames come from the Windows laptop) ----------------------

def _linear(path: str, encoding: str):
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    if encoding == "srgb":
        a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    return a


def _rect_mean(img, rect: str):
    x, y, w, h = (int(v) for v in rect.split(","))
    patch = img[y:y + h, x:x + w].reshape(-1, 3)
    if patch.size == 0:
        raise SystemExit(f"rect {rect} is outside the frame")
    if (patch.max(axis=0) >= 0.98).any():
        raise SystemExit(f"rect {rect} is clipped; lower the exposure and render again")
    return patch.mean(axis=0)


def direct_rgb(frame: str, lit: str, shadow: str, encoding: str):
    """Sun-only light on a neutral surface: lit patch minus the shadowed patch
    beside it (the sky's fill cancels)."""
    img = _linear(frame, encoding)
    d = _rect_mean(img, lit) - _rect_mean(img, shadow)
    if (d <= 0).any():
        raise SystemExit(f"{frame}: the lit patch is not brighter than the shadowed one in every channel")
    return d


def gate_errors(direct_low, direct_high, ref: dict) -> dict:
    lo, hi = np.asarray(direct_low, float), np.asarray(direct_high, float)
    rg = (lo[0] / lo[1]) / (hi[0] / hi[1])
    bg = (lo[2] / lo[1]) / (hi[2] / hi[1])
    lv = lo[1] / hi[1]
    return {
        "r_over_g_stops": abs(math.log2(rg / ref["chroma_ratio_r_over_g"])),
        "b_over_g_stops": abs(math.log2(bg / ref["chroma_ratio_b_over_g"])),
        "level_g_stops": abs(math.log2(lv / ref["level_ratio_g_horizontal"])),
    }


def measure(args) -> int:
    ref = json.loads((OUT / "ephemeris_coastal.json").read_text())["gate_reference"]
    result = {}
    for label, low, high in (("reference", args.ref_low, args.ref_high), ("candidate", args.low, args.high)):
        if not (low and high):
            continue
        e = gate_errors(direct_rgb(low, args.lit_rect, args.shadow_rect, args.encoding),
                        direct_rgb(high, args.lit_rect, args.shadow_rect, args.encoding), ref)
        e["chroma_stops"] = max(e["r_over_g_stops"], e["b_over_g_stops"])
        result[label] = e
    c = result["candidate"]
    ok = c["chroma_stops"] <= GATE_CHROMA_STOPS
    if "reference" in result:
        ok = ok and c["chroma_stops"] < result["reference"]["chroma_stops"]
    result["level_within"] = c["level_g_stops"] <= GATE_LEVEL_STOPS
    result["pass"] = bool(ok)
    result["threshold_chroma_stops"] = GATE_CHROMA_STOPS
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--date")
    m = sub.add_parser("measure", help="the pixel gate on Windows frames")
    m.add_argument("--low", required=True, help="candidate frame, sun at 12 deg")
    m.add_argument("--high", required=True, help="candidate frame, sun at 60 deg")
    m.add_argument("--ref-low")
    m.add_argument("--ref-high")
    m.add_argument("--lit-rect", required=True, help="x,y,w,h of a sunlit neutral patch")
    m.add_argument("--shadow-rect", required=True, help="x,y,w,h of the same surface in shadow")
    m.add_argument("--encoding", choices=("srgb", "linear"), default="srgb")
    args = p.parse_args(argv)
    return measure(args) if args.cmd == "measure" else bake(args)


if __name__ == "__main__":
    raise SystemExit(main())
