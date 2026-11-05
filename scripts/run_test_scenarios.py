"""Run the test scenarios through the web app, one after another.

The app must already be running (``python -m uvicorn webapp.server:app
--port 8008``). For each scenario this does what the page does: Interpret
(``/compile``), apply the scenario's lighting edits to the spec, Run
(``/run``; a place with no terrain yet is baked through ``/bake`` and run
again), then waits for the run to finish before the next one starts (the
server runs one at a time). At the end it prints one line per scenario --
done, failed or refused, with the run id and the clip line -- writes the
same as ``runs/test_scenarios.json``, and copies every finished run's clip
(or its frame, with ``--still``) and its boxed pictures into ONE folder,
``runs/test_scenarios/``, named by scenario, with an ``index.html`` that
shows them all on one page.

    python scripts/run_test_scenarios.py                 # all of them, 3 s clips
    python scripts/run_test_scenarios.py --only 1 4 7    # just these
    python scripts/run_test_scenarios.py --still         # 1 frame each (fast look check)
    python scripts/run_test_scenarios.py --list          # print the scenarios
    python scripts/run_test_scenarios.py --collect       # (re)gather the last batch's results
    python scripts/run_test_scenarios.py --matrix        # Phase 3 D6: {A4,J11} x {desert,forest}
    python scripts/run_test_scenarios.py --matrix --list # print the four cells

Open http://127.0.0.1:8008, or each run's frames page, to look at the
results. Run it with the venv's python (--matrix reads webapp.runs).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

#: (name, prompt, lighting edits). Every prompt was compiled and validated
#: with the offline interpreter; the AI interpreter may read one slightly
#: differently, which the summary's notes show.
SCENARIOS = [
    ("golden hour A-4, flying east",
     "chase view of the a4 at 1500 m over yosemite at golden hour, flying east, for 6 seconds", {}),
    ("same, super bright preset",
     "chase view of the a4 at 1500 m over yosemite at golden hour, flying east, for 6 seconds",
     {"preset": "super_bright"}),
    ("a320 over new york, wide lens (terrain download)",
     "chase view of the a320 over new york city at 600 m in the morning with a 18 mm lens for 6 seconds", {}),
    ("desert A-4, sun behind the camera",
     "chase view of the a4 at 2000 m over the desert at 17:30, flying southwest, for 6 seconds",
     # Heading 225 (south-west); the chase camera sits behind, to the
     # north-east, so light FROM the north-east (45) comes from behind it.
     {"sun_azimuth_deg": 45.0, "sun_elevation_deg": 20.0}),
    ("desert A-4, backlit",
     "chase view of the a4 at 2000 m over the desert at 17:30, flying southwest, for 6 seconds",
     {"sun_azimuth_deg": 225.0, "sun_elevation_deg": 12.0}),
    ("a320 over sfo heading south, moderate rain",
     "wingman view of the a320 over sfo south at 3000 m in moderate rain for 6 seconds", {}),
    ("tower view, heavy rain",
     "tower view of the a320 at 1000 m in heavy rain for 6 seconds", {}),
    ("c172 over fuji, sunrise, light rain",
     "chase view of the c172p over mount fuji at sunrise in light rain for 6 seconds", {}),
    ("747 through a thunderstorm",
     "chase view of the 747 flying west through a thunderstorm at 2000 m for 6 seconds", {}),
    ("c172 near a tornado",
     "chase view of the c172p near a tornado over the flint hills at 600 m for 6 seconds", {}),
    ("A-4 over the matterhorn, strong wind, severe turbulence",
     "chase view of the a4 over the matterhorn at 5000 m in strong wind and severe "
     "turbulence, flying north, for 6 seconds", {}),
    ("c172 cockpit over the grand canyon",
     "cockpit view of the c172p over the grand canyon at 2500 m flying east for 6 seconds", {}),
    ("747 cruise over the ocean",
     "chase view of the 747 over the ocean at 10000 m at noon for 6 seconds", {}),
    ("hurricane (should be refused: not supported)",
     "fly the 747 through a hurricane", {}),
]

DONE = ("done", "failed")


def call(server: str, method: str, path: str, body=None, timeout: float = 3600.0):
    """(HTTP status, parsed JSON) -- a 4xx/5xx is an answer, not an error."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(server + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except ValueError:
            return exc.code, {"error": text[:300]}


