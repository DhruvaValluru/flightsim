"""The web front door: compile, confirm, refuse, run -- §2.6 with a UI.

No test here launches an editor: the run manager's lock logic is exercised
against monkeypatched process checks, and the render pipeline itself is the
showcase machinery already covered by its own gates.
"""

from pathlib import Path

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

def test_clip_selector_is_a_user_edit_of_duration(client):
    """The UI's clip-length choice is an explicit USER edit of the run
    duration (the clip is min(duration, CLIP_SECONDS)), it wins over a
    duration stated in the prompt, and an out-of-range value refuses by
    name instead of clamping silently."""
    payload = client.post("/compile", json={
        "prompt": "fly the 747 at 3000 m and 250 kt for 90 seconds",
        "compiler": "regex", "clip_seconds": 6}).json()
    duration = next(f for f in payload["spec"]["fields"]
                    if f["name"] == "duration")
    assert duration["value"] == 6.0
    assert duration["source"] == "user"
    assert "selector" in duration["from"]

    refused = client.post("/compile", json={
        "prompt": "fly the 747", "compiler": "regex", "clip_seconds": 99})
    assert refused.status_code == 400
    assert "clip length" in refused.json()["error"]


def test_answer_round_keeps_the_question_rounds_decisions(client):
    """The protocol is stateless: round 2 re-extracts everything, so a
    field the model drops -- or the WHOLE round, when the LLM dies and the
    regex fallback compiles the original prompt -- silently reverted to
    its default (measured: an answered location question came back with
    round 1's settings gone). The page echoes round 1's spec; anything
    that round decided and round 2 left at default is restored with its
    provenance intact, and a fresh compile (no answers) ignores the echo.
    """
    round1 = client.post("/compile", json={
        "prompt": "fly the 747 at 5100 m and 260 kt",
        "compiler": "regex"}).json()

    round2 = client.post("/compile", json={
        "prompt": "fly the 747",
        "compiler": "regex",
        "answers": [{"id": "place", "answer": "the mountains"}],
        "prior_spec": round1["spec"]["dict"]}).json()
    altitude = next(f for f in round2["spec"]["fields"]
                    if f["name"] == "altitude")
    assert altitude["value"] == 5100.0
    assert altitude["source"] == "user"
    assert "kept from the question round" in altitude["from"]

    fresh = client.post("/compile", json={
        "prompt": "fly the 747", "compiler": "regex",
        "prior_spec": round1["spec"]["dict"]}).json()
    altitude = next(f for f in fresh["spec"]["fields"]
                    if f["name"] == "altitude")
    assert altitude["source"] != "user"


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
    # The lock logic is platform-independent CODE and stays covered on
    # every OS: force the platform gate open so the ue.platform refusal
    # (tested in test_platform.py) does not preempt the editor refusal.
    import core.util.platform as plat
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(runs_module, "editor_running", lambda: True)
    # Belt and braces: if the refusal is ever broken (the mutation check
    # breaks it ON PURPOSE), the accepted run must die here in the stub --
    # measured 2026-08-11: without this, the mutated run launched a REAL
    # UnrealEditor-Cmd render that outlived pytest and orphaned 660 frames
    # into runs/webapp.
    monkeypatch.setattr(RunManager, "_execute",
                        lambda self, run, spec, provenance: None)
    # About the editor lock, not the mesh rule or the scene: hold the
    # mesh gate open and pin the flat scene so this measures the same
    # thing on a machine with or without local bakes.
    import webapp.server as server_module
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    monkeypatch.setattr(runs_module, "pick_scene",
                        lambda spec: {"key": "flat", "kind": "flat",
                                      "terrain": None, "imagery": None,
                                      "label": "flat (test)"})
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
    # Same platform-gate override as the editor-lock test: the
    # concurrency rail is code under test on every OS.
    import core.util.platform as plat
    monkeypatch.setattr(plat, "ue_available", lambda: True)
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
    import webapp.server as server_module

    captured = {}

    def fake_start(spec, provenance):
        captured.update(provenance)
        return {"run_id": "test"}

    # About provenance forwarding, not the platform/mesh gates or the
    # scene: hold both gates open and pin the flat scene so this measures
    # the same thing on a machine with or without local bakes.
    import core.util.platform as plat
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    monkeypatch.setattr(runs_module, "pick_scene",
                        lambda spec: {"key": "flat", "kind": "flat",
                                      "terrain": None, "imagery": None,
                                      "label": "flat (test)"})

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
                             '"alpha_deg": [2.5, 2.6]}}', encoding="utf-8")
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
    }), encoding="utf-8")
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


