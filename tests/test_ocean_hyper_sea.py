"""Hyperreal sea (2026-11-15): M_FlightSimOceanBeauty generation 6, BEAUTY ONLY.

Every generation-6 term sits behind the HyperSea scalar (default 1); the render
switch -ocean-hyper=0 sets it to 0 and the shaders reduce to generation 5. The
numbers are checked against their sources: Pierson-Moskowitz 1964 (peak, Hs),
Cox & Munk 1954 (upwind/crosswind slope variance), Monahan & O'Muircheartaigh
1980 / Callaghan et al. 2008 (whitecap onset), Pope & Fry 1997 (absorption).
"""
import re
from pathlib import Path

import numpy as np
import pytest

from core.scene import ocean_storm_sea as twin

REPO = Path(__file__).resolve().parents[1]
SHADERS = REPO / "assets" / "shaders" / "world"
TILES_CPP = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
             / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
K = twin.shader_constants()
TEXTS = {n: (SHADERS / f"{n}.hlsl").read_text(encoding="utf-8") for n in ("ocean_colour", "ocean_normal",
                                                                           "ocean_emissive")}


def test_pm_peak_and_steepness_match_the_spectrum():
    for u in (5.0, 7.0, 12.0):
        assert twin.pm_peak_wavelength_m(u) == pytest.approx(K["HYPER_PEAK_PER_U2"] * u * u, rel=1e-3)
    assert twin.pm_peak_wavelength_m(7.0) == pytest.approx(40.8, abs=0.1)
    ka = twin.pm_component_steepness()
    assert ka == pytest.approx([K["HYPER_SEA_KA_1"], K["HYPER_SEA_KA_2"], K["HYPER_SEA_KA_3"]], abs=2e-4)
    # fully developed: the steepness does not depend on the wind
    assert twin.pm_component_steepness(wind_ms=15.0) == pytest.approx(ka, rel=1e-9)
    # Hs / Lp = 0.21 / (2 pi / 0.877^2) = 0.0257
    assert 0.21 * 0.877 ** 2 / (2 * np.pi) == pytest.approx(0.0257, abs=1e-4)


def test_the_swell_is_a_12_second_two_metre_swell():
    assert K["HYPER_SWELL_M"] == pytest.approx(9.81 * 12.0 ** 2 / (2 * np.pi), abs=0.1)
    assert K["HYPER_SWELL_KA"] == pytest.approx(np.pi * 2.0 / K["HYPER_SWELL_M"], abs=1e-3)


def test_gerstner_crests_are_sharper_than_troughs():
    # one resolved swell along x: compare the slope magnitude near crest vs trough
    pm = np.stack([np.linspace(0.0, 2000.0, 20001), np.zeros(20001)], axis=1)
    tilt, height, var = twin.hyper_waves(pm, np.array([1.0, 0.0]), 0.0, 0.5, 7.0)
    slope = np.linalg.norm(tilt, axis=1)
    crest, trough = height > 0.5, height < -0.5
    assert crest.any() and trough.any()
    # trochoid: the steep parts sit around the crests, the troughs are broad and flat
    assert np.percentile(slope[crest], 90) > 1.05 * np.percentile(slope[trough], 90)
    assert np.all(np.abs(height) <= 1.0 + 1e-9) and np.all(var > 0.0)


def test_unresolved_waves_vanish_and_carry_no_variance():
    pm = np.random.default_rng(3).uniform(-5e4, 5e4, (5000, 2))
    tilt, height, var = twin.hyper_waves(pm, np.array([0.6, 0.8]), 1.0, 500.0, 7.0)
    assert np.abs(tilt).max() == 0.0 and np.abs(height).max() == 0.0 and var.max() == 0.0


def test_cox_munk_anisotropy():
    assert K["CM_UPWIND_PER_MS"] == 3.16e-3 and K["CM_CROSS_BASE"] == 3e-3 and K["CM_CROSS_PER_MS"] == 1.92e-3
    assert twin.cox_munk_upwind_share(0.0) == 0.0
    share7 = twin.cox_munk_upwind_share(7.0)
    assert share7 == pytest.approx(0.02212 / (0.02212 + 0.01644), rel=1e-6)
    assert share7 > 0.5 and twin.cox_munk_upwind_share(14.0) > share7   # the glint stretches downwind


def test_no_whitecaps_below_three_metres_per_second():
    assert twin.whitecap_onset(np.array([0.0, 2.9, 3.0]))[...].max() == 0.0
    assert twin.whitecap_onset(np.array([4.0, 7.0, 20.0])).min() == 1.0
    # Monahan: 3.7 m/s (the Callaghan 2008 onset) sits inside the ramp
    assert 0.0 < float(twin.whitecap_onset(3.7)) < 1.0


def test_crest_light_is_pope_fry_transmittance():
    a = np.array([0.340, 0.0565, 0.0092])
    assert K["SSS_RGB"] == pytest.approx(np.exp(-a * 1.5), abs=1e-3)
    r, g, b = K["SSS_RGB"]
    assert b > g > r     # turquoise-blue: red absorbed first


def test_every_generation_6_term_is_gated_by_hyper():
    for name, text in TEXTS.items():
        assert "float hyper = saturate(HyperSea);" in text, name
        assert "[branch] if (hyper < 1.0) { swellTilt = S.Swell(p.xy, windDir, TimeS, footprintM); }" in text, name
        assert "swellTilt = lerp(swellTilt, S.HyperWaves(" in text, name
        assert "HYPER_WHITECAP_FULL_MS, WindSpeedMS), hyper);" in text, name
        assert re.search(r"//\s+HyperSea\s", text), name
        # the shared block names no const (Metal: Custom-node locals are invisible to struct methods)
        shared = text[text.index("// shared: ocean"):text.index("// end shared")]
        code = "\n".join(line.split("//")[0] for line in shared.splitlines())
        for const in re.findall(r"^const float3? (\w+) =", text, re.M):
            assert not re.search(rf"\b{const}\b", code), (name, const)
    e = TEXTS["ocean_emissive"]
    assert "float3 sss = hyper * SunIlluminance" in e
    assert "d = k == 0 ? lerp(d, dAniso, hyper) : d;" in e
    assert "variance = lerp(variance, max(variance - hyperVar, 0.0004), hyper);" in e
    assert "lerp(0.05, HYPER_NV_FLOOR, hyper)" in e
    # Schlick at the floors: 0.78 (generation 5) -> 0.95 near grazing
    assert 0.02 + 0.98 * (1 - 0.05) ** 5 == pytest.approx(0.778, abs=1e-3)
    assert 0.02 + 0.98 * (1 - K["HYPER_NV_FLOOR"]) ** 5 == pytest.approx(0.952, abs=1e-3)


def test_the_switch_and_the_default():
    assert '"HyperSea": 1.0, "HorizonLift": 1.0}' in SCRIPT and '"HyperSea", "OceanN")' in SCRIPT
    body = TILES_CPP[TILES_CPP.index("TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyGround("):]
    assert 'TEXT("ocean-hyper="), OceanHyperWord) && OceanHyperWord == 0' in body
    assert 'SeaMaterial->SetScalarParameterValue(FName(TEXT("HyperSea")), 0.0f);' in body
