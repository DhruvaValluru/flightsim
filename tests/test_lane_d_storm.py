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
    """The volumetric scud band's law (off in beauty since round 19: its slices drew
    rings in #09; tested at a stated depth so the shader term stays honest)."""
    assert storm_cell.BEAUTY_CURTAIN["scud_depth_m"] == 0.0
    cell = _cell()
    curtain = dict(storm_cell.BEAUTY_CURTAIN, scud_depth_m=300.0)
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


# -- the rain veil: the curtain at depth and the scud ---------------------------------

from core.scene import rain_veil  # noqa: E402

WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"


def test_the_veil_follows_the_rain_and_layers_the_depth():
    # visibility (Koschmieder 3.912 / beta) of the order of heavy and tropical rain
    assert 1.5 < 3.912 / rain_veil.rain_extinction_per_km(10.0) < 4.0
    assert 0.6 < 3.912 / rain_veil.rain_extinction_per_km(40.0) < 1.5
    assert rain_veil.rain_extinction_per_km(0.0) == 0.0
    veils = [rain_veil.shell_veil_alpha(40.0, i) for i in range(3)]
    assert veils == sorted(veils) and veils[-1] < 0.6   # deeper slabs veil more; never a wall
    # the near shell (inside a chase camera's 40-60 m) barely veils the subject
    assert rain_veil.shell_veil_alpha(10.0, 0) < 0.06
    assert rain_veil.streak_density(10.0) < rain_veil.streak_density(40.0) <= rain_veil.VEIL_STREAK_DENSITY_MAX
    assert not rain_veil.scud_drawn(4.0, False) and rain_veil.scud_drawn(10.0, False)
    assert rain_veil.scud_drawn(0.0, True)


def test_the_scud_cards_are_deterministic_carried_by_the_wind_and_clear_of_the_lens():
    band = rain_veil.scud_band(2000.0, 2500.0)
    assert band == (1700.0, 2450.0)
    assert rain_veil.scud_band(2000.0, None) == (1700.0, 2400.0)
    assert rain_veil.scud_band(2000.0, 1500.0) == (1700.0, 2400.0)   # a deck below: not its base
    camera = (0.0, 0.0, 2000.0)
    a = rain_veil.scud_cards(3, 2.0, camera, camera, (0.0, -12.86), band)
    b = rain_veil.scud_cards(3, 2.0, camera, camera, (0.0, -12.86), band)
    assert a == b and len(a) == rain_veil.SCUD_CARDS
    assert tuple(a[0]) == rain_veil.CARD_KEYS
    for card in a:
        assert band[0] <= card["up_m"] <= band[1]
        assert abs(card["east_m"]) <= rain_veil.SCUD_BOX_HALF_M
        d = math.dist((card["east_m"], card["north_m"], card["up_m"]), camera)
        if d < rain_veil.SCUD_CAMERA_CLEAR_M + 0.5 * card["width_m"]:
            assert card["alpha"] == 0.0
    # one second later every card's air has moved 12.86 m south (unless it wrapped)
    c = rain_veil.scud_card(3, 5, 3.0, camera, camera, (0.0, -12.86), band)
    d0 = rain_veil.scud_card(3, 5, 2.0, camera, camera, (0.0, -12.86), band)
    assert c["north_m"] == pytest.approx(d0["north_m"] - 12.86) or abs(c["north_m"] - d0["north_m"]) > 4000


def _veil_cpp():
    start = WEATHER_CPP.index("namespace FlightSimRainVeil")
    return WEATHER_CPP[start:WEATHER_CPP.index("// -- visual round 2 (weather scenes", start)]


