"""The route (docs/ROUTE.md), the core half: the ``route`` block, the
route's own checks, the geometry, the guidance, the run and the card.

What is measured here: the block is absent-canonical (a spec that states
none keeps its digest and reads back with a default block added), a
stated route moves the digest and is a version-9 key, the table
summarises the list, every ``route.*`` name refuses with its numbers,
the TECS limits the module pins are the XML's, the guidance is pure and
deterministic on a scripted state sequence, a real JSBSim flight of the
c172p around a 90-degree route closes within RouteTolerance with the
route columns recorded, and the same spec without the block flies
straight with no route column. What is NOT measured: terrain (the web
app's pre-flight) and the render host's open-loop replay (the web part
measures that divergence).

The real flight is the c172p at 1500 m / 100 kt, not the A-4: at the
A-4's 406 kt true the bank-limit radius is 9.6 km, so no 90-degree
route fits a 60 s run; the c172p's 670 m radius does. Measured here
(2026-10-09): 60 s in about 5 s wall, cross-track 40 m worst on an
1100 m arc, bank 20 degrees peak under the 25 limit.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from core.control.route import (
    BANK_LIMIT_DEFAULT_DEG, CARD_KEYS, COMMAND_COLUMNS, HDOT_MAX_MPS, LOOKAHEAD_S,
    MIN_LOOKAHEAD_M, RECORDER_COLUMNS, ROUTE_MIN_CLEARANCE_M, SCHEDULE_KEYS,
    TURN_RADIUS_SLACK, Route, RouteError, RouteGuidance, RouteTolerance, control_schedule,
    route_card_block, route_closure, route_problems, tas_kt_for_spec, tas_kt_isa,
    terrain_clearance_problem, turn_radius_m,
)
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.scenario.blocks import RouteSpec
from core.scenario.card import write_run_card
from core.scenario.runner import run_spec
from core.scenario.spec import SPEC9_BLOCKS, ScenarioSpec, spec9_keys_in
from core.scenario.validate import validate

REPO = Path(__file__).resolve().parents[1]
TECS = REPO / "core/control/systems/tecs.xml"

PROMPT = "fly the c172p at 1500 m and 100 kt for 60 seconds"
ALT = 1500.0


def plain_spec() -> ScenarioSpec:
    return compile_prompt(PROMPT)


def point(east, north, alt=ALT):
    return {"east_m": float(east), "north_m": float(north), "alt_m": float(alt)}


def corner_route():
    """Two legs of 1.5 km meeting at a sharp 90-degree corner."""
    return [point(0, 1500), point(1500, 1500)]


def arc_route(leg1_m=600.0, radius_m=1100.0, leg2_m=300.0, n_arc=12):
    """North for leg1, a right-hand quarter circle of radius_m, east for
    leg2: 2627 m at the defaults, flyable at the c172p's bank limit."""
    points = [point(0.0, leg1_m)]
    cx, cy = radius_m, leg1_m
    for k in range(1, n_arc + 1):
        a = math.pi * 0.5 * k / n_arc
        points.append(point(cx - radius_m * math.cos(a), cy + radius_m * math.sin(a)))
    points.append(point(cx + leg2_m, cy + radius_m))
    return points


def route_spec(points=None) -> ScenarioSpec:
    spec = plain_spec()
    spec.set("route.waypoints", points if points is not None else arc_route(),
             frm="drawn on the route map")
    return spec


def names(spec):
    return [v.constraint for v in validate(spec, check_feasibility=False).violations]


# -- the block ----------------------------------------------------------------------

def test_an_unstated_block_is_absent_and_changes_no_digest():
    spec = plain_spec()
    assert spec.route.is_default()
    assert "route" not in spec.to_dict()
    data = spec.to_dict()
    data["route"] = RouteSpec.defaulted().to_dict()
    assert ScenarioSpec.from_dict(data).digest() == spec.digest()
    assert Route.from_spec(spec) is None
    assert names(spec) == []


