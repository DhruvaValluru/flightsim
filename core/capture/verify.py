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

import functools
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
        # Two kinds of NOT RUN, told apart on the page: a check whose
        # independent reference is absent (an engine pass, a second run)
        # and a version-5 check that a successor replaced on this
        # manifest. The second is waiting for nothing, so it is neither
        # listed with the first nor counted in "not run"; the status
        # word and verification.json's counts are unchanged.
        superseded = [c.name for c in self.checks if is_superseded(c)]
        skipped = [c.name for c in self.checks
                   if c.status == NOT_RUN and not is_superseded(c)]
        lines.append(f"verification {'PASSED' if self.ok else 'FAILED'} "
                     f"({passed} passed, {failed} failed, "
                     f"{len(skipped)} not run"
                     + (f", {len(superseded)} superseded" if superseded else "")
                     + ")")
        if skipped:
            lines.append("  NOT RUN (no independent reference available "
                         "for these; they are NOT counted as passes): "
                         + ", ".join(skipped))
        if superseded:
            lines.append("  SUPERSEDED on this manifest (each names the check "
                         "that replaced it above; not counted as passes, and "
                         "not waiting for any evidence): "
                         + ", ".join(superseded))
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
        # S2: a materialised stereo right camera is placed by its rig, not
        # by its preset: disparity_vs_right_depth grades it against the left.
        if not spec or _spec_value(spec, "position_mode") == "stereo_right":
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


#: The mesh manifest version from which the mesh origin the render
#: commandlet attaches the mesh at is MEASURED from the mesh's own
#: vertices (nose keypoint in x, main-gear contact in z; contracts
#: §0.1). Version 2 placed it by the staged FDM's VRP rule -- 3.9 m off
#: on the B747, 19.3 m on the A320 -- and version 1 recorded no origin
#: at all (attached at the structural datum, 33.7 m off on the B747).
#: Named here, not imported from the producer (assets_pipeline/convert.py
#: MESH_MANIFEST_VERSION says the same number).
DRAWN_MESH_MIN_MANIFEST_VERSION = 3
#: What a measured origin's basis string starts with (the converter's
#: MESH_ORIGIN_BASIS_MEASURED* strings, echoed by the commandlet under
#: ``drawn.origin_basis``); a VRP-rule basis never does.
DRAWN_MESH_ORIGIN_BASIS_PREFIX = "measured from vertices"


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
      ``DRAWN_MESH_MIN_MANIFEST_VERSION``: version 1 carried no origin,
      so the mesh was attached at the datum and every mask is offset
      from its label by the VRP; version 2 placed it by the VRP rule
      that is the wrong FDM for two of three airframes (contracts §0.1);
    * FAIL when the recorded ``origin_basis`` does not start with
      ``DRAWN_MESH_ORIGIN_BASIS_PREFIX`` -- a manifest that says version
      3 but places the mesh by a rule is graded by what it says it did;
    * PASS when the mesh was drawn at a measured origin;
    * NOT RUN with no render.json, or one that predates ``drawn``.

    The failure name is ``aircraft.placeholder_drawn`` for every clause
    (contracts §4): the pictures show the airframe somewhere other than
    where the labels describe it.
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
            if isinstance(version, (int, float)) and version >= 2:
                problems.append(
                    f"{camera}: the mesh was drawn from manifest version "
                    f"{version!r} (< {DRAWN_MESH_MIN_MANIFEST_VERSION}), which "
                    f"placed the mesh origin by the staged FDM's VRP rule "
                    f"instead of measuring it from the mesh's vertices, so "
                    f"every mask is offset from its label -- 3.9 m on the "
                    f"B747, 19.3 m on the A320; re-run "
                    f"assets_pipeline/convert.py and render again")
            else:
                problems.append(
                    f"{camera}: the mesh was drawn from manifest version "
                    f"{version!r} (< {DRAWN_MESH_MIN_MANIFEST_VERSION}), which "
                    f"records no mesh origin, so it was attached at the actor "
                    f"origin -- the JSBSim structural datum -- and every mask "
                    f"is offset from its label by the FDM's VRP (33.7 m on "
                    f"the B747); re-run assets_pipeline/convert.py and render "
                    f"again")
            continue
        basis = drawn.get("origin_basis")
        if not (isinstance(basis, str)
                and basis.startswith(DRAWN_MESH_ORIGIN_BASIS_PREFIX)):
            problems.append(
                f"{camera}: the mesh was drawn about an origin whose recorded "
                f"basis is {basis!r}, not one measured from the mesh's "
                f"vertices ('{DRAWN_MESH_ORIGIN_BASIS_PREFIX}...'): a rule-"
                f"placed origin puts the mesh 3.9 m (B747) to 19.3 m (A320) "
                f"from its label; re-run assets_pipeline/convert.py and "
                f"render again")
            continue
        origin = drawn.get("mesh_origin_actor_cm")
        origin_text = (", ".join(f"{float(v):.1f}" for v in origin)
                       if isinstance(origin, list) and len(origin) == 3
                       else "?")
        notes.append(f"{camera}: mesh at ({origin_text}) cm in the actor "
                     f"frame, manifest version {int(version)}, origin "
                     f"{DRAWN_MESH_ORIGIN_BASIS_PREFIX}")
    if problems:
        return Check("drawn_airframe", FAIL,
                     f"{len(problems)} camera(s) drew something other than "
                     f"the airframe the labels describe, where they describe "
                     f"it: " + "; ".join(problems[:4]),
                     failure="aircraft.placeholder_drawn")
    return Check("drawn_airframe", PASS,
                 f"{len(recorded)} camera(s): " + "; ".join(notes[:4]))


class BundleFileError(Exception):
    """A file the render record declares could not be read from the run
    directory -- missing, truncated, not an image. The message is the
    plain sentence the check reports; the failure name is
    ``annotation.files`` (the same finding label_files makes)."""


def _unreadable(path, exc: OSError) -> str:
    path = Path(path)
    where = f"{path.parent.name}/{path.name}"
    if isinstance(exc, FileNotFoundError):
        return (f"{where} is missing: the render record declares it, but the "
                f"run directory does not hold it")
    return f"{where} could not be read as the record declares it ({exc})"


def _reads_the_bundle(check):
    """A check that opens the files the render record declares.

    Measured before this guard: deleting one declared mask from a run
    ended ``flightsim.verify`` in a FileNotFoundError traceback, exit 1
    for the wrong reason, no ``refused by name`` line and no
    verification.json -- a run with no verdict at all. A file the
    record names and the disk does not hold is now what label_files
    already calls it, ``annotation.files``, on every check that would
    have opened it, naming the file in a sentence.
    """
    name = check.__name__[len("verify_"):]

    @functools.wraps(check)
    def guarded(*args, **kwargs) -> Check:
        try:
            return check(*args, **kwargs)
        except BundleFileError as exc:
            return Check(name, FAIL, str(exc), failure=FAIL_FILES)
    return guarded


def _read_gray_png(path):
    """A mask or depth PNG as a 2-D integer array, via Pillow; None
    without Pillow; :class:`BundleFileError` when the file cannot be
    read."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:            # pragma: no cover - Pillow is in the venv
        return None
    try:
        with Image.open(path) as image:
            return np.array(image)
    except OSError as exc:
        raise BundleFileError(_unreadable(path, exc)) from exc


#: What the detail of a version-5 check starts with on a manifest whose
#: objects[] hands its question to a successor; the summary reads it to
#: list such checks apart from the ones waiting for evidence.
SUPERSEDED_MARK = "superseded for manifest"


def is_superseded(check: Check) -> bool:
    """NOT RUN because a successor check took over on this manifest --
    not because any evidence is missing."""
    return check.status == NOT_RUN and check.detail.startswith(SUPERSEDED_MARK)


@_reads_the_bundle
def verify_mask_containment(manifest: Dict, run_dir=None) -> Check:
    """The engine's aircraft mask lies inside the label's 2-D box.

    The version-5 check: one instance id, one box. On a manifest that
    declares ``objects[]`` (version 6) the ID image carries every
    object's integer and box_vs_mask grades each against its projected
    hull, so this reports NOT RUN naming its successor rather than
    grading the primary twice."""
    if _declared_objects(manifest):
        return Check("mask_containment", NOT_RUN,
                     f"{SUPERSEDED_MARK} {manifest.get('manifest_version')} "
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


@_reads_the_bundle
def verify_depth_range(manifest: Dict, run_dir=None) -> Check:
    """Depth at the engine's aircraft-mask pixels lies within the 3-D
    box's depth span.

    The version-5 check. On a manifest that declares ``objects[]``
    (version 6) depth_vs_geometry grades every aircraft object's depth
    against its projected hull, keypoints and record, so this reports
    NOT RUN naming its successor."""
    if _declared_objects(manifest):
        return Check("depth_range", NOT_RUN,
                     f"{SUPERSEDED_MARK} {manifest.get('manifest_version')} "
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
        try:
            raw = np.fromfile(path, dtype="<f4")
        except OSError as exc:
            raise BundleFileError(_unreadable(path, exc)) from exc
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

@_reads_the_bundle
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


@_reads_the_bundle
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


@_reads_the_bundle
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
    module's box of the same visible pixels, to a pixel -- and a null
    record while the ID image holds pixels of the object is failed by
    name, not skipped (a record the bundle was never attached to). The
    PASS sentence says how many records were compared. Supersedes
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
    records = 0
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
            own_record = _record_object(record, int_id)
            recorded = (own_record or {}).get("bbox_2d_tight")
            if visible.any():
                # The ID image holds pixels of this object, so the record
                # owes a tight box measured from them. A null here is a
                # record the bundle was never attached to (the producer
                # leaves the key null until attach_engine_labels runs);
                # a null cannot be "graded to a pixel" and is failed by
                # name rather than skipped.
                ys, xs = np.nonzero(visible)
                own = (float(xs.min()), float(ys.min()), float(xs.max()) + 1.0,
                       float(ys.max()) + 1.0)
                if own_record is None:
                    return Check("box_vs_mask", FAIL,
                                 f"{where}: the ID image holds {int(xs.size)} "
                                 f"pixels of it but the frame's labels.objects[] "
                                 f"has no record for it",
                                 failure=FAIL_BOX_MISMATCH)
                if not (isinstance(recorded, (list, tuple)) and len(recorded) == 4):
                    return Check("box_vs_mask", FAIL,
                                 f"{where}: the record's bbox_2d_tight is "
                                 f"{recorded!r} while the ID image holds "
                                 f"{int(xs.size)} pixels of it (box "
                                 f"{[round(v, 1) for v in own]}); the record "
                                 f"was never completed from the bundle",
                                 failure=FAIL_BOX_MISMATCH)
                gap = max(abs(float(a) - b) for a, b in zip(recorded, own))
                if gap > 0.5:
                    return Check("box_vs_mask", FAIL,
                                 f"{where}: the record's bbox_2d_tight "
                                 f"{[round(float(v), 1) for v in recorded]} is not "
                                 f"the box of its own visible pixels "
                                 f"{[round(v, 1) for v in own]} ({gap:.1f} px off)",
                                 failure=FAIL_BOX_MISMATCH)
                records += 1
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
                 f"{BOX_IOU_MIN_SMALL} at >= {BOX_IOU_MIN_PX:.0f} px); {records} "
                 f"records' bbox_2d_tight re-counted from the ID image to a pixel"
                 + (f"; {not_claimed} under {BOX_IOU_MIN_PX:.0f} px not claimed"
                    if not_claimed else ""))


@_reads_the_bundle
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
    pixels, and agree to DEPTH_RECORD_TOL_M -- a null record under a
    mask with pixels is failed by name, not skipped. The median against
    the projected CG depth is reported. Supersedes depth_range for manifest
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
            recorded = _record_object(record, int_id)
            if recorded is None:
                return Check("depth_vs_geometry", FAIL,
                             f"{where}: the depth file holds {under.size} pixels "
                             f"under its mask but the frame's labels.objects[] has "
                             f"no record for it",
                             failure=FAIL_DEPTH_RANGE)
            for key, own in (("depth_min_m", d_min), ("depth_median_m", d_median)):
                value = recorded.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    # Every mask pixel has a finite depth (checked above),
                    # so the record owes the number; a null was never
                    # attached from the bundle and is not "the same
                    # pixels to 0.05 m" -- failed by name, not skipped.
                    return Check("depth_vs_geometry", FAIL,
                                 f"{where}: the record's {key} is {value!r} while "
                                 f"the depth file holds {under.size} finite pixels "
                                 f"under its mask ({own:.2f} m); the record was "
                                 f"never completed from the bundle",
                                 failure=FAIL_DEPTH_RANGE)
                if abs(float(value) - own) > DEPTH_RECORD_TOL_M:
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
                 f"differs by at most {worst_median[0]:.1f} m at {worst_median[1] or 'none'}; "
                 f"{graded} records' depth_min_m / depth_median_m are the same pixels "
                 f"to {DEPTH_RECORD_TOL_M:g} m")


@_reads_the_bundle
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
    and every occluder named is a declared object (a null recorded
    ``visible_fraction`` under an alone pass with pixels is failed by
    name, not skipped). An object's own depth is its projected CG depth (the geometry, independent of the
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
            recorded = _record_object(record, int_id)
            if recorded is None:
                return fail(f"{where}: an alone pass is declared for it but the "
                            f"frame's labels.objects[] has no record for it")
            rec_fraction = recorded.get("visible_fraction")
            if own_fraction is not None:
                if (not isinstance(rec_fraction, (int, float))
                        or isinstance(rec_fraction, bool)):
                    # The alone pass holds footprint pixels, so the record
                    # owes the fraction; a null was never attached from
                    # the bundle and is failed by name, not skipped.
                    return fail(f"{where}: the manifest's visible_fraction is "
                                f"{rec_fraction!r} while the alone pass holds "
                                f"{n_alone} footprint pixels ({n_vis} visible, "
                                f"{own_fraction:.4f}); the record was never "
                                f"completed from the bundle")
                if abs(float(rec_fraction) - own_fraction) > VISIBILITY_RECORD_TOL:
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
                 f"object, and {graded} records' fractions and occluders re-counted "
                 f"from the files")


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
    the engine's echo is half the evidence -- and a render.json that
    declares label records with no root ``objects[]`` echo is no echo:
    NOT RUN when no camera of the run carries one, FAIL when another
    camera's does (the same build wrote both). Such a camera never
    counts toward the sentence that says the engine echoed the list.
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
    unechoed = []
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
            echoed = mapping(payload.get("objects"))
            if not echoed:
                # Label records with no root objects[] echo: the engine
                # did not say which integers it was told, so this camera
                # is evidence of nothing and never counts toward the
                # PASS sentence that says the engine echoed the list.
                unechoed.append(camera_dir.name)
                continue
            cameras.append(camera_dir.name)
            for key, value in echoed.items():
                if reference.get(key) != value:
                    return fail(f"{camera_dir.name}/render.json: the engine wrote "
                                f"{key} as {value} where objects[] says "
                                f"{reference.get(key)} -- the stencils were not "
                                f"the card's")
            for value in sorted(set(reference.values()) - set(echoed.values())):
                return fail(f"{camera_dir.name}/render.json: objects[] declares "
                            f"int_id {value} but the engine's echo does not "
                            f"name it")
    if unechoed and cameras:
        return fail(f"{', '.join(unechoed)}: render.json declares label records "
                    f"but carries no root objects[] echo, while {', '.join(cameras)} "
                    f"carries one -- the engine did not say which integers it "
                    f"stencilled for that camera")
    if not cameras:
        why = (f"{', '.join(unechoed)}: render.json declares label records but "
               f"carries no root objects[] echo (an older engine build, or the "
               f"key was dropped)" if unechoed else
               "no render.json echoes the ids the engine wrote (no engine pass)")
        return Check("identity_stable", NOT_RUN,
                     f"{frames} frames agree with objects[] {reference}, but {why}; "
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
    carries the applied intrinsics; FAIL by name when one camera's
    render.json carries them and another's frame records carry none
    (the same build wrote both); a camera with no render at all is
    named in the PASS sentence as not graded.
    """
    applied: Dict[str, Dict[str, Dict]] = {}
    rendered = set()
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
            records = [r for r in _render_frame_records(payload) if isinstance(r, dict)]
            if records:
                rendered.add(camera_dir.name)
            per_frame = {str(r.get("frame")): r for r in records
                         if "applied_fov_deg" in r}
            if per_frame:
                applied[camera_dir.name] = per_frame
    if not applied:
        return Check("applied_intrinsics", NOT_RUN,
                     "no render.json records the applied intrinsics "
                     "(applied_fov_deg et al.; no render, or an older build)")
    # A camera of this run whose render.json holds frame records but not
    # one applied lens, while another camera's does: the same build wrote
    # both, so the omission is the per-frame clause below one level up
    # -- failed by name, not skipped. A camera with no render at all is
    # named as not graded in the PASS sentence.
    manifest_cameras = sorted({str(r["camera_id"]) for r in manifest.get("frames", [])})
    silent = [c for c in manifest_cameras if c in rendered and c not in applied]
    if silent:
        return Check("applied_intrinsics", FAIL,
                     f"{', '.join(silent)}: the engine recorded no applied intrinsics "
                     f"for this camera while it did for {sorted(applied)}, so its "
                     f"frames cannot be shown rendered at the record's lens",
                     failure=FAIL_INTRINSICS)
    unrendered = [c for c in manifest_cameras if c not in applied]
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
                 f"{counted} frames of {sorted(applied)} rendered at the record's "
                 f"lens and picture size; worst field-of-view gap {worst_deg:.4f} "
                 f"deg (tol {APPLIED_FOV_TOL_DEG} deg)"
                 + (f"; {unrendered} not rendered, not graded" if unrendered else ""))


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


# -- I6 (gap S3): the ground-truth passes -------------------------------------
#
# The commandlet's -passes=normal,velocity,albedo writes frame_NNNN_normal.png
# (16-bit, (n * 0.5 + 0.5) * 65535, n in the scene frame north/east/up),
# frame_NNNN_flow.f32 (little-endian float32 (dx, dy) pixels, +x right, +y
# down, previous captured frame to this one; the first frame zeros) and
# frame_NNNN_albedo.png (16-bit linear base colour), named on the render.json
# record as normal_png / flow_f32 / albedo_png. Each check below reads the
# file with this module's OWN reader and grades it against something the
# engine did not write it from: the normals against the depth file through
# the record's intrinsics, the flow against the keypoints' motion through the
# manifest's states and poses, the albedo against the beauty picture. NOT RUN
# without the file it needs; never a pass on absence.

#: Median angle allowed between the normal the depth implies and the normal
#: the pass wrote, over smooth-depth pixels.
NORMAL_ANGLE_TOL_DEG = 10.0
#: A pixel is "smooth" when its depth and its four neighbours' are finite
#: and no neighbour differs by more than this fraction of the depth: a
#: silhouette edge or the sky is not a surface to differentiate across.
#: 0.02 keeps a plane up to about 87 deg off the view ray at fx = 1000 px.
SMOOTH_DEPTH_FRACTION = 0.02
#: Fewer smooth pixels than this and the frame is not graded.
NORMAL_MIN_SMOOTH_PIXELS = 100
#: Median pixel error allowed between the flow at a keypoint's pixel and
#: the keypoint's projected displacement from the previous frame.
FLOW_TOL_PX = 2.0
#: Fewer keypoints inside the ID image than this, across the run, and the
#: flow is not graded.
FLOW_MIN_KEYPOINTS = 3
#: The albedo must differ from the beauty picture (both as 8-bit) by more
#: than ALBEDO_DIFFERENT_COUNTS on at least this fraction of pixels.
ALBEDO_MIN_DIFFERENT_FRACTION = 0.01
ALBEDO_DIFFERENT_COUNTS = 2
PASS_PNG16_MAX = 65535.0

FAIL_NORMALS = "annotation.normals"
FAIL_FLOW = "annotation.flow"
FAIL_ALBEDO = "annotation.albedo"


def _read_rgb16(path):
    """A 16-bit RGB(A) PNG as an (h, w, 3) uint16 array through rasterio
    (own reader: Pillow hands a 16-bit RGB PNG back as 8-bit).
    :class:`BundleFileError` when it cannot be read; a string when it is
    not the 16-bit three-channel file the contract declares."""
    import numpy as np
    try:
        import rasterio
        from rasterio.errors import RasterioIOError
    except ImportError:            # pragma: no cover - rasterio is in the venv
        return "rasterio unavailable"
    path = Path(path)
    if not path.is_file():
        raise BundleFileError(_unreadable(path, FileNotFoundError(str(path))))
    try:
        with rasterio.open(path) as dataset:
            if dataset.count < 3:
                return f"{path.name}: {dataset.count} channel(s), not three"
            if dataset.dtypes[0] != "uint16":
                return f"{path.name}: {dataset.dtypes[0]} samples, not 16-bit"
            planes = dataset.read((1, 2, 3))
    except (RasterioIOError, OSError) as exc:
        raise BundleFileError(_unreadable(path, OSError(str(exc)))) from exc
    return np.ascontiguousarray(np.transpose(planes, (1, 2, 0)))


def _read_flow(path, width: int, height: int):
    """``frame_NNNN_flow.f32`` as (h, w, 2) float64 pixels; a string when
    the size is not width*height*2 float32 values."""
    import numpy as np

    path = Path(path)
    try:
        raw = np.fromfile(path, dtype="<f4")
    except OSError as exc:
        raise BundleFileError(_unreadable(path, exc)) from exc
    if raw.size != width * height * 2:
        return (f"{path.name}: {raw.size} float32 values for a {width}x{height} "
                f"flow ({width * height * 2} expected)")
    return raw.reshape(height, width, 2).astype("float64")


def _pass_frames(manifest: Dict, run_dir, key: str):
    """Yield (record, camera, name, engine, folder, file) for every bundle
    frame whose render.json record declares the pass file under ``key``."""
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        file = engine.get(key)
        if isinstance(file, str) and file:
            yield record, camera, name, engine, folder, file


def _no_pass_reason(word: str, key: str) -> str:
    return (f"no render.json frame record declares {key} (no -passes={word}, or no "
            f"engine pass at all): render on Windows with -labels -passes={word} to "
            f"exercise this")


@_reads_the_bundle
def verify_normals_vs_depth(manifest: Dict, run_dir=None) -> Check:
    """The normal pass against the depth file.

    Per frame with a normal image and a float32 depth: the camera-space
    surface normal at every interior pixel from the depth by central
    differences of the back-projected points (the record's fx, fy,
    principal point; x right, y down, z forward), oriented toward the
    camera; the pass's scene-frame normal rotated into the camera by the
    record's quaternion through this module's own axes; the angle between
    them over SMOOTH pixels (finite depth at the pixel and its four
    neighbours, no neighbour more than SMOOTH_DEPTH_FRACTION of the depth
    away). The median over those pixels must be under
    NORMAL_ANGLE_TOL_DEG; a normal image rotated by more than that fails
    by name (annotation.normals). NOT RUN without the normal image or the
    float32 depth (the 16-bit PNG at 0.1 m quantises the differences).
    NOT claimed: silhouette edges, the sky, and pixels the depth resolves
    at under the smoothness rule -- a surface at grazing incidence.
    """
    frames = list(_pass_frames(manifest, run_dir, "normal_png"))
    if not frames:
        return Check("normals_vs_depth", NOT_RUN, _no_pass_reason("normal", "normal_png"))
    import numpy as np

    graded = 0
    skipped = []
    worst = (0.0, "")
    for record, camera, name, engine, folder, file in frames:
        labels = engine["labels"]
        where = f"{camera}/{name}"
        if not labels.get("depth_f32"):
            return Check("normals_vs_depth", NOT_RUN,
                         f"{where}: the normals are graded against the float32 depth "
                         f"and the record declares none (the 16-bit PNG at its "
                         f"0.1 m step quantises the finite differences)")
        width, height = int(record["width_px"]), int(record["height_px"])
        depth = _read_depth_metres(folder, labels, width, height)
        if isinstance(depth, str):
            return Check("normals_vs_depth", FAIL, f"{where}: {depth}", failure=FAIL_NORMALS)
        stored = _read_rgb16(folder / file)
        if isinstance(stored, str):
            return Check("normals_vs_depth", FAIL, f"{where}: {stored}", failure=FAIL_NORMALS)
        if stored.shape[:2] != depth.shape:
            return Check("normals_vs_depth", FAIL,
                         f"{where}: the normal image is {stored.shape[1]}x{stored.shape[0]}, "
                         f"the depth {depth.shape[1]}x{depth.shape[0]}", failure=FAIL_NORMALS)
        # The pass's normal, decoded here: v / 65535 -> [0, 1] -> [-1, 1].
        n_scene = (stored.astype("float64") / PASS_PNG16_MAX - 0.5) * 2.0
        forward, right, up = axes_from_quat(record["quaternion_wxyz"])
        rows = np.array([right, [-c for c in up], forward], dtype="float64")   # x, y, z
        n_cam_pass = n_scene @ rows.T
        length = np.linalg.norm(n_cam_pass, axis=2)
        n_cam_pass = n_cam_pass / np.where(length > 1e-9, length, 1.0)[..., None]
        # The depth's normal: back-project, differentiate, cross, orient.
        fx, fy = float(record["fx_px"]), float(record["fy_px"])
        cx, cy = (float(c) for c in record["principal_point_px"])
        u = np.arange(width, dtype="float64")[None, :]
        v = np.arange(height, dtype="float64")[:, None]
        z = depth
        points = np.stack([(u - cx) / fx * z, (v - cy) / fy * z, z], axis=2)
        interior = (slice(1, -1), slice(1, -1))
        d_du = (points[1:-1, 2:] - points[1:-1, :-2]) * 0.5
        d_dv = (points[2:, 1:-1] - points[:-2, 1:-1]) * 0.5
        n_depth = np.cross(d_du, d_dv)
        length = np.linalg.norm(n_depth, axis=2)
        n_depth = n_depth / np.where(length > 1e-12, length, 1.0)[..., None]
        facing = np.einsum("ijk,ijk->ij", n_depth, points[interior])
        n_depth = np.where((facing > 0.0)[..., None], -n_depth, n_depth)
        centre = z[interior]
        finite = np.isfinite(centre)
        smooth = finite.copy()
        for neighbour in (z[1:-1, 2:], z[1:-1, :-2], z[2:, 1:-1], z[:-2, 1:-1]):
            with np.errstate(invalid="ignore"):
                near = np.isfinite(neighbour) & (
                    np.abs(neighbour - centre) <= SMOOTH_DEPTH_FRACTION * np.abs(centre))
            smooth &= near
        smooth &= length > 1e-12
        count = int(np.count_nonzero(smooth))
        if count < NORMAL_MIN_SMOOTH_PIXELS:
            skipped.append(f"{where} ({count} smooth pixels)")
            continue
        cosine = np.einsum("ijk,ijk->ij", n_depth, n_cam_pass[interior])
        angle = np.degrees(np.arccos(np.clip(cosine[smooth], -1.0, 1.0)))
        median = float(np.median(angle))
        if median > worst[0]:
            worst = (median, f"{where} ({count} smooth pixels)")
        if median > NORMAL_ANGLE_TOL_DEG:
            return Check("normals_vs_depth", FAIL,
                         f"{where}: the pass's normals sit a median {median:.1f} deg "
                         f"from the normals the depth implies over {count} smooth "
                         f"pixels (tolerance {NORMAL_ANGLE_TOL_DEG:g} deg): the normal "
                         f"image is not the surface the depth shows -- a wrong axis, "
                         f"frame or sign", failure=FAIL_NORMALS)
        graded += 1
    if graded == 0:
        return Check("normals_vs_depth", NOT_RUN,
                     f"no frame with at least {NORMAL_MIN_SMOOTH_PIXELS} smooth-depth "
                     f"pixels to differentiate ({'; '.join(skipped[:3]) or 'none'})")
    return Check("normals_vs_depth", PASS,
                 f"{graded} frames: the pass's normals agree with the depth's to a "
                 f"median of at most {worst[0]:.2f} deg at {worst[1]} (tolerance "
                 f"{NORMAL_ANGLE_TOL_DEG:g} deg, smooth pixels only)"
                 + (f"; not graded: {'; '.join(skipped[:3])}" if skipped else ""))