def test_the_cpp_veil_carries_the_python_numbers():
    veil = _veil_cpp()
    pairs = {"VeilShellRadiusNearM": rain_veil.VEIL_SHELL_RADII_M[0],
             "VeilShellRadiusMidM": rain_veil.VEIL_SHELL_RADII_M[1],
             "VeilShellRadiusFarM": rain_veil.VEIL_SHELL_RADII_M[2],
             "VeilHeightRadii": rain_veil.VEIL_HEIGHT_RADII, "VeilBetaA": rain_veil.VEIL_BETA_A,
             "VeilBetaB": rain_veil.VEIL_BETA_B, "VeilStreakPixels": rain_veil.VEIL_STREAK_PIXELS,
             "VeilShadeUnderDeck": rain_veil.VEIL_SHADE_UNDER_DECK, "VeilShadeOpen": rain_veil.VEIL_SHADE_OPEN,
             "VeilStreakDensityA": rain_veil.VEIL_STREAK_DENSITY_A,
             "VeilStreakDensityMax": rain_veil.VEIL_STREAK_DENSITY_MAX,
             "VeilStreakAlpha": rain_veil.VEIL_STREAK_ALPHA, "ScudBoxHalfM": rain_veil.SCUD_BOX_HALF_M,
             "ScudBandBelowM": rain_veil.SCUD_BAND_BELOW_M, "ScudDeckGapM": rain_veil.SCUD_DECK_GAP_M,
             "ScudNoDeckTopM": rain_veil.SCUD_NO_DECK_TOP_M, "ScudWidthMinM": rain_veil.SCUD_WIDTH_M[0],
             "ScudWidthMaxM": rain_veil.SCUD_WIDTH_M[1], "ScudAspectMin": rain_veil.SCUD_ASPECT[0],
             "ScudAspectMax": rain_veil.SCUD_ASPECT[1], "ScudAlphaMin": rain_veil.SCUD_ALPHA[0],
             "ScudAlphaMax": rain_veil.SCUD_ALPHA[1], "ScudCameraClearM": rain_veil.SCUD_CAMERA_CLEAR_M,
             "ScudEdgeShare": rain_veil.SCUD_EDGE_SHARE, "ScudMinRainMmh": rain_veil.SCUD_MIN_RAIN_MMH}
    for name, value in pairs.items():
        assert _cpp_constant(veil, name) == value, name
    assert f"constexpr int32 VeilSegments = {rain_veil.VEIL_SEGMENTS};" in veil
    assert f"constexpr int32 ScudCards = {rain_veil.SCUD_CARDS};" in veil
    assert f"constexpr uint64 ScudSeedSalt = 0x{rain_veil.SCUD_SEED_SALT:X};" in veil
    # the same channels of the same hash, card for card
    for channel in range(7):
        assert f"Unit(ScudSeed, Index, {channel})" in veil, channel
    assert "Smooth(Clear, Clear * 1.5, ToCameraM)" in veil
    assert "WindEnuMps.X * T" in veil and "WindEnuMps.Y * T" in veil
    shader = (SHADERS / "rain_curtain.hlsl").read_text(encoding="utf-8")
    assert "float cellL = cellW * 60.0;" in shader and rain_veil.VEIL_STREAK_ASPECT == 60.0


