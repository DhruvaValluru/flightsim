# The route: a drawn flight path, flown by the autopilot

Status: designed 2026-10-09 on `phase-2-testing`. This page is the contract
every part of the feature is built against; the measured results are
appended at the end once the parts exist.

## What the user sees

1. Interpret a prompt as today. The review table fills in.
2. Press **Draw the flight path**. A map of the ground around the start
   point opens in the page, north up, scaled so that the circle of
   everything the aircraft can reach in the run (true airspeed x the run's
   seconds) fits the view. The ground is the SAME raster the physics
   flies (`pick_scene`), drawn as a hill-shaded relief with contour
   bands; a flat scene draws a flat slab and says so.
3. Draw the path with the pen from the aircraft, or click straight legs.
   Four checks update as the line is drawn, each with the sentence first
   and the rule name underneath, exactly like the review table:
   * **fits the time** -- the line's length against true airspeed x
     seconds;
   * **turns flyable** -- no bend tighter than the turn radius at the
     autopilot's bank limit (`V_true^2 / (g tan 25 deg)`);
   * **clear of the ground** -- the line, flown at its altitude, stays at
     least `ROUTE_MIN_CLEARANCE_M` (150 m) above the raster, measured on
     the map's grid;
   * **climbs feasible** -- altitude changes between points stay within
     the autopilot's climb-rate demand limit (12.19 m/s, `hdot-max-fps`
     40 in `core/control/systems/tecs.xml`): this is the autopilot's own
     bound, not a measured airframe climb figure, and the page says so.
4. **Self adjust** moves the line as little as needed until every check
   passes (the mockup's algorithm, in the browser): cut where the run ends,
   replace the line by the track a bank-limited plane flies along it,
   push stretches that are too low sideways to the side away from the high
   ground and fly again, and only then raise altitude. The drawn line
   stays on the map dotted; the card lists every change in words.
5. **Check with the physics** sends the line to the server, which flies it
   for real -- JSBSim, the TECS autopilot, the route guidance below, over
   the scene's full raster with the stated wind -- and sends back the
   flown track, the minimum ground clearance over the span stations, the
   cross-track error and the closure report. The flown track is drawn
   over the line; a refusal is shown by name.
6. **Use this path** writes the route into the review table as user-stated
   fields (`route.waypoints`, `route.bank_limit_deg`), provenance "drawn
   on the route map" (or "... then self-adjusted"), and sets the initial
   heading to the first leg's bearing (also user-stated, so no planner
   moves it). Run proceeds as today.

## What is claimed, and what is not

* The physics run (`run_spec`, every machine) flies the route with the
  autopilot already in the stack. Its closure assertion is route-aware:
  a run that strays more than the declared cross-track tolerance, or
  misses the route's altitude profile, produces no output.
