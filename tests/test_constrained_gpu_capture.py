"""Round 1b hang (2026-11-10): the constrained GPU's safeguards in the render
commandlet (source checks; the authoring Mac cannot build UE).

Shot b of the contact sheet (Grand Canyon desert low pass, J-11, 1920 x 1080
at -supersample=2) still hung in the sky light capture on d4e9c7dd. The
render thread's stack is FD3D11DynamicRHI::RHIBlockUntilGPUIdle's unbounded
poll, reached from every cube face (the run's first CPU-GPU sync), so the work
that never finished may have been queued by the warm-up captures as much as by
the capture. Three switches, defaults keeping the fix, beauty raster only:
-constrained-supersample=cap|keep, -sky-capture-restore=auto|on|off,
-gpu-drain=auto|on|off (also read from FLIGHTSIM_RENDER_SWITCHES)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
COMMANDLET = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
CLOUDS = (PRIVATE / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (PUBLIC / "FlightSimClouds.h").read_text(encoding="utf-8")
FALLBACK = (PRIVATE / "FlightSimBeautyFallback.cpp").read_text(encoding="utf-8")
FALLBACK_H = (PRIVATE / "FlightSimBeautyFallback.h").read_text(encoding="utf-8")
TILES = (PRIVATE / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
TILES_H = (PUBLIC / "FlightSimGoogleTiles.h").read_text(encoding="utf-8")
CATALOG = yaml.safe_load((ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8"))


def _body(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start:source.index("\n}\n", start)]


# -- the watchdog ---------------------------------------------------------------

def test_the_watchdog_fires_inside_the_wrappers_560_s_cap():
    assert "constexpr double RenderCaptureTimeoutDefaultS = 300.0;" in COMMANDLET
    assert "900.0" not in COMMANDLET[COMMANDLET.index("// The capture watchdog (round 1 hang"):
                                     COMMANDLET.index("class FRenderCaptureWatchdog")]
    # its line names whether the D3D11 device was removed
    run = COMMANDLET[COMMANDLET.index("virtual uint32 Run() override"):]
    run = run[:run.index("DumpThreadStack(TEXT(\"game\")")]
    assert "*RenderDeviceRemovedNote()" in run
    note = COMMANDLET[COMMANDLET.index("FString RenderDeviceRemovedNote()"):]
    note = note[:note.index("\n\t}\n")]
    assert "Device->GetDeviceRemovedReason()" in note
    assert "RHIGetInterfaceType() == ERHIInterfaceType::D3D11" in note
    assert "#if PLATFORM_WINDOWS" in note


# -- one predicate --------------------------------------------------------------

def test_the_commandlet_reads_the_clouds_constrained_predicate():
    assert "static bool ConstrainedGpu();" in CLOUDS_H
    body = _body(CLOUDS, "bool FFlightSimWorldBeauty::ConstrainedGpu()")
    assert "return CloudConstrainedGpu();" in body
    assert "const bool bBeautyRasterRun = bVisual && bBeauty && !bPathTrace;" in COMMANDLET
    assert ("const bool bConstrainedGpu = bBeautyRasterRun && FFlightSimWorldBeauty::ConstrainedGpu();"
            in COMMANDLET)


# -- the switches ---------------------------------------------------------------

def test_the_switches_default_to_the_fix_and_measure_never_reaches_them():
    for key, default in (("sky-capture-restore=", "auto"), ("gpu-drain=", "auto"),
                         ("constrained-supersample=", "cap")):
        assert f'FParse::Value(*RenderSwitches, TEXT("{key}")' in COMMANDLET, key
    assert 'FString SkyCaptureRestoreMode = TEXT("auto");' in COMMANDLET
    assert 'FString GpuDrainMode = TEXT("auto");' in COMMANDLET
    assert 'FString ConstrainedSupersampleMode = TEXT("cap");' in COMMANDLET
    switch_on = COMMANDLET[COMMANDLET.index("auto SwitchOn = "):]
    switch_on = switch_on[:switch_on.index("};")]
    assert 'bBeautyRasterRun && (Mode == TEXT("on") || (Mode == TEXT("auto") && bConstrainedGpu))' in switch_on
    assert "const bool bSkyCaptureRestore = SwitchOn(SkyCaptureRestoreMode);" in COMMANDLET
    assert "const bool bGpuDrain = SwitchOn(GpuDrainMode);" in COMMANDLET
    # the environment is read on beauty runs only
    assert ('const FString RenderSwitches = bBeauty\n\t\t? Params + TEXT(" ") + '
            'FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))\n\t\t: Params;'
            in COMMANDLET)
    # the round-1 bisection switches ride the same string
    for key in ("sky-capture-start-frame=", "sky-capture-at=", "sky-capture-clouds=",
                "sky-capture-beauty-only=", "sky-capture-tiles=", "sky-capture-primitives="):
        assert f'FParse::Value(*RenderSwitches, TEXT("{key}")' in COMMANDLET, key
        assert f'FParse::Value(*Params, TEXT("{key}")' not in COMMANDLET, key


def test_a_bad_switch_value_refuses_by_its_catalogue_name():
    assert 'TEXT("render.sky_capture_switch: -sky-capture-restore=%s, -gpu-drain=%s: ")' in COMMANDLET
    assert 'TEXT("render.sky_capture_switch: -constrained-supersample=%s is not cap or keep")' in COMMANDLET
    assert "render.sky_capture_switch" in CATALOG
    assert "-gpu-drain" in CATALOG["render.sky_capture_switch"]["hint"]


def test_the_switches_are_logged_on_one_line_and_recorded():
    line = COMMANDLET[COMMANDLET.index('TEXT("constrained gpu: %s (integrated %s, SM6 %s); '):]
    line = line[:line.index(";\n")]
    for word in ("sky-capture-restore %s (%s)", "gpu-drain %s (%s)", "constrained-supersample %s (stated %d"):
        assert word in line, word
    assert 'VisualScene.LookApplied->SetObjectField(TEXT("constrained_gpu"), ConstrainedRecord);' in COMMANDLET
    for key in ("sky_capture_restore", "gpu_drain", "supersample", "gpu_drains", "gpu_drain_longest_s",
                "sky_capture_restore_record"):
        assert f'TEXT("{key}")' in COMMANDLET, key


# -- the supersample cap --------------------------------------------------------

def _fit(width: int, height: int, factor: int, budget: int = 1920 * 1080) -> int:
    """Python mirror of the commandlet's cap loop."""
    while factor > 1 and width * factor * height * factor > budget:
        factor -= 1
    return factor


