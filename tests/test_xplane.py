"""X-Plane extraction and its readers, on a synthetic install.

The claim under test: the extractor reads X-Plane's own file layouts
(.shp polygon records, .ter headers, the sky_colors panel) into
data/xplane/, and the readers answer honestly -- water only where a tile
was shipped, None where it was not, and a named refusal when nothing has
been extracted.
"""

import struct

import pytest
from PIL import Image

from core.xplane import (
    WaterMask, XPlaneDataError, load_sky_palettes, load_terrain_catalog,
)
from core.xplane.extract import (
    SKY_SIZE, XPlaneExtractError, extract, read_shp_polygons,
)

# A lake in tile +10+020 with an island in it. Shapefile winding: outer
# ring clockwise, hole counter-clockwise.
LAKE = [(20.2, 10.2), (20.2, 10.8), (20.8, 10.8), (20.8, 10.2), (20.2, 10.2)]
ISLAND = [(20.4, 10.4), (20.6, 10.4), (20.6, 10.6), (20.4, 10.6), (20.4, 10.4)]


def write_shp(path, records):
    """records: a list of polygon records, each a list of rings."""
    body = b""
    for number, rings in enumerate(records, 1):
        points = [p for ring in rings for p in ring]
        parts, offset = [], 0
        for ring in rings:
            parts.append(offset)
            offset += len(ring)
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        content = struct.pack("<i4d2i", 5, min(xs), min(ys), max(xs), max(ys),
                              len(rings), len(points))
        content += struct.pack(f"<{len(parts)}i", *parts)
        for x, y in points:
            content += struct.pack("<2d", x, y)
        body += struct.pack(">2i", number, len(content) // 2) + content
    header = struct.pack(">i", 9994) + b"\0" * 20
    header += struct.pack(">i", (100 + len(body)) // 2)
    header += struct.pack("<2i", 1000, 5) + b"\0" * 64
    path.write_bytes(header + body)


@pytest.fixture
def install(tmp_path):
    root = tmp_path / "X-Plane 12"
    water = root / "Resources" / "map data" / "water" / "+10+020"
    water.mkdir(parents=True)
    write_shp(water / "+10+020.shp", [[LAKE, ISLAND]])

    terrain = root / "Resources" / "default scenery" / "1000 world terrain"
    (terrain / "terrain10").mkdir(parents=True)
    (terrain / "terrain10" / "rock_cld_dry_steep.ter").write_text(
        "A\n800\nTERRAIN\n\nBASE_TEX ../textures10/soil/rock.dds\n",
        encoding="utf-8")

    sky = root / "Resources" / "bitmaps" / "skycolors"
    sky.mkdir(parents=True)
    image = Image.new("RGB", SKY_SIZE, (0, 255, 0))      # the unused fill
    image.paste((10, 20, 30), (0, 0, 128, 256))          # upper panel half
    image.paste((200, 210, 220), (0, 256, 128, 512))     # lower panel half
    image.save(sky / "sky_colors_clean.png")
    return root


@pytest.fixture
def data(install, tmp_path):
    out = tmp_path / "data"
    counts = extract(install, out)
    assert counts == {"water": {"tiles": 1, "polygons": 1},
                      "terrain": {"definitions": 1},
                      "sky": {"conditions": 1}}
    return out


def test_shp_reader_returns_each_records_rings(install):
    shp = (install / "Resources" / "map data" / "water" / "+10+020"
           / "+10+020.shp")
    assert read_shp_polygons(shp) == [[LAKE, ISLAND]]


def test_water_is_the_lake_minus_its_island(data):
    mask = WaterMask.load(data / "water" / "water_polygons.geojson")
    assert mask.polygon_count == 1
    assert mask.contains(10.3, 20.3) is True      # in the lake
    assert mask.contains(10.5, 20.5) is False     # on the island
    assert mask.contains(10.1, 20.1) is False     # on the shore, same tile


def test_outside_shipped_tiles_is_unknown_not_dry(data):
    mask = WaterMask.load(data / "water" / "water_polygons.geojson")
    assert mask.covers(10.5, 20.5)
    assert not mask.covers(11.5, 20.5)
    assert mask.contains(11.5, 20.5) is None


def test_rasterize_matches_contains_north_up(data):
    mask = WaterMask.load(data / "water" / "water_polygons.geojson")
    raster = mask.rasterize(20.0, 10.0, 21.0, 11.0, 100, 100)
    assert raster.shape == (100, 100)

    def pixel(lat, lon):
        return raster[int((11.0 - lat) * 100), int((lon - 20.0) * 100)]

    assert pixel(10.3, 20.3)
    assert not pixel(10.5, 20.5)
    assert not pixel(10.1, 20.1)
    # lake 0.6 x 0.6 deg minus island 0.2 x 0.2 deg = 32% of the tile; the
    # rasteriser fills edge pixels inclusively, hence the 3% allowance
    assert abs(raster.mean() - 0.32) < 0.03
    # north-up: the lake spans rows 20..80, so the top rows are dry
    assert not raster[:15].any()


def test_sky_palette_samples_the_panel_not_the_fill(data):
    bands = load_sky_palettes(data / "lighting" / "sky_palettes.json")["clean"]
    assert len(bands) == 32
    assert bands[0] == "#0a141e" and bands[-1] == "#c8d2dc"
    assert "#00ff00" not in bands


def test_terrain_catalog_reads_the_base_texture(data):
    rows = load_terrain_catalog(data / "terrain" / "terrain_catalog.csv")
    assert rows == [{"folder": "terrain10", "name": "rock_cld_dry_steep",
                     "category": "rock",
                     "base_texture": "../textures10/soil/rock.dds"}]


def test_missing_extraction_is_a_named_refusal(tmp_path):
    with pytest.raises(XPlaneDataError, match="extract_xplane.py"):
        WaterMask.load(tmp_path / "water_polygons.geojson")
    with pytest.raises(XPlaneDataError, match="extract_xplane.py"):
        load_sky_palettes(tmp_path / "sky_palettes.json")


def test_not_an_xplane_folder_is_a_named_refusal(tmp_path):
    with pytest.raises(XPlaneExtractError, match="Resources"):
        extract(tmp_path, tmp_path / "out")