def test_compile_table_shows_weather_event_planning(client):
    """What the user reviews is what will run: the event's environment
    composition (altitude descent, background inflow wind, turbulence
    word) appears in the /compile table as recorded derived edits, not as
    silent run-time surprises. The vortex itself remains a position-
    coupled field on top of this planned background."""
    payload = client.post("/compile", json={
        "prompt": "fly the c172p through a tornado",
        "compiler": "regex"}).json()
    fields = {f["name"]: f for f in payload["spec"]["fields"]}
    assert fields["altitude"]["value"] == 800.0
    assert fields["altitude"]["source"] == "derived"
    assert "vortex" in fields["altitude"]["from"]
    assert fields["wind_speed"]["value"] == 25.0         # composed background
    assert fields["wind_speed"]["source"] == "derived"
    assert fields["turbulence"]["value"] == "severe"
    assert payload["validation"]["ok"], payload["validation"]["violations"]

    storm = client.post("/compile", json={
        "prompt": "fly the b747 through a thunderstorm",
        "compiler": "regex"}).json()
    sf = {f["name"]: f for f in storm["spec"]["fields"]}
    assert sf["turbulence"]["value"] == "severe"
    assert sf["turbulence"]["source"] == "derived"


def test_flyable_defaults_are_planned_not_refused():
    """A prompt whose every number the SYSTEM chose is never refused over
    the system's own choices (measured 2026-08-13: everest raised a
    defaulted altitude into air where the defaulted 250 kt sits below the
    B747's measured Vs, and the page dead-ended). Planned defaults are
    recorded pre-digest edits with source ``derived``; a stated value is
    never moved and its refusal stands."""
    from core.scenario.validate import validate
    from webapp.runs import plan_flyable_defaults

    # Altitude floor: the location's terrain datum, raster-free.
    spec = compile_prompt("fly the 747")
    spec.set("terrain_elevation", 4750.0, frm="test: everest datum")
    plan_flyable_defaults(spec)
    assert float(spec.altitude.value) == 5050.0     # datum + 300 m planned
    assert str(spec.altitude.source) == "derived"   # still system-chosen

    # Airspeed floor: the model's own measured Vs at the final altitude.
    high = compile_prompt("fly the 747 at 9200 m")
    assert str(high.airspeed.source) == "default"
    plan_flyable_defaults(high)
    assert str(high.airspeed.source) == "derived"
    assert float(high.airspeed.value) > 260.0       # above 1.05 x Vs(9200 m)
    assert "measured stall speed" in high.airspeed.frm
    report = validate(high)                          # trim has the last word
    assert report.ok, report.violations

    # A STATED airspeed is never moved: the refusal is the answer.
    stated = compile_prompt("fly the 747 at 9200 m at 250 kt")
    plan_flyable_defaults(stated)
    assert float(stated.airspeed.value) == 250.0
    report = validate(stated, check_feasibility=False)
    assert not report.ok
    assert report.violations[0].constraint == "airspeed.stall_margin"

    # plan() itself refuses to touch the user's words.
    with pytest.raises(ValueError, match="never.*moved"):
        stated.plan("airspeed", 300.0, frm="should refuse")


def test_placeholder_airframes_never_render(client, monkeypatch):
    """Owner's rule (2026-08-14, extended 2026-08-31): an aircraft
    without a real licensed 3-D model refuses to render BY NAME on ANY
    machine -- a mesh-less fresh clone included ("always use a real
    model", measured on the first Windows deploy).

    NARROWED 2026-09-01: a model this machine can BUILD is no longer a
    refusal -- the render flow provisions it (tests/test_aircraft_assets.py
    pins that half). What still refuses here is what no command can fix:
    the f15 has no config, so there is nothing to fetch. The refusal
    names the airframes that can be built instead of an import command
    that would not help this one."""
    from webapp.runs import refuse_placeholder_mesh, renderable_aircraft

    spec = compile_prompt("fly the f15 at 5000 m and 350 kt")
    refusal = refuse_placeholder_mesh(spec)
    assert refusal is not None
    assert refusal["constraint"] == "aircraft.mesh"
    assert "f15" in refusal["message"]
    assert "B747" in refusal["message"]
    have = renderable_aircraft()
    if have:                    # with real models imported, those pass
        real = compile_prompt("fly the 747 at 3000 m and 250 kt")
        real.set("aircraft", have[0], frm="test: a model that IS imported")
        assert refuse_placeholder_mesh(real) is None

    # The endpoint wires the refusal as a named 409, whatever machine --
    # with the platform gate held open, since ue.platform is checked
    # first and would otherwise preempt the mesh refusal under test.
    import core.util.platform as plat
    import webapp.server as server_module
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: {"constraint": "aircraft.mesh",
                                      "message": "no real 3-D model"})
    spec = compile_prompt("fly the f15 at 5000 m and 350 kt")
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409
    assert reply.json()["refused"] == "aircraft.mesh"


