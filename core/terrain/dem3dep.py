"""USGS 3DEP 1/3 arc-second elevation: the curated US places at ~10 m.

The GLO-30 bakes (core/terrain/glo30.py) are a 30 m surface model; a
summit, a ridge or a canyon wall is smoothed to 30 m and no texture can
put the shape back. For the places inside the United States the USGS 3D
Elevation Program publishes a 1/3 arc-second (~10 m) bare-earth DEM,
public domain, as 1 x 1 degree cloud-optimised GeoTIFFs on a public
bucket. This module bakes those through the ONE pipeline -- fetch,
mosaic, ``dem.ingest`` (reproject, resample, quantise), verify against
the source, check the named summits, the datum block, the geoid crop --
so a 3DEP bake and a GLO-30 bake are the same kind of file with a
different provenance; the scene, the drape, the land cover and the
flight model do not know which they got.

What is different, and stated in the sidecar:

* the tiles are read WINDOWED over HTTPS (GDAL ``/vsicurl/`` range
  requests on the COG): only the scene's box is fetched and cached as
  ``<stem>_<bbox>.tif``, never the 450 MB tile;
* the vertical datum is NAVD88 (GEOID12B/18 orthometric), not EGM2008;
  the datum block treats the heights as orthometric over the bake's
  geoid grid, and the ~1-1.5 m by which NAVD88 and EGM2008 differ across
  the conterminous US is NOT modelled -- the provenance says so;
* the posting is ~10 m, so the raster is 9x the GLO-30 pixel count; the
  procedural mesh's triangle budget (``TerrainTriangleBudget``, 4 M)
  may decimate it to a coarser stride and the host RECORDS the achieved
  posting (``TerrainPostingMetres``); the Landscape route carries it
  whole.

Outside 3DEP's coverage (the United States) the bake refuses by name;
GLO-30 stands for those places.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .dem import DEMError, ingest
from .geoid import (
    bake_datum, cdb_descriptor_block, datum_for_heightfield, dted_block, grid_for_model,
    write_gtx_bundle,
)
from .glo30 import Location, check_summits, merge_and_crop, sha256_of, verify_against_source

BUCKET = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current"
DATASET = "USGS 3DEP 1/3 arc-second DEM (~10 m, bare earth)"
ATTRIBUTION = ("U.S. Geological Survey, 3D Elevation Program (3DEP), 1/3 "
               "arc-second seamless DEM; public domain (USGS, no restriction)")
VERTICAL_DATUM_NOTE = (
    "NAVD88 orthometric (GEOID12B/18) per 3DEP; the datum block treats the "
    "heights as orthometric over the bake's geoid grid -- NAVD88 and EGM2008 "
    "differ by up to ~1.5 m across the conterminous US, unmodelled")
#: 1/3 arc-second is 9.26e-5 degrees: ~10.3 m north-south, less east-west.
NOMINAL_GSD_M = 10.0
#: Degrees of source kept around the scene box so the reprojection's edge
#: pixels have neighbours (dem.ingest crops to the valid rectangle).
CROP_MARGIN_DEG = 0.01
#: (lat_min, lat_max, lon_min, lon_max) boxes 3DEP's 1/3 arc-second product
#: covers: the conterminous US, Alaska, Hawaii. A scene box must lie inside
#: one of them; anything else is refused by name.
COVERAGE = (
    (24.0, 49.6, -125.1, -66.4),
    (51.0, 71.6, -180.0, -129.0),
    (18.5, 22.5, -161.0, -154.0),
)


def covers(bbox: Sequence[float]) -> bool:
    lat_min, lat_max, lon_min, lon_max = bbox
    return any(lat_min >= a and lat_max <= b and lon_min >= c and lon_max <= d
               for a, b, c, d in COVERAGE)


def tile_stems(bbox: Sequence[float]) -> Tuple[str, ...]:
    """The 1 x 1 degree tiles a box touches, named by their NORTH and WEST
    edges the way the bucket names them: ``n38w120`` is 37..38 N,
    120..119 W."""
    lat_min, lat_max, lon_min, lon_max = bbox
    stems = []
    for lat_floor in range(math.floor(lat_min), math.ceil(lat_max)):
        for lon_floor in range(math.floor(lon_min), math.ceil(lon_max)):
            north, west = lat_floor + 1, lon_floor
            stems.append(f"{'n' if north >= 0 else 's'}{abs(north):02d}"
                         f"{'w' if west < 0 else 'e'}{abs(west):03d}")
    return tuple(stems)


def tile_url(stem: str) -> str:
    return f"{BUCKET}/{stem}/USGS_13_{stem}.tif"


def crop_path(cache_dir: Path, stem: str, bbox: Sequence[float]) -> Path:
    tag = "_".join(f"{v:.3f}" for v in bbox).replace("-", "m").replace(".", "p")
    return Path(cache_dir) / f"USGS_13_{stem}_{tag}.tif"


def gdal_env() -> Dict[str, str]:
    """GDAL's HTTP configuration for the windowed reads: no directory
    listing, .tif only, retries, and the machine's proxy and CA bundle
    when the environment names them (this container routes HTTPS through
    an agent proxy with its own CA)."""
    env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
           "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
           "GDAL_HTTP_MAX_RETRY": "3", "GDAL_HTTP_RETRY_DELAY": "2"}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        env["GDAL_HTTP_PROXY"] = proxy
    for name in ("GDAL_CURL_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO",
                 "SSL_CERT_FILE"):
        if os.environ.get(name) and Path(os.environ[name]).is_file():
            env["GDAL_CURL_CA_BUNDLE"] = os.environ[name]
            break
    return env


def fetch_crops(bbox: Sequence[float], cache_dir) -> List[Path]:
    """The scene box cut out of each tile it touches, cached; a cached
    crop is reused. Raises DEMError when a tile cannot be read."""
    import rasterio
    from rasterio.windows import Window, from_bounds

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    lat_min, lat_max, lon_min, lon_max = bbox
    paths = []
    for stem in tile_stems(bbox):
        path = crop_path(cache_dir, stem, bbox)
        if path.is_file():
            paths.append(path)
            continue
        url = tile_url(stem)
        try:
            with rasterio.Env(**gdal_env()):
                with rasterio.open("/vsicurl/" + url) as src:
                    want = from_bounds(lon_min - CROP_MARGIN_DEG, lat_min - CROP_MARGIN_DEG,
                                       lon_max + CROP_MARGIN_DEG, lat_max + CROP_MARGIN_DEG,
                                       src.transform)
                    # Clip to the tile: a box that crosses a degree line
                    # takes its other part from the neighbouring tile.
                    window = want.intersection(Window(0, 0, src.width, src.height))
                    window = window.round_offsets().round_lengths()
                    if window.width <= 0 or window.height <= 0:
                        raise DEMError(f"{stem}: the scene box does not touch this tile")
                    data = src.read(1, window=window)
                    profile = src.profile.copy()
                    profile.update(driver="GTiff", height=data.shape[0],
                                   width=data.shape[1],
                                   transform=src.window_transform(window),
                                   compress="deflate", tiled=True,
                                   blockxsize=256, blockysize=256)
            with rasterio.open(path, "w", **profile) as dst:
                dst.write(data, 1)
        except DEMError:
            raise
        except Exception as exc:          # rasterio/GDAL raise many kinds
            raise DEMError(f"3DEP tile {stem} ({url}) could not be read "
                           f"windowed: {exc}") from exc
        paths.append(path)
    return paths


def bake(location: Location, cache_dir, out_dir,
         ground_sample_distance_m: float = NOMINAL_GSD_M,
         geoid_model: str = "auto") -> Tuple[Path, Dict]:
    """Fetch (windowed), mosaic, ingest, verify and write one location's
    heightfield from 3DEP: the glo30.bake pipeline with this source. Same
    returns, same refusals (an unverified bake is not written); a place
    outside 3DEP's coverage refuses by name before anything is fetched."""
    if not covers(location.bbox):
        raise DEMError(
            f"{location.key}: 3DEP covers the United States; its box "
            f"{location.bbox} lies outside -- bake it from GLO-30")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = grid_for_model(geoid_model)

    crops = fetch_crops(location.bbox, cache_dir)
    crop_shas = {p.name: sha256_of(p) for p in crops}

    source_mosaic = out_dir / f"{location.key}_source_4269.tif"
    merge_and_crop(crops, location.bbox, source_mosaic)

    baked = ingest(source_mosaic, target_crs=location.crs,
                   ground_sample_distance_m=ground_sample_distance_m,
                   name=location.key)

    verification = verify_against_source(baked, source_mosaic)
    summit_report = check_summits(baked, location)
    if not verification["ok"]:
        raise DEMError(
            f"{location.key}: baked raster disagrees with the 3DEP source "
            f"mosaic ({verification}). Refusing to write an unverified bake.")
    if not all(s["ok"] for s in summit_report):
        raise DEMError(
            f"{location.key}: a named summit is not where the raster says "
            f"({summit_report}). This is the wrong mountain or a "
            f"georeferencing error, not a resampling artefact.")

    baked.provenance.update({
        "dataset": DATASET,
        "attribution": ATTRIBUTION,
        "vertical_datum": VERTICAL_DATUM_NOTE,
        "tiles": {stem: crop_shas[crop_path(Path(cache_dir), stem, location.bbox).name]
                  for stem in tile_stems(location.bbox)},
        "source_urls": {stem: tile_url(stem) for stem in tile_stems(location.bbox)},
        "source_read": "windowed over HTTPS (GDAL /vsicurl/ on the COG); the "
                       "cached file is the scene's crop, not the tile",
        "ground_sample_distance_m": float(ground_sample_distance_m),
        "bbox_deg": location.bbox,
        "location": location.title,
        "origin_lat_deg": location.origin_lat,
        "origin_lon_deg": location.origin_lon,
        "snowline_m_approx": location.snowline_m,
        "verification_vs_source": verification,
        "summit_identity": summit_report,
        "surface_model_note": (
            "bare-earth DTM (lidar, IfSAR or legacy NED where no lidar "
            "exists); 1/3 arc-second (~10 m) posting; the procedural mesh's "
            "triangle budget may decimate it and the host records the "
            "achieved posting"),
    })
    baked.provenance["datum"] = datum_for_heightfield(baked)
    gtx = write_gtx_bundle(grid, location.bbox, out_dir, location.key,
                           location.origin_lat, location.origin_lon)
    baked.provenance["datum"] = bake_datum(baked.provenance["datum"], grid,
                                           location.bbox, gtx, location_key=location.key)
    baked.provenance["geoid_files"] = {
        "gtx": gtx["file"], "gtx_sha256": gtx["sha256"],
        "samples": gtx["samples_file"], "samples_sha256": gtx["samples_sha256"],
    }
    baked.provenance["dted"] = dted_block(baked)
    baked.provenance["cdb_descriptor"] = cdb_descriptor_block(baked)
    raw = baked.write(out_dir / location.key)
    return raw, verification
