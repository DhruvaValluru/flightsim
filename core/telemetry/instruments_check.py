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

NOT CLAIMED: that the profile's numbers describe any real instrument (the
check grades the file against the profile it carries, not the profile
against the world); that the drawn biases were drawn from the stated seed
(the check reads the draws the file recorded and bounds them; the seed
derivation is graded by tests/test_instruments.py); any distribution shape
beyond the second moment (no chi-square, no normality test).
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
