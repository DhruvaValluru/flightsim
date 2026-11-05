"""E4: pressing Capture with nothing typed gives a working run.

``POST /run {}`` builds the default spec server-side (the c172p with
its own load, the Desert preset, one chase camera, a 6 s clip) and
runs the SAME planner order; the page's Capture button posts ``{}`` when
nothing is compiled. The weather flags and the Google tiles are not
edited by the default run (decision 4, CLAUDE.md)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import webapp.runs as runs_module  # noqa: E402
import webapp.server as server_module  # noqa: E402
from core.nl.compiler import CRUISE_DEFAULT_KT, compile_prompt  # noqa: E402
from core.scenario.camera import CHASE_OFFSETS, CameraSpec  # noqa: E402
from core.scenario.card import google_tiles_requested  # noqa: E402
from webapp.runs import (  # noqa: E402
    AIRCRAFT_PICK_FROM, CLIP_SECONDS, DEFAULT_RUN_AIRCRAFT, DEFAULT_RUN_FROM,
    DEFAULT_RUN_PROMPT, RunManager, apply_aircraft_choice, default_run_spec,
    weather_backend_flags, webapp_chase_flag,
)
from webapp.server import app  # noqa: E402

INDEX_HTML = REPO / "webapp" / "static" / "index.html"
FLAT_SCENE = {"key": "flat", "kind": "flat", "terrain": None,
              "imagery": None, "label": "flat (test)"}


@pytest.fixture
def client():
    return TestClient(app)


def test_empty_run_body_is_not_422(client, monkeypatch):
    """RunRequest.spec is optional: an empty body is the default run,
    never a validation error. The engine gate is left open and the run
    is stopped at the planner's last step so no flight starts here."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(runs_module, "needs_dynamic_bake", lambda spec: None)
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module.manager, "start",
                        lambda spec, provenance: {"refused": "stopped by the test",
                                                  "constraint": "test.stop"})
    reply = client.post("/run", json={})
    assert reply.status_code != 422, reply.text
    assert reply.json().get("constraint") == "test.stop"


def test_default_spec_is_c172p_desert_chase_6s():
    spec = default_run_spec()
    assert str(spec.aircraft.value) == "c172p"
    assert str(spec.aircraft.source) == "user"
    assert spec.aircraft.frm == DEFAULT_RUN_FROM
    # The Cessna flies its own config's load: the default run states none.
    assert str(spec.loading.payload.source) != "user"
    # The Desert preset: surface, the grand_canyon origin and July noon.
    assert str(spec.surface.value) == "desert"
    assert str(spec.latitude.source) == "user"
    assert "desert -> grand_canyon" in spec.latitude.frm
    assert str(spec.time_of_day.value).startswith("2026-07-15T12:00")
    # One chase camera with the per-airframe offset the render flag uses.
    assert len(spec.cameras) == 1
    camera = spec.cameras[0]
    assert str(camera.camera_id.value) == "camera0"
    assert str(camera.preset.value) == "chase"
    offset = (float(camera.offset_forward_m.value),
              float(camera.offset_right_m.value),
              float(camera.offset_up_m.value))
    assert webapp_chase_flag("c172p") == f"{offset[0]:g}:{offset[1]:g}:{offset[2]:g}"
    # A 6 s clip, under the cap, as a recorded USER edit.
    assert float(spec.duration.value) == 6.0 <= CLIP_SECONDS
    assert str(spec.duration.source) == "user"
    assert DEFAULT_RUN_FROM in spec.duration.frm
    # The spec round-trips through the page's dict form unchanged.
    again = type(spec).from_dict(spec.to_dict())
    assert again.loading.payload.value == spec.loading.payload.value
    assert len(again.cameras) == 1


def test_default_spec_leaves_tiles_and_storm_on(monkeypatch):
    """Decision 4 / CLAUDE.md: the default run edits neither the weather
    flags nor the Google tiles; both read their defaults."""
    for name in ("FLIGHTSIM_WEATHER_BACKEND", "FLIGHTSIM_RAIN_GAIN",
                 "FLIGHTSIM_RAIN_STYLE", "FLIGHTSIM_GOOGLE_TILES"):
        monkeypatch.delenv(name, raising=False)
    before = weather_backend_flags()
    assert before == ["-weather-backend=procedural", "-rain-gain=4",
                      "-rain-style=cinematic"]
    assert google_tiles_requested() is True
    spec = default_run_spec()
    assert weather_backend_flags() == before
    assert google_tiles_requested() is True
    # The default spec has no weather event of its own: the storm comes
    # from the render flags, not from a spec edit.
    assert str(spec.weather_event.source) != "user"


