"""Visual round 5, lane L3 (2026-11-10): the distant 2D cloud sheet and the sky
HDRI probe. What must hold without an engine:

* the C++ pure laws (FlightSimClouds.cpp DistantSheet*, DistantLook) are the
  Python ones (core/scene/world_beauty.py DISTANT_*), compiled and compared;
* the material script's parameters, the HLSL inputs and the C++ names agree,
  the material is unlit translucent with no custom-depth or velocity write,
  and its shared noise is cloud_layers.hlsl's, text for text;
* the sheet is beauty only and label safe (BeautyOnlyActors, no custom depth,
  no shadow, no collision) and the volumetric trace never rises;
* the switches are registered and their refusals are in the catalogue;
* the sky HDRI is pinned (CC0, sha256), fetched and verified, its RGBE codec
  round-trips, the sun clamp normalises, and a bad digest is refused by name.
"""

import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from core import config_surface
from core.scene import sky_hdri as sh
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
CATALOG = (REPO / "core" / "messages" / "catalog.yaml").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "world"
DISTANT_HLSL = (SHADERS / "distant_clouds.hlsl").read_text(encoding="utf-8")
LAYERS_HLSL = (SHADERS / "cloud_layers.hlsl").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _block(text, begin, end):
    return text[text.index(begin) + len(begin):text.index(end)]


def _body(text, name, nxt):
    return text[text.index(name):text.index(nxt)]


