"""The independent reader of the tabular export (R3): ``frames.npz`` +
``frames.csv`` + ``columns.json`` back into columns, every cross-check
the three files allow made on the way.

INDEPENDENT BY CONSTRUCTION: this module imports the standard library
and numpy and nothing from ``core`` -- in particular nothing from the
writer (core/dataset/tabular.py), so a writer that drifts from its own
declared layout is caught here rather than agreed with (the verifier's
rule, core/capture/verify.py, applied to the export). A test reads this
file's imports and pins that.

What it checks, in order: the declared version; each data file's
sha256 against the one columns.json states; the npz holds exactly the
declared columns, each of the declared length and dtype kind; the CSV's
first row is the declared column names and its SECOND row the declared
units (the units row), every unit non-empty and not ``?``; the CSV
holds the declared number of rows; every CSV cell equals the npz value
(floats exactly, through ``repr``; NaN equals NaN); a source-rank column
holds only 0..6; a verdict column only the declared verdict words.
Any disagreement raises ``ValueError`` naming the file, the column and
the row.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Dict, List

#: The layout this reader understands (columns.json ``tabular_version``).
READS_VERSION = 1

#: The dtype words columns.json uses and the numpy kinds each may carry.
_KINDS = {"float": ("f",), "int": ("i",), "str": ("U",)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cell(text: str, dtype: str, where: str) -> Any:
    try:
        if dtype == "float":
            return float(text)
        if dtype == "int":
            return int(text)
    except ValueError as exc:
        raise ValueError(f"{where}: {text!r} is not a {dtype}") from exc
    return text


def _same(a: Any, b: Any, dtype: str) -> bool:
    if dtype == "float":
        a, b = float(a), float(b)
        return (math.isnan(a) and math.isnan(b)) or a == b
    if dtype == "int":
        return int(a) == int(b)
    return str(a) == str(b)


def read_tabular(directory) -> Dict[str, Any]:
    """The tabular export in ``directory``, read and cross-checked.

    Returns ``{"rows": n, "columns": [the declared column dicts],
    "units": {name: unit}, "arrays": {name: numpy array}, "csv":
    {name: [values]}}``; raises ``ValueError`` on any disagreement
    between the three files (see the module doc)."""
    import numpy as np

    directory = Path(directory)
    declared = json.loads((directory / "columns.json").read_text(encoding="utf-8"))
    if declared.get("tabular_version") != READS_VERSION:
        raise ValueError(f"the column declaration states version "
                         f"{declared.get('tabular_version')!r}; this reader reads {READS_VERSION}")
    columns: List[Dict[str, Any]] = list(declared.get("columns") or [])
    names = [str(c.get("name")) for c in columns]
    if len(set(names)) != len(names) or not names:
        raise ValueError("the column declaration names no columns, or a column twice")
    rows = int(declared.get("rows", -1))
    files = declared.get("files") or {}
    for file in ("frames.npz", "frames.csv"):
        stated = (files.get(file) or {}).get("sha256")
        actual = _sha256(directory / file)
        if stated != actual:
            raise ValueError(f"{file} hashes to {actual[:12]}, the declaration states "
                             f"{str(stated)[:12]}: the file changed after it was declared")
    units: Dict[str, str] = {}
    for column in columns:
        unit = column.get("unit")
        if not isinstance(unit, str) or not unit.strip() or unit.strip() == "?":
            raise ValueError(f"column {column.get('name')!r} declares no unit ({unit!r})")
        if column.get("dtype") not in _KINDS:
            raise ValueError(f"column {column.get('name')!r} declares dtype {column.get('dtype')!r}")
        units[str(column["name"])] = unit
    arrays: Dict[str, Any] = {}
    with np.load(directory / "frames.npz", allow_pickle=False) as data:
        held = sorted(data.files)
        if held != sorted(names):
            missing = sorted(set(names) - set(held))
            extra = sorted(set(held) - set(names))
            raise ValueError(f"the npz holds other columns than declared (missing {missing[:5]}, "
                             f"undeclared {extra[:5]})")
        for column in columns:
            array = np.asarray(data[column["name"]])
            if array.ndim != 1 or len(array) != rows:
                raise ValueError(f"npz column {column['name']!r} has shape {array.shape}, "
                                 f"declared ({rows},)")
            if array.dtype.kind not in _KINDS[column["dtype"]]:
                raise ValueError(f"npz column {column['name']!r} is numpy kind "
                                 f"{array.dtype.kind!r}, declared {column['dtype']}")
            arrays[column["name"]] = array
    text = (directory / "frames.csv").read_text(encoding="utf-8")
    table = list(csv.reader(io.StringIO(text)))
    if len(table) < 2:
        raise ValueError("the CSV lacks its header and units rows")
    if table[0] != names:
        raise ValueError("the CSV's header row is not the declared column names in order")
    if table[1] != [units[n] for n in names]:
        bad = [n for n, u in zip(names, table[1]) if units.get(n) != u]
        raise ValueError(f"the CSV's units row disagrees with the declaration at "
                         f"{bad[:5] or 'its length'}")
    body = table[2:]
    if len(body) != rows:
        raise ValueError(f"the CSV holds {len(body)} data rows, declared {rows}")
    parsed: Dict[str, List[Any]] = {n: [] for n in names}
    ranks = set(range(0, 7))
    verdicts = set(declared.get("verdicts") or ())
    for r, line in enumerate(body):
        if len(line) != len(names):
            raise ValueError(f"CSV row {r} has {len(line)} cells, declared {len(names)}")
        for column, cell in zip(columns, line):
            name, dtype = column["name"], column["dtype"]
            where = f"CSV row {r} column {name!r}"
            value = _cell(cell, dtype, where)
            if not _same(value, arrays[name][r].item(), dtype):
                raise ValueError(f"{where} reads {cell!r}, the npz holds {arrays[name][r]!r}")
            if column.get("kind") == "source_rank" and value not in ranks:
                raise ValueError(f"{where}: a source rank outside 0..6 ({value!r})")
            if column.get("kind") == "null_verdict" and verdicts and value not in verdicts:
                raise ValueError(f"{where}: {value!r} is not a declared verdict word")
            parsed[name].append(value)
    return {"rows": rows, "columns": columns, "units": units, "arrays": arrays, "csv": parsed}
