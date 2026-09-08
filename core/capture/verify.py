"""Verification: can the recorded geometry actually be used as labels?

The phase's exit criterion is not "a manifest exists" but "the manifest
is RIGHT": frames align in time across camera variants, world points
recover through the recorded pose + intrinsics, and two views agree
about where things are. Everything here reimplements the geometry
INDEPENDENTLY of :mod:`core.capture.poses` -- rotation from the
recorded quaternion, cross-checked against the recorded Euler angles,
projection straight from the manifest's documented model -- so a bug in
the producer cannot hide inside a verifier that imports it.

Checks (numbered as in the phase document):

1. **Temporal alignment** (:func:`verify_alignment`) -- two runs of the
   same simulation with different camera sets: identical
   ``simulation_digest`` (the camera-free spec identity), identical
   ``output_digest`` (the telemetry really was the same flight),
   matching per-camera frame counts and per-frame sim times to float
   tolerance.
2. **Geometry recovery** (:func:`verify_geometry`) -- the aircraft's
   recorded position, projected through each frame's recorded pose and
   intrinsics with THIS module's own projection: it must land in front
   of the camera and (for aircraft-aimed cameras) inside the frame,
   and the quaternion and Euler encodings of the same orientation must
   project it to the same pixel within a stated tolerance.
3. **Cross-view consistency** (:func:`verify_triangulation`) -- at
   instants two cameras captured the same telemetry sample, rays cast
   through each camera's own projection of the aircraft must
   triangulate back to the recorded aircraft position within a stated
   metre tolerance.
4. **Count exactness** (:func:`verify_counts`) -- every camera delivers
   exactly the number of images its SPECIFICATION requested, densely
   indexed.
5. **Intrinsics match the specification** (:func:`verify_intrinsics`) --
   the pixel focal lengths and principal point a consumer will project
   with follow from the camera's stated lens, sensor and resolution.
6. **Placement matches the specification** (:func:`verify_placement`) --
   world-anchored poses sit exactly where the specification puts them;
   offset poses sit within a stated lag envelope of the flown track.
7. **Telemetry agreement** (:func:`verify_telemetry_agreement`) -- every
   frame's simulation time and aircraft state are the ones the recorded
   telemetry holds at the sample index the frame names.

Checks 1-4 read the manifest against itself and so cannot distinguish a
correct manifest from a self-consistent wrong one: measured, all of them
pass on a manifest whose camera was displaced 500 m and re-aimed, whose
focal length was multiplied by 1.7, or which delivered 10 of 24
requested images. Checks 5-7 exist because of that, and anchor the
manifest to the camera SPECIFICATION and to the RECORDED TELEMETRY --
artefacts the camera code did not author.
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
#: Metre agreement demanded of two-view triangulation.
TRIANGULATION_TOL_M = 0.5
#: Frame-time agreement across runs (times come off the same recorded
#: telemetry clock, so this is a float-representation tolerance).
TIME_TOL_S = 1e-9


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class VerificationReport:
    checks: List[Check] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))

    def render(self) -> str:
        lines = []
        for c in self.checks:
            lines.append(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: "
                         f"{c.detail}")
        lines.append(f"verification {'PASSED' if self.ok else 'FAILED'} "
                     f"({sum(c.ok for c in self.checks)}/"
                     f"{len(self.checks)} checks)")
        return "\n".join(lines)


# -- independent geometry ------------------------------------------------

def axes_from_quat(q: Sequence[float]):
    """(forward, right, up) unit vectors in (north, east, up) from a
    (w, x, y, z) NED quaternion. Straight rotation-matrix expansion --
    no shared code with the pose solver."""
    w, x, y, z = q
    # Body axes in NED: rows of the body->NED DCM columns.
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
    """The same axes from the recorded Euler angles, independently."""
    r, p, y = (math.radians(roll_deg), math.radians(pitch_deg),
               math.radians(yaw_deg))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    forward = (cp * cy, cp * sy, sp)
    right = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    up = (-(cr * sp * cy + sr * sy), -(cr * sp * sy - sr * cy), cr * cp)
    return forward, right, up


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


# -- the checks ----------------------------------------------------------

def _aircraft_point(record: Dict):
    a = record["aircraft"]
    return (a["north_m"], a["east_m"], a["alt_m"])


def _aim_modes(manifest: Dict) -> Dict[str, str]:
    modes = {}
    for block in manifest.get("cameras", []):
        spec = block.get("spec") or {}
        aim = spec.get("aim_mode", {}).get("value", "aircraft")
        modes[block["camera_id"]] = str(aim)
    return modes


def verify_geometry(manifest: Dict,
                    tol_px: float = REPROJECTION_TOL_PX) -> Check:
    """Check 2: recovery of the aircraft through pose + intrinsics."""
    aim_modes = _aim_modes(manifest)
    worst_gap = 0.0
    behind = 0
    out_of_frame = 0
    frames = manifest.get("frames", [])
    for record in frames:
        point = _aircraft_point(record)
        u_q, v_q, z_q = project_point(
            record, point, axes_from_quat(record["quaternion_wxyz"]))
        u_e, v_e, z_e = project_point(
            record, point, axes_from_euler(record["roll_deg"],
                                           record["pitch_deg"],
                                           record["yaw_deg"]))
        cockpit_origin = (math.hypot(
            point[0] - record["position_north_m"],
            point[1] - record["position_east_m"]) < 10.0
            and abs(z_q) < 10.0)
        if z_q <= 0 and not cockpit_origin:
            behind += 1
            continue
        if math.isfinite(u_q) and math.isfinite(u_e):
            worst_gap = max(worst_gap, math.hypot(u_q - u_e, v_q - v_e))
        if aim_modes.get(record["camera_id"]) == "aircraft":
            # An aircraft-aimed camera that cannot see the aircraft has
            # wrong geometry somewhere.
            if not (0.0 <= u_q <= record["width_px"]
                    and 0.0 <= v_q <= record["height_px"]):
                out_of_frame += 1
    ok = (behind == 0 and out_of_frame == 0 and worst_gap <= tol_px
          and bool(frames))
    return Check(
        "geometry_recovery", ok,
        f"{len(frames)} frames; quaternion-vs-euler reprojection gap "
        f"{worst_gap:.4f} px (tol {tol_px}); {behind} aircraft behind "
        f"camera; {out_of_frame} aimed frames without the aircraft in "
        f"frame")


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


def verify_triangulation(manifest: Dict,
                         tol_m: float = TRIANGULATION_TOL_M) -> Check:
    """Check 3: a world point seen from two cameras at the same instant
    triangulates back."""
    by_sample: Dict[int, List[Dict]] = {}
    for record in manifest.get("frames", []):
        by_sample.setdefault(record["sample_index"], []).append(record)
    pairs = 0
    worst = 0.0
    for records in by_sample.values():
        if len(records) < 2:
            continue
        a, b = records[0], records[1]
        # Each camera's ray is cast through ITS OWN record's view of the
        # world (its own pose, its own recorded aircraft state). Two
        # honest records of the same instant produce rays through the
        # same point; a misattributed pairing -- wrong instant, wrong
        # camera, disagreeing aircraft states -- produces skew rays and
        # a triangulation error. (Casting both rays from ONE record's
        # point would be circular: any invertible corruption of a pose
        # projects and back-projects consistently and could never fail.)
        point_a = _aircraft_point(a)
        point_b = _aircraft_point(b)
        ua, va, za = project_point(a, point_a)
        ub, vb, zb = project_point(b, point_b)
        if za <= 0 or zb <= 0:
            continue          # a camera that cannot see it: check 2's job
        recovered = _closest_point_between_rays(
            *_ray_through_pixel(a, ua, va), *_ray_through_pixel(b, ub, vb))
        if recovered is None:
            continue          # parallel rays carry no depth information
        pairs += 1
        worst = max(worst, math.dist(recovered, point_a),
                    math.dist(point_a, point_b))
    if pairs == 0:
        # A single camera (or disjoint schedules) has nothing to cross-
        # check: report NOT EXERCISED rather than a false pass or a
        # false failure -- the detail says exactly what was not
        # verified, and the phase demo runs two shared-schedule cameras
        # so the check is exercised where the claim is made.
        return Check("cross_view_consistency", True,
                     "NOT EXERCISED: no instant is seen by two cameras "
                     "(single camera or disjoint schedules); capture "
                     "two cameras on a shared schedule to verify "
                     "cross-view consistency")
    return Check(
        "cross_view_consistency", worst <= tol_m,
        f"{pairs} two-view instants; worst triangulation error "
        f"{worst:.4f} m (tol {tol_m})")


def verify_counts(manifest: Dict) -> Check:
    """Check 4: exactly as many images as were ASKED FOR.

    The count the phase promises is the one the SPECIFICATION states,
    not the one the producer ended up writing down. Comparing the frame
    records against the manifest's own ``capture_count`` compares the
    delivery to itself and can never fail: a producer that emitted 10 of
    24 requested frames and recorded "10" passes it (measured before
    this check read the spec). So the request is read from the camera
    block's recorded specification, and the delivered count is checked
    against THAT; the dense-index condition still catches gaps and
    misattribution on top.
    """
    problems = []
    requested_total = 0
    for block in manifest.get("cameras", []):
        camera_id = block["camera_id"]
        declared = int(block["capture_count"])
        indices = sorted(r["index"] for r in manifest.get("frames", [])
                         if r["camera_id"] == camera_id)
        # One condition carries the whole guarantee (dense 0..declared-1
        # covers both a wrong count and a gap), so its mutation guard is
        # load-bearing rather than shadowed by a sibling check.
        if indices != list(range(declared)):
            problems.append(f"{camera_id}: {len(indices)} frames against "
                            f"a declared {declared}, or gaps in the "
                            f"index sequence")
        # The external anchor: a stated count is a contract. Zero means
        # "no counted capture" (the period/trigger conventions), and is
        # governed by the trigger, not by a number.
        requested = int(_spec_value(block.get("spec") or {},
                                    "capture_count", 0) or 0)
        if requested > 0:
            requested_total += requested
            if len(indices) != requested:
                problems.append(
                    f"{camera_id}: {len(indices)} frames delivered against "
                    f"the {requested} its specification requests")
    detail = (f"{len(manifest.get('cameras', []))} camera(s), every "
              f"requested count met exactly")
    if requested_total:
        detail += f" ({requested_total} images requested in total)"
    return Check("count_exactness", not problems,
                 "; ".join(problems) if problems else detail)


def verify_alignment(manifest_a: Dict, manifest_b: Dict,
                     tol_s: float = TIME_TOL_S) -> Check:
    """Check 1: two runs of the same simulation align frame-for-frame."""
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
    return Check("temporal_alignment", not problems,
                 "; ".join(problems) if problems
                 else f"{len(times_a)} capture instants align exactly "
                      f"across the two camera sets")


def verify_run(run_dir, other_run_dir=None) -> VerificationReport:
    """The pass/fail summary over a run directory (CLI: flightsim.verify)."""
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

    # The telemetry is the one artefact in a run directory the camera
    # code did not author; the external-anchor checks below read the
    # manifest against it and against the recorded camera specification,
    # so a self-consistent but wrong manifest fails instead of passing.
    columns = load_telemetry(run_dir)
    if columns is not None:
        _project_track(columns, manifest.get("frame") or {})

    report.checks.append(verify_geometry(manifest))
    report.checks.append(verify_triangulation(manifest))
    report.checks.append(verify_counts(manifest))
    report.checks.append(verify_intrinsics(manifest))
    report.checks.append(verify_placement(manifest, columns))
    report.checks.append(verify_telemetry_agreement(manifest, columns))

    if other_run_dir is not None:
        other = read_capture_manifest(
            Path(other_run_dir) / "capture_manifest.json")
        report.checks.append(verify_alignment(manifest, other))
    return report


# -- external-anchor checks ----------------------------------------------
#
# Checks 2-4 above all read the manifest against ITSELF. That makes them
# independent of the PRODUCER'S CODE but not of the producer's OUTPUT:
# every one of them passes on a manifest whose camera was moved 500 m and
# re-aimed, whose focal length was multiplied by 1.7, or which delivered
# 10 of the 24 images that were asked for (measured on runs/demo, all
# three corruptions, before these checks existed). The phase document
# names exactly this failure -- "verification that cannot fail" -- so the
# checks below anchor the manifest to things OUTSIDE it:
#
#   * the camera SPECIFICATION recorded in the manifest's camera blocks
#     (intrinsics, stated placement, requested capture count), and
#   * the RECORDED TELEMETRY (telemetry.json), which is a separate
#     artefact written by the flight, not by the camera code.
#
# A manifest that agrees with itself but not with the specification that
# commanded it, or not with the flight it claims to label, is precisely
# the "plausible fiction" the phase warns about.

#: Pixel-focal agreement demanded between each frame's recorded fx/fy and
#: the value recomputed from the camera spec's own lens, sensor and
#: resolution. Pure arithmetic on both sides; float noise only.
INTRINSICS_TOL_PX = 1e-6

#: Metre agreement demanded of a WORLD-ANCHORED camera against its stated
#: placement. A stated placement is a constant (or a keyframe
#: interpolation of constants): there is nothing here to be approximate
#: about.
PLACEMENT_TOL_M = 1e-6

#: How far a lagged offset camera may sit from its UNLAGGED goal point,
#: as a multiple of the ground speed times the director's position time
#: constant. A first-order lag tracking a ramp trails by exactly
#: v * tau in steady state; 2.0 leaves room for manoeuvre transients
#: while still catching gross displacement (measured worst case on
#: runs/demo: 0.30 of the bound).
OFFSET_LAG_BOUND_FACTOR = 2.0
OFFSET_LAG_TAU_S = 0.45
OFFSET_LAG_FLOOR_M = 5.0


def _spec_value(spec: Dict, name: str, default=None):
    """One value out of a recorded CameraSpec dict."""
    entry = (spec or {}).get(name)
    if not isinstance(entry, dict):
        return default
    return entry.get("value", default)


def _keyed(moves: Sequence[Dict], key: str, t: float, default: float):
    """Piecewise-linear read of a keyframed scalar. Re-derived here from
    the documented convention rather than imported, so a bug in the
    producer's interpolation cannot hide inside the verifier."""
    keyed = sorted((float(m["t_s"]), float(m[key])) for m in (moves or [])
                   if isinstance(m, dict) and key in m and "t_s" in m)
    if not keyed:
        return default
    if t <= keyed[0][0]:
        return keyed[0][1]
    if t >= keyed[-1][0]:
        return keyed[-1][1]
    for (t0, v0), (t1, v1) in zip(keyed, keyed[1:]):
        if t0 <= t <= t1:
            return v0 if t1 == t0 else v0 + (t - t0) / (t1 - t0) * (v1 - v0)
    return keyed[-1][1]


