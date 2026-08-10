"""Trim must be real, and it must not be attempted on a dead airframe.

Covers the two §2.7 failures found while building Gate 0: an unstarted engine
that trims as a glider while reporting success, and a trim failure that JSBSim
logs but continues past.
"""

import pytest

from core.fdm import FlightDynamics, SimulationError, TrimError, TrimMode
from core.fdm import units as u

AIRCRAFT = "global5000"
LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
}


def cruise(aircraft=AIRCRAFT, altitude_m=3000, cas_kt=250):
    fdm = FlightDynamics(aircraft)
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL}
    )
    return fdm


def test_trim_before_initial_conditions_is_refused():
    fdm = FlightDynamics(AIRCRAFT)
    with pytest.raises(SimulationError):
        fdm.trim(TrimMode.LONGITUDINAL)


def test_airborne_trim_with_engines_stopped_is_refused():
    """Trimming an unpowered airframe yields a plausible-looking glider."""
    fdm = cruise()
    assert not fdm.engines_running
    with pytest.raises(SimulationError) as exc:
        fdm.trim(TrimMode.LONGITUDINAL)
    assert "engines stopped" in str(exc.value)


def test_start_engines_verifies_spool_not_thrust():
    """Thrust at zero throttle cannot distinguish running from stopped.

    Measured: global5000 idles at 12 lbf per engine at 3000 m and 0 lbf at
    6000 m, running or not. N1 goes 0 -> 30%.
    """
    fdm = cruise()
    assert fdm.props.get("propulsion/engine/n1") == 0.0
    fdm.start_engines()
    assert fdm.props.get("propulsion/engine/n1") > 0.0
    assert fdm.engines_running


def test_trim_succeeds_in_the_envelope_and_holds():
    fdm = cruise()
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    assert fdm.is_trimmed
    s = fdm.state()
    # Level symmetric trim: pitch equals alpha when the flight path is level.
    assert s.pitch_deg == pytest.approx(s.alpha_deg, abs=0.05)
    assert abs(s.roll_deg) < 0.01
    assert abs(s.climb_rate_mps) < 0.5


def test_trim_outside_the_envelope_raises_rather_than_continuing():
    """JSBSim logs 'Trim Failed!!!' and carries on with partial state."""
    fdm = cruise(altitude_m=10000, cas_kt=300)   # M0.835, past this model's tables
    fdm.start_engines()
    with pytest.raises(TrimError) as exc:
        fdm.trim(TrimMode.LONGITUDINAL)
    assert "must not" in str(exc.value)


def test_mass_hold_is_recorded_in_provenance():
    """A mass-held run must never be reportable as a realistic one."""
    fdm = cruise()
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    assert fdm.provenance()["mass_held_constant"] is False
    fdm.hold_mass(True)
    assert fdm.provenance()["mass_held_constant"] is True

    before = fdm.state().weight_kg
    fdm.run_for(30)
    assert fdm.state().weight_kg == pytest.approx(before, abs=1e-6)


def test_fuel_burn_moves_mass_when_not_held():
    fdm = cruise()
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    before = fdm.state().weight_kg
    fdm.run_for(60)
    assert fdm.state().weight_kg < before


def test_discovered_mixture_refuses_full_rich_at_altitude():
    """The card's engine-start mixture is verified in the UE host's own
    sequence (InitRunning + mixture + trim + 5 s sustain). At 2600 m a
    force-started engine at full rich decays through 531 rpm and trims a
    glider (measured -- it cost four glider clips), so the discovery must
    come back leaned. A discovery that skips the sustain check settles at
    1.0 here, which is the regression this test pins. (The crank-start
    path is different: with the starter assisting, full rich stabilises at
    a sick ~500 rpm idle -- measured -- so the crank cannot discriminate
    and the DISCOVERY is the load-bearing check for cards.)"""
    from core.scenario.card import _MIXTURE_CACHE, discovered_engine_mixture
    from experiments.gate5_ue_parity import reference_spec

    _MIXTURE_CACHE.clear()
    spec = reference_spec("fly the c172 at 2600 m and 100 kt for 30 seconds")
    spec.set("latitude", 37.7275, frm="test")
    spec.set("longitude", -119.61, frm="test")
    spec.set("heading", 73.0, frm="test")
    spec.set("terrain_elevation", 1230.9, frm="test")
    mixture = discovered_engine_mixture(spec)
    assert mixture < 1.0, (
        "the discovery accepted full rich at a density altitude where the "
        "force-started engine cannot sustain it")
