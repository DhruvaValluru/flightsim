"""Extract water, terrain-type and sky-colour data from an X-Plane 12 install.

One implementation; ``scripts/extract_xplane.py`` is a thin CLI over
:func:`extract`. Output goes to ``assets/xplane/`` and IS COMMITTED (owner's
decision, 2026-10-05, so a machine without X-Plane renders the same
terrain). These are Laminar Research's files and derivatives of them: the
repository must stay PRIVATE while they are in its history.

What is read, and what each output does and does not claim:

* ``Resources/map data/water/**/*.shp`` -> ``water/water_polygons.geojson``.
  Polygon geometry only: the shapefiles ship without ``.dbf`` attributes, so
  sea, lake and river are NOT distinguished. Coverage is whatever tiles the
  install has; outside them the mask knows nothing.
* ``Resources/default scenery/1000 world terrain/terrain*/**/*.ter`` ->
  ``terrain/terrain_catalog.csv``. Name, folder and base texture of every
  terrain definition. The ``category`` column is the name's first token, a
  convenience and not an X-Plane classification.
* ``Resources/bitmaps/skycolors/sky_colors_*.png`` -> copied to
  ``lighting/`` plus ``lighting/sky_palettes.json``, the centre-column colour
  of the left 128x512 gradient panel in 32 bands, top to bottom. The panel's
  rows are sun-elevation bands by the image's own labels.
  ``lighting/sky_tables.json`` is the same images decoded by those labels:
  16 rows of 32 px (top to bottom: night, -8, -4, -2, set, +2, +4, aft,
  then morn, +4, +2, dawn, -2, -4, -8, night) and, right of the panel,
  eight 4 px strips (ambient light, direct light, sun color, moon color,
  water color, cloud dark, cloud light, moon dir lit). Each cell is sampled
  at its centre. The labels give the row ORDER and the +/-2/4/8 degree
  anchors; the elevations of "night" and of full day ("aft"/"morn") are not
  printed anywhere and are assumptions of the reader (core.xplane), stated
  there. Sky zenith/horizon are the panel's top-centre and bottom-edge
  pixels of the row, read as zenith and horizon-away-from-sun: an
  interpretation of the gradient, not a documented layout.

* five ``.ter`` definitions and the textures they name ->
  ``terrain/drape/<role>.png`` + ``drape_textures.json``: the ground
  textures core.xplane.drape tiles over a bake (valley grass, hill scrub,
  steep rock, cliff, snow/ice), each downsampled to at most 512 px with the
  ground size X-Plane projects it at (the .ter's own PROJECTED /
  AUTO_SLOPE_CLIFF metres).

The .shp reader is the ESRI polygon record layout read directly, so the
extraction adds no dependency.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import struct
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image

Ring = List[Tuple[float, float]]

WATER_REL = Path("Resources") / "map data" / "water"
TERRAIN_REL = Path("Resources") / "default scenery" / "1000 world terrain"
SKY_REL = Path("Resources") / "bitmaps" / "skycolors"

#: Polygon, PolygonZ, PolygonM share the bbox/parts/points prefix read here.
_POLYGON_TYPES = (5, 15, 25)
#: The gradient panel of a 256x640 sky_colors image; the rest is labels,
#: per-channel strips and an unused fill.
SKY_PANEL = (0, 0, 128, 512)
SKY_SIZE = (256, 640)
SKY_BANDS = 32
#: The decoded layout (see the module docstring): row labels top to bottom
#: for the evening half; the morning half is the same order bottom to top.
SKY_ROW_PX = 32
SKY_ANCHORS = ("night", "-8", "-4", "-2", "0", "+2", "+4", "day")
#: The eight strips right of the panel, left to right, and their x origin.
SKY_STRIPS = ("ambient", "direct", "sun", "moon", "water", "cloud_dark",
              "cloud_light", "moon_dir")
SKY_STRIP_X0 = 129
SKY_STRIP_PITCH = 5

#: role -> (terrain10 .ter name, which line names the texture). The roles
#: are the classes of FlightSimVisualScene's ClassifyVertex plus a cliff.
DRAPE_TEXTURES = {
    "valley": ("grass_cld_dry_fl", "PROJECTED"),
    "scrub": ("shrb_cld_sdry_hill", "PROJECTED"),
    "rock": ("rock_cld_dry_steep", "PROJECTED"),
    "cliff": ("rock_cld_dry_steep", "AUTO_SLOPE_CLIFF"),
    "snow": ("ice_cld_dry_hill", "PROJECTED"),
}
DRAPE_TEXTURE_MAX_PX = 512
_PROJECTED = re.compile(r"^\s*PROJECTED\s+(\d+)\s+(\d+)", re.M)
_CLIFF = re.compile(r"^\s*AUTO_SLOPE_CLIFF\s+(\d+)\s+(\d+)\s+\S+\s+\S+\s+(\S+)",
                    re.M)

_TILE = re.compile(r"^([+-]\d{2})([+-]\d{3})$")
_BASE_TEX = re.compile(r"^\s*BASE_TEX\s+(\S+)", re.M)


class XPlaneExtractError(Exception):
    """The install does not contain what the extraction needs."""


def read_shp_polygons(path: Path) -> List[List[Ring]]:
    """Every polygon record of a .shp file as its list of rings (lon, lat)."""
    data = path.read_bytes()
    if len(data) < 100 or struct.unpack(">i", data[:4])[0] != 9994:
        raise XPlaneExtractError(f"{path} is not an ESRI shapefile")
    records = []
    pos = 100
    while pos + 8 <= len(data):
        content_len = struct.unpack(">i", data[pos + 4:pos + 8])[0] * 2
        body = data[pos + 8:pos + 8 + content_len]
        pos += 8 + content_len
        if len(body) < 44:
            continue
        if struct.unpack("<i", body[:4])[0] not in _POLYGON_TYPES:
            continue
        n_parts, n_points = struct.unpack("<ii", body[36:44])
        parts = list(struct.unpack(f"<{n_parts}i", body[44:44 + 4 * n_parts]))
        start = 44 + 4 * n_parts
        flat = struct.unpack(f"<{2 * n_points}d",
                             body[start:start + 16 * n_points])
        points = list(zip(flat[0::2], flat[1::2]))
        rings = [points[a:b] for a, b in zip(parts, parts[1:] + [n_points])]
        rings = [r for r in rings if len(r) >= 4]
        if rings:
            records.append(rings)
    return records


def _signed_area(ring: Ring) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0
                     for (x0, y0), (x1, y1) in zip(ring, ring[1:]))


def _point_in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def rings_to_polygons(rings: Sequence[Ring]) -> List[List[Ring]]:
    """Group a shapefile record's rings into GeoJSON polygons.

    Shapefile outer rings are clockwise and holes counter-clockwise; a hole
    belongs to the outer ring that contains it.
    """
    outers = [r for r in rings if _signed_area(r) <= 0]
    holes = [r for r in rings if _signed_area(r) > 0]
    if not outers:      # a writer that ignored winding: treat all as outers
        outers, holes = list(rings), []
    polygons = [[o] for o in outers]
    for hole in holes:
        x, y = hole[0]
        for poly in polygons:
            if _point_in_ring(x, y, poly[0]):
                poly.append(hole)
                break
    return polygons


def extract_water(xplane_root: Path, out_dir: Path) -> Dict[str, int]:
    src = xplane_root / WATER_REL
    shps = sorted(src.rglob("*.shp"))
    if not shps:
        raise XPlaneExtractError(f"no water shapefiles under {src}")
    features = []
    tiles = []
    for shp in shps:
        tile = shp.stem
        if not _TILE.match(tile):
            raise XPlaneExtractError(
                f"{shp.name}: expected a +LL+LLL tile name")
        tiles.append(tile)
        for rings in read_shp_polygons(shp):
            features.append({
                "type": "Feature",
                "properties": {"tile": tile},
                "geometry": {"type": "MultiPolygon",
                             "coordinates": rings_to_polygons(rings)},
            })
    out = out_dir / "water"
    out.mkdir(parents=True, exist_ok=True)
    (out / "water_polygons.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "tiles": tiles,
                    "features": features}), encoding="utf-8")
    return {"tiles": len(tiles), "polygons": len(features)}


def extract_terrain_catalog(xplane_root: Path, out_dir: Path) -> Dict[str, int]:
    src = xplane_root / TERRAIN_REL
    rows = []
    for folder in sorted(p for p in src.glob("terrain*") if p.is_dir()):
        for ter in sorted(folder.rglob("*.ter")):
            head = ter.read_bytes()[:4096].decode("utf-8", errors="ignore")
            match = _BASE_TEX.search(head)
            rows.append({"folder": folder.name, "name": ter.stem,
                         "category": ter.stem.split("_")[0],
                         "base_texture": match.group(1) if match else ""})
    if not rows:
        raise XPlaneExtractError(f"no .ter terrain definitions under {src}")
    out = out_dir / "terrain"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "terrain_catalog.csv", "w", newline="",
              encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"definitions": len(rows)}


def _hex(pixel: Tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*pixel)


def _sky_row(rgb: Image.Image, row: int) -> Dict[str, str]:
    top = row * SKY_ROW_PX
    centre_y = top + SKY_ROW_PX // 2
    cell = {name: _hex(rgb.getpixel((SKY_STRIP_X0 + SKY_STRIP_PITCH * i + 1,
                                     centre_y)))
            for i, name in enumerate(SKY_STRIPS)}
    panel_width = SKY_PANEL[2]
    cell["sky_zenith"] = _hex(rgb.getpixel((panel_width // 2, top + 1)))
    cell["sky_horizon"] = _hex(rgb.getpixel((4, top + SKY_ROW_PX - 2)))
    return cell


def _sky_table(rgb: Image.Image) -> Dict[str, Dict[str, Dict[str, str]]]:
    """One condition's lookup image as {half: {anchor: {quantity: hex}}}."""
    last = 2 * len(SKY_ANCHORS) - 1
    return {
        "evening": {anchor: _sky_row(rgb, i)
                    for i, anchor in enumerate(SKY_ANCHORS)},
        "morning": {anchor: _sky_row(rgb, last - i)
                    for i, anchor in enumerate(SKY_ANCHORS)},
    }


