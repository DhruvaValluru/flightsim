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

Beside the composite the drape writes the MAPS the engine's terrain
material takes, so the GPU can do per pixel what the composite bakes at
the drape's texel size (M_TerrainImagery, scripts/ue_create_materials.py;
uncompiled here, Windows is the render platform):

* ``<bake>_xplane_roles.png`` (RGBA 8-bit): the valley, scrub, rock and
  cliff weights of the rule, upsampled from the DEM exactly as the
  composite is; snow is the remainder, ``saturate(1 - R - G - B - A)``,
  so the four channels never sum past 255;
* ``<bake>_xplane_snow.png`` (8-bit L): the weather snow LEVEL, the
  month's satellite cover and nothing else -- the material applies the
  band, the jitter, the slope ramp and the snow albedo itself; all zero
  without a month or a known cover;
* ``<bake>_xplane_water.png`` (8-bit L): 255 on the mapped water the
  composite paints, 0 elsewhere;
* ``<bake>_xplane_base.png`` (RGB 8-bit): the image the material's
  "Imagery" parameter should receive (``material.textures.imagery``):
  the composite's own per-texel role blend, the permanent snow role
  included, with each role's TILE replaced by its MEAN colour -- the
  per-channel mean of the 8-bit sRGB texels of the committed
  drape/<role>.png, taken from the tile at load (the same measurement
  scripts/ue_create_materials.py pins as TERRAIN_DETAIL_NEUTRAL, there
  in linear light; what is composited here is the sRGB mean, a few
  counts darker than that neutral encoded) -- the mapped water painted
  exactly as the composite paints it, and WITHOUT the weather-snow pass;

and a ``material`` block in the sidecar (:func:`material_block`) naming
those maps, the simulator's ground textures as the material's detail
albedos with their projected sizes, the weather bitmaps when committed,
and every scalar the material takes with its default. The two images
divide the work: the COMPOSITE (``texture.file``) carries the role
tiles and the luma-key weather snow and stays exactly what it was, the
fallback for a host or material without the block; the BASE image
carries neither, so a material fed it applies the detail and the
weather snow ONCE, from Roles / SnowCover, instead of over a composite
that already has them. Every scalar in that block but DetailMetres*
(the simulator's PROJECTED sizes, drape_textures.json) is this
repository's constant (the simulator's uniform values are in no
module). A role's detail normal is the one the extraction recorded
(``index[role]["normal"]``, relative to terrain/drape/, when its .ter
names a normal map); the committed index records none, so the drape
falls back to ``<role>_nrm_derived.png`` (``core/xplane/normals.py``),
and to the material's flat default when that is absent too.

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
                       SNOW_COVER_YEAR, WATER_FALLBACK_NOTE, WEATHER_BITMAPS,
                       SnowCover, WaterTiles, season_for, weather_bitmaps)

#: Bump when the classification or compositing changes, so a cached drape
#: from an older rule is rebuilt instead of reused. 2: MODIS snow cover
#: modulates the snow class; the per-tile water colour. 3: the sidecar
#: records the simulator-shaped season (index, blend, mask) and names
#: the water fallback for what it is. 4: satellite-seen snow whitened
#: the ground (a misreading of the shader names, withdrawn). 5: weather
#: snow composited the way weather_apply does it (key, band, linear
#: cos-slope ramp, snow_ALB by cov); the water fallback is any.png. 6:
#: the material maps (roles, snow level, water mask) written beside the
#: composite and the sidecar's "material" block. 7: the base image (the
#: role means, the water, no weather snow) the material's Imagery takes,
#: listed as material.textures.imagery. 8: a role without an extracted
#: normal takes the one derived from its texture (core/xplane/normals.py).
DRAPE_VERSION = 8
ROLES = ("valley", "scrub", "rock", "cliff", "snow")
#: The roles map's channels, R G B A in this order; snow is the remainder.
ROLE_CHANNELS = ROLES[:4]
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
SNOW_ALBEDO_FILE = WEATHER_BITMAPS["snow_albedo"]
SNOW_ALBEDO_METRES = 64.0
WEATHER_NOISE_FILE = WEATHER_BITMAPS["noise"]
WEATHER_NOISE_METRES = 512.0

