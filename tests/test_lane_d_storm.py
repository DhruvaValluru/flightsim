"""Lane D (2026-11-11): severe weather that reads as a photograph from inside a storm.

The owner: "the hurricane does not look real" (#15, the 747 in strong wind, severe
turbulence and heavy rain; #14 stays the refusal; #09 shares the storm look). The
round-4 review: the cell a hard ring over a glowing cylinder, the rain thin white
scratches, #07 a flat grey void, #06 isolated puffs under the deck. Pinned by
reading the source (nothing compiles on this machine): every term is BEAUTY ONLY
and a no-op at its material default, and the Python and C++ twins agree.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from core.scene import storm_cell

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
STORM_HLSL = (REPO / "assets" / "shaders" / "weather" / "storm_cell.hlsl").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def _cpp_constant(text, name):
    match = re.search(rf"constexpr double {name} = ([0-9.eE+-]+);", text)
    assert match, name
    return float(match.group(1))


def _cell():
    return {"base_m": 1500.0, "top_m": 12000.0, "overshoot_m": 1000.0, "tower_radius_m": 4000.0,
            "anvil_radius_m": 15000.0, "anvil_bottom_m": 9000.0, "anvil_offset_enu_m": [3000.0, 0.0],
            "anvil_drift_enu_mps": [10.0, 0.0], "updraft_mps": 15.0,
            "extinction_core_per_m": 0.19, "extinction_anvil_per_m": 0.02,
            "noise": {"seed": 7, "billow_m": 600.0, "erosion": 0.4},
            "shaft": {"radius_m": 1000.0, "extinction_per_m": 0.003}}


# -- the precipitation curtain and the scud (M_StormCell 6) ---------------------------


def test_the_curtain_is_off_unless_asked_and_the_measure_cell_is_unchanged():
    cell = _cell()
    for e, n, u in ((0.0, 0.0, 600.0), (900.0, 200.0, 1200.0), (3000.0, 0.0, 5000.0), (8000.0, 0.0, 1400.0)):
        assert storm_cell.extinction_at(cell, e, n, u) == storm_cell.extinction_at(cell, e, n, u, curtain=None)
        off = dict(storm_cell.BEAUTY_CURTAIN, flare=0.0, scud_depth_m=0.0)
        assert storm_cell.extinction_at(cell, e, n, u, ragged=storm_cell.BEAUTY_RAGGED, curtain=off) == \
            storm_cell.extinction_at(cell, e, n, u, ragged=storm_cell.BEAUTY_RAGGED)


def test_the_curtain_flares_and_thins_toward_the_ground_with_no_hard_rim():
    cell = _cell()
    curtain = storm_cell.BEAUTY_CURTAIN
    shaft_r = cell["shaft"]["radius_m"]
    near_base = storm_cell.curtain_shaft(cell, shaft_r * 1.2, 0.0, 1400.0, None, curtain)
    near_ground = storm_cell.curtain_shaft(cell, shaft_r * 1.2, 0.0, 100.0, None, curtain)
    # outside the measure radius: nothing at the base, curtain near the ground (flare)
    assert near_base["shaft"] < near_ground["shaft"]
    assert near_ground["shaft"] > 0.0
    # thinner toward the ground (the column's water spread, the rain evaporating)
    assert storm_cell.curtain_shaft(cell, 0.0, 0.0, 100.0, None, curtain)["fall"] < \
        storm_cell.curtain_shaft(cell, 0.0, 0.0, 1400.0, None, curtain)["fall"] <= 1.0
    # the rim fades over most of the radius: no step anywhere along a radius
    shapes = [storm_cell.curtain_shaft(cell, k * 20.0, 0.0, 800.0, None, curtain)["shaft"] for k in range(120)]
    assert max(abs(b - a) for a, b in zip(shapes, shapes[1:])) < 0.05
    assert curtain["scud_depth_m"] < 400.0   # inside world_beauty.AIRCRAFT_LAYER_CLEARANCE_M


def test_the_scud_is_ragged_and_only_under_the_base():
    cell = _cell()
    curtain = storm_cell.BEAUTY_CURTAIN
    base = cell["base_m"]
    under = [storm_cell.scud_at(cell, k * 137.0, k * 59.0, base - 150.0, 0.0, None, curtain) for k in range(400)]
    covered = sum(1 for v in under if v > 0.0) / len(under)
    assert 0.05 < covered < 0.9                  # fragments, not a sheet and not nothing
    assert max(under) <= cell["extinction_core_per_m"] * storm_cell.SCUD_SIGMA_SHARE + 1e-12
    assert storm_cell.scud_at(cell, 0.0, 0.0, base + 50.0, 0.0, None, curtain) == 0.0
    assert storm_cell.scud_at(cell, 0.0, 0.0, base - 400.0, 0.0, None, curtain) == 0.0
    assert storm_cell.scud_at(cell, 20000.0, 0.0, base - 150.0, 0.0, None, curtain) == 0.0
    # it drifts with time (half the anvil's drift): the same air, moved
    moved = storm_cell.scud_at(cell, 500.0 + 5.0 * 10.0, 0.0, base - 150.0, 10.0, None, curtain)
    assert moved == pytest.approx(storm_cell.scud_at(cell, 500.0, 0.0, base - 150.0, 0.0, None, curtain))


def test_the_shader_and_the_cpp_carry_the_python_numbers_beauty_only():
    curtain = storm_cell.BEAUTY_CURTAIN
    apply = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyStormVantage(")
    for cpp, key in (("WeatherBeautyCurtainFlare", "flare"), ("WeatherBeautyCurtainGroundThin", "ground_thin"),
                     ("WeatherBeautyScudDepthM", "scud_depth_m"), ("WeatherBeautyScudCover", "scud_cover")):
        assert _cpp_constant(apply, cpp) == curtain[key], cpp
    assert 'StormMaterial->SetVectorParameterValue(TEXT("Curtain")' in apply
    assert WEATHER_CPP.count('TEXT("Curtain")') == 1          # nowhere but the beauty vantage
    assert 'Row->SetObjectField(TEXT("curtain"), Curtain);' in apply
    for text in ("if (Curtain.x > 0.0)", "if (Curtain.z > 0.0)", "shaftDensity *= fall;",
                 "shaft = S.Ss(rOut, rOut * 0.25, rt)",
                 "float rOut = shaftR * (1.0 + Curtain.x * below);",
                 "fall = (1.0 - Curtain.y * below) / (1.0 + Curtain.x * below);",
                 "u * 3.0) / 700.0;", "S.Fbm(q, seed + 7u)", "(0.62 - 0.2 * Curtain.w)) / 0.08",
                 "sigma += Sigma.x * 0.1 * band * rag;"):
        assert text in STORM_HLSL, text
    assert storm_cell.CURTAIN_RIM_SHARE == 0.25 and storm_cell.SCUD_SCALE_M == 700.0
    assert storm_cell.SCUD_SQUASH == 3.0 and storm_cell.SCUD_SIGMA_SHARE == 0.1
    assert (storm_cell.SCUD_CUT, storm_cell.SCUD_CUT_PER_COVER, storm_cell.SCUD_RAMP) == (0.62, 0.2, 0.08)
    assert '"M_StormCell": "6"' in SCRIPT and '"Curtain": params["Curtain"]' in SCRIPT


# -- the severe-rain look: #15 draws the storm preset ---------------------------------

from core.scene import world_beauty as wb  # noqa: E402

CLOUDS_CPP = (BRIDGE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")


def _card_for(prompt):
    from core.nl.compiler import compile_prompt
    from core.scene import storm_weather
    from core.scenario.card import world_look_card_block
    from core.scene.weather_look import weather_look_card_block

    spec = compile_prompt(prompt)
    card = {"weather_look": weather_look_card_block(spec), "look": world_look_card_block(spec)}
    weather = storm_weather.card_block(spec)
    if weather is not None:
        card["weather"] = weather
    return card


def test_heavy_rain_in_a_strong_wind_is_the_storm_look():
    assert wb.select_preset(False, 10.0, False, 0.0, 0.0, 12.9) == "storm"
    assert wb.select_preset(False, 10.0, False, 0.0, 0.0, 5.0) == "rain"      # heavy rain, light wind
    assert wb.select_preset(False, 2.0, False, 0.0, 0.0, 20.0) == "rain"      # light rain, strong wind
    assert wb.select_preset(False, 0.0, False, 0.0, 0.0, 30.0) == "clear"     # wind alone is no storm
    assert wb.select_preset(False, 10.0, False, 0.0, 0.0) == "rain"           # the old call is unchanged
    card = {"weather_look": {"rain_rate_mmh": 10.0}, "weather": {"rain": {"wind_enu_mps": [0.0, -12.86, 0.0]}}}
    assert wb.card_wind_mps(card) == pytest.approx(12.86)
    assert wb.card_preset(card) == "storm"
    drift = {"weather_look": {"rain_rate_mmh": 10.0}, "look": {"cloud_drift": {"mps": 11.0, "from_deg": 0.0}}}
    assert wb.card_preset(drift) == "storm"


def test_the_hurricane_suggestion_draws_the_storm_and_the_refusal_stands():
    card = _card_for("chase view of the 747 at 2000 m in strong wind, severe turbulence and heavy rain "
                     "for 6 seconds")
    assert card["weather_look"]["storm"] is None            # no storm word: the physics is unchanged
    assert wb.card_preset(card) == "storm"
    from core.scene.beauty_look import world_preset_for_card
    assert world_preset_for_card(card)[0] == "storm"        # the grade and the meter see the same world
    assert wb.card_preset(_card_for("747 through a thunderstorm")) == "storm"


def test_the_cpp_twin_reads_the_same_wind_and_thresholds():
    assert f"constexpr double SevereRainMmh = {wb.SEVERE_RAIN_MMH};" in CLOUDS_CPP
    assert f"constexpr double SevereWindMps = {wb.SEVERE_WIND_MPS};" in CLOUDS_CPP
    assert "if (bStorm || IsSevereRain(RainRateMmh, WindMps))" in CLOUDS_CPP
    assert "double VisibilityKm, double WindMps = 0.0)" in CLOUDS_CPP
    assert "SelectPreset(bStorm, RainRate, bRainWord, bCardLayer ? CardCover : 0.0, VisibilityKm, WindMps);" \
        in CLOUDS_CPP
    assert 'RainBlock->TryGetArrayField(TEXT("wind_enu_mps"), WindArray)' in CLOUDS_CPP
    assert 'WorldLookValue(Card, TEXT("cloud_drift"), EJson::Object)' in CLOUDS_CPP


def test_the_rain_deck_is_a_soft_deck_not_puffs():
    row = wb.CLOUDS["nimbostratus"]
    assert wb.RAIN_DEFAULT_COVER < wb.OVERCAST_COVER and wb.RAIN_DEFAULT_COVER >= 0.7
    assert row["coverage_contrast"] <= 0.8 and row["shape_scale_km"] >= 9.0
    assert "{0.045, 9.0, 0.6, 0.3, 0.1, 0.4, 0.8, 0.98},      // nimbostratus" in CLOUDS_CPP