def extract_sky(xplane_root: Path, out_dir: Path) -> Dict[str, int]:
    src = xplane_root / SKY_REL
    pngs = sorted(src.glob("sky_colors_*.png"))
    if not pngs:
        raise XPlaneExtractError(f"no sky_colors_*.png under {src}")
    out = out_dir / "lighting"
    out.mkdir(parents=True, exist_ok=True)
    palettes = {}
    tables = {}
    for png in pngs:
        condition = png.stem[len("sky_colors_"):]
        with Image.open(png) as im:
            if im.size != SKY_SIZE:
                raise XPlaneExtractError(
                    f"{png.name} is {im.size}, expected {SKY_SIZE}; the "
                    f"panel crop was only checked against that layout")
            rgb = im.convert("RGB")
            panel = rgb.crop(SKY_PANEL)
        width, height = panel.size
        bands = []
        for i in range(SKY_BANDS):
            r, g, b = panel.getpixel((width // 2,
                                      int((i + 0.5) * height / SKY_BANDS)))
            bands.append(f"#{r:02x}{g:02x}{b:02x}")
        palettes[condition] = {"source": png.name, "panel": list(SKY_PANEL),
                               "bands_top_to_bottom": bands}
        tables[condition] = _sky_table(rgb)
        shutil.copy(png, out / png.name)
    (out / "sky_palettes.json").write_text(
        json.dumps(palettes, indent=1), encoding="utf-8")
    (out / "sky_tables.json").write_text(
        json.dumps(tables, indent=1), encoding="utf-8")
    return {"conditions": len(palettes)}


