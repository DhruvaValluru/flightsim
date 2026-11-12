"""Pixel gate for the alpine detail normals. Run on the WINDOWS laptop (through
run_gate.py, which renders the frames and fills every argument). On the Mac
only its arithmetic is tested, on synthetic images; that is not a render result.

Inputs: three stills of one pinned spec and the baseline's depth image.
    baseline   detail off
    repeat     detail off again (the run-to-run noise floor)
    candidate  detail on
    depth      frame_NNNN_depth.f32 of the baseline (metres along the camera
               axis, +inf sky; converted to slant range here)

Nobody picks a box. The regions come from the baseline's depth alone, never
from the candidate, so the choice cannot favour it:
    ground    finite depth, slant range >= 200 m (nearer is the airframe)
    near box  the 96 px box wholly on ground with the smallest median range;
              it must lie within --near-max-m (where the detail is still strong)
    far mask  ground at or beyond --far-min-m (where every layer has faded to 0)
    skyline   per column, the first ground row under sky

Exit code and the "status" printed:
    0  provisional_pass   every check held. PROVISIONAL: thresholds predate any frame.
    1  fail               a check failed, or the candidate is the baseline again
    2  not_applicable     no ground near enough in this frame, or the two
                          detail-off frames differ too much to compare anything

Checks (all must hold for 0):
    gsd_ratio      candidate / baseline effective GSD, near box      <= 0.85
    diff_coherence lag-1 autocorrelation of candidate - baseline,
                   near box (per-pixel noise scores about 0)         >= 0.10
    clip_increase  rise in the near box's >= 250 fraction            <= 0.005
    far_contrast   candidate / baseline RMS contrast, far mask       in [0.95, 1.05]
    far_mean_abs   mean |candidate - baseline|, far mask, 8-bit      <= 2.0
    skyline_shift  median |row shift| of the skyline edge, px        <= 1.0
The far and skyline checks are skipped, and listed under "not_checked", when
the frame holds no such pixels. Effective GSD = pixel footprint / (2 x f95),
f95 the frequency below which 95 % of the box's gradient power lies. It is a
proxy for resolved detail, not a measurement of realism.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HFOV_DEG = 54.4
GSD_RATIO_MAX = 0.85
DIFF_COHERENCE_MIN = 0.10
FAR_CONTRAST_BAND = (0.95, 1.05)
FAR_MEAN_ABS_MAX = 2.0
SKYLINE_SHIFT_MAX_PX = 1.0
CLIP_INCREASE_MAX = 0.005
POWER_FRACTION = 0.95
# applicability: the two detail-off frames must agree this well
NULL_MEAN_ABS_MAX = 1.0
NULL_GSD_RATIO_TOL = 0.05
# the candidate must differ from the baseline by more than the repeat does
EFFECT_MIN_OVER_NULL = 0.25
AIRFRAME_MAX_M = 200.0
BOX_PX = 96
BOX_STRIDE_PX = 32
FAR_MIN_PIXELS = 1024
SKYLINE_WINDOW_PX = 6
EXIT = {"provisional_pass": 0, "fail": 1, "not_applicable": 2}
TIER_JSON = Path(__file__).resolve().parent / "out" / "alpine_detail_t0.json"


def luminance(rgb8: np.ndarray) -> np.ndarray:
    """Rec. 709 luma of an 8-bit RGB array, 0..255 (display-referred)."""
    return rgb8[..., :3].astype(np.float64) @ np.array([0.2126, 0.7152, 0.0722])


def footprint_m_per_px(distance_m: float, width_px: int, hfov_deg: float = HFOV_DEG) -> float:
    return 2.0 * distance_m * math.tan(math.radians(hfov_deg) / 2.0) / width_px


def slant_range_m(depth: np.ndarray, hfov_deg: float = HFOV_DEG) -> np.ndarray:
    """Camera-axis depth -> distance from the camera (square pixels)."""
    hgt, wid = depth.shape
    focal = (wid / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    yy, xx = np.mgrid[0:hgt, 0:wid]
    scale = np.sqrt(1.0 + ((xx - (wid - 1) / 2.0) / focal) ** 2 + ((yy - (hgt - 1) / 2.0) / focal) ** 2)
    with np.errstate(invalid="ignore"):
        return depth.astype(np.float64) * scale


def f95_cycles_per_px(lum: np.ndarray, fraction: float = POWER_FRACTION) -> float:
    """The frequency below which ``fraction`` of the detrended, Hann-windowed
    luminance gradient power lies. 0.5 is the pixel Nyquist limit."""
    hgt, wid = lum.shape
    yy, xx = np.mgrid[0:hgt, 0:wid]
    design = np.column_stack([np.ones(lum.size), xx.ravel(), yy.ravel()])
    coef, *_ = np.linalg.lstsq(design, lum.ravel(), rcond=None)
    resid = lum - (design @ coef).reshape(lum.shape)  # removes the lighting ramp
    resid = resid * np.outer(np.hanning(hgt), np.hanning(wid))
    radius = np.hypot(*np.meshgrid(np.fft.fftfreq(wid), np.fft.fftfreq(hgt), indexing="xy"))
    # gradient power (|F|^2 f^2): photographs fall off as 1/f^2, so plain power
    # is all in the lowest bins and would not see added fine relief
    power = np.abs(np.fft.fft2(resid)) ** 2 * radius ** 2
    keep = (radius > 1.5 / min(hgt, wid)) & (radius <= 0.5)
    order = np.argsort(radius[keep])
    cum = np.cumsum(power[keep][order])
    if cum[-1] <= 0.0:
        return 0.0
    return float(radius[keep][order][np.searchsorted(cum, fraction * cum[-1])])


def effective_gsd_m(lum: np.ndarray, footprint_m: float) -> float:
    f95 = f95_cycles_per_px(lum)
    return float("inf") if f95 <= 0.0 else footprint_m / (2.0 * f95)


def rms_contrast(values: np.ndarray) -> float:
    mean = float(values.mean())
    return 0.0 if mean <= 0.0 else float(values.std()) / mean


def lag1_coherence(diff: np.ndarray) -> float:
    """Mean of the horizontal and vertical lag-1 autocorrelation. Relief that
    spans several pixels scores well above 0; per-pixel noise scores about 0."""
    d = diff - diff.mean()
    var = float((d * d).mean())
    if var <= 1e-12:
        return 0.0
    return float(((d[:, 1:] * d[:, :-1]).mean() + (d[1:] * d[:-1]).mean()) / (2.0 * var))


def pick_near_box(ground: np.ndarray, rng_m: np.ndarray):
    """(box, median range) of the nearest BOX_PX square wholly on ground, or
    (None, inf). Ties go to the first box in row-major order."""
    hgt, wid = ground.shape
    best, best_range = None, float("inf")
    for y0 in range(0, hgt - BOX_PX + 1, BOX_STRIDE_PX):
        for x0 in range(0, wid - BOX_PX + 1, BOX_STRIDE_PX):
            if not ground[y0:y0 + BOX_PX, x0:x0 + BOX_PX].all():
                continue
            median = float(np.median(rng_m[y0:y0 + BOX_PX, x0:x0 + BOX_PX]))
            if median < best_range:
                best, best_range = (x0, y0, x0 + BOX_PX, y0 + BOX_PX), median
    return best, best_range


def skyline_edge_rows(lum: np.ndarray, depth: np.ndarray):
    """For each column whose top is sky with ground below, the row of the
    strongest vertical luminance step within SKYLINE_WINDOW_PX of the depth
    image's skyline. Returns (columns, rows)."""
    hgt = depth.shape[0]
    solid = np.isfinite(depth)
    first = np.argmax(solid, axis=0)
    cols = np.where(solid.any(axis=0) & ~solid[0] & (first >= SKYLINE_WINDOW_PX)
                    & (first < hgt - SKYLINE_WINDOW_PX))[0]
    step = np.abs(np.diff(lum, axis=0))
    rows = np.array([first[c] - SKYLINE_WINDOW_PX
                     + int(np.argmax(step[first[c] - SKYLINE_WINDOW_PX:first[c] + SKYLINE_WINDOW_PX, c]))
                     for c in cols], dtype=np.int64)
    return cols, rows


