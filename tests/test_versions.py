"""INT-final: the advancement addition's one version bump, pinned.

Every version the addition moved, each moved once (docs/ADVANCEMENTS_BLUEPRINT.md
"Versions and keys"):

* ``SPEC_VERSION`` 8 -> 9. The addition's blocks stay optional and
  absent-canonical, so a version-9 spec that states none of them is a
  version-8 spec with one number changed -- measured against the committed
  version-8 examples frozen under tests/data/spec8_examples. A version-8
  dict still reads (as 9) unless it states a version-9 block, which is
  refused by name (spec.version); version 7 and older refuse as before.
* ``MANIFEST_VERSION`` 6 -> 7, ``SUPPORTED_MANIFEST_VERSIONS`` (3, 4, 5, 6, 7),
  docs/schemas/capture_manifest.v7.schema.json = v6 plus every optional
  block the addition wrote (v6 kept beside it); the aggregate object ids
  ``building:all`` / ``vegetation:all`` valid at 7 (v6's pattern refuses
  them).
* ``RECORD_VERSION`` 1 -> 2: the structured model block is ``model``, the
  one-line name ``model_name``; a record-1 dict (and block) still reads,
  renamed on the way in.
* The limits monitor's flag columns ``exceed_*`` / ``any_exceedance`` ->
  ``*_flag``, read as unit 1 from the name alone.
* The verifier's ``georeference`` check (D2's render.json pin), its text
  pinned by sha256 and its clauses by corruption.

What is NOT claimed: nothing here flies. The capture that writes a real v7
manifest is tests/test_capture_schema.py's; the render host that writes
render.json's georeference block is Windows-side and unverified here.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest
import yaml

from core.capture import verify
from core.capture.manifest import (
    MANIFEST_VERSION, SUPPORTED_MANIFEST_VERSIONS, channel_unit, suffix_unit,
)
from core.capture.schema import SCHEMA_DIR, load_schema, validate
from core.messages import explain, is_catalogued
from core.records import (
    READABLE_RECORD_VERSIONS, RECORD_VERSION, AppliedVariable, JsbsimWrite, Model, NullTest,
    Readback, read_records, records_block, upgrade_record,
)
from core.registry import REGISTRY
from core.scenario import spec as spec_module
from core.scenario.blocks import SceneSpec
from core.scenario.camera import IR_FIELD, PASS_FIELDS, SENSING_FIELDS
from core.scenario.spec import (
    READABLE_SPEC_VERSIONS, SPEC9_BLOCKS, SPEC9_CAMERA_FIELDS, SPEC9_ENVIRONMENT_FIELDS,
    SPEC9_SCENE_FIELDS, SPEC_VERSION, ScenarioSpec, spec9_keys_in,
)
from core.telemetry import limits

from tests.test_registry import EXAMPLE_DIGESTS

REPO = Path(__file__).resolve().parents[1]
SPEC8 = Path(__file__).resolve().parent / "data" / "spec8_examples"

#: The committed examples' digests at spec 8 (pinned by tests/test_registry.py
#: before INT-final), re-measured here from the frozen version-8 files.
SPEC8_DIGESTS = {
    "cameras_event_trigger.yaml": "cb2f5b5500584bd84c8aa84749c854a9c67f1c366db2ec97e9cb0c8ee150b8b0",
    "cameras_hazard_refusal.yaml": "148f87bc37eab96c8f029e048dbf4f8328ad3247fa0596f10e71c81914d509de",
    "cameras_mountain_refusal.yaml": "58a36aa0943b0dd895d79c89d7031525b6fc29e55ec47b927b4b3e7ccbfb2496",
    "cameras_multi.yaml": "84e53a6931489f90fec8d0a750a1fd745bb630d0a2186befba659c68e2396f45",
    "cameras_refusal.yaml": "d3565392215f6db2b66060c41554d10b4916779b9319e2c3a7063b3a04eb6a9a",
    "cameras_terrain.yaml": "4b7b5dbdc8ba0a04cb3408f6e70c19be3d0e28c4053762ee30551c23d751acf3",
    "cameras_waypoint.yaml": "9760294005e1efcae1777ad4a2035fe3733d219428c477c6c7caf2f0220b2372",
    "randomized.yaml": "102d38250e4b7c9b4b6737af5e3e2886fad0748aa4e7af825ce8388e4fe7fda1",
}


def _canonical_digest(payload) -> str:
    """The digest rule, re-implemented (not imported)."""
    payload = dict(payload)
    payload.pop("prompt", None)
    payload.pop("notes", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


# -- the constants -------------------------------------------------------------------------

def test_the_three_versions_and_what_each_reads():
    assert SPEC_VERSION == 9 and READABLE_SPEC_VERSIONS == (8, 9)
    assert MANIFEST_VERSION == 7 and SUPPORTED_MANIFEST_VERSIONS == (3, 4, 5, 6, 7)
    assert RECORD_VERSION == 2 and READABLE_RECORD_VERSIONS == (1, 2)


# -- spec 9 --------------------------------------------------------------------------------

def test_the_version_9_keys_are_the_ones_the_classes_carry():
    """The named version-9 keys are exactly the optional fields the spec,
    scene and camera classes gained under 8: nothing left out, nothing
    invented."""
    assert SPEC9_SCENE_FIELDS == SceneSpec.OPTIONAL_FIELDS
    assert SPEC9_CAMERA_FIELDS == tuple(SENSING_FIELDS) + tuple(PASS_FIELDS) + (IR_FIELD,)
    assert SPEC9_ENVIRONMENT_FIELDS == ("precipitation_rate_mmh", "time_of_day")
    fields = ScenarioSpec.__dataclass_fields__
    for name in SPEC9_BLOCKS:
        assert name in fields, name
    assert "precipitation_rate_mmh" in fields
    assert "time_of_day" in fields


@pytest.mark.parametrize("name", sorted(SPEC8_DIGESTS))
def test_a_committed_version_8_example_reads_at_9_with_only_the_version_line_moved(name):
    frozen_text = SPEC8.joinpath(name).read_text(encoding="utf-8")
    frozen = yaml.safe_load(frozen_text)
    assert frozen["spec_version"] == 8
    assert spec9_keys_in(frozen) == []
    assert _canonical_digest(frozen) == SPEC8_DIGESTS[name]          # the spec-8 pin
    spec = ScenarioSpec.from_dict(copy.deepcopy(frozen))
    reread = spec.to_dict()
    assert reread["spec_version"] == 9
    assert {k: v for k, v in reread.items() if k != "spec_version"} == \
        {k: v for k, v in frozen.items() if k != "spec_version"}
    # The digest moves with the hashed version line and nothing else.
    assert spec.digest() == EXAMPLE_DIGESTS[f"examples/{name}"] != SPEC8_DIGESTS[name]
    unversioned = dict(reread); unversioned.pop("spec_version")
    frozen_unversioned = dict(frozen); frozen_unversioned.pop("spec_version")
    assert _canonical_digest(unversioned) == _canonical_digest(frozen_unversioned)
    # The committed example is the writer's output: header + to_yaml(),
    # byte for byte the frozen file with its version line moved.
    current = (REPO / "examples" / name).read_text(encoding="utf-8")
    assert current == frozen_text.replace("spec_version: 8\n", "spec_version: 9\n", 1)
    header = current[:current.index("spec_version:")]
    assert header.startswith("#") and len(header.splitlines()) >= 3    # says what it exercises
    assert current == header + ScenarioSpec.read(REPO / "examples" / name).to_yaml()


def test_every_committed_spec_example_is_at_9():
    specs = [p for p in sorted((REPO / "examples").glob("*.yaml"))
             if "spec_version" in (yaml.safe_load(p.read_text(encoding="utf-8")) or {})]
    # The eight frozen at spec 8, plus traffic.yaml (written at spec 9).
    assert len(SPEC8_DIGESTS) == 8
    assert sorted(p.name for p in specs) == sorted([*SPEC8_DIGESTS, "traffic.yaml"])
    for path in specs:
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["spec_version"] == 9, path


def _spec9_data():
    """A version-9 dict with every version-9 key stated (values are not
    parsed before the version rule, so a placeholder mapping serves)."""
    data = ScenarioSpec.read(REPO / "examples/cameras_multi.yaml").to_dict()
    for name in SPEC9_BLOCKS:
        data[name] = {"stated": True}
    data.setdefault("scene", {})
    for name in SPEC9_SCENE_FIELDS:
        data["scene"][name] = {"value": 1}
    for name in SPEC9_ENVIRONMENT_FIELDS:
        data["environment"][name] = {"value": 1}
    for name in SPEC9_CAMERA_FIELDS:
        data["cameras"][1][name] = {"value": 1}
    return data


def test_a_version_9_key_under_version_8_is_refused_by_name():
    data = _spec9_data()
    stated = spec9_keys_in(data)
    assert stated == (list(SPEC9_BLOCKS) + [f"scene.{n}" for n in SPEC9_SCENE_FIELDS]
                      + [f"environment.{n}" for n in SPEC9_ENVIRONMENT_FIELDS]
                      + [f"cameras[1].{n}" for n in SPEC9_CAMERA_FIELDS])
    for key in stated:
        one = ScenarioSpec.read(REPO / "examples/cameras_multi.yaml").to_dict()
        one["spec_version"] = 8
        section, _, leaf = key.partition(".")
        if not leaf:
            one[section] = {"stated": True}
        elif section.startswith("cameras["):
            one["cameras"][1][leaf] = {"value": 1}
        else:
            one.setdefault(section, {})[leaf] = {"value": 1}
        with pytest.raises(ValueError) as err:
            ScenarioSpec.from_dict(one)
        message = str(err.value)
        assert f"spec_version 8 with the version-9 block(s) {key} is not supported" in message
        assert explain(err.value)["rule"] == "spec.version", key
    assert is_catalogued("spec.version")


def test_a_real_stated_block_reads_at_9_and_is_refused_under_8():
    spec = ScenarioSpec.read(REPO / "examples/cameras_waypoint.yaml")
    spec.set("atmosphere.temperature_deviation_c", 15.0, frm="a hot day")
    data = spec.to_dict()
    assert data["spec_version"] == 9 and "atmosphere" in data
    assert ScenarioSpec.from_dict(copy.deepcopy(data)).to_dict() == data
    data["spec_version"] = 8
    with pytest.raises(ValueError, match=re.escape("version-9 block(s) atmosphere is not "
                                                   "supported")):
        ScenarioSpec.from_dict(data)
    for version in (7, 10, None):
        data["spec_version"] = version
        with pytest.raises(ValueError, match=f"spec_version {version!r} is not supported"):
            ScenarioSpec.from_dict(data)


def test_the_version_rule_keeps_its_one_comparison():
    """The spec reader's first test is still ``version != SPEC_VERSION``
    (a mutation to it lets old versions load), and the history comment
    states version 9's rule."""
    source = inspect.getsource(ScenarioSpec.from_dict)
    assert 'version = data.get("spec_version")\n        if version != SPEC_VERSION:' in source
    text = Path(spec_module.__file__).read_text(encoding="utf-8")
    assert "# 9 (2026-09-29): the advancement addition's one bump" in text


