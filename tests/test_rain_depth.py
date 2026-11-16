"""Round 147 (#07 "tower view, heavy rain, 250 mm": a flat grey wall): the rain veil's
three curtain shells each take their own tone and curtain contrast (-rain-depth=on,
the default; off is generation 6). core/scene/rain_veil.py is the Python twin of
FlightSimWeather.cpp ApplyBeautyRainVeil; the switch is read in FlightSimClouds.cpp."""
from __future__ import annotations

import re
from pathlib import Path

from core.scene import rain_veil as rv

BRIDGE = Path(__file__).resolve().parents[1] / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
CLOUDS_CPP = (BRIDGE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")


def _cpp_array(name):
    m = re.search(rf"constexpr double {name}\[3\] = \{{([^}}]*)\}};", WEATHER_CPP)
    assert m, name
    return tuple(float(v) for v in m.group(1).split(","))


def test_cpp_shell_rows_are_the_python_twin():
    assert _cpp_array("VeilDepthShade") == rv.VEIL_DEPTH_SHADE
    assert _cpp_array("VeilDepthVary") == rv.VEIL_DEPTH_VARY
    assert "const double ShellShade = VeilShade * (bBeautyRainDepth ? VeilDepthShade[Shell] : 1.0);" in WEATHER_CPP
    assert "const double ShellVary = bBeautyRainDepth ? VeilDepthVary[Shell] : VeilVary;" in WEATHER_CPP
    assert 'SetScalarParameterValue(TEXT("Shade"), static_cast<float>(ShellShade));' in WEATHER_CPP
    assert 'SetScalarParameterValue(TEXT("VeilVary"), static_cast<float>(ShellVary));' in WEATHER_CPP
    assert "bool bBeautyRainDepth = true;" in WEATHER_H


def test_the_switch_defaults_on_and_refuses_other_words():
    assert rv.RAIN_DEPTH_DEFAULT == "on" and rv.RAIN_DEPTH_WORDS == ("on", "off")
    assert 'FString RainDepthSwitch = TEXT("on");' in CLOUDS_CPP
    assert 'FParse::Value(*Switches, TEXT("rain-depth="), RainDepthSwitch);' in CLOUDS_CPP
    assert '-rain-depth=%s is not on or off' in CLOUDS_CPP
    assert 'Weather.SetBeautyRainDepth(RainDepthSwitch == TEXT("on"));' in CLOUDS_CPP


def test_layers_near_light_far_dark_and_off_is_generation_6():
    for deck in (True, False):
        near, mid, far = (rv.shell_shade(s, deck) for s in range(3))
        assert near > mid > far
        assert mid == rv.veil_shade(deck)
        assert all(rv.shell_shade(s, deck, depth=False) == rv.veil_shade(deck) for s in range(3))
    assert rv.shell_vary(2) > rv.shell_vary(0) == rv.VEIL_VARY
    assert all(rv.shell_vary(s, depth=False) == rv.VEIL_VARY for s in range(3))
    # the near streaks read LIGHTER than the deck behind them, the far shafts darker
    assert rv.shell_shade(0, True) > 1.0 > rv.shell_shade(2, True)
