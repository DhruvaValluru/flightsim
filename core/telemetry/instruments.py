"""Instrument models: measured channels beside the recorded truth (gap M-data, PHASE3_GAP_ANALYSIS section 5.3).

The recorder writes what JSBSim knows (``telemetry.json``). A real data
collection never sees that: it sees an IMU, a GPS receiver, a pitot-static
system and a magnetometer, each with its own errors. This module reads the
recorded columns AFTER the run, as an observer, and writes
``telemetry_measured.json`` beside them: for every truth column the profile
covers, a ``<truth>_meas`` column with the truth beside it, the profile (with
its sources), the seed streams used, and the ``instruments.profile`` record
(:class:`core.records.AppliedVariable`). It writes no JSBSim property and
changes no trajectory.

The models, per instrument (every constant is in the profile, every
reference is in the profile's ``references`` and repeated in the record):

* **IMU** (accelerometer and gyro, per body axis), the IEEE Std 952-2020
  Allan-variance terms: a CONSTANT BIAS drawn once per run from the stated
  bias-repeatability sigma; WHITE NOISE from the random-walk density (VRW in
  m/s/sqrt(h), ARW in deg/sqrt(h)), converted to a sigma at the recorder's
  sample interval as ``sigma = density / sqrt(dt)`` (Woodman 2007); BIAS
  INSTABILITY as a first-order Gauss-Markov process with the stated sigma
  and correlation time (El-Sheimy et al. 2008), ``x[i] = a x[i-1] +
  sqrt(1 - a^2) sigma w``, ``a = exp(-dt / tau)``, started stationary.
  The accelerometer "truth" is the load factor JSBSim's own accelerometer
  recorded (``accelerations/Nz`` -> ``n_z``, in g), so the error terms in
  m/s^2 are divided by g0 = 9.80665 to ride on that channel. WHAT IS
  DERIVED: nothing -- the channel is JSBSim's, in JSBSim's unit. The x and
  y accelerometer channels (``n_x``, ``n_y``) and the yaw gyro
  (``yaw_rate_dps``) are read by the state but are NOT in the recorder's
  default channel set; they are modelled only when the telemetry carries
  them and listed under ``absent`` otherwise (the draws for them are made
  regardless, so a channel's noise does not change when another channel
  appears).
* **GPS**: per-axis white noise on north/east (``north_east_sigma_m``),
  down (``vertical_sigma_m``) and the three velocities
  (``velocity_sigma_mps``); a FIX every ``1 / update_rate_hz`` seconds and a
  ZERO-ORDER HOLD between fixes at the recorder's rate (5 Hz fixes at the
  10 Hz recorder: every second sample repeats the last fix; ``gps_fix``
  marks the fix samples); the LEVER ARM ``measured = CG + R_body_to_NED *
  antenna_offset_body`` (Titterton & Weston 2004), the north/east offsets
  converted to degrees with the WGS 84 radii of curvature at the truth
  latitude. The velocity lever-arm term (omega x arm) is NOT applied: the
  yaw rate is not a recorded column.
* **Pitot-static**: CAS and pressure altitude through a first-order lag
  with time constant tau, discretised backward-Euler (``y[i] = y[i-1] +
  dt / (tau + dt) * (x[i] - y[i-1])``, ``y[0] = x[0]``), plus white noise.
  The pressure-altitude truth is ``pressure_altitude_m`` when the telemetry
  carries it, else ``altitude_m`` with the ISA assumption STATED in the
  channel entry.
* **Magnetometer**: heading from the level horizontal field with a HARD-IRON
  offset (``bx``, ``by``, each drawn once per run as a fraction of the
  horizontal field, Caruso 2000): ``psi_meas = atan2(sin psi - by, cos psi
  + bx)`` plus white noise, wrapped to [0, 360).

NAMING: every measured column is ``<truth>_meas``, with one stated
exception: two instruments measure ``altitude_m`` (the GPS geometrically,
the static port barometrically), so those two are ``altitude_m_gps_meas``
and ``altitude_m_baro_meas``.

DETERMINISM: every draw comes from the run seed through the named streams
``imu``, ``gps``, ``pitot_static`` and ``magnetometer``
(:mod:`core.experiments.seeds`), in a fixed order, so the same seed and
profile give a byte-identical file (tested).

THE FDM-RATE PATH (R2, blueprint section 2). :class:`InstrumentObserver`
is the same four models run INSIDE the step loop, once per FDM step
(``rate_basis`` 'fdm loop'), built from the spec's ``instruments`` block
(one profile and one lever arm per instrument; an unstated instrument is
the ideal profile at the CG). Per step it reads JSBSim's own
accelerometer (``accelerations/Nx, Ny, Nz``), body rates and angular
accelerations, position, attitude, CAS and heading, and writes nothing
back. The IMU's truth is the SPECIFIC FORCE at the sensor, in body axes
(x forward, y right, z down):

    f = g0 (N_x, N_y, -N_z) + omega_dot x r + omega x (omega x r)

with NO gravity term (JSBSim's N is the total body force over the weight;
FGAuxiliary's vPilotAccel has the same form, read here) and the N_z SIGN
FLIP stated: JSBSim's Nz is positive UP (0.997 g in level flight) while
the sensor's z axis points down, so f_z = -g0 N_z; the measured load
factor is meas_n_z = -f_z_meas / g0. Measured (tests): at r = 0 the
specific force equals g0 (N_x, N_y, -N_z) exactly, and at r = the
eyepoint offset it equals g0 times JSBSim's own ``n-pilot-*-norm`` (which
carries JSBSim's rotational terms) within the numerical tolerance stated
there, while a finite difference of the recorded rates reproduces the
omega_dot x r term. GPS fixes on the receiver's clock at the profile's
rate, HELD between fixes, at the antenna (CG + R_body_to_NED r_gps);
pitot-static CAS through the first-order lag plus a position-error table
in knots (default empty = zero, stated); the magnetometer as a TILTED
DIPOLE from the IGRF-13 degree-1 coefficients (g10 -29404.8, g11 -1450.9,
h11 4652.5 nT at 2020.0, verified here from the fetched IGRF13.shc),
rotated into the body, hard-iron offsets added, levelled with the truth
attitude: the sensor reads MAGNETIC heading (true minus the dipole's
declination), so ``meas_heading_deg`` differs from the true heading by
the declination the record states. Every draw comes from the five named
streams ``imu``, ``gps``, ``pitot_static``, ``magnetometer``,
``null_test`` (never the declared-but-unused ``sensor_noise``). The 10 Hz
recorder samples the LATEST measured value (Recorder(measured=observer)),
so frames carry meas_* beside truth; ``instruments.npz`` beside the run
holds every truth_* and meas_* column at the FDM rate, byte-deterministic.
The Allan self-report (the NON-overlapping deviation, :func:`allan_deviation`)
grades the white term N against the stated density within
:data:`ALLAN_TOL`; B and K are NOT RUN when the run is shorter than 100
correlation times (:data:`ALLAN_BK_RUN_MULTIPLE`), and the check module
(core/telemetry/instruments_check.py) uses the OVERLAPPING form so the
two agree by arithmetic, not by copy.

NOT CLAIMED (both paths): stated class models -- no device is calibrated
and every profile number is 'unverified here'; the Allan check measures
that the model produced the noise it declares, not that a real sensor
has it; B and K on a 60 s run; the magnetometer is a tilted dipole with
a few degrees of declination error against IGRF/WMM (geodetic latitude
taken as geocentric, no secular variation, no soft iron); the pitot-static
and magnetometer lever arms are carried, not applied; GPS multipath,
ionosphere, clock and geometry; host-flight instruments are post-hoc at
the recorded rate (the engine side is P9's). Also, for the recorded-rate
path: scale-factor and misalignment errors; g-sensitivity;
quantisation; temperature effects; the rate random walk (the third
IEEE 952 term); GPS multipath, ionospheric or clock errors (only a white
per-axis sigma); any satellite geometry; the velocity lever-arm term;
soft-iron, tilt and declination for the magnetometer (the truth heading
is TRUE heading and the field is taken level); air-data position error;
any correlation between instruments; any fidelity of the profile numbers,
each of which the profile cites as 'unverified here'; any per-frame key
(the measured file is per step, not attached to the capture frames).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from ..experiments.seeds import DERIVATION, derive, generator
from ..records import AppliedVariable, Model, NullTest, Readback, records_block

REPO = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO / "assets" / "instrument_profiles"
DEFAULT_PROFILE = "ideal"
MEASURED_FILE = "telemetry_measured.json"
#: Bumped when a key is added or renamed; the check refuses by name.
MEASURED_VERSION = 1
RECORD_NAME = "instruments.profile"
MODEL = "IEEE 952 IMU + GPS + pitot-static + magnetometer error models"
#: Standard gravity, the g of JSBSim's load-factor channels.
G0 = 9.80665
#: WGS 84.
WGS84_A = 6378137.0
WGS84_E2 = 6.69437999014e-3
#: The seed streams the models draw from, in the order they are drawn.
STREAMS = ("imu", "gps", "pitot_static", "magnetometer")
#: R2: the FDM-rate observer's streams -- the four above and the null
#: test's own (the estimator self-check's synthetic stream).
OBSERVER_STREAMS = ("imu", "gps", "pitot_static", "magnetometer", "null_test")
#: The two rates an instrument model can run at, named in every record.
FDM_RATE_BASIS = "fdm loop"
RECORDED_RATE_BASIS = "recorded telemetry, 10 Hz"
#: The FDM-rate file beside the run, and its version (refused by name when unknown).
INSTRUMENTS_FILE = "instruments.npz"
INSTRUMENTS_VERSION = 1
#: A lever arm longer than this is not a sensor on the airframe (the
#: B747's half-span is 32 m and its length 70 m): refused instrument.lever_arm.
LEVER_ARM_MAX_M = 80.0
#: The Allan self-report's agreement bound on the white term: |adev(tau) /
#: (N / sqrt(tau)) - 1| < 0.25 at short tau (the blueprint's clause).
ALLAN_TOL = 0.25
#: B and K are NOT RUN unless the run spans at least this many
#: correlation times (a bias instability shows as the flat floor of the
#: Allan curve near tau_B, which a shorter run never reaches).
ALLAN_BK_RUN_MULTIPLE = 100.0
#: The cluster counts (tau = m dt) the short-tau agreement is taken at.
ALLAN_SHORT_M = (1, 2, 4)
#: Fewer clusters than this make no Allan statistic (NOT RUN).
ALLAN_MIN_CLUSTERS = 30
#: The IGRF-13 degree-1 (dipole) coefficients at 2020.0, nT, verified here
#: from the fetched IGRF13.shc (docs/ADVANCEMENTS_BLUEPRINT.md section 2),
#: and the IGRF reference radius.
IGRF13_G10_NT = -29404.8
IGRF13_G11_NT = -1450.9
IGRF13_H11_NT = 4652.5
IGRF_REFERENCE_RADIUS_M = 6371200.0
#: The null test's threshold on the residual std in units of the stated
#: sigma: a stated instrument reaches when the ratio is at least 0.75 (the
#: within-25 % agreement itself is recorded per channel and pinned by the
#: tests); the ideal instrument measures 0 and is honestly not ok.
NULL_RATIO_THRESHOLD = 0.75
#: The null test's threshold on the normalised residual RMS (dimensionless:
#: every channel's residual divided by its stated sigma). An ideal profile
#: measures 0 by construction; any profile with noise measures about 1.
NULL_THRESHOLD = 0.5

#: The profile's blocks and every numeric key each must carry.
PROFILE_KEYS: Dict[str, Tuple[str, ...]] = {
    "imu.accelerometer": ("bias_repeatability_mg", "velocity_random_walk_mps_per_sqrt_h",
                          "bias_instability_mg", "correlation_time_s"),
    "imu.gyro": ("bias_repeatability_deg_per_h", "angle_random_walk_deg_per_sqrt_h",
                 "bias_instability_deg_per_h", "correlation_time_s"),
    "gps": ("north_east_sigma_m", "vertical_sigma_m", "velocity_sigma_mps",
            "update_rate_hz"),
    "pitot_static": ("cas_sigma_kt", "cas_lag_s", "pressure_altitude_sigma_m",
                     "pressure_altitude_lag_s"),
    "magnetometer": ("hard_iron_sigma_fraction", "heading_sigma_deg"),
}

#: The channel table: (truth column, measured column, instrument, axis,
#: unit). The truth column is a RECORDED column of telemetry.json; a truth
#: the recording lacks is listed under ``absent`` in the file, never
#: invented.
CHANNELS: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("n_x", "n_x_meas", "imu.accelerometer", "x", "g"),
    ("n_y", "n_y_meas", "imu.accelerometer", "y", "g"),
    ("n_z", "n_z_meas", "imu.accelerometer", "z", "g"),
    ("roll_rate_dps", "roll_rate_dps_meas", "imu.gyro", "x", "deg/s"),
    ("pitch_rate_dps", "pitch_rate_dps_meas", "imu.gyro", "y", "deg/s"),
    ("yaw_rate_dps", "yaw_rate_dps_meas", "imu.gyro", "z", "deg/s"),
    ("lat_deg", "lat_deg_meas", "gps.position", "north", "deg"),
    ("lon_deg", "lon_deg_meas", "gps.position", "east", "deg"),
    ("altitude_m", "altitude_m_gps_meas", "gps.position", "down", "m"),
    ("v_north_mps", "v_north_mps_meas", "gps.velocity", "north", "m/s"),
    ("v_east_mps", "v_east_mps_meas", "gps.velocity", "east", "m/s"),
    ("v_down_mps", "v_down_mps_meas", "gps.velocity", "down", "m/s"),
    ("cas_kt", "cas_kt_meas", "pitot_static.airspeed", "", "kt"),
    ("pressure_altitude_m", "altitude_m_baro_meas", "pitot_static.altitude", "", "m"),
    ("heading_deg", "heading_deg_meas", "magnetometer.heading", "", "deg"),
)
#: The attitude and time columns every instrument needs.
ATTITUDE_COLUMNS = ("t", "roll_deg", "pitch_deg", "heading_deg")
#: The ISA stand-in for a pressure-altitude truth the recording lacks.
BARO_FALLBACK = ("pressure_altitude_m", "altitude_m")


class InstrumentProfileError(Exception):
    constraint = "instruments.profile"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"instruments.profile: {message}")


@dataclass(frozen=True)
class InstrumentProfile:
    name: str
    basis: str
    source: str
    references: Tuple[str, ...]
    accelerometer: Dict[str, float]
    gyro: Dict[str, float]
    gps: Dict[str, Any]
    pitot_static: Dict[str, float]
    magnetometer: Dict[str, float]
    sha256: str = ""
    path: str = ""

    @property
    def is_ideal(self) -> bool:
        """Every error term zero: the truth is the measurement."""
        blocks = (self.accelerometer, self.gyro,
                  {k: v for k, v in self.pitot_static.items()
                   if k != "position_error_table_kt"},
                  self.magnetometer,
                  {k: v for k, v in self.gps.items()
                   if k not in ("update_rate_hz", "antenna_offset_body_m")})
        terms = [v for block in blocks for k, v in block.items()
                 if k != "correlation_time_s"]
        terms += list(self.gps["antenna_offset_body_m"])
        terms += [d for _, d in self.pitot_static.get("position_error_table_kt", [])]
        return all(float(v) == 0.0 for v in terms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "basis": self.basis, "source": self.source,
            "references": list(self.references),
            "imu": {"accelerometer": dict(self.accelerometer), "gyro": dict(self.gyro)},
            "gps": {**self.gps, "antenna_offset_body_m": list(self.gps["antenna_offset_body_m"])},
            "pitot_static": {**self.pitot_static,
                             "position_error_table_kt": [list(r) for r in self.pitot_static.get(
                                 "position_error_table_kt", [])]},
            "magnetometer": dict(self.magnetometer),
            "sha256": self.sha256, "path": self.path,
        }


def available_profiles(profile_dir: Optional[Path] = None) -> List[str]:
    return sorted(p.stem for p in Path(profile_dir or PROFILE_DIR).glob("*.json"))


def profile_from_dict(data: Mapping[str, Any], name: str = "", sha256: str = "",
                      path: str = "") -> InstrumentProfile:
    """A profile from its JSON shape, or a named ``instruments.profile`` refusal."""
    if not isinstance(data, Mapping):
        raise InstrumentProfileError(f"profile {name!r} is not a JSON object")
    stated = str(data.get("name", ""))
    if name and stated != name:
        raise InstrumentProfileError(
            f"profile file {name!r} names itself {stated!r}; the file stem is the name")
    if not str(data.get("source", "")).strip():
        raise InstrumentProfileError(
            f"profile {stated!r} cites no source; an error model with no stated "
            f"provenance is a guess dressed as an instrument")
    references = data.get("references")
    if not isinstance(references, list) or not references \
            or not all(isinstance(r, str) and r.strip() for r in references):
        raise InstrumentProfileError(f"profile {stated!r} lists no references")
    blocks: Dict[str, Dict[str, float]] = {}
    for dotted, keys in PROFILE_KEYS.items():
        block: Any = data
        for part in dotted.split("."):
            block = block.get(part) if isinstance(block, Mapping) else None
        if not isinstance(block, Mapping):
            raise InstrumentProfileError(f"profile {stated!r} has no {dotted!r} block")
        numbers = {}
        for key in keys:
            value = block.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value) or value < 0.0:
                raise InstrumentProfileError(
                    f"profile {stated!r}: {dotted}.{key} must be a finite number >= 0, "
                    f"got {value!r}")
            numbers[key] = float(value)
        unknown = sorted(set(block) - set(keys) - {"antenna_offset_body_m",
                                                   "position_error_table_kt"})
        if unknown:
            raise InstrumentProfileError(
                f"profile {stated!r}: {dotted} has keys this build does not model: "
                f"{unknown}")
        blocks[dotted] = numbers
    for dotted in ("imu.accelerometer", "imu.gyro"):
        if blocks[dotted]["correlation_time_s"] <= 0.0:
            raise InstrumentProfileError(
                f"profile {stated!r}: {dotted}.correlation_time_s must be > 0")
    if blocks["gps"]["update_rate_hz"] <= 0.0:
        raise InstrumentProfileError(f"profile {stated!r}: gps.update_rate_hz must be > 0")
    arm = data["gps"].get("antenna_offset_body_m")
    if not isinstance(arm, list) or len(arm) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in arm):
        raise InstrumentProfileError(
            f"profile {stated!r}: gps.antenna_offset_body_m must be [x, y, z] metres "
            f"in body axes (x forward, y right, z down)")
    gps = dict(blocks["gps"])
    gps["antenna_offset_body_m"] = [float(v) for v in arm]
    # R2: the optional position-error table, [[cas_kt, delta_kt], ...] in
    # ascending CAS (delta is ADDED to the lagged CAS; linear between rows,
    # held beyond the ends); absent = an empty table = zero, stated.
    table = data["pitot_static"].get("position_error_table_kt", [])
    if not isinstance(table, list) or not all(
            isinstance(row, list) and len(row) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in row) for row in table) or any(
            table[i][0] >= table[i + 1][0] for i in range(len(table) - 1)):
        raise InstrumentProfileError(
            f"profile {stated!r}: pitot_static.position_error_table_kt must be "
            f"[[cas_kt, delta_kt], ...] with ascending CAS")
    pitot = dict(blocks["pitot_static"])
    pitot["position_error_table_kt"] = [[float(c), float(d)] for c, d in table]
    return InstrumentProfile(
        name=stated, basis=str(data.get("basis", "synthetic")),
        source=str(data["source"]), references=tuple(references),
        accelerometer=blocks["imu.accelerometer"], gyro=blocks["imu.gyro"], gps=gps,
        pitot_static=pitot, magnetometer=blocks["magnetometer"],
        sha256=sha256, path=path)


def load_profile(name: str, profile_dir: Optional[Path] = None) -> InstrumentProfile:
    """A profile by name from ``assets/instrument_profiles``, or a named refusal."""
    directory = Path(profile_dir or PROFILE_DIR)
    path = directory / f"{name}.json"
    if not path.is_file():
        raise InstrumentProfileError(
            f"no instrument profile {name!r} in {directory} (available: "
            f"{', '.join(available_profiles(directory)) or 'none'})")
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise InstrumentProfileError(f"profile {name!r} unreadable: {exc}") from exc
    try:
        relative = str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        relative = str(path)
    return profile_from_dict(data, name=name, sha256=hashlib.sha256(raw).hexdigest(),
                             path=relative)


# -- the error processes -----------------------------------------------------

def gauss_markov(rng: np.random.Generator, n: int, sigma: float, tau_s: float,
                 dt: float) -> np.ndarray:
    """First-order Gauss-Markov bias instability, started stationary.

    The draws are made even when ``sigma`` is 0 so the stream's later
    draws do not move when a term is switched off.
    """
    a = math.exp(-dt / tau_s)
    w = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = sigma * w[0]
    scale = math.sqrt(max(0.0, 1.0 - a * a)) * sigma
    for i in range(1, n):
        x[i] = a * x[i - 1] + scale * w[i]
    return x


def random_walk_sigma(density_per_sqrt_h: float, dt: float) -> float:
    """A random-walk density in <unit>/sqrt(h) -> the white-noise sigma of a
    sample at interval ``dt`` seconds, in <unit>/s: density / 60 / sqrt(dt)."""
    return density_per_sqrt_h / 60.0 / math.sqrt(dt)


def first_order_lag(x: np.ndarray, tau_s: float, dt: float) -> np.ndarray:
    """Backward-Euler first-order lag, ``y[0] = x[0]``; tau 0 is the identity."""
    if tau_s <= 0.0:
        return np.array(x, dtype=float)
    alpha = dt / (tau_s + dt)
    y = np.empty(len(x))
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = y[i - 1] + alpha * (x[i] - y[i - 1])
    return y


def body_to_ned(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """R_body_to_NED for the ZYX (yaw, pitch, roll) Euler sequence."""
    sr, cr = math.sin(math.radians(roll_deg)), math.cos(math.radians(roll_deg))
    sp, cp = math.sin(math.radians(pitch_deg)), math.cos(math.radians(pitch_deg))
    sy, cy = math.sin(math.radians(yaw_deg)), math.cos(math.radians(yaw_deg))
    return np.array([
        [cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy],
        [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],
        [-sp, sr * cp, cr * cp],
    ])


def radii_of_curvature(lat_deg: float) -> Tuple[float, float]:
    """WGS 84 meridional (north) and prime-vertical (east) radii, metres."""
    s = math.sin(math.radians(lat_deg))
    denom = 1.0 - WGS84_E2 * s * s
    r_n = WGS84_A / math.sqrt(denom)
    r_m = WGS84_A * (1.0 - WGS84_E2) / (denom ** 1.5)
    return r_m, r_n


def hard_iron_heading(heading_deg: np.ndarray, bx: float, by: float) -> np.ndarray:
    """Heading from a level field with a hard-iron offset, degrees [0, 360)."""
    psi = np.radians(heading_deg)
    return np.degrees(np.arctan2(np.sin(psi) - by, np.cos(psi) + bx)) % 360.0


def gps_fix_mask(t: np.ndarray, update_rate_hz: float) -> np.ndarray:
    """1 at the samples where a new fix arrives: the first sample, then
    every time ``1 / update_rate_hz`` seconds have elapsed since the last
    fix's due time (fixes are on the receiver's own clock, not the
    sample's)."""
    period = 1.0 / update_rate_hz
    mask = np.zeros(len(t), dtype=int)
    next_fix = float(t[0]) if len(t) else 0.0
    for i in range(len(t)):
        if t[i] >= next_fix - 1e-9:
            mask[i] = 1
            next_fix += period
            while next_fix <= t[i] + 1e-9:         # a gap longer than one period:
                next_fix += period                 # the next fix is the next due time
    return mask