def test_a_stated_route_round_trips_moves_the_digest_and_is_a_version_9_key():
    spec = plain_spec()
    before = spec.digest()
    spec.set("route.waypoints", corner_route(), frm="drawn on the route map")
    data = spec.to_dict()
    assert data["route"]["waypoints"]["value"] == corner_route()
    assert data["route"]["waypoints"]["unit"] == "points"
    assert data["route"]["bank_limit_deg"]["value"] == BANK_LIMIT_DEFAULT_DEG
    assert "route" in SPEC9_BLOCKS and spec9_keys_in(data) == ["route"]
    again = ScenarioSpec.from_dict(data)
    assert str(again.route.waypoints.source) == "user"
    assert again.digest() == spec.digest() != before
    # The table summarises the list the way camera moves are summarised.
    table = spec.render_table()
    assert "2 points, 3.0 km" in table and "[route]" in table
    assert "1500.0" not in table.split("[route]")[1]
    # A version-8 dict carrying the block is refused by name.
    data["spec_version"] = 8
    with pytest.raises(ValueError, match="version-9 block\\(s\\) route"):
        ScenarioSpec.from_dict(data)


def test_the_block_follows_the_edit_doctrine_and_refuses_unknown_fields():
    spec = plain_spec()
    spec.plan("route.bank_limit_deg", 30.0, frm="a planner")
    assert str(spec.route.bank_limit_deg.source) == "derived"
    spec.set("route.bank_limit_deg", 20.0)
    with pytest.raises(ValueError, match="stated value is never silently moved"):
        spec.plan("route.bank_limit_deg", 30.0, frm="a planner")
    with pytest.raises(ValueError, match="not a route field"):
        spec.set("route.lookahead_m", 1.0)
    data = spec.to_dict()
    data["route"]["speed_kt"] = {"value": 1, "source": "user"}
    with pytest.raises(ValueError, match="route carries unknown fields"):
        ScenarioSpec.from_dict(data)


def test_a_route_without_the_autopilot_refuses_route_hold_state():
    spec = route_spec()
    assert names(spec) == []
    spec.set("hold_state", False)
    assert names(spec) == ["route.hold_state"]
    # The runner says it by name too, validator or no validator.
    with pytest.raises(RouteError) as err:
        run_spec(spec, validate_first=False)
    assert err.value.constraint == "route.hold_state"


# -- route_problems, every name -----------------------------------------------------

def test_a_sharp_corner_refuses_route_turn_with_the_radius_numbers():
    spec = route_spec(corner_route())
    violations = validate(spec, check_feasibility=False).violations
    assert [v.constraint for v in violations] == ["route.turn"]
    v = violations[0]
    radius = turn_radius_m(tas_kt_for_spec(spec), BANK_LIMIT_DEFAULT_DEG)
    assert v.limit == pytest.approx(TURN_RADIUS_SLACK * radius)
    assert v.unit == "m" and 0.0 < v.actual < v.limit
    # A 90-degree corner seen over a window of one radius: R / (pi/2).
    assert v.actual == pytest.approx(radius / (math.pi / 2), rel=0.05)
    assert f"{radius:.0f} m turn radius" in v.message
    # The arc of 1100 m, wider than the limit, passes.
    assert names(route_spec()) == []


def test_a_gentle_corner_and_the_start_are_not_bends():
    tas = tas_kt_isa(100.0, ALT)
    # 30 degrees over one radius is a 1.9-radius bend: flyable.
    gentle = [point(0, 1000), point(500, 1866)]
    assert route_problems(gentle, 25.0, tas_kt=tas, duration_s=60.0, altitude0_m=ALT) == []
    # The first leg may head anywhere: the aircraft starts pointed along it.
    sideways = [point(-1500, 0)]
    assert route_problems(sideways, 25.0, tas_kt=tas, duration_s=60.0,
                          altitude0_m=ALT) == []


