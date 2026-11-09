"""Match the realtime beauty frame to a path-traced reference of the same shot.

Visual overhaul, reference-frames lane (2026-11-09). VISUAL ONLY: nothing
here reaches an equation of motion, a label or a measure render. The CLI is
``experiments/look_match.py``; this module is its pure part, so the refusal
names below are scanned by tests/test_messages.py like every other.

What it does
------------
Given the ``-quality=pathtrace`` frame (the reference: the path tracer with
the reference atmosphere and clouds, docs/visual/PROBE_LOG.md
"## reference-frames") and the ``-quality=beauty`` frame of the SAME shot
(same card, same pose, same resolution), it splits the frame into three
regions from the realtime run's label bundle -- **sky** (depth +inf),
**ground** (finite depth, not aircraft) and **aircraft** (the ID mask's
aircraft int_ids) -- and measures in each, on both frames:

* luminance: linear (sRGB-decoded) relative luminance Y, median and
  percentiles; the difference is in stops, log2(realtime / reference);
* colour: CIELAB (D65), the CIEDE2000 difference of the region means (the
  colour cast) and the mean per-pixel CIEDE2000;
* contrast: the interquartile spread of L* (mid-tone contrast);
* shadow depth: log2(median Y / 5th-percentile Y), how many stops the
  shadows sit under the mid-tones (the fill light's signature);
* far-ground contrast: the L* spread of the farthest quarter of the ground
  (by depth), which haze and aerial perspective flatten.

From those it SUGGESTS new values for the named UNCALIBRATED look constants
and writes them in the formats their loaders already read:

* ``beauty_look.json`` -- the ``-beauty-look=`` sidecar
  (core/scene/beauty_look.py, FlightSimBeautyLook.cpp): ``exposure.ev100``
  and ``color_grade`` (ColorGain, ColorSaturation, ColorContrast). The
  host recomputes AutoExposureBias from the EV100 it reads;
* ``world_beauty_overrides.json`` -- the ``-world-beauty-overrides=`` /
  ``FLIGHTSIM_WORLD_BEAUTY_OVERRIDES`` file (core/scene/world_beauty.py
  validate_overrides, FlightSimClouds.cpp): ``atmosphere.<preset>.
  aerial_perspective_scale`` (fog / haze) and
  ``constants.cloud_extinction_scale``;
* the ``-sky-light-scale=`` flag (core/render/flags.py LIGHTING_FLAGS): the
  sky light's multiplier, which has no sidecar of its own.

The frames are DISPLAY-referred PNGs: the tonemapper sits between the
scene and the pixels, so a stop measured in the PNG is not a stop of
scene light. Every correction is therefore damped (``*_GAIN`` below) and
clamped per pass, and the runbook iterates: render, match, apply,
re-render, until every region is inside its tolerance. Every gain,
tolerance and clamp here is UNCALIBRATED: set by probe render on the
render machine (PROBE_LOG.md "## reference-frames" names the probe).

What it does NOT claim: that the path tracer is ground truth for the world
(it traces the same tiles, the same materials and the same sun; its value
is the light transport -- multiple scattering in the atmosphere and the
clouds, sky occlusion, interreflection -- that the realtime path
approximates); that the heuristics are independent (the grade, the sky
light and the haze all move the same pixels, which is why each pass is
damped); or that a region with fewer than :data:`MIN_REGION_PIXELS`
pixels says anything (it is skipped, by name).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

#: The report's format and version.
LOOK_MATCH_FORMAT = "flightsim.look_match"
LOOK_MATCH_VERSION = 1

#: The refusal names (core/messages/catalog.yaml).
REFUSE_INPUTS = "look_match.inputs"
REFUSE_NOT_SAME_SHOT = "look_match.not_same_shot"
REFUSE_QUALITY = "look_match.quality"


class LookMatchError(ValueError):
    """A look match that cannot be made as asked, refused by name."""

    def __init__(self, constraint: str, message: str):
        super().__init__(f"{constraint}: {message}")
        self.constraint = constraint


#: Luminance floor (linear Y) under logs, so a black pixel is not -inf stops
#: (a numerical guard, not a look constant).
Y_FLOOR = 1.0e-4


# -- the constants (every one UNCALIBRATED: set by probe render on the render machine) --

#: A region with fewer pixels than this is skipped (its statistics are noise).
MIN_REGION_PIXELS = 64
#: Exposure: no suggestion within this many stops; else move the EV100 by
#: EXPOSURE_GAIN x the measured stops, at most EXPOSURE_STEP_MAX_STOPS a pass.
EXPOSURE_TOLERANCE_STOPS = 0.10
EXPOSURE_GAIN = 0.8
EXPOSURE_STEP_MAX_STOPS = 2.0
#: Colour cast: no ColorGain change while the region means are within this
#: CIEDE2000; else move each channel by its chromaticity ratio ^ GAIN_DAMP,
#: clamped to GAIN_STEP_CLAMP a pass.
COLOUR_TOLERANCE_DE00 = 2.0
GAIN_DAMP = 0.7
GAIN_STEP_CLAMP = (0.85, 1.15)
#: Saturation: mean CIELAB chroma ratio outside 1 +- this moves ColorSaturation.
SATURATION_TOLERANCE = 0.05
SATURATION_DAMP = 0.7
SATURATION_STEP_CLAMP = (0.8, 1.25)
#: Mid-tone contrast: L* interquartile ratio outside 1 +- this moves ColorContrast.
CONTRAST_TOLERANCE = 0.05
CONTRAST_DAMP = 0.6
CONTRAST_STEP_CLAMP = (0.8, 1.25)
#: Shadow depth: realtime shadows deeper than the reference's by more than this
#: (stops) means too little fill: the sky light scale moves by
#: 2 ^ (SKY_LIGHT_GAIN x the difference), clamped a pass.
SHADOW_TOLERANCE_STOPS = 0.15
SKY_LIGHT_GAIN = 0.6
SKY_LIGHT_STEP_CLAMP = (0.5, 2.0)
#: Haze: far-ground L* spread ratio outside 1 +- this moves the preset's
#: aerial_perspective_scale (a larger scale = more haze at a distance).
HAZE_TOLERANCE = 0.08
HAZE_DAMP = 0.7
HAZE_STEP_CLAMP = (0.7, 1.4)
#: The far ground is the ground at or beyond this depth percentile.
FAR_GROUND_PERCENTILE = 75.0
#: Clouds: only judged when the reference sky's L* spread exceeds this (a
#: clear sky has no cloud to match); the sky's L* spread ratio outside 1 +-
#: CLOUD_TOLERANCE moves constants.cloud_extinction_scale.
CLOUD_SKY_MIN_SPREAD_L = 3.0
CLOUD_TOLERANCE = 0.08
CLOUD_DAMP = 0.6
CLOUD_STEP_CLAMP = (0.5, 2.0)

UNCALIBRATED: Tuple[str, ...] = (
    "MIN_REGION_PIXELS", "EXPOSURE_TOLERANCE_STOPS", "EXPOSURE_GAIN",
    "EXPOSURE_STEP_MAX_STOPS", "COLOUR_TOLERANCE_DE00", "GAIN_DAMP", "GAIN_STEP_CLAMP",
    "SATURATION_TOLERANCE", "SATURATION_DAMP", "SATURATION_STEP_CLAMP",
    "CONTRAST_TOLERANCE", "CONTRAST_DAMP", "CONTRAST_STEP_CLAMP",
    "SHADOW_TOLERANCE_STOPS", "SKY_LIGHT_GAIN", "SKY_LIGHT_STEP_CLAMP",
    "HAZE_TOLERANCE", "HAZE_DAMP", "HAZE_STEP_CLAMP", "FAR_GROUND_PERCENTILE",
    "CLOUD_SKY_MIN_SPREAD_L", "CLOUD_TOLERANCE", "CLOUD_DAMP", "CLOUD_STEP_CLAMP",
)

REGIONS: Tuple[str, ...] = ("sky", "ground", "aircraft")

# -- colour science -------------------------------------------------------------------

#: sRGB (D65) linear RGB -> CIE XYZ (IEC 61966-2-1).
_SRGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
#: The D65 white point, Y = 1.
_D65 = (0.95047, 1.0, 1.08883)
#: Rec. 709 / sRGB luminance weights.
_LUMA = (0.2126729, 0.7151522, 0.0721750)


def _np():
    import numpy as np

    return np


def srgb_to_linear(rgb):
    """sRGB -> linear 0..1, per IEC 61966-2-1. An integer array is 8-bit
    (0..255); a float array is already 0..1."""
    np = _np()
    raw = np.asarray(rgb)
    v = raw.astype(np.float64)
    if np.issubdtype(raw.dtype, np.integer):
        v = v / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def linear_to_xyz(linear):
    np = _np()
    return np.asarray(linear, dtype=np.float64) @ np.asarray(_SRGB_TO_XYZ).T


def xyz_to_lab(xyz):
    np = _np()
    xyz = np.asarray(xyz, dtype=np.float64) / np.asarray(_D65)
    eps, kappa = 216.0 / 24389.0, 24389.0 / 27.0
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def srgb_to_lab(rgb):
    return xyz_to_lab(linear_to_xyz(srgb_to_linear(rgb)))


def luminance(linear):
    np = _np()
    return np.asarray(linear, dtype=np.float64) @ np.asarray(_LUMA)


def ciede2000(lab1, lab2):
    """CIEDE2000 colour difference (Sharma, Wu & Dalal 2005), kL = kC = kH = 1.
    Broadcasts over leading axes; the last axis is (L*, a*, b*)."""
    np = _np()
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cbar7 = ((C1 + C2) / 2.0) ** 7
    G = 0.5 * (1.0 - np.sqrt(Cbar7 / (Cbar7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + G) * a1, (1.0 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, np.where(dh < -180.0, dh + 360.0, dh))
    dh = np.where(C1p * C2p == 0.0, 0.0, dh)
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2.0))
    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0
    hsum = h1p + h2p
    hbarp = np.where(np.abs(h1p - h2p) > 180.0,
                     np.where(hsum < 360.0, (hsum + 360.0) / 2.0, (hsum - 360.0) / 2.0),
                     hsum / 2.0)
    hbarp = np.where(C1p * C2p == 0.0, hsum, hbarp)
    T = (1.0 - 0.17 * np.cos(np.radians(hbarp - 30.0)) + 0.24 * np.cos(np.radians(2.0 * hbarp))
         + 0.32 * np.cos(np.radians(3.0 * hbarp + 6.0)) - 0.20 * np.cos(np.radians(4.0 * hbarp - 63.0)))
    dtheta = 30.0 * np.exp(-(((hbarp - 275.0) / 25.0) ** 2))
    Cbarp7 = Cbarp ** 7
    Rc = 2.0 * np.sqrt(Cbarp7 / (Cbarp7 + 25.0 ** 7))
    Sl = 1.0 + 0.015 * (Lbarp - 50.0) ** 2 / np.sqrt(20.0 + (Lbarp - 50.0) ** 2)
    Sc = 1.0 + 0.045 * Cbarp
    Sh = 1.0 + 0.015 * Cbarp * T
    Rt = -np.sin(np.radians(2.0 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2
                   + Rt * (dCp / Sc) * (dHp / Sh))


# -- regions --------------------------------------------------------------------------


def region_masks(id_mask, depth=None, aircraft_ids: Iterable[int] = (1,)) -> Dict[str, Any]:
    """{"sky", "ground", "aircraft"} boolean masks of the frame.

    ``id_mask``: the label bundle's ID image (0 = background, the primary
    airframe int_id 1). ``depth``: metres, +inf for sky (frame_NNNN_depth.f32);
    without it, sky and ground cannot be told apart and the non-aircraft
    pixels become one ``scene`` region (sky and ground then absent)."""
    np = _np()
    ids = np.asarray(id_mask)
    aircraft = np.isin(ids, np.asarray(sorted({int(i) for i in aircraft_ids}), dtype=ids.dtype))
    out: Dict[str, Any] = {"aircraft": aircraft}
    if depth is None:
        out["scene"] = ~aircraft
        return out
    depth = np.asarray(depth, dtype=np.float64)
    if depth.shape != ids.shape:
        raise LookMatchError("look_match.inputs", f"the depth image is {depth.shape[::-1]} and the ID "
                                            f"mask {ids.shape[::-1]} (width, height)")
    sky = ~np.isfinite(depth) & ~aircraft
    out["sky"] = sky
    out["ground"] = ~sky & ~aircraft
    return out


def far_ground_mask(ground, depth, percentile: float = FAR_GROUND_PERCENTILE):
    """The ground at or beyond the depth percentile (None if too few pixels)."""
    np = _np()
    if depth is None or ground is None or int(ground.sum()) < MIN_REGION_PIXELS:
        return None
    depth = np.asarray(depth, dtype=np.float64)
    cut = float(np.percentile(depth[ground], percentile))
    far = ground & (depth >= cut)
    return far if int(far.sum()) >= MIN_REGION_PIXELS else None


def _iqr(values) -> float:
    np = _np()
    p25, p75 = np.percentile(values, [25.0, 75.0])
    return float(p75 - p25)


def region_stats(rgb, mask) -> Optional[Dict[str, Any]]:
    """The statistics of one region of one frame (``rgb``: (h, w, 3) sRGB)."""
    np = _np()
    pixels = int(np.asarray(mask).sum())
    if pixels < MIN_REGION_PIXELS:
        return None
    srgb = np.asarray(rgb)[mask]
    linear = srgb_to_linear(srgb)
    Y = np.maximum(luminance(linear), Y_FLOOR)
    lab = xyz_to_lab(linear_to_xyz(linear))
    p05, p50, p95 = (float(v) for v in np.percentile(Y, [5.0, 50.0, 95.0]))
    mean_linear = linear.mean(axis=0)
    mean_lab = xyz_to_lab(linear_to_xyz(mean_linear))
    return {
        "pixels": pixels,
        "y_mean": float(Y.mean()),
        "y_median": p50,
        "y_p05": p05,
        "y_p95": p95,
        "mean_linear_rgb": [float(v) for v in mean_linear],
        "mean_lab": [float(v) for v in mean_lab],
        "chroma_mean": float(np.hypot(lab[:, 1], lab[:, 2]).mean()),
        "l_iqr": _iqr(lab[:, 0]),
        "shadow_depth_stops": float(math.log2(p50 / p05)),
        "dynamic_range_stops": float(math.log2(p95 / p05)),
    }


def _ratio(a: float, b: float) -> Optional[float]:
    return None if b <= 1.0e-9 else a / b


def compare_region(ref_rgb, rt_rgb, mask) -> Optional[Dict[str, Any]]:
    """Reference vs realtime over one region; None when the region is too small."""
    np = _np()
    ref = region_stats(ref_rgb, mask)
    rt = region_stats(rt_rgb, mask)
    if ref is None or rt is None:
        return None
    per_pixel = ciede2000(srgb_to_lab(np.asarray(ref_rgb)[mask]), srgb_to_lab(np.asarray(rt_rgb)[mask]))
    return {
        "reference": ref,
        "realtime": rt,
        "diff": {
            "luminance_stops": math.log2(rt["y_median"] / ref["y_median"]),
            "delta_e00_of_means": float(ciede2000(ref["mean_lab"], rt["mean_lab"])),
            "delta_e00_per_pixel_mean": float(per_pixel.mean()),
            "chroma_ratio": _ratio(rt["chroma_mean"], ref["chroma_mean"]),
            "contrast_ratio": _ratio(rt["l_iqr"], ref["l_iqr"]),
            "shadow_depth_stops": rt["shadow_depth_stops"] - ref["shadow_depth_stops"],
        },
    }


def compare(ref_rgb, rt_rgb, masks: Mapping[str, Any], depth=None) -> Dict[str, Any]:
    """Every region's comparison, the lit (ground + aircraft) pool, and the
    far-ground haze band. ``ref_rgb`` and ``rt_rgb``: (h, w, 3) sRGB of the
    same shot."""
    np = _np()
    ref_rgb = np.asarray(ref_rgb)
    rt_rgb = np.asarray(rt_rgb)
    if ref_rgb.shape != rt_rgb.shape or ref_rgb.ndim != 3 or ref_rgb.shape[2] != 3:
        raise LookMatchError("look_match.not_same_shot",
                             f"the reference is {ref_rgb.shape} and the realtime frame "
                             f"{rt_rgb.shape}; both must be the same (height, width, 3)")
    regions: Dict[str, Any] = {}
    skipped: Dict[str, str] = {}
    for name, mask in masks.items():
        if mask is None:
            continue
        if mask.shape != ref_rgb.shape[:2]:
            raise LookMatchError("look_match.inputs", f"the {name} mask is {mask.shape[::-1]} and the "
                                                f"frames {ref_rgb.shape[1::-1]} (width, height)")
        row = compare_region(ref_rgb, rt_rgb, mask)
        if row is None:
            skipped[name] = f"{int(mask.sum())} pixels, under MIN_REGION_PIXELS {MIN_REGION_PIXELS}"
        else:
            regions[name] = row
    lit_parts = [masks[n] for n in ("ground", "aircraft", "scene") if masks.get(n) is not None]
    lit = None
    if lit_parts:
        lit_mask = np.logical_or.reduce(lit_parts)
        lit = compare_region(ref_rgb, rt_rgb, lit_mask)
    far = far_ground_mask(masks.get("ground"), depth)
    haze = None
    if far is not None:
        ref_l = srgb_to_lab(ref_rgb[far])[:, 0]
        rt_l = srgb_to_lab(rt_rgb[far])[:, 0]
        haze = {"pixels": int(far.sum()), "percentile": FAR_GROUND_PERCENTILE,
                "reference_l_iqr": _iqr(ref_l), "realtime_l_iqr": _iqr(rt_l),
                "contrast_ratio": _ratio(_iqr(rt_l), _iqr(ref_l))}
    return {"regions": regions, "skipped": skipped, "lit": lit, "far_ground": haze}


# -- the current look (read from the realtime run's render.json) -------------------------


def find_key(doc: Any, key: str) -> Optional[Any]:
    """The first value under ``key`` anywhere in a JSON document (depth first)."""
    if isinstance(doc, dict):
        if key in doc:
            return doc[key]
        for value in doc.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(doc, list):
        for value in doc:
            found = find_key(value, key)
            if found is not None:
                return found
    return None


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def current_look(render: Optional[Mapping[str, Any]], beauty_plan: Optional[Mapping[str, Any]] = None,
                 world_overrides: Optional[Mapping[str, Any]] = None,
                 preset: Optional[str] = None) -> Dict[str, Any]:
    """The look constants the realtime frame was rendered with, each with
    where it was read: the beauty-look plan (the sidecar, or the copy the
    render.json echoes), ``look_applied.world_beauty`` (the preset), the
    world overrides in force, ``look_applied.lighting`` (the sky light
    scale), else the tables' own defaults."""
    from core.scene import beauty_look, world_beauty

    render = render or {}
    look_record = render.get("beauty_look") if isinstance(render.get("beauty_look"), dict) else {}
    plan = copy.deepcopy(dict(beauty_plan)) if beauty_plan else copy.deepcopy(look_record.get("plan") or {})
    sources: Dict[str, str] = {}
    ev100 = _number(((plan.get("exposure") or {}).get("ev100")))
    sources["ev100"] = "beauty_look plan" if ev100 is not None else "absent (no EV100 in the plan)"
    grade = plan.get("color_grade")
    if not isinstance(grade, dict):
        name = plan.get("grade") if plan.get("grade") in beauty_look.GRADES else "desert_noon"
        grade = {k: copy.deepcopy(beauty_look.GRADES[name][k]) for k in
                 ("ColorSaturation", "ColorContrast", "ColorGamma", "ColorGain", "ColorOffset",
                  "WhiteTemp", "WhiteTint")}
        sources["color_grade"] = f"beauty_look.GRADES[{name!r}] (the plan carries none)"
    else:
        sources["color_grade"] = "beauty_look plan"
    world = find_key(render, "world_beauty")
    world = world if isinstance(world, dict) else {}
    if preset is None and world.get("preset") in world_beauty.PRESETS:
        preset = world["preset"]
        sources["preset"] = "look_applied.world_beauty.preset"
    elif preset is not None:
        if preset not in world_beauty.PRESETS:
            raise LookMatchError("look_match.inputs", f"preset {preset!r} is not one of {list(world_beauty.PRESETS)}")
        sources["preset"] = "stated"
    else:
        sources["preset"] = "absent (no world_beauty record): the haze suggestion is not written"
    overrides = copy.deepcopy(dict(world_overrides or {}))
    ap = None
    if preset is not None:
        ap = _number(((overrides.get("atmosphere") or {}).get(preset) or {}).get("aerial_perspective_scale"))
        if ap is not None:
            sources["aerial_perspective_scale"] = "the world overrides in force"
        else:
            recorded = world.get("atmosphere") if isinstance(world.get("atmosphere"), dict) else {}
            ap = _number(recorded.get("aerial_perspective_scale"))
            if ap is not None:
                sources["aerial_perspective_scale"] = "look_applied.world_beauty.atmosphere"
            else:
                ap = world_beauty.ATMOSPHERE[preset]["aerial_perspective_scale"]
                sources["aerial_perspective_scale"] = f"world_beauty.ATMOSPHERE[{preset!r}]"
    cloud = _number((overrides.get("constants") or {}).get("cloud_extinction_scale"))
    if cloud is not None:
        sources["cloud_extinction_scale"] = "the world overrides in force"
    else:
        cloud = world_beauty.CLOUD_EXTINCTION_SCALE
        sources["cloud_extinction_scale"] = "world_beauty.CLOUD_EXTINCTION_SCALE"
    lighting = find_key(render, "lighting")
    sky = _number(lighting.get("sky_light_scale")) if isinstance(lighting, dict) else None
    if sky is not None and sky >= 0.0:
        sources["sky_light_scale"] = "look_applied.lighting.sky_light_scale"
    else:
        sky = 1.0
        sources["sky_light_scale"] = "1 (no -sky-light-scale on the realtime run)"
    return {"plan": plan, "ev100": ev100, "color_grade": copy.deepcopy(grade), "preset": preset,
            "aerial_perspective_scale": ap, "cloud_extinction_scale": cloud,
            "sky_light_scale": sky, "world_overrides": overrides, "sources": sources}