* The render (Windows, the UE host) has no autopilot and refuses one by
  name. A route run renders from a **control schedule**: the aileron,
  elevator and rudder the autopilot commanded in the headless route
  flight, sampled at 10 Hz as deltas on trim and carried as the card's
  `control_inputs`, the host's one steering input, held between entries
  as the host holds them. This is open loop: the clip follows the route
  as well as two JSBSim builds replaying the same inputs agree. The
  divergence is MEASURED, not assumed: the same schedule is re-flown
  open loop headlessly (`_fly_clearance_track`'s stock FDM) and the
  worst distance between the open-loop and closed-loop tracks is on the
  run card and in the run report as `route.replay_divergence_m`. A
  closed-loop render needs the guidance ported to the host (NEXT.md).
* Turn radius and climb limits shown on the map come from the autopilot's
  own limits (`tecs.xml`), served by the server, never typed into the
  page. No airframe climb performance is measured anywhere in this
  system; the climb check is honest about being the demand clip.
* True airspeed is the ISA conversion of the spec's calibrated airspeed
  at the spec altitude (`core/control/route.py: tas_kt_isa`); the run's
  own TAS is what the recorder shows.
* The map's grid (129 x 129 over the reach window) is for drawing and the
  quick checks; the server check and the run use the full raster. The
  map says "measured on the map's grid" and the server check says
  "measured on the raster", and the two can disagree near a ridge.

## The spec block: `route` (spec 9, optional, absent-canonical)

`core/scenario/blocks.py: class RouteSpec(ProvenancedBlock)`, after
`LightingSpec`. `BLOCK = "route"`, `FIELD_ORDER = ("waypoints",
"bank_limit_deg")`.

* `waypoints`: ONE `Quantity` whose value is a list of mappings
  `{"east_m": float, "north_m": float, "alt_m": float}` in the scene frame
  (metres east and north of the spec origin, `SceneFrame.for_spec`;
  altitude metres MSL). The first mapping is the start of the flown line
  AFTER the start point: the aircraft begins at (0, 0, spec altitude)
  heading along the first leg; the list never repeats (0, 0). Unit
  `"points"`. Default `Quantity.default([], frm="no route drawn: the
  initial heading is held")`.
* `bank_limit_deg`: the autopilot's bank limit for this run. Default
  `Quantity.default(25.0, unit="deg", frm="the autopilot's bank limit
  (tecs.xml ap/limits/bank-rad)")`. Range (5, 60].

`is_default()` is the base rule: an unstated block is absent from
`to_dict()`, so every existing digest is unchanged; a stated block moves
the digest. `spec.set("route.waypoints", [...])` and `spec.plan(...)`
reach it through `_block_address`. `render_table` summarises the list as
"N points, L km" the way camera moves are summarised, never the whole
list. `spec.py` wiring exactly as `lighting`: import, `SPEC9_BLOCKS`,
the dataclass field with `default_factory=RouteSpec.defaulted`, the
regex, `to_dict`/`from_dict`, `render_table`. No `SPEC_VERSION` bump
(rain and lighting set the precedent). No registry entry (the section
stays unclaimed). No NL compiler fills it; `core/nl/unsupported.py`
gets a CARRIED row so "fly to", "waypoint", "follow the valley" words
tell the user to draw the path on the map.

## `core/control/route.py` (new) -- the one place that knows a route

Pure functions and small classes, no I/O, no wall clock, no RNG.

```
ROUTE_MIN_CLEARANCE_M = 150.0      # the route's own floor, between MIN_CLEARANCE_M (30) and PLANNED_CLEARANCE_M (300)
BANK_LIMIT_DEFAULT_DEG = 25.0      # tecs.xml ap/limits/bank-rad, read back and pinned by a test
HDOT_MAX_MPS = 12.192              # tecs.xml ap/tecs/hdot-max-fps 40, pinned by a test
LOOKAHEAD_S = 4.0                  # pure pursuit looks this many seconds of TAS ahead
MIN_LOOKAHEAD_M = 120.0
MAX_WAYPOINTS = 400
G_MPS2 = 9.80665

def tas_kt_isa(cas_kt, altitude_m) -> float            # ISA density ratio; documented approximation
def turn_radius_m(tas_kt, bank_deg) -> float
def route_problems(waypoints, bank_limit_deg, *, tas_kt, duration_s, altitude0_m) -> list[dict]
    # the validator's shape: {"constraint", "message", "actual", "limit", "unit"}; names:
    #   route.shape      (not a list / unknown keys / non-finite / fewer than 1 point / too many / repeats the origin)
    #   route.bank_limit (outside (5, 60])
    #   route.time       (length / TAS > duration_s)
    #   route.turn       (a bend tighter than 0.9 x turn radius at the bank limit, measured over a window of one radius, the plane arriving heading north of... no: heading along the first leg; the start is not a bend)
    #   route.climb      (|alt change| / leg time > HDOT_MAX_MPS, leg time >= 1 s)
    # terrain is NOT here (the validator is scene-free); see plan_route_flight.

class Route:                      # the polyline with cumulative distance and altitude profile
    @classmethod from_spec(spec) -> Optional[Route]      # None for the default block
    points: list[(east_m, north_m, alt_m)] including the origin (0, 0, spec altitude) first
    cum_m, length_m, initial_heading_deg (first leg's bearing)
    altitude_at(d_m), point_at(d_m), project(east_m, north_m) -> (d_m, cross_track_m signed)
    digest() -> sha256 of the point list (for the card and the manifest)

class RouteGuidance:              # setpoints only (autopilot.py's rule); runs at the harness's 2 Hz
    __init__(route, frame: LocalFrame, autopilot, tas_mps)
    update(state) -> None         # north/east from state.lat_deg/lon_deg via frame.north_east;
                                  # d = project(...); target = point_at(min(d + L, length)); heading = bearing to target
                                  # (past the end: hold the last leg's heading); altitude = altitude_at(d + L);
                                  # autopilot.command(heading_deg=..., altitude_m=...)
    last: dict                    # d_m, cross_track_m, heading_setpoint_deg, altitude_setpoint_m, leg (for the recorder)

class RouteTolerance: cross_track_m = 75.0; altitude_m = 30.0
def route_closure(route, frame, lat_deg[], lon_deg[], altitude_m[], tolerance) -> list[ClosureCheck]
    # ("cross_track_max", 0, max|xte| over the samples, tol, "m"), ("route_altitude", 0, max|alt - profile|, tol, "m"),
    # ("route_reached", route.length_m, max d reached, 0.1*length... no: tolerance = lookahead, "m")

def control_schedule(telemetry_samples, trims, hz=10.0) -> list[dict]
    # {"t_s", "aileron", "elevator", "rudder"}: the commanded fcs/*-cmd-norm minus the trim values captured at engage,
    # one entry per 1/hz, first at t=0; the card's control_inputs shape (increasing t_s; the host holds between entries).
def route_card_block(route, flown=None, schedule=None, divergence_m=None) -> dict
    # CARD_KEYS = ("waypoints", "digest", "bank_limit_deg", "lookahead_m", "flown", "replay_divergence_m")
    # flown = {"t_s","north_m","east_m","alt_m","yaw_deg","pitch_deg","roll_deg"} like traffic poses (host may ignore)
```

The turn check ports the mockup's `turnAnalysis`: heading change over a
window of about one turn radius, padded with the first leg's heading
before the start (the aircraft begins already pointed along the first
leg, because the spec heading is set to it).

## The run (`core/scenario/runner.py`)

In `run_spec`, after `autopilot.engage()`:

* `route = Route.from_spec(spec)`; when stated: `hold_state` must be true
  (refuse `route.hold_state` by name otherwise -- the validator says it
  too), `autopilot.tune(bank_limit_deg=...)`, build
  `RouteGuidance(route, scene_frame_for(spec, terrain_ground), autopilot,
  tas)`; recorder extras `route_d_m`, `route_cross_track_m`,
  `route_heading_setpoint_deg`, `route_altitude_setpoint_m` are added
  ONLY when a route is stated (digests of every other run unchanged);
* at the 2 Hz site, `guidance.update(fdm.state())` before
  `autopilot.update()`;
* closure: with a route, the heading and "settled" checks are replaced
  by `route_closure(...)`; altitude closure is the route one; the
  airspeed check stays. `ClosureError` as before: no output;
* manifest: `manifest["route"] = {"digest", "points", "length_m",
  "bank_limit_deg", "lookahead_m", "closure": [...]}`.

## The web app

`webapp/route_map.py` (new):

* `terrain_payload_for_route(spec, scene, seconds)` -- `camera_placer.
  terrain_payload` with the window sized by TAS x seconds (same 129
  grid, same caps) plus `route: {tas_kt, turn_radius_m, bank_limit_deg,
  hdot_max_mps, min_clearance_m, lookahead_m, seconds}` and any stated
  route from the spec. Seconds = `min(duration, CLIP_SECONDS)`, the
  same clock the placer uses, and the payload says so.
* `check_route(spec_dict, waypoints, bank_limit_deg)` -- parse, write the
  route into a COPY as user-stated, set the heading to the first leg,
  plan the copy the way `/run` will (`plan_scene_setting`,
  `plan_water_surface`, `place_on_scene`, `plan_terrain_environment`;
  never `project_for_ue_host`), validate (400 with the violations on a
  problem), then fly it with `run_spec(copy, terrain_ground=...)` over
  the scene raster (flat slab otherwise), `assert_closure=False`, and
  return `{flown: {t_s, north_m, east_m, alt_m, agl_m, heading_deg,
  roll_deg}, min_clearance_m, max_cross_track_m, closure: [...],
  violations: [...], ok, seconds}` where the clearance is the minimum
  over span stations (reuse `core.terrain.contact.station_offsets_ned`
  as `_fly_clearance_track` does) and `violations` carries
  `route.terrain_clearance` when below `ROUTE_MIN_CLEARANCE_M`.
* `plan_route_flight(spec) -> Optional[dict]` -- the `/run` planner for a
  stated route: the same flight as `check_route`, then the control
  schedule, the open-loop re-flight on a stock FDM (the
  `_fly_clearance_track` machinery with a full `{aileron, elevator,
  rudder}` script -- extend that function to apply all three, the way
  the host does: aileron set, elevator added to trim, rudder as given),
  the replay divergence, and the card block stashed on the spec's notes
  or returned for `_render_flow`. A clearance below the floor or a
  failed closure is the violation returned (the verdict shows it by
  name). A user-stated altitude is never moved.

`webapp/server.py`:

* `POST /route/terrain {spec}` -> the payload above (400 on a parse
  error, 409 on `PlacementError`).
* `POST /route/check {spec, waypoints, bank_limit_deg}` -> `check_route`.
* `GET /route_map.js` -> the static module (explicit route, like
  `/camera3d.js`).
* `_spec_payload`: `dict["route"]` always present (the lighting rule) and
  a summary row "route.waypoints" so the table shows "N points, L km";
  the page edits the block through the map, not the row.
* `/run`: `plan_route_flight` runs after `plan_terrain_environment` and
  before `derive_seed` / `plan_terrain_flight`; with a route stated,
  `plan_terrain_flight` is skipped (the route pre-flight is the terrain
  check) and `_render_flow` carries the route's control schedule as
  `control_inputs` instead of `SHOWCASE_DOUBLET`, the card's `route`
  block beside it.

`webapp/static/route_map.js` (new, `window.RouteMap.open({container,
getSpec, onPlaced})` like `CameraPlacer`): the mockup's engine
(`flight-path-tracer.html`'s CORE: resample, turn analysis, the
autopilot stand-in sim, self adjust) with the illustrative terrain
replaced by the server grid (bilinear, the placer's `Terrain` rule) and
every limit taken from the payload. Dark theme, the page's monospace
font and `.card/.opt/.dim` classes. The post-run chart (`initFlightPath`)
draws the planned route dotted under the flown track, read from
`card.json`'s `route.waypoints`, converted to its own flat-earth metres
from the card's origin.

## Tests

* `tests/test_route_core.py`: the block (absent-canonical, digest moves
  when stated, `SPEC9_BLOCKS`, `spec9_keys_in`, render_table summary,
  refusals by name); `route_problems` for every name; `Route` geometry;
  `RouteGuidance` on a scripted state sequence (pure); the TECS
  constants pinned to `tecs.xml`; a real JSBSim flight (`run_spec`, flat
  scene, c172p, a 90 degree route) whose closure passes within
  `RouteTolerance`, with a null test: the same spec without the block
  flies straight; `control_schedule` and the card block keys.
* `tests/test_route_map.py`: `/route/terrain` on a flat spec and on a
  synthetic `Heightfield` (grid equality, the payload's limits match the
  Python constants); `/route/check` returns a flown track and refuses a
  route into the synthetic hill by name; `/run` with a route calls
  `plan_route_flight` in the pinned order (monkeypatched `ue_available`)
  and carries the schedule; the page includes the script and the server
  serves it; JS constants mirrored from Python are pinned by regex
  (`lens_picker` precedent).
* `core/messages/catalog.yaml` entries for every `route.*` name, enforced
  by `tests/test_messages.py`.

## Ownership while building (no two agents touch one file)

* A -- core: `core/control/route.py`, `core/scenario/blocks.py`,
  `spec.py`, `validate.py`, `runner.py`, `card.py` (the helper only),
  `core/messages/catalog.yaml`, `core/nl/unsupported.py`,
  `tests/test_route_core.py`.
* B -- web server: `webapp/route_map.py`, `webapp/server.py`,
  `webapp/runs.py`, `tests/test_route_map.py`.
* C -- page: `webapp/static/route_map.js`, `webapp/static/index.html`,
  `tests/test_route_page.py`.
* Docs (this file's results section, README, VALIDITY, NEXT) after the
  parts are measured.

## Built and measured (2026-10-09, this branch, JSBSim 1.2.4 on Linux)

Everything above the ownership list exists, with these deviations from
the contract, each for a measured reason:

* **Guidance past the end.** The target continues along the last leg's
  extension rather than clamping to the end point: clamping makes the
  bearing to a point the aircraft is about to pass swing through 180
  degrees in the last lookahead, which the heading hold turns into a
  wobble. `Route.point_at` extrapolates beyond either end; `project`
  still clamps the distance to the line.
* **`route.turn`'s numbers.** `actual` is the tightest implied radius and
  `limit` is the enforced floor, 0.9 x the radius at the bank limit, so
  `actual < limit` is exactly the refusal; the message names the full
  radius as well.
* **`route.closure`** (not in the first contract): the pre-flight's
  refusal when the autopilot cannot close on the drawn line. Measured
  reason it exists: two legs meeting at 45 degrees pass `route.turn` and
  still overshoot 117 m at the c172p's 670 m radius, past the 75 m
  tolerance.
* **The host's entry rule, mirrored exactly.** `_fly_clearance_track`
  applies a schedule entry as the host does (aileron set, elevator =
  latched trim + entry, rudder as given, held between entries) and takes
  a `clock` argument: the doublet keeps JSBSim's sim time, which the
  engine start has already advanced to 4.875 s when the loop begins; the
  route replay uses the run clock the render commandlet steps on.
* **A fix the feature needed.** `Autopilot.engage()` measured the
  control signs at the probe's default 6000 m / 280 kt, where the c172p
  cannot trim, so no Cessna had ever flown under `hold_state`. The probe
  now runs at the aircraft's own trimmed condition.

Measured: the c172p at 1500 m / 100 kt (107.6 kt true, 670 m radius at
25 degrees) flies a 2.6 km route -- 600 m north, a 1100 m quarter circle
to the right, 300 m east -- with 40 m worst cross-track (tolerance 75),
1.8 m of its profile (tolerance 30), the end reached, 20 degrees of
bank; the same spec without the block flies straight, no route columns,
and runs without a route are byte-identical to the previous runner for
the 747, the A-4 and a turbulent c172p (digest, columns, closure,
manifest keys). A 20 s flat c172p route: 42 m worst cross-track in the
pre-flight, 13.4 m replay divergence. A 30 s line over a 1400 m
synthetic hill at 1500 m: refused `route.terrain_clearance` at 100.5 m.
The page, driven in headless Chromium against the live server
(tests/test_route_page.py and a scripted run of the real app): the map
opens on the scene `pick_scene` names, the checks carry their rule
names, Self adjust cuts an over-long line to the run, Check with the
physics returns the flown track, Use this path writes the user-stated
block and heading, no console errors.


## The lookahead and short lines (2026-10-09)

Pure pursuit aims at the point one lookahead ahead on the line, and the
lookahead was four seconds of true airspeed: 450 m for a 747 at 220 kt.
On the line a ten-second run can fly (about 800 m) that aimed at the end
from the start, so a drawn bend was flown as a straight line to the flag
(the owner's map: "I draw a curve and it makes its own line"). The
lookahead is now capped to a quarter of the line's length, never under
`MIN_LOOKAHEAD_M` (`lookahead_m_for(tas_kt, length_m)`), on both sides:
`Route.lookahead_m` carries the capped number to the card, and the
browser's quick look applies the same cap (`lookaheadFor` in
`route_map.js`), so the grey line is what the physics steers.