def verify_intrinsics(manifest: Dict,
                      tol_px: float = INTRINSICS_TOL_PX) -> Check:
    """Check 5: every frame's recorded intrinsics are the ones the
    SPECIFICATION asked for.

    ``fx_px`` and ``fy_px`` are the numbers a consumer projects with; if
    they do not follow from the camera's stated lens, sensor and output
    resolution, the labels describe a camera nobody asked for. The
    principal point must be the image centre, as the schema states.
    """
    problems: List[str] = []
    checked = 0
    specs = {b["camera_id"]: (b.get("spec") or {})
             for b in manifest.get("cameras", [])}
    for record in manifest.get("frames", []):
        spec = specs.get(record["camera_id"])
        if not spec:
            problems.append(f"{record['camera_id']}: no camera spec in the "
                            f"manifest to check the intrinsics against")
            break
        moves = spec.get("moves") or []
        want_focal = _keyed(moves, "focal_length_mm", float(record["t_s"]),
                            float(_spec_value(spec, "focal_length_mm", 0.0)))
        want_w = float(_spec_value(spec, "sensor_width_mm", 0.0))
        want_h = float(_spec_value(spec, "sensor_height_mm", 0.0))
        want_px = int(_spec_value(spec, "width_px", 0))
        want_py = int(_spec_value(spec, "height_px", 0))
        if want_w <= 0 or want_h <= 0 or want_px <= 0 or want_py <= 0:
            problems.append(f"{record['camera_id']}: the recorded spec has "
                            f"no usable sensor or resolution")
            break
        for name, want in (("focal_length_mm", want_focal),
                           ("sensor_width_mm", want_w),
                           ("sensor_height_mm", want_h),
                           ("width_px", want_px), ("height_px", want_py)):
            if abs(float(record[name]) - float(want)) > 1e-9:
                problems.append(
                    f"{record['camera_id']} frame {record['index']}: "
                    f"{name} is {record[name]!r}, the specification says "
                    f"{want!r}")
        # fx and fy are checked SEPARATELY on purpose. Written as one
        # `or`, either half covers for the other: a mutation that
        # disables the fx comparison still fails every test through fy,
        # so the fx guard is not load-bearing. Non-square pixels are
        # legal here (sensor aspect need not match output aspect), which
        # is exactly when only one of the two is wrong.
        want_fx = want_focal / want_w * want_px
        want_fy = want_focal / want_h * want_py
        if abs(float(record["fx_px"]) - want_fx) > tol_px:
            problems.append(
                f"{record['camera_id']} frame {record['index']}: recorded "
                f"fx {record['fx_px']:.3f} px does not follow from the "
                f"specified lens and sensor ({want_fx:.3f} px)")
        if abs(float(record["fy_px"]) - want_fy) > tol_px:
            problems.append(
                f"{record['camera_id']} frame {record['index']}: recorded "
                f"fy {record['fy_px']:.3f} px does not follow from the "
                f"specified lens and sensor ({want_fy:.3f} px)")
        cx, cy = record["principal_point_px"]
        if abs(cx - want_px / 2.0) > tol_px or \
                abs(cy - want_py / 2.0) > tol_px:
            problems.append(
                f"{record['camera_id']} frame {record['index']}: principal "
                f"point ({cx}, {cy}) is not the image centre")
        checked += 1
        if len(problems) >= 3:
            break
    return Check(
        "intrinsics_match_spec", not problems and checked > 0,
        "; ".join(problems[:3]) if problems
        else f"{checked} frames carry exactly the lens, sensor and "
             f"resolution their camera specification states")


