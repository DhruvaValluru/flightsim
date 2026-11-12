"""2026-11-11, #02 super bright's blue shade: the tiles' baked sky-shade, neutralised.

core/scene/tiles_shade_neutral.py is the law; assets/shaders/world/tiles_shade_neutral.hlsl
runs it per frame in M_FlightSimTilesBeauty right after the de-light;
FlightSimClouds.cpp sets ShadeNeutralAmount (0 with -tiles-shade-neutral=off, the
A/B) and writes world_beauty.tiles.shade_neutral. Beauty only: the material is
the beauty tiles' alone. Nothing here renders (the probe is PROBE_LOG.md
"## #02 blue: the tiles' baked sky-shade").
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pytest

from core.scene import tiles_delight as td
from core.scene import tiles_shade_neutral as sn
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
HLSL = (REPO / "assets" / "shaders" / "world" / "tiles_shade_neutral.hlsl").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
CLOUDS_CPP = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
              / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Public"
            / "FlightSimClouds.h").read_text(encoding="utf-8")
PROBE_LOG = (REPO / "docs" / "visual" / "PROBE_LOG.md").read_text(encoding="utf-8")

#: Round 51's #02 shade (lower-right quadrant, sRGB) and its cliffs' darkest 5 %;
#: a plausible linear albedo of the same chroma for a baked-shade texel.
BAKED_SHADE = (0.045, 0.060, 0.127)
GRANITE_SUNLIT = (0.42, 0.40, 0.38)
FOREST = (0.05, 0.07, 0.03)
WATER = (0.02, 0.04, 0.07)
STEEP_Z = 0.3   # a cliff's face normal |z|
LEVEL_Z = 1.0


def _script_literal(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _b_minus_r(rgb):
    return rgb[..., 2] - rgb[..., 0]


# -- the law ---------------------------------------------------------------------------

def test_amount_zero_is_an_exact_pass_through():
    rng = np.random.default_rng(3)
    albedo = rng.random((16, 16, 3))
    out = sn.shade_neutral(albedo, STEEP_Z, 0.0)
    assert np.array_equal(out, albedo)
    # and the switch off gives amount 0 for every preset
    for preset in wb.PRESETS:
        assert sn.amount_for(preset, "", "off") == 0.0


def test_a_baked_shade_texel_on_a_wall_goes_most_of_the_way_to_grey_at_its_luma():
    a = np.array([BAKED_SHADE])
    out = sn.shade_neutral(a, STEEP_Z, 1.0)
    luma = a @ np.asarray(sn.SHADE_LUMA)
    assert (out @ np.asarray(sn.SHADE_LUMA)) == pytest.approx(luma)   # brightness kept
    # B - R falls by at least two thirds; R / B rises from 0.35 to above 0.75
    assert _b_minus_r(out)[0] < _b_minus_r(a)[0] / 3
    assert out[0, 0] / out[0, 2] > 0.75


def test_lit_warm_green_and_level_water_texels_are_untouched():
    for rgb, z in ((GRANITE_SUNLIT, STEEP_Z), (FOREST, STEEP_Z), (WATER, LEVEL_Z)):
        a = np.array([rgb])
        assert np.allclose(sn.shade_neutral(a, z, 1.0), a), rgb
    # the same water on a wall is shade, not water
    assert sn.shade_weight(np.array([WATER]), STEEP_Z)[0] > 0.5


def test_the_weight_is_absolute_so_a_wall_wholly_in_shade_is_caught_where_the_delight_is_not():
    # A wall whose whole neighbourhood is shade: the de-light's local mean is the
    # texel itself, so it does nothing (#02's right-hand cliff); this law does.
    wall = np.broadcast_to(np.array(BAKED_SHADE), (8, 8, 3)).copy()
    delit = td.delight(wall, wall, td.amount_for("clear"))
    assert np.allclose(delit, wall)
    out = sn.shade_neutral(delit, STEEP_Z, sn.amount_for("clear"))
    assert np.all(_b_minus_r(out) < _b_minus_r(wall) / 3)


def test_amounts_by_preset_surface_and_switch():
    assert sn.amount_for("clear") == 1.0 and sn.amount_for("hazy") == 1.0
    for preset in ("overcast", "rain", "storm"):
        assert sn.amount_for(preset) == 0.0
    assert sn.amount_for("clear", "city") == 0.0
    assert sn.amount_for("nonsense") == 0.0
    assert tuple(sn.SHADE_NEUTRAL_DEFAULTS) == tuple(wb.PRESETS)


@pytest.mark.parametrize("text,value", [
    ("", "on"), (None, "on"), ("-tiles-shade-neutral=off", "off"),
    ("-start-gear=down -tiles-shade-neutral=off", "off"), ("-tiles-shade-neutral=on", "on"),
    ("-tiles-shade-neutral=bogus", "on"), ("-stated-fill-fog=sky", "on"),
])
def test_the_switch_reads_like_the_host(text, value):
    assert sn.parse_switch(text) == value


def test_the_collection_parameter_is_in_both_contracts_and_tiles_parameters():
    assert wb.WORLD_MPC_SCALARS["ShadeNeutralAmount"] == 0.0
    assert _script_literal("WORLD_COLLECTION_SCALARS")["ShadeNeutralAmount"] == 0.0
    assert wb.tiles_parameters("clear", 0.0)["ShadeNeutralAmount"] == 1.0
    assert wb.tiles_parameters("clear", 0.0, surface="city")["ShadeNeutralAmount"] == 0.0
    assert wb.tiles_parameters("clear", 0.0, shade_switch="off")["ShadeNeutralAmount"] == 0.0
    assert wb.tiles_parameters("storm", 0.0)["ShadeNeutralAmount"] == 0.0


# -- the shader and the material -------------------------------------------------------

def test_the_hlsl_constants_and_input_order_are_the_twin():
    def const(name):
        m = re.search(rf"const float {name} = ([0-9.e+-]+);", HLSL)
        assert m, name
        return float(m.group(1))
    luma = re.search(r"const float3 SHADE_LUMA = float3\(([^)]*)\);", HLSL)
    assert luma and tuple(float(x) for x in luma.group(1).split(",")) == sn.SHADE_LUMA
    assert const("SHADE_EPS") == sn.SHADE_EPS
    assert const("SHADE_LUMA_KNEE") == sn.SHADE_LUMA_KNEE
    assert const("SHADE_BLUE_GATE") == sn.SHADE_BLUE_GATE
    assert (const("SHADE_LEVEL_LO"), const("SHADE_LEVEL_HI")) == sn.SHADE_LEVEL_SLOPE
    documented = re.findall(r"^//\s+(\w+)\s+float3?\s", HLSL[HLSL.index("// Inputs"):], re.M)
    assert tuple(documented) == sn.SHADE_INPUTS
    assert _script_literal("WORLD_TILES_INPUTS")["tiles_shade_neutral"] == sn.SHADE_INPUTS
    for line in ("[branch] if (amount <= 0.0)",
                 "return Albedo;",
                 "float violet = saturate((a.b / rg - 1.0) * SHADE_BLUE_GATE);",
                 "float dark = saturate(1.0 - L / SHADE_LUMA_KNEE);",
                 "float slope = 1.0 - saturate(faceUp);",
                 "float water = 1.0 - smoothstep(SHADE_LEVEL_LO, SHADE_LEVEL_HI, slope);",
                 "float w = violet * dark * (1.0 - water) * amount;",
                 "return lerp(a, float3(L, L, L), w);"):
        assert line in HLSL, line
    # the pass-through comes before any arithmetic on the input
    assert HLSL.index("return Albedo;") < HLSL.index("float3 a = max(Albedo, 0.0);")
    # the derivatives come before the branch (no gradient inside flow control)
    assert HLSL.index("ddx_fine(p)") < HLSL.index("[branch]")
    assert "static const" not in HLSL


def test_the_material_runs_it_between_the_delight_and_the_detail_and_restamps():
    create = SCRIPT[SCRIPT.index("def create_world_tiles_beauty"):SCRIPT.index("def terrain_detail_pin")]
    assert re.search(r'common\["Albedo"\] = \(world_custom\(material, lib, "tiles_shade_neutral"', create)
    assert (create.index('"tiles_delight"') < create.index('"tiles_shade_neutral"')
            < create.index("world_tiles_detail(material, lib, common, uv, factor)")
            < create.index("for row, (shader"))
    generations = _script_literal("WORLD_GENERATIONS")
    assert int(generations["M_FlightSimTilesBeauty"]) >= 5 and int(generations["MPC_FlightSimWorld"]) >= 4


# -- the host ---------------------------------------------------------------------------

def test_the_cpp_numbers_and_record_are_the_twin():
    block = CLOUDS_CPP[CLOUDS_CPP.index("namespace FlightSimTilesShade"):
                       CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyTiles(")]
    amounts = re.search(r"ShadeNeutralAmounts\[FlightSimWorldPure::PresetCount\] = \{([^}]*)\};", block)
    assert tuple(float(x) for x in amounts.group(1).split(",")) == tuple(
        sn.SHADE_NEUTRAL_DEFAULTS[p] for p in wb.PRESETS)
    for name, value in (("ShadeLumaKnee", sn.SHADE_LUMA_KNEE), ("ShadeBlueGate", sn.SHADE_BLUE_GATE)):
        found = re.search(rf"constexpr double {name} = ([0-9.]+);", block)
        assert found and float(found.group(1)) == value, name
    assert 'Switch == TEXT("off") || Surface == TEXT("city")' in block
    record = sn.shade_record("clear")
    rec_cpp = block[block.index("TSharedPtr<FJsonObject> ShadeRecord("):]
    assert set(re.findall(r'Out->Set\w+Field\(TEXT\("(\w+)"\)', rec_cpp)) == set(record)
    basis = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', rec_cpp[rec_cpp.index('TEXT("basis")'):
                                                               rec_cpp.index('TEXT("pixel_moving")')])[1:])
    assert basis == sn.BASIS


def test_the_host_reads_the_switch_and_records_it():
    assert 'FString TilesShadeSwitch = TEXT("on");' in CLOUDS_H
    build = CLOUDS_CPP[CLOUDS_CPP.index('TEXT("FLIGHTSIM_RENDER_SWITCHES")'):]
    build = build[:build.index("}")]
    assert 'FParse::Value(*Switches, TEXT("tiles-shade-neutral="), TilesShadeSwitch);' in build
    assert sn.SWITCH_FLAG == "tiles-shade-neutral="
    tiles = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyTiles"):
                       CLOUDS_CPP.index("void FFlightSimWorldBeauty::Advance")]
    assert ('{TEXT("ShadeNeutralAmount"), FlightSimTilesShade::AmountFor(Preset, Surface, TilesShadeSwitch)}'
            in tiles)
    assert 'Out->SetObjectField(TEXT("shade_neutral"),' in tiles


def test_the_probe_is_written_down():
    section = PROBE_LOG[PROBE_LOG.index("## #02 blue: the tiles' baked sky-shade"):]
    assert "-tiles-shade-neutral=off" in section and "world_beauty.tiles.shade_neutral" in section


def test_the_level_test_is_the_face_normal_never_the_vertex_normal():
    """Rounds 58/59: Cesium draws the Google tiles (KHR_materials_unlit) with every
    vertex normal the ellipsoid's up, so a vertex-normal level test called every
    texel open water and the term moved no pixel (the A/B pixel-identical)."""
    code = HLSL[HLSL.index("float3 p = WorldPos / 100.0;"):]
    assert "NormalWS" not in code and "NormalWS" not in sn.SHADE_INPUTS
    assert "float3 face = cross(ddx_fine(p), ddy_fine(p));" in code
    assert "float faceUp = abs(face.z) / max(length(face), 1e-8);" in code
    # what the old test did with Cesium's up normals: no weight anywhere
    assert sn.shade_weight(np.array([BAKED_SHADE]), 1.0)[0] == 0.0
    # a wall's face normal lets the baked shade through; the sign of the cross is free
    assert sn.shade_weight(np.array([BAKED_SHADE]), -STEEP_Z)[0] == sn.shade_weight(np.array([BAKED_SHADE]), STEEP_Z)[0] > 0.7
    assert sn.shade_record("clear")["level_basis"] == sn.LEVEL_BASIS


def test_a_numeric_switch_is_the_amount():
    assert sn.parse_switch("-tiles-shade-neutral=0.5") == "0.5"
    assert sn.amount_for("clear", "", "0.5") == 0.5
    assert sn.amount_for("overcast", "", "0.6") == 0.6
    assert sn.amount_for("clear", "", "3") == 1.0
    assert sn.amount_for("clear", "city", "0.5") == 0.0
    assert sn.shade_record("clear", "", "0.5")["switch"] == "0.5"
