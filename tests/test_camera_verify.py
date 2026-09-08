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
    verify_engine_parity, verify_intrinsics, verify_placement, verify_run,
    verify_telemetry_agreement, verify_triangulation,
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


def write_run(directory, manifest, columns=None):
    """A run directory as ``flightsim.capture`` writes one: the manifest
    AND the telemetry it claims to label. The external-anchor checks
    read the second one, so a directory without it is not verifiable."""
    import json

    write_capture_manifest(manifest, directory)
    (directory / "telemetry.json").write_text(
        json.dumps({"columns": columns or make_columns(duration_s=14.0)}),
        encoding="utf-8")
    return directory


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


def test_count_exactness_catches_a_gap_in_an_UNCOUNTED_schedule():
    """The dense-index condition, exercised where nothing else can cover
    for it: a period-triggered camera states no count, so only the index
    sequence can catch a dropped or misattributed frame. (Without this,
    the requested-count check shadows the index check and the index
    guard reports WEAK.)"""
    camera = CameraSpec.defaulted(camera_id="ticker", preset="tower",
                                  aircraft="B747")
    camera.set("period_s", 2.0, frm="test: an uncounted schedule")
    manifest = manifest_for(spec_with(camera))
    assert int(manifest["cameras"][0]["spec"]["capture_count"]["value"]) == 0
    assert verify_counts(manifest).ok
    # A hole in the middle: the count still matches nothing stated, so
    # only the dense-index condition can see it.
    declared = manifest["cameras"][0]["capture_count"]
    manifest["frames"] = [r for r in manifest["frames"] if r["index"] != 2]
    manifest["cameras"][0]["capture_count"] = declared
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
    write_run(tmp_path, two_camera_manifest())
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


def test_verify_run_refuses_a_manifest_with_no_telemetry(tmp_path):
    """Three of the checks anchor the manifest to the recorded flight.
    Without telemetry.json they have nothing to anchor to, and "cannot
    be verified" is reported as a failure, not as a pass."""
    write_capture_manifest(two_camera_manifest(), tmp_path)
    report = verify_run(tmp_path)
    assert not report.ok
    assert any(not c.ok and c.name == "telemetry_agreement"
               for c in report.checks)


# -- checks 5-7: the external anchors -----------------------------------
#
# Checks 1-4 read the manifest against itself. Measured before these
# existed, ALL of them passed on a manifest whose camera had been
# displaced 500 m and re-aimed, whose focal length had been multiplied
# by 1.7, and which had delivered 10 of 24 requested images. Each test
# below reproduces one of those corruptions and demands a failure.

def corrupted(manifest, camera_id, **changes):
    """A deep copy of a manifest with one camera's frame records
    edited -- the "plausible fiction" shape."""
    import copy

    out = copy.deepcopy(manifest)
    for record in out["frames"]:
        if record["camera_id"] == camera_id:
            for key, value in changes.items():
                record[key] = (value(record[key]) if callable(value)
                               else value)
    return out


def reaimed(manifest, camera_id, dnorth=0.0, deast=0.0):
    """Displace one camera and re-aim it at the aircraft, so the
    manifest stays internally consistent -- exactly the corruption the
    self-referential checks cannot see."""
    out = corrupted(manifest, camera_id,
                    position_north_m=lambda v: v + dnorth,
                    position_east_m=lambda v: v + deast)
    for record in out["frames"]:
        if record["camera_id"] != camera_id:
            continue
        a = record["aircraft"]
        dn = a["north_m"] - record["position_north_m"]
        de = a["east_m"] - record["position_east_m"]
        dalt = a["alt_m"] - record["position_alt_m"]
        yaw = math.degrees(math.atan2(de, dn)) % 360.0
        pitch = math.degrees(math.atan2(dalt, math.hypot(dn, de)))
        record["yaw_deg"], record["pitch_deg"] = yaw, pitch
        record["quaternion_wxyz"] = list(euler_to_quat(0.0, pitch, yaw))
    return out


def test_the_self_referential_checks_pass_a_displaced_camera():
    """The reason checks 5-7 exist, stated as a test: geometry recovery
    and triangulation are blind to a camera that was moved and re-aimed,
    because both read only the manifest's own numbers."""
    bad = reaimed(two_camera_manifest(), "tower0", dnorth=500.0, deast=-300.0)
    assert verify_geometry(bad).ok
    assert verify_triangulation(bad).ok


