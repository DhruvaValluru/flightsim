"""S2: the stereo rig -- cameras[i].stereo, the materialised right camera,
the disparity pass and disparity_vs_right_depth.

The rig is rectified by construction (core/capture/stereo.py); these
tests measure the construction against this file's own arithmetic and
the verifier's own axes, the refusals by name (sensing.stereo,
sensing.pass), the absent-canonical spec (every committed example keeps
its digest), and the disparity against the synthetic right camera's own
depth (tests/test_passes.py's ray caster). One short headless capture
(2 s of the B747) shows the right camera flying through the real
solver, the card, the manifest and the verifier.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.capture import passes, stereo, verify
from core.capture.poses import euler_to_quat
from core.scenario.camera import CameraSpec
from core.scenario.fields import Quantity
from core.scenario.spec import ScenarioSpec
from tests.test_passes import (
    CAMERA, SAMPLES, attach, build_run, camera_pose, load, pose_track, rewrite,
)
from tests.test_registry import EXAMPLE_DIGESTS

REPO = Path(__file__).resolve().parents[1]


def rig_camera(baseline=0.5, side="right", words=None) -> CameraSpec:
    camera = CameraSpec.defaulted("left", preset="explicit")
    camera.stereo = Quantity.user({"baseline_m": baseline, "side": side}, frm="test")
    if words is not None:
        camera.passes = Quantity.user(list(words), frm="test")
    return camera


# -- the block and its refusals -----------------------------------------------------

@pytest.mark.parametrize("value,words", [
    ({"baseline_m": 0.0, "side": "right"}, "not a rig"),
    ({"baseline_m": -0.3, "side": "right"}, "not a rig"),
    ({"baseline_m": 150.0, "side": "right"}, "exceeds the 100 m bound"),
    ({"baseline_m": 0.5, "side": "left"}, "side 'left' is not modelled"),
    ({"baseline_m": "wide", "side": "right"}, "finite number"),
    ({"baseline_m": float("nan"), "side": "right"}, "finite number"),
    ({"baseline_m": 0.5}, "missing ['side']"),
    ({"baseline_m": 0.5, "side": "right", "roll": 1}, "unknown ['roll']"),
    ([0.5, "right"], "must be a mapping"),
])
def test_a_rig_that_cannot_be_built_is_refused_sensing_stereo_by_name(value, words):
    camera = CameraSpec.defaulted("left", preset="explicit")
    camera.stereo = Quantity.user(value, frm="test")
    assert words in stereo.stereo_problem(value)
    with pytest.raises(stereo.StereoError) as err:
        stereo.stereo_of(camera)
    assert err.value.constraint == "sensing.stereo" and str(err.value).startswith("sensing.stereo: ")
    (violation,) = stereo.stereo_violations(camera, 0, ["left"])
    assert violation.constraint == "sensing.stereo" and words in violation.message


def test_the_bound_is_inclusive_and_the_right_id_must_fit_and_be_free():
    assert stereo.stereo_problem({"baseline_m": stereo.STEREO_MAX_BASELINE_M, "side": "right"}) is None
    assert stereo.stereo_problem(None) is None
    camera = rig_camera()
    assert stereo.stereo_violations(camera, 0, ["left"]) == []
    (clash,) = stereo.stereo_violations(camera, 0, ["left", "left_right"])
    assert clash.constraint == "sensing.stereo" and "already a stated camera's" in clash.message
    camera.camera_id = Quantity.user("x" * 60, frm="test")
    (long,) = stereo.stereo_violations(camera, 0, ["x" * 60])
    assert "66 characters" in long.message


def test_the_validator_refuses_a_bad_rig_and_a_disparity_without_one_by_name():
    from core.capture.validate import validate_cameras

    spec = ScenarioSpec.read(REPO / "examples/cameras_multi.yaml")
    assert validate_cameras(spec) == []
    spec.cameras[0].stereo = Quantity.user({"baseline_m": 0.0, "side": "right"}, frm="test")
    names = [v.constraint for v in validate_cameras(spec)]
    assert names == ["sensing.stereo"]
    spec.cameras[0].stereo = Quantity.user({"baseline_m": 0.6, "side": "right"}, frm="test")
    spec.cameras[0].passes = Quantity.user(["flow", "disparity", "points"], frm="test")
    assert validate_cameras(spec) == []
    spec.cameras[1].passes = Quantity.user(["disparity"], frm="test")
    (violation,) = validate_cameras(spec)
    assert violation.constraint == "sensing.pass" and "stereo rig" in violation.message


def test_both_fields_are_absent_canonical_and_every_example_keeps_its_digest(tmp_path):
    for path, digest in EXAMPLE_DIGESTS.items():
        spec = ScenarioSpec.read(REPO / path)
        assert spec.digest() == digest, path
        for camera in spec.cameras:
            assert "stereo" not in camera.to_dict() and "passes" not in camera.to_dict()
    spec = ScenarioSpec.read(REPO / "examples/cameras_multi.yaml")
    before = spec.digest()
    spec.cameras[0].stereo = Quantity.user({"baseline_m": 0.6, "side": "right"}, frm="test")
    spec.cameras[0].passes = Quantity.user(["flow", "disparity"], frm="test")
    assert spec.digest() != before
    spec.write(tmp_path / "rig.yaml")
    again = ScenarioSpec.read(tmp_path / "rig.yaml")
    assert again.digest() == spec.digest()
    assert again.cameras[0].stereo.value == {"baseline_m": 0.6, "side": "right"}
    assert again.cameras[0].passes.value == ["flow", "disparity"]
    assert again.cameras[1].stereo.value is None and again.cameras[1].passes.value is None


# -- the right camera, by construction ----------------------------------------------

def test_the_right_camera_is_the_left_moved_by_the_baseline_along_its_right_axis():
    left = rig_camera(0.75, words=["flow", "disparity", "points"])
    right = stereo.right_camera_spec(left)
    assert right.camera_id.value == "left_right" and stereo.is_stereo_right(right)
    assert right.position_mode.value == stereo.STEREO_RIGHT_MODE
    assert right.passes.value == ["flow", "points"]                   # no right partner
    for name in ("focal_length_mm", "sensor_width_mm", "sensor_height_mm", "width_px",
                 "height_px", "near_m", "far_m", "trigger", "capture_count", "preset"):
        assert getattr(right, name).value == getattr(left, name).value, name
    flown = stereo.with_stereo_right([left, CameraSpec.defaulted("tower", preset="tower")])
    assert [c.camera_id.value for c in flown] == ["left", "tower", "left_right"]
    # materialising again adds nothing: a right camera gets no right of its own
    assert [c.camera_id.value for c in stereo.with_stereo_right(flown)] == [
        "left", "tower", "left_right"]
    with pytest.raises(stereo.StereoError):
        stereo.right_camera_spec(right)
    # the track: a rolled, pitched, yawing camera
    track = pose_track("left", [camera_pose(i) for i in range(SAMPLES)])
    moved = stereo.right_track(track, 0.75, "left_right")
    assert moved.camera_id == "left_right" and moved.quat == track.quat
    assert moved.focal_length_mm == track.focal_length_mm and moved.t == track.t
    for i in range(SAMPLES):
        _, right_axis, _ = verify.axes_from_quat(track.quat[i])      # the verifier's own axes
        gap = [moved.north_m[i] - track.north_m[i], moved.east_m[i] - track.east_m[i],
               moved.alt_m[i] - track.alt_m[i]]
        assert gap == pytest.approx([0.75 * c for c in right_axis], abs=1e-12)
        # rectified: the baseline is perpendicular to the optical axis and the up axis
        forward, _, up = verify.axes_from_quat(moved.quat[i])
        assert abs(sum(g * f for g, f in zip(gap, forward))) < 1e-12
        assert abs(sum(g * u for g, u in zip(gap, up))) < 1e-12


def test_the_manifest_block_names_both_roles():
    left = rig_camera(0.5)
    right = stereo.right_camera_spec(left)
    flown = [left, right]
    a = stereo.manifest_stereo_block(left, flown)
    b = stereo.manifest_stereo_block(right, flown)
    assert a["role"] == "left" and b["role"] == "right"
    assert a["right_camera_id"] == b["right_camera_id"] == "left_right"
    assert a["baseline_m"] == b["baseline_m"] == 0.5
    assert stereo.manifest_stereo_block(CameraSpec.defaulted("x"), flown) is None


def test_the_pose_check_leaves_the_right_camera_to_the_rig_clause():
    manifest = {"cameras": [{"camera_id": "left_right", "preset": "cockpit",
                             "spec": stereo.right_camera_spec(rig_camera()).to_dict()}],
                "frames": [{"camera_id": "left_right", "index": 0, "position_north_m": 0.0,
                            "position_east_m": 0.0, "position_alt_m": 100.0,
                            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                            "aircraft": {"north_m": 50.0, "east_m": 0.0, "alt_m": 100.0,
                                         "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}}]}
    check = verify.verify_pose_matches_spec(manifest)
    assert check.status == verify.NOT_RUN and "left_right" in check.detail


# -- the disparity against the right camera's depth -------------------------------------

def test_disparity_vs_right_depth_passes_on_the_rig_and_its_record_measures_b_to_zero(tmp_path):
    run_dir = build_run(tmp_path, baseline=5.0)
    attach(run_dir)
    manifest = load(run_dir)
    check = verify.verify_disparity_vs_right_depth(manifest, run_dir)
    assert check.status == verify.PASS, check.detail
    assert "3 left/right pair(s)" in check.detail
    blocks = {b["camera_id"]: b for b in manifest["cameras"]}
    assert blocks[CAMERA]["stereo"]["role"] == "left"
    assert blocks[f"{CAMERA}_right"]["stereo"]["role"] == "right"
    right_frames = [f for f in manifest["frames"] if f["camera_id"] == f"{CAMERA}_right"]
    assert all("disparity" not in f["passes"]["requested"] for f in right_frames)
    records = {r["name"]: r for r in manifest["applied_variables"]["applied_variables"]}
    disparity = records["passes.disparity"]
    assert disparity["value"] == 5.0 and disparity["unit"] == "m"
    assert disparity["null_test"]["ok"] and disparity["null_test"]["with"] == 0.0   # B -> 0
    entry = json.loads((run_dir / "frames" / CAMERA / "passes.json").read_text(
        encoding="utf-8"))["frames"][0]["disparity"]
    depth = np.fromfile(run_dir / "frames" / CAMERA / "frame_0000_depth.f32", dtype="<f4")
    finite = depth[np.isfinite(depth)]
    fx = manifest["frames"][0]["fx_px"]
    assert entry["d_max_px"] == pytest.approx(fx * 5.0 / float(finite.min()), rel=1e-6)
    assert entry["right_camera_id"] == f"{CAMERA}_right"


def test_a_disparity_off_the_formula_fails_by_name(tmp_path):
    run_dir = build_run(tmp_path, baseline=5.0)
    attach(run_dir)
    rewrite(run_dir, CAMERA, "frame_0001.png", "disparity", lambda a: a * 1.1)
    check = verify.verify_disparity_vs_right_depth(load(run_dir), run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.disparity"
    assert "f_x B / Z" in check.detail


def test_a_right_camera_off_the_rig_fails_the_rig_clause_by_name(tmp_path):
    run_dir = build_run(tmp_path, baseline=5.0)
    attach(run_dir)
    manifest = load(run_dir)
    for frame in manifest["frames"]:
        if frame["camera_id"] == f"{CAMERA}_right" and frame["index"] == 2:
            frame["position_alt_m"] += 0.3
    check = verify.verify_disparity_vs_right_depth(manifest, run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.disparity"
    assert "left's right axis" in check.detail
    manifest = load(run_dir)
    manifest["frames"] = [f for f in manifest["frames"]
                          if not (f["camera_id"] == f"{CAMERA}_right" and f["index"] == 1)]
    check = verify.verify_disparity_vs_right_depth(manifest, run_dir)
    assert check.status == verify.FAIL and "no frame at this index" in check.detail


def test_a_right_render_that_is_not_the_rig_fails_against_its_depth(tmp_path):
    run_dir = build_run(tmp_path, baseline=5.0, right_yaw_error_deg=10.0)
    attach(run_dir)
    check = verify.verify_disparity_vs_right_depth(load(run_dir), run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.disparity"
    assert "find their own depth in the right image" in check.detail


def test_a_rig_without_a_disparity_pass_is_not_run_with_the_rig_checked(tmp_path):
    run_dir = build_run(tmp_path, words=("points",))
    attach(run_dir)
    manifest = load(run_dir)
    # a rig declared on the camera blocks, frames present for both cameras
    left = rig_camera(2.0)
    right = stereo.right_camera_spec(left)
    manifest["cameras"] = [{"camera_id": "left", "stereo": stereo.manifest_stereo_block(left, [left, right])},
                           {"camera_id": "left_right", "stereo": stereo.manifest_stereo_block(right, [left, right])}]
    track = pose_track("left", [camera_pose(i) for i in range(SAMPLES)])
    moved = stereo.right_track(track, 2.0, "left_right")
    manifest["frames"] = []
    for camera_id, cam_track in (("left", track), ("left_right", moved)):
        for index, i in enumerate((1, 3)):
            record = passes.camera_record_at(cam_track, i)
            record.update({"camera_id": camera_id, "index": index,
                           "file": f"frames/{camera_id}/frame_{index:04d}.png"})
            manifest["frames"].append(record)
    check = verify.verify_disparity_vs_right_depth(manifest, None)
    assert check.status == verify.NOT_RUN, check.detail
    assert "2 left/right pair(s) rectified by construction as declared" in check.detail


# -- through the real solver, card and manifest -------------------------------------------

def test_a_stated_rig_flies_its_right_camera_through_the_capture(tmp_path):
    from flightsim.capture import main as capture_main

    spec = ScenarioSpec.read(REPO / "examples/cameras_multi.yaml")
    spec.set("duration", 2.0, frm="test: a short flight")
    spec.cameras = spec.cameras[:1]
    spec.cameras[0].set("capture_count", 4, frm="test")
    spec.cameras[0].stereo = Quantity.user({"baseline_m": 1.5, "side": "right"}, frm="test")
    spec.cameras[0].passes = Quantity.user(["flow", "disparity", "points", "amodal"], frm="test")
    spec.write(tmp_path / "rig.yaml")
    out = tmp_path / "out"
    assert capture_main([str(tmp_path / "rig.yaml"), "--out", str(out), "--max-previews", "0",
                         "--card"]) == 0
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    left_id = str(spec.cameras[0].camera_id.value)
    right_id = f"{left_id}_right"
    blocks = {b["camera_id"]: b for b in manifest["cameras"]}
    assert set(blocks) == {left_id, right_id}
    assert blocks[right_id]["stereo"]["role"] == "right" and blocks[left_id]["stereo"]["baseline_m"] == 1.5
    lefts = [f for f in manifest["frames"] if f["camera_id"] == left_id]
    rights = [f for f in manifest["frames"] if f["camera_id"] == right_id]
    assert len(lefts) == len(rights) == 4
    for a, b in zip(lefts, rights):
        assert a["t_s"] == b["t_s"] and a["quaternion_wxyz"] == b["quaternion_wxyz"]
        _, right_axis, _ = verify.axes_from_quat(a["quaternion_wxyz"])
        gap = [b[k] - a[k] for k in ("position_north_m", "position_east_m", "position_alt_m")]
        assert gap == pytest.approx([1.5 * c for c in right_axis], abs=1e-9)
        assert a["passes"]["requested"] == ["flow", "disparity", "points", "amodal"]
        assert b["passes"]["requested"] == ["flow", "points", "amodal"]
        for block in (a["passes"], b["passes"]):
            neighbours = block["neighbours"]
            assert neighbours["current"]["sample_index"] == a["sample_index"]
            forward = neighbours["forward"]
            assert forward is None or forward["camera"]["sample_index"] == a["sample_index"] + 1
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert [c["camera_id"] for c in card["cameras"]] == [left_id, right_id]
    report = verify.verify_run(out)
    checks = {c.name: c for c in report.checks}
    assert checks["pose_matches_spec"].status == verify.PASS, checks["pose_matches_spec"].detail
    assert checks["intrinsics_match_spec"].status == verify.PASS
    rig = checks["disparity_vs_right_depth"]
    assert rig.status == verify.NOT_RUN and "4 left/right pair(s)" in rig.detail
    for name in ("flow_vs_keypoints", "flow_static_null", "points_vs_depth",
                 "amodal_contains_visible"):
        assert checks[name].status == verify.NOT_RUN, name        # headless: no bundle
