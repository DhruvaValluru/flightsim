"""The settings panel (Phase 3 box E3: webapp/static/settings.js, mounted
by index.html over E2's GET/PUT /settings).

What these tests pin: the page mounts the panel with exactly E1's
``ui_keys()`` in E1's order (five rendered fields plus the empty
``#settings-capture-passes`` slot E5 fills), everything else under one
collapsed ``<details id="settings-advanced">``; Cesium and the engine are
shown, never set; a missing tiles key is a named, fixable message; the
script is served; and, in a headless Chromium (the test_route_page.py
harness: node + global Playwright + its Chromium, skipping with the same
named reason where one is missing), typing the key once, waiting for the
PUT and reloading finds it persisted with at most six visible fields.
"""

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config_surface import flightsim_env_names, ui_keys
from core.util import settings
from tests.test_route_page import CHROMIUM, NODE, _browser_ready, _free_port, _npm_root
from webapp.server import app

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "webapp" / "static"
SCRIPT = (STATIC / "settings.js").read_text(encoding="utf-8")
PAGE = (STATIC / "index.html").read_text(encoding="utf-8")

CLEARED = sorted(flightsim_env_names() | {"GOOGLE_MAPS_API_KEY", "ANTHROPIC_API_KEY"})

TILES_MESSAGE = ("Google tiles key missing: paste it here once "
                 "(Google Maps Platform key with the Map Tiles API)")


@pytest.fixture
def clean(monkeypatch, tmp_path):
    """Empty settings file and an environment without any switch or key."""
    path = tmp_path / "settings.json"
    path.write_bytes(b"")
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    for name in CLEARED:
        monkeypatch.delenv(name, raising=False)
    return path


def _js_list(name):
    match = re.search(rf"^  const {name} = \[(.*?)\];", SCRIPT, re.M)
    assert match, name
    return re.findall(r'"([^"]+)"', match.group(1))


def _panel():
    start = PAGE.index('<section id="settings-panel"')
    return PAGE[start:PAGE.index("</section>", start)]


# -- the page and the module ----------------------------------------------

def test_the_panel_mounts_six_fields_and_an_advanced_fold():
    """The five rendered field names plus the slot are ui_keys(), in order
    (one home: core/config_surface.py); the page mounts the script, a gear
    button and one collapsed Advanced fold."""
    keys = list(ui_keys())
    assert len(keys) == 6
    assert _js_list("FIELDS") + ["capture_passes"] == keys
    assert '<script src="/settings.js"></script>' in PAGE
    assert 'FlightSimSettings.mount(document.getElementById("settings-panel"))' in PAGE
    assert '<button id="settingsToggle" type="button" class="gear"' in PAGE
    panel = _panel()
    assert '<div id="settings-fields"></div>' in panel
    assert '<details id="settings-advanced">' in panel
    assert "<details open" not in panel
    assert panel.index('<div id="settings-fields">') < panel.index('data-field="capture_passes"') \
        < panel.index('<details id="settings-advanced">')
    assert "window.FlightSimSettings = (function () {" in SCRIPT
    for name in ("function mount(el)", "function render(body)", "async function save(key, value)",
                 "function fieldsVisible()", "function messageFor(missing, readonly)"):
        assert name in SCRIPT, name
    assert 'fetch("/settings")' in SCRIPT
    assert 'fetch("/settings", {method: "PUT"' in SCRIPT
    # The advanced fold is not counted as visible.
    assert 'el.closest("details:not([open])")' in SCRIPT
    # Secrets: password inputs with a show toggle.
    assert _js_list("SECRETS") == ["google_tiles_key", "llm_key"]
    assert 'type="password"' in SCRIPT and 'class="settings-show"' in SCRIPT
    # Dark theme, no external resources.
    assert "https://" not in SCRIPT and "http://" not in SCRIPT


