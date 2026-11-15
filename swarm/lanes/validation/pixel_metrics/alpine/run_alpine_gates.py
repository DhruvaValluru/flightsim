"""One command for every alpine pixel gate. Runs on the WINDOWS laptop, AFTER
the captures exist and with Unreal closed (CPU only, no GPU, one gate at a time).

    python swarm\\lanes\\validation\\pixel_metrics\\alpine\\run_alpine_gates.py ^
        --shot runs\\alpine_gates\\shot.json --out runs\\alpine_gates\\report.json --tier 0

Steps, in order:
  1. selfcheck   recompute the calibration frames' metrics; a mismatch means
                 this machine's numpy/Pillow disagree with the bake and
                 nothing below can be trusted (exit 3).
  2. health      alpine_metrics.compare(candidate, reference), plus the
                 blank-frame / flicker scan when either is a run directory
                 (tiers 2-3 read every frame; tiers 0-1 the first only).
  3. lane gates  each script in alpine_gates.json as its own subprocess,
                 arguments from the shot file.

Statuses: PASS (exit 0), FAIL (exit 1), ERROR (any other exit, timeout),
UNMEASURED (an argument left null, or a file missing), STALE added when the
script's sha256 no longer matches the manifest. A gate script on disk that the
manifest does not list is reported as UNLISTED.

Exit 0 only when health passes and every gate is PASS with nothing
UNMEASURED, ERROR, STALE or UNLISTED. Exit 1 otherwise. Exit 3 on selfcheck.

tiers (all CPU, zero VRAM): 0 = 640 px wide, first frame; 1 = 1280 px, first
frame; 2 = 640 px, whole sequence; 3 = 1280 px, whole sequence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

LANE = Path(__file__).resolve().parent
sys.path.insert(0, str(LANE))
import alpine_metrics as am  # noqa: E402
import build_gate_manifest as bgm  # noqa: E402

REPO = bgm.REPO
TAIL = 1500


def selfcheck(calib: Path = LANE / "calib", tol: float = 1e-5) -> List[str]:
    try:
        expected = json.loads((calib / "expected.json").read_text())
    except OSError as exc:
        return [f"calibration missing: {exc}"]
    problems = []
    for name, exp in sorted(expected.items()):
        try:
            h = am.frame_health(am.load(calib / f"{name}.png"))
        except OSError as exc:
            problems.append(f"{name}: {exc}")
            continue
        for key, want in exp["health"].items():
            if abs(h[key] - want) > tol * max(1.0, abs(want)):
                problems.append(f"{name}.{key}: got {h[key]!r}, baked {want!r}")
        if am.health_failures(h) != exp["failures"]:
            problems.append(f"{name}: failures {am.health_failures(h)} != {exp['failures']}")
    return problems


def run_health(health: Dict[str, object], tier: int) -> Dict[str, object]:
    missing = [k for k in ("reference", "candidate") if not health.get(k)]
    if missing:
        return {"status": "UNMEASURED", "missing": missing}
    width = am.TIER_WIDTH[tier]
    files = {k: am.frame_files(REPO / str(health[k]) if not Path(str(health[k])).is_absolute()
                               else health[k]) for k in ("reference", "candidate")}
    empty = [k for k, v in files.items() if not v]
    if empty:
        return {"status": "UNMEASURED", "missing_files": empty}
    cand = am.load(files["candidate"][0], width)
    ref = am.load(files["reference"][0], width)
    out = am.compare(cand, ref)
    out["tier"] = tier
    out["width_px"] = cand.shape[1]
    if tier >= 2 and len(files["candidate"]) > 1:
        # one frame in memory at a time: the laptop's RAM is the constraint
        seq = am.sequence([am.frame_health(am.load(f, width)) for f in files["candidate"]])
        out["sequence"] = seq
        out["failures"] += seq["failures"]
        out["pass"] = not out["failures"]
    out["status"] = "PASS" if out["pass"] else "FAIL"
    return out


def build_argv(gate: Dict[str, object], shot: Dict[str, object]) -> Dict[str, object]:
    """argv for one gate, or the list of arguments still missing."""
    common = shot.get("common") or {}
    own = (shot.get("lanes") or {}).get(gate["lane"]) or {}
    declared = list(gate["required"]) + list(gate["optional"]) + list(gate["flags"])
    values: Dict[str, object] = {}
    for name in declared:
        if common.get(name) is not None:
            values[name] = common[name]
    for name, value in own.items():        # lane block wins, and may add undeclared args
        if value is not None:
            values[name] = value
        else:
            values.pop(name, None)
    missing = [a for a in gate["required"] if a not in values]
    argv: List[str] = []
    for name, value in values.items():
        if value is True:
            argv.append("--" + name)
        elif value is not False:
            argv += ["--" + name, str(value)]
    return {"argv": argv, "missing": missing}


def last_json(text: str) -> Optional[object]:
    end = text.rfind("}")
    while end != -1:
        depth = 0
        for i in range(end, -1, -1):
            depth += (text[i] == "}") - (text[i] == "{")
            if depth == 0:
                try:
                    return json.loads(text[i:end + 1])
                except ValueError:
                    break
        end = text.rfind("}", 0, end)
    return None


def run_gate(gate: Dict[str, object], shot: Dict[str, object], timeout_s: int,
             runner=subprocess.run) -> Dict[str, object]:
    res: Dict[str, object] = {"lane": gate["lane"], "script": gate["script"]}
    script = REPO / str(gate["script"])
    if not script.is_file():
        res.update(status="UNMEASURED", reason="script missing")
        return res
    res["stale"] = bgm.sha256(script) != gate["sha256"]
    built = build_argv(gate, shot)
    if built["missing"]:
        res.update(status="UNMEASURED", missing=built["missing"])
        return res
    cmd = [sys.executable, str(script)] + built["argv"]
    res["command"] = " ".join(cmd)
    try:
        proc = runner(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        res.update(status="ERROR", reason=f"timeout after {timeout_s} s")
        return res
    res["exit_code"] = proc.returncode
    res["status"] = {0: "PASS", 1: "FAIL"}.get(proc.returncode, "ERROR")
    res["stdout_tail"] = (proc.stdout or "")[-TAIL:]
    if proc.returncode != 0:
        res["stderr_tail"] = (proc.stderr or "")[-TAIL:]
    parsed = last_json(proc.stdout or "")
    if parsed is not None:
        res["metrics"] = parsed
    return res


def summarise(health: Dict[str, object], gates: List[Dict[str, object]],
              unlisted: List[str]) -> Dict[str, object]:
    counts = {s: 0 for s in ("PASS", "FAIL", "ERROR", "UNMEASURED")}
    for g in gates:
        counts[g["status"]] += 1
    stale = [g["lane"] for g in gates if g.get("stale")]
    ok = (health.get("status") == "PASS" and counts["PASS"] == len(gates)
          and not stale and not unlisted)
    return {"gates_total": len(gates), "gates_passed": counts["PASS"],
            "gates_failed": counts["FAIL"], "gates_error": counts["ERROR"],
            "gates_unmeasured": counts["UNMEASURED"], "stale": stale, "unlisted": unlisted,
            "health_status": health.get("status"),
            "health_penalty_delta": health.get("penalty_delta"), "all_pass": ok}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shot", type=Path, required=True, help="filled copy of shot.template.json")
    ap.add_argument("--out", type=Path, help="write the full report here")
    ap.add_argument("--manifest", type=Path, default=LANE / "alpine_gates.json")
    ap.add_argument("--tier", type=int, default=0, choices=sorted(am.TIER_WIDTH))
    ap.add_argument("--only", action="append", default=[], help="lane id; repeatable")
    ap.add_argument("--timeout-s", type=int, default=600)
    args = ap.parse_args(argv)

    problems = selfcheck()
    if problems:
        print(json.dumps({"selfcheck": "FAIL", "problems": problems}, indent=1))
        return 3
    shot = json.loads(args.shot.read_text())
    manifest = json.loads(args.manifest.read_text())
    gates = [g for g in manifest["gates"] if not args.only or g["lane"] in args.only]
    listed = {g["script"] for g in manifest["gates"]}
    unlisted = [] if args.only else sorted(g["script"] for g in bgm.scan() if g["script"] not in listed)

    health = run_health(shot.get("health") or {}, args.tier)
    results = [run_gate(g, shot, args.timeout_s) for g in gates]
    summary = summarise(health, results, unlisted)
    report = {"lane": bgm.SELF_ID, "label": "visual-only", "selfcheck": "PASS",
              "summary": summary, "health": health, "gates": results}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + "\n")
    for g in results:
        print(f"{g['status']:<10} {g['lane']}" + (f"  missing: {g['missing']}" if g.get("missing") else ""))
    print(json.dumps(summary, indent=1))
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
