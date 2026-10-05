"""Extract water, terrain-type and sky-colour data from an X-Plane 12 install.

One implementation; ``scripts/extract_xplane.py`` is a thin CLI over
:func:`extract`. Output goes to ``assets/xplane/`` and IS COMMITTED so a
machine without the local simulator install renders the same terrain.

What is read, and what each output does and does not claim:

* ``Resources/map data/water/**/*.shp`` -> ``water/water_polygons.geojson``.
  Polygon geometry only: the shapefiles ship without ``.dbf`` attributes, so
  sea, lake and river are NOT distinguished. Coverage is whatever tiles the
  install has; outside them the mask knows nothing.
* ``Resources/default scenery/1000 world terrain/terrain*/**/*.ter`` ->
  ``terrain/terrain_catalog.csv``. Name, folder and base texture of every
  terrain definition. The ``category`` column is the name's first token, a
  convenience and not an official simulator classification.
* ``Resources/bitmaps/skycolors/sky_colors_*.png`` -> copied to
  ``lighting/`` plus ``lighting/sky_palettes.json``, the centre-column colour
  of the left 128x512 gradient panel in 32 bands, top to bottom
  (``bands_top_to_bottom_32``), beside the crop (``gradient_crop``) and its
  mean colour (``mean_rgb``, each channel truncated). The panel's
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
  steep rock, cliff, snow/ice), each downsampled to at most 2048 px (512
  until 2026-10-05: the committed PNGs are that 512 px pull until the owner
  re-runs the extraction on the machine with the install; what a re-pull
  costs in git and moves in the material script is at
  :data:`DRAPE_TEXTURE_MAX_PX`) with the ground size X-Plane projects it
  at (the .ter's own PROJECTED / AUTO_SLOPE_CLIFF metres). Per role the
  index also records, for the terrain material
  (scripts/ue_create_materials.py M_TerrainImagery, via the drape sidecar):
  ``directives``, every texture- or decal-naming line of the .ter (token,
  arguments, the file as written, and the ``<role>_<kind>.png`` pulled when
  that file is on disk and decodes -- the directive names vary by simulator
  version, so the match is generic, see :data:`_TEXTURE_TOKEN`; a decal
  library (.dcl) is RECORDED, not parsed: the material's detail is the
  role's albedo, not the simulator's decals); ``normal``, the pulled normal
  map when a NORMAL / _NRM directive resolved -- a name relative to
  terrain/drape/, which the drape resolves to an absolute path before it
  reaches the sidecar (null otherwise; the committed index predates this
  and has none); and ``library_lines``, the lines of the terrain
  library.txt files that name the .ter with the REGION selector in force,
  the input the per-season resolution (the simulator mixes a seasonal
  texture per layer, assets/logic_reports/README.md) will be built from
  next -- no seasonal texture is extracted yet. The weather bitmaps
  (snow_ALB/NML/DCL, ice_*, noise) are NOT pulled: core.xplane.physical
  reads them from the committed assets/physical_renders tree alone, and
  the drape records one that tree lacks as absent.

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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageStat

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
#: The longer side of every pulled texture, albedo or map. 512 until
#: 2026-10-05: the material tiles these at the simulator's projected sizes
#: (700-2800 m), where 512 px is 1.4-5.5 m per texel, too coarse for the
#: detail pass; the committed PNGs stay the 512 px pull until re-extracted.
#: What a re-pull at 2048 px costs: sixteen times the texels, so the five
#: albedos (and any map pulled beside them) go from under a megabyte to
#: tens of MB of PNG that git keeps for good -- whether to commit that is
#: the owner's call. What it moves: scripts/ue_create_materials.py pins
#: TERRAIN_DETAIL_NEUTRAL (each tile's linear mean), TERRAIN_DEFAULT_TEXTURES
#: (the flat fallback texels) and TERRAIN_DETAIL_ASPECT (width / height) to
#: the committed PNGs, so a re-pull re-measures all three before the next
#: asset build.
DRAPE_TEXTURE_MAX_PX = 2048
_PROJECTED = re.compile(r"^\s*PROJECTED\s+(\d+)\s+(\d+)", re.M)
_CLIFF = re.compile(r"^\s*AUTO_SLOPE_CLIFF\s+(\d+)\s+(\d+)\s+\S+\s+\S+\s+(\S+)",
                    re.M)

_TILE = re.compile(r"^([+-]\d{2})([+-]\d{3})$")
_BASE_TEX = re.compile(r"^\s*BASE_TEX\s+(\S+)", re.M)

#: A .ter / library.txt directive line: an upper-case token, then arguments.
_DIRECTIVE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)(?:\s+(.*?))?\s*$")
#: The .ter tokens that name a texture or a decal, matched by NAME because
#: the set varies by simulator version: ends in _TEX (BASE_TEX, BORDER_TEX,
#: COMPOSITE_TEX, NORMAL_TEX; BASE_TEX_NOWRAP through its _TEX_ component),
#: ends in _NRM, contains NORMAL (TEXTURE_NORMAL), starts with TEXTURE_ or
#: DECAL_ (DECAL_LIB, DECAL_PARAMS). Those names are the public .ter format
#: description's, not read from any file here; a line is recorded whichever
#: version wrote it. A line of any other token whose arguments name an
#: image file is recorded too (AUTO_SLOPE_CLIFF is one). A DECAL_LIB line's
#: .dcl decal library is recorded, not parsed: the material's detail is the
#: role's albedo, not the simulator's decals.
_TEXTURE_TOKEN = re.compile(r"^(?:TEXTURE_|DECAL_)|_TEX(?:_|$)|_NRM$|NORMAL")
#: The tokens that name a normal / bump map, the role's ``normal``.
_NORMAL_TOKEN = re.compile(r"_NRM$|NORMAL")
#: An argument that names a file: a path separator or a letter extension
#: (a bare number such as DECAL_PARAMS' 1.5 is not one).
_FILE_ARGUMENT = re.compile(r"[/\\]|\.[A-Za-z][A-Za-z0-9]*$")
#: What PIL is asked to decode; anything else named by a directive (a .dcl
#: decal library, say) is recorded and left where it is.
IMAGE_SUFFIXES = frozenset(
    {".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff"})


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
        mean = ImageStat.Stat(panel).mean
        palettes[condition] = {
            "gradient_crop": list(SKY_PANEL),
            "mean_rgb": "#{:02x}{:02x}{:02x}".format(*(int(c) for c in mean[:3])),
            "bands_top_to_bottom_32": bands}
        tables[condition] = _sky_table(rgb)
        shutil.copy(png, out / png.name)
    (out / "sky_palettes.json").write_text(
        json.dumps(palettes, indent=1), encoding="utf-8")
    (out / "sky_tables.json").write_text(
        json.dumps(tables, indent=1), encoding="utf-8")
    return {"conditions": len(palettes)}


def _save_texture(source: Path, out_path: Path, keep_alpha: bool) -> None:
    """Decode a texture (PIL reads the simulator's .dds), fit its longer
    side to :data:`DRAPE_TEXTURE_MAX_PX` (LANCZOS, the one resample for
    albedo and map alike: a normal map is NOT renormalised after it) and
    write it as PNG -- RGB, or RGBA when ``keep_alpha`` and PIL reports an
    alpha mode for the source (every DXT-compressed .dds does, so a map
    comes out RGBA whether or not its alpha holds anything; whether the
    channel carries data is not decided here). A map's channels are kept
    as shipped; which channel holds what (a .dds normal map's blue /
    alpha) is not decoded here."""
    with Image.open(source) as im:
        has_alpha = keep_alpha and (im.mode in ("RGBA", "LA", "PA")
                                    or "transparency" in im.info)
        image = im.convert("RGBA" if has_alpha else "RGB")
    scale = DRAPE_TEXTURE_MAX_PX / max(image.size)
    if scale < 1.0:
        image = image.resize((max(1, round(image.width * scale)),
                              max(1, round(image.height * scale))),
                             Image.LANCZOS)
    image.save(out_path)


def _directive_kind(token: str) -> str:
    """The ``<kind>`` of a pulled ``<role>_<kind>.png``: "normal" for a
    normal-map token, else the token lower-cased without its TEXTURE_ /
    _TEX decoration (BORDER_TEX -> border, BASE_TEX_NOWRAP -> base_nowrap).
    """
    if _NORMAL_TOKEN.search(token):
        return "normal"
    kind = re.sub(r"^texture_", "", token.lower())
    kind = re.sub(r"_tex(?=_|$)", "", kind)
    return kind or "texture"


def _file_argument(args: Sequence[str]) -> Optional[str]:
    """The argument of a directive that names a file: the LAST one with a
    path separator or a letter extension, since some versions put a number
    before the file (TEXTURE_NORMAL's ratio) and DECAL_PARAMS has none."""
    for arg in reversed(args):
        if _FILE_ARGUMENT.search(arg):
            return arg
    return None


def _extract_directives(role: str, ter: Path, text: str, out: Path,
                        written: Dict[Path, str]
                        ) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    """The role's ``directives`` record, its ``normal`` and how many new
    textures were pulled. ``written`` (resolved source -> file in ``out``)
    is shared across roles, so a texture named twice -- the rock .ter's
    BASE_TEX seen again from the cliff role, the same map by two lines --
    is pulled once and the record points at the one file. A file PIL
    cannot decode is recorded with its ``error`` and skipped: the five
    albedos are required, these maps are not. The role's normal is the
    first resolved NORMAL / _NRM directive; the rock .ter serves the rock
    AND the cliff role, so a token with CLIFF in it is the cliff's and one
    without is the rock's (whether the simulator ships a cliff normal
    under any name is not known: none is claimed, the rule only keeps the
    rock's map off the cliff).
    """
    is_cliff = DRAPE_TEXTURES[role][1] == "AUTO_SLOPE_CLIFF"
    directives: List[Dict[str, Any]] = []
    normal = None
    pulled = 0
    kinds: Dict[str, int] = {}
    for raw in text.splitlines():
        match = _DIRECTIVE.match(raw)
        if not match:
            continue
        token = match.group(1)
        args = (match.group(2) or "").split()
        source = _file_argument(args)
        is_image = (source is not None
                    and Path(source).suffix.lower() in IMAGE_SUFFIXES)
        if not (_TEXTURE_TOKEN.search(token) or is_image):
            continue
        entry: Dict[str, Any] = {"token": token, "args": args,
                                 "source": source, "file": None}
        if is_image:
            path = (ter.parent / source).resolve()
            if path in written:
                entry["file"] = written[path]
            elif path.is_file():
                kind = _directive_kind(token)
                kinds[kind] = kinds.get(kind, 0) + 1
                suffix = str(kinds[kind]) if kinds[kind] > 1 else ""
                name = f"{role}_{kind}{suffix}.png"
                try:
                    _save_texture(path, out / name, keep_alpha=True)
                except (OSError, ValueError, NotImplementedError) as exc:
                    # PIL: an unsupported .dds block format, a truncated
                    # file; the record keeps the name, the pull is
                    # skipped. The type alone: PIL's message names the
                    # file by the install's absolute path, which the
                    # committed index must not carry.
                    entry["error"] = type(exc).__name__
                else:
                    written[path] = name
                    entry["file"] = name
                    pulled += 1
        if (entry["file"] and normal is None and _NORMAL_TOKEN.search(token)
                and ("CLIFF" in token) == is_cliff):
            normal = entry["file"]
        directives.append(entry)
    return directives, normal, pulled


def _library_lines(xplane_root: Path, ter: Path) -> List[Dict[str, Any]]:
    """Every line of the terrain library.txt files that names the .ter,
    with the REGION selector in force at it (``REGION <name>`` narrows the
    EXPORTs that follow to a REGION_DEFINE'd region, ``REGION_ALL`` lifts
    it; the library format's own block structure, read from the file and
    not from any decompiled body). Libraries read: the world terrain
    folder's library.txt and a library.txt beside the .ter. This is the
    record the per-season resolution will be built from; it resolves
    nothing itself.
    """
    name = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(ter.name)
                      + r"(?![A-Za-z0-9_])")
    libraries: List[Path] = []
    for candidate in (xplane_root / TERRAIN_REL / "library.txt",
                      ter.parent / "library.txt"):
        if candidate.is_file() and candidate not in libraries:
            libraries.append(candidate)
    lines: List[Dict[str, Any]] = []
    for library in libraries:
        try:
            where = library.relative_to(xplane_root).as_posix()
        except ValueError:
            where = str(library)
        region = None
        text = library.read_bytes().decode("utf-8", errors="ignore")
        for number, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            match = _DIRECTIVE.match(line)
            token = match.group(1) if match else ""
            if token == "REGION":
                region = (match.group(2) or "").strip() or None
            elif token == "REGION_ALL":
                region = None
            if name.search(line):
                lines.append({"library": where, "line": number,
                              "text": line, "region": region})
    return lines


def extract_drape_textures(xplane_root: Path, out_dir: Path) -> Dict[str, int]:
    """The five role albedos and their index (the module docstring), then
    per role the .ter's texture directives, normal map and library lines.
    The counts carry ``textures`` always and ``maps`` (directive textures
    pulled) only when one was written, so an install with nothing new
    yields the same counts as before these were read.
    """
    src = xplane_root / TERRAIN_REL / "terrain10"
    out = out_dir / "terrain" / "drape"
    out.mkdir(parents=True, exist_ok=True)
    index = {}
    #: resolved source texture -> the file it was written to under out
    written: Dict[Path, str] = {}
    texts: Dict[str, Tuple[Path, str]] = {}
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
        _save_texture(texture, out / f"{role}.png", keep_alpha=False)
        written.setdefault(texture, f"{role}.png")
        texts[role] = (ter, text)
        index[role] = {"file": f"{role}.png", "metres_x": metres[0],
                       "metres_y": metres[1], "source_ter": ter.name,
                       "source_texture": texture.name}
    # The maps after every albedo, so a directive naming an albedo (the
    # cliff role's BASE_TEX is the rock's) points at it instead of
    # pulling a second copy, whatever the role order.
    pulled = 0
    for role, (ter, text) in texts.items():
        directives, normal, count = _extract_directives(
            role, ter, text, out, written)
        pulled += count
        index[role]["normal"] = normal
        index[role]["directives"] = directives
        index[role]["library_lines"] = _library_lines(xplane_root, ter)
    (out / "drape_textures.json").write_text(
        json.dumps(index, indent=1), encoding="utf-8")
    counts = {"textures": len(index)}
    if pulled:
        counts["maps"] = pulled
    return counts


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
