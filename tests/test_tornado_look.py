"""Visual push lane C (2026-11-11): #10's tornado in beauty.

Round 5 (f7232cc7) drew the tornado as a tan cone on a faceted octagonal base
filling the frame. Pinned here by reading the source (no engine on this
machine): the beauty refines the scenario world's markers in place
(FlightSimTornadoBeauty.cpp, smooth ragged funnel, a wall cloud that thins into
the deck, Kenney CC0 smoke puffs for the dust and scud) under -quality=beauty
only, so the measure renders keep Build's meshes byte for byte; the funnel stays
depth-writing for the labels; every C++ constant equals its Python twin; the
puff atlas is the pinned, licensed bytes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from core.scene import weather_look

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
BEAUTY_CPP = (BRIDGE / "Private" / "FlightSimTornadoBeauty.cpp").read_text(encoding="utf-8")
SCENARIO_CPP = (BRIDGE / "Private" / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
SCENARIO_H = (BRIDGE / "Public" / "FlightSimScenarioWorld.h").read_text(encoding="utf-8")
COMMANDLET_CPP = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
TORNADO_ASSETS = REPO / "assets" / "looks" / "tornado"
THIRD_PARTY = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")


def _cpp(name):
    match = re.search(rf"constexpr (?:double|float|int32) {name} = ([0-9.eE+-]+|0x[0-9A-Fa-f]+)f?;",
                      BEAUTY_CPP)
    assert match, name
    return float(int(match.group(1), 16)) if match.group(1).startswith("0x") else float(match.group(1))


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not in the material script")


def _function(text, name, next_name):
    return text[text.index(f"def {name}"):text.index(f"def {next_name}")]


# -- measure is untouched ----------------------------------------------------------


def test_the_measure_markers_are_build_s_own_unchanged():
    """Build's markers (drawn on every quality) keep round 6's shape: the lane C
    geometry exists only in the beauty-only refinement."""
    block = SCENARIO_CPP[SCENARIO_CPP.index("// -- tornado funnel marker"):SCENARIO_CPP.index("// -- the aircraft")]
    assert "const int32 Segments = 24;" in block and "const int32 Rings = 20;" in block
    assert "AddRing(2.2 * RCore, 0.0, 0.0," in block                 # the measure dust skirt
    assert "UMaterial::GetDefaultMaterial(" in block                  # the measure material
    assert "BuildBeautyTornado(" not in block
    # Build only records where it put the axis for the beauty.
    assert "TornadoAxisEngine = AxisEngine;" in block
    assert "TornadoShapePhase = Phase;" in block


def test_the_refinement_runs_on_beauty_only_before_the_world_lane():
    call = "Scenario.BuildBeautyTornado(Card, VisualScene.BeautyOnlyActors, VisualScene.LookApplied);"
    assert COMMANDLET_CPP.count(call) == 1
    at = COMMANDLET_CPP.index(call)
    guard = COMMANDLET_CPP.rfind("if (", 0, at)
    assert COMMANDLET_CPP[guard:at].startswith("if (bBeauty && Card.bTornado)")
    assert at < COMMANDLET_CPP.index("if (bBeauty && !WorldBeauty.Build(")  # dressed after, labels later
    assert "bool BuildBeautyTornado(const FFlightSimScenarioCard& Card," in SCENARIO_H


def test_the_markers_keep_their_actors_and_spin_and_the_puffs_spin_too():
    assert "Cast<UProceduralMeshComponent>(TornadoFunnel->GetRootComponent())" in BEAUTY_CPP
    assert "Cast<UProceduralMeshComponent>(TornadoWallCloud->GetRootComponent())" in BEAUTY_CPP
    assert "Mesh->ClearAllMeshSections();" in BEAUTY_CPP
    assert "SpawnActor" not in BEAUTY_CPP.split("auto SpawnPuffActor")[0]   # no new marker actors
    step = SCENARIO_CPP[SCENARIO_CPP.index("if (TornadoFunnel != nullptr)"):]
    assert "TimeSeconds * TornadoDustOmegaDegPerSec" in step[:2000]
    assert "TimeSeconds * TornadoScudOmegaDegPerSec" in step[:2000]
    assert ("TornadoDustOmegaDegPerSec = TornadoOmegaDegPerSec / (BeautyDustSpinRadii * BeautyDustSpinRadii);"
            in BEAUTY_CPP)
    assert "TornadoScudOmegaDegPerSec = TornadoWallOmegaDegPerSec;" in BEAUTY_CPP
    assert _cpp("BeautyDustSpinRadii") == weather_look.BEAUTY_TORNADO_DUST_SPIN_RADII
    assert weather_look.dust_omega_scale() == pytest.approx(1.0)


# -- labels --------------------------------------------------------------------------


def test_the_puffs_are_beauty_only_and_the_funnel_writes_depth():
    assert BEAUTY_CPP.count("BeautyOnlyActors.Add(Actor);") == 1      # every puff actor, via SpawnPuffActor
    assert 'SpawnPuffActor(TEXT("TornadoDust"))' in BEAUTY_CPP
    assert 'SpawnPuffActor(TEXT("TornadoScud"))' in BEAUTY_CPP
    funnel = _function(SCRIPT, "create_tornado_funnel", "create_lightning():")
    body = funnel.split('"""', 2)[2]
    assert "BLEND_MASKED" in body and "BLEND_TRANSLUCENT" not in body
    assert "MP_OPACITY_MASK" in body and "WORLD_POSITION_OFFSET" not in body
    assert "VertexColor" not in body                                  # gotcha 26
    assert _assigned("WEATHER_LOOK_GENERATIONS")["M_TornadoFunnel"] == "4"
    # The sheath (section 1) is translucent and only ever drawn with its own material.
    soft = _function(SCRIPT, "create_tornado_funnel_soft", "create_tornado_puff():")
    assert "BLEND_TRANSLUCENT" in soft and "MP_OPACITY_MASK" not in soft and "VertexColor" not in soft
    assert _assigned("WEATHER_LOOK_GENERATIONS")["M_TornadoFunnelSoft"] == "1"
    assert "create_tornado_funnel_soft()" in SCRIPT[SCRIPT.index("create_tornado_funnel()   #"):]
    assert "Replace(FunnelMesh, 1, FunnelSheath);" in BEAUTY_CPP
    assert BEAUTY_CPP.index("if (SoftMaterial != nullptr)") < BEAUTY_CPP.index("Replace(FunnelMesh, 1, FunnelSheath);")
    assert "FunnelMesh->SetMaterial(1, Soft);" in BEAUTY_CPP
    puff = _function(SCRIPT, "create_tornado_puff", "create_rain_drop():")
    assert "BLEND_TRANSLUCENT" in puff and "MP_OPACITY_MASK" not in puff
    assert "create_tornado_puff()" in SCRIPT[SCRIPT.index("create_tornado_funnel()   #"):]