def test_every_other_name_refuses_with_its_numbers():
    tas = tas_kt_isa(100.0, ALT)

    def only(points, bank=25.0, duration=60.0):
        found = route_problems(points, bank, tas_kt=tas, duration_s=duration, altitude0_m=ALT)
        assert len(found) == 1, found
        return found[0]

    too_long = only([point(0, 9000)])
    assert too_long["constraint"] == "route.time" and too_long["unit"] == "s"
    assert too_long["actual"] == pytest.approx(9000.0 / (u.kt_to_mps(tas)))
    assert too_long["limit"] == 60.0

    climb = only([point(0, 500, ALT + 200)])
    assert climb["constraint"] == "route.climb" and climb["unit"] == "m/s"
    assert climb["actual"] == pytest.approx(200.0 / (500.0 / (u.kt_to_mps(tas))))
    assert climb["limit"] == HDOT_MAX_MPS

    for bank in (70, 5.0, 0, "steep", None):
        bad = only([point(0, 500)], bank=bank)
        assert bad["constraint"] == "route.bank_limit" and bad["limit"] == 60.0
    assert route_problems([point(0, 500)], 60.0, tas_kt=tas, duration_s=60.0,
                          altitude0_m=ALT) == []

    for shape in ("not a list", [], [point(0, 0)], [{"east_m": 0.0, "north_m": 10.0}],
                  [point(0, 10), point(0, 10.5)], [point(float("nan"), 10)],
                  [{"east_m": 0.0, "north_m": 10.0, "alt_m": True}],
                  [{"east_m": 0, "north_m": 10, "alt_m": 1, "x": 2}],
                  [(0.0, 10.0, 1.0)]):
        assert only(shape)["constraint"] == "route.shape", shape
    many = [point(i, 10.0 * (i + 1)) for i in range(401)]
    assert only(many)["actual"] == 401 and only(many)["limit"] == 400
    # A shape problem is the only one reported: nothing is measured on a
    # line that cannot be read.
    assert len(route_problems([point(0, 0)], 70, tas_kt=tas, duration_s=1.0,
                              altitude0_m=ALT)) == 1


def test_the_terrain_clearance_refusal_has_one_source():
    assert terrain_clearance_problem(ROUTE_MIN_CLEARANCE_M) is None
    problem = terrain_clearance_problem(120.0)
    assert problem["constraint"] == "route.terrain_clearance"
    assert problem["actual"] == 120.0 and problem["limit"] == ROUTE_MIN_CLEARANCE_M


# -- the constants are the controller's ------------------------------------------------

def test_the_limits_are_pinned_to_tecs_xml():
    text = TECS.read_text(encoding="utf-8")
    bank_rad = float(re.search(r'<property value="([0-9.]+)">ap/limits/bank-rad</property>',
                               text).group(1))
    hdot_fps = float(re.search(r'<property value="([0-9.]+)">ap/tecs/hdot-max-fps</property>',
                               text).group(1))
    assert math.degrees(bank_rad) == pytest.approx(BANK_LIMIT_DEFAULT_DEG, abs=0.01)
    assert hdot_fps * 0.3048 == pytest.approx(HDOT_MAX_MPS, abs=1e-9)
    assert RouteSpec.defaulted().bank_limit_deg.value == BANK_LIMIT_DEFAULT_DEG


def test_tas_and_turn_radius_are_the_documented_formulas():
    assert tas_kt_isa(100.0, 0.0) == 100.0
    assert tas_kt_isa(100.0, ALT) == pytest.approx(107.6, abs=0.1)
    assert tas_kt_isa(350.0, 3000.0) == pytest.approx(406.3, abs=0.5)
    assert tas_kt_isa(250.0, 12000.0) > tas_kt_isa(250.0, 11000.0)
    v = u.kt_to_mps(107.6)
    assert turn_radius_m(107.6, 25.0) == pytest.approx(v * v / (9.80665 * math.tan(math.radians(25))))
    spec = plain_spec()
    assert tas_kt_for_spec(spec) == pytest.approx(tas_kt_isa(100.0, ALT))
    spec.set("airspeed_kind", "tas")
    assert tas_kt_for_spec(spec) == 100.0


# -- geometry -----------------------------------------------------------------------

