"""Gate V -- the visual overhaul's clauses, measured from pixels.

    python experiments/gate_v_visual.py --step v0 --skip-render   # measure runs/visual/v0/
    python experiments/gate_v_visual.py --step v0                 # render the sheet first, then measure
    python experiments/gate_v_visual.py --dir runs/webapp/<id>/frames/chase --skip-render
    python experiments/gate_v_visual.py --compare v0_before v0    # per-shot deltas, before -> after

docs/VISUAL_FIDELITY_PLAN.md §5 asks that every phase of the overhaul be
closed "by pixels, never by opinion", alongside Gate 6
(experiments/gate6_visual.py). This harness measures seven image clauses
per shot, from the contact sheet's PNGs (experiments/visual_contact_sheet.py,
``runs/visual/<step>/a.png .. d.png`` and their ``_mask.png``) or from a
render bundle's frames (``frame_NNNN.png`` with ``_mask.png`` and
``_depth.f32`` beside them):

  aerial_perspective  with the depth label: ground pixels binned by range;
                      farther bins must turn bluer (blue share of RGB rises
                      per decade of range), lose contrast (luma std / mean,
                      C = C0 * T) and move toward the sky's colour
  horizon_fill        a geometric horizon (the labels' polyline, a
                      ``<shot>_horizon.json`` sidecar or ``--horizon``):
                      the band just under it must be drawn ground (finite
                      depth, or not sky-coloured) and differ from the band
                      above it -- the 40 km island leaves an empty band
  cloud_fraction      the share of sky pixels that are cloud (low
                      saturation, not dark) against the weather's
                      cloud_cover, +/- CLOUD_TOLERANCE (plan §5, V6)
  exposure            90th-percentile luma in a band; clipped pixels at
                      most EXPOSURE_MAX_CLIP_FRACTION
  texel_detail        near-ground high-frequency energy: RMS of (luma -
                      3x3 box mean) / mean luma over the bottom third's
                      ground pixels -- a proxy for texel density (V3)
  specular            the airframe mask (ID 1) must hold a highlight:
                      pixels far brighter than the airframe's median
  edge_aliasing       Gate 6's number, imported (reported, not a gate)

Self-validation (plan §5: "or the pass is void"). Each graded clause is
also run on a control built from the same frame to carry exactly the
failure the clause exists to catch: depth shuffled among ground pixels
(no range ramp), the band under the horizon painted sky with infinite
depth, the sky painted clear or overcast against the expected cover, the
frame pushed EXPOSURE_CONTROL_GAIN stops-ish brighter, the bottom third
blurred, the airframe flattened to its median colour. A control that
PASSES makes the clause VOID: the measurement could not have said no.

What this harness does NOT claim. Every threshold below is a named
UNCALIBRATED constant, a starting value until a probe render on the
render machine sets it (docs/visual/PROBE_LOG.md is where calibrations are
recorded -- not by this file). The cloud classifier sees haze near the
horizon as cloud, and a sky-pixel fraction is not the overhead-dome
``cloud_cover`` -- it is compared anyway because it is what the frame
shows, and the basis says so. The texel proxy measures image detail, not
texels. Nothing here judges likeness to MSFS: that clause is the reader's
judgment (plan §5, last row) and stays labelled as such.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: Where the contact sheet's steps live (experiments/visual_contact_sheet.py).
VISUAL_ROOT = REPO / "runs" / "visual"
#: The contact sheet's fixed shots.
CONTACT_SHOTS = ("a", "b", "c", "d")
#: This harness's output beside the step's shots.json.
REPORT_NAME = "gate_v.json"

# -- thresholds: every one UNCALIBRATED (set by a probe render) -------------

#: Aerial perspective: range bins (log-spaced between the 5th and 95th
#: percentile ground depth), pixels a bin needs, far/near range span needed.
AP_BINS = 5                       # UNCALIBRATED
AP_MIN_BIN_PX = 200               # UNCALIBRATED
AP_MIN_DEPTH_SPAN = 3.0           # UNCALIBRATED (far / near, ratio)
#: Blue share b/(r+g+b) must rise at least this much per decade of range.
AP_MIN_BLUE_SLOPE = 0.004         # UNCALIBRATED (per log10 m)
#: Far-bin contrast / near-bin contrast must be at most this.
AP_MAX_CONTRAST_RATIO = 0.85      # UNCALIBRATED
#: Far-bin colour distance to the sky / near-bin distance, at most this.
AP_MAX_SKY_RATIO = 0.9            # UNCALIBRATED
#: The control's shuffle seed (fixed: the control is reproducible).
AP_CONTROL_SEED = 20261109

#: Horizon fill: band height under / over the horizon, pixels.
HORIZON_BAND_PX = 12              # UNCALIBRATED
#: Share of the under-band that must be drawn ground.
HORIZON_MIN_FILL = 0.9            # UNCALIBRATED
#: |under - over| mean luma / over mean luma, at least this.
HORIZON_MIN_CONTRAST = 0.04       # UNCALIBRATED
#: Without depth: an under-band pixel within this RGB distance (8-bit
#: counts) of the over-band mean is "sky-coloured", i.e. empty.
HORIZON_SKYLIKE_DIST = 12.0       # UNCALIBRATED
#: Share of image columns whose horizon is in frame, needed to grade.
HORIZON_MIN_COLUMNS = 0.5         # UNCALIBRATED
#: Heuristic horizon (no geometric one): row-mean luma window, pixels.
HORIZON_HEURISTIC_WINDOW = 8      # UNCALIBRATED

#: Cloud: a sky pixel is cloud at HSV saturation <= this and value >= the next.
CLOUD_MAX_SATURATION = 0.15       # UNCALIBRATED
CLOUD_MIN_VALUE = 60.0            # UNCALIBRATED (8-bit)
#: |measured - expected| at most this (plan §5 V6: +/- 15 %).
CLOUD_TOLERANCE = 0.15            # plan §5 states it; the classifier is UNCALIBRATED
#: Sky pixels needed to grade.
CLOUD_MIN_SKY_PX = 500            # UNCALIBRATED
#: The controls' painted skies: clear blue, overcast white.
CLOUD_CONTROL_CLEAR_RGB = (90.0, 140.0, 225.0)
CLOUD_CONTROL_OVERCAST_RGB = (205.0, 205.0, 210.0)

#: Exposure: the 90th-percentile luma band (8-bit) and the clip budget.
EXPOSURE_P90_MIN = 120.0          # UNCALIBRATED
EXPOSURE_P90_MAX = 240.0          # UNCALIBRATED
EXPOSURE_CLIP_LEVEL = 254.0       # any channel at or above is clipped
EXPOSURE_MAX_CLIP_FRACTION = 0.02 # UNCALIBRATED ("no clipping beyond N %")
EXPOSURE_CRUSH_LEVEL = 2.0        # luma at or below is crushed (reported only)
#: The control: the frame times this, clipped (a blown exposure).
EXPOSURE_CONTROL_GAIN = 4.0

#: Texel proxy: minimum normalised high-frequency RMS in the bottom third.
TEXEL_MIN_HF = 0.02               # UNCALIBRATED
TEXEL_MIN_PX = 1000               # UNCALIBRATED
#: The control: this many 3x3 box blurs over the bottom third.
TEXEL_CONTROL_BLUR_PASSES = 6

#: Specular: airframe pixels needed; a highlight pixel's luma is at least
#: SPEC_HIGHLIGHT_RATIO x the airframe median and at least SPEC_MIN_LUMA.
SPEC_MIN_AIRFRAME_PX = 200        # UNCALIBRATED
SPEC_HIGHLIGHT_RATIO = 1.6        # UNCALIBRATED
SPEC_MIN_LUMA = 180.0             # UNCALIBRATED (8-bit)
SPEC_MIN_HIGHLIGHT_PX = 5         # UNCALIBRATED
SPEC_MIN_FRACTION = 0.001         # UNCALIBRATED
SPEC_MAX_FRACTION = 0.25          # UNCALIBRATED (more is a blown airframe)
#: The primary airframe's int_id in the ID image (core/capture/labels.py).
AIRFRAME_INT_ID = 1

PASS, FAIL, NOT_RUN, VOID, INFO = "PASS", "FAIL", "NOT RUN", "VOID", "INFO"

UNCALIBRATED = (
    "AP_BINS", "AP_MIN_BIN_PX", "AP_MIN_DEPTH_SPAN", "AP_MIN_BLUE_SLOPE",
    "AP_MAX_CONTRAST_RATIO", "AP_MAX_SKY_RATIO", "HORIZON_BAND_PX",
    "HORIZON_MIN_FILL", "HORIZON_MIN_CONTRAST", "HORIZON_SKYLIKE_DIST",
    "HORIZON_MIN_COLUMNS", "HORIZON_HEURISTIC_WINDOW", "CLOUD_MAX_SATURATION",
    "CLOUD_MIN_VALUE", "CLOUD_MIN_SKY_PX", "EXPOSURE_P90_MIN", "EXPOSURE_P90_MAX",
    "EXPOSURE_MAX_CLIP_FRACTION", "TEXEL_MIN_HF", "TEXEL_MIN_PX",
    "SPEC_MIN_AIRFRAME_PX", "SPEC_HIGHLIGHT_RATIO", "SPEC_MIN_LUMA",
    "SPEC_MIN_HIGHLIGHT_PX", "SPEC_MIN_FRACTION", "SPEC_MAX_FRACTION",
)


def thresholds() -> Dict[str, Any]:
    """Every UNCALIBRATED constant by name, for the report."""
    module = sys.modules[__name__]
    return {name: getattr(module, name) for name in UNCALIBRATED}


# -- pixels -----------------------------------------------------------------


def luma(rgb):
    """Rec. 709 weights on the 8-bit encoded values (a luma, not a
    luminance). ``rgb`` is (h, w, 3)."""
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def saturation(rgb):
    import numpy as np

    top = rgb.max(axis=-1)
    bottom = rgb.min(axis=-1)
    return np.where(top > 0, (top - bottom) / np.maximum(top, 1e-9), 0.0)


def box3(image):
    import numpy as np

    padded = np.pad(image, 1, mode="edge")
    total = np.zeros(image.shape, dtype=float)
    for dy in range(3):
        for dx in range(3):
            total += padded[dy:dy + image.shape[0], dx:dx + image.shape[1]]
    return total / 9.0


def erode(mask, steps: int = 1):
    import numpy as np

    out = np.asarray(mask, dtype=bool).copy()
    for _ in range(steps):
        inner = out.copy()
        inner[1:, :] &= out[:-1, :]
        inner[:-1, :] &= out[1:, :]
        inner[:, 1:] &= out[:, :-1]
        inner[:, :-1] &= out[:, 1:]
        out = inner
    return out


def load_png_rgb(path: Path):
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=float)


def load_id_mask(path: Path):
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=np.int64)


# -- clause results ----------------------------------------------------------


@dataclass
class Clause:
    name: str
    status: str
    values: Dict[str, Any] = field(default_factory=dict)
    control: Optional[Dict[str, Any]] = None
    basis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "values": self.values,
                "control": self.control, "basis": self.basis}


def _graded(name: str, measure, frame_inputs: dict, control_inputs: Optional[dict],
            basis: str) -> Clause:
    """Run ``measure`` on the frame and on its control; a control that
    passes voids a PASS (plan §5: "or the pass is void"). A FAIL stands
    whatever its control does: the frame itself said no, and reporting it
    as VOID would hide a real failure (an underexposed frame whose x4
    control lands in band, say)."""
    values = measure(**frame_inputs)
    if values.get("not_run"):
        return Clause(name, NOT_RUN, values, None, values.pop("not_run"))
    status = PASS if values.pop("passed") else FAIL
    control = None
    if control_inputs is not None:
        control = measure(**control_inputs)
        if control.get("not_run"):
            control = {"note": "the control could not run: " + control.pop("not_run"),
                       **control}
            status = VOID if status == PASS else status
        elif control.pop("passed"):
            if status == PASS:
                status = VOID
                control["note"] = "the control passed: the measurement could not say no"
            else:
                control["note"] = ("the control passed too; the frame's FAIL stands, "
                                   "but this control does not test it")
        else:
            control["note"] = "the control tripped"
    return Clause(name, status, values, control, basis)


# -- aerial perspective ------------------------------------------------------


def ground_mask(depth, ids):
    import numpy as np

    good = np.isfinite(depth) & (depth > 0)
    if ids is not None:
        good &= ids == 0
    return good


def sky_mask_from_depth(depth, ids):
    import numpy as np

    sky = ~np.isfinite(depth)
    if ids is not None:
        sky &= ids == 0
    return sky


def aerial_perspective_values(rgb, depth, ids) -> Dict[str, Any]:
    import numpy as np

    if depth is None:
        return {"not_run": "no depth label for this shot"}
    ground = ground_mask(depth, ids)
    if ground.sum() < AP_BINS * AP_MIN_BIN_PX:
        return {"not_run": f"{int(ground.sum())} ground pixels with depth; "
                           f"{AP_BINS * AP_MIN_BIN_PX} needed"}
    d = depth[ground].astype(float)
    near, far = np.percentile(d, 5), np.percentile(d, 95)
    if not near > 0 or far / near < AP_MIN_DEPTH_SPAN:
        return {"not_run": f"ground range {near:.0f}-{far:.0f} m spans less than "
                           f"x{AP_MIN_DEPTH_SPAN:g}"}
    colours = rgb[ground]
    light = luma(colours)
    edges = np.logspace(math.log10(near), math.log10(far), AP_BINS + 1)
    bins = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        inside = (d >= lo) & (d <= hi)
        if inside.sum() < AP_MIN_BIN_PX:
            continue
        mean_rgb = colours[inside].mean(axis=0)
        mean_l = float(light[inside].mean())
        bins.append({"range_m": float(math.sqrt(lo * hi)), "px": int(inside.sum()),
                     "mean_rgb": [round(float(c), 2) for c in mean_rgb],
                     "blue_share": float(mean_rgb[2] / max(mean_rgb.sum(), 1e-9)),
                     "contrast": float(light[inside].std() / max(mean_l, 1e-9))})
    if len(bins) < 2:
        return {"not_run": "fewer than two range bins hold enough pixels"}
    x = np.log10([b["range_m"] for b in bins])
    blue = np.array([b["blue_share"] for b in bins])
    slope = float(np.polyfit(x, blue, 1)[0])
    contrast_ratio = float(bins[-1]["contrast"] / max(bins[0]["contrast"], 1e-9))
    sky = sky_mask_from_depth(depth, ids)
    sky_ratio = None
    if sky.sum() >= AP_MIN_BIN_PX:
        sky_rgb = rgb[sky].mean(axis=0)
        near_d = float(np.linalg.norm(np.array(bins[0]["mean_rgb"]) - sky_rgb))
        far_d = float(np.linalg.norm(np.array(bins[-1]["mean_rgb"]) - sky_rgb))
        sky_ratio = far_d / max(near_d, 1e-9)
    passed = (slope >= AP_MIN_BLUE_SLOPE and contrast_ratio <= AP_MAX_CONTRAST_RATIO
              and (sky_ratio is None or sky_ratio <= AP_MAX_SKY_RATIO))
    return {"passed": passed, "blue_slope_per_decade": slope,
            "contrast_ratio_far_near": contrast_ratio,
            "sky_distance_ratio_far_near": sky_ratio,
            "near_m": float(near), "far_m": float(far), "bins": bins}


def shuffled_depth(depth, ids, seed: int = AP_CONTROL_SEED):
    """The control: the same depth values dealt at random among the ground
    pixels -- every bin then holds the same mix, so no ramp can show."""
    import numpy as np

    out = depth.copy()
    ground = ground_mask(depth, ids)
    values = out[ground]
    np.random.default_rng(seed).shuffle(values)
    out[ground] = values
    return out


def measure_aerial_perspective(rgb, depth, ids) -> Clause:
    control = None if depth is None else {
        "rgb": rgb, "depth": shuffled_depth(depth, ids), "ids": ids}
    return _graded("aerial_perspective", aerial_perspective_values,
                   {"rgb": rgb, "depth": depth, "ids": ids}, control,
                   "ground pixels binned by depth label; bluer, lower-contrast and "
                   "nearer the sky's colour with range; control: depth shuffled")


# -- horizon -----------------------------------------------------------------


def horizon_rows_from_polyline(polyline, width: int):
    """Per-column horizon row (float) by linear interpolation of the
    labels' ``polyline_px`` ([[u, v], ...])."""
    import numpy as np

    points = sorted((float(u), float(v)) for u, v in polyline)
    us = np.array([p[0] for p in points])
    vs = np.array([p[1] for p in points])
    return np.interp(np.arange(width) + 0.5, us, vs)


