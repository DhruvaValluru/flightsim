"""P10 / D1, the vertical datum: the EGM96 and EGM2008 geoid grids, the
bilinear and cubic undulations, the .gtx crop, the datum block on the
bake sidecar, the run card and the capture manifest, the applied-variable
record, and the verifier's independent re-checks.

Every number asserted here was measured in the container on 2026-09-28
(phase3_facts.md, the D1 report): the six curated origins' undulations
from the GeographicLib egm96-15 and egm2008-5 grids, the (0, 0) check
values, the headers' bounds. The EGM2008 grid is NOT committed (18.7 MB;
data/geoid is the bake cache): the tests that need it skip by name when
the cache lacks it and ran here with it present; every EGM96 test runs
everywhere. The verifier clauses are tested against
``core.capture.verify`` once the integrator has applied the patch, and
until then against the SAME text carried verbatim in
``VERIFY_DATUM_PATCH`` below (executed here with the verifier's own
``Check`` type); a test pins the applied functions to that text (or to
the landed batch-1 text, by sha256, until the D1 patch lands) so the two
cannot drift.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.messages import name_of
from core.records import RECORD_VERSION, read_records
from core.terrain import geoid
from core.terrain.geoid import (
    BAKE_DATUM, EGM2008_GRID_PATH, EGM2008_GRID_SHA256, FLAT_DATUM, GRID_PATH,
    GRID_SHA256, SYNTHESISED_DATUM, DatumError, GeoidError, datum_block,
    datum_for_heightfield, flat_datum_block, load_egm2008, load_grid, read_gtx,
    undulation, undulation_variable, write_gtx, write_gtx_bundle,
)
from core.terrain.heightfield import Georeference, Heightfield

REPO = Path(__file__).resolve().parents[1]

#: (lat, lon, N) measured from the same grid with the probe reader.
MEASURED = {
    "matterhorn": (46.005, 7.72, 52.52),
    "yosemite": (37.7275, -119.61, -25.94),
    "fuji": (35.42, 138.7274, 41.47),
    "everest": (27.90, 86.87, -29.84),
    "grand_canyon": (36.09, -112.0, -23.40),
    "flint_hills": (38.43, -96.60, -30.54),
}


# -- the grid --------------------------------------------------------------

def test_the_committed_grid_is_the_measured_one():
    """The file under assets/geoid is byte-for-byte the grid every number
    in this file was measured from: 2,076,888 bytes, the recorded
    sha256, 1440 x 721 samples, and the header's own bilinear bound."""
    assert GRID_PATH.is_file(), GRID_PATH
    assert GRID_PATH.stat().st_size == 2076888
    assert hashlib.sha256(GRID_PATH.read_bytes()).hexdigest() == GRID_SHA256
    grid = load_grid()
    assert (grid.width, grid.height) == (1440, 721)
    assert grid.offset_m == -108.0 and grid.scale_m == 0.003
    assert grid.max_bilinear_error_m == 1.152
    assert grid.description == "WGS84 EGM96, 15-minute grid"


def test_readme_records_source_sha256_and_licence():
    text = (REPO / "assets" / "geoid" / "README.md").read_text(encoding="utf-8")
    assert GRID_SHA256 in text
    assert geoid.TARBALL_SHA256 in text
    assert "sourceforge.net/projects/geographiclib" in text
    assert "public domain" in text and "MIT/X11" in text
    assert text.isascii()


def test_six_curated_origins_reproduce_the_measured_undulations():
    """The numbers the gap was measured with, to 0.01 m; and each origin
    is the curated location's own (glo30.LOCATIONS), not a copy."""
    from core.terrain.glo30 import LOCATIONS

    for key, (lat, lon, expected) in MEASURED.items():
        assert (LOCATIONS[key].origin_lat, LOCATIONS[key].origin_lon) == (lat, lon)
        assert undulation(lat, lon) == pytest.approx(expected, abs=0.01), key


def test_origin_of_the_graticule_is_the_known_value():
    assert undulation(0.0, 0.0) == pytest.approx(17.16, abs=0.05)


def test_interpolation_is_bilinear_not_nearest():
    """At a cell centre the bilinear value is the mean of the four nodes,
    and in the Alps the four differ by metres, so a nearest-neighbour
    reader returns one node and misses by more than the tolerance."""
    grid = load_grid()
    # The cell whose corners are (45.25 N, 7.0 E), (45.25, 7.25), (45.0,
    # 7.0), (45.0, 7.25): centre at (45.125, 7.125).
    iy, ix = int((90.0 - 45.25) * 4), int(7.0 * 4)
    nodes = [grid.offset_m + grid.scale_m * float(grid.values[r, c])
             for r in (iy, iy + 1) for c in (ix, ix + 1)]
    centre = undulation(45.125, 7.125)
    assert centre == pytest.approx(sum(nodes) / 4.0, abs=1e-9)
    assert all(abs(centre - node) > 0.02 for node in nodes), nodes
    # And along one edge it is the two-node mean, so the weights are the
    # bilinear ones and not a quirk of the centre.
    edge = undulation(45.25, 7.125)
    assert edge == pytest.approx((nodes[0] + nodes[1]) / 2.0, abs=1e-9)


def test_longitude_wraps_and_the_poles_are_reachable():
    assert undulation(10.0, -10.0) == pytest.approx(undulation(10.0, 350.0), abs=1e-12)
    assert math.isfinite(undulation(90.0, 0.0)) and math.isfinite(undulation(-90.0, 123.0))
    with pytest.raises(GeoidError):
        undulation(91.0, 0.0)


# -- refusals by name --------------------------------------------------------

def test_a_corrupted_grid_byte_refuses_by_name(tmp_path):
    """One flipped sample byte: the sha256 check refuses terrain.geoid.
    Unchecked, the same file would answer with a different number near
    the flipped node -- which is why the check is not optional."""
    corrupt = tmp_path / "egm96-15.pgm"
    data = bytearray(GRID_PATH.read_bytes())
    # The sample of node (row for 46.0 N, column for 7.75 E), high byte.
    header_end = len(data) - 1440 * 721 * 2
    index = header_end + 2 * (int((90.0 - 46.0) * 4) * 1440 + int(7.75 * 4))
    data[index] ^= 0x10
    corrupt.write_bytes(bytes(data))
    with pytest.raises(GeoidError) as info:
        load_grid(corrupt)
    assert name_of(info.value) == "terrain.geoid"
    assert "sha256" in str(info.value)
    unchecked = load_grid(corrupt, expected_sha256=None)
    assert abs(unchecked.undulation(46.005, 7.72) - undulation(46.005, 7.72)) > 1.0


def test_an_absent_grid_refuses_by_name(tmp_path):
    with pytest.raises(GeoidError) as info:
        load_grid(tmp_path / "nowhere.pgm")
    assert name_of(info.value) == "terrain.geoid"
    assert "absent" in str(info.value)


def test_a_file_that_is_not_a_geoid_pgm_refuses_by_name(tmp_path):
    bad = tmp_path / "bad.pgm"
    bad.write_bytes(b"P5\n# Origin 90N 0E\n2 2\n65535\n" + b"\x00" * 8)
    with pytest.raises(GeoidError) as info:
        load_grid(bad, expected_sha256=None)
    assert name_of(info.value) == "terrain.geoid"


# -- the datum block ---------------------------------------------------------

DATUM_KEYS = (
    "vertical_datum_of_heights", "geoid_model", "origin_lat_deg",
    "origin_lon_deg", "undulation_m", "undulation_source",
    "bilinear_error_bound_m", "model_difference_bound_m",
    "model_difference_basis", "model_difference_at_origin_m",
    "orthometric_height_of_origin_m", "ellipsoidal_height_of_origin_m", "note",
)