def _script_value(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


APPLY_DISTANT = _body(CLOUDS_CPP, "void FFlightSimWorldBeauty::ApplyDistantClouds(",
                      "bool FFlightSimWorldBeauty::ApplySkyHdri(")
APPLY_HDRI = _body(CLOUDS_CPP, "bool FFlightSimWorldBeauty::ApplySkyHdri(", "void FFlightSimWorldBeauty::ApplyTiles(")
CREATE = _body(SCRIPT, "def create_world_distant_clouds", "def create_sky_hdri")
CREATE_HDRI = _body(SCRIPT, "def create_sky_hdri", "# == END WORLD LANE")


# -- the laws, Python and C++ -------------------------------------------------------------

def test_the_python_sheet_laws():
    # the rings densify towards the centre and end at the radius
    radii = [wb.distant_ring_radius_km(i) for i in range(wb.DISTANT_RINGS + 1)]
    assert radii[0] == 0.0 and radii[-1] == wb.DISTANT_RADIUS_KM
    assert all(b > a for a, b in zip(radii, radii[1:]))
    assert radii[1] < 0.2   # the first ring within 200 m: metre-fine near the camera
    # the droop is the earth's curvature: 300 km -> about 7.1 km
    assert wb.distant_droop_m(0.0) == 0.0
    assert wb.distant_droop_m(300.0) == pytest.approx(-7063.6, abs=1.0)
    assert wb.distant_droop_m(113.0) == pytest.approx(-1002.0, abs=1.0)   # the horizon from 1 km
    # the sheet: bases from below, tops from above, off inside the slab
    below = wb.distant_sheet_altitude_m(500.0, 1500.0, 2700.0)
    assert below == {"altitude_m": 1500.0, "from_above": False, "fade": 1.0}
    above = wb.distant_sheet_altitude_m(3800.0, 1500.0, 2700.0)
    assert above == {"altitude_m": 2700.0, "from_above": True, "fade": 1.0}
    inside = wb.distant_sheet_altitude_m(2000.0, 1500.0, 2700.0)
    assert inside["fade"] == 0.0 and inside["from_above"] is False
    assert wb.distant_sheet_altitude_m(1400.0, 1500.0, 2700.0)["fade"] == pytest.approx(0.5)
    assert wb.distant_sheet_altitude_m(2800.0, 1500.0, 2700.0)["fade"] == pytest.approx(0.5)
    # the trace: constrained and drawn -> the near field; never above the row
    assert wb.distant_tracing_max_km(True, True, 80.0) == wb.DISTANT_NEAR_FIELD_KM
    assert wb.distant_tracing_max_km(True, False, 80.0) == 80.0
    assert wb.distant_tracing_max_km(False, True, 50.0) == 50.0
    assert wb.distant_tracing_max_km(True, True, 20.0) == 20.0
    for constrained in (True, False):
        for drawn in (True, False):
            row = wb.CLOUD_MARCH["integrated" if constrained else "discrete"]["tracing_max_distance_km"]
            assert wb.distant_tracing_max_km(constrained, drawn, row) <= row
    assert wb.distant_handover_km(32.0) == 24.0
    assert wb.distant_handover_km(4.0) == 0.0
    # the disc's size, the rim's droop, the storm cover, the switch
    assert wb.distant_disc_vertex_count() == 1 + 48 * 96
    assert wb.distant_disc_triangle_count() == 96 + 2 * 47 * 96
    assert wb.distant_droop_at_rim_m() == wb.distant_droop_m(300.0)
    assert wb.distant_storm_cover() == wb.CLOUDS["nimbostratus"]["default_cover"]
    assert wb.distant_clouds_mode({}) == "on" and wb.distant_clouds_mode({"FLIGHTSIM_DISTANT_CLOUDS": "off"}) == "off"
    with pytest.raises(ValueError, match="world_beauty.distant_clouds"):
        wb.distant_clouds_mode({"FLIGHTSIM_DISTANT_CLOUDS": "fair"})
    # the hand-over sits inside the near field, and the sheet fades in before the trace ends
    assert wb.DISTANT_FADE_KM < wb.DISTANT_NEAR_FIELD_KM
    # the constrained march row is untouched (the round-1 hang's pin)
    row = wb.cloud_march(True)
    assert (row["view_samples_max"], row["shadow_samples"], row["tracing_max_distance_km"]) == (192.0, 10.0, 80.0)


@NEEDS_CXX
def test_the_cpp_distant_laws_are_the_python_ones(tmp_path):
    block = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    cameras = (0.0, 500.0, 1400.0, 1500.0, 2000.0, 2100.0, 2700.0, 2800.0, 3800.0)
    traces = [(c, d, r) for c in (0, 1) for d in (0, 1) for r in (20.0, 50.0, 80.0)]
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            "for (int f = 0; f < DistantLookCount; ++f) printf(\"look %s %.17g\\n\", DistantLookName(f), DistantLook(f));",
            "printf(\"const %.17g %d %d %.17g %.17g %.17g %.17g %s\\n\", DistantRadiusKm, DistantRings, DistantSegments,"
            " DistantEarthRadiusKm, DistantFadeKm, DistantNearFieldKm, DistantInsideRampM, CloudName(DistantStormShape));",
            "printf(\"disc %d %d %.17g %.17g\\n\", DistantDiscVertexCount(), DistantDiscTriangleCount(), DistantDroopAtRimM(),"
            " DistantStormCover(nullptr));",
            "for (int i = 0; i <= DistantRings; ++i) printf(\"ring %.17g\\n\", DistantRingRadiusKm(i, DistantRings, DistantRadiusKm));",
            "for (double d = 0.0; d <= 300.0; d += 37.5) printf(\"droop %.17g\\n\", DistantDroopM(d));"]
    for c in cameras:
        main.append(f"{{ FDistantSheet S = DistantSheetAltitudeM({c!r}, 1500.0, 2700.0);"
                    " printf(\"sheet %.17g %d %.17g\\n\", S.AltitudeM, S.bFromAbove ? 1 : 0, S.Fade); }")
    for c, d, r in traces:
        main.append(f"printf(\"trace %.17g\\n\", DistantTracingMaxKm({'true' if c else 'false'}, "
                    f"{'true' if d else 'false'}, {r!r}));")
    for t in (4.0, 32.0, 50.0, 80.0):
        main.append(f"printf(\"hand %.17g\\n\", DistantHandoverKm({t!r}));")
    main.append("return 0; }")
    source = tmp_path / "distant.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-o", str(tmp_path / "distant"), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "distant")], check=True, capture_output=True,
                           text=True).stdout.splitlines()
    look = [line.split() for line in lines if line.startswith("look ")]
    assert [name for _, name, _ in look] == list(wb.DISTANT_LOOK)
    assert {name: float(v) for _, name, v in look} == wb.DISTANT_LOOK
    const = next(line for line in lines if line.startswith("const ")).split()[1:]
    assert float(const[0]) == wb.DISTANT_RADIUS_KM and int(const[1]) == wb.DISTANT_RINGS
    assert int(const[2]) == wb.DISTANT_SEGMENTS and float(const[3]) == wb.DISTANT_EARTH_RADIUS_KM
    assert float(const[4]) == wb.DISTANT_FADE_KM and float(const[5]) == wb.DISTANT_NEAR_FIELD_KM
    assert float(const[6]) == wb.DISTANT_INSIDE_RAMP_M and const[7] == wb.DISTANT_STORM_SHAPE
    disc = next(line for line in lines if line.startswith("disc ")).split()[1:]
    assert (int(disc[0]), int(disc[1])) == (wb.distant_disc_vertex_count(), wb.distant_disc_triangle_count())
    assert float(disc[2]) == pytest.approx(wb.distant_droop_at_rim_m(), rel=1e-15)
    assert float(disc[3]) == wb.distant_storm_cover()
    rings = [float(l.split()[1]) for l in lines if l.startswith("ring ")]
    assert rings == pytest.approx([wb.distant_ring_radius_km(i) for i in range(wb.DISTANT_RINGS + 1)], rel=1e-15)
    droops = [float(l.split()[1]) for l in lines if l.startswith("droop ")]
    assert droops == pytest.approx([wb.distant_droop_m(d) for d in np.arange(0.0, 300.01, 37.5)], rel=1e-15)
    sheets = [l.split()[1:] for l in lines if l.startswith("sheet ")]
    for c, (alt, above, fade) in zip(cameras, sheets):
        ref = wb.distant_sheet_altitude_m(c, 1500.0, 2700.0)
        assert (float(alt), bool(int(above))) == (ref["altitude_m"], ref["from_above"]), c
        assert float(fade) == pytest.approx(ref["fade"], rel=1e-15)
    got = [float(l.split()[1]) for l in lines if l.startswith("trace ")]
    assert got == [wb.distant_tracing_max_km(bool(c), bool(d), r) for c, d, r in traces]
    assert [float(l.split()[1]) for l in lines if l.startswith("hand ")] == [
        wb.distant_handover_km(t) for t in (4.0, 32.0, 50.0, 80.0)]


