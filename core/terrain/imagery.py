"""Sentinel-2 cloudless imagery, draped over the georeferenced terrain bakes.

Replaces the approximated slope/altitude vertex classification for the real
locations with true-colour satellite imagery, under the same provenance
discipline as the GLO-30 elevations (:mod:`core.terrain.glo30`): the source
is named, every fetched tile is sha256'd, the license and attribution ride in
the sidecar and every render manifest, and the baked texture is verified
against the source it came from before anything may render it.

Source, honestly
----------------
EOX "Sentinel-2 cloudless" (https://s2maps.eu), the **2016 release** (WMTS
layer ``s2cloudless``), tiles from ``tiles.maps.eox.at`` (public, no auth).
This release is licensed **CC-BY-SA 4.0** (verified against EOX's release
announcement, 2026-08-07; later releases are CC-BY-NC-SA and are not used).
The mosaic is assembled from Copernicus Sentinel-2 acquisitions of 2016 and
2017: the imagery is roughly a decade old, cloud-free by construction
(compositing, not a single acquisition date), 10 m native resolution, and
sun/snow conditions are whatever the compositing kept -- all recorded in
VALIDITY.md. The classification path remains for the control ridge and as
fallback, still labeled approximated.

Alignment, by construction then verified
----------------------------------------
The texture's texel grid shares the DEM bake's CRS, origin and extent, with
the texel size an integer subdivision of the DEM pixel (30 m / 3 = 10 m, the
imagery's native resolution). Texel (u, v) therefore lands on DEM pixel
(u/k, v/k) exactly; no independent georeferencing exists to drift. That
construction is then *verified* the way the elevation bake is: hundreds of
random texels are pushed back through projected -> geographic -> source
mosaic and compared, which catches a CRS mix-up, a row flip or an axis swap
as hundreds of pixels of decorrelation rather than a few counts of
resampling noise. The final check -- that the drape lands on the rendered
GEOMETRY -- is landmark projection through the camera of record on a
rendered frame (experiments/imagery_drape.py), because texture-to-source
agreement cannot see a UV mapping bug in the mesh itself.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .glo30 import Location, sha256_of
from .heightfield import Heightfield

TILE_HOST = "https://tiles.maps.eox.at"
LAYER = "s2cloudless"
TILE_MATRIX_SET = "WGS84"
TILE_SIZE = 256

LICENSE = "CC-BY-SA 4.0"
ATTRIBUTION = (
    "Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH "
    "(Contains modified Copernicus Sentinel data 2016 & 2017)"
)
SOURCE_NOTE = (
    "EOX Sentinel-2 cloudless 2016 release: cloud-free composite of "
    "Copernicus Sentinel-2 acquisitions 2016-2017, 10 m native resolution, "
    "no single acquisition date. Later EOX releases are CC-BY-NC-SA and "
    "deliberately not used."
)

#: WGS84 tile-matrix zoom used for fetches. Pixel size 180/(256*2^13) =
#: 9.5 m N-S -- the source's native 10 m, without upsampled tiles.
FETCH_ZOOM = 13

#: Texels per DEM pixel per axis: 30 m bakes carry 10 m imagery.
TEXELS_PER_DEM_PIXEL = 3

#: Largest texture edge written, matching UE's comfortable import size.
MAX_TEXTURE_EDGE = 8192


class ImageryError(RuntimeError):
    pass


# -- WGS84 tile arithmetic (matrix z: 2^(z+1) x 2^z tiles of 256 px) -----


def tile_span_deg(zoom: int) -> float:
    return 180.0 / (2 ** zoom)


def tile_indices(lat_deg: float, lon_deg: float, zoom: int) -> Tuple[int, int]:
    """(row, col) of the tile containing a point."""
    span = tile_span_deg(zoom)
    col = int(math.floor((lon_deg + 180.0) / span))
    row = int(math.floor((90.0 - lat_deg) / span))
    return row, col

def tile_range(bbox: Tuple[float, float, float, float],
               zoom: int) -> Tuple[range, range]:
    """(rows, cols) covering a (lat_min, lat_max, lon_min, lon_max) bbox."""
    lat_min, lat_max, lon_min, lon_max = bbox
    span = tile_span_deg(zoom)
    row0, col0 = tile_indices(lat_max, lon_min, zoom)
    # The bottom/right edges belong to the next tile only if they cross it.
    row1 = int(math.floor((90.0 - lat_min) / span - 1e-12))
    col1 = int(math.floor((lon_max + 180.0) / span - 1e-12))
    return range(row0, row1 + 1), range(col0, col1 + 1)


def tile_url(zoom: int, row: int, col: int) -> str:
    return (f"{TILE_HOST}/wmts/1.0.0/{LAYER}/default/{TILE_MATRIX_SET}/"
            f"{zoom}/{row}/{col}.jpg")


def tile_cache_path(cache_dir: Path, zoom: int, row: int, col: int) -> Path:
    return Path(cache_dir) / f"{LAYER}_z{zoom}_r{row}_c{col}.jpg"


def _fetch_one(url: str, path: Path, attempts: int = 4) -> None:
    """One tile, with backoff: a public tile server occasionally resets."""
    import time

    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url) as rsp:
                data = rsp.read()
            path.write_bytes(data)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(2.0 ** attempt)


def fetch_tiles(bbox: Tuple[float, float, float, float], cache_dir,
                zoom: int = FETCH_ZOOM) -> Dict[str, Dict]:
    """Download every tile covering the bbox (cached). Returns name->meta."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows, cols = tile_range(bbox, zoom)
    out: Dict[str, Dict] = {}
    for row in rows:
        for col in cols:
            path = tile_cache_path(cache_dir, zoom, row, col)
            if not path.is_file():
                _fetch_one(tile_url(zoom, row, col), path)
            out[path.name] = {
                "zoom": zoom, "row": row, "col": col,
                "url": tile_url(zoom, row, col),
                "sha256": sha256_of(path), "path": str(path),
            }
    return out


