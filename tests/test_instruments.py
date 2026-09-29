"""Instrument models (core/telemetry/instruments.py) and their independent
check (core/telemetry/instruments_check.py): measured channels beside truth.

Every statistic here is a relative tolerance on a second moment over a
long synthetic run (no chi-square); every determinism claim is a byte
comparison; the CLI claim is a real c172p capture.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from core.experiments.seeds import SUBSYSTEMS, derive, generator
from core.telemetry import instruments as I
from core.telemetry.instruments_check import (
    FAIL, NOT_RUN, PASS, SIGMA_FACTOR, check_instruments,
)

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"


# -- fixtures ------------------------------------------------------------

def synthetic_telemetry(n: int = 3000, dt: float = 0.1) -> dict:
    """A recorder-shaped dict: a slow turn with gentle altitude, speed and
    attitude motion, so every instrument sees a moving truth."""
    t = np.arange(n) * dt
    heading = (6.0 * t) % 360.0
    lat = 45.0 + 1.0e-4 * t
    lon = 8.0 + 1.5e-4 * t
    cols = {
        "t": t,
        "altitude_m": 1000.0 + 20.0 * np.sin(0.05 * t),
        "cas_kt": 100.0 + 5.0 * np.sin(0.1 * t),
        "heading_deg": heading,
        "pitch_deg": 2.0 + 1.0 * np.sin(0.3 * t),
        "roll_deg": 15.0 * np.sin(0.2 * t),
        "n_z": 1.0 + 0.1 * np.sin(0.4 * t),
        "pitch_rate_dps": 0.3 * np.cos(0.3 * t),
        "roll_rate_dps": 3.0 * np.cos(0.2 * t),
        "v_north_mps": 50.0 * np.cos(np.radians(heading)),
        "v_east_mps": 50.0 * np.sin(np.radians(heading)),
        "v_down_mps": -1.0 * np.cos(0.05 * t),
        "lat_deg": lat,
        "lon_deg": lon,
    }
    return {"provenance": {"synthetic": True}, "interval_s": dt, "samples": n,
            "events": [], "derived": [],
            "columns": {k: [float(v) for v in v_] for k, v_ in cols.items()}}


def write_run(directory: Path, telemetry: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "telemetry.json").write_text(json.dumps(telemetry, indent=1),
                                              encoding="utf-8")
    return directory


def quiet_profile(**overrides) -> I.InstrumentProfile:
    """The tactical profile with every noise term zeroed unless overridden:
    the deterministic parts (lever arm, hold, lag) in isolation."""
    data = json.loads((I.PROFILE_DIR / "tactical.json").read_text(encoding="utf-8"))
    for key in ("bias_repeatability_mg", "velocity_random_walk_mps_per_sqrt_h",
                "bias_instability_mg"):
        data["imu"]["accelerometer"][key] = 0.0
    for key in ("bias_repeatability_deg_per_h", "angle_random_walk_deg_per_sqrt_h",
                "bias_instability_deg_per_h"):
        data["imu"]["gyro"][key] = 0.0
    data["gps"].update({"north_east_sigma_m": 0.0, "vertical_sigma_m": 0.0,
                        "velocity_sigma_mps": 0.0})
    data["pitot_static"].update({"cas_sigma_kt": 0.0, "pressure_altitude_sigma_m": 0.0})
    data["magnetometer"].update({"hard_iron_sigma_fraction": 0.0, "heading_sigma_deg": 0.0})
    for dotted, value in overrides.items():
        block = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            block = block[part]
        block[parts[-1]] = value
    return I.profile_from_dict(data, name="tactical")


def column(result: I.MeasuredResult, name: str) -> np.ndarray:
    return np.asarray(result.data["columns"][name], dtype=float)


# -- the profiles ----------------------------------------------------------

def test_the_three_profiles_load_and_cite_their_sources():
    assert I.available_profiles() == ["consumer_mems", "ideal", "tactical"]
    for name in I.available_profiles():
        profile = I.load_profile(name)
        assert profile.name == name and profile.source.strip() and profile.references
        assert len(profile.sha256) == 64
        assert profile.path == f"assets/instrument_profiles/{name}.json"
        assert (name == "ideal") == profile.is_ideal
        assert all(ord(ch) < 128 for ch in json.dumps(profile.to_dict()))
    tactical = I.load_profile("tactical")
    assert tactical.gps["update_rate_hz"] == 5.0
    assert "unverified here" in tactical.source


@pytest.mark.parametrize("edit, fragment", [
    (lambda d: d.pop("source"), "no source"),
    (lambda d: d.update(references=[]), "no references"),
    (lambda d: d["gps"].update(north_east_sigma_m=-1.0), ">= 0"),
    (lambda d: d["magnetometer"].update(soft_iron=0.1), "does not model"),
    (lambda d: d["imu"].pop("gyro"), "no 'imu.gyro' block"),
    (lambda d: d["gps"].update(update_rate_hz=0.0), "update_rate_hz must be > 0"),
    (lambda d: d["gps"].update(antenna_offset_body_m=[1.0, 2.0]), "[x, y, z]"),
    (lambda d: d.update(name="other"), "names itself"),
])
def test_a_malformed_profile_refuses_by_name(edit, fragment):
    data = json.loads((I.PROFILE_DIR / "tactical.json").read_text(encoding="utf-8"))
    edit(data)
    with pytest.raises(I.InstrumentProfileError, match=re.escape(fragment)) as info:
        I.profile_from_dict(data, name="tactical")
    assert info.value.constraint == "instruments.profile"


def test_an_unknown_profile_refuses_by_name_and_lists_the_known_ones():
    with pytest.raises(I.InstrumentProfileError, match="consumer_mems, ideal, tactical"):
        I.load_profile("nope")


# -- the statistics against the profile (relative tolerance, no chi-square) ----

def test_synthetic_truth_statistics_match_the_tactical_profile():
    telemetry = synthetic_telemetry()
    profile = I.load_profile("tactical")
    result = I.measure(telemetry, profile, seed=11, source="user")
    dt = telemetry["interval_s"]
    n = telemetry["samples"]
    tol = 0.10                                   # 1/sqrt(2N) = 1.3 % sampling error

    # IMU: white sigma = density / 60 / sqrt(dt); the accelerometer channel
    # is in g, so its m/s^2 sigma is divided by g0.
    acc = profile.accelerometer
    sigma_acc = acc["velocity_random_walk_mps_per_sqrt_h"] / 60.0 / math.sqrt(dt) / I.G0
    resid = column(result, "n_z_meas") - column(result, "n_z")
    assert np.std(resid) == pytest.approx(sigma_acc, rel=tol)
    entry = next(e for e in result.data["channels"] if e["measured"] == "n_z_meas")
    # ... the constant bias is the drawn one, within the bias-instability
    # and sampling bounds, and the draw is a draw from the repeatability.
    assert abs(np.mean(resid) - entry["drawn_bias"]) < (
        acc["bias_instability_mg"] / 1000.0 + 4.0 * sigma_acc / math.sqrt(n))
    assert abs(entry["drawn_bias"]) < 4.0 * acc["bias_repeatability_mg"] / 1000.0
    gyro = profile.gyro
    sigma_gyro = gyro["angle_random_walk_deg_per_sqrt_h"] / 60.0 / math.sqrt(dt)
    for name in ("roll_rate_dps", "pitch_rate_dps"):
        resid = column(result, f"{name}_meas") - column(result, name)
        assert np.std(resid) == pytest.approx(sigma_gyro, rel=tol)

    # GPS at the fix samples: per-axis sigma after the lever arm.
    fix = column(result, "gps_fix").astype(int)
    at = np.flatnonzero(fix)
    assert at.size == int(math.floor((n - 1) * dt * profile.gps["update_rate_hz"] + 1e-9)) + 1
    cols = telemetry["columns"]
    lever = np.array([I.body_to_ned(cols["roll_deg"][i], cols["pitch_deg"][i],
                                    cols["heading_deg"][i]) @ np.array(
        profile.gps["antenna_offset_body_m"]) for i in at])
    lat = column(result, "lat_deg")[at]
    r_m = np.array([I.radii_of_curvature(v)[0] for v in lat])
    r_n = np.array([I.radii_of_curvature(v)[1] for v in lat])
    north = np.radians(column(result, "lat_deg_meas")[at] - lat) * r_m - lever[:, 0]
    east = (np.radians(column(result, "lon_deg_meas")[at] - column(result, "lon_deg")[at])
            * r_n * np.cos(np.radians(lat)) - lever[:, 1])
    down = (column(result, "altitude_m")[at] - column(result, "altitude_m_gps_meas")[at]
            - lever[:, 2])
    assert np.std(north) == pytest.approx(profile.gps["north_east_sigma_m"], rel=tol)
    assert np.std(east) == pytest.approx(profile.gps["north_east_sigma_m"], rel=tol)
    assert np.std(down) == pytest.approx(profile.gps["vertical_sigma_m"], rel=tol)
    for name in ("v_north_mps", "v_east_mps", "v_down_mps"):
        resid = column(result, f"{name}_meas")[at] - column(result, name)[at]
        assert np.std(resid) == pytest.approx(profile.gps["velocity_sigma_mps"], rel=tol)

    # Pitot-static: white sigma about the lagged truth.
    ps = profile.pitot_static
    lagged = I.first_order_lag(column(result, "cas_kt"), ps["cas_lag_s"], dt)
    assert np.std(column(result, "cas_kt_meas") - lagged) == pytest.approx(
        ps["cas_sigma_kt"], rel=tol)
    lagged = I.first_order_lag(column(result, "altitude_m"), ps["pressure_altitude_lag_s"], dt)
    assert np.std(column(result, "altitude_m_baro_meas") - lagged) == pytest.approx(
        ps["pressure_altitude_sigma_m"], rel=tol)

    # Magnetometer: white sigma about the hard-iron-biased heading.
    bx, by = result.data["draws"]["magnetometer"]["hard_iron_fraction"]
    biased = I.hard_iron_heading(column(result, "heading_deg"), bx, by)
    resid = (column(result, "heading_deg_meas") - biased + 180.0) % 360.0 - 180.0
    assert np.std(resid) == pytest.approx(profile.magnetometer["heading_sigma_deg"], rel=tol)
    assert 0.0 < math.hypot(bx, by) < 4.0 * profile.magnetometer["hard_iron_sigma_fraction"]

    # The null test measured a trace; the record names the columns.
    record = result.record
    assert record.name == "instruments.profile" and record.value == "tactical"
    assert record.source == "user" and record.model_name == I.MODEL
    assert record.null_test.ok and record.null_test.without_value == 0.0
    assert set(record.telemetry_columns) == {e["measured"] for e in result.data["channels"]}
    assert record.frame_keys == () and record.properties_written == ()
    assert set(result.data["absent"]) == {"n_x", "n_y", "yaw_rate_dps"}


def test_a_recorded_x_channel_is_measured_and_its_absence_moves_no_other_draw():
    """The draws for n_x, n_y and yaw_rate_dps are made whether or not the
    recording has them, so adding a channel changes nothing else."""
    telemetry = synthetic_telemetry(n=200)
    without = I.measure(telemetry, I.load_profile("tactical"), seed=3)
    with_x = copy.deepcopy(telemetry)
    with_x["columns"]["n_x"] = [0.05] * 200
    with_x["columns"]["yaw_rate_dps"] = [6.0] * 200
    added = I.measure(with_x, I.load_profile("tactical"), seed=3)
    assert "n_x_meas" in added.measured_columns and "yaw_rate_dps_meas" in added.measured_columns
    assert "n_x_meas" not in without.measured_columns
    assert set(added.data["absent"]) == {"n_y"}
    for name in without.measured_columns:
        assert added.data["columns"][name] == without.data["columns"][name]


# -- the ideal profile writes nothing -------------------------------------------

def test_the_ideal_profile_writes_nothing_and_says_so(tmp_path):
    run = write_run(tmp_path / "run", synthetic_telemetry(n=100))
    result = I.measure_run(run, "ideal", seed=0, source="default")
    assert result.data is None and result.measured_columns == []
    assert not (run / I.MEASURED_FILE).exists()
    assert I.write_measured(result, run) is None
    line = I.describe(result)
    assert line.startswith("instruments: ideal") and "no telemetry_measured.json written" in line
    # Its record is still a record: source default, a null test that
    # measured nothing (0 vs 0) and therefore is NOT ok.
    assert result.record.source == "default" and result.record.value == "ideal"
    assert result.record.null_test.with_value == 0.0 and not result.record.null_test.ok
    assert result.record.parameters["file"] is None
    assert check_instruments(run).status == NOT_RUN


# -- determinism ---------------------------------------------------------------

def test_the_same_seed_and_profile_give_a_byte_identical_file(tmp_path):
    telemetry = synthetic_telemetry(n=400)
    a = write_run(tmp_path / "a", telemetry)
    b = write_run(tmp_path / "b", telemetry)
    I.measure_run(a, "consumer_mems", seed=42)
    I.measure_run(b, "consumer_mems", seed=42)
    assert (a / I.MEASURED_FILE).read_bytes() == (b / I.MEASURED_FILE).read_bytes()
    assert (a / I.MEASURED_FILE).read_bytes().isascii()
    c = write_run(tmp_path / "c", telemetry)
    I.measure_run(c, "consumer_mems", seed=43)
    assert (a / I.MEASURED_FILE).read_bytes() != (c / I.MEASURED_FILE).read_bytes()
    d = write_run(tmp_path / "d", telemetry)
    I.measure_run(d, "tactical", seed=42)
    assert (a / I.MEASURED_FILE).read_bytes() != (d / I.MEASURED_FILE).read_bytes()


def test_every_instrument_draws_from_its_own_named_stream():
    """The seed streams are the four named subsystems, derived from the
    run seed; the IMU's first draw is the accelerometer x bias, so a
    model that borrowed another stream would record a different bias."""
    for name in I.STREAMS:
        assert name in SUBSYSTEMS
    seed = 2024
    telemetry = synthetic_telemetry(n=100)
    result = I.measure(telemetry, I.load_profile("tactical"), seed=seed)
    seeds = derive(seed, 0)
    assert result.data["seeds"]["streams"] == {s: seeds.for_subsystem(s) for s in I.STREAMS}
    assert len(set(result.data["seeds"]["streams"].values())) == 4
    profile = I.load_profile("tactical")
    expected_bias = (generator(seed, "imu", 0).standard_normal(3)
                     * profile.accelerometer["bias_repeatability_mg"] / 1000.0)
    assert result.data["draws"]["imu"]["accelerometer_bias"] == pytest.approx(
        list(expected_bias), rel=1e-12)
    expected_hard_iron = (generator(seed, "magnetometer", 0).standard_normal(2)
                          * profile.magnetometer["hard_iron_sigma_fraction"])
    assert result.data["draws"]["magnetometer"]["hard_iron_fraction"] == pytest.approx(
        list(expected_hard_iron), rel=1e-12)


# -- the deterministic parts in isolation ------------------------------------------

def rotate_by_hand(arm, roll_deg, pitch_deg, yaw_deg):
    """Rx(phi), then Ry(theta), then Rz(psi), one axis at a time -- a second
    derivation of body -> NED, not the module's matrix."""
    phi, theta, psi = map(math.radians, (roll_deg, pitch_deg, yaw_deg))
    x, y, z = arm
    y, z = math.cos(phi) * y - math.sin(phi) * z, math.sin(phi) * y + math.cos(phi) * z
    x, z = math.cos(theta) * x + math.sin(theta) * z, -math.sin(theta) * x + math.cos(theta) * z
    x, y = math.cos(psi) * x - math.sin(psi) * y, math.sin(psi) * x + math.cos(psi) * y
    return x, y, z


