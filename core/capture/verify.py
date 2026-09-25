"""Verification: can the recorded geometry actually be used as labels?

What a verifier is allowed to claim
-----------------------------------
A manifest is a closed document. Projecting a point out of it and then
back-projecting the result through the same numbers returns the point
you started with, whatever those numbers are -- so any check built only
out of the manifest's own projection is incapable of failing. Phase 1
learned this the expensive way: its cross-view check cast both rays
through each record's copy of ONE aircraft array, reported
``0.0000 m`` error, and passed with a camera displaced 300 m, with
every focal length scaled by 1.7, and with the aircraft states swapped
between cameras. The docstring claimed it caught exactly those cases.

So this module is organised around what each check's *independent
reference* actually is:

* **the specification** -- the camera the user asked for is an input to
  the solver, not an output of it, so grading the solved track against
  it is a real test. :func:`verify_intrinsics` and
  :func:`verify_pose_matches_spec` are the two checks that can fail on
  a geometry bug with no engine present, and they are what make the
  off-Windows run worth running.
* **the engine** -- the render commandlet projects the manifest's own
  landmarks through its own ``ProjectToPixel`` and writes the pixels
  into ``render.json``. Comparing those against this module's
  projection is two implementations in two languages, and it is the
  independent reprojection the phase exit criterion asks for.
  :func:`verify_landmark_reprojection` and
  :func:`verify_triangulation` need it and report **NOT RUN** without
  it rather than passing on a tautology.
* **a second run** -- two captures of the same simulation with
  different cameras (:func:`verify_alignment`).

A check that could not execute reports NOT RUN, is named in the
summary, and is excluded from the pass tally. A green summary that
silently omitted half its checks is worse than a red one.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: Pixel agreement demanded between the quaternion and Euler encodings
#: of one recorded orientation.
REPROJECTION_TOL_PX = 0.5
#: Pixel agreement demanded between this module's projection and the
#: engine's own, for the same landmark in the same frame.
ENGINE_TOL_PX = 2.0
#: Metre agreement demanded of two-view triangulation.
TRIANGULATION_TOL_M = 0.5
#: Frame-time agreement across runs (times come off the same recorded
#: telemetry clock, so this is a float-representation tolerance).
TIME_TOL_S = 1e-9
#: Placement agreement for a camera whose position the user STATED, in
#: scene metres. A stated field is never silently moved, so this is a
#: representation tolerance, not a budget.
STATED_POSITION_TOL_M = 1e-6
#: The same for a geographic placement, which round-trips through the
#: scene's projection.
GEOGRAPHIC_POSITION_TOL_M = 0.5
#: How far an aircraft-aimed camera's forward axis may sit off the
#: direction to the aircraft. The ported presets smooth their aim, so
#: this bounds the lag rather than demanding an exact hit.
AIM_TOL_DEG = 25.0
#: Below this separation an aim direction is degenerate (a cockpit
#: camera is AT the aircraft), so the aim clause does not apply.
AIM_DEGENERATE_M = 20.0

PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT RUN"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    #: The catalogue name of what failed (contracts §4, §11), carried on
    #: FAIL only: a refusal is by name, never only in the prose. None on
    #: PASS / NOT RUN and on the checks that predate the key; readers of
    #: verification.json take it by key and tolerate its absence.
    failure: Optional[str] = None

    @property
    def ok(self) -> bool:
        """NOT RUN is not a failure -- but it is not a pass either, and
        :meth:`VerificationReport.render` counts it separately."""
        return self.status != FAIL

    def to_dict(self) -> Dict[str, str]:
        out = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.status == FAIL and self.failure:
            out["failure"] = self.failure
        return out


@dataclass
class VerificationReport:
    checks: List[Check] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, status_or_ok, detail: str,
            failure: Optional[str] = None) -> None:
        if isinstance(status_or_ok, bool):
            status_or_ok = PASS if status_or_ok else FAIL
        self.checks.append(Check(name, status_or_ok, detail, failure))

    def failures(self) -> List[Check]:
        """The FAIL checks, in report order (their ``failure`` names are
        what the CLI prints as refusals)."""
        return [c for c in self.checks if c.status == FAIL]

    def to_dict(self) -> Dict:
        """The record a run directory keeps (verification.json): every
        check with its status, and the counts -- NOT RUN counted apart,
        never as a pass."""
        return {
            "ok": self.ok,
            "passed": sum(c.status == PASS for c in self.checks),
            "failed": sum(c.status == FAIL for c in self.checks),
            "not_run": sum(c.status == NOT_RUN for c in self.checks),
            "checks": [c.to_dict() for c in self.checks],
        }

    def render(self) -> str:
        lines = [f"  [{c.status}] {c.name}: {c.detail}" for c in self.checks]
        passed = sum(c.status == PASS for c in self.checks)
        failed = sum(c.status == FAIL for c in self.checks)
        skipped = [c.name for c in self.checks if c.status == NOT_RUN]
        lines.append(f"verification {'PASSED' if self.ok else 'FAILED'} "
                     f"({passed} passed, {failed} failed, "
                     f"{len(skipped)} not run)")
        if skipped:
            lines.append("  NOT RUN (no independent reference available "
                         "for these; they are NOT counted as passes): "
                         + ", ".join(skipped))
        return "\n".join(lines)


# -- independent geometry ------------------------------------------------

def axes_from_quat(q: Sequence[float]):
    """(forward, right, up) unit vectors in (north, east, up) from a
    (w, x, y, z) NED quaternion. Straight rotation-matrix expansion --
    no shared code with the pose solver."""
    w, x, y, z = q
    fwd_n = 1.0 - 2.0 * (y * y + z * z)
    fwd_e = 2.0 * (x * y + w * z)
    fwd_d = 2.0 * (x * z - w * y)
    rgt_n = 2.0 * (x * y - w * z)
    rgt_e = 1.0 - 2.0 * (x * x + z * z)
    rgt_d = 2.0 * (y * z + w * x)
    dwn_n = 2.0 * (x * z + w * y)
    dwn_e = 2.0 * (y * z - w * x)
    dwn_d = 1.0 - 2.0 * (x * x + y * y)
    forward = (fwd_n, fwd_e, -fwd_d)
    right = (rgt_n, rgt_e, -rgt_d)
    up = (-dwn_n, -dwn_e, dwn_d)
    return forward, right, up


def axes_from_euler(roll_deg: float, pitch_deg: float, yaw_deg: float):
    """The same axes from the recorded Euler angles, independently.

    This pair tests the two ROTATION ENCODINGS against each other, and
    nothing more: the producer writes the quaternion by converting
    these very angles, so agreement proves the conventions match, not
    that the pose is right. :func:`verify_pose_matches_spec` is what
    grades the pose.
    """
    r, p, y = (math.radians(roll_deg), math.radians(pitch_deg),
               math.radians(yaw_deg))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    forward = (cp * cy, cp * sy, sp)
    right = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    up = (-(cr * sp * cy + sr * sy), -(cr * sp * sy - sr * cy), cr * cp)
    return forward, right, up


def scene_to_enu(manifest: Dict):
    """``f(north_m, east_m, alt_m) -> (north, east, up)`` metres in the
    frame the RENDER HOST actually places things in, or ``None``.

    A manifest's positions are offsets in the scene's projected CRS
    about a recorded origin (``manifest["frame"]``: ``crs``,
    ``origin_x_m``, ``origin_y_m``, ``origin_lat_deg``,
    ``origin_lon_deg``) -- grid metres, not local Cartesian ones. The
    render host reads them as exactly that and walks
    projected -> geographic -> ECEF -> a round-planet ENU tangent frame
    (``AGeoReferencingSystem``, ``PlanetShape=RoundPlanet``). Every
    check here that compares a projection against the engine's own has
    to stand in the same frame or it is grading two different scenes.

    It matters more than "projections are approximate" suggests, and
    the size is measured, not assumed. The example run's origin sits
    334 km off the UTM 31N central meridian, where the point scale
    factor is 1.00097: grid metres are 0.097% longer than ground
    metres, HORIZONTALLY ONLY -- altitude passes through untouched --
    so the mismatch is an anisotropic squeeze that no common scaling
    cancels, and earth curvature drops a further 0.8 m over the tower
    camera's 3.2 km sightline. Reading the frame flat put this
    module's landmark projections 0.60 px from the engine's (mean 0.23
    px on the chase camera, 0.36 px on the tower camera, systematic in
    sign, growing with range). Walking the same chain the host walks
    takes that to 0.0013 px worst of 916 projections -- float noise.
    That 0.60 px is what made two-view triangulation miss by up to
    1.17 m: at 3.2 km, one pixel is 2.6 m.

    Returns ``None`` when the manifest declares no usable frame -- a
    synthetic manifest built for a unit test has none, and for a scene
    with no projection the flat reading IS the right one.
    """
    frame = manifest.get("frame")
    if not isinstance(frame, dict):
        return None
    try:
        crs = str(frame["crs"])
        origin_x = float(frame["origin_x_m"])
        origin_y = float(frame["origin_y_m"])
        lat0 = float(frame["origin_lat_deg"])
        lon0 = float(frame["origin_lon_deg"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        from pyproj import Transformer
    except ImportError:                     # pragma: no cover
        return None
    try:
        to_geographic = Transformer.from_crs(crs, "EPSG:4979", always_xy=True)
        to_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
        x0, y0, z0 = to_ecef.transform(lon0, lat0, 0.0)
    except Exception:                       # pragma: no cover
        return None
    sin_lat, cos_lat = math.sin(math.radians(lat0)), math.cos(math.radians(lat0))
    sin_lon, cos_lon = math.sin(math.radians(lon0)), math.cos(math.radians(lon0))

    def convert(north_m, east_m, alt_m):
        lon, lat, height = to_geographic.transform(
            origin_x + float(east_m), origin_y + float(north_m), float(alt_m))
        x, y, z = to_ecef.transform(lon, lat, height)
        dx, dy, dz = x - x0, y - y0, z - z0
        # The origin's own altitude never enters: every consumer takes
        # a DIFFERENCE of two converted points, and a common
        # translation cancels out of it.
        east = -sin_lon * dx + cos_lon * dy
        north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
        return north, east, up

    return convert


def _record_in_enu(record: Dict, to_enu) -> Dict:
    """``record`` with its camera position moved into the host's frame.

    The recorded ROTATION is left exactly as it is: the host applies
    the card's yaw/pitch/roll directly in its ENU frame, so the
    verifier must read them there too. (Grid convergence would separate
    grid north from true north elsewhere; at this scene's equatorial
    origin it is identically zero, and the 0.0013 px residual says the
    host is doing no other rotation either.)
    """
    if to_enu is None:
        return record
    north, east, up = to_enu(record["position_north_m"],
                             record["position_east_m"],
                             record["position_alt_m"])
    moved = dict(record)
    moved["position_north_m"] = north
    moved["position_east_m"] = east
    moved["position_alt_m"] = up
    return moved


def project_point(record: Dict, point, axes=None) -> Tuple[float, float, float]:
    """(u_px, v_px, depth_m) of a world point through one frame record,
    the manifest's documented model, implemented here from scratch."""
    if axes is None:
        axes = axes_from_quat(record["quaternion_wxyz"])
    forward, right, up = axes
    d = (point[0] - record["position_north_m"],
         point[1] - record["position_east_m"],
         point[2] - record["position_alt_m"])
    x_cam = sum(a * b for a, b in zip(right, d))
    y_cam = -sum(a * b for a, b in zip(up, d))
    z_cam = sum(a * b for a, b in zip(forward, d))
    cx, cy = record["principal_point_px"]
    if z_cam <= 0:
        return math.inf, math.inf, z_cam
    u = cx + record["fx_px"] * x_cam / z_cam
    v = cy + record["fy_px"] * y_cam / z_cam
    return u, v, z_cam


def _ray_through_pixel(record: Dict, u: float, v: float):
    """World-space ray from the camera centre through a pixel, again
    from scratch off the recorded pose + intrinsics."""
    forward, right, up = axes_from_quat(record["quaternion_wxyz"])
    cx, cy = record["principal_point_px"]
    x_cam = (u - cx) / record["fx_px"]
    y_cam = (v - cy) / record["fy_px"]
    direction = tuple(
        f + x_cam * r - y_cam * uv
        for f, r, uv in zip(forward, right, up))
    origin = (record["position_north_m"], record["position_east_m"],
              record["position_alt_m"])
    return origin, direction


def _closest_point_between_rays(o1, d1, o2, d2):
    """Midpoint of the shortest segment between two rays; None for
    near-parallel rays."""
    d1d1 = sum(a * a for a in d1)
    d2d2 = sum(a * a for a in d2)
    d1d2 = sum(a * b for a, b in zip(d1, d2))
    denom = d1d1 * d2d2 - d1d2 * d1d2
    if abs(denom) < 1e-12:
        return None
    w0 = tuple(a - b for a, b in zip(o1, o2))
    a1 = sum(a * b for a, b in zip(w0, d1))
    a2 = sum(a * b for a, b in zip(w0, d2))
    t1 = (d1d2 * a2 - d2d2 * a1) / denom
    t2 = (d1d1 * a2 - d1d2 * a1) / denom
    p1 = tuple(o + t1 * d for o, d in zip(o1, d1))
    p2 = tuple(o + t2 * d for o, d in zip(o2, d2))
    return tuple((a + b) / 2.0 for a, b in zip(p1, p2))


# -- reading the spec back off the manifest ------------------------------

def _spec_value(spec: Optional[Dict], name: str, default=None):
    """One camera-spec field's value out of the manifest's own copy of
    the CameraSpec. The spec is an INPUT to the solver, so reading it
    back is an independent reference for what the track should be."""
    if not spec:
        return default
    field = spec.get(name)
    if not isinstance(field, dict):
        return default
    value = field.get("value", default)
    return default if value is None else value


def _camera_specs(manifest: Dict) -> Dict[str, Dict]:
    return {str(block["camera_id"]): (block.get("spec") or {})
            for block in manifest.get("cameras", [])}


def _presets(manifest: Dict) -> Dict[str, str]:
    return {str(block["camera_id"]): str(block.get("preset", "chase"))
            for block in manifest.get("cameras", [])}


def _aircraft_point(record: Dict):
    a = record["aircraft"]
    return (a["north_m"], a["east_m"], a["alt_m"])


def _heading_only_components(d, heading_deg: float):
    """(forward, right, up) of a world delta in the aircraft's
    heading-only frame -- the frame the chase/wingman offsets are
    stated in."""
    y = math.radians(heading_deg)
    cy, sy = math.cos(y), math.sin(y)
    north, east, up = d
    return (north * cy + east * sy, -north * sy + east * cy, up)


# -- check: intrinsics against the stated lens ---------------------------

def verify_intrinsics(manifest: Dict) -> Check:
    """The recorded intrinsics must be the lens the spec asked for.

    Independent reference: the CameraSpec. Every frame's sensor size,
    resolution, near/far and principal point must equal the stated
    values exactly, the focal length must be one the spec or its
    keyframes actually name, and the pixel focal lengths must be the
    documented arithmetic on those numbers -- so a manifest whose
    ``fx_px`` was scaled cannot pass by scaling ``focal_length_mm`` to
    match.
    """
    specs = _camera_specs(manifest)
    frames = manifest.get("frames", [])
    if not frames:
        return Check("intrinsics_match_spec", FAIL,
                     "the manifest records no frames")
    unspecified = sorted({r["camera_id"] for r in frames
                          if not specs.get(r["camera_id"])})
    problems: List[str] = []
    worst_fx = 0.0
    for record in frames:
        spec = specs.get(record["camera_id"])
        if not spec:
            continue
        for name in ("sensor_width_mm", "sensor_height_mm", "width_px",
                     "height_px", "near_m", "far_m"):
            stated = _spec_value(spec, name)
            if stated is None:
                continue
            if abs(float(record[name]) - float(stated)) > 1e-9:
                problems.append(
                    f"{record['camera_id']} #{record['index']}: {name} is "
                    f"{record[name]!r} where the spec states {stated!r}")
        # The focal length may vary only through the camera's own
        # keyframed moves, so the admissible set is the stated value
        # plus every keyed value.
        stated_focal = _spec_value(spec, "focal_length_mm")
        keyed = [float(m["focal_length_mm"])
                 for m in (spec.get("moves") or [])
                 if "focal_length_mm" in m]
        if stated_focal is not None:
            lo = min([float(stated_focal)] + keyed)
            hi = max([float(stated_focal)] + keyed)
            focal = float(record["focal_length_mm"])
            if not (lo - 1e-9 <= focal <= hi + 1e-9):
                problems.append(
                    f"{record['camera_id']} #{record['index']}: focal "
                    f"length {focal:g} mm is outside the stated "
                    f"[{lo:g}, {hi:g}] mm the spec and its moves name")
        # The documented arithmetic, recomputed here.
        expect_fx = (float(record["focal_length_mm"])
                     / float(record["sensor_width_mm"])
                     * float(record["width_px"]))
        expect_fy = (float(record["focal_length_mm"])
                     / float(record["sensor_height_mm"])
                     * float(record["height_px"]))
        worst_fx = max(worst_fx, abs(record["fx_px"] - expect_fx),
                       abs(record["fy_px"] - expect_fy))
        centre = [float(record["width_px"]) / 2.0,
                  float(record["height_px"]) / 2.0]
        if [float(v) for v in record["principal_point_px"]] != centre:
            problems.append(
                f"{record['camera_id']} #{record['index']}: principal "
                f"point {record['principal_point_px']} is not the image "
                f"centre {centre}")
    if worst_fx > 1e-6:
        problems.append(
            f"pixel focal length disagrees with focal/sensor*pixels by "
            f"up to {worst_fx:.6f} px")
    if unspecified:
        problems.append(
            f"no camera spec recorded for {', '.join(unspecified)}; the "
            f"lens cannot be graded against what was asked for")
    if problems:
        return Check("intrinsics_match_spec", FAIL,
                     "; ".join(problems[:6])
                     + (f" (+{len(problems) - 6} more)"
                        if len(problems) > 6 else ""))
    return Check("intrinsics_match_spec", PASS,
                 f"{len(frames)} frames carry the lens their spec states, "
                 f"and fx/fy match focal/sensor*pixels to "
                 f"{worst_fx:.2e} px")


# -- check: the solved pose against the stated camera --------------------

def _keyframed_scalar(moves: Sequence[Dict], key: str, t: float,
                      default: float) -> float:
    """The value one keyframed camera field states at time ``t``:
    piecewise-linear between the keyframes that carry ``key``, held at
    the boundary values outside them, ``default`` when no keyframe
    carries it. Written here in plain arithmetic on purpose: the
    verifier grades the solver's track and may not borrow the solver's
    interpolation to do it."""
    keyed = sorted((float(m["t_s"]), float(m[key])) for m in (moves or [])
                   if key in m)
    if not keyed:
        return default
    if t <= keyed[0][0]:
        return keyed[0][1]
    if t >= keyed[-1][0]:
        return keyed[-1][1]
    for (t0, v0), (t1, v1) in zip(keyed, keyed[1:]):
        if t0 <= t <= t1:
            return v1 if t1 == t0 else v0 + (t - t0) / (t1 - t0) * (v1 - v0)
    return keyed[-1][1]


