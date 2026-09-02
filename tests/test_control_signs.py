"""Package B: the control-sign probe flies a state the airframe can hold.

Before: signs.measure() probed at a hardcoded 6000 m / 280 kt CAS. The
c172p trims fine with TECS attached (600 m / 85 kt, 1200 m / 100 kt,
300 m / 75 kt through configure_from_spec) and then failed inside
engage() every time, because the probe could not trim a Cessna at a
transport cruise. The autopilot was unreachable for the general-aviation
airframe, for any spec.
"""

import pytest

from core.control import signs as signs_module
from core.control.autopilot import Autopilot
from core.control.signs import ControlSignError
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.scenario.runner import configure_from_spec


@pytest.fixture(autouse=True)
def fresh_sign_cache(monkeypatch):
    monkeypatch.setattr(signs_module, "_CACHE", {})


def test_the_c172p_engages_and_flies_a_step():
    """The airframe the old probe excluded, flying closed loop."""
    spec = compile_prompt("fly the c172p at 600 m and 85 kt for 10 seconds")
    fdm = configure_from_spec(spec)
    fdm.hold_mass(True)
    ap = Autopilot(fdm)
    ap.engage()                                  # used to raise TrimFailureError
    assert ap.signs.aircraft == "c172p"
    for _ in range(600):
        fdm.step()
    ap.command(altitude_m=700.0)
    hs = []
    for i in range(60 * 120):
        fdm.step()
        if i % 60 == 0:
            ap.update()
        if i % 12 == 0:
            hs.append(u.ft_to_m(fdm.props.get("position/h-sl-ft")))
    assert max(hs) > 690.0                      # it climbed most of the way
    assert abs(hs[-1] - 700.0) < 15.0           # and is holding near the target


def test_engage_probes_at_the_aircrafts_own_state(monkeypatch):
    calls = []
    real = signs_module.measure

    def spy(aircraft, altitude_m=6000.0, cas_kt=280.0, use_cache=True):
        calls.append((aircraft, altitude_m, cas_kt))
        return real(aircraft, altitude_m=altitude_m, cas_kt=cas_kt,
                    use_cache=use_cache)

    monkeypatch.setattr("core.control.signs.measure", spy)
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt for 10 seconds")
    fdm = configure_from_spec(spec)
    Autopilot(fdm).engage()
    assert calls, "engage() did not measure the signs"
    aircraft, altitude_m, cas_kt = calls[0]
    assert aircraft == "B747"
    assert altitude_m == pytest.approx(3000.0, abs=5.0)
    assert cas_kt == pytest.approx(250.0, abs=0.5)


def test_a_probe_that_cannot_trim_refuses_by_name():
    """The old failure mode, made honest: probing the c172p at the old
    transport condition names the condition and the constraint."""
    with pytest.raises(ControlSignError) as caught:
        signs_module.measure("c172p", altitude_m=6000.0, cas_kt=280.0,
                             use_cache=False)
    assert caught.value.constraint == "control.signs"
    assert "6000 m / 280 kt" in str(caught.value)


@pytest.mark.parametrize("aircraft,altitude_m,cas_kt", [
    ("B747", 3000.0, 250.0),
    ("A320", 3000.0, 250.0),
    ("c172p", 600.0, 85.0),
    ("DHC6", 1500.0, 120.0),
])
def test_every_flyable_configured_airframe_has_measurable_signs(
        aircraft, altitude_m, cas_kt):
    """Every airframe with a model config that this JSBSim build can trim
    is probed at a condition it can hold, and every sign is +/-1 -- never
    a coin flip."""
    signs = signs_module.measure(aircraft, altitude_m=altitude_m,
                                 cas_kt=cas_kt, use_cache=False)
    assert signs.aircraft == aircraft
    assert {signs.elevator, signs.aileron, signs.rudder} <= {1.0, -1.0}


def test_the_p51d_refuses_by_name_because_it_cannot_trim_at_all():
    """The stock p51d in the pinned JSBSim 1.2.4 does not trim at any
    airborne condition tried (500 m/150 kt through 3000 m/280 kt: "udot
    doesn't appear to be trimmable" every time -- measured, Package B).
    That is an airframe limitation, not the probe's, and the probe says
    so: a named control.signs refusal carrying the condition, never a
    guessed sign."""
    with pytest.raises(ControlSignError) as caught:
        signs_module.measure("p51d", altitude_m=1500.0, cas_kt=200.0,
                             use_cache=False)
    assert caught.value.constraint == "control.signs"
    assert "1500 m / 200 kt" in str(caught.value)


def test_the_convention_is_condition_independent():
    """The premise that makes any trimmable probe valid, checked rather
    than assumed: the B747's signs at 1500 m / 200 kt equal its signs at
    6000 m / 280 kt."""
    low = signs_module.measure("B747", altitude_m=1500.0, cas_kt=200.0,
                               use_cache=False)
    high = signs_module.measure("B747", altitude_m=6000.0, cas_kt=280.0,
                                use_cache=False)
    assert (low.elevator, low.aileron, low.rudder) == (
        high.elevator, high.aileron, high.rudder)
