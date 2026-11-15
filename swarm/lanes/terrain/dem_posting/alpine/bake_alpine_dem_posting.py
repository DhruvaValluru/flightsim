"""Offline bake (Mac) for terrain.dem_posting.alpine. Visual-only.

Two products, both sampled by the render path and never computed on the laptop:

1. alpine_dem_posting.json -- the posting ladder: for the scenario camera, the
   ground footprint of one pixel at each range, the DEM posting that range can
   actually show, and the per-tier settings (Google-tiles screen-space error,
   tile cache cap, far-ring size). Pure arithmetic, no data.

2. alpine_far_ring_t<N>.bin + alpine_skyline_ref.bin -- Copernicus GLO-90
   pooled onto a polar grid centred on the Matterhorn summit. The far ring
   (30-280 km) is a few-hundred-KB horizon backdrop drawn BEHIND the Google
   tiles; the skyline reference (2-280 km) is what the pixel gate compares a
   rendered skyline against. Heights are orthometric (EGM2008) metres.

    .venv/bin/python -I bake_alpine_dem_posting.py --cache <dir for GLO-90 tiles>

Needs numpy; reading the tiles needs rasterio. Tiles are downloaded into
--cache (outside the repo), read as data only, and their sha256 recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent

# --- scenario constants ----------------------------------------------------
#: Ring centre: Matterhorn summit (core/terrain/glo30.py LOCATIONS["matterhorn"]).
CENTRE_LAT, CENTRE_LON = 45.97636, 7.65853
EYE_ALT_M = 5000.0            # scenario 11: "over the matterhorn at 5000 m"
SNOWLINE_M = 3100.0           # glo30 Location.snowline_m (approximated there)
#: core/scenario/camera.py defaults: 35 mm lens on a 36 x 20.25 mm sensor.
FOCAL_MM, SENSOR_W_MM = 35.0, 36.0
CAPTURE_W, CAPTURE_H = 1280, 720
EARTH_R_M = 6371008.8
REFRACTION_K = 0.13           # standard terrestrial refraction coefficient

GLO90_BUCKET = "https://copernicus-dem-90m.s3.amazonaws.com"
TILE_LATS, TILE_LONS = tuple(range(43, 49)), tuple(range(3, 12))
TILE_PX = 1200                # 3 arc-second tiles below 50 deg latitude

#: 5000 m eye: sea-level horizon 271 km. A first bake to 160 km put the predicted
#: northward skyline on the outer edge in half the columns, so it was too short.
R_OUTER_M = 280_000.0
RING_INNER_M = 30_000.0
REF_INNER_M = 2_000.0
FINE_STEP_M = 60.0
FINE_AZ = 8192
HEIGHT_SCALE_M = 0.1          # uint16 * 0.1 m

#: tier -> (Google tiles SSE, Cesium tile cache cap MB, ring n_r, ring n_az)
TIERS = {
    0: (16.0, 128, 24, 2048),
    1: (8.0, 192, 32, 2048),
    2: (4.0, 256, 48, 4096),
    3: (2.0, 384, 48, 8192),
}
REF_SHAPE = (96, 4096)
LADDER_RANGES_KM = (0.5, 1, 2, 5, 10, 20, 40, 80, 160, 280)
SNOW_ALBEDO = 0.90            # matches lighting_exposure.physical_light_units.alpine
ROCK_SRGB, VEG_SRGB = (0.30, 0.29, 0.28), (0.10, 0.14, 0.07)   # uncalibrated


# --- posting ladder (no data) ----------------------------------------------
def ifov_rad(width_px: int = CAPTURE_W) -> float:
    """Angle of one pixel at the image centre."""
    return SENSOR_W_MM / FOCAL_MM / width_px


def pixel_footprint_m(range_m: float, width_px: int = CAPTURE_W) -> float:
    """Ground sample distance of one pixel facing the camera at range_m."""
    return range_m * ifov_rad(width_px)


def subpixel_range_m(posting_m: float, width_px: int = CAPTURE_W) -> float:
    """Range beyond which a DEM of this posting is finer than one pixel."""
    return posting_m / ifov_rad(width_px)


def horizon_range_m(eye_alt_m: float, target_alt_m: float = 0.0, k: float = REFRACTION_K) -> float:
    """Range at which a target at target_alt_m touches the refracted horizon."""
    r_eff = EARTH_R_M / (1.0 - k)
    return math.sqrt(2.0 * r_eff * eye_alt_m) + math.sqrt(2.0 * r_eff * max(target_alt_m, 0.0))


def ring_vram_mb(n_r: int, n_az: int) -> float:
    """Estimate: 20-byte vertices (pos, packed normal, colour) + 32-bit indices."""
    return (n_r * n_az * 20 + (n_r - 1) * n_az * 6 * 4) / 1e6


def ladder() -> dict:
    rows = []
    for km in LADDER_RANGES_KM:
        fp = pixel_footprint_m(km * 1000.0)
        rows.append({
            "range_km": km,
            "pixel_footprint_m": round(fp, 3),
            "glo30_post_px": round(30.0 / fp, 2),
            "glo90_post_px": round(90.0 / fp, 2),
            "tile_geometric_error_m_by_tier": {str(t): round(v[0] * fp, 2) for t, v in TIERS.items()},
        })
    tiers = []
    for t, (sse, cache_mb, n_r, n_az) in TIERS.items():
        ring = ring_vram_mb(n_r, n_az)
        tiers.append({
            "tier": t,
            "google_tiles_sse": sse,
            "tile_cache_cap_mb": cache_mb,
            "far_ring": {"file": f"alpine_far_ring_t{t}.bin", "n_r": n_r, "n_az": n_az,
                         "azimuth_step_px": round(math.radians(360.0 / n_az) / ifov_rad(), 2),
                         "est_vram_mb": round(ring, 1)},
            "est_vram_mb": round(cache_mb + ring, 1),
            "est_note": "ESTIMATE: tile cache cap (a setting, soft in Cesium) plus ring buffers; not measured",
        })
    return {
        "label": "visual-only; arithmetic only, UNMEASURED on the render machine",
        "camera": {"focal_mm": FOCAL_MM, "sensor_w_mm": SENSOR_W_MM, "width_px": CAPTURE_W,
                   "height_px": CAPTURE_H, "ifov_mrad": round(ifov_rad() * 1e3, 5),
                   "hfov_deg": round(math.degrees(2 * math.atan(SENSOR_W_MM / 2 / FOCAL_MM)), 2)},
        "eye_alt_m": EYE_ALT_M,
        "refraction_k": REFRACTION_K,
        "horizon_km": {"sea_level": round(horizon_range_m(EYE_ALT_M) / 1e3, 1),
                       "to_4000_m_summit": round(horizon_range_m(EYE_ALT_M, 4000.0) / 1e3, 1),
                       "baked_to": R_OUTER_M / 1e3},
        "subpixel_beyond_km": {"glo30_30m": round(subpixel_range_m(30.0) / 1e3, 1),
                               "glo90_90m": round(subpixel_range_m(90.0) / 1e3, 1)},
        "rows": rows,
        "tiers": tiers,
    }


# --- GLO-90 mosaic ----------------------------------------------------------
def tile_name(lat: int, lon: int) -> str:
    return f"Copernicus_DSM_COG_30_N{lat:02d}_00_E{lon:03d}_00_DEM"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_tiles(cache: Path) -> list:
    cache.mkdir(parents=True, exist_ok=True)
    out = []
    for lat in TILE_LATS:
        for lon in TILE_LONS:
            name = tile_name(lat, lon)
            path = cache / f"{name}.tif"
            url = f"{GLO90_BUCKET}/{name}/{name}.tif"
            if not path.is_file():
                try:
                    with urllib.request.urlopen(url, timeout=120) as resp, path.open("wb") as fh:
                        while chunk := resp.read(1 << 20):
                            fh.write(chunk)
                except urllib.error.HTTPError as err:   # an all-sea tile does not exist
                    path.unlink(missing_ok=True)
                    if err.code not in (403, 404):
                        raise
                    out.append({"tile": name, "url": url, "missing": True})
                    continue
            out.append({"tile": name, "url": url, "sha256": sha256_of(path), "bytes": path.stat().st_size})
    return out


def load_mosaic(cache: Path, tiles: list) -> np.ndarray:
    """Rows north to south from lat max(TILE_LATS)+1, columns west to east."""
    import rasterio

    mosaic = np.zeros((len(TILE_LATS) * TILE_PX, len(TILE_LONS) * TILE_PX), dtype=np.float32)
    present = {t["tile"] for t in tiles if not t.get("missing")}
    top = max(TILE_LATS) + 1
    for lat in TILE_LATS:
        for lon in TILE_LONS:
            name = tile_name(lat, lon)
            if name not in present:
                continue
            with rasterio.open(cache / f"{name}.tif") as src:
                data = src.read(1)
                # pixel centres sit on the integer-degree corner (pixel-is-point)
                cx, cy = src.transform * (0.5, 0.5)
                if data.shape != (TILE_PX, TILE_PX) or abs(cx - lon) > 1e-6 or abs(cy - (lat + 1)) > 1e-6:
                    raise SystemExit(f"{name}: unexpected grid {data.shape} centre {cx},{cy}")
            r0, c0 = (top - (lat + 1)) * TILE_PX, (lon - min(TILE_LONS)) * TILE_PX
            mosaic[r0:r0 + TILE_PX, c0:c0 + TILE_PX] = np.where(np.isfinite(data), data, 0.0)
    return mosaic


def destination(lat_deg: float, lon_deg: float, az_rad, dist_m):
    """Spherical direct problem, vectorised. Returns (lat_deg, lon_deg)."""
    lat1, lon1 = math.radians(lat_deg), math.radians(lon_deg)
    d = dist_m / EARTH_R_M
    lat2 = np.arcsin(math.sin(lat1) * np.cos(d) + math.cos(lat1) * np.sin(d) * np.cos(az_rad))
    lon2 = lon1 + np.arctan2(np.sin(az_rad) * np.sin(d) * math.cos(lat1),
                             np.cos(d) - math.sin(lat1) * np.sin(lat2))
    return np.degrees(lat2), np.degrees(lon2)


def sample_polar(mosaic: np.ndarray, r_fine: np.ndarray) -> np.ndarray:
    """Nearest-post heights at [len(r_fine), FINE_AZ] around the centre."""
    out = np.empty((r_fine.size, FINE_AZ), dtype=np.float32)
    top, left = max(TILE_LATS) + 1, min(TILE_LONS)
    for a0 in range(0, FINE_AZ, 1024):
        az = np.radians((np.arange(a0, a0 + 1024) + 0.5) * 360.0 / FINE_AZ)
        lat, lon = destination(CENTRE_LAT, CENTRE_LON, az[None, :], r_fine[:, None])
        rows = np.clip(np.rint((top - lat) * TILE_PX).astype(np.int64), 0, mosaic.shape[0] - 1)
        cols = np.clip(np.rint((lon - left) * TILE_PX).astype(np.int64), 0, mosaic.shape[1] - 1)
        out[:, a0:a0 + 1024] = mosaic[rows, cols]
    return out


def ring_edges(r_inner: float, n_r: int) -> np.ndarray:
    return np.geomspace(r_inner, R_OUTER_M, n_r + 1)


def pool(fine: np.ndarray, r_fine: np.ndarray, edges: np.ndarray, n_az: int):
    """(hmax, hmin, hmean) of the fine samples per (radial bin, azimuth bin)."""
    keep = (r_fine >= edges[0]) & (r_fine < edges[-1])
    f, r = fine[keep], r_fine[keep]
    idx = np.searchsorted(r, edges[:-1])
    counts = np.diff(np.append(idx, r.size))
    if np.any(counts <= 0):
        raise SystemExit("a radial bin has no samples; lower FINE_STEP_M")
    sub = FINE_AZ // n_az
    shape = (edges.size - 1, n_az, sub)
    hmax = np.maximum.reduceat(f, idx, axis=0).reshape(shape).max(axis=2)
    hmin = np.minimum.reduceat(f, idx, axis=0).reshape(shape).min(axis=2)
    hmean = (np.add.reduceat(f.astype(np.float64), idx, axis=0) / counts[:, None]).reshape(shape).mean(axis=2)
    return hmax, hmin, hmean


def smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def colour(hmean: np.ndarray) -> np.ndarray:
    """sRGB8 + snow fraction in alpha. A height rule only: visual-only, uncalibrated."""
    snow = smoothstep(SNOWLINE_M - 300.0, SNOWLINE_M + 300.0, hmean)[..., None]
    rock = smoothstep(1800.0, 2200.0, hmean)[..., None]
    base = np.array(VEG_SRGB) * (1.0 - rock) + np.array(ROCK_SRGB) * rock
    rgb = base * (1.0 - snow) + SNOW_ALBEDO * snow
    return np.rint(np.concatenate([rgb, snow], axis=-1) * 255.0).astype(np.uint8)


def quantise(h: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(h, 0.0, 6553.5) / HEIGHT_SCALE_M).astype("<u2")


def bake_rings(mosaic: np.ndarray, out_dir: Path) -> dict:
    r_fine = np.arange(REF_INNER_M, R_OUTER_M, FINE_STEP_M)
    fine = sample_polar(mosaic, r_fine)
    meta = {}
    for t, (_sse, _cache, n_r, n_az) in TIERS.items():
        edges = ring_edges(RING_INNER_M, n_r)
        hmax, hmin, hmean = pool(fine, r_fine, edges, n_az)
        name = f"alpine_far_ring_t{t}.bin"
        (out_dir / name).write_bytes(quantise(hmax).tobytes() + quantise(hmin).tobytes() + colour(hmean).tobytes())
        meta[name] = {"n_r": n_r, "n_az": n_az, "r_inner_m": RING_INNER_M,
                      "layers": ["hmax u16le", "hmin u16le", "srgb8 + snow alpha"]}
    edges = ring_edges(REF_INNER_M, REF_SHAPE[0])
    hmax, _, _ = pool(fine, r_fine, edges, REF_SHAPE[1])
    (out_dir / "alpine_skyline_ref.bin").write_bytes(quantise(hmax).tobytes())
    meta["alpine_skyline_ref.bin"] = {"n_r": REF_SHAPE[0], "n_az": REF_SHAPE[1], "r_inner_m": REF_INNER_M,
                                      "layers": ["hmax u16le"]}
    return meta


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, help="directory for the GLO-90 tiles; omit to write the ladder only")
    ap.add_argument("--out", type=Path, default=LANE)
    args = ap.parse_args()
    plan = ladder()
    if args.cache:
        tiles = fetch_tiles(args.cache)
        files = bake_rings(load_mosaic(args.cache, tiles), args.out)
        plan["rings"] = {
            "centre_lat": CENTRE_LAT, "centre_lon": CENTRE_LON, "r_outer_m": R_OUTER_M,
            "height_scale_m": HEIGHT_SCALE_M, "vertical_datum": "EGM2008 orthometric (GLO-90)",
            "layout": "row i = radial bin (geomspace r_inner..r_outer, n_r+1 edges, vertex at the "
                      "geometric mean), column j = azimuth (j+0.5)*360/n_az clockwise from north",
            "files": files,
        }
        write_json(args.out / "glo90_tiles.json", tiles)
    write_json(args.out / "alpine_dem_posting.json", plan)
    for p in sorted(args.out.glob("alpine_*")) + sorted(args.out.glob("glo90_tiles.json")):
        print(sha256_of(p), p.stat().st_size, p.name)


if __name__ == "__main__":
    main()
