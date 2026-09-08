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

    @property
    def ok(self) -> bool:
        """NOT RUN is not a failure -- but it is not a pass either, and
        :meth:`VerificationReport.render` counts it separately."""
        return self.status != FAIL


@dataclass
class VerificationReport:
    checks: List[Check] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, status_or_ok, detail: str) -> None:
        if isinstance(status_or_ok, bool):
            status_or_ok = PASS if status_or_ok else FAIL
        self.checks.append(Check(name, status_or_ok, detail))

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
            offset = (float(_spec_value(spec, "offset_forward_m", 0.0)),
                      float(_spec_value(spec, "offset_right_m", 0.0)),
                      float(_spec_value(spec, "offset_up_m", 0.0)))
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
        return Check("landmark_reprojection", NOT_RUN,
                     f"render.json carried no landmark this manifest also "
                     f"names. ({coverage})")
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

def verify_flight_agreement(manifest: Dict, run_dir=None,
                            tol_m: float = 25.0) -> Check:
    """The aircraft this manifest labels must be the aircraft the frames
    show.

    Poses are solved over a headless pre-run, then the render host flies
    the scenario itself. The camera poses are consumed verbatim, so
    those are exact -- but the AIRCRAFT states in the manifest come from
    the pre-run, and if the host's flight diverges from it the labels
    describe a slightly different flight than the pixels.

    This measures that divergence instead of assuming it away: the
    manifest's aircraft track against the host's own recorded telemetry,
    matched on simulation time. NOT RUN where no host telemetry exists
    (an unrendered capture has only the one flight).
    """
    if run_dir is None:
        return Check("flight_agreement", NOT_RUN,
                     "no run directory given, so the host's telemetry "
                     "cannot be compared against the manifest's")
    path = Path(run_dir) / "telemetry.json"
    if not path.is_file():
        return Check(
            "flight_agreement", NOT_RUN,
            "no host telemetry.json beside the manifest: nothing rendered "
            "here, so there is only one flight and nothing to disagree")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("flight_agreement", NOT_RUN,
                     f"host telemetry could not be read ({exc})")
    columns = payload.get("columns", payload)
    needed = ("t", "lat_deg", "lon_deg", "altitude_m")
    if not all(key in columns for key in needed):
        return Check("flight_agreement", NOT_RUN,
                     f"host telemetry carries no {needed} columns")

    frame_meta = manifest.get("frame") or {}
    try:
        from pyproj import Transformer

        transformer = Transformer.from_crs("EPSG:4326", frame_meta["crs"],
                                           always_xy=True)
    except Exception as exc:
        return Check("flight_agreement", NOT_RUN,
                     f"the manifest's CRS could not be opened ({exc})")

    times = [float(v) for v in columns["t"]]
    if len(times) < 2:
        return Check("flight_agreement", NOT_RUN,
                     "host telemetry has fewer than two samples")

    worst = 0.0
    worst_t = 0.0
    compared = 0
    for record in manifest.get("frames", []):
        t = float(record["t_s"])
        # Nearest host sample to this frame's simulation time.
        index = min(range(len(times)), key=lambda i: abs(times[i] - t))
        if abs(times[index] - t) > 0.5:
            continue
        x, y = transformer.transform(float(columns["lon_deg"][index]),
                                     float(columns["lat_deg"][index]))
        host = (y - float(frame_meta["origin_y_m"]),
                x - float(frame_meta["origin_x_m"]),
                float(columns["altitude_m"][index]))
        gap = math.dist(_aircraft_point(record), host)
        if gap > worst:
            worst, worst_t = gap, t
        compared += 1
    if compared == 0:
        return Check("flight_agreement", NOT_RUN,
                     "no frame time matched a host telemetry sample")
    if worst > tol_m:
        return Check(
            "flight_agreement", FAIL,
            f"the manifest's aircraft track and the host's recorded "
            f"flight differ by up to {worst:.1f} m (at t={worst_t:.2f}s, "
            f"tol {tol_m:g} m) over {compared} frames: the labels "
            f"describe a different flight than the frames show")
    return Check("flight_agreement", PASS,
                 f"{compared} frames; the manifest's aircraft track "
                 f"matches the host's recorded flight to within "
                 f"{worst:.2f} m (tol {tol_m:g} m)")


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

    report.checks.append(verify_intrinsics(manifest))
    report.checks.append(verify_pose_matches_spec(manifest))
    report.checks.append(verify_geometry(manifest))
    report.checks.append(verify_landmark_reprojection(manifest, run_dir))
    report.checks.append(verify_triangulation(manifest, run_dir))
    report.checks.append(verify_counts(manifest))
    report.checks.append(verify_aircraft_consistency(manifest))
    report.checks.append(verify_flight_agreement(manifest, run_dir))
    report.checks.append(verify_capture_times(manifest, run_dir))

    if other_run_dir is not None:
        other = read_capture_manifest(
            Path(other_run_dir) / "capture_manifest.json")
        report.checks.append(verify_alignment(manifest, other))
    else:
        report.checks.append(Check(
            "temporal_alignment", NOT_RUN,
            "needs a second capture of the SAME simulation with a "
            "different camera set: run flightsim.capture again with "
            "other cameras and pass --against <that run dir>"))
    return report