def test_control_ridge_failsafe_synthesises_once(tmp_path, monkeypatch):
    """Owner's rule (2026-08-31): the synthesised control ridge is always
    available, so a scene the SYSTEM chose never falls through to the
    featureless slab just because nothing is baked yet (measured: a
    fresh Windows machine's mountains prompt rendered flat). Synthesises
    into runs/terrain exactly once, and only when missing."""
    import webapp.runs as runs

    calls = []

    class FakeField:
        def write(self, path):
            Path(str(path) + ".r16").write_bytes(b"synthesised")
            calls.append(str(path))

    def fake_generate(**kwargs):
        assert kwargs["seed"] == 6          # the showcase's exact ridge
        return FakeField()

    monkeypatch.setattr(runs, "REPO", tmp_path)
    monkeypatch.setattr("core.terrain.synthesis.generate", fake_generate)

    runs.ensure_control_ridge()
    ridge = tmp_path / "runs" / "terrain" / "control_ridge.r16"
    assert ridge.is_file()
    runs.ensure_control_ridge()             # idempotent: no re-synthesis
    assert len(calls) == 1


def test_platform_refusal_precedes_the_mesh_refusal(client, monkeypatch):
    """A machine with no engine build hears ue.platform, not
    aircraft.mesh. Measured 2026-08-31 on a fresh Windows clone: it was
    told to import aircraft models when the real blocker was that no
    Unreal host existed there at all. The engine is the more
    fundamental missing piece, so it refuses first."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(runs_module, "pick_scene",
                        lambda spec: {"key": "flat", "kind": "flat",
                                      "terrain": None, "imagery": None,
                                      "label": "flat (test)"})
    # An aircraft with no model on ANY machine: both refusals are live,
    # and the platform one must win.
    spec = compile_prompt("fly the f15 at 5000 m and 350 kt")
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409
    assert reply.json()["constraint"] == "ue.platform"

    # With an engine, the SAME spec falls through to the asset refusal.
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409
    assert reply.json()["refused"] == "aircraft.mesh"


def test_scene_setting_stages_unlocated_scenes():
    """No featureless slabs unless asked for: all-default coordinates are
    placed DETERMINISTICALLY on the fitting curated bake (the model
    proved erratic at this judgment). Stated places, flat/ocean opt-outs,
    and the unnamed-mountains generic ridge are untouched."""
    from core.terrain.glo30 import LOCATIONS
    from webapp.runs import plan_scene_setting

    bare = compile_prompt("fly the 747 at 3000 m and 250 kt")
    plan_scene_setting(bare)
    assert float(bare.latitude.value) == LOCATIONS["flint_hills"].origin_lat
    assert str(bare.latitude.source) == "derived"
    assert "scene-setting" in bare.latitude.frm

    desert = compile_prompt("fly the c172p over the desert at 2500 m")
    plan_scene_setting(desert)
    assert float(desert.latitude.value) == \
        LOCATIONS["grand_canyon"].origin_lat

    flat = compile_prompt("fly the 747 over flat ground at 3000 m")
    plan_scene_setting(flat)
    assert str(flat.latitude.source) == "default"      # asked for flat

    ocean = compile_prompt("fly the 747 over the ocean at 3000 m")
    plan_scene_setting(ocean)
    assert str(ocean.latitude.source) == "default"     # no ocean bake

    named = compile_prompt("fly the 747 at 5200 m")
    named.set("latitude", 45.9764, frm="stated place")
    named.set("longitude", 7.6586, frm="stated place")
    plan_scene_setting(named)
    assert float(named.latitude.value) == 45.9764      # stated place wins

    peaks = compile_prompt("fly the 747 at 5000 m over 2000 m mountains")
    plan_scene_setting(peaks)
    assert str(peaks.latitude.source) == "default"     # generic ridge kept


def test_ridge_axis_math_on_synthetic_rasters():
    """The axis computation is pinned on rasters whose orientation is
    KNOWN by construction: elevation varying only east-west is a
    north-south ridge (axis 0), only north-south an east-west ridge
    (axis 90), and the anti-diagonal ridge (col == row, which runs
    south-east as rows grow southward) sits at 135."""
    import numpy as np

    from webapp.runs import _ridge_axis_deg

    x = np.abs(np.arange(200) - 100)[None, :] * np.ones((200, 1))
    ns = (1000 - x * 5).clip(0).astype(np.uint16)
    assert abs(_ridge_axis_deg(ns, 1.0) - 0.0) < 0.5

    y = np.abs(np.arange(200) - 100)[:, None] * np.ones((1, 200))
    ew = (1000 - y * 5).clip(0).astype(np.uint16)
    assert abs(_ridge_axis_deg(ew, 1.0) - 90.0) < 0.5

    d = np.abs(np.arange(200)[None, :] - np.arange(200)[:, None])
    diag = (1000 - d * 5).clip(0).astype(np.uint16)
    assert abs(_ridge_axis_deg(diag, 1.0) - 135.0) < 0.5


def test_terrain_environment_planned_across_the_ridge():
    """Mountains-with-wind is physically different from flatland: the
    SYSTEM-CHOSEN wind is planned ACROSS the scene's principal ridge axis
    and the heading ALONG it, both recorded derived edits. A user-stated
    direction never moves, a calm spec gets no invented wind direction,
    and a flat scene is a no-op."""
    from webapp.runs import (REPO, place_on_scene, plan_terrain_environment,
                             _ridge_axis_deg)

    if not (REPO / "runs" / "terrain" / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    from core.terrain.heightfield import Heightfield

    axis = _ridge_axis_deg(
        *(lambda hf: (hf.samples, hf.scale_m))(
            Heightfield.read(REPO / "runs" / "terrain" / "control_ridge.r16")))

    spec = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains in a "
        "strong wind")
    assert str(spec.wind_direction.source) == "default"
    place_on_scene(spec)
    plan_terrain_environment(spec)
    assert str(spec.wind_direction.source) == "derived"
    assert "across ridge axis" in spec.wind_direction.frm
    assert abs(float(spec.wind_direction.value)
               - (axis + 90.0) % 360.0) < 0.51
    assert str(spec.heading.source) == "derived"
    assert "along ridge axis" in spec.heading.frm

    stated = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains with "
        "wind from 270 at 25 kt heading 045")
    assert str(stated.wind_direction.source) == "user"
    place_on_scene(stated)
    plan_terrain_environment(stated)
    assert float(stated.wind_direction.value) == 270.0   # never moved
    assert float(stated.heading.value) == 45.0           # never moved

    calm = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains")
    place_on_scene(calm)
    plan_terrain_environment(calm)
    assert str(calm.wind_direction.source) == "default"  # no invented wind

    flat = compile_prompt("fly the 747 at 3000 m and 250 kt")
    plan_terrain_environment(flat)
    assert str(flat.heading.source) == "default"         # flat: no-op


def test_default_airspeed_follows_a_model_chosen_aircraft():
    """The defaulted cruise is filled before the model decides the
    aircraft: 'a plane' -> c172p must not keep a B747's 250 kt default
    (measured -- TrimError). The still-default airspeed is re-planned to
    THIS airframe's documented cruise default."""
    from core.scenario.fields import Quantity, Source
    from webapp.runs import plan_flyable_defaults

    spec = compile_prompt("fly a plane at 2000 m")
    spec.aircraft = Quantity("c172p", None, Source.MODEL, frm="a plane")
    assert float(spec.airspeed.value) == 250.0    # the pre-aircraft default
    plan_flyable_defaults(spec)
    assert float(spec.airspeed.value) == 100.0    # c172p's own default
    assert str(spec.airspeed.source) == "derived"
    assert "documented cruise default" in spec.airspeed.frm


