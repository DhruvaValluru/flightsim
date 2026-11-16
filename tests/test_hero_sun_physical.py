"""Lane hl-sun (2026-11-15): ``-sun-physical=on|off`` -- the beauty sun is the
true 0.533 deg disc and takes its colour from the atmosphere's extinction
only (core/scene/hero_lighting.py physical_sun, FlightSimHeroLighting.cpp).
Numeric checks on the Python twin, and source checks that the host's
constants and rule match it."""

import math
import re
from pathlib import Path

import pytest

import core.messages as messages
from core.scene import beauty_look
from core.scene import hero_lighting as hl
from core.scene import lighting

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimHeroLighting.cpp"


def _cpp() -> str:
    return CPP.read_text(encoding="utf-8")


def _cpp_const(name: str) -> float:
    match = re.search(rf"constexpr \w+ {name} = ([0-9.]+)f?;", _cpp())
    assert match is not None, name
    return float(match.group(1))


# -- the sun's size ------------------------------------------------------------


def test_true_disc_is_the_sun_seen_from_earth():
    # 2 atan(R_sun / 1 AU), R_sun 696,000 km (IAU nominal 695,700), 1 AU 149,597,870.7 km.
    disc = math.degrees(2.0 * math.atan(696_000.0 / 149_597_870.7))
    assert disc == pytest.approx(0.533, abs=0.001)
    assert hl.SUN_DISC_ANGLE_DEG == pytest.approx(disc, abs=0.005)


@pytest.mark.parametrize("preset", [p for p in lighting.PRESETS if p != "natural"])
def test_every_clear_preset_draws_the_true_disc_and_no_tint(preset):
    table = lighting.PRESETS[preset]
    sun = hl.physical_sun(table["shadow_softness_deg"], table["color_temperature_k"])
    if table["shadow_softness_deg"] > hl.OVERCAST_SOURCE_ANGLE_DEG:
        # overcast / soft: the deck's light, the disc hidden, its colour kept
        assert sun["source_angle_deg"] == table["shadow_softness_deg"]
        assert sun["temperature_k"] == table["color_temperature_k"]
        assert not sun["disc_drawn"]
    else:
        assert sun["source_angle_deg"] == hl.SUN_DISC_ANGLE_DEG
        assert sun["source_soft_angle_deg"] == hl.SUN_SOFT_ANGLE_DEG
        assert sun["temperature_k"] is None
        assert sun["disc_drawn"]


def test_off_is_the_earlier_sun():
    for angle, kelvin in ((0.3, 4800.0), (0.9, 3300.0), (1.5, 5600.0), (25.0, 6800.0)):
        sun = hl.physical_sun(angle, kelvin, switch="off")
        assert sun["source_angle_deg"] == angle
        assert sun["source_soft_angle_deg"] is None       # the host leaves it as the scene set it
        assert sun["temperature_k"] == kelvin
    # unstated: the true disc on both settings (the host's behaviour before this lane)
    for switch in hl.SUN_PHYSICAL_SWITCHES:
        sun = hl.physical_sun(None, None, switch=switch)
        assert (sun["source_angle_deg"], sun["source_soft_angle_deg"], sun["temperature_k"]) == \
            (hl.SUN_DISC_ANGLE_DEG, hl.SUN_SOFT_ANGLE_DEG, None)


def test_golden_hour_disc_was_drawn_too_wide():
    # The preset's 0.9 deg drew a sun 1.68x the real diameter (2.8x the area).
    old = hl.physical_sun(0.9, 3300.0, switch="off")["source_angle_deg"]
    new = hl.physical_sun(0.9, 3300.0)["source_angle_deg"]
    assert old / new == pytest.approx(1.68, abs=0.01)
    assert (old / new) ** 2 == pytest.approx(2.82, abs=0.02)


def test_pcss_penumbra_grows_with_distance_at_the_true_disc():
    # ShadowRendering.h: kernel ~ tan(angle / 2) x (receiver - blocker) / blocker
    # for a directional light, i.e. the penumbra width w = 2 d tan(angle / 2).
    angle = math.radians(hl.SUN_DISC_ANGLE_DEG)
    widths = [2.0 * d * math.tan(angle / 2.0) for d in (1.0, 10.0, 100.0)]
    assert widths[0] == pytest.approx(0.00935, abs=0.0001)   # 9 mm at 1 m: wing on fuselage
    assert widths[2] == pytest.approx(0.935, abs=0.01)       # ~0.9 m at 100 m: aircraft on runway
    assert widths[1] / widths[0] == pytest.approx(10.0)