@_reads_the_bundle
def verify_flow_vs_motion(manifest: Dict, run_dir=None) -> Check:
    """The flow at the primary airframe's keypoints against their motion.

    Per camera, the labelled frames in time order; for every consecutive
    pair whose later frame declares a flow file: each keypoint of the
    airframe block placed by the two frames' aircraft states and
    projected through the two records with this module's own rotation
    and pinhole; the predicted displacement (u_now - u_prev, v_now -
    v_prev) against the flow sampled at the pixel containing (u_now,
    v_now), for keypoints inside the image whose pixel carries the
    primary's int_id in the ID image. The median |error| over all such
    keypoints in the run must be under FLOW_TOL_PX; a scaled or negated
    flow fails by name (annotation.flow). A frame flagged
    flow_first_frame must be all zeros. NOT RUN without a flow file, with
    one frame per camera, or with fewer than FLOW_MIN_KEYPOINTS keypoints
    inside the mask. NOT claimed: the flow between the two frames at a
    keypoint the airframe itself occludes (its pixel shows a nearer
    surface of the same rigid body; the tolerance absorbs the parallax
    at the ranges the datasets fly), and any pixel off the airframe.
    """
    objects = _declared_objects(manifest)
    if not objects:
        return Check("flow_vs_motion", NOT_RUN, _no_objects_reason(manifest))
    declared = _engine_label_records(run_dir)
    if not declared:
        return Check("flow_vs_motion", NOT_RUN, _no_bundle_reason())
    primary = None
    for entry in _aircraft_entries(objects):
        if entry.get("role") == "primary" or int(entry.get("int_id", 0)) == AIRCRAFT_INSTANCE_ID:
            primary = entry
    airframe = manifest.get("airframe")
    keypoints = [(str(kp["name"]), tuple(float(c) for c in kp["body_m"]))
                 for kp in ((airframe or {}).get("keypoints") or [])
                 if isinstance(kp, dict) and kp.get("name") and kp.get("body_m")]
    if primary is None or not keypoints:
        return Check("flow_vs_motion", NOT_RUN,
                     "the manifest names no primary airframe with keypoints to "
                     "predict a displacement for")
    primary_id = int(primary["int_id"])
    import numpy as np

    by_camera: Dict[str, List[Dict]] = {}
    for record in _labelled_frames(manifest):
        by_camera.setdefault(str(record["camera_id"]), []).append(record)
    any_flow = False
    pairs = 0
    first_frames = 0
    errors: List[Tuple[float, str]] = []
    for camera, records in by_camera.items():
        records.sort(key=lambda r: float(r["t_s"]))
        folder = Path(run_dir) / "frames" / camera
        prev: Optional[Dict] = None
        for record in records:
            name = Path(str(record["file"])).name
            engine = declared.get(camera, {}).get(name)
            file = (engine or {}).get("flow_f32")
            if not isinstance(file, str) or not file:
                prev = record
                continue
            any_flow = True
            where = f"{camera}/{name}"
            width, height = int(record["width_px"]), int(record["height_px"])
            flow = _read_flow(folder / file, width, height)
            if isinstance(flow, str):
                return Check("flow_vs_motion", FAIL, f"{where}: {flow}", failure=FAIL_FLOW)
            if engine.get("flow_first_frame") or prev is None:
                if np.any(flow != 0.0):
                    return Check("flow_vs_motion", FAIL,
                                 f"{where}: the record flags the first frame of the "
                                 f"camera (all zeros by contract) but the flow file "
                                 f"holds {int(np.count_nonzero(flow.any(axis=2)))} moving "
                                 f"pixels", failure=FAIL_FLOW)
                first_frames += 1
                prev = record
                continue
            labels = engine.get("labels") or {}
            mask = _read_gray_png(folder / labels["mask"]) if labels.get("mask") else None
            state_now, state_prev = record.get("aircraft"), prev.get("aircraft")
            if not isinstance(state_now, dict) or not isinstance(state_prev, dict):
                return Check("flow_vs_motion", NOT_RUN,
                             f"{where}: no aircraft state on the frame pair to move "
                             f"the keypoints by")
            axes_now = axes_from_quat(record["quaternion_wxyz"])
            axes_prev = axes_from_quat(prev["quaternion_wxyz"])
            for kp_name, body in keypoints:
                p_now = _pinhole(record, _camera_coords(
                    record, _body_point_enu(body, state_now), axes_now))
                p_prev = _pinhole(prev, _camera_coords(
                    prev, _body_point_enu(body, state_prev), axes_prev))
                if p_now is None or p_prev is None:
                    continue
                px, py = int(math.floor(p_now[0])), int(math.floor(p_now[1]))
                if not (0 <= px < width and 0 <= py < height):
                    continue
                if mask is not None and int(mask[py, px]) != primary_id:
                    continue
                du_pred = p_now[0] - p_prev[0]
                dv_pred = p_now[1] - p_prev[1]
                du, dv = float(flow[py, px, 0]), float(flow[py, px, 1])
                error = math.hypot(du - du_pred, dv - dv_pred)
                errors.append((error, f"{where} {kp_name} (flow {du:+.2f},{dv:+.2f} px, "
                                      f"predicted {du_pred:+.2f},{dv_pred:+.2f} px)"))
            pairs += 1
            prev = record
    if not any_flow:
        return Check("flow_vs_motion", NOT_RUN, _no_pass_reason("velocity", "flow_f32"))
    if pairs == 0:
        return Check("flow_vs_motion", NOT_RUN,
                     f"{first_frames} first frame(s) checked as zeros, but no camera "
                     f"has a second flow frame to grade motion on")
    if len(errors) < FLOW_MIN_KEYPOINTS:
        return Check("flow_vs_motion", NOT_RUN,
                     f"only {len(errors)} keypoint sample(s) fall inside the primary's "
                     f"ID image over {pairs} frame pair(s) (minimum {FLOW_MIN_KEYPOINTS})")
    values = np.array([e for e, _ in errors])
    median = float(np.median(values))
    worst = max(errors, key=lambda e: e[0])
    if median > FLOW_TOL_PX:
        return Check("flow_vs_motion", FAIL,
                     f"the flow at the primary's keypoints is a median {median:.2f} px "
                     f"from their projected displacement over {len(errors)} samples in "
                     f"{pairs} frame pair(s) (tolerance {FLOW_TOL_PX:g} px); worst "
                     f"{worst[0]:.2f} px at {worst[1]} -- a scaled, negated or "
                     f"mis-based motion vector", failure=FAIL_FLOW)
    return Check("flow_vs_motion", PASS,
                 f"{len(errors)} keypoint samples over {pairs} frame pair(s): the flow "
                 f"is a median {median:.2f} px from the keypoints' projected displacement "
                 f"(tolerance {FLOW_TOL_PX:g} px), worst {worst[0]:.2f} px at {worst[1]}; "
                 f"{first_frames} first frame(s) all zeros as declared")


@_reads_the_bundle
def verify_albedo_range(manifest: Dict, run_dir=None) -> Check:
    """The albedo pass: present, 16-bit three-channel at the record's
    size, every value finite and in [0, 1] as read, and NOT the beauty
    picture -- as 8-bit the two must differ by more than
    ALBEDO_DIFFERENT_COUNTS on at least ALBEDO_MIN_DIFFERENT_FRACTION of
    pixels (a base colour that equals the lit, tone-mapped frame was
    not a base colour pass). The mean albedo over sky pixels (depth
    +inf) is reported, not graded. Sun invariance is Gate 6's albedo
    clause on Windows (experiments/gate6_visual.py), not this check.
    NOT RUN without an albedo file.
    """
    frames = list(_pass_frames(manifest, run_dir, "albedo_png"))
    if not frames:
        return Check("albedo_range", NOT_RUN, _no_pass_reason("albedo", "albedo_png"))
    import numpy as np

    graded = 0
    least = (1.0, "")
    sky_means: List[float] = []
    for record, camera, name, engine, folder, file in frames:
        where = f"{camera}/{name}"
        width, height = int(record["width_px"]), int(record["height_px"])
        stored = _read_rgb16(folder / file)
        if isinstance(stored, str):
            return Check("albedo_range", FAIL, f"{where}: {stored}", failure=FAIL_ALBEDO)
        if stored.shape[:2] != (height, width):
            return Check("albedo_range", FAIL,
                         f"{where}: the albedo image is {stored.shape[1]}x{stored.shape[0]}, "
                         f"the record says {width}x{height}", failure=FAIL_ALBEDO)
        values = stored.astype("float64") / PASS_PNG16_MAX
        if not np.all(np.isfinite(values)) or float(values.min()) < 0.0 or float(values.max()) > 1.0:
            return Check("albedo_range", FAIL,
                         f"{where}: albedo values outside [0, 1] or not finite as read",
                         failure=FAIL_ALBEDO)
        beauty = _read_gray_png(folder / str(engine.get("frame") or name))
        if beauty is None:
            return Check("albedo_range", NOT_RUN, "Pillow unavailable")
        if beauty.ndim != 3 or beauty.shape[:2] != (height, width):
            return Check("albedo_range", FAIL,
                         f"{where}: the beauty frame is not an RGB image of {width}x{height}",
                         failure=FAIL_ALBEDO)
        albedo8 = np.rint(values * 255.0)
        beauty8 = beauty[:, :, :3].astype("float64")
        different = np.any(np.abs(albedo8 - beauty8) > ALBEDO_DIFFERENT_COUNTS, axis=2)
        fraction = float(different.mean())
        if fraction < least[0]:
            least = (fraction, where)
        if fraction < ALBEDO_MIN_DIFFERENT_FRACTION:
            return Check("albedo_range", FAIL,
                         f"{where}: the albedo differs from the beauty picture on only "
                         f"{fraction * 100:.2f} % of pixels (minimum "
                         f"{ALBEDO_MIN_DIFFERENT_FRACTION * 100:g} %): a base colour that "
                         f"equals the lit, tone-mapped frame was not a base colour pass",
                         failure=FAIL_ALBEDO)
        labels = engine.get("labels") or {}
        if labels.get("depth_f32"):
            depth = _read_depth_metres(folder, labels, width, height)
            if not isinstance(depth, str) and depth.shape == (height, width):
                sky = ~np.isfinite(depth)
                if sky.any():
                    sky_means.append(float(values[sky].mean()))
        graded += 1
    sky_note = (f"; mean albedo over sky pixels {max(sky_means):.4f} at most "
                f"(reported, not graded)" if sky_means else "")
    return Check("albedo_range", PASS,
                 f"{graded} albedo images: 16-bit, finite, in [0, 1], and unlike the "
                 f"beauty picture on at least {least[0] * 100:.1f} % of pixels at "
                 f"{least[1]} (minimum {ALBEDO_MIN_DIFFERENT_FRACTION * 100:g} %)"
                 + sky_note)


# -- P10 / D1: the vertical datum ---------------------------------------------

#: How far the manifest's geoid undulation may sit from the checker's own
#: re-evaluation of the same grid. Two bilinear readers of one file agree
#: to floating-point; 0.01 m catches a nearest-neighbour producer (the
#: grid's own bilinear bound is 1.152 m), a wrong origin, a wrong grid.
DATUM_TOL_M = 0.01
FAIL_DATUM = "scene.datum"
#: The committed EGM96 grid the checker reads for itself (assets/geoid),
#: and the EGM2008 grid of the bake cache (data/geoid; not committed, so
#: an EGM2008 block is NOT RUN here when the cache lacks it -- the crop
#: check below covers it from the bake's own files).
DATUM_GRID = Path(__file__).resolve().parents[2] / "assets" / "geoid" / "egm96-15.pgm"
DATUM_GRID_EGM2008 = Path(__file__).resolve().parents[2] / "data" / "geoid" / "egm2008-5.pgm"
DATUM_KEYS = (
    "vertical_datum_of_heights", "geoid_model", "origin_lat_deg",
    "origin_lon_deg", "undulation_m", "undulation_source",
    "bilinear_error_bound_m", "model_difference_bound_m",
    "orthometric_height_of_origin_m", "ellipsoidal_height_of_origin_m", "note",
)
#: The independent evaluation of the bake's .gtx crop (PROJ vgridshift,
#: +inv so +N is read; bilinear on the nodes) against the producer's
#: bilinear values from the FULL grid: 0.01 m (measured 2e-6 m on a
#: node-aligned crop; a crop misaligned by one third of a node misses by
#: 0.06 m at the Matterhorn origin).
DATUM_INDEPENDENT_TOL_M = 0.01


def _own_undulation(path, lat_deg: float, lon_deg: float):
    """The checker's OWN GeographicLib-PGM reader (it never imports
    core.terrain.geoid): header offset/scale, big-endian uint16 samples
    from 90N 0E, bilinear on the four surrounding nodes. Returns (N in
    metres, the file's sha256)."""
    import re

    import numpy as np

    data = Path(path).read_bytes()
    match = re.match(rb"P5\s*(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s*(?:#[^\n]*\n\s*)*(\d+)\s", data)
    header = data[:match.end()].decode("ascii", "replace")
    width, height = int(match.group(1)), int(match.group(2))
    offset = float(re.search(r"# Offset (\S+)", header).group(1))
    scale = float(re.search(r"# Scale (\S+)", header).group(1))
    values = np.frombuffer(data, dtype=">u2", offset=match.end(),
                           count=width * height).reshape(height, width)
    fy = (90.0 - float(lat_deg)) * (height - 1) / 180.0
    fx = (float(lon_deg) % 360.0) * width / 360.0
    iy = min(int(math.floor(fy)), height - 2)
    ix = int(math.floor(fx)) % width
    dy, dx, ix1 = fy - iy, fx - ix, (ix + 1) % width
    value = (float(values[iy, ix]) * (1.0 - dx) * (1.0 - dy)
             + float(values[iy, ix1]) * dx * (1.0 - dy)
             + float(values[iy + 1, ix]) * (1.0 - dx) * dy
             + float(values[iy + 1, ix1]) * dx * dy)
    return offset + scale * value, hashlib.sha256(data).hexdigest()


def _datum_model(datum: Dict) -> str:
    """Which grid the block was evaluated with, from its key or, for a
    block written before the key existed, from the model's name."""
    key = datum.get("geoid_model_key")
    if key in ("EGM2008", "EGM96"):
        return key
    return "EGM2008" if "EGM2008" in str(datum.get("geoid_model")) else "EGM96"


def verify_datum(manifest: Dict) -> Check:
    """The scene's vertical datum block against the checker's own geoid.

    NOT RUN on a scene with no georeferenced heights (a flat slab or a
    synthesised ridge: ``undulation_m`` is null there, by contract), on
    a manifest written before the block existed, and on an EGM2008
    block when the checker's machine has no EGM2008 grid in its cache
    (the grid is not committed; ``datum_independent`` re-measures such
    a block from the bake's own crop). Otherwise the block must carry
    every key of DATUM_KEYS, name the grid the checker holds (by
    sha256), state a bilinear undulation within DATUM_TOL_M of the
    checker's own bilinear evaluation at the recorded origin (a block
    interpolated another way carries ``undulation_bilinear_m`` beside
    ``undulation_m``, and the two may differ by no more than the
    header's two bounds), and an ellipsoidal height equal to
    orthometric + undulation. FAIL by name (scene.datum) on any of
    these. What is NOT checked: that the heights themselves are EGM2008
    orthometric (the bake's provenance says so; no second source is
    available here), the EGM96-EGM2008 difference beyond the stated
    bound, and the cubic interpolation itself (its bound is checked,
    its arithmetic is the crop check's business).
    """
    datum = manifest.get("datum")
    if not isinstance(datum, dict):
        return Check("datum", NOT_RUN,
                     "the manifest carries no datum block (written before the "
                     "vertical datum landed); nothing to re-evaluate")
    if datum.get("undulation_m") is None:
        return Check("datum", NOT_RUN,
                     f"no georeferenced heights ({datum.get('vertical_datum_of_heights')}): "
                     f"the undulation is null by contract and there is nothing to re-evaluate")
    missing = [key for key in DATUM_KEYS if key not in datum]
    if missing:
        return Check("datum", FAIL,
                     f"the datum block lacks {missing}; a block that does not say "
                     f"where its undulation came from cannot be checked",
                     failure=FAIL_DATUM)
    model = _datum_model(datum)
    grid = DATUM_GRID_EGM2008 if model == "EGM2008" else DATUM_GRID
    if not grid.is_file():
        if model == "EGM2008":
            return Check("datum", NOT_RUN,
                         f"the block was evaluated with EGM2008 and the checker's cache "
                         f"has no EGM2008 grid ({grid}; not committed); the bake's own "
                         f"crop is re-measured by datum_independent instead")
        return Check("datum", FAIL,
                     f"the checker's own geoid grid {grid} is absent, so the "
                     f"manifest's undulation cannot be re-evaluated (see "
                     f"assets/geoid/README.md)", failure=FAIL_DATUM)
    own, digest = _own_undulation(grid, datum["origin_lat_deg"], datum["origin_lon_deg"])
    recorded = (datum.get("undulation_source") or {}).get("sha256")
    if recorded != digest:
        return Check("datum", FAIL,
                     f"the manifest's undulation came from a grid with sha256 "
                     f"{str(recorded)[:16]}..., the checker's {model} grid is {digest[:16]}...; "
                     f"two grids cannot be compared", failure=FAIL_DATUM)
    stated = float(datum["undulation_m"])
    interpolation = str(datum.get("interpolation") or "bilinear")
    bilinear = stated if interpolation == "bilinear" else datum.get("undulation_bilinear_m")
    if not isinstance(bilinear, (int, float)):
        return Check("datum", FAIL,
                     f"the block is interpolated {interpolation!r} and carries no "
                     f"undulation_bilinear_m to re-evaluate against", failure=FAIL_DATUM)
    bilinear = float(bilinear)
    if abs(bilinear - own) > DATUM_TOL_M:
        return Check("datum", FAIL,
                     f"the manifest states a bilinear undulation of {bilinear:.3f} m at "
                     f"({datum['origin_lat_deg']}, {datum['origin_lon_deg']}); the "
                     f"checker's own bilinear read of the same grid gives {own:.3f} m "
                     f"(tolerance {DATUM_TOL_M} m)", failure=FAIL_DATUM)
    if interpolation != "bilinear":
        allowed = float(datum.get("bilinear_error_bound_m") or 0.0) + float(
            datum.get("interpolation_error_bound_m") or 0.0)
        if abs(stated - bilinear) > allowed:
            return Check("datum", FAIL,
                         f"the {interpolation} undulation {stated:.3f} m sits {abs(stated - bilinear):.3f} m "
                         f"from the bilinear one {bilinear:.3f} m, beyond the header's two "
                         f"bounds ({allowed:.3f} m)", failure=FAIL_DATUM)
    ellipsoidal = float(datum["ellipsoidal_height_of_origin_m"])
    orthometric = float(datum["orthometric_height_of_origin_m"])
    if abs(ellipsoidal - (orthometric + stated)) > 1e-6:
        return Check("datum", FAIL,
                     f"ellipsoidal height {ellipsoidal:.3f} m is not orthometric "
                     f"{orthometric:.3f} m + undulation {stated:.3f} m",
                     failure=FAIL_DATUM)
    return Check("datum", PASS,
                 f"heights {datum['vertical_datum_of_heights']}; {model} {interpolation} undulation "
                 f"{stated:+.3f} m at the origin (bilinear {bilinear:+.3f} m) agrees with the "
                 f"checker's own read of the grid to {abs(bilinear - own):.4f} m; ellipsoidal "
                 f"origin {ellipsoidal:.1f} m = orthometric {orthometric:.1f} m + N")


def verify_datum_independent(manifest: Dict, run_dir=None) -> Check:
    """The bake's own geoid crop (``<stem>_geoid.gtx``, a node-aligned
    NOAA gtx of the model's nodes) evaluated by PROJ -- code this
    checker and the producer share nothing with -- against the values
    the producer recorded from the FULL grid (``<stem>_geoid.json``): the
    origin's bilinear undulation and 100 interior points, each within
    DATUM_INDEPENDENT_TOL_M, with ``+inv`` so the grid's +N is read (a
    forward pipeline reads -N and fails by 2N), the crop's header
    corner on whole nodes of its posting, and inf one node outside the
    crop. Independent of the producer's interpolation CODE, not of its
    DATA: the grid the crop was cut from is the producer's, anchored
    only by its recorded sha256. NOT RUN without a georeferenced block,
    a gtx sub-block, a bake path (``scene.terrain``) or pyproj; FAIL
    (scene.datum) on an absent or altered file, a misaligned corner, a
    residual beyond the tolerance, or a finite value outside the crop.
    """
    datum = manifest.get("datum")
    if not isinstance(datum, dict) or datum.get("undulation_m") is None:
        return Check("datum_independent", NOT_RUN,
                     "no georeferenced datum block; no crop to evaluate")
    gtx = datum.get("gtx")
    if not isinstance(gtx, dict):
        return Check("datum_independent", NOT_RUN,
                     "the datum block carries no gtx crop (a bake from before the crop "
                     "was written); re-bake to get one")
    stem = (manifest.get("scene") or {}).get("terrain")
    if not stem:
        return Check("datum_independent", NOT_RUN,
                     "the manifest names no bake (scene.terrain), so the crop beside it "
                     "cannot be found")
    try:
        from pyproj import Transformer
    except ImportError:
        return Check("datum_independent", NOT_RUN, "pyproj is not installed here")
    import struct

    folder = Path(str(stem)).parent
    path = folder / str(gtx.get("file"))
    samples_path = folder / str(gtx.get("samples_file"))
    for file, expected in ((path, gtx.get("sha256")), (samples_path, gtx.get("samples_sha256"))):
        if not file.is_file():
            return Check("datum_independent", FAIL,
                         f"the bake's geoid file {file} is absent", failure=FAIL_DATUM)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        if digest != expected:
            return Check("datum_independent", FAIL,
                         f"{file.name} has sha256 {digest[:16]}..., not the block's "
                         f"{str(expected)[:16]}...; the crop is not the one the bake wrote",
                         failure=FAIL_DATUM)
    lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">ddddii", path.read_bytes()[:40])
    posting = float(gtx.get("posting_deg") or 0.0)
    if (abs(dlat - posting) > 1e-12 or abs(dlon - posting) > 1e-12
            or abs(lat0 / dlat - round(lat0 / dlat)) > 1e-6
            or abs(lon0 / dlon - round(lon0 / dlon)) > 1e-6
            or (rows, cols) != (gtx.get("rows"), gtx.get("cols"))):
        return Check("datum_independent", FAIL,
                     f"the crop's corner ({lat0}, {lon0}) or steps ({dlat}, {dlon}) are not "
                     f"whole nodes of the {posting} deg posting the block records "
                     f"({rows}x{cols} vs {gtx.get('rows')}x{gtx.get('cols')})",
                     failure=FAIL_DATUM)
    samples = json.loads(samples_path.read_text(encoding="utf-8"))
    interior = samples.get("interior") or {}
    evaluator = Transformer.from_pipeline(f"+inv +proj=vgridshift +grids={path}")
    origin_lat, origin_lon = float(datum["origin_lat_deg"]), float(datum["origin_lon_deg"])
    stated = datum.get("undulation_bilinear_m", datum.get("undulation_m"))
    at_origin = evaluator.transform(origin_lon, origin_lat, 0.0)[2]
    if not math.isfinite(at_origin) or abs(at_origin - float(stated)) > DATUM_INDEPENDENT_TOL_M:
        return Check("datum_independent", FAIL,
                     f"PROJ reads {at_origin:+.3f} m from the crop at the origin; the block "
                     f"states {float(stated):+.3f} m (bilinear); tolerance "
                     f"{DATUM_INDEPENDENT_TOL_M} m (a sign flip reads -N)", failure=FAIL_DATUM)
    worst = 0.0
    points = list(zip(interior.get("lat_deg", ()), interior.get("lon_deg", ()),
                      interior.get("undulation_bilinear_m", ())))
    if len(points) < 100:
        return Check("datum_independent", FAIL,
                     f"the samples file records {len(points)} interior points; 100 are "
                     f"the contract", failure=FAIL_DATUM)
    for lat, lon, expected in points:
        value = evaluator.transform(float(lon), float(lat), 0.0)[2]
        residual = abs(value - float(expected)) if math.isfinite(value) else float("inf")
        worst = max(worst, residual)
    if worst > DATUM_INDEPENDENT_TOL_M:
        return Check("datum_independent", FAIL,
                     f"PROJ's evaluation of the crop disagrees with the producer's full-grid "
                     f"values by up to {worst:.4f} m over {len(points)} interior points "
                     f"(tolerance {DATUM_INDEPENDENT_TOL_M} m): the crop's nodes or their "
                     f"alignment are not the grid's", failure=FAIL_DATUM)
    outside = [evaluator.transform(lon0, lat0 + rows * dlat, 0.0)[2],
               evaluator.transform(lon0 - dlon, lat0, 0.0)[2]]
    if any(math.isfinite(v) for v in outside):
        return Check("datum_independent", FAIL,
                     f"the crop answers {outside} one node outside its stated extent; a "
                     f"crop that is not bounded is not the crop the block describes",
                     failure=FAIL_DATUM)
    return Check("datum_independent", PASS,
                 f"PROJ +inv vgridshift on {path.name} ({rows}x{cols} nodes at {posting:.6f} deg, "
                 f"corner on whole nodes) reads {at_origin:+.3f} m at the origin (block "
                 f"{float(stated):+.3f} m) and agrees with the producer's full-grid values to "
                 f"{worst:.2e} m over {len(points)} interior points; inf outside")


# -- D2: the DIS entity-state stream round trip ------------------------------

#: The full-rate Entity State PDU log a capture writes beside its manifest
#: with --dis (core/interop/dis_stream.py) and its index. The checker walks
#: the bytes with its own reading of IEEE 1278.1-2012 7.2.2 and imports
#: nothing from the producer package.
DIS_STREAM_FILE = "dis_entity_state.bin"
DIS_INDEX_FILE = "dis_entity_state.json"
DIS_RECORD_NAME = "dis.entity_state"
DIS_PDU_LENGTH = 144
DIS_TIMESTAMP_UNITS_PER_HOUR = 2 ** 31
#: Location: the wire's float64 ECEF against pyproj's EPSG:4979 -> EPSG:4978
#: of the recorded (lat, lon, hae_m). 0.05 m holds the export to the 3.4 cm
#: the JSBSim ECEF cross-check measured (blueprint section 5) while a PDU
#: moved 1 m, or a stale undulation (|N| >= 17 m at every committed scene),
#: fails. Euler: 1e-4 rad against the checker's own composition (the wire is
#: float32, ~1e-7 rad at pi); a flipped sign misses by 2|angle|. Timestamps:
#: strictly increasing after one hour unwrap.
DIS_LOCATION_TOL_M = 0.05
DIS_EULER_TOL_RAD = 1e-4
FAIL_DIS_ROUNDTRIP = "check.dis_roundtrip"


def _dis_walk(data: bytes):
    """The checker's OWN reading of the Entity State PDU (IEEE 1278.1-2012
    7.2.2 with the version-7 header): (offset, fields) per PDU, walking by
    the header's length field. Raises ValueError on anything that is not
    whole version-7 Entity State PDUs of 144 bytes."""
    import struct

    pdus = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError(f"{len(data) - offset} trailing bytes at {offset} are shorter "
                             f"than a PDU header")
        version, exercise, pdu_type, family = struct.unpack(">BBBB", data[offset:offset + 4])
        timestamp = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        length = struct.unpack(">H", data[offset + 8:offset + 10])[0]
        if version != 7 or pdu_type != 1 or family != 1:
            raise ValueError(f"PDU at {offset} is version {version}, type {pdu_type}, "
                             f"family {family}; not a version-7 Entity State PDU")
        if length != DIS_PDU_LENGTH or offset + length > len(data):
            raise ValueError(f"PDU at {offset} declares {length} bytes; {len(data) - offset} "
                             f"remain and this reader takes {DIS_PDU_LENGTH}")
        chunk = data[offset:offset + length]
        site, application, entity = struct.unpack(">HHH", chunk[12:18])
        force_id, n_params = struct.unpack(">BB", chunk[18:20])
        pdus.append((offset, {
            "exercise_id": exercise, "timestamp": timestamp,
            "site": site, "application": application, "entity": entity,
            "force_id": force_id, "variable_parameters": n_params,
            "entity_type": struct.unpack(">BBHBBBB", chunk[20:28]),
            "velocity": struct.unpack(">fff", chunk[36:48]),
            "location": struct.unpack(">ddd", chunk[48:72]),
            "orientation": struct.unpack(">fff", chunk[72:84]),
            "dr_algorithm": chunk[88], "marking": chunk[129:140],
            "time_past_hour_s": (timestamp >> 1) * 3600.0 / DIS_TIMESTAMP_UNITS_PER_HOUR,
            "absolute": bool(timestamp & 1),
        }))
        offset += length
    return pdus