def test_trim_recovery_replans_an_unflyable_guess_once():
    """Physics keeps the last word over guesses: a model-guessed 120 kt
    is beyond the c172p's level-flight power at 2500 m (the stall floor
    cannot see an upper-envelope miss); ONE recorded re-plan to the
    documented cruise makes it fly. A user-stated condition is never
    touched -- its named refusal stands."""
    from core.scenario.fields import Quantity, Source
    from core.scenario.validate import validate
    from webapp.runs import plan_trim_recovery

    spec = compile_prompt("a small plane over the ridge")
    spec.aircraft = Quantity("c172p", None, Source.MODEL, frm="small plane")
    spec.altitude = Quantity(2500.0, "m", Source.MODEL, frm="over the ridge")
    spec.airspeed = Quantity(120.0, "kt", Source.MODEL, frm="a plane")
    assert not validate(spec).ok                  # the measured miss
    plan_trim_recovery(spec)
    assert float(spec.airspeed.value) == 100.0
    assert "could not be trimmed" in spec.airspeed.frm
    assert validate(spec).ok

    stated = compile_prompt("fly the c172p at 2500 m and 120 kt")
    assert str(stated.airspeed.source) == "user"
    plan_trim_recovery(stated)
    assert float(stated.airspeed.value) == 120.0  # never moved
    report = validate(stated)
    assert not report.ok                          # the refusal stands


