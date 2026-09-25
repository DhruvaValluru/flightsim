"""Phase 2, package E: dataset export formats, round-tripped through
independent readers.

Every round trip here reads the written dataset with code that is NOT
the writer: pycocotools for COCO (an optional dev dependency,
requirements-dev.txt; the test skips by name when it is absent), a
minimal YOLO text reader against the Ultralytics layout, xml.etree for
Pascal VOC, a minimal KITTI line reader, tarfile for WebDataset. The
expected numbers come from ``capture_manifest.json`` read with json,
never from the export module's own Sample objects.

The Phase 10 writers are pinned byte-identical against a frozen copy of
the pre-package-E module (``tests/data/export_phase10_frozen.py``) on a
run that carries none of the new fields.
"""

import importlib.util
import json
import math
import shutil
import sys
import tarfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml
from PIL import Image

from core.capture.verify import VERIFICATION_FILE
from core.dataset.batch import read_matrix, run_batch
from core.dataset.export import (
    ExportError, NOT_CLAIMED_EXTENT_PX, assign_splits, collect_samples,
    discover_runs, export, load_run, parse_formats,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
FROZEN = Path(__file__).resolve().parent / "data" / "export_phase10_frozen.py"


# -- fixtures ------------------------------------------------------------------

@pytest.fixture(scope="module")
def batch_dir(tmp_path_factory):
    """The committed example matrix, run for real (four short headless
    captures, each verified): four simulation digests, 192 frames."""
    out = tmp_path_factory.mktemp("batch")
    matrix = read_matrix(EXAMPLES / "batch_matrix.yaml")
    result = run_batch(matrix, out, progress=lambda line: None)
    assert result.failed == 0 and result.unverified == 0
    return out


def _runs(batch_dir):
    return sorted(p for p in batch_dir.iterdir() if (p / "capture_manifest.json").is_file())


def _manifest(run: Path):
    return json.loads((run / "capture_manifest.json").read_text(encoding="utf-8"))


def _fabricate_frames(run_dir: Path) -> int:
    n = 0
    for record in _manifest(run_dir)["frames"]:
        path = run_dir / record["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (int(record["width_px"]), int(record["height_px"])),
                  (40, 80, 120)).save(path)
        n += 1
    return n


def _expected_boxes(run: Path):
    """{key: (bbox_2d, width, height, record)} straight from the manifest."""
    out = {}
    for record in _manifest(run)["frames"]:
        key = f"{run.name}_{record['camera_id']}_{int(record['index']):04d}"
        out[key] = (record["labels"]["bbox_2d"], int(record["width_px"]),
                    int(record["height_px"]), record)
    return out


def _frozen_module():
    spec = importlib.util.spec_from_file_location("export_phase10_frozen", FROZEN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # dataclasses resolve the module by name
    spec.loader.exec_module(module)
    return module


# -- independent readers ---------------------------------------------------------

def read_yolo(root: Path):
    """The Ultralytics detect layout: data.yaml names + labels/<split>/*.txt
    -> {key: (split, [(class_idx, x0, y0, x1, y1) in pixels])}, using the
    image size from the PNG when present, else the caller's."""
    data = yaml.safe_load((root / "data.yaml").read_text(encoding="utf-8"))
    names = data["names"]
    assert isinstance(names, dict) and list(names) == list(range(len(names)))
    assert data["train"] == "images/train" and data["val"] == "images/val"
    boxes = {}
    for split in ("train", "val", "test"):
        assert (root / "images" / split).is_dir() and (root / "labels" / split).is_dir()
        for txt in sorted((root / "labels" / split).glob("*.txt")):
            lines = []
            for line in txt.read_text(encoding="utf-8").splitlines():
                c, cx, cy, w, h = line.split()
                lines.append((int(c), float(cx), float(cy), float(w), float(h)))
            boxes[txt.stem] = (split, lines)
    return names, boxes


def read_voc(root: Path):
    """The devkit layout: ImageSets/Main/<split>.txt stems, Annotations
    xml -> {stem: (split, size, [object dicts])}."""
    splits = {}
    for split in ("train", "val", "test"):
        for stem in (root / "ImageSets" / "Main" / f"{split}.txt").read_text(encoding="utf-8").split():
            assert stem not in splits, "a stem listed in two splits"
            splits[stem] = split
    out = {}
    for xml in sorted((root / "Annotations").glob("*.xml")):
        tree = ET.parse(xml).getroot()
        assert tree.tag == "annotation"
        size = (int(tree.find("size/width").text), int(tree.find("size/height").text))
        objects = []
        for obj in tree.findall("object"):
            box = obj.find("bndbox")
            objects.append({
                "name": obj.find("name").text,
                "truncated": int(obj.find("truncated").text),
                "occluded": int(obj.find("occluded").text),
                "difficult": int(obj.find("difficult").text),
                "bndbox": tuple(int(box.find(k).text) for k in ("xmin", "ymin", "xmax", "ymax")),
            })
        assert tree.find("filename").text == f"{xml.stem}.png"
        assert tree.find("folder").text == "JPEGImages"
        out[xml.stem] = (splits[xml.stem], size, objects)
    return out


def read_kitti(root: Path):
    """{key: (split, [15-field lists])}."""
    out = {}
    for split in ("train", "val", "test"):
        for txt in sorted((root / split / "label_2").glob("*.txt")) if (root / split).is_dir() else []:
            rows = [line.split() for line in txt.read_text(encoding="utf-8").splitlines()]
            assert all(len(r) == 15 for r in rows)
            out[txt.stem] = (split, rows)
    return out


def read_webdataset(root: Path):
    """{key: (split, {extension: bytes})} over every shard."""
    out = {}
    for split in ("train", "val", "test"):
        for shard in sorted((root / split).glob("shard-*.tar")) if (root / split).is_dir() else []:
            with tarfile.open(shard) as tar:
                for member in tar.getmembers():
                    key, ext = member.name.split(".", 1)
                    out.setdefault(key, (split, {}))[1][ext] = tar.extractfile(member).read()
    return out


# -- the Phase 10 writers are unchanged -------------------------------------------

def test_phase10_outputs_are_byte_identical_to_the_frozen_writer(batch_dir, tmp_path):
    """COCO, KITTI and labels-only WebDataset for a run without the new
    fields: the frozen pre-package-E module and the live one write the
    same bytes. (A with-pixels WebDataset differs BY DESIGN: the frozen
    writer leaked the source PNG's mtime, the live one fixes it at 0.)"""
    frozen = _frozen_module()
    run = _runs(batch_dir)[0]
    _fabricate_frames(run)
    headless = tmp_path / "headless"                 # the same run with no pixels
    shutil.copytree(run, headless, ignore=shutil.ignore_patterns("*.png"))
    for fmt in ("coco", "kitti", "webdataset"):
        source = headless if fmt == "webdataset" else run
        kwargs = {"fractions": (0.5, 0.25, 0.25), "seed": 3,
                  "labels_only": fmt == "webdataset", "shard_size": 16}
        frozen.export([source], tmp_path / "old" / fmt, fmt, **kwargs)
        export([source], tmp_path / "new" / fmt, fmt, **kwargs)
        old_files = sorted(p.relative_to(tmp_path / "old" / fmt)
                           for p in (tmp_path / "old" / fmt).rglob("*") if p.is_file())
        new_files = sorted(p.relative_to(tmp_path / "new" / fmt)
                           for p in (tmp_path / "new" / fmt).rglob("*") if p.is_file())
        assert old_files == new_files, fmt
        compared = 0
        for rel in old_files:
            if rel.name in ("dataset.json", "DATASET_CARD.md"):
                continue                     # the card GAINS keys; that is the point
            assert (tmp_path / "old" / fmt / rel).read_bytes() == \
                (tmp_path / "new" / fmt / rel).read_bytes(), f"{fmt}: {rel}"
            compared += 1
        assert compared > 0


# -- round trips -------------------------------------------------------------------

def test_yolo_round_trip_with_a_minimal_reader(batch_dir, tmp_path):
    run = _runs(batch_dir)[0]
    n = _fabricate_frames(run)
    card = export([run], tmp_path / "yolo", "yolo", fractions=(1.0, 0.0, 0.0))
    assert card["formats"] == ["yolo"] and card["frames"] == n
    names, boxes = read_yolo(tmp_path / "yolo")
    assert names == {0: "B747"}                   # airframe names: no taxonomy on a v5 run
    assert card["classes"] == ["B747"] and card["class_order"] == "airframe names"
    expected = _expected_boxes(run)
    assert set(boxes) == set(expected)
    images = sorted((tmp_path / "yolo" / "images" / "train").glob("*.png"))
    assert len(images) == n and {p.stem for p in images} == set(expected)
    checked = 0
    for key, (split, lines) in boxes.items():
        box, width, height, _ = expected[key]
        assert split == "train"
        if box is None:
            assert lines == []
            continue
        assert len(lines) == 1
        c, cx, cy, w, h = lines[0]
        assert c == 0
        got = ((cx - w / 2) * width, (cy - h / 2) * height,
               (cx + w / 2) * width, (cy + h / 2) * height)
        for a, b in zip(got, box):
            assert abs(a - b) < 0.01, key       # to the pixel (and well under)
        checked += 1
    assert checked > 0


def test_voc_round_trip_with_xml_etree(batch_dir, tmp_path):
    run = _runs(batch_dir)[1]
    n = _fabricate_frames(run)
    card = export([run], tmp_path / "voc", "voc", fractions=(0.0, 1.0, 0.0))
    assert card["frames_per_split"]["val"] == n
    parsed = read_voc(tmp_path / "voc")
    expected = _expected_boxes(run)
    assert set(parsed) == set(expected)
    assert len(list((tmp_path / "voc" / "JPEGImages").glob("*.png"))) == n
    checked = 0
    for key, (split, size, objects) in parsed.items():
        box, width, height, record = expected[key]
        assert split == "val" and size == (width, height)
        if box is None:
            assert objects == []
            continue
        assert len(objects) == 1
        obj = objects[0]
        assert obj["name"] == "B747"
        xmin, ymin, xmax, ymax = obj["bndbox"]
        # 1-based inclusive integers covering the float box: within a pixel.
        assert xmin - 1 <= box[0] < xmin and ymin - 1 <= box[1] < ymin
        assert xmax - 1 < box[2] <= xmax and ymax - 1 < box[3] <= ymax
        # The flags, re-derived from the manifest record.
        truncation = record["labels"]["truncation"]
        assert obj["truncated"] == int(truncation is not None and truncation > 0)
        assert obj["occluded"] == 0                # no visibility recorded on a v5 run
        extent = max(box[2] - box[0], box[3] - box[1])
        assert obj["difficult"] == int(extent < NOT_CLAIMED_EXTENT_PX)
        checked += 1
    assert checked > 0


def test_coco_round_trip_with_pycocotools(batch_dir, tmp_path):
    coco_api = pytest.importorskip("pycocotools.coco",
                                   reason="pycocotools (requirements-dev.txt) is the "
                                          "independent COCO reader")
    run = _runs(batch_dir)[2]
    n = _fabricate_frames(run)
    export([run], tmp_path / "coco", "coco", fractions=(1.0, 0.0, 0.0))
    coco = coco_api.COCO(str(tmp_path / "coco" / "annotations" / "instances_train.json"))
    assert len(coco.getImgIds()) == n
    cats = coco.loadCats(coco.getCatIds())
    assert [(c["id"], c["name"]) for c in cats] == [(1, "B747")]
    expected = _expected_boxes(run)
    checked = 0
    for image in coco.loadImgs(coco.getImgIds()):
        key = image["file_name"][:-len(".png")]
        box, width, height, _ = expected[key]
        assert (image["width"], image["height"]) == (width, height)
        assert (tmp_path / "coco" / "images" / "train" / image["file_name"]).is_file()
        anns = coco.loadAnns(coco.getAnnIds(imgIds=[image["id"]]))
        if box is None:
            assert anns == []
            continue
        assert len(anns) == 1 and anns[0]["category_id"] == 1
        x, y, w, h = anns[0]["bbox"]
        assert (x, y, x + w, y + h) == pytest.approx(tuple(box), abs=1e-6)
        checked += 1
    assert checked > 0


def test_kitti_round_trip_with_a_minimal_line_reader(batch_dir, tmp_path):
    run = _runs(batch_dir)[3]
    export([run], tmp_path / "kitti", "kitti", fractions=(0.0, 0.0, 1.0), labels_only=True)
    parsed = read_kitti(tmp_path / "kitti")
    expected = _expected_boxes(run)
    assert set(parsed) == set(expected)
    checked = 0
    for key, (split, rows) in parsed.items():
        box, _, _, record = expected[key]
        assert split == "test"
        if box is None or record["labels"]["bbox_3d_camera"] is None:
            assert rows == []
            continue
        assert len(rows) == 1
        row = rows[0]
        assert row[0] == "B747" and row[2] == "3"        # occluded unknown without an ID pass
        assert [float(v) for v in row[4:8]] == pytest.approx(box, abs=0.005)   # 2 decimals
        centre = record["labels"]["bbox_3d_camera"]["centre_m"]
        assert [float(v) for v in row[11:14]] == pytest.approx(centre, abs=0.0005)
        checked += 1
    assert checked > 0


def test_webdataset_round_trip_with_tarfile_and_reproducible_pixels(batch_dir, tmp_path):
    run = _runs(batch_dir)[0]
    n = _fabricate_frames(run)
    export([run], tmp_path / "wds", "webdataset", fractions=(1.0, 0.0, 0.0), shard_size=20)
    export([run], tmp_path / "wds2", "webdataset", fractions=(1.0, 0.0, 0.0), shard_size=20)
    shards = sorted((tmp_path / "wds" / "train").glob("shard-*.tar"))
    assert len(shards) == math.ceil(n / 20)
    for shard in shards:                                 # with pixels, byte for byte
        assert shard.read_bytes() == (tmp_path / "wds2" / "train" / shard.name).read_bytes()
    parsed = read_webdataset(tmp_path / "wds")
    expected = _expected_boxes(run)
    assert set(parsed) == set(expected)
    for key, (split, members) in parsed.items():
        assert split == "train" and set(members) == {"png", "json"}
        assert members["png"] == (run / expected[key][3]["file"]).read_bytes()
        sidecar = json.loads(members["json"].decode("utf-8"))
        assert sidecar["export"]["labels"]["bbox_2d"] == expected[key][0]
        assert "objects" not in sidecar["export"]["labels"]        # the sidecar is unchanged
    with tarfile.open(shards[0]) as tar:
        assert all(m.mtime == 0 and m.uid == 0 and m.uname == "" for m in tar.getmembers())


# -- the split: one flight, one side, in every format ---------------------------------

def test_a_frame_of_one_flight_never_straddles_train_and_val(batch_dir, tmp_path):
    runs = _runs(batch_dir)
    digest_of_run = {r.name: _manifest(r)["simulation_digest"] for r in runs}
    assert len(set(digest_of_run.values())) == 4
    card = export([batch_dir], tmp_path / "all", "yolo,voc,kitti,coco,webdataset",
                  fractions=(0.5, 0.25, 0.25), seed=0, labels_only=True, shard_size=50)
    assert card["formats"] == ["yolo", "voc", "kitti", "coco", "webdataset"]
    assert len(set(card["split"]["assignment"].values())) == 3
    seen = {}
    names, yolo = read_yolo(tmp_path / "all" / "yolo")
    seen["yolo"] = {k: v[0] for k, v in yolo.items()}
    seen["voc"] = {k: v[0] for k, v in read_voc(tmp_path / "all" / "voc").items()}
    seen["kitti"] = {k: v[0] for k, v in read_kitti(tmp_path / "all" / "kitti").items()}
    seen["webdataset"] = {k: v[0] for k, v in read_webdataset(tmp_path / "all" / "webdataset").items()}
    coco = {}
    for split in ("train", "val", "test"):
        payload = json.loads((tmp_path / "all" / "coco" / "annotations" / f"instances_{split}.json")
                             .read_text(encoding="utf-8"))
        for image in payload["images"]:
            coco[image["file_name"][:-len(".png")]] = split
    seen["coco"] = coco
    for fmt, membership in seen.items():
        assert len(membership) == 192, fmt
        by_digest = {}
        for key, split in membership.items():
            run_name = key[:16]
            by_digest.setdefault(digest_of_run[run_name], set()).add(split)
        assert all(len(s) == 1 for s in by_digest.values()), (fmt, by_digest)
        assert {d: next(iter(s)) for d, s in by_digest.items()} == card["split"]["assignment"], fmt
    # assign_splits itself is keyed on the digest, and the split follows the seed.
    samples = collect_samples([load_run(d) for d in discover_runs([batch_dir])], labels_only=True)
    assert set(assign_splits(samples, (0.5, 0.25, 0.25), 0)) == set(digest_of_run.values())


# -- manifest 6: labels.objects[] --------------------------------------------------------

def _fabricate_objects_run(source: Path, target: Path) -> Path:
    """A copy of a real run with a manifest-6-shaped objects[] block and
    a per-frame labels.objects[] of three objects: the primary (its own
    labels), a small truncated, part-occluded traffic aircraft, and the
    terrain (a tight box only, no 3-D box, no visibility, and the
    draft's ``fraction_in_frame`` key, which the reader still honours)."""
    shutil.copytree(source, target)
    manifest = _manifest(target)
    manifest["taxonomy"] = ["aircraft", "terrain"]
    manifest["objects"] = [
        {"id": "aircraft:B747:0", "int_id": 1, "class": "aircraft", "class_id": 1,
         "instance": 0, "role": "primary", "mesh_sha256": "a" * 64,
         "licence": "GPL-2.0", "in_scene": True, "labelled": True},
        {"id": "aircraft:A320:1", "int_id": 2, "class": "aircraft", "class_id": 1,
         "instance": 1, "role": "traffic", "mesh_sha256": "b" * 64,
         "licence": "GPL-2.0", "in_scene": True, "labelled": True},
        {"id": "terrain", "int_id": 3, "class": "terrain", "class_id": 2,
         "instance": 0, "role": "scene", "mesh_sha256": None, "licence": None,
         "in_scene": True, "labelled": True},
    ]
    for record in manifest["frames"]:
        labels = record["labels"]
        labels["objects"] = [
            {"id": "aircraft:B747:0", "int_id": 1, "class_id": 1,
             "bbox_2d": labels["bbox_2d"], "bbox_2d_unclipped": labels["bbox_2d_unclipped"],
             "truncation": labels["truncation"], "in_frame": labels["in_frame"],
             "visible_fraction": 0.97, "occluded_by": [],
             "bbox_3d_camera": labels["bbox_3d_camera"],
             "not_claimed": ["objects_under_px: 12"]},
            {"id": "aircraft:A320:1", "int_id": 2, "class_id": 1,
             "bbox_2d": [10.0, 10.0, 20.0, 18.0], "bbox_2d_unclipped": [5.0, 10.0, 20.0, 18.0],
             "truncation": 1.0 - (10.0 * 8.0) / (15.0 * 8.0), "in_frame": True,
             "visible_fraction": 0.6, "occluded_by": ["aircraft:B747:0"],
             "bbox_3d_camera": labels["bbox_3d_camera"],
             "not_claimed": ["objects_under_px: 12"]},
            {"id": "terrain", "int_id": 3, "class_id": 2,
             "bbox_2d_tight": [0.0, 400.0, float(record["width_px"]), float(record["height_px"])],
             "fraction_in_frame": 0.5,          # the draft key: half the terrain is in frame
             "visible_fraction": None, "occluded_by": [], "not_claimed": []},
        ]
    (target / "capture_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return target


def test_manifest6_objects_export_every_object_with_its_class(batch_dir, tmp_path):
    run = _fabricate_objects_run(_runs(batch_dir)[0], tmp_path / "objects_run")
    card = export([run], tmp_path / "ds", "yolo,voc,kitti,coco", fractions=(1.0, 0.0, 0.0),
                  labels_only=True)
    n = card["frames"]
    assert card["classes"] == ["aircraft", "terrain"] and card["class_order"] == "manifest taxonomy"
    frames_with_primary = sum(1 for r in _manifest(run)["frames"] if r["labels"]["bbox_2d"])
    assert card["instances"] == frames_with_primary + 2 * n
    assert card["class_balance"]["aircraft"]["instances"] == frames_with_primary + n
    assert card["class_balance"]["terrain"]["instances"] == n
    assert card["not_claimed_from_labels"] == {"objects_under_px: 12": frames_with_primary + n}
    assert any("objects_under_px: 12" in item for item in card["not_claimed"])
    licences = {(e["kind"], e["asset"]): e for e in card["licences"]}
    assert licences[("object", "aircraft:A320:1")]["licence"] == "GPL-2.0"
    assert licences[("aircraft_config", "assets/aircraft_config/B747.json")]["licence"] == "GPL-2.0"
    assert ("object", "terrain") not in licences
    # YOLO: three lines per frame, class 0 aircraft / 1 terrain, the traffic box exact.
    names, yolo = read_yolo(tmp_path / "ds" / "yolo")
    assert names == {0: "aircraft", 1: "terrain"}
    key = next(k for k, v in yolo.items() if len(v[1]) == 3)
    width, height = _expected_boxes(run)[key][1:3]
    classes = [line[0] for line in yolo[key][1]]
    assert classes == [0, 0, 1]
    c, cx, cy, w, h = yolo[key][1][1]
    assert ((cx - w / 2) * width, (cy - h / 2) * height, (cx + w / 2) * width, (cy + h / 2) * height) \
        == pytest.approx((10.0, 10.0, 20.0, 18.0), abs=0.01)
    # VOC: the flags per object, derived from the record.
    voc = read_voc(tmp_path / "ds" / "voc")
    _, _, objects = voc[key]
    assert [o["name"] for o in objects] == ["aircraft", "aircraft", "terrain"]
    primary, traffic, terrain = objects
    assert (primary["truncated"], primary["occluded"], primary["difficult"]) == (0, 0, 0)
    assert (traffic["truncated"], traffic["occluded"], traffic["difficult"]) == (1, 1, 1)
    assert traffic["bndbox"] == (11, 11, 20, 18)
    assert (terrain["truncated"], terrain["occluded"], terrain["difficult"]) == (1, 0, 0)
    assert terrain["bndbox"] == (1, 401, width, height)
    # KITTI: two aircraft lines (terrain has no 3-D box); occluded 0 and 1 from visibility.
    kitti = read_kitti(tmp_path / "ds" / "kitti")
    rows = kitti[key][1]
    assert [r[0] for r in rows] == ["aircraft", "aircraft"]
    assert [r[2] for r in rows] == ["0", "1"]
    assert rows[1][1] == "0.33"
    # COCO: categories from the taxonomy, one annotation per object, the visibility carried.
    train = json.loads((tmp_path / "ds" / "coco" / "annotations" / "instances_train.json")
                       .read_text(encoding="utf-8"))
    assert [(c["id"], c["name"]) for c in train["categories"]] == [(1, "aircraft"), (2, "terrain")]
    image_id = next(im["id"] for im in train["images"] if im["file_name"] == f"{key}.png")
    anns = [a for a in train["annotations"] if a["image_id"] == image_id]
    assert [a["category_id"] for a in anns] == [1, 1, 2]
    assert anns[1]["visible_fraction"] == 0.6 and anns[1]["occluded_by"] == ["aircraft:B747:0"]
    assert "segmentation" not in anns[0]                 # no mask on disk
    # A v5 run and a taxonomy run in one export refuse by name.
    with pytest.raises(ExportError) as caught:
        export([run, _runs(batch_dir)[1]], tmp_path / "mixed", "yolo", labels_only=True)
    assert caught.value.constraint == "export.taxonomy"


def test_a_sensor_image_refuses_an_object_without_sensor_labels(batch_dir, tmp_path):
    run = _fabricate_objects_run(_runs(batch_dir)[1], tmp_path / "objects_run")
    for record in _manifest(run)["frames"]:
        path = run / record["file"]
        path = path.with_name(path.stem + "_sensor.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (int(record["width_px"]), int(record["height_px"]))).save(path)
    with pytest.raises(ExportError) as caught:
        export([run], tmp_path / "ds", "yolo", image="sensor")
    assert caught.value.constraint == "export.sensor_labels"
    assert "aircraft:A320:1" in caught.value.message


# -- masks: refused by name until graded, then shipped -----------------------------------

def test_masks_refuse_unverified_labels_then_ship_as_rle_and_members(batch_dir, tmp_path):
    coco_mask = pytest.importorskip("pycocotools.mask",
                                    reason="pycocotools decodes the RLE independently")
    run = tmp_path / "mask_run"
    shutil.copytree(_runs(batch_dir)[2], run)
    n = _fabricate_frames(run)
    record = _manifest(run)["frames"][0]
    key = f"{run.name}_{record['camera_id']}_{int(record['index']):04d}"
    width, height = int(record["width_px"]), int(record["height_px"])
    mask = Image.new("L", (width, height), 0)
    mask.paste(1, (100, 50, 300, 170))                  # 200 x 120 = 24000 pixels of int_id 1
    mask_path = run / record["file"]
    mask_path = mask_path.with_name(mask_path.stem + "_mask.png")
    mask.save(mask_path)
    # A mask on disk that no verifier check graded refuses the mask-shipping formats by name...
    for fmt in ("coco", "webdataset", "yolo,coco"):
        with pytest.raises(ExportError) as caught:
            export([run], tmp_path / "refused", fmt, fractions=(1.0, 0.0, 0.0))
        assert caught.value.constraint == "export.unverified_labels"
        assert "mask_integers_only" in caught.value.message
    # ...while a format that ships no mask exports.
    export([run], tmp_path / "yolo", "yolo", fractions=(1.0, 0.0, 0.0))
    # Graded: the checks PASS in verification.json (fabricated -- no engine here).
    verification = json.loads((run / VERIFICATION_FILE).read_text(encoding="utf-8"))
    verification["checks"] += [{"name": "mask_integers_only", "status": "PASS", "detail": "test"},
                               {"name": "mask_vs_geometry", "status": "PASS", "detail": "test"}]
    verification["passed"] += 2
    (run / VERIFICATION_FILE).write_text(json.dumps(verification), encoding="utf-8")
    card = export([run], tmp_path / "shipped", "coco,webdataset", fractions=(1.0, 0.0, 0.0),
                  shard_size=100)
    assert card["runs"][0]["masks_shipped"] is True
    train = json.loads((tmp_path / "shipped" / "coco" / "annotations" / "instances_train.json")
                       .read_text(encoding="utf-8"))
    image_id = next(im["id"] for im in train["images"] if im["file_name"] == f"{key}.png")
    ann = next(a for a in train["annotations"] if a["image_id"] == image_id)
    assert ann["mask_pixels"] == 24000
    decoded = coco_mask.decode(coco_mask.frPyObjects(ann["segmentation"], height, width))
    assert decoded.shape == (height, width) and int(decoded.sum()) == 24000
    assert decoded[50:170, 100:300].all() and not decoded[:50].any() and not decoded[:, :100].any()
    with_mask = sum(1 for a in train["annotations"] if "segmentation" in a)
    assert with_mask == 1 and len(train["images"]) == n
    members = read_webdataset(tmp_path / "shipped" / "webdataset")
    assert members[key][1]["mask.png"] == mask_path.read_bytes()
    assert all("mask.png" not in m for k, (_, m) in members.items() if k != key)


# -- refusals by name, the CLI and the card -----------------------------------------------

def test_the_cli_takes_a_format_list_and_refuses_by_name(batch_dir, tmp_path, capsys):
    from flightsim.export import main

    assert parse_formats("coco, yolo,coco") == ["coco", "yolo"]
    with pytest.raises(ExportError) as caught:
        parse_formats("coco,tfrecord")
    assert caught.value.constraint == "export.format"
    out = tmp_path / "ds"
    assert main([str(batch_dir), "--out", str(out), "--format", "coco,yolo", "--labels-only"]) == 0
    text = capsys.readouterr().out
    assert "exported 192 frame(s) from 4 run(s) as coco,yolo" in text and "layout:" in text
    assert (out / "coco" / "annotations" / "instances_train.json").is_file()
    assert (out / "yolo" / "data.yaml").is_file()
    assert not (out / "annotations").exists()
    card = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
    assert card["formats"] == ["coco", "yolo"] and card["layout"] == {"coco": "coco/", "yolo": "yolo/"}
    assert main([str(batch_dir), "--out", str(tmp_path / "bad"), "--format", "coco,tfrecord",
                 "--labels-only"]) == 2
    assert "REFUSED -- export.format" in capsys.readouterr().out
    # An unverified run refuses BY NAME, for the new formats too.
    copy = tmp_path / "unverified"
    shutil.copytree(_runs(batch_dir)[0], copy)
    (copy / VERIFICATION_FILE).unlink()
    assert main([str(copy), "--out", str(tmp_path / "u"), "--format", "yolo,voc", "--labels-only"]) == 2
    assert "REFUSED -- export.unverified:" in capsys.readouterr().out
    with pytest.raises(ExportError) as caught:
        export([copy], tmp_path / "u2", "voc", labels_only=True)
    assert caught.value.constraint == "export.unverified"
    assert "labels nobody checked" in caught.value.message
    assert not (tmp_path / "u2").exists()


def test_the_card_carries_counts_conditions_licences_and_the_split_policy(batch_dir, tmp_path):
    card = export([batch_dir], tmp_path / "ds", "voc", fractions=(0.5, 0.25, 0.25), seed=7,
                  labels_only=True)
    assert card["images"] == card["frames"] == 192
    assert card["instances"] == sum(c["instances"] for c in card["class_balance"].values())
    assert card["instances"] > 0
    per_split = card["class_balance"]["B747"]["per_split"]
    assert sum(p["instances"] for p in per_split.values()) == card["instances"]
    assert card["split"]["seed"] == 7 and card["split"]["by"] == "simulation_digest"
    assert "one side" in card["split"]["policy"]
    stated = card["conditions"]["stated"]
    assert {float(json.loads(v)) for v in stated["altitude"]["values"]} == {1500.0, 3000.0}
    assert sum(stated["altitude"]["values"].values()) == 4
    sampled = card["conditions"]["sampled"]
    assert card["conditions"]["randomised_runs"] == sorted(r["name"] for r in card["runs"])
    assert sampled["sun_elevation_deg"]["n"] == 4
    assert sampled["sun_elevation_deg"]["min"] <= sampled["sun_elevation_deg"]["max"]
    assert sampled["livery"] == {"default": 4}
    licences = card["licences"]
    assert len(licences) == 1 and licences[0]["licence"] == "GPL-2.0"
    assert licences[0]["asset"] == "assets/aircraft_config/B747.json"
    assert sorted(licences[0]["runs"]) == sorted(r["name"] for r in card["runs"])
    for run in card["runs"]:
        assert run["seed"] in (1, 2)
        assert run["verification"]["status"] == "passed"
        assert run["masks_shipped"] is False
    assert card["label_conventions_by_manifest_version"] == {"5": card["label_conventions"]}
    assert card["not_claimed_from_labels"] == {}
    assert card["not_claimed_extent_px"] == NOT_CLAIMED_EXTENT_PX
    text = (tmp_path / "ds" / "DATASET_CARD.md").read_text(encoding="utf-8")
    for heading in ("## Class balance", "## Conditions", "## Licences", "## Not claimed"):
        assert heading in text
    assert "GPL-2.0" in text and "voc bndbox" in text