def why(payload) -> str:
    """The refusal in words: the plain sentence, the rule's name and its
    own message -- the sentence alone is sometimes only "refused"."""
    if not isinstance(payload, dict):
        return str(payload)[:300]
    violations = payload.get("violations") or []
    if violations:
        return "; ".join(f"[{v.get('constraint')}] {v.get('sentence') or v.get('message')}"
                         for v in violations)[:400]
    parts = []
    for key in ("sentence", "constraint", "refused", "message", "error"):
        text = " ".join(str(payload.get(key) or "").split())
        if text and not any(text in part for part in parts):
            parts.append(f"[{text}]" if key == "constraint" else text)
    return (" ".join(parts) or json.dumps(payload))[:400]


def apply_lighting(spec_dict, edits) -> None:
    for name, value in edits.items():
        entry = spec_dict["lighting"][name]
        entry.update(value=value, source="user", **{"from": "scripts/run_test_scenarios.py"})


def run_one(server, number, name, prompt, edits, args):
    result = {"number": number, "name": name, "prompt": prompt, "lighting": edits}
    body = {"prompt": prompt, "compiler": args.compiler}
    if args.still:
        body["still"] = True
    else:
        body["clip_seconds"] = args.clip
    status, payload = call(server, "POST", "/compile", body)
    if status != 200 or "spec" not in payload:
        return {**result, "outcome": "refused", "why": why(payload)}
    result["compiler"] = payload.get("compiler")
    result["notes"] = payload["spec"].get("notes", [])
    if not payload["validation"]["ok"]:
        return {**result, "outcome": "refused", "why": why(payload["validation"])}
    spec_dict = payload["spec"]["dict"]
    apply_lighting(spec_dict, edits)
    return run_spec(server, result, spec_dict, payload.get("compiler"), args)


def run_spec(server, result, spec_dict, compiler_name, args):
    """POST the edited spec to /run (baking the place on a 409
    ``terrain.unbaked`` and running again), poll GET /runs/{id} until the
    run is done or failed, and return ``result`` completed with outcome,
    why, run_id, clip and conditions. The /run body is
    ``{"spec": spec_dict, "provenance": {...}}`` and nothing else."""
    run_body = {"spec": spec_dict, "provenance": {"compiler": compiler_name}}

    status, started = call(server, "POST", "/run", run_body)
    if status == 409 and started.get("refused") == "terrain.unbaked":
        print(f"    downloading terrain for {started['latitude']:.3f}, {started['longitude']:.3f} ...")
        status, baked = call(server, "POST", "/bake", {"latitude": started["latitude"],
                                                       "longitude": started["longitude"]})
        if status != 200:
            return {**result, "outcome": "refused", "why": "terrain: " + why(baked)}
        status, started = call(server, "POST", "/run", run_body)
    if status != 200 or "run_id" not in started:
        return {**result, "outcome": "refused", "why": why(started)}

    run_id = started["run_id"]
    result["run_id"] = run_id
    print(f"    run {run_id} started")
    last = None
    while True:
        time.sleep(args.poll)
        status, state = call(server, "GET", f"/runs/{run_id}")
        if status != 200:
            return {**result, "outcome": "failed", "why": why(state)}
        line = f"{state.get('status')}: {state.get('detail', '')}"
        if line != last:
            print(f"    {line[:160]}")
            last = line
        if state.get("status") in DONE:
            break
    events = state.get("events") or []
    clip = next((e["detail"] for e in reversed(events)
                 if str(e.get("detail", "")).startswith("clip:")), None)
    return {**result, "outcome": state["status"], "why": state.get("detail", ""),
            "clip": clip, "conditions": state.get("conditions")}


