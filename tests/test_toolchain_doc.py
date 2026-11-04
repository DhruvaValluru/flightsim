"""docs/TOOLCHAIN.md: one row per machine, every filled row on the pinned
engine (Phase 3 A1). Rows other machines have not filled yet read
"pending" and are tolerated here; Gate A cross-checks all three."""

import re
from pathlib import Path

from core.util import platform as plat

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "TOOLCHAIN.md"


def _rows():
    """The machine rows of the table as dicts keyed by the header cells."""
    header, rows = None, []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        elif not set("".join(cells)) <= set("-: "):
            rows.append(dict(zip(header, cells)))
    return rows


def _engine(row):
    return next(v for k, v in row.items() if k.startswith("Engine"))


def _pending(row):
    return "pending" in _engine(row).lower()


def test_every_filled_row_names_the_pinned_engine():
    rows = _rows()
    assert rows, "docs/TOOLCHAIN.md has no machine rows"
    full = f"{plat.UE_ENGINE_VERSION}.{plat.UE_ENGINE_PATCH}"
    for row in rows:
        if _pending(row):
            continue
        assert _engine(row).startswith(full), (
            f"{row['Machine']!r}: engine {_engine(row)!r} is not {full}")


def test_decision_line_is_dated():
    assert re.search(r"\*\*Decision, \d{4}-\d{2}-\d{2}",
                     DOC.read_text(encoding="utf-8"))
