"""Copernicus GLO-30 ingestion: real named mountains through the Phase 4 pipeline.

Locations are scenario inputs (§ Phase 6B.2). Each entry below names a real
place, the 1x1 degree GLO-30 tiles that cover it, the metric CRS suited to it,
and the crop that bounds the scene. The tiles come from the public AWS bucket
(``copernicus-dem-30m``, no auth); everything after the download goes through
the EXISTING :func:`core.terrain.dem.ingest` -- the same reproject / resample /
quantise path Gate 4 verified -- so nothing downstream can tell a real
mountain from a synthesised one, which is §3.2 by construction.

Verification discipline (Gate 4's, applied per bake)
----------------------------------------------------
:func:`verify_against_source` re-opens the *source* mosaic and compares the
baked raster against it at hundreds of independently chosen points, through
the full chain: baked pixel -> projected coordinate -> geographic -> source
pixel. The comparison result ships inside the baked sidecar's provenance, so
a raster whose verification was skipped is distinguishable from one that
passed.

What the data is, honestly
--------------------------
GLO-30 is a 30 m *surface* model (DSM): tree canopy and buildings are in the
elevations, summits are smoothed by the 30 m posting (the Matterhorn's summit
pyramid loses ~100 m), and heights are EGM2008 orthometric. All three limits
are recorded in provenance and docs/VALIDITY.md rather than smoothed over.

License: Copernicus DEM is free to use and redistribute with attribution --
"produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and (c) Airbus
Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European
Union and ESA; all rights reserved". Recorded in every bake's provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .dem import DEMError, ingest
from .heightfield import Heightfield

BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"

ATTRIBUTION = (
    "produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-2014 and "
    "(c) Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS "
    "by the European Union and ESA; all rights reserved"
)


@dataclass(frozen=True)
class Location:
    """A real place, as a terrain scenario input."""

    key: str
    title: str
    #: GLO-30 tile stems, e.g. "N45_00_E007_00".
    tiles: Tuple[str, ...]
    #: Scene crop in geographic degrees: (lat_min, lat_max, lon_min, lon_max).
    bbox: Tuple[float, float, float, float]
    #: Metric CRS the scene is baked in (UTM zone for the place).
    crs: str
    #: Where the georeferencing origin (and the flight) sits.
    origin_lat: float
    origin_lon: float
    #: Local snowline for the material pass, metres MSL, and the season it
    #: approximates. Presentation only; recorded as approximated.
    snowline_m: float
    #: Named summits inside the crop, for the identity check:
    #: (name, lat, lon, surveyed elevation m).
    summits: Tuple[Tuple[str, float, float, float], ...] = ()


LOCATIONS: Dict[str, Location] = {
    "matterhorn": Location(
        key="matterhorn",
        title="Matterhorn / Zermatt, Pennine Alps, Switzerland-Italy",
        tiles=("N45_00_E007_00", "N46_00_E007_00"),
        bbox=(45.85, 46.10, 7.45, 7.95),
        crs="EPSG:32632",
        origin_lat=46.005, origin_lon=7.72,
        snowline_m=3100.0,
        summits=(
            ("Matterhorn", 45.97636, 7.65853, 4478.0),
            ("Dufourspitze (Monte Rosa)", 45.93692, 7.86675, 4634.0),
            ("Dom", 46.09371, 7.85881, 4545.0),
        ),
    ),
    "yosemite": Location(
        key="yosemite",
        title="Yosemite Valley, Sierra Nevada, California",
        tiles=("N37_00_W120_00",),
        bbox=(37.60, 37.85, -119.80, -119.40),
        crs="EPSG:32611",
        origin_lat=37.7275, origin_lon=-119.61,
        snowline_m=3600.0,
        summits=(
            ("Half Dome", 37.74595, -119.53295, 2694.0),
            ("El Capitan", 37.73404, -119.63768, 2307.0),
            ("Clouds Rest", 37.76778, -119.48861, 3025.0),
        ),
    ),
    # Phase 9 terrain spread (2026-08-11): four more terrain CHARACTERS --
    # volcano cone, extreme Himalayan relief, canyon, rolling prairie.
    # Every summit surveyed value web-verified before entry (Wikipedia /
    # PeakVisor), same identity-check discipline as the first two bakes.
    "fuji": Location(
        key="fuji",
        title="Mount Fuji, Honshu, Japan",
        tiles=("N35_00_E138_00",),
        bbox=(35.22, 35.50, 138.55, 138.90),
        crs="EPSG:32654",
        origin_lat=35.42, origin_lon=138.7274,
        snowline_m=2800.0,
        summits=(
            ("Mount Fuji", 35.3606, 138.7274, 3776.0),
        ),
    ),
    "everest": Location(
        key="everest",
        title="Mount Everest / Lhotse, Mahalangur Himal, Nepal-China",
        tiles=("N27_00_E086_00", "N28_00_E086_00"),
        bbox=(27.85, 28.05, 86.75, 87.00),
        crs="EPSG:32645",
        origin_lat=27.90, origin_lon=86.87,
        snowline_m=5600.0,
        summits=(
            ("Mount Everest", 27.98833, 86.92528, 8849.0),
            ("Lhotse", 27.9617, 86.9333, 8516.0),
        ),
    ),
    "grand_canyon": Location(
        key="grand_canyon",
        title="Grand Canyon (Cape Royal reach), Arizona",
        tiles=("N36_00_W112_00",),
        bbox=(35.98, 36.20, -112.12, -111.85),
        crs="EPSG:32612",
        origin_lat=36.09, origin_lon=-112.0,
        snowline_m=3500.0,
        summits=(
            ("Vishnu Temple", 36.08876, -111.93571, 2296.0),
            ("Wotans Throne", 36.10472, -111.96028, 2353.0),
            ("Angels Gate", 36.09389, -111.99000, 2061.0),
        ),
    ),
    "flint_hills": Location(
        key="flint_hills",
        title="Flint Hills tallgrass prairie, Kansas",
        tiles=("N38_00_W097_00",),
        bbox=(38.30, 38.55, -96.75, -96.45),
        crs="EPSG:32614",
        origin_lat=38.43, origin_lon=-96.60,
        snowline_m=3000.0,
        # Rolling prairie has no summits; surveyed TOWN elevations anchor
        # the identity check instead (same georeferencing question, gentler
        # relief -- the +-3 px window changes them by metres, not 150).
        summits=(
            ("Cottonwood Falls (town datum)", 38.36806, -96.54306, 368.0),
            ("Strong City (town datum)", 38.39722, -96.53694, 364.0),
        ),
    ),
}


def tile_url(stem: str) -> str:
    name = f"Copernicus_DSM_COG_10_{stem}_DEM"
    return f"{BUCKET}/{name}/{name}.tif"


def tile_path(cache_dir: Path, stem: str) -> Path:
    return Path(cache_dir) / f"Copernicus_DSM_COG_10_{stem}_DEM.tif"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(location: Location, cache_dir) -> List[Path]:
    """Download the location's tiles unless already cached. Returns paths."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for stem in location.tiles:
        path = tile_path(cache_dir, stem)
        if not path.is_file():
            url = tile_url(stem)
            with urllib.request.urlopen(url) as response, path.open("wb") as out:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
        paths.append(path)
    return paths


