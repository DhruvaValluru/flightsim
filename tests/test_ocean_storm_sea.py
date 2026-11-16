"""Hyperreal stormsea (2026-11-14): M_FlightSimOceanBeauty generation 5, BEAUTY ONLY.

The cause, in code: FlightSimGoogleTiles.cpp ApplyBeautyGround created the sea
cap's material instance and set only Wetness; nothing set WindSpeedMS, so the
material's 7 m/s default drew every sea and a storm over the ocean looked
calm. And the Monahan crest foam keys on the resolved wave texels, so wiring
the wind as it was would have drawn texel speckle near the camera and nothing
from altitude.

What is proved here, without the engine:
* the calm sea (#13: an unstated wind compiles to 0 kt, still air keeps the
  material's 7 m/s) is generation 4's to within 1e-9 in float64 -- the twin
  core/scene/ocean_storm_sea.py evaluates both generations' tails at the same
  inputs; every storm term is a product with smoothstep(8, 18, wind) = 0;
* the storm foam is filtered by pixel footprint and distance: a fine pixel
  draws streaks and patches whose mean cover is the shader's stated MEAN
  constants; a coarse or far pixel is given those means exactly (no speckle,
  no vanishing); the streaks run along the wind;
* the storm swell is resolved (gone at a coarse footprint), the body colour
  turns grey-green, the C++ feeds the card's wind to the cap's material
  instance only, and the material's generation stamp is bumped.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from core.scene import ocean_storm_sea as twin

REPO = Path(__file__).resolve().parents[1]
SHADERS = REPO / "assets" / "shaders" / "world"
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
TILES_CPP = (BRIDGE / "Private" / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
TILES_H = (BRIDGE / "Public" / "FlightSimGoogleTiles.h").read_text(encoding="utf-8")
COMMANDLET = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
K = twin.shader_constants()
WIND_DIR = np.array([0.6, 0.8])


def _samples(n=20000, seed=7):
    rng = np.random.default_rng(seed)
    pm3 = np.concatenate([rng.uniform(-30000.0, 30000.0, size=(n, 2)), np.zeros((n, 1))], -1)
    footprint = 10.0 ** rng.uniform(-1.0, 2.5, size=n)
    dist = 10.0 ** rng.uniform(1.0, 4.7, size=n)
    wave_tilt = rng.normal(0.0, 0.1, size=(n, 2))
    crest = np.abs(rng.normal(0.0, 1.0, size=n)) * 2.0
    return pm3, footprint, dist, wave_tilt, crest


# -- the calm sea is generation 4's ----------------------------------------------

@pytest.mark.parametrize("wind_ms", [7.0, 0.0, 3.0, 8.0])
def test_the_calm_sea_is_generation_4_to_1e_9(wind_ms):
    """Every storm term is a product with storm = smoothstep(8, 18, wind) = 0
    at and below 8 m/s; the twin's two tails agree to CALM_TOLERANCE."""
    pm3, footprint, dist, wave_tilt, crest = _samples()
    assert float(twin.storm_factor(wind_ms, K)) == 0.0
    n4, base4, foam4 = twin.shade_gen4(pm3, wind_ms, WIND_DIR, 2.5, footprint, wave_tilt, crest)
    n5, base5, foam5 = twin.shade_gen5(pm3, wind_ms, WIND_DIR, 2.5, footprint, dist, wave_tilt, crest, K)
    assert np.abs(n5 - n4).max() <= twin.CALM_TOLERANCE
    assert np.abs(base5 - base4).max() <= twin.CALM_TOLERANCE
    assert np.abs(foam5 - foam4).max() <= twin.CALM_TOLERANCE
    # the generation-4 colour constants are still the shader's
    assert np.array_equal(K["WATER_RGB"], twin.GEN4_WATER_RGB) and K["FOAM_ALBEDO"] == twin.GEN4_FOAM_ALBEDO


