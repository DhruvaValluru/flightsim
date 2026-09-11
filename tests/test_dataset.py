"""Phase 10, package 6: batch execution and dataset export.

A matrix becomes content-addressed, ledgered, verified runs; verified
runs become a COCO / KITTI / WebDataset dataset split by simulation
digest, with a card. An unverified run refuses the export by name;
a failed capture is a ledger line, not a silence.
"""

import json
import math
import tarfile
from pathlib import Path

import pytest
import yaml
from PIL import Image

from core.capture.airframe import KEYPOINT_NAMES
from core.capture.manifest import simulation_digest
from core.capture.verify import VERIFICATION_FILE
from core.dataset.batch import (
    BatchError, build_cases, capture_command, read_matrix, run_batch,
)
from core.dataset.export import (
    ExportError, assign_splits, collect_samples, discover_runs, export,
    kitti_alpha, kitti_calib, kitti_label_line, kitti_rotation_y, load_run,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec
from core.scenario.spec import ScenarioSpec

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


# -- fixtures ------------------------------------------------------------------

@pytest.fixture(scope="module")
def batch_dir(tmp_path_factory):
    """The committed example matrix, run for real (four short headless
    captures, each verified)."""
    out = tmp_path_factory.mktemp("batch")
    matrix = read_matrix(EXAMPLES / "batch_matrix.yaml")
    result = run_batch(matrix, out, progress=lambda line: None)
    assert result.failed == 0 and result.unverified == 0
    assert result.completed == 4
    return out


def _matrix_file(tmp_path, **overrides):
    data = {"base": str(EXAMPLES / "cameras_multi.yaml"),
            "factors": [{"field": "altitude", "levels": [1500, 3000]}],
            "seeds": [1, 2]}
    data.update(overrides)
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _fabricate_frames(run_dir: Path, suffix: str = "") -> int:
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    n = 0
    for record in manifest["frames"]:
        path = run_dir / record["file"]
        if suffix:
            path = path.with_name(path.stem + suffix + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (int(record["width_px"]), int(record["height_px"])),
                  (40, 80, 120)).save(path)
        n += 1
    return n


# -- the matrix ------------------------------------------------------------------

def test_the_matrix_refuses_by_name(tmp_path):
    cases = [
        ({"nonsense": 1}, "batch.matrix"),
        ({"base": None}, "batch.base"),
        ({"seeds": [1, 1]}, "batch.seeds"),
        ({"seeds": ["a"]}, "batch.seeds"),
        ({"seeds": [True]}, "batch.seeds"),
        ({"workers": 0}, "batch.workers"),
        ({"design": "latin"}, "batch.design"),
        ({"capture": {"fast": True}}, "batch.capture"),
        ({"capture": {"card": "yes"}}, "batch.capture"),
        ({"factors": [{"field": "altitude"}]}, "batch.factors"),
    ]
    for overrides, constraint in cases:
        path = _matrix_file(tmp_path, **overrides)
        if overrides.get("base", "x") is None:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            del data["base"]
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with pytest.raises(BatchError) as caught:
            read_matrix(path)
        assert caught.value.constraint == constraint, overrides
    with pytest.raises(BatchError) as caught:
        read_matrix(tmp_path / "missing.yaml")
    assert caught.value.constraint == "batch.matrix"


def test_cases_are_content_addressed_and_an_unknown_factor_refuses_first(tmp_path):
    matrix = read_matrix(EXAMPLES / "batch_matrix.yaml")
    cases = build_cases(matrix)
    assert len(cases) == 4
    assert len({c.run_id for c in cases}) == 4
    for case in cases:
        assert case.run_id == case.spec.digest()[:16]
        assert int(case.spec.seed.value) == case.seed
        assert str(case.spec.seed.source) == "user"
        assert case.spec.randomization.is_enabled()
    # Built twice: the same ids (content, not position).
    assert [c.run_id for c in build_cases(matrix)] == [c.run_id for c in cases]
    # A level equal to the base value collapses onto one run.
    base = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    same = read_matrix(_matrix_file(
        tmp_path, factors=[{"field": "altitude",
                            "levels": [float(base.altitude.value)]}],
        seeds=[int(base.seed.value)]))
    assert len(build_cases(same)) == 1
    bad = read_matrix(_matrix_file(
        tmp_path, factors=[{"field": "wingspan", "levels": [1, 2]}]))
    with pytest.raises(BatchError) as caught:
        build_cases(bad)
    assert caught.value.constraint == "batch.factors"
    assert "wingspan" in caught.value.message
    # Camera and randomisation addresses work through the spec's own set().
    nested = read_matrix(_matrix_file(
        tmp_path, factors=[{"field": "cameras[0].focal_length_mm", "levels": [35, 85]},
                           {"field": "randomization.fog_density_max", "levels": [0.005]}],
        seeds=[3]))
    built = build_cases(nested)
    assert len(built) == 2
    assert {float(c.spec.cameras[0].focal_length_mm.value) for c in built} == {35.0, 85.0}


def test_the_capture_command_is_exactly_the_cli(tmp_path):
    import sys

    command = capture_command(tmp_path / "s.yaml", tmp_path / "run",
                              {"card": True, "max_previews": 0, "render": False})
    assert command == [sys.executable, "-m", "flightsim.capture",
                       str(tmp_path / "s.yaml"), "--out", str(tmp_path / "run"),
                       "--max-previews", "0", "--card"]
    assert "--no-host-flight" in capture_command(
        tmp_path / "s.yaml", tmp_path / "run", {"no_host_flight": True, "render": True})


def test_the_ledger_records_failures_resumes_and_runs_in_parallel(tmp_path):
    """No subprocess: a fake runner that fails one case. The failed case
    is a ledger line; a resumed batch retries it and skips the rest; a
    fresh batch discards the ledger; two workers give the same rows."""
    matrix = read_matrix(_matrix_file(tmp_path, workers=2))
    calls = []

    def runner(case, out_dir, capture):
        calls.append(case.run_id)
        ok = case.seed != 2 or case.overrides["altitude"] != 3000
        return {**case.to_dict(), "case_id": case.run_id, "ok": ok,
                "verified": ok, "wall_seconds": 0.0,
                **({} if ok else {"error": "the test broke this one"})}

    out = tmp_path / "batch"
    result = run_batch(matrix, out, runner=runner, progress=lambda line: None)
    assert (result.completed, result.failed, result.skipped) == (3, 1, 0)
    rows = [json.loads(l) for l in (out / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    failed = [r for r in rows if not r["ok"]]
    assert len(failed) == 1 and "broke" in failed[0]["error"]
    record = json.loads((out / "batch.json").read_text(encoding="utf-8"))
    assert record["cases"] == 4 and len(record["run_ids"]) == 4
    assert record["matrix"]["workers"] == 2
    # Resume: only the failed run is retried.
    calls.clear()
    again = run_batch(matrix, out, runner=runner, progress=lambda line: None)
    assert (again.skipped, len(calls)) == (3, 1)
    assert len(again.rows) == 5                       # the retry is a new line
    # Not resuming starts fresh.
    calls.clear()
    fresh = run_batch(matrix, out, resume=False, runner=runner, workers=1,
                      progress=lambda line: None)
    assert (fresh.skipped, len(calls), len(fresh.rows)) == (0, 4, 4)


def test_the_real_batch_captures_verifies_and_ledgers_every_run(batch_dir):
    rows = [json.loads(l) for l in (batch_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4 and all(r["ok"] and r["verified"] for r in rows)
    for row in rows:
        run = Path(row["run_dir"])
        assert run.name == row["run_id"] == row["spec_digest"][:16]
        assert (run / "capture_manifest.json").is_file()
        assert (run / VERIFICATION_FILE).is_file()
        assert (run / "card.json").is_file()            # capture: {card: true}
        assert (run / "spec.yaml").is_file() and (run / "capture.log").is_file()
        verification = json.loads((run / VERIFICATION_FILE).read_text(encoding="utf-8"))
        assert verification["ok"] and verification["failed"] == 0
        assert row["verification"]["passed"] == verification["passed"]
        manifest = json.loads((run / "capture_manifest.json").read_text(encoding="utf-8"))
        assert manifest["spec_digest"] == row["spec_digest"]
        assert manifest["randomization"]["seed"] > 0   # the block drew
    assert {r["factor.altitude"] for r in rows} == {1500, 3000}
    assert {r["seed"] for r in rows} == {1, 2}


def test_the_batch_cli_dry_runs_and_resumes(batch_dir, capsys):
    from flightsim.batch import main

    assert main([str(EXAMPLES / "batch_matrix.yaml"), "--out", str(batch_dir),
                 "--dry-run"]) == 0
    assert "4 run(s) = 2 cell(s) x 2 seed(s)" in capsys.readouterr().out
    assert main([str(EXAMPLES / "batch_matrix.yaml"), "--out", str(batch_dir)]) == 0
    assert "0 captured, 4 skipped" in capsys.readouterr().out
    assert main([str(EXAMPLES / "missing.yaml"), "--out", str(batch_dir)]) == 2
    assert "REFUSED -- batch.matrix" in capsys.readouterr().out


def test_the_verify_cli_writes_the_verdict_the_export_reads(batch_dir, capsys):
    from flightsim.verify import main as verify_main

    run = next(p for p in batch_dir.iterdir() if (p / "capture_manifest.json").is_file())
    (run / VERIFICATION_FILE).unlink()
    assert verify_main([str(run)]) == 0
    assert (run / VERIFICATION_FILE).is_file()
    assert "recorded:" in capsys.readouterr().out


# -- the split key --------------------------------------------------------------

def test_simulation_digest_ignores_cameras_and_randomisation():
    """Two runs that differ only in what LOOKED at the flight, or in
    the sampled sun/fog/jitter, flew one simulation: one split side."""
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt for 60 seconds")
    base = simulation_digest(spec)
    spec.cameras = [CameraSpec.defaulted(camera_id="x", preset="tower", aircraft="B747")]
    assert simulation_digest(spec) == base
    spec.set("randomization.enabled", True, frm="test")
    assert simulation_digest(spec) == base
    assert spec.digest() != compile_prompt(
        "fly the 747 at 10000 ft and 280 kt for 60 seconds").digest()
    spec.set("altitude", 4000.0, frm="test")
    assert simulation_digest(spec) != base


def test_splits_keep_a_simulation_on_one_side_and_follow_the_seed(batch_dir):
    runs = [load_run(d) for d in discover_runs([batch_dir])]
    samples = collect_samples(runs, labels_only=True)
    splits = assign_splits(samples, (0.5, 0.25, 0.25), seed=0)
    assert set(splits) == {s.simulation_digest for s in samples}
    assert set(splits.values()) <= {"train", "val", "test"}
    assert len(set(splits.values())) == 3
    assert assign_splits(samples, (0.5, 0.25, 0.25), seed=0) == splits
    other = [assign_splits(samples, (0.5, 0.25, 0.25), seed=s) for s in range(1, 8)]
    assert any(o != splits for o in other)
    only_train = assign_splits(samples, (1.0, 0.0, 0.0), seed=0)
    assert set(only_train.values()) == {"train"}
    with pytest.raises(ExportError) as caught:
        assign_splits(samples, (0.5, 0.5, 0.5), seed=0)
    assert caught.value.constraint == "export.split"


# -- refusals --------------------------------------------------------------------

def test_export_refuses_unverified_failed_and_frameless_runs(batch_dir, tmp_path):
    with pytest.raises(ExportError) as caught:
        discover_runs([tmp_path / "nowhere"])
    assert caught.value.constraint == "export.runs"
    run = sorted(p for p in batch_dir.iterdir() if (p / "capture_manifest.json").is_file())[0]
    # No verification record.
    import shutil

    copy = tmp_path / "copy"
    shutil.copytree(run, copy)
    (copy / VERIFICATION_FILE).unlink()
    with pytest.raises(ExportError) as caught:
        export([copy], tmp_path / "ds", "coco", labels_only=True)
    assert caught.value.constraint == "export.unverified"
    # A failed check.
    record = json.loads((run / VERIFICATION_FILE).read_text(encoding="utf-8"))
    record["ok"] = False
    record["checks"].append({"name": "landmark_reprojection", "status": "FAIL",
                             "detail": "the test broke it"})
    (copy / VERIFICATION_FILE).write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ExportError) as caught:
        load_run(copy)
    assert caught.value.constraint == "export.verification_failed"
    assert "landmark_reprojection" in caught.value.message
    # No pixels, no --labels-only.
    with pytest.raises(ExportError) as caught:
        export([run], tmp_path / "ds2", "coco")
    assert caught.value.constraint == "export.missing_frames"
    with pytest.raises(ExportError) as caught:
        export([run], tmp_path / "ds3", "tfrecord", labels_only=True)
    assert caught.value.constraint == "export.format"


# -- the formats -----------------------------------------------------------------

def test_coco_export_with_real_pixels_and_the_card(batch_dir, tmp_path):
    runs = sorted(p for p in batch_dir.iterdir() if (p / "capture_manifest.json").is_file())
    n = _fabricate_frames(runs[0])
    card = export([runs[0]], tmp_path / "coco", "coco", fractions=(1.0, 0.0, 0.0))
    assert card["frames"] == n and card["frames_per_split"]["train"] == n
    train = json.loads((tmp_path / "coco" / "annotations" / "instances_train.json").read_text(encoding="utf-8"))
    assert len(train["images"]) == n
    images = sorted((tmp_path / "coco" / "images" / "train").glob("*.png"))
    assert len(images) == n
    assert {im["file_name"] for im in train["images"]} == {p.name for p in images}
    assert train["categories"][0]["name"] == "B747"
    assert train["categories"][0]["keypoints"] == list(KEYPOINT_NAMES)
    assert train["annotations"], "the chase camera sees the aircraft"
    ann = train["annotations"][0]
    image = next(im for im in train["images"] if im["id"] == ann["image_id"])
    x, y, w, h = ann["bbox"]
    assert 0 <= x and x + w <= image["width"] and 0 <= y and y + h <= image["height"]
    assert ann["area"] == pytest.approx(w * h)
    assert len(ann["keypoints"]) == 3 * len(KEYPOINT_NAMES)
    assert ann["num_keypoints"] == sum(1 for i in range(2, 21, 3) if ann["keypoints"][i] == 2)
    assert ann["bbox_3d_camera"]["extents_m"][1] > 60.0     # a 747's span
    assert ann["horizon"]["model"].startswith("spherical")
    # The card.
    assert card["split"]["by"] == "simulation_digest"
    assert card["runs"][0]["verification"]["failed"] == 0
    assert card["runs"][0]["randomization"]["seed"] > 0
    assert any("Gate 10-R" in item for item in card["not_claimed"])
    text = (tmp_path / "coco" / "DATASET_CARD.md").read_text(encoding="utf-8")
    assert "## Not claimed" in text and "randomised" in text
    # A run that has the sensor frames exports them with labels_sensor.
    _fabricate_frames(runs[0], suffix="_sensor")
    sensor = export([runs[0]], tmp_path / "coco_sensor", "coco",
                    fractions=(1.0, 0.0, 0.0), image="sensor")
    assert sensor["image"] == "sensor"
    train_s = json.loads((tmp_path / "coco_sensor" / "annotations" / "instances_train.json").read_text(encoding="utf-8"))
    assert train_s["images"][0]["pixels"].startswith("sensor (ideal_pinhole)")
    # The ideal profile maps every pixel onto itself: same boxes.
    assert train_s["annotations"][0]["bbox"] == pytest.approx(ann["bbox"], abs=1e-6)


def test_kitti_conventions_and_export(batch_dir, tmp_path):
    # rotation_y: the body forward axis along camera +x is 0; along
    # camera +z (flying away from a chase camera) is -pi/2.
    assert kitti_rotation_y([1.0, 0.0, 0.0]) == pytest.approx(0.0)
    assert kitti_rotation_y([0.0, 0.0, 1.0]) == pytest.approx(-math.pi / 2)
    assert kitti_rotation_y([0.0, 0.0, -1.0]) == pytest.approx(math.pi / 2)
    # alpha: rotation_y minus the observation angle atan2(x, z), wrapped.
    assert kitti_alpha(0.0, [0.0, 0.0, 10.0]) == pytest.approx(0.0)
    assert kitti_alpha(0.0, [10.0, 0.0, 10.0]) == pytest.approx(-math.pi / 4)
    assert -math.pi <= kitti_alpha(3.0, [-10.0, 0.0, 1.0]) <= math.pi
    runs = sorted(p for p in batch_dir.iterdir() if (p / "capture_manifest.json").is_file())
    card = export([runs[1]], tmp_path / "kitti", "kitti", fractions=(0.0, 0.0, 1.0),
                  labels_only=True)
    assert card["frames_per_split"]["test"] == card["frames"]
    labels = sorted((tmp_path / "kitti" / "test" / "label_2").glob("*.txt"))
    calib = sorted((tmp_path / "kitti" / "test" / "calib").glob("*.txt"))
    assert len(labels) == len(calib) == card["frames"]
    lines = [l for p in labels for l in p.read_text(encoding="utf-8").splitlines()]
    assert lines
    fields = lines[0].split()
    assert len(fields) == 15 and fields[0] == "B747" and fields[2] == "3"
    h, w, l = (float(v) for v in fields[8:11])
    assert w > 60.0 and l > 60.0 and 0.0 < h < 30.0
    p2 = next(l for l in calib[0].read_text(encoding="utf-8").splitlines() if l.startswith("P2:"))
    manifest = json.loads((runs[1] / "capture_manifest.json").read_text(encoding="utf-8"))
    record = manifest["frames"][0]
    assert float(p2.split()[1]) == pytest.approx(record["fx_px"], abs=1e-5)
    assert float(p2.split()[3]) == pytest.approx(record["principal_point_px"][0], abs=1e-5)
    assert kitti_calib(record).count("\n") == 7
    sample_line = kitti_label_line(
        collect_samples([load_run(runs[1])], labels_only=True)[0])
    assert sample_line is None or len(sample_line.split()) == 15


def test_webdataset_shards_are_sorted_and_reproducible(batch_dir, tmp_path):
    runs = sorted(p for p in batch_dir.iterdir() if (p / "capture_manifest.json").is_file())
    card = export([runs[2]], tmp_path / "wds", "webdataset", fractions=(1.0, 0.0, 0.0),
                  labels_only=True, shard_size=20)
    shards = sorted((tmp_path / "wds" / "train").glob("shard-*.tar"))
    assert len(shards) == math.ceil(card["frames"] / 20)
    with tarfile.open(shards[0]) as tar:
        names = tar.getnames()
        assert names == sorted(names) and len(names) == 20
        sidecar = json.loads(tar.extractfile(names[0]).read().decode("utf-8"))
    assert sidecar["context"]["spec_digest"] == card["runs"][0]["spec_digest"]
    assert sidecar["export"]["split"] == "train"
    assert "bbox_2d" in sidecar["export"]["labels"]
    export([runs[2]], tmp_path / "wds2", "webdataset", fractions=(1.0, 0.0, 0.0),
           labels_only=True, shard_size=20)
    assert shards[0].read_bytes() == (tmp_path / "wds2" / "train" / shards[0].name).read_bytes()


def test_the_export_cli_refuses_and_succeeds_by_exit_code(batch_dir, tmp_path, capsys):
    from flightsim.export import main

    assert main([str(batch_dir), "--out", str(tmp_path / "ds"), "--format", "coco"]) == 2
    assert "REFUSED -- export.missing_frames" in capsys.readouterr().out
    assert main([str(batch_dir), "--out", str(tmp_path / "ds"), "--format", "coco",
                 "--labels-only", "--split", "0.5,0.25,0.25"]) == 0
    out = capsys.readouterr().out
    assert "exported 192 frame(s) from 4 run(s)" in out
    assert (tmp_path / "ds" / "DATASET_CARD.md").is_file()
    assert main([str(batch_dir), "--out", str(tmp_path / "ds"), "--format", "coco",
                 "--labels-only", "--split", "0.5,0.5"]) == 2
