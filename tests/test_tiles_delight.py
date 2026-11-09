"""tiles-delight: the shader's Python twin, and the material, the HLSL and the C++ agree.

core/scene/tiles_delight.py is the law; assets/shaders/world/tiles_delight.hlsl
runs it per frame in M_FlightSimTilesBeauty; FlightSimClouds.cpp sets its two
collection scalars and writes world_beauty.tiles.delight. Nothing here renders:
this Mac cannot (the probe is docs/visual/PROBE_LOG.md ## tiles-delight).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pytest

from core.capture import beauty_look as capture_look
from core.scene import tiles_delight as td
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
HLSL = (REPO / "assets" / "shaders" / "world" / "tiles_delight.hlsl").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
CLOUDS_CPP = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
              / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
MODULE = (REPO / "core" / "scene" / "tiles_delight.py").read_text(encoding="utf-8")

WARM = (0.45, 0.35, 0.25)
BLUE_SHADOW = (0.10, 0.11, 0.16)
ASPHALT = (0.10, 0.10, 0.10)


def _script_literal(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _patch(square_rgb, size=16, square=4):
    """A warm field with a dark square in the middle, and its local mean (a
    low mip covering the whole patch: every pixel's coarse sample is the mean)."""
    img = np.empty((size, size, 3))
    img[...] = WARM
    lo = (size - square) // 2
    img[lo:lo + square, lo:lo + square] = square_rgb
    low = np.broadcast_to(img.reshape(-1, 3).mean(axis=0), img.shape).copy()
    return img, low, (slice(lo, lo + square), slice(lo, lo + square))


def _luma(rgb):
    return np.asarray(rgb) @ np.asarray(td.DELIGHT_LUMA)


# -- the law ---------------------------------------------------------------------------

def test_amount_zero_is_an_exact_pass_through():
    rng = np.random.default_rng(7)
    albedo = rng.random((32, 32, 3))
    low = rng.random((32, 32, 3))
    out = td.delight(albedo, low, 0.0)
    assert np.array_equal(out, albedo)
    img, low, _ = _patch(BLUE_SHADOW)
    assert np.array_equal(td.delight(img, low, 0.0), img)


def test_a_dark_blue_square_is_lifted_toward_the_field_mean_and_loses_its_blue():
    img, low, sq = _patch(BLUE_SHADOW)
    out = td.delight(img, low, 1.0)
    before, after, mean = img[sq], out[sq], low[sq]
    assert np.all(_luma(after) > _luma(before) + 0.05)
    assert np.all(_luma(after) <= _luma(mean) + 1e-12)
    ratio_before = before[..., 2] / before[..., 0]
    ratio_after = after[..., 2] / after[..., 0]
    assert np.all(ratio_after < ratio_before - 0.2)
    # the warm field (brighter than the knee) is untouched
    field = np.ones(img.shape[:2], bool)
    field[sq] = False
    assert np.array_equal(out[field], img[field])
    # more amount, more lift
    half = td.delight(img, low, 0.5)
    assert np.all(_luma(before) < _luma(half[sq])) and np.all(_luma(half[sq]) < _luma(after))


def test_dark_neutral_asphalt_is_lifted_far_less_than_a_blue_shadow():
    blue_img, blue_low, sq = _patch(BLUE_SHADOW)
    grey_img, grey_low, _ = _patch(ASPHALT)
    blue_lift = _luma(td.delight(blue_img, blue_low, 1.0)[sq]) - _luma(blue_img[sq])
    grey_lift = _luma(td.delight(grey_img, grey_low, 1.0)[sq]) - _luma(grey_img[sq])
    assert np.all(grey_lift <= 0.1 * blue_lift)
    assert td.shadow_weight(grey_img, grey_low)[sq].max() == 0.0
    assert td.shadow_weight(blue_img, blue_low)[sq].min() > 0.3


def test_the_output_never_exceeds_the_low_mip_where_it_lifts():
    rng = np.random.default_rng(11)
    albedo = rng.random((64, 64, 3)) * np.array([0.5, 0.6, 1.0])   # many blue-shifted pixels
    low = np.clip(albedo + rng.random((64, 64, 3)) * 0.5, 0.0, 1.0)
    for amount in (0.2, 0.5, 1.0):
        out = td.delight(albedo, low, amount)
        assert np.all(out >= 0.0) and np.all(out <= 1.0)
        assert np.all(out <= np.maximum(albedo, low) + 1e-12)
        lifted = td.shadow_weight(albedo, low) > 0.0
        assert lifted.any()
        assert np.all(out[lifted] <= low[lifted] + 1e-12)
        assert np.all(_luma(out[lifted]) >= _luma(albedo[lifted]) - 1e-12)


def test_bad_inputs_refuse_by_name():
    with pytest.raises(td.TilesDelightError) as err:
        td.delight(np.zeros((4, 3)), np.zeros((5, 3)), 0.5)
    assert err.value.constraint == "world_beauty.tiles_delight"
    with pytest.raises(td.TilesDelightError):
        td.delight(np.zeros((4, 4)), np.zeros((4, 4)), 0.5)
    with pytest.raises(td.TilesDelightError):
        td.delight(np.zeros((4, 3)), np.zeros((4, 3)), float("nan"))
    with pytest.raises(td.TilesDelightError):
        td.delight(np.zeros((4, 3)), np.zeros((4, 3)), 0.5, ratio_knee=0.0)


def test_the_presets_are_the_world_presets_and_diffuse_light_keeps_more_occlusion():
    assert set(td.DELIGHT_DEFAULTS) == set(wb.PRESETS)
    for preset in ("overcast", "rain", "storm"):
        assert td.DELIGHT_DEFAULTS[preset] < td.DELIGHT_DEFAULTS["clear"]
    assert all(0.0 <= v <= 1.0 for v in td.DELIGHT_DEFAULTS.values())
    for preset in wb.PRESETS:
        params = wb.tiles_parameters(preset, 0.0)
        assert params["DelightAmount"] == td.DELIGHT_DEFAULTS[preset]
        assert params["DelightBlueGate"] == td.DELIGHT_BLUE_GATE


# -- the shader and the material ----------------------------------------------------------

def test_the_hlsl_constants_and_input_order_are_the_twin():
    luma = re.search(r"const float3 DELIGHT_LUMA = float3\(([^)]*)\);", HLSL)
    assert luma and tuple(float(x) for x in luma.group(1).split(",")) == td.DELIGHT_LUMA
    eps = re.search(r"const float DELIGHT_EPS = ([0-9.e+-]+);", HLSL)
    assert eps and float(eps.group(1)) == td.DELIGHT_EPS
    documented = re.findall(r"^//\s+(\w+)\s+float3?\s", HLSL[HLSL.index("// Inputs"):], re.M)
    assert tuple(documented) == td.DELIGHT_INPUTS
    assert _script_literal("WORLD_TILES_INPUTS")["tiles_delight"] == td.DELIGHT_INPUTS
    # the law's shape, written once in the shader
    for line in ("float ratio = L / max(Lm, DELIGHT_EPS);",
                 "float darker = saturate((knee - ratio) / knee);",
                 "float bluer = saturate((a.b / max(a.r, DELIGHT_EPS) - 1.0) * DelightBlueGate);",
                 "float w = darker * bluer * saturate(DelightAmount);",
                 "return min(saturate(c), max(a, m));"):
        assert line in HLSL, line
    assert "static const" not in HLSL


def test_the_material_samples_the_same_texture_at_the_mip_bias_and_feeds_the_grade():
    assert _script_literal("WORLD_TILES_DELIGHT_SCALARS") == {
        "DelightMipBias": td.DELIGHT_MIP_BIAS, "DelightRatioKnee": td.DELIGHT_RATIO_KNEE}
    create = SCRIPT[SCRIPT.index("def create_world_tiles_beauty"):SCRIPT.index("# == END WORLD LANE")]
    assert create.count("texture_parameter(material, lib, CESIUM_BASE_COLOUR_TEXTURE") == 2
    assert "TMVM_MIP_BIAS" in create and '"MipBias")' in create
    assert re.search(r'common\["Albedo"\] = \(world_custom\(material, lib, "tiles_delight"', create)
    # it runs before the nodes that read Albedo
    assert create.index('"tiles_delight"') < create.index("for row, (shader")


def test_the_two_collection_scalars_are_in_the_contract_and_the_cpp():
    for name, default in (("DelightAmount", 0.0), ("DelightBlueGate", td.DELIGHT_BLUE_GATE)):
        assert wb.WORLD_MPC_SCALARS[name] == default
        assert _script_literal("WORLD_COLLECTION_SCALARS")[name] == default
    scalars = CLOUDS_CPP[CLOUDS_CPP.index("const FWorldScalar Scalars[] = {"):]
    scalars = scalars[:scalars.index("};")]
    assert '{TEXT("DelightAmount"), FlightSimTilesDelight::AmountFor(Preset)}' in scalars
    assert '{TEXT("DelightBlueGate"), FlightSimTilesDelight::DelightBlueGate}' in scalars


def test_the_cpp_numbers_are_the_twin():
    block = CLOUDS_CPP[CLOUDS_CPP.index("namespace FlightSimTilesDelight"):
                       CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyAtmosphere(")]
    amounts = re.search(r"DelightAmounts\[FlightSimWorldPure::PresetCount\] = \{([^}]*)\};", block)
    assert tuple(float(x) for x in amounts.group(1).split(",")) == tuple(
        td.DELIGHT_DEFAULTS[p] for p in wb.PRESETS)
    for name, value in (("DelightMipBias", td.DELIGHT_MIP_BIAS), ("DelightRatioKnee", td.DELIGHT_RATIO_KNEE),
                        ("DelightBlueGate", td.DELIGHT_BLUE_GATE)):
        found = re.search(rf"constexpr double {name} = ([0-9.]+);", block)
        assert found and float(found.group(1)) == value, name
    found = re.search(r"constexpr float ContactShadowLength = ([0-9.]+)f;", block)
    assert found and float(found.group(1)) == td.CONTACT_SHADOW_LENGTH
    cvars = re.findall(r'TEXT\("(r\.Lumen\.[A-Za-z.]+)"\)', block)
    assert cvars == list(td.CONTACT_CVARS) and set(td.CONTACT_CVARS.values()) == {1}
    assert "Variable->Set(1, ECVF_SetByCode);" in block
    # the record's keys and fixed words are the Python record's
    record = td.delight_record("clear")
    for key in record:
        assert f'TEXT("{key}")' in block, key
    # and the C++ record writes no key the twin lacks (both directions)
    rec_cpp = block[block.index("TSharedPtr<FJsonObject> DelightRecord("):block.index("TSharedPtr<FJsonObject> ApplyContactShading(")]
    assert set(re.findall(r'Out->Set\w+Field\(TEXT\("(\w+)"\)', rec_cpp)) == set(record)
    assert f'TEXT("{td.CONTACT_SHADING_RECORD}")' in rec_cpp
    assert f'TEXT("{td.BASIS}")' in block and 'TEXT("UNCALIBRATED")' in block
    assert 'SetBoolField(TEXT("pixel_moving"), false)' in block
    # the hooks: once each, in the beauty world look only
    assert CLOUDS_CPP.count("FlightSimTilesDelight::DelightRecord(Preset)") == 1
    assert CLOUDS_CPP.count("FlightSimTilesDelight::ApplyContactShading(SunLight)") == 1
    tiles = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyTiles"):
                       CLOUDS_CPP.index("void FFlightSimWorldBeauty::Advance")]
    assert 'SetObjectField(TEXT("delight")' in tiles


def test_the_record_is_colour_only_and_not_pixel_moving():
    record = td.delight_record("storm")
    assert record == {"amount": 0.2, "mip_bias": td.DELIGHT_MIP_BIAS, "ratio_knee": td.DELIGHT_RATIO_KNEE,
                      "blue_gate": td.DELIGHT_BLUE_GATE, "preset": "storm", "basis": td.BASIS,
                      "pixel_moving": False, "calibration": "UNCALIBRATED",
                      "contact_shading": "world_beauty.atmosphere.contact_shading"}
    assert "delight" not in capture_look.PIXEL_MOVING_KEYS
    assert not any("delight" in k or "contact" in k for k in capture_look.PIXEL_MOVING_KEYS)
    # colour only: no world-position offset, no depth
    assert "WorldPositionOffset" not in HLSL and "Depth" not in HLSL


def test_nothing_derived_from_the_tiles_is_stored():
    # Google Map Tiles policy: the law exists for tests and the probe; it writes nothing.
    tree = ast.parse(MODULE)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    imported = {a.name.split(".")[0] for n in imports for a in n.names}
    imported |= {n.module for n in imports if isinstance(n, ast.ImportFrom) and n.module}
    for word in ("open", "write_text", "write_bytes", "save", "savez", "imwrite", "tofile", "Path"):
        assert word not in names, word
    assert imported <= {"__future__", "annotations", "typing", "Any", "Dict", "Tuple", "numpy"}, imported
    assert "Tiles.IsEnabled()" in CLOUDS_CPP   # ApplyTiles still declines only when the tiles are not drawn
    block = CLOUDS_CPP[CLOUDS_CPP.index("namespace FlightSimTilesDelight"):
                       CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyAtmosphere(")]
    assert "SetActorHiddenInGame" not in block and "GoogleTiles" not in block


def test_the_bridge_check_lists_the_delight_symbols():
    block = CHECK[CHECK.index("# -- tiles-delight"):CHECK.index("# -- tiles-delight -- end")]
    for symbol in ("ContactShadowLength;", "ContactShadowLengthInWS", "MarkRenderStateDirty",
                   "r.Lumen.ScreenProbeGather.ShortRangeAO\"", "ShortRangeAO.HorizonSearch",
                   "FindConsoleVariable", "TMVM_MipBias", 'IF_INPUT_RETURN(TEXT("MipBias"));'):
        assert symbol in block, symbol