def verify_pose_matches_spec(manifest: Dict) -> Check:
    """The solved track must be the camera the spec asked for.

    Independent reference: the CameraSpec. This is the check that can
    catch a wrong pose with no engine present -- a world-anchored
    camera must sit exactly where it was placed, a cockpit camera must
    ride at its stated body offset, a chase or wingman camera must hold
    its stated station in the heading-only frame within its documented
    smoothing lag, and any aircraft-aimed camera must actually be
    looking at the aircraft.
    """
    specs = _camera_specs(manifest)
    presets = _presets(manifest)
    frames = manifest.get("frames", [])
    if not frames:
        return Check("pose_matches_spec", FAIL,
                     "the manifest records no frames")
    graded = 0
    ungraded: List[str] = []
    problems: List[str] = []
    worst_placement = 0.0
    worst_aim_deg = 0.0

    transformer = None
    frame_meta = manifest.get("frame") or {}

    def to_local(lat_deg, lon_deg):
        """Local north/east of a geographic placement, through the
        manifest's own recorded CRS and origin."""
        nonlocal transformer
        if transformer is None:
            from pyproj import Transformer

            transformer = Transformer.from_crs(
                "EPSG:4326", frame_meta["crs"], always_xy=True)
        x, y = transformer.transform(float(lon_deg), float(lat_deg))
        return (y - float(frame_meta["origin_y_m"]),
                x - float(frame_meta["origin_x_m"]))

    for record in frames:
        camera_id = record["camera_id"]
        spec = specs.get(camera_id)
        if not spec:
            if camera_id not in ungraded:
                ungraded.append(camera_id)
            continue
        preset = presets.get(camera_id, "chase")
        camera = (record["position_north_m"], record["position_east_m"],
                  record["position_alt_m"])
        aircraft = _aircraft_point(record)
        moves = spec.get("moves") or []
        label = f"{camera_id} #{record['index']}"

        # -- placement ---------------------------------------------------
        mode = str(_spec_value(spec, "position_mode", "offset"))
        keyed_position = any(
            key in m for m in moves
            for key in ("position_north_m", "position_east_m",
                        "position_alt_m", "position_lat_deg",
                        "position_lon_deg"))
        if preset in ("ground", "tower", "explicit") and not keyed_position:
            expected = None
            tol = STATED_POSITION_TOL_M
            if mode == "scene":
                expected = (float(_spec_value(spec, "position_north_m", 0.0)),
                            float(_spec_value(spec, "position_east_m", 0.0)),
                            float(_spec_value(spec, "position_alt_m", 0.0)))
            elif mode == "geographic" and frame_meta.get("crs"):
                try:
                    north, east = to_local(
                        _spec_value(spec, "position_lat_deg", 0.0),
                        _spec_value(spec, "position_lon_deg", 0.0))
                except Exception:          # pyproj absent or CRS unusable
                    expected = None
                else:
                    expected = (north, east,
                                float(_spec_value(spec, "position_alt_m",
                                                  0.0)))
                    tol = GEOGRAPHIC_POSITION_TOL_M
            if expected is not None:
                gap = math.dist(camera, expected)
                worst_placement = max(worst_placement, gap)
                graded += 1
                if gap > tol:
                    problems.append(
                        f"{label}: placed {gap:.3f} m from the position "
                        f"the spec states (tol {tol:g} m) -- a stated "
                        f"camera position is never silently moved")
        elif preset == "cockpit":
            offset = (float(_spec_value(spec, "offset_forward_m", 0.0)),
                      float(_spec_value(spec, "offset_right_m", 0.0)),
                      float(_spec_value(spec, "offset_up_m", 0.0)))
            expected_range = math.sqrt(sum(v * v for v in offset))
            gap = abs(math.dist(camera, aircraft) - expected_range)
            worst_placement = max(worst_placement, gap)
            graded += 1
            if gap > 1e-3:
                problems.append(
                    f"{label}: rides {math.dist(camera, aircraft):.3f} m "
                    f"from the aircraft where its body offset is "
                    f"{expected_range:.3f} m -- a body-fixed camera is "
                    f"rigid")
        elif preset in ("chase", "wingman"):
            # The station the spec states AT THIS FRAME'S TIME: a move
            # word ("pull back", "push in", "orbit") keyframes the
            # offset over the flight, and the keyframes are the
            # contract. Graded against the static offset, a documented
            # "pull back" failed this check at 172.1 m against a 166.0 m
            # bound (Phase 1 initial run report) -- the solver had done
            # exactly what the word asked. Interpolated here with the
            # verifier's own arithmetic, never the solver's.
            t_frame = float(record.get("t_s", 0.0))
            offset = tuple(
                _keyframed_scalar(moves, key, t_frame,
                                  float(_spec_value(spec, key, 0.0)))
                for key in ("offset_forward_m", "offset_right_m",
                            "offset_up_m"))
            magnitude = math.sqrt(sum(v * v for v in offset))
            # The station is smoothed onto with a time constant, so the
            # camera trails it; the bound is generous enough that lag at
            # airliner speed never trips it and tight enough that a
            # camera in the wrong place does.
            tol = max(50.0, 1.5 * magnitude)
            delta = tuple(c - a for c, a in zip(camera, aircraft))
            station = _heading_only_components(
                delta, float(record["aircraft"]["heading_deg"]))
            gap = math.dist(station, offset)
            worst_placement = max(worst_placement, gap)
            graded += 1
            if gap > tol:
                problems.append(
                    f"{label}: sits {gap:.1f} m from its stated station "
                    f"in the heading-only frame (tol {tol:.1f} m); "
                    f"measured offset "
                    f"({station[0]:.1f}, {station[1]:.1f}, "
                    f"{station[2]:.1f}) against a stated "
                    f"({offset[0]:g}, {offset[1]:g}, {offset[2]:g})")

        # -- aim ----------------------------------------------------------
        if str(_spec_value(spec, "aim_mode", "aircraft")) == "aircraft":
            to_aircraft = tuple(a - c for a, c in zip(aircraft, camera))
            span = math.sqrt(sum(v * v for v in to_aircraft))
            if span >= AIM_DEGENERATE_M:
                forward, _, _ = axes_from_quat(record["quaternion_wxyz"])
                cosine = sum(f * d for f, d in zip(forward, to_aircraft)) / span
                angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
                worst_aim_deg = max(worst_aim_deg, angle)
                graded += 1
                if angle > AIM_TOL_DEG:
                    problems.append(
                        f"{label}: aims {angle:.1f} deg off the aircraft "
                        f"(tol {AIM_TOL_DEG:g} deg) though its spec says "
                        f"aim_mode 'aircraft'")

    if not graded:
        return Check("pose_matches_spec", NOT_RUN,
                     "no frame carried a camera spec to grade the solved "
                     "track against"
                     + (f" ({', '.join(ungraded)})" if ungraded else ""))
    if problems:
        return Check("pose_matches_spec", FAIL,
                     "; ".join(problems[:6])
                     + (f" (+{len(problems) - 6} more)"
                        if len(problems) > 6 else ""))
    return Check("pose_matches_spec", PASS,
                 f"{graded} placement/aim clauses graded against the "
                 f"stated cameras; worst placement gap "
                 f"{worst_placement:.3f} m, worst aim error "
                 f"{worst_aim_deg:.2f} deg")


# -- check: geometry recovery -------------------------------------------

def verify_geometry(manifest: Dict,
                    tol_px: float = REPROJECTION_TOL_PX) -> Check:
    """The aircraft must be in front of, and for an aimed camera inside,
    every frame that claims to see it; and the two recorded encodings of
    one orientation must agree.

    This is a consistency check, not a proof of correct geometry: both
    encodings come from the producer's single conversion.
    :func:`verify_pose_matches_spec` and
    :func:`verify_landmark_reprojection` are the checks with an
    independent reference.
    """
    specs = _camera_specs(manifest)
    presets = _presets(manifest)
    worst_gap = 0.0
    behind = 0
    out_of_frame = 0
    frames = manifest.get("frames", [])
    if not frames:
        return Check("geometry_recovery", FAIL,
                     "the manifest records no frames")
    for record in frames:
        point = _aircraft_point(record)
        u_q, v_q, z_q = project_point(
            record, point, axes_from_quat(record["quaternion_wxyz"]))
        u_e, v_e, _ = project_point(
            record, point, axes_from_euler(record["roll_deg"],
                                           record["pitch_deg"],
                                           record["yaw_deg"]))
        if presets.get(record["camera_id"]) == "cockpit":
            # A body-fixed camera is AT the aircraft: its own origin is
            # neither in front of nor inside its frame.
            continue
        if z_q <= 0:
            behind += 1
            continue
        if math.isfinite(u_q) and math.isfinite(u_e):
            worst_gap = max(worst_gap, math.hypot(u_q - u_e, v_q - v_e))
        aim = str(_spec_value(specs.get(record["camera_id"]), "aim_mode",
                              "aircraft"))
        if aim == "aircraft":
            if not (0.0 <= u_q <= record["width_px"]
                    and 0.0 <= v_q <= record["height_px"]):
                out_of_frame += 1
    ok = behind == 0 and out_of_frame == 0 and worst_gap <= tol_px
    return Check(
        "geometry_recovery", PASS if ok else FAIL,
        f"{len(frames)} frames; quaternion-vs-euler reprojection gap "
        f"{worst_gap:.4f} px (tol {tol_px}); {behind} aircraft behind "
        f"camera; {out_of_frame} aimed frames without the aircraft in "
        f"frame")


# -- checks needing the engine ------------------------------------------

def _render_frame_records(payload: Dict) -> List[Dict]:
    """The per-frame records out of a host's ``render.json``.

    The commandlet writes TWO differently-shaped things whose names
    read alike: ``frames`` is the integer COUNT of images written, and
    ``frame_records`` is the array of per-frame records. Both readers
    below asked for ``frames`` and got the count, so the landmark and
    capture-time checks could never see a record: before a render
    existed they reported NOT RUN, and the first real render turned
    the count into ``TypeError: 'int' object is not iterable``. Read
    the array by its name, and accept ``frames`` only when a producer
    genuinely made it a list.
    """
    records = payload.get("frame_records")
    if isinstance(records, list):
        return [r for r in records if isinstance(r, dict)]
    legacy = payload.get("frames")
    if isinstance(legacy, list):
        return [r for r in legacy if isinstance(r, dict)]
    return []


