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


def test_a_requested_rebuild_is_not_skipped_by_the_tonemapper_move():
    """Measured on the owner's machine: FLIGHTSIM_REBUILD_MATERIALS rebuilt
    M_GreyCard and M_LandcoverID (which then compiled) but not M_RainStreaks
    or M_LensDrops, whose creators return early from move_after_tonemapping
    before new_material's delete; the move now yields to a rebuild."""
    move = SCRIPT[SCRIPT.index("def move_after_tonemapping"):SCRIPT.index("def new_material")]
    assert "or rebuild_requested(name)" in move


def test_the_storm_is_lit_by_multiple_scattering_and_its_exposure_is_metered():
    """The owner's first storm frame (2026-10-08) rendered black: the cloud
    material had no VolumetricAdvancedMaterialOutput (single scattering:
    nothing under an 11 km tower), the look's deck was drawn 156 optical
    depths deep, and the look's manual exposure stood. Now: the node with
    its phase and two multiple-scattering octaves, the deck capped to a
    nimbostratus depth, the commandlet metering a frame read back before
    frame 0 (never closing, never past the physical cap), the window on
    the engine's histogram, and the debug script measuring the frames."""
    scattering = _tuple("STORM_SCATTERING")
    assert scattering["octaves"] == 2 and scattering["phase_g"] == 0.8 and scattering["phase_g2"] < 0.0
    properties = _tuple("STORM_SCATTERING_PROPERTIES")
    assert set(properties) == set(scattering)
    node = SCRIPT[SCRIPT.index("def storm_scattering"):SCRIPT.index("def weather_shader")]
    assert "unreal.MaterialExpressionVolumetricAdvancedMaterialOutput" in node
    assert '("ground_contribution", True)' in node
    assert "raise RuntimeError" in node   # a refused property name is reported, never skipped
    # Measured on the owner's machine (2026-10-09): the per-sample atmosphere
    # transmittance switch is the cloud component's, not the node's; the
    # refused name cost the storm its material.
    assert "per_sample_atmosphere_light_transmittance" not in SCRIPT
    storm = SCRIPT[SCRIPT.index("def create_storm_cell"):SCRIPT.index("def create_windshield_rain")]
    assert "storm_scattering(material, lib" in storm
    cell = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildCell")
    assert "LayerDepthMaxM = 1500.0" in cell and "LayerTopDrawnM" in cell
    assert 'TEXT("look_layer_top_drawn_m")' in cell
    # The drawn top is what the shader's Layer parameter gets.
    assert "static_cast<float>(LayerTopDrawnM), static_cast<float>(LayerExtinctionPerM)" in cell
    assert "static_cast<float>(Options.LayerTopMetres), static_cast<float>(LayerExtinctionPerM)" not in cell
    assert "bool DrawsCell() const { return bCell; }" in WEATHER_H
    # The commandlet meters after the warm-up captures and before the probe loop.
    warmup = COMMANDLET.index("for (int32 i = 0; i < WarmupCaptures; ++i)")
    meter = COMMANDLET.index("if (Weather.DrawsCell() && !bAutoExposure)")
    probe = COMMANDLET.index("// -- Phase 8B.0: the real-time probe loop")
    assert warmup < meter < probe
    metering = COMMANDLET[meter:probe]
    for needle in ("ReadPixels(MeterPixels)", "FMath::Clamp(Opened + Step, 0.0, StormMeterMaxStops)",
                   'TEXT("storm_exposure")', "MeterSettings.AutoExposureBias =",
                   # the clip keeps a measured exposure: the last round never steps
                   'MeterNote = TEXT("out of rounds; the last measured exposure stands");',
                   "OpenedMeasured = Opened;",
                   # the linear and accumulation captures render at the metered bias too
                   "for (USceneCaptureComponent2D* Sibling : {LinearCapture, AccumulateCapture})",
                   "Sibling->PostProcessSettings.AutoExposureBias = MeterSettings.AutoExposureBias;"):
        assert needle in metering, needle
    assert "constexpr double StormMeterMaxStops = 8.0;" in COMMANDLET
    assert 'TEXT("storm-meter-target=")' in COMMANDLET
    assert "opened %.2f stops by the storm meter" in COMMANDLET   # the scene record says so
    window = INTERACTIVE[INTERACTIVE.index("Weather.DrawsCell()"):]
    assert "AEM_Histogram" in window[:1200]
    debug = (REPO / "scripts" / "debug_storm_render.py").read_text(encoding="utf-8")
    assert "def frame_luma" in debug and "RENDERED-DARK" in debug
    # The record's fields, the same on both sides.
    assert '(manifest.get("look_applied") or {}).get("storm_exposure")' in debug
    for field in ("stops_opened", "mean_luma_before", "mean_luma_after", "target_mean_luma", "note"):
        assert f'TEXT("{field}")' in metering, field
        assert f"meter.get('{field}')" in debug, field
    # A re-run clears the previous run's frames; a crash outranks a manifest;
    # the look is the web app's for the spec.
    assert 'stale.unlink(missing_ok=True)' in debug
    assert '"CRASHED" if crashed else ("RENDERED" if rendered' in debug
    assert "render_look_for(spec," in debug and "look=look" in debug
    assert "storm_exposure" in DOC and "STORM_SCATTERING" in DOC


def test_a_storm_material_built_by_an_older_script_is_built_again():
    """Every storm material is stamped with STORM_GENERATION as asset
    metadata; one stamped older (or not at all) is deleted and rebuilt by
    its own creator, so a graph change here reaches a machine that built
    the storm before it. The windshield's tonemapper move and the cloud's
    usage repair both yield to a stale stamp."""
    assert re.search(r'^STORM_GENERATION = "\d+"$', SCRIPT, re.M)
    stale = SCRIPT[SCRIPT.index("def storm_material_stale"):SCRIPT.index("def finish_storm")]
    assert "get_metadata_tag" in stale and "STORM_GENERATION_TAG" in stale
    stamp = SCRIPT[SCRIPT.index("def finish_storm"):SCRIPT.index("def storm_scattering")]
    assert "set_metadata_tag(material, STORM_GENERATION_TAG, STORM_GENERATION)" in stamp
    maker = SCRIPT[SCRIPT.index("def _storm_material"):SCRIPT.index("_ASIDE = {}")]
    assert "storm_material_stale(name)" in maker
    # The old asset is set aside, never deleted before the new one is saved
    # (measured 2026-10-09: a delete-then-build left the storm no material).
    assert "rename_asset(full, aside)" in maker and "raise RuntimeError" in maker
    assert "unreal.EditorAssetLibrary.delete_asset(full)" not in maker
    assert "restore_storm_materials()" in SCRIPT[SCRIPT.index("def _guard"):]
    stamp = SCRIPT[SCRIPT.index("def finish_storm"):SCRIPT.index("def storm_scattering")]
    assert "_ASIDE.pop(name, None)" in stamp and "delete_asset(aside)" in stamp
    for name in _tuple("STORM_MATERIALS"):
        assert f'finish_storm(material, "{name}")' in SCRIPT, name
        assert f'finish(material, "{name}")' not in SCRIPT, name
    repair = SCRIPT[SCRIPT.index("def ensure_volumetric_cloud_usage"):SCRIPT.index("def create_storm_cell")]
    assert "or storm_material_stale(name)" in repair
    glass = SCRIPT[SCRIPT.index("def create_windshield_rain"):]
    assert 'not storm_material_stale("M_WindshieldRain") and move_after_tonemapping' in glass