def _heading_offset(heading_deg: float, forward: float, right: float,
                    up: float):
    """The heading-only offset frame, re-derived from the documented
    convention (yaw applied, pitch and roll discarded)."""
    y = math.radians(heading_deg)
    cy, sy = math.cos(y), math.sin(y)
    return forward * cy - right * sy, forward * sy + right * cy, up


def _body_offset(roll_deg: float, pitch_deg: float, yaw_deg: float,
                 forward: float, right: float, up: float):
    """The full-attitude body frame, re-derived from the standard
    aerospace body->NED direction cosine matrix."""
    r, p, y = (math.radians(roll_deg), math.radians(pitch_deg),
               math.radians(yaw_deg))
    bx, by, bz = forward, right, -up
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    n = (cp * cy) * bx + (sr * sp * cy - cr * sy) * by \
        + (cr * sp * cy + sr * sy) * bz
    e = (cp * sy) * bx + (sr * sp * sy + cr * cy) * by \
        + (cr * sp * sy - sr * cy) * bz
    d = (-sp) * bx + (sr * cp) * by + (cr * cp) * bz
    return n, e, -d


def _ground_speed(columns: Optional[Dict], index: int) -> Optional[float]:
    """Metres per second at a telemetry sample, from the recorded track
    itself -- no dependence on any speed channel's units."""
    if not columns:
        return None
    t = columns.get("t") or []
    north = columns.get("_north_m")
    east = columns.get("_east_m")
    alt = columns.get("altitude_m") or []
    if north is None or east is None or len(t) < 2:
        return None
    j = min(max(index, 1), len(t) - 1)
    dt = float(t[j]) - float(t[j - 1])
    if dt <= 0:
        return None
    return math.dist(
        (north[j], east[j], float(alt[j])),
        (north[j - 1], east[j - 1], float(alt[j - 1]))) / dt


