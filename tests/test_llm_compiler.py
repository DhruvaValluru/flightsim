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
        "notes": [], "questions": [],
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
    client = fake_client({"fields": {}, "notes": [], "questions": []})
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
        "questions": [],
    })
    result = compile_prompt_llm("epic flyby of an SR-71", client=client)
    assert result.spec.prompt == "epic flyby of an SR-71"
    assert len(result.spec.notes) == 2
    assert "SR-71" in result.spec.notes[1]


def test_spec_round_trips_and_digest_is_stable():
    client = fake_client({
        "fields": {"altitude": entry(3000.0, "user", "3000 m")},
        "notes": [], "questions": [],
    })
    spec = compile_prompt_llm("fly at 3000 m", client=client).spec
    again = ScenarioSpec.from_yaml(spec.to_yaml())
    assert again.digest() == spec.digest()


def test_request_carries_schema_and_no_sampling_params():
    client = fake_client({"fields": {}, "notes": [], "questions": []})
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
        "notes": [], "questions": [],
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
        "questions": [],
    })
    with pytest.raises(LLMCompileError, match="unknown field 'camera_angle'"):
        compile_prompt_llm("anything", client=client)


def test_model_cannot_claim_default_provenance():
    client = fake_client({
        "fields": {"altitude": {"value": 3000.0, "source": "default",
                                "from": "made up"}},
        "notes": [], "questions": [],
    })
    with pytest.raises(LLMCompileError, match="source"):
        compile_prompt_llm("anything", client=client)


def test_out_of_vocabulary_enum_is_an_error():
    client = fake_client({
        "fields": {"turbulence": entry("apocalyptic", "inferred", "hell")},
        "notes": [], "questions": [],
    })
    with pytest.raises(LLMCompileError, match="outside the vocabulary"):
        compile_prompt_llm("anything", client=client)


def test_unknown_aircraft_cannot_be_guessed_into_a_field():
    assert "SR71" not in FIELD_VALUE_SCHEMAS["aircraft"]["enum"]
    client = fake_client({
        "fields": {"aircraft": entry("SR71", "user", "the blackbird")},
        "notes": [], "questions": [],
    })
    with pytest.raises(LLMCompileError, match="outside the vocabulary"):
        compile_prompt_llm("anything", client=client)


def test_boolean_is_not_a_number():
    client = fake_client({
        "fields": {"altitude": {"value": True, "source": "user", "from": "x"}},
        "notes": [], "questions": [],
    })
    with pytest.raises(LLMCompileError, match="not a number"):
        compile_prompt_llm("anything", client=client)


def test_missing_provenance_phrase_is_an_error():
    client = fake_client({
        "fields": {"altitude": {"value": 3000.0, "source": "user", "from": "  "}},
        "notes": [], "questions": [],
    })
    with pytest.raises(LLMCompileError, match="no provenance phrase"):
        compile_prompt_llm("anything", client=client)


def test_extra_top_level_keys_are_an_error():
    client = fake_client({"fields": {}, "notes": [], "questions": [], "confidence": 0.9})
    with pytest.raises(LLMCompileError, match="top-level keys"):
        compile_prompt_llm("anything", client=client)


def test_refusal_stop_reason_is_an_error():
    client = fake_client({"fields": {}, "notes": [], "questions": []}, stop_reason="refusal")
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


# -- clarifying questions: one round, strict, bounded ----------------------

def question(qid="mountains", text="Which mountains?",
             options=("Matterhorn / Zermatt", "Yosemite Valley",
                      "a generic ridge")):
    return {"id": qid, "question": text, "options": list(options)}


def test_question_round_returns_questions_and_partial_fields():
    client = fake_client({
        "fields": {"wind_speed": entry(25.0, "inferred", "windy")},
        "notes": [],
        "questions": [question()],
    })
    result = compile_prompt_llm(
        "simulate an aircraft under windy conditions on a mountain",
        client=client)
    assert len(result.questions) == 1
    assert result.questions[0]["id"] == "mountains"
    assert result.questions[0]["options"][0] == "Matterhorn / Zermatt"
    # A question round is not an empty round: confident fields arrived and
    # the partial spec is honest to run as-is.
    assert float(result.spec.wind_speed.value) == 25.0
    assert str(result.spec.wind_speed.source) == "inferred"
    assert result.transcript is None


