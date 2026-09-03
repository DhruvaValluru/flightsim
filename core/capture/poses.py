"""Deterministic camera pose solving: telemetry in, pose track out.

Camera Phase 1's design decision 1, the run-card discipline applied to
cameras: the pose track is COMPUTED IN PYTHON as a pure function of the
recorded telemetry and the camera spec, and every consumer -- the
capture manifest, the geometry verifier, the preview renderer, and (on
macOS) the render commandlet's consume-poses mode -- reads the same
solved track verbatim. No engine, no wall clock, no RNG, no frame-rate
dependence: two invocations over the same telemetry are bit-identical,
and the suite compares them by digest.

The five presets are ported from
``ue/.../FlightSimCameraDirector.cpp`` faithfully:

* **chase** / **wingman** -- the offset is applied in a HEADING-ONLY
  frame (yaw from the aircraft, pitch and roll discarded; §1.5: using
  the full rotation is precisely the historic failure), position and
  aim exponentially smoothed with the C++ time constants
  (:data:`POSITION_LAG_S`, :data:`AIM_LAG_S`; the wingman's
  station-keeping is twice as tight). The look rotation never inherits
  roll.
* **ground** / **tower** -- world-anchored: the camera does not move;
  only the aim point is smoothed toward the aircraft. Roll stays zero.
* **cockpit** -- body-fixed, no smoothing, FULL rotation applied: roll
  is inherited BY DECLARATION (``horizon_stable`` is False, mirroring
  ``PresetKeepsHorizonLevel()``), and nothing recorded from this camera
  may be graded as aircraft motion.
* **explicit** -- a stated placement with no preset behaviour: position
  and aim exactly as stated (or keyframed), no smoothing.

Smoothing is the C++ ``SmoothTowards`` filter discretised on the
telemetry clock: ``alpha = 1 - exp(-dt / tau)`` with dt the recorded
sample spacing, so the lag is a time constant, never a per-frame
fraction. The initial condition is DECLARED (the C++ actor starts
wherever it was spawned; the solver has no spawn): the smoothed
position starts AT its first goal and the smoothed aim at the
aircraft, which is exactly the commandlet's own "start it where it
will settle" placement.

Frames and conventions (the manifest's contract):

* Positions are local **north/east metres about the scene origin** plus
  **altitude in metres MSL** -- the same projected frame every
  position-coupled card block uses (:class:`SceneFrame` reuses the
  webapp's ``_projected_origin`` pattern: terrain scenes project
  through the raster's own CRS, flat scenes through the spec origin's
  UTM zone).
* Orientation is aerospace yaw/pitch/roll (intrinsic Z-Y'-X'': yaw
  degrees true from north toward east, pitch positive up, roll positive
  right-wing-down) AND the equivalent unit quaternion (w, x, y, z) in
  the NED frame.
* The camera's view axes: forward along the look direction,
  right = forward x up(world) (yaw-pitch-roll applied), up completing
  the triad. Projection into pixels is documented in
  :mod:`core.capture.manifest`.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..scenario.camera import CameraSpec

#: The C++ director's spring-arm time constants, seconds.
POSITION_LAG_S = 0.45
AIM_LAG_S = 0.25
#: "Station-keeping is tighter than a chase: a wingman holds position."
WINGMAN_POSITION_LAG_FACTOR = 0.5

#: Telemetry channels the solver consumes. Missing ones refuse by name.
REQUIRED_CHANNELS = ("t", "lat_deg", "lon_deg", "altitude_m",
                     "roll_deg", "pitch_deg", "heading_deg")


class PoseSolveError(Exception):
    """The pose track could not be solved; named, never approximated."""

    constraint = "camera.poses"


# -- the scene frame -----------------------------------------------------

class SceneFrame:
    """The projected local frame every position-coupled block shares.

    Terrain scenes work in the raster's own CRS (``crs_declared`` is
    None: the terrain declares it to the host); flat scenes use the
    spec origin's UTM zone and must DECLARE it on the card
    (``scene_crs``), exactly the webapp's ``_projected_origin``.
    """

    def __init__(self, crs: str, origin_lat_deg: float,
                 origin_lon_deg: float, declared: bool) -> None:
        from pyproj import Transformer

        self.crs = str(crs)
        self.origin_lat_deg = float(origin_lat_deg)
        self.origin_lon_deg = float(origin_lon_deg)
        self.declared = bool(declared)
        self._forward = Transformer.from_crs("EPSG:4326", self.crs,
                                             always_xy=True)
        self._inverse = Transformer.from_crs(self.crs, "EPSG:4326",
                                             always_xy=True)
        ox, oy = self._forward.transform(self.origin_lon_deg,
                                         self.origin_lat_deg)
        self.origin_x_m = float(ox)
        self.origin_y_m = float(oy)

    @classmethod
    def for_spec(cls, spec, heightfield=None) -> "SceneFrame":
        """Terrain scenes: the raster's CRS. Flat scenes: the origin's
        UTM zone, declared."""
        lat = float(spec.latitude.value)
        lon = float(spec.longitude.value)
        if heightfield is not None:
            return cls(heightfield.georeference.crs, lat, lon,
                       declared=False)
        from ..terrain.glo30 import utm_zone_crs

        return cls(utm_zone_crs(lat, lon), lat, lon, declared=True)

    def to_local(self, lat_deg: float, lon_deg: float) -> Tuple[float, float]:
        """(north_m, east_m) about the origin."""
        x, y = self._forward.transform(float(lon_deg), float(lat_deg))
        return float(y - self.origin_y_m), float(x - self.origin_x_m)

    def to_geographic(self, north_m: float,
                      east_m: float) -> Tuple[float, float]:
        """(lat_deg, lon_deg) of a local position."""
        lon, lat = self._inverse.transform(self.origin_x_m + east_m,
                                           self.origin_y_m + north_m)
        return float(lat), float(lon)

    def to_projected(self, north_m: float,
                     east_m: float) -> Tuple[float, float]:
        """(x_m, y_m) in the frame's own CRS -- what a Heightfield
        query wants."""
        return self.origin_x_m + east_m, self.origin_y_m + north_m

    def provenance(self) -> Dict[str, object]:
        return {"crs": self.crs,
                "origin_lat_deg": self.origin_lat_deg,
                "origin_lon_deg": self.origin_lon_deg,
                "origin_x_m": self.origin_x_m,
                "origin_y_m": self.origin_y_m,
                "declared_on_card": self.declared}


# -- rotation helpers ----------------------------------------------------

def euler_to_quat(roll_deg: float, pitch_deg: float,
                  yaw_deg: float) -> Tuple[float, float, float, float]:
    """Aerospace intrinsic Z-Y'-X'' euler -> unit quaternion (w,x,y,z),
    NED frame."""
    r = math.radians(roll_deg) / 2.0
    p = math.radians(pitch_deg) / 2.0
    y = math.radians(yaw_deg) / 2.0
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return (cr * cp * cy + sr * sp * sy,
            sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy)


def quat_slerp(a: Sequence[float], b: Sequence[float],
               fraction: float) -> Tuple[float, float, float, float]:
    """Spherical interpolation on the shorter arc; deterministic."""
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b = tuple(-x for x in b)
        dot = -dot
    dot = min(dot, 1.0)
    theta = math.acos(dot)
    if theta < 1e-9:
        out = tuple(x + fraction * (y - x) for x, y in zip(a, b))
    else:
        sa = math.sin((1.0 - fraction) * theta) / math.sin(theta)
        sb = math.sin(fraction * theta) / math.sin(theta)
        out = tuple(sa * x + sb * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in out))
    return tuple(x / norm for x in out)


def _rotate_body_to_ned(roll_deg, pitch_deg, yaw_deg, forward, right, up):
    """Rotate a body-frame offset (forward, right, up) into
    (north, east, up) through the full attitude."""
    r = math.radians(roll_deg)
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    # Body vector in the NED convention: x forward, y right, z DOWN.
    bx, by, bz = forward, right, -up
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    # Standard aerospace DCM body->NED.
    n = (cp * cy) * bx + (sr * sp * cy - cr * sy) * by \
        + (cr * sp * cy + sr * sy) * bz
    e = (cp * sy) * bx + (sr * sp * sy + cr * cy) * by \
        + (cr * sp * sy - sr * cy) * bz
    d = (-sp) * bx + (sr * cp) * by + (cr * cp) * bz
    return n, e, -d


def _heading_only(heading_deg, forward, right, up):
    """Rotate an offset in the heading-only frame (yaw applied, pitch
    and roll DISCARDED -- the §1.5 rule)."""
    y = math.radians(heading_deg)
    cy, sy = math.cos(y), math.sin(y)
    n = forward * cy - right * sy
    e = forward * sy + right * cy
    return n, e, up


def look_angles(from_n, from_e, from_alt, to_n, to_e, to_alt):
    """(yaw_deg, pitch_deg) of the look direction; roll is zero by
    construction (the presets never inherit roll)."""
    dn, de, dalt = to_n - from_n, to_e - from_e, to_alt - from_alt
    yaw = math.degrees(math.atan2(de, dn)) % 360.0
    pitch = math.degrees(math.atan2(dalt, math.hypot(dn, de)))
    return yaw, pitch


# -- keyframed moves -----------------------------------------------------

def _keyframe_value(moves: List[Dict], key: str, t: float,
                    default: float) -> float:
    """Piecewise-linear interpolation of one keyframed scalar over
    simulation time; holds the boundary values outside the keyed span.
    Pure function of (moves, t): sampling the same keyframes on a
    different telemetry clock agrees at shared times by construction.
    """
    keyed = sorted((float(m["t_s"]), float(m[key])) for m in moves
                   if key in m)
    if not keyed:
        return default
    if t <= keyed[0][0]:
        return keyed[0][1]
    if t >= keyed[-1][0]:
        return keyed[-1][1]
    for (t0, v0), (t1, v1) in zip(keyed, keyed[1:]):
        if t0 <= t <= t1:
            if t1 == t0:
                return v1
            fraction = (t - t0) / (t1 - t0)
            return v0 + fraction * (v1 - v0)
    return keyed[-1][1]           # unreachable; keeps the checker honest


def _keyframed_bearing_quat(moves: List[Dict], t: float,
                            default_bearing: float,
                            default_elevation: float):
    """Slerp between bearing/elevation keyframes: orientation moves on
    the sphere, never through a wrapped euler discontinuity."""
    keyed = sorted((float(m["t_s"]),
                    euler_to_quat(0.0,
                                  float(m.get("aim_elevation_deg",
                                              default_elevation)),
                                  float(m.get("aim_bearing_deg",
                                              default_bearing))))
                   for m in moves
                   if "aim_bearing_deg" in m or "aim_elevation_deg" in m)
    if not keyed:
        return None
    if t <= keyed[0][0]:
        return keyed[0][1]
    if t >= keyed[-1][0]:
        return keyed[-1][1]
    for (t0, q0), (t1, q1) in zip(keyed, keyed[1:]):
        if t0 <= t <= t1:
            fraction = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return quat_slerp(q0, q1, fraction)
    return keyed[-1][1]


# -- the pose track ------------------------------------------------------

@dataclass(frozen=True)
class PoseTrack:
    """The solved per-sample camera track, parallel tuples."""

    camera_id: str
    preset: str
    horizon_stable: bool
    t: Tuple[float, ...]
    north_m: Tuple[float, ...]
    east_m: Tuple[float, ...]
    alt_m: Tuple[float, ...]
    #: Unit quaternion (w, x, y, z), NED frame.
    quat: Tuple[Tuple[float, float, float, float], ...]
    yaw_deg: Tuple[float, ...]
    pitch_deg: Tuple[float, ...]
    roll_deg: Tuple[float, ...]
    #: Per-sample focal length (keyframed moves may vary it).
    focal_length_mm: Tuple[float, ...]
    #: Constant intrinsics.
    sensor_width_mm: float
    sensor_height_mm: float
    width_px: int
    height_px: int
    near_m: float
    far_m: float

    def __len__(self) -> int:
        return len(self.t)

    def digest(self) -> str:
        """SHA-256 over repr of every float, the _digest_telemetry
        convention: exact, never rounded -- bit-identical or different."""
        h = hashlib.sha256()
        for name in ("t", "north_m", "east_m", "alt_m", "yaw_deg",
                     "pitch_deg", "roll_deg", "focal_length_mm"):
            h.update(name.encode())
            for value in getattr(self, name):
                h.update(repr(value).encode())
        h.update(b"quat")
        for q in self.quat:
            for value in q:
                h.update(repr(value).encode())
        return h.hexdigest()

    def card_block(self, camera: CameraSpec, schedule,
                   frame: "SceneFrame") -> Dict[str, object]:
        """The run card's ``cameras[]`` entry: spec fields AND the
        solved per-sample pose track, computed here and consumed
        VERBATIM by the render host's consume-poses mode (the wind-
        schedule discipline applied to cameras). Positions ride as
        local north/east about the same projected origin every
        position-coupled block uses; orientation as aerospace
        yaw/pitch/roll degrees. The host derives nothing and refuses a
        track that does not cover the run.
        """
        return {
            "camera_id": self.camera_id,
            "preset": self.preset,
            "horizon_stable": self.horizon_stable,
            "origin_x_m": frame.origin_x_m,
            "origin_y_m": frame.origin_y_m,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "sensor_width_mm": self.sensor_width_mm,
            "sensor_height_mm": self.sensor_height_mm,
            "near_m": self.near_m,
            "far_m": self.far_m,
            "spec": camera.to_dict(),
            "poses": {
                "t_s": list(self.t),
                "north_m": list(self.north_m),
                "east_m": list(self.east_m),
                "alt_m": list(self.alt_m),
                "yaw_deg": list(self.yaw_deg),
                "pitch_deg": list(self.pitch_deg),
                "roll_deg": list(self.roll_deg),
                "focal_length_mm": list(self.focal_length_mm),
            },
            "capture_times_s": list(schedule.times),
        }

    def sample(self, index: int) -> Dict[str, object]:
        """One pose as the manifest's per-frame mapping."""
        return {
            "t_s": self.t[index],
            "position_north_m": self.north_m[index],
            "position_east_m": self.east_m[index],
            "position_alt_m": self.alt_m[index],
            "quaternion_wxyz": list(self.quat[index]),
            "yaw_deg": self.yaw_deg[index],
            "pitch_deg": self.pitch_deg[index],
            "roll_deg": self.roll_deg[index],
            "focal_length_mm": self.focal_length_mm[index],
        }


