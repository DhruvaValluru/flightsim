"""Dense pose clock and a seeded camera-motion layer.

Visual overhaul module "camera-motion-layer". Two things, both applied
to the SOLVED pose track before anything records or renders it, so the
beauty pass and every label capture consume one pose through the
commandlet's ``ApplyPoseAtTime`` (labels are safe by construction: the
motion is part of the pose track, not a post effect, so nothing here
goes in ``pixel_moving_effects``; the velocity pass already sees the
previous camera transform):

(a) **Dense clock.** :func:`resample_track` moves a pose track from the
    0.1 s telemetry clock onto the render clock (fps x accumulate
    sub-frames) with Catmull-Rom (cubic Hermite, non-uniform
    finite-difference tangents) position and slerp rotation. The
    original sample times are kept IN the dense clock, so at every
    telemetry time the dense track holds exactly the sample the
    manifest records (``label_pose: shutter-centre sample``).

(b) **Motion.** :func:`apply_motion` adds a deterministic perturbation
    named by the camera spec's ``motion`` block
    ``{profile, seed, intensity}``:

    * ``none`` -- the default for every existing card: the input track is
      returned AS IS (same object), so every digest is byte-identical.
    * ``handheld`` -- 1-15 Hz with the energy in a 3-9 Hz tremor band and
      a body sway under 3 Hz; RMS a few hundredths of a degree.
    * ``camera_ship`` -- narrow lines at a stated blade-pass frequency
      (and its first harmonic) plus broadband turbulence scaled by the
      camera's own speed, with second-order gimbal aim lag.
    * ``tripod_fluid_head`` -- a very small low-frequency wander and a
      fluid-head aim lag.

    Noise is a sum of sinusoids per axis whose frequency and phase come
    from ``sha256(seed, camera_id, axis, k)`` and which is evaluated at
    continuous t, so the value at a given t does not depend on the sample
    rate. Roll shake is clamped to +/- :data:`ROLL_BOUND_DEG` and the
    record states the bound (``horizon_stable`` stays True within it).

    Aim lag (when the profile asks) is a second-order spring-damper
    ``y'' + 2 zeta wn y' + wn^2 y = wn^2 x`` integrated EXACTLY over each
    interval with the input linear across it (first-order hold,
    :func:`second_order_step`) -- the analogue of ``poses.lag_step``.

Every profile number below is UNCALIBRATED (see docs/visual/PROBE_LOG.md
"## camera-motion-layer"): no footage has been measured against them.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .poses import PoseSolveError, PoseTrack, euler_to_quat, quat_slerp

#: The roll-shake clamp, degrees. Inside it a horizon-stable preset still
#: reports ``horizon_stable`` True; the record states the bound.
ROLL_BOUND_DEG = 0.15

#: Accepted intensity range (a multiplier on every profile amplitude).
INTENSITY_MAX = 3.0

ROTATION_AXES = ("yaw", "pitch", "roll")
TRANSLATION_AXES = ("north", "east", "up")

#: The profile table. Rotation RMS in degrees, translation RMS in metres,
#: each the nominal value at intensity 1 (and airspeed scale 1). A band
#: places ``n`` sinusoids log-uniformly in [lo_hz, hi_hz], each weighted
#: ``weight``; amplitudes are normalised so the axis RMS is the nominal.
#: ALL VALUES UNCALIBRATED.
PROFILES: Dict[str, Dict[str, Any]] = {
    "none": {
        "description": "no camera motion (the default; the track is unchanged)",
    },
    "handheld": {
        "description": "hand-held operator: 3-9 Hz tremor, sway under 3 Hz",
        "rotation_rms_deg": {"yaw": 0.035, "pitch": 0.03, "roll": 0.02},
        "translation_rms_m": 0.004,
        "bands": (
            {"name": "tremor", "lo_hz": 3.0, "hi_hz": 9.0, "n": 10, "weight": 1.0,
             "airspeed_scaled": False},
            {"name": "broad", "lo_hz": 1.0, "hi_hz": 15.0, "n": 4, "weight": 0.35,
             "airspeed_scaled": False},
            {"name": "sway", "lo_hz": 0.2, "hi_hz": 2.5, "n": 4, "weight": 0.5,
             "airspeed_scaled": False},
        ),
        "lines": (),
        "aim_lag": None,
    },
    "camera_ship": {
        "description": ("helicopter camera ship: blade-pass lines plus "
                        "airspeed-scaled turbulence, gimbal aim lag"),
        "rotation_rms_deg": {"yaw": 0.03, "pitch": 0.04, "roll": 0.02},
        "translation_rms_m": 0.02,
        "bands": (
            {"name": "turbulence", "lo_hz": 0.3, "hi_hz": 4.0, "n": 8, "weight": 1.0,
             "airspeed_scaled": True},
        ),
        #: Narrow lines: frequency = factor x blade_pass_hz x (1 +/- width).
        "lines": (
            {"name": "blade_pass", "factor": 1.0, "n": 2, "weight": 0.8, "width": 0.005},
            {"name": "blade_pass_2x", "factor": 2.0, "n": 1, "weight": 0.3, "width": 0.005},
        ),
        #: Default blade-pass frequency: a 3-blade main rotor near 390 rpm.
        "blade_pass_hz": 19.5,
        #: Turbulence scale = clamp(speed / reference, lo, hi).
        "reference_speed_mps": 60.0,
        "speed_scale_bounds": (0.25, 2.0),
        "aim_lag": {"zeta": 0.7, "fn_hz": 1.5},
    },
    "tripod_fluid_head": {
        "description": "tripod on a fluid head: tiny wander, damped pan",
        "rotation_rms_deg": {"yaw": 0.004, "pitch": 0.003, "roll": 0.001},
        "translation_rms_m": 0.0,
        "bands": (
            {"name": "wander", "lo_hz": 0.5, "hi_hz": 3.0, "n": 6, "weight": 1.0,
             "airspeed_scaled": False},
        ),
        "lines": (),
        "aim_lag": {"zeta": 0.8, "fn_hz": 1.0},
    },
}

MOTION_KEYS = ("profile", "seed", "intensity", "blade_pass_hz", "source")


class CameraMotionError(PoseSolveError):
    """A camera motion block that cannot be applied; refused by name."""

    constraint = "camera.motion"


# -- the spec block ------------------------------------------------------

def normalise_motion(spec: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The camera's ``motion`` block, checked: {profile, seed, intensity,
    blade_pass_hz?, source?}. None (absent) is profile none."""
    if spec is None:
        return {"profile": "none"}
    if not isinstance(spec, Mapping):
        raise CameraMotionError(
            f"camera.motion: the motion block is {type(spec).__name__}, not a mapping")
    unknown = sorted(set(spec) - set(MOTION_KEYS))
    if unknown:
        raise CameraMotionError(
            f"camera.motion: unknown key(s) {unknown}; the block takes {list(MOTION_KEYS)}")
    profile = str(spec.get("profile", "none"))
    if profile not in PROFILES:
        raise CameraMotionError(
            f"camera.motion: unknown profile {profile!r}; one of {sorted(PROFILES)}")
    out: Dict[str, Any] = {"profile": profile}
    if profile == "none":
        return out
    seed = spec.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise CameraMotionError(f"camera.motion: seed {seed!r} is not a whole number >= 0")
    intensity = spec.get("intensity", 1.0)
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)) \
            or not (0.0 <= float(intensity) <= INTENSITY_MAX):
        raise CameraMotionError(
            f"camera.motion: intensity {intensity!r} is outside [0, {INTENSITY_MAX:g}]")
    out.update(seed=int(seed), intensity=float(intensity))
    if "blade_pass_hz" in spec:
        if profile != "camera_ship":
            raise CameraMotionError(
                f"camera.motion: blade_pass_hz only applies to camera_ship, not {profile!r}")
        bp = spec["blade_pass_hz"]
        if isinstance(bp, bool) or not isinstance(bp, (int, float)) or not (0.5 <= float(bp) <= 200.0):
            raise CameraMotionError(f"camera.motion: blade_pass_hz {bp!r} is outside [0.5, 200]")
        out["blade_pass_hz"] = float(bp)
    elif profile == "camera_ship":
        out["blade_pass_hz"] = float(PROFILES["camera_ship"]["blade_pass_hz"])
    if spec.get("source") is not None:
        out["source"] = str(spec["source"])
    return out


