"""D1, the datum blocks: the spec's ``datum`` block, the runner's channels
and record, the bake sidecar (datum, dted, cdb_descriptor, the .gtx crop),
the refusals by name, the independent verifier clause, and the null test.

Every flight here is a real JSBSim flight (c172p, 2-3 s); every bake is
the synthetic peak through the real bake path (tests/test_geoid.py's).
The EGM2008 grid is the bake cache's (data/geoid; not committed): the
tests that need it say so and skip when it is absent; every other test
runs everywhere and exercised both models here.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest

from core.messages import name_of
from core.records import AppliedVariable, read_records
from core.scenario.blocks import DatumSpec
from core.scenario.fields import Source
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate
from core.terrain import geoid, glo30
from core.terrain.geoid import (
    EGM2008_GRID_PATH, DatumError, check_model_declared, datum_spec_problems,
    datum_for_heightfield, dted_block, flat_datum_block,
)
from core.terrain.ground import TerrainGround
from core.terrain.heightfield import Georeference, Heightfield
from tests.test_geoid import (
    DATUM_KEYS, VERIFY_DATUM_PATCH, _heightfield, _independent_verifier, _patch_namespace,
    _synthetic_tile,
)
from tests.test_registry import EXAMPLE_DIGESTS

REPO = Path(__file__).resolve().parents[1]
EGM2008_CACHED = EGM2008_GRID_PATH.is_file()


def spec_for(seconds: int = 2, **datum) -> ScenarioSpec:
    from core.nl.compiler import compile_prompt

    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {seconds} seconds")
    spec.set("hold_state", False, frm="test")
    for name, value in datum.items():
        spec.set(f"datum.{name}", value, frm="test")
    return spec


# -- the spec block ---------------------------------------------------------------

def test_the_default_block_is_absent_canonical_and_every_committed_example_keeps_its_digest():
    spec = spec_for()
    assert spec.datum.is_default()
    assert "datum" not in spec.to_dict()
    assert DatumSpec.FIELD_ORDER == ("vertical", "physics_frame", "geoid_model")
    for path, digest in EXAMPLE_DIGESTS.items():
        example = ScenarioSpec.read(REPO / path)
        assert example.digest() == digest, path
        assert "datum" not in example.to_dict() and example.datum.is_default()


def test_a_stated_block_is_behind_the_front_door_round_trips_and_changes_the_digest(tmp_path):
    spec = spec_for()
    before = spec.digest()
    spec.set("datum.geoid_model", "EGM2008", frm="declared")
    assert spec.datum.geoid_model.source is Source.USER
    assert spec.digest() != before
    data = spec.to_dict()["datum"]
    assert list(data) == list(DatumSpec.FIELD_ORDER)
    assert data["vertical"]["value"] == "orthometric" and data["vertical"]["source"] == "default"
    spec.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(tmp_path / "s.yaml")
    assert reread.digest() == spec.digest() and reread.datum.geoid_model.value == "EGM2008"
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("datum.geoid_model", "EGM96", frm="a planner")
    spec.plan("datum.physics_frame", "orthometric", frm="a planner")
    assert spec.datum.physics_frame.source is Source.DERIVED
    assert "datum" in spec.render_table()
    with pytest.raises(ValueError, match="unknown fields"):
        DatumSpec.from_dict(dict(data, extra={"value": 1, "source": "user", "from": "x"}))
    with pytest.raises(ValueError, match="missing required field"):
        DatumSpec.from_dict({k: v for k, v in data.items() if k != "vertical"})


@pytest.mark.parametrize("field, value, name", [
    ("vertical", "ellipsoidal", "datum.physics_frame_unsupported"),
    ("vertical", "geoid", "datum.physics_frame_unsupported"),
    ("physics_frame", "ellipsoid", "datum.physics_frame_unsupported"),
    ("geoid_model", "EGM84", "datum.model_mismatch"),
])
def test_the_block_refuses_by_name_before_any_flight(field, value, name):
    from core.scenario.runner import refuse_datum_spec, run_spec

    spec = spec_for(**{field: value})
    problems = datum_spec_problems(spec.datum)
    assert [p.constraint for p in problems] == [name]
    with pytest.raises(DatumError) as info:
        refuse_datum_spec(spec)
    assert name_of(info.value) == name
    # The runner refuses at its top, whether or not the validator ran.
    with pytest.raises(DatumError) as info:
        run_spec(spec, validate_first=False)
    assert name_of(info.value) == name
    assert datum_spec_problems(spec_for().datum) == [] and datum_spec_problems(None) == []


def test_the_declared_model_is_checked_against_the_scene():
    egm96 = geoid.datum_block(46.005, 7.72, 2400.0)
    check_model_declared(None, egm96)
    check_model_declared("EGM96", egm96)
    with pytest.raises(DatumError) as info:
        check_model_declared("EGM2008", egm96)
    assert name_of(info.value) == "datum.model_mismatch" and "re-bake" in str(info.value)
    with pytest.raises(DatumError) as info:
        check_model_declared("EGM96", flat_datum_block(0.0))
    assert name_of(info.value) == "datum.model_mismatch" and "no geoid" in str(info.value)
    # A block from before the key: the model is read from its name.
    old = {k: v for k, v in egm96.items() if k != "geoid_model_key"}
    check_model_declared("EGM96", old)


VALIDATE_DATUM_PATCH = '''
def validate_datum(spec) -> List[Violation]:
    """D1: the datum block's refusals by name (core/terrain/geoid.py
    datum_spec_problems, the one list for the validator and the runner):
    ``datum.physics_frame_unsupported`` for ellipsoidal heights or the
    ellipsoid physics frame, ``datum.model_mismatch`` for a model this
    build does not carry. The match against the bake's model is the
    runner's, where the spec meets the bake."""
    from ..terrain.geoid import datum_spec_problems

    return [Violation(problem.constraint, problem.message)
            for problem in datum_spec_problems(getattr(spec, "datum", None))]