def _dis_own_euler(lat_deg, lon_deg, heading_deg, pitch_deg, roll_deg):
    """The checker's own DIS orientation (psi, theta, phi, radians): the
    body-from-ECEF matrix composed as body-from-NED (passive yaw about
    down, pitch about the new right axis, roll about the new forward
    axis) times NED-from-ECEF (rows north, east, down at the place), the
    angles read off it as theta = asin(-r02), psi = atan2(r01, r00),
    phi = atan2(r12, r22). Written here from the definition, not taken
    from the producer."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sl, cl, so, co = math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon)
    ned_from_ecef = ((-sl * co, -sl * so, cl), (-so, co, 0.0), (-cl * co, -cl * so, -sl))
    h, p, r = (math.radians(heading_deg), math.radians(pitch_deg), math.radians(roll_deg))
    ch, sh, cp, sp, cr, sr = math.cos(h), math.sin(h), math.cos(p), math.sin(p), math.cos(r), math.sin(r)
    yaw = ((ch, sh, 0.0), (-sh, ch, 0.0), (0.0, 0.0, 1.0))
    pitch = ((cp, 0.0, -sp), (0.0, 1.0, 0.0), (sp, 0.0, cp))
    roll = ((1.0, 0.0, 0.0), (0.0, cr, sr), (0.0, -sr, cr))

    def mul(a, b):
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                     for i in range(3))

    m = mul(roll, mul(pitch, mul(yaw, ned_from_ecef)))
    theta = math.asin(max(-1.0, min(1.0, -m[0][2])))
    psi = math.atan2(m[0][1], m[0][0])
    phi = math.atan2(m[1][2], m[2][2])
    return psi, theta, phi


def _dis_hae(columns, datum):
    """The ellipsoidal height per sample the stream should carry: the
    recorded hae_m, else altitude_m plus the manifest datum's numeric
    undulation, else altitude_m (a scene with no geoid)."""
    if "hae_m" in columns:
        return [float(h) for h in columns["hae_m"]], "hae_m"
    n = (datum or {}).get("undulation_m") if isinstance(datum, dict) else None
    n = float(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else 0.0
    return [float(a) + n for a in columns["altitude_m"]], f"altitude_m + {n:+.3f} m"


def verify_dis_roundtrip(manifest: Dict, run_dir=None) -> Check:
    """The Entity State PDU log against the recording it was made from,
    by the checker's own decode: every PDU's location within
    DIS_LOCATION_TOL_M of pyproj's EPSG:4979 -> EPSG:4978 of the
    telemetry's (lat, lon, hae_m) at the PDU's sample, its orientation
    within DIS_EULER_TOL_RAD of the checker's own DIS Euler angles from
    the recorded heading, pitch, roll and place, the timestamps strictly
    increasing (one hour unwrap allowed) with the LSB the index's mode
    says, the ids and marking the index's, the index's offsets the walk's,
    every frame's dis keys pointing at a PDU of the stream. NOT RUN
    without a stream (no file, no index and no dis.entity_state record),
    without telemetry.json, or without pyproj; FAIL (check.dis_roundtrip)
    on a record without its files, a stream that does not walk, a PDU
    moved, an angle wrong, a stale undulation, a non-monotonic clock."""
    run_dir = Path(run_dir) if run_dir is not None else None
    records = ((manifest.get("applied_variables") or {}).get("applied_variables") or [])
    record = next((r for r in records if isinstance(r, dict) and r.get("name") == DIS_RECORD_NAME), None)
    stream_path = run_dir / DIS_STREAM_FILE if run_dir is not None else None
    index_path = run_dir / DIS_INDEX_FILE if run_dir is not None else None
    have_files = (stream_path is not None and stream_path.is_file()
                  and index_path is not None and index_path.is_file())
    if record is None and not have_files:
        return Check("dis_roundtrip", NOT_RUN,
                     "no Entity State PDU log: the run was captured without --dis "
                     "(no dis_entity_state.bin, no index, no dis.entity_state record)")
    if not have_files:
        return Check("dis_roundtrip", FAIL,
                     f"the manifest carries a {DIS_RECORD_NAME} record but {DIS_STREAM_FILE} "
                     f"or {DIS_INDEX_FILE} is absent from the run directory",
                     failure=FAIL_DIS_ROUNDTRIP)
    telemetry_path = run_dir / "telemetry.json"
    if not telemetry_path.is_file():
        return Check("dis_roundtrip", NOT_RUN,
                     "no telemetry.json beside the stream, so there is no recording to "
                     "compare it with")
    try:
        from pyproj import Transformer
    except ImportError:
        return Check("dis_roundtrip", NOT_RUN, "pyproj is not installed here")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        columns = json.loads(telemetry_path.read_text(encoding="utf-8"))["columns"]
        pdus = _dis_walk(stream_path.read_bytes())
    except (ValueError, KeyError, OSError) as exc:
        return Check("dis_roundtrip", FAIL,
                     f"the stream, its index or the telemetry could not be read as what it "
                     f"claims to be: {exc}", failure=FAIL_DIS_ROUNDTRIP)
    offsets = [offset for offset, _ in pdus]
    samples = index.get("sample_indices")
    if (index.get("byte_offsets") != offsets or index.get("pdu_count") != len(pdus)
            or not isinstance(samples, list) or len(samples) != len(pdus)):
        return Check("dis_roundtrip", FAIL,
                     f"the index lists {index.get('pdu_count')} PDUs over "
                     f"{len(samples) if isinstance(samples, list) else '?'} samples; the "
                     f"checker's walk finds {len(pdus)} at offsets {offsets[:3]}...",
                     failure=FAIL_DIS_ROUNDTRIP)
    needed = ("t", "lat_deg", "lon_deg", "heading_deg", "pitch_deg", "roll_deg")
    missing = [c for c in needed if c not in columns]
    if missing or ("hae_m" not in columns and "altitude_m" not in columns):
        return Check("dis_roundtrip", FAIL,
                     f"the telemetry lacks {missing or ['hae_m / altitude_m']}, so the "
                     f"stream cannot be checked against the recording",
                     failure=FAIL_DIS_ROUNDTRIP)
    heights, height_source = _dis_hae(columns, manifest.get("datum"))
    to_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    ids = index.get("entity_id") or {}
    mode = index.get("timestamp_mode")
    marking = str((index.get("marking") or {}).get("text", "")).encode("ascii", "replace")
    worst_location = 0.0
    worst_euler = 0.0
    previous = None
    for k, (offset, pdu) in enumerate(pdus):
        s = samples[k]
        if not isinstance(s, int) or not 0 <= s < len(columns["t"]):
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} names sample {s!r}, outside the recording's "
                         f"{len(columns['t'])} samples", failure=FAIL_DIS_ROUNDTRIP)
        lat, lon = float(columns["lat_deg"][s]), float(columns["lon_deg"][s])
        expected = to_ecef.transform(lon, lat, heights[s])
        distance = math.dist(pdu["location"], expected)
        worst_location = max(worst_location, distance)
        if distance > DIS_LOCATION_TOL_M:
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} (sample {s}) sits {distance:.3f} m from pyproj's ECEF of "
                         f"the recorded place at {height_source} (tolerance "
                         f"{DIS_LOCATION_TOL_M} m): a moved PDU or a stale undulation",
                         failure=FAIL_DIS_ROUNDTRIP)
        own = _dis_own_euler(lat, lon, float(columns["heading_deg"][s]),
                             float(columns["pitch_deg"][s]), float(columns["roll_deg"][s]))
        for name, mine, theirs in zip(("psi", "theta", "phi"), own, pdu["orientation"]):
            error = abs((float(theirs) - mine + math.pi) % (2.0 * math.pi) - math.pi)
            worst_euler = max(worst_euler, error)
            if error > DIS_EULER_TOL_RAD:
                return Check("dis_roundtrip", FAIL,
                             f"PDU {k} (sample {s}) {name} = {float(theirs):+.6f} rad; the "
                             f"checker's own composition gives {mine:+.6f} rad (tolerance "
                             f"{DIS_EULER_TOL_RAD} rad)", failure=FAIL_DIS_ROUNDTRIP)
        if (pdu["site"], pdu["application"], pdu["entity"]) != (
                ids.get("site"), ids.get("application"), ids.get("entity")):
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} carries entity id {pdu['site']}:{pdu['application']}:"
                         f"{pdu['entity']}; the index says {ids}", failure=FAIL_DIS_ROUNDTRIP)
        if pdu["marking"].rstrip(b"\0") != marking:
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} is marked {pdu['marking']!r}; the index says {marking!r}",
                         failure=FAIL_DIS_ROUNDTRIP)
        if pdu["absolute"] != (mode == "absolute"):
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k}'s timestamp LSB says {'absolute' if pdu['absolute'] else 'relative'}; "
                         f"the index says {mode!r}", failure=FAIL_DIS_ROUNDTRIP)
        seconds = pdu["time_past_hour_s"]
        if previous is not None:
            if seconds < previous - 1800.0:
                seconds += 3600.0                      # one wrap at the hour
            if seconds <= previous:
                return Check("dis_roundtrip", FAIL,
                             f"PDU {k}'s timestamp ({seconds:.6f} s past the hour) is not "
                             f"after PDU {k - 1}'s ({previous:.6f} s)", failure=FAIL_DIS_ROUNDTRIP)
        previous = seconds
    for f, frame in enumerate(manifest.get("frames") or []):
        keys = frame.get("dis") if isinstance(frame, dict) else None
        if not isinstance(keys, dict) or keys.get("pdu_index") is None:
            continue
        k = keys.get("pdu_index")
        if not isinstance(k, int) or not 0 <= k < len(pdus) or keys.get("byte_offset") != offsets[k]:
            return Check("dis_roundtrip", FAIL,
                         f"frame {f} names PDU {k!r} at byte {keys.get('byte_offset')!r}, which "
                         f"the stream does not hold at that offset", failure=FAIL_DIS_ROUNDTRIP)
    return Check("dis_roundtrip", PASS,
                 f"{len(pdus)} Entity State PDUs walked by the checker's own layout: location "
                 f"within {worst_location:.2e} m of pyproj at {height_source} (tolerance "
                 f"{DIS_LOCATION_TOL_M} m), orientation within {worst_euler:.2e} rad of the "
                 f"checker's own Euler composition (tolerance {DIS_EULER_TOL_RAD} rad), "
                 f"timestamps {mode} and strictly increasing, ids and marking as indexed")


# -- Advancement I3: the instrument models' measured channels ---------------

def verify_instruments(manifest: Dict, run_dir=None) -> Check:
    """telemetry_measured.json against the profile it carries and the
    recorder's truth beside it (core/telemetry/instruments_check.py, which
    imports nothing from the producer). NOT RUN when the run has no
    measured file (the ideal profile, or none stated)."""
    from ..telemetry.instruments_check import check_instruments

    result = check_instruments(run_dir)
    return Check("instruments", result.status, result.detail, result.failure)

# -- S1: the sensing checks -- the PSF on the calibration edge, the blur against
#    the flow, the grey card against the predicted chain ---------------------------

#: The checker's own e-SFR MTF50 against the manifest's predicted one, as a
#: fraction (the producer measured 0.45 % and 1.3 % on synthetic edges; 5 % is
#: the blueprint's clause).
PSF_MTF50_TOL = 0.05
#: A recorded streak against the flow's prediction: the larger of this many
#: pixels and this fraction of the prediction (the producer's own estimator
#: holds 0.25 px for streaks of 2 px and longer).
BLUR_TOL_PX = 0.25
BLUR_TOL_FRACTION = 0.10
#: The grey card's measured / predicted ratio (S4's calibration.json) must sit
#: within this of one.
GREY_CARD_TOL = 0.02
FAIL_PSF = "annotation.psf"
FAIL_BLUR = "annotation.blur"
FAIL_RADIOMETRY = "annotation.radiometry"


def _sensing_cameras(manifest, key):
    """{camera_id: sensing block} over the camera blocks whose ``sensing``
    carries a ``key`` block (the capture manifest's cameras[i].sensing)."""
    out = {}
    for block in manifest.get("cameras", []) or []:
        sensing = block.get("sensing") if isinstance(block, dict) else None
        if isinstance(sensing, dict) and isinstance(sensing.get(key), dict):
            out[str(block.get("camera_id"))] = sensing
    return out


def _sensing_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sensing_read_linear_gray(path):
    """An 8-bit sRGB PNG as linear gray in [0, 1] by the checker's own sRGB
    inverse (IEC 61966-2-1: c / 12.92 below 0.04045, ((c + 0.055) / 1.055)^2.4
    above), channels averaged; None when it cannot be read."""
    import numpy as np

    try:
        from PIL import Image

        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    except (OSError, ImportError):
        return None
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return linear.mean(axis=2)


def _sensing_own_mtf50(gray, oversample=4):
    """The checker's OWN e-SFR (ISO 12233 from the definition, written apart
    from the producer's): each row's edge at the half-level crossing between
    the row's 10th and 90th percentile levels, linearly interpolated; a
    least-squares line through the crossings; every pixel's distance along
    the edge normal binned at 1 / oversample px into the edge spread
    function; the line spread function by finite difference under a
    Hamming window; the MTF by FFT; MTF50 at the first half crossing.
    None when no edge is found."""
    import numpy as np

    image = np.asarray(gray, dtype=np.float64)
    height, width = image.shape
    rows, crossings = [], []
    for y in range(height):
        row = image[y]
        lo, hi = np.percentile(row, 10), np.percentile(row, 90)
        if hi - lo <= 1e-9:
            continue
        level = 0.5 * (lo + hi)
        rising = row[-1] > row[0]
        above = row >= level if rising else row <= level
        idx = np.flatnonzero(above)
        if idx.size == 0 or idx[0] == 0:
            continue
        i = int(idx[0])
        v0, v1 = row[i - 1], row[i]
        if v1 == v0:
            continue
        crossings.append((i - 1) + (level - v0) / (v1 - v0))
        rows.append(float(y))
    if len(rows) < 3:
        return None
    slope, intercept = np.polyfit(np.asarray(rows), np.asarray(crossings), 1)
    cos_theta = 1.0 / math.sqrt(1.0 + slope * slope)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    distance = (xs - (intercept + slope * ys)) * cos_theta
    bins = np.floor(distance * oversample).astype(int)
    bins -= bins.min()
    counts = np.bincount(bins.ravel())
    sums = np.bincount(bins.ravel(), weights=image.ravel())
    esf = np.full(len(counts), np.nan)
    esf[counts > 0] = sums[counts > 0] / counts[counts > 0]
    first = esf[counts > 0][0]
    for i in range(len(esf)):
        if np.isnan(esf[i]):
            esf[i] = esf[i - 1] if i > 0 else first
    lsf = np.diff(esf) * np.hamming(len(esf) - 1)
    spectrum = np.abs(np.fft.rfft(lsf))
    if spectrum[0] <= 0.0:
        return None
    mtf = spectrum / spectrum[0]
    freqs = np.fft.rfftfreq(len(lsf), d=1.0 / oversample)
    below = np.flatnonzero(mtf < 0.5)
    if below.size == 0:
        return float(freqs[-1])
    i = int(below[0])
    if i == 0:
        return 0.0
    return float(freqs[i - 1] + (0.5 - mtf[i - 1]) * (freqs[i] - freqs[i - 1]) / (mtf[i] - mtf[i - 1]))


def verify_psf_slanted_edge(manifest: Dict, run_dir=None) -> Check:
    """The PSF the sensor post-pass applied, measured by the checker's own
    e-SFR on the calibration frame's slanted-edge quad (render.json root
    ``calibration.slanted_edge {frame, quad_px}``, S4) and held to the
    manifest's predicted MTF50 within PSF_MTF50_TOL; the kernel sensor.json
    says it applied must be the manifest's. NOT RUN without a sensing.optics
    block, a run directory or a calibration edge; FAIL annotation.psf."""
    import numpy as np

    cameras = _sensing_cameras(manifest, "optics")
    if not cameras:
        return Check("psf_slanted_edge", NOT_RUN,
                     "no camera carries a sensing.optics block: no PSF was applied")
    if run_dir is None:
        return Check("psf_slanted_edge", NOT_RUN, "no run directory: the sensor frames are not here")
    graded, details = 0, []
    for camera, sensing in cameras.items():
        folder = Path(run_dir) / "frames" / camera
        render = _sensing_json(folder / "render.json") or {}
        calibration = render.get("calibration") if isinstance(render, dict) else None
        edge = calibration.get("slanted_edge") if isinstance(calibration, dict) else None
        if not isinstance(edge, dict) or not edge.get("frame") or not edge.get("quad_px"):
            details.append(f"{camera}: no calibration frame with a slanted-edge quad "
                           f"(render with -calibration on Windows, S4)")
            continue
        frame_name = str(edge["frame"])
        sensor_json = _sensing_json(folder / "sensor.json") or {}
        item = next((f for f in sensor_json.get("frames", []) if f.get("frame") == frame_name), None)
        if item is None or not item.get("sensor"):
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the calibration frame {frame_name} has no sensor frame in "
                         f"sensor.json, so the PSF was never applied to the edge", failure=FAIL_PSF)
        applied = ((item.get("sensing") or {}).get("psf") or {}).get("kernel_sha256")
        expected = sensing["optics"].get("kernel_sha256")
        if applied != expected:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the kernel applied to {frame_name} ({str(applied)[:16]}..) is "
                         f"not the manifest's ({str(expected)[:16]}..)", failure=FAIL_PSF)
        gray = _sensing_read_linear_gray(folder / str(item["sensor"]))
        if gray is None:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the sensor frame {item['sensor']} cannot be read", failure=FAIL_PSF)
        quad = np.asarray(edge["quad_px"], dtype=np.float64).reshape(-1, 2)
        u0 = max(0, int(math.floor(quad[:, 0].min())))
        u1 = min(gray.shape[1], int(math.ceil(quad[:, 0].max())))
        v0 = max(0, int(math.floor(quad[:, 1].min())))
        v1 = min(gray.shape[0], int(math.ceil(quad[:, 1].max())))
        crop = gray[v0:v1, u0:u1]
        if crop.shape[0] < 8 or crop.shape[1] < 8:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the slanted-edge quad is {crop.shape[1]} x {crop.shape[0]} px, "
                         f"too small to measure", failure=FAIL_PSF)
        measured = _sensing_own_mtf50(crop)
        if measured is None:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: no edge was found inside the slanted-edge quad of {frame_name}",
                         failure=FAIL_PSF)
        predicted = float(sensing["optics"]["mtf50_predicted_cyc_per_px"])
        error = abs(measured - predicted) / predicted if predicted > 0.0 else math.inf
        if error > PSF_MTF50_TOL:
            return Check("psf_slanted_edge", FAIL,
                         f"{camera}: the checker's own e-SFR reads MTF50 {measured:.4f} cycles/px on "
                         f"the calibration edge against the manifest's predicted {predicted:.4f} "
                         f"({error * 100:.1f} %, tolerance {PSF_MTF50_TOL * 100:.0f} %)",
                         failure=FAIL_PSF)
        graded += 1
        details.append(f"{camera}: MTF50 {measured:.4f} cycles/px by the checker's own e-SFR against "
                       f"{predicted:.4f} predicted ({error * 100:.1f} %)")
    if graded == 0:
        return Check("psf_slanted_edge", NOT_RUN, "; ".join(details))
    return Check("psf_slanted_edge", PASS, "; ".join(details))


def _sensing_read_flow(path, width, height):
    """frame_NNNN_flow.f32 as (h, w, 2) float64 pixels; None when the size
    is not width x height x 2 float32 values."""
    import numpy as np

    try:
        raw = np.fromfile(path, dtype="<f4")
    except OSError:
        return None
    if raw.size != width * height * 2:
        return None
    return raw.reshape(height, width, 2).astype("float64")


def verify_blur_vs_flow(manifest: Dict, run_dir=None) -> Check:
    """The streak the sensor post-pass recorded per frame (sensor.json
    ``sensing.blur.blur_px_max``) against the checker's own prediction from
    the engine's flow pass: the 95th percentile of |flow| over the frame
    (pixels since the previous captured frame) divided by the capture
    interval, times the exposure. Held within the larger of BLUR_TOL_PX and
    BLUR_TOL_FRACTION of the prediction. NOT RUN without a sensing.motion_blur
    block, a run directory, or any frame with a flow file (S2's pass); a
    frame the engine accumulated (S4) is not graded here and says so.
    FAIL annotation.blur."""
    import numpy as np

    cameras = _sensing_cameras(manifest, "motion_blur")
    if not cameras:
        return Check("blur_vs_flow", NOT_RUN,
                     "no camera carries a sensing.motion_blur block: no blur was applied")
    if run_dir is None:
        return Check("blur_vs_flow", NOT_RUN, "no run directory: the flow files are not here")
    graded, worst, notes = 0, 0.0, []
    for camera, sensing in cameras.items():
        folder = Path(run_dir) / "frames" / camera
        render = _sensing_json(folder / "render.json") or {}
        records = render.get("frame_records") if isinstance(render, dict) else None
        engine = {r.get("frame"): r for r in records if isinstance(r, dict)} if isinstance(records, list) else {}
        sensor_json = _sensing_json(folder / "sensor.json") or {}
        applied = {f.get("frame"): f for f in sensor_json.get("frames", []) if isinstance(f, dict)}
        frames = sorted((f for f in manifest.get("frames", []) if str(f.get("camera_id")) == camera),
                        key=lambda f: float(f.get("t_s", 0.0)))
        for previous, record in zip(frames, frames[1:]):
            name = Path(str(record.get("file"))).name
            flow_file = ((engine.get(name) or {}).get("labels") or {}).get("flow_f32")
            if not flow_file:
                continue
            blur = ((applied.get(name) or {}).get("sensing") or {}).get("blur")
            if not isinstance(blur, dict):
                continue
            if blur.get("applied_by") == "engine_accumulation":
                notes.append(f"{camera}/{name}: the engine accumulated k = {blur.get('k')} sub-exposures; "
                             f"graded on Windows against the accumulation (S4), not here")
                continue
            width, height = int(record["width_px"]), int(record["height_px"])
            flow = _sensing_read_flow(folder / str(flow_file), width, height)
            if flow is None:
                return Check("blur_vs_flow", FAIL,
                             f"{camera}/{name}: {flow_file} is not {width} x {height} x 2 float32 values",
                             failure=FAIL_BLUR)
            speed = np.hypot(flow[..., 0], flow[..., 1])
            finite = speed[np.isfinite(speed)]
            if finite.size == 0:
                return Check("blur_vs_flow", FAIL, f"{camera}/{name}: the flow holds no finite value",
                             failure=FAIL_BLUR)
            interval = float(record.get("t_s", 0.0)) - float(previous.get("t_s", 0.0))
            if interval <= 0.0:
                return Check("blur_vs_flow", FAIL,
                             f"{camera}/{name}: the capture interval before this frame is {interval} s",
                             failure=FAIL_BLUR)
            predicted = float(np.percentile(finite, 95)) * float(blur.get("exposure_s", 0.0)) / interval
            recorded = blur.get("blur_px_max")
            if not isinstance(recorded, (int, float)):
                return Check("blur_vs_flow", FAIL, f"{camera}/{name}: no streak length recorded",
                             failure=FAIL_BLUR)
            tolerance = max(BLUR_TOL_PX, BLUR_TOL_FRACTION * predicted)
            error = abs(float(recorded) - predicted)
            worst = max(worst, error)
            if error > tolerance:
                return Check("blur_vs_flow", FAIL,
                             f"{camera}/{name}: the recorded streak {float(recorded):.2f} px against "
                             f"{predicted:.2f} px from the flow's 95th percentile over {interval:g} s "
                             f"at {float(blur.get('exposure_s', 0.0)):g} s exposure (tolerance "
                             f"{tolerance:.2f} px)", failure=FAIL_BLUR)
            graded += 1
    if graded == 0:
        reason = ("no frame with a flow file (render with -labels -passes=velocity; the flow pass is "
                  "I6's, its keypoint check S2's)")
        if notes:
            reason = reason + "; " + "; ".join(notes)
        return Check("blur_vs_flow", NOT_RUN, reason)
    return Check("blur_vs_flow", PASS,
                 f"{graded} frame(s): the recorded streak within {worst:.3f} px of the flow's prediction "
                 f"(tolerance max({BLUR_TOL_PX} px, {BLUR_TOL_FRACTION * 100:.0f} %))"
                 + ("; " + "; ".join(notes) if notes else ""))


def verify_radiometry_grey_card(manifest: Dict, run_dir=None) -> Check:
    """The calibration chain's constant against the grey card the engine
    rendered (S4's frames/<camera>/calibration.json {predicted, measured,
    ratio}): the file's prediction must be the manifest's grey_card_predicted
    (1e-6 relative), the ratio the file's own measured / predicted (1e-6),
    within GREY_CARD_TOL of one, and the manifest's calibration_status
    'measured'. NOT RUN without a sensing.radiometry block, a run directory
    or a calibration file, and when the chain was refused
    sensing.exposure_units (the sun is not in lux). FAIL annotation.radiometry."""
    cameras = _sensing_cameras(manifest, "radiometry")
    if not cameras:
        return Check("radiometry_grey_card", NOT_RUN,
                     "no camera carries a sensing.radiometry block")
    if run_dir is None:
        return Check("radiometry_grey_card", NOT_RUN, "no run directory: no calibration file is here")
    graded, details = 0, []
    for camera, sensing in cameras.items():
        block = sensing["radiometry"]
        if block.get("calibration_status") == "refused":
            details.append(f"{camera}: the chain was refused by name -- {block.get('calibration_basis')}")
            continue
        calibration = _sensing_json(Path(run_dir) / "frames" / camera / "calibration.json")
        if calibration is None:
            details.append(f"{camera}: no calibration.json (render with -calibration on Windows, S4): "
                           f"the constant stays {block.get('calibration_status')}")
            continue
        try:
            predicted = float(calibration["predicted"])
            measured = float(calibration["measured"])
            ratio = float(calibration["ratio"])
        except (KeyError, TypeError, ValueError):
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: calibration.json lacks predicted / measured / ratio",
                         failure=FAIL_RADIOMETRY)
        own = block.get("grey_card_predicted")
        if not isinstance(own, (int, float)) or predicted <= 0.0 \
                or abs(predicted - float(own)) > 1e-6 * abs(predicted):
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: calibration.json predicts {predicted!r} for the grey card where the "
                         f"manifest's chain predicts {own!r}", failure=FAIL_RADIOMETRY)
        if abs(ratio - measured / predicted) > 1e-6 * max(1.0, abs(ratio)):
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: calibration.json's ratio {ratio:.6f} is not its own measured / "
                         f"predicted {measured / predicted:.6f}", failure=FAIL_RADIOMETRY)
        if block.get("calibration_status") != "measured":
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: a calibration file exists but the manifest's chain is "
                         f"{block.get('calibration_status')!r}, not measured", failure=FAIL_RADIOMETRY)
        if abs(ratio - 1.0) > GREY_CARD_TOL:
            return Check("radiometry_grey_card", FAIL,
                         f"{camera}: the grey card measured {ratio:.4f} of its prediction "
                         f"(tolerance {GREY_CARD_TOL * 100:.0f} %)", failure=FAIL_RADIOMETRY)
        graded += 1
        details.append(f"{camera}: grey card measured / predicted {ratio:.4f}")
    if graded == 0:
        return Check("radiometry_grey_card", NOT_RUN, "; ".join(details))
    return Check("radiometry_grey_card", PASS, "; ".join(details))