def horizon_roll_tolerance_deg(motion: Optional[Mapping[str, Any]]) -> float:
    """The camera-roll tolerance a horizon-stable check may take: exact
    zero for profile none (or no record), ROLL_BOUND_DEG otherwise."""
    if not motion or str(motion.get("profile", "none")) == "none":
        return 0.0
    return float(motion.get("roll_bound_deg", ROLL_BOUND_DEG))


# -- noise ---------------------------------------------------------------

def _unit_pair(seed: int, camera_id: str, axis: str, k: int) -> Tuple[float, float]:
    """Two uniforms in [0, 1) from sha256(seed, camera_id, axis, k)."""
    digest = hashlib.sha256(f"{seed}|{camera_id}|{axis}|{k}".encode("utf-8")).digest()
    u1 = int.from_bytes(digest[0:8], "big") / 2.0 ** 64
    u2 = int.from_bytes(digest[8:16], "big") / 2.0 ** 64
    return u1, u2


@lru_cache(maxsize=256)
def _components(seed: int, camera_id: str, axis: str, profile: str,
                blade_pass_hz: float) -> Tuple[Tuple[float, float, float, bool], ...]:
    """(amplitude at unit RMS, frequency Hz, phase rad, airspeed_scaled)
    per sinusoid, normalised so the sum has RMS 1."""
    table = PROFILES[profile]
    raw: List[Tuple[float, float, float, bool]] = []
    k = 0
    for band in table.get("bands", ()):
        lo, hi = float(band["lo_hz"]), float(band["hi_hz"])
        for _ in range(int(band["n"])):
            u1, u2 = _unit_pair(seed, camera_id, axis, k)
            k += 1
            raw.append((float(band["weight"]), lo * (hi / lo) ** u1,
                        2.0 * math.pi * u2, bool(band["airspeed_scaled"])))
    for line in table.get("lines", ()):
        for _ in range(int(line["n"])):
            u1, u2 = _unit_pair(seed, camera_id, axis, k)
            k += 1
            f = float(line["factor"]) * blade_pass_hz * (1.0 + float(line["width"]) * (2.0 * u1 - 1.0))
            raw.append((float(line["weight"]), f, 2.0 * math.pi * u2, False))
    energy = sum(w * w for w, _, _, _ in raw) / 2.0
    if energy <= 0.0:
        return ()
    norm = 1.0 / math.sqrt(energy)
    return tuple((w * norm, f, ph, scaled) for w, f, ph, scaled in raw)