def heuristic_horizon_row(rgb, ids=None,
                          window: int = HORIZON_HEURISTIC_WINDOW) -> Optional[int]:
    """The row with the largest step in row-mean luma between the
    ``window`` rows above and below it. A guess, never a graded horizon:
    over a 40 km island it finds the island's edge, not the horizon."""
    import numpy as np

    light = luma(rgb).astype(float)
    if ids is not None:
        light = np.where(ids == 0, light, np.nan)
    with np.errstate(all="ignore"):
        rows = np.nanmean(light, axis=1)
    if np.all(np.isnan(rows)) or rgb.shape[0] < 2 * window + 1:
        return None
    rows = np.where(np.isnan(rows), np.nanmean(rows), rows)
    best, best_step = None, -1.0
    for r in range(window, rgb.shape[0] - window):
        step = abs(rows[r - window:r].mean() - rows[r:r + window].mean())
        if step > best_step:
            best, best_step = r, step
    return best


def horizon_fill_values(rgb, depth, ids, horizon) -> Dict[str, Any]:
    import numpy as np

    if horizon is None:
        return {"not_run": "no geometric horizon (labels polyline, sidecar or --horizon)"}
    height, width = rgb.shape[:2]
    band = HORIZON_BAND_PX
    light = luma(rgb)
    over_px, under_px, under_filled = [], [], []
    over_rgb = []
    columns = 0
    for u in range(width):
        v = int(round(float(horizon[u])))
        if v - band < 0 or v + band >= height:
            continue
        columns += 1
        rows_over = slice(v - band, v)
        rows_under = slice(v + 1, v + 1 + band)
        keep_over = np.ones(band, bool) if ids is None else ids[rows_over, u] == 0
        keep_under = np.ones(band, bool) if ids is None else ids[rows_under, u] == 0
        over_px.append(light[rows_over, u][keep_over])
        over_rgb.append(rgb[rows_over, u][keep_over])
        under_px.append(light[rows_under, u][keep_under])
        if depth is not None:
            under_filled.append(np.isfinite(depth[rows_under, u][keep_under]))
        else:
            under_filled.append(rgb[rows_under, u][keep_under])
    if columns < HORIZON_MIN_COLUMNS * width:
        return {"not_run": f"horizon in frame in {columns}/{width} columns"}
    over = np.concatenate(over_px)
    under = np.concatenate(under_px)
    if over.size == 0 or under.size == 0:
        return {"not_run": "the aircraft covers the horizon bands"}
    over_mean = float(over.mean())
    contrast = abs(float(under.mean()) - over_mean) / max(over_mean, 1.0)
    if depth is not None:
        fill = float(np.concatenate(under_filled).mean())
        fill_source = "depth"
    else:
        sky_rgb = np.concatenate(over_rgb).mean(axis=0)
        under_rgb = np.concatenate(under_filled)
        skylike = np.linalg.norm(under_rgb - sky_rgb, axis=1) < HORIZON_SKYLIKE_DIST
        fill = float(1.0 - skylike.mean())
        fill_source = "colour against the band above"
    passed = fill >= HORIZON_MIN_FILL and contrast >= HORIZON_MIN_CONTRAST
    return {"passed": passed, "fill": fill, "fill_source": fill_source,
            "contrast": contrast, "columns": columns}


