"""maxpick/rain (2026-11-13): the baked tier 0 of the storm rain and the windscreen.

-rain-layers=on draws the falling rain as three baked layers in one post-process
pass (M_RainLayers) instead of the particle drops; -windscreen-baked=on draws a
cockpit's glass from baked optics (M_WindshieldRainBaked) instead of
M_WindshieldRain's hashed loop. Both default off and beauty only. Nothing here
compiles or renders (the Mac has no engine build): the tests read the source and
re-run the bakes.

* the switches ride the web app's render-switch channel onto the argv and the
  bridge reads them, off by default, on a beauty run only;
* the bakes are reproducible byte for byte and equal the swarm lanes' PROVENANCE
  sha256 (copied into each PIN.json);
* both effects are beauty only: blendables on the beauty capture, never a label
  capture's, and the particle drops they replace stay beauty-only actors;
* the C++ constants, the shaders' and the script's parameters agree with the bakes.
"""

import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from webapp.runs import with_render_switches

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
BAKED_CPP = (PRIVATE / "FlightSimWeatherBaked.cpp").read_text(encoding="utf-8")
WEATHER_CPP = (PRIVATE / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (PUBLIC / "FlightSimWeather.h").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts/ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets/shaders/weather"
RAIN_DIR = REPO / "assets/looks/rain_layers"
GLASS_DIR = REPO / "assets/looks/windscreen_water"
RAIN_PLAN = json.loads((RAIN_DIR / "rain_layers.json").read_text(encoding="utf-8"))
GLASS_PLAN = json.loads((GLASS_DIR / "windscreen_water_storm.json").read_text(encoding="utf-8"))


def _strip_comments(text):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not in the material script")


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _numbers(text):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", text)]


# -- the switches reach the command line ------------------------------------------------

PLANNED = ["UnrealEditor-Cmd.exe", "FlightSim.uproject", "-run=FlightSimBridge.FlightSimRender",
           "-quality=beauty", "-weather-backend=procedural", "-rain-gain=4"]


@pytest.mark.parametrize("switches", ["-rain-layers=on", "-windscreen-baked=on",
                                      "-rain-layers=on -windscreen-baked=on",
                                      "-rain-layers=off -windscreen-baked=off"])
def test_the_baked_switches_reach_the_argv_ahead_of_the_planned_flags(switches):
    out = with_render_switches(PLANNED, switches)
    run = out.index("-run=FlightSimBridge.FlightSimRender")
    tokens = switches.split()
    assert out[run + 1:run + 1 + len(tokens)] == tokens
    assert out[run + 1 + len(tokens):] == PLANNED[3:]


def test_the_environment_channel_carries_them_too(monkeypatch):
    monkeypatch.setenv("FLIGHTSIM_RENDER_SWITCHES", "-rain-layers=on -windscreen-baked=on")
    out = with_render_switches(PLANNED)
    assert "-rain-layers=on" in out and "-windscreen-baked=on" in out


def test_the_bridge_reads_both_switches_off_by_default_on_a_beauty_run_only():
    code = _strip_comments(RENDER_CPP)
    build = code.index("if (!Weather.Build(World, WeatherOptions, Error))")
    block = code[code.rindex("if (bBeauty)", 0, build):build]
    assert 'FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in block
    assert "Params + TEXT(\" \")" in block
    assert 'ParseBakedSwitch(BakedSwitches, TEXT("rain-layers="),\n' in block
    assert "WeatherOptions.bRainLayers, Error)" in block
    assert 'ParseBakedSwitch(BakedSwitches, TEXT("windscreen-baked="),\n' in block
    assert "WeatherOptions.bWindscreenBaked, Error)" in block
    assert "return Fail(Error);" in block
    # Off unless asked: the options' defaults, the parser's default word, a refusal for any other.
    assert "bool bRainLayers = false;" in WEATHER_H and "bool bWindscreenBaked = false;" in WEATHER_H
    parse = _function(BAKED_CPP, "bool FFlightSimWeather::ParseBakedSwitch(")
    assert 'FString Value = TEXT("off");' in parse
    assert 'Value != TEXT("on") && Value != TEXT("off")' in parse and "weather.baked_switch" in parse
    build_fn = _function(WEATHER_CPP, "bool FFlightSimWeather::Build(")
    assert "bRainLayers = Options.bRainLayers;" in build_fn
    assert "bWindscreenBaked = Options.bWindscreenBaked;" in build_fn
    # The interactive window never sets them (the render's A/B only).
    interactive = (PRIVATE / "FlightSimInteractiveMode.cpp").read_text(encoding="utf-8")
    assert "bRainLayers" not in interactive and "bWindscreenBaked" not in interactive


def test_every_refusal_is_catalogued():
    catalog = (REPO / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    for name in ("weather.baked_switch", "weather.rain_layers", "weather.windscreen_baked"):
        assert f"{name}:" in BAKED_CPP or f"{name}:" in BAKED_CPP.replace("TEXT(\"", "")
        assert re.search(rf"^{re.escape(name)}:$", catalog, re.M), name


# -- the bakes are reproducible and are the lanes' --------------------------------------

def _pin(folder):
    return json.loads((folder / "PIN.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("folder", [RAIN_DIR, GLASS_DIR])
def test_the_committed_bake_is_its_pin(folder):
    pin = _pin(folder)
    assert pin["provenance"]["branch"] == "origin/max-push"
    assert re.fullmatch(r"[0-9a-f]{40}", pin["provenance"]["commit"])
    on_disk = {p.name for p in folder.iterdir()} - {"PIN.json"}
    assert on_disk == set(pin["files"]), "every committed file is pinned, every pin committed"
    for name, row in pin["files"].items():
        data = (REPO / row["path"]).read_bytes()
        assert row["path"] == f"{folder.relative_to(REPO)}/{name}"
        assert len(data) == row["size"], name
        assert hashlib.sha256(data).hexdigest() == row["sha256"], name


def test_the_rain_bake_reproduces_byte_for_byte(tmp_path):
    plan = _load("make_rain_layers").build(write=True, out_dir=tmp_path)
    pin = _pin(RAIN_DIR)
    written = {row["path"]: row["sha256"] for row in plan["_files"]}
    assert written == {name: row["sha256"] for name, row in pin["files"].items()}
    for name, row in pin["files"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == row["sha256"], name


def test_the_windscreen_bake_reproduces_byte_for_byte(tmp_path):
    assert _load("make_windscreen_water").main(["--out", str(tmp_path)]) == 0
    pin = _pin(GLASS_DIR)
    assert {p.name for p in tmp_path.iterdir()} == set(pin["files"])
    for name, row in pin["files"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == row["sha256"], name


def test_the_material_script_imports_the_pinned_bakes():
    assert _assigned("RAIN_LAYERS_PIN") == "assets/looks/rain_layers/PIN.json"
    assert _assigned("WINDSHIELD_BAKED_PIN") == "assets/looks/windscreen_water/PIN.json"
    rain_pin, glass_pin = _pin(RAIN_DIR), _pin(GLASS_DIR)
    assert set(_assigned("RAIN_LAYERS_FILES")) <= set(rain_pin["files"])
    assert _assigned("RAIN_LAYERS_PLAN") in rain_pin["files"]
    assert set(_assigned("WINDSHIELD_BAKED_FILES").values()) <= set(glass_pin["files"])
    helper = SCRIPT[SCRIPT.index("def baked_texture("):SCRIPT.index("def baked_float4(")]
    assert "pinned_texture(pin[\"files\"][file_name], name, False, False)" in helper   # sha-checked import
    assert "never_stream" in helper
    # The materials prep on the render box runs when assets/looks/ or the script changes.
    ps1 = (REPO / "scripts/visual_fix_round.ps1").read_text(encoding="utf-8")
    assert "^assets/looks/" in ps1 and "^scripts/ue_create_materials\\.py$" in ps1


# -- beauty only: labels, masks and depth cannot change ----------------------------------

def test_both_effects_are_blendables_on_the_beauty_capture_only():
    code = _strip_comments(BAKED_CPP)
    adds = re.findall(r"(\w+)->PostProcessSettings\.WeightedBlendables\.Array\.Add\(\s*"
                      r"FWeightedBlendable\(1\.0f, (\w+)\)\)", code)
    assert sorted(adds) == [("Beauty", "RainLayersMaterial"), ("Beauty", "WindscreenBakedMaterial")]
    for forbidden in ("SpawnActor", "NewObject<USceneCapture", "HiddenActors", "ShowOnlyActors",
                      "PostProcessVolume", "bRenderCustomDepth", "CustomDepthStencil", "ConfigureLabelCapture"):
        assert forbidden not in code, forbidden
    # The commandlet hands both the beauty capture, before any label capture exists.
    render = _strip_comments(RENDER_CPP)
    apply_layers = render.index("Weather.ApplyRainLayers(Capture, Error)")
    apply_glass = render.index("Weather.ApplyWindshield(Capture, AirspeedKt * 0.514444, Error)")
    assert render.count("Weather.ApplyRainLayers(") == 1
    assert apply_layers < render.index("auto ConfigureLabelCapture")
    assert apply_glass < render.index("auto ConfigureLabelCapture")
    label_region = render[render.index("auto ConfigureLabelCapture"):
                          render.index("USceneCaptureComponent2D* LinearCapture = nullptr;")]
    assert "RainLayers" not in label_region and "WindshieldRainBaked" not in label_region
    # The baked glass is what ApplyWindshield draws when asked (one call site, the beauty's).
    glass = _function(WEATHER_CPP, "bool FFlightSimWeather::ApplyWindshield(")
    assert "return ApplyWindscreenBaked(Beauty, AirspeedMps, Error);" in glass


def test_the_rain_it_replaces_was_beauty_only_and_its_actor_still_is():
    rain = _function(WEATHER_CPP, "bool FFlightSimWeather::BuildRain(")
    actor = rain.index("BeautyOnlyActors.Add(RainActor);")
    layers = rain.index("if (bRainLayers)")
    assert actor < layers, "the (empty) rain actor stays hidden from every label capture"
    branch = rain[layers:rain.index("BuildRainMesh(World, Error)")]
    assert "else if (Backend == EFlightSimWeatherBackend::Niagara)" in branch, \
        "-rain-layers=on builds neither the mesh nor the Niagara system"
    assert 'TEXT("drawn_as"), bRainLayers ? TEXT("baked_layers") : TEXT("particles")' in rain
    # The scene's label pass appends the weather's beauty-only actors before any label capture.
    assert "VisualScene.BeautyOnlyActors.Append(Weather.BeautyOnlyActors);" in RENDER_CPP


def test_the_baked_materials_are_post_process_after_the_tonemapper():
    for creator, name in (("def create_rain_layers(", "M_RainLayers"),
                          ("def create_windshield_rain_baked(", "M_WindshieldRainBaked")):
        body = SCRIPT[SCRIPT.index(creator):]
        body = body[:body.index("\ndef ")]
        assert f'_storm_material("{name}")' in body and f'finish_storm(material, "{name}")' in body
        assert "MD_POST_PROCESS" in body and "after_tonemapping()" in body
        assert name in _assigned("STORM_MATERIALS") and _assigned("STORM_GENERATIONS")[name] == "1"
        assert re.search(rf"^{creator[4:-1]}\(\)", SCRIPT, re.M), "called by the script"
    # The existing materials are untouched: the default-off path draws exactly what it drew.
    assert _assigned("STORM_GENERATIONS")["M_RainDrops"] == "6"
    assert _assigned("STORM_GENERATIONS")["M_WindshieldRain"] == "3"


# -- the constants agree with the bakes ----------------------------------------------------

def _cpp_array(name):
    match = re.search(rf"{name}\[\w*\] = \{{([^}}]*)\}};", BAKED_CPP)
    assert match, name
    return _numbers(match.group(1))


def _cpp_constant(name):
    match = re.search(rf"constexpr double {name} = ([-0-9.e]+);", BAKED_CPP)
    assert match, name
    return float(match.group(1))


def test_the_rain_constants_are_the_bakes():
    assert _cpp_array("WeatherBakedBinSweepM") == [b["sweep_m"] for b in RAIN_PLAN["bins"]]
    assert _cpp_array("WeatherBakedTileHeightM") == [l["tile_height_m"] for l in RAIN_PLAN["layers"]]
    assert _cpp_constant("WeatherBakedDensityPerM3") == RAIN_PLAN["physics"]["density_drawn_per_m3"]
    tex = RAIN_PLAN["texture"]
    shader = (SHADERS / "rain_layers.hlsl").read_text(encoding="utf-8")
    assert f"({tex['nrep']}.0 / 6.28318530718)" in shader
    assert f"* {tex['nu']}.0;" in shader and f"* {tex['nv']}.0;" in shader
    lo, hi = tex["pole_fade_sin"]
    assert f"smoothstep({lo}, {hi}, sinT)" in shader
    assert _assigned("RAIN_LAYERS_LIFT") == 0.35 and "SetNumberField(TEXT(\"lift\"), 0.35)" in BAKED_CPP


def test_the_windscreen_constants_are_the_bakes():
    make = _load("make_windscreen_water")
    assert _cpp_constant("WeatherBakedTanMax") == GLASS_PLAN["optics"]["tan_max"]
    assert abs(_cpp_constant("WeatherBakedTileM") - make.TILE_MM / 1000.0) < 1e-9
    assert _cpp_constant("WeatherBakedMeanCapAreaM2") == GLASS_PLAN["drops"]["mean_cap_area_m2"]
    assert _cpp_constant("WeatherBakedMaxCover") == GLASS_PLAN["drops"]["max_cover"]
    assert _cpp_constant("WeatherBakedASpan") == GLASS_PLAN["shader"]["a_span"]
    assert _cpp_constant("WeatherBakedVShedMps") == GLASS_PLAN["law"]["v_shed_mps"]
    table = GLASS_PLAN["drops"]["density_to_cover"]
    assert _cpp_array("WeatherBakedCoverDensity") == [d for d, _ in table]
    assert _cpp_array("WeatherBakedCoverShare") == [c for _, c in table]
    # The glass's static lifetime is the one FlightSimWeather.cpp already has.
    assert "constexpr double WeatherGlassStaticLifeS = 6.0;" in WEATHER_CPP
    assert _cpp_constant("WeatherBakedGlassLifeS") == 6.0
    shader = (SHADERS / "windshield_baked.hlsl").read_text(encoding="utf-8")
    assert f"* {GLASS_PLAN['shader']['edge_gain']});" in shader
    assert abs(_assigned("WINDSHIELD_BAKED_LENS_H") - make.TAN_MAX / 2.0) < 1e-6
    assert _assigned("WINDSHIELD_BAKED_TILES") == make.TILES


def test_the_host_wet_port_matches_the_lanes_law():
    """FlightSimWeatherBaked.cpp ApplyWindscreenBaked is make_windscreen_water.host_wet on the
    card's numbers: replay it in Python, line for line, against the lane's two worked examples."""
    make = _load("make_windscreen_water")
    table = GLASS_PLAN["drops"]["density_to_cover"]
    area = GLASS_PLAN["drops"]["mean_cap_area_m2"]
    import math

    import numpy as np

    for key, v, imp in (("example_wet_at_100kt", 51.44, GLASS_PLAN["example_impinge_per_m2_s_at_100kt"]),
                        ("example_wet_at_15mps_taxi", 15.0, None)):
        if imp is None:
            imp = GLASS_PLAN["example_impinge_per_m2_s_at_100kt"] * 15.0 / 51.44
        hold = 1.0 if v <= 22.0 else 22.0 / v
        wetted = 1.0 - math.exp(-imp * area * 5.0)
        cover = min(0.3, wetted) * hold
        dens = float(np.interp(cover, [c for _, c in table], [d for d, _ in table]))
        riv = 0.75 * (1.0 - hold) * min(1.0, wetted / 0.3)
        ref = make.host_wet(v, imp, 5.0, area, table)
        assert round(dens, 4) == ref["drop_density"] and round(riv, 4) == ref["rivulet_density"], key
    code = _function(BAKED_CPP, "bool FFlightSimWeather::ApplyWindscreenBaked(")
    for line in ("const double Hold = V <= WeatherBakedVShedMps ? 1.0 : WeatherBakedVShedMps / V;",
                 "const double Wetted = 1.0 - FMath::Exp(-WindshieldImpinge * WeatherBakedMeanCapAreaM2 * "
                 "WeatherBakedGlassLifeS);",
                 "const double Cover = FMath::Min(WeatherBakedMaxCover, Wetted) * Hold;",
                 "const double TrackDensity = WeatherBakedASpan * (1.0 - Hold) * FMath::Min(1.0, Wetted / "
                 "WeatherBakedMaxCover);",
                 "const double HeadRate = WindshieldRunoffMps / WeatherBakedTileM;"):
        assert line in code, line


def test_the_parameters_the_cpp_sets_are_the_ones_the_script_exposes():
    def set_on(variable):
        return set(re.findall(rf"{variable}->Set(?:Scalar|Vector)ParameterValue\(TEXT\(\"(\w+)\"\)", BAKED_CPP))

    # Lift and Tiles keep the material's stated defaults (the script's constants).
    assert set_on("RainLayersMaterial") == set(_assigned("RAIN_LAYERS_PARAMETERS")) - {"Lift"}
    assert set_on("WindscreenBakedMaterial") == set(_assigned("WINDSHIELD_BAKED_PARAMETERS")) - {"Tiles"}
    for name in re.findall(r"/Game/FlightSim/(M_\w+)\.", BAKED_CPP):
        assert name in _assigned("STORM_MATERIALS"), name
    for name in _assigned("RAIN_LAYERS_PARAMETERS") + _assigned("RAIN_LAYERS_BAKE_PARAMETERS"):
        assert f'"{name}"' in SCRIPT[SCRIPT.index("def create_rain_layers("):], name
    # The look contract finds the baked glass and bounds its refraction from LensH.
    assert 'Base->GetFName() == FName(TEXT("M_WindshieldRainBaked"))' in RENDER_CPP
    assert 'K2_GetScalarParameterValue(TEXT("LensH"))' in RENDER_CPP


# -- SM5: the shaders are small, straight-line and use nothing past D3D11 -----------------

@pytest.mark.parametrize("name", ["rain_layers", "windshield_baked"])
def test_the_shaders_are_sm5_straight_line_code(name):
    code = _strip_comments((SHADERS / f"{name}.hlsl").read_text(encoding="utf-8"))
    for forbidden in (r"\bfor\s*\(", r"\bwhile\s*\(", r"\[unroll", r"\[loop", r"\bWave\w+\(", r"\bQuad\w+\(",
                      r"\bddx", r"\bddy", r"\bfwidth\(", r"\.Sample\(", r"\.SampleGrad\(", r"\bdiscard\b",
                      r"\bclip\(", r"\buint64", r"\bhalf\b", r"\bdouble\b", r"\bView\.", r"\bResolvedView\."):
        assert not re.search(forbidden, code), (name, forbidden)
    assert not re.search(r"\w\[[^\]]*\]", code), "no array indexing"
    assert len([line for line in code.splitlines() if line.strip()]) < 50, "small"
    # Every input the script wires is declared in the shader's header (test_ue_weather_source's rule).
    call = re.search(rf'custom\(material, lib, "{name}", [^{{]+\{{(.*?)\}}, -?\d+, -?\d+\)', SCRIPT, re.S)
    assert call, name
    text = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
    for pin in re.findall(r'"(\w+)":', call.group(1)):
        assert re.search(rf"//\s+{pin}\s", text), (name, pin)


def test_the_rain_layers_take_three_taps_with_an_explicit_lod():
    code = _strip_comments((SHADERS / "rain_layers.hlsl").read_text(encoding="utf-8"))
    assert code.count(".SampleLevel(") == 1, "one tap in the per-layer method"
    assert code.count("R.Alpha(") == 3, "called once per layer"
    for k in range(3):
        assert f"R.Alpha(Layer{k}, Layer{k}Sampler, Scale{k}," in code
    assert "atan2(py, (abs(px) + abs(py)) > 1.0e-6 ? px : 1.0)" in code, "no atan2(0, 0)"
    assert "CotT * Rho / span - Ph" in code, "the travel is subtracted: the rain falls along its axis"