# -- suggestions ---------------------------------------------------------------------------


def _clamp(value: float, bounds: Tuple[float, float]) -> float:
    return min(max(value, bounds[0]), bounds[1])


def _r4(value: float) -> float:
    return round(float(value), 4)


def suggest(comparison: Mapping[str, Any], current: Mapping[str, Any]) -> Dict[str, Any]:
    """The suggested look changes, each with the metric that drove it.

    Returns ``{"suggestions": [...], "within_tolerance": [...],
    "not_judged": [...], "beauty_look": <patched plan or None>,
    "world_overrides": <merged overrides>, "command_flags": [...]}``."""
    from core.scene import world_beauty

    suggestions: List[Dict[str, Any]] = []
    within: List[str] = []
    not_judged: List[str] = []
    plan = copy.deepcopy(dict(current.get("plan") or {}))
    grade = copy.deepcopy(dict(current["color_grade"]))
    overrides = copy.deepcopy(dict(current.get("world_overrides") or {}))
    flags: List[str] = []
    lit = comparison.get("lit")
    regions = comparison.get("regions", {})

    def add(constant, before, after, metric, reason):
        suggestions.append({"constant": constant, "from": before, "to": after,
                            "metric": metric, "reason": reason})

    # 1. exposure: the lit pool's median luminance, in stops.
    if lit is None:
        not_judged.append("exposure: no lit (ground or aircraft) region")
    else:
        stops = lit["diff"]["luminance_stops"]
        if abs(stops) <= EXPOSURE_TOLERANCE_STOPS:
            within.append(f"exposure ({stops:+.3f} stops)")
        elif current.get("ev100") is None:
            not_judged.append(f"exposure: {stops:+.3f} stops off, but the plan states no EV100 to move")
        else:
            step = max(-EXPOSURE_STEP_MAX_STOPS, min(EXPOSURE_STEP_MAX_STOPS, EXPOSURE_GAIN * stops))
            after = _r4(current["ev100"] + step)
            add("beauty_look.exposure.ev100", current["ev100"], after,
                {"lit_luminance_stops": _r4(stops)},
                f"the realtime lit regions are {stops:+.2f} stops from the reference; a higher "
                f"EV100 darkens (damped by EXPOSURE_GAIN {EXPOSURE_GAIN:g})")
            plan.setdefault("exposure", {})["ev100"] = after

    # 2. colour cast: chromaticity ratios of the lit pool's mean linear RGB.
    if lit is not None:
        de = lit["diff"]["delta_e00_of_means"]
        if de <= COLOUR_TOLERANCE_DE00:
            within.append(f"colour cast (dE00 {de:.2f})")
        else:
            ref_rgb = lit["reference"]["mean_linear_rgb"]
            rt_rgb = lit["realtime"]["mean_linear_rgb"]
            ref_y = sum(w * c for w, c in zip(_LUMA, ref_rgb))
            rt_y = sum(w * c for w, c in zip(_LUMA, rt_rgb))
            ratios = [((r / ref_y) / (t / rt_y)) if t > 1e-9 and ref_y > 1e-9 and rt_y > 1e-9 else 1.0
                      for r, t in zip(ref_rgb, rt_rgb)]
            norm = sum(w * k for w, k in zip(_LUMA, ratios)) or 1.0
            steps = [_clamp((k / norm) ** GAIN_DAMP, GAIN_STEP_CLAMP) for k in ratios]
            before = list(grade["ColorGain"])
            after = [_r4(before[i] * steps[i]) for i in range(3)] + [before[3]]
            add("beauty_look.color_grade.ColorGain", before, after,
                {"lit_delta_e00_of_means": _r4(de)},
                "the realtime lit regions carry a colour cast against the reference; each channel "
                "moves by its chromaticity ratio (luminance kept) ^ GAIN_DAMP")
            grade["ColorGain"] = after
        # 3. saturation.
        ratio = lit["diff"]["chroma_ratio"]
        if ratio is None:
            not_judged.append("saturation: the reference lit regions have no chroma")
        elif abs(ratio - 1.0) <= SATURATION_TOLERANCE:
            within.append(f"saturation (chroma ratio {ratio:.3f})")
        else:
            before = list(grade["ColorSaturation"])
            step = _clamp((1.0 / ratio) ** SATURATION_DAMP, SATURATION_STEP_CLAMP)
            after = before[:3] + [_r4(before[3] * step)]
            add("beauty_look.color_grade.ColorSaturation", before, after,
                {"lit_chroma_ratio": _r4(ratio)},
                "realtime mean CIELAB chroma / the reference's; ColorSaturation's overall term "
                "moves by its inverse ^ SATURATION_DAMP")
            grade["ColorSaturation"] = after
        # 4. mid-tone contrast.
        ratio = lit["diff"]["contrast_ratio"]
        if ratio is None:
            not_judged.append("contrast: the reference lit regions are flat")
        elif abs(ratio - 1.0) <= CONTRAST_TOLERANCE:
            within.append(f"contrast (L* IQR ratio {ratio:.3f})")
        else:
            before = list(grade["ColorContrast"])
            step = _clamp((1.0 / ratio) ** CONTRAST_DAMP, CONTRAST_STEP_CLAMP)
            after = before[:3] + [_r4(before[3] * step)]
            add("beauty_look.color_grade.ColorContrast", before, after,
                {"lit_l_iqr_ratio": _r4(ratio)},
                "realtime L* interquartile spread / the reference's; ColorContrast's overall "
                "term moves by its inverse ^ CONTRAST_DAMP")
            grade["ColorContrast"] = after
        # 5. shadow depth -> the sky light (the fill).
        diff = lit["diff"]["shadow_depth_stops"]
        if abs(diff) <= SHADOW_TOLERANCE_STOPS:
            within.append(f"shadow depth ({diff:+.3f} stops)")
        else:
            before = float(current["sky_light_scale"])
            step = _clamp(2.0 ** (SKY_LIGHT_GAIN * diff), SKY_LIGHT_STEP_CLAMP)
            after = _r4(before * step)
            add("-sky-light-scale", before, after, {"lit_shadow_depth_stops": _r4(diff)},
                f"the realtime shadows sit {diff:+.2f} stops deeper under the mid-tones than the "
                f"reference's; the sky light is the fill (2 ^ (SKY_LIGHT_GAIN x difference))")
            flags.append(f"-sky-light-scale={after:g}")

    # 6. haze: the far ground's contrast.
    haze = comparison.get("far_ground")
    if haze is None or haze.get("contrast_ratio") is None:
        not_judged.append("haze: no far-ground band (no depth, or too little ground)")
    elif current.get("preset") is None:
        not_judged.append("haze: the world preset is unknown (pass --preset)")
    else:
        ratio = haze["contrast_ratio"]
        if abs(ratio - 1.0) <= HAZE_TOLERANCE:
            within.append(f"haze (far-ground L* IQR ratio {ratio:.3f})")
        else:
            before = float(current["aerial_perspective_scale"])
            step = _clamp(ratio ** HAZE_DAMP, HAZE_STEP_CLAMP)
            after = _r4(before * step)
            preset = current["preset"]
            add(f"world_beauty.atmosphere.{preset}.aerial_perspective_scale", before, after,
                {"far_ground_l_iqr_ratio": _r4(ratio)},
                "realtime far-ground L* spread / the reference's: a crisper far ground than the "
                "reference wants more aerial perspective (a larger scale), and the reverse")
            overrides.setdefault("atmosphere", {}).setdefault(preset, {})["aerial_perspective_scale"] = after

    # 7. clouds: the sky's L* spread.
    sky = regions.get("sky")
    if sky is None:
        not_judged.append("clouds: no sky region")
    elif sky["reference"]["l_iqr"] < CLOUD_SKY_MIN_SPREAD_L:
        not_judged.append(f"clouds: the reference sky is uniform (L* IQR {sky['reference']['l_iqr']:.2f} "
                          f"< CLOUD_SKY_MIN_SPREAD_L {CLOUD_SKY_MIN_SPREAD_L:g})")
    else:
        ratio = sky["diff"]["contrast_ratio"]
        if abs(ratio - 1.0) <= CLOUD_TOLERANCE:
            within.append(f"clouds (sky L* IQR ratio {ratio:.3f})")
        else:
            before = float(current["cloud_extinction_scale"])
            step = _clamp((1.0 / ratio) ** CLOUD_DAMP, CLOUD_STEP_CLAMP)
            after = _r4(before * step)
            add("world_beauty.constants.cloud_extinction_scale", before, after,
                {"sky_l_iqr_ratio": _r4(ratio)},
                "realtime sky L* spread / the reference's: denser clouds (a larger extinction) "
                "brighten the sunlit tops and darken the bases against the sky")
            overrides.setdefault("constants", {})["cloud_extinction_scale"] = after
    if sky is not None:
        stops = sky["diff"]["luminance_stops"]
        if lit is not None:
            stops -= lit["diff"]["luminance_stops"]
        if abs(stops) > EXPOSURE_TOLERANCE_STOPS:
            not_judged.append(f"sky brightness: {stops:+.2f} stops against the lit regions' offset; no "
                              f"look constant owns it (the atmosphere's own scattering): reported only")

    problems = world_beauty.validate_overrides(overrides)
    if problems:  # pragma: no cover - the writer above only emits schema names
        raise LookMatchError("look_match.inputs", "the world overrides written would not load: " + "; ".join(problems))
    patched = None
    if plan:
        plan["color_grade"] = grade
        patched = plan
    return {"suggestions": suggestions, "within_tolerance": within, "not_judged": not_judged,
            "beauty_look": patched, "color_grade": grade, "world_overrides": overrides,
            "command_flags": flags}