def emptied_horizon(rgb, depth, horizon):
    """The control: the band under the horizon painted with the band
    above's colour and given infinite depth -- the empty band."""
    import numpy as np

    out = rgb.copy()
    out_depth = None if depth is None else depth.copy()
    height, width = rgb.shape[:2]
    band = HORIZON_BAND_PX
    for u in range(width):
        v = int(round(float(horizon[u])))
        if v - band < 0 or v + band >= height:
            continue
        out[v + 1:v + 1 + band, u] = rgb[v - band:v, u].mean(axis=0)
        if out_depth is not None:
            out_depth[v + 1:v + 1 + band, u] = np.inf
    return out, out_depth


def measure_horizon_fill(rgb, depth, ids, horizon, horizon_source: str) -> Clause:
    if horizon is not None and horizon_source == "heuristic":
        values = horizon_fill_values(rgb, depth, ids, horizon)
        values.pop("passed", None)
        values.pop("not_run", None)
        return Clause("horizon_fill", NOT_RUN, values, None,
                      "heuristic horizon only (numbers reported): it finds the "
                      "terrain's edge, so it cannot see an empty band")
    control = None
    if horizon is not None:
        c_rgb, c_depth = emptied_horizon(rgb, depth, horizon)
        control = {"rgb": c_rgb, "depth": c_depth, "ids": ids, "horizon": horizon}
    return _graded("horizon_fill", horizon_fill_values,
                   {"rgb": rgb, "depth": depth, "ids": ids, "horizon": horizon}, control,
                   f"horizon from {horizon_source}; the {HORIZON_BAND_PX} px under it "
                   "drawn and unlike the band above; control: that band emptied")


