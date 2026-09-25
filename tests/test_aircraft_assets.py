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
import os
import subprocess
import xml.etree.ElementTree as ET
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


# -- where the mesh sits (manifest version 3): MEASURED from the vertices --
#
# Measured in the Camera Phase 1 initial run report: the rendered airframe
# sat 25-30 m AHEAD of the position the capture manifest recorded for it,
# along its own axis. The converter maps the FlightGear model about the
# MODEL's origin while the JSBSim plugin makes the actor origin the
# structural datum; a mesh attached at the actor root is drawn with its
# model origin on the datum. Version 2 (eb5c71d) placed the origin at the
# STAGED FDM's VRP -- an assumption, and the wrong FDM: each FlightGear
# mesh was modelled against its OWN repository's FDM. Measured from the
# pinned vertices with the repository's own reader, the B747's nose is
# 29.80 m ahead of its model origin (the VRP rule drew the mesh 3.9 m aft
# of its label), the A320's origin is 2.53 m ahead of its nose (the VRP
# rule made a NEW 19.3 m error), the c172p's nose is 2.14 m ahead (the
# VRP rule was right to 0.1 m, by luck). Version 3 measures: origin x =
# labelled nose keypoint - mesh forward extreme; z = main-gear contact -
# lowest gear vertex where the config names gear geometry, else the VRP z,
# stated; a mesh whose span is not the labelled length refuses by name.

FDM_XML = """<?xml version="1.0"?>
<fdm_config name="testcraft" version="2.0" release="ALPHA">
  <metrics>
    <wingarea unit="FT2"> 100 </wingarea>
    <wingspan unit="FT"> 30 </wingspan>
    <location name="AERORP" unit="IN"><x> 10 </x><y> 0 </y><z> 0 </z></location>
    {vrp}
  </metrics>
  <mass_balance>
    <location name="CG" unit="IN"><x> 20 </x><y> 0 </y><z> 5 </z></location>
  </mass_balance>
  <ground_reactions>
    {contacts}
  </ground_reactions>
</fdm_config>
"""

#: Structural frame, inches: the nose tip 10 in AHEAD of the datum, the
#: main gear 60 in below it. In the actor frame (-x, y, z) * 2.54 the
#: nose is at x = +25.4 cm and the main-gear contact at z = -152.4 cm.
CONTACTS = (
    '<contact type="STRUCTURE" name="NOSE_TIP"><location unit="IN">'
    '<x> -10 </x><y> 0 </y><z> 0 </z></location></contact>'
    '<contact type="BOGEY" name="NOSE_LG"><location unit="IN">'
    '<x> 40 </x><y> 0 </y><z> -50 </z></location></contact>'
    '<contact type="BOGEY" name="LEFT_MLG"><location unit="IN">'
    '<x> 150 </x><y> -40 </y><z> -60 </z></location></contact>'
    '<contact type="BOGEY" name="RIGHT_MLG"><location unit="IN">'
    '<x> 150 </x><y> 40 </y><z> -60 </z></location></contact>'
)

VRP_80_0_5 = ('<location name="VRP" unit="IN">'
              '<x> 80 </x><y> 0 </y><z> 5 </z></location>')   # actor (-203.2, 0, 12.7)


def _fdm_xml(tmp_path: Path, vrp: str, contacts: str = CONTACTS) -> Path:
    path = tmp_path / "testcraft.xml"
    path.write_text(FDM_XML.format(vrp=vrp, contacts=contacts), encoding="utf-8")
    return path


def _ac_vertex(actor_m):
    """An actor-frame point (x fwd, y right, z up, metres) as the .ac
    file's coordinates: acmodel.ac_to_ue is (x, y, z) -> (-x, -z, y), so
    ac = (-X, Z, -Y)."""
    x, y, z = actor_m
    return f"{-x} {z} {-y}"


def _ac_object(name, triangle_actor_m):
    lines = [f'OBJECT poly', f'name "{name}"', 'numvert 3']
    lines += [_ac_vertex(p) for p in triangle_actor_m]
    lines += ['numsurf 1', 'SURF 0x0', 'mat 0', 'refs 3', '0 0 0', '1 1 0', '2 0 1', 'kids 0']
    return "\n".join(lines)