# -- manifest 7 and the v7 schema ----------------------------------------------------------

V6 = SCHEMA_DIR / "capture_manifest.v6.schema.json"
V7 = SCHEMA_DIR / "capture_manifest.v7.schema.json"


def test_v7_is_v6_plus_the_additions_and_v6_is_kept():
    v6, v7 = load_schema(V6), load_schema(V7)
    assert v6["properties"]["manifest_version"]["const"] == 6
    assert v7["properties"]["manifest_version"]["const"] == 7
    assert v7["required"] == v6["required"]                  # every addition is optional
    assert set(v6["properties"]) < set(v7["properties"])
    assert set(v6["$defs"]) < set(v7["$defs"])
    for name in ("camera_block", "frame_record"):
        assert v6["$defs"][name]["required"] == v7["$defs"][name]["required"]
        assert set(v6["$defs"][name]["properties"]) < set(v7["$defs"][name]["properties"])
    added = set(v7["properties"]) - set(v6["properties"])
    # presence: scene vs labelled per taxonomy class (optional, like the rest).
    assert added == {"datum", "applied_variables", "uncertainty", "instruments", "null_tests",
                     "look", "landcover", "licences", "interop", "presence"}
    assert {"buildings", "runway", "land_cover"} <= set(v7["properties"]["scene"]["properties"])
    assert "vertical_datum" in v7["properties"]["frame"]["properties"]
    assert {"sensing", "stereo"} <= set(v7["$defs"]["camera_block"]["properties"])
    assert {"radiometry", "passes", "ir", "dis"} <= set(v7["$defs"]["frame_record"]["properties"])
    assert v7["properties"]["applied_variables"]["anyOf"][0]["properties"][
        "record_version"]["const"] == RECORD_VERSION
    assert V7.read_text(encoding="utf-8").isascii()


