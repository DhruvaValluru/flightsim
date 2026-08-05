"""Validation rejects what cannot be flown; runs reproduce exactly.

§5 Phase 1 requires an impossible request to be rejected "with a clear message
naming the violated constraint" -- not to fail obscurely at trim, and not to run
and produce a plausible-looking video of nonsense.
"""

import pytest

from core.nl.compiler import compile_prompt
from core.scenario.envelope import measure_lift_curve, reference_speeds
from core.scenario.runner import UnimplementedConditionError, run_spec, wind_components_fps
from core.scenario.validate import ValidationError, validate


def constraints(prompt):
    return [v.constraint for v in validate(compile_prompt(prompt)).violations]


def test_valid_scenario_passes():
    report = validate(compile_prompt("fly the 747 at 6000 m and 280 kt"))
    assert report.ok, report.render()


def test_altitude_below_terrain_is_rejected_by_name():
    """The §5 example."""
    assert "altitude.terrain_clearance" in constraints(
        "land the 747 at 400 kt at 300 m altitude over 3000 m terrain"
    )


def test_below_stall_speed_is_rejected_by_name():
    assert "airspeed.stall_margin" in constraints("fly the 747 at 60 kt at 3000 m")


def test_condition_outside_the_aero_tables_is_rejected_by_name():
    """No analytic rule predicts where stock tables end, so trim is attempted."""
    assert "envelope.trim_feasible" in constraints(
        "cruise the global5000 at 10000 m at 300 kt"
    )


def test_unknown_aircraft_is_rejected_and_stops_further_checks():
    spec = compile_prompt("fly the 747 at 6000 m and 280 kt")
    spec.set("aircraft", "concorde-supersonic")
    report = validate(spec)
    assert [v.constraint for v in report.violations] == ["aircraft.exists"]


def test_running_an_invalid_scenario_raises_rather_than_running():
    spec = compile_prompt("land the 747 at 400 kt at 300 m altitude over 3000 m terrain")
    with pytest.raises(ValidationError):
        run_spec(spec)


def test_requesting_an_unimplemented_condition_is_fatal():
    """A spec must never run without a condition it asked for (§1.6).

    Turbulence itself became a real provider in Phase 3, so it is no longer
    refused. What must still be refused is an intensity no provider implements:
    quietly rounding it to the nearest one it does know would produce a run
    that reports a condition it does not have.
    """
    spec = compile_prompt("fly the 747 at 6000 m and 280 kt")
    spec.set("turbulence", "apocalyptic")
    with pytest.raises(UnimplementedConditionError, match="no provider"):
        run_spec(spec)


def test_turbulence_is_now_delivered_rather_than_refused():
    """The Phase 3 counterpart: a requested condition must actually arrive."""
    calm = compile_prompt("fly the 747 at 3000 m and 250 kt for 40 seconds")
    rough = compile_prompt(
        "fly the 747 at 3000 m and 250 kt in moderate turbulence for 40 seconds"
    )
    assert str(rough.turbulence.value) == "moderate"
    assert run_spec(rough).output_digest != run_spec(calm).output_digest


def test_same_spec_produces_the_same_output_digest():
    spec = compile_prompt("fly the 747 at 6000 m and 280 kt for 20 seconds")
    assert run_spec(spec).output_digest == run_spec(spec).output_digest


def test_changing_the_spec_changes_the_output():
    spec = compile_prompt("fly the 747 at 6000 m and 280 kt for 20 seconds")
    first = run_spec(spec).output_digest
    spec.set("airspeed", 270.0)
    assert run_spec(spec).output_digest != first


def test_manifest_records_what_is_needed_to_reproduce():
    spec = compile_prompt("fly the 747 at 6000 m and 280 kt for 10 seconds")
    manifest = run_spec(spec).manifest
    assert manifest["spec_digest"] == spec.digest()
    assert manifest["fdm"]["aircraft"]["sha256"]
    assert manifest["fdm"]["jsbsim_version"]
    assert manifest["fdm"]["mass_held_constant"] is False


@pytest.mark.parametrize(
    "from_deg,north,east",
    [(0.0, -1.0, 0.0), (90.0, 0.0, -1.0), (180.0, 1.0, 0.0), (270.0, 0.0, 1.0)],
)
def test_wind_direction_is_meteorological(from_deg, north, east):
    """Wind 'from 270' blows toward the east: +east component."""
    n, e = wind_components_fps(1.0, from_deg)
    from core.fdm import units as u
    assert n == pytest.approx(north * u.kt_to_fps(1.0), abs=1e-9)
    assert e == pytest.approx(east * u.kt_to_fps(1.0), abs=1e-9)


def test_reference_speeds_are_measured_not_asserted():
    """Vs comes from the model's own lift curve (§5 Phase 1)."""
    curve = measure_lift_curve("B747")
    assert not curve.clipped, "CLmax landed on a sweep edge; the stall was not bracketed"
    # A transport's clean CLmax sits near 1.2 and its peak well short of 20 deg.
    assert 0.8 < curve.cl_max < 1.8
    assert 8.0 < curve.alpha_at_cl_max_deg < 20.0

    speeds = reference_speeds("B747", 250_000.0, 0.0, curve=curve)
    assert speeds.vref_kt > speeds.vs_kt          # Vref is above the stall
    # Published clean 1 g stall at this weight is roughly 150-165 kt. This is a
    # sanity bound on the model, not a validation of the aircraft.
    assert 130.0 < speeds.vs_kt < 190.0
