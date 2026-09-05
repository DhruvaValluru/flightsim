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

Section 6 of the same Windows section carries the PAGE block, between
``<!-- page_expected: begin -->`` and ``<!-- page_expected: end -->``:
the committed example posted to the TestClient's ``/run`` with the
render choice "frames" on the same honest stub (``--page-stub-run
<root>`` is its child process), the run's event list as ``/runs/<id>``
serves it and the card, strip and galleries rendered under node from
the page's own functions. ``tests/test_webapp_capture.py::
test_the_documents_page_block_matches_the_stub_run`` regenerates and
compares it. Every attribute either child stubs is disclosed in
:data:`STUBBED` / :data:`PAGE_STUBBED` and named in the block's
preamble; the tests read the children's own source against the tuples.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]

#: The environment every documented command runs under as a child
#: process: stdout decoded here as UTF-8, so the child must WRITE UTF-8.
#: On Windows a child Python writes a pipe in the console code page
#: (cp1252) unless told otherwise -- measured on the Windows CI leg at
#: 150c220: the page block's em dash arrived as byte 0x97 and the
#: UTF-8 decode of the reader thread failed, stdout came back None.
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
sys.path.insert(0, str(REPO))

DOC = REPO / "docs" / "CAMERA_PHASE1_REPORT.md"
BEGIN = "<!-- examples_expected: begin -->"
END = "<!-- examples_expected: end -->"
FRAMES_BEGIN = "<!-- frames_expected: begin -->"
FRAMES_END = "<!-- frames_expected: end -->"
PAGE_BEGIN = "<!-- page_expected: begin -->"
PAGE_END = "<!-- page_expected: end -->"

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
        capture_output=True, text=True, encoding="utf-8", env=CHILD_ENV)
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
        encoding="utf-8", env=CHILD_ENV)
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


# -- the same run from the page, on the honest engine stub --------------

#: Every attribute :func:`page_stub_child` replaces, and what stands in
#: for it -- the webapp's own stubs (``tests/test_webapp_capture.py``'s
#: ``engine_stubs`` and ``engine_client`` fixtures), disclosed the way
#: :data:`STUBBED` discloses the CLI child's; the freshness test reads
#: the function's own source against this tuple.
PAGE_STUBBED = (
    ("webapp.runs.RunManager._render",
     "the commandlet pass replaced by `tests.test_webapp_capture."
     "honest_engine`, the consume-poses pass as a Python function (the "
     "scheduled PNGs and render.json the contract specifies)"),
    ("webapp.runs.encode_scheduled_clip",
     "the by-product clip's ffmpeg concat call replaced by a placeholder "
     "writer: `clip.mp4` is the 3 bytes `mp4`, never an encode"),
    ("core.util.platform.find_ffmpeg",
     "a fake path (no ffmpeg on this machine, none run)"),
    ("core.util.platform.ue_available",
     "held open (True) so the engine choices are offered and taken"),
    ("core.util.platform.ue_unavailable_reason",
     "None, the same gate"),
    ("webapp.server.refuse_placeholder_mesh",
     "disabled (the B747 mesh is not imported here)"),
    ("webapp.runs.ensure_control_ridge",
     "a no-op (the flat scene needs no raster; the bake is not run)"),
    ("webapp.runs.ensure_aircraft_model",
     "a no-op (the model import needs the engine)"),
    ("webapp.runs.editor_running",
     "False (gotcha 9's editor-lock check; no editor here)"),
    ("webapp.server.manager.out_root",
     "the generator's temporary directory, so the run lands there"),
)

#: The page's status log, as the generated block prints it: the event's
#: status word padded to this width, then its detail (the page itself
#: prefixes each line with the local time, which no document can carry).
PAGE_STATUS_WIDTH = 10

#: The example the page block runs -- the same spec as the Windows
#: command's -- posted to /run as the page posts a reviewed spec, with
#: the prompt below recorded on it. The prompt matters: the page's
#: scene-setting planner (webapp.runs.plan_scene_setting) stages a spec
#: whose location nobody chose on the prairie bake, and on a machine
#: without that bake on the synthesised control ridge, where 10000 ft
#: refuses terrain.clearance under 3299 m peaks (measured here); "flat
#: ground" is the planner's own opt-out, so the run stays on the flat
#: scene the CLI's cameras_multi run flies, with the same digest (the
#: prompt is not digest-relevant).
PAGE_EXAMPLE = "examples/cameras_multi.yaml"
PAGE_PROMPT = ("fly the 747 at 10000 ft and 280 kt for 12 seconds over flat "
               "ground with a chase camera and a tower camera capturing 24 "
               "images")


def page_stubbed_words() -> str:
    return "; ".join(f"`{name}` -- {what}" for name, what in PAGE_STUBBED)