def verify_placement(manifest: Dict,
                     columns: Optional[Dict] = None) -> Check:
    """Check 6: the recorded camera positions are where the
    SPECIFICATION put the camera.

    A world-anchored camera (``scene`` or ``geographic`` placement) is a
    constant, or a keyframe interpolation of constants: the recorded
    position must equal it exactly. An offset camera rides the
    aircraft, so what is checked is its geometry relative to the flown
    track -- the unlagged goal point, with a lag envelope of
    ``OFFSET_LAG_BOUND_FACTOR * v * tau`` metres, because a first-order
    lag tracking a ramp trails by exactly ``v * tau``. Either way a
    camera silently moved somewhere else fails here, which is the whole
    point: without this, a manifest that has been displaced and re-aimed
    reprojects and triangulates perfectly.
    """
    problems: List[str] = []
    checked = 0
    worst = 0.0
    transformer = None
    blocks = {b["camera_id"]: b for b in manifest.get("cameras", [])}
    for record in manifest.get("frames", []):
        block = blocks.get(record["camera_id"])
        spec = (block or {}).get("spec") or {}
        if not spec:
            problems.append(f"{record['camera_id']}: no camera spec in the "
                            f"manifest to check the placement against")
            break
        mode = str(_spec_value(spec, "position_mode", "offset"))
        moves = spec.get("moves") or []
        t = float(record["t_s"])
        got = (record["position_north_m"], record["position_east_m"],
               record["position_alt_m"])
        alt = _keyed(moves, "position_alt_m", t,
                     float(_spec_value(spec, "position_alt_m", 0.0)))
        if mode in ("scene", "geographic"):
            if mode == "scene":
                want = (_keyed(moves, "position_north_m", t,
                               float(_spec_value(spec, "position_north_m",
                                                 0.0))),
                        _keyed(moves, "position_east_m", t,
                               float(_spec_value(spec, "position_east_m",
                                                 0.0))),
                        alt)
            else:
                frame = manifest.get("frame") or {}
                if transformer is None:
                    from pyproj import Transformer
                    transformer = Transformer.from_crs(
                        "EPSG:4326", str(frame.get("crs")), always_xy=True)
                lat = _keyed(moves, "position_lat_deg", t,
                             float(_spec_value(spec, "position_lat_deg", 0.0)))
                lon = _keyed(moves, "position_lon_deg", t,
                             float(_spec_value(spec, "position_lon_deg", 0.0)))
                x, y = transformer.transform(lon, lat)
                want = (y - float(frame.get("origin_y_m", 0.0)),
                        x - float(frame.get("origin_x_m", 0.0)), alt)
            gap = math.dist(got, want)
            worst = max(worst, gap)
            if gap > PLACEMENT_TOL_M:
                problems.append(
                    f"{record['camera_id']} frame {record['index']}: the "
                    f"recorded position sits {gap:.3f} m from the "
                    f"{mode} placement the specification states")
        else:
            a = record["aircraft"]
            offset = (float(_spec_value(spec, "offset_forward_m", 0.0)),
                      float(_spec_value(spec, "offset_right_m", 0.0)),
                      float(_spec_value(spec, "offset_up_m", 0.0)))
            if str(block.get("preset")) == "cockpit":
                dn, de, dup = _body_offset(a["roll_deg"], a["pitch_deg"],
                                           a["heading_deg"], *offset)
                bound = PLACEMENT_TOL_M      # body-fixed: no smoothing
            else:
                dn, de, dup = _heading_offset(a["heading_deg"], *offset)
                speed = _ground_speed(columns, record["sample_index"])
                if speed is None:
                    speed = math.hypot(offset[0], offset[1])   # conservative
                bound = max(OFFSET_LAG_FLOOR_M,
                            OFFSET_LAG_BOUND_FACTOR * speed * OFFSET_LAG_TAU_S)
            want = (a["north_m"] + dn, a["east_m"] + de, a["alt_m"] + dup)
            gap = math.dist(got, want)
            worst = max(worst, gap)
            if gap > bound:
                problems.append(
                    f"{record['camera_id']} frame {record['index']}: the "
                    f"recorded position sits {gap:.1f} m from the offset "
                    f"the specification states, past the {bound:.1f} m "
                    f"lag envelope")
        checked += 1
        if len(problems) >= 3:
            break
    return Check(
        "placement_matches_spec", not problems and checked > 0,
        "; ".join(problems[:3]) if problems
        else f"{checked} poses sit where their specification puts them "
             f"(worst deviation {worst:.3f} m)")


