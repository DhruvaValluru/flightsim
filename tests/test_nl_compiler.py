"""The compiler emits a spec and never runs anything (§2.6).

It is rule-based and therefore deterministic: the same sentence always produces
the same spec. That guarantee is what the reproducibility claim rests on.
"""

import pytest

from core.nl.compiler import compile_prompt
from core.scenario.fields import Source


def test_same_prompt_always_produces_the_same_spec():
    prompt = "fly the 747 at 10000 ft and 280 kt into a strong crosswind"
    digests = {compile_prompt(prompt).digest() for _ in range(5)}
    assert len(digests) == 1


def test_explicit_numbers_are_attributed_to_the_user():
    s = compile_prompt("fly the 737 at 6000 m and 250 kt")
    assert s.altitude.value == 6000.0 and s.altitude.source is Source.USER
    assert s.airspeed.value == 250.0 and s.airspeed.source is Source.USER


def test_vague_phrases_are_marked_inferred_not_user():
    """The distinction a reviewer needs: stated versus guessed."""
    s = compile_prompt("fly the 747 into a strong crosswind")
    assert s.wind_speed.source is Source.INFERRED
    assert s.wind_speed.value == 25.0


def test_unmentioned_values_are_marked_default():
    s = compile_prompt("fly the 747")
    assert s.turbulence.source is Source.DEFAULT
    assert s.latitude.source is Source.DEFAULT


def test_turbulence_words_carry_a_citation_not_a_magic_number():
    """§2.5: a plugin must answer 'what does moderate mean' with a standard."""
    s = compile_prompt("fly the 747 in moderate turbulence")
    assert s.turbulence.value == "moderate"
    assert "MIL-F-8785C" in s.turbulence.std
    assert s.turbulence.detail["W20_kt"] == 30.0


def test_terrain_number_is_not_read_as_the_altitude():
    """Both are '<number> m' and the terrain figure usually comes second.

    Before the fix this fell back to the default altitude of 3000 m, which
    happened to equal the terrain height in the §5 example and so produced the
    right rejection for entirely the wrong reason.
    """
    s = compile_prompt("land the 747 at 400 kt at 300 m altitude over 3000 m terrain")
    assert s.altitude.value == 300.0
    assert s.terrain_elevation.value == 3000.0


def test_terrain_stated_before_the_altitude_is_still_not_read_as_altitude():
    """The ordering that actually requires the terrain clause to be removed.

    When terrain comes first it is the leftmost '<number> m' in the sentence, so
    a plain left-to-right search returns it. The case above happens to pass
    either way, which is why it is not sufficient on its own.
    """
    s = compile_prompt("over 3000 m terrain, fly the 747 at 4500 m and 280 kt")
    assert s.terrain_elevation.value == 3000.0
    assert s.altitude.value == 4500.0


@pytest.mark.parametrize(
    "prompt,expected_m",
    [
        ("cruise at FL350", 10668.0),
        ("fly at 10000 ft", 3048.0),
        ("fly at 6000 m", 6000.0),
    ],
)
def test_altitude_units(prompt, expected_m):
    assert compile_prompt(prompt).altitude.value == pytest.approx(expected_m, abs=0.5)


def test_relative_wind_direction_is_resolved_against_heading():
    s = compile_prompt("fly heading 090 into a 20 kt crosswind")
    assert s.heading.value == 90.0
    # Meteorological: a crosswind for an easterly heading blows from the south.
    assert s.wind_direction.value == pytest.approx(180.0)
    assert s.wind_direction.detail["rel_to"] == "aircraft heading"


def test_cinematic_terms_are_reported_as_ignored_not_silently_dropped():
    """§8: the vocabulary is conditions-first, and says so when asked for a shot."""
    s = compile_prompt("epic cinematic flyby of the 747 over mountains")
    assert any("cinematic" in n for n in s.notes)
    # and nothing in the spec was set from them
    assert s.airspeed.source is Source.DEFAULT
