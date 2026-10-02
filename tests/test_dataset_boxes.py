"""The 2-D box of record: derived from the engine ID mask, with the
projected box kept beside it, in every export format -- and the export's
refusal of engine labels whose annotation gates never ran.

The run is tests/test_annotation_gates.py's fabricated manifest-6 bundle
(a 747, an A320 crossing 400 m ahead, the terrain; two cameras): the
producer's manifest, an ID image / depth / alone passes painted by that
file's own arithmetic, ``attach_engine_labels`` filling each object
record's ``bbox_2d_tight``, then the real verifier (every annotation gate
PASS, asserted) and its verdict bound to the manifest. The expected boxes
are read from ``capture_manifest.json`` with json; every format is read
back with code that is not the writer: pycocotools for COCO, the
``webdataset`` package's own reader for the shards, xml.etree for VOC,
line readers for YOLO and KITTI (requirements-dev.txt; a reader that is
absent skips by name).

The licence gate is not this file's subject (tests/test_licence.py): the
fixture's airframes are GPL meshes, which refuse any format that ships
the ID mask, so ``mesh_drawn`` is patched to "no mesh drawn" for the
exports here -- stated, not hidden.

What is NOT measured: an engine's own ID image (none in this container);
the boxes here are a box-shaped airframe's silhouette, so mask and
projection differ only by the pixel quantisation and by occlusion.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml

from core.capture import labels as producer
from core.capture.verify import PASS, verify_run, write_verification
from core.dataset.export import (
    ANNOTATION_GATES, BOX_MASK, BOX_PROJECTED, ExportError, bind_verification,
    engine_label_evidence, export, load_run,
)

FORMATS = "coco,kitti,webdataset,yolo,voc"


# -- the fixture ----------------------------------------------------------------

@pytest.fixture(scope="module")
def engine_run(tmp_path_factory):
    from tests.test_annotation_gates import fabricate_run

    run = tmp_path_factory.mktemp("boxes") / "engine_run"
    fabricate_run(run)
    report = verify_run(run)
    statuses = {c.name: c.status for c in report.checks}
    assert report.ok
    assert all(statuses[name] == PASS for name in ANNOTATION_GATES), statuses
    write_verification(report, run)
    bind_verification(run)
    return run


@pytest.fixture
def no_mesh_licence(monkeypatch):
    """The fixture's GPL airframes are drawn meshes; the licence gate
    (tests/test_licence.py's subject) would refuse every mask-shipping
    format. Patched to "no mesh drawn" for the box round trips only."""
    import core.assets.licence as licence

    monkeypatch.setattr(licence, "mesh_drawn", lambda manifest, render: False)


def _manifest(run: Path):
    return json.loads((run / "capture_manifest.json").read_text(encoding="utf-8"))


def _area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _expected(run: Path):
    """{key: [(int_id, class name, box of record, projected box, source)]}
    straight from the manifest: the tight box where the record carries
    one, else the projected bbox_2d; objects without a box left out;
    primary first, then by int_id (the exporter's order)."""
    manifest = _manifest(run)
    classes = {int(o["int_id"]): o["class"] for o in manifest["objects"]}
    roles = {int(o["int_id"]): o["role"] for o in manifest["objects"]}
    out = {}
    for record in manifest["frames"]:
        key = f"{run.name}_{record['camera_id']}_{int(record['index']):04d}"
        rows = []
        for entry in record["labels"]["objects"]:
            int_id = int(entry["int_id"])
            projected = entry["bbox_2d"]
            tight = entry["bbox_2d_tight"]
            box, source = (tight, BOX_MASK) if tight is not None else (projected, BOX_PROJECTED)
            if box is None:
                continue
            rows.append((int_id, classes[int_id], box, projected, source))
        rows.sort(key=lambda r: (roles[r[0]] != "primary", r[0]))
        out[key] = (rows, int(record["width_px"]), int(record["height_px"]), record)
    return out


# -- independent readers ----------------------------------------------------------

def read_shards_with_webdataset(root: Path):
    """Every sample of every shard through the ``webdataset`` package's own
    tar reader (``webdataset.WebDataset``, no shuffle, no decoding):
    {key: (split, {extension: bytes})}."""
    wds = pytest.importorskip("webdataset", reason="webdataset (requirements-dev.txt) is "
                                                   "the independent shard reader")
    out = {}
    for split in ("train", "val", "test"):
        shards = sorted(str(p) for p in (root / split).glob("shard-*.tar")) \
            if (root / split).is_dir() else []
        if not shards:
            continue
        for sample in wds.WebDataset(shards, shardshuffle=False, empty_check=False):
            key = sample["__key__"]
            assert key not in out, f"{key} in two shards"
            out[key] = (split, {k: v for k, v in sample.items() if not k.startswith("__")})
    return out


def _yolo(root: Path):
    data = yaml.safe_load((root / "data.yaml").read_text(encoding="utf-8"))
    out = {}
    for txt in sorted((root / "labels" / "train").glob("*.txt")):
        out[txt.stem] = [tuple(float(v) if i else int(v) for i, v in enumerate(line.split()))
                         for line in txt.read_text(encoding="utf-8").splitlines()]
    return data["names"], out


def _voc(root: Path):
    out = {}
    for xml in sorted((root / "Annotations").glob("*.xml")):
        tree = ET.parse(xml).getroot()
        out[xml.stem] = [(o.find("name").text, int(o.find("truncated").text),
                          tuple(int(o.find("bndbox").find(k).text)
                                for k in ("xmin", "ymin", "xmax", "ymax")))
                         for o in tree.findall("object")]
    return out


def _kitti(root: Path):
    return {txt.stem: [line.split() for line in txt.read_text(encoding="utf-8").splitlines()]
            for txt in sorted((root / "train" / "label_2").glob("*.txt"))}


# -- the box of record ------------------------------------------------------------------

def test_the_fixture_has_mask_boxes_that_differ_from_the_projected_ones(engine_run):
    """Not vacuous: the records carry tight boxes, some object has one
    that is not its projected box (quantisation, occlusion), and some
    object with a projected box has no mask box (nothing of it visible)."""
    rows = [entry for r in _manifest(engine_run)["frames"] for entry in r["labels"]["objects"]]
    tight = [e for e in rows if e["bbox_2d_tight"] is not None]
    assert tight
    assert any(e["bbox_2d"] is not None and e["bbox_2d"] != e["bbox_2d_tight"] for e in tight)
    assert all(isinstance(e["basis"]["engine"], dict) for e in rows)


def test_every_format_writes_the_mask_box_and_keeps_the_projected_one(
        engine_run, tmp_path, no_mesh_licence):
    coco_api = pytest.importorskip("pycocotools.coco", reason="pycocotools (requirements-dev.txt) "
                                                              "is the independent COCO reader")
    out = tmp_path / "ds"
    card = export([engine_run], out, FORMATS, fractions=(1.0, 0.0, 0.0), labels_only=True,
                  shard_size=4)
    expected = _expected(engine_run)
    n_mask = sum(1 for rows, *_ in expected.values() for r in rows if r[4] == BOX_MASK)
    n_projected = sum(1 for rows, *_ in expected.values() for r in rows if r[4] == BOX_PROJECTED)
    assert n_mask > 0
    # The card: the rule, the counts, the run the mask boxes came from.
    boxes = card["box_source"]
    assert boxes["counts"] == {"mask": n_mask, "projected": n_projected, "landcover": 0}
    assert boxes["mask_runs"] == [engine_run.name]
    assert "derived from the engine ID mask" in boxes["rule"]
    assert card["instances"] == n_mask + n_projected
    text = (out / "DATASET_CARD.md").read_text(encoding="utf-8")
    assert f"2-D boxes: {n_mask} from the ID mask" in text
    taxonomy = card["classes"]
    # COCO through pycocotools: the bbox is the mask's, the projected one beside it.
    coco = coco_api.COCO(str(out / "coco" / "annotations" / "instances_train.json"))
    assert [(c["id"], c["name"]) for c in coco.loadCats(coco.getCatIds())] == \
        list(enumerate(taxonomy, start=1))
    assert len(coco.getImgIds()) == len(expected)
    for image in coco.loadImgs(coco.getImgIds()):
        rows, *_ = expected[image["file_name"][:-len(".png")]]
        anns = coco.loadAnns(coco.getAnnIds(imgIds=[image["id"]]))
        assert len(anns) == len(rows)
        for ann, (_, name, box, projected, source) in zip(anns, rows):
            assert coco.loadCats(ann["category_id"])[0]["name"] == name
            x, y, w, h = ann["bbox"]
            assert (x, y, x + w, y + h) == pytest.approx(tuple(box), abs=1e-9)
            if source == BOX_MASK:
                assert ann["bbox_source"] == "mask"
                if projected is None:
                    assert ann["bbox_projected"] is None
                else:
                    px, py, pw, ph = ann["bbox_projected"]
                    assert (px, py, px + pw, py + ph) == pytest.approx(tuple(projected), abs=1e-9)
            else:
                assert "bbox_source" not in ann and "bbox_projected" not in ann
    # YOLO: the normalised line is the mask box to well under a pixel.
    names, yolo = _yolo(out / "yolo")
    assert names == dict(enumerate(taxonomy))
    for key, (rows, width, height, _) in expected.items():
        lines = yolo[key]
        assert [taxonomy[line[0]] for line in lines] == [r[1] for r in rows]
        for (c, cx, cy, w, h), (_, _, box, _, _) in zip(lines, rows):
            got = ((cx - w / 2) * width, (cy - h / 2) * height,
                   (cx + w / 2) * width, (cy + h / 2) * height)
            assert got == pytest.approx(tuple(box), abs=0.005), key
    # VOC: a mask box sits on pixel edges, so the devkit box is exact.
    voc = _voc(out / "voc")
    for key, (rows, *_) in expected.items():
        assert [o[0] for o in voc[key]] == [r[1] for r in rows]
        for (_, _, bndbox), (_, _, box, _, source) in zip(voc[key], rows):
            if source == BOX_MASK:
                assert bndbox == (int(box[0]) + 1, int(box[1]) + 1, int(box[2]), int(box[3]))
    # KITTI: the 2-D box fields of each aircraft line are the mask's.
    kitti = _kitti(out / "kitti")
    for key, (rows, *_) in expected.items():
        aircraft = [r for r in rows if r[1] == "aircraft"]
        assert len(kitti[key]) == len(aircraft)
        for line, (_, _, box, _, _) in zip(kitti[key], aircraft):
            assert [float(v) for v in line[4:8]] == pytest.approx(box, abs=0.005)
    # WebDataset through its own reader: counts, classes and boxes.
    samples = read_shards_with_webdataset(out / "webdataset")
    assert set(samples) == set(expected)
    assert len(list((out / "webdataset" / "train").glob("shard-*.tar"))) == \
        math.ceil(len(expected) / 4)
    seen_classes = set()
    for key, (split, members) in samples.items():
        rows, *_ = expected[key]
        assert split == "train" and {"json", "mask.png"} <= set(members)
        sidecar = json.loads(members["json"])
        objects = sidecar["export"]["objects"]
        assert [(o["int_id"], o["class"], o["bbox_2d"], o["bbox_2d_projected"], o["bbox_source"])
                for o in objects if o["bbox_2d"] is not None] == \
            [(i, name, box, projected, source) for i, name, box, projected, source in rows]
        seen_classes |= {o["class"] for o in objects}
        primary = rows[0] if rows and rows[0][0] == 1 else None
        if primary is not None and primary[4] == BOX_MASK:
            assert sidecar["export"]["labels"]["bbox_2d"] == primary[2]
            assert sidecar["export"]["labels"]["bbox_2d_projected"] == primary[3]
            assert sidecar["export"]["labels"]["bbox_source"] == "mask"
    assert seen_classes <= set(taxonomy) and {"aircraft", "terrain"} <= seen_classes


def test_the_sensor_image_keeps_the_projected_box(engine_run, tmp_path, no_mesh_licence):
    """The ID image is drawn through the ideal pinhole: under --image
    sensor the box of record is the sensor-mapped projected one, and the
    card counts no mask box."""
    from PIL import Image

    run = tmp_path / "sensor_run"
    shutil.copytree(engine_run, run)
    for record in _manifest(run)["frames"]:
        path = run / record["file"]
        path = path.with_name(path.stem + "_sensor.png")
        Image.new("RGB", (int(record["width_px"]), int(record["height_px"]))).save(path)
    card = export([run], tmp_path / "ds", "yolo", fractions=(1.0, 0.0, 0.0), image="sensor")
    assert card["box_source"]["counts"]["mask"] == 0
    assert card["box_source"]["projected_runs"] == [run.name]
    assert any("not the pixels" in item for item in card["not_claimed"])


def test_a_headless_run_keeps_the_projected_box_and_the_card_says_so(engine_run, tmp_path):
    """No engine labels in the records (the manifest before
    attach_engine_labels): every box is the projected one, no COCO
    annotation carries bbox_source, and the card names the run."""
    run = tmp_path / "headless_run"
    run.mkdir()
    manifest = _manifest(engine_run)
    for record in manifest["frames"]:
        for entry in record["labels"]["objects"]:
            for key in producer.ENGINE_LABEL_KEYS:
                entry[key] = [] if key == "occluded_by" else None
            entry["basis"]["engine"] = producer.NO_BUNDLE_BASIS
    (run / "capture_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    write_verification(verify_run(run), run)
    bind_verification(run)
    assert engine_label_evidence(run, manifest) is None
    card = export([run], tmp_path / "ds", "coco", fractions=(1.0, 0.0, 0.0), labels_only=True)
    assert card["box_source"]["counts"]["mask"] == 0 and card["box_source"]["counts"]["projected"]
    assert card["box_source"]["projected_runs"] == [run.name]
    payload = json.loads((tmp_path / "ds" / "annotations" / "instances_train.json")
                         .read_text(encoding="utf-8"))
    assert payload["annotations"] and not any("bbox_source" in a for a in payload["annotations"])
    assert "no engine mask box in any record" in \
        (tmp_path / "ds" / "DATASET_CARD.md").read_text(encoding="utf-8")


# -- engine labels with their gates NOT RUN refuse -------------------------------------------

def test_engine_labels_whose_gates_did_not_run_refuse_by_name(engine_run, tmp_path):
    """The bundle's files gone, the records still carrying what was
    measured from them: the verifier reports every annotation gate NOT
    RUN and the verdict is ok (NOT RUN is no failure), so before this
    refusal the run exported its unchecked mask boxes."""
    run = tmp_path / "bare"
    run.mkdir()
    shutil.copy(engine_run / "capture_manifest.json", run / "capture_manifest.json")
    report = verify_run(run)
    assert report.ok
    assert all(c.status == "NOT RUN" for c in report.checks if c.name in ANNOTATION_GATES)
    write_verification(report, run)
    bind_verification(run)
    with pytest.raises(ExportError) as caught:
        load_run(run)
    assert caught.value.constraint == "export.annotation_not_run"
    assert "mask_integers_only NOT RUN" in caught.value.message
    assert "engine-derived labels" in caught.value.message
    with pytest.raises(ExportError) as caught:
        export([run], tmp_path / "ds", "yolo", labels_only=True)
    assert caught.value.constraint == "export.annotation_not_run"
    assert not (tmp_path / "ds").exists()


def test_a_verdict_without_the_gates_refuses_and_one_with_them_loads(engine_run, tmp_path):
    """An older verifier wrote no annotation gate at all: refused, naming
    each as absent. The full verdict on the same run loads."""
    run = tmp_path / "older"
    shutil.copytree(engine_run, run)
    assert load_run(run).name == "older"
    path = run / "verification.json"
    verdict = json.loads(path.read_text(encoding="utf-8"))
    verdict["checks"] = [c for c in verdict["checks"] if c["name"] != "box_vs_mask"]
    path.write_text(json.dumps(verdict), encoding="utf-8")
    with pytest.raises(ExportError) as caught:
        load_run(run)
    assert caught.value.constraint == "export.annotation_not_run"
    assert "box_vs_mask absent" in caught.value.message
    assert "mask_integers_only" not in caught.value.message


def test_a_render_json_bundle_counts_and_a_run_without_one_is_unaffected(engine_run, tmp_path):
    """A label bundle declared only by render.json (the records not yet
    completed) is evidence too; a run with neither is untouched."""
    run = tmp_path / "declared"
    run.mkdir()
    manifest = _manifest(engine_run)
    for record in manifest["frames"]:
        for entry in record["labels"]["objects"]:
            entry["basis"]["engine"] = producer.NO_BUNDLE_BASIS
    (run / "capture_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    write_verification(verify_run(run), run)
    bind_verification(run)
    assert engine_label_evidence(run, manifest) is None
    assert load_run(run).name == "declared"                  # no bundle: not affected
    camera = manifest["frames"][0]["camera_id"]
    (run / "frames" / camera).mkdir(parents=True)
    (run / "frames" / camera / "render.json").write_text(json.dumps({
        "host": "unreal", "frame_records": [
            {"frame": "frame_0000.png", "labels": {"mask": "frame_0000_mask.png"}}]}),
        encoding="utf-8")
    assert "render.json declares label files" in engine_label_evidence(run, manifest)
    with pytest.raises(ExportError) as caught:
        load_run(run)
    assert caught.value.constraint == "export.annotation_not_run"


# -- fraction_in_frame: written by the producer ------------------------------------------------

def test_every_object_record_carries_fraction_in_frame_beside_truncation(engine_run):
    """clipped area / unclipped area for every aircraft record, the
    complement of truncation, null with it (terrain); and it agrees with
    truncation on whether the object leaves the frame."""
    checked = 0
    for record in _manifest(engine_run)["frames"]:
        for entry in record["labels"]["objects"]:
            assert "fraction_in_frame" in entry
            fraction, truncation = entry["fraction_in_frame"], entry["truncation"]
            if truncation is None:
                assert fraction is None
                continue
            box, unclipped = entry["bbox_2d"], entry["bbox_2d_unclipped"]
            expected = _area(box) / _area(unclipped) if box else 0.0
            assert fraction == pytest.approx(expected, abs=1e-12)
            assert fraction + truncation == pytest.approx(1.0, abs=1e-12)
            assert (fraction < 1.0) == (truncation > 0.0)
            checked += 1
    assert checked > 0


def test_fraction_in_frame_is_the_area_ratio_and_null_with_the_unclipped_box():
    assert producer.fraction_in_frame([0.0, 0.0, 50.0, 100.0], [-50.0, 0.0, 50.0, 100.0]) == 0.5
    assert producer.fraction_in_frame([0.0, 0.0, 10.0, 10.0], [0.0, 0.0, 10.0, 10.0]) == 1.0
    assert producer.fraction_in_frame(None, [-20.0, 0.0, -10.0, 10.0]) == 0.0
    assert producer.fraction_in_frame(None, None) is None
    assert producer.fraction_in_frame(None, [5.0, 5.0, 5.0, 9.0]) == 0.0     # zero area: out
    assert "fraction_in_frame" in producer.conventions()


def test_the_v7_schema_takes_fraction_in_frame_and_refuses_one_out_of_range():
    from core.capture.schema import SCHEMA_DIR, load_schema, validate

    node = load_schema(SCHEMA_DIR / "capture_manifest.v7.schema.json")["$defs"]["object_label"]
    prop = node["properties"]["fraction_in_frame"]
    assert "fraction_in_frame" not in node["required"]        # optional: older records validate
    assert validate(0.25, prop) == [] and validate(None, prop) == []
    assert validate(1.5, prop) and validate(-0.1, prop)
