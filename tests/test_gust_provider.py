"""P6, the gust provider and the stack (core/environment/base.py,
stack.py) with the von Karman field on a real c172p: the gust channel
equals the summed contributions and persists only while written (V20),
the stack writes zero every step, the equivalent roll rate is delivered
where the derived airframe declares it and recorded absent where not,
the records carry the read-back, the null pairs measure vK against none
and against Dryden, and the card table equals the run's.

Every number asserted here was measured in the container on 2026-09-28
(JSBSim 1.2.4 in .venv, c172p at 1500 m / 100 kt, 120 Hz, seed 7). What
is NOT claimed: that the Dryden channel's delivered std equals the ladder
(it does not; measured and said so), the engine side, the aircraft's
response as a validated one.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.environment.base import GustProvider, OwnShipState, Position, WindNED
from core.environment.stack import (
    GUST_PROPERTIES, P_EQUIVALENT_PROPERTY, STACK_CHANNELS, EnvironmentStack,
)
from core.environment.turbulence import DrydenTurbulence
from core.environment.von_karman import TELEMETRY_COLUMNS, VonKarmanTurbulence
from core.environment.wind import SteadyWind
from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.record_null import run_null_pair
from core.records import read_records
from core.registry import REGISTRY
from core.scenario.blocks import TURBULENCE_MODELS, TurbulenceModelSpec, WindProfileSpec
from core.scenario.card import gust_table_card_block, write_run_card
from core.scenario.runner import UnimplementedConditionError, environment_for, run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_turbulence_model
from core.telemetry.recorder import DEFAULT_CHANNELS

REPO = Path(__file__).resolve().parents[1]
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}


def trimmed(fdm=None, altitude_m=1500.0, cas_kt=100.0) -> FlightDynamics:
    fdm = fdm or FlightDynamics("c172p")
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL})
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    return fdm


def spec_for(text="fly the c172p at 1500 m and 100 kt for 3 seconds with moderate turbulence",
             **fields) -> ScenarioSpec:
    spec = compile_prompt(text)
    spec.set("hold_state", False, frm="test")
    for name, value in fields.items():
        spec.set(f"turbulence_model.{name}", value, frm="test")
    return spec


class Constant(GustProvider):
    """A gust of a constant vector, for the summing and persistence tests."""

    name = "constant_gust"

    def __init__(self, north=0.0, east=0.0, down=0.0, p=0.0) -> None:
        self.vector = WindNED(north, east, down)
        self.p = p

    def gust_at(self, own_ship, time_s):
        return self.vector

    def p_equivalent_at(self, own_ship, time_s):
        return self.p

    def vocabulary(self):
        return []


def names(violations):
    return [v.constraint for v in violations]


# -- the contract -------------------------------------------------------------------------

def test_the_gust_provider_defaults_and_the_own_ship_state():
    class Silent(GustProvider):
        name = "silent"

        def vocabulary(self):
            return []

    own = OwnShipState(Position(0.0, 0.0, 1500.0, 1500.0, 0.0), 1.0, 2.0, 3.0, 4.0, 5.0, 6.0,
                       10.9, 55.0)
    assert Silent().gust_at(own, 0.0) == WindNED() and Silent().p_equivalent_at(own, 0.0) == 0.0
    assert own.span_m == 10.9 and own.tas_mps == 55.0 and own.heading_deg == 6.0
    stack = EnvironmentStack([Constant(1.0), SteadyWind(5.0, 270.0), DrydenTurbulence("none")])
    assert [type(p).__name__ for p in stack.providers] == ["SteadyWind", "DrydenTurbulence", "Constant"]
    assert len(stack.gust) == 1 and len(stack) == 3
    with pytest.raises(TypeError):
        stack.add(object())


def test_own_ship_is_read_from_the_fdm_with_the_span():
    fdm = trimmed()
    own = EnvironmentStack().own_ship_of(fdm)
    assert own.span_m == pytest.approx(u.ft_to_m(35.8)) and own.tas_mps == pytest.approx(55.322, abs=1e-3)
    assert own.position.altitude_m == pytest.approx(1500.0, abs=0.01)
    assert own.heading_deg == pytest.approx(0.0, abs=1e-6) or own.heading_deg == pytest.approx(360.0, abs=1e-6)


# -- V20: the channel equals the sum and persists only while written ----------------------

def test_v20_the_gust_channel_equals_the_summed_contributions():
    """Two providers of 1 and 2 m/s north: the channel reads 3 m/s (in
    fps) after apply, and JSBSim's total wind carries it beside the base
    wind (wind + gust, measured to 1e-12 fps)."""
    fdm = trimmed()
    stack = EnvironmentStack([SteadyWind(4.0, 180.0), Constant(1.0, 0.5), Constant(2.0, -0.25, 0.75)])
    stack.configure(fdm)
    stack.apply(fdm)
    assert fdm.props.get("atmosphere/gust-north-fps") == pytest.approx(u.mps_to_fps(3.0))
    assert fdm.props.get("atmosphere/gust-east-fps") == pytest.approx(u.mps_to_fps(0.25))
    assert fdm.props.get("atmosphere/gust-down-fps") == pytest.approx(u.mps_to_fps(0.75))
    fdm.step()
    total = fdm.props.get("atmosphere/total-wind-north-fps")
    assert total == pytest.approx(u.mps_to_fps(4.0 + 3.0), abs=1e-9)
    assert fdm.state().gust_north_mps == pytest.approx(3.0)


def test_v20_the_channel_persists_only_while_written_so_the_stack_writes_zero_every_step():
    """7 fps written once reads 7.0 after 11 steps (the JSBSim fact); an
    apply of a stack with NO gust provider writes 0 and the channel reads
    0 -- the write-when-zero rule. A provider whose gust has passed
    (returns zero) is written as zero the same way."""
    fdm = trimmed()
    fdm.props.set("atmosphere/turb-type", 0.0)
    fdm.props.set("atmosphere/gust-north-fps", 7.0)
    for _ in range(11):
        fdm.step()
    assert fdm.props.get("atmosphere/gust-north-fps") == 7.0
    assert fdm.props.get("atmosphere/total-wind-north-fps") == pytest.approx(7.0, abs=1e-9)
    empty = EnvironmentStack()
    empty.configure(fdm)
    empty.apply(fdm)
    assert fdm.props.get("atmosphere/gust-north-fps") == 0.0
    fdm.step()
    assert fdm.props.get("atmosphere/gust-north-fps") == 0.0
    assert empty.delivery_report()["gust"]["steps_written"] == 1
    assert set(empty.delivery_report()["gust"]["final_write"]) == set(GUST_PROPERTIES)
    assert set(empty.delivery_report()["gust"]["final_write"].values()) == {0.0}
    # A provider that goes quiet: the last non-zero value does not linger.
    class Burst(GustProvider):
        name = "burst"
        calls = 0

        def gust_at(self, own_ship, time_s):
            self.calls += 1
            return WindNED(north=2.0) if self.calls == 1 else WindNED()

        def vocabulary(self):
            return []

    stack = EnvironmentStack([Burst()])
    stack.apply(fdm)
    assert fdm.props.get("atmosphere/gust-north-fps") == pytest.approx(u.mps_to_fps(2.0))
    fdm.step()
    stack.apply(fdm)
    assert fdm.props.get("atmosphere/gust-north-fps") == 0.0
    report = stack.delivery_report()["gust"]
    assert report["max_abs_error"]["atmosphere/gust-north-fps"] == 0.0 and report["steps_checked"] == 1


def test_the_stack_reads_each_gust_property_back_before_the_next_write():
    fdm = trimmed()
    stack = EnvironmentStack([Constant(1.5, -0.5, 0.25)])
    stack.configure(fdm)
    for _ in range(5):
        stack.apply(fdm)
        fdm.step()
    report = stack.delivery_report()["gust"]
    assert report["steps_written"] == 5 and report["steps_checked"] == 4
    assert report["max_abs_error"] == {p: 0.0 for p in GUST_PROPERTIES}
    assert report["last_read"]["atmosphere/gust-north-fps"] == pytest.approx(u.mps_to_fps(1.5))
    assert report["last_written"] == report["final_write"]
    assert report["channel_std_mps"] == pytest.approx({"north": 0.0, "east": 0.0, "down": 0.0}, abs=1e-12)
    assert report["p_equivalent"] == "absent" and report["providers"] == ["constant_gust"]


# -- the equivalent roll rate: property or absent ------------------------------------------

def test_p_equivalent_is_absent_on_a_stock_airframe_and_delivered_on_the_derived_one():
    """A stock c172p declares no gust/p-equivalent-rad_sec: the stack
    writes only the three gust properties and records ``absent``. The
    airframe derived with the gust_rotation injection declares it: the
    stack writes it every step (read back exact) and the roll response
    to the same table differs (measured after 3 s of the moderate seed-7
    field: -0.681 deg stock vs -0.402 deg derived)."""
    rolls = {}
    for label, fdm in (("stock", trimmed()),
                       ("derived", trimmed(FlightDynamics.with_injections("c172p", ("gust_rotation",))))):
        vk = VonKarmanTurbulence("moderate", seed=7, altitude_m=1500.0, duration_s=3.0, rate_hz=120.0)
        stack = EnvironmentStack([DrydenTurbulence("none"), vk])
        stack.prepare(fdm)
        stack.configure(fdm)
        stack.run_for(fdm, 3.0)
        report = stack.delivery_report()["gust"]
        rolls[label] = fdm.state().roll_deg
        if label == "stock":
            assert report["p_equivalent"] == "absent"
            assert P_EQUIVALENT_PROPERTY not in report["last_written"]
            assert fdm.state().gust_p_equivalent_rad_s == 0.0
            assert not fdm.props.has(P_EQUIVALENT_PROPERTY)
        else:
            assert report["p_equivalent"] == "property"
            assert P_EQUIVALENT_PROPERTY in report["last_written"]
            assert report["max_abs_error"][P_EQUIVALENT_PROPERTY] == 0.0
            assert fdm.state().gust_p_equivalent_rad_s == pytest.approx(vk.table[359][4])
        assert report["max_abs_error"]["atmosphere/gust-down-fps"] == 0.0
        assert vk.built["tas_mps"] == pytest.approx(55.322, abs=1e-3)
        record = vk.applied_variables(stack.delivery_report())[0]
        assert record.parameters["delivery"]["p_equivalent"] == report["p_equivalent"]
        assert (P_EQUIVALENT_PROPERTY in record.properties_written) == (label == "derived")
        assert any("absent" in n for n in record.not_claimed) == (label == "stock")
    assert rolls["stock"] == pytest.approx(-0.6808, abs=0.01)
    assert rolls["derived"] == pytest.approx(-0.4022, abs=0.01)
    assert abs(rolls["stock"] - rolls["derived"]) > 0.05


def test_the_table_is_built_before_the_trim_from_the_ic_true_airspeed_which_the_trim_keeps():
    """prepare(fdm) reads velocities/vtrue-kts at the initial conditions
    (107.537 kt); the longitudinal trim holds CAS, so the TAS after the
    trim is the same to 2.3e-13 kt (measured)."""
    fdm = FlightDynamics("c172p")
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(1500.0), "vc-kts": 100.0, **LEVEL})
    vk = VonKarmanTurbulence("moderate", seed=7, altitude_m=1500.0, duration_s=3.0, rate_hz=120.0)
    stack = EnvironmentStack([vk])
    report = stack.prepare(fdm)
    pre = fdm.props.get("velocities/vtrue-kts")
    assert report["von_karman_turbulence"]["tas_mps"] == pytest.approx(u.kt_to_mps(pre))
    assert report["von_karman_turbulence"]["basis"].startswith("the FDM's velocities/vtrue-kts")
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    assert fdm.props.get("velocities/vtrue-kts") == pytest.approx(pre, abs=1e-9)
    assert pre == pytest.approx(107.537484, abs=1e-5)


# -- the spec block, the validator, the runner ---------------------------------------------

def test_the_block_defaults_to_dryden_and_is_absent_canonical():
    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 3 seconds")
    assert spec.turbulence_model.is_default() and "turbulence_model" not in spec.to_dict()
    assert TurbulenceModelSpec.FIELD_ORDER == ("model", "intensity", "seed")
    assert TURBULENCE_MODELS == ("dryden", "von_karman")
    before = spec.digest()
    spec.set("turbulence_model.model", "von_karman")
    assert spec.digest() != before
    reread = ScenarioSpec.from_dict(json.loads(json.dumps(spec.to_dict())))
    assert reread.digest() == spec.digest()
    assert list(reread.to_dict()["turbulence_model"]) == list(TurbulenceModelSpec.FIELD_ORDER)
    for path, digest in {
        "examples/cameras_waypoint.yaml": "9760294005e1efcae1777ad4a2035fe3733d219428c477c6c7caf2f0220b2372",
        "examples/randomized.yaml": "102d38250e4b7c9b4b6737af5e3e2886fad0748aa4e7af825ce8388e4fe7fda1",
    }.items():
        assert ScenarioSpec.read(REPO / path).digest() == digest, path


def test_validation_refuses_turbulence_model_problems_by_name():
    assert names(validate_turbulence_model(spec_for())) == []
    assert names(validate_turbulence_model(spec_for(model="von_karman"))) == []
    assert names(validate_turbulence_model(spec_for(model="kaimal"))) == ["turbulence.model"]
    assert names(validate_turbulence_model(spec_for(model="von_karman", intensity="wild"))) == ["turbulence.model"]
    assert names(validate_turbulence_model(spec_for(model="von_karman", intensity=25.0))) == []
    assert names(validate_turbulence_model(spec_for(model="dryden", intensity=25.0))) == ["turbulence.model"]
    assert names(validate_turbulence_model(spec_for(model="dryden", intensity="severe"))) == []
    assert names(validate_turbulence_model(spec_for(model="von_karman", intensity=-3.0))) == ["turbulence.model"]
    assert names(validate_turbulence_model(spec_for(model="von_karman", seed=2 ** 31))) == ["turbulence.model"]
    assert names(validate_turbulence_model(spec_for(model="von_karman", seed=1.5))) == ["turbulence.model"]
    assert names(validate_turbulence_model(spec_for(model="von_karman", seed=12))) == []
    report = validate(spec_for(model="kaimal"), check_feasibility=False)
    assert "[turbulence.model]" in report.render()


def test_the_registry_claims_both_blocks_field_for_field_with_recorded_channels(vk_run):
    fields = ({f"turbulence_model.{f}" for f in TurbulenceModelSpec.FIELD_ORDER}
              | {f"wind_profile.{f}" for f in WindProfileSpec.FIELD_ORDER})
    assert fields <= set(REGISTRY.spec_fields())
    assert set(REGISTRY.sections()) >= {"turbulence_model", "wind_profile"}
    recorded = set(vk_run.telemetry.columns)
    for name in fields:
        entry = REGISTRY.get(name)
        missing = [c.name for c in entry.effect_channels if c.name not in recorded]
        assert missing == [], (name, missing)
    assert REGISTRY.get("turbulence_model.model").null_value == "dryden"
    assert set(TELEMETRY_COLUMNS) <= set(DEFAULT_CHANNELS)
    assert set(STACK_CHANNELS) <= recorded and not set(STACK_CHANNELS) & set(DEFAULT_CHANNELS)
    assert validate(spec_for(model="von_karman"), check_feasibility=False).ok


def test_environment_for_builds_the_von_karman_stack_with_dryden_off():
    stack = environment_for(spec_for(model="von_karman"))
    assert [type(p).__name__ for p in stack.providers] == ["DrydenTurbulence", "VonKarmanTurbulence"]
    assert stack.turbulence[0].intensity == "none" and stack.turbulence[0].model == 0
    vk = stack.gust[0]
    assert vk.word == "moderate" and vk.seed == int(spec_for().seed.value)
    assert vk.stated["model"]["value"] == "von_karman" and vk.stated["intensity"] is None
    stated = environment_for(spec_for(model="von_karman", intensity="severe", seed=5)).gust[0]
    assert stated.word == "severe" and stated.seed == 5
    assert stated.stated["intensity"]["value"] == "severe" and stated.stated["seed"]["value"] == 5
    none = environment_for(spec_for("fly the c172p at 1500 m and 100 kt for 3 seconds", model="von_karman"))
    assert none.gust == [] and none.turbulence[0].intensity == "none"
    dryden = environment_for(spec_for(intensity="light", seed=3)).turbulence[0]
    assert dryden.intensity == "light" and dryden.seed == 3
    with pytest.raises(UnimplementedConditionError):
        environment_for(spec_for(model="von_karman", intensity="wild"))


@pytest.fixture(scope="module")
def vk_run():
    return run_spec(spec_for(model="von_karman"))


@pytest.fixture(scope="module")
def dryden_run():
    return run_spec(spec_for())


def test_the_von_karman_run_records_the_gust_it_received(vk_run, dryden_run):
    """The gust channel as JSBSim holds it: std 2.187 / 2.177 / 2.174 m/s
    (n/e/d) read back at 120 Hz over the 3 s run against the commanded
    2.189 (the 10 Hz recorder's 31 samples give 2.10 / 2.18 / 2.18);
    every gust property reads back with 0.0 error on 359 of 360 steps;
    altitude moves within 1500 +- 0.6 m and roll to -10.05 deg; the
    Dryden run's gust channel is 0 everywhere; the digests differ."""
    cols = vk_run.telemetry.columns
    for column in TELEMETRY_COLUMNS:
        assert column in cols and len(cols[column]) == len(vk_run.telemetry)
    gust = np.array([cols["gust_north_mps"], cols["gust_east_mps"], cols["gust_down_mps"]])
    assert gust.std(axis=1) == pytest.approx([2.10, 2.18, 2.18], abs=0.05)
    assert max(abs(gust).max(axis=1)) < 4.0
    assert set(cols["gust_p_equivalent_rad_s"]) == {0.0}         # stock airframe: absent
    assert min(cols["roll_deg"]) == pytest.approx(-10.05, abs=0.1)
    assert max(abs(a - 1500.0) for a in cols["altitude_m"]) < 0.6
    for column in ("gust_north_mps", "gust_east_mps", "gust_down_mps"):
        assert set(dryden_run.telemetry.columns[column]) == {0.0}
    assert vk_run.output_digest != dryden_run.output_digest
    delivery = vk_run.manifest["environment_delivery"]["gust"]
    assert delivery["max_abs_error"] == {p: 0.0 for p in GUST_PROPERTIES}
    assert delivery["steps_written"] == 360 and delivery["steps_checked"] == 359
    assert delivery["p_equivalent"] == "absent"
    assert delivery["channel_std_mps"] == pytest.approx(
        {"north": 2.187, "east": 2.177, "down": 2.174}, abs=0.005)
    assert not any(p["name"] == "dryden_turbulence" and p["jsbsim_turb_type"] != 0
                   for p in vk_run.manifest["environment"])


def test_the_von_karman_run_returns_the_model_record_with_readback_and_null_test(vk_run):
    records = {r["name"]: r for r in read_records(vk_run.manifest["applied_variables"])}
    record = records["turbulence_model.model"]
    assert record["value"] == "von_karman" and record["source"] == "user" and record["unit"] == "word"
    assert record["properties_written"] == list(GUST_PROPERTIES)
    assert [w["property"] for w in record["jsbsim_writes"]] == list(GUST_PROPERTIES)
    assert all("every step, zero included" in w["when"] for w in record["jsbsim_writes"])
    assert record["readback"]["property"] == "atmosphere/gust-north-fps"
    assert record["readback"]["agrees"] and record["readback"]["tolerance"] == 0.0
    assert record["readback"]["value"] == record["readback"]["written"]
    null = record["null_test"]
    assert null["kind"] == "reached" and null["ok"] and null["unit"] == "m/s"
    assert null["with"] == pytest.approx(2.174, abs=0.02) and null["without"] == 0.0
    assert record["telemetry_columns"] == list(TELEMETRY_COLUMNS)
    assert record["frame_keys"] == list(TELEMETRY_COLUMNS)
    assert record["model_block"]["name"].startswith("von Karman")
    assert record["model_block"]["parameters"]["L_relation_above_2000_ft"] == "L_u = 2 L_v = 2 L_w = 2500 ft"
    assert "MIL-F-8785C" in record["model_block"]["parameters"]["spectral_convention"]
    assert record["parameters"]["delivery"]["p_equivalent"] == "absent"
    assert record["parameters"]["per_step_readback"]["agrees"] is True
    assert record["parameters"]["table"]["rows"] == 361
    assert record["parameters"]["table"]["seed_stream"] == "von_karman"
    assert record["parameters"]["table"]["realised"]["w"]["sigma_amplitudes"] == pytest.approx(2.1844, abs=1e-3)
    assert any("q_g and r_g" in n for n in record["not_claimed"])
    assert any("absent" in n for n in record["not_claimed"])
    assert any("FGWinds.cpp" in r for r in record["references"])
    assert "turbulence_model.intensity" not in records and "turbulence_model.seed" not in records
    assert json.dumps(vk_run.manifest).isascii()


def test_a_stated_intensity_and_seed_return_their_own_records():
    run = run_spec(spec_for("fly the c172p at 1500 m and 100 kt for 3 seconds",
                            model="von_karman", intensity="moderate", seed=99))
    records = {r["name"]: r for r in read_records(run.manifest["applied_variables"])}
    assert records["turbulence_model.intensity"]["value"] == "moderate"
    assert records["turbulence_model.intensity"]["unit"] == "W20 kt | word"
    assert records["turbulence_model.seed"]["value"] == 99 and records["turbulence_model.seed"]["unit"] == "1"
    assert records["turbulence_model.seed"]["parameters"]["seed"] == 99
    assert records["turbulence_model.model"]["null_test"]["ok"]


def test_the_run_is_deterministic_and_another_seed_differs(vk_run):
    again = run_spec(spec_for(model="von_karman"))
    assert again.output_digest == vk_run.output_digest
    other = run_spec(spec_for(model="von_karman", seed=8))
    assert other.output_digest != vk_run.output_digest


def test_the_null_pairs_measure_vk_against_none_and_against_dryden():
    """intensity moderate vs unstated (the spec's word is none): the gust
    channel moves 3.40 / 3.95 / 3.43 m/s, altitude 0.59 m, roll 4.47 deg.
    model von_karman vs dryden at the same word: the gust channel is the
    von Karman field itself (Dryden's lives in JSBSim's turb channel, 0
    on the gust one), altitude 0.51 m, roll 4.55 deg apart; both reached."""
    none = run_null_pair(spec_for("fly the c172p at 1500 m and 100 kt for 3 seconds",
                                  model="von_karman", intensity="moderate"), "turbulence_model.intensity")
    assert none.verdict == "reached" and none.digests_differ and none.null_value is None
    effect = none.to_dict()["effect"]
    assert effect["gust_down_mps"]["peak_abs"] == pytest.approx(3.427, abs=0.02)
    assert effect["altitude_m"]["peak_abs"] == pytest.approx(0.591, abs=0.05)
    assert effect["roll_deg"]["peak_abs"] == pytest.approx(4.465, abs=0.1)
    assert none.null_test().ok
    dryden = run_null_pair(spec_for(model="von_karman"), "turbulence_model.model")
    assert dryden.verdict == "reached" and dryden.null_value == "dryden"
    effect = dryden.to_dict()["effect"]
    assert effect["gust_north_mps"]["reached"] and effect["altitude_m"]["reached"]
    assert effect["roll_deg"]["peak_abs"] == pytest.approx(4.555, abs=0.1)
    assert effect["gust_p_equivalent_rad_s"]["peak_abs"] == 0.0     # absent on both stock runs


@pytest.mark.timeout(300)
def test_the_same_sigma_comparison_with_dryden_is_at_the_ladder_not_the_delivered_channel():
    """Both models are given the SAME ladder sigma at the c172p's altitude
    (7.181 ft/s = 2.189 m/s, exceedance row 3 at 4921 ft ASL). The von
    Karman table realises it within 0.5 %. JSBSim's Tustin Dryden channel,
    sampled at 10 Hz over 60 s at seed 7 with the controls held, delivers
    a std of 2.39 / 15.21 / 4.07 m/s (n/e/d): the w channel 1.9 x the
    ladder and the v channel 7 x. So "the same sigma" holds at the
    commanded ladder and NOT in the delivered channel; the comparable
    quantity is the ladder, and the aircraft's responses are compared in
    the null pair above. The bounds here are broad on purpose: they pin
    that the Dryden channel is neither silent nor within 10 %."""
    fdm = trimmed()
    dryden = DrydenTurbulence("moderate", seed=7)
    stack = EnvironmentStack([dryden])
    stack.configure(fdm)
    samples = []
    for i in range(60 * 120):
        stack.apply(fdm)
        fdm.step()
        if i % 12 == 0:
            samples.append([fdm.props.get(p) for p in ("atmosphere/turb-north-fps",
                                                       "atmosphere/turb-east-fps",
                                                       "atmosphere/turb-down-fps")])
    turb = np.array(samples) * u.M_PER_FT
    vk = VonKarmanTurbulence("moderate", seed=7, altitude_m=1500.0, duration_s=60.0, rate_hz=120.0)
    vk.build(55.322, 10.912)
    ladder = u.fps_to_mps(7.181364829396326)
    assert vk.sigma_mps == pytest.approx((ladder,) * 3)
    assert dryden.poe_index == vk.poe_index == 3
    assert vk.table[:, 3].std() == pytest.approx(ladder, rel=0.005)
    ratio = turb.std(axis=0) / ladder
    assert ratio[2] == pytest.approx(1.86, abs=0.15)
    assert ratio[1] > 3.0 and ratio[0] == pytest.approx(1.09, abs=0.15)
    assert not abs(ratio[2] - 1.0) < 0.10        # the delivered channel is NOT within 10 %


def test_the_gust_table_card_block_equals_the_runs_table(vk_run, tmp_path):
    """The card's rows are the run's rows (same sha256 over the %.17g text),
    361 of them for 3 s at 120 Hz, in the fixed key order; a Dryden spec
    writes no block."""
    spec = spec_for(model="von_karman")
    block = gust_table_card_block(spec)
    record = {r["name"]: r for r in read_records(vk_run.manifest["applied_variables"])}["turbulence_model.model"]
    assert list(block) == ["model", "seed", "sigma", "L", "tas_mps", "dt_s", "rows", "sha256"]
    assert block["sha256"] == record["parameters"]["table_sha256"]
    assert len(block["rows"]) == 361 and block["model"] == "von_karman"
    assert block["tas_mps"] == record["parameters"]["table"]["tas_mps"]
    assert gust_table_card_block(spec_for()) is None
    path = write_run_card(spec, tmp_path / "card.json")
    card = json.loads(path.read_text(encoding="utf-8"))
    assert card["gust_table"]["sha256"] == block["sha256"] and card["turbulence"] == "moderate"
    assert card["turbulence_properties"]["atmosphere/turb-type"] == 0.0      # Dryden OFF beside the table
    dryden_card = json.loads(write_run_card(spec_for(), tmp_path / "dry.json").read_text(encoding="utf-8"))
    assert dryden_card["turbulence_properties"]["atmosphere/turb-type"] == 4.0
    assert path.read_text(encoding="utf-8").isascii()
    assert "gust_table" not in json.loads(write_run_card(spec_for(), tmp_path / "d.json").read_text(encoding="utf-8"))


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    """The new modules, the fixture and the card blocks are ASCII (base.py
    and stack.py keep their pre-existing section signs in docstrings the
    engine never reads)."""
    for rel in ("core/environment/von_karman.py", "core/environment/shear.py",
                "assets/nwp/synthetic_profile_2026-09-28.json",
                "assets/nwp/synthetic_profile_2026-09-28.provenance.json"):
        assert (REPO / rel).read_text(encoding="utf-8").isascii(), rel
    import inspect

    text = (REPO / "core/scenario/blocks.py").read_text(encoding="utf-8")
    assert text[text.index("TURBULENCE_MODELS"):text.index("def configured_airframes")].isascii()
    assert inspect.getsource(TurbulenceModelSpec).isascii()
    assert inspect.getsource(WindProfileSpec).isascii()
    assert json.dumps(gust_table_card_block(spec_for(model="von_karman"))).isascii()
