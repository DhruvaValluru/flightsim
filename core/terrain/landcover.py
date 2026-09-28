"""ESA WorldCover land cover, rasterised onto a terrain bake as weightmaps.

Gap S5 of docs/PHASE3_GAP_ANALYSIS.md: the world carries height and an
imagery drape but no land cover. This module is the Python half of the
closing step -- the data pipeline, measured in this container. The engine
half (a landscape material or a PCG biome reading the weightmaps) comes
later and is NOT claimed here; nothing in the engine reads these files
yet.

Source, honestly
----------------
ESA WorldCover 10 m 2021 v200: a global land cover map at 10 m (1/12000
degree) posting in 11 classes, from Sentinel-1 and Sentinel-2 acquisitions
of 2021, delivered as 3x3 degree Cloud-Optimised GeoTIFFs in EPSG:4326
from the public AWS bucket ``esa-worldcover`` (no auth). Licence CC BY 4.0;
attribution text and citation as the product user manual states them
(section 5.1 and 5.2 of ``WorldCover_PUM_V2.0.pdf``, fetched from the
bucket's ``v200/2021/docs/`` on 2026-09-28, sha256
``4301a3d95260d88bd4315f43ccf2a12ef74ad391109b9f36e22b6e51d8490107``; the
DOI itself did not resolve through this container's proxy). The manual
reports a global overall accuracy of 76.7 +/- 0.5 % (North America 74.6
+/- 1.2 %): the classes are a product's estimate, not ground truth, and
this module does not re-validate them.

CC BY 4.0 REQUIRES ATTRIBUTION: a dataset distributed with these
weightmaps must carry :data:`ATTRIBUTION`; every ``landcover.json`` this
module writes carries it, and the dataset card is expected to lift it.

What is read
------------
Only the scene's window. A ranged GET through this container's proxy
returned 206, and rasterio's ``/vsicurl/`` path read the Yosemite scene's
window (3000 x 4800 px) from the 115 MB N36W120 tile in 2.7 s without
downloading the tile. When a whole tile already sits in the cache dir
under its bucket name it is read from there instead (no network). The
cropped window is written to the cache dir as a GeoTIFF and sha256'd;
that digest is the provenance every consumer carries, as
:mod:`core.terrain.glo30` does for its tiles.

What is written
---------------
For a bake ``<key>.r16`` + ``<key>.json`` (written by ``glo30.bake``), a
directory ``<key>_landcover/`` holding one 8-bit PNG per legend class
(``<class>_weight.png``: 0-255 = the fraction of the 10 m cells of that
class inside each bake cell, largest-remainder rounded so the sum over
every class map, nodata included, is exactly 255 in every cell), a
majority ``class_map.png`` (the legend code per cell), and
``landcover.json`` (classes, fractions over the scene, source, sha256,
licence, attribution, posting, the bake grid, and the ``scene.landcover``
:class:`core.records.AppliedVariable` under ``applied_variables``).

Alignment is by construction and then verified: the weightmap grid is the
bake's own CRS, origin and extent (the sidecar's georeference keys),
subdivided ``texels_per_cell`` times the way the imagery drape's texel
grid is, and hundreds of random fine texels are pushed back through
projected -> geographic -> source pixel and compared class for class,
which catches a CRS mix-up, a row flip or an axis swap as wholesale
disagreement.

Refusals by name: ``terrain.landcover`` (a tile unreachable, a file that
is not a WorldCover raster, values outside the legend, a window that does
not verify against its source) and ``terrain.landcover_grid`` (a bake
sidecar absent or missing the grid keys).

Not claimed: nothing in the engine consumes these files; no vegetation
or structure is placed; the class accuracy is the product's own; the
2021 classes are not temporally aligned with the 2016-2017 imagery drape
or the 2010-2015 GLO-30 heights; a weight is a fraction of 10 m cells,
not of area, and the 10 m posting is nominal (1/12000 degree).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np

from ..records import AppliedVariable, NullTest, records_block
from .glo30 import Location, sha256_of

BUCKET = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
PRODUCT_PATH = "v200/2021/map"
DATASET = "ESA WorldCover 10 m 2021 v200"
PRODUCT_VERSION = "v200"
YEAR = 2021

LICENSE = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_NOTE = (
    "CC BY 4.0 requires attribution: a dataset distributed with these "
    "weightmaps must carry the attribution line, and a publication must "
    "cite the dataset (product user manual sections 5.1 and 5.2)")
ATTRIBUTION = (
    "(c) ESA WorldCover project 2021 / Contains modified Copernicus "
    "Sentinel data (2021) processed by ESA WorldCover consortium"
)
CITATION = (
    "Zanaga, D., Van De Kerchove, R., Daems, D., De Keersmaecker, W., "
    "Brockmann, C., Kirches, G., Wevers, J., Cartus, O., Santoro, M., "
    "Fritz, S., Lesiv, M., Herold, M., Tsendbazar, N.E., Xu, P., Ramoino, "
    "F., Arino, O., 2022. ESA WorldCover 10 m 2021 v200. "
    "doi:10.5281/zenodo.7254221"
)
MANUAL_SHA256 = "4301a3d95260d88bd4315f43ccf2a12ef74ad391109b9f36e22b6e51d8490107"
REFERENCES = (
    CITATION + " (citation text as the product user manual prints it; "
    "the DOI itself was not resolvable through this container's proxy)",
    "ESA WorldCover Product User Manual V2.0, 2022-10-24, bucket path "
    "v200/2021/docs/WorldCover_PUM_V2.0.pdf, sha256 " + MANUAL_SHA256 +
    ": Table 3 (legend), 5.1 (licence), 5.2 (attribution, citation), "
    "6 (global overall accuracy 76.7 +/- 0.5 %)",
)

#: The product's posting: 1/12000 degree, nominally 10 m.
PIXEL_DEG = 1.0 / 12000.0
POSTING_M_NOMINAL = 10.0
TILE_DEG = 3
NODATA = 0

#: Fine texels per bake cell per axis: a 30 m bake counts 10 m cells 3 x 3.
TEXELS_PER_CELL = 3
#: Largest fine-grid edge; the subdivision drops until it fits (as the
#: imagery drape's texel grid does).
MAX_FINE_EDGE = 8192

#: Random texels pushed back to the source, and the agreement that counts.
VERIFY_SAMPLES = 400
VERIFY_MIN_AGREEMENT = 0.9

#: The uniform prior over the legend: what a scene says about its cover
#: with no land cover data at all. The null test measures the dominant
#: class's fraction against it.
NULL_TEST_THRESHOLD = 0.05


@dataclass(frozen=True)
class LandCoverClass:
    code: int
    key: str
    title: str
    rgb: Tuple[int, int, int]


#: Table 3 of the product user manual: map code, class, colour.
LEGEND: Tuple[LandCoverClass, ...] = (
    LandCoverClass(10, "tree_cover", "Tree cover", (0, 100, 0)),
    LandCoverClass(20, "shrubland", "Shrubland", (255, 187, 34)),
    LandCoverClass(30, "grassland", "Grassland", (255, 255, 76)),
    LandCoverClass(40, "cropland", "Cropland", (240, 150, 255)),
    LandCoverClass(50, "built_up", "Built-up", (250, 0, 0)),
    LandCoverClass(60, "bare_sparse", "Bare / sparse vegetation", (180, 180, 180)),
    LandCoverClass(70, "snow_ice", "Snow and ice", (240, 240, 240)),
    LandCoverClass(80, "permanent_water", "Permanent water bodies", (0, 100, 200)),
    LandCoverClass(90, "herbaceous_wetland", "Herbaceous wetland", (0, 150, 160)),
    LandCoverClass(95, "mangroves", "Mangroves", (0, 207, 117)),
    LandCoverClass(100, "moss_lichen", "Moss and lichen", (250, 230, 160)),
)
LEGEND_CODES: Tuple[int, ...] = tuple(c.code for c in LEGEND)
NODATA_KEY = "nodata"
#: The class keys with a weightmap, nodata last.
WEIGHT_KEYS: Tuple[str, ...] = tuple(c.key for c in LEGEND) + (NODATA_KEY,)
_CODE_BY_KEY = {c.key: c.code for c in LEGEND}


class LandcoverError(Exception):
    """The land cover source cannot be used; refused by name
    (``terrain.landcover``). ``reason`` is ``unreachable`` (the tile could
    not be fetched), ``corrupt`` (not a WorldCover raster, or values
    outside the legend) or ``unverified`` (the rasterised window
    disagrees with its source)."""

    constraint = "terrain.landcover"

    def __init__(self, message: str, reason: str = "corrupt") -> None:
        self.message = message
        self.reason = reason
        super().__init__(f"terrain.landcover: {message}")


class LandcoverGridError(Exception):
    """The bake sidecar does not say where its grid is; refused by name
    (``terrain.landcover_grid``)."""

    constraint = "terrain.landcover_grid"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"terrain.landcover_grid: {message}")


# -- tiles -----------------------------------------------------------------


def tile_stem(lat_deg: float, lon_deg: float) -> str:
    """The 3x3 degree tile containing a point, named by its south-west
    corner as the bucket names it: ``N36W120`` covers 36..39 N, 120..117 W."""
    lat0 = int(math.floor(float(lat_deg) / TILE_DEG)) * TILE_DEG
    lon0 = int(math.floor(float(lon_deg) / TILE_DEG)) * TILE_DEG
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


def tile_corner(stem: str) -> Tuple[int, int]:
    """(lat_sw, lon_sw) of a stem."""
    lat = int(stem[1:3]) * (1 if stem[0] == "N" else -1)
    lon = int(stem[4:7]) * (1 if stem[3] == "E" else -1)
    return lat, lon


def tiles_for_bbox(bbox: Tuple[float, float, float, float]) -> Tuple[str, ...]:
    """Every tile a (lat_min, lat_max, lon_min, lon_max) bbox touches. A
    maximum edge exactly on a tile boundary belongs to the tile below it."""
    lat_min, lat_max, lon_min, lon_max = (float(v) for v in bbox)
    eps = 1e-9
    stems = []
    la = int(math.floor(lat_min / TILE_DEG)) * TILE_DEG
    while la < lat_max - eps:
        lo = int(math.floor(lon_min / TILE_DEG)) * TILE_DEG
        while lo < lon_max - eps:
            stems.append(tile_stem(la, lo))
            lo += TILE_DEG
        la += TILE_DEG
    return tuple(stems)


def tile_name(stem: str) -> str:
    return f"ESA_WorldCover_10m_{YEAR}_{PRODUCT_VERSION}_{stem}_Map.tif"


def tile_url(stem: str) -> str:
    return f"{BUCKET}/{PRODUCT_PATH}/{tile_name(stem)}"


def tile_path(cache_dir, stem: str) -> Path:
    """Where a whole tile would sit in the cache (read from there when
    present; this module never downloads a whole tile itself)."""
    return Path(cache_dir) / tile_name(stem)


def crop_path(cache_dir, key: str) -> Path:
    return Path(cache_dir) / f"ESA_WorldCover_10m_{YEAR}_{PRODUCT_VERSION}_{key}_crop_4326.tif"


def _gdal_options() -> Dict[str, str]:
    """GDAL config for a remote read: no directory listing on open, only
    .tif through vsicurl, and the container's HTTPS proxy and CA bundle
    when the environment names them (GDAL's curl reads https_proxy and
    CURL_CA_BUNDLE itself; naming them explicitly is belt and braces)."""
    options = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    }
    proxy = os.environ.get("GDAL_HTTP_PROXY") or os.environ.get("HTTPS_PROXY") \
        or os.environ.get("https_proxy")
    if proxy:
        options["GDAL_HTTP_PROXY"] = proxy
    bundle = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle:
        options["CURL_CA_BUNDLE"] = bundle
    return options


def _head(url: str) -> Dict[str, Any]:
    """The bucket's own identity for the whole tile (ETag, size, date),
    recorded beside the window's sha256. None for each when HEAD fails;
    the vsicurl read is the reachability check, not this."""
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=60) as response:
            headers = response.headers
            return {
                "etag": headers.get("ETag"),
                "content_length": int(headers.get("Content-Length") or 0) or None,
                "last_modified": headers.get("Last-Modified"),
            }
    except (OSError, ValueError):
        return {"etag": None, "content_length": None, "last_modified": None}


def _global_index(lat_deg: float, lon_deg: float) -> Tuple[float, float]:
    """(row, col) on the product's global 1/12000 degree grid, origin
    90 N 180 W, rows southward -- fractional."""
    return (90.0 - lat_deg) / PIXEL_DEG, (lon_deg + 180.0) / PIXEL_DEG


def _check_tile_georeference(src, stem: str, where: str) -> None:
    """A WorldCover tile is EPSG:4326 at exactly 1/12000 degree with its
    origin at the stem's north-west corner; anything else is not the
    product and is refused rather than resampled into a wrong answer."""
    if src.crs is None or not src.crs.to_epsg() == 4326:
        raise LandcoverError(
            f"{where} is not in EPSG:4326 (got {src.crs}); not a WorldCover tile")
    t = src.transform
    if abs(t.a - PIXEL_DEG) > 1e-12 or abs(-t.e - PIXEL_DEG) > 1e-12 \
            or abs(t.b) > 0 or abs(t.d) > 0:
        raise LandcoverError(
            f"{where} pixel is not 1/12000 degree north-up ({t.a}, {t.e}); "
            f"not a WorldCover tile")
    lat_sw, lon_sw = tile_corner(stem)
    if abs(t.c - lon_sw) > 1e-9 or abs(t.f - (lat_sw + TILE_DEG)) > 1e-9:
        raise LandcoverError(
            f"{where} origin ({t.c}, {t.f}) is not tile {stem}'s corner")
    if src.count != 1 or src.dtypes[0] != "uint8":
        raise LandcoverError(
            f"{where} has {src.count} band(s) of {src.dtypes[0]}; the map "
            f"layer is one uint8 band")


def _check_legend(values: np.ndarray, where: str) -> None:
    seen = np.unique(values)
    bad = [int(v) for v in seen if int(v) != NODATA and int(v) not in LEGEND_CODES]
    if bad:
        raise LandcoverError(
            f"{where} carries values outside the WorldCover legend: {bad}")


def fetch(location: Location, cache_dir,
          bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    """The scene's window of WorldCover, cropped to the cache dir with
    sha256 provenance and the licence recorded.

    Reads only the bbox's window from each tile it touches (``/vsicurl/``
    against the bucket, or a whole tile already in ``cache_dir``), mosaics
    the windows on the product's global grid, checks every value is in
    the legend, writes ``<cache>/..._<key>_crop_4326.tif`` and a ``.json``
    beside it, and returns the provenance dict. A cached crop whose
    recorded sha256 still matches is returned without touching the
    network. Refuses ``terrain.landcover`` by name when a tile is
    unreachable or is not the product.
    """
    import rasterio
    from rasterio.errors import RasterioIOError
    from rasterio.transform import from_origin
    from rasterio.windows import Window

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    bbox = tuple(float(v) for v in (bbox or location.bbox))
    out_path = crop_path(cache_dir, location.key)
    meta_path = out_path.with_suffix(".json")
    if out_path.is_file() and meta_path.is_file():
        cached = json.loads(meta_path.read_text(encoding="utf-8"))
        if cached.get("sha256") == sha256_of(out_path) \
                and tuple(cached.get("bbox_deg", ())) == bbox:
            return cached

    lat_min, lat_max, lon_min, lon_max = bbox
    row0f, col0f = _global_index(lat_max, lon_min)
    row1f, col1f = _global_index(lat_min, lon_max)
    grow0, gcol0 = int(math.floor(row0f + 1e-9)), int(math.floor(col0f + 1e-9))
    grow1, gcol1 = int(math.ceil(row1f - 1e-9)), int(math.ceil(col1f - 1e-9))
    height, width = grow1 - grow0, gcol1 - gcol0
    if height <= 0 or width <= 0:
        raise LandcoverError(f"bbox {bbox} spans no WorldCover cell")
    mosaic = np.full((height, width), NODATA, dtype=np.uint8)

    stems = tiles_for_bbox(bbox)
    tiles: Dict[str, Dict[str, Any]] = {}
    for stem in stems:
        local = tile_path(cache_dir, stem)
        url = tile_url(stem)
        source = str(local) if local.is_file() else f"/vsicurl/{url}"
        lat_sw, lon_sw = tile_corner(stem)
        trow0, tcol0 = (int(round(v)) for v in _global_index(lat_sw + TILE_DEG, lon_sw))
        tile_px = TILE_DEG * 12000
        r0, r1 = max(grow0, trow0), min(grow1, trow0 + tile_px)
        c0, c1 = max(gcol0, tcol0), min(gcol1, tcol0 + tile_px)
        if r1 <= r0 or c1 <= c0:
            continue
        try:
            with rasterio.Env(**_gdal_options()):
                with rasterio.open(source) as src:
                    _check_tile_georeference(src, stem, source)
                    window = Window(c0 - tcol0, r0 - trow0, c1 - c0, r1 - r0)
                    block = src.read(1, window=window)
        except (RasterioIOError, OSError) as exc:
            raise LandcoverError(
                f"tile {stem} unreachable or unreadable at {source}: {exc}",
                reason="unreachable") from exc
        _check_legend(block, f"tile {stem}")
        mosaic[r0 - grow0:r1 - grow0, c0 - gcol0:c1 - gcol0] = block
        tiles[stem] = {
            "url": url,
            "read": "cached whole tile" if local.is_file() else "vsicurl window",
            "window": {"col_off": c0 - tcol0, "row_off": r0 - trow0,
                       "width": c1 - c0, "height": r1 - r0},
            **({} if local.is_file() else _head(url)),
            **({"sha256": sha256_of(local)} if local.is_file() else {}),
        }

    transform = from_origin(-180.0 + gcol0 * PIXEL_DEG, 90.0 - grow0 * PIXEL_DEG,
                            PIXEL_DEG, PIXEL_DEG)
    with rasterio.open(out_path, "w", driver="GTiff", height=height, width=width,
                       count=1, dtype="uint8", crs="EPSG:4326",
                       transform=transform, nodata=NODATA,
                       compress="deflate") as dst:
        dst.write(mosaic, 1)

    provenance = {
        "dataset": DATASET,
        "product_version": PRODUCT_VERSION,
        "year": YEAR,
        "bucket": BUCKET,
        "posting_deg": PIXEL_DEG,
        "posting_m_nominal": POSTING_M_NOMINAL,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "license_note": LICENSE_NOTE,
        "attribution": ATTRIBUTION,
        "citation": CITATION,
        "location": location.key,
        "bbox_deg": list(bbox),
        "tiles": tiles,
        "crop": {"file": out_path.name, "width": width, "height": height,
                 "origin_lon_deg": -180.0 + gcol0 * PIXEL_DEG,
                 "origin_lat_deg": 90.0 - grow0 * PIXEL_DEG},
        "sha256": sha256_of(out_path),
        "path": str(out_path),
    }
    meta_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return provenance


# -- the bake grid ---------------------------------------------------------


@dataclass(frozen=True)
class BakeGrid:
    """The bake's frame as its sidecar states it (glo30.bake writes it
    through Heightfield.metadata): CRS, upper-left origin, posting, size."""

    key: str
    crs: str
    origin_x_m: float
    origin_y_m: float
    pixel_size_m: float
    width: int
    height: int
    raster_sha256: Optional[str]
    sidecar: str

    def to_dict(self) -> Dict[str, Any]:
        return {"crs": self.crs, "origin_x_m": self.origin_x_m,
                "origin_y_m": self.origin_y_m, "cell_size_m": self.pixel_size_m,
                "width": self.width, "height": self.height,
                "bake_sha256": self.raster_sha256, "aligned_to_bake": self.sidecar}


GRID_KEYS = ("crs", "origin_x_m", "origin_y_m", "pixel_size_m")


def read_grid(bake_path) -> BakeGrid:
    """The grid from a bake's ``.json`` sidecar; refuses
    ``terrain.landcover_grid`` when the sidecar is absent or lacks a key."""
    sidecar = Path(bake_path).with_suffix(".json")
    if not sidecar.is_file():
        raise LandcoverGridError(f"no bake sidecar at {sidecar}")
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LandcoverGridError(f"{sidecar} is not readable JSON: {exc}") from exc
    geo = meta.get("georeference")
    missing = [k for k in GRID_KEYS if not isinstance(geo, dict) or k not in geo]
    missing += [k for k in ("width", "height") if not isinstance(meta.get(k), int)]
    if missing:
        raise LandcoverGridError(
            f"{sidecar} lacks the grid keys {missing}; cannot place land "
            f"cover on a bake whose frame is unknown")
    return BakeGrid(
        key=str(meta.get("name") or sidecar.stem),
        crs=str(geo["crs"]), origin_x_m=float(geo["origin_x_m"]),
        origin_y_m=float(geo["origin_y_m"]), pixel_size_m=float(geo["pixel_size_m"]),
        width=int(meta["width"]), height=int(meta["height"]),
        raster_sha256=meta.get("sha256"), sidecar=str(sidecar.resolve()))


def fine_subdivision(grid: BakeGrid, texels_per_cell: int = TEXELS_PER_CELL) -> int:
    k = max(1, int(texels_per_cell))
    while k > 1 and max(grid.width * k, grid.height * k) > MAX_FINE_EDGE:
        k -= 1
    return k


def bbox_for_grid(grid: BakeGrid, pad_deg: float = 5 * PIXEL_DEG
                  ) -> Tuple[float, float, float, float]:
    """The geographic bbox the grid's full cell extent covers, from its
    corners and edge midpoints, padded by a few source cells."""
    from pyproj import Transformer

    transformer = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    x0, y0 = grid.origin_x_m, grid.origin_y_m
    x1 = x0 + grid.width * grid.pixel_size_m
    y1 = y0 - grid.height * grid.pixel_size_m
    xs = [x0, (x0 + x1) / 2, x1]
    ys = [y0, (y0 + y1) / 2, y1]
    lons, lats = [], []
    for x in xs:
        for y in ys:
            lon, lat = transformer.transform(x, y)
            lons.append(lon)
            lats.append(lat)
    return (min(lats) - pad_deg, max(lats) + pad_deg,
            min(lons) - pad_deg, max(lons) + pad_deg)


def location_for_grid(grid: BakeGrid) -> Location:
    """A Location for a bake given by path alone: bbox from the grid, no
    summits, no snowline claim (0: presentation only, unused here)."""
    bbox = bbox_for_grid(grid)
    return Location(key=grid.key, title=f"land cover for bake {grid.key}",
                    tiles=(), bbox=bbox, crs=grid.crs,
                    origin_lat=(bbox[0] + bbox[1]) / 2,
                    origin_lon=(bbox[2] + bbox[3]) / 2,
                    snowline_m=0.0, summits=())


# -- rasterisation ---------------------------------------------------------


def reproject_classes(source_4326: Path, grid: BakeGrid, k: int) -> np.ndarray:
    """The class code on the fine grid (bake cells subdivided k x k),
    nearest neighbour: a class is a label, not a quantity to blend."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.errors import RasterioIOError
    from rasterio.transform import from_origin
    from rasterio.warp import reproject as rio_reproject

    transform = from_origin(grid.origin_x_m, grid.origin_y_m,
                            grid.pixel_size_m / k, grid.pixel_size_m / k)
    out = np.full((grid.height * k, grid.width * k), NODATA, dtype=np.uint8)
    try:
        with rasterio.open(source_4326) as src:
            if src.count != 1 or src.dtypes[0] != "uint8":
                raise LandcoverError(
                    f"{source_4326} has {src.count} band(s) of {src.dtypes[0]}; "
                    f"a WorldCover map is one uint8 band")
            values = src.read(1)
            _check_legend(values, str(source_4326))
            rio_reproject(
                source=values, destination=out,
                src_transform=src.transform, src_crs=src.crs,
                src_nodata=NODATA, dst_nodata=NODATA,
                dst_transform=transform, dst_crs=grid.crs,
                resampling=Resampling.nearest,
            )
    except (RasterioIOError, OSError) as exc:
        raise LandcoverError(
            f"{source_4326} is not a readable raster: {exc}") from exc
    return out


