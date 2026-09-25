"""The aircraft fail-safe: models the system builds for itself.

Placeholder airframes never render (owner's rule 2026-08-14, extended
2026-08-31). Until 2026-09-01 the cost of that rule was paid by the
USER: a missing model refused the render and handed back a command to
run, once per machine, per airframe ("i cant run commands for every
single mesh they should upload by themselves").

The rule is unchanged. What changed is who does the work: the render
flow provisions a buildable model itself, exactly as it already
synthesises the control ridge. These tests pin the three things that
must remain true afterwards, because they are the ways automation could
quietly become a downgrade:

* what CANNOT be built still refuses, by name, before any editor time;
* what MUST NOT be built (no upstream license, VALIDITY 3.3) is never
  fetched -- automation is not a back door to unattributed geometry;
* a build that FAILS fails the run by name and never reaches a render,
  so the placeholder can never appear as a fallback.
"""

import json
import subprocess
from pathlib import Path

import pytest

from assets_pipeline import importer
from core.nl.compiler import compile_prompt
from webapp.runs import (RunManager, RunState, ensure_aircraft_model,
                         refuse_placeholder_mesh)
import webapp.runs as runs_module


class FakeSubprocess:
    """Stands in for the subprocess module inside the importer, so a test
    can prove a step was never reached rather than merely being slow."""

    CalledProcessError = subprocess.CalledProcessError

    def __init__(self, handler=None) -> None:
        self.calls = []
        self._handler = handler or (lambda cmd, **kw: _Completed(0))

    def run(self, cmd, **kwargs):
        self.calls.append([str(part) for part in cmd])
        return self._handler(cmd, **kwargs)


class _Completed:
    def __init__(self, code: int, out: str = "") -> None:
        self.returncode = code
        self.stdout = out


def write_manifest(tmp_path: Path, name: str = "TEST") -> Path:
    manifest = tmp_path / "assets" / "generated" / name / "mesh_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "name": name, "asset_path_root": f"/Game/Aircraft/{name}",
        "parts": ["fuselage", "wing"]}), encoding="utf-8")
    return manifest


def place_assets(tmp_path: Path, name: str = "TEST", parts=("fuselage",
                                                            "wing")) -> None:
    root = tmp_path / "ue" / "Content" / "Aircraft" / name
    root.mkdir(parents=True, exist_ok=True)
    for part in parts:
        (root / f"{part}.uasset").write_bytes(b"asset")


# -- what automation may not do -----------------------------------------


