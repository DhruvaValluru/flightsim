"""Round 5 (2026-11-10): #02 "same, super bright preset" still blue after the
neutral fill; the cause is not the sky light's colour.

Round 3's frames (b6a9aff2, Windows, D3D11 SM5, the round-4 neutral fill
applied: render.json ``stated_fill`` 1/0.497/0.250) measure the same as round
2's (mean sRGB 95/102/159 against 96/102/157). Diffed plan to plan on this Mac
(scripts in this test: the same calls webapp.runs._render makes), #01 and #02
differ in exactly: the relit sun (6 -> 72 deg), the exposure (EV100 11.60 ->
13.57, 1.7 stops over the physical meter), the four knob flags, the haze
(0.0012 -> 0.0005), the grade (golden_hour -> desert_noon, both neutral gain)
and this lane's fill. On the frame the shade is Rayleigh-coloured in every
horizontal band (R/B 0.06-0.12 on the JPEG, scene-linear about 0.18) while the
airframe a few metres from the camera is neutral, and the engine multiplies
the sky light's colour per frame (View.SkyLightColor, SkyLightingDiffuseShared
.ush; nothing in the bridge sets it after the hero lane). So the shade is lit
by the atmosphere's in-scatter between camera and ground, with no visible
fill under it: the fill rounds 3 and 4 tinted was never what coloured it.

Pinned here: the diff (so the next round starts from it), the host's order
(the fill colour is the last word on the sky light's colour), the round-5
probes the host reads (names and words, one Python twin), the capture
witnesses in render.json, and that measure never sees any of it. What is NOT
measured: which of "the fill does not reach the ground" and "the in-scatter
outruns it" holds on the render machine (PROBE_LOG round 5, probes r5-*).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.render.flags import lighting_flags, render_flags
from core.scene import hero_lighting as hl

from tests.test_presets_colour import YOSEMITE, edited, write_sky

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
HERO_CPP = (PRIVATE / "FlightSimHeroLighting.cpp").read_text(encoding="utf-8")
SCENE_CPP = (PRIVATE / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
COMMANDLET_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
API = (REPO / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")


def _plan(tmp_path: Path, name: str, **edits):
    """What webapp.runs._render hands the commandlet for one Yosemite scene on
    the physical sky at beauty: the look, sky.json, beauty_look.json, the hero
    sidecar and the flag list (the same builders, in the same order)."""
    import webapp.runs as runs

    out = tmp_path / name
    out.mkdir()
    spec = edited(YOSEMITE, **edits)
    sky = write_sky(spec, out)
    look = runs.relight_sky_plan(spec, sky, None)
    beauty = runs.write_beauty_look_plan(spec, out, look, sky=sky, quality="beauty")
    hero = hl.write_sidecar_beside(spec, beauty)
    look = hl.with_stated_fill_scale(look, beauty)
    extra = lighting_flags(look) + runs.beauty_look_render_flags(beauty) + hl.flags_beside(beauty)
    flags = render_flags(out / "card.json", out / "frames", scene={}, mesh=None, look=look,
                         camera_flags=((), ()), labels=False, deterministic=True,
                         width=1920, height=1080, fps=30, quality="beauty", sky=sky,
                         triangle_budget=None, telemetry=None, extra=extra)
    return {"look": look, "sky": json.loads(sky.read_text(encoding="ascii")),
            "beauty": json.loads(beauty.read_text(encoding="utf-8")),
            "hero": json.loads(hero.read_text(encoding="utf-8")),
            "flags": [f.split("=")[0] if f.startswith(("-scenario=", "-frames=", "-sky=",
                                                        "-beauty-look=", "-hero-lighting="))
                      else f for f in flags]}


# -- the diff that matters ------------------------------------------------------------


def test_02_differs_from_01_only_in_the_sun_the_exposure_the_knobs_and_the_fill(tmp_path):
    golden = _plan(tmp_path, "01")
    bright = _plan(tmp_path, "02", preset="super_bright")
    # The command: the knob flags and the haze are the only new or changed tokens.
    added = sorted(set(bright["flags"]) - set(golden["flags"]))
    removed = sorted(set(golden["flags"]) - set(bright["flags"]))
    assert added == ["-fog-density=0.0005", "-sky-light-scale=1.90231", "-sun-intensity-scale=1.6",
                     "-sun-source-angle=0.45", "-sun-temperature=6300"]
    assert removed == ["-fog-density=0.0012"]
    # The sky: the sun relit to 72 deg, the meter 3.7 stops up; the atmosphere, clouds and fog untouched.
    assert (golden["sky"]["sun"]["elevation_deg"], bright["sky"]["sun"]["elevation_deg"]) == (6.0, 72.0)
    assert bright["sky"]["exposure"]["relit_from_ev100"] == golden["sky"]["exposure"]["ev100"]
    for key in ("clouds", "fog", "lighting", "post_process", "observer"):
        assert bright["sky"][key] == golden["sky"][key]
    assert bright["sky"]["fog"] == {"inscattering": "sky-atmosphere ambient contribution (dims with the sun)"}
    # The beauty look: the exposure opens 1.7 stops over the physical meter; the grade is neutral.
    ex = bright["beauty"]["exposure"]
    assert ex["base_ev100"] - ex["ev100"] == pytest.approx(0.6 + ex["relit_sun_open_stops"], abs=1e-3)
    assert ex["relit_sun_open_stops"] == pytest.approx(1.1022, abs=1e-3)
    grade = bright["beauty"]["color_grade"]
    assert bright["beauty"]["grade"] == "desert_noon" and golden["beauty"]["grade"] == "golden_hour"
    assert grade["WhiteTemp"] == 6500.0 and grade["WhiteTint"] == 0.0        # the engine's neutral
    assert grade["ColorGain"] == [1.0, 1.0, 1.0, 1.0] and grade["ColorOffset"] == [0.0, 0.0, 0.0, 0.0]
    assert bright["beauty"]["tonemap"] == golden["beauty"]["tonemap"]
    # The hero sidecar: the fill (neutral, round 4) and the ground compensation are #02's only extras.
    assert "sky_light" not in golden["hero"] and "sky_light" in bright["hero"]
    assert bright["hero"]["sky_light"]["color_linear_rgb"] == pytest.approx([1.0, 0.708376, 0.502886], abs=1e-6)   # round 75: share 0.5
    assert bright["hero"]["sky_light"]["intensity_scale"] == pytest.approx(1.409122, abs=1e-6)   # round 75: share 0.5
    assert set(bright["hero"]) - set(golden["hero"]) == {"sky_light"}


# -- the fill's colour reaches the frame: nothing after the hero lane changes it ----------


def test_the_hero_lanes_fill_colour_is_the_last_word_on_the_sky_lights_colour():
    # The X-Plane ambient colour (white in beauty) is set in VisualScene.Build ...
    assert SCENE_CPP.index("SkyComponent->SetLightColor(Ambient);") < SCENE_CPP.index(
        "if (Options.SunIntensityScale >= 0.0 || Options.SkyLightScale >= 0.0 ||")
    # ... which the commandlet runs before the hero lane; the sky capture comes after both.
    build = COMMANDLET_CPP.index("if (!VisualScene.Build(World, SceneOptions, Error))")
    hero = COMMANDLET_CPP.index("FFlightSimHeroLighting::Apply(VisualScene, Capture, bPathTrace, *Params)")
    capture = COMMANDLET_CPP.index("USkyLightComponent::UpdateSkyCaptureContents(World);")
    assert build < hero < capture
    # No other SetLightColor on the sky light anywhere in the bridge after the hero lane's.
    after_hero = COMMANDLET_CPP[hero:]
    assert "SkyLightComponent->SetLightColor" not in after_hero
    for name in ("FlightSimBeautyFallback.cpp", "FlightSimClouds.cpp", "FlightSimSky.cpp",
                 "FlightSimWeatherLook.cpp", "FlightSimSunShafts.cpp", "FlightSimGoogleTiles.cpp"):
        text = (PRIVATE / name).read_text(encoding="utf-8")
        assert "Sky->SetLightColor" not in text and "SkyLight->SetLightColor" not in text, name
    # The beauty fallback restores only the intensity and min occlusion around the capture.
    fallback = (PRIVATE / "FlightSimBeautyFallback.cpp").read_text(encoding="utf-8")
    suspend = fallback[fallback.index("SuspendForSkyCapture(FFlightSimVisualScene& Scene)"):]
    assert "SetLightColor" not in suspend and "SetLowerHemisphereColor" not in suspend


# -- the round-5 probes: one Python twin, read by the host --------------------------------


def test_the_host_reads_the_probes_the_python_twin_names():
    # From the sky light block: -storm-lower-hemisphere= (2026-11-11) is read where the ground is drawn.
    sky = HERO_CPP[HERO_CPP.index("// -- the sky light"):HERO_CPP.index('SkyRecord->SetObjectField(TEXT("probes"), Probe);')]
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in sky
    for name, words in hl.DIAGNOSTIC_SWITCHES.items():
        assert f'TEXT("{name}=")' in sky, name
        for word in words or ():
            assert f'TEXT("{word}")' in sky, (name, word)
    assert "Sky->SetLightColor(FLinearColor(1.0f, 0.0f, 0.0f, 1.0f));" in sky      # red
    assert "Sky->SetLightColor(FLinearColor::Black);" in sky                        # off
    assert "SetIntensity(" not in HERO_CPP                 # the lane never changes an intensity
    assert "Sky->bCloudAmbientOcclusion = false;" in sky
    assert "Scene.Atmosphere->SetAerialPespectiveViewDistanceScale(static_cast<float>(AerialScale));" in sky
    assert sky.count("render.sky_fill_probe:") == 5                                 # every refusal by name
    # Outside the stated-fill slice round 3 pins ("the lane never changes an intensity"):
    fill = HERO_CPP[HERO_CPP.index('TryGetObjectField(TEXT("sky_light"), SkyFill)'):]
    assert "SetIntensity(" not in fill[:fill.index("Sky->SetCaptureIsDirty();")]
    # The probes are the hero lane's, which the commandlet runs for beauty only.
    assert "if (bVisual && bBeauty && !FFlightSimHeroLighting::Apply(" in COMMANDLET_CPP
    for check in ("hero: SkyLight GetProcessedSkyTexture", "hero: SkyLight bCloudAmbientOcclusion",
                  "hero: SkyAtmosphere SetAerialPespectiveViewDistanceScale"):
        assert check in API


def test_parse_diagnostic_switches_matches_the_host():
    assert hl.parse_diagnostic_switches("") == {}
    assert hl.parse_diagnostic_switches("-sky-capture-restore=on -gpu-drain=auto") == {}
    assert hl.parse_diagnostic_switches("-sky-fill-probe=red") == {"sky-fill-probe": "red"}
    assert hl.parse_diagnostic_switches(" -sky-cloud-ao=off -aerial-perspective-scale=0") == {
        "sky-cloud-ao": "off", "aerial-perspective-scale": 0.0}
    assert hl.parse_diagnostic_switches("-aerial-perspective-scale=2.5") == {"aerial-perspective-scale": 2.5}
    for bad in ("-sky-fill-probe=blue", "-sky-cloud-ao=maybe", "-aerial-perspective-scale=-1",
                "-aerial-perspective-scale=x", "-aerial-perspective-scale=nan"):
        with pytest.raises(hl.HeroLightingError, match="render.sky_fill_probe"):
            hl.parse_diagnostic_switches(bad)


# -- the capture witnesses in render.json ---------------------------------------------------


def test_the_commandlet_witnesses_the_sky_light_capture():
    start = COMMANDLET_CPP.index("const bool bShadersCompilingAtSkyCapture =")
    block = COMMANDLET_CPP[start:COMMANDLET_CPP.index('SetObjectField(TEXT("sky_light_capture_result")')]
    assert block.index("GShaderCompilingManager->IsCompiling()") < block.index(
        "USkyLightComponent::UpdateSkyCaptureContents(World);")
    for field in ("processed_texture", "shaders_compiling_at_capture", "real_time_capture",
                  "intensity_at_capture", "light_color_linear", "lower_hemisphere_solid",
                  "cloud_ambient_occlusion", "min_occlusion"):
        assert f'TEXT("{field}")' in block, field
    assert "SkyAfter->GetProcessedSkyTexture() != nullptr" in block


def test_measure_never_gets_a_probe_or_a_sidecar(tmp_path):
    assert hl.write_sidecar_beside(edited(YOSEMITE, preset="super_bright"), None) is None
    assert hl.flags_beside(None) == []
    # No probe switch is ever emitted by the web app: they are the operator's A/B, by hand.
    runs_py = (REPO / "webapp/runs.py").read_text(encoding="utf-8")
    for name in hl.DIAGNOSTIC_SWITCHES:
        assert f"-{name}=" not in runs_py
