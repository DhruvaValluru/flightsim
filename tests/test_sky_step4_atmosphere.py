"""Sky step 4 (the owner's X-Plane-12 brief, 2026-11-15): atmosphere, horizon haze
and sun bloom. BEAUTY ONLY (FFlightSimWorldBeauty::ApplyAtmosphere / Advance and
FFlightSimHeroLighting::Apply); the measure path's scene fog, sky and sun are
untouched (pinned below). Nothing here was rendered: every visual outcome is
UNMEASURED and every look value UNCALIBRATED; the exact Windows commands are in
docs/VISUAL_FIDELITY_PLAN.md "Sky step 4".

What the step does, and what these tests pin to one another:

1. The height fog's VERTICAL PROFILE. Read in the UE 5.7 source: the engine draws
   FogDensity/1000 per cm x 2^(-FogHeightFalloff/1000 x cm above the fog's
   height) (SceneCore.cpp, HeightFogCommon.ush), OVER the sky atmosphere
   (DeferredShadingRenderer.cpp RenderSkyAtmosphere then RenderFog), and a sky
   pixel's fog is the ray's whole line integral capped at FogMaxOpacity. The
   scene's falloff 0.0002 is a 72 km scale height, so every sky pixel from every
   camera took 0.92 of one flat in-scatter colour: the owner's "flat navy frame"
   and "no horizon haze". The clear and hazy rows now give the fog the Mie layer's
   scale height (ATMOSPHERE fog_scale_height_km == mie_scale_height_km), with the
   density at the scene's fog height kept (the Koschmieder count at the ground is
   unchanged) and the fog's reference height following the aircraft, because the
   engine clamps the fog's observer to 655.36 m above the fog height and shifts
   the ray by the excess (FogRendering.cpp MaxObserverHeightDifference). The C++
   laws (FlightSimWorldPure::FogHeightFalloffFor, FogDensityRebased,
   FogReferenceZM) are compiled with g++ and compared with world_beauty.py's.
2. -sky-multi-scatter=auto|on|off: the row's MultiScatteringFactor on every GPU
   class (auto, on) or the scene's 1.0 (off). The class gate ef361bd6 left is
   lifted because the factor is one multiply in the multi-scattering LUT pass
   (SkyAtmosphere.usf) the atmosphere runs every frame anyway, in no per-pixel
   shader: no new submission on the iGPU. UNMEASURED; the first Windows round is
   the A/B.
3. (The sun bloom per world preset was left out of claude/hl-sky: FlightSimHeroLighting.cpp
   belongs to the hero-lighting lane.)
4. render.json: look_applied.world_beauty.atmosphere.horizon_haze, .aerial_perspective,
   the multi-scatter keys, per-fog before/after rows, Advance's fog_reference_z_m;
"""
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import config_surface
from core.scene import hero_lighting as hl
from core.scene import world_beauty as wb

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
CPP = PRIVATE / "FlightSimClouds.cpp"
HEADER = PUBLIC / "FlightSimClouds.h"
HERO = PRIVATE / "FlightSimHeroLighting.cpp"
SCENE_CPP = PRIVATE / "FlightSimVisualScene.cpp"
SKY_CPP = PRIVATE / "FlightSimSky.cpp"
WEATHER_CPP = PRIVATE / "FlightSimWeather.cpp"
CHECK = ROOT / "scripts/check_bridge_api.sh"
CATALOG = ROOT / "core/messages/catalog.yaml"
VFP = ROOT / "docs/VISUAL_FIDELITY_PLAN.md"
DESIGN = ROOT / "docs/visual/XPLANE_SKY_DESIGN.md"

NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")

NEW_FIELDS = ("fog_scale_height_km", "fog_start_distance_m", "fog_max_opacity")
PROFILE_PRESETS = ("clear", "hazy")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(text: str, begin: str, end: str) -> str:
    start = text.index(begin) + len(begin)
    return text[start:text.index(end, start)]


def _compile_and_run(tmp_path, block, main):
    source = tmp_path / "pure.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + main, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-o", str(tmp_path / "pure"), str(source)],
                   check=True, capture_output=True, text=True)
    return subprocess.run([str(tmp_path / "pure")], check=True, capture_output=True, text=True).stdout.splitlines()