# -- applying a profile --------------------------------------------------------

@dataclass
class MeasuredResult:
    """What :func:`measure` returns: the file's content (None for the ideal
    profile, which writes nothing), the record, and the summary."""

    profile: InstrumentProfile
    record: AppliedVariable
    data: Optional[Dict[str, Any]]
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def measured_columns(self) -> List[str]:
        return [] if self.data is None else [c["measured"] for c in self.data["channels"]]


def _sigmas(profile: InstrumentProfile, dt: float) -> Dict[str, Dict[str, float]]:
    """Every channel's white-noise sigma (in the channel's unit) and the
    bias terms, from the profile at the recorder's interval."""
    acc, gyr = profile.accelerometer, profile.gyro
    ps, mag, gps = profile.pitot_static, profile.magnetometer, profile.gps
    acc_terms = {
        "sigma_white": random_walk_sigma(acc["velocity_random_walk_mps_per_sqrt_h"], dt) / G0,
        "sigma_bias_instability": acc["bias_instability_mg"] / 1000.0,
        "sigma_bias_repeatability": acc["bias_repeatability_mg"] / 1000.0,
        "correlation_time_s": acc["correlation_time_s"],
    }
    gyr_terms = {
        "sigma_white": random_walk_sigma(gyr["angle_random_walk_deg_per_sqrt_h"], dt),
        "sigma_bias_instability": gyr["bias_instability_deg_per_h"] / 3600.0,
        "sigma_bias_repeatability": gyr["bias_repeatability_deg_per_h"] / 3600.0,
        "correlation_time_s": gyr["correlation_time_s"],
    }
    return {
        "imu.accelerometer": acc_terms, "imu.gyro": gyr_terms,
        "gps.position": {"sigma_north_east_m": gps["north_east_sigma_m"],
                         "sigma_down_m": gps["vertical_sigma_m"]},
        "gps.velocity": {"sigma_white": gps["velocity_sigma_mps"]},
        "pitot_static.airspeed": {"sigma_white": ps["cas_sigma_kt"], "lag_s": ps["cas_lag_s"],
                                  "position_error_table_kt": [
                                      list(r) for r in ps.get("position_error_table_kt", [])]},
        "pitot_static.altitude": {"sigma_white": ps["pressure_altitude_sigma_m"],
                                  "lag_s": ps["pressure_altitude_lag_s"]},
        "magnetometer.heading": {"sigma_white": mag["heading_sigma_deg"],
                                 "sigma_hard_iron_fraction": mag["hard_iron_sigma_fraction"]},
    }


