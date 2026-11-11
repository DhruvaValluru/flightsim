"""Visual round 6 (2026-11-10): round 4's #09 rain shaft and #10 tornado.

Round 4 (docs/visual/round_4) showed #10 ("c172 near a tornado over the Flint
Hills at 600 m") with no tornado in the frame and the prairie red (ground R/G
2.2 under a neutral sky), and #09's rain shaft as a smooth glowing cylinder.
Pinned here by reading the source (no engine on this machine): the vortex
axis is placed where the chase camera sees it, the funnel stops at a wall
cloud that turns at the model's own exterior rate, the beauty deck shadows
the storm look's 10 deg beam, and the beauty shaft gets streaks, an eroded
rim and a grey albedo inside the measure shaft's own volume -- each Python
twin equal to its C++ and HLSL, constant for constant.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

import pytest

from core.environment import tornado
from core.scene import storm_cell, weather_look, world_beauty

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
SCENARIO_CPP = (BRIDGE / "Private" / "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
SCENARIO_H = (BRIDGE / "Public" / "FlightSimScenarioWorld.h").read_text(encoding="utf-8")
LOOK_CPP = (BRIDGE / "Private" / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
CLOUDS_CPP = (BRIDGE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (BRIDGE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"
STORM_HLSL = (SHADERS / "storm_cell.hlsl").read_text(encoding="utf-8")
ALBEDO_HLSL = (SHADERS / "storm_shaft_albedo.hlsl").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
RUNNER_PY = (REPO / "core" / "scenario" / "runner.py").read_text(encoding="utf-8")
RUNS_PY = (REPO / "webapp" / "runs.py").read_text(encoding="utf-8")

#: The chase camera's frame: 55 deg horizontal (webapp.runs write_sky_plan's
#: fallback, camera.py "Horizontal FOV ~54.4 deg"), 16:9, pitched about 6 deg
#: down (round 4's #10: the horizon at row 215 of 720).
CHASE_HALF_WIDTH_DEG = 27.5
CHASE_HALF_HEIGHT_DEG = math.degrees(math.atan(math.tan(math.radians(27.5)) * 9.0 / 16.0))
CHASE_PITCH_DOWN_DEG = 6.0
C172_CHASE_BACK_M = 28.0


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not in the material script")


def _cpp_constant(text, name):
    match = re.search(rf"constexpr (?:double|float) {name} = ([0-9.eE+-]+)f?;", text)
    assert match, name
    return float(match.group(1))


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


# -- #10: the axis is where the chase camera looks ----------------------------------


def test_the_abeam_axis_stands_ahead_of_the_whole_run_inside_the_chase_frame():
    """Round 4's #10: 139 m ahead, 375 m abeam = 67 deg off the view axis. Now
    the c172's 6 s run (309 m) plus the standoff (3.5 x 600 m AGL = 2100 m)
    ahead: inside the 27.5 deg half-width for every frame, its ground contact
    inside the frame's lower half, the vortex wind at the aircraft a breeze."""
    run_m = 100.0 * 1852.0 / 3600.0 * 6.0
    ahead, abeam = tornado.abeam_placement("abeam", run_m, 600.0)
    assert abeam == pytest.approx(2.5 * tornado.R_CORE_M) == 375.0
    assert ahead == pytest.approx(run_m + 3.5 * 600.0)
    for travelled in (0.0, run_m):                      # the first and the last frame
        along = ahead - travelled + C172_CHASE_BACK_M
        bearing = math.degrees(math.atan2(abeam, along))
        depression = math.degrees(math.atan2(600.0, along))
        assert bearing < CHASE_HALF_WIDTH_DEG * 0.5, (travelled, bearing)
        assert depression < CHASE_HALF_HEIGHT_DEG + CHASE_PITCH_DOWN_DEG, (travelled, depression)
    # Round 4's placement, for the record: outside the frame.
    old = math.degrees(math.atan2(375.0, 0.45 * run_m + C172_CHASE_BACK_M))
    assert old > 2 * CHASE_HALF_WIDTH_DEG
    # The wind the aircraft feels at the end of the clip: the Rankine exterior.
    r_end = math.hypot(ahead - run_m, abeam)
    assert tornado.V_MAX_MPS * tornado.R_CORE_M / r_end < 5.0


