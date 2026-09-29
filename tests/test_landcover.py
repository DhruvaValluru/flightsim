"""ESA WorldCover land cover onto the bake grid (gap S5, the data half).

Offline throughout except one test: synthetic COGs written with rasterio
in tmp_path carry known classes in known quadrants, synthetic bake
sidecars (written by Heightfield itself, so the shape is the real one)
carry the grid, and the expected fractions are re-derived here from the
source arrays without the module. The one network test reads a small
window of the real N36W120 tile and is SKIPPED BY NAME when the bucket is
unreachable (the shape of tests/test_aircraft_assets.py's pinned-source
skip); it measures nothing when skipped and says so.

Every number below was measured in this container on 2026-09-28: the
Yosemite bake's land cover (1151 x 894 cells, tree cover 68.66 %,
grassland 21.69 %, bare 9.18 %, 400 of 400 texels agreeing with the
source, weights summing to 255 in every cell) is the demonstration in
docs/ADVANCEMENTS_REPORT.md; the unit tests here pin the arithmetic that
produced it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from core.messages import name_of
from core.records import RECORD_VERSION, read_records
from core.terrain import landcover
from core.terrain.glo30 import LOCATIONS, Location
from core.terrain.heightfield import Georeference, Heightfield
from core.terrain.landcover import (
    LEGEND, LEGEND_CODES, NODATA_KEY, PIXEL_DEG, WEIGHT_KEYS, LandcoverError,
    LandcoverGridError, bbox_for_grid, fetch, rasterise, read_grid, tile_stem,
    tile_url, tiles_for_bbox, verify_against_source, weight_counts, weightmaps,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bake_landcover.py"

#: The attribution the product user manual requires (section 5.2), spelled
#: here independently of the module so a drift in either is caught.
REQUIRED_ATTRIBUTION = ("(c) ESA WorldCover project 2021 / Contains modified "
                        "Copernicus Sentinel data (2021) processed by ESA "
                        "WorldCover consortium")

#: The legend as the task states it (WorldCover Table 3).
LEGEND_AS_STATED = {10: "tree_cover", 20: "shrubland", 30: "grassland",
                    40: "cropland", 50: "built_up", 60: "bare_sparse",
                    70: "snow_ice", 80: "permanent_water",
                    90: "herbaceous_wetland", 95: "mangroves", 100: "moss_lichen"}

LON0, LAT0 = -119.80, 37.85      # a source origin on the product's grid
SIZE = 60                        # source pixels per side (quadrants of 30)
QUADRANTS = ((10, 30), (60, 80))  # (NW, NE), (SW, SE)


# -- fixtures --------------------------------------------------------------

def write_source(path: Path, lon_left: float, lat_top: float,
                 classes: np.ndarray, driver: str = "COG") -> Path:
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(path, "w", driver=driver, height=classes.shape[0],
                       width=classes.shape[1], count=1, dtype="uint8",
                       crs="EPSG:4326", nodata=0, compress="DEFLATE",
                       transform=from_origin(lon_left, lat_top, PIXEL_DEG, PIXEL_DEG)
                       ) as dst:
        dst.write(classes.astype(np.uint8), 1)
    return path


def quadrant_classes(size: int = SIZE) -> np.ndarray:
    half = size // 2
    out = np.zeros((size, size), dtype=np.uint8)
    out[:half, :half] = QUADRANTS[0][0]
    out[:half, half:] = QUADRANTS[0][1]
    out[half:, :half] = QUADRANTS[1][0]
    out[half:, half:] = QUADRANTS[1][1]
    return out


def write_bake(out_dir: Path, key: str, crs: str, origin_x: float,
               origin_y: float, pixel: float, width: int, height: int,
               datum: bool = False) -> Path:
    """A bake with the sidecar Heightfield.write really writes. With
    ``datum`` the sidecar carries the synthesised datum block a real bake
    carries (core.terrain.geoid.datum_for_heightfield), which the
    Landscape import manifest copies (W1)."""
    z = np.linspace(1000.0, 1500.0, width * height).reshape(height, width)
    field = Heightfield.from_elevations(
        z, Georeference(crs, origin_x, origin_y, pixel,
                        is_projected=not crs.endswith("4326")),
        name=key, provenance={"synthetic": True})
    if datum:
        from core.terrain.geoid import datum_for_heightfield

        field.provenance["datum"] = datum_for_heightfield(field)
    return field.write(out_dir / key)


@pytest.fixture
def quadrant_source(tmp_path):
    return write_source(tmp_path / "quadrants.tif", LON0, LAT0, quadrant_classes())


def aligned_location(key: str, bbox) -> Location:
    return Location(key=key, title="synthetic", tiles=(), bbox=bbox,
                    crs="EPSG:4326", origin_lat=(bbox[0] + bbox[1]) / 2,
                    origin_lon=(bbox[2] + bbox[3]) / 2, snowline_m=0.0)


def read_weights(scene_dir: Path):
    from PIL import Image

    return {key: np.asarray(Image.open(scene_dir / f"{key}_weight.png"))
            for key in WEIGHT_KEYS}


# -- tiles -----------------------------------------------------------------

def test_tile_stems_name_the_south_west_corner_in_three_degree_steps():
    assert tile_stem(37.7275, -119.61) == "N36W120"
    assert tile_stem(46.005, 7.72) == "N45E006"
    assert tile_stem(-33.9, 151.2) == "S36E150"
    assert tile_stem(0.5, -0.5) == "N00W003"
    assert tile_url("N36W120") == (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
        "ESA_WorldCover_10m_2021_v200_N36W120_Map.tif")


def test_every_curated_scene_sits_in_one_tile_and_an_edge_on_a_boundary_stays():
    """Five curated scenes sit inside one tile; the Grand Canyon crop
    (35.98 N) crosses the 36 N tile edge and mosaics two (measured)."""
    for key, location in LOCATIONS.items():
        expected = 2 if key == "grand_canyon" else 1
        assert len(tiles_for_bbox(location.bbox)) == expected, key
    assert tiles_for_bbox(LOCATIONS["grand_canyon"].bbox) == ("N33W114", "N36W114")
    # Everest's east edge is exactly 87.00: the tile below it, not E087.
    assert tiles_for_bbox(LOCATIONS["everest"].bbox) == ("N27E084",)
    # A bbox that crosses 39 N touches two tiles.
    assert tiles_for_bbox((38.99, 39.01, -119.99, -119.97)) == ("N36W120", "N39W120")


def test_the_legend_is_the_eleven_classes_as_stated():
    assert {c.code: c.key for c in LEGEND} == LEGEND_AS_STATED
    assert LEGEND_CODES == (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
    assert WEIGHT_KEYS[-1] == NODATA_KEY and len(WEIGHT_KEYS) == 12


# -- the fraction arithmetic -----------------------------------------------

def test_weights_are_255_times_the_fraction_with_the_largest_remainder():
    """A 3 x 3 block split 4 / 3 / 2: 113.33, 85, 56.67 -> floors 113, 85,
    56 sum to 254; the unit goes to the largest remainder: 113, 85, 57."""
    counts = {key: np.zeros((1, 1), dtype=np.int64) for key in WEIGHT_KEYS}
    counts["tree_cover"][:] = 4
    counts["grassland"][:] = 3
    counts["permanent_water"][:] = 2
    weights = weightmaps(counts, 3)
    assert int(weights["tree_cover"][0, 0]) == 113
    assert int(weights["grassland"][0, 0]) == 85
    assert int(weights["permanent_water"][0, 0]) == 57
    assert sum(int(w[0, 0]) for w in weights.values()) == 255


def test_random_partitions_sum_to_exactly_255_and_stay_within_one_count():
    rng = np.random.default_rng(7)
    cells = 2000
    parts = rng.multinomial(9, np.full(12, 1 / 12), size=cells)   # (cells, 12)
    counts = {key: parts[:, i].reshape(cells, 1) for i, key in enumerate(WEIGHT_KEYS)}
    weights = weightmaps(counts, 3)
    stack = np.stack([weights[key] for key in WEIGHT_KEYS]).astype(np.int64)
    assert np.all(stack.sum(axis=0) == 255)
    for i, key in enumerate(WEIGHT_KEYS):
        exact = parts[:, i].reshape(cells, 1) * 255.0 / 9.0
        assert np.all(np.abs(weights[key].astype(np.float64) - exact) < 1.0), key


def test_weight_counts_count_fine_cells_per_block():
    fine = np.zeros((6, 6), dtype=np.uint8)
    fine[:3, :3] = 10
    fine[0, 3] = 30
    counts = weight_counts(fine, 3)
    assert counts["tree_cover"].tolist() == [[9, 0], [0, 0]]
    assert counts["grassland"].tolist() == [[0, 1], [0, 0]]
    assert counts[NODATA_KEY].tolist() == [[0, 8], [9, 9]]


# -- rasterising a synthetic COG onto a synthetic bake ---------------------

def test_aligned_bake_gets_exact_quadrant_fractions_and_pure_cells(tmp_path, quadrant_source):
    """The bake grid is the source grid subdivided: every cell is one class
    (255 / 0), the scene is exactly a quarter of each quadrant class, and
    the JSON says so."""
    cells = SIZE // 3
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, cells, cells)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path,
                               source_4326=quadrant_source)
    assert scene_dir == tmp_path / "aligned_landcover"
    weights = read_weights(scene_dir)
    assert all(w.shape == (cells, cells) for w in weights.values())
    assert doc["fractions"]["tree_cover"] == 0.25
    assert doc["fractions"]["grassland"] == 0.25
    assert doc["fractions"]["bare_sparse"] == 0.25
    assert doc["fractions"]["permanent_water"] == 0.25
    assert doc["nodata_fraction"] == 0.0 and doc["coverage"] == 1.0
    half = cells // 2
    assert np.all(weights["tree_cover"][:half, :half] == 255)
    assert np.all(weights["tree_cover"][half:, :] == 0)
    assert np.all(weights["permanent_water"][half:, half:] == 255)
    assert np.all(weights["grassland"][:half, half:] == 255)
    assert np.all(weights["bare_sparse"][half:, :half] == 255)
    from PIL import Image
    majority = np.asarray(Image.open(scene_dir / "class_map.png"))
    assert int(majority[0, 0]) == 10 and int(majority[-1, -1]) == 80
    assert doc["verification_vs_source"] == {"samples": 400, "agreement": 1.0, "ok": True}


def test_boundary_through_a_cell_gives_the_exact_thirds(tmp_path, quadrant_source):
    """The bake origin one source pixel east of the source's: the class
    boundary falls one fine column into bake column 9, so that column
    holds 6 of 9 cells of the west class (170) and 3 of the east (85).
    The expected weights are re-derived here from the source array."""
    cells = (SIZE - 1) // 3          # 19 columns of 3 stay inside the source
    bake = write_bake(tmp_path, "shifted", "EPSG:4326", LON0 + PIXEL_DEG, LAT0,
                      3 * PIXEL_DEG, cells, SIZE // 3)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path,
                               source_4326=quadrant_source)
    weights = read_weights(scene_dir)
    fine = quadrant_classes()[:, 1:1 + 3 * cells]
    for code, key in LEGEND_AS_STATED.items():
        expected = (fine == code).reshape(SIZE // 3, 3, cells, 3).sum(axis=(1, 3))
        expected = np.rint(expected * 255.0 / 9.0).astype(np.int64)
        assert np.array_equal(weights[key].astype(np.int64), expected), key
    assert int(weights["tree_cover"][0, 9]) == 170
    assert int(weights["grassland"][0, 9]) == 85
    assert doc["fractions"]["tree_cover"] == pytest.approx((fine == 10).mean())
    assert doc["fractions"]["grassland"] == pytest.approx((fine == 30).mean())


def test_utm_bake_sums_to_255_per_cell_and_lands_near_the_quadrants(tmp_path, quadrant_source):
    """A projected grid (UTM 11 N) over the source centre: fractions near a
    quarter each (the grids are not aligned, so not exact), every cell's
    weights summing to exactly 255, nothing outside the source."""
    from pyproj import Transformer

    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32611", always_xy=True)
    cx, cy = to_utm.transform(LON0 + 30 * PIXEL_DEG, LAT0 - 30 * PIXEL_DEG)
    bake = write_bake(tmp_path, "utm", "EPSG:32611", cx - 180.0, cy + 180.0,
                      30.0, 12, 12)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path,
                               source_4326=quadrant_source)
    weights = read_weights(scene_dir)
    stack = np.stack([weights[key] for key in WEIGHT_KEYS]).astype(np.int64)
    assert np.all(stack.sum(axis=0) == 255)
    assert doc["weight_sum_per_cell"] == {"min": 255, "max": 255, "expected": 255}
    for key in ("tree_cover", "grassland", "bare_sparse", "permanent_water"):
        assert abs(doc["fractions"][key] - 0.25) < 0.05, (key, doc["fractions"])
    assert doc["nodata_fraction"] == 0.0
    assert doc["grid"]["crs"] == "EPSG:32611" and doc["grid"]["texels_per_cell"] == 3
    assert doc["grid"]["texel_size_m"] == 10.0
    lat_min, lat_max, lon_min, lon_max = bbox_for_grid(read_grid(bake))
    assert lat_min < LAT0 - 30 * PIXEL_DEG < lat_max
    assert lon_min < LON0 + 30 * PIXEL_DEG < lon_max


# -- the JSON and the record ------------------------------------------------

def test_landcover_json_carries_the_record_the_sha256_the_licence_and_the_attribution(tmp_path, quadrant_source):
    from core.terrain.glo30 import sha256_of

    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path,
                               source_4326=quadrant_source)
    on_disk = json.loads((scene_dir / "landcover.json").read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["sha256"] == sha256_of(quadrant_source)
    assert doc["license"] == "CC BY 4.0"
    assert "requires attribution" in doc["license_note"]
    assert doc["attribution"] == REQUIRED_ATTRIBUTION
    assert "doi:10.5281/zenodo.7254221" in doc["citation"]
    assert doc["posting_m_nominal"] == 10.0 and doc["posting_deg"] == PIXEL_DEG
    assert [c["code"] for c in doc["classes"]] == list(LEGEND_CODES)
    for entry in doc["classes"]:
        assert (scene_dir / entry["file"]).is_file()
        assert doc["weightmaps"][entry["key"]]["sha256"] == sha256_of(scene_dir / entry["file"])
    assert set(doc["grid"]) >= {"crs", "origin_x_m", "origin_y_m", "cell_size_m",
                                "width", "height", "bake_sha256", "aligned_to_bake",
                                "texels_per_cell", "texel_size_m"}
    assert doc["grid"]["bake_sha256"] == Heightfield.read(bake).digest()

    block = doc["applied_variables"]
    assert block["record_version"] == RECORD_VERSION
    (record,) = read_records(block)
    assert record["name"] == "scene.landcover"
    assert record["source"] == "derived"
    assert record["model_name"] == "ESA WorldCover v200 2021 majority/fraction"
    for key in ("name", "value", "unit", "source", "model_name", "parameters",
                "references", "properties_written", "telemetry_columns",
                "frame_keys", "null_test", "not_claimed"):
        assert key in record, key
    assert record["properties_written"] == [] and record["frame_keys"] == []
    assert record["parameters"]["fractions"] == doc["fractions"]
    assert record["parameters"]["source_sha256"] == doc["sha256"]
    null = record["null_test"]
    assert null["with"] == 0.25 and null["without"] == pytest.approx(1 / 11)
    assert null["difference"] == pytest.approx(0.25 - 1 / 11)
    assert null["ok"] is True and null["threshold"] == 0.05
    assert any("engine" in line for line in record["not_claimed"])
    assert doc["dominant_class"] == record["value"] == "tree_cover"
    # The licence travels inside the record, so a manifest that lifts the
    # record carries the attribution with it.
    assert record["parameters"]["license"] == "CC BY 4.0"
    assert record["parameters"]["attribution"] == REQUIRED_ATTRIBUTION


def test_landcover_records_lifts_the_json_record_for_a_bake_and_nothing_for_none(tmp_path, quadrant_source):
    """The manifest builder's hook: the record beside a bake, re-typed
    from the JSON verbatim; an empty list (not a zero record) for a bake
    with no land cover, and it composes with the geoid record."""
    from core.records import records_block
    from core.terrain.geoid import flat_datum_block, undulation_variable
    from core.terrain.landcover import landcover_records, scene_dir_for

    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    assert landcover_records(bake) == []
    assert landcover_records(None) == []
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path,
                               source_4326=quadrant_source)
    assert scene_dir == scene_dir_for(bake)
    (record,) = landcover_records(bake)
    assert record.to_dict() == doc["applied_variables"]["applied_variables"][0]
    assert record.null_test is not None and record.null_test.ok
    block = records_block([undulation_variable(flat_datum_block(600.0)), record])
    assert [r["name"] for r in read_records(block)] == [
        "scene.geoid_undulation_m", "scene.landcover"]


# -- refusals by name --------------------------------------------------------

def test_a_file_that_is_not_a_raster_refuses_by_name(tmp_path):
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    garbage = tmp_path / "garbage.tif"
    garbage.write_bytes(b"not a GeoTIFF at all" * 64)
    with pytest.raises(LandcoverError) as info:
        rasterise(bake, tmp_path / "cache", tmp_path, source_4326=garbage)
    assert name_of(info.value) == "terrain.landcover"
    assert str(info.value).startswith("terrain.landcover: ")
    assert not (tmp_path / "aligned_landcover" / "landcover.json").exists()


def test_values_outside_the_legend_refuse_by_name(tmp_path):
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    classes = quadrant_classes()
    classes[5, 5] = 37
    bad = write_source(tmp_path / "bad.tif", LON0, LAT0, classes)
    with pytest.raises(LandcoverError) as info:
        rasterise(bake, tmp_path / "cache", tmp_path, source_4326=bad)
    assert name_of(info.value) == "terrain.landcover"
    assert "outside the WorldCover legend: [37]" in str(info.value)


def test_a_rasterisation_that_disagrees_with_its_source_refuses_by_name(tmp_path, quadrant_source, monkeypatch):
    """The verifier pushes texels back to the source: a row-flipped result
    disagrees on most texels, is graded not ok, and rasterise refuses."""
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    grid = read_grid(bake)
    honest = landcover.reproject_classes(quadrant_source, grid, 3)
    flipped = honest[::-1, :].copy()
    assert verify_against_source(honest, grid, 3, quadrant_source)["ok"]
    report = verify_against_source(flipped, grid, 3, quadrant_source)
    assert not report["ok"] and report["agreement"] < 0.6

    monkeypatch.setattr(landcover, "reproject_classes", lambda *a, **k: flipped)
    with pytest.raises(LandcoverError) as info:
        rasterise(bake, tmp_path / "cache", tmp_path, source_4326=quadrant_source)
    assert name_of(info.value) == "terrain.landcover"
    assert info.value.reason == "unverified"


def test_a_sidecar_without_the_grid_refuses_by_name(tmp_path, quadrant_source):
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    sidecar = bake.with_suffix(".json")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    del meta["georeference"]["origin_x_m"]
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(LandcoverGridError) as info:
        rasterise(bake, tmp_path / "cache", tmp_path, source_4326=quadrant_source)
    assert name_of(info.value) == "terrain.landcover_grid"
    assert "origin_x_m" in str(info.value)
    sidecar.unlink()
    with pytest.raises(LandcoverGridError) as info:
        read_grid(bake)
    assert name_of(info.value) == "terrain.landcover_grid"


# -- the fetch path, offline: cached whole tiles, mosaic, refusals ---------

def test_fetch_reads_cached_tiles_mosaics_across_a_boundary_and_records_provenance(tmp_path):
    """Two synthetic tiles under their bucket names in the cache dir (no
    network): the crop straddles 39 N, the north half from N39W120, the
    south from N36W120, both sha256'd in the provenance."""
    from core.terrain.glo30 import sha256_of

    cache = tmp_path / "cache"
    cache.mkdir()
    south = write_source(landcover.tile_path(cache, "N36W120"), -120.0, 39.0,
                         np.full((240, 480), 30, np.uint8))
    north = write_source(landcover.tile_path(cache, "N39W120"), -120.0, 42.0,
                         np.full((36000, 480), 80, np.uint8))
    location = aligned_location("straddle", (38.99, 39.01, -119.99, -119.97))
    provenance = fetch(location, cache)
    assert set(provenance["tiles"]) == {"N36W120", "N39W120"}
    for stem, path in (("N36W120", south), ("N39W120", north)):
        assert provenance["tiles"][stem]["read"] == "cached whole tile"
        assert provenance["tiles"][stem]["sha256"] == sha256_of(path)
    crop = Path(provenance["path"])
    assert provenance["sha256"] == sha256_of(crop)
    assert provenance["license"] == "CC BY 4.0"
    assert provenance["attribution"] == REQUIRED_ATTRIBUTION
    import rasterio
    with rasterio.open(crop) as src:
        values = src.read(1)
        assert src.crs.to_epsg() == 4326 and src.transform.a == PIXEL_DEG
        assert (src.transform.c, src.transform.f) == pytest.approx((-119.99, 39.01))
    assert values.shape == (240, 240)
    assert np.all(values[:120] == 80) and np.all(values[120:] == 30)
    # A second call is the cache: the same provenance, no re-read.
    assert fetch(location, cache) == provenance

    # And the whole pipeline through it: an aligned bake over the crop is
    # half water, half grass.
    bake = write_bake(tmp_path, "straddle", "EPSG:4326", -119.99, 39.01,
                      3 * PIXEL_DEG, 80, 80)
    scene_dir, doc = rasterise(location, cache, tmp_path, bake_path=bake)
    assert doc["fractions"]["permanent_water"] == 0.5
    assert doc["fractions"]["grassland"] == 0.5
    assert doc["source"]["tiles"] == provenance["tiles"]


