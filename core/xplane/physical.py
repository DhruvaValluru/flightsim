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
  (``assets/logic_reports/terrain_ocean/code.c``: a 10 degree folder,
  floored, then the 1 degree tile). RGBA, 256 or 512 px: the RGB is the
  location's water colour (a dark blue that varies by tile), the alpha
  sits near 191 everywhere and is NOT a water mask. What the water
  shader does with the alpha is not decoded here; only the colour is
  used, and the sidecar says so.

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
                       "REN_setup_terrain_shading",
                       "OGL_build_water_mixdown_graph",
                       "DSF_AcceptTerrainDef",
                       "dsf_fat_season::dsf_fat_season",
                       "OGL_terrain_grid_calculate_lod_bias",
                       "flt_class::terrain_ele_cg",
                       "flt_class::drag_point_in_water"),
        consumers=("core.xplane.drape", "core.xplane.physical.SnowCover",
                   "core.xplane.physical.WaterTiles",
                   "webapp.runs.plan_water_surface"),
        caveat="ATC terrain-warning and water-rudder dataref accessors "
               "matched the name filter and are not render logic"),
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
        caveat="the sky_colors_*.png tables and lights.txt this code reads "
               "are committed once, under assets/xplane/lighting/ (the "
               "extractor's output), not duplicated here; the name filter "
               "also matched 'flight' and libpng/OpenSSL header helpers"),
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
        consumers=("core.xplane.drape (snow role)",
                   "core.scene.precipitation", "core.scene.weather_visuals"),
        caveat="the shaders folder is the compiled set (spv, msl, xsv "
               "mappings); no shader source is committed"),
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
               "are the physics-relevant part"),
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


# -- water tiles -----------------------------------------------------------

def water_tile_relpath(lat: float, lon: float) -> Path:
    """``+LL+LLL/+ll+lll.png`` for a point, by the simulator's own formula
    (``REN_degree::create_water_shader``): the 1 degree tile inside its
    10 degree folder, both floored."""
    lat_i, lon_i = math.floor(lat), math.floor(lon)
    folder = f"{math.floor(lat_i / 10) * 10:+03d}{math.floor(lon_i / 10) * 10:+04d}"
    return Path(folder) / f"{lat_i:+03d}{lon_i:+04d}.png"


class WaterTiles:
    """The committed ``bitmaps/world/water`` tree: per-tile water colour."""

    def __init__(self, root: Path):
        self.root = root

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