def test_the_placement_rule_keeps_core_and_stated_distances():
    run_m = 1000.0
    assert tornado.abeam_placement("core", run_m, 600.0) == (pytest.approx(450.0), 0.0)
    assert tornado.abeam_placement("core", run_m, 600.0, 3000.0) == (3000.0, 0.0)
    assert tornado.abeam_placement("abeam", run_m, 600.0, 2000.0) == (2000.0, 375.0)
    # The standoff floor: a low pass still gets 1.5 km.
    assert tornado.abeam_placement("abeam", run_m, 100.0)[0] == pytest.approx(run_m + 1500.0)
    assert tornado.FRAME_AHEAD_MIN_M == 1500.0 and tornado.FRAME_AHEAD_PER_AGL == 3.5


def test_the_web_app_and_the_runner_place_the_axis_by_the_one_rule():
    from core.nl.compiler import compile_prompt
    from webapp.runs import tornado_axis

    spec = compile_prompt("fly the c172p near a tornado at 600 m, heading 90, for 6 seconds")
    assert spec.weather_event.detail["aim"] == "abeam"
    seconds = float(spec.duration.value)
    run_m = float(spec.airspeed.value) * 1852.0 / 3600.0 * seconds
    agl = float(spec.altitude.value) - float(spec.terrain_elevation.value or 0.0)
    ahead, abeam = tornado.abeam_placement("abeam", run_m, agl)
    north, east = tornado_axis(spec, {}, seconds)
    hdg = math.radians(float(spec.heading.value))
    assert north == pytest.approx(ahead * math.cos(hdg) + abeam * math.cos(hdg + math.pi / 2))
    assert east == pytest.approx(ahead * math.sin(hdg) + abeam * math.sin(hdg + math.pi / 2))
    # The headless runner builds its TornadoVortex from the same function.
    assert "abeam_placement(" in RUNNER_PY and "abeam_placement(" in RUNS_PY
    assert "2.5 * R_CORE_M" not in RUNNER_PY and "2.5 * R_CORE_M" not in RUNS_PY

    through = compile_prompt("fly the c172p through a tornado at 600 m for 6 seconds")
    assert through.weather_event.detail["aim"] == "core"
    n, e = tornado_axis(through, {}, 6.0)
    assert math.hypot(n, e) == pytest.approx(0.45 * float(through.airspeed.value) * 1852.0 / 3600.0 * 6.0)


# -- #10: the funnel and its wall cloud ---------------------------------------------


def test_the_funnel_stops_at_a_wall_cloud_that_turns_at_the_exterior_rate():
    block = SCENARIO_CPP[SCENARIO_CPP.index("// -- tornado funnel marker"):SCENARIO_CPP.index("// -- the aircraft")]
    assert _cpp_constant(block, "TornadoFunnelTopShare") == weather_look.FUNNEL_TOP_SHARE == 0.6
    assert _cpp_constant(block, "TornadoFunnelTopRadii") == weather_look.FUNNEL_TOP_RADII
    assert _cpp_constant(block, "TornadoWallTopShare") == weather_look.WALL_TOP_SHARE == 0.9
    assert _cpp_constant(block, "TornadoWallRadii") == weather_look.WALL_RADII == 4.5
    # The condensation funnel reaches FunnelTopMetres, not the wind model's top.
    assert "const double FunnelTopMetres = TornadoFunnelTopShare * Card.TornadoTopMetres;" in block
    assert "AddRing(Radius, F * FunnelTopMetres, 0.35 * RCore * F," in block
    assert "AddRing(Radius, F * Card.TornadoTopMetres" not in block
    # Two markers, two actors, the wall cloud at omega / radii^2.
    assert 'SpawnMarker(TEXT("TornadoFunnel"))' in block
    assert 'SpawnMarker(TEXT("TornadoWallCloud"))' in block
    assert "TornadoWallOmegaDegPerSec = TornadoOmegaDegPerSec\n\t\t\t/ (TornadoWallRadii * TornadoWallRadii);" in block
    assert weather_look.wall_cloud_omega_scale() == pytest.approx(1.0 / 4.5 ** 2)
    assert "AActor* TornadoWallCloud = nullptr;" in SCENARIO_H
    assert "double TornadoWallOmegaDegPerSec = 0.0;" in SCENARIO_H
    # Spun from SIM time beside the funnel (replay-identical).
    step = SCENARIO_CPP[SCENARIO_CPP.index("if (TornadoFunnel != nullptr)"):]
    assert "TornadoWallCloud->SetActorRotation(FRotator(" in step[:1200]
    assert "TimeSeconds * TornadoWallOmegaDegPerSec" in step[:1200]
    # The wall cloud's lens: widest at WallRadii, closed over the top.
    assert "{0.35, TornadoWallRadii, 1.0}," in block and "{1.06, 0.4, 0.3}," in block


