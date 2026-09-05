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
   instants two cameras captured the same telemetry sample, a ray
   through each record's LABEL (its own projection of its own
   aircraft) must triangulate to one point, and that point must be the
   aircraft: the telemetry's aircraft at that sample AND each record's
   own. The rays are cast from the poses RECOMPUTED from the spec over
   the telemetry (check 8's tracks), never from the record under test
   -- a ray cast from a record's own pose through that record's own
   label passes through its aircraft by construction, whatever the
   pose, so the old check could only ever see two records' aircraft
   disagree (the judge's demonstration: a tower moved 5 m or yawed
   10 deg triangulated "perfectly"). Without ``scenario.yaml`` and
   ``telemetry.json`` beside the manifest the rays come from the
   records themselves and the row SAYS SO: the two records agree on
   the aircraft; the poses are not tested.
4. **Count exactness** (:func:`verify_counts`) -- every camera's frame
   records number exactly its declared capture count, densely indexed.
5. **Engine parity** (:func:`verify_engine_parity`) -- on a machine with
   the engine, the render commandlet's consume-poses pass writes
   ``frames/<camera_id>/render.json`` beside the PNGs: per frame the
   pose it ACTUALLY APPLIED and the simulation time it captured at. The
   applied pose must equal the manifest's solved pose within 10 cm and
   0.1 deg, the applied time must EQUAL the scheduled instant (every
   instant lies on the manifest's fixed-step grid and the engine
   captures on that step; the engine's step is checked against the
   manifest's rate), the PNG named by the frame's index must exist at the
   manifest's size, the aircraft must reproject through the applied
   pose to the pixel the manifest's own projection gives, and the
   aircraft the engine actually DREW (``aircraft_applied_*``, its own
   FDM's state at the capture) must land within a metre budget computed
   from THIS run (the measured one-step host phase plus half a step,
   times the frame's recorded speed over the manifest's rate) of the
   manifest's aircraft and, reprojected through the applied pose,
   within the pixels that budget subtends at the frame's depth; the
   engine's own projection of that aircraft must sit at the labelled
   pixel, and the PNG's window around the label must differ from the
   frame's background -- the clauses that judge the pixels, not only
   the numbers the engine wrote about itself. With no
   render.json at all the check is AWAITING ENGINE FRAMES -- a third
   state that neither passes nor fails, so a headless run can never
   claim parity it did not exercise and never fails for lacking an
   engine.
6. **Flight fidelity** (:func:`verify_flight_fidelity`) -- the manifest
   against the flight it claims to record: ``telemetry.json`` beside
   the manifest must digest to the manifest's ``output_digest`` (the
   same hash the runner computes, reimplemented here), and EVERY frame
   record's ``t_s`` must be the telemetry's own ``t`` at its
   ``sample_index`` and its recorded aircraft altitude, attitude and --
   when the record carries ``lat_deg``/``lon_deg`` -- local north/east
   (projected here through the manifest's own frame block with pyproj,
   never the pose solver) must equal the telemetry at that sample to
   representation tolerance. Checks 2 and 3 grade records against each
   other; this one grades them against the flight, so two views that
   agree with each other but not with the telemetry FAIL here.
7. **Schedule fidelity** (:func:`verify_schedule_fidelity`) -- the
   capture schedule recomputed from ``scenario.yaml``'s cameras over
   ``telemetry.json`` (:mod:`core.capture.schedule`) must match the
   manifest's instants sample-for-sample, per camera, so a shifted
   clock or a moved instant is caught by the run's own verification,
   without a sibling run to align against.

8. **Pose fidelity** (:func:`verify_pose_fidelity`) -- every record's
   camera position, quaternion, Euler angles, focal length, pixel
   focal lengths, principal point, resolution, sensor and clip planes
   against the pose track recomputed from ``scenario.yaml``'s cameras
   over ``telemetry.json`` (:func:`recompute_pose_tracks`, the
   producer's own solver -- stated as such in the phase document, as
   check 7 states it for the scheduler) at the record's sample, to
   representation tolerance, and every camera block's
   ``pose_track_digest`` against the recomputed track's digest,
   verbatim. Before this check the pose was graded against nothing
   outside the manifest: a manifest whose cameras were all moved 30 m,
   or yawed 3 deg with the quaternion and Euler angles moved together,
   or whose lens was scaled 1.5x, verified 7/7.

9. **Aim fidelity** (:func:`verify_aim_fidelity`) -- the promise the
   header prints beside each camera, graded: for every record the
   telemetry's aircraft (projected here with pyproj) is put through
   the record's own pose and lens, and that pixel must be where the
   preset promises it -- the image centre for an explicit camera
   aimed at the aircraft; for the lagged presets (chase, wingman,
   tower, ground) the pixel the AIM_LAG_S first-order lag of the
   aircraft track, recomputed HERE over the telemetry, predicts at
   that sample; for a cockpit the pixel the spec's lens offsets put
   the cg at along the body axis, with the record's axes compared to
   the telemetry's attitude directly. The ``off-aim px`` column of the
   schedule table was a number nobody graded; this check grades it
   against a computed expectation, to representation tolerance. A
   camera whose aim mode promises nothing about the aircraft (point,
   bearing) is named as not graded.

Checks 6, 7, 8 and 9 are SKIPPED by name when the file they need is
not beside the manifest; a skipped check is never a pass.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:                                   # pragma: no cover
    from .poses import PoseTrack

#: Pixel agreement demanded between the quaternion and Euler encodings
#: of one recorded orientation.
REPROJECTION_TOL_PX = 0.5
#: Metre agreement demanded of two-view triangulation.
TRIANGULATION_TOL_M = 0.5
#: Frame-time agreement across runs (times come off the same recorded
#: telemetry clock, so this is a float-representation tolerance).
TIME_TOL_S = 1e-9

#: Flight fidelity (check 6): the manifest's per-frame aircraft state
#: and instant against telemetry.json at the record's sample. The
#: manifest copies the telemetry's own numbers (altitude, attitude, t)
#: and projects lat/lon through the same CRS, so every tolerance is
#: representation slack, never a physical allowance: a record that
#: differs from the flight by more than this describes a different
#: flight.
FLIGHT_TIME_TOL_S = 1e-9
FLIGHT_POSITION_TOL_M = 1e-6
FLIGHT_ANGLE_TOL_DEG = 1e-6
#: The files checks 6, 7 and 8 read beside the manifest.
TELEMETRY_FILE = "telemetry.json"
SCENARIO_FILE = "scenario.yaml"

#: Pose fidelity (check 8): every record's pose and lens against the
#: track recomputed from the spec's cameras over the telemetry, at the
#: record's sample. The manifest copies the solver's numbers verbatim
#: (core.capture.manifest takes PoseTrack.sample as is and derives only
#: fx/fy by one multiplication), so every tolerance is representation
#: slack: a record that differs by more describes a camera the spec did
#: not command. Integer fields (resolution) and the digest are exact.
POSE_POSITION_TOL_M = 1e-6
POSE_ANGLE_TOL_DEG = 1e-6
POSE_QUATERNION_TOL = 1e-9
POSE_LENS_TOL_PX = 1e-6
POSE_LENS_TOL_MM = 1e-9

#: Aim fidelity (check 9): the aircraft's pixel through the record
#: against the pixel the preset's promise predicts, both computed here.
#: Representation slack: the promise is a look direction, a rotation
#: and a projection, and the record encodes the same direction; the
#: measured worst on the committed examples is below 1e-9 px.
AIM_TOL_PX = 1e-6
#: The record's forward axis against the telemetry's body axis for a
#: cockpit camera (the preset inherits the full attitude).
AIM_AXIS_TOL_DEG = 1e-6

#: Engine parity (check 5): the pose the engine APPLIED, written back per
#: frame by the render commandlet's consume-poses pass, against the pose
#: the manifest says was solved. The same 10 cm the commandlet itself
#: fails on, and 0.1 deg of orientation.
ENGINE_POSITION_TOL_M = 0.10
ENGINE_ANGLE_TOL_DEG = 0.1
#: Applied capture time against the scheduled instant. Every instant lies
#: on the spec's fixed-step grid (core.capture.schedule refuses one that
#: does not, by name, before any editor time) and the commandlet captures
#: on the step whose run clock EQUALS the instant (its clock origin, read
#: before the first step, is subtracted and recorded), so the tolerance
#: is representation slack, not a step: a capture one step late is a
#: different FDM state and fails by name here. The grid itself is the
#: MANIFEST's ``rate_hz``; render.json's ``step_s`` is a fact to check
#: against it, never the tolerance.
ENGINE_TIME_TOL_S = 1.0e-6
#: The engine's step against the manifest's 1/rate_hz: exact to float
#: representation.
ENGINE_STEP_TOL_S = 1.0e-9
#: The instant the engine interpolated the applied pose AT (``t_pose_s``)
#: against the scheduled instant: the commandlet applies the pose at the
#: scheduled instant itself, never at the engine clock, so this is exact
#: by construction and the tolerance is float representation only. A
#: pose taken at the clock instead would move a chase camera ~1.4 m per
#: step at 320 kt and fail the 10 cm clause; naming the cause here is
#: what tells that failure from a real drift.
ENGINE_POSE_TIME_TOL_S = 1.0e-6
#: The aircraft reprojected through the applied pose against the
#: manifest's own projection. 0.1 deg at the default 1244 px focal is
#: 2.2 px and 10 cm at 100 m is 1.2 px: 3 px is what the pose tolerances
#: above already permit, not slack on top of them.
ENGINE_REPROJECTION_TOL_PX = 3.0
#: The aircraft the engine DREW (``aircraft_applied_*``: its own FDM's
#: state at the capture, in the card frame) against the manifest's
#: aircraft (the headless flight) -- the host-parity budget, computed PER
#: RUN from the manifest, never a constant for some other aircraft:
#:
#:     budget_m = (HOST_PHASE_STEPS + HOST_PHASE_MARGIN_STEPS)
#:                x speed_mps / rate_hz
#:
#: with the frame's own ``aircraft.speed_mps`` (the recorded true
#: airspeed) and the manifest's ``rate_hz``. Measured basis
#: (docs/VALIDITY.md, Gate 5 and the parity matrix): the two hosts' calm
#: flights agree to 3.6e-4 m in altitude and 1e-5 deg in attitude, and
#: differ in position by a CONSTANT phase of EXACTLY ONE fixed step (1.24
#: m at 250 kt: the headless host integrates one extra step during
#: engine start) -- HOST_PHASE_STEPS. The margin is half a step: the
#: phase was measured at one envelope point, and half a step covers a
#: trim start that differs by less than a step WITHOUT admitting a whole
#: second step -- which is the clock offset the time clause above
#: refuses by name, so the two clauses cannot contradict each other. The
#: arithmetic is printed in the detail line ("budget 2.08 m = 1.5 steps x
#: 1.384 m/step"). In pixels the budget is GRADED per frame: the pose
#: tolerance above plus what the budget subtends at the frame's depth
#: (fx x budget / depth).
HOST_PHASE_STEPS = 1.0
HOST_PHASE_MARGIN_STEPS = 0.5


def drawn_aircraft_budget_m(speed_mps: float, rate_hz: float) -> Dict[str, float]:
    """The drawn-aircraft budget for one frame: the numbers the detail
    line prints (``budget_m``, ``steps``, ``step_m``)."""
    step_m = float(speed_mps) / float(rate_hz)
    steps = HOST_PHASE_STEPS + HOST_PHASE_MARGIN_STEPS
    return {"budget_m": steps * step_m, "steps": steps, "step_m": step_m,
            "speed_mps": float(speed_mps), "rate_hz": float(rate_hz)}

#: The engine's OWN measurement of where it drew the aircraft:
#: ``aircraft_px`` / ``aircraft_py`` / ``aircraft_visible`` per frame, the
#: aircraft actor projected through the capture component's transform and
#: field of view by the commandlet itself (the same call its landmarks
#: block makes). It is graded twice: against the manifest's labelled pixel
#: within the graded budget above (the engine's projection of what it
#: drew, independent of any projection computed here), and against THIS
#: module's projection of the drawn aircraft through the applied pose
#: within ENGINE_REPROJECTION_TOL_PX -- the capture FOV is
#: 2 atan(sensor / 2 focal), so the engine's tan-based projection and the
#: manifest's fx-based one describe one lens and must agree to the pose
#: tolerance, not merely to the budget.
#:
#: Pixel content: the numbers above are what the engine wrote about
#: itself; a mesh that failed to load leaves them perfect and the frame
#: empty (measured: the 747 body absent from every frame while captures
#: "succeeded"). So a window of the PNG around the labelled pixel -- half
#: size the larger of ENGINE_LABEL_WINDOW_HALF_PX and the frame's graded
#: pixel budget, widened to the engine's reported screen box -- must
#: differ from a same-size background window at the frame corner
#: farthest from the label: the larger of the mean-luminance and the
#: luminance-spread differences, ``contrast``, at least
#: ENGINE_LABEL_CONTRAST_MIN of 255. A flat frame, or a frame drawn
#: anywhere but at the label, fails by frame with both windows' numbers.
ENGINE_LABEL_WINDOW_HALF_PX = 16
ENGINE_LABEL_CONTRAST_MIN = 8.0

#: The check name and the detail prefix the page and the CLI key on.
ENGINE_PARITY_CHECK = "engine_parity"
AWAITING_ENGINE_FRAMES = "awaiting engine frames"


@dataclass(frozen=True)
class Check:
    """One named check. ``ok`` is True (PASS), False (FAIL) or None --
    AWAITING (the check could not be exercised on this machine: engine
    parity without engine frames) or, when ``skipped`` names a reason,
    SKIPPED (the check had nothing to grade: cross-view consistency with
    one camera). Neither None state is a pass nor a failure, neither is
    counted among the checks that ran, and each is reported in its own
    word.

    ``measured`` / ``tolerance`` / ``unit`` are the number the verdict
    rests on and the bound it was graded against (the table's MEASURED
    and TOLERANCE columns; ``measured_text`` / ``tolerance_text``
    override the cell for a check whose verdict rests on several
    numbers). ``where`` names the worst offender -- camera, frame index,
    instant, sample or run -- so a FAIL says where, and a PASS says what
    its worst case was. ``data`` carries structured numbers the page
    renders (per-camera counts for the engine check)."""

    name: str
    ok: Optional[bool]
    detail: str
    data: Optional[Dict] = None
    measured: Optional[float] = None
    tolerance: Optional[float] = None
    unit: str = ""
    where: str = ""
    skipped: Optional[str] = None
    measured_text: Optional[str] = None
    tolerance_text: Optional[str] = None

    @property
    def status(self) -> str:
        if self.ok is None:
            return "SKIPPED" if self.skipped else "AWAITING"
        return "PASS" if self.ok else "FAIL"

    @property
    def measured_cell(self) -> str:
        """The MEASURED column: the override, the number with its unit,
        or the detail when the check carries no number."""
        if self.measured_text is not None:
            return self.measured_text
        if self.measured is not None:
            return _number(self.measured, self.unit)
        return self.detail

    @property
    def tolerance_cell(self) -> str:
        if self.tolerance_text is not None:
            return self.tolerance_text
        if self.tolerance is not None:
            return _number(self.tolerance, self.unit)
        return "-"

    def to_dict(self) -> Dict:
        """The check as data: every table column, the prose detail, and
        the structured block -- verify.json's per-check record."""
        record = {
            "name": self.name, "ok": self.ok, "status": self.status,
            "detail": self.detail,
            "measured": self.measured, "tolerance": self.tolerance,
            "unit": self.unit, "measured_text": self.measured_cell,
            "tolerance_text": self.tolerance_cell, "where": self.where,
            "skipped_reason": self.skipped,
        }
        if self.data is not None:
            record["data"] = self.data
        return record


def _number(value: float, unit: str) -> str:
    """A measured or tolerance number for the table: full precision
    where it is small (a 1e-09 s tolerance stays 1e-09), four decimals
    otherwise, the unit appended."""
    value = float(value)
    if value == 0.0:
        text = "0"
    elif abs(value) < 1e-3 or abs(value) >= 1e6:
        text = f"{value:.3g}"
    else:
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        if "." not in text and abs(value) < 1e3:
            text = f"{value:.1f}" if value != int(value) else text
    return f"{text} {unit}".strip()


#: The verification table's column heads, in order.
TABLE_COLUMNS = ("CHECK", "STATUS", "MEASURED", "TOLERANCE", "WHERE")


@dataclass
class VerificationReport:
    checks: List[Check] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Every check that RAN passed. An awaiting or skipped check (ok
        None) is excluded on purpose: it neither passes nor fails, and
        the report says so in render()."""
        return all(c.ok is not False for c in self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.ok is True)

    @property
    def failed(self) -> List[Check]:
        return [c for c in self.checks if c.ok is False]

    @property
    def awaiting(self) -> List[Check]:
        return [c for c in self.checks if c.ok is None and not c.skipped]

    @property
    def skipped(self) -> List[Check]:
        """Checks that had nothing to grade (ok None with a reason):
        never counted as passed, never counted as ran."""
        return [c for c in self.checks if c.ok is None and c.skipped]

    @property
    def ran(self) -> int:
        return len(self.checks) - len(self.awaiting) - len(self.skipped)

    def add(self, name: str, ok: Optional[bool], detail: str, **fields) -> None:
        self.checks.append(Check(name, ok, detail, **fields))

    def summary(self) -> str:
        """"verification PASSED (5/5 checks; 1 awaiting engine frames:
        engine_parity)" -- skipped checks named with their reason and
        counted in neither number."""
        text = (f"verification {'PASSED' if self.ok else 'FAILED'} "
                f"({self.passed}/{self.ran} checks")
        if self.failed:
            text += "; FAILED: " + ", ".join(c.name for c in self.failed)
        if self.skipped:
            text += (f"; {len(self.skipped)} skipped: "
                     + ", ".join(f"{c.name} ({c.skipped})"
                                 for c in self.skipped))
        if self.awaiting:
            text += (f"; {len(self.awaiting)} {AWAITING_ENGINE_FRAMES}: "
                     + ", ".join(c.name for c in self.awaiting))
        return text + ")"

    def table_rows(self) -> List[Tuple[str, str, str, str, str]]:
        """One (check, status, measured, tolerance, where) row per
        check, the same cells the JSON carries."""
        rows = []
        for c in self.checks:
            if c.ok is None:
                rows.append((c.name, c.status, "-", "-",
                             c.skipped or c.detail))
            else:
                rows.append((c.name, c.status, c.measured_cell,
                             c.tolerance_cell, c.where or "-"))
        return rows

    def table(self, indent: str = "  ") -> str:
        """The fixed-width verification table: CHECK, STATUS, MEASURED,
        TOLERANCE, WHERE; one row per check, columns padded to the
        widest cell."""
        rows = [TABLE_COLUMNS] + self.table_rows()
        widths = [max(len(str(r[i])) for r in rows) for i in range(4)]
        lines = []
        for row in rows:
            cells = [f"{str(row[i]):<{widths[i]}}" for i in range(4)]
            lines.append((indent + "  ".join(cells) + "  " + str(row[4]))
                         .rstrip())
        return "\n".join(lines)

    def render(self) -> str:
        """The table, then -- only for the rows that did not PASS -- one
        ``[STATUS] name: detail`` line each (what a FAIL found, why a
        check was SKIPPED or is AWAITING), then the summary line. A
        PASS is rendered ONCE, in the table: its number, its tolerance
        and its worst case are the row, and a second rendering of the
        same number in prose is a second number for the reader to
        choose between. The prose detail of every check, PASS
        included, stays in :meth:`to_dict` (verify.json)."""
        lines = [self.table()]
        noted = [c for c in self.checks if c.ok is not True]
        if noted:
            lines.append("  detail:")
            for c in noted:
                lines.append(f"  [{c.status}] {c.name}: {c.detail}")
        lines.append(self.summary())
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """verify.json, the page and --json all read THIS: the report as
        data. ``ok`` is decided by the checks that ran, exactly as the
        property is; awaiting and skipped checks are listed by name and
        counted in neither ``passed`` nor ``ran``."""
        return {
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
            "passed": self.passed,
            "ran": self.ran,
            "failed": [c.name for c in self.failed],
            "awaiting": [c.name for c in self.awaiting],
            "skipped": [{"name": c.name, "reason": c.skipped}
                        for c in self.skipped],
            "summary": self.summary(),
            "table": self.table_rows(),
        }


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
    worst_at = None
    behind = 0
    behind_at = None
    out_of_frame = 0
    out_at = None
    frames = manifest.get("frames", [])
    for record in frames:
        point = _aircraft_point(record)
        here = _frame_words(record)
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
            behind_at = behind_at or here
            continue
        if math.isfinite(u_q) and math.isfinite(u_e):
            gap = math.hypot(u_q - u_e, v_q - v_e)
            if worst_at is None or gap > worst_gap:
                worst_gap, worst_at = gap, here
        if aim_modes.get(record["camera_id"]) == "aircraft":
            # An aircraft-aimed camera that cannot see the aircraft has
            # wrong geometry somewhere.
            if not (0.0 <= u_q <= record["width_px"]
                    and 0.0 <= v_q <= record["height_px"]):
                out_of_frame += 1
                out_at = out_at or (f"{here} at ({u_q:.1f}, {v_q:.1f}) px "
                                    f"of {record['width_px']}x"
                                    f"{record['height_px']}")
    ok = (behind == 0 and out_of_frame == 0 and worst_gap <= tol_px
          and bool(frames))
    where = (f"worst {worst_at}" if worst_at else "no frames")
    if behind:
        where += f"; first behind the camera: {behind_at}"
    if out_of_frame:
        where += f"; first out of frame: {out_at}"
    return Check(
        "geometry_recovery", ok,
        f"{len(frames)} frames; quaternion-vs-euler reprojection gap "
        f"{worst_gap:.4f} px (tol {tol_px}) at {worst_at or 'no frame'}; "
        f"{behind} aircraft behind camera"
        + (f" (first {behind_at})" if behind else "")
        + f"; {out_of_frame} aimed frames without the aircraft in frame"
        + (f" (first {out_at})" if out_of_frame else ""),
        measured=worst_gap, tolerance=tol_px, unit="px", where=where,
        data={"frames": len(frames), "behind": behind,
              "out_of_frame": out_of_frame, "worst_frame": worst_at,
              "first_behind": behind_at, "first_out_of_frame": out_at})


def _frame_words(record: Dict) -> str:
    """"chase0 #3 t=1.508 s": one frame, named the way the manifest and
    the PNG name it."""
    return (f"{record['camera_id']} #{int(record['index'])} "
            f"t={float(record['t_s']):.3f} s")


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
                         tol_m: float = TRIANGULATION_TOL_M,
                         tracks: Optional[Dict[str, "PoseTrack"]] = None,
                         columns: Optional[Dict[str, Sequence[float]]] = None
                         ) -> Check:
    """Check 3: a world point seen from two cameras at the same instant
    triangulates back -- to the aircraft the telemetry recorded, and to
    the aircraft each record labels.

    Each ray goes through the record's LABEL: the record's own
    projection of its own aircraft, the pixel a consumer of the
    manifest would draw the box around. Where the ray STARTS is what
    makes the check independent of the record: with ``tracks`` (the
    poses recomputed from the spec over the telemetry,
    :func:`recompute_pose_tracks`) and ``columns`` (the telemetry), the
    ray is cast from the RECOMPUTED pose and lens at the record's
    sample, and the recovered point is graded against the telemetry's
    aircraft at that sample (projected here with pyproj) as well as
    against both records' own aircraft. A record whose camera was
    moved or rotated labels the wrong pixel, and a ray from the true
    pose through the wrong pixel misses. Without the two, the rays come
    from the records themselves (``mode`` ``records-only``): two honest
    records of one instant still triangulate, disagreeing aircraft
    states still fail, but a pose corruption cannot be seen -- and the
    WHERE column says so."""
    by_sample: Dict[int, List[Dict]] = {}
    for record in manifest.get("frames", []):
        by_sample.setdefault(record["sample_index"], []).append(record)
    frame_block = manifest.get("frame") or {}
    independent_possible = tracks is not None and columns is not None
    pairs = 0
    independent_pairs = 0
    worst = 0.0
    worst_at = None
    for sample_index, records in sorted(by_sample.items()):
        if len(records) < 2:
            continue
        a, b = records[0], records[1]
        point_a = _aircraft_point(a)
        point_b = _aircraft_point(b)
        # The labels: each record's own pixel for its own aircraft.
        ua, va, za = project_point(a, point_a)
        ub, vb, zb = project_point(b, point_b)
        if za <= 0 or zb <= 0:
            continue          # a camera that cannot see it: check 2's job
        # Where the rays start. Independent: the pose the spec commands
        # at this sample, and the flight's aircraft as the target.
        cast_a, cast_b, target = a, b, point_a
        if independent_possible:
            expected_a = track_record(tracks.get(a["camera_id"]),
                                      int(sample_index))
            expected_b = track_record(tracks.get(b["camera_id"]),
                                      int(sample_index))
            flight = telemetry_state_at(columns, frame_block,
                                        int(sample_index)) \
                if 0 <= int(sample_index) < len(columns.get("t", [])) \
                else None
            if (expected_a is not None and expected_b is not None
                    and flight is not None
                    and flight["north_m"] is not None
                    and flight["alt_m"] is not None):
                cast_a, cast_b = expected_a, expected_b
                target = (flight["north_m"], flight["east_m"],
                          flight["alt_m"])
                independent_pairs += 1
        recovered = _closest_point_between_rays(
            *_ray_through_pixel(cast_a, ua, va),
            *_ray_through_pixel(cast_b, ub, vb))
        if recovered is None:
            continue          # parallel rays carry no depth information
        pairs += 1
        # One point: where the flight was (independent mode) and where
        # each record says the aircraft was.
        error = max(math.dist(recovered, target),
                    math.dist(recovered, point_a),
                    math.dist(recovered, point_b))
        if worst_at is None or error > worst:
            worst = error
            worst_at = (f"sample {int(sample_index)} t={float(a['t_s']):.3f} s "
                        f"({a['camera_id']} #{int(a['index'])} with "
                        f"{b['camera_id']} #{int(b['index'])})")
    cameras = len(manifest.get("cameras", []))
    if pairs == 0:
        # A single camera (or disjoint schedules) has nothing to cross-
        # check: SKIPPED, with the reason, rather than a false pass or a
        # false failure -- ok None, counted in neither passed nor ran;
        # the phase demo runs two shared-schedule cameras so the check
        # is exercised where the claim is made.
        reason = ("single camera" if cameras < 2
                  else "disjoint schedules: no instant is seen by two "
                       "cameras")
        return Check("cross_view_consistency", None,
                     f"NOT EXERCISED ({reason}): no instant is seen by "
                     f"two cameras; capture two cameras on a shared "
                     f"schedule to verify cross-view consistency",
                     skipped=reason, unit="m", tolerance=tol_m,
                     data={"pairs": 0, "cameras": cameras})
    if independent_pairs == pairs:
        mode = "independent"
        basis = ("rays from the poses recomputed from the spec through "
                 "each record's own label, against the telemetry's "
                 "aircraft")
    elif independent_pairs == 0:
        mode = "records-only"
        basis = ("rays from the records' own poses: the two records agree "
                 "on the aircraft; the poses are not tested here"
                 + ("" if independent_possible else
                    f" (no {SCENARIO_FILE} or {TELEMETRY_FILE} beside the "
                    f"manifest)"))
    else:
        mode = "mixed"
        basis = (f"{independent_pairs} of {pairs} instants cast from the "
                 f"recomputed poses; the rest from the records' own "
                 f"(a camera the spec does not carry, or a sample past "
                 f"the telemetry)")
    return Check(
        "cross_view_consistency", worst <= tol_m,
        f"{pairs} two-view instants ({basis}); worst triangulation error "
        f"{worst:.4f} m (tol {tol_m}) at {worst_at}",
        measured=worst, tolerance=tol_m, unit="m",
        where=f"{pairs} two-view instants; worst {worst_at}; {basis}",
        data={"pairs": pairs, "cameras": cameras, "worst_at": worst_at,
              "mode": mode, "independent_pairs": independent_pairs})


def verify_counts(manifest: Dict) -> Check:
    """Check 4: per-camera frame records number exactly the declared
    capture count, densely indexed from zero."""
    problems = []
    per_camera = []
    counts = {}
    for block in manifest.get("cameras", []):
        camera_id = block["camera_id"]
        declared = int(block["capture_count"])
        indices = sorted(r["index"] for r in manifest.get("frames", [])
                         if r["camera_id"] == camera_id)
        counts[camera_id] = {"declared": declared, "found": len(indices)}
        per_camera.append(f"{camera_id} {len(indices)}/{declared}")
        # One condition carries the whole guarantee (dense 0..declared-1
        # covers both a wrong count and a gap), so its mutation guard is
        # load-bearing rather than shadowed by a sibling check.
        if indices != list(range(declared)):
            missing = sorted(set(range(declared)) - set(indices))
            extra = sorted(set(indices) - set(range(declared)))
            found = (" (missing index "
                     f"{', '.join(str(i) for i in missing[:4])}"
                     + (f"; unexpected index "
                        f"{', '.join(str(i) for i in extra[:4])}"
                        if extra else "") + ")") if missing or extra else ""
            # Say what was found -- a wrong count, or the right count
            # with the wrong indices -- never "or".
            if len(indices) != declared:
                problems.append(f"{camera_id}: {len(indices)} frames "
                                f"against a declared {declared}{found}")
            else:
                problems.append(f"{camera_id}: {declared} frames as "
                                f"declared but not indexed 0.."
                                f"{declared - 1}{found}")
    found = sum(c["found"] for c in counts.values())
    declared_total = sum(c["declared"] for c in counts.values())
    return Check("count_exactness", not problems,
                 "; ".join(problems) if problems
                 else f"{len(manifest.get('cameras', []))} camera(s), "
                      f"every declared count met exactly",
                 measured=float(found), tolerance=float(declared_total),
                 unit="frames",
                 measured_text=(f"{found} frames = "
                                + " + ".join(str(c["found"])
                                             for c in counts.values())
                                if counts else "0 frames"),
                 tolerance_text=f"exactly {declared_total}",
                 where=", ".join(per_camera) or "no cameras",
                 data={"cameras": counts})


# -- the flight the manifest claims to record ---------------------------

def read_telemetry_columns(run_dir) -> Optional[Dict[str, List[float]]]:
    """The recorded telemetry columns beside a manifest
    (``telemetry.json``, the recorder's own JSON: ``columns`` keyed by
    channel), or None when the file is not there."""
    path = Path(run_dir) / TELEMETRY_FILE
    if not path.is_file():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    columns = record.get("columns", record)
    if not isinstance(columns, dict) or "t" not in columns:
        return None
    return columns


def telemetry_digest(columns: Dict[str, Sequence[float]]) -> str:
    """SHA-256 over the recorded columns, exactly as the runner
    computes ``output_digest`` (names sorted, every value's ``repr``):
    reimplemented here so the verifier does not import the producer."""
    import hashlib

    h = hashlib.sha256()
    for name in sorted(columns):
        h.update(name.encode())
        for value in columns[name]:
            h.update(repr(value).encode())
    return h.hexdigest()


def telemetry_state_at(columns: Dict[str, Sequence[float]],
                       frame_block: Optional[Dict], sample_index: int
                       ) -> Dict[str, Optional[float]]:
    """The flight at one telemetry sample, in the manifest's own frame:
    ``t_s``, ``alt_m``, ``roll_deg``, ``pitch_deg``, ``heading_deg``
    and, when the record carries ``lat_deg``/``lon_deg`` and the
    manifest names its CRS and projected origin, ``north_m``/``east_m``
    projected HERE with pyproj (the manifest's documented frame: the
    CRS, minus the origin's projected coordinates) -- never through the
    pose solver's SceneFrame."""
    i = int(sample_index)
    state: Dict[str, Optional[float]] = {
        "t_s": float(columns["t"][i]),
        "alt_m": float(columns["altitude_m"][i])
        if "altitude_m" in columns else None,
        "roll_deg": float(columns["roll_deg"][i])
        if "roll_deg" in columns else None,
        "pitch_deg": float(columns["pitch_deg"][i])
        if "pitch_deg" in columns else None,
        "heading_deg": float(columns["heading_deg"][i])
        if "heading_deg" in columns else None,
        "north_m": None, "east_m": None,
    }
    block = frame_block or {}
    if ("lat_deg" in columns and "lon_deg" in columns and block.get("crs")
            and block.get("origin_x_m") is not None
            and block.get("origin_y_m") is not None):
        from pyproj import Transformer

        forward = Transformer.from_crs("EPSG:4326", str(block["crs"]),
                                       always_xy=True)
        x, y = forward.transform(float(columns["lon_deg"][i]),
                                 float(columns["lat_deg"][i]))
        state["north_m"] = float(y) - float(block["origin_y_m"])
        state["east_m"] = float(x) - float(block["origin_x_m"])
    return state


def verify_flight_fidelity(manifest: Dict,
                           columns: Optional[Dict[str, Sequence[float]]],
                           time_tol_s: float = FLIGHT_TIME_TOL_S,
                           position_tol_m: float = FLIGHT_POSITION_TOL_M,
                           angle_tol_deg: float = FLIGHT_ANGLE_TOL_DEG
                           ) -> Check:
    """Check 6: every record's instant and aircraft state against the
    telemetry at its sample, and the telemetry's digest against the
    manifest's ``output_digest``. ``columns`` None: SKIPPED by name."""
    tolerance_text = (f"{time_tol_s:g} s, {position_tol_m:g} m, "
                      f"{angle_tol_deg:g} deg")
    if columns is None:
        return Check("flight_fidelity", None,
                     f"NOT EXERCISED (no {TELEMETRY_FILE} beside the "
                     f"manifest): the records were not compared with the "
                     f"flight; verify the run directory capture wrote",
                     skipped=f"no {TELEMETRY_FILE} beside the manifest",
                     tolerance_text=tolerance_text,
                     data={"telemetry": None})
    frames = manifest.get("frames", [])
    n = len(columns.get("t", []))
    frame_block = manifest.get("frame") or {}
    problems: List[str] = []
    worst = {"time_s": 0.0, "position_m": 0.0, "angle_deg": 0.0}
    worst_at = {"time_s": None, "position_m": None, "angle_deg": None}
    positions_compared = 0
    out_of_range = 0
    for record in frames:
        here = _frame_words(record)
        i = int(record["sample_index"])
        if not 0 <= i < n:
            out_of_range += 1
            problems.append(f"{here}: sample_index {i} outside the "
                            f"telemetry's {n} samples")
            continue
        flight = telemetry_state_at(columns, frame_block, i)
        gap_t = abs(float(record["t_s"]) - flight["t_s"])
        if worst_at["time_s"] is None or gap_t > worst["time_s"]:
            worst["time_s"], worst_at["time_s"] = gap_t, (
                f"{here} (telemetry t={flight['t_s']:.6f} s at sample {i})")
        aircraft = record["aircraft"]
        gaps = []
        if flight["alt_m"] is not None:
            gaps.append(abs(float(aircraft["alt_m"]) - flight["alt_m"]))
        if flight["north_m"] is not None:
            gaps.append(abs(float(aircraft["north_m"]) - flight["north_m"]))
            gaps.append(abs(float(aircraft["east_m"]) - flight["east_m"]))
            positions_compared += 1
        gap_p = math.sqrt(sum(g * g for g in gaps)) if gaps else 0.0
        if worst_at["position_m"] is None or gap_p > worst["position_m"]:
            worst["position_m"], worst_at["position_m"] = gap_p, (
                f"{here} (recorded aircraft "
                f"{float(aircraft['north_m']):.3f} N, "
                f"{float(aircraft['east_m']):.3f} E, "
                f"{float(aircraft['alt_m']):.3f} m; telemetry "
                + (f"{flight['north_m']:.3f} N, {flight['east_m']:.3f} E, "
                   if flight["north_m"] is not None else "")
                + (f"{flight['alt_m']:.3f} m" if flight["alt_m"] is not None
                   else "no altitude channel")
                + f" at sample {i})")
        gap_a = 0.0
        for key in ("roll_deg", "pitch_deg", "heading_deg"):
            if flight[key] is not None:
                gap_a = max(gap_a, _angle_gap_deg(aircraft[key], flight[key]))
        if worst_at["angle_deg"] is None or gap_a > worst["angle_deg"]:
            worst["angle_deg"], worst_at["angle_deg"] = gap_a, here
    if worst["time_s"] > time_tol_s:
        problems.append(f"instant differs from the telemetry by "
                        f"{worst['time_s']:.6f} s at {worst_at['time_s']}")
    if worst["position_m"] > position_tol_m:
        problems.append(f"aircraft position differs from the telemetry "
                        f"by {worst['position_m']:.3f} m at "
                        f"{worst_at['position_m']}")
    if worst["angle_deg"] > angle_tol_deg:
        problems.append(f"aircraft attitude differs from the telemetry "
                        f"by {worst['angle_deg']:.6f} deg at "
                        f"{worst_at['angle_deg']}")
    digest = telemetry_digest(columns)
    digests_equal = digest == manifest.get("output_digest")
    if not digests_equal:
        problems.append(f"{TELEMETRY_FILE} digests to {digest[:16]}, not "
                        f"the manifest's output_digest "
                        f"{str(manifest.get('output_digest'))[:16]}: this "
                        f"is not the flight the manifest records")
    ok = not problems and bool(frames)
    if not frames:
        problems.append("no frame records to compare with the flight")
    measured_text = (f"t {worst['time_s']:g} s, pos {worst['position_m']:g} "
                     f"m, att {worst['angle_deg']:g} deg")
    where = (problems[0] if problems else
             f"{len(frames)} records against {n} samples"
             + (f" ({positions_compared} with north/east)"
                if positions_compared < len(frames) else "")
             + f"; digest {digest[:16]} = output_digest; worst "
             + (str(worst_at["position_m"]).split(" (")[0]
                if worst_at["position_m"] else "no frame"))
    detail = ("; ".join(problems) if problems else
              f"{len(frames)} records match the flight at their samples "
              f"(worst t {worst['time_s']:g} s, position "
              f"{worst['position_m']:g} m, attitude {worst['angle_deg']:g} "
              f"deg; {TELEMETRY_FILE} digest = output_digest)")
    return Check("flight_fidelity", ok, detail,
                 measured=worst["position_m"], tolerance=position_tol_m,
                 unit="m", measured_text=measured_text,
                 tolerance_text=tolerance_text, where=where,
                 data={"frames": len(frames), "samples": n,
                       "positions_compared": positions_compared,
                       "out_of_range": out_of_range, "worst": worst,
                       "worst_at": worst_at,
                       "telemetry_digest": digest,
                       "digests_equal": digests_equal})


def verify_schedule_fidelity(manifest: Dict, spec,
                             columns: Optional[Dict[str, Sequence[float]]]
                             ) -> Check:
    """Check 7: the schedule recomputed from the spec's cameras over the
    telemetry against the manifest's instants, sample for sample.
    ``spec`` None or ``columns`` None: SKIPPED by name."""
    missing = ([SCENARIO_FILE] if spec is None else []) + (
        [TELEMETRY_FILE] if columns is None else [])
    if missing:
        return Check("schedule_fidelity", None,
                     f"NOT EXERCISED (no {' or '.join(missing)} beside the "
                     f"manifest): the schedule was not recomputed from "
                     f"the spec",
                     skipped=f"no {' or '.join(missing)} beside the manifest",
                     tolerance_text="0 differ",
                     data={"missing": missing})
    from ..scenario.camera import default_cameras
    from .poses import SceneFrame
    from .schedule import ScheduleError, solve_schedule

    block = manifest.get("frame") or {}
    frame = SceneFrame(str(block.get("crs")),
                       float(block.get("origin_lat_deg", 0.0)),
                       float(block.get("origin_lon_deg", 0.0)),
                       bool(block.get("declared_on_card", False)))
    cameras = spec.cameras or default_cameras(spec)
    rate_hz = float(manifest.get("rate_hz") or spec.rate.value)
    recorded: Dict[str, List[Tuple[int, float]]] = {}
    for record in manifest.get("frames", []):
        recorded.setdefault(record["camera_id"], []).append(
            (int(record["sample_index"]), float(record["t_s"])))
    problems: List[str] = []
    differing = 0
    total = 0
    worst_gap = 0.0
    worst_at = None
    per_camera = []
    spec_ids = []
    for camera in cameras:
        camera_id = str(camera.camera_id.value)
        spec_ids.append(camera_id)
        try:
            schedule = solve_schedule(columns, camera, frame, rate_hz=rate_hz)
        except ScheduleError as exc:
            problems.append(f"{camera_id}: the spec's schedule cannot be "
                            f"recomputed over this telemetry ({exc})")
            continue
        expected = list(zip(schedule.indices, schedule.times))
        actual = recorded.get(camera_id, [])
        total += max(len(expected), len(actual))
        per_camera.append(f"{camera_id} {len(actual)}/{len(expected)}")
        if len(expected) != len(actual):
            differing += abs(len(expected) - len(actual))
            problems.append(f"{camera_id}: {len(actual)} recorded instants "
                            f"against {len(expected)} the spec schedules")
        for number, ((si, st), (ai, at)) in enumerate(zip(expected, actual)):
            gap = abs(st - at)
            if si != ai or gap > TIME_TOL_S:
                differing += 1
                if worst_at is None or gap > worst_gap:
                    worst_gap = gap
                    worst_at = (f"{camera_id} #{number} at sample {ai} "
                                f"t={at:.3f} s where the spec schedules "
                                f"sample {si} t={st:.3f} s")
    for camera_id in recorded:
        if camera_id not in spec_ids:
            problems.append(f"{camera_id}: recorded in the manifest but "
                            f"not a camera of the spec")
            differing += len(recorded[camera_id])
            total += len(recorded[camera_id])
    if worst_at is not None:
        problems.insert(0, f"{differing} of {total} instants differ from "
                           f"the spec's schedule; worst {worst_at}")
    ok = not problems and total > 0
    if total == 0 and not problems:
        problems.append("no instants to compare")
    return Check("schedule_fidelity", ok,
                 "; ".join(problems) if problems
                 else f"{total} instants across {len(cameras)} camera(s) "
                      f"match the schedule recomputed from the spec's "
                      f"cameras over the telemetry, sample for sample",
                 measured=float(differing), tolerance=0.0, unit="instants",
                 measured_text=f"{differing} of {total} instants differ",
                 tolerance_text="0 differ",
                 where=(problems[0] if problems
                        else ", ".join(per_camera) + " (recorded/spec)"),
                 data={"differing": differing, "instants": total,
                       "worst_gap_s": worst_gap, "worst_at": worst_at,
                       "cameras": per_camera})


def recompute_pose_tracks(manifest: Dict, spec,
                          columns: Dict[str, Sequence[float]]
                          ) -> Tuple[Dict[str, "PoseTrack"], List[str]]:
    """The per-camera pose tracks solved AGAIN from the spec's cameras
    (or the documented default camera of a camera-less spec) over the
    telemetry, in the manifest's own frame block (CRS and origin):
    ``{camera_id: PoseTrack}`` plus the problems named for any camera
    whose track cannot be solved over this telemetry. This is the
    producer's solver (core.capture.poses.solve_pose_track), run here
    on the run's own inputs: what checks 3 and 8 grade the records
    against. Measured on examples/cameras_multi: both tracks in a few
    milliseconds, digests bit-identical to the manifest's."""
    from ..scenario.camera import default_cameras
    from .poses import PoseSolveError, SceneFrame, solve_pose_track

    block = manifest.get("frame") or {}
    frame = SceneFrame(str(block.get("crs")),
                       float(block.get("origin_lat_deg", 0.0)),
                       float(block.get("origin_lon_deg", 0.0)),
                       bool(block.get("declared_on_card", False)))
    tracks: Dict[str, "PoseTrack"] = {}
    problems: List[str] = []
    for camera in (spec.cameras or default_cameras(spec)):
        camera_id = str(camera.camera_id.value)
        try:
            tracks[camera_id] = solve_pose_track(columns, camera, frame)
        except PoseSolveError as exc:
            problems.append(f"{camera_id}: the spec's pose track cannot be "
                            f"recomputed over this telemetry ({exc})")
    return tracks, problems


def track_record(track: Optional["PoseTrack"], sample_index: int
                 ) -> Optional[Dict]:
    """One recomputed pose as a frame-record mapping (the fields
    :func:`project_point` and :func:`_ray_through_pixel` read, plus the
    lens the manifest derives: fx/fy from focal, sensor and resolution
    by the manifest's own one multiplication, the principal point at
    the image centre); None when there is no track or the sample lies
    outside it."""
    if track is None or not 0 <= int(sample_index) < len(track):
        return None
    pose = track.sample(int(sample_index))
    fx = track.width_px / track.sensor_width_mm
    fy = track.height_px / track.sensor_height_mm
    return {
        **pose,
        "sensor_width_mm": track.sensor_width_mm,
        "sensor_height_mm": track.sensor_height_mm,
        "width_px": track.width_px, "height_px": track.height_px,
        "near_m": track.near_m, "far_m": track.far_m,
        "principal_point_px": [track.width_px / 2.0, track.height_px / 2.0],
        "fx_px": pose["focal_length_mm"] * fx,
        "fy_px": pose["focal_length_mm"] * fy,
    }


def verify_pose_fidelity(manifest: Dict, spec,
                         columns: Optional[Dict[str, Sequence[float]]],
                         recomputed: Optional[Tuple[Dict[str, "PoseTrack"],
                                                    List[str]]] = None,
                         position_tol_m: float = POSE_POSITION_TOL_M,
                         angle_tol_deg: float = POSE_ANGLE_TOL_DEG,
                         quaternion_tol: float = POSE_QUATERNION_TOL,
                         lens_tol_px: float = POSE_LENS_TOL_PX,
                         lens_tol_mm: float = POSE_LENS_TOL_MM) -> Check:
    """Check 8: every record's pose and lens against the track
    recomputed from the spec's cameras over the telemetry at the
    record's sample, and every camera block's ``pose_track_digest``
    against the recomputed track's digest, verbatim. ``recomputed`` is
    :func:`recompute_pose_tracks`' result when the caller already has
    it. ``spec`` None or ``columns`` None: SKIPPED by name."""
    tolerance_text = (f"{position_tol_m:g} m, {angle_tol_deg:g} deg, "
                      f"{lens_tol_px:g} px")
    missing = ([SCENARIO_FILE] if spec is None else []) + (
        [TELEMETRY_FILE] if columns is None else [])
    if missing:
        return Check("pose_fidelity", None,
                     f"NOT EXERCISED (no {' or '.join(missing)} beside the "
                     f"manifest): the camera poses were not recomputed "
                     f"from the spec; a moved or rotated camera is not "
                     f"seen without them",
                     skipped=f"no {' or '.join(missing)} beside the manifest",
                     tolerance_text=tolerance_text,
                     data={"missing": missing})
    if recomputed is None:
        recomputed = recompute_pose_tracks(manifest, spec, columns)
    tracks, problems = recomputed
    problems = list(problems)
    frames = manifest.get("frames", [])
    blocks = manifest.get("cameras", [])
    digests_equal: Dict[str, bool] = {}
    for block in blocks:
        camera_id = block["camera_id"]
        track = tracks.get(camera_id)
        if track is None:
            problems.append(f"{camera_id}: a camera block in the manifest "
                            f"but not a camera of the spec")
            continue
        equal = str(block.get("pose_track_digest")) == track.digest()
        digests_equal[camera_id] = equal
        if not equal:
            problems.append(f"{camera_id}: pose_track_digest "
                            f"{str(block.get('pose_track_digest'))[:16]} is "
                            f"not the recomputed track's "
                            f"{track.digest()[:16]}")
        if str(block.get("preset")) != track.preset:
            problems.append(f"{camera_id}: block preset "
                            f"{block.get('preset')!r} against the spec "
                            f"camera's {track.preset!r}")
    for camera_id in tracks:
        if camera_id not in {b["camera_id"] for b in blocks}:
            problems.append(f"{camera_id}: a camera of the spec with no "
                            f"camera block in the manifest")
    worst_pose = {"position_m": 0.0, "angle_deg": 0.0, "quaternion": 0.0,
                  "lens_px": 0.0, "focal_mm": 0.0}
    worst_at = {key: None for key in worst_pose}
    field_problems = 0
    out_of_range = 0
    compared = 0
    for record in frames:
        here = _frame_words(record)
        expected = track_record(tracks.get(record["camera_id"]),
                                int(record["sample_index"]))
        if expected is None:
            if record["camera_id"] in tracks:
                out_of_range += 1
                problems.append(
                    f"{here}: sample_index {int(record['sample_index'])} "
                    f"outside the recomputed track's "
                    f"{len(tracks[record['camera_id']])} samples")
            continue
        compared += 1
        gap_pos = math.dist(
            (record["position_north_m"], record["position_east_m"],
             record["position_alt_m"]),
            (expected["position_north_m"], expected["position_east_m"],
             expected["position_alt_m"]))
        if worst_at["position_m"] is None or gap_pos > worst_pose["position_m"]:
            worst_pose["position_m"], worst_at["position_m"] = gap_pos, (
                f"{here} (recorded {float(record['position_north_m']):.3f} N, "
                f"{float(record['position_east_m']):.3f} E, "
                f"{float(record['position_alt_m']):.3f} m; the spec's track "
                f"{expected['position_north_m']:.3f} N, "
                f"{expected['position_east_m']:.3f} E, "
                f"{expected['position_alt_m']:.3f} m at sample "
                f"{int(record['sample_index'])})")
        gap_ang = max(_angle_gap_deg(record["yaw_deg"], expected["yaw_deg"]),
                      abs(float(record["pitch_deg"]) - expected["pitch_deg"]),
                      abs(float(record["roll_deg"]) - expected["roll_deg"]))
        if worst_at["angle_deg"] is None or gap_ang > worst_pose["angle_deg"]:
            worst_pose["angle_deg"], worst_at["angle_deg"] = gap_ang, (
                f"{here} (recorded yaw {float(record['yaw_deg']):.4f}, pitch "
                f"{float(record['pitch_deg']):.4f}, roll "
                f"{float(record['roll_deg']):.4f} deg; the spec's track "
                f"{expected['yaw_deg']:.4f}, {expected['pitch_deg']:.4f}, "
                f"{expected['roll_deg']:.4f})")
        gap_q = max(abs(float(x) - float(y)) for x, y in zip(
            record["quaternion_wxyz"], expected["quaternion_wxyz"]))
        if worst_at["quaternion"] is None or gap_q > worst_pose["quaternion"]:
            worst_pose["quaternion"], worst_at["quaternion"] = gap_q, here
        gap_lens = max(
            abs(float(record["fx_px"]) - expected["fx_px"]),
            abs(float(record["fy_px"]) - expected["fy_px"]),
            math.dist(record["principal_point_px"],
                      expected["principal_point_px"]))
        if worst_at["lens_px"] is None or gap_lens > worst_pose["lens_px"]:
            worst_pose["lens_px"], worst_at["lens_px"] = gap_lens, (
                f"{here} (recorded fx {float(record['fx_px']):.3f}, fy "
                f"{float(record['fy_px']):.3f} px, focal "
                f"{float(record['focal_length_mm']):.3f} mm; the spec's "
                f"camera fx {expected['fx_px']:.3f}, fy "
                f"{expected['fy_px']:.3f} px, focal "
                f"{expected['focal_length_mm']:.3f} mm)")
        gap_mm = abs(float(record["focal_length_mm"])
                     - expected["focal_length_mm"])
        if worst_at["focal_mm"] is None or gap_mm > worst_pose["focal_mm"]:
            worst_pose["focal_mm"], worst_at["focal_mm"] = gap_mm, here
        for key in ("width_px", "height_px", "sensor_width_mm",
                    "sensor_height_mm", "near_m", "far_m"):
            if record.get(key) != expected[key]:
                field_problems += 1
                if field_problems <= 4:
                    problems.append(f"{here}: {key} {record.get(key)!r} "
                                    f"against the spec camera's "
                                    f"{expected[key]!r}")
    if worst_pose["position_m"] > position_tol_m:
        problems.append(f"camera position differs from the spec's track by "
                        f"{worst_pose['position_m']:.3f} m at "
                        f"{worst_at['position_m']}")
    if worst_pose["angle_deg"] > angle_tol_deg:
        problems.append(f"camera orientation differs from the spec's track "
                        f"by {worst_pose['angle_deg']:.4f} deg at "
                        f"{worst_at['angle_deg']}")
    if worst_pose["quaternion"] > quaternion_tol:
        problems.append(f"quaternion differs from the spec's track by "
                        f"{worst_pose['quaternion']:.6f} at "
                        f"{worst_at['quaternion']}")
    if worst_pose["lens_px"] > lens_tol_px or worst_pose["focal_mm"] > lens_tol_mm:
        problems.append(f"lens differs from the spec's camera by "
                        f"{worst_pose['lens_px']:.3f} px "
                        f"({worst_pose['focal_mm']:.3f} mm) at "
                        f"{worst_at['lens_px']}")
    if field_problems > 4:
        problems.append(f"{field_problems - 4} more record fields differ "
                        f"from the spec camera's")
    ok = not problems and compared > 0 and bool(blocks)
    if compared == 0 and not problems:
        problems.append("no frame records to compare with the spec's track")
    measured_text = (f"pos {worst_pose['position_m']:g} m, ang "
                     f"{worst_pose['angle_deg']:g} deg, lens "
                     f"{worst_pose['lens_px']:g} px")
    samples = len(columns.get("t", []))
    where = (problems[0] if problems else
             f"{compared} records against the tracks recomputed from "
             f"{len(tracks)} camera(s) over {samples} samples; digests = "
             f"pose_track_digest; worst "
             + (str(worst_at["position_m"]).split(" (")[0]
                if worst_at["position_m"] else "no frame"))
    detail = ("; ".join(problems) if problems else
              f"{compared} records match the pose track recomputed from "
              f"the spec's {len(tracks)} camera(s) over the telemetry at "
              f"their samples (worst position {worst_pose['position_m']:g} "
              f"m, orientation {worst_pose['angle_deg']:g} deg, quaternion "
              f"{worst_pose['quaternion']:g}, lens {worst_pose['lens_px']:g} "
              f"px, focal {worst_pose['focal_mm']:g} mm); every camera "
              f"block's pose_track_digest = the recomputed track's")
    return Check("pose_fidelity", ok, detail,
                 measured=worst_pose["position_m"], tolerance=position_tol_m,
                 unit="m", measured_text=measured_text,
                 tolerance_text=tolerance_text, where=where,
                 data={"records": compared, "out_of_range": out_of_range,
                       "cameras": sorted(tracks), "samples": samples,
                       "digests_equal": digests_equal,
                       "worst": worst_pose, "worst_at": worst_at,
                       "field_problems": field_problems,
                       "tolerances": {"position_m": position_tol_m,
                                      "angle_deg": angle_tol_deg,
                                      "quaternion": quaternion_tol,
                                      "lens_px": lens_tol_px,
                                      "focal_mm": lens_tol_mm}})


def _aim_kind(block: Dict) -> Tuple[str, Dict]:
    """(kind, spec values) of a camera block's promise about the
    aircraft's pixel: ``aircraft-exact`` (explicit, aim aircraft),
    ``aircraft-lagged`` (chase, wingman, tower, ground: the C++
    director's aim lag), ``body-axis`` (cockpit: the view is along the
    body axis whatever aim_mode says) or ``none`` (point / bearing)."""
    spec = block.get("spec") or {}

    def value(key, default=None):
        field = spec.get(key)
        return field.get("value", default) if isinstance(field, dict) \
            else default

    preset = str(block.get("preset") or value("preset", "-"))
    aim_mode = str(value("aim_mode", "aircraft"))
    values = {"preset": preset, "aim_mode": aim_mode,
              "offset_forward_m": float(value("offset_forward_m", 0.0)),
              "offset_right_m": float(value("offset_right_m", 0.0)),
              "offset_up_m": float(value("offset_up_m", 0.0))}
    if preset == "cockpit":
        return "body-axis", values
    if aim_mode == "aircraft":
        return ("aircraft-exact" if preset == "explicit"
                else "aircraft-lagged"), values
    return "none", values


def _telemetry_track(columns: Dict[str, Sequence[float]],
                     frame_block: Dict) -> Optional[List[Tuple[float, float, float]]]:
    """The aircraft's (north, east, alt) at every telemetry sample,
    projected here with pyproj through the manifest's frame block;
    None when the telemetry or the frame cannot give it."""
    n = len(columns.get("t", []))
    if n == 0 or "altitude_m" not in columns:
        return None
    probe = telemetry_state_at(columns, frame_block, 0)
    if probe["north_m"] is None:
        return None
    from pyproj import Transformer

    forward = Transformer.from_crs("EPSG:4326", str(frame_block["crs"]),
                                   always_xy=True)
    ox, oy = float(frame_block["origin_x_m"]), float(frame_block["origin_y_m"])
    track = []
    for i in range(n):
        x, y = forward.transform(float(columns["lon_deg"][i]),
                                 float(columns["lat_deg"][i]))
        track.append((float(y) - oy, float(x) - ox,
                      float(columns["altitude_m"][i])))
    return track


def lagged_aim_track(t: Sequence[float],
                     track: Sequence[Tuple[float, float, float]],
                     lag_s: float) -> List[Tuple[float, float, float]]:
    """The first-order lag of the aircraft track the ported presets aim
    at: the aim starts ON the aircraft and follows it with time constant
    ``lag_s`` over the recorded clock (dt from the telemetry's own t).
    Written here from the promise's statement, not imported."""
    aim: List[Tuple[float, float, float]] = []
    current = None
    for i, point in enumerate(track):
        if current is None:
            current = tuple(point)
        else:
            dt = float(t[i]) - float(t[i - 1])
            gain = 1.0 - math.exp(-dt / lag_s)
            current = tuple(c + (p - c) * gain for c, p in zip(current, point))
        aim.append(current)
    return aim


def _look_axes(from_point, to_point):
    """(forward, right, up) of a roll-free camera at ``from_point``
    looking at ``to_point``: yaw from the horizontal bearing, pitch
    from the climb angle, roll 0 -- the horizon-stable rule every
    ported preset follows."""
    dn = to_point[0] - from_point[0]
    de = to_point[1] - from_point[1]
    dup = to_point[2] - from_point[2]
    yaw = math.degrees(math.atan2(de, dn))
    pitch = math.degrees(math.atan2(dup, math.hypot(dn, de)))
    return axes_from_euler(0.0, pitch, yaw)


def _angle_between_deg(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if norm == 0.0:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / norm))))