def test_the_storm_ramp_is_stated_and_full_at_its_top():
    assert K["STORM_WIND_LOW_MS"] == 8.0 and K["STORM_WIND_HIGH_MS"] == 18.0   # Beaufort 5 to 8
    assert 7.0 < K["STORM_WIND_LOW_MS"]                                        # the 7 m/s calm sea is below the ramp
    assert float(twin.storm_factor(18.0, K)) == 1.0 and float(twin.storm_factor(30.0, K)) == 1.0
    assert 0.0 < float(twin.storm_factor(13.0, K)) < 1.0


# -- the storm foam ------------------------------------------------------------------

def test_a_fine_pixel_draws_each_foam_layer_at_its_stated_mean_cover():
    """At a 0.5 m footprint close by, each layer's mean cover over a 4 km patch is
    the MEAN constant the shader hands an unresolving pixel (within 0.02)."""
    rng = np.random.default_rng(3)
    pm = rng.uniform(-2000.0, 2000.0, size=(200000, 2))
    _, crest_key = twin.storm_swell(pm, WIND_DIR, 3.0, 5.0, 1.0, K)
    fine, fine_seen, patch, patch_seen = twin.storm_foam_layers(pm, WIND_DIR, 0.5, 100.0, 3.0, 22.0, crest_key, K)
    assert np.all(fine_seen == 1.0) and np.all(patch_seen == 1.0)
    assert abs(fine.mean() - K["STREAK_MEAN"]) < 0.02
    assert abs(patch.mean() - K["PATCH_MEAN"]) < 0.02
    # the layers are real foam, not a haze: a fine pixel is mostly clear water or mostly foam
    assert (fine > 0.9).mean() > 0.05 and (fine < 0.1).mean() > 0.6
    assert K["STREAK_SHARE"] + K["PATCH_SHARE"] == pytest.approx(1.0)


@pytest.mark.parametrize("footprint_m,dist_m", [(80.0, 500.0), (0.5, 40000.0), (300.0, 60000.0)])
def test_a_coarse_or_far_pixel_gets_the_mean_cover_exactly_never_speckle(footprint_m, dist_m):
    """Nothing sub-pixel: past a layer's footprint or distance the foam is its
    mean -- one value over the whole patch (variance 0), and not zero."""
    rng = np.random.default_rng(5)
    pm = rng.uniform(-20000.0, 20000.0, size=(50000, 2))
    _, crest_key = twin.storm_swell(pm, WIND_DIR, 3.0, footprint_m, 1.0, K)
    foam = twin.storm_foam(pm, WIND_DIR, footprint_m, dist_m, 3.0, 22.0, crest_key, 1.0, K)
    expected = K["STREAK_SHARE"] * K["STREAK_MEAN"] + K["PATCH_SHARE"] * K["PATCH_MEAN"]
    assert foam.max() - foam.min() < 1e-12      # one value (float rounding of the lerp aside)
    assert foam.min() == pytest.approx(expected, abs=1e-12) and expected > 0.05


def test_the_footprint_filter_resolves_a_layer_only_when_the_pixel_is_finer_than_it():
    """Each layer's `seen` fades from a quarter of its width to its width."""
    pm = np.zeros((1, 2))
    key = np.zeros(1)
    for across, fade_start, fade_end in (("STREAK_ACROSS_M", "STREAK_FADE_START_M", "STREAK_FADE_END_M"),
                                         ("PATCH_ACROSS_M", "PATCH_FADE_START_M", "PATCH_FADE_END_M")):
        w = K[across]
        idx = 1 if across.startswith("STREAK") else 3
        seen = lambda fp, d: float(np.asarray(  # noqa: E731
            twin.storm_foam_layers(pm, WIND_DIR, fp, d, 0.0, 22.0, key, K)[idx]).reshape(-1)[0])
        assert seen(w / 4.0, 10.0) == 1.0
        assert seen(w, 10.0) == 0.0
        assert seen(0.1, K[fade_start]) == 1.0
        assert seen(0.1, K[fade_end]) == 0.0
    # the fine streaks are gone well before the patches; both are sub-pixel from 10 km up
    assert K["STREAK_ACROSS_M"] < K["PATCH_ACROSS_M"] <= 60.0


