"""Round 147 (#06's quilted bay): open water on the tiles to one mean across tile edges.

core/scene/tiles_water_unify.py is the Python twin of
assets/shaders/world/tiles_water_unify.hlsl (M_FlightSimTilesBeauty, beauty only) and of
FlightSimClouds.cpp FlightSimTilesWater (the per-preset WaterUnifyAmount and the
-tiles-water-unify= switch). These pin the three to each other and the law's behaviour.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np

from core.scene import tiles_water_unify as wu
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
HLSL = (REPO / "assets" / "shaders" / "world" / "tiles_water_unify.hlsl").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CLOUDS_CPP = (BRIDGE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (BRIDGE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")

# Two neighbouring water tiles as r146 drew them: the same bay, means ~10 levels apart.
TILE_A_MEAN = (0.012, 0.030, 0.060)
TILE_B_MEAN = (0.020, 0.042, 0.072)
LAND_MEAN = (0.10, 0.09, 0.07)   # warm, bright: never water
LEVEL_Z, SLOPE_Z = 1.0, 0.9


def _script_literal(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _hlsl_const(name):
    m = re.search(rf"const float3? {name} = (?:float3\()?([^;]*?)\)?;", HLSL)
    assert m, name
    vals = [float(v) for v in m.group(1).split(",")]
    return vals[0] if len(vals) == 1 else tuple(vals)


def test_hlsl_constants_are_the_python_twin():
    assert _hlsl_const("WATER_LUMA") == wu.WATER_LUMA
    assert _hlsl_const("WATER_EPS") == wu.WATER_EPS
    assert _hlsl_const("WATER_MEAN") == wu.WATER_MEAN
    assert (_hlsl_const("WATER_LEVEL_LO"), _hlsl_const("WATER_LEVEL_HI")) == wu.WATER_LEVEL
    assert (_hlsl_const("WATER_DARK_LO"), _hlsl_const("WATER_DARK_HI")) == wu.WATER_DARK
    assert _hlsl_const("WATER_BR_MIN") == wu.WATER_BR_MIN and _hlsl_const("WATER_BR_GAIN") == wu.WATER_BR_GAIN
    assert _hlsl_const("WATER_BG_MIN") == wu.WATER_BG_MIN and _hlsl_const("WATER_BG_GAIN") == wu.WATER_BG_GAIN
    assert _hlsl_const("WATER_FLAT_KEEP") == wu.WATER_FLAT_KEEP and _hlsl_const("WATER_FLAT_SPAN") == wu.WATER_FLAT_SPAN
    assert (_hlsl_const("WATER_RATIO_LO"), _hlsl_const("WATER_RATIO_HI")) == wu.WATER_RATIO
    for pin in wu.WATER_INPUTS:
        assert re.search(rf"//\s+{pin}\s", HLSL), pin
    # derivatives before the branch; amount 0 is the exact pass-through
    assert HLSL.index("ddx_fine(p)") < HLSL.index("[branch] if (amount <= 0.0)")
    assert "return Albedo;" in HLSL


def test_the_material_runs_it_after_the_shade_neutraliser():
    assert _script_literal("WORLD_TILES_INPUTS")["tiles_water_unify"] == wu.WATER_INPUTS
    assert _script_literal("WORLD_COLLECTION_SCALARS")["WaterUnifyAmount"] == 0.0
    assert wb.WORLD_MPC_SCALARS["WaterUnifyAmount"] == 0.0
    create = SCRIPT[SCRIPT.index("def create_world_tiles_beauty"):]
    assert create.index('"tiles_shade_neutral",') < create.index('"tiles_water_unify",') \
        < create.index("world_tiles_detail(material, lib, common, uv, factor)")
    gens = _script_literal("WORLD_GENERATIONS")
    assert int(gens["M_FlightSimTilesBeauty"]) >= 13 and int(gens["MPC_FlightSimWorld"]) >= 5


def test_the_cpp_amounts_and_switch_are_the_python_twin():
    m = re.search(r"WaterUnifyAmounts\[FlightSimWorldPure::PresetCount\] = \{([^}]*)\};", CLOUDS_CPP)
    assert [float(v) for v in m.group(1).split(",")] == [wu.WATER_UNIFY_DEFAULTS[p] for p in wb.PRESETS]
    assert '{TEXT("WaterUnifyAmount"), FlightSimTilesWater::AmountFor(Preset, TilesWaterSwitch)}' in CLOUDS_CPP
    assert 'FParse::Value(*Switches, TEXT("tiles-water-unify="), TilesWaterSwitch);' in CLOUDS_CPP
    assert 'FString TilesWaterSwitch = TEXT("on");' in CLOUDS_H
    assert 'Out->SetObjectField(TEXT("water_unify"), FlightSimTilesWater::WaterRecord(Preset, TilesWaterSwitch));' \
        in CLOUDS_CPP


def test_amounts_and_switch():
    assert wu.amount_for("rain") == 1.0 and wu.amount_for("storm") == 1.0 and wu.amount_for("overcast") == 1.0
    assert wu.amount_for("clear") == 0.0 and wu.amount_for("hazy") == 0.0
    assert wu.amount_for("rain", "off") == 0.0 and wu.amount_for("clear", "0.5") == 0.5
    assert wu.amount_for("rain", "7") == 1.0
    assert wu.parse_switch("-tiles-water-unify=off -x") == "off"
    assert wu.parse_switch("-tiles-water-unify=0.25") == "0.25"
    assert wu.parse_switch("") == "on" and wu.parse_switch("-tiles-water-unify=bogus") == "on"
    assert wb.tiles_parameters("rain", 1.0)["WaterUnifyAmount"] == 1.0
    assert wb.tiles_parameters("rain", 1.0, water_switch="off")["WaterUnifyAmount"] == 0.0
    assert wb.tiles_parameters("clear", 0.0)["WaterUnifyAmount"] == 0.0
    rec = wu.water_record("rain", "off")
    assert rec["amount"] == 0.0 and rec["switch"] == "off" and rec["pixel_moving"] is False


def test_two_water_tiles_meet_without_a_step():
    """r146's seam: two tiles' water, the same texel detail (ratio 1.1) on means ~10 levels
    apart, come out the same colour; before, they differed by the means' gap."""
    detail = 1.1
    a = np.array(TILE_A_MEAN) * detail
    b = np.array(TILE_B_MEAN) * detail
    out_a = wu.water_unify(a, TILE_A_MEAN, LEVEL_Z)
    out_b = wu.water_unify(b, TILE_B_MEAN, LEVEL_Z)
    assert wu.water_weight(a, TILE_A_MEAN, LEVEL_Z) > 0.99 and wu.water_weight(b, TILE_B_MEAN, LEVEL_Z) > 0.99
    assert np.max(np.abs(out_a - out_b)) < 1e-3
    assert np.max(np.abs(b - a)) > 0.01
    np.testing.assert_allclose(out_a, np.array(wu.WATER_MEAN) * detail, atol=1e-3)