def test_a_cached_tile_that_is_not_the_product_refuses_by_name(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    location = aligned_location("probe", (38.99, 38.995, -119.995, -119.99))
    # Garbage under the tile's name: unreadable.
    landcover.tile_path(cache, "N36W120").write_bytes(b"\x00" * 4096)
    with pytest.raises(LandcoverError) as info:
        fetch(location, cache)
    assert name_of(info.value) == "terrain.landcover"
    # A valid raster with the wrong posting: not the product.
    import rasterio
    from rasterio.transform import from_origin
    with rasterio.open(landcover.tile_path(cache, "N36W120"), "w", driver="GTiff",
                       height=30, width=30, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(-120.0, 39.0, 0.1, 0.1)) as dst:
        dst.write(np.full((30, 30), 10, np.uint8), 1)
    with pytest.raises(LandcoverError) as info:
        fetch(location, cache)
    assert name_of(info.value) == "terrain.landcover"
    assert "not a WorldCover tile" in str(info.value)


# -- the network, one window, skipped by name when unreachable --------------

def test_one_real_tile_window_carries_legend_values_and_its_digest(tmp_path):
    """A 0.02 degree window around Half Dome from the real N36W120 tile
    through /vsicurl/: every value in the legend, the crop's sha256
    recorded, the bucket's ETag beside it. Skipped by name when the bucket
    is unreachable; the measurement is then NOT made here."""
    location = aligned_location("halfdome", (37.735, 37.755, -119.545, -119.525))
    try:
        provenance = fetch(location, tmp_path / "cache")
    except LandcoverError as exc:
        if exc.reason != "unreachable":
            raise
        pytest.skip(f"network refused: fetching the WorldCover N36W120 window "
                    f"failed ({exc}); the real-tile measurements were NOT made here")
    from core.terrain.glo30 import sha256_of
    import rasterio

    tile = provenance["tiles"]["N36W120"]
    assert tile["read"] == "vsicurl window"
    assert tile["window"] == {"col_off": 5460, "row_off": 14940, "width": 240, "height": 240}
    assert tile["content_length"] == 115482414
    assert tile["etag"] is not None
    crop = Path(provenance["path"])
    assert provenance["sha256"] == sha256_of(crop)
    with rasterio.open(crop) as src:
        values = src.read(1)
    seen = {int(v) for v in np.unique(values)}
    assert seen and seen <= set(LEGEND_CODES) | {0}, seen
    # Half Dome's window is granite and forest, measured 2026-09-28.
    assert {10, 60} <= seen


# -- the script ---------------------------------------------------------------

def run_script(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, cwd=str(REPO))


def test_the_script_writes_the_scene_and_prints_the_attribution(tmp_path, quadrant_source):
    """With the bake-grid maps (I7), the script writes the Landscape-
    resolution layers, the Landscape heightmap and the import manifest
    carrying the bake's datum (W1), and prints the measured round trip."""
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3, datum=True)
    result = run_script("--location", "aligned", "--cache", str(tmp_path / "cache"),
                        "--out", str(tmp_path), "--bake", str(bake),
                        "--source", str(quadrant_source))
    assert result.returncode == 0, result.stdout + result.stderr
    assert REQUIRED_ATTRIBUTION in result.stdout
    assert "Tree cover" in result.stdout and "25.00 %" in result.stdout
    scene_dir = tmp_path / "aligned_landcover"
    assert (scene_dir / "landcover.json").is_file()
    assert result.stdout.isascii()
    # W1: the Landscape half beside the bake-grid maps.
    assert "Landscape layers 12 x 127x127" in result.stdout
    assert "argmax round trip" in result.stdout and "import manifest" in result.stdout
    assert "W5 (Windows)" in result.stdout
    assert (scene_dir / "aligned_landcover_layers.json").is_file()
    assert (scene_dir / "aligned_landcover_10.u8").stat().st_size == 127 * 127
    manifest = json.loads((scene_dir / "aligned_landscape.json").read_text(encoding="utf-8"))
    assert len(manifest["weight_layers"]) == 12
    assert manifest["datum"]["vertical_datum_of_heights"].startswith("synthesised heightfield")
    assert manifest["bake"]["sha256"] == Heightfield.read(bake).digest()
    assert (scene_dir / "aligned_landscape.r16").stat().st_size == 127 * 127 * 2