REPO = Path(__file__).resolve().parents[1]
#: Where the web app writes each run (webapp.runs.RunManager's default).
RUNS = REPO / "runs" / "webapp"
SUMMARY = REPO / "runs" / "test_scenarios.json"
GALLERY = REPO / "runs" / "test_scenarios"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48]


def _first(directory: Path, pattern: str):
    found = sorted(directory.glob(pattern)) if directory.is_dir() else []
    return found[0] if found else None


def collect(results) -> Path:
    """Copy each finished run's clip (or first frame) and its boxed
    pictures into GALLERY as NN_<name>.*, and write index.html there."""
    GALLERY.mkdir(parents=True, exist_ok=True)
    cards = []
    for r in results:
        stem = f"{int(r['number']):02d}_{_slug(r['name'])}"
        media = []
        run_dir = RUNS / str(r.get("run_id") or "-")
        if r.get("run_id") and run_dir.is_dir():
            camera_dirs = sorted(d for d in (run_dir / "frames").glob("*") if d.is_dir()) \
                if (run_dir / "frames").is_dir() else []
            camera = camera_dirs[0].name if camera_dirs else None
            picks = [("clip.mp4", run_dir / "clip.mp4"),
                     ("view.mp4", _first(run_dir / "clips", "*.mp4"))]
            if camera:
                picks += [("frame.png", _first(run_dir / "frames" / camera, "frame_*[0-9].png")),
                          ("boxes.png", _first(run_dir / "boxed" / camera, "*_boxes.png")),
                          ("box3d.png", _first(run_dir / "boxed3d" / camera, "*_box3d.png"))]
            have_clip = False
            for label, source in picks:
                if source is None or not Path(source).is_file():
                    continue
                if label == "view.mp4" and have_clip:
                    continue              # the panel clip already shows this view
                target = GALLERY / f"{stem}_{label}"
                shutil.copy2(source, target)
                media.append(target.name)
                have_clip = have_clip or label.endswith(".mp4")
            r["frames_page"] = (f"http://127.0.0.1:8008/frames.html?run={r['run_id']}"
                                f"&camera={camera}" if camera else None)
        r["gallery_files"] = media
        tiles = "".join(
            (f'<video src="{html.escape(m)}" controls loop muted playsinline></video>'
             if m.endswith(".mp4") else f'<a href="{html.escape(m)}"><img src="{html.escape(m)}"></a>')
            for m in media) or '<div class="none">nothing rendered</div>'
        link = (f' &middot; <a href="{html.escape(r["frames_page"])}">every frame with its labels</a>'
                if r.get("frames_page") else "")
        cards.append(
            f'<section class="{html.escape(r["outcome"])}"><h2>{int(r["number"])}. '
            f'{html.escape(r["name"])} <span>{html.escape(r["outcome"].upper())}</span></h2>'
            f'<p class="prompt">{html.escape(r["prompt"])}</p>'
            + (f'<p class="why">{html.escape(str(r.get("why", "")))}</p>' if r["outcome"] != "done" else "")
            + (f'<p class="clip">{html.escape(r["clip"])}</p>' if r.get("clip") else "")
            + f'<div class="media">{tiles}</div>'
            + (f'<p class="run">run {html.escape(r["run_id"])}{link}</p>' if r.get("run_id") else "")
            + "</section>")
    page = ("<!doctype html><meta charset='utf-8'><title>Test scenarios</title><style>"
            "body{font:14px/1.5 system-ui,sans-serif;background:#101418;color:#d8dde2;margin:1.5rem}"
            "section{background:#151b22;border:1px solid #232d38;border-radius:8px;padding:1rem;margin:0 0 1rem}"
            "h2{font-size:1.05rem;margin:0}h2 span{font-size:.8rem;margin-left:.5rem;color:#7fd08f}"
            "section.failed h2 span,section.refused h2 span{color:#e07a6f}"
            ".prompt{color:#9fb4c7;margin:.3rem 0}.why{color:#e07a6f}.clip,.run{color:#7d8a93}"
            ".media{display:flex;gap:.6rem;flex-wrap:wrap}.media video,.media img{max-width:32rem;"
            "width:100%;border-radius:6px;background:#000}.none{color:#7d8a93}a{color:#6fb3e0}"
            "</style><h1>Test scenarios</h1>" + "".join(cards))
    (GALLERY / "index.html").write_text(page, encoding="utf-8")
    return GALLERY / "index.html"


