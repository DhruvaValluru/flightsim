"""The weather's Unreal side, pinned by reading the source (no engine here).

FlightSimWeather (the card's weather block drawn: drops, splashes, the
storm cell, lightning, the glass, thunder), its hooks in the render
commandlet and the interactive window, the Niagara dependency, the
materials' parameters and Custom node inputs, the card keys the C++ reads.

Not verified here: that any of it compiles or draws; the closed forms are
compiled and run in tests/test_weather.py, the rest is docs/WEATHER.md's
first Windows build (clauses WX.1-WX.6).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from core.scene import storm_weather

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
COMMANDLET = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
INTERACTIVE = (BRIDGE / "Private" / "FlightSimInteractiveMode.cpp").read_text(encoding="utf-8")
INTERACTIVE_H = (BRIDGE / "Public" / "FlightSimInteractiveMode.h").read_text(encoding="utf-8")
BUILD_CS = (BRIDGE / "FlightSimBridge.Build.cs").read_text(encoding="utf-8")
UPLUGIN = json.loads((REPO / "ue" / "Plugins" / "FlightSimBridge" / "FlightSimBridge.uplugin").read_text(encoding="utf-8"))
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"
DOC = (REPO / "docs" / "WEATHER.md").read_text(encoding="utf-8")


def _tuple(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not in the material script")


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def test_niagara_is_a_dependency_of_the_module_and_the_plugin():
    assert '"Niagara"' in BUILD_CS
    assert {"Name": "Niagara", "Enabled": True} in UPLUGIN["Plugins"]


def test_the_commandlet_builds_the_weather_after_the_scene_and_hides_it_from_labels():
    build = COMMANDLET.index("Weather.Build(World, WeatherOptions, Error)")
    assert COMMANDLET.index("VisualScene.Build(World, SceneOptions, Error)") < build
    append = COMMANDLET.index("VisualScene.BeautyOnlyActors.Append(Weather.BeautyOnlyActors)")
    # Before any label capture reads the beauty-only list.
    assert build < append < COMMANDLET.index("Label->HiddenActors.Append(VisualScene.BeautyOnlyActors)")
    assert 'LookApplied->SetObjectField(TEXT("weather"), Weather.Record)' in COMMANDLET
    assert 'TEXT("weather-backend=")' in COMMANDLET
    assert "WeatherOptions.bManualNiagaraTick = true" in COMMANDLET
    assert "WeatherOptions.bAudio = false" in COMMANDLET


def test_the_commandlet_advances_the_weather_before_each_capture():
    advance = COMMANDLET.index("Weather.Advance(WeatherView)")
    flush = COMMANDLET.index("World->SendAllEndOfFrameUpdates();", advance)
    assert COMMANDLET.index("Capture->CaptureScene();", advance) > flush > advance
    loop = COMMANDLET[COMMANDLET.index("for (int32 Step = 0; Step < Steps; ++Step)"):]
    assert "Weather.Advance(WeatherView)" in loop
    assert "WeatherView.CameraCm = Capture->GetComponentLocation()" in COMMANDLET
    assert "ExposureShutterSeconds > 0.0" in COMMANDLET


def test_the_drops_supersede_the_screen_space_streaks():
    block = COMMANDLET[COMMANDLET.index("if (Weather.DrawsRain())"):]
    assert block.index("superseded_by") < block.index("VisualScene.ApplyRainToBeauty(Capture")
    assert "else if (!VisualScene.ApplyRainToBeauty(Capture, RainCameraId, Error))" in COMMANDLET
    assert 'RainCameraPreset == TEXT("cockpit")' in COMMANDLET
    assert "Weather.ApplyWindshield(Capture" in COMMANDLET


def test_the_interactive_window_draws_the_storm_without_sound():
    assert "FFlightSimWeather Weather;" in INTERACTIVE_H
    assert "WeatherOptions.bAudio = false" in INTERACTIVE
    tick = _function(INTERACTIVE, "void AFlightSimInteractiveMode::Tick")
    assert "Weather.Advance(View)" in tick
    assert "PlayerCameraManager->GetCameraLocation()" in tick


def test_the_backends_are_named_and_anything_else_refused():
    parse = _function(WEATHER_CPP, "bool FFlightSimWeather::ParseBackend")
    for word in ("procedural", "niagara", "off"):
        assert f'TEXT("{word}")' in parse
    assert "weather.backend" in parse


def test_every_refusal_is_by_name():
    for name in ("weather.card", "weather.selftest", "weather.frame", "weather.rain_material",
                 "weather.storm_material", "weather.lightning_material", "weather.windshield",
                 "weather.niagara_asset", "weather.backend"):
        assert name in WEATHER_CPP, name
        assert name in DOC, name


def test_the_selftests_are_checked_at_build():
    assert "WeatherSelftestTolerance = 1.0e-9" in WEATHER_CPP
    rain = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildRain")
    assert 'TryGetArrayField(TEXT("selftest")' in rain
    assert "SampleDiameterMm(Unit(RainSeed, Index, 3)" in rain
    lightning = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildLightning")
    assert "WindowPower(Curve, *Flash, A, B)" in lightning
    thunder = _function(WEATHER_CPP, "bool FFlightSimWeather::ReadThunder")
    assert "SynthesiseThunder(Thunder, Flash" in thunder


def test_every_weather_actor_is_beauty_only():
    for actor in ("RainActor", "LightningActor"):
        assert f"BeautyOnlyActors.Add({actor})" in WEATHER_CPP


def _set_on(variable):
    """Every parameter name the C++ sets on one material instance variable."""
    names = set(re.findall(rf"{variable}->Set(?:Scalar|Vector)ParameterValue\(TEXT\(\"(\w+)\"\)", WEATHER_CPP))
    assert names, variable
    return names


def test_the_parameters_the_cpp_sets_are_the_ones_the_script_exposes():
    rain = set(_tuple("DROPS_PARAMETERS"))
    assert _set_on("RainMaterial") <= rain
    assert _set_on("SplashMaterial") <= set(_tuple("SPLASH_PARAMETERS"))
    assert _set_on("FlashMaterials\\[I\\]") | _set_on("Instance") <= set(_tuple("LIGHTNING_PARAMETERS"))
    storm = set(_tuple("STORM_PARAMETERS")) | {"Albedo"}
    assert _set_on("StormMaterial") <= storm
    assert _set_on("WindshieldMaterial") <= set(_tuple("WINDSHIELD_PARAMETERS"))
    # And every material the C++ loads is one the script makes.
    for name in re.findall(r"/Game/FlightSim/(M_\w+)\.", WEATHER_CPP):
        assert name in _tuple("STORM_MATERIALS"), name


def test_every_custom_node_input_is_a_shader_input():
    for call in re.finditer(r'custom\(material, lib, "(\w+)", [^{]+\{(.*?)\}, -?\d+, -?\d+\)', SCRIPT, re.S):
        shader, inputs = call.group(1), call.group(2)
        text = (SHADERS / f"{shader}.hlsl").read_text(encoding="utf-8")
        names = re.findall(r'"(\w+)":', inputs)
        assert names, shader
        for name in names:
            assert re.search(rf"//\s+{name}\s", text), (shader, name)
            assert re.search(rf"\b{name}\b", text.split("struct", 1)[-1]), (shader, name)


def test_the_card_keys_the_cpp_reads_are_on_the_card():
    from tests.test_weather import _Spec

    block = storm_weather.card_block(_Spec(event="thunderstorm", rate=5.0))
    keys = set()

    def walk(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                keys.add(key)
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(block)
    read = set(re.findall(r'WeatherNumber\([^,]+, TEXT\("(\w+)"\)', WEATHER_CPP))
    read |= set(re.findall(r'WeatherVector\([^,]+, TEXT\("(\w+)"\)', WEATHER_CPP))
    downburst = {"origin_x_m", "origin_y_m", "centre_north_m", "centre_east_m", "core_radius_m",
                 "outflow_max_mps", "outflow_height_m"}
    # A continuing current's keys appear only on the flashes that have one.
    continuing = {"duration_s", "w_per_m"}
    lightning_source = (REPO / "core" / "scene" / "lightning.py").read_text(encoding="utf-8")
    assert all(f'"{key}"' in lightning_source for key in continuing)
    assert read - downburst - continuing <= keys, sorted(read - downburst - continuing - keys)


def test_the_niagara_recipe_documents_every_user_parameter():
    params = set(re.findall(r'TEXT\("User\.(\w+)"\)', WEATHER_CPP))
    assert params
    for name in params:
        assert f"User.{name}" in DOC, name
    assert "/Game/FlightSim/Weather/NS_FlightSimRain" in DOC


def test_the_storm_weather_is_opt_in_and_replaces_the_rain_particles_when_asked():
    parse = _function(WEATHER_CPP, "bool FFlightSimWeather::ParseBackend")
    assert 'Name.IsEmpty() || Name == TEXT("off")' in parse
    assert "EFlightSimWeatherBackend WeatherBackend = EFlightSimWeatherBackend::Off;" in COMMANDLET
    skip = COMMANDLET.index("SceneOptions.bSkipRainParticles = WeatherBackend != EFlightSimWeatherBackend::Off")
    assert skip < COMMANDLET.index("VisualScene.Build(World, SceneOptions, Error)")
    rain = (BRIDGE / "Private" / "FlightSimRainParticles.cpp").read_text(encoding="utf-8")
    body = _function(rain, "bool FFlightSimVisualScene::ApplyRainParticles")
    assert body.index("if (Options.bSkipRainParticles)") < body.index("RainNumber(Block, TEXT(\"count\")")
    # On a cockpit camera the glass takes the lens drops' place, never both.
    lens = COMMANDLET.index("VisualScene.ApplyLensDropsToBeauty(Capture);")
    glass = COMMANDLET.index("Weather.ApplyWindshield(Capture", lens)
    assert "if (!bStormGlass)" in COMMANDLET[lens - 60:lens]
    assert "else" in COMMANDLET[lens:glass]


def test_the_web_app_asks_for_the_storm_weather_only_when_told(monkeypatch):
    from webapp import runs

    monkeypatch.delenv("FLIGHTSIM_WEATHER_BACKEND", raising=False)
    assert runs.weather_backend_flags() == []
    monkeypatch.setenv("FLIGHTSIM_WEATHER_BACKEND", "procedural")
    assert runs.weather_backend_flags() == ["-weather-backend=procedural"]
    monkeypatch.setenv("FLIGHTSIM_WEATHER_BACKEND", "hail")
    import pytest
    with pytest.raises(ValueError):
        runs.weather_backend_flags()


def test_the_storm_material_is_compiled_and_checked_before_the_cloud_draws_it():
    """Measured on the owner's machine: the volumetric cloud asserted
    'Material->GetMaterialDomain() == MD_Volume' while M_StormCell's shaders
    were still compiling (a not-ready material renders as the default surface
    material). The cell now compiles it first and skips a bad one by name."""
    cell = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildCell")
    check = cell.index("Base->MaterialDomain != MD_Volume")
    assert check < cell.index("Resource->FinishCompilation();") < cell.index("GetCompileErrors()")
    assert cell.index("GetCompileErrors()") < cell.index("StormClouds->SetMaterial(StormMaterial)")
    assert "weather.storm_material" in cell[check:cell.index("StormClouds->SetMaterial(StormMaterial)")]


def test_the_storm_material_is_flagged_for_the_volumetric_cloud_and_every_cloud_is_verified():
    """Measured on the owner's machine (2026-10-08): the engine's cloud SHADOW
    pass asserts MD_Volume on a cloud whose material compiled without cloud
    shaders -- a Volume material not flagged 'Used with Volumetric Cloud'.
    The script sets the flag (new and existing assets), BuildCell checks it,
    and both hosts verify every cloud before the first frame."""
    assert 'STORM_USAGE_PROPERTY = "used_with_volumetric_cloud"' in SCRIPT
    storm = SCRIPT[SCRIPT.index("def create_storm_cell"):SCRIPT.index("def create_windshield_rain")]
    assert 'ensure_volumetric_cloud_usage("M_StormCell")' in storm
    assert "material.set_editor_property(STORM_USAGE_PROPERTY, True)" in storm
    repair = SCRIPT[SCRIPT.index("def ensure_volumetric_cloud_usage"):SCRIPT.index("def create_storm_cell")]
    assert "recompile_material" in repair and "save_asset" in repair
    cell = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildCell")
    assert cell.index("GetUsageByFlag(MATUSAGE_VolumetricCloud)") < cell.index("Resource->FinishCompilation();")
    verify = _function(WEATHER_CPP, "bool FFlightSimWeather::VerifyCloudMaterials")
    for needle in ("TObjectIterator<UVolumetricCloudComponent>", "MD_Volume",
                   "MATUSAGE_VolumetricCloud", "GetCompileErrors()", "clouds.material"):
        assert needle in verify, needle
    # The commandlet verifies after the shader wait and before the warm-up captures.
    wait = COMMANDLET.index('TEXT("waiting for shader compilation")')
    check = COMMANDLET.index("FFlightSimWeather::VerifyCloudMaterials(World, CloudError, &CloudReport)")
    warmup = COMMANDLET.index("for (int32 i = 0; i < WarmupCaptures; ++i)")
    assert wait < check < warmup
    assert "VerifyCloudMaterials(GetWorld(), Error)" in INTERACTIVE


def test_the_if_pins_are_connected_under_a_name_the_engine_accepts_or_refused():
    """Measured on the owner's 5.7: connecting "A>B" did nothing and every
    If-based material (M_LensDrops, and the older M_GreyCard, M_LandcoverID,
    M_RainStreaks built the same way) failed with 'Missing If AGreaterThanB
    input'. select_if now tries each engine name and raises, naming the
    node's real inputs, when none connects."""
    assert 'IF_PIN_NAMES = (("A > B", "A>B", "AGreaterThanB")' in SCRIPT
    select = SCRIPT[SCRIPT.index("def select_if"):SCRIPT.index("def in_unit_interval")]
    assert "connect(lib, constant(material, lib, value, x - 150, y), \"\", node, names)" in select
    helper = SCRIPT[SCRIPT.index("def connect(lib, source"):SCRIPT.index("def select_if")]
    assert "if lib.connect_material_expressions(source, source_out, node, name):" in helper
    assert "raise RuntimeError" in helper
    assert 'os.environ.get("FLIGHTSIM_REBUILD_MATERIALS"' in SCRIPT
    assert "delete_asset(full)" in SCRIPT


def test_the_debug_script_runs_the_render_commandlet_per_backend_and_keeps_the_logs():
    text = (REPO / "scripts" / "debug_storm_render.py").read_text(encoding="utf-8")
    assert "run_headless(list(command) + list(HEADLESS_FLAGS), log, watch=[frames])" in text
    assert '"-run=FlightSimBridge.FlightSimRender"' in text
    assert 'extra.append(f"-weather-backend={backend}")' in text
    assert "Assertion failed" in text and "Failed to compile Material" in text
    assert "debug_storm_render.py" in DOC