_BLOCK_CLOSE = re.compile(r"</(?:p|div|li|tr|h[1-6]|summary|details|ul|table|"
                          r"thead|tbody|figure|figcaption|label)>|<br\s*/?>",
                          re.I)


def lines_of(html: str) -> List[str]:
    """The words a reader sees, one line per block element: the HTML
    split at its block-closing tags, tags stripped, whitespace
    collapsed, empty lines dropped (``tests.test_webapp_capture.
    text_of`` per block)."""
    import html as html_module

    lines = []
    for piece in _BLOCK_CLOSE.split(html):
        words = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", piece)).strip()
        if words:
            lines.append(html_module.unescape(words))
    return lines


_CAPTION = re.compile(r"^#\d+ t=\S+ s$")


def fold_captions(lines: List[str]) -> List[str]:
    """Consecutive frame captions (``#k t=... s``, one block element
    each in a gallery) joined on one line, comma-separated, so a
    24-frame gallery reads as one line of captions and not 24."""
    folded: List[str] = []
    run: List[str] = []
    for line in [*lines, None]:
        if line is not None and _CAPTION.match(line):
            run.append(line)
            continue
        if run:
            folded.append("captions: " + ", ".join(run))
            run = []
        if line is not None:
            folded.append(line)
    return folded


def page_stub_child(root: Path) -> int:
    """The child process of :func:`generate_page`: the TestClient over
    the webapp with the engine gate held open and every engine-side
    piece stubbed EXACTLY as ``tests/test_webapp_capture.py``'s
    ``engine_stubs`` and ``engine_client`` fixtures hold it -- every
    attribute replaced is listed in :data:`PAGE_STUBBED`. Posts the
    committed example to ``/run`` with the render choice "frames",
    polls the run to completion, and prints the page's status log (the
    run's event list, the same list ``status.json`` keeps) followed by
    the capture card, the download strip and the galleries as node
    renders them from the page's own functions, one line per block
    element."""
    from starlette.testclient import TestClient

    import core.util.platform as plat
    import webapp.runs as runs_module
    import webapp.server as server_module
    from core.scenario.spec import ScenarioSpec
    from tests.test_webapp_capture import (
        finished, honest_engine, page_capture, text_of,
    )

    plat.ue_available = lambda: True
    plat.ue_unavailable_reason = lambda: None
    plat.find_ffmpeg = lambda: Path("ffmpeg")
    server_module.refuse_placeholder_mesh = lambda spec: None
    runs_module.ensure_control_ridge = lambda: None
    runs_module.ensure_aircraft_model = lambda spec, report: None
    runs_module.editor_running = lambda: False
    server_module.manager.out_root = root / "runs"

    def fake_encode(ffmpeg, frames_dir, times, clip, lead_in_s=None):
        Path(clip).write_bytes(b"mp4")
        return True

    runs_module.encode_scheduled_clip = fake_encode
    runs_module.RunManager._render = staticmethod(honest_engine([]))

    client = TestClient(server_module.app)
    spec = ScenarioSpec.read(REPO / PAGE_EXAMPLE)
    spec.prompt = PAGE_PROMPT
    reply = client.post("/run", json={"spec": spec.to_dict(), "render": "frames"})
    if reply.status_code != 200:
        print(f"POST /run answered {reply.status_code}: {reply.text}")
        return 1
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    files = client.get(f"/runs/{run_id}/files").json()
    for event in state["events"]:
        print(f"{event['status']:<{PAGE_STATUS_WIDTH}} {event['detail']}")
    print()
    print("card (the words the page shows, one line per block; tags stripped):")
    page = page_capture(root, state, files, run_id)
    print(f"  {text_of(page['clip'])}")
    for line in lines_of(page["strip"]):
        print(f"  {line}")
    for line in lines_of(page["card"]):
        print(f"  {line}")
    for gallery in page["galleries"]:
        for line in fold_captions(lines_of(gallery)):
            print(f"  {line}")
    (root / "run_id").write_text(run_id, encoding="utf-8")
    return 0 if state["status"] == "done" else 1


#: The page's engine_parity row, as the card's table renders it: the
#: MEASURED cell only the engine can fill, digits masked as the CLI
#: block's are.
_PAGE_PARITY_ROW = re.compile(
    r"^(?P<head>  engine_parity PASS )(?P<measured>pos \S+ m, ang \S+ deg, "
    r"t \S+ s, px \S+)(?P<tail> .*)$", re.M)


def mask_page(text: str, run_id: str) -> str:
    """The run id (a uuid, different every run) reads ``<id>`` and the
    page's engine_parity MEASURED cell has every digit replaced by
    ``x``: the stub's zeros are the stub's."""
    text = text.replace(run_id, "<id>")

    def _mask(match):
        cell = re.sub(r"\d", "x", match.group("measured"))
        return match.group("head") + cell + match.group("tail")
    return _PAGE_PARITY_ROW.sub(_mask, text)


