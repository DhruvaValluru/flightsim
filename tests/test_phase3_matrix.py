"""Phase 3 D6: the same pipeline, unchanged, across {A4, J11} x {desert, forest}.

A matrix is a claim about coverage, and the three ways
tests/test_parity_matrix.py names for a matrix to lie apply here too: the
cells could be duplicates, a cell could change more than the two chosen
variables, and a failed or not-run verification could be counted as a pass.
Each has a guard in ``scripts/run_test_scenarios.py --matrix`` and each
guard has a test here. No server and no render: the runner's ``call`` is
replaced by a fake that answers like the web app.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_test_scenarios.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_test_scenarios_d6", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rts = _load()
MATRIX = rts.matrix_cells()


# -- the cells -------------------------------------------------------------


def test_matrix_has_four_unique_cells():
    assert len(MATRIX) == 4
    names = [c["name"] for c in MATRIX]
    assert len(set(names)) == 4
    pairs = {(c["aircraft"], c["environment"]) for c in MATRIX}
    assert len(pairs) == 4


def test_cells_are_the_product_of_two_aircraft_and_two_environments():
    assert rts.MATRIX_AIRCRAFT == ("A4", "J11")
    assert rts.MATRIX_ENVIRONMENTS == ("desert", "forest")
    expected = {(a, e) for a in rts.MATRIX_AIRCRAFT for e in rts.MATRIX_ENVIRONMENTS}
    assert {(c["aircraft"], c["environment"]) for c in MATRIX} == expected
    for cell in MATRIX:
        assert set(cell) == {"name", "aircraft", "environment"}
        # the aircraft is a config stem (assets/aircraft_config/<name>.json)
        assert cell["aircraft"].isalnum() and cell["aircraft"].isupper()
    assert (REPO / "assets" / "aircraft_config" / "A4.json").is_file()


# -- a cell changes only the aircraft (spec) and the environment (/compile) -


def _spec_dict():
    return {
        "aircraft": {"aircraft": {"value": "c172p", "source": "default", "from": "compiler"}},
        "altitude": {"value": 1500.0, "source": "default"},
        "airspeed": {"value": 110.0, "source": "default"},
        "lighting": {"preset": {"value": "noon", "source": "default"}},
        "weather": {"value": "storm", "source": "default"},
    }


def test_apply_cell_changes_only_the_aircraft():
    before = _spec_dict()
    for cell in MATRIX:
        spec = copy.deepcopy(before)
        rts.apply_cell(spec, cell)
        assert spec["aircraft"]["aircraft"]["value"] == cell["aircraft"]
        assert spec["aircraft"]["aircraft"]["source"] == "user"
        rest_before = {k: v for k, v in before.items() if k != "aircraft"}
        rest_after = {k: v for k, v in spec.items() if k != "aircraft"}
        assert rest_after == rest_before
    # a spec without an aircraft entry gets one, in the same shape
    bare = {"lighting": {}}
    rts.apply_cell(bare, MATRIX[2])
    assert bare["aircraft"]["aircraft"]["value"] == "J11" and bare["aircraft"]["aircraft"]["source"] == "user"


def test_cell_compile_body_adds_only_environment():
    for cell in MATRIX:
        still = rts.cell_compile_body(cell, "regex", True)
        assert still == {"prompt": rts.MATRIX_PROMPT, "compiler": "regex",
                         "environment": cell["environment"], "still": True}
        clip = rts.cell_compile_body(cell, "llm", False, 6.0)
        assert clip == {"prompt": rts.MATRIX_PROMPT, "compiler": "llm",
                        "environment": cell["environment"], "clip_seconds": 6.0}
    # the one prompt is neutral: it names no aircraft, place, speed or height
    prompt = rts.MATRIX_PROMPT.lower()
    for word in ("a4", "a-4", "j11", "j-11", "c172", "747", "a320", "desert", "forest",
                 "canyon", "yosemite", "knots", "kt", " m ", "ft", "altitude"):
        assert word not in f" {prompt} ", word
    assert len({rts.cell_compile_body(c, "regex", True)["prompt"] for c in MATRIX}) == 1


def test_matrix_scenes_match_scene_setting_bakes():
    from webapp.runs import ENVIRONMENT_PRESETS, SCENE_SETTING_BAKES
    assert rts.MATRIX_SCENES == {"desert": "grand_canyon", "forest": "yosemite"}
    for environment, scene in rts.MATRIX_SCENES.items():
        assert SCENE_SETTING_BAKES[environment] == scene
        assert ENVIRONMENT_PRESETS[environment]["scene"] == scene
    assert set(rts.MATRIX_SCENES) == set(rts.MATRIX_ENVIRONMENTS)


# -- the card diff ---------------------------------------------------------


def _card(aircraft="A4", lat=36.1, scene_crs="EPSG:32612"):
    return {
        "aircraft": aircraft, "spec_digest": f"{aircraft}-{lat}",
        "latitude_deg": lat, "longitude_deg": -112.1, "terrain_elevation_m": 2100.0,
        "duration_s": 6.0, "rate_hz": 30.0, "airspeed_kt": 250.0 if aircraft == "A4" else 300.0,
        "airspeed_kind": "indicated",
        "weather": {"kind": "storm", "rain_gain": 4.0},
        "look": {"rain_style": "cinematic"},
        "scene_crs": scene_crs,
        "objects": [{"id": f"aircraft:{aircraft}:0", "int_id": 1}],
        "google_tiles": {"requested": True, "origin": [lat, -112.1]},
        "cameras": [{"name": "chase", "fov_deg": 60.0}],
    }


def test_card_diff_allows_aircraft_and_scene_keys():
    cards = [_card("A4", 36.1), _card("A4", 37.7, "EPSG:32611"),
             _card("J11", 36.1), _card("J11", 37.7, "EPSG:32611")]
    diff = rts.card_diff(cards[0], cards[3])
    assert "aircraft" in diff and "latitude_deg" in diff and "google_tiles.origin" in diff
    assert "duration_s" not in diff and "weather.kind" not in diff
    assert rts.check_cards(cards) == []
    assert rts.check_cards(cards[:1]) == []


@pytest.mark.parametrize("key,value", [
    ("duration_s", 8.0), ("weather", {"kind": "clear", "rain_gain": 4.0}),
    ("look", {"rain_style": "plain"}), ("cameras", [{"name": "tower", "fov_deg": 60.0}]),
    ("rate_hz", 60.0), ("airspeed_kind", "true"),
])
def test_card_diff_refuses_other_key(key, value):
    first = _card("A4", 36.1)
    other = _card("J11", 37.7, "EPSG:32611")
    other[key] = value
    bad = rts.check_cards([first, other])
    assert bad and all(k == key or k.startswith(key + ".") for k in bad), bad
    # a key missing on one side is a difference too
    missing = _card("J11", 36.1)
    del missing["cameras"]
    assert rts.check_cards([first, missing]) == ["cameras"]


# -- verify: PASS means PASS, NOT RUN is not a pass -------------------------


def _report(coverage="PASS", ok=True, failed=0):
    checks = [{"name": "pose_matches_spec", "status": "PASS", "detail": ""}]
    if coverage is not None:
        checks.append({"name": "component_coverage", "status": coverage,
                       "detail": "6 of 6 components boxed" if coverage == "PASS"
                       else "no engine bundle"})
    return {"ok": ok, "passed": sum(c["status"] == "PASS" for c in checks),
            "failed": failed, "not_run": sum(c["status"] == "NOT RUN" for c in checks),
            "checks": checks}


def _record(scene="grand_canyon"):
    return {"run_id": "abc", "status": "done", "scene": {"key": scene, "title": "Grand Canyon"}}


def test_verify_cell_requires_component_coverage_pass():
    cell = MATRIX[0]                       # A4/desert -> grand_canyon
    ok, words = rts.verify_cell(_report(), _record(), cell)
    assert ok, words
    assert "verify PASS component_coverage PASS" in words
    ok, words = rts.verify_cell(_report(coverage="FAIL"), _record(), cell)
    assert not ok and "component_coverage FAIL" in words
    ok, words = rts.verify_cell(_report(coverage=None), _record(), cell)
    assert not ok and "component_coverage" in words
    ok, words = rts.verify_cell(_report(ok=False, failed=1), _record(), cell)
    assert not ok and "failed=1" in words
    # the scene must be the environment's bake
    ok, words = rts.verify_cell(_report(), _record("yosemite"), cell)
    assert not ok and "scene" in words
    ok, _ = rts.verify_cell(_report(), _record("yosemite"), MATRIX[1])
    assert ok


def test_verify_cell_not_run_is_not_a_pass():
    for status in ("NOT RUN", "NOT_RUN"):
        ok, words = rts.verify_cell(_report(coverage=status), _record(), MATRIX[0])
        assert not ok
        assert "NOT RUN" in words
    # a server error is a failure in words, not an exception
    ok, words = rts.verify_cell({"ok": False, "error": "verify.json: HTTP 404"},
                                _record(), MATRIX[0])
    assert not ok and "404" in words


# -- the runner, against a fake web app -------------------------------------


class FakeApp:
    """Answers /compile, /run, /runs/{id}, verify.json and card.json the way
    webapp.server does, recording every request body; no render."""

    def __init__(self, coverage="PASS"):
        self.coverage = coverage
        self.requests = []
        self.runs = {}

    def call(self, server, method, path, body=None, timeout=3600.0):
        self.requests.append((method, path, copy.deepcopy(body)))
        if path == "/compile":
            spec = _spec_dict()
            if body.get("environment") == "forest":
                spec["latitude"] = {"value": 37.7, "source": "user"}
            else:
                spec["latitude"] = {"value": 36.1, "source": "user"}
            return 200, {"compiler": body["compiler"], "validation": {"ok": True},
                         "spec": {"dict": spec, "notes": []}}
        if path == "/run":
            spec = body["spec"]
            run_id = f"run{len(self.runs) + 1}"
            scene = "yosemite" if spec["latitude"]["value"] == 37.7 else "grand_canyon"
            self.runs[run_id] = {"aircraft": spec["aircraft"]["aircraft"]["value"], "scene": scene,
                                 "spec": spec}
            return 200, {"run_id": run_id}
        run_id = path.split("/")[2]
        run = self.runs[run_id]
        if path.endswith("/verify.json"):
            return 200, _report(coverage=self.coverage)
        if path.endswith("/card.json"):
            lat = 37.7 if run["scene"] == "yosemite" else 36.1
            return 200, _card(run["aircraft"], lat,
                              "EPSG:32611" if run["scene"] == "yosemite" else "EPSG:32612")
        return 200, {"run_id": run_id, "status": "done", "detail": "clip ready",
                     "scene": {"key": run["scene"]}, "events": [], "conditions": {}}


class Args:
    server = "http://fake"
    compiler = "regex"
    still = True
    clip = 3.0
    poll = 0.0


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(rts, "MATRIX_SUMMARY", tmp_path / "phase3_matrix.json")
    monkeypatch.setattr(rts, "GALLERY", tmp_path / "gallery")
    monkeypatch.setattr(rts, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(rts.time, "sleep", lambda s: None)
    return tmp_path


def test_run_matrix_with_fake_server_passes_and_writes_summary(sandbox, monkeypatch, capsys):
    app = FakeApp()
    monkeypatch.setattr(rts, "call", app.call)
    assert rts.run_matrix(Args()) == 0
    summary = json.loads((sandbox / "phase3_matrix.json").read_text(encoding="utf-8"))
    assert summary["ok"] is True and len(summary["cells"]) == 4
    assert [c["outcome"] for c in summary["cells"]] == ["done"] * 4
    assert all(c["verify"]["passed"] for c in summary["cells"])
    assert summary["card_outside_allow"] == []
    assert "aircraft" in summary["card_diff"]
    # every /compile carried the environment and the one prompt; every /run
    # carried only the spec and its provenance, with the cell's aircraft
    compiles = [b for m, p, b in app.requests if p == "/compile"]
    runs = [b for m, p, b in app.requests if p == "/run"]
    assert [b["environment"] for b in compiles] == ["desert", "forest", "desert", "forest"]
    assert {b["prompt"] for b in compiles} == {rts.MATRIX_PROMPT}
    assert all(set(b) == {"spec", "provenance"} for b in runs)
    assert [b["spec"]["aircraft"]["aircraft"]["value"] for b in runs] == ["A4", "A4", "J11", "J11"]
    out = capsys.readouterr().out
    # once per cell as it finishes (step 7's line) and once in the summary
    assert out.count("verify PASS component_coverage PASS") >= 4
    assert "matrix PASS" in out


def test_run_matrix_fails_when_coverage_is_not_run(sandbox, monkeypatch, capsys):
    app = FakeApp(coverage="NOT RUN")
    monkeypatch.setattr(rts, "call", app.call)
    assert rts.run_matrix(Args()) == 1
    summary = json.loads((sandbox / "phase3_matrix.json").read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert all(not c["verify"]["passed"] for c in summary["cells"])
    assert "matrix FAIL" in capsys.readouterr().out


def test_matrix_flag_lists_four_cells():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--matrix", "--list"],
                          capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    lines = [l for l in proc.stdout.splitlines() if l[:3].strip().rstrip(".").isdigit()]
    assert len(lines) == 4
    for cell in MATRIX:
        assert cell["name"] in proc.stdout
    assert "grand_canyon" in proc.stdout and "yosemite" in proc.stdout
    # plain --list is unchanged: the scenarios, not the cells
    plain = subprocess.run([sys.executable, str(SCRIPT), "--list"],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    assert plain.returncode == 0
    assert "A4/desert" not in plain.stdout and "hurricane" in plain.stdout