# -- clouds ------------------------------------------------------------------


def sky_mask(rgb, depth, ids, horizon) -> Tuple[Optional[Any], str]:
    import numpy as np

    if depth is not None:
        return sky_mask_from_depth(depth, ids), "depth (+inf is sky)"
    if horizon is None:
        return None, "none"
    rows = np.arange(rgb.shape[0])[:, None]
    sky = rows < np.asarray(horizon)[None, :]
    if ids is not None:
        sky &= ids == 0
    return sky, "rows above the horizon"


def cloud_values(rgb, sky, expected) -> Dict[str, Any]:
    if sky is None:
        return {"not_run": "no sky mask (no depth, no horizon)"}
    count = int(sky.sum())
    if count < CLOUD_MIN_SKY_PX:
        return {"not_run": f"{count} sky pixels; {CLOUD_MIN_SKY_PX} needed"}
    pixels = rgb[sky]
    cloud = (saturation(pixels) <= CLOUD_MAX_SATURATION) & (pixels.max(axis=-1) >= CLOUD_MIN_VALUE)
    fraction = float(cloud.mean())
    out: Dict[str, Any] = {"cloud_fraction": fraction, "sky_px": count,
                           "expected_cover": expected}
    if expected is None:
        out["not_run"] = "no expected cloud_cover for this shot (measured fraction reported)"
        return out
    out["error"] = fraction - float(expected)
    out["passed"] = abs(out["error"]) <= CLOUD_TOLERANCE
    return out


def painted_sky(rgb, sky, colour):
    out = rgb.copy()
    out[sky] = colour
    return out


def measure_cloud(rgb, depth, ids, horizon, expected, expected_source: str) -> Clause:
    sky, sky_source = sky_mask(rgb, depth, ids, horizon)
    control = None
    if sky is not None and expected is not None:
        colour = CLOUD_CONTROL_CLEAR_RGB if expected > 0.5 else CLOUD_CONTROL_OVERCAST_RGB
        control = {"rgb": painted_sky(rgb, sky, colour), "sky": sky, "expected": expected}
    return _graded("cloud_fraction", cloud_values,
                   {"rgb": rgb, "sky": sky, "expected": expected}, control,
                   f"sky from {sky_source}; expected cover from {expected_source}; a sky-"
                   "pixel fraction, not the overhead-dome cover, and haze reads as "
                   "cloud; control: the sky painted clear or overcast against it")