def generate_page(root: Optional[Path] = None) -> Dict:
    """Run the page's frames flow on the honest engine stub under
    ``root`` as its own process and return its record: exit code,
    seconds, text (paths normalised, the run id and the engine-measured
    digits masked), the run directory."""
    if root is None:
        root = Path(tempfile.mkdtemp(prefix="page_expected_"))
    root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--page-stub-run",
         str(root)], cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", env=CHILD_ENV)
    elapsed = time.perf_counter() - started
    run_id_file = root / "run_id"
    run_id = run_id_file.read_text(encoding="utf-8") if run_id_file.is_file() else ""
    text = _normalise_paths(completed.stdout, root)
    if run_id:
        text = mask_page(text, run_id)
    return {"code": int(completed.returncode), "seconds": elapsed,
            "text": text, "stderr": completed.stderr,
            "run_dir": (root / "runs" / run_id) if run_id else None,
            "run_id": run_id}


def render_page(record: Dict, when: Optional[str] = None) -> str:
    when = when or dt.date.today().isoformat()
    machine = (f"{platform.system()} {platform.machine()}, Python "
               f"{platform.python_version()}")
    lines = [PAGE_BEGIN,
             f"Measured {when} on {machine} on the honest engine STUB by "
             f"`scripts/examples_expected.py` (`--page-stub-run`: "
             f"`{PAGE_EXAMPLE}` posted to the TestClient's `/run` with the "
             f"render choice \"frames\", the run polled to completion, "
             f"exit {record['code']}, {record['seconds']:.2f} s wall on the "
             f"stub; the status lines are the run's event list as `/runs/"
             f"<id>` serves it -- the page prefixes each with the local "
             f"time -- the status word padded to {PAGE_STATUS_WIDTH} "
             f"columns; the card lines are the download strip, the capture "
             f"card and the galleries rendered under node from the page's "
             f"own functions, one line per block element, tags stripped, "
             f"a gallery's consecutive frame captions joined on one line; "
             f"the run id reads `<id>`). Stubbed in the child process, and "
             f"nothing else: {page_stubbed_words()}. The capture flight, "
             f"the closure flight, the card, the manifest, the schedule, "
             f"the previews, the contact sheets, the overlays, the "
             f"verifier and the page's own JavaScript are the real code. "
             f"{CLIP_LINE_CAVEAT} The page's `engine_parity` row's MEASURED "
             f"cell is masked `x`: those digits come from the Windows run. "
             f"`tests/test_webapp_capture.py::"
             f"test_the_documents_page_block_matches_the_stub_run` "
             f"regenerates this block and compares it as the CLI blocks "
             f"are compared (exact on {platform.system()} "
             f"{platform.machine()}, numbers masked elsewhere).", ""]
    lines.append("```")
    lines.extend(record["text"].rstrip("\n").splitlines())
    lines.append("```")
    lines.append("")
    lines.append(PAGE_END)
    return "\n".join(lines)


def page_doc_block(doc_text: str) -> Optional[Dict]:
    """The document's page block: exit code, text; None when the
    markers or the block are absent."""
    if PAGE_BEGIN not in doc_text or PAGE_END not in doc_text:
        return None
    section = doc_text.split(PAGE_BEGIN, 1)[1].split(PAGE_END, 1)[0]
    match = re.search(r"exit (?P<code>\d+), [\d.]+ s wall on the stub.*?"
                      r"\n\n```\n(?P<text>.*?)```", section, re.S)
    if not match:
        return None
    return {"code": int(match.group("code")), "text": match.group("text")}


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
    parser.add_argument("--page-stub-run", default=None, metavar="ROOT",
                        help="(the generator's own child process) run the "
                             "page's frames flow on the honest engine stub "
                             "under ROOT and print its status log and card")
    args = parser.parse_args(argv)
    if args.frames_stub_run is not None:
        return frames_stub_child(args.frames_stub_run)
    if args.page_stub_run is not None:
        return page_stub_child(Path(args.page_stub_run))
    root = Path(args.root) if args.root else None
    records = generate(root)
    section = render(records)
    frames = render_frames(generate_frames(
        root / "frames" if root else None))
    page = render_page(generate_page(root / "page" if root else None))
    if args.write:
        write_doc(section)
        write_doc(frames, begin=FRAMES_BEGIN, end=FRAMES_END)
        write_doc(page, begin=PAGE_BEGIN, end=PAGE_END)
        print(f"wrote {len(records)} blocks, the stub-frames block and the "
              f"page block into {DOC.relative_to(REPO)}", file=sys.stderr)
    else:
        print(section)
        print()
        print(frames)
        print()
        print(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
