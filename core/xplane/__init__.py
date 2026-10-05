"""Readers for the data ``scripts/extract_xplane.py`` writes to data/xplane/.

The water mask feeds webapp.runs.plan_water_surface (mapped water under
the flight plans the water surface class). The decoded sky tables feed
webapp.runs.xplane_lighting_flags (sun, sky-light and fog colours for the
legacy-look render). The terrain catalog has no consumer yet. Every loader refuses by name when the
extraction has not been run, rather than returning an empty answer that
would read as "no water here".
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "xplane"


class XPlaneDataError(Exception):
    """The extracted X-Plane data is missing or not what the loader expects."""


def _require(path: Path) -> Path:
    if not path.exists():
        raise XPlaneDataError(
            f"{path} not found; run scripts/extract_xplane.py "
            f"--xplane-root <your X-Plane 12 folder> first")
    return path


def _tile_key(lat: float, lon: float) -> Tuple[int, int]:
    return math.floor(lat), math.floor(lon)


class WaterMask:
    """Water polygons from X-Plane's map data, in WGS84 lon/lat.

    The source carries no attributes, so "water" is sea, lake or river
    without distinction. The mask only knows the 1x1 degree tiles the
    install shipped: :meth:`covers` says whether a point is inside one, and
    :meth:`contains` returns ``None`` outside them instead of ``False``.
    """

    def __init__(self, tiles: Set[Tuple[int, int]],
                 polygons: Dict[Tuple[int, int], List[List[np.ndarray]]]):
        self.tiles = tiles
        self._polygons = polygons

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "WaterMask":
        path = _require(Path(path) if path else
                        DATA_DIR / "water" / "water_polygons.geojson")
        doc = json.loads(path.read_text(encoding="utf-8"))
        tiles = {(int(t[:3]), int(t[3:])) for t in doc["tiles"]}
        polygons: Dict[Tuple[int, int], List[List[np.ndarray]]] = {}
        for feature in doc["features"]:
            tile = feature["properties"]["tile"]
            key = (int(tile[:3]), int(tile[3:]))
            for rings in feature["geometry"]["coordinates"]:
                polygons.setdefault(key, []).append(
                    [np.asarray(r, dtype=float) for r in rings])
        return cls(tiles, polygons)

    @property
    def polygon_count(self) -> int:
        return sum(len(v) for v in self._polygons.values())

    def covers(self, lat: float, lon: float) -> bool:
        return _tile_key(lat, lon) in self.tiles

    def contains(self, lat: float, lon: float) -> Optional[bool]:
        """True/False inside a covered tile, None where there is no data."""
        key = _tile_key(lat, lon)
        if key not in self.tiles:
            return None
        for rings in self._polygons.get(key, ()):
            # even-odd over outer ring + holes
            if sum(_in_ring(lon, lat, r) for r in rings) % 2 == 1:
                return True
        return False

    def rasterize(self, west: float, south: float, east: float, north: float,
                  width: int, height: int) -> np.ndarray:
        """Boolean water mask on a plain lon/lat grid, row 0 at the north edge.

        The grid is equirectangular; a UTM bake needs its pixel centres
        projected to lon/lat and passed to :meth:`contains`, or this raster
        reprojected. Pixels in tiles the mask does not cover come back
        False -- check :meth:`covers` for the corners first.
        """
        if not (east > west and north > south and width > 0 and height > 0):
            raise ValueError("empty raster extent")
        sx = width / (east - west)
        sy = height / (north - south)

        def to_px(ring: np.ndarray) -> List[Tuple[float, float]]:
            return list(zip(((ring[:, 0] - west) * sx).tolist(),
                            ((north - ring[:, 1]) * sy).tolist()))

        mask = Image.new("1", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        for lat in range(math.floor(south), math.ceil(north)):
            for lon in range(math.floor(west), math.ceil(east)):
                for rings in self._polygons.get((lat, lon), ()):
                    if len(rings) == 1:
                        draw.polygon(to_px(rings[0]), fill=1)
                        continue
                    one = Image.new("1", (width, height), 0)
                    one_draw = ImageDraw.Draw(one)
                    one_draw.polygon(to_px(rings[0]), fill=1)
                    for hole in rings[1:]:
                        one_draw.polygon(to_px(hole), fill=0)
                    mask = ImageChops.logical_or(mask, one)
                    draw = ImageDraw.Draw(mask)
        return np.asarray(mask, dtype=bool)


def _in_ring(x: float, y: float, ring: np.ndarray) -> bool:
    x0, y0 = ring[:-1, 0], ring[:-1, 1]
    x1, y1 = ring[1:, 0], ring[1:, 1]
    straddle = (y0 > y) != (y1 > y)
    if not straddle.any():
        return False
    xi = x0[straddle] + (y - y0[straddle]) * (x1[straddle] - x0[straddle]) \
        / (y1[straddle] - y0[straddle])
    return bool(np.count_nonzero(x < xi) % 2)


def load_sky_palettes(path: Optional[Path] = None) -> Dict[str, List[str]]:
    """Condition name -> 32 hex colours down the sky gradient panel.

    The bands run top to bottom of X-Plane's lookup image; their mapping to
    sun elevation is not decoded (see core/xplane/extract.py).
    """
    path = _require(Path(path) if path else
                    DATA_DIR / "lighting" / "sky_palettes.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {name: entry["bands_top_to_bottom"] for name, entry in doc.items()}


#: Sun elevation of each table anchor, degrees. The +/-2/4/8 anchors and
#: 0 (the image's "set"/"dawn" row) are the image's own labels. The two
#: ends are ASSUMPTIONS: X-Plane prints "night" and "aft"/"morn" with no
#: angle, so night is taken as the end of nautical twilight and full day
#: as the first elevation comfortably past the +4 row.
SKY_ANCHOR_ELEVATION_DEG = (("night", -12.0), ("-8", -8.0), ("-4", -4.0),
                            ("-2", -2.0), ("0", 0.0), ("+2", 2.0),
                            ("+4", 4.0), ("day", 10.0))
SKY_QUANTITIES = ("ambient", "direct", "sun", "moon", "water", "cloud_dark",
                  "cloud_light", "moon_dir", "sky_zenith", "sky_horizon")


def load_sky_tables(path: Optional[Path] = None) -> Dict[str, Dict]:
    """Condition -> {"evening"|"morning": {anchor: {quantity: "#rrggbb"}}}."""
    path = _require(Path(path) if path else
                    DATA_DIR / "lighting" / "sky_tables.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _rgb(hex_colour: str) -> Tuple[int, int, int]:
    return (int(hex_colour[1:3], 16), int(hex_colour[3:5], 16),
            int(hex_colour[5:7], 16))


def sky_lighting(condition: str, sun_elevation_deg: float,
                 sun_azimuth_deg: float,
                 tables: Optional[Dict[str, Dict]] = None
                 ) -> Dict[str, Tuple[int, int, int]]:
    """X-Plane's lighting colours for a sky condition and sun position.

    Returns every quantity of :data:`SKY_QUANTITIES` as an 8-bit sRGB
    triple, linearly interpolated (in sRGB, as the lookup image itself
    blends between its rows) between the two anchors bracketing the sun
    elevation and clamped at the night and day ends. A sun east of south
    (azimuth < 180) reads the morning half, otherwise the evening half.
    Unknown conditions refuse by name.
    """
    tables = load_sky_tables() if tables is None else tables
    if condition not in tables:
        raise XPlaneDataError(
            f"unknown sky condition {condition!r}; extracted: "
            f"{sorted(tables)}")
    half = tables[condition][
        "morning" if (sun_azimuth_deg % 360.0) < 180.0 else "evening"]
    anchors = SKY_ANCHOR_ELEVATION_DEG
    elevation = min(max(float(sun_elevation_deg), anchors[0][1]),
                    anchors[-1][1])
    for (low, low_deg), (high, high_deg) in zip(anchors, anchors[1:]):
        if elevation <= high_deg:
            break
    t = (elevation - low_deg) / (high_deg - low_deg)
    result = {}
    for quantity in SKY_QUANTITIES:
        a = _rgb(half[low][quantity])
        b = _rgb(half[high][quantity])
        result[quantity] = tuple(
            int(round(x + (y - x) * t)) for x, y in zip(a, b))
    return result


def load_terrain_catalog(path: Optional[Path] = None) -> List[Dict[str, str]]:
    """Every X-Plane terrain definition: folder, name, category, base_texture."""
    path = _require(Path(path) if path else
                    DATA_DIR / "terrain" / "terrain_catalog.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
