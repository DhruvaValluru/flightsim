"""The route map page (webapp/static/route_map.js, mounted by index.html).

The map is the mockup's engine -- the smoothed line, the turn analysis,
the bank-limited pure-pursuit stand-in, self adjust -- over the server's
terrain grid, with every limit read from the payload's `route` block.
What these tests pin is the honesty of that page: the index page mounts
it and resets it with the placer; the module declares the CameraPlacer
shape; no limit is typed into the engine (every numeric literal in it is
listed here, and the few constants that mirror Python are compared to
their Python sources); the engine clears a synthetic hill in node; and a
headless Chromium run against a stub of the three endpoints draws a
line, reads the four checks by rule name, self-adjusts, flies the line,
shows a refusal by name and writes the waypoints into the spec dict,
with no console errors. The browser run skips cleanly without node or
the Playwright Chromium.

The stub app is this test's own (docs/ROUTE.md: the endpoints are the
server part's); it serves the real index page and scripts through the
real app, with POST /route/terrain, POST /route/check and GET
/route_map.js stubbed in front of it, so the page is exercised against
the documented payload shapes whether or not the server part has landed.
"""

import json
import math
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "webapp" / "static"
SCRIPT = (STATIC / "route_map.js").read_text(encoding="utf-8")
PAGE = (STATIC / "index.html").read_text(encoding="utf-8")

NODE = shutil.which("node")
#: Where this machine keeps the Playwright Chromium (the task's pin), and
#: where the global node modules (playwright) live.
CHROMIUM = Path(os.environ.get("FLIGHTSIM_TEST_CHROMIUM", "/opt/pw-browsers/chromium"))