def test_placement_catches_a_displaced_world_anchored_camera():
    manifest = two_camera_manifest()
    columns = make_columns(duration_s=14.0)
    assert verify_placement(manifest, columns).ok
    bad = reaimed(manifest, "tower0", dnorth=500.0, deast=-300.0)
    check = verify_placement(bad, columns)
    assert not check.ok
    assert "tower0" in check.detail


def test_placement_catches_a_displaced_offset_camera():
    manifest = two_camera_manifest()
    columns = make_columns(duration_s=14.0)
    bad = reaimed(manifest, "chase0", dnorth=500.0)
    check = verify_placement(bad, columns)
    assert not check.ok
    assert "lag envelope" in check.detail


def test_placement_accepts_the_lag_a_chase_camera_really_has():
    """The envelope must not be so tight that an honest lagged chase
    camera trips it: a first-order lag tracking a ramp trails by v*tau,
    which is real geometry, not a defect."""
    columns = make_columns(duration_s=14.0, speed_mps=140.0)
    manifest = manifest_for(spec_with(counted("chase", "chase0")), columns)
    check = verify_placement(manifest, columns)
    assert check.ok, check.detail


def test_intrinsics_catch_a_focal_length_the_spec_never_asked_for():
    manifest = two_camera_manifest()
    assert verify_intrinsics(manifest).ok
    # The engine-disagreement shape: the manifest advertises a lens the
    # pixels were never taken with.
    bad = corrupted(manifest, "chase0", focal_length_mm=85.0)
    assert not verify_intrinsics(bad).ok


def test_intrinsics_catch_pixel_focal_lengths_that_do_not_follow():
    bad = corrupted(two_camera_manifest(), "tower0",
                    fx_px=lambda v: v * 1.7, fy_px=lambda v: v * 1.7)
    check = verify_intrinsics(bad)
    assert not check.ok
    assert "does not follow" in check.detail


@pytest.mark.parametrize("axis", ["fx_px", "fy_px"])
def test_intrinsics_catch_ONE_wrong_pixel_focal_length(axis):
    """Each axis carries its own guarantee. Checked as a single `or`,
    either half covers for the other and neither guard is load-bearing
    -- and a camera whose sensor aspect differs from its output aspect
    is exactly where only one of the two goes wrong."""
    bad = corrupted(two_camera_manifest(), "tower0",
                    **{axis: lambda v: v * 1.7})
    check = verify_intrinsics(bad)
    assert not check.ok
    assert axis[:2] in check.detail


def test_intrinsics_catch_a_principal_point_off_centre():
    bad = corrupted(two_camera_manifest(), "tower0",
                    principal_point_px=[10.0, 10.0])
    assert not verify_intrinsics(bad).ok


def test_counts_catch_a_shortfall_the_producer_wrote_down():
    """The count contract is the SPECIFICATION's number. A producer that
    delivers 10 of 24 and records "10" passed the old check."""
    manifest = two_camera_manifest()
    manifest["frames"] = [r for r in manifest["frames"]
                          if r["camera_id"] != "chase0" or r["index"] < 10]
    for block in manifest["cameras"]:
        if block["camera_id"] == "chase0":
            block["capture_count"] = 10
    check = verify_counts(manifest)
    assert not check.ok
    assert "its specification requests" in check.detail


def test_telemetry_agreement_catches_a_shifted_sample_index():
    columns = make_columns(duration_s=14.0)
    manifest = manifest_for(spec_with(counted("chase", "chase0")), columns)
    assert verify_telemetry_agreement(manifest, columns).ok
    bad = corrupted(manifest, "chase0",
                    sample_index=lambda v: min(v + 3, len(columns["t"]) - 1))
    assert not verify_telemetry_agreement(bad, columns).ok


def test_telemetry_agreement_catches_a_fabricated_frame_time():
    columns = make_columns(duration_s=14.0)
    manifest = manifest_for(spec_with(counted("chase", "chase0")), columns)
    bad = corrupted(manifest, "chase0", t_s=lambda v: v + 0.05)
    assert not verify_telemetry_agreement(bad, columns).ok


