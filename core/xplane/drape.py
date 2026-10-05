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
  cells) seasons the ground the way the simulator's shaders do: its
  permanent snow (the height rule's ice texture) thins where the
  satellite saw bare ground that month, and WEATHER snow is composited
  the way the simulator's weather_apply pass does it (disassembled from
  the committed SPIR-V, assets/physical_renders/Resources/shaders): the
  terrain shader writes a luminance KEY per texel, the pass thresholds
  ``key + jitter`` against a global snow level with a smoothstep band,
  multiplies by a LINEAR ramp in cos(slope) between two values, turns
  that coverage into ``cov = saturate(2 * coverage - 1 + snow.a)`` with
  the dedicated snow albedo's alpha, and mixes the snow albedo in by
  ``cov``. Here the satellite cover stands in for the global snow level
  (the simulator's is a weather global), the band, jitter, slope values
  and texture scales are this repository's constants (the simulator's
  are globals the decompilation does not show), the decal-modulation
  terms whose constants are unreadable are taken as zero, and the
  sidecar says all of that. The 30 m shape still decides WHERE within
  a cell; the satellite decides whether that month had snow there.

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
import math
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

from ..capture.exposure import REC709_LUMA
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
#: the water fallback for what it is. 4: satellite-seen snow whitened
#: the ground (a misreading of the shader names, withdrawn). 5: weather
#: snow composited the way weather_apply does it (key, band, linear
#: cos-slope ramp, snow_ALB by cov); the water fallback is any.png.
DRAPE_VERSION = 5
ROLES = ("valley", "scrub", "rock", "cliff", "snow")
#: DEM rows composited per step (bounds memory on an 8192-texel drape).
_CHUNK_ROWS = 256

LICENSE = "Local simulator-derived texture set"
ATTRIBUTION = "Ground textures and water colour: local simulator-derived data"
#: Snow-cover fraction at or above which a cell counts as "saw snow" for
#: the sidecar's summary (the blend itself is continuous).
SNOW_SEEN = 0.5
#: ITU-R BT.709 luma weights: the terrain shader's snow key is a dot of
#: the (linear) ground colour with u_material_snow_luma_coef, whose
#: value is a global the decompilation does not show; Rec.709 on the
#: 8-bit texel is this repository's stand-in for it.
_REC709 = np.array(REC709_LUMA, dtype=np.float32)
#: weather_apply's snow band: snow_w0 = smoothstep(L - a, L + a,
#: key + j * (2 * noise - 1)) with L = u_weather.z (a weather global),
#: a = u_snow_area.y, j = u_snow_area.w. The three are unread; a and j
#: are this repository's, and L is driven by the satellite cover as
#: L = (1 + a + j) * (1 - 2 * cover), which gives no weather snow at
#: zero cover and full coverage at full cover whatever the key.
WEATHER_SNOW_BAND = 0.25
WEATHER_SNOW_JITTER = 0.25
#: weather_apply's slope gate is LINEAR in cos(slope) between
#: u_snow_slope.x and .y (values unread): here cos 38 deg .. cos 30 deg,
#: the drape's own rock transition.
WEATHER_SNOW_COS_RAMP = (math.cos(math.radians(38.0)),
                         math.cos(math.radians(30.0)))
#: The dedicated snow albedo (bitmaps/world/weather/snow_ALB.png, RGBA:
#: alpha is the per-texel cover threshold the pass adds) and the noise
#: the jitter samples, each tiled at a ground size in metres. The
#: simulator's u_snow_scale_alb and u_snow_area.x are unread; these are
#: this repository's choices.
SNOW_ALBEDO_FILE = "snow_ALB.png"
SNOW_ALBEDO_METRES = 64.0
WEATHER_NOISE_FILE = "noise.png"
WEATHER_NOISE_METRES = 512.0


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
    the permanent snow but a north face above the line keeps a quarter).
    The returned dict then carries two extra maps that are NOT role
    weights (the roles still sum to 1): ``"snow_cover"`` (the cover, 0
    where unknown) and ``"snow_slope"`` (weather_apply's linear ramp in
    cos(slope), 0 on cliffs), the DEM-resolution inputs of the weather
    snow :func:`build_drape` composites per texel.
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
    extra = {}
    if snow_cover is not None:
        if snow_cover.shape != elevation_m.shape:
            raise ValueError(
                f"snow cover {snow_cover.shape} does not match the DEM "
                f"{elevation_m.shape}")
        known = np.isfinite(snow_cover)
        cover = np.where(known, snow_cover, 0.0)
        snow = np.where(known, snow * (0.25 + 0.75 * cover), snow)
        cos_low, cos_high = WEATHER_SNOW_COS_RAMP
        ramp = np.clip((np.cos(np.radians(slope)) - cos_low)
                       / (cos_high - cos_low), 0.0, 1.0)
        extra["snow_cover"] = cover.astype(np.float32)
        extra["snow_slope"] = (ramp * (1.0 - cliff)).astype(np.float32)
    weights = {
        "cliff": cliff,
        "rock": steep * (1.0 - cliff),
        "scrub": gentle * high * (1.0 - cliff),
        "valley": gentle * (1.0 - high) * (1.0 - cliff),
    }
    weights = {name: w * (1.0 - snow) for name, w in weights.items()}
    weights["snow"] = snow
    out = {name: w.astype(np.float32) for name, w in weights.items()}
    out.update(extra)
    return out