def test_missing_tiles_key_shows_a_named_fixable_message(clean):
    """With no key and the tiles on (the default; FLIGHTSIM_GOOGLE_TILES=off
    is the only off switch), GET /settings names google_tiles_key as
    missing and the panel's text for it says what to paste where."""
    body = TestClient(app).get("/settings").json()
    assert body["settings"]["google_tiles"] is True
    assert "google_tiles_key" in [m["key"] for m in body["missing"]]
    assert TILES_MESSAGE in SCRIPT
    messages = SCRIPT[SCRIPT.index("const MESSAGES = {"):SCRIPT.index("};", SCRIPT.index("const MESSAGES = {"))]
    assert "google_tiles_key:" in messages and "llm_key:" in messages
    # Shown next to the input, which is focused, and the panel opened.
    assert 'data-missing="${esc(key)}"' in SCRIPT
    assert 'root.querySelector("#settings-google_tiles_key")' in SCRIPT
    assert "if (input) input.focus();" in SCRIPT
    # Cesium absent: named with the pinned version and the engine.
    assert "not found for engine" in SCRIPT and "install it from" in SCRIPT


def test_cesium_and_engine_are_read_only(clean):
    """Both come from GET readonly.* and render as text, never as a control;
    a PUT of either is refused by name (E2's whitelist)."""
    assert _js_list("READONLY") == ["cesium_status", "engine"]
    assert 'data-readonly="${esc(key)}"' in SCRIPT
    assert "if (READONLY.indexOf(el.name) >= 0) return;" in SCRIPT
    client = TestClient(app)
    body = client.get("/settings").json()
    assert body["readonly"]["engine"] == settings.engine_label()
    assert set(body["readonly"]["cesium_status"]) == {"ok", "name", "version", "message"}
    for key in ("engine", "cesium_status"):
        response = client.put("/settings", json={"settings": {key: "5.7.4"}})
        assert response.status_code == 422
        assert response.json()["detail"].startswith(f"settings.{key}: read-only")


