"""The physical render assets and the logic reports, and what each governs.

Two committed trees arrived beside the extraction in ``assets/xplane/``:

* ``assets/physical_renders/Resources/`` mirrors the local simulator's own
  ``Resources/`` layout (bitmaps, shaders, effects, brdf_lookup), and
* ``assets/logic_reports/<report>/`` holds, per subsystem, the decompiled
  function listing (``functions.txt``: address, name) and code
  (``code.c``) that CONSUME those assets.

:data:`REPORTS` is the index tying the two together: which report's code
reads which asset folders, which terrain-drape roles that feeds, and the
named functions worth reading first. The two rasters the terrain drape
consumes are read here:

* ``bitmaps/Snow Cover/MOD10C1_M_SNOW_<yyyy>-<mm>.png``: NASA Earth
  Observations monthly snow cover (MODIS MOD10C1), a 3600x1800 palette
  PNG on a 0.1 degree equirectangular grid, row 0 at 90 N, column 0 at
  180 W. Palette index 0..254 is the snow-fraction ramp (0 = bare, 254 =
  full cover; the blue-to-white colours are presentation), index 255 is
  NO DATA (ocean, polar night) -- black like index 0, so the index, not
  the colour, is read.
* ``bitmaps/world/water/+LL+LLL/+ll+lll.png``: the per-1-degree water
  texture ``REN_degree::create_water_shader`` loads by exactly that path
  (``assets/logic_reports/terrain_ocean/code.c`` 19894-19926: a 10
  degree folder, floored, then the 1 degree tile) and binds as the
  ocean pass's base colour (``u_color`` of ``ocean_meta_data``). RGBA,
  256 or 512 px: the RGB is the location's water colour (a dark blue
  that varies by tile); the alpha (~191 everywhere) is NOT a mask but
  the depth attenuation exponent of that pass, disassembled from the
  committed SPIR-V: ``k = 0.1 * 10 ** (2 * alpha)`` per linearised
  depth unit and the water's opacity over the sea floor is ``1 -
  exp(-k * thickness)`` (alpha 191/255 gives k = 3.15;
  :meth:`WaterTiles.depth_attenuation`). Only the colour is used here.
  The ``any.png`` beside the tiles (64 x 64, one colour, the same
  alpha) is the candidate for the simulator's single global fallback
  texture (``REN_water_get_fallback_water_color``, no body):
  unverified, said so wherever it is used.

* ``bitmaps/Earth Orbit Textures/<+LL+LLL>{.dds,-ele.png,-nrm.png}``: the
  three 10-degree rasters the simulator's map terrain layer loads per
  tile (``Map::terrain_tile::terrain_tile``, terrain_ocean code.c
  7424-7565: name = lat then lon, each floored to 10 degrees). The
  ``-ele.png`` is an 8-bit height on an inverted 0..30,000 ft axis (sea
  level = texel 243, ~117 ft per texel; the axis is a least-squares fit
  over flat sites of known height, confirmed here on Paris, Lyon and
  Zermatt; summits read low because a texel is ~540 m across).
* ``bitmaps/world/weather/{snow,ice}_{ALB,NML,DCL}.png`` and ``noise.png``:
  the dedicated weather textures the ``weather_apply`` pass composites
  over the ground (disassembled from the committed SPIR-V; the README
  of the logic reports): the albedo's alpha is the per-texel cover
  threshold, the NML a tangent-space normal, the DCL a decal, the noise
  the jitter the pass adds to the snow key. :func:`weather_bitmaps`
  names them by role so the drape (its composite and its material
  block) and anything else binding them read ONE index; a missing one
  is None, never a stand-in.

Rules read out of the decompiled bodies and reproduced here (each names
its function and lines in ``assets/logic_reports/<report>/code.c``):

* :func:`floor10` / :func:`tile_name`: the simulator's tile naming
  (``return_latlon_str_dsf`` 39482-39686; ``create_water_shader``
  19871-19896), ``+30-130/+37-122``: bucket then tile, explicit sign.
* :func:`classify_terrain_def`: a DSF TERRAIN_DEF is water by the exact
  names ``water`` / ``terrain_Water`` (no ``.ter`` file: the water
  shader with the per-degree PNG and the ``lib/g10/decals/water.dcl``
  decals; ``has_bathymetry`` = the DSF declared a ``sea_level``
  raster), a photo-ortho quadrant by ``terrain_VirtualOrtho00..11``,
  otherwise a ``.ter`` file resolved per season and region; the token
  ``unknown token`` is replaced by ``lib/terrain/rock_gray.ter`` -- the
  simulator's fallback ground is ROCK (``DSF_AcceptTerrainDef``
  18536-19013 and its async twin).
* :data:`DSF_RASTER_NAMES`: the eleven rasters a DSF may carry
  (``DSF_AcceptRasterDef`` 21989-22086): the elevation DEM, a sea-level
  DEM, a soundscape and two rasters per season, spring/summer/fall/
  winter in that order.
* :func:`season_split`: a continuous per-location season value is
  floored to one of FOUR seasons with a fractional blend
  (``build_placement<REN_beach_def>`` 30893-30910: ``idx = clamp(floor(s),
  0, 3)``, ``blend = s - floor(s)``, mask ``1 << idx``). The value itself
  comes from ``REN_degree_dem_table::total_season_for_location``, whose
  body is NOT in the reports; :func:`season_for` is this repository's
  stand-in (meteorological seasons from the month, hemisphere-flipped),
  and says so.

Neither reader fetches anything: the files are committed, and a missing
one refuses by name (:class:`core.xplane.XPlaneDataError`) rather than
answering "no snow" or "no water colour".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from . import LOGIC_DIR, RENDER_DIR, XPlaneDataError, _require

SNOW_COVER_SIZE = (3600, 1800)
SNOW_COVER_NODATA = 255
SNOW_COVER_FULL = 254
#: The year the committed monthly set was captured for.
SNOW_COVER_YEAR = 2025
SNOW_COVER_DATASET = "NASA NEO MOD10C1_M_SNOW (MODIS/Terra monthly snow cover)"
SNOW_COVER_ATTRIBUTION = ("Snow cover: NASA Earth Observations, MODIS/Terra "
                          "MOD10C1 monthly snow cover (NSIDC), via the local "
                          "simulator's Snow Cover bitmaps")
#: Points sampled across the bake per axis before the bilinear upsample:
#: the source is a 10 km grid, so sampling finer than this only costs.
_SNOW_SAMPLE_MAX = 256


@dataclass(frozen=True)
class Report:
    """One logic report and the assets its code consumes."""

    name: str
    governs: str
    #: Folders/files under assets/physical_renders/Resources/ this
    #: report's code reads; empty when it is code only.
    assets: Tuple[str, ...]
    #: Terrain-drape roles (core.xplane.drape.ROLES plus "water") that
    #: those assets feed, directly or through assets/xplane/.
    drape_roles: Tuple[str, ...]
    #: Functions in functions.txt worth reading first.
    key_functions: Tuple[str, ...]
    #: Python consumers of what this report governs.
    consumers: Tuple[str, ...]
    #: How the report was cut from the binary: name-matched dumps carry
    #: unrelated hits (the lighting dump matched "flight" on "light").
    caveat: str = ""

    @property
    def functions_path(self) -> Path:
        return LOGIC_DIR / self.name / "functions.txt"

    @property
    def code_path(self) -> Path:
        return LOGIC_DIR / self.name / "code.c"


REPORTS: Dict[str, Report] = {
    "terrain_ocean": Report(
        name="terrain_ocean",
        governs="DSF terrain loading, the terrain shader, the water shader "
                "and beach placement; the per-location season table",
        assets=("bitmaps/world/water", "bitmaps/Snow Cover",
                "bitmaps/Earth Orbit Textures", "bitmaps/earth1.dds",
                "bitmaps/earth1-nrm.png", "bitmaps/earth2.dds",
                "bitmaps/earth2-nrm.png"),
        drape_roles=("valley", "scrub", "rock", "cliff", "snow", "water"),
        key_functions=("REN_degree::create_water_shader",
                       "DSF_AcceptTerrainDef", "DSF_AcceptRasterDef",
                       "return_latlon_str_dsf",
                       "REN_degree_loadtable_loader::build_placement<REN_beach_def",
                       "Map::terrain_tile::terrain_tile",
                       "sim_objects::is_water",
                       "sim_objects::xyz_if_open_ocean",
                       "ATCUtilsGetTerrainAltForPoint",
                       "OGL_build_water_mixdown_graph",
                       "REN_setup_terrain_shading",
                       "dsf_fat_season::dsf_fat_season",
                       "OGL_terrain_grid_calculate_lod_bias",
                       "flt_class::terrain_ele_cg",
                       "flt_class::drag_point_in_water"),
        consumers=("core.xplane.drape", "core.xplane.physical.SnowCover",
                   "core.xplane.physical.WaterTiles",
                   "core.xplane.physical.EarthOrbitTiles",
                   "core.xplane.physical.tile_name",
                   "core.xplane.physical.classify_terrain_def",
                   "core.xplane.physical.season_for",
                   "webapp.runs.plan_water_surface"),
        caveat="400 bodies: the DSF loader, the water shader's CPU side, "
               "the 2D map terrain layer and the DEM lookups are decompiled; "
               "io_read_terrain (the .ter parser, i.e. the land-class -> "
               "texture mapping), REN_water_get_fallback_water_color, "
               "DSF_LocateResourcePrimary and total_season_for_location are "
               "names only. ATC terrain-warning and water-rudder dataref "
               "accessors matched the name filter and are not render logic"),
    "lighting": Report(
        name="lighting",
        governs="sky-colour and ambient lookups, HDR and exposure fusion, "
                "ground and runway lights",
        assets=("brdf_lookup", "bitmaps/world/lites", "bitmaps/world/moon.dds",
                "bitmaps/world/moon_NML.png", "bitmaps/world/moon_NML.ktx2"),
        drape_roles=("water",),
        key_functions=("OGL_build_sky_ambient_graph",
                       "OGL_build_sky_view_graph",
                       "OGL_build_exposure_fusion_graph",
                       "OBJ_transform_ground_lights", "plot_init_lights_v11",
                       "OGL_hdr_init"),
        consumers=("core.xplane.sky_lighting", "core.xplane.drape.water_colour",
                   "webapp.runs.xplane_lighting_flags"),
        caveat="NO lighting logic is decompiled in THIS report: its three "
               "non-accessor bodies are the loading screen "
               "(plot_init_lights_v11, MACIBM_push_v11_init_lights_screen) "
               "and a flight_spec copy constructor; the sky/ambient/"
               "exposure/ground-light functions it lists (compute_sky_"
               "ambient, OGL_build_sky_*, sky_stat::get_for_now, "
               "get_sun_position, tonemap_*, OBJ_lights_*) are names only. "
               "Two relatives DO have bodies elsewhere: scattering_state::"
               "render_atmosphere_sky in the physics report (binds the sky "
               "draw's inputs, no table lookup) and the exposure-fusion "
               "pass in render_quality. The sky_colors_*.png tables and "
               "lights.txt this code reads are committed once, under "
               "assets/xplane/lighting/; the name filter also matched "
               "'flight' and libpng/OpenSSL header helpers"),
    "render_quality": Report(
        name="render_quality",
        governs="terrain shader setup, weather decals (snow/ice/rain on "
                "surfaces), clouds, volumetric fog, FSR scaling, overlays",
        assets=("shaders", "effects", "bitmaps/world/clouds",
                "bitmaps/world/weather", "bitmaps/world/overlays",
                "bitmaps/world/maps"),
        drape_roles=("snow",),
        key_functions=("OGL_terrain_shader_setup",
                       "OGL_terrain_shader_write_material_data",
                       "OBJ_command_builder::set_texture_weather",
                       "OBJ_command_builder::set_texture_weather_decal",
                       "REN_degree_dem_table::total_season_for_location",
                       "REN_do_water_per_frame", "rain_effect_init_shaders"),
        consumers=("core.xplane.drape (snow role; the material block's "
                   "snow albedo / normal / noise paths)",
                   "core.xplane.physical.weather_bitmaps",
                   "core.scene.precipitation", "core.scene.weather_visuals"),
        caveat="the decompiled bodies are the HDR/bloom constant block, "
               "exposure fusion (EV100 multiplier, Rec.709 luma), the FSR "
               "scale table and the rain shaders; OGL_terrain_shader_* and "
               "total_season_for_location are names only. The shaders "
               "folder is the compiled set; its SPIR-V archives keep their "
               "debug names and were disassembled for the GPU side: the "
               "terrain shader mixes a seasonal texture per layer by "
               "u_imm_a_season.x, writes a luminance snow KEY "
               "(u_material_snow_luma_coef) into the G-buffer, and adds a "
               "night texture by a night level; weather_apply thresholds "
               "that key against the global snow level u_weather.z with "
               "noise jitter, ramps it linearly in cos(slope) between "
               "u_snow_slope.x/.y and composites snow_ALB/NML/DCL by "
               "cov = saturate(2 coverage - 1 + alb.a). No shader source "
               "is committed and no uniform VALUE is in any module"),
    "physics": Report(
        name="physics",
        governs="atmosphere and fog parameters, rain-on-surface forces, "
                "ground contact; no render assets",
        assets=(),
        drape_roles=(),
        key_functions=("atmo_params::set_fog_params",
                       "atmo_params::set_turbidity",
                       "scattering_state::render_atmosphere_sky",
                       "OGL_gbuffer_init_atmospheric_model",
                       "wxr_api::get_cloud_properties_for_str",
                       "rain_surface::write_force_and_ubo_data"),
        consumers=("core.environment", "core.terrain.contact"),
        caveat="the name filter matched G1000/GNS430 page classes and "
               "atmospheric-conditions UI; the atmosphere functions above "
               "are the physics-relevant part. Decoded: fog extinction is "
               "Koschmieder, k = -ln(threshold)/visibility * scale "
               "(atmo_params::set_fog_params 5227-5236); Mie extinction is "
               "linear in (turbidity - 1) with an albedo split "
               "(set_turbidity 5174-5207); tire contact takes the MAX of "
               "vertical rays over the tire footprint, surface type from the "
               "centre ray (handle_contact_tire 15457-15637); the surface "
               "class -> friction table (yter_class::surface_ret_fric_cos) "
               "has no body and is not even listed"),
}


def logic_functions(report: str, pattern: Optional[str] = None
                    ) -> List[Tuple[str, str]]:
    """(address, name) rows of a report's functions.txt, optionally only
    those whose name contains ``pattern`` (case-insensitive)."""
    if report not in REPORTS:
        raise XPlaneDataError(
            f"unknown logic report {report!r}; committed: {sorted(REPORTS)}")
    path = _require(REPORTS[report].functions_path)
    needle = pattern.lower() if pattern else None
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("  ", 1)
            if len(parts) != 2:
                continue
            address, name = parts[0].strip(), parts[1].strip()
            if needle is None or needle in name.lower():
                rows.append((address, name))
    return rows


def catalogue(render_dir: Optional[Path] = None) -> Dict[str, Dict]:
    """The index as plain data, with whether each asset path is present
    on this checkout (the trees are committed; absence is a broken
    checkout, not a fetch to make)."""
    render_dir = Path(render_dir) if render_dir else RENDER_DIR
    out = {}
    for name, report in REPORTS.items():
        out[name] = {
            "governs": report.governs,
            "functions": str(report.functions_path.relative_to(LOGIC_DIR.parent)),
            "code": str(report.code_path.relative_to(LOGIC_DIR.parent)),
            "assets": {rel: (render_dir / rel).exists()
                       for rel in report.assets},
            "drape_roles": list(report.drape_roles),
            "key_functions": list(report.key_functions),
            "consumers": list(report.consumers),
            "caveat": report.caveat,
        }
    return out


# -- snow cover ------------------------------------------------------------

class SnowCover:
    """One month of MODIS snow cover as a fraction 0..1, NaN where unknown."""

    def __init__(self, index: np.ndarray, month: int, year: int,
                 source: Path):
        self.index = index
        self.month = month
        self.year = year
        self.source = source

    @classmethod
    def load(cls, month: int, render_dir: Optional[Path] = None,
             year: int = SNOW_COVER_YEAR) -> "SnowCover":
        if not 1 <= int(month) <= 12:
            raise XPlaneDataError(f"snow cover month {month!r} is not 1..12")
        render_dir = Path(render_dir) if render_dir else RENDER_DIR
        path = _require(render_dir / "bitmaps" / "Snow Cover"
                        / f"MOD10C1_M_SNOW_{year}-{int(month):02d}.png")
        with Image.open(path) as im:
            if im.mode != "P" or im.size != SNOW_COVER_SIZE:
                raise XPlaneDataError(
                    f"{path} is {im.mode} {im.size}; the reader decodes the "
                    f"NEO palette layout only ({SNOW_COVER_SIZE}, mode P)")
            index = np.asarray(im, dtype=np.uint8).copy()
        return cls(index, int(month), year, path)

    def sample(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Snow fraction at each (lat, lon), nearest cell; NaN = no data."""
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        rows = np.clip(((90.0 - lats) * 10.0).astype(int), 0,
                       SNOW_COVER_SIZE[1] - 1)
        cols = np.clip(((lons + 180.0) % 360.0 * 10.0).astype(int), 0,
                       SNOW_COVER_SIZE[0] - 1)
        raw = self.index[rows, cols]
        out = raw.astype(np.float32) / SNOW_COVER_FULL
        out[raw == SNOW_COVER_NODATA] = np.nan
        return out

    def fraction(self, lat: float, lon: float) -> Optional[float]:
        value = float(self.sample(np.array([lat]), np.array([lon]))[0])
        return None if math.isnan(value) else value

    def rasterize_projected(self, crs: str, origin_x_m: float,
                            origin_y_m: float, pixel_size_m: float,
                            width: int, height: int) -> np.ndarray:
        """Snow fraction on a projected north-up grid (a bake's frame),
        float32 ``(height, width)``, NaN where the source has no data.

        Sampled on at most 256 points per axis (the source is 10 km) and
        bilinearly upsampled; the no-data mask is upsampled the same way
        and anything touched by no-data stays NaN.
        """
        from pyproj import Transformer

        inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        nx = min(width, _SNOW_SAMPLE_MAX)
        ny = min(height, _SNOW_SAMPLE_MAX)
        xs = origin_x_m + (np.arange(nx) + 0.5) * (width * pixel_size_m / nx)
        ys = origin_y_m - (np.arange(ny) + 0.5) * (height * pixel_size_m / ny)
        gx, gy = np.meshgrid(xs, ys)
        lons, lats = inverse.transform(gx.ravel(), gy.ravel())
        lons = np.asarray(lons)
        lats = np.asarray(lats)
        if not (np.isfinite(lons).all() and np.isfinite(lats).all()):
            return np.full((height, width), np.nan, dtype=np.float32)
        coarse = self.sample(lats, lons).reshape(ny, nx)
        known = np.isfinite(coarse)
        filled = np.where(known, coarse, 0.0).astype(np.float32)
        if (nx, ny) == (width, height):
            fine, fine_known = filled, known.astype(np.float32)
        else:
            fine = np.asarray(Image.fromarray(filled).resize(
                (width, height), Image.BILINEAR), dtype=np.float32)
            fine_known = np.asarray(Image.fromarray(
                known.astype(np.float32)).resize(
                    (width, height), Image.BILINEAR), dtype=np.float32)
        fine = fine.copy()
        fine[fine_known < 0.999] = np.nan
        return fine


