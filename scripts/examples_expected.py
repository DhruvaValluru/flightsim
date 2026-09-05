#!/usr/bin/env python
"""Regenerate the expected output of every committed camera example.

    .venv/bin/python scripts/examples_expected.py            # print the section
    .venv/bin/python scripts/examples_expected.py --write    # splice it into the doc

Runs, each as its own process and in this order, the commands an
instructor runs from the committed tree -- ``flightsim.capture`` over
``examples/cameras_multi.yaml``, ``cameras_multi_cockpit.yaml``,
``cameras_waypoint.yaml`` and ``cameras_refusal.yaml``,
``flightsim.verify`` over the first run, ``--against`` over the pair,
and the ten ``--corrupt`` kinds -- and prints each command with its
exit code, its measured wall time and its stdout VERBATIM, paths
normalised to ``runs/...`` so the text reads the same from any
checkout. The section carries the date and the platform it was
measured on.

``docs/CAMERA_PHASE1_REPORT.md`` holds the section between the
markers ``<!-- examples_expected: begin -->`` and ``<!-- examples_expected:
end -->``; ``--write`` replaces it. ``tests/test_camera_cli.py`` regenerates
the blocks and compares them with the document's (:func:`shape`): on
the platform the section was measured on, EXACTLY -- every digest,
check number, pixel coordinate and camera position at its printed
precision, with only the wall-clock seconds per frame and the
machine-worded engine-availability line masked; on another platform
(the CI legs) with digests and numbers masked as well, because the
JSBSim build differs by bits there (measured on the CI streams:
4.1e-13 px here against 1.61e-13 px elsewhere for the same check). So
the document cannot go stale without a test saying so, and a stale
number is stale on the platform it was measured on.

The Windows "Engine verification" section carries ONE more block, the
``--render frames`` run of ``cameras_multi`` on the honest engine STUB
(``tests.test_camera_cli.honest_cli_engine``: the consume-poses pass
as a Python function that writes the PNGs and render.json the
contract specifies), between ``<!-- frames_expected: begin -->`` and
``<!-- frames_expected: end -->``. It is the stdout shape the Windows
command prints -- the same header, JSBSim line, schedule lines, engine
pass lines, overlays, clip, verification table and ``done:`` verdict
-- with the engine-measured digits of the ``engine_parity`` row
masked as ``x``, because only the engine can supply them (``--write``
regenerates it too; ``--frames-stub-run <out>`` is the child process
the generator runs it in). ``test_the_documents_windows_frames_block_
matches_the_stub_run`` compares it the same way.
"""

from __future__ import annotations

import argparse
import datetime as dt
import platform
import re
import subprocess
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
FRAMES_BEGIN = "<!-- frames_expected: begin -->"
FRAMES_END = "<!-- frames_expected: end -->"

#: The Windows command (section "Engine verification (Windows)", step
#: 2), as the instructor types it there with the venv's Windows path
#: and backslashes; here the same argv on the honest engine stub. --brief
#: keeps the two schedule tables to one line each (the full tables are
#: the first Linux block's).
FRAMES_COMMAND = (
    "capture --render frames: two cameras, one flight (cameras_multi), on "
    "the honest engine STUB",
    ".venv\\Scripts\\python -m flightsim.capture examples\\cameras_multi.yaml "
    "--out runs\\demo --render frames --brief",
    ["examples/cameras_multi.yaml", "--out", "runs/demo", "--render",
     "frames", "--brief"])

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
     "moved in every view; cross-view fails beside it since round 3)",
     "python -m flightsim.verify runs/demo --corrupt flight",
     "verify", ["runs/demo", "--corrupt", "flight"]),
    ("verify --corrupt schedule: schedule fidelity must FAIL (an instant "
     "the spec does not schedule; every per-record check PASSES)",
     "python -m flightsim.verify runs/demo --corrupt schedule",
     "verify", ["runs/demo", "--corrupt", "schedule"]),
    ("verify --corrupt pose: pose fidelity must FAIL (one camera moved 5 m, "
     "its quaternion, Euler angles and aircraft untouched; cross-view fails "
     "beside it)",
     "python -m flightsim.verify runs/demo --corrupt pose",
     "verify", ["runs/demo", "--corrupt", "pose"]),
    ("verify --corrupt lens: pose fidelity must FAIL (fx, fy and focal "
     "scaled 1.5x; geometry recovery still PASSES)",
     "python -m flightsim.verify runs/demo --corrupt lens",
     "verify", ["runs/demo", "--corrupt", "lens"]),
    ("verify --corrupt aim: aim fidelity must FAIL (one camera yawed 1 deg, "
     "quaternion and Euler together; the aircraft's pixel is no longer where "
     "the promise puts it)",
     "python -m flightsim.verify runs/demo --corrupt aim",
     "verify", ["runs/demo", "--corrupt", "aim"]),
]