def n_sinusoids(profile: str) -> int:
    """Sinusoids per axis for a profile."""
    table = PROFILES[profile]
    return (sum(int(b["n"]) for b in table.get("bands", ()))
            + sum(int(line["n"]) for line in table.get("lines", ())))


def _axis_rms(profile: str, axis: str) -> float:
    table = PROFILES[profile]
    if axis in ROTATION_AXES:
        return float(table["rotation_rms_deg"][axis])
    return float(table["translation_rms_m"])


def band_noise(t: float, seed: int, camera_id: str, axis: str, profile: str,
               intensity: float = 1.0, airspeed_scale: float = 1.0,
               blade_pass_hz: Optional[float] = None) -> float:
    """The profile's perturbation on one axis at continuous time t:
    degrees for yaw/pitch/roll, metres for north/east/up. Unclamped.

    A pure function of t (never of a sample index or rate), so a 30 Hz
    and a 240 Hz clock agree wherever they share a t. ``airspeed_scale``
    multiplies only the bands marked airspeed_scaled."""
    if profile == "none" or profile not in PROFILES:
        if profile not in PROFILES:
            raise CameraMotionError(f"camera.motion: unknown profile {profile!r}")
        return 0.0
    rms = _axis_rms(profile, axis) * float(intensity)
    if rms == 0.0:
        return 0.0
    bp = float(blade_pass_hz if blade_pass_hz is not None
               else PROFILES[profile].get("blade_pass_hz", 0.0))
    total = 0.0
    for amp, f, ph, scaled in _components(int(seed), str(camera_id), axis, profile, bp):
        a = amp * (airspeed_scale if scaled else 1.0)
        total += a * math.sin(2.0 * math.pi * f * t + ph)
    return rms * total