def test_the_streaks_run_along_the_wind():
    """A 2 m step across the wind changes the fine foam far more than along it."""
    rng = np.random.default_rng(11)
    pm = rng.uniform(-2000.0, 2000.0, size=(100000, 2))
    key = np.zeros(len(pm))
    f0 = twin.storm_foam_layers(pm, WIND_DIR, 0.5, 100.0, 3.0, 22.0, key, K)[0]
    along = twin.storm_foam_layers(pm + 2.0 * WIND_DIR, WIND_DIR, 0.5, 100.0, 3.0, 22.0, key, K)[0]
    across = twin.storm_foam_layers(pm + 2.0 * np.array([-WIND_DIR[1], WIND_DIR[0]]), WIND_DIR, 0.5, 100.0,
                                    3.0, 22.0, key, K)[0]
    assert np.abs(across - f0).mean() > 8.0 * np.abs(along - f0).mean()
    assert K["STREAK_ALONG_M"] >= 10.0 * K["STREAK_ACROSS_M"] and K["PATCH_ALONG_M"] >= 5.0 * K["PATCH_ACROSS_M"]


def test_the_crest_foam_fades_out_with_the_storm():
    """At full storm the texel-keyed Monahan foam is gone (it would be speckle);
    the storm foam alone remains, bounded by 1."""
    pm3, footprint, dist, wave_tilt, crest = _samples(4000)
    big_crest = np.full_like(crest, 5.0)   # every texel 'breaking'
    _, _, foam_calm = twin.shade_gen5(pm3, 7.0, WIND_DIR, 2.5, footprint, dist, wave_tilt, big_crest, K)
    _, _, foam_storm = twin.shade_gen5(pm3, 25.0, WIND_DIR, 2.5, footprint, dist, wave_tilt, big_crest, K)
    assert foam_calm.min() == 1.0            # generation 4's crest foam on a breaking texel
    assert foam_storm.max() <= 1.0 and foam_storm.max() < 1.0
    assert foam_storm.mean() < 0.6


# -- the storm swell and the body ------------------------------------------------------

def test_the_storm_swell_is_resolved_steep_and_absent_from_the_calm_sea():
    rng = np.random.default_rng(13)
    pm = rng.uniform(-5000.0, 5000.0, size=(50000, 2))
    tilt_fine, key = twin.storm_swell(pm, WIND_DIR, 3.0, 5.0, 1.0, K)
    rms = np.sqrt((tilt_fine ** 2).sum(-1).mean())
    assert 0.03 < rms < 0.12                 # steeper than Swell's 0.022, far from a wall
    tilt_coarse, _ = twin.storm_swell(pm, WIND_DIR, 3.0, 200.0, 1.0, K)
    assert np.abs(tilt_coarse).max() == 0.0  # 200 m footprint: a 420 m wave is not resolved
    tilt_calm, _ = twin.storm_swell(pm, WIND_DIR, 3.0, 5.0, 0.0, K)
    assert np.abs(tilt_calm).max() == 0.0
    assert 0.05 < key.mean() < 0.5 and key.max() <= 1.0