def measure(telemetry: Mapping[str, Any], profile: InstrumentProfile, seed: int,
            replicate: int = 0, source: str = "default") -> MeasuredResult:
    """Apply ``profile`` to the recorded columns of a telemetry dict
    (``Recorder.to_dict()`` / telemetry.json).

    ``source`` is the record's provenance word: ``user`` when the profile
    was named on the command line, ``default`` for the default. Every
    draw comes from the run ``seed`` through the four named streams.
    """
    columns = telemetry.get("columns")
    if not isinstance(columns, Mapping) or "t" not in columns:
        raise ValueError("telemetry carries no 't' column; nothing to measure")
    dt = float(telemetry.get("interval_s", 0.0))
    if not dt > 0.0:
        raise ValueError(f"telemetry interval_s {dt!r} is not a positive interval")
    for name in ATTITUDE_COLUMNS:
        if name not in columns:
            raise ValueError(f"telemetry has no {name!r} column; the instruments need "
                             f"the attitude beside the time")
    t = np.asarray(columns["t"], dtype=float)
    n = len(t)
    if n < 2:
        raise ValueError(f"telemetry has {n} sample(s); an instrument model needs a run")
    seeds = derive(int(seed), int(replicate))
    if profile.is_ideal:
        return MeasuredResult(profile, _record(profile, source, seeds, [], {}, 0.0), None,
                              {"normalised_rms": 0.0})

    sigmas = _sigmas(profile, dt)
    roll = np.asarray(columns["roll_deg"], dtype=float)
    pitch = np.asarray(columns["pitch_deg"], dtype=float)
    yaw = np.asarray(columns["heading_deg"], dtype=float)
    out: Dict[str, List[float]] = {"t": [float(v) for v in t]}
    entries: List[Dict[str, Any]] = []
    absent: Dict[str, str] = {}
    draws: Dict[str, Any] = {}
    per_channel_rms: Dict[str, float] = {}
    normalised: List[float] = []

    def add(truth_name: str, measured_name: str, instrument: str, axis: str, unit: str,
            truth: np.ndarray, meas: np.ndarray, sigma_for_null: float,
            extra: Mapping[str, Any]) -> None:
        out[truth_name] = [float(v) for v in truth]
        out[measured_name] = [float(v) for v in meas]
        residual = meas - truth
        if instrument == "magnetometer.heading":
            residual = (residual + 180.0) % 360.0 - 180.0
        rms = float(np.sqrt(np.mean(residual ** 2)))
        per_channel_rms[measured_name] = rms
        if sigma_for_null > 0.0:
            normalised.append(rms / sigma_for_null)
        entries.append({"truth": truth_name, "measured": measured_name,
                        "instrument": instrument, "axis": axis, "unit": unit,
                        "residual_rms": rms, **extra})

    # -- IMU: one stream, the draws in a fixed order (bias x,y,z, then
    #    per axis the Gauss-Markov and the white sequences), for the
    #    accelerometer then the gyro, whether or not the channel exists.
    rng = generator(int(seed), "imu", int(replicate))
    imu_draws: Dict[str, Any] = {}
    for instrument in ("imu.accelerometer", "imu.gyro"):
        terms = sigmas[instrument]
        biases = rng.standard_normal(3) * terms["sigma_bias_repeatability"]
        imu_draws[instrument.split(".")[1] + "_bias"] = [float(b) for b in biases]
        for k, (truth_name, measured_name, inst, axis, unit) in enumerate(
                c for c in CHANNELS if c[2] == instrument):
            gm = gauss_markov(rng, n, terms["sigma_bias_instability"],
                              terms["correlation_time_s"], dt)
            white = rng.standard_normal(n) * terms["sigma_white"]
            if truth_name not in columns:
                absent[truth_name] = ("not a recorded column (core/telemetry/recorder.py "
                                      "DEFAULT_CHANNELS); its draws were made and discarded")
                continue
            truth = np.asarray(columns[truth_name], dtype=float)
            add(truth_name, measured_name, inst, axis, unit, truth,
                truth + biases[k] + gm + white,
                math.hypot(terms["sigma_white"], terms["sigma_bias_instability"]),
                {"drawn_bias": float(biases[k]), **terms})
    draws["imu"] = imu_draws

    # -- GPS: fixes on the receiver's clock, a hold between them, the
    #    antenna where the lever arm puts it.
    rng = generator(int(seed), "gps", int(replicate))
    gps = profile.gps
    arm = np.asarray(gps["antenna_offset_body_m"], dtype=float)
    fix = gps_fix_mask(t, gps["update_rate_hz"])
    pos_names = {c[3]: c for c in CHANNELS if c[2] == "gps.position"}
    vel_names = {c[3]: c for c in CHANNELS if c[2] == "gps.velocity"}
    have_pos = all(pos_names[a][0] in columns for a in ("north", "east", "down"))
    have_vel = all(vel_names[a][0] in columns for a in ("north", "east", "down"))
    pos_truth = {a: np.asarray(columns[pos_names[a][0]], dtype=float)
                 for a in pos_names if pos_names[a][0] in columns}
    vel_truth = {a: np.asarray(columns[vel_names[a][0]], dtype=float)
                 for a in vel_names if vel_names[a][0] in columns}
    pos_meas = {a: np.empty(n) for a in ("north", "east", "down")}
    vel_meas = {a: np.empty(n) for a in ("north", "east", "down")}
    sig_ne, sig_d, sig_v = (gps["north_east_sigma_m"], gps["vertical_sigma_m"],
                            gps["velocity_sigma_mps"])
    last = None
    for i in range(n):
        if fix[i]:
            noise = rng.standard_normal(6)
            if have_pos:
                offset = body_to_ned(roll[i], pitch[i], yaw[i]) @ arm
                lat = pos_truth["north"][i]
                r_m, r_n = radii_of_curvature(lat)
                north_m = offset[0] + sig_ne * noise[0]
                east_m = offset[1] + sig_ne * noise[1]
                down_m = offset[2] + sig_d * noise[2]
                p = (lat + math.degrees(north_m / r_m),
                     pos_truth["east"][i] + math.degrees(
                         east_m / (r_n * math.cos(math.radians(lat)))),
                     pos_truth["down"][i] - down_m)
            else:
                p = (math.nan, math.nan, math.nan)
            v = tuple((vel_truth[a][i] + sig_v * noise[3 + k]) if have_vel else math.nan
                      for k, a in enumerate(("north", "east", "down")))
            last = (p, v)
        p, v = last
        for k, a in enumerate(("north", "east", "down")):
            pos_meas[a][i] = p[k]
            vel_meas[a][i] = v[k]
    out["gps_fix"] = [int(v) for v in fix]
    gps_extra = {"update_rate_hz": gps["update_rate_hz"], "hold": "zero-order between fixes",
                 "fix_column": "gps_fix", "fixes": int(fix.sum())}
    if have_pos:
        # The null test's normaliser for the angular channels: the
        # sigma in degrees at the run's first latitude.
        r_m0, r_n0 = radii_of_curvature(float(pos_truth["north"][0]))
        sigma_deg = {"north": math.degrees(sig_ne / r_m0),
                     "east": math.degrees(sig_ne / (r_n0 * math.cos(
                         math.radians(float(pos_truth["north"][0]))))),
                     "down": sig_d}
        for a in ("north", "east", "down"):
            truth_name, measured_name, inst, axis, unit = pos_names[a]
            add(truth_name, measured_name, inst, axis, unit, pos_truth[a], pos_meas[a],
                sigma_deg[a],
                {**gps_extra, "sigma_white_m": sig_d if a == "down" else sig_ne,
                 "sigma_white": sigma_deg[a],
                 "antenna_offset_body_m": [float(x) for x in arm],
                 "lever_arm": "measured = CG + R_body_to_NED(roll, pitch, heading) * arm; "
                              "north/east in degrees by the WGS 84 radii of curvature "
                              "at the truth latitude; down subtracts from altitude"})
    else:
        for a in ("north", "east", "down"):
            if pos_names[a][0] not in columns:
                absent[pos_names[a][0]] = "not a recorded column; the GPS position needs all three"
    if have_vel:
        for a in ("north", "east", "down"):
            truth_name, measured_name, inst, axis, unit = vel_names[a]
            add(truth_name, measured_name, inst, axis, unit, vel_truth[a], vel_meas[a],
                sig_v, {**gps_extra, "sigma_white": sig_v,
                        "lever_arm": "not applied to velocity (omega x arm needs the yaw "
                                     "rate, which is not a recorded column)"})
    else:
        for a in ("north", "east", "down"):
            if vel_names[a][0] not in columns:
                absent[vel_names[a][0]] = "not a recorded column; the GPS velocity needs all three"
    draws["gps"] = {"fixes": int(fix.sum())}

    # -- pitot-static: a lag, then white noise; two channels, in order.
    rng = generator(int(seed), "pitot_static", int(replicate))
    for truth_name, measured_name, inst, axis, unit in (
            c for c in CHANNELS if c[2].startswith("pitot_static")):
        terms = sigmas[inst]
        white = rng.standard_normal(n) * terms["sigma_white"]
        source_column = truth_name
        note = ""
        if truth_name == BARO_FALLBACK[0] and truth_name not in columns:
            if BARO_FALLBACK[1] not in columns:
                absent[truth_name] = "neither pressure_altitude_m nor altitude_m is recorded"
                continue
            source_column = BARO_FALLBACK[1]
            note = ("ISA assumed: the recording has no pressure_altitude_m, so the "
                    "geometric altitude_m stands in for the pressure altitude")
        elif truth_name not in columns:
            absent[truth_name] = "not a recorded column"
            continue
        truth = np.asarray(columns[source_column], dtype=float)
        lagged = first_order_lag(truth, terms["lag_s"], dt)
        if inst == "pitot_static.airspeed":
            lagged = lagged + position_error_kt(lagged, terms["position_error_table_kt"])
        add(source_column, measured_name, inst, axis, unit, truth, lagged + white,
            terms["sigma_white"],
            {**terms, "discretisation": "backward Euler: y[i] = y[i-1] + dt/(tau+dt) * "
                                        "(x[i] - y[i-1]), y[0] = x[0]",
             **({"note": note} if note else {})})
    draws["pitot_static"] = {"per_run_draws": "none (a lag and white noise only)"}

    # -- magnetometer: the hard-iron pair, then white noise.
    rng = generator(int(seed), "magnetometer", int(replicate))
    terms = sigmas["magnetometer.heading"]
    hard_iron = rng.standard_normal(2) * terms["sigma_hard_iron_fraction"]
    white = rng.standard_normal(n) * terms["sigma_white"]
    truth_name, measured_name, inst, axis, unit = next(
        c for c in CHANNELS if c[2] == "magnetometer.heading")
    truth = np.asarray(columns[truth_name], dtype=float)
    meas = (hard_iron_heading(truth, float(hard_iron[0]), float(hard_iron[1])) + white) % 360.0
    add(truth_name, measured_name, inst, axis, unit, truth, meas, terms["sigma_white"],
        {**terms, "drawn_hard_iron_fraction": [float(hard_iron[0]), float(hard_iron[1])],
         "model": "psi_meas = atan2(sin psi - by, cos psi + bx) + noise, wrapped [0, 360)"})
    draws["magnetometer"] = {"hard_iron_fraction": [float(hard_iron[0]), float(hard_iron[1])]}

    normalised_rms = float(math.sqrt(sum(v * v for v in normalised) / len(normalised))) \
        if normalised else 0.0
    # R2: the Allan self-report of the recorded-rate gyro and accelerometer
    # residuals (non-overlapping form), graded against the profile's N.
    allan = {}
    for truth_name, measured_name, inst, axis, unit in CHANNELS:
        if inst not in ("imu.accelerometer", "imu.gyro") or measured_name not in out:
            continue
        residual = np.asarray(out[measured_name]) - np.asarray(out[truth_name])
        density = (profile.accelerometer["velocity_random_walk_mps_per_sqrt_h"] if inst == "imu.accelerometer"
                   else profile.gyro["angle_random_walk_deg_per_sqrt_h"])
        allan[measured_name] = allan_self_report(
            residual * (G0 if inst == "imu.accelerometer" else 1.0), dt, density / 60.0,
            sigmas[inst]["sigma_bias_instability"] * (G0 if inst == "imu.accelerometer" else 1.0),
            sigmas[inst]["correlation_time_s"],
            unit="m/s^2" if inst == "imu.accelerometer" else "deg/s")
    record = _record(profile, source, seeds, [e["measured"] for e in entries],
                     absent, normalised_rms, dt=dt, allan=allan)
    data = {
        "measured_version": MEASURED_VERSION,
        "profile": profile.to_dict(),
        "seeds": {"experiment_seed": seeds.experiment_seed, "replicate": seeds.replicate,
                  "derivation": DERIVATION, "generator": "PCG64",
                  "streams": {s: seeds.for_subsystem(s) for s in STREAMS}},
        "interval_s": dt,
        "samples": n,
        "truth_source": "telemetry.json",
        "truth_sha256": None,
        "naming": "<truth>_meas beside <truth>; altitude_m is measured twice "
                  "(altitude_m_gps_meas, altitude_m_baro_meas)",
        "channels": entries,
        "absent": absent,
        "draws": draws,
        "summary": {"normalised_rms": normalised_rms, "residual_rms": per_channel_rms},
        "columns": out,
        "applied_variables": records_block([record]),
    }
    return MeasuredResult(profile, record, data,
                          {"normalised_rms": normalised_rms, "channels": len(entries),
                           "absent": len(absent)})


