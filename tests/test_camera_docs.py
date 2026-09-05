"""Camera Phase 1, package I: the documents tell the truth today.

docs/CAMERA_PHASE1_REPORT.md, README.md and NEXT.md are read as
files: what they claim about platforms is pinned against the facts
the tree carries, and the engine claims are pinned to "NOT YET RUN"
until a Windows log has been read -- the session that reads it
rewrites the report's status table AND this test in one commit, which
is the point: no engine result can enter the document without a test
changing beside it.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "docs" / "CAMERA_PHASE1_REPORT.md"
README = REPO / "README.md"
NEXT = REPO / "NEXT.md"


def _status_table():
    """The rows of the report's "Status today" table: {deliverable:
    (headless cell, windows-engine cell)}, taken from the top of the
    document."""
    text = REPORT.read_text(encoding="utf-8")
    head = text.split("## What the camera is now", 1)[0]
    match = re.search(r"^## Status today \((\d{4}-\d{2}-\d{2})\)$", head, re.M)
    assert match, "the report has no dated 'Status today' heading at its top"
    rows = {}
    for line in head.splitlines():
        if not line.startswith("| ") or line.startswith("|---") or \
                line.startswith("| deliverable"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 3, line
        rows[cells[0]] = (cells[1], cells[2])
    return match.group(1), rows


def test_the_report_carries_no_control_character_but_newline():
    """A backslash sequence interpreted when the text was written
    (`\\f`, `\\r`) destroys the one path a reader is told to edit
    (measured on section 6c: `capture<FF>rames\\chase0<LF>ender.json`);
    the document is plain text with newlines and nothing else below
    space."""
    raw = REPORT.read_bytes()
    # A checkout on Windows may carry CRLF line endings (Git's autocrlf
    # on the CI runner): a CR that ends a line is the line ending, not
    # a destroyed path; a CR anywhere else still is.
    raw = raw.replace(b"\r\n", b"\n")
    bad = [(i, b) for i, b in enumerate(raw)
           if b < 0x20 and b not in (0x0A,)]
    assert bad == [], bad[:5]
    assert b"\t" not in raw
    text = raw.decode("utf-8")
    assert "`runs\\<id>\\capture\\frames\\chase0\\render.json`" in text


def test_the_report_opens_with_a_dated_status_table():
    """The thirty-second reader learns at the top what is measured and
    what awaits: one row per deliverable, the headless column dated and
    naming the test that keeps it fresh, the engine column either
    'NOT YET RUN -- section N' or an observation with its date."""
    when, rows = _status_table()
    assert when == "2026-09-05"
    text = REPORT.read_text(encoding="utf-8")
    assert text.index("## Status today") < text.index("## What the camera is now")
    assert text.index("## Status today") < 400
    assert len(rows) >= 9
    for deliverable, (headless, engine) in rows.items():
        assert headless, deliverable
        assert re.search(r"NOT YET RUN -- section|observed on the user's Windows|"
                         r"the same Python|the same command", engine), \
            (deliverable, engine)
    engine_rows = [d for d in rows
                   if re.search(r"--render frames|engine_parity|overlays|"
                                r"by-product clip|page's frames flow|"
                                r"temporal alignment|C\+\+", d)]
    assert len(engine_rows) >= 7
    for deliverable in engine_rows:
        headless, engine = rows[deliverable]
        assert engine.startswith("NOT YET RUN -- section"), (deliverable, engine)
        assert not re.search(r"\bverified on Windows\b|measured on Windows", engine)
    # The headless column carries dates and tests, not promises.
    dated = [d for d, (h, _) in rows.items() if "2026-09-05" in h]
    assert len(dated) >= 5
    assert any("test_the_documents_expected_output_matches_a_fresh_run" in h
               for h, _ in rows.values())
    # The clip row says WHEN and on WHAT the Windows observation was made,
    # and that today's flow is not re-run.
    clip = next(e for d, (_, e) in rows.items() if d.startswith("`--render clip`"))
    assert "before 2026-09-03" in clip and "PRE-REWRITE" in clip
    assert "NOT re-run" in clip


def test_the_engine_section_and_limitations_say_not_yet_run():
    """The engine section's status line and the Known limitations agree
    with the table: NOT YET RUN, in those words, until a log is read."""
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("## Engine verification (Windows)", 1)[1]
    assert section.lstrip().startswith("**Status: NOT YET RUN.**")
    limits = text.split("## Known limitations", 1)[1]
    assert "**The engine pass is NOT YET RUN.**" in limits
    assert "The overlays have been drawn over the honest engine stub only" in limits


def test_the_readme_matches_its_own_platform_table():
    """README's platform table says Windows renders after the build;
    its capture section must not say the render refuses 'off macOS',
    must not quote a preview timing that the report's dated blocks do
    not carry, and must point at the report's engine section and its
    status table."""
    text = README.read_text(encoding="utf-8")
    capture = text.split("## Capture camera geometry", 1)[1].split("\n## ", 1)[0]
    assert "Off macOS" not in capture
    assert "Without the engine (Linux; macOS or Windows before the build" in capture
    report = REPORT.read_text(encoding="utf-8")
    for match in re.finditer(r"(\d+\.\d+)(?:-(\d+\.\d+))? s/frame", capture):
        for value in match.groups():
            if value is not None:
                assert f"{value} s/frame" in report, (value, "not in the report")
    assert '"Engine verification\n(Windows)"' in capture or \
        '"Engine verification (Windows)"' in capture
    assert '"Status today"' in capture
    assert "NOT YET RUN" in capture
    # The Windows column of the table is what the capture section says.
    table_row = next(line for line in text.splitlines()
                     if line.startswith("| Rendered frames and clips"))
    assert table_row.rstrip("| ").endswith("after the build below")


def test_the_platform_module_docstring_matches_its_own_refusal():
    """core/util/platform.py's docstring said the render half was
    'macOS-only for now' while ue_unavailable_reason() names Windows;
    the docstring carries the reason's own words."""
    import core.util.platform as plat

    doc = " ".join(plat.__doc__.split())
    assert "macOS-only" not in doc
    words = "Windows with Unreal Engine 5.5 and the FlightSimBridge built"
    assert words in doc
    assert words in " ".join(plat.UE_PLATFORM_REFUSAL.split())
    if plat.os_name() == "linux":
        assert words in plat.ue_unavailable_reason()


def test_next_md_has_a_standing_windows_pointer_and_counts_its_gotchas():
    """A fresh session must not read 500 lines to learn that the engine
    pass has never run, where the steps are, or what the render choice
    is; and 'gotchas 1-N' must count the gotchas the file holds."""
    text = NEXT.read_text(encoding="utf-8")
    top = "\n".join(text.splitlines()[:40])
    assert "NOT YET RUN on Windows" in top
    assert 'docs/CAMERA_PHASE1_REPORT.md\n"Engine verification (Windows)" steps 1-7' in top
    assert "`--render frames|clip|none`" in top
    assert "Render frames and clip / Clip only / Headless" in top
    assert '"Status today"' in top
    numbers = [int(n) for n in re.findall(r"^(\d+)\. \*\*", text, re.M)]
    assert numbers and numbers == sorted(numbers)
    highest = max(numbers)
    match = re.search(r"gotchas 1-(\d+)\.", top)
    assert match, "the resume block names no gotcha range"
    assert int(match.group(1)) == highest, (match.group(1), highest)