def test_the_aggregate_ids_are_valid_at_7_and_refused_at_6():
    v6, v7 = load_schema(V6), load_schema(V7)
    node6 = v6["$defs"]["scene_object"]["properties"]["id"]
    node7 = v7["$defs"]["scene_object"]["properties"]["id"]
    for object_id in ("vegetation:all", "building:all"):
        assert validate(object_id, node7) == []
        assert validate(object_id, node6)                    # the reason v7 exists
    for object_id in ("aircraft:B747:0", "terrain", "traffic:0"):
        assert validate(object_id, node7) == [] and validate(object_id, node6) == []
    for bad in ("building:", "Building:all", "building:all:", "building:any"):
        assert validate(bad, node7), bad


def test_the_state_units_vocabulary_covers_every_unit_this_build_writes():
    """The v7 schema's unit enum is the suffix table's and the registry's
    units plus s, g, 1 and ?: every channel this build can name validates,
    so the schema and the writer cannot drift apart silently."""
    enum = set(load_schema(V7)["$defs"]["unit"]["enum"])
    from core.capture.manifest import _UNIT_SUFFIXES

    assert {unit for _, unit in _UNIT_SUFFIXES} <= enum
    assert set(REGISTRY.channel_units().values()) <= enum
    assert {"s", "g", "1", "?"} <= enum
    for new in ("kg/m^3", "kg m^2", "m/s^2", "rad/s", "hPa", "%", "uT", "K", "rpm", "m^2/s"):
        assert new in enum, new


