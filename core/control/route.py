"""The route: a drawn flight path, flown by the autopilot (docs/ROUTE.md).

The one place that knows a route. A route is a polyline in the scene
frame (metres east and north of the spec origin, ``SceneFrame.for_spec``
/ ``runner.scene_frame_for``) with an altitude at every point; the
aircraft begins at the origin, at the spec altitude, pointed along the
first leg, and the autopilot is steered along the line by writing
setpoints only (``autopilot.py``'s rule: this module never touches a
control surface). Pure functions and small classes: no I/O, no wall
clock, no random numbers, so two runs of one spec steer identically.

What lives here and why:

* the limits the map and the validator show -- the bank limit and the
  climb-rate demand clip -- are the TECS controller's own numbers
  (``core/control/systems/tecs.xml``), pinned here as constants and
  pinned to the XML by a test, so the page never types a number of its
  own; no airframe climb performance is measured anywhere in this
  system, and ``HDOT_MAX_MPS`` is the autopilot's demand clip, not a
  measured figure;
* :func:`route_problems` is the validator's list (``route.shape``,
  ``route.bank_limit``, ``route.time``, ``route.turn``, ``route.climb``),
  scene-free: terrain is the web app's pre-flight (``plan_route_flight``),
  which flies the raster;
* :class:`RouteGuidance` is pure pursuit on the projected point: the
  heading setpoint is the bearing to the point ``lookahead`` metres
  ahead of the aircraft's projection on the line, so a cross-track error
  pulls back with gain about 1/lookahead and the controller's own
  heading hold does the turning;
* :func:`route_closure` is the route-aware half of the run's closure
  assertion (§2.8): a run that strayed further than the declared
  cross-track tolerance or missed the altitude profile produces no
  output;
* :func:`control_schedule` turns the flown autopilot commands into the
  run card's ``control_inputs`` for the render host, which has no
  autopilot and replays the deltas open loop.

Headings are GRID bearings in the scene frame (projected metres), used
as the commanded true heading. Grid north and true north differ by the
projection's convergence angle, about 1 degree in the middle of a UTM
zone and up to 3 at its edge. The guidance is closed loop on POSITION,
so a constant bearing offset only shifts the heading setpoint by that
angle; the cross-track pull-back absorbs it and the flown track still
follows the line. The closure measures the track, not the heading, for
the same reason.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..fdm import units as u

#: The route's own clearance floor over the raster (metres above the
#: ground at every span station of the flown line): between the airborne
#: start's MIN_CLEARANCE_M (30, core/scenario/validate.py) and the terrain
#: planner's PLANNED_CLEARANCE_M (300, webapp/runs.py). The web app's
#: pre-flight measures against it (``route.terrain_clearance``).
ROUTE_MIN_CLEARANCE_M = 150.0
#: tecs.xml ``ap/limits/bank-rad`` 0.436332 rad, the heading hold's bank
#: clip; pinned to the XML by tests/test_route_core.py.
BANK_LIMIT_DEFAULT_DEG = 25.0
#: The bank limit a route may state: (5, 60] degrees. Below 5 the turn
#: radius at a fighter's speed is tens of kilometres and no drawn line
#: passes; above 60 the load factor exceeds 2 g and the stock aero tables
#: are not trusted there.
BANK_LIMIT_RANGE_DEG = (5.0, 60.0)
#: tecs.xml ``ap/tecs/hdot-max-fps`` 40 ft/s: the climb-rate DEMAND clip
#: in the energy loop, not a measured airframe climb rate. Pinned to the
#: XML by a test.
HDOT_MAX_MPS = 12.192
#: Pure pursuit looks this many seconds of true airspeed ahead along the
#: line (4 s: about one TECS heading-loop time constant, so the setpoint
#: leads the aircraft by the lag it has), never closer than
#: MIN_LOOKAHEAD_M (a slow airframe at 50 m/s would otherwise aim 200 m
#: ahead and hunt across the line).
LOOKAHEAD_S = 4.0
MIN_LOOKAHEAD_M = 120.0
#: The longest list the block carries: the map's pen resamples to a few
#: metres, and 400 points at the c172p's 55 m/s is far longer than the
#: longest scenario (MAX_DURATION_S, an hour) at the resample step.
MAX_WAYPOINTS = 400
G_MPS2 = 9.80665
#: A bend is refused when its radius falls below this fraction of the
#: radius at the bank limit: the heading hold overshoots a little into a
#: turn, and a drawn arc exactly at the limit is flown 10% wide.
TURN_RADIUS_SLACK = 0.9
#: The turn analysis resamples the line into this many steps per turn
#: radius (the window is one radius), never finer than
#: MIN_RESAMPLE_STEP_M.
TURN_WINDOW_STEPS = 16
MIN_RESAMPLE_STEP_M = 2.0
#: Two consecutive points closer than this are one point: a zero-length
#: leg has no bearing, and the mockup's pen never writes one.
MIN_LEG_M = 1.0
#: A leg's climb time is never taken shorter than this when the demand is
#: measured: a 1 m leg with a 5 m climb is not a 5 m/s demand on the
#: controller, which clips the rate, not the step.
CLIMB_MIN_LEG_S = 1.0
#: A point of the list: metres east and north of the spec origin in the
#: scene frame and the altitude in metres MSL. Nothing else is accepted.
WAYPOINT_KEYS = ("east_m", "north_m", "alt_m")

#: ISA troposphere: sigma = (1 - L h / T0) ** (g / (R L) - 1); above the
#: tropopause the isothermal layer's exponential. The CAS -> TAS conversion
#: is CAS / sqrt(sigma), which takes CAS for EAS (no compressibility
#: correction: at the A-4's 350 kt at 3000 m, Mach 0.63, EAS is about 2%
#: below CAS, so the planning TAS is about 2% high). This is the figure
#: the map and the validator plan with; the run's own TAS is what the
#: recorder shows, and the closure measures that.
ISA_T0_K = 288.15
ISA_LAPSE_K_PER_M = 0.0065
ISA_TROPOPAUSE_M = 11000.0
ISA_DENSITY_EXPONENT = 4.2559
ISA_STRATOSPHERE_SCALE_M = 6341.6

#: The recorder columns a route run adds (the guidance's own numbers,
#: held between its 2 Hz ticks) and the autopilot's commanded surface
#: norms (what tecs.xml writes), recorded so the control schedule can be
#: cut from the flight. Added ONLY when a route is stated, so every other
#: run's digest is unchanged.
RECORDER_COLUMNS = ("route_d_m", "route_cross_track_m",
                    "route_heading_setpoint_deg", "route_altitude_setpoint_m")
COMMAND_COLUMNS = {"aileron_cmd_norm": "fcs/aileron-cmd-norm",
                   "elevator_cmd_norm": "fcs/elevator-cmd-norm",
                   "rudder_cmd_norm": "fcs/rudder-cmd-norm"}
#: The run card's route block, fixed so the host and the page read one
#: shape; ``flown`` and ``replay_divergence_m`` are null until measured.
CARD_KEYS = ("waypoints", "digest", "bank_limit_deg", "lookahead_m", "flown",
             "replay_divergence_m")
#: The card's ``control_inputs`` entry: deltas on the trimmed command,
#: increasing ``t_s``, held by the host between entries.
SCHEDULE_KEYS = ("t_s", "aileron", "elevator", "rudder")


class RouteError(ValueError):
    """A route the build cannot fly, refused by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str, actual=None, limit=None,
                 unit: Optional[str] = None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {"constraint": self.constraint, "message": self.message,
                "actual": self.actual, "limit": self.limit, "unit": self.unit}


