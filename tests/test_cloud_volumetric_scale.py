"""Impostor A/B (0deddc6d's cloud cards, 2026-11-14): ``-cloud-volumetric-scale=<0..1>``
(1 by default) thins every volumetric layer's drawn cover and, at 0, hides the
layer, so a frame can carry p3-mac's impostor cards without doubled clouds.
BEAUTY ONLY: the code lives in ApplyClouds, which only -quality=beauty reaches.
These tests pin the C++ parse string, the refusal message, the render.json field
names and the header default to core/scene/world_beauty.py, the way
tests/test_cloud_billow.py does."""
import re
from pathlib import Path

import pytest

from core.scene import world_beauty as wb

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp"
HEADER = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimClouds.h"
PLAN = ROOT / "docs/VISUAL_FIDELITY_PLAN.md"

SWITCH = "-cloud-volumetric-scale"
REFUSAL = "world_beauty.clouds: -cloud-volumetric-scale=%s is not a number in 0..1"
FIELDS = ("volumetric_scale", "volumetric_scale_applied", "cover_before_volumetric_scale", "volumetric_hidden")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_switch_name_and_default_match_the_bridge():
    assert wb.CLOUD_VOLUMETRIC_SCALE_SWITCH == SWITCH
    assert wb.CLOUD_VOLUMETRIC_SCALE_DEFAULT == 1.0
    cpp = _read(CPP)
    m = re.search(r"constexpr double CloudVolumetricScaleDefault = ([0-9.]+);", cpp)
    assert m and float(m.group(1)) == wb.CLOUD_VOLUMETRIC_SCALE_DEFAULT
    m = re.search(r"double CloudVolumetricScale = ([0-9.]+);", _read(HEADER))
    assert m and float(m.group(1)) == wb.CLOUD_VOLUMETRIC_SCALE_DEFAULT
    assert "FString CloudVolumetricScaleText;" in _read(HEADER)


def test_the_bridge_reads_the_switch_the_way_the_billow_is_read():
    cpp = _read(CPP)
    assert 'FParse::Value(*Switches, TEXT("cloud-volumetric-scale="), CloudVolumetricScaleText);' in cpp
    assert 'FParse::Value(*Switches, TEXT("look-cloud-billow="), CloudBillowSwitch);' in cpp
    # Read from the same Switches string (command line + FLIGHTSIM_RENDER_SWITCHES),
    # inside the same block, right after the billow switch.
    billow = cpp.index('TEXT("look-cloud-billow="), CloudBillowSwitch);')
    scale = cpp.index('TEXT("cloud-volumetric-scale="), CloudVolumetricScaleText);')
    assert billow < scale < billow + 800
    assert "CloudVolumetricScale = CloudVolumetricScaleDefault;" in cpp


def test_the_bridge_refuses_by_name_a_non_number_or_out_of_range():
    cpp = _read(CPP)
    assert REFUSAL in cpp
    assert "FCString::IsNumeric(*CloudVolumetricScaleText)" in cpp
    assert "!(Scale >= 0.0 && Scale <= 1.0)" in cpp
    # The refusal is in the same style as the billow's.
    assert "world_beauty.clouds: -look-cloud-billow=%s is not on or off" in cpp


def test_the_cover_is_scaled_before_every_later_row_and_zero_hides_the_component():
    cpp = _read(CPP)
    assert "State.Cover = CloudVolumetricCoverage(CoverBeforeScale, CloudVolumetricScale);" in cpp
    assert "const bool bVolumetricHidden = CloudVolumetricHidden(CloudVolumetricScale);" in cpp
    scaled = cpp.index("State.Cover = CloudVolumetricCoverage(")
    coverage = cpp.index('SetScalarParameterValue(TEXT("Coverage"), static_cast<float>(State.Cover));')
    assert scaled < coverage
    hide = cpp.index("if (bVolumetricHidden)")
    assert coverage < hide
    assert "Cloud->SetVisibility(false);" in cpp[hide:hide + 120]
    # The pure helpers: the twin of cloud_volumetric_coverage.
    # Plain C++ (no FMath): test_world_beauty compiles the pure block with g++.
    assert "return Cover * (Scale < 0.0 ? 0.0 : (Scale > 1.0 ? 1.0 : Scale));" in cpp
    assert "return Scale <= 0.0;" in cpp


def test_the_record_names_match_the_python():
    cpp = _read(CPP)
    for field in FIELDS:
        assert 'TEXT("' + field + '")' in cpp
    assert 'SetNumberField(TEXT("volumetric_scale"), CloudVolumetricScale);' in cpp
    assert ('SetBoolField(TEXT("volumetric_scale_applied"), CloudVolumetricScaleApplied(CloudVolumetricScale));'
            in cpp)
    assert "return Scale < CloudVolumetricScaleDefault;" in cpp
    doc = wb.__doc__ or ""
    source = (ROOT / "core/scene/world_beauty.py").read_text(encoding="utf-8")
    for field in FIELDS:
        assert field in source or field in doc


def test_the_python_twin_scales_and_refuses():
    assert wb.cloud_volumetric_coverage(0.6, 1.0) == 0.6
    assert wb.cloud_volumetric_coverage(0.6, wb.CLOUD_VOLUMETRIC_SCALE_DEFAULT) == 0.6
    assert wb.cloud_volumetric_coverage(0.6, 0.5) == pytest.approx(0.3)
    assert wb.cloud_volumetric_coverage(0.6, 0.0) == 0.0
    assert wb.cloud_volumetric_coverage(0.0, 0.3) == 0.0
    for bad in (-0.1, 1.5, float("nan"), "0.5", None, True):
        with pytest.raises(ValueError, match=re.escape(SWITCH)):
            wb.cloud_volumetric_coverage(0.6, bad)
    with pytest.raises(ValueError):
        wb.cloud_volumetric_coverage(1.2, 0.5)


def test_only_zero_hides():
    assert wb.cloud_volumetric_hidden(0.0)
    for scale in (0.01, 0.5, 1.0):
        assert not wb.cloud_volumetric_hidden(scale)


def test_the_plan_names_the_switch_the_ab_and_the_windows_command():
    text = _read(PLAN)
    start = text.index("-cloud-volumetric-scale")
    section = text[start:start + 3000]
    assert "0deddc6d" in section
    assert "UNMEASURED" in section
    assert '-Switches "-cloud-volumetric-scale=0"' in section
    assert "visual_fix_round.ps1" in section
