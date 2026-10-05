"""An X-Plane ground texture for a terrain bake: the drape a render wears.

The georeferenced terrain is textured either by a drape sidecar
(``-imagery=``, the path core.terrain.imagery built for Sentinel-2) or by
the engine's four flat vertex colours. This module writes a drape in the
SAME sidecar format from X-Plane's own ground textures, so the engine needs
no change to show them:

* every DEM pixel is classified by slope and height with the rule of
  FlightSimVisualScene's ClassifyVertex (snow above the bake's approximate
  snowline, rock on steep ground, scrub below the snowline, valley floor
  otherwise), plus a cliff class above 50-58 degrees, with smooth
  transitions instead of hard cuts;
* each class is X-Plane's texture for it, tiled at the ground size X-Plane
  itself projects it at (assets/xplane/terrain/drape/drape_textures.json);
* where the X-Plane water mask has a polygon the texel is X-Plane's own
  water colour: the per-tile water texture of the committed render assets
  (core.xplane.physical.WaterTiles, what the simulator's own water shader
  loads for that degree) when the bake's tile has one, else the "water
  color" strip of sky_colors_clean;
* when the scene's calendar month is known, the MODIS monthly snow cover
  of the committed render assets (core.xplane.physical.SnowCover, 10 km
  cells) MODULATES the snow class: ground the rule already whitens thins
  where the satellite saw bare ground that month, and the gentle high
  ground just below the snowline whitens where it saw snow. The 30 m
  shape still decides WHERE within a cell; the satellite decides whether
  that month had snow there at all.

What this is NOT: X-Plane's terrain. The SHAPE is the bake's (Copernicus
GLO-30 or the synthesised ridge); the placement of each texture is this
module's slope/height rule, not X-Plane's land-class data (its DSF tiles
are not read); the water mask covers only the tiles the extraction had;
the snow cover is one captured year's months, not the scene's year. The
sidecar says "approximated" and names the textures and rasters it used.

Texel grid: the bake's CRS, origin and extent, subdivided an integer number
of times (core.terrain.imagery.TexelGrid), so the drape cannot drift off
the DEM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

from ..terrain.glo30 import sha256_of
from ..terrain.heightfield import Heightfield
from ..terrain.imagery import TexelGrid
from . import (DATA_DIR, RENDER_DIR, WaterMask, XPlaneDataError, _require,
               load_sky_tables)
from .physical import (SNOW_COVER_ATTRIBUTION, SNOW_COVER_DATASET,
                       SNOW_COVER_YEAR, WATER_FALLBACK_NOTE, SnowCover,
                       WaterTiles, season_for)

#: Bump when the classification or compositing changes, so a cached drape
#: from an older rule is rebuilt instead of reused. 2: MODIS snow cover
#: modulates the snow class; the per-tile water colour. 3: the sidecar
#: records the simulator-shaped season (index, blend, mask) and names
#: the water fallback for what it is.
DRAPE_VERSION = 3
ROLES = ("valley", "scrub", "rock", "cliff", "snow")
#: DEM rows composited per step (bounds memory on an 8192-texel drape).
_CHUNK_ROWS = 256

LICENSE = "Local simulator-derived texture set"
ATTRIBUTION = "Ground textures and water colour: local simulator-derived data"
#: Snow-cover fraction at or above which a cell counts as "saw snow" for
#: the sidecar's summary (the blend itself is continuous).
SNOW_SEEN = 0.5


def _smoothstep(low: float, high: float, value: np.ndarray) -> np.ndarray:
    t = np.clip((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def classify(elevation_m: np.ndarray, pixel_size_m: float,
             snowline_m: float,
             snow_cover: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    """Per-pixel weight of each role (float32, summing to 1).

    ``snow_cover`` (same shape, fraction 0..1, NaN = unknown) is the
    month's satellite snow cover: where it is known, the rule's snow is
    scaled by ``0.25 + 0.75 * cover`` (bare ground seen from orbit thins
    the snow but a north face above the line keeps a quarter), and the
    gentle ground in the scrub band below the snowline gains ``cover``
    worth of snow. Unknown cells keep the height rule alone.
    """
    dz_dy, dz_dx = np.gradient(elevation_m, pixel_size_m)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    cliff = _smoothstep(50.0, 58.0, slope)
    steep = _smoothstep(30.0, 38.0, slope)
    if snowline_m > 0.0:
        # ClassifyVertex: scrub within 900 m below the snowline.
        high = _smoothstep(snowline_m - 1100.0, snowline_m - 700.0,
                           elevation_m)
        # ...and snow blended across 300 m around the line, not on the
        # steepest faces (52 degrees there; softened here).
        snow = (np.clip((elevation_m - (snowline_m - 150.0)) / 300.0,
                        0.0, 1.0)
                * (1.0 - _smoothstep(48.0, 56.0, slope)))
    else:
        # No snowline (the synthesised ridge): scrub is the hillsides.
        high = _smoothstep(12.0, 25.0, slope)
        snow = np.zeros_like(slope)
    gentle = 1.0 - steep
    if snow_cover is not None:
        if snow_cover.shape != elevation_m.shape:
            raise ValueError(
                f"snow cover {snow_cover.shape} does not match the DEM "
                f"{elevation_m.shape}")
        known = np.isfinite(snow_cover)
        cover = np.where(known, snow_cover, 0.0)
        scrub_band = gentle * high * (1.0 - cliff)
        seen = np.maximum(snow * (0.25 + 0.75 * cover), cover * scrub_band)
        snow = np.where(known, seen, snow)
    weights = {
        "cliff": cliff,
        "rock": steep * (1.0 - cliff),
        "scrub": gentle * high * (1.0 - cliff),
        "valley": gentle * (1.0 - high) * (1.0 - cliff),
    }
    weights = {name: w * (1.0 - snow) for name, w in weights.items()}
    weights["snow"] = snow
    return {name: w.astype(np.float32) for name, w in weights.items()}


def _load_tiles(data_dir: Path, texel_size_m: float) -> Dict[str, Any]:
    drape_dir = data_dir / "terrain" / "drape"
    index_path = _require(drape_dir / "drape_textures.json")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    tiles = {}
    for role in ROLES:
        if role not in index:
            raise XPlaneDataError(f"{index_path} has no {role!r} texture")
        entry = index[role]
        with Image.open(_require(drape_dir / entry["file"])) as im:
            size = (max(2, round(entry["metres_x"] / texel_size_m)),
                    max(2, round(entry["metres_y"] / texel_size_m)))
            tiles[role] = np.asarray(
                im.convert("RGB").resize(size, Image.LANCZOS),
                dtype=np.float32)
    return {"tiles": tiles, "index": index}


def _tiled(tile: np.ndarray, row0: int, rows: int, width: int) -> np.ndarray:
    """``rows`` x ``width`` texels of a repeating tile, starting at row0."""
    row_index = (np.arange(row0, row0 + rows) % tile.shape[0])
    col_index = (np.arange(width) % tile.shape[1])
    return tile[row_index][:, col_index]


def water_colour(data_dir: Path) -> Optional[tuple]:
    """X-Plane's clear-sky daytime water colour, or None without tables."""
    try:
        tables = load_sky_tables(data_dir / "lighting" / "sky_tables.json")
        colour = tables["clean"]["evening"]["day"]["water"]
    except (XPlaneDataError, KeyError):
        return None
    return (int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16))