def test_the_core_mask_is_a_plain_torn_clip_and_the_sheath_is_soft():
    """Round 7 rendered generation 3's dither as a stipple: the core's clip is now
    deterministic (the labels see its silhouette exactly), the soft edge the sheath."""
    hlsl = (SHADERS / "tornado_funnel_mask.hlsl").read_text(encoding="utf-8")
    funnel = _function(SCRIPT, "create_tornado_funnel", "create_lightning():")
    for pin in ("Coverage", "Normal", "CamVec", "Noise", "EdgeSoft", "NoiseAmp"):
        assert f'"{pin}":' in funnel and pin in hlsl
    code = "\n".join(l for l in hlsl.splitlines() if not l.startswith("//"))
    assert "dither" not in code.lower() and "View." not in code and "Pixel" not in funnel
    assert "return saturate(Coverage * edge + NoiseAmp * (Noise - 0.5));" in hlsl
    assert _assigned("FUNNEL_MASK_CLIP") == 0.5
    assert _assigned("FUNNEL_STREAK_MIN") < 0.7                       # round 7: no visible texture at 0.7
    assert 'streaks.set_editor_property("output_min", FUNNEL_STREAK_MIN)' in funnel
    soft_hlsl = (SHADERS / "tornado_funnel_soft.hlsl").read_text(encoding="utf-8")
    soft = _function(SCRIPT, "create_tornado_funnel_soft", "create_tornado_puff():")
    for pin in ("Coverage", "Normal", "CamVec", "Noise", "Streaks", "Opacity", "EdgeSoft"):
        assert f'"{pin}":' in soft and pin in soft_hlsl
    assert 0.0 < _assigned("FUNNEL_MASK_EDGE_SOFT") < 1.0
    uv = (SHADERS / "tornado_puff_uv.hlsl").read_text(encoding="utf-8")
    puff = _function(SCRIPT, "create_tornado_puff", "create_rain_drop():")
    for pin in ("UV", "Tile", "Spin", "Turn"):
        assert f'"{pin}":' in puff and pin in uv
    for name in _assigned("PUFF_PARAMETERS"):
        assert f'FName(TEXT("{name}"))' in BEAUTY_CPP