def verify_aim_fidelity(manifest: Dict,
                        columns: Optional[Dict[str, Sequence[float]]],
                        tol_px: float = AIM_TOL_PX,
                        axis_tol_deg: float = AIM_AXIS_TOL_DEG) -> Check:
    """Check 9: the aircraft's pixel through each record against the
    pixel its camera's promise predicts (module docstring). ``columns``
    None: SKIPPED by name; a telemetry without lat/lon or altitude, or
    a manifest whose every camera aims at a point or a bearing:
    SKIPPED with that reason."""
    from .poses import AIM_LAG_S

    tolerance_text = f"{tol_px:g} px, {axis_tol_deg:g} deg"
    if columns is None:
        return Check("aim_fidelity", None,
                     f"NOT EXERCISED (no {TELEMETRY_FILE} beside the "
                     f"manifest): the aim promise was not graded",
                     skipped=f"no {TELEMETRY_FILE} beside the manifest",
                     tolerance_text=tolerance_text, data={"telemetry": None})
    frame_block = manifest.get("frame") or {}
    track = _telemetry_track(columns, frame_block)
    if track is None:
        return Check("aim_fidelity", None,
                     f"NOT EXERCISED: {TELEMETRY_FILE} carries no lat/lon "
                     f"and altitude to put through the manifest's frame",
                     skipped=f"{TELEMETRY_FILE} carries no lat/lon/altitude",
                     tolerance_text=tolerance_text, data={"telemetry": None})
    t = [float(v) for v in columns["t"]]
    kinds = {b["camera_id"]: _aim_kind(b) for b in manifest.get("cameras", [])}
    lagged: Dict[str, List] = {}
    per_camera: Dict[str, Dict] = {}
    problems: List[str] = []
    worst_gap = 0.0
    worst_at = None
    worst_axis = 0.0
    graded = 0
    for record in manifest.get("frames", []):
        camera_id = record["camera_id"]
        kind, values = kinds.get(camera_id, ("none", {}))
        entry = per_camera.setdefault(camera_id, {
            "kind": kind, "graded": 0, "worst_gap_px": 0.0,
            "off_aim_px": 0.0, "predicted_off_aim_px": 0.0,
            "worst_at": None})
        if kind == "none":
            continue
        here = _frame_words(record)
        i = int(record["sample_index"])
        if not 0 <= i < len(track):
            problems.append(f"{here}: sample_index {i} outside the "
                            f"telemetry's {len(track)} samples")
            continue
        aircraft = track[i]
        camera = (float(record["position_north_m"]),
                  float(record["position_east_m"]),
                  float(record["position_alt_m"]))
        cx, cy = record["principal_point_px"]
        # Where the record puts the flight's aircraft.
        u, v, depth = project_point(record, aircraft)
        if kind == "body-axis":
            ahead = -values["offset_forward_m"]
            if not ahead > 0.0:
                # The cg is not ahead of the lens: no pixel is promised.
                entry["kind"] = "body-axis (cg not ahead of the lens)"
                continue
            u_p = cx + float(record["fx_px"]) * (-values["offset_right_m"]) / ahead
            v_p = cy + float(record["fy_px"]) * values["offset_up_m"] / ahead
            body = axes_from_euler(float(columns["roll_deg"][i]),
                                   float(columns["pitch_deg"][i]),
                                   float(columns["heading_deg"][i])) \
                if all(k in columns for k in ("roll_deg", "pitch_deg",
                                              "heading_deg")) else None
            if body is not None:
                own = axes_from_quat(record["quaternion_wxyz"])
                axis_gap = max(_angle_between_deg(a, b)
                               for a, b in zip(own, body))
                if axis_gap > worst_axis:
                    worst_axis = axis_gap
                if axis_gap > axis_tol_deg:
                    problems.append(f"{here}: the camera's axes are "
                                    f"{axis_gap:.6f} deg from the "
                                    f"telemetry's body axes (tol "
                                    f"{axis_tol_deg:g}); the cockpit view "
                                    f"is promised ALONG the body axis")
        else:
            if kind == "aircraft-lagged":
                if camera_id not in lagged:
                    lagged[camera_id] = lagged_aim_track(t, track, AIM_LAG_S)
                aim = lagged[camera_id][i]
            else:
                aim = aircraft
            axes = _look_axes(camera, aim)
            u_p, v_p, depth_p = project_point(record, aircraft, axes)
            if depth_p <= 0:
                problems.append(f"{here}: the promised aim puts the "
                                f"aircraft behind the camera")
                continue
        if depth <= 0 or not math.isfinite(u):
            problems.append(f"{here}: the aircraft lies behind the camera "
                            f"where the promise puts it at ({u_p:.1f}, "
                            f"{v_p:.1f}) px")
            continue
        graded += 1
        entry["graded"] += 1
        gap = math.hypot(u - u_p, v - v_p)
        off_aim = math.hypot(u - cx, v - cy)
        predicted = math.hypot(u_p - cx, v_p - cy)
        entry["off_aim_px"] = max(entry["off_aim_px"], off_aim)
        entry["predicted_off_aim_px"] = max(entry["predicted_off_aim_px"],
                                            predicted)
        if entry["worst_at"] is None or gap > entry["worst_gap_px"]:
            entry["worst_gap_px"], entry["worst_at"] = gap, here
        if worst_at is None or gap > worst_gap:
            worst_gap, worst_at = gap, (
                f"{here} (aircraft at ({u:.1f}, {v:.1f}) px, promised "
                f"({u_p:.1f}, {v_p:.1f}) px: {kind}, off-aim {off_aim:.1f} px "
                f"against a predicted {predicted:.1f})")
    if worst_gap > tol_px:
        problems.insert(0, f"the aircraft's pixel is {worst_gap:.3f} px from "
                           f"where the camera's promise puts it at "
                           f"{worst_at}")
    not_graded = [c for c, e in per_camera.items() if e["graded"] == 0
                  and not problems]
    if graded == 0 and not problems:
        reason = ("no camera promises the aircraft's pixel (aim point / "
                  "bearing)" if per_camera else "no frames")
        return Check("aim_fidelity", None,
                     f"NOT EXERCISED: {reason}", skipped=reason,
                     tolerance_text=tolerance_text,
                     data={"cameras": per_camera})
    ok = not problems and graded > 0
    words = []
    for camera_id, entry in per_camera.items():
        if entry["graded"]:
            words.append(f"{camera_id} {entry['kind']}: off-aim up to "
                         f"{entry['off_aim_px']:.1f} px, predicted "
                         f"{entry['predicted_off_aim_px']:.1f}")
        else:
            words.append(f"{camera_id} not graded ({entry['kind']})")
    measured_text = f"gap {worst_gap:.3g} px" + (
        f", axes {worst_axis:.3g} deg" if any(
            e["kind"].startswith("body-axis") for e in per_camera.values())
        else "")
    where = (problems[0] if problems else
             f"{graded} records; " + "; ".join(words))
    detail = ("; ".join(problems) if problems else
              f"{graded} records put the flight's aircraft where their "
              f"camera's promise predicts (worst gap {worst_gap:.3g} px, "
              f"tol {tol_px:g}); " + "; ".join(words))
    return Check("aim_fidelity", ok, detail, measured=worst_gap,
                 tolerance=tol_px, unit="px", measured_text=measured_text,
                 tolerance_text=tolerance_text, where=where,
                 data={"records": graded, "worst_gap_px": worst_gap,
                       "worst_axis_deg": worst_axis, "worst_at": worst_at,
                       "cameras": per_camera, "lag_s": AIM_LAG_S})


