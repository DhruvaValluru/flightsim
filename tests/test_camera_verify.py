"""Camera Phase 1, package H: verification that can actually fail.

The exit criterion is checks 1-3 passing -- and each check is shown
here to FAIL on a corrupted manifest, because a verifier that cannot
fail verifies nothing. The reprojection expectations are computed
inline in this file with plain arithmetic (no import of the pose
solver's projection), per the phase rules.
"""

import math

import pytest

from core.capture.manifest import build_capture_manifest, write_capture_manifest
from core.capture.poses import euler_to_quat, solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    project_point, verify_alignment, verify_counts, verify_geometry,
    verify_run, verify_triangulation,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


def spec_with(*cameras):
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = list(cameras)
    return spec


def counted(preset, camera_id, count=15, **kwargs):
    camera = CameraSpec.defaulted(camera_id=camera_id, preset=preset,
                                  aircraft="B747", **kwargs)
    camera.set("capture_count", count, frm="test")
    return camera


def manifest_for(spec, columns=None):
    columns = columns or make_columns(duration_s=14.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                  output_digest="0" * 64)


def two_camera_manifest():
    return manifest_for(spec_with(counted("chase", "chase0"),
                                  counted("tower", "tower0")))


# -- the independent projection, checked against hand arithmetic --------

def test_projection_matches_hand_computed_pinhole():
    """A frame record built BY HAND: camera at the origin, level,
    facing north. Every expected number below is plain arithmetic on
    the documented projection -- nothing imported."""
    record = {
        "position_north_m": 0.0, "position_east_m": 0.0,
        "position_alt_m": 0.0,
        "quaternion_wxyz": list(euler_to_quat(0.0, 0.0, 0.0)),
        "roll_deg": 0.0, "pitch_deg": 0.0, "yaw_deg": 0.0,
        "principal_point_px": [640.0, 360.0],
        "fx_px": 1244.4, "fy_px": 1244.4,
        "width_px": 1280, "height_px": 720,
    }
    # Point 100 m ahead, 10 m east (image right), 5 m up (image up).
    u, v, z = project_point(record, (100.0, 10.0, 5.0))
    assert z == pytest.approx(100.0)
    assert u == pytest.approx(640.0 + 1244.4 * 10.0 / 100.0)
    assert v == pytest.approx(360.0 - 1244.4 * 5.0 / 100.0)
    # Straight ahead lands exactly on the principal point.
    u0, v0, _ = project_point(record, (50.0, 0.0, 0.0))
    assert (u0, v0) == (pytest.approx(640.0), pytest.approx(360.0))
    # Behind the camera is reported, never wrapped into the frame.
    _, _, z_behind = project_point(record, (-50.0, 0.0, 0.0))
    assert z_behind < 0


# -- checks 2-4 pass on an honest manifest, fail on a corrupted one -----

def test_geometry_recovery_passes_and_catches_a_bad_quaternion():
    manifest = two_camera_manifest()
    assert verify_geometry(manifest).ok

    bad = two_camera_manifest()
    record = bad["frames"][5]
    record["quaternion_wxyz"] = list(
        euler_to_quat(0.0, record["pitch_deg"] + 5.0, record["yaw_deg"]))
    assert not verify_geometry(bad).ok


def test_geometry_recovery_catches_an_aimless_camera():
    manifest = two_camera_manifest()
    for record in manifest["frames"]:
        if record["camera_id"] == "tower0":
            # Point the tower camera due away from the aircraft: it ends
            # up BEHIND the lens.
            record["yaw_deg"] = (record["yaw_deg"] + 180.0) % 360.0
            record["quaternion_wxyz"] = list(
                euler_to_quat(record["roll_deg"], record["pitch_deg"],
                              record["yaw_deg"]))
    assert not verify_geometry(manifest).ok


def test_geometry_recovery_catches_an_out_of_frame_aim():
    # A 45-degree twist keeps the aircraft in FRONT of the camera
    # (depth positive) but outside the ~27-degree half field of view:
    # only the in-frame clause can catch this one.
    manifest = two_camera_manifest()
    for record in manifest["frames"]:
        if record["camera_id"] == "tower0":
            record["yaw_deg"] = (record["yaw_deg"] + 45.0) % 360.0
            record["quaternion_wxyz"] = list(
                euler_to_quat(record["roll_deg"], record["pitch_deg"],
                              record["yaw_deg"]))
    assert not verify_geometry(manifest).ok


def test_triangulation_passes_and_catches_misattributed_states():
    manifest = two_camera_manifest()
    check = verify_triangulation(manifest)
    assert check.ok, check.detail

    bad = two_camera_manifest()
    for record in bad["frames"]:
        if record["camera_id"] == "tower0":
            record["aircraft"]["north_m"] += 50.0   # a different instant
    assert not verify_triangulation(bad).ok


def test_triangulation_reports_not_exercised_for_one_camera():
    """No false pass, no false failure: a single camera cannot be
    cross-checked and the report says so in words."""
    manifest = manifest_for(spec_with(counted("chase", "solo")))
    check = verify_triangulation(manifest)
    assert check.ok
    assert "NOT EXERCISED" in check.detail


def test_count_exactness_passes_and_catches_a_dropped_frame():
    manifest = two_camera_manifest()
    assert verify_counts(manifest).ok
    manifest["frames"] = manifest["frames"][:-1]
    assert not verify_counts(manifest).ok


# -- check 1: temporal alignment across camera variants -----------------

def test_two_camera_variants_align_exactly():
    """The load-bearing phase claim: same spec, different cameras, frame
    sets that align exactly in time."""
    columns = make_columns(duration_s=14.0)
    a = manifest_for(spec_with(counted("chase", "chase0")), columns)
    b = manifest_for(spec_with(counted("tower", "tower0"),
                               counted("cockpit", "shoulder0")), columns)
    check = verify_alignment(a, b)
    assert check.ok, check.detail


def test_alignment_catches_a_different_simulation():
    columns = make_columns(duration_s=14.0)
    a = manifest_for(spec_with(counted("chase", "chase0")), columns)
    b = manifest_for(spec_with(counted("chase", "chase0")), columns)
    b["simulation_digest"] = "f" * 64
    assert not verify_alignment(a, b).ok

    c = manifest_for(spec_with(counted("chase", "chase0")), columns)
    c["frames"][3]["t_s"] += 0.05
    assert not verify_alignment(a, c).ok


# -- the run-directory summary ------------------------------------------

def test_verify_run_over_a_directory(tmp_path):
    write_capture_manifest(two_camera_manifest(), tmp_path)
    report = verify_run(tmp_path)
    assert report.ok, report.render()
    assert "PASSED" in report.render()


def test_verify_run_refuses_a_missing_or_wrong_version_manifest(tmp_path):
    report = verify_run(tmp_path)
    assert not report.ok
    manifest = two_camera_manifest()
    manifest["manifest_version"] = 99
    write_capture_manifest(manifest, tmp_path)
    assert not verify_run(tmp_path).ok