def bake_centre_lat_lon(baked: Heightfield) -> Optional[tuple]:
    """(lat, lon) of the bake's centre, or None when its CRS does not
    project back (the all-default synthetic frame)."""
    from pyproj import Transformer

    g = baked.georeference
    inverse = Transformer.from_crs(g.crs, "EPSG:4326", always_xy=True)
    lon, lat = inverse.transform(g.origin_x_m + 0.5 * baked.width * g.pixel_size_m,
                                 g.origin_y_m - 0.5 * baked.height * g.pixel_size_m)
    if not (np.isfinite(lat) and np.isfinite(lon)):
        return None
    return float(lat), float(lon)


def water_colour_for(data_dir: Path, render_dir: Path,
                     centre: Optional[tuple]) -> tuple:
    """(rgb, source) for a bake: the committed per-tile water texture's
    colour when the bake's tile has one (what the simulator's own water
    shader binds for that degree, create_water_shader), else the sky
    table's water strip standing in for the simulator's single global
    fallback texture (:data:`WATER_FALLBACK_NOTE`); (None, None) with
    neither."""
    if centre is not None:
        try:
            tiles = WaterTiles.load(render_dir)
        except XPlaneDataError:
            tiles = None
        if tiles is not None:
            colour = tiles.colour(*centre)
            if colour is not None:
                return colour, ("per-tile water texture "
                                f"{tiles.path(*centre).relative_to(tiles.root)}")
    colour = water_colour(data_dir)
    return colour, (f"sky_colors_clean water strip ({WATER_FALLBACK_NOTE})"
                    if colour else None)


