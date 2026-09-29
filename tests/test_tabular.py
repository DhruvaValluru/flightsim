"""R3: the tabular export -- frames.npz + frames.csv with a units row +
columns.json -- round-tripped through an independent reader, over a
two-case headless campaign plus a copy of one case that lacks the
user-stated variable and the uncertainty block (the absent rank and the
NaN). Expected values are read here from the cases' files with json.
"""

import ast
import csv
import hashlib
import io
import json
import math
import shutil
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pytest

from core.dataset import tabular
from core.dataset.export import (
    ExportError, assign_splits, bind_verification, collect_samples, export, load_run,
)
from core.dataset.tabular import (
    ABSENT_RANK, COLUMNS_JSON, FRAMES_CSV, FRAMES_NPZ, SOURCE_RANK, tabular_table,
    write_tabular,
)
from core.dataset.tabular_read import read_tabular

from tests.test_campaign_report import VARIABLE, case_dirs, two_case_campaign

READER = Path(__file__).resolve().parents[1] / "core" / "dataset" / "tabular_read.py"


def _strip(run_dir: Path, variable: str) -> None:
    """The case without ``variable``'s record and without its uncertainty
    block, in both records; the verdict rebound to the edited manifest."""
    for name in ("capture_manifest.json", "run.json"):
        data = json.loads((run_dir / name).read_text(encoding="utf-8"))
        block = data.get("applied_variables") or {}
        block["applied_variables"] = [r for r in block.get("applied_variables", [])
                                      if r["name"] != variable]
        data.pop("uncertainty", None)
        (run_dir / name).write_text(json.dumps(data, indent=1), encoding="utf-8")
    bind_verification(run_dir)


@pytest.fixture(scope="module")
def dirs(tmp_path_factory):
    root = tmp_path_factory.mktemp("tabular")
    campaign = two_case_campaign(root / "c")
    cases = case_dirs(campaign)
    absent = root / "absent_case"
    shutil.copytree(cases[0], absent)
    _strip(absent, VARIABLE)
    return cases + [absent]


@pytest.fixture(scope="module")
def table(dirs, tmp_path_factory):
    runs = [load_run(d) for d in dirs]
    samples = collect_samples(runs, labels_only=True)
    splits = assign_splits(samples, (0.5, 0.5, 0.0), 1)
    out = tmp_path_factory.mktemp("table")
    declaration = write_tabular(samples, out, splits)
    return {"out": out, "declaration": declaration, "samples": samples, "splits": splits}


def _expected_rows(dirs):
    """(key, run dir, frame record) per frame, in key order, from json."""
    rows = []
    for d in dirs:
        manifest = json.loads((d / "capture_manifest.json").read_text(encoding="utf-8"))
        for frame in manifest["frames"]:
            rows.append((f"{d.name}_{frame['camera_id']}_{int(frame['index']):04d}", d, frame))
    return sorted(rows, key=lambda r: r[0])


def _records(d):
    manifest = json.loads((d / "capture_manifest.json").read_text(encoding="utf-8"))
    return {r["name"]: r for r in manifest["applied_variables"]["applied_variables"]}


def _same(a, b):
    return (isinstance(a, float) and math.isnan(a) and math.isnan(b)) or a == b


def test_the_table_round_trips_through_the_independent_reader(dirs, table):
    """R-REC-04: every cell the reader returns is the value the cases'
    files hold: applied values, their source ranks (0..5, 6 absent), the
    null verdicts, u_num, the recorded state and the labels."""
    got = read_tabular(table["out"])
    a = got["arrays"]
    expected = _expected_rows(dirs)
    assert got["rows"] == len(expected) == table["declaration"]["rows"]
    assert list(a["key"]) == [k for k, _, _ in expected]
    for i, (key, d, frame) in enumerate(expected):
        records = _records(d)
        run_json = json.loads((d / "run.json").read_text(encoding="utf-8"))
        stated = records.get(VARIABLE)
        assert _same(float(a[f"applied__{VARIABLE}"][i]),
                     float(stated["value"]) if stated else math.nan), key
        assert int(a[f"applied__{VARIABLE}__source"][i]) == (0 if stated else ABSENT_RANK)
        assert int(a["applied__instruments.profile__source"][i]) == SOURCE_RANK["default"] == 5
        assert str(a["applied__instruments.profile"][i]) == records["instruments.profile"]["value"]
        verdict = stated["null_test"]["verdict"] if stated else "absent"
        assert str(a[f"null__{VARIABLE}__verdict"][i]) == verdict
        u = run_json.get("uncertainty")
        assert _same(float(a["u_num__altitude_m"][i]),
                     u["u_num"]["srq"]["altitude_m"]["value"] if u else math.nan)
        for channel, value in frame["state"].items():
            assert float(a[f"state__{channel}"][i]) == float(value), (key, channel)
        box = frame["labels"]["bbox_2d"]
        assert _same(float(a["label__bbox_x0_px"][i]), float(box[0]) if box else math.nan)
        assert int(a["label__in_frame"][i]) == (1 if frame["labels"]["in_frame"] else 0)
        assert str(a["split"][i]) in ("train", "val")
    # The CSV says the same as the npz, cell for cell (the reader checked it).
    assert got["csv"]["key"] == [k for k, _, _ in expected]