def extract_drape_textures(xplane_root: Path, out_dir: Path) -> Dict[str, int]:
    src = xplane_root / TERRAIN_REL / "terrain10"
    out = out_dir / "terrain" / "drape"
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    for role, (ter_name, line) in DRAPE_TEXTURES.items():
        ter = src / f"{ter_name}.ter"
        if not ter.is_file():
            raise XPlaneExtractError(f"{ter} not found")
        text = ter.read_bytes().decode("utf-8", errors="ignore")
        if line == "AUTO_SLOPE_CLIFF":
            match = _CLIFF.search(text)
            if not match:
                raise XPlaneExtractError(f"{ter.name} has no AUTO_SLOPE_CLIFF")
            metres = (float(match.group(1)), float(match.group(2)))
            texture_rel = match.group(3)
        else:
            size = _PROJECTED.search(text)
            base = _BASE_TEX.search(text)
            if not size or not base:
                raise XPlaneExtractError(
                    f"{ter.name} has no PROJECTED size or BASE_TEX")
            metres = (float(size.group(1)), float(size.group(2)))
            texture_rel = base.group(1)
        texture = (ter.parent / texture_rel).resolve()
        if not texture.is_file():
            raise XPlaneExtractError(
                f"{ter.name} names {texture_rel}, which this install lacks")
        with Image.open(texture) as im:
            rgb = im.convert("RGB")
        scale = DRAPE_TEXTURE_MAX_PX / max(rgb.size)
        if scale < 1.0:
            rgb = rgb.resize((max(1, round(rgb.width * scale)),
                              max(1, round(rgb.height * scale))),
                             Image.LANCZOS)
        rgb.save(out / f"{role}.png")
        index[role] = {"file": f"{role}.png", "metres_x": metres[0],
                       "metres_y": metres[1], "source_ter": ter.name,
                       "source_texture": texture.name}
    (out / "drape_textures.json").write_text(
        json.dumps(index, indent=1), encoding="utf-8")
    return {"textures": len(index)}


def extract(xplane_root: Path, out_dir: Path) -> Dict[str, Dict[str, int]]:
    """Run all three extractions; returns the counts of what was written."""
    xplane_root = Path(xplane_root)
    if not (xplane_root / "Resources").is_dir():
        raise XPlaneExtractError(
            f"{xplane_root} has no Resources/ folder; pass the X-Plane 12 "
            f"install root")
    out_dir = Path(out_dir)
    return {"water": extract_water(xplane_root, out_dir),
            "terrain": extract_terrain_catalog(xplane_root, out_dir),
            "drape": extract_drape_textures(xplane_root, out_dir),
            "sky": extract_sky(xplane_root, out_dir)}
