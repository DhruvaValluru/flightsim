"""The corruptions Phase 1's verifier could not see.

Every corruption below was run against the Phase 1 verifier on a real
captured manifest and PASSED. That is the regression these tests exist
for, and it is the reason the checks were rebuilt around what each
one's independent reference actually is:

    corruption                              Phase 1     now
    ------------------------------------    --------    ----------------
    a camera displaced 300 m                PASS        pose_matches_spec
    every focal length scaled 1.7x          PASS        intrinsics
    fx/fy alone scaled 1.7x                 PASS        intrinsics
    the requested capture count inflated    PASS        count_exactness
    one camera's aircraft state moved       caught      aircraft_state_*

A verifier is only worth its runtime if it fails on a wrong manifest,
so each test here corrupts one thing and asserts the named check goes
red. The mutation guards in scripts/mutation_check.sh disable each
safeguard in turn and confirm the matching test then fails.
"""

import copy
import math

import pytest

from core.capture.manifest import build_capture_manifest
from core.capture.poses import solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, NOT_RUN, PASS, verify_aircraft_consistency, verify_counts,
    verify_geometry, verify_intrinsics, verify_pose_matches_spec,
    verify_triangulation,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


def counted(preset, camera_id, count=12, **kwargs):
    camera = CameraSpec.defaulted(camera_id=camera_id, preset=preset,
                                  aircraft="B747", **kwargs)
    camera.set("capture_count", count, frm="test")
    return camera


@pytest.fixture
def manifest():
    """A real two-camera manifest over real solved telemetry."""
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [counted("chase", "chase0"), counted("tower", "tower0")]
    columns = make_columns(duration_s=14.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                  output_digest="digest", cameras=spec.cameras)


def test_the_clean_manifest_passes_every_offline_check(manifest):
    """The corruption tests below mean nothing if the uncorrupted
    manifest does not pass first."""
    for check in (verify_intrinsics(manifest),
                  verify_pose_matches_spec(manifest),
                  verify_geometry(manifest),
                  verify_counts(manifest),
                  verify_aircraft_consistency(manifest)):
        assert check.status == PASS, f"{check.name}: {check.detail}"


def test_a_displaced_camera_is_caught(manifest):
    """Phase 1: PASS, triangulation error 0.0000 m. A camera 300 m from
    where its spec puts it is the plainest possible geometry bug."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        if record["camera_id"] == "chase0":
            record["position_east_m"] += 300.0
    check = verify_pose_matches_spec(bad)
    assert check.status == FAIL
    assert "stated station" in check.detail


def test_a_displaced_world_anchored_camera_is_caught(manifest):
    """A stated placement is never silently moved; a tower that is not
    where the spec put it fails by name."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        if record["camera_id"] == "tower0":
            record["position_north_m"] += 25.0
    check = verify_pose_matches_spec(bad)
    assert check.status == FAIL
    assert "spec states" in check.detail


def test_an_aim_that_stops_tracking_the_aircraft_is_caught(manifest):
    """An aircraft-aimed camera must actually point at the aircraft."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        if record["camera_id"] == "tower0":
            # Yaw the recorded orientation 90 deg off its target.
            w, x, y, z = record["quaternion_wxyz"]
            half = math.radians(90.0) / 2.0
            cw, sw = math.cos(half), math.sin(half)
            record["quaternion_wxyz"] = [w * cw - z * sw, x * cw + y * sw,
                                         y * cw - x * sw, z * cw + w * sw]
    check = verify_pose_matches_spec(bad)
    assert check.status == FAIL
    assert "aim" in check.detail


def test_a_scaled_lens_is_caught(manifest):
    """Phase 1: PASS on every check. Scaling the focal length and the
    pixel focal lengths together keeps the manifest internally
    consistent -- only the SPEC knows what lens was asked for."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        record["fx_px"] *= 1.7
        record["fy_px"] *= 1.7
        record["focal_length_mm"] *= 1.7
    check = verify_intrinsics(bad)
    assert check.status == FAIL
    assert "focal length" in check.detail