# -- S4: the sensing engine side, graded only where render.json carries it ---------
# The commandlet (FlightSimRenderCommandlet.cpp, uncompiled here) writes: the
# linear passes (labels.normal / labels.basecolor with labels.normal_axes and
# labels.normal_encoding), the velocity cross-check (labels.velocity), the
# read-backs (render_settings.console, render_settings.working_colour_space,
# look_applied.sun.lux), the calibration frame (root calibration{} and the
# calibration.json beside it) and the accumulation (frame_records[].accumulation).
# Each check grades a key only when it is present; a check with nothing to grade
# is NOT RUN, never a pass on absence. The readers are the checker's own
# (numpy.fromfile '<f4'); nothing is imported from the producer.

#: The linear .f32 layout the commandlet states (little-endian float32, no
#: header, row-major, channels interleaved): 3 a pixel for the normal and the
#: base colour, 2 for the velocity read-back.
S4_NORMAL_AXES = "north,east,up"
S4_NORMAL_ENCODINGS = ("signed", "offset_half")
#: A written (non-sky) normal is unit length within this, on at least this
#: fraction of the written pixels.
S4_NORMAL_UNIT_TOL = 0.05
S4_NORMAL_UNIT_FRACTION = 0.99
#: The recorded 95th-percentile speed against the file's own, in pixels (the
#: float32 the file holds).
S4_VELOCITY_P95_TOL_PX = 1e-3
#: The console read-backs S4 adds (r.Substrate predates it and is read too).
S4_READBACK_CVARS = ("r.EyeAdaptation.LensAttenuation", "r.UsePreExposure",
                     "r.VelocityOutputPass", "r.Substrate")
S4_LENS_ATTENUATION_CVAR = "r.EyeAdaptation.LensAttenuation"
#: core/scenario/solar.py's bound, restated: nothing above the atmosphere is
#: brighter.
S4_SUN_LUX_MAX = 133100.0
#: The chain's constant and the grey card, restated (ISO 2720 / ISO 12232).
S4_CALIBRATION_CONSTANT = 1.2
S4_GREY_CARD_REFLECTANCE = 0.18
#: The accumulation's bounds and the 0.25 px rule, restated.
S4_ACCUMULATE_MAX = 64
S4_SUB_PIXEL_BLUR_PX = 0.25
FAIL_READBACK = "annotation.readback"
FAIL_ACCUMULATION = "annotation.accumulation"


def _s4_renders(run_dir):
    """(camera, folder, payload) for every frames/<camera>/render.json that parses."""
    if run_dir is None or not (Path(run_dir) / "frames").is_dir():
        return []
    out = []
    for folder in sorted(p for p in (Path(run_dir) / "frames").iterdir() if p.is_dir()):
        payload = _sensing_json(folder / "render.json")
        if isinstance(payload, dict):
            out.append((folder.name, folder, payload))
    return out


def _s4_size(payload, record):
    return (int(record.get("applied_width_px", payload.get("width", 0)) or 0),
            int(record.get("applied_height_px", payload.get("height", 0)) or 0))


def _s4_read_f32(path, width: int, height: int, channels: int):
    """A declared linear file as (h, w, channels) float64; a string when its
    size is not the stated layout; BundleFileError when it is missing."""
    import numpy as np

    path = Path(path)
    try:
        raw = np.fromfile(path, dtype="<f4")
    except OSError as exc:
        raise BundleFileError(_unreadable(path, exc)) from exc
    if raw.size != width * height * channels:
        return (f"{path.name}: {raw.size} float32 values for a {width}x{height} file of "
                f"{channels} a pixel ({width * height * channels} expected)")
    return raw.reshape(height, width, channels).astype("float64")


def _s4_close(a, b, rel=1e-6) -> bool:
    return abs(float(a) - float(b)) <= rel * max(1.0, abs(float(a)), abs(float(b)))


@_reads_the_bundle
def verify_engine_linear_passes(manifest: Dict, run_dir=None) -> Check:
    """The linear normal and base colour files (S4) against their stated
    layout: 3 float32 a pixel; the normal in the scene axes north,east,up,
    its encoding word one the commandlet measures (signed or offset_half),
    every written (non-zero) normal unit length; the base colour finite with
    its out-of-range count the file's own; the frame-level name the labels'.
    FAIL annotation.normals / annotation.albedo; NOT RUN without either key."""
    import numpy as np

    graded, notes = 0, []
    for camera, folder, payload in _s4_renders(run_dir):
        for record in _render_frame_records(payload):
            labels = record.get("labels")
            if not isinstance(labels, dict):
                continue
            where = f"{camera}/{record.get('frame')}"
            width, height = _s4_size(payload, record)
            if labels.get("normal"):
                if labels.get("normal_axes") != S4_NORMAL_AXES:
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: the normal file's axes are {labels.get('normal_axes')!r}, "
                                 f"not {S4_NORMAL_AXES!r}", failure=FAIL_NORMALS)
                if labels.get("normal_encoding") not in S4_NORMAL_ENCODINGS:
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: the normal encoding {labels.get('normal_encoding')!r} is not "
                                 f"one the commandlet measures {S4_NORMAL_ENCODINGS}", failure=FAIL_NORMALS)
                if record.get("normal_f32") != labels["normal"]:
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: the record names {record.get('normal_f32')!r} and its labels "
                                 f"{labels['normal']!r} for one normal file", failure=FAIL_NORMALS)
                normal = _s4_read_f32(folder / str(labels["normal"]), width, height, 3)
                if isinstance(normal, str) or not np.all(np.isfinite(normal)):
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: {normal if isinstance(normal, str) else 'a non-finite normal'}",
                                 failure=FAIL_NORMALS)
                length = np.linalg.norm(normal, axis=2)
                written = length > 0.0
                if written.any():
                    unit = float(np.mean(np.abs(length[written] - 1.0) <= S4_NORMAL_UNIT_TOL))
                    if unit < S4_NORMAL_UNIT_FRACTION:
                        return Check("engine_linear_passes", FAIL,
                                     f"{where}: {unit * 100:.1f} % of the written normals are unit length "
                                     f"(at least {S4_NORMAL_UNIT_FRACTION * 100:.0f} % must be)",
                                     failure=FAIL_NORMALS)
                graded += 1
            if labels.get("basecolor"):
                if record.get("basecolor_f32") != labels["basecolor"]:
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: the record names {record.get('basecolor_f32')!r} and its labels "
                                 f"{labels['basecolor']!r} for one base colour file", failure=FAIL_ALBEDO)
                colour = _s4_read_f32(folder / str(labels["basecolor"]), width, height, 3)
                if isinstance(colour, str) or not np.all(np.isfinite(colour)):
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: {colour if isinstance(colour, str) else 'a non-finite base colour'}",
                                 failure=FAIL_ALBEDO)
                outside = int(np.count_nonzero(np.any((colour < 0.0) | (colour > 1.0), axis=2)))
                declared = labels.get("basecolor_out_of_range_pixels")
                if isinstance(declared, (int, float)) and int(declared) != outside:
                    return Check("engine_linear_passes", FAIL,
                                 f"{where}: the record declares {int(declared)} out-of-range base colour "
                                 f"pixels and the file holds {outside}", failure=FAIL_ALBEDO)
                if outside:
                    notes.append(f"{where}: {outside} base colour pixel(s) outside [0, 1], counted")
                graded += 1
    if graded == 0:
        return Check("engine_linear_passes", NOT_RUN,
                     "no render.json frame record declares labels.normal or labels.basecolor (render on "
                     "Windows with -labels -passes=normal,albedo to exercise this)")
    return Check("engine_linear_passes", PASS,
                 f"{graded} linear pass file(s): the stated layout, axes and encoding word, unit normals, "
                 f"the base colour's own counts" + ("; " + "; ".join(notes[:3]) if notes else ""))


@_reads_the_bundle
def verify_velocity_readback(manifest: Dict, run_dir=None) -> Check:
    """The engine's velocity cross-check (S4, -velocity-check) against its own
    record: 2 float32 a pixel, finite, all zeros on the first frame, and the
    recorded 95th-percentile speed over the non-sky pixels (the nearest rank
    below, as the commandlet takes it) the file's own within
    S4_VELOCITY_P95_TOL_PX. A read-back, never the truth: its agreement with
    the Python flow is the Windows step. FAIL annotation.flow; NOT RUN
    without labels.velocity."""
    import numpy as np

    graded = 0
    for camera, folder, payload in _s4_renders(run_dir):
        for record in _render_frame_records(payload):
            labels = record.get("labels")
            velocity = labels.get("velocity") if isinstance(labels, dict) else None
            if not isinstance(velocity, dict):
                continue
            where = f"{camera}/{record.get('frame')}"
            width, height = _s4_size(payload, record)
            if not velocity.get("file") or record.get("velocity_f32") != velocity.get("file"):
                return Check("velocity_readback", FAIL,
                             f"{where}: the record names {record.get('velocity_f32')!r} and its labels "
                             f"{velocity.get('file')!r} for one velocity file", failure=FAIL_FLOW)
            flow = _s4_read_f32(folder / str(velocity["file"]), width, height, 2)
            if isinstance(flow, str) or not np.all(np.isfinite(flow)):
                return Check("velocity_readback", FAIL,
                             f"{where}: {flow if isinstance(flow, str) else 'a non-finite velocity'}",
                             failure=FAIL_FLOW)
            if velocity.get("first_frame") is True and np.any(flow != 0.0):
                return Check("velocity_readback", FAIL,
                             f"{where}: the first frame's velocity is not all zeros", failure=FAIL_FLOW)
            geometry = np.ones((height, width), dtype=bool)
            if labels.get("depth_f32"):
                depth = _s4_read_f32(folder / str(labels["depth_f32"]), width, height, 1)
                if not isinstance(depth, str):
                    geometry = np.isfinite(depth[..., 0])
            speeds = np.sort(np.hypot(flow[..., 0], flow[..., 1])[geometry].astype(np.float32))
            own = 0.0 if velocity.get("first_frame") is True or speeds.size == 0 \
                else float(speeds[min(max(int(0.95 * (speeds.size - 1)), 0), speeds.size - 1)])
            recorded = velocity.get("p95_px")
            if not isinstance(recorded, (int, float)) or abs(float(recorded) - own) > S4_VELOCITY_P95_TOL_PX:
                return Check("velocity_readback", FAIL,
                             f"{where}: the record's 95th-percentile speed {recorded!r} px is not the "
                             f"file's own {own:.4f} px", failure=FAIL_FLOW)
            graded += 1
    if graded == 0:
        return Check("velocity_readback", NOT_RUN,
                     "no render.json frame record declares labels.velocity (render on Windows with "
                     "-labels -velocity-check to exercise this)")
    return Check("velocity_readback", PASS,
                 f"{graded} velocity read-back file(s) agree with their own records; the comparison "
                 f"with the Python flow is the Windows step")


def verify_engine_readbacks(manifest: Dict, run_dir=None) -> Check:
    """What the engine reported, graded where render.json carries it: the
    console read-backs S4 names (a number or 'absent'; the lens attenuation
    a fraction in (0, 1]), the working colour space (a linear space named),
    and look_applied.sun: a sun with a lux must say light_units 'physical',
    its intensity must be that lux, and the lux must lie in (0, 133100];
    a sun that says 'physical' must carry its lux. FAIL annotation.readback;
    NOT RUN with none of them."""
    graded = 0
    for camera, _folder, payload in _s4_renders(run_dir):
        settings = payload.get("render_settings") if isinstance(payload.get("render_settings"), dict) else {}
        console = settings.get("console") if isinstance(settings.get("console"), dict) else {}
        for name in S4_READBACK_CVARS:
            if name not in console:
                continue
            value = str(console[name]).strip()
            graded += 1
            if value == "absent":
                continue
            try:
                number = float(value) if value.lower() not in ("true", "false") else float(value.lower() == "true")
            except ValueError:
                return Check("engine_readbacks", FAIL,
                             f"{camera}: the console read-back {name} is {value!r}, neither a number nor "
                             f"'absent'", failure=FAIL_READBACK)
            if name == S4_LENS_ATTENUATION_CVAR and not (0.0 < number <= 1.0):
                return Check("engine_readbacks", FAIL,
                             f"{camera}: the lens attenuation read back as {number:g}, not a fraction of the "
                             f"light passed", failure=FAIL_READBACK)
        if "working_colour_space" in settings:
            space = settings["working_colour_space"]
            if not isinstance(space, str) or "linear" not in space:
                return Check("engine_readbacks", FAIL,
                             f"{camera}: the working colour space read back as {space!r}, not a linear "
                             f"space named", failure=FAIL_READBACK)
            graded += 1
        look = payload.get("look_applied") if isinstance(payload.get("look_applied"), dict) else {}
        sun = look.get("sun") if isinstance(look.get("sun"), dict) else None
        if sun is None:
            continue
        if "lux" in sun:
            lux = sun.get("lux")
            if not isinstance(lux, (int, float)) or not math.isfinite(float(lux)) \
                    or not (0.0 < float(lux) <= S4_SUN_LUX_MAX):
                return Check("engine_readbacks", FAIL,
                             f"{camera}: the sun's lux {lux!r} is not in (0, {S4_SUN_LUX_MAX:g}]",
                             failure=FAIL_READBACK)
            if sun.get("light_units") != "physical":
                return Check("engine_readbacks", FAIL,
                             f"{camera}: the sun carries {float(lux):g} lux in light units "
                             f"{sun.get('light_units')!r}, not 'physical'", failure=FAIL_READBACK)
            intensity = sun.get("intensity")
            if not isinstance(intensity, (int, float)) or not _s4_close(intensity, lux):
                return Check("engine_readbacks", FAIL,
                             f"{camera}: the sun was set to {intensity!r} while it records {float(lux):g} "
                             f"lux", failure=FAIL_READBACK)
            graded += 1
        elif sun.get("light_units") == "physical":
            return Check("engine_readbacks", FAIL,
                         f"{camera}: the sun says light units 'physical' and carries no lux",
                         failure=FAIL_READBACK)
    if graded == 0:
        return Check("engine_readbacks", NOT_RUN,
                     "no render.json carries the S4 read-backs (a render from before S4, or none)")
    return Check("engine_readbacks", PASS,
                 f"{graded} read-back(s): the console values parse, the lens attenuation is a fraction, "
                 f"the colour space is linear, a sun in lux says so and was set to it")


@_reads_the_bundle
def verify_calibration_frame(manifest: Dict, run_dir=None) -> Check:
    """The calibration frame's record (render.json root calibration{}, S4)
    re-derived by the checker: the luminance per unit 1.2 x A x 2^(EV100 -
    EC) from the recorded EV100, EC and A; the emissive quad's prediction
    nits / per unit, the Lambertian quad's rho E / pi / per unit, the root's
    the 18 % card's; every ratio its own measured / predicted and within
    GREY_CARD_TOL of one; the root measured the white quad's scaled by
    0.18 / rho; the MTF50 null or a positive number; the slanted-edge frame
    on disk with a four-corner quad; calibration.json, when beside it,
    carrying the same numbers. FAIL annotation.radiometry (annotation.files
    for a missing frame); NOT RUN without calibration{}."""
    graded, details = 0, []
    for camera, folder, payload in _s4_renders(run_dir):
        calibration = payload.get("calibration")
        if not isinstance(calibration, dict):
            continue

        def fail(text: str) -> Check:
            return Check("calibration_frame", FAIL, f"{camera}: {text}", failure=FAIL_RADIOMETRY)

        emissive = calibration.get("emissive") if isinstance(calibration.get("emissive"), dict) else {}
        white = calibration.get("lambertian") if isinstance(calibration.get("lambertian"), dict) else {}
        try:
            ev = float(calibration["ev100"])
            ec = float(calibration["exposure_compensation_ev"])
            a = float(calibration["lens_attenuation"])
            per_unit = float(calibration["luminance_cd_m2_per_unit"])
            sun = float(calibration["sun_lux"])
            nits = float(calibration["grey_card_nits"])
            rho = float(white["reflectance"])
            root = {k: float(calibration[k]) for k in ("predicted", "measured", "ratio")}
            quads = {"emissive": {k: float(emissive[k]) for k in ("predicted", "measured", "ratio")},
                     "white": {k: float(white[k]) for k in ("predicted", "measured", "ratio")}}
        except (KeyError, TypeError, ValueError):
            return fail("the calibration record lacks one of ev100, exposure_compensation_ev, "
                        "lens_attenuation, luminance_cd_m2_per_unit, sun_lux, grey_card_nits, or a "
                        "quad's predicted / measured / ratio / reflectance")
        own_per_unit = S4_CALIBRATION_CONSTANT * a * 2.0 ** (ev - ec)
        if not _s4_close(per_unit, own_per_unit):
            return fail(f"the record's {per_unit:g} cd/m^2 per unit is not 1.2 x {a:g} x 2^({ev:g} - "
                        f"{ec:g}) = {own_per_unit:g}")
        expected = {"emissive": nits / own_per_unit,
                    "white": rho * sun / math.pi / own_per_unit}
        for label, quad in quads.items():
            if not _s4_close(quad["predicted"], expected[label]):
                return fail(f"the {label} quad's prediction {quad['predicted']:g} is not the chain's "
                            f"{expected[label]:g}")
            if quad["predicted"] <= 0.0 or not _s4_close(quad["ratio"], quad["measured"] / quad["predicted"]):
                return fail(f"the {label} quad's ratio {quad['ratio']:g} is not its own measured / predicted")
            if abs(quad["ratio"] - 1.0) > GREY_CARD_TOL:
                return fail(f"the {label} quad measured {quad['ratio']:.4f} of its prediction "
                            f"(tolerance {GREY_CARD_TOL * 100:.0f} %)")
        grey = S4_GREY_CARD_REFLECTANCE * sun / math.pi / own_per_unit
        if not _s4_close(root["predicted"], grey) \
                or not _s4_close(root["measured"], quads["white"]["measured"] * S4_GREY_CARD_REFLECTANCE / rho) \
                or not _s4_close(root["ratio"], root["measured"] / root["predicted"]):
            return fail("the root predicted / measured / ratio are not the 18 % card's from the white quad")
        mtf50 = calibration.get("mtf50_measured")
        if mtf50 is not None and (not isinstance(mtf50, (int, float)) or not math.isfinite(float(mtf50))
                                  or float(mtf50) <= 0.0):
            return fail(f"the engine's MTF50 {mtf50!r} is neither null nor a positive number")
        edge = calibration.get("slanted_edge") if isinstance(calibration.get("slanted_edge"), dict) else {}
        corners = edge.get("quad_px")
        if not edge.get("frame") or not isinstance(corners, list) or len(corners) != 4:
            return fail("the slanted edge names no frame or no four-corner quad")
        if not (folder / str(edge["frame"])).is_file():
            raise BundleFileError(_unreadable(folder / str(edge["frame"]),
                                              FileNotFoundError(str(edge["frame"]))))
        beside = _sensing_json(folder / "calibration.json")
        if isinstance(beside, dict):
            for key in ("predicted", "measured", "ratio"):
                if not isinstance(beside.get(key), (int, float)) or not _s4_close(beside[key], root[key], 1e-9):
                    return fail(f"calibration.json's {key} {beside.get(key)!r} is not render.json's "
                                f"{root[key]!r}")
        graded += 1
        details.append(f"{camera}: grey card {root['ratio']:.4f}, emissive {quads['emissive']['ratio']:.4f}"
                       + (f", engine MTF50 {float(mtf50):.4f} cycles/px" if mtf50 is not None else ""))
    if graded == 0:
        return Check("calibration_frame", NOT_RUN,
                     "no render.json carries a calibration record (render on Windows with -calibration "
                     "-sun-lux= to exercise this)")
    return Check("calibration_frame", PASS, "; ".join(details))


@_reads_the_bundle
def verify_engine_accumulation(manifest: Dict, run_dir=None) -> Check:
    """Each frame's accumulation record (S4, -accumulate=K) against itself:
    k a whole number from 1 to 64; t0_s <= t <= t1_s; t1_s - t0_s the
    exposure; the sub-exposure instants k of them, at the midpoints of k
    equal slices of the window; k = 1 exactly when the predicted blur is
    under 0.25 px, else the k asked for; the accumulated file the record's
    linear file and on disk. FAIL annotation.accumulation (annotation.files
    for a missing file); NOT RUN without an accumulation record."""
    graded, single = 0, 0
    for camera, folder, payload in _s4_renders(run_dir):
        for record in _render_frame_records(payload):
            block = record.get("accumulation")
            if not isinstance(block, dict):
                continue
            where = f"{camera}/{record.get('frame')}"

            def fail(text: str) -> Check:
                return Check("engine_accumulation", FAIL, f"{where}: {text}", failure=FAIL_ACCUMULATION)

            k = block.get("k")
            if isinstance(k, bool) or not isinstance(k, (int, float)) or int(k) != k \
                    or not (1 <= int(k) <= S4_ACCUMULATE_MAX):
                return fail(f"k = {k!r} is not a whole number of sub-exposures from 1 to {S4_ACCUMULATE_MAX}")
            k = int(k)
            try:
                t0, t1, t = float(block["t0_s"]), float(block["t1_s"]), float(record["t"])
            except (KeyError, TypeError, ValueError):
                return fail("the record lacks t, t0_s or t1_s")
            if not (t0 - 1e-9 <= t <= t1 + 1e-9):
                return fail(f"the capture instant {t:g} s is outside the window [{t0:g}, {t1:g}] s")
            exposure = block.get("exposure_s")
            if isinstance(exposure, (int, float)) and abs((t1 - t0) - float(exposure)) > 1e-9 * max(1.0, t1):
                return fail(f"the window is {t1 - t0:g} s long, not the {float(exposure):g} s exposure")
            times = block.get("sub_frame_times_s")
            if times is not None:
                if not isinstance(times, list) or len(times) != k:
                    return fail(f"{len(times) if isinstance(times, list) else times!r} sub-exposure "
                                f"instant(s) recorded for k = {k}")
                for j, value in enumerate(times):
                    midpoint = t0 + (j + 0.5) * (t1 - t0) / k
                    if not isinstance(value, (int, float)) or abs(float(value) - midpoint) > 1e-9 * max(1.0, t1):
                        return fail(f"sub-exposure {j} at {value!r} s is not the midpoint {midpoint:g} s of "
                                    f"its slice")
            predicted, requested = block.get("predicted_blur_px"), block.get("requested_k")
            if isinstance(predicted, (int, float)) and isinstance(requested, (int, float)):
                wanted = 1 if float(predicted) < S4_SUB_PIXEL_BLUR_PX else int(requested)
                if k != wanted:
                    return fail(f"k = {k} with {float(predicted):.3f} px of predicted blur and {int(requested)} "
                                f"asked for: the 0.25 px rule gives {wanted}")
            if block.get("file"):
                if record.get("linear") != block["file"]:
                    return fail(f"the accumulation {block['file']!r} is not the record's linear file "
                                f"{record.get('linear')!r}")
                if not (folder / str(block["file"])).is_file():
                    raise BundleFileError(_unreadable(folder / str(block["file"]),
                                                      FileNotFoundError(str(block["file"]))))
            graded += 1
            single += int(k == 1)
    if graded == 0:
        return Check("engine_accumulation", NOT_RUN,
                     "no render.json frame record carries an accumulation (render on Windows with "
                     "-accumulate=K to exercise this)")
    return Check("engine_accumulation", PASS,
                 f"{graded} accumulated frame(s), {single} at k = 1 under the 0.25 px rule: windows, "
                 f"instants and counts consistent")


# -- S3: the IR proxy declares itself ---------------------------------------------

FAIL_IR_PROXY = "annotation.ir_proxy"


def verify_ir_proxy_declared(manifest: Dict, run_dir=None) -> Check:
    """Every IR frame (``frames/<camera>/frame_NNNN_ir.f32``) carries its
    declaration ``frame_NNNN_ir.json`` with ``proxy`` true, the manifest's
    band, the manifest's ``sensing.ir.tables_sha256`` table for table,
    and the sha256 and size of the image it sits beside -- read here with
    hashlib and json, nothing from the producer. NOT RUN without a run
    directory or an IR frame; FAIL annotation.ir_proxy otherwise."""
    blocks = {}
    for block in manifest.get("cameras", []) or []:
        sensing = block.get("sensing") if isinstance(block, dict) else None
        if isinstance(sensing, dict) and isinstance(sensing.get("ir"), dict):
            blocks[str(block.get("camera_id"))] = sensing["ir"]
    if run_dir is None:
        return Check("ir_proxy_declared", NOT_RUN, "no run directory: no IR frame is here")
    images = sorted((Path(run_dir) / "frames").glob("*/frame_*_ir.f32"))
    if not images:
        return Check("ir_proxy_declared", NOT_RUN,
                     f"no IR frame under frames/ ({len(blocks)} camera(s) declare sensing.ir; the "
                     f"proxy is written after a render's ID image and depth exist)")
    for image in images:
        camera = image.parent.name
        where = f"{camera}/{image.name}"
        block = blocks.get(camera)
        if block is None:
            return Check("ir_proxy_declared", FAIL,
                         f"{where}: an IR frame for a camera whose manifest declares no sensing.ir block",
                         failure=FAIL_IR_PROXY)
        declaration_path = image.with_suffix(".json")
        try:
            declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Check("ir_proxy_declared", FAIL,
                         f"{where}: no readable proxy declaration {declaration_path.name} beside it",
                         failure=FAIL_IR_PROXY)
        if not isinstance(declaration, dict) or declaration.get("proxy") is not True \
                or block.get("proxy") is not True:
            return Check("ir_proxy_declared", FAIL,
                         f"{where}: the frame or its camera block does not declare proxy: true",
                         failure=FAIL_IR_PROXY)
        if declaration.get("band") != block.get("band"):
            return Check("ir_proxy_declared", FAIL,
                         f"{where}: declared band {declaration.get('band')!r}, the manifest's is "
                         f"{block.get('band')!r}", failure=FAIL_IR_PROXY)
        declared = declaration.get("tables_sha256")
        expected = block.get("tables_sha256")
        if not isinstance(declared, dict) or not isinstance(expected, dict) or declared != expected:
            roles = sorted(set(declared or {}) | set(expected or {}))
            differ = [r for r in roles if (declared or {}).get(r) != (expected or {}).get(r)]
            return Check("ir_proxy_declared", FAIL,
                         f"{where}: the tables' sha256s differ from the manifest's "
                         f"({', '.join(differ) or 'no tables declared'})", failure=FAIL_IR_PROXY)
        data = image.read_bytes()
        try:
            size = int(declaration["width_px"]) * int(declaration["height_px"]) * 4
        except (KeyError, TypeError, ValueError):
            size = -1
        if hashlib.sha256(data).hexdigest() != declaration.get("sha256") or len(data) != size:
            return Check("ir_proxy_declared", FAIL,
                         f"{where}: the image's sha256 or size is not the one its declaration records",
                         failure=FAIL_IR_PROXY)
    return Check("ir_proxy_declared", PASS,
                 f"{len(images)} IR frame(s) declare proxy: true, the manifest's band and every "
                 f"table's sha256 ({len(next(iter(blocks.values())).get('tables_sha256') or {})} "
                 f"tables), and their own digest")


# -- P7: the wake-vortex pair's selftest vectors -------------------------------

#: How far the checker's own evaluation of the card's field may sit from
#: the card's vectors, and a host's from the card's: 1e-9 m/s and rad/s
#: (the blueprint's bound; two IEEE-754 evaluations of one closed form).
WAKE_SELFTEST_TOL = 1e-9
FAIL_WAKE = "check.wake_selftest"
WAKE_SELFTEST_KEYS = ("y_m", "z_m", "age_s", "u_mps", "v_mps", "w_mps", "p_eq_rad_s")