def mosaic_tiles(tiles: Dict[str, Dict], zoom: int, out_path: Path) -> Path:
    """Assemble fetched tiles into one georeferenced 4326 GeoTIFF."""
    import rasterio
    from PIL import Image
    from rasterio.transform import from_origin

    rows = sorted({t["row"] for t in tiles.values()})
    cols = sorted({t["col"] for t in tiles.values()})
    if rows != list(range(rows[0], rows[-1] + 1)) or \
            cols != list(range(cols[0], cols[-1] + 1)):
        raise ImageryError("tile set has holes; refusing a gapped mosaic")

    span = tile_span_deg(zoom)
    height = len(rows) * TILE_SIZE
    width = len(cols) * TILE_SIZE
    mosaic = np.zeros((height, width, 3), dtype=np.uint8)
    for meta in tiles.values():
        img = np.asarray(Image.open(meta["path"]).convert("RGB"))
        if img.shape != (TILE_SIZE, TILE_SIZE, 3):
            raise ImageryError(f"tile {meta['url']} is {img.shape}, "
                               f"expected {TILE_SIZE}x{TILE_SIZE}x3")
        r0 = (meta["row"] - rows[0]) * TILE_SIZE
        c0 = (meta["col"] - cols[0]) * TILE_SIZE
        mosaic[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE] = img

    top_lat = 90.0 - rows[0] * span
    left_lon = -180.0 + cols[0] * span
    pixel_deg = span / TILE_SIZE
    transform = from_origin(left_lon, top_lat, pixel_deg, pixel_deg)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="GTiff", height=height, width=width, count=3,
        dtype="uint8", crs="EPSG:4326", transform=transform,
        photometric="RGB",
    ) as dst:
        for band in range(3):
            dst.write(mosaic[:, :, band], band + 1)
    return out_path