def test_route_geometry():
    tas = tas_kt_isa(100.0, ALT)
    r = Route([point(0, 1000), point(1000, 1000, ALT + 100)], ALT, tas_kt=tas)
    assert r.points[0] == (0.0, 0.0, ALT) and r.legs == 2
    assert r.length_m == 2000.0 and r.cum_m == [0.0, 1000.0, 2000.0]
    assert r.initial_heading_deg == 0.0 and r.leg_heading_deg(1) == 90.0
    assert r.lookahead_m == pytest.approx(max(MIN_LOOKAHEAD_M, LOOKAHEAD_S * u.kt_to_mps(tas)))
    assert r.altitude_at(500) == ALT and r.altitude_at(1500) == ALT + 50
    assert r.altitude_at(-10) == ALT and r.altitude_at(5000) == ALT + 100
    assert r.point_at(1500) == (500.0, 1000.0, ALT + 50)
    # Beyond the ends the end legs continue; the profile holds.
    assert r.point_at(2500) == (1500.0, 1000.0, ALT + 100)
    assert r.point_at(-100) == (0.0, -100.0, ALT)
    # Cross-track is signed, positive to the right of travel.
    assert r.project(50.0, 500.0) == (500.0, 50.0)
    assert r.project(500.0, 1020.0) == (1500.0, -20.0)
    assert r.project(1200.0, 1010.0) == (2000.0, -10.0)
    assert r.project(0.0, -50.0) == (0.0, 0.0)
    assert r.digest() == Route([point(0, 1000), point(1000, 1000, ALT + 100)], ALT,
                               tas_kt=tas).digest()
    assert r.digest() != Route([point(0, 1000), point(1000, 1000)], ALT, tas_kt=tas).digest()
    assert r.waypoint_dicts() == [point(0, 1000), point(1000, 1000, ALT + 100)]
    assert r.point_dicts()[0] == point(0, 0)
    with pytest.raises(RouteError) as err:
        Route([point(0, 0)], ALT, tas_kt=tas)
    assert err.value.constraint == "route.shape"


# -- the guidance, pure ----------------------------------------------------------------

class FlatFrame:
    """A frame whose latitude is north metres and longitude east metres."""

    def north_east(self, latitude_deg, longitude_deg):
        return float(latitude_deg), float(longitude_deg)


class RecordingAutopilot:
    def __init__(self):
        self.commands = []

    def command(self, **setpoints):
        self.commands.append(setpoints)


class At:
    def __init__(self, north, east):
        self.lat_deg, self.lon_deg = north, east


def test_guidance_is_pure_pursuit_on_the_projected_point():
    r = Route([point(0, 1000), point(1000, 1000, ALT + 100)], ALT, tas_kt=100.0)
    autopilot = RecordingAutopilot()
    g = RouteGuidance(r, FlatFrame(), autopilot, tas_mps=50.0)
    L = g.lookahead_m
    assert L == 200.0
    assert g.last["heading_setpoint_deg"] == 0.0 and g.last["d_m"] == 0.0
    # On the line, the heading is the leg's and the altitude the profile's L ahead.
    g.update(At(500.0, 0.0))
    assert autopilot.commands[-1] == {"heading_deg": 0.0, "altitude_m": ALT}
    assert g.last == {"d_m": 500.0, "cross_track_m": 0.0, "heading_setpoint_deg": 0.0,
                      "altitude_setpoint_m": ALT, "leg": 0}
    # Right of the line: the setpoint pulls left, by about atan(xte / L).
    g.update(At(500.0, 30.0))
    heading = autopilot.commands[-1]["heading_deg"]
    assert heading == pytest.approx(360.0 - math.degrees(math.atan2(30.0, L)))
    assert g.last["cross_track_m"] == 30.0
    # Near the corner the target is already on the second leg, climbing.
    g.update(At(900.0, 0.0))
    assert 0.0 < autopilot.commands[-1]["heading_deg"] < 90.0
    assert autopilot.commands[-1]["altitude_m"] == r.altitude_at(900.0 + L)
    assert g.last["leg"] == 0
    # Past the end: the last leg's heading is held, the profile's end altitude too.
    g.update(At(1000.0, 1300.0))
    assert autopilot.commands[-1] == {"heading_deg": 90.0, "altitude_m": ALT + 100}
    assert g.last["d_m"] == r.length_m and g.last["leg"] == 1
    # Deterministic: the same state commands the same setpoints.
    before = list(autopilot.commands)
    g.update(At(500.0, 30.0))
    assert autopilot.commands[-1] == before[1]


