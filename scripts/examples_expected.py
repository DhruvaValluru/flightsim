#!/usr/bin/env python
"""Regenerate the expected output of every committed camera example.

    .venv/bin/python scripts/examples_expected.py            # print the section
    .venv/bin/python scripts/examples_expected.py --write    # splice it into the doc

Runs, in this process and in this order, the commands an instructor
runs from the committed tree -- ``flightsim.capture`` over
``examples/cameras_multi.yaml``, ``cameras_multi_cockpit.yaml``,
``cameras_waypoint.yaml`` and ``cameras_refusal.yaml``,
``flightsim.verify`` over the first run, ``--against`` over the pair,
and the seven ``--corrupt`` kinds -- and prints each command with its
exit code, its measured wall time and its stdout VERBATIM, paths
normalised to ``runs/...`` so the text reads the same from any
checkout. The section carries the date and the platform it was
measured on.

``docs/CAMERA_PHASE1_REPORT.md`` holds the section between the
markers ``<!-- examples_expected: begin -->`` and ``<!-- examples_expected:
end -->``; ``--write`` replaces it. ``tests/test_camera_cli.py`` regenerates
the blocks and compares their SHAPE (:func:`shape`: numbers, camera ids
and paths masked, so timings and float noise do not count) with the
document's, so the document cannot go stale without a test saying so.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import platform
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DOC = REPO / "docs" / "CAMERA_PHASE1_REPORT.md"
BEGIN = "<!-- examples_expected: begin -->"
END = "<!-- examples_expected: end -->"

#: (label, command words as the instructor types them, main, argv
#: relative to the root) -- the order matters: verify needs the runs.
COMMANDS = [
    ("capture: two cameras, one flight (cameras_multi)",
     "python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo",
     "capture", ["examples/cameras_multi.yaml", "--out", "runs/demo",
                 "--render", "none"]),
    ("verify: the same run, graded from its directory",
     "python -m flightsim.verify runs/demo",
     "verify", ["runs/demo"]),
    ("capture: the same flight, a cockpit camera (cameras_multi_cockpit)",
     "python -m flightsim.capture examples/cameras_multi_cockpit.yaml "
     "--out runs/demo_b",
     "capture", ["examples/cameras_multi_cockpit.yaml", "--out",
                 "runs/demo_b", "--render", "none"]),
    ("verify --against: temporal alignment across the two camera sets",
     "python -m flightsim.verify runs/demo_b --against runs/demo",
     "verify", ["runs/demo_b", "--against", "runs/demo"]),
    ("capture: waypoint trigger, one camera (cameras_waypoint)",
     "python -m flightsim.capture examples/cameras_waypoint.yaml "
     "--out runs/waypoint",
     "capture", ["examples/cameras_waypoint.yaml", "--out", "runs/waypoint",
                 "--render", "none"]),
    ("capture: the refusal (cameras_refusal)",
     "python -m flightsim.capture examples/cameras_refusal.yaml "
     "--out runs/refused",
     "capture", ["examples/cameras_refusal.yaml", "--out", "runs/refused",
                 "--render", "none"]),
    ("verify --corrupt quaternion: geometry recovery must FAIL",
     "python -m flightsim.verify runs/demo --corrupt quaternion",
     "verify", ["runs/demo", "--corrupt", "quaternion"]),
    ("verify --corrupt aircraft: cross-view consistency must FAIL",
     "python -m flightsim.verify runs/demo --corrupt aircraft",
     "verify", ["runs/demo", "--corrupt", "aircraft"]),
    ("verify --corrupt time: temporal alignment must FAIL",
     "python -m flightsim.verify runs/demo --corrupt time",
     "verify", ["runs/demo", "--corrupt", "time"]),
    ("verify --corrupt count: count exactness must FAIL",
     "python -m flightsim.verify runs/demo --corrupt count",
     "verify", ["runs/demo", "--corrupt", "count"]),
    ("verify --corrupt clock: flight fidelity must FAIL (every instant "
     "shifted, no sibling run)",
     "python -m flightsim.verify runs/demo --corrupt clock",
     "verify", ["runs/demo", "--corrupt", "clock"]),
    ("verify --corrupt flight: flight fidelity must FAIL (the aircraft "
     "moved in every view; cross-view still PASSES)",
     "python -m flightsim.verify runs/demo --corrupt flight",
     "verify", ["runs/demo", "--corrupt", "flight"]),
    ("verify --corrupt schedule: schedule fidelity must FAIL (an instant "
     "the spec does not schedule; every per-record check PASSES)",
     "python -m flightsim.verify runs/demo --corrupt schedule",
     "verify", ["runs/demo", "--corrupt", "schedule"]),
]


def run_one(main, argv: List[str], root: Path) -> Dict:
    """Run ``main`` in-process with ``argv`` (paths under ``root``),
    collecting stdout, the exit code and the wall time."""
    resolved = [str(root / a) if a.startswith("runs/") else
                (str(REPO / a) if a.startswith("examples/") else a)
                for a in argv]
    buffer = io.StringIO()
    started = time.perf_counter()
    with contextlib.redirect_stdout(buffer):
        code = main(resolved)
    elapsed = time.perf_counter() - started
    text = _normalise_paths(buffer.getvalue(), root)
    return {"code": int(code), "seconds": elapsed, "text": text}


_RELATIVE = re.compile(r"(?:runs|examples)\\[^\s'\"(),;]*")


def _normalise_paths(text: str, root: Path) -> str:
    """Every path under ``root`` or the checkout reads ``runs/...`` or
    ``examples/...`` with forward slashes, whatever the host's
    separator: the document is measured on one platform and compared
    on all three."""
    for base in (root, REPO):
        for sep in ("/", "\\"):
            text = text.replace(str(base) + sep, "")
    return _RELATIVE.sub(lambda m: m.group(0).replace("\\", "/"), text)


def generate(root: Optional[Path] = None, when: Optional[str] = None) -> List[Dict]:
    """Run every command under ``root`` (a temporary directory by
    default) and return one record per command: label, command, exit
    code, seconds, text."""
    from flightsim.capture import main as capture_main
    from flightsim.verify import main as verify_main

    mains = {"capture": capture_main, "verify": verify_main}
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="examples_expected_"))
    records = []
    for label, command, which, argv in COMMANDS:
        record = run_one(mains[which], argv, root)
        record.update({"label": label, "command": command})
        records.append(record)
    return records


def render(records: List[Dict], when: Optional[str] = None) -> str:
    when = when or dt.date.today().isoformat()
    machine = (f"{platform.system()} {platform.machine()}, Python "
               f"{platform.python_version()}")
    lines = [BEGIN,
             f"Measured {when} on {machine} by "
             f"`scripts/examples_expected.py` (every block below is the "
             f"command's stdout verbatim, paths normalised to `runs/...`; "
             f"wall times are this machine's, previews at full "
             f"resolution). `tests/test_camera_cli.py::"
             f"test_the_documents_expected_output_matches_a_fresh_run` "
             f"regenerates the blocks and compares their shape with "
             f"these.", ""]
    for r in records:
        lines.append(f"#### {r['label']}")
        lines.append("")
        lines.append(f"`{r['command']}` -- exit {r['code']}, "
                     f"{r['seconds']:.2f} s wall")
        lines.append("")
        lines.append("```")
        lines.extend(r["text"].rstrip("\n").splitlines())
        lines.append("```")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


# -- the shape a test compares ------------------------------------------

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?")
_CAMERA = re.compile(r"\b(chase0|tower0|shoulder|survey|buried)\b")
_HEX = re.compile(r"\b[0-9a-f]{16,64}\b")
#: The one line whose words depend on the machine, not the run: the
#: engine's absence is stated with the platform's own reason (Linux,
#: macOS and Windows each word it differently), and a machine that HAS
#: the engine says "render: none (headless by choice ...)" instead.
_ENGINE_LINE = re.compile(
    r"^(?:engine absent: .*; frames not rendered .*"
    r"|render: none \(headless by choice.*)$")
_GAP = re.compile(r" {2,}")


def shape(text: str) -> List[str]:
    """The text with every number, digest and camera id masked: what a
    fresh run must reproduce line for line (timings, float noise and
    the worst frame's identity do not count; the words, the columns,
    the check names, the statuses and the line count do).

    Two things are machine-dependent and masked as well: the engine-
    availability line (its reason is worded per platform) becomes
    ``<engine availability: machine-dependent>``, and runs of two or
    more spaces collapse to two, so a column keeps its place in the
    row while a float's width (``4.1e-13`` here, ``1.61e-13`` on
    another platform) does not move the column after it."""
    masked = _HEX.sub("<hex>", text)
    masked = _CAMERA.sub("<cam>", masked)
    masked = _NUMBER.sub("#", masked)
    lines = []
    for line in masked.rstrip("\n").splitlines():
        line = line.rstrip()
        if _ENGINE_LINE.match(line):
            line = "<engine availability: machine-dependent>"
        lines.append(_GAP.sub("  ", line))
    return lines


def doc_blocks(doc_text: str) -> List[Dict]:
    """The blocks of the document's section: label, command, exit
    code, text."""
    section = doc_text.split(BEGIN, 1)[1].split(END, 1)[0]
    blocks = []
    pattern = re.compile(
        r"#### (?P<label>.+?)\n\n`(?P<command>[^`]+)` -- exit (?P<code>\d+), "
        r"[\d.]+ s wall\n\n```\n(?P<text>.*?)```", re.S)
    for match in pattern.finditer(section):
        blocks.append({"label": match.group("label"),
                       "command": match.group("command"),
                       "code": int(match.group("code")),
                       "text": match.group("text")})
    return blocks


def write_doc(section: str, doc: Path = DOC) -> None:
    text = doc.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{doc} carries no {BEGIN} / {END} markers")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    doc.write_text(head + section + tail, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help=f"replace the section between the markers in "
                             f"{DOC.relative_to(REPO)}")
    parser.add_argument("--root", default=None,
                        help="where to write the runs (default: a "
                             "temporary directory)")
    args = parser.parse_args(argv)
    records = generate(Path(args.root) if args.root else None)
    section = render(records)
    if args.write:
        write_doc(section)
        print(f"wrote {len(records)} blocks into {DOC.relative_to(REPO)}",
              file=sys.stderr)
    else:
        print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
