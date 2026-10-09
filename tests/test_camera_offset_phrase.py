"""The exact camera position the 3D sample frame writes into the prompt:
"camera <a> m behind|ahead, <b> m left|right, <c> m above|below the
aircraft" (webapp/static/lens_picker.js positionPhrase).

Both compilers read it as a user-stated chase offset in the aircraft's
heading frame -- the same forward / right / up convention as
CHASE_OFFSETS -- and its metres are never an altitude. A view that
cannot follow at an offset says so by name.
"""

import re
from pathlib import Path

from core.nl.compiler import (
    CAMERA_OFFSET_PHRASE, camera_questions, compile_prompt,
    stated_camera_offset,
)

STATIC = Path(__file__).resolve().parents[1] / "webapp" / "static"
SCRIPT = (STATIC / "lens_picker.js").read_text(encoding="utf-8")


def test_the_phrase_reads_as_signed_offsets():
    assert stated_camera_offset(
        "camera 110 m behind, 20 m left, 12 m above the aircraft") == \
        (-110.0, -20.0, 12.0, "camera 110 m behind, 20 m left, 12 m above")
    assert stated_camera_offset(
        "camera 50.5 m ahead, 0 m right and 5 m below the aircraft")[:3] == \
        (50.5, 0.0, -5.0)
    assert stated_camera_offset("camera 0 m behind, 0 m left, 0 m below") \
        [:3] == (0.0, 0.0, 0.0)
    assert stated_camera_offset("a chase view of the 747") is None


def test_the_regex_compiler_places_a_chase_camera_the_user_stated():
    spec = compile_prompt("fly the a320 at 3000 m, camera 80 m behind, "
                          "30 m right, 15 m above the aircraft, with a 50 mm lens")
    assert len(spec.cameras) == 1
    camera = spec.cameras[0]
    assert str(camera.preset.value) == "chase"
    assert (float(camera.offset_forward_m.value),
            float(camera.offset_right_m.value),
            float(camera.offset_up_m.value)) == (-80.0, 30.0, 15.0)
    for name in ("offset_forward_m", "offset_right_m", "offset_up_m"):
        assert str(getattr(camera, name).source) == "user", name
    assert float(camera.focal_length_mm.value) == 50.0
    # The whole clip from there, like any view named without a count.
    assert str(camera.trigger.value) == "continuous"


def test_the_camera_s_metres_are_not_the_altitude():
    """"camera 110 m behind" used to read as a 110 m flight altitude."""
    spec = compile_prompt("fly the a320, camera 110 m behind, 0 m right, "
                          "12 m above the aircraft")
    assert str(spec.altitude.source) == "default"
    spec = compile_prompt("fly the a320 at 3000 m over the alps, camera "
                          "900 m ahead, 300 m left, 450 m below the aircraft")
    assert float(spec.altitude.value) == 3000.0
    assert str(spec.altitude.source) == "user"


def test_the_phrase_applies_to_the_wingman_and_not_the_tower():
    spec = compile_prompt("wingman view of the 747, camera 50 m ahead, "
                          "0 m right, 5 m below the aircraft")
    camera = spec.cameras[0]
    assert str(camera.preset.value) == "wingman"
    assert float(camera.offset_forward_m.value) == 50.0
    assert float(camera.offset_up_m.value) == -5.0

    spec = compile_prompt("tower view of the c172p, camera 10 m behind, "
                          "0 m right, 2 m above the aircraft")
    camera = spec.cameras[0]
    assert str(camera.preset.value) == "tower"
    assert str(camera.offset_forward_m.source) == "default"
    assert any("not applied to the tower view" in n for n in spec.notes)


def test_a_stated_position_does_not_ask_which_view():
    assert camera_questions("fly the a320, camera 80 m behind, 30 m right, "
                            "15 m above the aircraft") == []


def test_the_llm_compiler_takes_the_stated_position_over_the_model_s():
    from core.nl.llm_compiler import compile_prompt_llm
    from tests.test_llm_compiler import entry, fake_client

    prompt = ("fly the a320 at 3000 m, camera 80 m behind, 30 m right, "
              "15 m above the aircraft")
    client = fake_client({
        "fields": {"altitude": entry(3000.0, "user", "3000 m")},
        "cameras": [{"preset": entry("chase", "inferred", "camera"),
                     "offset_forward_m": entry(-300.0, "model", "behind"),
                     "offset_up_m": entry(40.0, "model", "above")}],
        "notes": [], "questions": [],
    })
    spec = compile_prompt_llm(prompt, client=client).spec
    camera = spec.cameras[0]
    assert (float(camera.offset_forward_m.value),
            float(camera.offset_right_m.value),
            float(camera.offset_up_m.value)) == (-80.0, 30.0, 15.0)
    assert str(camera.offset_forward_m.source) == "user"

    # No camera from the model at all: the phrase still earns one.
    client = fake_client({"fields": {}, "cameras": [], "notes": [],
                          "questions": []})
    spec = compile_prompt_llm(prompt, client=client).spec
    assert len(spec.cameras) == 1
    assert float(spec.cameras[0].offset_right_m.value) == 30.0


def test_the_page_writes_the_phrase_the_compiler_reads():
    """The JS writes "camera <f> m behind, <r> m right, <u> m above the
    aircraft" and both compilers read it -- pinned by running the
    Python regex over the JS's own output shape, and by the JS's
    replace-regex matching what Python accepts."""
    assert "function positionPhrase" in SCRIPT
    assert "function applyCameraToPrompt" in SCRIPT
    sample = "camera 80.5 m behind, 0 m right, 15 m above the aircraft"
    assert CAMERA_OFFSET_PHRASE.search(sample)
    # The pattern's string pieces, up to the flags argument.
    m = re.search(r'const POSITION_RE = new RegExp\((.*?), "i"\);', SCRIPT, re.S)
    assert m, "POSITION_RE missing from lens_picker.js"
    js_source = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
    js_pattern = js_source.encode().decode("unicode_escape")
    assert re.search(js_pattern, sample, re.IGNORECASE)
    assert re.search(js_pattern, "camera 1 m ahead, 2 m left and 3 m below",
                     re.IGNORECASE)


def test_both_pages_load_the_3d_helpers_before_the_picker():
    for page in ("index.html", "generate.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        helpers = html.index('<script src="/camera3d.js"></script>')
        picker = html.index('<script src="/lens_picker.js"></script>')
        assert helpers < picker, page
    assert "window.Flight3D" in (STATIC / "camera3d.js").read_text(encoding="utf-8")
