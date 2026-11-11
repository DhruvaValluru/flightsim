"""Retractable gear as its own hideable part (owner decision 2026-11-11,
render round 47: an airborne retractable-gear airframe cruises gear-up).

The FDM flew the 747 gear-up (core/fdm/gear.py, the card's
``start_gear_up``) and the labels gave the retracted gear no box
(core/capture/labels.py GEAR_RETRACTED_*), but the mesh drew its four main
bogies and nose gear anyway: the gear was baked into body.obj, so nothing
could stop drawing it, and #13's tight box poked out of bbox_2d. Now the
converter writes a retractable-gear airframe's gear_geometry triangles to
their own part (``gear``), the manifest names it under
``retractable_gear``, and the commandlet attaches it under MeshOrigin and
draws it only while the flown ``gear/gear-pos-norm`` is >= 0.01 -- in every
pass, so the labels keep matching the pixels. Gear down draws the same
triangles as before.
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest

from assets_pipeline import convert
from tests.test_aircraft_assets import (
    CONTACTS, GEAR_COMPONENT, VRP_80_0_5, _convert, _faces, _fdm_xml,
    _labelled_config_with_gear, _point_fdm_at, _write_labelled_config)

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
COMMANDLET = BRIDGE / "Private/FlightSimRenderCommandlet.cpp"
ANIMATOR_H = BRIDGE / "Public/FlightSimSurfaceAnimator.h"
ANIMATOR_CPP = BRIDGE / "Private/FlightSimSurfaceAnimator.cpp"
CONFIG_DIR = REPO / "assets/aircraft_config"

#: The synthetic FDM's main gear, declared retractable as the B747's is.
RETRACTABLE_CONTACTS = CONTACTS.replace(
    '<x> 150 </x><y> -40 </y><z> -60 </z></location></contact>',
    '<x> 150 </x><y> -40 </y><z> -60 </z></location>'
    '<retractable>1</retractable></contact>')


def _retractable(monkeypatch, tmp_path):
    xml = _fdm_xml(tmp_path, VRP_80_0_5, RETRACTABLE_CONTACTS)
    assert "<retractable>1</retractable>" in xml.read_text(encoding="utf-8")
    _point_fdm_at(monkeypatch, xml)


def _vertices(obj_path: Path):
    return sorted(line for line in obj_path.read_text(encoding="utf-8").splitlines()
                  if line.startswith("v "))


# -- the converter ------------------------------------------------------------

def test_a_retractable_gear_goes_to_its_own_part_and_the_manifest_names_it(
        tmp_path, monkeypatch):
    # The reference: the same model, fixed gear -- the gear stays in the body.
    (tmp_path / "fixed").mkdir()
    _point_fdm_at(monkeypatch, _fdm_xml(tmp_path / "fixed", VRP_80_0_5))
    fixed, fixed_path = _convert(tmp_path / "fixed",
                                 _write_labelled_config(tmp_path / "fixed"))
    assert fixed["parts"] == ["body", "aileron_l"]
    assert "retractable_gear" not in fixed
    assert len(_faces(fixed_path.parent / "body.obj")) == 2

    (tmp_path / "up").mkdir()
    _retractable(monkeypatch, tmp_path / "up")
    manifest, manifest_path = _convert(tmp_path / "up", _write_labelled_config(tmp_path / "up"))
    out = manifest_path.parent

    assert manifest["parts"] == ["body", "aileron_l", convert.RETRACTABLE_GEAR_PART]
    assert manifest["triangles"] == {"body": 1, "aileron_l": 1, "gear": 1}
    assert len(_faces(out / "body.obj")) == 1            # the fuselage only
    assert len(_faces(out / "gear.obj")) == 1            # LeftWheel
    assert (out / "gear.mtl").is_file()
    # Gear down draws exactly the triangles the body drew before.
    assert sorted(_vertices(out / "body.obj") + _vertices(out / "gear.obj")) == \
        _vertices(fixed_path.parent / "body.obj")
    assert (out / "aileron_l.obj").read_bytes() == \
        (fixed_path.parent / "aileron_l.obj").read_bytes()

    block = manifest["retractable_gear"]
    extent = block.pop("mesh_extent_actor_m")
    basis = block.pop("basis")
    assert block == {"part": "gear", "property": "gear/gear-pos-norm",
                     "hidden_below": 0.01, "triangles": 1, "vertices": 3,
                     "patterns": {"parts": [], "objects": [".*Wheel"]}}
    for axis, lo_hi in {"x": (-1.5, -1.0), "y": (-0.5, 0.5), "z": (-1.2, -1.0)}.items():
        assert extent[axis] == pytest.approx(lo_hi), axis
    assert "every pass" in basis and "labels.py" in basis

    # The measured origin and extents still include the gear vertices.
    for key in ("mesh_extents_actor_cm", "mesh_extent_actor_m", "vertices_measured",
                "gear_vertices_measured", "mesh_origin_actor_cm",
                "mesh_origin_measured_actor_cm", "origin_anchor", "mesh_origin_basis",
                "version", "components"):
        assert manifest[key] == fixed[key], key
    assert manifest["origin_anchor"]["z"] == "main-gear contact"


def test_the_importer_imports_the_gear_part(tmp_path, monkeypatch):
    from assets_pipeline import importer

    _retractable(monkeypatch, tmp_path)
    manifest, _ = _convert(tmp_path, _write_labelled_config(tmp_path))
    # scripts/ue_import_aircraft.py imports manifest["parts"] with
    # manifest["triangles"][part] as the expected count.
    assert "gear" in importer.imported_parts(manifest)
    assert all(part in manifest["triangles"] for part in manifest["parts"])


def test_a_retractable_gear_with_a_beauty_mesh_gets_its_own_beauty_copy(
        tmp_path, monkeypatch):
    _retractable(monkeypatch, tmp_path)
    config_path = _write_labelled_config(
        tmp_path, beauty_mesh={"normals": "crease", "two_sided": False,
                               "source": "synthetic"})
    manifest, manifest_path = _convert(tmp_path, config_path)
    out = manifest_path.parent
    assert set(manifest["beauty_parts"]) == {"body", "gear"}
    assert manifest["beauty_parts"]["gear"]["part"] == "gear_beauty"
    assert manifest["beauty_parts"]["gear"]["front_triangles"] == 1
    assert manifest["beauty_parts"]["body"]["front_triangles"] == 1
    assert len(_faces(out / "gear_beauty.obj")) == 1
    assert len(_faces(out / "body_beauty.obj")) == 1


def test_patterns_that_match_nothing_or_no_patterns_split_nothing(tmp_path, monkeypatch):
    _retractable(monkeypatch, tmp_path)
    for name, geometry in (("none", {"objects": ["NoSuchObject"]}),
                           ("empty", {"parts": [], "objects": []})):
        (tmp_path / name).mkdir()
        config_path = _write_labelled_config(tmp_path / name, gear_geometry=geometry)
        manifest, manifest_path = _convert(tmp_path / name, config_path)
        assert manifest["parts"] == ["body", "aileron_l"], name
        assert "gear" not in manifest["triangles"], name
        assert "retractable_gear" not in manifest, name
        assert not (manifest_path.parent / "gear.obj").exists(), name
        assert len(_faces(manifest_path.parent / "body.obj")) == 2, name


def test_a_c7_gear_component_of_a_retractable_airframe_is_the_hidden_part(
        tmp_path, monkeypatch):
    _retractable(monkeypatch, tmp_path)
    manifest, _ = _convert(tmp_path, _labelled_config_with_gear(tmp_path, (GEAR_COMPONENT,)))
    part = "SM_testcraft_landing_gear"
    assert manifest["parts"] == ["body", "aileron_l", part]       # no second gear part
    assert manifest["retractable_gear"]["part"] == part
    assert manifest["retractable_gear"]["triangles"] == 1


def test_the_rules_are_the_fdm_s_and_the_labels_own():
    from core.capture import labels, verify
    from core.fdm import gear

    assert convert.RETRACTABLE_GEAR_RE.pattern == gear._RETRACTABLE.pattern
    assert convert.GEAR_POSITION_PROPERTY == labels.GEAR_POSITION_CHANNEL \
        == verify.GEAR_POSITION_CHANNEL
    assert convert.GEAR_HIDDEN_BELOW == labels.GEAR_RETRACTED_BELOW \
        == verify.GEAR_RETRACTED_BELOW


#: Per airframe in assets/aircraft_config: what the converter now does with
#: its gear (the configs' own patterns and the staged FDM's XML decide).
EXPECTED_GEAR = {
    "B747": "split",      # 747-400_gear.ac: nose + 4 main bogies, hideable
    "J11": "split",       # Su-27.ac UC_* objects, hideable
    "p51d": "split",      # mainWheel*, tailWheel*, struts ..., hideable
    "A320": "none drawn",  # no gear part converted: no gear vertex at all
    "A4": "stowed",       # .mdl exported gear stowed: never drawn
    "c172p": "fixed",     # C7 component, never retracts
    "DHC6": "fixed",      # C7 component, never retracts
}


@pytest.mark.parametrize("name", sorted(EXPECTED_GEAR))
def test_every_configured_airframe_s_gear(name):
    from core.capture.airframe import fdm_xml_path

    config = json.loads((CONFIG_DIR / f"{name}.json").read_text(encoding="utf-8"))
    retractable = convert.fdm_has_retractable_gear(fdm_xml_path(config["fdm"]))
    if config.get("converter") == "mdl":
        assert EXPECTED_GEAR[name] == "stowed"
        assert retractable                      # flown gear-up airborne, drawn stowed
        return
    parts, objects = convert._gear_patterns(config)
    component = convert._gear_component(config)
    if EXPECTED_GEAR[name] == "split":
        assert retractable and (parts or objects) and component is None
    elif EXPECTED_GEAR[name] == "fixed":
        assert not retractable and component is not None
    else:
        assert retractable and not parts and not objects


# -- the verifier: a retracted gear's vertices are not the silhouette ----------

def test_the_verifier_leaves_the_retracted_gear_out_of_the_silhouette(tmp_path, monkeypatch):
    import hashlib

    from core.capture import verify

    folder = tmp_path / "assets" / "generated" / "X"
    folder.mkdir(parents=True)
    (folder / "body.obj").write_text("v 100 0 0\nv -100 0 0\n", encoding="utf-8")
    (folder / "gear.obj").write_text("v 0 0 -500\n", encoding="utf-8")
    mesh = {"version": 3, "parts": ["body", "gear"], "mesh_origin_actor_cm": [0, 0, 0],
            "retractable_gear": {"part": "gear", "property": "gear/gear-pos-norm",
                                 "hidden_below": 0.01}}
    path = folder / "mesh_manifest.json"
    path.write_text(json.dumps(mesh), encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"assets": {"mesh_manifest": {
        "path": "assets/generated/X/mesh_manifest.json", "sha256": sha}}}
    monkeypatch.setattr(verify, "_REPO", tmp_path)
    verify._mesh_vertices_actor_m.cache_clear()
    airframe = {"cg_structural_in": [0.0, 0.0, 0.0]}

    down, _ = verify._mesh_points_body(manifest, airframe)
    assert len(down) == 3 and float(np.max(down[:, 2])) == pytest.approx(5.0)
    up, basis = verify._mesh_points_body(manifest, airframe, gear_retracted=True)
    assert len(up) == 2 and float(np.max(up[:, 2])) == pytest.approx(0.0)
    assert "retracted gear" in basis

    assert verify._frame_gear_retracted({"state": {"gear/gear-pos-norm": 0.0}})
    assert not verify._frame_gear_retracted({"state": {"gear/gear-pos-norm": 1.0}})
    assert not verify._frame_gear_retracted({"state": {}})
    assert not verify._frame_gear_retracted({})
    # Only the primary's gear follows the frame (traffic flies no FDM).
    source = Path(verify.__file__).read_text(encoding="utf-8")
    assert "gear_retracted=primary and _frame_gear_retracted(record)" in source


# -- the engine (structure: no Unreal on this machine) --------------------------

def _function_body(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:i + 1]
    raise AssertionError(f"unbalanced {signature}")


def test_the_animator_hides_the_gear_from_the_fdm_s_own_position():
    header = ANIMATOR_H.read_text(encoding="utf-8")
    assert "struct FFlightSimVisibilityBinding" in header
    assert "TArray<FFlightSimVisibilityBinding> VisibilityBindings;" in header
    assert re.search(r"void AddVisibilityBinding\(const FString& Property, float HiddenBelow,\s*"
                     r"USceneComponent\* Component\);", header)
    source = ANIMATOR_CPP.read_text(encoding="utf-8")
    tick = _function_body(source, "void UFlightSimSurfaceAnimator::TickComponent(")
    loop = tick[tick.index("VisibilityBindings"):]
    # Read (empty value = read) the way every surface is read, never written.
    assert "Movement->CommandConsole(Visibility.PropertyName, FString(), Value);" in loop
    assert "Visibility.CurrentValue >= Visibility.HiddenBelow" in loop
    assert "SetVisibility(bDrawn)" in loop
    assert "SetHiddenInGame" not in source
    # ClearBindings (a manifest's surface table) leaves the gear binding.
    assert "void ClearBindings() { Bindings.Empty(); }" in header


def test_the_commandlet_attaches_the_gear_part_and_binds_it():
    text = COMMANDLET.read_text(encoding="utf-8")
    build = _function_body(text, "bool BuildMeshAirframe(")
    gear = build[build.index('TEXT("retractable_gear")'):build.index("Phase 10 (package 7)")]
    for needle in ('TEXT("part"), Out.GearPart', 'TEXT("property"), Out.GearProperty',
                   'TEXT("hidden_below"), Out.GearHiddenBelow',
                   'NewObject<UStaticMeshComponent>(Aircraft, TEXT("MeshGear"))',
                   "Gear->SetupAttachment(MeshOrigin);",
                   "Gear->SetCollisionEnabled(ECollisionEnabled::NoCollision);",
                   "Gear->RegisterComponent();",
                   "Out.bGearDrawnAtStart = !(Animator != nullptr && StartGearUp == 1);",
                   "Out.GearComponent->SetVisibility(Out.bGearDrawnAtStart);",
                   "Animator->AddVisibilityBinding(Out.GearProperty,"):
        assert needle in gear, needle
    # No offset: the gear OBJ is in the body's vertex frame at MeshOrigin.
    assert "Gear->SetRelativeLocation" not in gear
    # Visibility, never bHiddenInGame (the stencil loop skips hidden-in-game).
    assert "SetHiddenInGame" not in gear
    # Before the livery, so a sampled livery paints the gear too.
    assert build.index('TEXT("retractable_gear")') < build.index("LiveryMaterial")
    # The primary passes the card's gear answer; render.json records the run.
    assert "&Card.Objects, Card.StartGearUp))" in text
    assert 'Root->SetObjectField(TEXT("retractable_gear"), GearRecord);' in text
    assert "int32 StartGearUp = -1)" in text


def test_a_converter_change_triggers_the_aircraft_prep_on_windows():
    script = (REPO / "scripts/visual_fix_round.ps1").read_text(encoding="utf-8")
    rule = re.search(r"\$_ -match '([^']*aircraft_config[^']*)' \}\) \{ \$steps \+= \"aircraft\"",
                     script)
    assert rule, "aircraft prep rule not found"
    pattern = re.compile(rule.group(1))
    for changed in ("assets_pipeline/convert.py", "assets/aircraft_config/B747.json",
                    "scripts/ue_import_aircraft.py"):
        assert pattern.search(changed), changed
    assert not pattern.search("core/capture/verify.py")
