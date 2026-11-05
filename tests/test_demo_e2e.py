"""The automated end-to-end demo run (Phase 3, box F1).

Five steps, driven with no other input: pick the aircraft (the page has
no aircraft picker, so the main aircraft the page offers -- E4's default
run, the c172p -- is accepted), pick Desert (`#environmentPreset`), press
Capture (`#run`, which posts `POST /run {}`), wait for `done`
(`GET /runs/{id}`), download `dataset.zip` (`?format=coco&cameras=camera0`,
the page's default dataset query). The two tests share `DEMO_STEPS`:

* `test_demo_page_end_to_end` (`ue_host`) drives the real page in the
  headless Chromium of tests/test_route_page.py against a server this
  file starts, on the Windows engine machine, and then checks that the
  zip's COCO file has a `payload` box wherever verify says there are
  payload pixels. It skips by name everywhere else (tests/conftest.py).
* `test_demo_run_headless_to_the_render_step` posts the same bodies
  through the TestClient with no engine, so CI covers the path up to the
  render step: the run reaches `done` with the Python capture (manifest,
  verify, labels-only zip) and no pixels.

The payload-box clause is a pure function with its own unit test, so a
Windows failure names the frame rather than only failing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pytest
from fastapi.testclient import TestClient

import webapp.runs as runs_module
import webapp.server as server_module
from core.util import settings
from tests.test_route_page import CHROMIUM, NODE, _browser_ready, _free_port, _npm_root
from webapp.runs import DEFAULT_RUN_AIRCRAFT, DEFAULT_RUN_ENVIRONMENT, ENVIRONMENT_PRESETS, RunManager
from webapp.server import app

REPO = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve()

#: The five Do steps, in order; both tests walk them and record each.
DEMO_STEPS = ("aircraft", "desert", "capture", "done", "download")
#: D4's picker value for "Pick Desert" (a key of ENVIRONMENT_PRESETS).
DESERT = "desert"
#: "Pick the aircraft": the main aircraft the page offers (E4's default
#: run). The test imports E4's constant and fails if the names drift.
DEMO_AIRCRAFT = "c172p"
#: What the Capture button posts with nothing compiled (E4 agreement).
CAPTURE_BODY: Dict = {}
#: The page's default dataset query (`datasetQuery`: format coco, camera0).
DATASET_QUERY = "format=coco&cameras=camera0"
#: Terminal run statuses (scripts/run_test_scenarios.py DONE).
DONE = ("done", "failed")
#: C3's component class word in the COCO categories (core/dataset/export.py).
PAYLOAD_CLASS = "payload"
#: The two verify checks whose detail can name a frame with payload pixels.
PAYLOAD_CHECKS = ("component_coverage", "component_boxes")

FLAT_SCENE = {"key": "flat", "kind": "flat", "terrain": None,
              "imagery": None, "label": "flat (test)"}

_DETAIL_FRAME = re.compile(r"(camera\d+)/(\S*?(\d+)\S*?\.png)")
_COCO_FRAME = re.compile(r"_(camera\d+)_(\d+)\.png$")


# -- helpers shared by the two tests ---------------------------------------

def wait_done(get, run_id: str, timeout_s: float = 600.0, every_s: float = 1.0) -> dict:
    """Poll `GET /runs/{id}` (``get(path) -> dict``) until a terminal status."""
    deadline = time.monotonic() + timeout_s
    state = get(f"/runs/{run_id}")
    while state.get("status") not in DONE and time.monotonic() < deadline:
        time.sleep(every_s)
        state = get(f"/runs/{run_id}")
    return state


def _coco_files(zf: zipfile.ZipFile) -> List[str]:
    return [n for n in zf.namelist()
            if n.endswith(".json") and "/annotations/" in f"/{n}" and "instances_" in n]


def coco_payload_frames(zip_path: Path) -> Set[str]:
    """The COCO image file names (every split) that carry a `payload`
    annotation. Raises if the zip holds no COCO annotation file."""
    frames: Set[str] = set()
    with zipfile.ZipFile(zip_path) as zf:
        files = _coco_files(zf)
        if not files:
            raise AssertionError(f"no COCO annotations file in {zip_path.name}: {zf.namelist()[:8]}")
        for name in files:
            coco = json.loads(zf.read(name).decode("utf-8"))
            payload_ids = {c["id"] for c in coco.get("categories", [])
                           if c.get("name") == PAYLOAD_CLASS}
            images = {img["id"]: img["file_name"] for img in coco.get("images", [])}
            for ann in coco.get("annotations", []):
                if ann.get("category_id") in payload_ids and ann.get("image_id") in images:
                    frames.add(images[ann["image_id"]])
    return frames


def _frame_ids(file_names: Iterable[str]) -> Set[Tuple[str, int]]:
    out = set()
    for name in file_names:
        m = _COCO_FRAME.search(name)
        if m:
            out.add((m.group(1), int(m.group(2))))
    return out


def payload_boxes_cover_pixels(zip_path: Path, verification: dict) -> List[str]:
    """The frames verify's `component_coverage` / `component_boxes` detail
    names (``camera/frame.png``) that have no `payload` annotation in the
    zip's COCO file; empty = PASS. Frames are matched by camera and frame
    index (the export keys a sample ``<run>_<camera>_<index>``)."""
    covered = _frame_ids(coco_payload_frames(zip_path))
    uncovered: List[str] = []
    for check in verification.get("checks", []):
        if check.get("name") not in PAYLOAD_CHECKS:
            continue
        for camera, frame, index in _DETAIL_FRAME.findall(str(check.get("detail", ""))):
            if (camera, int(index)) not in covered:
                uncovered.append(f"{camera}/{frame}")
    return uncovered


def failed_checks(verification: dict) -> List[str]:
    return [c["name"] for c in verification.get("checks", []) if c.get("status") == "FAIL"]


# -- the pure clause -------------------------------------------------------

def _synthetic_coco_zip(path: Path, payload_frames: List[str], all_frames: List[str]) -> Path:
    images = [{"id": i + 1, "file_name": f"images/train/{f}"} for i, f in enumerate(all_frames)]
    categories = [{"id": 1, "name": "A4", "supercategory": "aircraft"},
                  {"id": 2, "name": PAYLOAD_CLASS, "supercategory": PAYLOAD_CLASS,
                   "parent_category": "aircraft"}]
    annotations = []
    for img in images:
        annotations.append({"id": len(annotations) + 1, "image_id": img["id"],
                            "category_id": 1, "bbox": [10, 10, 100, 40]})
        if Path(img["file_name"]).name in payload_frames:
            annotations.append({"id": len(annotations) + 1, "image_id": img["id"],
                                "category_id": 2, "bbox": [30, 30, 12, 6]})
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("dataset/annotations/instances_train.json", json.dumps(
            {"images": images, "categories": categories, "annotations": annotations}))
    return path


def test_payload_boxes_cover_pixels_names_the_uncovered_frame(tmp_path):
    frames = ["run_camera0_0001.png", "run_camera0_0002.png"]
    zip_path = _synthetic_coco_zip(tmp_path / "dataset.zip", ["run_camera0_0001.png"], frames)
    verification = {"checks": [
        {"name": "component_coverage", "status": "FAIL",
         "detail": "camera0/frame_0002.png: the ID image holds 40 pixels of "
                   "payload:STA2:0 (int_id 64) but the frame's labels.objects[] "
                   "has no record for it"},
        {"name": "component_boxes", "status": "PASS",
         "detail": "3 component records: tight box inside its own hull"},
        {"name": "label_offset", "status": "FAIL", "detail": "camera0/frame_0002.png: unrelated"},
    ]}
    assert payload_boxes_cover_pixels(zip_path, verification) == ["camera0/frame_0002.png"]
    covered = {"checks": [{"name": "component_boxes", "status": "FAIL",
                           "detail": "camera0/frame_0001.png payload:STA2:0: bbox_2d_tight ..."}]}
    assert payload_boxes_cover_pixels(zip_path, covered) == []
    assert payload_boxes_cover_pixels(zip_path, {"checks": []}) == []
    assert coco_payload_frames(zip_path) == {"images/train/run_camera0_0001.png"}


def test_the_demo_touches_no_tiles_or_weather_switch():
    """CLAUDE.md: Google tiles and the storm weather are ON by default;
    the demo posts nothing that would switch either, and this file reads
    no such switch."""
    text = HERE.read_text(encoding="utf-8")
    assert "FLIGHTSIM_GOOGLE_" + "TILES" not in text
    assert "WEATHER_" + "BACKEND" not in text
    assert CAPTURE_BODY == {}
    assert DEMO_AIRCRAFT == DEFAULT_RUN_AIRCRAFT
    assert DESERT == DEFAULT_RUN_ENVIRONMENT and DESERT in ENVIRONMENT_PRESETS
    assert list(DEMO_STEPS) == ["aircraft", "desert", "capture", "done", "download"]


# -- CI: the same steps headless, up to the render step --------------------

@pytest.fixture
def client():
    return TestClient(app)


def test_demo_run_headless_to_the_render_step(client, monkeypatch, tmp_path):
    """No engine on this host: the Capture body `{}` is accepted, the run
    reaches `done` through the Python capture, verify has no FAIL, and
    the page's dataset download is a 200 zip holding the COCO file
    (labels only: there are no pixels before the render step)."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(server_module, "ue_available", lambda: False, raising=False)
    monkeypatch.setattr(runs_module, "ue_available", lambda: False, raising=False)
    monkeypatch.setattr(runs_module, "ensure_aircraft_model", lambda spec, report: None)
    # The grand_canyon bake is not on every clone (tests/test_run_default.py).
    monkeypatch.setattr(runs_module, "needs_dynamic_bake", lambda spec: None)
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "pick_scene", lambda spec: FLAT_SCENE)
    monkeypatch.setattr(server_module, "manager", RunManager(out_root=tmp_path))
    walked = []

    walked.append("aircraft")                      # accepted: the page's main aircraft
    assert DEMO_AIRCRAFT == DEFAULT_RUN_AIRCRAFT
    walked.append("desert")                        # the default run's environment
    assert DEFAULT_RUN_ENVIRONMENT == DESERT

    reply = client.post("/run", json=CAPTURE_BODY)   # Capture
    assert reply.status_code == 200, reply.text
    run_id = reply.json()["run_id"]
    walked.append("capture")

    state = wait_done(lambda p: client.get(p).json(), run_id)
    assert state["status"] == "done", state.get("detail")
    assert state["capture"] is not None and state["capture"]["headless"] is True
    walked.append("done")
    # a headless run writes no card.json (the card is the engine's input);
    # the manifest names the same primary aircraft
    manifest = (tmp_path / run_id / "capture_manifest.json").read_text(encoding="utf-8")
    assert f"aircraft:{DEMO_AIRCRAFT}:0" in manifest
    verification = client.get(f"/runs/{run_id}/verify.json")
    assert verification.status_code == 200, verification.text
    assert failed_checks(verification.json()) == [], verification.json()

    download = client.get(f"/runs/{run_id}/dataset.zip?{DATASET_QUERY}")
    assert download.status_code == 200, download.text[:400]
    assert download.headers["content-type"].startswith("application/zip")
    zip_path = tmp_path / "dataset.zip"
    zip_path.write_bytes(download.content)
    with zipfile.ZipFile(zip_path) as zf:
        assert _coco_files(zf), zf.namelist()[:12]
    coco_payload_frames(zip_path)                  # runs; no pixel clause before the render
    walked.append("download")
    assert tuple(walked) == DEMO_STEPS


