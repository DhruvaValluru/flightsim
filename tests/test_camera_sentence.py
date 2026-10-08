"""The camera reader's wider control: placement scaled to the airframe,
the scene shown to the model, edits of an existing camera, lens, aim and
moves -- on the camera-sentence box (core.nl.camera_prompt) and on the
main prompt's LLM compiler (core.nl.llm_compiler).

No test touches the network: the model is a canned client throughout.
"""

import json
import math
from types import SimpleNamespace

import pytest

from core.capture.poses import SceneFrame, solve_pose_track
from core.nl.camera_prompt import (
    CameraPromptError, build_camera, framing_distances,
    intent_from_dict, parse_intent_llm, parse_intent_rules, scene_context,
)
from core.nl.compiler import compile_prompt, describe_moves
from core.nl.llm_compiler import (LLMCompileError, SYSTEM_PROMPT,
                                  compile_prompt_llm)
from core.scenario.blocks import TrafficSpec
from core.scenario.camera import CHASE_OFFSETS, CameraSpec


def fake_client(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               stop_reason="end_turn", model="fake-model")

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.captured = captured
    return client


def entry(value, source="user", frm="stated"):
    return {"value": value, "source": source, "from": frm}


def spec_for(aircraft="c172p"):
    return compile_prompt(f"fly the {aircraft} at 1000 m for 20 seconds")


def with_traffic(spec, ahead=200.0, right=150.0):
    other = TrafficSpec.defaulted(str(spec.aircraft.value), frm="test")
    other.set("track", "offset", frm="test")
    for name, value in (("ahead_m", ahead), ("right_m", right),
                        ("up_m", 0.0), ("speed_delta_kt", 0.0)):
        other.set(name, value, frm="test")
    spec.traffic = [other]
    return spec


def intent(**kwargs):
    base = {"view": "follow", "anchor": "primary", "forward_m": -30.0,
            "right_m": 0.0, "up_m": 5.0, "show_all": True,
            "quote": "behind", "note": ""}
    base.update(kwargs)
    return base


# -- distances scale with the airframe ------------------------------------

def test_distance_words_scale_with_the_calibrated_chase_framing():
    small, big = framing_distances("c172p"), framing_distances("B747")
    assert small["default"] == abs(CHASE_OFFSETS["c172p"][0]) == 28.0
    assert big["default"] == 110.0
    assert small["close"] == pytest.approx(0.6 * 28.0)
    assert small["far"] == pytest.approx(4 * 28.0)
    assert small["chase_up"] == CHASE_OFFSETS["c172p"][2]


def test_the_rule_reader_places_behind_a_cessna_at_its_chase_distance():
    spec = spec_for("c172p")
    behind = parse_intent_rules("behind the plane", spec)
    assert behind.forward_m == -28.0 and behind.up_m == 4.0
    far = parse_intent_rules("far behind", spec)
    assert far.forward_m == pytest.approx(-112.0)
    stated = parse_intent_rules("300 m behind", spec)
    assert stated.forward_m == -300.0


# -- show_all: the rule reader's always-true expression ---------------------

def test_show_all_follows_the_sentence_not_a_constant():
    spec = with_traffic(spec_for())
    assert parse_intent_rules("behind", spec).show_all is True
    assert parse_intent_rules("close behind, only the main plane",
                              spec).show_all is False
    assert parse_intent_rules("just the lead aircraft from the left",
                              spec).show_all is False
    assert parse_intent_rules("above both planes", spec).show_all is True


def test_the_rule_reader_reads_lens_aim_and_moves():
    spec = spec_for()
    read = parse_intent_rules("telephoto from the left, looking north, "
                              "orbit", spec)
    assert read.focal_length_mm == 85.0
    assert (read.aim, read.aim_bearing_deg, read.aim_elevation_deg) == \
        ("bearing", 0.0, 0.0)
    assert read.moves == ["orbit"]
    assert parse_intent_rules("a 200 mm lens behind", spec).focal_length_mm == 200.0
    assert parse_intent_rules("cockpit view", spec).view == "cockpit"


# -- the model sees the scene ---------------------------------------------