# -- speeds and radii ------------------------------------------------------------------

def tas_kt_isa(cas_kt: float, altitude_m: float) -> float:
    """True airspeed from calibrated airspeed in the standard atmosphere:
    CAS / sqrt(sigma) with sigma the ISA density ratio at the altitude
    (troposphere power law, isothermal layer above 11 km). CAS stands in
    for EAS (see the ISA constants' note); negative altitudes use sea
    level."""
    h = max(0.0, float(altitude_m))
    if h <= ISA_TROPOPAUSE_M:
        sigma = (1.0 - ISA_LAPSE_K_PER_M * h / ISA_T0_K) ** ISA_DENSITY_EXPONENT
    else:
        sigma_11 = (1.0 - ISA_LAPSE_K_PER_M * ISA_TROPOPAUSE_M / ISA_T0_K) ** ISA_DENSITY_EXPONENT
        sigma = sigma_11 * math.exp(-(h - ISA_TROPOPAUSE_M) / ISA_STRATOSPHERE_SCALE_M)
    return float(cas_kt) / math.sqrt(sigma)


def tas_kt_for_spec(spec) -> float:
    """The spec's true airspeed for planning: the stated speed when its
    kind is ``tas``, else :func:`tas_kt_isa` at the spec altitude."""
    airspeed = float(spec.airspeed.value)
    if str(spec.airspeed_kind.value) == "tas":
        return airspeed
    return tas_kt_isa(airspeed, float(spec.altitude.value))