def lever_arm_measured(telemetry, arm, roll, pitch, heading):
    n = telemetry["samples"]
    cols = telemetry["columns"]
    cols["roll_deg"], cols["pitch_deg"], cols["heading_deg"] = [roll] * n, [pitch] * n, [heading] * n
    profile = quiet_profile(**{"gps.antenna_offset_body_m": list(arm),
                               "gps.update_rate_hz": 10.0})
    result = I.measure(telemetry, profile, seed=0)
    at = np.flatnonzero(column(result, "gps_fix"))
    lat = column(result, "lat_deg")[at]
    r_m = np.array([I.radii_of_curvature(v)[0] for v in lat])
    r_n = np.array([I.radii_of_curvature(v)[1] for v in lat])
    north = np.radians(column(result, "lat_deg_meas")[at] - lat) * r_m
    east = (np.radians(column(result, "lon_deg_meas")[at] - column(result, "lon_deg")[at])
            * r_n * np.cos(np.radians(lat)))
    up = column(result, "altitude_m_gps_meas")[at] - column(result, "altitude_m")[at]
    return result, at, north, east, up


def test_the_lever_arm_is_the_antenna_offset_rotated_by_the_attitude():
    """roll 30, pitch 0, heading 90 with an arm of (2, 0, -1) m puts the
    antenna 0.5 m south, 2 m east and 0.866 m above the CG (worked by hand
    from Rz(psi) Ry(theta) Rx(phi)); a general attitude matches an
    axis-by-axis rotation written out in this test."""
    result, at, north, east, up = lever_arm_measured(
        synthetic_telemetry(n=50), (2.0, 0.0, -1.0), 30.0, 0.0, 90.0)
    assert north == pytest.approx(-0.5, abs=1e-6)
    assert east == pytest.approx(2.0, abs=1e-6)
    assert up == pytest.approx(math.sqrt(3) / 2, abs=1e-9)
    # Velocity carries no lever-arm term (stated), so it is exact here.
    assert column(result, "v_north_mps_meas")[at] == pytest.approx(
        column(result, "v_north_mps")[at], abs=0.0)
    arm = (2.0, 0.5, -1.0)
    _, _, north, east, up = lever_arm_measured(synthetic_telemetry(n=50), arm, 30.0, 10.0, 60.0)
    n_hand, e_hand, d_hand = rotate_by_hand(arm, 30.0, 10.0, 60.0)
    assert north == pytest.approx(n_hand, abs=1e-6)
    assert east == pytest.approx(e_hand, abs=1e-6)
    assert up == pytest.approx(-d_hand, abs=1e-9)