#: The sidecar's "material" block: the contract between this writer, the
#: engine's FlightSimVisualScene (which sets every texture and scalar it
#: finds on the drape's dynamic material instance and records each as
#: applied or absent) and M_TerrainImagery (scripts/ue_create_materials.py).
#: Parameter NAMES are the contract; bump the version when a name or a
#: map's encoding changes, not for a new default value.
MATERIAL_VERSION = 1
#: The detail albedo's contribution to the macro colour, colour =
#: Imagery * lerp(1, detail / neutral, DetailStrength * fade), neutral =
#: the role texture's mean (TERRAIN_DETAIL_NEUTRAL in the script, the
#: linear-light mean; the base image composites the sRGB mean), and the
#: camera distances (metres) over which the detail fades out: the
#: simulator's decals are keyed by distance (km_key in the terrain
#: shader) with constants that are not readable, so both are this
#: repository's.
MATERIAL_DETAIL_STRENGTH = 0.6
MATERIAL_DETAIL_FADE_M = (3000.0, 12000.0)
#: Per-material roughness. The simulator's .ter files carry no roughness
#: the extractor reads (the terrain shader's per-material roughness is a
#: material-data uniform, OGL_terrain_shader_write_material_data, a name
#: only); these are this repository's values: rougher for vegetation,
#: smoother for rock, smoother again for snow, near-mirror for water.
MATERIAL_ROUGHNESS = {"valley": 0.85, "scrub": 0.8, "rock": 0.75,
                      "cliff": 0.7, "snow": 0.55, "water": 0.08}
#: Every scalar the material takes from the sidecar, in the block's order
#: (:func:`material_scalars`). "Wetness" and "NightLuminance" are the
#: material's too but are the SCENE's (the weather coupling, the night
#: plan) and deliberately not in the sidecar, so a drape never resets them.
MATERIAL_SCALAR_NAMES = (
    tuple(f"DetailMetres{role.capitalize()}" for role in ROLES)
    + ("SnowMetres", "NoiseMetres", "DetailStrength", "DetailFadeStartM",
       "DetailFadeEndM", "SnowSlopeLowCos", "SnowSlopeHighCos", "SnowBand")
    + tuple(f"Roughness{role.capitalize()}" for role in ROLES + ("water",)))
MATERIAL_SCENE_SCALARS = {
    "Wetness": "the render's weather coupling (ApplyWetness)",
    "NightLuminance": "the night-lights plan's level (M_TerrainImageryNight)",
}


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
    found = weather_bitmaps(render_dir)
    albedo_path, noise_path = found["snow_albedo"], found["noise"]
    if albedo_path is None or noise_path is None:
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
            "files": [str(albedo_path.relative_to(Path(render_dir).resolve())),
                      str(noise_path.relative_to(Path(render_dir).resolve()))]}


def _load_tiles(data_dir: Path, texel_size_m: float) -> Dict[str, Any]:
    """Each role's tile resized to the drape's texel size ("tiles"), its
    MEAN colour ("means": float32 RGB 0..255, the per-channel mean of the
    committed PNG's 8-bit sRGB texels, taken from the whole tile before
    the resize; what the base image composites) and the extraction's
    index."""
    drape_dir = data_dir / "terrain" / "drape"
    index_path = _require(drape_dir / "drape_textures.json")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    tiles, means = {}, {}
    for role in ROLES:
        if role not in index:
            raise XPlaneDataError(f"{index_path} has no {role!r} texture")
        entry = index[role]
        with Image.open(_require(drape_dir / entry["file"])) as im:
            rgb = im.convert("RGB")
            means[role] = np.asarray(rgb, dtype=np.float64).reshape(
                -1, 3).mean(axis=0).astype(np.float32)
            size = (max(2, round(entry["metres_x"] / texel_size_m)),
                    max(2, round(entry["metres_y"] / texel_size_m)))
            tiles[role] = np.asarray(rgb.resize(size, Image.LANCZOS),
                                     dtype=np.float32)
    return {"tiles": tiles, "means": means, "index": index}


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
    """The composite ("png"), the sidecar, the base image the material's
    Imagery takes ("base") and the three material maps ("roles", "snow",
    "water"), all beside the bake. Every one of them must be present for
    :func:`build_drape` to reuse a cached drape."""
    stem = Path(baked_path)
    return {"png": stem.with_name(stem.name + "_xplane_drape.png"),
            "sidecar": stem.with_name(stem.name + "_xplane_drape.json"),
            "base": stem.with_name(stem.name + "_xplane_base.png"),
            "roles": stem.with_name(stem.name + "_xplane_roles.png"),
            "snow": stem.with_name(stem.name + "_xplane_snow.png"),
            "water": stem.with_name(stem.name + "_xplane_water.png")}


