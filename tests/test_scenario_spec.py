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


def test_spec_version_5_and_the_model_source(spec):
    """SPEC_VERSION is 5: the field list is version 4's, but the
    provenance vocabulary gained source "model" (the scene director's
    declared interpretation), which version-4 builds refuse -- so the
    refuse-old-dicts convention applies in both directions. A
    model-sourced quantity round-trips; plan() may move it (the guess is
    the system's choice) and the source becomes derived; user and
    inferred values stay immovable."""
    from core.scenario.spec import SPEC_VERSION

    assert SPEC_VERSION == 5

    spec.altitude = Quantity(150.0, "m", Source.MODEL, frm="treetop level")
    reread = ScenarioSpec.from_dict(spec.to_dict())
    assert reread.altitude.source is Source.MODEL
    assert reread.altitude.frm == "treetop level"

    spec.plan("altitude", 300.0, frm="planner raised the declared guess")
    assert spec.altitude.source is Source.DERIVED

    with pytest.raises(ValueError, match="never.*moved"):
        spec.plan("airspeed", 300.0, frm="airspeed is user-stated here")

    old = spec.to_dict()
    old["spec_version"] = 4
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