def test_the_beauty_dresses_both_markers_in_the_funnel_material():
    beauty = _function(LOOK_CPP, "void FFlightSimVisualScene::ApplyBeautyWeatherLook(")
    assert 'LookWallCloudComponentName = TEXT("TornadoWallCloud")' in LOOK_CPP
    assert 'Dress(Funnel, TEXT("tornado_funnel"),' in beauty
    assert 'Dress(WallCloud, TEXT("tornado_wall_cloud"),' in beauty
    assert "Mesh->SetMaterial(0, Instance);" in beauty
    colour = tuple(float(v) for v in re.findall(r"LookBeautyWallCloudColour[RGB] = ([0-9.]+)f;", LOOK_CPP))
    assert colour == weather_look.BEAUTY_WALL_CLOUD_COLOUR
    assert max(colour) < min(weather_look.BEAUTY_FUNNEL_COLOUR)       # darker than the funnel


def test_the_funnel_material_streaks_spin_with_the_mesh_and_scroll():
    assert _assigned("WEATHER_LOOK_GENERATIONS")["M_TornadoFunnel"] >= "2"
    funnel = SCRIPT[SCRIPT.index("def create_tornado_funnel"):SCRIPT.index("def create_lightning():")]
    body = funnel.split('"""', 2)[2]
    assert "MaterialExpressionTransformPosition" in body
    assert "TRANSFORMPOSSOURCE_WORLD" in body and "TRANSFORMPOSSOURCE_LOCAL" in body
    assert "MaterialExpressionTime" in body
    assert "FUNNEL_STREAK_SCROLL_CM_PER_S / 30.0" in body         # the scroll in the stretched units
    assert "FUNNEL_SKIRT_HEIGHT_CM" in body and "FUNNEL_SKIRT_TINT" in body
    # Still opaque, no WPO, no vertex colour: the labels' silhouettes are the beauty's.
    assert "VertexColor" not in body and "BLEND_TRANSLUCENT" not in body
    assert "WORLD_POSITION_OFFSET" not in body
    assert _assigned("FUNNEL_STREAK_SCROLL_CM_PER_S") > 0.0


# -- #10: the deck shadows the beam -------------------------------------------------


def test_the_deck_shadows_the_beam_under_a_drawn_deck_only():
    assert world_beauty.deck_shadows_beam("storm", [1.0]) is True
    assert world_beauty.deck_shadows_beam("rain", [0.5]) is True
    assert world_beauty.deck_shadows_beam("overcast", [0.9]) is True
    assert world_beauty.deck_shadows_beam("storm", [0.2]) is False
    assert world_beauty.deck_shadows_beam("storm", []) is False
    assert world_beauty.deck_shadows_beam("clear", [1.0]) is False
    assert world_beauty.deck_shadows_beam("hazy", [1.0]) is False
    assert world_beauty.DECK_SHADOW_PRESETS == ("storm", "rain", "overcast")