def test_route_closure_measures_every_sample():
    r = Route([point(0, 1000)], ALT, tas_kt=100.0)
    checks = route_closure(r, FlatFrame(), [0.0, 500.0, 900.0], [0.0, 20.0, -40.0],
                           [ALT, ALT + 5, ALT - 12], RouteTolerance(), lookahead_m=120.0)
    by_name = {c.name: c for c in checks}
    assert by_name["cross_track_max"].achieved == 40.0 and by_name["cross_track_max"].ok
    assert by_name["route_altitude"].achieved == 12.0
    assert by_name["route_reached"].commanded == 1000.0
    assert by_name["route_reached"].achieved == 900.0 and by_name["route_reached"].ok
    assert by_name["route_reached"].tolerance == 120.0
    short = route_closure(r, FlatFrame(), [0.0, 500.0], [0.0, 0.0], [ALT, ALT],
                          RouteTolerance(), lookahead_m=120.0)
    assert not [c for c in short if c.name == "route_reached"][0].ok
    wide = route_closure(r, FlatFrame(), [500.0], [80.0], [ALT], RouteTolerance(),
                         lookahead_m=120.0)
    assert not [c for c in wide if c.name == "cross_track_max"][0].ok


# -- the run -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def flown():
    spec = route_spec()
    return spec, run_spec(spec)


@pytest.fixture(scope="module")
def straight():
    spec = plain_spec()
    return spec, run_spec(spec)


def test_the_c172p_flies_a_90_degree_route_within_tolerance(flown):
    spec, result = flown
    route = Route.from_spec(spec)
    assert result.closure.ok
    checks = {c.name: c for c in result.closure.checks}
    assert set(checks) == {"airspeed", "cross_track_max", "route_altitude", "route_reached"}
    tolerance = RouteTolerance()
    assert checks["cross_track_max"].achieved <= 0.8 * tolerance.cross_track_m
    assert checks["route_altitude"].achieved <= 0.5 * tolerance.altitude_m
    assert checks["route_reached"].achieved == pytest.approx(route.length_m, abs=1.0)
    columns = result.telemetry.columns
    for name in RECORDER_COLUMNS + tuple(COMMAND_COLUMNS):
        assert name in columns and len(columns[name]) == len(columns["t"])
    assert max(columns["route_d_m"]) == pytest.approx(route.length_m, abs=1.0)
    # The column is the guidance's number, held between its 2 Hz ticks; the
    # closure projects every 10 Hz sample, so the two agree to the drift
    # within half a tick (measured 3 cm), not bit for bit.
    assert max(abs(v) for v in columns["route_cross_track_m"]) == \
        pytest.approx(checks["cross_track_max"].achieved, abs=1.0)
    # The turn was flown inside the bank limit, and the aircraft ends on the
    # east leg (grid east; the UTM convergence at the origin is under a degree).
    assert max(abs(v) for v in columns["roll_deg"]) <= BANK_LIMIT_DEFAULT_DEG + 0.5
    assert abs((columns["heading_deg"][-1] - 90.0 + 180.0) % 360.0 - 180.0) < 5.0
    block = result.manifest["route"]
    assert set(block) == {"digest", "points", "length_m", "bank_limit_deg", "lookahead_m",
                          "closure", "trims"}
    assert block["digest"] == route.digest() and block["points"][0] == point(0, 0)
    assert block["lookahead_m"] == route.lookahead_m
    assert [c["name"] for c in block["closure"]] == list(checks)
    assert set(block["trims"]) == {"aileron", "elevator", "rudder"}
    assert result.manifest["control"]["gains"]["ap/limits/bank-rad"] == \
        pytest.approx(math.radians(BANK_LIMIT_DEFAULT_DEG))


