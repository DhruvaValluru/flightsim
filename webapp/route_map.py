"""The route map's server half: the ground to draw on, the line flown for real.

docs/ROUTE.md "The web app". The page draws a flight path on the scene
the physics flies and asks the server to check it; the server flies it
-- JSBSim, the TECS autopilot and the route guidance
(core/control/route.py) over the scene's full raster -- and answers with
the flown track and the measures the design names. Three entry points:

* :func:`terrain_payload_for_route` -- the camera placer's terrain
  payload (``webapp.camera_placer.terrain_payload``: same 129 x 129 grid,
  same frame, same caps) with the window sized to the circle of
  everything the aircraft can reach in the run (true airspeed x the
  run's seconds), plus the ``route`` block: every limit the map shows,
  each a constant of core/control/route.py, so the page never types a
  number of its own;
* :func:`check_route` -- the physics check: the line written into a COPY
  of the spec as user-stated, the copy planned the way ``/run`` plans it,
  validated (refusals by name, nothing flown) and flown closed loop with
  ``run_spec`` over the scene's raster; the flown track comes back in
  the scene frame with the minimum ground clearance over the span
  stations, the worst cross-track and the closure checks, and
  ``route.terrain_clearance`` by name when the line comes within
  ``ROUTE_MIN_CLEARANCE_M`` of the ground;
* :func:`plan_route_flight` -- the ``/run`` planner: the same flight,
  then the control schedule the render host steers from (the autopilot's
  commanded surfaces as deltas on trim, ``control_schedule``), the
  open-loop replay of that schedule on a stock FDM
  (``webapp.runs._fly_clearance_track``, the host's own rule for
  applying the entries) and the MEASURED divergence between the two
  tracks, which rides on the run card as ``route.replay_divergence_m``.

What is claimed: the headless run flies the route closed loop; the
render is open loop and follows it as well as two JSBSim builds
replaying one schedule agree, and that figure is measured here, not
assumed. The replay is still air over the same ground with the spec's
steady wind and the scene's orographic field (the clearance planner's
own pre-flight air); turbulence, when the spec words it, is in the
closed-loop flight (the environment stack, the spec's seed as it stands
when the planner runs) and not in the replay, so a turbulent route's
divergence includes what the autopilot did about the gusts.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.control.route import (
    BANK_LIMIT_RANGE_DEG,
    HDOT_MAX_MPS,
    ROUTE_MIN_CLEARANCE_M,
    Route,
    RouteError,
    control_schedule,
    lookahead_m_for,
    route_card_block,
    tas_kt_for_spec,
    terrain_clearance_problem,
    turn_radius_m,
)
from core.fdm import units as u
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate
from webapp.camera_placer import (
    GRID_POINTS,
    MAX_HALF_EXTENT_M,
    MIN_HALF_EXTENT_M,
    PlacementError,
    _sample_grid,
    terrain_payload,
)

# The runs module by name, not its members: tests redirect TERRAIN_DIR and
# pick_scene on the module, and a binding taken at import time would keep
# flying the real scene picker under a redirected one.
import webapp.runs as runs

#: Provenance every field the map writes carries (docs/ROUTE.md step 6);
#: the page says "... then self-adjusted" when self adjust moved the line.
ROUTE_FROM = "drawn on the route map"
#: The heading the copy flies: the first leg's bearing, user-stated so no
#: planner moves it (the page writes the same value into the spec).
HEADING_FROM = "drawn on the route map: the first leg's bearing"
#: The window's margin beyond the reach circle: the camera placer's own
#: rule (reach x 1.25 + 1000 m) applied to the circle's radius instead
#: of the straight-line track's end, so the two maps share one rule.
WINDOW_REACH_FACTOR = 1.25
WINDOW_MARGIN_M = 1000.0
#: The control schedule's rate: the recorder's 10 Hz, one entry per
#: sample, so the host holds each commanded surface for the 0.1 s the
#: autopilot held it.
SCHEDULE_HZ = 10.0
#: The flown track's numbers are rounded to centimetres for the page and
#: the card: the physics is not accurate below that and the JSON halves.
TRACK_DECIMALS = 2
#: Where :func:`plan_route_flight` leaves its result for
#: ``RunManager._render_flow``. The run endpoint hands the manager the
#: SAME spec object it planned, and the planners that follow the route
#: pre-flight (the seed, the envelope floors, the host projection) move
#: the digest, so a cache keyed by digest would miss there; the object
#: is the one thing both ends hold. Not a spec field: ``to_dict`` and the
#: digest never see it, and a spec re-read from its dict arrives without
#: it, in which case :func:`route_flight_for` flies the pre-flight then.
ROUTE_FLIGHT_ATTR = "_route_flight"


# -- the ground to draw on ----------------------------------------------------------

def _reach_window_m(tas_kt: float, seconds: float):
    """``(reach_m, half_m)``: the radius of the circle the aircraft can
    reach (true airspeed x seconds) and the half-width of the window
    that shows it, the placer's rule and caps."""
    reach = u.kt_to_mps(float(tas_kt)) * float(seconds)
    half = min(max(MIN_HALF_EXTENT_M, reach * WINDOW_REACH_FACTOR + WINDOW_MARGIN_M),
               MAX_HALF_EXTENT_M)
    return reach, half