def _wake_vortex_speed(r, gamma, r_c):
    """Burnham-Hallock, written from the definition: Gamma/(2 pi r) x r^2/(r^2 + r_c^2)."""
    return gamma * r / (2.0 * math.pi * (r * r + r_c * r_c))


def _wake_pair(y, z, gamma, b_0, r_c):
    """(v, w_up) of the pair: starboard (+b_0/2) counter-clockwise seen from
    behind, port (-b_0/2) clockwise; y right, z up."""
    v = w = 0.0
    for y0, sign in ((0.5 * b_0, 1.0), (-0.5 * b_0, -1.0)):
        dy, dz = y - y0, z
        r = math.hypot(dy, dz)
        if r > 0.0:
            s = _wake_vortex_speed(r, gamma, r_c)
            v += sign * s * (-dz / r)
            w += sign * s * (dy / r)
    return v, w


def _wake_p_eq(y, z, gamma, b_0, r_c, span):
    """(12/b^3) int w_up(y + s) s ds over the span by 32-point Gauss-Legendre
    (numpy's nodes; the producer's rule of the same order, re-written)."""
    import numpy as np

    nodes, weights = np.polynomial.legendre.leggauss(32)
    total = 0.0
    for x, wt in zip(nodes, weights):
        s = 0.5 * span * float(x)
        total += float(wt) * s * _wake_pair(y + s, z, gamma, b_0, r_c)[1]
    return 12.0 / span ** 3 * total * 0.5 * span


def verify_wake_selftest(manifest: Dict, run_dir=None) -> Check:
    """The run card's ``wake`` block against the checker's own evaluation
    of the same closed forms: for each of the five selftest vectors, u = 0,
    (v, w down) from the checker's Burnham-Hallock pair at the card's
    Gamma at the age, b_0 and r_c, and p_eq from the checker's own
    strip-theory quadrature over the card's own span, each within
    WAKE_SELFTEST_TOL; then, where a render host wrote
    ``environment.wake_selftest`` into a render.json (P9), the host's
    vectors against the card's within the same bound. NOT RUN without a
    run directory, a card.json or a wake block (no wake was stated), and
    the host half is reported NOT RUN inside the detail when no render.json
    carries the key. FAIL (check.wake_selftest) on a block missing a key,
    a vector that does not reproduce, or a host vector that differs. What
    is NOT checked: Gamma_0 itself against the generator's weight (the card
    states it; the generator's data are the producer's), the decay's
    history (the card's circulation at the age is taken as stated), and
    that the field reached the aircraft (the delivery is the run's own
    read-back)."""
    if run_dir is None:
        return Check("wake_selftest", NOT_RUN, "no run directory: no card to read")
    card_path = Path(run_dir) / "card.json"
    if not card_path.is_file():
        return Check("wake_selftest", NOT_RUN, "no card.json in the run directory")
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("wake_selftest", FAIL, f"card.json could not be read: {exc}", FAIL_WAKE)
    wake = card.get("wake") if isinstance(card, dict) else None
    if not isinstance(wake, dict):
        return Check("wake_selftest", NOT_RUN, "the card states no wake: nothing to re-evaluate")
    try:
        b_0 = float(wake["b_0"])
        r_c = float(wake["r_c"])
        gamma = float(wake["decay"]["gamma_at_age_0_m2_s"])
        span = float(wake["geometry"]["own_span_m"])
        vectors = list(wake["selftest"])
    except (KeyError, TypeError, ValueError) as exc:
        return Check("wake_selftest", FAIL,
                     f"the wake block lacks a key the re-evaluation needs: {exc!r}", FAIL_WAKE)
    if len(vectors) != 5 or any(tuple(v) != WAKE_SELFTEST_KEYS for v in vectors):
        return Check("wake_selftest", FAIL,
                     f"the selftest is not five vectors of {list(WAKE_SELFTEST_KEYS)}", FAIL_WAKE)
    worst = 0.0
    for vector in vectors:
        y, z = float(vector["y_m"]), float(vector["z_m"])
        v, w_up = _wake_pair(y, z, gamma, b_0, r_c)
        own = {"u_mps": 0.0, "v_mps": v, "w_mps": -w_up,
               "p_eq_rad_s": _wake_p_eq(y, z, gamma, b_0, r_c, span)}
        for key, value in own.items():
            worst = max(worst, abs(float(vector[key]) - value))
    if worst > WAKE_SELFTEST_TOL:
        return Check("wake_selftest", FAIL,
                     f"the card's selftest vectors differ from the checker's own Burnham-Hallock "
                     f"pair and strip-theory quadrature by up to {worst:.3e} (bound "
                     f"{WAKE_SELFTEST_TOL:g})", FAIL_WAKE)
    host_worst = None
    host_files = 0
    for path in sorted(Path(run_dir).rglob("render.json")):
        try:
            render = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        host = (render.get("environment") or {}).get("wake_selftest") if isinstance(render, dict) else None
        if not isinstance(host, list):
            continue
        host_files += 1
        if len(host) != len(vectors):
            return Check("wake_selftest", FAIL,
                         f"{path.name} carries {len(host)} host vectors for the card's "
                         f"{len(vectors)}", FAIL_WAKE)
        for ours, theirs in zip(vectors, host):
            for key in ("u_mps", "v_mps", "w_mps", "p_eq_rad_s"):
                try:
                    diff = abs(float(ours[key]) - float(theirs[key]))
                except (KeyError, TypeError, ValueError):
                    return Check("wake_selftest", FAIL,
                                 f"{path.name}'s host vector lacks {key}", FAIL_WAKE)
                host_worst = diff if host_worst is None else max(host_worst, diff)
    if host_worst is not None and host_worst > WAKE_SELFTEST_TOL:
        return Check("wake_selftest", FAIL,
                     f"the render host's wake selftest differs from the card's vectors by up to "
                     f"{host_worst:.3e} (bound {WAKE_SELFTEST_TOL:g})", FAIL_WAKE)
    return Check("wake_selftest", PASS,
                 f"five vectors re-evaluated by the checker's own pair and quadrature, worst "
                 f"{worst:.3e}; host half "
                 + ("NOT RUN (no render.json carries environment.wake_selftest: the host port "
                    "is a Windows step)" if host_worst is None else
                    f"PASS over {host_files} render.json, worst {host_worst:.3e}"))


# -- P9: the physics blocks as the render host reports them ----------------------

FAIL_HOST_PHYSICS = "check.host_physics"
#: The render.json ``environment`` keys the engine side adds (P9), each
#: graded against the run's card.json ONLY when a render.json carries it
#: (``wake_selftest`` is check.wake_selftest's).
HOST_PHYSICS_KEYS = ("atmosphere_delivery", "loading_applied", "loading_readback_cg_in",
                     "failure_schedule_applied", "gust_delivery", "gust_rows_applied",
                     "derived_aircraft_sha256", "layered_wind", "icing_applied")
#: Slack on the failure timing's one-step window: the host's run clock is
#: read back through JSBSim's property text, so a write landing exactly on
#: a step boundary may read a hair either side of it.
HOST_FAILURE_SLACK_S = 1e-9


def _host_number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def verify_host_physics(manifest: Dict, run_dir=None) -> Check:
    """What the render host says it applied from the card's physics blocks
    (FlightSimScenarioWorld::AppendEnvironmentReport), graded against the
    run's own card.json key by key, each ONLY when a render.json carries it:
    ``atmosphere_delivery`` needs the card's atmosphere block;
    ``loading_applied`` must be true and ``loading_readback_cg_in`` within
    the card's ``tolerance_in`` of ``expected_cg_in``; every
    ``failure_schedule_applied[]`` entry names the card's event in order and
    landed at the first step at or past ``at_s`` (0 <= t_applied - at_s <
    one step; null only for an event past the card's duration);
    ``gust_delivery`` is 'wake_port' when the card carries a wake, 'table'
    when it carries a gust table alone, with ``gust_rows_applied`` between 1
    and the table's rows (0 without a table); ``derived_aircraft_sha256``
    equals the card's xml_sha256 and, where the manifest records a
    derivation, its derived_sha256; ``layered_wind`` names the card's
    profile kind; ``icing_applied`` is true with an icing block on the card.
    NOT RUN without a run directory, a card.json, or any render.json
    carrying one of the keys (the engine side is a Windows step) -- never a
    pass on absence. FAIL (check.host_physics) on the first disagreement.
    What is NOT checked: that the values reached the FDM (the host's own
    read-back and telemetry are), and the wake vectors (check.wake_selftest)."""
    if run_dir is None:
        return Check("host_physics", NOT_RUN, "no run directory: no card to read")
    card_path = Path(run_dir) / "card.json"
    if not card_path.is_file():
        return Check("host_physics", NOT_RUN, "no card.json in the run directory")
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("host_physics", FAIL, f"card.json could not be read: {exc}",
                     FAIL_HOST_PHYSICS)
    if not isinstance(card, dict):
        return Check("host_physics", FAIL, "card.json does not hold a card object",
                     FAIL_HOST_PHYSICS)
    reports = []
    for path in sorted(Path(run_dir).rglob("render.json")):
        try:
            render = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        env = render.get("environment") if isinstance(render, dict) else None
        if isinstance(env, dict) and any(key in env for key in HOST_PHYSICS_KEYS):
            reports.append((path, env))
    if not reports:
        return Check("host_physics", NOT_RUN,
                     "no render.json carries the engine's physics keys: the engine side "
                     "is a Windows step")
    rate = _host_number(card.get("rate_hz"))
    step = 1.0 / rate if rate and rate > 0.0 else None
    duration = _host_number(card.get("duration_s"))
    derivation = ((manifest.get("fdm") or {}).get("derivation") or {}) if isinstance(
        manifest, dict) else {}
    graded = 0

    def fail(where: str, why: str) -> Check:
        return Check("host_physics", FAIL, f"{where}: {why}", FAIL_HOST_PHYSICS)

    for path, env in reports:
        where = path.relative_to(Path(run_dir)).as_posix()
        if "atmosphere_delivery" in env:
            graded += 1
            if not isinstance(card.get("atmosphere_properties"), dict):
                return fail(where, "the host reports a stated day the card does not carry")
            if not isinstance(env["atmosphere_delivery"], str) or not env["atmosphere_delivery"]:
                return fail(where, "atmosphere_delivery is not a sentence")
        if "loading_applied" in env or "loading_readback_cg_in" in env:
            graded += 1
            block = card.get("loading_properties")
            if not isinstance(block, dict):
                return fail(where, "the host reports a loading the card does not carry")
            expected = _host_number(block.get("expected_cg_in"))
            tolerance = _host_number(block.get("tolerance_in"))
            read = _host_number(env.get("loading_readback_cg_in"))
            if env.get("loading_applied") is not True:
                return fail(where, "the host did not apply the card's loading")
            if expected is None or tolerance is None or read is None:
                return fail(where, "the loading's read-back or the card's expected centre of "
                                   "gravity is not a number")
            if abs(read - expected) > tolerance:
                return fail(where, f"the host's centre of gravity {read:.4f} in is "
                                   f"{abs(read - expected):.4f} in from the card's "
                                   f"{expected:.4f} in (tolerance {tolerance:g} in)")
        if "failure_schedule_applied" in env:
            graded += 1
            block = card.get("failure_schedule")
            events = block.get("events") if isinstance(block, dict) else None
            applied = env["failure_schedule_applied"]
            if not isinstance(events, list) or not isinstance(applied, list):
                return fail(where, "failure_schedule_applied has no card schedule to answer")
            if len(applied) != len(events):
                return fail(where, f"{len(applied)} applied entries for the card's "
                                   f"{len(events)} events")
            for index, (event, entry) in enumerate(zip(events, applied)):
                if not isinstance(entry, dict) or not isinstance(event, dict):
                    return fail(where, f"failure entry {index} is not an object")
                if (entry.get("kind") != event.get("kind")
                        or str(entry.get("target")) != str(event.get("target"))
                        or _host_number(entry.get("at_s")) != _host_number(event.get("at_s"))):
                    return fail(where, f"failure entry {index} is not the card's event {index}")
                at_s = _host_number(event.get("at_s"))
                t_applied = _host_number(entry.get("t_applied_s"))
                if t_applied is None:
                    if entry.get("t_applied_s") is None and duration is not None \
                            and at_s is not None and at_s >= duration:
                        continue
                    return fail(where, f"failure entry {index} was never applied inside the run")
                if step is None or at_s is None:
                    return fail(where, "the card states no rate or no event time to judge "
                                       "the timing by")
                late = t_applied - at_s
                if late < -HOST_FAILURE_SLACK_S or late >= step - HOST_FAILURE_SLACK_S:
                    return fail(where, f"failure entry {index} landed at {t_applied:.6f} s for "
                                       f"at_s {at_s:g} s, not within the first step at or past it")
        if "gust_delivery" in env or "gust_rows_applied" in env:
            graded += 1
            expected_delivery = ("wake_port" if isinstance(card.get("wake"), dict) else
                                 "table" if isinstance(card.get("gust_table"), dict) else None)
            if env.get("gust_delivery") != expected_delivery:
                return fail(where, f"gust_delivery {env.get('gust_delivery')!r}, the card "
                                   f"asks for {expected_delivery!r}")
            rows_applied = env.get("gust_rows_applied")
            table = card.get("gust_table")
            rows = table.get("rows") if isinstance(table, dict) else None
            if isinstance(rows_applied, bool) or not isinstance(rows_applied, int):
                return fail(where, "gust_rows_applied is not a whole number")
            if isinstance(rows, list):
                if not 1 <= rows_applied <= len(rows):
                    return fail(where, f"{rows_applied} gust rows applied from a "
                                       f"{len(rows)}-row table")
            elif rows_applied != 0:
                return fail(where, f"{rows_applied} gust rows applied with no table on the card")
        if "derived_aircraft_sha256" in env:
            graded += 1
            block = card.get("derived_aircraft")
            if not isinstance(block, dict):
                return fail(where, "the host reports a derived airframe the card does not name")
            logged = env["derived_aircraft_sha256"]
            if logged != block.get("xml_sha256"):
                return fail(where, f"the host's XML hash {str(logged)[:16]} is not the card's "
                                   f"{str(block.get('xml_sha256'))[:16]}")
            recorded = derivation.get("derived_sha256") if isinstance(derivation, dict) else None
            if recorded is not None and recorded != logged:
                return fail(where, f"the host's XML hash {str(logged)[:16]} is not the "
                                   f"manifest's derived_sha256 {str(recorded)[:16]}")
        if "layered_wind" in env:
            graded += 1
            block = card.get("layered_wind")
            if not isinstance(block, dict) or env["layered_wind"] != block.get("kind"):
                return fail(where, f"layered_wind {env['layered_wind']!r} is not the card's "
                                   f"profile kind")
        if "icing_applied" in env:
            graded += 1
            if not isinstance(card.get("icing_schedule"), dict):
                return fail(where, "the host reports icing the card does not carry")
            if env["icing_applied"] is not True:
                return fail(where, "the host did not apply the card's icing schedule")
    return Check("host_physics", PASS,
                 f"{graded} engine report(s) over {len(reports)} render.json agree with the "
                 f"card; the engine's own read-backs are the Windows steps")


# -- R2: the record's own checks and the FDM-rate instruments --------------------

FAIL_READBACK = "record.readback"
FAIL_NULL_EFFECT = "annotation.null_effect"
FAIL_UNCERTAINTY = "check.uncertainty_present"
#: The re-computed root sum square must equal the stated u_val to this
#: relative tolerance (the block lists every term).
UNCERTAINTY_RSS_TOL = 1e-9


def _applied_records(manifest: Dict):
    """The record-1 applied_variables list, or None."""
    block = manifest.get("applied_variables")
    if not isinstance(block, dict) or block.get("record_version") != 1:
        return None
    records = block.get("applied_variables")
    return records if isinstance(records, list) else None


