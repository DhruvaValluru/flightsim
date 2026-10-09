"""The route map's server half (docs/ROUTE.md "The web app"; webapp/route_map.py).

The page draws a line on the ground the physics flies and asks the
server to fly it for real. These tests pin the server part: the
terrain payload is the camera placer's grid windowed to the reach
circle with every limit served from core/control/route.py; the physics
check flies the line closed loop over the scene's raster and refuses a
line into a hill BY NAME; /run flies a stated route in the pinned
planner order and the card the render host reads carries the route's
control schedule and its block.

The flights are the c172p at 1500 m / 100 kt for 20-30 s (about 2.5 s
each here), over the datum slab or a synthetic hill built in memory the
way tests/test_camera_placer.py builds its raster -- never the network,
never a real bake.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import webapp.runs as runs_module
import webapp.server as server_module
from core.control.route import (
    BANK_LIMIT_DEFAULT_DEG,
    BANK_LIMIT_RANGE_DEG,
    CARD_KEYS,
    HDOT_MAX_MPS,
    ROUTE_MIN_CLEARANCE_M,
    SCHEDULE_KEYS,
    Route,
    RouteTolerance,
    lookahead_m_for,
    tas_kt_for_spec,
    turn_radius_m,
)
from core.nl.compiler import compile_prompt
from core.scenario.spec import ScenarioSpec
from webapp.runs import CLIP_SECONDS, RunManager
from webapp.server import app, manager

ALT = 1500.0
#: The hill's origin: a real place by coordinates (so a stated bake is
#: honoured) in UTM zone 32N, with nothing else about it used.
ORIGIN_LAT, ORIGIN_LON = 47.0, 8.0
#: The synthetic hill: a Gaussian 900 m north of the start, 1400 m high
#: over a 0 m datum, 300 m wide at one sigma. A line straight north at
#: 1500 m passes about 100 m over its top (below the 150 m floor); a
#: line that bends east passes beside it with over a kilometre to spare.
HILL_NORTH_M, HILL_SIGMA_M, HILL_PEAK_M = 900.0, 300.0, 1400.0
HILL_HALF_M, HILL_PIXEL_M = 3000.0, 30.0


def point(east, north, alt=ALT):
    return {"east_m": float(east), "north_m": float(north), "alt_m": float(alt)}


def flat_spec(duration_s=20):
    """A c172p pinned to the datum slab, whatever bakes this machine holds."""
    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {duration_s} seconds")
    spec.set("scene.terrain_source", "flat")
    return spec


def hill_spec(duration_s=30):
    """The same aircraft at the hill: stated coordinates on the stated
    bake, at a stated 0 m datum (scene-setting leaves stated fields)."""
    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {duration_s} seconds")
    spec.set("latitude", ORIGIN_LAT, frm="stated in test")
    spec.set("longitude", ORIGIN_LON, frm="stated in test")
    spec.set("terrain_elevation", 0.0, frm="stated in test")
    spec.set("scene.terrain_source", "baked")
    spec.set("scene.terrain", "hill")
    return spec


#: Straight north over the hill's top.
INTO_THE_HILL = [point(0.0, 1200.0)]
#: East, then a gentle curve to the north-east beside the hill: 1591 m
#: in four legs with 10-20 degree bends, inside 30 s of reach. (Two legs
#: meeting at 45 degrees overshoot 117 m at the c172p's 660 m radius --
#: measured, and refused as route.closure -- which is the guidance's
#: tolerance to tune, not this test's.)
AROUND_THE_HILL = [point(400.0, 0.0), point(800.0, 100.0), point(1150.0, 300.0),
                   point(1400.0, 580.0)]
#: The flat route: north, then a bend to the north-east.
FLAT_ROUTE = [point(0.0, 500.0), point(150.0, 900.0)]


@pytest.fixture(scope="module")
def hill_root(tmp_path_factory) -> Path:
    from core.capture.poses import SceneFrame
    from core.terrain.glo30 import utm_zone_crs
    from core.terrain.heightfield import Georeference, Heightfield

    crs = utm_zone_crs(ORIGIN_LAT, ORIGIN_LON)
    frame = SceneFrame(crs, ORIGIN_LAT, ORIGIN_LON, declared=True)
    n = int(round(2 * HILL_HALF_M / HILL_PIXEL_M)) + 1
    offsets = -HILL_HALF_M + HILL_PIXEL_M * np.arange(n)
    east, north = np.meshgrid(offsets, -offsets, indexing="xy")   # row 0 northernmost
    z = HILL_PEAK_M * np.exp(-(east ** 2 + (north - HILL_NORTH_M) ** 2)
                             / (2.0 * HILL_SIGMA_M ** 2))
    geo = Georeference(crs=crs, origin_x_m=frame.origin_x_m - HILL_HALF_M,
                       origin_y_m=frame.origin_y_m + HILL_HALF_M, pixel_size_m=HILL_PIXEL_M)
    field = Heightfield.from_elevations(z, geo, name="hill",
                                        provenance={"fixture": "tests/test_route_map.py hill"})
    root = tmp_path_factory.mktemp("route_terrain")
    field.write(root / "hill")
    return root


@pytest.fixture
def hill(hill_root, monkeypatch) -> Path:
    """Point the scene picker at the hill for one test (TERRAIN_DIR only,
    as tests/test_webapp.py's control_ridge does)."""
    monkeypatch.setattr(runs_module, "TERRAIN_DIR", hill_root)
    return hill_root / "hill"


def hill_elevation_m(east, north):
    return HILL_PEAK_M * math.exp(-(east ** 2 + (north - HILL_NORTH_M) ** 2)
                                  / (2.0 * HILL_SIGMA_M ** 2))


def worst_cross_track_m(flown, waypoints, spec):
    """The largest distance of a flown sample from the drawn line, by the
    route's own projection (the measure the closure uses)."""
    route = Route(waypoints, ALT, tas_kt=tas_kt_for_spec(spec))
    return max(abs(route.project(p["east_m"], p["north_m"])[1]) for p in flown)


# -- the ground to draw on ---------------------------------------------------------

def test_the_flat_payload_serves_every_limit_from_python():
    spec = flat_spec()
    reply = TestClient(app).post("/route/terrain", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["kind"] == "flat"
    grid = data["grid"]
    assert grid["points"] == 2 and len(grid["heights_m"]) == 4
    assert set(grid["heights_m"]) == {float(spec.terrain_elevation.value)}
    assert data["aircraft"]["alt_m"] == ALT
    limits = data["route"]
    tas = tas_kt_for_spec(spec)
    assert limits["tas_kt"] == tas
    assert limits["turn_radius_m"] == turn_radius_m(tas, BANK_LIMIT_DEFAULT_DEG)
    assert limits["bank_limit_deg"] == BANK_LIMIT_DEFAULT_DEG
    assert limits["bank_limit_max_deg"] == BANK_LIMIT_RANGE_DEG[1]
    assert limits["hdot_max_mps"] == HDOT_MAX_MPS
    assert limits["min_clearance_m"] == ROUTE_MIN_CLEARANCE_M
    assert limits["lookahead_m"] == lookahead_m_for(tas)
    # The placer's clock: min(duration, CLIP_SECONDS), said so.
    assert limits["seconds"] == min(float(spec.duration.value), CLIP_SECONDS) == data["clip_seconds"]
    assert limits["duration_s"] == float(spec.duration.value)
    assert limits["clip_cap_s"] == CLIP_SECONDS
    assert "placer" in limits["seconds_basis"]
    # The window holds the reach circle, and nothing is stated yet.
    assert limits["reach_m"] == pytest.approx(tas * 0.514444 * limits["seconds"], rel=1e-3)
    assert limits["half_extent_m"] >= limits["reach_m"]
    assert grid["step_m"] * (grid["points"] - 1) / 2 == pytest.approx(limits["half_extent_m"])
    assert limits["waypoints"] == [] and limits["stated"] is False
    assert "no route drawn" in limits["from"]
    assert "ISA" in limits["tas_basis"]


def test_the_raster_payload_is_the_hill_sampled_at_the_reach_window(hill):
    from core.capture.poses import SceneFrame
    from core.terrain.heightfield import Heightfield

    spec = hill_spec()
    spec.set("route.waypoints", AROUND_THE_HILL, frm="drawn on the route map")
    reply = TestClient(app).post("/route/terrain", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["kind"] == "raster" and data["scene"]["key"] == "hill"
    grid = data["grid"]
    assert grid["points"] == 129 and len(grid["heights_m"]) == 129 ** 2
    field = Heightfield.read(hill)
    frame = SceneFrame.for_spec(spec, field)
    half, step = -grid["south_m"], grid["step_m"]
    assert half <= HILL_HALF_M + 1e-6          # clipped to the raster
    for r in (0, 40, 64, 100, 128):
        for c in (0, 64, 128):
            x, y = frame.to_projected(-half + r * step, -half + c * step)
            assert abs(grid["heights_m"][r * 129 + c] - field.elevation_at(x, y)) < 0.06
    # The hill is where it was built, in the page's frame.
    row = int(round((half + HILL_NORTH_M) / step))
    col = int(round(half / step))
    assert grid["heights_m"][row * 129 + col] == pytest.approx(HILL_PEAK_M, abs=25.0)
    # A stated route comes back for the map to open with.
    assert data["route"]["waypoints"] == AROUND_THE_HILL and data["route"]["stated"] is True
    assert data["route"]["from"] == "drawn on the route map"


def test_a_bank_limit_the_autopilot_does_not_fly_refuses_the_map_by_name():
    spec = flat_spec()
    spec.set("route.waypoints", FLAT_ROUTE, frm="drawn on the route map")
    spec.set("route.bank_limit_deg", 90.0)
    reply = TestClient(app).post("/route/terrain", json={"spec": spec.to_dict()})
    assert reply.status_code == 400
    data = reply.json()
    assert data["refused"] == "route.bank_limit"
    assert data["limit"] == BANK_LIMIT_RANGE_DEG[1] and data["actual"] == 90.0
    assert data["sentence"] and "route.bank_limit" not in data["sentence"]


# -- the physics check -------------------------------------------------------------

def test_the_check_flies_the_flat_line_and_returns_the_track():
    spec = flat_spec(20)
    reply = TestClient(app).post("/route/check", json={
        "spec": spec.to_dict(), "waypoints": FLAT_ROUTE, "bank_limit_deg": 25.0})
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["ok"] is True and data["violations"] == [] and data["stage"] == "flight"
    assert data["seconds"] == pytest.approx(20.0, abs=0.2)
    assert data["heading_deg"] == 0.0            # the first leg's bearing
    assert data["bank_limit_deg"] == 25.0
    flown = data["flown"]
    assert len(flown) > 150
    assert set(flown[0]) == {"t_s", "north_m", "east_m", "alt_m", "agl_m", "heading_deg",
                             "pitch_deg", "roll_deg"}
    assert flown[0]["t_s"] == 0.0 and abs(flown[0]["north_m"]) < 1.0 and abs(flown[0]["east_m"]) < 1.0
    # The track follows the line within the declared tolerance, and the
    # server's own cross-track figure agrees with a projection of it.
    tolerance = RouteTolerance()
    worst = worst_cross_track_m(flown, FLAT_ROUTE, spec)
    assert worst <= tolerance.cross_track_m
    assert data["max_cross_track_m"] == pytest.approx(worst, abs=2.0)
    assert flown[-1]["north_m"] > 800.0 and flown[-1]["east_m"] > 50.0   # on the second leg
    assert all(abs(p["alt_m"] - ALT) <= tolerance.altitude_m for p in flown)
    # Over the slab the clearance is the altitude over the datum the
    # PLANNED copy flew (scene-setting stages a place for a placeless
    # prompt, so the reply says which datum), the wing's droop at most a
    # few metres below it, and every sample says so.
    datum = data["datum_m"]
    assert datum != float(spec.terrain_elevation.value)   # staged, and said
    assert 0.0 <= (ALT - datum) - data["min_clearance_m"] < 5.0
    assert all(abs(p["agl_m"] - (p["alt_m"] - datum)) < 1.0 for p in flown)
    assert data["clearance_floor_m"] == ROUTE_MIN_CLEARANCE_M
    assert "slab" in data["measured_on"]
    checks = {c["name"]: c for c in data["closure"]}
    assert set(checks) == {"airspeed", "cross_track_max", "route_altitude", "route_reached"}
    assert all(c["ok"] for c in checks.values())


def test_a_malformed_line_and_a_bad_bank_limit_refuse_by_name_without_flying():
    client = TestClient(app)
    spec = flat_spec().to_dict()
    reply = client.post("/route/check", json={"spec": spec, "waypoints": "north"})
    assert reply.status_code == 400
    data = reply.json()
    assert data["refused"] == "route.shape" and data["flown"] is None
    assert data["stage"] == "validation" and data["ok"] is False
    assert data["violations"][0]["constraint"] == "route.shape"
    assert data["violations"][0]["sentence"] and data["violations"][0]["hint"]
    reply = client.post("/route/check", json={"spec": spec, "waypoints": FLAT_ROUTE,
                                              "bank_limit_deg": 70.0})
    assert reply.status_code == 400
    names = [v["constraint"] for v in reply.json()["violations"]]
    assert names == ["route.bank_limit"]
    # A spec that cannot be read is said, not flown.
    assert client.post("/route/check", json={"spec": {"nonsense": True},
                                             "waypoints": FLAT_ROUTE}).status_code == 400


def test_a_line_into_the_hill_is_refused_by_name_with_the_measured_clearance(hill):
    spec = hill_spec(30)
    reply = TestClient(app).post("/route/check", json={
        "spec": spec.to_dict(), "waypoints": INTO_THE_HILL, "bank_limit_deg": 25.0})
    assert reply.status_code == 409, reply.json()
    data = reply.json()
    assert data["refused"] == "route.terrain_clearance" and data["ok"] is False
    violation = data["violations"][0]
    assert violation["constraint"] == "route.terrain_clearance"
    assert violation["limit"] == ROUTE_MIN_CLEARANCE_M and violation["unit"] == "m"
    # About 100 m over the top (1500 m over a 1400 m hill), measured on
    # the raster at the span stations, never a guess.
    assert violation["actual"] == data["min_clearance_m"]
    assert 60.0 < violation["actual"] < ROUTE_MIN_CLEARANCE_M
    assert "raster" in violation["message"] and violation["sentence"]
    assert "raster" in data["measured_on"]
    # The flight was flown and comes back, so the page can show where.
    flown = data["flown"]
    assert len(flown) > 200
    lowest = min(flown, key=lambda p: p["agl_m"])
    assert abs(lowest["north_m"] - HILL_NORTH_M) < 150.0 and abs(lowest["east_m"]) < 60.0
    assert lowest["agl_m"] == pytest.approx(ALT - hill_elevation_m(lowest["east_m"],
                                                                   lowest["north_m"]), abs=15.0)


def test_a_line_around_the_hill_passes_with_the_track_near_the_line(hill):
    spec = hill_spec(30)
    reply = TestClient(app).post("/route/check", json={
        "spec": spec.to_dict(), "waypoints": AROUND_THE_HILL, "bank_limit_deg": 25.0})
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["ok"] is True and data["violations"] == []
    assert data["min_clearance_m"] >= ROUTE_MIN_CLEARANCE_M
    assert data["min_clearance_m"] > 1000.0
    assert data["heading_deg"] == 90.0                   # the first leg runs east
    flown = data["flown"]
    tolerance = RouteTolerance()
    assert worst_cross_track_m(flown, AROUND_THE_HILL, spec) <= tolerance.cross_track_m
    assert data["max_cross_track_m"] <= tolerance.cross_track_m
    end = flown[-1]
    assert math.hypot(end["east_m"] - 1400.0, end["north_m"] - 580.0) < 250.0   # the end reached
    assert end["heading_deg"] < 60.0                     # turned north-east
    assert all(c["ok"] for c in data["closure"])
    assert data["scene"] == "hill"


# -- /run -----------------------------------------------------------------------------

def test_run_flies_the_route_in_the_pinned_order_and_the_card_carries_its_schedule(
        tmp_path, monkeypatch, hill_root):
    """/run: plan_terrain_environment -> plan_route_flight -> derive_seed,
    with plan_terrain_flight skipped (the route pre-flight is the terrain
    check); the manager then receives the spec with the flight on it, and
    the card _render_flow writes carries the route's control schedule as
    control_inputs and the route block beside it."""
    import core.util.platform as plat
    from webapp.route_map import ROUTE_FLIGHT_ATTR, plan_route_flight
    from webapp.runs import RunState

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh", lambda spec: None)
    captured = {}
    monkeypatch.setattr(manager, "start",
                        lambda spec, provenance: captured.update(spec=spec) or {"run_id": "routetest"})
    order = []

    def recording(name, real):
        def wrapped(spec, *args, **kwargs):
            order.append(name)
            return real(spec, *args, **kwargs)
        return wrapped

    for name in ("plan_terrain_environment", "plan_route_flight", "derive_seed",
                 "plan_terrain_flight"):
        monkeypatch.setattr(server_module, name, recording(name, getattr(server_module, name)))

    spec = flat_spec(20)
    spec.set("route.waypoints", FLAT_ROUTE, frm="drawn on the route map")
    spec.set("heading", 0.0, frm="drawn on the route map: the first leg's bearing")
    reply = TestClient(app).post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    assert order == ["plan_terrain_environment", "plan_route_flight", "derive_seed"]
    planned = captured["spec"]
    assert reply.json()["digest"] == planned.digest()
    flight = getattr(planned, ROUTE_FLIGHT_ATTR)
    assert flight["ok"] and flight["digest"] == Route.from_spec(planned).digest()
    schedule = flight["schedule"]
    assert len(schedule) == 201 and all(tuple(e) == SCHEDULE_KEYS for e in schedule)
    assert schedule[0]["t_s"] == 0.0 and schedule[-1]["t_s"] == pytest.approx(20.0)
    assert max(abs(e["aileron"]) for e in schedule) > 0.01      # the bend was flown
    assert isinstance(flight["replay_divergence_m"], float)
    assert 0.0 < flight["replay_divergence_m"] < 200.0
    assert flight["replay_seconds"] == min(20.0, CLIP_SECONDS)
    # The host projection left the autopilot off. Planned again as it
    # stands, the copy fails validation (route.hold_state), which the
    # planner leaves to the validator: None, and the flight /run made is
    # left on the object untouched.
    assert bool(planned.hold_state.value) is False
    assert plan_route_flight(planned) is None
    assert getattr(planned, ROUTE_FLIGHT_ATTR) is flight

    # The render flow, with the render itself stubbed as test_webapp.py
    # stubs it: the card is the product under test.
    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None, look=None,
                    camera="chase", **kwargs):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    monkeypatch.setattr(RunManager, "_render", staticmethod(fake_render))
    monkeypatch.setattr(runs_module, "encode_clip",
                        lambda frames, clip: bool(clip.write_bytes(b"x")) or True)
    monkeypatch.setattr(runs_module, "build_panel_clip", lambda *a, **k: True)
    monkeypatch.setattr(runs_module, "ensure_aircraft_model", lambda spec, report: None)
    monkeypatch.setattr(runs_module, "ensure_control_ridge", lambda: None)
    monkeypatch.setattr(runs_module, "TERRAIN_DIR", hill_root)   # no real bakes, no synthesis
    local = RunManager(out_root=tmp_path)
    run = RunState(run_id="routetest")
    local._render_flow(run, planned, provenance={})
    assert run.status == "done", run.detail
    card = json.loads((tmp_path / "routetest" / "card.json").read_text(encoding="utf-8"))
    assert card["control_inputs"] == json.loads(json.dumps(schedule))
    block = card["route"]
    assert tuple(block) == CARD_KEYS
    assert block["waypoints"] == FLAT_ROUTE and block["digest"] == flight["digest"]
    assert block["bank_limit_deg"] == BANK_LIMIT_DEFAULT_DEG
    assert block["replay_divergence_m"] == flight["replay_divergence_m"]
    assert len(block["flown"]) == len(flight["flown"])
    assert set(block["flown"][0]) == {"t_s", "north_m", "east_m", "alt_m", "yaw_deg",
                                      "pitch_deg", "roll_deg"}
    assert "OPEN LOOP" in run.conditions["route"]
    assert f"{flight['replay_divergence_m']:.0f} m" in run.conditions["route"]


def test_a_route_without_the_autopilot_is_refused_once_by_name(monkeypatch):
    """The planner leaves a validation problem to the validator (the
    clearance planner's rule), so the verdict names route.hold_state
    once, not twice."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(RunManager, "_execute", lambda self, run, spec, provenance: None)
    spec = flat_spec(20)
    spec.set("route.waypoints", FLAT_ROUTE, frm="drawn on the route map")
    spec.set("hold_state", False)
    reply = TestClient(app).post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409
    data = reply.json()
    assert data["refused"] == "validation"
    names = [v["constraint"] for v in data["violations"]]
    assert names.count("route.hold_state") == 1


def test_a_run_with_no_route_is_untouched(monkeypatch):
    """Without a route the planner answers None at once and the clearance
    planner runs as before (its call is the pin)."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh", lambda spec: None)
    monkeypatch.setattr(manager, "start", lambda spec, provenance: {"run_id": "plain"})
    called = []
    monkeypatch.setattr(server_module, "plan_terrain_flight",
                        lambda spec: called.append("plan_terrain_flight"))
    reply = TestClient(app).post("/run", json={"spec": flat_spec().to_dict()})
    assert reply.status_code == 200, reply.json()
    assert called == ["plan_terrain_flight"]


# -- the page's payload and script -----------------------------------------------------

def test_the_spec_payload_always_carries_the_route_section_and_a_summary_row():
    client = TestClient(app)
    compiled = client.post("/compile", json={
        "prompt": "fly the c172p at 1500 m and 100 kt for 20 seconds",
        "compiler": "regex"}).json()
    payload = compiled["spec"]
    assert set(payload["dict"]["route"]) == {"waypoints", "bank_limit_deg"}
    assert payload["dict"]["route"]["waypoints"]["value"] == []
    assert payload["dict"]["route"]["bank_limit_deg"]["value"] == BANK_LIMIT_DEFAULT_DEG
    rows = [f for f in payload["fields"] if f["section"] == "route"]
    assert [r["name"] for r in rows] == ["waypoints"]
    assert rows[0]["value"] == "0 points, 0.0 km" and rows[0]["source"] == "default"
    assert "no route drawn" in rows[0]["from"]
    # The default section read back is absent, so the digest is unmoved.
    assert ScenarioSpec.from_dict(payload["dict"]).digest() == payload["digest"]
    # A stated route shows its summary, never the list.
    spec_dict = payload["dict"]
    spec_dict["route"]["waypoints"] = {"value": FLAT_ROUTE, "unit": "points",
                                       "source": "user", "from": "drawn on the route map"}
    again = client.post("/cameras", json={"spec": spec_dict, "preset": "chase"}).json()
    row = next(f for f in again["fields"] if f["section"] == "route")
    assert row["value"] == "2 points, 0.9 km" and row["source"] == "user"
    assert "1500" not in str(row["value"])


def test_the_server_serves_the_route_map_script():
    static = Path(__file__).resolve().parents[1] / "webapp" / "static"
    if not (static / "route_map.js").is_file():
        pytest.skip("webapp/static/route_map.js is the page part's; the route is declared")
    reply = TestClient(app).get("/route_map.js")
    assert reply.status_code == 200
    assert "javascript" in reply.headers["content-type"]
    assert "window.RouteMap" in reply.text


# -- the open-loop replay --------------------------------------------------------------

def test_the_replay_applies_all_three_surfaces_on_the_run_clock():
    """_fly_clearance_track generalised: aileron set, elevator added to the
    latched trim, rudder as given (FlightSimScenarioWorld.cpp
    ApplyStepWrites), on the run clock the host steps the card on. A
    rudder entry yaws, an elevator entry pitches, and an entry at 4 s
    acts at 4 s of run time -- while the doublet's "sim" clock, left as
    it was, acts at once (JSBSim's clock is past 4 s at the first step
    after the engine start)."""
    from webapp.runs import _fly_clearance_track

    spec = flat_spec(20)
    still = _fly_clearance_track(spec, None, (), 8.0, clock="run")
    assert len(still) == 80 and {"t_s", "lat_deg", "lon_deg", "alt_m", "clearance_m",
                                 "north_m", "east_m"} <= set(still[0])
    assert still[0]["t_s"] == pytest.approx(1.0 / float(spec.rate.value))
    assert still[-1]["north_m"] > 400.0                   # flew its heading, north
    # Over the slab the stations clear the datum by the altitude, less a
    # wing's droop: the flat branch of the station check.
    datum = float(spec.terrain_elevation.value)
    assert 0.0 <= (still[-1]["alt_m"] - datum) - still[-1]["clearance_m"] < 5.0

    def flown_with(**surface):
        entry = {"t_s": 2.0, "aileron": 0.0, "elevator": 0.0, "rudder": 0.0, **surface}
        return _fly_clearance_track(spec, None, (entry,), 8.0, clock="run")

    rudder = flown_with(rudder=0.3)
    before = [abs(a["east_m"] - b["east_m"]) for a, b in zip(still, rudder) if a["t_s"] < 2.0]
    assert max(before) < 1e-9                              # nothing applied before 2 s
    assert abs(rudder[-1]["east_m"] - still[-1]["east_m"]) > 15.0  # then it yawed (32 m measured)
    elevator = flown_with(elevator=-0.2)
    assert elevator[-1]["alt_m"] - still[-1]["alt_m"] > 30.0       # nose up: 73 m measured
    aileron = flown_with(aileron=0.3)
    assert aileron[-1]["east_m"] - still[-1]["east_m"] > 30.0      # rolled right: 76 m measured

    # The doublet's clock is JSBSim's own, already past 4 s at the first
    # step (the engine start): an entry at 4 s acts at once on that
    # clock and at 4 s on the run clock -- the pre-flight's measured
    # discrepancy with the host, left as it was and said here.
    later = ({"t_s": 4.0, "aileron": 0.0, "elevator": 0.0, "rudder": 0.3},)
    on_run_clock = _fly_clearance_track(spec, None, later, 6.0, clock="run")
    at_once = _fly_clearance_track(spec, None, later, 6.0)
    assert on_run_clock[25]["east_m"] == still[25]["east_m"]        # 2.5 s: not yet
    assert abs(at_once[25]["east_m"] - still[25]["east_m"]) > 0.5    # 2.5 s: already

    with pytest.raises(ValueError, match="clock"):
        _fly_clearance_track(spec, None, (), 1.0, clock="wall")