def read_scenario_spec(run_dir):
    """The spec beside a manifest (``scenario.yaml``) or None when the
    file is not there. An unreadable spec raises: a verify that reads
    the wrong thing must say so, never grade around it."""
    path = Path(run_dir) / SCENARIO_FILE
    if not path.is_file():
        return None
    from ..scenario.spec import ScenarioSpec

    return ScenarioSpec.read(path)


def verify_alignment(manifest_a: Dict, manifest_b: Dict,
                     tol_s: float = TIME_TOL_S, label_a: str = "this run",
                     label_b: str = "the other run") -> Check:
    """Check 1: two runs of the same simulation align frame-for-frame.
    ``label_a`` / ``label_b`` name the runs in the offender text."""
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
    worst = 0.0
    worst_at = None
    where = None
    if len(times_a) != len(times_b):
        only_a = sorted(set(times_a) - set(times_b))
        only_b = sorted(set(times_b) - set(times_a))
        extra = (f"; only in {label_a}: t="
                 + ", ".join(f"{t:.6f}" for t in only_a[:3]) + " s"
                 if only_a else "") + (
                 f"; only in {label_b}: t="
                 + ", ".join(f"{t:.6f}" for t in only_b[:3]) + " s"
                 if only_b else "")
        problems.append(f"{len(times_a)} capture instants in {label_a} "
                        f"against {len(times_b)} in {label_b}{extra}")
        where = (f"{len(times_a)} instants in {label_a} vs {len(times_b)} "
                 f"in {label_b}{extra}")
        worst = math.inf
    else:
        for x, y in zip(times_a, times_b):
            gap = abs(x - y)
            if worst_at is None or gap > worst:
                worst, worst_at = gap, (x, y)
        if worst > tol_s:
            problems.append(f"capture times diverge by {worst:g} s "
                            f"(t={worst_at[0]:.6f} s in {label_a} against "
                            f"{worst_at[1]:.6f} s in {label_b})")
        where = (f"{len(times_a)} instants in both runs; worst gap "
                 f"{worst:g} s"
                 + (f" at t={worst_at[0]:.6f} s ({label_a}) vs "
                    f"{worst_at[1]:.6f} s ({label_b})"
                    if worst_at and worst > 0 else ""))
    return Check("temporal_alignment", not problems,
                 "; ".join(problems) if problems
                 else f"{len(times_a)} capture instants align exactly "
                      f"across the two camera sets (worst gap {worst:g} s, "
                      f"tol {tol_s:g})",
                 measured=worst, tolerance=tol_s, unit="s",
                 measured_text=(f"{worst:g} s" if math.isfinite(worst)
                                else f"{len(times_a)} vs {len(times_b)} "
                                     f"instants"),
                 where=where,
                 data={"instants": [len(times_a), len(times_b)],
                       "runs": [label_a, label_b],
                       "simulation_digests_equal":
                           manifest_a.get("simulation_digest")
                           == manifest_b.get("simulation_digest"),
                       "output_digests_equal":
                           manifest_a.get("output_digest")
                           == manifest_b.get("output_digest")})