def _bank_limit_or_refuse(spec: ScenarioSpec) -> float:
    """The block's bank limit when it is one the autopilot flies, else
    ``route.bank_limit`` by name: a turn radius at 0 or 90 degrees is not
    a number, and the map would otherwise draw against a guessed one."""
    value = spec.route.bank_limit_deg.value
    low, high = BANK_LIMIT_RANGE_DEG
    if (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low < float(value) <= high):
        return float(value)
    raise RouteError("route.bank_limit",
                     f"route.bank_limit_deg must be a number in ({low:g}, {high:g}] "
                     f"degrees, not {value!r}; the map shows no radius for it",
                     actual=value if isinstance(value, (int, float)) else repr(value),
                     limit=high, unit="deg")


def terrain_payload_for_route(spec: ScenarioSpec, scene: Dict,
                              clip_seconds: float) -> Dict[str, Any]:
    """The placer's terrain payload, windowed to the route's reach, with
    the ``route`` block of limits.

    The base is ``camera_placer.terrain_payload`` as it stands (one
    source for the frame, the aircraft, the lens and the flat rule), and
    only its ``grid`` is replaced: the placer sizes its window to the
    straight-line track, the map to the circle of everything the
    aircraft can reach in ``seconds`` at true airspeed, so the raster is
    sampled again at that window (the same ``_sample_grid``, the same
    129 points, the same caps). ``seconds`` is ``min(duration,
    clip_seconds)``, the placer's clock, and the block says so beside the
    spec's own duration. The limits are core/control/route.py's
    constants and functions; a stated bank limit outside the range the
    autopilot flies refuses by name rather than drawing a radius at it.
    """
    from core.capture.poses import SceneFrame
    from core.terrain.heightfield import Heightfield

    payload = terrain_payload(spec, scene, clip_seconds)
    seconds = float(payload["clip_seconds"])
    tas = tas_kt_for_spec(spec)
    bank = _bank_limit_or_refuse(spec)
    reach, half = _reach_window_m(tas, seconds)
    datum = float(spec.terrain_elevation.value)
    heightfield = None
    terrain = scene.get("terrain")
    if terrain and runs.baked(Path(terrain)):
        heightfield = Heightfield.read(Path(terrain))
    if heightfield is not None:
        frame = SceneFrame.for_spec(spec, heightfield)
        heights, step, points = _sample_grid(heightfield, frame, half, GRID_POINTS)
    else:
        # Flat: the datum IS the ground, the placer's rule (a 2 x 2 slab).
        points, step, heights = 2, 2.0 * half, [datum] * 4
    half_used = step * (points - 1) / 2.0
    payload["grid"] = {"points": points, "step_m": step,
                       "south_m": -half_used, "west_m": -half_used,
                       "heights_m": heights}
    block = spec.route
    payload["route"] = {
        "tas_kt": tas,
        "tas_basis": ("the stated true airspeed" if str(spec.airspeed_kind.value) == "tas"
                      else "ISA conversion of the calibrated airspeed at the spec "
                           "altitude (core/control/route.py tas_kt_isa)"),
        "turn_radius_m": turn_radius_m(tas, bank),
        "bank_limit_deg": bank,
        "bank_limit_max_deg": BANK_LIMIT_RANGE_DEG[1],
        "hdot_max_mps": HDOT_MAX_MPS,
        "min_clearance_m": ROUTE_MIN_CLEARANCE_M,
        "lookahead_m": lookahead_m_for(tas),
        "seconds": seconds,
        "duration_s": float(spec.duration.value),
        "clip_cap_s": float(clip_seconds),
        "seconds_basis": "min(duration, the render's clip cap): the camera placer's clock",
        "reach_m": reach,
        "half_extent_m": half_used,
        "stated": not block.is_default(),
        "waypoints": (list(block.waypoints.value)
                      if isinstance(block.waypoints.value, (list, tuple)) else []),
        "from": block.waypoints.frm,
    }
    return payload