def test_the_model_is_told_the_airframe_distances_and_the_cameras():
    spec = with_traffic(spec_for())
    spec.cameras.append(CameraSpec.defaulted(camera_id="chase", preset="chase",
                                             aircraft="c172p"))
    text = scene_context(spec)
    assert "c172p" in text and "default 28" in text and "close 16.8" in text
    assert "- chase: view follow" in text and "lens 35 mm" in text
    assert "200 m ahead" in text
    client = fake_client(intent())
    parse_intent_llm("behind", spec, client=client)
    assert "Distance table" in client.captured["messages"][0]["content"]
    assert client.captured["output_config"]["format"]["schema"][
        "properties"]["moves"]["items"]["enum"]


def test_the_strict_parse_refuses_bad_optional_fields_by_name():
    with pytest.raises(CameraPromptError, match="moves"):
        intent_from_dict(intent(moves=["barrel_roll"]))
    with pytest.raises(CameraPromptError, match="focal_length_mm"):
        intent_from_dict(intent(focal_length_mm=-5))
    with pytest.raises(CameraPromptError, match="aim"):
        intent_from_dict(intent(aim="mountain"))
    with pytest.raises(CameraPromptError, match="unknown"):
        intent_from_dict(intent(roll_deg=10))
    read = intent_from_dict(intent(edit_camera_id="", moves=["zoom_in",
                                                              "zoom_in"]))
    assert read.edit_camera_id is None and read.moves == ["zoom_in"]


# -- building: lens, aim, moves, edits ------------------------------------

def test_a_stated_lens_is_never_widened_to_fit_the_traffic():
    spec = with_traffic(spec_for())
    read = intent_from_dict(intent(focal_length_mm=85.0))
    camera, notes = build_camera(spec, read, "prompt")
    assert float(camera.focal_length_mm.value) == 85.0
    assert str(camera.focal_length_mm.source) == "user"
    assert float(camera.offset_forward_m.value) < -30.0   # pulled back instead
    assert any("85 mm lens is kept" in n for n in notes)


def test_a_bearing_aim_with_no_bearing_looks_along_the_heading():
    spec = spec_for()
    camera, notes = build_camera(spec, intent_from_dict(intent(aim="bearing")),
                                 "prompt")
    assert str(camera.aim_mode.value) == "bearing"
    assert float(camera.aim_bearing_deg.value) == float(spec.heading.value) % 360
    assert any("heading" in n for n in notes)


def test_an_edit_keeps_lens_schedule_and_moves_and_rekeys_them():
    spec = spec_for()
    first, _ = build_camera(spec, intent_from_dict(intent(
        forward_m=-40.0, focal_length_mm=50.0, moves=["orbit"])), "prompt")
    first.set("capture_count", 12, frm="test")
    first.set("trigger", "interval", frm="test")
    assert describe_moves(first.moves) == ["orbit"]
    closer = intent_from_dict(intent(forward_m=-24.0, edit_camera_id="prompt"))
    camera, notes = build_camera(spec, closer, "prompt", existing=first)
    assert str(camera.camera_id.value) == "prompt"
    assert float(camera.focal_length_mm.value) == 50.0
    assert camera.capture_count.value == 12
    assert describe_moves(camera.moves) == ["orbit"]
    assert camera.moves[0]["offset_forward_m"] == -24.0
    stopped, _ = build_camera(spec, intent_from_dict(intent(
        forward_m=-24.0, moves=[])), "prompt", existing=first)
    assert stopped.moves == []


def test_describe_moves_reads_back_every_documented_shape():
    spec = spec_for()
    for kind in ("zoom_in", "zoom_out", "push_in", "pull_back", "orbit"):
        camera, _ = build_camera(spec, intent_from_dict(intent(moves=[kind])),
                                 "prompt")
        assert describe_moves(camera.moves) == [kind]