def test_the_constrained_frame_is_capped_at_the_frame_every_pass_had():
    assert "constexpr int64 RenderConstrainedInternalPixelsMax = 1920 * 1080;" in COMMANDLET
    loop = COMMANDLET[COMMANDLET.index("while (bConstrainedGpu && ConstrainedFactor > 1"):]
    loop = loop[:loop.index("}")]
    assert "> RenderConstrainedInternalPixelsMax" in loop and "--ConstrainedFactor;" in loop
    assert _fit(1920, 1080, 2) == 1          # shot b: 3840 x 2160 internal hung
    assert _fit(1280, 720, 2) == 1           # 2560 x 1440 is over the passing frame too
    assert _fit(960, 540, 2) == 2            # 1920 x 1080 internal: kept
    assert _fit(640, 360, 4) == 3            # 1920 x 1080 at 3: kept at the largest that fits
    # Configure reads the capped string; "keep" leaves -supersample as stated
    assert "FFlightSimSupersample::Configure(*SupersampleParams, Quality," in COMMANDLET
    cap = COMMANDLET[COMMANDLET.index('if (ConstrainedSupersampleMode == TEXT("cap") && ConstrainedFactor != StatedFactor)'):]
    assert "SupersampleParams.ReplaceInline(" in cap[:400]
    assert "FString SupersampleParams = Params;" in COMMANDLET


# -- the bounded drain ----------------------------------------------------------

def test_the_drain_checks_the_hresult_and_the_device():
    drain = COMMANDLET[COMMANDLET.index("FRenderGpuDrain RenderDrainGpu(double TimeoutS)"):]
    drain = drain[:drain.index("\n\t}\n")]
    assert "RHICmdList.ImmediateFlush(EImmediateFlushType::FlushRHIThread);" in drain
    assert "Desc.Query = D3D11_QUERY_EVENT;" in drain
    assert "Hr = Context->GetData(Query, &bComplete, sizeof(bComplete), 0);" in drain
    assert "if (FAILED(Hr))" in drain and "Device->GetDeviceRemovedReason()" in drain
    assert "Result->bTimedOut = true;" in drain
    assert "Query->Release();" in drain and "Context->Release();" in drain
    assert "FlushRenderingCommands();" in drain
    # never FALSE: HideWindowsPlatformTypes.h undefines it
    assert "= FALSE" not in drain
    assert '#include "Windows/AllowWindowsPlatformTypes.h"\n#include <d3d11.h>\n#include "Windows/HideWindowsPlatformTypes.h"' in COMMANDLET