def test_model_sourced_values_are_plannable():
    """A declared model guess is the system's choice: the planners may
    move it exactly like a default, and the guess plus the plan are both
    on record afterwards."""
    from core.scenario.fields import Quantity, Source
    from webapp.runs import plan_flyable_defaults

    spec = compile_prompt("fly the 747")
    spec.altitude = Quantity(100.0, "m", Source.MODEL, frm="right on the deck")
    spec.set("terrain_elevation", 4750.0, frm="test: everest datum")
    plan_flyable_defaults(spec)
    assert float(spec.altitude.value) == 5050.0
    assert str(spec.altitude.source) == "derived"


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


def test_terrain_airflow_is_coupled_when_there_is_wind_and_stated_when_not():
    """The mountains shape the air the plan flies through: a windy terrain
    spec pre-flies with the SAME orographic field the card will carry; a
    calm spec has honestly nothing to couple (orographic forcing is wind
    over terrain) and gets None, never an invented field."""
    from webapp.runs import _orographic_provider, place_on_scene

    if not (runs_module.REPO / "runs" / "terrain"
            / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    windy = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains "
        "in a strong crosswind")
    place_on_scene(windy)
    provider = _orographic_provider(windy, pick_scene(windy))
    assert provider is not None
    assert provider.wind_speed_mps > 0.0

    calm = compile_prompt("fly the 747 at 5000 m over 2000 m mountains")
    place_on_scene(calm)
    assert _orographic_provider(calm, pick_scene(calm)) is None


