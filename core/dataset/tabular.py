"""The tabular export (ADVANCEMENTS_BLUEPRINT section 2, work item R3):
one row per exported frame, one column per recorded quantity, with a
unit stated for every column.

Three files, written into one directory:

* ``frames.npz`` -- one 1-D array per column (float64, int64 or unicode),
  a zip of ``.npy`` members sorted by name with fixed timestamps and no
  compression, so the same export gives the same bytes;
* ``frames.csv`` -- the same table as text: the column names, then a
  UNITS ROW (every column's unit; nothing is unitless by omission), then
  one line per frame; floats through ``repr`` so they read back exactly,
  NaN as ``nan``;
* ``columns.json`` -- the declaration: version, row count, each
  column's name / unit / dtype / kind / description, the source-rank
  and verdict vocabularies, and the sha256 of the two data files.

The columns, in order:

* identifiers: ``key`` (the export's sample key), ``run``, ``camera_id``
  (unit ``id``), ``frame_index`` (``1``), ``t_s`` (``s``), ``split``
  (``id``) when the export assigned one;
* ``applied__<name>``: every applied variable any run records, its value
  (a number; a non-number as its JSON text, unit the record's), NaN /
  empty where the run does not carry it;
* ``applied__<name>__source``: the provenance rank of that value, 0..5 by
  the spec's precedence (user 0, inferred 1, sampled 2, model 3, derived
  4, default 5) and 6 when the run does not carry the variable (unit
  ``rank``);
* ``null__<name>__verdict``: the record's null-test verdict word
  (reached / silent / bounded / exceeded / ungraded / absent; unit
  ``category``);
* ``u_num__<srq>``: the run's numerical uncertainty per system response
  quantity (the dt/2 twin's GCI; NaN when the run flew no twin);
* ``state__<channel>``: every channel of the frame's recorded state, its
  unit the manifest's ``state_units`` (the registry first, then the
  suffix convention);
* ``label__*``: the 2-D labels of the frame's primary object in the
  exported image's pixels (the clipped box corners, truncation, in-frame
  flag, the count of keypoints in frame).

REFUSED -- ``export.tabular_units``: a column whose unit is empty or
``?`` (a state channel no convention names), or a column whose runs
state two different units. A table with a column nobody can read the
unit of is not written.

The reader is :mod:`core.dataset.tabular_read` (imports nothing from
here); :func:`write_tabular` returns the declaration it wrote.

NOT claimed: the table is a flattening of the manifests, nothing is
recomputed; a string-valued variable is carried as its JSON text; no
PROV-O or Croissant description is written (the identifiers -- run,
spec digest, variable name -- are stable so a later exporter needs no
new column).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.records import SOURCES

from .export import ExportError, sample_split

TABULAR_VERSION = 1
FRAMES_NPZ = "frames.npz"
FRAMES_CSV = "frames.csv"
COLUMNS_JSON = "columns.json"

#: The provenance rank of each source word, and of a variable a run lacks.
SOURCE_RANK: Dict[str, int] = {source: rank for rank, source in enumerate(SOURCES)}
ABSENT_RANK = len(SOURCES)

#: The units the table states for the columns that carry no physical unit.
UNIT_ID = "id"
UNIT_RANK = "rank"
UNIT_CATEGORY = "category"
UNIT_COUNT = "1"

#: The primary label columns: (column, unit, description).
LABEL_COLUMNS = (
    ("label__bbox_x0_px", "px", "the clipped 2-D box's left edge (NaN out of frame)"),
    ("label__bbox_y0_px", "px", "the clipped 2-D box's top edge"),
    ("label__bbox_x1_px", "px", "the clipped 2-D box's right edge"),
    ("label__bbox_y1_px", "px", "the clipped 2-D box's bottom edge"),
    ("label__truncation", UNIT_COUNT, "the fraction of the unclipped box outside the image"),
    ("label__in_frame", UNIT_COUNT, "1 when the object is in the image, else 0"),
    ("label__keypoints_in_frame", UNIT_COUNT, "the number of keypoints inside the image"),
)


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _deterministic_npz(arrays: Mapping[str, Any]) -> bytes:
    import numpy as np

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(arrays):
            member = io.BytesIO()
            np.lib.format.write_array(member, np.ascontiguousarray(arrays[name]),
                                      allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, member.getvalue())
    return buffer.getvalue()


def _unit_ok(unit: Any) -> bool:
    return isinstance(unit, str) and bool(unit.strip()) and unit.strip() != "?"


def _refuse_units(problems: List[str]) -> None:
    if problems:
        raise ExportError(
            "export.tabular_units",
            f"{len(problems)} column(s) of the table carry no readable unit, so the "
            f"table is not written: " + "; ".join(problems[:8]))


class _Run:
    """What the table reads from one run: its records by name, their
    verdicts, and its u_num per SRQ (both records: the capture manifest's
    block first, then any name only run.json carries)."""

    def __init__(self, run) -> None:
        from core.campaign.report import null_verdict, run_documents, run_records

        documents = run_documents(run.directory)
        documents["manifest"] = run.manifest
        self.records = {r["name"]: r for r in run_records(run.directory, documents)}
        self.verdicts = {name: null_verdict(r) for name, r in self.records.items()}
        block = None
        for key in ("manifest", "run"):
            if isinstance(documents[key].get("uncertainty"), dict):
                block = documents[key]["uncertainty"]
                break
        srqs = ((block or {}).get("u_num") or {}).get("srq") or {}
        self.u_num = {srq: (float(e["value"]) if isinstance(e, dict) and _is_number(e.get("value"))
                            else math.nan) for srq, e in srqs.items()}


def tabular_table(samples: Sequence[Any], splits: Optional[Mapping[str, str]] = None
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Any]]]:
    """The declared columns and the column values for ``samples`` (the
    export's :class:`core.dataset.export.Sample` list), in key order.
    Refuses ``export.tabular_units`` before anything is written."""
    from core.uncertainty import SRQ_UNITS, SRQS

    ordered = sorted(samples, key=lambda s: s.key)
    runs: Dict[str, _Run] = {}
    for sample in ordered:
        if sample.run.name not in runs:
            runs[sample.run.name] = _Run(sample.run)
    columns: List[Dict[str, Any]] = []
    values: Dict[str, List[Any]] = {}
    problems: List[str] = []

    def column(name: str, unit: str, dtype: str, kind: str, description: str,
               cells: List[Any]) -> None:
        if not _unit_ok(unit):
            problems.append(f"{name} has unit {unit!r}")
        columns.append({"name": name, "unit": unit, "dtype": dtype, "kind": kind,
                        "description": description})
        values[name] = cells

    column("key", UNIT_ID, "str", "identifier", "the export's sample key",
           [s.key for s in ordered])
    column("run", UNIT_ID, "str", "identifier", "the run directory's name",
           [s.run.name for s in ordered])
    column("camera_id", UNIT_ID, "str", "identifier", "the camera the frame was taken by",
           [str(s.record.get("camera_id")) for s in ordered])
    column("frame_index", UNIT_COUNT, "int", "identifier", "the frame's index in its camera",
           [int(s.record.get("index", -1)) for s in ordered])
    column("t_s", "s", "float", "identifier", "the frame's time in the flight",
           [float(s.record["t_s"]) if _is_number(s.record.get("t_s")) else math.nan
            for s in ordered])
    if splits is not None:
        column("split", UNIT_ID, "str", "identifier", "the split the export assigned",
               [sample_split(s, dict(splits)) for s in ordered])

    # -- the applied variables, their source rank and their null verdict --
    names = sorted({name for run in runs.values() for name in run.records})
    for name in names:
        present = [run.records[name] for run in runs.values() if name in run.records]
        units: Dict[str, int] = {}
        for record in present:
            unit = str(record.get("unit", ""))
            units[unit] = units.get(unit, 0) + 1
        if len(units) > 1:
            problems.append(f"applied__{name} is recorded in {sorted(units)} by different runs")
        unit = sorted(units, key=lambda u: (-units[u], u))[0]
        numeric = all(_is_number(r.get("value")) or r.get("value") is None for r in present)
        cells: List[Any] = []
        for sample in ordered:
            record = runs[sample.run.name].records.get(name)
            value = None if record is None else record.get("value")
            if numeric:
                cells.append(float(value) if _is_number(value) else math.nan)
            else:
                cells.append("" if record is None else
                             value if isinstance(value, str) else json.dumps(value, sort_keys=True))
        column(f"applied__{name}", unit, "float" if numeric else "str", "applied_value",
               f"the applied value of {name} (core/records.py)", cells)
        column(f"applied__{name}__source", UNIT_RANK, "int", "source_rank",
               f"the provenance rank of {name}: user 0 .. default 5, 6 absent",
               [SOURCE_RANK.get(str((runs[s.run.name].records.get(name) or {}).get("source")),
                                ABSENT_RANK) if name in runs[s.run.name].records else ABSENT_RANK
                for s in ordered])
        column(f"null__{name}__verdict", UNIT_CATEGORY, "str", "null_verdict",
               f"the verdict of {name}'s null test",
               [runs[s.run.name].verdicts.get(name, "absent") for s in ordered])

    # -- the run's numerical uncertainty per SRQ --
    for srq in SRQS:
        column(f"u_num__{srq}", SRQ_UNITS[srq], "float", "u_num",
               f"the run's u_num for {srq} (dt/2 twin GCI; NaN when not flown)",
               [runs[s.run.name].u_num.get(srq, math.nan) for s in ordered])

    # -- the frame's recorded state, with the manifest's units --
    channel_units: Dict[str, Dict[str, int]] = {}
    for sample in ordered:
        declared = sample.run.manifest.get("state_units") or {}
        for channel in (sample.record.get("state") or {}):
            unit = str(declared.get(channel, ""))
            slot = channel_units.setdefault(channel, {})
            slot[unit] = slot.get(unit, 0) + 1
    for channel in sorted(channel_units):
        units = channel_units[channel]
        if len(units) > 1:
            problems.append(f"state__{channel} is stated in {sorted(units)} by different runs")
        unit = sorted(units, key=lambda u: (-units[u], u))[0]
        cells = []
        for sample in ordered:
            value = (sample.record.get("state") or {}).get(channel)
            cells.append(float(value) if isinstance(value, (int, float))
                         and not isinstance(value, bool) else math.nan)
        column(f"state__{channel}", unit, "float", "state",
               f"the recorded channel {channel} at the frame's sample", cells)

    # -- the primary object's 2-D labels --
    boxes = [s.labels.get("bbox_2d") if isinstance(s.labels, dict) else None for s in ordered]
    for i, (name, unit, description) in enumerate(LABEL_COLUMNS[:4]):
        column(name, unit, "float", "label", description,
               [float(b[i]) if b else math.nan for b in boxes])
    name, unit, description = LABEL_COLUMNS[4]
    column(name, unit, "float", "label", description,
           [float(s.labels["truncation"]) if _is_number(s.labels.get("truncation")) else math.nan
            for s in ordered])
    name, unit, description = LABEL_COLUMNS[5]
    column(name, unit, "int", "label", description,
           [1 if s.labels.get("in_frame") else 0 for s in ordered])
    name, unit, description = LABEL_COLUMNS[6]
    column(name, unit, "int", "label", description,
           [sum(1 for kp in (s.labels.get("keypoints") or {}).values()
                if isinstance(kp, dict) and kp.get("in_frame")) for s in ordered])
    _refuse_units(problems)
    return columns, values


def _csv_cell(value: Any, dtype: str) -> str:
    if dtype == "float":
        return repr(float(value))
    if dtype == "int":
        return str(int(value))
    return str(value)


def write_tabular(samples: Sequence[Any], out, splits: Optional[Mapping[str, str]] = None
                  ) -> Dict[str, Any]:
    """Write ``frames.npz``, ``frames.csv`` and ``columns.json`` into
    ``out`` for ``samples``; returns the declaration (columns.json).
    Refuses ``export.tabular_units`` before any file is written."""
    import numpy as np

    columns, values = tabular_table(samples, splits)
    rows = len(next(iter(values.values()))) if values else 0
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    arrays: Dict[str, Any] = {}
    for c in columns:
        cells = values[c["name"]]
        if c["dtype"] == "float":
            arrays[c["name"]] = np.asarray(cells, dtype=np.float64)
        elif c["dtype"] == "int":
            arrays[c["name"]] = np.asarray(cells, dtype=np.int64)
        else:
            arrays[c["name"]] = np.asarray([str(v) for v in cells], dtype=np.str_) \
                if cells else np.zeros(0, dtype="<U1")
    npz = _deterministic_npz(arrays)
    (out / FRAMES_NPZ).write_bytes(npz)
    text = io.StringIO()
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow([c["name"] for c in columns])
    writer.writerow([c["unit"] for c in columns])      # the units row
    for r in range(rows):
        writer.writerow([_csv_cell(values[c["name"]][r], c["dtype"]) for c in columns])
    payload = text.getvalue().encode("utf-8")
    (out / FRAMES_CSV).write_bytes(payload)
    declaration = {
        "tabular_version": TABULAR_VERSION,
        "rows": rows,
        "files": {FRAMES_NPZ: {"sha256": hashlib.sha256(npz).hexdigest(), "bytes": len(npz)},
                  FRAMES_CSV: {"sha256": hashlib.sha256(payload).hexdigest(),
                               "bytes": len(payload)}},
        "csv_layout": "row 1 the column names, row 2 the units, then one row per frame; "
                      "floats by repr (exact), NaN as nan",
        "source_rank": {**SOURCE_RANK, "absent": ABSENT_RANK},
        "verdicts": ["reached", "silent", "bounded", "exceeded", "ungraded", "absent"],
        "columns": columns,
        "reader": "core.dataset.tabular_read.read_tabular (imports nothing from the writer)",
        "not_claimed": [
            "a flattening of the manifests: nothing is recomputed",
            "a variable whose value is not a number is carried as its JSON text",
            "no PROV-O or Croissant description; the identifiers are stable for a later one",
        ],
    }
    (out / COLUMNS_JSON).write_text(json.dumps(declaration, indent=1), encoding="utf-8")
    return declaration