def verify_applied_readback(manifest: Dict) -> Check:
    """Every applied-variable record that carries a readback agrees with
    the value it wrote, re-graded here from the record's own numbers
    (|value - written| against the tolerance, absolute or relative to
    |written|) and never from its ``agrees`` flag alone; a record whose
    flag contradicts the arithmetic fails too. NOT RUN without a
    record-1 block or when no record carries a readback."""
    records = _applied_records(manifest)
    if records is None:
        return Check("applied_readback", NOT_RUN,
                     "no applied_variables block (record_version 1) in the manifest")
    checked, problems = 0, []
    for record in records:
        readback = record.get("readback") if isinstance(record, dict) else None
        if not isinstance(readback, dict):
            continue
        checked += 1
        name = record.get("name")
        try:
            value = float(readback["value"])
            written = float(readback["written"])
            tolerance = float(readback["tolerance"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"{name}: a readback without value, written and tolerance")
            continue
        allowed = tolerance * abs(written) if readback.get("tolerance_kind") == "relative" else tolerance
        if not (math.isfinite(value) and math.isfinite(written)) or abs(value - written) > allowed:
            problems.append(f"{name}: {readback.get('property')} wrote {written!r} and read "
                            f"{value!r} (tolerance {tolerance!r} {readback.get('tolerance_kind')})")
        elif readback.get("agrees") is not True:
            problems.append(f"{name}: the readback agrees by arithmetic but the record says it "
                            f"does not")
    if checked == 0:
        return Check("applied_readback", NOT_RUN,
                     f"{len(records)} record(s), none carrying a readback")
    if problems:
        return Check("applied_readback", FAIL,
                     f"{len(problems)} of {checked} readback(s) disagree: " + "; ".join(problems[:3]),
                     failure=FAIL_READBACK)
    return Check("applied_readback", PASS,
                 f"{checked} readback(s) re-graded from their own numbers, every one within "
                 f"its stated tolerance")


def verify_null_effect(manifest: Dict) -> Check:
    """Every applied-variable record with a null test carries a verdict
    the checker can re-grade: ``ok`` must equal the arithmetic of its
    kind (reached: |with - without| >= threshold; bounded: <= threshold),
    and a null PAIR's verdict (reached / silent / ungraded) must agree
    with that ``ok``. The rule for silence: a ``silent`` verdict is an
    honest measurement and passes; it FAILS by name only when the record
    CLAIMS OTHERWISE -- ``ok`` true, or a ``reached`` verdict, beside a
    difference below the threshold. NOT RUN without a record-1 block or
    a null test."""
    records = _applied_records(manifest)
    if records is None:
        return Check("null_effect", NOT_RUN,
                     "no applied_variables block (record_version 1) in the manifest")
    checked, silent, problems = 0, [], []
    for record in records:
        null = record.get("null_test") if isinstance(record, dict) else None
        if not isinstance(null, dict):
            continue
        checked += 1
        name = record.get("name")
        try:
            difference = abs(float(null["with"]) - float(null["without"]))
            threshold = float(null["threshold"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"{name}: a null test without with, without and threshold")
            continue
        kind = null.get("kind", "reached")
        if kind not in ("reached", "bounded"):
            problems.append(f"{name}: null test kind {kind!r} is not reached or bounded")
            continue
        arithmetic = difference <= threshold if kind == "bounded" else difference >= threshold
        if null.get("ok") is not arithmetic:
            problems.append(f"{name}: ok {null.get('ok')!r} contradicts |{null.get('with')!r} - "
                            f"{null.get('without')!r}| against {threshold!r} ({kind})")
            continue
        verdict = null.get("verdict")
        if verdict is None:
            continue
        if verdict not in ("reached", "silent", "ungraded"):
            problems.append(f"{name}: verdict {verdict!r} is not reached, silent or ungraded")
        elif verdict == "silent":
            silent.append(str(name))
            if arithmetic and kind == "reached":
                problems.append(f"{name}: the pair reads silent yet the record claims the "
                                f"threshold was reached")
        elif verdict == "reached" and not arithmetic and kind == "reached":
            problems.append(f"{name}: the pair reads reached yet the record's difference "
                            f"{difference!r} is below its threshold {threshold!r}")
    if checked == 0:
        return Check("null_effect", NOT_RUN, f"{len(records)} record(s), none carrying a null test")
    if problems:
        return Check("null_effect", FAIL,
                     f"{len(problems)} of {checked} null test(s) contradict their own numbers: "
                     + "; ".join(problems[:3]), failure=FAIL_NULL_EFFECT)
    return Check("null_effect", PASS,
                 f"{checked} null test(s) re-graded from their own numbers; every verdict "
                 f"agrees" + (f"; {len(silent)} honest silence(s): {', '.join(silent[:5])}" if silent else ""))


def verify_instrument_allan(manifest: Dict, run_dir=None) -> Check:
    """instruments.npz's IMU residuals against the profile's white density
    by the checker's own OVERLAPPING Allan deviation (core/telemetry/
    instruments_check.py, which imports nothing from the producer). NOT
    RUN without the file (the default ideal set) or a stated IMU."""
    from ..telemetry.instruments_check import check_allan

    result = check_allan(manifest, run_dir)
    return Check("instrument_allan", result.status, result.detail, result.failure)


def verify_instrument_lever_arm(manifest: Dict, run_dir=None) -> Check:
    """The GPS antenna arm recovered from the fix residuals and the IMU arm
    from the specific-force difference against the manifest's declared
    arms (core/telemetry/instruments_check.py). NOT RUN without the file,
    a stated instrument or a rotating track."""
    from ..telemetry.instruments_check import check_lever_arm

    result = check_lever_arm(manifest, run_dir)
    return Check("instrument_lever_arm", result.status, result.detail, result.failure)


def verify_uncertainty_present(manifest: Dict) -> Check:
    """The optional ``uncertainty`` block (R1, core/uncertainty.py): its
    form is stated, u_num carries a finite value or a stated NOT RUN
    basis per SRQ, and every u_val is the root sum square of the terms
    it lists (re-computed here). NOT RUN without the block -- absence is
    never a pass."""
    block = manifest.get("uncertainty")
    if block is None:
        return Check("uncertainty_present", NOT_RUN,
                     "no uncertainty block: the capture did not run the dt/2 twin "
                     "(--uncertainty or record.sensitivity_pairs)")
    if not isinstance(block, dict) or not block.get("form"):
        return Check("uncertainty_present", FAIL, "the uncertainty block states no form",
                     failure=FAIL_UNCERTAINTY)
    u_num = (block.get("u_num") or {}).get("srq")
    u_val = block.get("u_val")
    if not isinstance(u_num, dict) or not isinstance(u_val, dict):
        return Check("uncertainty_present", FAIL, "the uncertainty block lacks u_num.srq or u_val",
                     failure=FAIL_UNCERTAINTY)
    problems, graded = [], 0
    for srq, part in u_num.items():
        value = part.get("value") if isinstance(part, dict) else None
        if value is None:
            if not str((part or {}).get("basis", "")).startswith("NOT RUN"):
                problems.append(f"u_num {srq}: no value and no NOT RUN basis")
            continue
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0.0:
            problems.append(f"u_num {srq}: {value!r} is not a finite non-negative number")
    for srq, part in u_val.items():
        if not isinstance(part, dict):
            problems.append(f"u_val {srq}: not a block")
            continue
        stated = part.get("value")
        num = part.get("u_num")
        terms = part.get("u_input_terms") or {}
        if stated is None:
            continue
        if num is None or any(v is None for v in terms.values()):
            problems.append(f"u_val {srq}: a value with a missing term")
            continue
        rss = math.sqrt(float(num) ** 2 + sum(float(v) ** 2 for v in terms.values()))
        graded += 1
        if abs(rss - float(stated)) > UNCERTAINTY_RSS_TOL * max(1.0, abs(rss)):
            problems.append(f"u_val {srq}: stated {stated!r}, the root sum square of its terms is {rss!r}")
    if problems:
        return Check("uncertainty_present", FAIL, "; ".join(problems[:3]), failure=FAIL_UNCERTAINTY)
    return Check("uncertainty_present", PASS,
                 f"form {block.get('form')!r}; {len(u_num)} u_num SRQ(s) finite or stated NOT RUN; "
                 f"{graded} u_val(s) equal the root sum square of their listed terms")


# -- W2: the buildings against their footprints, the runway raster against its plane ----
#
# Both checks read the world documents the manifest's scene block names
# (scene.buildings -> the <bake>_buildings.json; scene.runway -> the pad's
# _record.json and its markings PNG), hold each file to the sha256 the
# manifest recorded, and grade it with THIS module's own geometry: nothing
# from core/scene runs here. Grid metres are read flat (a manifest position
# is an offset in the scene's projected CRS about the frame's origin; the
# host's round-planet ENU differs from it by the grid scale factor -- 0.1 %
# of range at the example origin, see scene_to_enu -- which the
# depth-proportional tolerance below absorbs: stated, not measured on an
# engine frame). Each reports NOT RUN without its evidence and never passes
# on absence.

#: building_vs_footprint: a building pixel carried back into the scene
#: through its depth may sit this far outside its footprint prism
#: (horizontally, or below the seat / above the roof), plus
#: BUILDING_TOL_DEPTH_FRACTION of its depth (the depth's own quantisation
#: and the flat grid reading grow with range) ...
BUILDING_TOL_M = 1.0
BUILDING_TOL_DEPTH_FRACTION = 0.01
#: ... and this fraction of a frame's building pixels may miss every prism
#: (silhouette edge pixels; the 3 % visibility_vs_scene tolerates).
BUILDING_OUTSIDE_TOL_FRACTION = 0.03
#: At most this many building pixels are carried back per frame (a
#: deterministic stride over the rest, stated in the detail).
BUILDING_MAX_PIXELS = 20000
BUILDING_ALL_ID = "building:all"
FAIL_BUILDING = "check.building_vs_footprint"

#: runway_vs_geometry: the raster's threshold, placed on the runway plane,
#: may project this many pixels from the runway's own threshold (the
#: blueprint's Windows step 8 bound on the runway mask residual).
RUNWAY_RESIDUAL_TOL_PX = 2.0
#: The checker's own copy of the Annex 14 5.2.4 threshold stripes (from
#: memory, unverified here, as the producer's): they start 6 m past the
#: threshold and run 30 m; the count is the largest width row not above
#: the runway's width.
RUNWAY_STRIPE_START_M = 6.0
RUNWAY_STRIPE_LENGTH_M = 30.0
RUNWAY_STRIPES_BY_WIDTH = ((18.0, 4), (23.0, 6), (30.0, 8), (45.0, 12), (60.0, 16))
#: The raster's resolution, metres per pixel.
RUNWAY_PX_M = 0.1
#: The threshold re-projected here from the spec's latitude and longitude
#: may sit this far from the document's geometry (a representation bound).
RUNWAY_GEOMETRY_TOL_M = 0.01
FAIL_RUNWAY = "check.runway_vs_geometry"


def _world_file(where, run_dir) -> Optional[Path]:
    """A file a world block names: the recorded path, else the same name
    inside the run directory; None when neither is on this machine."""
    if not where:
        return None
    path = Path(str(where))
    if path.is_file():
        return path
    if run_dir is not None and (Path(run_dir) / path.name).is_file():
        return Path(run_dir) / path.name
    return None


def _world_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _frame_grid_origin(manifest: Dict):
    """(crs, origin_x_m, origin_y_m) of the manifest's frame, or None."""
    frame = manifest.get("frame")
    if not isinstance(frame, dict):
        return None
    try:
        return str(frame["crs"]), float(frame["origin_x_m"]), float(frame["origin_y_m"])
    except (KeyError, TypeError, ValueError):
        return None


def _ring_distance(xs, ys, ring):
    """Horizontal distance from each point to a footprint ring: 0 inside
    (even-odd rule), else to the nearest edge. Vectorised, written here."""
    import numpy as np

    inside = np.zeros(xs.shape, dtype=bool)
    best = np.full(xs.shape, np.inf)
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        crosses = (y0 > ys) != (y1 > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_cross = x0 + (ys - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (xs < x_cross)
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        t = (np.zeros(xs.shape) if length2 <= 0.0
             else np.clip(((xs - x0) * dx + (ys - y0) * dy) / length2, 0.0, 1.0))
        best = np.minimum(best, np.hypot(xs - (x0 + t * dx), ys - (y0 + t * dy)))
    return np.where(inside, 0.0, best)


@_reads_the_bundle
def verify_building_vs_footprint(manifest: Dict, run_dir=None) -> Check:
    """The building pixels of the ID image against the cached footprints.

    The manifest's ``scene.buildings`` block names the buildings document
    (its sha256 held to the manifest's) and ``objects[]`` the one
    ``building:all`` id. Per labelled frame, two clauses by this module's
    own unprojection: (1) every building pixel, carried back into the
    scene through its depth along its own ray, lies inside some footprint
    prism -- the ring, from the block's seat to its roof -- within
    BUILDING_TOL_M + BUILDING_TOL_DEPTH_FRACTION x depth, all but
    BUILDING_OUTSIDE_TOL_FRACTION of them; (2) every roof centre that
    projects into the frame with the depth there agreeing with it (visible,
    not occluded) carries the building id within one pixel, and no roof
    centre the depth sees past (a block the footprints put there and the
    render did not draw). FAIL (check.building_vs_footprint) on a document
    that changed, a frame or CRS mismatch, a stated set with no
    building:all object, either clause. NOT RUN without a footprint set
    (no scene.buildings, or its document not on this machine), without an
    ID image and depth, or with no building in view. What is NOT checked:
    per-building identity (the 8-bit stencil carries one aggregate id), a
    roof shape beyond LoD1, the pad seat against a surveyed DTM."""
    name = "building_vs_footprint"
    block = (manifest.get("scene") or {}).get("buildings")
    if not isinstance(block, dict):
        return Check(name, NOT_RUN, "the manifest names no footprint set (no scene.buildings): "
                                    "nothing to carry the ID image back against")
    path = _world_file(block.get("document"), run_dir)
    if path is None:
        return Check(name, NOT_RUN, f"the buildings document {block.get('document')!r} is not on "
                                    f"this machine: no footprint set to grade against")
    digest = _world_sha256(path)
    if digest != block.get("document_sha256"):
        return Check(name, FAIL, f"{path.name}: sha256 {digest[:16]}... is not the manifest's "
                                 f"{str(block.get('document_sha256'))[:16]}...: the footprints "
                                 f"changed after the capture", failure=FAIL_BUILDING)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        crs = str(document["bake"]["crs"])
        prisms = [([(float(p[0]), float(p[1])) for p in b["polygon_xy"]],
                   float(b["pad_seat_m"]), float(b["top_z_m"]),
                   (float(b["centroid_xy"][0]), float(b["centroid_xy"][1])), str(b["id"]))
                  for b in document["buildings"]]
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return Check(name, FAIL, f"{path.name} lacks what the unprojection needs ({exc!r})",
                     failure=FAIL_BUILDING)
    if document.get("sha256") != block.get("sha256"):
        return Check(name, FAIL, f"{path.name} extrudes the footprint file "
                                 f"{str(document.get('sha256'))[:16]}..., the manifest names "
                                 f"{str(block.get('sha256'))[:16]}...", failure=FAIL_BUILDING)
    origin = _frame_grid_origin(manifest)
    if origin is None:
        return Check(name, NOT_RUN, "the manifest declares no projected frame, so the footprints "
                                    "cannot be placed in the scene")
    if origin[0] != crs:
        return Check(name, FAIL, f"the footprints are in {crs}, the manifest's frame in "
                                 f"{origin[0]}", failure=FAIL_BUILDING)
    entries = [o for o in _declared_objects(manifest) if o.get("id") == BUILDING_ALL_ID]
    if not entries:
        return Check(name, FAIL, "the manifest names a footprint set but objects[] declares no "
                                 "building:all object, so the ID image cannot carry it",
                     failure=FAIL_BUILDING)
    int_id = int(entries[0]["int_id"])
    if not _engine_label_records(run_dir):
        return Check(name, NOT_RUN, _no_bundle_reason())
    if not prisms:
        return Check(name, NOT_RUN, f"{path.name} extrudes no building on the bake")
    import numpy as np

    _, ox, oy = origin
    frames = pixels = roofs = 0
    worst = 0.0
    strided = False
    for record, camera, fname, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        if not labels.get("mask"):
            continue
        mask = _read_gray_png(folder / labels["mask"])
        if mask is None:
            return Check(name, NOT_RUN, "Pillow unavailable")
        height, width = mask.shape[:2]
        depth = _read_depth_metres(folder, labels, width, height)
        if isinstance(depth, str):
            continue
        frames += 1
        forward, right, up = axes_from_quat(record["quaternion_wxyz"])
        cx, cy = record["principal_point_px"]
        fx, fy = float(record["fx_px"]), float(record["fy_px"])
        pn, pe, pa = (float(record["position_north_m"]), float(record["position_east_m"]),
                      float(record["position_alt_m"]))
        rows, cols = np.nonzero(mask == int_id)
        if rows.size:
            stride = max(1, int(math.ceil(rows.size / BUILDING_MAX_PIXELS)))
            strided = strided or stride > 1
            rows, cols = rows[::stride], cols[::stride]
            z = depth[rows, cols]
            finite = np.isfinite(z) & (z > 0.0)
            z = np.where(finite, z, 0.0)
            d = (cols + 0.5 - cx) / fx
            e = (rows + 0.5 - cy) / fy
            north = pn + z * (forward[0] + d * right[0] - e * up[0])
            east = pe + z * (forward[1] + d * right[1] - e * up[1])
            alt = pa + z * (forward[2] + d * right[2] - e * up[2])
            xs, ys = ox + east, oy + north
            residual = np.full(z.shape, np.inf)
            for ring, seat, top, _, _ in prisms:
                horizontal = _ring_distance(xs, ys, ring)
                vertical = np.maximum(0.0, np.maximum(seat - alt, alt - top))
                residual = np.minimum(residual, np.maximum(horizontal, vertical))
            residual = np.where(finite, residual, np.inf)
            tol = BUILDING_TOL_M + BUILDING_TOL_DEPTH_FRACTION * z
            miss = residual > tol
            fraction = float(np.count_nonzero(miss)) / float(rows.size)
            graded = residual[np.isfinite(residual)]
            if graded.size:
                worst = max(worst, float(graded.max()))
            pixels += int(rows.size)
            if fraction > BUILDING_OUTSIDE_TOL_FRACTION:
                far = residual[miss]
                far = far[np.isfinite(far)]
                return Check(name, FAIL,
                             f"{camera}/{fname}: {np.count_nonzero(miss)} of {rows.size} building "
                             f"pixels ({fraction:.1%}) land outside every footprint prism "
                             f"(bound {BUILDING_OUTSIDE_TOL_FRACTION:.0%}; "
                             + (f"median miss {float(np.median(far)):.2f} m" if far.size else
                                "no finite depth under them") + ")", failure=FAIL_BUILDING)
        for ring, seat, top, centroid, ident in prisms:
            u, v, zc = project_point(record, (centroid[1] - oy, centroid[0] - ox, top),
                                     (forward, right, up))
            if zc <= 0.0 or not (0.0 <= u < width and 0.0 <= v < height):
                continue
            px, py = int(math.floor(u)), int(math.floor(v))
            seen = float(depth[py, px])
            tol = BUILDING_TOL_M + BUILDING_TOL_DEPTH_FRACTION * zc
            if math.isfinite(seen) and seen < zc - tol:
                continue                            # something nearer hides the roof
            roofs += 1
            if not math.isfinite(seen) or seen > zc + tol:
                return Check(name, FAIL,
                             f"{camera}/{fname}: the roof of {ident} projects to ({u:.1f}, {v:.1f}) "
                             f"at {zc:.1f} m but the depth there sees past it "
                             f"({seen:.1f} m): a block the footprints place is not drawn",
                             failure=FAIL_BUILDING)
            window = mask[max(0, py - 1):py + 2, max(0, px - 1):px + 2]
            if not np.any(window == int_id):
                return Check(name, FAIL,
                             f"{camera}/{fname}: the roof of {ident} is visible at ({u:.1f}, "
                             f"{v:.1f}) but the ID image does not carry building:all "
                             f"({int_id}) there", failure=FAIL_BUILDING)
    if frames == 0:
        return Check(name, NOT_RUN, "no labelled frame declares both an ID image and a depth")
    if pixels == 0 and roofs == 0:
        return Check(name, NOT_RUN, f"no building is in view in {frames} labelled frame(s)")
    return Check(name, PASS,
                 f"{pixels} building pixels over {frames} frame(s) carried back through their "
                 f"depth land in the {len(prisms)} footprint prisms (worst {worst:.2f} m; bound "
                 f"{BUILDING_TOL_M:g} m + {BUILDING_TOL_DEPTH_FRACTION:.0%} of depth, "
                 f"{BUILDING_OUTSIDE_TOL_FRACTION:.0%} of pixels"
                 + ("; a stride over the pixels" if strided else "") + f"); {roofs} visible "
                 f"roof centre(s) carry building:all")


def verify_runway_vs_geometry(manifest: Dict, run_dir=None) -> Check:
    """The runway's marking raster against the runway's own plane.

    The manifest's ``scene.runway`` block names the runway document and
    the markings PNG (each held to the manifest's sha256). The checker
    reads the raster itself: the threshold stripes' first painted row,
    less the stripes' 6 m start, is the raster's threshold offset along
    the runway; the stripe runs across their middle row are counted
    against the checker's own width table; the stripes' painted extent
    gives the raster's offset across. The runway's own threshold is
    re-projected here from the spec's latitude and longitude (held to the
    document's geometry within RUNWAY_GEOMETRY_TOL_M) and oriented by the
    stated heading; both thresholds are placed on the pad's plane and
    projected into every frame that sees them, and the residual in pixels
    is held to RUNWAY_RESIDUAL_TOL_PX. FAIL (check.runway_vs_geometry) on a
    changed document or raster, a raster of the wrong size or resolution,
    a stripe count that is not the width's, a geometry that is not the
    spec's threshold, a residual over the bound. NOT RUN without a runway
    (no scene.runway, or its files not on this machine), without threshold
    stripes to find, or with no frame that sees the threshold. The engine
    half (the drape in a rendered frame) is reported NOT RUN inside the
    detail until a render.json carries a runway mask (a Windows step)."""
    name = "runway_vs_geometry"
    block = (manifest.get("scene") or {}).get("runway")
    if not isinstance(block, dict):
        return Check(name, NOT_RUN, "the manifest names no runway (no scene.runway): nothing to "
                                    "grade")
    path = _world_file(block.get("document"), run_dir)
    raster_path = _world_file(block.get("markings"), run_dir)
    if path is None or raster_path is None:
        return Check(name, NOT_RUN, "the runway document or its markings raster is not on this "
                                    "machine")
    for where, key in ((path, "document_sha256"), (raster_path, "markings_sha256")):
        digest = _world_sha256(where)
        if digest != block.get(key):
            return Check(name, FAIL, f"{where.name}: sha256 {digest[:16]}... is not the "
                                     f"manifest's {str(block.get(key))[:16]}...: the runway "
                                     f"changed after the capture", failure=FAIL_RUNWAY)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        spec = document["spec"]
        geometry = document["geometry"]
        plane = document["pad"]["statistics"]["plane"]
        a, b, c = float(plane["a_m"]), float(plane["b_per_m"]), float(plane["c_per_m"])
        length_m, width_m = float(spec["length_m"]), float(spec["width_m"])
        lat, lon = float(spec["threshold_lat_deg"]), float(spec["threshold_lon_deg"])
        heading = math.radians(float(spec["heading_deg"]))
        crs = str(geometry["crs"])
        doc_x0, doc_y0 = (float(v) for v in geometry["threshold_xy"])
        px_m = float(document["markings"]["measurement"]["px_m"])
        elements = list(spec.get("markings") or [])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return Check(name, FAIL, f"{path.name} lacks what the check needs ({exc!r})",
                     failure=FAIL_RUNWAY)
    if "threshold" not in elements:
        return Check(name, NOT_RUN, "the runway states no threshold stripes: the raster carries "
                                    "no threshold for the checker to find")
    if abs(px_m - RUNWAY_PX_M) > 1e-12:
        return Check(name, FAIL, f"the raster declares {px_m:g} m per pixel, not "
                                 f"{RUNWAY_PX_M:g}", failure=FAIL_RUNWAY)
    import numpy as np

    array = _read_gray_png(raster_path)
    if array is None:
        return Check(name, NOT_RUN, "Pillow unavailable")
    painted = np.asarray(array) > 127
    expected_shape = (int(round(length_m / RUNWAY_PX_M)), int(round(width_m / RUNWAY_PX_M)))
    if painted.ndim != 2 or painted.shape != expected_shape:
        return Check(name, FAIL, f"{raster_path.name} is {list(painted.shape)} pixels; a "
                                 f"{length_m:g} x {width_m:g} m runway at {RUNWAY_PX_M:g} m is "
                                 f"{list(expected_shape)}", failure=FAIL_RUNWAY)
    rows = np.nonzero(painted.any(axis=1))[0]
    if rows.size == 0:
        return Check(name, FAIL, f"{raster_path.name} holds no paint although threshold stripes "
                                 f"are stated", failure=FAIL_RUNWAY)
    first = int(rows[0])
    delta_s = first * RUNWAY_PX_M - RUNWAY_STRIPE_START_M
    middle = painted[min(painted.shape[0] - 1,
                         first + int(round(RUNWAY_STRIPE_LENGTH_M / 2.0 / RUNWAY_PX_M)))]
    starts = middle & ~np.concatenate(([False], middle[:-1]))
    runs = int(np.count_nonzero(starts))
    expected = None
    for row_width, count in RUNWAY_STRIPES_BY_WIDTH:
        if width_m >= row_width:
            expected = count
    if runs != expected:
        return Check(name, FAIL, f"{raster_path.name}: {runs} threshold stripes read across the "
                                 f"stripes' middle row; a {width_m:g} m runway has {expected}",
                     failure=FAIL_RUNWAY)
    columns = np.nonzero(middle)[0]
    delta_t = (float(columns[0] + columns[-1] + 1) / 2.0) * RUNWAY_PX_M - width_m / 2.0
    origin = _frame_grid_origin(manifest)
    if origin is None:
        return Check(name, NOT_RUN, "the manifest declares no projected frame, so the runway "
                                    "cannot be placed in the scene")
    if origin[0] != crs:
        return Check(name, FAIL, f"the runway is placed in {crs}, the manifest's frame is "
                                 f"{origin[0]}", failure=FAIL_RUNWAY)
    try:
        from pyproj import Transformer
    except ImportError:                     # pragma: no cover
        return Check(name, NOT_RUN, "pyproj unavailable: the threshold cannot be re-projected")
    x0, y0 = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    if math.hypot(x0 - doc_x0, y0 - doc_y0) > RUNWAY_GEOMETRY_TOL_M:
        return Check(name, FAIL, f"the document places the threshold "
                                 f"{math.hypot(x0 - doc_x0, y0 - doc_y0):.2f} m from where the "
                                 f"spec's latitude and longitude project", failure=FAIL_RUNWAY)
    along = (math.sin(heading), math.cos(heading))
    across = (math.cos(heading), -math.sin(heading))
    _, ox, oy = origin

    def place(s, t):
        x = x0 + s * along[0] + t * across[0]
        y = y0 + s * along[1] + t * across[1]
        return (y - oy, x - ox, a + b * s + c * t)

    half = width_m / 2.0
    own = [place(0.0, -half), place(0.0, half)]
    drawn = [place(delta_s, -half + delta_t), place(delta_s, half + delta_t)]
    frames = 0
    worst = 0.0
    for record in manifest.get("frames", []):
        if not isinstance(record, dict):
            continue
        try:
            axes = axes_from_quat(record["quaternion_wxyz"])
            width_px = float(record.get("width_px") or 2.0 * record["principal_point_px"][0])
            height_px = float(record.get("height_px") or 2.0 * record["principal_point_px"][1])
            points = [project_point(record, p, axes) for p in own + drawn]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if any(p[2] <= 0.0 for p in points):
            continue
        if not any(0.0 <= p[0] < width_px and 0.0 <= p[1] < height_px for p in points[:2]):
            continue
        frames += 1
        for mine, theirs in zip(points[:2], points[2:]):
            worst = max(worst, math.hypot(mine[0] - theirs[0], mine[1] - theirs[1]))
    if frames == 0:
        return Check(name, NOT_RUN, "no frame sees the runway threshold in front of its camera")
    detail = (f"the raster's threshold (first painted row {first}, offset {delta_s:+.2f} m along, "
              f"{delta_t:+.2f} m across; {runs} stripes for {width_m:g} m) on the pad plane "
              f"projects within {worst:.2f} px of the runway's own threshold over {frames} "
              f"frame(s) (bound {RUNWAY_RESIDUAL_TOL_PX:g} px)")
    if worst > RUNWAY_RESIDUAL_TOL_PX:
        return Check(name, FAIL, detail.replace("projects within", "projects"), failure=FAIL_RUNWAY)
    return Check(name, PASS, detail + "; engine half NOT RUN (no render.json carries a runway "
                                      "mask: the drape is a Windows step)")


# -- S2: the passes as data -- flow, disparity, points, amodal ------------------
#
# The derived passes (core/capture/passes.py; the amodal keys by
# core/capture/labels.py) are graded here from the same files with this
# module's OWN readers, rotation, pinhole and z-test; nothing from the
# producers runs. Each camera's passes.json names every file with its
# sha256, and a file whose bytes are not the ones named fails by the
# pass's name. The neighbouring telemetry samples the flow was computed
# against are the manifest frame's ``passes.neighbours``, cross-checked
# here against the manifest's own frames at those samples and against the
# run card's solved track where the run carries one.

#: flow_vs_keypoints: the flow at a keypoint's pixel against the checker's
#: own prediction for the surface that pixel shows, moved rigidly with the
#: keypoint's aircraft between the two telemetry samples (px).
FLOW_KEYPOINT_TOL_PX = 0.25
#: flow_vs_keypoints: validity bits that may disagree with the checker's
#: own z-test, as a fraction of the surface pixels (float ties at the
#: tolerance and at pixel edges), never fewer than the floor in pixels.
FLOW_BITS_MISMATCH_FRACTION = 0.001
FLOW_BITS_MISMATCH_MIN_PX = 2
#: flow_static_null: the static world under a camera that did not move
#: carries no flow beyond this (an exact zero is exact in float32).
STATIC_NULL_TOL_PX = 1e-3
#: flow_static_null: the static world under a moving camera against the
#: checker's own camera-only flow (px).
STATIC_FLOW_TOL_PX = 0.25
#: Pose differences under which a camera counts as still, and neighbour
#: records agree with the manifest's own (m and quaternion components).
STILL_CAMERA_TOL = 1e-9
NEIGHBOUR_TOL = 1e-9
#: disparity_vs_right_depth: the right camera's centre against the left's
#: plus B along the left's right axis (m; a representation tolerance).
STEREO_RIG_TOL_M = 1e-6
#: disparity_vs_right_depth: the stored disparity against the checker's
#: own f_x B / Z (px; float32 storage).
DISPARITY_FORMULA_TOL_PX = 1e-3
#: disparity_vs_right_depth: the fraction of the left surface pixels whose
#: disparity-shifted right pixel shows the same depth (within the depth
#: tolerance); the rest are occlusions and the image edge.
DISPARITY_RIGHT_AGREE_MIN = 0.9
#: points_vs_depth: a point's reprojection against its pixel centre (px),
#: its z against the depth there (m, plus float32's relative step).
POINTS_REPROJECTION_TOL_PX = 1e-3
POINTS_DEPTH_TOL_M = 1e-3
POINTS_DEPTH_TOL_FRACTION = 1e-6
#: amodal_contains_visible: how far the amodal box may reach outside the
#: projected extents box (bbox_2d_unclipped), px.
AMODAL_BOX_SLACK_PX = 2.0
#: amodal_contains_visible: the record's ratio against the checker's count.
AMODAL_RATIO_TOL = 1e-9

FAIL_DISPARITY = "annotation.disparity"
FAIL_POINTS = "annotation.points"
FAIL_AMODAL = "annotation.amodal"
PASSES_DOCUMENT = "passes.json"
FLOW_BIT_VALID, FLOW_BIT_OCCLUDED, FLOW_BIT_OUT_OF_FRAME = 1, 2, 4


def _no_passes_reason(word: str) -> str:
    return (f"no passes.json names a {word} pass (no camera asks for it in "
            f"cameras[i].passes, or no render): render on Windows with the pass "
            f"asked for to exercise this")


def _passes_documents(run_dir) -> Dict[str, Dict[str, Dict]]:
    """{camera: {frame name: passes.json entry}}, own JSON reader."""
    out: Dict[str, Dict[str, Dict]] = {}
    if run_dir is None:
        return out
    frames_dir = Path(run_dir) / "frames"
    if not frames_dir.is_dir():
        return out
    for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        path = camera_dir / PASSES_DOCUMENT
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BundleFileError(_unreadable(path, OSError(str(exc)))) from exc
        if isinstance(payload, dict) and isinstance(payload.get("frames"), list):
            out[camera_dir.name] = {str(e.get("frame")): e for e in payload["frames"]
                                    if isinstance(e, dict)}
    return out


def _passes_frames(manifest: Dict, run_dir, key: str):
    """Yield (record, camera, name, entry, folder) for every manifest frame
    whose passes.json entry carries ``key``."""
    documents = _passes_documents(run_dir)
    for record in manifest.get("frames", []):
        camera = str(record.get("camera_id"))
        name = Path(str(record.get("file"))).name
        entry = documents.get(camera, {}).get(name)
        if isinstance(entry, dict) and key in entry:
            yield record, camera, name, entry, Path(run_dir) / "frames" / camera


def _passes_file(folder: Path, entry: Dict, key: str):
    """(path, None) for a passes.json-named file whose bytes hash to the
    recorded sha256, else (None, the reason)."""
    item = (entry.get("files") or {}).get(key)
    if not isinstance(item, dict) or not item.get("file"):
        return None, f"passes.json names no {key} file"
    path = folder / str(item["file"])
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BundleFileError(_unreadable(path, exc)) from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != item.get("sha256"):
        return None, (f"{path.name} is not the file passes.json names (sha256 "
                      f"{digest[:16]}.. against {str(item.get('sha256'))[:16]}..)")
    return path, None


def _own_values(path: Path, dtype: str, count: Optional[int]):
    """The file as a flat numpy array of ``dtype``, or None when it does
    not hold ``count`` values."""
    import numpy as np

    raw = np.fromfile(path, dtype=dtype)
    if count is not None and raw.size != count:
        return None
    return raw


def _own_rows(record: Dict):
    """The camera's rows (right, -up, forward) in (north, east, up), from
    this module's own quaternion expansion."""
    import numpy as np

    forward, right, up = axes_from_quat(record["quaternion_wxyz"])
    return np.array([right, [-c for c in up], forward], dtype="float64")


def _own_centre(record: Dict):
    import numpy as np

    return np.array([float(record["position_north_m"]), float(record["position_east_m"]),
                     float(record["position_alt_m"])], dtype="float64")


def _own_body_columns(state: Dict):
    """3 x 3 with the body axes forward, right, down as columns in (north,
    east, up), from this module's own Euler expansion."""
    import numpy as np

    forward, right, up = _aircraft_axes_enu(state)
    return np.array([forward, right, [-c for c in up]], dtype="float64").T


def _own_cg(state: Dict):
    import numpy as np

    return np.array([float(state["north_m"]), float(state["east_m"]),
                     float(state["alt_m"])], dtype="float64")


def _own_scene_points(record: Dict, depth):
    """Every pixel centre at its depth, in the scene, and the finite mask."""
    import numpy as np

    height, width = depth.shape
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    cx, cy = (float(c) for c in record["principal_point_px"])
    finite = np.isfinite(depth) & (depth > 0.0)
    z = np.where(finite, depth, 0.0)
    x = ((np.arange(width, dtype="float64") + 0.5)[None, :] - cx) / fx * z
    y = ((np.arange(height, dtype="float64") + 0.5)[:, None] - cy) / fy * z
    camera = np.stack([x, y, z], axis=2)
    return _own_centre(record) + camera @ _own_rows(record), finite


def _own_project(record: Dict, points):
    import numpy as np

    camera = (points - _own_centre(record)) @ _own_rows(record).T
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    cx, cy = (float(c) for c in record["principal_point_px"])
    z = camera[..., 2]
    safe = np.where(z > 0.0, z, 1.0)
    return cx + fx * camera[..., 0] / safe, cy + fy * camera[..., 1] / safe, z


def _own_flow(record: Dict, depth, mask, now: Dict, neighbour: Dict):
    """The checker's own flow and validity bits for one direction: each
    pixel's surface moved rigidly with its aircraft (static world
    otherwise) and projected through the neighbour camera; out of frame
    behind it or outside the image; occluded when the nearest splatted
    surface at its pixel is another object's and nearer by more than
    DEPTH_TOL_FRACTION z + DEPTH_TOL_M (the four pixel centres around each
    warped point receive it). Returns (flow (h, w, 2), bits (h, w), finite)."""
    import numpy as np

    points, finite = _own_scene_points(record, depth)
    then = {str(k): v for k, v in (neighbour.get("objects") or {}).items()}
    moved = points.copy()
    for key, state in now.items():
        other = then.get(str(key))
        if other is None:
            continue
        chosen = finite & (mask == int(key))
        if not np.any(chosen):
            continue
        body = (points[chosen] - _own_cg(state)) @ _own_body_columns(state)
        moved[chosen] = _own_cg(other) + body @ _own_body_columns(other).T
    target = neighbour["camera"]
    u2, v2, z2 = _own_project(target, moved)
    height, width = depth.shape
    ahead = finite & (z2 > 0.0)
    flow = np.zeros((height, width, 2), dtype="float64")
    flow[..., 0] = np.where(ahead, u2 - (np.arange(width) + 0.5)[None, :], 0.0)
    flow[..., 1] = np.where(ahead, v2 - (np.arange(height) + 0.5)[:, None], 0.0)
    w2, h2 = int(target["width_px"]), int(target["height_px"])
    inside = ahead & (u2 >= 0.0) & (u2 < w2) & (v2 >= 0.0) & (v2 < h2)
    bits = np.zeros((height, width), dtype=np.uint8)
    us, vs, zs = u2[inside], v2[inside], z2[inside]
    owners = mask[inside].astype(int)
    nearest = np.full((h2, w2), np.inf)
    nearest_owner = np.full((h2, w2), -1, dtype=int)
    left, top = np.floor(us - 0.5).astype(int), np.floor(vs - 0.5).astype(int)
    placed = []
    for du in (0, 1):
        for dv in (0, 1):
            cols, rows = left + du, top + dv
            keep = (cols >= 0) & (cols < w2) & (rows >= 0) & (rows < h2)
            np.minimum.at(nearest, (rows[keep], cols[keep]), zs[keep])
            placed.append((rows[keep], cols[keep], zs[keep], owners[keep]))
    for rows, cols, depths, who in placed:
        won = depths == nearest[rows, cols]
        nearest_owner[rows[won], cols[won]] = who[won]
    at_rows, at_cols = np.floor(vs).astype(int), np.floor(us).astype(int)
    front = nearest[at_rows, at_cols]
    hidden = (nearest_owner[at_rows, at_cols] != owners) & (
        zs > front + DEPTH_TOL_FRACTION * front + DEPTH_TOL_M)
    bits[inside] = np.where(hidden, FLOW_BIT_OCCLUDED, FLOW_BIT_VALID)
    bits[finite & ~inside] = FLOW_BIT_OUT_OF_FRAME
    return flow, bits, finite


def _primary_int_id(manifest: Dict) -> int:
    for entry in _declared_objects(manifest):
        if entry.get("role") == "primary":
            return int(entry["int_id"])
    return AIRCRAFT_INSTANCE_ID


def _aircraft_ids(manifest: Dict) -> List[int]:
    ids = {int(e["int_id"]) for e in _aircraft_entries(_declared_objects(manifest))
           if "int_id" in e}
    ids.add(_primary_int_id(manifest))
    return sorted(ids)


def _state_keys_differ(a: Dict, b: Dict) -> Optional[str]:
    for key in ("north_m", "east_m", "alt_m", "roll_deg", "pitch_deg", "heading_deg"):
        try:
            if abs(float(a[key]) - float(b[key])) > NEIGHBOUR_TOL:
                return key
        except (KeyError, TypeError, ValueError):
            return key
    return None


def _camera_keys_differ(a: Dict, b: Dict) -> Optional[str]:
    for key in ("position_north_m", "position_east_m", "position_alt_m", "fx_px", "fy_px"):
        try:
            if abs(float(a[key]) - float(b[key])) > NEIGHBOUR_TOL:
                return key
        except (KeyError, TypeError, ValueError):
            return key
    try:
        if any(abs(float(p) - float(q)) > NEIGHBOUR_TOL
               for p, q in zip(a["quaternion_wxyz"], b["quaternion_wxyz"])):
            return "quaternion_wxyz"
    except (KeyError, TypeError, ValueError):
        return "quaternion_wxyz"
    return None


def _card_cameras(run_dir) -> Dict[str, Dict]:
    """{camera_id: poses} from the run card, or {} without one."""
    path = Path(run_dir) / "card.json" if run_dir is not None else None
    if path is None or not path.is_file():
        return {}
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(c.get("camera_id")): c.get("poses") or {}
            for c in (card.get("cameras") or []) if isinstance(c, dict)}


def _own_neighbour_problem(manifest: Dict, record: Dict, neighbours: Dict,
                           primary_id: int, card: Dict[str, Dict]) -> Tuple[Optional[str], int]:
    """(the first disagreement, the number of cross-checks made) between a
    frame's neighbour block and the manifest's own frames at those samples
    (the same camera's pose; any frame's primary state) and the run card's
    solved track (the pose at that sample, axes compared through this
    module's own Euler and quaternion expansions)."""
    checked = 0
    camera = str(record["camera_id"])
    own_sample = int(record.get("sample_index", -1))
    current = (neighbours.get("current") or {}).get("objects") or {}
    mine = current.get(str(primary_id))
    if mine is None or _state_keys_differ(mine, record.get("aircraft") or {}):
        return (f"the neighbour block's own-sample primary state is not the frame's "
                f"aircraft state"), checked
    for direction, step in (("forward", 1), ("backward", -1)):
        block = neighbours.get(direction)
        if block is None:
            continue
        target = block.get("camera") or {}
        try:
            sample = int(target["sample_index"])
        except (KeyError, TypeError, ValueError):
            return f"the {direction} neighbour names no sample", checked
        if sample != own_sample + step:
            return (f"the {direction} neighbour is sample {sample}, not the neighbouring "
                    f"sample {own_sample + step}"), checked
        for other in manifest.get("frames", []):
            if int(other.get("sample_index", -2)) != sample:
                continue
            key = _state_keys_differ((block.get("objects") or {}).get(str(primary_id)) or {},
                                     other.get("aircraft") or {})
            if key:
                return (f"the {direction} neighbour's primary {key} differs from the "
                        f"manifest's own frame at sample {sample}"), checked
            checked += 1
            if str(other.get("camera_id")) == camera:
                key = _camera_keys_differ(target, other)
                if key:
                    return (f"the {direction} neighbour camera's {key} differs from the "
                            f"manifest's own frame at sample {sample}"), checked
                checked += 1
        poses = card.get(camera)
        if poses and len(poses.get("t_s") or []) > sample:
            try:
                where = (float(poses["north_m"][sample]), float(poses["east_m"][sample]),
                         float(poses["alt_m"][sample]))
                axes_card = axes_from_euler(float(poses["roll_deg"][sample]),
                                            float(poses["pitch_deg"][sample]),
                                            float(poses["yaw_deg"][sample]))
            except (KeyError, IndexError, TypeError, ValueError):
                return f"the run card's track for {camera} cannot be read at sample {sample}", checked
            gap = math.dist(where, (float(target["position_north_m"]),
                                    float(target["position_east_m"]),
                                    float(target["position_alt_m"])))
            axes_block = axes_from_quat(target["quaternion_wxyz"])
            turn = max(abs(a - b) for u, w in zip(axes_card, axes_block) for a, b in zip(u, w))
            if gap > STEREO_RIG_TOL_M or turn > 1e-9:
                return (f"the {direction} neighbour camera sits {gap:.3g} m and {turn:.3g} "
                        f"(axis components) from the run card's track at sample {sample}"), checked
            checked += 1
    return None, checked


def _own_now(record: Dict, neighbours: Dict, primary_id: int) -> Dict[str, Dict]:
    """The objects' states at the frame's own sample: the primary from the
    frame's own aircraft block, the others from the neighbour block."""
    now = {str(k): v for k, v in ((neighbours.get("current") or {}).get("objects") or {}).items()}
    now[str(primary_id)] = dict(record["aircraft"])
    return now


def _flow_pair(folder: Path, entry: Dict, tag: str, width: int, height: int):
    """(flow (h, w, 2) float64, bits (h, w) uint8, None) or (None, None, reason)."""
    path, bad = _passes_file(folder, entry, f"flow_{tag}")
    if bad:
        return None, None, bad
    valid_path, bad = _passes_file(folder, entry, f"flow_{tag}_valid")
    if bad:
        return None, None, bad
    flow = _own_values(path, "<f4", width * height * 2)
    bits = _own_values(valid_path, "u1", width * height)
    if flow is None or bits is None:
        return None, None, (f"{path.name} / {valid_path.name} are not {width} x {height} "
                            f"flow pairs and bytes")
    return flow.reshape(height, width, 2).astype("float64"), bits.reshape(height, width), None


def _pass_bundle(declared: Dict, camera: str, name: str, folder: Path, record: Dict):
    """(depth, mask, None) for the frame's render bundle, or (None, None, reason)."""
    engine = declared.get(camera, {}).get(name)
    if engine is None:
        return None, None, "passes.json names a frame the render did not label"
    labels = engine["labels"]
    width, height = int(record["width_px"]), int(record["height_px"])
    depth = _read_depth_metres(folder, labels, width, height)
    if isinstance(depth, str):
        return None, None, depth
    if not labels.get("mask"):
        return None, None, "the bundle declares no ID image"
    mask = _read_gray_png(folder / str(labels["mask"]))
    if mask is None or mask.shape != (height, width):
        return None, None, f"{labels['mask']} is not an ID image of {width}x{height}"
    return depth, mask, None


@_reads_the_bundle
def verify_flow_vs_keypoints(manifest: Dict, run_dir=None) -> Check:
    """The derived flow at the aircraft keypoints, and its validity bits,
    against the checker's own projection and z-test.

    Per frame and direction with a flow pass: the neighbour block is
    cross-checked (the manifest's own frames at the neighbouring sample,
    the run card's track); the checker computes its own flow and bits for
    the whole frame (:func:`_own_flow`); every aircraft keypoint (the
    primary's from the airframe block and the frame's own aircraft state,
    each traffic aircraft's from its block) projected through the frame
    whose pixel shows that aircraft at the keypoint's depth (the depth
    tolerance) is a sample: the file's flow there against the checker's
    within FLOW_KEYPOINT_TOL_PX. The file's validity bits must agree with
    the checker's over the frame but for FLOW_BITS_MISMATCH_FRACTION of
    the surface pixels: a dropped z-test (every warped pixel valid) or a
    wrong bit fails by name (annotation.flow). NOT RUN without a flow
    pass or with fewer than FLOW_MIN_KEYPOINTS samples. NOT claimed:
    flow on non-rigid parts, occluders the source frame does not see."""
    frames = list(_passes_frames(manifest, run_dir, "flow"))
    if not frames:
        return Check("flow_vs_keypoints", NOT_RUN, _no_passes_reason("flow"))
    import numpy as np

    declared = _engine_label_records(run_dir)
    card = _card_cameras(run_dir)
    primary_id = _primary_int_id(manifest)
    keypoints: Dict[int, List] = {}
    for owner, block in [(primary_id, manifest.get("airframe"))] + [
            (t.get("int_id"), t.get("airframe")) for t in (manifest.get("traffic") or [])
            if isinstance(t, dict)]:
        kps = [(str(k["name"]), tuple(float(c) for c in k["body_m"]))
               for k in ((block or {}).get("keypoints") or [])
               if isinstance(k, dict) and k.get("name") and k.get("body_m")]
        if kps and owner is not None:
            keypoints[int(owner)] = kps
    samples: List[Tuple[float, str]] = []
    own_offsets: List[float] = []
    occluded_samples = 0
    crosschecks = 0
    worst_bits = (-1, 0, "")
    for record, camera, name, entry, folder in frames:
        where = f"{camera}/{name}"
        width, height = int(record["width_px"]), int(record["height_px"])
        depth, mask, bad = _pass_bundle(declared, camera, name, folder, record)
        if bad:
            return Check("flow_vs_keypoints", FAIL, f"{where}: {bad}", failure=FAIL_FLOW)
        neighbours = (record.get("passes") or {}).get("neighbours")
        if not isinstance(neighbours, dict):
            return Check("flow_vs_keypoints", FAIL,
                         f"{where}: the manifest frame carries no neighbour samples for the "
                         f"flow passes.json names", failure=FAIL_FLOW)
        problem, checked = _own_neighbour_problem(manifest, record, neighbours, primary_id, card)
        if problem:
            return Check("flow_vs_keypoints", FAIL, f"{where}: {problem}", failure=FAIL_FLOW)
        crosschecks += checked
        now = _own_now(record, neighbours, primary_id)
        for direction, tag in (("forward", "fw"), ("backward", "bw")):
            flow, bits, bad = _flow_pair(folder, entry, tag, width, height)
            if bad:
                return Check("flow_vs_keypoints", FAIL, f"{where}: {bad}", failure=FAIL_FLOW)
            neighbour = neighbours.get(direction)
            if neighbour is None:
                continue                    # the end-of-recording null: flow_static_null's
            predicted, own_bits, finite = _own_flow(record, depth, mask, now, neighbour)
            disagree = bits != own_bits
            count = int(np.count_nonzero(disagree))
            surface = int(np.count_nonzero(finite))
            if count > worst_bits[0]:
                worst_bits = (count, surface, f"{where} {direction}")
            if count > max(FLOW_BITS_MISMATCH_MIN_PX, FLOW_BITS_MISMATCH_FRACTION * surface):
                hidden_marked_valid = int(np.count_nonzero(
                    disagree & (own_bits == FLOW_BIT_OCCLUDED) & (bits == FLOW_BIT_VALID)))
                return Check("flow_vs_keypoints", FAIL,
                             f"{where} {direction}: the validity bits disagree with the "
                             f"checker's own z-test on {count} of {surface} surface pixels "
                             f"({hidden_marked_valid} it finds occluded are marked valid) -- a "
                             f"dropped or altered z-test or validity bit", failure=FAIL_FLOW)
            axes = axes_from_quat(record["quaternion_wxyz"])
            then = {str(k): v for k, v in (neighbour.get("objects") or {}).items()}
            for int_id, kps in keypoints.items():
                state, later = now.get(str(int_id)), then.get(str(int_id))
                if state is None or later is None:
                    continue
                for kp_name, body in kps:
                    u, v, z = project_point(record, _body_point_enu(body, state), axes)
                    if not math.isfinite(u):
                        continue
                    px, py = int(math.floor(u)), int(math.floor(v))
                    if not (0 <= px < width and 0 <= py < height):
                        continue
                    if int(mask[py, px]) != int_id:
                        continue
                    seen = float(depth[py, px])
                    if not math.isfinite(seen) or abs(seen - z) > DEPTH_TOL_FRACTION * z + DEPTH_TOL_M:
                        continue            # the pixel shows a nearer part, not the keypoint
                    du, dv = float(flow[py, px, 0]), float(flow[py, px, 1])
                    pu, pv = float(predicted[py, px, 0]), float(predicted[py, px, 1])
                    samples.append((math.hypot(du - pu, dv - pv),
                                    f"{where} {direction} {int_id}:{kp_name} (flow {du:+.3f},"
                                    f"{dv:+.3f} px, checker {pu:+.3f},{pv:+.3f} px)"))
                    if own_bits[py, px] == FLOW_BIT_OCCLUDED:
                        occluded_samples += 1
                    u2, v2, _ = project_point(neighbour["camera"], _body_point_enu(body, later))
                    if math.isfinite(u2):
                        own_offsets.append(math.hypot((u2 - u) - du, (v2 - v) - dv))
    if len(samples) < FLOW_MIN_KEYPOINTS:
        return Check("flow_vs_keypoints", NOT_RUN,
                     f"only {len(samples)} keypoint sample(s) show their own aircraft at their "
                     f"own depth over {len(frames)} flow frame(s) (minimum {FLOW_MIN_KEYPOINTS}); "
                     f"validity bits agreed with the checker's z-test to {max(0, worst_bits[0])} "
                     f"pixel(s)")
    worst = max(samples, key=lambda s: s[0])
    if worst[0] > FLOW_KEYPOINT_TOL_PX:
        return Check("flow_vs_keypoints", FAIL,
                     f"the flow at the aircraft keypoints is up to {worst[0]:.3f} px from the "
                     f"checker's own projection (tolerance {FLOW_KEYPOINT_TOL_PX:g} px) at "
                     f"{worst[1]} -- a scaled, negated, mis-based or mis-assigned motion",
                     failure=FAIL_FLOW)
    return Check("flow_vs_keypoints", PASS,
                 f"{len(samples)} keypoint samples over {len(frames)} frame(s): the flow within "
                 f"{worst[0]:.2e} px of the checker's own projection (tolerance "
                 f"{FLOW_KEYPOINT_TOL_PX:g} px), {occluded_samples} of them occluded at the "
                 f"neighbour sample; validity bits disagree with the checker's z-test on at "
                 f"most {max(0, worst_bits[0])} of {worst_bits[1]} surface pixels "
                 f"({worst_bits[2] or 'no direction with a neighbour'}); "
                 f"{crosschecks} neighbour cross-check(s) against the manifest and the card; "
                 f"the keypoints' own displacement differs from their pixel's flow by at most "
                 f"{max(own_offsets) if own_offsets else 0.0:.3f} px (sub-pixel position, "
                 f"reported, not graded)")


@_reads_the_bundle
def verify_flow_static_null(manifest: Dict, run_dir=None) -> Check:
    """The static world's flow is the camera's own motion and nothing else.

    Per frame and direction with a flow pass, over the pixels that show no
    aircraft (finite depth, an ID that is not an aircraft object's): when
    the neighbour camera is where the frame's camera was (position and
    quaternion within STILL_CAMERA_TOL), every such pixel's flow must be
    zero within STATIC_NULL_TOL_PX -- a static scene gives zero flow;
    otherwise within STATIC_FLOW_TOL_PX of the checker's own camera-only
    flow. A direction with no neighbour sample (the end of the recording)
    must be all zeros with every bit 0, as declared. FAIL annotation.flow;
    NOT RUN without a flow pass."""
    frames = list(_passes_frames(manifest, run_dir, "flow"))
    if not frames:
        return Check("flow_static_null", NOT_RUN, _no_passes_reason("flow"))
    import numpy as np

    declared = _engine_label_records(run_dir)
    aircraft = _aircraft_ids(manifest)
    still = moving = ends = 0
    worst_still = worst_moving = 0.0
    for record, camera, name, entry, folder in frames:
        where = f"{camera}/{name}"
        width, height = int(record["width_px"]), int(record["height_px"])
        depth, mask, bad = _pass_bundle(declared, camera, name, folder, record)
        if bad:
            return Check("flow_static_null", FAIL, f"{where}: {bad}", failure=FAIL_FLOW)
        neighbours = (record.get("passes") or {}).get("neighbours") or {}
        for direction, tag in (("forward", "fw"), ("backward", "bw")):
            flow, bits, bad = _flow_pair(folder, entry, tag, width, height)
            if bad:
                return Check("flow_static_null", FAIL, f"{where}: {bad}", failure=FAIL_FLOW)
            neighbour = neighbours.get(direction)
            if neighbour is None:
                if np.any(flow != 0.0) or np.any(bits != 0):
                    return Check("flow_static_null", FAIL,
                                 f"{where} {direction}: no neighbouring sample, so the flow is "
                                 f"declared null, but the file holds "
                                 f"{int(np.count_nonzero(flow.any(axis=2)))} moving pixels and "
                                 f"{int(np.count_nonzero(bits))} set bits", failure=FAIL_FLOW)
                ends += 1
                continue
            finite = np.isfinite(depth) & (depth > 0.0)
            static = finite & ~np.isin(mask, aircraft)
            if not np.any(static):
                continue
            target = neighbour["camera"]
            if _camera_keys_differ(target, record) is None and all(
                    abs(float(p) - float(q)) <= STILL_CAMERA_TOL
                    for p, q in zip(target["quaternion_wxyz"], record["quaternion_wxyz"])):
                largest = float(np.hypot(flow[..., 0], flow[..., 1])[static].max())
                worst_still = max(worst_still, largest)
                if largest > STATIC_NULL_TOL_PX:
                    return Check("flow_static_null", FAIL,
                                 f"{where} {direction}: the camera did not move, yet the static "
                                 f"world flows by up to {largest:.4f} px (tolerance "
                                 f"{STATIC_NULL_TOL_PX:g} px) -- a static scene gives zero flow",
                                 failure=FAIL_FLOW)
                still += 1
                continue
            points, _ = _own_scene_points(record, depth)
            u2, v2, z2 = _own_project(target, points)
            ahead = static & (z2 > 0.0)
            if not np.any(ahead):
                continue
            error = np.hypot(flow[..., 0] - (u2 - (np.arange(width) + 0.5)[None, :]),
                             flow[..., 1] - (v2 - (np.arange(height) + 0.5)[:, None]))[ahead]
            largest = float(error.max())
            worst_moving = max(worst_moving, largest)
            if largest > STATIC_FLOW_TOL_PX:
                return Check("flow_static_null", FAIL,
                             f"{where} {direction}: the static world's flow is up to "
                             f"{largest:.3f} px from the camera's own motion as the checker "
                             f"projects it (tolerance {STATIC_FLOW_TOL_PX:g} px)",
                             failure=FAIL_FLOW)
            moving += 1
    if still + moving + ends == 0:
        return Check("flow_static_null", NOT_RUN,
                     f"{len(frames)} flow frame(s), none with a static pixel to grade")
    return Check("flow_static_null", PASS,
                 f"{still} still-camera direction(s) with the static world at most "
                 f"{worst_still:.2e} px (the null), {moving} moving-camera direction(s) within "
                 f"{worst_moving:.2e} px of the camera's own motion, {ends} end-of-recording "
                 f"direction(s) all zeros as declared")


@_reads_the_bundle
def verify_disparity_vs_right_depth(manifest: Dict, run_dir=None) -> Check:
    """The stereo rig and its disparity.

    The rig clause (no pixels needed): every left frame of a rig the
    manifest declares (a camera block's ``stereo`` with role left) has
    its right frame at the same index, time and sample, with the same
    quaternion and intrinsics and the centre STEREO_RIG_TOL_M from the
    left centre plus baseline_m along the left camera's right axis (this
    module's own axes). The disparity clause, per left frame with a
    disparity pass: the stored d against the checker's own f_x B / Z of
    the left depth (DISPARITY_FORMULA_TOL_PX; 0 for sky), and against
    the RIGHT camera's depth: the right pixel d to the left on the same
    row shows the same depth (rectified: Z is the same in both cameras)
    on at least DISPARITY_RIGHT_AGREE_MIN of the left surface pixels that
    land inside the right image. FAIL annotation.disparity. NOT RUN
    without a rig, or with no disparity to grade against a right depth."""
    rigs = {str(b.get("camera_id")): b["stereo"] for b in manifest.get("cameras", []) or []
            if isinstance(b, dict) and isinstance(b.get("stereo"), dict)
            and b["stereo"].get("role") == "left"}
    if not rigs:
        return Check("disparity_vs_right_depth", NOT_RUN,
                     "no camera block declares a stereo rig (cameras[i].stereo)")
    import numpy as np

    by_index = {(str(f.get("camera_id")), int(f.get("index", -1))): f
                for f in manifest.get("frames", [])}
    pairs = 0
    for left_id, rig in rigs.items():
        right_id = str(rig.get("right_camera_id"))
        baseline = float(rig.get("baseline_m", 0.0))
        for record in manifest.get("frames", []):
            if str(record.get("camera_id")) != left_id:
                continue
            other = by_index.get((right_id, int(record["index"])))
            where = f"{left_id}/{record['index']}"
            if other is None:
                return Check("disparity_vs_right_depth", FAIL,
                             f"{where}: the rig's right camera {right_id!r} has no frame at "
                             f"this index", failure=FAIL_DISPARITY)
            for key in ("t_s", "sample_index", "fx_px", "fy_px", "width_px", "height_px"):
                if other.get(key) != record.get(key):
                    return Check("disparity_vs_right_depth", FAIL,
                                 f"{where}: the right frame's {key} is {other.get(key)!r} where "
                                 f"the left's is {record.get(key)!r} -- not one rectified rig",
                                 failure=FAIL_DISPARITY)
            if list(other.get("principal_point_px") or []) != list(record.get("principal_point_px") or []) \
                    or any(abs(float(p) - float(q)) > 1e-12 for p, q in
                           zip(other["quaternion_wxyz"], record["quaternion_wxyz"])):
                return Check("disparity_vs_right_depth", FAIL,
                             f"{where}: the right camera is not oriented and centred as the "
                             f"left (principal point or quaternion differ)", failure=FAIL_DISPARITY)
            _, right_axis, _ = axes_from_quat(record["quaternion_wxyz"])
            expected = tuple(float(record[k]) + baseline * r for k, r in zip(
                ("position_north_m", "position_east_m", "position_alt_m"), right_axis))
            gap = math.dist(expected, (float(other["position_north_m"]),
                                       float(other["position_east_m"]),
                                       float(other["position_alt_m"])))
            if gap > STEREO_RIG_TOL_M:
                return Check("disparity_vs_right_depth", FAIL,
                             f"{where}: the right camera sits {gap:.3g} m from the left centre "
                             f"plus {baseline:g} m along the left's right axis (tolerance "
                             f"{STEREO_RIG_TOL_M:g} m)", failure=FAIL_DISPARITY)
            pairs += 1
    declared = _engine_label_records(run_dir)
    graded, notes, worst_formula, least_agree = 0, [], 0.0, 1.0
    for record, camera, name, entry, folder in _passes_frames(manifest, run_dir, "disparity"):
        where = f"{camera}/{name}"
        rig = rigs.get(camera)
        if rig is None:
            return Check("disparity_vs_right_depth", FAIL,
                         f"{where}: a disparity pass on a camera that is no rig's left",
                         failure=FAIL_DISPARITY)
        width, height = int(record["width_px"]), int(record["height_px"])
        path, bad = _passes_file(folder, entry, "disparity")
        if bad:
            return Check("disparity_vs_right_depth", FAIL, f"{where}: {bad}", failure=FAIL_DISPARITY)
        stored = _own_values(path, "<f4", width * height)
        if stored is None:
            return Check("disparity_vs_right_depth", FAIL,
                         f"{where}: {path.name} is not {width} x {height} float32 values",
                         failure=FAIL_DISPARITY)
        stored = stored.reshape(height, width).astype("float64")
        engine = declared.get(camera, {}).get(name)
        if engine is None:
            return Check("disparity_vs_right_depth", FAIL,
                         f"{where}: passes.json names a frame the render did not label",
                         failure=FAIL_DISPARITY)
        depth = _read_depth_metres(folder, engine["labels"], width, height)
        if isinstance(depth, str):
            return Check("disparity_vs_right_depth", FAIL, f"{where}: {depth}",
                         failure=FAIL_DISPARITY)
        finite = np.isfinite(depth) & (depth > 0.0)
        baseline = float(rig["baseline_m"])
        own = np.where(finite, float(record["fx_px"]) * baseline / np.where(finite, depth, 1.0), 0.0)
        formula = float(np.abs(stored - own).max())
        worst_formula = max(worst_formula, formula)
        if formula > DISPARITY_FORMULA_TOL_PX:
            return Check("disparity_vs_right_depth", FAIL,
                         f"{where}: the disparity is up to {formula:.4f} px from the checker's "
                         f"f_x B / Z at the rig's {baseline:g} m (tolerance "
                         f"{DISPARITY_FORMULA_TOL_PX:g} px)", failure=FAIL_DISPARITY)
        right_id = str(rig["right_camera_id"])
        right_record = by_index.get((right_id, int(record["index"])))
        right_engine = declared.get(right_id, {}).get(
            Path(str((right_record or {}).get("file"))).name)
        if right_engine is None:
            notes.append(f"{where}: the right camera {right_id} has no depth to compare against")
            continue
        right_depth = _read_depth_metres(Path(run_dir) / "frames" / right_id,
                                         right_engine["labels"], width, height)
        if isinstance(right_depth, str):
            return Check("disparity_vs_right_depth", FAIL, f"{right_id}: {right_depth}",
                         failure=FAIL_DISPARITY)
        rows, cols = np.nonzero(finite)
        columns = np.floor(cols + 0.5 - stored[rows, cols]).astype(int)
        inside = (columns >= 0) & (columns < width)
        if not np.any(inside):
            notes.append(f"{where}: no left surface pixel lands inside the right image")
            continue
        z_left = depth[rows[inside], cols[inside]]
        z_right = right_depth[rows[inside], columns[inside]]
        agree = np.isfinite(z_right) & (np.abs(z_right - z_left)
                                        <= DEPTH_TOL_FRACTION * z_left + DEPTH_TOL_M)
        fraction = float(np.count_nonzero(agree)) / float(agree.size)
        least_agree = min(least_agree, fraction)
        if fraction < DISPARITY_RIGHT_AGREE_MIN:
            return Check("disparity_vs_right_depth", FAIL,
                         f"{where}: only {fraction * 100:.1f} % of the left surface pixels find "
                         f"their own depth in the right image {right_id} at the stored "
                         f"disparity (minimum {DISPARITY_RIGHT_AGREE_MIN * 100:g} %) -- the "
                         f"disparity or the right camera is not the rig", failure=FAIL_DISPARITY)
        graded += 1
    rig_note = f"the rig: {pairs} left/right pair(s) rectified by construction as declared"
    if graded == 0:
        return Check("disparity_vs_right_depth", NOT_RUN,
                     f"{rig_note}; no disparity pass with a right depth to grade"
                     + (f" ({'; '.join(notes[:2])})" if notes else ""))
    return Check("disparity_vs_right_depth", PASS,
                 f"{rig_note}; {graded} disparity frame(s) within {worst_formula:.2e} px of "
                 f"f_x B / Z, at least {least_agree * 100:.1f} % of left surface pixels matching "
                 f"the right camera's depth (minimum {DISPARITY_RIGHT_AGREE_MIN * 100:g} %)"
                 + (f"; {'; '.join(notes[:2])}" if notes else ""))


@_reads_the_bundle
def verify_points_vs_depth(manifest: Dict, run_dir=None) -> Check:
    """The point cloud against the depth it was back-projected from.

    Per frame with a points pass: N x 4 float32 and N id bytes; the
    reflectance column 0; every point re-projected through the record's
    pinhole lands on a pixel centre (POINTS_REPROJECTION_TOL_PX) of a
    finite-depth pixel, at that pixel's depth (POINTS_DEPTH_TOL_M +
    POINTS_DEPTH_TOL_FRACTION z), with that pixel's ID; every finite
    pixel exactly once (the sky contributes none); the per-object counts
    passes.json states are the checker's own. FAIL annotation.points;
    NOT RUN without a points pass."""
    frames = list(_passes_frames(manifest, run_dir, "points"))
    if not frames:
        return Check("points_vs_depth", NOT_RUN, _no_passes_reason("points"))
    import numpy as np

    declared = _engine_label_records(run_dir)
    total = 0
    worst_px = worst_m = 0.0
    for record, camera, name, entry, folder in frames:
        where = f"{camera}/{name}"
        width, height = int(record["width_px"]), int(record["height_px"])
        depth, mask, bad = _pass_bundle(declared, camera, name, folder, record)
        if bad:
            return Check("points_vs_depth", FAIL, f"{where}: {bad}", failure=FAIL_POINTS)
        path, bad = _passes_file(folder, entry, "points")
        if bad:
            return Check("points_vs_depth", FAIL, f"{where}: {bad}", failure=FAIL_POINTS)
        id_path, bad = _passes_file(folder, entry, "points_id")
        if bad:
            return Check("points_vs_depth", FAIL, f"{where}: {bad}", failure=FAIL_POINTS)
        raw = _own_values(path, "<f4", None)
        ids = _own_values(id_path, "u1", None)
        if raw.size % 4 or ids.size != raw.size // 4:
            return Check("points_vs_depth", FAIL,
                         f"{where}: {raw.size} float32 values and {ids.size} ids are not N x 4 "
                         f"points with N ids", failure=FAIL_POINTS)
        points = raw.reshape(-1, 4).astype("float64")
        finite = np.isfinite(depth) & (depth > 0.0)
        if points.shape[0] != int(np.count_nonzero(finite)):
            return Check("points_vs_depth", FAIL,
                         f"{where}: {points.shape[0]} points for {int(np.count_nonzero(finite))} "
                         f"finite-depth pixels ({int(np.count_nonzero(~finite))} sky pixels "
                         f"contribute none)", failure=FAIL_POINTS)
        if points.shape[0] and np.any(points[:, 3] != 0.0):
            return Check("points_vs_depth", FAIL,
                         f"{where}: the reflectance column is not 0 as declared", failure=FAIL_POINTS)
        fx, fy = float(record["fx_px"]), float(record["fy_px"])
        cx, cy = (float(c) for c in record["principal_point_px"])
        z = points[:, 2]
        if points.shape[0] and np.any(z <= 0.0):
            return Check("points_vs_depth", FAIL, f"{where}: a point behind the camera",
                         failure=FAIL_POINTS)
        u = cx + fx * points[:, 0] / np.where(z > 0, z, 1.0)
        v = cy + fy * points[:, 1] / np.where(z > 0, z, 1.0)
        px, py = np.floor(u).astype(int), np.floor(v).astype(int)
        off = np.hypot(u - (px + 0.5), v - (py + 0.5)) if points.shape[0] else np.zeros(0)
        inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
        if not np.all(inside) or (off.size and float(off.max()) > POINTS_REPROJECTION_TOL_PX):
            return Check("points_vs_depth", FAIL,
                         f"{where}: points re-project up to "
                         f"{float(off.max()) if off.size else 0.0:.4f} px from a pixel centre, or "
                         f"outside the image", failure=FAIL_POINTS)
        linear = py * width + px
        if np.unique(linear).size != linear.size or not np.all(finite.ravel()[linear]):
            return Check("points_vs_depth", FAIL,
                         f"{where}: the points do not cover each finite-depth pixel exactly once",
                         failure=FAIL_POINTS)
        gap = np.abs(z - depth.ravel()[linear])
        allowed = POINTS_DEPTH_TOL_M + POINTS_DEPTH_TOL_FRACTION * z
        if gap.size and np.any(gap > allowed):
            return Check("points_vs_depth", FAIL,
                         f"{where}: a point sits up to {float(gap.max()):.4f} m from the depth of "
                         f"its pixel", failure=FAIL_POINTS)
        if np.any(ids != mask.ravel()[linear]):
            return Check("points_vs_depth", FAIL,
                         f"{where}: {int(np.count_nonzero(ids != mask.ravel()[linear]))} point ids "
                         f"are not the ID image's at their pixel", failure=FAIL_POINTS)
        values, counts = np.unique(ids, return_counts=True)
        own = {str(int(a)): int(b) for a, b in zip(values, counts)}
        stated = {str(k): int(v) for k, v in ((entry.get("points") or {}).get("per_object") or {}).items()}
        if own != stated or int((entry.get("points") or {}).get("total", -1)) != points.shape[0]:
            return Check("points_vs_depth", FAIL,
                         f"{where}: passes.json states {stated} points per object, the checker "
                         f"counts {own}", failure=FAIL_POINTS)
        total += points.shape[0]
        worst_px = max(worst_px, float(off.max()) if off.size else 0.0)
        worst_m = max(worst_m, float(gap.max()) if gap.size else 0.0)
    return Check("points_vs_depth", PASS,
                 f"{len(frames)} frame(s), {total} points: each on its pixel centre within "
                 f"{worst_px:.1e} px at its depth within {worst_m:.1e} m with its pixel's ID; "
                 f"every finite pixel once, the sky contributing none; per-object counts as "
                 f"stated")


@_reads_the_bundle
def verify_amodal_contains_visible(manifest: Dict, run_dir=None) -> Check:
    """The amodal box and mask of each aircraft object against its visible
    pixels, from the checker's own reading of the ID image and the alone
    pass: the visible pixels lie in the alone footprint (all but
    VISIBILITY_TOL_FRACTION of them); the record's amodal_bbox_2d is the
    tight box of the footprint, contains the visible tight box and sits
    within bbox_2d_unclipped +- AMODAL_BOX_SLACK_PX; amodal_mask names the
    alone pass with its pixel count; amodal_ratio is the checker's
    footprint / visible count and 1 / visible_fraction. FAIL
    annotation.amodal; a record that refused annotation.amodal while its
    alone pass exists fails too. NOT RUN when no record carries the keys."""
    if not _engine_label_records(run_dir):
        return Check("amodal_contains_visible", NOT_RUN, _no_bundle_reason())
    import numpy as np

    graded = refused = 0
    least = 1.0
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        labels = engine["labels"]
        alone_files = _alone_files(labels)
        entries = [e for e in (record.get("labels") or {}).get("objects") or []
                   if isinstance(e, dict) and "amodal_bbox_2d" in e]
        if not entries:
            continue
        mask = _read_gray_png(folder / str(labels["mask"])) if labels.get("mask") else None
        for entry in entries:
            int_id = int(entry["int_id"])
            where = f"{camera}/{name} object {entry.get('id', int_id)}"
            basis = (entry.get("basis") or {}).get("amodal")
            if isinstance(basis, dict) and basis.get("refused"):
                if int_id in alone_files:
                    return Check("amodal_contains_visible", FAIL,
                                 f"{where}: the record refused {basis['refused']} though the "
                                 f"bundle declares its alone pass {alone_files[int_id]}",
                                 failure=FAIL_AMODAL)
                refused += 1
                continue
            alone_file = alone_files.get(int_id)
            declared_mask = entry.get("amodal_mask") or {}
            if alone_file is None or declared_mask.get("file") != alone_file:
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: the amodal mask names {declared_mask.get('file')!r}, the "
                             f"bundle's alone pass is {alone_file!r} (basis 'alone pass')",
                             failure=FAIL_AMODAL)
            alone = _read_gray_png(folder / alone_file)
            if mask is None or alone is None or alone.shape != mask.shape:
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: the ID image and the alone pass are not one frame's size",
                             failure=FAIL_AMODAL)
            visible = mask == int_id
            footprint = alone == int_id
            seen, whole = int(np.count_nonzero(visible)), int(np.count_nonzero(footprint))
            outside = int(np.count_nonzero(visible & ~footprint))
            if seen and outside > VISIBILITY_TOL_FRACTION * seen:
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: {outside} of its {seen} visible pixels lie outside its "
                             f"amodal mask (tolerance {VISIBILITY_TOL_FRACTION * 100:g} %)",
                             failure=FAIL_AMODAL)
            if seen:
                least = min(least, 1.0 - outside / seen)
            own_box = None
            if whole:
                ys, xs = np.nonzero(footprint)
                own_box = [float(xs.min()), float(ys.min()), float(xs.max()) + 1.0,
                           float(ys.max()) + 1.0]
            box = entry.get("amodal_bbox_2d")
            if (own_box is None) != (box is None) or (own_box is not None and any(
                    abs(float(a) - b) > 1e-9 for a, b in zip(box, own_box))):
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: amodal_bbox_2d {box} is not the tight box of the alone "
                             f"pass {own_box}", failure=FAIL_AMODAL)
            tight = entry.get("bbox_2d_tight")
            if own_box is not None and tight and not (
                    own_box[0] <= tight[0] and own_box[1] <= tight[1]
                    and own_box[2] >= tight[2] and own_box[3] >= tight[3]):
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: the amodal box {own_box} does not contain the visible "
                             f"box {tight}", failure=FAIL_AMODAL)
            hull = entry.get("bbox_2d_unclipped")
            slack = AMODAL_BOX_SLACK_PX
            if own_box is not None and hull and not (
                    own_box[0] >= hull[0] - slack and own_box[1] >= hull[1] - slack
                    and own_box[2] <= hull[2] + slack and own_box[3] <= hull[3] + slack):
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: the amodal box {own_box} leaves the projected extents box "
                             f"{[round(float(c), 2) for c in hull]} by more than {slack:g} px",
                             failure=FAIL_AMODAL)
            if int(declared_mask.get("pixels", -1)) != whole:
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: the amodal mask states {declared_mask.get('pixels')} "
                             f"pixels, the alone pass holds {whole}", failure=FAIL_AMODAL)
            ratio = entry.get("amodal_ratio")
            own_ratio = (whole / seen) if seen else None
            if (ratio is None) != (own_ratio is None) or (own_ratio is not None and abs(
                    float(ratio) - own_ratio) > AMODAL_RATIO_TOL * own_ratio):
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: amodal_ratio {ratio} is not the checker's {own_ratio}",
                             failure=FAIL_AMODAL)
            fraction = entry.get("visible_fraction")
            if own_ratio is not None and isinstance(fraction, (int, float)) and fraction > 0 \
                    and abs(own_ratio - 1.0 / float(fraction)) > 1e-6 * own_ratio:
                return Check("amodal_contains_visible", FAIL,
                             f"{where}: amodal_ratio {own_ratio:.6f} is not 1 / visible_fraction "
                             f"{1.0 / float(fraction):.6f}", failure=FAIL_AMODAL)
            graded += 1
    if graded == 0:
        return Check("amodal_contains_visible", NOT_RUN,
                     f"no object record carries an amodal box (no camera asks for amodal)"
                     + (f"; {refused} refused annotation.amodal without an alone pass"
                        if refused else ""))
    return Check("amodal_contains_visible", PASS,
                 f"{graded} aircraft object record(s): the visible pixels inside the amodal mask "
                 f"(at least {least * 100:.1f} %), each amodal box the alone pass's tight box, "
                 f"containing the visible box, within the extents box +- "
                 f"{AMODAL_BOX_SLACK_PX:g} px, ratio = 1 / visible_fraction"
                 + (f"; {refused} refused annotation.amodal without an alone pass"
                    if refused else ""))