def _frame_record():
    """One frame record with every version-6 required key (types only)."""
    matrix3 = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    return {
        "index": 0, "camera_id": "chase0", "file": "frames/chase0/frame_0000.png",
        "t_s": 0.0, "sample_index": 0, "position_north_m": 0.0, "position_east_m": 0.0,
        "position_alt_m": 100.0, "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0, "focal_length_mm": 35.0,
        "sensor_width_mm": 36.0, "sensor_height_mm": 24.0, "width_px": 1280,
        "height_px": 720, "near_m": 0.1, "far_m": 1000.0, "principal_point_px": [640.0, 360.0],
        "fx_px": 1244.4, "fy_px": 1050.0, "intrinsic_matrix": matrix3,
        "projection_matrix": [row + [0.0] for row in matrix3],
        "aircraft": {"north_m": 0.0, "east_m": 0.0, "alt_m": 100.0, "roll_deg": 0.0,
                     "pitch_deg": 0.0, "heading_deg": 0.0},
        "state": {"t": 0.0, "altitude_m": 100.0},
        "labels": {"bbox_2d": None, "bbox_2d_unclipped": None, "truncation": None,
                   "in_frame": False, "bbox_3d_camera": None, "keypoints": {},
                   "horizon": {}, "objects": [{
                       "id": "vegetation:all", "int_id": 3, "class_id": 4, "bbox_2d": None,
                       "bbox_2d_unclipped": None, "truncation": None, "in_frame": None,
                       "bbox_2d_tight": None, "bbox_2d_hull": None, "visible_fraction": None,
                       "occluded_by": [], "atmospheric_transmittance": None,
                       "depth_projected_m": None, "depth_min_m": None, "depth_median_m": None,
                       "bbox_3d_camera": None, "keypoints": {}, "horizon": None,
                       "not_claimed": [], "basis": {"bbox_2d_hull": "x",
                                                    "atmospheric_transmittance": "x",
                                                    "engine": "x"}}]},
        "sensor": {"profile": "ideal_pinhole", "angular_rate_rad_s": [0.0, 0.0, 0.0],
                   "labels_sensor": {}},
    }


def _manifest_7():
    """A version-7 manifest with every version-6 required key and none of
    the addition's blocks."""
    sha = "0" * 64
    return {
        "manifest_version": 7, "spec_digest": sha, "simulation_digest": sha,
        "output_digest": sha, "solve_source": "headless pre-run", "seed": 7,
        "aircraft": "c172p", "scene": {"key": "flat", "terrain": None, "terrain_sha256": None},
        "frame": {"crs": "EPSG:32632", "origin_lat_deg": 46.0, "origin_lon_deg": 7.7,
                  "origin_x_m": 400000.0, "origin_y_m": 5094000.0, "declared_on_card": True},
        "software_revision": "unknown", "landmarks": [], "conditions": {},
        "state_units": {"t": "s", "altitude_m": "m"},
        "airframe": {"aircraft": "c172p", "length_m": 8.3, "span_m": 11.0, "height_m": 2.7,
                     "keypoints": []},
        "label_conventions": {}, "assets": {}, "randomization": None,
        "cameras": [{"camera_id": "chase0", "preset": "chase", "horizon_stable": True,
                     "inherits_roll": False, "spec": None, "schedule_basis": "count",
                     "trigger": "count", "capture_count": 1, "pose_track_digest": sha,
                     "profile": {}}],
        "frames": [_frame_record()],
        "objects": [
            {"id": "aircraft:c172p:0", "int_id": 1, "class": "aircraft", "class_id": 1,
             "instance": 0, "role": "primary", "mesh_sha256": None, "licence": None,
             "in_scene": True, "labelled": True},
            {"id": "building:all", "int_id": 2, "class": "building", "class_id": 3,
             "instance": 0, "role": "scene", "mesh_sha256": sha, "licence": "ODbL-1.0",
             "in_scene": True, "labelled": True},
            {"id": "vegetation:all", "int_id": 3, "class": "vegetation", "class_id": 4,
             "instance": 0, "role": "scene", "mesh_sha256": None, "licence": None,
             "in_scene": True, "labelled": True}],
        "taxonomy": ["aircraft", "terrain", "building", "vegetation"],
        "traffic": [],
    }