def drape_paths(baked_path) -> Dict[str, Path]:
    stem = Path(baked_path)
    return {"png": stem.with_name(stem.name + "_xplane_drape.png"),
            "sidecar": stem.with_name(stem.name + "_xplane_drape.json")}


def build_drape(baked_path, data_dir: Optional[Path] = None,
                water_mask: Optional[WaterMask] = None,
                month: Optional[int] = None,
                render_dir: Optional[Path] = None) -> Path:
    """Write ``<bake>_xplane_drape.png`` + ``.json`` beside the bake and
    return the sidecar path. A drape already built from this bake by this
    version of the rule, for this ``month`` (None = the height rule
    alone), is reused. Raises XPlaneDataError when the extracted textures
    are missing; a missing snow-cover or water-tile raster is recorded in
    the sidecar and the drape falls back to the extraction's own data."""
    data_dir = Path(data_dir) if data_dir else DATA_DIR
    render_dir = Path(render_dir) if render_dir else RENDER_DIR
    month = int(month) if month is not None else None
    baked_path = Path(baked_path)
    paths = drape_paths(baked_path)
    raster = baked_path.with_name(baked_path.name + ".r16")
    bake_sha = sha256_of(raster) if raster.is_file() else None
    if paths["sidecar"].is_file() and paths["png"].is_file():
        try:
            previous = json.loads(paths["sidecar"].read_text(encoding="utf-8"))
        except ValueError:
            previous = {}
        if (previous.get("drape_version") == DRAPE_VERSION
                and previous.get("bake_sha256") == bake_sha
                and (previous.get("snow_cover") or {}).get("month") == month):
            return paths["sidecar"]

    baked = Heightfield.read(baked_path)
    grid = TexelGrid.from_bake(baked)
    k = round(baked.georeference.pixel_size_m / grid.texel_size_m)
    loaded = _load_tiles(data_dir, grid.texel_size_m)
    snowline = float(baked.provenance.get("snowline_m_approx", 0.0) or 0.0)
    centre = bake_centre_lat_lon(baked)

    # The simulator's season shape (four seasons, index + blend) for the
    # record; the stand-in rule is the month's meteorological season, the
    # visible seasonal effect is the satellite snow cover below.
    season = (season_for(month, centre[0])
              if month is not None and centre is not None else None)
    snow_cover = None
    snow_record: Dict[str, Any] = {"month": month, "source": None}
    if month is not None:
        try:
            cover = SnowCover.load(month, render_dir)
        except XPlaneDataError as exc:
            snow_record["missing"] = str(exc)
        else:
            g = baked.georeference
            snow_cover = cover.rasterize_projected(
                g.crs, g.origin_x_m, g.origin_y_m, g.pixel_size_m,
                baked.width, baked.height)
            known = np.isfinite(snow_cover)
            snow_record.update({
                "dataset": SNOW_COVER_DATASET,
                "year": SNOW_COVER_YEAR,
                "source": cover.source.name,
                "cell_deg": 0.1,
                "known_fraction": round(float(known.mean()), 4),
                "mean_cover": (round(float(snow_cover[known].mean()), 4)
                               if known.any() else None),
                "seen_snow_fraction": (
                    round(float((snow_cover[known] >= SNOW_SEEN).mean()), 4)
                    if known.any() else None),
                "rule": "rule snow x (0.25 + 0.75 cover); scrub band gains "
                        "cover; unknown cells keep the height rule",
            })
            if not known.any():
                snow_cover = None
    weights = classify(baked.elevations(), baked.georeference.pixel_size_m,
                       snowline, snow_cover)

    texture = np.empty((grid.height, grid.width, 3), dtype=np.uint8)
    for row0 in range(0, baked.height, _CHUNK_ROWS):
        rows = min(_CHUNK_ROWS, baked.height - row0)
        out_rows = rows * k
        block = np.zeros((out_rows, grid.width, 3), dtype=np.float32)
        for role in ROLES:
            # One row of context each side so the bilinear upsample does
            # not seam at chunk boundaries.
            lo = max(row0 - 1, 0)
            hi = min(row0 + rows + 1, baked.height)
            piece = Image.fromarray(weights[role][lo:hi], mode="F").resize(
                (grid.width, (hi - lo) * k), Image.BILINEAR)
            weight = np.asarray(piece, dtype=np.float32)[
                (row0 - lo) * k:(row0 - lo) * k + out_rows]
            block += weight[:, :, None] * _tiled(
                loaded["tiles"][role], row0 * k, out_rows, grid.width)
        texture[row0 * k:row0 * k + out_rows] = np.clip(
            block + 0.5, 0.0, 255.0).astype(np.uint8)

    water_texels = 0
    colour, colour_source = water_colour_for(data_dir, render_dir, centre)
    if colour is not None:
        if water_mask is None:
            try:
                water_mask = WaterMask.load(
                    data_dir / "water" / "water_polygons.geojson")
            except XPlaneDataError:
                water_mask = None
        if water_mask is not None:
            wet = water_mask.rasterize_projected(
                grid.crs, grid.origin_x_m, grid.origin_y_m,
                grid.texel_size_m, grid.width, grid.height)
            water_texels = int(wet.sum())
            texture[wet] = colour

    Image.fromarray(texture).save(paths["png"])
    fractions = {role: round(float(weights[role].mean()), 4)
                 for role in ROLES}
    sidecar = {
        "dataset": "Local simulator-derived ground textures, tiled by a "
                   "slope/height classification (approximated)",
        "license": LICENSE,
        "attribution": (ATTRIBUTION + ("; " + SNOW_COVER_ATTRIBUTION
                                       if snow_cover is not None else "")),
        "source_note": (
            "terrain SHAPE is the bake's, not X-Plane's; texture placement "
            "is this repository's slope/height rule (core/xplane/drape.py), "
            "not X-Plane land-class data; water is X-Plane's map-data "
            "polygons, present only in the tiles that were extracted; snow "
            "cover, when a month is known, is one captured year's MODIS "
            "monthly product at 10 km, modulating the rule, not placing "
            "snow by itself"),
        "drape_version": DRAPE_VERSION,
        "bake_sha256": bake_sha,
        "centre_lat_lon": list(centre) if centre else None,
        "snowline_m_approx": snowline,
        "season": ({"name": season.name, "index": season.index,
                    "blend": round(season.blend, 4), "mask": season.mask,
                    "value": round(season.value, 4), "basis": season.basis}
                   if season else None),
        "snow_cover": snow_record,
        "class_fractions": fractions,
        "water_texels": water_texels,
        "water_colour_srgb8": list(colour) if colour else None,
        "water_colour_source": colour_source,
        "textures": loaded["index"],
        "texture": {
            "file": paths["png"].name,
            "sha256": None,
            "crs": grid.crs,
            "origin_x_m": grid.origin_x_m, "origin_y_m": grid.origin_y_m,
            "texel_size_m": grid.texel_size_m,
            "width": grid.width, "height": grid.height,
            "aligned_to_bake": str(baked_path.resolve()),
            "texels_per_dem_pixel": k,
        },
    }
    sidecar["texture"]["sha256"] = sha256_of(paths["png"])
    paths["sidecar"].write_text(json.dumps(sidecar, indent=2),
                                encoding="utf-8")
    return paths["sidecar"]
