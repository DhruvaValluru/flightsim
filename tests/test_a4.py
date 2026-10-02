"""The A4 airframe: reachable by name, generated from its visual model's cfg,
and subject to the same wind stack as every other airframe.

The physics is generated from the A-4E model's aircraft.cfg
(assets_pipeline/a4_sync.py) and checked against the decoded mesh
(test_a4_mesh.py); see docs/A4_SYNC.md.
"""

import pytest

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
    pilot = cfg["stations"][0][0]
    assert abs(g("inertia/weight-lbs") - cfg["empty_lb"] - internal_fuel
               - pilot) < 2.0


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


# -- mesh <-> physics ------------------------------------------------------

def test_mesh_extents_match_the_flight_models_contact_points():
    """The decoded .mdl geometry against the FDM's own contact points.

    Wingtip, tail top, tail end and main-gear bottom agree to about an inch;
    the nose differs by the fixed refuelling probe, which the cfg's nose
    scrape point leaves out."""
    from assets_pipeline import a4_mesh_check as mc

    m, r = mc.measure(), mc.fdm_reference()
    for key in ("half_span_ft", "top_ft", "tail_end_ft", "bottom_ft"):
        assert abs(m[key] - r[key]) < 0.2, (key, m[key], r[key])
    assert 0.0 < m["nose_ft"] - r["nose_ft"] < 3.5   # the probe


def test_mesh_wing_agrees_with_the_flight_models_reference_geometry():
    from assets_pipeline import a4_mesh_check as mc

    m = mc.measure()
    fdm = FlightDynamics("A4")
    area = fdm.props.get("metrics/Sw-sqft")
    # planform from the wing surface hull (includes the root fairing)
    assert abs(m["wing_area_ft2"] - area) / area < 0.05
    # the aerodynamic reference point (AERORP) sits at the datum/CG; the
    # mesh quarter-MAC must be within a foot of it
    assert abs(m["wing_ac_long_ft"]) < 1.0


# -- configuration and performance -----------------------------------------

def test_a4_starts_airborne_with_gear_up_but_stock_aircraft_are_untouched():
    a4 = FlightDynamics("A4")
    a4.set_initial_conditions({"h-sl-ft": 10000.0, "vc-kts": 350.0})
    assert a4.props.get("gear/gear-pos-norm") == 0.0
    assert a4.props.get("gear/gear-cmd-norm") == 0.0

    stock = FlightDynamics("f16")
    stock.set_initial_conditions({"h-sl-ft": 10000.0, "vc-kts": 350.0})
    assert stock.props.get("gear/gear-pos-norm") == 1.0   # JSBSim default

    ground = FlightDynamics("A4")
    ground.set_initial_conditions({"h-agl-ft": 7.0, "vc-kts": 0,
                                   "terrain-elevation-ft": 0})
    assert ground.props.get("gear/gear-pos-norm") == 1.0


def test_a4_reaches_its_published_maximum_speed():
    """aircraft.cfg quotes 585 kn. Clean and level at 1000 ft the model
    trims at 550 kt CAS below full throttle and runs out of thrust before
    620 kt, so its top speed is the published one to within a few percent.
    (Measured 2026-09-30: 585 kt trims at 0.96 throttle; 620 does not.)"""

    def trimmed_throttle(kt):
        fdm = FlightDynamics("A4")
        fdm.set_initial_conditions({"h-sl-ft": 1000.0, "vc-kts": kt,
                                    "gamma-deg": 0.0})
        fdm.start_engines()
        fdm.trim()
        return fdm.props.get("fcs/throttle-cmd-norm")

    assert trimmed_throttle(550.0) < 0.95
    try:
        trimmed_throttle(620.0)
    except Exception:
        return
    raise AssertionError("A4 trims at 620 kt CAS: faster than published")


# -- flaps, hook, stores ----------------------------------------------------

def test_flaps_travel_to_the_cfgs_fifty_degrees():
    fdm = FlightDynamics("A4")
    fdm.set_initial_conditions({"h-sl-ft": 10000.0, "vc-kts": 250.0})
    fdm.start_engines()
    reached = {}
    for cmd in (0.5, 1.0, 0.0):
        fdm.props.set("fcs/flap-cmd-norm", cmd)
        fdm.run_for(4.0)
        reached[cmd] = fdm.props.get("fcs/flap-pos-deg")
    assert reached == {0.5: 25.0, 1.0: 50.0, 0.0: 0.0}


def test_tail_hook_arrests_only_when_down_engaged_and_on_the_deck():
    def roll_out(hook_down, wire):
        fdm = FlightDynamics("A4")
        fdm.set_initial_conditions({"h-agl-ft": 7.0, "vc-kts": 120,
                                    "terrain-elevation-ft": 0})
        fdm.props.set("systems/hook/tailhook-cmd-norm",
                      1.0 if hook_down else 0.0)
        fdm.run_for(2.0)
        fdm.props.set("systems/hook/wire-engaged", 1.0 if wire else 0.0)
        fdm.run_for(3.0)
        return fdm.props.get("velocities/vc-kts")

    free = roll_out(False, False)
    assert roll_out(True, False) == pytest.approx(free, abs=0.5)   # no wire
    assert roll_out(False, True) == pytest.approx(free, abs=0.5)   # hook up
    assert roll_out(True, True) < 0.25 * free                      # arrested


def test_pylon_stores_add_weight_and_drag_and_the_clean_airframe_has_none():
    fdm = FlightDynamics("A4")
    fdm.set_initial_conditions({"h-sl-ft": 10000.0, "vc-kts": 350.0})
    from assets_pipeline import a4_sync

    g = fdm.props.get
    clean = g("inertia/weight-lbs")
    fdm.start_engines()
    fdm.run_for(0.1)
    assert g("stores/drag-area-ft2") == 0.0
    fdm.props.set("inertia/pointmass-weight-lbs[3]", 2000.0)
    fdm.run_for(0.1)
    assert g("inertia/weight-lbs") == pytest.approx(clean + 2000.0, abs=1.0)
    assert g("stores/drag-area-ft2") == pytest.approx(
        2000.0 * a4_sync.STORES_DRAG_FT2_PER_LB, rel=1e-3)


def test_a4_climb_and_ceiling_match_the_published_figures(monkeypatch):
    """cfg text: 8,440 ft/min and a 42,250 ft service ceiling at the 18,300 lb
    loaded weight. Fitted (assets_pipeline/a4_calibrate.py) with a stores drag
    constant and the Oswald efficiency; this pins the result. The ceiling is
    bracketed rather than solved for, to keep the test quick."""
    from assets_pipeline import a4_performance as perf

    speed, roc = perf.best_rate_of_climb(500.0)
    assert abs(roc - 8440.0) / 8440.0 < 0.05
    monkeypatch.setattr(perf, "SPEEDS_KT", (170, 200, 250))
    assert perf._roc_at(40500.0, perf.REFERENCE_GROSS_LB) > 100.0
    assert perf._roc_at(44000.0, perf.REFERENCE_GROSS_LB) < 100.0
