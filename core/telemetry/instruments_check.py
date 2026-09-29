"""The verifier-side check of ``telemetry_measured.json`` -- independent code.

This module imports NOTHING from :mod:`core.telemetry.instruments` (the
producer). It re-derives every expectation from the profile the file
carries and from ``telemetry.json`` (the truth the recorder wrote), with
its own unit conversions, its own rotation, its own lag filter and its
own hard-iron formula, so a producer that computed any of them wrongly
cannot pass by agreeing with itself (the verifier rule of
core/capture/verify.py). ``core.capture.verify.verify_instruments`` wraps
:func:`check_instruments` into its ``Check``.

What is checked, in order, with the refusal name each FAIL carries:

* ``instruments.file``: the file is readable and its ``measured_version``
  is one this build reads.
* ``instruments.truth``: ``telemetry.json`` is beside it, hashes to the
  ``truth_sha256`` the file recorded, and every truth column in the file
  equals the recorder's column value for value.
* ``instruments.record``: the ``applied_variables`` block is version 1 and
  holds the ``instruments.profile`` record naming the file's profile,
  with a null test that measured a difference.
* ``instruments.residual``: per channel, the residual (measured minus
  truth) has the statistics the profile states -- the standard deviation
  within :data:`SIGMA_FACTOR` of the expected sigma, the mean within the
  bias bound -- after this module accounts for the lag (it re-filters the
  truth), the hold (GPS statistics are taken at the fix samples, and the
  held samples must repeat the last fix exactly), the lever arm (it
  re-rotates the antenna offset with the recorder's attitude) and the
  hard-iron pair (it re-applies the drawn offsets, which must lie within
  five sigma of the profile). The IMU's drawn constant biases must lie
  within five sigma of the stated repeatability, and the mean residual
  within the drawn bias plus the bias-instability and sampling bounds.

NOT RUN when the run has no ``telemetry_measured.json`` (the ideal profile,
or none stated) and when a channel has fewer than :data:`MIN_SAMPLES`
samples to take a statistic from.

THE FDM-RATE CHECKS (R2). :func:`check_allan` reads ``instruments.npz``
(the observer's truth_* and meas_* columns at the FDM rate) and the
manifest's ``instruments`` block, and computes the OVERLAPPING Allan
deviation of each IMU residual from the definition,

    sigma^2(tau) = 1 / (2 tau^2 (N - 2m)) sum_k (theta_{k+2m} - 2 theta_{k+m} + theta_k)^2

with theta the cumulative sum of the rate series times dt (the integrated
angle / velocity), and grades ``|adev(tau) / (N / sqrt(tau)) - 1| <
ALLAN_TOL`` at the short taus against the profile's own random-walk
density N -- a second estimator against the producer's non-overlapping
one, so the two agree by arithmetic, not by copy. B and K are NOT RUN
when the run spans less than ALLAN_BK_RUN_MULTIPLE correlation times.
:func:`check_lever_arm` recovers the GPS antenna arm from the position
residuals at the fix samples (measured minus truth in NED, each fix's
attitude rotated by the checker's own axis-by-axis rotation; the arm is
the least-squares solution r = mean(R_i^T d_i), R orthonormal) and the
IMU arm from the specific-force difference (sensor minus CG) against the
matrix ``[omega_dot]x + [omega]x [omega]x`` built from the LOGGED rates
with omega_dot by central finite differences of those rates -- not
JSBSim's own angular accelerations -- and compares each to the declared
arm. Both are NOT RUN without the file, for an unstated instrument (the
ideal at the CG grades nothing) or below the sample minimum; each FAIL
carries its name (``check.instrument_allan``, ``instrument.lever_arm``).

NOT CLAIMED: that the profile's numbers describe any real instrument (the
check grades the file against the profile it carries, not the profile
against the world); that the drawn biases were drawn from the stated seed
(the check reads the draws the file recorded and bounds them; the seed
derivation is graded by tests/test_instruments.py); any distribution shape
beyond the second moment (no chi-square, no normality test); B and K on a
run shorter than 100 correlation times (NOT RUN, said so).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

import numpy as np

PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT RUN"
MEASURED_FILE = "telemetry_measured.json"
READS_VERSION = 1
RECORD_NAME = "instruments.profile"
#: The residual standard deviation must lie within [1/SIGMA_FACTOR,
#: SIGMA_FACTOR] of the profile's expected sigma. With N >= MIN_SAMPLES
#: the sampling error of a standard deviation is under 1/sqrt(2N) = 13%,
#: so 1.5 leaves room for it and for the Gauss-Markov term while a file
#: whose noise was doubled (ratio 2.0) or halved (0.5) fails.
SIGMA_FACTOR = 1.5
#: Fewer samples than this make no statistic: NOT RUN, not a pass.
MIN_SAMPLES = 30
#: A drawn constant bias further than this many sigma from zero is not a
#: draw from the stated repeatability.
BIAS_SIGMAS = 5.0
#: How many sampling sigmas a mean residual may sit from its expectation.
MEAN_SIGMAS = 5.0
G0 = 9.80665
WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3


#: R2: the FDM-rate file, its version, the Allan agreement bound, the
#: B / K rule, the short taus (as multiples of dt), the sample minimum and
#: the lever-arm recovery tolerance (metres, beyond the sampling term).
INSTRUMENTS_FILE = "instruments.npz"
INSTRUMENTS_READS_VERSION = 1
ALLAN_TOL = 0.25
ALLAN_BK_RUN_MULTIPLE = 100.0
ALLAN_SHORT_M = (1, 2, 4)
ALLAN_MIN_SAMPLES = 30
LEVER_ARM_TOL_M = 0.05
FAIL_ALLAN = "check.instrument_allan"
FAIL_LEVER_ARM = "instrument.lever_arm"


class CheckResult(NamedTuple):
    status: str
    detail: str
    failure: Optional[str] = None


def _radii(lat_deg: float) -> Tuple[float, float]:
    s = math.sin(math.radians(lat_deg))
    d = 1.0 - WGS84_E2 * s * s
    return WGS84_A * (1.0 - WGS84_E2) / d ** 1.5, WGS84_A / math.sqrt(d)


def _rotate_body_to_ned(arm: Sequence[float], roll_deg: float, pitch_deg: float,
                        yaw_deg: float) -> Tuple[float, float, float]:
    """The lever arm in NED, written out from the ZYX Euler sequence rather
    than as a matrix so it is a second derivation, not a copy."""
    phi, theta, psi = (math.radians(roll_deg), math.radians(pitch_deg),
                       math.radians(yaw_deg))
    x, y, z = float(arm[0]), float(arm[1]), float(arm[2])
    # Rx(phi) first: body -> after roll
    y1 = math.cos(phi) * y - math.sin(phi) * z
    z1 = math.sin(phi) * y + math.cos(phi) * z
    x1 = x
    # Ry(theta)
    x2 = math.cos(theta) * x1 + math.sin(theta) * z1
    z2 = -math.sin(theta) * x1 + math.cos(theta) * z1
    y2 = y1
    # Rz(psi)
    north = math.cos(psi) * x2 - math.sin(psi) * y2
    east = math.sin(psi) * x2 + math.cos(psi) * y2
    return north, east, z2


def _lag(x: np.ndarray, tau_s: float, dt: float) -> np.ndarray:
    """The stated backward-Euler lag, ``y[i] = y[i-1] + dt/(tau+dt) (x[i] - y[i-1])``."""
    if tau_s <= 0.0:
        return x.copy()
    a = dt / (tau_s + dt)
    y = np.empty_like(x)
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = (1.0 - a) * y[i - 1] + a * x[i]
    return y


def _wrap180(x: np.ndarray) -> np.ndarray:
    return (x + 180.0) % 360.0 - 180.0


class _Violation(Exception):
    pass


def _std_ok(residual: np.ndarray, expected: float, label: str,
            problems: List[str]) -> float:
    """The ratio of the residual's standard deviation to the expected sigma;
    records a problem when it falls outside the band."""
    std = float(np.std(residual))
    if expected <= 0.0:
        if std > 1e-9:
            problems.append(f"{label}: residual std {std:.3g} where the profile "
                            f"states 0")
        return 0.0 if std <= 1e-9 else math.inf
    ratio = std / expected
    if not (1.0 / SIGMA_FACTOR <= ratio <= SIGMA_FACTOR):
        problems.append(f"{label}: residual std {std:.4g} is {ratio:.2f} x the "
                        f"profile's {expected:.4g} (band {1 / SIGMA_FACTOR:.2f}"
                        f"..{SIGMA_FACTOR:.2f})")
    return ratio


def _mean_ok(residual: np.ndarray, expected_mean: float, extra_bound: float,
             sigma: float, label: str, problems: List[str]) -> None:
    n = len(residual)
    bound = extra_bound + MEAN_SIGMAS * sigma / math.sqrt(n) + 1e-12
    mean = float(np.mean(residual))
    if abs(mean - expected_mean) > bound:
        problems.append(f"{label}: mean residual {mean:.4g} sits {abs(mean - expected_mean):.4g} "
                        f"from the expected {expected_mean:.4g} (bound {bound:.4g})")


def _expected_imu(profile: Mapping[str, Any], instrument: str, dt: float
                  ) -> Tuple[float, float, float]:
    """(white sigma, bias-instability sigma, bias-repeatability sigma) in the
    channel's unit, from the profile's own words."""
    imu = profile["imu"]
    if instrument == "imu.accelerometer":
        a = imu["accelerometer"]
        white = a["velocity_random_walk_mps_per_sqrt_h"] / math.sqrt(3600.0) / math.sqrt(dt) / G0
        return white, a["bias_instability_mg"] * 1e-3, a["bias_repeatability_mg"] * 1e-3
    g = imu["gyro"]
    white = g["angle_random_walk_deg_per_sqrt_h"] / math.sqrt(3600.0) / math.sqrt(dt)
    return white, g["bias_instability_deg_per_h"] / 3600.0, g["bias_repeatability_deg_per_h"] / 3600.0


def check_instruments(run_dir) -> CheckResult:
    """Grade ``<run_dir>/telemetry_measured.json`` against the profile it
    carries and the truth beside it. See the module docstring."""
    if run_dir is None:
        return CheckResult(NOT_RUN, "no run directory")
    run_dir = Path(run_dir)
    path = run_dir / MEASURED_FILE
    if not path.is_file():
        return CheckResult(NOT_RUN, f"no {MEASURED_FILE} in the run (instruments "
                                    f"profile ideal, or none stated)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult(FAIL, f"{path} is unreadable: {exc}", failure="instruments.file")
    if not isinstance(data, dict) or data.get("measured_version") != READS_VERSION:
        return CheckResult(FAIL, f"{MEASURED_FILE} measured_version "
                                 f"{data.get('measured_version') if isinstance(data, dict) else '?'!r} "
                                 f"(this build reads {READS_VERSION})",
                           failure="instruments.file")
    columns = data.get("columns")
    entries = data.get("channels")
    profile = data.get("profile")
    if not isinstance(columns, dict) or not isinstance(entries, list) \
            or not isinstance(profile, dict) or "t" not in columns:
        return CheckResult(FAIL, f"{MEASURED_FILE} lacks its columns, channels or profile",
                           failure="instruments.file")

    # -- the truth beside the measurement is the recorder's -------------
    truth_path = run_dir / "telemetry.json"
    if not truth_path.is_file():
        return CheckResult(FAIL, f"{truth_path} is absent, so the truth beside the "
                                 f"measurements cannot be confirmed",
                           failure="instruments.truth")
    raw = truth_path.read_bytes()
    if data.get("truth_sha256") != hashlib.sha256(raw).hexdigest():
        return CheckResult(FAIL, "telemetry.json does not hash to the truth_sha256 the "
                                 "measured file recorded; the truth beside the "
                                 "measurements is not this run's recording",
                           failure="instruments.truth")
    try:
        telemetry = json.loads(raw.decode("utf-8"))
        truth_columns = telemetry["columns"]
        dt = float(telemetry["interval_s"])
    except (ValueError, KeyError, TypeError) as exc:
        return CheckResult(FAIL, f"telemetry.json unreadable as a recording: {exc}",
                           failure="instruments.truth")
    if float(data.get("interval_s", -1.0)) != dt:
        return CheckResult(FAIL, f"the measured file's interval_s {data.get('interval_s')!r} "
                                 f"is not the recorder's {dt!r}", failure="instruments.truth")
    for name in ["t"] + [e.get("truth") for e in entries]:
        if name not in truth_columns or name not in columns:
            return CheckResult(FAIL, f"truth column {name!r} is not in both files",
                               failure="instruments.truth")
        if list(columns[name]) != list(truth_columns[name]):
            return CheckResult(FAIL, f"truth column {name!r} in {MEASURED_FILE} differs "
                                     f"from the recorder's", failure="instruments.truth")

    # -- the record ------------------------------------------------------
    block = data.get("applied_variables")
    records = block.get("applied_variables") if isinstance(block, dict) else None
    if not isinstance(block, dict) or block.get("record_version") != 1 \
            or not isinstance(records, list):
        return CheckResult(FAIL, "the measured file carries no version-1 applied_variables "
                                 "block", failure="instruments.record")
    record = next((r for r in records if isinstance(r, dict) and r.get("name") == RECORD_NAME), None)
    if record is None or record.get("value") != profile.get("name") \
            or not isinstance(record.get("null_test"), dict) \
            or record["null_test"].get("ok") is not True:
        return CheckResult(FAIL, f"the {RECORD_NAME} record is absent, names another "
                                 f"profile, or its null test measured no difference",
                           failure="instruments.record")

    # -- the residual statistics ----------------------------------------
    t = np.asarray(columns["t"], dtype=float)
    n = len(t)
    if n < MIN_SAMPLES:
        return CheckResult(NOT_RUN, f"{n} samples are too few for a residual statistic "
                                    f"(needs {MIN_SAMPLES})")
    problems: List[str] = []
    ratios: Dict[str, float] = {}
    gps_fix = np.asarray(columns.get("gps_fix", []), dtype=int)
    roll = np.asarray(truth_columns.get("roll_deg", []), dtype=float)
    pitch = np.asarray(truth_columns.get("pitch_deg", []), dtype=float)
    yaw = np.asarray(truth_columns.get("heading_deg", []), dtype=float)
    try:
        for entry in entries:
            instrument = str(entry.get("instrument"))
            truth_name, measured_name = str(entry.get("truth")), str(entry.get("measured"))
            if measured_name not in columns:
                raise _Violation(f"measured column {measured_name!r} is declared but absent")
            truth = np.asarray(columns[truth_name], dtype=float)
            meas = np.asarray(columns[measured_name], dtype=float)
            if len(meas) != n or len(truth) != n:
                raise _Violation(f"{measured_name}: {len(meas)} values for {n} samples")
            if not np.all(np.isfinite(meas)):
                raise _Violation(f"{measured_name}: a non-finite measurement")
            label = measured_name

            if instrument in ("imu.accelerometer", "imu.gyro"):
                white, bi, rep = _expected_imu(profile, instrument, dt)
                drawn = float(entry.get("drawn_bias", math.nan))
                if not math.isfinite(drawn) or abs(drawn) > BIAS_SIGMAS * rep + 1e-12:
                    raise _Violation(f"{label}: drawn bias {drawn:.4g} is outside "
                                     f"{BIAS_SIGMAS:g} sigma of the repeatability {rep:.4g}")
                residual = meas - truth
                ratios[label] = _std_ok(residual, math.hypot(white, bi), label, problems)
                _mean_ok(residual, drawn, 6.0 * bi, white, label, problems)

            elif instrument in ("gps.position", "gps.velocity"):
                if len(gps_fix) != n:
                    raise _Violation(f"{label}: no gps_fix column to account for the hold")
                held = np.flatnonzero(gps_fix[1:] == 0) + 1
                if held.size and not np.array_equal(meas[held], meas[held - 1]):
                    raise _Violation(f"{label}: a held sample does not repeat the last fix")
                rate = float(profile["gps"]["update_rate_hz"])
                expected_fixes = int(math.floor((t[-1] - t[0]) * rate + 1e-9)) + 1
                fixes = int(gps_fix.sum())
                if abs(fixes - expected_fixes) > 1 or gps_fix[0] != 1:
                    raise _Violation(f"{label}: {fixes} fixes over {t[-1] - t[0]:.2f} s at "
                                     f"{rate:g} Hz (expected {expected_fixes} +- 1, "
                                     f"the first at the first sample)")
                at = np.flatnonzero(gps_fix == 1)
                if at.size < MIN_SAMPLES:
                    return CheckResult(NOT_RUN, f"{at.size} GPS fixes are too few for a "
                                                f"residual statistic (needs {MIN_SAMPLES})")
                axis = str(entry.get("axis"))
                if instrument == "gps.velocity":
                    sigma = float(profile["gps"]["velocity_sigma_mps"])
                    residual = meas[at] - truth[at]
                else:
                    if not (len(roll) == len(pitch) == len(yaw) == n):
                        raise _Violation(f"{label}: telemetry.json has no attitude to "
                                         f"re-rotate the lever arm with")
                    arm = profile["gps"]["antenna_offset_body_m"]
                    lever = np.array([_rotate_body_to_ned(arm, roll[i], pitch[i], yaw[i])
                                      for i in at])
                    lat = np.asarray(columns["lat_deg"], dtype=float)[at]
                    if axis == "north":
                        r_m = np.array([_radii(v)[0] for v in lat])
                        residual = np.radians(meas[at] - truth[at]) * r_m - lever[:, 0]
                        sigma = float(profile["gps"]["north_east_sigma_m"])
                    elif axis == "east":
                        r_n = np.array([_radii(v)[1] for v in lat])
                        residual = (np.radians(meas[at] - truth[at]) * r_n
                                    * np.cos(np.radians(lat)) - lever[:, 1])
                        sigma = float(profile["gps"]["north_east_sigma_m"])
                    else:
                        residual = (truth[at] - meas[at]) - lever[:, 2]
                        sigma = float(profile["gps"]["vertical_sigma_m"])
                ratios[label] = _std_ok(residual, sigma, label, problems)
                _mean_ok(residual, 0.0, 0.0, sigma, label, problems)

            elif instrument in ("pitot_static.airspeed", "pitot_static.altitude"):
                ps = profile["pitot_static"]
                if instrument == "pitot_static.airspeed":
                    sigma, tau = float(ps["cas_sigma_kt"]), float(ps["cas_lag_s"])
                else:
                    sigma, tau = (float(ps["pressure_altitude_sigma_m"]),
                                  float(ps["pressure_altitude_lag_s"]))
                residual = meas - _lag(truth, tau, dt)
                ratios[label] = _std_ok(residual, sigma, label, problems)
                _mean_ok(residual, 0.0, 0.0, sigma, label, problems)

            elif instrument == "magnetometer.heading":
                mag = profile["magnetometer"]
                sigma = float(mag["heading_sigma_deg"])
                s_hi = float(mag["hard_iron_sigma_fraction"])
                drawn = entry.get("drawn_hard_iron_fraction")
                if not (isinstance(drawn, list) and len(drawn) == 2) or any(
                        abs(float(b)) > BIAS_SIGMAS * s_hi + 1e-12 for b in drawn):
                    raise _Violation(f"{label}: drawn hard-iron pair {drawn!r} is outside "
                                     f"{BIAS_SIGMAS:g} sigma of {s_hi:.4g}")
                psi = np.radians(truth)
                biased = np.degrees(np.arctan2(np.sin(psi) - float(drawn[1]),
                                               np.cos(psi) + float(drawn[0])))
                residual = _wrap180(meas - biased)
                ratios[label] = _std_ok(residual, sigma, label, problems)
                _mean_ok(residual, 0.0, 0.0, sigma, label, problems)
            else:
                raise _Violation(f"{label}: instrument {instrument!r} is not one this "
                                 f"check knows how to grade")
    except _Violation as exc:
        return CheckResult(FAIL, str(exc), failure="instruments.residual")

    if problems:
        return CheckResult(FAIL, f"{len(problems)} channel statistic(s) off the profile: "
                                 + "; ".join(problems[:3]), failure="instruments.residual")
    worst = max(ratios.items(), key=lambda kv: abs(math.log(kv[1])) if kv[1] > 0 else 0.0) \
        if ratios else ("none", 1.0)
    return CheckResult(PASS, f"{len(entries)} measured channels graded against profile "
                             f"{profile.get('name')!r} over {n} samples; residual std "
                             f"within {1 / SIGMA_FACTOR:.2f}..{SIGMA_FACTOR:.2f} x the "
                             f"stated sigma on every channel (worst {worst[0]} at "
                             f"{worst[1]:.2f} x); biases within bounds; GPS hold exact")


# -- R2: the FDM-rate checks ---------------------------------------------------------

def overlapping_allan_deviation(rate: np.ndarray, dt: float, m: int) -> Tuple[float, int]:
    """The OVERLAPPING Allan deviation of a rate series at tau = m dt,
    from the definition over the integrated series theta = cumsum(rate) dt:
    sigma^2 = 1 / (2 tau^2 (N - 2m)) sum_{k=0}^{N-2m-1} (theta_{k+2m} -
    2 theta_{k+m} + theta_k)^2, N the length of theta (the series with a
    leading 0). Returns (adev, N - 2m); NaN when fewer than one term."""
    rate = np.asarray(rate, dtype=float)
    theta = np.concatenate([[0.0], np.cumsum(rate) * dt])
    n, m = len(theta), int(m)
    terms = n - 2 * m
    if terms < 1:
        return math.nan, terms
    tau = m * dt
    second = theta[2 * m:] - 2.0 * theta[m:n - m] + theta[:n - 2 * m]
    return float(math.sqrt(np.sum(second ** 2) / (2.0 * tau * tau * terms))), terms


def _load_instruments(manifest: Optional[Mapping[str, Any]], run_dir):
    """The manifest's instruments block and the file's arrays, or the
    NOT RUN / FAIL that says why not. Reads the run's manifest.json (the
    run manifest) when no manifest is given."""
    if run_dir is None:
        return None, None, CheckResult(NOT_RUN, "no run directory")
    run_dir = Path(run_dir)
    block = manifest.get("instruments") if isinstance(manifest, Mapping) else None
    if block is None:
        for name in ("manifest.json", "run.json"):
            path = run_dir / name
            if path.is_file():
                try:
                    block = json.loads(path.read_text(encoding="utf-8")).get("instruments")
                except (OSError, ValueError):
                    block = None
                if block is not None:
                    break
    if not isinstance(block, dict):
        return None, None, CheckResult(NOT_RUN, "the manifest carries no instruments block "
                                                "(a run before the FDM-rate observer)")
    if block.get("file") is None:
        return block, None, CheckResult(NOT_RUN, "no instrument stated: the ideal set at the CG "
                                                 f"writes no {INSTRUMENTS_FILE} and grades nothing")
    if block.get("instruments_version") != INSTRUMENTS_READS_VERSION:
        return block, None, CheckResult(FAIL, f"instruments block version "
                                              f"{block.get('instruments_version')!r} (this build "
                                              f"reads {INSTRUMENTS_READS_VERSION})",
                                        failure="instruments.file")
    path = run_dir / str(block["file"])
    if not path.is_file():
        return block, None, CheckResult(FAIL, f"{path} is absent although the manifest names it",
                                        failure="instruments.file")
    raw = path.read_bytes()
    if block.get("sha256") != hashlib.sha256(raw).hexdigest():
        return block, None, CheckResult(FAIL, f"{path.name} does not hash to the sha256 the "
                                              f"manifest recorded", failure="instruments.file")
    try:
        import io

        with np.load(io.BytesIO(raw)) as data:
            arrays = {name: np.asarray(data[name], dtype=float) for name in data.files}
    except (OSError, ValueError) as exc:
        return block, None, CheckResult(FAIL, f"{path.name} is unreadable: {exc}",
                                        failure="instruments.file")
    missing = [c for c in block.get("columns", []) if c not in arrays]
    if missing or "t" not in arrays:
        return block, None, CheckResult(FAIL, f"{path.name} lacks columns {missing or ['t']}",
                                        failure="instruments.file")
    return block, arrays, None


def check_allan(manifest: Optional[Mapping[str, Any]], run_dir) -> CheckResult:
    """The IMU residuals' overlapping Allan deviation against the profile's
    white density at the short taus (see the module docstring)."""
    block, arrays, problem = _load_instruments(manifest, run_dir)
    if problem is not None:
        return problem
    imu = (block.get("instruments") or {}).get("imu") or {}
    if not imu.get("stated"):
        return CheckResult(NOT_RUN, "the IMU is unstated (ideal at the CG): no noise declared, "
                                    "nothing for an Allan deviation to recover")
    profile = (block.get("profiles") or {}).get("imu") or {}
    try:
        n_acc = float(profile["imu"]["accelerometer"]["velocity_random_walk_mps_per_sqrt_h"]) / 60.0
        n_gyr = float(profile["imu"]["gyro"]["angle_random_walk_deg_per_sqrt_h"]) / 60.0
        tau_b = float(profile["imu"]["gyro"]["correlation_time_s"])
    except (KeyError, TypeError, ValueError) as exc:
        return CheckResult(FAIL, f"the IMU profile in the manifest lacks a term: {exc!r}",
                           failure=FAIL_ALLAN)
    t = arrays["t"]
    if len(t) < 2:
        return CheckResult(NOT_RUN, f"{len(t)} sample(s): no series")
    dt = float(np.median(np.diff(t)))
    rate_hz = float(block.get("rate_hz", 0.0))
    if rate_hz > 0.0 and abs(dt * rate_hz - 1.0) > 1e-6:
        return CheckResult(FAIL, f"the file's sample spacing {dt:.6g} s is not the manifest's "
                                 f"rate {rate_hz:g} Hz", failure=FAIL_ALLAN)
    series = {}
    for axis in "xyz":
        series[f"meas_f_{axis}_mps2"] = (arrays[f"meas_f_{axis}_mps2"] - arrays[f"truth_f_{axis}_mps2"], n_acc)
    for name, truth in (("meas_p_dps", "truth_p_rad_s"), ("meas_q_dps", "truth_q_rad_s"),
                        ("meas_r_dps", "truth_r_rad_s")):
        series[name] = (arrays[name] - np.degrees(arrays[truth]), n_gyr)
    graded = 0
    worst = (0.0, "none", 0.0)
    problems = []
    for name, (residual, density) in series.items():
        if density <= 0.0:
            continue
        for m in ALLAN_SHORT_M:
            adev, terms = overlapping_allan_deviation(residual, dt, m)
            if terms < ALLAN_MIN_SAMPLES:
                continue
            expected = density / math.sqrt(m * dt)
            agreement = abs(adev / expected - 1.0)
            graded += 1
            if agreement > worst[0]:
                worst = (agreement, name, m * dt)
            if not agreement < ALLAN_TOL:
                problems.append(f"{name} at tau {m * dt:.4g} s: adev {adev:.4g} against "
                                f"N/sqrt(tau) {expected:.4g} ({agreement:.3f} off)")
    if graded == 0:
        return CheckResult(NOT_RUN, f"no residual with a declared density and at least "
                                    f"{ALLAN_MIN_SAMPLES} terms ({len(t)} samples)")
    span = float(t[-1] - t[0])
    bk = (f"B and K NOT RUN: the run spans {span:.1f} s, under {ALLAN_BK_RUN_MULTIPLE:g} x the "
          f"correlation time {tau_b:g} s"
          if span < ALLAN_BK_RUN_MULTIPLE * tau_b else
          f"B and K within reach ({span:.1f} s >= {ALLAN_BK_RUN_MULTIPLE:g} x {tau_b:g} s); "
          f"estimated by the producer, not graded here")
    if problems:
        return CheckResult(FAIL, f"{len(problems)} Allan point(s) off the declared white "
                                 f"density (tolerance {ALLAN_TOL}): " + "; ".join(problems[:3])
                                 + f"; {bk}", failure=FAIL_ALLAN)
    return CheckResult(PASS, f"{graded} overlapping Allan points on {len(series)} IMU residuals "
                             f"over {len(t)} samples at {1.0 / dt:g} Hz agree with N/sqrt(tau) "
                             f"within {ALLAN_TOL} (worst {worst[1]} at tau {worst[2]:.4g} s, "
                             f"{worst[0]:.3f} off); {bk}")


def _own_rotation(roll_deg, pitch_deg, yaw_deg) -> np.ndarray:
    """R_body_to_NED as columns of the axis-by-axis rotation (the same
    second derivation _rotate_body_to_ned uses), for the least squares."""
    return np.array([_rotate_body_to_ned(e, roll_deg, pitch_deg, yaw_deg)
                     for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]).T


def _skew(v: np.ndarray) -> np.ndarray:
    return np.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])


def check_lever_arm(manifest: Optional[Mapping[str, Any]], run_dir) -> CheckResult:
    """The GPS antenna arm recovered from the fix residuals and the IMU arm
    from the specific-force difference, each against the declared arm
    (see the module docstring)."""
    block, arrays, problem = _load_instruments(manifest, run_dir)
    if problem is not None:
        return problem
    instruments = block.get("instruments") or {}
    profiles = block.get("profiles") or {}
    t = arrays["t"]
    if len(t) < 3:
        return CheckResult(NOT_RUN, f"{len(t)} sample(s): no track")
    dt = float(np.median(np.diff(t)))
    lines = []
    problems = []
    graded = 0
    gps = instruments.get("gps") or {}
    if gps.get("stated"):
        at = np.flatnonzero(arrays["gps_fix"] > 0.5)
        if at.size < ALLAN_MIN_SAMPLES:
            lines.append(f"GPS arm NOT RUN: {at.size} fixes (needs {ALLAN_MIN_SAMPLES})")
        else:
            lat = arrays["truth_lat_deg"][at]
            d = np.empty((at.size, 3))
            for k, i in enumerate(at):
                r_m, r_n = _radii(lat[k])
                d[k, 0] = math.radians(arrays["meas_lat_deg"][i] - arrays["truth_lat_deg"][i]) * r_m
                d[k, 1] = (math.radians(arrays["meas_lon_deg"][i] - arrays["truth_lon_deg"][i])
                           * r_n * math.cos(math.radians(lat[k])))
                d[k, 2] = arrays["truth_alt_m"][i] - arrays["meas_alt_m"][i]
            recovered = np.zeros(3)
            for k, i in enumerate(at):
                recovered += _own_rotation(arrays["truth_roll_deg"][i], arrays["truth_pitch_deg"][i],
                                           arrays["truth_heading_deg"][i]).T @ d[k]
            recovered /= at.size
            declared = np.asarray(gps.get("lever_arm_m", [0.0, 0.0, 0.0]), dtype=float)
            g = (profiles.get("gps") or {}).get("gps") or {}
            sigma = max(float(g.get("north_east_sigma_m", 0.0)), float(g.get("vertical_sigma_m", 0.0)))
            tol = LEVER_ARM_TOL_M + 4.0 * sigma / math.sqrt(at.size)
            error = float(np.linalg.norm(recovered - declared))
            graded += 1
            lines.append(f"GPS arm recovered {np.round(recovered, 3).tolist()} m from {at.size} "
                         f"fixes against the declared {declared.tolist()} (|error| {error:.3f} m, "
                         f"tolerance {tol:.3f} m)")
            if error > tol:
                problems.append(f"GPS arm {error:.3f} m off (tolerance {tol:.3f} m)")
    imu = instruments.get("imu") or {}
    if imu.get("stated"):
        omega = np.stack([arrays["truth_p_rad_s"], arrays["truth_q_rad_s"], arrays["truth_r_rad_s"]], axis=1)
        omega_dot = np.gradient(omega, dt, axis=0)               # central differences, the checker's own
        diff = np.stack([arrays[f"truth_f_{a}_mps2"] - arrays[f"truth_f_cg_{a}_mps2"] for a in "xyz"], axis=1)
        interior = slice(1, len(t) - 1)
        ata = np.zeros((3, 3))
        atb = np.zeros(3)
        for i in range(1, len(t) - 1):
            a_i = _skew(omega_dot[i]) + _skew(omega[i]) @ _skew(omega[i])
            ata += a_i.T @ a_i
            atb += a_i.T @ diff[i]
        declared = np.asarray(imu.get("lever_arm_m", [0.0, 0.0, 0.0]), dtype=float)
        excitation = float(np.sqrt(np.trace(ata) / max(1, len(t) - 2)))
        if excitation < 1e-6:
            lines.append("IMU arm NOT RUN: the track carries no rotation (the rotational terms "
                         "vanish, so the arm is unobservable)")
        else:
            try:
                recovered = np.linalg.solve(ata + 1e-12 * np.eye(3), atb)
            except np.linalg.LinAlgError:
                recovered = np.full(3, np.nan)
            error = float(np.linalg.norm(recovered - declared))
            residual = float(np.sqrt(np.mean(np.sum(diff[interior] ** 2, axis=1))))
            # The finite-difference omega_dot differs from JSBSim's by the
            # rate's own curvature over 2 dt; the tolerance carries the
            # declared length times that share of the excitation.
            tol = LEVER_ARM_TOL_M + 0.05 * float(np.linalg.norm(declared)) + 0.05
            graded += 1
            lines.append(f"IMU arm recovered {np.round(recovered, 3).tolist()} m from the "
                         f"specific-force difference (rms {residual:.4g} m/s^2, excitation "
                         f"{excitation:.3g} 1/s^2) against the declared {declared.tolist()} "
                         f"(|error| {error:.3f} m, tolerance {tol:.3f} m)")
            if not error <= tol:
                problems.append(f"IMU arm {error:.3f} m off (tolerance {tol:.3f} m)")
    if graded == 0:
        return CheckResult(NOT_RUN, "; ".join(lines) or "neither the GPS nor the IMU is stated")
    if problems:
        return CheckResult(FAIL, "; ".join(problems) + " -- " + "; ".join(lines), failure=FAIL_LEVER_ARM)
    return CheckResult(PASS, "; ".join(lines))
