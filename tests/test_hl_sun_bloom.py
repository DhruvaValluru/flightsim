"""hl-sun: -bloom-mode=sun|full (core/scene/beauty_look.py bloom_for)."""
import math
import re
from pathlib import Path

import pytest

from core.scene import beauty_look as bl

CPP = Path(__file__).resolve().parents[1] / (
    "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimBeautyLook.cpp")


def _post_exposure_luminance(cd_m2: float, ev100: float) -> float:
    # Reflected-light meter constant K = 12.5: mid grey (0.18) at L = 2^EV x K / 100.
    return 0.18 * cd_m2 / (2.0 ** ev100 * 12.5 / 100.0)


@pytest.mark.parametrize("preset", bl.ENGINE_LOOK_PRESETS)
def test_default_bloom_is_sun_only(preset):
    v = bl.engine_look_for(preset)["bloom"]["values"]
    assert v["bloom_mode"] == "sun"
    assert v["BloomThreshold"] == bl.BLOOM_SUN_THRESHOLD == 8.0
    assert v["BloomThresholdFull"] == -1.0
    # Intensity and size per preset unchanged (the haze-scaled halo).
    assert v["BloomIntensity"] == bl.ENGINE_LOOK["bloom"]["per_preset"][preset]["BloomIntensity"]


def test_full_mode_is_the_old_row():
    row = bl.ENGINE_LOOK["bloom"]["per_preset"]["clear"]
    v = bl.bloom_for(row, "full")
    assert v["BloomThreshold"] == row["BloomThreshold"] == -1.0
    with pytest.raises(bl.BeautyLookError):
        bl.bloom_for(row, "glow")


def test_threshold_sits_between_white_and_the_sun():
    white = 0.8  # 0.8-albedo paint under the sun at a correct exposure (mid grey 0.18)
    ramp_top = bl.BLOOM_SUN_THRESHOLD + 2.0  # PostProcessBloom.usf saturate((L - T) * 0.5)
    assert math.log2(bl.BLOOM_SUN_THRESHOLD / white) >= 3.0
    disc = _post_exposure_luminance(1.6e9, 15.0)
    assert disc > 1e4 * ramp_top / 10.0
    glint = _post_exposure_luminance(0.02 * 1.6e9, 15.0)  # 2 % water Fresnel at normal incidence
    assert glint > ramp_top


def test_host_reads_the_switch():
    src = CPP.read_text()
    assert 'TEXT("bloom-mode=")' in src
    assert re.search(r'BloomThresholdFull"\) : TEXT\("BloomThresholdSun"', src)