def test_datum_block_states_the_datum_the_model_the_bounds_and_the_shift():
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    assert set(DATUM_KEYS) <= set(block)
    assert block["vertical_datum_of_heights"] == BAKE_DATUM
    assert block["geoid_model"] == "EGM96 15-minute grid (GeographicLib egm96-15)"
    assert block["undulation_m"] == pytest.approx(52.52, abs=0.01)
    assert block["ellipsoidal_height_of_origin_m"] == pytest.approx(2400.0 + block["undulation_m"])
    assert block["bilinear_error_bound_m"] == 1.152
    assert block["model_difference_bound_m"] == 13.7
    assert block["model_difference_at_origin_m"] == pytest.approx(2.231)
    assert block["undulation_source"]["sha256"] == GRID_SHA256
    assert block["undulation_source"]["file"] == "assets/geoid/egm96-15.pgm"
    assert block["undulation_source"]["interpolation"] == "bilinear"
    assert "ellipsoidal = altitude + undulation_m" in block["note"]
    # An origin nobody measured EGM2008 at says null, not a guess; the live
    # difference rides beside it only when the EGM2008 grid is cached.
    elsewhere = datum_block(10.0, 10.0, 0.0)
    assert elsewhere["model_difference_at_origin_m"] is None
    live = elsewhere["egm2008_minus_egm96_at_origin_m"]
    assert (isinstance(live, float) and abs(live) < 13.7) if EGM2008_GRID_PATH.is_file() else live is None


def test_the_model_difference_bound_covers_every_measured_value():
    """The stated bound is the measured node maximum plus both grids'
    bilinear bounds; every per-origin measurement sits well inside it."""
    assert geoid.MODEL_DIFFERENCE_BOUND_M >= (
        geoid.MODEL_DIFFERENCE_MAX_AT_NODES_M + 1.152 + 0.478)
    assert all(abs(v) < geoid.MODEL_DIFFERENCE_BOUND_M
               for v in geoid.EGM2008_MINUS_EGM96_AT_ORIGIN_M.values())
    assert set(geoid.EGM2008_MINUS_EGM96_AT_ORIGIN_M) == set(MEASURED)


def _heightfield(provenance, crs="EPSG:32632", origin=(400500.0, 5096000.0),
                 base=2400.0):
    """A 16 x 16, 90 m raster; the default origin puts the Matterhorn
    scene origin (46.005 N, 7.72 E -> 400896, 5095399 in EPSG:32632)
    inside it."""
    z = base + np.arange(16 * 16, dtype=np.float64).reshape(16, 16) * 0.5
    return Heightfield.from_elevations(
        z, Georeference(crs, origin[0], origin[1], 90.0), name="matterhorn",
        provenance=provenance)


def test_datum_for_a_sidecar_that_carries_the_block_is_copied_not_recomputed():
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    block["undulation_m"] = 99.0   # a marker: the copy is verbatim
    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72,
                          "datum": block})
    assert datum_for_heightfield(field) == block


def test_datum_for_a_bake_from_before_the_block_is_evaluated_at_its_origin():
    """A sidecar with an origin and no block: N is evaluated there and
    the orthometric height is the raster's at the projected origin."""
    from pyproj import Transformer

    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72})
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:32632",
                                always_xy=True).transform(7.72, 46.005)
    assert field.contains(x, y)
    block = datum_for_heightfield(field)
    assert block["undulation_m"] == pytest.approx(52.52, abs=0.01)
    assert block["orthometric_height_of_origin_m"] == pytest.approx(field.elevation_at(x, y))
    assert block["model_difference_at_origin_m"] == pytest.approx(2.231)


def test_a_synthesised_heightfield_and_a_flat_slab_say_so_with_null_not_zero():
    synthesised = datum_for_heightfield(_heightfield({"generator": "ridge"}))
    assert synthesised["vertical_datum_of_heights"] == SYNTHESISED_DATUM
    assert synthesised["undulation_m"] is None
    flat = flat_datum_block(600.0)
    assert flat["vertical_datum_of_heights"] == FLAT_DATUM
    assert flat["undulation_m"] is None and flat["terrain_elevation_m"] == 600.0
    assert "no geoid undulation applies" in flat["note"]


# -- the bake sidecar ----------------------------------------------------------

def _synthetic_tile(path, lat0, lon0):
    """The same 0.2 x 0.2 degree smooth-mountain tile tests/test_phase6b.py
    ingests: peak 3000 m at (lat0 + 0.1, lon0 + 0.1)."""
    from core.terrain.dem import write_geotiff

    n = 240
    lats = np.linspace(lat0 + 0.2, lat0, n)
    lons = np.linspace(lon0, lon0 + 0.2, n)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    distance = np.hypot((lat_grid - (lat0 + 0.1)) * 111e3,
                        (lon_grid - (lon0 + 0.1)) * 78e3)
    z = 800.0 + 2200.0 * np.exp(-(distance / 6500.0) ** 2)
    return write_geotiff(path, z.astype(np.float32), "EPSG:4326",
                         lon0, lat0 + 0.2, 0.2 / n)


def test_bake_sidecar_carries_the_datum_block(tmp_path, monkeypatch):
    """The whole bake (mosaic, ingest, verify, summit check, write) with
    the fetch replaced by a synthetic tile: the sidecar's provenance
    carries the block, evaluated at the location's origin."""
    from core.terrain import glo30

    location = glo30.Location(
        key="testpeak", title="synthetic test peak", tiles=("X",),
        bbox=(45.82, 45.98, 7.02, 7.18), crs="EPSG:32632",
        origin_lat=45.9, origin_lon=7.1, snowline_m=2500.0,
        summits=(("Test Peak", 45.9, 7.1, 3000.0),))

    def fake_fetch(loc, cache_dir):
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return [_synthetic_tile(glo30.tile_path(cache_dir, "X"), 45.8, 7.0)]

    monkeypatch.setattr(glo30, "fetch", fake_fetch)
    raw, report = glo30.bake(location, tmp_path / "cache", tmp_path / "out",
                             ground_sample_distance_m=90.0, geoid_model="EGM96")
    assert report["ok"]
    sidecar = json.loads(raw.with_suffix(".json").read_text(encoding="utf-8"))
    datum = sidecar["provenance"]["datum"]
    assert set(DATUM_KEYS) <= set(datum)
    assert datum["undulation_m"] == undulation(45.9, 7.1)
    assert datum["geoid_model_key"] == "EGM96" and datum["interpolation"] == "bilinear"
    # D1: the crop and its samples beside the raster, named from the sidecar.
    files = sidecar["provenance"]["geoid_files"]
    assert (raw.parent / files["gtx"]).is_file() and (raw.parent / files["samples"]).is_file()
    assert datum["gtx"]["file"] == files["gtx"] == "testpeak_geoid.gtx"
    assert datum["orthometric_height_of_origin_m"] == pytest.approx(3000.0, abs=30.0)
    assert datum["ellipsoidal_height_of_origin_m"] == pytest.approx(
        datum["orthometric_height_of_origin_m"] + datum["undulation_m"])
    assert sidecar["provenance"]["vertical_datum"].startswith("EGM2008 orthometric")
    assert "treated as MSL" not in json.dumps(sidecar)
    # And the same block comes back through the reader, verbatim.
    assert datum_for_heightfield(Heightfield.read(raw)) == datum


# -- the run card ---------------------------------------------------------------

def test_orographic_block_and_run_card_carry_the_datum(tmp_path):
    from core.nl.compiler import compile_prompt
    from core.scenario.card import write_run_card
    from core.terrain.glo30 import orographic_card_block

    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72,
                          "datum": block})
    field.write(tmp_path / "matterhorn")
    orographic = orographic_card_block(tmp_path / "matterhorn", 46.005, 7.72,
                                       25.0, 270.0)
    assert orographic["datum"] == block
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    card = json.loads(write_run_card(spec, tmp_path / "card.json",
                                     orographic=orographic).read_text(encoding="utf-8"))
    assert card["datum"] == block
    # Lifted, not duplicated: the orographic block keeps exactly the keys
    # the C++ port reads.
    assert "datum" not in card["orographic"]
    assert (tmp_path / "card.json").read_text(encoding="utf-8").isascii()
    # And an explicit datum wins over none.
    card2 = json.loads(write_run_card(spec, tmp_path / "card2.json",
                                      datum=block).read_text(encoding="utf-8"))
    assert card2["datum"] == block


# -- the capture manifest -----------------------------------------------------