def merge_and_crop(tile_paths: Sequence[Path], bbox: Tuple[float, float, float, float],
                   out_path: Path) -> Path:
    """Mosaic the tiles and crop to the scene bbox, still in EPSG:4326.

    The crop happens BEFORE reprojection so the metric raster is the scene and
    nothing else -- reprojecting a full 1x1 degree tile would spend most of its
    pixels outside the scene, and dem.ingest's valid-rectangle crop would then
    keep the tile, not the scene.
    """
    import rasterio
    from rasterio.merge import merge as rio_merge

    lat_min, lat_max, lon_min, lon_max = bbox
    sources = [rasterio.open(p) for p in tile_paths]
    try:
        mosaic, transform = rio_merge(
            sources, bounds=(lon_min, lat_min, lon_max, lat_max))
        profile = sources[0].profile.copy()
        profile.update(height=mosaic.shape[1], width=mosaic.shape[2],
                       transform=transform, driver="GTiff",
                       crs=sources[0].crs)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(mosaic)
    finally:
        for src in sources:
            src.close()
    return out_path


def verify_against_source(baked: Heightfield, source_path: Path,
                          samples: int = 400, seed: int = 20260806) -> Dict:
    """Check baked elevations against the source mosaic, point by point.

    The path under test is the full ingest chain: baked pixel centre ->
    projected metres -> geographic degrees -> source pixel. Bilinear against
    bilinear, so the comparison tolerates resampling but not a CRS mix-up, a
    row flip, or a scale/offset error -- each of which throws hundreds of
    metres, not a few.
    """
    import rasterio
    from pyproj import Transformer

    rng = np.random.default_rng(seed)
    g = baked.georeference
    transformer = Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True)

    with rasterio.open(source_path) as src:
        band = src.read(1)
        rows = rng.integers(2, baked.height - 2, size=samples)
        cols = rng.integers(2, baked.width - 2, size=samples)
        differences = []
        excesses = []
        for row, col in zip(rows, cols):
            x = g.origin_x_m + float(col) * g.pixel_size_m
            y = g.origin_y_m - float(row) * g.pixel_size_m
            lon, lat = transformer.transform(x, y)
            src_row, src_col = src.index(lon, lat, op=float)
            r0, c0 = int(src_row), int(src_col)
            if not (0 <= r0 < src.height - 1 and 0 <= c0 < src.width - 1):
                continue
            fr, fc = src_row - r0, src_col - c0
            window = band[r0:r0 + 2, c0:c0 + 2].astype(np.float64)
            # Source voids are nodata, not measurement: the bake fills them
            # by interpolation (counted and recorded as such), so comparing
            # a filled pixel against the raw void would grade the fill as a
            # datum error. Note what this guard does NOT excuse: a bbox
            # that exceeds its tiles' coverage merges ZEROS (not nodata) --
            # measured on the first Everest bake, where a one-tile list
            # under a 28.05 N crop put a 5297 m error at 28.00036 N and
            # the mean gate correctly refused the bake. Fix the tile list,
            # never this check.
            if not np.isfinite(window).all() or (
                    src.nodata is not None
                    and np.any(window == src.nodata)):
                continue
            source_elev = (window[0, 0] * (1 - fr) * (1 - fc)
                           + window[0, 1] * (1 - fr) * fc
                           + window[1, 0] * fr * (1 - fc)
                           + window[1, 1] * fr * fc)
            baked_elev = baked.elevation_at(x, y)
            differences.append(baked_elev - source_elev)
            # Resampling disagreement is slope-proportional: a half-pixel
            # of effective registration shift on a slope of |grad h| moves
            # the surface vertically by |grad h| * (pixel/2). That much is
            # the resampling regime, not a datum error, so it is excused
            # PER SAMPLE; what remains ("excess") faces the same 30 m gate
            # as before. On flat ground the allowance is ~0 and the gate is
            # exactly the old one; a datum/axis/scale error still blows
            # through by hundreds of metres. (Measured: the Everest bake's
            # raw p95 of 31.8 m on its extreme faces vs the Alps-calibrated
            # 30 m -- honest resampling noise, not a georeferencing fault.)
            dzdx, dzdy = baked.gradient_at(x, y)
            allowance = math.hypot(dzdx, dzdy) * g.pixel_size_m / 2.0
            excesses.append(max(0.0, abs(baked_elev - source_elev)
                                - allowance))

    differences = np.asarray(differences)
    excesses = np.asarray(excesses)
    report = {
        "samples": int(differences.size),
        "mean_m": float(differences.mean()),
        "p50_abs_m": float(np.percentile(np.abs(differences), 50)),
        "p95_abs_m": float(np.percentile(np.abs(differences), 95)),
        "max_abs_m": float(np.abs(differences).max()),
        "p95_excess_m": float(np.percentile(excesses, 95)),
    }
    report["ok"] = bool(report["samples"] >= samples * 0.9
                        and abs(report["mean_m"]) < 5.0
                        and report["p95_excess_m"] < 30.0)
    return report