# -- the rows ----------------------------------------------------------------------------

def test_the_three_fields_are_appended_and_every_row_states_them():
    assert wb.ATMOSPHERE_FIELDS[-3:] == NEW_FIELDS
    assert len(wb.ATMOSPHERE_FIELDS) == 16
    for preset in wb.PRESETS:
        row = wb.ATMOSPHERE[preset]
        assert set(row) == set(wb.ATMOSPHERE_FIELDS), preset
        # start distance and max opacity are the scene's own: a recorded knob, no move
        assert row["fog_start_distance_m"] == wb.SCENE_FOG_START_DISTANCE_M
        assert row["fog_max_opacity"] == wb.SCENE_FOG_MAX_OPACITY
    # the fair-weather rows give the fog the Mie layer's scale height; the weather rows keep the scene's fog
    for preset in PROFILE_PRESETS:
        assert wb.ATMOSPHERE[preset]["fog_scale_height_km"] == wb.ATMOSPHERE[preset]["mie_scale_height_km"] > 0.0
    for preset in ("overcast", "rain", "storm"):
        assert wb.ATMOSPHERE[preset]["fog_scale_height_km"] == 0.0
    # the overrides file may name them
    assert wb.validate_overrides({"atmosphere": {"clear": {"fog_scale_height_km": 2.0}}}) == []


def test_the_scene_constants_are_the_scene_hosts_literals():
    """The measure path's fog (FlightSimVisualScene.cpp) is what the rows restate."""
    scene = _read(SCENE_CPP)
    assert "FogComponent->SetFogHeightFalloff(0.0002f);" in scene
    assert "FogComponent->SetFogMaxOpacity(0.92f);" in scene
    assert "FogComponent->SetStartDistance(1500.0f * SceneCmPerMetre);" in scene
    assert wb.SCENE_FOG_HEIGHT_FALLOFF == 0.0002
    assert wb.SCENE_FOG_MAX_OPACITY == 0.92
    assert wb.SCENE_FOG_START_DISTANCE_M == 1500.0


# -- the laws in Python --------------------------------------------------------------------

def test_the_falloff_draws_the_scale_height_it_names():
    """density(z) = D x 2^(-falloff x z_m / 10): at z = the scale height the
    density is D / e, and the scene's 0.0002 is a 72 km scale height."""
    for km in (0.8, 1.0, 1.2, 1.6, 2.5):
        falloff = wb.fog_height_falloff(km)
        assert wb.fog_density_rebased(1.0, falloff, 0.0, km * 1000.0) == pytest.approx(math.exp(-1.0))
        assert wb.fog_scale_height_km(falloff) == pytest.approx(km)
    assert wb.fog_height_falloff(0.0) == wb.SCENE_FOG_HEIGHT_FALLOFF
    assert wb.fog_height_falloff(-1.0) == wb.SCENE_FOG_HEIGHT_FALLOFF
    assert wb.fog_scale_height_km(wb.SCENE_FOG_HEIGHT_FALLOFF) == pytest.approx(72.13, abs=0.01)
    assert wb.fog_height_falloff(1.2) == pytest.approx(0.012023, abs=1e-6)


def test_the_rebase_keeps_the_ground_density_and_composes():
    """Moving the fog's reference height and rebasing its density draws the
    same profile in world space; two rebases compose; the scene height is kept
    as the reference below the aircraft."""
    falloff = wb.fog_height_falloff(1.2)
    d0 = 0.0025
    d1 = wb.fog_density_rebased(d0, falloff, 0.0, 10000.0)
    assert d1 < d0 / 1000.0                                   # a cruise camera sits in near-clean air
    assert wb.fog_density_rebased(d1, falloff, 10000.0, 0.0) == pytest.approx(d0)   # the ground density is kept
    via = wb.fog_density_rebased(wb.fog_density_rebased(d0, falloff, 0.0, 600.0), falloff, 600.0, 10000.0)
    assert via == pytest.approx(d1)
    assert wb.fog_density_rebased(d0, falloff, 0.0, 0.0) == d0
    assert wb.fog_reference_z_m(0.0, 10000.0, True) == 10000.0
    assert wb.fog_reference_z_m(0.0, 10000.0, False) == 0.0
    assert wb.fog_reference_z_m(0.0, -50.0, True) == 0.0        # never below the scene's fog height
    assert wb.fog_reference_z_m(300.0, 200.0, True) == 300.0