def turn_radius_m(tas_kt: float, bank_deg: float) -> float:
    """The level-turn radius V^2 / (g tan phi) at a true airspeed and bank."""
    v = u.kt_to_mps(float(tas_kt))
    return v * v / (G_MPS2 * math.tan(math.radians(float(bank_deg))))


def lookahead_m_for(tas_kt: float) -> float:
    """The pure-pursuit lookahead: LOOKAHEAD_S of true airspeed, never
    below MIN_LOOKAHEAD_M."""
    return max(MIN_LOOKAHEAD_M, LOOKAHEAD_S * u.kt_to_mps(float(tas_kt)))


# -- geometry ----------------------------------------------------------------------

def _bearing_deg(e0: float, n0: float, e1: float, n1: float) -> float:
    """Grid bearing from (e0, n0) to (e1, n1), degrees clockwise from
    grid north in [0, 360)."""
    return math.degrees(math.atan2(e1 - e0, n1 - n0)) % 360.0


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def waypoint_tuples(waypoints: Any) -> Optional[List[Tuple[float, float, float]]]:
    """``[(east_m, north_m, alt_m)]`` from the block's list, or None when
    the list is not a list of exactly-keyed finite mappings (the shape
    refusal's reason is :func:`_shape_problem`'s; this only answers
    whether the numbers can be read)."""
    if not isinstance(waypoints, (list, tuple)):
        return None
    out = []
    for point in waypoints:
        if not isinstance(point, Mapping) or set(point) != set(WAYPOINT_KEYS):
            return None
        values = [point[key] for key in WAYPOINT_KEYS]
        if not all(_finite_number(v) for v in values):
            return None
        out.append((float(values[0]), float(values[1]), float(values[2])))
    return out


def route_length_m(waypoints: Any) -> Optional[float]:
    """The horizontal length of the line from the origin through the
    list, or None when the list cannot be read (the table's summary
    then says so rather than inventing a number)."""
    parsed = waypoint_tuples(waypoints)
    if parsed is None:
        return None
    points = [(0.0, 0.0)] + [(e, n) for e, n, _ in parsed]
    return sum(math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
               for i in range(len(points) - 1))


def _shape_problem(waypoints: Any) -> Optional[Dict[str, Any]]:
    """The one ``route.shape`` refusal for a list the build cannot read as
    a route, or None for a well-formed one."""
    def refuse(message, actual=None, limit=None, unit=None):
        return {"constraint": "route.shape", "message": message,
                "actual": actual, "limit": limit, "unit": unit}

    if not isinstance(waypoints, (list, tuple)):
        return refuse(f"route.waypoints must be a list of points {list(WAYPOINT_KEYS)}, "
                      f"not {type(waypoints).__name__}", actual=type(waypoints).__name__)
    if len(waypoints) < 1:
        return refuse("the route has no points: a route is at least one point after "
                      "the start, which is the aircraft's own position",
                      actual=0, limit=1, unit="points")
    if len(waypoints) > MAX_WAYPOINTS:
        return refuse(f"the route has {len(waypoints)} points; at most {MAX_WAYPOINTS} "
                      f"are carried", actual=len(waypoints), limit=MAX_WAYPOINTS,
                      unit="points")
    for i, point in enumerate(waypoints):
        if not isinstance(point, Mapping):
            return refuse(f"route.waypoints[{i}] is not a mapping "
                          f"{list(WAYPOINT_KEYS)}", actual=type(point).__name__)
        missing = [k for k in WAYPOINT_KEYS if k not in point]
        unknown = sorted(set(point) - set(WAYPOINT_KEYS))
        if missing or unknown:
            return refuse(f"route.waypoints[{i}] must carry exactly {list(WAYPOINT_KEYS)}"
                          + (f"; missing {missing}" if missing else "")
                          + (f"; unknown {unknown}" if unknown else ""))
        for key in WAYPOINT_KEYS:
            if not _finite_number(point[key]):
                return refuse(f"route.waypoints[{i}].{key} must be a finite number, "
                              f"not {point[key]!r}", actual=repr(point[key]))
    parsed = waypoint_tuples(waypoints)
    assert parsed is not None
    previous = (0.0, 0.0)
    for i, (e, n, _) in enumerate(parsed):
        leg = math.hypot(e - previous[0], n - previous[1])
        if leg < MIN_LEG_M:
            if i == 0:
                return refuse("the route's first point repeats the origin: the aircraft "
                              "already starts there, and the list begins AFTER the start",
                              actual=leg, limit=MIN_LEG_M, unit="m")
            return refuse(f"route.waypoints[{i}] repeats the point before it: a leg "
                          f"shorter than {MIN_LEG_M:g} m has no bearing",
                          actual=leg, limit=MIN_LEG_M, unit="m")
        previous = (e, n)
    return None


