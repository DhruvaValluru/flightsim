"""Per-run uncertainty (core/uncertainty.py): the Richardson / GCI
arithmetic, the dt/2 twin, u_x by source rank, the central sensitivity
pair, u_val and the block's form -- on a fake runner for the arithmetic
and on the real c172p for one measured twin.
"""

import contextlib
import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import pytest

from core.registry import REGISTRY, Registry, UInputRule, VariableRecord
from core.scenario.spec import ScenarioSpec
from core.uncertainty import (
    ASSUMED_ORDER, FORM, FS_THREE_RATE, FS_TWO_RATE, SRQS, central_sensitivity, observed_order,
    record_u_num, richardson, srq_series, three_rate_study, twin_spec, u_input_for, u_num_twin,
    u_val, u_x, uncertainty_block, uncertainty_for_run,
)

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/cameras_waypoint.yaml"


def base_spec() -> ScenarioSpec:
    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("duration", 1.0)
    return spec


@dataclass
class FakeResult:
    spec_digest: str
    output_digest: str
    telemetry: Any


class FakeTelemetry:
    def __init__(self, columns: Dict[str, list]) -> None:
        self.columns = columns


def fake_runner(spec):
    """Altitude drifts by 0.1 m per (1/rate) step scaled so the dt and
    dt/2 runs differ by exactly 0.2 m at t = 1 s; wind speed w kt lifts
    altitude by 2 m per kt at the end (a sensitivity of 2 m/kt)."""
    rate = float(spec.rate.value)
    w = float(spec.wind_speed.value)
    n = 11
    t = [0.1 * i for i in range(n)]
    bias = 0.2 * (120.0 / rate - 1.0) * -1.0        # 0 at 120 Hz, -0.1 at 240, -0.15 at 480
    alt = [1000.0 + bias + 2.0 * w * (ti / 1.0) for ti in t]
    cols = {"t": t, "altitude_m": alt, "tas_kt": [100.0] * n, "pitch_deg": [2.0] * n,
            "roll_deg": [0.0] * n, "heading_deg": [359.0 + 0.2 * i for i in range(n)],
            "lat_deg": [0.0 + 1e-6 * i for i in range(n)], "lon_deg": [0.0] * n}
    return FakeResult(spec.digest(), f"o-{rate:g}-{w:g}", FakeTelemetry(cols))


# -- the arithmetic ----------------------------------------------------------------------

def test_richardson_and_the_gci_are_the_stated_formulae():
    """e = |S_dt - S_dt/2| / (2^p - 1); GCI = Fs x e (Roache 1994)."""
    est = richardson(0.3, p=2.0, fs=1.25)
    assert est["error_estimate"] == pytest.approx(0.1)
    assert est["gci"] == pytest.approx(0.125)
    est = richardson(0.3, p=ASSUMED_ORDER, fs=FS_TWO_RATE)
    assert est["error_estimate"] == pytest.approx(0.3) and est["gci"] == pytest.approx(0.9)
    assert richardson(0.3, p=1.0, fs=3.0, ratio=4.0)["error_estimate"] == pytest.approx(0.1)
    assert FS_TWO_RATE == 3.0 and FS_THREE_RATE == 1.25 and ASSUMED_ORDER == 1.0
    with pytest.raises(ValueError, match="positive"):
        richardson(0.3, p=0.0, fs=3.0)
    assert observed_order(0.4, 0.1) == pytest.approx(2.0)
    assert observed_order(0.098, 0.048) == pytest.approx(1.03, abs=0.01)   # V9's own numbers
    with pytest.raises(ValueError):
        observed_order(0.0, 0.1)


def test_the_twin_doubles_the_rate_turns_turbulence_off_and_says_so():
    spec = base_spec()
    spec.set("turbulence", "moderate")
    twin = twin_spec(spec)
    assert float(twin.rate.value) == 240.0 and float(spec.rate.value) == 120.0
    assert str(twin.turbulence.value) == "none" and str(spec.turbulence.value) == "moderate"
    assert "turbulence off" in twin.turbulence.frm and "twin" in twin.rate.frm
    assert twin.digest() != spec.digest()
    assert float(twin_spec(spec, factor=4.0).rate.value) == 480.0


def test_srq_series_derives_north_east_from_lat_lon_and_unwraps_heading():
    cols = {"altitude_m": [1.0, 2.0], "lat_deg": [45.0, 45.0 + 1e-3], "lon_deg": [7.0, 7.0 + 1e-3],
            "heading_deg": [359.0, 1.0], "tas_kt": [1.0, 1.0]}
    s = srq_series(cols)
    assert set(s) == {"altitude_m", "north_m", "east_m", "heading_deg", "tas_kt"}
    assert s["north_m"][0] == 0.0 and s["north_m"][1] == pytest.approx(111.13, rel=1e-3)
    assert s["east_m"][1] == pytest.approx(78.85, rel=1e-3)    # cos(45) x prime-vertical arc
    assert s["heading_deg"][1] == pytest.approx(361.0)
    assert "pitch_deg" not in srq_series({"t": [0.0]})