# -- W3: the night frame's sky against the K&S sky through the EV100 of record --

#: How far (stops) a night frame's sky band may sit from the checker's own
#: K&S sky luminance through the camera's EV100 of record: above it by more
#: than this is a night that did not hold (a day-exposed sky); below it, when
#: the moonlit prediction is above one 8-bit code, a moon that did not light.
NIGHT_EXPOSURE_TOL_STOPS = 2.0
#: The sky band graded: this far above the horizon along the camera's own
#: azimuth, or the camera's elevation when it looks higher.
NIGHT_SKY_BAND_ELEVATION_DEG = 10.0
#: A frame needs this many sky pixels (class 0) to be graded.
NIGHT_SKY_MIN_PIXELS = 64
#: The smallest non-zero 8-bit sRGB code, in linear units (1/255/12.92).
NIGHT_ONE_CODE_LINEAR = 1.0 / 255.0 / 12.92
#: The night the check grades: the recorded sun at or below this elevation.
NIGHT_SUN_ELEVATION_MAX_DEG = -6.0
FAIL_NIGHT_EXPOSURE = "check.night_exposure"


def _night_air_mass(zenith_deg):
    s = math.sin(math.radians(min(90.0, max(0.0, zenith_deg))))
    return 1.0 / math.sqrt(1.0 - 0.96 * s * s)


