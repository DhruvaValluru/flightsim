"""W4: the per-asset licence gate (core/assets/licence.py), the export that
runs it before any file is written (core/dataset/export.py), and the
capture's world documents whose licence records it reads
(flightsim/capture.py ``_world_documents``: the runway pad and record, the
buildings document).

Every asset a dataset ships carries a licence record {licence, spdx,
source, attribution, ml_use, reaches}; a shipped asset with no record, a
licence forbidding machine-learning use, or a licence off the stated
allow-list refuses the export BY NAME -- aircraft.licence_dataset (every
GPL airframe in this tree, when its mesh was drawn), aircraft.licence_noai,
asset.licence -- and nothing is written. The verdicts are the records'
words, not legal advice; the tests pin the table and the arithmetic, not
the law.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.assets import licence as lic

REPO = Path(__file__).resolve().parents[1]

ENGINE = {"pixels": True, "label_files": True, "labels": False, "mesh_drawn": True}
PHYSICS_ONLY = {"pixels": False, "label_files": False, "labels": False, "mesh_drawn": False}


def write_config(directory: Path, name: str, licence, ml_use=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    block = {"license_name": licence, "file": "LICENSE", "repo": f"https://example.org/{name}",
             "commit": "0" * 40, "authors_file": "AUTHORS"}
    if ml_use is not None:
        block["ml_use"] = ml_use
    path = directory / f"{name}.json"
    path.write_text(json.dumps({"name": name, "license": block}), encoding="utf-8")
    return path


def write_sidecar(directory: Path, stem: str, provenance) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}.json").write_text(json.dumps(
        {"name": stem, "sha256": "1" * 64, "provenance": provenance}), encoding="utf-8")
    return directory / stem


def one(result):
    (verdict,) = result["verdicts"]
    return verdict


# -- the table ------------------------------------------------------------------

def test_the_allow_list_is_stated_and_the_gpl_family_is_off_it():
    assert {"CC-BY-4.0", "CC0-1.0", lic.PUBLIC_DOMAIN, lic.OWN, lic.SYNTHETIC} <= set(lic.ALLOW_LIST)
    for name in ("GPL-2.0", "GPL-3.0-or-later", "LGPL-2.1", "AGPL-3.0"):
        spdx = lic.normalise_licence(name)
        assert lic.is_copyleft_code(spdx) and lic.allow_list_entry(spdx) is None
    assert lic.normalise_licence("CC BY 4.0") == "CC-BY-4.0"
    assert lic.normalise_licence("cc0") == "CC0-1.0"
    assert lic.normalise_licence("synthetic") == lic.SYNTHETIC
    assert lic.normalise_licence("Copernicus DEM licence") == lic.COPERNICUS_DEM
    assert lic.normalise_licence("CC-BY-NC-4.0") == "CC-BY-NC-4.0"       # unknown: kept, off the list
    assert lic.normalise_licence(None) is None and lic.normalise_licence("  ") is None
    # A licence silent on machine learning reads unknown -- never yes.
    assert lic.default_ml_use("CC-BY-4.0") == "unknown"
    assert lic.default_ml_use("CC0-1.0") == "allowed"
    assert lic.default_ml_use("GPL-2.0") == "unknown"
    for entry in lic.ALLOW_LIST.values():
        assert entry["ml_use"] in lic.ML_USE and entry["basis"]
    assert any("not legal advice" in line for line in lic.NOT_CLAIMED)


def test_every_committed_airframe_record_reads_its_config():
    configs = sorted((REPO / "assets" / "aircraft_config").glob("*.json"))
    assert configs
    for path in configs:
        record = lic.airframe_record(path.stem)
        block = json.loads(path.read_text(encoding="utf-8"))["license"]
        assert record["asset"] == f"airframe:{path.stem}" and record["kind"] == "airframe"
        assert record["licence"] == block["license_name"]
        assert record["source"].startswith(block["repo"])
        assert record["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert record["reaches"] == ["pixels", "label_files"]
    assert lic.airframe_record("c172p")["spdx"] == "GPL-2.0"
    missing = lic.airframe_record("no_such_airframe")
    assert missing["licence"] is None and "no config" in missing["note"]


# -- the gate: the three refusals, by name ---------------------------------------------

def test_a_drawn_gpl_airframe_refuses_and_a_physics_only_one_is_not_shipped():
    record = lic.airframe_record("c172p")
    result = lic.gate([("run", [record], ENGINE)])
    verdict = one(result)
    assert verdict["verdict"] == "refused" and verdict["refusal"] == "aircraft.licence_dataset"
    assert "GPL" in verdict["reason"] and result["refused"] == [verdict]
    with pytest.raises(lic.LicenceError) as caught:
        lic.enforce(result)
    assert caught.value.constraint == "aircraft.licence_dataset"
    assert "Nothing was written" in caught.value.message and "not legal advice" in caught.value.message
    # Flown physics-only: nothing licensed is in the dataset -- not shipped, said why.
    idle = one(lic.gate([("run", [record], PHYSICS_ONLY)]))
    assert idle["verdict"] == "not shipped" and idle["refusal"] is None
    assert idle["would_refuse"] == "aircraft.licence_dataset"
    lic.enforce(lic.gate([("run", [record], PHYSICS_ONLY)]))
    # Pixels shipped but a placeholder drawn: no licensed geometry in them.
    boxes = one(lic.gate([("run", [record], dict(ENGINE, mesh_drawn=False))]))
    assert boxes["verdict"] == "not shipped" and "no mesh" in " ".join(boxes["shipped_as"])


def test_a_licence_forbidding_ml_use_refuses_noai_before_the_allow_list(tmp_path):
    configs = tmp_path / "configs"
    write_config(configs, "open", "CC-BY-4.0")
    write_config(configs, "noai", "CC-BY-4.0", ml_use="forbidden")
    write_config(configs, "gplnoai", "GPL-3.0", ml_use="forbidden")
    allowed = one(lic.gate([("run", [lic.airframe_record("open", configs)], ENGINE)]))
    assert allowed["verdict"] == "allowed" and allowed["ml_use"] == "unknown"
    assert allowed["obligations"][0].startswith("attribution: the authors listed in AUTHORS")
    assert allowed["distribution"]["name"] == "Creative Commons Attribution 4.0"
    for name in ("noai", "gplnoai"):
        verdict = one(lic.gate([("run", [lic.airframe_record(name, configs)], ENGINE)]))
        assert verdict["refusal"] == "aircraft.licence_noai" and "machine-learning" in verdict["reason"]
    livery = lic.airframe_record("noai", configs, kind="livery", asset="livery:noai:red")
    assert one(lic.gate([("run", [livery], ENGINE)]))["refusal"] == "aircraft.licence_noai"
    # A scene asset that forbids it refuses asset.licence (the aircraft names are the airframes').
    imagery = lic.record("imagery:x", "imagery", "CC-BY-4.0", "a source", "a line", ("pixels",),
                         ml_use="forbidden")
    assert one(lic.gate([("run", [imagery], ENGINE)]))["refusal"] == "asset.licence"


def test_scene_assets_without_a_record_or_off_the_list_refuse_asset_licence(tmp_path):
    unknown = lic.terrain_record(write_sidecar(tmp_path, "mystery", {"source": "a disk"}))
    assert unknown["licence"] is None and "states no licence" in unknown["note"]
    verdict = one(lic.gate([("run", [unknown], ENGINE)]))
    assert verdict["refusal"] == "asset.licence" and "no licence record" in verdict["reason"]
    off = lic.record("terrain:nc", "terrain", "CC-BY-NC-4.0", "a source", None, ("pixels",))
    verdict = one(lic.gate([("run", [off], ENGINE)]))
    assert verdict["refusal"] == "asset.licence" and "not on the allow-list" in verdict["reason"]
    # Labels only: terrain reaches pixels and engine label files, none ship.
    assert one(lic.gate([("run", [unknown], PHYSICS_ONLY)]))["verdict"] == "not shipped"
    # The recognised terrains: GLO-30 (attribution owed) and the project's own.
    glo = lic.terrain_record(write_sidecar(tmp_path, "glo", {
        "dataset": "Copernicus GLO-30 DSM (30 m surface model)", "attribution": "(c) DLR / ESA"}))
    assert glo["spdx"] == lic.COPERNICUS_DEM
    verdict = one(lic.gate([("run", [glo], ENGINE)]))
    assert verdict["verdict"] == "allowed" and verdict["obligations"] == ["attribution: (c) DLR / ESA"]
    own = lic.terrain_record(write_sidecar(tmp_path, "ridge", {"producer": "spectral synthesis"}))
    assert own["spdx"] == lic.OWN and one(lic.gate([("run", [own], ENGINE)]))["verdict"] == "allowed"
    assert lic.terrain_record(None) is None
    assert lic.terrain_record(tmp_path / "absent")["licence"] is None


def test_the_land_cover_ships_through_its_labels_with_its_attribution(tmp_path):
    from tests.test_landcover_labels import write_world

    _, document, _ = write_world(tmp_path)
    record = lic.landcover_record(document)
    assert record["kind"] == "land_cover" and record["spdx"] == "CC-BY-4.0"
    assert record["reaches"] == ["labels"] and record["ml_use"] == "unknown"
    shipped = one(lic.gate([("run", [record], dict(PHYSICS_ONLY, labels=True))]))
    assert shipped["verdict"] == "allowed" and shipped["shipped_as"] == ["a label derived from it ships"]
    assert shipped["obligations"][0].startswith("attribution: (c) ESA WorldCover project 2021")
    # Pixels and engine label files do not carry it (nothing engine-side draws it yet).
    assert one(lic.gate([("run", [record], dict(ENGINE, labels=False))]))["verdict"] == "not shipped"


def test_one_verdict_per_asset_over_runs_and_the_record_is_bounded():
    record = lic.airframe_record("c172p")
    result = lic.gate([("a", [record], PHYSICS_ONLY), ("b", [record], ENGINE)])
    verdict = one(result)
    assert verdict["runs"] == ["a", "b"] and verdict["verdict"] == "refused"
    assert verdict["shipped_as"] == ["a drawn mesh in the shipped pixels and label files"]
    variable = lic.gate_record(lic.gate([("a", [record], PHYSICS_ONLY)]), 0, 12)
    assert variable.name == "dataset.licences" and variable.value == "allowed"
    assert variable.null_test.kind == "bounded" and variable.null_test.ok
    assert variable.parameters["counts"] == {"allowed": 0, "refused": 0, "not shipped": 1}
    assert not lic.gate_record(result, 1, 12).null_test.ok       # a label changed by the gate


# -- the export: the gate before any file is written ----------------------------------

def fabricated_run(tmp_path, name, drawn=None, licences=None, images=True):
    """A verified c172p run from the real manifest builder (a synthetic
    northbound flight, two chase frames), with its frames drawn as flat
    PNGs and, with ``drawn``, a render.json whose ``drawn.kind`` says what
    the engine drew."""
    from core.capture.manifest import write_capture_manifest, write_frame_sidecars
    from core.dataset.export import bind_verification
    from tests.test_capture_objects import manifest_with, spec_with

    manifest = manifest_with(spec_with(aircraft="c172p", count=2))
    if licences is not None:
        manifest["licences"] = licences
    run = tmp_path / name
    write_capture_manifest(manifest, run)
    write_frame_sidecars(manifest, run)
    (run / "verification.json").write_text(json.dumps(
        {"ok": True, "passed": 0, "failed": 0, "not_run": 0, "checks": []}), encoding="utf-8")
    for record in manifest["frames"]:
        if images:
            path = run / record["file"]
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.full((int(record["height_px"]), int(record["width_px"]), 3), 90,
                                    np.uint8)).save(path)
    if drawn is not None:
        for camera in sorted({r["camera_id"] for r in manifest["frames"]}):
            folder = run / "frames" / camera
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "render.json").write_text(json.dumps(
                {"host": "unreal", "frames": 0, "frame_records": [], "drawn": {"kind": drawn}}),
                encoding="utf-8")
    bind_verification(run)
    return run


def test_the_export_refuses_a_drawn_gpl_mesh_before_any_file_is_written(tmp_path, capsys):
    from core.dataset.export import ExportError, export
    from flightsim.export import main

    run = fabricated_run(tmp_path, "gpl_mesh", drawn="mesh")
    with pytest.raises(ExportError) as caught:
        export([run], tmp_path / "ds", "yolo", fractions=(1.0, 0.0, 0.0))
    assert caught.value.constraint == "aircraft.licence_dataset"
    assert "airframe:c172p" in caught.value.message
    assert not (tmp_path / "ds").exists()
    assert main([str(run), "--out", str(tmp_path / "cli"), "--format", "coco",
                 "--split", "1,0,0"]) == 2
    assert "REFUSED -- aircraft.licence_dataset:" in capsys.readouterr().out
    assert not (tmp_path / "cli").exists()
    # The same run's annotations alone ship no drawn pixel: allowed, the card says why.
    card = export([run], tmp_path / "labels", "yolo", fractions=(1.0, 0.0, 0.0), labels_only=True)
    entries = [e for e in card["licences"] if e.get("verdict")]
    assert entries and {e["verdict"] for e in entries} == {"not shipped"}
    assert all(e["licence"] == "GPL-2.0" and e["refusal"] is None for e in entries)
    gate = card["licence_gate"]
    assert gate["counts"] == {"allowed": 0, "refused": 0, "not shipped": 1}
    assert gate["record"]["name"] == "dataset.licences" and gate["record"]["null_test"]["ok"]
    assert gate["record"]["null_test"]["with"] == 0.0
    assert "CC-BY-4.0" in gate["allow_list"] and "GPL-2.0" not in gate["allow_list"]
    text = (tmp_path / "labels" / "DATASET_CARD.md").read_text(encoding="utf-8")
    assert "verdict **not shipped**" in text and "not legal advice" in text


def test_a_scene_asset_with_no_record_refuses_asset_licence_and_a_placeholder_ships(tmp_path):
    from core.dataset.export import ExportError, export

    mystery = lic.record("terrain:mystery", "terrain", None, None, None, ("pixels", "label_files"),
                         note="the bake's provenance states no licence")
    run = fabricated_run(tmp_path, "mystery", drawn="placeholder", licences=[mystery])
    with pytest.raises(ExportError) as caught:
        export([run], tmp_path / "ds", "yolo", fractions=(1.0, 0.0, 0.0))
    assert caught.value.constraint == "asset.licence" and "terrain:mystery" in caught.value.message
    assert not (tmp_path / "ds").exists()
    # The project's own terrain under a placeholder airframe: the dataset ships.
    own = lic.record("terrain:ridge", "terrain", lic.OWN, "synthesised", None,
                     ("pixels", "label_files"))
    run = fabricated_run(tmp_path, "placeholder", drawn="placeholder", licences=[own])
    card = export([run], tmp_path / "ok", "yolo", fractions=(1.0, 0.0, 0.0))
    verdicts = {e["asset"]: e for e in card["licences"] if e.get("verdict")}
    assert verdicts["terrain:ridge"]["verdict"] == "allowed"
    assert verdicts["terrain:ridge"]["reason"] == "in the shipped pixels"
    airframe = [e for e in card["licences"] if e["asset"] == "aircraft:c172p:0"][0]
    assert airframe["verdict"] == "not shipped" and "placeholder" in airframe["reason"]


# -- the capture's world documents (W2, wired by W4) -------------------------------------

def test_the_capture_builds_the_world_documents_and_their_licence_records(tmp_path, monkeypatch):
    from core.capture.manifest import world_scene
    from core.scene import buildings as bd
    from core.scene import runway as rw
    from core.terrain.heightfield import Heightfield
    from flightsim.capture import _world_documents
    from tests import test_buildings as tb
    from tests import test_runway as tr

    spec = tb.spec_for()
    assert _world_documents(spec, None) == {"terrain": None, "buildings_document": None,
                                            "runway_document": None}
    # Buildings over the town bake, from the cached fixture set.
    cache = tmp_path / "cache"
    bd.write_fixture_set(cache, tb.KEY, tb.footprint_records())
    monkeypatch.setattr(bd, "BUILDINGS_DIR", cache)
    spec.set("scene.buildings", tb.KEY, frm="test")
    town = tb.write_bake(tmp_path / "town_dir")
    world = _world_documents(spec, str(town))
    assert world["terrain"] == str(town) and Path(world["buildings_document"]).is_file()
    blocks, records = world_scene({"buildings_document": world["buildings_document"]})
    assert blocks["buildings"]["count"] == 3 and [r.name for r in records] == ["scene.buildings"]
    record = lic.buildings_record(world["buildings_document"])
    assert record["spdx"] == lic.SYNTHETIC and record["ml_use"] == "allowed"
    assert record["reaches"] == ["pixels", "label_files"]
    (refused,) = _world_documents(spec, None)["violations"]
    assert refused.constraint == "scene.terrain"
    # The runway: the pad baked beside the ridge, its record written, the flight over the pad.
    ridge = tr.write_ridge(tmp_path / "ridge_dir")
    runway_spec = tr.spec_with_runway()
    world = _world_documents(runway_spec, str(ridge))
    pad = Path(world["terrain"])
    assert pad.name == "ridge_runway_09" and pad.with_suffix(".r16").is_file()
    document = rw.read_runway_document(world["runway_document"])
    assert document["pad"]["sha256"] == Heightfield.read(pad).digest()
    assert document["pad"]["parent_sha256"] == Heightfield.read(ridge).digest()
    assert document["null_test"] is None and "not measured by the capture" in document["null_test_basis"]
    assert document["markings"]["measurement"]["within_tolerance"]
    card_world = rw.world_card_block(pad, Heightfield.read(pad).digest(), None, world["runway_document"])
    assert card_world["runway"]["designator"] == "09" and card_world["terrain"] == str(pad)
    assert list(world_scene({"runway_document": world["runway_document"]})[0]) == ["runway"]
    scene = lic.scene_licence_records({"terrain": world["terrain"],
                                       "runway_document": world["runway_document"]})
    assert [r["kind"] for r in scene] == ["terrain", "runway_markings"]
    assert all(r["spdx"] == lic.OWN for r in scene)
    (refused,) = _world_documents(runway_spec, None)["violations"]
    assert refused.constraint == "runway.terrain_mismatch"
    (refused,) = _world_documents(tr.spec_with_runway(length_m=50.0), str(ridge))["violations"]
    assert refused.constraint == "runway.geometry"
