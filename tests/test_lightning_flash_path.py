"""Scene #09 stability (2026-11-13): the stroke's flash light casts no
shadows by default, and a frame has one flash path.

The render box (Intel iGPU, D3D11 SM5, ~491 MB usable) lost the device on
#09 every time. FlightSimWeather.cpp built the stroke's movable point light
with SetCastShadows(true) and a 30 km radius: a cube shadow pass over the
whole scene on each stroke frame, for under 1 % of the scene's light (swarm
lane weather_fx/lightning/storm). The light's intensity, colour, radius and
placement are unchanged; only its shadows are off. -lightning-shadows=on
keeps the old shadowed light reachable (the command line, then
FLIGHTSIM_RENDER_SWITCHES). The weather look's own bolt and light stand down
whenever the storm weather draws its lightning. Beauty-only actors: labels,
masks and depth are untouched, and nothing here reaches the flight model.
"""

import re
from pathlib import Path

from webapp.runs import with_render_switches

SOURCE = (Path(__file__).resolve().parents[1] / "ue" / "Plugins" / "FlightSimBridge" / "Source"
          / "FlightSimBridge")
WEATHER_CPP = (SOURCE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (SOURCE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
LOOK_CPP = (SOURCE / "Private" / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
SCENE_H = (SOURCE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")
COMMANDLET = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
INTERACTIVE = (SOURCE / "Private" / "FlightSimInteractiveMode.cpp").read_text(encoding="utf-8")


def _function(text, signature):
    start = text.index(signature)
    open_at = text.index("{", start)
    depth = 0
    for i in range(open_at, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    raise AssertionError(f"unbalanced {signature}")


def test_the_stroke_light_is_unshadowed_unless_switched_on():
    build = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildLightning(")
    assert "FlashLight->SetCastShadows(true);" not in WEATHER_CPP
    assert "FlashLight->SetCastShadows(bFlashShadows);" in build
    # the light itself is the one it was: candelas, 30 km, the same colour
    assert "FlashLight->SetIntensityUnits(ELightUnits::Candelas);" in build
    assert "FlashLight->SetAttenuationRadius(static_cast<float>(WeatherFlashLightRadiusCm));" in build
    assert "constexpr double WeatherFlashLightRadiusCm = 3.0e6;" in WEATHER_CPP
    assert "FlashLight->SetLightColor(FLinearColor(0.86f / 0.913f, 0.92f / 0.913f, 1.0f / 0.913f));" in build
    # recorded either way
    assert 'Row->SetStringField(TEXT("flash_light"), bFlashShadows' in build
    # the option defaults off and reaches the member Build keeps
    assert "bool bLightningShadows = false;" in WEATHER_H
    assert "bool bFlashShadows = false;" in WEATHER_H
    assert "bFlashShadows = Options.bLightningShadows;" in _function(WEATHER_CPP, "bool FFlightSimWeather::Build(")


def test_the_switch_reads_the_command_line_then_the_switch_channel_and_refuses_other_words():
    parse = _function(WEATHER_CPP, "bool FFlightSimWeather::ParseLightningShadows(")
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in parse
    assert parse.index("Params + TEXT(\" \")") < parse.index('GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))')
    assert 'FString Word = TEXT("off");' in parse
    assert 'FParse::Value(*Switches, TEXT("lightning-shadows="), Word);' in parse
    assert 'Word == TEXT("on")' in parse and 'Word == TEXT("off")' in parse
    assert "weather.lightning_shadows: -lightning-shadows=%s is not on or off" in parse
    # both hosts parse it before the weather is built, and refuse a bad word
    for host, build in ((COMMANDLET, "Weather.Build(World, WeatherOptions, Error)"),
                        (INTERACTIVE, "Weather.Build(GetWorld(), WeatherOptions, Error)")):
        at = host.index("FFlightSimWeather::ParseLightningShadows(")
        assert at < host.index(build)
        assert "WeatherOptions.bLightningShadows, Error)" in host[at:at + 200]


def test_one_flash_path_the_look_bolt_stands_down_for_the_storm_weather():
    assert "bool DrawsLightning() const { return bLightning; }" in WEATHER_H
    assert "void StandDownLookLightning();" in SCENE_H
    stand = _function(LOOK_CPP, "void FFlightSimVisualScene::StandDownLookLightning(")
    assert "LightningLight->SetIntensity(0.0f);" in stand
    assert "Root->SetVisibility(false, true);" in stand
    assert "LightningInstance = nullptr;" in stand and "LightningLight = nullptr;" in stand
    # AdvanceWeather only drives a bolt it still holds
    advance = _function(LOOK_CPP, "void FFlightSimVisualScene::AdvanceWeather(")
    assert "if (LightningInstance != nullptr)" in advance and "if (LightningLight != nullptr)" in advance
    # the look's own light keeps its brightness and stays unshadowed
    assert "constexpr double LightningCandela = 3.0e8;" in LOOK_CPP
    assert "LightningLight->SetCastShadows(false);" in LOOK_CPP
    # each host stands the look down after the weather is built
    for host, scene in ((COMMANDLET, "VisualScene"), (INTERACTIVE, "Visual")):
        guard = re.search(r"if \(Weather\.DrawsLightning\(\)\)\s*\{\s*" + scene + r"\.StandDownLookLightning\(\);",
                          host)
        assert guard is not None, scene
    # the card with a cell already skipped the look's bolt (bSkipStormLook): unchanged
    assert '(*StormWeather)->HasField(TEXT("cell"));' in COMMANDLET


def test_the_switch_rides_the_switch_channel():
    planned = ["UnrealEditor-Cmd.exe", "FlightSim.uproject", "-run=FlightSimBridge.FlightSimRender",
               "-quality=beauty"]
    out = with_render_switches(planned, "-lightning-shadows=on")
    run = out.index("-run=FlightSimBridge.FlightSimRender")
    assert out[run + 1] == "-lightning-shadows=on"
