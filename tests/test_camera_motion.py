"""camera-motion-layer: the dense pose clock and the seeded motion layer.

Profile none must leave every existing track (and so every digest)
byte-identical; the noise is a pure function of continuous t; the
roll bound holds; the second-order lag is exact; resampling reproduces
the original samples at the original times.
"""

import json
import math

import pytest

from core.capture import camera_motion as cm
from core.capture.poses import SceneFrame, euler_to_quat, solve_pose_track
from core.scenario.camera import CameraSpec

FRAME = SceneFrame("EPSG:32631", 0.0, 0.0, declared=True)


def make_columns(duration_s=20.0, dt=0.1, speed_mps=100.0):
    """A northbound flight with a gentle turn, on the recorder's clock."""
    n = int(round(duration_s / dt)) + 1
    mpd = 111_320.0
    cols = {k: [] for k in ("t", "lat_deg", "lon_deg", "altitude_m",
                            "roll_deg", "pitch_deg", "heading_deg")}
    north = east = 0.0
    for i in range(n):
        t = i * dt
        heading = 10.0 * math.sin(t / 6.0)
        if i:
            north += speed_mps * dt * math.cos(math.radians(heading))
            east += speed_mps * dt * math.sin(math.radians(heading))
        cols["t"].append(t)
        cols["lat_deg"].append(north / mpd)
        cols["lon_deg"].append(3.0 + east / mpd)
        cols["altitude_m"].append(1000.0 + 5.0 * math.sin(t / 4.0))
        cols["roll_deg"].append(15.0 * math.cos(t / 6.0))
        cols["pitch_deg"].append(2.0)
        cols["heading_deg"].append(heading % 360.0)
    return cols


def camera(preset="chase", motion=None):
    cam = CameraSpec.defaulted(camera_id="cam0", preset=preset)
    cam.motion = motion
    return cam


# -- profile none: byte-identical ------------------------------------------

@pytest.mark.parametrize("preset", ["chase", "ground", "cockpit"])
def test_profile_none_returns_the_input_track_and_keeps_the_digest(preset):
    cols = make_columns()
    plain = solve_pose_track(cols, camera(preset), FRAME)
    with_clock = solve_pose_track(cols, camera(preset), FRAME, render_clock=(30, 4))
    stated_none = solve_pose_track(cols, camera(preset, {"profile": "none"}), FRAME,
                                   render_clock=(30, 1))
    assert with_clock.digest() == plain.digest() == stated_none.digest()
    assert type(with_clock).__name__ == "PoseTrack"
    track, record = cm.apply_motion(plain, None, (30, 8))
    assert track is plain and record == {"profile": "none"}
    # The card block is unchanged too: no camera_motion key, same poses.
    assert "motion" not in camera(preset).to_dict()


def test_absent_motion_round_trips_absent_and_a_stated_one_round_trips():
    cam = camera()
    assert CameraSpec.from_dict(cam.to_dict()).motion is None
    cam.motion = {"profile": "handheld", "seed": 3, "intensity": 0.5}
    back = CameraSpec.from_dict(json.loads(json.dumps(cam.to_dict())))
    assert back.motion == cam.motion


# -- noise ------------------------------------------------------------------

def test_rate_independence_30_and_240_hz():
    for axis in cm.ROTATION_AXES + cm.TRANSLATION_AXES:
        for profile in ("handheld", "camera_ship", "tripod_fluid_head"):
            for k in range(31):                     # 0 .. 1 s on the 30 Hz clock
                t30 = 5.0 + k / 30.0
                t240 = 5.0 + (8 * k) / 240.0
                a = cm.band_noise(t30, 7, "cam0", axis, profile, 1.0, 1.3)
                b = cm.band_noise(t240, 7, "cam0", axis, profile, 1.0, 1.3)
                assert abs(a - b) <= 1e-12