# -- the C++ and its Python twin -----------------------------------------------------


def test_the_funnel_constants_are_the_pythons():
    c = weather_look.BEAUTY_TORNADO_FUNNEL
    for key, name in (("segments", "BeautyFunnelSegments"), ("rings", "BeautyFunnelRings"),
                      ("base_radii", "BeautyFunnelBaseRadii"), ("taper_power", "BeautyFunnelTaperPower"),
                      ("ground_coverage", "BeautyFunnelGroundCoverage"),
                      ("contact_share", "BeautyFunnelContactShare"), ("bend_radii", "BeautyFunnelBendRadii"),
                      ("sheath_scale", "BeautySheathScale"), ("sheath_pad_radii", "BeautySheathPadRadii"),
                      ("sheath_coverage", "BeautySheathCoverage")):
        assert _cpp(name) == c[key], name
    assert _cpp("TornadoBeautyFunnelTopShare") == weather_look.FUNNEL_TOP_SHARE
    assert _cpp("TornadoBeautyFunnelTopRadii") == weather_look.FUNNEL_TOP_RADII
    assert _cpp("TornadoBeautyWallTopShare") == weather_look.WALL_TOP_SHARE
    # Tapered: a narrow rope at the ground flaring into the wall cloud.
    assert weather_look.beauty_funnel_radius_radii(0.0) == pytest.approx(0.16)
    assert weather_look.beauty_funnel_radius_radii(0.5) < 0.4
    assert weather_look.beauty_funnel_radius_radii(1.0) == pytest.approx(weather_look.FUNNEL_TOP_RADII)
    assert weather_look.beauty_funnel_coverage(0.0) == pytest.approx(0.25)
    assert weather_look.beauty_funnel_coverage(0.12) == pytest.approx(1.0)
    # Smooth: many more facets than the measure marker's 24 x 20.
    assert c["segments"] >= 48 and c["rings"] >= 64


def test_the_wall_profile_is_the_pythons_and_dissolves_at_the_rim():
    rows = re.findall(r"\{([0-9.]+), ([0-9.]+), ([0-9.]+), ([0-9.]+)\},",
                      BEAUTY_CPP[BEAUTY_CPP.index("BeautyWallProfile[BeautyWallRows][4]"):])
    rows = tuple(tuple(float(v) for v in row) for row in rows[:int(_cpp("BeautyWallRows"))])
    assert rows == weather_look.BEAUTY_TORNADO_WALL_PROFILE
    assert _cpp("BeautyWallSegments") == weather_look.BEAUTY_TORNADO_WALL_SEGMENTS
    widest = max(rows, key=lambda r: r[1])
    assert widest[2] == 0.0                                           # the rim is gone, not a hard edge
    assert rows[0][1] == weather_look.FUNNEL_TOP_RADII and rows[0][2] == 1.0