def _engine_landmark_pixels(run_dir) -> Dict:
    """``{frame_file: {landmark: (px, py, visible)}}`` from the render
    host's own ``render.json``, where one exists.

    These pixels were produced by the commandlet's ``ProjectToPixel``
    from the pose it ACTUALLY applied -- a different implementation, in
    a different language, of the same projection. They are the only
    reference in this system that is not the manifest talking to
    itself.
    """
    if run_dir is None:
        return {}
    run_dir = Path(run_dir)
    out: Dict[str, Dict] = {}
    for path in sorted(run_dir.rglob("render.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # The engine names a frame by its BASENAME ("frame_0005.png"),
        # because it only knows the directory it was told to write into.
        # The manifest names it by the path relative to the run
        # ("frames/chase0/frame_0005.png"). Keying on the engine's name
        # alone never matched the manifest -- so both engine-dependent
        # checks reported NOT RUN even with a render present, which is
        # the quietest possible way for them to not exist. It also
        # collides across cameras, which all number from frame_0000.
        # render.json sits in the camera's own directory, so that
        # directory IS the missing prefix.
        try:
            prefix = path.parent.relative_to(run_dir).as_posix()
        except ValueError:
            prefix = ""
        for record in _render_frame_records(payload):
            landmarks = record.get("landmarks") or {}
            name = record.get("frame") or record.get("file")
            if not name or not landmarks:
                continue
            # Basename first: the engine records "frame_0005.png", but a
            # producer that recorded a path must not be prefixed twice.
            leaf = str(name).replace("\\", "/").rsplit("/", 1)[-1]
            name = f"{prefix}/{leaf}" if prefix else leaf
            out[str(name)] = {
                str(key): (float(entry.get("px", math.nan)),
                           float(entry.get("py", math.nan)),
                           bool(entry.get("visible", False)))
                for key, entry in landmarks.items()
            }
    return out


def _engine_frame_times(run_dir) -> Dict[str, float]:
    """``{frame_file: sim time the engine actually rendered it at}``.

    The commandlet records its own clock per frame. The manifest states
    the SCHEDULED instant. They are not automatically the same: capture
    times come off the telemetry clock while the renderer advances on
    its own frame grid, so the frame delivered for a scheduled instant
    is the first one at or after it.
    """
    if run_dir is None:
        return {}
    run_dir = Path(run_dir)
    out: Dict[str, float] = {}
    for path in sorted(run_dir.rglob("render.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            prefix = path.parent.relative_to(run_dir).as_posix()
        except ValueError:
            prefix = ""
        for record in _render_frame_records(payload):
            name = record.get("frame") or record.get("file")
            if not name or "t" not in record:
                continue
            leaf = str(name).replace("\\", "/").rsplit("/", 1)[-1]
            out[f"{prefix}/{leaf}" if prefix else leaf] = float(record["t"])
    return out


def verify_capture_times(manifest: Dict, run_dir=None,
                         tol_s: float = 0.05) -> Check:
    """The frame delivered for a scheduled instant must be FROM that
    instant.

    Every label in a frame record -- the camera pose, the aircraft
    state -- is stated for ``t_s``. If the pixels come from a different
    moment, the labels describe a world the picture does not show, and
    nothing inside the manifest can reveal it. The engine's own
    per-frame clock is the reference.
    """
    engine = _engine_frame_times(run_dir)
    if not engine:
        return Check("capture_time_agreement", NOT_RUN,
                     "no render.json with per-frame times: nothing was "
                     "rendered here, so the scheduled instant is the only "
                     "instant")
    worst = 0.0
    worst_frame = ""
    compared = 0
    for record in manifest.get("frames", []):
        actual = engine.get(str(record.get("file")))
        if actual is None:
            continue
        gap = abs(actual - float(record["t_s"]))
        compared += 1
        if gap > worst:
            worst, worst_frame = gap, str(record.get("file"))
    if compared == 0:
        return Check("capture_time_agreement", NOT_RUN,
                     "no rendered frame matched a manifest frame record")
    if worst > tol_s:
        return Check(
            "capture_time_agreement", FAIL,
            f"a frame was rendered {worst:.4f} s from the instant its "
            f"record states ({worst_frame}, tol {tol_s:g} s) over "
            f"{compared} frames: the labels describe a moment the "
            f"pixels do not show")
    return Check("capture_time_agreement", PASS,
                 f"{compared} frames rendered within {worst:.4f} s of the "
                 f"instant each record states (tol {tol_s:g} s)")


def _landmark_coverage(manifest: Dict) -> Tuple[int, float]:
    """(landmark projections that land in frame, worst radial offset
    from the principal point as a fraction of the half-diagonal).

    Coverage is reported because a projection check exercised only near
    the optical centre proves very little: an intrinsic or distortion
    error grows with radius.
    """
    from .landmarks import landmark_point

    landmarks = manifest.get("landmarks") or []
    in_frame = 0
    worst_radius = 0.0
    for record in manifest.get("frames", []):
        cx, cy = record["principal_point_px"]
        half_diagonal = math.hypot(cx, cy) or 1.0
        for landmark in landmarks:
            u, v, z = project_point(record, landmark_point(landmark))
            if z <= 0 or not math.isfinite(u):
                continue
            if 0.0 <= u <= record["width_px"] and 0.0 <= v <= record["height_px"]:
                in_frame += 1
                worst_radius = max(worst_radius,
                                   math.hypot(u - cx, v - cy) / half_diagonal)
    return in_frame, worst_radius


def verify_landmark_reprojection(manifest: Dict, run_dir=None,
                                 tol_px: float = ENGINE_TOL_PX) -> Check:
    """This module's projection of each known landmark against the
    ENGINE's projection of the same landmark in the same frame."""
    from .landmarks import by_name, landmark_point

    in_frame, worst_radius = _landmark_coverage(manifest)
    coverage = (f"{len(manifest.get('landmarks') or [])} landmarks, "
                f"{in_frame} in-frame projections, worst off-axis radius "
                f"{worst_radius:.2f} of the half-diagonal")
    engine = _engine_landmark_pixels(run_dir)
    if not engine:
        return Check(
            "landmark_reprojection", NOT_RUN,
            f"no render.json with landmark pixels under the run "
            f"directory, so there is no independent projection to "
            f"compare against -- reprojecting the manifest through its "
            f"own model would agree by construction. Render on Windows "
            f"to exercise this. ({coverage})")
    if not manifest.get("landmarks"):
        return Check("landmark_reprojection", NOT_RUN,
                     "the manifest records no landmarks to reproject")
    known = by_name(manifest["landmarks"])
    to_enu = scene_to_enu(manifest)
    compared = 0
    worst = 0.0
    disagreements: List[str] = []
    for record in manifest.get("frames", []):
        pixels = engine.get(str(record.get("file")))
        if not pixels:
            continue
        placed = _record_in_enu(record, to_enu)
        for name, (px, py, visible) in pixels.items():
            landmark = known.get(name)
            if landmark is None or not visible:
                continue
            point = landmark_point(landmark)
            if to_enu is not None:
                point = to_enu(*point)
            u, v, z = project_point(placed, point)
            if z <= 0 or not math.isfinite(u):
                disagreements.append(
                    f"{record['camera_id']} #{record['index']}: the "
                    f"engine sees {name} but this projection puts it "
                    f"behind the camera")
                continue
            gap = math.hypot(u - px, v - py)
            worst = max(worst, gap)
            compared += 1
            if gap > tol_px:
                disagreements.append(
                    f"{record['camera_id']} #{record['index']} {name}: "
                    f"{gap:.2f} px between this projection "
                    f"({u:.1f}, {v:.1f}) and the engine's "
                    f"({px:.1f}, {py:.1f})")
    if compared == 0:
        # A render.json with landmark pixels, none of which this manifest
        # names, is not a missing reference -- it is a broken contract.
        # The engine rendered these frames FROM this manifest's card and
        # projected a different scene's landmarks into them, so nothing
        # here can be graded and something upstream is wrong. Reporting
        # it as NOT RUN is how it stayed invisible: turning on the visual
        # scene made the commandlet overwrite the card's 36 landmarks
        # with Gate 6's 4, both engine-referenced checks stopped running,
        # and the summary still said PASSED.
        seen = sorted({name for pixels in engine.values() for name in pixels})
        return Check(
            "landmark_reprojection", FAIL,
            f"the engine projected {len(seen)} landmark(s) into these "
            f"frames and this manifest names none of them "
            f"({', '.join(seen[:6])}{'...' if len(seen) > 6 else ''} "
            f"against {', '.join(sorted(known)[:6])}...): the frames were "
            f"rendered from a different landmark set than the labels "
            f"describe. ({coverage})")
    if disagreements:
        return Check("landmark_reprojection", FAIL,
                     "; ".join(disagreements[:5])
                     + (f" (+{len(disagreements) - 5} more)"
                        if len(disagreements) > 5 else ""))
    return Check("landmark_reprojection", PASS,
                 f"{compared} landmark projections agree with the "
                 f"engine's own to within {worst:.2f} px (tol {tol_px}). "
                 f"({coverage})")


def verify_triangulation(manifest: Dict, run_dir=None,
                         tol_m: float = TRIANGULATION_TOL_M) -> Check:
    """A static landmark seen from two cameras at one instant must
    triangulate back to where the scene says it is.

    Needs the ENGINE's measured pixels. Casting both rays through this
    module's own projection would return the input point by
    construction, whatever the poses are -- that is the Phase 1 defect,
    and reporting NOT RUN is the honest alternative to repeating it.
    """
    from .landmarks import by_name, landmark_point

    measured = _engine_landmark_pixels(run_dir)
    if not measured:
        return Check(
            "cross_view_consistency", NOT_RUN,
            "two-view triangulation needs pixels measured independently "
            "of this manifest (the engine's render.json landmarks); "
            "back-projecting rays this module itself projected returns "
            "the input point whatever the pose is, so it is not run "
            "rather than passed. Render on Windows to exercise this.")
    known = by_name(manifest.get("landmarks"))
    if not known:
        return Check("cross_view_consistency", NOT_RUN,
                     "the manifest records no landmarks to triangulate")

    # Both rays and the truth they are graded against stand in the
    # host's frame -- see scene_to_enu. Triangulating grid-metre rays
    # against a grid-metre truth would miss by up to 1.17 m here for
    # no reason but the frame.
    to_enu = scene_to_enu(manifest)

    # (sample_index, landmark) -> [(record, u, v)]
    sightings: Dict[Tuple[int, str], List] = {}
    for record in manifest.get("frames", []):
        pixels = measured.get(str(record.get("file")))
        if not pixels:
            continue
        placed = _record_in_enu(record, to_enu)
        for name, (px, py, visible) in pixels.items():
            if not visible or name not in known:
                continue
            sightings.setdefault((int(record["sample_index"]), name),
                                 []).append((placed, px, py))

    pairs = 0
    worst = 0.0
    problems: List[str] = []
    for (sample_index, name), seen in sorted(sightings.items()):
        if len(seen) < 2:
            continue
        (record_a, ua, va), (record_b, ub, vb) = seen[0], seen[1]
        if record_a["camera_id"] == record_b["camera_id"]:
            continue
        recovered = _closest_point_between_rays(
            *_ray_through_pixel(record_a, ua, va),
            *_ray_through_pixel(record_b, ub, vb))
        if recovered is None:
            continue                    # parallel rays carry no depth
        truth = landmark_point(known[name])
        if to_enu is not None:
            truth = to_enu(*truth)
        error = math.dist(recovered, truth)
        worst = max(worst, error)
        pairs += 1
        if error > tol_m:
            problems.append(
                f"t={record_a['t_s']:.2f}s {name} seen by "
                f"{record_a['camera_id']} and {record_b['camera_id']} "
                f"triangulates {error:.3f} m from where the scene puts it")
    if pairs == 0:
        return Check("cross_view_consistency", NOT_RUN,
                     "no landmark was seen by two cameras at the same "
                     "instant; capture two cameras on a shared schedule "
                     "with a landmark in both frames to exercise this")
    if problems:
        return Check("cross_view_consistency", FAIL,
                     "; ".join(problems[:5])
                     + (f" (+{len(problems) - 5} more)"
                        if len(problems) > 5 else ""))
    return Check("cross_view_consistency", PASS,
                 f"{pairs} two-view landmark sightings triangulate to "
                 f"within {worst:.3f} m of their known positions "
                 f"(tol {tol_m} m)")


# -- check: count exactness ---------------------------------------------

def verify_counts(manifest: Dict) -> Check:
    """Every camera emitted exactly the number of images its SPEC asked
    for, densely indexed.

    The number to grade against is the one the user stated, read out of
    the manifest's copy of the CameraSpec -- not the schedule length the
    producer derived, which is the frame count restated and can only
    agree with itself.
    """
    problems: List[str] = []
    ungraded: List[str] = []
    graded = 0
    for block in manifest.get("cameras", []):
        camera_id = str(block["camera_id"])
        indices = sorted(r["index"] for r in manifest.get("frames", [])
                         if r["camera_id"] == camera_id)
        emitted = len(indices)
        if indices != list(range(emitted)):
            problems.append(f"{camera_id}: frame indices are not a dense "
                            f"0..{emitted - 1} sequence")
        spec = block.get("spec") or {}
        requested = _spec_value(spec, "capture_count")
        if requested is None:
            ungraded.append(camera_id)
        elif int(requested) > 0:
            graded += 1
            if emitted != int(requested):
                problems.append(
                    f"{camera_id}: {emitted} frames against the "
                    f"{int(requested)} its spec requests")
        else:
            # capture_count 0 means "every period_s", which states no
            # count contract; the schedule's own length is all there is.
            declared = int(block.get("capture_count", emitted))
            if emitted != declared:
                problems.append(
                    f"{camera_id}: {emitted} frames against a schedule of "
                    f"{declared}")
    if problems:
        return Check("count_exactness", FAIL, "; ".join(problems))
    detail = (f"{graded} camera(s) requested an exact image count and got "
              f"exactly it; every camera's frames are densely indexed")
    if ungraded:
        detail += (f"; no spec recorded for {', '.join(ungraded)}, so the "
                   f"requested count could not be read back")
    return Check("count_exactness", PASS, detail)


# -- check: the manifest agreeing with itself ----------------------------

def verify_aircraft_consistency(manifest: Dict) -> Check:
    """Every camera that captured a given telemetry sample must record
    the SAME aircraft state for it.

    A self-consistency check, and stated as one: its reference is the
    manifest itself, so it cannot tell a right aircraft state from a
    wrong one -- only a manifest that contradicts itself about where
    the aircraft was at one instant. That is worth catching (it is
    exactly what a misattributed frame record looks like) and it is all
    this check claims.
    """
    by_sample: Dict[int, List[Dict]] = {}
    for record in manifest.get("frames", []):
        by_sample.setdefault(int(record["sample_index"]), []).append(record)
    shared = [records for records in by_sample.values() if len(records) > 1]
    if not shared:
        return Check("aircraft_state_consistency", NOT_RUN,
                     "no telemetry sample was captured by more than one "
                     "camera, so there is nothing to cross-check")
    problems: List[str] = []
    worst = 0.0
    for records in shared:
        first = records[0]
        for other in records[1:]:
            gap = math.dist(_aircraft_point(first), _aircraft_point(other))
            worst = max(worst, gap)
            if gap > 1e-6:
                problems.append(
                    f"t={first['t_s']:.2f}s: {first['camera_id']} and "
                    f"{other['camera_id']} disagree about the aircraft "
                    f"position by {gap:.3f} m")
    if problems:
        return Check("aircraft_state_consistency", FAIL,
                     "; ".join(problems[:5])
                     + (f" (+{len(problems) - 5} more)"
                        if len(problems) > 5 else ""))
    return Check("aircraft_state_consistency", PASS,
                 f"{len(shared)} shared instants; every camera records "
                 f"the same aircraft state for each (worst disagreement "
                 f"{worst:.2e} m)")


# -- check: the manifest's flight against the flight that rendered -------

def _host_telemetry_paths(run_dir) -> List[Path]:
    """Every flight the RENDER HOST recorded, one per camera pass.

    The single place that decides which file is the host's. It is
    emphatically not ``<run>/telemetry.json``: that is the headless
    pre-run, the telemetry the manifest's aircraft track was solved
    from, and reading it made flight_agreement compare the pre-run with
    itself and report 0.00 m forever. Both files carry the same four
    column names, so nothing downstream can tell them apart -- which is
    why the choice lives here, once, behind a name that says which one
    it is.
    """
    return sorted(Path(run_dir).rglob("host_telemetry.json"))


#: Tolerance for a manifest solved over the HEADLESS PRE-RUN. Two JSBSim
#: builds stepping one scenario diverge; measured at 1.38 m on the demo,
#: and this bounds it rather than pretending it is zero.
PRE_RUN_AGREEMENT_TOL_M = 25.0

#: Tolerance for a manifest solved over THE HOST'S OWN FLIGHT. There is
#: no divergence left to allow for: the labels and the pixels come from
#: one flight, and the host is bit-deterministic, so all that separates
#: them is this check interpolating the host's 0.1 s samples to the
#: frame's own instant. That error is the curvature of the track over
#: half a sample -- sub-decimetre even in a hard manoeuvre. 0.5 m is
#: loose enough never to fire on interpolation and tight enough that
#: solving over the pre-run again (1.38 m) FAILS here, which is exactly
#: the regression this bound exists to catch.
HOST_FLIGHT_AGREEMENT_TOL_M = 0.5


def verify_flight_agreement(manifest: Dict, run_dir=None,
                            tol_m: Optional[float] = None) -> Check:
    """The aircraft this manifest labels must be the aircraft the frames
    show.

    Two ways a run can get here, and the manifest says which in
    ``solve_source``:

    * **"headless pre-run"** -- poses solved over the Python-side
      flight, the host then re-flies the scenario itself. Camera poses
      are consumed verbatim so those are exact, but the AIRCRAFT states
      come from a DIFFERENT flight than the pixels show. Bounded at
      ``PRE_RUN_AGREEMENT_TOL_M``, measured at 1.38 m on the demo.
    * **"host flight"** -- the host flew the card first and everything
      was solved over its telemetry (``core.capture.hostflight``). The
      labels and the pixels are one flight, so the bound drops to
      ``HOST_FLIGHT_AGREEMENT_TOL_M`` and this check becomes the guard
      that the pipeline did not quietly fall back to the pre-run.

    Either way it MEASURES the divergence instead of assuming it away:
    the manifest's aircraft track against the host's own recorded
    telemetry, matched on simulation time. NOT RUN where no host
    telemetry exists (an unrendered capture has only the one flight).
    """
    from .manifest import SOLVE_HOST_FLIGHT

    solved_over = str(manifest.get("solve_source") or "")
    if tol_m is None:
        tol_m = (HOST_FLIGHT_AGREEMENT_TOL_M
                 if solved_over == SOLVE_HOST_FLIGHT
                 else PRE_RUN_AGREEMENT_TOL_M)
    if run_dir is None:
        return Check("flight_agreement", NOT_RUN,
                     "no run directory given, so the host's telemetry "
                     "cannot be compared against the manifest's")
    # The HOST's own recording, written by the render pass into the
    # camera's directory -- never <run>/telemetry.json, which is the
    # headless pre-run the manifest's aircraft track was SOLVED FROM.
    # Reading that one made this check compare the pre-run against
    # itself: structurally 0.00 m, on every run, whatever the host
    # actually flew. It is the P10 guard, and it had the P1 defect.
    # The two files carry the same four column names, which is exactly
    # why pointing at the wrong one looked like it worked.
    hosts = _host_telemetry_paths(run_dir)
    if not hosts:
        return Check(
            "flight_agreement", NOT_RUN,
            "no host_telemetry.json under the run directory: the render "
            "host recorded no flight of its own, so there is nothing to "
            "compare the manifest's aircraft track against. Render on "
            "Windows to exercise this")
    columns_by_camera: Dict[str, Dict] = {}
    needed = ("t", "lat_deg", "lon_deg", "altitude_m")
    for path in hosts:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Check("flight_agreement", NOT_RUN,
                         f"host telemetry could not be read ({exc})")
        columns = payload.get("columns", payload)
        if not all(key in columns for key in needed):
            return Check("flight_agreement", NOT_RUN,
                         f"host telemetry carries no {needed} columns")
        columns_by_camera[path.parent.name] = columns

    frame_meta = manifest.get("frame") or {}
    try:
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", frame_meta["crs"],
                                           always_xy=True)
    except Exception as exc:
        return Check("flight_agreement", NOT_RUN,
                     f"the manifest's CRS could not be opened ({exc})")

    times_by_camera = {camera: [float(v) for v in cols["t"]]
                       for camera, cols in columns_by_camera.items()}
    if not any(len(t) >= 2 for t in times_by_camera.values()):
        return Check("flight_agreement", NOT_RUN,
                     "host telemetry has fewer than two samples")

    worst = 0.0
    worst_t = 0.0
    worst_camera = ""
    compared = 0
    unmatched = 0
    edge = 0
    outside: List[str] = []
    for record in manifest.get("frames", []):
        # Each camera pass is its own flight of the host, so a frame is
        # graded against the flight that produced IT -- not against
        # whichever host recording happened to be found first.
        camera = str(record.get("camera_id"))
        columns = columns_by_camera.get(camera)
        if columns is None:
            unmatched += 1
            continue
        times = times_by_camera[camera]
        t = float(record["t_s"])
        # INTERPOLATE to the frame's own instant; do not snap to the
        # nearest host sample. The host records every 0.1 s and a
        # 280 kt aircraft covers 8.3 m in half of that, so snapping
        # reported up to ~8 m of pure time quantisation as though it
        # were flight divergence -- which both inflates the number
        # (12.46 m measured, against a true divergence nearer 2.8 m)
        # and eats most of the tolerance, leaving the check able to
        # catch only what is bigger than its own noise.
        upper = None
        for i in range(1, len(times)):
            if times[i - 1] <= t <= times[i]:
                upper = i
                break
        if upper is None:
            # Outside the host's own track, and never extrapolated. A
            # frame just past either end is the recorder's granularity
            # -- it samples every SampleIntervalSeconds and the last
            # capture instant can fall inside that final interval, so
            # the last frame of every run lands here. A frame outside
            # by MORE than one interval means the host stopped flying
            # before the run ended, which is not granularity and is not
            # allowed to pass quietly.
            interval = ((times[-1] - times[0]) / (len(times) - 1)
                        if len(times) > 1 else 0.0)
            if t < times[0] - interval or t > times[-1] + interval:
                outside.append(f"{camera} t={t:.3f}s")
            else:
                edge += 1
            continue
        lower = upper - 1
        span = times[upper] - times[lower]
        fraction = (t - times[lower]) / span if span > 0 else 0.0

        def at(key, i):
            return float(columns[key][i])

        def lerp(key):
            return at(key, lower) + fraction * (at(key, upper) - at(key, lower))

        x, y = transformer.transform(lerp("lon_deg"), lerp("lat_deg"))
        host = (y - float(frame_meta["origin_y_m"]),
                x - float(frame_meta["origin_x_m"]),
                lerp("altitude_m"))
        gap = math.dist(_aircraft_point(record), host)
        if gap > worst:
            worst, worst_t, worst_camera = gap, t, camera
        compared += 1
    if compared == 0:
        return Check("flight_agreement", NOT_RUN,
                     "no frame time matched a host telemetry sample")
    if unmatched:
        return Check(
            "flight_agreement", FAIL,
            f"{unmatched} frames name a camera that recorded no host "
            f"flight, so nothing grades them; host flights present for "
            f"{sorted(columns_by_camera)}")
    if outside:
        return Check(
            "flight_agreement", FAIL,
            f"{len(outside)} frames fall outside the host's recorded "
            f"flight by more than one sample interval, so the host was "
            f"not flying when they were taken and nothing grades them: "
            + ", ".join(outside[:5])
            + (f" (+{len(outside) - 5} more)" if len(outside) > 5 else ""))
    if worst > tol_m:
        return Check(
            "flight_agreement", FAIL,
            f"the manifest's aircraft track and the host's recorded "
            f"flight differ by up to {worst:.1f} m (at t={worst_t:.2f}s "
            f"on {worst_camera}, tol {tol_m:g} m) over {compared} "
            f"frames: the labels describe a different flight than the "
            f"frames show. Solved over {solved_over!r}"
            + ("; a gap this size is what solving over the headless "
               "pre-run produces, so check the host flight actually ran"
               if solved_over == SOLVE_HOST_FLIGHT else ""))
    return Check("flight_agreement", PASS,
                 f"{compared} frames against {len(columns_by_camera)} "
                 f"host flight(s); the manifest's aircraft track matches "
                 f"the host's recorded flight to within {worst:.2f} m "
                 f"(solved over {solved_over!r}, tol {tol_m:g} m)"
                 + (f"; {edge} frame(s) sat inside the recorder's final "
                    f"sample interval and were not graded" if edge else ""))


def verify_host_determinism(run_dir=None) -> Check:
    """Every render pass over one card must fly the same flight.

    This is the property that licenses the pipeline's shape. The plan
    left the choice open -- re-fly the scenario in the host, or replay
    the recorded telemetry into it -- and made it conditional on a
    measurement nobody had taken: render the same card twice and see
    whether the host is bit-deterministic. It is. Two commandlet passes
    over examples/cameras_multi.yaml produced byte-identical telemetry
    across all 30 recorded columns and 120 samples, digest
    4e5a7334... both times, worst per-sample difference exactly 0. So
    re-flying is reproducible and the replay path is not needed.

    A conditional decision has to keep checking its condition, or it
    quietly becomes an assumption again -- which is how this phase got
    every other defect it had. A run renders one pass per camera, so
    every multi-camera run measures the property for free: same card,
    separate host flights, digests compared. If they ever diverge, the
    "re-fly" decision is invalid and the aircraft labels drift between
    cameras with nothing else to notice.

    Since the solve pass landed (core.capture.hostflight), a rendered
    run records the host's SOLVE flight as well as one flight per camera
    pass, so this compares the flight the labels were solved over
    against the flights the pixels were taken on -- which is the exact
    premise of solving over the host at all, and it now has something to
    compare even on a single-camera render.

    NOT RUN with fewer than two host flights -- one pass measures
    nothing about repeatability.
    """
    if run_dir is None:
        return Check("host_determinism", NOT_RUN,
                     "no run directory given")
    hosts = _host_telemetry_paths(run_dir)
    if len(hosts) < 2:
        return Check(
            "host_determinism", NOT_RUN,
            f"{len(hosts)} host flight(s) recorded; repeatability needs "
            f"two flights over the same card to compare. Render on "
            f"Windows to exercise this -- a run that flies the host to "
            f"solve, then renders, records two")
    digests: Dict[str, str] = {}
    for path in hosts:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return Check("host_determinism", NOT_RUN,
                         f"a host telemetry could not be read ({exc})")
        columns = payload.get("columns", payload)
        if not isinstance(columns, dict) or not columns:
            return Check("host_determinism", NOT_RUN,
                         f"{path.parent.name} recorded no columns")
        # Exact, over every column the host records -- repr, not a
        # rounded format, so two flights differing in the last bit
        # produce different digests. A tolerance here would defeat the
        # point: the claim being checked is bit-determinism.
        digest = hashlib.sha256()
        for key in sorted(columns):
            digest.update(key.encode("utf-8"))
            for value in columns[key]:
                digest.update(repr(float(value)).encode("utf-8"))
        digests[path.parent.name] = digest.hexdigest()
    unique = sorted(set(digests.values()))
    if len(unique) > 1:
        listed = ", ".join(f"{camera}={value[:12]}"
                           for camera, value in sorted(digests.items()))
        return Check(
            "host_determinism", FAIL,
            f"{len(unique)} different flights across {len(digests)} "
            f"host flights of one card ({listed}): the host is not "
            f"reproducible, so the aircraft labels differ between "
            f"passes and re-flying the scenario per pass is not sound "
            f"-- the poses would have to be replayed instead. If the "
            f"odd one out is 'host_flight', the solve pass and the "
            f"render passes are not being given the same "
            f"scenario-affecting flags")
    sample_count = len(next(iter(
        json.loads(hosts[0].read_text(encoding="utf-8"))
        .get("columns", {}).values()), []))
    return Check(
        "host_determinism", PASS,
        f"{len(digests)} host flights of one card were byte-identical "
        f"({unique[0][:12]}, {sample_count} samples): the host is "
        f"reproducible, which is what makes solving over one of its "
        f"flights and re-flying for the pixels sound rather than an "
        f"assumption")


# -- check: temporal alignment ------------------------------------------

def verify_alignment(manifest_a: Dict, manifest_b: Dict,
                     tol_s: float = TIME_TOL_S) -> Check:
    """Two runs of the same simulation align frame-for-frame."""
    problems = []
    if manifest_a.get("simulation_digest") != \
            manifest_b.get("simulation_digest"):
        problems.append("simulation digests differ: these are not the "
                        "same simulation")
    if manifest_a.get("output_digest") != manifest_b.get("output_digest"):
        problems.append("telemetry digests differ: the flights were not "
                        "identical")
    times_a = sorted({round(r["t_s"], 9)
                      for r in manifest_a.get("frames", [])})
    times_b = sorted({round(r["t_s"], 9)
                      for r in manifest_b.get("frames", [])})
    if len(times_a) != len(times_b):
        problems.append(f"{len(times_a)} capture instants against "
                        f"{len(times_b)}")
    else:
        worst = max((abs(x - y) for x, y in zip(times_a, times_b)),
                    default=0.0)
        if worst > tol_s:
            problems.append(f"capture times diverge by {worst:g} s")
    if problems:
        return Check("temporal_alignment", FAIL, "; ".join(problems))
    return Check("temporal_alignment", PASS,
                 f"{len(times_a)} capture instants align exactly across "
                 f"the two camera sets")


# -- the run summary -----------------------------------------------------

# -- version 5: the labels ------------------------------------------------
#
# Four checks, each with a stated independent reference:
#
# * label_geometry -- the labels against THIS verifier's own projection
#   of the airframe block through the aircraft state (the producer's
#   labels.py never runs here);
# * keypoints_in_box -- an internal consistency the producer could get
#   wrong: every in-frame keypoint inside the unclipped box;
# * drawn_airframe -- the engine's render.json says WHAT it drew (a real
#   mesh or placeholder boxes) and WHERE within the actor it attached it;
#   a mesh attached at the structural datum is offset from every label
#   by the FDM's VRP, FAIL by name. NOT RUN without a render.
# * label_files -- every per-frame label file the engine DECLARED in
#   render.json exists on disk (the frame-count contract, extended);
# * mask_containment / depth_range -- the engine's instance mask and
#   depth image against the labels, NOT RUN without them (version 5;
#   superseded on manifest 6 by the package-D block further down:
#   mask_integers_only, mask_vs_geometry, box_vs_mask, depth_vs_geometry,
#   visibility_vs_scene, identity_stable, applied_intrinsics).

#: A reprojected label may differ from the producer's by float rounding
#: and nothing else.
LABEL_REPROJECTION_TOL_PX = 0.05
#: A keypoint lies inside the box it belongs to, to half a pixel.
KEYPOINT_BOX_TOL_PX = 0.5
#: Of the engine's aircraft-mask pixels, the fraction that must fall
#: inside the label's 2-D box. The box is the airframe's overall extents,
#: so the mask should sit INSIDE it; mask pixels outside it are pixels
#: the labels say are not aircraft.
MASK_CONTAINMENT_MIN = 0.95
#: Depth at an aircraft-mask pixel must lie within the 3-D box's depth
#: span, widened by this much each way (the box is extents, not hull).
DEPTH_RANGE_SLACK_M = 2.0
#: The fraction of aircraft-mask pixels that must be within that span.
DEPTH_IN_RANGE_MIN = 0.99
#: The instance id the engine writes for the airframe in the mask.
AIRCRAFT_INSTANCE_ID = 1


def _aircraft_axes_enu(state: Dict):
    """The AIRCRAFT's body axes in (north, east, up) from its recorded
    Euler angles -- the same rotation as axes_from_euler, which is the
    verifier's own."""
    return axes_from_euler(float(state["roll_deg"]),
                           float(state["pitch_deg"]),
                           float(state["heading_deg"]))


def _body_point_enu(body, state: Dict):
    """Body (forward, right, down) about the CG -> scene (n, e, up)."""
    forward, right, up = _aircraft_axes_enu(state)
    bx, by, bz = body
    return (float(state["north_m"]) + bx * forward[0] + by * right[0] - bz * up[0],
            float(state["east_m"]) + bx * forward[1] + by * right[1] - bz * up[1],
            float(state["alt_m"]) + bx * forward[2] + by * right[2] - bz * up[2])


def _labelled_frames(manifest: Dict):
    return [f for f in manifest.get("frames", [])
            if isinstance(f.get("labels"), dict)]


def verify_labels(manifest: Dict) -> Check:
    """The labels, re-derived here from the airframe block and the
    aircraft state through the verifier's own projection."""
    frames = _labelled_frames(manifest)
    airframe = manifest.get("airframe")
    if not frames or not airframe:
        return Check("label_geometry", NOT_RUN,
                     "no per-frame labels in this manifest (version < 5)")
    box = airframe["box_body_m"]
    corners = [(x, y, z) for x in box["forward"] for y in box["right"]
               for z in box["down"]]
    keypoints = {k["name"]: tuple(k["body_m"]) for k in airframe["keypoints"]}
    worst = 0.0
    worst_where = ""
    checked = 0
    for record in frames:
        labels = record["labels"]
        state = record["aircraft"]
        axes = axes_from_quat(record["quaternion_wxyz"])
        pixels = [project_point(record, _body_point_enu(c, state), axes)
                  for c in corners]
        if all(math.isfinite(u) for u, v, z in pixels):
            us = [u for u, v, z in pixels]
            vs = [v for u, v, z in pixels]
            mine = (min(us), min(vs), max(us), max(vs))
            theirs = labels.get("bbox_2d_unclipped")
            if theirs is None:
                return Check("label_geometry", FAIL,
                             f"frame {record['camera_id']}/{record['index']}: "
                             f"every corner projects but the label says the "
                             f"box is unbounded")
            for a, b, name in zip(mine, theirs, ("u0", "v0", "u1", "v1")):
                if abs(a - b) > worst:
                    worst, worst_where = abs(a - b), (
                        f"{record['camera_id']}/{record['index']} bbox {name}")
        elif labels.get("bbox_2d_unclipped") is not None:
            return Check("label_geometry", FAIL,
                         f"frame {record['camera_id']}/{record['index']}: a "
                         f"corner is behind the camera but the label states "
                         f"a box")
        for name, body in keypoints.items():
            theirs = labels.get("keypoints", {}).get(name)
            if theirs is None:
                return Check("label_geometry", FAIL,
                             f"frame {record['camera_id']}/{record['index']}: "
                             f"keypoint {name!r} is in the airframe block but "
                             f"not in the labels")
            u, v, depth = project_point(record, _body_point_enu(body, state),
                                        axes)
            if math.isfinite(u):
                if theirs.get("u") is None:
                    return Check("label_geometry", FAIL,
                                 f"{record['camera_id']}/{record['index']} "
                                 f"keypoint {name!r}: projects, but labelled "
                                 f"as behind the camera")
                for a, b, what in ((u, theirs["u"], "u"), (v, theirs["v"], "v"),
                                   (depth, theirs["depth_m"], "depth")):
                    if abs(a - b) > worst:
                        worst, worst_where = abs(a - b), (
                            f"{record['camera_id']}/{record['index']} "
                            f"keypoint {name} {what}")
            elif theirs.get("u") is not None:
                return Check("label_geometry", FAIL,
                             f"{record['camera_id']}/{record['index']} "
                             f"keypoint {name!r}: behind the camera, but "
                             f"labelled with a pixel")
        checked += 1
    ok = worst <= LABEL_REPROJECTION_TOL_PX
    return Check("label_geometry", PASS if ok else FAIL,
                 f"{checked} labelled frames re-projected independently; "
                 f"worst disagreement {worst:.4f} (px or m) at "
                 f"{worst_where or 'none'}; tolerance "
                 f"{LABEL_REPROJECTION_TOL_PX}")


def verify_keypoints_in_box(manifest: Dict) -> Check:
    frames = _labelled_frames(manifest)
    if not frames:
        return Check("keypoints_in_box", NOT_RUN,
                     "no per-frame labels in this manifest (version < 5)")
    outside = []
    counted = 0
    for record in frames:
        labels = record["labels"]
        box = labels.get("bbox_2d_unclipped")
        for name, kp in labels.get("keypoints", {}).items():
            if kp.get("u") is None:
                continue
            counted += 1
            if box is None:
                continue
            u0, v0, u1, v1 = box
            t = KEYPOINT_BOX_TOL_PX
            if not (u0 - t <= kp["u"] <= u1 + t and v0 - t <= kp["v"] <= v1 + t):
                outside.append(f"{record['camera_id']}/{record['index']} "
                               f"{name} at ({kp['u']:.1f}, {kp['v']:.1f}) "
                               f"outside [{u0:.1f}, {v0:.1f}, {u1:.1f}, "
                               f"{v1:.1f}]")
    if outside:
        return Check("keypoints_in_box", FAIL,
                     f"{len(outside)} keypoint(s) outside their own box: "
                     + "; ".join(outside[:3]))
    return Check("keypoints_in_box", PASS,
                 f"{counted} projected keypoints, every one inside its "
                 f"frame's box (tolerance {KEYPOINT_BOX_TOL_PX} px)")


def _engine_label_records(run_dir) -> Dict[str, Dict]:
    """{camera_id: {frame name: the render.json record}} for every
    per-camera render.json that declares label outputs."""
    out: Dict[str, Dict] = {}
    if run_dir is None:
        return out
    frames_dir = Path(run_dir) / "frames"
    if not frames_dir.is_dir():
        return out
    for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        path = camera_dir / "render.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records = {r.get("frame"): r for r in _render_frame_records(payload)
                   if isinstance(r.get("labels"), dict)}
        if records:
            out[camera_dir.name] = records
    return out


def verify_label_files(manifest: Dict, run_dir=None) -> Check:
    """Every label file the engine declared exists -- the frame-count
    contract extended to the label outputs."""
    declared = _engine_label_records(run_dir)
    if not declared:
        return Check("label_files", NOT_RUN,
                     "no render.json declares per-frame label outputs "
                     "(no engine pass, or one that wrote none)")
    # Per CAMERA: a pass that declared label outputs owes every frame
    # all three files (the frame-count contract, extended); a pass that
    # declared none wrote none, and is named rather than failed.
    missing = []
    counted = 0
    undeclared = set()
    for record in manifest.get("frames", []):
        camera = str(record["camera_id"])
        if camera not in declared:
            undeclared.add(camera)
            continue
        name = Path(str(record["file"])).name
        engine = declared[camera].get(name)
        if engine is None:
            missing.append(f"{camera}/{name}: no engine label record")
            continue
        for kind in ("mask", "class_mask", "depth"):
            file = engine["labels"].get(kind)
            if not file:
                missing.append(f"{camera}/{name}: {kind} not declared")
                continue
            counted += 1
            if not (Path(run_dir) / "frames" / camera / file).is_file():
                missing.append(f"{camera}/{name}: {kind} {file} missing")
        # Contracts §1 (manifest 6): the raw float depth and each aircraft
        # object's alone pass are declared by the record when the engine
        # wrote them; a declared file that is absent is the same finding.
        # Absent keys are an older bundle, not a missing file.
        extra = []
        if engine["labels"].get("depth_f32"):
            extra.append(("depth_f32", str(engine["labels"]["depth_f32"])))
        for declared_object in engine["labels"].get("objects") or []:
            if isinstance(declared_object, dict) and declared_object.get("alone_png"):
                extra.append((f"alone_{declared_object.get('int_id')}",
                              str(declared_object["alone_png"])))
        for kind, file in extra:
            counted += 1
            if not (Path(run_dir) / "frames" / camera / file).is_file():
                missing.append(f"{camera}/{name}: {kind} {file} missing")
    if missing:
        return Check("label_files", FAIL,
                     f"{len(missing)} declared label file(s) absent: "
                     + "; ".join(missing[:4]),
                     failure="annotation.files")
    note = (f"; {sorted(undeclared)} declared no label outputs"
            if undeclared else "")
    return Check("label_files", PASS,
                 f"{counted} declared label files present across "
                 f"{sorted(declared)}{note}")


#: The mesh manifest version from which the render commandlet attaches
#: the mesh at the recorded model origin (the FDM's VRP) instead of the
#: actor root. Named here, not imported from the producer.
DRAWN_MESH_MIN_MANIFEST_VERSION = 2


def _engine_drawn(run_dir) -> Dict[str, Optional[Dict]]:
    """{camera_id: render.json['drawn'] or None} for every camera that
    has a render.json; None where the record predates the key."""
    out: Dict[str, Optional[Dict]] = {}
    if run_dir is None:
        return out
    frames_dir = Path(run_dir) / "frames"
    if not frames_dir.is_dir():
        return out
    for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        path = camera_dir / "render.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        drawn = payload.get("drawn") if isinstance(payload, dict) else None
        out[camera_dir.name] = drawn if isinstance(drawn, dict) else None
    return out


def verify_drawn_airframe(manifest: Dict, run_dir=None) -> Check:
    """The frames show the airframe the manifest describes, where it
    describes it.

    Measured (Camera Phase 1 initial run report): the rendered B747 sat
    25-30 m AHEAD of the position the manifest recorded for it, along
    its own axis, and every mask with it -- the converter maps the
    FlightGear model about the model's own origin (the FDM's visual
    reference point, 33.7 m aft of the datum on the 747) while the
    commandlet attached the mesh at the actor root, which is the JSBSim
    structural datum. The label, built from the telemetry's CG, was
    right; the pixels were not. Nothing in the manifest could show it,
    so the commandlet now records under ``drawn`` what it drew and
    where it attached it, and this check reads that record:

    * FAIL, by name, when placeholder boxes were drawn while the
      manifest's ``assets.mesh_manifest`` names a real mesh (its sha256
      is non-null);
    * FAIL when a mesh was drawn from a manifest older than version
      ``DRAWN_MESH_MIN_MANIFEST_VERSION``: it carried no origin, so the
      mesh was attached at the datum and every mask is offset from its
      label by the VRP;
    * PASS when the mesh was drawn at a version-2 origin;
    * NOT RUN with no render.json, or one that predates ``drawn``.
    """
    drawn_by_camera = _engine_drawn(run_dir)
    if not drawn_by_camera:
        return Check("drawn_airframe", NOT_RUN,
                     "no render.json (no engine pass); what was drawn is "
                     "unknown here")
    recorded = {c: d for c, d in drawn_by_camera.items() if d is not None}
    if not recorded:
        return Check("drawn_airframe", NOT_RUN,
                     "render.json predates the 'drawn' record (older engine "
                     "build): it does not say where the mesh was attached, "
                     "so the 25-30 m datum offset cannot be ruled out")
    mesh_asset = (manifest.get("assets") or {}).get("mesh_manifest") or {}
    expected_sha = mesh_asset.get("sha256")
    expected_path = mesh_asset.get("path") or "assets/generated/<aircraft>/mesh_manifest.json"
    problems = []
    notes = []
    for camera, drawn in sorted(recorded.items()):
        kind = drawn.get("kind")
        version = drawn.get("manifest_version")
        if kind == "placeholder":
            if expected_sha is not None:
                problems.append(
                    f"{camera}: placeholder boxes were drawn while the "
                    f"manifest expected the mesh {expected_path} "
                    f"(sha256 {str(expected_sha)[:12]}); the render was "
                    f"launched without -mesh=")
            else:
                notes.append(f"{camera}: placeholder boxes; the manifest "
                             f"expected no mesh (none on the producing "
                             f"machine)")
            continue
        if kind != "mesh":
            problems.append(f"{camera}: drawn.kind {kind!r} is neither "
                            f"'mesh' nor 'placeholder'")
            continue
        if (not isinstance(version, (int, float))
                or version < DRAWN_MESH_MIN_MANIFEST_VERSION):
            problems.append(
                f"{camera}: the mesh was drawn from manifest version "
                f"{version!r} (< {DRAWN_MESH_MIN_MANIFEST_VERSION}), which "
                f"records no mesh origin, so it was attached at the actor "
                f"origin -- the JSBSim structural datum -- and every mask "
                f"is offset from its label by the FDM's VRP (33.7 m on "
                f"the B747); re-run assets_pipeline/convert.py and render "
                f"again")
            continue
        origin = drawn.get("mesh_origin_actor_cm")
        origin_text = (", ".join(f"{float(v):.1f}" for v in origin)
                       if isinstance(origin, list) and len(origin) == 3
                       else "?")
        notes.append(f"{camera}: mesh at ({origin_text}) cm in the actor "
                     f"frame, manifest version {int(version)}")
    if problems:
        return Check("drawn_airframe", FAIL,
                     f"{len(problems)} camera(s) drew something other than "
                     f"the airframe the labels describe, where they describe "
                     f"it: " + "; ".join(problems[:4]),
                     failure="aircraft.placeholder_drawn")
    return Check("drawn_airframe", PASS,
                 f"{len(recorded)} camera(s): " + "; ".join(notes[:4]))


def _read_gray_png(path):
    """A mask or depth PNG as a 2-D integer array, via Pillow."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:            # pragma: no cover - Pillow is in the venv
        return None
    with Image.open(path) as image:
        return np.array(image)


def verify_mask_containment(manifest: Dict, run_dir=None) -> Check:
    """The engine's aircraft mask lies inside the label's 2-D box.

    The version-5 check: one instance id, one box. On a manifest that
    declares ``objects[]`` (version 6) the ID image carries every
    object's integer and box_vs_mask grades each against its projected
    hull, so this reports NOT RUN naming its successor rather than
    grading the primary twice."""
    if _declared_objects(manifest):
        return Check("mask_containment", NOT_RUN,
                     f"superseded for manifest {manifest.get('manifest_version')} "
                     f"by box_vs_mask (the ID image carries every object's int_id; "
                     f"the tight box of each is graded against its projected hull "
                     f"there); this single-id containment test is the version-5 check")
    declared = _engine_label_records(run_dir)
    if not declared:
        return Check("mask_containment", NOT_RUN,
                     "no engine instance masks to compare against")
    worst = 1.0
    worst_where = ""
    counted = 0
    for record in _labelled_frames(manifest):
        camera = str(record["camera_id"])
        name = Path(str(record["file"])).name
        engine = declared.get(camera, {}).get(name)
        if engine is None or not engine["labels"].get("mask"):
            continue
        mask = _read_gray_png(Path(run_dir) / "frames" / camera
                              / engine["labels"]["mask"])
        if mask is None:
            return Check("mask_containment", NOT_RUN, "Pillow unavailable")
        import numpy as np

        ys, xs = np.nonzero(mask == AIRCRAFT_INSTANCE_ID)
        box = record["labels"].get("bbox_2d")
        if xs.size == 0:
            if box is not None and record["labels"].get("in_frame"):
                return Check("mask_containment", FAIL,
                             f"{camera}/{name}: the label says the aircraft "
                             f"is in frame but the engine mask has no "
                             f"aircraft pixels")
            continue
        if box is None:
            return Check("mask_containment", FAIL,
                         f"{camera}/{name}: the engine mask shows "
                         f"{xs.size} aircraft pixels but the label says "
                         f"nothing of it is in frame")
        u0, v0, u1, v1 = box
        inside = ((xs + 0.5 >= u0) & (xs + 0.5 <= u1)
                  & (ys + 0.5 >= v0) & (ys + 0.5 <= v1)).mean()
        counted += 1
        if inside < worst:
            worst, worst_where = float(inside), f"{camera}/{name}"
    if counted == 0:
        return Check("mask_containment", NOT_RUN,
                     "engine masks declared but none matched a labelled frame")
    ok = worst >= MASK_CONTAINMENT_MIN
    return Check("mask_containment", PASS if ok else FAIL,
                 f"{counted} frames; lowest containment {worst:.3f} at "
                 f"{worst_where} (min {MASK_CONTAINMENT_MIN})")


def verify_depth_range(manifest: Dict, run_dir=None) -> Check:
    """Depth at the engine's aircraft-mask pixels lies within the 3-D
    box's depth span.

    The version-5 check. On a manifest that declares ``objects[]``
    (version 6) depth_vs_geometry grades every aircraft object's depth
    against its projected hull, keypoints and record, so this reports
    NOT RUN naming its successor."""
    if _declared_objects(manifest):
        return Check("depth_range", NOT_RUN,
                     f"superseded for manifest {manifest.get('manifest_version')} "
                     f"by depth_vs_geometry (per object: the depth under the mask "
                     f"against the projected hull band, the nearest keypoint and the "
                     f"record); this single-id span test is the version-5 check")
    declared = _engine_label_records(run_dir)
    if not declared:
        return Check("depth_range", NOT_RUN,
                     "no engine depth images to compare against")
    worst = 1.0
    worst_where = ""
    counted = 0
    for record in _labelled_frames(manifest):
        camera = str(record["camera_id"])
        name = Path(str(record["file"])).name
        engine = declared.get(camera, {}).get(name)
        if engine is None:
            continue
        labels = engine["labels"]
        if not labels.get("mask") or not labels.get("depth"):
            continue
        scale = float(labels.get("depth_scale_m") or 0.0)
        if scale <= 0.0:
            return Check("depth_range", FAIL,
                         f"{camera}/{name}: depth declared with no positive "
                         f"depth_scale_m")
        folder = Path(run_dir) / "frames" / camera
        mask = _read_gray_png(folder / labels["mask"])
        depth = _read_gray_png(folder / labels["depth"])
        if mask is None or depth is None:
            return Check("depth_range", NOT_RUN, "Pillow unavailable")
        import numpy as np

        aircraft = mask == AIRCRAFT_INSTANCE_ID
        if not aircraft.any():
            continue
        zs = [c[2] for c in record["labels"]["bbox_3d_camera"]["corners_m"]]
        lo, hi = min(zs) - DEPTH_RANGE_SLACK_M, max(zs) + DEPTH_RANGE_SLACK_M
        metres = depth[aircraft].astype(float) * scale
        fraction = float(((metres >= lo) & (metres <= hi)).mean())
        counted += 1
        if fraction < worst:
            worst, worst_where = fraction, (
                f"{camera}/{name} (span {lo:.1f}-{hi:.1f} m, engine "
                f"{metres.min():.1f}-{metres.max():.1f} m)")
    if counted == 0:
        return Check("depth_range", NOT_RUN,
                     "engine depth declared but none matched a labelled frame")
    ok = worst >= DEPTH_IN_RANGE_MIN
    return Check("depth_range", PASS if ok else FAIL,
                 f"{counted} frames; lowest in-range fraction {worst:.3f} "
                 f"at {worst_where} (min {DEPTH_IN_RANGE_MIN})")


# -- Phase 2, package D: the annotation gates (contracts §4) ----------------
#
# The per-frame ground-truth bundle (contracts §1) is graded here against
# the manifest's geometry through THIS module's projection: the ID image,
# the class image, the depth (.f32, else the 16-bit PNG at its scale), the
# alone passes and the render.json record. Nothing from the producer
# (core/capture/labels.py, core/capture/objects.py) runs here; every
# number the bundle carries is re-derived from the files with numpy and
# compared against the record and against the projected geometry. Each
# check names its FAIL from the catalogue (``Check.failure``), reports NOT
# RUN without its evidence (no bundle; a manifest below 6 declares no
# ids), and never turns NOT RUN into a pass.
#
# What is NOT claimed, stated once for the block:
#
# * The hull a mask is graded against is a BOX -- the converter's measured
#   mesh extent when the very mesh manifest the run cites is on this
#   machine, else the airframe block's extents box. A real airframe's
#   silhouette lies inside that box, so the box-vs-mask agreement on an
#   oblique view is bounded by the contract's tolerances, not measured
#   here: no engine ran in this environment, and the first rendered frame
#   measures the residual (see the report).
# * A traffic aircraft's per-frame state is not recorded in the manifest
#   (only the primary's ``aircraft`` block is); its placement is taken
#   from the record's own ``bbox_3d_camera`` and stated so in the detail.
#   The projection of that placement, the pixels and the depth are graded;
#   the placement itself is not independently re-derived.
# * A blended ID value that rounds to a DECLARED integer is invisible to
#   a histogram (the ids are 1..N, contiguous); the engine's own
#   ``non_integer_id_pixels`` count, the class image and the geometry
#   checks are what see such a blend. Stated in mask_integers_only.
# * Objects whose projected hull spans fewer than BOX_IOU_MIN_PX pixels
#   are counted and not graded (the contract's "not claimed under 16 px").

#: mask_vs_geometry: the centre of the silhouette's tight box may sit
#: this fraction of the projected hull span (the larger of its width and
#: height) from the centre of the projected hull box (contracts §3: 2 %
#: "centroid vs projected CG" -- see the check for why the two centres
#: and not the area centroid and the CG). A 3 m mesh-origin shift on a
#: 70 m airframe seen from abeam is 4 % of the span.
MASK_CENTROID_TOL_FRACTION = 0.02
#: mask_vs_geometry: the ID mask's tight-box width and height may differ
#: from the projected hull box's by this fraction of the hull's
#: (contracts §3: 5 %; the converter refuses a mesh whose span disagrees
#: with the cited length by more than the same 5 %).
MASK_EXTENT_TOL_FRACTION = 0.05
#: mask_vs_geometry: the pixel floor under both fractions. The ID pass
#: samples pixel centres, so each rasterised edge of a continuous extent
#: lands within half a pixel of it: a width is quantised to within one
#: pixel and a centroid to within half of one, whatever the size. Below
#: 20 px of span the floor, not the fraction, is the tolerance.
MASK_TOL_PX = 1.0
#: box_vs_mask: IoU between the tight box and the projected hull box for
#: an object whose hull spans at least BOX_IOU_LARGE_PX pixels ...
BOX_IOU_MIN_LARGE = 0.8
#: ... and for one spanning BOX_IOU_MIN_PX to BOX_IOU_LARGE_PX pixels.
BOX_IOU_MIN_SMALL = 0.5
BOX_IOU_LARGE_PX = 64.0
#: Below this projected span the box/mask agreement is NOT CLAIMED
#: (contracts §3); such objects are counted, not graded.
BOX_IOU_MIN_PX = 16.0
#: depth_vs_geometry: a measured depth may differ from the geometry's by
#: this fraction of itself plus DEPTH_TOL_M (contracts §3: 1 % + 2 m).
#: The band itself -- from the hull's nearest corner to its farthest --
#: is what grows with the airframe's length.
DEPTH_TOL_FRACTION = 0.01
DEPTH_TOL_M = 2.0
#: depth_vs_geometry: the record's depth_min_m / depth_median_m are the
#: same pixels this module reads, so they agree to float rounding.
DEPTH_RECORD_TOL_M = 0.05
#: visibility_vs_scene: the visible pixels outside an object's alone
#: footprint, the hidden footprint pixels nothing nearer explains, and
#: the overlap pixels drawn with the farther object, each as a fraction
#: of the footprint (or of the overlap) the check tolerates (contracts
#: §3: 3 % of the analytic overlap). Both passes are AA-free from the
#: same pose, so the residual on a correct render is edge pixels.
VISIBILITY_TOL_FRACTION = 0.03
#: visibility_vs_scene: the recorded visible_fraction is the same two
#: counts this module makes; agreement to float rounding.
VISIBILITY_RECORD_TOL = 1e-6
#: applied_intrinsics: the engine's applied horizontal field of view
#: against the record's 2 atan(width / 2 fx) (contracts §4: 0.1 deg).
APPLIED_FOV_TOL_DEG = 0.1
#: applied_intrinsics: the applied focal length and sensor width against
#: the record's, in mm (a representation tolerance, not a budget).
APPLIED_LENS_TOL_MM = 1e-3

#: Failure names (contracts §11), one per check.
FAIL_MASK_BLEND = "annotation.mask_blend"
FAIL_MASK_OFFSET = "annotation.mask_offset"
FAIL_BOX_MISMATCH = "annotation.box_mismatch"
FAIL_DEPTH_RANGE = "annotation.depth_range"
FAIL_VISIBILITY = "annotation.visibility"
FAIL_IDENTITY = "annotation.identity"
FAIL_INTRINSICS = "annotation.intrinsics"
FAIL_FILES = "annotation.files"

#: The manifest version from which ``objects[]`` declares the ids the ID
#: image may hold (contracts §2.4).
OBJECTS_MIN_MANIFEST_VERSION = 6

_REPO = Path(__file__).resolve().parents[2]


def _declared_objects(manifest: Dict) -> List[Dict]:
    """The manifest's ``objects[]`` (version 6), or [] for an older one."""
    objects = manifest.get("objects")
    return [o for o in objects if isinstance(o, dict)] if isinstance(objects, list) else []


def _no_objects_reason(manifest: Dict) -> str:
    return (f"manifest_version {manifest.get('manifest_version')!r} carries no "
            f"objects[] (version {OBJECTS_MIN_MANIFEST_VERSION} declares the ids "
            f"the ID image may hold), so there is nothing to grade the bundle against")


def _no_bundle_reason() -> str:
    return ("no render.json declares per-frame label outputs (no engine pass, "
            "or one without -labels): render on Windows to exercise this")


def _labelled_ids(objects: Sequence[Dict]) -> Dict[int, Dict]:
    """``{int_id: entry}`` for the objects the ID image may carry."""
    out: Dict[int, Dict] = {}
    for entry in objects:
        try:
            if entry.get("labelled", True) and entry.get("in_scene", True):
                out[int(entry["int_id"])] = entry
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _aircraft_entries(objects: Sequence[Dict]) -> List[Dict]:
    return [e for e in objects if e.get("class") == "aircraft"
            and e.get("labelled", True) and e.get("in_scene", True)]


def _record_object(record: Dict, int_id: int) -> Optional[Dict]:
    """The frame's ``labels.objects[]`` entry for an id, or None."""
    for entry in (record.get("labels") or {}).get("objects") or []:
        if isinstance(entry, dict) and entry.get("int_id") == int_id:
            return entry
    return None


def _engine_object(engine: Dict, int_id: int) -> Optional[Dict]:
    """The render.json record's ``labels.objects[]`` entry for an id."""
    for entry in (engine.get("labels") or {}).get("objects") or []:
        if isinstance(entry, dict) and entry.get("int_id") == int_id:
            return entry
    return None


def _read_depth_metres(folder: Path, labels: Dict, width: int, height: int):
    """The frame's depth as float metres (+inf for sky), from the raw
    float32 file when declared, else the 16-bit PNG at its stated scale
    (65535 saturates to +inf). Own numpy reader; refuses a float file of
    the wrong size (a truncated depth would label everything below the
    cut as sky) by returning the reason as a string."""
    import numpy as np

    if labels.get("depth_f32"):
        path = folder / str(labels["depth_f32"])
        raw = np.fromfile(path, dtype="<f4")
        if raw.size != width * height:
            return (f"{path.name}: {raw.size} float32 values for a "
                    f"{width}x{height} frame ({width * height} expected)")
        return raw.reshape(height, width).astype("float64")
    if labels.get("depth"):
        array = _read_gray_png(folder / str(labels["depth"]))
        if array is None:
            return "Pillow unavailable"
        scale = float(labels.get("depth_scale_m") or 0.0)
        if scale <= 0.0:
            return f"{labels['depth']}: declared with no positive depth_scale_m"
        metres = array.astype("float64") * scale
        metres[array >= 65535] = math.inf
        return metres
    return "no depth file declared"


# -- the geometry an object is graded against ------------------------------
#
# Every object is reduced to an oriented box in CAMERA coordinates (x
# right, y down, z forward): centre, the three body axes, the half
# extents, the CG, the keypoints. For the primary all of it comes from the
# frame's own ``aircraft`` state and the manifest's airframe block through
# this module's rotation and projection; for a traffic aircraft the
# placement comes from the record (stated).

def _camera_coords(record: Dict, point, axes) -> Tuple[float, float, float]:
    """A world (north, east, up) point in camera coordinates."""
    forward, right, up = axes
    d = (point[0] - record["position_north_m"],
         point[1] - record["position_east_m"],
         point[2] - record["position_alt_m"])
    return (sum(a * b for a, b in zip(right, d)),
            -sum(a * b for a, b in zip(up, d)),
            sum(a * b for a, b in zip(forward, d)))


def _pinhole(record: Dict, cam) -> Optional[Tuple[float, float]]:
    """Camera coordinates -> continuous pixel (u, v); None behind the
    camera. Pixel (x, y) covers [x, x+1) x [y, y+1)."""
    x, y, z = cam
    if z <= 0.0:
        return None
    cx, cy = record["principal_point_px"]
    return (cx + record["fx_px"] * x / z, cy + record["fy_px"] * y / z)


def _hull_box_body(manifest: Dict, airframe_block: Dict, primary: bool
                   ) -> Tuple[Dict[str, Tuple[float, float]], str]:
    """The box an object's pixels are graded against, in body metres
    about the CG ``{"forward": (aft, fwd), "right": (left, right),
    "down": (top, bottom)}``, with its basis.

    For the primary, when ``assets.mesh_manifest`` names a file that is
    on THIS machine with the cited sha256 and carries the converter's
    measured extent (version >= 3, contracts §0.1): that extent re-based
    on the CG -- the actor frame is +x forward, +y right, +z up with its
    origin at the structural datum, the CG sits at (-x, y, z) * 0.0254 of
    its structural inches, body z is DOWN. The arithmetic is written here
    (the producer's hull_box_body_m never runs in the verifier). Else the
    airframe block's extents box, which the labels' own bbox_2d is built
    from and which test_camera_labels pins against the FDM's XML.
    """
    if primary:
        asset = (manifest.get("assets") or {}).get("mesh_manifest") or {}
        path, sha = asset.get("path"), asset.get("sha256")
        if path and sha:
            candidate = _REPO / str(path)
            if candidate.is_file() and hashlib.sha256(
                    candidate.read_bytes()).hexdigest() == str(sha):
                try:
                    mesh = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    mesh = {}
                version = mesh.get("version")
                extent = mesh.get("mesh_extent_actor_m") or {}
                origin = mesh.get("mesh_origin_actor_cm")
                if (isinstance(version, (int, float)) and version >= 3
                        and origin and all(k in extent for k in "xyz")):
                    ox, oy, oz = (float(v) / 100.0 for v in origin)
                    cx, cy, cz = (float(v) for v in airframe_block["cg_structural_in"])
                    cg = (-cx * 0.0254, cy * 0.0254, cz * 0.0254)
                    ex, ey, ez = ([float(v) for v in extent[k]] for k in "xyz")
                    box = {"forward": (ox + ex[0] - cg[0], ox + ex[1] - cg[0]),
                           "right": (oy + ey[0] - cg[1], oy + ey[1] - cg[1]),
                           "down": (-(oz + ez[1] - cg[2]), -(oz + ez[0] - cg[2]))}
                    return box, (f"mesh manifest version {int(version)} "
                                 f"measured extent ({path}) re-based on the CG")
    box = airframe_block["box_body_m"]
    return ({k: (float(box[k][0]), float(box[k][1])) for k in ("forward", "right", "down")},
            "the airframe block's extents box (no mesh manifest with the cited "
            "digest on this machine)")


def _object_geometry(manifest: Dict, record: Dict, entry: Dict, axes):
    """The oriented box of one aircraft object in camera coordinates, or
    ``(None, why)``."""
    int_id = int(entry["int_id"])
    if entry.get("role") == "primary" or int_id == AIRCRAFT_INSTANCE_ID:
        airframe = manifest.get("airframe")
        state = record.get("aircraft")
        if not isinstance(airframe, dict) or not isinstance(state, dict):
            return None, "no airframe block or aircraft state in the manifest"
        cg = _camera_coords(record, (float(state["north_m"]), float(state["east_m"]),
                                     float(state["alt_m"])), axes)
        body_axes = []
        for unit in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            tip = _camera_coords(record, _body_point_enu(unit, state), axes)
            body_axes.append(tuple(t - c for t, c in zip(tip, cg)))
        placement = "the frame's aircraft state through the verifier's own rotation"
    else:
        block = None
        for traffic in manifest.get("traffic") or []:
            if isinstance(traffic, dict) and traffic.get("int_id") == int_id:
                block = traffic
        airframe = (block or {}).get("airframe")
        own = _record_object(record, int_id)
        box3 = (own or {}).get("bbox_3d_camera") if own else None
        if not isinstance(airframe, dict):
            return None, f"{entry.get('id')}: no traffic airframe block in the manifest"
        if not isinstance(box3, dict) or not box3.get("cg_m") or not box3.get("body_axes_in_camera"):
            return None, (f"{entry.get('id')}: the record carries no bbox_3d_camera "
                          f"placement for it")
        cg = tuple(float(v) for v in box3["cg_m"])
        body_axes = [tuple(float(v) for v in row) for row in box3["body_axes_in_camera"]]
        placement = ("the record's bbox_3d_camera placement (the manifest records no "
                     "per-frame traffic state; the projection and the pixels are graded, "
                     "the placement is not independently re-derived)")
    box, basis = _hull_box_body(manifest, airframe, entry.get("role") == "primary"
                                or int_id == AIRCRAFT_INSTANCE_ID)
    lo = (box["forward"][0], box["right"][0], box["down"][0])
    hi = (box["forward"][1], box["right"][1], box["down"][1])
    centre_body = tuple((a + b) / 2.0 for a, b in zip(lo, hi))
    half = tuple((b - a) / 2.0 for a, b in zip(lo, hi))

    def place(body):
        return tuple(cg[i] + sum(body[k] * body_axes[k][i] for k in range(3))
                     for i in range(3))

    corners = [place((x, y, z)) for x in box["forward"] for y in box["right"]
               for z in box["down"]]
    keypoints = {}
    for kp in airframe.get("keypoints") or []:
        if isinstance(kp, dict) and kp.get("name") and kp.get("body_m"):
            keypoints[str(kp["name"])] = place(tuple(float(v) for v in kp["body_m"]))
    return {
        "centre": place(centre_body), "axes": body_axes, "half": half,
        "cg": cg, "corners": corners, "keypoints": keypoints,
        "length_m": float(box["forward"][1] - box["forward"][0]),
        "basis": f"{basis}; placement: {placement}",
    }, ""


def _projected_hull(record: Dict, geometry: Dict):
    """(unclipped box, clipped box, cg pixel) of the object's hull, or
    ``None`` when a corner is behind the camera."""
    pixels = [_pinhole(record, c) for c in geometry["corners"]]
    if any(p is None for p in pixels):
        return None
    us = [p[0] for p in pixels]
    vs = [p[1] for p in pixels]
    unclipped = (min(us), min(vs), max(us), max(vs))
    width, height = float(record["width_px"]), float(record["height_px"])
    clipped = (max(unclipped[0], 0.0), max(unclipped[1], 0.0),
               min(unclipped[2], width), min(unclipped[3], height))
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        clipped = None
    return unclipped, clipped, _pinhole(record, geometry["cg"])


def _iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])
    union = area(a) + area(b) - inter
    return inter / union if union > 0.0 else 0.0