# -- second-order aim lag -------------------------------------------------

def second_order_step(y: float, ydot: float, x_prev: float, x_now: float,
                      dt: float, zeta: float, fn: float) -> Tuple[float, float]:
    """One exact step of ``y'' + 2 zeta wn y' + wn^2 y = wn^2 x`` with x
    LINEAR from x_prev to x_now across dt (first-order hold). Returns
    (y, ydot) at the end of the interval. ``fn`` is in Hz.

    The ramp's particular solution is ``x(t) - 2 zeta s / wn`` (s the
    slope); the error about it is homogeneous and is propagated with
    the closed-form transition, so the integrator adds no rate error of
    its own (the analogue of poses.lag_step)."""
    if dt <= 0.0:
        return y, ydot
    if zeta <= 0.0 or fn <= 0.0:
        raise CameraMotionError(f"camera.motion: aim lag needs zeta > 0 and fn > 0, got {zeta}, {fn}")
    wn = 2.0 * math.pi * fn
    s = (x_now - x_prev) / dt
    offset = 2.0 * zeta * s / wn
    z0 = y - x_prev + offset
    v0 = ydot - s
    sigma = zeta * wn
    if zeta < 1.0 - 1e-12:
        wd = wn * math.sqrt(1.0 - zeta * zeta)
        e = math.exp(-sigma * dt)
        c, sn = math.cos(wd * dt), math.sin(wd * dt)
        z = e * (z0 * c + (v0 + sigma * z0) / wd * sn)
        v = e * (v0 * c - (wn * wn * z0 + sigma * v0) / wd * sn)
    elif zeta <= 1.0 + 1e-12:
        e = math.exp(-wn * dt)
        cc = v0 + wn * z0
        z = (z0 + cc * dt) * e
        v = (v0 - wn * cc * dt) * e
    else:
        root = wn * math.sqrt(zeta * zeta - 1.0)
        r1, r2 = -sigma + root, -sigma - root
        a = (v0 - r2 * z0) / (r1 - r2)
        b = z0 - a
        e1, e2 = math.exp(r1 * dt), math.exp(r2 * dt)
        z = a * e1 + b * e2
        v = a * r1 * e1 + b * r2 * e2
    return z + x_now - offset, v + s


# -- resampling ----------------------------------------------------------

def quat_to_euler(q: Sequence[float]) -> Tuple[float, float, float]:
    """Unit quaternion (w,x,y,z), NED -> (roll, pitch, yaw) degrees, the
    inverse of poses.euler_to_quat; yaw in [0, 360)."""
    w, x, y, z = q
    roll = math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (w * y - z * x)))))
    yaw = math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))) % 360.0
    return roll, pitch, yaw


def _tangents(t: Sequence[float], p: Sequence[float]) -> List[float]:
    """Catmull-Rom tangents on a non-uniform clock (one-sided at ends)."""
    n = len(t)
    out = []
    for i in range(n):
        lo, hi = max(i - 1, 0), min(i + 1, n - 1)
        out.append((p[hi] - p[lo]) / (t[hi] - t[lo]))
    return out