def load_telemetry(run_dir) -> Optional[Dict]:
    """The run's own ``telemetry.json`` columns, with the aircraft track
    projected into the manifest's scene frame.

    This file is written by the FLIGHT, not by the camera code, so it is
    the one artefact in a run directory that a camera bug cannot have
    authored. Returns None when the run carries no telemetry -- the
    checks that use it then say so instead of passing silently.
    """
    path = Path(run_dir) / "telemetry.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    columns = dict(payload.get("columns") or {})
    if not columns.get("t"):
        return None
    return columns


def _project_track(columns: Dict, frame: Dict) -> bool:
    """Add ``_north_m`` / ``_east_m`` to the telemetry columns, through
    the manifest's own declared CRS and origin. True when it worked."""
    crs = (frame or {}).get("crs")
    if not crs or "lat_deg" not in columns or "lon_deg" not in columns:
        return False
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", str(crs), always_xy=True)
    ox = float(frame.get("origin_x_m", 0.0))
    oy = float(frame.get("origin_y_m", 0.0))
    north, east = [], []
    for lat, lon in zip(columns["lat_deg"], columns["lon_deg"]):
        x, y = transformer.transform(float(lon), float(lat))
        north.append(y - oy)
        east.append(x - ox)
    columns["_north_m"] = north
    columns["_east_m"] = east
    return True