def test_the_zenith_clears_and_the_horizon_keeps_the_band():
    """A reading of HeightFogCommon.ush, not a render: under the scene's fog the
    straight-up integral is unbounded (the sky took the max opacity in every
    direction); under the clear row's profile a 600 m camera keeps ~13 % fog at
    the zenith and the horizon ray is still unbounded (the pale band)."""
    d0 = 0.0025   # the commandlet's default FogDensity
    assert wb.fog_zenith_optical_depth(d0, 0.0) == math.inf
    # the scene's falloff: 2^-(0.0025 / 0.0002) = 2^-12.5: the max opacity in every direction
    assert 2.0 ** -wb.fog_zenith_optical_depth(d0, wb.SCENE_FOG_HEIGHT_FALLOFF) < 1.0 - wb.SCENE_FOG_MAX_OPACITY
    falloff = wb.fog_height_falloff(wb.ATMOSPHERE["clear"]["fog_scale_height_km"])
    tau_600 = wb.fog_zenith_optical_depth(d0, falloff, 600.0)
    assert 0.05 < 1.0 - 2.0 ** -tau_600 < 0.2
    tau_cruise = wb.fog_zenith_optical_depth(d0, falloff, 10000.0)
    assert 1.0 - 2.0 ** -tau_cruise < 0.001
    # a horizontal ray has no z and the shader's closed form grows with its length: the band stays


def test_the_multi_scatter_switch_law():
    assert wb.SKY_MULTI_SCATTER_SWITCH == "-sky-multi-scatter"
    assert wb.SKY_MULTI_SCATTER_SWITCH_WORDS == ("auto", "on", "off")
    for constrained in (False, True):
        assert wb.sky_multi_scatter_applies("auto", constrained) is (not constrained)
        assert wb.sky_multi_scatter_applies(None, constrained) is (not constrained)
        assert wb.sky_multi_scatter_applies("on", constrained) is True
        assert wb.sky_multi_scatter_applies("off", constrained) is False
        assert wb.sky_multi_scatter_applies("probe", constrained) is None
    assert wb.SKY_MULTI_SCATTERING == {"clear": 1.25, "hazy": 1.15, "overcast": 1.0, "rain": 1.0, "storm": 1.0}


