"""Pixel gate for the alpine horizon and tile level of detail.

Run on the WINDOWS laptop on two rendered frames of the same shot (baseline:
today's settings; candidate: a tier of alpine_horizon_lod.json). A number from
this script counts as measured only when the frames came from that laptop.

Two metrics, both from pixels:

* gsd_ratio. In a ground box, the effective resolved size in pixels is
  0.5 / f50, f50 being the radial spatial frequency below which half of the
  box's luminance power lies (Hann window, mean removed; the median, because
  a higher fraction lands in the side lobes of hard texel edges). A coarser tile
  stretched over the same pixels moves power to low frequencies. Times the
  pixel's footprint at the box's slant distance it is an effective ground
  sample distance in metres; the gate is candidate / baseline, which needs no
  calibration. It is blind to sharp polygon edges of coarse tiles and to grain,
  so compare frames rendered with the same post-process settings.
* horizon_range_km. Per column the skyline is the first row from the top
  whose vertical luminance step leaves the sky's own noise. The row gives a
  depression angle (camera pitch and field of view are arguments); the 90th
  percentile depression over the columns (the lowest gaps between peaks) is
  inverted on the sphere to the ground range drawn there. It is a LOWER BOUND
  and saturates near the horizon: past `resolvable_km` the skyline moves less
  than two pixels, and a ridge above the horizon hides what is behind it.

Exit code 0 when the gate passes, 1 when it fails, 2 on bad input.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent


def _bake():
    spec = importlib.util.spec_from_file_location("alpine_horizon_lod_bake", LANE / "bake_alpine_horizon_lod.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _bake()


def luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec. 709 luma of an (H, W, 3+) array, as float in the input's units."""
    a = np.asarray(rgb, dtype=np.float64)
    if a.ndim == 2:
        return a
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def effective_px(lum_box: np.ndarray, power_fraction: float = 0.5) -> float:
    """0.5 / f50 of the box: the resolved feature size in pixels."""
    a = np.asarray(lum_box, dtype=np.float64)
    if a.shape[0] < 16 or a.shape[1] < 16:
        raise ValueError("the ground box must be at least 16 x 16 pixels")
    a = a - a.mean()
    a = a * np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    power = np.abs(np.fft.fft2(a)) ** 2
    fr = np.hypot(np.fft.fftfreq(a.shape[0])[:, None], np.fft.fftfreq(a.shape[1])[None, :])
    power[0, 0] = 0.0
    total = power.sum()
    if total <= 0.0:
        raise ValueError("the ground box is flat: no texture to measure")
    order = np.argsort(fr, axis=None)
    cumulative = np.cumsum(power.ravel()[order])
    f50 = fr.ravel()[order][np.searchsorted(cumulative, power_fraction * total)]
    return 0.5 / max(f50, 1e-9)


def skyline_rows(lum: np.ndarray, sky_rows: int = 24, sigma: float = 8.0) -> np.ndarray:
    """Per column, the first row from the top where the vertical step exceeds
    the sky's own noise; NaN where the column never leaves the sky."""
    a = np.asarray(lum, dtype=np.float64)
    kernel = np.ones(5) / 5.0
    smooth = np.apply_along_axis(lambda c: np.convolve(c, kernel, mode="same"), 0, a)
    step = np.abs(np.diff(smooth, axis=0))
    step[:3, :] = 0.0
    step[-3:, :] = 0.0
    sky = step[3:max(sky_rows, 8), :]
    floor = np.median(sky) + sigma * (1.4826 * np.median(np.abs(sky - np.median(sky))) + 1e-9)
    floor = max(floor, 0.004 * (a.max() - a.min() + 1e-9))
    hit = step > floor
    first = hit.argmax(axis=0)
    # the smoothing spreads the edge over its 5 rows: the edge itself is the
    # largest step just below the first row that left the noise
    window = np.stack([np.take_along_axis(step, np.minimum(first + k, step.shape[0] - 1)[None, :], 0)[0]
                       for k in range(6)])
    return np.where(hit.any(axis=0), first + window.argmax(axis=0) + 0.5, np.nan)


def depression_of_pixel_deg(row: float, col: float, width: int, height: int,
                            hfov_deg: float, pitch_deg: float) -> float:
    """Angle below the local horizontal of the ray through (row, col); roll 0."""
    f = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    x, y = col - (width - 1) / 2.0, row - (height - 1) / 2.0
    norm = math.sqrt(f * f + x * x + y * y)
    forward, up = f / norm, -y / norm
    p = math.radians(pitch_deg)
    return -math.degrees(math.asin(forward * math.sin(p) + up * math.cos(p)))