# ---------------------------------------------------------------- Phase 3 D6
#: The matrix: the default run with ONLY the aircraft and the environment
#: changed. The aircraft is the spec's ``aircraft`` value (the config file
#: stem, assets/aircraft_config/<name>.json); the environment is D4's
#: POST /compile ``environment`` field, whose preset maps onto the scene
#: bake named in MATRIX_SCENES (webapp.runs.SCENE_SETTING_BAKES).
MATRIX_AIRCRAFT = ("A4", "J11")
MATRIX_ENVIRONMENTS = ("desert", "forest")
sys.path.insert(0, str(REPO))
from webapp.runs import ENVIRONMENT_PRESETS, SCENE_SETTING_BAKES  # noqa: E402

#: environment -> scene key, read from the web app's own table (never copied).
MATRIX_SCENES = {name: SCENE_SETTING_BAKES[name] for name in MATRIX_ENVIRONMENTS}
#: One neutral prompt for every cell: it names no aircraft, no place, no
#: airspeed and no altitude, so the compiled airspeed keeps source
#: ``default`` and /run re-plans it to the cell aircraft's own cruise
#: default after the aircraft swap.
MATRIX_PROMPT = "chase view"
MATRIX_SUMMARY = REPO / "runs" / "phase3_matrix.json"
#: Card keys that MAY differ between cells (they follow the aircraft or
#: the scene). Dotted names address nested dicts; a bare top-level key
#: allows everything under it. Every other key must be equal: the
#: duration, rate, weather, look (storm, rain gain 4, cinematic), cameras,
#: controls, wind, failures and route are the SAME default run.
MATRIX_CARD_ALLOW = (
    "aircraft", "spec_digest",
    "latitude_deg", "longitude_deg", "terrain_elevation_m", "heading_deg",
    "altitude_m",
    "scene_crs", "datum", "georeference", "orographic", "collision_terrain",
    "landmarks", "google_tiles", "wind_schedule",
    "objects", "taxonomy", "traffic",
    "derived_aircraft", "loading_properties", "engine_mixture",
    "reference_speeds", "airspeed_kt", "atmosphere_properties",
    "run_id", "created",
)
#: The verifier's "could not run" status (core.capture.verify.NOT_RUN is
#: "NOT RUN"); both spellings are read, neither is a pass.
NOT_RUN_STATUSES = ("NOT RUN", "NOT_RUN")


def matrix_cells() -> list:
    """The four cells, aircraft-major: A4/desert, A4/forest, J11/desert,
    J11/forest. Each is ``{"name", "aircraft", "environment"}``."""
    return [{"name": f"{aircraft}/{environment}", "aircraft": aircraft,
             "environment": environment}
            for aircraft in MATRIX_AIRCRAFT
            for environment in MATRIX_ENVIRONMENTS]


def apply_cell(spec_dict: dict, cell: dict) -> None:
    """Set the cell's aircraft on the compiled spec dict as a USER edit
    (the shape apply_lighting writes: value, source, from). Nothing else on
    the spec is touched; the environment is a /compile field, not a spec
    edit."""
    # ScenarioSpec.to_dict nests it: spec["aircraft"]["aircraft"] is the field
    # (packet D6-1: writing one level up left every cell on the B747).
    block = spec_dict.setdefault("aircraft", {})
    entry = block.setdefault("aircraft", {})
    entry.update(value=cell["aircraft"], source="user",
                 **{"from": "scripts/run_test_scenarios.py --matrix"})