def test_the_cpp_fog_profile_and_switch_laws_are_the_python_ones(tmp_path):
    block = _block(_read(CPP), "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    assert "#include" not in block and "FString" not in block and "TEXT(" not in block
    heights = (0.0, -1.0, 0.8, 1.2, 1.6, 2.5)
    rebases = [(d, f, a, b) for d in (0.0025, 0.012) for f in (0.0002, 0.012023, 0.009) for a, b in
               ((0.0, 600.0), (0.0, 10000.0), (600.0, 0.0), (10000.0, 0.0), (0.0, 0.0), (300.0, 2300.0))]
    refs = [(s, a, p) for s in (0.0, 300.0) for a in (-50.0, 200.0, 10000.0) for p in (0, 1)]
    words = ("auto", "on", "off", "probe", "ON")
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            "printf(\"n %d\\n\", AtmosphereFieldCount);",
            "for (int f = 13; f < AtmosphereFieldCount; ++f) printf(\"name %s\\n\", AtmosphereFieldName(f));",
            "printf(\"const %.17g %.17g %.17g %.17g %.17g %.17g\\n\", SceneFogHeightFalloff, SceneFogStartDistanceM,"
            " SceneFogMaxOpacity, FogObserverClampM, FogRebaseStepM, FogFalloffPerScaleHeightKm);",
            "for (int i = 0; i < SkyMultiScatterWordCount; ++i) printf(\"word %s\\n\", SkyMultiScatterWord(i));"]
    main += [f"printf(\"falloff %.17g\\n\", FogHeightFalloffFor({h!r}));" for h in heights]
    main += [f"printf(\"rebase %.17g\\n\", FogDensityRebased({d!r}, {f!r}, {a!r}, {b!r}));" for d, f, a, b in rebases]
    main += [f"printf(\"ref %.17g\\n\", FogReferenceZM({s!r}, {a!r}, {'true' if p else 'false'}));" for s, a, p in refs]
    main += [f"printf(\"ms %d %d\\n\", SkyMultiScatterFor(\"{w}\", {c}), {c});" for w in words for c in ("false", "true")]
    main.append("printf(\"ms %d 0\\n\", SkyMultiScatterFor(nullptr, false));")
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, block, "\n".join(main))
    assert [l for l in lines if l.startswith("n ")] == [f"n {len(wb.ATMOSPHERE_FIELDS)}"]
    assert [l.split()[1] for l in lines if l.startswith("name ")] == list(NEW_FIELDS)
    const = [float(v) for v in next(l for l in lines if l.startswith("const ")).split()[1:]]
    assert const[:5] == [wb.SCENE_FOG_HEIGHT_FALLOFF, wb.SCENE_FOG_START_DISTANCE_M, wb.SCENE_FOG_MAX_OPACITY,
                         wb.FOG_OBSERVER_CLAMP_M, wb.FOG_REBASE_STEP_M]
    assert const[5] == pytest.approx(wb.FOG_FALLOFF_PER_SCALE_HEIGHT_KM, rel=1e-15)
    assert [l.split()[1] for l in lines if l.startswith("word ")] == list(wb.SKY_MULTI_SCATTER_SWITCH_WORDS)
    got = [float(l.split()[1]) for l in lines if l.startswith("falloff ")]
    assert got == pytest.approx([wb.fog_height_falloff(h) for h in heights], rel=1e-15)
    got = [float(l.split()[1]) for l in lines if l.startswith("rebase ")]
    assert got == pytest.approx([wb.fog_density_rebased(*case) for case in rebases], rel=1e-14)
    got = [float(l.split()[1]) for l in lines if l.startswith("ref ")]
    assert got == [wb.fog_reference_z_m(s, a, bool(p)) for s, a, p in refs]
    ms = [(int(a), int(c)) for _, a, c in (l.split() for l in lines if l.startswith("ms "))]
    expect = {True: 1, False: 0, None: -1}
    assert ms == [(expect[wb.sky_multi_scatter_applies(w, bool(c))], c) for w in words for c in (0, 1)] + [(1, 0)]


# -- the host ----------------------------------------------------------------------------------

def _apply_atmosphere() -> str:
    cpp = _read(CPP)
    return cpp[cpp.index("void FFlightSimWorldBeauty::ApplyAtmosphere"):cpp.index("void FFlightSimWorldBeauty::ApplyClouds")]