# -- the material, the shader and the C++ agree ----------------------------------------------

def test_the_shader_inputs_are_the_scripts_and_the_cpp_sets_them():
    scalars = _script_value("WORLD_DISTANT_SCALARS")
    vectors = _script_value("WORLD_DISTANT_VECTORS")
    engine = _script_value("WORLD_DISTANT_ENGINE_INPUTS")
    inputs = tuple(engine) + tuple(scalars) + tuple(vectors)
    for name in inputs:
        assert re.search(rf"//\s+{name}\s", DISTANT_HLSL), name
        assert re.search(rf"\b{name}\b", DISTANT_HLSL.split("FWorldCloud C;")[1]), f"{name} unused in the body"
    # the C++ sets every scalar: the literal ones plus the look table by name
    literal = set(re.findall(r'(?<!Layer\.)Material->SetScalarParameterValue\(TEXT\("([A-Za-z]+)"\)', APPLY_DISTANT))
    names = re.search(r"static const char\* const Names\[DistantLookCount\] = \{([^}]*)\};",
                      CLOUDS_CPP, re.S).group(1)
    look_names = re.findall(r'"([A-Za-z]+)"', names)
    assert "DistantLookName(F)" in APPLY_DISTANT
    assert literal | set(look_names) == set(scalars)
    assert set(re.findall(r'Material->SetVectorParameterValue\(TEXT\("([A-Za-z]+)"\)', APPLY_DISTANT)) == set(vectors)
    # Advance sets the per-frame ones
    advance = _body(CLOUDS_CPP, "void FFlightSimWorldBeauty::Advance(", "TSharedPtr<FJsonObject> FFlightSimWorldBeauty::CloudOcclusionRecord")
    assert 'DistantSheet.Material->SetScalarParameterValue(TEXT("SheetFade")' in advance
    assert 'DistantSheet.Material->SetVectorParameterValue(TEXT("WindOffsetM")' in advance
    assert "DistantSheet.Actor->SetActorLocation(FVector(CameraCm.X, CameraCm.Y, Sheet.AltitudeM * WorldCmPerMetre));" in advance
    # the look defaults are the Python table's; the hand-over defaults the constrained near field
    assert {k: scalars[k] for k in wb.DISTANT_LOOK} == wb.DISTANT_LOOK
    assert look_names == list(wb.DISTANT_LOOK)
    assert scalars["HandoverKm"] == wb.distant_handover_km(wb.DISTANT_NEAR_FIELD_KM)
    assert scalars["FadeKm"] == wb.DISTANT_FADE_KM and scalars["RadiusKm"] == wb.DISTANT_RADIUS_KM
    cumulus = wb.CLOUDS["cumulus"]
    assert scalars["Coverage"] == cumulus["default_cover"]
    assert scalars["ShapeScaleKm"] == cumulus["shape_scale_km"]
    assert scalars["CoverageContrast"] == cumulus["coverage_contrast"]
    assert scalars["SheetFade"] == 1.0


