"""The web front door: compile, confirm, refuse, run -- §2.6 with a UI.

No test here launches an editor: the run manager's lock logic is exercised
against monkeypatched process checks, and the render pipeline itself is the
showcase machinery already covered by its own gates.
"""

import pytest
from fastapi.testclient import TestClient

import webapp.runs as runs_module
from core.nl.compiler import compile_prompt
from webapp.runs import RunManager, derive_seed, pick_scene
from webapp.server import app, manager


@pytest.fixture()
def client():
    return TestClient(app)


# -- /compile --------------------------------------------------------------

def test_compile_returns_provenanced_fields_and_verdict(client):
    response = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt in a strong crosswind",
        "compiler": "regex"})
    payload = response.json()
    assert payload["compiler"] == "regex"
    assert payload["validation"]["ok"] is True
    wind = next(f for f in payload["spec"]["fields"]
                if f["name"] == "wind_speed")
    assert wind["value"] == 25.0
    assert wind["source"] == "inferred"
    # The dict round-trips through /run: same schema as ScenarioSpec.to_dict.
    assert payload["spec"]["dict"]["environment"]["wind_speed"]["value"] == 25.0


def test_compile_renders_refusals_by_name(client):
    response = client.post("/compile", json={
        "prompt": "fly the 747 at 500 m over 2000 m terrain",
        "compiler": "regex"})
    verdict = response.json()["validation"]
    assert verdict["ok"] is False
    assert [v["constraint"] for v in verdict["violations"]] == [
        "altitude.terrain_clearance"]


def test_compile_states_llm_fallback(client, monkeypatch):
    from core.nl.llm_compiler import LLMCompileError

    def unavailable(prompt, **kwargs):
        raise LLMCompileError("no key on this machine")

    monkeypatch.setattr("webapp.server.compile_prompt_llm", unavailable)
    response = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m", "compiler": "llm"})
    payload = response.json()
    assert payload["compiler"] == "regex (llm unavailable)"
    assert "no key" in payload["llm_note"]


# -- /run ------------------------------------------------------------------

def test_run_revalidates_and_refuses_by_name(client):
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 500 m over 2000 m terrain",
        "compiler": "regex"}).json()
    response = client.post("/run", json={"spec": compiled["spec"]["dict"]})
    assert response.status_code == 409
    assert response.json()["refused"] == "validation"
    assert response.json()["violations"][0]["constraint"] == \
        "altitude.terrain_clearance"


def test_run_refuses_while_editor_is_owned(client, monkeypatch):
    monkeypatch.setattr(runs_module, "editor_running", lambda: True)
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt", "compiler": "regex"}
    ).json()
    response = client.post("/run", json={"spec": compiled["spec"]["dict"]})
    assert response.status_code == 409
    assert "editor" in response.json()["refused"]


def test_run_rejects_malformed_spec(client):
    response = client.post("/run", json={"spec": {"nonsense": True}})
    assert response.status_code == 400
    assert "did not parse" in response.json()["error"]


def test_edited_field_changes_digest_and_records_the_edit(client):
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt", "compiler": "regex"}
    ).json()
    spec_dict = compiled["spec"]["dict"]
    spec_dict["initial"]["altitude"]["value"] = 4000.0
    spec_dict["initial"]["altitude"]["source"] = "user"
    spec_dict["initial"]["altitude"]["from"] = "edited in the web UI"
    from core.scenario.spec import ScenarioSpec

    edited = ScenarioSpec.from_dict(spec_dict)
    assert edited.digest() != compiled["spec"]["digest"]
    assert float(edited.altitude.value) == 4000.0
    assert str(edited.altitude.source) == "user"


# -- run manager policies --------------------------------------------------

def test_pick_scene_reuses_the_matterhorn_bake():
    spec = compile_prompt("fly the 747 at 5200 m and 250 kt")
    spec.set("latitude", 45.9766, frm="test")   # matterhorn origin vicinity
    spec.set("longitude", 7.6585, frm="test")
    scene = pick_scene(spec)
    # The bake is reused only when it exists on this machine AND the origin
    # sits on it; otherwise the honest fallback applies.
    if scene["key"] == "matterhorn":
        assert "GLO-30" in scene["kind"]
        assert scene["terrain"] is not None
    else:
        assert scene["key"] in ("control", "flat")


