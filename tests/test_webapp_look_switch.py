"""The web app's look switch (webapp.runs.LOOK_SWITCHES): one word -- the
page's "look" option or "cinematic" / "beauty" in the prompt -- renders THIS
run at quality=beauty with the grade chosen from the sun and the weather,
and records it. Without the switch nothing changes: a label run stays on
the configured (measure) quality the gates were measured under."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import webapp.runs as runs
from core.nl.compiler import compile_prompt


def test_the_prompt_word_names_the_switch():
    assert runs.look_word_in_prompt("a Cinematic flight over the Alps") == "cinematic"
    assert runs.look_word_in_prompt("beauty shot of the 747 at dawn") == "beauty"
    # Whole words only: "beautiful" is not the switch.
    assert runs.look_word_in_prompt("a beautiful day") is None
    assert runs.look_word_in_prompt("fly the 747 at 280 kt") is None
    assert runs.look_word_in_prompt(None) is None
    # The first word written wins.
    assert runs.look_word_in_prompt("beauty, cinematic") == "beauty"


def test_the_page_option_wins_and_off_ignores_the_prompt():
    look = runs.resolve_look_switch("cinematic", "a beauty shot")
    assert look == {"switch": "cinematic", "quality": "beauty", "lens": "cinematic",
                    "source": "the page's look option"}
    assert runs.resolve_look_switch("off", "a cinematic flight") is None
    assert runs.resolve_look_switch(None, "fly the 747") is None
    prompted = runs.resolve_look_switch(None, "a BEAUTY pass")
    assert (prompted["switch"], prompted["quality"], prompted["lens"]) == (
        "beauty", "beauty", "standard")
    assert prompted["source"] == "the prompt word 'beauty'"
    with pytest.raises(ValueError, match="anamorphic"):
        runs.resolve_look_switch("anamorphic", None)


def test_without_the_switch_the_configured_quality_stands(monkeypatch):
    """The default for label runs is not this lane's to change."""
    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    assert runs.run_render_quality(None) == "measure"
    assert runs.run_render_quality(runs.resolve_look_switch("beauty", None)) == "beauty"
    assert runs.RENDER_QUALITIES["measure"] is None


def test_the_weather_defaults_are_the_owners():
    assert runs.WEATHER_DEFAULT_BACKEND == "procedural"
    assert runs.WEATHER_DEFAULT_GAIN == 4.0
    assert runs.WEATHER_DEFAULT_STYLE == "cinematic"


@pytest.mark.parametrize("prompt, look, grade", [
    # The harness's noon default sun (50 deg): desert_noon.
    ("fly the 747 at 280 kt", None, "desert_noon"),
    # A low sun: golden_hour.
    ("fly the 747 at 280 kt", {"sun_elev": 6.0}, "golden_hour"),
    # The storm weather: the storm grade, whatever the sun.
    ("fly the c172 into a thunderstorm", runs.STORM_LOOK, "storm"),
])
def test_the_switch_writes_the_sidecar_with_the_automatic_grade(
        tmp_path, monkeypatch, prompt, look, grade):
    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    switch = runs.resolve_look_switch("cinematic", prompt)
    path = runs.write_beauty_look_plan(compile_prompt(prompt), tmp_path, look,
                                       lens=switch["lens"], quality=switch["quality"])
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert sidecar["grade"] == grade
    assert sidecar["lens"] == "cinematic"
    # Neither lens moves pixels off the labels.
    assert sidecar["pixel_effects"]["pixel_moving"] == []
    # Without the switch, measure writes nothing.
    assert runs.write_beauty_look_plan(compile_prompt(prompt), tmp_path / "m", look) is None


def test_the_render_command_takes_the_runs_quality(tmp_path, monkeypatch):
    from tests.engine_launch import launch_through_run

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    captured = []
    launch_through_run(monkeypatch)
    monkeypatch.setattr(runs.subprocess, "run",
                        lambda command, **kw: captured.append(list(command)))
    spec = compile_prompt("fly the 747 at 280 kt")
    for quality in (None, "beauty"):
        runs.RunManager._render(tmp_path / "card.json", tmp_path / "frames",
                                {"key": "flat", "terrain": None, "imagery": None},
                                tmp_path / "missing_mesh.json", "B747",
                                camera_flags=runs.camera_render_flags(spec),
                                quality=quality)
    measure, beauty = captured
    assert "-quality=beauty" not in measure
    assert "-quality=beauty" in beauty
    assert any(token in beauty for token in ("-width=1920", "-ResX=1920"))
    # The storm weather rides both, the owner's default.
    for command in (measure, beauty):
        assert "-weather-backend=procedural" in command


@pytest.fixture
def run_client(monkeypatch):
    import core.util.platform as plat
    import webapp.server as server

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(server, "refuse_placeholder_mesh", lambda spec: None)
    monkeypatch.setattr(runs, "pick_scene",
                        lambda spec: {"key": "flat", "kind": "flat", "terrain": None,
                                      "imagery": None, "label": "flat (test)"})
    calls = []

    def fake_start(spec, provenance, **kwargs):
        calls.append(kwargs)
        return {"run_id": "looktest"}

    monkeypatch.setattr(server.manager, "start", fake_start)
    return TestClient(server.app), calls


def _compiled(client, prompt):
    return client.post("/compile", json={"prompt": prompt, "compiler": "regex"}).json()


def test_run_endpoint_passes_the_option_and_the_prompt_word(run_client):
    client, calls = run_client
    plain = _compiled(client, "fly the 747 at 3000 m and 250 kt")
    response = client.post("/run", json={"spec": plain["spec"]["dict"]})
    assert response.status_code == 200, response.text
    # No switch: the run starts exactly as before.
    assert calls[-1] == {} and "look" not in response.json()

    response = client.post("/run", json={"spec": plain["spec"]["dict"], "look": "cinematic"})
    assert response.status_code == 200, response.text
    assert calls[-1]["look"]["switch"] == "cinematic"
    assert response.json()["look"]["quality"] == "beauty"

    worded = _compiled(client, "a cinematic flight of the 747 at 3000 m and 250 kt")
    response = client.post("/run", json={"spec": worded["spec"]["dict"]})
    assert response.status_code == 200, response.text
    assert calls[-1]["look"]["source"] == "the prompt word 'cinematic'"

    response = client.post("/run", json={"spec": worded["spec"]["dict"], "look": "off"})
    assert response.status_code == 200, response.text
    assert calls[-1] == {}


def test_run_endpoint_refuses_an_unknown_look_by_name(run_client):
    client, calls = run_client
    response = client.post("/run", json={"look": "anamorphic"})
    assert response.status_code == 400
    assert "anamorphic" in response.json()["error"]
    assert calls == []


def test_the_page_offers_the_switch():
    from pathlib import Path

    page = (Path(runs.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="lookSwitch"' in page
    for value in ("cinematic", "beauty", "off"):
        assert f'<option value="{value}">' in page
    assert "body.look = look" in page


def test_the_run_state_carries_the_look():
    state = runs.RunState(run_id="x")
    assert state.as_dict()["look"] is None
    state.look = {**runs.resolve_look_switch("beauty", None),
                  "grade": "golden_hour", "grade_basis": "sun 6.0 deg, below 15 deg"}
    assert state.as_dict()["look"]["grade"] == "golden_hour"
    line = runs.look_condition(state.look)
    assert "look switch beauty" in line and "grade golden_hour" in line
    assert "VISUAL ONLY" in line