# -- the simulator's tile naming -------------------------------------------

def floor10(value: int) -> int:
    """An integer degree floored to its 10 degree bucket the way the
    simulator does it: ``(v/10)*10`` for v > 0, ``-(((9 - v)/10)*10)``
    otherwise, C integer division (``REN_degree::create_water_shader``,
    terrain_ocean code.c 19871-19892; ``return_latlon_str_dsf`` 39482-
    39490 writes the same bucket as ``((v+90)/10)*10-90``). Both equal
    ``floor(v / 10) * 10``; kept in the simulator's form so the two
    readings can be compared."""
    value = int(value)
    if value > 0:
        return (value // 10) * 10
    return -(((9 - value) // 10) * 10)


def tile_name(lat: float, lon: float, suffix: str = ".dsf") -> str:
    """``+30-130/+37-122<suffix>``: the simulator's path fragment for the
    1 degree tile holding a point (``return_latlon_str_dsf``, terrain_
    ocean code.c 39482-39686): the 10 degree bucket folder then the tile,
    every number with an explicit sign ('+' for zero), two latitude and
    three longitude digits, zero padded."""
    lat_i, lon_i = math.floor(lat), math.floor(lon)
    return (f"{floor10(lat_i):+03d}{floor10(lon_i):+04d}/"
            f"{lat_i:+03d}{lon_i:+04d}{suffix}")


# -- water tiles -----------------------------------------------------------

#: The simulator swaps a missing or empty water tile for ONE global
#: fallback texture, ``REN_water_get_fallback_water_color()`` (create_
#: water_shader 19931-19959), whose body is not in the reports. The
#: committed ``bitmaps/world/water/any.png`` is the candidate for it
#: (:meth:`WaterTiles.fallback_colour`); without the render assets the
#: drape falls back to the sky table's water strip, and either way the
#: sidecar says what stood in.
WATER_FALLBACK_NOTE = ("the simulator's no-tile fallback is a single global "
                       "texture, REN_water_get_fallback_water_color(), not "
                       "decompiled; water/any.png is its unverified "
                       "candidate, the sky table's water strip the last "
                       "resort")


def water_tile_relpath(lat: float, lon: float) -> Path:
    """``+LL+LLL/+ll+lll.png`` for a point, by the simulator's own formula
    (``REN_degree::create_water_shader``): the 1 degree tile inside its
    10 degree folder, both floored (:func:`tile_name`)."""
    return Path(tile_name(lat, lon, ".png"))


class WaterTiles:
    """The committed ``bitmaps/world/water`` tree: per-tile water colour,
    and the one-colour ``any.png`` beside the tiles."""

    #: The 64 x 64 single-colour PNG beside the tiles: the candidate for
    #: the simulator's global fallback texture (unverified: no report
    #: names the file).
    FALLBACK_TILE = "any.png"

    def __init__(self, root: Path):
        self.root = root

    def fallback_colour(self) -> Optional[Tuple[int, int, int]]:
        """The mean RGB of ``any.png`` as 8-bit sRGB, or None without it."""
        path = self.root / self.FALLBACK_TILE
        if not path.is_file():
            return None
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"), dtype=np.float64)
        return tuple(int(round(v)) for v in rgb.reshape(-1, 3).mean(axis=0))

    @staticmethod
    def depth_attenuation(alpha_8bit: int) -> float:
        """The ocean pass's depth attenuation from a tile's alpha:
        ``k = 0.1 * 10 ** (2 * alpha)``, alpha as 0..1; the water's
        opacity over the sea floor is ``1 - exp(-k * thickness)``
        (``ocean_meta_data``, disassembled from the committed SPIR-V;
        the thickness unit is the pass's linearised depth)."""
        return 0.1 * 10.0 ** (2.0 * float(alpha_8bit) / 255.0)

    @classmethod
    def load(cls, render_dir: Optional[Path] = None) -> "WaterTiles":
        render_dir = Path(render_dir) if render_dir else RENDER_DIR
        root = render_dir / "bitmaps" / "world" / "water"
        if not root.is_dir():
            raise XPlaneDataError(
                f"{root} not found; the physical render assets are committed "
                f"under assets/physical_renders/ -- this checkout lacks them")
        return cls(root)

    def path(self, lat: float, lon: float) -> Optional[Path]:
        candidate = self.root / water_tile_relpath(lat, lon)
        return candidate if candidate.is_file() else None

    def covers(self, lat: float, lon: float) -> bool:
        return self.path(lat, lon) is not None

    def colour(self, lat: float, lon: float
               ) -> Optional[Tuple[int, int, int]]:
        """The tile's mean RGB as 8-bit sRGB, or None without a tile."""
        path = self.path(lat, lon)
        if path is None:
            return None
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"), dtype=np.float64)
        mean = rgb.reshape(-1, 3).mean(axis=0)
        return tuple(int(round(v)) for v in mean)

    def tile_count(self) -> int:
        return sum(1 for _ in self.root.glob("*/*.png"))


# -- weather bitmaps --------------------------------------------------------

#: ``bitmaps/world/weather``: the textures ``weather_apply`` composites
#: over the ground, by role. The file names are the committed tree's own
#: (the pass binds them through OBJ_command_builder::set_texture_weather
#: (_decal), a name only in render_quality, so WHICH uniform takes which
#: file is read from the SPIR-V debug names, not from a body).
WEATHER_BITMAP_DIR = Path("bitmaps") / "world" / "weather"
WEATHER_BITMAPS: Dict[str, str] = {
    "snow_albedo": "snow_ALB.png",     # RGBA: alpha = per-texel cover threshold
    "snow_normal": "snow_NML.png",     # tangent-space normal
    "snow_decal": "snow_DCL.png",
    "ice_albedo": "ice_ALB.png",
    "ice_normal": "ice_NML.png",
    "ice_decal": "ice_DCL.png",
    "noise": "noise.png",              # L: the snow key's jitter
}


def weather_bitmaps(render_dir: Optional[Path] = None
                    ) -> Dict[str, Optional[Path]]:
    """Each weather bitmap's absolute path under the render assets, by
    the role names of :data:`WEATHER_BITMAPS`, None where the file is not
    on this checkout. No refusal here: the drape composites without them
    and records the absence, and the material binds what it finds."""
    render_dir = Path(render_dir) if render_dir else RENDER_DIR
    folder = render_dir / WEATHER_BITMAP_DIR
    out: Dict[str, Optional[Path]] = {}
    for role, name in WEATHER_BITMAPS.items():
        candidate = folder / name
        out[role] = candidate.resolve() if candidate.is_file() else None
    return out


# -- Earth Orbit Textures --------------------------------------------------

#: The three rasters per 10 degree tile (``Map::terrain_tile::terrain_tile``
#: loads three suffixes it hides from the decompiler; the committed folder
#: is the ground truth for them).
EARTH_ORBIT_SUFFIXES = {"albedo": ".dds", "elevation": "-ele.png",
                        "normal": "-nrm.png"}
#: The -ele.png axis: value = 255 * (1 - (ele_ft + OFFSET) / RANGE). A
#: least-squares fit over flat sites of known height (sea level = 243,
#: ~117 ft per texel); the two constants the map shader uses
#: (DAT_025625d0 / DAT_02562580, ``Map::terrain_layer_desktop::draw``
#: 8716-8717) are not readable, so these are the FIT, stated as such.
ELE_PNG_SEA_LEVEL_TEXEL = 243
ELE_PNG_RANGE_FT = 30000.0
ELE_PNG_OFFSET_FT = 1412.0
ELE_PNG_TILE_DEG = 10.0
_FT_TO_M = 0.3048


def earth_orbit_tile_relpath(lat: float, lon: float) -> str:
    """``+40-130``: the 10 degree Earth Orbit tile name for a point, lat
    then lon, each floored to 10 (terrain_ocean code.c 7424-7432)."""
    return f"{floor10(math.floor(lat)):+03d}{floor10(math.floor(lon)):+04d}"


def ele_png_to_metres(texel: int) -> float:
    """Decode one -ele.png texel to metres by the fitted axis."""
    feet = (1.0 - float(texel) / 255.0) * ELE_PNG_RANGE_FT - ELE_PNG_OFFSET_FT
    return feet * _FT_TO_M


class EarthOrbitTiles:
    """The committed ``bitmaps/Earth Orbit Textures`` tree: a coarse
    (~540 m per texel) height, normal and albedo per 10 degree tile."""

    def __init__(self, root: Path):
        self.root = root

    @classmethod
    def load(cls, render_dir: Optional[Path] = None) -> "EarthOrbitTiles":
        render_dir = Path(render_dir) if render_dir else RENDER_DIR
        root = render_dir / "bitmaps" / "Earth Orbit Textures"
        if not root.is_dir():
            raise XPlaneDataError(
                f"{root} not found; the physical render assets are committed "
                f"under assets/physical_renders/ -- this checkout lacks them")
        return cls(root)

    def paths(self, lat: float, lon: float) -> Dict[str, Optional[Path]]:
        """Each raster's path for the tile under a point, None where the
        file is absent (only five tiles are committed)."""
        stem = self.root / earth_orbit_tile_relpath(lat, lon)
        out = {}
        for role, suffix in EARTH_ORBIT_SUFFIXES.items():
            candidate = stem.with_name(stem.name + suffix)
            out[role] = candidate if candidate.is_file() else None
        return out

    def covers(self, lat: float, lon: float) -> bool:
        return self.paths(lat, lon)["elevation"] is not None

    def elevation_m(self, lat: float, lon: float) -> Optional[float]:
        """The decoded height under a point, or None without the tile.
        Coarse: one texel is ~540 m across and ~36 m in height, and a
        summit reads low; for anything finer use the GLO-30 bake."""
        path = self.paths(lat, lon)["elevation"]
        if path is None:
            return None
        lat0 = floor10(math.floor(lat))
        lon0 = floor10(math.floor(lon))
        with Image.open(path) as im:
            grey = im.convert("L")
            width, height = grey.size
            row = int((lat0 + ELE_PNG_TILE_DEG - lat) / ELE_PNG_TILE_DEG * height)
            col = int((lon - lon0) / ELE_PNG_TILE_DEG * width)
            row = min(max(row, 0), height - 1)
            col = min(max(col, 0), width - 1)
            texel = grey.getpixel((col, row))
        return ele_png_to_metres(int(texel))

    def tile_count(self) -> int:
        return sum(1 for _ in self.root.glob("*-ele.png"))


# -- DSF terrain definitions and rasters ------------------------------------

#: ``DSF_AcceptTerrainDef`` (terrain_ocean code.c 18536-19013; the sync
#: twin 19187-19668): exact, case-sensitive names, compared on the raw
#: token before path normalisation.
TERRAIN_DEF_WATER_NAMES = ("water", "terrain_Water")
TERRAIN_DEF_ORTHO_NAMES = tuple(f"terrain_VirtualOrtho{q}"
                                for q in ("00", "01", "10", "11"))
TERRAIN_DEF_UNKNOWN_TOKEN = "unknown token"
#: The simulator's fallback ground for an unresolvable definition: rock.
TERRAIN_DEF_FALLBACK = "lib/terrain/rock_gray.ter"
TERRAIN_DEF_FALLBACK_ROLE = "rock"
#: The required suffix is a 4-character literal Ghidra did not dump; the
#: fatal message ("is not a legal terrain file") makes it ".ter".
TERRAIN_DEF_SUFFIX = ".ter"


def classify_terrain_def(token: str) -> Tuple[str, str]:
    """(kind, resolved name) of a DSF TERRAIN_DEF token the way the
    loader classifies it: ``water`` (no texture file at all: the water
    shader), ``virtual_ortho`` (photo-textured; the quadrant digits
    change nothing), or ``ter`` (a terrain definition file). Any other
    token is refused by name, as the loader aborts the tile."""
    token = str(token)
    name = TERRAIN_DEF_FALLBACK if token == TERRAIN_DEF_UNKNOWN_TOKEN else token
    if token in TERRAIN_DEF_WATER_NAMES:
        return "water", name
    if token in TERRAIN_DEF_ORTHO_NAMES:
        return "virtual_ortho", name
    if len(name) >= 4 and name.endswith(TERRAIN_DEF_SUFFIX):
        return "ter", name
    raise XPlaneDataError(
        f"terrain definition {token!r} is not a legal terrain file "
        f"(DSF_AcceptTerrainDef: water, terrain_VirtualOrtho00..11 or *.ter)")


#: ``DSF_AcceptRasterDef`` (terrain_ocean code.c 21989-22086): the eleven
#: raster names a DSF may declare, in the loader's own order. Two per
#: season; what the seasonal rasters encode is not visible.
DSF_RASTER_NAMES = ("elevation", "sea_level", "soundscape",
                    "spr1", "spr2", "sum1", "sum2", "fal1", "fal2",
                    "win1", "win2")


# -- seasons ----------------------------------------------------------------

#: Four seasons, in the DSF raster order (spr, sum, fal, win).
SEASONS = ("spring", "summer", "fall", "winter")


@dataclass(frozen=True)
class Season:
    """A continuous season value split the simulator's way."""

    value: float
    index: int
    blend: float
    mask: int
    name: str
    basis: str


def season_split(value: float, basis: str = "stated") -> Season:
    """``build_placement<REN_beach_def>`` (terrain_ocean code.c 30893-
    30910): ``idx = clamp(floor(s), 0, 3)``, ``blend = s - floor(s)``,
    one-hot ``mask = 1 << idx``. The season an art asset is loaded for
    is fixed at load time (``dsf_season`` is a constructor argument on a
    path-keyed cache; UTL_art_asset_vram::load_sync 16077-16163)."""
    value = float(value)
    if not math.isfinite(value):
        raise XPlaneDataError(f"season value {value!r} is not finite")
    floored = math.floor(value)
    index = min(max(floored, 0), 3)
    return Season(value=value, index=index, blend=value - floored,
                  mask=1 << index, name=SEASONS[index], basis=basis)


def season_for(month: int, lat: float) -> Season:
    """This repository's stand-in for ``REN_degree_dem_table::
    total_season_for_location`` (a name only in the reports): the
    meteorological season of a calendar month, hemisphere-flipped, as
    a continuous value 0..4 -- March is spring 0.0, June summer 1.0,
    September fall 2.0, December winter 3.0, February winter + 2/3
    (south of the equator shifted by six months) -- then split the
    simulator's way. The basis says it is a month rule, not the
    simulator's per-location raster."""
    month = int(month)
    if not 1 <= month <= 12:
        raise XPlaneDataError(f"season month {month!r} is not 1..12")
    start = 3 if float(lat) >= 0.0 else 9          # the hemisphere's March
    value = ((month - start) % 12) / 3.0
    hemisphere = "northern" if float(lat) >= 0.0 else "southern"
    return season_split(value, basis=(
        f"meteorological season of month {month:02d}, {hemisphere} "
        f"hemisphere (this repository's rule; the simulator's "
        f"total_season_for_location has no decompiled body)"))