def _hermite(t0, t1, p0, p1, m0, m1, at):
    """Cubic Hermite value and derivative on [t0, t1]."""
    h = t1 - t0
    u = (at - t0) / h
    u2, u3 = u * u, u * u * u
    value = ((2 * u3 - 3 * u2 + 1) * p0 + (u3 - 2 * u2 + u) * h * m0
             + (-2 * u3 + 3 * u2) * p1 + (u3 - u2) * h * m1)
    deriv = ((6 * u2 - 6 * u) * p0 + (3 * u2 - 4 * u + 1) * h * m0
             + (-6 * u2 + 6 * u) * p1 + (3 * u2 - 2 * u) * h * m1) / h
    return value, deriv


class _Interp:
    """Catmull-Rom position / slerp rotation over one track."""

    def __init__(self, track: PoseTrack):
        self.track = track
        self.t = [float(v) for v in track.t]
        if len(self.t) < 2:
            raise CameraMotionError("camera.motion: a track of fewer than two samples cannot be resampled")
        self.tangents = {name: _tangents(self.t, getattr(track, name))
                         for name in ("north_m", "east_m", "alt_m")}

    def locate(self, at: float) -> Tuple[int, Optional[int]]:
        """(lower index, exact index or None)."""
        t = self.t
        if at < t[0] - 1e-9 or at > t[-1] + 1e-9:
            raise CameraMotionError(
                f"camera.motion: t={at:.6f} s lies outside the solved track "
                f"[{t[0]:.6f}, {t[-1]:.6f}]; resampling never extrapolates")
        j = bisect.bisect_left(t, at)
        for cand in (j - 1, j):
            if 0 <= cand < len(t) and abs(t[cand] - at) <= 1e-9:
                return min(cand, len(t) - 2), cand
        return max(0, min(j - 1, len(t) - 2)), None

    def position(self, at: float) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        i, _ = self.locate(at)
        pos, vel = [], []
        for name in ("north_m", "east_m", "alt_m"):
            p = getattr(self.track, name)
            m = self.tangents[name]
            v, d = _hermite(self.t[i], self.t[i + 1], p[i], p[i + 1], m[i], m[i + 1], at)
            pos.append(v)
            vel.append(d)
        return tuple(pos), tuple(vel)

    def speed(self, at: float) -> float:
        _, vel = self.position(at)
        return math.sqrt(sum(v * v for v in vel))


def _track_with(track: PoseTrack, **arrays) -> PoseTrack:
    return PoseTrack(
        camera_id=track.camera_id, preset=track.preset,
        horizon_stable=track.horizon_stable,
        t=tuple(arrays["t"]), north_m=tuple(arrays["north_m"]),
        east_m=tuple(arrays["east_m"]), alt_m=tuple(arrays["alt_m"]),
        quat=tuple(arrays["quat"]), yaw_deg=tuple(arrays["yaw_deg"]),
        pitch_deg=tuple(arrays["pitch_deg"]), roll_deg=tuple(arrays["roll_deg"]),
        focal_length_mm=tuple(arrays["focal_length_mm"]),
        sensor_width_mm=track.sensor_width_mm, sensor_height_mm=track.sensor_height_mm,
        width_px=track.width_px, height_px=track.height_px,
        near_m=track.near_m, far_m=track.far_m)