def test_the_endpoint_replaces_an_edited_camera_in_place(monkeypatch):
    from fastapi.testclient import TestClient

    import core.nl.llm_compiler as llm
    import core.nl.providers as providers
    from webapp.server import app

    spec = spec_for()
    spec.cameras.append(CameraSpec.defaulted(camera_id="chase", preset="chase",
                                             aircraft="c172p"))
    reply = intent(forward_m=-17.0, edit_camera_id="chase",
                   quote="a bit closer")
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(providers, "resolve_client",
                        lambda: (fake_client(reply), "fake-model"))
    response = TestClient(app).post("/cameras/prompt", json={
        "spec": spec.to_dict(), "prompt": "a bit closer"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["camera_prompt"]["edited"] is True
    assert [c["camera_id"] for c in payload["cameras"]] == ["chase"]
    fields = {f["name"]: f for f in payload["cameras"][0]["fields"]}
    assert fields["offset_forward_m"]["value"] == -17.0
    assert fields["offset_forward_m"]["source"] == "user"


# -- the pose solver honours a following camera's aim ----------------------

def test_a_chase_camera_with_a_bearing_aim_looks_along_it():
    columns = {name: [] for name in ("t", "lat_deg", "lon_deg", "altitude_m",
                                     "roll_deg", "pitch_deg", "heading_deg")}
    for i in range(101):
        t = i * 0.1
        for name, value in (("t", t), ("lat_deg", 100.0 * t / 111_320.0),
                            ("lon_deg", 0.0), ("altitude_m", 1000.0),
                            ("roll_deg", 0.0), ("pitch_deg", 0.0),
                            ("heading_deg", 0.0)):
            columns[name].append(value)
    camera = CameraSpec.defaulted(camera_id="chase", preset="chase",
                                  aircraft="B747")
    camera.set("aim_mode", "bearing")
    camera.set("aim_bearing_deg", 90.0)
    camera.set("aim_elevation_deg", -30.0)
    track = solve_pose_track(columns, camera,
                             SceneFrame("EPSG:32631", 0.0, 0.0, declared=True))
    assert all(math.isclose(y, 90.0) for y in track.yaw_deg)
    assert all(math.isclose(p, -30.0) for p in track.pitch_deg)
    # ...while still following the aircraft north.
    assert track.north_m[-1] - track.north_m[0] > 500.0


# -- the main prompt's LLM compiler -----------------------------------------

def payload(cameras, fields=None):
    return {"fields": fields or {"aircraft": entry("c172p", "inferred", "Cessna")},
            "notes": [], "questions": [], "cameras": cameras,
            "randomization": {}, "traffic": []}


def test_the_system_prompt_carries_the_calibrated_chase_table():
    assert "c172p: D = 28 m behind, 4 m up" in SYSTEM_PROMPT
    assert "B747: D = 110 m behind" in SYSTEM_PROMPT


def test_the_model_places_aims_and_moves_a_chase_camera():
    client = fake_client(payload([{
        "preset": entry("chase", "inferred", "chase"),
        "offset_forward_m": entry(-17.0, "inferred", "close behind"),
        "offset_up_m": entry(-3.0, "inferred", "slightly below"),
        "aim_mode": entry("bearing", "inferred", "looking east"),
        "aim_bearing_deg": entry(90.0, "inferred", "looking east"),
        "moves": entry(["zoom_in"], "inferred", "zooming in"),
    }]))
    spec = compile_prompt_llm("a Cessna, close behind and slightly below, "
                              "looking east, zooming in",
                              client=client).spec
    camera = spec.cameras[0]
    assert float(camera.offset_forward_m.value) == -17.0
    assert str(camera.offset_forward_m.source) == "inferred"
    assert float(camera.offset_up_m.value) == -3.0
    assert str(camera.aim_mode.value) == "bearing"
    assert describe_moves(camera.moves) == ["zoom_in"]


def test_an_offset_on_a_fixed_view_is_noted_not_applied():
    client = fake_client(payload([{
        "preset": entry("tower", "inferred", "from the tower"),
        "offset_forward_m": entry(-50.0, "model", "close"),
    }]))
    spec = compile_prompt_llm("from the tower, close", client=client).spec
    assert str(spec.cameras[0].offset_forward_m.source) == "default"
    assert any("offset_forward_m" in n and "not applied" in n
               for n in spec.notes)


def test_move_words_the_model_dropped_still_move_the_camera():
    client = fake_client(payload([]))
    spec = compile_prompt_llm("a Cessna, the camera orbits it",
                              client=client).spec
    assert len(spec.cameras) == 1
    assert describe_moves(spec.cameras[0].moves) == ["orbit"]


def test_an_unknown_move_is_refused_by_name():
    client = fake_client(payload([{"moves": entry(["dutch_tilt"])}]))
    with pytest.raises(LLMCompileError, match="moves"):
        compile_prompt_llm("dutch tilt", client=client)