def _npm_root():
    if not NODE:
        return None
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        out = subprocess.run([npm, "root", "-g"], capture_output=True, text=True,
                             timeout=30, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    return out or None


def _browser_ready():
    """node, Playwright and its Chromium, or the reason one is missing."""
    if not NODE:
        return "node is not installed"
    root = _npm_root()
    if not root or not (Path(root) / "playwright").exists():
        return "playwright is not installed globally (npm root -g)"
    if not CHROMIUM.exists():
        return f"no Chromium at {CHROMIUM}"
    return None


# -- the page and the module ----------------------------------------------

def test_the_page_mounts_the_map_beside_the_camera_buttons():
    assert '<script src="/route_map.js"></script>' in PAGE
    assert '<div id="routeMap"></div>' in PAGE
    assert '<div id="routeState" class="dim"></div>' in PAGE
    assert 'routeBtn.textContent = "+ draw the flight path"' in PAGE
    assert "function openRouteMap()" in PAGE
    assert 'container: $("routeMap")' in PAGE
    # The map hands back waypoints; the page writes them as user-stated
    # fields with the map's provenance, and the heading as a user edit.
    assert 'dict.route.waypoints = {value: route.waypoints, unit: "points",' in PAGE
    assert 'dict.route.bank_limit_deg = {value: route.bank_limit_deg, unit: "deg",' in PAGE
    assert 'setRow("heading", route.heading_deg);' in PAGE
    # Reset with the placer on a new compile.
    assert "if (window.RouteMap) RouteMap.close();" in PAGE
    assert PAGE.index("CameraPlacer.close();") < PAGE.index("if (window.RouteMap) RouteMap.close();")
    # The route block's row is read-only: the map edits the block.
    assert 'f.section !== "route"' in PAGE


def test_the_post_run_chart_draws_the_planned_route_dotted():
    """initFlightPath reads card.json's route.waypoints and draws them
    dotted under the flown track, from (0, 0): the card's frame is metres
    about the spec origin, the chart's about the first sample, and the
    two coincide at t = 0."""
    chart = PAGE[PAGE.index("async function initFlightPath"):]
    chart = chart[:chart.index("async function initAeroPanel")]
    assert "card.route.waypoints" in chart
    assert "[{e: 0, n: 0}].concat(card.route.waypoints.map" in chart
    assert "ctx.setLineDash([3, 5])" in chart
    assert "planned route (dotted magenta) = the run card's" in chart
    # Under the track: the dotted line is drawn before the coloured track.
    assert chart.index("The planned route, dotted") < chart.index("The track, coloured start->end")


def test_the_module_declares_the_placer_shape():
    assert SCRIPT.startswith('"use strict";')
    assert "window.RouteMap = (function () {" in SCRIPT
    assert "async function open" in SCRIPT
    assert "return {open, close: () => current && current.close()," in SCRIPT
    assert 'fetch("/route/terrain"' in SCRIPT
    assert 'fetch("/route/check"' in SCRIPT
    assert "this.opts.onPlaced(route)" in SCRIPT
    # Dark theme, no CDN, no fonts, no external resources.
    assert "https://" not in SCRIPT and "http://" not in SCRIPT
    assert "@import" not in SCRIPT and "<link" not in SCRIPT
    assert '"SF Mono", Menlo, monospace' in SCRIPT


def test_the_checks_carry_the_rule_names_and_the_caveat_once():
    for name in ("route.time", "route.turn", "route.terrain_clearance", "route.climb"):
        assert f'id: "{name}"' in SCRIPT, name
    # Sentence first, rule name underneath in small type.
    assert '<span class="t">${esc(c.t)}</span><span class="m">${esc(c.m)}</span>' in SCRIPT
    assert '<span class="rm-rule">${esc(c.id)}</span>' in SCRIPT
    code = "\n".join(l for l in SCRIPT.splitlines() if not l.strip().startswith("//"))
    assert code.count("measured on the map's grid") == 1
    # The climb check is honest about what its limit is.
    assert "its own bound, not a measured airframe climb figure" in SCRIPT
    # The clock is the payload's seconds, and the clip cap is named as such.
    assert "the render's ${esc(fmtN(lim.seconds))} s clip" in SCRIPT
    assert "the render's ${fmtN(R.T)} s clip" in SCRIPT


def test_the_module_refuses_a_payload_without_its_limits():
    """A missing limit draws nothing rather than guessing one."""
    block = SCRIPT[SCRIPT.index("async function open"):]
    assert '["tas_kt", "turn_radius_m", "bank_limit_deg", "hdot_max_mps", "min_clearance_m", "lookahead_m", "seconds"]' in block
    assert "the map draws nothing rather than guess a limit" in block


# -- no limit is typed into the engine ------------------------------------

#: Every named number in the module, pinned: geometry, the engine's own
#: resolution and self adjust's margins. A limit (the clearance floor, the
#: climb clip, the bank, the lookahead, the clip cap, the waypoint cap)
#: is NOT here because it comes from the payload.
NAMED_CONSTANTS = {
    "G_MPS2": 9.80665, "KT_TO_MPS": 0.514444, "TURN_RADIUS_SLACK": 0.9,
    "CLIMB_MIN_LEG_S": 1, "RESAMPLE_PER_RADIUS": 30, "RESAMPLE_STEP_MIN_M": 5,
    "RESAMPLE_STEP_MAX_M": 60, "CHAIKIN_PASSES": 3, "SIM_DT_S": 0.05,
    "ADJ_MARGIN_FRACTION": 0.25, "RATE_MARGIN": 0.97, "BANK_IN_HAND": 0.85,
    "ALT_ROUND_M": 10, "ADJUST_ITERATIONS": 12, "ALTITUDE_PASSES": 6,
    "ADJUST_BUDGET_MS": 2000, "LOST_FRACTION": 0.4, "LOW_STRETCH_GAP_S": 2,
    "PIN_STEP_M": 50,
}

#: Every bare numeric literal the engine block may use: geometry (halves,
#: quarters, the 1e-6 zero test, the 0.1 % reach tolerance, the 1.5-radius
#: marker merge, the 5-degree bank rounding, the 0.1 m waypoint rounding,
#: the "straight line" 50-radii threshold, the pushClear slope floor and
#: lever fractions). Nothing here is metres of clearance, knots or a clip.
ENGINE_LITERALS = {0, 1e-6, 0.05, 0.25, 0.5, 0.6, 0.75, 1, 1.001, 1.5, 2, 3, 4,
                   5, 10, 50}

#: The Python limits the page must never carry as its own numbers.
FORBIDDEN_LIMITS = ("150", "12.19", "12.192", "400", "120", "22", "25", "300", "60.0")


def _engine_block():
    start = SCRIPT.index("/*ENGINE*/")
    end = SCRIPT.index("/*ENDENGINE*/")
    code = SCRIPT[start:end]
    return "\n".join(l for l in code.splitlines() if not l.strip().startswith("//"))


def test_every_limit_the_js_uses_comes_from_the_payload():
    consts = {name: float(value) for name, value in
              re.findall(r"^  const ([A-Z_0-9]+) = (-?[\d.]+);", SCRIPT, re.M)}
    assert consts == NAMED_CONSTANTS
    engine = _engine_block()
    found = {float(x) for x in re.findall(
        r"(?<![\w.])(\d+(?:\.\d+)?(?:e-?\d+)?)(?![\w.])", engine)}
    assert found <= ENGINE_LITERALS, sorted(found - ENGINE_LITERALS)
    # Every limit the engine reads is a field of the payload's route block.
    for key in ("tas_kt", "seconds", "min_clearance_m", "hdot_max_mps", "lookahead_m"):
        assert f"lim.{key}" in engine, key
    # The reach is TAS x seconds and the radius the formula route.py uses.
    assert "reach = V * T" in engine
    assert "return V * V / (G_MPS2 * Math.tan(bankDeg * DEG));" in engine
    for literal in FORBIDDEN_LIMITS:
        assert not re.search(rf"(?<![\w.]){re.escape(literal)}(?![\w.])", engine), literal


def test_the_mirrored_constants_match_python():
    """The four numbers the JS shares with Python are Python's (the
    lens_picker precedent: pinned by regex, one source each)."""
    from webapp.camera_placer import KT_TO_MPS

    assert NAMED_CONSTANTS["KT_TO_MPS"] == KT_TO_MPS
    route = pytest.importorskip("core.control.route")
    assert NAMED_CONSTANTS["G_MPS2"] == route.G_MPS2
    assert NAMED_CONSTANTS["TURN_RADIUS_SLACK"] == route.TURN_RADIUS_SLACK
    assert NAMED_CONSTANTS["CLIMB_MIN_LEG_S"] == route.CLIMB_MIN_LEG_S


# -- node: the script parses, the engine clears a hill ------------------

@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_script_parses():
    subprocess.run([NODE, "--check", str(STATIC / "route_map.js")], check=True, timeout=60)


# The synthetic hill both node runs use: a 65 x 65 grid, 3 km each way,
# a 1,200 m Gaussian hill north of the start on a 2,000 m datum, so a
# line straight north at 3,000 m meets the ground.
GRID_POINTS, GRID_HALF_M, DATUM_M = 65, 3000.0, 2000.0
GRID_STEP_M = 2 * GRID_HALF_M / (GRID_POINTS - 1)
#: The stub's limits, the shape of the server's route block. The values
#: are the fixture's own (120 kt true, 20 s), with the Python constants
#: where the real payload would carry them.
STUB_TAS_KT, STUB_BANK_DEG, STUB_SECONDS = 120.0, 25.0, 20.0


def _route_limits(seconds):
    try:
        from core.control.route import (
            HDOT_MAX_MPS, LOOKAHEAD_LENGTH_FRACTION, MIN_LOOKAHEAD_M, ROUTE_MIN_CLEARANCE_M,
            lookahead_m_for, turn_radius_m)
        radius = turn_radius_m(STUB_TAS_KT, STUB_BANK_DEG)
        lookahead = lookahead_m_for(STUB_TAS_KT)
        floor, hdot = ROUTE_MIN_CLEARANCE_M, HDOT_MAX_MPS
        min_look, look_frac = MIN_LOOKAHEAD_M, LOOKAHEAD_LENGTH_FRACTION
    except ImportError:          # the core part has not landed: the design's values
        v = STUB_TAS_KT * 0.514444
        radius = v * v / (9.80665 * math.tan(math.radians(STUB_BANK_DEG)))
        lookahead, floor, hdot = max(120.0, 4.0 * v), 150.0, 12.192
        min_look, look_frac = 120.0, 0.25
    return {"tas_kt": STUB_TAS_KT, "turn_radius_m": radius, "bank_limit_deg": STUB_BANK_DEG,
            "hdot_max_mps": hdot, "min_clearance_m": floor, "lookahead_m": lookahead,
            "min_lookahead_m": min_look, "lookahead_length_fraction": look_frac,
            "seconds": seconds}


def _hill(north, east):
    return DATUM_M + 1200.0 * math.exp(
        -((north - 1800.0) ** 2 + (east + 400.0) ** 2) / (2 * 700.0 ** 2))


def _grid_payload():
    heights = [round(_hill(-GRID_HALF_M + r * GRID_STEP_M, -GRID_HALF_M + c * GRID_STEP_M), 1)
               for r in range(GRID_POINTS) for c in range(GRID_POINTS)]
    return {"points": GRID_POINTS, "step_m": GRID_STEP_M, "south_m": -GRID_HALF_M,
            "west_m": -GRID_HALF_M, "heights_m": heights}


ENGINE_PROBE = r"""
const fs = require("fs");
global.window = {};
new Function(fs.readFileSync(process.argv[2], "utf8"))();
const fixture = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const {compute, selfAdjust, exportWaypoints, Grid} = window.RouteMap._engine;
const grid = new Grid({kind: "raster", datum_m: fixture.datum_m, grid: fixture.grid});
const lim = {...fixture.route, heading_deg: 0};
const S = {strokes: [fixture.stroke], pins: [], alt0: fixture.alt0, bank: lim.bank_limit_deg};
const status = R => Object.fromEntries(R.checks.map(c => [c.id, c.s]));
const R0 = compute(S, lim, grid);
const res = selfAdjust(S, lim, grid, 4000);
let after = null, waypoints = null, capped = null;
if (res) {
  const R1 = compute({...S, strokes: res.strokes, pins: res.pins, alt0: res.alt0}, lim, grid);
  after = {status: status(R1), minClr: R1.minClr};
  waypoints = exportWaypoints(R1, 0);
  capped = exportWaypoints(R1, 6).length;
}
console.log(JSON.stringify({before: {status: status(R0), minClr: R0.minClr, len: R0.len},
  ok: res && res.ok, changes: res && res.changes.map(c => c.kind), maxMove: res && res.maxMove,
  alt0: res && res.alt0, after, waypoints, capped}));
"""


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_the_engine_self_adjusts_a_line_over_the_hill(tmp_path):
    """A line straight over the synthetic hill fails route.terrain_clearance
    on the grid; self adjust pushes it sideways toward lower ground (the
    mockup's rule, the grid's slope as the lever) and the result passes
    every check, exports as a handful of waypoints that never repeat the
    origin, and honours a waypoint cap."""
    fixture = {"datum_m": DATUM_M, "grid": _grid_payload(), "route": _route_limits(40.0),
               "alt0": 3000.0,
               "stroke": [{"x": -100, "y": 600}, {"x": -300, "y": 1500}, {"x": -400, "y": 2400}]}
    (tmp_path / "fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    (tmp_path / "probe.js").write_text(ENGINE_PROBE, encoding="utf-8")
    out = subprocess.run([NODE, str(tmp_path / "probe.js"), str(STATIC / "route_map.js"),
                          str(tmp_path / "fixture.json")],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    result = json.loads(out)
    assert result["before"]["status"]["route.terrain_clearance"] == "error"
    assert result["before"]["minClr"] < 0
    assert result["ok"] is True, result
    assert "lateral" in result["changes"]
    assert result["after"]["status"] == {"route.time": "ok", "route.turn": "ok",
                                         "route.terrain_clearance": "ok", "route.climb": "ok"}
    assert result["after"]["minClr"] >= fixture["route"]["min_clearance_m"]
    # Sideways first: the altitude was not touched.
    assert result["alt0"] == 3000.0
    wps = result["waypoints"]
    assert 3 <= len(wps) <= 60
    assert all(set(w) == {"east_m", "north_m", "alt_m"} for w in wps)
    assert all(math.hypot(w["east_m"], w["north_m"]) > 1 for w in wps)
    assert result["capped"] <= 6


# -- the browser ----------------------------------------------------------

def _stub_app():
    """The real app behind this test's own stubs of the three endpoints."""
    from fastapi import FastAPI, Response
    from fastapi.responses import FileResponse, JSONResponse

    from webapp.server import app as real_app

    stub = FastAPI()
    limits = _route_limits(STUB_SECONDS)
    v_mps = STUB_TAS_KT * 0.514444

    @stub.get("/route_map.js")
    def script():
        return FileResponse(STATIC / "route_map.js", media_type="text/javascript")

    @stub.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    @stub.post("/route/terrain")
    def terrain(body: dict):
        spec = body["spec"]
        return {"kind": "raster",
                "scene": {"key": "stub", "label": "synthetic hill", "refused": None},
                "grid": _grid_payload(), "datum_m": DATUM_M,
                "aircraft": {"aircraft": str(spec["aircraft"]["aircraft"]["value"]),
                             "north_m": 0.0, "east_m": 0.0,
                             "alt_m": float(spec["initial"]["altitude"]["value"]),
                             "heading_deg": float(spec["initial"]["heading"]["value"] or 0.0)},
                "track": [], "traffic": [], "clip_seconds": STUB_SECONDS,
                "min_clearance_m": 30.0, "route": {**limits, "waypoints": []}}

    @stub.post("/route/check")
    def check(body: dict):
        bank = float(body.get("bank_limit_deg") or 0.0)
        if not 5.0 < bank <= 60.0:
            # The validator's shape, worded as the server words it.
            return JSONResponse({"ok": False, "violations": [{
                "constraint": "route.bank_limit", "actual": bank, "limit": 60.0, "unit": "deg",
                "message": f"bank limit {bank:g} deg is outside (5, 60]",
                "sentence": "A bank limit of 70 degrees is outside what the autopilot "
                            "accepts; it must be between 5 and 60 degrees.",
                "hint": "Ask for a bank limit between 5 and 60 degrees.",
                "details": {"rule": "route.bank_limit"}}]}, status_code=400)
        pts = [(0.0, 0.0, float(body["spec"]["initial"]["altitude"]["value"]))]
        pts += [(w["east_m"], w["north_m"], w["alt_m"]) for w in body["waypoints"]]
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        cols = {k: [] for k in ("t_s", "north_m", "east_m", "alt_m", "agl_m", "heading_deg", "roll_deg")}
        t = 0.0
        while t <= STUB_SECONDS:
            d, i = v_mps * t, 0
            while i < len(cum) - 2 and cum[i + 1] < d:
                i += 1
            f = max(0.0, min(1.0, (d - cum[i]) / ((cum[i + 1] - cum[i]) or 1.0)))
            e, n, alt = (pts[i][k] + (pts[i + 1][k] - pts[i][k]) * f for k in range(3))
            cols["t_s"].append(t); cols["north_m"].append(n); cols["east_m"].append(e)
            cols["alt_m"].append(alt); cols["agl_m"].append(alt - _hill(n, e))
            cols["heading_deg"].append(90.0); cols["roll_deg"].append(0.0)
            t += 0.5
        return {"flown": cols, "min_clearance_m": min(cols["agl_m"]), "max_cross_track_m": 15.0,
                "closure": [{"name": "cross_track_max", "commanded": 0.0, "achieved": 15.0,
                             "tolerance": 75.0, "unit": "m", "ok": True}],
                "violations": [], "ok": True, "seconds": STUB_SECONDS}

    stub.mount("/", real_app)
    return stub


BROWSER_DRIVER = r"""
const { chromium } = require("playwright");
const [base, executablePath] = process.argv.slice(2);
(async () => {
  const errors = [];
  const browser = await chromium.launch({headless: true, executablePath, args: ["--no-sandbox"]});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  page.on("console", msg => { if (msg.type() === "error")
    errors.push({text: msg.text(), url: (msg.location() || {}).url || ""}); });
  page.on("pageerror", err => errors.push({text: "pageerror: " + err.message, url: ""}));
  const settled = sel => page.waitForFunction(s => {
    const e = document.querySelector(s); return e && !e.hidden && e.dataset.s !== "run"; }, sel, {timeout: 15000});
  const checks = () => page.$$eval("#routeMap .rm-checks li", els => els.map(e => ({
    rule: e.dataset.rule, s: e.dataset.s, t: e.querySelector(".t").textContent,
    m: e.querySelector(".m").textContent, ruleText: e.querySelector(".rm-rule").textContent})));
  await page.goto(base + "/", {waitUntil: "load"});
  await page.fill("#prompt", "fly the A4 at 3000 m and 350 kt for 20 seconds");
  await page.click("#compile");
  await page.waitForSelector("#routeMapOpen", {timeout: 40000});
  await page.click("#routeMapOpen");
  await page.waitForSelector("#routeMap .rm-map", {timeout: 15000});
  await page.waitForFunction(() => document.querySelectorAll("#routeMap .rm-checks li").length === 4);
  // The map scrolls itself into view smoothly; measure it once it has settled.
  await page.evaluate(() => document.getElementById("routeMap").scrollIntoView({block: "start"}));
  await page.waitForTimeout(400);
  const idle = await checks();
  const caveats = await page.$eval("#routeMap", e => e.textContent.split("measured on the map's grid").length - 1);
  const box = await page.locator("#routeMap .rm-map").boundingBox();
  const topPad = await page.evaluate(() => document.querySelector("#routeMap .rm-toolbar").offsetHeight + 16);
  const cx = box.x + box.width / 2, cy = box.y + topPad + (box.height - topPad) / 2;
  // Draw with the pen: from the aircraft, east, further than the reach.
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  for (let i = 1; i <= 10; i++) await page.mouse.move(cx + i * box.width * 0.045, cy - Math.sin(i / 10 * Math.PI) * 30);
  await page.mouse.up();
  await page.waitForTimeout(100);
  const drawn = await checks();
  await page.click("#routeMap .rm-adjust");
  await settled("#routeMap .rm-adjusted");
  const adjusted = await page.$eval("#routeMap .rm-adjusted", e => ({s: e.dataset.s, text: e.textContent}));
  const afterAdjust = await checks();
  await page.click("#routeMap .rm-physics");
  await settled("#routeMap .rm-result");
  const physics = await page.$eval("#routeMap .rm-result", e => ({s: e.dataset.s, text: e.textContent}));
  const legend = await page.$eval("#routeMap .rm-legphys", e => e.hidden);
  await page.click("#routeMap .rm-use");
  const used = await page.evaluate(() => ({
    state: document.getElementById("routeState").textContent,
    heading: document.querySelector('#specTable input[data-name="heading"]').value,
    headingSrc: document.querySelector('#specTable [data-src="heading"]').textContent,
    route: editedSpecDict().route}));
  await page.fill("#routeMap .rm-bank", "70");
  await page.dispatchEvent("#routeMap .rm-bank", "change");
  await page.click("#routeMap .rm-physics");
  await settled("#routeMap .rm-result");
  const refusal = await page.$eval("#routeMap .rm-result", e => ({s: e.dataset.s, text: e.textContent}));
  await page.click("#routeMap .rm-close");
  const closed = await page.$eval("#routeMap", e => e.innerHTML === "");
  await browser.close();
  console.log(JSON.stringify({idle, caveats, drawn, adjusted, afterAdjust, physics, legend, used, refusal, closed, errors}));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(_browser_ready() is not None, reason=_browser_ready() or "")
def test_the_map_draws_checks_adjusts_and_flies_in_a_browser(tmp_path):
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_stub_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    try:
        driver = tmp_path / "drive.js"
        driver.write_text(BROWSER_DRIVER, encoding="utf-8")
        env = {**os.environ, "NODE_PATH": _npm_root()}
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(CHROMIUM.parent))
        run = subprocess.run([NODE, str(driver), f"http://127.0.0.1:{port}", str(CHROMIUM)],
                             capture_output=True, text=True, timeout=50, env=env)
    finally:
        server.should_exit = True
        thread.join(10)
    assert run.returncode == 0, run.stderr[-4000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])

    rules = ["route.time", "route.turn", "route.terrain_clearance", "route.climb"]
    assert [c["rule"] for c in result["idle"]] == rules
    assert [c["ruleText"] for c in result["idle"]] == rules
    assert result["caveats"] == 1
    # The clearance floor shown is the payload's.
    floor = _route_limits(STUB_SECONDS)["min_clearance_m"]
    assert f"The minimum is {floor:,.0f} m." in result["idle"][2]["m"]
    assert "its own bound, not a measured airframe climb figure" in result["idle"][3]["m"]

    drawn = {c["rule"]: c for c in result["drawn"]}
    assert drawn["route.time"]["s"] == "warn", drawn
    assert "so the run ends at the flag" in drawn["route.time"]["m"]
    assert drawn["route.turn"]["s"] == "ok"
    assert drawn["route.terrain_clearance"]["s"] == "ok"
    assert drawn["route.climb"]["s"] == "ok"

    assert result["adjusted"]["s"] == "ok", result["adjusted"]
    assert "Cut" in result["adjusted"]["text"]
    assert all(c["s"] == "ok" for c in result["afterAdjust"]), result["afterAdjust"]

    assert result["physics"]["s"] == "ok", result["physics"]
    for words in ("lowest above the ground", "(on the raster)", "furthest from your line",
                  "closure · cross_track_max", "Flown by the physics"):
        assert words in result["physics"]["text"], words
    assert result["legend"] is False       # the flown track's legend entry shows

    used = result["used"]
    assert "drawn on the route map, then self-adjusted" in used["state"]
    route = used["route"]
    assert route["waypoints"]["unit"] == "points"
    assert route["waypoints"]["source"] == "user"
    assert route["waypoints"]["from"] == "drawn on the route map, then self-adjusted"
    assert route["bank_limit_deg"] == {"value": STUB_BANK_DEG, "unit": "deg", "source": "user",
                                       "from": "drawn on the route map, then self-adjusted"}
    wps = route["waypoints"]["value"]
    assert 2 <= len(wps) <= 60
    assert all(math.hypot(w["east_m"], w["north_m"]) > 1 for w in wps)
    # Eastward line: the first leg's bearing became the heading, a user edit.
    assert 20 < float(used["heading"]) < 160, used["heading"]
    assert used["headingSrc"] == "user (edited)"

    assert result["refusal"]["s"] == "error"
    assert "route.bank_limit" in result["refusal"]["text"]
    assert "between 5 and 60 degrees" in result["refusal"]["text"]
    assert "Nothing was flown" in result["refusal"]["text"]
    assert result["closed"] is True

    # No console errors but the refused check's own 400, which Chromium
    # logs as a failed resource load.
    unexpected = [e for e in result["errors"]
                  if not (e["url"].endswith("/route/check") and "400" in e["text"])]
    assert not unexpected, unexpected


def test_the_server_serves_the_script():
    """GET /route_map.js is the server part's (docs/ROUTE.md); until it
    lands, this says so instead of failing the page."""
    from fastapi.testclient import TestClient

    from webapp.server import app

    reply = TestClient(app).get("/route_map.js")
    if reply.status_code == 404:
        pytest.skip("GET /route_map.js is added by the server part (webapp/server.py)")
    assert reply.status_code == 200
    assert "javascript" in reply.headers["content-type"]
    assert "window.RouteMap" in reply.text