def test_the_sheet_shares_the_volumetric_noise_and_its_cut():
    shared_a = _block(DISTANT_HLSL, "// shared: world cloud noise (cloud_layers.hlsl FWorldCloud, text-equal)\n", "// end shared")
    shared_b = _block(LAYERS_HLSL, "const float WISP_HEIGHT = 0.25;\n", "FWorldCloud C;")
    assert shared_a == shared_b
    for name, value in (("FBM_MEAN", wb.CLOUD_FBM_MEAN), ("FBM_SIGMA", wb.CLOUD_FBM_SIGMA)):
        assert f"const float {name} = {value};" in DISTANT_HLSL
    # the same cut, the same z stretch, one shape evaluation, derivatives for the normal
    assert "float thr = FBM_MEAN + FBM_SIGMA * C.Probit(1.0 - cover);" in DISTANT_HLSL
    assert "SliceKm * 2.0" in DISTANT_HLSL
    assert DISTANT_HLSL.count("C.ShapeLod(") == 1 and "C.Shape(" not in DISTANT_HLSL.split("// end shared")[1] and "C.Detail(" not in DISTANT_HLSL.split("// end shared")[1]
    assert "ddx(thick)" in DISTANT_HLSL and "ddy(thick)" in DISTANT_HLSL
    assert "return float4(L, a);" in DISTANT_HLSL
    assert "UNCALIBRATED" in DISTANT_HLSL
    assert "static const" not in DISTANT_HLSL


