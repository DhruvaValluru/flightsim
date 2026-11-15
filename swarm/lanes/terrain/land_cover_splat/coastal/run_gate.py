"""The coastal land-cover splat gate, one command, for the Windows laptop.

    .venv\\Scripts\\python.exe swarm\\lanes\\terrain\\land_cover_splat\\coastal\\run_gate.py --tier 0

NEVER EXECUTED on Windows: written on the Mac, where only its refusals and
its bookkeeping are tested against made-up run directories.

What it does, in order, and where it refuses by name instead of passing:

1. ``not_integrated``  The switch must exist in the tree: ``core/scenario/card.py``
   must read ``FLIGHTSIM_LAND_COVER_SPLAT`` and a FlightSimBridge source file
   must name ``LandCoverSplat`` (INTEGRATION.md changes 1 and 3). Without them
   both renders are the same scene, so nothing is rendered at all.
2. ``no_coastal_scenario``  Exactly one entry of scripts/run_test_scenarios.py
   ``SCENARIOS`` must have ``--scenario`` (default "coastal") in its name.
   There is none in the tree today (INTEGRATION.md change 5).
3. ``app_already_running``  The web app must not be answering on the port:
   the gate starts its own, once per side, with the switch in that server's
   environment (the switch is read by the app, not by the scenario runner).
4. Renders the scenario as one still with the switch ``off``, then with
   ``--tier``, through the runner's own ``run_batch`` with the compiled spec
   pinned (``--compiler regex``, a private ``--spec-dir``), so both sides are
   the same shot. The runner's own summary and gallery are not touched.
5. Hands the two run directories to ``measure_ground.py``, which reads the
   camera from each run's capture_manifest.json and refuses unless the
   engine's render.json says the splat was drawn in the candidate only.

Exit: 0 pass, 1 fail (including a candidate render that failed, e.g. device
lost), 2 could not measure, 3 refused here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]
SWITCH = "FLIGHTSIM_LAND_COVER_SPLAT"
NAME = "terrain.land_cover_splat.gate"

#: (file or directory under the repo, text it must contain, what merges it).
MARKERS: Tuple[Tuple[str, str, str], ...] = (
    ("core/scenario/card.py", SWITCH, "INTEGRATION.md change 1"),
    ("ue/Plugins/FlightSimBridge/Source", "LandCoverSplat", "INTEGRATION.md change 3"),
)


class Refused(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(f"REFUSED {NAME}.{code}: {reason}")
        self.code = code


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def missing_markers(repo: Path = REPO) -> List[str]:
    """The integration changes the tree does not carry yet."""
    missing = []
    for where, text, change in MARKERS:
        target = repo / where
        files = [target] if target.is_file() else \
            sorted(p for p in target.rglob("*") if p.suffix in (".cpp", ".h", ".py")) if target.is_dir() else []
        if not any(text in f.read_text(encoding="utf-8", errors="replace") for f in files):
            missing.append(f"{where} does not mention {text} ({change})")
    return missing


def find_scenario(scenarios: Sequence[Sequence[Any]], needle: str) -> int:
    """The 1-based number (as ``--list`` and ``--only`` count) of the one
    scenario whose name contains ``needle``."""
    hits = [n for n, row in enumerate(scenarios, 1) if needle.lower() in str(row[0]).lower()]
    if len(hits) != 1:
        raise Refused("no_coastal_scenario",
                      f"{len(hits)} entries of scripts/run_test_scenarios.py SCENARIOS have {needle!r} in "
                      "their name; the gate needs exactly one (INTEGRATION.md change 5)")
    return hits[0]


def answering(server: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(server + "/", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def render_side(runner, number: int, value: str, args, gate_dir: Path,
                start: Optional[Callable[[Dict[str, str]], Any]] = None) -> Dict[str, Any]:
    """Start the app with the switch at ``value``, render the scenario as one
    still, stop the app, and return the runner's result row."""
    if answering(args.server):
        raise Refused("app_already_running",
                      f"something answers at {args.server}; stop the web app, the gate starts its own "
                      f"with {SWITCH} set")
    env = dict(os.environ, **{SWITCH: value})
    port = args.server.rsplit(":", 1)[-1]
    log = (gate_dir / f"app_{value}.log").open("w", encoding="utf-8")
    start = start or (lambda e: subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "webapp.server:app", "--port", port],
        cwd=str(REPO), env=e, stdout=log, stderr=subprocess.STDOUT))
    process = start(env)
    try:
        deadline = time.monotonic() + args.app_wait
        while not answering(args.server):
            if process.poll() is not None or time.monotonic() > deadline:
                raise Refused("app_did_not_start", f"the web app did not answer at {args.server}; see {log.name}")
            time.sleep(1.0)
        summary = gate_dir / f"summary_{value}.json"
        batch = argparse.Namespace(
            server=args.server, still=True, clip=3.0, compiler="regex", poll=5.0, resume=False,
            recompile=False, spec_dir=str(gate_dir / "specs"), min_free_mb=args.min_free_mb,
            memory_wait=600.0)
        code = runner.run_batch(batch, {number}, summary=summary,
                                gather=lambda results: gate_dir / "index.html")
        rows = json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else []
        row = next((r for r in rows if int(r.get("number", -1)) == number), None)
        if row is None:
            raise Refused("no_result", f"the runner (exit {code}) wrote no row for scenario {number}")
        return row
    finally:
        process.terminate()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()