def _manifest(heightfield=None, terrain_elevation_m=0.0):
    from core.capture.manifest import build_capture_manifest
    from core.capture.poses import solve_pose_track
    from core.capture.schedule import solve_schedule
    from tests.test_camera_manifest import spec_with_cameras
    from tests.test_camera_poses import FRAME, make_columns

    spec = spec_with_cameras()
    columns = make_columns(duration_s=10.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(
        spec, columns, FRAME, tracks, schedules, output_digest="0" * 64,
        scene={"key": "terrain" if heightfield else "flat", "terrain": None},
        terrain_sha256=heightfield.digest() if heightfield else None,
        heightfield=heightfield, terrain_elevation_m=terrain_elevation_m)


def test_flat_manifest_carries_the_flat_block_and_an_unapplied_record():
    manifest = _manifest(terrain_elevation_m=600.0)
    assert manifest["datum"]["vertical_datum_of_heights"] == FLAT_DATUM
    assert manifest["datum"]["undulation_m"] is None
    records = read_records(manifest["applied_variables"])
    assert manifest["applied_variables"]["record_version"] == RECORD_VERSION
    (record,) = [r for r in records if r["name"] == "scene.geoid_undulation_m"]
    assert record["value"] is None and record["null_test"] is None
    assert record["source"] == "derived"
    assert "not applied" in record["model"]


def test_georeferenced_manifest_carries_the_block_and_the_record_with_its_null_test():
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72,
                          "datum": block},
                         crs="EPSG:32631", origin=(-1000.0, 1000.0))
    manifest = _manifest(field)
    assert manifest["datum"] == block
    (record,) = [r for r in read_records(manifest["applied_variables"])
                 if r["name"] == "scene.geoid_undulation_m"]
    for key in ("name", "value", "unit", "source", "model", "parameters",
                "references", "properties_written", "telemetry_columns",
                "frame_keys", "null_test", "not_claimed"):
        assert key in record, key
    assert record["value"] == pytest.approx(52.52, abs=0.01)
    assert record["unit"] == "m" and record["source"] == "derived"
    assert record["model"] == "EGM96 bilinear"
    assert record["parameters"]["grid_sha256"] == GRID_SHA256
    null = record["null_test"]
    assert null["with"] == pytest.approx(52.52, abs=0.01) and null["without"] == 0.0
    assert null["difference"] == pytest.approx(record["value"])
    assert null["threshold"] == 1.152 and null["ok"] is True
    assert any("h-sl stays ellipsoidal" in s for s in record["not_claimed"])
    # The manifest round-trips through JSON and the sidecar context has it.
    from core.capture.manifest import frame_sidecar
    reread = json.loads(json.dumps(manifest))
    assert reread["datum"] == block
    assert frame_sidecar(manifest, manifest["frames"][0])["context"]["datum"] == block


def test_the_undulation_record_refuses_a_repeated_name_through_records_block():
    from core.records import records_block

    block = datum_block(46.005, 7.72, 2400.0)
    with pytest.raises(ValueError, match="repeat"):
        records_block([undulation_variable(block), undulation_variable(block)])


# -- the verifier: independent re-evaluation -----------------------------------