def cell_compile_body(cell: dict, compiler: str, still: bool,
                      clip_seconds: float = 3.0) -> dict:
    """The POST /compile body of a cell: the one neutral prompt, the
    compiler, D4's ``environment`` and the still/clip selector. The /run
    body is the one run_spec builds from the returned spec after
    apply_cell."""
    body = {"prompt": MATRIX_PROMPT, "compiler": compiler,
            "environment": cell["environment"]}
    if still:
        body["still"] = True
    else:
        body["clip_seconds"] = clip_seconds
    return body


def card_diff(a: dict, b: dict, prefix: str = "") -> list:
    """The dotted names of every key whose value differs between the two
    cards (recursing into nested dicts; a key present on one side only
    counts), sorted."""
    out = []
    for key in sorted(set(a) | set(b)):
        name = f"{prefix}{key}"
        if key not in a or key not in b:
            out.append(name)
            continue
        left, right = a[key], b[key]
        if isinstance(left, dict) and isinstance(right, dict):
            out.extend(card_diff(left, right, name + "."))
        elif left != right:
            out.append(name)
    return out


def _allowed(name: str) -> bool:
    parts = name.split(".")
    return any(name == allow or parts[0] == allow
               or name.startswith(allow + ".")
               for allow in MATRIX_CARD_ALLOW)


def check_cards(cards: list) -> list:
    """Diff every card against the first; return the differing keys that
    the allow-list does not cover (sorted, unique). Empty means the cells
    differ only where the aircraft or the scene is allowed to show."""
    if len(cards) < 2:
        return []
    bad = set()
    for other in cards[1:]:
        bad.update(k for k in card_diff(cards[0], other) if not _allowed(k))
    return sorted(bad)


def fetch_verify(server, run_id) -> dict:
    """GET /runs/{id}/verify.json; a non-200 answer comes back as a report
    with ``ok`` False and the server's words, so it fails the cell by
    name instead of raising."""
    status, payload = call(server, "GET", f"/runs/{run_id}/verify.json")
    if status != 200 or not isinstance(payload, dict):
        return {"ok": False, "passed": 0, "failed": 0, "not_run": 0,
                "checks": [], "error": f"verify.json: HTTP {status}: {why(payload)}"}
    return payload


def verify_cell(report: dict, run_record: dict, cell: dict):
    """(passed, words). A cell passes only when the verifier says ``ok``
    with ``failed`` 0, its ``component_coverage`` check is PASS (absent or
    NOT RUN is a failure: NOT RUN is never a pass), and the run record's
    scene key is the cell environment's bake."""
    problems = []
    if report.get("error"):
        problems.append(str(report["error"]))
    if report.get("ok") is not True:
        problems.append("verify ok is not true")
    if int(report.get("failed") or 0) != 0:
        problems.append(f"verify failed={report.get('failed')}")
    checks = report.get("checks") or []
    coverage = next((c for c in checks
                     if isinstance(c, dict) and c.get("name") == "component_coverage"), None)
    if coverage is None:
        problems.append("component_coverage: not in the report")
    else:
        status = str(coverage.get("status") or "")
        if status in NOT_RUN_STATUSES:
            problems.append(f"component_coverage NOT RUN: {coverage.get('detail', '')}")
        elif status != "PASS":
            problems.append(f"component_coverage {status}: {coverage.get('detail', '')}")
    wanted = MATRIX_SCENES[cell["environment"]]
    scene = (run_record or {}).get("scene") or {}
    scene_key = scene.get("key") if isinstance(scene, dict) else scene
    if scene_key != wanted:
        problems.append(f"scene {scene_key!r} is not {wanted!r}")
    if problems:
        return False, "; ".join(problems)
    return True, (f"verify PASS component_coverage PASS "
                  f"(passed {report.get('passed')}, not_run {report.get('not_run')}, "
                  f"scene {scene_key})")