#: A 10 m airframe about its own origin: nose at x = +5 m, tail at -5 m,
#: one wheel whose lowest vertex is 1.2 m below the origin, one aileron.
SYNTHETIC_AC = "\n".join([
    "AC3Db",
    'MATERIAL "white" rgb 0.8 0.8 0.8  amb 0.2 0.2 0.2  emis 0 0 0  spec 0 0 0  shi 0  trans 0',
    "OBJECT world",
    "kids 3",
    _ac_object("fuselage", [(5.0, 0.0, 0.0), (-5.0, -1.0, 1.0), (-5.0, 1.0, -1.0)]),
    _ac_object("LeftWheel", [(-1.0, -0.5, -1.2), (-1.0, 0.5, -1.2), (-1.5, 0.0, -1.0)]),
    _ac_object("aileron", [(-3.0, -2.0, 0.0), (-4.0, -2.0, 0.0), (-3.0, -3.0, 0.0)]),
]) + "\n"


def _write_labelled_config(tmp_path: Path, **overrides) -> Path:
    """A synthetic config WITH a labels block (nose = the FDM's NOSE_TIP
    contact, main gear = LEFT/RIGHT_MLG) and gear patterns. The pairing
    check reads the repo's staged B747 FDM; the labels and the VRP read
    the synthetic XML through the monkeypatched fdm_xml_path."""
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    (source / "model.ac").write_text(SYNTHETIC_AC, encoding="utf-8")
    (source / "COPYING").write_text("GNU GENERAL PUBLIC LICENSE\n", encoding="utf-8")
    config = {
        "name": "testcraft", "fdm": "B747", "fdm_match": ["B747-400"],
        "mesh_airframe": "synthetic labelled test craft", "source_dir": "src",
        "license": {"license_name": "GPL-2.0", "file": "COPYING",
                    "repo": "local", "commit": "0" * 40},
        "parts": [{"file": "model.ac"}], "exclude": [],
        "surfaces": {"aileron_l": {
            "bone": "aileron_l", "objects": ["aileron"],
            "property": "fcs/left-aileron-pos-rad", "scale_deg_per_unit": 57.29578,
            "hinge_m": [[3.0, -2.0, 0.0], [4.0, -2.0, 0.0]]}},
        "gear_geometry": {"objects": [".*Wheel"], "source": "synthetic"},
        "labels": {
            "dimensions_m": {"length": 10.0, "height": 3.0, "source": "synthetic"},
            "keypoints": {"nose": {"fdm_contact": "NOSE_TIP"},
                          "nose_gear": {"fdm_contact": "NOSE_LG"},
                          "left_main_gear": {"fdm_contact": "LEFT_MLG"},
                          "right_main_gear": {"fdm_contact": "RIGHT_MLG"}}},
    }
    config.update(overrides)
    for key in [k for k, v in overrides.items() if v is None]:
        del config[key]
    config_path = tmp_path / "testcraft.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _point_fdm_at(monkeypatch, xml: Path) -> None:
    """Both readers of the FDM XML -- the converter's VRP and the
    labeller's keypoints -- see the synthetic file."""
    import core.capture.airframe as airframe_module
    from assets_pipeline import convert as convert_module

    monkeypatch.setattr(convert_module, "fdm_xml_path", lambda fdm: xml)
    monkeypatch.setattr(airframe_module, "fdm_xml_path", lambda fdm: xml)


def _convert(tmp_path, config_path):
    from assets_pipeline import convert as convert_module

    manifest_path = convert_module.convert(config_path, tmp_path / "out", importer.REPO)
    return json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path


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
    """(0, 0, 0) would put the reference point (and the z fallback) on
    the structural datum, so a missing VRP is a named refusal, never a
    default."""
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