# -- the sun's colour: the air mass --------------------------------------------


@pytest.mark.parametrize("elevation, expected", [(90.0, 1.0), (30.0, 1.995), (10.0, 5.60), (0.0, 37.9)])
def test_kasten_young_air_mass(elevation, expected):
    # Kasten & Young (1989) Table: m(90)=1, m(30)~1.995, m(10)~5.60, m(0)~37.9
    assert hl.kasten_young_air_mass(elevation) == pytest.approx(expected, rel=0.01)
    assert hl.kasten_young_air_mass(elevation) == pytest.approx(beauty_look.air_mass(elevation), rel=1e-9)


def test_air_mass_reddens_the_low_sun_and_not_the_noon_sun():
    # Rayleigh optical depth at sea level: 0.0973 at 550 nm (Bucholtz 1995,
    # Appl. Opt. 34(15) 2765), scaling as lambda^-4.08 (ibid.). Direct-beam
    # transmittance exp(-tau m); aerosols only redden it further.
    tau = {name: 0.0973 * (550.0 / nm) ** 4.08 for name, nm in (("r", 650.0), ("g", 550.0), ("b", 450.0))}
    noon = {k: math.exp(-v * hl.kasten_young_air_mass(70.0)) for k, v in tau.items()}
    low = {k: math.exp(-v * hl.kasten_young_air_mass(5.0)) for k, v in tau.items()}
    assert noon["b"] / noon["r"] > 0.8                 # near white at a high sun
    assert low["b"] / low["r"] < 0.25                  # deep orange near the horizon
    # The double tint the switch removes: 3300 K on top of that is redder still.
    assert beauty_look.sun_cct_k(5.0) < 4000.0


def test_cpp_constants_match_the_twin():
    assert _cpp_const("HeroLightingSunDiscAngleDeg") == hl.SUN_DISC_ANGLE_DEG
    assert _cpp_const("HeroLightingSunSoftAngleDeg") == hl.SUN_SOFT_ANGLE_DEG
    assert _cpp_const("HeroLightingOvercastAngleDeg") == hl.OVERCAST_SOURCE_ANGLE_DEG
    assert (_cpp_const("HeroLightingKastenYoungA"), _cpp_const("HeroLightingKastenYoungB"),
            _cpp_const("HeroLightingKastenYoungC")) == hl.KASTEN_YOUNG


# -- the switch ------------------------------------------------------------------


def test_switch_parses_both_channels_and_refuses_by_name(monkeypatch):
    assert hl.sun_physical_switch("") == "on"
    assert hl.sun_physical_switch("-sky-fill-probe=red -sun-physical=off") == "off"
    monkeypatch.setenv("FLIGHTSIM_RENDER_SWITCHES", "-sun-physical=off")
    assert hl.sun_physical_switch() == "off"
    with pytest.raises(hl.HeroLightingError) as error:
        hl.sun_physical_switch("-sun-physical=maybe")
    assert error.value.constraint == "render.sun_physical"
    with pytest.raises(hl.HeroLightingError):
        hl.physical_sun(0.5, None, switch="yes")
    assert messages.is_catalogued("render.sun_physical")


def test_cpp_reads_the_switch_and_defaults_on():
    source = _cpp()
    block = source[source.index("-sun-physical=on|off"):source.index("// Contact shadows, world space")]
    assert 'FString SunPhysical = TEXT("on");' in block
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in block
    assert "render.sun_physical: -sun-physical=%s is not on or off" in block
    assert "bSunPhysical && !IsOvercastSourceAngle(StatedAngle)" in block
    assert "bSunPhysical && !bOvercast && bAtmosphereColours" in block
    assert "SetUseTemperature(false)" in block
    # the sun's intensity is never touched (no SetIntensity in the lane)
    assert "SetIntensity(" not in source
    # record-only read-back of the engine's transmittance
    assert "GetAtmosphereTransmitanceOnGroundAtPlanetTop(SunLight)" in block


def test_lane_is_beauty_only():
    # The whole sun block sits inside Apply, which the commandlet calls only
    # for a visual beauty render; a light's angle and colour reach no label
    # capture (stencil, depth, GBuffer, velocity).
    commandlet = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
                  "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
    apply_line = next(l for l in commandlet.splitlines() if "FFlightSimHeroLighting::Apply(" in l)
    assert "bVisual && bBeauty" in apply_line
    source = _cpp()
    assert source.index("-sun-physical=on|off") > source.index("bool FFlightSimHeroLighting::Apply(")