def run_one(module: str, argv: List[str], root: Path) -> Dict:
    """Run ``python -m <module> <argv>`` (paths under ``root``) as its
    own process -- the command exactly as the instructor types it, in
    a fresh interpreter, so the stdout (the JSBSim model-load count
    included: 14 for cameras_multi from a cold process, fewer inside a
    process whose envelope and mixture caches are already warm) is the
    command's own -- collecting stdout, the exit code and the wall
    time."""
    resolved = [str(root / a) if a.startswith("runs/") else
                (str(REPO / a) if a.startswith("examples/") else a)
                for a in argv]
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", module, *resolved], cwd=str(REPO),
        capture_output=True, text=True, encoding="utf-8")
    elapsed = time.perf_counter() - started
    text = _normalise_paths(completed.stdout, root)
    return {"code": int(completed.returncode), "seconds": elapsed,
            "text": text, "stderr": completed.stderr}


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
    mains = {"capture": "flightsim.capture", "verify": "flightsim.verify"}
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
             f"regenerates the blocks and compares them with these: on "
             f"{platform.system()} {platform.machine()} exactly -- every "
             f"digest, check number, pixel coordinate and camera position "
             f"at its printed precision, only the wall-clock seconds per "
             f"frame and the engine-availability line masked; on another "
             f"platform with digests and numbers masked too, because the "
             f"JSBSim build differs by bits there.", ""]
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


# -- the Windows command on the honest engine stub ----------------------

#: Every attribute :func:`frames_stub_child` replaces, and what stands
#: in for it: (dotted name, what the stand-in does). The preamble of the
#: generated block names each one, and the freshness test reads the
#: function's own source to check that nothing is stubbed that this
#: tuple does not disclose -- so a new stub cannot go undisclosed.
STUBBED = (
    ("flightsim.capture.run_render_pass",
     "the commandlet's consume-poses pass replaced by "
     "`tests.test_camera_cli.honest_cli_engine`, a Python function that "
     "reads -scenario= and -camera-index= off the argv and writes the "
     "scheduled PNGs and render.json the contract specifies"),
    ("flightsim.capture.encode_scheduled_clip",
     "the by-product clip's ffmpeg concat call replaced by a placeholder "
     "writer: `clip.mp4` is the 3 bytes `mp4`, never an encode"),
    ("core.util.platform.find_ffmpeg",
     "a fake path (no ffmpeg on this machine, none run)"),
    ("core.util.platform.ue_available",
     "held open (True) so the engine branch is entered"),
    ("core.util.platform.ue_unavailable_reason",
     "None, the same gate"),
    ("webapp.runs.refuse_placeholder_mesh",
     "disabled (the B747 mesh is not imported here, so `aircraft.mesh` "
     "would refuse by name)"),
)

#: The one line of the block that is the playlist ARITHMETIC, not an
#: encode, until section 5b measures the file: what the `clip:` line
#: and run.json's clip_encoded / clip_seconds mean on the stub.
CLIP_LINE_CAVEAT = (
    "The `clip:` line, and run.json's `clip_encoded true` / "
    "`clip_seconds 12.992`, are the playlist arithmetic (black lead-in, "
    "24 instants, a 1 s hold) over a placeholder file, not an encode: "
    "section 5b's ffprobe on the Windows machine is the measurement."
)


def stubbed_words() -> str:
    """The stubs, named one by one for a preamble."""
    return "; ".join(f"`{name}` -- {what}" for name, what in STUBBED)