def _record_2() -> dict:
    return AppliedVariable(
        name="atmosphere.temperature_deviation_c", value=15.0, unit="degC", source="user",
        model_name="ISA deviation (US Standard Atmosphere 1976)",
        properties_written=("atmosphere/delta-T",), telemetry_columns=("temperature_k",),
        frame_keys=("temperature_k",),
        null_test=NullTest("temperature", "K", 303.15, 288.15, 0.1),
        frm="a hot day", std="MIL-HDBK-310",
        readback=Readback("atmosphere/delta-T", 27.0, 27.0, 0.0, basis="exact"),
        jsbsim_writes=(JsbsimWrite("atmosphere/delta-T", "before trim and every step"),),
        model=Model("ISA deviation", standard="USSA 1976", version="1"),
        uncertainty={"u_input": {"value": 1.0, "unit": "degC", "rule": "declared",
                                 "sensitivity": {"temperature_k": 1.0}},
                     "u_num": None}).to_dict()


def _every_block(manifest):
    """Every optional block the addition added, in the producers' shapes."""
    sha = "1" * 64
    m = copy.deepcopy(manifest)
    m["datum"] = {"vertical_datum_of_heights": "EGM2008 orthometric", "geoid_model": "EGM2008",
                  "undulation_m": 53.85, "note": "the bake's own block"}
    m["applied_variables"] = records_block([AppliedVariable.from_dict(_record_2())])
    m["uncertainty"] = {"u_num": {"altitude_m": {"srq": "altitude_m", "value": 0.3,
                                                 "basis": "dt/2 twin"}},
                        "u_input": {}, "u_val": {}, "form": "ASME V&V 20; u_D absent per run",
                        "not_claimed": ["u_D"]}
    m["instruments"] = {"instruments_version": 1, "rate_hz": 120.0, "rate_basis": "fdm loop",
                        "instruments": {"imu": {}}, "profiles": {"imu": {}},
                        "file": "instruments.npz", "sha256": sha, "columns": ["t"],
                        "not_claimed": ["no device calibrated"]}
    m["null_tests"] = {"atmosphere.temperature_deviation_c": {
        "variable": "atmosphere.temperature_deviation_c", "kind": "reached",
        "spec_path": "atmosphere.temperature_deviation_c", "digests": {}, "effect": {},
        "verdict": "reached"}}
    m["look"] = {"night": {}, "precipitation": {}, "cloud_drift": {}, "night_sky": {}}
    m["landcover"] = {"dataset": "ESA WorldCover v200", "legend": [], "nodata": 0,
                      "class_map": {}, "grid": {}, "image": {}}
    m["licences"] = [{"asset": "terrain", "kind": "terrain", "licence": "CC-BY-4.0",
                      "spdx": "CC-BY-4.0", "source": None, "attribution": None,
                      "ml_use": "allowed", "sha256": sha, "reaches": ["pixels"], "note": None}]
    m["interop"] = {"dis": {"stream_file": "dis_entity_state.bin"}}
    m["frame"]["vertical_datum"] = "EGM2008 orthometric"
    m["scene"]["buildings"] = {"key": "k", "file": "k.jsonl", "sha256": sha, "licence": "ODbL-1.0",
                               "count": 12, "document": "b.json", "document_sha256": sha,
                               "object_id": "building:all"}
    m["scene"]["runway"] = {"designator": "09", "pad": "p", "pad_sha256": sha,
                            "parent_sha256": sha, "document": "r.json", "document_sha256": sha,
                            "markings": "m.png", "markings_sha256": sha}
    m["scene"]["land_cover"] = {"dataset": "ESA WorldCover v200"}
    m["cameras"][0]["sensing"] = {"requested_by": ["camera.exposure_compensation_ev"],
                                  "exposure": {}, "radiometry": {}, "bands": None,
                                  "optics": None, "motion_blur": None, "ir": {},
                                  "records": "applied_variables (this camera)"}
    m["cameras"][0]["stereo"] = {"role": "left", "left_camera_id": "chase0",
                                 "right_camera_id": "chase0_right", "baseline_m": 0.5,
                                 "side": "right"}
    frame = m["frames"][0]
    frame["radiometry"] = {"luminance_cd_m2_per_unit": 1.0, "calibration_status": "predicted"}
    frame["passes"] = {"requested": ["normal", "flow"]}
    frame["ir"] = {"proxy": True, "band": "LWIR", "file": "frame_0000_ir.f32", "basis": "rendered"}
    frame["dis"] = {"pdu_index": 0, "byte_offset": 0}
    frame["labels"]["landcover"] = {"file": "frame_0000_landcover.png"}
    m["state_units"].update({"nz_pos_flag": "1", "rho_kgm3": "kg/m^3", "f_x_mps2": "m/s^2",
                             "p_rads": "rad/s", "pressure_hpa": "hPa", "rh_pct": "%",
                             "b_north_ut": "uT", "temperature_k": "K", "engine0_rpm": "rpm"})
    return m