def test_the_host_gives_the_fog_its_profile_rebased_at_the_aircraft_and_records_it():
    body = _apply_atmosphere()
    header = _read(HEADER)
    assert "AActor* Aircraft)" in body.splitlines()[1] or "AActor* Aircraft" in body[:400]
    assert "void ApplyAtmosphere(UWorld* World, FFlightSimVisualScene& Scene, double VisibilityKm, AActor* Aircraft);" in header
    assert "ApplyAtmosphere(World, Scene, VisibilityKm, Aircraft);" in _read(CPP)
    # the row's three fields drive the three setters, through the pure laws
    assert "const double FogFalloff = FogHeightFalloffFor(FogScaleHeightKm);" in body
    assert "const double FogScaleHeightKm = Row[AtmFogScaleHeightKm];" in body
    assert "Fog->SetFogHeightFalloff(static_cast<float>(FogFalloff));" in body
    assert "Fog->SetStartDistance(static_cast<float>(Row[AtmFogStartDistanceM] * WorldCmPerMetre));" in body
    assert "Fog->SetFogMaxOpacity(static_cast<float>(Row[AtmFogMaxOpacity]));" in body
    # the density is rebased AFTER the Koschmieder share (fog_density x FogFactor) and the component moves
    share = body.index("Fog->SetFogDensity(static_cast<float>(Fog->FogDensity * FogFactor));")
    rebase = body.index("const double Rebased = FogDensityRebased(Fog->FogDensity, FogFalloff, SceneZM, ReferenceZM);")
    assert share < rebase
    assert "const double ReferenceZM = FogReferenceZM(SceneZM, AircraftZM, bFogProfile && bAircraftKnown);" in body
    assert "Fog->SetWorldLocation(FVector(FogLocation.X, FogLocation.Y, ReferenceZM * WorldCmPerMetre));" in body
    assert body.count("Fog->MarkRenderStateDirty();") >= 1
    assert "FogProfiles.Add(Profile);" in body and "FogProfiles.Reset();" in body
    # the record: the horizon-haze block and per-fog before/after
    for key in ("profile_applied", "fog_scale_height_km", "fog_height_falloff", "fog_height_falloff_scene",
                "fog_start_distance_m", "fog_max_opacity", "observer_clamp_m", "rebase_step_m", "aircraft_known",
                "aircraft_z_m", "fog_components", "calibration"):
        assert f'Haze->SetNumberField(TEXT("{key}")' in body or f'Haze->SetBoolField(TEXT("{key}")' in body \
            or f'Haze->SetStringField(TEXT("{key}")' in body, key
    assert 'Out->SetObjectField(TEXT("horizon_haze"), Haze);' in body
    for key in ("fog_height_falloff_before", "fog_height_z_m_scene", "fog_density_at_scene_height", "fog_height_falloff",
                "fog_height_z_m", "fog_start_distance_m_before", "fog_max_opacity_before", "fog_start_distance_m",
                "fog_max_opacity", "fog_density_after"):
        assert f'FogRow->SetNumberField(TEXT("{key}")' in body, key
    assert 'Out->SetObjectField(TEXT("aerial_perspective"), Aerial);' in body
    assert 'Aerial->SetNumberField(TEXT("view_distance_scale"), Row[AtmAerialPerspectiveScale]);' in body
    assert "UNCALIBRATED" in body and "UNMEASURED" in body
    # the header carries the per-fog profile state Advance re-bases
    assert "TWeakObjectPtr<UExponentialHeightFogComponent> Fog;" in header
    assert "TArray<FBeautyFogProfile> FogProfiles;" in header
    assert "class UExponentialHeightFogComponent;" in header


def test_advance_rebases_the_fog_from_its_current_density():
    cpp = _read(CPP)
    body = cpp[cpp.index("void FFlightSimWorldBeauty::Advance"):]
    body = body[:body.index("// The lightning: both schedules")]
    assert "const double WantZM = FogReferenceZM(Profile.SceneZM, AircraftZM, true);" in body
    assert "if (FMath::Abs(WantZM - CurrentZM) >= FogRebaseStepM)" in body
    # from the CURRENT density: translation-invariant, so the dust haze's later ratio is kept
    assert "FogDensityRebased(Fog->FogDensity, Profile.Falloff, CurrentZM, WantZM)" in body
    assert "Fog->SetWorldLocation(FVector(FogLocation.X, FogLocation.Y, WantZM * WorldCmPerMetre));" in body
    assert 'Frame->SetNumberField(TEXT("fog_reference_z_m")' in body
    assert 'Frame->SetNumberField(TEXT("fog_rebased"), Rebased);' in body


def test_the_dust_haze_and_the_rain_haze_read_the_fogs_height_live():
    """Both compose on the moved fog: they read GetComponentLocation().Z after
    ApplyAtmosphere, never a cached scene height."""
    dust = _read(PRIVATE / "FlightSimDustHaze.cpp")
    assert "Fogs[0]->GetComponentLocation().Z / 100.0" in dust
    cpp = _read(CPP)
    assert "const double FogZM = Fog->GetComponentLocation().Z / WorldCmPerMetre;" in cpp
    # order in Build: the atmosphere (the profile) before the dust haze and the rain veil
    build = cpp[cpp.index("bool FFlightSimWorldBeauty::Build"):cpp.index("void FFlightSimWorldBeauty::RestoreCvars")]
    assert build.index("ApplyAtmosphere(World, Scene, VisibilityKm, Aircraft);") < build.index("DustHaze.Apply(")
    assert build.index("ApplyAtmosphere(World, Scene, VisibilityKm, Aircraft);") < build.index("FFlightSimWeather::RainHazeFog(")


