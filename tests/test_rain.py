"""The rain provider (core/environment/rain.py): the water, the drops'
momentum, the wetted wing, the wet runway, the injection, the block.

Measured here on the c172p (JSBSim 1.2.4):

* the water closes on the stated rate: rho_w R = LWC v_m exactly;
* the drops' force reduces to its two textbook limits (level flight
  through rain that does not fall: LWC V^2 A_front against the motion; an
  aircraft at rest: the rain's weight-flux rho_w R v_m A_plan straight down);
* the 14 CFR 25.109 curves fall with speed and interpolate in pressure;
* the rain injection at neutral values flies bit-identically to the stock
  airframe, and every property it declares reads back to the last bit;
* a full-brake stop from 55 kt is longer wet than dry and longer again on
  standing water above the hydroplaning speed;
* the default block adds nothing (the committed examples keep their
  digests), and a stated block runs end to end with its records.
"""

from __future__ import annotations

import contextlib
import copy
import io
import math
from pathlib import Path

import pytest

from core.control.derive import INJECTION_ORDER, derive
from core.environment import rain as rn
from core.environment.rain import (
    CARD_KEYS, PROPERTY_DRAG, PROPERTY_FRICTION, PROPERTY_LIFT, PROPERTY_MAGNITUDE,
    TELEMETRY_COLUMNS, RainProvider, Stated, friction_factor, hydroplaning_speed_kt,
    momentum_force_body, rain_injections_for, roughness_factors, water, wet_mu,
)
from core.environment.stack import EnvironmentStack
from core.fdm.fdm import FlightDynamics
from core.nl.compiler import compile_prompt
from core.scenario.blocks import RainSpec
from core.scenario.runner import run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate_rain

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def spec_for(rate=None, seconds=3, aircraft="c172p", **rain) -> ScenarioSpec:
    spec = compile_prompt(f"fly the {aircraft} at 1500 m and 100 kt for {seconds} seconds")
    spec.set("hold_state", False, frm="test")
    if rate is not None:
        spec.set("precipitation_rate_mmh", rate, frm="test")
    for name, value in rain.items():
        spec.set(f"rain.{name}", value, frm="test")
    return spec


# -- the water -------------------------------------------------------------------

@pytest.mark.parametrize("rate", [1.0, 50.0, 300.0, 1800.0])
def test_water_closes_on_the_rate(rate):
    w = water(rate)
    # rho_w R (kg m^-2 s^-1) = LWC (kg m^-3) v_m (m/s), by construction and exactly.
    assert rn.RHO_WATER * rate / 3.6e6 == pytest.approx(w["lwc_g_m3"] * 1e-3 * w["fall_speed_mps"],
                                                       rel=1e-12)
    assert 2.0 < w["fall_speed_mps"] < 9.65


def test_water_values_at_50_mmh():
    w = water(50.0)
    assert 2.0 < w["lwc_g_m3"] < 2.8
    assert 5.5 < w["fall_speed_mps"] < 7.0
    assert water(300.0)["lwc_g_m3"] > 5 * w["lwc_g_m3"]


def test_roughness_factors_linear_then_held():
    half = roughness_factors(rn.LWC_REF_G_M3 / 2, 0.2, 0.4)
    assert half["lift"] == pytest.approx(0.9) and half["drag"] == pytest.approx(1.2)
    beyond = roughness_factors(rn.LWC_REF_G_M3 * 3, 0.2, 0.4)
    assert beyond["phi"] == 1.0 and beyond["lift"] == pytest.approx(0.8)
    assert roughness_factors(0.0, 0.2, 0.4) == {"phi": 0.0, "lift": 1.0, "drag": 1.0}


# -- the drops' momentum ------------------------------------------------------------

def test_momentum_level_flight_through_rain_that_does_not_fall():
    lwc, v, a_front = 5.0, 60.0, 3.8
    fx, fy, fz = momentum_force_body(lwc, 0.0, (v, 0.0, 0.0), 0.0, 0.0, a_front, 16.0)
    assert fx == pytest.approx(-lwc * 1e-3 * v * v * a_front, rel=1e-12)
    assert fy == 0.0 and fz == 0.0