def resample_track(track: PoseTrack, times: Sequence[float]) -> PoseTrack:
    """The track at ``times`` (inside its span): Catmull-Rom position,
    slerp rotation, linear focal length (the commandlet's lerp). At an
    original sample time the original sample is copied verbatim. A
    horizon-stable track keeps roll exactly zero."""
    interp = _Interp(track)
    out: Dict[str, List[Any]] = {k: [] for k in (
        "t", "north_m", "east_m", "alt_m", "quat", "yaw_deg", "pitch_deg",
        "roll_deg", "focal_length_mm")}
    for at in times:
        at = float(at)
        i, exact = interp.locate(at)
        if exact is not None:
            out["t"].append(track.t[exact])
            for name in ("north_m", "east_m", "alt_m", "quat", "yaw_deg",
                         "pitch_deg", "roll_deg", "focal_length_mm"):
                out[name].append(getattr(track, name)[exact])
            continue
        (pn, pe, pa), _ = interp.position(at)
        frac = (at - interp.t[i]) / (interp.t[i + 1] - interp.t[i])
        q = quat_slerp(track.quat[i], track.quat[i + 1], frac)
        roll, pitch, yaw = quat_to_euler(q)
        if track.horizon_stable:
            roll = 0.0
            q = euler_to_quat(0.0, pitch, yaw)
        f0, f1 = track.focal_length_mm[i], track.focal_length_mm[i + 1]
        out["t"].append(at)
        out["north_m"].append(pn)
        out["east_m"].append(pe)
        out["alt_m"].append(pa)
        out["quat"].append(q)
        out["yaw_deg"].append(yaw)
        out["pitch_deg"].append(pitch)
        out["roll_deg"].append(roll)
        out["focal_length_mm"].append(f0 + frac * (f1 - f0))
    return _track_with(track, **out)


def dense_clock(times: Sequence[float],
                render_clock: Optional[Tuple[float, int]]) -> Tuple[List[float], List[int]]:
    """(dense times, index of each original time in them). The dense
    clock is t0 + k / (fps x accumulate) over the span, UNION the
    original times (so every telemetry sample is a dense sample)."""
    original = [float(v) for v in times]
    if render_clock is None:
        return original, list(range(len(original)))
    fps, accumulate = render_clock
    if not (float(fps) > 0.0) or int(accumulate) < 1:
        raise CameraMotionError(
            f"camera.motion: render clock {render_clock!r} needs fps > 0 and accumulate >= 1")
    hz = float(fps) * int(accumulate)
    t0, t1 = original[0], original[-1]
    count = int(math.floor((t1 - t0) * hz + 1e-9))
    merged = sorted(set(original) | {t0 + k / hz for k in range(count + 1)})
    dense: List[float] = []
    orig_set = set(original)
    for value in merged:
        if dense and value - dense[-1] <= 1e-9:
            if value in orig_set:          # keep the original spelling
                dense[-1] = value
            continue
        dense.append(value)
    index = []
    for value in original:
        j = bisect.bisect_left(dense, value - 1e-9)
        index.append(j)
    return dense, index


# -- the layer -----------------------------------------------------------

@dataclass(frozen=True)
class MotionPoseTrack(PoseTrack):
    """A pose track carrying camera motion. Its own arrays are the
    telemetry-clock samples (the indices the schedule and the manifest
    use, each the dense track's sample at that very time); ``dense`` is
    the render-clock track the card ships to the commandlet."""

    dense: Optional[PoseTrack] = field(default=None, compare=False)
    motion_record: Optional[Dict[str, Any]] = field(default=None, compare=False, hash=False)

    def digest(self) -> str:
        h = hashlib.sha256()
        h.update(PoseTrack.digest(self).encode())
        if self.dense is not None:
            h.update(b"dense")
            h.update(self.dense.digest().encode())
        h.update(json.dumps(self.motion_record, sort_keys=True).encode("utf-8"))
        return h.hexdigest()

    def card_block(self, camera, schedule, frame) -> Dict[str, object]:
        block = PoseTrack.card_block(self, camera, schedule, frame)
        if self.dense is not None:
            d = self.dense
            block["poses"] = {
                "t_s": list(d.t), "north_m": list(d.north_m),
                "east_m": list(d.east_m), "alt_m": list(d.alt_m),
                "yaw_deg": list(d.yaw_deg), "pitch_deg": list(d.pitch_deg),
                "roll_deg": list(d.roll_deg),
                "focal_length_mm": list(d.focal_length_mm),
            }
        if self.motion_record is not None:
            block["camera_motion"] = dict(self.motion_record)
        return block