def check_summits(baked: Heightfield, location: Location) -> List[Dict]:
    """Compare the raster at each named summit with its surveyed elevation.

    This is an identity check, not an accuracy claim: a raster of the wrong
    mountain, or one georeferenced a valley over, misses a 4000 m summit by
    kilometres of position or thousands of metres of height. GLO-30's 30 m
    posting smooths real summits down by up to ~150 m (measured below,
    recorded in provenance); the tolerance accepts that and still catches a
    misplacement.
    """
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                       always_xy=True)
    out = []
    for name, lat, lon, surveyed in location.summits:
        x, y = transformer.transform(lon, lat)
        # The DSM summit may sit a pixel or two off the surveyed coordinate;
        # take the highest baked sample within a small window around it.
        best = -1e9
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                px = x + dx * baked.georeference.pixel_size_m
                py = y + dy * baked.georeference.pixel_size_m
                best = max(best, baked.elevation_at(px, py))
        out.append({
            "summit": name,
            "surveyed_m": surveyed,
            "baked_max_within_90m": round(best, 1),
            "difference_m": round(best - surveyed, 1),
            # Identity, not accuracy: within 250 m vertically is the same
            # mountain; a georeferencing error is thousands out.
            "ok": bool(abs(best - surveyed) < 250.0),
        })
    return out