def test_the_veil_is_beauty_only_and_hidden_from_every_label():
    veil = _veil_cpp()
    assert veil.count("BeautyOnlyActors.Add(VeilActor);") == 1
    assert veil.count("BeautyOnlyActors.Add(ScudActor);") == 1
    assert "bool ApplyBeautyRainVeil(UWorld* World" in WEATHER_H
    # its one caller is the beauty world look (built only under -quality=beauty)
    assert CLOUDS_CPP.count("Weather.ApplyBeautyRainVeil(") == 1
    build = CLOUDS_CPP[CLOUDS_CPP.index("bool FFlightSimWorldBeauty::Build("):]
    assert "Weather.ApplyBeautyRainVeil(" in build
    assert 'FlagOrEnv(TEXT("rain-veil="), TEXT("FLIGHTSIM_RAIN_VEIL"))' in CLOUDS_CPP
    # per frame: nothing unless the beauty built it
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::StepBeautyRainVeil(")
    assert "if (VeilActor != nullptr)" in advance and "if (ScudMesh == nullptr)" in advance
    assert WEATHER_CPP.count("StepBeautyRainVeil(View, Wind, CameraVelocity, Share, PixelAngle);") == 1
    # the materials exist in the script, stamped, with their shader inputs
    assert '"M_RainCurtain": "6"' in SCRIPT and '"M_ScudCard": "3"' in SCRIPT
    assert 'custom(material, lib, "rain_curtain"' in SCRIPT and 'custom(material, lib, "scud_card"' in SCRIPT
    assert "create_rain_curtain()" in SCRIPT and "create_scud_card()" in SCRIPT


# -- the windscreen water film (the pinned CC0 asset) ---------------------------------


def test_the_water_film_is_pinned_listed_and_a_no_op_off_the_beauty_path():
    import importlib.util

    spec = importlib.util.spec_from_file_location("fetch_weather_textures",
                                                  REPO / "scripts" / "fetch_weather_textures.py")
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    listing = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    for name, pin in fetch.PINS.items():
        assert pin["licence"] == "CC0-1.0"
        assert re.fullmatch(r"[0-9a-f]{64}", pin["zip_sha256"]) and pin["zip_sha256"] in listing
        assert pin["zip_url"] in listing and pin["page"] in listing
        assert pin["zip_bytes"] < 4_000_000                          # small
        for member in pin["members"].values():
            assert re.fullmatch(r"[0-9a-f]{64}", member["sha256"]) and member["sha256"] in listing
            assert member["bytes"] < 500_000
    # the material reads exactly the fetched files
    files = SCRIPT[SCRIPT.index("WINDSHIELD_FILM_FILES = "):SCRIPT.index("WINDSHIELD_FILM_TILES")]
    for file in fetch.PINS["leaking019c"]["members"]:
        assert f"data/textures/weather/leaking019c/{file}" in files
    assert '"M_WindshieldRain": "3"' in SCRIPT
    film = (SHADERS / "windshield_film.hlsl").read_text(encoding="utf-8")
    assert "if (Film <= 0.0)\n{\n\treturn Drops;\n}" in film
    # Film is set only from the beauty veil's value (0 until ApplyBeautyRainVeil runs)
    assert "BeautyFilm = FlightSimRainVeil::BeautyWindshieldFilm;" in WEATHER_CPP
    assert WEATHER_CPP.count("BeautyFilm = ") == 1
    assert "double BeautyFilm = 0.0;" in WEATHER_H
    assert _cpp_constant(WEATHER_CPP, "BeautyWindshieldFilm") == rain_veil.BEAUTY_WINDSHIELD_FILM


# -- round 6's #15: the rain's own haze up to the camera ------------------------------


def test_the_storm_rain_haze_reaches_the_camera_and_never_thins_the_fog():
    # the engine's 0.2 falloff halves the fog every 50 m: nothing left at 2 km
    haze = rain_veil.rain_haze_fog(10.0, 2000.0, 2400.0, 0.012, 0.2)
    assert haze["falloff"] == pytest.approx(10.0 / 2400.0)
    at_camera = haze["density"] * 2.0 ** (-haze["falloff"] / 10.0 * 2000.0) * rain_veil.FOG_BETA_PER_DENSITY
    assert at_camera * 1000.0 == pytest.approx(rain_veil.rain_extinction_per_km(10.0))
    # never thinner, never a steeper falloff than the scene's own fog
    thick = rain_veil.rain_haze_fog(10.0, 2000.0, 2400.0, 5.0, 0.001)
    assert thick == {"density": 5.0, "falloff": 0.001}
    # a deck 300 m up is taken as a 1 km column
    assert rain_veil.rain_haze_fog(10.0, 0.0, 300.0, 0.0, 0.2)["falloff"] == pytest.approx(0.01)


def test_the_cpp_rain_haze_is_the_pythons_and_storm_only():
    body = _function(WEATHER_CPP, "void FFlightSimWeather::RainHazeFog(")
    assert _cpp_constant(body, "RainHazeFogBetaPerDensity") == pytest.approx(rain_veil.FOG_BETA_PER_DENSITY)
    assert _cpp_constant(body, "RainHazeFalloffColumn") == rain_veil.RAIN_HAZE_FALLOFF_COLUMN
    assert _cpp_constant(body, "RainHazeMinColumnM") == rain_veil.RAIN_HAZE_MIN_COLUMN_M
    assert "OutDensity = FMath::Max(FogDensity, Density);" in body
    assert "const bool bHaze = Preset == PresetStorm && HazeRate > 0.0 && VisibilityKm <= 0.0 &&" in CLOUDS_CPP
    assert CLOUDS_CPP.count("FFlightSimWeather::RainHazeFog(") == 1
    assert 'Record->SetObjectField(TEXT("rain_haze"), Haze);' in CLOUDS_CPP


# -- round 12's #15 and round 9's #07 -------------------------------------------------


def test_round12_the_streaks_slant_and_keep_their_screen_size_at_every_lens():
    # the cinematic style keeps a share of the camera's motion on the beauty path only
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::Advance(")
    assert "CameraVelocity = CameraVelocity * BeautyCameraShare;" in advance
    assert "double BeautyCameraShare = 0.0;" in WEATHER_H
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    assert "BeautyCameraShare = FlightSimRainVeil::BeautyCameraMotionShare;" in readability
    assert WEATHER_CPP.count("BeautyCameraShare = ") == 1
    assert _cpp_constant(WEATHER_CPP, "BeautyCameraMotionShare") == rain_veil.BEAUTY_CAMERA_MOTION_SHARE
    assert _cpp_constant(WEATHER_CPP, "BeautyReferencePixelRad") == pytest.approx(
        rain_veil.BEAUTY_REFERENCE_PIXEL_RAD, rel=1e-12)
    # the cap shrinks with a long lens and holds at a wide one
    ref = rain_veil.BEAUTY_REFERENCE_PIXEL_RAD
    assert rain_veil.streak_cap_rad(0.045, ref / 7.0) == pytest.approx(0.045 / 7.0)
    assert rain_veil.streak_cap_rad(0.045, ref * 2.0) == 0.045
    assert "BeautyMaxStreakRad * FMath::Min(1.0, PixelAngle / FlightSimRainVeil::BeautyReferencePixelRad)" \
        in advance
    # the curtain: the shell's surface frame, pixel-wide streaks, the beauty's streak path
    shader = (SHADERS / "rain_curtain.hlsl").read_text(encoding="utf-8")
    assert "float arc = atan2(Rel.y, Rel.x) * Radius;" in shader
    assert "float2 v2 = float2(dot(fallVel.xy, tangent), fallVel.z);" in shader
    assert "cross(dir, float3(0.0, 0.0, 1.0))" not in shader     # the world-fixed frame is gone
    step = _function(WEATHER_CPP, "void FFlightSimWeather::StepBeautyRainVeil(")
    assert 'TEXT("StreakRad"), static_cast<float>(VeilStreakPixels * PixelAngle)' in step
    assert 'WeatherColour(Wind - CamVel)' in step


def test_round12_the_veil_and_scud_are_shaded_and_torn():
    assert rain_veil.veil_shade(True) == rain_veil.VEIL_SHADE_UNDER_DECK < rain_veil.veil_shade(False) <= 1.0
    veil = _veil_cpp()
    assert "VeilShade = bDeck && DeckBaseM > AircraftUpM ? VeilShadeUnderDeck : VeilShadeOpen;" in WEATHER_CPP
    assert 'ScudMaterial->SetScalarParameterValue(TEXT("Shade")' in WEATHER_CPP
    assert 'Material->SetScalarParameterValue(TEXT("Shade")' in WEATHER_CPP
    assert 'shade = scalar(material, lib, "Shade", 1.0' in SCRIPT
    assert '"M_RainCurtain": "6"' in SCRIPT and '"M_ScudCard": "3"' in SCRIPT
    scud = (SHADERS / "scud_card.hlsl").read_text(encoding="utf-8")
    assert "float tear = S.Value(" in scud and "S.Ss(0.55, 0.68," in scud
    assert "0.55 * falloff" not in scud                            # the falloff no longer makes the shape
    assert veil


def test_round12_the_storm_fog_is_lit_by_the_deck_not_the_clear_sky():
    # round 26: under ANY storm deck (rain or not: #10's tornado), not only with rain haze
    deck = CLOUDS_CPP[CLOUDS_CPP.index("const bool bDeckLight = "):]
    deck = deck[:deck.index('Record->SetObjectField(TEXT("storm_deck_light"), DeckLight);')]
    assert "const bool bDeckLight = Preset == PresetStorm && bDeckAbove && RainVeilMode == TEXT(\"on\");" \
        in CLOUDS_CPP
    r, g, b = rain_veil.STORM_FOG_AMBIENT_RGB
    assert (r, g, b) == (0.0, 0.0, 0.0)                     # round 36: the green ambient off
    assert "const FLinearColor Ambient(0.0f, 0.0f, 0.0f);" in deck
    assert f"constexpr float StormFogInscatterNits = {rain_veil.STORM_FOG_INSCATTER_NITS:.1f}f;" in deck
    assert "Fog->SetFogInscatteringColor(Inscatter);" in deck   # neutral: equal channels
    assert "Fog->SetSkyAtmosphereAmbientContributionColorScale(Ambient);" in deck
    assert "Fog->SetDirectionalInscatteringColor(FLinearColor::Black);" in deck
    assert f"constexpr double StormSunFogShare = {rain_veil.STORM_SUN_FOG_SHARE};" in deck
    # the green: the captured sky light's lower hemisphere (the tiles) made solid and dark
    assert "DeckSky->bLowerHemisphereIsBlack = true;" in deck
    assert "if (DeckSky != nullptr && !DeckSky->bLowerHemisphereIsBlack)" in deck   # the hero sidecar wins
    haze = CLOUDS_CPP[CLOUDS_CPP.index("const bool bHaze = Preset == PresetStorm"):]
    haze = haze[:haze.index('Record->SetObjectField(TEXT("rain_haze"), Haze);')]
    assert "SetSkyAtmosphereAmbientContributionColorScale" not in haze


# -- round 19: dark rags, no arcs ------------------------------------------------------


def test_round19_the_scud_is_a_modulate_rag_darker_than_what_is_behind_it():
    creator = SCRIPT[SCRIPT.index("def create_scud_card"):SCRIPT.index("def create_rain_splash")]
    assert "_translucent_unlit(material, unreal.BlendMode.BLEND_MODULATE)" in creator
    assert "_translucent_lit(material)" not in creator and "_veil_lit(" not in creator
    assert "MP_EMISSIVE_COLOR" in creator and "MP_OPACITY" not in creator
    assert 'tone = scalar(material, lib, "Shade", 1.0' in creator
    assert 0.0 < rain_veil.scud_tone(True) < rain_veil.scud_tone(False) < 1.0
    for cpp, py in (("ScudToneUnderDeck", rain_veil.SCUD_TONE_UNDER_DECK),
                    ("ScudToneOpen", rain_veil.SCUD_TONE_OPEN)):
        assert _cpp_constant(_veil_cpp(), cpp) == py, cpp
    assert 'ScudMaterial->SetScalarParameterValue(TEXT("Shade"), static_cast<float>(ScudTone));' in WEATHER_CPP


def test_round19_the_volumetric_scud_band_is_off_in_beauty():
    apply = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyStormVantage(")
    assert _cpp_constant(apply, "WeatherBeautyScudDepthM") == storm_cell.BEAUTY_CURTAIN["scud_depth_m"] == 0.0
    assert "if (Curtain.z > 0.0)" in STORM_HLSL     # the term is skipped, not evaluated



# -- round 26: a low full deck, falling curtains, the green ---------------------------


def test_round26_the_storm_deck_hangs_low_over_the_aircraft():
    assert wb.deck_clearance_m("storm") == wb.STORM_DECK_CLEARANCE_M < wb.AIRCRAFT_LAYER_CLEARANCE_M
    assert wb.deck_clearance_m("rain") == wb.AIRCRAFT_LAYER_CLEARANCE_M
    out = wb.aircraft_clear_layer(1500.0, 2700.0, 2000.0, wb.deck_clearance_m("storm"), True)
    assert out["base_m"] == 2000.0 + wb.STORM_DECK_CLEARANCE_M and out["above"]
    assert f"constexpr double StormDeckClearanceM = {wb.STORM_DECK_CLEARANCE_M};" in CLOUDS_CPP
    assert "Preset == PresetStorm ? StormDeckClearanceM : AircraftLayerClearanceM, bRainDeck);" in CLOUDS_CPP
    # the cell's deck (#09) keeps the wide clearance
    assert "AircraftClearLayer(LayerBaseM, LayerTopM, AircraftUpM, AircraftLayerClearanceM, true)" in CLOUDS_CPP


def test_round26_the_veil_carries_falling_curtains():
    shader = (SHADERS / "rain_curtain.hlsl").read_text(encoding="utf-8")
    assert "if (VeilVary > 0.0)" in shader
    assert "veil = saturate(Veil * (1.0 + VeilVary * (2.0 * n - 1.0)));" in shader
    assert '"VeilVary": params["VeilVary"]' in SCRIPT
    assert _cpp_constant(_veil_cpp(), "VeilVary") == rain_veil.VEIL_VARY
    assert _cpp_constant(_veil_cpp(), "VeilShadeOpen") == rain_veil.VEIL_SHADE_OPEN


def test_round26_the_veil_is_neutral_grey_at_any_light():
    """r31/r32: #10's green was the rain veil's (a lit surface taking the sky light's
    green ground bounce). Generation 4: unlit, its colour the scene's local luminance."""
    creator = SCRIPT[SCRIPT.index("def create_rain_curtain"):SCRIPT.index("def create_scud_card")]
    assert "_translucent_unlit(material, unreal.BlendMode.BLEND_TRANSLUCENT)" in creator
    assert "_translucent_lit(" not in creator and "_veil_lit(" not in creator
    assert creator.count("unreal.MaterialExpressionSceneColor") == 1 and '"rgb"' in creator
    # round 36: ONE tap at the pixel's own UV -- no shifted copies of the scene (ghosts)
    assert 'tap.set_editor_property("const_input", unreal.Vector2D(0.0, 0.0))' in creator
    assert "VEIL_TAP" not in SCRIPT and "for i, (key, offset)" not in creator
    assert 'custom(material, lib, "veil_tone"' in creator and "MP_EMISSIVE_COLOR" in creator
    tone = (SHADERS / "veil_tone.hlsl").read_text(encoding="utf-8")
    assert "float lum = dot(A, float3(0.2126, 0.7152, 0.0722));" in tone
    assert "B" not in tone.split("float lum")[1]
    assert "return float3(lum, lum, lum) * Shade;" in tone          # grey: equal channels
    # the scud is a modulate rag of one scalar tone: neutral too
    scud = SCRIPT[SCRIPT.index("def create_scud_card"):SCRIPT.index("def create_rain_splash")]
    assert 'tone = scalar(material, lib, "Shade", 1.0' in scud
    assert rain_veil.VEIL_SHADE_UNDER_DECK < rain_veil.VEIL_SHADE_OPEN == 1.0


# -- round 47: #07's curtains shrink with a long lens ------------------------------


def test_round47_the_curtain_cells_scale_with_the_lens_and_hold_at_a_wide_one():
    ref = rain_veil.BEAUTY_REFERENCE_PIXEL_RAD
    assert rain_veil.veil_vary_scale(ref) == rain_veil.VEIL_VARY_SCALE_MAX == 1.0
    assert rain_veil.veil_vary_scale(ref * 2.0) == 1.0            # wider: generation 5's cells
    assert rain_veil.veil_vary_scale(ref / 7.0) == pytest.approx(1.0 / 7.0)
    assert rain_veil.veil_vary_scale(ref / 7.0, lens_cells=False) == 1.0   # the A/B
    assert rain_veil.veil_vary_scale(0.0) == 1.0
    # #07's 250 mm frame (8.2 deg across): a cell is a fifth of the radius x the scale
    # wide, so at 54 deg one cell is 11.3 deg (wider than the frame) and now several fit.
    hfov = 2.0 * math.atan(18.0 / 250.0)
    pixel = 2.0 * math.tan(hfov / 2.0) / 1280.0
    cell = math.atan(0.2 * rain_veil.veil_vary_scale(pixel))
    assert math.atan(0.2) > hfov and hfov / cell > 4.0


def test_round47_the_curtain_shader_cpp_and_script_carry_vary_scale():
    shader = (SHADERS / "rain_curtain.hlsl").read_text(encoding="utf-8")
    assert "float vs = VaryScale > 0.0 ? min(VaryScale, 1.0) : 1.0;" in shader
    assert "arc / (Radius * 0.2 * vs)" in shader and "/ (Radius * 0.8 * vs)" in shader
    assert '"VaryScale"' in SCRIPT and '"VaryScale": params["VaryScale"]' in SCRIPT
    assert 'weather_parameter(material, lib, "VaryScale", -1800, 760, default=1.0)' in SCRIPT
    assert '"M_RainCurtain": "6"' in SCRIPT
    assert _cpp_constant(_veil_cpp(), "VeilVaryScaleMax") == rain_veil.VEIL_VARY_SCALE_MAX
    scale = _function(WEATHER_CPP, "double FFlightSimWeather::VeilVaryScale(")
    assert "PixelAngle / FlightSimRainVeil::BeautyReferencePixelRad" in scale
    assert "if (!bLensCells || PixelAngle <= 0.0)" in scale
    step = _function(WEATHER_CPP, "void FFlightSimWeather::StepBeautyRainVeil(")
    assert 'TEXT("VaryScale")' in step and "VeilVaryScale(PixelAngle, bBeautyVeilLensCells)" in step
    # the A/B: the command line or FLIGHTSIM_RENDER_SWITCHES, refused unless on|off,
    # set before the veil is built, recorded
    build = CLOUDS_CPP[CLOUDS_CPP.index("bool FFlightSimWorldBeauty::Build("):]
    assert 'FParse::Value(*Switches, TEXT("veil-lens-cells="), VeilLensCellsSwitch);' in build
    assert build.index("Weather.SetBeautyVeilLensCells(") < build.index("Weather.ApplyBeautyRainVeil(")
    assert "-veil-lens-cells=%s is not on or off" in build
    assert 'TEXT("vary_lens_cells")' in WEATHER_CPP
    assert "void SetBeautyVeilLensCells(bool bOn)" in WEATHER_H
