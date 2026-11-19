"""The AI rewrites the prompt: a vague one is expanded, one that cannot run
is fixed and kept only when it runs (core/nl/prompt_assist.py, POST /compile
assist). No network: a stand-in client answers."""

import json

import pytest
from fastapi.testclient import TestClient

import core.nl.prompt_assist as pa
import webapp.server as server
from core.nl.llm_compiler import LLMCompileError


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Client:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        reply = self.replies.pop(0)
        return type("R", (), {"content": [_Block(json.dumps(reply))]})()


@pytest.fixture
def app(monkeypatch):
    def offline(*a, **k):
        raise LLMCompileError("offline in tests")
    monkeypatch.setattr(server, "compile_prompt_llm", offline)
    monkeypatch.setattr(server, "llm_available", lambda: True)
    monkeypatch.setattr(server, "_prefetch", lambda spec: None)
    return TestClient(server.app)


def _use(monkeypatch, replies):
    client = _Client(replies)
    monkeypatch.setattr(pa, "_client", lambda c=None, m=None: (client, "stand-in"))
    return client


def test_vague_prompts_are_told_apart():
    assert pa.is_vague("a plane flying")
    assert pa.is_vague("fly a jet")
    assert not pa.is_vague("An A-4E Skyhawk over the Grand Canyon at 9,000 feet at sunset")


def test_a_low_prompt_is_fixed_and_the_page_is_told(app, monkeypatch):
    low = "an A-4E Skyhawk over the Grand Canyon at 500 ft in the afternoon"
    first = server._compile_problems(app.post("/compile", json={"prompt": low}).json())
    assert first, "the low prompt must not run, or this test proves nothing"
    client = _use(monkeypatch, [{"prompt": "an A-4E Skyhawk over the Grand Canyon at "
                                           "10,000 ft in the afternoon",
                                 "explanation": "raised the altitude above the rim"}])
    data = app.post("/compile", json={"prompt": low, "assist": True}).json()
    assert data["assist"]["original"] == low
    assert "10,000 ft" in data["assist"]["prompt"]
    assert data["assist"]["steps"][0]["kind"] == "fixed"
    assert data["assist"]["unresolved"] == []
    assert server._compile_problems(data) == []
    assert "Problems:" in client.calls[0]["messages"][0]["content"]


def test_a_fix_that_still_fails_is_not_kept(app, monkeypatch):
    low = "an A-4E Skyhawk over the Grand Canyon at 500 ft in the afternoon"
    _use(monkeypatch, [{"prompt": low.replace("500", "600"), "explanation": "x"},
                       {"prompt": low.replace("500", "700"), "explanation": "y"}])
    data = app.post("/compile", json={"prompt": low, "assist": True}).json()
    assert data["assist"]["prompt"] == low
    assert data["assist"]["steps"] == []
    assert data["assist"]["unresolved"]


def test_a_vague_prompt_is_expanded(app, monkeypatch):
    _use(monkeypatch, [{"prompt": "An A-4E Skyhawk over Yosemite Valley at 12,000 ft at "
                                  "golden hour, chase view",
                        "explanation": "picked a place, altitude, time and view"}])
    data = app.post("/compile", json={"prompt": "a plane flying", "assist": True}).json()
    assert data["assist"]["steps"][0]["kind"] == "expanded"
    assert "Yosemite" in data["assist"]["prompt"]


def test_without_assist_the_prompt_is_never_touched(app, monkeypatch):
    client = _use(monkeypatch, [])
    data = app.post("/compile", json={"prompt": "a plane flying"}).json()
    assert "assist" not in data and client.calls == []


def test_no_model_leaves_the_verdict_alone(app, monkeypatch):
    monkeypatch.setattr(pa, "_client", lambda c=None, m=None: (None, None))
    data = app.post("/compile", json={"prompt": "a plane flying", "assist": True}).json()
    assert "spec" in data


def test_an_aircraft_without_a_model_is_named_so_the_ai_swaps_it(app, monkeypatch):
    prompt = "an A-4E Skyhawk over the ocean at 8,000 ft in the afternoon"
    data = app.post("/compile", json={"prompt": prompt}).json()
    assert server._compile_problems(data) == []
    monkeypatch.setattr(server, "refuse_placeholder_mesh",
                        lambda spec: {"sentence": "no licensed 3-D model"})
    problems = server._compile_problems(data)
    assert len(problems) == 1 and "no 3-D model" in problems[0]