def _null_blocks(manifest):
    """Every optional block null: what a frame sidecar carries for a block
    its run did not write."""
    m = copy.deepcopy(manifest)
    for key in ("datum", "applied_variables", "uncertainty", "instruments", "null_tests",
                "look", "landcover", "licences", "interop"):
        m[key] = None
    m["frame"]["vertical_datum"] = None
    for key in ("buildings", "runway", "land_cover"):
        m["scene"][key] = None
    m["cameras"][0]["sensing"] = None
    m["cameras"][0]["stereo"] = None
    for key in ("radiometry", "passes", "ir", "dis"):
        m["frames"][0][key] = None
    m["frames"][0]["labels"]["landcover"] = None
    return m


def _nulls_with_basis(manifest):
    """Every block present with its values null and the basis stated: the
    flat datum (no undulation), the ideal instruments (no file), an IR
    frame before the render, a frame no PDU covers, a record whose null
    test and model block were not measured."""
    m = _every_block(manifest)
    m["datum"] = {"vertical_datum_of_heights": "flat slab", "geoid_model": None,
                  "undulation_m": None, "note": "no georeferenced heights: N null, never 0"}
    m["instruments"].update({"file": None, "sha256": None})
    m["frames"][0]["ir"].update({"file": None, "basis": "no IR frame until a render exists"})
    m["frames"][0]["dis"] = {"pdu_index": None, "byte_offset": None}
    record = _record_2()
    record.update({"null_test": None, "readback": None, "model": None, "uncertainty": None,
                   "value": None})
    m["applied_variables"]["applied_variables"] = [record]
    m["licences"][0].update({"licence": None, "spdx": None, "sha256": None})
    m["scene"]["runway"].update({"pad": None, "markings": None, "markings_sha256": None})
    return m


def test_the_v7_schema_validates_every_block_present_null_and_null_with_basis():
    schema = load_schema(V7)
    base = _manifest_7()
    assert validate(base, schema) == []
    assert validate(_every_block(base), schema) == []
    assert validate(_null_blocks(base), schema) == []
    assert validate(_nulls_with_basis(base), schema) == []
    # v6 reads the same manifest at 6 except for the aggregate ids.
    older = _every_block(base)
    older["manifest_version"] = 6
    problems = validate(older, load_schema(V6))
    assert problems and all("objects[" in p and ":all" in p for p in problems), problems


@pytest.mark.parametrize("path,value,fragment", [
    (("applied_variables", "record_version"), 1, "applied_variables.record_version"),
    (("applied_variables", "applied_variables", 0, "source"), "guessed", ".source"),
    (("applied_variables", "applied_variables", 0, "model"), "ISA deviation", ".model"),
    (("applied_variables", "applied_variables", 0, "readback", "tolerance_kind"), "fuzzy",
     ".readback"),
    (("applied_variables", "applied_variables", 0, "null_test", "kind"), "maybe", ".null_test"),
    (("scene", "buildings", "object_id"), "building:0", "scene.buildings"),
    (("cameras", 0, "stereo", "role"), "centre", "cameras[0].stereo"),
    (("frames", 0, "dis", "pdu_index"), -1, "frames[0].dis"),
    (("state_units", "altitude_m"), "furlong", "state_units.altitude_m"),
    (("instruments", "sha256"), "not-a-digest", "instruments"),
    (("datum", "undulation_m"), "fifty", "datum"),
])
def test_a_corrupted_block_fails_the_v7_schema_by_path(path, value, fragment):
    m = _every_block(_manifest_7())
    node = m
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    problems = validate(m, load_schema(V7))
    assert any(fragment in p for p in problems), problems


def test_a_record_1_block_is_not_a_version_7_block():
    """The v7 manifest's records are record 2: the record-1 spelling (the
    string under model) fails the schema by path, and the verifier's
    record checks read either version."""
    m = _every_block(_manifest_7())
    record = m["applied_variables"]["applied_variables"][0]
    record_1 = {("model" if k == "model_name" else "model_block" if k == "model" else k): v
                for k, v in record.items()}
    m["applied_variables"] = {"record_version": 2, "applied_variables": [record_1]}
    assert any("applied_variables[0]" in p for p in validate(m, load_schema(V7)))
    for version in (1, 2):
        block = {"applied_variables": {"record_version": version,
                                       "applied_variables": [record]}}
        assert verify.verify_applied_readback(block).status == verify.PASS
        assert verify.verify_null_effect(block).status == verify.PASS
    assert verify.verify_applied_readback(
        {"applied_variables": {"record_version": 3, "applied_variables": [record]}}
    ).status == verify.NOT_RUN


