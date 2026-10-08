"""Run the test scenarios through the web app, one after another.

The app must already be running (``python -m uvicorn webapp.server:app
--port 8008``). For each scenario this does what the page does: Interpret
(``/compile``), apply the scenario's lighting edits to the spec, Run
(``/run``; a place with no terrain yet is baked through ``/bake`` and run
again), then waits for the run to finish before the next one starts (the
server runs one at a time). At the end it prints one line per scenario --
done, failed or refused, with the run id and the clip line -- and writes
the same as ``runs/test_scenarios.json``.

    python scripts/run_test_scenarios.py                 # all of them, 3 s clips
    python scripts/run_test_scenarios.py --only 1 4 7    # just these
    python scripts/run_test_scenarios.py --still         # 1 frame each (fast look check)
    python scripts/run_test_scenarios.py --list          # print the scenarios

Open http://127.0.0.1:8008, or each run's frames page, to look at the
results. Only the standard library is used, so the venv's python runs it.
"""

from __future__ import annotations

import argparse
import json
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
    ("hurricane (not supported: refused, or the word silently ignored?)",
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
    run_body = {"spec": spec_dict, "provenance": {"compiler": payload.get("compiler")}}

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
    args = parser.parse_args()

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
    out = Path(__file__).resolve().parents[1] / "runs" / "test_scenarios.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