def _smoothstep_between(low: np.ndarray, high: np.ndarray,
                        value: np.ndarray) -> np.ndarray:
    t = np.clip((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def weather_snow_cov(rgb: np.ndarray, cover: np.ndarray, slope_ramp: np.ndarray,
                     noise: np.ndarray, albedo_alpha: np.ndarray) -> np.ndarray:
    """weather_apply's snow coverage per texel, 0..1:

    ``key = 2 * luma - 1`` (the terrain shader's luminance key, here
    Rec.709 of the composite), ``w0 = smoothstep(L - a, L + a, key +
    j * (2 * noise - 1))`` with ``L = (1 + a + j) * (1 - 2 * cover)``,
    ``coverage = w0 * slope_ramp``, ``cov = saturate(2 * coverage - 1 +
    albedo_alpha)``. The decal-modulation terms the pass adds on top
    (mod_k / mod_rgba, constants unread) are taken as zero, which
    reduces its blend to a plain mix by ``cov``."""
    a, j = WEATHER_SNOW_BAND, WEATHER_SNOW_JITTER
    key = 2.0 * (rgb @ _REC709) / 255.0 - 1.0
    level = (1.0 + a + j) * (1.0 - 2.0 * cover)
    w0 = _smoothstep_between(level - a, level + a,
                             key + j * (2.0 * noise - 1.0))
    coverage = w0 * slope_ramp
    return np.clip(2.0 * coverage - 1.0 + albedo_alpha, 0.0, 1.0)


def _load_weather(render_dir: Path, texel_size_m: float) -> Optional[Dict[str, Any]]:
    """The snow albedo (RGB 0..255 and alpha 0..1) and the noise (0..1)
    tiled to the drape's texel size, or None when the committed weather
    bitmaps are not on this checkout."""
    folder = Path(render_dir) / "bitmaps" / "world" / "weather"
    albedo_path = folder / SNOW_ALBEDO_FILE
    noise_path = folder / WEATHER_NOISE_FILE
    if not (albedo_path.is_file() and noise_path.is_file()):
        return None
    with Image.open(albedo_path) as im:
        px = max(2, round(SNOW_ALBEDO_METRES / texel_size_m))
        rgba = np.asarray(im.convert("RGBA").resize((px, px), Image.LANCZOS),
                          dtype=np.float32)
    with Image.open(noise_path) as im:
        px = max(2, round(WEATHER_NOISE_METRES / texel_size_m))
        noise = np.asarray(im.convert("L").resize((px, px), Image.LANCZOS),
                           dtype=np.float32) / 255.0
    return {"albedo_rgb": np.ascontiguousarray(rgba[:, :, :3]),
            "albedo_alpha": np.ascontiguousarray(rgba[:, :, 3] / 255.0),
            "noise": noise,
            "files": [str(albedo_path.relative_to(render_dir)),
                      str(noise_path.relative_to(render_dir))]}


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
    shader binds for that degree, create_water_shader), else the
    committed ``any.png`` beside the tiles (the candidate for the
    simulator's single global fallback texture), else the sky table's
    water strip (:data:`WATER_FALLBACK_NOTE`); (None, None) with none."""
    try:
        tiles = WaterTiles.load(render_dir)
    except XPlaneDataError:
        tiles = None
    if tiles is not None:
        if centre is not None:
            colour = tiles.colour(*centre)
            if colour is not None:
                return colour, ("per-tile water texture "
                                f"{tiles.path(*centre).relative_to(tiles.root)}")
        colour = tiles.fallback_colour()
        if colour is not None:
            return colour, (f"water/{tiles.FALLBACK_TILE} (the candidate for "
                            f"the simulator's global fallback texture "
                            f"REN_water_get_fallback_water_color, unverified)")
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
                and (previous.get("snow_cover") or {}).get("month") == month
                and previous.get("render_dir") == str(render_dir)):
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
                "rule": "permanent snow x (0.25 + 0.75 cover); weather snow "
                        "= cover on gentle ground, whitening the texture "
                        "underneath; unknown cells keep the height rule",
            })
            if not known.any():
                snow_cover = None
    weights = classify(baked.elevations(), baked.georeference.pixel_size_m,
                       snowline, snow_cover)
    weather = None
    if "snow_cover" in weights:
        weather = _load_weather(render_dir, grid.texel_size_m)
        if weather is None:
            snow_record["weather_snow"] = {
                "applied": False,
                "missing": f"{SNOW_ALBEDO_FILE} / {WEATHER_NOISE_FILE} under "
                           f"{render_dir / 'bitmaps' / 'world' / 'weather'}"}
    cov_sum = 0.0

    def upsampled(name: str, row0: int, rows: int, out_rows: int) -> np.ndarray:
        # One row of context each side so the bilinear upsample does
        # not seam at chunk boundaries.
        lo = max(row0 - 1, 0)
        hi = min(row0 + rows + 1, baked.height)
        piece = Image.fromarray(weights[name][lo:hi], mode="F").resize(
            (grid.width, (hi - lo) * k), Image.BILINEAR)
        return np.asarray(piece, dtype=np.float32)[
            (row0 - lo) * k:(row0 - lo) * k + out_rows]

    texture = np.empty((grid.height, grid.width, 3), dtype=np.uint8)
    for row0 in range(0, baked.height, _CHUNK_ROWS):
        rows = min(_CHUNK_ROWS, baked.height - row0)
        out_rows = rows * k
        block = np.zeros((out_rows, grid.width, 3), dtype=np.float32)
        for role in ROLES:
            block += upsampled(role, row0, rows, out_rows)[:, :, None] * _tiled(
                loaded["tiles"][role], row0 * k, out_rows, grid.width)
        if weather is not None:
            alpha = _tiled(weather["albedo_alpha"], row0 * k, out_rows, grid.width)
            cov = weather_snow_cov(
                block, upsampled("snow_cover", row0, rows, out_rows),
                upsampled("snow_slope", row0, rows, out_rows),
                _tiled(weather["noise"], row0 * k, out_rows, grid.width), alpha)
            albedo = _tiled(weather["albedo_rgb"], row0 * k, out_rows, grid.width)
            block = block + (albedo - block) * cov[:, :, None]
            cov_sum += float(cov.sum())
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
    if weather is not None:
        snow_record["weather_snow"] = {
            "applied": True,
            "mean_cov": round(cov_sum / float(grid.width * grid.height), 4),
            "mechanism": "weather_apply: key = 2 luma - 1; w0 = smoothstep("
                         "L - a, L + a, key + j (2 noise - 1)); coverage = "
                         "w0 * linear cos-slope ramp; cov = saturate(2 "
                         "coverage - 1 + snow.a); albedo = mix(albedo, "
                         "snow_ALB, cov) (decompiled from the committed "
                         "SPIR-V)",
            "key": "Rec.709 luma of the composite texel (the simulator's "
                   "u_material_snow_luma_coef is unread)",
            "level_source": "MODIS cover: L = (1 + a + j) (1 - 2 cover) "
                            "(this repository's mapping; the simulator's "
                            "L is the weather global u_weather.z)",
            "band_half_width": WEATHER_SNOW_BAND,
            "jitter": WEATHER_SNOW_JITTER,
            "slope_ramp_cos": [round(v, 4) for v in WEATHER_SNOW_COS_RAMP],
            "textures": weather["files"],
            "albedo_metres": SNOW_ALBEDO_METRES,
            "noise_metres": WEATHER_NOISE_METRES,
            "decal_modulation": "taken as 0 (mod_k / mod_rgba unread)",
            "assumed": ["band_half_width", "jitter", "slope_ramp_cos",
                        "albedo_metres", "noise_metres", "key coefficients",
                        "level_source"],
        }
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
        "render_dir": str(render_dir),
        "centre_lat_lon": list(centre) if centre else None,
        "snowline_m_approx": snowline,
        "season": ({"name": season.name, "index": season.index,
                    "blend": round(season.blend, 4), "mask": season.mask,
                    "value": round(season.value, 4), "basis": season.basis,
                    "evaluated_at": "bake centre",
                    "simulator": "total_season_for_location per terrain "
                                 "patch (first vertex) and per placement "
                                 "at DSF load; no body in the reports"}
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
