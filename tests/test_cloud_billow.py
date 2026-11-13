"""Round 82 (the owner, 2026-11-13: "the clouds dont look that realistic"):
the cumulus billow. ``-look-cloud-billow=on|off`` (on by default) sharpens a
cumulus layer's edge, makes its billows finer, thins its base under a dense
body (the material's HeightDensity) and occludes the sky light harder at its
base; off is round 81's clouds exactly. BEAUTY ONLY: the measure path never
puts M_FlightSimCloudLayers on a cloud. These tests pin the C++, the shader,
the material script and core/scene/world_beauty.py to one another."""
import re
from pathlib import Path

import pytest

from core.scene import world_beauty as wb

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp"
HEADER = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimClouds.h"
HLSL = ROOT / "assets/shaders/world/cloud_layers.hlsl"
MATERIALS = ROOT / "scripts/ue_create_materials.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cpp_constant(name: str) -> float:
    m = re.search(r"constexpr double " + name + r" = ([0-9.]+);", _read(CPP))
    assert m, name
    return float(m.group(1))


@pytest.mark.parametrize("cpp, py", [
    ("CloudBillowContrastGain", "CLOUD_BILLOW_CONTRAST_GAIN"),
    ("CloudBillowDetailScaleKm", "CLOUD_BILLOW_DETAIL_SCALE_KM"),
    ("CloudBillowErosion", "CLOUD_BILLOW_EROSION"),
    ("CloudBillowHeightDensity", "CLOUD_BILLOW_HEIGHT_DENSITY"),
    ("CloudBillowBottomOcclusion", "CLOUD_BILLOW_BOTTOM_OCCLUSION"),
])
def test_the_cpp_constants_match_python(cpp, py):
    assert _cpp_constant(cpp) == getattr(wb, py)


def test_the_shader_rise_matches_python():
    m = re.search(r"const float HEIGHT_DENSITY_RISE = ([0-9.]+);", _read(HLSL))
    assert m and float(m.group(1)) == wb.CLOUD_HEIGHT_DENSITY_RISE


def test_only_cumulus_with_the_switch_on():
    assert wb.cloud_billow_applies(True, "cumulus")
    for shape in ("stratocumulus", "overcast", "nimbostratus"):
        assert not wb.cloud_billow_applies(True, shape)
    assert not wb.cloud_billow_applies(False, "cumulus")


def test_the_row_off_is_round_81_and_on_replaces_three_fields():
    row = wb.CLOUDS["cumulus"]
    assert wb.cloud_billow_row(row, False) == row
    on = wb.cloud_billow_row(row, True)
    assert on["coverage_contrast"] == pytest.approx(row["coverage_contrast"] * wb.CLOUD_BILLOW_CONTRAST_GAIN)
    assert on["detail_scale_km"] == wb.CLOUD_BILLOW_DETAIL_SCALE_KM
    assert on["detail_erosion"] == wb.CLOUD_BILLOW_EROSION
    changed = {k for k in row if on[k] != row[k]}
    assert changed == {"coverage_contrast", "detail_scale_km", "detail_erosion"}


def test_the_height_density_is_one_when_off_and_rises_when_on():
    for h in (0.0, 0.1, 0.35, 0.7, 1.0):
        assert wb.cloud_height_density(0.0, h) == 1.0
    amount = wb.cloud_height_density_for(True)
    assert wb.cloud_height_density_for(False) == 0.0
    assert wb.cloud_height_density(amount, 0.0) == pytest.approx(1.0 - amount)
    assert wb.cloud_height_density(amount, wb.CLOUD_HEIGHT_DENSITY_RISE) == pytest.approx(1.0)
    values = [wb.cloud_height_density(amount, h / 10.0) for h in range(11)]
    assert values == sorted(values)