def _unwrap(degrees: Sequence[float]) -> List[float]:
    out: List[float] = []
    for value in degrees:
        if not out:
            out.append(float(value))
            continue
        step = ((float(value) - out[-1] + 180.0) % 360.0) - 180.0
        out.append(out[-1] + step)
    return out


def _lagged(series: Sequence[float], t: Sequence[float], zeta: float, fn: float) -> List[float]:
    """The second-order lag over a series; starts at the first value at
    the first interval's slope (declared, like poses' start-where-it-settles)."""
    if len(series) < 2:
        return list(series)
    y = series[0]
    ydot = (series[1] - series[0]) / (t[1] - t[0])
    out = [y]
    for i in range(1, len(series)):
        y, ydot = second_order_step(y, ydot, series[i - 1], series[i], t[i] - t[i - 1], zeta, fn)
        out.append(y)
    return out


def apply_motion(track: PoseTrack, spec: Optional[Mapping[str, Any]],
                 render_clock: Optional[Tuple[float, int]] = None
                 ) -> Tuple[PoseTrack, Dict[str, Any]]:
    """(track with motion, record). Profile none (or no block) returns
    the input track itself, unresampled, so every digest is unchanged."""
    motion = normalise_motion(spec)
    profile = motion["profile"]
    if profile == "none":
        return track, {"profile": "none"}
    table = PROFILES[profile]
    seed, intensity = motion["seed"], motion["intensity"]
    bp = motion.get("blade_pass_hz")
    cam = track.camera_id
    times, index = dense_clock(track.t, render_clock)
    base = track if len(times) == len(track.t) else resample_track(track, times)
    interp = _Interp(track)

    yaw = list(base.yaw_deg)
    pitch = list(base.pitch_deg)
    lag = table.get("aim_lag")
    if lag:
        yaw = [v % 360.0 for v in _lagged(_unwrap(yaw), times, lag["zeta"], lag["fn_hz"])]
        pitch = _lagged(pitch, times, lag["zeta"], lag["fn_hz"])

    lo, hi = table.get("speed_scale_bounds", (1.0, 1.0))
    ref = float(table.get("reference_speed_mps", 0.0) or 0.0)
    arrays: Dict[str, List[Any]] = {k: [] for k in (
        "north_m", "east_m", "alt_m", "quat", "yaw_deg", "pitch_deg",
        "roll_deg", "focal_length_mm")}
    shake_sq = {axis: 0.0 for axis in ROTATION_AXES}
    clamped = 0
    for j, at in enumerate(times):
        scale = 1.0
        if ref > 0.0:
            scale = max(lo, min(hi, interp.speed(at) / ref))

        def noise(axis):
            return band_noise(at, seed, cam, axis, profile, intensity, scale, bp)

        d_yaw, d_pitch, d_roll = noise("yaw"), noise("pitch"), noise("roll")
        if abs(d_roll) > ROLL_BOUND_DEG:
            clamped += 1
            d_roll = math.copysign(ROLL_BOUND_DEG, d_roll)
        shake_sq["yaw"] += d_yaw * d_yaw
        shake_sq["pitch"] += d_pitch * d_pitch
        shake_sq["roll"] += d_roll * d_roll
        y = (yaw[j] + d_yaw) % 360.0
        p = pitch[j] + d_pitch
        r = base.roll_deg[j] + d_roll
        arrays["yaw_deg"].append(y)
        arrays["pitch_deg"].append(p)
        arrays["roll_deg"].append(r)
        arrays["quat"].append(euler_to_quat(r, p, y))
        arrays["north_m"].append(base.north_m[j] + noise("north"))
        arrays["east_m"].append(base.east_m[j] + noise("east"))
        arrays["alt_m"].append(base.alt_m[j] + noise("up"))
        arrays["focal_length_mm"].append(base.focal_length_mm[j])
    dense = _track_with(track, t=list(times), **arrays)

    n = len(times)
    hz = (float(render_clock[0]) * int(render_clock[1])) if render_clock else None
    record: Dict[str, Any] = {
        "profile": profile,
        "seed": seed,
        "intensity": intensity,
        "n_sinusoids": n_sinusoids(profile),
        "rms_deg": {axis: math.sqrt(shake_sq[axis] / n) for axis in ROTATION_AXES},
        "nominal_rms_deg": {axis: float(table["rotation_rms_deg"][axis]) * intensity
                            for axis in ROTATION_AXES},
        "roll_bound_deg": ROLL_BOUND_DEG,
        "roll_clamped_samples": clamped,
        "dense_clock_hz": hz,
        "dense_samples": n,
        "label_pose": "shutter-centre sample",
        "basis": "pose track: beauty and labels share it",
        "aim_lag": dict(lag) if lag else None,
        "uncalibrated": True,
    }
    if bp is not None:
        record["blade_pass_hz"] = bp
        record["turbulence_scale_basis"] = (
            "camera speed from the solved track (Catmull-Rom derivative), "
            f"clamp(speed / {ref:g} m/s, {lo:g}, {hi:g}); wind not included")
    if motion.get("source"):
        record["source"] = motion["source"]

    sparse = {name: [getattr(dense, name)[j] for j in index]
              for name in ("north_m", "east_m", "alt_m", "quat", "yaw_deg",
                           "pitch_deg", "roll_deg", "focal_length_mm")}
    sparse_track = _track_with(track, t=list(track.t), **sparse)
    out = MotionPoseTrack(**{f: getattr(sparse_track, f) for f in PoseTrack.__dataclass_fields__},
                          dense=dense if render_clock is not None else None,
                          motion_record=record)
    return out, record