def test_clearance_track_is_wingspan_aware():
    """clearance_m is the minimum over the airframe's span stations, so a
    banked wingtip tightens the plan: the scripted S-turn track's minimum
    clearance is never above the CG-only figure, and strictly below it
    while the doublet holds a bank over sloping terrain."""
    from pathlib import Path as _Path

    from core.terrain.ground import TerrainGround
    from core.terrain.heightfield import Heightfield
    from experiments.showcase_matrix import SHOWCASE_DOUBLET
    from webapp.runs import _fly_clearance_track, place_on_scene

    if not (runs_module.REPO / "runs" / "terrain"
            / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    spec = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains")
    place_on_scene(spec)
    scene = pick_scene(spec)
    ground = TerrainGround(Heightfield.read(_Path(scene["terrain"])))
    track = _fly_clearance_track(spec, ground, SHOWCASE_DOUBLET, 12.0)
    # The span-aware figure can only be tighter than the CG-only one, and
    # while the doublet holds a bank over the ridge it is STRICTLY tighter
    # (a 747 wingtip hangs ~6 m below the CG at 11 degrees of roll).
    assert all(p["clearance_m"] <= p["cg_clearance_m"] + 1e-9 for p in track)
    assert (min(p["clearance_m"] for p in track)
            < min(p["cg_clearance_m"] for p in track))


def test_windy_terrain_run_card_carries_the_rotor(tmp_path, monkeypatch):
    """Lee-rotor turbulence rides the same orographic field the card
    carries (gotcha 14: the card word gates the turbulence writes, so the
    provider's own word 'lee-rotor' travels with its pinned properties);
    the seed is derived and recorded even when the spec's word is 'none',
    and the conditions strip states the coupling."""
    import json as jsonlib

    from webapp.runs import RunState, place_on_scene

    if not (runs_module.REPO / "runs" / "terrain"
            / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    spec = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains "
        "in a strong crosswind")
    place_on_scene(spec)
    assert str(spec.turbulence.value) == "none"

    # **kwargs so a new render argument (camera_flags, Phase 1) does
    # not silently break this stub on a machine WITH terrain baked,
    # which is the only place these tests reach _render at all.
    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera="chase", **kwargs):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        if telemetry is not None:
            # A plausible recorded run: the effect report needs the actual
            # telemetry to compare its headless baseline against.
            from webapp.runs import EFFECT_CHANNELS
            columns = {"t": [round(0.1 * i, 1) for i in range(220)]}
            for name in EFFECT_CHANNELS:
                columns[name] = [1.0 + 0.01 * (i % 7) for i in range(220)]
            telemetry.write_text(jsonlib.dumps({"columns": columns}), encoding="utf-8")
        return True

    monkeypatch.setattr(RunManager, "_render", staticmethod(fake_render))
    monkeypatch.setattr(runs_module, "encode_clip",
                        lambda frames, clip: bool(clip.write_bytes(b"x")) or True)
    monkeypatch.setattr(runs_module, "build_panel_clip",
                        lambda *a, **k: True)

    local = RunManager(out_root=tmp_path)
    run = RunState(run_id="rotortest")
    local._render_flow(run, spec, provenance={})
    assert run.status == "done", run.detail

    card = jsonlib.loads((tmp_path / "rotortest" / "card.json").read_text(encoding="utf-8"))
    assert card["turbulence"] == "lee-rotor"
    assert card["rotor"]["sigma_gain"] > 0.0
    assert card["turbulence_properties"]     # the provider's pinned writes
    assert "orographic" in card and "collision_terrain" in card
    assert str(spec.seed.source) != "default"      # derived, recorded
    assert "lee-rotor over terrain" in run.conditions["turbulence"]
    assert run.conditions["turbulence_seed"] == int(spec.seed.value)

    # The conditions-effect report: a headless still-air baseline of the
    # same spec beside the run's own telemetry, with the cross-host claim
    # stated. Coupled runs carry it; the calm test below asserts absence.
    effect = jsonlib.loads((tmp_path / "rotortest" / "effect.json").read_text(encoding="utf-8"))
    assert effect["samples"] > 0
    assert "severed" in effect["claim"] and "Gate 5" in effect["claim"]
    wind = effect["channels"]["wind_down_mps"]
    assert all(v == 0.0 for v in wind["baseline"])   # still air IS still
    assert effect["stats"]["n_z"]["baseline"]["rms"] >= 0.0


def test_calm_terrain_run_states_why_the_air_is_still(tmp_path, monkeypatch):
    """No wind, no orographic field, no rotor -- and the conditions strip
    SAYS so instead of leaving 'calm' to imply the mountains were felt."""
    import json as jsonlib

    from webapp.runs import RunState, place_on_scene

    if not (runs_module.REPO / "runs" / "terrain"
            / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    spec = compile_prompt("fly the 747 at 5000 m over 2000 m mountains")
    place_on_scene(spec)

    # **kwargs so a new render argument (camera_flags, Phase 1) does
    # not silently break this stub on a machine WITH terrain baked,
    # which is the only place these tests reach _render at all.
    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera="chase", **kwargs):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    monkeypatch.setattr(RunManager, "_render", staticmethod(fake_render))
    monkeypatch.setattr(runs_module, "encode_clip",
                        lambda frames, clip: bool(clip.write_bytes(b"x")) or True)
    monkeypatch.setattr(runs_module, "build_panel_clip",
                        lambda *a, **k: True)

    local = RunManager(out_root=tmp_path)
    run = RunState(run_id="calmtest")
    local._render_flow(run, spec, provenance={})
    assert run.status == "done", run.detail

    card = jsonlib.loads((tmp_path / "calmtest" / "card.json").read_text(encoding="utf-8"))
    assert "rotor" not in card and "orographic" not in card
    assert "no terrain-driven airflow" in run.conditions["wind_note"]
    # No coupling, no effect report -- a baseline identical to the run
    # would be a report about nothing.
    assert not (tmp_path / "calmtest" / "effect.json").exists()