def test_a_lost_device_refuses_by_name_and_ends_the_process():
    lam = COMMANDLET[COMMANDLET.index("auto DrainGpu = [&](const FString& Stage)"):]
    lam = lam[:lam.index("\n\t};\n")]
    assert "if (!bGpuDrain)" in lam
    assert 'TEXT("render.gpu_lost: the D3D11 device was removed while the GPU ran %s' in lam
    assert 'TEXT("render.capture_timeout: the GPU did not finish %s within %.0f s' in lam
    assert "::TerminateProcess(::GetCurrentProcess(), 4);" in lam and "std::_Exit(4);" in lam
    assert "RenderDrainGpu(GpuDrainTimeoutS)" in lam
    assert "const double GpuDrainTimeoutS = CaptureTimeoutS > 0.0 ? 0.8 * CaptureTimeoutS : 0.0;" in COMMANDLET
    for name in ("render.gpu_lost", "render.capture_timeout"):
        assert name in CATALOG, name


def test_every_warm_up_and_the_sky_capture_are_drained_where_they_were_queued():
    warm = COMMANDLET[COMMANDLET.index("for (int32 i = 0; i < WarmupCaptures; ++i)"):]
    warm = warm[:warm.index('UE_LOG(LogFlightSimRender, Display, TEXT("warm-up done"));')]
    assert warm.index("Capture->CaptureScene();") < warm.index("DrainGpu(")
    update = COMMANDLET.index("USkyLightComponent::UpdateSkyCaptureContents(World);")
    before = COMMANDLET.index('DrainGpu(TEXT("the work queued before the sky light capture"));')
    after = COMMANDLET.index('DrainGpu(TEXT("the sky light capture"));')
    assert before < update < after
    assert 'DrainGpu(FString::Printf(TEXT("post-sky capture %d/2"), i + 1));' in COMMANDLET


# -- the sky capture's ef361bd6 scene state --------------------------------------

def test_the_sky_capture_takes_ef361bd6_scene_state_and_gives_it_back():
    update = COMMANDLET.index("USkyLightComponent::UpdateSkyCaptureContents(World);")
    suspend = COMMANDLET.index("FFlightSimBeautyFallback::SuspendForSkyCapture(VisualScene)")
    haze = COMMANDLET.index("GoogleTiles.SuspendBeautyHaze()")
    lamps = COMMANDLET.index("Lamp->SetVolumetricScatteringIntensity(RenderLampScatteringEf361bd6);")
    resume = COMMANDLET.index("FFlightSimBeautyFallback::ResumeAfterSkyCapture(VisualScene);")
    haze_back = COMMANDLET.index("GoogleTiles.ResumeBeautyHaze();")
    lamps_back = COMMANDLET.index("Lamp->SetVolumetricScatteringIntensity(Held.Value);")
    assert max(suspend, haze, lamps) < update < min(resume, haze_back, lamps_back)
    gate = COMMANDLET.rindex("if (bSkyCaptureRestore)", 0, suspend)
    assert suspend - gate < 300
    assert "constexpr float RenderLampScatteringEf361bd6 = 1.0f;" in COMMANDLET
    assert 'TEXT("constrained_gpu_restore"), SkyRestoreRecord' in COMMANDLET