def test_the_committed_b747_vrp_is_recorded_for_reference_not_as_the_origin():
    """The staged B747.xml states VRP x = 1327 in (aft) -- in the actor
    frame -1327 * 2.54 = -3370.58 cm. eb5c71d made that the mesh origin;
    the pinned mesh's nose is 29.80 m ahead of ITS origin, so that rule
    drew the 747 3.9 m aft of its label. The VRP stays in the manifest as
    a reference number; the origin is measured (the pinned-source test
    below carries the 747's measured -2979.8 cm)."""
    from assets_pipeline.convert import fdm_vrp_actor_cm
    from core.capture.airframe import fdm_xml_path

    vrp = fdm_vrp_actor_cm(fdm_xml_path("B747"))
    assert vrp == pytest.approx([-1327 * 2.54, 0.0, -24 * 2.54])


def test_the_mesh_origin_is_measured_from_the_vertices(tmp_path, monkeypatch):
    """The rule, on a mesh whose extents are known by construction: the
    nose at +5 m about the model origin aligns with the labelled nose
    (NOSE_TIP, 10 in ahead of the datum = +25.4 cm in the actor), so the
    origin x is 25.4 - 500 = -474.6 cm; the lowest wheel vertex (-120 cm)
    aligns with the main-gear contact (-60 in = -152.4 cm), so z is
    -152.4 + 120 = -32.4 cm. Neither is the VRP (-203.2, 0, 12.7)."""
    import hashlib

    xml = _fdm_xml(tmp_path, VRP_80_0_5)
    _point_fdm_at(monkeypatch, xml)
    manifest, manifest_path = _convert(tmp_path, _write_labelled_config(tmp_path))

    assert manifest["version"] == 3
    assert manifest["mesh_origin_actor_cm"] == pytest.approx([-474.6, 0.0, -32.4])
    assert manifest["mesh_origin_measured_actor_cm"] == pytest.approx([-474.6, 0.0, -32.4])
    assert manifest["vrp_actor_cm"] == pytest.approx([-203.2, 0.0, 12.7])
    assert manifest["mesh_origin_basis"] == (
        "measured from vertices: nose keypoint (x), main-gear contact (z)")
    assert manifest["origin_anchor"] == {"x": "nose keypoint (fdm)",
                                         "z": "main-gear contact"}
    extents = manifest["mesh_extents_actor_cm"]
    assert extents == pytest.approx({"nose": 500.0, "tail": -500.0,
                                     "lowest": -120.0, "gear_lowest": -120.0})
    assert manifest["mesh_extent_actor_m"]["x"] == pytest.approx([-5.0, 5.0])
    assert manifest["mesh_extent_actor_m"]["y"] == pytest.approx([-3.0, 1.0])
    assert manifest["mesh_extent_actor_m"]["z"] == pytest.approx([-1.2, 1.0])
    assert manifest["mesh_length_m"] == pytest.approx(10.0)
    assert manifest["labels_length_m"] == 10.0
    assert manifest["vertices_measured"] == 9 and manifest["gear_vertices_measured"] == 3
    measurement = manifest["origin_measurement"]
    assert measurement["nose_keypoint"]["actor_cm"] == pytest.approx([25.4, 0.0, 0.0])
    assert measurement["nose_keypoint"]["basis"] == "fdm"
    assert measurement["main_gear_contact"]["name"] in ("left_main_gear", "right_main_gear")
    assert measurement["main_gear_contact"]["actor_cm"][2] == pytest.approx(-152.4)
    assert manifest["gear_geometry"] == {"parts": [], "objects": [".*Wheel"]}
    assert manifest["vrp_source"]["sha256"] == hashlib.sha256(xml.read_bytes()).hexdigest()
    assert importer.stale_manifest_reason(manifest_path) is None


