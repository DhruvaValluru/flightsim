"""Fix lane sun-color: -sky-capture-veil (core/sky/gradient.py and its C++ twin).

Round 144 (the gradient and sky step 4 merged) lost #01's golden hour and turned
#02 blue-white: the sky light's one capture draws the height fog over its sky
with the view's FogCutoffDistance test, so the cutoff and the 1.2 km profile
took the fog veil out of the FILL. The veil switch puts the pre-gradient fog back
for that capture only."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from core.scene import world_beauty as wb
from core.sky import gradient as g

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
CLOUDS = (SRC / "Private/FlightSimClouds.cpp").read_text(encoding="utf-8")
HEADER = (SRC / "Public/FlightSimClouds.h").read_text(encoding="utf-8")
COMMANDLET = (SRC / "Private/FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
API = (ROOT / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
CATALOG = (ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8")

SCENE_FALLOFF = wb.SCENE_FOG_HEIGHT_FALLOFF       # 0.0002: a 72 km scale height
SKY_DEPTH_M = g.SKY_PIXEL_DEPTH_KM * 1000.0       # where a sky pixel decodes to
CUTOFF_CM = g.FOG_CUTOFF_KM * 1000.0 * 100.0


def _opacity(density: float, falloff: float, fog_z_m: float, eye_z_m: float, dir_z: float,
             length_m: float, cutoff_cm: float, max_opacity: float = 0.92) -> float:
    """The engine's analytic height fog along one ray (HeightFogCommon.ush): the
    line integral of FogDensity/1000 per cm x 2^(-falloff/1000 x (z - FogHeight) cm),
    transmittance exp2(-integral), capped at max opacity; none past the cutoff."""
    length_cm = length_m * 100.0
    if cutoff_cm > 0.0 and length_cm > cutoff_cm:
        return 0.0
    k = falloff / 1000.0                           # per cm
    z0 = (eye_z_m - fog_z_m) * 100.0
    dz = dir_z * length_cm
    base = density / 1000.0 * 2.0 ** (-k * z0)
    if abs(k * dz) < 1e-9:
        integral = base * length_cm
    else:
        integral = base * length_cm * (1.0 - 2.0 ** (-k * dz)) / (k * dz * math.log(2.0))
    return min(1.0 - 2.0 ** (-integral), max_opacity)


def test_mode_default_on_and_refusal():
    assert g.sky_capture_veil_mode(None) == "on"
    assert g.sky_capture_veil_mode("") == "on"
    assert g.sky_capture_veil_mode("off") == "off"
    with pytest.raises(ValueError, match="world_beauty.sky_capture_veil"):
        g.sky_capture_veil_mode("maybe")
    assert g.SKY_CAPTURE_VEIL_SWITCH_WORDS == ("on", "off")


def test_veil_rebuilds_the_pre_gradient_fog_from_the_rebased_view():
    # #01: scene fog height 0 m, aircraft 1500 m above it, clear row (1.2 km).
    scene_density, scene_z, aircraft_z = 0.02, 0.0, 1500.0
    falloff = wb.fog_height_falloff(1.2)
    view_density = wb.fog_density_rebased(scene_density, falloff, scene_z, aircraft_z)
    assert view_density < 0.3 * scene_density          # the profile thinned the fog up there
    gain = g.horizon_airlight_gain(7.0)
    assert gain == pytest.approx(2.0)                   # capped at the golden hour
    view_ambient = (0.9 * gain, 0.95 * gain, 1.0 * gain)
    veil = g.sky_capture_veil_fog(view_density, falloff, aircraft_z, scene_z, SCENE_FALLOFF,
                                  0.0, view_ambient, gain)
    assert veil["density"] == pytest.approx(scene_density, rel=1e-12)
    assert veil["falloff"] == SCENE_FALLOFF
    assert veil["z_m"] == scene_z
    assert veil["cutoff_cm"] == 0.0
    assert veil["ambient_rgb"] == pytest.approx((0.9, 0.95, 1.0), rel=1e-12)
    # A later ratio on the view's density (the dust haze's) survives the round trip.
    veil2 = g.sky_capture_veil_fog(1.5 * view_density, falloff, aircraft_z, scene_z, SCENE_FALLOFF,
                                   0.0, view_ambient, gain)
    assert veil2["density"] == pytest.approx(1.5 * scene_density, rel=1e-12)
    with pytest.raises(ValueError):
        g.sky_capture_veil_fog(view_density, falloff, aircraft_z, scene_z, SCENE_FALLOFF, 0.0, view_ambient, 0.0)


@pytest.mark.parametrize("dir_z", [1.0, 0.5, 0.1])
def test_capture_sky_has_the_veil_only_under_the_veil_state(dir_z):
    """The regression in numbers: the captured sky's fog opacity, sky light at the
    aircraft. Round 199 (scene fog, no cutoff): the 0.92 veil. Round 144 (profile
    and cutoff): none, the bare atmosphere fills the shade. The veil state: 0.92 again."""
    scene_density, aircraft_z = 0.02, 1500.0
    falloff = wb.fog_height_falloff(1.2)
    old = _opacity(scene_density, SCENE_FALLOFF, 0.0, aircraft_z, dir_z, SKY_DEPTH_M, 0.0)
    view_density = wb.fog_density_rebased(scene_density, falloff, 0.0, aircraft_z)
    r144 = _opacity(view_density, falloff, aircraft_z, aircraft_z, dir_z, SKY_DEPTH_M, CUTOFF_CM)
    veil = g.sky_capture_veil_fog(view_density, falloff, aircraft_z, 0.0, SCENE_FALLOFF, 0.0, (1, 1, 1), 1.0)
    fixed = _opacity(veil["density"], veil["falloff"], veil["z_m"], aircraft_z, dir_z, SKY_DEPTH_M,
                     veil["cutoff_cm"])
    assert old == pytest.approx(0.92)
    assert r144 == 0.0
    assert fixed == pytest.approx(old, abs=1e-12)
    # Even without the cutoff, the profile alone thins the veil (sky step 4's part).
    profile_only = _opacity(view_density, falloff, aircraft_z, aircraft_z, dir_z, SKY_DEPTH_M, 0.0)
    assert profile_only <= old
    if dir_z == 1.0:
        assert profile_only < old


def test_view_surfaces_keep_the_gradient():
    """The veil is for the capture: a tile 3 km away keeps the view's own fog
    (the capture state is never left on). Here: the view state differs from the
    veil state, so Resume must put it back (pinned in C++ below)."""
    falloff = wb.fog_height_falloff(1.2)
    view_density = wb.fog_density_rebased(0.02, falloff, 0.0, 1500.0)
    view = _opacity(view_density, falloff, 1500.0, 1500.0, -0.5, 3000.0, CUTOFF_CM)
    old = _opacity(0.02, SCENE_FALLOFF, 0.0, 1500.0, -0.5, 3000.0, 0.0)
    assert view != pytest.approx(old, rel=1e-3)


def test_cpp_switch_and_refusal():
    assert 'FParse::Value(*Switches, TEXT("sky-capture-veil="), SkyCaptureVeilSwitch);' in CLOUDS
    assert "inline int SkyCaptureVeilFor(const char* Word)" in CLOUDS
    assert "world_beauty.sky_capture_veil: -sky-capture-veil=%s is not on or off" in CLOUDS
    assert "world_beauty.sky_capture_veil:" in CATALOG
    assert 'FString SkyCaptureVeilSwitch = TEXT("on");' in HEADER


def test_cpp_suspend_is_the_twin():
    body = CLOUDS[CLOUDS.index("TSharedPtr<FJsonObject> FFlightSimWorldBeauty::SuspendSkyGradientForCapture()"):]
    body = body[:body.index("void FFlightSimWorldBeauty::ResumeSkyGradientAfterCapture()")]
    assert "FogDensityRebased(Fog->FogDensity, Fog->FogHeightFalloff, CurrentZM, Veil.SceneZM)" in body
    assert "Fog->SetFogHeightFalloff(static_cast<float>(Veil.SceneFalloff));" in body
    assert "Fog->SetFogCutoffDistance(Veil.CutoffBeforeCm);" in body
    assert "Veil.HeldAmbient.R / G" in body
    assert "Veil.SceneZM * WorldCmPerMetre" in body
    # Recorded in ApplyAtmosphere BEFORE the profile and the cutoff change them.
    apply = CLOUDS[CLOUDS.index("Veil.SceneFalloff = Fog->FogHeightFalloff;") - 400:]
    assert apply.index("Veil.SceneFalloff = Fog->FogHeightFalloff;") < apply.index("Fog->SetFogHeightFalloff(static_cast<float>(FogFalloff));")
    assert apply.index("Veil.CutoffBeforeCm = Fog->FogCutoffDistance;") < apply.index("Fog->SetFogCutoffDistance(static_cast<float>(SkyGradientFogCutoffKm")
    assert "Veil.AirlightGain = AirlightGain;" in CLOUDS


def test_cpp_resume_restores_every_held_field():
    body = CLOUDS[CLOUDS.index("void FFlightSimWorldBeauty::ResumeSkyGradientAfterCapture()"):]
    body = body[:body.index("\n}\n")]
    for line in ("Fog->SetFogDensity(Veil.HeldDensity);", "Fog->SetFogHeightFalloff(Veil.HeldFalloff);",
                 "Fog->SetFogCutoffDistance(Veil.HeldCutoffCm);",
                 "Fog->SetSkyAtmosphereAmbientContributionColorScale(Veil.HeldAmbient);",
                 "Fog->SetWorldLocation(Veil.HeldLocation);"):
        assert line in body


def test_commandlet_wraps_both_sky_captures():
    calls = [m.start() for m in re.finditer(r"USkyLightComponent::UpdateSkyCaptureContents\(World\);", COMMANDLET)]
    assert len(calls) == 2
    for at in calls:
        before = COMMANDLET[at - 1200:at]
        after = COMMANDLET[at:at + 600]
        assert "WorldBeauty.SuspendSkyGradientForCapture()" in before
        assert "WorldBeauty.ResumeSkyGradientAfterCapture();" in after
    assert 'SetObjectField(TEXT("sky_capture_veil"), SkyVeilRecord);' in COMMANDLET


def test_api_pins():
    for name in ("sky-capture-veil: Fog SetFogHeightFalloff", "sky-capture-veil: Fog SetFogDensity",
                 "sky-capture-veil: the capture is one static call",
                 "sky-capture-veil: the sky light capture is a game-flag scene render (fog drawn)"):
        assert name in API