def test_the_units_row_states_every_columns_unit(dirs, table):
    """R-REC-04: row 2 of the CSV is the units row: one unit per column,
    none empty or '?', equal to columns.json, the state channels' units
    equal to the manifest's state_units."""
    text = (table["out"] / FRAMES_CSV).read_text(encoding="utf-8")
    header, units = list(csv.reader(io.StringIO(text)))[:2]
    declared = json.loads((table["out"] / COLUMNS_JSON).read_text(encoding="utf-8"))
    assert header == [c["name"] for c in declared["columns"]]
    assert units == [c["unit"] for c in declared["columns"]]
    assert all(u.strip() and u != "?" for u in units)
    by_name = dict(zip(header, units))
    manifest = json.loads((dirs[0] / "capture_manifest.json").read_text(encoding="utf-8"))
    for channel, unit in manifest["state_units"].items():
        assert by_name[f"state__{channel}"] == unit
    assert by_name[f"applied__{VARIABLE}"] == _records(dirs[0])[VARIABLE]["unit"]
    assert by_name[f"applied__{VARIABLE}__source"] == "rank"
    assert by_name["u_num__altitude_m"] == "m" and by_name["label__bbox_x0_px"] == "px"
    assert declared["source_rank"] == {"user": 0, "inferred": 1, "sampled": 2, "model": 3,
                                       "derived": 4, "default": 5, "absent": 6}


def test_the_files_are_the_same_bytes_every_time(table, tmp_path):
    """R-REC-04: the npz has fixed timestamps and the CSV is exact text, so
    the same export is the same bytes."""
    again = write_tabular(table["samples"], tmp_path / "again", table["splits"])
    assert again == table["declaration"]
    for name in (FRAMES_NPZ, FRAMES_CSV, COLUMNS_JSON):
        assert (tmp_path / "again" / name).read_bytes() == (table["out"] / name).read_bytes()