# -- Windows: the real page, the real engine ------------------------------

PAGE_DRIVER = r"""
const { chromium } = require("playwright");
const [base, executablePath, desert, timeoutS] = process.argv.slice(2);
(async () => {
  const errors = [];
  const browser = await chromium.launch({headless: true, executablePath, args: ["--no-sandbox"]});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  page.on("console", msg => { if (msg.type() === "error")
    errors.push({text: msg.text(), url: (msg.location() || {}).url || ""}); });
  page.on("pageerror", err => errors.push({text: "pageerror: " + err.message, url: ""}));
  await page.goto(base + "/", {waitUntil: "load"});
  await page.waitForSelector("#environmentPreset", {state: "attached", timeout: 30000});
  await page.selectOption("#environmentPreset", desert);                     // Pick Desert
  const picked = await page.$eval("#environmentPreset", e => e.value);
  await page.waitForSelector("#run:not([disabled])", {timeout: 30000});
  const button = (await page.$eval("#run", e => e.textContent)).trim();
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/run") && r.request().method() === "POST", {timeout: 60000}),
    page.click("#run"),                                                        // Capture
  ]);
  const body = response.request().postData();
  const started = await response.json();
  const t0 = Date.now();
  let state = null;
  while (Date.now() - t0 < Number(timeoutS) * 1000) {                        // wait for done
    state = await page.evaluate(async id => (await fetch("/runs/" + id)).json(), started.run_id);
    if (state.status === "done" || state.status === "failed") break;
    await page.waitForTimeout(2000);
  }
  const wall_s = (Date.now() - t0) / 1000;
  await browser.close();
  console.log(JSON.stringify({picked, button, body, started, state, wall_s, errors}));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""

#: A long render: the c172p clip through the editor, then capture and verify.
RENDER_TIMEOUT_S = float(os.environ.get("FLIGHTSIM_DEMO_TIMEOUT_S", "1800"))


@pytest.fixture
def demo_server(monkeypatch, tmp_path):
    """The real app on a free port in this process. Settings are read from
    a copy of the user's settings.json on tmp_path (the tiles key stays,
    the user's file is never written). Yields the base URL."""
    import uvicorn

    copy = tmp_path / "settings.json"
    source = Path(settings.SETTINGS_PATH)
    if source.is_file():
        shutil.copyfile(source, copy)
    monkeypatch.setattr(settings, "SETTINGS_PATH", copy)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)