def _angle_gap_deg(a: float, b: float) -> float:
    """Smallest unsigned difference between two angles in degrees."""
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def _png_size(path: Path) -> Tuple[int, int]:
    from PIL import Image

    with Image.open(path) as image:
        return int(image.size[0]), int(image.size[1])


def labelled_pixel(record: Dict) -> Tuple[float, float, float]:
    """(u, v, depth) of the manifest's aircraft through the manifest's
    OWN pose and intrinsics -- the labelled pixel every engine-side clause
    is graded against. The manifest's projection model, nothing else."""
    return project_point(record, _aircraft_point(record))


def _luminance(path: Path):
    """The PNG as a float luminance array (rows, columns), 0..255."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("L"), dtype=np.float32)


def _window(lum, x0: int, y0: int, x1: int, y1: int):
    height, width = lum.shape
    x0, x1 = max(0, min(width, x0)), max(0, min(width, x1))
    y0, y1 = max(0, min(height, y0)), max(0, min(height, y1))
    return lum[y0:y1, x0:x1], (x0, y0, x1, y1)


def label_window_contrast(lum, u: float, v: float, half_px: int,
                          bbox=None) -> Dict[str, float]:
    """How the label window differs from the background, in luminance.

    The label window is the square of half size ``half_px`` centred on
    the labelled pixel, widened to cover ``bbox`` (the engine's screen
    box ``[x0, y0, x1, y1]``) when given; the background window is one
    of the same size in the frame corner farthest from the label. Both
    are clamped to the frame. ``contrast`` is the larger of the two
    windows' mean difference and spread (standard deviation)
    difference: an aircraft against sky moves the mean, an aircraft
    against textured ground moves at least one of them; nothing drawn
    moves neither. The numbers go into the detail line."""
    import numpy as np

    height, width = lum.shape
    x0, y0 = int(math.floor(u - half_px)), int(math.floor(v - half_px))
    x1, y1 = int(math.ceil(u + half_px)) + 1, int(math.ceil(v + half_px)) + 1
    if bbox is not None:
        try:
            bx0, by0, bx1, by1 = (float(b) for b in bbox)
        except (TypeError, ValueError):
            bx0 = by0 = bx1 = by1 = float("nan")
        if all(math.isfinite(b) for b in (bx0, by0, bx1, by1)):
            x0, y0 = min(x0, int(math.floor(bx0))), min(y0, int(math.floor(by0)))
            x1, y1 = max(x1, int(math.ceil(bx1)) + 1), \
                max(y1, int(math.ceil(by1)) + 1)
    label, label_box = _window(lum, x0, y0, x1, y1)
    size_x, size_y = x1 - x0, y1 - y0
    corners = [(0, 0), (width - size_x, 0), (0, height - size_y),
               (width - size_x, height - size_y)]
    far = max(corners, key=lambda c: math.hypot(c[0] + size_x / 2.0 - u,
                                                 c[1] + size_y / 2.0 - v))
    background, background_box = _window(lum, far[0], far[1],
                                         far[0] + size_x, far[1] + size_y)
    if label.size == 0 or background.size == 0:
        return {"mean": float("nan"), "std": float("nan"),
                "background_mean": float("nan"),
                "background_std": float("nan"), "contrast": 0.0,
                "window": label_box, "background": background_box}
    mean, std = float(np.mean(label)), float(np.std(label))
    bg_mean, bg_std = float(np.mean(background)), float(np.std(background))
    return {"mean": mean, "std": std, "background_mean": bg_mean,
            "background_std": bg_std,
            "contrast": max(abs(mean - bg_mean), abs(std - bg_std)),
            "window": label_box, "background": background_box}


def _rendered_count(run_dir: Path, camera_id: str) -> int:
    """PNGs actually present under frames/<camera_id> -- what "rendered"
    means everywhere the word is used: files on disk, never a schedule
    length."""
    directory = Path(run_dir) / "frames" / camera_id
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.glob("*.png") if p.is_file())


def _engine_pixel_clauses(camera_id: str, index: int, record: Dict,
                          applied: Dict, label, drawn_px, tol_px_d: float,
                          px_tol: float, worst: Dict,
                          problems: List[str]) -> bool:
    """The engine-measured aircraft pixel (``aircraft_px``,
    ``aircraft_py``, ``aircraft_visible``): required, visible, within the
    graded budget of the labelled pixel, and within ``px_tol`` of this
    module's projection of the drawn aircraft through the applied pose.
    Returns False when the frame fails a clause (appended by name)."""
    try:
        e_px = float(applied["aircraft_px"])
        e_py = float(applied["aircraft_py"])
        e_visible = bool(applied["aircraft_visible"])
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"{camera_id} frame {index}: engine record lacks "
                        f"its own projection of the drawn aircraft "
                        f"({exc}); aircraft_px/aircraft_py/aircraft_visible "
                        f"are required")
        return False
    ok = True
    u_s, v_s = label
    if not e_visible:
        ok = False
        problems.append(f"{camera_id} frame {index}: the engine reports the "
                        f"aircraft not visible in a frame whose label places "
                        f"it at ({u_s:.1f}, {v_s:.1f}) px")
    gap_e = math.hypot(e_px - u_s, e_py - v_s)
    worst["engine_px"] = max(worst["engine_px"], gap_e)
    if gap_e > tol_px_d:
        ok = False
        problems.append(f"{camera_id} frame {index}: the engine measured "
                        f"the aircraft at ({e_px:.1f}, {e_py:.1f}) px, "
                        f"{gap_e:.1f} px from the labelled pixel "
                        f"({u_s:.1f}, {v_s:.1f}) (tol {tol_px_d:.1f} px)")
    gap_model = math.hypot(e_px - drawn_px[0], e_py - drawn_px[1])
    worst["engine_model_px"] = max(worst["engine_model_px"], gap_model)
    if gap_model > px_tol:
        ok = False
        problems.append(f"{camera_id} frame {index}: the engine's own "
                        f"projection of the aircraft it drew disagrees with "
                        f"the manifest's projection model by "
                        f"{gap_model:.2f} px (tol {px_tol}); the two do not "
                        f"describe one lens")
    return ok


def _pixel_content_clause(camera_id: str, index: int, record: Dict,
                          applied: Dict, png: Path, label, tol_px_d: float,
                          worst: Dict, problems: List[str],
                          contrast_min: float = ENGINE_LABEL_CONTRAST_MIN
                          ) -> bool:
    """Something must be DRAWN at the label: the PNG's window around the
    labelled pixel must differ from the frame's background window by at
    least ``contrast_min`` (label_window_contrast). Returns False when
    the frame fails, appended with both windows' numbers."""
    u_s, v_s = label
    half = max(ENGINE_LABEL_WINDOW_HALF_PX, int(math.ceil(tol_px_d)))
    try:
        stats = label_window_contrast(_luminance(png), u_s, v_s, half,
                                      bbox=applied.get("aircraft_bbox_px"))
    except (OSError, ValueError) as exc:
        problems.append(f"{camera_id} frame {index}: {record['file']} "
                        f"could not be read for its pixels ({exc})")
        return False
    if stats["contrast"] < worst["label_contrast"]:
        worst["label_contrast"] = stats["contrast"]
        worst["label_background"] = stats["background_mean"]
    if stats["contrast"] < contrast_min:
        x0, y0, x1, y1 = stats["window"]
        problems.append(
            f"{camera_id} frame {index}: nothing is drawn at the labelled "
            f"pixel of {record['file']}: label window "
            f"[{x0}:{x1}, {y0}:{y1}] mean {stats['mean']:.1f} std "
            f"{stats['std']:.1f} against background mean "
            f"{stats['background_mean']:.1f} std "
            f"{stats['background_std']:.1f}, contrast "
            f"{stats['contrast']:.1f} (min {contrast_min:g})")
        return False
    return True


