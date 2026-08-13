"""Airframe-extent terrain contact: the wings feel the mountain.

The gap under test: JSBSim's ground model looks straight down from the CG,
so a banked wingtip could pass through a slope while the physics reported
hundreds of metres of clearance. core/terrain/contact.py closes it with span
stations computed from the aircraft's own attitude and the FDM's own
wingspan; both UE hosts carry the same check (source-pinned here, the same
way the recorder selftest wiring is pinned).
"""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from core.fdm import units as u
from core.terrain.contact import (
    STATION_FRACTIONS, AirframeContact, TerrainImpactError,
    station_offsets_ned,
)
from core.terrain.ground import TerrainGround
from core.terrain.heightfield import Georeference, Heightfield

REPO = Path(__file__).resolve().parents[1]
BRIDGE = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source"
          / "FlightSimBridge" / "Private")

UTM = "EPSG:32633"
SPAN_M = 30.0


@dataclass
class FakeState:
    lat_deg: float
    lon_deg: float
    altitude_m: float
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    heading_deg: float = 0.0


def flat_ground(elevation_m: float) -> TerrainGround:
    """A 40 x 40 km flat plateau; big enough that a state near the centre
    keeps every span station inside the raster."""
    z = np.full((41, 41), elevation_m)
    field = Heightfield.from_elevations(
        z, Georeference(UTM, origin_x_m=0.0, origin_y_m=40_000.0,
                        pixel_size_m=1000.0))
    return TerrainGround(field)


def centre_lonlat(ground: TerrainGround):
    lon, lat = ground.centre_lonlat()
    return lat, lon


# -- station geometry ----------------------------------------------------


def test_level_flight_keeps_the_tips_level():
    stations = list(station_offsets_ned(0.0, 0.0, 0.0, SPAN_M))
    assert [name for name, *_ in stations] == [n for n, _ in STATION_FRACTIONS]
    for _, north, east, down in stations:
        assert down == pytest.approx(0.0, abs=1e-12)
        assert north == pytest.approx(0.0, abs=1e-12)
    # Heading north: the right tip is due east at exactly the semi-span.
    assert stations[-1][2] == pytest.approx(SPAN_M / 2.0)
    assert stations[0][2] == pytest.approx(-SPAN_M / 2.0)


def test_a_right_roll_lowers_the_right_tip_by_the_dcm_amount():
    roll = 30.0
    stations = {name: (n, e, d) for name, n, e, d
                in station_offsets_ned(roll, 0.0, 0.0, SPAN_M)}
    expected = (SPAN_M / 2.0) * math.sin(math.radians(roll))
    assert stations["right wingtip"][2] == pytest.approx(expected)
    assert stations["left wingtip"][2] == pytest.approx(-expected)
    # Mid-span stations scale linearly with their fraction.
    assert stations["right mid-span"][2] == pytest.approx(expected / 2.0)


def test_heading_carries_the_tips_around_the_compass():
    # Heading east: the right wing points south (negative north offset).
    stations = {name: (n, e, d) for name, n, e, d
                in station_offsets_ned(0.0, 0.0, 90.0, SPAN_M)}
    assert stations["right wingtip"][0] == pytest.approx(-SPAN_M / 2.0)
    assert stations["right wingtip"][1] == pytest.approx(0.0, abs=1e-9)


# -- the contact verdict -------------------------------------------------


def test_a_banked_wingtip_below_the_surface_is_an_impact():
    ground = flat_ground(100.0)
    lat, lon = centre_lonlat(ground)
    # 5 m above the plateau with 40 degrees of right bank: the right tip
    # hangs 15*sin(40) = 9.6 m below the CG, 4.6 m into the ground.
    state = FakeState(lat, lon, altitude_m=105.0, roll_deg=40.0)
    contact = AirframeContact(ground, SPAN_M)
    impact = contact.check(state, time_s=7.5)
    assert impact is not None
    assert impact.station == "right wingtip"
    assert impact.time_s == 7.5
    expected = (SPAN_M / 2.0) * math.sin(math.radians(40.0)) - 5.0
    assert impact.penetration_m == pytest.approx(expected, abs=0.01)
    assert "right wingtip" in impact.describe()