def test_default_spec_dated_clock_resolves_the_sun():
    """The Desert preset's clock carries core.sky.plan's ISO date prefix;
    the render's sun look reads the date from it and the sun from the
    clock (measured: it refused the prefix as an unknown time of day)."""
    from webapp.runs import sun_look

    look = sun_look(default_run_spec())
    assert look is not None
    assert look["sun_elev"] > 60.0            # July noon over the canyon
    assert "2026-07-15" in look["note"]


def _wait_for_run(client, run_id: str, timeout_s: float = 600.0):
    deadline = time.time() + timeout_s
    state = client.get(f"/runs/{run_id}").json()
    while state["status"] not in ("done", "failed") and time.time() < deadline:
        time.sleep(1.0)
        state = client.get(f"/runs/{run_id}").json()
    return state


def test_empty_run_headless_reaches_done_no_fail(client, monkeypatch, tmp_path):
    """No engine on this host: POST /run {} is not refused ue.platform
    (the default spec states a camera) and the run captures headlessly
    to done with no FAIL in the capture verify."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(runs_module, "ensure_aircraft_model",
                        lambda spec, report: None)
    # The grand_canyon bake is not on every clone: the bake check is held
    # open and the scene is the slab, which the headless capture accepts.
    monkeypatch.setattr(runs_module, "needs_dynamic_bake", lambda spec: None)
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "manager", RunManager(out_root=tmp_path))
    reply = client.post("/run", json={})
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert "run_id" in payload, payload
    state = _wait_for_run(client, payload["run_id"])
    assert state["status"] == "done", state["detail"]
    assert state["capture"] is not None and state["capture"]["headless"] is True
    failed = [c["name"] for c in state["capture"]["checks"]
              if c["status"] == "FAIL"]
    assert failed == [], failed
    assert "FAILED" not in state["detail"]


def test_ue_platform_refusal_still_fires_for_cameraless_spec(client, monkeypatch):
    """Narrowing the gate to camera specs weakens nothing: a spec without
    cameras on a host without the engine still hears ue.platform, with
    the same body as before."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "pick_scene", lambda spec: FLAT_SCENE)
    spec = compile_prompt("fly the a-4 at 3000 m and 300 kt")
    assert not spec.cameras
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 409
    body = reply.json()
    assert body["constraint"] == "ue.platform"
    assert body["refused"] == plat.ue_platform_refusal()


def test_capture_button_enabled_and_posts_empty_body():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert '<button id="run" class="run">Capture</button>' in html
    assert '<button id="run" class="run">Run</button>' not in html
    # Enabled on load: no disabled attribute in the markup, and the only
    # toggles are renderVerdict's for the edited-table path.
    assert 'id="run" class="run" disabled' not in html
    assert html.count('$("run").disabled = true;') == 1
    assert html.count('$("run").disabled = false;') == 1
    start = html.index("async function startRun(mayBake)")
    body = html[start:html.index("const payload = await response.json();", start)]
    assert "compiled == null ? {} :" in body
    assert "JSON.stringify(body)" in body


# -- the aircraft picker (box P1) ------------------------------------------

def _hold_engine_open(monkeypatch):
    """The test_empty_run_body_is_not_422 gate: every spec /run would start
    is collected instead, so a test reads the spec that would have flown."""
    import core.util.platform as plat

    started = []

    def start(spec, provenance):
        started.append(spec)
        return {"refused": "stopped by the test", "constraint": "test.stop"}

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(runs_module, "needs_dynamic_bake", lambda spec: None)
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module.manager, "start", start)
    return started


def test_get_aircraft_lists_the_pickable_aircraft(client):
    reply = client.get("/aircraft")
    assert reply.status_code == 200
    body = reply.json()
    assert body["default"] == DEFAULT_RUN_AIRCRAFT
    titles = {entry["name"]: entry["title"] for entry in body["aircraft"]}
    assert {"c172p", "A4", "J11"} <= set(titles)
    assert titles["c172p"] == "Cessna 172P Skyhawk"
    assert titles["A4"] == "Douglas A-4E Skyhawk"
    assert titles["J11"] == "Shenyang J-11A"
    assert "p51d" not in titles            # its config states why it cannot render


def test_run_with_aircraft_flies_it_at_its_own_cruise(client, monkeypatch):
    started = _hold_engine_open(monkeypatch)
    reply = client.post("/run", json={"aircraft": "J11"})
    assert reply.json().get("constraint") == "test.stop", reply.text
    spec = started[0]
    assert str(spec.aircraft.value) == "J11"
    assert str(spec.aircraft.source) == "user"
    assert spec.aircraft.frm == AIRCRAFT_PICK_FROM
    assert float(spec.airspeed.value) == CRUISE_DEFAULT_KT["J11"]
    assert float(spec.altitude.value) == 3500.0
    assert spec.to_dict()["aircraft"]["aircraft"]["value"] == "J11"
    # The rest of the default run stays: Desert, one chase camera, 6 s.
    assert str(spec.surface.value) == "desert"
    assert [str(c.preset.value) for c in spec.cameras] == ["chase"]
    assert float(spec.duration.value) == 6.0