def test_momentum_at_rest_is_the_rains_weight_flux():
    rate = 100.0
    w = water(rate)
    plan = 16.0
    fx, fy, fz = momentum_force_body(w["lwc_g_m3"], w["fall_speed_mps"], (0.0, 0.0, 0.0),
                                     0.0, 0.0, 3.8, plan)
    flux = rn.RHO_WATER * rate / 3.6e6
    assert fz == pytest.approx(flux * w["fall_speed_mps"] * plan, rel=1e-12)
    assert abs(fx) < 1e-15 and abs(fy) < 1e-15


def test_momentum_in_flight_is_drag_and_down():
    w = water(300.0)
    fx, _, fz = momentum_force_body(w["lwc_g_m3"], w["fall_speed_mps"], (60.0, 0.0, 3.0),
                                    0.0, math.radians(3.0), 3.8, 16.2)
    assert fx < -100.0          # opposes the motion: about LWC V^2 A_front + LWC V v_m A_plan
    assert fz > 0.0             # the falling water pushes the wing down


# -- the runway ---------------------------------------------------------------------

def test_wet_mu_matches_the_rule_at_its_anchors():
    assert wet_mu(0.0, 50.0) == pytest.approx(0.883)
    assert wet_mu(0.0, 300.0) == pytest.approx(0.614)
    assert wet_mu(100.0, 100.0) == pytest.approx(-0.0437 + 0.320 - 0.805 + 0.804)
    assert wet_mu(0.0, 75.0) == pytest.approx((0.883 + 0.804) / 2)
    assert wet_mu(0.0, 20.0) == wet_mu(0.0, 50.0)          # clamped to the 50 psi curve
    assert wet_mu(250.0, 100.0) == wet_mu(200.0, 100.0)    # clamped at 200 kt


@pytest.mark.parametrize("psi", [50.0, 100.0, 150.0, 200.0, 300.0])
def test_wet_mu_falls_with_speed(psi):
    values = [wet_mu(v, psi) for v in range(0, 201, 5)]
    assert all(a > b for a, b in zip(values, values[1:]))
    assert values[-1] > 0.0


def test_friction_factor_words():
    assert friction_factor("dry", 80.0, None, 0.8) == 1.0
    assert friction_factor("wet", 0.0, 29.0, 0.8) == 1.0          # never better than dry
    assert friction_factor("wet", 60.0, 29.0, 0.8) == pytest.approx(wet_mu(60.0, 29.0) / 0.8)
    vp = hydroplaning_speed_kt(29.0)
    assert vp == pytest.approx(9.0 * math.sqrt(29.0))
    assert friction_factor("standing_water", vp - 1.0, 29.0, 0.8) == pytest.approx(
        wet_mu(vp - 1.0, 29.0) / 0.8)
    assert friction_factor("standing_water", vp + 1.0, 29.0, 0.8) == pytest.approx(0.05 / 0.8)


# -- the injection ---------------------------------------------------------------------

def test_rain_is_last_in_the_pipeline_and_names_its_derivation(tmp_path):
    assert INJECTION_ORDER[-1] == "rain"
    derived = derive("c172p", build_dir=tmp_path, injections=("rain",))
    assert derived.name == "c172p-rain"
    text = derived.xml_path.read_text(encoding="utf-8")
    assert text.count("<property>rain/lift-factor</property>") >= 1
    assert text.count("<property>rain/drag-factor</property>") >= 1
    assert text.count('<force name="rain-momentum" frame="BODY">') == 1
    # Beside icing, both factors wrap the same axis (the products nest).
    both = derive("c172p", build_dir=tmp_path, injections=("icing", "rain"))
    assert both.name == "c172p-ice-rain"


def _fly(fdm, seconds=4.0):
    fdm.set_initial_conditions({"h-sl-ft": 5000.0, "vc-kts": 100.0, "theta-deg": 2.0,
                                "psi-true-deg": 0.0})
    fdm.props.set("fcs/throttle-cmd-norm", 0.7)
    out = []
    for _ in range(int(seconds * fdm.rate_hz)):
        fdm.step()
        out.append((fdm.props.get("position/h-sl-ft"), fdm.props.get("velocities/u-fps"),
                    fdm.props.get("attitude/theta-rad"), fdm.props.get("velocities/q-rad_sec")))
    return out


def test_neutral_injection_is_bit_identical_to_stock():
    stock = quiet(_fly, quiet(FlightDynamics, "c172p"))
    derived = quiet(_fly, quiet(FlightDynamics.with_injections, "c172p", ("rain",)))
    assert stock == derived