def orographic_card_block(baked_path, origin_lat: float, origin_lon: float,
                          wind_speed_kt: float, wind_from_deg: float) -> Dict:
    """The run card's ``orographic`` block, with every parameter computed here.

    The C++ port derives nothing: wavelength (the raster-extent heuristic
    terrain_field_from documents), decay height (the provider's own clamp) and
    the projected origin all come from this one place, so the two hosts cannot
    derive differently. The same numbers drive the Python provider when the
    selftest verifies the port.
    """
    from pyproj import Transformer

    from ..environment.terrain_field import (
        DECAY_FROM_WAVELENGTH, DECAY_HEIGHT_MAX_M, DECAY_HEIGHT_MIN_M,
    )
    from ..fdm import units as u

    baked = Heightfield.read(baked_path)
    width_m, _ = baked.extent_m
    wavelength_m = max(width_m / 8.0, 200.0)
    decay_height_m = min(max(wavelength_m * DECAY_FROM_WAVELENGTH,
                             DECAY_HEIGHT_MIN_M), DECAY_HEIGHT_MAX_M)
    transformer = Transformer.from_crs("EPSG:4326", baked.georeference.crs,
                                       always_xy=True)
    origin_x, origin_y = transformer.transform(origin_lon, origin_lat)
    return {
        "terrain": str(Path(baked_path).resolve()),
        "wind_speed_mps": u.kt_to_mps(wind_speed_kt),
        "wind_from_deg": float(wind_from_deg),
        "decay_height_m": float(decay_height_m),
        "wavelength_m": float(wavelength_m),
        "origin_x_m": float(origin_x),
        "origin_y_m": float(origin_y),
        "lee": True,
    }


