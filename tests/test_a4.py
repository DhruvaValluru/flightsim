"""The A4 airframe is reachable by name and feels the wind stack.

The visual model (assets/aircraft_models/A4) is a P3D .mdl that is not yet
rendered; the physics is the JSBSim A4 and must respond to wind exactly as
every other airframe does -- the environment stack is airframe-agnostic and
this pins that for the A4.
"""

from core.fdm import FlightDynamics
from core.nl.compiler import compile_prompt
from core.scenario.runner import run_spec


def test_a4_is_named_not_substituted():
    for word in ("A4", "A-4", "Skyhawk"):
        spec = compile_prompt(f"fly the {word} at 3000 m and 350 kt for 10 seconds")
        assert str(spec.aircraft.value) == "A4"


def test_a4_default_cruise_is_a_fighter_speed():
    spec = compile_prompt("fly the A4 at 3000 m for 10 seconds")
    assert float(spec.airspeed.value) == 350.0


def test_a4_receives_steady_wind_and_turbulence():
    calm = compile_prompt("fly the A4 at 3000 m and 350 kt for 20 seconds")
    windy = compile_prompt(
        "fly the A4 at 3000 m and 350 kt in a 25 kt crosswind from the east "
        "for 20 seconds")
    rough = compile_prompt(
        "fly the A4 at 3000 m and 350 kt in moderate turbulence for 20 seconds")
    base = run_spec(calm).output_digest
    assert run_spec(windy).output_digest != base
    assert run_spec(rough, assert_closure=False).output_digest != base


def test_a4_total_wind_matches_the_commanded_wind():
    fdm = FlightDynamics("A4")
    fdm.set_initial_conditions({"h-sl-ft": 10000.0, "vc-kts": 350.0})
    fdm.props.set_many({"atmosphere/wind-east-fps": -25.0 * 1.68781,
                        "atmosphere/wind-north-fps": 0.0,
                        "atmosphere/wind-down-fps": 0.0})
    fdm.start_engines()
    fdm.run_for(1.0)
    s = fdm.state()
    assert abs(s.wind_east_mps + 25.0 * 0.514444) < 0.5