# -- record 2 ------------------------------------------------------------------------------

def test_record_2_spells_the_model_as_model_and_the_name_as_model_name():
    record = _record_2()
    assert record["model_name"] == "ISA deviation (US Standard Atmosphere 1976)"
    assert record["model"]["name"] == "ISA deviation" and "model_block" not in record
    assert records_block([AppliedVariable.from_dict(record)])["record_version"] == 2
    assert AppliedVariable.__dataclass_fields__["model_name"].type in ("str", str)
    with pytest.raises(ValueError, match="model block"):
        AppliedVariable(name="x.y", value=1, unit="1", source="user", model_name="m",
                        model="a string where the block goes")


def test_a_record_1_dict_is_readable_at_record_2():
    record_2 = _record_2()
    record_1 = {("model" if k == "model_name" else "model_block" if k == "model" else k): v
                for k, v in record_2.items()}
    assert upgrade_record(record_1) == record_2
    # Renamed in place: every other key keeps its position.
    assert list(upgrade_record(record_1)) == [
        "model_name" if k == "model" else "model" if k == "model_block" else k for k in record_1]
    assert upgrade_record(record_2) == record_2 and upgrade_record(record_2) is not record_2
    assert AppliedVariable.from_dict(record_1) == AppliedVariable.from_dict(record_2)
    (read,) = read_records({"record_version": 1, "applied_variables": [record_1]})
    assert read == record_2
    # A plain record-1 dict (before record 2's fields existed) reads too.
    plain = {"name": "limits.monitor", "value": {}, "unit": "g", "source": "derived",
             "model": "exceedance monitor", "parameters": {}, "references": [],
             "properties_written": [], "telemetry_columns": [], "frame_keys": [],
             "null_test": None, "not_claimed": []}
    (read,) = read_records({"record_version": 1, "applied_variables": [plain]})
    assert read["model_name"] == "exceedance monitor" and "model" not in read
    assert AppliedVariable.from_dict(plain).model is None
    with pytest.raises(ValueError, match="record_version 3"):
        read_records({"record_version": 3, "applied_variables": []})


# -- the limits flag rename ----------------------------------------------------------------

def test_the_limits_flags_carry_the_flag_suffix():
    columns = [column for _, column, *_ in limits.CHECKS] + [limits.ANY_COLUMN]
    assert columns == ["nz_pos_flag", "nz_neg_flag", "vne_or_vmo_flag", "mmo_flag",
                       "alpha_stall_flag", "any_exceedance_flag"]
    assert sorted(limits.FLAG_RENAMES.values()) == sorted(columns)
    assert all(old.startswith("exceed_") or old == "any_exceedance" for old in limits.FLAG_RENAMES)
    for column in columns:
        assert suffix_unit(column) == channel_unit(column) == "1", column
    entry = REGISTRY.get("limits.monitor")
    assert [c.name for c in entry.effect_channels] == columns
    assert list(entry.host_channels) == columns
    assert not [c for c in REGISTRY.channel_units() if c.startswith("exceed_")]
    # A run recorded before the rename still reads its flags as unit 1.
    assert channel_unit("exceed_mmo") == channel_unit("any_exceedance") == "1"


def test_the_monitor_writes_the_renamed_columns():
    cols = {"t": [0.0, 0.1], "n_z": [1.0, 4.5], "cas_kt": [100.0, 100.0],
            "mach": [0.1, 0.1], "alpha_deg": [2.0, 2.0]}
    table = limits.load_limits("c172p")
    result = limits.monitor(cols, table)
    assert set(result.flags) <= {column for _, column, *_ in limits.CHECKS} | {limits.ANY_COLUMN}
    assert result.flags["nz_pos_flag"] == [0, 1] and result.flags["any_exceedance_flag"] == [0, 1]
    assert result.summary["any_exceedance"]["column"] == "any_exceedance_flag"


# -- the georeference check (D2's render.json pin) -----------------------------------------

#: sha256 of verify.verify_georeference as landed at INT-final.
GEOREFERENCE_SOURCE_SHA256 = "7f4595f8547068da4fb275ee5e8a82aa27086c6392c4b45e31515ad068b75899"