def test_apply_motion_agrees_across_clocks_where_they_share_a_t():
    """Handheld has no lag, so the applied pose at a shared t does not
    depend on the dense clock."""
    cols = make_columns(duration_s=6.0)
    motion = {"profile": "handheld", "seed": 11, "intensity": 1.0}
    a = solve_pose_track(cols, camera("chase", motion), FRAME, render_clock=(30, 1))
    b = solve_pose_track(cols, camera("chase", motion), FRAME, render_clock=(30, 8))
    da, db = a.dense, b.dense
    index_b = {round(t, 9): i for i, t in enumerate(db.t)}
    shared = 0
    for i, t in enumerate(da.t):
        j = index_b.get(round(t, 9))
        if j is None:
            continue
        shared += 1
        for name in ("north_m", "east_m", "alt_m", "pitch_deg", "roll_deg"):
            assert abs(getattr(da, name)[i] - getattr(db, name)[j]) <= 1e-9, name
        assert abs(((da.yaw_deg[i] - db.yaw_deg[j] + 180) % 360) - 180) <= 1e-9
    assert shared >= 150


def test_same_seed_same_output_different_seed_different_output():
    cols = make_columns(duration_s=4.0)
    base = solve_pose_track(cols, camera(), FRAME)
    a, _ = cm.apply_motion(base, {"profile": "camera_ship", "seed": 1}, (30, 1))
    b, _ = cm.apply_motion(base, {"profile": "camera_ship", "seed": 1}, (30, 1))
    c, _ = cm.apply_motion(base, {"profile": "camera_ship", "seed": 2}, (30, 1))
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()
    assert a.digest() != base.digest()


def test_roll_bound_holds_over_600_s():
    worst = 0.0
    for profile in ("handheld", "camera_ship", "tripod_fluid_head"):
        cols = make_columns(duration_s=600.0, dt=0.1)
        base = solve_pose_track(cols, camera(), FRAME)
        track, record = cm.apply_motion(
            base, {"profile": profile, "seed": 5, "intensity": cm.INTENSITY_MAX}, None)
        worst = max(worst, max(abs(r) for r in track.roll_deg))
        assert record["roll_bound_deg"] == cm.ROLL_BOUND_DEG
        assert track.horizon_stable
    assert worst <= cm.ROLL_BOUND_DEG
    # The tolerance a horizon check takes: exact zero for none.
    assert cm.horizon_roll_tolerance_deg({"profile": "none"}) == 0.0
    assert cm.horizon_roll_tolerance_deg(None) == 0.0
    assert cm.horizon_roll_tolerance_deg(record) == cm.ROLL_BOUND_DEG


def test_handheld_yaw_fft_peak_is_in_3_to_9_hz():
    import numpy as np

    rate, seconds = 100.0, 60.0
    t = np.arange(int(rate * seconds)) / rate
    for seed in range(5):
        y = np.array([cm.band_noise(v, seed, "cam0", "yaw", "handheld") for v in t])
        spectrum = np.abs(np.fft.rfft(y - y.mean()))
        freqs = np.fft.rfftfreq(len(y), 1.0 / rate)
        peak = freqs[int(np.argmax(spectrum[1:])) + 1]
        assert 3.0 <= peak <= 9.0, (seed, peak)
        rms = float(np.sqrt(np.mean(y * y)))
        assert 0.02 <= rms <= 0.05


def test_camera_ship_has_lines_at_the_stated_blade_pass():
    import numpy as np

    rate, seconds = 200.0, 40.0
    t = np.arange(int(rate * seconds)) / rate
    y = np.array([cm.band_noise(v, 0, "cam0", "pitch", "camera_ship",
                                airspeed_scale=0.25, blade_pass_hz=23.0) for v in t])
    spectrum = np.abs(np.fft.rfft(y))
    freqs = np.fft.rfftfreq(len(y), 1.0 / rate)
    peak = freqs[int(np.argmax(spectrum[1:])) + 1]
    assert abs(peak - 23.0) <= 23.0 * 0.01


