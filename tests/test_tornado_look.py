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
    assert weather_look.dust_omega_scale() == pytest.approx(1.0 / 1.6 ** 2)


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
    assert _assigned("WEATHER_LOOK_GENERATIONS")["M_TornadoFunnel"] == "3"
    puff = _function(SCRIPT, "create_tornado_puff", "create_rain_drop():")
    assert "BLEND_TRANSLUCENT" in puff and "MP_OPACITY_MASK" not in puff
    assert "create_tornado_puff()" in SCRIPT[SCRIPT.index("create_tornado_funnel()   #"):]


def test_the_mask_shader_dithers_coverage_by_the_frame():
    hlsl = (SHADERS / "tornado_funnel_mask.hlsl").read_text(encoding="utf-8")
    funnel = _function(SCRIPT, "create_tornado_funnel", "create_lightning():")
    for pin in ("Coverage", "Normal", "CamVec", "Noise", "Pixel", "EdgeSoft", "NoiseAmp"):
        assert f'"{pin}":' in funnel and pin in hlsl
    assert "View.StateFrameIndexMod8" in hlsl
    assert "return alpha + 0.4999 - dither;" in hlsl
    assert _assigned("FUNNEL_MASK_CLIP") == 0.5
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
    assert (_cpp("BeautyDustRadiiMin"), _cpp("BeautyDustRadiiMax")) == p["dust"]["radii"]
    assert (_cpp("BeautyDustSizeMinM"), _cpp("BeautyDustSizeMaxM")) == p["dust"]["size_m"]
    assert _cpp("BeautyDustTopShare") == p["dust"]["top_share"]
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
    # The dust is low: no puff centre above the dust band plus its own size.
    assert p["dust"]["top_share"] * 1500.0 < 100.0
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
                   "OpacityMaskClipValue", "TLM_SurfacePerPixelLighting", "PixelPosition",
                   "StateFrameIndexMod8", "MaterialExpressionDepthFade"):
        assert needle in block, needle