def test_the_script_refuses_the_landscape_manifest_for_a_bake_without_a_datum(tmp_path, quadrant_source):
    """A bake without its datum block writes its bake-grid maps and then
    refuses terrain.landscape_missing by name (exit 1): a Landscape whose
    heights state no datum is the P10 error again. --no-landscape keeps
    the bake-grid-only behaviour (exit 0, no layer written)."""
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    result = run_script("--location", "aligned", "--cache", str(tmp_path / "cache"),
                        "--out", str(tmp_path), "--bake", str(bake),
                        "--source", str(quadrant_source))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "REFUSED -- terrain.landscape_missing:" in result.stdout
    assert (tmp_path / "aligned_landcover" / "landcover.json").is_file()
    assert not (tmp_path / "aligned_landcover" / "aligned_landscape.json").is_file()
    result = run_script("--location", "aligned", "--cache", str(tmp_path / "cache"),
                        "--out", str(tmp_path), "--bake", str(bake),
                        "--source", str(quadrant_source), "--no-landscape")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Landscape layers" not in result.stdout
    assert not (tmp_path / "aligned_landcover" / "aligned_landcover_layers.json").is_file()


def test_the_script_refuses_by_name_and_exits_one(tmp_path, quadrant_source):
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3)
    garbage = tmp_path / "garbage.tif"
    garbage.write_bytes(b"\x00" * 1024)
    result = run_script("--location", "aligned", "--cache", str(tmp_path / "cache"),
                        "--out", str(tmp_path), "--bake", str(bake),
                        "--source", str(garbage))
    assert result.returncode == 1
    assert "REFUSED -- terrain.landcover: " in result.stdout
    result = run_script("--location", "nowhere", "--cache", str(tmp_path / "cache"),
                        "--out", str(tmp_path), "--bake", str(tmp_path / "nowhere.r16"),
                        "--source", str(quadrant_source))
    assert result.returncode == 1
    assert "REFUSED -- terrain.landcover_grid: " in result.stdout
    result = run_script("--location", "nowhere", "--cache", str(tmp_path / "cache"),
                        "--out", str(tmp_path))
    assert result.returncode == 2


# -- the culture ---------------------------------------------------------------

def test_the_verifier_never_imports_the_landcover_producer():
    text = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    assert "landcover" not in text


def test_everything_the_engine_or_a_reader_sees_is_ascii(tmp_path, quadrant_source):
    for rel in ("core/terrain/landcover.py", "scripts/bake_landcover.py",
                "tests/test_landcover.py", "core/terrain/weightmaps.py",
                "core/environment/surface.py",
                "tests/test_weightmaps.py", "tests/test_surface_inference.py"):
        assert (REPO / rel).read_text(encoding="utf-8").isascii(), rel
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, SIZE // 3, SIZE // 3, datum=True)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path,
                               source_4326=quadrant_source)
    assert (scene_dir / "landcover.json").read_text(encoding="utf-8").isascii()
    from core.terrain.weightmaps import export_layers

    sidecar, _ = export_layers(scene_dir)
    assert sidecar.read_text(encoding="utf-8").isascii()
    assert all(name.isascii() for name in (p.name for p in scene_dir.iterdir()))