def test_the_bottom_occlusion_only_rises():
    assert wb.cloud_bottom_occlusion_for(True, 0.5) == wb.CLOUD_BILLOW_BOTTOM_OCCLUSION
    assert wb.cloud_bottom_occlusion_for(True, 0.9) == 0.9
    assert wb.cloud_bottom_occlusion_for(False, 0.5) == 0.5


def test_the_density_replica_keeps_round_81_at_zero():
    row = wb.CLOUDS["cumulus"]
    for km in ((0.3, 1.7, 0.2), (4.1, -2.2, 0.6), (10.0, 3.3, 0.9)):
        for h in (0.05, 0.3, 0.8):
            assert wb.cloud_density(km, h, 0.5, row) == wb.cloud_density(km, h, 0.5, row, height_density=0.0)


def test_the_shader_multiplies_the_body_into_the_extinction():
    text = _read(HLSL)
    assert "float body = lerp(1.0 - saturate(HeightDensity), 1.0, smoothstep(0.0, HEIGHT_DENSITY_RISE, h));" in text
    assert "return density * base * body * ExtinctionPerM * ExtinctionScale * fadeOut;" in text


def test_the_material_gains_the_input_and_a_new_generation():
    text = _read(MATERIALS)
    assert '"HeightDensity": 0.0,' in text
    start = text.index("WORLD_CLOUD_INPUTS = (")
    assert '"HeightDensity")   # round 82' in text[start:text.index("WORLD_CLOUD_ALBEDO", start)]
    assert 'WORLD_GRAPH_GENERATIONS = {"M_FlightSimCloudLayers": "7"' in text
    assert '"M_FlightSimCloudLayers": "8"' in text


def test_the_bridge_reads_refuses_and_records_the_switch():
    text = _read(CPP)
    assert 'FParse::Value(*Switches, TEXT("look-cloud-billow="), CloudBillowSwitch);' in text
    assert "world_beauty.clouds: -look-cloud-billow=%s is not on or off" in text
    assert wb.CLOUD_BILLOW_SWITCH == "-look-cloud-billow"
    assert 'SetScalarParameterValue(TEXT("HeightDensity")' in text
    assert "CloudBottomOcclusionFor(bBillow, AtmRow[AtmCloudBottomOcclusion])" in text
    for field in ("cloud_billow", "cloud_billow_applied", "height_density", "sky_light_cloud_bottom_occlusion"):
        assert 'TEXT("' + field + '")' in text
    assert 'FString CloudBillowSwitch = TEXT("on");' in _read(HEADER)


def test_the_distant_sheet_softens_at_grazing_views_under_the_switch():
    text = (ROOT / "assets/shaders/world/distant_clouds.hlsl").read_text(encoding="utf-8")
    for name, value in (("GRAZE_LO", wb.DISTANT_GRAZE_LO), ("GRAZE_HI", wb.DISTANT_GRAZE_HI),
                        ("GRAZE_SOFTEN", wb.DISTANT_GRAZE_SOFTEN)):
        assert f"const float {name} = {value};" in text
    assert "soft *= 1.0 + GRAZE_SOFTEN * graze;" in text
    assert "slope *= 1.0 - graze;" in text
    materials = _read(MATERIALS)
    assert '"GrazingSoften": 0.0,' in materials
    assert '"M_FlightSimDistantClouds": "5"' in materials
    cpp = _read(CPP)
    assert 'const float GrazingSoften = CloudBillowSwitch == TEXT("on") ? 1.0f : 0.0f;' in cpp
    assert 'Material->SetScalarParameterValue(TEXT("GrazingSoften"), GrazingSoften);' in cpp


def test_the_scud_is_grey_not_a_hole():
    from core.scene import rain_veil
    weather = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimWeather.cpp").read_text(
        encoding="utf-8")
    assert rain_veil.SCUD_TONE_UNDER_DECK == 0.75 and rain_veil.SCUD_TONE_OPEN == 0.85
    assert "constexpr double ScudToneUnderDeck = 0.75;" in weather
    assert "constexpr double ScudToneOpen = 0.85;" in weather