def test_scaled_pixel_focal_lengths_alone_are_caught(manifest):
    """The other half: fx/fy that no longer follow from the focal
    length and sensor size they are recorded beside."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        record["fx_px"] *= 1.7
        record["fy_px"] *= 1.7
    check = verify_intrinsics(bad)
    assert check.status == FAIL
    assert "focal/sensor*pixels" in check.detail


def test_a_resolution_the_spec_did_not_ask_for_is_caught(manifest):
    """The rendered resolution is part of the label. A manifest that
    claims one the spec never stated is refused."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        record["width_px"] = 960
        record["principal_point_px"] = [480.0, record["height_px"] / 2.0]
    check = verify_intrinsics(bad)
    assert check.status == FAIL
    assert "width_px" in check.detail


def test_an_inflated_requested_count_is_caught(manifest):
    """Phase 1: PASS. verify_counts compared the schedule length against
    the frame list -- the same number twice. The number that matters is
    the one the user asked for."""
    bad = copy.deepcopy(manifest)
    bad["cameras"][0]["spec"]["capture_count"]["value"] = 999
    check = verify_counts(bad)
    assert check.status == FAIL
    assert "999" in check.detail


def test_a_dropped_frame_is_still_caught(manifest):
    bad = copy.deepcopy(manifest)
    bad["frames"] = bad["frames"][:-1]
    assert verify_counts(bad).status == FAIL


def test_a_gap_in_the_frame_indices_is_caught(manifest):
    """The right NUMBER of frames indexed 0,1,2,4,5.. is still a broken
    frame set: a consumer walking 0..n-1 would miss one and read one that
    does not exist. Exercised separately from the count clause, which
    would otherwise shadow it and leave this guard untested."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        if record["camera_id"] == "chase0" and record["index"] >= 3:
            record["index"] += 1          # count unchanged, 3 now missing
    check = verify_counts(bad)
    assert check.status == FAIL
    assert "densely" in check.detail or "dense" in check.detail


def test_a_manifest_that_contradicts_itself_about_the_aircraft(manifest):
    """The one corruption Phase 1's triangulation did catch, kept as a
    check that names what it actually tests: self-consistency."""
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        if record["camera_id"] == "tower0":
            record["aircraft"]["north_m"] += 50.0
    check = verify_aircraft_consistency(bad)
    assert check.status == FAIL
    assert "disagree" in check.detail


def test_swapping_aircraft_states_between_cameras_is_a_no_op(manifest):
    """Worth pinning, because it is easy to mistake for a corruption:
    at a shared instant both cameras record the SAME aircraft state, so
    exchanging them changes nothing in the file. No check can detect it
    because there is nothing to detect -- which is precisely why
    triangulating the aircraft across two cameras carried no
    information in Phase 1."""
    bad = copy.deepcopy(manifest)
    by_sample = {}
    for record in bad["frames"]:
        by_sample.setdefault(record["sample_index"], []).append(record)
    swapped = 0
    for records in by_sample.values():
        if len(records) == 2:
            records[0]["aircraft"], records[1]["aircraft"] = (
                records[1]["aircraft"], records[0]["aircraft"])
            swapped += 1
    assert swapped > 0
    assert bad["frames"] == manifest["frames"]


def test_triangulation_reports_not_run_without_engine_pixels(manifest):
    """The load-bearing honesty fix: with no independently measured
    pixels there is no two-view check to run, and saying so beats
    reporting a 0.0000 m error that no corruption can move."""
    check = verify_triangulation(manifest, run_dir=None)
    assert check.status == NOT_RUN
    assert "independently" in check.detail


def test_landmarks_are_recorded_and_land_off_axis(manifest):
    """A projection check exercised only at the optical centre proves
    almost nothing, so the landmark set has to reach the corners."""
    from core.capture.verify import _landmark_coverage

    assert manifest["landmarks"], "no landmarks recorded"
    in_frame, worst_radius = _landmark_coverage(manifest)
    assert in_frame > 0, "no landmark lands inside any frame"
    assert worst_radius > 0.5, (
        f"landmarks only reach {worst_radius:.2f} of the half-diagonal; "
        f"the projection is never exercised near the frame edge")