# -- the bundle -----------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rgb(path: Path):
    np = _np()
    from PIL import Image

    try:
        with Image.open(path) as image:
            return np.asarray(image.convert("RGB"))
    except (OSError, ValueError) as exc:
        raise LookMatchError("look_match.inputs", f"{path} cannot be read as an image ({exc})")


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def frame_bundle(frame: Path) -> Dict[str, Any]:
    """The files beside a frame: ``<stem>_mask.png``, ``<stem>_depth.f32``
    and the camera directory's ``render.json`` (each None when absent)."""
    frame = Path(frame)
    if not frame.is_file():
        raise LookMatchError("look_match.inputs", f"{frame} is not a file")
    mask = frame.with_name(f"{frame.stem}_mask.png")
    depth = frame.with_name(f"{frame.stem}_depth.f32")
    render = frame.parent / "render.json"
    return {"frame": frame, "mask": mask if mask.is_file() else None,
            "depth": depth if depth.is_file() else None,
            "render": read_json(render) if render.is_file() else None}


def aircraft_ids(*docs: Optional[Mapping[str, Any]]) -> List[int]:
    """The int_ids of every ``class: aircraft`` object any document's
    ``objects[]`` lists; [1] (the primary airframe, always int_id 1) if none."""
    found = set()
    for doc in docs:
        objects = find_key(doc, "objects") if doc else None
        if isinstance(objects, list):
            for obj in objects:
                if isinstance(obj, dict) and obj.get("class") == "aircraft" and isinstance(obj.get("int_id"), int):
                    found.add(int(obj["int_id"]))
    return sorted(found) or [1]