def main(argv: Optional[Sequence[str]] = None, runner=None, measure=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tier", type=int, default=0, choices=(0, 1, 2, 3))
    parser.add_argument("--scenario", default="coastal", help="text the scenario's name must contain")
    parser.add_argument("--server", default="http://127.0.0.1:8008")
    parser.add_argument("--surface-elevation-m", type=float, default=0.0)
    parser.add_argument("--app-wait", type=float, default=180.0, help="seconds to wait for the app to answer")
    parser.add_argument("--min-free-mb", type=float, default=4096.0)
    parser.add_argument("--check", action="store_true",
                        help="only say whether the gate could run (steps 1-3); render nothing")
    args = parser.parse_args(argv)
    try:
        missing = missing_markers()
        if missing:
            raise Refused("not_integrated", "; ".join(missing) + ". Both renders would be the same scene")
        runner = runner or _load(REPO / "scripts" / "run_test_scenarios.py", "run_test_scenarios")
        number = find_scenario(runner.SCENARIOS, args.scenario)
        if args.check:
            if answering(args.server):
                raise Refused("app_already_running", f"something answers at {args.server}; stop the web app")
            print(f"{NAME}: could run (scenario {number}: {runner.SCENARIOS[number - 1][0]}); nothing rendered")
            return 0
        gate_dir = REPO / "runs" / "coastal_splat_gate" / f"tier{args.tier}"
        gate_dir.mkdir(parents=True, exist_ok=True)
        rows = {}
        for side, value in (("baseline", "off"), ("candidate", str(args.tier))):
            row = render_side(runner, number, value, args, gate_dir)
            rows[side] = row
            if row.get("outcome") != "done" or not row.get("run_id"):
                reason = f"{side} render ({SWITCH}={value}) ended {row.get('outcome')}: {row.get('why', '')}"
                if side == "baseline":
                    raise Refused("baseline_render_failed", reason)
                print(f"FAIL {NAME}: {reason}", file=sys.stderr)
                return 1
        measure = measure or _load(LANE / "measure_ground.py", "coastal_splat_measure_ground")
        return measure.main([
            "--baseline-run", str(runner.RUNS / str(rows["baseline"]["run_id"])),
            "--candidate-run", str(runner.RUNS / str(rows["candidate"]["run_id"])),
            "--surface-elevation-m", str(args.surface_elevation_m)])
    except Refused as refusal:
        print(refusal, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
