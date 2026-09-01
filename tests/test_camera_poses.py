"""Camera Phase 1, package B: the pose solver.

The pose track is a pure function of the recorded telemetry and the
camera spec -- bit-identical across invocations, sample-rate
independent for keyframed moves, and faithful to the C++ presets'
one non-negotiable property: only the cockpit preset inherits roll.
"""

import math

import pytest

from core.capture.poses import (
    PoseSolveError, SceneFrame, aircraft_local_track, euler_to_quat,
    solve_pose_track,
)
from core.scenario.camera import CameraSpec

FRAME = SceneFrame("EPSG:32631", 0.0, 0.0, declared=True)


def make_columns(duration_s=20.0, dt=0.1, speed_mps=100.0,
                 roll=lambda t: 0.0, pitch=lambda t: 0.0,
                 heading=lambda t: 0.0, altitude=lambda t: 1000.0):
    """A synthetic northbound telemetry record on the recorder's clock."""
    n = int(round(duration_s / dt)) + 1
    metres_per_degree = 111_320.0
    columns = {name: [] for name in
               ("t", "lat_deg", "lon_deg", "altitude_m", "roll_deg",
                "pitch_deg", "heading_deg")}
    for i in range(n):
        t = round(i * dt, 6)
        columns["t"].append(t)
        columns["lat_deg"].append(speed_mps * t / metres_per_degree)
        columns["lon_deg"].append(0.0)
        columns["altitude_m"].append(altitude(t))
        columns["roll_deg"].append(roll(t))
        columns["pitch_deg"].append(pitch(t))
        columns["heading_deg"].append(heading(t))
    return columns


def camera_for(preset, **kwargs):
    return CameraSpec.defaulted(camera_id=f"{preset}0", preset=preset,
                                aircraft="B747", **kwargs)


# -- determinism ---------------------------------------------------------

def test_pose_track_is_bit_identical_across_invocations():
    columns = make_columns(roll=lambda t: 25.0 * math.sin(0.4 * t),
                           heading=lambda t: (5.0 * t) % 360.0)
    for preset in ("chase", "ground", "wingman", "tower", "cockpit"):
        a = solve_pose_track(columns, camera_for(preset), FRAME)
        b = solve_pose_track(columns, camera_for(preset), FRAME)
        assert a.digest() == b.digest(), preset
        assert a.north_m == b.north_m and a.quat == b.quat


# -- the §1.5 rule: only the cockpit preset inherits roll ---------------

def test_only_cockpit_inherits_roll():
    """Drive a rolling track: the four horizon-stable presets keep
    camera roll at exactly zero; the cockpit camera's roll IS the
    aircraft's, by declaration. A preset ported with the full rotation
    in the offset frame would fail the altitude check below too."""
    roll = lambda t: 30.0 * math.sin(0.5 * t)
    columns = make_columns(roll=roll)
    for preset in ("chase", "ground", "wingman", "tower"):
        track = solve_pose_track(columns, camera_for(preset), FRAME)
        assert all(r == 0.0 for r in track.roll_deg), preset
        assert track.horizon_stable
    cockpit = solve_pose_track(columns, camera_for("cockpit"), FRAME)
    assert not cockpit.horizon_stable
    for i, t in enumerate(columns["t"]):
        assert cockpit.roll_deg[i] == pytest.approx(roll(t))


def test_chase_offset_lives_in_the_heading_only_frame():
    """Pitch the aircraft hard: the chase offset must NOT tilt with it
    (heading-only frame -- yaw applied, pitch and roll discarded). A
    wrong port through the full rotation moves the camera's altitude
    by offset_forward * sin(pitch) ~ 28 m and fails loudly here."""
    columns = make_columns(pitch=lambda t: 15.0)
    camera = camera_for("chase")
    track = solve_pose_track(columns, camera, FRAME)
    up = float(camera.offset_up_m.value)
    for i in range(len(track)):
        assert track.alt_m[i] == pytest.approx(
            columns["altitude_m"][i] + up, abs=1e-9)


def test_cockpit_is_body_fixed():
    """The shoulder camera rides the airframe: pitch rotates its offset
    (unlike the chase), and position tracks the aircraft unsmoothed."""
    columns = make_columns(pitch=lambda t: 10.0)
    camera = camera_for("cockpit")
    track = solve_pose_track(columns, camera, FRAME)
    forward, right, up = (float(camera.offset_forward_m.value),
                          float(camera.offset_right_m.value),
                          float(camera.offset_up_m.value))
    p = math.radians(10.0)
    # Body->NED at heading 0, roll 0: up_component = -(-sin p * fwd
    # + cos p * (-up)) = fwd * sin p + up * cos p.
    expected_up = forward * math.sin(p) + up * math.cos(p)
    for i in range(0, len(track), 40):
        assert track.alt_m[i] - columns["altitude_m"][i] == pytest.approx(
            expected_up, abs=1e-9)


# -- smoothing: the C++ time constants on the telemetry clock -----------

