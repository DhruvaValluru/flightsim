"""Gate 10-R -- render reproducibility, measured, never asserted.

The claim under test, from VALIDITY section 3: "Rendering will not be
bit-deterministic." That was written about Movie Render Queue, which
this system does not use. The offscreen commandlet renders from a card
with every input the same on every run -- fixed warm-up captures, manual
exposure, async compilation finished before the first frame -- and with
-deterministic it also pins texture streaming and LOD. Whether the
pixels come out the same is a MEASUREMENT: render the same card twice
and compare.

    python experiments/gate10_render_repro.py --card runs/x/card.json
    python experiments/gate10_render_repro.py --against A/frames B/frames

The first renders twice and compares; the second compares two existing
frame directories (any two renders of one card by one build). The
report is runs/gate10_render_repro/report.json and the verdict is one
of core.capture.repro's three words with its numbers: bit-identical,
bounded (with the maximum per-pixel difference), or incomplete. On a
machine with no engine the first form exits 2 with the ue.platform
reason and writes a report saying NOT RUN -- it never fabricates a
number, and NOT RUN is not a verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.capture.repro import compare_frame_sets, describe  # noqa: E402
from core.util.platform import (  # noqa: E402
    ue_available, ue_platform_refusal, ue_runner_command,
)

NOT_RUN = "NOT RUN"


def render_twice(card: Path, out: Path, extra: Sequence[str]) -> Optional[str]:
    """Two passes of the same card through the same wrapper, with the
    same arguments. Returns a refusal string, or None when both wrote
    frames."""
    import subprocess

    for label in ("A", "B"):
        frames = out / f"render_{label}"
        frames.mkdir(parents=True, exist_ok=True)
        command = ue_runner_command(REPO, "render_ue_scenario")
        command += [str(card), str(frames), "-Visual", "-deterministic", *extra]
        log = out / f"render_{label}.log"
        with log.open("w", encoding="utf-8") as sink:
            completed = subprocess.run(command, stdout=sink,
                                       stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL)
        if completed.returncode != 0:
            return (f"render pass {label} exited {completed.returncode}; "
                    f"its log is {log}")
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 10-R: render reproducibility")
    ap.add_argument("--card", help="run card to render twice")
    ap.add_argument("--against", nargs=2, metavar=("FRAMES_A", "FRAMES_B"),
                    help="compare two existing frame directories instead")
    ap.add_argument("--out", default="runs/gate10_render_repro")
    ap.add_argument("--extra", nargs="*", default=[],
                    help="extra wrapper arguments (e.g. -terrain=...)")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "report.json"

    if args.against:
        dir_a, dir_b = (Path(p).resolve() for p in args.against)
        source = {"mode": "against", "frames_a": str(dir_a), "frames_b": str(dir_b)}
    elif args.card:
        card = Path(args.card).resolve()
        if not card.is_file():
            print(f"no such card: {card}")
            return 1
        if not ue_available():
            report = {"verdict": NOT_RUN, "reason": "ue.platform",
                      "detail": ue_platform_refusal(), "card": str(card)}
            report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
            print(f"Gate 10-R: {NOT_RUN} -- [ue.platform] {ue_platform_refusal()}")
            print(f"report: {report_path}")
            return 2
        refusal = render_twice(card, out, args.extra)
        if refusal:
            report = {"verdict": NOT_RUN, "reason": "render", "detail": refusal,
                      "card": str(card)}
            report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
            print(f"Gate 10-R: {NOT_RUN} -- {refusal}")
            return 2
        dir_a, dir_b = out / "render_A", out / "render_B"
        source = {"mode": "render", "card": str(card),
                  "frames_a": str(dir_a), "frames_b": str(dir_b),
                  "wrapper_arguments": ["-Visual", "-deterministic", *args.extra]}
    else:
        ap.error("give --card to render twice, or --against A B to compare")
        return 1

    report = compare_frame_sets(dir_a, dir_b)
    report["source"] = source
    report["statement"] = describe(report)
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"Gate 10-R: {report['statement']}")
    if report.get("engine_digests_agree_with_files") is False:
        print("  NOTE: a frame on disk is not the frame the engine recorded "
              "writing (sha256 disagrees) -- a replaced frame, not a render "
              "difference")
    print(f"report: {report_path}")
    return 0 if report["verdict"] in ("bit-identical", "bounded") else 1


if __name__ == "__main__":
    sys.exit(main())