def frames_stub_child(argv: List[str]) -> int:
    """The child process of :func:`generate_frames`: the capture CLI
    with the engine gate held open and every engine-side piece stubbed
    EXACTLY as ``tests/test_camera_cli.py``'s ``cli_engine`` fixture
    holds it. Every attribute this function replaces is listed in
    :data:`STUBBED` -- ``run_render_pass`` is the honest stub (reads
    -scenario= and -camera-index= off the argv as the commandlet does,
    writes the scheduled PNGs with the aircraft drawn at the labelled
    pixel and the render.json the contract specifies), the by-product
    clip's ffmpeg call writes a 3-byte placeholder, ``find_ffmpeg`` is
    a fake path, the engine gate is held open and the placeholder-mesh
    refusal is disabled. Nothing else is touched: the flight, the
    card, the manifest, the previews, the overlays and the verifier
    are the real ones."""
    import core.util.platform as plat
    import flightsim.capture as cli
    import webapp.runs as runs_module
    from tests.test_camera_cli import honest_cli_engine

    plat.ue_available = lambda: True
    plat.ue_unavailable_reason = lambda: None
    plat.find_ffmpeg = lambda: Path("ffmpeg")
    runs_module.refuse_placeholder_mesh = lambda spec: None

    def fake_encode(ffmpeg, frames_dir, times, clip, lead_in_s=None):
        Path(clip).write_bytes(b"mp4")
        return True

    cli.encode_scheduled_clip = fake_encode
    cli.run_render_pass = honest_cli_engine([])
    return int(cli.main(argv))


def generate_frames(root: Optional[Path] = None) -> Dict:
    """Run the Windows command on the honest engine stub under ``root``
    (``runs/demo`` there) as its own process and return its record:
    label, command, exit code, seconds, text (paths normalised, the
    engine-measured digits masked by :func:`mask_engine`), and the run
    directory so a test can read verify.json and run.json beside the
    block."""
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="frames_expected_"))
    label, command, argv = FRAMES_COMMAND
    resolved = [str(root / a) if a.startswith("runs/") else
                (str(REPO / a) if a.startswith("examples/") else a)
                for a in argv]
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--frames-stub-run",
         *resolved], cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8")
    elapsed = time.perf_counter() - started
    text = mask_engine(_normalise_paths(completed.stdout, root))
    return {"label": label, "command": command,
            "code": int(completed.returncode), "seconds": elapsed,
            "text": text, "stderr": completed.stderr,
            "run_dir": root / "runs" / "demo"}


#: The one table row whose MEASURED cell only the engine can fill: the
#: applied-vs-solved pose, the capture clock, the reprojection.
_ENGINE_PARITY_ROW = re.compile(
    r"^(?P<head>  engine_parity\s+\S+\s+)(?P<measured>.+?)(?P<tail>\s{2,}\S.*)$",
    re.M)


def mask_engine(text: str) -> str:
    """The ``engine_parity`` row's MEASURED cell with every digit
    replaced by ``x`` (``pos 0.000 m`` reads ``pos x.xxx m``), the
    column widths kept: the stub's zeros are the stub's, and the
    document must not print a number the engine has not produced."""
    def _mask(match):
        cell = re.sub(r"\d", "x", match.group("measured"))
        return match.group("head") + cell + match.group("tail")
    return _ENGINE_PARITY_ROW.sub(_mask, text)


def render_frames(record: Dict, when: Optional[str] = None) -> str:
    when = when or dt.date.today().isoformat()
    machine = (f"{platform.system()} {platform.machine()}, Python "
               f"{platform.python_version()}")
    lines = [FRAMES_BEGIN,
             f"Measured {when} on {machine} on the honest engine STUB by "
             f"`scripts/examples_expected.py` (stdout verbatim, paths "
             f"normalised to `runs/...` where Windows prints `runs\\...`; "
             f"wall times are this machine's). Stubbed in the child "
             f"process, and nothing else: {stubbed_words()}. The flight, "
             f"card, manifest, schedule, previews, contact sheets, "
             f"overlays and verifier are the real code. {CLIP_LINE_CAVEAT} "
             f"The `engine_parity` row's MEASURED cell is masked `x`: those "
             f"digits come from the Windows run and are written in here "
             f"from its log. Everything else -- every other line, digest, "
             f"count and check number -- the Windows log must print the "
             f"same, or the difference is the finding. `tests/"
             f"test_camera_cli.py::test_the_documents_windows_frames_block_"
             f"matches_the_stub_run` regenerates this block and compares "
             f"it as the Linux blocks are compared.", ""]
    lines.append(f"#### {record['label']}")
    lines.append("")
    lines.append(f"`{record['command']}` -- exit {record['code']}, "
                 f"{record['seconds']:.2f} s wall on the stub")
    lines.append("")
    lines.append("```")
    lines.extend(record["text"].rstrip("\n").splitlines())
    lines.append("```")
    lines.append("")
    lines.append(FRAMES_END)
    return "\n".join(lines)