def test_telemetry_agreement_refuses_without_telemetry():
    assert not verify_telemetry_agreement(two_camera_manifest(), None).ok


# -- check 8: engine parity (package G's claim, graded from Python) -----
#
# The phase names the risk: "if the engine ever recomputes a pose instead
# of consuming it, the manifest becomes a plausible fiction". The host
# writes what it APPLIED into render.json; these tests grade that against
# the solved manifest, and they run on any platform because the render
# manifest is just JSON. On macOS the same function grades a real one.

def render_manifest_from(manifest, camera_id, **drift):
    """A render.json as the commandlet's consume-poses mode writes one,
    optionally drifted to model a host that recomputed instead of
    consuming."""
    from core.capture.manifest import horizontal_fov_deg

    frames = []
    for record in manifest["frames"]:
        if record["camera_id"] != camera_id:
            continue
        fov = horizontal_fov_deg(record["focal_length_mm"],
                                 record["sensor_width_mm"])
        frames.append({
            "frame": f"frame_{record['index']:04d}.png",
            "t": record["t_s"],
            "camera_index": 0,
            "camera_applied_north_m":
                record["position_north_m"] + drift.get("north_m", 0.0),
            "camera_applied_east_m": record["position_east_m"],
            "camera_applied_alt_m": record["position_alt_m"],
            "camera_applied_yaw_deg":
                record["yaw_deg"] + drift.get("yaw_deg", 0.0),
            "camera_applied_pitch_deg": record["pitch_deg"],
            "camera_applied_roll_deg": record["roll_deg"],
            "camera_applied_hfov_deg": drift.get("hfov_deg", fov),
            "camera_applied_width_px": drift.get("width_px",
                                                 record["width_px"]),
            "camera_applied_height_px": record["height_px"],
        })
    return {"frames": frames}


def test_engine_parity_passes_when_the_host_consumed_the_pose():
    manifest = two_camera_manifest()
    render = render_manifest_from(manifest, "tower0")
    check = verify_engine_parity(manifest, render, "tower0")
    assert check.ok, check.detail


def test_engine_parity_catches_a_recomputed_pose():
    manifest = two_camera_manifest()
    render = render_manifest_from(manifest, "tower0", north_m=0.5)
    assert not verify_engine_parity(manifest, render, "tower0").ok
    render = render_manifest_from(manifest, "tower0", yaw_deg=0.2)
    assert not verify_engine_parity(manifest, render, "tower0").ok


def test_engine_parity_catches_the_hardcoded_field_of_view():
    """The measured defect: the render commandlet framed every visual
    shot at 55 deg while the manifest recorded fx from the spec's 35 mm
    lens on a 36 mm sensor (54.43 deg). A pose-only parity check is
    silent about it; this is not."""
    manifest = two_camera_manifest()
    render = render_manifest_from(manifest, "tower0", hfov_deg=55.0)
    check = verify_engine_parity(manifest, render, "tower0")
    assert not check.ok
    assert "lens these pixels were not taken with" in check.detail


def test_engine_parity_catches_a_resolution_the_manifest_does_not_carry():
    manifest = two_camera_manifest()
    render = render_manifest_from(manifest, "tower0", width_px=960)
    assert not verify_engine_parity(manifest, render, "tower0").ok


def test_engine_parity_reports_not_exercised_without_applied_fields():
    manifest = two_camera_manifest()
    check = verify_engine_parity(manifest, {"frames": [{"frame": "a.png"}]},
                                 "tower0")
    assert check.ok and "NOT EXERCISED" in check.detail


def test_the_lens_arithmetic_round_trips():
    """One statement of the lens, used by both halves: the manifest's
    fx_px and the render host's field of view must be the same camera."""
    from core.capture.manifest import horizontal_fov_deg, pixel_focal_from_fov

    for focal, sensor, width in ((35.0, 36.0, 1280), (85.0, 36.0, 1920),
                                 (24.0, 36.0, 640)):
        fov = horizontal_fov_deg(focal, sensor)
        assert pixel_focal_from_fov(fov, width) == pytest.approx(
            focal / sensor * width, rel=1e-12)