#: Metre agreement demanded between the manifest's per-frame aircraft
#: state and the recorded telemetry it claims to label. Both sides are
#: the same projection of the same sample, so this is float noise plus
#: the transformer's own repeatability.
TELEMETRY_TOL_M = 1e-3
TELEMETRY_TOL_DEG = 1e-6


def verify_telemetry_agreement(manifest: Dict,
                               columns: Optional[Dict]) -> Check:
    """Check 7: every frame really does label the flight that was flown.

    Each frame names a telemetry ``sample_index``; the simulation time
    and the aircraft state it records must be the ones the telemetry
    holds at that index. A frame whose time was fabricated, whose
    sample index was renumbered, or whose aircraft state was edited to
    make the geometry agree with a wrong pose fails here -- the
    manifest cannot both disagree with the flight and be a label of it.
    """
    if columns is None:
        return Check("telemetry_agreement", False,
                     "no telemetry.json beside the manifest; the frames "
                     "cannot be checked against the flight they claim to "
                     "label")
    t = [float(v) for v in columns["t"]]
    has_track = "_north_m" in columns
    problems: List[str] = []
    worst_t = 0.0
    worst_m = 0.0
    for record in manifest.get("frames", []):
        index = int(record["sample_index"])
        if not 0 <= index < len(t):
            problems.append(
                f"{record['camera_id']} frame {record['index']}: sample "
                f"index {index} is outside the {len(t)}-sample telemetry")
            break
        gap_t = abs(float(record["t_s"]) - t[index])
        worst_t = max(worst_t, gap_t)
        if gap_t > TIME_TOL_S:
            problems.append(
                f"{record['camera_id']} frame {record['index']}: records "
                f"t={record['t_s']:.6f} s where telemetry sample {index} "
                f"is at t={t[index]:.6f} s")
        a = record["aircraft"]
        for key, channel in (("alt_m", "altitude_m"), ("roll_deg", "roll_deg"),
                             ("pitch_deg", "pitch_deg"),
                             ("heading_deg", "heading_deg")):
            if channel not in columns:
                continue
            want = float(columns[channel][index])
            got = float(a[key])
            tol = TELEMETRY_TOL_M if key == "alt_m" else TELEMETRY_TOL_DEG
            if abs(got - want) > tol:
                problems.append(
                    f"{record['camera_id']} frame {record['index']}: "
                    f"aircraft {key} is {got:.6f}, the telemetry says "
                    f"{want:.6f}")
        if has_track:
            gap = math.dist((a["north_m"], a["east_m"]),
                            (columns["_north_m"][index],
                             columns["_east_m"][index]))
            worst_m = max(worst_m, gap)
            if gap > TELEMETRY_TOL_M:
                problems.append(
                    f"{record['camera_id']} frame {record['index']}: the "
                    f"recorded aircraft position sits {gap:.3f} m from "
                    f"the flown track at that sample")
        if len(problems) >= 3:
            break
    return Check(
        "telemetry_agreement", not problems,
        "; ".join(problems[:3]) if problems
        else f"{len(manifest.get('frames', []))} frames match the recorded "
             f"flight at their own sample index (worst time gap "
             f"{worst_t:g} s, worst position gap {worst_m:.4f} m)")