def test_run_with_unknown_aircraft_is_400_naming_the_accepted(client):
    for body in ({"aircraft": "hindenburg"},
                 {"aircraft": "hindenburg", "spec": compile_prompt("fly the a-4").to_dict()}):
        reply = client.post("/run", json=body)
        assert reply.status_code == 400, reply.text
        error = reply.json()["error"]
        assert "hindenburg" in error and "c172p" in error and "J11" in error
    # Not offered is not accepted: the p51d may never render.
    assert client.post("/run", json={"aircraft": "p51d"}).status_code == 400


def test_run_with_no_aircraft_field_is_unchanged(client, monkeypatch):
    started = _hold_engine_open(monkeypatch)
    client.post("/run", json={})
    spec = started[0]
    assert str(spec.aircraft.value) == DEFAULT_RUN_AIRCRAFT
    assert spec.aircraft.frm == DEFAULT_RUN_FROM
    assert spec.prompt == DEFAULT_RUN_PROMPT
    assert float(spec.airspeed.value) == 100.0
    assert default_run_spec().digest() == default_run_spec(None).digest()


def test_an_aircraft_the_picker_does_not_offer_is_refused_and_never_switched(client, monkeypatch):
    """The DHC6 has no labels block, so it is not offered; asking for it is a
    400 naming what is, and nothing flies in its place."""
    started = _hold_engine_open(monkeypatch)
    reply = client.post("/run", json={"aircraft": "DHC6"})
    assert reply.status_code == 400, reply.text
    assert "c172p" in reply.text
    assert started == []


def test_compile_applies_the_picked_aircraft_over_the_prompt(client):
    reply = client.post("/compile", json={
        "prompt": "fly the a-4 at 3000 m over the desert", "compiler": "regex",
        "aircraft": "J11"})
    assert reply.status_code == 200, reply.text
    spec = type(default_run_spec()).from_dict(reply.json()["spec"]["dict"])
    assert str(spec.aircraft.value) == "J11"
    assert spec.aircraft.frm == AIRCRAFT_PICK_FROM
    plain = client.post("/compile", json={"prompt": "fly the a-4 at 3000 m",
                                          "compiler": "regex"})
    assert plain.json()["spec"]["dict"]["aircraft"]["aircraft"]["value"] == "A4"
    refused = client.post("/compile", json={"prompt": "fly the a-4", "compiler": "regex",
                                            "aircraft": "hindenburg"})
    assert refused.status_code == 400
    assert "hindenburg" in refused.json()["error"] and "J11" in refused.json()["error"]


def test_a_stated_speed_stays_and_a_planned_one_follows_the_aircraft():
    stated = compile_prompt("fly the c172p at 3000 m and 110 kt")
    apply_aircraft_choice(stated, "J11")
    assert float(stated.airspeed.value) == 110.0
    assert str(stated.airspeed.source) == "user"
    planned = compile_prompt("fly the c172p at 3000 m")
    planned.cameras = [CameraSpec.defaulted(camera_id="camera0", preset="chase",
                                            aircraft="c172p")]
    apply_aircraft_choice(planned, "A4")
    assert float(planned.airspeed.value) == CRUISE_DEFAULT_KT["A4"]
    camera = planned.cameras[0]
    assert (float(camera.offset_forward_m.value), float(camera.offset_up_m.value)) \
        == (CHASE_OFFSETS["A4"][0], CHASE_OFFSETS["A4"][2])


def test_picking_an_aircraft_leaves_tiles_and_storm_on(monkeypatch):
    for name in ("FLIGHTSIM_WEATHER_BACKEND", "FLIGHTSIM_RAIN_GAIN",
                 "FLIGHTSIM_RAIN_STYLE", "FLIGHTSIM_GOOGLE_TILES"):
        monkeypatch.delenv(name, raising=False)
    before = weather_backend_flags()
    default_run_spec("J11")
    assert weather_backend_flags() == before
    assert google_tiles_requested() is True


def test_the_page_mounts_the_picker_and_posts_only_a_real_pick(client):
    script = client.get("/aircraft_picker.js")
    assert script.status_code == 200
    assert "aircraftPreset" in script.text and 'fetch("/aircraft")' in script.text
    page = client.get("/").text
    assert 'id="aircraftPicker"' in page and "/aircraft_picker.js" in page
    assert page.count("aircraft: aircraftPreset()") == 2      # Interpret, answer round
    assert "if (aircraft) body.aircraft = aircraft;" in page


def test_the_picker_offers_only_aircraft_a_capture_can_label():
    from webapp.runs import pickable_aircraft

    names = {entry["name"] for entry in pickable_aircraft()}
    assert {"c172p", "J11", "A4"} <= names and "DHC6" not in names

