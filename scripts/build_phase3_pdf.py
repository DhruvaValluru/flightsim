"""Build docs/FlightSim_Phase3_Guidelines.pdf from the two Phase 3 task files.

The PDF is the checklist (tasks/phase3_checklist.md, Part 1) and the
lettered plan (tasks/phase3_todo.md, Part 2) behind a cover page. Edit the
Markdown, then re-run this script; the PDF is never edited by hand.

Needs pandoc, Node with Playwright, and the Inter font installed.

Usage: python scripts/build_phase3_pdf.py [--html out.html]
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKLIST = REPO / "tasks" / "phase3_checklist.md"
PLAN = REPO / "tasks" / "phase3_todo.md"
OUT = REPO / "docs" / "FlightSim_Phase3_Guidelines.pdf"

TAGS = {
    "windows": "WINDOWS",
    "python": "PYTHON",
    "owner": "OWNER",
    "checkpoint": "CHECKPOINT",
}

CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: Inter, sans-serif; font-size: 8.6pt; line-height: 1.5;
       color: #1d2433; margin: 0; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 7.4pt;
       background: #eef1f6; color: #2a3a5c; padding: 0.5px 3px; border-radius: 2px; }
a { color: inherit; text-decoration: none; }
p { margin: 0 0 5px; }
ul, ol { margin: 2px 0 6px; padding-left: 16px; }
li { margin: 1.5px 0; break-inside: avoid; }
h2 { font-size: 12pt; color: #13284b; margin: 20px 0 8px; padding-bottom: 5px;
     border-bottom: 1.5px solid #c9d2e3; break-after: avoid; }
h3 { font-size: 9.6pt; color: #13284b; margin: 14px 0 5px; break-after: avoid; }
hr { border: 0; border-top: 1px dashed #d4dae5; margin: 14px 0; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 10px; font-size: 7.8pt; }
thead { display: table-header-group; }
th { background: #13284b; color: #fff; text-align: left; font-weight: 600;
     padding: 5px 7px; }
td { padding: 5px 7px; border-bottom: 1px solid #e3e7ef; vertical-align: top; }
tr:nth-child(even) td { background: #f6f8fb; }
tr { break-inside: avoid; }
ul.task-list, ul:has(> li > input) { list-style: none; padding-left: 2px; }
li > input[type=checkbox] { width: 9px; height: 9px; margin: 0 5px 0 0;
     vertical-align: -1px; accent-color: #13284b; }
.tag { display: inline-block; font-size: 5.6pt; font-weight: 700; letter-spacing: 0.08em;
       padding: 0.5px 4px; border-radius: 2px; vertical-align: 1px; margin: 0 1px; }
.tag.windows { background: #e1ecfb; color: #1f57a6; }
.tag.python { background: #def3e4; color: #1d7a3a; }
.tag.owner { background: #fdebd2; color: #a35a00; }
.tag.checkpoint { background: #ece4fb; color: #5b34a8; }
.cover { height: 255mm; display: flex; flex-direction: column; justify-content: center;
         padding: 0 6mm; break-after: page; }
.kicker { font-size: 7.5pt; letter-spacing: 0.22em; font-weight: 700; color: #1f57a6; }
.cover h1 { font-size: 28pt; color: #13284b; margin: 8px 0 12px; }
.lede { font-size: 10.5pt; color: #3a4357; max-width: 118mm; margin-bottom: 18px; }
.meta { border-left: 2.5px solid #13284b; padding: 2px 0 2px 10px; color: #4a5468;
        font-size: 7.8pt; margin-bottom: 18px; }
.meta div { margin: 2px 0; }
.legend div { margin: 4px 0; color: #3a4357; font-size: 7.6pt; }
.decision { background: #eef4fd; border-left: 3px solid #1f57a6; padding: 7px 10px;
            margin: 0 0 18px; font-size: 8.4pt; max-width: 130mm; }
.contents h2 { margin-top: 26px; }
.part { break-before: page; background: #13284b; color: #fff; border-radius: 4px;
        padding: 14px 16px 12px; margin-bottom: 14px; }
.part .kicker { color: #9fb6dc; font-size: 6.6pt; }
.part h1 { font-size: 15pt; margin: 4px 0 4px; }
.part p { color: #c9d4e8; font-size: 7.8pt; margin: 0; }
"""