def crop(img: np.ndarray, box) -> np.ndarray:
    x0, y0, x1, y1 = box
    return img[y0:y1, x0:x1]


def gate(baseline: np.ndarray, repeat: np.ndarray, candidate: np.ndarray, depth: np.ndarray,
         near_max_m: float, far_min_m: float, hfov_deg: float = HFOV_DEG) -> dict:
    """Frames: 8-bit RGB, one size. ``depth``: (h, w) metres, +inf for sky."""
    if not (baseline.shape == repeat.shape == candidate.shape) or depth.shape != baseline.shape[:2]:
        raise ValueError(f"sizes differ: {baseline.shape} {repeat.shape} {candidate.shape} depth {depth.shape}")
    lb, lr, lc = luminance(baseline), luminance(repeat), luminance(candidate)
    rng_m = slant_range_m(depth, hfov_deg)
    ground = np.isfinite(rng_m) & (rng_m >= AIRFRAME_MAX_M)
    out = {"thresholds_provisional": True, "near_max_m": near_max_m, "far_min_m": far_min_m,
           "ground_fraction": float(ground.mean()), "checks": {}, "not_checked": []}

    def done(status: str, reason: str = "") -> dict:
        out["status"], out["reason"] = status, reason
        out["pass"] = status == "provisional_pass"
        return out

    box, near_range = pick_near_box(ground, rng_m)
    out["near_box"], out["near_range_m"] = box, (near_range if box else None)
    if box is None:
        return done("not_applicable", f"no {BOX_PX} px box of ground in the frame")
    if near_range > near_max_m:
        return done("not_applicable", f"nearest ground box is at {near_range:.0f} m, beyond {near_max_m:.0f} m: "
                                      "the detail is too faded there to measure in this frame")
    foot = footprint_m_per_px(near_range, baseline.shape[1], hfov_deg)
    nb, nr, nc = crop(lb, box), crop(lr, box), crop(lc, box)
    gsd_b, gsd_r, gsd_c = (effective_gsd_m(n, foot) for n in (nb, nr, nc))
    if not math.isfinite(gsd_b) or gsd_b <= 0.0:
        return done("not_applicable", "the baseline near box is featureless")
    null_abs = float(np.abs(lr - lb)[ground].mean())
    effect_abs = float(np.abs(nc - nb).mean())
    out.update({
        "near_footprint_m_per_px": foot, "baseline_gsd_m": gsd_b, "candidate_gsd_m": gsd_c,
        "null_mean_abs": null_abs, "null_gsd_ratio": gsd_r / gsd_b,
        "near_mean_abs": effect_abs, "near_null_mean_abs": float(np.abs(nr - nb).mean()),
        "gsd_ratio": gsd_c / gsd_b,
        "diff_coherence": lag1_coherence(nc - nb),
        "clip_increase": float(np.mean(nc >= 250.0) - np.mean(nb >= 250.0)),
    })
    if null_abs > NULL_MEAN_ABS_MAX or abs(out["null_gsd_ratio"] - 1.0) > NULL_GSD_RATIO_TOL:
        return done("not_applicable", "the two detail-off frames differ (rain, camera shake or a changed spec): "
                                      "nothing can be compared pixel to pixel")
    if effect_abs <= out["near_null_mean_abs"] + EFFECT_MIN_OVER_NULL:
        return done("fail", "no_effect: the candidate matches the baseline as closely as the repeat does. "
                            "The switch is not wired, the textures did not load, or Strength is 0")
    checks = out["checks"]
    checks["gsd_ratio"] = out["gsd_ratio"] <= GSD_RATIO_MAX
    checks["diff_coherence"] = out["diff_coherence"] >= DIFF_COHERENCE_MIN
    checks["clip_increase"] = out["clip_increase"] <= CLIP_INCREASE_MAX
    far = ground & (rng_m >= far_min_m)
    out["far_pixels"] = int(far.sum())
    if out["far_pixels"] >= FAR_MIN_PIXELS:
        cb = rms_contrast(lb[far])
        out["far_contrast"] = rms_contrast(lc[far]) / cb if cb > 0 else float("inf")
        out["far_mean_abs"] = float(np.abs(lc - lb)[far].mean())
        checks["far_contrast"] = FAR_CONTRAST_BAND[0] <= out["far_contrast"] <= FAR_CONTRAST_BAND[1]
        checks["far_mean_abs"] = out["far_mean_abs"] <= FAR_MEAN_ABS_MAX
    else:
        out["not_checked"] += ["far_contrast", "far_mean_abs"]
    cols, rows_b = skyline_edge_rows(lb, depth)
    out["skyline_columns"] = int(cols.size)
    if cols.size >= 16:
        out["skyline_shift"] = float(np.median(np.abs(skyline_edge_rows(lc, depth)[1] - rows_b)))
        checks["skyline_shift"] = out["skyline_shift"] <= SKYLINE_SHIFT_MAX_PX
    else:
        out["not_checked"].append("skyline_shift")
    failed = [name for name, ok in checks.items() if not ok]
    return done("fail", "failed: " + ", ".join(failed)) if failed else done("provisional_pass")


