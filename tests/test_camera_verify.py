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


# -- check 5: engine parity on rendered frames --------------------------

def write_engine_output(manifest, run_dir, cameras=None, step_s=1.0 / 120.0):
    """A synthetic consume-poses pass: what an HONEST engine writes --
    frames/<camera_id>/render.json with the applied pose equal to the
    solved one, the applied time equal to the scheduled instant, one
    PNG per record named by its index at the manifest's size. Built
    here by hand from the manifest so the test owns every number."""
    import json

    from PIL import Image

    outputs = {}
    for block in manifest["cameras"]:
        camera_id = block["camera_id"]
        if cameras is not None and camera_id not in cameras:
            continue
        records = [r for r in manifest["frames"] if r["camera_id"] == camera_id]
        directory = run_dir / "frames" / camera_id
        directory.mkdir(parents=True, exist_ok=True)
        frame_records = []
        for record in records:
            frame_records.append({
                "frame_index": record["index"],
                "frame": f"{record['index']:04d}.png",
                "t_scheduled_s": record["t_s"],
                "t_applied_s": record["t_s"],
                "t_pose_s": record["t_s"],
                "camera_applied_north_m": record["position_north_m"],
                "camera_applied_east_m": record["position_east_m"],
                "camera_applied_alt_m": record["position_alt_m"],
                "camera_applied_yaw_deg": record["yaw_deg"],
                "camera_applied_pitch_deg": record["pitch_deg"],
                "camera_applied_roll_deg": record["roll_deg"],
                "aircraft_applied_north_m": record["aircraft"]["north_m"],
                "aircraft_applied_east_m": record["aircraft"]["east_m"],
                "aircraft_applied_alt_m": record["aircraft"]["alt_m"],
            })
            Image.new("RGB", (record["width_px"], record["height_px"]),
                      (40, 40, 40)).save(run_dir / record["file"])
        render = {
            "host": "unreal", "camera_consume_poses": True,
            "width": records[0]["width_px"], "height": records[0]["height_px"],
            "step_s": step_s,
            "frames_scheduled": len(records), "frames_captured": len(records),
            "frame_records": frame_records,
        }
        outputs[camera_id] = render
        (directory / "render.json").write_text(json.dumps(render),
                                               encoding="utf-8")
    return outputs


def rewrite(run_dir, camera_id, render):
    import json

    (run_dir / "frames" / camera_id / "render.json").write_text(
        json.dumps(render), encoding="utf-8")


def test_engine_parity_passes_on_honest_engine_output(tmp_path):
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    write_engine_output(manifest, tmp_path)
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is True, check.detail
    assert "30 frames across 2 camera(s)" in check.detail
    assert check.data["cameras"]["chase0"] == {
        "scheduled": 15, "rendered": 15, "verified": 15}
    # Through verify_run the check is a named member of the report and
    # the report passes with it.
    report = verify_run(tmp_path)
    assert report.ok, report.render()
    assert [c.name for c in report.checks][-1] == "engine_parity"
    assert "[PASS] engine_parity" in report.render()


def test_engine_parity_is_awaiting_without_engine_frames(tmp_path):
    """No render.json anywhere: AWAITING, in those words -- neither a
    pass the headless run did not earn nor a failure for lacking an
    engine; report.ok is decided by the checks that ran."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is None
    assert check.status == "AWAITING"
    assert "awaiting engine frames" in check.detail
    assert "chase0" in check.detail and "tower0" in check.detail
    assert check.data["cameras"]["tower0"] == {
        "scheduled": 15, "rendered": 0, "verified": 0}
    report = verify_run(tmp_path)
    assert report.ok
    assert report.awaiting and report.awaiting[0].name == "engine_parity"
    assert "[AWAITING] engine_parity" in report.render()
    assert "awaiting engine frames" in report.render()
    assert "PASSED (5/5 checks" in report.render()


def test_engine_parity_fails_on_a_corrupted_position(tmp_path):
    """A 20 cm shift of ONE applied position -- twice the tolerance the
    commandlet itself fails on -- fails the check by frame."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    outputs["chase0"]["frame_records"][4]["camera_applied_north_m"] += 0.20
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 4" in check.detail and "0.200 m" in check.detail
    assert check.data["cameras"]["chase0"]["verified"] == 14


def test_engine_parity_fails_on_a_corrupted_yaw(tmp_path):
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    record = outputs["tower0"]["frame_records"][7]
    record["camera_applied_yaw_deg"] = (record["camera_applied_yaw_deg"]
                                        + 0.5) % 360.0
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "tower0 frame 7" in check.detail and "0.500 deg" in check.detail
    # 0.5 deg at 1244 px is ~11 px: the reprojection clause sees it too.
    assert "reprojects" in check.detail


def test_engine_parity_fails_on_a_shifted_capture_time(tmp_path):
    """Captured 50 ms late: six steps at 120 Hz, well past the one fixed
    step the contract allows, so the frame is not the scheduled
    instant. (One step late -- t=0 met by the first step -- passes.)"""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    outputs["chase0"]["frame_records"][0]["t_applied_s"] += 1.0 / 120.0
    rewrite(tmp_path, "chase0", outputs["chase0"])
    assert verify_engine_parity(tmp_path, manifest).ok is True
    outputs["chase0"]["frame_records"][0]["t_applied_s"] += 0.05
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 0: captured at" in check.detail