#: The text returned to the integrator for core/capture/verify.py, verbatim
#: (D1: the batch-1 verify_datum extended to EGM2008 blocks, plus the
#: independent crop check datum_independent). Executed here with the
#: verifier's own Check/PASS/FAIL/NOT_RUN so the clauses are tested before
#: the patch lands; once it has, the functions in verify.py are used and
#: pinned to this text.
VERIFY_DATUM_PATCH = r'''
# -- P10 / D1: the vertical datum ---------------------------------------------

#: How far the manifest's geoid undulation may sit from the checker's own
#: re-evaluation of the same grid. Two bilinear readers of one file agree
#: to floating-point; 0.01 m catches a nearest-neighbour producer (the
#: grid's own bilinear bound is 1.152 m), a wrong origin, a wrong grid.
DATUM_TOL_M = 0.01
FAIL_DATUM = "scene.datum"
#: The committed EGM96 grid the checker reads for itself (assets/geoid),
#: and the EGM2008 grid of the bake cache (data/geoid; not committed, so
#: an EGM2008 block is NOT RUN here when the cache lacks it -- the crop
#: check below covers it from the bake's own files).
DATUM_GRID = Path(__file__).resolve().parents[2] / "assets" / "geoid" / "egm96-15.pgm"
DATUM_GRID_EGM2008 = Path(__file__).resolve().parents[2] / "data" / "geoid" / "egm2008-5.pgm"
DATUM_KEYS = (
    "vertical_datum_of_heights", "geoid_model", "origin_lat_deg",
    "origin_lon_deg", "undulation_m", "undulation_source",
    "bilinear_error_bound_m", "model_difference_bound_m",
    "orthometric_height_of_origin_m", "ellipsoidal_height_of_origin_m", "note",
)
#: The independent evaluation of the bake's .gtx crop (PROJ vgridshift,
#: +inv so +N is read; bilinear on the nodes) against the producer's
#: bilinear values from the FULL grid: 0.01 m (measured 2e-6 m on a
#: node-aligned crop; a crop misaligned by one third of a node misses by
#: 0.06 m at the Matterhorn origin).
DATUM_INDEPENDENT_TOL_M = 0.01


def _own_undulation(path, lat_deg: float, lon_deg: float):
    """The checker's OWN GeographicLib-PGM reader (it never imports
    core.terrain.geoid): header offset/scale, big-endian uint16 samples
    from 90N 0E, bilinear on the four surrounding nodes. Returns (N in
    metres, the file's sha256)."""
    import re

    import numpy as np

    data = Path(path).read_bytes()
    match = re.match(rb"P5\s*(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s*(?:#[^\n]*\n\s*)*(\d+)\s", data)
    header = data[:match.end()].decode("ascii", "replace")
    width, height = int(match.group(1)), int(match.group(2))
    offset = float(re.search(r"# Offset (\S+)", header).group(1))
    scale = float(re.search(r"# Scale (\S+)", header).group(1))
    values = np.frombuffer(data, dtype=">u2", offset=match.end(),
                           count=width * height).reshape(height, width)
    fy = (90.0 - float(lat_deg)) * (height - 1) / 180.0
    fx = (float(lon_deg) % 360.0) * width / 360.0
    iy = min(int(math.floor(fy)), height - 2)
    ix = int(math.floor(fx)) % width
    dy, dx, ix1 = fy - iy, fx - ix, (ix + 1) % width
    value = (float(values[iy, ix]) * (1.0 - dx) * (1.0 - dy)
             + float(values[iy, ix1]) * dx * (1.0 - dy)
             + float(values[iy + 1, ix]) * (1.0 - dx) * dy
             + float(values[iy + 1, ix1]) * dx * dy)
    return offset + scale * value, hashlib.sha256(data).hexdigest()


def _datum_model(datum: Dict) -> str:
    """Which grid the block was evaluated with, from its key or, for a
    block written before the key existed, from the model's name."""
    key = datum.get("geoid_model_key")
    if key in ("EGM2008", "EGM96"):
        return key
    return "EGM2008" if "EGM2008" in str(datum.get("geoid_model")) else "EGM96"


def verify_datum(manifest: Dict) -> Check:
    """The scene's vertical datum block against the checker's own geoid.

    NOT RUN on a scene with no georeferenced heights (a flat slab or a
    synthesised ridge: ``undulation_m`` is null there, by contract), on
    a manifest written before the block existed, and on an EGM2008
    block when the checker's machine has no EGM2008 grid in its cache
    (the grid is not committed; ``datum_independent`` re-measures such
    a block from the bake's own crop). Otherwise the block must carry
    every key of DATUM_KEYS, name the grid the checker holds (by
    sha256), state a bilinear undulation within DATUM_TOL_M of the
    checker's own bilinear evaluation at the recorded origin (a block
    interpolated another way carries ``undulation_bilinear_m`` beside
    ``undulation_m``, and the two may differ by no more than the
    header's two bounds), and an ellipsoidal height equal to
    orthometric + undulation. FAIL by name (scene.datum) on any of
    these. What is NOT checked: that the heights themselves are EGM2008
    orthometric (the bake's provenance says so; no second source is
    available here), the EGM96-EGM2008 difference beyond the stated
    bound, and the cubic interpolation itself (its bound is checked,
    its arithmetic is the crop check's business).
    """
    datum = manifest.get("datum")
    if not isinstance(datum, dict):
        return Check("datum", NOT_RUN,
                     "the manifest carries no datum block (written before the "
                     "vertical datum landed); nothing to re-evaluate")
    if datum.get("undulation_m") is None:
        return Check("datum", NOT_RUN,
                     f"no georeferenced heights ({datum.get('vertical_datum_of_heights')}): "
                     f"the undulation is null by contract and there is nothing to re-evaluate")
    missing = [key for key in DATUM_KEYS if key not in datum]
    if missing:
        return Check("datum", FAIL,
                     f"the datum block lacks {missing}; a block that does not say "
                     f"where its undulation came from cannot be checked",
                     failure=FAIL_DATUM)
    model = _datum_model(datum)
    grid = DATUM_GRID_EGM2008 if model == "EGM2008" else DATUM_GRID
    if not grid.is_file():
        if model == "EGM2008":
            return Check("datum", NOT_RUN,
                         f"the block was evaluated with EGM2008 and the checker's cache "
                         f"has no EGM2008 grid ({grid}; not committed); the bake's own "
                         f"crop is re-measured by datum_independent instead")
        return Check("datum", FAIL,
                     f"the checker's own geoid grid {grid} is absent, so the "
                     f"manifest's undulation cannot be re-evaluated (see "
                     f"assets/geoid/README.md)", failure=FAIL_DATUM)
    own, digest = _own_undulation(grid, datum["origin_lat_deg"], datum["origin_lon_deg"])
    recorded = (datum.get("undulation_source") or {}).get("sha256")
    if recorded != digest:
        return Check("datum", FAIL,
                     f"the manifest's undulation came from a grid with sha256 "
                     f"{str(recorded)[:16]}..., the checker's {model} grid is {digest[:16]}...; "
                     f"two grids cannot be compared", failure=FAIL_DATUM)
    stated = float(datum["undulation_m"])
    interpolation = str(datum.get("interpolation") or "bilinear")
    bilinear = stated if interpolation == "bilinear" else datum.get("undulation_bilinear_m")
    if not isinstance(bilinear, (int, float)):
        return Check("datum", FAIL,
                     f"the block is interpolated {interpolation!r} and carries no "
                     f"undulation_bilinear_m to re-evaluate against", failure=FAIL_DATUM)
    bilinear = float(bilinear)
    if abs(bilinear - own) > DATUM_TOL_M:
        return Check("datum", FAIL,
                     f"the manifest states a bilinear undulation of {bilinear:.3f} m at "
                     f"({datum['origin_lat_deg']}, {datum['origin_lon_deg']}); the "
                     f"checker's own bilinear read of the same grid gives {own:.3f} m "
                     f"(tolerance {DATUM_TOL_M} m)", failure=FAIL_DATUM)
    if interpolation != "bilinear":
        allowed = float(datum.get("bilinear_error_bound_m") or 0.0) + float(
            datum.get("interpolation_error_bound_m") or 0.0)
        if abs(stated - bilinear) > allowed:
            return Check("datum", FAIL,
                         f"the {interpolation} undulation {stated:.3f} m sits {abs(stated - bilinear):.3f} m "
                         f"from the bilinear one {bilinear:.3f} m, beyond the header's two "
                         f"bounds ({allowed:.3f} m)", failure=FAIL_DATUM)
    ellipsoidal = float(datum["ellipsoidal_height_of_origin_m"])
    orthometric = float(datum["orthometric_height_of_origin_m"])
    if abs(ellipsoidal - (orthometric + stated)) > 1e-6:
        return Check("datum", FAIL,
                     f"ellipsoidal height {ellipsoidal:.3f} m is not orthometric "
                     f"{orthometric:.3f} m + undulation {stated:.3f} m",
                     failure=FAIL_DATUM)
    return Check("datum", PASS,
                 f"heights {datum['vertical_datum_of_heights']}; {model} {interpolation} undulation "
                 f"{stated:+.3f} m at the origin (bilinear {bilinear:+.3f} m) agrees with the "
                 f"checker's own read of the grid to {abs(bilinear - own):.4f} m; ellipsoidal "
                 f"origin {ellipsoidal:.1f} m = orthometric {orthometric:.1f} m + N")


def verify_datum_independent(manifest: Dict, run_dir=None) -> Check:
    """The bake's own geoid crop (``<stem>_geoid.gtx``, a node-aligned
    NOAA gtx of the model's nodes) evaluated by PROJ -- code this
    checker and the producer share nothing with -- against the values
    the producer recorded from the FULL grid (``<stem>_geoid.json``): the
    origin's bilinear undulation and 100 interior points, each within
    DATUM_INDEPENDENT_TOL_M, with ``+inv`` so the grid's +N is read (a
    forward pipeline reads -N and fails by 2N), the crop's header
    corner on whole nodes of its posting, and inf one node outside the
    crop. Independent of the producer's interpolation CODE, not of its
    DATA: the grid the crop was cut from is the producer's, anchored
    only by its recorded sha256. NOT RUN without a georeferenced block,
    a gtx sub-block, a bake path (``scene.terrain``) or pyproj; FAIL
    (scene.datum) on an absent or altered file, a misaligned corner, a
    residual beyond the tolerance, or a finite value outside the crop.
    """
    datum = manifest.get("datum")
    if not isinstance(datum, dict) or datum.get("undulation_m") is None:
        return Check("datum_independent", NOT_RUN,
                     "no georeferenced datum block; no crop to evaluate")
    gtx = datum.get("gtx")
    if not isinstance(gtx, dict):
        return Check("datum_independent", NOT_RUN,
                     "the datum block carries no gtx crop (a bake from before the crop "
                     "was written); re-bake to get one")
    stem = (manifest.get("scene") or {}).get("terrain")
    if not stem:
        return Check("datum_independent", NOT_RUN,
                     "the manifest names no bake (scene.terrain), so the crop beside it "
                     "cannot be found")
    try:
        from pyproj import Transformer
    except ImportError:
        return Check("datum_independent", NOT_RUN, "pyproj is not installed here")
    import struct

    folder = Path(str(stem)).parent
    path = folder / str(gtx.get("file"))
    samples_path = folder / str(gtx.get("samples_file"))
    for file, expected in ((path, gtx.get("sha256")), (samples_path, gtx.get("samples_sha256"))):
        if not file.is_file():
            return Check("datum_independent", FAIL,
                         f"the bake's geoid file {file} is absent", failure=FAIL_DATUM)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != expected:
            return Check("datum_independent", FAIL,
                         f"{file.name} has sha256 {digest[:16]}..., not the block's "
                         f"{str(expected)[:16]}...; the crop is not the one the bake wrote",
                         failure=FAIL_DATUM)
    lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">ddddii", path.read_bytes()[:40])
    posting = float(gtx.get("posting_deg") or 0.0)
    if (abs(dlat - posting) > 1e-12 or abs(dlon - posting) > 1e-12
            or abs(lat0 / dlat - round(lat0 / dlat)) > 1e-6
            or abs(lon0 / dlon - round(lon0 / dlon)) > 1e-6
            or (rows, cols) != (gtx.get("rows"), gtx.get("cols"))):
        return Check("datum_independent", FAIL,
                     f"the crop's corner ({lat0}, {lon0}) or steps ({dlat}, {dlon}) are not "
                     f"whole nodes of the {posting} deg posting the block records "
                     f"({rows}x{cols} vs {gtx.get('rows')}x{gtx.get('cols')})",
                     failure=FAIL_DATUM)
    samples = json.loads(samples_path.read_text(encoding="utf-8"))
    interior = samples.get("interior") or {}
    evaluator = Transformer.from_pipeline(f"+inv +proj=vgridshift +grids={path}")
    origin_lat, origin_lon = float(datum["origin_lat_deg"]), float(datum["origin_lon_deg"])
    stated = datum.get("undulation_bilinear_m", datum.get("undulation_m"))
    at_origin = evaluator.transform(origin_lon, origin_lat, 0.0)[2]
    if not math.isfinite(at_origin) or abs(at_origin - float(stated)) > DATUM_INDEPENDENT_TOL_M:
        return Check("datum_independent", FAIL,
                     f"PROJ reads {at_origin:+.3f} m from the crop at the origin; the block "
                     f"states {float(stated):+.3f} m (bilinear); tolerance "
                     f"{DATUM_INDEPENDENT_TOL_M} m (a sign flip reads -N)", failure=FAIL_DATUM)
    worst = 0.0
    points = list(zip(interior.get("lat_deg", ()), interior.get("lon_deg", ()),
                      interior.get("undulation_bilinear_m", ())))
    if len(points) < 100:
        return Check("datum_independent", FAIL,
                     f"the samples file records {len(points)} interior points; 100 are "
                     f"the contract", failure=FAIL_DATUM)
    for lat, lon, expected in points:
        value = evaluator.transform(float(lon), float(lat), 0.0)[2]
        residual = abs(value - float(expected)) if math.isfinite(value) else float("inf")
        worst = max(worst, residual)
    if worst > DATUM_INDEPENDENT_TOL_M:
        return Check("datum_independent", FAIL,
                     f"PROJ's evaluation of the crop disagrees with the producer's full-grid "
                     f"values by up to {worst:.4f} m over {len(points)} interior points "
                     f"(tolerance {DATUM_INDEPENDENT_TOL_M} m): the crop's nodes or their "
                     f"alignment are not the grid's", failure=FAIL_DATUM)
    outside = [evaluator.transform(lon0, lat0 + rows * dlat, 0.0)[2],
               evaluator.transform(lon0 - dlon, lat0, 0.0)[2]]
    if any(math.isfinite(v) for v in outside):
        return Check("datum_independent", FAIL,
                     f"the crop answers {outside} one node outside its stated extent; a "
                     f"crop that is not bounded is not the crop the block describes",
                     failure=FAIL_DATUM)
    return Check("datum_independent", PASS,
                 f"PROJ +inv vgridshift on {path.name} ({rows}x{cols} nodes at {posting:.6f} deg, "
                 f"corner on whole nodes) reads {at_origin:+.3f} m at the origin (block "
                 f"{float(stated):+.3f} m) and agrees with the producer's full-grid values to "
                 f"{worst:.2e} m over {len(points)} interior points; inf outside")
'''