def test_u_num_from_the_fake_twin_reports_the_gci_per_srq_with_its_basis():
    block = u_num_twin(base_spec(), runner=fake_runner)
    alt = block["srq"]["altitude_m"]
    assert alt["difference"] == pytest.approx(0.1)
    assert alt["p"] == 1.0 and alt["fs"] == 3.0
    assert alt["value"] == pytest.approx(0.3)                 # 3 x 0.1 / (2^1 - 1)
    assert alt["coarse_dt_s"] == pytest.approx(1 / 120) and alt["fine_dt_s"] == pytest.approx(1 / 240)
    assert "assumed" in alt["basis"] and alt["samples_compared"] == 11
    assert block["srq"]["tas_kt"]["value"] == 0.0
    assert block["twin"]["rate_hz"] == 240.0 and block["twin"]["turbulence"] == "none"
    assert block["base"]["output_digest"] == "o-120-0" and block["twin"]["output_digest"] == "o-240-0"
    assert set(block["srq"]) == set(SRQS)
    observed = u_num_twin(base_spec(), runner=fake_runner, observed_p={"altitude_m": 2.0})
    alt2 = observed["srq"]["altitude_m"]
    assert alt2["p"] == 2.0 and alt2["fs"] == 1.25 and "observed" in alt2["basis"]
    assert alt2["value"] == pytest.approx(1.25 * 0.1 / 3.0)
    assert record_u_num(block, "altitude_m") == {"srq": "altitude_m", "value": alt["value"],
                                                 "basis": alt["basis"]}
    assert record_u_num(block, "north_m")["value"] == pytest.approx(0.0)


def test_a_missing_srq_column_is_not_run_and_says_so():
    def no_lat(spec):
        r = fake_runner(spec)
        del r.telemetry.columns["lat_deg"]
        return r
    block = u_num_twin(base_spec(), runner=no_lat)
    assert block["srq"]["north_m"]["value"] is None
    assert block["srq"]["north_m"]["basis"].startswith("NOT RUN")
    assert record_u_num(block, "north_m") is None


def test_the_three_rate_study_observes_the_order():
    study = three_rate_study(base_spec(), runner=fake_runner)
    assert study["rates_hz"] == [120.0, 240.0, 480.0]
    # 0.1 (120 vs 240) against 0.05 (240 vs 480): first order.
    assert study["observed_p"]["altitude_m"] == pytest.approx(1.0)
    assert "tas_kt" not in study["observed_p"]                 # zero differences: no order
    assert study["detail"]["altitude_m"]["e_coarse_mid"] == pytest.approx(0.1)


# -- u_input ------------------------------------------------------------------------------

def _wind_entry(**overrides) -> VariableRecord:
    fields = dict(name="environment.wind_speed", spec_path="environment.wind_speed", unit="kt",
                  null_value=0.0, null_basis="still air",
                  u_input_rule=UInputRule(bin_width=10.0, declared_spread=1.5, note="test"))
    fields.update(overrides)
    return VariableRecord(**fields)


def test_u_x_follows_the_source_rank():
    entry = _wind_entry()
    assert u_x("user", entry) == (0.0, "user: 0 (no tolerance stated with the value)")
    assert u_x("user", entry, stated_tolerance=2.0)[0] == 2.0
    value, rule = u_x("inferred", entry)
    assert value == pytest.approx(5.0 / math.sqrt(3.0)) and "b = 10" in rule
    assert u_x("sampled", entry)[0] == 0.0
    assert u_x("default", entry)[0] == 1.5 and u_x("model", entry)[0] == 1.5
    with pytest.raises(ValueError, match="bin width"):
        u_x("inferred", _wind_entry(u_input_rule=UInputRule(bin_width=None)))
    with pytest.raises(ValueError, match="unknown"):
        u_x("guessed", entry)


def test_the_central_pair_measures_the_sensitivity_as_a_secant():
    spec = base_spec()
    spec.set("wind_speed", 10.0)
    pair = central_sensitivity(spec, _wind_entry(), u=2.0, runner=fake_runner)
    assert pair["sensitivity"]["altitude_m"] == pytest.approx(2.0)      # 2 m per kt at t = 1 s
    assert pair["sensitivity"]["tas_kt"] == 0.0
    assert pair["x"] == 10.0 and pair["u_x"] == 2.0
    assert pair["digests"] == {"plus": "o-120-12", "minus": "o-120-8"}
    with pytest.raises(ValueError, match="positive"):
        central_sensitivity(spec, _wind_entry(), u=0.0, runner=fake_runner)
    with pytest.raises(ValueError, match="no spec field"):
        central_sensitivity(spec, REGISTRY.get("limits.monitor"), u=1.0, runner=fake_runner)


