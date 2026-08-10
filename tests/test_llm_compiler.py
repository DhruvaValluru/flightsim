"""The LLM compiler: same schema, same provenance, same validator.

Every test runs against a mock client -- the suite never touches the network
and never needs a key. The live path differs only in who fills the JSON, and
Gate 8.1's corpus exercises that separately.
"""

import json
from types import SimpleNamespace

import pytest

from core.nl.compiler import compile_prompt
from core.nl.llm_compiler import (
    AIRCRAFT_MODELS,
    FIELD_VALUE_SCHEMAS,
    RESPONSE_SCHEMA,
    LLMCompileError,
    compile_prompt_llm,
)
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate


def fake_client(payload, stop_reason="end_turn", model="claude-opus-5"):
    """An anthropic.Anthropic stand-in returning a canned structured output."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        model=model,
    )
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.captured = captured
    return client


def entry(value, source="user", frm="stated"):
    return {"value": value, "source": source, "from": frm}


# -- the happy path -------------------------------------------------------

def test_stated_and_inferred_fields_overlay_with_provenance():
    client = fake_client({
        "fields": {
            "aircraft": entry("c172p", "user", "the cessna"),
            "altitude": entry(2600.0, "user", "2600 m"),
            "wind_speed": entry(25.0, "inferred", "rough wind"),
            "turbulence": entry("moderate", "inferred", "rough wind"),
        },
        "notes": [],
    })
    result = compile_prompt_llm(
        "simulate the cessna at 2600 m in rough wind", client=client)
    spec = result.spec

    assert str(spec.aircraft.value) == "c172p"
    assert str(spec.aircraft.source) == "user"
    assert spec.aircraft.frm == "the cessna"
    assert float(spec.altitude.value) == 2600.0
    assert str(spec.wind_speed.source) == "inferred"
    assert spec.wind_speed.frm == "rough wind"
    # Turbulence carries the same citation + W20 detail the regex path attaches.
    assert str(spec.turbulence.value) == "moderate"
    assert spec.turbulence.std and "MIL-F-8785C" in spec.turbulence.std
    assert spec.turbulence.detail["W20_kt"] == 30.0
    # Untouched fields stay defaulted.
    assert str(spec.airspeed.source) == "default"
    assert str(spec.heading.source) == "default"
    assert result.compiler == "llm"
    assert result.model == "claude-opus-5"
    assert json.loads(result.raw_response)["fields"]["aircraft"]["value"] == "c172p"


def test_untouched_fields_are_bit_identical_to_regex_defaults():
    """An empty overlay must produce the regex compiler's exact defaults.

    This is the property Gate 8.1's refusal-for-refusal comparison rests on:
    if the two compilers defaulted differently, the validator could judge
    the same prompt differently depending on who compiled it.
    """
    client = fake_client({"fields": {}, "notes": []})
    llm_spec = compile_prompt_llm("a prompt saying nothing usable",
                                  client=client).spec
    regex_spec = compile_prompt("")
    # digest() covers every field and excludes prompt/notes by design.
    assert llm_spec.digest() == regex_spec.digest()


def test_prompt_is_retained_and_notes_carried():
    client = fake_client({
        "fields": {},
        "notes": ["ignored cinematic term 'epic flyby'",
                  "unknown aircraft 'SR-71' cannot be expressed"],
    })
    result = compile_prompt_llm("epic flyby of an SR-71", client=client)
    assert result.spec.prompt == "epic flyby of an SR-71"
    assert len(result.spec.notes) == 2
    assert "SR-71" in result.spec.notes[1]


def test_spec_round_trips_and_digest_is_stable():
    client = fake_client({
        "fields": {"altitude": entry(3000.0, "user", "3000 m")},
        "notes": [],
    })
    spec = compile_prompt_llm("fly at 3000 m", client=client).spec
    again = ScenarioSpec.from_yaml(spec.to_yaml())
    assert again.digest() == spec.digest()


def test_request_carries_schema_and_no_sampling_params():
    client = fake_client({"fields": {}, "notes": []})
    compile_prompt_llm("anything", client=client)
    request = client.captured
    assert request["model"] == "claude-opus-5"
    assert request["output_config"]["format"]["schema"] is RESPONSE_SCHEMA
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in request


# -- the validator still governs ------------------------------------------

def test_validation_refuses_llm_specs_by_name():
    """An impossible request compiles literally and is refused by name."""
    client = fake_client({
        "fields": {
            "altitude": entry(500.0, "user", "500 m"),
            "terrain_elevation": entry(2000.0, "inferred", "mountains"),
        },
        "notes": [],
    })
    spec = compile_prompt_llm("fly at 500 m over the mountains",
                              client=client).spec
    report = validate(spec, check_feasibility=False)
    assert not report.ok
    assert any(v.constraint == "altitude.terrain_clearance"
               for v in report.violations)


# -- strict rejection: never silently patched -----------------------------

def test_malformed_json_is_an_error():
    client = fake_client("this is not json {")
    with pytest.raises(LLMCompileError, match="not valid JSON"):
        compile_prompt_llm("anything", client=client)


def test_unknown_field_is_an_error():
    client = fake_client({
        "fields": {"camera_angle": entry("chase")}, "notes": [],
    })
    with pytest.raises(LLMCompileError, match="unknown field 'camera_angle'"):
        compile_prompt_llm("anything", client=client)


def test_model_cannot_claim_default_provenance():
    client = fake_client({
        "fields": {"altitude": {"value": 3000.0, "source": "default",
                                "from": "made up"}},
        "notes": [],
    })
    with pytest.raises(LLMCompileError, match="source"):
        compile_prompt_llm("anything", client=client)


def test_out_of_vocabulary_enum_is_an_error():
    client = fake_client({
        "fields": {"turbulence": entry("apocalyptic", "inferred", "hell")},
        "notes": [],
    })
    with pytest.raises(LLMCompileError, match="outside the vocabulary"):
        compile_prompt_llm("anything", client=client)


def test_unknown_aircraft_cannot_be_guessed_into_a_field():
    assert "SR71" not in FIELD_VALUE_SCHEMAS["aircraft"]["enum"]
    client = fake_client({
        "fields": {"aircraft": entry("SR71", "user", "the blackbird")},
        "notes": [],
    })
    with pytest.raises(LLMCompileError, match="outside the vocabulary"):
        compile_prompt_llm("anything", client=client)


def test_boolean_is_not_a_number():
    client = fake_client({
        "fields": {"altitude": {"value": True, "source": "user", "from": "x"}},
        "notes": [],
    })
    with pytest.raises(LLMCompileError, match="not a number"):
        compile_prompt_llm("anything", client=client)


def test_missing_provenance_phrase_is_an_error():
    client = fake_client({
        "fields": {"altitude": {"value": 3000.0, "source": "user", "from": "  "}},
        "notes": [],
    })
    with pytest.raises(LLMCompileError, match="no provenance phrase"):
        compile_prompt_llm("anything", client=client)


def test_extra_top_level_keys_are_an_error():
    client = fake_client({"fields": {}, "notes": [], "confidence": 0.9})
    with pytest.raises(LLMCompileError, match="top-level keys"):
        compile_prompt_llm("anything", client=client)


def test_refusal_stop_reason_is_an_error():
    client = fake_client({"fields": {}, "notes": []}, stop_reason="refusal")
    with pytest.raises(LLMCompileError, match="refusal"):
        compile_prompt_llm("anything", client=client)


def test_api_failure_is_reported_not_swallowed():
    def create(**kwargs):
        raise ConnectionError("network unreachable")

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(LLMCompileError, match="API call failed"):
        compile_prompt_llm("anything", client=client)


# -- schema consistency ----------------------------------------------------

def test_every_schema_field_is_a_spec_field():
    spec_fields = {name for _, name in ScenarioSpec.FIELD_ORDER}
    assert set(FIELD_VALUE_SCHEMAS) <= spec_fields


def test_host_policy_fields_are_not_model_settable():
    for policy_field in ("rate", "seed", "mass_held", "hold_state"):
        assert policy_field not in FIELD_VALUE_SCHEMAS


def test_schema_objects_all_refuse_additional_properties():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
            for value in node.values():
                walk(value)

    walk(RESPONSE_SCHEMA)


def test_aircraft_vocabulary_matches_regex_compiler():
    from core.nl.compiler import AIRCRAFT_WORDS

    regex_models = {model for _, model in AIRCRAFT_WORDS}
    assert set(AIRCRAFT_MODELS) == regex_models