def measure(image: np.ndarray, *, hfov_deg: float, pitch_deg: float, height_above_ground_m: float,
            gsd_box, gsd_distance_m: float | None = None, columns=None) -> dict:
    lum = luminance(image)
    h, w = lum.shape
    x0, y0, x1, y1 = gsd_box
    eff = effective_px(lum[y0:y1, x0:x1])
    if gsd_distance_m is None:
        dep = depression_of_pixel_deg((y0 + y1) / 2.0, (x0 + x1) / 2.0, w, h, hfov_deg, pitch_deg)
        if dep <= bake.horizon_dip_deg(height_above_ground_m):
            raise ValueError("the ground box is at or above the horizon; give --gsd-distance-m")
        ground = bake.range_from_depression_m(dep, height_above_ground_m)
        gsd_distance_m = math.hypot(ground, height_above_ground_m)
    c0, c1 = columns if columns else (0, w)
    rows = skyline_rows(lum)[c0:c1]
    cols = np.arange(c0, c1)[~np.isnan(rows)]
    rows = rows[~np.isnan(rows)]
    if rows.size < 8:
        raise ValueError("no skyline found: fewer than 8 columns leave the sky")
    deps = np.array([depression_of_pixel_deg(r, c, w, h, hfov_deg, pitch_deg) for r, c in zip(rows, cols)])
    dep90 = float(np.percentile(deps, 90))
    range_m = bake.range_from_depression_m(dep90, height_above_ground_m)
    return {
        "effective_px": round(float(eff), 4),
        "gsd_distance_m": round(float(gsd_distance_m), 1),
        "gsd_m": round(float(eff * gsd_distance_m * bake.ifov_rad(hfov_deg, w)), 4),
        "skyline_row_median": round(float(np.median(rows)), 2),
        "skyline_depression_p90_deg": round(dep90, 4),
        "horizon_range_km": round(range_m / 1000.0, 2),
        "horizon_range_saturated": bool(dep90 <= bake.horizon_dip_deg(height_above_ground_m)),
        "skyline_columns": int(rows.size),
    }


def verdict(baseline: dict, candidate: dict, tier: int, plan: dict) -> dict:
    gate = plan["gate"]
    ratio = candidate["gsd_m"] / baseline["gsd_m"]
    ratio_max = gate["gsd_ratio_max"][str(tier)]
    range_min = min(gate["horizon_range_min_fraction_of_baseline"] * baseline["horizon_range_km"],
                    plan["horizon"]["skyline_resolvable_range_km"])
    range_min = max(range_min, min(gate["horizon_range_floor_km"], plan["horizon"]["skyline_resolvable_range_km"]))
    gsd_ok = ratio <= ratio_max
    range_ok = candidate["horizon_range_km"] >= range_min
    return {"tier": tier, "gsd_ratio": round(ratio, 4), "gsd_ratio_max": ratio_max, "gsd_pass": bool(gsd_ok),
            "horizon_range_km": candidate["horizon_range_km"], "horizon_range_min_km": round(range_min, 2),
            "horizon_pass": bool(range_ok), "pass": bool(gsd_ok and range_ok)}


def _load(path: str) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--tier", type=int, required=True, choices=[0, 1, 2, 3])
    ap.add_argument("--gsd-box", required=True, help="x0,y0,x1,y1 of textured ground, no aircraft, no sky")
    ap.add_argument("--gsd-distance-m", type=float, help="slant distance to the box; else from its row")
    ap.add_argument("--pitch-deg", type=float, required=True, help="camera pitch of the shot, up positive")
    ap.add_argument("--hfov-deg", type=float, default=bake.SHOT["hfov_deg"])
    ap.add_argument("--height-above-ground-m", type=float,
                    default=bake.SHOT["camera_altitude_amsl_m"] - bake.SHOT["reference_ground_amsl_m"])
    ap.add_argument("--columns", help="c0,c1 skyline columns to use (leave the aircraft out)")
    args = ap.parse_args(argv)
    try:
        box = tuple(int(v) for v in args.gsd_box.split(","))
        cols = tuple(int(v) for v in args.columns.split(",")) if args.columns else None
        plan = bake.build()
        results = {}
        for name in ("baseline", "candidate"):
            results[name] = measure(_load(getattr(args, name)), hfov_deg=args.hfov_deg, pitch_deg=args.pitch_deg,
                                    height_above_ground_m=args.height_above_ground_m, gsd_box=box,
                                    gsd_distance_m=args.gsd_distance_m, columns=cols)
        results["verdict"] = verdict(results["baseline"], results["candidate"], args.tier, plan)
    except (ValueError, OSError) as exc:
        print(f"measure_horizon_lod: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(results, indent=1, sort_keys=True))
    return 0 if results["verdict"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