def test_preflight_feels_the_orographic_field():
    """The plan flies through the same air as the run: with the orographic
    provider attached, the pre-flown track diverges from the still-air one
    (lift/sink moves the aircraft), so a plan through lee sink cannot come
    back identical to a plan through dead air."""
    from pathlib import Path as _Path

    from core.terrain.ground import TerrainGround
    from core.terrain.heightfield import Heightfield
    from experiments.showcase_matrix import SHOWCASE_DOUBLET
    from webapp.runs import (_fly_clearance_track, _orographic_provider,
                             place_on_scene)

    if not (runs_module.REPO / "runs" / "terrain"
            / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    spec = compile_prompt(
        "fly the 747 at 5000 m and 250 kt over 2000 m mountains "
        "in a strong crosswind")
    place_on_scene(spec)
    scene = pick_scene(spec)
    ground = TerrainGround(Heightfield.read(_Path(scene["terrain"])))
    provider = _orographic_provider(spec, scene)
    still = _fly_clearance_track(spec, ground, SHOWCASE_DOUBLET, 6.0)
    coupled = _fly_clearance_track(spec, ground, SHOWCASE_DOUBLET, 6.0,
                                   orographic=provider)
    deltas = [abs(a["clearance_m"] - b["clearance_m"])
              for a, b in zip(still, coupled)]
    assert max(deltas) > 0.01


def test_windy_terrain_run_digest_is_content_addressed(client, monkeypatch):
    """A windy terrain run is stochastic even with turbulence word 'none'
    (lee-rotor rides the orographic field), so /run derives its seed
    BEFORE answering the digest: the digest in the response must be the
    digest of the spec the worker actually receives, or the card would
    quietly content-address something else."""
    from webapp.server import manager

    if not (runs_module.REPO / "runs" / "terrain"
            / "control_ridge.r16").is_file():
        pytest.skip("no control ridge baked on this machine")

    captured = {}

    def fake_start(spec, provenance):
        captured["spec"] = spec
        return {"run_id": "digesttest"}

    monkeypatch.setattr(manager, "start", fake_start)
    # This test is about the digest, not the platform or mesh gates:
    # hold both open so it measures the same thing on every machine.
    import core.util.platform as plat
    import webapp.server as server_module
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 5000 m and 250 kt over 2000 m mountains "
                  "in a strong crosswind",
        "compiler": "regex"}).json()
    response = client.post("/run", json={"spec": compiled["spec"]["dict"]})
    assert response.status_code == 200, response.json()
    spec = captured["spec"]
    assert str(spec.turbulence.value) == "none"
    assert str(spec.seed.source) != "default"      # derived, recorded
    assert "derived from spec digest" in spec.seed.frm
    assert response.json()["digest"] == spec.digest()


def test_effect_report_served_only_after_completion(client, tmp_path,
                                                    monkeypatch):
    """Same gate as the telemetry endpoint: the file may exist on disk
    mid-flow, but it is not served until the run is done."""
    from webapp.runs import RunState
    from webapp.server import manager

    monkeypatch.setattr(manager, "out_root", tmp_path)
    run = RunState(run_id="fxtest")
    manager.runs["fxtest"] = run
    try:
        run.status = "report"
        path = tmp_path / "fxtest" / "effect.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"channels": {"t": [0.0]}, "samples": 1}', encoding="utf-8")
        assert client.get("/runs/fxtest/effect.json").status_code == 404

        run.status = "done"
        assert client.get("/runs/fxtest/effect.json").status_code == 200
        assert client.get("/runs/fxtest/effect.json").json()["samples"] == 1

        path.unlink()
        assert client.get("/runs/fxtest/effect.json").status_code == 404
    finally:
        del manager.runs["fxtest"]