def test_pick_scene_mountainous_without_location_is_the_control_ridge():
    spec = compile_prompt("fly the 747 at 4000 m over 2000 m mountains")
    scene = pick_scene(spec)
    assert scene["key"] in ("control", "flat")
    if scene["key"] == "control":
        assert "synthesised" in scene["kind"]


def test_pick_scene_flat_carries_no_scenery_claim():
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    scene = pick_scene(spec)
    assert scene["key"] == "flat"
    assert scene["terrain"] is None


def test_derive_seed_only_touches_defaulted_turbulent_specs():
    turbulent = compile_prompt("fly the 747 at 3000 m in moderate turbulence")
    assert str(turbulent.seed.source) == "default"
    derive_seed(turbulent)
    assert str(turbulent.seed.source) == "user"   # set() records the override
    assert turbulent.seed.frm == "derived from spec digest"

    calm = compile_prompt("fly the 747 at 3000 m and 250 kt")
    derive_seed(calm)
    assert str(calm.seed.source) == "default"

    stated = compile_prompt("fly the 747 at 3000 m in moderate turbulence")
    stated.set("seed", 424242, frm="user asked")
    derive_seed(stated)
    assert int(stated.seed.value) == 424242


def test_manager_refuses_second_concurrent_run(monkeypatch):
    monkeypatch.setattr(runs_module, "editor_running", lambda: False)
    local = RunManager()
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")

    # Occupy the manager without launching anything real.
    monkeypatch.setattr(RunManager, "_execute",
                        lambda self, run, spec, provenance: None)
    first = local.start(spec, provenance={})
    assert "run_id" in first
    second = local.start(spec, provenance={})
    assert "refused" in second


def test_run_manager_projects_the_spec_for_the_ue_host():
    """A compiled spec defaults hold_state True (the headless closure
    default); the UE hosts have no autopilot and refuse a held state
    (measured -- Gate 8.3's first run). The projection is reference_spec's
    own, applied and recorded."""
    from webapp.runs import project_for_ue_host

    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    assert bool(spec.hold_state.value) is True
    project_for_ue_host(spec)
    assert bool(spec.hold_state.value) is False
    assert "no autopilot" in spec.hold_state.frm
    assert bool(spec.mass_held.value) is True


# -- clarifying questions through the front door ---------------------------

def test_status_reports_llm_availability(client):
    payload = client.get("/status").json()
    assert isinstance(payload["llm_available"], bool)


def test_compile_question_round_trip(client, monkeypatch):
    from core.nl.llm_compiler import LLMCompileResult

    calls = {}

    def fake_llm(prompt, questions=None, answers=None, **kwargs):
        calls["questions"], calls["answers"] = questions, answers
        spec = compile_prompt(prompt)
        if answers is None:
            spec.set("wind_speed", 25.0, frm="windy")
            return LLMCompileResult(
                spec=spec, model="test-model", raw_response="{}",
                questions=({"id": "mountains",
                            "question": "Which mountains?",
                            "options": ["Matterhorn / Zermatt",
                                        "a generic ridge"]},))
        spec.set("latitude", 46.005,
                 frm='answer to "Which mountains?": "Matterhorn"')
        return LLMCompileResult(
            spec=spec, model="test-model", raw_response="{}",
            transcript=({"role": "user", "content": prompt},
                        {"role": "assistant", "content": "q"},
                        {"role": "user", "content": "a"}))

    monkeypatch.setattr("webapp.server.compile_prompt_llm", fake_llm)

    first = client.post("/compile", json={
        "prompt": "windy on a mountain"}).json()
    assert first["needs_clarification"] is True
    assert first["questions"][0]["id"] == "mountains"
    assert first["questions"][0]["options"][0] == "Matterhorn / Zermatt"
    # The partial spec/verdict payload rides under the questions.
    assert first["spec"]["fields"] and first["validation"]
    assert first["transcript"] is None

    second = client.post("/compile", json={
        "prompt": "windy on a mountain",
        "questions": first["questions"],
        "answers": [{"id": "mountains", "answer": "Matterhorn"}]}).json()
    assert calls["questions"] == first["questions"]
    assert calls["answers"] == [{"id": "mountains", "answer": "Matterhorn"}]
    assert second["needs_clarification"] is False
    assert second["questions"] == []
    assert len(second["transcript"]) == 3
    latitude = next(f for f in second["spec"]["fields"]
                    if f["name"] == "latitude")
    assert latitude["source"] == "user"
    assert latitude["from"].startswith("answer to")