def test_the_same_spec_without_the_block_flies_straight(flown, straight):
    spec, result = straight
    columns = result.telemetry.columns
    assert not any(name in columns for name in RECORDER_COLUMNS + tuple(COMMAND_COLUMNS))
    assert "route" not in result.manifest
    assert {c.name for c in result.closure.checks} == {"altitude", "airspeed", "heading",
                                                       "settled"}
    first, last = columns["heading_deg"][0], columns["heading_deg"][-1]
    assert abs((last - first + 180.0) % 360.0 - 180.0) < 3.0
    assert result.output_digest != flown[1].output_digest
    assert spec.digest() != flown[0].digest()


def test_the_control_schedule_and_the_card_block(flown, tmp_path):
    spec, result = flown
    route = Route.from_spec(spec)
    trims = result.manifest["route"]["trims"]
    schedule = control_schedule(result.telemetry.columns, trims, hz=10.0)
    assert len(schedule) == 601
    assert [e["t_s"] for e in schedule[:3]] == [0.0, 0.1, 0.2]
    assert schedule[-1]["t_s"] == pytest.approx(60.0)
    assert all(tuple(e) == SCHEDULE_KEYS for e in schedule)
    # The first entry is the trim itself: a zero delta on every surface.
    assert all(abs(schedule[0][k]) < 1e-9 for k in ("aileron", "elevator", "rudder"))
    # The turn moved the aileron.
    assert max(abs(e["aileron"]) for e in schedule) > 0.01
    coarse = control_schedule(result.telemetry.columns, trims, hz=2.0)
    assert len(coarse) == 121 and coarse[1]["t_s"] == 0.5

    block = route_card_block(route, schedule=schedule, divergence_m=3.5)
    assert tuple(block) == CARD_KEYS
    assert block["waypoints"] == arc_route() and block["digest"] == route.digest()
    assert block["bank_limit_deg"] == BANK_LIMIT_DEFAULT_DEG
    assert block["lookahead_m"] == route.lookahead_m
    assert block["flown"] is None and block["replay_divergence_m"] == 3.5
    with pytest.raises(RouteError) as err:
        route_card_block(route, schedule=[{"t_s": 1.0, "aileron": 0, "elevator": 0,
                                           "rudder": 0}, {"t_s": 0.5, "aileron": 0,
                                                          "elevator": 0, "rudder": 0}])
    assert err.value.constraint == "route.shape"

    path = write_run_card(spec, tmp_path / "card.json", control_inputs=schedule,
                          traffic=[{"aircraft": "c172p"}], route=block)
    card = json.loads(path.read_text(encoding="utf-8"))
    assert card["route"] == json.loads(json.dumps(block))
    keys = list(card)
    assert keys.index("route") == keys.index("traffic") + 1
    assert card["control_inputs"][0]["t_s"] == 0.0
    bare = json.loads(write_run_card(spec, tmp_path / "bare.json").read_text(encoding="utf-8"))
    assert "route" not in bare


# -- the prompt words ---------------------------------------------------------------

@pytest.mark.parametrize("prompt, word", [
    ("fly to the ridge in the c172p at 1500 m", "fly to"),
    ("c172p through three waypoints at 1500 m", "waypoints"),
    ("the c172p following the valley at 1500 m", "following the valley"),
    ("c172p around the peak at 1500 m", "around the peak"),
    ("c172p in a circle at 1500 m for 60 seconds", "circle"),
])
def test_route_words_point_at_the_route_map(prompt, word):
    spec = compile_prompt(prompt)
    not_set = [v for v in validate(spec, check_feasibility=False).violations
               if v.constraint == "prompt.not_set"]
    assert len(not_set) == 1
    assert str(not_set[0].actual).startswith(word)
    assert "route map" in not_set[0].message and "language model" not in not_set[0].message
    # A drawn route honours the words.
    spec.set("route.waypoints", arc_route(), frm="drawn on the route map")
    assert "prompt.not_set" not in names(spec)


def test_the_camera_orbit_is_not_a_route_word():
    from core.nl.unsupported import CARRIED

    spec = compile_prompt("orbit the 747 from the chase camera for 20 seconds")
    assert "prompt.not_set" not in names(spec)
    assert [row[1] for row in CARRIED].count("a flight path") == 1