def camera_card_blocks(cameras: Sequence[CameraSpec],
                       tracks: Sequence[PoseTrack],
                       schedules: Sequence,
                       frame: "SceneFrame") -> List[Dict[str, object]]:
    """The run card's ``cameras`` block: one entry per camera from its
    solved track and schedule. THE one builder -- the CLI's --card and
    the webapp's frames flow both call it, so the card the engine
    consumes cannot drift between the two producers."""
    if not (len(cameras) == len(tracks) == len(schedules)):
        raise PoseSolveError(
            f"{len(cameras)} cameras against {len(tracks)} tracks and "
            f"{len(schedules)} schedules; refusing a misattributed card")
    blocks = []
    for camera, track, schedule in zip(cameras, tracks, schedules):
        if track.camera_id != schedule.camera_id or \
                track.camera_id != str(camera.camera_id.value):
            raise PoseSolveError(
                f"camera {camera.camera_id.value!r} paired with track "
                f"{track.camera_id!r} and schedule "
                f"{schedule.camera_id!r}; refusing a misattributed card")
        blocks.append(track.card_block(camera, schedule, frame))
    return blocks


def _columns(columns: Dict[str, Sequence[float]]):
    missing = [name for name in REQUIRED_CHANNELS if name not in columns]
    if missing:
        raise PoseSolveError(
            f"camera.poses: telemetry is missing channel(s) "
            f"{missing}; the pose solver consumes the recorded track "
            f"and never invents one")
    n = len(columns["t"])
    if n < 2:
        raise PoseSolveError(
            "camera.poses: fewer than two telemetry samples; there is "
            "no track to solve a camera against")
    for name in REQUIRED_CHANNELS:
        if len(columns[name]) != n:
            raise PoseSolveError(
                f"camera.poses: channel {name!r} has "
                f"{len(columns[name])} samples where t has {n}; refusing "
                f"a misaligned record")
    return n