def _night_sky_cd_m2(phase_angle_deg, moon_az, moon_el, sky_az, sky_el, moon_lit):
    """The checker's own reading of Krisciunas & Schaefer 1991 (written apart
    from core/scene/night.py): the dark sky 79.0 nL x X 10^(-0.4 k (X - 1))
    plus, with the moon lit, f(rho) I* 10^(-0.4 k X(Zm)) (1 - 10^(-0.4 k X(Z)))
    with I* = 10^(-0.4 (m + 16.57)) fc and m = -12.73 + 0.026 a + 4e-9 a^4;
    k = 0.172; 1 nL = 1e-5 / pi cd/m^2."""
    k = 0.172
    to_cd = 1e-5 / math.pi
    zenith = 90.0 - sky_el
    x = _night_air_mass(zenith)
    dark = 79.0 * x * 10.0 ** (-0.4 * k * (x - 1.0))
    lit = 0.0
    if moon_lit and moon_el > 0.0:
        a1, e1, a2, e2 = (math.radians(v) for v in (moon_az, moon_el, sky_az, sky_el))
        cos_rho = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(a1 - a2)
        rho = max(10.0, math.degrees(math.acos(max(-1.0, min(1.0, cos_rho)))))
        f_rho = (10.0 ** 5.36 * (1.06 + math.cos(math.radians(rho)) ** 2)
                 + 10.0 ** (6.15 - rho / 40.0))
        alpha = abs(phase_angle_deg)
        i_star = 10.0 ** (-0.4 * (-12.73 + 0.026 * alpha + 4e-9 * alpha ** 4 + 16.57))
        lit = (f_rho * i_star * 10.0 ** (-0.4 * k * _night_air_mass(90.0 - moon_el))
               * (1.0 - 10.0 ** (-0.4 * k * x)))
    return dark * to_cd, lit * to_cd


def verify_night_exposure(manifest: Dict, run_dir=None) -> Check:
    """A night frame's sky band against the checker's own K&S sky luminance
    through the camera's EV100 of record (cameras[i].sensing.radiometry
    luminance_cd_m2_per_unit): the band mean (linear, the class image's
    sky pixels) must not exceed prediction x 2^NIGHT_EXPOSURE_TOL_STOPS, and
    with the moon lit and the prediction above one 8-bit code it must not
    fall below prediction x 2^-NIGHT_EXPOSURE_TOL_STOPS. The phase angle is
    re-derived from the card's illuminated fraction (i = acos(2k - 1)).
    NOT RUN without a look.night block, when the recorded sun is above -6
    deg (no night frame), without an EV100 chain of record, a run
    directory, or a night frame with a class image. FAIL check.night_exposure."""
    look = manifest.get("look") if isinstance(manifest.get("look"), dict) else {}
    night, sky = look.get("night"), look.get("night_sky")
    if not isinstance(night, dict) or not isinstance(sky, dict):
        return Check("night_exposure", NOT_RUN, "the manifest carries no look.night block: no "
                                                "night was asked for")
    try:
        sun = float(sky["sun_elevation_deg"])
        k_phase = float(night["phase"])
        moon_el = float(night["moon_elevation_deg"])
        moon_az = float(night["moon_azimuth_deg"])
        lux = float(night["illuminance_lux"])
    except (KeyError, TypeError, ValueError):
        return Check("night_exposure", FAIL, "look.night / look.night_sky lack the sun "
                                             "elevation, the phase or the moon's position",
                     failure=FAIL_NIGHT_EXPOSURE)
    if sun > NIGHT_SUN_ELEVATION_MAX_DEG:
        return Check("night_exposure", NOT_RUN, f"the recorded sun is at {sun:.2f} deg, above "
                                                f"{NIGHT_SUN_ELEVATION_MAX_DEG:g}: no night frame")
    cameras = _sensing_cameras(manifest, "radiometry")
    if not cameras:
        return Check("night_exposure", NOT_RUN, "no camera carries an EV100 chain of record "
                                                "(sensing.radiometry): nothing to expose against")
    if run_dir is None:
        return Check("night_exposure", NOT_RUN, "no run directory: no night frame is here")
    import numpy as np

    phase_angle = math.degrees(math.acos(max(-1.0, min(1.0, 2.0 * k_phase - 1.0))))
    moon_lit = lux > 0.0
    graded, details = 0, []
    for record, camera, name, engine, folder in _bundle_frames(manifest, run_dir):
        if camera not in cameras:
            continue
        class_file = (engine.get("labels") or {}).get("class_mask")
        if not class_file:
            details.append(f"{camera}/{name}: no class image, no sky band")
            continue
        beauty = _sensing_read_linear_gray(folder / name)
        classes = _read_gray_png(folder / class_file)
        if beauty is None or classes is None or beauty.shape != classes.shape:
            details.append(f"{camera}/{name}: the frame or its class image is unreadable")
            continue
        band = classes == 0
        if int(np.count_nonzero(band)) < NIGHT_SKY_MIN_PIXELS:
            details.append(f"{camera}/{name}: under {NIGHT_SKY_MIN_PIXELS} sky pixels")
            continue
        per_unit = float(cameras[camera]["radiometry"]["luminance_cd_m2_per_unit"])
        forward, _right, _up = axes_from_quat(record["quaternion_wxyz"])
        azimuth = math.degrees(math.atan2(forward[1], forward[0])) % 360.0
        elevation = max(NIGHT_SKY_BAND_ELEVATION_DEG,
                        math.degrees(math.asin(max(-1.0, min(1.0, forward[2])))))
        dark, lit = _night_sky_cd_m2(phase_angle, moon_az, moon_el, azimuth, elevation, moon_lit)
        predicted = (dark + lit) / per_unit
        measured = float(beauty[band].mean())
        ceiling = predicted * 2.0 ** NIGHT_EXPOSURE_TOL_STOPS
        if measured > ceiling:
            return Check("night_exposure", FAIL,
                         f"{camera}/{name}: the sky band reads {measured:.3e} of full scale where "
                         f"the K&S sky ({(dark + lit):.3e} cd/m^2) through the EV100 of record "
                         f"predicts {predicted:.3e}; above the {ceiling:.3e} ceiling, the night "
                         f"did not hold", failure=FAIL_NIGHT_EXPOSURE)
        if moon_lit and predicted >= NIGHT_ONE_CODE_LINEAR:
            floor = predicted * 2.0 ** -NIGHT_EXPOSURE_TOL_STOPS
            if measured < floor:
                return Check("night_exposure", FAIL,
                             f"{camera}/{name}: the moonlit sky band reads {measured:.3e} where "
                             f"{predicted:.3e} is predicted; below the {floor:.3e} floor, the "
                             f"moon did not light the sky", failure=FAIL_NIGHT_EXPOSURE)
        graded += 1
        details.append(f"{camera}/{name}: sky {measured:.3e} against {predicted:.3e}")
    if graded == 0:
        return Check("night_exposure", NOT_RUN,
                     "; ".join(details) or "no night frame with an engine label record is here")
    return Check("night_exposure", PASS, f"{graded} night frame(s) within "
                                         f"{NIGHT_EXPOSURE_TOL_STOPS:g} stops: "
                                         + "; ".join(details[:4]))


def verify_run(run_dir, other_run_dir=None) -> VerificationReport:
    """The pass/fail summary over a run directory (CLI: flightsim.verify).

    Every check runs or says why it did not. Temporal alignment needs a
    second capture of the same simulation; landmark reprojection and
    two-view triangulation need rendered frames. None of the three is
    counted as a pass when its reference is absent.

    A verification never ends in a traceback: a check that breaks on a
    run (a file it did not expect, a defect of its own) is recorded as a
    FAIL saying so in a sentence, so the run still gets its verdict on
    disk and the CLI still prints what was refused. The same holds for
    the ``--against`` run: a missing or unreadable second manifest is a
    named FAIL check, and the cross-run clauses report NOT RUN.
    """
    from .manifest import read_capture_manifest

    report = VerificationReport()

    def run(name: str, check, *args) -> None:
        try:
            report.checks.append(check(*args))
        except Exception as exc:        # noqa: BLE001 -- the verdict must be written
            report.checks.append(Check(
                name, FAIL,
                f"the checker hit an error it did not expect while running this "
                f"check ({exc.__class__.__name__}: {exc}); that is a defect in the "
                f"checker or a run file it did not expect, and the run is not "
                f"verified until it is fixed"))

    def read_manifest(where, label: str):
        """The manifest at ``where`` or None, with the FAIL check that
        says why (``<label>manifest_present`` / ``<label>manifest_version``)."""
        path = Path(where) / "capture_manifest.json"
        if not path.is_file():
            report.add(f"{label}manifest_present", False,
                       f"{path} does not exist; nothing to verify"
                       if not label else
                       f"--against {Path(where)}: {path} does not exist, so the "
                       f"second run cannot be compared; cross-run identity and "
                       f"temporal alignment are NOT RUN")
            return None
        try:
            manifest = read_capture_manifest(path)
            if not isinstance(manifest, dict):
                raise ValueError(f"{path} does not hold a manifest object")
        except (OSError, ValueError, AttributeError) as exc:
            report.add(f"{label}manifest_version", False,
                       (f"--against {Path(where)}: " if label else "") + str(exc))
            return None
        report.add(f"{label}manifest_version", True,
                   (f"--against {Path(where)}: " if label else "")
                   + f"manifest_version {manifest.get('manifest_version')}, "
                   f"spec {str(manifest.get('spec_digest') or '?')[:16]}")
        return manifest

    manifest = read_manifest(run_dir, "")
    if manifest is None:
        return report

    finite = True
    for record in manifest.get("frames", []):
        for key in ("t_s", "position_north_m", "position_east_m",
                    "position_alt_m", "fx_px", "fy_px"):
            value = record.get(key) if isinstance(record, dict) else None
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                finite = False
    report.add("fields_finite", finite,
               f"{len(manifest.get('frames', []))} frame records checked")

    run("json_schema", verify_json_schema, manifest)
    run("intrinsics_match_spec", verify_intrinsics, manifest)
    run("projection_matrix", verify_projection_matrix, manifest)
    run("pose_matches_spec", verify_pose_matches_spec, manifest)
    run("geometry_recovery", verify_geometry, manifest)
    run("landmark_reprojection", verify_landmark_reprojection, manifest, run_dir)
    run("cross_view_consistency", verify_triangulation, manifest, run_dir)
    run("count_exactness", verify_counts, manifest)
    run("aircraft_state_consistency", verify_aircraft_consistency, manifest)
    run("flight_agreement", verify_flight_agreement, manifest, run_dir)
    run("host_determinism", verify_host_determinism, run_dir)
    run("capture_time_agreement", verify_capture_times, manifest, run_dir)
    run("label_geometry", verify_labels, manifest)
    run("keypoints_in_box", verify_keypoints_in_box, manifest)
    run("drawn_airframe", verify_drawn_airframe, manifest, run_dir)
    run("label_files", verify_label_files, manifest, run_dir)
    run("mask_containment", verify_mask_containment, manifest, run_dir)
    run("depth_range", verify_depth_range, manifest, run_dir)
    # Phase 2, package D (contracts §4): the annotation gates, in the
    # page's order, after the version-5 label checks they supersede.
    other = read_manifest(other_run_dir, "against_") if other_run_dir is not None else None
    run("mask_integers_only", verify_mask_integers_only, manifest, run_dir)
    run("mask_vs_geometry", verify_mask_vs_geometry, manifest, run_dir)
    run("box_vs_mask", verify_box_vs_mask, manifest, run_dir)
    run("depth_vs_geometry", verify_depth_vs_geometry, manifest, run_dir)
    run("visibility_vs_scene", verify_visibility_vs_scene, manifest, run_dir)
    run("identity_stable", verify_identity_stable, manifest, run_dir, other)
    run("applied_intrinsics", verify_applied_intrinsics, manifest, run_dir)
    run("sensor_undistortion", verify_sensor_undistortion, manifest)
    run("sensor_files", verify_sensor_files, manifest, run_dir)
    run("frame_integrity", verify_frame_integrity, manifest, run_dir)
    run("applied_pose", verify_applied_pose, manifest, run_dir)
    run("instruments", verify_instruments, manifest, run_dir)
    # P10: the vertical datum block against the checker's own geoid read.
    run("datum", verify_datum, manifest)
    run("datum_independent", verify_datum_independent, manifest, run_dir)
    # D2: the Entity State PDU log against the recording, by the checker's
    # own decode -- NOT RUN without a stream, never a pass on absence.
    run("dis_roundtrip", verify_dis_roundtrip, manifest, run_dir)
    # P7: the wake card's five selftest vectors against the checker's own
    # Burnham-Hallock pair and strip-theory quadrature; the host's vectors
    # against the card's where a render.json carries them.
    run("wake_selftest", verify_wake_selftest, manifest, run_dir)
    # P9: what the render host reports it applied from the card's physics
    # blocks, each key graded only where a render.json carries it.
    run("host_physics", verify_host_physics, manifest, run_dir)
    # W2: the ID image's building pixels against the cached footprints, and
    # the runway raster's threshold against the runway plane -- NOT RUN
    # without their evidence, never a pass on absence.
    run("building_vs_footprint", verify_building_vs_footprint, manifest, run_dir)
    run("runway_vs_geometry", verify_runway_vs_geometry, manifest, run_dir)
    # I6 (gap S3): the ground-truth passes -- NOT RUN without their files,
    # never a pass on absence.
    run("normals_vs_depth", verify_normals_vs_depth, manifest, run_dir)
    run("flow_vs_motion", verify_flow_vs_motion, manifest, run_dir)
    run("albedo_range", verify_albedo_range, manifest, run_dir)
    # S1 (gap S1/S2): the PSF on the calibration edge, the blur against
    # the flow, the grey card against the chain -- each NOT RUN without
    # its evidence, never a pass on absence.
    run("psf_slanted_edge", verify_psf_slanted_edge, manifest, run_dir)
    run("blur_vs_flow", verify_blur_vs_flow, manifest, run_dir)
    run("radiometry_grey_card", verify_radiometry_grey_card, manifest, run_dir)
    # S4: the sensing engine side's render.json keys (the linear passes, the
    # velocity read-back, the read-backs, the calibration frame, the
    # accumulation), each graded only when present -- NOT RUN otherwise.
    run("engine_linear_passes", verify_engine_linear_passes, manifest, run_dir)
    run("velocity_readback", verify_velocity_readback, manifest, run_dir)
    run("engine_readbacks", verify_engine_readbacks, manifest, run_dir)
    run("calibration_frame", verify_calibration_frame, manifest, run_dir)
    run("engine_accumulation", verify_engine_accumulation, manifest, run_dir)
    # W3: a night frame's sky against the checker's own K&S sky through the
    # EV100 of record -- NOT RUN without a night frame, never a pass on absence.
    run("night_exposure", verify_night_exposure, manifest, run_dir)
    # S2: the passes as data -- flow against the checker's own projection
    # and z-test, the static null, disparity against the right camera's
    # depth, the points against the depth, the amodal masks against the
    # visible ones; each NOT RUN without its files, never a pass on absence.
    run("flow_vs_keypoints", verify_flow_vs_keypoints, manifest, run_dir)
    run("flow_static_null", verify_flow_static_null, manifest, run_dir)
    run("disparity_vs_right_depth", verify_disparity_vs_right_depth, manifest, run_dir)
    run("points_vs_depth", verify_points_vs_depth, manifest, run_dir)
    run("amodal_contains_visible", verify_amodal_contains_visible, manifest, run_dir)
    # S3: every IR frame declares itself a proxy with the manifest's tables;
    # NOT RUN without an IR frame.
    run("ir_proxy_declared", verify_ir_proxy_declared, manifest, run_dir)
    # R2: the record's own checks -- every readback re-graded, every null
    # test's verdict against its numbers, the uncertainty block's sums --
    # and the FDM-rate instruments' Allan deviation and lever arms by the
    # checker's own estimators; each NOT RUN on absence, never a pass.
    run("applied_readback", verify_applied_readback, manifest)
    run("null_effect", verify_null_effect, manifest)
    run("instrument_allan", verify_instrument_allan, manifest, run_dir)
    run("instrument_lever_arm", verify_instrument_lever_arm, manifest, run_dir)
    run("uncertainty_present", verify_uncertainty_present, manifest)

    if other is not None:
        run("temporal_alignment", verify_alignment, manifest, other)
    elif other_run_dir is not None:
        report.checks.append(Check(
            "temporal_alignment", NOT_RUN,
            f"the --against run {Path(other_run_dir)} has no usable manifest "
            f"(see the against_manifest check above), so there is no second "
            f"frame set to align"))
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