def test_texture_detail_survives_as_its_ratio():
    lo = wu.water_unify(np.array(TILE_A_MEAN) * 0.95, TILE_A_MEAN, LEVEL_Z)
    hi = wu.water_unify(np.array(TILE_A_MEAN) * 1.10, TILE_A_MEAN, LEVEL_Z)
    assert np.all(hi > lo)


def test_land_slopes_and_amount_zero_are_untouched():
    land = np.array(LAND_MEAN)
    np.testing.assert_array_equal(wu.water_unify(land, LAND_MEAN, LEVEL_Z), land)
    water = np.array(TILE_A_MEAN)
    np.testing.assert_array_equal(wu.water_unify(water, TILE_A_MEAN, SLOPE_Z), water)
    np.testing.assert_array_equal(wu.water_unify(water, TILE_A_MEAN, LEVEL_Z, 0.0), water)
    # a dark green field (G over B) is never water
    field = np.array((0.03, 0.06, 0.03))
    np.testing.assert_array_equal(wu.water_unify(field, field, LEVEL_Z), field)
    # a high-contrast texel (a boat, a pier) against the water mean keeps its colour
    pier = np.array(TILE_A_MEAN) * 2.0
    np.testing.assert_array_equal(wu.water_unify(pier, TILE_A_MEAN, LEVEL_Z), pier)