# -- second-order lag --------------------------------------------------------

@pytest.mark.parametrize("zeta", [0.5, 0.7, 0.9])
def test_second_order_step_overshoot_matches_zeta(zeta):
    y, ydot, dt, peak = 0.0, 0.0, 1e-4, 0.0
    for _ in range(int(3.0 / dt)):
        y, ydot = cm.second_order_step(y, ydot, 1.0, 1.0, dt, zeta, 1.5)
        peak = max(peak, y)
    expected = math.exp(-math.pi * zeta / math.sqrt(1.0 - zeta * zeta))
    assert abs((peak - 1.0) - expected) <= 0.01 * expected


def test_second_order_step_is_exact_across_step_sizes():
    """A ramp input integrated in one step or in 1000 agrees: first-order
    hold is exact for a linear input."""
    one = cm.second_order_step(0.2, -0.1, 0.0, 2.0, 0.8, 0.7, 1.2)
    y, ydot = 0.2, -0.1
    for k in range(1000):
        y, ydot = cm.second_order_step(y, ydot, 2.0 * k / 1000, 2.0 * (k + 1) / 1000,
                                       0.8 / 1000, 0.7, 1.2)
    assert abs(y - one[0]) <= 1e-12 and abs(ydot - one[1]) <= 1e-11
    for zeta in (1.0, 1.4):        # critical and overdamped branches agree too
        one = cm.second_order_step(0.0, 0.0, 1.0, 1.0, 0.5, zeta, 1.0)
        y, ydot = 0.0, 0.0
        for _ in range(500):
            y, ydot = cm.second_order_step(y, ydot, 1.0, 1.0, 0.001, zeta, 1.0)
        assert abs(y - one[0]) <= 1e-12


# -- resampling ----------------------------------------------------------------

@pytest.mark.parametrize("preset", ["chase", "cockpit", "tower"])
def test_resample_reproduces_the_original_samples_at_original_times(preset):
    cols = make_columns(duration_s=5.0)
    base = solve_pose_track(cols, camera(preset), FRAME)
    same = cm.resample_track(base, base.t)
    assert same.digest() == base.digest()
    times, index = cm.dense_clock(base.t, (30, 4))
    dense = cm.resample_track(base, times)
    for i, j in enumerate(index):
        assert dense.t[j] == base.t[i]
        assert dense.north_m[j] == base.north_m[i]
        assert dense.quat[j] == base.quat[i]
    # Between samples: smooth and roll exactly zero on a horizon-stable preset.
    if base.horizon_stable:
        assert all(r == 0.0 for r in dense.roll_deg)
    assert len(dense) == len(times) > 10 * len(base)


def test_quat_to_euler_inverts_euler_to_quat():
    for roll, pitch, yaw in ((0.0, 3.0, 10.0), (20.0, -10.0, 350.0), (-45.0, 30.0, 180.0)):
        r, p, y = cm.quat_to_euler(euler_to_quat(roll, pitch, yaw))
        assert (r, p) == pytest.approx((roll, pitch), abs=1e-9)
        assert ((y - yaw + 180) % 360 - 180) == pytest.approx(0.0, abs=1e-9)


# -- the layer end to end --------------------------------------------------------

