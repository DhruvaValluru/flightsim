"""Phase 3 definition of done, as tests.

One test per letter, marked ``gate`` and ``gate_<L>``. A letter is done when
``pytest -m gate_<L>`` passes on the Windows laptop and on CI. The checks
read only the repository, so they are the same on every machine:

- every box of the letter is ticked in ``tasks/phase3_checklist.md``, or its
  state file records ``verdict: cut`` (a decision), or the box is marked
  Optional on the sheet and its verdict starts with ``deferred``;
- every ticked box has a state file with ``verdict: PASS`` and a ``run_id``;
- every gate line of the letter is ticked on the sheet AND has a row in
  ``docs/phase3/gate_log_<L>.md`` whose Result starts with ``PASS`` or
  ``owner-pending`` (a row the pipeline cannot do, with its evidence text).

The suite excludes these by default (``-m "not gate"`` in pytest.ini); the
Windows letter tester and CI's gate job run them by name.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "tasks" / "phase3_checklist.md"
P3 = ROOT / "docs" / "phase3"

BOX_RE = re.compile(r"^- \[( |x|X)\] \*\*([A-F])(\d+) ·([^*]*)\*\*", re.M)
TICK_RE = re.compile(r"^- \[( |x|X)\] (.+)$")


def _sheet() -> str:
    return CHECKLIST.read_text(encoding="utf-8")


def boxes(letter: str) -> list[tuple[str, bool, str]]:
    """(box id, ticked, title) for every box of the letter."""
    out = []
    for m in BOX_RE.finditer(_sheet()):
        if m.group(2) == letter:
            out.append((m.group(2) + m.group(3), m.group(1).lower() == "x", m.group(4).strip()))
    return out


def gate_lines(letter: str) -> list[tuple[bool, str]]:
    """(ticked, text) for each line under the letter's GATE heading, or under
    'The six goals' for F, which has no GATE section on the sheet. A gate
    line may wrap onto indented continuation lines; they are joined."""
    lines = _sheet().splitlines()
    head = f"### GATE {letter}" if letter != "F" else "## The six goals"
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(head))
    except StopIteration:
        return []
    out: list[tuple[bool, str]] = []
    for l in lines[start + 1:]:
        if l.startswith("#"):
            break
        m = TICK_RE.match(l)
        if m:
            out.append((m.group(1).lower() == "x", m.group(2).strip()))
        elif l.startswith("  ") and out:
            t, txt = out[-1]
            out[-1] = (t, txt + " " + l.strip())
    return out


def state(box: str) -> dict:
    p = P3 / "state" / f"{box}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def gate_log_rows(letter: str) -> list[tuple[str, str, str]]:
    p = P3 / f"gate_log_{letter}.md"
    if not p.exists():
        return []
    rows = []
    for l in p.read_text(encoding="utf-8").splitlines():
        if l.startswith("|") and not l.startswith("|---") and not l.lower().startswith("| gate line"):
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            if len(cells) >= 3:
                rows.append((cells[0], cells[1], cells[2]))
    return rows


def letter_problems(letter: str) -> list[str]:
    problems = []
    bx = boxes(letter)
    assert bx, f"no boxes for letter {letter} on the sheet"
    for box, ticked, title in bx:
        st = state(box)
        verdict = str(st.get("verdict", ""))
        if ticked:
            if verdict != "PASS":
                problems.append(f"{box} is ticked but its state verdict is {verdict!r}, not PASS")
            if not st.get("run_id"):
                problems.append(f"{box} is ticked but its state has no run_id")
        elif verdict == "cut":
            continue
        elif "optional" in title.lower() and verdict.startswith("deferred"):
            continue
        else:
            problems.append(f"{box} is not ticked (state verdict {verdict!r})")
    gl = gate_lines(letter)
    assert gl, f"no gate lines for letter {letter} on the sheet"
    rows = gate_log_rows(letter)
    for ticked, text in gl:
        key = _norm(text)[:60]
        row = next((r for r in rows if _norm(r[0])[:60] == key), None)
        if row is None:
            problems.append(f"gate line has no row in gate_log_{letter}.md: {text[:80]}")
            continue
        result = row[1].lower()
        if not (result.startswith("pass") or result.startswith("owner-pending")):
            problems.append(f"gate line result is {row[1]!r}, needs PASS or owner-pending: {text[:60]}")
        if result.startswith("owner-pending") and not row[2].strip():
            problems.append(f"owner-pending gate line has no evidence text: {text[:60]}")
        if not ticked and result.startswith("pass"):
            problems.append(f"gate line passed in the log but is not ticked on the sheet: {text[:60]}")
    return problems


@pytest.mark.gate
@pytest.mark.gate_A
def test_gate_A():
    assert not letter_problems("A"), "\n".join(letter_problems("A"))


@pytest.mark.gate
@pytest.mark.gate_B
def test_gate_B():
    assert not letter_problems("B"), "\n".join(letter_problems("B"))


@pytest.mark.gate
@pytest.mark.gate_C
def test_gate_C():
    assert not letter_problems("C"), "\n".join(letter_problems("C"))


@pytest.mark.gate
@pytest.mark.gate_D
def test_gate_D():
    assert not letter_problems("D"), "\n".join(letter_problems("D"))


@pytest.mark.gate
@pytest.mark.gate_E
def test_gate_E():
    assert not letter_problems("E"), "\n".join(letter_problems("E"))


@pytest.mark.gate
@pytest.mark.gate_F
def test_gate_F():
    assert not letter_problems("F"), "\n".join(letter_problems("F"))


def test_sheet_parses():
    """Not a gate: the parser sees every letter and every GATE section."""
    for L in "ABCDEF":
        assert boxes(L), L
        assert gate_lines(L), L
