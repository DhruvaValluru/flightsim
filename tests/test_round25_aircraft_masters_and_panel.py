"""Round 25 (2026-11-11): two scene fixes, without the engine.

1. Scene #12 (C172 cockpit) drew no instrument panel: the c172p config
   converted only the exterior .ac. The FlightGear panel model
   (c172p-interior.ac) is now a ``beauty_only`` interior part: written into
   the body's beauty copy after the measured slots, never into body.obj, so
   every measure frame stays byte-identical.
2. The gen-4..6 paint / bare-metal masters drew the default material (rounds
   37-39 byte-identical under five probes, round 40's basecolor-debug a lit
   untextured airframe). The host compile-checks the class masters and falls
   back to the Custom-node-free clear-coat master, then the flat one; the
   masters rebuild in place (never deleted) at LOOK_GENERATION 7 with a
   LookGeneration sentinel the host records.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import aircraft_look as look  # noqa: E402

PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
FX_CPP = (PRIVATE / "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
MASTERS = (ROOT / "scripts/ue_aircraft_master_materials.py").read_text(encoding="utf-8")
C172 = json.loads((ROOT / "assets/aircraft_config/c172p.json").read_text(encoding="utf-8"))


def _apply():
    body = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::ApplyMaterials"):]
    return body[:body.index("\nvoid FFlightSimAircraftFX::", 10)]


def _def(name, until):
    return MASTERS[MASTERS.index(f"def {name}("):MASTERS.index(f"def {until}(")]


# -- 2. the masters --------------------------------------------------------------

def test_absent_probe_means_the_class_masters_and_flat_is_the_switch():
    assert look.DEFAULT_AIRCRAFT_PROBES == ()
    assert look.parse_aircraft_probes("") == ()
    assert look.parse_aircraft_probes("-aircraft-materials=on -aircraft-probe=flat") == ("flat",)
    assert look.parse_aircraft_probes("-aircraft-probe=coat") == ("coat",)
    assert "coat" in look.AIRCRAFT_PROBES
    parse = FX_CPP[FX_CPP.index("// Round 23: the master bisect probes"):FX_CPP.index("double FFlightSimAircraftFX::HeatHaze")]
    assert 'Word == TEXT("coat")' in parse
    assert 'Probes.Add(TEXT("flat"))' not in parse          # no hidden default probe
    assert look.MASTER_FALLBACK_ORDER == ("class master", look.PROBE_COAT_MASTER, look.PROBE_FLAT_MASTER)


def test_the_host_compile_checks_like_the_cloud_materials():
    helper = FX_CPP[FX_CPP.index("FString AircraftFxCompileProblem("):]
    helper = helper[:helper.index("\n\t}\n") + 4]
    for needle in ("GShaderPlatformForFeatureLevel[World->GetFeatureLevel()]",
                   "FLIGHTSIM_AIRCRAFT_MATERIAL_RESOURCE(Base, World, Platform)",
                   "Resource->FinishCompilation();", "Resource->GetCompileErrors()",
                   "Resource->GetGameThreadShaderMap() == nullptr"):
        assert needle in helper, needle
    # The 5.7 overload (shader platform) and the older one, under its own macro name
    # (FlightSimWeather.cpp defines FLIGHTSIM_GET_MATERIAL_RESOURCE: unity builds).
    assert "#define FLIGHTSIM_AIRCRAFT_MATERIAL_RESOURCE(Base, World, Platform) ((Base)->GetMaterialResource(Platform))" in FX_CPP
    assert "#define FLIGHTSIM_GET_MATERIAL_RESOURCE" not in FX_CPP
    for include in ('#include "MaterialShared.h"', '#include "RHI.h"', '#include "Runtime/Launch/Resources/Version.h"'):
        assert include in FX_CPP


def test_a_master_that_fails_to_compile_falls_back_to_coat_then_flat():
    apply = _apply()
    assert f"/Game/FlightSim/Aircraft/{look.PROBE_COAT_MASTER}.{look.PROBE_COAT_MASTER}" in FX_CPP
    # both plain masters are loaded on every beauty render (the fallback needs them)
    assert "UMaterialInterface* ProbeFlat = LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeFlatMaterialPath);" in apply
    assert "UMaterialInterface* ProbeCoat = LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeCoatMaterialPath);" in apply
    choice = apply[apply.index("UMaterialInterface* Plain = nullptr;"):apply.index("// wet-airframe-canopy: a MID of the look instance")]
    assert choice.index('Options.Probes.Contains(TEXT("flat"))') < choice.index('Options.Probes.Contains(TEXT("coat"))') \
        < choice.index("CompileProblemOf(Drawn)")
    assert "CompileProblemOf(ProbeCoat).IsEmpty())\n\t\t\t\t\t\t\t? ProbeCoat : ProbeFlat;" in choice
    assert "CoatMid->CopyParameterOverrides(LookMic);" in choice
    # the class master's own graph (or its round-24 twin) is what is checked
    assert "UMaterialInterface* Drawn = PaintTwin != nullptr ? PaintTwin : LookInstance;" in choice
    # every paint / bare-metal slot, not only probed ones
    assert "const bool bProbeSlot =\n\t\t\t\t(ProbeBaseName == TEXT(\"M_AircraftPaint\")" in apply


def test_render_json_names_the_compile_result_the_fallback_and_the_generation():
    apply = _apply()
    for field in ("master_compile", "slots_fallback", "master_generation", "probe_parameters_missing",
                  "fallback_rule", "probe_coat"):
        assert f'TEXT("{field}")' in apply, field
    assert "AircraftFxLookGenerationParam" in apply
    assert 'TEXT("LookGeneration")' in FX_CPP


def test_the_masters_rebuild_in_place_at_generation_7():
    assert re.search(r'^LOOK_GENERATION = "8"$', MASTERS, re.M)
    new = _def("_new", "_finish")
    assert "delete_all_material_expressions(material)" in new
    assert "delete_asset" not in new                       # never deleted: the look instances reference it
    assert "MATERIAL-UPDATED" in new and "MATERIAL-EXISTS" in new


def test_the_generation_sentinel_is_in_every_paint_and_bare_metal_graph():
    assert 'LOOK_GENERATION_PARAMETER = "LookGeneration"' in MASTERS
    surface = _def("_surface", "create_aircraft_paint")
    assert "_generation(material" in surface
    assert surface.index("_generation(material") < surface.index('_link(occlusion, "", out')


def test_the_coat_master_is_plain_clear_coat_and_never_darker_than_flat():
    coat = _def("create_aircraft_paint_coat", "create_aircraft_bare_metal")
    assert '"MSM_CLEAR_COAT"' in coat
    assert "_base_colour(material" in coat
    for absent in ("_custom(", "add_wet_layer", "_use_attributes", "tangent_space_normal", "AlbedoMax",
                   "VertexNormalWS", "MP_NORMAL"):
        assert absent not in coat, absent
    assert '"MP_CUSTOM_DATA0", "MP_CLEAR_COAT"' in coat and '"MP_CUSTOM_DATA1", "MP_CLEAR_COAT_ROUGHNESS"' in coat
    assert look.COAT_SCALARS == {k: look.CLASS_SCALARS["paint"][k]
                                 for k in ("Metallic", "Specular", "Roughness", "ClearCoat", "ClearCoatRoughness")}
    assert look.COAT_SCALARS["Metallic"] == 0.0
    creators = MASTERS[MASTERS.index("CREATORS = ("):MASTERS.index("CREATED = (")]
    assert "create_aircraft_paint_coat" in creators
    assert f'"{look.PROBE_COAT_MASTER}"' in MASTERS[MASTERS.index("CREATED = ("):MASTERS.index("def build_all")]


# -- 1. the c172p instrument panel -----------------------------------------------

def test_the_c172p_panel_is_a_beauty_only_interior_part():
    panel = [p for p in C172["parts"] if p["file"].endswith("c172p-interior.ac")]
    assert len(panel) == 1
    panel = panel[0]
    assert panel["interior"] is True and panel["beauty_only"] is True
    assert panel["file"] == "Models/Interior/Panel/c172p-panel/c172p-interior.ac"
    assert panel["texture_dir"] == "Models"                 # the panel XML's <texture-path>
    assert panel["exclude"] == ["glass_panel"]              # opaque glass would cover the gauges
    assert "offset_m" not in panel and "pitch_deg" not in panel   # c172p.xml loads it without <offsets>
    assert C172["parts"][0] == {"file": "Models/c172-common.ac"}
    assert C172.get("beauty_mesh")                          # beauty_only needs the beauty copy


def _tri(x):
    return [((x, 0.0, 0.0), (0.0, 0.0)), ((x, 100.0, 0.0), (1.0, 0.0)), ((x, 0.0, 100.0), (0.0, 1.0))]


def test_beauty_only_rows_go_after_the_measured_slots_and_never_into_the_measured_part(tmp_path):
    from assets_pipeline.convert import ObjWriter, _write_beauty_mesh

    body = ObjWriter()
    skin = body.material_key("fuselage.png", (1.0, 1.0, 1.0), 0.0)
    body.add_triangle(skin, _tri(0.0))
    body.write(tmp_path / "body.obj")
    before = (tmp_path / "body.obj").read_bytes()
    rows = [(skin, _tri(0.0), 1, False, 30.0, False, "fuselage")]
    extra_writer = ObjWriter()
    panel = extra_writer.material_key("panel.png", (1.0, 1.0, 1.0), 0.0)
    shared = extra_writer.material_key("fuselage.png", (1.0, 1.0, 1.0), 0.0)
    extra = [(panel, _tri(10.0), 2, False, 30.0, False, "panel_1_gauges"),
             (shared, _tri(20.0), 3, False, 30.0, False, "chassis")]
    record = _write_beauty_mesh(rows, {"normals": "crease", "two_sided": False}, body, tmp_path,
                                extra, extra_writer)["body"]
    assert record["beauty_only_triangles"] == 2 and record["beauty_only_slots"] == [panel]
    assert record["front_triangles"] == 3
    assert "beauty-only interior" in record["drawn_in"]
    usemtl = lambda text: [l.split()[1] for l in text.splitlines() if l.startswith("usemtl")]
    beauty = (tmp_path / "body_beauty.obj").read_text(encoding="utf-8")
    plain = (tmp_path / "body.obj").read_text(encoding="utf-8")
    # the measured slots are the copy's FIRST ones (the host's swap rule), the new one after
    assert usemtl(beauty)[:len(usemtl(plain))] == usemtl(plain)
    assert usemtl(beauty) == usemtl(plain) + [panel]
    assert (tmp_path / "body.obj").read_bytes() == before


def test_without_beauty_only_rows_the_copy_is_unchanged(tmp_path):
    from assets_pipeline.convert import ObjWriter, _write_beauty_mesh

    body = ObjWriter()
    skin = body.material_key("fuselage.png", (1.0, 1.0, 1.0), 0.0)
    body.add_triangle(skin, _tri(0.0))
    body.write(tmp_path / "body.obj")
    record = _write_beauty_mesh([(skin, _tri(0.0), 1, False, 30.0, False, "fuselage")],
                                {"normals": "crease", "two_sided": False}, body, tmp_path)["body"]
    assert "beauty_only_triangles" not in record and "beauty_only_slots" not in record


def test_the_converter_routes_beauty_only_parts_and_refuses_one_without_a_beauty_copy():
    src = (ROOT / "assets_pipeline/convert.py").read_text(encoding="utf-8")
    loop = src[src.index("    for part in config[\"parts\"]:"):src.index("    if livery is not None:\n        unmatched")]
    assert 'beauty_only = bool(part.get("beauty_only"))' in loop
    assert "if beauty_only and (not interior or beauty is None):" in loop
    assert 'part_exclude = list(exclude) + list(part.get("exclude", []))' in loop
    assert "_matches(obj.name, part_exclude)" in loop
    assert "texture_path = ((texture_dir or ac_path.parent) / obj.texture)" in loop
    # a beauty-only triangle is appended to the beauty rows and never reaches body.obj
    guard = loop[loop.index("if beauty_only:\n"):loop.index("writer.add_triangle(key, tri)\n")]
    assert "beauty_only_rows.append(" in guard and "continue" in guard
    assert "beauty_only_rows, beauty_only_writer)" in src


def test_the_slot_rule_is_a_prefix_on_both_sides():
    import ue_aircraft_materials as m

    report = {"slot_names": {"body": ["a", "b"], "body_beauty": ["a", "b", "panel"]}}
    assert m.beauty_slot_mismatches(report, {"body": {"part": "body_beauty"}}) == []
    report = {"slot_names": {"body": ["a", "b"], "body_beauty": ["b", "a", "panel"]}}
    assert len(m.beauty_slot_mismatches(report, {"body": {"part": "body_beauty"}})) == 1
    report = {"slot_names": {"body": ["a", "b"], "body_beauty": ["a"]}}
    assert len(m.beauty_slot_mismatches(report, {"body": {"part": "body_beauty"}})) == 1
    apply = _apply()
    assert "bool bSameSlots = From.Num() <= To.Num();" in apply
    assert "MaterialSlotName == To[Slot].MaterialSlotName" in apply
    assert 'TEXT("beauty_only_slots")' in apply


@pytest.mark.parametrize("field", ["beauty_only", "texture_dir", "exclude"])
def test_no_other_airframe_uses_the_round25_part_fields(field):
    for path in sorted((ROOT / "assets/aircraft_config").glob("*.json")):
        if path.stem == "c172p":
            continue
        config = json.loads(path.read_text(encoding="utf-8"))
        assert all(field not in part for part in config.get("parts", [])), path.name