def test_stated_coordinates_without_a_bake_refuse_by_name(client, monkeypatch):
    """USER-stated coordinates mean 'that real place': with no bake there,
    /run refuses terrain.unbaked (the page then bakes via /bake and runs
    again) -- never a silent flat slab standing in for a named place."""
    # Belt and braces (the mutation-check lesson): if the refusal is ever
    # broken, the accepted run dies in this stub instead of launching a
    # real render.
    monkeypatch.setattr(RunManager, "_execute",
                        lambda self, run, spec, provenance: None)
    compiled = client.post("/compile", json={
        "prompt": "fly the 747 at 9000 m and 250 kt", "compiler": "regex"}
    ).json()
    spec_dict = compiled["spec"]["dict"]
    for name, value in (("latitude", 51.5), ("longitude", -0.1)):
        spec_dict["initial"][name]["value"] = value
        spec_dict["initial"][name]["source"] = "user"
        spec_dict["initial"][name]["from"] = "stated in test"
    response = client.post("/run", json={"spec": spec_dict})
    assert response.status_code == 409
    payload = response.json()
    assert payload["refused"] == "terrain.unbaked"
    assert payload["latitude"] == 51.5
    assert "POST /bake" in payload["message"]


def test_bake_endpoint_registers_a_pickable_scene(client, monkeypatch,
                                                  tmp_path):
    """/bake -> bake_on_demand -> a scene sidecar pick_scene can find.
    The bake itself is stubbed (no network in the suite); the registry
    round-trip is what is under test."""
    import json as jsonlib

    from core.terrain.glo30 import dynamic_location
    from webapp.runs import _dynamic_scenes

    location = dynamic_location(51.5, -0.1)
    dynamic_dir = tmp_path / "dynamic"
    dynamic_dir.mkdir()
    (dynamic_dir / f"{location.key}.r16").write_bytes(b"\0\0")
    (dynamic_dir / f"{location.key}.scene.json").write_text(jsonlib.dumps({
        "key": location.key, "title": location.title,
        "origin_lat": 51.5, "origin_lon": -0.1, "crs": location.crs,
        "identity": "source-verified only (no named summits)"}), encoding="utf-8")
    scenes = _dynamic_scenes(dynamic_dir)
    assert len(scenes) == 1
    assert scenes[0]["key"] == location.key
    assert scenes[0]["terrain"].endswith(location.key)

    def fail_bake(lat, lon):
        raise RuntimeError("no tiles here (test)")

    monkeypatch.setattr("webapp.server.bake_on_demand", fail_bake)
    response = client.post("/bake", json={"latitude": 0.0,
                                          "longitude": -30.0})
    assert response.status_code == 502
    assert "no tiles here" in response.json()["error"]


def test_dated_spec_gets_reanalysis_wind_as_recorded_edits(client,
                                                           monkeypatch):
    """A weather_date pulls the ERA5 mean wind for the place/day/altitude
    as pre-digest spec edits with full provenance; a USER-stated wind is
    never moved; the control ridge (not a place) refuses by name. The
    fetch is stubbed -- no network in the suite."""
    from core.nl.compiler import compile_prompt
    from webapp.runs import apply_historical_weather

    def fake_fetch(lat, lon, date, altitude_m):
        return {"speed_kt": 42.0, "from_deg": 260.0, "level_hpa": 300,
                "level_note": "300 hPa (~9200 m)",
                "level_altitude_m": 9200.0, "hour_utc": 12,
                "source": "test stub"}

    monkeypatch.setattr("core.environment.era5.fetch_reanalysis_wind",
                        fake_fetch)

    spec = compile_prompt("fly the 747 at 9000 m and 250 kt on 2024-01-15")
    assert apply_historical_weather(spec) is None
    assert float(spec.wind_speed.value) == 42.0
    assert float(spec.wind_direction.value) == 260.0
    assert "historical weather 2024-01-15" in spec.wind_speed.frm

    stated = compile_prompt(
        "fly the 747 at 9000 m and 250 kt with a 30 kt crosswind "
        "on 2024-01-15")
    assert apply_historical_weather(stated) is None
    assert float(stated.wind_speed.value) == 30.0     # stated wind wins
    assert any("stated wind wins" in n for n in stated.notes)

    ridge = compile_prompt(
        "fly the 747 at 5000 m over 2000 m mountains on 2024-01-15")
    from webapp.runs import place_on_scene
    place_on_scene(ridge)
    refusal = apply_historical_weather(ridge)
    if refusal is not None:      # control ridge baked on this machine
        assert refusal["constraint"] == "weather.not_a_place"


def test_era5_level_selection_is_nearest_standard_level():
    from core.environment.era5 import nearest_pressure_level

    assert nearest_pressure_level(9000.0) == 300
    assert nearest_pressure_level(1500.0) == 850
    assert nearest_pressure_level(200.0) == 1000