def test_the_cpp_deck_shadow_is_the_pythons_and_switchable():
    pure = CLOUDS_CPP[CLOUDS_CPP.index("FLIGHTSIM-WORLD-PURE-BEGIN"):CLOUDS_CPP.index("FLIGHTSIM-WORLD-PURE-END")]
    assert _cpp_constant(pure, "DeckShadowMinCover") == world_beauty.DECK_SHADOW_MIN_COVER
    law = _function(pure, "inline bool DeckShadowsBeam(int Preset, double Cover)")
    for preset in world_beauty.DECK_SHADOW_PRESETS:
        assert f"Preset == Preset{preset.capitalize()}" in law
    assert "Preset == PresetClear" not in law and "Preset == PresetHazy" not in law
    apply = _function(CLOUDS_CPP, "void FFlightSimWorldBeauty::ApplyClouds(")
    assert "const bool bWanted = DeckShadowsBeam(Preset, TopCover);" in apply
    assert "TopCover = FMath::Max(TopCover, State.Cover);" in apply
    assert "if (bWanted && bSwitchOn)\n\t\t\t{\n\t\t\t\tDeckSun->bCastCloudShadows = true;" in apply
    assert 'Out->SetObjectField(TEXT("deck_shadow"), DeckShadow);' in apply
    # The switch: the command line or FLIGHTSIM_RENDER_SWITCHES, default on.
    build = _function(CLOUDS_CPP, "bool FFlightSimWorldBeauty::Build(")
    assert 'FParse::Value(*Switches, TEXT("deck-shadow="), DeckShadowSwitch);' in build
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in build
    assert 'FString DeckShadowSwitch = TEXT("on");' in CLOUDS_H
    assert 'const bool bSwitchOn = DeckShadowSwitch != TEXT("off");' in apply
    # Beauty only: FFlightSimWorldBeauty is the -quality=beauty world look.
    assert CLOUDS_CPP.count("DeckSun->bCastCloudShadows = true;") == 1


# -- #09: the rain shaft ------------------------------------------------------------


def _cell():
    return storm_cell.card_block(900.0, 40.0, 200.0, 270.0, 8.0, None, 42)


def test_the_beauty_shaft_is_structured_inside_the_measure_shaft_only():
    cell = _cell()
    base = float(cell["base_m"])
    shaft_r = float(cell["shaft"]["radius_m"])
    sigma_shaft = float(cell["shaft"]["extinction_per_m"])
    measure = [storm_cell.extinction_at(cell, e, n, u) for e, n, u in _shaft_points(shaft_r, base)]
    beauty = [storm_cell.extinction_at(cell, e, n, u, ragged=storm_cell.BEAUTY_RAGGED)
              for e, n, u in _shaft_points(shaft_r, base)]
    assert any(m != b for m, b in zip(measure, beauty))          # the beauty differs inside
    for (e, n, u), m, b in zip(_shaft_points(shaft_r, base), measure, beauty):
        assert 0.0 <= b <= sigma_shaft + 1e-12
        if math.hypot(e, n) >= shaft_r:                          # never wider than the measure's
            assert m == 0.0 and b == 0.0
    # More structure: inside the core of the shaft the beauty's relative spread
    # (std / mean) is wider than the measure's, and its peak is no higher.
    inside = [k for k, (e, n, _) in enumerate(_shaft_points(shaft_r, base)) if math.hypot(e, n) < 0.6 * shaft_r]

    def spread(values):
        mean = sum(values) / len(values)
        return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) / mean

    assert spread([beauty[k] for k in inside]) > spread([measure[k] for k in inside])
    assert max(beauty) <= max(measure)
    # The measure path is the one before: the density law and its floor.
    assert "float shaft = S.Ss(shaftR, shaftR * 0.6, r)" in STORM_HLSL
    assert ": shaft * (0.6 + 0.4 * curtain);" in STORM_HLSL


def _shaft_points(shaft_r, base):
    out = []
    for k in range(24):
        angle = 2.0 * math.pi * k / 24.0
        for share in (0.0, 0.3, 0.55, 0.8, 0.95, 1.05):
            out.append((share * shaft_r * math.cos(angle), share * shaft_r * math.sin(angle),
                        base * (0.2 + 0.6 * (k % 5) / 4.0)))
    return out