def _resample(points_en: Sequence[Tuple[float, float]], step_m: float):
    """Points along the polyline every ``step_m`` from the start, the end
    point last; returns ``(samples, arc_m)`` with each sample's distance
    along the line."""
    samples = [tuple(points_en[0])]
    arcs = [0.0]
    walked = 0.0            # distance along the line of the last sample
    cum = 0.0               # distance along the line at the current vertex
    for i in range(len(points_en) - 1):
        (e0, n0), (e1, n1) = points_en[i], points_en[i + 1]
        leg = math.hypot(e1 - e0, n1 - n0)
        if leg <= 0.0:
            continue
        target = walked + step_m
        while target <= cum + leg + 1e-9:
            t = (target - cum) / leg
            samples.append((e0 + t * (e1 - e0), n0 + t * (n1 - n0)))
            arcs.append(target)
            walked = target
            target += step_m
        cum += leg
    if cum - arcs[-1] > 1e-6:
        samples.append(tuple(points_en[-1]))
        arcs.append(cum)
    return samples, arcs


def tightest_turn_radius_m(points: Sequence[Tuple[float, ...]],
                           window_m: float) -> Optional[float]:
    """The mockup's ``turnAnalysis``: the line is resampled, the heading
    change over every window of about one turn radius (``window_m``)
    along it is measured, and the tightest implied radius (arc length /
    heading change) is returned; None for a line with no bend. The
    headings are padded BEFORE the start with the first leg's heading,
    because the aircraft begins already pointed along the first leg (the
    page sets the spec heading to it), so the start is never a bend."""
    xy = [(float(p[0]), float(p[1])) for p in points]
    step = max(MIN_RESAMPLE_STEP_M, float(window_m) / TURN_WINDOW_STEPS)
    samples, arcs = _resample(xy, step)
    if len(samples) < 2:
        return None
    headings = [_bearing_deg(*samples[i], *samples[i + 1]) for i in range(len(samples) - 1)]
    mids = [0.5 * (arcs[i] + arcs[i + 1]) for i in range(len(samples) - 1)]
    n = max(1, int(round(float(window_m) / step)))
    # The padding: n headings of the first leg, one step apart, before the start.
    headings = [headings[0]] * n + headings
    mids = [mids[0] - step * (n - k) for k in range(n)] + mids
    psi = [headings[0]]
    for h in headings[1:]:
        psi.append(psi[-1] + _wrap180(h - psi[-1]))
    tightest = None
    for k in range(len(psi) - n):
        change = abs(psi[k + n] - psi[k])
        arc = mids[k + n] - mids[k]
        if change < 1e-9 or arc <= 0.0:
            continue
        radius = arc / math.radians(change)
        tightest = radius if tightest is None else min(tightest, radius)
    return tightest


# -- the validator's list ------------------------------------------------------------