def test_the_storm_body_is_grey_green():
    rng = np.random.default_rng(17)
    pm3 = np.concatenate([rng.uniform(-5000.0, 5000.0, size=(20000, 2)), np.zeros((20000, 1))], -1)
    footprint = np.full(len(pm3), 500.0)      # unresolving: no foam layers, the body alone
    dist = np.full(len(pm3), 60000.0)
    zero = np.zeros((len(pm3), 2))
    crest = np.zeros(len(pm3))
    _, calm, _ = twin.shade_gen5(pm3, 7.0, WIND_DIR, 0.0, footprint, dist, zero, crest, K)
    _, storm, _ = twin.shade_gen5(pm3, 25.0, WIND_DIR, 0.0, footprint, dist, zero, crest, K)
    lum = lambda c: c @ np.array([0.2126, 0.7152, 0.0722])  # noqa: E731
    assert lum(storm).mean() > 1.5 * lum(calm).mean()                       # whipped water is paler
    assert (storm[:, 2] / storm[:, 1]).mean() < (calm[:, 2] / calm[:, 1]).mean()   # less blue than green
    chroma = lambda c: (c.max(-1) - c.min(-1)) / c.max(-1)  # noqa: E731
    assert chroma(storm).mean() < 0.6 * chroma(calm).mean()                 # greyer
    assert K["STORM_RGB"][1] >= K["STORM_RGB"][2] > K["STORM_RGB"][0]      # grey-green


# -- the shaders and the material ------------------------------------------------------

def test_the_three_shaders_share_one_storm_block_and_the_same_tail():
    texts = {n: (SHADERS / f"{n}.hlsl").read_text(encoding="utf-8") for n in ("ocean_colour", "ocean_normal",
                                                                               "ocean_emissive")}
    for name, text in texts.items():
        for fn in ("float2 StormSwell(", "float StormFoam("):
            assert fn in text, (name, fn)
        assert "float storm = smoothstep(STORM_WIND_LOW_MS, STORM_WIND_HIGH_MS, WindSpeedMS);" in text, name
        # A Custom node's body is a function body: its const floats are locals the
        # local struct's methods cannot see, so the shared block names none of them
        # (the generation-4 block kept to literals for the same reason).
        shared = text[text.index("// shared: ocean"):text.index("// end shared")]
        shared_code = "\n".join(line.split("//")[0] for line in shared.splitlines())
        for const in re.findall(r"^const float3? (\w+) =", text, re.M):
            assert const not in shared_code, (name, const)
        assert "tilt += S.StormSwell(p.xy, windDir, TimeS, footprintM, storm, crestKey);" in text, name
        assert "float foam = saturate(crestFoam * (1.0 - storm)" in text, name
        assert "float distM = length(CameraPos - WorldPos) / 100.0;" in text, name
        assert "return storm * saturate(cover);" in text, name
        assert "UNCALIBRATED" in text, name
        # bounded loops only (SM5): every loop is an unrolled fixed count
        assert all(re.search(r"\[unroll\] for \(int \w+ = 0; \w+ < \d+; \+\+\w+\)", line)
                   for line in text.splitlines() if "for (" in line), name
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
        assert "[loop]" not in code and "while" not in code, name
    assert "body = lerp(body, STORM_RGB *" in texts["ocean_colour"]
    assert "STORM_RGB" not in texts["ocean_normal"].split("struct FOceanSurface")[1]   # the normal needs no colour
    assert "* (1.0 - foam);" in texts["ocean_emissive"]
    # the constants the twin reads are all there
    for name in ("STORM_WIND_LOW_MS", "STORM_WIND_HIGH_MS", "STORM_RGB", "STREAK_ALONG_M", "STREAK_ACROSS_M",
                 "STREAK_THRESHOLD", "STREAK_MEAN", "STREAK_SHARE", "PATCH_ALONG_M", "PATCH_ACROSS_M",
                 "PATCH_THRESHOLD", "PATCH_MEAN", "PATCH_SHARE", "STREAK_FADE_START_M", "STREAK_FADE_END_M",
                 "PATCH_FADE_START_M", "PATCH_FADE_END_M", "FOAM_DRIFT_SHARE"):
        assert name in K, name


def test_the_material_generation_is_bumped_and_the_defaults_are_the_calm_sea():
    gens = re.search(r'"M_FlightSimOceanBeauty": "(\d+)"\}', SCRIPT)
    assert gens and gens.group(1) == "7"   # generation 6: hyperreal sea (test_ocean_hyper_sea.py); 7: round-147 HorizonLift
    assert 'WORLD_OCEAN_SCALARS = {"WindSpeedMS": 7.0, "WindDirX": 1.0, "WindDirY": 0.3, "HyperSea": 1.0, "HorizonLift": 1.0}' in SCRIPT
    # the ocean section only: the cloud sections are flightsim-83's
    assert "ocean_storm_sea" in SCRIPT[SCRIPT.index("#: M_FlightSimOceanBeauty (the beauty sea cap"):
                                       SCRIPT.index("WORLD_OCEAN_SCALARS")]