# -- exposure ----------------------------------------------------------------


def exposure_values(rgb) -> Dict[str, Any]:
    import numpy as np

    light = luma(rgb)
    p90 = float(np.percentile(light, 90))
    clipped = float((rgb.max(axis=-1) >= EXPOSURE_CLIP_LEVEL).mean())
    crushed = float((light <= EXPOSURE_CRUSH_LEVEL).mean())
    passed = (EXPOSURE_P90_MIN <= p90 <= EXPOSURE_P90_MAX
              and clipped <= EXPOSURE_MAX_CLIP_FRACTION)
    return {"passed": passed, "luma_p90": p90, "clipped_fraction": clipped,
            "crushed_fraction": crushed, "luma_mean": float(light.mean())}


def measure_exposure(rgb) -> Clause:
    import numpy as np

    blown = np.clip(rgb * EXPOSURE_CONTROL_GAIN, 0.0, 255.0)
    return _graded("exposure", exposure_values, {"rgb": rgb}, {"rgb": blown},
                   f"luma p90 in [{EXPOSURE_P90_MIN:g}, {EXPOSURE_P90_MAX:g}], clipped "
                   f"<= {EXPOSURE_MAX_CLIP_FRACTION:.0%}; crushed is reported only; "
                   f"control: the frame x{EXPOSURE_CONTROL_GAIN:g}")


# -- near-ground detail ------------------------------------------------------