def test_motion_track_keeps_telemetry_indices_and_ships_the_dense_clock():
    cols = make_columns(duration_s=10.0)
    cam = camera("chase", {"profile": "camera_ship", "seed": 4, "intensity": 1.0})
    track = solve_pose_track(cols, cam, FRAME, render_clock=(30, 1))
    assert len(track) == len(cols["t"])          # schedule indices stay valid
    dense = track.dense
    times, index = cm.dense_clock(track.t, (30, 1))
    assert list(dense.t) == times
    for i, j in enumerate(index):                 # label pose == engine pose at t_i
        assert dense.yaw_deg[j] == track.yaw_deg[i]
        assert dense.alt_m[j] == track.alt_m[i]
    record = track.motion_record
    for key in ("profile", "seed", "intensity", "n_sinusoids", "rms_deg",
                "roll_bound_deg", "dense_clock_hz", "label_pose", "basis"):
        assert key in record
    assert record["dense_clock_hz"] == 30.0
    assert record["label_pose"] == "shutter-centre sample"
    assert record["basis"] == "pose track: beauty and labels share it"

    class Schedule:
        times = (1.0, 2.0)

    block = track.card_block(cam, Schedule, FRAME)
    assert block["camera_motion"] == record
    assert len(block["poses"]["t_s"]) == len(dense)
    assert block["spec"]["motion"]["profile"] == "camera_ship"


def test_card_pose_block_size_stays_well_inside_the_parser():
    """The commandlet reads the card with FFileHelper::LoadFileToString and
    FJsonSerializer, which carry no size cap below FString's int32 length;
    SetPoseTrack takes any length >= 2. Measured here: the web's longest
    clip on the densest clock the commandlet accepts (accumulate 64)."""
    cols = make_columns(duration_s=30.0)
    cam = camera("chase", {"profile": "handheld", "seed": 0})
    track = solve_pose_track(cols, cam, FRAME, render_clock=(30, 64))

    class Schedule:
        times = (1.0,)

    size = len(json.dumps(track.card_block(cam, Schedule, FRAME)["poses"]))
    # 30 s x 1920 Hz = 57,601 samples x 8 arrays: 8,241,919 bytes measured (2026-11-09).
    assert len(track.dense) == 57601
    assert size < 16 * 1024 * 1024
    assert size < 2 ** 31 - 1


def test_aim_lag_follows_and_stays_bounded():
    cols = make_columns(duration_s=20.0)
    base = solve_pose_track(cols, camera(), FRAME)
    lagged, _ = cm.apply_motion(base, {"profile": "camera_ship", "seed": 0, "intensity": 0.0},
                                (30, 1))
    err = max(abs(((a - b + 180) % 360) - 180) for a, b in zip(lagged.yaw_deg, base.yaw_deg))
    assert 0.0 < err < 2.0


def test_bad_blocks_refuse_by_name():
    base = solve_pose_track(make_columns(duration_s=2.0), camera(), FRAME)
    for bad in ({"profile": "earthquake"}, {"profile": "handheld", "seed": -1},
                {"profile": "handheld", "intensity": 9}, {"profile": "handheld", "wobble": 1},
                {"profile": "handheld", "blade_pass_hz": 20.0}):
        with pytest.raises(cm.CameraMotionError) as info:
            cm.apply_motion(base, bad, None)
        assert info.value.constraint == "camera.motion"


def test_cinematic_look_switch_maps_presets():
    look = {"switch": "cinematic", "camera_motion": "auto"}
    assert cm.look_motion(look, "chase")["profile"] == "camera_ship"
    assert cm.look_motion(look, "chase")["intensity"] == 1.0
    assert cm.look_motion(look, "cockpit") == {
        "profile": "handheld", "seed": 0, "intensity": 0.5, "source": "look switch cinematic"}
    assert cm.look_motion(look, "tower")["profile"] == "tripod_fluid_head"
    assert cm.look_motion({"switch": "beauty"}, "chase") is None
    assert cm.look_motion(None, "chase") is None

    class Spec:
        cameras = [camera("chase"), camera("cockpit", {"profile": "none"})]

    assert cm.apply_look_motion(Spec, look) == ["cam0"]
    assert Spec.cameras[1].motion == {"profile": "none"}   # stated, never moved
    from webapp import runs
    assert runs.LOOK_SWITCHES["cinematic"]["camera_motion"] == "auto"
    assert "camera_motion" not in runs.LOOK_SWITCHES["beauty"]