def default_ranges(tier_json: Path = TIER_JSON) -> tuple:
    """(near_max_m, far_min_m) from the bake's JSON: the largest fade_start_m
    (some layer is still at full strength inside it) and the largest fade_end_m."""
    layers = json.loads(Path(tier_json).read_text(encoding="utf-8"))["layers"].values()
    return max(l["fade_start_m"] for l in layers), max(l["fade_end_m"] for l in layers)


def write_crops(path: Path, baseline: np.ndarray, candidate: np.ndarray, box) -> None:
    """Baseline | candidate near box, 3x nearest-neighbour, for the eye check."""
    from PIL import Image

    pair = np.concatenate([crop(baseline, box), crop(candidate, box)], axis=1)
    Image.fromarray(pair).resize((pair.shape[1] * 3, pair.shape[0] * 3), Image.NEAREST).save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pixel gate for the alpine detail normals (see the module docstring).")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--repeat", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--depth", required=True, help="the baseline's frame_NNNN_depth.f32")
    ap.add_argument("--tier-json", default=str(TIER_JSON), help="where the fade distances are read from")
    ap.add_argument("--near-max-m", type=float, default=None)
    ap.add_argument("--far-min-m", type=float, default=None)
    ap.add_argument("--hfov-deg", type=float, default=HFOV_DEG)
    ap.add_argument("--crops", default=None, help="write the near box, baseline | candidate, here")
    args = ap.parse_args(argv)
    from PIL import Image

    frames = [np.asarray(Image.open(p).convert("RGB")) for p in (args.baseline, args.repeat, args.candidate)]
    hgt, wid = frames[0].shape[:2]
    raw = np.fromfile(args.depth, dtype="<f4")
    if raw.size != wid * hgt:
        print(f"depth: {raw.size} float32 values for a {wid}x{hgt} frame", file=sys.stderr)
        return EXIT["not_applicable"]
    near_max, far_min = default_ranges(Path(args.tier_json))
    result = gate(frames[0], frames[1], frames[2], raw.reshape(hgt, wid),
                  args.near_max_m or near_max, args.far_min_m or far_min, args.hfov_deg)
    if args.crops and result["near_box"]:
        write_crops(Path(args.crops), frames[0], frames[2], result["near_box"])
    print(json.dumps(result, indent=1))
    return EXIT[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
