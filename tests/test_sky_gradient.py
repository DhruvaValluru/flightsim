"""Lane sky-atmosphere: -look-sky-gradient (core/sky/gradient.py and its C++ twin)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.scene import world_beauty as wb
from core.sky import gradient as g

ROOT = Path(__file__).resolve().parents[1]
CLOUDS = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp").read_text()
HEADER = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimClouds.h").read_text()
API = (ROOT / "scripts/check_bridge_api.sh").read_text()


def _cpp_array(name: str):
    m = re.search(name + r"\[[A-Za-z0-9]+\]\s*=\s*\{([^}]*)\}", CLOUDS)
    assert m, name
    return tuple(float(x) for x in m.group(1).split(","))


def _cpp_const(name: str) -> float:
    m = re.search(r"constexpr double " + name + r" = ([-0-9.]+);", CLOUDS)
    assert m, name
    return float(m.group(1))


@pytest.mark.parametrize("el", [0, 10, 20, 30, 40, 50, 60, 70, 80, 90])
def test_airlight_table_is_the_cie_clear_sky(el):
    assert g.AIRLIGHT_GAIN_TABLE[el // 10] == pytest.approx(g.cie_horizon_to_mean(el), abs=0.012)


def test_cie_clear_sky_horizon_brighter_than_zenith_and_mean():
    # A clear sky is darkest near 90 deg from the sun and brightens to the horizon.
    zs = 0.7854
    assert g.cie_clear_sky_relative(1.5359, 3.1416, zs) > g.cie_clear_sky_relative(0.0, 0.0, zs)
    assert all(v > 1.0 for v in g.AIRLIGHT_GAIN_TABLE)
    assert list(g.AIRLIGHT_GAIN_TABLE) == sorted(g.AIRLIGHT_GAIN_TABLE, reverse=True)


def test_cpp_table_and_constants_match():
    assert _cpp_array("AirlightGainTable") == g.AIRLIGHT_GAIN_TABLE
    assert _cpp_const("AirlightGainMax") == g.AIRLIGHT_GAIN_MAX
    assert _cpp_const("AirlightTwilightDeg") == g.AIRLIGHT_TWILIGHT_DEG
    assert _cpp_const("SkyGradientFogCutoffKm") == g.FOG_CUTOFF_KM
    assert _cpp_const("SkyGradientSkyPixelDepthKm") == g.SKY_PIXEL_DEPTH_KM
    assert _cpp_array("EarthRayleighPerKm") == g.EARTH_ATMOSPHERE["rayleigh_per_km"]
    assert _cpp_array("EarthOzonePerKm") == g.EARTH_ATMOSPHERE["ozone_per_km"]
    assert _cpp_const("EarthRayleighScaleHeightKm") == g.EARTH_ATMOSPHERE["rayleigh_scale_height_km"]


def test_gain_curve():
    assert g.horizon_airlight_gain(45.0) == pytest.approx((1.371 + 1.273) / 2.0)
    assert g.horizon_airlight_gain(90.0) == pytest.approx(1.123)
    assert g.horizon_airlight_gain(120.0) == pytest.approx(1.123)
    assert g.horizon_airlight_gain(0.0) == g.AIRLIGHT_GAIN_MAX == 2.0   # 2.313 capped
    assert g.horizon_airlight_gain(-3.0) == pytest.approx(1.5)
    assert g.horizon_airlight_gain(-6.0) == pytest.approx(1.0)
    assert g.horizon_airlight_gain(-30.0) == pytest.approx(1.0)
    for el in range(-10, 91):
        assert 1.0 <= g.horizon_airlight_gain(el) <= g.AIRLIGHT_GAIN_MAX


def test_cutoff_clears_every_surface_and_stops_short_of_the_sky():
    # Engine: SubtractValue -= 1e-8, so DeviceZ 0 -> 1 / 1e-8 cm.
    assert g.SKY_PIXEL_DEPTH_KM == pytest.approx(1.0 / 1e-8 / 1e5)
    far = g.max_visible_distance_km()
    assert 740.0 < far < 760.0
    assert far < g.FOG_CUTOFF_KM < g.SKY_PIXEL_DEPTH_KM
    # FL350 over the sea: horizon ~369 km.
    assert g.max_visible_distance_km(10.668, 0.0) == pytest.approx(368.8, abs=0.5)


def test_earth_atmosphere_is_the_brief_numbers_per_mm():
    ea = g.EARTH_ATMOSPHERE
    assert tuple(round(v * 1000, 3) for v in ea["rayleigh_per_km"]) == (5.802, 13.558, 33.1)
    assert tuple(round(v * 1000, 3) for v in ea["ozone_per_km"]) == (0.65, 1.881, 0.085)
    assert ea["mie_scattering_per_km"] * 1000 == pytest.approx(3.996)
    assert ea["rayleigh_scale_height_km"] == 8.0
    assert wb.ATMOSPHERE["clear"]["mie_scale_height_km"] == 1.2


def test_presets_are_the_fog_profile_rows():
    rows = tuple(p for p, r in wb.ATMOSPHERE.items() if r["fog_scale_height_km"] > 0.0)
    assert rows == g.GRADIENT_PRESETS
    assert "SkyGradientFor(TCHAR_TO_ANSI(*SkyGradientSwitch)) == 1 && bFogProfile" in CLOUDS


def test_switch_words():
    assert g.sky_gradient_mode(None) == "on"
    assert g.sky_gradient_mode("") == "on"
    assert g.sky_gradient_mode("off") == "off"
    with pytest.raises(ValueError, match="-look-sky-gradient=bright is not on or off"):
        g.sky_gradient_mode("bright")
    assert 'FParse::Value(*Switches, TEXT("look-sky-gradient="), SkyGradientSwitch);' in CLOUDS
    assert "-look-sky-gradient=%s is not on or off" in CLOUDS
    assert 'FString SkyGradientSwitch = TEXT("on");' in HEADER


def test_host_applies_cutoff_and_gain_only_on_atmosphere_lit_fog():
    body = CLOUDS[CLOUDS.index("void FFlightSimWorldBeauty::ApplyAtmosphere"):]
    body = body[:body.index("\nvoid FFlightSimWorldBeauty::", 10)]
    assert "Fog->SetFogCutoffDistance(static_cast<float>(SkyGradientFogCutoffKm * 1000.0 * WorldCmPerMetre));" in body
    assert "Fog->FogInscatteringLuminance.Equals(FLinearColor::Black)" in body
    assert "Before.R * G, Before.G * G, Before.B * G" in body
    assert body.count("if (bSkyGradient)") == 2
    assert 'Out->SetObjectField(TEXT("sky_gradient"), Gradient);' in body


def test_engine_readings_pinned():
    for needle in ("SetFogCutoffDistance(float Value);", "SubtractValue -= 0.00000001f;",
                   "ExponentialFogParameters3.w > 0 && CameraToReceiverLength > FogData.ExponentialFogParameters3.w",
                   "GetViewDistanceSkyLightColor();", "const float EarthRayleighScaleHeight = 8.0f;",
                   "SetOtherAbsorptionScale(float NewValue);"):
        assert needle in API, needle