def test_the_same_bank_with_clearance_is_null():
    """The check must be quiet when the geometry clears -- otherwise every
    terrain run dies and the feature is a kill switch, not physics."""
    ground = flat_ground(100.0)
    lat, lon = centre_lonlat(ground)
    state = FakeState(lat, lon, altitude_m=200.0, roll_deg=40.0)
    assert AirframeContact(ground, SPAN_M).check(state, 0.0) is None


def test_level_wings_at_the_cg_altitude_of_the_wall_hit_all_stations():
    ground = flat_ground(100.0)
    lat, lon = centre_lonlat(ground)
    state = FakeState(lat, lon, altitude_m=99.0)
    impact = AirframeContact(ground, SPAN_M).check(state, 1.0)
    assert impact is not None
    assert impact.penetration_m == pytest.approx(1.0, abs=1e-6)


def test_stations_outside_the_raster_are_unchecked_not_cliffed():
    """The edge clamp in elevation_at would manufacture a boundary cliff;
    contains() gates the check instead."""
    ground = flat_ground(1000.0)
    # Far outside the raster in projected space: ~2 degrees south of it.
    state = FakeState(-2.0, 15.0, altitude_m=10.0, roll_deg=45.0)
    assert AirframeContact(ground, SPAN_M).check(state, 0.0) is None


def test_zero_span_is_refused():
    with pytest.raises(ValueError):
        AirframeContact(flat_ground(0.0), 0.0)


# -- the FDM's own wingspan ----------------------------------------------


def test_wingspan_comes_from_the_model_not_a_constant():
    """metrics/bw-ft, verified against the live property catalog of the
    pinned JSBSim (2026-08-11): B747 211.5 ft, c172p 35.8 ft."""
    from core.fdm import FlightDynamics

    fdm = FlightDynamics("c172p")
    contact = AirframeContact.from_fdm(flat_ground(0.0), fdm)
    assert contact.wingspan_m == pytest.approx(u.ft_to_m(35.8), abs=0.1)


# -- the runner ends the run ---------------------------------------------


def test_run_spec_raises_on_terrain_impact():
    """A run whose wings enter the terrain produces a named impact, not a
    clean recording of a flight through rock."""
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec

    ground = flat_ground(1000.0)
    lat, lon = centre_lonlat(ground)
    spec = compile_prompt("fly the 747 at 900 m and 250 kt for 5 seconds")
    spec.set("latitude", round(lat, 6))
    spec.set("longitude", round(lon, 6))
    with pytest.raises(TerrainImpactError) as exc:
        run_spec(spec, validate_first=False, terrain_ground=ground)
    assert "below the surface" in str(exc.value)
    assert exc.value.impact.penetration_m > 0.0


def test_run_spec_over_clear_terrain_records_the_contact_claim():
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec

    ground = flat_ground(100.0)
    lat, lon = centre_lonlat(ground)
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt for 2 seconds")
    spec.set("latitude", round(lat, 6))
    spec.set("longitude", round(lon, 6))
    result = run_spec(spec, validate_first=False, terrain_ground=ground)
    claim = result.manifest["airframe_contact"]
    assert claim["stations"] == [n for n, _ in STATION_FRACTIONS]
    assert "not a mesh intersection" in claim["claim"]


# -- the UE hosts carry the same check (source-pinned) -------------------


def test_ue_step_refuses_on_airframe_impact():
    text = (BRIDGE / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    assert ("return !Crashed(TimeSeconds, Error) "
            "&& !AirframeImpact(TimeSeconds, Error);") in text


def test_interactive_host_refuses_on_airframe_impact():
    text = (BRIDGE / "FlightSimInteractiveMode.cpp").read_text(encoding="utf-8")
    assert "Scenario.AirframeImpact(SimTimeSeconds, Error)" in text


def test_ue_stations_match_the_python_stations():
    """One station table in two languages: change one, change both."""
    text = (BRIDGE / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    body = text.split("FFlightSimScenarioWorld::AirframeImpact", 1)[-1]
    for name, fraction in STATION_FRACTIONS:
        assert f'TEXT("{name}"), {fraction}' in body, name
    assert 'ReadProperty(TEXT("metrics/bw-ft"))' in body