def test_the_gps_holds_the_last_fix_between_fixes():
    """5 Hz fixes at a 10 Hz recorder: every second sample repeats the
    previous one exactly, the fix count is duration x rate + 1, and a fix
    sample moves with the truth."""
    telemetry = synthetic_telemetry(n=300)
    result = I.measure(telemetry, quiet_profile(), seed=0)
    fix = column(result, "gps_fix").astype(int)
    assert fix[0] == 1 and fix.sum() == 150
    assert list(fix[:6]) == [1, 0, 1, 0, 1, 0]
    for name in ("lat_deg_meas", "lon_deg_meas", "altitude_m_gps_meas",
                 "v_north_mps_meas", "v_east_mps_meas", "v_down_mps_meas"):
        meas = column(result, name)
        held = np.flatnonzero(fix == 0)
        assert np.array_equal(meas[held], meas[held - 1])
    v = column(result, "v_north_mps_meas")
    truth = column(result, "v_north_mps")
    at = np.flatnonzero(fix)
    assert v[at] == pytest.approx(truth[at], abs=0.0)      # no noise, no arm
    assert not np.array_equal(v[1:], truth[1:])              # the hold lags the truth
    assert I.gps_fix_mask(np.array([0.0, 0.1, 0.2, 5.0, 5.1]), 5.0).tolist() == [1, 0, 1, 1, 0]


def test_the_pitot_static_lag_is_the_stated_backward_euler_filter():
    telemetry = synthetic_telemetry(n=60)
    cols = telemetry["columns"]
    cols["cas_kt"] = [100.0] * 10 + [110.0] * 50          # a 10 kt step at t = 1 s
    profile = quiet_profile(**{"pitot_static.cas_lag_s": 0.4})
    result = I.measure(telemetry, profile, seed=0)
    meas = column(result, "cas_kt_meas")
    alpha = 0.1 / (0.4 + 0.1)
    expected = 100.0 + 10.0 * (1.0 - (1.0 - alpha) ** np.arange(1, 51))
    assert meas[:10] == pytest.approx(100.0, abs=0.0)
    assert meas[10:] == pytest.approx(expected, abs=1e-9)
    assert meas[-1] < 110.0 and meas[-1] > 109.9


def test_the_magnetometer_hard_iron_bends_the_heading_by_its_offset():
    """A hard-iron offset of +0.1 along body x makes a heading of 90 read
    atan2(1, 0.1) = 84.29 deg; 0 and 180 are untouched."""
    heading = np.array([0.0, 90.0, 180.0, 270.0])
    bent = I.hard_iron_heading(heading, 0.1, 0.0)
    assert bent == pytest.approx([0.0, math.degrees(math.atan2(1.0, 0.1)), 180.0,
                                  360.0 - math.degrees(math.atan2(1.0, 0.1))], abs=1e-9)


# -- the independent check ----------------------------------------------------------

@pytest.fixture
def graded_run(tmp_path):
    run = write_run(tmp_path / "run", synthetic_telemetry(n=600))
    I.measure_run(run, "tactical", seed=7)
    return run


def rewrite_measured(run: Path, edit) -> None:
    data = json.loads((run / I.MEASURED_FILE).read_text(encoding="utf-8"))
    edit(data)
    (run / I.MEASURED_FILE).write_bytes(I.serialise(data))


def test_the_check_passes_on_the_models_own_output(graded_run):
    result = check_instruments(graded_run)
    assert result.status == PASS and result.failure is None
    assert "12 measured channels" in result.detail and "GPS hold exact" in result.detail


def scaled_noise_run(tmp_path: Path, factor: float) -> Path:
    """A file that CLAIMS the tactical profile but whose every noise term
    was scaled by ``factor`` (the model run with a scaled profile, the
    profile block then put back)."""
    run = write_run(tmp_path / f"scaled_{factor}", synthetic_telemetry(n=600))
    data = json.loads((I.PROFILE_DIR / "tactical.json").read_text(encoding="utf-8"))
    data["imu"]["accelerometer"]["velocity_random_walk_mps_per_sqrt_h"] *= factor
    data["imu"]["gyro"]["angle_random_walk_deg_per_sqrt_h"] *= factor
    for key in ("north_east_sigma_m", "vertical_sigma_m", "velocity_sigma_mps"):
        data["gps"][key] *= factor
    for key in ("cas_sigma_kt", "pressure_altitude_sigma_m"):
        data["pitot_static"][key] *= factor
    data["magnetometer"]["heading_sigma_deg"] *= factor
    scaled = I.profile_from_dict(data, name="tactical")
    telemetry = json.loads((run / "telemetry.json").read_text(encoding="utf-8"))
    result = I.measure(telemetry, scaled, seed=7)
    result.data["profile"] = I.load_profile("tactical").to_dict()
    I.write_measured(result, run)
    return run


