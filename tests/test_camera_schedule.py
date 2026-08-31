"""Camera Phase 1, package C: capture scheduling.

The schedule is a pure function of the telemetry record and the camera
spec -- rendering never enters it -- and a requested count is a
contract: exactly that many captures, or a named camera.schedule
refusal before anything runs.
"""

import pytest

from core.capture.schedule import ScheduleError, solve_schedule
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


def camera(**fields):
    cam = CameraSpec.defaulted(camera_id="cam", preset="chase",
                               aircraft="B747")
    for name, value in fields.items():
        cam.set(name, value, frm="test")
    return cam


# -- interval: exact counts ---------------------------------------------

def test_exact_count_is_exact_endpoints_included():
    columns = make_columns(duration_s=20.0)          # 201 samples
    schedule = solve_schedule(columns, camera(capture_count=50))
    assert len(schedule) == 50
    assert schedule.indices[0] == 0
    assert schedule.indices[-1] == len(columns["t"]) - 1
    assert len(set(schedule.indices)) == 50

    for count in (1, 2, 3, 201):
        assert len(solve_schedule(columns,
                                  camera(capture_count=count))) == count


def test_unreachable_count_refuses_by_name():
    columns = make_columns(duration_s=2.0)           # 21 samples
    with pytest.raises(ScheduleError, match="camera.schedule"):
        solve_schedule(columns, camera(capture_count=22))


def test_negative_count_refuses():
    with pytest.raises(ScheduleError, match="negative capture count"):
        solve_schedule(make_columns(), camera(capture_count=-3))


def test_period_snaps_to_the_sample_clock():
    columns = make_columns(duration_s=10.0)
    schedule = solve_schedule(columns, camera(period_s=1.0))
    assert list(schedule.times) == pytest.approx(
        [float(k) for k in range(11)])
    with pytest.raises(ScheduleError, match="non-positive period"):
        solve_schedule(columns, camera(period_s=0.0))


# -- schedules never see rendering --------------------------------------

def test_schedule_is_a_pure_function_of_telemetry():
    columns = make_columns(duration_s=20.0)
    a = solve_schedule(columns, camera(capture_count=10))
    b = solve_schedule({k: list(v) for k, v in columns.items()},
                       camera(capture_count=10))
    assert a == b


# -- distance (waypoint) trigger ----------------------------------------

def _expected_waypoint_captures(columns, spacing):
    """Independent recomputation: 1 (the start) + one per full spacing
    of PROJECTED track length (the UTM scale factor at the frame's
    longitude makes the projected track slightly shorter than the
    great-circle one -- the schedule works in scene metres, so the
    check must too)."""
    track = [FRAME.to_local(a, b) for a, b in
             zip(columns["lat_deg"], columns["lon_deg"])]
    travelled = sum(
        ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        for a, b in zip(track, track[1:]))
    return 1 + int(travelled // spacing)


def test_distance_trigger_marks_the_flown_track():
    # 100 m/s northbound for 30 s ~ 3 km: the start + one per 500 m.
    columns = make_columns(duration_s=30.0)
    schedule = solve_schedule(columns, camera(trigger="distance",
                                              distance_m=500.0),
                              frame=FRAME)
    expected = _expected_waypoint_captures(columns, 500.0)
    assert expected >= 6
    assert len(schedule) == expected
    assert schedule.indices[0] == 0
    with pytest.raises(ScheduleError, match="non-positive waypoint"):
        solve_schedule(columns, camera(trigger="distance",
                                       distance_m=0.0), frame=FRAME)


def test_distance_count_contract_refuses_when_missed():
    columns = make_columns(duration_s=30.0)
    expected = _expected_waypoint_captures(columns, 500.0)
    with pytest.raises(ScheduleError, match="count contract"):
        solve_schedule(columns, camera(trigger="distance",
                                       distance_m=500.0,
                                       capture_count=expected + 5),
                       frame=FRAME)
    exact = solve_schedule(columns, camera(trigger="distance",
                                           distance_m=500.0,
                                           capture_count=expected),
                           frame=FRAME)
    assert len(exact) == expected


# -- proximity trigger ---------------------------------------------------

def test_proximity_fires_once_inside_the_radius():
    columns = make_columns(duration_s=30.0)
    schedule = solve_schedule(
        columns, camera(trigger="proximity", distance_m=100.0,
                        aim_north_m=1500.0, aim_east_m=0.0,
                        refractory_s=5.0), frame=FRAME)
    assert len(schedule) == 1
    assert 14.0 <= schedule.times[0] <= 16.1


def test_proximity_outside_the_window_refuses():
    columns = make_columns(duration_s=10.0)
    with pytest.raises(ScheduleError, match="never comes within"):
        solve_schedule(columns, camera(trigger="proximity",
                                       distance_m=50.0,
                                       aim_north_m=100000.0),
                       frame=FRAME)


# -- event trigger and the refractory period ----------------------------

def bursty_roll(t):
    if 10.0 <= t <= 12.0 or 20.0 <= t <= 21.0:
        return 40.0
    return 0.0


def test_rising_event_is_one_capture_per_crossing():
    columns = make_columns(duration_s=30.0, roll=bursty_roll)
    schedule = solve_schedule(columns, camera(trigger="event",
                                              event_channel="roll_deg",
                                              event_threshold=30.0,
                                              event_direction="rising"))
    assert len(schedule) == 2
    assert schedule.times[0] == pytest.approx(10.0)
    assert schedule.times[1] == pytest.approx(20.0)


def test_refractory_collapses_a_held_exceedance():
    columns = make_columns(duration_s=30.0, roll=bursty_roll)
    held = solve_schedule(columns, camera(trigger="event",
                                          event_channel="roll_deg",
                                          event_threshold=30.0,
                                          event_direction="above",
                                          refractory_s=2.0))
    # 2 s exceedance + 1 s exceedance with a 2 s refractory: 10.0, 12.0
    # (the sample AT 12.0 still reads 40), then 20.0 -- never one
    # capture per 0.1 s telemetry sample.
    assert list(held.times) == pytest.approx([10.0, 12.0, 20.0])
    burst = solve_schedule(columns, camera(trigger="event",
                                           event_channel="roll_deg",
                                           event_threshold=30.0,
                                           event_direction="above",
                                           refractory_s=0.0))
    assert len(burst) == 32          # every exceeding sample: the burst


def test_event_that_never_fires_refuses():
    columns = make_columns(duration_s=10.0)
    with pytest.raises(ScheduleError, match="fires zero|never goes"):
        solve_schedule(columns, camera(trigger="event",
                                       event_channel="roll_deg",
                                       event_threshold=30.0,
                                       event_direction="rising"))


def test_event_on_a_missing_channel_refuses():
    columns = make_columns(duration_s=10.0)
    with pytest.raises(ScheduleError, match="does not carry"):
        solve_schedule(columns, camera(trigger="event",
                                       event_channel="n_z",
                                       event_threshold=2.0,
                                       event_direction="above"))


def test_unknown_trigger_refuses():
    with pytest.raises(ScheduleError, match="unknown trigger"):
        solve_schedule(make_columns(), camera(trigger="sometimes"))
