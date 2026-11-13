"""Judge the stress ladder's rounds and write the measured hardware budget.

scripts/stress_ladder.ps1 runs the renders (each one a visual_fix_round.ps1
round with the tier's -Switches) and calls this twice:

    python scripts/stress_ladder.py judge --tier 0 --run 1 --round-dir <ladder>\\round_9001 \\
        --sampler <ladder>\\tier0_run1_typeperf.csv --exit-code 0 --out <ladder>\\tier0_run1.json
    python scripts/stress_ladder.py summarise --dir <ladder> --runs-per-tier 3

Ported from the max-push lane hardware_perf.stress_ladder.alpine
(measure_ladder.py), rewired to what the round machinery actually leaves on
disk: ROUND.json and summary.json in the round folder, the run's render.log
under runs/webapp/<run_id>/, and a typeperf CSV. stdlib only, so the tests
drive it on synthetic files; that is a check of the parsing, never a
measurement.

A run SURVIVES its tier when: the round script exited 0; the scene's
outcome is ``done``; the logs carry no device-lost line (DXGI_ERROR_DEVICE_HUNG
/ REMOVED / RESET, DRIVER_INTERNAL_ERROR, render.gpu_lost, "device being
lost", a GPU crash), no capture-watchdog line (render.capture_timeout: the
commandlet's exit 4), no stall / timeout kill and no out-of-memory line; and
the tier's ``-FlightSimStressTier=N`` marker is in the logs (the engine echoes
its command line, so a missing marker means the switches never reached it).
Frame time, GPU memory and free RAM are REPORTED, not judged: no threshold
for them has been calibrated on the laptop.

Frame time: a still has one frame, so the numbers are the commandlet's own
``gpu drain: <stage> finished on the GPU in X s`` lines (GPU time per capture
stage, on D3D11 with -gpu-drain on) and the scene's wall seconds from
ROUND.json. GPU memory: typeperf ``\\GPU Adapter Memory(*)\\Dedicated Usage``
and ``Shared Usage`` (adapter-wide, every process, so the desktop is in it).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]

DEVICE_LOST = re.compile(
    r"DXGI_ERROR_DEVICE_(?:REMOVED|HUNG|RESET)|DXGI_ERROR_DRIVER_INTERNAL_ERROR"
    r"|render\.gpu_lost|device being lost|D3D11 device REMOVED|GPU ?crash", re.I)
#: the capture watchdog's line; the commandlet then ends with exit code 4
WATCHDOG = re.compile(r"render\.capture_timeout")
STALLED = re.compile(r"render\.stalled|render\.timeout")
OUT_OF_MEMORY = re.compile(r"Out of video memory|E_OUTOFMEMORY|Ran out of memory|OutOfMemory", re.I)
TIER_MARKER = re.compile(r"-FlightSimStressTier=(\d+)")
GPU_DRAIN = re.compile(r"gpu drain: (.+?) finished on the GPU in ([0-9.]+) s")
MB = 1024.0 * 1024.0


def scan_logs(texts: List[str]) -> Dict[str, object]:
    lines = [ln for t in texts for ln in t.splitlines()]
    markers = sorted({int(m.group(1)) for ln in lines for m in TIER_MARKER.finditer(ln)})
    drains = [float(m.group(2)) for ln in lines for m in [GPU_DRAIN.search(ln)] if m]
    first = lambda rx: next((ln.strip()[:300] for ln in lines if rx.search(ln)), None)  # noqa: E731
    return {
        "device_lost_lines": sum(1 for ln in lines if DEVICE_LOST.search(ln)),
        "watchdog_lines": sum(1 for ln in lines if WATCHDOG.search(ln)),
        "stalled_lines": sum(1 for ln in lines if STALLED.search(ln)),
        "out_of_memory_lines": sum(1 for ln in lines if OUT_OF_MEMORY.search(ln)),
        "first_device_lost": first(DEVICE_LOST),
        "first_watchdog": first(WATCHDOG),
        "tier_markers": markers,
        "gpu_drains": len(drains),
        "gpu_drain_s_max": round(max(drains), 3) if drains else None,
        "gpu_drain_s_median": round(statistics.median(drains), 3) if drains else None,
    }


def _read_text(path: Path) -> str:
    data = Path(path).read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def parse_typeperf(path: Optional[Path]) -> Dict[str, List[float]]:
    """typeperf CSV -> {counter name (lower case): [per-row sum over instances]}.
    A blank or unparseable cell is a missed sample and is skipped; a missing
    or empty file (the counter does not exist here) gives nothing."""
    series: Dict[str, List[float]] = {}
    if path is None or not Path(path).is_file():
        return series
    rows = [r for r in csv.reader(io.StringIO(_read_text(path))) if r]
    if len(rows) < 2:
        return series
    names = [h.rsplit("\\", 1)[-1].strip().lower() for h in rows[0][1:]]
    for row in rows[1:]:
        sums: Dict[str, float] = {}
        for name, cell in zip(names, row[1:]):
            try:
                sums[name] = sums.get(name, 0.0) + float(cell)
            except ValueError:
                continue
        for name, value in sums.items():
            series.setdefault(name, []).append(value)
    return series


def sampler_metrics(paths) -> Dict[str, object]:
    """One CSV or several (stress_ladder.ps1 runs one typeperf per counter)."""
    if paths is None or isinstance(paths, (str, Path)):
        paths = [paths] if paths is not None else []
    s: Dict[str, List[float]] = {}
    for path in paths:
        for name, values in parse_typeperf(path).items():
            s.setdefault(name, []).extend(values)
    ded, shr = s.get("dedicated usage", []), s.get("shared usage", [])
    total = [a + b for a, b in zip(ded, shr)]
    ram = s.get("available mbytes", [])
    util = s.get("utilization percentage", [])
    return {
        "samples": max((len(v) for v in s.values()), default=0),
        "gpu_memory_mb_peak": round(max(total) / MB, 1) if total else None,
        "gpu_dedicated_mb_peak": round(max(ded) / MB, 1) if ded else None,
        "gpu_shared_mb_peak": round(max(shr) / MB, 1) if shr else None,
        "available_ram_mb_min": round(min(ram), 1) if ram else None,
        "gpu_3d_utilization_max": round(min(100.0, max(util)), 1) if util else None,
    }


def _load_json(path: Path, default):
    try:
        return json.loads(_read_text(path))
    except (OSError, ValueError):
        return default


def judge(tier: int, run: int, round_dir: Path, run_root: Path, sampler,
          exit_code: int, extra_logs: List[Path] = ()) -> Dict[str, object]:
    """One ladder run -> {"survived", "reasons", "metrics", ...}. Every reason is named."""
    round_dir = Path(round_dir)
    record = _load_json(round_dir / "ROUND.json", {})
    rows = _load_json(round_dir / "summary.json", [])
    reasons: List[str] = []
    if exit_code != 0:
        reasons.append(f"round_exit:{exit_code}" + (" (refused by name)" if exit_code == 3 else ""))
    if not record:
        reasons.append("no_round_json")
    outcomes = record.get("outcomes") or []
    if isinstance(outcomes, dict):        # ConvertTo-Json writes a one-item array as an object
        outcomes = [outcomes]
    if not outcomes or any(o.get("outcome") != "done" for o in outcomes):
        reasons.append("scene_outcome:" + ",".join(str(o.get("outcome")) for o in outcomes) if outcomes
                       else "scene_outcome:none")
    texts, log_files = [], []
    for row in rows if isinstance(rows, list) else []:
        if row.get("why"):
            texts.append(str(row["why"]))
        if row.get("run_id"):
            run_dir = Path(run_root) / str(row["run_id"])
            log_files += sorted(run_dir.rglob("*.log")) if run_dir.is_dir() else []
    log_files += [Path(p) for p in extra_logs if Path(p).is_file()]
    texts += [_read_text(p) for p in log_files]
    log = scan_logs(texts)
    if not log_files:
        reasons.append("no_render_log")
    if log["device_lost_lines"]:
        reasons.append(f"device_lost:{log['device_lost_lines']}")
    if log["watchdog_lines"]:
        reasons.append("capture_watchdog:exit_4")
    if log["stalled_lines"]:
        reasons.append("render_stalled")
    if log["out_of_memory_lines"]:
        reasons.append(f"out_of_memory:{log['out_of_memory_lines']}")
    if log_files and tier not in log["tier_markers"]:
        reasons.append(f"tier_not_applied:logs_have_{log['tier_markers'] or 'none'}")
    metrics = {**log, **sampler_metrics(sampler),
               "scene_seconds": max((o.get("seconds") or 0 for o in outcomes), default=None),
               "round_seconds": record.get("seconds"),
               "logs": [str(p) for p in log_files]}
    return {"tier": tier, "run": run, "survived": not reasons, "reasons": reasons,
            "switches": record.get("switches"), "commit": record.get("commit"),
            "round": record.get("round"), "metrics": metrics}


def summarise(verdicts: List[dict], runs_per_tier: int, gpu: Optional[str] = None) -> Dict[str, object]:
    """Verdicts -> the measured budget. A tier is sustained when it has
    ``runs_per_tier`` verdicts and all survived; the sustained tier is the
    highest with every tier below it sustained. ``measured`` is true only
    when tier 0 is sustained."""
    by_tier: Dict[int, List[dict]] = {}
    for v in verdicts:
        by_tier.setdefault(int(v["tier"]), []).append(v)
    sustained = None
    for tier in sorted(by_tier):
        runs = by_tier[tier]
        if tier == (0 if sustained is None else sustained + 1) and len(runs) >= runs_per_tier \
                and all(r["survived"] for r in runs):
            sustained = tier
        else:
            break
    out: Dict[str, object] = {
        "label": "measured on the render laptop by scripts/stress_ladder.ps1; survival only, "
                 "frame time and memory are reported, not judged (uncalibrated)",
        "measured": sustained is not None, "sustained_tier": sustained, "gpu": gpu,
        "runs_per_tier": runs_per_tier,
        "written": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "device_lost_total": sum(v["metrics"].get("device_lost_lines", 0) for v in verdicts),
        "runs": [{k: v.get(k) for k in ("tier", "run", "survived", "reasons", "round")} for v in verdicts],
    }
    if sustained is None:
        out["refused"] = "stress_ladder.tier0_not_sustained"
        return out
    held = by_tier[sustained]

    def peak(key, fn=max):
        vals = [r["metrics"].get(key) for r in held if r["metrics"].get(key) is not None]
        return fn(vals) if vals else None

    out.update(switches=held[0].get("switches"), commit=held[0].get("commit"),
               gpu_memory_mb_peak=peak("gpu_memory_mb_peak"),
               gpu_dedicated_mb_peak=peak("gpu_dedicated_mb_peak"),
               gpu_shared_mb_peak=peak("gpu_shared_mb_peak"),
               available_ram_mb_min=peak("available_ram_mb_min", min),
               gpu_drain_s_max=peak("gpu_drain_s_max"),
               scene_seconds_max=peak("scene_seconds"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--tier", type=int, required=True)
    j.add_argument("--run", type=int, required=True)
    j.add_argument("--round-dir", type=Path, required=True)
    j.add_argument("--run-root", type=Path, default=REPO / "runs" / "webapp")
    j.add_argument("--sampler", type=Path, action="append", default=[],
                   help="a typeperf CSV (repeatable)")
    j.add_argument("--exit-code", type=int, required=True)
    j.add_argument("--log", type=Path, action="append", default=[], help="another log to scan")
    j.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("summarise")
    s.add_argument("--dir", type=Path, required=True, help="the ladder folder (tier*_run*.json)")
    s.add_argument("--runs-per-tier", type=int, default=3)
    s.add_argument("--profile", type=Path, default=REPO / "docs" / "hardware" / "hardware_profile.json")
    s.add_argument("--out", type=Path, default=REPO / "docs" / "hardware" / "hardware_budget_measured.json")
    a = ap.parse_args(argv)

    if a.cmd == "judge":
        v = judge(a.tier, a.run, a.round_dir, a.run_root, a.sampler, a.exit_code, a.log)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(v, indent=1) + "\n", encoding="utf-8")
        print(f"tier {a.tier} run {a.run}: " + ("SURVIVED" if v["survived"] else "FAILED " + ", ".join(v["reasons"])))
        return 0 if v["survived"] else 1

    verdicts = [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(a.dir.glob("tier*_run*.json"))]
    gpu = None
    if a.profile and a.profile.is_file():
        try:
            sys.path.insert(0, str(REPO))
            from core.render.hardware_budget import budget_from_file
            gpu = budget_from_file(a.profile, measured_path=None).get("gpu")
        except Exception:   # an incomplete profile: the GPU stays unnamed
            gpu = None
    summary = summarise(verdicts, a.runs_per_tier, gpu)
    text = json.dumps(summary, indent=1, sort_keys=True) + "\n"
    (a.dir / "budget.json").write_text(text, encoding="utf-8")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print(f"sustained_tier={summary['sustained_tier']} measured={summary['measured']} "
          f"device_lost_total={summary['device_lost_total']} -> {a.out}")
    return 0 if summary["measured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