def test_injected_properties_move_the_aerodynamics_and_read_back():
    fdm = quiet(FlightDynamics.with_injections, "c172p", ("rain",))
    fdm.set_initial_conditions({"h-sl-ft": 5000.0, "vc-kts": 100.0, "psi-true-deg": 0.0})
    # The aerodynamics are recomputed by a re-latch (icing's measured rule);
    # a re-latch repeats to about 1e-3 (the alpha-dot and q terms move with
    # it, measured: the factor written back to 1.0 reads 0.99998), so the
    # ratios are held to 3e-3.
    fdm.relatch_initial_conditions()
    lift0 = fdm.props.get("forces/fwz-aero-lbs")
    drag0 = fdm.props.get("forces/fwx-aero-lbs")
    fx0 = fdm.props.get("forces/fbx-total-lbs")
    writes = {PROPERTY_LIFT: 0.9, PROPERTY_DRAG: 1.2, PROPERTY_MAGNITUDE: 50.0,
              "external_reactions/rain-momentum/x": -1.0,
              "external_reactions/rain-momentum/y": 0.0,
              "external_reactions/rain-momentum/z": 0.0}
    fdm.props.set_many(writes)
    fdm.relatch_initial_conditions()
    assert lift0 > 0.0 and drag0 > 0.0
    assert fdm.props.get("forces/fwz-aero-lbs") == pytest.approx(0.9 * lift0, rel=3e-3)
    assert fdm.props.get("forces/fwx-aero-lbs") == pytest.approx(1.2 * drag0, rel=3e-3)
    fdm.step()
    for prop, value in writes.items():
        assert fdm.props.get(prop) == value
    # The force is in the body totals (the aero drag rose too, so only a bound).
    assert fdm.props.get("forces/fbx-total-lbs") < fx0 - 50.0 + 1.0


# -- the runway, measured: full brakes from 55 kt -----------------------------------------

def _stop(condition, tire_psi=29.0):
    fdm = quiet(FlightDynamics, "c172p")
    fdm.set_initial_conditions({"h-agl-ft": 0.0, "theta-deg": 0.0, "psi-true-deg": 0.0,
                                "vg-kts": 55.0})
    effective = {"aerodynamics": Stated(False), "runway_condition": Stated(condition),
                 "lift_loss_at_ref": Stated(0.15, "default"),
                 "drag_rise_at_ref": Stated(0.30, "default"),
                 "tire_pressure_psi": Stated(tire_psi)}
    provider = RainProvider("c172p", None, effective, rate_hz=fdm.rate_hz)
    stack = EnvironmentStack([provider])
    stack.prepare(fdm)
    fdm.props.set_many({"fcs/throttle-cmd-norm": 0.0, "fcs/left-brake-cmd-norm": 1.0,
                        "fcs/right-brake-cmd-norm": 1.0})
    steps = 0
    while fdm.props.get("velocities/vg-fps") > 1.0 and steps < 60 * int(fdm.rate_hz):
        stack.apply(fdm)
        fdm.step()
        steps += 1
    stack.apply(fdm)            # one more observe: the last write is read back
    return fdm.props.get("position/distance-from-start-mag-mt"), provider


def test_wet_and_standing_water_stop_longer_than_dry():
    dry, p_dry = _stop("dry")
    wet, p_wet = _stop("wet")
    flooded, p_flooded = _stop("standing_water")
    assert dry < wet < flooded
    assert wet > 1.15 * dry
    assert p_dry.peaks["min_friction_factor"] == 1.0
    assert p_wet.peaks["min_friction_factor"] < 1.0
    # 29 psi hydroplanes above 9 sqrt(29) = 48.5 kt: the first seconds at 55 kt.
    assert p_flooded.peaks["steps_hydroplaning"] > 0
    assert p_wet.peaks["steps_hydroplaning"] == 0
    for provider in (p_dry, p_wet, p_flooded):
        assert all(e == 0.0 for e in provider.readback["max_abs_error"].values())


# -- the block ---------------------------------------------------------------------------

def test_default_block_is_absent_canonical():
    spec = spec_for(rate=10.0)
    assert spec.rain.is_default()
    assert "rain" not in spec.to_dict()
    assert rain_injections_for(spec) == ()
    assert RainProvider.from_spec(spec) is None
    assert validate_rain(spec) == []