def route_problems(waypoints: Any, bank_limit_deg: Any, *, tas_kt: float,
                   duration_s: float, altitude0_m: float) -> List[Dict[str, Any]]:
    """Every way a route is outside what the autopilot flies, by name, in
    the validator's shape ``{"constraint", "message", "actual", "limit",
    "unit"}``:

    * ``route.shape`` -- not a list, fewer than 1 or more than
      MAX_WAYPOINTS points, a point that is not an exactly-keyed mapping
      of finite numbers, a first point on the origin, or a zero-length
      leg. A shape problem is the only one returned, because the others
      cannot be measured on a line that cannot be read;
    * ``route.bank_limit`` -- not a number, or outside BANK_LIMIT_RANGE_DEG;
      the turn check is skipped then (no radius to measure against: a
      guessed one would be a silent substitution);
    * ``route.time`` -- the line is longer than true airspeed x duration;
    * ``route.turn`` -- a bend tighter than TURN_RADIUS_SLACK x the radius
      at the bank limit (``actual`` the tightest radius, ``limit`` the
      floor enforced);
    * ``route.climb`` -- a leg whose altitude change over its flying time
      (never under CLIMB_MIN_LEG_S) exceeds HDOT_MAX_MPS.

    Terrain is NOT here: the validator is scene-free, and the web app's
    pre-flight flies the raster (``route.terrain_clearance``)."""
    shape = _shape_problem(waypoints)
    if shape is not None:
        return [shape]
    out: List[Dict[str, Any]] = []
    points = [(0.0, 0.0, float(altitude0_m))] + waypoint_tuples(waypoints)
    tas_mps = u.kt_to_mps(float(tas_kt))
    low, high = BANK_LIMIT_RANGE_DEG
    bank_ok = _finite_number(bank_limit_deg) and low < float(bank_limit_deg) <= high
    if not bank_ok:
        out.append({"constraint": "route.bank_limit",
                    "message": f"route.bank_limit_deg must be a number in ({low:g}, {high:g}] "
                               f"degrees, not {bank_limit_deg!r}",
                    "actual": bank_limit_deg if _finite_number(bank_limit_deg)
                    else repr(bank_limit_deg),
                    "limit": high, "unit": "deg"})
    length = sum(math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
                 for i in range(len(points) - 1))
    need_s = length / tas_mps if tas_mps > 0.0 else float("inf")
    if need_s > float(duration_s):
        out.append({"constraint": "route.time",
                    "message": f"the route is {length:.0f} m long, {need_s:.0f} s at "
                               f"{float(tas_kt):.0f} kt true airspeed, but the run lasts "
                               f"{float(duration_s):g} s",
                    "actual": need_s, "limit": float(duration_s), "unit": "s"})
    if bank_ok:
        radius_limit = turn_radius_m(tas_kt, float(bank_limit_deg))
        floor = TURN_RADIUS_SLACK * radius_limit
        tightest = tightest_turn_radius_m(points, radius_limit)
        if tightest is not None and tightest < floor:
            out.append({"constraint": "route.turn",
                        "message": f"a bend of the route has a radius of about {tightest:.0f} m, "
                                   f"tighter than the {floor:.0f} m floor ({TURN_RADIUS_SLACK:g} x "
                                   f"the {radius_limit:.0f} m turn radius at {float(bank_limit_deg):g} "
                                   f"degrees of bank and {float(tas_kt):.0f} kt true airspeed)",
                        "actual": tightest, "limit": floor, "unit": "m"})
    worst = 0.0
    for i in range(len(points) - 1):
        (e0, n0, a0), (e1, n1, a1) = points[i], points[i + 1]
        leg_s = max(CLIMB_MIN_LEG_S, math.hypot(e1 - e0, n1 - n0) / tas_mps
                    if tas_mps > 0.0 else CLIMB_MIN_LEG_S)
        worst = max(worst, abs(a1 - a0) / leg_s)
    if worst > HDOT_MAX_MPS:
        out.append({"constraint": "route.climb",
                    "message": f"a leg of the route climbs or descends at {worst:.1f} m/s, "
                               f"above the autopilot's {HDOT_MAX_MPS:g} m/s climb-rate demand "
                               f"limit (the energy loop's clip, not a measured airframe figure)",
                    "actual": worst, "limit": HDOT_MAX_MPS, "unit": "m/s"})
    return out


def terrain_clearance_problem(min_clearance_m: float) -> Optional[Dict[str, Any]]:
    """The web app's pre-flight refusal, ``route.terrain_clearance``, in
    the validator's shape when the measured minimum clearance over the
    flown line's span stations is below ROUTE_MIN_CLEARANCE_M; None when
    the floor is kept. Here, not in the web app, so the floor and the
    name have one source (``check_route`` and ``plan_route_flight``
    call it with the number they measured on the raster)."""
    clearance = float(min_clearance_m)
    if clearance >= ROUTE_MIN_CLEARANCE_M:
        return None
    return {"constraint": "route.terrain_clearance",
            "message": f"flown as drawn, the route comes within {clearance:.0f} m of the "
                       f"ground (measured on the raster at the span stations); the route "
                       f"keeps at least {ROUTE_MIN_CLEARANCE_M:g} m",
            "actual": clearance, "limit": ROUTE_MIN_CLEARANCE_M, "unit": "m"}


# -- the route ----------------------------------------------------------------------

