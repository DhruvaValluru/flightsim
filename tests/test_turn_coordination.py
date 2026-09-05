"""Package G: the autopilot turn is coordinated, from a measured gain.

Every number asserted here was produced by
``experiments/airborne/turn_coordination.py`` (``--pre`` for the
damper-only channel) on the shipped code.
"""

from __future__ import annotations

import pytest

import core.control.coordination as coordination
from core.control.coordination import (
    LOOP_GAIN, CoordinationError, measure_yaw_authority,
)
from experiments.airborne.turn_coordination import dutch_roll, heading_step


@pytest.mark.parametrize("cas_kt", [230.0, 300.0])
def test_the_turn_is_coordinated(cas_kt):
    """B747 at 3000 m, +90 deg heading step, 8 s steady at the 25 deg
    bank limit. Damper only (before): turn rate 10.3% / 11.5% below
    g tan(phi)/V with 1.16 deg / 0.82 deg of sideslip. With the
    coordinator: within 1.3% / 0.8%, sideslip 0.004 / 0.001 deg."""
    result = heading_step(cas_kt, pre=False)
    assert abs(result["turn_rate_error_pct"]) < 2.0
    assert abs(result["beta_deg"]) < 0.2
    assert result["beta_abs_max_deg"] < 0.2
    assert abs(result["side_force_over_weight"]) < 0.002
    assert result["k_beta"] != 0.0 and result["ki_beta"] != 0.0
    assert result["heading_overshoot_pct"] < 1.0


def test_the_damper_alone_slips_the_turn():
    """The measurement the package exists for, kept as the control: the
    pre-Package-G channel flies a slipping turn."""
    result = heading_step(230.0, pre=True)
    assert result["turn_rate_error_pct"] < -8.0
    assert result["beta_deg"] > 0.8


def test_the_dutch_roll_is_not_degraded():
    """A 1 s rudder pulse, wings held level: the sideslip must ring down
    no slower and no larger with the coordinator than without it, and
    the mode must stay at MIL-F-8785C Level 1 (zeta >= 0.19). Measured:
    settle to 0.05 deg 7.7 s -> 4.9 s, peak 0.29 -> 0.19 deg, zeta 0.43
    -> 0.25 (a stiffer, faster mode: period 9.4 s -> 5.1 s)."""
    pre = dutch_roll(230.0, pre=True)
    post = dutch_roll(230.0, pre=False)
    assert post["settle_005deg_s"] <= pre["settle_005deg_s"]
    assert post["beta_peak_deg"] <= pre["beta_peak_deg"]
    assert post["damping_ratio"] is not None and post["damping_ratio"] >= 0.19
    assert abs(post["beta_end_deg"]) < 0.01


def test_the_gain_is_measured_on_the_airframe_at_its_state():
    """The gain closes the loop at LOOP_GAIN against the MEASURED
    beta-per-rudder slope, sign included: k_beta * slope = -LOOP_GAIN
    whatever the airframe's rudder convention."""
    authority = measure_yaw_authority("B747", altitude_m=3000.0, cas_kt=230.0)
    assert authority.beta_per_rudder_deg != 0.0
    assert authority.k_beta * authority.beta_per_rudder_deg == pytest.approx(
        -LOOP_GAIN)
    assert authority.ki_beta == pytest.approx(
        authority.k_beta / coordination.INTEGRAL_TIME_S)
    faster = measure_yaw_authority("B747", altitude_m=3000.0, cas_kt=300.0)
    assert faster.beta_per_rudder_deg != authority.beta_per_rudder_deg
    props = authority.as_properties()
    assert set(props) == {"ap/yaw/k-beta", "ap/yaw/ki-beta"}


def test_the_manifest_records_the_coordination():
    from core.nl.compiler import compile_prompt
    from core.scenario.runner import run_spec

    spec = compile_prompt("fly the 747 at 3000 m and 250 kt for 2 seconds")
    spec.set("hold_state", True)
    result = run_spec(spec, validate_first=False)
    block = result.manifest["control"]["coordination"]
    assert block["k_beta"] != 0.0 and block["loop_gain"] == LOOP_GAIN
    assert result.manifest["control"]["gains"]["ap/yaw/k-beta"] == pytest.approx(
        block["k_beta"])


def test_an_unmeasurable_slope_refuses_by_name(monkeypatch):
    monkeypatch.setattr(coordination, "MIN_SLOPE_DEG", 1e9)
    with pytest.raises(CoordinationError) as exc:
        measure_yaw_authority("B747", altitude_m=3000.0, cas_kt=230.0,
                              use_cache=False)
    assert exc.value.constraint == "control.coordination"
    assert "positive feedback" in str(exc.value)