def _http_get(url: str):
    import urllib.request

    with urllib.request.urlopen(url, timeout=120) as reply:  # noqa: S310 (loopback)
        return reply.status, reply.headers.get("content-type", ""), reply.read()


def test_the_page_driver_parses(tmp_path):
    if not NODE:
        pytest.skip("node is not installed")
    driver = tmp_path / "demo.js"
    driver.write_text(PAGE_DRIVER, encoding="utf-8")
    subprocess.run([NODE, "--check", str(driver)], check=True, timeout=60)


@pytest.mark.ue_host
def test_demo_page_end_to_end(demo_server, tmp_path, record_property):
    """Windows, serial with any other render: the five steps on the real
    page, then the zip has payload boxes wherever there are payload pixels."""
    reason = _browser_ready()
    if reason:
        pytest.skip(reason)
    driver = tmp_path / "demo.js"
    driver.write_text(PAGE_DRIVER, encoding="utf-8")
    env = {**os.environ, "NODE_PATH": _npm_root()}
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(CHROMIUM.parent))
    run = subprocess.run([NODE, str(driver), demo_server, str(CHROMIUM), DESERT, str(RENDER_TIMEOUT_S)],
                         capture_output=True, text=True, timeout=RENDER_TIMEOUT_S + 120, env=env)
    assert run.returncode == 0, run.stderr[-4000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])
    walked = []

    walked.append("aircraft")                      # the page offers one aircraft: E4's A-4
    assert result["picked"] == DESERT
    walked.append("desert")
    assert result["button"] == "Capture", result["button"]
    assert json.loads(result["body"]) == CAPTURE_BODY, result["body"]
    run_id = result["started"].get("run_id")
    assert run_id, result["started"]
    walked.append("capture")
    state = result["state"]
    assert state and state["status"] == "done", (state or {}).get("detail")
    walked.append("done")
    assert result["errors"] == [], result["errors"]
    record_property("run_id", run_id)
    record_property("wall_s", result["wall_s"])

    status, _, raw = _http_get(f"{demo_server}/runs/{run_id}/card.json")
    assert status == 200 and json.loads(raw)["aircraft"] == DEMO_AIRCRAFT
    status, _, raw = _http_get(f"{demo_server}/runs/{run_id}/verify.json")
    assert status == 200, raw[:400]
    verification = json.loads(raw)
    assert failed_checks(verification) == [], verification
    status, ctype, raw = _http_get(f"{demo_server}/runs/{run_id}/dataset.zip?{DATASET_QUERY}")
    assert status == 200 and ctype.startswith("application/zip"), (status, ctype)
    zip_path = tmp_path / "dataset.zip"
    zip_path.write_bytes(raw)
    walked.append("download")
    assert tuple(walked) == DEMO_STEPS
    record_property("payload_frames", len(coco_payload_frames(zip_path)))
    assert payload_boxes_cover_pixels(zip_path, verification) == []
    print(f"F1 demo run {run_id}: done in {result['wall_s']:.0f} s, "
          f"verify passed={verification.get('passed')} failed={verification.get('failed')} "
          f"not_run={verification.get('not_run')}")
