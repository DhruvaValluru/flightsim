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


# -- physics <-> visual model sync ---------------------------------------

def test_committed_fdm_files_match_the_model_cfg():
    """The A4 physics is generated from the model's aircraft.cfg; a hand edit
    of either side that breaks the link fails here (regenerate with
    ``python -m assets_pipeline.a4_sync``)."""
    from assets_pipeline import a4_sync

    assert a4_sync.main(["--check"]) == 0


def test_a4_is_the_repo_airframe_not_the_stock_one():
    fdm = FlightDynamics("A4")
    assert fdm.model.root_dir.name == "fdm_root"


def test_a4_geometry_and_mass_come_from_the_model_cfg():
    from assets_pipeline import a4_sync

    cfg = a4_sync.read_cfg()
    fdm = FlightDynamics("A4")
    g = fdm.props.get
    assert abs(g("metrics/bw-ft") - cfg["span_ft"]) < 1e-6
    assert abs(g("metrics/Sw-sqft") - cfg["area_ft2"]) < 1e-6
    fdm.set_initial_conditions({"h-agl-ft": 7.0, "vc-kts": 0,
                                "terrain-elevation-ft": 0})
    internal_fuel = sum(cfg["tanks"][k][3] for k in ("Center1", "Center2")) \
        * a4_sync.JET_A_LB_PER_GAL
    assert abs(g("inertia/empty-weight-lbs") - cfg["empty_lb"]) < 1.0
    assert abs(g("inertia/weight-lbs") - cfg["empty_lb"] - internal_fuel) < 2.0


def test_a4_rests_on_its_gear_at_the_models_static_attitude():
    """Independent of how the gear was generated: the cfg states the airplane
    sits at 5 deg pitch with its CG 7 ft up. The generated gear must land
    there, which only holds if the frame conversion is right."""
    fdm = FlightDynamics("A4")
    fdm.set_initial_conditions({"h-agl-ft": 7.0, "vc-kts": 0,
                                "terrain-elevation-ft": 0})
    fdm.run_for(8.0)
    g = fdm.props.get
    assert abs(g("attitude/theta-deg") - 5.0) < 1.0
    assert abs(g("position/h-agl-ft") - 7.0) < 1.0
    assert all(g(f"gear/unit[{i}]/WOW") == 1.0 for i in range(3))