def test_wingman_station_keeping_is_tighter_than_chase():
    """After a heading step the wingman (half the position time
    constant) closes on its goal faster than the chase."""
    columns = make_columns(heading=lambda t: 0.0 if t < 10.0 else 90.0)
    i = columns["t"].index(10.5)

    def goal_error(preset):
        camera = camera_for(preset)
        track = solve_pose_track(columns, camera, FRAME)
        yaw = math.radians(columns["heading_deg"][i])
        f, r, u = (float(camera.offset_forward_m.value),
                   float(camera.offset_right_m.value),
                   float(camera.offset_up_m.value))
        goal_n = (f * math.cos(yaw) - r * math.sin(yaw))
        goal_e = (f * math.sin(yaw) + r * math.cos(yaw))
        air_n, air_e = FRAME.to_local(columns["lat_deg"][i],
                                      columns["lon_deg"][i])
        return math.hypot(track.north_m[i] - (air_n + goal_n),
                          track.east_m[i] - (air_e + goal_e))

    # Normalise by the offset magnitude so the comparison is about the
    # filter, not the different formation geometry.
    chase = goal_error("chase") / 110.0
    wingman = goal_error("wingman") / 185.0
    assert wingman < chase


def test_ground_observer_never_moves():
    columns = make_columns(roll=lambda t: 20.0 * math.sin(t))
    track = solve_pose_track(columns, camera_for("ground"), FRAME)
    assert len(set(track.north_m)) == 1
    assert len(set(track.east_m)) == 1
    assert len(set(track.alt_m)) == 1
    # ...but the aim follows the aircraft: yaw changes as it flies past.
    assert len(set(track.yaw_deg)) > 1


# -- keyframed moves: continuous solution, sampled ----------------------

def explicit_camera_with_moves():
    camera = CameraSpec.defaulted(camera_id="dolly", preset="explicit")
    camera.set("position_mode", "scene", frm="stated")
    camera.set("position_north_m", 0.0, frm="stated")
    camera.set("position_east_m", -500.0, frm="stated")
    camera.set("position_alt_m", 1200.0, frm="stated")
    camera.set("aim_mode", "point", frm="stated")
    camera.set("aim_north_m", 1000.0, frm="stated")
    camera.set("aim_alt_m", 1000.0, frm="stated")
    camera.moves = [
        {"t_s": 0.0, "position_north_m": 0.0, "focal_length_mm": 35.0},
        {"t_s": 10.0, "position_north_m": 2000.0,
         "focal_length_mm": 85.0},
    ]
    return camera


def test_keyframes_interpolate_linearly_and_hold_ends():
    columns = make_columns(duration_s=15.0)
    track = solve_pose_track(columns, explicit_camera_with_moves(), FRAME)
    i5 = columns["t"].index(5.0)
    i12 = columns["t"].index(12.0)
    assert track.north_m[i5] == pytest.approx(1000.0)
    assert track.focal_length_mm[i5] == pytest.approx(60.0)
    assert track.north_m[i12] == pytest.approx(2000.0)   # held after last
    assert track.focal_length_mm[0] == pytest.approx(35.0)


def test_keyframes_agree_across_telemetry_rates():
    """The moves are a continuous solution; a different sample rate
    merely samples it. Shared sample times must agree exactly."""
    camera = explicit_camera_with_moves()
    coarse = make_columns(duration_s=15.0, dt=0.1)
    fine = make_columns(duration_s=15.0, dt=0.05)
    track_c = solve_pose_track(coarse, camera, FRAME)
    track_f = solve_pose_track(fine, camera, FRAME)
    for i, t in enumerate(coarse["t"]):
        j = fine["t"].index(t)
        assert track_c.north_m[i] == track_f.north_m[j]
        assert track_c.focal_length_mm[i] == track_f.focal_length_mm[j]
        assert track_c.quat[i] == track_f.quat[j]


def test_bearing_aim_slerps_between_keyframes():
    camera = CameraSpec.defaulted(camera_id="pan", preset="explicit")
    camera.set("position_mode", "scene", frm="stated")
    camera.set("aim_mode", "bearing", frm="stated")
    camera.moves = [{"t_s": 0.0, "aim_bearing_deg": 0.0},
                    {"t_s": 10.0, "aim_bearing_deg": 90.0}]
    columns = make_columns(duration_s=10.0)
    track = solve_pose_track(columns, camera, FRAME)
    i5 = columns["t"].index(5.0)
    assert track.yaw_deg[i5] == pytest.approx(45.0, abs=1e-6)
    assert track.roll_deg[i5] == 0.0


# -- refusals ------------------------------------------------------------

def test_missing_channel_refuses_by_name():
    columns = make_columns()
    del columns["heading_deg"]
    with pytest.raises(PoseSolveError, match="camera.poses"):
        solve_pose_track(columns, camera_for("chase"), FRAME)


def test_offset_mode_on_a_world_anchored_preset_refuses():
    camera = camera_for("ground")
    camera.set("position_mode", "offset", frm="nonsense")
    with pytest.raises(PoseSolveError, match="position_mode"):
        solve_pose_track(make_columns(), camera, FRAME)


# -- the shared aircraft projection -------------------------------------

def test_aircraft_local_track_matches_the_frame():
    columns = make_columns(duration_s=1.0)
    track = aircraft_local_track(columns, FRAME)
    assert track[0]["north_m"] == pytest.approx(0.0, abs=1e-6)
    # ~100 m north through the projection (the UTM scale factor at the
    # frame's longitude is < 1, so slightly under).
    assert track[-1]["north_m"] == pytest.approx(100.0, rel=0.01)


def test_quaternion_matches_euler():
    q = euler_to_quat(0.0, 0.0, 90.0)
    assert q[0] == pytest.approx(math.cos(math.radians(45.0)))
    assert q[3] == pytest.approx(math.sin(math.radians(45.0)))