class Route:
    """The polyline with its cumulative distance and altitude profile.

    ``points`` includes the origin ``(0, 0, altitude0_m)`` first; the
    block's list follows it. ``bank_limit_deg`` and ``tas_kt`` are what
    the route was planned at (the block's limit, the spec's planning
    TAS), so the card and the manifest say which radius and lookahead
    the line was checked against.
    """

    def __init__(self, waypoints: Any, altitude0_m: float, *, tas_kt: float,
                 bank_limit_deg: float = BANK_LIMIT_DEFAULT_DEG) -> None:
        shape = _shape_problem(waypoints)
        if shape is not None:
            raise RouteError(shape["constraint"], shape["message"], actual=shape["actual"],
                             limit=shape["limit"], unit=shape["unit"])
        self.points: List[Tuple[float, float, float]] = (
            [(0.0, 0.0, float(altitude0_m))] + waypoint_tuples(waypoints))
        self.bank_limit_deg = float(bank_limit_deg)
        self.tas_kt = float(tas_kt)
        self.lookahead_m = lookahead_m_for(self.tas_kt)
        self.cum_m: List[float] = [0.0]
        for i in range(len(self.points) - 1):
            (e0, n0, _), (e1, n1, _) = self.points[i], self.points[i + 1]
            self.cum_m.append(self.cum_m[-1] + math.hypot(e1 - e0, n1 - n0))
        self.length_m = self.cum_m[-1]
        self.initial_heading_deg = _bearing_deg(*self.points[0][:2], *self.points[1][:2])

    @classmethod
    def from_spec(cls, spec) -> Optional["Route"]:
        """The spec's route, or None for the default block (no route: the
        initial heading is held, exactly the run before routes existed)."""
        block = getattr(spec, "route", None)
        if block is None or block.is_default():
            return None
        return cls(block.waypoints.value, float(spec.altitude.value),
                   tas_kt=tas_kt_for_spec(spec),
                   bank_limit_deg=float(block.bank_limit_deg.value))

    @property
    def legs(self) -> int:
        return len(self.points) - 1

    def leg_heading_deg(self, leg: int) -> float:
        leg = min(max(leg, 0), self.legs - 1)
        return _bearing_deg(*self.points[leg][:2], *self.points[leg + 1][:2])

    def _leg_at(self, d_m: float) -> int:
        """The leg index whose span holds ``d_m`` (the last leg at and
        beyond the end, the first before the start)."""
        if d_m <= 0.0:
            return 0
        for i in range(self.legs):
            if d_m <= self.cum_m[i + 1]:
                return i
        return self.legs - 1

    def altitude_at(self, d_m: float) -> float:
        """The profile's altitude at a distance along the line, linear
        between points and held at the ends."""
        d = min(max(float(d_m), 0.0), self.length_m)
        i = self._leg_at(d)
        span = self.cum_m[i + 1] - self.cum_m[i]
        t = (d - self.cum_m[i]) / span if span > 0.0 else 0.0
        return self.points[i][2] + t * (self.points[i + 1][2] - self.points[i][2])

    def point_at(self, d_m: float) -> Tuple[float, float, float]:
        """``(east_m, north_m, alt_m)`` at a distance along the line.
        Beyond either end the position continues along that end's leg
        (so a target past the end keeps the last leg's bearing: the
        guidance holds that heading and still corrects the cross-track);
        the altitude is the profile's, held at the ends."""
        d = float(d_m)
        i = self._leg_at(d)
        (e0, n0, _), (e1, n1, _) = self.points[i], self.points[i + 1]
        span = self.cum_m[i + 1] - self.cum_m[i]
        t = (d - self.cum_m[i]) / span if span > 0.0 else 0.0
        return e0 + t * (e1 - e0), n0 + t * (n1 - n0), self.altitude_at(d)

    def _project_raw(self, east_m: float, north_m: float) -> Tuple[float, float, int]:
        """``(d_m, cross_track_m, leg)`` of the nearest point of the line.
        ``d_m`` runs negative before the start and past ``length_m``
        beyond the end (the end legs extended), so the guidance keeps
        advancing its target; cross-track is signed, positive to the
        RIGHT of the direction of travel."""
        best = None
        for i in range(self.legs):
            (e0, n0, _), (e1, n1, _) = self.points[i], self.points[i + 1]
            de, dn = e1 - e0, n1 - n0
            span2 = de * de + dn * dn
            pe, pn = east_m - e0, north_m - n0
            t = (pe * de + pn * dn) / span2 if span2 > 0.0 else 0.0
            if i > 0:
                t = max(t, 0.0)
            if i < self.legs - 1:
                t = min(t, 1.0)
            ce, cn = e0 + t * de, n0 + t * dn
            distance = math.hypot(east_m - ce, north_m - cn)
            if best is None or distance < best[0] - 1e-9:
                span = math.sqrt(span2)
                xte = (pe * dn - pn * de) / span if span > 0.0 else 0.0
                best = (distance, self.cum_m[i] + t * span, xte, i)
        assert best is not None
        return best[1], best[2], best[3]

    def project(self, east_m: float, north_m: float) -> Tuple[float, float]:
        """``(d_m, cross_track_m)``: the distance along the line of the
        nearest point, clamped to ``[0, length_m]``, and the signed
        cross-track distance (positive right of the direction of travel;
        beyond the ends it is measured from that end's leg extended)."""
        d, xte, _ = self._project_raw(east_m, north_m)
        return min(max(d, 0.0), self.length_m), xte

    def digest(self) -> str:
        """SHA-256 over the point list (the origin included), floats as
        ``repr`` so two lists that differ in the last bit differ here."""
        payload = json.dumps([[e, n, a] for e, n, a in self.points], separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def waypoint_dicts(self) -> List[Dict[str, float]]:
        """The block's list back as mappings (the origin excluded, as the
        block carries it)."""
        return [{"east_m": e, "north_m": n, "alt_m": a} for e, n, a in self.points[1:]]

    def point_dicts(self) -> List[Dict[str, float]]:
        """Every point of the flown line, the origin first (the manifest's
        ``points``)."""
        return [{"east_m": e, "north_m": n, "alt_m": a} for e, n, a in self.points]


# -- the guidance -------------------------------------------------------------------

class RouteGuidance:
    """Pure pursuit along the route, setpoints only, at the harness's 2 Hz.

    Each tick: the aircraft's position is taken into the scene frame
    (``frame.north_east`` of the state's latitude / longitude), projected
    on the line (``d``), the target is the point ``lookahead_m`` further
    along the line (continuing along the last leg past the end), the
    heading setpoint is the grid bearing from the aircraft to the target
    and the altitude setpoint is the profile's at the target; both go
    through ``autopilot.command``. ``last`` holds the tick's numbers for
    the recorder (held between ticks: the recorder samples at 10 Hz, the
    guidance runs at 2 Hz, so a column changes every fifth row).
    """

    def __init__(self, route: Route, frame, autopilot, tas_mps: float) -> None:
        self.route = route
        self.frame = frame
        self.autopilot = autopilot
        self.lookahead_m = max(MIN_LOOKAHEAD_M, LOOKAHEAD_S * float(tas_mps))
        self.last: Dict[str, float] = {
            "d_m": 0.0, "cross_track_m": 0.0,
            "heading_setpoint_deg": route.initial_heading_deg,
            "altitude_setpoint_m": route.altitude_at(self.lookahead_m), "leg": 0,
        }

    def update(self, state) -> None:
        north, east = self.frame.north_east(float(state.lat_deg), float(state.lon_deg))
        d_raw, xte, leg = self.route._project_raw(east, north)
        ahead = d_raw + self.lookahead_m
        target_e, target_n, _ = self.route.point_at(ahead)
        heading = _bearing_deg(east, north, target_e, target_n)
        altitude = self.route.altitude_at(ahead)
        self.autopilot.command(heading_deg=heading, altitude_m=altitude)
        self.last = {
            "d_m": min(max(d_raw, 0.0), self.route.length_m), "cross_track_m": xte,
            "heading_setpoint_deg": heading, "altitude_setpoint_m": altitude, "leg": leg,
        }


def route_recorder_extras(guidance: Optional[RouteGuidance]) -> Dict[str, Callable[[Any], float]]:
    """The route run's extra recorder columns (RECORDER_COLUMNS from the
    guidance's ``last``, COMMAND_COLUMNS from the FDM's commanded surface
    norms); {} without a guidance, so a run with no route records exactly
    what it did before."""
    if guidance is None:
        return {}
    out: Dict[str, Callable[[Any], float]] = {}
    for column in RECORDER_COLUMNS:
        key = column[len("route_"):]
        out[column] = (lambda fdm, key=key: float(guidance.last[key]))
    for column, prop in COMMAND_COLUMNS.items():
        out[column] = (lambda fdm, prop=prop: float(fdm.props.get(prop)))
    return out


# -- the closure -------------------------------------------------------------------

@dataclass(frozen=True)
class RouteTolerance:
    """Declared before the run, not fitted to it: the flown track stays
    within ``cross_track_m`` of the line and within ``altitude_m`` of its
    profile at every sample."""

    cross_track_m: float = 75.0
    altitude_m: float = 30.0


def route_closure(route: Route, frame, lat_deg: Sequence[float], lon_deg: Sequence[float],
                  altitude_m: Sequence[float], tolerance: RouteTolerance = RouteTolerance(),
                  lookahead_m: float = MIN_LOOKAHEAD_M) -> list:
    """The route-aware closure checks, over EVERY sample (a route has no
    settled tail to wait for): ``cross_track_max`` (the largest |cross
    track|, tolerance ``cross_track_m``), ``route_altitude`` (the largest
    |altitude - profile at the sample's d|, tolerance ``altitude_m``) and
    ``route_reached`` (the furthest d against the length, tolerance the
    guidance's lookahead: the target is that far ahead of the aircraft,
    so the end is reached when the aircraft comes within it)."""
    from .autopilot import ClosureCheck

    worst_xte = 0.0
    worst_alt = 0.0
    furthest = 0.0
    for lat, lon, alt in zip(lat_deg, lon_deg, altitude_m):
        north, east = frame.north_east(float(lat), float(lon))
        d, xte = route.project(east, north)
        worst_xte = max(worst_xte, abs(xte))
        worst_alt = max(worst_alt, abs(float(alt) - route.altitude_at(d)))
        furthest = max(furthest, d)
    return [
        ClosureCheck("cross_track_max", 0.0, worst_xte, tolerance.cross_track_m, "m"),
        ClosureCheck("route_altitude", 0.0, worst_alt, tolerance.altitude_m, "m"),
        ClosureCheck("route_reached", route.length_m, furthest, float(lookahead_m), "m"),
    ]


# -- the render host's inputs ---------------------------------------------------------

def control_schedule(telemetry_samples: Mapping[str, Sequence[float]],
                     trims: Mapping[str, float], hz: float = 10.0) -> List[Dict[str, float]]:
    """The run card's ``control_inputs`` cut from a route flight: one
    entry per 1/hz from t = 0 to the last sample, each the commanded
    surface norm (the recorder's COMMAND_COLUMNS, the telemetry's
    ``columns`` mapping with its ``t``) at the latest sample at or before
    that time, MINUS the trim command captured at engage (``trims``:
    ``aileron`` / ``elevator`` / ``rudder``, the autopilot's
    ``ap/trim/*``). Deltas on trim because that is what the host applies
    (aileron set, elevator added to trim, rudder as given) and holds
    between entries. ``t_s`` is the RUN's clock -- seconds from the first
    sample, the trimmed state at engage -- not the FDM's sim time, which
    has already run through the trim and the engine start when the first
    sample is taken (measured: the c172p's first sample is at 4.8 s).
    Open loop by construction: the host has no autopilot."""
    t = [float(v) for v in telemetry_samples["t"]]
    if not t:
        return []
    t = [v - t[0] for v in t]
    columns = {name: list(telemetry_samples[column])
               for name, column in (("aileron", "aileron_cmd_norm"),
                                    ("elevator", "elevator_cmd_norm"),
                                    ("rudder", "rudder_cmd_norm"))}
    out: List[Dict[str, float]] = []
    j = 0
    k = 0
    while True:
        at = round(k / float(hz), 6)
        if at > t[-1] + 1e-9:
            break
        while j + 1 < len(t) and t[j + 1] <= at + 1e-9:
            j += 1
        entry = {"t_s": at}
        for name, values in columns.items():
            entry[name] = float(values[j]) - float(trims[name])
        out.append(entry)
        k += 1
    return out


def route_card_block(route: Route, flown: Optional[Sequence[Mapping[str, float]]] = None,
                     schedule: Optional[Sequence[Mapping[str, float]]] = None,
                     divergence_m: Optional[float] = None) -> Dict[str, Any]:
    """The run card's ``route`` block, CARD_KEYS exactly: the block's
    waypoints (the origin excluded, as the spec carries them), the point
    list's digest, the bank limit and lookahead the line was flown with,
    the flown track (``{t_s, north_m, east_m, alt_m, yaw_deg, pitch_deg,
    roll_deg}`` like traffic poses; the host may ignore it) and the
    measured open-loop replay divergence -- null until measured. The
    control schedule rides on the card as ``control_inputs`` (the host's
    one steering input) and is not duplicated here; when given it is
    checked for the card's shape (SCHEDULE_KEYS, increasing ``t_s``) so a
    malformed schedule is refused before the host holds it."""
    if schedule is not None:
        last = None
        for i, entry in enumerate(schedule):
            if set(entry) != set(SCHEDULE_KEYS):
                raise RouteError("route.shape", f"control schedule entry {i} must carry "
                                 f"exactly {list(SCHEDULE_KEYS)}, not {sorted(entry)}")
            if last is not None and float(entry["t_s"]) <= last:
                raise RouteError("route.shape", f"control schedule entry {i} at "
                                 f"{float(entry['t_s']):g} s does not follow entry {i - 1} "
                                 f"at {last:g} s", actual=float(entry["t_s"]), limit=last,
                                 unit="s")
            last = float(entry["t_s"])
    block = {
        "waypoints": route.waypoint_dicts(),
        "digest": route.digest(),
        "bank_limit_deg": route.bank_limit_deg,
        "lookahead_m": route.lookahead_m,
        "flown": None if flown is None else [dict(pose) for pose in flown],
        "replay_divergence_m": None if divergence_m is None else float(divergence_m),
    }
    assert tuple(block) == CARD_KEYS
    return block