def test_committed_examples_do_not_gain_the_block():
    for path in sorted(EXAMPLES.glob("*.yaml")):
        try:
            spec = ScenarioSpec.read(path)
        except Exception:
            continue
        assert "rain" not in spec.to_dict(), path.name


def test_stated_block_round_trips():
    spec = spec_for(rate=80.0, runway_condition="standing_water", lift_loss_at_ref=0.2)
    data = spec.to_dict()
    assert data["rain"]["runway_condition"]["value"] == "standing_water"
    again = ScenarioSpec.from_dict(copy.deepcopy(data))
    assert again.rain.to_dict() == spec.rain.to_dict()
    assert rain_injections_for(again) == ("rain",)


def test_runway_only_block_flies_the_stock_airframe():
    spec = spec_for(aerodynamics=False, runway_condition="wet")
    assert rain_injections_for(spec) == ()
    assert validate_rain(spec) == []
    provider = RainProvider.from_spec(spec)
    assert provider.runway_condition == "wet" and provider.tire_pressure_psi == 29.0


@pytest.mark.parametrize("kwargs, constraint", [
    ({"aerodynamics": True}, "rain.rate_missing"),
    ({"rate": 10.0, "runway_condition": "icy"}, "rain.runway_condition"),
    ({"rate": 10.0, "lift_loss_at_ref": 0.9}, "rain.factor_range"),
    ({"rate": 10.0, "drag_rise_at_ref": -0.1}, "rain.factor_range"),
    ({"rate": 10.0, "frontal_area_m2": -1.0}, "rain.airframe_data"),
])
def test_refusals_by_name(kwargs, constraint):
    rate = kwargs.pop("rate", None)
    spec = spec_for(rate=rate, **kwargs)
    names = [v.constraint for v in validate_rain(spec)]
    assert constraint in names
    with pytest.raises(rn.RainError) as excinfo:
        RainProvider.from_spec(spec)
    assert excinfo.value.constraint in names


def test_airframe_without_data_refuses_by_name():
    spec = spec_for(rate=10.0, aircraft="A320", aerodynamics=True)
    assert "rain.airframe_data" in [v.constraint for v in validate_rain(spec)]
    stated = spec_for(rate=10.0, aircraft="A320", frontal_area_m2=20.0, tire_pressure_psi=200.0)
    assert validate_rain(stated) == []


def test_rate_implies_a_wet_runway():
    provider = RainProvider.from_spec(spec_for(rate=20.0, aerodynamics=True))
    assert provider.runway_condition == "wet"
    assert provider.effective["runway_condition"].source == "derived"
    assert tuple(provider.card_block()) == CARD_KEYS


# -- end to end ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runs():
    dry = quiet(run_spec, spec_for(rate=300.0, seconds=10))
    wet = quiet(run_spec, spec_for(rate=300.0, seconds=10, aerodynamics=True))
    return dry, wet


def test_run_records_and_reads_back(runs):
    _, wet = runs
    manifest = wet.manifest
    assert manifest["rain"]["applied"] is True
    assert manifest["rain"]["per_step_readback"]["agrees"] is True
    names = [r["name"] for r in manifest["applied_variables"]["applied_variables"]]
    assert "rain.aerodynamics" in names and "rain.runway_condition" in names
    assert manifest["rain"]["prepared"]["derived_aircraft"] == "c172p-rain"
    assert manifest["rain"]["prepared"]["with_factors"]["drag_n"] > \
        manifest["rain"]["prepared"]["baseline"]["drag_n"] > 0.0
    for column in TELEMETRY_COLUMNS:
        assert len(wet.telemetry.series(column)) == len(wet.telemetry)


def test_run_without_block_is_untouched(runs):
    dry, _ = runs
    assert dry.manifest["rain"] is None
    assert "rain_lwc_gm3" not in dry.telemetry.to_dict().get("channels", {})
    with pytest.raises(Exception):
        dry.telemetry.series("rain_lwc_gm3")


def test_heavy_rain_costs_energy(runs):
    dry, wet = runs
    # Same trim, same controls: the rain's drag and lost lift take energy out.
    def energy(run):
        h = run.telemetry.series("altitude_m")[-1]
        v = run.telemetry.series("tas_kt")[-1] * 0.514444
        return 9.80665 * h + 0.5 * v * v
    assert energy(wet) < energy(dry) - 50.0
    drag = wet.telemetry.series("rain_momentum_drag_n")
    assert min(drag[1:]) > 100.0