#: sha256 of the batch-1 functions as landed in verify.py at bb02dd6: the
#: pin accepts them until the D1 patch above is integrated, and nothing else.
LANDED_VERIFY_SHA256 = {
    "_own_undulation": "244e91522b23b5614950dc9bb732054dbf0b0cc469791432d6be5f2a1840160d",
    "verify_datum": "a2d33d6df9cc84dcd6137440607917a64f7f3f0c4c5eb3ec2bdafeb6ffaef4c5",
}


def _patch_namespace():
    """The patch text executed against the verifier's own types."""
    from core.capture import verify

    namespace = {
        "Check": verify.Check, "PASS": verify.PASS, "FAIL": verify.FAIL,
        "NOT_RUN": verify.NOT_RUN, "Path": Path, "math": math, "json": json,
        "hashlib": hashlib, "Dict": dict, "__file__": str(verify.__file__),
    }
    exec(compile(VERIFY_DATUM_PATCH, "<verify_datum patch>", "exec"), namespace)
    return namespace


def _verifier():
    """``(verify_datum, tolerance)``: verify.py's own once the D1 patch is
    applied, else the patch text executed against verify.py's Check."""
    from core.capture import verify

    if hasattr(verify, "verify_datum_independent"):
        return verify.verify_datum, verify.DATUM_TOL_M
    namespace = _patch_namespace()
    return namespace["verify_datum"], namespace["DATUM_TOL_M"]


def _independent_verifier():
    """``verify_datum_independent``: verify.py's own once applied, else
    the patch text's."""
    from core.capture import verify

    if hasattr(verify, "verify_datum_independent"):
        return verify.verify_datum_independent
    return _patch_namespace()["verify_datum_independent"]


def test_the_verifier_never_imports_the_geoid_producer():
    text = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    for source in (text, VERIFY_DATUM_PATCH):
        assert "import core.terrain" not in source
        assert "from core.terrain" not in source
        assert "from ..terrain" not in source and "import geoid" not in source


def test_the_applied_verifier_is_pinned_to_the_returned_text():
    """The functions in verify.py are character-for-character the ones
    carried here (the D1 text), or -- until the integrator applies the D1
    patch -- the batch-1 ones as landed, identified by sha256; anything
    else is drift."""
    from core.capture import verify

    if not hasattr(verify, "verify_datum"):
        pytest.skip("verify_datum not yet integrated into core/capture/verify.py")
    if hasattr(verify, "verify_datum_independent"):
        for name in ("_own_undulation", "_datum_model", "verify_datum",
                     "verify_datum_independent"):
            assert inspect.getsource(getattr(verify, name)) in VERIFY_DATUM_PATCH, name
        assert verify.DATUM_INDEPENDENT_TOL_M == 0.01
    else:
        for name, digest in LANDED_VERIFY_SHA256.items():
            source = inspect.getsource(getattr(verify, name))
            assert hashlib.sha256(source.encode()).hexdigest() == digest, (
                f"{name} in verify.py is neither the landed batch-1 text nor the D1 text")
    assert verify.DATUM_TOL_M == 0.01 and verify.FAIL_DATUM == "scene.datum"


def test_verify_datum_passes_a_correct_block_and_fails_a_wrong_undulation():
    verify_datum, tolerance = _verifier()
    assert tolerance == 0.01
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    check = verify_datum({"datum": json.loads(json.dumps(block))})
    assert check.status == "PASS", check.detail
    assert "+52.52" in check.detail
    wrong = dict(block, undulation_m=block["undulation_m"] + 0.5,
                 ellipsoidal_height_of_origin_m=2400.0 + block["undulation_m"] + 0.5)
    check = verify_datum({"datum": wrong})
    assert check.status == "FAIL" and check.failure == "scene.datum", check.detail
    assert "0.500" in check.detail or "53.02" in check.detail
    # Just inside the tolerance passes; just outside fails.
    near = dict(block, undulation_m=block["undulation_m"] + 0.009,
                ellipsoidal_height_of_origin_m=2400.0 + block["undulation_m"] + 0.009)
    assert verify_datum({"datum": near}).status == "PASS"
    far = dict(block, undulation_m=block["undulation_m"] + 0.011,
               ellipsoidal_height_of_origin_m=2400.0 + block["undulation_m"] + 0.011)
    assert verify_datum({"datum": far}).status == "FAIL"


def test_verify_datum_fails_a_block_missing_keys_or_naming_another_grid():
    verify_datum, _ = _verifier()
    block = datum_block(46.005, 7.72, 2400.0)
    lacking = {k: v for k, v in block.items() if k != "undulation_source"}
    check = verify_datum({"datum": lacking})
    assert check.status == "FAIL" and check.failure == "scene.datum"
    assert "undulation_source" in check.detail
    other = json.loads(json.dumps(block))
    other["undulation_source"]["sha256"] = "0" * 64
    check = verify_datum({"datum": other})
    assert check.status == "FAIL" and "sha256" in check.detail
    inconsistent = dict(block, ellipsoidal_height_of_origin_m=2400.0)
    check = verify_datum({"datum": inconsistent})
    assert check.status == "FAIL" and "not orthometric" in check.detail


def test_verify_datum_is_not_run_on_a_flat_scene_or_an_older_manifest():
    verify_datum, _ = _verifier()
    assert verify_datum({"datum": flat_datum_block(0.0)}).status == "NOT RUN"
    assert verify_datum({}).status == "NOT RUN"


def test_the_verifiers_own_reader_agrees_with_the_producer_at_every_origin():
    """Two readers of one file: the checker's ~15-line one and the
    producer's. They agree to 1e-9 m at the six origins and (0, 0), on
    the EGM96 grid always and on the EGM2008 grid when it is cached."""
    own = _patch_namespace()["_own_undulation"]
    for lat, lon, _ in list(MEASURED.values()) + [(0.0, 0.0, 17.16)]:
        n, digest = own(GRID_PATH, lat, lon)
        assert n == pytest.approx(undulation(lat, lon), abs=1e-9)
        assert digest == GRID_SHA256
    if EGM2008_GRID_PATH.is_file():
        grid = load_egm2008()
        for lat, lon, _ in list(MEASURED.values()) + [(0.0, 0.0, 17.226)]:
            n, digest = own(EGM2008_GRID_PATH, lat, lon)
            assert n == pytest.approx(grid.undulation(lat, lon), abs=1e-9)
            assert digest == EGM2008_GRID_SHA256


# -- the bake script's datum line ---------------------------------------------