def test_llm_death_on_answer_round_falls_back_to_the_original_prompt(
        client, monkeypatch):
    """The regex compiler never asks and never sees answers: a mid-flow LLM
    failure compiles the ORIGINAL prompt offline, stated as such."""
    from core.nl.llm_compiler import LLMCompileError

    def dead(prompt, **kwargs):
        raise LLMCompileError("the key vanished between rounds")

    monkeypatch.setattr("webapp.server.compile_prompt_llm", dead)
    payload = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt",
        "questions": [{"id": "q", "question": "?", "options": ["a"]}],
        "answers": [{"id": "q", "answer": "a"}]}).json()
    assert payload["compiler"] == "regex (llm unavailable)"
    assert "vanished" in payload["llm_note"]
    assert payload["needs_clarification"] is False
    altitude = next(f for f in payload["spec"]["fields"]
                    if f["name"] == "altitude")
    assert altitude["value"] == 3000.0   # the original prompt, regex-parsed


def test_run_forwards_the_transcript_into_provenance(client, monkeypatch):
    from webapp.server import manager

    captured = {}

    def fake_start(spec, provenance):
        captured.update(provenance)
        return {"run_id": "test"}

    monkeypatch.setattr(manager, "start", fake_start)
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt",
        "compiler": "regex"}).json()
    response = client.post("/run", json={
        "spec": compiled["spec"]["dict"],
        "provenance": {"compiler": "llm", "model": "m",
                       "transcript": [{"role": "user", "content": "hi"}],
                       "evil_extra": 1}})
    assert response.status_code == 200
    assert captured["transcript"] == [{"role": "user", "content": "hi"}]
    assert "evil_extra" not in captured


def test_llm_matterhorn_response_lands_on_the_real_bake(monkeypatch):
    """A mocked 'Matterhorn' response uses the generated locations block's
    exact origin, so the spec lands inside pick_scene's tolerance window and
    the real bake is selected (when baked on this machine)."""
    import json as jsonlib
    from types import SimpleNamespace

    from core.nl.llm_compiler import compile_prompt_llm
    from core.terrain.glo30 import LOCATIONS
    from webapp.runs import LOCATION_TOLERANCE_DEG, REPO

    location = LOCATIONS["matterhorn"]
    payload = jsonlib.dumps({
        "fields": {
            "latitude": {"value": location.origin_lat, "source": "inferred",
                         "from": "the matterhorn"},
            "longitude": {"value": location.origin_lon, "source": "inferred",
                          "from": "the matterhorn"},
            "terrain_elevation": {"value": 1860.0, "source": "inferred",
                                  "from": "the matterhorn"},
        },
        "notes": [], "questions": []})
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=payload)],
        stop_reason="end_turn", model="test-model")
    mock = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kwargs: response))

    spec = compile_prompt_llm("a cessna over the matterhorn",
                              client=mock).spec
    assert abs(float(spec.latitude.value) - location.origin_lat) \
        <= LOCATION_TOLERANCE_DEG
    assert abs(float(spec.longitude.value) - location.origin_lon) \
        <= LOCATION_TOLERANCE_DEG
    scene = pick_scene(spec)
    if (REPO / "runs" / "terrain" / "matterhorn.r16").is_file():
        assert scene["key"] == "matterhorn"
        assert "GLO-30" in scene["kind"]
    else:
        assert scene["key"] in ("control", "flat")


