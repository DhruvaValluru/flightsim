"""Climb the alpine stress ladder on the Windows laptop. UNMEASURED until run there.

    python swarm\\lanes\\hardware_perf\\stress_ladder\\alpine\\run_ladder.py

Needs the web app serving on 127.0.0.1:8008 with the INTEGRATION.md hook in
place (the renderer reads runs\\stress_ladder\\active_tier.json). For each
tier, three times: write the active tier, start the Windows ``typeperf``
samplers, render scenario 11 as a 3 s clip, judge the run. It stops at the
first failing run and never climbs past it, then writes
``measured\\hardware_budget_measured.json``. Exit code 0 only when tier 0 held.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[3]
sys.path.insert(0, str(LANE))
import measure_ladder  # noqa: E402

COUNTERS = [r"\GPU Adapter Memory(*)\Shared Usage",
            r"\GPU Adapter Memory(*)\Dedicated Usage",
            r"\Memory\Available MBytes",
            r"\Processor Information(_Total)\% Processor Performance"]
#: its own process: a laptop without the counter must not stop the others
THERMAL = [r"\Thermal Zone Information(*)\Temperature"]


def start_sampler(counters: list, out: Path):
    handle = out.open("w", encoding="utf-8")
    return subprocess.Popen(["typeperf", *counters, "-si", "1"],
                            stdout=handle, stderr=subprocess.DEVNULL), handle


def stop_sampler(pair) -> None:
    proc, handle = pair
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    handle.close()


def newest_run(runs: Path, since: float):
    found = [d for d in runs.iterdir()
             if d.is_dir() and (d / "frames").is_dir() and d.stat().st_mtime >= since]
    return max(found, key=lambda d: d.stat().st_mtime) if found else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-tier", type=int, default=3)
    ap.add_argument("--work", type=Path, default=REPO / "runs" / "stress_ladder")
    a = ap.parse_args(argv)

    ladder = json.loads((LANE / "alpine_ladder.json").read_text())
    proto = ladder["protocol"]
    a.work.mkdir(parents=True, exist_ok=True)
    active = a.work / "active_tier.json"
    results, failed = [], False
    try:
        for tier in ladder["tiers"]:
            if tier["tier"] > a.max_tier or failed:
                break
            for run in range(proto["runs_per_tier"]):
                tag = f"tier{tier['tier']}_run{run}"
                active.write_text(json.dumps(tier, indent=1))
                since = time.time()
                main_csv, thermal_csv = a.work / f"{tag}_sampler.csv", a.work / f"{tag}_thermal.csv"
                samplers = [start_sampler(COUNTERS, main_csv), start_sampler(THERMAL, thermal_csv)]
                try:
                    subprocess.run([sys.executable, str(REPO / "scripts" / "run_test_scenarios.py"),
                                    "--clip", "3", "--only", str(ladder["scenario"]["test_scenario"])],
                                   cwd=REPO, check=False)
                finally:
                    for s in samplers:
                        stop_sampler(s)
                run_dir = newest_run(REPO / "runs", since)
                if run_dir is None:
                    verdict = {"pass": False, "reasons": ["no_run_directory"],
                               "metrics": {"tier": tier["tier"], "device_lost": 0}}
                else:
                    verdict = measure_ladder.judge_run(run_dir, tier["tier"], proto["thresholds"],
                                                       main_csv, thermal_csv)
                results.append(verdict)
                print(f"{tag}: {'PASS' if verdict['pass'] else 'FAIL ' + ','.join(verdict['reasons'])}")
                if not verdict["pass"]:
                    failed = True
                    break
                time.sleep(proto["cooldown_seconds"])
    finally:
        active.unlink(missing_ok=True)   # later renders go back to the default
        (a.work / "results.json").write_text(json.dumps(results, indent=1))
    return measure_ladder.main(["--results", str(a.work / "results.json")])


if __name__ == "__main__":
    raise SystemExit(main())