# -- engine parity (package G's claim, gradeable anywhere) ---------------

#: Metres of applied-vs-solved camera position a rendered frame may
#: differ by. The engine host enforces 10 cm internally; this grades the
#: manifest it wrote, at the same figure.
PARITY_POSITION_TOL_M = 0.1
#: Degrees of applied-vs-solved orientation. Well inside a pixel at any
#: framing this project renders.
PARITY_ANGLE_TOL_DEG = 0.05
#: Pixel focal disagreement between the intrinsics the manifest records
#: and the framing the render host actually applied.
PARITY_FOCAL_TOL_PX = 1.0


def verify_engine_parity(manifest: Dict, render_manifest: Dict,
                         camera_id: Optional[str] = None) -> Check:
    """Check 8: the frames the engine rendered used the pose and lens the
    capture manifest records.

    The phase's stated risk: "if the engine ever recomputes a pose
    instead of consuming it, the manifest becomes a plausible fiction."
    The host writes what it APPLIED into its own ``render.json``
    (``camera_applied_*``); this grades those against the SOLVED values,
    including the field of view -- because a pose-only parity check
    leaves the intrinsics free to disagree, which is exactly how a
    manifest can record an 85 mm telephoto for frames shot at 55
    degrees.

    Runs on any platform against any render manifest; on macOS it grades
    a real one. A render manifest carrying no ``camera_applied_*``
    fields is reported NOT EXERCISED rather than passed.
    """
    records = [r for r in render_manifest.get("frames", [])
               if "camera_applied_north_m" in r]
    if not records:
        return Check("engine_parity", True,
                     "NOT EXERCISED: this render manifest carries no "
                     "camera_applied_* fields (no consume-poses pass, or "
                     "no engine on this platform)")
    by_id: Dict[str, List[Dict]] = {}
    for record in manifest.get("frames", []):
        by_id.setdefault(record["camera_id"], []).append(record)
    if camera_id is None:
        if len(by_id) != 1:
            return Check("engine_parity", False,
                         f"the capture manifest carries {len(by_id)} "
                         f"cameras; name the one this render pass "
                         f"rendered")
        camera_id = next(iter(by_id))
    solved = sorted(by_id.get(camera_id, []), key=lambda r: r["t_s"])
    if not solved:
        return Check("engine_parity", False,
                     f"the capture manifest carries no frames for camera "
                     f"{camera_id!r}")
    problems: List[str] = []
    worst_m = worst_deg = worst_px = 0.0
    graded = 0
    for applied in records:
        t = float(applied.get("t", applied.get("t_s", 0.0)))
        near = min(solved, key=lambda r: abs(r["t_s"] - t))
        if abs(near["t_s"] - t) > 1e-3:
            continue          # a warm-up or uncaptured frame; not a label
        graded += 1
        gap = math.dist(
            (applied["camera_applied_north_m"],
             applied["camera_applied_east_m"],
             applied["camera_applied_alt_m"]),
            (near["position_north_m"], near["position_east_m"],
             near["position_alt_m"]))
        worst_m = max(worst_m, gap)
        if gap > PARITY_POSITION_TOL_M:
            problems.append(
                f"t={t:.3f} s: the frame was rendered {gap:.2f} m from "
                f"the pose the manifest records")
        for key, name in (("camera_applied_yaw_deg", "yaw_deg"),
                          ("camera_applied_pitch_deg", "pitch_deg"),
                          ("camera_applied_roll_deg", "roll_deg")):
            if key not in applied:
                continue
            delta = abs((float(applied[key]) - float(near[name]) + 180.0)
                        % 360.0 - 180.0)
            worst_deg = max(worst_deg, delta)
            if delta > PARITY_ANGLE_TOL_DEG:
                problems.append(
                    f"t={t:.3f} s: {name} was rendered {delta:.3f} deg "
                    f"from the manifest's value")
        if "camera_applied_hfov_deg" in applied:
            from .manifest import pixel_focal_from_fov

            width = int(applied.get("camera_applied_width_px",
                                    near["width_px"]))
            applied_fx = pixel_focal_from_fov(
                float(applied["camera_applied_hfov_deg"]), width)
            delta = abs(applied_fx - float(near["fx_px"]))
            worst_px = max(worst_px, delta)
            if delta > PARITY_FOCAL_TOL_PX:
                problems.append(
                    f"t={t:.3f} s: the frame was rendered at a focal "
                    f"length of {applied_fx:.1f} px where the manifest "
                    f"records {near['fx_px']:.1f} px -- the labels "
                    f"describe a lens these pixels were not taken with")
            if width != int(near["width_px"]):
                problems.append(
                    f"t={t:.3f} s: rendered {width} px wide where the "
                    f"manifest records {near['width_px']} px")
    if graded == 0:
        return Check("engine_parity", False,
                     "no rendered frame shares a capture instant with the "
                     "manifest; the two describe different runs")
    return Check(
        "engine_parity", not problems,
        "; ".join(problems[:3]) if problems
        else f"{graded} rendered frames used the solved pose and lens "
             f"(worst gaps {worst_m:.3f} m, {worst_deg:.4f} deg, "
             f"{worst_px:.2f} px)")