'''


def test_the_validator_patch_names_the_refusals_and_the_landed_validator_stays_feasible():
    """The returned validate.py text, executed against the validator's
    own Violation: an ellipsoidal spec is refused by name; once the
    integrator wires it, the whole validator names it too."""
    from core.scenario import validate as module
    from core.terrain.geoid import datum_spec_problems as problems

    namespace = {"Violation": module.Violation, "List": list,
                 "__name__": "core.scenario.validate"}
    text = VALIDATE_DATUM_PATCH.replace("from ..terrain.geoid import datum_spec_problems",
                                        "datum_spec_problems = problems")
    namespace["problems"] = problems
    exec(compile(text, "<validate_datum patch>", "exec"), namespace)
    violations = namespace["validate_datum"](spec_for(vertical="ellipsoidal"))
    assert [v.constraint for v in violations] == ["datum.physics_frame_unsupported"]
    assert namespace["validate_datum"](spec_for()) == []
    report = validate(spec_for(vertical="ellipsoidal"), check_feasibility=False)
    if hasattr(module, "validate_datum"):
        assert "datum.physics_frame_unsupported" in [v.constraint for v in report.violations]
    else:
        assert report.ok        # not yet wired: the runner refuses instead (tested above)


# -- the runner: channels appended after the digest, the record -------------------

@pytest.fixture(scope="module")
def flat_run():
    from core.scenario.runner import run_spec

    return run_spec(spec_for())


def test_a_flat_run_carries_the_flat_block_and_the_channels_after_the_digest(flat_run):
    from core.scenario.runner import _digest_columns

    datum = flat_run.manifest["datum"]
    assert datum["vertical_datum_of_heights"] == "flat slab, spec terrain_elevation"
    assert datum["undulation_m"] is None and datum["geoid_model_key"] is None
    columns = flat_run.telemetry.columns
    # Appended right after the digest, before the limit monitor's flags.
    assert flat_run.telemetry.derived[:2] == ["undulation_m", "hae_m"]
    assert all(v == 0.0 for v in columns["undulation_m"])
    assert columns["hae_m"] == columns["altitude_m"]
    # The digest is over the RECORDED columns: appending moved nothing.
    recorded = {k: v for k, v in columns.items() if k not in flat_run.telemetry.derived}
    assert _digest_columns(recorded) == flat_run.output_digest
    assert _digest_columns(columns) != flat_run.output_digest
    (record,) = [r for r in read_records(flat_run.manifest["applied_variables"])
                 if r["name"] == "scene.geoid_undulation_m"]
    assert record["value"] is None and record["null_test"] is None
    assert record["telemetry_columns"] == ["undulation_m", "hae_m"]
    assert record["frame_keys"] == ["state.undulation_m", "state.hae_m"]
    assert record["readback"]["agrees"] and record["readback"]["property"] == "telemetry.hae_m[0]"
    invariance = record["parameters"]["invariance"]
    assert invariance["ok"] and invariance["kind"] == "bounded"
    assert invariance["recorded_digest_after_channels"] == flat_run.output_digest
    assert record["parameters"]["spec_datum"]["vertical"]["value"] == "orthometric"
    assert any("0 by the frame's definition" in s for s in record["not_claimed"])
    assert AppliedVariable.from_dict(record).readback.agrees
    assert json.dumps(flat_run.manifest).isascii()
    # Per frame: every column, the two included (core.capture.manifest.frame_state).
    from core.capture.manifest import frame_state, state_units
    state = frame_state(columns, 3)
    assert state["hae_m"] == columns["hae_m"][3] and state["undulation_m"] == 0.0
    assert state_units(columns)["hae_m"] == "m" and state_units(columns)["undulation_m"] == "m"


def test_a_declared_model_on_a_flat_scene_is_refused_before_the_flight(monkeypatch):
    from core.scenario import runner

    def never(*args, **kwargs):
        raise AssertionError("the flight was configured before the datum was checked")

    monkeypatch.setattr(runner, "configure_from_spec", never)
    with pytest.raises(DatumError) as info:
        runner.run_spec(spec_for(geoid_model="EGM2008"), validate_first=False)
    assert name_of(info.value) == "datum.model_mismatch"


def test_a_georeferenced_bake_without_its_block_is_refused_before_the_flight(monkeypatch):
    from core.scenario import runner

    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72})
    assert datum_for_heightfield(field)["undulation_m"] == pytest.approx(52.52, abs=0.01)
    with pytest.raises(DatumError) as info:
        datum_for_heightfield(field, require_block=True)
    assert name_of(info.value) == "datum.sidecar_without_datum"
    monkeypatch.setattr(runner, "configure_from_spec",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("flew")))
    with pytest.raises(DatumError) as info:
        runner.run_spec(spec_for(), validate_first=False, terrain_ground=TerrainGround(field))
    assert name_of(info.value) == "datum.sidecar_without_datum"
    # A synthesised ridge (no real place) needs no block and is not refused.
    ridge = _heightfield({"generator": "ridge"})
    assert datum_for_heightfield(ridge, require_block=True)["undulation_m"] is None


# -- the bake: sidecar, crop, dted, cdb ---------------------------------------

LOCATION = glo30.Location(
    key="testpeak", title="synthetic test peak", tiles=("X",),
    bbox=(45.82, 45.98, 7.02, 7.18), crs="EPSG:32632",
    origin_lat=45.9, origin_lon=7.1, snowline_m=2500.0,
    summits=(("Test Peak", 45.9, 7.1, 3000.0),))


def _bake(tmp_path, monkeypatch, geoid_model="auto", calls=None):
    def fake_fetch(loc, cache_dir):
        if calls is not None:
            calls.append(loc.key)
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return [_synthetic_tile(glo30.tile_path(cache_dir, "X"), 45.8, 7.0)]

    monkeypatch.setattr(glo30, "fetch", fake_fetch)
    raw, report = glo30.bake(LOCATION, tmp_path / "cache", tmp_path / "out",
                             ground_sample_distance_m=90.0, geoid_model=geoid_model)
    assert report["ok"]
    return raw


@pytest.fixture(scope="module")
def auto_bake(tmp_path_factory):
    monkeypatch = pytest.MonkeyPatch()
    try:
        raw = _bake(tmp_path_factory.mktemp("bake"), monkeypatch)
    finally:
        monkeypatch.undo()
    return raw


def test_the_bake_sidecar_carries_the_extended_datum_the_crop_dted_and_cdb(auto_bake):
    sidecar = json.loads(auto_bake.with_suffix(".json").read_text(encoding="utf-8"))
    provenance = sidecar["provenance"]
    datum = provenance["datum"]
    assert set(DATUM_KEYS) <= set(datum)
    expected = "EGM2008" if EGM2008_CACHED else "EGM96"
    assert datum["geoid_model_key"] == expected
    assert datum["interpolation"] == ("cubic" if EGM2008_CACHED else "bilinear")
    grid = geoid.grid_for_model(expected)
    assert datum["undulation_m"] == grid.undulation_at(45.9, 7.1)
    assert datum["undulation_bilinear_m"] == grid.undulation(45.9, 7.1)
    assert datum["grid_sha256"] == grid.sha256 == datum["undulation_source"]["sha256"]
    assert datum["bounds"]["scene_bbox_deg"] == list(LOCATION.bbox)
    assert datum["bounds"]["undulation_min_m"] <= datum["undulation_m"] <= datum["bounds"]["undulation_max_m"]
    assert datum["u_model_m"] == (0.10 if EGM2008_CACHED else 13.7)
    assert datum["tide_system"] == "not verified here"
    assert datum["physics_frame"]["frame"] == "orthometric"
    assert datum["orthometric_height_of_origin_m"] == pytest.approx(3000.0, abs=30.0)
    assert datum["ellipsoidal_height_of_origin_m"] == pytest.approx(
        datum["orthometric_height_of_origin_m"] + datum["undulation_m"])
    # The crop beside the raster, its sha256 as recorded, node-aligned.
    gtx = datum["gtx"]
    path = auto_bake.parent / gtx["file"]
    assert gtx["file"] == "testpeak_geoid.gtx" and path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == gtx["sha256"]
    assert gtx["alignment"]["node_aligned"] and gtx["margin_nodes"] == 1
    assert gtx["lat_south"] <= 45.82 - gtx["posting_deg"] and gtx["lat_north"] >= 45.98 + gtx["posting_deg"]
    samples = json.loads((auto_bake.parent / gtx["samples_file"]).read_text(encoding="utf-8"))
    assert samples["interior"]["count"] == 100 and samples["gtx"]["sha256"] == gtx["sha256"]
    assert provenance["geoid_files"]["gtx_sha256"] == gtx["sha256"]
    # DTED-style metadata from the bake, the accuracies as declared u_D.
    dted = provenance["dted"]
    assert dted["not_a_dted_file"] and "[unverified here]" in dted["standard"]
    assert dted["dsi"]["sw_corner"] == [45.82, 7.02] and dted["dsi"]["ne_corner"] == [45.98, 7.18]
    assert dted["dsi"]["lines"] == sidecar["height"] and dted["dsi"]["samples"] == sidecar["width"]
    assert dted["dsi"]["horizontal_datum"].startswith("WGS84") and "EGM2008" in dted["dsi"]["vertical_datum"]
    assert dted["acc"]["absolute_vertical_accuracy_m"] == 4.0
    assert dted["acc"]["u_D"]["vertical_sigma_m"] == pytest.approx(4.0 / 1.6449)
    assert dted["acc"]["bake_verification_vs_source"]["ok"] is True
    assert dted["source_tiles"] == provenance["tiles"]
    cdb = provenance["cdb_descriptor"]
    assert cdb["datastore_written"] is False and cdb["geocell"] == [45, 7]
    # The block comes back through the reader verbatim, and the runner's path takes it.
    field = Heightfield.read(auto_bake)
    assert datum_for_heightfield(field) == datum
    assert datum_for_heightfield(field, require_block=True) == datum
    assert auto_bake.with_suffix(".json").read_text(encoding="utf-8").isascii()
    assert (auto_bake.parent / gtx["samples_file"]).read_text(encoding="utf-8").isascii()


def test_a_bake_that_asks_for_egm2008_without_the_grid_refuses_before_fetching(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(geoid, "egm2008_available", lambda path=None: False)

    def missing():
        raise DatumError("geoid.grid_missing", "the EGM2008 geoid grid is absent from the bake cache")

    monkeypatch.setattr(geoid, "egm2008_grid", missing)
    with pytest.raises(DatumError) as info:
        _bake(tmp_path, monkeypatch, geoid_model="EGM2008", calls=calls)
    assert name_of(info.value) == "geoid.grid_missing"
    assert calls == []                      # refused before any tile was fetched
    raw = _bake(tmp_path, monkeypatch, geoid_model="auto", calls=calls)
    datum = Heightfield.read(raw).provenance["datum"]
    assert datum["geoid_model_key"] == "EGM96" and datum["model_difference_bound_m"] == 13.7
    assert calls == ["testpeak"]


def test_dted_metadata_refuses_a_bake_that_cannot_name_its_source():
    field = _heightfield({"origin_lat_deg": 46.005, "origin_lon_deg": 7.72})
    with pytest.raises(DatumError) as info:
        dted_block(field)
    assert name_of(info.value) == "dted.metadata_incomplete"
    assert "bbox_deg" in str(info.value) and "tiles" in str(info.value)


# -- the null test: with and without the block, one flight ------------------------

@pytest.fixture(scope="module")
def null_report(tmp_path_factory):
    from experiments.datum_null_test import measure

    return measure(tmp_path_factory.mktemp("dnt"))


def test_the_datum_block_moves_no_recorded_column_and_the_export_moves_by_n0(null_report):
    """Measured on the synthetic bake: the output digest is identical
    with and without the spec's datum block (bounded, 0 columns differ),
    and the exported ECEF position sits N0 further out radially than
    JSBSim's altitude taken as ellipsoidal, within 0.5 m at every sample
    (measured 3e-4 m: the normal-vs-radius angle)."""
    assert null_report["digests"]["identical"] and null_report["invariance"]["ok"]
    assert null_report["invariance"]["with"] == 0.0 and null_report["invariance"]["kind"] == "bounded"
    n0 = null_report["bake"]["undulation_m"]
    assert null_report["export"]["ok"] and null_report["export_bounded"]["ok"]
    assert null_report["export"]["difference"] == pytest.approx(n0, abs=0.01)
    assert null_report["radial_difference_m"]["worst_abs_error_vs_n0"] < 1e-3
    assert null_report["bake"]["geoid_model"] == ("EGM2008" if EGM2008_CACHED else "EGM96")
    record = null_report["run_record"]
    assert record["value"] == n0 and record["null_test"]["ok"]
    assert record["model"] == (f"{null_report['bake']['geoid_model']} "
                               f"{null_report['bake']['interpolation']}")
    assert record["readback"]["agrees"] and record["parameters"]["invariance"]["ok"]
    assert record["parameters"]["declared_model"] == null_report["bake"]["geoid_model"]
    assert record["parameters"]["gtx_sha256"] == null_report["bake"]["gtx_sha256"]
    assert record["uncertainty"]["u_input"]["value"] == (0.10 if EGM2008_CACHED else 13.7)
    assert null_report["spec_with_block"]["geoid_model"]["value"] == null_report["bake"]["geoid_model"]
    print(f"datum null test: N0 {n0:+.3f} m, digests identical {null_report['digests']['identical']}, "
          f"worst |radial - N0| {null_report['radial_difference_m']['worst_abs_error_vs_n0']:.2e} m, "
          f"{null_report['elapsed_s']:.1f} s")


def test_a_declared_model_that_is_not_the_bakes_refuses_by_name(auto_bake, monkeypatch):
    from core.scenario import runner

    field = Heightfield.read(auto_bake)
    other = "EGM96" if field.provenance["datum"]["geoid_model_key"] == "EGM2008" else "EGM2008"
    monkeypatch.setattr(runner, "configure_from_spec",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("flew")))
    with pytest.raises(DatumError) as info:
        runner.run_spec(spec_for(geoid_model=other), validate_first=False,
                        terrain_ground=TerrainGround(field))
    assert name_of(info.value) == "datum.model_mismatch"


# -- the independent verifier clause -------------------------------------------------

def _manifest_for(raw: Path):
    datum = json.loads(raw.with_suffix(".json").read_text(encoding="utf-8"))["provenance"]["datum"]
    return {"datum": datum, "scene": {"key": "terrain", "terrain": str(raw.with_suffix(""))}}


def test_datum_independent_passes_the_bakes_own_crop_through_proj(auto_bake):
    check = _independent_verifier()(_manifest_for(auto_bake))
    assert check.status == "PASS", check.detail
    assert "100 interior points" in check.detail and "inf outside" in check.detail
    assert "+inv" in check.detail


def test_datum_independent_is_not_run_without_a_block_a_crop_or_a_bake_path(auto_bake):
    verify = _independent_verifier()
    assert verify({"datum": flat_datum_block(0.0)}).status == "NOT RUN"
    assert verify({}).status == "NOT RUN"
    manifest = _manifest_for(auto_bake)
    without_crop = dict(manifest, datum={k: v for k, v in manifest["datum"].items() if k != "gtx"})
    assert verify(without_crop).status == "NOT RUN"
    assert verify(dict(manifest, scene={"key": "terrain", "terrain": None})).status == "NOT RUN"


def _corrupted_copy(raw: Path, tmp_path: Path, mutate):
    """The bake's files copied to tmp_path with the gtx bytes mutated and
    the block's sha256 re-recorded (so the sha check is not what fails)."""
    import shutil

    for file in raw.parent.iterdir():
        shutil.copy(file, tmp_path / file.name)
    manifest = _manifest_for(tmp_path / raw.name)
    gtx_path = tmp_path / manifest["datum"]["gtx"]["file"]
    data = bytearray(gtx_path.read_bytes())
    mutate(data)
    gtx_path.write_bytes(bytes(data))
    manifest["datum"]["gtx"]["sha256"] = hashlib.sha256(bytes(data)).hexdigest()
    return manifest


def test_datum_independent_fails_an_altered_crop_by_name(auto_bake, tmp_path):
    verify = _independent_verifier()
    # 1. one byte of a node flipped, sha not re-recorded: the file is not the bake's.
    manifest = _manifest_for(auto_bake)
    import shutil
    for file in auto_bake.parent.iterdir():
        shutil.copy(file, tmp_path / file.name)
    manifest["scene"]["terrain"] = str((tmp_path / auto_bake.name).with_suffix(""))
    gtx_path = tmp_path / manifest["datum"]["gtx"]["file"]
    data = bytearray(gtx_path.read_bytes())
    data[60] ^= 0x40
    gtx_path.write_bytes(bytes(data))
    check = verify(manifest)
    assert check.status == "FAIL" and check.failure == "scene.datum" and "sha256" in check.detail
    # 2. the header corner moved a third of a node (sha re-recorded): not on whole nodes.
    def shift(data):
        lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">ddddii", bytes(data[:40]))
        data[:40] = struct.pack(">ddddii", lat0 + dlat / 3.0, lon0, dlat, dlon, rows, cols)
    check = verify(_corrupted_copy(auto_bake, tmp_path / "shift" if (tmp_path / "shift").mkdir() is None else tmp_path, shift))
    assert check.status == "FAIL" and "whole nodes" in check.detail
    # 3. the nodes negated (a forward-sign crop): PROJ reads -N at the origin.
    def negate(data):
        values = np.frombuffer(bytes(data[40:]), dtype=">f4")
        data[40:] = (-values).astype(">f4").tobytes()
    (tmp_path / "neg").mkdir()
    check = verify(_corrupted_copy(auto_bake, tmp_path / "neg", negate))
    assert check.status == "FAIL" and "sign flip" in check.detail
    # 4. every node raised by 0.05 m (a crop of other data): the interior disagrees.
    def raise_nodes(data):
        values = np.frombuffer(bytes(data[40:]), dtype=">f4")
        data[40:] = (values + 0.05).astype(">f4").tobytes()
    (tmp_path / "raise").mkdir()
    check = verify(_corrupted_copy(auto_bake, tmp_path / "raise", raise_nodes))
    assert check.status == "FAIL" and "origin" in check.detail
    # 5. a stale block: the bake's crop is right, the recorded bilinear N is not.
    stale = _manifest_for(auto_bake)
    stale["datum"] = dict(stale["datum"], undulation_bilinear_m=stale["datum"]["undulation_bilinear_m"] + 0.5)
    check = verify(stale)
    assert check.status == "FAIL" and "tolerance" in check.detail
    # 6. the crop file gone.
    (tmp_path / "gone").mkdir()
    gone = _corrupted_copy(auto_bake, tmp_path / "gone", lambda data: None)
    (tmp_path / "gone" / gone["datum"]["gtx"]["file"]).unlink()
    check = verify(gone)
    assert check.status == "FAIL" and "absent" in check.detail
    # 7. a stale samples file (the origin agrees, the interior does not):
    # every recorded interior value raised 0.05 m, its sha256 re-recorded.
    (tmp_path / "stale").mkdir()
    stale_samples = _corrupted_copy(auto_bake, tmp_path / "stale", lambda data: None)
    samples_path = tmp_path / "stale" / stale_samples["datum"]["gtx"]["samples_file"]
    document = json.loads(samples_path.read_text(encoding="utf-8"))
    document["interior"]["undulation_bilinear_m"] = [
        v + 0.05 for v in document["interior"]["undulation_bilinear_m"]]
    samples_path.write_text(json.dumps(document), encoding="utf-8")
    stale_samples["datum"]["gtx"]["samples_sha256"] = hashlib.sha256(
        samples_path.read_bytes()).hexdigest()
    check = verify(stale_samples)
    assert check.status == "FAIL" and "interior points" in check.detail
    # 8. fewer than the 100 interior points the contract names.
    document["interior"] = {k: (v[:99] if isinstance(v, list) else v) for k, v in document["interior"].items()}
    samples_path.write_text(json.dumps(document), encoding="utf-8")
    stale_samples["datum"]["gtx"]["samples_sha256"] = hashlib.sha256(
        samples_path.read_bytes()).hexdigest()
    check = verify(stale_samples)
    assert check.status == "FAIL" and "99 interior points" in check.detail


def test_the_independent_clause_imports_no_producer_and_names_its_check():
    for fragment in ("import core.terrain", "from core.terrain", "from ..terrain", "import geoid"):
        assert fragment not in VERIFY_DATUM_PATCH, fragment
    assert 'Check("datum_independent"' in VERIFY_DATUM_PATCH
    assert "+inv +proj=vgridshift" in VERIFY_DATUM_PATCH
    namespace = _patch_namespace()
    assert namespace["DATUM_INDEPENDENT_TOL_M"] == 0.01


# -- the registry entries the integrator lands (returned text, tested here) ----------

REGISTRY_PATCH = '''
    # -- D1: the datum block (spec fields land with D1). The three words
    # declare and check; the applied variable is scene.geoid_undulation_m
    # (its record carries the channels' readback), so a pair on any of them
    # is the bounded invariance experiments/datum_null_test.py measures:
    # the recorded columns are identical, the channels are recorded either
    # way (0 where no geoid applies, by the frame's definition).
    VariableRecord(
        name="datum.vertical", spec_path="datum.vertical", unit="word",
        effect_channels=(EffectChannel("undulation_m", "m"), EffectChannel("hae_m", "m")),
        null_value="orthometric",
        null_basis="the heights as built: orthometric numbers in JSBSim's ellipsoidal slot; "
                   "'ellipsoidal' is refused by name (datum.physics_frame_unsupported), so no "
                   "pair can fly it",
        u_input_rule=UInputRule(note="a word: no bin, no spread; the datum's uncertainty is "
                                     "the geoid model's declared u_model_m on the applied record"),
        host_channels=("undulation_m", "hae_m")),
    VariableRecord(
        name="datum.physics_frame", spec_path="datum.physics_frame", unit="word",
        effect_channels=(EffectChannel("undulation_m", "m"), EffectChannel("hae_m", "m")),
        null_value="orthometric",
        null_basis="the frame as built (C2); 'ellipsoid' (C3) is refused by name until the "
                   "physics frame handles it",
        u_input_rule=UInputRule(note="a word: no bin, no spread"),
        host_channels=("undulation_m", "hae_m")),
    VariableRecord(
        name="datum.geoid_model", spec_path="datum.geoid_model", unit="word",
        effect_channels=(EffectChannel("undulation_m", "m"), EffectChannel("hae_m", "m")),
        null_value=None,
        null_basis="unstated: the bake's own model is accepted; a stated model is checked "
                   "against the bake's (datum.model_mismatch) and moves no channel -- the "
                   "pair is the bounded invariance (digests identical, measured)",
        u_input_rule=UInputRule(note="a word: no bin, no spread; the model's declared "
                                     "u_model_m rides on the applied record"),
        host_channels=("undulation_m", "hae_m")),