def test_the_multi_scatter_switch_is_parsed_refused_applied_and_recorded():
    cpp = _read(CPP)
    build = cpp[cpp.index("bool FFlightSimWorldBeauty::Build"):cpp.index("void FFlightSimWorldBeauty::RestoreCvars")]
    assert 'SkyMultiScatterSwitch = TEXT("auto");' in build
    assert 'FParse::Value(*Switches, TEXT("sky-multi-scatter="), SkyMultiScatterSwitch);' in build
    assert "if (SkyMultiScatterFor(TCHAR_TO_ANSI(*SkyMultiScatterSwitch), false) < 0)" in build
    assert 'TEXT("world_beauty.clouds: -sky-multi-scatter=%s is not auto, on or off")' in build
    body = _apply_atmosphere()
    assert "const int32 MultiScatter = SkyMultiScatterFor(TCHAR_TO_ANSI(*SkyMultiScatterSwitch), CloudConstrainedGpu());" in body
    assert "if (MultiScatter == 1)" in body
    assert "Atmosphere->SetMultiScatteringFactor(static_cast<float>(SkyMultiScattering(Preset)));" in body
    for key in ("multi_scattering_factor_before", "multi_scattering_factor", "multi_scattering_switch",
                "multi_scattering_applied", "multi_scattering_constrained_gpu", "multi_scattering_basis",
                "multi_scattering_gate_basis"):
        assert f'TEXT("{key}")' in body, key
    assert 'FString SkyMultiScatterSwitch = TEXT("auto");' in _read(HEADER)
    # registered and catalogued
    note = config_surface.by_key("render_switches").note
    assert "-sky-multi-scatter=auto|on|off" in note and "SKY_MULTI_SCATTER_SWITCH_WORDS" in note
    catalog = _block(_read(CATALOG), "world_beauty.clouds:", "world_beauty.distant_clouds:")
    assert "-sky-multi-scatter=" in catalog
    for word in wb.SKY_MULTI_SCATTER_SWITCH_WORDS:
        assert word in catalog, word


def test_the_measure_path_never_sees_the_profile_or_the_switch():
    for path in (SCENE_CPP, SKY_CPP, WEATHER_CPP):
        text = _read(path)
        for needle in ("FogHeightFalloffFor", "FogDensityRebased", "FogReferenceZM", "sky-multi-scatter",
                       "SkyMultiScatterFor", "fog_scale_height_km", "SetMultiScatteringFactor"):
            assert needle not in text, (path.name, needle)
    # the scene still builds the fog as before, in every quality
    scene = _read(SCENE_CPP)
    assert "Atmosphere->MultiScatteringFactor = 1.0f;" in scene
    # exposure: plan.py's EV100 and beauty_look's meters are not in this step's files
    plan = _read(ROOT / "core/sky/plan.py")
    assert "fog_scale_height" not in plan and "multi_scatter" not in plan
    for name in ("FogHeightFalloffFor", "SkyMultiScatterFor", "SHAFT_BLOOM"):
        assert name not in _read(ROOT / "core/scene/beauty_look.py")
        assert name not in _read(ROOT / "core/capture/beauty_look.py")


def test_the_bridge_check_and_the_docs():
    check = _read(CHECK)
    block = check[check.index("# Sky step 4 (the owner's X-Plane-12 brief)"):check.index("# The sky HDRI probe")]
    for needle in ("SetFogHeightFalloff(float Value);", "SetStartDistance(float Value);", "SetFogMaxOpacity(float Value);",
                   "FogData[0].HeightFalloff = State.FogHeightFalloff / 1000.0f;",
                   "float MaxObserverHeightDifference = 65536.0f;",
                   "MultiScatteredLuminanceLutUAV[int2(PixPos)] = L * Atmosphere.MultiScatteringFactor;",
                   "RenderFog(GraphBuilder, SceneTextures, LightShaftOcclusionTexture, bFogComposeLocalFogVolumes);",
                   "SendRenderTransform_Concurrent()", "SetWorldLocation(FVector NewLocation"):
        assert needle in block, needle
    vfp = _read(VFP)
    entry = vfp[vfp.index("### Sky step 4"):]
    for needle in ("UNMEASURED", "UNCALIBRATED", "-sky-multi-scatter=off", "visual_fix_round.ps1", "fog_scale_height_km",
                   "horizon_haze", "65536", "FogMaxOpacity", "light_shaft_bloom", "887a0006"):
        assert needle in entry, needle
    design = _read(DESIGN)
    assert "Built (sky step 4" in design
    assert "MaxObserverHeightDifference" in design
