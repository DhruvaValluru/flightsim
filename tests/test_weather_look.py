"""The weather look: the card's weather_look block (core/scene/weather_look.py)
and the engine side that draws it (FlightSimWeatherLook.cpp, uncompiled
here, so pinned by its text).

Measured here: the block is absent for a spec that states no weather (the
card is unchanged), carries the surface, the storm, the rain, the wetness
and the ice in its fixed order when one is stated, and gives a
thunderstorm a stated visual rain rate. Pinned: every material the C++
loads is one the script creates, under the parameter names the script
exposes; the storm's actors are beauty-only and the lens drops go on the
beauty capture only (the label passes are unchanged); the flash law in the
C++ is the one re-implemented here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.nl.compiler import compile_prompt
from core.scene.weather_look import (
    CARD_KEYS, ICE_FULL_ETA, STORM_RAIN_MMH, WET_AT_MMH, weather_look_card_block,
)

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
SCENE_CPP = (BRIDGE / "Private" / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
COMMANDLET_CPP = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")


def spec_for(prompt="fly the c172p at 1500 m and 100 kt"):
    spec = compile_prompt(prompt)
    spec.set("hold_state", False, frm="test")
    return spec


# -- the card block ------------------------------------------------------------------

def test_no_weather_writes_no_block():
    assert weather_look_card_block(spec_for()) is None


def test_surface_storm_rain_and_ice_ride_in_order():
    spec = spec_for("fly the c172p at 1500 m and 100 kt over the desert through a thunderstorm")
    block = weather_look_card_block(spec)
    assert tuple(block) == CARD_KEYS
    assert block["surface"] == "desert" and block["storm"] == "thunderstorm"
    assert block["rain_rate_mmh"] == STORM_RAIN_MMH
    assert block["rain_source"] == "thunderstorm visual default"
    assert block["wetness"] == 1.0


def test_stated_rain_sets_rate_and_wetness():
    spec = spec_for()
    spec.set("precipitation_rate_mmh", 2.0, frm="test")
    block = weather_look_card_block(spec)
    assert block["rain_rate_mmh"] == 2.0 and block["storm"] is None
    assert block["wetness"] == pytest.approx(2.0 / WET_AT_MMH)


def test_wet_runway_and_ice_alone_write_a_block():
    spec = spec_for()
    spec.set("rain.aerodynamics", False, frm="test")
    spec.set("rain.runway_condition", "standing_water", frm="test")
    spec.set("icing.severity", "moderate", frm="test")
    block = weather_look_card_block(spec)
    assert block["rain_rate_mmh"] is None and block["wetness"] == 1.0
    assert block["ice_eta_max"] == pytest.approx(0.20)


def test_the_card_carries_the_block_only_when_stated(tmp_path):
    from core.scenario.card import write_run_card
    import json

    plain = json.loads(write_run_card(spec_for(), tmp_path / "a.json").read_text(encoding="utf-8"))
    assert "weather_look" not in plain
    storm = spec_for("fly the c172p at 1500 m and 100 kt over the ocean")
    card = json.loads(write_run_card(storm, tmp_path / "b.json").read_text(encoding="utf-8"))
    assert set(card) - set(plain) == {"weather_look"}
    assert card["weather_look"]["surface"] == "ocean"


# -- the engine side, pinned by text --------------------------------------------------

def _cpp_constant(name: str) -> float:
    match = re.search(rf"constexpr double {name} = ([\d.e+-]+);", WEATHER_CPP)
    assert match, name
    return float(match.group(1))


def test_every_ground_word_has_a_material_the_script_creates():
    from core.environment.surface import SURFACE_CLASSES

    rows = dict(re.findall(r'\{TEXT\("(\w+)"\), TEXT\("/Game/FlightSim/(M_Ground_\w+)\.\2"\)\}',
                           WEATHER_CPP))
    assert set(rows) == set(SURFACE_CLASSES)
    for surface, name in rows.items():
        assert f'create_ground("{surface}", _weather_material("{name}"))' in SCRIPT


def test_parameter_names_match_the_script():
    names = dict(re.findall(r'const TCHAR\* const Weather(\w+)Parameter = TEXT\("(\w+)"\);',
                            WEATHER_CPP))
    assert names["Wet"] == "Wetness" and 'WET_GROUND_PARAMETER = "Wetness"' in SCRIPT
    script = dict(re.findall(r'"(\w+)": "(\w+)"', SCRIPT[SCRIPT.index("WEATHER_PARAMETERS = {"):]
                                                      .split("}")[0]))
    assert {names["Drop"], names["Shaft"], names["Flash"], names["Ice"]} == set(script.values())


def test_the_ice_scale_and_storm_rate_agree_with_the_card():
    assert _cpp_constant("IceFullEta") == ICE_FULL_ETA
    assert _cpp_constant("WeatherReferenceRateMmh") == STORM_RAIN_MMH


def test_storm_actors_are_beauty_only_and_drops_are_on_the_beauty_capture():
    assert WEATHER_CPP.count("BeautyOnlyActors.Add(") == 2          # the shafts and the bolt
    assert ("Beauty->PostProcessSettings.WeightedBlendables.Array.Add("
            "FWeightedBlendable(1.0f, LensDropsInstance));") in WEATHER_CPP
    assert COMMANDLET_CPP.count("VisualScene.ApplyLensDropsToBeauty(Capture);") == 1
    rain = COMMANDLET_CPP.index("VisualScene.ApplyRainToBeauty(Capture, RainCameraId, Error)")
    drops = COMMANDLET_CPP.index("VisualScene.ApplyLensDropsToBeauty(Capture);")
    assert 0 < drops - rain < 200
    label = COMMANDLET_CPP[COMMANDLET_CPP.index(
        "auto ConfigureLabelCapture = [&](USceneCaptureComponent2D* Label)"):]
    label = label[:label.index("\t\t};")]
    assert "LensDrops" not in label and "WeightedBlendables" not in label
    # The drops are added where the rain is: inside the beauty capture's block.
    assert "LensDropsInstance" not in COMMANDLET_CPP


def test_build_applies_the_look_after_the_flat_ground_and_advances_it():
    ground = SCENE_CPP.index("FlatGround = GroundMesh;")
    call = SCENE_CPP.index("if (!ApplyWeatherLook(World, Options, Error))")
    assert ground < call
    advance = SCENE_CPP[SCENE_CPP.index("void FFlightSimVisualScene::AdvanceWorld"):]
    assert "AdvanceWeather(TimeSeconds);" in advance[:advance.index("\n}\n")]
    assert "Part->SetOverlayMaterial(IceInstance);" in WEATHER_CPP
    assert "VisualScene.ApplyIceOverlay(Scenario.Aircraft);" in COMMANDLET_CPP


def test_a_missing_material_is_recorded_never_refused():
    # No refusal-name prefix ("x.y: ") anywhere in the weather look.
    assert not re.search(r'TEXT\("[a-z_]+\.[a-z_]+: ', WEATHER_CPP)
    assert "return false;" not in WEATHER_CPP


def _flash(t: float, seed: int) -> float:
    """LightningFlash re-implemented from its documentation."""
    period, length = _cpp_constant("FlashPeriodSeconds"), _cpp_constant("FlashSeconds")
    offset = (seed % 1000) / 1000.0 * period
    cycle = (max(t, 0.0) + offset) % period
    if cycle >= length:
        return 0.0
    if cycle < 0.4 * length:
        return 1.0
    return 0.2 if cycle < 0.6 * length else 0.8


def test_the_flash_law_matches_its_text():
    body = WEATHER_CPP[WEATHER_CPP.index("double FFlightSimVisualScene::LightningFlash"):]
    body = body[:body.index("\n}\n")]
    assert "% 1000u) / 1000.0 *" in body and "FlashPeriodSeconds" in body
    assert "0.4 * FlashSeconds" in body and "0.6 * FlashSeconds ? 0.2 : 0.8" in body
    samples = [_flash(t / 100.0, 7) for t in range(0, 2000)]
    lit = sum(1 for v in samples if v > 0.0) / len(samples)
    assert 0.01 < lit < 0.06                         # about FlashSeconds / FlashPeriodSeconds
    assert _flash(0.0, 0) == 1.0 and _flash(1.0, 0) == 0.0