def test_settings_script_is_served():
    response = TestClient(app).get("/settings.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.text == SCRIPT


def test_capture_passes_slot_is_reserved():
    """The sixth field is E3's slot; E5 fills it with #passPicker and its
    three checkboxes, and settings.js leaves it alone (E5's
    loadPasses/savePasses own its inside)."""
    panel = _panel()
    assert panel.count('<div id="settings-capture-passes">') == 1
    slot = panel[panel.index('<div id="settings-capture-passes">'):]
    slot = slot[:slot.index("</div>")]
    assert 'id="passPicker"' in slot
    for box in ("passNormals", "passFlow", "passAmodal"):
        assert slot.count(f'id="{box}"') == 1, box
    assert "settings-capture-passes" not in SCRIPT.replace("#settings-capture-passes; this module never writes into it", "")
    for name in ("passPicker", "passNormals", "passFlow", "passAmodal", "loadPasses", "savePasses"):
        assert name not in SCRIPT, name
        assert name in PAGE, name
    # E4's element and function are untouched by this box.
    assert PAGE.count('id="run"') == 1 and "function startRun" in PAGE


def test_the_status_line_sends_the_user_to_settings():
    assert "add the LLM key in Settings" in PAGE
    assert "no ANTHROPIC_API_KEY in the server" not in PAGE


# -- node and the browser --------------------------------------------------

@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_script_parses():
    subprocess.run([NODE, "--check", str(STATIC / "settings.js")], check=True, timeout=60)


BROWSER_DRIVER = r"""
const { chromium } = require("playwright");
const [base, executablePath, key] = process.argv.slice(2);
(async () => {
  const errors = [];
  const browser = await chromium.launch({headless: true, executablePath, args: ["--no-sandbox"]});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  page.on("console", msg => { if (msg.type() === "error")
    errors.push({text: msg.text(), url: (msg.location() || {}).url || ""}); });
  page.on("pageerror", err => errors.push({text: "pageerror: " + err.message, url: ""}));
  const openPanel = async () => {
    await page.waitForSelector("#settings-google_tiles_key", {state: "attached", timeout: 15000});
    if (await page.$eval("#settings-panel", e => e.hidden)) await page.click("#settingsToggle");
  };
  const snapshot = () => page.evaluate(() => ({
    hidden: document.getElementById("settings-panel").hidden,
    order: Array.from(document.querySelectorAll("#settings-panel [data-field]")).map(e => e.dataset.field),
    visible: window.FlightSimSettings.fieldsVisible(),
    counted: Array.from(document.querySelectorAll("#settings-panel input, #settings-panel select"))
      .filter(e => !e.closest("details:not([open])")).length,
    advancedOpen: document.getElementById("settings-advanced").open,
    advancedRows: document.querySelectorAll("#settings-advanced [data-advanced]").length,
    messages: Array.from(document.querySelectorAll("#settings-panel [data-missing]"))
      .map(e => ({key: e.dataset.missing, text: e.textContent})),
    focused: document.activeElement && document.activeElement.id,
    value: document.getElementById("settings-google_tiles_key").value,
    type: document.getElementById("settings-google_tiles_key").type,
    engine: document.querySelector('[data-readonly="engine"]').textContent,
    cesium: document.querySelector('[data-readonly="cesium_status"]').textContent,
    readonlyControls: document.querySelectorAll('[data-field="engine"] input, [data-field="engine"] select, ' +
      '[data-field="cesium_status"] input, [data-field="cesium_status"] select').length,
    passBoxes: document.querySelectorAll("#settings-capture-passes #passPicker input[type=checkbox]").length,
  }));
  await page.goto(base + "/", {waitUntil: "load"});
  await openPanel();
  const before = await snapshot();
  await page.click('.settings-show[data-for="settings-google_tiles_key"]');
  const shown = await page.$eval("#settings-google_tiles_key", e => e.type);
  await page.fill("#settings-google_tiles_key", key);
  const [response] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith("/settings") && r.request().method() === "PUT", {timeout: 15000}),
    page.dispatchEvent("#settings-google_tiles_key", "change"),
  ]);
  const put = {status: response.status(), body: await response.json()};
  await page.waitForFunction(() => !document.querySelector('[data-missing="google_tiles_key"]'), null, {timeout: 15000});
  const saved = await snapshot();
  await page.reload({waitUntil: "load"});
  await openPanel();
  const after = await snapshot();
  await browser.close();
  console.log(JSON.stringify({before, shown, put, saved, after, errors}));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@pytest.mark.skipif(_browser_ready() is not None, reason=_browser_ready() or "")
def test_tiles_key_survives_a_reload(clean, tmp_path):
    """The Verify line: the panel opens on the missing key with the input
    focused, the key typed once is PUT (200), the message clears, and a
    reload finds the input holding it; at most six fields are visible."""
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    key = "AIza-e3-page-test-key"
    try:
        driver = tmp_path / "drive.js"
        driver.write_text(BROWSER_DRIVER, encoding="utf-8")
        env = {**os.environ, "NODE_PATH": _npm_root()}
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(CHROMIUM.parent))
        run = subprocess.run([NODE, str(driver), f"http://127.0.0.1:{port}", str(CHROMIUM), key],
                             capture_output=True, text=True, timeout=60, env=env)
    finally:
        server.should_exit = True
        thread.join(10)
    assert run.returncode == 0, run.stderr[-4000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])

    before = result["before"]
    assert before["hidden"] is False            # opened by the missing key
    assert before["order"] == list(ui_keys())
    # E5's three pass checkboxes sit in the sixth field; the five rows before it are at most six controls.
    assert before["passBoxes"] == 3
    assert before["visible"] - before["passBoxes"] <= 6 and before["counted"] == before["visible"]
    assert before["advancedOpen"] is False and before["advancedRows"] > 0
    assert {m["key"] for m in before["messages"]} >= {"google_tiles_key"}
    assert any(m["text"] == TILES_MESSAGE for m in before["messages"])
    assert before["focused"] == "settings-google_tiles_key"
    assert before["value"] == "" and before["type"] == "password"
    assert before["engine"] == settings.engine_label()
    assert before["readonlyControls"] == 0
    assert result["shown"] == "text"
    assert result["put"]["status"] == 200
    assert result["put"]["body"]["settings"]["google_tiles_key"] == key
    assert "google_tiles_key" not in [m["key"] for m in result["saved"]["messages"]]
    after = result["after"]
    assert after["value"] == key
    assert after["type"] == "password"
    assert after["visible"] - after["passBoxes"] <= 6
    assert "google_tiles_key" not in [m["key"] for m in after["messages"]]
    assert json.loads(clean.read_text(encoding="utf-8"))["google_tiles_key"] == key
    assert result["errors"] == [], result["errors"]