# -- the C++ feed ----------------------------------------------------------------------

def test_the_card_wind_reaches_the_sea_caps_material_instance_only():
    body = TILES_CPP[TILES_CPP.index("TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyGround("):]
    assert "double WindSpeedMps, double WindFromDeg," in body
    sea = body[body.index("UMaterialInstanceDynamic* SeaMaterial"):body.index("BeautyOnlyActors.Add(SeaActor);")]
    for name in ("WindSpeedMS", "WindDirX", "WindDirY"):
        assert f'SeaMaterial->SetScalarParameterValue(FName(TEXT("{name}"))' in sea, name
    assert TILES_CPP.count('SetScalarParameterValue(FName(TEXT("WindSpeedMS"))') == 1   # the cap's instance only
    assert "DownwindX = -FMath::Sin(FromRadians);" in sea and "DownwindY = -FMath::Cos(FromRadians);" in sea
    # still air keeps the material's defaults (the calm #13 sea stays the 7 m/s one)
    assert "WindSpeedMps > 0.0" in sea and "bOceanBeauty &&" in sea
    assert 'Wind->SetNumberField(TEXT("WindSpeedMS"), bCardWind ? WindSpeedMps : 7.0);' in body
    # the header states the feed and the signature
    assert ("TSharedPtr<FJsonObject> ApplyBeautyGround(UWorld* World, double CameraAglM, double SeaRadiusM,\n"
            "\t                                          double WindSpeedMps, double WindFromDeg,") in TILES_H
    # the record claims the sea state now, not tides
    assert 'Sea->SetObjectField(TEXT("wind"), Wind);' in body
    assert "the sea state of the card (the waves are the material's stated 7 m/s sea)" not in body


def test_the_commandlet_hands_the_cards_wind_over_inside_the_beauty_gate():
    hook = COMMANDLET.index("GoogleTiles.ApplyBeautyGround(")
    call = COMMANDLET[hook:hook + 400]
    assert "Card.WindSpeedKnots * (1852.0 / 3600.0), Card.WindFromDegrees," in call
    gate = COMMANDLET.rindex("if (bBeauty && bVisual)", 0, hook)
    assert hook - gate < 1500
    assert COMMANDLET.count("GoogleTiles.ApplyBeautyGround(") == 1


@pytest.mark.parametrize("from_deg,expected", [(270.0, (1.0, 0.0)), (0.0, (0.0, -1.0)), (90.0, (-1.0, 0.0)),
                                               (180.0, (0.0, 1.0))])
def test_the_downwind_direction_is_the_from_bearing_turned_about(from_deg, expected):
    """A west wind (from 270) blows east: downwind +X in engine X east / Y north."""
    assert twin.downwind_engine_xy(from_deg) == pytest.approx(expected, abs=1e-12)


def test_knots_to_metres_per_second_matches_the_physics_conversion():
    # FlightSimScenarioWorld.cpp: SpeedMps = WindSpeedKnots * (1852.0 / 3600.0)
    assert twin.card_wind_ms(40.0) == pytest.approx(20.5777, abs=1e-3)
    assert float(twin.storm_factor(twin.card_wind_ms(40.0), K)) == 1.0     # "gale" (40 kt) is a full storm sea
    assert 0.4 < float(twin.storm_factor(twin.card_wind_ms(25.0), K)) < 0.6   # "strong wind" (25 kt, Beaufort 6): half way
    assert float(twin.storm_factor(twin.card_wind_ms(12.0), K)) == 0.0     # "breezy" (12 kt) is the calm sea