def test_a_mesh_whose_length_is_not_the_labelled_length_refuses_by_name(
        tmp_path, monkeypatch, capsys):
    """The 10 m synthetic mesh under labels that say 12 m (16.7 % off,
    tolerance 5 %) is not the airframe the labels describe: refused as
    aircraft.mesh_extent, with the likeliest cause named, and the CLI
    prints the name and exits 2 -- no stack trace, no manifest."""
    from assets_pipeline import convert as convert_module

    xml = _fdm_xml(tmp_path, VRP_80_0_5)
    _point_fdm_at(monkeypatch, xml)
    config_path = _write_labelled_config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))

    config["labels"]["dimensions_m"]["length"] = 12.0
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(convert_module.ConvertError) as caught:
        _convert(tmp_path, config_path)
    assert caught.value.constraint == "aircraft.mesh_extent"
    assert "10.00 m" in caught.value.message and "12.00 m" in caught.value.message
    assert "wrong mesh" in caught.value.message
    assert not (tmp_path / "out" / "testcraft" / "mesh_manifest.json").exists()

    # A span that is the labelled length in inches names the unit.
    config["labels"]["dimensions_m"]["length"] = 10.0 / 39.3701
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(convert_module.ConvertError, match="wrong unit.*inches per metre"):
        _convert(tmp_path, config_path)

    # A span that matches the labelled length along y names the frame.
    config["labels"]["dimensions_m"]["length"] = 4.0     # the mesh's y span
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(convert_module.ConvertError, match="wrong frame"):
        _convert(tmp_path, config_path)

    config["labels"]["dimensions_m"]["length"] = 12.0
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert convert_module.main([str(config_path), "--out", str(tmp_path / "cli")]) == 2
    out = capsys.readouterr().out
    assert "REFUSED -- aircraft.mesh_extent" in out
    assert "Traceback" not in out

    # Within tolerance is not a refusal: 10.4 m is 4 % off.
    config["labels"]["dimensions_m"]["length"] = 10.4
    config_path.write_text(json.dumps(config), encoding="utf-8")
    manifest, _ = _convert(tmp_path, config_path)
    assert manifest["origin_measurement"]["length_deviation"] == pytest.approx(0.4 / 10.4)


def test_without_identifiable_gear_the_z_anchor_is_the_vrp_and_says_so(
        tmp_path, monkeypatch):
    """No gear_geometry patterns (the A320 config today): x is still
    measured, z falls back to the VRP's, and the basis says which --
    never a silent 0 and never the measured wording."""
    xml = _fdm_xml(tmp_path, VRP_80_0_5)
    _point_fdm_at(monkeypatch, xml)
    manifest, _ = _convert(tmp_path, _write_labelled_config(tmp_path, gear_geometry=None))
    assert manifest["mesh_origin_actor_cm"] == pytest.approx([-474.6, 0.0, 12.7])
    assert manifest["mesh_origin_basis"].startswith("measured from vertices: nose keypoint (x), VRP (z:")
    assert "no gear geometry identifiable" in manifest["mesh_origin_basis"]
    assert manifest["origin_anchor"] == {"x": "nose keypoint (fdm)", "z": "vrp"}
    assert manifest["mesh_extents_actor_cm"]["gear_lowest"] is None
    assert manifest["origin_measurement"]["main_gear_contact"] is None

    # Patterns that match nothing are the same case, stated the same way.
    manifest, _ = _convert(tmp_path, _write_labelled_config(
        tmp_path, gear_geometry={"objects": ["NoSuchObject"]}))
    assert manifest["origin_anchor"]["z"] == "vrp"
    assert manifest["gear_vertices_measured"] == 0


def test_a_config_with_no_labels_keeps_the_vrp_rule_and_says_so(tmp_path,
                                                                 monkeypatch):
    """A config without a labels block (the DHC6) has no nose keypoint to
    align to. Its origin is byte-identical to eb5c71d's VRP rule, the
    basis says so (so the verifier's drawn_airframe can grade it by
    name), and the extents are still recorded."""
    from tests.test_phase6b import _write_config

    xml = _fdm_xml(tmp_path, '<location name="VRP" unit="IN">'
                             '<x> 100 </x><y> 0 </y><z> -4 </z></location>')
    _point_fdm_at(monkeypatch, xml)
    manifest, manifest_path = _convert(tmp_path, _write_config(tmp_path))
    assert manifest["version"] == 3
    assert manifest["vrp_actor_cm"] == pytest.approx([-254.0, 0.0, -10.16])
    assert manifest["mesh_origin_actor_cm"] == pytest.approx([-254.0, 0.0, -10.16])
    assert manifest["mesh_origin_basis"].startswith("FDM VRP (no labels block")
    assert "(-x, y, z)" in manifest["mesh_origin_basis"]
    assert manifest["origin_anchor"] == {"x": "vrp", "z": "vrp"}
    assert manifest["labels_length_m"] is None
    # The fixture's wing spans ac x 0..1 (actor 0..-1 m) and its pod sits
    # under a group at ac loc (10, 20, 30): actor x = -10..-11 m.
    assert manifest["mesh_extents_actor_cm"]["nose"] == pytest.approx(0.0)
    assert manifest["mesh_extents_actor_cm"]["tail"] == pytest.approx(-1100.0)
    assert manifest["mesh_length_m"] == pytest.approx(11.0)
    assert importer.stale_manifest_reason(manifest_path) is None