def verify_engine_parity(run_dir, manifest: Dict,
                         pos_tol_m: float = ENGINE_POSITION_TOL_M,
                         ang_tol_deg: float = ENGINE_ANGLE_TOL_DEG,
                         time_tol_s: float = ENGINE_TIME_TOL_S,
                         px_tol: float = ENGINE_REPROJECTION_TOL_PX,
                         aircraft_tol_m: Optional[float] = None
                         ) -> Check:
    """Check 5: the frames the engine rendered carry the geometry the
    manifest claims.

    Per camera, ``frames/<camera_id>/render.json`` (written by the render
    commandlet's consume-poses pass) is matched to the manifest's frame
    records by ``frame_index``. For every record: the applied camera
    position within ``pos_tol_m`` of the solved one, applied
    yaw/pitch/roll within ``ang_tol_deg``, the pose interpolated AT the
    scheduled instant (``t_pose_s``, exact to ENGINE_POSE_TIME_TOL_S),
    the applied capture time EQUAL to the scheduled instant within
    ``time_tol_s`` (representation slack: the instant lies on the
    manifest's ``rate_hz`` grid and the engine captures on that step;
    render.json's ``step_s`` must equal 1/rate_hz), the
    PNG named by the index present at the
    manifest's width and height, and the aircraft reprojected through
    the APPLIED pose (this module's own projection, Euler path) within
    ``px_tol`` of the manifest's own projection and, for aircraft-aimed
    cameras, inside the frame. Then the aircraft the engine DREW
    (``aircraft_applied_*``; its absence FAILS the frame -- a record
    without it cannot be graded) within the frame's budget -- computed
    from the frame's recorded speed and the manifest's rate
    (:func:`drawn_aircraft_budget_m`; ``aircraft_tol_m`` overrides it
    for a caller that states its own) -- of the
    manifest's aircraft and, reprojected through the applied pose,
    within ``px_tol + fx * budget / depth`` of the manifest's
    labelled pixel and inside an aimed frame. The engine's frame counts
    must equal the schedule's.

    Returns an AWAITING check (``ok`` None) when no camera has a
    render.json -- the honest state of a headless run -- and a FAIL when
    some cameras rendered and others did not.
    """
    run_dir = Path(run_dir)
    aim_modes = _aim_modes(manifest)
    by_camera: Dict[str, List[Dict]] = {}
    for record in manifest.get("frames", []):
        by_camera.setdefault(record["camera_id"], []).append(record)
    camera_ids = [b["camera_id"] for b in manifest.get("cameras", [])]

    awaiting: List[str] = []
    problems: List[str] = []
    per_camera: Dict[str, Dict] = {}
    worst = {"position_m": 0.0, "angle_deg": 0.0, "time_s": 0.0,
             "pose_time_s": 0.0,
             "reprojection_px": 0.0, "aircraft_m": 0.0, "aircraft_px": 0.0,
             "aircraft_px_tol": 0.0, "aircraft_depth_m": 0.0,
             "engine_px": 0.0, "engine_model_px": 0.0,
             "label_contrast": float("inf"), "label_background": 0.0}
    frames_checked = 0
    time_tol_used = time_tol_s
    rate_hz = manifest.get("rate_hz")
    if not isinstance(rate_hz, (int, float)) or not rate_hz > 0:
        problems.append("the manifest carries no rate_hz; the fixed-step "
                        "grid the capture clock is graded on cannot be "
                        "stated (a manifest written before this contract)")
        rate_hz = None
    worst["budget_m"] = 0.0
    worst["budget_steps"] = HOST_PHASE_STEPS + HOST_PHASE_MARGIN_STEPS
    worst["budget_step_m"] = 0.0
    worst["budget_speed_mps"] = 0.0
    clock_origins: Dict[str, float] = {}

    for camera_id in camera_ids:
        records = by_camera.get(camera_id, [])
        scheduled = len(records)
        entry = {"scheduled": scheduled,
                 "rendered": _rendered_count(run_dir, camera_id),
                 "verified": 0}
        per_camera[camera_id] = entry
        report_path = run_dir / "frames" / camera_id / "render.json"
        if not report_path.is_file():
            awaiting.append(camera_id)
            continue
        try:
            render = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            problems.append(f"{camera_id}: render.json is not JSON ({exc})")
            continue
        if not isinstance(render, dict):
            problems.append(f"{camera_id}: render.json is not a mapping")
            continue
        tol_t = time_tol_s
        # The engine's step is a FACT to check against the spec's rate,
        # never the tolerance: a render.json declaring step_s = 10 would
        # otherwise pass any capture time.
        step = render.get("step_s")
        if rate_hz is not None:
            if not isinstance(step, (int, float)) or not step > 0:
                problems.append(f"{camera_id}: render.json states no step_s; "
                                f"the engine's step cannot be checked "
                                f"against the spec's {rate_hz:g} Hz")
            elif abs(float(step) - 1.0 / rate_hz) > ENGINE_STEP_TOL_S:
                problems.append(f"{camera_id}: the engine stepped "
                                f"{float(step):.6g} s against the spec's "
                                f"{rate_hz:g} Hz (1/{rate_hz:g} = "
                                f"{1.0 / rate_hz:.6f} s); the frames are "
                                f"not on the manifest's grid")
        origin = render.get("clock_origin_s")
        if isinstance(origin, (int, float)):
            clock_origins[camera_id] = float(origin)
        applied_by_index: Dict[int, Dict] = {}
        for applied in render.get("frame_records", []):
            if isinstance(applied, dict) and "frame_index" in applied:
                applied_by_index[int(applied["frame_index"])] = applied
        captured = render.get("frames_captured")
        declared = render.get("frames_scheduled")
        if captured != scheduled or declared != scheduled:
            problems.append(
                f"{camera_id}: the engine reports {captured} captured of "
                f"{declared} scheduled against {scheduled} manifest frames")
        if records:
            size = (int(records[0]["width_px"]), int(records[0]["height_px"]))
            engine_size = (render.get("width"), render.get("height"))
            if engine_size != size:
                problems.append(
                    f"{camera_id}: the engine rendered {engine_size[0]}x"
                    f"{engine_size[1]} against the manifest's "
                    f"{size[0]}x{size[1]}")
        verified = 0
        for record in records:
            index = int(record["index"])
            applied = applied_by_index.get(index)
            if applied is None:
                problems.append(f"{camera_id} frame {index}: no engine "
                                f"record carries this frame_index")
                continue
            try:
                a_pos = (float(applied["camera_applied_north_m"]),
                         float(applied["camera_applied_east_m"]),
                         float(applied["camera_applied_alt_m"]))
                a_yaw = float(applied["camera_applied_yaw_deg"])
                a_pitch = float(applied["camera_applied_pitch_deg"])
                a_roll = float(applied["camera_applied_roll_deg"])
                a_t = float(applied["t_applied_s"])
                pose_t = float(applied["t_pose_s"])
            except (KeyError, TypeError, ValueError) as exc:
                problems.append(f"{camera_id} frame {index}: engine record "
                                f"lacks an applied field ({exc})")
                continue
            frame_ok = True
            gap_pos = math.dist(a_pos, (record["position_north_m"],
                                        record["position_east_m"],
                                        record["position_alt_m"]))
            gap_ang = max(_angle_gap_deg(a_yaw, record["yaw_deg"]),
                          abs(a_pitch - float(record["pitch_deg"])),
                          abs(a_roll - float(record["roll_deg"])))
            gap_t = abs(a_t - float(record["t_s"]))
            gap_pose_t = abs(pose_t - float(record["t_s"]))
            worst["position_m"] = max(worst["position_m"], gap_pos)
            worst["angle_deg"] = max(worst["angle_deg"], gap_ang)
            worst["time_s"] = max(worst["time_s"], gap_t)
            worst["pose_time_s"] = max(worst["pose_time_s"], gap_pose_t)
            if gap_pose_t > ENGINE_POSE_TIME_TOL_S:
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: pose applied "
                                f"at t={pose_t:.6f} s against the scheduled "
                                f"{float(record['t_s']):.6f} s (tol "
                                f"{ENGINE_POSE_TIME_TOL_S:g}): the pose must "
                                f"be applied at the scheduled instant, not "
                                f"the engine clock")
            if gap_pos > pos_tol_m:
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: applied "
                                f"position {gap_pos:.3f} m from the solved "
                                f"pose (tol {pos_tol_m})")
            if gap_ang > ang_tol_deg:
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: applied "
                                f"orientation {gap_ang:.3f} deg from the "
                                f"solved pose (tol {ang_tol_deg})")
            if gap_t > tol_t:
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: captured at "
                                f"t={a_t:.4f} s against the scheduled "
                                f"{float(record['t_s']):.4f} s (tol "
                                f"{tol_t:.4g})")
            png = run_dir / str(record["file"])
            png_readable = False
            if not png.is_file():
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: "
                                f"{record['file']} does not exist")
            else:
                try:
                    size = _png_size(png)
                except (OSError, ValueError) as exc:
                    size = None
                    problems.append(f"{camera_id} frame {index}: "
                                    f"{record['file']} is not a readable "
                                    f"PNG ({exc})")
                expected = (int(record["width_px"]), int(record["height_px"]))
                if size is not None and size != expected:
                    frame_ok = False
                    problems.append(f"{camera_id} frame {index}: PNG is "
                                    f"{size[0]}x{size[1]} against the "
                                    f"manifest's {expected[0]}x{expected[1]}")
                elif size is None:
                    frame_ok = False
                else:
                    png_readable = True
            # Reprojection through the pose the engine APPLIED, this
            # module's own projection on the Euler path, against the
            # manifest's own projection of the same aircraft point.
            point = _aircraft_point(record)
            u_s, v_s, z_s = project_point(record, point)
            applied_record = dict(record)
            applied_record["position_north_m"] = a_pos[0]
            applied_record["position_east_m"] = a_pos[1]
            applied_record["position_alt_m"] = a_pos[2]
            u_a, v_a, z_a = project_point(
                applied_record, point, axes_from_euler(a_roll, a_pitch, a_yaw))
            if z_s > 0 and z_a > 0 and math.isfinite(u_s) \
                    and math.isfinite(u_a):
                gap_px = math.hypot(u_a - u_s, v_a - v_s)
                worst["reprojection_px"] = max(worst["reprojection_px"],
                                               gap_px)
                if gap_px > px_tol:
                    frame_ok = False
                    problems.append(f"{camera_id} frame {index}: the "
                                    f"aircraft reprojects {gap_px:.2f} px "
                                    f"from the manifest's pixel through the "
                                    f"applied pose (tol {px_tol})")
                if aim_modes.get(camera_id) == "aircraft" and not (
                        0.0 <= u_a <= record["width_px"]
                        and 0.0 <= v_a <= record["height_px"]):
                    frame_ok = False
                    problems.append(f"{camera_id} frame {index}: the "
                                    f"aircraft falls outside the rendered "
                                    f"frame through the applied pose")
            elif z_s > 0:
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: the aircraft "
                                f"lies behind the applied camera")
            # The aircraft the engine DREW (its own FDM's state in the
            # card frame), judged: within the metre budget of the
            # manifest's aircraft, and -- reprojected through the APPLIED
            # pose -- within the pixels that budget subtends at this
            # frame's depth of the manifest's labelled pixel, inside an
            # aimed frame. A record without it FAILS: the pose contract
            # alone cannot tell a labelled frame from a picture of some
            # other flight.
            try:
                drawn = (float(applied["aircraft_applied_north_m"]),
                         float(applied["aircraft_applied_east_m"]),
                         float(applied["aircraft_applied_alt_m"]))
            except (KeyError, TypeError, ValueError) as exc:
                drawn = None
                frame_ok = False
                problems.append(f"{camera_id} frame {index}: engine record "
                                f"lacks the drawn aircraft ({exc}); the "
                                f"pixels cannot be judged against the "
                                f"label")
            budget = None
            if drawn is not None:
                speed = (record.get("aircraft") or {}).get("speed_mps")
                if aircraft_tol_m is not None:
                    budget = {"budget_m": float(aircraft_tol_m),
                              "steps": float("nan"), "step_m": float("nan"),
                              "speed_mps": float("nan"),
                              "rate_hz": float("nan")}
                elif rate_hz is None or not isinstance(speed, (int, float)):
                    drawn = None
                    frame_ok = False
                    problems.append(f"{camera_id} frame {index}: the "
                                    f"manifest frame carries no aircraft "
                                    f"speed_mps or rate_hz; the drawn-"
                                    f"aircraft budget cannot be computed "
                                    f"for this run")
                else:
                    budget = drawn_aircraft_budget_m(speed, rate_hz)
            if drawn is not None:
                tol_m = budget["budget_m"]
                budget_words = (
                    f"budget {tol_m:.2f} m = {budget['steps']:g} steps x "
                    f"{budget['step_m']:.3f} m/step at {budget['speed_mps']:.1f} "
                    f"m/s, {budget['rate_hz']:g} Hz"
                    if math.isfinite(budget["steps"])
                    else f"budget {tol_m:.2f} m stated by the caller")
                gap_m = math.dist(drawn, point)
                if gap_m >= worst["aircraft_m"]:
                    worst["aircraft_m"] = gap_m
                    worst["budget_m"] = tol_m
                    worst["budget_step_m"] = budget["step_m"]
                    worst["budget_speed_mps"] = budget["speed_mps"]
                u_d, v_d, z_d = project_point(
                    applied_record, drawn,
                    axes_from_euler(a_roll, a_pitch, a_yaw))
                if z_s > 0 and (z_d <= 0 or not math.isfinite(u_d)):
                    frame_ok = False
                    problems.append(f"{camera_id} frame {index}: the "
                                    f"engine drew the aircraft behind the "
                                    f"applied camera ({gap_m:.2f} m from "
                                    f"the manifest's aircraft)")
                elif z_s > 0 and math.isfinite(u_s):
                    gap_px_d = math.hypot(u_d - u_s, v_d - v_s)
                    tol_px_d = px_tol + float(record["fx_px"]) * tol_m / z_d
                    if gap_px_d > worst["aircraft_px"]:
                        worst["aircraft_px"] = gap_px_d
                        worst["aircraft_px_tol"] = tol_px_d
                        worst["aircraft_depth_m"] = z_d
                    if gap_m > tol_m or gap_px_d > tol_px_d:
                        frame_ok = False
                        problems.append(
                            f"{camera_id} frame {index}: the engine drew "
                            f"the aircraft {gap_m:.2f} m from the "
                            f"manifest's aircraft ({budget_words}), "
                            f"{gap_px_d:.1f} px from its labelled pixel "
                            f"(tol {tol_px_d:.1f} px at {z_d:.0f} m)")
                    if aim_modes.get(camera_id) == "aircraft" and not (
                            0.0 <= u_d <= record["width_px"]
                            and 0.0 <= v_d <= record["height_px"]):
                        frame_ok = False
                        problems.append(f"{camera_id} frame {index}: the "
                                        f"drawn aircraft falls outside the "
                                        f"rendered frame through the "
                                        f"applied pose")
                    # The engine's OWN projection of the aircraft it drew
                    # (aircraft_px/py through the capture's transform and
                    # FOV) against the labelled pixel and against this
                    # module's projection of the same drawn point; then
                    # the pixels themselves: something must be drawn at
                    # the label. Graded only where the label lies inside
                    # the frame (a cockpit view sees no aircraft).
                    in_frame = (0.0 <= u_s <= record["width_px"]
                                and 0.0 <= v_s <= record["height_px"])
                    if in_frame:
                        frame_ok &= _engine_pixel_clauses(
                            camera_id, index, record, applied, (u_s, v_s),
                            (u_d, v_d), tol_px_d, px_tol, worst, problems)
                        if png_readable:
                            frame_ok &= _pixel_content_clause(
                                camera_id, index, record, applied, png,
                                (u_s, v_s), tol_px_d, worst, problems)
                elif gap_m > tol_m:
                    # The manifest's own camera does not see the aircraft
                    # ahead (a cockpit view): the metre budget still holds.
                    frame_ok = False
                    problems.append(
                        f"{camera_id} frame {index}: the engine drew the "
                        f"aircraft {gap_m:.2f} m from the manifest's "
                        f"aircraft ({budget_words})")
            if frame_ok:
                verified += 1
        entry["verified"] = verified
        frames_checked += scheduled

    data = {"cameras": per_camera, "worst": worst,
            "clock_origins_s": clock_origins,
            "tolerances": {"position_m": pos_tol_m, "angle_deg": ang_tol_deg,
                           "time_s": time_tol_used,
                           "step_s": ENGINE_STEP_TOL_S,
                           "rate_hz": rate_hz,
                           "pose_time_s": ENGINE_POSE_TIME_TOL_S,
                           "reprojection_px": px_tol,
                           "aircraft_m": (worst["budget_m"]
                                          if aircraft_tol_m is None
                                          else aircraft_tol_m),
                           "aircraft_budget_steps": worst["budget_steps"],
                           "label_contrast_min": ENGINE_LABEL_CONTRAST_MIN}}
    if worst["label_contrast"] == float("inf"):
        worst["label_contrast"] = None
    engine_measured = (f"pos {worst['position_m']:.3f} m, ang "
                       f"{worst['angle_deg']:.3f} deg, t {worst['time_s']:.1e} "
                       f"s, px {worst['reprojection_px']:.2f}")
    engine_tolerance = (f"{pos_tol_m} m, {ang_tol_deg} deg, "
                        f"{time_tol_used:.0e} s, {px_tol} px")
    if awaiting and not problems and frames_checked == 0:
        return Check(
            ENGINE_PARITY_CHECK, None,
            f"{AWAITING_ENGINE_FRAMES}: no render.json for camera "
            + ", ".join(awaiting)
            + " (the engine pass has not run on this machine; choose "
              "'Render frames and clip' or --render frames where the "
              "engine exists)",
            data=data, measured_text="-", tolerance_text=engine_tolerance,
            where="no render.json for camera " + ", ".join(awaiting))
    if awaiting:
        problems.append("no render.json for camera " + ", ".join(awaiting)
                        + " while other cameras rendered")
    ok = not problems and frames_checked > 0
    if ok:
        detail = (f"{frames_checked} frames across {len(camera_ids)} "
                  f"camera(s); worst position {worst['position_m']:.3f} m "
                  f"(tol {pos_tol_m}); worst angle {worst['angle_deg']:.3f} "
                  f"deg (tol {ang_tol_deg}); worst time "
                  f"{worst['time_s']:.1e} s (tol {time_tol_used:.0e}; every "
                  f"instant on the {rate_hz:g} Hz grid, the engine stepped "
                  f"{1.0 / rate_hz:.6f} s"
                  + (f", clock origin {max(clock_origins.values()):.6f} s"
                     if clock_origins else "")
                  + f"); pose applied at the scheduled instant to "
                  f"{worst['pose_time_s']:.1e} s; "
                  f"worst reprojection {worst['reprojection_px']:.2f} px "
                  f"(tol {px_tol}); aircraft drawn within "
                  f"{worst['aircraft_m']:.2f} m of the manifest's aircraft "
                  f"(budget {worst['budget_m']:.2f} m = "
                  f"{worst['budget_steps']:g} steps x "
                  f"{worst['budget_step_m']:.3f} m/step at "
                  f"{worst['budget_speed_mps']:.1f} m/s) and "
                  f"{worst['aircraft_px']:.1f} px "
                  f"of its labelled pixel (tol {worst['aircraft_px_tol']:.1f} "
                  f"px at that frame's {worst['aircraft_depth_m']:.0f} m); "
                  f"the engine measured its aircraft within "
                  f"{worst['engine_px']:.1f} px of the label and "
                  f"{worst['engine_model_px']:.2f} px of the manifest's "
                  f"projection model (tol {px_tol}); lowest label window "
                  f"contrast "
                  + (f"{worst['label_contrast']:.1f}"
                     if worst['label_contrast'] is not None else "n/a")
                  + f" against background {worst['label_background']:.1f} "
                  f"(min {ENGINE_LABEL_CONTRAST_MIN:g})")
    else:
        shown = problems[:4]
        detail = "; ".join(shown) + (
            f"; {len(problems) - len(shown)} more" if len(problems) > 4
            else "")
        if not problems:
            detail = "no frames to verify"
    verified_total = sum(int(c["verified"]) for c in per_camera.values())
    where = (f"{verified_total} of {frames_checked} frames verified across "
             f"{len(camera_ids)} camera(s)")
    if problems:
        where += f"; first: {problems[0]}"
    return Check(ENGINE_PARITY_CHECK, ok, detail, data=data,
                 measured_text=engine_measured,
                 tolerance_text=engine_tolerance, where=where)