def test_the_material_is_unlit_translucent_and_label_safe():
    assert '_world_beauty_material("M_FlightSimDistantClouds")' in CREATE
    assert "MSM_UNLIT" in CREATE and "BLEND_TRANSLUCENT" in CREATE
    assert 'set_editor_property("two_sided", True)' in CREATE
    assert 'set_editor_property("use_translucency_vertex_fog", True)' in CREATE
    assert 'set_editor_property("compute_fog_per_pixel", True)' in CREATE
    assert 'set_editor_property("apply_cloud_fogging", True)' in CREATE
    assert 'set_editor_property("allow_translucent_custom_depth_writes", False)' in CREATE
    assert 'set_editor_property("output_translucent_velocity", False)' in CREATE
    assert "MaterialExpressionSkyAtmosphereLightDirection" in CREATE
    assert "MaterialExpressionSkyAtmosphereLightIlluminance" in CREATE
    assert "MaterialExpressionSkyAtmosphereDistantLightScatteredLuminance" in CREATE
    assert 'world_custom(material, lib, "distant_clouds", unreal.CustomMaterialOutputType.CMOT_FLOAT4' in CREATE
    assert "MP_EMISSIVE_COLOR" in CREATE and "MP_OPACITY" in CREATE
    assert "MP_BASE_COLOR" not in CREATE and "MD_VOLUME" not in CREATE
    assert CREATE.index('world_stamp(material, "M_FlightSimDistantClouds")') < CREATE.index("finish(material")
    assert "M_FlightSimDistantClouds" in _script_value("WORLD_BEAUTY_MATERIALS")
    assert int(_script_value("WORLD_GENERATIONS")["M_FlightSimDistantClouds"]) >= 1
    assert int(_script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimDistantClouds"]) >= 1
    calls = re.findall(r"^(create_world_distant_clouds|create_sky_hdri)\(\)", SCRIPT, re.M)
    assert calls == ["create_world_distant_clouds", "create_sky_hdri"]
    assert SCRIPT.index("\ncreate_world_scatter()\n") < SCRIPT.index("\ncreate_world_distant_clouds()")
    assert SCRIPT.index("\ncreate_sky_hdri()") < SCRIPT.index("\ncreate_aircraft_masters()  # AIRCRAFT LANE")


def test_the_cpp_sheet_is_beauty_only_and_label_safe():
    assert "Mesh->SetRenderCustomDepth(false);" in APPLY_DISTANT
    assert "Mesh->SetCastShadow(false);" in APPLY_DISTANT
    assert "Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);" in APPLY_DISTANT
    assert "Mesh->SetTranslucentSortPriority(-100);" in APPLY_DISTANT
    assert "Scene.BeautyOnlyActors.Add(Actor);" in APPLY_DISTANT
    assert "CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);" in APPLY_DISTANT
    assert "DistantDroopM(RadiusKm)" in APPLY_DISTANT and "DistantRingRadiusKm(Ring, DistantRings, DistantRadiusKm)" in APPLY_DISTANT
    # the trace shrinks only on the constrained class, only when drawn, never rises
    assert "DistantTracingMaxKm(bConstrained, true, RowKm)" in APPLY_DISTANT
    guard = APPLY_DISTANT.index("if (TraceKm < RowKm)")
    assert APPLY_DISTANT.index("Layer.Component->SetTracingMaxDistance(static_cast<float>(TraceKm));", guard) - guard < 300
    assert APPLY_DISTANT.count("SetTracingMaxDistance(") == 1
    # the engine content finding and the labels line are recorded
    assert "BP_Sky_Sphere" in APPLY_DISTANT and "M_Sky_Panning_Clouds2" in APPLY_DISTANT
    assert 'Out->SetStringField(TEXT("labels")' in APPLY_DISTANT
    assert 'Record->SetObjectField(TEXT("distant_clouds"), Out);' in APPLY_DISTANT
    assert "UNCALIBRATED: set by probe render on the render machine" in APPLY_DISTANT
    # Build: after the clearance (the sheet follows the slab drawn), before the tiles; off by word
    build = _body(CLOUDS_CPP, "bool FFlightSimWorldBeauty::Build(", "// -- tiles-delight")
    assert build.index("KeepAircraftClearOfClouds(Card, Aircraft, Weather);") < build.index(
        "ApplyDistantClouds(World, Scene, Weather, DistantMode, Seed);") < build.index("ApplyTiles(World, Tiles, CardWetness, SunElevationDeg);")
    assert 'if (DistantMode != TEXT("on") && DistantMode != TEXT("off"))' in build
    assert 'if (Mode == TEXT("off"))' in APPLY_DISTANT
    # the storm deck continues when no layer was redrawn
    assert "Weather.BeautyStormLayer(BaseM, TopM)" in APPLY_DISTANT and "DistantStormShape" in APPLY_DISTANT
    # the header declares the state and the two methods
    assert "struct FDistantSheetState" in CLOUDS_H and "void ApplyDistantClouds(" in CLOUDS_H
    assert "bool ApplySkyHdri(" in CLOUDS_H and "class UProceduralMeshComponent;" in CLOUDS_H
    assert '#include "ProceduralMeshComponent.h"' in CLOUDS_CPP


def test_the_sky_hdri_probe_is_a_switch_on_clear_presets_only():
    assert 'FlagOrEnv(TEXT("sky-hdri="), TEXT("FLIGHTSIM_SKY_HDRI"))' in CLOUDS_CPP
    assert 'if (Name.IsEmpty() || Name == TEXT("off"))' in APPLY_HDRI
    assert "if (Preset != PresetClear && Preset != PresetHazy)" in APPLY_HDRI
    assert "Sky->SourceType = SLS_SpecifiedCubemap;" in APPLY_HDRI
    assert "Sky->SetCubemap(Cube);" in APPLY_HDRI and "Sky->SetRealTimeCapture(false);" in APPLY_HDRI
    assert "Sky->SetIntensity(static_cast<float>(FillShare * SunLux / PI));" in APPLY_HDRI
    assert "Sky->SetCaptureIsDirty();" in APPLY_HDRI
    assert 'Record->SetObjectField(TEXT("sky_hdri"), Out);' in APPLY_HDRI
    # the asset path the C++ loads is the module's
    fmt = re.search(r'FString::Printf\(TEXT\("([^"]*T_SkyHdri_[^"]*)"\), \*Name, \*Name\)', APPLY_HDRI).group(1)
    assert fmt.replace("%s", "qwantani_puresky") == sh.asset_path("qwantani_puresky")
    assert f'SKY_HDRI_PATH = "{sh.HDRI_ASSET_DIR}"' in SCRIPT
    assert "sky_hdri.HDRI_ASSET_PREFIX" in CREATE_HDRI
    # the fill share default is one number in both
    assert f"constexpr double WorldSkyHdriFillShareDefault = {sh.HDRI_FILL_SHARE};" in CLOUDS_CPP
    # the editor script imports only a prepared, pinned, digest-matching file, and never silently
    assert 'os.environ.get("FLIGHTSIM_SKY_HDRI", "")' in CREATE_HDRI
    assert "sky_hdri.pin(name)" in CREATE_HDRI and "sky_hdri.sha256_of(source)" in CREATE_HDRI
    assert "raise RuntimeError" in CREATE_HDRI and "unreal.TextureCube" in CREATE_HDRI
    assert "SKY-HDRI-SKIPPED" in CREATE_HDRI


def test_the_switches_are_registered_and_the_refusals_catalogued():
    assert config_surface.by_key("distant_clouds").env == "FLIGHTSIM_DISTANT_CLOUDS"
    assert config_surface.by_key("sky_hdri").env == "FLIGHTSIM_SKY_HDRI"
    assert config_surface.by_key("hdri_cache").env == "FLIGHTSIM_HDRI_CACHE"
    for key in ("distant_clouds", "sky_hdri", "hdri_cache"):
        assert config_surface.by_key(key).bucket == "dev-only"
    assert 'FlagOrEnv(TEXT("distant-clouds="), TEXT("FLIGHTSIM_DISTANT_CLOUDS"))' in CLOUDS_CPP
    for name in ("world_beauty.distant_clouds", "world_beauty.sky_hdri"):
        assert f"\n{name}:\n" in CATALOG, name
        assert f'TEXT("{name}: ' in CLOUDS_CPP, name


def test_the_bridge_check_lists_the_distant_symbols():
    block = _block(CHECK, "# -- visual round 5, lane L3", "# -- visual round 5, lane L3 -- end")
    for symbol in ("BP_Sky_Sphere", "CreateMeshSection_LinearColor", "SetRenderCustomDepth",
                   "SetTranslucentSortPriority", "bComputeFogPerPixel", "bApplyCloudFogging",
                   "AllowTranslucentCustomDepthWrites", "UMaterialExpressionSkyAtmosphereLightDirection",
                   "UMaterialExpressionSkyAtmosphereDistantLightScatteredLuminance",
                   "r.VolumetricCloud.DistanceToSampleMaxCount", "InvDistanceToSampleCountMax",
                   "SLS_SpecifiedCubemap", "SetCubemap", "SetSourceCubemapAngle", "SetRealTimeCapture",
                   "SetCaptureIsDirty"):
        assert symbol in block, symbol


def test_the_finding_and_the_licence_are_written_down():
    probe = (REPO / "docs" / "visual" / "PROBE_LOG.md").read_text(encoding="utf-8")
    assert "## round-5 distant clouds (L3)" in probe
    assert "BP_Sky_Sphere" in probe and "DistanceToSampleMaxCount" in probe
    third = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    row = sh.HDRIS["qwantani_puresky"]
    assert row["sha256"] in third and row["url"] in third and "CC0" in third


# -- the sky HDRI module ----------------------------------------------------------------------

def test_the_pins_are_cc0_4k_and_sha256_pinned():
    for name, row in sh.HDRIS.items():
        assert row["licence"] in sh.HDRI_LICENCES
        assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), name
        assert row["url"].startswith("https://dl.polyhaven.org/") and row["url"].endswith("_4k.hdr")
        assert max(row["resolution"]) <= 4096
        assert set(row["presets"]) <= {"clear", "hazy"}
        assert sh.pin(name) is row
    with pytest.raises(ValueError, match="sky_hdri.unknown"):
        sh.pin("not_a_sky")
    assert sh.asset_path("x") == "/Game/FlightSim/Sky/T_SkyHdri_x.T_SkyHdri_x"