def quality_of(render: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not render:
        return None
    scene = render.get("scene")
    value = scene.get("render_quality") if isinstance(scene, dict) else None
    return value if isinstance(value, str) else None


def match(reference: Path, realtime: Path, *, beauty_look_path: Optional[Path] = None,
          world_overrides_path: Optional[Path] = None, preset: Optional[str] = None,
          same_shot_depth_tolerance: float = 0.01) -> Dict[str, Any]:
    """The whole look match of two frames on disk: the report, with the
    patched beauty-look plan and the world overrides inside it."""
    np = _np()
    from core.capture.labels import read_depth_f32

    ref = frame_bundle(reference)
    rt = frame_bundle(realtime)
    ref_q, rt_q = quality_of(ref["render"]), quality_of(rt["render"])
    if ref_q is not None and ref_q != "pathtrace":
        raise LookMatchError("look_match.quality", f"the reference was rendered at -quality={ref_q}; "
                                             f"it must be -quality=pathtrace")
    if rt_q is not None and rt_q != "beauty":
        raise LookMatchError("look_match.quality", f"the realtime frame was rendered at -quality={rt_q}; "
                                             f"it must be -quality=beauty")
    ref_rgb, rt_rgb = read_rgb(ref["frame"]), read_rgb(rt["frame"])
    if ref_rgb.shape != rt_rgb.shape:
        raise LookMatchError("look_match.not_same_shot", f"the reference is {ref_rgb.shape[1::-1]} px and the "
                                                   f"realtime frame {rt_rgb.shape[1::-1]} px")
    labels = rt if rt["mask"] is not None else ref
    if labels["mask"] is None:
        raise LookMatchError("look_match.inputs", f"neither frame has a label mask beside it "
                                            f"({ref['frame'].stem}_mask.png); render with labels")
    from PIL import Image

    with Image.open(labels["mask"]) as image:
        ids = np.asarray(image)
    if ids.ndim != 2 or ids.shape != rt_rgb.shape[:2]:
        raise LookMatchError("look_match.inputs", f"{labels['mask'].name} is not a single-channel ID image "
                                            f"of the frame's size")
    height, width = ids.shape
    depth = None
    depth_note = "no depth beside the realtime frame: sky and ground are one region"
    depth_bundle = rt if rt["depth"] is not None else (ref if ref["depth"] is not None else None)
    if depth_bundle is not None:
        try:
            depth = read_depth_f32(depth_bundle["depth"], width, height)
        except ValueError as exc:
            raise LookMatchError("look_match.inputs", str(exc))
        depth_note = f"{depth_bundle['depth'].name} ({'realtime' if depth_bundle is rt else 'reference'})"
    if ref["depth"] is not None and rt["depth"] is not None:
        other = read_depth_f32(ref["depth"], width, height)
        both = np.isfinite(depth) & np.isfinite(other)
        sky_mismatch = float(np.mean(np.isfinite(depth) != np.isfinite(other)))
        rel = float(np.median(np.abs(depth[both] - other[both]) / np.maximum(depth[both], 1e-3))) \
            if both.any() else 0.0
        if rel > same_shot_depth_tolerance or sky_mismatch > same_shot_depth_tolerance:
            raise LookMatchError("look_match.not_same_shot",
                                 f"the two depth images differ (median relative {rel:.4f}, sky "
                                 f"pixels disagreeing {sky_mismatch:.4f}; tolerance "
                                 f"{same_shot_depth_tolerance:g}): not the same pose")
    ids_aircraft = aircraft_ids(rt["render"], ref["render"])
    masks = region_masks(ids, depth, ids_aircraft)
    comparison = compare(ref_rgb, rt_rgb, masks, depth)

    if beauty_look_path is None:
        # The web app writes runs/<id>/beauty_look.json; the frame sits in
        # runs/<id>/frames/<camera>/. Else the plan render.json echoes.
        for parent in list(rt["frame"].parents)[:3]:
            if (parent / "beauty_look.json").is_file():
                beauty_look_path = parent / "beauty_look.json"
                break
    plan = read_json(beauty_look_path) if beauty_look_path else None
    if beauty_look_path and plan is None:
        raise LookMatchError("look_match.inputs", f"{beauty_look_path} is not a JSON beauty-look sidecar")
    overrides_file = world_overrides_path
    if overrides_file is None and rt["render"]:
        recorded = (find_key(rt["render"], "world_beauty") or {}).get("overrides_file")
        if isinstance(recorded, str) and recorded and Path(recorded).is_file():
            overrides_file = Path(recorded)
    overrides = read_json(overrides_file) if overrides_file else None
    if overrides_file and overrides is None:
        raise LookMatchError("look_match.inputs", f"{overrides_file} is not a JSON world overrides file")
    from core.scene import world_beauty

    if overrides:
        problems = world_beauty.validate_overrides(overrides)
        if problems:
            raise LookMatchError("look_match.inputs", f"{overrides_file}: " + "; ".join(problems))
    current = current_look(rt["render"], plan, overrides, preset)
    result = suggest(comparison, current)

    def described(bundle, quality):
        return {"frame": str(bundle["frame"]), "sha256": sha256_of(bundle["frame"]),
                "render_quality": quality,
                "path_tracer": find_key(bundle["render"], "path_tracer") if bundle["render"] else None}

    return {
        "format": LOOK_MATCH_FORMAT,
        "version": LOOK_MATCH_VERSION,
        "reference": described(ref, ref_q),
        "realtime": described(rt, rt_q),
        "labels": {"mask": str(labels["mask"]), "aircraft_int_ids": ids_aircraft, "depth": depth_note,
                   "region_pixels": {k: int(v.sum()) for k, v in masks.items()}},
        "current": {k: v for k, v in current.items() if k not in ("plan", "world_overrides")},
        "comparison": comparison,
        "suggestions": result["suggestions"],
        "within_tolerance": result["within_tolerance"],
        "not_judged": result["not_judged"],
        "beauty_look": result["beauty_look"],
        "color_grade": result["color_grade"],
        "world_beauty_overrides": result["world_overrides"],
        "command_flags": result["command_flags"],
        "converged": not result["suggestions"],
        "uncalibrated": list(UNCALIBRATED),
        "note": ("VISUAL ONLY: suggestions for the beauty look's UNCALIBRATED constants, damped; "
                 "apply, re-render the realtime beauty and match again until converged. The "
                 "frames are display-referred, so a stop here is not a stop of scene light."),
    }


def write_outputs(report: Mapping[str, Any], out_dir: Path) -> Dict[str, Optional[str]]:
    """Write ``look_match.json``, ``world_beauty_overrides.json`` and, when a
    plan was available, ``beauty_look.json`` (ASCII, as the host reads it)."""
    from core.scene.beauty_look import write_beauty_look

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Optional[str]] = {}
    path = out_dir / "look_match.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    written["report"] = str(path)
    path = out_dir / "world_beauty_overrides.json"
    path.write_text(json.dumps(report["world_beauty_overrides"], indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    written["world_beauty_overrides"] = str(path)
    if report.get("beauty_look"):
        written["beauty_look"] = str(write_beauty_look(report["beauty_look"], out_dir / "beauty_look.json"))
    else:
        written["beauty_look"] = None
    return written