def verify_run(run_dir, other_run_dir=None) -> VerificationReport:
    """The pass/fail summary over a run directory (CLI: flightsim.verify).

    ``run_dir`` holds capture_manifest.json and, when the engine pass
    ran, ``frames/<camera_id>/`` with the PNGs and render.json."""
    from .manifest import MANIFEST_VERSION, read_capture_manifest

    report = VerificationReport()
    path = Path(run_dir) / "capture_manifest.json"
    if not path.is_file():
        report.add("manifest_present", False,
                   f"{path} does not exist; nothing to verify",
                   measured_text="absent", tolerance_text="present",
                   where=str(path))
        return report
    try:
        manifest = read_capture_manifest(path)
    except ValueError as exc:
        report.add("manifest_version", False, str(exc),
                   measured_text="unsupported",
                   tolerance_text=f"= {MANIFEST_VERSION}", where=str(path))
        return report
    report.add("manifest_version", True,
               f"manifest_version {manifest['manifest_version']}, "
               f"spec {manifest['spec_digest'][:16]}",
               measured=float(manifest["manifest_version"]),
               tolerance=float(MANIFEST_VERSION),
               measured_text=f"version {manifest['manifest_version']}",
               tolerance_text=f"= {MANIFEST_VERSION}",
               where=f"spec {manifest['spec_digest'][:16]}")

    non_finite = 0
    first_bad = None
    frames = manifest.get("frames", [])
    for record in frames:
        for key in ("t_s", "position_north_m", "position_east_m",
                    "position_alt_m", "fx_px", "fy_px"):
            if not math.isfinite(record[key]):
                non_finite += 1
                first_bad = first_bad or f"{_frame_words(record)} {key}"
    report.add("fields_finite", non_finite == 0,
               f"{len(frames)} frame records checked, {non_finite} "
               f"non-finite field(s)"
               + (f" (first {first_bad})" if first_bad else ""),
               measured=float(non_finite), tolerance=0.0, unit="fields",
               measured_text=f"{non_finite} non-finite of {len(frames)} "
                             f"records",
               tolerance_text="0 non-finite",
               where=(f"first {first_bad}" if first_bad
                      else f"{len(frames)} records, 6 fields each"))

    # Checks 3, 6, 7 and 8 read the flight and the spec beside the
    # manifest: the records against the telemetry, the instants against
    # the schedule the spec commands over it, the poses against the
    # tracks the spec commands over it -- recomputed ONCE here and
    # shared by the cross-view rays and the pose check. SKIPPED by name
    # without them (cross-view falls back to the records' own poses and
    # says so).
    columns = read_telemetry_columns(run_dir)
    spec = read_scenario_spec(run_dir)
    recomputed = (recompute_pose_tracks(manifest, spec, columns)
                  if spec is not None and columns is not None else None)
    report.checks.append(verify_geometry(manifest))
    report.checks.append(verify_triangulation(
        manifest, tracks=recomputed[0] if recomputed else None,
        columns=columns if recomputed else None))
    report.checks.append(verify_counts(manifest))
    report.checks.append(verify_flight_fidelity(manifest, columns))
    report.checks.append(verify_schedule_fidelity(manifest, spec, columns))
    report.checks.append(verify_pose_fidelity(manifest, spec, columns,
                                              recomputed))
    report.checks.append(verify_aim_fidelity(manifest, columns))
    report.checks.append(verify_engine_parity(run_dir, manifest))

    if other_run_dir is not None:
        other = read_capture_manifest(
            Path(other_run_dir) / "capture_manifest.json")
        report.checks.append(verify_alignment(
            manifest, other, label_a=Path(run_dir).name or str(run_dir),
            label_b=Path(other_run_dir).name or str(other_run_dir)))
    return report