def test_the_reader_imports_nothing_from_the_writer():
    """R-REC-04: the reader's imports are the standard library and numpy;
    nothing from core, nothing relative."""
    tree = ast.parse(READER.read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import in the reader"
            modules.add(node.module.split(".")[0])
    assert modules <= {"__future__", "csv", "hashlib", "io", "json", "math", "pathlib",
                       "typing", "numpy"}, modules


def _rehash(out: Path) -> None:
    """What a drifting writer would do: declare the files it wrote."""
    declared = json.loads((out / COLUMNS_JSON).read_text(encoding="utf-8"))
    for name in (FRAMES_NPZ, FRAMES_CSV):
        declared["files"][name]["sha256"] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    (out / COLUMNS_JSON).write_text(json.dumps(declared), encoding="utf-8")


def test_the_reader_catches_a_writer_that_drifts(table, tmp_path, monkeypatch):
    """R-REC-04: a lossy float in the CSV, a wrong unit in the units row, a
    rank outside 0..6 and a file edited after it was declared -- each is a
    ValueError from the reader, not a quiet agreement."""
    # A writer mutation: floats printed to six figures instead of exactly.
    monkeypatch.setattr(tabular, "_csv_cell",
                        lambda v, dtype: f"{float(v):.6g}" if dtype == "float" else
                        (str(int(v)) if dtype == "int" else str(v)))
    write_tabular(table["samples"], tmp_path / "lossy", table["splits"])
    monkeypatch.undo()
    with pytest.raises(ValueError, match="the npz holds"):
        read_tabular(tmp_path / "lossy")

    def copy(name):
        shutil.copytree(table["out"], tmp_path / name)
        return tmp_path / name

    units = copy("units")
    lines = (units / FRAMES_CSV).read_text(encoding="utf-8").split("\n")
    lines[1] = lines[1].replace("px", "m", 1)
    (units / FRAMES_CSV).write_text("\n".join(lines), encoding="utf-8")
    _rehash(units)
    with pytest.raises(ValueError, match="units row"):
        read_tabular(units)

    rank = copy("rank")
    column = f"applied__{VARIABLE}__source"
    with np.load(rank / FRAMES_NPZ, allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    arrays[column] = np.full_like(arrays[column], 7)
    (rank / FRAMES_NPZ).write_bytes(tabular._deterministic_npz(arrays))
    rows = list(csv.reader(io.StringIO((rank / FRAMES_CSV).read_text(encoding="utf-8"))))
    index = rows[0].index(column)
    for row in rows[2:]:
        row[index] = "7"
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    (rank / FRAMES_CSV).write_text(buffer.getvalue(), encoding="utf-8")
    _rehash(rank)
    with pytest.raises(ValueError, match="source rank outside"):
        read_tabular(rank)

    stale = copy("stale")
    with zipfile.ZipFile(stale / FRAMES_NPZ, "a") as zf:
        zf.writestr("extra.npy", b"")
    with pytest.raises(ValueError, match="changed after it was declared"):
        read_tabular(stale)
    read_tabular(table["out"])                      # the untouched export still reads


def test_a_column_without_a_unit_refuses_by_name_before_any_file(dirs, table, tmp_path):
    """R-REC-04: a state channel whose unit is '?' (or two units for one
    column across runs) refuses export.tabular_units; the export writes
    nothing."""
    runs = [load_run(d) for d in dirs]
    runs[0].manifest["state_units"]["altitude_m"] = "?"
    with pytest.raises(ExportError) as err:
        tabular_table(collect_samples(runs, labels_only=True))
    assert err.value.constraint == "export.tabular_units" and "altitude_m" in err.value.message
    runs = [load_run(d) for d in dirs]
    runs[0].manifest["state_units"]["altitude_m"] = "ft"
    with pytest.raises(ExportError) as err:
        tabular_table(collect_samples(runs, labels_only=True))
    assert err.value.constraint == "export.tabular_units"
    # Through export(): nothing is written, not even the format.
    bad = tmp_path / "bad_case"
    shutil.copytree(dirs[0], bad)
    manifest = json.loads((bad / "capture_manifest.json").read_text(encoding="utf-8"))
    manifest["state_units"]["altitude_m"] = "?"
    (bad / "capture_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    bind_verification(bad)
    with pytest.raises(ExportError) as err:
        export([bad], tmp_path / "out", "coco", labels_only=True, tabular=True)
    assert err.value.constraint == "export.tabular_units"
    assert not (tmp_path / "out").exists()


def test_the_export_writes_the_table_and_the_card_names_it(dirs, tmp_path):
    """R-REC-04: export(..., tabular=True) writes tabular/ beside the format
    and the card declares its rows, columns and hashes."""
    card = export(dirs, tmp_path / "ds", "coco", labels_only=True, tabular=True)
    got = read_tabular(tmp_path / "ds" / "tabular")
    assert card["tabular"]["rows"] == got["rows"] == card["frames"]
    assert card["tabular"]["columns"] == len(got["columns"])
    assert card["tabular"]["files"][FRAMES_NPZ] == hashlib.sha256(
        (tmp_path / "ds" / "tabular" / FRAMES_NPZ).read_bytes()).hexdigest()
    assert "## Tabular" in (tmp_path / "ds" / "DATASET_CARD.md").read_text(encoding="utf-8")


def test_the_webdataset_sidecar_carries_export_applied(dirs, tmp_path):
    """R-REC-04: every WebDataset sample's sidecar gains export.applied --
    the run's applied variables (value, unit, source), read here from the
    manifest."""
    export(dirs, tmp_path / "wds", "webdataset", labels_only=True, fractions=(1.0, 0.0, 0.0))
    shards = sorted((tmp_path / "wds").rglob("*.tar"))
    seen = 0
    for shard in shards:
        with tarfile.open(shard) as tar:
            for member in tar.getmembers():
                if not member.name.endswith(".json"):
                    continue
                sidecar = json.loads(tar.extractfile(member).read())
                run = next(d for d in dirs if member.name.startswith(d.name + "_"))
                expected = {n: (r["value"], r["unit"], r["source"])
                            for n, r in _records(run).items()}
                applied = sidecar["export"]["applied"]
                assert {n: (v["value"], v["unit"], v["source"]) for n, v in applied.items()} \
                    == expected
                seen += 1
    assert seen > 0