def frames_doc_block(doc_text: str) -> Optional[Dict]:
    """The document's stub-frames block: label, command, exit code,
    text; None when the markers are absent."""
    if FRAMES_BEGIN not in doc_text or FRAMES_END not in doc_text:
        return None
    section = doc_text.split(FRAMES_BEGIN, 1)[1].split(FRAMES_END, 1)[0]
    match = re.search(
        r"#### (?P<label>.+?)\n\n`(?P<command>[^`]+)` -- exit (?P<code>\d+), "
        r"[\d.]+ s wall on the stub\n\n```\n(?P<text>.*?)```", section, re.S)
    if not match:
        return None
    return {"label": match.group("label"), "command": match.group("command"),
            "code": int(match.group("code")), "text": match.group("text")}


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
#: The one wall-clock number inside a block: the previews' measured
#: seconds per frame.
_WALL = re.compile(r"\d+\.\d+ s/frame")
_MEASURED_ON = re.compile(r"Measured \d{4}-\d{2}-\d{2} on (\S+) (\S+), Python")


def measured_platform(doc_text: str) -> Optional[str]:
    """"Linux x86_64": the platform the document's section was measured
    on, from its first line; None when the section carries none."""
    match = _MEASURED_ON.search(doc_text)
    return f"{match.group(1)} {match.group(2)}" if match else None


def this_platform() -> str:
    return f"{platform.system()} {platform.machine()}"


def shape(text: str, exact: bool = True) -> List[str]:
    """What a fresh run must reproduce line for line.

    ``exact`` (the document's own platform): the text with ONLY the
    wall-clock seconds per frame and the machine-worded engine-
    availability line masked -- every digest, check number, pixel
    coordinate and camera position must match at its printed
    precision, and a stale one fails.

    Not exact (another platform): every number, digest and camera id
    masked as well, and runs of two or more spaces collapsed to two so
    a float's width (``4.1e-13`` here, ``1.61e-13`` on another
    platform) does not move the column after it -- the words, the
    columns, the check names, the statuses and the line count still
    count. The JSBSim build differs by bits across platforms and so do
    the digests and the last digits; the document says which platform
    its numbers are from."""
    masked = _WALL.sub("<s/frame>", text)
    if not exact:
        masked = _HEX.sub("<hex>", masked)
        masked = _CAMERA.sub("<cam>", masked)
        masked = _NUMBER.sub("#", masked)
    lines = []
    for line in masked.rstrip("\n").splitlines():
        line = line.rstrip()
        if _ENGINE_LINE.match(line):
            line = "<engine availability: machine-dependent>"
        lines.append(line if exact else _GAP.sub("  ", line))
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


def write_doc(section: str, doc: Path = DOC, begin: str = BEGIN,
              end: str = END) -> None:
    text = doc.read_text(encoding="utf-8")
    if begin not in text or end not in text:
        raise SystemExit(f"{doc} carries no {begin} / {end} markers")
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    doc.write_text(head + section + tail, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help=f"replace the section between the markers in "
                             f"{DOC.relative_to(REPO)}")
    parser.add_argument("--root", default=None,
                        help="where to write the runs (default: a "
                             "temporary directory)")
    parser.add_argument("--frames-stub-run", nargs=argparse.REMAINDER,
                        default=None, metavar="CAPTURE-ARGS",
                        help="(the generator's own child process) run the "
                             "capture CLI with these arguments on the "
                             "honest engine stub and exit with its code")
    args = parser.parse_args(argv)
    if args.frames_stub_run is not None:
        return frames_stub_child(args.frames_stub_run)
    root = Path(args.root) if args.root else None
    records = generate(root)
    section = render(records)
    frames = render_frames(generate_frames(
        root / "frames" if root else None))
    if args.write:
        write_doc(section)
        write_doc(frames, begin=FRAMES_BEGIN, end=FRAMES_END)
        print(f"wrote {len(records)} blocks and the stub-frames block into "
              f"{DOC.relative_to(REPO)}", file=sys.stderr)
    else:
        print(section)
        print()
        print(frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