def test_the_georeference_check_text_is_pinned():
    assert verify.GEOREFERENCE_KEYS == ("geographic_crs", "projected_crs", "origin",
                                        "vertical_convention", "undulation_origin_m")
    assert verify.GEOREFERENCE_GEOGRAPHIC_CRS == "EPSG:4326"
    assert verify.GEOREFERENCE_VERTICAL_CONVENTION == (
        "orthometric heights passed to AGeoReferencingSystem as ellipsoidal; engine ECEF "
        "radially low by undulation_origin_m")
    assert verify.GEOREFERENCE_TOL_DEG == 1e-7 and verify.GEOREFERENCE_TOL_M == 1e-3
    assert verify.FAIL_GEOREFERENCE == "check.georeference"
    assert is_catalogued("check.georeference")
    source = inspect.getsource(verify.verify_georeference)
    assert hashlib.sha256(source.encode()).hexdigest() == GEOREFERENCE_SOURCE_SHA256
    assert source.isascii()
    run_source = inspect.getsource(verify.verify_run)
    assert re.search(r'run\("georeference", verify_georeference, manifest, run_dir\)', run_source)


def _georeferenced(tmp_path, cameras=("chase0", "tower0"), **changes):
    manifest = _every_block(_manifest_7())
    frame = manifest["frame"]
    block = {"geographic_crs": "EPSG:4326", "projected_crs": frame["crs"],
             "origin": {"lat_deg": frame["origin_lat_deg"], "lon_deg": frame["origin_lon_deg"],
                        "x_m": frame["origin_x_m"], "y_m": frame["origin_y_m"]},
             "vertical_convention": verify.GEOREFERENCE_VERTICAL_CONVENTION,
             "undulation_origin_m": manifest["datum"]["undulation_m"]}
    for number, camera in enumerate(cameras):
        own = copy.deepcopy(block)
        if number == len(cameras) - 1:
            for key, value in changes.items():
                if key.startswith("origin_"):
                    own["origin"][key[len("origin_"):]] = value
                elif value is KeyError:
                    own.pop(key)
                else:
                    own[key] = value
        directory = tmp_path / "frames" / camera
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "render.json").write_text(json.dumps({"georeference": own}),
                                               encoding="utf-8")
    return manifest


def test_the_georeference_check_passes_a_verbatim_block_and_is_not_run_without_one(tmp_path):
    manifest = _georeferenced(tmp_path)
    check = verify.verify_georeference(manifest, tmp_path)
    assert check.status == verify.PASS, check.detail
    assert "2 render.json georeference block(s)" in check.detail
    empty = tmp_path / "empty"
    (empty / "frames" / "chase0").mkdir(parents=True)
    (empty / "frames" / "chase0" / "render.json").write_text("{}", encoding="utf-8")
    assert verify.verify_georeference(manifest, empty).status == verify.NOT_RUN
    assert verify.verify_georeference(manifest, None).status == verify.NOT_RUN
    # A flat scene: the datum's undulation is null, and so must the host's be.
    flat = tmp_path / "flat"
    manifest = _georeferenced(flat, undulation_origin_m=None)
    for camera in ("chase0",):
        path = flat / "frames" / camera / "render.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["georeference"]["undulation_origin_m"] = None
        path.write_text(json.dumps(data), encoding="utf-8")
    manifest["datum"]["undulation_m"] = None
    assert verify.verify_georeference(manifest, flat).status == verify.PASS


@pytest.mark.parametrize("changes,fragment", [
    ({"projected_crs": "EPSG:32633"}, "projected_crs"),
    ({"geographic_crs": "EPSG:4979"}, "geographic_crs"),
    ({"origin_lat_deg": 46.00001}, "origin.lat_deg"),
    ({"origin_x_m": 400000.5}, "origin.x_m"),
    ({"vertical_convention": "ellipsoidal heights"}, "vertical_convention"),
    ({"undulation_origin_m": 53.95}, "undulation_origin_m"),
    ({"undulation_origin_m": None}, "undulation_origin_m"),
    ({"undulation_origin_m": KeyError}, "lacks ['undulation_origin_m']"),
])
def test_the_georeference_check_fails_by_name_on_each_corruption(tmp_path, changes, fragment):
    manifest = _georeferenced(tmp_path, cameras=("chase0",), **changes)
    check = verify.verify_georeference(manifest, tmp_path)
    assert check.status == verify.FAIL and fragment in check.detail, check.detail
    assert check.failure == "check.georeference"


def test_the_georeference_check_fails_when_cameras_disagree(tmp_path):
    manifest = _georeferenced(tmp_path, origin_x_m=400000.0004)      # inside the tolerance
    check = verify.verify_georeference(manifest, tmp_path)
    assert check.status == verify.FAIL and "one scene, one georeference" in check.detail