def test_u_input_for_runs_the_pair_only_when_u_x_is_non_zero():
    spec = base_spec()
    spec.set("wind_speed", 10.0)
    exact = u_input_for(_wind_entry(), {"value": 10.0, "source": "user"}, spec=spec,
                        runner=fake_runner)
    assert exact["value"] == 0.0 and exact["sensitivity"] is None
    assert "no pair run" in exact["sensitivity_basis"]
    inferred = u_input_for(_wind_entry(), {"value": 10.0, "source": "inferred"}, spec=spec,
                           runner=fake_runner)
    assert inferred["value"] == pytest.approx(5.0 / math.sqrt(3.0)) and inferred["unit"] == "kt"
    assert inferred["sensitivity"]["altitude_m"] == pytest.approx(2.0)
    assert "central pair" in inferred["sensitivity_basis"]
    given = u_input_for(_wind_entry(), {"value": 10.0, "source": "default"},
                        sensitivity={"altitude_m": 3.0})
    assert given["sensitivity"] == {"altitude_m": 3.0} and given["sensitivity_basis"] == "given"


def test_u_val_is_the_root_sum_square_with_u_d_absent():
    num = {"srq": {"altitude_m": {"value": 0.3}, "tas_kt": {"value": None}}}
    inputs = {"environment.wind_speed": {"value": 2.0, "sensitivity": {"altitude_m": 2.0, "tas_kt": 0.0}},
              "atmosphere.temperature_deviation_c": {"value": 0.0, "sensitivity": None}}
    v = u_val(num, inputs)
    assert v["altitude_m"]["value"] == pytest.approx(math.sqrt(0.3 ** 2 + 4.0 ** 2))
    assert v["altitude_m"]["u_input_terms"] == {"environment.wind_speed": 4.0,
                                               "atmosphere.temperature_deviation_c": 0.0}
    assert v["tas_kt"]["value"] is None and v["tas_kt"]["basis"].startswith("NOT RUN")
    block = uncertainty_block(num, inputs)
    assert block["form"] == FORM == "ASME V&V 20; u_D absent per run"
    assert set(block) == {"u_num", "u_input", "u_val", "form", "not_claimed"}
    assert any("u_D" in s for s in block["not_claimed"])


def test_uncertainty_for_run_over_the_committed_example_carries_the_environment_inputs_at_zero():
    """Since W1 the environment section is registered whole, so the
    committed example states six registered inputs -- every one at its
    default (or a user value with no tolerance), u_x 0 by the rule, no
    pair run -- and u_val still equals u_num per SRQ; the base result is
    reused when given."""
    spec = base_spec()
    base = fake_runner(spec)
    block = uncertainty_for_run(spec, runner=fake_runner, base_result=base)
    assert set(block["u_input"]) == {
        "environment.wind_speed", "environment.wind_direction", "environment.turbulence",
        "environment.surface", "environment.weather_date", "environment.weather_event"}
    for name, part in block["u_input"].items():
        assert part["value"] == 0.0 and part["sensitivity"] is None, name
        assert part["sensitivity_basis"].startswith("no pair run: u_x is 0"), name
    assert block["u_val"]["altitude_m"]["value"] == pytest.approx(block["u_num"]["srq"]["altitude_m"]["value"])
    assert all(v == 0.0 for v in block["u_val"]["altitude_m"]["u_input_terms"].values())
    with_wind = Registry((_wind_entry(),))
    spec.set("wind_speed", 10.0, frm="strong wind")
    data = spec.to_dict()
    data["environment"]["wind_speed"]["source"] = "inferred"
    block = uncertainty_for_run(ScenarioSpec.from_dict(data), runner=fake_runner, registry=with_wind)
    assert block["u_input"]["environment.wind_speed"]["sensitivity"]["altitude_m"] == pytest.approx(2.0)
    assert block["u_val"]["altitude_m"]["u_input_terms"]["environment.wind_speed"] == pytest.approx(
        2.0 * 5.0 / math.sqrt(3.0))


# -- one real twin on the c172p ---------------------------------------------------------------

@pytest.mark.timeout(300)
def test_a_real_dt_2_twin_on_the_c172p_reports_u_num_below_the_null_floor():
    """One second of examples/cameras_waypoint.yaml at 120 and 240 Hz: the
    altitude GCI over a trimmed second is far below the 0.5 m null floor
    (measured), every SRQ has a number, the twin's digest differs, and
    the pair costs seconds (printed for the report)."""
    spec = base_spec()
    with contextlib.redirect_stdout(io.StringIO()):
        block = u_num_twin(spec)
    alt = block["srq"]["altitude_m"]
    assert alt["value"] is not None and alt["value"] < 0.5
    assert block["twin"]["output_digest"] != block["base"]["output_digest"]
    for srq in SRQS:
        assert block["srq"][srq]["value"] is not None, srq
    assert block["elapsed_s"] < 60.0
    print("dt/2 twin c172p 1 s: {:.2f} s; u_num altitude {:.3e} m, tas {:.3e} kt, "
          "heading {:.3e} deg".format(block["elapsed_s"], alt["value"],
                                      block["srq"]["tas_kt"]["value"],
                                      block["srq"]["heading_deg"]["value"]))
