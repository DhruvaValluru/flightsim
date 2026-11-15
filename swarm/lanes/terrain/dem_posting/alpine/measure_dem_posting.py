"""Pixel gate for terrain.dem_posting.alpine. Run on the Windows laptop on two
rendered frames of scenario 11 (the Mac only unit-tests the arithmetic on
synthetic images; a Mac run is never a result).

    python swarm\\lanes\\terrain\\dem_posting\\alpine\\measure_dem_posting.py ^
        --baseline <frame> --candidate <frame> ^
        --camera-lat <deg> --camera-lon <deg> --camera-alt-m <m MSL> ^
        --heading-deg <deg> --pitch-deg <deg> [--exclude-cols 480:800]

Metrics (JSON on stdout; exit 0 pass, 1 fail):
  horizon_range_km        95th percentile, over image columns, of the range of
                          the farthest GLO-90 ridge the rendered skyline
                          reaches. Per column the measured skyline elevation is
                          compared with the predicted skyline when terrain is
                          cut at each range; the column's range is the first
                          cut whose skyline is as high as the measured one.
  skyline_match_fraction  share of columns whose skyline is within
                          TOL_DEG of the full prediction.
  detail_px               effective sample size of the ground ROI in pixels:
                          the smallest lag at which the image structure
                          function stops growing like lag^2 (a texture
                          magnified k times is smooth below about k px).
  effective_gsd_m         detail_px * pixel footprint at --roi-range-m.
Pass: candidate horizon_range_km >= max(120, baseline) and
      skyline_match_fraction >= max(0.80, baseline) and
      detail_px <= --max-detail-px (2.0; 4.0 for tier 0, which trades ground
      detail for stability).
The skyline detector (strongest vertical luminance edge near the prediction)
and both tolerances are UNCALIBRATED until they have run on real frames; pass
--sky-mask (white = sky) frames if the renderer can write them.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent
EARTH_R_M = 6371008.8
TOL_DEG = 0.15
AZ_BIN_DEG = 0.1
RANGE_EDGES_M = np.geomspace(1_000.0, 300_000.0, 49)
MIN_RANGE_KM, MIN_MATCH = 120.0, 0.80
LAGS = (1, 2, 3, 4, 6, 8, 12, 16, 24, 32)
SMOOTH_SLOPE = 1.5


def load_reference(lane: Path = LANE) -> dict:
    plan = json.loads((lane / "alpine_dem_posting.json").read_text())
    rings = plan["rings"]
    meta = rings["files"]["alpine_skyline_ref.bin"]
    n_r, n_az = meta["n_r"], meta["n_az"]
    h = np.frombuffer((lane / "alpine_skyline_ref.bin").read_bytes(), dtype="<u2", count=n_r * n_az)
    edges = np.geomspace(meta["r_inner_m"], rings["r_outer_m"], n_r + 1)
    return {"h": h.reshape(n_r, n_az) * rings["height_scale_m"], "r": np.sqrt(edges[:-1] * edges[1:]),
            "lat": rings["centre_lat"], "lon": rings["centre_lon"], "k": plan["refraction_k"],
            "ifov": plan["camera"]["ifov_mrad"] * 1e-3, "hfov": plan["camera"]["hfov_deg"]}


def skyline_table(ref: dict, eye_lat: float, eye_lon: float, eye_alt_m: float) -> np.ndarray:
    """E[k, b]: skyline elevation (deg) in azimuth bin b from terrain within
    RANGE_EDGES_M[k+1] of the eye. Refraction by the effective-radius rule;
    meridian convergence between ring centre and eye is ignored (<0.1 deg)."""
    R = EARTH_R_M / (1.0 - ref["k"])
    n_r, n_az = ref["h"].shape
    az = np.radians((np.arange(n_az) + 0.5) * 360.0 / n_az)[None, :]
    theta = (ref["r"] / R)[:, None]
    rad = R + ref["h"]
    pts = np.stack([rad * np.sin(theta) * np.sin(az), rad * np.sin(theta) * np.cos(az), rad * np.cos(theta)], -1)
    north = math.radians(eye_lat - ref["lat"]) * EARTH_R_M
    east = math.radians(eye_lon - ref["lon"]) * EARTH_R_M * math.cos(math.radians(ref["lat"]))
    d = math.hypot(north, east) / R
    a = math.atan2(east, north)
    up = np.array([math.sin(d) * math.sin(a), math.sin(d) * math.cos(a), math.cos(d)])
    n_hat = np.array([0.0, 1.0, 0.0]) - up[1] * up
    n_hat /= np.linalg.norm(n_hat)
    e_hat = np.cross(n_hat, up)
    v = pts.reshape(-1, 3) - (R + eye_alt_m) * up
    rng = np.linalg.norm(v, axis=1)
    el = np.degrees(np.arcsin((v @ up) / rng))
    b = (np.degrees(np.arctan2(v @ e_hat, v @ n_hat)) % 360.0 / AZ_BIN_DEG).astype(int)
    k = np.searchsorted(RANGE_EDGES_M, rng) - 1
    ok = (k >= 0) & (k < RANGE_EDGES_M.size - 1)
    n_b = int(round(360.0 / AZ_BIN_DEG))
    table = np.full((RANGE_EDGES_M.size - 1, n_b), -90.0)
    np.maximum.at(table, (k[ok], b[ok] % n_b), el[ok])
    table = np.maximum.accumulate(table, axis=0)
    return np.maximum(table, np.maximum(np.roll(table, 1, 1), np.roll(table, -1, 1)))   # close 1-bin gaps


def pixel_angles(w: int, h: int, hfov_deg: float, heading_deg: float, pitch_deg: float):
    """(azimuth deg, elevation deg) of every pixel; zero roll, square pixels."""
    f = (w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    x = (np.arange(w) + 0.5 - w / 2.0)[None, :]
    y = (h / 2.0 - np.arange(h) - 0.5)[:, None]
    p = math.radians(pitch_deg)
    fwd = f * math.cos(p) - y * math.sin(p)
    up = f * math.sin(p) + y * math.cos(p)
    el = np.degrees(np.arctan2(up, np.hypot(fwd, x)))
    az = (heading_deg + np.degrees(np.arctan2(x, fwd))) % 360.0
    return az, el


def luma(path) -> np.ndarray:
    from PIL import Image

    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def lookup(table_row: np.ndarray, az_deg: np.ndarray) -> np.ndarray:
    return table_row[(az_deg / AZ_BIN_DEG).astype(int) % table_row.size]


def detect_skyline(img: np.ndarray, pred_rows: np.ndarray, window_px: int, sky_mask=None) -> np.ndarray:
    """Skyline row per column: first non-sky row of the mask, else the
    strongest vertical luminance edge within window_px of the prediction."""
    h, w = img.shape
    if sky_mask is not None:
        return np.argmax(sky_mask < 0.5, axis=0).astype(float)
    pad = np.pad(img, ((2, 2), (0, 0)), mode="edge")
    grad = np.abs((pad[3:-1] + pad[4:]) - (pad[:-4] + pad[1:-3]))[: h]       # edge between row r-1 and r
    rows = np.arange(h)[:, None]
    grad = np.where(np.abs(rows - pred_rows[None, :]) <= window_px, grad, -1.0)
    return np.argmax(grad, axis=0).astype(float)


def horizon_metrics(img: np.ndarray, table: np.ndarray, hfov: float, heading: float, pitch: float,
                    exclude=None, sky_mask=None, window_px: int = 60) -> dict:
    h, w = img.shape
    az, el = pixel_angles(w, h, hfov, heading, pitch)
    cols = np.arange(w)
    full_mid = lookup(table[-1], az[h // 2])
    pred = np.argmin(np.abs(el - full_mid[None, :]), axis=0)
    pred = np.argmin(np.abs(el - lookup(table[-1], az[pred, cols])[None, :]), axis=0)
    rows = np.clip(detect_skyline(img, pred, window_px, sky_mask).astype(int), 0, h - 1)
    m_el, m_az = el[rows, cols] + 0.5 * (el[0, 0] - el[1, 0]), az[rows, cols]   # edge sits half a pixel up
    b = (m_az / AZ_BIN_DEG).astype(int) % table.shape[1]
    column = table[:, b]                                    # [K, W]
    valid = m_el <= column[-1] + TOL_DEG                    # above the prediction: aircraft, cloud
    if exclude:
        valid[exclude[0]:exclude[1]] = False
    reach = np.argmax(column >= m_el[None, :] - TOL_DEG, axis=0)
    ranges_km = RANGE_EDGES_M[reach + 1] / 1e3
    matched = np.abs(m_el - column[-1]) <= TOL_DEG
    n = int(valid.sum())
    return {"columns_used": n,
            "horizon_range_km": round(float(np.percentile(ranges_km[valid], 95)), 1) if n else 0.0,
            "skyline_match_fraction": round(float(matched[valid].mean()), 4) if n else 0.0}


def detail_px(roi: np.ndarray) -> float:
    """Smallest lag (px) where the structure function leaves the lag^2 regime."""
    d = []
    for lag in LAGS:
        dx = roi[:, lag:] - roi[:, :-lag]
        dy = roi[lag:, :] - roi[:-lag, :]
        d.append(0.5 * (np.mean(dx * dx) + np.mean(dy * dy)) + 1e-12)
    slopes = np.diff(np.log(d)) / np.diff(np.log(LAGS))
    for i, s in enumerate(slopes):
        if s < SMOOTH_SLOPE:
            if i == 0:
                return 1.0
            t = (slopes[i - 1] - SMOOTH_SLOPE) / max(slopes[i - 1] - s, 1e-9)   # interpolate the crossing
            mid = [math.sqrt(LAGS[j] * LAGS[j + 1]) for j in (i - 1, i)]
            return round(mid[0] + min(max(t, 0.0), 1.0) * (mid[1] - mid[0]), 2)
    return float(LAGS[-1])


def parse_roi(text: str, w: int, h: int):
    x0, y0, x1, y1 = (float(v) for v in text.split(","))
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def measure(path, ref, table, args, mask_path=None) -> dict:
    img = luma(path)
    h, w = img.shape
    mask = luma(mask_path) if mask_path else None
    out = horizon_metrics(img, table, args.hfov_deg or ref["hfov"], args.heading_deg, args.pitch_deg,
                          exclude=args.exclude, sky_mask=mask)
    x0, y0, x1, y1 = parse_roi(args.roi, w, h)
    out["detail_px"] = detail_px(img[y0:y1, x0:x1])
    footprint = args.roi_range_m * ref["ifov"] * (1280.0 / w)
    out["effective_gsd_m"] = round(out["detail_px"] * footprint, 2)
    return out


def verdict(base: dict, cand: dict, max_detail_px: float) -> dict:
    checks = {
        "horizon_range": cand["horizon_range_km"] >= max(MIN_RANGE_KM, base["horizon_range_km"]),
        "skyline_match": cand["skyline_match_fraction"] >= max(MIN_MATCH, base["skyline_match_fraction"]),
        "ground_detail": cand["detail_px"] <= max_detail_px,
    }
    return {"checks": checks, "pass": all(checks.values())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--baseline-sky-mask")
    ap.add_argument("--candidate-sky-mask")
    ap.add_argument("--camera-lat", type=float, required=True)
    ap.add_argument("--camera-lon", type=float, required=True)
    ap.add_argument("--camera-alt-m", type=float, required=True)
    ap.add_argument("--heading-deg", type=float, required=True)
    ap.add_argument("--pitch-deg", type=float, required=True)
    ap.add_argument("--hfov-deg", type=float)
    ap.add_argument("--exclude-cols", dest="exclude", type=lambda s: tuple(int(v) for v in s.split(":")))
    ap.add_argument("--roi", default="0.05,0.62,0.35,0.95", help="ground ROI as x0,y0,x1,y1 fractions")
    ap.add_argument("--roi-range-m", type=float, default=6000.0, help="slant range to the ROI centre")
    ap.add_argument("--max-detail-px", type=float, default=2.0)
    args = ap.parse_args()
    ref = load_reference()
    table = skyline_table(ref, args.camera_lat, args.camera_lon, args.camera_alt_m)
    base = measure(args.baseline, ref, table, args, args.baseline_sky_mask)
    cand = measure(args.candidate, ref, table, args, args.candidate_sky_mask)
    result = {"baseline": base, "candidate": cand, **verdict(base, cand, args.max_detail_px)}
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