def test_bake_script_prints_the_datum_line_from_the_sidecar(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bake_terrain", REPO / "scripts" / "bake_terrain.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72,
                          "datum": block})
    raw = field.write(tmp_path / "matterhorn")
    line = module.datum_line("matterhorn", raw)
    assert "N = +52.52 m" in line and "+-1.152 m" in line and "13.7 m" in line
    assert "2452.5 m ellipsoidal" in line
    old = _heightfield({"origin_lat_deg": 46.005}).write(tmp_path / "old")
    assert "no datum block" in module.datum_line("old", old)


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    for rel in ("core/terrain/geoid.py", "assets/geoid/README.md",
                "tests/test_geoid.py", "tests/test_datum_block.py",
                "experiments/datum_null_test.py"):
        assert (REPO / rel).read_text(encoding="utf-8").isascii(), rel
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    assert json.dumps(block).isascii()
    assert json.dumps(undulation_variable(block).to_dict()).isascii()


# -- D1: the EGM2008 grid, the cubic interpolation, the crop ------------------

#: EGM2008 undulations at the six origins, MEASURED here 2026-09-28 from
#: the egm2008-5 grid (bilinear, as the blueprint states them; cubic beside).
MEASURED_EGM2008 = {
    "matterhorn": (46.005, 7.72, 54.76, 54.78),
    "yosemite": (37.7275, -119.61, -25.43, -25.43),
    "fuji": (35.42, 138.7274, 42.41, 42.42),
    "everest": (27.90, 86.87, -28.97, -28.90),
    "grand_canyon": (36.09, -112.0, -23.42, -23.44),
    "flint_hills": (38.43, -96.60, -30.30, -30.31),
}

egm2008_here = pytest.mark.skipif(
    not EGM2008_GRID_PATH.is_file(),
    reason="the EGM2008 grid is not in the bake cache (data/geoid; not committed); "
           "fetch it with core.terrain.geoid.fetch_egm2008")


def _weighted_cubic_fit(mask):
    """GeographicLib's transfer matrix re-derived: the weighted
    least-squares fit of the masked cubic terms over the 12-point
    stencil, in exact rational arithmetic (Lesh 1959)."""
    from fractions import Fraction

    keep = [i for i, p in enumerate(geoid.CUBIC_TERMS) if mask(p)]
    n = len(keep)
    a = [[Fraction(0)] * n for _ in range(n)]
    b = [[Fraction(0)] * 12 for _ in range(n)]
    for k, ((x, y), w) in enumerate(zip(geoid.CUBIC_STENCIL, geoid.CUBIC_WEIGHTS)):
        basis = [Fraction(x) ** geoid.CUBIC_TERMS[i][0] * Fraction(y) ** geoid.CUBIC_TERMS[i][1]
                 for i in keep]
        for i in range(n):
            for j in range(n):
                a[i][j] += w * basis[i] * basis[j]
            b[i][k] += w * basis[i]
    m = [row[:] + b[i][:] for i, row in enumerate(a)]
    for c in range(n):
        pivot = next(r for r in range(c, n) if m[r][c] != 0)
        m[c], m[pivot] = m[pivot], m[c]
        m[c] = [v / m[c][c] for v in m[c]]
        for r in range(n):
            if r != c and m[r][c] != 0:
                f = m[r][c]
                m[r] = [u - f * v for u, v in zip(m[r], m[c])]
    out = [[Fraction(0)] * 10 for _ in range(12)]
    for ii, i in enumerate(keep):
        for k in range(12):
            out[k][i] = m[ii][10 + k] if False else m[ii][n + k]
    return out


def test_the_cubic_transfer_matrices_are_the_least_squares_fit_they_claim():
    """The three tables transcribed from GeographicLib 2.3 Geoid.cpp are
    re-derived here: C3 is the weighted cubic fit over the stencil, C3N
    the same fit without the x, x^2, x^3 terms, C3S is C3N under
    y -> 1 - y with the stencil reflected. A single wrong digit in the
    transcription fails this."""
    from fractions import Fraction

    interior = _weighted_cubic_fit(lambda p: True)
    assert [int(v * geoid.CUBIC_C0) for row in interior for v in row] == list(geoid.CUBIC_C3)
    assert all((v * geoid.CUBIC_C0).denominator == 1 for row in interior for v in row)
    north = _weighted_cubic_fit(lambda p: not (p[0] > 0 and p[1] == 0))
    assert [int(v * geoid.CUBIC_C0N) for row in north for v in row] == list(geoid.CUBIC_C3N)
    perm = [10, 11, 6, 7, 8, 9, 2, 3, 4, 5, 0, 1]
    south = []
    for j in range(12):
        row = [Fraction(v, geoid.CUBIC_C0N) for v in geoid.CUBIC_C3N[10 * perm[j]:10 * perm[j] + 10]]
        out = {p: Fraction(0) for p in geoid.CUBIC_TERMS}
        for (a, b), c in zip(geoid.CUBIC_TERMS, row):
            for k in range(b + 1):
                out[(a, k)] += c * math.comb(b, k) * (-1) ** k
        south += [int(out[p] * geoid.CUBIC_C0S) for p in geoid.CUBIC_TERMS]
    assert south == list(geoid.CUBIC_C3S)


def test_cubic_on_the_committed_grid_stays_within_the_header_cubic_bound():
    """EGM96, always here: the cubic and bilinear evaluations differ by
    less than the sum of the header's two bounds at the six origins and
    (0, 0), the cubic is not the bilinear (it is a different fit), and
    at (0, 0) both are the known 17.16 m."""
    grid = load_grid()
    assert grid.max_cubic_error_m == 0.169 and grid.model_key == "EGM96"
    for lat, lon, _ in list(MEASURED.values()) + [(0.0, 0.0, 17.16)]:
        cubic, bilinear = grid.undulation_cubic(lat, lon), grid.undulation(lat, lon)
        assert abs(cubic - bilinear) <= 1.152 + 0.169
    assert grid.undulation_cubic(0.0, 0.0) == pytest.approx(17.161, abs=0.002)
    assert grid.undulation(0.0, 0.0) == pytest.approx(17.163, abs=0.002)
    # Cubic differs from bilinear where the field curves (the Alps: 4 cm).
    assert abs(grid.undulation_cubic(46.005, 7.72) - grid.undulation(46.005, 7.72)) > 0.02
    # And at a node-centred flat patch the two agree closely (a sanity
    # bound on the fit, not a claim about the geoid).
    assert grid.undulation_at(46.005, 7.72, "cubic") == grid.undulation_cubic(46.005, 7.72)
    assert grid.undulation_at(46.005, 7.72, "bilinear") == grid.undulation(46.005, 7.72)
    with pytest.raises(ValueError):
        grid.undulation_at(46.0, 7.0, "nearest")


def test_the_cubic_wraps_in_longitude_and_reaches_the_poles():
    grid = load_grid()
    assert grid.undulation_cubic(10.0, -10.0) == pytest.approx(grid.undulation_cubic(10.0, 350.0), abs=1e-12)
    assert grid.undulation_cubic(10.0, 359.999) == pytest.approx(grid.undulation_cubic(10.0, -0.001), abs=1e-12)
    # At each pole the polar matrix makes N independent of longitude.
    assert grid.undulation_cubic(90.0, 0.0) == pytest.approx(grid.undulation_cubic(90.0, 123.0), abs=1e-9)
    assert grid.undulation_cubic(-90.0, 0.0) == pytest.approx(grid.undulation_cubic(-90.0, 200.0), abs=1e-9)
    assert math.isfinite(grid.undulation_cubic(89.99, 180.0)) and math.isfinite(grid.undulation_cubic(-89.99, 45.0))
    with pytest.raises(GeoidError):
        grid.undulation_cubic(90.5, 0.0)