def bottom_third_ground(shape, depth, ids):
    import numpy as np

    height = shape[0]
    region = np.zeros(shape[:2], dtype=bool)
    region[height - height // 3:, :] = True
    if depth is not None:
        region &= np.isfinite(depth)
    if ids is not None:
        region &= erode(ids == 0, 2)
    return region


def texel_values(rgb, region) -> Dict[str, Any]:
    import numpy as np

    count = int(region.sum())
    if count < TEXEL_MIN_PX:
        return {"not_run": f"{count} near-ground pixels; {TEXEL_MIN_PX} needed"}
    light = luma(rgb).astype(float)
    high = light - box3(light)
    mean = float(light[region].mean())
    energy = float(np.sqrt(np.mean(high[region] ** 2)) / max(mean, 1.0))
    return {"passed": energy >= TEXEL_MIN_HF, "hf_energy": energy, "px": count}


def blurred_region(rgb, region, passes: int = TEXEL_CONTROL_BLUR_PASSES):
    out = rgb.copy()
    for channel in range(3):
        plane = rgb[..., channel].astype(float)
        for _ in range(passes):
            plane = box3(plane)
        out[..., channel][region] = plane[region]
    return out


def measure_texel_detail(rgb, depth, ids) -> Clause:
    region = bottom_third_ground(rgb.shape, depth, ids)
    return _graded("texel_detail", texel_values, {"rgb": rgb, "region": region},
                   {"rgb": blurred_region(rgb, region), "region": region},
                   "RMS(luma - 3x3 mean) / mean luma over the bottom third's ground "
                   "(an image-detail proxy, not texels); control: that region blurred")


# -- aircraft material -------------------------------------------------------


def airframe_mask(ids):
    if ids is None:
        return None
    primary = ids == AIRFRAME_INT_ID
    return primary if primary.any() else ids > 0


def specular_values(rgb, airframe) -> Dict[str, Any]:
    import numpy as np

    if airframe is None:
        return {"not_run": "no label mask for this shot"}
    inner = erode(airframe, 1)
    count = int(inner.sum())
    if count < SPEC_MIN_AIRFRAME_PX:
        return {"not_run": f"{count} interior airframe pixels; {SPEC_MIN_AIRFRAME_PX} needed"}
    light = luma(rgb)[inner]
    median = float(np.median(light))
    cut = max(SPEC_MIN_LUMA, SPEC_HIGHLIGHT_RATIO * median)
    highlight = int((light >= cut).sum())
    fraction = highlight / count
    passed = (highlight >= SPEC_MIN_HIGHLIGHT_PX
              and SPEC_MIN_FRACTION <= fraction <= SPEC_MAX_FRACTION)
    return {"passed": passed, "highlight_fraction": fraction, "highlight_px": highlight,
            "airframe_px": count, "median_luma": median,
            "peak_over_median": float(light.max() / max(median, 1.0)), "cut_luma": cut}


def flattened_airframe(rgb, airframe):
    import numpy as np

    out = rgb.copy()
    out[airframe] = np.median(rgb[airframe], axis=0)
    return out


def measure_specular(rgb, ids) -> Clause:
    airframe = airframe_mask(ids)
    control = None
    if airframe is not None and airframe.any():
        control = {"rgb": flattened_airframe(rgb, airframe), "airframe": airframe}
    return _graded("specular", specular_values, {"rgb": rgb, "airframe": airframe}, control,
                   "interior airframe pixels (ID 1) brighter than "
                   f"max({SPEC_MIN_LUMA:g}, {SPEC_HIGHLIGHT_RATIO:g} x median); "
                   "control: the airframe flattened to its median colour")


# -- edge aliasing (Gate 6's number) -----------------------------------------


def measure_aliasing(rgb, ids) -> Clause:
    import numpy as np

    if ids is None:
        return Clause("edge_aliasing", NOT_RUN, {}, None, "no label mask for this shot")
    from experiments.gate6_visual import measure_edge_aliasing

    frame = np.moveaxis(np.rint(rgb).astype(np.int64), 2, 0)
    row = measure_edge_aliasing(frame, ids > 0)
    return Clause("edge_aliasing", VOID if row["void"] else INFO,
                  {"energy": row["energy"], "control_energy": row["control_energy"]},
                  {"note": "Gate 6's own aliased control"},
                  "experiments/gate6_visual.py measure_edge_aliasing; reported, not a gate")


# -- inputs ------------------------------------------------------------------


@dataclass
class ShotInputs:
    key: str
    png: Path
    mask: Optional[Path] = None
    depth: Optional[Any] = None
    depth_source: str = "none"
    horizon: Optional[Any] = None
    horizon_source: str = "none"
    expected_cloud: Optional[float] = None
    cloud_source: str = "none"
    ground_ids: Tuple[int, ...] = (0,)
    ground_ids_source: str = "id 0 only"


_SIDE = re.compile(r"_(mask|depth|alone_\d+|normal|albedo|flow|horizon|id)$")


def discover_shots(directory: Path) -> List[Tuple[str, Path]]:
    """Contact-sheet layout (a..d .png) first, then a bundle's
    frame_NNNN.png, then any other plain PNG."""
    contact = [(k, directory / f"{k}.png") for k in CONTACT_SHOTS
               if (directory / f"{k}.png").is_file()]
    if contact:
        return contact
    frames = sorted(p for p in directory.glob("frame_*.png") if re.fullmatch(r"frame_\d+", p.stem))
    if frames:
        return [(p.stem, p) for p in frames]
    return [(p.stem, p) for p in sorted(directory.glob("*.png"))
            if not _SIDE.search(p.stem) and p.stem != "sheet" and not p.stem.startswith("compare_")]


def _number(value) -> Optional[float]:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def find_key(blob, key: str):
    """The first value under ``key`` anywhere in a JSON blob (depth first)."""
    if isinstance(blob, dict):
        if key in blob:
            return blob[key]
        children = blob.values()
    elif isinstance(blob, list):
        children = blob
    else:
        return None
    for child in children:
        found = find_key(child, key)
        if found is not None:
            return found
    return None


def stated_cloud_cover(blob) -> Optional[float]:
    """A cloud_cover the run actually drew, or None. A Quantity whose
    source is ``default`` is the randomization block's unsampled 0.0
    placeholder (core/scenario/randomization.py), and a plain number is
    only trusted beside a ``policy`` that names cloud_cover (card_block):
    the look block writes 0.0 when no policy drew it. Grading the storm
    sky (default-on in the web app) against either would be a label that
    does not match the pixels."""
    found: List[float] = []

    def walk(node):
        if found:
            return
        if isinstance(node, dict):
            value = node.get("cloud_cover")
            if isinstance(value, dict):
                if str(value.get("source", "default")) != "default":
                    number = _number(value)
                    if number is not None:
                        found.append(number)
                        return
            elif value is not None and _number(value) is not None \
                    and "cloud_cover" in json.dumps(node.get("policy"), default=str):
                found.append(_number(value))
                return
            children = node.values()
        elif isinstance(node, list):
            children = node
        else:
            return
        for child in children:
            walk(child)

    walk(blob)
    return found[0] if found else None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_depth(png: Path, frame_hint: Optional[Path], width: int, height: int):
    from core.capture.labels import read_depth_f32, read_depth_png

    candidates = [png.with_name(f"{png.stem}_depth")]
    if frame_hint is not None:
        candidates.append(frame_hint.with_name(f"{frame_hint.stem}_depth"))
    for stem in candidates:
        f32 = stem.with_suffix(".f32")
        if f32.is_file():
            try:
                return read_depth_f32(f32, width, height), str(f32)
            except ValueError:
                continue
        p16 = stem.with_suffix(".png")
        if p16.is_file():
            scale = _number(find_key(_read_json(stem.parent / "render.json") or {}, "depth_scale_m"))
            depth = read_depth_png(p16, scale or 0.1, 0.0)
            if depth.shape == (height, width):
                return depth, f"{p16} (16-bit)"
    return None, "none"


def _record_polyline(record):
    """``labels.horizon.polyline_px`` of one capture-manifest frame record."""
    if not isinstance(record, dict):
        return None
    horizon = (record.get("labels") or {}).get("horizon")
    if isinstance(horizon, dict) and horizon.get("polyline_px"):
        return horizon["polyline_px"]
    return None


def _horizon_from_sidecar(frame: Optional[Path]):
    """The frame's own sidecar, ``frame_NNNN.json`` beside the PNG
    (core/capture/manifest.py write_frame_sidecars): its ``frame`` record."""
    if frame is None:
        return None
    sidecar = _read_json(frame.with_suffix(".json"))
    return _record_polyline(sidecar.get("frame")) if isinstance(sidecar, dict) else None


def _horizon_from_manifest(run_dir: Path, frame_hint: Optional[Path]):
    """The run's ``capture_manifest.json`` frame whose ``file`` is this
    frame (matched by camera directory and name, never by a list index:
    the list holds every camera's frames)."""
    if frame_hint is None:
        return None
    manifest = _read_json(run_dir / "capture_manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("frames"), list):
        return None
    tail = (frame_hint.parent.name, frame_hint.name)
    for record in manifest["frames"]:
        if isinstance(record, dict) and tuple(Path(str(record.get("file", ""))).parts[-2:]) == tail:
            return _record_polyline(record)
    return None


def _ground_ids(png: Path, frame_hint: Optional[Path]) -> Tuple[Tuple[int, ...], str]:
    """The mask ids that are ground. The label mask gives terrain an id of
    its own (render.json objects: terrain int_id 2, role "scene"), so id 0
    alone is only the sky: on the first real renders every shot's
    aerial_perspective and texel_detail were NOT RUN ("0 ground pixels with
    depth") and horizon_fill FAILed on fill 0.0. Read from ``<shot>_ids.json``
    (experiments/visual_contact_sheet.py writes it), else from the frame's
    own render.json objects; id 0 alone when neither says."""
    side = _read_json(png.with_name(f"{png.stem}_ids.json"))
    if isinstance(side, dict) and isinstance(side.get("ground_ids"), list):
        ids = sorted({0, *(int(v) for v in side["ground_ids"] if isinstance(v, int))})
        return tuple(ids), f"{png.stem}_ids.json"
    for render in ([frame_hint.parent / "render.json"] if frame_hint is not None else []) + \
            [png.parent / "render.json"]:
        manifest = _read_json(render)
        if isinstance(manifest, dict) and isinstance(manifest.get("objects"), list):
            ids = {0}
            for row in manifest["objects"]:
                if isinstance(row, dict) and isinstance(row.get("int_id"), int) and (
                        row.get("role") == "scene" or row.get("class") == "terrain"):
                    ids.add(int(row["int_id"]))
            return tuple(sorted(ids)), str(render)
    return (0,), "id 0 only"


def ground_as_zero(ids, ground_ids: Sequence[int]):
    """The mask with every ground id folded into 0, the id every clause here
    reads as ground (the airframe, id 1 and its components, untouched)."""
    import numpy as np

    if ids is None or tuple(ground_ids) == (0,):
        return ids
    out = ids.copy()
    out[np.isin(ids, [i for i in ground_ids if i != 0])] = 0
    return out


def resolve_inputs(directory: Path, key: str, png: Path, width: int, height: int,
                   overrides: Optional[dict] = None) -> ShotInputs:
    overrides = overrides or {}
    shots = _read_json(directory / "shots.json") or {}
    row = (shots.get("shots") or {}).get(key, {}) if isinstance(shots, dict) else {}
    frame_hint = Path(row["frame"]) if row.get("frame") else None
    run_dir = Path(row["run_dir"]) if row.get("run_dir") else None
    inputs = ShotInputs(key, png)
    mask = png.with_name(f"{png.stem}_mask.png")
    inputs.mask = mask if mask.is_file() else None
    inputs.depth, inputs.depth_source = _load_depth(png, frame_hint, width, height)
    inputs.ground_ids, inputs.ground_ids_source = _ground_ids(png, frame_hint)

    polyline, source = None, "none"
    if key in overrides.get("horizon", {}):
        row_px = float(overrides["horizon"][key])
        polyline, source = [[0.0, row_px], [float(width), row_px]], "--horizon"
    if polyline is None:
        side = _read_json(png.with_name(f"{png.stem}_horizon.json"))
        found = find_key(side, "polyline_px") if side is not None else None
        if found:
            polyline, source = found, f"{png.stem}_horizon.json"
    if polyline is None:
        for frame in (frame_hint, png):
            found = _horizon_from_sidecar(frame)
            if found:
                polyline, source = found, f"{frame.with_suffix('.json').name} labels"
                break
    if polyline is None and run_dir is not None:
        found = _horizon_from_manifest(run_dir, frame_hint)
        if found:
            polyline, source = found, f"{run_dir / 'capture_manifest.json'} labels"
    if polyline is None:
        # A bundle measured in place: frames/<camera>/frame_NNNN.png.
        found = _horizon_from_manifest(png.parent.parent.parent, png)
        if found:
            polyline, source = found, "the bundle's capture_manifest.json labels"
    if polyline is not None:
        import numpy as np

        inputs.horizon = horizon_rows_from_polyline(polyline, width)
        inputs.horizon_source = source
        if not np.all(np.isfinite(inputs.horizon)):
            inputs.horizon, inputs.horizon_source = None, "none"

    if key in overrides.get("cloud", {}):
        inputs.expected_cloud, inputs.cloud_source = float(overrides["cloud"][key]), "--expect-cloud"
    elif _number(row.get("expected_cloud_cover")) is not None:
        inputs.expected_cloud = _number(row["expected_cloud_cover"])
        inputs.cloud_source = "shots.json expected_cloud_cover"
    else:
        places = [run_dir] if run_dir is not None else []
        places += [png.parent, png.parent.parent]
        for place in places:
            for name in ("spec.json", "card.json", "manifest.json", "render.json"):
                value = stated_cloud_cover(_read_json(place / name))
                if value is not None:
                    inputs.expected_cloud, inputs.cloud_source = value, str(place / name)
                    break
            if inputs.expected_cloud is not None:
                break
    return inputs


# -- one shot, one tree ------------------------------------------------------


def measure_frame(rgb, ids=None, depth=None, horizon=None, horizon_source: str = "none",
                  expected_cloud: Optional[float] = None,
                  cloud_source: str = "none") -> Dict[str, Clause]:
    """Every clause on one frame. ``rgb`` (h, w, 3) float 0..255; ``ids``
    the ID image (0 = background); ``depth`` metres, +inf sky;
    ``horizon`` per-column rows."""
    import numpy as np

    rgb = np.asarray(rgb, dtype=float)
    if horizon is None:
        guess = heuristic_horizon_row(rgb, ids)
        if guess is not None:
            horizon = np.full(rgb.shape[1], float(guess))
            horizon_source = "heuristic"
    clauses = [
        measure_aerial_perspective(rgb, depth, ids),
        measure_horizon_fill(rgb, depth, ids, horizon, horizon_source),
        measure_cloud(rgb, depth, ids, horizon, expected_cloud, cloud_source),
        measure_exposure(rgb),
        measure_texel_detail(rgb, depth, ids),
        measure_specular(rgb, ids),
        measure_aliasing(rgb, ids),
    ]
    return {clause.name: clause for clause in clauses}


def measure_shot(inputs: ShotInputs) -> Dict[str, Any]:
    rgb = load_png_rgb(inputs.png)
    ids = None
    if inputs.mask is not None:
        ids = load_id_mask(inputs.mask)
        if ids.shape != rgb.shape[:2]:
            ids = None
        ids = ground_as_zero(ids, inputs.ground_ids)
    clauses = measure_frame(rgb, ids, inputs.depth, inputs.horizon, inputs.horizon_source,
                            inputs.expected_cloud, inputs.cloud_source)
    return {"png": str(inputs.png), "mask": str(inputs.mask) if ids is not None else None,
            "depth": inputs.depth_source, "horizon": inputs.horizon_source,
            "ground_ids": list(inputs.ground_ids), "ground_ids_source": inputs.ground_ids_source,
            "expected_cloud": inputs.cloud_source,
            "clauses": {name: clause.to_dict() for name, clause in clauses.items()}}


def measure_tree(directory: Path, overrides: Optional[dict] = None) -> Dict[str, Any]:
    from PIL import Image

    shots = {}
    for key, png in discover_shots(directory):
        with Image.open(png) as image:
            width, height = image.size
        shots[key] = measure_shot(resolve_inputs(directory, key, png, width, height, overrides))
    return {"directory": str(directory), "thresholds": thresholds(),
            "calibration": "every threshold UNCALIBRATED until a probe render sets it",
            "not_claimed": "likeness to MSFS is the reader's judgment, not measured here",
            "shots": shots}


def write_report(directory: Path, report: Dict[str, Any]) -> Path:
    path = directory / REPORT_NAME
    path.write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    return path


# -- printing and comparing --------------------------------------------------


def headline(clause: Dict[str, Any]) -> Dict[str, float]:
    """The clause's scalar numbers (bins and other lists left out)."""
    return {k: float(v) for k, v in (clause.get("values") or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def report_lines(report: Dict[str, Any]) -> List[str]:
    lines = [f"Gate V  {report['directory']}  (every threshold UNCALIBRATED)"]
    for key, shot in report["shots"].items():
        lines.append(f"[{key}] depth={shot['depth']} horizon={shot['horizon']} "
                     f"cloud={shot['expected_cloud']}")
        for name, clause in shot["clauses"].items():
            numbers = ", ".join(f"{k}={v:.4g}" for k, v in headline(clause).items())
            note = "" if clause["status"] in (PASS, FAIL, INFO) else f" -- {clause['basis']}"
            lines.append(f"    {clause['status']:<7} {name:<19} {numbers}{note}")
    return lines


def compare_reports(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in [k for k in after["shots"] if k in before["shots"]]:
        rows = {}
        for name, clause in after["shots"][key]["clauses"].items():
            old = before["shots"][key]["clauses"].get(name)
            if old is None:
                continue
            a, b = headline(old), headline(clause)
            rows[name] = {"status": [old["status"], clause["status"]],
                          "delta": {k: {"before": a[k], "after": b[k], "delta": b[k] - a[k]}
                                    for k in b if k in a}}
        out[key] = rows
    return {"before": before["directory"], "after": after["directory"], "shots": out}


def compare_lines(comparison: Dict[str, Any]) -> List[str]:
    lines = [f"Gate V compare  before={comparison['before']}  after={comparison['after']}"]
    for key, rows in comparison["shots"].items():
        lines.append(f"[{key}]")
        for name, row in rows.items():
            before, after = row["status"]
            lines.append(f"    {name:<19} {before} -> {after}")
            for metric, d in row["delta"].items():
                lines.append(f"        {metric:<28} {d['before']:>10.4g} -> "
                             f"{d['after']:>10.4g}  ({d['delta']:+.4g})")
    return lines


# -- command line ------------------------------------------------------------


def _pairs(values: Sequence[str], flag: str) -> Dict[str, float]:
    out = {}
    for value in values or ():
        key, _, number = value.partition("=")
        if not key or not number:
            raise SystemExit(f"{flag} wants SHOT=NUMBER, not {value!r}")
        out[key] = float(number)
    return out


def resolve_dir(name: str, root: Path) -> Path:
    path = Path(name)
    if path.is_dir():
        return path
    from experiments.visual_contact_sheet import step_dir

    return step_dir(name, root)


def _report_for(directory: Path, overrides: dict) -> Dict[str, Any]:
    report = measure_tree(directory, overrides)
    write_report(directory, report)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate V visual clauses (docs/VISUAL_FIDELITY_PLAN.md §5)")
    ap.add_argument("--step", help="runs/visual/<step>/ (the contact sheet's step)")
    ap.add_argument("--dir", help="any directory of shots or a bundle's frames")
    ap.add_argument("--skip-render", action="store_true",
                    help="measure the PNGs already there; without it, --step renders "
                         "the contact sheet first (experiments/visual_contact_sheet.py)")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"),
                    help="per-shot deltas between two steps or directories")
    ap.add_argument("--horizon", action="append", metavar="SHOT=ROW",
                    help="a level geometric horizon row for a shot")
    ap.add_argument("--expect-cloud", action="append", metavar="SHOT=COVER",
                    help="the weather's cloud_cover (0..1) for a shot")
    ap.add_argument("--root", default=str(VISUAL_ROOT), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = Path(args.root)
    overrides = {"horizon": _pairs(args.horizon, "--horizon"),
                 "cloud": _pairs(args.expect_cloud, "--expect-cloud")}

    if args.compare:
        before_dir, after_dir = (resolve_dir(name, root) for name in args.compare)
        for directory in (before_dir, after_dir):
            if not directory.is_dir():
                print(f"NOT RUN {directory}: no such directory")
                return 2
        comparison = compare_reports(_report_for(before_dir, overrides),
                                     _report_for(after_dir, overrides))
        out = root / f"gate_v_compare_{before_dir.name}_vs_{after_dir.name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
        print("\n".join(compare_lines(comparison)))
        print(f"wrote {out}")
        return 0
    if bool(args.step) == bool(args.dir):
        ap.error("give exactly one of --step or --dir (or --compare A B)")
    if args.dir:
        directory = Path(args.dir)
        if not args.skip_render:
            ap.error("--dir measures existing frames only: pass --skip-render")
    else:
        directory = resolve_dir(args.step, root)
        if not args.skip_render:
            from experiments import visual_contact_sheet

            code = visual_contact_sheet.main(["--step", args.step, "--root", str(root)])
            if code != 0:
                return code
    if not directory.is_dir():
        print(f"NOT RUN {directory}: no such directory (render it, or check the name)")
        return 2
    report = measure_tree(directory, overrides)
    if not report["shots"]:
        print(f"NOT RUN {directory}: no shot PNGs")
        return 2
    path = write_report(directory, report)
    print("\n".join(report_lines(report)))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
