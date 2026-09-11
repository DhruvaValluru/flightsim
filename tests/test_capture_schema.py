"""Camera Phase 1, package E, closed: the published JSON Schema and the
per-frame projection matrix.

The manifest validates against docs/schemas/capture_manifest.v<N>.schema.json
with a dependency-free validator that refuses any keyword it does not
enforce; the verifier runs it as ``json_schema``. Every frame carries
K and P = K [R | t], and ``projection_matrix`` fails on a matrix that
disagrees with the parameters it summarises.
"""

import copy
import json
from pathlib import Path

import pytest

from core.capture.labels import (
    camera_axes, project_with_matrix, projection_matrices, to_camera, to_pixel,
)
from core.capture.manifest import MANIFEST_VERSION
from core.capture.schema import (
    SchemaError, load_schema, schema_path, validate, validate_manifest,
)
from core.capture.verify import FAIL, NOT_RUN, PASS, verify_json_schema, verify_projection_matrix
from flightsim.capture import main as capture_main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def manifest(tmp_path_factory):
    out = tmp_path_factory.mktemp("schema")
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out", str(out),
                         "--max-previews", "0"]) == 0
    return json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))


# -- the schema -------------------------------------------------------------

def test_the_schema_is_versioned_with_the_writer_and_the_manifest_validates(manifest):
    path = schema_path(manifest)
    assert path.name == f"capture_manifest.v{MANIFEST_VERSION}.schema.json"
    schema = load_schema(path)
    assert schema["properties"]["manifest_version"]["const"] == MANIFEST_VERSION
    assert validate_manifest(manifest) == []


def test_corruptions_fail_by_path(manifest):
    broken = copy.deepcopy(manifest)
    del broken["frames"][3]["quaternion_wxyz"]
    assert any("frames[3]: missing required key 'quaternion_wxyz'" in p
               for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["width_px"] = 1280.5
    assert any("frames[0].width_px" in p and "integer" in p for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["frames"][1]["fx_px"] = float("nan")
    assert any("frames[1].fx_px" in p for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["frames"][2]["file"] = "frames/chase0/img_0002.jpg"
    assert any("frames[2].file" in p for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["spec_digest"] = "not-a-digest"
    assert any("spec_digest" in p for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["projection_matrix"] = broken["frames"][0]["projection_matrix"][:2]
    assert any("projection_matrix" in p and "at least 3" in p for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["cameras"] = []
    assert any("cameras" in p for p in validate_manifest(broken))
    broken = copy.deepcopy(manifest)
    broken["manifest_version"] = 4
    with pytest.raises(SchemaError):          # no v4 schema file: not guessed
        validate_manifest(broken)


def test_the_validator_refuses_keywords_it_does_not_enforce(tmp_path):
    path = tmp_path / "s.schema.json"
    path.write_text(json.dumps({"type": "object", "properties": {
        "x": {"type": "string", "format": "email"}}}), encoding="utf-8")
    with pytest.raises(SchemaError, match="format"):
        load_schema(path)
    assert validate({"a": [1, 2]}, {"type": "object", "properties": {
        "a": {"type": "array", "maxItems": 1}}}) == ["$.a: 2 item(s), at most 1 allowed"]
    assert validate(3, {"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert validate(None, {"anyOf": [{"type": "string"}, {"type": "null"}]}) == []
    assert validate({"k": 1}, {"type": "object", "additionalProperties": False}) == [
        "$: unexpected key 'k'"]


def test_the_verifier_runs_the_schema(manifest):
    assert verify_json_schema(manifest).status == PASS
    broken = copy.deepcopy(manifest)
    del broken["frames"][0]["labels"]
    check = verify_json_schema(broken)
    assert check.status == FAIL and "frames[0]" in check.detail


# -- the projection matrix -----------------------------------------------------

def test_the_matrix_projects_exactly_as_the_parameters(manifest):
    landmarks = [(lm["north_m"], lm["east_m"], lm["alt_m"]) for lm in manifest["landmarks"]]
    compared = 0
    for record in manifest["frames"]:
        K, P = projection_matrices(record)
        assert record["intrinsic_matrix"] == K and record["projection_matrix"] == P
        assert K[0][0] == record["fx_px"] and K[1][2] == record["principal_point_px"][1]
        axes = camera_axes(record["quaternion_wxyz"])
        for point in landmarks:
            expected = to_pixel(record, to_camera(record, point, axes))
            got = project_with_matrix(P, point)
            assert (expected is None) == (got is None)
            if expected is not None:
                compared += 1
                assert got[0] == pytest.approx(expected[0], abs=1e-6)
                assert got[1] == pytest.approx(expected[1], abs=1e-6)
    assert compared > 100


def test_projection_matrix_check_passes_fails_and_is_not_run(manifest):
    assert verify_projection_matrix(manifest).status == PASS
    broken = copy.deepcopy(manifest)
    broken["frames"][5]["projection_matrix"][0][3] += 1.0
    check = verify_projection_matrix(broken)
    assert check.status == FAIL and f"{broken['frames'][5]['camera_id']}/5" in check.detail
    broken = copy.deepcopy(manifest)
    broken["frames"][2]["intrinsic_matrix"][0][0] *= 1.1
    check = verify_projection_matrix(broken)
    assert check.status == FAIL and "intrinsic_matrix" in check.detail
    older = copy.deepcopy(manifest)
    for record in older["frames"]:
        del record["projection_matrix"]
        del record["intrinsic_matrix"]
    assert verify_projection_matrix(older).status == NOT_RUN