@egm2008_here
def test_the_cached_egm2008_grid_is_the_measured_one_and_reproduces_the_origins():
    """The grid in the bake cache is byte-for-byte the one every EGM2008
    number here was measured from (its sha256, 4320 x 2161, the header's
    bounds), N(0, 0) = 17.226 bilinear / 17.225 cubic, and the six
    origins to 0.01 m both ways (the blueprint's numbers are bilinear)."""
    grid = load_egm2008()
    assert grid.sha256 == EGM2008_GRID_SHA256 and grid.model_key == "EGM2008"
    assert (grid.width, grid.height) == (4320, 2161)
    assert grid.max_bilinear_error_m == 0.478 and grid.max_cubic_error_m == 0.294
    assert grid.posting_deg == pytest.approx(1.0 / 12.0)
    assert grid.undulation(0.0, 0.0) == pytest.approx(17.226, abs=0.001)
    assert grid.undulation_cubic(0.0, 0.0) == pytest.approx(17.225, abs=0.001)
    for key, (lat, lon, bilinear, cubic) in MEASURED_EGM2008.items():
        assert grid.undulation(lat, lon) == pytest.approx(bilinear, abs=0.01), key
        assert grid.undulation_cubic(lat, lon) == pytest.approx(cubic, abs=0.01), key
        assert abs(grid.undulation_cubic(lat, lon) - grid.undulation(lat, lon)) <= 0.478 + 0.294
    # The curated EGM2008 - EGM96 table (bilinear on both) is reproduced live.
    for key, (lat, lon, _) in MEASURED.items():
        assert grid.undulation(lat, lon) - undulation(lat, lon) == pytest.approx(
            geoid.EGM2008_MINUS_EGM96_AT_ORIGIN_M[key], abs=0.001), key


def test_an_absent_egm2008_grid_refuses_grid_missing_and_a_wrong_one_grid_digest(tmp_path):
    with pytest.raises(DatumError) as info:
        load_egm2008(tmp_path / "nowhere.pgm")
    assert name_of(info.value) == "geoid.grid_missing"
    # The committed EGM96 grid under the EGM2008 name: the digest refuses.
    wrong = tmp_path / "egm2008-5.pgm"
    wrong.write_bytes(GRID_PATH.read_bytes())
    with pytest.raises(DatumError) as info:
        load_egm2008(wrong)
    assert name_of(info.value) == "geoid.grid_digest"
    # Unchecked, the same file is refused for what its header says it is.
    with pytest.raises(DatumError) as info:
        load_egm2008(wrong, expected_sha256=None)
    assert name_of(info.value) == "geoid.grid_digest" and "EGM2008" in str(info.value)
    assert geoid.grid_for_model("EGM96").model_key == "EGM96"
    with pytest.raises(ValueError):
        geoid.grid_for_model("EGM84")


def test_a_fetched_tarball_with_the_wrong_digest_is_refused_before_extraction(tmp_path, monkeypatch):
    """The fetch checks the tarball's sha256 against the recorded one and
    extracts nothing from a tarball that is not the one measured."""
    import io
    import tarfile
    import urllib.request

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as archive:
        data = GRID_PATH.read_bytes()
        info = tarfile.TarInfo(geoid.EGM2008_TARBALL_MEMBER)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    payload = buffer.getvalue()

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: _Response(payload))
    with pytest.raises(DatumError) as info:
        geoid.fetch_egm2008(tmp_path)
    assert name_of(info.value) == "geoid.grid_digest"
    assert (tmp_path / "egm2008-5.tar.bz2").is_file()
    assert not (tmp_path / "egm2008-5.pgm").exists()


def _proj_reads(path, lat, lon):
    from pyproj import Transformer

    return Transformer.from_pipeline(f"+inv +proj=vgridshift +grids={path}").transform(
        lon, lat, 0.0)[2]


def test_write_gtx_snaps_the_crop_to_whole_nodes_with_a_one_node_margin(tmp_path):
    """EGM96 (15-minute nodes), always here: the Matterhorn bbox
    (45.85..46.10 N, 7.45..7.95 E) floors/ceils to 45.75..46.25 N,
    7.25..8.00 E and the margin adds a node each side: 45.5..46.5 N,
    7.0..8.25 E, 5 x 6 nodes, corner on whole nodes."""
    grid = load_grid()
    record = write_gtx(grid, (45.85, 46.10, 7.45, 7.95), tmp_path / "mh.gtx")
    assert (record["rows"], record["cols"]) == (5, 6)
    assert (record["lat_south"], record["lat_north"]) == (45.5, 46.5)
    assert (record["lon_west"], record["lon_east"]) == (7.0, 8.25)
    align = record["alignment"]
    assert align["node_aligned"] and align["south_node"] * 0.25 == 45.5 and align["west_node"] * 0.25 == 7.0
    assert record["posting_deg"] == 0.25 and record["margin_nodes"] == 1
    assert record["sha256"] == hashlib.sha256((tmp_path / "mh.gtx").read_bytes()).hexdigest()
    assert record["bytes"] == 40 + 4 * 30
    crop = read_gtx(tmp_path / "mh.gtx")
    assert (crop.rows, crop.cols) == (5, 6) and crop.sha256 == record["sha256"]
    # The nodes are the grid's own, verbatim.
    iy, ix = int((90.0 - 46.5) * 4), int(7.0 * 4)
    assert crop.values[-1, 0] == pytest.approx(grid.offset_m + grid.scale_m * float(grid.values[iy, ix]), abs=1e-5)
    # Outside the nodes: refused by name; inside: bilinear on them.
    with pytest.raises(DatumError) as info:
        crop.undulation(46.51, 7.5)
    assert name_of(info.value) == "datum.outside_grid"
    assert crop.undulation(46.005, 7.72) == pytest.approx(undulation(46.005, 7.72), abs=2e-6)


def test_proj_reads_plus_n_from_the_crop_with_inv_and_inf_outside(tmp_path):
    """The independent evaluator: PROJ's vgridshift on the written crop
    reads +N (with +inv; the forward pipeline reads -N) within 2e-6 m of
    the producer's bilinear value at the origin and at the 100 interior
    samples, on the EGM96 grid; inf one node beyond the crop."""
    from pyproj import Transformer

    grid = load_grid()
    record = write_gtx_bundle(grid, (45.85, 46.10, 7.45, 7.95), tmp_path, "mh", 46.005, 7.72)
    path = tmp_path / record["file"]
    assert _proj_reads(path, 46.005, 7.72) == pytest.approx(undulation(46.005, 7.72), abs=1e-5)
    forward = Transformer.from_pipeline(f"+proj=vgridshift +grids={path}").transform(7.72, 46.005, 0.0)[2]
    assert forward == pytest.approx(-undulation(46.005, 7.72), abs=1e-5)
    samples = json.loads((tmp_path / record["samples_file"]).read_text(encoding="utf-8"))
    interior = samples["interior"]
    assert interior["count"] == 100 == len(interior["lat_deg"])
    worst = max(abs(_proj_reads(path, la, lo) - nb)
                for la, lo, nb in zip(interior["lat_deg"], interior["lon_deg"],
                                      interior["undulation_bilinear_m"]))
    assert worst < 1e-5
    assert math.isinf(_proj_reads(path, 46.75, 7.72)) and math.isinf(_proj_reads(path, 46.0, 6.75))
    # The sign anchor: a crop around (0, 0) reads +17.16 with +inv.
    zero = write_gtx(grid, (-0.1, 0.1, -0.1, 0.1), tmp_path / "zero.gtx")
    assert _proj_reads(tmp_path / "zero.gtx", 0.0, 0.0) == pytest.approx(17.163, abs=0.002)
    assert zero["lat_south"] == -0.5 and zero["lon_west"] == -0.5


def test_a_node_misaligned_crop_disagrees_with_the_grid(tmp_path):
    """Why the alignment is recorded and checked: the same nodes with the
    header corner moved half a node make PROJ read another place --
    measured here on the EGM96 crop: 0.028 m at the Matterhorn origin for
    a third of a node, 0.043 m for half a node (the research measured
    0.058 m on its EGM2008 crop); both beyond the 0.01 m tolerance."""
    import struct

    grid = load_grid()
    write_gtx(grid, (45.85, 46.10, 7.45, 7.95), tmp_path / "mh.gtx")
    data = bytearray((tmp_path / "mh.gtx").read_bytes())
    lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">ddddii", bytes(data[:40]))
    data[:40] = struct.pack(">ddddii", lat0 + dlat / 2.0, lon0, dlat, dlon, rows, cols)
    (tmp_path / "shifted.gtx").write_bytes(bytes(data))
    miss = abs(_proj_reads(tmp_path / "shifted.gtx", 46.005, 7.72) - undulation(46.005, 7.72))
    print(f"node-misaligned crop (half a node): PROJ misses the origin by {miss:.4f} m")
    assert miss > 0.02


