"""Camera Phase 1, package D: named camera refusals.

One test per named constraint that TRIPS it: refusals are first-class
results, and a check that cannot fail is not a check (each of these has
a mutation guard in scripts/mutation_check.sh that disables the check
and expects the test here to fail).
"""

import numpy as np
import pytest

from core.capture.poses import SceneFrame, solve_pose_track
from core.capture.validate import (
    CAMERA_MIN_CLEARANCE_M, intrinsics_violations, schedule_violations,
    static_camera_violations, track_violations, validate_cameras,
    vocabulary_violations,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec
from core.terrain.heightfield import Georeference, Heightfield

from tests.test_camera_poses import FRAME, make_columns


def camera(**fields):
    cam = CameraSpec.defaulted(camera_id="cam", preset="chase",
                               aircraft="B747")
    for name, value in fields.items():
        cam.set(name, value, frm="test")
    return cam


def constraints(violations):
    return [v.constraint for v in violations]


# -- camera.intrinsics ---------------------------------------------------

def test_zero_focal_length_refuses():
    violations = intrinsics_violations(camera(focal_length_mm=0.0))
    assert "camera.intrinsics" in constraints(violations)


def test_far_before_near_refuses():
    violations = intrinsics_violations(camera(near_m=10.0, far_m=5.0))
    assert any(v.constraint == "camera.intrinsics"
               and "far plane" in v.message for v in violations)


def test_nonsense_resolution_refuses():
    violations = intrinsics_violations(camera(width_px=0))
    assert "camera.intrinsics" in constraints(violations)
    violations = intrinsics_violations(camera(height_px=100000))
    assert "camera.intrinsics" in constraints(violations)


def test_physical_camera_passes():
    assert intrinsics_violations(camera()) == []


# -- camera.preset -------------------------------------------------------

def test_unknown_preset_refuses_by_name():
    violations = vocabulary_violations(camera(preset="drone"))
    assert constraints(violations) == ["camera.preset"]
    assert "drone" in violations[0].message


def test_unknown_aim_mode_refuses():
    violations = vocabulary_violations(camera(aim_mode="vibes"))
    assert constraints(violations) == ["camera.preset"]


# -- camera.schedule (scene-free half) ----------------------------------

def test_unknown_trigger_refuses():
    violations = schedule_violations(camera(trigger="sometimes"))
    assert constraints(violations) == ["camera.schedule"]


def test_negative_count_refuses():
    violations = schedule_violations(camera(capture_count=-1))
    assert "camera.schedule" in constraints(violations)


def test_interval_with_no_count_and_no_period_refuses():
    violations = schedule_violations(camera(capture_count=0, period_s=0.0))
    assert "camera.schedule" in constraints(violations)


# -- the whole surface rides validate() ---------------------------------

def test_core_validate_carries_camera_refusals():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [camera(focal_length_mm=-5.0)]
    from core.scenario.validate import validate

    report = validate(spec, check_feasibility=False)
    assert not report.ok
    assert any(v.constraint == "camera.intrinsics"
               for v in report.violations)


def test_duplicate_camera_ids_refuse():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [camera(), camera()]
    assert any(v.constraint == "camera.preset" and "twice" in v.message
               for v in validate_cameras(spec))


def test_validation_never_moves_a_stated_camera_field():
    """Refusal by name is the only path: validating an invalid stated
    camera changes nothing about the spec (digest identical), and
    plan() on the stated field still refuses."""
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [camera()]
    spec.set("cameras[0].focal_length_mm", -5.0, frm="stated, wrong")
    before = spec.digest()
    from core.scenario.validate import validate

    report = validate(spec, check_feasibility=False)
    assert not report.ok
    assert spec.digest() == before
    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("cameras[0].focal_length_mm", 35.0, frm="fix it")


# -- scene-coupled: a synthetic mountain --------------------------------

def make_mountain():
    """A 64x64, 10 m/px raster around the scene origin: a 500 m plain
    with a 1500 m peak at the centre."""
    x = np.linspace(-1.0, 1.0, 64)
    xx, yy = np.meshgrid(x, x)
    z = 500.0 + 1000.0 * np.exp(-((xx * 3) ** 2 + (yy * 3) ** 2))
    geo = Georeference(crs=FRAME.crs,
                       origin_x_m=FRAME.origin_x_m - 320.0,
                       origin_y_m=FRAME.origin_y_m + 320.0,
                       pixel_size_m=10.0)
    return Heightfield.from_elevations(z, geo, name="test-mountain")


def test_static_camera_inside_the_mountain_refuses():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    cam = CameraSpec.defaulted(camera_id="buried", preset="explicit")
    cam.set("position_mode", "scene", frm="stated")
    cam.set("position_north_m", 0.0, frm="stated")
    cam.set("position_east_m", 0.0, frm="stated")
    cam.set("position_alt_m", 600.0, frm="stated")     # peak is ~1500 m
    spec.cameras = [cam]
    violations = static_camera_violations(spec, make_mountain(), FRAME)
    assert [v.constraint for v in violations] == ["camera.terrain_clearance"]
    assert violations[0].limit == CAMERA_MIN_CLEARANCE_M


def test_static_camera_above_the_mountain_passes():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    cam = CameraSpec.defaulted(camera_id="high", preset="explicit")
    cam.set("position_mode", "scene", frm="stated")
    cam.set("position_alt_m", 2000.0, frm="stated")
    spec.cameras = [cam]
    assert static_camera_violations(spec, make_mountain(), FRAME) == []


def test_static_camera_off_the_raster_refuses_scene_bounds():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    cam = CameraSpec.defaulted(camera_id="offmap", preset="explicit")
    cam.set("position_mode", "scene", frm="stated")
    cam.set("position_north_m", 5000.0, frm="stated")  # raster is +-320 m
    cam.set("position_alt_m", 2000.0, frm="stated")
    spec.cameras = [cam]
    violations = static_camera_violations(spec, make_mountain(), FRAME)
    assert [v.constraint for v in violations] == ["camera.scene_bounds"]


def test_static_camera_inside_the_tornado_core_refuses():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    cam = CameraSpec.defaulted(camera_id="inside", preset="explicit")
    cam.set("position_mode", "scene", frm="stated")
    cam.set("position_north_m", 1000.0, frm="stated")
    cam.set("position_alt_m", 800.0, frm="stated")
    spec.cameras = [cam]
    tornado = {"centre_north_m": 1000.0, "centre_east_m": 0.0,
               "r_core_m": 150.0, "fade_top_m": 3000.0}
    violations = static_camera_violations(spec, None, FRAME,
                                          tornado=tornado)
    assert [v.constraint for v in violations] == \
        ["camera.hazard_intersection"]


# -- the SOLVED track, checked along the whole run ----------------------

def buried_ground_camera():
    cam = CameraSpec.defaulted(camera_id="lowground", preset="ground")
    cam.set("position_mode", "scene", frm="stated")
    cam.set("position_north_m", 0.0, frm="stated")
    cam.set("position_east_m", 0.0, frm="stated")
    cam.set("position_alt_m", 600.0, frm="stated")
    return cam


def test_solved_track_inside_terrain_refuses_whole_track():
    columns = make_columns(duration_s=10.0, altitude=lambda t: 3000.0)
    track = solve_pose_track(columns, buried_ground_camera(), FRAME)
    violations = track_violations(track, heightfield=make_mountain(),
                                  scene_frame=FRAME)
    assert "camera.terrain_clearance" in [v.constraint for v in violations]


def test_solved_track_off_the_raster_refuses_scene_bounds():
    # 100 m/s for 10 s runs the chase camera off the +-320 m raster.
    columns = make_columns(duration_s=10.0, altitude=lambda t: 3000.0)
    cam = CameraSpec.defaulted(camera_id="drift", preset="chase",
                               aircraft="B747")
    track = solve_pose_track(columns, cam, FRAME)
    violations = track_violations(track, heightfield=make_mountain(),
                                  scene_frame=FRAME)
    assert "camera.scene_bounds" in [v.constraint for v in violations]


def test_solved_track_through_the_core_refuses_hazard():
    # A cockpit camera rides the aircraft straight through a vortex
    # core placed on the track at cruise altitude.
    columns = make_columns(duration_s=10.0, altitude=lambda t: 800.0)
    cam = CameraSpec.defaulted(camera_id="ride", preset="cockpit",
                               aircraft="B747")
    track = solve_pose_track(columns, cam, FRAME)
    tornado = {"centre_north_m": 500.0, "centre_east_m": 0.0,
               "r_core_m": 150.0, "fade_top_m": 3000.0}
    violations = track_violations(track, tornado=tornado,
                                  terrain_elevation_m=0.0)
    assert [v.constraint for v in violations] == \
        ["camera.hazard_intersection"]


def test_clear_track_passes():
    # 2 s at 100 m/s keeps aircraft and chase camera on the +-320 m
    # test raster; a longer run drifts off it and trips scene_bounds
    # (correctly -- see the off-raster test above).
    columns = make_columns(duration_s=2.0, altitude=lambda t: 3000.0)
    cam = CameraSpec.defaulted(camera_id="ok", preset="chase",
                               aircraft="B747")
    track = solve_pose_track(columns, cam, FRAME)
    assert track_violations(track, heightfield=make_mountain(),
                            scene_frame=FRAME) == []
