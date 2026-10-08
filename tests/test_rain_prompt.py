"""A prompt's rain reaches environment.precipitation_rate_mmh, from either
compiler.

Measured 2026-10-08 on the owner's machine: "raining" was refused
``prompt.not_set`` -- the regex compiler had no rain vocabulary, and the
LLM, with no rain field in its schema, wrote weather_event "rain" and was
rejected, so the fallback was the regex compiler again.
"""

import pytest

from core.nl.compiler import compile_prompt
from core.nl.llm_compiler import (
    CANONICAL_UNITS,
    FIELD_VALUE_SCHEMAS,
    SYSTEM_PROMPT,
    LLMCompileError,
    compile_prompt_llm,
)
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate
from tests.test_llm_compiler import entry, fake_client


def _not_set(spec):
    return [v for v in validate(spec, check_feasibility=False).violations
            if v.constraint == "prompt.not_set"]


@pytest.mark.parametrize("prompt, rate", [
    ("fly the c172p while it is raining", 4.0),
    ("a rainy approach in the a320", 4.0),
    ("the c172p through light rain", 1.0),
    ("fly the 747 in drizzle", 1.0),
    ("the a320 in heavy rain", 10.0),
    ("the c172p in a downpour", 10.0),
    ("fly the c172p in 6 mm/h rain", 6.0),
])
def test_rain_words_set_a_rate_and_pass_the_prompt_check(prompt, rate):
    spec = compile_prompt(prompt)
    assert spec.precipitation_rate_mmh.value == rate
    assert spec.precipitation_rate_mmh.unit == "mm/h"
    assert not _not_set(spec)


def test_a_stated_rate_is_the_users_and_a_word_is_inferred():
    assert str(compile_prompt("c172p in 6 mm/h rain").precipitation_rate_mmh.source) == "user"
    assert str(compile_prompt("c172p in the rain").precipitation_rate_mmh.source) == "inferred"


def test_no_rain_word_leaves_the_canonical_default():
    spec = compile_prompt("fly the c172p at 1000 m")
    assert spec.precipitation_rate_mmh.value is None
    assert spec.precipitation_rate_mmh.to_dict() == \
        ScenarioSpec.from_dict(spec.to_dict()).precipitation_rate_mmh.to_dict()
    assert "precipitation_rate_mmh" not in spec.to_dict().get("environment", {})


def test_a_negated_rain_word_states_no_rate():
    assert compile_prompt("fly the c172p with no rain").precipitation_rate_mmh.value is None
    assert compile_prompt("fly the c172p without drizzle").precipitation_rate_mmh.value is None


def test_snow_still_refused_by_name():
    """A rate is rain (core.scene.precipitation): snow sets nothing."""
    spec = compile_prompt("fly the c172p in the snow")
    assert spec.precipitation_rate_mmh.value is None
    assert [v.actual for v in _not_set(spec)] == ["snow"]


def test_the_llm_can_state_a_rain_rate():
    assert FIELD_VALUE_SCHEMAS["precipitation_rate_mmh"]["type"] == "number"
    assert CANONICAL_UNITS["precipitation_rate_mmh"] == "mm/h"
    assert "precipitation_rate_mmh" in SYSTEM_PROMPT
    client = fake_client({"fields": {
        "precipitation_rate_mmh": entry(4, "inferred", "raining")},
        "notes": [], "questions": []})
    spec = compile_prompt_llm("fly the c172p while it is raining", client=client).spec
    assert spec.precipitation_rate_mmh.value == 4.0
    assert spec.precipitation_rate_mmh.unit == "mm/h"
    assert str(spec.precipitation_rate_mmh.source) == "inferred"
    assert not _not_set(spec)


def test_the_llm_writing_rain_as_a_weather_event_is_still_rejected():
    client = fake_client({"fields": {"weather_event": entry("rain", "inferred", "raining")},
                          "notes": [], "questions": []})
    with pytest.raises(LLMCompileError, match="outside the vocabulary"):
        compile_prompt_llm("fly the c172p while it is raining", client=client)


def test_an_llm_rate_out_of_bounds_is_refused_by_the_validator():
    client = fake_client({"fields": {
        "precipitation_rate_mmh": entry(-3, "user", "-3 mm/h")},
        "notes": [], "questions": []})
    spec = compile_prompt_llm("c172p in -3 mm/h rain", client=client).spec
    assert any(v.constraint == "look.precipitation_rate"
               for v in validate(spec, check_feasibility=False).violations)