'''


def test_the_registry_entries_claim_every_datum_field_and_name_recorded_channels(flat_run):
    """The returned registry text, built here: one entry per DatumSpec
    field (so record.unregistered refuses nothing a datum block states
    once integrated), every effect channel a column a real run records."""
    from core.registry import (
        REGISTRY, EffectChannel, Registry, UInputRule, VariableRecord,
    )

    namespace = {"VariableRecord": VariableRecord, "EffectChannel": EffectChannel,
                 "UInputRule": UInputRule}
    entries = eval("(" + REGISTRY_PATCH + ")", namespace)
    if "datum" in REGISTRY.sections():
        # Integrated: the live registry carries the same entries.
        for entry in entries:
            assert REGISTRY.get(entry.name).to_dict() == entry.to_dict(), entry.name
    registry = Registry(tuple(e for e in REGISTRY if e.spec_section != "datum") + entries)
    assert set(registry.spec_fields()) >= {f"datum.{f}" for f in DatumSpec.FIELD_ORDER}
    assert "datum" in registry.sections()
    for entry in entries:
        assert entry.unit == "word" and entry.spec_path == entry.name
        for channel in entry.effect_channels:
            assert channel.name in flat_run.telemetry.columns, channel.name
    data = spec_for(geoid_model="EGM2008").to_dict()
    assert registry.unregistered_fields(data) == []
    assert set(registry.stated_variables(data)) == {"datum.vertical", "datum.physics_frame",
                                                    "datum.geoid_model"}
    if "datum" in REGISTRY.sections():
        assert set(REGISTRY.spec_fields()) >= {f"datum.{f}" for f in DatumSpec.FIELD_ORDER}


def test_the_texts_the_engine_or_a_reader_sees_are_ascii():
    import inspect

    from core.scenario import runner

    for rel in ("tests/test_datum_block.py", "experiments/datum_null_test.py"):
        assert (REPO / rel).read_text(encoding="utf-8").isascii(), rel
    # blocks.py, spec.py, runner.py and glo30.py carry section signs from
    # earlier phases; the D1 text in them is ASCII.
    assert inspect.getsource(DatumSpec).isascii()
    for function in (runner.scene_datum_for, runner.datum_run, runner.refuse_datum_spec,
                     runner._digest_columns, glo30.bake):
        assert inspect.getsource(function).isascii(), function.__name__
    assert VERIFY_DATUM_PATCH.isascii() and REGISTRY_PATCH.isascii() and VALIDATE_DATUM_PATCH.isascii()
