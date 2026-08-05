"""The observer tier is read-only, and it reports what the FDM actually has.

§2.1: state flows JSBSim -> observers and never back. §1.3: load factor comes
from the accelerometer, never from finite-differenced velocity.
"""

import dataclasses
import math

import pytest

from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u
from core.fdm.state import wrap180

LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
}


@pytest.fixture(scope="module")
def trimmed():
    fdm = FlightDynamics("global5000")
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(3000), "vc-kts": 250, **LEVEL})
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    return fdm


def test_state_is_immutable(trimmed):
    """An observer must not be able to rewrite the trajectory (§2.1)."""
    s = trimmed.state()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.altitude_m = 999.0


def test_load_factor_comes_from_the_accelerometer(trimmed):
    """§1.3: the previous build differenced velocity and produced impossible G."""
    s = trimmed.state()
    assert s.load_factor == s.n_z
    # Level trimmed flight sits at about 1 g, and it must be steady rather than
    # swinging 0.5-1.5 g as the differenced trace did.
    readings = []
    for _ in range(240):
        trimmed.step()
        readings.append(trimmed.state().n_z)
    assert min(readings) > 0.97 and max(readings) < 1.03
    assert max(readings) - min(readings) < 0.02


def test_still_air_gives_zero_crab(trimmed):
    """Crab is the evidence that wind reached the FDM (§1.6)."""
    s = trimmed.state()
    assert abs(s.wind_speed_mps) < 1e-6
    assert abs(s.crab_deg) < 0.05


def test_crosswind_produces_measurable_crab():
    """The check the previous build could not perform on its own output.

    A 25 kt crosswind at 250 kt TAS should produce roughly 5-6 degrees of crab;
    the previous build advertised exactly this wind and displayed no track, so
    nobody could tell it was absent.
    """
    fdm = FlightDynamics("global5000")
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(3000), "vc-kts": 250, **LEVEL})
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)

    # Heading is north; put the wind squarely on the beam.
    fdm.props.set("atmosphere/wind-east-fps", u.kt_to_fps(25.0))
    fdm.run_for(5)

    s = fdm.state()
    assert s.wind_speed_mps == pytest.approx(u.kt_to_mps(25.0), rel=0.02)
    expected = math.degrees(math.asin(25.0 / s.tas_kt))
    assert abs(s.crab_deg) == pytest.approx(expected, abs=1.5)
    assert abs(s.crab_deg) > 3.0


def test_wind_direction_is_meteorological(trimmed):
    """Wind 'from' the west means a wind vector pointing east."""
    trimmed.props.set_many(
        {"atmosphere/wind-north-fps": 0.0,
         "atmosphere/wind-east-fps": u.kt_to_fps(20.0)}
    )
    trimmed.step()
    assert trimmed.state().wind_from_deg == pytest.approx(270.0, abs=1.0)


@pytest.mark.parametrize(
    "raw,expected", [(0, 0), (180, 180), (181, -179), (-181, 179), (360, 0), (540, 180)]
)
def test_wrap180(raw, expected):
    assert wrap180(raw) == pytest.approx(expected)


def test_state_is_finite_after_a_run(trimmed):
    trimmed.run_for(10)
    assert trimmed.state().is_finite()
