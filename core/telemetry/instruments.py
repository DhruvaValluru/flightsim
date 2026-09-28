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

NOT CLAIMED: scale-factor and misalignment errors; g-sensitivity;
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
from ..records import AppliedVariable, NullTest, records_block

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
        blocks = (self.accelerometer, self.gyro, self.pitot_static, self.magnetometer,
                  {k: v for k, v in self.gps.items()
                   if k not in ("update_rate_hz", "antenna_offset_body_m")})
        terms = [v for block in blocks for k, v in block.items()
                 if k != "correlation_time_s"]
        terms += list(self.gps["antenna_offset_body_m"])
        return all(float(v) == 0.0 for v in terms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "basis": self.basis, "source": self.source,
            "references": list(self.references),
            "imu": {"accelerometer": dict(self.accelerometer), "gyro": dict(self.gyro)},
            "gps": {**self.gps, "antenna_offset_body_m": list(self.gps["antenna_offset_body_m"])},
            "pitot_static": dict(self.pitot_static),
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
        unknown = sorted(set(block) - set(keys) - {"antenna_offset_body_m"})
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
    return InstrumentProfile(
        name=stated, basis=str(data.get("basis", "synthetic")),
        source=str(data["source"]), references=tuple(references),
        accelerometer=blocks["imu.accelerometer"], gyro=blocks["imu.gyro"], gps=gps,
        pitot_static=blocks["pitot_static"], magnetometer=blocks["magnetometer"],
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
        "pitot_static.airspeed": {"sigma_white": ps["cas_sigma_kt"], "lag_s": ps["cas_lag_s"]},
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
    record = _record(profile, source, seeds, [e["measured"] for e in entries],
                     absent, normalised_rms)
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
            absent: Mapping[str, str], normalised_rms: float) -> AppliedVariable:
    """The ``instruments.profile`` record for one run."""
    return AppliedVariable(
        name=RECORD_NAME,
        value=profile.name,
        unit="profile",
        source=source,
        model=MODEL,
        parameters={
            "profile": profile.to_dict(),
            "seed_streams": {s: seeds.for_subsystem(s) for s in STREAMS},
            "experiment_seed": seeds.experiment_seed,
            "replicate": seeds.replicate,
            "file": None if profile.is_ideal else MEASURED_FILE,
            "absent_truth_columns": dict(absent),
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