def run_matrix(args) -> int:
    """Run the four cells serially (one editor at a time), verify each
    through GET /runs/{id}/verify.json, diff the cards against cell 1 with
    the allow-list, write runs/phase3_matrix.json and return 0 only when
    every cell PASSes and the cards agree."""
    cells = matrix_cells()
    results = []
    cards = []
    for number, cell in enumerate(cells, 1):
        result = {"number": number, "name": cell["name"], "aircraft": cell["aircraft"],
                  "environment": cell["environment"], "prompt": MATRIX_PROMPT,
                  "scene": MATRIX_SCENES[cell["environment"]]}
        print(f"\n[{number}] {cell['name']}\n    {MATRIX_PROMPT}  "
              f"[environment: {cell['environment']} -> {result['scene']}]")
        body = cell_compile_body(cell, args.compiler, args.still, args.clip)
        try:
            status, payload = call(args.server, "POST", "/compile", body)
            if status != 200 or "spec" not in payload:
                outcome = {**result, "outcome": "refused", "why": why(payload)}
            elif not payload["validation"]["ok"]:
                outcome = {**result, "outcome": "refused", "why": why(payload["validation"])}
            else:
                result["compiler"] = payload.get("compiler")
                result["notes"] = payload["spec"].get("notes", [])
                spec_dict = payload["spec"]["dict"]
                apply_cell(spec_dict, cell)
                outcome = run_spec(args.server, result, spec_dict, payload.get("compiler"), args)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            outcome = {**result, "outcome": "failed", "why": f"could not reach the app: {exc}"}
        outcome["verify"] = {"passed": False, "why": f"run {outcome['outcome']}"}
        if outcome["outcome"] == "done" and outcome.get("run_id"):
            run_id = outcome["run_id"]
            report = fetch_verify(args.server, run_id)
            _, record = call(args.server, "GET", f"/runs/{run_id}")
            passed, words = verify_cell(report, record if isinstance(record, dict) else {}, cell)
            outcome["verify"] = {"passed": passed, "why": words,
                                 "ok": report.get("ok"), "passed_count": report.get("passed"),
                                 "failed": report.get("failed"), "not_run": report.get("not_run"),
                                 "component_coverage": next(
                                     (c for c in report.get("checks") or []
                                      if isinstance(c, dict) and c.get("name") == "component_coverage"),
                                     None),
                                 "scene": (record or {}).get("scene") if isinstance(record, dict) else None}
            status, card = call(args.server, "GET", f"/runs/{run_id}/card.json")
            if status == 200 and isinstance(card, dict):
                cards.append(card)
                outcome["card_aircraft"] = card.get("aircraft")
            else:
                outcome["verify"] = {"passed": False,
                                     "why": f"{words}; card.json: HTTP {status}: {why(card)}"}
            print(f"    {outcome['verify']['why'][:300]}")
        results.append(outcome)
        print(f"    -> {outcome['outcome'].upper()}: {str(outcome.get('why', ''))[:200]}")

    card_problems = check_cards(cards) if len(cards) == len(cells) else \
        [f"only {len(cards)} of {len(cells)} cards read"]
    diff_keys = sorted({k for c in cards[1:] for k in card_diff(cards[0], c)}) if cards else []
    all_pass = (len(results) == len(cells)
                and all(r["verify"]["passed"] for r in results)
                and not card_problems)

    print("\n================ matrix ================")
    for r in results:
        print(f"{r['number']:2}. {r['outcome'].upper():8} {r['name']}"
              + (f"  [run {r['run_id']}]" if r.get("run_id") else ""))
        print(f"      {'PASS' if r['verify']['passed'] else 'FAIL'}: {r['verify']['why'][:240]}")
    print(f"card diff against cell 1: {diff_keys or 'none'}")
    if card_problems:
        print(f"FAIL card keys outside the allow-list: {card_problems}")
    summary = {"cells": results, "card_diff": diff_keys,
               "card_outside_allow": card_problems, "ok": all_pass}
    MATRIX_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_SUMMARY.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    index = collect(results)
    print(f"\nwritten: {MATRIX_SUMMARY}\nall results in one folder: {index.parent}")
    print("matrix PASS" if all_pass else "matrix FAIL")
    return 0 if all_pass else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", default="http://127.0.0.1:8008")
    parser.add_argument("--only", type=int, nargs="*", help="scenario numbers (see --list)")
    parser.add_argument("--clip", type=float, default=3.0, help="clip length, seconds (default 3)")
    parser.add_argument("--still", action="store_true", help="one frame per camera instead of a clip")
    parser.add_argument("--compiler", choices=("llm", "regex"), default="llm",
                        help="the AI interpreter (default, as the page) or the offline one")
    parser.add_argument("--poll", type=float, default=5.0, help="seconds between status checks")
    parser.add_argument("--list", action="store_true", help="print the scenarios and stop")
    parser.add_argument("--matrix", action="store_true",
                        help="Phase 3 D6: run {A4,J11} x {desert,forest} from the default run, "
                             "changing only the aircraft and the environment; verify each cell "
                             "and diff the cards (with --list: print the four cells)")
    parser.add_argument("--collect", action="store_true",
                        help="gather the last batch's results (runs/test_scenarios.json) "
                             "into runs/test_scenarios/ and stop")
    args = parser.parse_args()

    if args.collect:
        if not SUMMARY.is_file():
            print(f"no {SUMMARY} yet: run the scenarios first")
            return 2
        index = collect(json.loads(SUMMARY.read_text(encoding="utf-8")))
        print(f"all results in one folder: {index.parent}\nopen: {index}")
        return 0

    if args.matrix and args.list:
        for number, cell in enumerate(matrix_cells(), 1):
            print(f"{number:2}. {cell['name']}\n    {MATRIX_PROMPT}  "
                  f"[aircraft: {cell['aircraft']}, environment: {cell['environment']} "
                  f"-> {MATRIX_SCENES[cell['environment']]}]")
        return 0
    if args.list:
        for number, (name, prompt, edits) in enumerate(SCENARIOS, 1):
            extra = f"   [lighting: {edits}]" if edits else ""
            print(f"{number:2}. {name}\n    {prompt}{extra}")
        return 0
    status, _ = call(args.server, "GET", "/status", timeout=10)
    if status != 200:
        print(f"The app is not answering at {args.server}. Start it first:\n"
              f"  .\\.venv\\Scripts\\python.exe -m uvicorn webapp.server:app --port 8008")
        return 2
    if args.matrix:
        return run_matrix(args)

    wanted = set(args.only or range(1, len(SCENARIOS) + 1))
    results = []
    for number, (name, prompt, edits) in enumerate(SCENARIOS, 1):
        if number not in wanted:
            continue
        print(f"\n[{number}] {name}\n    {prompt}")
        try:
            outcome = run_one(args.server, number, name, prompt, edits, args)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            outcome = {"number": number, "name": name, "prompt": prompt,
                       "outcome": "failed", "why": f"could not reach the app: {exc}"}
        results.append(outcome)
        print(f"    -> {outcome['outcome'].upper()}: {str(outcome.get('why', ''))[:200]}")

    print("\n================ summary ================")
    for r in results:
        print(f"{r['number']:2}. {r['outcome'].upper():8} {r['name']}"
              + (f"  [run {r['run_id']}]" if r.get("run_id") else ""))
        if r.get("clip"):
            print(f"      {r['clip']}")
        if r["outcome"] != "done":
            print(f"      {str(r.get('why', ''))[:240]}")
    index = collect(results)
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten: {SUMMARY}")
    print(f"all results in one folder: {index.parent}\nopen: {index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
