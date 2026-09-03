"""Package E: the altitude setpoint is raised ahead of terrain, or the run
refuses by name before the impact.

Every number asserted here was produced by
``experiments/airborne/terrain_lookahead.py`` on the shipped code; the
tests fly the same ridge through the same runner.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.terrain.contact import TerrainImpactError
from core.terrain.lookahead import (
    HORIZON_S, RTC_M, TerrainLookahead, TerrainLookaheadError,
)
from experiments.airborne.terrain_lookahead import (
    PLAIN_M, ridge_ground, ridge_spec,
)

ALTITUDE_M = 3000.0
CAS_KT = 250.0
RIDGE_NORTH_M = 8000.0


def fly(crest_m: float, duration_s: float = 100.0):
    from core.scenario.runner import run_spec

    ground = ridge_ground(crest_m, RIDGE_NORTH_M)
    spec = ridge_spec(ground, ALTITUDE_M, CAS_KT, duration_s)
    return run_spec(spec, validate_first=False, terrain_ground=ground)


# -- the flight -----------------------------------------------------------


def test_a_ridge_the_aircraft_can_clear_is_cleared_with_the_rtc():
    """The 747 at 3000 m flies north at a 3300 m ridge 8 km ahead. The
    look-ahead raises the setpoint at the first tick, roughly 54 s
    before the crest; the aircraft climbs, crosses with at least the RTC
    (measured: 44.8 m minimum AGL at the raster's crest, RTC + the hold
    tolerance) and the closure assertion passes at the raised setpoint.
    Without the look-ahead the SAME run ends in a left-wingtip impact at
    52.6 s (experiments/airborne/terrain_lookahead.py --pre)."""
    result = fly(3300.0)
    lookahead = result.manifest["terrain_lookahead"]
    assert lookahead["raises"] >= 1
    first = lookahead["events"][0]
    # Issued at least 30 s before the terrain it clears.
    assert first["ahead_s"] >= 30.0
    assert first["t"] < 1.0
    assert first["setpoint_m"] > ALTITUDE_M + 250.0
    assert first["required_hdot_mps"] < first["available_hdot_mps"]
    agl = result.telemetry.series("agl_m")
    assert min(agl) >= RTC_M
    assert result.closure is not None and result.closure.ok
    # The setpoint was raised, never lowered: the run ends at the raised
    # altitude, not back at the spec's.
    assert result.telemetry.series("altitude_m")[-1] > ALTITUDE_M + 250.0
    # The record says so.
    labels = [e["label"] for e in result.telemetry.events]
    assert any("terrain look-ahead" in label for label in labels)


def test_a_ridge_the_aircraft_cannot_clear_refuses_by_name_before_impact():
    """A 5000 m crest 8 km ahead needs 12.8 m/s of climb on the ridge's
    face against the 12.2 m/s the controller's limit allows: the run
    refuses terrain.lookahead at its first tick, not with an impact 50 s
    later."""
    with pytest.raises(TerrainLookaheadError) as exc:
        fly(5000.0)
    threat = exc.value.threat
    assert exc.value.constraint == "terrain.lookahead"
    assert not threat.feasible
    assert threat.time_s < 1.0
    assert threat.required_hdot_mps > threat.available_hdot_mps
    assert "does NOT clear" in str(exc.value)
    assert f"{RTC_M:.0f} m" in str(exc.value)


def test_terrain_beyond_the_end_of_the_run_is_not_this_flight_s_threat():
    """The 5000 m crest 8 km (54 s) ahead refuses a 100 s run at its first
    tick; a 20 s run never reaches it, so it is not raised, not refused,
    and the setpoint stays at the spec's. Measured on the user's machine
    before this cap: a 22 s clip's closure pair refused on a ridge 59 s
    ahead that the clip never showed."""
    result = fly(5000.0, duration_s=20.0)
    lookahead = result.manifest["terrain_lookahead"]
    assert lookahead["raises"] == 0
    commanded = [c for c in result.closure.checks if c.name == "altitude"][0]
    assert commanded.commanded == pytest.approx(ALTITUDE_M, abs=0.01)


def test_the_horizon_is_capped_by_the_time_left():
    ground = ridge_ground(3300.0, RIDGE_NORTH_M)
    la = TerrainLookahead(ground, wingspan_m=60.0, hdot_capability_mps=12.0)
    state = centre_state(ground, 3000.0)
    assert la.evaluate(state, 3000.0).threat is not None
    assert la.evaluate(state, 3000.0, remaining_s=20.0).threat is None
    assert la.evaluate(state, 3000.0, remaining_s=120.0).threat is not None


def test_a_plain_never_moves_the_setpoint():
    result = fly(PLAIN_M, duration_s=20.0)
    lookahead = result.manifest["terrain_lookahead"]
    assert lookahead["raises"] == 0
    assert lookahead["events"] == []
    assert lookahead["samples"] > 0
    commanded = [c for c in result.closure.checks if c.name == "altitude"][0]
    assert commanded.commanded == pytest.approx(ALTITUDE_M, abs=0.01)


def test_the_capability_is_the_controller_limit_package_d_measured():
    """The escape profile climbs at ap/tecs/hdot-max-fps, which engage()
    capped at a fraction of the MEASURED excess power, not at a constant."""
    result = fly(PLAIN_M, duration_s=2.0)
    lookahead = result.manifest["terrain_lookahead"]
    performance = result.manifest["control"]["performance"]
    assert lookahead["hdot_capability_mps"] > 0.0
    assert lookahead["hdot_capability_mps"] <= performance["edot_max_mps"]
    assert lookahead["horizon_s"] == HORIZON_S
    assert lookahead["rtc_m"] == RTC_M


# -- the projection, without an FDM ---------------------------------------


@dataclass
class State:
    t: float
    lat_deg: float
    lon_deg: float
    altitude_m: float
    climb_rate_mps: float
    v_north_mps: float
    v_east_mps: float


def centre_state(ground, altitude_m, hdot=0.0, speed=150.0):
    lon, lat = ground.centre_lonlat()
    return State(0.0, lat, lon, altitude_m, hdot, speed, 0.0)


def test_the_escape_profile_holds_the_present_climb_then_the_limit():
    ground = ridge_ground(PLAIN_M, RIDGE_NORTH_M)
    la = TerrainLookahead(ground, wingspan_m=60.0, hdot_capability_mps=10.0,
                          response_s=5.0)
    assert la.escape_altitude_m(1000.0, -2.0, 5.0) == pytest.approx(990.0)
    assert la.escape_altitude_m(1000.0, -2.0, 15.0) == pytest.approx(1090.0)
    assert la.escape_altitude_m(1000.0, 0.0, 2.0) == pytest.approx(1000.0)


def test_the_setpoint_is_only_ever_raised():
    ground = ridge_ground(3300.0, RIDGE_NORTH_M)
    la = TerrainLookahead(ground, wingspan_m=60.0, hdot_capability_mps=12.0)
    # Already holding above the crest + RTC: nothing to do.
    high = la.evaluate(centre_state(ground, 3500.0), current_setpoint_m=3500.0)
    assert high.threat is None and high.setpoint_m is None
    # Holding below it: the setpoint clears the highest sample in the
    # horizon, and the threat names where it is.
    low = la.evaluate(centre_state(ground, 3000.0), current_setpoint_m=3000.0)
    assert low.threat is not None and low.threat.feasible
    assert low.setpoint_m >= low.threat.terrain_m + RTC_M
    assert low.threat.distance_m == pytest.approx(RIDGE_NORTH_M, abs=100.0)


def test_a_descending_aircraft_needs_more_than_a_level_one():
    ground = ridge_ground(3300.0, RIDGE_NORTH_M)
    la = TerrainLookahead(ground, wingspan_m=60.0, hdot_capability_mps=12.0)
    level = la.evaluate(centre_state(ground, 3000.0, hdot=0.0), 3000.0)
    sinking = la.evaluate(centre_state(ground, 3000.0, hdot=-10.0), 3000.0)
    assert sinking.threat.required_hdot_mps > level.threat.required_hdot_mps


def test_an_aircraft_that_cannot_climb_is_refused_at_construction():
    ground = ridge_ground(PLAIN_M, RIDGE_NORTH_M)
    with pytest.raises(ValueError, match="cannot climb"):
        TerrainLookahead(ground, wingspan_m=60.0, hdot_capability_mps=0.0)


# -- the web app carries the name -----------------------------------------


def test_the_capture_carries_the_refusal_by_name():
    from webapp.capture import CaptureError, _run_named

    ground = ridge_ground(5000.0, RIDGE_NORTH_M)
    la = TerrainLookahead(ground, wingspan_m=60.0, hdot_capability_mps=12.0)

    def refusing_run_spec(spec, **kwargs):
        la.evaluate(centre_state(ground, 3000.0), 3000.0)
        raise AssertionError("unreachable: the evaluation refuses")

    with pytest.raises(CaptureError) as exc:
        _run_named(refusing_run_spec, None)
    assert exc.value.constraint == "terrain.lookahead"
    assert "does NOT clear" in exc.value.message

    def crashing_run_spec(spec, **kwargs):
        from core.terrain.contact import TerrainImpact

        raise TerrainImpactError(TerrainImpact(
            station="left wingtip", time_s=1.0, penetration_m=2.0,
            station_altitude_m=10.0, terrain_m=12.0, lat_deg=0.0,
            lon_deg=0.0))

    with pytest.raises(CaptureError) as exc:
        _run_named(crashing_run_spec, None)
    assert exc.value.constraint == "terrain.impact"