def _ray_box_depths(record: Dict, geometry: Dict, xs, ys):
    """For pixel centres (xs, ys): the camera-z depth at which the ray
    enters and leaves the object's oriented box, and whether it hits it
    at all. The slab test, vectorised; the ray is parametrised by camera
    z so the parameter IS the scene depth the engine writes."""
    import numpy as np

    cx, cy = record["principal_point_px"]
    d = (np.asarray(xs, dtype=float) + 0.5 - cx) / float(record["fx_px"])
    e = (np.asarray(ys, dtype=float) + 0.5 - cy) / float(record["fy_px"])
    ones = np.ones_like(d)
    t_enter = np.full(d.shape, -np.inf)
    t_exit = np.full(d.shape, np.inf)
    hit = np.ones(d.shape, dtype=bool)
    centre = geometry["centre"]
    for axis, half in zip(geometry["axes"], geometry["half"]):
        origin = -sum(a * c for a, c in zip(axis, centre))
        direction = axis[0] * d + axis[1] * e + axis[2] * ones
        parallel = np.abs(direction) < 1e-12
        with np.errstate(divide="ignore", invalid="ignore"):
            t0 = (-half - origin) / direction
            t1 = (half - origin) / direction
        lo, hi = np.minimum(t0, t1), np.maximum(t0, t1)
        lo = np.where(parallel, -np.inf, lo)
        hi = np.where(parallel, np.inf, hi)
        hit &= ~(parallel & (abs(origin) > half))
        t_enter = np.maximum(t_enter, lo)
        t_exit = np.minimum(t_exit, hi)
    hit &= (t_exit >= t_enter) & (t_exit > 0.0)
    return np.maximum(t_enter, 0.0), t_exit, hit


