"""The campaign ledger: one JSON line per event, append-only, keyed
on the case index (contracts §6.1).

The batch ledger (``core.experiments.sweep.ResultLog``) is the model:
flushed per line, tolerant of a truncated last line, never rewritten.
The campaign keeps every batch row key and adds ``index`` and
``status``; the LATEST row for an index is that slot's state, and
everything the campaign says about itself -- progress, yield,
refusals, whether it may call itself done -- is computed from these
rows by :func:`summarise`, never from a counter in memory. A process
that restarts reads the same truth the one before it wrote.

Not claimed: the ledger is one writer per campaign directory (the
process running the campaign); two processes appending to one ledger
are not detected here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

LEDGER = "ledger.jsonl"

#: The per-index states, in pipeline order (contracts §6.1).
STATUS_SAMPLED = "sampled"
STATUS_REFUSED = "refused"
STATUS_RUNNING = "running"
STATUS_RENDERED = "rendered"
STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"
STATUSES = (STATUS_SAMPLED, STATUS_REFUSED, STATUS_RUNNING, STATUS_RENDERED,
            STATUS_VERIFIED, STATUS_FAILED)

#: Row keys that carry time or a machine-local path: what two ledgers
#: of one campaign at different worker counts are allowed to differ in.
TIMING_KEYS = ("wall_seconds", "started_utc", "finished_utc", "bytes")
PATH_KEYS = ("run_dir", "command")


class Ledger:
    """Append-only JSONL, flushed and fsynced per line."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: Dict[str, Any]) -> None:
        line = json.dumps(row, sort_keys=True, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass

    def rows(self) -> List[Dict[str, Any]]:
        """Every complete row in file order; a truncated final line
        (a process killed mid-write) is dropped, never fatal."""
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
        return out

    def latest(self) -> Dict[int, Dict[str, Any]]:
        """{index: the last row written for it}."""
        return latest_by_index(self.rows())

    def truncate(self) -> None:
        if self.path.exists():
            self.path.unlink()


def latest_by_index(rows: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    latest: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        index = row.get("index")
        if isinstance(index, int) and not isinstance(index, bool):
            latest[index] = row
    return latest


def summarise(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Progress and yield FROM THE ROWS: counts per status over the
    latest row of every index, verified frames (the yield), captured
    frames, refusals by name (refused slots and the refused attempts
    inside successful draws), the next free index, timing totals."""
    latest = latest_by_index(rows)
    counts = {status: 0 for status in STATUSES}
    frames_verified = frames_captured = 0
    refusals: Dict[str, int] = {}
    wall = 0.0
    bytes_measured: List[int] = []
    verified_dirs: List[str] = []
    failed_captures = unverified = 0
    for index in sorted(latest):
        row = latest[index]
        status = str(row.get("status", ""))
        if status in counts:
            counts[status] += 1
        for name in row.get("refusals") or []:
            refusals[str(name)] = refusals.get(str(name), 0) + 1
        if status == STATUS_VERIFIED:
            frames_verified += int(row.get("yield") or 0)
            if row.get("run_dir"):
                verified_dirs.append(str(row["run_dir"]))
        if row.get("ok"):
            frames_captured += int(row.get("frames") or 0)
            if isinstance(row.get("bytes"), int):
                bytes_measured.append(int(row["bytes"]))
            if not row.get("verified"):
                unverified += 1
        elif status == STATUS_FAILED:
            failed_captures += 1
        if isinstance(row.get("wall_seconds"), (int, float)):
            wall += float(row["wall_seconds"])
    return {
        "indices": len(latest),
        "next_index": (max(latest) + 1) if latest else 0,
        "cases": counts,
        "frames_verified": frames_verified,
        "frames_captured": frames_captured,
        "refusals": dict(sorted(refusals.items())),
        "failed_captures": failed_captures,
        "unverified": unverified,
        "wall_seconds": round(wall, 3),
        "bytes_per_case": (int(sum(bytes_measured) / len(bytes_measured))
                           if bytes_measured else None),
        "bytes_measured_over": len(bytes_measured),
        "verified_run_dirs": verified_dirs,
    }


def comparable(rows: Iterable[Dict[str, Any]],
               drop: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """The rows with timing and path keys removed, sorted by (index,
    status order, case id): what two ledgers of one campaign must agree
    on regardless of worker count (the exit criterion's comparison)."""
    dropped = set(TIMING_KEYS) | set(PATH_KEYS) | set(drop or ())
    order = {status: i for i, status in enumerate(STATUSES)}
    out = [{k: v for k, v in row.items() if k not in dropped} for row in rows]
    out.sort(key=lambda r: (int(r.get("index", -1)),
                            order.get(str(r.get("status")), 99),
                            str(r.get("case_id", "")),
                            json.dumps(r, sort_keys=True, default=str)))
    return out