def test_engine_parity_fails_when_the_pose_was_applied_at_the_clock(
        tmp_path):
    """The pose contract is exact by construction: the commandlet
    interpolates the pose AT the scheduled instant and records it as
    t_pose_s. A pose taken one step later (at an engine clock one step
    off) is a different pose -- ~1.4 m along a chase track at 320 kt --
    and fails by name even when the capture time itself is within its
    one-step tolerance."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    record = outputs["chase0"]["frame_records"][5]
    record["t_pose_s"] += 1.0 / 120.0
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 5: pose applied at t=" in check.detail
    assert "not the engine clock" in check.detail
    assert check.data["cameras"]["chase0"]["verified"] == 14
    assert check.data["worst"]["pose_time_s"] == pytest.approx(1.0 / 120.0)
    # A record that never says when its pose was taken cannot be graded.
    del record["t_pose_s"]
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 5: engine record lacks an applied field" in check.detail


def test_engine_parity_fails_on_a_missing_or_misshapen_png(tmp_path):
    from PIL import Image

    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    write_engine_output(manifest, tmp_path)
    (tmp_path / "frames" / "chase0" / "0003.png").unlink()
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "frames/chase0/0003.png does not exist" in check.detail

    Image.new("RGB", (640, 360)).save(tmp_path / "frames" / "chase0"
                                      / "0003.png")
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "640x360 against the manifest's 1280x720" in check.detail


def test_engine_parity_fails_on_a_short_pass(tmp_path):
    """The engine captured fewer frames than scheduled: the counts
    disagree and the missing record is named."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    render = outputs["chase0"]
    render["frame_records"] = render["frame_records"][:-1]
    render["frames_captured"] = 14
    rewrite(tmp_path, "chase0", render)
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "14 captured of 15 scheduled" in check.detail
    assert "frame 14: no engine record" in check.detail


def test_engine_parity_fails_when_the_engine_drew_the_aircraft_elsewhere(
        tmp_path):
    """The camera pose and the capture time are exact, but the engine's
    own FDM put the aircraft 5 m from where the manifest says (the case
    host parity is refused for): the frame's label does not match its
    pixels, and the check FAILS by frame with the metre and pixel
    numbers. One step of travel (the measured host phase) passes."""
    from core.capture.verify import (
        ENGINE_AIRCRAFT_TOL_M, verify_engine_parity,
    )

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    record = outputs["chase0"]["frame_records"][2]
    record["aircraft_applied_east_m"] += 1.3      # one 1/120 s step at 156 m/s
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is True, check.detail
    assert "aircraft drawn within 1.30 m" in check.detail
    assert f"(tol {ENGINE_AIRCRAFT_TOL_M})" in check.detail
    assert "px of its labelled pixel" in check.detail

    record["aircraft_applied_east_m"] += 3.7      # 5.0 m in all
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 2: the engine drew the aircraft 5.00 m" in check.detail
    assert f"(tol {ENGINE_AIRCRAFT_TOL_M})" in check.detail
    assert "px from its labelled pixel (tol" in check.detail
    assert check.data["cameras"]["chase0"]["verified"] == 14
    assert check.data["worst"]["aircraft_m"] == pytest.approx(5.0)
    # 5 m abeam at the chase distance is tens of pixels: the graded pixel
    # tolerance at that depth is stated in the failure, and exceeded.
    import re

    gap_px, tol_px = map(float, re.search(
        r"(\d+\.\d) px from its labelled pixel \(tol (\d+\.\d) px",
        check.detail).groups())
    assert gap_px > tol_px > 3.0

    # The tower is 1.2 km away: the same 5 m is a few pixels there, and
    # the METRE clause still fails it -- the budget is not slack.
    outputs = write_engine_output(manifest, tmp_path)
    outputs["tower0"]["frame_records"][9]["aircraft_applied_north_m"] += 5.0
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "tower0 frame 9: the engine drew the aircraft 5.00 m" in check.detail


def test_engine_parity_fails_when_the_engine_did_not_record_the_aircraft(
        tmp_path):
    """A consume-poses record without the aircraft the engine drew cannot
    be graded against its label: FAIL by frame, never a silent skip."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    for key in ("aircraft_applied_north_m", "aircraft_applied_east_m",
                "aircraft_applied_alt_m"):
        del outputs["tower0"]["frame_records"][3][key]
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "tower0 frame 3: engine record lacks the drawn aircraft" in check.detail
    assert check.data["cameras"]["tower0"]["verified"] == 14


def test_engine_parity_fails_when_only_some_cameras_rendered(tmp_path):
    """One camera's pass ran and the other's did not: that is a failed
    run, not an awaiting one."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    write_engine_output(manifest, tmp_path, cameras=("chase0",))
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "no render.json for camera tower0" in check.detail