def weight_counts(fine: np.ndarray, k: int) -> Dict[str, np.ndarray]:
    """Per class, the count of fine cells of that class in each k x k
    block, keyed as WEIGHT_KEYS (nodata included)."""
    h, w = fine.shape
    if h % k or w % k:
        raise ValueError(f"fine grid {fine.shape} is not a multiple of {k}")
    blocks = fine.reshape(h // k, k, w // k, k)
    counts = {}
    for key in WEIGHT_KEYS:
        code = NODATA if key == NODATA_KEY else _CODE_BY_KEY[key]
        counts[key] = (blocks == code).sum(axis=(1, 3)).astype(np.int64)
    return counts


def weightmaps(counts: Dict[str, np.ndarray], k: int) -> Dict[str, np.ndarray]:
    """0-255 weights from the counts: 255 * count / k^2, rounded by the
    largest remainder so every cell's weights sum to exactly 255 (plain
    rounding of up to k^2 classes can miss by several counts)."""
    keys = list(counts)
    stack = np.stack([counts[key] for key in keys]).astype(np.float64)
    if not np.all(stack.sum(axis=0) == k * k):
        raise ValueError("counts do not fill every cell")
    raw = stack * 255.0 / float(k * k)
    base = np.floor(raw)
    remainder = (255 - base.sum(axis=0)).astype(np.int64)
    frac = raw - base
    # Rank each class per cell by its fractional part, largest first
    # (ties by legend order); the first `remainder` ranks get +1.
    order = np.argsort(-frac, axis=0, kind="stable")
    rank = np.argsort(order, axis=0, kind="stable")
    extra = (rank < remainder[None, :, :]).astype(np.float64)
    weights = (base + extra).astype(np.uint8)
    return {key: weights[i] for i, key in enumerate(keys)}


def majority_map(counts: Dict[str, np.ndarray]) -> np.ndarray:
    """The legend code with the most fine cells per bake cell (ties by
    legend order; nodata only where nothing else is present)."""
    keys = [key for key in WEIGHT_KEYS if key != NODATA_KEY]
    stack = np.stack([counts[key] for key in keys])
    best = np.argmax(stack, axis=0)
    codes = np.array([_CODE_BY_KEY[key] for key in keys], dtype=np.uint8)
    out = codes[best]
    out[stack.max(axis=0) == 0] = NODATA
    return out


def verify_against_source(fine: np.ndarray, grid: BakeGrid, k: int,
                          source_4326: Path, samples: int = VERIFY_SAMPLES,
                          seed: int = 20260928) -> Dict[str, Any]:
    """Fine texel -> projected -> geographic -> source pixel, class for
    class. Nearest against nearest agrees except at the odd boundary
    texel; a CRS mix-up, row flip or axis swap disagrees wholesale."""
    import rasterio
    from pyproj import Transformer

    rng = np.random.default_rng(seed)
    transformer = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    texel = grid.pixel_size_m / k
    with rasterio.open(source_4326) as src:
        band = src.read(1)
        rows = rng.integers(0, fine.shape[0], size=samples)
        cols = rng.integers(0, fine.shape[1], size=samples)
        compared = agreed = 0
        for row, col in zip(rows, cols):
            x = grid.origin_x_m + (float(col) + 0.5) * texel
            y = grid.origin_y_m - (float(row) + 0.5) * texel
            lon, lat = transformer.transform(x, y)
            src_row, src_col = src.index(lon, lat)
            if not (0 <= src_row < src.height and 0 <= src_col < src.width):
                continue
            compared += 1
            agreed += int(band[src_row, src_col] == fine[row, col])
    report = {"samples": int(compared),
              "agreement": float(agreed) / compared if compared else 0.0}
    report["ok"] = bool(compared >= samples * 0.9
                        and report["agreement"] >= VERIFY_MIN_AGREEMENT)
    return report


def landcover_variable(fractions: Dict[str, float], nodata_fraction: float,
                       parameters: Dict[str, Any]) -> AppliedVariable:
    """The ``scene.landcover`` record. Null test: the dominant class's
    fraction of the scene against the uniform prior over the 11 legend
    classes (what the scene says about its cover with no land cover data:
    every class equally likely)."""
    legend = {key: fractions[key] for key in fractions if key != NODATA_KEY}
    dominant = max(legend, key=lambda key: (legend[key], -WEIGHT_KEYS.index(key)))
    prior = 1.0 / len(LEGEND)
    null_test = NullTest(
        quantity="fraction of the scene in the dominant land cover class",
        unit="fraction", with_value=float(legend[dominant]), without_value=prior,
        threshold=NULL_TEST_THRESHOLD,
        note=f"without = the uniform prior over the {len(LEGEND)} legend classes "
             f"(no land cover data); with = the WorldCover fraction of "
             f"{dominant!r} over the bake grid, nodata counted in the total")
    return AppliedVariable(
        name="scene.landcover",
        value=dominant, unit="WorldCover legend class (dominant); fractions in parameters",
        source="derived",
        model="ESA WorldCover v200 2021 majority/fraction",
        parameters={"fractions": legend, "nodata_fraction": float(nodata_fraction),
                    "dominant_class": dominant, "license": LICENSE,
                    "attribution": ATTRIBUTION, **parameters},
        references=REFERENCES,
        properties_written=(),
        telemetry_columns=(),
        frame_keys=(),
        null_test=null_test,
        not_claimed=(
            "nothing in the engine reads the weightmaps yet: no landscape "
            "layer, material or PCG biome consumes them, no vegetation or "
            "structure is placed, and no rendered pixel changes",
            "the classes are the product's estimate (global overall accuracy "
            "76.7 +/- 0.5 % per its manual), not ground truth, and are not "
            "re-validated here",
            "2021 classes are not temporally aligned with the 2016-2017 "
            "imagery drape or the 2010-2015 GLO-30 heights",
            "a weight is the fraction of 10 m cells in a bake cell, not of "
            "area; the 10 m posting is nominal (1/12000 degree)",
        ))


def scene_dir_for(bake_path) -> Path:
    """Where a bake's land cover lives: ``<dir>/<stem>_landcover/``."""
    bake = Path(bake_path)
    return bake.with_name(f"{bake.with_suffix('').name}_landcover")


def landcover_records(bake_path) -> list:
    """The ``scene.landcover`` record for a bake, reconstructed from the
    ``landcover.json`` beside it, as a one-element list for a manifest's
    ``records_block`` -- or an empty list when the bake has no land cover
    (absent-canonical: an older scene carries no record, not a zero one).
    The record is the JSON's own, re-typed; nothing is recomputed."""
    if bake_path is None:
        return []
    path = scene_dir_for(bake_path) / "landcover.json"
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    records = (document.get("applied_variables") or {}).get("applied_variables") or []
    out = []
    for record in records:
        null = record.get("null_test")
        out.append(AppliedVariable(
            name=record["name"], value=record["value"], unit=record["unit"],
            source=record["source"], model=record["model"],
            parameters=dict(record.get("parameters") or {}),
            references=tuple(record.get("references") or ()),
            properties_written=tuple(record.get("properties_written") or ()),
            telemetry_columns=tuple(record.get("telemetry_columns") or ()),
            frame_keys=tuple(record.get("frame_keys") or ()),
            null_test=None if null is None else NullTest(
                quantity=null["quantity"], unit=null["unit"],
                with_value=null["with"], without_value=null["without"],
                threshold=null["threshold"], note=null.get("note", "")),
            not_claimed=tuple(record.get("not_claimed") or ())))
    return out


def rasterise(location_or_bake: Union[Location, str, Path], cache_dir, out_dir,
              bake_path: Optional[Union[str, Path]] = None,
              source_4326: Optional[Union[str, Path]] = None,
              texels_per_cell: int = TEXELS_PER_CELL) -> Tuple[Path, Dict[str, Any]]:
    """Fetch (or take ``source_4326``), reproject onto the bake's grid,
    count, verify, write the weightmaps and ``landcover.json``.

    ``location_or_bake`` is a curated :class:`Location` (the bake is then
    ``out_dir/<key>.r16`` unless ``bake_path`` says otherwise) or a bake
    path (the scene bbox is then derived from the bake's own grid).
    Returns the scene directory ``out_dir/<key>_landcover`` and the JSON
    written into it. Refuses by name: ``terrain.landcover_grid`` (no
    grid in the sidecar), ``terrain.landcover`` (source unreachable,
    corrupt, or disagreeing with the rasterised result).
    """
    from PIL import Image

    out_dir = Path(out_dir)
    if isinstance(location_or_bake, Location):
        location: Optional[Location] = location_or_bake
        bake = Path(bake_path) if bake_path else out_dir / f"{location.key}.r16"
    else:
        location = None
        bake = Path(location_or_bake)
    grid = read_grid(bake)
    if location is None:
        location = location_for_grid(grid)
    k = fine_subdivision(grid, texels_per_cell)

    if source_4326 is not None:
        source = Path(source_4326)
        if not source.is_file():
            raise LandcoverError(f"{source} is absent", reason="unreachable")
        provenance: Dict[str, Any] = {
            "dataset": DATASET, "product_version": PRODUCT_VERSION, "year": YEAR,
            "bucket": None, "posting_deg": PIXEL_DEG,
            "posting_m_nominal": POSTING_M_NOMINAL,
            "license": LICENSE, "license_url": LICENSE_URL,
            "license_note": LICENSE_NOTE, "attribution": ATTRIBUTION,
            "citation": CITATION, "location": location.key,
            "bbox_deg": list(location.bbox), "tiles": {},
            "crop": {"file": source.name, "note": "local source, not fetched"},
            "sha256": sha256_of(source), "path": str(source),
        }
    else:
        provenance = fetch(location, cache_dir)
        source = Path(provenance["path"])

    fine = reproject_classes(source, grid, k)
    verification = verify_against_source(fine, grid, k, source)
    if not verification["ok"]:
        raise LandcoverError(
            f"{grid.key}: rasterised classes disagree with the source window "
            f"({verification}); refusing to write unverified weightmaps",
            reason="unverified")

    counts = weight_counts(fine, k)
    weights = weightmaps(counts, k)
    majority = majority_map(counts)
    total = float(fine.size)
    fractions = {key: float(counts[key].sum()) / total for key in WEIGHT_KEYS}
    nodata_fraction = fractions[NODATA_KEY]

    # Named by the bake FILE's stem (scene_dir_for's rule), so a manifest
    # builder given the bake path finds the record without the sidecar.
    scene_dir = out_dir / scene_dir_for(bake).name
    scene_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Dict[str, Any]] = {}
    for key in WEIGHT_KEYS:
        path = scene_dir / f"{key}_weight.png"
        Image.fromarray(weights[key], mode="L").save(path)
        written[key] = {"file": path.name, "sha256": sha256_of(path)}
    class_path = scene_dir / "class_map.png"
    Image.fromarray(majority, mode="L").save(class_path)

    stack = np.stack([weights[key] for key in WEIGHT_KEYS]).astype(np.int64)
    sums = stack.sum(axis=0)
    grid_block = {**grid.to_dict(), "texels_per_cell": k,
                  "texel_size_m": grid.pixel_size_m / k,
                  "fine_width": grid.width * k, "fine_height": grid.height * k}
    record = landcover_variable(fractions, nodata_fraction, {
        "posting_deg": PIXEL_DEG, "posting_m_nominal": POSTING_M_NOMINAL,
        "texels_per_cell": k, "grid": grid_block,
        "source_sha256": provenance["sha256"],
        "verification_vs_source": verification,
        "weight_encoding": "0..255 = fraction of fine cells of the class in "
                           "the bake cell, largest-remainder rounded; the "
                           "sum over every class map (nodata included) is "
                           "exactly 255 per cell",
    })
    document = {
        "dataset": DATASET,
        "product_version": PRODUCT_VERSION,
        "year": YEAR,
        "model": "ESA WorldCover v200 2021 majority/fraction",
        "posting_deg": PIXEL_DEG,
        "posting_m_nominal": POSTING_M_NOMINAL,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "license_note": LICENSE_NOTE,
        "attribution": ATTRIBUTION,
        "citation": CITATION,
        "source": {key: provenance[key] for key in (
            "dataset", "bucket", "location", "bbox_deg", "tiles", "crop", "path")},
        "sha256": provenance["sha256"],
        "classes": [{"code": c.code, "key": c.key, "title": c.title,
                     "rgb": list(c.rgb), "file": written[c.key]["file"],
                     "fraction": fractions[c.key]} for c in LEGEND],
        "fractions": {key: fractions[key] for key in WEIGHT_KEYS if key != NODATA_KEY},
        "nodata_fraction": nodata_fraction,
        "coverage": 1.0 - nodata_fraction,
        "dominant_class": record.value,
        "grid": grid_block,
        "weightmaps": written,
        "class_map": {"file": class_path.name, "sha256": sha256_of(class_path),
                      "encoding": "legend code per bake cell, majority of fine "
                                  "cells; 0 = nodata"},
        "weight_sum_per_cell": {"min": int(sums.min()), "max": int(sums.max()),
                                "expected": 255},
        "verification_vs_source": verification,
        "applied_variables": records_block([record]),
        "not_claimed": list(record.not_claimed),
    }
    (scene_dir / "landcover.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8")
    return scene_dir, document