def _synthetic_sky(width=16, height=8):
    img = np.zeros((height, width, 3), dtype=np.float32)
    img[:, :, 2] = 0.4
    img[:, :, 1] = 0.3
    img[:, :, 0] = 0.2
    img[height // 2:] *= 0.5          # a darker ground half
    img[1, 11] = (900.0, 850.0, 800.0)  # the sun: row 1, column 11
    return img


def test_the_rgbe_codec_round_trips_flat_and_rle(tmp_path):
    img = _synthetic_sky()
    flat = tmp_path / "flat.hdr"
    sh.write_rgbe(flat, img)
    back = sh.read_rgbe(flat)
    assert back.shape == img.shape
    assert np.allclose(back, img, rtol=0.01, atol=1e-6)
    # an adaptive-RLE scanline, hand built: 16 wide, one run per channel (the sun column aside)
    width, height = 16, 1
    pixel = np.array([128, 96, 64, 128], dtype=np.uint8)   # 0.5, 0.375, 0.25 at exponent 0
    body = bytes([2, 2, width >> 8, width & 0xFF])
    for channel in range(4):
        body += bytes([128 + width, int(pixel[channel])])   # a run of 16
    header = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n" + f"-Y {height} +X {width}\n".encode()
    rle = tmp_path / "rle.hdr"
    rle.write_bytes(header + body)
    decoded = sh.read_rgbe(rle)
    assert decoded.shape == (1, 16, 3)
    assert np.allclose(decoded[0, 0], (0.5, 0.375, 0.25))
    assert np.allclose(decoded[0, 15], decoded[0, 0])
    (tmp_path / "not.hdr").write_bytes(b"\x89PNG not a radiance file\n")
    with pytest.raises(ValueError, match="sky_hdri.format"):
        sh.read_rgbe(tmp_path / "not.hdr")


def test_the_sun_is_found_clamped_and_the_upper_hemisphere_normalised():
    img = _synthetic_sky()
    lon, elev = sh.sun_direction_deg(img)
    assert lon == pytest.approx((11.5 / 16) * 360.0 - 180.0)
    assert elev == pytest.approx(90.0 - (1.5 / 8) * 180.0)
    out = sh.clamp_sun(img, factor=32.0)
    clamped = out["image"]
    assert out["clamped_pixels"] == 1 and 0.0 < out["clamped_energy_share"] < 1.0
    assert out["upper_mean_luminance_written"] == pytest.approx(1.0, rel=1e-5)
    assert sh.luminance(clamped[:4]).mean() == pytest.approx(1.0, rel=1e-5)
    # the sun pixel is now at the cap (relative to the normalised mean), the sky's colour kept
    cap_ratio = sh.luminance(clamped)[1, 11] / sh.luminance(clamped)[0, 0]
    assert cap_ratio == pytest.approx(32.0 * out["upper_median_luminance"] / sh.luminance(img)[0, 0], rel=1e-4)
    assert np.allclose(clamped[0, 0] / clamped[0, 0].sum(), img[0, 0] / img[0, 0].sum())


def test_fetch_verifies_the_digest_and_refuses_a_wrong_one(tmp_path, monkeypatch):
    good = b"not really an hdr but the bytes we pinned"
    row = dict(sh.HDRIS["qwantani_puresky"], sha256=hashlib.sha256(good).hexdigest(), url="https://example.invalid/x_4k.hdr")
    monkeypatch.setitem(sh.HDRIS, "test_sky", row)
    calls = []

    def bad_download(url, target):
        calls.append(url)
        Path(target).write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="sky_hdri.sha256"):
        sh.fetch("test_sky", tmp_path, download=bad_download)
    assert not sh.source_path("test_sky", tmp_path).exists()
    assert not list(tmp_path.glob("*.part"))

    def good_download(url, target):
        calls.append(url)
        Path(target).write_bytes(good)

    got = sh.fetch("test_sky", tmp_path, download=good_download)
    assert got == sh.source_path("test_sky", tmp_path) and got.read_bytes() == good
    sh.fetch("test_sky", tmp_path, download=good_download)
    assert len(calls) == 2   # the cached file is re-hashed and reused, not downloaded again
    got.write_bytes(b"rotted")
    sh.fetch("test_sky", tmp_path, download=good_download)
    assert len(calls) == 3 and got.read_bytes() == good
    with pytest.raises(ValueError, match="sky_hdri.unknown"):
        sh.fetch("nope", tmp_path, download=good_download)


