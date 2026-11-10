"""Round-2b weather-fx (2026-11-09): the beauty rain, shafts, funnel and lamps.

Round 0 (docs/visual/round_0 on origin/phase-2-final) showed #07 heavy rain as a
full-frame wall of vertical streaks, #09 two hard-edged glowing cones under the
747 and #10 no tornado. Pinned here by reading the source (no engine on this
machine): the Python twin and the C++ twin of the beauty rain shape agree, the
shape is set only on the beauty path, the material defaults are the measure
path's shader, and every new material parameter is one the script exposes.
docs/visual/PROBE_LOG.md "## round-2b weather-fx" holds the probes.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

from core.scene import weather_look

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not in the material script")


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def _cpp_constant(text, name):
    match = re.search(rf"constexpr double {name} = ([0-9.eE+-]+);", text)
    assert match, name
    return float(match.group(1))


# -- #07 the rain -------------------------------------------------------------------


def test_the_beauty_rain_follows_the_rate_and_never_draws_a_sheet():
    budget = 262144
    light = weather_look.beauty_rain_shape(2.0, budget)
    heavy = weather_look.beauty_rain_shape(40.0, budget)
    assert tuple(heavy) == weather_look.BEAUTY_RAIN_KEYS
    # Density and streak length both rise with the rate; neither is the whole box.
    assert light["density_share"] < heavy["density_share"] < 1.0
    assert light["max_streak_rad"] < heavy["max_streak_rad"]
    assert heavy["max_streak_rad"] <= weather_look.BEAUTY_RAIN_STREAK_RAD_HEAVY
    # A streak 1 m from the lens is at most a few degrees long (round 0: the frame).
    assert math.degrees(heavy["max_streak_rad"]) < 3.0
    # No streak is opaque; the far drops fade; the near ones are thinned.
    assert heavy["max_coverage"] < 0.5
    assert heavy["depth_fade_m"] > 0.0 and heavy["near_thin_m"] > 1.0
    # Held outside the anchors; a dry rate still draws a floor of drops.
    assert weather_look.beauty_rain_shape(500.0, budget)["max_streak_rad"] == \
        weather_look.BEAUTY_RAIN_STREAK_RAD_HEAVY
    assert weather_look.beauty_rain_shape(0.0, budget)["density_share"] == \
        weather_look.BEAUTY_RAIN_MIN_SHARE
    assert weather_look.beauty_rain_shape(1000.0, 10)["density_share"] == 1.0


def test_the_cpp_twin_carries_the_python_numbers():
    body = _function(WEATHER_CPP, "FFlightSimBeautyRainShape FFlightSimWeather::BeautyRainShape(")
    pairs = {"WeatherBeautyRainDropsPerMmh": "BEAUTY_RAIN_DROPS_PER_MMH",
             "WeatherBeautyRainMinShare": "BEAUTY_RAIN_MIN_SHARE",
             "WeatherBeautyRainNearThinM": "BEAUTY_RAIN_NEAR_THIN_M",
             "WeatherBeautyRainStreakRadLight": "BEAUTY_RAIN_STREAK_RAD_LIGHT",
             "WeatherBeautyRainStreakRadHeavy": "BEAUTY_RAIN_STREAK_RAD_HEAVY",
             "WeatherBeautyRainLightMmh": "BEAUTY_RAIN_LIGHT_MMH",
             "WeatherBeautyRainHeavyMmh": "BEAUTY_RAIN_HEAVY_MMH",
             "WeatherBeautyRainMaxCoverage": "BEAUTY_RAIN_MAX_COVERAGE",
             "WeatherBeautyRainDepthFadeM": "BEAUTY_RAIN_DEPTH_FADE_M"}
    for cpp, py in pairs.items():
        assert _cpp_constant(body, cpp) == getattr(weather_look, py), cpp
    assert "FMath::Loge(Rate / WeatherBeautyRainLightMmh)" in body
    assert "static FFlightSimBeautyRainShape BeautyRainShape(double RateMmh, int32 Particles);" in WEATHER_H


def test_the_shape_is_set_on_the_beauty_path_only_and_recorded():
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    assert "BeautyRainShape(RainRateMmh, Particles)" in readability
    for name in ("Density", "NearThin", "MaxStreak", "MaxCoverage", "DepthFade"):
        assert f'RainMaterial->SetScalarParameterValue(TEXT("{name}")' in readability, name
        # Nowhere else: the measure path keeps the material's defaults.
        assert WEATHER_CPP.count(f'TEXT("{name}")') == 1, name
    assert 'TEXT("beauty_shape")' in readability
    # Metres on the card, centimetres in the shader.
    assert "Shape.NearThinM * WeatherCmPerMetre" in readability
    assert "Shape.DepthFadeM * WeatherCmPerMetre" in readability


def test_the_material_defaults_are_the_measure_paths_shader():
    defaults = _assigned("DROPS_BEAUTY_DEFAULTS")
    assert defaults == {"Density": 1.0, "NearThin": 0.0, "MaxStreak": 0.0, "MaxCoverage": 1.0,
                        "DepthFade": 0.0}
    assert set(defaults) <= set(_assigned("DROPS_PARAMETERS"))
    assert _assigned("STORM_GENERATIONS")["M_RainDrops"] >= "5"   # the shader body changed
    offset = (SHADERS / "rain_drop_offset.hlsl").read_text(encoding="utf-8")
    opacity = (SHADERS / "rain_drop_opacity.hlsl").read_text(encoding="utf-8")
    # Each beauty term is a no-op at its default.
    assert "if (Index >= Active * Density)" in offset
    assert "if (NearThin > 0.0)" in offset and "if (MaxStreak > 0.0)" in offset
    assert "if (MaxStreak > 0.0)" in opacity and "if (DepthFade > 0.0)" in opacity
    assert "float shown = min(saturate(coverage), MaxCoverage);" in opacity
    # The coverage follows the streak the offset draws: the same cap in both.
    cap = "streak = max(min(streak, MaxStreak * dist), diameterCm);"
    assert cap in offset and cap in opacity
    # The 30 cm near fade (the owner's 2026-10-09 frame) is kept.
    assert "float nearFade = R.Ss(5.0, 30.0, dist);" in opacity
    creator = SCRIPT[SCRIPT.index("def create_rain_drops"):SCRIPT.index("def create_rain_splash")]
    for name in ("Density", "NearThin", "MaxStreak"):
        assert f'"{name}": params["{name}"]' in creator.split("lib, \"rain_drop_opacity\"")[0], name
    for name in ("MaxStreak", "MaxCoverage", "DepthFade"):
        assert f'"{name}": params["{name}"]' in creator.split("lib, \"rain_drop_opacity\"")[1], name