def test_an_unlicensable_airframe_is_never_fetched(monkeypatch):
    """VALIDITY 3.3, the load-bearing case: the p51d's upstream ships no
    license file, so it may never render -- and the fail-safe must
    refuse it BEFORE the fetch, not discover it at the converter. If
    automation reached upstream first, an unattributed model would be on
    disk whatever happened next."""
    fake = FakeSubprocess()
    monkeypatch.setattr(importer, "subprocess", fake)

    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.ensure_model("p51d", report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh"
    assert "license" in caught.value.message
    assert fake.calls == []             # nothing was fetched, converted, run


def test_an_unconfigured_airframe_refuses_with_nothing_to_build(monkeypatch):
    """No config means nothing to fetch: the refusal stands, and names
    only airframes that can ACTUALLY be built (never the p51d, whose
    refusal no command can fix)."""
    monkeypatch.setattr(runs_module, "renderable_aircraft", lambda: [])
    spec = compile_prompt("fly the f15 at 5000 m and 350 kt")
    refusal = refuse_placeholder_mesh(spec)
    assert refusal is not None
    assert refusal["constraint"] == "aircraft.mesh"
    assert "f15" in refusal["message"]
    assert "B747" in refusal["message"]
    assert "p51d" not in refusal["message"]

    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.ensure_model("f15", report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh"


def test_an_unlicensable_airframe_refuses_at_the_webapp_too(monkeypatch):
    """The same rule at the other door: the run endpoint's refusal for
    the p51d states the license reason, not an import command that would
    never help."""
    monkeypatch.setattr(runs_module, "renderable_aircraft", lambda: [])
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    spec.set("aircraft", "p51d", frm="test: an airframe with no license")
    refusal = refuse_placeholder_mesh(spec)
    assert refusal is not None
    assert refusal["constraint"] == "aircraft.mesh"
    assert "never render" in refusal["message"]
    assert "import_aircraft" not in refusal["message"]


# -- what automation now does -------------------------------------------


def test_a_buildable_airframe_is_no_longer_a_refusal(monkeypatch):
    """The change the user asked for: a configured, licensable airframe
    with no model on this machine does NOT refuse -- the run builds it."""
    monkeypatch.setattr(runs_module, "renderable_aircraft", lambda: [])
    for name in ("c172p", "B747", "A320", "DHC6"):
        spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
        spec.set("aircraft", name, frm="test: a buildable airframe")
        assert refuse_placeholder_mesh(spec) is None, name


def test_the_fail_safe_builds_a_missing_model_once(monkeypatch):
    """Missing -> built, with progress reported; present -> untouched.
    Idempotence is what makes this safe to put on the render path."""
    built = []
    monkeypatch.setattr(importer, "ensure_model",
                        lambda name, report: built.append(name))

    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    lines = []
    monkeypatch.setattr(importer, "is_imported", lambda name: False)
    ensure_aircraft_model(spec, lines.append)
    assert built == ["B747"]
    assert any("B747" in line for line in lines)

    monkeypatch.setattr(importer, "is_imported", lambda name: True)
    ensure_aircraft_model(spec, lines.append)
    assert built == ["B747"]            # already there: no second build


def test_a_failed_build_fails_the_run_by_name_and_never_renders(
        tmp_path, monkeypatch):
    """The rule this fail-safe serves, not one it relaxes: when the model
    cannot be built the run FAILS, named, and the flow stops there. It
    must never continue into a render that would draw placeholders."""
    monkeypatch.setattr(runs_module, "REPO", tmp_path)
    monkeypatch.setattr(runs_module, "ensure_control_ridge", lambda: None)

    def refuse(spec, report):
        raise importer.AircraftAssetError(
            "aircraft.mesh_import", "converting the B747 model failed")

    monkeypatch.setattr(runs_module, "ensure_aircraft_model", refuse)

    def never(spec):
        raise AssertionError("the flow continued past a failed model build")

    monkeypatch.setattr(runs_module, "pick_scene", never)

    run = RunState(run_id="deadbeef")
    manager = RunManager(out_root=tmp_path / "runs")
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    manager._render_flow(run, spec, provenance={})

    assert run.status == "failed"
    assert "aircraft.mesh_import" in run.detail
    assert "B747" in run.detail


# -- verification of the build itself ------------------------------------


def test_missing_assets_reads_the_manifest_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "REPO", tmp_path)
    manifest = write_manifest(tmp_path)
    assert importer.missing_assets(manifest) == ["TEST/fuselage", "TEST/wing"]
    place_assets(tmp_path, parts=("fuselage",))
    assert importer.missing_assets(manifest) == ["TEST/wing"]
    place_assets(tmp_path)
    assert importer.missing_assets(manifest) == []


def test_the_import_verifies_assets_not_the_editor_exit_code(
        tmp_path, monkeypatch):
    """Measured 2026-09-01: a cosmetic texture warning made a completely
    successful four-aircraft import report failure, and an editor that
    logs nothing can still import nothing. Both directions are pinned --
    exit 0 with no assets FAILS, non-zero with every asset PASSES."""
    import core.util.platform as platform_module

    monkeypatch.setattr(importer, "REPO", tmp_path)
    editor = tmp_path / "UnrealEditor-Cmd"
    editor.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setattr(platform_module, "ue_editor_path", lambda: editor)
    manifest = write_manifest(tmp_path)

    monkeypatch.setattr(importer, "subprocess",
                        FakeSubprocess(lambda cmd, **kw: _Completed(0)))
    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.import_manifests([manifest], report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh_import"
    assert "TEST/fuselage" in caught.value.message

    place_assets(tmp_path)
    monkeypatch.setattr(importer, "subprocess",
                        FakeSubprocess(lambda cmd, **kw: _Completed(3)))
    lines = []
    importer.import_manifests([manifest], report=lines.append)
    assert any("exited 3" in line for line in lines)


def test_the_import_refuses_without_an_engine(tmp_path, monkeypatch):
    """No editor is a named refusal, not a crash mid-flow."""
    import core.util.platform as platform_module

    monkeypatch.setattr(importer, "REPO", tmp_path)
    monkeypatch.setattr(platform_module, "ue_editor_path", lambda: None)
    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.import_manifests([write_manifest(tmp_path)],
                                  report=lambda line: None)
    assert caught.value.constraint == "aircraft.mesh_import"


# -- where the mesh sits (manifest version 2) ----------------------------
#
# Measured in the Camera Phase 1 initial run report: the rendered airframe
# sat 25-30 m AHEAD of the position the capture manifest recorded for it,
# along its own axis. The converter maps the FlightGear model about the
# MODEL's origin (the FDM's VRP, by FlightGear's convention) while the
# JSBSim plugin makes the actor origin the structural datum; a mesh
# attached at the actor root is drawn with its VRP on the datum. The
# manifest now records where the model origin sits in the actor, and a
# manifest that does not is stale.

FDM_XML = """<?xml version="1.0"?>
<fdm_config name="testcraft" version="2.0" release="ALPHA">
  <metrics>
    <wingarea unit="FT2"> 100 </wingarea>
    <location name="AERORP" unit="IN"><x> 10 </x><y> 0 </y><z> 0 </z></location>
    {vrp}
  </metrics>
  <mass_balance>
    <location name="CG" unit="IN"><x> 20 </x><y> 0 </y><z> 5 </z></location>
  </mass_balance>
</fdm_config>
"""


def _fdm_xml(tmp_path: Path, vrp: str) -> Path:
    path = tmp_path / "testcraft.xml"
    path.write_text(FDM_XML.format(vrp=vrp), encoding="utf-8")
    return path


def test_the_vrp_is_mapped_to_the_actor_frame_in_inches(tmp_path):
    """Structural x is AFT in inches; the actor's is forward in cm. The
    (-x, y, z) map is the plugin's StructuralToActorMatrix, whose origin
    is zero, so the actor origin IS the structural datum."""
    from assets_pipeline.convert import fdm_vrp_actor_cm

    xml = _fdm_xml(tmp_path, '<location name="VRP" unit="IN">'
                             '<x> 100 </x><y> 2 </y><z> -4 </z></location>')
    assert fdm_vrp_actor_cm(xml) == pytest.approx([-254.0, 5.08, -10.16])


def test_the_vrp_is_mapped_to_the_actor_frame_in_metres(tmp_path):
    from assets_pipeline.convert import fdm_vrp_actor_cm

    xml = _fdm_xml(tmp_path, '<location name="VRP" unit="M">'
                             '<x> 1.5 </x><y> 0 </y><z> 0.25 </z></location>')
    assert fdm_vrp_actor_cm(xml) == pytest.approx([-150.0, 0.0, 25.0])


def test_an_fdm_with_no_vrp_refuses_rather_than_guessing(tmp_path):
    """(0, 0, 0) would put the mesh on the structural datum -- the very
    offset this field exists to remove -- so a missing VRP is a named
    refusal, never a default."""
    from assets_pipeline.convert import ConvertError, fdm_vrp_actor_cm

    xml = _fdm_xml(tmp_path, "")
    with pytest.raises(ConvertError, match="REFUSING to place the mesh"):
        fdm_vrp_actor_cm(xml)
    with pytest.raises(ConvertError, match="VRP"):
        fdm_vrp_actor_cm(xml)


def test_an_unreadable_vrp_unit_refuses_by_name(tmp_path):
    from assets_pipeline.convert import ConvertError, fdm_vrp_actor_cm

    xml = _fdm_xml(tmp_path, '<location name="VRP" unit="FURLONG">'
                             '<x> 1 </x><y> 0 </y><z> 0 </z></location>')
    with pytest.raises(ConvertError, match="FURLONG"):
        fdm_vrp_actor_cm(xml)


def test_the_committed_b747_vrp_is_33_7_m_aft_of_the_datum():
    """Pinned numbers: the staged B747.xml states VRP x = 1327 in (aft),
    so in the actor frame the mesh origin is -1327 * 2.54 cm -- 33.7 m
    BEHIND the actor origin. Attached at the root, the 747 was drawn
    33.7 m forward of its label."""
    from assets_pipeline.convert import fdm_vrp_actor_cm
    from core.capture.airframe import fdm_xml_path

    origin = fdm_vrp_actor_cm(fdm_xml_path("B747"))
    assert origin[0] == pytest.approx(-1327 * 2.54)
    assert origin[1] == pytest.approx(0.0)
    assert origin[2] == pytest.approx(-24 * 2.54)


def test_the_converter_records_the_mesh_origin(tmp_path, monkeypatch):
    """The manifest carries version 2, the VRP, the (default zero) config
    offset, their sum, the convention in words, and the XML the VRP was
    read from with its digest -- provenance beside the number."""
    import hashlib

    from assets_pipeline import convert as convert_module
    from tests.test_phase6b import _write_config

    xml = _fdm_xml(tmp_path, '<location name="VRP" unit="IN">'
                             '<x> 100 </x><y> 0 </y><z> -4 </z></location>')
    monkeypatch.setattr(convert_module, "fdm_xml_path", lambda fdm: xml)
    manifest_path = convert_module.convert(_write_config(tmp_path),
                                           tmp_path / "out", importer.REPO)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert manifest["vrp_actor_cm"] == pytest.approx([-254.0, 0.0, -10.16])
    assert manifest["model_origin_offset_actor_cm"] == [0.0, 0.0, 0.0]
    assert manifest["mesh_origin_actor_cm"] == pytest.approx([-254.0, 0.0, -10.16])
    assert "VRP" in manifest["mesh_origin_basis"]
    assert "(-x, y, z)" in manifest["mesh_origin_basis"]
    assert manifest["vrp_source"]["fdm_xml"] == str(xml)
    assert manifest["vrp_source"]["sha256"] == hashlib.sha256(
        xml.read_bytes()).hexdigest()
    assert importer.stale_manifest_reason(manifest_path) is None


def test_a_documented_model_origin_offset_is_added_to_the_vrp(tmp_path,
                                                             monkeypatch):
    from assets_pipeline import convert as convert_module
    from tests.test_phase6b import _write_config

    xml = _fdm_xml(tmp_path, '<location name="VRP" unit="IN">'
                             '<x> 100 </x><y> 0 </y><z> 0 </z></location>')
    monkeypatch.setattr(convert_module, "fdm_xml_path", lambda fdm: xml)
    config_path = _write_config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["model_origin_offset_m"] = [1.0, -0.5, 0.25]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    manifest = json.loads(convert_module.convert(
        config_path, tmp_path / "out", importer.REPO).read_text(encoding="utf-8"))
    assert manifest["model_origin_offset_actor_cm"] == pytest.approx([100.0, -50.0, 25.0])
    assert manifest["mesh_origin_actor_cm"] == pytest.approx([-154.0, -50.0, 25.0])

    config["model_origin_offset_m"] = [1.0, "up"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(convert_module.ConvertError, match="model_origin_offset_m"):
        convert_module.convert(config_path, tmp_path / "out", importer.REPO)


def test_a_version_1_manifest_is_stale_and_rebuilds(tmp_path, monkeypatch):
    """The manifests already on every machine were written by the
    converter that said nothing about the origin. They must NOT count as
    converted: ensure_model re-converts (source already fetched at the
    pinned commit -> one converter run, no editor), and says why."""
    monkeypatch.setattr(importer, "REPO", tmp_path)
    monkeypatch.setattr(importer, "GENERATED", tmp_path / "assets" / "generated")
    monkeypatch.setattr(importer, "CONFIG_DIR", tmp_path / "assets" / "aircraft_config")
    config_dir = tmp_path / "assets" / "aircraft_config"
    config_dir.mkdir(parents=True)
    (config_dir / "TEST.json").write_text(json.dumps({
        "name": "TEST", "source_dir": "../aircraft_src/TEST",
        "license": {"repo": "local", "commit": "0" * 40, "file": "COPYING"},
    }), encoding="utf-8")
    manifest = write_manifest(tmp_path)          # no version at all
    place_assets(tmp_path)
    assert importer.stale_manifest_reason(manifest) is not None
    assert "structural datum" in importer.stale_manifest_reason(manifest)
    assert not importer.is_converted("TEST")
    assert not importer.is_imported("TEST")

    def current(manifest_path: Path) -> None:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data.update({"version": 2, "mesh_origin_actor_cm": [-3370.58, 0.0, -60.96]})
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

    steps = []
    monkeypatch.setattr(importer, "fetch_source",
                        lambda config, path, report: steps.append("fetch"))

    def fake_convert(config_path, report):
        steps.append("convert")
        current(manifest)
        return manifest

    monkeypatch.setattr(importer, "convert", fake_convert)
    monkeypatch.setattr(importer, "import_manifests",
                        lambda manifests, report: steps.append("import"))
    lines = []
    assert importer.ensure_model("TEST", report=lines.append) == manifest
    assert steps == ["fetch", "convert"]          # no editor: geometry unchanged
    assert any("stale" in line and "re-converting" in line for line in lines)

    # Current now: converted, imported, and a second ensure touches nothing.
    assert importer.stale_manifest_reason(manifest) is None
    assert importer.is_converted("TEST") and importer.is_imported("TEST")
    importer.ensure_model("TEST", report=lines.append)
    assert steps == ["fetch", "convert"]

    # Version 2 WITHOUT the field is equally stale: the version is a
    # claim, the field is what the commandlet reads.
    data = json.loads(manifest.read_text(encoding="utf-8"))
    del data["mesh_origin_actor_cm"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert "mesh_origin_actor_cm" in importer.stale_manifest_reason(manifest)
    assert not importer.is_imported("TEST")


def test_import_script_re_converts_a_stale_manifest(tmp_path, monkeypatch,
                                                    capsys):
    """scripts/import_aircraft.py said 'already converted' for a
    version-1 manifest -- the one every machine has -- and skipped the
    converter, so the mesh-origin fix never reached the asset on the
    documented path. A stale manifest is re-converted, with the reason."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "import_aircraft_script",
        Path(__file__).resolve().parents[1] / "scripts" / "import_aircraft.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    manifest = tmp_path / "TEST" / "mesh_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"magic": "flightsim-aircraft-mesh",
                                    "name": "TEST", "version": 1}),
                        encoding="utf-8")
    converted = []
    monkeypatch.setattr(script, "REPO", tmp_path)
    monkeypatch.setattr(script, "configured_aircraft",
                        lambda: {"TEST": tmp_path / "TEST.json"})
    monkeypatch.setattr(script, "unavailable_reason", lambda name: None)
    monkeypatch.setattr(script, "mesh_manifest_path", lambda name: manifest)
    monkeypatch.setattr(script, "load_config", lambda name: {"name": name})
    monkeypatch.setattr(script, "fetch_source",
                        lambda config, path, report: tmp_path / "src")
    monkeypatch.setattr(script, "convert",
                        lambda path, report: converted.append(path) or manifest)

    assert script.main(["TEST", "--no-import"]) == 0
    out = capsys.readouterr().out
    assert "re-converting" in out
    assert "structural datum" in out
    assert "already converted" not in out
    assert converted == [tmp_path / "TEST.json"]

    # A current manifest is left alone.
    manifest.write_text(json.dumps({"magic": "flightsim-aircraft-mesh",
                                    "name": "TEST", "version": 2,
                                    "mesh_origin_actor_cm": [-1.0, 0.0, 0.0]}),
                        encoding="utf-8")
    converted.clear()
    assert script.main(["TEST", "--no-import"]) == 0
    assert "already converted" in capsys.readouterr().out
    assert converted == []
