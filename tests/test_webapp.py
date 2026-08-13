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
    # Belt and braces: if the refusal is ever broken (the mutation check
    # breaks it ON PURPOSE), the accepted run must die here in the stub --
    # measured 2026-08-11: without this, the mutated run launched a REAL
    # UnrealEditor-Cmd render that outlived pytest and orphaned 660 frames
    # into runs/webapp.
    monkeypatch.setattr(RunManager, "_execute",
                        lambda self, run, spec, provenance: None)
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


def test_compile_table_shows_weather_event_planning(client):
    """What the user reviews is what will run: the tornado's defaulted-
    altitude descent (and a thunderstorm's turbulence word) appear in the
    /compile table as recorded derived edits, not as silent run-time
    surprises. Ambient wind stays honestly untouched -- the vortex is a
    position-coupled field, not a uniform wind."""
    payload = client.post("/compile", json={
        "prompt": "fly the c172p through a tornado",
        "compiler": "regex"}).json()
    fields = {f["name"]: f for f in payload["spec"]["fields"]}
    assert fields["altitude"]["value"] == 800.0
    assert fields["altitude"]["source"] == "derived"
    assert "vortex" in fields["altitude"]["from"]
    assert fields["wind_speed"]["value"] == 0.0          # not a uniform wind
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

    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None, look=None, camera="chase"):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}")
        if telemetry is not None:
            # A plausible recorded run: the effect report needs the actual
            # telemetry to compare its headless baseline against.
            from webapp.runs import EFFECT_CHANNELS
            columns = {"t": [round(0.1 * i, 1) for i in range(220)]}
            for name in EFFECT_CHANNELS:
                columns[name] = [1.0 + 0.01 * (i % 7) for i in range(220)]
            telemetry.write_text(jsonlib.dumps({"columns": columns}))
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

    card = jsonlib.loads((tmp_path / "rotortest" / "card.json").read_text())
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
    effect = jsonlib.loads((tmp_path / "rotortest" / "effect.json").read_text())
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

    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None, look=None, camera="chase"):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}")
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

    card = jsonlib.loads((tmp_path / "calmtest" / "card.json").read_text())
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
        path.write_text('{"channels": {"t": [0.0]}, "samples": 1}')
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
        "identity": "source-verified only (no named summits)"}))
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