def _alone_files(labels: Dict) -> Dict[int, str]:
    """``{int_id: alone png}`` the record declares."""
    out: Dict[int, str] = {}
    for declared in labels.get("objects") or []:
        if isinstance(declared, dict) and declared.get("alone_png"):
            try:
                out[int(declared["int_id"])] = str(declared["alone_png"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _silhouette(folder: Path, labels: Dict, mask, int_id: int):
    """(the object's silhouette, its basis): the alone footprint when the
    engine wrote one -- the object drawn with nothing in front of it,
    so occlusion does not shrink it -- else its visible pixels in the
    ID image. None when the alone file is unreadable."""
    alone = _alone_files(labels).get(int_id)
    if alone is None:
        return mask == int_id, "the ID image (no alone pass declared)"
    array = _read_gray_png(folder / alone)
    if array is None or array.shape != mask.shape:
        return None, f"{alone} is not an image of the frame's size"
    return array == int_id, f"the alone pass {alone}"


def _bundle_frames(manifest: Dict, run_dir):
    """Yield (record, camera, name, engine record, folder) for every
    labelled manifest frame with a render.json label record."""
    declared = _engine_label_records(run_dir)
    for record in _labelled_frames(manifest):
        camera = str(record["camera_id"])
        name = Path(str(record["file"])).name
        engine = declared.get(camera, {}).get(name)
        if engine is None:
            continue
        yield record, camera, name, engine, Path(run_dir) / "frames" / camera


# -- the checks ---------------------------------------------------------------

def verify_mask_integers_only(manifest: Dict, run_dir=None) -> Check:
    """The ID image holds the declared object integers and nothing else.

    Three clauses, each an independent reading of the bundle: (1) the
    histogram of ``_mask.png`` -- every non-zero value is a declared,
    labelled, in-scene ``int_id``; (2) the class image agrees with the
    ID image pixel for pixel -- a pixel whose id maps to one class while
    the class image states another is a blended or mis-stencilled edge;
    (3) the engine's own ``non_integer_id_pixels`` count (the readback
    floats that were not whole numbers before quantisation) is zero.

    NOT claimed: a blend that rounds to a DECLARED integer (the ids are
    contiguous from 1) is invisible to the histogram; clause (2) sees it
    when the class image did not blend the same way, the engine's count
    sees it at the source, and mask_vs_geometry sees where it lands.
    Pixels with id 0 but a non-zero class are unlabelled geometry (the
    engine's ``unlabelled_geometry_pixels``): reported, not failed.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("mask_integers_only", NOT_RUN, _no_objects_reason(manifest))
    if not _engine_label_records(run_dir):
        return Check("mask_integers_only", NOT_RUN, _no_bundle_reason())
    import numpy as np

    labelled = _labelled_ids(objects)
    declared_ids = sorted(labelled)
    class_of = {i: int(e.get("class_id", 0)) for i, e in labelled.items()}
    seen = set()
    frames = 0
    unlabelled = 0
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        if not labels.get("mask"):
            continue
        mask = _read_gray_png(folder / labels["mask"])
        if mask is None:
            return Check("mask_integers_only", NOT_RUN, "Pillow unavailable")
        if mask.ndim != 2:
            return Check("mask_integers_only", FAIL,
                         f"{camera}/{name}: {labels['mask']} has {mask.ndim} "
                         f"dimensions; an ID image is one integer per pixel",
                         failure=FAIL_MASK_BLEND)
        values, counts = np.unique(mask, return_counts=True)
        undeclared = [(int(v), int(c)) for v, c in zip(values, counts)
                      if int(v) != 0 and int(v) not in labelled]
        if undeclared:
            return Check("mask_integers_only", FAIL,
                         f"{camera}/{name}: the ID image holds values no object "
                         f"declares: " + ", ".join(f"{v} ({c} px)" for v, c in undeclared[:6])
                         + f"; declared ids {declared_ids}",
                         failure=FAIL_MASK_BLEND)
        seen.update(int(v) for v in values if int(v) != 0)
        non_integer = labels.get("non_integer_id_pixels")
        if isinstance(non_integer, (int, float)) and non_integer > 0:
            return Check("mask_integers_only", FAIL,
                         f"{camera}/{name}: the engine read {int(non_integer)} "
                         f"ID pixels that were not whole numbers (a blended pass); "
                         f"the ID image was quantised from them",
                         failure=FAIL_MASK_BLEND)
        if labels.get("class_mask"):
            classes = _read_gray_png(folder / labels["class_mask"])
            if classes is not None and classes.shape == mask.shape:
                lut = np.zeros(int(mask.max()) + 1, dtype=np.int64)
                for i, c in class_of.items():
                    if i < lut.size:
                        lut[i] = c
                expected = lut[mask.astype(np.int64)]
                ided = mask != 0
                disagree = int(np.count_nonzero(ided & (classes.astype(np.int64) != expected)))
                if disagree:
                    return Check("mask_integers_only", FAIL,
                                 f"{camera}/{name}: {disagree} pixels carry an object "
                                 f"id whose class is not what the class image states "
                                 f"(a blended edge takes one image's value and not "
                                 f"the other's)",
                                 failure=FAIL_MASK_BLEND)
                unlabelled += int(np.count_nonzero(~ided & (classes != 0)))
        frames += 1
    if frames == 0:
        return Check("mask_integers_only", NOT_RUN,
                     "engine label records declared but none matched a labelled frame")
    note = (f"; {unlabelled} pixels of geometry carry a class but no id "
            f"(unlabelled, reported not failed)" if unlabelled else "")
    return Check("mask_integers_only", PASS,
                 f"{frames} ID images hold only {sorted(seen)} of the declared "
                 f"{declared_ids} (0 background); the class image agrees at every "
                 f"labelled pixel; the engine counted no non-integer ids{note}")


def verify_mask_vs_geometry(manifest: Dict, run_dir=None) -> Check:
    """The ID mask sits where the geometry says the object is.

    Per aircraft object per frame, through this module's own rotation
    and pinhole: the centre of the silhouette's tight box against the
    centre of the projected hull box, within MASK_CENTROID_TOL_FRACTION
    of the projected hull span (graded only when the hull lies wholly
    inside the image: a truncated silhouette has no meaningful centre),
    and the tight box's width and height against the projected hull
    box's (within MASK_EXTENT_TOL_FRACTION). A hull inside the image
    with no pixels, or pixels for a hull outside it, fails outright.
    The silhouette graded is the object's ALONE pass where the engine
    wrote one -- the object drawn with nothing in front of it, so an
    occluder does not shrink or shift it -- else its pixels in the ID
    image; whether the ID image then shows the right part of that
    silhouette is visibility_vs_scene's question.

    Contracts §3 says "mask centroid vs projected CG". Measured on a
    perfectly placed box silhouette and stated on the page: a hull is
    not centred on its CG (the 747's box centre sits 4.8 m above it,
    6 % of the span seen from behind), and perspective does not preserve
    area centroids (at the 185 m wingman slot the near end of a 70 m box
    projects 1.5x the far end, putting the area centroid 5.6 % of the
    span from the projected centre). Two extent centres compare like
    with like; the area centroid and the projected CG are reported in
    the detail, not graded.
    This is the check that exposes the Phase 1 offset: a mesh drawn
    25-30 m ahead of its label moves the centroid by a third of the
    span. A shift ALONG the line of sight is invisible to it (a chase
    camera looks down the axis); the second camera sees it, and
    depth_vs_geometry bounds it.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("mask_vs_geometry", NOT_RUN, _no_objects_reason(manifest))
    if not _engine_label_records(run_dir):
        return Check("mask_vs_geometry", NOT_RUN, _no_bundle_reason())
    import numpy as np

    aircraft = _aircraft_entries(objects)
    graded = 0
    not_claimed = 0
    skipped: Dict[str, str] = {}
    worst_centroid = (0.0, "")
    worst_extent = (0.0, "")
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        if not labels.get("mask"):
            continue
        mask = _read_gray_png(folder / labels["mask"])
        if mask is None:
            return Check("mask_vs_geometry", NOT_RUN, "Pillow unavailable")
        axes = axes_from_quat(record["quaternion_wxyz"])
        for entry in aircraft:
            int_id = int(entry["int_id"])
            where = f"{camera}/{name} {entry.get('id')}"
            geometry, why = _object_geometry(manifest, record, entry, axes)
            if geometry is None:
                skipped[str(entry.get("id"))] = why
                continue
            hull = _projected_hull(record, geometry)
            hit, source = _silhouette(folder, labels, mask, int_id)
            if hit is None:
                return Check("mask_vs_geometry", FAIL, f"{where}: {source}",
                             failure=FAIL_MASK_OFFSET)
            pixels = int(np.count_nonzero(hit))
            if hull is None:
                if pixels:
                    return Check("mask_vs_geometry", FAIL,
                                 f"{where}: {pixels} pixels carry its id in {source} "
                                 f"while a hull corner is behind the camera",
                                 failure=FAIL_MASK_OFFSET)
                continue
            unclipped, clipped, cg_px = hull
            if clipped is None:
                if pixels > BOX_IOU_MIN_PX:
                    return Check("mask_vs_geometry", FAIL,
                                 f"{where}: {pixels} pixels carry its id while its "
                                 f"hull projects outside the image "
                                 f"({', '.join(f'{v:.0f}' for v in unclipped)})",
                                 failure=FAIL_MASK_OFFSET)
                continue
            hull_w, hull_h = clipped[2] - clipped[0], clipped[3] - clipped[1]
            span = max(hull_w, hull_h)
            if span < BOX_IOU_MIN_PX:
                not_claimed += 1
                continue
            if pixels == 0:
                return Check("mask_vs_geometry", FAIL,
                             f"{where}: the hull projects inside the image "
                             f"({span:.0f} px span) but {source} has no pixel of "
                             f"its id",
                             failure=FAIL_MASK_OFFSET)
            ys, xs = np.nonzero(hit)
            tight_w = float(xs.max() + 1 - xs.min())
            tight_h = float(ys.max() + 1 - ys.min())
            extent = max(abs(tight_w - hull_w) / hull_w, abs(tight_h - hull_h) / hull_h)
            extent_px = max(abs(tight_w - hull_w), abs(tight_h - hull_h))
            if extent > worst_extent[0]:
                worst_extent = (extent, f"{where} ({tight_w:.0f}x{tight_h:.0f} px vs "
                                        f"hull {hull_w:.0f}x{hull_h:.0f})")
            graded += 1
            if extent > MASK_EXTENT_TOL_FRACTION and extent_px > MASK_TOL_PX:
                return Check("mask_vs_geometry", FAIL,
                             f"{where}: mask extent {tight_w:.0f}x{tight_h:.0f} px "
                             f"against a projected hull of {hull_w:.0f}x{hull_h:.0f} "
                             f"px ({extent * 100:.1f} % off, tol "
                             f"{MASK_EXTENT_TOL_FRACTION * 100:.0f} % or {MASK_TOL_PX:g} "
                             f"px); basis: "
                             f"{geometry['basis']}",
                             failure=FAIL_MASK_OFFSET)
            inside = (unclipped[0] >= 0.0 and unclipped[1] >= 0.0
                      and unclipped[2] <= float(record["width_px"])
                      and unclipped[3] <= float(record["height_px"]))
            if inside:
                centre_px = ((unclipped[0] + unclipped[2]) / 2.0,
                             (unclipped[1] + unclipped[3]) / 2.0)
                centre_mask = (float(xs.min() + xs.max() + 1) / 2.0,
                               float(ys.min() + ys.max() + 1) / 2.0)
                offset = math.dist(centre_mask, centre_px)
                relative = offset / span
                if relative > worst_centroid[0]:
                    worst_centroid = (relative, f"{where} ({offset:.1f} px of "
                                                f"{span:.0f} px span)")
                if relative > MASK_CENTROID_TOL_FRACTION and offset > MASK_TOL_PX:
                    centroid = (float(xs.mean()) + 0.5, float(ys.mean()) + 0.5)
                    cg_text = (f"({cg_px[0]:.0f}, {cg_px[1]:.0f})"
                               if cg_px is not None else "behind the camera")
                    return Check("mask_vs_geometry", FAIL,
                                 f"{where}: the centre of the mask's box "
                                 f"({centre_mask[0]:.0f}, {centre_mask[1]:.0f}) sits "
                                 f"{offset:.1f} px from the centre of the projected "
                                 f"hull box ({centre_px[0]:.0f}, {centre_px[1]:.0f}) "
                                 f"-- {relative * 100:.1f} % of the {span:.0f} px hull "
                                 f"span, tol {MASK_CENTROID_TOL_FRACTION * 100:.0f} % "
                                 f"or {MASK_TOL_PX:g} px (area centroid "
                                 f"({centroid[0]:.0f}, {centroid[1]:.0f}), projected "
                                 f"CG {cg_text}); the pixels of {source} are not "
                                 f"where the geometry puts the object; basis: "
                                 f"{geometry['basis']}",
                                 failure=FAIL_MASK_OFFSET)
    if graded == 0:
        why = "; ".join(f"{k}: {v}" for k, v in list(skipped.items())[:3])
        return Check("mask_vs_geometry", NOT_RUN,
                     f"no aircraft object could be graded ({not_claimed} under "
                     f"{BOX_IOU_MIN_PX:.0f} px, not claimed{'; ' + why if why else ''})")
    notes = []
    if not_claimed:
        notes.append(f"{not_claimed} object-frames under {BOX_IOU_MIN_PX:.0f} px not claimed")
    for key, why in skipped.items():
        notes.append(f"{key} not graded: {why}")
    return Check("mask_vs_geometry", PASS,
                 f"{graded} object-frames; worst box-centre offset "
                 f"{worst_centroid[0] * 100:.2f} % of span at "
                 f"{worst_centroid[1] or 'none graded'} (tol "
                 f"{MASK_CENTROID_TOL_FRACTION * 100:.0f} %); worst extent "
                 f"{worst_extent[0] * 100:.2f} % at {worst_extent[1] or 'none'} (tol "
                 f"{MASK_EXTENT_TOL_FRACTION * 100:.0f} %)"
                 + (f"; {'; '.join(notes)}" if notes else ""))


def verify_box_vs_mask(manifest: Dict, run_dir=None) -> Check:
    """The tight box from the ID mask against the projected hull box.

    IoU at or above BOX_IOU_MIN_LARGE for a hull spanning at least
    BOX_IOU_LARGE_PX pixels, BOX_IOU_MIN_SMALL down to BOX_IOU_MIN_PX,
    not claimed below (counted). The tight box graded is the object's
    silhouette -- its alone pass where the engine wrote one, so that a
    legitimately occluded object is not failed for the part an
    occluder hides; else its visible pixels. The record's
    ``bbox_2d_tight`` is by definition the VISIBLE pixels' box (the
    producer measured the ID image), so it is graded against this
    module's box of the same visible pixels, to a pixel. Supersedes
    mask_containment for manifest 6.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("box_vs_mask", NOT_RUN, _no_objects_reason(manifest))
    if not _engine_label_records(run_dir):
        return Check("box_vs_mask", NOT_RUN, _no_bundle_reason())
    import numpy as np

    aircraft = _aircraft_entries(objects)
    graded = 0
    not_claimed = 0
    worst = (1.0, "")
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        if not labels.get("mask"):
            continue
        mask = _read_gray_png(folder / labels["mask"])
        if mask is None:
            return Check("box_vs_mask", NOT_RUN, "Pillow unavailable")
        axes = axes_from_quat(record["quaternion_wxyz"])
        for entry in aircraft:
            int_id = int(entry["int_id"])
            where = f"{camera}/{name} {entry.get('id')}"
            geometry, why = _object_geometry(manifest, record, entry, axes)
            if geometry is None:
                continue
            hull = _projected_hull(record, geometry)
            visible = mask == int_id
            recorded = (_record_object(record, int_id) or {}).get("bbox_2d_tight")
            if recorded is not None and visible.any():
                ys, xs = np.nonzero(visible)
                own = (float(xs.min()), float(ys.min()), float(xs.max()) + 1.0,
                       float(ys.max()) + 1.0)
                gap = max(abs(float(a) - b) for a, b in zip(recorded, own))
                if gap > 0.5:
                    return Check("box_vs_mask", FAIL,
                                 f"{where}: the record's bbox_2d_tight "
                                 f"{[round(float(v), 1) for v in recorded]} is not "
                                 f"the box of its own visible pixels "
                                 f"{[round(v, 1) for v in own]} ({gap:.1f} px off)",
                                 failure=FAIL_BOX_MISMATCH)
            hit, source = _silhouette(folder, labels, mask, int_id)
            if hit is None or hull is None or hull[1] is None or not hit.any():
                continue        # mask_vs_geometry grades presence
            _, clipped, _ = hull
            span = max(clipped[2] - clipped[0], clipped[3] - clipped[1])
            if span < BOX_IOU_MIN_PX:
                not_claimed += 1
                continue
            ys, xs = np.nonzero(hit)
            tight = (float(xs.min()), float(ys.min()), float(xs.max()) + 1.0,
                     float(ys.max()) + 1.0)
            iou = _iou(tight, clipped)
            floor = BOX_IOU_MIN_LARGE if span >= BOX_IOU_LARGE_PX else BOX_IOU_MIN_SMALL
            graded += 1
            if iou < worst[0]:
                worst = (iou, f"{where} ({span:.0f} px span, floor {floor})")
            if iou < floor:
                return Check("box_vs_mask", FAIL,
                             f"{where}: tight box {[round(v) for v in tight]} of "
                             f"{source} vs projected hull box "
                             f"{[round(v) for v in clipped]}: IoU {iou:.3f} below "
                             f"{floor} for a {span:.0f} px span; basis: "
                             f"{geometry['basis']}",
                             failure=FAIL_BOX_MISMATCH)
    if graded == 0:
        return Check("box_vs_mask", NOT_RUN,
                     f"no aircraft object with pixels and a projected hull to grade "
                     f"({not_claimed} under {BOX_IOU_MIN_PX:.0f} px, not claimed)")
    return Check("box_vs_mask", PASS,
                 f"{graded} object-frames; lowest IoU {worst[0]:.3f} at {worst[1]} "
                 f"(floors {BOX_IOU_MIN_LARGE} at >= {BOX_IOU_LARGE_PX:.0f} px, "
                 f"{BOX_IOU_MIN_SMALL} at >= {BOX_IOU_MIN_PX:.0f} px)"
                 + (f"; {not_claimed} under {BOX_IOU_MIN_PX:.0f} px not claimed"
                    if not_claimed else ""))


def verify_depth_vs_geometry(manifest: Dict, run_dir=None) -> Check:
    """The depth under the ID mask against the projected geometry.

    Per aircraft object per frame, with ``tol(z) = DEPTH_TOL_FRACTION *
    z + DEPTH_TOL_M``: (1) no mask pixel reads as sky; (2) the nearest
    depth under the mask is no nearer than the hull's nearest corner and
    (3) the farthest no farther than its farthest -- the box contains
    the airframe, so both hold on any view; (4) the nearest depth under
    the mask is no FARTHER than the nearest keypoint (a keypoint is on
    the airframe, so the nearest visible surface is at most as deep) --
    the clause a scaled depth fails: from behind, the tail is the
    nearest surface, and a 2 % scale beyond 200 m moves it past the
    tolerance; (5) the record's depth_min_m / depth_median_m are these
    pixels, and agree to DEPTH_RECORD_TOL_M. The median against the
    projected CG depth is reported. Supersedes depth_range for manifest
    6. NOT claimed: a scale under 2 % inside 200 m, where 1 % + 2 m is
    wider than the scale.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("depth_vs_geometry", NOT_RUN, _no_objects_reason(manifest))
    if not _engine_label_records(run_dir):
        return Check("depth_vs_geometry", NOT_RUN, _no_bundle_reason())
    import numpy as np

    def tol(z: float) -> float:
        return DEPTH_TOL_FRACTION * abs(z) + DEPTH_TOL_M

    aircraft = _aircraft_entries(objects)
    graded = 0
    worst_median = (0.0, "")
    worst_near = (-math.inf, "")
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        if not labels.get("mask") or not (labels.get("depth_f32") or labels.get("depth")):
            continue
        mask = _read_gray_png(folder / labels["mask"])
        if mask is None:
            return Check("depth_vs_geometry", NOT_RUN, "Pillow unavailable")
        depth = _read_depth_metres(folder, labels, int(record["width_px"]),
                                   int(record["height_px"]))
        if isinstance(depth, str):
            return Check("depth_vs_geometry", FAIL, f"{camera}/{name}: {depth}",
                         failure=FAIL_DEPTH_RANGE)
        if depth.shape != mask.shape:
            return Check("depth_vs_geometry", FAIL,
                         f"{camera}/{name}: depth is {depth.shape[1]}x{depth.shape[0]}, "
                         f"the ID image {mask.shape[1]}x{mask.shape[0]}",
                         failure=FAIL_DEPTH_RANGE)
        axes = axes_from_quat(record["quaternion_wxyz"])
        for entry in aircraft:
            int_id = int(entry["int_id"])
            where = f"{camera}/{name} {entry.get('id')}"
            hit = mask == int_id
            if not hit.any():
                continue
            geometry, why = _object_geometry(manifest, record, entry, axes)
            if geometry is None:
                continue
            under = depth[hit]
            sky = int(np.count_nonzero(~np.isfinite(under)))
            if sky:
                return Check("depth_vs_geometry", FAIL,
                             f"{where}: {sky} of {under.size} mask pixels read as sky "
                             f"(no finite depth) where the ID image says the object is",
                             failure=FAIL_DEPTH_RANGE)
            d_min, d_max = float(under.min()), float(under.max())
            d_median = float(np.median(under))
            z_corners = [c[2] for c in geometry["corners"]]
            z_near, z_far = min(z_corners), max(z_corners)
            if d_min < z_near - tol(z_near):
                return Check("depth_vs_geometry", FAIL,
                             f"{where}: nearest depth under the mask {d_min:.1f} m is "
                             f"nearer than the hull's nearest corner {z_near:.1f} m by "
                             f"more than {tol(z_near):.1f} m; basis: {geometry['basis']}",
                             failure=FAIL_DEPTH_RANGE)
            if d_max > z_far + tol(z_far):
                return Check("depth_vs_geometry", FAIL,
                             f"{where}: farthest depth under the mask {d_max:.1f} m is "
                             f"beyond the hull's farthest corner {z_far:.1f} m by more "
                             f"than {tol(z_far):.1f} m; basis: {geometry['basis']}",
                             failure=FAIL_DEPTH_RANGE)
            if geometry["keypoints"]:
                nearest_name, nearest = min(geometry["keypoints"].items(),
                                            key=lambda kv: kv[1][2])
                z_kp = nearest[2]
                gap = d_min - z_kp
                if gap > worst_near[0]:
                    worst_near = (gap, f"{where} ({nearest_name} at {z_kp:.1f} m, "
                                       f"mask from {d_min:.1f} m)")
                if gap > tol(z_kp):
                    return Check("depth_vs_geometry", FAIL,
                                 f"{where}: the nearest depth under the mask "
                                 f"{d_min:.1f} m is {gap:.1f} m FARTHER than the "
                                 f"nearest keypoint ({nearest_name} projects at "
                                 f"{z_kp:.1f} m; tol {tol(z_kp):.1f} m) -- a "
                                 f"surface point cannot be behind a point on the "
                                 f"surface, so the depth is scaled or shifted; "
                                 f"basis: {geometry['basis']}",
                                 failure=FAIL_DEPTH_RANGE)
            cg_z = geometry["cg"][2]
            if abs(d_median - cg_z) > worst_median[0]:
                worst_median = (abs(d_median - cg_z), f"{where} (median {d_median:.1f} m, "
                                                      f"CG {cg_z:.1f} m)")
            recorded = _record_object(record, int_id) or {}
            for key, own in (("depth_min_m", d_min), ("depth_median_m", d_median)):
                value = recorded.get(key)
                if isinstance(value, (int, float)) and abs(float(value) - own) > DEPTH_RECORD_TOL_M:
                    return Check("depth_vs_geometry", FAIL,
                                 f"{where}: the record's {key} {float(value):.2f} m is "
                                 f"not what the depth file holds under the mask "
                                 f"({own:.2f} m)",
                                 failure=FAIL_DEPTH_RANGE)
            graded += 1
    if graded == 0:
        return Check("depth_vs_geometry", NOT_RUN,
                     "no aircraft object with mask pixels, a depth file and a "
                     "projected hull to grade")
    return Check("depth_vs_geometry", PASS,
                 f"{graded} object-frames within the hull's depth band at "
                 f"{DEPTH_TOL_FRACTION * 100:.0f} % + {DEPTH_TOL_M:g} m; nearest "
                 f"surface at most {worst_near[0]:.2f} m beyond the nearest keypoint "
                 f"at {worst_near[1] or 'none'}; median depth vs projected CG depth "
                 f"differs by at most {worst_median[0]:.1f} m at {worst_median[1] or 'none'}")


def verify_visibility_vs_scene(manifest: Dict, run_dir=None) -> Check:
    """The alone passes against the ID pass: what the scene hides.

    Per aircraft object with an alone pass, re-counted from the files:
    (1) its visible pixels lie inside its alone footprint; (2) every
    hidden footprint pixel has something NEARER drawn over it -- a
    declared id at a finite depth no deeper than the object's own depth
    plus half its length: a footprint pixel showing sky, or something
    behind the object, is an object the ID pass dropped; (3) where two
    aircraft footprints overlap and their depths order them
    unambiguously, the nearer one owns the overlap pixels -- the
    occluder hidden from the full pass (its stencil missing where the
    other's footprint is, the depth capture untouched) fails here; (4)
    the recorded pixel counts,
    ``visible_fraction`` and ``occluded_by`` (render.json integers; the
    manifest's strings resolved through objects[]) are these same counts,
    and every occluder named is a declared object. An object's own
    depth is its projected CG depth (the geometry, independent of the
    engine's depth image, which a wrong ID pass can contradict); only
    an object with no geometry falls back to the median under its
    visible pixels. Each tolerance is VISIBILITY_TOL_FRACTION of the
    footprint or of the overlap. NOT RUN without alone passes. The
    terrain has no alone pass and is graded only as an occluder.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("visibility_vs_scene", NOT_RUN, _no_objects_reason(manifest))
    if not _engine_label_records(run_dir):
        return Check("visibility_vs_scene", NOT_RUN, _no_bundle_reason())
    import numpy as np

    labelled = _labelled_ids(objects)
    id_of = {i: str(e.get("id")) for i, e in labelled.items()}
    aircraft = {int(e["int_id"]): e for e in _aircraft_entries(objects)}
    graded = 0
    alone_seen = False
    worst = (0.0, "")

    def fail(text: str) -> Check:
        return Check("visibility_vs_scene", FAIL, text, failure=FAIL_VISIBILITY)

    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        if not labels.get("mask"):
            continue
        alone_files = _alone_files(labels)
        if not alone_files:
            continue
        alone_seen = True
        mask = _read_gray_png(folder / labels["mask"])
        if mask is None:
            return Check("visibility_vs_scene", NOT_RUN, "Pillow unavailable")
        depth = _read_depth_metres(folder, labels, int(record["width_px"]),
                                   int(record["height_px"]))
        if isinstance(depth, str) or depth.shape != mask.shape:
            depth = None
        axes = axes_from_quat(record["quaternion_wxyz"])
        footprints: Dict[int, object] = {}
        depths: Dict[int, Optional[float]] = {}
        half_len: Dict[int, float] = {}
        for int_id, file in sorted(alone_files.items()):
            if int_id not in aircraft:
                return fail(f"{camera}/{name}: an alone pass is declared for id "
                            f"{int_id}, which is not a labelled aircraft object")
            alone = _read_gray_png(folder / file)
            if alone is None or alone.shape != mask.shape:
                return fail(f"{camera}/{name}: {file} is not an image of the frame's size")
            footprints[int_id] = alone == int_id
            geometry, _ = _object_geometry(manifest, record, aircraft[int_id], axes)
            half_len[int_id] = geometry["length_m"] / 2.0 if geometry else 0.0
            visible = mask == int_id
            if geometry is not None:
                depths[int_id] = geometry["cg"][2]
            elif depth is not None and visible.any():
                finite = depth[visible][np.isfinite(depth[visible])]
                depths[int_id] = float(np.median(finite)) if finite.size else None
            else:
                depths[int_id] = None
        for int_id, footprint in footprints.items():
            where = f"{camera}/{name} {id_of.get(int_id, int_id)}"
            n_alone = int(np.count_nonzero(footprint))
            visible = mask == int_id
            n_vis = int(np.count_nonzero(visible))
            stray = int(np.count_nonzero(visible & ~footprint))
            if stray > VISIBILITY_TOL_FRACTION * max(n_alone, 1):
                return fail(f"{where}: {stray} pixels carry its id outside its alone "
                            f"footprint of {n_alone} px -- the ID pass and the alone "
                            f"pass do not draw it in the same place")
            hidden = footprint & ~visible
            if hidden.any():
                unexplained = hidden & (mask == 0)
                if depth is not None:
                    unexplained |= hidden & ~np.isfinite(depth)
                    if depths.get(int_id) is not None:
                        limit = depths[int_id] + half_len[int_id] + (
                            DEPTH_TOL_FRACTION * depths[int_id] + DEPTH_TOL_M)
                        unexplained |= hidden & (depth > limit)
                n_bad = int(np.count_nonzero(unexplained))
                fraction = n_bad / max(n_alone, 1)
                if fraction > worst[0]:
                    worst = (fraction, f"{where} ({n_bad} of {n_alone} footprint px)")
                if n_bad > VISIBILITY_TOL_FRACTION * max(n_alone, 1):
                    return fail(f"{where}: {n_bad} of its {n_alone} footprint pixels "
                                f"are hidden with nothing nearer drawn over them (sky, "
                                f"background, or a surface beyond the object) -- the "
                                f"ID pass dropped it where nothing occludes it")
            own_occluders = sorted(int(v) for v in np.unique(mask[footprint])
                                   if int(v) not in (0, int_id))
            for occluder in own_occluders:
                if occluder not in labelled:
                    return fail(f"{where}: occluded by id {occluder}, which no object "
                                f"declares")
            own_fraction = (n_vis / n_alone) if n_alone else None
            engine_entry = _engine_object(engine, int_id) or {}
            for key, own in (("pixels", n_vis), ("pixels_alone", n_alone)):
                value = engine_entry.get(key)
                if isinstance(value, (int, float)) and int(value) != own:
                    return fail(f"{where}: render.json says {key} {int(value)}, the "
                                f"files hold {own}")
            engine_fraction = engine_entry.get("visible_fraction")
            if (isinstance(engine_fraction, (int, float)) and own_fraction is not None
                    and abs(float(engine_fraction) - own_fraction) > VISIBILITY_RECORD_TOL):
                return fail(f"{where}: render.json visible_fraction "
                            f"{float(engine_fraction):.4f} is not the files' "
                            f"{own_fraction:.4f}")
            engine_occ = engine_entry.get("occluded_by")
            if isinstance(engine_occ, list) and sorted(int(v) for v in engine_occ) != own_occluders:
                return fail(f"{where}: render.json occluded_by {engine_occ} but the "
                            f"footprint holds {own_occluders}")
            recorded = _record_object(record, int_id) or {}
            rec_fraction = recorded.get("visible_fraction")
            if (isinstance(rec_fraction, (int, float)) and own_fraction is not None
                    and abs(float(rec_fraction) - own_fraction) > VISIBILITY_RECORD_TOL):
                return fail(f"{where}: the manifest's visible_fraction "
                            f"{float(rec_fraction):.4f} is not the files' "
                            f"{own_fraction:.4f}")
            rec_occ = recorded.get("occluded_by")
            if isinstance(rec_occ, list):
                expected = sorted(id_of[o] for o in own_occluders)
                if sorted(str(v) for v in rec_occ) != expected:
                    return fail(f"{where}: the manifest's occluded_by {rec_occ} is not "
                                f"what the footprint holds {expected}")
            graded += 1
        ids = sorted(footprints)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                overlap = footprints[a] & footprints[b]
                n_overlap = int(np.count_nonzero(overlap))
                if n_overlap == 0 or depths.get(a) is None or depths.get(b) is None:
                    continue
                margin = half_len[a] + half_len[b] + DEPTH_TOL_M
                if abs(depths[a] - depths[b]) <= margin:
                    continue            # ordering ambiguous at this range
                near, far = (a, b) if depths[a] < depths[b] else (b, a)
                wrong = int(np.count_nonzero(overlap & (mask == far)))
                if wrong > VISIBILITY_TOL_FRACTION * n_overlap:
                    return fail(f"{camera}/{name}: {id_of.get(far, far)} at "
                                f"{depths[far]:.0f} m is drawn over "
                                f"{id_of.get(near, near)} at {depths[near]:.0f} m in "
                                f"{wrong} of their {n_overlap} overlapping footprint "
                                f"pixels -- the nearer object is missing from the "
                                f"full pass")
    if not alone_seen:
        return Check("visibility_vs_scene", NOT_RUN,
                     "the engine declared no alone pass (labels.objects[].alone_png); "
                     "visibility needs the per-object footprint")
    if graded == 0:
        return Check("visibility_vs_scene", NOT_RUN,
                     "alone passes declared but none matched a labelled frame")
    return Check("visibility_vs_scene", PASS,
                 f"{graded} object-frames: visible pixels inside the alone footprint, "
                 f"hidden pixels explained by something nearer (worst unexplained "
                 f"{worst[0] * 100:.2f} % at {worst[1] or 'none'}; tol "
                 f"{VISIBILITY_TOL_FRACTION * 100:.0f} %), overlaps owned by the nearer "
                 f"object, and the recorded fractions and occluders re-counted")


def verify_identity_stable(manifest: Dict, run_dir=None,
                           other_manifest: Optional[Dict] = None) -> Check:
    """One id, one integer -- across frames, cameras, and runs of one
    spec.

    The manifest's ``objects[]`` is the reference. Every frame's
    ``labels.objects[]`` must map each id to the same integer (frames
    and cameras); every camera's render.json must echo the same
    mapping in its root ``objects[]`` and name only those integers in
    its per-frame records (the engine wrote the stencils it was told);
    with ``--against``, the other run's ``objects[]`` must be the same
    mapping when the two runs are of one spec (same ``spec_digest``) --
    a different spec is named, not failed. NOT RUN without a render:
    the engine's echo is half the evidence.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("identity_stable", NOT_RUN, _no_objects_reason(manifest))

    def mapping(entries) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("id") is not None:
                try:
                    out[str(entry["id"])] = int(entry["int_id"])
                except (KeyError, TypeError, ValueError):
                    continue
        return out

    def fail(text: str) -> Check:
        return Check("identity_stable", FAIL, text, failure=FAIL_IDENTITY)

    reference = mapping(objects)
    if len(set(reference.values())) != len(reference):
        return fail(f"objects[] gives one integer to two ids: {reference}")
    frames = 0
    for record in manifest.get("frames", []):
        entries = (record.get("labels") or {}).get("objects")
        if not isinstance(entries, list):
            continue
        frames += 1
        seen = mapping(entries)
        for key, value in seen.items():
            if reference.get(key) != value:
                return fail(f"{record.get('camera_id')}/{record.get('index')}: "
                            f"{key} is {value} in this frame's labels but "
                            f"{reference.get(key)} in objects[]")
    cameras = []
    frames_dir = Path(run_dir) / "frames" if run_dir is not None else None
    if frames_dir is not None and frames_dir.is_dir():
        for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
            path = camera_dir / "render.json"
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            records = _render_frame_records(payload)
            if not any(isinstance(r.get("labels"), dict) for r in records):
                continue
            cameras.append(camera_dir.name)
            echoed = mapping(payload.get("objects"))
            for key, value in echoed.items():
                if reference.get(key) != value:
                    return fail(f"{camera_dir.name}/render.json: the engine wrote "
                                f"{key} as {value} where objects[] says "
                                f"{reference.get(key)} -- the stencils were not "
                                f"the card's")
            for value in set(reference.values()) - set(echoed.values()):
                if echoed:
                    return fail(f"{camera_dir.name}/render.json: objects[] declares "
                                f"int_id {value} but the engine's echo does not "
                                f"name it")
            for r in records:
                for declared in (r.get("labels") or {}).get("objects") or []:
                    if not isinstance(declared, dict):
                        continue
                    try:
                        value = int(declared["int_id"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if value not in reference.values():
                        return fail(f"{camera_dir.name}/{r.get('frame')}: the engine "
                                    f"wrote int_id {value}, which objects[] does not "
                                    f"declare")
    if not cameras:
        return Check("identity_stable", NOT_RUN,
                     f"{frames} frames agree with objects[] {reference}, but no "
                     f"render.json echoes the ids the engine wrote (no engine pass); "
                     f"the engine's half of the evidence is missing")
    note = ""
    if other_manifest is not None:
        other = mapping(_declared_objects(other_manifest))
        if other_manifest.get("spec_digest") == manifest.get("spec_digest"):
            if other != reference:
                return fail(f"the --against run of the same spec maps its objects "
                            f"{other} where this run maps {reference}")
            note = "; the --against run of the same spec maps them identically"
        else:
            note = ("; the --against run is of a different spec, so cross-run "
                    "identity (one spec, one list) is not graded against it")
    return Check("identity_stable", PASS,
                 f"{len(reference)} objects keep one integer each across {frames} "
                 f"frames and {len(cameras)} camera(s) ({sorted(cameras)}), and the "
                 f"engine's render.json echoes the same list{note}")


def verify_applied_intrinsics(manifest: Dict, run_dir=None) -> Check:
    """The lens and picture the ENGINE applied against the record's.

    The commandlet writes ``applied_focal_length_mm``,
    ``applied_sensor_width_mm``, ``applied_fov_deg``, ``applied_width_px``
    and ``applied_height_px`` on every consume-poses frame; this reads
    them back against the record's ``focal_length_mm``,
    ``sensor_width_mm``, ``width_px``, ``height_px`` and the horizontal
    field of view they imply, 2 atan(width / 2 fx) (APPLIED_FOV_TOL_DEG).
    A render at a different field of view scales every mask by the
    ratio of the tangents -- 1 deg at 55 deg is 2 %, under every mask
    tolerance, which is why this check exists. NOT RUN where no record
    carries the applied intrinsics.
    """
    applied: Dict[str, Dict[str, Dict]] = {}
    frames_dir = Path(run_dir) / "frames" if run_dir is not None else None
    if frames_dir is not None and frames_dir.is_dir():
        for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
            path = camera_dir / "render.json"
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            per_frame = {str(r.get("frame")): r for r in _render_frame_records(payload)
                         if isinstance(r, dict) and "applied_fov_deg" in r}
            if per_frame:
                applied[camera_dir.name] = per_frame
    if not applied:
        return Check("applied_intrinsics", NOT_RUN,
                     "no render.json records the applied intrinsics "
                     "(applied_fov_deg et al.; no render, or an older build)")
    counted = 0
    worst_deg = 0.0
    for record in manifest.get("frames", []):
        camera = str(record["camera_id"])
        if camera not in applied:
            continue
        name = Path(str(record["file"])).name
        engine = applied[camera].get(name)
        if engine is None:
            return Check("applied_intrinsics", FAIL,
                         f"{camera}/{name}: the engine recorded no applied intrinsics "
                         f"for this frame while it did for others",
                         failure=FAIL_INTRINSICS)
        fov = math.degrees(2.0 * math.atan(float(record["width_px"])
                                           / (2.0 * float(record["fx_px"]))))
        gap = abs(float(engine["applied_fov_deg"]) - fov)
        worst_deg = max(worst_deg, gap)
        if gap > APPLIED_FOV_TOL_DEG:
            return Check("applied_intrinsics", FAIL,
                         f"{camera}/{name}: the engine rendered at "
                         f"{float(engine['applied_fov_deg']):.3f} deg horizontal field "
                         f"of view where the record's lens implies {fov:.3f} deg "
                         f"(tol {APPLIED_FOV_TOL_DEG} deg); every mask is scaled by "
                         f"the ratio of the tangents",
                         failure=FAIL_INTRINSICS)
        for key, mine in (("applied_width_px", "width_px"),
                          ("applied_height_px", "height_px")):
            if key in engine and int(engine[key]) != int(record[mine]):
                return Check("applied_intrinsics", FAIL,
                             f"{camera}/{name}: {key} {int(engine[key])} where the "
                             f"record states {mine} {int(record[mine])}",
                             failure=FAIL_INTRINSICS)
        for key, mine in (("applied_focal_length_mm", "focal_length_mm"),
                          ("applied_sensor_width_mm", "sensor_width_mm")):
            if key in engine and abs(float(engine[key]) - float(record[mine])) > APPLIED_LENS_TOL_MM:
                return Check("applied_intrinsics", FAIL,
                             f"{camera}/{name}: {key} {float(engine[key]):.3f} where "
                             f"the record states {mine} {float(record[mine]):.3f}",
                             failure=FAIL_INTRINSICS)
        counted += 1
    if counted == 0:
        return Check("applied_intrinsics", NOT_RUN,
                     "applied intrinsics recorded but none matched a manifest frame")
    return Check("applied_intrinsics", PASS,
                 f"{counted} frames rendered at the record's lens and picture size; "
                 f"worst field-of-view gap {worst_deg:.4f} deg (tol "
                 f"{APPLIED_FOV_TOL_DEG} deg)")


# -- Phase 10, P10-3: the sensor model --------------------------------------
#
# sensor_undistortion: every sensor-frame keypoint, undistorted and
# de-rolled with the MANIFEST'S OWN recorded profile and angular rate,
# must land back on the pinhole label. A recorded distortion that does
# not describe the sensor labels -- k1 corrupted, a profile swapped, an
# angular rate dropped -- fails here by the pixel. The inverse model is
# core.capture.profile's; the forward mapping that made the labels is
# the producer's, so this closes the loop rather than repeating it.
#
# sensor_files: every sensor frame a camera's sensor.json declares
# exists. NOT RUN when no camera ran the post-pass.

#: Undistort-then-compare tolerance: Newton to 1e-13 in normalised
#: coordinates leaves float noise, not pixels.
SENSOR_UNDISTORT_TOL_PX = 0.05


def verify_sensor_undistortion(manifest: Dict) -> Check:
    from .profile import (CameraProfile, CameraProfileError,
                          pinhole_pixel_from_sensor)

    profiles: Dict[str, CameraProfile] = {}
    for block in manifest.get("cameras", []):
        recorded = block.get("profile")
        if not isinstance(recorded, dict):
            continue
        try:
            profiles[str(block["camera_id"])] = CameraProfile(
                name=str(recorded["name"]), basis=str(recorded.get("basis", "")),
                source=str(recorded.get("source", "")),
                k1=float(recorded["distortion"]["k1"]),
                k2=float(recorded["distortion"]["k2"]),
                k3=float(recorded["distortion"]["k3"]),
                p1=float(recorded["distortion"]["p1"]),
                p2=float(recorded["distortion"]["p2"]),
                readout_s=float(recorded["rolling_shutter"]["readout_s"]),
                exposure_s=float(recorded["exposure"]["time_s"]),
                reference_exposure_s=float(recorded["exposure"]["reference_time_s"]),
                iso=float(recorded["exposure"]["iso"]),
                base_iso=float(recorded["exposure"]["base_iso"]),
                noise_model=str(recorded["noise"]["model"]),
                full_well_e=float(recorded["noise"].get("full_well_e", 0.0)),
                read_noise_e=float(recorded["noise"].get("read_noise_e", 0.0)),
                vignetting_model=str(recorded["vignetting"]["model"]),
                vignetting_strength=float(recorded["vignetting"].get("strength", 1.0)),
                bit_depth=int(recorded.get("bit_depth", 8)))
        except (KeyError, TypeError, ValueError) as exc:
            return Check("sensor_undistortion", FAIL,
                         f"camera {block.get('camera_id')!r}: recorded profile "
                         f"unreadable ({exc})")
    frames = [f for f in manifest.get("frames", [])
              if isinstance(f.get("sensor"), dict)
              and isinstance(f.get("labels"), dict)]
    if not frames or not profiles:
        return Check("sensor_undistortion", NOT_RUN,
                     "no per-frame sensor block in this manifest (version < 5)")
    worst = 0.0
    worst_where = ""
    counted = 0
    for record in frames:
        camera = str(record["camera_id"])
        profile = profiles.get(camera)
        if profile is None:
            return Check("sensor_undistortion", FAIL,
                         f"{camera}: frames carry a sensor block but the "
                         f"camera block records no profile")
        sensor = record["sensor"]
        if sensor.get("profile") != profile.name:
            return Check("sensor_undistortion", FAIL,
                         f"{camera}/{record['index']}: frame names profile "
                         f"{sensor.get('profile')!r}, camera block "
                         f"{profile.name!r}")
        omega = sensor.get("angular_rate_rad_s") or [0.0, 0.0, 0.0]
        for name, kp in sensor.get("labels_sensor", {}).get("keypoints", {}).items():
            ideal = record["labels"]["keypoints"].get(name)
            if kp.get("u") is None or ideal is None or ideal.get("u") is None:
                continue
            u, v = pinhole_pixel_from_sensor(profile, record, kp["u"], kp["v"],
                                             float(ideal["depth_m"]), omega)
            error = max(abs(u - ideal["u"]), abs(v - ideal["v"]))
            counted += 1
            if error > worst:
                worst, worst_where = error, f"{camera}/{record['index']} {name}"
    if counted == 0:
        return Check("sensor_undistortion", NOT_RUN,
                     "no sensor keypoint had a pinhole counterpart to compare")
    ok = worst <= SENSOR_UNDISTORT_TOL_PX
    return Check("sensor_undistortion", PASS if ok else FAIL,
                 f"{counted} sensor keypoints undistorted with the recorded "
                 f"profile; worst return error {worst:.4f} px at "
                 f"{worst_where} (tolerance {SENSOR_UNDISTORT_TOL_PX})")


def verify_sensor_files(manifest: Dict, run_dir=None) -> Check:
    if run_dir is None:
        return Check("sensor_files", NOT_RUN, "no run directory")
    declared = {}
    frames_dir = Path(run_dir) / "frames"
    if frames_dir.is_dir():
        for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
            path = camera_dir / "sensor.json"
            if path.is_file():
                try:
                    declared[camera_dir.name] = json.loads(
                        path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return Check("sensor_files", FAIL,
                                 f"{path} is unreadable")
    if not declared:
        return Check("sensor_files", NOT_RUN,
                     "no camera ran the sensor post-pass (every profile "
                     "ideal, or no frames rendered)")
    missing = []
    counted = 0
    for camera, entry in declared.items():
        for item in entry.get("frames", []):
            counted += 1
            if not (frames_dir / camera / str(item.get("sensor", ""))).is_file():
                missing.append(f"{camera}/{item.get('sensor')}")
    if missing:
        return Check("sensor_files", FAIL,
                     f"{len(missing)} declared sensor frame(s) absent: "
                     + ", ".join(missing[:4]))
    return Check("sensor_files", PASS,
                 f"{counted} sensor frames present across {sorted(declared)}")


# -- Phase 10, P10-4: the frame on disk is the frame the engine wrote ------

def verify_frame_integrity(manifest: Dict, run_dir=None) -> Check:
    """The render commandlet records the SHA-256 of every PNG it writes
    in render.json; the file on disk must hash to it. A replaced,
    re-encoded or truncated frame fails here BY FRAME -- and so does a
    frame the manifest names that the engine never recorded. NOT RUN
    where no render.json carries digests (an older build, or no
    render)."""
    from .repro import engine_digests, frame_sha256

    if run_dir is None:
        return Check("frame_integrity", NOT_RUN, "no run directory")
    frames_dir = Path(run_dir) / "frames"
    recorded: Dict[str, Dict[str, str]] = {}
    if frames_dir.is_dir():
        for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
            digests = engine_digests(camera_dir)
            if digests:
                recorded[camera_dir.name] = digests
    if not recorded:
        return Check("frame_integrity", NOT_RUN,
                     "no render.json records per-frame sha256 (older engine "
                     "build, or no render)")
    bad = []
    counted = 0
    for record in manifest.get("frames", []):
        camera = str(record["camera_id"])
        if camera not in recorded:
            continue
        name = Path(str(record["file"])).name
        expected = recorded[camera].get(name)
        path = frames_dir / camera / name
        if expected is None:
            bad.append(f"{camera}/{name}: not in the engine's record")
            continue
        if not path.is_file():
            bad.append(f"{camera}/{name}: recorded but absent")
            continue
        counted += 1
        if frame_sha256(path) != expected:
            bad.append(f"{camera}/{name}: bytes differ from the engine's record")
    if bad:
        return Check("frame_integrity", FAIL,
                     f"{len(bad)} frame(s) are not what the engine wrote: "
                     + "; ".join(bad[:4]))
    return Check("frame_integrity", PASS,
                 f"{counted} frames hash to the engine's own record across "
                 f"{sorted(recorded)}")


PROJECTION_MATRIX_TOL_PX = 1e-3


def verify_projection_matrix(manifest: Dict) -> Check:
    """Every frame's projection_matrix projects the aircraft (and every
    landmark in front of the camera) to the SAME pixel as the record's
    parameters through the manifest's stated formula, to a thousandth
    of a pixel; the intrinsic_matrix carries the record's own fx, fy
    and principal point. A matrix that disagrees with the parameters it
    claims to summarise fails by frame. NOT RUN on a manifest with no
    matrices (older than this check)."""
    from .labels import camera_axes, project_with_matrix, to_camera, to_pixel

    frames = manifest.get("frames", [])
    carried = [r for r in frames if "projection_matrix" in r]
    if not carried:
        return Check("projection_matrix", NOT_RUN,
                     "no frame carries a projection_matrix")
    landmarks = [(lm["north_m"], lm["east_m"], lm["alt_m"])
                 for lm in manifest.get("landmarks", [])]
    bad = []
    worst = 0.0
    compared = 0
    for record in frames:
        P = record.get("projection_matrix")
        K = record.get("intrinsic_matrix")
        name = f"{record.get('camera_id')}/{record.get('index')}"
        if P is None or K is None:
            bad.append(f"{name}: no matrices")
            continue
        cx, cy = record["principal_point_px"]
        if (abs(K[0][0] - record["fx_px"]) > 1e-9 or abs(K[1][1] - record["fy_px"]) > 1e-9
                or abs(K[0][2] - cx) > 1e-9 or abs(K[1][2] - cy) > 1e-9
                or K[2] != [0.0, 0.0, 1.0] or K[0][1] != 0.0 or K[1][0] != 0.0):
            bad.append(f"{name}: intrinsic_matrix is not [[fx,0,cx],[0,fy,cy],[0,0,1]]")
        axes = camera_axes(record["quaternion_wxyz"])
        aircraft = record["aircraft"]
        points = [(aircraft["north_m"], aircraft["east_m"], aircraft["alt_m"])] + landmarks
        for point in points:
            expected = to_pixel(record, to_camera(record, point, axes))
            via_matrix = project_with_matrix(P, point)
            if (expected is None) != (via_matrix is None):
                bad.append(f"{name}: matrix and parameters disagree on "
                           f"whether a point is in front of the camera")
                break
            if expected is None:
                continue
            compared += 1
            err = max(abs(expected[0] - via_matrix[0]), abs(expected[1] - via_matrix[1]))
            worst = max(worst, err)
            if err > PROJECTION_MATRIX_TOL_PX:
                bad.append(f"{name}: matrix projects {err:.4f} px from the parameters")
                break
    if bad:
        return Check("projection_matrix", FAIL,
                     f"{len(bad)} frame(s): " + "; ".join(bad[:4]))
    return Check("projection_matrix", PASS,
                 f"{compared} projections through P agree with the recorded "
                 f"parameters to {worst:.2e} px (tol {PROJECTION_MATRIX_TOL_PX} px)")


def verify_json_schema(manifest: Dict) -> Check:
    """The manifest against the published JSON Schema for its version
    (docs/schemas/capture_manifest.v<N>.schema.json): the contract a
    consumer validates against before parsing. Any violation fails,
    by path."""
    from .manifest import MANIFEST_VERSION, SUPPORTED_MANIFEST_VERSIONS
    from .schema import SchemaError, schema_path, validate_manifest

    version = manifest.get("manifest_version")
    if (version in SUPPORTED_MANIFEST_VERSIONS and version != MANIFEST_VERSION
            and not schema_path(manifest).is_file()):
        # A supported older manifest with no published contract: there
        # is nothing to grade it against, and that is NOT a failure of
        # the manifest -- it is named, not counted as a pass.
        return Check("json_schema", NOT_RUN,
                     f"no schema is published for manifest version "
                     f"{version} (the current version is {MANIFEST_VERSION})")
    try:
        problems = validate_manifest(manifest)
    except SchemaError as exc:
        return Check("json_schema", FAIL, str(exc))
    if problems:
        return Check("json_schema", FAIL,
                     f"{len(problems)} violation(s) of {schema_path(manifest).name}: "
                     + "; ".join(problems[:4]))
    return Check("json_schema", PASS,
                 f"valid against {schema_path(manifest).name}")


APPLIED_POSE_TOL_M = 0.10       # FlightSimCameraDirector::PositionToleranceCm
APPLIED_POSE_TOL_DEG = 0.05     # FlightSimCameraDirector::RotationToleranceDeg


def verify_applied_pose(manifest: Dict, run_dir=None) -> Check:
    """The pose the ENGINE reports applying, frame by frame, against the
    pose the manifest solved. The commandlet writes
    ``camera_applied_{north,east,alt}_m`` and ``_{yaw,pitch,roll}_deg``
    into each camera's render.json for exactly this comparison; the
    director already aborts a render past the same tolerances, and
    this check is the Python side that reads what it wrote, so a host
    that silently recomputed a pose could not pass. NOT RUN where no
    render.json carries applied poses."""
    if run_dir is None:
        return Check("applied_pose", NOT_RUN, "no run directory")
    frames_dir = Path(run_dir) / "frames"
    applied: Dict[str, Dict[str, Dict]] = {}
    if frames_dir.is_dir():
        for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
            path = camera_dir / "render.json"
            if not path.is_file():
                continue
            try:
                records = json.loads(path.read_text(encoding="utf-8")).get("frame_records") or []
            except (OSError, ValueError):
                continue
            per_frame = {str(r.get("frame")): r for r in records
                         if isinstance(r, dict) and "camera_applied_north_m" in r}
            if per_frame:
                applied[camera_dir.name] = per_frame
    if not applied:
        return Check("applied_pose", NOT_RUN,
                     "no render.json records the applied camera pose "
                     "(no render, or an older build)")
    bad = []
    counted = 0
    worst_m = worst_deg = 0.0
    for record in manifest.get("frames", []):
        camera = str(record["camera_id"])
        if camera not in applied:
            continue
        name = Path(str(record["file"])).name
        engine = applied[camera].get(name)
        if engine is None:
            bad.append(f"{camera}/{name}: the engine recorded no applied pose")
            continue
        counted += 1
        dist = math.dist(
            (float(engine["camera_applied_north_m"]),
             float(engine["camera_applied_east_m"]),
             float(engine["camera_applied_alt_m"])),
            (float(record["position_north_m"]), float(record["position_east_m"]),
             float(record["position_alt_m"])))
        angles = max(
            abs((float(engine[f"camera_applied_{axis}_deg"]) - float(record[f"{axis}_deg"])
                 + 180.0) % 360.0 - 180.0)
            for axis in ("yaw", "pitch", "roll"))
        worst_m = max(worst_m, dist)
        worst_deg = max(worst_deg, angles)
        if dist > APPLIED_POSE_TOL_M or angles > APPLIED_POSE_TOL_DEG:
            bad.append(f"{camera}/{name}: applied pose off by {dist:.3f} m / "
                       f"{angles:.3f} deg")
    if bad:
        return Check("applied_pose", FAIL,
                     f"{len(bad)} frame(s) were not rendered from the solved "
                     f"pose: " + "; ".join(bad[:4]))
    return Check("applied_pose", PASS,
                 f"{counted} frames: the engine applied the solved pose to "
                 f"{worst_m:.4f} m / {worst_deg:.4f} deg (tol "
                 f"{APPLIED_POSE_TOL_M} m / {APPLIED_POSE_TOL_DEG} deg)")


def verify_run(run_dir, other_run_dir=None) -> VerificationReport:
    """The pass/fail summary over a run directory (CLI: flightsim.verify).

    Every check runs or says why it did not. Temporal alignment needs a
    second capture of the same simulation; landmark reprojection and
    two-view triangulation need rendered frames. None of the three is
    counted as a pass when its reference is absent.
    """
    from .manifest import read_capture_manifest

    report = VerificationReport()
    path = Path(run_dir) / "capture_manifest.json"
    if not path.is_file():
        report.add("manifest_present", False,
                   f"{path} does not exist; nothing to verify")
        return report
    try:
        manifest = read_capture_manifest(path)
    except ValueError as exc:
        report.add("manifest_version", False, str(exc))
        return report
    report.add("manifest_version", True,
               f"manifest_version {manifest['manifest_version']}, "
               f"spec {manifest['spec_digest'][:16]}")

    finite = True
    for record in manifest.get("frames", []):
        for key in ("t_s", "position_north_m", "position_east_m",
                    "position_alt_m", "fx_px", "fy_px"):
            if not math.isfinite(record[key]):
                finite = False
    report.add("fields_finite", finite,
               f"{len(manifest.get('frames', []))} frame records checked")

    report.checks.append(verify_json_schema(manifest))
    report.checks.append(verify_intrinsics(manifest))
    report.checks.append(verify_projection_matrix(manifest))
    report.checks.append(verify_pose_matches_spec(manifest))
    report.checks.append(verify_geometry(manifest))
    report.checks.append(verify_landmark_reprojection(manifest, run_dir))
    report.checks.append(verify_triangulation(manifest, run_dir))
    report.checks.append(verify_counts(manifest))
    report.checks.append(verify_aircraft_consistency(manifest))
    report.checks.append(verify_flight_agreement(manifest, run_dir))
    report.checks.append(verify_host_determinism(run_dir))
    report.checks.append(verify_capture_times(manifest, run_dir))
    report.checks.append(verify_labels(manifest))
    report.checks.append(verify_keypoints_in_box(manifest))
    report.checks.append(verify_drawn_airframe(manifest, run_dir))
    report.checks.append(verify_label_files(manifest, run_dir))
    report.checks.append(verify_mask_containment(manifest, run_dir))
    report.checks.append(verify_depth_range(manifest, run_dir))
    # Phase 2, package D (contracts §4): the annotation gates, in the
    # page's order, after the version-5 label checks they supersede.
    other = None
    if other_run_dir is not None:
        other = read_capture_manifest(Path(other_run_dir) / "capture_manifest.json")
    report.checks.append(verify_mask_integers_only(manifest, run_dir))
    report.checks.append(verify_mask_vs_geometry(manifest, run_dir))
    report.checks.append(verify_box_vs_mask(manifest, run_dir))
    report.checks.append(verify_depth_vs_geometry(manifest, run_dir))
    report.checks.append(verify_visibility_vs_scene(manifest, run_dir))
    report.checks.append(verify_identity_stable(manifest, run_dir, other))
    report.checks.append(verify_applied_intrinsics(manifest, run_dir))
    report.checks.append(verify_sensor_undistortion(manifest))
    report.checks.append(verify_sensor_files(manifest, run_dir))
    report.checks.append(verify_frame_integrity(manifest, run_dir))
    report.checks.append(verify_applied_pose(manifest, run_dir))

    if other is not None:
        report.checks.append(verify_alignment(manifest, other))
    else:
        report.checks.append(Check(
            "temporal_alignment", NOT_RUN,
            "needs a second capture of the SAME simulation with a "
            "different camera set: run flightsim.capture again with "
            "other cameras and pass --against <that run dir>"))
    return report


#: Where a run keeps its last verification (written by flightsim.verify
#: and by the batch runner; read by the dataset export, which refuses a
#: run without one or with a failed check).
VERIFICATION_FILE = "verification.json"


def write_verification(report: VerificationReport, run_dir) -> Path:
    """Write the verdict atomically: a temporary file in the same
    directory, then ``os.replace``. Campaign workers (package G) verify
    runs in parallel while the campaign process reads the verdicts; a
    reader must see the previous complete file or the new one, never
    half of a JSON document (NEXT.md gotcha 30)."""
    import json
    import os

    path = Path(run_dir) / VERIFICATION_FILE
    staged = path.with_name(f".{VERIFICATION_FILE}.{os.getpid()}.tmp")
    staged.write_text(json.dumps(report.to_dict(), indent=1), encoding="utf-8")
    os.replace(staged, path)
    return path