def test_the_fallback_suspend_moves_the_scene_values_and_no_cvar():
    for decl in ("static TSharedPtr<FJsonObject> SuspendForSkyCapture(FFlightSimVisualScene& Scene);",
                 "static void ResumeAfterSkyCapture(FFlightSimVisualScene& Scene);"):
        assert decl in FALLBACK_H, decl
    suspend = _body(FALLBACK, "TSharedPtr<FJsonObject> FFlightSimBeautyFallback::SuspendForSkyCapture(")
    for call in ("Sky->SetIntensity(State.SkyIntensityBefore);", "Sky->SetMinOcclusion(State.SkyMinOcclusionBefore);",
                 "SunLight->SetDynamicShadowCascades(State.SunCascadesBefore);",
                 "SunLight->SetCascadeDistributionExponent(State.SunDistributionBefore);"):
        assert call in suspend, call
    # the cvars equal the Cinematic level's (ef361bd6 ran it): read back, never set
    assert "->Set(" not in suspend
    assert "BeautyFallbackConsole(*Entry.Key)" in suspend
    resume = _body(FALLBACK, "void FFlightSimBeautyFallback::ResumeAfterSkyCapture(")
    for call in ("SetIntensity(State.SkyIntensityHeld)", "SetMinOcclusion(State.SkyMinOcclusionHeld)",
                 "SetDynamicShadowCascades(State.SunCascadesHeld)",
                 "SetCascadeDistributionExponent(State.SunDistributionHeld)"):
        assert call in resume, call
    # ApplyScene keeps the values it replaced
    apply = _body(FALLBACK, "bool FFlightSimBeautyFallback::ApplyScene(")
    assert "State.SkyIntensityBefore = IntensityBefore;" in apply
    assert "State.SunCascadesBefore = SunLight->DynamicShadowCascades;" in apply
    assert apply.index("State.SunCascadesBefore = SunLight->DynamicShadowCascades;") < apply.index(
        "SunLight->SetDynamicShadowCascades(BeautyFallbackCsmCascades);")


def test_the_fallback_cvar_asks_are_the_cinematic_levels():
    """Why SuspendForSkyCapture leaves the cvars: ef361bd6 ran Cinematic
    scalability too, and every fallback ask is that level's value."""
    ini = Path("/Users/Shared/Epic Games/UE_5.7/Engine/Config/BaseScalability.ini")
    asks = dict(re.findall(r'BeautyFallbackCvar\(TEXT\("(r\.[\w.]+)"\), (\w+|[\d.]+f)', FALLBACK))
    constants = dict(re.findall(r"constexpr float (\w+) = ([\d.]+)f;", FALLBACK))
    values = {name: float(constants.get(value, value.rstrip("f"))) for name, value in asks.items()}
    assert values == {"r.SSGI.Quality": 4.0, "r.SSR.Quality": 4.0, "r.DistanceFieldAO": 1.0, "r.AOQuality": 2.0,
                      "r.Shadow.CSM.MaxCascades": 10.0, "r.Shadow.MaxCSMResolution": 4096.0,
                      "r.Shadow.MaxResolution": 4096.0}
    if ini.exists():   # the authoring Mac's engine install; the render box has its own
        text = ini.read_text(encoding="utf-8", errors="replace")
        cine = {}
        for section, body in re.findall(r"^\[(\w+)@Cine\]\n(.*?)(?=^\[)", text, re.S | re.M):
            for name, value in re.findall(r"^(r\.[\w.]+)=([\d.]+)", body, re.M):
                cine[name] = float(value)
        for name, value in values.items():
            assert cine.get(name) == value, (name, cine.get(name), value)


def test_the_beauty_ground_haze_is_held_with_its_before_values():
    for decl in ("TSharedPtr<FJsonObject> SuspendBeautyHaze();", "void ResumeBeautyHaze();",
                 "TArray<FHazeFogRow> HazeFogRows;", "TArray<FHazeMieRow> HazeMieRows;"):
        assert decl in TILES_H, decl
    ground = _body(TILES, "TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyGround(")
    assert ground.index("Held.DensityBefore = Fog->FogDensity;") < ground.index("Fog->SetFogDensity(")
    assert ground.index("Held.ScatteringBefore = Atmosphere->MieScatteringScale;") < ground.index(
        "Atmosphere->SetMieScatteringScale(")
    suspend = _body(TILES, "TSharedPtr<FJsonObject> FFlightSimGoogleTiles::SuspendBeautyHaze()")
    assert "Fog->SetFogDensity(Row.DensityBefore);" in suspend
    assert "Fog->SetSecondFogDensity(Row.SecondDensityBefore);" in suspend
    assert "Atmosphere->SetMieScatteringScale(Row.ScatteringBefore);" in suspend
    resume = _body(TILES, "void FFlightSimGoogleTiles::ResumeBeautyHaze()")
    assert "Fog->SetFogDensity(Row.DensityHeld);" in resume
    assert "Atmosphere->SetMieAbsorptionScale(Row.AbsorptionHeld);" in resume
