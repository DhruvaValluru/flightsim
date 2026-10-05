"""render.json's root ``georeference``: the card carries the numbers, the
host copies them, the verifier grades the copy.

The host (C++, not compiled here) is pinned by source: it writes the five
keys check.georeference reads, with the verifier's own geographic CRS and
vertical-convention sentence, and copies the rest from the card's
``georeference`` block. The Python half is measured: a real headless
capture's card, copied the way the host copies it, passes the check
against that capture's manifest, and a copy one metre off fails it.
"""

import json
import re
from pathlib import Path

from core.capture.verify import (
    FAIL, FAIL_GEOREFERENCE, GEOREFERENCE_GEOGRAPHIC_CRS, GEOREFERENCE_KEYS,
    GEOREFERENCE_VERTICAL_CONVENTION, PASS, verify_georeference,
)
from flightsim.capture import main as capture_main

REPO = Path(__file__).resolve().parents[1]
COMMANDLET = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
              / "Private" / "FlightSimRenderCommandlet.cpp")
EXAMPLE = REPO / "examples" / "cameras_multi.yaml"


def _host_block() -> str:
    source = COMMANDLET.read_text(encoding="utf-8")
    start = source.index('TryGetObjectField(TEXT("georeference"), CardGeoreference)')
    end = source.index('Root->SetObjectField(TEXT("georeference"), Georeference);', start)
    return source[start:end]


def host_copy(card_block: dict) -> dict:
    """What the commandlet writes for a card block (the C++ above, in
    Python): its own geographic CRS and sentence, the rest copied."""
    return {"geographic_crs": GEOREFERENCE_GEOGRAPHIC_CRS,
            "projected_crs": card_block.get("projected_crs", ""),
            "origin": card_block["origin"],
            "vertical_convention": GEOREFERENCE_VERTICAL_CONVENTION,
            "undulation_origin_m": card_block.get("undulation_origin_m")}


def test_the_host_writes_the_verifier_s_keys_and_words():
    block = _host_block()
    written = set(re.findall(r'Set(?:String|Object)?Field\(\s*TEXT\("([a-z_]+)"\)', block))
    assert written == set(GEOREFERENCE_KEYS)
    assert f'TEXT("{GEOREFERENCE_GEOGRAPHIC_CRS}")' in block
    sentence = re.search(r'TEXT\("vertical_convention"\),\s*((?:TEXT\("[^"]*"\)\s*)+)\)',
                         block).group(1)
    assert "".join(re.findall(r'TEXT\("([^"]*)"\)', sentence)) == \
        GEOREFERENCE_VERTICAL_CONVENTION
    # Copied from the card, never derived; a missing undulation is null.
    for key in ("projected_crs", "origin", "undulation_origin_m"):
        assert f'TEXT("{key}")' in block
    assert "FJsonValueNull" in block


def test_a_capture_s_card_copied_by_the_host_passes_the_check(tmp_path):
    out = tmp_path / "run"
    assert capture_main([str(EXAMPLE), "--out", str(out), "--max-previews", "0",
                         "--card"]) == 0
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    block = card["georeference"]
    assert block["projected_crs"] == manifest["frame"]["crs"]
    assert block["undulation_origin_m"] == manifest["datum"].get("undulation_m")

    cameras = [str(c["camera_id"]) for c in manifest["cameras"]]
    for camera in cameras:
        folder = out / "frames" / camera
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "render.json").write_text(
            json.dumps({"georeference": host_copy(block)}), encoding="utf-8")
    check = verify_georeference(manifest, out)
    assert check.status == PASS, check.detail

    moved = host_copy(block)
    moved["origin"] = dict(moved["origin"], x_m=moved["origin"]["x_m"] + 1.0)
    (out / "frames" / cameras[0] / "render.json").write_text(
        json.dumps({"georeference": moved}), encoding="utf-8")
    check = verify_georeference(manifest, out)
    assert check.status == FAIL and check.failure == FAIL_GEOREFERENCE
    assert "origin.x_m" in check.detail


def test_the_web_app_s_card_block_is_its_manifest_s_frame_and_datum(tmp_path):
    """The page's capture path writes its card through webapp.capture
    georeference; the copy of it passes against the manifest the same
    path writes."""
    from core.scenario.spec import ScenarioSpec
    from webapp.capture import georeference, solve, write_manifest

    spec = ScenarioSpec.read(EXAMPLE)
    scene = {"key": "flat", "terrain": None, "imagery": None}
    solved = solve(spec, scene)
    out = tmp_path / "web"
    out.mkdir()
    manifest = json.loads(write_manifest(spec, solved, out, scene).read_text(encoding="utf-8"))
    block = georeference(solved)
    for camera in manifest["cameras"]:
        folder = out / "frames" / str(camera["camera_id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "render.json").write_text(
            json.dumps({"georeference": host_copy(block)}), encoding="utf-8")
    check = verify_georeference(manifest, out)
    assert check.status == PASS, check.detail
