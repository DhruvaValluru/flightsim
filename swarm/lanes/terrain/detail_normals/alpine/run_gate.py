"""Render the three stills the alpine detail-normal gate needs and run the
gate. WINDOWS laptop only; from the repository root, with the app stopped:

    .venv\\Scripts\\python.exe swarm\\lanes\\terrain\\detail_normals\\alpine\\run_gate.py

No argument is needed. What it does, in order:

  1. Refuses (exit 3, before any render) unless the engine source reads
     FLIGHTSIM_ALPINE_DETAIL_NORMALS, i.e. unless INTEGRATION.md changes 1 to
     3 are in. Without them the three frames would be the same frame.
  2. Refuses (exit 3) if something already listens on the port: the switch is
     read by the UnrealEditor-Cmd process the web app starts, so it has to be
     in the environment of the app, not of the scenario driver.
  3. Three times (off, off, tier): starts the app with the switch in its
     environment (set through the process API, so no shell quoting or
     trailing space), runs scenario 11 as one still from ONE pinned spec,
     copies that run's own frame (and the first run's depth image) out of
     runs/webapp/<run_id>/frames/<camera>/, stops the app. One render per
     process.
  4. Runs measure_detail_gsd.py on the three frames and returns its exit
     code (0 provisional pass, 1 fail, 2 not applicable).

Outputs: runs/alpine_detail_gate/{baseline,repeat,candidate}.png,
baseline_depth.f32, near_crops.png, gate.json.

UNMEASURED: this script has never run on the laptop. On the Mac only its
refusals, its command lines and its file picking are tested.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]
SWITCH = "FLIGHTSIM_ALPINE_DETAIL_NORMALS"
ENGINE_SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source"
SUMMARY = REPO / "runs" / "test_scenarios.json"       # scripts/run_test_scenarios.py SUMMARY
WEBAPP_RUNS = REPO / "runs" / "webapp"                # scripts/run_test_scenarios.py RUNS
OUT = REPO / "runs" / "alpine_detail_gate"
EXIT_REFUSED = 3


def switch_is_wired(source: Path = ENGINE_SOURCE) -> bool:
    """True when some engine source file names the switch."""
    for path in source.rglob("*"):
        if path.suffix in (".cpp", ".h") and SWITCH in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def variants(tier: int) -> list:
    """(label, switch value) in render order."""
    return [("baseline", "off"), ("repeat", "off"), ("candidate", str(int(tier)))]


def app_env(value: str, base=None) -> dict:
    env = dict(os.environ if base is None else base)
    env[SWITCH] = value
    return env


def app_command(port: int) -> list:
    return [sys.executable, "-m", "uvicorn", "webapp.server:app", "--host", "127.0.0.1", "--port", str(port)]


def driver_command(scenario: int, port: int, spec_dir: Path) -> list:
    return [sys.executable, str(REPO / "scripts" / "run_test_scenarios.py"), "--still",
            "--only", str(scenario), "--server", f"http://127.0.0.1:{port}", "--spec-dir", str(spec_dir)]


def frame_of_run(run_dir: Path) -> Path:
    """The run's beauty frame, picked as scripts/run_test_scenarios.py collect
    picks it: first camera, first frame_*<digit>.png. Refuses by name."""
    cameras = sorted(d for d in (run_dir / "frames").glob("*") if d.is_dir())
    if not cameras:
        raise FileNotFoundError(f"{run_dir}: no camera folder under frames/")
    found = sorted(cameras[0].glob("frame_*[0-9].png"))
    if not found:
        raise FileNotFoundError(f"{cameras[0]}: no frame_*[0-9].png")
    return found[0]


def finished_run(scenario: int, summary: Path = SUMMARY, runs: Path = WEBAPP_RUNS) -> Path:
    rows = json.loads(summary.read_text(encoding="utf-8"))
    row = next((r for r in rows if int(r.get("number", -1)) == scenario), None)
    if row is None or row.get("outcome") != "done" or not row.get("run_id"):
        raise RuntimeError(f"scenario {scenario} did not finish: {row and row.get('outcome')} "
                           f"{row and row.get('why', '')}")
    return runs / str(row["run_id"])


def render(label: str, value: str, args) -> None:
    env = app_env(value)
    print(f"[{label}] {SWITCH}={value!r}: starting the app", flush=True)
    app = subprocess.Popen(app_command(args.port), cwd=REPO, env=env)
    try:
        deadline = time.monotonic() + 180.0
        while not port_open(args.port):
            if app.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("the app did not come up on the port")
            time.sleep(1.0)
        if SUMMARY.is_file():
            SUMMARY.unlink()                  # a stale row must never stand in for this run
        subprocess.run(driver_command(args.scenario, args.port, OUT / "specs"), cwd=REPO, env=env, check=False)
        frame = frame_of_run(finished_run(args.scenario))
        shutil.copy2(frame, OUT / f"{label}.png")
        if label == "baseline":
            depth = frame.with_name(f"{frame.stem}_depth.f32")
            if not depth.is_file():
                raise FileNotFoundError(f"{depth.name} is not beside the frame: the gate takes its "
                                        "regions from depth and cannot run without it")
            shutil.copy2(depth, OUT / "baseline_depth.f32")
    finally:
        app.terminate()
        try:
            app.wait(timeout=60)
        except subprocess.TimeoutExpired:
            app.kill()
        while port_open(args.port):
            time.sleep(1.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render and gate the alpine detail normals (Windows laptop).")
    ap.add_argument("--tier", type=int, default=0, choices=(0, 1, 2, 3))
    ap.add_argument("--scenario", type=int, default=11)
    ap.add_argument("--port", type=int, default=8008)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop; renders nothing")
    args = ap.parse_args(argv)
    if args.dry_run:
        for label, value in variants(args.tier):
            print(f"{label}: {SWITCH}={value}\n  {' '.join(app_command(args.port))}\n  "
                  f"{' '.join(driver_command(args.scenario, args.port, OUT / 'specs'))}")
        return 0
    if not switch_is_wired():
        print(f"terrain.detail_normals: NOT WIRED. No file under {ENGINE_SOURCE} reads {SWITCH}. "
              "Apply INTEGRATION.md changes 1 to 3 first; until then baseline and candidate are the same frame.")
        return EXIT_REFUSED
    if port_open(args.port):
        print(f"terrain.detail_normals: something is already listening on port {args.port}. Stop the app: "
              f"this script starts it itself so that {SWITCH} is in its environment.")
        return EXIT_REFUSED
    OUT.mkdir(parents=True, exist_ok=True)
    for label, value in variants(args.tier):
        render(label, value, args)
    gate_args = ["--baseline", str(OUT / "baseline.png"), "--repeat", str(OUT / "repeat.png"),
                 "--candidate", str(OUT / "candidate.png"), "--depth", str(OUT / "baseline_depth.f32"),
                 "--crops", str(OUT / "near_crops.png")]
    if args.tier:
        tier_json = LANE / "out" / f"alpine_detail_t{args.tier}.json"   # fade distances of that tier
        if not tier_json.is_file():
            print(f"terrain.detail_normals: {tier_json.name} missing. Bake it: "
                  f"bake_alpine_detail_normals.py --tier {args.tier}")
            return EXIT_REFUSED
        gate_args += ["--tier-json", str(tier_json)]
    done = subprocess.run([sys.executable, str(LANE / "measure_detail_gsd.py"), *gate_args],
                          cwd=REPO, capture_output=True, text=True)
    (OUT / "gate.json").write_text(done.stdout, encoding="utf-8")
    print(done.stdout, done.stderr)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