def test_the_check_fails_a_file_whose_noise_was_doubled(tmp_path):
    result = check_instruments(scaled_noise_run(tmp_path, 2.0))
    assert result.status == FAIL and result.failure == "instruments.residual"
    ratios = [float(m) for m in re.findall(r"is ([0-9.]+) x the", result.detail)]
    assert ratios and all(1.7 < r < 2.3 for r in ratios)   # measured 1.85..2.05
    assert 2.0 > SIGMA_FACTOR                       # the band the doubled file falls outside


def test_the_check_fails_a_file_whose_noise_was_halved(tmp_path):
    result = check_instruments(scaled_noise_run(tmp_path, 0.5))
    assert result.status == FAIL and result.failure == "instruments.residual"


def test_the_check_fails_a_broken_hold_and_a_bent_lever_arm(graded_run):
    rewrite_measured(graded_run, lambda d: d["columns"].__setitem__(
        "v_north_mps_meas", d["columns"]["v_north_mps"]))      # no hold at all
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.residual"
    assert "held sample" in result.detail


def test_the_check_fails_when_the_truth_beside_the_measurement_is_not_the_recorders(graded_run):
    truth = json.loads((graded_run / "telemetry.json").read_text(encoding="utf-8"))
    truth["columns"]["cas_kt"][0] += 1.0
    (graded_run / "telemetry.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.truth"
    # ... and with the hash put right, a truth column that differs still fails.
    rewrite_measured(graded_run, lambda d: d.__setitem__(
        "truth_sha256", hashlib.sha256((graded_run / "telemetry.json").read_bytes()).hexdigest()))
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.truth"
    assert "cas_kt" in result.detail


def test_the_check_fails_a_missing_record_and_a_foreign_version(graded_run):
    rewrite_measured(graded_run, lambda d: d["applied_variables"]["applied_variables"][0]
                     ["null_test"].__setitem__("ok", False))
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.record"
    rewrite_measured(graded_run, lambda d: d["applied_variables"]["applied_variables"].clear())
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.record"
    rewrite_measured(graded_run, lambda d: d.__setitem__("measured_version", 99))
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.file"


def test_the_check_fails_a_drawn_bias_the_profile_could_not_have_drawn(graded_run):
    def bend(d):
        entry = next(e for e in d["channels"] if e["measured"] == "n_z_meas")
        entry["drawn_bias"] = 0.5                                # 500 mg: not a 1 mg draw
        d["columns"]["n_z_meas"] = [v + 0.5 for v in d["columns"]["n_z_meas"]]
    rewrite_measured(graded_run, bend)
    result = check_instruments(graded_run)
    assert result.status == FAIL and result.failure == "instruments.residual"
    assert "drawn bias" in result.detail


def test_the_check_is_not_run_without_a_measured_file(tmp_path):
    assert check_instruments(None).status == NOT_RUN
    assert check_instruments(tmp_path).status == NOT_RUN
    run = write_run(tmp_path / "short", synthetic_telemetry(n=20))
    I.measure_run(run, "tactical", seed=1)
    assert check_instruments(run).status == NOT_RUN        # too few samples, not a pass


def test_the_check_imports_nothing_from_the_producer():
    """The verifier rule: the check re-derives every expectation itself."""
    check_source = (REPO / "core" / "telemetry" / "instruments_check.py").read_text(encoding="utf-8")
    verify_source = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    forbidden = re.compile(r"(from\s+\.?\S*instruments\s+import|import\s+\S*telemetry\.instruments\b"
                           r"|instruments\.(measure|load_profile|body_to_ned|first_order_lag))")
    assert not forbidden.search(check_source)
    assert not forbidden.search(verify_source)


# -- the command line, on a real c172p capture ---------------------------------------

@pytest.fixture(scope="module")
def c172p_measured(tmp_path_factory):
    from flightsim.capture import main as capture_main

    out = tmp_path_factory.mktemp("c172p")
    code = capture_main([str(EXAMPLES / "cameras_waypoint.yaml"), "--out", str(out),
                         "--max-previews", "0", "--instruments", "tactical"])
    assert code == 0
    return out


def test_the_cli_option_writes_the_measured_file_beside_the_telemetry(c172p_measured, capsys):
    out = c172p_measured
    data = json.loads((out / I.MEASURED_FILE).read_text(encoding="utf-8"))
    telemetry = json.loads((out / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["provenance"]["aircraft"]["name"] == "c172p"
    assert data["profile"]["name"] == "tactical" and data["samples"] == telemetry["samples"]
    assert data["truth_sha256"] == hashlib.sha256((out / "telemetry.json").read_bytes()).hexdigest()
    assert {e["measured"] for e in data["channels"]} == {
        "n_z_meas", "roll_rate_dps_meas", "pitch_rate_dps_meas", "yaw_rate_dps_meas",
        "lat_deg_meas", "lon_deg_meas", "altitude_m_gps_meas", "v_north_mps_meas",
        "v_east_mps_meas", "v_down_mps_meas", "cas_kt_meas", "altitude_m_baro_meas",
        "heading_deg_meas"}
    record = data["applied_variables"]["applied_variables"][0]
    assert record["name"] == "instruments.profile" and record["source"] == "user"
    assert record["null_test"]["ok"] is True
    # The record also rides in the capture manifest (rule 0).
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    names = [r["name"] for r in manifest["applied_variables"]["applied_variables"]]
    assert "instruments.profile" in names
    # The independent check grades the real run.
    result = check_instruments(out)
    assert result.status == PASS, result.detail


def test_a_second_capture_with_the_same_seed_is_byte_identical(c172p_measured, tmp_path):
    from flightsim.capture import main as capture_main

    again = tmp_path / "again"
    assert capture_main([str(EXAMPLES / "cameras_waypoint.yaml"), "--out", str(again),
                         "--max-previews", "0", "--instruments", "tactical"]) == 0
    assert (again / I.MEASURED_FILE).read_bytes() == (c172p_measured / I.MEASURED_FILE).read_bytes()


def test_the_default_writes_nothing_and_an_unknown_profile_refuses_before_flying(tmp_path, capsys):
    from flightsim.capture import main as capture_main

    out = tmp_path / "default"
    assert capture_main([str(EXAMPLES / "cameras_waypoint.yaml"), "--out", str(out),
                         "--max-previews", "0"]) == 0
    printed = capsys.readouterr().out
    assert "instruments: ideal (the recorded channels are the measurement; " \
           "no telemetry_measured.json written)" in printed
    assert not (out / I.MEASURED_FILE).exists()
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    record = next(r for r in manifest["applied_variables"]["applied_variables"]
                  if r["name"] == "instruments.profile")
    assert record["source"] == "default" and record["value"] == "ideal"
    # R2: no instrument stated -- no FDM-rate file, no manifest block
    # (absent-canonical); run.json carries the block with its file null.
    assert not (out / I.INSTRUMENTS_FILE).exists() and "instruments" not in manifest
    run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run_json["instruments"]["file"] is None
    assert run_json["instruments"]["rate_basis"] == "fdm loop"

    refused = tmp_path / "refused"
    code = capture_main([str(EXAMPLES / "cameras_waypoint.yaml"), "--out", str(refused),
                         "--max-previews", "0", "--instruments", "nope"])
    printed = capsys.readouterr().out
    assert code == 2 and "REFUSED -- instruments.profile:" in printed
    assert not refused.exists()                       # refused before any flight


# =====================================================================================
# R2: the FDM-rate observer (core/telemetry/instruments.py InstrumentObserver)
# =====================================================================================

import contextlib
import io

from core.fdm.state import MEASURED_CHANNELS, AircraftState
from core.scenario.spec import ScenarioSpec
from core.telemetry.recorder import DEFAULT_CHANNELS, Recorder

WAYPOINT = EXAMPLES / "cameras_waypoint.yaml"
TACTICAL_ARMS = {"imu": [1.0, 0.0, 0.0], "gps": [-1.0, 0.0, -0.8],
                 "pitot_static": [0.0, 2.0, 0.0], "magnetometer": [0.0, 0.0, 0.0]}


def stated_spec(duration_s: float = 3.0, profile: str = "tactical", **arms) -> ScenarioSpec:
    """The c172p waypoint flight (a turn through 360 deg with 38 deg of
    bank) with every instrument stated at the tactical profile and the
    arms above (or the overrides)."""
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("duration", float(duration_s))
    for name, arm in TACTICAL_ARMS.items():
        spec.set(f"instruments.{name}", {"profile": profile, "lever_arm_m": list(arms.get(name, arm))})
    return spec


def fly(spec: ScenarioSpec):
    from core.scenario.runner import run_spec

    with contextlib.redirect_stdout(io.StringIO()):
        return run_spec(spec, assert_closure=False)


@pytest.fixture(scope="module")
def stated_run():
    """30 s, every instrument tactical: 3601 observations, 151 fixes."""
    return fly(stated_spec(30.0))


@pytest.fixture(scope="module")
def default_run():
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("duration", 3.0)
    return fly(spec)


# -- the streams ---------------------------------------------------------------------

def test_the_observer_draws_from_five_named_streams_and_never_sensor_noise():
    assert I.OBSERVER_STREAMS == ("imu", "gps", "pitot_static", "magnetometer", "null_test")
    for name in I.OBSERVER_STREAMS:
        assert name in SUBSYSTEMS
    assert "sensor_noise" in SUBSYSTEMS and "sensor_noise" not in I.OBSERVER_STREAMS
    source = (REPO / "core/telemetry/instruments.py").read_text(encoding="utf-8")
    assert '"sensor_noise"' not in source
    spec = stated_spec(1.0)
    observer = I.InstrumentObserver(I.instruments_from_spec(spec), 2024, 120.0)
    seeds = derive(2024, 0)
    block = observer.manifest_block()
    assert block["seeds"]["streams"] == {s: seeds.for_subsystem(s) for s in I.OBSERVER_STREAMS}
    assert len(set(block["seeds"]["streams"].values())) == 5
    # The IMU's first draws are the accelerometer bias (from the imu stream).
    profile = I.load_profile("tactical")
    expected = generator(2024, "imu", 0).standard_normal(3) * profile.accelerometer["bias_repeatability_mg"] / 1000.0
    assert observer.acc_bias_g == pytest.approx(list(expected), rel=1e-12)
    expected_hi = generator(2024, "magnetometer", 0).standard_normal(2) * profile.magnetometer["hard_iron_sigma_fraction"]
    assert observer.hard_iron == pytest.approx(list(expected_hi), rel=1e-12)


# -- the specific force ----------------------------------------------------------------

def test_at_r_zero_the_specific_force_is_g0_times_n_with_the_z_sign_flipped():
    omega, omega_dot = np.array([0.5, -0.2, 0.1]), np.array([1.0, 2.0, -3.0])
    f = I.specific_force_body(0.01, -0.02, 0.997, omega, omega_dot, np.zeros(3))
    assert f == pytest.approx([I.G0 * 0.01, I.G0 * -0.02, -I.G0 * 0.997], abs=0.0)
    # No gravity term: level flight at 1 g reads -g0 on the down axis, as a
    # real accelerometer does; and the rotational terms at r != 0 are the
    # textbook ones (checked by hand: omega x (omega x r) = -|omega|^2 r
    # for r perpendicular to omega, omega_dot x r the tangential term).
    r = np.array([2.0, 0.0, 0.0])
    f_r = I.specific_force_body(0.0, 0.0, 1.0, np.array([0.0, 0.0, 1.0]), np.zeros(3), r)
    assert f_r == pytest.approx([-2.0, 0.0, -I.G0], abs=1e-12)
    f_r = I.specific_force_body(0.0, 0.0, 1.0, np.zeros(3), np.array([0.0, 0.0, 1.0]), r)
    assert f_r == pytest.approx([0.0, 2.0, -I.G0], abs=1e-12)


def test_on_the_real_run_the_cg_specific_force_is_jsbsims_n_and_the_ideal_measures_it_to_the_bit(default_run):
    a = default_run.instruments.arrays()
    assert np.array_equal(a["truth_f_cg_x_mps2"], I.G0 * a["truth_n_x"])
    assert np.array_equal(a["truth_f_cg_z_mps2"], -I.G0 * a["truth_n_z"])
    # The default (ideal at the CG): meas_* equals truth to the bit on every
    # step and every recorded sample; nothing was drawn, nothing written.
    assert np.max(np.abs(a["meas_n_z"] - a["truth_n_z"])) <= 2.3e-16
    assert np.array_equal(a["meas_p_dps"], np.degrees(a["truth_p_rad_s"]))
    assert np.array_equal(a["meas_lat_deg"], a["truth_lat_deg"])
    assert np.array_equal(a["meas_cas_kt"], a["truth_cas_kt"])
    wrapped = (a["meas_heading_deg"] - a["truth_magnetic_heading_deg"] + 180.0) % 360.0 - 180.0
    assert np.max(np.abs(wrapped)) < 1e-9            # the levelled atan2 against psi - D: rounding
    cols = default_run.telemetry.columns
    assert max(abs(m - t) for m, t in zip(cols["meas_n_z"], cols["n_z"])) <= 2.3e-16
    assert cols["meas_cas_kt"] == cols["cas_kt"]
    assert default_run.manifest["instruments"]["file"] is None
    assert default_run.manifest["instruments"]["rate_basis"] == "fdm loop"
    assert not any(r["name"].startswith("instruments.")
                   for r in default_run.manifest["applied_variables"]["applied_variables"])


def test_at_the_eyepoint_the_model_reproduces_jsbsims_own_pilot_accelerometer():
    """JSBSim's n-pilot-*-norm is vBodyAccel + omega_dot x r + omega x
    (omega x r) at the eyepoint (FGAuxiliary): an independent computation
    of the rotational terms. The IMU placed at the eyepoint (structural
    inches -> body metres: x = -(eye - cg)_x, y = +, z = -(eye - cg)_z)
    must read what JSBSim reads, on a rolling run, within 1e-3 m/s^2."""
    from core.scenario.runner import configure_from_spec, environment_for

    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("duration", 3.0)
    with contextlib.redirect_stdout(io.StringIO()):
        environment = environment_for(spec)
        fdm = configure_from_spec(spec, environment)
    eye = [fdm.props.get(f"metrics/eyepoint-{a}-in") for a in "xyz"]
    cg = [fdm.props.get(f"inertia/cg-{a}-in") for a in "xyz"]
    arm = (-(eye[0] - cg[0]) * 0.0254, (eye[1] - cg[1]) * 0.0254, -(eye[2] - cg[2]) * 0.0254)
    assert 0.1 < abs(arm[0]) < 0.2 and 0.2 < abs(arm[2]) < 0.3        # the c172p's eyepoint
    instruments = I.instruments_from_spec(spec)
    ideal = instruments["imu"]
    instruments["imu"] = I.InstrumentSpec("imu", ideal.profile, arm, True, "user", "the eyepoint")
    observer = I.InstrumentObserver(instruments, int(spec.seed.value), fdm.rate_hz)
    pilot = []
    environment.add_observer(observer.observe)
    environment.add_observer(lambda f: pilot.append(
        [f.props.get(f"accelerations/n-pilot-{a}-norm") * I.G0 for a in "xyz"]))
    environment.configure(fdm)
    observer.observe(fdm)                          # the initial state, as the runner does
    with contextlib.redirect_stdout(io.StringIO()):
        environment.run_for(fdm, 3.0)
    a = observer.arrays()
    model = np.stack([a[f"truth_f_{ax}_mps2"] for ax in "xyz"], axis=1)[1:]
    jsbsim = np.array(pilot)
    assert len(model) == len(jsbsim) == 360
    worst = float(np.max(np.abs(model - jsbsim)))
    rotational = float(np.max(np.abs(model - np.stack([a[f"truth_f_cg_{ax}_mps2"] for ax in "xyz"], axis=1)[1:])))
    assert rotational > 5e-2                       # the arm did something on this run (0.063 m/s^2)
    assert worst < 1e-4, worst                       # measured 1.5e-6 m/s^2 (the Earth-rate terms)


def test_the_rotational_term_matches_a_finite_difference_of_the_recorded_rates(stated_run):
    """omega_dot x r + omega x (omega x r) rebuilt from the LOGGED rates
    (central differences for omega_dot, never JSBSim's own property)
    against the logged sensor-minus-CG difference: within 5 % rms over
    the 30 s rolling run at r = 1 m forward."""
    a = stated_run.instruments.arrays()
    dt = 1.0 / stated_run.instruments.rate_hz
    omega = np.stack([a["truth_p_rad_s"], a["truth_q_rad_s"], a["truth_r_rad_s"]], axis=1)
    omega_dot = np.gradient(omega, dt, axis=0)
    r = np.array([1.0, 0.0, 0.0])
    rebuilt = np.array([I.rotational_terms(omega[i], omega_dot[i], r) for i in range(len(omega))])
    logged = np.stack([a[f"truth_f_{ax}_mps2"] - a[f"truth_f_cg_{ax}_mps2"] for ax in "xyz"], axis=1)
    rms_logged = float(np.sqrt(np.mean(logged[1:-1] ** 2)))
    rms_error = float(np.sqrt(np.mean((rebuilt[1:-1] - logged[1:-1]) ** 2)))
    assert rms_logged > 1e-3
    assert rms_error < 0.05 * rms_logged, (rms_error, rms_logged)     # measured 0.27 % (central); a backward difference 2.5e-7
    assert stated_run.manifest["instruments"]["rotational_term_peak_mps2"] == pytest.approx(
        float(np.max(np.linalg.norm(logged, axis=1))))


def test_lever_arm_zero_versus_one_metre_differs_by_the_rotational_term():
    """The same 3 s rolling run with the IDEAL IMU at the CG and 1 m
    forward: meas_n_z differs by exactly the z rotational term over g0
    (no noise), and the truth channels are untouched (the observer writes
    nothing to JSBSim: identical output digests apart from the meas_*
    columns)."""
    at_cg = fly(stated_spec(3.0, profile="ideal", imu=[0.0, 0.0, 0.0]))
    forward = fly(stated_spec(3.0, profile="ideal", imu=[1.0, 0.0, 0.0]))
    a0, a1 = at_cg.instruments.arrays(), forward.instruments.arrays()
    assert np.array_equal(a0["truth_n_z"], a1["truth_n_z"])
    assert np.array_equal(a0["truth_f_cg_z_mps2"], a1["truth_f_cg_z_mps2"])
    term = np.stack([a1[f"truth_f_{ax}_mps2"] - a1[f"truth_f_cg_{ax}_mps2"] for ax in "xyz"], axis=1)
    assert np.max(np.linalg.norm(term, axis=1)) > 5e-3            # measured 0.0137 m/s^2 (mostly x: the turn's centripetal term)
    assert np.max(np.abs(a0["meas_f_x_mps2"] - a0["truth_f_cg_x_mps2"])) == 0.0
    for k, ax in enumerate("xyz"):
        assert (a1[f"meas_f_{ax}_mps2"] - a0[f"meas_f_{ax}_mps2"]) == pytest.approx(term[:, k], abs=1e-12)
    assert (a1["meas_n_z"] - a0["meas_n_z"]) == pytest.approx(-term[:, 2] / I.G0, abs=1e-15)
    truth = {k: v for k, v in at_cg.telemetry.columns.items() if not k.startswith("meas_")}
    other = {k: v for k, v in forward.telemetry.columns.items() if not k.startswith("meas_")}
    assert truth == other
    assert at_cg.telemetry.columns["meas_n_z"] != forward.telemetry.columns["meas_n_z"]


# -- the residuals against the profile, within 25 % --------------------------------------

def test_every_stated_channel_differs_from_truth_by_its_profile_sigma_within_25_pct(stated_run):
    residuals = stated_run.manifest["instruments"]["residuals"]
    assert set(residuals) == set(MEASURED_CHANNELS)
    for name, r in residuals.items():
        assert r["ratio"] is not None and abs(r["ratio"] - 1.0) <= 0.25, (name, r)
        assert r["within_25pct"] is True
    assert residuals["meas_lat_deg"]["samples"] == 151          # the fixes over 30 s at 5 Hz
    assert stated_run.manifest["instruments"]["fixes"] == 151
    assert stated_run.manifest["instruments"]["steps"] == 3601


def test_each_stated_instrument_returns_its_record_with_a_measured_null_test(stated_run):
    from core.records import AppliedVariable, read_records

    records = {r["name"]: r for r in read_records(stated_run.manifest["applied_variables"])}
    for name, columns in I.INSTRUMENT_COLUMNS.items():
        record = records[f"instruments.{name}"]
        AppliedVariable.from_dict(record)                      # a well-formed record 2
        assert record["value"] == {"profile": "tactical", "lever_arm_m": TACTICAL_ARMS[name]}
        assert record["source"] == "user" and record["unit"] == "profile + m"
        assert record["telemetry_columns"] == list(columns)
        assert record["frame_keys"] == [f"state.{c}" for c in columns]
        assert record["null_test"]["ok"] is True and record["null_test"]["kind"] == "reached"
        assert record["null_test"]["without"] == 0.0 and record["null_test"]["threshold"] == 0.75
        assert 0.75 <= record["null_test"]["with"] <= 1.25
        assert record["parameters"]["rate_basis"] == "fdm loop"
        assert record["parameters"]["rate_hz"] == 120.0
        assert set(record["parameters"]["seed_streams"]) == set(I.OBSERVER_STREAMS)
        assert record["parameters"]["lever_arm_m"] == TACTICAL_ARMS[name]
        assert record["model"]["parameters"]["rate_basis"] == "fdm loop"
        assert record["readback"]["agrees"] is True and record["readback"]["tolerance"] == 0.0
        assert record["properties_written"] == [] and "jsbsim_writes" not in record
        assert any("no device is calibrated" in n for n in record["not_claimed"])
    imu = records["instruments.imu"]
    assert imu["parameters"]["allan_self_report"]["meas_p_dps"]["white_term"] == "PASS"
    assert imu["parameters"]["rotational_term_peak_mps2"] > 1e-3
    assert records["instruments.magnetometer"]["parameters"]["declination_deg_at_start"] == pytest.approx(-8.99, abs=0.05)


# -- the Allan self-report --------------------------------------------------------------

def test_the_non_overlapping_allan_deviation_recovers_a_white_density_within_25_pct():
    rng = np.random.default_rng(3)
    dt, n_density = 1.0 / 120.0, 0.125 / 60.0                  # deg/sqrt(s), the tactical gyro
    stream = rng.standard_normal(3601) * n_density / math.sqrt(dt)
    for m in I.ALLAN_SHORT_M:
        adev, clusters = I.allan_deviation(stream, dt, m)
        assert clusters >= 30
        assert abs(adev / (n_density / math.sqrt(m * dt)) - 1.0) < I.ALLAN_TOL
    report = I.allan_self_report(stream, dt, n_density, 0.0, 100.0, "deg/s")
    assert report["white_term"] == "PASS" and report["tolerance"] == 0.25
    # A stream whose noise is doubled but declared at N fails the agreement.
    bad = I.allan_self_report(2.0 * stream, dt, n_density, 0.0, 100.0, "deg/s")
    assert bad["white_term"].startswith("FAIL")
    # An ideal channel grades nothing; a short stream grades nothing.
    assert I.allan_self_report(np.zeros(100), dt, 0.0, 0.0, 100.0, "deg/s")["white_term"].startswith("NOT RUN")
    assert I.allan_self_report(stream[:20], dt, n_density, 0.0, 100.0, "deg/s")["white_term"].startswith("NOT RUN")


def test_b_and_k_are_not_run_below_100_correlation_times_and_estimated_above(stated_run):
    report = stated_run.manifest["instruments"]["allan_self_report"]
    for name in ("meas_p_dps", "meas_f_z_mps2"):
        bk = report[name]["bias_instability_and_rate_random_walk"]
        assert bk["status"] == "NOT RUN" and "100" in bk["reason"]
        assert bk["B_estimate"] is None and bk["K_estimate"] is None
        assert report[name]["span_s"] == pytest.approx(30.0)
    assert report["estimator_check"]["stream"] == "null_test"
    assert report["estimator_check"]["report"]["white_term"] == "PASS"
    # A synthetic run spanning 100 correlation times: B and K are estimated
    # (not graded) -- the rule is on the span, not on the profile.
    rng = np.random.default_rng(5)
    dt = 0.01
    stream = rng.standard_normal(3001) * 0.002 / math.sqrt(dt)
    assert I.allan_self_report(stream, dt, 0.002, 1e-4, 0.3, "deg/s")["bias_instability_and_rate_random_walk"]["status"] == "estimated, not graded"
    assert I.allan_self_report(stream, dt, 0.002, 1e-4, 0.31, "deg/s")["bias_instability_and_rate_random_walk"]["status"] == "NOT RUN"


# -- the GPS at the FDM rate ------------------------------------------------------------

def test_the_gps_holds_the_last_fix_between_fixes_at_the_fdm_rate(stated_run):
    a = stated_run.instruments.arrays()
    fix = a["gps_fix"].astype(int)
    assert fix[0] == 1 and fix.sum() == 151                      # 5 Hz over 30 s, the first at t0
    assert list(fix[:25]) == [1] + [0] * 23 + [1]                # every 24th step at 120 Hz
    held = np.flatnonzero(fix == 0)
    for name in ("meas_lat_deg", "meas_lon_deg", "meas_alt_m"):
        assert np.array_equal(a[name][held], a[name][held - 1])
    # The 10 Hz recorder carries the held value too (the latest measured).
    cols = stated_run.telemetry.columns
    assert len(set(cols["meas_alt_m"])) < len(cols["meas_alt_m"])


def test_a_gps_faster_than_the_fdm_refuses_instrument_rate(tmp_path):
    from core.scenario.validate import validate_instruments

    profile = json.loads((I.PROFILE_DIR / "tactical.json").read_text(encoding="utf-8"))
    profile["gps"]["update_rate_hz"] = 200.0
    profile["name"] = "fast"
    (tmp_path / "fast.json").write_text(json.dumps(profile), encoding="utf-8")
    problems = I.instrument_problems("gps", {"profile": "fast", "lever_arm_m": [0, 0, 0]},
                                     rate_hz=120.0, profile_dir=tmp_path)
    assert [c for c, _ in problems] == ["instrument.rate"]
    assert I.instrument_problems("gps", {"profile": "fast"}, rate_hz=240.0, profile_dir=tmp_path) == []
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("instruments.gps", {"profile": "tactical", "lever_arm_m": [0.0, 0.0, 0.0]})
    spec.set("rate", 4.0)                                        # a 4 Hz FDM under a 5 Hz receiver
    assert [v.constraint for v in validate_instruments(spec)] == ["instrument.rate"]


# -- the pitot-static and the magnetometer ------------------------------------------------

def test_the_position_error_table_is_linear_held_and_zero_when_empty():
    assert I.position_error_kt(100.0, []) == 0.0
    table = [[80.0, -2.0], [120.0, 2.0]]
    assert I.position_error_kt(100.0, table) == pytest.approx(0.0)
    assert I.position_error_kt(90.0, table) == pytest.approx(-1.0)
    assert I.position_error_kt(50.0, table) == -2.0 and I.position_error_kt(200.0, table) == 2.0
    assert I.position_error_kt(np.array([80.0, 120.0]), table).tolist() == [-2.0, 2.0]
    data = json.loads((I.PROFILE_DIR / "tactical.json").read_text(encoding="utf-8"))
    data["pitot_static"]["position_error_table_kt"] = [[120.0, 1.0], [80.0, 0.0]]   # not ascending
    with pytest.raises(I.InstrumentProfileError, match="ascending"):
        I.profile_from_dict(data, name="tactical")
    assert I.load_profile("tactical").pitot_static["position_error_table_kt"] == []


def test_the_dipole_is_the_igrf13_degree_1_field_and_the_reading_is_magnetic_heading():
    """The spherical-gradient field against the Cartesian dipole formula
    B = a^3 (3 (G . r_hat) r_hat - G) / r^3 with G = (g11, h11, g10) --
    a second derivation -- at three points; the declination it gives;
    and the levelled reading with no hard iron = true heading minus D."""
    g = np.array([I.IGRF13_G11_NT, I.IGRF13_H11_NT, I.IGRF13_G10_NT])
    for lat, lon, alt in ((46.0, 7.7, 1500.0), (-33.9, 151.2, 0.0), (64.1, -21.9, 3000.0)):
        theta, phi = math.radians(90.0 - lat), math.radians(lon)
        r_hat = np.array([math.sin(theta) * math.cos(phi), math.sin(theta) * math.sin(phi), math.cos(theta)])
        scale = (I.IGRF_REFERENCE_RADIUS_M / (I.IGRF_REFERENCE_RADIUS_M + alt)) ** 3
        b_xyz = scale * (3.0 * np.dot(g, r_hat) * r_hat - g)
        north = np.array([-math.cos(theta) * math.cos(phi), -math.cos(theta) * math.sin(phi), math.sin(theta)])
        east = np.array([-math.sin(phi), math.cos(phi), 0.0])
        expected = (float(b_xyz @ north), float(b_xyz @ east), float(-b_xyz @ r_hat))
        assert I.dipole_field_ned(lat, lon, alt) == pytest.approx(expected, rel=1e-12, abs=1e-9)
    x, y, z = I.dipole_field_ned(46.0, 7.7, 1500.0)
    assert 15000.0 < math.hypot(x, y) < 30000.0 and z > 30000.0        # a mid-latitude field, down positive
    d = I.dipole_declination_deg(46.0, 7.7, 1500.0)
    assert d == pytest.approx(math.degrees(math.atan2(y, x)))
    for psi in (0.0, 90.0, 200.0, 359.0):
        for roll, pitch in ((0.0, 0.0), (30.0, 10.0), (-45.0, -5.0)):
            reading = I.magnetic_heading_deg((x, y, z), roll, pitch, psi, (0.0, 0.0))
            assert (reading - (psi - d)) % 360.0 == pytest.approx(0.0, abs=1e-9) or \
                   (reading - (psi - d)) % 360.0 == pytest.approx(360.0, abs=1e-9)
    # Level, the hard iron reduces to the recorded-rate formula.
    level = I.magnetic_heading_deg((x, y, z), 0.0, 0.0, 90.0 + d, (0.1, 0.0))
    assert level == pytest.approx(float(I.hard_iron_heading(np.array([90.0]), 0.1, 0.0)[0]), abs=1e-9)


# -- the recorder samples the latest value; NaN before the first observation -------------

def test_the_recorder_samples_the_latest_measured_value_and_reads_it_back(stated_run):
    a = stated_run.instruments.arrays()
    cols = stated_run.telemetry.columns
    for k, t in enumerate(cols["t"]):
        i = int(np.searchsorted(a["t"], t, side="right")) - 1
        assert a["t"][i] == pytest.approx(t, abs=1e-9)
        for name in MEASURED_CHANNELS:
            assert cols[name][k] == a[name][i], (name, k)
    rb = stated_run.instruments.readback(stated_run.telemetry)
    assert rb.agrees and rb.difference == 0.0 and rb.property == f"telemetry.meas_n_z[{len(cols['t']) - 1}]"


def test_an_unobserved_snapshot_and_a_recorder_without_an_observer_carry_nan():
    from core.fdm import FlightDynamics

    assert MEASURED_CHANNELS == I.MEASURED_CHANNEL_NAMES
    assert set(MEASURED_CHANNELS) <= set(DEFAULT_CHANNELS)
    with contextlib.redirect_stdout(io.StringIO()):
        fdm = FlightDynamics("c172p")
        state = fdm.state()
    assert all(math.isnan(getattr(state, name)) for name in MEASURED_CHANNELS)
    with pytest.raises(ValueError, match="not measured channels"):
        AircraftState.from_properties(fdm.props, (), measured={"n_z": 1.0})
    filled = AircraftState.from_properties(fdm.props, (), measured={"meas_n_z": 0.5})
    assert filled.meas_n_z == 0.5 and math.isnan(filled.meas_cas_kt)
    recorder = Recorder(fdm, interval_s=0.1)
    recorder.sample(force=True)
    assert all(math.isnan(recorder.columns[name][0]) for name in MEASURED_CHANNELS)
    observer = I.InstrumentObserver(I.instruments_from_spec(ScenarioSpec.read(WAYPOINT)), 1, fdm.rate_hz)
    assert all(math.isnan(v) for v in observer.latest().values())   # nothing observed yet
    recorder = Recorder(fdm, interval_s=0.1, measured=observer)
    recorder.sample(force=True)
    assert math.isnan(recorder.columns["meas_n_z"][0])              # NaN before the first fix
    observer.observe(fdm)
    recorder.sample(force=True)
    assert recorder.columns["meas_n_z"][1] == observer.latest()["meas_n_z"]
    assert not math.isnan(recorder.columns["meas_n_z"][1])


# -- both loops, determinism, the file --------------------------------------------------

def test_both_step_loops_record_the_same_number_of_fdm_rate_observations():
    """run_for (no autopilot) and the runner's explicit loop (hold_state
    true, the B747 example) each observe once per step plus once at the
    initial state."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    spec.set("duration", 2.0)
    spec.set("instruments.imu", {"profile": "tactical", "lever_arm_m": [1.0, 0.0, 0.0]})
    spec.set("hold_state", False)
    via_run_for = fly(spec)
    spec.set("hold_state", True)
    via_explicit = fly(spec)
    assert via_run_for.instruments.steps == via_explicit.instruments.steps == 241
    assert len(via_run_for.instruments.arrays()["t"]) == 241
    for run in (via_run_for, via_explicit):
        assert not any(math.isnan(v) for v in run.telemetry.columns["meas_n_z"])


def test_the_file_is_byte_deterministic_and_named_in_the_block(tmp_path):
    first, second = fly(stated_spec(2.0)), fly(stated_spec(2.0))
    assert first.instruments.npz_bytes() == second.instruments.npz_bytes()
    assert first.output_digest == second.output_digest
    spec = stated_spec(2.0)
    spec.set("seed", int(spec.seed.value) + 1)
    other = fly(spec)
    assert other.instruments.npz_bytes() != first.instruments.npz_bytes()
    written = first.write(tmp_path / "run")
    path = written / I.INSTRUMENTS_FILE
    block = first.manifest["instruments"]
    assert path.is_file() and block["file"] == I.INSTRUMENTS_FILE
    assert hashlib.sha256(path.read_bytes()).hexdigest() == block["sha256"]
    with np.load(path) as data:
        assert sorted(data.files) == sorted(block["columns"])
        assert len(data["t"]) == 241
    manifest = json.loads((written / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["instruments"]["sha256"] == block["sha256"]
    assert json.dumps(manifest).isascii()


# -- refusals by name ---------------------------------------------------------------------

@pytest.mark.parametrize("field, value, name", [
    ("imu", {"profile": "nope", "lever_arm_m": [0, 0, 0]}, "instrument.profile"),
    ("imu", "tactical", "instrument.profile"),
    ("gps", {"profile": "tactical", "antenna": 1}, "instrument.profile"),
    ("gps", {"lever_arm_m": [0, 0, 0]}, "instrument.profile"),
    ("imu", {"profile": "tactical", "lever_arm_m": [1, 2]}, "instrument.lever_arm"),
    ("imu", {"profile": "tactical", "lever_arm_m": [1, 2, "z"]}, "instrument.lever_arm"),
    ("imu", {"profile": "tactical", "lever_arm_m": [100.0, 0, 0]}, "instrument.lever_arm"),
])
def test_a_bad_instrument_field_refuses_by_name_in_the_validator_and_the_runner(field, value, name):
    from core.scenario.runner import run_spec
    from core.scenario.validate import validate_instruments

    spec = ScenarioSpec.read(WAYPOINT)
    spec.set(f"instruments.{field}", value)
    assert name in [v.constraint for v in validate_instruments(spec)]
    with pytest.raises(I.InstrumentError) as err, contextlib.redirect_stdout(io.StringIO()):
        run_spec(spec, validate_first=False, assert_closure=False)
    assert err.value.constraint == name
    assert I.instrument_problems("imu", None) == []
    assert I.instrument_problems("imu", {"profile": "tactical"}) == []   # the arm defaults to 0


def test_the_registry_claims_the_block_and_every_effect_channel_is_recorded(stated_run):
    from core.registry import REGISTRY
    from core.scenario.blocks import InstrumentsSpec

    recorded = set(stated_run.telemetry.columns)
    for name in InstrumentsSpec.FIELD_ORDER:
        entry = REGISTRY.get(f"instruments.{name}")
        assert entry.spec_path == f"instruments.{name}" and entry.null_value is None
        assert [c.name for c in entry.effect_channels] == list(I.INSTRUMENT_COLUMNS[name])
        assert all(c.name in recorded for c in entry.effect_channels)
    from core.capture.manifest import state_units
    units = state_units(stated_run.telemetry.columns)
    assert units["meas_n_z"] == "g" and units["meas_p_dps"] == "deg/s" and units["meas_alt_m"] == "m"
    assert "?" not in {units[c] for c in MEASURED_CHANNELS}