def test_the_puff_constants_are_the_pythons():
    p = weather_look.BEAUTY_TORNADO_PUFFS
    assert _cpp("BeautyDustPuffs") == p["dust"]["count"]
    assert _cpp("BeautyDustArms") == p["dust"]["arms"]
    assert _cpp("BeautyDustSpiralTurns") == p["dust"]["spiral_turns"]
    assert _cpp("BeautyDustJitterRadii") == p["dust"]["jitter_radii"]
    assert (_cpp("BeautyDustRadiiMin"), _cpp("BeautyDustRadiiMax")) == p["dust"]["radii"]
    assert (_cpp("BeautyDustSizeMinM"), _cpp("BeautyDustSizeMaxM")) == p["dust"]["size_m"]
    assert _cpp("BeautyDustTopM") == p["dust"]["top_m"]
    assert (_cpp("BeautySheathColourR"), _cpp("BeautySheathColourG"), _cpp("BeautySheathColourB")) \
        == weather_look.BEAUTY_TORNADO_SHEATH_COLOUR
    assert (_cpp("BeautyDustOpacityMin"), _cpp("BeautyDustOpacityMax")) == p["dust"]["opacity"]
    assert (_cpp("BeautyDustColourR"), _cpp("BeautyDustColourG"), _cpp("BeautyDustColourB")) == p["dust"]["colour"]
    assert _cpp("BeautyDebrisPuffs") == p["debris"]["count"]
    assert (_cpp("BeautyDebrisRadiiMin"), _cpp("BeautyDebrisRadiiMax")) == p["debris"]["radii"]
    assert (_cpp("BeautyDebrisShareMin"), _cpp("BeautyDebrisShareMax")) == p["debris"]["share"]
    assert (_cpp("BeautyDebrisSizeMinM"), _cpp("BeautyDebrisSizeMaxM")) == p["debris"]["size_m"]
    assert _cpp("BeautyScudPuffs") == p["scud"]["count"]
    assert (_cpp("BeautyScudRadiiMin"), _cpp("BeautyScudRadiiMax")) == p["scud"]["radii"]
    assert _cpp("BeautyScudBandM") == p["scud"]["band_m"]
    assert (_cpp("BeautyScudSizeMinM"), _cpp("BeautyScudSizeMaxM")) == p["scud"]["size_m"]
    assert (_cpp("BeautyScudOpacityMin"), _cpp("BeautyScudOpacityMax")) == p["scud"]["opacity"]
    assert (_cpp("BeautyScudColourR"), _cpp("BeautyScudColourG"), _cpp("BeautyScudColourB")) == p["scud"]["colour"]
    # Round 7: one beige blob wider than the funnel is tall. The whirl is a few
    # core radii across, low (its tallest puff well under the funnel's height),
    # and darker than the funnel.
    assert 2.0 * weather_look.dust_whirl_extent_radii() < 3.5
    funnel_height_m = weather_look.FUNNEL_TOP_SHARE * 1500.0
    assert p["dust"]["top_m"] + p["dust"]["size_m"][1] < 0.2 * funnel_height_m
    assert 2.0 * weather_look.dust_whirl_extent_radii() * 150.0 < 0.6 * funnel_height_m
    assert max(p["dust"]["colour"]) < min(weather_look.BEAUTY_FUNNEL_COLOUR)
    # The scud is darker than the funnel; the wall cloud darker still than the funnel.
    assert max(p["scud"]["colour"]) < min(weather_look.BEAUTY_FUNNEL_COLOUR)
    assert max(weather_look.BEAUTY_WALL_CLOUD_COLOUR) < min(weather_look.BEAUTY_FUNNEL_COLOUR)


# -- the third-party asset -----------------------------------------------------------


def test_the_puff_atlas_is_the_pinned_cc0_bytes():
    pin = json.loads((TORNADO_ASSETS / "PIN.json").read_text(encoding="utf-8"))
    assert pin["licence"] == "CC0-1.0"
    atlas = (TORNADO_ASSETS / pin["atlas"]["file"]).read_bytes()
    assert hashlib.sha256(atlas).hexdigest() == pin["atlas"]["sha256"]
    assert len(atlas) < 512 * 1024                                     # small
    licence = (TORNADO_ASSETS / "LICENSE").read_bytes()
    assert hashlib.sha256(licence).hexdigest() == pin["files"]["LICENSE"]["sha256"]
    assert b"License (CC0)" in licence
    for name in pin["atlas"]["tiles"]:
        entry = pin["files"][name]
        assert entry["url"].startswith("https://raw.githubusercontent.com/") and pin["commit"] in entry["url"]
        assert entry["sha256"] in THIRD_PARTY                           # listed with its digest
    assert pin["atlas"]["sha256"] in THIRD_PARTY
    assert _assigned("PUFF_ATLAS") == "assets/looks/tornado/puffs_atlas.png"


def test_the_atlas_generator_decodes_and_reencodes_losslessly():
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_tornado_puffs", REPO / "scripts" / "make_tornado_puffs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    width, height, pixels = module.decode_png((TORNADO_ASSETS / "puffs_atlas.png").read_bytes())
    assert (width, height) == (512, 512)
    again = module.encode_grey_alpha(width, height, pixels)
    assert hashlib.sha256(again).hexdigest() == hashlib.sha256(
        (TORNADO_ASSETS / "puffs_atlas.png").read_bytes()).hexdigest()
    corner = pixels[0]
    assert corner[1] == 0.0                                            # transparent margins