def test_the_shaft_shader_block_is_the_pythons_constant_for_constant():
    shaft = storm_cell.BEAUTY_SHAFT
    assert f"float across = Ragged.x > 0.0 ? billow * {shaft['streak_scale']} : billow;" in STORM_HLSL
    assert (f"? S.Eroded(shaft, curtain, {shaft['rim_erosion']}) * "
            f"({shaft['density_floor']} + {1.0 - shaft['density_floor']} * curtain)") in STORM_HLSL
    assert "u / (billow * 8.0)" in STORM_HLSL                     # the vertical stretch kept
    assert "+ Sigma.z * shaftDensity;" in STORM_HLSL
    # The one curtain fbm is still gated by the measure shaft (no new samples).
    assert STORM_HLSL.count("S.Fbm(float3(e / across, n / across") == 1
    assert "(shaft > 0.0) ? S.Fbm(float3(e / across" in STORM_HLSL


def test_the_shaft_albedo_is_grey_in_beauty_and_the_measures_by_default():
    cell = _cell()
    base = float(cell["base_m"])
    shaft_r = float(cell["shaft"]["radius_m"])
    scale = storm_cell.BEAUTY_SHAFT["albedo_scale"]
    assert storm_cell.shaft_albedo_scale(cell, 0.0, 0.0, base * 0.5) == 1.0            # default 1: exactly 1
    assert storm_cell.shaft_albedo_scale(cell, 0.0, 0.0, base * 0.5, scale) == pytest.approx(scale)
    assert storm_cell.shaft_albedo_scale(cell, shaft_r * 1.1, 0.0, base * 0.5, scale) == 1.0
    assert storm_cell.shaft_albedo_scale(cell, 0.0, 0.0, base + 300.0, scale) == 1.0    # above the base
    mid = storm_cell.shaft_albedo_scale(cell, shaft_r * 0.8, 0.0, base * 0.5, scale)
    assert scale < mid < 1.0                                                            # the rim fades
    # The HLSL: the early exact return, the shaft's own smoothsteps, the lerp.
    assert "if (ShaftAlbedo >= 1.0)\n{\n\treturn 1.0;\n}" in ALBEDO_HLSL
    assert "A.Ss(shaftR, shaftR * 0.6, r) * A.Ss(Geo1.x + Edge * 0.5, Geo1.x - Edge * 0.5, u)" in ALBEDO_HLSL
    assert "return 1.0 + shape * (ShaftAlbedo - 1.0);" in ALBEDO_HLSL
    assert "const float Edge = 250.0;" in ALBEDO_HLSL and storm_cell.EDGE_M == 250.0


def test_the_storm_material_exposes_the_shaft_albedo_and_is_rebuilt():
    assert "ShaftAlbedo" in _assigned("STORM_PARAMETERS")
    assert _assigned("STORM_SCALAR_DEFAULTS") == {"ExtinctionScale": 1.0, "ShaftAlbedo": 1.0}
    assert _assigned("STORM_GENERATIONS")["M_StormCell"] >= "5"
    storm = SCRIPT[SCRIPT.index("def create_storm_cell"):SCRIPT.index("def create_windshield_rain")]
    assert 'custom(material, lib, "storm_shaft_albedo"' in storm
    assert "MaterialExpressionMultiply, albedo, shaft_albedo" in storm
    assert "ShaftAlbedo" not in _assigned("WEATHER_FLOAT4_PARAMETERS")       # a scalar
    # The C++ sets it in beauty only, at the Python's value, recorded.
    apply = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyStormVantage(")
    shaft = storm_cell.BEAUTY_SHAFT
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyShaftAlbedo") == shaft["albedo_scale"]
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyShaftStreakScale") == shaft["streak_scale"]
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyShaftRimErosion") == shaft["rim_erosion"]
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyShaftDensityFloor") == shaft["density_floor"]
    assert 'StormMaterial->SetScalarParameterValue(TEXT("ShaftAlbedo")' in apply
    assert WEATHER_CPP.count('TEXT("ShaftAlbedo")') == 1
    assert 'Row->SetObjectField(TEXT("shaft"), Shaft);' in apply


def test_the_round6_engine_symbols_are_in_the_bridge_check():
    block = CHECK[CHECK.index("BEGIN round6"):CHECK.index("END round6")]
    for needle in ("SetActorRotation(FRotator NewRotation", "bCastCloudShadows : 1;",
                   "GetEnvironmentVariable(const TCHAR* VariableName)",
                   "class UMaterialExpressionTransformPosition", "TRANSFORMPOSSOURCE_World",
                   "class UMaterialExpressionTime"):
        assert needle in block, needle