def test_run_telemetry_served_only_after_completion(client, tmp_path,
                                                    monkeypatch):
    """The aero panel's data source: the recorder's own file, passed through
    verbatim, 404 before the run completes (like the clip)."""
    from webapp.runs import RunState
    from webapp.server import manager

    monkeypatch.setattr(manager, "out_root", tmp_path)
    run = RunState(run_id="teletest")
    manager.runs["teletest"] = run
    try:
        run.status = "rendering"
        telemetry = tmp_path / "teletest" / "telemetry.json"
        telemetry.parent.mkdir(parents=True)
        telemetry.write_text('{"columns": {"t": [0.0, 0.1], '
                             '"alpha_deg": [2.5, 2.6]}}')
        # Not done yet -> 404 even though the file exists on disk.
        assert client.get("/runs/teletest/telemetry.json").status_code == 404

        run.status = "done"
        response = client.get("/runs/teletest/telemetry.json")
        assert response.status_code == 200
        payload = response.json()
        # The recorder's own samples, unresampled.
        assert payload["columns"]["t"] == [0.0, 0.1]
        assert payload["columns"]["alpha_deg"] == [2.5, 2.6]

        telemetry.unlink()
        assert client.get("/runs/teletest/telemetry.json").status_code == 404
    finally:
        del manager.runs["teletest"]


def test_completed_run_survives_a_server_restart(tmp_path):
    """A finished clip on disk is served by a FRESH manager (measured: a
    restart landed mid-run and orphaned the page's poll)."""
    import json as jsonlib

    out = tmp_path / "abc123def456"
    out.mkdir()
    (out / "clip.mp4").write_bytes(b"not-a-real-clip")
    (out / "provenance.json").write_text(jsonlib.dumps({
        "spec_digest": "d" * 64,
        "scene": {"key": "flat", "label": "flat slab"},
        "reference_speeds": {"vs_kt": 176.0},
        "conditions": {"wind_note": "calm"},
    }))
    fresh = RunManager(out_root=tmp_path)
    run = fresh.get("abc123def456")
    assert run is not None and run.status == "done"
    assert run.clip.endswith("clip.mp4")
    assert run.reference == {"vs_kt": 176.0}
    assert run.conditions == {"wind_note": "calm"}
    # An interrupted run (no clip) is NOT resurrected -- there is no
    # worker thread to resume it, and pretending otherwise would lie.
    (out / "clip.mp4").unlink()
    assert RunManager(out_root=tmp_path).get("abc123def456") is None
    # Path safety: ids are hex only.
    assert fresh.get("../../etc") is None


def test_control_ridge_spec_is_placed_on_the_ridge():
    """A mountainous spec with the default 0,0 origin moves to the control
    ridge's centre (measured: it rendered empty sky from 500 km away),
    recorded in provenance; specs that earn a real bake or the flat slab
    are untouched."""
    from webapp.runs import REPO, place_on_scene

    if not (REPO / "runs" / "terrain" / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    spec = compile_prompt("fly the 747 at 4000 m over 2000 m mountains")
    assert float(spec.latitude.value) == 0.0
    place_on_scene(spec)
    assert float(spec.latitude.value) != 0.0 or float(spec.longitude.value) != 0.0
    assert "control ridge centre" in spec.latitude.frm
    # The placed spec still earns the same scene.
    assert pick_scene(spec)["key"] == "control"

    flat = compile_prompt("fly the 747 at 3000 m and 250 kt")
    place_on_scene(flat)
    assert float(flat.latitude.value) == 0.0
    assert str(flat.latitude.source) == "default"


def test_terrain_run_is_planned_for_clearance():
    """Terrain runs fly in coordination with the terrain (measured: a
    3000 m default flew THROUGH 3299 m ridge peaks over a flat slab): a
    DEFAULTED altitude is raised to clear the pre-flown track, recorded;
    a USER-stated altitude that cannot keep the margin is refused by
    name, never silently moved."""
    from webapp.runs import (REPO, place_on_scene, plan_terrain_flight,
                             pick_scene)

    if not (REPO / "runs" / "terrain" / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    spec = compile_prompt(
        "fly the 747 at 250 kt over 2000 m mountains in a strong crosswind")
    assert str(spec.altitude.source) == "default"
    place_on_scene(spec)
    assert plan_terrain_flight(spec) is None
    assert "raised to clear" in spec.altitude.frm
    assert float(spec.altitude.value) > 3000.0

    stated = compile_prompt(
        "fly the 747 at 2500 m and 250 kt over 2000 m mountains")
    place_on_scene(stated)
    refusal = plan_terrain_flight(stated)
    assert refusal is not None
    assert refusal["constraint"] == "terrain.clearance"
    assert float(stated.altitude.value) == 2500.0   # never silently moved

    flat = compile_prompt("fly the 747 at 3000 m and 250 kt")
    assert plan_terrain_flight(flat) is None        # no terrain, no plan