# -- the drape bake ------------------------------------------------------


@dataclass(frozen=True)
class TexelGrid:
    """The texture grid: the bake's frame, subdivided."""

    crs: str
    origin_x_m: float
    origin_y_m: float
    texel_size_m: float
    width: int
    height: int

    @classmethod
    def from_bake(cls, baked: Heightfield,
                  texels_per_pixel: int = TEXELS_PER_DEM_PIXEL) -> "TexelGrid":
        g = baked.georeference
        k = int(texels_per_pixel)
        while k > 1 and max(baked.width * k, baked.height * k) > MAX_TEXTURE_EDGE:
            k -= 1
        return cls(crs=g.crs, origin_x_m=g.origin_x_m, origin_y_m=g.origin_y_m,
                   texel_size_m=g.pixel_size_m / k,
                   width=baked.width * k, height=baked.height * k)


def reproject_to_grid(source_4326: Path, grid: TexelGrid) -> np.ndarray:
    """Warp the 4326 mosaic onto the texel grid, bilinear, RGB uint8."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin
    from rasterio.warp import reproject as rio_reproject

    transform = from_origin(grid.origin_x_m, grid.origin_y_m,
                            grid.texel_size_m, grid.texel_size_m)
    out = np.zeros((3, grid.height, grid.width), dtype=np.uint8)
    with rasterio.open(source_4326) as src:
        for band in range(3):
            rio_reproject(
                source=rasterio.band(src, band + 1),
                destination=out[band],
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=transform, dst_crs=grid.crs,
                resampling=Resampling.bilinear,
            )
    return np.moveaxis(out, 0, -1)


def verify_drape(texture: np.ndarray, grid: TexelGrid, source_4326: Path,
                 samples: int = 400, seed: int = 20260807) -> Dict:
    """Baked texel -> projected -> geographic -> source pixel, point by point.

    Bilinear against bilinear on JPEG-compressed imagery legitimately differs
    by a few counts; a CRS mix-up, row flip or axis swap lands hundreds of
    pixels away on different terrain and decorrelates completely. Thresholds
    sit between the regimes, as verify_against_source's do for elevations.
    """
    import rasterio
    from pyproj import Transformer

    rng = np.random.default_rng(seed)
    transformer = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    with rasterio.open(source_4326) as src:
        bands = src.read()  # (3, H, W)
        rows = rng.integers(2, grid.height - 2, size=samples)
        cols = rng.integers(2, grid.width - 2, size=samples)
        differences = []
        for row, col in zip(rows, cols):
            x = grid.origin_x_m + (float(col) + 0.5) * grid.texel_size_m
            y = grid.origin_y_m - (float(row) + 0.5) * grid.texel_size_m
            lon, lat = transformer.transform(x, y)
            src_row, src_col = src.index(lon, lat, op=float)
            r0, c0 = int(src_row), int(src_col)
            if not (0 <= r0 < src.height - 1 and 0 <= c0 < src.width - 1):
                continue
            fr, fc = src_row - r0, src_col - c0
            window = bands[:, r0:r0 + 2, c0:c0 + 2].astype(np.float64)
            source_rgb = (window[:, 0, 0] * (1 - fr) * (1 - fc)
                          + window[:, 0, 1] * (1 - fr) * fc
                          + window[:, 1, 0] * fr * (1 - fc)
                          + window[:, 1, 1] * fr * fc)
            baked_rgb = texture[row, col].astype(np.float64)
            differences.append(np.abs(baked_rgb - source_rgb).mean())

    differences = np.asarray(differences)
    report = {
        "samples": int(differences.size),
        "mean_abs_counts": float(differences.mean()),
        "p95_abs_counts": float(np.percentile(differences, 95)),
        "max_abs_counts": float(differences.max()),
    }
    report["ok"] = bool(report["samples"] >= samples * 0.9
                        and report["mean_abs_counts"] < 8.0
                        and report["p95_abs_counts"] < 30.0)
    return report


def snow_brightness_report(texture: np.ndarray, grid: TexelGrid,
                           baked: Heightfield, snowline_m: float,
                           samples: int = 2000,
                           seed: int = 20260808) -> Dict:
    """Brightness above vs below the snowline. Recorded, not gated: a weak
    physical cross-check between two independent datasets (imagery vs DEM);
    decisive alignment evidence is the landmark projection on a render."""
    rng = np.random.default_rng(seed)
    rows = rng.integers(0, grid.height, size=samples)
    cols = rng.integers(0, grid.width, size=samples)
    above, below = [], []
    for row, col in zip(rows, cols):
        x = grid.origin_x_m + (float(col) + 0.5) * grid.texel_size_m
        y = grid.origin_y_m - (float(row) + 0.5) * grid.texel_size_m
        elev = baked.elevation_at(x, y)
        luma = float(texture[row, col].astype(np.float64).mean())
        (above if elev >= snowline_m else below).append(luma)
    return {
        "snowline_m": snowline_m,
        "mean_brightness_above": float(np.mean(above)) if above else None,
        "mean_brightness_below": float(np.mean(below)) if below else None,
        "samples_above": len(above), "samples_below": len(below),
    }


def drape(location: Location, baked_path, cache_dir, out_dir,
          zoom: int = FETCH_ZOOM) -> Tuple[Path, Dict]:
    """Fetch, mosaic, reproject onto the bake's grid, verify, write.

    Returns the texture PNG path and the verification report. Raises
    :class:`ImageryError` if verification fails: an unverified drape must
    not be renderable by accident, exactly as an unverified bake is not.
    """
    from PIL import Image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    baked = Heightfield.read(baked_path)
    grid = TexelGrid.from_bake(baked)

    tiles = fetch_tiles(location.bbox, cache_dir, zoom)
    source_mosaic = out_dir / f"{location.key}_imagery_source_4326.tif"
    mosaic_tiles(tiles, zoom, source_mosaic)

    texture = reproject_to_grid(source_mosaic, grid)
    verification = verify_drape(texture, grid, source_mosaic)
    if not verification["ok"]:
        raise ImageryError(
            f"{location.key}: draped texture disagrees with its source "
            f"mosaic ({verification}). Refusing to write an unverified "
            f"drape.")
    snow = snow_brightness_report(texture, grid, baked, location.snowline_m)

    png_path = out_dir / f"{location.key}_imagery.png"
    Image.fromarray(texture).save(png_path)

    sidecar = {
        "dataset": f"EOX Sentinel-2 cloudless 2016 (WMTS layer {LAYER!r})",
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "source_note": SOURCE_NOTE,
        "endpoint": TILE_HOST,
        "tile_matrix_set": TILE_MATRIX_SET,
        "zoom": zoom,
        "tiles": {name: {k: v for k, v in meta.items() if k != "path"}
                  for name, meta in sorted(tiles.items())},
        "texture": {
            "file": png_path.name,
            "sha256": None,  # filled below, after the file exists
            "crs": grid.crs,
            "origin_x_m": grid.origin_x_m, "origin_y_m": grid.origin_y_m,
            "texel_size_m": grid.texel_size_m,
            "width": grid.width, "height": grid.height,
            "aligned_to_bake": str(Path(baked_path).resolve()),
            "texels_per_dem_pixel": round(
                baked.georeference.pixel_size_m / grid.texel_size_m),
        },
        "verification_vs_source": verification,
        "snow_brightness": snow,
        "native_resolution_note": (
            "10 m native; composite of 2016-2017 acquisitions, no single "
            "date; scene lighting/snow state is the composite's, not the "
            "render's sun position"),
    }
    sidecar["texture"]["sha256"] = sha256_of(png_path)
    sidecar_path = out_dir / f"{location.key}_imagery.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2))
    return png_path, verification