def test_the_lane_c_engine_symbols_are_in_the_bridge_check():
    block = CHECK[CHECK.index("BEGIN tornado-beauty"):CHECK.index("END tornado-beauty")]
    for needle in ("ClearAllMeshSections", "CreateMeshSection_LinearColor", "AddElement(",
                   "SetupAttachment", "UMaterialInstanceDynamic* Create(", "FRandRange",
                   "OpacityMaskClipValue", "TLM_SurfacePerPixelLighting", "CeilToDouble",
                   "SetVectorParameterValue", "MaterialExpressionDepthFade"):
        assert needle in block, needle


# -- round 7's green #10: the storm deck's ground bounce ------------------------------


def test_the_storm_ground_bounce_is_a_neutral_grey_of_the_same_luminance(tmp_path):
    """The C++ pure NeutralAlbedoSrgb equals world_beauty.neutral_albedo_srgb on every
    surface row and wetness, and keeps the row's linear luminance."""
    from core.scene import world_beauty as wb
    import subprocess

    from tests.test_world_beauty import CLOUDS_CPP, _block

    def _compile_and_run(tmp, pure, main_text):
        # The pure block alone with this one main: its unused helpers would trip
        # test_world_beauty's -Werror, so warnings stay warnings here.
        source = tmp / "pure.cpp"
        source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                          + pure + "\n" + main_text, encoding="utf-8")
        binary = tmp / "pure"
        subprocess.run(["g++", "-std=c++17", "-O1", "-w", "-o", str(binary), str(source)],
                       check=True, capture_output=True, text=True)
        return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()

    block = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    cases = [(s, w) for s in wb.GROUND_ALBEDO_SRGB for w in (0.0, 0.85, 1.0)]
    main = ["using namespace FlightSimWorldPure;", "int main() {"]
    for s, w in cases:
        main.append(f"{{ int R[3]; int N[3]; GroundAlbedoSrgb(GroundSurfaceIndex(\"{s}\"), {w!r}, R);"
                    " NeutralAlbedoSrgb(R, N); printf(\"n %d %d %d\\n\", N[0], N[1], N[2]); }")
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, block, "\n".join(main))
    got = [tuple(map(int, l.split()[1:])) for l in lines if l.startswith("n ")]
    assert got == [wb.neutral_albedo_srgb(wb.ground_albedo_srgb(s, w)) for s, w in cases]
    grass = wb.ground_albedo_srgb("grassland", 0.85)
    grey = wb.neutral_albedo_srgb(grass)
    assert grey[0] == grey[1] == grey[2]
    lum = lambda rgb: sum(k * wb._srgb_to_linear(c) for k, c in zip((0.2126, 0.7152, 0.0722), rgb))
    assert lum(grey) == pytest.approx(lum(grass), rel=0.03)
    # Storm only, and the A/B keeps the hue.
    assert wb.world_ground_albedo_srgb("grassland", 0.85, "storm") == grey
    assert wb.world_ground_albedo_srgb("grassland", 0.85, "storm", "surface") == grass
    assert wb.world_ground_albedo_srgb("grassland", 0.85, "rain") == grass
    assert wb.STORM_GROUND_ALBEDO_DEFAULT == "neutral"


def test_the_world_lane_uses_the_neutral_bounce_under_the_storm_preset():
    from tests.test_world_beauty import CLOUDS_CPP

    assert "Atmosphere->SetGroundAlbedo(Albedo);" in CLOUDS_CPP
    assert "const FColor Albedo = WorldAlbedo(Surface, GroundWetness, StormNeutralAlbedo());" in CLOUDS_CPP
    assert "Cloud->SetGroundAlbedo(WorldAlbedo(Surface, GroundWetness, StormNeutralAlbedo()));" in CLOUDS_CPP
    assert ('return Preset == FlightSimWorldPure::PresetStorm && StormAlbedoSwitch != TEXT("surface");'
            in CLOUDS_CPP)
    assert 'FParse::Value(*Switches, TEXT("storm-ground-albedo="), StormAlbedoSwitch);' in CLOUDS_CPP
    assert "WorldAlbedo(Surface, GroundWetness)" not in CLOUDS_CPP     # every call site decides