def solve_pose_track(columns: Dict[str, Sequence[float]],
                     camera: CameraSpec,
                     frame: SceneFrame) -> PoseTrack:
    """Solve one camera's pose track over the recorded telemetry.

    Pure: same inputs, bit-identical output (the suite pins this by
    digest). ``columns`` is the Recorder's own mapping (0.1 s clock,
    but nothing here assumes the rate -- dt comes from the recorded t).
    """
    n = _columns(columns)
    t = [float(v) for v in columns["t"]]
    # Aircraft track in the local frame.
    air_n: List[float] = []
    air_e: List[float] = []
    for lat, lon in zip(columns["lat_deg"], columns["lon_deg"]):
        north, east = frame.to_local(float(lat), float(lon))
        air_n.append(north)
        air_e.append(east)
    air_alt = [float(v) for v in columns["altitude_m"]]
    air_roll = [float(v) for v in columns["roll_deg"]]
    air_pitch = [float(v) for v in columns["pitch_deg"]]
    air_yaw = [float(v) for v in columns["heading_deg"]]

    preset = str(camera.preset.value)
    if preset not in ("chase", "ground", "wingman", "tower", "cockpit",
                     "explicit"):
        raise PoseSolveError(f"camera.poses: unknown preset {preset!r}")

    offset = (float(camera.offset_forward_m.value),
              float(camera.offset_right_m.value),
              float(camera.offset_up_m.value))

    pos_n: List[float] = []
    pos_e: List[float] = []
    pos_alt: List[float] = []
    yaw: List[float] = []
    pitch: List[float] = []
    roll: List[float] = []
    quat: List[Tuple[float, float, float, float]] = []

    def _static_position(at_t: float):
        """Stated placement (scene metres or geographic), keyframable."""
        mode = str(camera.position_mode.value)
        if mode == "geographic":
            lat = _keyframe_value(camera.moves, "position_lat_deg", at_t,
                                  float(camera.position_lat_deg.value))
            lon = _keyframe_value(camera.moves, "position_lon_deg", at_t,
                                  float(camera.position_lon_deg.value))
            north, east = frame.to_local(lat, lon)
        elif mode == "scene":
            north = _keyframe_value(camera.moves, "position_north_m", at_t,
                                    float(camera.position_north_m.value))
            east = _keyframe_value(camera.moves, "position_east_m", at_t,
                                   float(camera.position_east_m.value))
        else:
            raise PoseSolveError(
                f"camera.poses: preset {preset!r} needs position_mode "
                f"'scene' or 'geographic', got {mode!r} -- an offset "
                f"placement has no world anchor")
        alt = _keyframe_value(camera.moves, "position_alt_m", at_t,
                              float(camera.position_alt_m.value))
        return north, east, alt

    if preset in ("chase", "wingman"):
        tau_pos = POSITION_LAG_S * (WINGMAN_POSITION_LAG_FACTOR
                                    if preset == "wingman" else 1.0)
        sm_n = sm_e = sm_alt = None
        aim_n = aim_e = aim_alt = None
        for i in range(n):
            gn, ge, gup = _heading_only(air_yaw[i], *offset)
            goal = (air_n[i] + gn, air_e[i] + ge, air_alt[i] + gup)
            target = (air_n[i], air_e[i], air_alt[i])
            if i == 0:
                sm_n, sm_e, sm_alt = goal          # start where it settles
                aim_n, aim_e, aim_alt = target
            else:
                dt = t[i] - t[i - 1]
                ap = 1.0 - math.exp(-dt / tau_pos)
                aa = 1.0 - math.exp(-dt / AIM_LAG_S)
                sm_n += (goal[0] - sm_n) * ap
                sm_e += (goal[1] - sm_e) * ap
                sm_alt += (goal[2] - sm_alt) * ap
                aim_n += (target[0] - aim_n) * aa
                aim_e += (target[1] - aim_e) * aa
                aim_alt += (target[2] - aim_alt) * aa
            y, p = look_angles(sm_n, sm_e, sm_alt, aim_n, aim_e, aim_alt)
            pos_n.append(sm_n)
            pos_e.append(sm_e)
            pos_alt.append(sm_alt)
            yaw.append(y)
            pitch.append(p)
            roll.append(0.0)                       # never inherit roll
            quat.append(euler_to_quat(0.0, p, y))
    elif preset in ("ground", "tower", "explicit"):
        aim_mode = str(camera.aim_mode.value)
        aim_n = aim_e = aim_alt = None
        for i in range(n):
            cn, ce, calt = _static_position(t[i])
            if aim_mode == "aircraft":
                target = (air_n[i], air_e[i], air_alt[i])
                if preset == "explicit":
                    # Explicit cameras aim exactly; only the PORTED
                    # world-anchored presets carry the C++ aim lag.
                    aim_n, aim_e, aim_alt = target
                elif i == 0:
                    aim_n, aim_e, aim_alt = target
                else:
                    dt = t[i] - t[i - 1]
                    aa = 1.0 - math.exp(-dt / AIM_LAG_S)
                    aim_n += (target[0] - aim_n) * aa
                    aim_e += (target[1] - aim_e) * aa
                    aim_alt += (target[2] - aim_alt) * aa
                y, p = look_angles(cn, ce, calt, aim_n, aim_e, aim_alt)
                q = euler_to_quat(0.0, p, y)
            elif aim_mode == "point":
                pn = _keyframe_value(camera.moves, "aim_north_m", t[i],
                                     float(camera.aim_north_m.value))
                pe = _keyframe_value(camera.moves, "aim_east_m", t[i],
                                     float(camera.aim_east_m.value))
                palt = _keyframe_value(camera.moves, "aim_alt_m", t[i],
                                       float(camera.aim_alt_m.value))
                y, p = look_angles(cn, ce, calt, pn, pe, palt)
                q = euler_to_quat(0.0, p, y)
            elif aim_mode == "bearing":
                q = _keyframed_bearing_quat(
                    camera.moves, t[i],
                    float(camera.aim_bearing_deg.value),
                    float(camera.aim_elevation_deg.value))
                if q is None:
                    y = float(camera.aim_bearing_deg.value) % 360.0
                    p = float(camera.aim_elevation_deg.value)
                    q = euler_to_quat(0.0, p, y)
                else:
                    y, p = _quat_yaw_pitch(q)
            else:
                raise PoseSolveError(
                    f"camera.poses: unknown aim mode {aim_mode!r}")
            pos_n.append(cn)
            pos_e.append(ce)
            pos_alt.append(calt)
            yaw.append(y % 360.0)
            pitch.append(p)
            roll.append(0.0)
            quat.append(q)
    else:                                          # cockpit
        for i in range(n):
            dn, de, dup = _rotate_body_to_ned(
                air_roll[i], air_pitch[i], air_yaw[i], *offset)
            pos_n.append(air_n[i] + dn)
            pos_e.append(air_e[i] + de)
            pos_alt.append(air_alt[i] + dup)
            # Full rotation applied -- roll inherited BY DECLARATION.
            yaw.append(air_yaw[i] % 360.0)
            pitch.append(air_pitch[i])
            roll.append(air_roll[i])
            quat.append(euler_to_quat(air_roll[i], air_pitch[i],
                                      air_yaw[i]))

    focal = [_keyframe_value(camera.moves, "focal_length_mm", ti,
                             float(camera.focal_length_mm.value))
             for ti in t]

    return PoseTrack(
        camera_id=str(camera.camera_id.value),
        preset=preset,
        # Mirrors PresetKeepsHorizonLevel(): only the cockpit preset
        # inherits roll, and the record says so.
        horizon_stable=preset != "cockpit",
        t=tuple(t),
        north_m=tuple(pos_n), east_m=tuple(pos_e), alt_m=tuple(pos_alt),
        quat=tuple(quat),
        yaw_deg=tuple(yaw), pitch_deg=tuple(pitch), roll_deg=tuple(roll),
        focal_length_mm=tuple(focal),
        sensor_width_mm=float(camera.sensor_width_mm.value),
        sensor_height_mm=float(camera.sensor_height_mm.value),
        width_px=int(camera.width_px.value),
        height_px=int(camera.height_px.value),
        near_m=float(camera.near_m.value),
        far_m=float(camera.far_m.value),
    )


def _quat_yaw_pitch(q) -> Tuple[float, float]:
    """(yaw_deg, pitch_deg) of a roll-free quaternion."""
    w, x, y, z = q
    yaw = math.degrees(math.atan2(2.0 * (w * z + x * y),
                                  1.0 - 2.0 * (y * y + z * z))) % 360.0
    sinp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.degrees(math.asin(sinp))
    return yaw, pitch


def aircraft_local_track(columns: Dict[str, Sequence[float]],
                         frame: SceneFrame):
    """The aircraft's own (north, east, alt, roll, pitch, heading) per
    sample in the scene frame -- the manifest's aircraft-state block,
    computed once here so every consumer shares one projection."""
    _columns(columns)
    out = []
    for i in range(len(columns["t"])):
        north, east = frame.to_local(float(columns["lat_deg"][i]),
                                     float(columns["lon_deg"][i]))
        out.append({
            "t_s": float(columns["t"][i]),
            "north_m": north, "east_m": east,
            "alt_m": float(columns["altitude_m"][i]),
            "roll_deg": float(columns["roll_deg"][i]),
            "pitch_deg": float(columns["pitch_deg"][i]),
            "heading_deg": float(columns["heading_deg"][i]),
        })
    return out