def test_a_documented_model_origin_offset_is_added_to_the_measured_origin(
        tmp_path, monkeypatch):
    from assets_pipeline import convert as convert_module

    xml = _fdm_xml(tmp_path, VRP_80_0_5)
    _point_fdm_at(monkeypatch, xml)
    config_path = _write_labelled_config(tmp_path, model_origin_offset_m=[1.0, -0.5, 0.25])
    manifest, _ = _convert(tmp_path, config_path)
    assert manifest["model_origin_offset_actor_cm"] == pytest.approx([100.0, -50.0, 25.0])
    assert manifest["mesh_origin_measured_actor_cm"] == pytest.approx([-474.6, 0.0, -32.4])
    assert manifest["mesh_origin_actor_cm"] == pytest.approx([-374.6, -50.0, -7.4])

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["model_origin_offset_m"] = [1.0, "up"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(convert_module.ConvertError, match="model_origin_offset_m"):
        _convert(tmp_path, config_path)


def test_malformed_gear_geometry_and_unloadable_labels_refuse_by_name(
        tmp_path, monkeypatch):
    """A dropped gear pattern would silently move the z anchor to the
    VRP; a labels block the labeller cannot resolve leaves the nose
    unknown. Both refuse, named, rather than falling back."""
    from assets_pipeline import convert as convert_module

    xml = _fdm_xml(tmp_path, VRP_80_0_5)
    _point_fdm_at(monkeypatch, xml)
    with pytest.raises(convert_module.ConvertError, match="gear_geometry"):
        _convert(tmp_path, _write_labelled_config(tmp_path, gear_geometry="wheels"))
    with pytest.raises(convert_module.ConvertError, match="gear_geometry.objects"):
        _convert(tmp_path, _write_labelled_config(tmp_path, gear_geometry={"objects": ["("]}))

    config_path = _write_labelled_config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["labels"]["keypoints"]["nose"] = {"fdm_contact": "NO_SUCH_CONTACT"}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(convert_module.ConvertError) as caught:
        _convert(tmp_path, config_path)
    assert caught.value.constraint == "camera.labels"
    assert "NO_SUCH_CONTACT" in caught.value.message


def test_a_version_1_or_2_manifest_is_stale_and_rebuilds(tmp_path, monkeypatch):
    """The manifests on every machine were written either by the converter
    that said nothing about the origin (version 1) or by eb5c71d's, which
    assumed it from the staged VRP (version 2). Neither counts as
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

    # Version 2 -- eb5c71d's VRP origin -- is stale too, for its own reason.
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update({"version": 2, "mesh_origin_actor_cm": [-3370.58, 0.0, -60.96]})
    manifest.write_text(json.dumps(data), encoding="utf-8")
    reason = importer.stale_manifest_reason(manifest)
    assert reason is not None and "VRP" in reason and "not measured" in reason
    assert not importer.is_converted("TEST")

    def current(manifest_path: Path) -> None:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data.update({"version": 3, "mesh_origin_actor_cm": [-2979.82, 0.0, 13.86]})
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

    # Version 3 WITHOUT the field is equally stale: the version is a
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
    documented path. A stale manifest (version 1 OR eb5c71d's version
    2) is re-converted, with the reason."""
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

    # eb5c71d's version 2 (VRP origin) re-converts with its own reason.
    manifest.write_text(json.dumps({"magic": "flightsim-aircraft-mesh",
                                    "name": "TEST", "version": 2,
                                    "mesh_origin_actor_cm": [-3370.58, 0.0, -60.96]}),
                        encoding="utf-8")
    converted.clear()
    assert script.main(["TEST", "--no-import"]) == 0
    out = capsys.readouterr().out
    assert "re-converting" in out and "VRP" in out
    assert converted == [tmp_path / "TEST.json"]

    # A current manifest is left alone.
    manifest.write_text(json.dumps({"magic": "flightsim-aircraft-mesh",
                                    "name": "TEST", "version": 3,
                                    "mesh_origin_actor_cm": [-1.0, 0.0, 0.0]}),
                        encoding="utf-8")
    converted.clear()
    assert script.main(["TEST", "--no-import"]) == 0
    assert "already converted" in capsys.readouterr().out
    assert converted == []


# -- the real numbers: the pinned meshes, measured -----------------------
#
# These fetch each config's model repository at its PINNED commit (the
# repository's own assets/aircraft_src/<dir> is used when it is already
# at that commit; otherwise a session temp dir, or the directory named by
# FLIGHTSIM_AIRCRAFT_SRC_CACHE, which keeps a developer's second run off
# the network), run the converter, and pin the extents the critique
# measured and the origins the rule yields. When the network refuses,
# they SKIP BY NAME (pytest -rs shows the reason); they never pass
# without measuring.

#: Extents in the actor frame about the model origin (cm), from the pinned
#: .ac files through assets_pipeline.acmodel (critique offset_root_cause,
#: re-measured here 2026-09-25 over the drawn vertices), and the origin
#: the rule yields. Tolerances: extents +-5 cm, origins +-1 cm.
PINNED_MESHES = {
    "B747": {"nose": 2979.82, "tail": -4114.44, "lowest": -562.5, "gear_lowest": -562.5,
             "mesh_length_m": 70.94, "origin": (-2979.82, 0.0, 13.86),
             "z_anchor": "main-gear contact", "vrp_rule_residual_cm": -390.76},
    "A320": {"nose": -252.58, "tail": -4009.23, "lowest": -327.32, "gear_lowest": None,
             "mesh_length_m": 37.57, "origin": (252.58, 0.0, -93.98),
             "z_anchor": "vrp", "vrp_rule_residual_cm": -1931.78},
    "c172p": {"nose": 214.07, "tail": -608.52, "lowest": -136.79, "gear_lowest": -136.79,
              "mesh_length_m": 8.23, "origin": (-118.31, 0.0, 97.42),
              "z_anchor": "main-gear contact", "vrp_rule_residual_cm": 10.10},
}


def _at_commit(source_dir: Path, commit: str) -> bool:
    if not (source_dir / ".git").is_dir():
        return False
    head = subprocess.run(["git", "-C", str(source_dir), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return head.returncode == 0 and head.stdout.strip() == commit


@pytest.fixture(scope="session")
def pinned_sources(tmp_path_factory):
    """name -> source tree at the config's pinned commit, fetched with the
    importer's own fetch_source; a network refusal skips by name."""
    cache = os.environ.get("FLIGHTSIM_AIRCRAFT_SRC_CACHE")
    root = Path(cache).resolve() if cache else tmp_path_factory.mktemp("aircraft_src")
    root.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name in PINNED_MESHES:
        config_path = importer.CONFIG_DIR / f"{name}.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        commit = config["license"]["commit"]
        own = (config_path.parent / config["source_dir"]).resolve()
        if _at_commit(own, commit):
            sources[name] = own
            continue
        probe = dict(config)
        probe["source_dir"] = Path(config["source_dir"]).name
        probe_path = root / f"{name}.json"
        probe_path.write_text(json.dumps(probe), encoding="utf-8")
        try:
            sources[name] = importer.fetch_source(probe, probe_path,
                                                  report=lambda line: None)
        except (subprocess.CalledProcessError, OSError) as exc:
            pytest.skip(f"network refused: fetching {config['license']['repo']} "
                        f"@ {commit[:12]} into {root} failed ({exc}); the "
                        f"pinned-mesh measurements were NOT made here")
    return sources


def _expected_nose_actor_x_cm(name: str) -> float:
    """The labels' nose keypoint in the actor frame, re-derived here from
    the config and the FDM XML WITHOUT the converter: a stated
    structural_in point, or a <contact> location, x -> -x * 2.54."""
    from core.capture.airframe import fdm_xml_path

    config = json.loads((importer.CONFIG_DIR / f"{name}.json").read_text(encoding="utf-8"))
    definition = config["labels"]["keypoints"]["nose"]
    if "structural_in" in definition:
        return -float(definition["structural_in"][0]) * 2.54
    root = ET.parse(fdm_xml_path(config["fdm"])).getroot()
    for contact in root.find("ground_reactions").findall("contact"):
        if contact.get("name") == definition["fdm_contact"]:
            loc = contact.find("location")
            assert loc.get("unit", "IN") == "IN"
            return -float(loc.find("x").text) * 2.54
    raise AssertionError(f"{name}: no contact {definition['fdm_contact']!r}")


@pytest.mark.parametrize("name", sorted(PINNED_MESHES))
def test_pinned_sources_measure_the_extents_and_put_the_nose_on_its_label(
        name, pinned_sources, tmp_path):
    """The critique's numbers, reproduced from the pinned commit through
    the converter: the mesh's nose/tail about its own origin, the lowest
    (gear) vertex, the span against the type's length, and the origin
    the rule yields -- which puts the mesh nose EXACTLY on the labelled
    nose (re-derived here without the converter). The last assertion is
    eb5c71d's residual: how far the VRP rule drew each nose from its
    label (-3.91 m B747, -19.32 m A320, +0.10 m c172p)."""
    from assets_pipeline import convert as convert_module

    pinned = PINNED_MESHES[name]
    config = json.loads((importer.CONFIG_DIR / f"{name}.json").read_text(encoding="utf-8"))
    config["source_dir"] = str(pinned_sources[name])
    config_path = tmp_path / f"{name}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    manifest = json.loads(convert_module.convert(
        config_path, tmp_path / "out", importer.REPO).read_text(encoding="utf-8"))

    extents = manifest["mesh_extents_actor_cm"]
    assert extents["nose"] == pytest.approx(pinned["nose"], abs=5.0)
    assert extents["tail"] == pytest.approx(pinned["tail"], abs=5.0)
    assert extents["lowest"] == pytest.approx(pinned["lowest"], abs=5.0)
    if pinned["gear_lowest"] is None:
        assert extents["gear_lowest"] is None
    else:
        assert extents["gear_lowest"] == pytest.approx(pinned["gear_lowest"], abs=5.0)
    assert manifest["mesh_length_m"] == pytest.approx(pinned["mesh_length_m"], abs=0.05)
    assert manifest["labels_length_m"] == config["labels"]["dimensions_m"]["length"]
    assert abs(manifest["mesh_length_m"] - manifest["labels_length_m"]) / manifest["labels_length_m"] < 0.01

    assert manifest["version"] == 3
    assert manifest["mesh_origin_actor_cm"] == pytest.approx(pinned["origin"], abs=1.0)
    assert manifest["mesh_origin_basis"].startswith("measured from vertices: nose keypoint (x)")
    assert manifest["origin_anchor"]["z"] == pinned["z_anchor"]

    # The rule's whole point: origin + mesh nose == the labelled nose.
    nose_label_x = _expected_nose_actor_x_cm(name)
    assert manifest["mesh_origin_actor_cm"][0] + extents["nose"] == pytest.approx(nose_label_x, abs=0.01)
    # And what eb5c71d did instead (origin = the staged VRP): the mesh
    # nose landed this far from its label along x.
    vrp_rule_residual = manifest["vrp_actor_cm"][0] + extents["nose"] - nose_label_x
    assert vrp_rule_residual == pytest.approx(pinned["vrp_rule_residual_cm"], abs=5.0)
