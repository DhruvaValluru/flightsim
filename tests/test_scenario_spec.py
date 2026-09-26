"""The spec is the reproducible unit (§2.6).

It must round-trip exactly, hash on content rather than wording, and record
which numbers a human chose versus which were guessed.
"""

import pytest

from core.nl.compiler import compile_prompt
from core.scenario.fields import Quantity, Source
from core.scenario.spec import ScenarioSpec


@pytest.fixture
def spec():
    return compile_prompt("fly the 747 at 10000 ft and 280 kt heading 090 for 60 seconds")


def test_round_trip_through_yaml_preserves_the_digest(spec, tmp_path):
    path = spec.write(tmp_path / "s.yaml")
    assert ScenarioSpec.read(path).digest() == spec.digest()


def test_digest_ignores_the_prompt_wording(spec):
    """Two sentences commanding the same simulation must hash identically.

    What a run depends on is the numbers, not the English that produced them.
    """
    other = compile_prompt(
        "fly a 747 heading 090 at 280 kt, 10000 ft, for 60 seconds"
    )
    assert other.prompt != spec.prompt
    assert other.digest() == spec.digest()


def test_digest_changes_when_a_value_changes(spec):
    before = spec.digest()
    spec.set("altitude", 4500.0)
    assert spec.digest() != before


def test_editing_attributes_the_field_to_the_user(spec):
    """An override is a human decision and must be visible as one."""
    assert spec.turbulence.source is Source.DEFAULT
    spec.set("turbulence", "light", frm="operator disagreed with the default")
    assert spec.turbulence.source is Source.USER
    assert "operator" in spec.turbulence.frm


def test_every_numeric_field_carries_a_unit(spec):
    """A bare number is how 233 kt and 233 m get confused."""
    for _, name, q in spec.quantities():
        if isinstance(q.value, (int, float)) and not isinstance(q.value, bool):
            assert q.unit is not None, f"{name} has no unit"


def test_spec_version_8_and_the_model_source(spec):
    """SPEC_VERSION is 8 (Phase 2: scene, taxonomy, traffic,
    randomization.policy and cameras[].exposure, every one optional and
    absent-canonical), so older dicts refuse by the named version error
    -- completed runs recover from provenance.json, never by re-parsing.
    The provenance rules are unchanged since version 5: a model-sourced
    quantity round-trips; plan() may move it (the guess is the system's
    choice) and the source becomes derived; user and inferred values
    stay immovable."""
    from core.scenario.spec import SPEC_VERSION

    assert SPEC_VERSION == 8

    spec.altitude = Quantity(150.0, "m", Source.MODEL, frm="treetop level")
    reread = ScenarioSpec.from_dict(spec.to_dict())
    assert reread.altitude.source is Source.MODEL
    assert reread.altitude.frm == "treetop level"

    spec.plan("altitude", 300.0, frm="planner raised the declared guess")
    assert spec.altitude.source is Source.DERIVED

    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("airspeed", 300.0, frm="airspeed is user-stated here")

    old = spec.to_dict()
    old["spec_version"] = 5
    with pytest.raises(ValueError, match="not supported"):
        ScenarioSpec.from_dict(old)


def test_unsupported_spec_version_is_refused(spec):
    data = spec.to_dict()
    data["spec_version"] = 99
    with pytest.raises(ValueError, match="not supported"):
        ScenarioSpec.from_dict(data)


def test_missing_field_is_refused(spec):
    data = spec.to_dict()
    del data["initial"]["altitude"]
    with pytest.raises(ValueError, match="missing required field"):
        ScenarioSpec.from_dict(data)


def test_rendered_table_shows_provenance(spec):
    table = spec.render_table()
    assert "provenance" in table
    assert "10000 ft" in table          # the phrase the altitude came from
    assert "user" in table and "default" in table


def test_quantity_detail_survives_round_trip():
    q = Quantity.inferred("moderate", frm="moderate turbulence",
                          std="MIL-F-8785C Fig.7", W20_kt=30.0)
    assert Quantity.from_dict(q.to_dict()).detail["W20_kt"] == 30.0


def test_a_duration_above_an_hour_is_refused_by_name(spec):
    """The LLM tier or a hand-written YAML can state 120000 s; nothing
    refused it, and a campaign would integrate and write frames for
    hours on a number nobody meant. Above MAX_DURATION_S (an hour) the
    validator refuses run.duration by name, with the number and the
    limit, and the catalogue puts both bounds into one sentence."""
    import dataclasses

    from core.messages import explain
    from core.scenario.validate import MAX_DURATION_S, validate

    assert MAX_DURATION_S == 3600.0
    assert validate(spec, check_feasibility=False).ok
    spec.duration = dataclasses.replace(spec.duration, value=MAX_DURATION_S)
    assert validate(spec, check_feasibility=False).ok          # the bound is inclusive
    spec.duration = dataclasses.replace(spec.duration, value=120000.0)
    report = validate(spec, check_feasibility=False)
    named = [v for v in report.violations if v.constraint == "run.duration"]
    assert not report.ok and len(named) == 1
    violation = named[0]
    assert violation.actual == 120000.0 and violation.limit == MAX_DURATION_S
    assert violation.unit == "s" and "session, not a scenario" in violation.message
    words = explain(violation)
    assert words["rule"] == "run.duration"
    assert "no longer than an hour" in words["sentence"]
    assert "3600" in words["hint"]
