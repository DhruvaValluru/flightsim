"""Gate 8.2's replay clause: the interactive session's card, re-flown.

The interactive window is a viewport; claims come from the replay. Every
session records its card and telemetry exactly like the commandlets do, so
the headless host can re-fly the same card deterministically and the two
trajectories can be compared under Gate 5's own discipline -- the same
channels, the same tolerances, comparison on the recorded clock, the trim
snapshot exempt, heading on the circle. Nothing about that discipline is
re-derived here: the comparison function IS gate5_ue_parity.compare.

Three sessions:

* still air      -- must match within Gate 5 tolerances.
* steady wind    -- must match within Gate 5 tolerances (wind reaches both
                    hosts; ground track closes the loop).
* turbulent      -- compared only to confirm it DIVERGES, exactly as the
                    permanent visual-only verdict predicts. A turbulent
                    session that matched would contradict the measured
                    per-host RNG offset and would itself be suspicious.

Substep accounting rides along: each session's manifest must show
substeps == round(sim_seconds * 120) with the deficit explained by counted
catch-up caps.

Usage: .venv/bin/python experiments/interactive_replay.py [--skip-runs]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scenario.runner import run_spec  # noqa: E402
from experiments.fps_probe import (  # noqa: E402
    EDITOR_OFFSCREEN,
    PROJECT,
    editor_already_running,
)
from experiments.gate5_ue_parity import (  # noqa: E402
    TOLERANCE,
    compare,
    reference_spec,
    write_run_card,
)

RULE = "=" * 96

#: Session length. Long enough for dynamics to express, short enough that
#: three sessions plus replays stay inside a coffee break.
DURATION_S = 30.0

SESSIONS = (
    {"key": "still_air",
     "prompt": "fly the 747 at 3000 m and 250 kt for 30 seconds",
     "wind": None, "turbulence": None, "expect": "match"},
    {"key": "steady_wind",
     "prompt": "fly the 747 at 3000 m and 250 kt for 30 seconds",
     "wind": (25.0, 90.0), "turbulence": None, "expect": "match"},
    {"key": "turbulent",
     "prompt": "fly the 747 at 3000 m and 250 kt for 30 seconds",
     "wind": None, "turbulence": ("moderate", 424242), "expect": "diverge"},
)


def fly_interactive(card: Path, telemetry: Path, manifest: Path,
                    log: Path, timeout_s: float) -> None:
    """The locked-session path: the commandlet's wall-clock probe loop.

    -game mode never starts under a locked console session (gotcha 18), so
    the session is flown by the render commandlet's probe loop -- the SAME
    Scenario.Step stepping paced by the same wall-clock substep accumulator
    the interactive window uses, with the same recorder. What is absent is
    only the window itself; when a user session is unlocked, the windowed
    host produces the same artifacts via -telemetry=/-manifest= and this
    experiment re-runs against them unchanged.
    """
    telemetry.unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    scratch = telemetry.parent / (telemetry.stem + "_frames")
    scratch.mkdir(exist_ok=True)
    command = [
        str(EDITOR_OFFSCREEN), str(PROJECT),
        "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={scratch}",
        "-width=640", "-height=360",   # replay grades physics, not pixels
        f"-probe-wall-seconds={timeout_s:.0f}",
        f"-probe-telemetry={telemetry}", f"-probe-manifest={manifest}",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]
    with log.open("w") as sink:
        proc = subprocess.Popen(command, stdout=sink,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
        deadline = time.time() + timeout_s
        while proc.poll() is None and time.time() < deadline:
            time.sleep(2.0)
        if proc.poll() is None:
            proc.terminate()
            raise RuntimeError(f"interactive session timed out; see {log}")
    if not telemetry.is_file() or not manifest.is_file():
        raise RuntimeError(
            f"interactive session wrote no telemetry/manifest; see {log}")


def substep_ledger_ok(manifest: Dict) -> bool:
    expected = round(float(manifest["sim_seconds"])
                     * float(manifest["substep_rate_hz"]))
    return int(manifest["substeps"]) == expected


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="interactive replay parity (8C.3)")
    ap.add_argument("--out", default="runs/interactive_replay")
    ap.add_argument("--timeout", type=float, default=1200.0)
    ap.add_argument("--skip-runs", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n{RULE}\ninteractive replay parity: the window is a viewport, "
          f"claims come from the replay\n{RULE}")
    if not args.skip_runs and editor_already_running():
        print("  REFUSED: another editor process is running (gotcha 9)")
        return 2

    failures = 0
    rows = []
    for session in SESSIONS:
        key = session["key"]
        print(f"\n  [{key}] expect: {session['expect']}")
        spec = reference_spec(session["prompt"])
        if session["wind"]:
            speed, offset = session["wind"]
            spec.set("wind_speed", speed, frm="replay experiment")
            spec.set("wind_direction",
                     (float(spec.heading.value) + offset) % 360.0,
                     frm="crosswind = heading + 90")
        if session["turbulence"]:
            word, seed = session["turbulence"]
            spec.set("turbulence", word, frm="replay experiment")
            spec.set("seed", seed, frm="replay experiment")
        card = write_run_card(spec, out / f"{key}_card.json",
                              duration_s=DURATION_S)

        telemetry = out / f"{key}_interactive.json"
        manifest_path = out / f"{key}_manifest.json"
        if not args.skip_runs:
            print("    flying the interactive host (offscreen)...")
            fly_interactive(card, telemetry, manifest_path,
                            out / f"{key}.log", args.timeout)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ledger = substep_ledger_ok(manifest)
        print(f"    substeps {manifest['substeps']} over "
              f"{manifest['sim_seconds']:.2f} s sim "
              f"[{'ok' if ledger else 'LEDGER INCONSISTENT'}], "
              f"behind {manifest['deficit_seconds']:.3f} s "
              f"({manifest['deficit_events']} caps)")
        if not ledger:
            failures += 1

        # The replay: the SAME card's spec re-flown headless. The spec is
        # the reproducible unit; duration matches the interactive session.
        print("    re-flying headless...")
        spec.set("duration", DURATION_S, frm="replay comparison window")
        headless = run_spec(spec)
        headless_path = out / f"{key}_headless.json"
        headless.telemetry.write_json(headless_path)

        results, overlap = compare(headless_path, telemetry)
        worst = {r.channel: r.max_difference for r in results}
        matched = overlap.ok and all(r.ok for r in results)
        print(f"    overlap {overlap.fraction * 100:.1f}%  worst channels: "
              + ", ".join(f"{r.channel} {r.max_difference:.3g}"
                          for r in sorted(results,
                                          key=lambda x: -x.max_difference
                                          / x.tolerance)[:3]))
        if session["expect"] == "match":
            print(f"    parity: {'PASS' if matched else 'FAIL'} "
                  f"(Gate 5 channels and tolerances)")
            if not matched:
                failures += 1
        else:
            # Divergence is the PREDICTION for a turbulent session; agreeing
            # would contradict the measured per-host RNG offset.
            diverged = not matched
            print(f"    diverges as the visual-only verdict predicts: "
                  f"{'yes' if diverged else 'NO -- SUSPICIOUS AGREEMENT'}")
            if not diverged:
                failures += 1
        rows.append({"session": key, "expect": session["expect"],
                     "matched": matched, "ledger_ok": ledger,
                     "overlap": overlap.fraction, "worst": worst,
                     "manifest": manifest})

    report = {"tolerance": TOLERANCE, "sessions": rows, "failures": failures}
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n  wrote {out / 'report.json'}")
    print(f"\n  INTERACTIVE REPLAY: {'PASS' if failures == 0 else 'FAIL'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