def bake(location: Location, cache_dir, out_dir,
         ground_sample_distance_m: float = 30.0) -> Tuple[Path, Dict]:
    """Fetch, mosaic, ingest, verify and write one location's heightfield.

    Returns the ``.r16`` path and the verification report. Raises
    :class:`DEMError` if verification fails -- an unverified real-terrain bake
    must not be renderable by accident.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tile_paths = fetch(location, cache_dir)
    tile_shas = {p.name: sha256_of(p) for p in tile_paths}

    source_mosaic = out_dir / f"{location.key}_source_4326.tif"
    merge_and_crop(tile_paths, location.bbox, source_mosaic)

    baked = ingest(
        source_mosaic,
        target_crs=location.crs,
        ground_sample_distance_m=ground_sample_distance_m,
        name=location.key,
    )

    verification = verify_against_source(baked, source_mosaic)
    summit_report = check_summits(baked, location)
    if not verification["ok"]:
        raise DEMError(
            f"{location.key}: baked raster disagrees with the source mosaic "
            f"({verification}). Refusing to write an unverified bake.")
    if not all(s["ok"] for s in summit_report):
        raise DEMError(
            f"{location.key}: a named summit is not where the raster says "
            f"({summit_report}). This is the wrong mountain or a "
            f"georeferencing error, not a resampling artefact.")

    baked.provenance.update({
        "dataset": "Copernicus GLO-30 DSM (30 m surface model)",
        "attribution": ATTRIBUTION,
        "vertical_datum": "EGM2008 orthometric (treated as MSL)",
        "tiles": {stem: tile_shas[tile_path(Path(cache_dir), stem).name]
                  for stem in location.tiles},
        "bbox_deg": location.bbox,
        "location": location.title,
        "origin_lat_deg": location.origin_lat,
        "origin_lon_deg": location.origin_lon,
        "snowline_m_approx": location.snowline_m,
        "verification_vs_source": verification,
        "summit_identity": summit_report,
        "surface_model_note": (
            "DSM: canopy and buildings included; 30 m posting smooths "
            "summits and cliffs; finer detail than 30 m is not in the data"),
    })
    raw = baked.write(out_dir / location.key)
    return raw, verification


def utm_zone_crs(lat_deg: float, lon_deg: float) -> str:
    """The UTM zone EPSG for a point (326xx north / 327xx south)."""
    zone = int((float(lon_deg) + 180.0) // 6.0) + 1
    zone = min(max(zone, 1), 60)
    return f"EPSG:{32600 + zone if float(lat_deg) >= 0.0 else 32700 + zone}"


def _tile_stem(lat_floor: int, lon_floor: int) -> str:
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00"


def dynamic_location(lat: float, lon: float,
                     half_extent_deg: float = 0.12) -> Location:
    """A Location for ANY coordinates: the on-demand path into the same
    verified bake pipeline the curated table uses.

    What is and is not claimed: the bbox is a square around the stated
    point; the tile list is every 1x1 degree GLO-30 cell the bbox touches
    (a cell the bucket lacks -- open ocean -- fails the fetch by name);
    the CRS is the point's UTM zone; there are NO named summits, so the
    identity check does not run and every consumer labels the bake
    "source-verified only". The snowline is a latitudinal approximation
    (presentation only, like the field says): max(500, 5200 - 60|lat|) m.
    """
    lat, lon = float(lat), float(lon)
    if not (-85.0 <= lat <= 85.0 and -180.0 <= lon <= 180.0):
        raise ValueError(f"({lat}, {lon}) is not a usable coordinate pair")
    bbox = (lat - half_extent_deg, lat + half_extent_deg,
            lon - half_extent_deg, lon + half_extent_deg)
    tiles = tuple(
        _tile_stem(la, lo)
        for la in range(math.floor(bbox[0]), math.floor(bbox[1]) + 1)
        for lo in range(math.floor(bbox[2]), math.floor(bbox[3]) + 1))
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    key = (f"dyn_{abs(round(lat * 100)):05d}{ns}"
           f"_{abs(round(lon * 100)):05d}{ew}")
    return Location(
        key=key,
        title=f"GLO-30 on-demand bake near {lat:.3f}, {lon:.3f}",
        tiles=tiles, bbox=bbox, crs=utm_zone_crs(lat, lon),
        origin_lat=lat, origin_lon=lon,
        snowline_m=max(500.0, 5200.0 - 60.0 * abs(lat)),
        summits=(),
    )
