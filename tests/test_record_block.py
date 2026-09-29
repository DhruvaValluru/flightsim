"""The spec's record block (R2, core/scenario/blocks.py RecordSpec):
``record {null_tests, convergence, sensitivity_pairs}`` -- the spec's own
way to ask for the null pairs, the three-rate convergence study and the
sensitivity pairs flightsim/capture.py runs with --null-tests /
--uncertainty. Absent-canonical (every committed example keeps its
digest), refused by name (record.convergence, record.uncertainty_basis
in the validator; record.readback at the runner), registered one entry
per field, catalogued, and read by the capture beside the options.

No flight here: the runner's refusal is graded on a manifest built by
hand, the three-rate study on a fake runner that records the rates it
was asked for.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.scenario.blocks import RecordSpec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import (
    RATE_MAX_HZ, convergence_problems, uncertainty_basis_violations, validate, validate_record,
)

REPO = Path(__file__).resolve().parents[1]
WAYPOINT = REPO / "examples" / "cameras_waypoint.yaml"


def constraints(spec) -> list:
    return [v.constraint for v in validate_record(spec)]


# -- absent-canonical ---------------------------------------------------------------

def test_the_default_block_is_omitted_and_every_committed_example_keeps_its_digest():
    # The committed digests, pinned in tests/test_registry.py.
    from tests.test_registry import EXAMPLE_DIGESTS

    assert len(EXAMPLE_DIGESTS) >= 8
    for rel, digest in EXAMPLE_DIGESTS.items():
        spec = ScenarioSpec.read(REPO / rel)
        data = spec.to_dict()
        assert "record" not in data and "instruments" not in data, rel
        assert spec.record.is_default() and spec.instruments.is_default()
        assert spec.digest() == digest, rel
        assert ScenarioSpec.from_dict(data).digest() == digest, rel


def test_a_stated_block_round_trips_and_moves_the_digest():
    spec = ScenarioSpec.read(WAYPOINT)
    before = spec.digest()
    spec.set("record.null_tests", True)
    spec.set("record.convergence", {"rates": [60.0, 120.0, 240.0]})
    data = spec.to_dict()
    assert data["record"]["null_tests"]["value"] is True
    assert data["record"]["convergence"]["value"] == {"rates": [60.0, 120.0, 240.0]}
    assert data["record"]["sensitivity_pairs"]["value"] is False
    again = ScenarioSpec.from_dict(data)
    assert again.to_dict() == data and again.digest() == spec.digest() != before
    assert RecordSpec.FIELD_ORDER == ("null_tests", "convergence", "sensitivity_pairs")


# -- what the block asks for ---------------------------------------------------------------

def test_asks_ors_the_block_with_the_options_and_says_who_asked():
    block = RecordSpec.defaulted()
    assert block.asks() == {"null_tests": False, "uncertainty": False, "convergence_rates_hz": None,
                            "asked_by": {"null_tests": "", "uncertainty": ""}}
    asked = block.asks(null_tests=True, uncertainty=True)
    assert asked["null_tests"] and asked["uncertainty"]
    assert asked["asked_by"] == {"null_tests": "+cli", "uncertainty": "+cli"}
    block.set("null_tests", True)
    block.set("convergence", {"rates": [30, 60, 120]})
    asked = block.asks()
    assert asked["null_tests"] and asked["asked_by"]["null_tests"] == "spec"
    # The convergence study feeds u_num, so it asks for the uncertainty block.
    assert asked["uncertainty"] and asked["convergence_rates_hz"] == [30.0, 60.0, 120.0]
    assert asked["asked_by"]["uncertainty"] == "+convergence"
    block.set("sensitivity_pairs", True)
    assert block.asks(uncertainty=True)["asked_by"]["uncertainty"] == "spec+convergence+cli"


def test_the_capture_reads_the_block_beside_its_options():
    """flightsim/capture.py: the options stay, the block is OR-ed in, the
    convergence rates run the three-rate study from their first rate, the
    uncertainty basis is refused before any flight, and the FDM-rate
    instruments file and block ride with the capture."""
    source = (REPO / "flightsim" / "capture.py").read_text(encoding="utf-8")
    assert '"--null-tests"' in source and '"--uncertainty"' in source
    assert "spec.record.asks(null_tests=args.null_tests, uncertainty=args.uncertainty)" in source
    assert 'if record_asks["null_tests"] or record_asks["uncertainty"]:' in source
    assert 'record_asks["convergence_rates_hz"][0]' in source and "three_rate_study(" in source
    assert "uncertainty_basis_violations(spec)" in source
    assert "result.instruments.write(out)" in source
    assert "instruments=(result.manifest.get(\"instruments\")" in source
    from core.capture.manifest import SIDECAR_CONTEXT_KEYS

    assert "instruments" in SIDECAR_CONTEXT_KEYS and "uncertainty" in SIDECAR_CONTEXT_KEYS


def test_the_study_spec_the_capture_builds_flies_exactly_the_stated_rates():
    from core.uncertainty import three_rate_study

    flown = []

    def fake(spec):
        dt = 1.0 / float(spec.rate.value)
        flown.append(float(spec.rate.value))
        t = [0.1 * k for k in range(11)]
        return SimpleNamespace(output_digest=f"d{len(flown)}",
                               telemetry=SimpleNamespace(columns={
                                   "t": t, "altitude_m": [1000.0 + dt * x for x in t]}))

    spec = ScenarioSpec.read(WAYPOINT)
    rates = [30.0, 60.0, 120.0]
    study_spec = ScenarioSpec.from_dict(spec.to_dict())
    study_spec.set("rate", rates[0], frm="record.convergence: the three-rate study's first rate")
    study = three_rate_study(study_spec, runner=fake)
    assert flown == rates and study["rates_hz"] == rates
    assert study["observed_p"]["altitude_m"] == pytest.approx(1.0, abs=1e-9)   # error in dt: order 1


# -- the refusals, by name -----------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "fast", {"rate": [60, 120, 240]}, {"rates": [60, 120]}, {"rates": [60, 120, "240"]},
    {"rates": [60, 0, 240]}, {"rates": [120, 60, 240]}, {"rates": [60, 120, 300]},
    {"rates": [600, 1200, 2400]}, {"rates": [60, 120, float("nan")]},
])
def test_rates_the_fdm_cannot_run_refuse_record_convergence(value):
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("record.convergence", value)
    assert convergence_problems(value)
    assert set(constraints(spec)) == {"record.convergence"}


def test_rates_the_study_runs_pass_and_the_ceiling_is_stated():
    assert RATE_MAX_HZ == 1200.0
    for rates in ([60, 120, 240], [300, 600, 1200], [7.5, 15, 30]):
        assert convergence_problems({"rates": rates}) == []
    assert convergence_problems(None) == []
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("record.convergence", {"rates": [60, 120, 240]})
    assert constraints(spec) == []
    spec.set("record.null_tests", "yes")                   # a flag that is not a boolean
    assert constraints(spec) == ["record.convergence"]


def _with_inferred(field: str, value) -> ScenarioSpec:
    """The waypoint spec with one environment field inferred (a word the
    compiler read) and the sensitivity pairs asked for."""
    data = ScenarioSpec.read(WAYPOINT).to_dict()
    data["environment"][field]["value"] = value
    data["environment"][field]["source"] = "inferred"
    spec = ScenarioSpec.from_dict(data)
    spec.set("record.sensitivity_pairs", True)
    return spec


def test_an_inferred_variable_without_a_bin_width_refuses_record_uncertainty_basis():
    from core.registry import REGISTRY

    assert REGISTRY.get("environment.wind_direction").u_input_rule.bin_width is None
    spec = _with_inferred("wind_direction", 270.0)
    assert constraints(spec) == ["record.uncertainty_basis"]
    assert "environment.wind_direction" in validate_record(spec)[0].message
    # Wired into the full validator (feasibility aside), and into the
    # capture's own call when only the option asks.
    assert "record.uncertainty_basis" in [v.constraint for v in validate(spec, check_feasibility=False).violations]
    assert [v.constraint for v in uncertainty_basis_violations(spec)] == ["record.uncertainty_basis"]
    # An inferred variable WITH a bin width has its (b/2)/sqrt(3) rule.
    assert REGISTRY.get("environment.wind_speed").u_input_rule.bin_width == 10.0
    assert constraints(_with_inferred("wind_speed", 12.0)) == []
    # Nothing is asked, nothing is refused.
    quiet = _with_inferred("wind_direction", 270.0)
    quiet.set("record.sensitivity_pairs", False)
    assert constraints(quiet) == []
    # The convergence study feeds the same block, so it asks too.
    quiet.set("record.convergence", {"rates": [60, 120, 240]})
    assert constraints(quiet) == ["record.uncertainty_basis"]


def test_a_readback_outside_its_tolerance_refuses_the_run_record_readback():
    from core.records import RECORD_VERSION
    from core.registry import RecordError
    from core.scenario.runner import refuse_failed_readbacks

    def record(name, value, written, tolerance=0.0, kind="absolute"):
        allowed = tolerance * abs(written) if kind == "relative" else tolerance
        return {"name": name, "readback": {
            "property": f"{name}/prop", "value": value, "written": written, "tolerance": tolerance,
            "tolerance_kind": kind, "agrees": abs(value - written) <= allowed, "basis": "test"}}

    good = {"applied_variables": {"record_version": RECORD_VERSION, "applied_variables": [
        record("a.exact", 1.0, 1.0), record("b.relative", 0.5 + 1e-8, 0.5, 1e-6, "relative"),
        {"name": "c.none", "readback": None}]}}
    assert refuse_failed_readbacks(good) == ["a.exact/prop", "b.relative/prop"]
    assert refuse_failed_readbacks({}) == []
    bad = {"applied_variables": {"record_version": RECORD_VERSION, "applied_variables": [
        record("a.exact", 1.0, 1.0), record("d.off", 3.0, 2.0, 0.5)]}}
    with pytest.raises(RecordError) as err:
        refuse_failed_readbacks(bad)
    assert err.value.constraint == "record.readback"
    assert "d.off" in err.value.message and "a.exact" not in err.value.message


# -- registered and catalogued ------------------------------------------------------------

def test_every_field_is_registered_with_recorded_effect_channels_and_every_name_is_catalogued():
    from core.messages import catalogue, is_catalogued
    from core.registry import REGISTRY, unregistered_fields
    from core.telemetry.recorder import DEFAULT_CHANNELS

    for name in RecordSpec.FIELD_ORDER:
        entry = REGISTRY.get(f"record.{name}")
        assert entry.spec_path == f"record.{name}" and not entry.jsbsim_writes
        assert all(c.name in DEFAULT_CHANNELS for c in entry.effect_channels)
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("record.null_tests", True)
    spec.set("instruments.imu", {"profile": "tactical", "lever_arm_m": [1.0, 0.0, 0.0]})
    assert unregistered_fields(spec.to_dict()) == []
    assert {"record.null_tests", "instruments.imu"} <= set(REGISTRY.stated_variables(spec.to_dict()))
    for name in ("record.readback", "record.convergence", "record.uncertainty_basis",
                 "instrument.profile", "instrument.lever_arm", "instrument.rate",
                 "annotation.null_effect", "check.applied_readback", "check.null_effect",
                 "check.instrument_allan", "check.instrument_lever_arm", "check.uncertainty_present"):
        assert is_catalogued(name), name
        assert catalogue()[name]["sentence"].isascii()
