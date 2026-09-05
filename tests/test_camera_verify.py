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
    # SKIPPED, not a pass: ok is None, the reason is named, and the
    # report counts it in neither passed nor ran.
    assert check.ok is None
    assert check.status == "SKIPPED" and check.skipped == "single camera"
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

#: The honest stub's frame: a dark background with a light blob DRAWN AT
#: the labelled pixel -- the one thing the pixel-content clause requires
#: and a flat PNG lacks. Shared by every engine stub in the suite so all
#: three (this file, the webapp's, the CLI's) draw what the manifest says.
BLOB_RADIUS_PX = 8
BACKGROUND = (30, 30, 30)
BLOB = (200, 200, 200)


def honest_frame(path, width, height, pixel=None, background=BACKGROUND,
                 blob=BLOB, radius=BLOB_RADIUS_PX):
    """Write a PNG of ``width`` x ``height`` with a blob at ``pixel``
    (none: a flat frame -- what an engine whose mesh never loaded
    leaves)."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (int(width), int(height)), background)
    if pixel is not None:
        u, v = pixel
        ImageDraw.Draw(image).ellipse(
            [u - radius, v - radius, u + radius, v + radius], fill=blob)
    image.save(path)


def engine_pixel_fields(record):
    """What an honest engine measures about the aircraft it drew: the
    manifest's own labelled pixel (the stub draws exactly there), its
    visibility, and a screen box around it."""
    from core.capture.verify import labelled_pixel

    u, v, depth = labelled_pixel(record)
    visible = (depth > 0 and 0.0 <= u <= record["width_px"]
               and 0.0 <= v <= record["height_px"])
    return {"aircraft_px": u, "aircraft_py": v, "aircraft_visible": visible,
            "aircraft_bbox_px": [u - BLOB_RADIUS_PX, v - BLOB_RADIUS_PX,
                                 u + BLOB_RADIUS_PX, v + BLOB_RADIUS_PX]}


def write_engine_output(manifest, run_dir, cameras=None, step_s=1.0 / 120.0):
    """A synthetic consume-poses pass: what an HONEST engine writes --
    frames/<camera_id>/render.json with the applied pose equal to the
    solved one, the applied time equal to the scheduled instant, one
    PNG per record named by its index at the manifest's size WITH the
    aircraft drawn at the labelled pixel, and the engine's own
    measurement of that pixel. Built here by hand from the manifest so
    the test owns every number."""
    import json

    from core.capture.verify import labelled_pixel

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
                **engine_pixel_fields(record),
            })
            u, v, depth = labelled_pixel(record)
            honest_frame(run_dir / record["file"], record["width_px"],
                         record["height_px"],
                         pixel=(u, v) if depth > 0 else None)
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
    """The capture clock must EQUAL the scheduled instant: every instant
    lies on the spec's fixed-step grid and the commandlet captures on
    that step, so the tolerance is representation slack (1e-6 s), not a
    step. One step late (a different FDM state, ~1.4 m of travel on the
    example) fails by name -- never absorbed by a one-step tolerance
    AND charged to the drawn-aircraft budget both. 1e-7 s passes."""
    from core.capture.verify import ENGINE_TIME_TOL_S, verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    outputs["chase0"]["frame_records"][0]["t_applied_s"] += 1.0e-7
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is True, check.detail
    assert "worst time 1.0e-07 s (tol 1e-06; every instant on the 120 Hz grid, the engine stepped 0.008333 s)" in check.detail
    outputs["chase0"]["frame_records"][0]["t_applied_s"] += 1.0 / 120.0
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 0: captured at" in check.detail
    assert f"(tol {ENGINE_TIME_TOL_S:.4g})" in check.detail
    assert check.data["tolerances"]["time_s"] == ENGINE_TIME_TOL_S
    assert check.data["tolerances"]["rate_hz"] == 120.0


def test_engine_time_tolerance_comes_from_the_manifest_not_the_file_judged(
        tmp_path):
    """render.json's step_s is a FACT checked against the manifest's
    rate_hz, never the tolerance: a file declaring step_s = 10.0 fails
    by camera ("the engine stepped 10 s against the spec's 120 Hz") and
    a shifted capture time STILL fails with it in place."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    assert manifest["rate_hz"] == 120.0
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path, step_s=10.0)
    outputs["chase0"]["frame_records"][3]["t_applied_s"] += 0.05
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert ("chase0: the engine stepped 10 s against the spec's 120 Hz "
            "(1/120 = 0.008333 s); the frames are not on the manifest's "
            "grid") in check.detail
    assert "tower0: the engine stepped 10 s" in check.detail
    assert "chase0 frame 3: captured at" in check.detail
    assert check.data["cameras"]["chase0"]["verified"] == 14
    # A render.json that states no step at all cannot be checked either.
    del outputs["chase0"]["step_s"]
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert "chase0: render.json states no step_s" in check.detail
    # And a manifest without the rate has no grid to grade on.
    outputs = write_engine_output(manifest, tmp_path)
    stripped = dict(manifest)
    del stripped["rate_hz"]
    check = verify_engine_parity(tmp_path, stripped)
    assert check.ok is False
    assert "the manifest carries no rate_hz" in check.detail


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
    numbers. The budget is THIS run's: 1.5 steps (the measured one-step
    host phase plus half a step) x the frame's speed / the manifest's
    rate -- 99.43 m/s (the synthetic track's ground speed through the
    scene projection) at 120 Hz here, 0.829 m/step, budget 1.24 m --
    with the arithmetic in the detail line. One step of travel passes."""
    from core.capture.verify import (
        HOST_PHASE_MARGIN_STEPS, HOST_PHASE_STEPS, drawn_aircraft_budget_m,
        verify_engine_parity,
    )

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    record = outputs["chase0"]["frame_records"][2]
    speed = next(r for r in manifest["frames"] if r["camera_id"] == "chase0"
                 and r["index"] == 2)["aircraft"]["speed_mps"]
    assert speed == pytest.approx(99.43, abs=0.01)
    budget = drawn_aircraft_budget_m(speed, manifest["rate_hz"])
    assert budget["budget_m"] == pytest.approx(1.243, abs=1e-3)
    assert HOST_PHASE_STEPS == 1.0 and HOST_PHASE_MARGIN_STEPS == 0.5
    record["aircraft_applied_east_m"] += 0.83     # one 1/120 s step at 99.4 m/s
    # An honest engine measures and draws the aircraft where its FDM put
    # it: its own pixel and the blob move with the drawn point.
    move_drawn_aircraft(manifest, tmp_path, "chase0", record)
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is True, check.detail
    assert "aircraft drawn within 0.83 m" in check.detail
    assert "(budget 1.24 m = 1.5 steps x 0.829 m/step at 99.4 m/s)" in check.detail
    assert "px of its labelled pixel" in check.detail
    assert check.data["tolerances"]["aircraft_m"] == pytest.approx(1.243, abs=1e-3)

    # A second step (what a one-step clock offset would add) is over
    # budget by construction: the time clause refuses the clock, the
    # budget does not absorb it.
    record["aircraft_applied_east_m"] += 0.83     # 1.66 m
    move_drawn_aircraft(manifest, tmp_path, "chase0", record)
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 2: the engine drew the aircraft 1.66 m" in check.detail

    record["aircraft_applied_east_m"] += 3.34     # 5.0 m in all
    move_drawn_aircraft(manifest, tmp_path, "chase0", record)
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "chase0 frame 2: the engine drew the aircraft 5.00 m" in check.detail
    assert "(budget 1.24 m = 1.5 steps x 0.829 m/step at 99.4 m/s, 120 Hz)" in check.detail
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
    move_drawn_aircraft(manifest, tmp_path, "tower0",
                        outputs["tower0"]["frame_records"][9])
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "tower0 frame 9: the engine drew the aircraft 5.00 m" in check.detail


def move_drawn_aircraft(manifest, run_dir, camera_id, engine_record):
    """Keep an engine record honest after its drawn aircraft was moved:
    re-measure its own pixel through the applied pose (the solved one
    here) and redraw the blob there."""
    from core.capture.verify import axes_from_euler, project_point

    record = next(r for r in manifest["frames"] if r["camera_id"] == camera_id
                  and r["index"] == engine_record["frame_index"])
    drawn = (engine_record["aircraft_applied_north_m"],
             engine_record["aircraft_applied_east_m"],
             engine_record["aircraft_applied_alt_m"])
    u, v, depth = project_point(
        record, drawn, axes_from_euler(engine_record["camera_applied_roll_deg"],
                                       engine_record["camera_applied_pitch_deg"],
                                       engine_record["camera_applied_yaw_deg"]))
    engine_record.update({"aircraft_px": u, "aircraft_py": v,
                          "aircraft_visible": depth > 0,
                          "aircraft_bbox_px": [u - BLOB_RADIUS_PX,
                                               v - BLOB_RADIUS_PX,
                                               u + BLOB_RADIUS_PX,
                                               v + BLOB_RADIUS_PX]})
    honest_frame(run_dir / record["file"], record["width_px"],
                 record["height_px"], pixel=(u, v))


def test_engine_parity_fails_when_nothing_is_drawn_at_the_label(tmp_path):
    """The engine's numbers about itself are perfect; the PIXELS are
    judged: a flat frame (the mesh never loaded) fails by frame with
    both windows' luminance figures, and a frame whose blob sits 40 px
    from the label -- outside the label window, the engine still
    claiming the label -- fails the same clause. The honest frame, blob
    at the label, passes with the contrast stated."""
    from core.capture.verify import (
        ENGINE_LABEL_CONTRAST_MIN, verify_engine_parity,
    )

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    write_engine_output(manifest, tmp_path)
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is True, check.detail
    assert "lowest label window contrast" in check.detail
    assert f"(min {ENGINE_LABEL_CONTRAST_MIN:g})" in check.detail
    assert check.data["worst"]["label_contrast"] >= ENGINE_LABEL_CONTRAST_MIN
    assert check.data["worst"]["label_background"] == pytest.approx(30.0)

    # Flat: nothing drawn anywhere.
    record = next(r for r in manifest["frames"]
                  if r["camera_id"] == "tower0" and r["index"] == 7)
    honest_frame(tmp_path / record["file"], record["width_px"],
                 record["height_px"], pixel=None)
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert ("tower0 frame 7: nothing is drawn at the labelled pixel of "
            "frames/tower0/0007.png: label window [") in check.detail
    assert "mean 30.0 std 0.0 against background mean 30.0 std 0.0, contrast 0.0 (min 8)" in check.detail
    assert check.data["cameras"]["tower0"]["verified"] == 14
    assert check.data["worst"]["label_contrast"] == 0.0

    # Drawn, but 40 px from the label (the tower's window is +-16 px).
    from core.capture.verify import labelled_pixel

    u, v, _ = labelled_pixel(record)
    honest_frame(tmp_path / record["file"], record["width_px"],
                 record["height_px"], pixel=(u + 40.0, v))
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "tower0 frame 7: nothing is drawn at the labelled pixel" in check.detail
    assert check.data["cameras"]["tower0"]["verified"] == 14

    # Back at the label: the frame verifies again.
    honest_frame(tmp_path / record["file"], record["width_px"],
                 record["height_px"], pixel=(u, v))
    assert verify_engine_parity(tmp_path, manifest).ok is True


def test_engine_parity_fails_when_the_engine_measured_the_aircraft_elsewhere(
        tmp_path):
    """The engine's OWN projection of the aircraft it drew (aircraft_px /
    aircraft_py through the capture's transform) is graded against the
    labelled pixel: 40 px off on a tower frame (budget ~4.3 px at 1.2 km)
    fails by frame with both pixels; a record without it cannot be
    graded; 'not visible' where the label is in frame fails; and an
    engine pixel that disagrees with the manifest's projection model of
    the same drawn point by more than the pose tolerance fails even
    inside the graded budget (the chase's 24 px)."""
    from core.capture.verify import verify_engine_parity

    manifest = two_camera_manifest()
    write_capture_manifest(manifest, tmp_path)
    outputs = write_engine_output(manifest, tmp_path)
    record = outputs["tower0"]["frame_records"][7]
    label_px = record["aircraft_px"]
    record["aircraft_px"] = label_px + 40.0
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert ("tower0 frame 7: the engine measured the aircraft at "
            f"({label_px + 40.0:.1f}, {record['aircraft_py']:.1f}) px, 40.0 px "
            "from the labelled pixel") in check.detail
    assert "(tol 4.3 px)" in check.detail
    assert check.data["cameras"]["tower0"]["verified"] == 14
    assert check.data["worst"]["engine_px"] == pytest.approx(40.0)

    record["aircraft_px"] = label_px
    record["aircraft_visible"] = False
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert "tower0 frame 7: the engine reports the aircraft not visible" in check.detail

    for key in ("aircraft_px", "aircraft_py", "aircraft_visible"):
        del record[key]
    rewrite(tmp_path, "tower0", outputs["tower0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert ("tower0 frame 7: engine record lacks its own projection of the "
            "drawn aircraft") in check.detail

    # The chase's budget is 13.4 px at 150 m: 10 px off the label is inside
    # it, but 10 px off the manifest's projection of the SAME drawn point
    # means the engine's lens is not the manifest's lens.
    outputs = write_engine_output(manifest, tmp_path)
    chase = outputs["chase0"]["frame_records"][7]
    chase["aircraft_py"] += 10.0
    rewrite(tmp_path, "chase0", outputs["chase0"])
    check = verify_engine_parity(tmp_path, manifest)
    assert check.ok is False
    assert ("chase0 frame 7: the engine's own projection of the aircraft it "
            "drew disagrees with the manifest's projection model by 10.00 px "
            "(tol 3.0)") in check.detail
    assert "the engine measured the aircraft at" not in check.detail


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


# -- the report as a table and as data: every check carries its number,
# -- its tolerance and WHERE it was worst; SKIPPED is neither pass nor ran

def test_every_check_carries_measured_tolerance_and_where(tmp_path):
    """The table's cells and the JSON's fields are the same numbers: a
    FAIL says where, a PASS says what its worst case was."""
    write_capture_manifest(two_camera_manifest(), tmp_path)
    report = verify_run(tmp_path)
    data = report.to_dict()
    assert data["ok"] is True and data["ran"] == 5 and data["passed"] == 5
    assert data["skipped"] == [] and data["awaiting"] == ["engine_parity"]
    for check in data["checks"]:
        for key in ("measured_text", "tolerance_text", "where", "status",
                    "skipped_reason"):
            assert key in check, (check["name"], key)
    by_name = {c["name"]: c for c in data["checks"]}
    geometry = by_name["geometry_recovery"]
    assert geometry["unit"] == "px" and geometry["tolerance"] == 0.5
    assert geometry["measured"] <= 0.5
    assert geometry["where"].startswith("worst ") and " #" in geometry["where"]
    cross = by_name["cross_view_consistency"]
    assert cross["unit"] == "m" and cross["tolerance"] == 0.5
    assert "15 two-view instants; worst sample" in cross["where"]
    counts = by_name["count_exactness"]
    assert counts["measured_text"] == "30 frames = 15 + 15"
    assert counts["tolerance_text"] == "exactly 30"
    assert counts["where"] == "chase0 15/15, tower0 15/15"
    # The rendered table has one row per check with the same cells.
    rows = report.table_rows()
    assert [r[0] for r in rows] == [c["name"] for c in data["checks"]]
    assert data["table"] == rows
    table = report.table().splitlines()
    assert table[0].split() == ["CHECK", "STATUS", "MEASURED", "TOLERANCE",
                                "WHERE"]
    assert len(table) == 1 + len(data["checks"])
    for line, (name, status, measured, tolerance, where) in zip(table[1:],
                                                                rows):
        assert line.startswith(f"  {name}")
        assert f"  {status}  " in line
        assert measured in line and tolerance in line and where in line
    # The detail lines and the summary follow the table.
    rendered = report.render()
    assert rendered.index("CHECK") < rendered.index("  detail:") \
        < rendered.index("[PASS] manifest_version:") \
        < rendered.index("verification PASSED (5/5 checks")


def test_a_bad_quaternion_is_localised_by_camera_frame_and_instant():
    bad = two_camera_manifest()
    record = bad["frames"][5]
    record["quaternion_wxyz"] = list(
        euler_to_quat(0.0, record["pitch_deg"] + 5.0, record["yaw_deg"]))
    check = verify_geometry(bad)
    assert check.ok is False
    expected = (f"{record['camera_id']} #{record['index']} "
                f"t={record['t_s']:.3f} s")
    assert check.where == f"worst {expected}", check.where
    assert expected in check.detail
    assert check.measured > 0.5 and check.tolerance == 0.5
    assert check.data["worst_frame"] == expected
    # The table row says where, not only how much.
    from core.capture.verify import VerificationReport

    report = VerificationReport([check])
    row = report.table().splitlines()[1]
    assert "FAIL" in row and expected in row


def test_a_misattributed_state_is_localised_by_sample_and_cameras():
    bad = two_camera_manifest()
    for record in bad["frames"]:
        if record["camera_id"] == "tower0":
            record["aircraft"]["north_m"] += 5.0
    check = verify_triangulation(bad)
    assert check.ok is False
    # A 5 m misattribution triangulates to at least 5 m of error (the
    # rays no longer meet at the recorded point); the number is measured.
    assert 5.0 <= check.measured < 6.0, check.measured
    assert check.where.startswith("15 two-view instants; worst sample ")
    assert "chase0 #" in check.where and "with tower0 #" in check.where
    assert check.data["worst_at"] in check.where
    # ONE misattributed record: the offender is that sample, by name.
    one = two_camera_manifest()
    target = [r for r in one["frames"] if r["camera_id"] == "tower0"][7]
    target["aircraft"]["north_m"] += 5.0
    check = verify_triangulation(one)
    assert check.ok is False
    assert (f"worst sample {target['sample_index']} t={target['t_s']:.3f} s"
            in check.where)
    assert "with tower0 #7)" in check.where


def test_a_skipped_check_is_neither_passed_nor_ran(tmp_path):
    """One camera: cross-view consistency is SKIPPED with its reason --
    ok None, out of both tallies, named in the summary and the JSON."""
    write_capture_manifest(
        manifest_for(spec_with(counted("chase", "solo"))), tmp_path)
    report = verify_run(tmp_path)
    assert report.ok
    assert [c.name for c in report.skipped] == ["cross_view_consistency"]
    assert report.skipped[0].status == "SKIPPED"
    assert report.passed == 4 and report.ran == 4
    assert report.summary() == (
        "verification PASSED (4/4 checks; 1 skipped: cross_view_consistency "
        "(single camera); 1 awaiting engine frames: engine_parity)")
    data = report.to_dict()
    assert data["skipped"] == [{"name": "cross_view_consistency",
                                "reason": "single camera"}]
    assert data["passed"] == 4 and data["ran"] == 4
    assert "[SKIPPED] cross_view_consistency: NOT EXERCISED (single camera)" \
        in report.render()
    row = [r for r in report.table_rows()
           if r[0] == "cross_view_consistency"][0]
    assert row[1] == "SKIPPED" and row[4] == "single camera"


def test_alignment_names_the_run_with_the_extra_instant_and_the_gap():
    columns = make_columns(duration_s=14.0)
    a = manifest_for(spec_with(counted("chase", "chase0")), columns)
    c = manifest_for(spec_with(counted("chase", "chase0")), columns)
    c["frames"][3]["t_s"] += 0.05
    check = verify_alignment(a, c, label_a="demo", label_b="demo_b")
    assert check.ok is False
    assert check.unit == "s" and check.tolerance == 1e-9
    assert check.measured == pytest.approx(0.05, abs=1e-6)
    t3 = a["frames"][3]["t_s"]
    assert (f"t={t3:.6f} s in demo against {t3 + 0.05:.6f} s in demo_b"
            in check.detail)
    assert "worst gap 0.05 s at t=" in check.where
    # A run with an EXTRA instant is named, with the instant.
    d = manifest_for(spec_with(counted("chase", "chase0")), columns)
    d["frames"].append(dict(d["frames"][-1], index=15, t_s=13.37))
    check = verify_alignment(a, d, label_a="demo", label_b="demo_b")
    assert check.ok is False
    assert check.measured_cell == "15 vs 16 instants"
    assert "16 in demo_b; only in demo_b: t=13.370000 s" in check.where
    assert check.data["instants"] == [15, 16]
    good = verify_alignment(a, c := manifest_for(
        spec_with(counted("tower", "tower0")), columns),
        label_a="demo", label_b="demo_b")
    assert good.ok and good.measured == 0.0
    assert good.where == "15 instants in both runs; worst gap 0 s"
