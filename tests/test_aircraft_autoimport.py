"""A7: a missing or outdated aircraft mesh is imported by the render
itself; the refusal stays only for a real failure (named). Every test
runs in a throwaway repository layout with a fake importer: no network,
no editor, no converter."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from assets_pipeline import importer
from flightsim import capture


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fake repo: config dir, generated dir, ue content, a converter."""
    (tmp_path / "assets" / "aircraft_config").mkdir(parents=True)
    (tmp_path / "assets" / "generated").mkdir(parents=True)
    (tmp_path / "assets_pipeline").mkdir()
    (tmp_path / "assets_pipeline" / "convert.py").write_text("# converter\n", encoding="utf-8")
    monkeypatch.setattr(importer, "REPO", tmp_path)
    monkeypatch.setattr(importer, "CONFIG_DIR", tmp_path / "assets" / "aircraft_config")
    monkeypatch.setattr(importer, "GENERATED", tmp_path / "assets" / "generated")
    editor = tmp_path / "UnrealEditor-Cmd"
    editor.write_text("", encoding="utf-8")
    monkeypatch.setattr("core.util.platform.ue_editor_path", lambda: editor)
    world = SimpleNamespace(root=tmp_path, editor=editor, calls=[])
    world.add_config = lambda name, unavailable=None: (
        importer.CONFIG_DIR / f"{name}.json").write_text(json.dumps(
            {"license": {"repo": "x", "commit": "c", "unavailable": unavailable}}),
        encoding="utf-8")
    world.build = lambda name: _build(tmp_path, name)
    return world


def _build(root, name):
    out = root / "assets" / "generated" / name
    out.mkdir(parents=True, exist_ok=True)
    config = importer.CONFIG_DIR / f"{name}.json"
    inputs = importer.conversion_inputs(config) if config.is_file() else None
    (out / "mesh_manifest.json").write_text(json.dumps({
        "name": name, "version": importer.MESH_MANIFEST_VERSION,
        importer.OBJ_FRAME_KEY: importer.OBJ_FRAME,
        "mesh_origin_actor_cm": [0, 0, 0],
        importer.INPUTS_KEY: inputs,
        "asset_path_root": f"/Game/Aircraft/{name}", "parts": ["body"]}),
        encoding="utf-8")
    asset = root / "ue" / "Content" / "Aircraft" / name
    asset.mkdir(parents=True, exist_ok=True)
    (asset / "body.uasset").write_text("", encoding="utf-8")
    return out / "mesh_manifest.json"


def _fake_ensure(world, fail=None):
    def ensure(name, report=print):
        world.calls.append(name)
        if fail:
            raise fail
        return world.build(name)
    return ensure


def _traffic(*names):
    return SimpleNamespace(traffic=[SimpleNamespace(
        aircraft=SimpleNamespace(value=n)) for n in names])


def test_missing_mesh_calls_the_importer_not_the_refusal(world, monkeypatch, capsys):
    world.add_config("X")
    monkeypatch.setattr(importer, "ensure_model", _fake_ensure(world))
    assert capture._provision_refusal("X", "primary") is None
    assert world.calls == ["X"]
    assert "import_aircraft.py" not in capsys.readouterr().out


def test_traffic_airframe_is_provisioned(world, monkeypatch):
    world.add_config("X")
    monkeypatch.setattr(importer, "ensure_model", _fake_ensure(world))
    assert capture._traffic_mesh_refusal(_traffic("X", "X")) is None
    assert world.calls == ["X"]            # once per distinct name


def _age(path, seconds):
    stamp = path.stat().st_mtime + seconds
    os.utime(path, (stamp, stamp))


def test_manifest_older_than_config_reimports_once(world, monkeypatch):
    world.add_config("X")
    manifest = world.build("X")
    assert importer.outdated_reason("X") is None
    _age(importer.CONFIG_DIR / "X.json", 100)
    assert "older than X.json" in importer.outdated_reason("X")
    ensure = _fake_ensure(world)
    assert importer.provision_models(["X", "X"], lambda line: None, ensure) == ["X"]
    _age(manifest, 200)                     # the re-convert rewrote it ...
    _age(world.root / "ue" / "Content" / "Aircraft" / "X" / "body.uasset", 200)
    # ... and the re-import that follows it refreshed the asset (C4-2)
    assert importer.provision_models(["X"], lambda line: None, ensure) == []
    assert world.calls == ["X"]


def test_manifest_older_than_converter_reimports_once(world):
    world.add_config("X")
    manifest = world.build("X")
    _age(world.root / "assets_pipeline" / "convert.py", 100)
    assert "older than convert.py" in importer.outdated_reason("X")
    ensure = _fake_ensure(world)
    assert importer.provision_models(["X"], lambda line: None, ensure) == ["X"]
    _age(manifest, 200)
    _age(world.root / "ue" / "Content" / "Aircraft" / "X" / "body.uasset", 200)
    assert importer.provision_models(["X"], lambda line: None, ensure) == []
    assert world.calls == ["X"]


def test_a_reconverted_manifest_reimports_its_assets(world):
    """Packet C4-2: a re-convert left the .uassets older than the manifest
    and the import was skipped, so the editor drew the old mirrored mesh
    against the new hulls. Assets older than their manifest are stale."""
    world.add_config("X")
    manifest = world.build("X")
    assert importer.is_imported("X")
    _age(manifest, 300)                    # re-converted after the import
    assert importer.stale_assets(manifest) == ["X/body"]
    assert not importer.is_imported("X")
    ensure = _fake_ensure(world)
    assert importer.provision_models(["X"], lambda line: None, ensure) == ["X"]
    assert world.calls == ["X"]


def test_converter_error_still_refuses_by_name(world, monkeypatch):
    world.add_config("X")
    error = importer.AircraftAssetError(
        "aircraft.mesh_import", "converting the X model failed (exit 1)")
    monkeypatch.setattr(importer, "ensure_model", _fake_ensure(world, error))
    refusal = capture._provision_refusal("X", "primary")
    assert refusal["constraint"] == "aircraft.mesh_import"
    assert "import failed" in refusal["message"]
    assert "converting the X model failed" in refusal["message"]


def test_missing_licence_still_refuses_without_fetch(world, monkeypatch):
    world.add_config("X", unavailable="upstream ships no licence file")

    def fetch(*args, **kwargs):
        raise AssertionError("fetched an unlicensed model")

    monkeypatch.setattr(importer, "fetch_source", fetch)
    refusal = capture._traffic_mesh_refusal(_traffic("X"))
    assert refusal["constraint"] == "aircraft.mesh"
    assert "can never render" in refusal["message"]
    with pytest.raises(importer.AircraftAssetError):
        importer.ensure_model("X", lambda line: None)


def test_no_editor_runs_nothing_and_does_not_break_headless(world, monkeypatch):
    world.add_config("X")
    monkeypatch.setattr("core.util.platform.ue_editor_path", lambda: None)
    monkeypatch.setattr(importer, "ensure_model", _fake_ensure(world))

    def launched(*args, **kwargs):
        raise AssertionError("a subprocess was launched with no editor")

    monkeypatch.setattr(importer.subprocess, "run", launched)
    lines = []
    assert importer.provision_models(["X"], lines.append) == []
    assert world.calls == []
    assert any("no Unreal editor" in line or "none is installed" in line
               for line in lines)
    refusal = capture._provision_refusal("X", "primary")
    assert refusal["constraint"] == "aircraft.mesh"
    assert "import_aircraft.py" not in refusal["message"]
