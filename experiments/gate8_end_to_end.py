"""Gate 8.3 -- the whole front door, end to end, once.

    Browser prompt -> spec table with provenance -> edit one field -> run
    -> session recorded -> manifest carries prompt, model, compiler, spec
    digest, seed, terrain + sha256, and the honesty labels. One refusal
    case end to end too. (Phase 8 brief, Gate 8.3)

This drives the REAL web app (the FastAPI app object, exactly what the
browser talks to) and the REAL render pipeline -- one full clip render, so
it takes editor minutes. The compiler is the LLM one when a key is present;
otherwise the offline regex compiler runs and the report says so (the flow
under test -- compile, review, edit, validate, run, record -- is identical).

Usage: .venv/bin/python experiments/gate8_end_to_end.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RULE = "=" * 96

#: The brief's own sentence.
PROMPT = "simulate a plane in rough wind conditions over mountains"
#: The refusal case: commanded altitude below the terrain it flies over.
REFUSAL_PROMPT = "fly the 747 at 500 m over 2000 m terrain"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 8.3")
    ap.add_argument("--out", default="runs/gate8_end_to_end")
    ap.add_argument("--timeout", type=float, default=1800.0)
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    from fastapi.testclient import TestClient

    from experiments.fps_probe import editor_already_running
    from webapp.server import app, manager

    if editor_already_running():
        print("REFUSED: another editor process is running (gotcha 9)")
        return 2

    client = TestClient(app)
    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'ok  ' if ok else 'FAIL'}] {name}: {detail}")

    print(f"\n{RULE}\nGate 8.3: prompt -> table -> edit -> run -> recorded\n{RULE}")
    compiler = "llm" if os.environ.get("ANTHROPIC_API_KEY") else "regex"
    print(f'\n1. compile "{PROMPT}" ({compiler})')
    compiled = client.post("/compile", json={"prompt": PROMPT,
                                             "compiler": compiler}).json()
    spec = compiled["spec"]
    check("compiler stated", bool(compiled["compiler"]),
          f"{compiled['compiler']}" + (f" / {compiled['model']}"
                                       if compiled.get("model") else ""))
    sources = {f["name"]: f["source"] for f in spec["fields"]}
    check("provenance on every field",
          all(s in ("user", "inferred", "default") for s in sources.values()),
          f"{sum(1 for s in sources.values() if s != 'default')} non-default")
    if compiler == "llm":
        # Reading "rough wind" is the capability the LLM compiler adds; the
        # regex vocabulary documented-ly cannot parse it, so under the
        # offline fallback this is reported, not graded (Gate 8.1 grades
        # the compiler; this gate grades the FLOW).
        check("rough wind interpreted", sources.get("wind_speed") != "default"
              or sources.get("turbulence") != "default",
              f"wind_speed={sources.get('wind_speed')}, "
              f"turbulence={sources.get('turbulence')}")
    else:
        print(f"  [ -- ] rough wind under the regex fallback: "
              f"wind_speed={sources.get('wind_speed')} (not parsed -- the "
              f"documented vocabulary gap the LLM compiler exists to close)")
    check("mountains interpreted",
          sources.get("terrain_elevation") != "default",
          f"terrain_elevation={sources.get('terrain_elevation')}")
    check("validated before run", compiled["validation"]["ok"] is True,
          str(compiled["validation"]["violations"]) or "valid")

    print("\n2. edit one field (duration -> 20 s), re-validate, run")
    spec_dict = spec["dict"]
    spec_dict["run"]["duration"]["value"] = 20.0
    spec_dict["run"]["duration"]["source"] = "user"
    spec_dict["run"]["duration"]["from"] = "edited in the web UI"
    started = client.post("/run", json={
        "spec": spec_dict,
        "provenance": {"compiler": compiled["compiler"],
                       "model": compiled.get("model")}}).json()
    check("run accepted with edit", "run_id" in started, str(started))
    if "run_id" not in started:
        (out / "report.json").write_text(json.dumps({"checks": checks}, indent=1))
        return 1
    run_id = started["run_id"]

    print(f"\n3. wait for run {run_id} (a real render; minutes)")
    deadline = time.time() + args.timeout
    state = {}
    while time.time() < deadline:
        state = client.get(f"/runs/{run_id}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(10.0)
    check("run completed", state.get("status") == "done",
          f"{state.get('status')}: {state.get('detail')}")

    if state.get("status") == "done":
        run_dir = manager.out_root / run_id
        provenance = json.loads((run_dir / "provenance.json").read_text())
        manifest = json.loads((run_dir / "frames" / "render.json").read_text())
        card = json.loads((run_dir / "card.json").read_text())
        check("provenance carries prompt + compiler",
              provenance.get("prompt") == PROMPT
              and "compiler" in provenance,
              f"compiler={provenance.get('compiler')}")
        check("spec digest content-addresses the run",
              provenance["spec_digest"] == card["spec_digest"]
              == started["digest"],
              card["spec_digest"][:16])
        check("edited duration reached the card",
              abs(float(card["duration_s"]) - 20.0) < 1e-9,
              f"card duration_s={card['duration_s']}")
        terrain = manifest.get("terrain") or {}
        check("manifest carries terrain + sha256",
              bool(terrain.get("sha256")) if provenance["scene"]["terrain"]
              else True,
              f"scene={provenance['scene']['key']}")
        check("clip exists with the panel",
              (run_dir / "clip.mp4").is_file(),
              str(run_dir / "clip.mp4"))
        seed_needed = str(card.get("turbulence", "none")) != "none"
        check("turbulence seed recorded when turbulent",
              (not seed_needed) or "turbulence_properties" in card,
              f"turbulence={card.get('turbulence')}")

    print(f'\n4. the refusal case: "{REFUSAL_PROMPT}"')
    refused = client.post("/compile", json={"prompt": REFUSAL_PROMPT,
                                            "compiler": compiler}).json()
    names = [v["constraint"] for v in refused["validation"]["violations"]]
    check("refused by name in the browser payload",
          refused["validation"]["ok"] is False
          and "altitude.terrain_clearance" in names, str(names))
    run_refused = client.post("/run", json={"spec": refused["spec"]["dict"]})
    check("run endpoint also refuses it",
          run_refused.status_code == 409
          and run_refused.json().get("refused") == "validation",
          f"status {run_refused.status_code}")

    failures = sum(1 for c in checks if not c["ok"])
    report = {"prompt": PROMPT, "compiler": compiled["compiler"],
              "model": compiled.get("model"), "checks": checks,
              "failures": failures}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\n  wrote {out / 'report.json'}")
    print(f"\n  GATE 8.3: {'PASS' if failures == 0 else f'FAIL ({failures})'}"
          + ("" if compiler == "llm" else
         "  (flow exercised with the offline compiler; the LLM leg of the"
         "\n  flow is Gate 8.1's evidence and is BLOCKED without a key)"))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