FOOTER = (
    '<div style="width:100%;font-family:Inter,sans-serif;font-size:6.5px;color:#5a6478;'
    'padding:0 15mm;display:flex;justify-content:space-between;">'
    "<span>FlightSim · Phase 3 Guidelines · rev. 2</span>"
    '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'
)

PRINT_JS = """
const { chromium } = require('playwright');
(async () => {
  const [src, out, footer] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + src, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({ path: out, format: 'A4', printBackground: true,
    preferCSSPageSize: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>', footerTemplate: footer });
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def tag(kind: str) -> str:
    return f'<span class="tag {kind}">{TAGS[kind]}</span>'


def markdown_body(path: Path) -> str:
    """The file as HTML, without its own H1 (the Part banner replaces it)."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\A# [^\n]*\n", "", text)
    body = subprocess.run(
        ["pandoc", "-f", "gfm", "-t", "html", "--wrap=none"],
        input=text, capture_output=True, text=True, check=True).stdout
    body = body.replace("🪟", tag("windows")).replace("🐍", tag("python"))
    body = body.replace("[OWNER]", tag("owner"))
    body = re.sub(r"(<strong>)?\[CHECKPOINT\](</strong>)?", tag("checkpoint"), body)
    return body


def page() -> str:
    today = dt.date.today()
    date = f"{today.day} {today:%B %Y}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Phase 3 Guidelines</title>
<style>{CSS}</style></head><body>
<section class="cover">
  <div class="kicker">FLIGHTSIM · PHASE 3</div>
  <h1>Phase 3 Guidelines</h1>
  <div class="lede">Consolidation, component-level annotation, and a demonstration
  anyone can watch. The step-by-step plan and the guideline sheet, revision 2.</div>
  <div class="meta">
    <div>For Shashank Aitharaju · Dhruva Valluru</div>
    <div>Revision 2 · rebuilt {html.escape(date)} from <code>tasks/phase3_checklist.md</code>
    and <code>tasks/phase3_todo.md</code></div>
    <div>Built from: the Phase 3 requirements (13 Oct), the Windows review (24–25 Oct),
    and the A-4 model decode</div>
  </div>
  <div class="decision"><strong>Engine: Unreal Engine 5.7 (patch 5.7.4) on all three
  machines.</strong> Decided 2026-10-27 by the owner (A1, recorded in
  <code>docs/TOOLCHAIN.md</code>).</div>
  <div class="legend">
    <div>{tag("windows")} the check needs a Windows machine with the engine installed</div>
    <div>{tag("python")} Python-only work that may start while Phase A is open</div>
    <div>{tag("owner")} waits on a decision by Shashank or Dhruva</div>
    <div>{tag("checkpoint")} stop and re-verify before going on</div>
  </div>
  <div class="contents"><h2>Contents</h2><ol>
    <li><strong>Part 1 · The guideline sheet:</strong> tick-boxes in plain words, letters A–F, with the gates</li>
    <li><strong>Part 2 · The full implementation plan:</strong> every task with its files, what to do and how to verify it</li>
  </ol></div>
</section>
<section class="part"><div class="kicker">PART 1</div><h1>The guideline sheet</h1>
<p>Do the letters in order. Tick a box only when its check passes.</p></section>
{markdown_body(CHECKLIST)}
<section class="part"><div class="kicker">PART 2</div><h1>The full implementation plan</h1>
<p>Each task: the files it touches, what to do, and how to verify it.</p></section>
{markdown_body(PLAN)}
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--html", type=Path, help="also keep the intermediate HTML here")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(args.html or Path(tmp) / "phase3.html").resolve()
        src.write_text(page(), encoding="utf-8")
        js = Path(tmp) / "print.js"
        js.write_text(PRINT_JS, encoding="utf-8")
        subprocess.run(["node", str(js), str(src), str(args.out.resolve()), FOOTER],
                       check=True)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
