"""The lens picker (webapp/static/lens_picker.js): a sample frame and a
focal-length slider under both prompt boxes, which writes "with a <n> mm
lens" into the prompt.

The page draws the default chase view by projection, so its numbers are
only honest while they match the camera module's: the default lens, the
sensor and the hand-calibrated chase offsets are pinned here. The phrase
it writes must compile to a user-stated focal length, and both pages must
mount it.
"""

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from core.nl.compiler import compile_prompt
from core.scenario.camera import (
    CHASE_OFFSETS, DEFAULT_FOCAL_MM, DEFAULT_SENSOR_H_MM, DEFAULT_SENSOR_W_MM,
)
from webapp.server import app

STATIC = Path(__file__).resolve().parents[1] / "webapp" / "static"
SCRIPT = (STATIC / "lens_picker.js").read_text(encoding="utf-8")


def _js_number(name):
    m = re.search(rf"const {name} = (-?[\d.]+);", SCRIPT)
    assert m, f"{name} missing from lens_picker.js"
    return float(m.group(1))


def test_constants_match_the_camera_module():
    assert _js_number("DEFAULT_FOCAL_MM") == DEFAULT_FOCAL_MM
    assert _js_number("SENSOR_W_MM") == DEFAULT_SENSOR_W_MM
    assert _js_number("SENSOR_H_MM") == DEFAULT_SENSOR_H_MM


def test_chase_offsets_match_the_camera_module():
    m = re.search(r"const CHASE_OFFSETS = (\{.*?\});", SCRIPT, re.S)
    assert m
    table = json.loads(re.sub(r",\s*}", "}", m.group(1)))
    for aircraft, offset in table.items():
        assert tuple(offset) == CHASE_OFFSETS[aircraft], aircraft
    # Every sample airframe has an offset to be drawn from.
    for aircraft in re.findall(r'^  "(\w+)": \{label:', SCRIPT, re.M):
        assert aircraft in table, aircraft


def test_the_phrase_compiles_as_a_user_focal_length():
    spec = compile_prompt("chase view of the a320 at 3000 m, with an 85 mm lens")
    focal = spec.cameras[0].focal_length_mm
    assert focal.value == 85.0
    assert focal.source == "user"


def test_the_stated_lens_wins_over_a_lens_word():
    spec = compile_prompt("telephoto chase view of the 747, with a 200 mm lens")
    assert spec.cameras[0].focal_length_mm.value == 200.0


def test_the_script_is_served_and_both_pages_mount_it():
    client = TestClient(app)
    response = client.get("/lens_picker.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "window.LensPicker" in response.text
    for page in ("/", "/generate.html"):
        html = client.get(page).text
        assert '<script src="/lens_picker.js"></script>' in html, page
        assert 'LensPicker.mount(document.getElementById("lensPicker"), ' \
               'document.getElementById("prompt"))' in html, page


def test_the_picker_is_always_open():
    """The owner asked for the picker expanded no matter what: it mounts
    open and its header no longer folds it away."""
    assert "box.open = true;" in SCRIPT
    assert 'querySelector("summary").addEventListener("click", e => e.preventDefault())' in SCRIPT


def test_the_clip_selector_applies_after_interpret():
    """Picking a clip length after Interpret used to change nothing: the
    selector was read only by /compile. It now writes the table's rows."""
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '$("clipSeconds").addEventListener("change"' in page
    assert 'setRow("duration", seconds);' in page


def test_the_picker_zooms_out_to_6_mm():
    """The owner asked to zoom out further: 6 mm is ~143 deg across."""
    assert "const MIN_MM = 6;" in SCRIPT
    assert "[6, \"widest\"]" in SCRIPT
