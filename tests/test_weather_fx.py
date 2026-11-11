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
LOOK_CPP = (BRIDGE / "Private" / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
SCENE_H = (BRIDGE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")
CLOUDS_CPP = (BRIDGE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
FX_CPP = (BRIDGE / "Private" / "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")


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
             "WeatherBeautyRainDepthFadeM": "BEAUTY_RAIN_DEPTH_FADE_M",
             "WeatherBeautyRainSoftness": "BEAUTY_RAIN_SOFTNESS",
             "WeatherBeautyRainVariation": "BEAUTY_RAIN_VARIATION",
             "WeatherBeautyRainRadiance": "BEAUTY_RAIN_RADIANCE"}
    for cpp, py in pairs.items():
        assert _cpp_constant(body, cpp) == getattr(weather_look, py), cpp
    assert "FMath::Loge(Rate / WeatherBeautyRainLightMmh)" in body
    assert "static FFlightSimBeautyRainShape BeautyRainShape(double RateMmh, int32 Particles);" in WEATHER_H


def test_the_shape_is_set_on_the_beauty_path_only_and_recorded():
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    assert "BeautyRainShape(RainRateMmh, Particles)" in readability
    for name in ("Density", "NearThin", "MaxStreak", "MaxCoverage", "DepthFade", "Soft", "Vary",
                 "SkyRadianceScale"):
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
                        "DepthFade": 0.0, "Soft": 0.0, "Vary": 0.0}
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


def test_lane_d_the_beauty_streaks_are_soft_varied_and_background_lit():
    """Round 4's review: thin straight white lines that read as scratches. The
    beauty streak is soft (wider, Gaussian across, tapered), varied by its own
    hash, dimmer than the scene's light, and many more are drawn; each term is
    a no-op at its material default."""
    shape = weather_look.beauty_rain_shape(10.0, 262144)
    assert shape["softness"] > 0.0 and 0.0 < shape["variation"] <= 1.0
    assert 0.0 < shape["radiance"] < 1.0
    assert shape["density_share"] * 262144 >= 30000   # a sheet of streaks at 10 mm/h
    assert shape["max_coverage"] <= 0.25
    offset = (SHADERS / "rain_drop_offset.hlsl").read_text(encoding="utf-8")
    opacity = (SHADERS / "rain_drop_opacity.hlsl").read_text(encoding="utf-8")
    for text in (offset, opacity):
        assert "if (Vary > 0.0)" in text and "if (Soft > 0.0)" in text
        assert "R.Pcg(asuint(Index) ^ 0x68E31DA4u)" in text      # one length hash in both
        assert "streak *= lerp(1.0, 0.45 + 1.1 * h, Vary);" in text
        assert "width *= 1.0 + Soft;" in text
    # The profiles are normalised to a mean of 1 (the soft streak keeps its light).
    xs = [i / 1000.0 for i in range(-1000, 1001)]
    assert abs(sum(math.exp(-4.0 * x * x) for x in xs) / len(xs) - 0.441) < 0.002
    ts = [i / 2000.0 for i in range(2001)]
    assert abs(sum(math.sqrt(math.sin(math.pi * t)) for t in ts) / len(ts) - 0.763) < 0.003
    assert "exp(-4.0 * x * x) / 0.441" in opacity and "/ 0.763" in opacity
    assert _assigned("STORM_GENERATIONS")["M_RainDrops"] == "6"
    creator = SCRIPT[SCRIPT.index("def create_rain_drops"):SCRIPT.index("def create_rain_splash")]
    before, after = creator.split("lib, \"rain_drop_opacity\"")
    for name in ("Soft", "Vary"):
        assert f'"{name}": params["{name}"]' in before and f'"{name}": params["{name}"]' in after
    assert '"Corner": uv_channel(material, lib, 0, "rg"' in after


# -- #09 the cones ------------------------------------------------------------------


def test_the_shafts_soften_on_the_beauty_path_only():
    beauty = _function(LOOK_CPP, "void FFlightSimVisualScene::ApplyBeautyWeatherLook(")
    assert "LookShaftSoftEdgeParameter" in beauty and "LookShaftLightParameter" in beauty
    assert _cpp_constant(LOOK_CPP, "LookBeautyShaftSoftEdge") == weather_look.BEAUTY_SHAFT_SOFT_EDGE
    assert _cpp_constant(LOOK_CPP, "LookBeautyShaftLight") == weather_look.BEAUTY_SHAFT_LIGHT
    assert 'LookShaftSoftEdgeParameter = TEXT("ShaftSoftEdge")' in LOOK_CPP
    assert 'LookShaftLightParameter = TEXT("ShaftLight")' in LOOK_CPP
    # The shafts' instances are kept at build, set only by the beauty call.
    assert "ShaftInstances.Add(ShaftInstance);" in LOOK_CPP
    assert LOOK_CPP.count("LookShaftSoftEdgeParameter") == 2   # the name and the one set
    assert "TArray<UMaterialInstanceDynamic*> ShaftInstances;" in SCENE_H
    assert "void ApplyBeautyWeatherLook(UWorld* World);" in SCENE_H
    # Its one caller is the beauty world look (built only under -quality=beauty).
    build = CLOUDS_CPP[CLOUDS_CPP.index("bool FFlightSimWorldBeauty::Build("):]
    assert build.count("Scene.ApplyBeautyWeatherLook(World);") == 1
    assert CLOUDS_CPP.count("ApplyBeautyWeatherLook") == 1
    # The material's defaults draw generation 1's cones; the stamp brings the graph.
    assert _assigned("SHAFT_BEAUTY_DEFAULTS") == {"ShaftSoftEdge": 0.0, "ShaftLight": 1.0}
    assert _assigned("WEATHER_LOOK_GENERATIONS")["M_RainShaft"] >= "2"
    soft = (SHADERS / "rain_shaft_soft.hlsl").read_text(encoding="utf-8")
    assert "if (SoftEdge <= 0.0)\n{\n\treturn 1.0;\n}" in soft
    shaft = SCRIPT[SCRIPT.index("def create_rain_shaft"):SCRIPT.index("def create_tornado_funnel")]
    assert 'custom(material, lib, "rain_shaft_soft"' in shaft
    assert "MaterialExpressionCameraVectorWS" in shaft


def test_a_stale_weather_look_material_is_updated_in_place():
    maker = SCRIPT[SCRIPT.index("def _weather_material"):SCRIPT.index("def _world_xy_metres")]
    assert "weather_look_stale(name)" in maker
    assert "delete_all_material_expressions(material)" in maker
    stamp = SCRIPT[SCRIPT.index("def finish(material, name)"):SCRIPT.index("def linear_default_texture")]
    assert "WEATHER_LOOK_GENERATION_TAG" in stamp
    assert set(_assigned("WEATHER_LOOK_GENERATIONS")) == {"M_RainShaft", "M_TornadoFunnel", "M_TornadoPuff",
                                                           "M_TornadoFunnelSoft"}


def test_the_lamps_scatter_a_stated_fraction_in_fog():
    assert "Lamp.Spot->SetVolumetricScatteringIntensity(" in FX_CPP
    assert "Lamp.Point->SetVolumetricScatteringIntensity(" in FX_CPP
    assert 0.0 < _cpp_constant(FX_CPP, "AircraftFxLandingVolumetricScattering") < 1.0
    assert 0.0 < _cpp_constant(FX_CPP, "AircraftFxNavVolumetricScattering") < 1.0
    assert 'TEXT("landing_volumetric_scattering")' in FX_CPP
    # The bulb's beam stays the spot's own cone (tests/test_aircraft_look.py).
    assert "Lamp.Spot->SetInnerConeAngle(0.5f * Cone);" in FX_CPP


# -- #10 the tornado ----------------------------------------------------------------


def test_the_funnel_gets_a_lit_material_in_beauty_with_no_vertex_colour():
    beauty = _function(LOOK_CPP, "void FFlightSimVisualScene::ApplyBeautyWeatherLook(")
    assert "TObjectIterator<UProceduralMeshComponent>" in beauty
    assert 'LookFunnelComponentName = TEXT("TornadoFunnel")' in LOOK_CPP
    scenario = (BRIDGE / "Private" / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    # Round 6: the funnel and its wall cloud are spawned by one lambda, named
    # at the call; the beauty dresses each through Dress(...).
    assert "NewObject<UProceduralMeshComponent>(Marker, Name)" in scenario
    assert 'SpawnMarker(TEXT("TornadoFunnel"))' in scenario
    assert "Mesh->SetMaterial(0, Instance);" in beauty
    assert 'Dress(Funnel, TEXT("tornado_funnel")' in beauty
    colour = tuple(float(v) for v in re.findall(r"LookBeautyFunnelColour[RGB] = ([0-9.]+)f;", LOOK_CPP))
    assert colour == weather_look.BEAUTY_FUNNEL_COLOUR == _assigned("FUNNEL_COLOUR_DEFAULT")
    funnel = SCRIPT[SCRIPT.index("def create_tornado_funnel"):SCRIPT.index("def create_lightning():")]
    assert "VertexColor" not in funnel.split('"""', 2)[2]   # gotcha 26: no vertex colour read
    assert "BLEND_TRANSLUCENT" not in funnel and "WORLD_POSITION_OFFSET" not in funnel
    assert 'finish(material, "M_TornadoFunnel")' in funnel
    assert "create_tornado_funnel()" in SCRIPT[SCRIPT.index("create_rain_shaft()\n"):]


def test_the_engine_symbols_are_in_the_bridge_check():
    block = CHECK[CHECK.index("BEGIN weather-fx"):CHECK.index("END weather-fx")]
    for needle in ("SetVolumetricScatteringIntensity", "SetSourceRadius", "TObjectIterator",
                   "SetMaterial", "SetScalarParameterValue", "SetVectorParameterValue",
                   "UMaterialExpressionCameraVectorWS"):
        assert needle in block, needle