def _record(profile: InstrumentProfile, source: str, seeds, measured: Sequence[str],
            absent: Mapping[str, str], normalised_rms: float, dt: float = 0.1,
            allan: Optional[Mapping[str, Any]] = None) -> AppliedVariable:
    """The ``instruments.profile`` record for one run (the recorded-rate
    path; R2 extends it with the rate, the seed streams, the Allan
    self-report and the lever arms)."""
    return AppliedVariable(
        name=RECORD_NAME,
        value=profile.name,
        unit="profile",
        source=source,
        model_name=MODEL,
        parameters={
            "profile": profile.to_dict(),
            "seed_streams": {s: seeds.for_subsystem(s) for s in STREAMS},
            "experiment_seed": seeds.experiment_seed,
            "replicate": seeds.replicate,
            "file": None if profile.is_ideal else MEASURED_FILE,
            "absent_truth_columns": dict(absent),
            # R2: the rate this path runs at, the Allan self-report and the
            # lever arms (the GPS antenna's; the IMU is at the CG here).
            "rate_hz": 1.0 / dt,
            "rate_basis": RECORDED_RATE_BASIS,
            "allan_self_report": dict(allan or {}),
            "lever_arms_m": {"imu": [0.0, 0.0, 0.0],
                             "gps": [float(v) for v in profile.gps["antenna_offset_body_m"]],
                             "pitot_static": [0.0, 0.0, 0.0], "magnetometer": [0.0, 0.0, 0.0]},
        },
        references=tuple(profile.references),
        properties_written=(),
        telemetry_columns=tuple(measured),
        frame_keys=(),
        null_test=NullTest(
            quantity="measured-minus-truth RMS over every measured channel, each "
                     "residual divided by its channel's stated sigma",
            unit="dimensionless",
            with_value=float(normalised_rms),
            without_value=0.0,
            threshold=NULL_THRESHOLD,
            note="'without' is the ideal profile, whose measurement equals the truth "
                 "by construction (0 exactly); the ideal profile itself therefore "
                 "measures no difference and its null test is not ok"),
        # Record 2: the structured model and the provenance text. An
        # observer over the recording writes no JSBSim property: no readback.
        model=Model(
            name=MODEL, standard="IEEE Std 952-2020 terms; GPS SPS PS; Caruso 2000",
            version=f"profile {profile.name} (sha256 {profile.sha256})",
            parameters={"basis": profile.basis, "rate_basis": RECORDED_RATE_BASIS,
                        "rate_hz": 1.0 / dt,
                        "file": None if profile.is_ideal else MEASURED_FILE},
            references=tuple(profile.references)),
        frm=(f"--instruments {profile.name}" if source == "user"
             else "the documented default profile (ideal)"),
        std=profile.source,
        not_claimed=(
            "scale-factor, misalignment, g-sensitivity, quantisation and temperature "
            "errors", "the rate random walk term", "GPS multipath, ionospheric, clock "
            "and geometry errors", "the velocity lever-arm term (omega x arm)",
            "magnetometer soft-iron, tilt and declination (true heading, level field)",
            "air-data position error", "correlation between instruments",
            "the fidelity of the profile numbers (each cited as unverified here)",
            "any per-frame key: the measured file is per step",
        ),
    )