# -- the web look switch ---------------------------------------------------

def look_motion(look: Optional[Mapping[str, Any]], preset: str) -> Optional[Dict[str, Any]]:
    """The motion block a look switch asks for on a camera of ``preset``:
    the 'cinematic' switch (camera_motion 'auto') gives cockpit cameras
    handheld at 0.5 (airframe vibration), airborne external presets
    (chase, wingman) camera_ship at 1, and world-anchored presets
    (ground, tower, explicit) tripod_fluid_head at 1. Anything else: None.
    The intensity mapping is UNCALIBRATED."""
    if not look or look.get("camera_motion") != "auto":
        return None
    source = f"look switch {look.get('switch', '?')}"
    if preset == "cockpit":
        return {"profile": "handheld", "seed": 0, "intensity": 0.5, "source": source}
    if preset in ("chase", "wingman"):
        return {"profile": "camera_ship", "seed": 0, "intensity": 1.0, "source": source}
    return {"profile": "tripod_fluid_head", "seed": 0, "intensity": 1.0, "source": source}


def is_still_camera(camera) -> bool:
    """A camera that takes ONE frame (the web UI's 1-frame preview sets
    ``capture_count`` 1, webapp/server.py): a still. Read defensively, so a
    camera-like object without the field is not a still."""
    count = getattr(camera, "capture_count", None)
    value = getattr(count, "value", count)
    try:
        return int(value or 0) == 1
    except (TypeError, ValueError):
        return False


def apply_look_motion(spec, look: Optional[Mapping[str, Any]]) -> List[str]:
    """Give every camera that states no motion the look switch's block;
    a stated block is never moved. Returns the camera ids changed.

    aircraft-sharp (visual overhaul round 2): a STILL camera
    (:func:`is_still_camera`) gets no look motion. A still is one instant;
    its beauty sub-captures are one pose, and a shake sampled at that
    instant only offsets the framing the director chose (with nothing to
    show for it but a tilted, off-centre airframe). The camera keeps no
    motion block, so its track digest is the plain solve's, byte-identical.
    A motion block the user STATED is still never moved."""
    changed = []
    for camera in getattr(spec, "cameras", None) or []:
        if getattr(camera, "motion", None) is not None:
            continue
        if is_still_camera(camera):
            continue
        block = look_motion(look, str(camera.preset.value))
        if block is not None:
            camera.motion = block
            changed.append(str(camera.camera_id.value))
    return changed
