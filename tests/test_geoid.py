"""P10, the vertical datum: the EGM96 geoid grid, the undulation, the
datum block on the bake sidecar, the run card and the capture manifest,
the applied-variable record, and the verifier's independent re-check.

Every number asserted here was measured in the container on 2026-09-28
(phase3_facts.md): the six curated origins' undulations from the
GeographicLib egm96-15 grid, the (0, 0) check value, the header's
bilinear bound. The verifier clause is tested against
``core.capture.verify.verify_datum`` when the integrator has applied the
patch, and until then against the SAME text carried verbatim in
``VERIFY_DATUM_PATCH`` below (executed here with the verifier's own
``Check`` type); a test pins the applied function to that text so the
two cannot drift.
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
    BAKE_DATUM, FLAT_DATUM, GRID_PATH, GRID_SHA256, SYNTHESISED_DATUM,
    GeoidError, datum_block, datum_for_heightfield, flat_datum_block,
    load_grid, undulation, undulation_variable,
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
    # An origin nobody measured EGM2008 at says null, not a guess.
    assert datum_block(10.0, 10.0, 0.0)["model_difference_at_origin_m"] is None


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
                             ground_sample_distance_m=90.0)
    assert report["ok"]
    sidecar = json.loads(raw.with_suffix(".json").read_text(encoding="utf-8"))
    datum = sidecar["provenance"]["datum"]
    assert set(DATUM_KEYS) <= set(datum)
    assert datum["undulation_m"] == undulation(45.9, 7.1)
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

#: The text returned to the integrator for core/capture/verify.py, verbatim.
#: Executed here with the verifier's own Check/PASS/FAIL/NOT_RUN so the
#: clause is tested before the patch lands; once it has, the function in
#: verify.py is used and pinned to this text.
VERIFY_DATUM_PATCH = '''
# -- P10: the vertical datum ------------------------------------------------

#: How far the manifest's geoid undulation may sit from the checker's own
#: re-evaluation of the same grid. Two bilinear readers of one file agree
#: to floating-point; 0.01 m catches a nearest-neighbour producer (the
#: grid's own bilinear bound is 1.152 m), a wrong origin, a wrong grid.
DATUM_TOL_M = 0.01
FAIL_DATUM = "scene.datum"
#: The committed EGM96 grid the checker reads for itself (assets/geoid).
DATUM_GRID = Path(__file__).resolve().parents[2] / "assets" / "geoid" / "egm96-15.pgm"
DATUM_KEYS = (
    "vertical_datum_of_heights", "geoid_model", "origin_lat_deg",
    "origin_lon_deg", "undulation_m", "undulation_source",
    "bilinear_error_bound_m", "model_difference_bound_m",
    "orthometric_height_of_origin_m", "ellipsoidal_height_of_origin_m", "note",
)


def _own_undulation(path, lat_deg: float, lon_deg: float):
    """The checker's OWN GeographicLib-PGM reader (it never imports
    core.terrain.geoid): header offset/scale, big-endian uint16 samples
    from 90N 0E, bilinear on the four surrounding nodes. Returns (N in
    metres, the file's sha256)."""
    import re

    import numpy as np

    data = Path(path).read_bytes()
    match = re.match(rb"P5\\s*(?:#[^\\n]*\\n\\s*)*(\\d+)\\s+(\\d+)\\s*(?:#[^\\n]*\\n\\s*)*(\\d+)\\s", data)
    header = data[:match.end()].decode("ascii", "replace")
    width, height = int(match.group(1)), int(match.group(2))
    offset = float(re.search(r"# Offset (\\S+)", header).group(1))
    scale = float(re.search(r"# Scale (\\S+)", header).group(1))
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


def verify_datum(manifest: Dict) -> Check:
    """The scene's vertical datum block against the checker's own geoid.

    NOT RUN on a scene with no georeferenced heights (a flat slab or a
    synthesised ridge: ``undulation_m`` is null there, by contract) and
    on a manifest written before the block existed. Otherwise the block
    must carry every key of DATUM_KEYS, name the grid the checker holds
    (by sha256), state an undulation within DATUM_TOL_M of the checker's
    own bilinear evaluation at the recorded origin, and an ellipsoidal
    height equal to orthometric + undulation. FAIL by name (scene.datum)
    on any of these. What is NOT checked: that the heights themselves
    are EGM2008 orthometric (the bake's provenance says so; no second
    source is available here), and the EGM96-EGM2008 difference beyond
    the stated bound.
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
    if not DATUM_GRID.is_file():
        return Check("datum", FAIL,
                     f"the checker's own geoid grid {DATUM_GRID} is absent, so the "
                     f"manifest's undulation cannot be re-evaluated (see "
                     f"assets/geoid/README.md)", failure=FAIL_DATUM)
    own, digest = _own_undulation(DATUM_GRID, datum["origin_lat_deg"], datum["origin_lon_deg"])
    recorded = (datum.get("undulation_source") or {}).get("sha256")
    if recorded != digest:
        return Check("datum", FAIL,
                     f"the manifest's undulation came from a grid with sha256 "
                     f"{str(recorded)[:16]}..., the checker's is {digest[:16]}...; "
                     f"two grids cannot be compared", failure=FAIL_DATUM)
    stated = float(datum["undulation_m"])
    if abs(stated - own) > DATUM_TOL_M:
        return Check("datum", FAIL,
                     f"the manifest states an undulation of {stated:.3f} m at "
                     f"({datum['origin_lat_deg']}, {datum['origin_lon_deg']}); the "
                     f"checker's own bilinear read of the same grid gives {own:.3f} m "
                     f"(tolerance {DATUM_TOL_M} m)", failure=FAIL_DATUM)
    ellipsoidal = float(datum["ellipsoidal_height_of_origin_m"])
    orthometric = float(datum["orthometric_height_of_origin_m"])
    if abs(ellipsoidal - (orthometric + stated)) > 1e-6:
        return Check("datum", FAIL,
                     f"ellipsoidal height {ellipsoidal:.3f} m is not orthometric "
                     f"{orthometric:.3f} m + undulation {stated:.3f} m",
                     failure=FAIL_DATUM)
    return Check("datum", PASS,
                 f"heights {datum['vertical_datum_of_heights']}; undulation "
                 f"{stated:+.3f} m at the origin agrees with the checker's own "
                 f"read of the grid to {abs(stated - own):.4f} m; ellipsoidal "
                 f"origin {ellipsoidal:.1f} m = orthometric {orthometric:.1f} m + N")
'''


def _verifier():
    """``(verify_datum, tolerance)``: verify.py's own once the patch is
    applied, else the patch text executed against verify.py's Check."""
    from core.capture import verify

    if hasattr(verify, "verify_datum"):
        return verify.verify_datum, verify.DATUM_TOL_M
    namespace = {
        "Check": verify.Check, "PASS": verify.PASS, "FAIL": verify.FAIL,
        "NOT_RUN": verify.NOT_RUN, "Path": Path, "math": math,
        "hashlib": hashlib, "Dict": dict, "__file__": str(verify.__file__),
    }
    exec(compile(VERIFY_DATUM_PATCH, "<verify_datum patch>", "exec"), namespace)
    return namespace["verify_datum"], namespace["DATUM_TOL_M"]


def test_the_verifier_never_imports_the_geoid_producer():
    text = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    for source in (text, VERIFY_DATUM_PATCH):
        assert "import core.terrain" not in source
        assert "from core.terrain" not in source
        assert "from ..terrain" not in source and "import geoid" not in source


def test_the_applied_verifier_is_pinned_to_the_returned_text():
    """Once the integrator applies the patch, the function in verify.py
    is character-for-character the one carried here."""
    from core.capture import verify

    if not hasattr(verify, "verify_datum"):
        pytest.skip("verify_datum not yet integrated into core/capture/verify.py")
    for name in ("_own_undulation", "verify_datum"):
        assert inspect.getsource(getattr(verify, name)) in VERIFY_DATUM_PATCH, name
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
    producer's. They agree to 1e-9 m at the six origins and (0, 0)."""
    from core.capture import verify

    namespace = {
        "Check": verify.Check, "PASS": verify.PASS, "FAIL": verify.FAIL,
        "NOT_RUN": verify.NOT_RUN, "Path": Path, "math": math,
        "hashlib": hashlib, "Dict": dict, "__file__": str(verify.__file__),
    }
    exec(compile(VERIFY_DATUM_PATCH, "<verify_datum patch>", "exec"), namespace)
    own = namespace["_own_undulation"]
    for lat, lon, _ in list(MEASURED.values()) + [(0.0, 0.0, 17.16)]:
        n, digest = own(GRID_PATH, lat, lon)
        assert n == pytest.approx(undulation(lat, lon), abs=1e-9)
        assert digest == GRID_SHA256


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
                "tests/test_geoid.py"):
        assert (REPO / rel).read_text(encoding="utf-8").isascii(), rel
    block = datum_block(46.005, 7.72, 2400.0, location_key="matterhorn")
    assert json.dumps(block).isascii()
    assert json.dumps(undulation_variable(block).to_dict()).isascii()
