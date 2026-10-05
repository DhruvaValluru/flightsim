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

ROLE_COLOURS = {"valley": (20, 120, 20), "scrub": (90, 90, 30),
                "rock": (100, 100, 100), "cliff": (60, 50, 40),
                "snow": (240, 240, 250)}

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
    soil = terrain / "textures10" / "soil"
    soil.mkdir(parents=True)
    # One flat-coloured texture per drape role (PNG bytes under the .dds
    # name: the reader goes by content), so a drape's colours are checkable.
    for name, colour in ROLE_COLOURS.items():
        Image.new("RGB", (64, 64), colour).save(soil / f"{name}.dds",
                                                format="PNG")
    for ter, texture in (("grass_cld_dry_fl", "valley"),
                         ("shrb_cld_sdry_hill", "scrub"),
                         ("ice_cld_dry_hill", "snow")):
        (terrain / "terrain10" / f"{ter}.ter").write_text(
            f"A\n800\nTERRAIN\n\nBASE_TEX ../textures10/soil/{texture}.dds\n"
            f"PROJECTED 1000 1000\n", encoding="utf-8")
    (terrain / "terrain10" / "rock_cld_dry_steep.ter").write_text(
        "A\n800\nTERRAIN\n\nBASE_TEX ../textures10/soil/rock.dds\n"
        "PROJECTED 1000 1000\n"
        "AUTO_SLOPE_CLIFF 2000 500 57 62 ../textures10/soil/cliff.dds\n",
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
                      "terrain": {"definitions": 4},
                      "drape": {"textures": 5},
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
    assert {"folder": "terrain10", "name": "rock_cld_dry_steep",
            "category": "rock",
            "base_texture": "../textures10/soil/rock.dds"} in rows
    assert len(rows) == 4


def test_missing_extraction_is_a_named_refusal(tmp_path):
    with pytest.raises(XPlaneDataError, match="extract_xplane.py"):
        WaterMask.load(tmp_path / "water_polygons.geojson")
    with pytest.raises(XPlaneDataError, match="extract_xplane.py"):
        load_sky_palettes(tmp_path / "sky_palettes.json")


def test_not_an_xplane_folder_is_a_named_refusal(tmp_path):
    with pytest.raises(XPlaneExtractError, match="Resources"):
        extract(tmp_path, tmp_path / "out")


# -- the planner: mapped water under the flight plans the surface class --


@pytest.fixture
def lake_mask(data, monkeypatch):
    import webapp.runs as runs

    mask = WaterMask.load(data / "water" / "water_polygons.geojson")
    monkeypatch.setattr(runs, "_WATER_MASK", mask)
    return mask


def _spec_at(prompt, lat, lon):
    from core.nl.compiler import compile_prompt

    spec = compile_prompt(prompt)
    spec.set("latitude", lat, frm="stated place")
    spec.set("longitude", lon, frm="stated place")
    return spec


def test_stated_place_over_mapped_water_plans_the_water_class(lake_mask):
    from webapp.runs import plan_water_surface

    spec = _spec_at("fly the c172p at 1000 m", 10.3, 20.3)
    plan_water_surface(spec)
    assert str(spec.surface.value) == "ocean"
    assert str(spec.surface.source) == "derived"
    assert "X-Plane" in spec.surface.frm
    assert "not distinguished" in spec.surface.frm
    digest = spec.digest()
    plan_water_surface(spec)                    # /run plans again
    assert spec.digest() == digest


def test_land_and_uncovered_tiles_plan_nothing(lake_mask):
    from webapp.runs import plan_water_surface

    island = _spec_at("fly the c172p at 1000 m", 10.5, 20.5)
    plan_water_surface(island)
    assert str(island.surface.source) == "default"

    elsewhere = _spec_at("fly the c172p at 1000 m", 11.5, 20.5)
    plan_water_surface(elsewhere)               # no tile: unknown
    assert str(elsewhere.surface.source) == "default"


def test_a_stated_surface_is_never_moved(lake_mask):
    from webapp.runs import plan_water_surface

    spec = _spec_at("fly the c172p over the desert at 1000 m", 10.3, 20.3)
    plan_water_surface(spec)
    assert str(spec.surface.value) == "desert"


def test_default_origin_is_not_a_place(lake_mask, monkeypatch):
    from core.nl.compiler import compile_prompt
    from webapp.runs import plan_water_surface

    monkeypatch.setattr(lake_mask, "contains", lambda lat, lon: True)
    spec = compile_prompt("fly the c172p at 1000 m")
    plan_water_surface(spec)
    assert str(spec.surface.source) == "default"


def test_no_extraction_on_this_machine_plans_nothing(monkeypatch):
    import webapp.runs as runs

    monkeypatch.setattr(runs, "_WATER_MASK", False)
    spec = _spec_at("fly the c172p at 1000 m", 10.3, 20.3)
    runs.plan_water_surface(spec)
    assert str(spec.surface.source) == "default"


def test_compile_endpoint_applies_the_water_planner(lake_mask, monkeypatch):
    """The review table shows the planned surface: /compile runs the
    planner on whatever place the compiler resolved (the offline parser
    reads no coordinates, so the resolved place is injected here)."""
    from fastapi.testclient import TestClient

    import webapp.server as server

    monkeypatch.setattr(
        server, "compile_prompt",
        lambda prompt, **_: _spec_at(prompt, 10.3, 20.3))
    payload = TestClient(server.app).post("/compile", json={
        "prompt": "fly the c172p at 1000 m", "compiler": "regex"}).json()
    surface = next(f for f in payload["spec"]["fields"]
                   if f["name"] == "surface")
    assert surface["value"] == "ocean" and surface["source"] == "derived"


# -- lighting: the decoded sky tables and the render flags they become --


def _flat_tables(**halves):
    """A one-condition table whose every quantity at an anchor is one grey
    level, so interpolation is checkable by hand."""
    from core.xplane import SKY_ANCHOR_ELEVATION_DEG, SKY_QUANTITIES

    def half(levels):
        return {anchor: {q: "#{0:02x}{0:02x}{0:02x}".format(level)
                         for q in SKY_QUANTITIES}
                for (anchor, _), level in zip(SKY_ANCHOR_ELEVATION_DEG, levels)}

    return {"clean": {name: half(levels) for name, levels in halves.items()}}


EVENING = (0, 10, 20, 30, 40, 50, 60, 200)
MORNING = (5, 15, 25, 35, 45, 55, 65, 205)


def test_sky_tables_decode_the_labelled_rows_and_strips(install, tmp_path):
    """Row r of the image is painted grey level r in every strip: the
    evening half must read rows 0..7 top-down, the morning half rows
    15..8, and each strip its own column."""
    from core.xplane import load_sky_tables
    from core.xplane.extract import (
        SKY_ANCHORS, SKY_ROW_PX, SKY_STRIP_PITCH, SKY_STRIP_X0, SKY_STRIPS,
        extract_sky,
    )

    png = (install / "Resources" / "bitmaps" / "skycolors"
           / "sky_colors_clean.png")
    image = Image.new("RGB", SKY_SIZE, (0, 255, 0))
    for row in range(16):
        top = row * SKY_ROW_PX
        image.paste((row, row, 100), (0, top, 128, top + SKY_ROW_PX))
        for i in range(len(SKY_STRIPS)):
            x = SKY_STRIP_X0 + SKY_STRIP_PITCH * i
            image.paste((row, i, 0), (x, top, x + 4, top + SKY_ROW_PX))
    image.save(png)
    extract_sky(install, tmp_path / "out")
    table = load_sky_tables(
        tmp_path / "out" / "lighting" / "sky_tables.json")["clean"]
    for index, anchor in enumerate(SKY_ANCHORS):
        assert table["evening"][anchor]["direct"] == f"#{index:02x}0100"
        assert table["morning"][anchor]["direct"] == f"#{15 - index:02x}0100"
        assert table["evening"][anchor]["sky_zenith"] == \
            f"#{index:02x}{index:02x}64"
    assert table["evening"]["day"]["water"] == "#070400"


def test_sky_lighting_interpolates_between_anchors_and_clamps():
    from core.xplane import sky_lighting

    tables = _flat_tables(evening=EVENING, morning=MORNING)
    # +3 deg, afternoon: halfway between the +2 (50) and +4 (60) rows
    assert sky_lighting("clean", 3.0, 250.0, tables)["direct"] == (55,) * 3
    # the same sun in the morning reads the other half
    assert sky_lighting("clean", 3.0, 100.0, tables)["direct"] == (60,) * 3
    # clamped at both ends: high noon is the day row, deep night the night row
    assert sky_lighting("clean", 50.0, 180.0, tables)["ambient"] == (200,) * 3
    assert sky_lighting("clean", -40.0, 180.0, tables)["ambient"] == (0,) * 3


def test_unknown_sky_condition_is_a_named_refusal():
    from core.xplane import sky_lighting

    with pytest.raises(XPlaneDataError, match="unknown sky condition"):
        sky_lighting("purple", 10.0, 180.0, _flat_tables(evening=EVENING,
                                                         morning=MORNING))


def test_lighting_flags_follow_the_look(monkeypatch):
    from webapp.runs import STORM_LOOK, XPLANE_LIGHTING_ENV, \
        xplane_lighting_flags

    monkeypatch.setenv(XPLANE_LIGHTING_ENV, "on")
    tables = _flat_tables(evening=EVENING, morning=MORNING)
    tables["ocast"] = tables["hazy"] = tables["clean"]
    default = xplane_lighting_flags(None, tables)
    assert default == ["-xplane-condition=clean",
                       "-xplane-direct=200:200:200",
                       "-xplane-ambient=200:200:200",
                       "-xplane-horizon=200:200:200"]
    assert xplane_lighting_flags(STORM_LOOK, tables)[0] == \
        "-xplane-condition=ocast"
    hazy = {"sun_elev": 8.0, "sun_azim": 95.0, "fog_density": 0.010}
    assert xplane_lighting_flags(hazy, tables)[0] == "-xplane-condition=hazy"


def test_lighting_flags_are_absent_when_off_or_unextracted(monkeypatch):
    import core.xplane as xplane
    from webapp.runs import XPLANE_LIGHTING_ENV, xplane_lighting_flags

    tables = _flat_tables(evening=EVENING, morning=MORNING)
    monkeypatch.setenv(XPLANE_LIGHTING_ENV, "off")
    assert xplane_lighting_flags(None, tables) == []

    def missing(path=None):
        raise XPlaneDataError("not extracted")

    monkeypatch.setenv(XPLANE_LIGHTING_ENV, "on")
    monkeypatch.setattr(xplane, "load_sky_tables", missing)
    assert xplane_lighting_flags(None) == []


def test_the_commandlet_parses_every_flag_the_web_app_sends():
    """The Python half and the engine half agree on the flag names."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "ue" / "Plugins"
              / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
              / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
    for name in ("xplane-condition=", "xplane-direct=", "xplane-ambient=",
                 "xplane-horizon="):
        assert f'TEXT("{name}")' in source, name


# -- terrain: the X-Plane ground-texture drape a render wears ------------


def _bake(tmp_path, elevation, snowline=None, name="ridge"):
    from core.terrain.heightfield import Georeference, Heightfield

    field = Heightfield.from_elevations(
        elevation, Georeference(crs="EPSG:32633", origin_x_m=400000.0,
                                origin_y_m=5100000.0, pixel_size_m=30.0),
        name=name,
        provenance={"snowline_m_approx": snowline} if snowline else {})
    stem = tmp_path / "terrain" / name
    stem.parent.mkdir(parents=True, exist_ok=True)
    field.write(stem)
    return stem


def test_drape_textures_carry_xplanes_own_ground_size(data):
    import json

    index = json.loads((data / "terrain" / "drape" / "drape_textures.json")
                       .read_text(encoding="utf-8"))
    assert set(index) == set(ROLE_COLOURS)
    assert (index["rock"]["metres_x"], index["rock"]["metres_y"]) == (1000, 1000)
    # the cliff comes from the rock definition's AUTO_SLOPE_CLIFF line
    assert (index["cliff"]["metres_x"], index["cliff"]["metres_y"]) == (2000, 500)
    assert index["cliff"]["source_texture"] == "cliff.dds"


def test_drape_classifies_flat_steep_and_snow(data, tmp_path):
    """Flat low ground wears the valley texture, a 45 degree face the
    rock texture, flat ground above the snowline the snow texture."""
    import json

    import numpy as np

    from core.xplane.drape import build_drape

    elevation = np.full((60, 90), 500.0)
    # columns 30..59: a 45 degree ramp (30 m rise per 30 m pixel)
    elevation[:, 30:60] = 500.0 + 30.0 * np.arange(1, 31)
    elevation[:, 60:] = 4000.0                    # a high flat plateau
    stem = _bake(tmp_path, elevation, snowline=3000.0)
    sidecar_path = build_drape(stem, data_dir=data)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    texture = np.asarray(Image.open(
        sidecar_path.with_name(sidecar["texture"]["file"])).convert("RGB"))
    k = sidecar["texture"]["texels_per_dem_pixel"]
    assert texture.shape[:2] == (60 * k, 90 * k)

    def texel(column):
        return tuple(int(c) for c in texture[30 * k, column * k])

    assert texel(10) == ROLE_COLOURS["valley"]
    assert texel(45) == ROLE_COLOURS["rock"]
    assert texel(80) == ROLE_COLOURS["snow"]
    assert sidecar["texture"]["crs"] == "EPSG:32633"
    assert "Laminar" in sidecar["attribution"]
    # a second call reuses the drape instead of rebuilding it
    stamp = sidecar_path.stat().st_mtime_ns
    assert build_drape(stem, data_dir=data) == sidecar_path
    assert sidecar_path.stat().st_mtime_ns == stamp


def test_attach_replaces_the_scenes_own_texture(data, tmp_path, monkeypatch):
    import numpy as np

    import core.xplane.drape as drape
    import webapp.runs as runs

    stem = _bake(tmp_path, np.full((40, 40), 500.0))
    monkeypatch.setattr(drape, "DATA_DIR", data)
    monkeypatch.setattr(runs, "_WATER_MASK", False)
    scene = {"key": "x", "terrain": str(stem), "imagery": "/old/s2.json",
             "label": "bake"}

    monkeypatch.setenv(runs.XPLANE_TERRAIN_ENV, "off")
    assert runs.attach_xplane_drape(dict(scene)) is None

    monkeypatch.setenv(runs.XPLANE_TERRAIN_ENV, "on")
    told = []
    sidecar = runs.attach_xplane_drape(scene, told.append)
    assert scene["imagery"] == sidecar
    assert sidecar.endswith("_xplane_drape.json")
    assert "X-Plane" in scene["label"] and len(told) == 1

    flat = {"key": "flat", "terrain": None, "imagery": None, "label": ""}
    assert runs.attach_xplane_drape(flat) is None
