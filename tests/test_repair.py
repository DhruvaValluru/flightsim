"""The repair layer (core/nl/repair.py, POST /repair): a refused scenario
edited by the model -- or the trim rule when none is configured -- the
way the user wants, until it runs."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.nl.compiler import compile_prompt
from core.nl.repair import RepairError, kept_fields, repair_spec
from core.scenario.validate import validate


def fake_client(replies):
    """A model whose rounds reply with ``replies`` in turn."""
    replies = list(replies)
    captured = []

    def create(**kwargs):
        captured.append(kwargs)
        payload = replies.pop(0) if replies else {"edits": [], "note": "nothing more"}
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               stop_reason="end_turn", model="fake-model")

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.captured = captured
    return client


def test_the_instruction_names_the_fields_to_keep():
    assert kept_fields("keep the altitude") == ["altitude"]
    assert kept_fields("don't change the speed") == ["airspeed"]
    assert set(kept_fields("same altitude and heading")) == {"altitude", "heading"}
    assert kept_fields("make it fly") == []
    assert kept_fields("") == []


def test_the_model_repairs_a_refused_scenario_keeping_what_was_asked():
    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    assert not validate(spec).ok
    client = fake_client([{"edits": [{"field": "altitude", "value": 3000, "why": "within the ceiling"}],
                           "note": "lowered it"}])
    result = repair_spec(spec, "keep the speed", client=client, model="fake-model")
    assert result.ok and result.reader == "llm" and result.rounds == 1
    assert [e.to_dict()["field"] for e in result.edits] == ["altitude"]
    assert float(spec.altitude.value) == 3000.0 and str(spec.altitude.source) == "user"
    assert "repaired by the model (keep the speed)" in spec.altitude.frm
    assert float(spec.airspeed.value) == 100.0
    prompt_text = client.captured[0]["messages"][0]["content"]
    assert "airspeed = 100.0 kt (KEPT, never edit)" in prompt_text
    assert "cannot fly steadily" in prompt_text          # the refusal in plain words
    assert "change the altitude to" in prompt_text       # the trim rule's own suggestion


def test_an_edit_of_a_kept_field_is_refused_not_applied():
    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    client = fake_client([{"edits": [{"field": "altitude", "value": 3000, "why": "x"}], "note": ""}])
    with pytest.raises(RepairError, match="keeps"):
        repair_spec(spec, "keep the altitude", client=client, model="fake-model")
    assert float(spec.altitude.value) == 9000.0          # untouched


def test_a_second_round_follows_a_first_that_did_not_fix_it():
    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    client = fake_client([
        {"edits": [{"field": "altitude", "value": 8000, "why": "a little lower"}], "note": "try"},
        {"edits": [{"field": "altitude", "value": 3000, "why": "much lower"}], "note": "again"},
    ])
    result = repair_spec(spec, "", client=client, model="fake-model")
    assert result.ok and result.rounds == 2 and len(result.edits) == 2
    assert "still refused" in client.captured[1]["messages"][0]["content"]


def test_without_a_model_the_trim_rule_repairs_it(monkeypatch):
    monkeypatch.setenv("FLIGHTSIM_LLM", "none")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    result = repair_spec(spec, "keep the speed")
    assert result.reader == "rules" and result.ok
    assert result.edits[0].field == "altitude" and float(spec.airspeed.value) == 100.0
    held = compile_prompt("fly the c172 at 9000 m and 100 kt")
    result = repair_spec(held, "keep the altitude")
    assert result.reader == "rules" and not result.ok   # no speed trims a c172 at 9000 m
    assert float(held.altitude.value) == 9000.0


def test_a_scenario_that_already_runs_is_left_alone():
    spec = compile_prompt("fly the c172 at 900 m and 100 kt")
    result = repair_spec(spec, "keep everything", client=fake_client([]))
    assert result.ok and not result.edits and "already runs" in result.note


def test_the_endpoint_returns_the_spec_the_verdict_and_the_repair(monkeypatch):
    from fastapi.testclient import TestClient

    import core.nl.repair as repair
    from webapp.server import app

    monkeypatch.setattr(repair, "_resolve_client", lambda client, model: (
        fake_client([{"edits": [{"field": "altitude", "value": 3000, "why": "ceiling"}], "note": "ok"}]),
        "fake-model"))
    client = TestClient(app)
    compiled = client.post("/compile", json={"prompt": "fly the c172 at 9000 m and 100 kt",
                                            "compiler": "regex"}).json()
    assert not compiled["validation"]["ok"]
    spec_dict = {f["name"]: f for f in compiled["spec"]["fields"]}
    assert spec_dict["altitude"]["value"] == 9000.0
    # The page sends the spec dict it holds (the same shape /compile echoes).
    from core.scenario.spec import ScenarioSpec
    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    payload = client.post("/repair", json={"spec": spec.to_dict(), "instruction": "keep the speed"}).json()
    assert payload["validation"]["ok"] is True
    assert payload["repair"]["ok"] and payload["repair"]["reader"] == "llm"
    assert payload["repair"]["edits"][0]["field"] == "altitude"
    fields = {f["name"]: f for f in payload["spec"]["fields"]}
    assert fields["altitude"]["value"] == 3000.0 and fields["altitude"]["source"] == "user"


def test_three_fixes_are_offered_and_each_is_tried_against_the_check():
    """The owner (2026-10-09): "give 3 options on what to pick". The rules
    propose a speed change, an altitude change and the cruise speed for a
    trim refusal; each is tried on a copy and marked whether it passes."""
    from core.nl.repair import repair_options

    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    client = fake_client([{"options": [{"title": "a model idea",
                                        "edits": [{"field": "altitude", "value": 2500, "why": "low"}]}]}])
    result = repair_options(spec, "", client=client, model="fake-model")
    assert result["reader"] == "rules + model"
    assert 1 <= len(result["options"]) <= 3
    assert all(set(o) >= {"title", "edits", "ok", "remaining"} for o in result["options"])
    assert result["options"][0]["ok"] is True          # passing options come first
    assert float(spec.altitude.value) == 9000.0        # the spec itself is untouched


def test_a_clearance_refusal_offers_to_raise_the_altitude():
    """The owner's A-4 at 6000 (2026-10-09): the track came 571 m below the
    ground. The rule raises the altitude by the shortfall plus a margin,
    and the check the page's Run button uses decides whether it passes."""
    from core.nl.repair import apply_edits, rule_options
    from core.scenario.validate import Violation

    spec = compile_prompt("fly the a4 at 1000 m and 350 kt")
    clearance = Violation("terrain.clearance", "the planned track descends below the clearance margin",
                          actual=-571.4, limit=30.0, unit="m AGL")
    options = rule_options(spec, [clearance], [])
    assert [o["edits"][0]["field"] for o in options] == ["altitude", "altitude"]
    assert options[0]["edits"][0]["value"] == 1700.0 and options[1]["edits"][0]["value"] == 2100.0
    assert rule_options(spec, [clearance], ["altitude"]) == []    # a kept altitude: no such option
    calls = []

    def check(s):
        calls.append(float(s.altitude.value))
        return [] if float(s.altitude.value) >= 1700.0 else [clearance]

    result = apply_edits(spec, options[0]["edits"], "raise it", check=check)
    assert result.ok and result.reader == "picked" and calls == [1700.0]
    assert float(spec.altitude.value) == 1700.0 and "repaired by the model" in spec.altitude.frm


def test_the_options_endpoint_and_a_picked_option(monkeypatch):
    from fastapi.testclient import TestClient

    import core.nl.repair as repair
    from webapp.server import app

    monkeypatch.setattr(repair, "_resolve_client", lambda client, model: (fake_client([{"options": []}]), "fake"))
    client = TestClient(app)
    spec = compile_prompt("fly the c172 at 9000 m and 100 kt")
    options = client.post("/repair/options", json={"spec": spec.to_dict(), "instruction": "keep the speed"}).json()
    assert options["options"] and options["options"][0]["ok"]
    picked = options["options"][0]
    assert all(e["field"] != "airspeed" for e in picked["edits"])
    payload = client.post("/repair", json={
        "spec": spec.to_dict(), "instruction": "keep the speed",
        "edits": [{"field": e["field"], "value": e["to"], "why": e["why"]} for e in picked["edits"]]}).json()
    assert payload["validation"]["ok"] and payload["repair"]["reader"] == "picked"