def test_a_crop_that_would_leave_the_grid_refuses_outside_grid():
    grid = load_grid()
    with pytest.raises(DatumError) as info:
        geoid.gtx_crop_nodes(grid, (89.9, 89.99, 0.0, 1.0))
    assert name_of(info.value) == "datum.outside_grid"
    with pytest.raises(ValueError):
        geoid.gtx_crop_nodes(grid, (46.0, 45.0, 7.0, 8.0))


@egm2008_here
def test_the_egm2008_crop_at_five_minute_nodes_agrees_with_proj(tmp_path):
    grid = load_egm2008()
    record = write_gtx_bundle(grid, (45.85, 46.10, 7.45, 7.95), tmp_path, "mh", 46.005, 7.72)
    assert (record["rows"], record["cols"]) == (7, 10)
    assert record["lat_south"] == pytest.approx(45.75) and record["lon_west"] == pytest.approx(7.0 + 1.0 / 3.0)
    path = tmp_path / record["file"]
    assert _proj_reads(path, 46.005, 7.72) == pytest.approx(grid.undulation(46.005, 7.72), abs=1e-5)
    samples = json.loads((tmp_path / record["samples_file"]).read_text(encoding="utf-8"))
    worst = max(abs(_proj_reads(path, la, lo) - nb)
                for la, lo, nb in zip(samples["interior"]["lat_deg"], samples["interior"]["lon_deg"],
                                      samples["interior"]["undulation_bilinear_m"]))
    assert worst < 1e-5
    yosemite = write_gtx(grid, (37.60, 37.85, -119.80, -119.40), tmp_path / "yo.gtx")
    assert yosemite["lon_west"] < 0 and _proj_reads(tmp_path / "yo.gtx", 37.7275, -119.61) == pytest.approx(
        grid.undulation(37.7275, -119.61), abs=1e-5)


@egm2008_here
def test_an_egm2008_datum_block_is_cubic_with_the_bounds_the_crop_and_the_frame():
    grid = load_egm2008()
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn", grid=grid,
                        bbox=(45.85, 46.10, 7.45, 7.95))
    assert set(DATUM_KEYS) <= set(block)
    assert block["geoid_model_key"] == "EGM2008" and block["interpolation"] == "cubic"
    assert block["geoid_model"] == "EGM2008 5-minute grid (GeographicLib egm2008-5)"
    assert block["undulation_m"] == pytest.approx(54.78, abs=0.01)
    assert block["undulation_bilinear_m"] == pytest.approx(54.76, abs=0.01)
    assert block["interpolation_error_bound_m"] == 0.294 and block["bilinear_error_bound_m"] == 0.478
    assert block["model_difference_bound_m"] == 0.0 and block["model_difference_at_origin_m"] == 0.0
    assert block["egm2008_minus_egm96_at_origin_m"] == pytest.approx(2.231, abs=0.001)
    assert block["undulation_source"]["sha256"] == EGM2008_GRID_SHA256 == block["grid_sha256"]
    assert block["u_model_m"] == 0.10 and block["tide_system"] == "not verified here"
    assert block["physics_frame"]["frame"] == "orthometric"
    assert block["ellipsoidal_height_of_origin_m"] == pytest.approx(2400.0 + block["undulation_m"])
    bounds = block["bounds"]
    assert bounds["undulation_min_m"] <= block["undulation_m"] <= bounds["undulation_max_m"]
    assert 0.5 < bounds["undulation_range_m"] < 3.5      # the blueprint's 0.6-3.4 m bbox ranges
    record = undulation_variable(block).to_dict()
    assert record["model"] == "EGM2008 cubic" and record["null_test"]["threshold"] == 0.294
    assert record["telemetry_columns"] == ["undulation_m", "hae_m"]
    assert record["frame_keys"] == ["state.undulation_m", "state.hae_m"]
    assert record["uncertainty"]["u_input"]["value"] == 0.10
    assert record["parameters"]["model"] == "EGM2008"
    assert json.dumps(block).isascii() and json.dumps(record).isascii()


def test_an_egm96_block_keeps_its_landed_form_and_states_the_difference():
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    assert block["geoid_model_key"] == "EGM96" and block["interpolation"] == "bilinear"
    assert block["undulation_bilinear_m"] == block["undulation_m"]
    assert block["interpolation_error_bound_m"] == 1.152
    assert block["model_difference_bound_m"] == 13.7
    assert block["u_model_m"] == 13.7 and "not the bakes' datum model" in block["u_model_basis"]
    assert block["bounds"] is None and block["gtx"] is None
    assert geoid.model_key_of({"geoid_model": "EGM96 15-minute grid (GeographicLib egm96-15)"}) == "EGM96"
    assert geoid.model_key_of(flat_datum_block(0.0)) is None
    assert flat_datum_block(0.0)["physics_frame"]["frame"] == "orthometric"


def test_verify_datum_handles_a_cubic_block_and_fails_a_stale_bilinear_companion():
    """The extended clause on an EGM96 block interpolated cubic (the
    checker re-evaluates the bilinear companion, and holds the cubic
    value within the header's two bounds of it)."""
    verify_datum, _ = _verifier()
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn", interpolation="cubic")
    assert block["interpolation"] == "cubic" and block["undulation_m"] != block["undulation_bilinear_m"]
    check = verify_datum({"datum": json.loads(json.dumps(block))})
    assert check.status == "PASS", check.detail
    assert "cubic" in check.detail
    stale = dict(block, undulation_bilinear_m=block["undulation_bilinear_m"] + 0.02)
    check = verify_datum({"datum": stale})
    assert check.status == "FAIL" and check.failure == "scene.datum"
    wild = dict(block, undulation_m=block["undulation_bilinear_m"] + 2.0,
                ellipsoidal_height_of_origin_m=2400.0 + block["undulation_bilinear_m"] + 2.0)
    check = verify_datum({"datum": wild})
    assert check.status == "FAIL" and "beyond the header" in check.detail
    lacking = {k: v for k, v in block.items() if k != "undulation_bilinear_m"}
    assert verify_datum({"datum": lacking}).status == "FAIL"


@egm2008_here
def test_verify_datum_re_evaluates_an_egm2008_block_from_the_cached_grid():
    verify_datum, _ = _verifier()
    block = datum_block(46.005, 7.72, 2400.0, grid=load_egm2008())
    check = verify_datum({"datum": json.loads(json.dumps(block))})
    assert check.status == "PASS", check.detail
    assert "EGM2008 cubic" in check.detail and "+54.780" in check.detail
    foreign = dict(block, undulation_source=dict(block["undulation_source"], sha256=GRID_SHA256))
    check = verify_datum({"datum": foreign})
    assert check.status == "FAIL" and "two grids" in check.detail


def test_verify_datum_is_not_run_for_an_egm2008_block_when_the_checker_has_no_grid(monkeypatch):
    namespace = _patch_namespace()
    monkeypatch.setitem(namespace, "DATUM_GRID_EGM2008", Path("/nowhere/egm2008-5.pgm"))
    block = datum_block(46.005, 7.72, 2400.0)
    block = dict(block, geoid_model_key="EGM2008", geoid_model="EGM2008 5-minute grid (GeographicLib egm2008-5)")
    check = namespace["verify_datum"]({"datum": block})
    assert check.status == "NOT RUN" and "datum_independent" in check.detail


def test_an_egm2008_named_grid_with_the_wrong_digest_is_refused_by_the_digest_alone(tmp_path):
    """Only the sha256 stands between a file that CALLS itself EGM2008
    and the block: a small PGM with the EGM2008 header and other numbers
    is refused geoid.grid_digest by the digest check, and parses when
    the check is skipped (so the header alone would not have refused it)."""
    fake = tmp_path / "egm2008-5.pgm"
    header = (b"P5\n# Description WGS84 EGM2008, 5-minute grid\n# MaxBilinearError 0.478\n"
              b"# MaxCubicError 0.294\n# Offset -108\n# Scale 0.003\n# Origin 90N 0E\n4 3\n65535\n")
    fake.write_bytes(header + b"\x8c\xa0" * 12)
    with pytest.raises(DatumError) as info:
        load_egm2008(fake)
    assert name_of(info.value) == "geoid.grid_digest" and "sha256" in str(info.value)
    unchecked = load_egm2008(fake, expected_sha256=None)
    assert unchecked.model_key == "EGM2008" and unchecked.width == 4
