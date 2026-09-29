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
    assert record.source == "user" and record.model == I.MODEL
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

    refused = tmp_path / "refused"
    code = capture_main([str(EXAMPLES / "cameras_waypoint.yaml"), "--out", str(refused),
                         "--max-previews", "0", "--instruments", "nope"])
    printed = capsys.readouterr().out
    assert code == 2 and "REFUSED -- instruments.profile:" in printed
    assert not refused.exists()                       # refused before any flight