# -- the flight ---------------------------------------------------------------------

def _violation_dict(violation) -> Dict[str, Any]:
    """A validator Violation in the dict shape every refusal here uses."""
    return {"constraint": violation.constraint, "message": violation.message,
            "actual": violation.actual, "limit": violation.limit,
            "unit": violation.unit}


def _closure_problem(checks: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``route.closure`` when the closed-loop flight did not close on the
    line (a check of the route-aware closure, core/control/route.py
    route_closure, outside its declared tolerance), in the validator's
    shape; None when every check passed. The run itself would refuse
    the same flight (ClosureError: no output), so the pre-flight says
    it first."""
    failed = [c for c in checks if not c.get("ok", False)]
    if not failed:
        return None
    first = failed[0]
    described = "; ".join(
        f"{c['name']} reached {float(c['achieved']):.1f} {c['unit']} against "
        f"{float(c['commanded']):.1f} (tolerance {float(c['tolerance']):.1f} {c['unit']})"
        for c in failed)
    return {"constraint": "route.closure",
            "message": f"flown as drawn, the autopilot did not close on the line: "
                       f"{described}; the run would produce no output",
            "actual": float(first["achieved"]), "limit": float(first["tolerance"]),
            "unit": first["unit"]}


def _ground_for(scene: Dict):
    """The run's ground model over a baked scene, None over the slab
    (``run_spec``'s own convention: the spec's flat terrain elevation)."""
    terrain = scene.get("terrain")
    if not terrain or not runs.baked(Path(terrain)):
        return None
    from core.terrain.ground import TerrainGround
    from core.terrain.heightfield import Heightfield

    return TerrainGround(Heightfield.read(Path(terrain)))


_WINGSPAN_M: Dict[str, float] = {}


def _wingspan_m(aircraft: str) -> float:
    """The airframe's span from its own model, ``metrics/bw-ft`` (what
    core.terrain.contact reads from the live FDM); loaded once per
    aircraft per process, since a flat run has no contact record to
    carry it."""
    if aircraft not in _WINGSPAN_M:
        from core.fdm import FlightDynamics

        _WINGSPAN_M[aircraft] = u.ft_to_m(float(
            FlightDynamics(aircraft).props.get("metrics/bw-ft")))
    return _WINGSPAN_M[aircraft]


def _route_copy(spec: ScenarioSpec, waypoints: Any = None, bank_limit_deg: Any = None,
                *, restore_autopilot: bool) -> ScenarioSpec:
    """The spec the pre-flight flies: a copy through the canonical dict,
    with the page's line and bank limit written as USER-stated
    (``ROUTE_FROM``) when given, and the autopilot switched back on when
    asked (a spec reaching the render flow has been projected for the
    host, which has none; the route is flown by the autopilot's
    setpoints, so the pre-flight needs it). The heading is the caller's
    (:func:`_preflight`): the physics check sets it to the first leg's
    bearing, since the page's spec still carries the prompt's heading;
    ``/run``'s spec already carries the heading the page wrote and is
    flown as it stands."""
    copy = ScenarioSpec.from_dict(spec.to_dict())
    if waypoints is not None:
        copy.set("route.waypoints", waypoints, frm=ROUTE_FROM)
    if bank_limit_deg is not None:
        copy.set("route.bank_limit_deg", bank_limit_deg, frm=ROUTE_FROM)
    if restore_autopilot and not bool(copy.hold_state.value):
        copy.set("hold_state", True,
                 frm="the route pre-flight flies the autopilot the host projection "
                     "switched off (the render steers from the control schedule)")
    return copy


def _plan_copy(copy: ScenarioSpec) -> None:
    """The copy planned the way ``/run`` plans the spec before the route
    pre-flight: scene-setting, the water surface, placement on the
    scene, the terrain environment (cross-ridge wind, along-ridge
    heading when defaulted) -- each idempotent, so a spec ``/run``
    already planned is left as it is. Never ``project_for_ue_host``:
    the pre-flight is the closed-loop run, not the open-loop render."""
    runs.plan_scene_setting(copy)
    runs.plan_water_surface(copy)
    runs.place_on_scene(copy)
    runs.plan_terrain_environment(copy)


def _station_clearance_m(ground, datum: float, x: float, y: float, alt: float,
                         agl: float, roll: float, pitch: float, heading: float,
                         span_m: float) -> float:
    """The minimum clearance over the CG and the airframe's span stations
    at one sample: core.terrain.contact's stations, rotation and lookup
    (the check that ends the real run), the raster bilinear at each
    station inside it, the datum under every station over the slab."""
    from core.terrain.contact import station_offsets_ned

    clearance = float(agl)
    for _, north, east, down in station_offsets_ned(roll, pitch, heading, span_m):
        if ground is None:
            terrain = datum
        else:
            px, py = x + east, y + north
            if not ground.heightfield.contains(px, py):
                continue
            terrain = ground.heightfield.elevation_at(px, py)
        clearance = min(clearance, (alt - down) - terrain)
    return clearance


def _replay_divergence_m(closed: Sequence[Dict[str, float]],
                         replay: Sequence[Dict[str, float]], frame) -> Optional[float]:
    """The worst 3-D distance, metres, between the closed-loop track and
    the open-loop replay at the same run time: the replay (sampled on
    its own clock, one FDM step after each closed-loop sample) is
    interpolated linearly onto the closed-loop sample times inside the
    replay's span, both tracks in the same frame (the recorded latitude
    and longitude of each through ``frame.north_east``). None when the
    two share no time (an empty replay)."""
    if len(replay) < 2:
        return None
    rt = [float(p["t_s"]) for p in replay]
    rp = []
    for p in replay:
        north, east = frame.north_east(float(p["lat_deg"]), float(p["lon_deg"]))
        rp.append((north, east, float(p["alt_m"])))
    worst = None
    j = 0
    for sample in closed:
        t = float(sample["t_s"])
        if t < rt[0] or t > rt[-1]:
            continue
        while j + 1 < len(rt) and rt[j + 1] < t:
            j += 1
        span = rt[j + 1] - rt[j]
        w = (t - rt[j]) / span if span > 0.0 else 0.0
        north = rp[j][0] + w * (rp[j + 1][0] - rp[j][0])
        east = rp[j][1] + w * (rp[j + 1][1] - rp[j][1])
        alt = rp[j][2] + w * (rp[j + 1][2] - rp[j][2])
        distance = math.sqrt((north - float(sample["north_m"])) ** 2
                             + (east - float(sample["east_m"])) ** 2
                             + (alt - float(sample["alt_m"])) ** 2)
        worst = distance if worst is None else max(worst, distance)
    return worst


def _preflight(spec: ScenarioSpec, waypoints: Any = None, bank_limit_deg: Any = None, *,
               heading_to_first_leg: bool = False, restore_autopilot: bool = False,
               replay: bool = False) -> Dict[str, Any]:
    """The closed-loop route flight and its measures (the one flight
    :func:`check_route` and :func:`plan_route_flight` share).

    Returns ``stage`` ``"validation"`` (refused by name, nothing flown:
    ``violations`` the validator's, ``flown`` None) or ``"flight"``
    (flown: ``flown`` the track in the scene frame, ``min_clearance_m``
    over the span stations, ``max_cross_track_m`` from the route's own
    recorder column, ``closure`` the run's checks as dicts, ``violations``
    ``route.terrain_clearance`` and ``route.closure`` when earned, ``ok``,
    ``seconds`` flown), and with ``replay`` the control schedule, the
    replay divergence and the card block as well.
    """
    from core.scenario.runner import run_spec, scene_frame_for
    from core.terrain.contact import TerrainImpactError

    copy = _route_copy(spec, waypoints, bank_limit_deg, restore_autopilot=restore_autopilot)
    try:
        # Route construction refuses a malformed list by name (route.shape):
        # the validation stage, nothing flown.
        route = Route.from_spec(copy)
    except RouteError as exc:
        return {"stage": "validation", "ok": False, "violations": [exc.to_dict()],
                "flown": None}
    if route is None:
        raise ValueError("no route is stated: nothing to fly")
    if heading_to_first_leg:
        copy.set("heading", route.initial_heading_deg, frm=HEADING_FROM)
    _plan_copy(copy)
    report = validate(copy)
    if not report.ok:
        return {"stage": "validation", "ok": False,
                "violations": [_violation_dict(v) for v in report.violations],
                "flown": None, "heading_deg": float(copy.heading.value),
                "bank_limit_deg": route.bank_limit_deg}
    scene = runs.pick_scene(copy)
    ground = _ground_for(scene)
    datum = float(copy.terrain_elevation.value)
    frame = scene_frame_for(copy, ground)
    violations: List[Dict[str, Any]] = []
    try:
        result = run_spec(copy, validate_first=False, assert_closure=False,
                          terrain_ground=ground)
    except TerrainImpactError as exc:
        # A span station entered the raster: the clearance is the
        # penetration, negative, and the refusal is the clearance one.
        impact = exc.impact
        problem = terrain_clearance_problem(-float(impact.penetration_m))
        problem["message"] += (f" -- the {impact.station} entered the terrain at "
                               f"{float(impact.time_s):.1f} s, so the flight ended there")
        return {"stage": "flight", "ok": False, "violations": [problem], "flown": None,
                "min_clearance_m": -float(impact.penetration_m), "max_cross_track_m": None,
                "closure": [], "seconds": float(impact.time_s),
                "heading_deg": float(copy.heading.value),
                "bank_limit_deg": route.bank_limit_deg, "scene": scene.get("key")}
    columns = result.telemetry.columns
    t0 = float(columns["t"][0])
    span_m = (float(result.manifest["airframe_contact"]["wingspan_m"])
              if result.manifest.get("airframe_contact") else _wingspan_m(str(copy.aircraft.value)))
    flown: List[Dict[str, float]] = []
    min_clearance = None
    n = len(columns["t"])
    for i in range(n):
        lat, lon = float(columns["lat_deg"][i]), float(columns["lon_deg"][i])
        alt, agl = float(columns["altitude_m"][i]), float(columns["agl_m"][i])
        roll, pitch = float(columns["roll_deg"][i]), float(columns["pitch_deg"][i])
        heading = float(columns["heading_deg"][i])
        north, east = frame.north_east(lat, lon)
        x, y = ground.project(lat, lon) if ground is not None else (east, north)
        clearance = _station_clearance_m(ground, datum, x, y, alt, agl, roll, pitch,
                                         heading, span_m)
        min_clearance = clearance if min_clearance is None else min(min_clearance, clearance)
        flown.append({"t_s": round(float(columns["t"][i]) - t0, 3),
                      "north_m": round(north, TRACK_DECIMALS),
                      "east_m": round(east, TRACK_DECIMALS),
                      "alt_m": round(alt, TRACK_DECIMALS),
                      "agl_m": round(agl, TRACK_DECIMALS),
                      "heading_deg": round(heading, TRACK_DECIMALS),
                      "pitch_deg": round(pitch, TRACK_DECIMALS),
                      "roll_deg": round(roll, TRACK_DECIMALS)})
    checks = list(result.manifest["closure"]["checks"])
    # One number, rounded once: the refusal's ``actual`` and the reply's
    # ``min_clearance_m`` are the same figure.
    min_clearance = round(float(min_clearance), TRACK_DECIMALS)
    clearance_problem = terrain_clearance_problem(min_clearance)
    if clearance_problem is not None:
        violations.append(clearance_problem)
    closure_problem = _closure_problem(checks)
    if closure_problem is not None:
        violations.append(closure_problem)
    out: Dict[str, Any] = {
        "stage": "flight", "ok": not violations, "violations": violations,
        "flown": flown, "min_clearance_m": min_clearance,
        "clearance_floor_m": ROUTE_MIN_CLEARANCE_M,
        "max_cross_track_m": round(max(abs(float(v)) for v in columns["route_cross_track_m"]),
                                   TRACK_DECIMALS),
        "closure": checks, "seconds": round(float(columns["t"][-1]) - t0, 3),
        # The datum the copy flew over -- the PLANNED spec's (scene-setting
        # stages a place for a placeless prompt), which can differ from
        # the page's unplanned dict; said here so no reader guesses it.
        "datum_m": datum,
        "heading_deg": float(copy.heading.value), "bank_limit_deg": route.bank_limit_deg,
        "lookahead_m": route.lookahead_m, "digest": route.digest(),
        "scene": scene.get("key"), "physics_ground": scene.get("label"),
        "measured_on": ("the scene raster at the span stations" if ground is not None
                        else "the flat slab at the spec's datum"),
    }
    if not replay or violations:
        return out
    # The render host's steering: the autopilot's commanded surfaces as
    # deltas on the trim captured at engage, one entry per sample, and
    # the same schedule replayed open loop on the stock FDM exactly as
    # the host applies it, over the clip the host flies, so the
    # divergence on the card is the clip's.
    trims = result.manifest["route"]["trims"]
    schedule = control_schedule(columns, trims, hz=SCHEDULE_HZ)
    replay_seconds = min(float(copy.duration.value), runs.CLIP_SECONDS)
    replayed = runs._fly_clearance_track(copy, ground, schedule, replay_seconds,
                                         orographic=runs._orographic_provider(copy, scene),
                                         clock="run")
    divergence = _replay_divergence_m(flown, replayed, frame)
    # Rounded once: the card's figure and the reply's are one number.
    if divergence is not None:
        divergence = round(float(divergence), TRACK_DECIMALS)
    poses = [{"t_s": p["t_s"], "north_m": p["north_m"], "east_m": p["east_m"],
              "alt_m": p["alt_m"], "yaw_deg": p["heading_deg"], "pitch_deg": p["pitch_deg"],
              "roll_deg": p["roll_deg"]} for p in flown]
    out.update({
        "schedule": schedule,
        "replay_seconds": replay_seconds,
        "replay_divergence_m": divergence,
        "replay_min_clearance_m": (round(min(p["clearance_m"] for p in replayed), TRACK_DECIMALS)
                                   if replayed else None),
        "card": route_card_block(route, flown=poses, schedule=schedule,
                                 divergence_m=divergence),
    })
    return out


def check_route(spec: Any, waypoints: Any, bank_limit_deg: Any = None) -> Dict[str, Any]:
    """The physics check (docs/ROUTE.md step 5): ``spec`` the page's spec
    (a ``ScenarioSpec`` or its dict), ``waypoints`` the drawn line in
    the scene frame, ``bank_limit_deg`` the map's bank limit (None: the
    block's own). The line is written into a COPY as user-stated, the
    heading set to the first leg, the copy planned and validated --
    ``ok`` False with the validator's ``violations`` and ``flown`` None
    on a problem -- then flown closed loop over the scene's raster (the
    flat slab otherwise) with ``assert_closure=False`` so a flight that
    missed the line comes back measured rather than as an exception:
    ``flown`` ``{t_s, north_m, east_m, alt_m, agl_m, heading_deg,
    pitch_deg, roll_deg}`` per sample, ``min_clearance_m`` the minimum
    over the span stations, ``max_cross_track_m``, ``closure`` the run's
    checks, ``violations`` (``route.terrain_clearance`` below
    ``ROUTE_MIN_CLEARANCE_M``, ``route.closure`` outside the declared
    tolerance), ``ok`` and ``seconds`` flown. The spec on the page is
    not touched: the page writes the route itself when the user presses
    "Use this path"."""
    if not isinstance(spec, ScenarioSpec):
        spec = ScenarioSpec.from_dict(spec)
    payload = _preflight(spec, waypoints, bank_limit_deg, heading_to_first_leg=True)
    payload.pop("schedule", None)
    payload.pop("card", None)
    return payload


def plan_route_flight(spec: ScenarioSpec, *, restore_autopilot: bool = False
                      ) -> Optional[Dict[str, Any]]:
    """The ``/run`` planner for a stated route: None without a route or
    when the flight is clear, else the violation dict (the verdict shows
    it by name, exactly as ``plan_terrain_flight``'s). The flight is
    :func:`check_route`'s on the spec as it stands (the page already
    wrote the heading), then the control schedule, the open-loop replay
    and its divergence; the result is left on the spec object as
    ``ROUTE_FLIGHT_ATTR`` for ``_render_flow`` (see the attribute's
    note). A copy that the validator refuses returns None and leaves no
    result: ``validate`` names the problem in the same request. A
    user-stated altitude is never moved: a route into the ground is a
    refusal, not a climb."""
    if Route.from_spec(spec) is None:
        return None
    flight = _preflight(spec, restore_autopilot=restore_autopilot, replay=True)
    if flight["stage"] == "validation":
        return None
    if not flight["ok"]:
        return flight["violations"][0]
    setattr(spec, ROUTE_FLIGHT_ATTR, flight)
    return None


def route_flight_for(spec: ScenarioSpec) -> Optional[Dict[str, Any]]:
    """What ``_render_flow`` reads: None without a route; the result
    :func:`plan_route_flight` left on this spec object when its route is
    the one flown (the digest says); otherwise the pre-flight flown now,
    on a copy with the autopilot restored (the spec has been projected
    for the host by then), refused by name through ``RouteError`` when
    the line cannot be flown -- a validation problem, the clearance or
    the closure -- so the run fails by name rather than rendering a
    route nobody flew."""
    route = Route.from_spec(spec)
    if route is None:
        return None
    stash = getattr(spec, ROUTE_FLIGHT_ATTR, None)
    if stash is not None and stash.get("digest") == route.digest():
        return stash
    flight = _preflight(spec, restore_autopilot=True, replay=True)
    if not flight["ok"]:
        problem = flight["violations"][0]
        raise RouteError(problem["constraint"], problem["message"], actual=problem.get("actual"),
                         limit=problem.get("limit"), unit=problem.get("unit"))
    setattr(spec, ROUTE_FLIGHT_ATTR, flight)
    return flight


def route_conditions_note(flight: Dict[str, Any]) -> str:
    """The conditions strip's line for a route run: what steers the
    render and how far the replay strayed, measured."""
    card = flight["card"]
    points = len(card["waypoints"])
    divergence = flight.get("replay_divergence_m")
    return (f"route: {points} waypoint{'s' if points != 1 else ''}, flown closed loop "
            f"headlessly (min clearance {flight['min_clearance_m']:.0f} m, worst "
            f"cross-track {flight['max_cross_track_m']:.0f} m); the render steers "
            f"OPEN LOOP from the autopilot's control schedule "
            f"({len(flight['schedule'])} entries at {SCHEDULE_HZ:g} Hz), replay "
            f"divergence "
            + ("not measured" if divergence is None
               else f"{divergence:.0f} m over {flight['replay_seconds']:g} s"))
