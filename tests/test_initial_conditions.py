"""Initial conditions must actually take (§1.1).

The previous build began at 201 kt with 233 kt commanded and 290 m with 300 m
commanded, and nothing noticed. These tests pin the two mechanisms that make
that impossible here: a fixed application order, and a post-condition check.
"""

import math

import pytest

from core.fdm import FlightDynamics, SimulationError
from core.fdm import units as u

AIRCRAFT = "global5000"

LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
}


@pytest.fixture
def fdm():
    return FlightDynamics(AIRCRAFT)


@pytest.mark.parametrize(
    "altitude_m,cas_kt", [(0, 250), (3000, 250), (6000, 280), (10000, 300)]
)
def test_calibrated_airspeed_round_trips_at_altitude(fdm, altitude_m, cas_kt):
    """Regression for the ic/lat-geod-deg clobber.

    Setting geodetic latitude after the airspeed re-derives the velocity state
    and reinterprets the already-converted true airspeed as calibrated. Before
    the ordering fix, 250 kt CAS at 3000 m silently became 288 kt, and 300 kt at
    10 km became Mach 1.28 -- supersonic, well outside any transport envelope.
    """
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL}
    )
    assert fdm.props.get("velocities/vc-kts") == pytest.approx(cas_kt, abs=0.5)
    assert fdm.props.get("position/h-sl-meters") == pytest.approx(altitude_m, abs=1.0)


def test_true_airspeed_exceeds_calibrated_at_altitude(fdm):
    """A sanity check on the direction of the conversion, not just its stability."""
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(10000), "vc-kts": 250, **LEVEL})
    s = fdm.state()
    assert s.tas_kt > s.cas_kt
    # 250 kt CAS at 10 km is a normal transport cruise point, not supersonic.
    assert 0.6 < s.mach < 0.8


def test_ic_application_order_is_independent_of_dict_order(fdm):
    """The caller must not have to know that ICs are order-dependent."""
    hostile = {}
    hostile["vc-kts"] = 250.0          # airspeed first, the dangerous order
    hostile["lat-geod-deg"] = 47.0     # the property that clobbers it
    hostile["h-sl-ft"] = u.m_to_ft(6000)
    hostile.update({k: v for k, v in LEVEL.items() if k != "lat-geod-deg"})
    fdm.set_initial_conditions(hostile)
    assert fdm.props.get("velocities/vc-kts") == pytest.approx(250.0, abs=0.5)


def test_heading_survives_sideslip(fdm):
    """Regression for the ic/beta-deg clobber.

    Setting sideslip re-derives the velocity vector's orientation and resets
    true heading to zero, so sideslip must be applied before heading. Requested
    heading 270 silently became 000.
    """
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(4500), "vc-kts": 280, "psi-true-deg": 270.0,
         "beta-deg": 0.0, "phi-deg": 0.0, "gamma-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
    )
    assert fdm.props.get("attitude/psi-deg") == pytest.approx(270.0, abs=0.5)


def test_every_initial_condition_is_achieved_simultaneously(fdm):
    """The ordering is verified as a whole rather than reasoned about.

    Each field is set to a distinct non-default value, so any pair that
    interferes shows up here rather than in whichever scenario happens to
    trigger it months later.
    """
    wanted = {
        "lat-geod-deg": 47.0, "long-gc-deg": 8.0, "terrain-elevation-ft": 1000.0,
        "h-sl-ft": u.m_to_ft(4500), "phi-deg": 0.0, "beta-deg": 0.0,
        "psi-true-deg": 270.0, "gamma-deg": 0.0, "vc-kts": 280.0,
    }
    fdm.set_initial_conditions(wanted)
    achieved = {
        "lat-geod-deg": "position/lat-geod-deg",
        "long-gc-deg": "position/long-gc-deg",
        "terrain-elevation-ft": "position/terrain-elevation-asl-ft",
        "h-sl-ft": "position/h-sl-ft", "phi-deg": "attitude/phi-deg",
        "beta-deg": "aero/beta-deg", "psi-true-deg": "attitude/psi-deg",
        "gamma-deg": "flight-path/gamma-deg", "vc-kts": "velocities/vc-kts",
    }
    for key, prop in achieved.items():
        assert fdm.props.get(prop) == pytest.approx(
            wanted[key], rel=1e-3, abs=1e-3
        ), f"{key} was not achieved"


def test_unachievable_initial_condition_is_rejected(fdm):
    """The post-condition check must fire, not just the ordering fix.

    Ordering alone would rot the moment a new IC key is added.
    """
    with pytest.raises(SimulationError) as exc:
        # h-agl and h-sl cannot both be satisfied over terrain at 5000 ft.
        fdm.set_initial_conditions(
            {"h-sl-ft": 10000.0, "terrain-elevation-ft": 5000.0,
             "h-agl-ft": 10000.0, "vc-kts": 250.0,
             **{k: v for k, v in LEVEL.items() if k != "terrain-elevation-ft"}}
        )
    assert "did not take" in str(exc.value)


def test_typo_in_initial_condition_is_rejected(fdm):
    from core.fdm import UnknownPropertyError

    with pytest.raises(UnknownPropertyError):
        fdm.set_initial_conditions({"h-sl-feet": 10000.0})   # feet, not ft
