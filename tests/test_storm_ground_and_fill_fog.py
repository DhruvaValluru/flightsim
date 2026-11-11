"""2026-11-11: #10's green under the tornado's storm deck and #02's blue shade.

#10: the hero-lighting lane runs AFTER the world lane's storm_deck_light, so the
sidecar's ground (the grassland row, green) was the sky light's whole lower
hemisphere under the deck. Under a storm world the sidecar now states it as a
grey of the same luminance; ``-storm-lower-hemisphere=surface`` restores the
colour (the A/B).

#02: under a STATED fill the height fog's sky-atmosphere ambient takes the
fill's colour; ``-stated-fill-fog=sky`` keeps the sky's hue (the A/B).

Both are beauty only: the sidecar and the hero lane exist for beauty alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.scene import hero_lighting as hl

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
HERO_CPP = (PRIVATE / "FlightSimHeroLighting.cpp").read_text(encoding="utf-8")
COMMANDLET_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
API = (REPO / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")


def _luma(rgb):
    return sum(w * c for w, c in zip(hl.REC709_LUMA, rgb))


# -- #10: the storm ground ------------------------------------------------------------


def test_the_hero_lane_runs_after_the_world_lane():
    # Why the world lane's black lower hemisphere never reached the capture.
    world = COMMANDLET_CPP.index("if (bBeauty && !WorldBeauty.Build(")
    hero = COMMANDLET_CPP.index("if (bVisual && bBeauty && !FFlightSimHeroLighting::Apply(")
    assert world < hero


def test_storm_deck_ground_is_a_grey_of_the_surface_luminance():
    clear = hl.plan_sidecar(surface="grassland", sun_elevation_deg=51.6, horizontal_lux=None,
                            raining=True)
    storm = hl.plan_sidecar(surface="grassland", sun_elevation_deg=51.6, horizontal_lux=None,
                            raining=True, storm_deck=True)
    green = clear["ground"]["lower_hemisphere_luminance_rgb"]
    assert green[1] > 2.0 * green[2]                      # the grassland row: the #10 green
    grey = storm["ground"]["lower_hemisphere_luminance_rgb"]
    assert grey[0] == grey[1] == grey[2]
    assert grey[0] == pytest.approx(_luma(green), abs=2e-3)
    assert storm["ground"]["lower_hemisphere_luminance_rgb_surface"] == green
    assert "storm" in storm["ground"]["lower_hemisphere_storm_deck"]
    # Not a storm: byte-identical to before (no new keys).
    assert "lower_hemisphere_luminance_rgb_surface" not in clear["ground"]
    assert hl.plan_sidecar(surface="grassland", sun_elevation_deg=51.6, horizontal_lux=None,
                           raining=True, storm_deck=False) == clear


@pytest.mark.parametrize("look, expected", [
    ({"world_preset": "storm", "grade": "storm"}, True),
    ({"world_preset": "rain", "grade": "storm"}, False),
    ({"world_preset": "clear", "grade": "desert_noon"}, False),
    ({"world_preset": None, "grade": "storm", "grade_basis": "weather event tornado"}, True),
    # Round 55 (#10): the tornado card's look says "clear" while the world lane draws the storm.
    ({"world_preset": "clear", "grade": "storm", "grade_basis": "weather event tornado"}, True),
    ({"world_preset": None, "grade": "storm", "grade_basis": "rain is stated"}, False),
    ({}, False),
])
def test_storm_deck_look(look, expected):
    assert hl.storm_deck_look(look) is expected


def test_the_switches_are_named_once_in_python():
    assert hl.DIAGNOSTIC_SWITCHES["storm-lower-hemisphere"] == hl.STORM_LOWER_HEMISPHERE_SWITCHES
    assert hl.STORM_LOWER_HEMISPHERE_DEFAULT == hl.STORM_LOWER_HEMISPHERE_SWITCHES[0]
    assert hl.DIAGNOSTIC_SWITCHES["stated-fill-fog"] == hl.STATED_FILL_FOG_SWITCHES
    assert hl.STATED_FILL_FOG_DEFAULT == hl.STATED_FILL_FOG_SWITCHES[0]
    assert hl.parse_diagnostic_switches("-storm-lower-hemisphere=surface -stated-fill-fog=sky") == {
        "storm-lower-hemisphere": "surface", "stated-fill-fog": "sky"}
    for bad in ("-storm-lower-hemisphere=black", "-stated-fill-fog=off"):
        with pytest.raises(hl.HeroLightingError, match="render.sky_fill_probe"):
            hl.parse_diagnostic_switches(bad)


def test_the_host_draws_the_grey_and_the_switch_restores_the_surface():
    start = HERO_CPP.index('HeroLightingReadRgb(*Ground, TEXT("lower_hemisphere_luminance_rgb"), Lower)')
    block = HERO_CPP[start:HERO_CPP.index("Sky->SetLowerHemisphereColor(Lower);", start)]
    assert 'HasField(TEXT("lower_hemisphere_luminance_rgb_surface"))' in block
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in block
    assert 'FString StormLower = TEXT("neutral");' in block            # the default is the fix
    assert 'TEXT("storm-lower-hemisphere=")' in block
    assert 'HeroLightingReadRgb(*Ground, TEXT("lower_hemisphere_luminance_rgb_surface"), Lower)' in block
    assert "render.sky_fill_probe: -storm-lower-hemisphere=%s" in block
    assert 'SetStringField(TEXT("storm_lower_hemisphere"), StormLower)' in block


def test_write_sidecar_beside_marks_the_storm_world(tmp_path):
    from types import SimpleNamespace

    look = tmp_path / "beauty_look.json"
    look.write_text(json.dumps({"sun_elevation_deg": 51.6, "grade": "storm", "world_preset": "storm",
                                "exposure": {}}), encoding="utf-8")
    spec = SimpleNamespace(surface=SimpleNamespace(value="grassland"))
    plan = json.loads(hl.write_sidecar_beside(spec, look).read_text(encoding="utf-8"))
    grey = plan["ground"]["lower_hemisphere_luminance_rgb"]
    assert grey[0] == grey[1] == grey[2] > 0.0
    assert "lower_hemisphere_luminance_rgb_surface" in plan["ground"]
    look.write_text(json.dumps({"sun_elevation_deg": 51.6, "grade": "desert_noon", "world_preset": "clear",
                                "exposure": {}}), encoding="utf-8")
    plan = json.loads(hl.write_sidecar_beside(spec, look).read_text(encoding="utf-8"))
    assert "lower_hemisphere_luminance_rgb_surface" not in plan["ground"]


# -- #02: the stated fill's fog ---------------------------------------------------------


def test_the_host_tints_the_fog_ambient_by_the_stated_fill():
    start = HERO_CPP.index('FString FillFog = TEXT("tint");')
    block = HERO_CPP[start:HERO_CPP.index('Probe->SetObjectField(TEXT("sky_light_after_probes")', start)]
    assert 'TEXT("stated-fill-fog=")' in block
    assert 'FillFog == TEXT("tint") && Plan.IsValid()' in block
    assert 'Plan->TryGetObjectField(TEXT("sky_light"), FogFill)' in block    # stated fill only
    assert 'HeroLightingReadRgb(*FogFill, TEXT("color_linear_rgb"), FogTint)' in block
    assert "Fog->SetSkyAtmosphereAmbientContributionColorScale(AmbientAfter);" in block
    assert "Fog->GetWorld() != Sky->GetWorld()" in block
    assert "render.sky_fill_probe: -stated-fill-fog=%s" in block
    # Colour only: never an intensity, never the fog's own inscattering colour or density.
    for banned in ("SetIntensity(", "SetFogInscatteringColor(", "SetFogDensity("):
        assert banned not in block
    assert '#include "Components/ExponentialHeightFogComponent.h"' in HERO_CPP
    assert '#include "UObject/UObjectIterator.h"' in HERO_CPP
    assert "hero: Fog SetSkyAtmosphereAmbientContributionColorScale" in API


def test_the_stated_fill_colour_neutralises_the_model_sky():
    # The fill colour the fog takes is the one round 4 gives the sky light:
    # at #02's relit 72 deg sun, the model sky times it is grey.
    fill = hl.stated_fill_tint(72.0, 1500.0)
    r, g, b = fill["color_linear_rgb"]
    assert r >= g >= b and b < 0.5            # it removes blue: the fog's ambient loses the sky's hue