def serialise(data: Mapping[str, Any]) -> bytes:
    """The file's bytes: sorted keys, one indent, ASCII -- deterministic."""
    return (json.dumps(data, indent=1, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")


def write_measured(result: MeasuredResult, run_dir) -> Optional[Path]:
    """Write ``telemetry_measured.json`` beside ``telemetry.json`` (whose
    sha256 the file records); None for the ideal profile, which writes
    nothing."""
    if result.data is None:
        return None
    run_dir = Path(run_dir)
    truth = run_dir / "telemetry.json"
    if truth.is_file():
        result.data["truth_sha256"] = hashlib.sha256(truth.read_bytes()).hexdigest()
    path = run_dir / MEASURED_FILE
    path.write_bytes(serialise(result.data))
    return path


def measure_run(run_dir, profile_name: str, seed: int, source: str = "user",
                replicate: int = 0, profile_dir: Optional[Path] = None) -> MeasuredResult:
    """Read ``telemetry.json`` in ``run_dir``, apply the named profile and
    write the measured file (nothing for the ideal profile)."""
    run_dir = Path(run_dir)
    profile = load_profile(profile_name, profile_dir)
    telemetry = json.loads((run_dir / "telemetry.json").read_text(encoding="utf-8"))
    result = measure(telemetry, profile, seed, replicate, source)
    write_measured(result, run_dir)
    return result


def describe(result: MeasuredResult) -> str:
    """The one line the capture prints."""
    if result.data is None:
        return (f"instruments: {result.profile.name} (the recorded channels are the "
                f"measurement; no {MEASURED_FILE} written)")
    return (f"instruments: {result.profile.name} -> {MEASURED_FILE} "
            f"({result.summary['channels']} measured channels beside truth, "
            f"{result.summary['absent']} truth columns absent from the recording, "
            f"normalised residual RMS {result.summary['normalised_rms']:.3f})")


# -- R2: the FDM-rate observer ---------------------------------------------------

class InstrumentError(Exception):
    """A refusal of the ``instruments`` block, by name (``.constraint``:
    ``instrument.profile``, ``instrument.lever_arm``, ``instrument.rate``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


@dataclass(frozen=True)
class InstrumentSpec:
    """One instrument as the spec states it: its profile, its lever arm
    from the CG in body metres (x forward, y right, z down), whether the
    spec stated it (else the ideal profile at the CG), and the provenance."""

    name: str
    profile: InstrumentProfile
    lever_arm_m: Tuple[float, float, float]
    stated: bool
    source: str = "default"
    frm: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "profile": self.profile.name,
                "profile_sha256": self.profile.sha256, "profile_path": self.profile.path,
                "lever_arm_m": list(self.lever_arm_m), "stated": self.stated,
                "source": self.source, "from": self.frm}


def instrument_problems(name: str, value: Any, rate_hz: Optional[float] = None,
                        profile_dir: Optional[Path] = None) -> List[Tuple[str, str]]:
    """Every refusal one ``instruments.<name>`` field earns, as (constraint,
    message): ``instrument.profile`` (not a {profile, lever_arm_m} mapping,
    an unknown key, a profile not on file or malformed), ``instrument.lever_arm``
    (not three finite numbers, or longer than LEVER_ARM_MAX_M),
    ``instrument.rate`` (a GPS update rate above the FDM rate: a receiver
    cannot fix more often than the model steps). None (unstated) earns
    none. The same list serves the validator and the runner."""
    if value is None:
        return []
    out: List[Tuple[str, str]] = []
    if not isinstance(value, Mapping):
        return [_problem(constraint="instrument.profile",
                         message=f"instruments.{name} must be a mapping {{profile: <name>, "
                                 f"lever_arm_m: [x, y, z]}} or null, not {value!r}")]
    unknown = sorted(set(value) - {"profile", "lever_arm_m"})
    if unknown:
        out.append(_problem(constraint="instrument.profile",
                            message=f"instruments.{name} carries keys this build does not "
                                    f"read: {unknown}"))
    profile_name = value.get("profile")
    profile = None
    if not isinstance(profile_name, str) or not profile_name.strip():
        out.append(_problem(constraint="instrument.profile",
                            message=f"instruments.{name} names no profile"))
    else:
        try:
            profile = load_profile(profile_name, profile_dir)
        except InstrumentProfileError as exc:
            out.append(_problem(constraint="instrument.profile",
                                message=f"instruments.{name}: {exc.message}"))
    arm = value.get("lever_arm_m", [0.0, 0.0, 0.0])
    if not isinstance(arm, (list, tuple)) or len(arm) != 3 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in arm):
        out.append(_problem(constraint="instrument.lever_arm",
                            message=f"instruments.{name}.lever_arm_m must be [x, y, z] finite "
                                    f"metres in body axes (x forward, y right, z down), not "
                                    f"{arm!r}"))
    elif math.sqrt(sum(float(v) ** 2 for v in arm)) > LEVER_ARM_MAX_M:
        out.append(_problem(constraint="instrument.lever_arm",
                            message=f"instruments.{name}.lever_arm_m is "
                                    f"{math.sqrt(sum(float(v) ** 2 for v in arm)):.1f} m long; "
                                    f"a sensor on the airframe sits within "
                                    f"{LEVER_ARM_MAX_M:g} m of the CG"))
    if name == "gps" and profile is not None and rate_hz is not None \
            and float(profile.gps["update_rate_hz"]) > float(rate_hz) + 1e-9:
        out.append(_problem(constraint="instrument.rate",
                            message=f"instruments.gps profile {profile.name!r} fixes at "
                                    f"{profile.gps['update_rate_hz']:g} Hz, above the FDM rate "
                                    f"{float(rate_hz):g} Hz; a receiver cannot fix more often "
                                    f"than the model steps"))
    return out


def _problem(constraint: str, message: str) -> Tuple[str, str]:
    """One (constraint, message) refusal of :func:`instrument_problems`,
    the name spelled as a keyword so the catalogue's scanner reads it."""
    return constraint, message


def instruments_from_spec(spec, profile_dir: Optional[Path] = None) -> Dict[str, InstrumentSpec]:
    """The four instruments a spec states (core/scenario/blocks.py
    InstrumentsSpec), the ideal profile at the CG for each unstated one;
    refuses by name what :func:`instrument_problems` refuses."""
    from ..scenario.blocks import INSTRUMENT_NAMES

    block = getattr(spec, "instruments", None)
    rate = float(spec.rate.value)
    out: Dict[str, InstrumentSpec] = {}
    ideal = load_profile(DEFAULT_PROFILE, profile_dir)
    for name in INSTRUMENT_NAMES:
        quantity = getattr(block, name) if block is not None else None
        value = None if quantity is None else quantity.value
        problems = instrument_problems(name, value, rate, profile_dir)
        if problems:
            raise InstrumentError(problems[0][0], problems[0][1])
        if value is None:
            out[name] = InstrumentSpec(name, ideal, (0.0, 0.0, 0.0), False, "default",
                                       "unstated: the ideal profile at the CG")
            continue
        arm = value.get("lever_arm_m", [0.0, 0.0, 0.0])
        out[name] = InstrumentSpec(
            name, load_profile(str(value["profile"]), profile_dir),
            (float(arm[0]), float(arm[1]), float(arm[2])), True,
            str(quantity.source), str(quantity.frm or ""))
    return out


# -- the physics -----------------------------------------------------------------

def rotational_terms(omega: np.ndarray, omega_dot: np.ndarray, r: np.ndarray) -> np.ndarray:
    """``omega_dot x r + omega x (omega x r)``: the specific force a sensor
    at ``r`` (body metres from the CG) sees beyond the CG's, from the
    body rates (rad/s) and angular accelerations (rad/s^2)."""
    return np.cross(omega_dot, r) + np.cross(omega, np.cross(omega, r))


def specific_force_body(n_x: float, n_y: float, n_z: float, omega: np.ndarray,
                        omega_dot: np.ndarray, r: np.ndarray) -> np.ndarray:
    """The specific force (m/s^2, body axes x forward, y right, z down) at
    a sensor ``r`` metres from the CG: ``g0 (N_x, N_y, -N_z)`` plus the
    rotational terms. NO gravity term: JSBSim's N is the total body force
    over the weight (FGAuxiliary: vBodyAccel = Force / Mass), which IS the
    specific force; the N_z sign flips because JSBSim's Nz is positive up
    and the sensor's z is down."""
    f_cg = G0 * np.array([float(n_x), float(n_y), -float(n_z)])
    return f_cg + rotational_terms(omega, omega_dot, r)


def dipole_field_ned(lat_deg: float, lon_deg: float, alt_m: float) -> Tuple[float, float, float]:
    """The IGRF-13 degree-1 (tilted dipole) field in nT, NED, from the
    spherical-harmonic potential ``V = a (a/r)^2 [g10 cos(theta) + (g11 cos(phi)
    + h11 sin(phi)) sin(theta)]`` differentiated in spherical coordinates
    (X = -B_theta, Y = B_phi, Z = -B_r). The geodetic latitude is taken as
    the geocentric colatitude's complement and the radius as a + h: a
    stated approximation worth a few tenths of a degree of declination,
    beside the dipole's own few degrees against IGRF/WMM."""
    theta = math.radians(90.0 - float(lat_deg))
    phi = math.radians(float(lon_deg))
    ratio = (IGRF_REFERENCE_RADIUS_M / (IGRF_REFERENCE_RADIUS_M + float(alt_m))) ** 3
    st, ct = math.sin(theta), math.cos(theta)
    sp, cp = math.sin(phi), math.cos(phi)
    b_r = 2.0 * ratio * (IGRF13_G10_NT * ct + (IGRF13_G11_NT * cp + IGRF13_H11_NT * sp) * st)
    b_theta = -ratio * (-IGRF13_G10_NT * st + (IGRF13_G11_NT * cp + IGRF13_H11_NT * sp) * ct)
    b_phi = -ratio * (-IGRF13_G11_NT * sp + IGRF13_H11_NT * cp)
    return -b_theta, b_phi, -b_r


def dipole_declination_deg(lat_deg: float, lon_deg: float, alt_m: float) -> float:
    """The dipole's declination (east positive) at a point, degrees."""
    x, y, _ = dipole_field_ned(lat_deg, lon_deg, alt_m)
    return math.degrees(math.atan2(y, x))


def magnetic_heading_deg(field_ned: Sequence[float], roll_deg: float, pitch_deg: float,
                         heading_deg: float, hard_iron: Sequence[float]) -> float:
    """What a three-axis magnetometer at this attitude reads as heading,
    degrees [0, 360): the NED field rotated into the body, hard-iron
    offsets added (a stated fraction of the horizontal field per body
    component, Caruso 2000), the body field levelled with the TRUE roll
    and pitch, and ``atan2(-B_y, B_x)`` -- the magnetic heading, true
    heading minus the local declination when the offsets are zero."""
    b_ned = np.asarray(field_ned, dtype=float)
    r_b2n = body_to_ned(roll_deg, pitch_deg, heading_deg)
    b_body = r_b2n.T @ b_ned
    horizontal = math.hypot(b_ned[0], b_ned[1])
    b_body = b_body + np.array([float(hard_iron[0]) * horizontal,
                                float(hard_iron[1]) * horizontal, 0.0])
    level = body_to_ned(roll_deg, pitch_deg, 0.0) @ b_body      # yaw-less: the level frame
    return math.degrees(math.atan2(-level[1], level[0])) % 360.0


def position_error_kt(cas_kt, table: Sequence[Sequence[float]]):
    """The position-error correction (kt) at a CAS from a [[cas, delta], ...]
    table: linear between rows, held beyond the ends, ZERO for an empty
    table (the stated default). Works on a scalar or an array."""
    if not table:
        return np.zeros_like(np.asarray(cas_kt, dtype=float)) if np.ndim(cas_kt) else 0.0
    xs = np.array([row[0] for row in table], dtype=float)
    ys = np.array([row[1] for row in table], dtype=float)
    out = np.interp(np.asarray(cas_kt, dtype=float), xs, ys)
    return float(out) if np.ndim(cas_kt) == 0 else out


# -- the Allan self-report (the NON-overlapping form) --------------------------------

def allan_deviation(x: np.ndarray, dt: float, m: int) -> Tuple[float, int]:
    """The NON-overlapping Allan deviation of a rate series at tau = m dt:
    the series cut into M = floor(N / m) clusters, each averaged, sigma^2 =
    1 / (2 (M - 1)) sum (ybar_{k+1} - ybar_k)^2 (IEEE Std 952-2020 Annex C
    as remembered; the check module uses the overlapping form). Returns
    (adev, M); NaN with M < 2 clusters."""
    x = np.asarray(x, dtype=float)
    clusters = len(x) // int(m)
    if clusters < 2:
        return math.nan, clusters
    means = x[:clusters * m].reshape(clusters, m).mean(axis=1)
    return float(math.sqrt(0.5 * np.mean(np.diff(means) ** 2))), clusters


def allan_self_report(residual: np.ndarray, dt: float, density: float, sigma_b: float,
                      tau_b_s: float, unit: str) -> Dict[str, Any]:
    """The producer's own Allan report of one residual series (measured
    minus truth, in the channel's unit per second): the deviation at the
    short taus, the agreement ``|adev / (N / sqrt(tau)) - 1|`` against
    the declared white density ``density`` (unit / sqrt(s)) within
    :data:`ALLAN_TOL`, and B and K NOT RUN unless the span is at least
    ALLAN_BK_RUN_MULTIPLE correlation times (then B is read at the
    curve's minimum over 0.664, K from the longest tau, both as estimates,
    not graded). A zero density grades nothing (NOT RUN: the ideal)."""
    residual = np.asarray(residual, dtype=float)
    span = (len(residual) - 1) * dt
    points = []
    for m in ALLAN_SHORT_M:
        adev, clusters = allan_deviation(residual, dt, m)
        tau = m * dt
        expected = density / math.sqrt(tau) if density > 0.0 else 0.0
        entry = {"tau_s": tau, "clusters": clusters, "adev": adev, "expected_white": expected,
                 "agreement": (abs(adev / expected - 1.0)
                               if expected > 0.0 and math.isfinite(adev) else None)}
        points.append(entry)
    graded = [p for p in points if p["agreement"] is not None and p["clusters"] >= ALLAN_MIN_CLUSTERS]
    if density <= 0.0:
        verdict = "NOT RUN: the declared white density is 0 (an ideal channel)"
    elif not graded:
        verdict = (f"NOT RUN: fewer than {ALLAN_MIN_CLUSTERS} clusters at every short tau "
                   f"({len(residual)} samples)")
    else:
        worst = max(p["agreement"] for p in graded)
        verdict = "PASS" if worst < ALLAN_TOL else f"FAIL: worst agreement {worst:.3f} >= {ALLAN_TOL}"
    needed = ALLAN_BK_RUN_MULTIPLE * tau_b_s
    if span < needed:
        bk = {"status": "NOT RUN",
              "reason": f"the run spans {span:.1f} s, under {ALLAN_BK_RUN_MULTIPLE:g} x the "
                        f"correlation time {tau_b_s:g} s = {needed:.0f} s; a bias instability "
                        f"and a rate random walk show only past tau_B",
              "B_estimate": None, "K_estimate": None}
    else:
        taus, adevs = [], []
        m = 1
        while (len(residual) // m) >= ALLAN_MIN_CLUSTERS:
            adev, _ = allan_deviation(residual, dt, m)
            taus.append(m * dt)
            adevs.append(adev)
            m *= 2
        k = int(np.argmin(adevs))
        bk = {"status": "estimated, not graded",
              "B_estimate": adevs[k] / 0.664, "B_tau_s": taus[k],
              "K_estimate": adevs[-1] * math.sqrt(3.0 / taus[-1]), "K_tau_s": taus[-1],
              "declared_B": sigma_b, "declared_tau_B_s": tau_b_s}
    return {"form": "non-overlapping Allan deviation over clusters of m samples "
                    "(the check uses the overlapping form)",
            "unit": unit, "dt_s": dt, "samples": int(len(residual)), "span_s": span,
            "declared_white_density": density, "density_unit": f"{unit} sqrt(s)",
            "short_tau": points, "tolerance": ALLAN_TOL, "white_term": verdict,
            "bias_instability_and_rate_random_walk": bk}


def _deterministic_npz(arrays: Mapping[str, np.ndarray]) -> bytes:
    """An ``.npz`` (a zip of ``.npy`` members, sorted by name) with fixed
    timestamps and no compression, so the same arrays give the same bytes
    -- ``numpy.savez`` stamps the wall clock into each member."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(arrays):
            member = io.BytesIO()
            np.lib.format.write_array(member, np.ascontiguousarray(arrays[name]),
                                      allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, member.getvalue())
    return buffer.getvalue()


#: The observer's log columns, in the file's order: the time, the truths
#: it read, the specific force at the CG and at the sensor, the nine
#: measured channels plus the measured specific force and the fix flag.
OBSERVER_TRUTH_COLUMNS = (
    "t", "truth_n_x", "truth_n_y", "truth_n_z", "truth_p_rad_s", "truth_q_rad_s",
    "truth_r_rad_s", "truth_pdot_rad_s2", "truth_qdot_rad_s2", "truth_rdot_rad_s2",
    "truth_roll_deg", "truth_pitch_deg", "truth_heading_deg", "truth_lat_deg", "truth_lon_deg",
    "truth_alt_m", "truth_cas_kt", "truth_f_cg_x_mps2", "truth_f_cg_y_mps2", "truth_f_cg_z_mps2",
    "truth_f_x_mps2", "truth_f_y_mps2", "truth_f_z_mps2", "truth_magnetic_heading_deg",
    "truth_declination_deg",
)
OBSERVER_MEAS_COLUMNS = (
    "meas_f_x_mps2", "meas_f_y_mps2", "meas_f_z_mps2", "meas_n_z", "meas_p_dps", "meas_q_dps",
    "meas_r_dps", "meas_lat_deg", "meas_lon_deg", "meas_alt_m", "meas_cas_kt",
    "meas_heading_deg", "gps_fix",
)
#: The measured channels each instrument owns (the recorder's columns).
INSTRUMENT_COLUMNS: Dict[str, Tuple[str, ...]] = {
    "imu": ("meas_n_z", "meas_p_dps", "meas_q_dps", "meas_r_dps"),
    "gps": ("meas_lat_deg", "meas_lon_deg", "meas_alt_m"),
    "pitot_static": ("meas_cas_kt",),
    "magnetometer": ("meas_heading_deg",),
}
#: The JSBSim angular accelerations the IMU's rotational terms read.
ANGULAR_ACCELERATION_PROPERTIES = ("accelerations/pdot-rad_sec2", "accelerations/qdot-rad_sec2",
                                   "accelerations/rdot-rad_sec2")


class InstrumentObserver:
    """The four instrument models run once per FDM step (the stack's
    observer hook, core/environment/stack.py), writing nothing to JSBSim.

    Construct from :func:`instruments_from_spec`, the run seed and the
    FDM rate; call :meth:`observe` after every step (and once at the
    initial state, so the first recorder sample is not NaN); read
    :meth:`latest` from the recorder; after the run, :meth:`arrays`,
    :meth:`npz_bytes`, :meth:`manifest_block` and
    :meth:`applied_variables`. Every draw comes from the five named
    streams in a fixed order, so the same seed and block give the same
    bytes (tested).
    """

    def __init__(self, instruments: Mapping[str, InstrumentSpec], seed: int, rate_hz: float,
                 replicate: int = 0) -> None:
        if not rate_hz > 0.0:
            raise ValueError(f"rate_hz {rate_hz!r} is not a positive rate")
        self.instruments = dict(instruments)
        self.seed, self.replicate = int(seed), int(replicate)
        self.rate_hz = float(rate_hz)
        self.dt = 1.0 / self.rate_hz
        self.seeds = derive(self.seed, self.replicate)
        self._rng = {s: generator(self.seed, s, self.replicate) for s in OBSERVER_STREAMS}
        imu, gps = self.instruments["imu"], self.instruments["gps"]
        self._terms = {name: _sigmas(spec.profile, self.dt) for name, spec in self.instruments.items()}
        acc, gyr = self._terms["imu"]["imu.accelerometer"], self._terms["imu"]["imu.gyro"]
        rng = self._rng["imu"]
        # The IMU's per-run draws, in a fixed order: accelerometer bias
        # (3, in g), gyro bias (3, deg/s), then the stationary Gauss-Markov
        # starts (3 + 3).
        self.acc_bias_g = rng.standard_normal(3) * acc["sigma_bias_repeatability"]
        self.gyro_bias_dps = rng.standard_normal(3) * gyr["sigma_bias_repeatability"]
        self._acc_gm = rng.standard_normal(3) * acc["sigma_bias_instability"]
        self._gyro_gm = rng.standard_normal(3) * gyr["sigma_bias_instability"]
        self._acc_a = math.exp(-self.dt / acc["correlation_time_s"])
        self._gyro_a = math.exp(-self.dt / gyr["correlation_time_s"])
        mag = self._terms["magnetometer"]["magnetometer.heading"]
        self.hard_iron = self._rng["magnetometer"].standard_normal(2) * mag["sigma_hard_iron_fraction"]
        self.r_imu = np.asarray(imu.lever_arm_m, dtype=float)
        self.r_gps = np.asarray(gps.lever_arm_m, dtype=float)
        # An UNSTATED receiver is the ideal at the FDM rate: a fix every
        # step, so the recorded position IS the measurement. A stated
        # profile fixes at its own rate, ideal included (the ideal file
        # states 10 Hz), and holds between fixes.
        self._gps_period = (self.dt if not gps.stated
                            else 1.0 / float(gps.profile.gps["update_rate_hz"]))
        self._next_fix: Optional[float] = None
        self._gps_last: Optional[Tuple[float, float, float]] = None
        self._cas_lag: Optional[float] = None
        self._angular_acceleration_available: Optional[bool] = None
        #: JSBSim's N is computed by FGAuxiliary from the PREVIOUS
        #: FGAccelerations run, and so is its own pilot accelerometer's
        #: omega_dot (measured: g0 n-pilot agrees with the model to 1.5e-6
        #: m/s^2 with the previous step's pdot, 3.8e-3 with the current
        #: step's); the observer therefore pairs N with the angular
        #: acceleration read at the previous observation -- the same
        #: evaluation -- and states so. The first observation has no
        #: previous read and takes the current one.
        self._omega_dot_prev: Optional[np.ndarray] = None
        self.steps = 0
        self.fixes = 0
        self._latest: Dict[str, float] = {name: math.nan for name in MEASURED_CHANNEL_NAMES}
        self._log: Dict[str, List[float]] = {n: [] for n in OBSERVER_TRUTH_COLUMNS + OBSERVER_MEAS_COLUMNS}

    # -- per step ---------------------------------------------------------

    def observe(self, fdm) -> Dict[str, float]:
        """Read the FDM's state, run the four models one step, log the
        truths and the measurements, and return the latest values."""
        state = fdm.state()
        t = float(state.t)
        omega = np.radians([state.roll_rate_dps, state.pitch_rate_dps, state.yaw_rate_dps])
        if self._angular_acceleration_available is None:
            self._angular_acceleration_available = all(
                fdm.props.has(p) for p in ANGULAR_ACCELERATION_PROPERTIES)
        omega_dot_now = (np.array([fdm.props.get(p) for p in ANGULAR_ACCELERATION_PROPERTIES])
                         if self._angular_acceleration_available else np.zeros(3))
        omega_dot = omega_dot_now if self._omega_dot_prev is None else self._omega_dot_prev
        self._omega_dot_prev = omega_dot_now

        # -- IMU: the specific force at the sensor, then the error terms.
        f_cg = specific_force_body(state.n_x, state.n_y, state.n_z, omega, omega_dot, np.zeros(3))
        f_sensor = specific_force_body(state.n_x, state.n_y, state.n_z, omega, omega_dot, self.r_imu)
        acc, gyr = self._terms["imu"]["imu.accelerometer"], self._terms["imu"]["imu.gyro"]
        rng = self._rng["imu"]
        w = rng.standard_normal(12)
        self._acc_gm = self._acc_a * self._acc_gm + math.sqrt(max(0.0, 1.0 - self._acc_a ** 2)) \
            * acc["sigma_bias_instability"] * w[0:3]
        self._gyro_gm = self._gyro_a * self._gyro_gm + math.sqrt(max(0.0, 1.0 - self._gyro_a ** 2)) \
            * gyr["sigma_bias_instability"] * w[3:6]
        f_meas = f_sensor + G0 * (self.acc_bias_g + self._acc_gm + acc["sigma_white"] * w[6:9])
        rates_dps = np.degrees(omega) + self.gyro_bias_dps + self._gyro_gm + gyr["sigma_white"] * w[9:12]
        meas_n_z = -f_meas[2] / G0                       # the sign flip, back onto JSBSim's channel

        # -- GPS: a fix on the receiver's clock, held between.
        fix = 0
        if self._next_fix is None or t >= self._next_fix - 1e-9:
            fix = 1
            self._next_fix = (t if self._next_fix is None else self._next_fix) + self._gps_period
            while self._next_fix <= t + 1e-9:
                self._next_fix += self._gps_period
            gps = self.instruments["gps"].profile.gps
            noise = self._rng["gps"].standard_normal(3)
            offset = body_to_ned(state.roll_deg, state.pitch_deg, state.heading_deg) @ self.r_gps
            r_m, r_n = radii_of_curvature(state.lat_deg)
            north_m = offset[0] + gps["north_east_sigma_m"] * noise[0]
            east_m = offset[1] + gps["north_east_sigma_m"] * noise[1]
            down_m = offset[2] + gps["vertical_sigma_m"] * noise[2]
            self._gps_last = (
                state.lat_deg + math.degrees(north_m / r_m),
                state.lon_deg + math.degrees(east_m / (r_n * math.cos(math.radians(state.lat_deg)))),
                state.altitude_m - down_m)
            self.fixes += 1
        lat_m, lon_m, alt_m = self._gps_last

        # -- pitot-static: the lag, the position error, the noise.
        ps = self._terms["pitot_static"]["pitot_static.airspeed"]
        if self._cas_lag is None or ps["lag_s"] <= 0.0:
            self._cas_lag = float(state.cas_kt)
        else:
            alpha = self.dt / (ps["lag_s"] + self.dt)
            self._cas_lag = self._cas_lag + alpha * (float(state.cas_kt) - self._cas_lag)
        cas_m = (self._cas_lag + position_error_kt(self._cas_lag, ps["position_error_table_kt"])
                 + ps["sigma_white"] * self._rng["pitot_static"].standard_normal())

        # -- magnetometer: the dipole in the body, hard iron, levelled.
        field = dipole_field_ned(state.lat_deg, state.lon_deg, state.altitude_m)
        declination = math.degrees(math.atan2(field[1], field[0]))
        mag = self._terms["magnetometer"]["magnetometer.heading"]
        psi_m = magnetic_heading_deg(field, state.roll_deg, state.pitch_deg, state.heading_deg,
                                     self.hard_iron)
        heading_m = (psi_m + mag["sigma_white"] * self._rng["magnetometer"].standard_normal()) % 360.0

        self._latest = {
            "meas_n_z": float(meas_n_z), "meas_p_dps": float(rates_dps[0]),
            "meas_q_dps": float(rates_dps[1]), "meas_r_dps": float(rates_dps[2]),
            "meas_lat_deg": float(lat_m), "meas_lon_deg": float(lon_m), "meas_alt_m": float(alt_m),
            "meas_cas_kt": float(cas_m), "meas_heading_deg": float(heading_m),
        }
        row = {
            "t": t, "truth_n_x": state.n_x, "truth_n_y": state.n_y, "truth_n_z": state.n_z,
            "truth_p_rad_s": omega[0], "truth_q_rad_s": omega[1], "truth_r_rad_s": omega[2],
            "truth_pdot_rad_s2": omega_dot[0], "truth_qdot_rad_s2": omega_dot[1],
            "truth_rdot_rad_s2": omega_dot[2],
            "truth_roll_deg": state.roll_deg, "truth_pitch_deg": state.pitch_deg,
            "truth_heading_deg": state.heading_deg, "truth_lat_deg": state.lat_deg,
            "truth_lon_deg": state.lon_deg, "truth_alt_m": state.altitude_m,
            "truth_cas_kt": state.cas_kt,
            "truth_f_cg_x_mps2": f_cg[0], "truth_f_cg_y_mps2": f_cg[1], "truth_f_cg_z_mps2": f_cg[2],
            "truth_f_x_mps2": f_sensor[0], "truth_f_y_mps2": f_sensor[1], "truth_f_z_mps2": f_sensor[2],
            "truth_magnetic_heading_deg": (state.heading_deg - declination) % 360.0,
            "truth_declination_deg": declination,
            "meas_f_x_mps2": f_meas[0], "meas_f_y_mps2": f_meas[1], "meas_f_z_mps2": f_meas[2],
            **self._latest, "gps_fix": float(fix),
        }
        for name, value in row.items():
            self._log[name].append(float(value))
        self.steps += 1
        return dict(self._latest)

    def latest(self) -> Dict[str, float]:
        """The nine recorder channels as last measured (NaN before the
        first observation: absent, never invented)."""
        return dict(self._latest)

    # -- after the run ------------------------------------------------------

    def arrays(self) -> Dict[str, np.ndarray]:
        return {name: np.asarray(values, dtype=np.float64) for name, values in self._log.items()}

    def npz_bytes(self) -> bytes:
        return _deterministic_npz(self.arrays())

    def sha256(self) -> str:
        return hashlib.sha256(self.npz_bytes()).hexdigest()

    @property
    def stated(self) -> bool:
        """Whether the spec stated any instrument (the file is written
        only then; the default ideal set records the columns and no file)."""
        return any(spec.stated for spec in self.instruments.values())

    def write(self, run_dir) -> Optional[Path]:
        """``instruments.npz`` beside the run when an instrument is stated;
        None (nothing written) for the default ideal set."""
        if not self.stated:
            return None
        path = Path(run_dir) / INSTRUMENTS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.npz_bytes())
        return path

    def residuals(self) -> Dict[str, Dict[str, Any]]:
        """Per measured channel: the residual (measured minus the model's
        own truth) std against the sigma the profile states at this rate,
        the ratio, and whether it lies within 25 % -- the null measurement
        of each stated instrument against the ideal (0 by construction)."""
        a = self.arrays()
        n = len(a["t"])
        out: Dict[str, Dict[str, Any]] = {}
        if n < 2:
            return out
        acc, gyr = self._terms["imu"]["imu.accelerometer"], self._terms["imu"]["imu.gyro"]
        pairs = [
            ("meas_n_z", a["meas_n_z"] - (-a["truth_f_z_mps2"] / G0),
             math.hypot(acc["sigma_white"], acc["sigma_bias_instability"]), "g"),
            ("meas_p_dps", a["meas_p_dps"] - np.degrees(a["truth_p_rad_s"]),
             math.hypot(gyr["sigma_white"], gyr["sigma_bias_instability"]), "deg/s"),
            ("meas_q_dps", a["meas_q_dps"] - np.degrees(a["truth_q_rad_s"]),
             math.hypot(gyr["sigma_white"], gyr["sigma_bias_instability"]), "deg/s"),
            ("meas_r_dps", a["meas_r_dps"] - np.degrees(a["truth_r_rad_s"]),
             math.hypot(gyr["sigma_white"], gyr["sigma_bias_instability"]), "deg/s"),
        ]
        gps = self.instruments["gps"].profile.gps
        at = np.flatnonzero(a["gps_fix"] > 0.5)
        if at.size:
            lat = a["truth_lat_deg"][at]
            r_m = np.array([radii_of_curvature(v)[0] for v in lat])
            r_n = np.array([radii_of_curvature(v)[1] for v in lat])
            lever = np.array([body_to_ned(a["truth_roll_deg"][i], a["truth_pitch_deg"][i],
                                          a["truth_heading_deg"][i]) @ self.r_gps for i in at])
            pairs += [
                ("meas_lat_deg", np.radians(a["meas_lat_deg"][at] - lat) * r_m - lever[:, 0],
                 gps["north_east_sigma_m"], "m"),
                ("meas_lon_deg", np.radians(a["meas_lon_deg"][at] - a["truth_lon_deg"][at]) * r_n
                 * np.cos(np.radians(lat)) - lever[:, 1], gps["north_east_sigma_m"], "m"),
                ("meas_alt_m", (a["truth_alt_m"][at] - a["meas_alt_m"][at]) - lever[:, 2],
                 gps["vertical_sigma_m"], "m"),
            ]
        ps = self._terms["pitot_static"]["pitot_static.airspeed"]
        lagged = first_order_lag(a["truth_cas_kt"], ps["lag_s"], self.dt)
        lagged = lagged + position_error_kt(lagged, ps["position_error_table_kt"])
        pairs.append(("meas_cas_kt", a["meas_cas_kt"] - lagged, ps["sigma_white"], "kt"))
        mag = self._terms["magnetometer"]["magnetometer.heading"]
        biased = np.array([magnetic_heading_deg(
            dipole_field_ned(a["truth_lat_deg"][i], a["truth_lon_deg"][i], a["truth_alt_m"][i]),
            a["truth_roll_deg"][i], a["truth_pitch_deg"][i], a["truth_heading_deg"][i],
            self.hard_iron) for i in range(n)])
        pairs.append(("meas_heading_deg", (a["meas_heading_deg"] - biased + 180.0) % 360.0 - 180.0,
                      mag["sigma_white"], "deg"))
        for name, residual, sigma, unit in pairs:
            std = float(np.std(residual)) if len(residual) > 1 else 0.0
            ratio = (std / sigma) if sigma > 0.0 else None
            out[name] = {"residual_std": std, "sigma_expected": float(sigma), "unit": unit,
                         "ratio": ratio, "samples": int(len(residual)),
                         "within_25pct": (None if ratio is None else abs(ratio - 1.0) <= 0.25),
                         "basis": ("residual = measured minus the model's own truth at this "
                                   "channel (the lever arm removed for the GPS at the fix "
                                   "samples, the lag re-applied for the CAS, the dipole and "
                                   "hard iron re-applied for the heading)")}
        return out

    def allan_report(self) -> Dict[str, Any]:
        """The Allan self-report of the six IMU residuals (accelerometer in
        m/s^2, gyro in deg/s) plus the estimator's own check on a
        synthetic white stream from the null_test seed stream."""
        a = self.arrays()
        if len(a["t"]) < 2:
            return {}
        acc, gyr = self._terms["imu"]["imu.accelerometer"], self._terms["imu"]["imu.gyro"]
        profile = self.instruments["imu"].profile
        n_acc = profile.accelerometer["velocity_random_walk_mps_per_sqrt_h"] / 60.0
        n_gyr = profile.gyro["angle_random_walk_deg_per_sqrt_h"] / 60.0
        out: Dict[str, Any] = {}
        for axis, k in zip("xyz", range(3)):
            residual = a[f"meas_f_{axis}_mps2"] - a[f"truth_f_{axis}_mps2"]
            out[f"meas_f_{axis}_mps2"] = allan_self_report(
                residual, self.dt, n_acc, acc["sigma_bias_instability"] * G0,
                acc["correlation_time_s"], "m/s^2")
        for name, truth in (("meas_p_dps", "truth_p_rad_s"), ("meas_q_dps", "truth_q_rad_s"),
                            ("meas_r_dps", "truth_r_rad_s")):
            residual = a[name] - np.degrees(a[truth])
            out[name] = allan_self_report(residual, self.dt, n_gyr, gyr["sigma_bias_instability"],
                                          gyr["correlation_time_s"], "deg/s")
        # The estimator on a pure white stream of the run's own length at
        # the gyro's declared density, from the null_test stream: what the
        # non-overlapping estimator returns when the answer is known.
        n = len(a["t"])
        synthetic = self._rng["null_test"].standard_normal(n) * (n_gyr / math.sqrt(self.dt)
                                                                  if n_gyr > 0 else 1.0)
        density = n_gyr if n_gyr > 0 else 1.0 * math.sqrt(self.dt)
        out["estimator_check"] = {
            "stream": "null_test", "samples": n,
            "declared_density": density,
            "report": allan_self_report(synthetic, self.dt, density, 0.0, 1.0, "synthetic"),
        }
        return out

    def rotational_term_peak(self) -> float:
        """The largest |f_sensor - f_cg| over the run (m/s^2): what the IMU
        lever arm added, 0 at the CG."""
        a = self.arrays()
        if not len(a["t"]):
            return 0.0
        d = np.stack([a[f"truth_f_{ax}_mps2"] - a[f"truth_f_cg_{ax}_mps2"] for ax in "xyz"])
        return float(np.max(np.linalg.norm(d, axis=0)))

    def manifest_block(self, file_written: bool = None) -> Dict[str, Any]:
        """The run manifest's ``instruments`` block (and the capture
        manifest's top-level one): profiles, seeds, the two rates, the
        file with its sha256 and columns, the residuals, the Allan
        self-report, what is not claimed."""
        written = self.stated if file_written is None else bool(file_written)
        return {
            "instruments_version": INSTRUMENTS_VERSION,
            "rate_hz": self.rate_hz, "rate_basis": FDM_RATE_BASIS,
            "recorded_rate_basis": RECORDED_RATE_BASIS,
            "steps": self.steps, "fixes": self.fixes,
            "seeds": {"experiment_seed": self.seeds.experiment_seed,
                      "replicate": self.seeds.replicate, "derivation": DERIVATION,
                      "generator": "PCG64",
                      "streams": {s: self.seeds.for_subsystem(s) for s in OBSERVER_STREAMS}},
            "instruments": {name: spec.to_dict() for name, spec in self.instruments.items()},
            "profiles": {name: spec.profile.to_dict() for name, spec in self.instruments.items()},
            "draws": {"accelerometer_bias_g": [float(v) for v in self.acc_bias_g],
                      "gyro_bias_dps": [float(v) for v in self.gyro_bias_dps],
                      "hard_iron_fraction": [float(v) for v in self.hard_iron]},
            "file": INSTRUMENTS_FILE if written else None,
            "sha256": self.sha256() if written else None,
            "columns": list(OBSERVER_TRUTH_COLUMNS + OBSERVER_MEAS_COLUMNS),
            "recorder_columns": list(MEASURED_CHANNEL_NAMES),
            "specific_force": "f = g0 (N_x, N_y, -N_z) + omega_dot x r + omega x (omega x r), "
                              "body axes; no gravity term; meas_n_z = -f_z / g0",
            "rotational_term_peak_mps2": self.rotational_term_peak(),
            "residuals": self.residuals(),
            "allan_self_report": self.allan_report(),
            "not_claimed": list(OBSERVER_NOT_CLAIMED),
        }

    def readback(self, recorder) -> Readback:
        """The recorder's LAST meas_n_z sample against the observer's value
        at that sample's time: the latest-value sampling, read back from
        the recorder's own store (nothing is written to JSBSim)."""
        a = self.arrays()
        ts = list(recorder.columns["t"])
        sampled = list(recorder.columns["meas_n_z"])
        k = len(ts) - 1
        index = int(np.searchsorted(a["t"], ts[k], side="right")) - 1
        written = float(a["meas_n_z"][index]) if index >= 0 else math.nan
        return Readback(
            property=f"telemetry.meas_n_z[{k}]", value=float(sampled[k]), written=written,
            tolerance=0.0, tolerance_kind="absolute",
            basis="the recorder samples the observer's latest value at the sample's step "
                  "(Recorder(measured=observer)); read back from recorder.columns after the run "
                  "against the observer's own log at that time; this grades the recorder's "
                  "store, not JSBSim's, to which nothing is written")

    def applied_variables(self, recorder=None) -> List[AppliedVariable]:
        """One record per STATED instrument (the default ideal set records
        nothing: nothing applied), each with the profile, the lever arm,
        the rate, the seeds, the residual measurement per channel and a
        null test against the ideal (0 by construction)."""
        residuals = self.residuals()
        allan = self.allan_report()
        out: List[AppliedVariable] = []
        for name, spec in self.instruments.items():
            if not spec.stated:
                continue
            columns = INSTRUMENT_COLUMNS[name]
            own = {c: residuals[c] for c in columns if c in residuals}
            graded = [(c, r) for c, r in own.items() if r["ratio"] is not None]
            if graded:
                best_name, best = max(graded, key=lambda cr: cr[1]["ratio"])
                null = NullTest(
                    quantity=f"residual std of {best_name} in units of the profile's stated "
                             f"sigma ({best['sigma_expected']:.4g} {best['unit']})",
                    unit="sigma", with_value=float(best["ratio"]), without_value=0.0,
                    threshold=NULL_RATIO_THRESHOLD, kind="reached",
                    note=("'without' is the ideal profile at the CG, whose measurement equals "
                          "the truth by construction (0 exactly); reached when the ratio is at "
                          "least 0.75; the within-25 % agreement per channel is in parameters."
                          f"residuals ({sum(1 for r in own.values() if r['within_25pct']) } of "
                          f"{len(graded)} channels within 25 %)"))
            else:
                null = NullTest(
                    quantity=f"residual std over {', '.join(columns)}", unit="sigma",
                    with_value=0.0, without_value=0.0, threshold=NULL_RATIO_THRESHOLD,
                    kind="reached",
                    note="a stated profile with every error term 0 measures no difference "
                         "from the ideal and is honestly not ok")
            parameters: Dict[str, Any] = {
                "profile": spec.profile.to_dict(), "lever_arm_m": list(spec.lever_arm_m),
                "rate_hz": self.rate_hz, "rate_basis": FDM_RATE_BASIS,
                "seed_streams": {s: self.seeds.for_subsystem(s) for s in OBSERVER_STREAMS},
                "experiment_seed": self.seeds.experiment_seed, "replicate": self.seeds.replicate,
                "file": INSTRUMENTS_FILE if self.stated else None,
                "residuals": own, "steps": self.steps,
            }
            if name == "imu":
                parameters.update({
                    "specific_force": "f = g0 (N_x, N_y, -N_z) + omega_dot x r + omega x (omega x r)",
                    "rotational_term_peak_mps2": self.rotational_term_peak(),
                    "draws": {"accelerometer_bias_g": [float(v) for v in self.acc_bias_g],
                              "gyro_bias_dps": [float(v) for v in self.gyro_bias_dps]},
                    "allan_self_report": allan,
                    "angular_acceleration": ("JSBSim accelerations/pdot,qdot,rdot-rad_sec2 of the "
                                             "previous step: the evaluation N comes from (FGAuxiliary "
                                             "runs before FGAccelerations; measured against "
                                             "n-pilot-*-norm)"
                                             if self._angular_acceleration_available
                                             else "absent on this model: omega_dot taken as 0"),
                })
            elif name == "gps":
                parameters.update({"fixes": self.fixes,
                                   "update_rate_hz": spec.profile.gps["update_rate_hz"],
                                   "hold": "zero-order between fixes, on the receiver's clock",
                                   "lever_arm": "measured = CG + R_body_to_NED(roll, pitch, heading) "
                                                "r; the velocity term omega x r is not applied"})
            elif name == "pitot_static":
                parameters.update({"lag_s": spec.profile.pitot_static["cas_lag_s"],
                                   "position_error_table_kt": spec.profile.pitot_static.get(
                                       "position_error_table_kt", []),
                                   "position_error": "linear in the table, zero for an empty one "
                                                     "(the stated default); the lever arm is "
                                                     "carried, not applied"})
            elif name == "magnetometer":
                a = self.arrays()
                parameters.update({
                    "field_model": "IGRF-13 degree-1 tilted dipole (g10, g11, h11 at 2020.0)",
                    "declination_deg_at_start": float(a["truth_declination_deg"][0]) if len(a["t"]) else None,
                    "reading": "magnetic heading = true heading - declination, hard iron and "
                               "noise added; the lever arm is carried, not applied",
                    "draws": {"hard_iron_fraction": [float(v) for v in self.hard_iron]},
                })
            out.append(AppliedVariable(
                name=f"instruments.{name}",
                value={"profile": spec.profile.name, "lever_arm_m": list(spec.lever_arm_m)},
                unit="profile + m", source=spec.source,
                model_name=f"{MODEL} at the FDM rate ({name})",
                parameters=parameters, references=tuple(spec.profile.references),
                properties_written=(), telemetry_columns=tuple(columns),
                frame_keys=tuple(f"state.{c}" for c in columns),
                null_test=null,
                model=Model(
                    name=f"{MODEL} at the FDM rate", standard=_instrument_standard(name),
                    version=f"profile {spec.profile.name} (sha256 {spec.profile.sha256})",
                    parameters={"rate_basis": FDM_RATE_BASIS, "rate_hz": self.rate_hz,
                                "lever_arm_m": list(spec.lever_arm_m),
                                "file": INSTRUMENTS_FILE if self.stated else None},
                    references=tuple(spec.profile.references)),
                readback=self.readback(recorder) if recorder is not None else None,
                frm=spec.frm or f"instruments.{name} stated in the spec", std=spec.profile.source,
                not_claimed=OBSERVER_NOT_CLAIMED))
        return out


def _instrument_standard(name: str) -> str:
    from ..scenario.blocks import INSTRUMENT_STANDARDS

    return INSTRUMENT_STANDARDS[name]


#: The recorder's nine measured channels (core/fdm/state.py MEASURED_CHANNELS).
MEASURED_CHANNEL_NAMES = ("meas_n_z", "meas_p_dps", "meas_q_dps", "meas_r_dps", "meas_lat_deg",
                          "meas_lon_deg", "meas_alt_m", "meas_cas_kt", "meas_heading_deg")

OBSERVER_NOT_CLAIMED = (
    "stated class models: no device is calibrated; every profile number is unverified here",
    "the Allan check measures that the model produced the noise it declares, not that a "
    "real sensor has it",
    "B and K are NOT RUN on a run shorter than 100 correlation times (every 60 s run)",
    "the magnetometer is a tilted dipole: a few degrees of declination error against "
    "IGRF/WMM, geodetic latitude taken as geocentric, no secular variation, no soft iron",
    "the pitot-static and magnetometer lever arms are carried, not applied; the GPS "
    "velocity term omega x r is not applied",
    "GPS multipath, ionosphere, clock and geometry; a correlated GPS error",
    "scale-factor, misalignment, g-sensitivity, quantisation and temperature errors",
    "host-flight instruments are post-hoc at the recorded rate (the engine side is P9's)",
)