def test_prepare_writes_the_sky_light_copy_and_its_sidecar(tmp_path, monkeypatch):
    img = _synthetic_sky()
    source = tmp_path / "src.hdr"
    sh.write_rgbe(source, img)
    payload = source.read_bytes()
    row = dict(sh.HDRIS["qwantani_puresky"], sha256=hashlib.sha256(payload).hexdigest(),
               url="https://example.invalid/test_sky_4k.hdr")
    monkeypatch.setitem(sh.HDRIS, "test_sky", row)
    cache = tmp_path / "cache"
    downloads = []

    def download(url, target):
        downloads.append(url)
        Path(target).write_bytes(payload)

    record = sh.prepare("test_sky", cache, download=download)
    assert record["source_sha256"] == row["sha256"] and record["asset"] == sh.asset_path("test_sky")
    assert record["clamped_pixels"] == 1 and record["resolution"] == [16, 8]
    assert record["sun_longitude_deg"] == pytest.approx((11.5 / 16) * 360.0 - 180.0)
    assert record["fill_share_default"] == sh.HDRI_FILL_SHARE and "UNCALIBRATED" in record["basis"]
    written = sh.read_rgbe(sh.skylight_path("test_sky", cache))
    assert sh.luminance(written[:4]).mean() == pytest.approx(1.0, rel=0.02)
    side = json.loads(sh.sidecar_path("test_sky", cache).read_text(encoding="utf-8"))
    assert side["skylight_sha256"] == sh.sha256_of(sh.skylight_path("test_sky", cache))
    # a second prepare reuses the sidecar; a forced one downloads nothing new either (cached source)
    assert sh.prepare("test_sky", cache, download=download) == record
    assert len(downloads) == 1
    sh.prepare("test_sky", cache, download=download, force=True)
    assert len(downloads) == 1
    assert sh.main(["list"]) == 0