def test_answer_round_sends_the_transcript_and_finishes():
    questions = [question()]
    answer_from = 'answer to "Which mountains?": "Matterhorn"'
    client = fake_client({
        "fields": {
            "latitude": {"value": 46.005, "source": "user",
                         "from": answer_from},
            "longitude": {"value": 7.72, "source": "user",
                          "from": answer_from},
        },
        "notes": [], "questions": [],
    })
    result = compile_prompt_llm(
        "windy on a mountain", client=client, questions=questions,
        answers=[{"id": "mountains", "answer": "Matterhorn"}])

    # The conversation carried prompt, question turn, answer turn -- the
    # API-idiomatic shape, with the model's questions echoed verbatim.
    messages = client.captured["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert json.loads(messages[1]["content"])["questions"] == questions
    assert "Matterhorn" in messages[2]["content"]
    # An answered field is the user speaking, Q&A recorded in "from".
    assert str(result.spec.latitude.source) == "user"
    assert result.spec.latitude.frm == answer_from
    assert float(result.spec.latitude.value) == 46.005
    assert result.questions == ()
    assert result.transcript is not None and len(result.transcript) == 3


def test_second_round_questions_are_rejected_by_name():
    client = fake_client({"fields": {}, "notes": [],
                          "questions": [question()]})
    with pytest.raises(LLMCompileError, match="exactly one question round"):
        compile_prompt_llm("x", client=client, questions=[question()],
                           answers=[{"id": "mountains",
                                     "answer": "Matterhorn"}])


def test_more_than_three_questions_is_an_error():
    questions = [question(f"q{i}") for i in range(4)]
    client = fake_client({"fields": {}, "notes": [], "questions": questions})
    with pytest.raises(LLMCompileError, match="exceed the cap"):
        compile_prompt_llm("x", client=client)


def test_question_with_empty_options_is_an_error():
    bad = {"id": "q", "question": "Which?", "options": []}
    client = fake_client({"fields": {}, "notes": [], "questions": [bad]})
    with pytest.raises(LLMCompileError, match="no usable options"):
        compile_prompt_llm("x", client=client)


def test_question_missing_id_is_an_error():
    bad = {"question": "Which?", "options": ["a"]}
    client = fake_client({"fields": {}, "notes": [], "questions": [bad]})
    with pytest.raises(LLMCompileError, match="id/question/options"):
        compile_prompt_llm("x", client=client)


def test_missing_questions_key_is_an_error():
    client = fake_client({"fields": {}, "notes": []})
    with pytest.raises(LLMCompileError, match="top-level keys"):
        compile_prompt_llm("x", client=client)


def test_answered_field_cannot_claim_inferred():
    client = fake_client({
        "fields": {"latitude": {
            "value": 46.005, "source": "inferred",
            "from": 'answer to "Which mountains?": "Matterhorn"'}},
        "notes": [], "questions": [],
    })
    with pytest.raises(LLMCompileError, match="the user speaking"):
        compile_prompt_llm("x", client=client, questions=[question()],
                           answers=[{"id": "mountains",
                                     "answer": "Matterhorn"}])


def test_answers_without_questions_is_an_error():
    client = fake_client({"fields": {}, "notes": [], "questions": []})
    with pytest.raises(LLMCompileError, match="without the questions"):
        compile_prompt_llm("x", client=client,
                           answers=[{"id": "a", "answer": "b"}])


def test_same_final_spec_digests_identically_with_or_without_questions():
    """Determinism re-assert: the question round is prompt->spec plumbing;
    the SPEC stays the reproducible unit however it was arrived at."""
    final_fields = {
        "latitude": {"value": 46.005, "source": "user",
                     "from": 'answer to "Which mountains?": "Matterhorn"'},
        "wind_speed": {"value": 25.0, "source": "inferred", "from": "windy"},
    }
    direct = compile_prompt_llm(
        "windy on a mountain",
        client=fake_client({"fields": final_fields, "notes": [],
                            "questions": []})).spec
    answered = compile_prompt_llm(
        "windy on a mountain",
        client=fake_client({"fields": final_fields, "notes": [],
                            "questions": []}),
        questions=[question()],
        answers=[{"id": "mountains", "answer": "Matterhorn"}]).spec
    assert direct.digest() == answered.digest()


# -- key preflight: named, actionable, never leaking -----------------------

def test_missing_key_preflight_names_the_fix(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FLIGHTSIM_LLM", raising=False)
    with pytest.raises(LLMCompileError) as err:
        compile_prompt_llm("anything")   # client=None: the real entry path
    message = str(err.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "flightsim-web" in message and "uvicorn" in message
    assert "regex" in message            # the offline fallback is named
    # Presence-only check: no key exists here, and nothing key-shaped may
    # ever appear in the message.
    assert "sk-" not in message


def test_transport_error_text_carries_no_key_material(monkeypatch):
    sentinel = "sk-ant-TEST-SENTINEL-VALUE"
    monkeypatch.setenv("ANTHROPIC_API_KEY", sentinel)

    def create(**kwargs):
        raise ConnectionError("boom")

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(LLMCompileError) as err:
        compile_prompt_llm("anything", client=client)
    assert sentinel not in str(err.value)


def test_llm_available_is_a_presence_check(monkeypatch):
    from core.nl.llm_compiler import llm_available

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FLIGHTSIM_LLM", raising=False)
    assert llm_available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-TEST")
    assert llm_available() is True       # the SDK is installed in the venv
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("FLIGHTSIM_LLM", "ollama")
    assert llm_available() is True       # an alternate provider counts


# -- the world the compiler can render --------------------------------------

def test_system_prompt_carries_every_bake_with_exact_origins():
    from core.nl.llm_compiler import LOCATION_ALIASES, SYSTEM_PROMPT
    from core.terrain.glo30 import LOCATIONS

    for key, location in LOCATIONS.items():
        assert key in SYSTEM_PROMPT
        assert str(location.origin_lat) in SYSTEM_PROMPT
        assert str(location.origin_lon) in SYSTEM_PROMPT
        for alias in LOCATION_ALIASES[key]:
            assert alias in SYSTEM_PROMPT
    # A place the system cannot render is never in the block.
    assert "atlantis" not in SYSTEM_PROMPT.lower()


def test_locations_coverage_assert_fires_on_a_missing_bake():
    from core.nl.llm_compiler import (LOCATION_ALIASES,
                                      _assert_locations_covered)

    _assert_locations_covered({"matterhorn"}, LOCATION_ALIASES)
    with pytest.raises(AssertionError, match="atlantis"):
        _assert_locations_covered({"atlantis"}, LOCATION_ALIASES)


# -- alternate providers: same schema, same strict parse --------------------

def test_ollama_client_maps_the_anthropic_interface(monkeypatch):
    """The adapter carries system/messages/schema into Ollama's native API
    and returns the anthropic-shaped response the compiler reads."""
    from core.nl.providers import OllamaClient

    captured = {}

    def fake_post(self, path, payload):
        captured["path"], captured["payload"] = path, payload
        return {"message": {"content": '{"fields": {}, "notes": [], '
                                       '"questions": []}'},
                "model": "qwen2.5:7b"}

    monkeypatch.setattr(OllamaClient, "_post", fake_post)
    result = compile_prompt_llm("anything", client=OllamaClient(),
                                model="qwen2.5:7b")
    assert captured["path"] == "/api/chat"
    payload = captured["payload"]
    assert payload["model"] == "qwen2.5:7b"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][-1] == {"role": "user", "content": "anything"}
    # The compiler's OWN schema grammar-constrains the local model.
    assert payload["format"] is RESPONSE_SCHEMA
    assert payload["options"]["temperature"] == 0.0
    assert result.model == "qwen2.5:7b"
    # Defaults stay bit-identical to the regex compiler's, provider-agnostic.
    assert result.spec.digest() == compile_prompt("").digest()


def test_ollama_output_still_faces_the_strict_parser(monkeypatch):
    """A local model that ignores the schema is rejected exactly like a
    malformed Claude response -- the provider changes quality, not trust."""
    from core.nl.providers import OllamaClient

    monkeypatch.setattr(
        OllamaClient, "_post",
        lambda self, path, payload: {"message": {"content": "not json {"}})
    with pytest.raises(LLMCompileError, match="not valid JSON"):
        compile_prompt_llm("anything", client=OllamaClient())


def test_resolve_client_is_env_driven(monkeypatch):
    from core.nl.providers import OllamaClient, resolve_client

    monkeypatch.delenv("FLIGHTSIM_LLM", raising=False)
    assert resolve_client() is None
    monkeypatch.setenv("FLIGHTSIM_LLM", "ollama")
    client, model = resolve_client()
    assert isinstance(client, OllamaClient)
    assert model == "qwen2.5:7b"
    monkeypatch.setenv("FLIGHTSIM_LLM_MODEL", "qwen2.5:14b")
    assert resolve_client()[1] == "qwen2.5:14b"
    monkeypatch.setenv("FLIGHTSIM_LLM", "openai")
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        resolve_client()
    monkeypatch.setenv("FLIGHTSIM_LLM", "banana")
    with pytest.raises(ValueError, match="unknown FLIGHTSIM_LLM"):
        resolve_client()


def test_openai_compat_client_maps_the_interface(monkeypatch):
    from core.nl.providers import OpenAICompatClient

    captured = {}

    def fake_post(self, path, payload):
        captured["path"], captured["payload"] = path, payload
        return {"choices": [{"message": {"content":
                '{"fields": {}, "notes": [], "questions": []}'}}],
                "model": "llama-3.3-70b"}

    monkeypatch.setattr(OpenAICompatClient, "_post", fake_post)
    client = OpenAICompatClient("https://example.invalid/v1", api_key=None)
    result = compile_prompt_llm("anything", client=client,
                                model="llama-3.3-70b")
    assert captured["path"] == "/chat/completions"
    schema = captured["payload"]["response_format"]["json_schema"]["schema"]
    assert schema is RESPONSE_SCHEMA
    assert result.model == "llama-3.3-70b"


def test_hosted_free_provider_presets(monkeypatch):
    """The no-download fail-safe: FLIGHTSIM_LLM=groq/openrouter resolve to
    the right OpenAI-compatible endpoint with the key read from the named
    env var -- and refuse BY NAME with the signup URL when the key is
    absent, never guessing."""
    from core.nl.providers import resolve_client

    monkeypatch.setenv("FLIGHTSIM_LLM", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GROQ_API_KEY.*console.groq.com"):
        resolve_client()

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client, model = resolve_client()
    assert client.base_url == "https://api.groq.com/openai/v1"
    assert model == "llama-3.3-70b-versatile"

    monkeypatch.setenv("FLIGHTSIM_LLM", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client, model = resolve_client()
    assert client.base_url == "https://openrouter.ai/api/v1"
    assert model.endswith(":free")


def test_llm7_preset_is_keyless(monkeypatch):
    """The true zero-setup fail-safe: FLIGHTSIM_LLM=llm7 resolves with NO
    key in the environment (verified live against the real endpoint on
    2026-08-13; this test pins the wiring, not the network)."""
    from core.nl.providers import resolve_client

    monkeypatch.setenv("FLIGHTSIM_LLM", "llm7")
    monkeypatch.delenv("LLM7_API_KEY", raising=False)
    client, model = resolve_client()
    assert client.base_url == "https://api.llm7.io/v1"
    assert model == "gemini-3.1-flash-lite"


def test_relay_preset_is_keyless(monkeypatch):
    """The author-funded zero-setup tier: FLIGHTSIM_LLM=relay resolves with
    NO key in the environment (the OpenAI key lives server-side on the
    deployed relay, which pins the model itself; verified live against
    https://flightsim-relay.vercel.app on 2026-08-13 -- a request naming
    gpt-4o was served by gpt-4.1-mini. This test pins the wiring, not the
    network)."""
    from core.nl.providers import resolve_client

    monkeypatch.setenv("FLIGHTSIM_LLM", "relay")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FLIGHTSIM_RELAY_URL", raising=False)
    client, model = resolve_client()
    assert client.base_url == "https://flightsim-relay.vercel.app/v1"
    assert client._api_key is None
    assert model == "gpt-4.1-mini"

    # Pointing at your own deployment is one env var.
    monkeypatch.setenv("FLIGHTSIM_RELAY_URL", "https://example.dev/")
    client, model = resolve_client()
    assert client.base_url == "https://example.dev/v1"
