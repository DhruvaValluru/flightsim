#!/usr/bin/env python3
"""Append one event line to this machine's Phase 3 event log, or wrap a command.

Two forms:

  python scripts/phase3_event.py log --agent builder --box A9 --stage build \
      --note "merged into letter branch"

  python scripts/phase3_event.py run --agent builder --box A9 --stage build -- \
      .venv/bin/pytest -q tests/test_camera_empty.py

`run` logs a start line, runs the command with its output streamed through,
then logs an end line with the exit code and seconds taken, and exits with the
command's exit code. Every agent uses this instead of composing JSON itself,
so the progress terminals always have something true to show and no model
tokens are spent on logging.

The log is per machine (docs/phase3/events_<machine>.log) so the two machines
never append to the same file and never conflict on rebase. The machine comes
from FLIGHTSIM_MACHINE (mac or windows), defaulting to the platform.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def machine_name() -> str:
    env = os.environ.get("FLIGHTSIM_MACHINE")
    if env:
        return env
    return "windows" if platform.system().lower().startswith("win") else "mac"


def log_path() -> Path:
    return ROOT / "docs" / "phase3" / f"events_{machine_name()}.log"


def append(event: dict) -> None:
    event.setdefault("t", time.time())
    event.setdefault("machine", machine_name())
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("log", "run"):
        p = sub.add_parser(name)
        p.add_argument("--agent", required=True, help="breakdown, sub, align, builder, integrator, auditor, debug, decision, runner, synopsis, crosscheck, lettertest, summary, overlap, context, xlt, newcomer, monitor")
        p.add_argument("--box", default="", help="A9, or a letter such as A, or blank")
        p.add_argument("--stage", default="", help="plan, align, build, push, prove, debug, sync, lettertest, final")
        p.add_argument("--note", default="")
    sub.choices["log"].add_argument("--exit", type=int, default=None)
    sub.choices["run"].add_argument("cmd", nargs=argparse.REMAINDER, help="-- then the command")
    args = ap.parse_args(argv)

    base = {"agent": args.agent, "box": args.box, "stage": args.stage}
    if args.mode == "log":
        ev = dict(base, kind="note", note=args.note)
        if args.exit is not None:
            ev["exit"] = args.exit
        append(ev)
        return 0

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        ap.error("run needs a command after --")
    shown = " ".join(cmd)
    append(dict(base, kind="start", cmd=shown, note=args.note))
    t0 = time.time()
    try:
        rc = subprocess.call(cmd, cwd=str(ROOT))
    except FileNotFoundError as exc:
        append(dict(base, kind="end", cmd=shown, exit=127, secs=round(time.time() - t0, 1), note=f"not found: {exc}"))
        print(f"phase3_event: command not found: {cmd[0]}", file=sys.stderr)
        return 127
    append(dict(base, kind="end", cmd=shown, exit=rc, secs=round(time.time() - t0, 1), note=args.note))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