#: The maps' keys in drape_paths -> the material block's texture names
#: ("imagery" is the base image, the material's Imagery), and each map's
#: PIL mode as written (the sidecar's "maps" records it).
_MAP_TEXTURES = {"base": "imagery", "roles": "roles", "snow": "snow_cover",
                 "water": "water_mask"}
_MAP_MODES = {"base": "RGB", "roles": "RGBA", "snow": "L", "water": "L"}


def detail_metres(entry: Dict[str, Any]) -> float:
    """The ground size the material tiles a role's detail albedo at: the
    SHORTER of the simulator's PROJECTED pair (drape_textures.json). The
    material tiles by this one scalar and restores the pair's aspect
    itself (TERRAIN_DETAIL_ASPECT, scripts/ue_create_materials.py); the
    shorter axis keeps the texel density the simulator gives that
    texture (scrub and cliff are 2:1 and 4:1; the composite tiles them
    at both sizes)."""
    return float(min(entry["metres_x"], entry["metres_y"]))


def material_scalars(index: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    """Every scalar of the material contract with its default, in
    :data:`MATERIAL_SCALAR_NAMES` order: the detail sizes from the
    extraction's index, the weather-snow constants the composite itself
    uses (so the two agree), the detail and roughness constants."""
    cos_low, cos_high = WEATHER_SNOW_COS_RAMP
    fade_start, fade_end = MATERIAL_DETAIL_FADE_M
    out: Dict[str, float] = {}
    for role in ROLES:
        out[f"DetailMetres{role.capitalize()}"] = detail_metres(index[role])
    out.update({
        "SnowMetres": SNOW_ALBEDO_METRES,
        "NoiseMetres": WEATHER_NOISE_METRES,
        "DetailStrength": MATERIAL_DETAIL_STRENGTH,
        "DetailFadeStartM": fade_start,
        "DetailFadeEndM": fade_end,
        "SnowSlopeLowCos": cos_low,
        "SnowSlopeHighCos": cos_high,
        "SnowBand": WEATHER_SNOW_BAND,
    })
    for role in ROLES + ("water",):
        out[f"Roughness{role.capitalize()}"] = MATERIAL_ROUGHNESS[role]
    assert tuple(out) == MATERIAL_SCALAR_NAMES
    return out



def _role_normal(drape_dir: Path, role: str, entry: Dict) -> Dict[str, object]:
    """``normal`` (absolute path or None) and ``normal_source`` for a role."""
    from .normals import SUFFIX as DERIVED_SUFFIX

    if entry.get("normal"):
        return {"normal": str((drape_dir / entry["normal"]).resolve()),
                "normal_source": "extracted"}
    derived = drape_dir / f"{role}{DERIVED_SUFFIX}"
    if derived.is_file():
        return {"normal": str(derived.resolve()),
                "normal_source": "derived from the albedo (core/xplane/normals.py)"}
    return {"normal": None, "normal_source": None}

def material_block(paths: Dict[str, Path], drape_dir: Path,
                   index: Dict[str, Dict[str, Any]],
                   render_dir: Path,
                   means: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """The sidecar's "material" object. Map files, the base image
    ("imagery") among them, are relative to the sidecar (they sit beside
    it); detail albedos, their normals and the weather bitmaps are
    absolute, the weather ones None when not on this checkout (the
    engine records them "absent" and renders without; never a failed
    render). ``means`` is each role's mean colour (:func:`_load_tiles`),
    recorded per role as the value the base image composited for it.
    """
    weather = weather_bitmaps(render_dir)
    detail = {}
    for role in ROLES:
        entry = index[role]
        detail[role] = {
            "file": str((drape_dir / entry["file"]).resolve()),
            "metres": detail_metres(entry),
            "projected_m": [float(entry["metres_x"]), float(entry["metres_y"])],
            # The mean of the tile's 8-bit sRGB texels: the base image's
            # colour for this role where its weight is 1.
            "mean_srgb": [round(float(v), 2) for v in means[role]],
            # The role's normal map: the extraction's when it recorded one
            # (index[role]["normal"], relative to terrain/drape/, from a
            # .ter that names a normal map), else the stand-in derived
            # from the texture (core/xplane/normals.py) when it is on
            # disk, else None and the material keeps its flat default.
            **_role_normal(drape_dir, role, entry),
        }
    return {
        "version": MATERIAL_VERSION,
        "textures": {
            **{_MAP_TEXTURES[key]: paths[key].name for key in _MAP_TEXTURES},
            "detail": detail,
            "snow_albedo": (str(weather["snow_albedo"])
                            if weather["snow_albedo"] else None),
            "snow_normal": (str(weather["snow_normal"])
                            if weather["snow_normal"] else None),
            "noise": str(weather["noise"]) if weather["noise"] else None,
        },
        "scalars": material_scalars(index),
        "imagery_encoding": "RGB 8-bit sRGB on the composite's grid: the "
                            "roles map's weights (snow the remainder) x "
                            "each role's mean colour (detail[role]."
                            "mean_srgb, the mean of the committed PNG's "
                            "8-bit sRGB texels; the script's "
                            "TERRAIN_DETAIL_NEUTRAL is the linear-light "
                            "mean of the same PNGs), the mapped water "
                            "painted as the composite paints it, no "
                            "weather snow: the material applies detail "
                            "and weather snow once, from Roles / SnowCover",
        "roles_encoding": "RGBA 8-bit: R G B A = valley, scrub, rock, cliff "
                          "weights x 255; snow = saturate(1 - R - G - B - "
                          "A); the four channels sum to at most 255",
        "snow_cover_encoding": "8-bit L: the month's MODIS cover x 255 (the "
                               "weather snow LEVEL; the material applies "
                               "band, jitter, slope ramp and snow albedo); "
                               "0 without a month or a known cover",
        "water_mask_encoding": "8-bit L: 255 on the mapped water the "
                               "composite paints, 0 elsewhere",
        "noise_encoding": "8-bit L (the committed noise.png): the jitter "
                          "the material adds to the snow level, tiled at "
                          "NoiseMetres",
        "scene_scalars": dict(MATERIAL_SCENE_SCALARS),
        "note": "every scalar but DetailMetres* (the simulator's PROJECTED "
                "sizes, drape_textures.json) is this repository's constant "
                "(the simulator's uniform values are in no module); the "
                "maps are the drape's slope/height rule, not land-class "
                "data; the composite (texture.file) carries the role tiles "
                "and the luma-key weather snow and is the fallback for a "
                "host or material without this block; the base image "
                "(textures.imagery) carries neither, so the material "
                "applies detail and weather snow once, from Roles / "
                "SnowCover; a detail normal is the one the extraction "
                "recorded (none in the committed index)",
    }


def build_drape(baked_path, data_dir: Optional[Path] = None,
                water_mask: Optional[WaterMask] = None,
                month: Optional[int] = None,
                render_dir: Optional[Path] = None) -> Path:
    """Write ``<bake>_xplane_drape.png`` + ``.json`` beside the bake,
    with the base image the material's Imagery takes
    (``_xplane_base.png``) and the three material maps
    (``_xplane_roles/snow/water.png``, :func:`drape_paths`), and return
    the sidecar path. A drape already built from this bake by this
    version of the rule, for this ``month`` (None = the height rule
    alone), with all its files present, is reused. Raises
    XPlaneDataError when the extracted textures are missing; a missing
    snow-cover or water-tile raster is recorded in the sidecar and the
    drape falls back to the extraction's own data."""
    data_dir = Path(data_dir) if data_dir else DATA_DIR
    render_dir = Path(render_dir) if render_dir else RENDER_DIR
    month = int(month) if month is not None else None
    baked_path = Path(baked_path)
    paths = drape_paths(baked_path)
    raster = baked_path.with_name(baked_path.name + ".r16")
    bake_sha = sha256_of(raster) if raster.is_file() else None
    if all(path.is_file() for path in paths.values()):
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
                        "= the cover as weather_apply's level (weather_snow "
                        "below; the material's snow map carries the cover "
                        "itself); unknown cells keep the height rule",
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
    # The base image: the same role blend as the composite, each role's
    # tile replaced by its mean colour, no weather snow (the material
    # applies detail and weather snow once, from Roles / SnowCover).
    base = np.empty((grid.height, grid.width, 3), dtype=np.uint8)
    # The material maps, on the composite's texel grid: the four role
    # weights (snow is the remainder) and the weather snow level.
    roles = np.empty((grid.height, grid.width, len(ROLE_CHANNELS)),
                     dtype=np.uint8)
    snow_level = np.zeros((grid.height, grid.width), dtype=np.uint8)
    for row0 in range(0, baked.height, _CHUNK_ROWS):
        rows = min(_CHUNK_ROWS, baked.height - row0)
        out_rows = rows * k
        block = np.zeros((out_rows, grid.width, 3), dtype=np.float32)
        base_block = np.zeros((out_rows, grid.width, 3), dtype=np.float32)
        stacked = np.zeros((out_rows, grid.width, len(ROLE_CHANNELS)),
                           dtype=np.float32)
        for role in ROLES:
            weight = upsampled(role, row0, rows, out_rows)
            block += weight[:, :, None] * _tiled(
                loaded["tiles"][role], row0 * k, out_rows, grid.width)
            base_block += weight[:, :, None] * loaded["means"][role]
            if role in ROLE_CHANNELS:
                stacked[:, :, ROLE_CHANNELS.index(role)] = weight
        base[row0 * k:row0 * k + out_rows] = np.clip(
            base_block + 0.5, 0.0, 255.0).astype(np.uint8)
        # Quantise the RUNNING sum, then difference it: each channel is
        # non-negative (the weights are, and bilinear keeps them so) and
        # the four sum to round(255 * total) <= 255 exactly, so the
        # material's snow remainder never goes negative from rounding.
        running = np.rint(np.clip(np.cumsum(stacked, axis=2), 0.0, 1.0)
                          * 255.0).astype(np.int16)
        roles[row0 * k:row0 * k + out_rows] = np.diff(
            running, axis=2, prepend=0).astype(np.uint8)
        if "snow_cover" in weights:
            snow_level[row0 * k:row0 * k + out_rows] = np.rint(np.clip(
                upsampled("snow_cover", row0, rows, out_rows), 0.0, 1.0)
                * 255.0).astype(np.uint8)
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
    water_map = np.zeros((grid.height, grid.width), dtype=np.uint8)
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
            base[wet] = colour                 # exactly as the composite
            water_map[wet] = 255

    Image.fromarray(texture).save(paths["png"])
    Image.fromarray(base).save(paths["base"])            # (h, w, 3) u8: RGB
    Image.fromarray(roles).save(paths["roles"])          # (h, w, 4) u8: RGBA
    Image.fromarray(snow_level).save(paths["snow"])      # (h, w) u8: L
    Image.fromarray(water_map).save(paths["water"])
    fractions = {role: round(float(weights[role].mean()), 4)
                 for role in ROLES}
    if weather is not None:
        snow_record["weather_snow"] = {
            "applied": True,
            "applied_to": "the composite (texture.file) only; the base "
                          "image (material.textures.imagery) carries no "
                          "weather snow, the material applies it from "
                          "SnowCover",
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
                                       if snow_cover is not None
                                       and float(np.max(snow_cover)) > 0.0
                                       else "")),
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
        # The material maps and the base image ("imagery"): the same grid
        # as "texture", one entry each with its file and hash; what they
        # encode is in "material".
        "maps": {
            name: {"file": paths[key].name, "sha256": None,
                   "mode": _MAP_MODES[key]}
            for key, name in _MAP_TEXTURES.items()
        },
        "material": material_block(paths, data_dir / "terrain" / "drape",
                                   loaded["index"], render_dir,
                                   loaded["means"]),
    }
    sidecar["texture"]["sha256"] = sha256_of(paths["png"])
    for key, name in _MAP_TEXTURES.items():
        sidecar["maps"][name]["sha256"] = sha256_of(paths[key])
    paths["sidecar"].write_text(json.dumps(sidecar, indent=2),
                                encoding="utf-8")
    return paths["sidecar"]
