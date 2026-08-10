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
