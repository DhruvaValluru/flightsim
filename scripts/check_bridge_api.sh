#!/usr/bin/env bash
# Check the bridge's assumptions about the plugin API, without a compiler.
#
# The bridge C++ is written against headers rather than against a compiler's
# opinion, and on this machine it cannot be compiled at all. This does what can
# be done without one: confirm every plugin symbol the bridge calls actually
# exists, with the signature assumed, and that every module and plugin
# dependency it declares resolves.
#
# It does NOT establish that the code compiles. It establishes that the first
# compile will fail on ordinary C++ mistakes rather than on structural
# mismatches, and it re-runs if the plugin is ever re-vendored at a different
# version, which is when these assumptions would silently rot.
set -uo pipefail
cd "$(dirname "$0")/.."

# Module names the bridge declares: only the quoted names inside the
# Public/PrivateDependencyModuleNames Add/AddRange lists (comments stripped), not
# every quoted token -- FindCesium's path words "Plugins" and "Marketplace" are
# not modules.
module_names() {  # Build.cs path
    awk '{
        sub(/\/\/.*/, "")
        if ($0 ~ /(Public|Private)DependencyModuleNames[ \t]*\.[ \t]*(AddRange|Add)[ \t]*\(/) cap = 1
        if (cap) {
            s = $0
            while (match(s, /"[A-Za-z0-9_]+"/)) {
                print substr(s, RSTART + 1, RLENGTH - 2)
                s = substr(s, RSTART + RLENGTH)
            }
            if ($0 ~ /\)[ \t]*;/) cap = 0
        }
    }' "$1" | sort -u
}

# ERE for one show flag, as a whole token, in either engine form:
#   SHOWFLAG_FIXED_IN_SHIPPING(1, Grain, SFG_PostProcess, ...)
#   SHOWFLAG_ALWAYS_ACCESSIBLE(Grain, ...)
showflag_pattern() {  # flag name
    printf '%s' "\\([[:space:]]*([01][[:space:]]*,[[:space:]]*)?$1[[:space:]]*,"
}

# Interpreter: the repo venv, then python3, then python; a candidate must run
# (the Windows Store alias exists on PATH but does not).
pick_python() {
    local c
    for c in .venv/bin/python .venv/Scripts/python.exe python3 python; do
        case "$c" in
            .venv/*) [ -x "$c" ] || continue ;;
            *) command -v "$c" >/dev/null 2>&1 || continue ;;
        esac
        if "$c" -c "" >/dev/null 2>&1; then printf '%s' "$c"; return 0; fi
    done
    return 1
}

# Test hooks (no engine needed).
case "${1:-}" in
    --list-modules) module_names "${2:-ue/Plugins/FlightSimBridge/Source/FlightSimBridge/FlightSimBridge.Build.cs}"; exit 0 ;;
    --showflag-pattern) showflag_pattern "$2"; echo; exit 0 ;;
esac

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.7}"
PLUGIN="ue/Plugins/JSBSimFlightDynamicsModel"
BRIDGE="ue/Plugins/FlightSimBridge"
STATUS=0

ok()   { printf '  %-42s %s\n' "$1" "ok  $2"; }
bad()  { printf '  %-42s %s\n' "$1" "FAIL $2"; STATUS=1; }

echo "Bridge API check (no compiler involved)"
echo

# -- the one plugin call the bridge makes -----------------------------------
MC="$PLUGIN/Source/JSBSimFlightDynamicsModel/Public/JSBSimMovementComponent.h"
if [ -f "$MC" ]; then
    if grep -q 'void CommandConsole(FString Property, FString InValue, FString & OutValue)' "$MC"; then
        ok "UJSBSimMovementComponent::CommandConsole" "signature matches"
    else
        bad "UJSBSimMovementComponent::CommandConsole" "signature changed upstream"
    fi
    grep -q 'class JSBSIMFLIGHTDYNAMICSMODEL_API UJSBSimMovementComponent : public UActorComponent' "$MC" \
        && ok "UJSBSimMovementComponent" "is an exported UActorComponent" \
        || bad "UJSBSimMovementComponent" "class or base changed"
else
    bad "JSBSimMovementComponent.h" "not found -- plugin not vendored?"
fi

# -- upstream behaviours the commandlet compensates for ---------------------
# These are not API signatures, they are quirks. Each one is a place where
# FlightSimScenarioCommandlet does something that looks arbitrary until you read
# the plugin, and where a re-vendor at a different version would leave the
# compensation in place, still compiling, quietly wrong.
MCC="$PLUGIN/Source/JSBSimFlightDynamicsModel/Private/JSBSimMovementComponent.cpp"
if [ -f "$MCC" ]; then
    # Why the aircraft actor is placed by its centre of gravity, not its origin.
    grep -q 'FVector CGWorldPosition = Parent->GetTransform().TransformPosition(CGLocalPosition);' "$MCC" \
        && ok "IC derived from the CG" "still the CG, not the actor origin" \
        || bad "IC derived from the CG" "PrepareJSBSim changed how it locates the aircraft"

    # Why the actor yaw is set to heading - 90.
    grep -q 'IC->SetPsiDegIC(PsiThetaPhi.Yaw + 90);' "$MCC" \
        && ok "heading convention" "plugin still adds 90 deg to actor yaw" \
        || bad "heading convention" "the +90 the commandlet subtracts is gone"

    # Why LatchTrimmedControls exists at all: the trimmed throttle is thrown
    # away before the first tick, and the command struct is re-sent every tick.
    grep -q 'EngineCommands\[i\].Throttle = 0.0;' "$MCC" \
        && ok "throttle zeroed after trim" "still zeroed; latching is still needed" \
        || bad "throttle zeroed after trim" "upstream may have fixed this -- re-read LatchTrimmedControls"

    # Why the latched rudder and yaw trim are negated.
    grep -q 'FCS->SetDrCmd(-Commands.Rudder);' "$MCC" \
        && ok "rudder sign" "plugin still negates rudder on the way in" \
        || bad "rudder sign" "the negation the commandlet mirrors has changed"

    # Why the commandlet spawns a ground slab: with no world geometry the
    # ground query reports height-above-terrain 0 at any altitude, which puts a
    # cruising aircraft's gear in permanent contact.
    grep -q 'double HAT = 0.0;' "$MCC" \
        && ok "ground query fallback" "still 0.0 on a missed trace" \
        || bad "ground query fallback" "GetAGLevel's miss behaviour changed"

    # Upstream bug 3 must be patched, or the ground query silently reports the
    # aircraft on the deck above ~3.2 km AGL. A re-vendor that skipped this
    # would leave every cruise scenario running its gear model against a
    # fiction, with nothing reporting an error.
    grep -qF 'GetGeographicEllipsoidMaxRadius()) * 100.0 * Up;' "$MCC" \
        && ok "ground ray units" "patched to centimetres (319 km reach)" \
        || bad "ground ray units" "unpatched -- run scripts/vendor_ue_plugin.sh"

    # Local patch 4 must be present, or every piston aircraft force-started at
    # altitude dies full rich within seconds and trims (or verifies!) as a
    # glider -- measured on c172p at 3600 m, calm cells verified an untrimmed
    # state and windy cells failed trim outright.
    grep -q 'EngineCommands\[i\].Mixture = InitialMixture;' "$MCC" \
        && ok "start mixture" "card-carried mixture (piston-at-altitude patch)" \
        || bad "start mixture" "hardcoded full rich -- run scripts/vendor_ue_plugin.sh"
else
    bad "JSBSimMovementComponent.cpp" "not found -- plugin not vendored?"
fi

# -- engine types the bridge builds on --------------------------------------
CC="$UE_ROOT/Engine/Source/Runtime/CinematicCamera/Public/CineCameraComponent.h"
if [ -f "$CC" ]; then
    # RootComponent must be a USceneComponent; UCineCameraComponent reaches it
    # through UCameraComponent.
    grep -q 'class UCineCameraComponent : public UCameraComponent' "$CC" \
        && ok "UCineCameraComponent" "derives from UCameraComponent (a USceneComponent)" \
        || bad "UCineCameraComponent" "base class changed"
else
    bad "CineCameraComponent.h" "not found in $UE_ROOT"
fi

# -- every module the bridge declares ---------------------------------------
for m in $(module_names "$BRIDGE/Source/FlightSimBridge/FlightSimBridge.Build.cs"); do
    case "$m" in Core|CoreUObject|Engine) continue ;; esac
    # The found path, not the pipe's status: under pipefail a missing
    # $UE_ROOT/Engine (or grep -q closing the pipe early) failed a module
    # whose Build.cs is right there in the plugin. Searched: the engine (its
    # plugin trees, Marketplace included), the JSBSim plugin, and every plugin
    # in the project (ue/Plugins/*, e.g. a project-level CesiumForUnreal).
    if [ -n "$(find "$UE_ROOT/Engine" "$PLUGIN" ue/Plugins -name "$m.Build.cs" 2>/dev/null | head -n 1)" ]; then
        ok "module $m" "resolves"
    elif [ "$m" = CesiumRuntime ] && { [ "${FLIGHTSIM_CESIUM:-}" = 0 ] || [ -z "$(find ue/Plugins "$UE_ROOT/Engine/Plugins/Marketplace" -name CesiumForUnreal.uplugin 2>/dev/null | head -n 1)" ]; }; then
        # Build.cs adds CesiumRuntime only when FindCesium finds
        # CesiumForUnreal.uplugin (project Plugins, engine Marketplace) and
        # FLIGHTSIM_CESIUM is not 0; otherwise this build has no such
        # dependency and compiles WITH_FLIGHTSIM_CESIUM=0. Plugin present but
        # its module missing still FAILs below.
        ok "module $m" "not a dependency here (no Cesium for Unreal; WITH_FLIGHTSIM_CESIUM=0)"
    else
        bad "module $m" "no $m.Build.cs anywhere"
    fi
done

# -- engine surface the physical sky assumes (FlightSimSky.cpp) -------------
# Written from memory of the 5.x headers on a machine with no engine; each
# line below is one assumption, checked here before a build is spent on it.
ENG="$UE_ROOT/Engine/Source/Runtime/Engine"
sky_check() {  # label, header (relative to $ENG), fixed-string pattern
    if [ ! -f "$ENG/$2" ]; then
        bad "$1" "header $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$ENG/$2"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimSky.cpp needs updating"
    fi
}
DLC="Classes/Components/DirectionalLightComponent.h"
sky_check "DirectionalLight AtmosphereSunLightIndex" "$DLC" "AtmosphereSunLightIndex"
sky_check "DirectionalLight AtmosphereSunDiskColorScale" "$DLC" "AtmosphereSunDiskColorScale"
sky_check "DirectionalLight per-pixel transmittance" "$DLC" "bPerPixelAtmosphereTransmittance"
FOG="Classes/Components/ExponentialHeightFogComponent.h"
sky_check "Fog SetFogInscatteringColor" "$FOG" "SetFogInscatteringColor"
sky_check "Fog sky-atmosphere ambient scale" "$FOG" "SkyAtmosphereAmbientContributionColorScale"
VC="Classes/Components/VolumetricCloudComponent.h"
sky_check "AVolumetricCloud" "$VC" "class AVolumetricCloud"
sky_check "VolumetricCloud SetLayerBottomAltitude" "$VC" "SetLayerBottomAltitude"
sky_check "VolumetricCloud SetLayerHeight" "$VC" "SetLayerHeight"
sky_check "VolumetricCloud SetMaterial" "$VC" "SetMaterial"
PPS="Classes/Engine/Scene.h"
sky_check "PostProcess GI method" "$PPS" "DynamicGlobalIlluminationMethod"
sky_check "PostProcess reflection method" "$PPS" "EReflectionMethod"
sky_check "PostProcess physical camera exposure" "$PPS" "AutoExposureApplyPhysicalCameraExposure"
sky_check "PostProcess FilmGrainIntensity" "$PPS" "FilmGrainIntensity"
sky_check "PostProcess SceneFringeIntensity" "$PPS" "SceneFringeIntensity"
SF="Public/ShowFlagsValues.inl"
showflag_check() {  # flag name
    if [ ! -f "$ENG/$SF" ]; then
        bad "show flag $1" "header $SF not found in $UE_ROOT"
    elif grep -qE -- "$(showflag_pattern "$1")" "$ENG/$SF"; then
        ok "show flag $1" "present"
    else
        bad "show flag $1" "not found in $SF -- FlightSimSky.cpp needs updating"
    fi
}
showflag_check Cloud
showflag_check LumenGlobalIllumination
showflag_check LumenReflections
showflag_check Grain
showflag_check SceneColorFringe
showflag_check Vignette
# -- render-path lane (visual plan V0/V8): the beauty and path-trace path ----
# FlightSimRenderCommandlet.cpp -quality=beauty|pathtrace, -still-samples,
# -pathtrace-*. Paths are relative to $UE_ROOT/Engine/Source/Runtime; each
# pattern is a fixed string read from the 5.7.4 source on 2026-11-09.
RT="$UE_ROOT/Engine/Source/Runtime"
rp_check() {  # label, file (relative to $RT), fixed-string pattern
    if [ ! -f "$RT/$2" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$RT/$2"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the render-path beauty block needs updating"
    fi
}
rp_check "show flag TemporalAA" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(TemporalAA,"
rp_check "show flag PathTracing" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(PathTracing,"
rp_check "capture clears TemporalAA (why beauty sets it)" "Engine/Private/Components/SceneCaptureComponent.cpp" "ShowFlags.TemporalAA = false;"
rp_check "TSR falls back without the flag" "Engine/Private/SceneView.cpp" "if (!Family->EngineShowFlags.TemporalAA || !Family->bRealtimeUpdate || !SupportsTSR(GetShaderPlatform()))"
# Fix pass (shots-render): render.json anti_aliasing names the FXAA fallback
# for TAA too, and the Cinematic sky sample caps the beauty block repeats.
rp_check "TAA falls back without the flag" "Engine/Private/SceneView.cpp" "if (!Family->EngineShowFlags.TemporalAA || !Family->bRealtimeUpdate || !SupportsGen4TAA(GetShaderPlatform()))"
rp_check "fallback is FXAA" "Engine/Private/SceneView.cpp" "AntiAliasingMethod = AAM_FXAA;"
rp_check "Cinematic sky SampleCountMax 256" "../../Config/BaseScalability.ini" "r.SkyAtmosphere.SampleCountMax=256.0"
rp_check "Cinematic AP SampleCountMaxPerSlice 8" "../../Config/BaseScalability.ini" "r.SkyAtmosphere.AerialPerspectiveLUT.SampleCountMaxPerSlice=8"
rp_check "capture family realtime when persistent" "Renderer/Private/SceneCaptureRendering.cpp" ".SetRealtimeUpdate(SceneCaptureComponent->bCaptureEveryFrame || SceneCaptureComponent->bAlwaysPersistRenderingState));"
rp_check "capture Lumen off unless overridden" "Renderer/Private/SceneCaptureRendering.cpp" "By default, Lumen is disabled in scene captures"
rp_check "capture view state needs persistence" "Engine/Private/Components/SceneCaptureComponent.cpp" "if ((bCaptureEveryFrame || bAlwaysPersistRenderingState) && ViewStateInterface == NULL)"
rp_check "path tracer state lives in the view state" "Renderer/Private/PathTracing.cpp" "View.ViewState->PathTracingState = MakePimpl<FPathTracingState>();"
rp_check "PostProcess LumenSurfaceCacheResolution" "Engine/Classes/Engine/Scene.h" "uint8 bOverride_LumenSurfaceCacheResolution : 1;"
rp_check "PostProcess LumenSceneLightingQuality" "Engine/Classes/Engine/Scene.h" "uint32 bOverride_LumenSceneLightingQuality : 1;"
rp_check "PostProcess LumenFinalGatherQuality" "Engine/Classes/Engine/Scene.h" "uint32 bOverride_LumenFinalGatherQuality : 1;"
rp_check "PostProcess LumenReflectionQuality" "Engine/Classes/Engine/Scene.h" "uint8 bOverride_LumenReflectionQuality:1;"
rp_check "PostProcess LumenSceneViewDistance" "Engine/Classes/Engine/Scene.h" "uint32 bOverride_LumenSceneViewDistance : 1;"
rp_check "PostProcess LumenMaxTraceDistance" "Engine/Classes/Engine/Scene.h" "uint32 bOverride_LumenMaxTraceDistance : 1;"
rp_check "PostProcess PathTracingSamplesPerPixel" "Engine/Classes/Engine/Scene.h" "int32 PathTracingSamplesPerPixel;"
rp_check "PostProcess PathTracingMaxBounces" "Engine/Classes/Engine/Scene.h" "int32 PathTracingMaxBounces;"
rp_check "PostProcess PathTracingEnableDenoiser" "Engine/Classes/Engine/Scene.h" "uint32 PathTracingEnableDenoiser : 1;"
rp_check "Scalability::SetQualityLevels" "Engine/Public/Scalability.h" "ENGINE_API void SetQualityLevels(const FQualityLevels& QualityLevels, bool bForce = false);"
rp_check "Scalability SetFromSingleQualityLevel" "Engine/Public/Scalability.h" "ENGINE_API void SetFromSingleQualityLevel(int32 Value);"
rp_check "IsRayTracingEnabled" "RenderCore/Public/RenderUtils.h" "extern RENDERCORE_API bool IsRayTracingEnabled();"
rp_check "GRHISupportsRayTracing" "RHI/Public/RHIGlobals.h" "#define GRHISupportsRayTracing"
rp_check "GetSupportsPathTracing" "RHI/Public/DataDrivenShaderPlatformInfo.h" "static inline const bool GetSupportsPathTracing(const FStaticShaderPlatform Platform)"
rp_check "GMaxRHIShaderPlatform" "RHI/Public/RHIShaderPlatform.h" "extern RHI_API EShaderPlatform GMaxRHIShaderPlatform;"
rp_check "-ini: command-line override" "Core/Private/Misc/ConfigCacheIni.cpp" "const auto& IniSwitchIdentifier       = TEXT(\"-ini:\");"
rp_cvar() {  # cvar name, file (relative to $RT)
    rp_check "cvar $1" "$2" "TEXT(\"$1\")"
}
rp_cvar r.TSR.History.SampleCount "Renderer/Private/PostProcess/TemporalSuperResolution.cpp"
rp_cvar r.TSR.History.ScreenPercentage "Renderer/Private/PostProcess/TemporalSuperResolution.cpp"
rp_cvar r.SkyAtmosphere.FastSkyLUT "Renderer/Private/SkyAtmosphereRendering.cpp"
rp_cvar r.SkyAtmosphere.AerialPerspectiveLUT.FastApplyOnOpaque "Renderer/Private/SkyAtmosphereRendering.cpp"
rp_cvar r.SkyAtmosphere.MultiScatteringLUT.HighQuality "Renderer/Private/SkyAtmosphereRendering.cpp"
rp_cvar r.SkyAtmosphere.LUT32 "Renderer/Private/SkyAtmosphereRendering.cpp"
rp_cvar r.SkyAtmosphere.SampleCountMax "Renderer/Private/SkyAtmosphereRendering.cpp"
rp_cvar r.SkyAtmosphere.AerialPerspectiveLUT.SampleCountMaxPerSlice "Renderer/Private/SkyAtmosphereRendering.cpp"
rp_cvar r.VolumetricCloud "Renderer/Private/VolumetricCloudRendering.cpp"
rp_cvar r.VolumetricCloud.HighQualityAerialPerspective "Renderer/Private/VolumetricCloudRendering.cpp"
rp_cvar r.VolumetricRenderTarget.Mode "Renderer/Private/VolumetricRenderTarget.cpp"
# -- clouds round 6 (2026-11-10): the cloud march's blue-noise jitter --------
# FlightSimRenderCommandlet.cpp loads and builds GEngine's blue-noise textures
# before the first beauty capture; each line read in the 5.7 source that day.
rp_check "UEngine::LoadBlueNoiseTexture" "Engine/Classes/Engine/Engine.h" "ENGINE_API void LoadBlueNoiseTexture(bool LoadVector2BlueNoiseTexture);"
rp_check "GEngine blue-noise scalar texture" "Engine/Classes/Engine/Engine.h" "TObjectPtr<class UTexture2D> BlueNoiseScalarTexture;"
rp_check "GEngine blue-noise vec2 texture" "Engine/Classes/Engine/Engine.h" "TObjectPtr<class UTexture2D> BlueNoiseVec2Texture;"
rp_check "renderer loads blue noise lazily" "Renderer/Private/SceneRendering.cpp" "GEngine->LoadBlueNoiseTexture(LoadVector2BlueNoiseTexture);"
rp_check "commandlet gets the blue-noise dummy" "Renderer/Private/BlueNoise.cpp" "ensure(IsRunningCommandlet() && IsAllowCommandletRendering());"
rp_check "blue-noise dummy is 1x1" "Renderer/Private/BlueNoise.cpp" "Out.Dimensions = FIntVector(1,1,1);"
rp_check "cloud march starts at a blue-noise offset" "../../Shaders/Private/VolumetricCloud.usf" "t = TMin + BlueNoiseScalar(FullResPixelCoord, View.StateFrameIndexMod8) * StepT;"
rp_check "cloud shadow march is unjittered" "../../Shaders/Private/VolumetricCloud.usf" "const float ShadowJitterNorm = 0.5f; // InterleavedGradientNoise(SvPosition.xy, ShadowJitteringSeed); // Disabled jittering"
rp_check "a building texture is a default stand-in" "Engine/Classes/Engine/Texture.h" "ENGINE_API virtual bool IsDefaultTexture() const;"
rp_check "mode 3 composes the trace with no reconstruction" "Renderer/Private/VolumetricRenderTarget.cpp" "if (VRTMode == 1 || VRTMode == 3)"
rp_cvar r.PathTracing "Renderer/Private/PathTracing.cpp"
rp_cvar r.PathTracing.FilterWidth "Renderer/Private/PathTracing.cpp"
rp_cvar r.PathTracing.EnableReferenceAtmosphere "Renderer/Private/PathTracing.cpp"
rp_cvar r.PathTracing.EnableReferenceClouds "Renderer/Private/PathTracing.cpp"
rp_cvar r.PathTracing.Denoiser "Renderer/Private/PathTracingSpatialTemporalDenoising.cpp"
rp_cvar r.PathTracing.Denoiser.Name "Renderer/Private/PathTracingSpatialTemporalDenoising.cpp"
rp_cvar r.RayTracing "Renderer/Private/DeferredShadingRenderer.cpp"
rp_cvar r.RayTracing.Nanite.Mode "Engine/Private/Rendering/NaniteResources.cpp"
# -- reference-frames lane (2026-11-09): the path-traced reference ----------
# FlightSimRenderCommandlet.cpp pathtrace branch: the reference atmosphere
# (a post-process override the -1 cvar inherits), the reference clouds and
# the NNE denoiser's asset; each read in the 5.7.4 source on this date.
rp_check "PostProcess PathTracingEnableReferenceAtmosphere" "Engine/Classes/Engine/Scene.h" "uint32 PathTracingEnableReferenceAtmosphere : 1;"
rp_check "ref atmosphere inherits the post-process value" "Renderer/Private/PathTracing.cpp" "return EnableReferenceAtmosphereCVar < 0 ? View.FinalPostProcessSettings.PathTracingEnableReferenceAtmosphere != 0 : EnableReferenceAtmosphereCVar != 0;"
rp_check "ref clouds need the ref atmosphere" "Renderer/Private/PathTracing.cpp" "if (!PathTracing::UsesReferenceAtmosphere(View) || !ShouldRenderVolumetricCloud(Scene, View.Family->EngineShowFlags))"
rp_check "sky light skydome off under the ref atmosphere" "Renderer/Private/PathTracing.cpp" "const bool bEnableSkydome = !bUseAtmosphere;"
rp_check "denoise on the last sample" "Renderer/Private/PathTracing.cpp" "(((Config.PathTracingData.Iteration + 1) == MaxSPP) ||"
rp_check "default spatial denoiser is NNEDenoiser" "Renderer/Private/PathTracingSpatialTemporalDenoising.cpp" "\"NNEDenoiser\","
rp_cvar NNEDenoiser.Asset "../../Plugins/NNE/NNEDenoiser/Source/NNEDenoiser/Private/NNEDenoiserViewExtension.cpp"
rp_check "NNEDenoiser.Asset 3 is OIDN High Quality" "../../Plugins/NNE/NNEDenoiser/Source/NNEDenoiser/Private/NNEDenoiserViewExtension.cpp" "case 3: return TEXT(\"/NNEDenoiser/NNED_Oidn2-3_HighQuality.NNED_Oidn2-3_HighQuality\");"
rp_check "NNEDenoiser registers only with ray tracing" "../../Plugins/NNE/NNEDenoiser/Source/NNEDenoiser/Private/NNEDenoise.cpp" "if (IsRayTracingAllowed())"
rp_check "NNEDenoiser active only on path-traced families" "../../Plugins/NNE/NNEDenoiser/Source/NNEDenoiser/Private/NNEDenoiserViewExtension.cpp" "TimeoutCounter = !!InViewFamily.EngineShowFlags.PathTracing ? NO_SHOW_PATH_TRACING_TIMEOUT"
rp_check "NNEDenoiser plugin enabled by default" "../../Plugins/NNE/NNEDenoiser/NNEDenoiser.uplugin" "\"EnabledByDefault\" : true,"
# -- end reference-frames lane ------------------------------------------------

# -- integration (visual overhaul, 2026-11-09) -------------------------------
# RenderPinShowFlags / RegisterLabelCapture / RenderMakeLensFree /
# RenderWriteLookContract (FlightSimRenderCommandlet.cpp). The first two
# rows are WHY flags are pinned: registration resets ShowFlags.
rp_check "OnRegister re-applies show flag settings" "Engine/Private/Components/SceneCaptureComponent.cpp" "// Make sure any loaded saved flag settings are reflected in our FEngineShowFlags"
rp_check "UpdateShowFlags resets to the archetype" "Engine/Private/Components/SceneCaptureComponent.cpp" "ShowFlags = Archetype->ShowFlags;"
rp_check "SetShowFlagSettings" "Engine/Classes/Components/SceneCaptureComponent.h" "ENGINE_API void SetShowFlagSettings(const TArray<FEngineShowFlagsSetting>& InShowFlagSettings);"
rp_check "FEngineShowFlagsSetting.ShowFlagName" "Engine/Classes/Components/SceneCaptureComponent.h" "FString ShowFlagName;"
rp_check "FEngineShowFlagsSetting.Enabled" "Engine/Classes/Components/SceneCaptureComponent.h" "bool Enabled = false;"
rp_check "FEngineShowFlags::IterateAllFlags" "Engine/Public/ShowFlags.h" "template <class T> static void IterateAllFlags(T& Sink)"
rp_check "IterateAllFlags custom sink" "Engine/Public/ShowFlags.h" "return Sink.OnCustomShowFlag(Index, Name);"
rp_check "FEngineShowFlags::GetSingleFlag" "Engine/Public/ShowFlags.h" "ENGINE_API bool GetSingleFlag(uint32 Index) const;"
rp_check "show flag LensDistortion" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_FIXED_IN_SHIPPING(1, LensDistortion,"
rp_check "show flag Refraction" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_FIXED_IN_SHIPPING(1, Refraction,"
rp_check "show flag LocalExposure" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(LocalExposure,"
rp_check "PostProcess MotionBlurTargetFPS" "Engine/Classes/Engine/Scene.h" "int32 MotionBlurTargetFPS;"
rp_check "PostProcess MotionBlurMax" "Engine/Classes/Engine/Scene.h" "float MotionBlurMax;"
rp_check "UVolumetricCloudComponent header" "Engine/Classes/Components/VolumetricCloudComponent.h" "class UVolumetricCloudComponent"
rp_check "TObjectIterator" "CoreUObject/Public/UObject/UObjectIterator.h" "class TObjectIterator"


# -- engine surface the beauty look assumes (FlightSimBeautyLook.cpp) --------
# Look-dev lane, 2026-11-09: each symbol was read in the UE 5.7.4 headers on
# the authoring Mac (which cannot compile); re-checked here before a build.
beauty_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimBeautyLook.cpp needs updating"
    fi
}
BSCENE="Engine/Classes/Engine/Scene.h"
for p in FilmSlope FilmToe FilmShoulder FilmBlackClip FilmWhiteClip ToneCurveAmount \
         ColorSaturation ColorContrast ColorGamma ColorGain ColorOffset WhiteTemp WhiteTint \
         BloomMethod BloomIntensity BloomThreshold LensFlareIntensity LensFlareThreshold \
         VignetteIntensity MotionBlurAmount MotionBlurMax MotionBlurPerObjectSize \
         MotionBlurTargetFPS DepthOfFieldSensorWidth DepthOfFieldMinFstop \
         DepthOfFieldFocalDistance DepthOfFieldBladeCount CameraShutterSpeed CameraISO \
         LocalExposureMethod LocalExposureHighlightContrastScale \
         LocalExposureShadowContrastScale LocalExposureDetailStrength \
         LocalExposureBlurredLuminanceBlend LocalExposureMiddleGreyBias \
         LumenReflectionQuality LumenFinalGatherQuality LumenSceneLightingQuality \
         LumenSceneDetail LumenMaxTraceDistance LumenFrontLayerTranslucencyReflections \
         ScreenSpaceReflectionIntensity ScreenSpaceReflectionQuality \
         ScreenSpaceReflectionMaxRoughness; do
    beauty_check "PostProcess $p" "$BSCENE" "bOverride_$p"
done
beauty_check "EBloomMethod BM_SOG" "$BSCENE" "BM_SOG"
beauty_check "ELocalExposureMethod Bilateral" "$BSCENE" "enum class ELocalExposureMethod"
beauty_check "DirectionalLight GetAtmosphereSunLightIndex" \
    "Engine/Classes/Components/DirectionalLightComponent.h" "GetAtmosphereSunLightIndex() const override"
beauty_check "DirectionalLight IsUsedAsAtmosphereSunLight" \
    "Engine/Classes/Components/DirectionalLightComponent.h" "IsUsedAsAtmosphereSunLight() const override"
beauty_check "Light bUseTemperature" "Engine/Classes/Components/LightComponent.h" "uint32 bUseTemperature : 1;"
beauty_check "Light SetUseTemperature" "Engine/Classes/Components/LightComponent.h" "void SetUseTemperature(bool bNewValue);"
beauty_check "Light LightColor" "Engine/Classes/Components/LightComponentBase.h" "FColor LightColor;"
beauty_check "FCommandLine::Get" "Core/Public/Misc/CommandLine.h" "static const TCHAR* Get();"
# The premises the sun's lux is built on (core/scene/beauty_look.py): the
# light's intensity is outer-space illuminance times the atmosphere's
# transmittance, and the manual exposure is log2(N^2 * shutter * 100 / ISO).
beauty_check "premise: lux x transmittance" "Engine/Private/Components/DirectionalLightComponent.cpp" \
    "GetOuterSpaceIlluminance() * GetAtmosphereTransmittanceTowardSun()"
beauty_check "premise: transmittance floor" "Engine/Classes/Components/SkyAtmosphereComponent.h" \
    "float TransmittanceMinLightElevationAngle;"
# Fix pass (light-colour, 2026-11-09): ONE sun transmittance model. The beauty
# sun is outer-space lux; with per-pixel transmittance the CPU illuminance
# carries none, and the shader samples the LUT at the pixel's own sun angle
# (past the +90 deg floor). The host reads bPerPixelAtmosphereTransmittance.
beauty_check "premise: per-pixel sun carries no CPU transmittance" \
    "Engine/Private/Components/DirectionalLightComponent.cpp" \
    "return FLinearColor(FVector(GetOuterSpaceIlluminance()));"
beauty_check "DirectionalLight bPerPixelAtmosphereTransmittance" \
    "Engine/Classes/Components/DirectionalLightComponent.h" "uint32 bPerPixelAtmosphereTransmittance : 1;"
# The beauty sky light is captured once, from the aircraft (RenderCommandlet).
beauty_check "Actor SetActorLocation" "Engine/Classes/GameFramework/Actor.h" \
    "ENGINE_API bool SetActorLocation(const FVector& NewLocation, bool bSweep=false"
beauty_check "ActorComponent GetOwner" "Engine/Classes/Components/ActorComponent.h" "AActor* GetOwner() const;"
beauty_check "SkyLight UpdateSkyCaptureContents" "Engine/Classes/Components/SkyLightComponent.h" \
    "static ENGINE_API void UpdateSkyCaptureContents(UWorld* WorldToUpdate);"
# The -aerosol= probe converts its multiplier to 1/km against these defaults
# (FlightSimVisualScene.cpp SceneMie*DefaultPerKm).
beauty_check "premise: Mie scattering default 0.003996/km" \
    "Engine/Private/Components/SkyAtmosphereComponent.cpp" "MieScatteringScale = 0.003996f;"
beauty_check "premise: Mie absorption default 0.000444/km" \
    "Engine/Private/Components/SkyAtmosphereComponent.cpp" "MieAbsorptionScale = 0.000444f;"
if grep -qF -- "getTransmittanceLutUvs(PHeight, LightZenithCosAngle, BottomRadius, TopRadius, TransmittanceLutUv);" \
    "$UE_ROOT/Engine/Shaders/Private/SkyAtmosphereCommon.ush" 2>/dev/null; then
    ok "premise: per-pixel transmittance at the pixel's sun angle" "present"
else
    bad "premise: per-pixel transmittance at the pixel's sun angle" \
        "not found in Shaders/Private/SkyAtmosphereCommon.ush -- core/scene/beauty_look.py needs updating"
fi
beauty_check "premise: physical camera EV100" "Renderer/Private/PostProcess/PostProcessEyeAdaptation.cpp" \
    "FMath::Log2(FMath::Square(Settings.DepthOfFieldFstop) * Settings.CameraShutterSpeed * 100"
# Integration fix, 2026-11-09: RenderWriteLookContract finds the rain
# blendables (M_LensDrops, M_WindshieldRain) on the beauty capture by base
# material and reads the windshield's Glass vector back.
beauty_check "WeightedBlendable Weight/Object" "$BSCENE" "TObjectPtr<UObject> Object;"
beauty_check "MaterialInterface GetBaseMaterial" "Engine/Public/Materials/MaterialInterface.h" \
    "ENGINE_API UMaterial* GetBaseMaterial();"
beauty_check "MID K2_GetVectorParameterValue" "Engine/Public/Materials/MaterialInstanceDynamic.h" \
    "ENGINE_API FLinearColor K2_GetVectorParameterValue(FName ParameterName);"
for f in MotionBlur DepthOfField Bloom LensFlares Tonemapper LocalExposure ScreenSpaceReflections; do
    showflag_check "$f"
done
if [ -f "$UE_ROOT/Engine/Content/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.uasset" ]; then
    ok "engine simple cloud material" "present"
else
    bad "engine simple cloud material" "missing: physical-sky renders draw no clouds (recorded, not fatal)"
fi

# -- world lane (visual overhaul, 2026-11-09): the beauty world look ---------
# FlightSimClouds.cpp, FlightSimGroundDetail.cpp, the FlightSimGoogleTiles.cpp
# beauty look and the FlightSimWeather.cpp readability hook. Each symbol was
# read in the 5.7.4 headers when written; this re-checks them before a build.
# Cesium for Unreal's API is NOT checked here: it is reached by reflection by
# name (no Cesium headers on the authoring machine; UNVERIFIED).
COREUO="$UE_ROOT/Engine/Source/Runtime/CoreUObject/Public/UObject"
SKYC="Classes/Components/SkyAtmosphereComponent.h"
sky_check "world: SkyAtmosphere SetMieScatteringScale" "$SKYC" "void SetMieScatteringScale(float NewValue)"
sky_check "world: SkyAtmosphere SetMieAbsorptionScale" "$SKYC" "void SetMieAbsorptionScale(float NewValue)"
sky_check "world: SkyAtmosphere SetMieExponentialDistribution" "$SKYC" "void SetMieExponentialDistribution(float NewValue)"
sky_check "world: SkyAtmosphere SetMieAnisotropy" "$SKYC" "void SetMieAnisotropy(float NewValue)"
sky_check "world: SkyAtmosphere SetAerialPespectiveViewDistanceScale" "$SKYC" "void SetAerialPespectiveViewDistanceScale(float NewValue)"
sky_check "world: SkyAtmosphere SetGroundAlbedo" "$SKYC" "void SetGroundAlbedo(const FColor& NewValue)"
sky_check "world: Fog FogDensity property" "$FOG" "float FogDensity;"
sky_check "world: Fog SetVolumetricFog" "$FOG" "void SetVolumetricFog(bool bNewValue)"
sky_check "world: Fog SetVolumetricFogDistance" "$FOG" "void SetVolumetricFogDistance(float NewValue)"
sky_check "world: Fog SetVolumetricFogScatteringDistribution" "$FOG" "void SetVolumetricFogScatteringDistribution(float NewValue)"
sky_check "world: Fog SetVolumetricFogExtinctionScale" "$FOG" "void SetVolumetricFogExtinctionScale(float NewValue)"
sky_check "world: DirectionalLight bCastShadowsOnClouds" "$DLC" "uint32 bCastShadowsOnClouds : 1;"
sky_check "world: DirectionalLight bCastShadowsOnAtmosphere" "$DLC" "uint32 bCastShadowsOnAtmosphere : 1;"
sky_check "world: DirectionalLight bCastCloudShadows" "$DLC" "uint32 bCastCloudShadows : 1;"
sky_check "world: LightComponentBase bCastVolumetricShadow" "Classes/Components/LightComponentBase.h" "uint32 bCastVolumetricShadow : 1;"
sky_check "world: LightComponentBase Intensity" "Classes/Components/LightComponentBase.h" "float Intensity;"
sky_check "world: SkyLight SetIntensity" "Classes/Components/SkyLightComponent.h" "void SetIntensity(float NewIntensity)"
sky_check "world: VolumetricCloud Material soft pointer" "$VC" "TSoftObjectPtr<UMaterialInterface> Material;"
sky_check "world: VolumetricCloud LayerBottomAltitude" "$VC" "float LayerBottomAltitude;"
sky_check "world: VolumetricCloud per-sample transmittance" "$VC" "void SetbUsePerSampleAtmosphericLightTransmittance(bool NewValue)"
sky_check "world: VolumetricCloud SetSkyLightCloudBottomOcclusion" "$VC" "void SetSkyLightCloudBottomOcclusion(float NewValue)"
sky_check "world: VolumetricCloud SetViewSampleCountScale" "$VC" "void SetViewSampleCountScale(float NewValue)"
sky_check "world: VolumetricCloud SetShadowViewSampleCountScale" "$VC" "void SetShadowViewSampleCountScale(float NewValue)"
sky_check "world: VolumetricCloud SetShadowTracingDistance" "$VC" "void SetShadowTracingDistance(float NewValue)"
sky_check "world: VolumetricCloud SetTracingMaxDistance" "$VC" "void SetTracingMaxDistance(float NewValue)"
sky_check "world: VolumetricCloud SetStopTracingTransmittanceThreshold" "$VC" "void SetStopTracingTransmittanceThreshold(float NewValue)"
sky_check "world: VolumetricCloud SetGroundAlbedo" "$VC" "void SetGroundAlbedo(FColor NewValue)"
sky_check "world: cloud sample attribute expression" "Public/Materials/MaterialExpressionCloudLayer.h" "class UMaterialExpressionCloudSampleAttribute"
sky_check "world: MPC instance SetScalarParameterValue" "Public/Materials/MaterialParameterCollectionInstance.h" "bool SetScalarParameterValue(FName ParameterName, float ParameterValue)"
sky_check "world: World GetParameterCollectionInstance" "Classes/Engine/World.h" "GetParameterCollectionInstance(const UMaterialParameterCollection* Collection) const"
sky_check "world: World LineTraceSingleByChannel" "Classes/Engine/World.h" "bool LineTraceSingleByChannel(struct FHitResult& OutHit,const FVector& Start,const FVector& End,ECollisionChannel TraceChannel"
sky_check "world: CollisionQueryParams AddIgnoredActors" "Public/CollisionQueryParams.h" "void AddIgnoredActors(const TArray<AActor*>& InIgnoreActors)"
ISMH="Classes/Components/InstancedStaticMeshComponent.h"
sky_check "world: ISM AddInstance" "$ISMH" "virtual int32 AddInstance(const FTransform& InstanceTransform, bool bWorldSpace = false)"
sky_check "world: ISM GetInstanceTransform" "$ISMH" "bool GetInstanceTransform(int32 InstanceIndex, FTransform& OutInstanceTransform, bool bWorldSpace = false) const"
sky_check "world: ISM UpdateInstanceTransform" "$ISMH" "virtual bool UpdateInstanceTransform(int32 InstanceIndex, const FTransform& NewInstanceTransform, bool bWorldSpace=false, bool bMarkRenderStateDirty=false, bool bTeleport=false)"
sky_check "world: ISM SetCullDistances" "$ISMH" "void SetCullDistances(int32 StartCullDistance, int32 EndCullDistance)"
core_check() {  # label, header (relative to CoreUObject/Public/UObject), fixed-string pattern
    if [ ! -f "$COREUO/$2" ]; then
        bad "$1" "header $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$COREUO/$2"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the world lane's reflection code needs updating"
    fi
}
core_check "world: FindFProperty" "UnrealType.h" "T* FindFProperty(const UStruct* Owner, const TCHAR* FieldName"
core_check "world: FObjectProperty SetObjectPropertyValue_InContainer" "UnrealType.h" "void SetObjectPropertyValue_InContainer(void* ContainerAddress, UObject* Value, int32 ArrayIndex = 0) const"
core_check "world: FBoolProperty SetPropertyValue_InContainer" "UnrealType.h" "void SetPropertyValue_InContainer(void* A, bool Value, int32 ArrayIndex = 0) const"
core_check "world: UFunction ParmsSize" "Class.h" "uint16 ParmsSize;"
core_check "world: UObject ProcessEvent" "Object.h" "virtual void ProcessEvent( UFunction* Function, void* Parms );"
if [ -f "$UE_ROOT/Engine/Content/EngineResources/WhiteSquareTexture.uasset" ]; then
    ok "world: engine WhiteSquareTexture" "present (the tiles material's texture default)"
else
    bad "world: engine WhiteSquareTexture" "missing: M_FlightSimTilesBeauty needs another default texture"
fi
if grep -qF 'GetCloudSampleNormAltitudeInLayer' "$UE_ROOT/Engine/Config/BaseMaterialExpressions.ini" 2>/dev/null; then
    ok "world: NormAltitudeInLayer output" "present"
else
    bad "world: NormAltitudeInLayer output" "not in BaseMaterialExpressions.ini: M_FlightSimCloudLayers' pin name changed"
fi
# -- tiles-delight (visual overhaul module, 2026-11-09) -- begin -------------
# FlightSimClouds.cpp FlightSimTilesDelight (contact shading) and the
# M_FlightSimTilesBeauty coarse-mip sample in scripts/ue_create_materials.py.
# Each pattern was read in the 5.7.4 source on 2026-11-09 (paths under $RT).
rp_check "delight: Light ContactShadowLength" "Engine/Classes/Components/LightComponent.h" "float ContactShadowLength;"
rp_check "delight: Light ContactShadowLengthInWS" "Engine/Classes/Components/LightComponent.h" "uint32 ContactShadowLengthInWS : 1;"
rp_check "delight: MarkRenderStateDirty" "Engine/Classes/Components/ActorComponent.h" "ENGINE_API void MarkRenderStateDirty();"
rp_check "delight: cvar ShortRangeAO" "Renderer/Private/Lumen/LumenScreenProbeGather.cpp" 'TEXT("r.Lumen.ScreenProbeGather.ShortRangeAO"),'
rp_check "delight: cvar ShortRangeAO.HorizonSearch" "Renderer/Private/Lumen/LumenScreenSpaceBentNormal.cpp" 'TEXT("r.Lumen.ScreenProbeGather.ShortRangeAO.HorizonSearch"),'
rp_check "delight: FindConsoleVariable" "Core/Public/HAL/IConsoleManager.h" "virtual IConsoleVariable* FindConsoleVariable(const TCHAR* Name, bool bTrackFrequentCalls = true) const = 0;"
rp_check "delight: TMVM_MipBias" "Engine/Classes/Engine/EngineTypes.h" "TMVM_MipBias UMETA("
rp_check "delight: TextureSample MipBias pin" "Engine/Private/Materials/MaterialExpressions.cpp" 'IF_INPUT_RETURN(TEXT("MipBias"));'
# MaterialEditingLibrary::ConnectMaterialExpressions matches the shortened pin
# name, so the script connects "Bias", not "MipBias".
rp_check "delight: MipBias pin shortens to Bias" "../Editor/UnrealEd/Private/MaterialGraphNode.cpp" "InputName = MaterialPinNames::Bias;"
# -- tiles-delight -- end ------------------------------------------------------
# -- world lane fix pass (2026-11-09) -- begin --------------------------------
# FlightSimClouds.cpp (the per-key look read, the fog's sun lobe),
# FlightSimGroundDetail.cpp (the fade band, the scatter's material check) and
# M_FlightSimScatter (scripts/ue_create_materials.py, scatter_opacity.hlsl).
# Each pattern was read in the 5.7.4 source on 2026-11-09 (paths under $RT).
rp_check "world fix: Fog SetDirectionalInscatteringExponent" "Engine/Classes/Components/ExponentialHeightFogComponent.h" "ENGINE_API void SetDirectionalInscatteringExponent(float Value);"
rp_check "world fix: Json TryGetField" "Json/Public/Dom/JsonObject.h" "TSharedPtr<FJsonValue> TryGetField(FStringView FieldName) const"
rp_check "world fix: Json AsArray" "Json/Public/Dom/JsonValue.h" "JSON_API const TArray<TSharedPtr<FJsonValue>>& AsArray() const;"
rp_check "world fix: Json AsObject" "Json/Public/Dom/JsonValue.h" "JSON_API virtual const TSharedPtr<FJsonObject>& AsObject() const;"
rp_check "world fix: Json AsNumber" "Json/Public/Dom/JsonValue.h" "JSON_API double AsNumber() const;"
rp_check "world fix: Json AsString" "Json/Public/Dom/JsonValue.h" "JSON_API FString AsString() const;"
rp_check "world fix: StaticMesh GetStaticMaterials" "Engine/Classes/Engine/StaticMesh.h" "const TArray<FStaticMaterial>& GetStaticMaterials() const"
rp_check "world fix: StaticMesh GetMaterial" "Engine/Classes/Engine/StaticMesh.h" "ENGINE_API UMaterialInterface* GetMaterial(int32 MaterialIndex) const;"
rp_check "world fix: MaterialInterface GetBaseMaterial" "Engine/Public/Materials/MaterialInterface.h" "ENGINE_API UMaterial* GetBaseMaterial();"
rp_check "world fix: ISM SetCullDistances (start, end)" "Engine/Classes/Components/InstancedStaticMeshComponent.h" "ENGINE_API void SetCullDistances(int32 StartCullDistance, int32 EndCullDistance);"
rp_check "world fix: PerInstanceFadeAmount expression" "Engine/Public/Materials/MaterialExpressionPerInstanceFadeAmount.h" "class UMaterialExpressionPerInstanceFadeAmount"
rp_check "world fix: Material OpacityMaskClipValue" "Engine/Public/Materials/Material.h" "float OpacityMaskClipValue;"
rp_check "world fix: Material bUsedWithInstancedStaticMeshes" "Engine/Public/Materials/Material.h" "uint8 bUsedWithInstancedStaticMeshes : 1;"
rp_check "world fix: material SvPosition" "../../Shaders/Private/MaterialTemplate.ush" "float4 SvPosition;"
# -- world lane fix pass -- end ------------------------------------------------
# -- clouds-sky round 2 (visual overhaul, 2026-11-09) -- begin ----------------
# FlightSimClouds.cpp: the march by GPU class, the per-layer shadow length,
# the default layer's thinning, the fog on every cloud pixel and the sky's
# multiple scattering. Each pattern was read in the 5.7.4 source on 2026-11-09
# (paths under $RT); the two shader rows are the premises the banding fix
# rests on (the view march is jittered, the shadow march is not).
rp_check "clouds-sky: VolumetricCloud SetLayerHeight" "Engine/Classes/Components/VolumetricCloudComponent.h" "ENGINE_API void SetLayerHeight(float NewValue);"
rp_check "clouds-sky: VolumetricCloud SetShadowTracingDistance" "Engine/Classes/Components/VolumetricCloudComponent.h" "ENGINE_API void SetShadowTracingDistance(float NewValue);"
rp_check "clouds-sky: VolumetricCloud SetTracingMaxDistance" "Engine/Classes/Components/VolumetricCloudComponent.h" "ENGINE_API void SetTracingMaxDistance(float NewValue);"
rp_check "clouds-sky: VolumetricCloud SetStopTracingTransmittanceThreshold" "Engine/Classes/Components/VolumetricCloudComponent.h" "ENGINE_API void SetStopTracingTransmittanceThreshold(float NewValue);"
rp_check "clouds-sky: VolumetricCloud BaseViewRaySampleCount 96" "Engine/Classes/Components/VolumetricCloudComponent.h" "static constexpr float BaseViewRaySampleCount = 96.0f;"
rp_check "clouds-sky: VolumetricCloud BaseShadowRaySampleCount 10" "Engine/Classes/Components/VolumetricCloudComponent.h" "static constexpr float BaseShadowRaySampleCount = 10.0f;"
rp_check "clouds-sky: SkyAtmosphere SetMultiScatteringFactor" "Engine/Classes/Components/SkyAtmosphereComponent.h" "ENGINE_API void SetMultiScatteringFactor(float NewValue);"
rp_check "clouds-sky: SkyAtmosphere MultiScatteringFactor" "Engine/Classes/Components/SkyAtmosphereComponent.h" "float MultiScatteringFactor;"
rp_check "clouds-sky: GRHIDeviceIsIntegrated" "RHI/Public/RHIGlobals.h" "#define GRHIDeviceIsIntegrated"
rp_check "clouds-sky: GRHIAdapterName" "RHI/Public/RHIGlobals.h" "#define GRHIAdapterName"
rp_check "clouds-sky: RHIGlobals DeviceIsIntegrated" "RHI/Public/RHIGlobals.h" "bool DeviceIsIntegrated = false;"
rp_cvar r.VolumetricCloud.ApplyFogOnAllPixel "Renderer/Private/VolumetricCloudRendering.cpp"
rp_check "clouds-sky: view sample cap 768" "Renderer/Private/VolumetricCloudRendering.cpp" "TEXT(\"r.VolumetricCloud.ViewRaySampleMaxCount\"), 768,"
rp_check "clouds-sky: shadow sample cap 80" "Renderer/Private/VolumetricCloudRendering.cpp" "TEXT(\"r.VolumetricCloud.Shadow.ViewRaySampleMaxCount\"), 80,"
rp_check "clouds-sky: view march blue-noise jitter" "../../Shaders/Private/VolumetricCloud.usf" "t = TMin + BlueNoiseScalar(FullResPixelCoord, View.StateFrameIndexMod8) * StepT;"
rp_check "clouds-sky: shadow march unjittered" "../../Shaders/Private/VolumetricCloud.usf" "const float ShadowJitterNorm = 0.5f; // InterleavedGradientNoise"
# Round 52 (round 51's cloud tiers): M_FlightSimCloudLayers reads the engine's
# shadow-sample distance (Cloud Sample Attributes) and filters a shadow sample
# over its quadratic segment. Read in the 5.7 source on 2026-11-11.
rp_check "round 52: Cloud Sample Attributes ShadowSampleDistance pin" "Engine/Private/Materials/MaterialExpressions.cpp" "Outputs.Add(FExpressionOutput(TEXT(\"ShadowSampleDistance\")));"
rp_check "round 52: the sample carries its shadow distance" "../../Shaders/Private/VolumetricCloudMaterialPixelCommon.ush" "MaterialParameters.ShadowSampleDistance = ShadowSampleDistance;"
rp_check "round 52: a shadow sample passes its distance" "../../Shaders/Private/VolumetricCloud.usf" "ResolvedView, CloudLayerParams, ShadowSampleDistance, SPACE_SKIPPING_SLICE_DEPTH_OFF);"
rp_check "round 52: the shadow march is quadratic" "../../Shaders/Private/VolumetricCloud.usf" "float CurrentNormT = ShadowT * ShadowT;"
rp_check "round 52: the shadow march stops leaving the layer" "../../Shaders/Private/VolumetricCloud.usf" "break; // Ignore remaining samples since we have just traveled out of the cloud layer."
# -- clouds-sky round 2 -- end -------------------------------------------------
# -- visual round 5, lane L3 (2026-11-10): the distant cloud sheet, the sky HDRI probe --
# FlightSimClouds.cpp ApplyDistantClouds / ApplySkyHdri and the material the
# editor script builds (scripts/ue_create_materials.py create_world_distant_clouds).
# Each pattern was read in the 5.7 source on 2026-11-10.
# The engine-content finding, recorded either way (the sky sphere is NOT used:
# it would cover the SkyAtmosphere; the far deck is our own translucent sheet).
if [ -f "$UE_ROOT/Engine/Content/EngineSky/BP_Sky_Sphere.uasset" ] && \
   [ -f "$UE_ROOT/Engine/Content/EngineSky/M_Sky_Panning_Clouds2.uasset" ]; then
    ok "distant: EngineSky sky sphere" "UE 5.7 still ships BP_Sky_Sphere + M_Sky_Panning_Clouds2 (recorded, not used)"
else
    ok "distant: EngineSky sky sphere" "absent in this engine (recorded; not used either way)"
fi
PMC="../../Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h"
rp_check "distant: ProceduralMesh CreateMeshSection_LinearColor" "$PMC" "void CreateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<int32>& Triangles, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FLinearColor>& VertexColors, const TArray<FProcMeshTangent>& Tangents, bool bCreateCollision, bool bSRGBConversion = false)"
# Lane D (2026-11-11): the beauty rain veil's scud cards (FlightSimWeather.cpp
# AdvanceBeautyRainVeil) update their quads per frame with UV1 (alpha, seed);
# read in the 5.7 source on 2026-11-11.
rp_check "rain-veil: ProceduralMesh UpdateMeshSection_LinearColor with UV1..3" "$PMC" "UE_API void UpdateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FVector2D>& UV1, const TArray<FVector2D>& UV2, const TArray<FVector2D>& UV3,"
rp_check "rain-veil: ProceduralMesh CreateMeshSection_LinearColor with UV1..3" "$PMC" "UE_API void CreateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<int32>& Triangles, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FVector2D>& UV1, const TArray<FVector2D>& UV2, const TArray<FVector2D>& UV3,"
rp_check "distant: Primitive SetRenderCustomDepth" "Engine/Classes/Components/PrimitiveComponent.h" "ENGINE_API void SetRenderCustomDepth(bool bValue);"
rp_check "distant: Primitive SetTranslucentSortPriority" "Engine/Classes/Components/PrimitiveComponent.h" "ENGINE_API void SetTranslucentSortPriority(int32 NewTranslucentSortPriority);"
rp_check "distant: Primitive SetReceivesDecals" "Engine/Classes/Components/PrimitiveComponent.h" "ENGINE_API void SetReceivesDecals(bool bNewReceivesDecals);"
rp_check "distant: Primitive SetCastShadow" "Engine/Classes/Components/PrimitiveComponent.h" "ENGINE_API void SetCastShadow(bool NewCastShadow);"
rp_check "distant: Material Apply Fogging" "Engine/Public/Materials/Material.h" "uint8 bUseTranslucencyVertexFog : 1;"
rp_check "distant: Material bComputeFogPerPixel" "Engine/Public/Materials/Material.h" "uint8 bComputeFogPerPixel : 1;"
rp_check "distant: Material bApplyCloudFogging" "Engine/Public/Materials/Material.h" "uint8 bApplyCloudFogging : 1;"
rp_check "distant: Material AllowTranslucentCustomDepthWrites" "Engine/Public/Materials/Material.h" "uint8 AllowTranslucentCustomDepthWrites : 1;"
rp_check "distant: Material bOutputTranslucentVelocity" "Engine/Public/Materials/Material.h" "uint8 bOutputTranslucentVelocity : 1;"
rp_check "distant: SkyAtmosphereLightDirection node" "Engine/Public/Materials/MaterialExpressionSkyAtmosphereLightDirection.h" "class UMaterialExpressionSkyAtmosphereLightDirection"
rp_check "distant: SkyAtmosphereLightIlluminance node" "Engine/Public/Materials/MaterialExpressionSkyAtmosphereLightIlluminance.h" "class UMaterialExpressionSkyAtmosphereLightIlluminance"
rp_check "distant: SkyAtmosphereDistantLightScatteredLuminance node" "Engine/Public/Materials/MaterialExpressionSkyAtmosphereLightIlluminance.h" "class UMaterialExpressionSkyAtmosphereDistantLightScatteredLuminance"
rp_check "distant: sky light node LightIndex" "Engine/Public/Materials/MaterialExpressionSkyAtmosphereLightDirection.h" "int32 LightIndex;"
rp_check "distant: translucency applies cloud fogging" "../../Shaders/Private/BasePassPixelShader.usf" "TranslucentBasePass.ApplyVolumetricCloudOnTransparent > 0.0f"
# The march's cost law the trace shrink rests on: the sample count is
# non-decreasing in the traced path, capped at SampleCountMax past
# r.VolumetricCloud.DistanceToSampleMaxCount, so a shorter trace never adds a sample.
rp_check "distant: cloud sample count law" "../../Shaders/Private/VolumetricCloud.usf" "RenderVolumetricCloudParameters.SampleCountMax * saturate((TMax - TMin) * RenderVolumetricCloudParameters.InvDistanceToSampleCountMax)"
rp_cvar r.VolumetricCloud.DistanceToSampleMaxCount "Renderer/Private/VolumetricCloudRendering.cpp"
rp_check "distant: trace clamps TMax" "../../Shaders/Private/VolumetricCloud.usf" "const float MarchingDistance = min(RenderVolumetricCloudParameters.TracingMaxDistance, TMax - TMin);"
# The sky HDRI probe (ApplySkyHdri).
rp_check "sky-hdri: SLS_SpecifiedCubemap" "Engine/Classes/Components/SkyLightComponent.h" "SLS_SpecifiedCubemap,"
rp_check "sky-hdri: SkyLight SourceType" "Engine/Classes/Components/SkyLightComponent.h" "TEnumAsByte<enum ESkyLightSourceType> SourceType;"
rp_check "sky-hdri: SkyLight Cubemap" "Engine/Classes/Components/SkyLightComponent.h" "TObjectPtr<class UTextureCube> Cubemap;"
rp_check "sky-hdri: SkyLight SetCubemap" "Engine/Classes/Components/SkyLightComponent.h" "ENGINE_API void SetCubemap(UTextureCube* NewCubemap);"
rp_check "sky-hdri: SkyLight SetSourceCubemapAngle" "Engine/Classes/Components/SkyLightComponent.h" "ENGINE_API void SetSourceCubemapAngle(float NewValue);"
rp_check "sky-hdri: SkyLight SetRealTimeCapture" "Engine/Classes/Components/SkyLightComponent.h" "ENGINE_API void SetRealTimeCapture(bool bInRealTimeCapture);"
rp_check "sky-hdri: SkyLight SetCaptureIsDirty" "Engine/Classes/Components/SkyLightComponent.h" "ENGINE_API void SetCaptureIsDirty();"
rp_check "sky-hdri: SkyLight IsRealTimeCaptureEnabled" "Engine/Classes/Components/SkyLightComponent.h" "IsRealTimeCaptureEnabled()"
rp_check "sky-hdri: UTextureCube header" "Engine/Classes/Engine/TextureCube.h" "class UTextureCube"
# -- visual round 5, lane L3 -- end --------------------------------------------

# -- sun-shafts-sky-occlusion (visual overhaul, 2026-11-09) -----------------
# FlightSimSunShafts.cpp: the sun's light shafts and cloud shadow, the sky
# light's cloud AO, and the cvars it sets (each grepped in the 5.7.4 source
# when written; r.LightShaftNumSamples was dropped, ECVF_ReadOnly). Paths are
# relative to $UE_ROOT/Engine/Source/Runtime.
sunshafts_check() {  # label, file (relative to $RT), fixed-string pattern
    if [ ! -f "$RT/$2" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$RT/$2"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimSunShafts.cpp needs updating"
    fi
}
SS_DLC="Engine/Classes/Components/DirectionalLightComponent.h"
SS_LC="Engine/Classes/Components/LightComponent.h"
SS_SKY="Engine/Classes/Components/SkyLightComponent.h"
sunshafts_check "sun-shafts: DirectionalLight SetEnableLightShaftOcclusion" "$SS_DLC" "ENGINE_API void SetEnableLightShaftOcclusion(bool bNewValue);"
sunshafts_check "sun-shafts: DirectionalLight SetOcclusionMaskDarkness" "$SS_DLC" "ENGINE_API void SetOcclusionMaskDarkness(float NewValue);"
sunshafts_check "sun-shafts: DirectionalLight SetOcclusionDepthRange" "$SS_DLC" "ENGINE_API void SetOcclusionDepthRange(float NewValue);"
sunshafts_check "sun-shafts: Light SetEnableLightShaftBloom" "$SS_LC" "ENGINE_API void SetEnableLightShaftBloom(bool bNewValue);"
sunshafts_check "sun-shafts: Light SetBloomScale" "$SS_LC" "ENGINE_API void SetBloomScale(float NewValue);"
sunshafts_check "sun-shafts: Light SetBloomThreshold" "$SS_LC" "ENGINE_API void SetBloomThreshold(float NewValue);"
sunshafts_check "sun-shafts: Light SetBloomMaxBrightness" "$SS_LC" "ENGINE_API void SetBloomMaxBrightness(float NewValue);"
sunshafts_check "sun-shafts: DirectionalLight CloudShadowOnAtmosphereStrength" "$SS_DLC" "float CloudShadowOnAtmosphereStrength;"
sunshafts_check "sun-shafts: DirectionalLight CloudShadowOnSurfaceStrength" "$SS_DLC" "float CloudShadowOnSurfaceStrength;"
sunshafts_check "sun-shafts: DirectionalLight CloudShadowExtent" "$SS_DLC" "float CloudShadowExtent;"
sunshafts_check "sun-shafts: DirectionalLight CloudShadowMapResolutionScale" "$SS_DLC" "float CloudShadowMapResolutionScale;"
sunshafts_check "sun-shafts: DirectionalLight CloudShadowRaySampleCountScale" "$SS_DLC" "float CloudShadowRaySampleCountScale;"
sunshafts_check "sun-shafts: DirectionalLight bCastCloudShadows" "$SS_DLC" "uint32 bCastCloudShadows : 1;"
sunshafts_check "sun-shafts: SkyLight bCloudAmbientOcclusion" "$SS_SKY" "uint32 bCloudAmbientOcclusion : 1;"
sunshafts_check "sun-shafts: SkyLight CloudAmbientOcclusionStrength" "$SS_SKY" "float CloudAmbientOcclusionStrength;"
sunshafts_check "sun-shafts: SkyLight CloudAmbientOcclusionExtent" "$SS_SKY" "float CloudAmbientOcclusionExtent;"
sunshafts_check "sun-shafts: SkyLight CloudAmbientOcclusionMapResolutionScale" "$SS_SKY" "float CloudAmbientOcclusionMapResolutionScale;"
sunshafts_check "sun-shafts: SkyLight CloudAmbientOcclusionApertureScale" "$SS_SKY" "float CloudAmbientOcclusionApertureScale;"
sunshafts_check "sun-shafts: SkyLight bRealTimeCapture" "$SS_SKY" "bool bRealTimeCapture;"
sunshafts_check "sun-shafts: ActorComponent MarkRenderStateDirty" "Engine/Classes/Components/ActorComponent.h" "ENGINE_API void MarkRenderStateDirty();"
sunshafts_check "sun-shafts: show flag LightShafts" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(LightShafts,"
sunshafts_check "sun-shafts: show flag VolumetricFog" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(VolumetricFog,"
sunshafts_cvar() {  # cvar name, file (relative to $RT)
    sunshafts_check "sun-shafts: cvar $1" "$2" "TEXT(\"$1\")"
}
sunshafts_cvar r.VolumetricFog.GridPixelSize "Renderer/Private/VolumetricFog.cpp"
sunshafts_cvar r.VolumetricFog.GridSizeZ "Renderer/Private/VolumetricFog.cpp"
sunshafts_cvar r.VolumetricFog.HistoryMissSupersampleCount "Renderer/Private/VolumetricFog.cpp"
sunshafts_cvar r.VolumetricCloud.ShadowMap "Renderer/Private/VolumetricCloudRendering.cpp"
sunshafts_cvar r.VolumetricCloud.SkyAO "Renderer/Private/VolumetricCloudRendering.cpp"
sunshafts_cvar r.VolumetricCloud.HighQualityAerialPerspective "Renderer/Private/VolumetricCloudRendering.cpp"
sunshafts_cvar r.VolumetricCloud.Shadow.SampleAtmosphericLightShadowmap "Renderer/Private/VolumetricCloudRendering.cpp"
sunshafts_cvar r.SkyLight.RealTimeReflectionCapture.TimeSlice "Renderer/Private/ReflectionEnvironmentRealTimeCapture.cpp"
sunshafts_cvar r.SkyLight.RealTimeReflectionCapture.VolumetricCloudResolutionDivider "Renderer/Private/ReflectionEnvironmentRealTimeCapture.cpp"
sunshafts_cvar r.SkyLight.RealTimeReflectionCapture.ShadowFromOpaque "Renderer/Private/ReflectionEnvironmentRealTimeCapture.cpp"
sunshafts_cvar r.LightShaftQuality "Renderer/Private/LightShaftRendering.cpp"
sunshafts_cvar r.LightShaftDownSampleFactor "Renderer/Private/LightShaftRendering.cpp"
# -- end sun-shafts-sky-occlusion --------------------------------------------

# -- dust-humidity-haze (visual overhaul, 2026-11-09): the haze overlay ------
# FlightSimDustHaze.cpp: RH growth on the Mie, the dust tint, the second fog
# at the inversion height. Each symbol was read in the 5.7.4 headers when
# written; this re-checks them before a build.
sky_check "dust-haze: SkyAtmosphere SetMieAbsorption" "$SKYC" "void SetMieAbsorption(FLinearColor NewValue)"
sky_check "dust-haze: SkyAtmosphere SetOtherAbsorption" "$SKYC" "void SetOtherAbsorption(FLinearColor NewValue)"
sky_check "dust-haze: SkyAtmosphere SetOtherAbsorptionScale" "$SKYC" "void SetOtherAbsorptionScale(float NewValue)"
sky_check "dust-haze: SkyAtmosphere MieScatteringScale property" "$SKYC" "float MieScatteringScale;"
sky_check "dust-haze: SkyAtmosphere MieAbsorptionScale property" "$SKYC" "float MieAbsorptionScale;"
sky_check "dust-haze: Fog SetSecondFogData" "$FOG" "void SetSecondFogData(FExponentialHeightFogData NewValue)"
sky_check "dust-haze: Fog SetVolumetricFogAlbedo" "$FOG" "void SetVolumetricFogAlbedo(FColor NewValue)"
sky_check "dust-haze: Fog SetFogDensity" "$FOG" "void SetFogDensity(float Value)"
sky_check "dust-haze: FExponentialHeightFogData FogDensity" "Public/Rendering/ExponentialHeightFogData.h" "float FogDensity = 0.02f;"
sky_check "dust-haze: FExponentialHeightFogData FogHeightFalloff" "Public/Rendering/ExponentialHeightFogData.h" "float FogHeightFalloff = 0.2f;"
sky_check "dust-haze: FExponentialHeightFogData FogHeightOffset" "Public/Rendering/ExponentialHeightFogData.h" "float FogHeightOffset = 0.0f;"
if grep -qF 'FogData[1].Height = State.Height + State.SecondFogData.FogHeightOffset;' \
    "$UE_ROOT/Engine/Source/Runtime/Renderer/Private/SceneCore.cpp" 2>/dev/null; then
    ok "dust-haze: premise second fog height = actor Z + offset" "present"
else
    bad "dust-haze: premise second fog height = actor Z + offset" "SceneCore.cpp changed: FlightSimDustHaze.cpp's offset needs re-reading"
fi
if grep -qF 'FogData[1].HeightFalloff = State.SecondFogData.FogHeightFalloff / 1000.0f;' \
    "$UE_ROOT/Engine/Source/Runtime/Renderer/Private/SceneCore.cpp" 2>/dev/null; then
    ok "dust-haze: premise falloff / 1000 per cm" "present"
else
    bad "dust-haze: premise falloff / 1000 per cm" "SceneCore.cpp changed: core/scene/dust_haze.py FALLOFF_TO_PER_M needs re-reading"
fi
# -- AIRCRAFT LANE: engine surface the airframe look assumes ----------------
# FlightSimAircraftFX.cpp (lights, bulbs, trails, plume, haze, the slot swap)
# and scripts/ue_aircraft_master_materials.py (the masters' properties and
# enums), written on a Mac that cannot compile UE 5.7 (visual overhaul V7).
# Each line is one symbol grepped in the 5.7.4 headers when it was written.
ENGINE_SRC="$UE_ROOT/Engine/Source"
aircraft_check() {  # label, header (relative to $ENGINE_SRC or $UE_ROOT/Engine), fixed-string pattern
    local header="$ENGINE_SRC/$2"
    [ -f "$header" ] || header="$UE_ROOT/Engine/$2"
    if [ ! -f "$header" ]; then
        bad "$1" "header $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$header"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimAircraftFX.cpp / ue_aircraft_master_materials.py need updating"
    fi
}
RE="Runtime/Engine"
aircraft_check "PointLight SetSourceRadius" "$RE/Classes/Components/PointLightComponent.h" "void SetSourceRadius"
aircraft_check "LocalLight SetAttenuationRadius" "$RE/Classes/Components/LocalLightComponent.h" "void SetAttenuationRadius"
aircraft_check "LocalLight SetIntensityUnits" "$RE/Classes/Components/LocalLightComponent.h" "void SetIntensityUnits"
aircraft_check "ELightUnits::Candelas" "$RE/Classes/Engine/Scene.h" "Candelas UMETA"
aircraft_check "SpotLight SetInnerConeAngle" "$RE/Classes/Components/SpotLightComponent.h" "void SetInnerConeAngle"
aircraft_check "SpotLight SetOuterConeAngle" "$RE/Classes/Components/SpotLightComponent.h" "void SetOuterConeAngle"
aircraft_check "Light SetLightColor" "$RE/Classes/Components/LightComponent.h" "void SetLightColor"
aircraft_check "LightBase SetCastShadows" "$RE/Classes/Components/LightComponentBase.h" "void SetCastShadows"
aircraft_check "Actor AttachToActor" "$RE/Classes/GameFramework/Actor.h" "bool AttachToActor(AActor* ParentActor, const FAttachmentTransformRules& AttachmentRules"
aircraft_check "Actor SetActorRelativeLocation" "$RE/Classes/GameFramework/Actor.h" "void SetActorRelativeLocation(FVector NewRelativeLocation"
aircraft_check "AttachmentRules KeepRelativeTransform" "$RE/Classes/Engine/EngineTypes.h" "static ENGINE_API FAttachmentTransformRules KeepRelativeTransform"
aircraft_check "MeshComponent GetMaterial" "$RE/Classes/Components/MeshComponent.h" "virtual UMaterialInterface* GetMaterial(int32 ElementIndex) const override"
aircraft_check "MID Create" "$RE/Public/Materials/MaterialInstanceDynamic.h" "static ENGINE_API UMaterialInstanceDynamic* Create( class UMaterialInterface* ParentMaterial, class UObject* InOuter"
aircraft_check "MID SetVectorParameterValue" "$RE/Public/Materials/MaterialInstanceDynamic.h" "void SetVectorParameterValue(FName ParameterName, FLinearColor Value)"
aircraft_check "Material bUseMaterialAttributes" "$RE/Public/Materials/Material.h" "uint8 bUseMaterialAttributes : 1"
aircraft_check "Material bTangentSpaceNormal" "$RE/Public/Materials/Material.h" "uint8 bTangentSpaceNormal : 1"
aircraft_check "Material RefractionMethod" "$RE/Public/Materials/Material.h" "TEnumAsByte<ERefractionMode> RefractionMethod"
aircraft_check "Material TranslucencyLightingMode" "$RE/Public/Materials/Material.h" "TEnumAsByte<ETranslucencyLightingMode> TranslucencyLightingMode"
aircraft_check "RefractionMode RM_2DOffset" "$RE/Classes/Engine/EngineTypes.h" "RM_2DOffset"
aircraft_check "ShadingModel MSM_ClearCoat" "$RE/Classes/Engine/EngineTypes.h" "MSM_ClearCoat"
aircraft_check "TLM_VolumetricNonDirectional" "$RE/Classes/Engine/EngineTypes.h" "TLM_VolumetricNonDirectional"
aircraft_check "MP_MaterialAttributes (not Hidden)" "$RE/Public/SceneTypes.h" "MP_MaterialAttributes,"
aircraft_check "MP_Refraction" "$RE/Public/SceneTypes.h" "MP_Refraction UMETA(DisplayName = \"Refraction\")"
aircraft_check "MakeMaterialAttributes ClearCoat" "$RE/Public/Materials/MaterialExpressionMakeMaterialAttributes.h" "FExpressionInput ClearCoatRoughness;"
aircraft_check "Fresnel ExponentIn" "$RE/Public/Materials/MaterialExpressionFresnel.h" "ExponentIn"
# fix pass: the glass master zeroes the node's base reflect fraction (default
# 0.04) so the face-on F0 is the class Specular's, and that F0 is 0.08 x Specular.
aircraft_check "Fresnel BaseReflectFraction default 0.04" "$RE/Public/Materials/MaterialExpressionFresnel.h" "float BaseReflectFraction = 0.04f;"
aircraft_check "F0 = 0.08 x Specular" "Shaders/Private/ShadingCommon.ush" "return half(0.08f * Specular);"
# fix pass: the landing bulb's beam (camera vector, the actor-frame axis to
# world, normalised) and the heat haze's engine scale (the 2D offset times
# width x 0.00023 x the projection's M[0][0], FlightSimAircraftFX.cpp
# HeatHazeMaxDisplacementPx, with the capture's FOVAngle).
aircraft_check "MaterialExpressionCameraVectorWS" "$RE/Public/Materials/MaterialExpressionCameraVectorWS.h" "class UMaterialExpressionCameraVectorWS"
aircraft_check "MaterialExpressionNormalize" "$RE/Public/Materials/MaterialExpressionNormalize.h" "class UMaterialExpressionNormalize"
aircraft_check "2D offset fudge 0.00023" "Shaders/Private/DistortionCommon.ush" "const float OffsetFudgeFactor = 0.00023;"
aircraft_check "2D offset x view width x fudge x FOV fix" "Shaders/Private/DistortionCommon.ush" "BufferUVDistortion *= DistortionParameters.zw * float2(OffsetFudgeFactor, -OffsetFudgeFactor) * FovFix;"
aircraft_check "distortion params: M[0][0], aspect, width, height" "Runtime/Renderer/Private/DistortionRendering.cpp" "DistortionParams.Z = (float)View.UnscaledViewRect.Width();"
aircraft_check "SceneCapture2D FOVAngle" "$RE/Classes/Components/SceneCaptureComponent2D.h" "float FOVAngle;"
aircraft_check "Custom CMOT_Float4" "$RE/Public/Materials/MaterialExpressionCustom.h" "CMOT_Float4"
aircraft_check "MaterialExpressionLocalPosition" "$RE/Public/Materials/MaterialExpressionLocalPosition.h" "class UMaterialExpressionLocalPosition"
aircraft_check "MaterialExpressionTransform" "$RE/Public/Materials/MaterialExpressionTransform.h" "TransformSourceType"
aircraft_check "ProcMesh CreateMeshSection_LinearColor" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "void CreateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<int32>& Triangles, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FLinearColor>& VertexColors"
aircraft_check "ProcMesh ClearMeshSection" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "void ClearMeshSection(int32 SectionIndex)"
aircraft_check "RotationMatrix MakeFromX" "Runtime/Core/Public/Math/RotationMatrix.h" "MakeFromX(TVector<T> const& XAxis)"
aircraft_check "Math UE_DOUBLE_PI" "Runtime/Core/Public/Math/UnrealMathUtility.h" "#define UE_DOUBLE_PI"
# round 5 (L4, 2026-11-10): the Thin Translucent canopy master
# (scripts/ue_aircraft_master_materials.py create_aircraft_glass_thin), the
# measured-material graph nodes, and the -labels gate in FlightSimAircraftFX.cpp.
aircraft_check "round5: ShadingModel MSM_ThinTranslucent" "$RE/Classes/Engine/EngineTypes.h" "MSM_ThinTranslucent"
aircraft_check "round5: TLM_SurfacePerPixelLighting" "$RE/Classes/Engine/EngineTypes.h" "TLM_SurfacePerPixelLighting"
aircraft_check "round5: RefractionMode RM_None" "$RE/Classes/Engine/EngineTypes.h" "RM_None"
aircraft_check "round5: thin translucent needs Surface ForwardShading" "Runtime/Engine/Private/Materials/MaterialShared.cpp" "TranslucencyLightingMode != ETranslucencyLightingMode::TLM_SurfacePerPixelLighting"
aircraft_check "round5: thin translucent needs the output node" "Runtime/Engine/Private/Materials/MaterialShared.cpp" "HasAnyExpressionsInMaterialAndFunctionsOfType<UMaterialExpressionThinTranslucentMaterialOutput>()"
aircraft_check "round5: ThinTranslucentMaterialOutput TransmittanceColor" "$RE/Public/Materials/MaterialExpressionThinTranslucentMaterialOutput.h" "FExpressionInput TransmittanceColor;"
aircraft_check "round5: Material bScreenSpaceReflections" "$RE/Public/Materials/Material.h" "uint8 bScreenSpaceReflections : 1;"
aircraft_check "round5: Material AllowTranslucentCustomDepthWrites" "$RE/Public/Materials/Material.h" "uint8 AllowTranslucentCustomDepthWrites : 1;"
aircraft_check "round5: Material TwoSided" "$RE/Public/Materials/Material.h" "uint8 TwoSided : 1;"
aircraft_check "round5: D3D SM5 dual-source blending" "Config/Windows/DataDrivenPlatformInfo.ini" "bSupportsDualSourceBlending=true"
aircraft_check "round5: thin translucent single-target fallback" "Shaders/Private/BasePassPixelShader.usf" "float AdjustedAlpha = saturate(1-dot(AdjustedDualBlendMul,float3(1.0f,1.0f,1.0f)/3.0f));"
aircraft_check "round5: dual-source blending asked by the model" "Runtime/Engine/Private/Materials/MaterialShared.cpp" "bool bMaterialRequestsDualSourceBlending = Material->ShadingModel == MSM_ThinTranslucent;"
aircraft_check "round5: MaterialExpressionMin" "$RE/Public/Materials/MaterialExpressionMin.h" "class UMaterialExpressionMin : public UMaterialExpression"
aircraft_check "round5: MaterialExpressionMax" "$RE/Public/Materials/MaterialExpressionMax.h" "class UMaterialExpressionMax : public UMaterialExpression"
aircraft_check "round5: FParse Param (the -labels gate)" "Runtime/Core/Public/Misc/Parse.h" "static CORE_API bool Param( const TCHAR* Stream, const TCHAR* Param );"
# -- CONDENSATION (condensation-solver) --------------------------------------
# FlightSimCondensation.cpp (the humidity-gated vapour sites: mesh vertices
# read from LOD 0, the attached and world-space ribbons) and
# scripts/aircraft_condensation_material.py (M_AircraftCondensation's nodes).
# Each line is one symbol grepped in the 5.7.4 headers when it was written.
aircraft_check "condensation: UStaticMesh GetRenderData" "$RE/Classes/Engine/StaticMesh.h" "ENGINE_API const FStaticMeshRenderData* GetRenderData() const;"
aircraft_check "condensation: RenderData LODResources" "$RE/Public/StaticMeshResources.h" "FStaticMeshLODResourcesArray LODResources;"
aircraft_check "condensation: LODResources VertexBuffers" "$RE/Public/StaticMeshResources.h" "FStaticMeshVertexBuffers VertexBuffers;"
aircraft_check "condensation: VertexBuffers PositionVertexBuffer" "$RE/Public/StaticMeshResources.h" "FPositionVertexBuffer PositionVertexBuffer;"
aircraft_check "condensation: PositionVertexBuffer VertexPosition" "$RE/Public/Rendering/PositionVertexBuffer.h" "inline const FVector3f& VertexPosition(uint32 VertexIndex) const"
aircraft_check "condensation: PositionVertexBuffer GetVertexData" "$RE/Public/Rendering/PositionVertexBuffer.h" "const void* GetVertexData() const { return Data; }"
aircraft_check "condensation: PositionVertexBuffer GetNumVertices" "$RE/Public/Rendering/PositionVertexBuffer.h" "inline uint32 GetNumVertices() const"
aircraft_check "condensation: editor keeps mesh CPU data" "$RE/Private/StaticMesh.cpp" "bool bNeedsCPUAccess = !FPlatformProperties::RequiresCookedData()"
aircraft_check "condensation: StaticMeshComponent GetStaticMesh" "$RE/Classes/Components/StaticMeshComponent.h" "TObjectPtr<UStaticMesh> GetStaticMesh() const"
aircraft_check "condensation: Transform GetRelativeTransform" "Runtime/Core/Public/Math/TransformVectorized.h" "TTransform<T> GetRelativeTransform(const TTransform<T>& Other) const;"
aircraft_check "condensation: FParse Value double" "Runtime/Core/Public/Misc/Parse.h" "static CORE_API bool Value(const TCHAR* Stream, const TCHAR* Match, double& Value);"
aircraft_check "condensation: FMath IsFinite double" "Runtime/Core/Public/GenericPlatform/GenericPlatformMath.h" "static UE_FORCEINLINE_HINT bool IsFinite(double A)"
aircraft_check "condensation: FJsonValueNull" "Runtime/Json/Public/Dom/JsonValue.h" "class FJsonValueNull : public FJsonValue"
aircraft_check "condensation: UMaterialExpressionDepthFade" "$RE/Public/Materials/MaterialExpressionDepthFade.h" "class UMaterialExpressionDepthFade : public UMaterialExpression"
aircraft_check "condensation: DepthFade FadeDistanceDefault" "$RE/Public/Materials/MaterialExpressionDepthFade.h" "float FadeDistanceDefault"
aircraft_check "condensation: UMaterialExpressionNoise" "$RE/Public/Materials/MaterialExpressionNoise.h" "class UMaterialExpressionNoise : public UMaterialExpression"
aircraft_check "condensation: Noise OutputMax" "$RE/Public/Materials/MaterialExpressionNoise.h" "float OutputMax;"
aircraft_check "condensation: UMaterialExpressionVertexColor" "$RE/Public/Materials/MaterialExpressionVertexColor.h" "class UMaterialExpressionVertexColor"
# -- CONDENSATION -- end
if [ -f "$UE_ROOT/Engine/Content/EngineResources/WhiteSquareTexture.uasset" ]; then
    ok "engine WhiteSquareTexture" "present"
else
    bad "engine WhiteSquareTexture" "missing: the aircraft masters' BaseColorMap default"
fi

# -- WET-AIRFRAME-CANOPY: engine surface the wet airframe assumes ----------
# FlightSimAircraftWet.cpp (scalars on the look MIDs, the anisotropy cvar
# record) and scripts/aircraft_wet_layer.py (the graft: Break -> Custom with
# an additional output -> Make, the glass's world-space tangent), written on
# a Mac that cannot compile UE 5.7 (visual overhaul, 2026-11-09). Each line is
# one symbol grepped in the 5.7.4 headers when it was written.
wet_check() {  # label, file (relative to $UE_ROOT/Engine/Source or $UE_ROOT/Engine), fixed-string pattern
    local file="$UE_ROOT/Engine/Source/$2"
    [ -f "$file" ] || file="$UE_ROOT/Engine/$2"
    if [ ! -f "$file" ]; then
        bad "wet: $1" "$2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$file"; then
        ok "wet: $1" "present"
    else
        bad "wet: $1" "not found in $2 -- FlightSimAircraftWet.cpp / aircraft_wet_layer.py need updating"
    fi
}
WM="Runtime/Engine/Public/Materials"
wet_check "MID SetScalarParameterValue" "$WM/MaterialInstanceDynamic.h" "void SetScalarParameterValue(FName ParameterName, float Value)"
wet_check "MID Create" "$WM/MaterialInstanceDynamic.h" "static ENGINE_API UMaterialInstanceDynamic* Create( class UMaterialInterface* ParentMaterial, class UObject* InOuter"
wet_check "IConsoleManager FindConsoleVariable" "Runtime/Core/Public/HAL/IConsoleManager.h" "virtual IConsoleVariable* FindConsoleVariable(const TCHAR* Name"
wet_check "IConsoleVariable GetInt" "Runtime/Core/Public/HAL/IConsoleManager.h" "virtual int32 GetInt() const = 0;"
wet_check "cvar r.AnisotropicMaterials" "Runtime/Renderer/Private/AnisotropyRendering.cpp" 'TEXT("r.AnisotropicMaterials")'
wet_check "Cine scalability enables anisotropy" "Config/BaseScalability.ini" "r.AnisotropicMaterials=1"
wet_check "anisotropy tangent in the normal's space" "Shaders/Private/MaterialTemplate.ush" "float3 CalculateAnisotropyTangent"
wet_check "Custom AdditionalOutputs" "$WM/MaterialExpressionCustom.h" "TArray<struct FCustomOutput> AdditionalOutputs;"
wet_check "FCustomOutput OutputName" "$WM/MaterialExpressionCustom.h" "FName OutputName;"
wet_check "Custom output 0 is 'return'" "Runtime/Engine/Private/Materials/MaterialExpressions.cpp" 'Outputs.Add(FExpressionOutput(TEXT("return")));'
wet_check "Custom CMOT_Float1" "$WM/MaterialExpressionCustom.h" "CMOT_Float1"
wet_check "BreakMaterialAttributes" "$WM/MaterialExpressionBreakMaterialAttributes.h" "class UMaterialExpressionBreakMaterialAttributes"
wet_check "Break output ClearCoatRoughness" "Runtime/Engine/Private/Materials/MaterialExpressions.cpp" 'Outputs.Add(FExpressionOutput(TEXT("ClearCoatRoughness"), 1, 1, 0, 0, 0));'
wet_check "MakeMaterialAttributes Anisotropy" "$WM/MaterialExpressionMakeMaterialAttributes.h" "FExpressionInput Anisotropy;"
wet_check "MakeMaterialAttributes Tangent" "$WM/MaterialExpressionMakeMaterialAttributes.h" "FExpressionInput Tangent;"
wet_check "AppendVector" "$WM/MaterialExpressionAppendVector.h" "class UMaterialExpressionAppendVector"
wet_check "VertexNormalWS" "$WM/MaterialExpressionVertexNormalWS.h" "class UMaterialExpressionVertexNormalWS"
wet_check "EditingLibrary GetMaterialPropertyInputNode" "Editor/MaterialEditor/Public/MaterialEditingLibrary.h" "static UE_API UMaterialExpression* GetMaterialPropertyInputNode(UMaterial* Material, EMaterialProperty Property);"
wet_check "EditingLibrary GetMaterialPropertyInputNodeOutputName" "Editor/MaterialEditor/Public/MaterialEditingLibrary.h" "GetMaterialPropertyInputNodeOutputName(UMaterial* Material, EMaterialProperty Property);"
wet_check "Json TryGetObjectField (pointer)" "Runtime/Json/Public/Dom/JsonObject.h" "bool TryGetObjectField(FStringView FieldName, const TSharedPtr<FJsonObject>*& OutObject) const;"
wet_check "Json TryGetNumberField" "Runtime/Json/Public/Dom/JsonObject.h" "bool TryGetNumberField(FStringView FieldName, double& OutNumber) const;"
wet_check "FMath Exp(double)" "Runtime/Core/Public/GenericPlatform/GenericPlatformMath.h" "double Exp(double Value)"
# -- WET-AIRFRAME-CANOPY -- end

# -- ACES2-DISPLAY LANE: what the offline ACES 2.0 view assumes of -linear --
# core/capture/display.py reads frame_NNNN_linear.exr (SCS_FinalColorHDR) as
# graded, exposed, bloomed linear light with NO filmic curve. No C++ added;
# these pin the engine behaviour that reading rests on (grepped in 5.7.4).
aircraft_check "aces2: SCS_FinalColorHDR" "$RE/Classes/Engine/EngineTypes.h" "SCS_FinalColorHDR UMETA"
aircraft_check "aces2: FinalColorHDR -> LinearNoToneCurve" "Runtime/Renderer/Private/PostProcess/PostProcessTonemap.cpp" "OutputDeviceValue = EDisplayOutputFormat::HDR_LinearNoToneCurve;"
aircraft_check "aces2: bloom and exposure before the LUT" "Shaders/Private/PostProcessTonemap.usf" "FinalLinearColor += Bloom * (OneOverPreExposure * GlobalExposure"
# -- end ACES2-DISPLAY LANE --------------------------------------------------

# -- hero lighting (hero-lighting lane, 2026-11-09) ---- BEGIN hero lighting --
# FlightSimHeroLighting.cpp: the beauty sun / sky light quality. Each symbol
# was grepped in the UE 5.7.4 headers and sources on the authoring Mac (which
# cannot compile); re-checked here before a build. Cvar names are matched at
# their DEFINITION (the quoted name in the file that registers it).
hl_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimHeroLighting.cpp needs updating"
    fi
}
HLD="Engine/Classes/Components/DirectionalLightComponent.h"
HLL="Engine/Classes/Components/LightComponent.h"
HLB="Engine/Classes/Components/LightComponentBase.h"
HLS="Engine/Classes/Components/SkyLightComponent.h"
hl_check "hero: SetLightSourceAngle" "$HLD" "ENGINE_API void SetLightSourceAngle(float NewValue);"
hl_check "hero: SetLightSourceSoftAngle" "$HLD" "ENGINE_API void SetLightSourceSoftAngle(float NewValue);"
hl_check "hero: LightSourceAngle" "$HLD" "float LightSourceAngle;"
hl_check "hero: LightSourceSoftAngle" "$HLD" "float LightSourceSoftAngle;"
hl_check "hero: SetEnableLightShaftOcclusion" "$HLD" "ENGINE_API void SetEnableLightShaftOcclusion(bool bNewValue);"
hl_check "hero: SetOcclusionMaskDarkness" "$HLD" "ENGINE_API void SetOcclusionMaskDarkness(float NewValue);"
hl_check "hero: SetAtmosphereSunDiskColorScale" "$HLD" "ENGINE_API void SetAtmosphereSunDiskColorScale(FLinearColor NewValue);"
hl_check "hero: SetEnableLightShaftBloom" "$HLL" "ENGINE_API void SetEnableLightShaftBloom(bool bNewValue);"
hl_check "hero: SetBloomScale" "$HLL" "ENGINE_API void SetBloomScale(float NewValue);"
hl_check "hero: SetBloomThreshold" "$HLL" "ENGINE_API void SetBloomThreshold(float NewValue);"
hl_check "hero: SetBloomMaxBrightness" "$HLL" "ENGINE_API void SetBloomMaxBrightness(float NewValue);"
# round 5 shade probes (FlightSimHeroLighting.cpp sky-light block; the commandlet's sky_light_capture_result)
hl_check "hero: SkyLight GetProcessedSkyTexture" "$HLS" "const FTexture* GetProcessedSkyTexture() const"
hl_check "hero: SkyLight bCloudAmbientOcclusion" "$HLS" "uint32 bCloudAmbientOcclusion : 1;"
hl_check "hero: SkyLight MinOcclusion" "$HLS" "float MinOcclusion;"
hl_check "hero: SkyLight LightColor (FColor, sRGB 8-bit)" "$HLB" "FColor LightColor;"
hl_check "hero: SkyAtmosphere SetAerialPespectiveViewDistanceScale" "Engine/Classes/Components/SkyAtmosphereComponent.h" "ENGINE_API void SetAerialPespectiveViewDistanceScale(float NewValue);"
# 2026-11-11 #02: the stated fill tints the height fog's sky-atmosphere ambient (-stated-fill-fog=)
hl_check "hero: Fog SetSkyAtmosphereAmbientContributionColorScale" "Engine/Classes/Components/ExponentialHeightFogComponent.h" "ENGINE_API void SetSkyAtmosphereAmbientContributionColorScale(FLinearColor NewValue);"
hl_check "hero: Fog SkyAtmosphereAmbientContributionColorScale" "Engine/Classes/Components/ExponentialHeightFogComponent.h" "FLinearColor SkyAtmosphereAmbientContributionColorScale;"
hl_check "hero: SetVolumetricScatteringIntensity" "$HLL" "ENGINE_API void SetVolumetricScatteringIntensity(float NewIntensity);"
hl_check "hero: ContactShadowLength" "$HLL" "float ContactShadowLength;"
hl_check "hero: ContactShadowLengthInWS" "$HLL" "uint32 ContactShadowLengthInWS : 1;"
hl_check "hero: ContactShadowCastingIntensity" "$HLL" "float ContactShadowCastingIntensity;"
hl_check "hero: ContactShadowNonCastingIntensity" "$HLL" "float ContactShadowNonCastingIntensity;"
hl_check "hero: SetCastVolumetricShadow" "$HLB" "ENGINE_API void SetCastVolumetricShadow(bool bNewValue);"
hl_check "hero: SkyLight IsRealTimeCaptureEnabled" "$HLS" "ENGINE_API bool IsRealTimeCaptureEnabled() const;"
hl_check "hero: SkyLight SetLowerHemisphereColor" "$HLS" "ENGINE_API void SetLowerHemisphereColor(const FLinearColor& InLowerHemisphereColor);"
hl_check "hero: SkyLight SetCaptureIsDirty" "$HLS" "ENGINE_API void SetCaptureIsDirty();"
# round 3 stated fill (core/scene/hero_lighting.py stated_fill_tint)
hl_check "hero: SkyLight SetLightColor" "$HLS" "ENGINE_API void SetLightColor(FLinearColor NewLightColor);"
hl_check "hero: SkyLight bLowerHemisphereIsBlack" "$HLS" "bool bLowerHemisphereIsBlack;"
hl_check "hero: SkyLight LowerHemisphereColor" "$HLS" "FLinearColor LowerHemisphereColor;"
hl_check "hero: SkyLight bCloudAmbientOcclusion" "$HLS" "uint32 bCloudAmbientOcclusion : 1;"
hl_check "hero: SkyLight CloudAmbientOcclusionStrength" "$HLS" "float CloudAmbientOcclusionStrength;"
hl_check "hero: SkyAtmosphere MieAnisotropy" "Engine/Classes/Components/SkyAtmosphereComponent.h" "float MieAnisotropy;"
hl_check "hero: captured lower hemisphere colour" "Renderer/Private/ReflectionEnvironmentCapture.cpp" "PassParameters->LowerHemisphereColor = LowerHemisphereColor;"
# Why the sky light stays capture-once: a scene capture never runs the real-time capture.
hl_check "hero: no real-time sky capture in a scene capture" "Renderer/Private/ReflectionEnvironmentRealTimeCapture.cpp" "if (MainView.bIsSceneCapture || !MainView.Family->EngineShowFlags.Atmosphere)"
hl_check "hero: sun disc from the source angle" "Renderer/Private/SkyAtmosphereRendering.cpp" "GetAtmosphereSunDiskColorScale() * Light.Proxy->GetOuterSpaceIlluminance() / SunSolidAngle"
hl_check "hero: JSON TryGetObjectField" "Json/Public/Dom/JsonObject.h" "JSON_API bool TryGetObjectField(FStringView FieldName, const TSharedPtr<FJsonObject>*& OutObject) const;"
hl_check "hero: IsRayTracingEnabled" "RenderCore/Public/RenderUtils.h" "extern RENDERCORE_API bool IsRayTracingEnabled();"
hl_check "hero: show flag LightShafts" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(LightShafts,"
hl_check "hero: show flag ContactShadows" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(ContactShadows,"
hl_cvar() {  # cvar name, file (relative to $UE_ROOT/Engine/Source/Runtime)
    hl_check "hero: cvar $1" "$2" "\"$1\""
}
hl_cvar r.Shadow.Virtual.ResolutionLodBiasDirectional "Renderer/Private/VirtualShadowMaps/VirtualShadowMapClipmap.cpp"
hl_cvar r.Shadow.Virtual.MaxPhysicalPages "Renderer/Private/VirtualShadowMaps/VirtualShadowMapArray.cpp"
hl_cvar r.Shadow.Virtual.SMRT.RayCountDirectional "Renderer/Private/VirtualShadowMaps/VirtualShadowMapArray.cpp"
hl_cvar r.Shadow.Virtual.SMRT.SamplesPerRayDirectional "Renderer/Private/VirtualShadowMaps/VirtualShadowMapArray.cpp"
hl_cvar r.ContactShadows "Core/Private/HAL/ConsoleManager.cpp"
hl_cvar r.LightShaftQuality "Renderer/Private/LightShaftRendering.cpp"
hl_cvar r.VolumetricFog "Renderer/Private/VolumetricFog.cpp"
hl_cvar r.VolumetricFog.GridPixelSize "Renderer/Private/VolumetricFog.cpp"
hl_cvar r.VolumetricFog.GridSizeZ "Renderer/Private/VolumetricFog.cpp"
hl_cvar r.Lumen.ScreenProbeGather.ShortRangeAO "Renderer/Private/Lumen/LumenScreenProbeGather.cpp"
hl_cvar r.Lumen.ScreenProbeGather.ScreenTraces "Renderer/Private/Lumen/LumenScreenProbeTracing.cpp"
hl_cvar r.Lumen.ScreenProbeGather.ShortRangeAO.HardwareRayTracing "Renderer/Private/Lumen/LumenShortRangeAOHardwareRayTracing.cpp"
hl_cvar r.Lumen.Reflections.ScreenTraces "Renderer/Private/Lumen/LumenReflectionTracing.cpp"
hl_cvar r.Lumen.Reflections.MaxRoughnessToTrace "Renderer/Private/Lumen/LumenReflections.cpp"
hl_cvar r.Lumen.Reflections.DownsampleFactor "Renderer/Private/Lumen/LumenReflections.cpp"
hl_cvar r.Lumen.HardwareRayTracing "Renderer/Private/Lumen/LumenHardwareRayTracingCommon.cpp"
hl_cvar r.Lumen.HardwareRayTracing.LightingMode "Renderer/Private/Lumen/LumenHardwareRayTracingCommon.cpp"
hl_cvar r.Lumen.Reflections.HardwareRayTracing "Renderer/Private/Lumen/LumenReflectionHardwareRayTracing.cpp"
# ------------------------------------------------------ END hero lighting --

# -- supersample lane (visual overhaul, 2026-11-09): -supersample=N ---------
# FlightSimSupersample.cpp and its hooks in FlightSimRenderCommandlet.cpp.
# Each pattern is a fixed string read in the 5.7.4 source when written.
ss_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimSupersample.cpp needs updating"
    fi
}
ss_check "supersample: GMaxTextureDimensions" "RHI/Public/RHIGlobals.h" "#define GMaxTextureDimensions"
ss_check "supersample: RenderTarget InitAutoFormat" "Engine/Classes/Engine/TextureRenderTarget2D.h" "ENGINE_API void InitAutoFormat(uint32 InSizeX, uint32 InSizeY);"
ss_check "supersample: RTF_RGBA8_SRGB" "Engine/Classes/Engine/TextureRenderTarget2D.h" "RTF_RGBA8_SRGB,"
ss_check "supersample: SCS_FinalColorLDR" "Engine/Classes/Engine/EngineTypes.h" "SCS_FinalColorLDR UMETA"
ss_check "supersample: ReadPixels FColor" "Engine/Public/UnrealClient.h" "ENGINE_API virtual bool ReadPixels(TArray<FColor>& OutImageData"
ss_check "supersample: Json TryGetObjectField" "Json/Public/Dom/JsonObject.h" "JSON_API bool TryGetObjectField(FStringView FieldName, const TSharedPtr<FJsonObject>*& OutObject) const;"
ss_check "supersample: FParse::Value int32" "Core/Public/Misc/Parse.h" "static CORE_API bool Value( const TCHAR* Stream, const TCHAR* Match, int32& Value );"
ss_check "supersample: TArray SetNumUninitialized" "Core/Public/Containers/Array.h" "void SetNumUninitialized(SizeType NewNum"
# -- supersample lane end ---------------------------------------------------

# -- exposure-storm (visual overhaul round 2, 2026-11-09) ---- BEGIN exposure-storm --
# FlightSimBeautyLook.cpp's one exposure owner over the -sky= plan's camera,
# the exposure meter's GI-path detection, and the engine behaviour the
# breathing fix (FlightSimHeroLighting.cpp, light-shaft occlusion off) rests
# on. Each pattern is a fixed string grepped in the UE 5.7.4 source when written.
es_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the exposure-storm lane needs updating"
    fi
}
es_check "exposure: DoesPlatformSupportLumenGI" "RenderCore/Public/RenderUtils.h" "extern RENDERCORE_API bool DoesPlatformSupportLumenGI(EShaderPlatform Platform, bool bSkipProjectCheck = false);"
es_check "exposure: GMaxRHIShaderPlatform" "RHI/Public/RHIShaderPlatform.h" "extern RHI_API EShaderPlatform GMaxRHIShaderPlatform;"
es_check "exposure: LexToString(EShaderPlatform)" "RHI/Public/RHIStrings.h" "RHI_API FString LexToString(EShaderPlatform Platform, bool bError = true);"
es_check "exposure: Lumen.Supported.SM5 read" "RenderCore/Private/RenderUtils.cpp" "FindConsoleVariable(TEXT(\"r.Lumen.Supported.SM5\"))"
es_check "exposure: CameraShutterSpeed" "Engine/Classes/Engine/Scene.h" "float CameraShutterSpeed;"
es_check "exposure: CameraISO" "Engine/Classes/Engine/Scene.h" "float CameraISO;"
es_check "exposure: DepthOfFieldFstop" "Engine/Classes/Engine/Scene.h" "float DepthOfFieldFstop;"
es_check "exposure: AutoExposureBias" "Engine/Classes/Engine/Scene.h" "float AutoExposureBias;"
es_check "exposure: Json TryGetBoolField" "Json/Public/Dom/JsonObject.h" "JSON_API bool TryGetBoolField(FStringView FieldName, bool& OutBool) const;"
es_check "exposure: local exposure highlight default 1" "Engine/Private/Scene.cpp" "LocalExposureHighlightContrastScale = 1.0f;"
es_check "breathing: shafts run whenever the sun is ahead" "Renderer/Private/LightShaftRendering.cpp" "return GetLightScreenPosition(View, LightSceneProxy).W > 0.0f;"
es_check "breathing: fog reads the shaft occlusion" "Renderer/Private/FogRendering.cpp" "PassParameters->PS.OcclusionTexture = LightShaftOcclusionTexture"
# ------------------------------------------------------ END exposure-storm --


# -- aircraft-sharp (visual overhaul round 2, 2026-11-09) -- begin ----------
# FlightSimRenderCommandlet.cpp (RenderBeautyStartSceneFrame, the still's
# camera cut, render_settings.beauty_path.aircraft_sharp) and
# FlightSimBeautyLook.cpp (ApplyShutterPolicy). Fixed strings read in the
# 5.7.4 source when written; the engine BEHAVIOUR the fix rests on (only
# FEngineLoop::Tick calls FScene::StartFrame; only StartFrame rolls a
# primitive's PreviousLocalToWorld) is pinned by the last three.
as_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the aircraft-sharp hooks need re-reading"
    fi
}
as_check "sharp: FSceneInterface::StartFrame" "Engine/Public/SceneInterface.h" "virtual void StartFrame() {}"
as_check "sharp: UWorld::Scene" "Engine/Classes/Engine/World.h" "class FSceneInterface*						Scene;"
as_check "sharp: ENQUEUE_RENDER_COMMAND" "RenderCore/Public/RenderingThread.h" "#define ENQUEUE_RENDER_COMMAND(Type)"
as_check "sharp: bCameraCutThisFrame" "Engine/Classes/Components/SceneCaptureComponent2D.h" "uint32 bCameraCutThisFrame : 1;"
as_check "sharp: bAlwaysPersistRenderingState" "Engine/Classes/Components/SceneCaptureComponent.h" "bool bAlwaysPersistRenderingState;"
as_check "sharp: SupportsTSR" "RenderCore/Public/RenderUtils.h" "RENDERCORE_API bool SupportsTSR(const FStaticShaderPlatform Platform);"
as_check "sharp: GMaxRHIShaderPlatform" "RHI/Public/RHIShaderPlatform.h" "extern RHI_API EShaderPlatform GMaxRHIShaderPlatform;"
as_check "sharp: LexToString(EShaderPlatform)" "RHI/Public/RHIStrings.h" "RHI_API FString LexToString(EShaderPlatform Platform, bool bError = true);"
as_check "sharp: USceneComponent::Mobility" "Engine/Classes/Components/SceneComponent.h" "TEnumAsByte<EComponentMobility::Type> Mobility;"
as_check "sharp: MotionBlurAmount" "Engine/Classes/Engine/Scene.h" "float MotionBlurAmount;"
as_check "sharp: SetMotionBlur show flag" "Engine/Public/ShowFlagsValues.inl" "SHOWFLAG_ALWAYS_ACCESSIBLE(MotionBlur, SFG_PostProcess"
as_check "sharp: StartFrame rolls previous" "Renderer/Private/RendererScene.cpp" "VelocityData.PreviousLocalToWorld = VelocityData.LocalToWorld;"
as_check "sharp: UpdateTransform keeps previous" "Renderer/Private/ScenePrivate.h" "if (!VelocityData.bPreviousLocalToWorldValid)"
as_check "sharp: engine loop calls StartFrame" "Launch/Private/LaunchEngineLoop.cpp" "ENQUEUE_RENDER_COMMAND(FScene_StartFrame)"
# -- aircraft-sharp -- end ----------------------------------------------------


# -- cockpit-airframe (visual overhaul round 2, 2026-11-09) ------------------
# FlightSimAircraftFX.cpp: the beauty body swap (mesh manifest beauty_parts ->
# SetStaticMesh on a beauty render) and the slot count. Each pattern is a
# fixed string read in the 5.7.4 headers when written (uses ss_check above).
ss_check "cockpit-airframe: SMC SetStaticMesh" "Engine/Classes/Components/StaticMeshComponent.h" "ENGINE_API virtual bool SetStaticMesh(class UStaticMesh* NewMesh);"
ss_check "cockpit-airframe: SMC GetStaticMesh" "Engine/Classes/Components/StaticMeshComponent.h" "TObjectPtr<UStaticMesh> GetStaticMesh() const"
ss_check "cockpit-airframe: StaticMesh GetStaticMaterials" "Engine/Classes/Engine/StaticMesh.h" "const TArray<FStaticMaterial>& GetStaticMaterials() const"
ss_check "cockpit-airframe: FStaticMaterial MaterialSlotName" "Engine/Classes/Engine/StaticMesh.h" "FName MaterialSlotName;"
ss_check "cockpit-airframe: FJsonObject Values" "Json/Public/Dom/JsonObject.h" "TMap<FString, TSharedPtr<FJsonValue>> Values;"
ss_check "cockpit-airframe: FJsonValue AsObject" "Json/Public/Dom/JsonValue.h" "JSON_API virtual const TSharedPtr<FJsonObject>& AsObject() const;"
# ue_import_aircraft.py keep_normals (Python names of these UPROPERTYs):
ss_check "cockpit-airframe: MeshBuildSettings bRecomputeNormals" "Engine/Classes/Engine/EngineTypes.h" "uint8 bRecomputeNormals:1;"
ss_check "cockpit-airframe: StaticMesh StaticMaterials getter" "Engine/Classes/Engine/StaticMesh.h" "UPROPERTY(BlueprintGetter = GetStaticMaterials"
if [ -f "$UE_ROOT/Engine/Plugins/Interchange/Runtime/Source/Pipelines/Public/InterchangeGenericAssetsPipelineSharedSettings.h" ] \
   && grep -qF -- "bool bRecomputeNormals = true;" "$UE_ROOT/Engine/Plugins/Interchange/Runtime/Source/Pipelines/Public/InterchangeGenericAssetsPipelineSharedSettings.h"; then
    ok "cockpit-airframe: Interchange CommonMeshes bRecomputeNormals" "present"
else
    bad "cockpit-airframe: Interchange CommonMeshes bRecomputeNormals" "not found -- ue_import_aircraft.py keep_normals needs updating"
fi
# -- cockpit-airframe end ----------------------------------------------------

# -- beauty fallback (no-lumen-and-machine lane, 2026-11-09) -- BEGIN beauty fallback --
# FlightSimBeautyFallback.cpp: the beauty look when this process cannot run
# Lumen GI (the render laptop: D3D11 / PCD3D_SM5). Each symbol was grepped in
# the UE 5.7.4 headers and sources on the authoring Mac (which cannot
# compile); re-checked here before a build. Cvar names at their DEFINITION.
bf_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimBeautyFallback.cpp needs updating"
    fi
}
BFR="RenderCore/Public/RenderUtils.h"
BFS="Engine/Classes/Engine/Scene.h"
BFK="Engine/Classes/Components/SkyLightComponent.h"
BFD="Engine/Classes/Components/DirectionalLightComponent.h"
bf_check "fallback: DoesPlatformSupportLumenGI" "$BFR" "extern RENDERCORE_API bool DoesPlatformSupportLumenGI(EShaderPlatform Platform, bool bSkipProjectCheck = false);"
bf_check "fallback: DoesPlatformSupportVirtualShadowMaps" "$BFR" "RENDERCORE_API bool DoesPlatformSupportVirtualShadowMaps(EShaderPlatform Platform);"
bf_check "fallback: DoesPlatformSupportNanite" "$BFR" "RENDERCORE_API bool DoesPlatformSupportNanite(EShaderPlatform Platform, bool bCheckForProjectSetting = true);"
bf_check "fallback: IsRayTracingEnabled" "$BFR" "extern RENDERCORE_API bool IsRayTracingEnabled();"
bf_check "fallback: Lumen on SM5 only with r.Lumen.Supported.SM5" "RenderCore/Private/RenderUtils.cpp" "const bool bAllowSM5 = bLumenSupportedSM5 && IsFeatureLevelSupported(Platform, ERHIFeatureLevel::SM5);"
bf_check "fallback: VSM needs Nanite's platform" "RenderCore/Private/RenderUtils.cpp" "return DoesPlatformSupportNanite(Platform);"
bf_check "fallback: DoesPlatformSupportDistanceFields" "Engine/Public/SceneManagement.h" "ENGINE_API bool DoesPlatformSupportDistanceFields(const FStaticShaderPlatform Platform);"
bf_check "fallback: DoesProjectSupportDistanceFields" "Engine/Public/SceneManagement.h" "ENGINE_API bool DoesProjectSupportDistanceFields();"
bf_check "fallback: GMaxRHIFeatureLevel" "RHI/Public/RHIFeatureLevel.h" "extern RHI_API ERHIFeatureLevel::Type GMaxRHIFeatureLevel;"
bf_check "fallback: GMaxRHIShaderPlatform" "RHI/Public/RHIShaderPlatform.h" "extern RHI_API EShaderPlatform GMaxRHIShaderPlatform;"
bf_check "fallback: LexToString feature level" "RHI/Public/RHIStrings.h" "RHI_API FString LexToString(ERHIFeatureLevel::Type Level);"
bf_check "fallback: LexToString shader platform" "RHI/Public/RHIStrings.h" "RHI_API FString LexToString(EShaderPlatform Platform, bool bError = true);"
bf_check "fallback: PostProcess GI method override" "$BFS" "uint32 bOverride_DynamicGlobalIlluminationMethod : 1;"
bf_check "fallback: PostProcess GI method" "$BFS" "TEnumAsByte<EDynamicGlobalIlluminationMethod::Type> DynamicGlobalIlluminationMethod;"
bf_check "fallback: PostProcess reflection method override" "$BFS" "uint8 bOverride_ReflectionMethod:1;"
bf_check "fallback: PostProcess reflection method" "$BFS" "TEnumAsByte<EReflectionMethod::Type> ReflectionMethod;"
bf_check "fallback: PostProcess SSR quality override" "$BFS" "uint8 bOverride_ScreenSpaceReflectionQuality:1;"
bf_check "fallback: PostProcess SSR quality" "$BFS" "float ScreenSpaceReflectionQuality;"
bf_check "fallback: GI method ScreenSpace" "Engine/Classes/Engine/EngineTypes.h" "ScreenSpace UMETA(DisplayName=\"Screen Space (Beta)\"),"
bf_check "fallback: SSGI runs on the view's ScreenSpace method" "Renderer/Private/ScreenSpaceRayTracing.cpp" "if (View.FinalPostProcessSettings.DynamicGlobalIlluminationMethod != EDynamicGlobalIlluminationMethod::ScreenSpace)"
bf_check "fallback: SSGI when Lumen GI does not render" "Renderer/Private/IndirectLightRendering.cpp" "DiffuseIndirectMethod = EDiffuseIndirectMethod::SSGI;"
bf_check "fallback: SkyLight SetIntensity" "$BFK" "ENGINE_API void SetIntensity(float NewIntensity);"
bf_check "fallback: SkyLight SetMinOcclusion" "$BFK" "ENGINE_API void SetMinOcclusion(float InMinOcclusion);"
bf_check "fallback: SkyLight MinOcclusion" "$BFK" "float MinOcclusion;"
bf_check "fallback: SkyLight OcclusionMaxDistance" "$BFK" "float OcclusionMaxDistance;"
bf_check "fallback: SkyLight SetCaptureIsDirty" "$BFK" "ENGINE_API void SetCaptureIsDirty();"
bf_check "fallback: SkyLight IsRealTimeCaptureEnabled" "$BFK" "ENGINE_API bool IsRealTimeCaptureEnabled() const;"
bf_check "fallback: Light Intensity" "Engine/Classes/Components/LightComponentBase.h" "float Intensity;"
bf_check "fallback: Light CastShadows" "Engine/Classes/Components/LightComponentBase.h" "uint32 CastShadows:1;"
bf_check "fallback: Directional SetDynamicShadowCascades" "$BFD" "ENGINE_API void SetDynamicShadowCascades(int32 NewValue);"
bf_check "fallback: Directional SetCascadeDistributionExponent" "$BFD" "ENGINE_API void SetCascadeDistributionExponent(float NewValue);"
bf_check "fallback: Directional DynamicShadowCascades" "$BFD" "int32 DynamicShadowCascades;"
bf_check "fallback: Directional CascadeDistributionExponent" "$BFD" "float CascadeDistributionExponent;"
bf_check "fallback: Directional DynamicShadowDistanceMovableLight" "$BFD" "float DynamicShadowDistanceMovableLight;"
bf_cvar() {  # cvar name, file (relative to $UE_ROOT/Engine/Source/Runtime)
    bf_check "fallback: cvar $1" "$2" "TEXT(\"$1\"),"
}
bf_cvar r.SSGI.Quality "Renderer/Private/ScreenSpaceRayTracing.cpp"
bf_cvar r.SSR.Quality "Renderer/Private/ScreenSpaceRayTracing.cpp"
bf_cvar r.DistanceFieldAO "Renderer/Private/DistanceFieldAmbientOcclusion.cpp"
bf_cvar r.AOQuality "Renderer/Private/DistanceFieldAmbientOcclusion.cpp"
bf_cvar r.Shadow.CSM.MaxCascades "Renderer/Private/SceneRendering.cpp"
bf_cvar r.Shadow.MaxCSMResolution "Core/Private/HAL/ConsoleManager.cpp"
bf_cvar r.Shadow.MaxResolution "Core/Private/HAL/ConsoleManager.cpp"
bf_cvar r.Lumen.Supported.SM5 "Renderer/Private/Lumen/Lumen.cpp"
# ------------------------------------------------------ END beauty fallback --

# -- round-5 engine look (lane L1, 2026-11-10) -- BEGIN engine look --
# FlightSimBeautyLook.cpp ApplyEngineLook: the renderer's built-in lighting and
# post effects per world preset (core/scene/beauty_look.py ENGINE_LOOK). Each
# post-process member and its bOverride_ was read in Scene.h, each light / fog
# member and setter in its component header, each cvar at its definition, and
# the engine-default kernel and grain textures in SceneRendering.cpp, on the
# authoring Mac (no compile there); re-checked here before a build is spent.
el_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimBeautyLook.cpp (engine look) needs updating"
    fi
}
ELS="Engine/Classes/Engine/Scene.h"
ELD="Engine/Classes/Components/DirectionalLightComponent.h"
ELL="Engine/Classes/Components/LightComponent.h"
ELF="Engine/Classes/Components/ExponentialHeightFogComponent.h"
for p in IndirectLightingIntensity AmbientOcclusionIntensity AmbientOcclusionRadius \
         AmbientOcclusionQuality AmbientOcclusionPower AmbientOcclusionStaticFraction \
         AmbientOcclusionMipBlend AmbientOcclusionTemporalBlendWeight AmbientOcclusionRadiusInWS \
         BloomSizeScale BloomConvolutionSize BloomConvolutionScatterDispersion \
         BloomConvolutionPreFilterMin BloomConvolutionPreFilterMax BloomConvolutionPreFilterMult \
         BloomConvolutionBufferScale LensFlareBokehSize FilmGrainIntensity \
         FilmGrainIntensityShadows FilmGrainIntensityMidtones FilmGrainIntensityHighlights \
         FilmGrainShadowsMax FilmGrainHighlightsMin FilmGrainHighlightsMax FilmGrainTexelSize \
         DepthOfFieldSqueezeFactor ScreenSpaceReflectionIntensity ScreenSpaceReflectionQuality \
         ScreenSpaceReflectionMaxRoughness; do
    el_check "engine look: PostProcess $p" "$ELS" "bOverride_$p"
done
el_check "engine look: EBloomMethod BM_FFT" "$ELS" "BM_FFT"
el_check "engine look: AmbientOcclusionRadiusInWS is a bit" "$ELS" "uint32 AmbientOcclusionRadiusInWS:1;"
el_check "engine look: GI method None" "Engine/Classes/Engine/EngineTypes.h" "namespace EDynamicGlobalIlluminationMethod"
el_check "engine look: reflection method None" "Engine/Classes/Engine/EngineTypes.h" "namespace EReflectionMethod"
el_check "engine look: Directional SetDynamicShadowDistanceMovableLight" "$ELD" "ENGINE_API void SetDynamicShadowDistanceMovableLight(float NewValue);"
el_check "engine look: Directional SetShadowDistanceFadeoutFraction" "$ELD" "ENGINE_API void SetShadowDistanceFadeoutFraction(float NewValue);"
el_check "engine look: Directional SetCascadeTransitionFraction" "$ELD" "ENGINE_API void SetCascadeTransitionFraction(float NewValue);"
el_check "engine look: Directional ShadowDistanceFadeoutFraction" "$ELD" "float ShadowDistanceFadeoutFraction;"
el_check "engine look: Directional CascadeTransitionFraction" "$ELD" "float CascadeTransitionFraction;"
el_check "engine look: Directional DistanceFieldShadowDistance" "$ELD" "float DistanceFieldShadowDistance;"
el_check "engine look: Directional LightSourceAngle" "$ELD" "float LightSourceAngle;"
el_check "engine look: Light bUseRayTracedDistanceFieldShadows" "$ELL" "bool bUseRayTracedDistanceFieldShadows;"
el_check "engine look: Light SetUseRayTracedDistanceFieldShadows" "$ELL" "ENGINE_API void SetUseRayTracedDistanceFieldShadows(bool bNewValue);"
el_check "engine look: Light ContactShadowLength" "$ELL" "float ContactShadowLength;"
el_check "engine look: Light ContactShadowLengthInWS" "$ELL" "uint32 ContactShadowLengthInWS : 1;"
el_check "engine look: Light ContactShadowCastingIntensity" "$ELL" "float ContactShadowCastingIntensity;"
el_check "engine look: Light ContactShadowNonCastingIntensity" "$ELL" "float ContactShadowNonCastingIntensity;"
el_check "engine look: Light GetDirection" "$ELL" "ENGINE_API FVector GetDirection() const;"
el_check "engine look: Light VolumetricScatteringIntensity" "Engine/Classes/Components/LightComponentBase.h" "float VolumetricScatteringIntensity;"
el_check "engine look: Fog SetVolumetricFogAlbedo" "$ELF" "ENGINE_API void SetVolumetricFogAlbedo(FColor NewValue);"
el_check "engine look: Fog VolumetricFogAlbedo" "$ELF" "FColor VolumetricFogAlbedo;"
el_check "engine look: Fog VolumetricFogScatteringDistribution" "$ELF" "float VolumetricFogScatteringDistribution;"
el_check "engine look: Fog VolumetricFogExtinctionScale" "$ELF" "float VolumetricFogExtinctionScale;"
el_check "engine look: Fog VolumetricFogDistance" "$ELF" "float VolumetricFogDistance;"
el_check "engine look: Fog bEnableVolumetricFog" "$ELF" "bool bEnableVolumetricFog;"
el_check "engine look: SceneComponent GetForwardVector" "Engine/Classes/Components/SceneComponent.h" "ENGINE_API FVector GetForwardVector() const;"
el_check "engine look: SceneCapture2D TextureTarget" "Engine/Classes/Components/SceneCaptureComponent2D.h" "TObjectPtr<class UTextureRenderTarget2D> TextureTarget;"
el_check "engine look: RenderTarget2D SizeX" "Engine/Classes/Engine/TextureRenderTarget2D.h" "int32 SizeX;"
el_check "engine look: ObjectIterator" "CoreUObject/Public/UObject/UObjectIterator.h" "class TObjectIterator"
# The premises: film grain and FFT bloom fall back to the engine's own textures
# when the post-process texture is null, and SSAO runs on intensity > 0.
el_check "engine look: premise default grain texture" "Renderer/Private/SceneRendering.cpp" "FilmGrainTexture = GEngine->DefaultFilmGrainTexture;"
el_check "engine look: premise default bloom kernel" "Renderer/Private/SceneRendering.cpp" "BloomConvolutionTexture = GEngine->DefaultBloomKernelTexture;"
el_check "engine look: premise SSAO on intensity" "Renderer/Private/CompositionLighting/CompositionLighting.cpp" "View.FinalPostProcessSettings.AmbientOcclusionIntensity > 0"
el_check "engine look: premise PCSS is FilterMethod 1" "Renderer/Private/ShadowRendering.cpp" "TEXT(\" 1: PCSS (experimental)\\n\"),"
el_cvar() {  # cvar name, file (relative to $UE_ROOT/Engine/Source/Runtime)
    el_check "engine look: cvar $1" "$2" "TEXT(\"$1\"),"
}
el_cvar r.SSGI.Quality "Renderer/Private/ScreenSpaceRayTracing.cpp"
el_cvar r.SSR.Quality "Renderer/Private/ScreenSpaceRayTracing.cpp"
el_cvar r.SSR.HalfResSceneColor "Renderer/Private/ScreenSpaceRayTracing.cpp"
el_cvar r.AmbientOcclusionMaxQuality "Renderer/Private/CompositionLighting/PostProcessAmbientOcclusion.cpp"
el_cvar r.AmbientOcclusionLevels "Renderer/Private/CompositionLighting/PostProcessAmbientOcclusion.cpp"
el_cvar r.Shadow.MaxResolution "Core/Private/HAL/ConsoleManager.cpp"
el_cvar r.Shadow.MaxCSMResolution "Core/Private/HAL/ConsoleManager.cpp"
el_cvar r.Shadow.CSM.MaxCascades "Renderer/Private/SceneRendering.cpp"
el_cvar r.Shadow.FilterMethod "Renderer/Private/ShadowRendering.cpp"
el_cvar r.Shadow.MaxSoftKernelSize "Renderer/Private/ShadowRendering.cpp"
el_cvar r.DistanceFieldShadowing "Renderer/Private/DistanceFieldShadowing.cpp"
el_cvar r.ContactShadows "Core/Private/HAL/ConsoleManager.cpp"
el_cvar r.LensFlareQuality "Renderer/Private/PostProcess/PostProcessLensFlares.cpp"
el_cvar r.FilmGrain "Renderer/Private/SceneRendering.cpp"
el_cvar r.VolumetricFog "Renderer/Private/VolumetricFog.cpp"
el_cvar r.VolumetricFog.GridPixelSize "Renderer/Private/VolumetricFog.cpp"
el_cvar r.VolumetricFog.GridSizeZ "Renderer/Private/VolumetricFog.cpp"
el_cvar r.TSR.History.ScreenPercentage "Renderer/Private/PostProcess/TemporalSuperResolution.cpp"
el_cvar r.TSR.History.SampleCount "Renderer/Private/PostProcess/TemporalSuperResolution.cpp"
for f in ScreenSpaceAO AmbientOcclusion RayTracedDistanceFieldShadows ContactShadows LensFlares Grain Bloom; do
    if grep -qE -- "$(showflag_pattern "$f")" "$UE_ROOT/Engine/Source/Runtime/Engine/Public/ShowFlagsValues.inl" 2>/dev/null; then
        ok "engine look: show flag $f" "present"
    else
        bad "engine look: show flag $f" "not found in ShowFlagsValues.inl"
    fi
done
# ------------------------------------------------------ END engine look --

# -- round-2b weather-fx (2026-11-09) -- BEGIN weather-fx --
# FlightSimAircraftFX.cpp (the lamps' volumetric scattering and source radius),
# FlightSimWeatherLook.cpp (ApplyBeautyWeatherLook: the shafts' parameters and the
# funnel's material) and FlightSimWeather.cpp (the beauty rain shape's parameters).
# Each symbol grepped in the UE 5.7.4 headers on the authoring Mac (no compile there).
wfx_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the round-2b weather-fx code needs updating"
    fi
}
wfx_check "weather-fx: Light SetVolumetricScatteringIntensity" "Engine/Classes/Components/LightComponent.h" "ENGINE_API void SetVolumetricScatteringIntensity(float NewIntensity);"
wfx_check "weather-fx: PointLight SetSourceRadius" "Engine/Classes/Components/PointLightComponent.h" "ENGINE_API void SetSourceRadius(float bNewValue);"
wfx_check "weather-fx: SpotLight is a PointLight" "Engine/Classes/Components/SpotLightComponent.h" "class USpotLightComponent : public UPointLightComponent"
wfx_check "weather-fx: TObjectIterator" "CoreUObject/Public/UObject/UObjectIterator.h" "template< class T > class TObjectIterator"
wfx_check "weather-fx: MeshComponent SetMaterial" "Engine/Classes/Components/MeshComponent.h" "ENGINE_API virtual void SetMaterial(int32 ElementIndex, UMaterialInterface* Material) override;"
wfx_check "weather-fx: MID SetScalarParameterValue" "Engine/Public/Materials/MaterialInstanceDynamic.h" "ENGINE_API void SetScalarParameterValue(FName ParameterName, float Value);"
wfx_check "weather-fx: MID SetVectorParameterValue" "Engine/Public/Materials/MaterialInstanceDynamic.h" "ENGINE_API void SetVectorParameterValue(FName ParameterName, FLinearColor Value);"
wfx_check "weather-fx: CameraVectorWS expression (M_RainShaft)" "Engine/Public/Materials/MaterialExpressionCameraVectorWS.h" "class UMaterialExpressionCameraVectorWS"
# ------------------------------------------------------ END weather-fx --

# -- visual round 6 (2026-11-10) -- BEGIN round6 --
# FlightSimScenarioWorld.cpp (the wall cloud actor's own spin), FlightSimClouds.cpp
# (the deck's cloud shadow on the sun, the -deck-shadow= switch) and
# scripts/ue_create_materials.py (M_TornadoFunnel generation 2: local-space,
# time-scrolled streaks). tests/test_visual_round6.py pins this block.
wfx_check "round6: Actor SetActorRotation" "Engine/Classes/GameFramework/Actor.h" "ENGINE_API bool SetActorRotation(FRotator NewRotation, ETeleportType Teleport = ETeleportType::None);"
wfx_check "round6: DirectionalLight bCastCloudShadows" "Engine/Classes/Components/DirectionalLightComponent.h" "uint32 bCastCloudShadows : 1;"
wfx_check "round6: GetEnvironmentVariable (-deck-shadow= via FLIGHTSIM_RENDER_SWITCHES)" "Core/Public/GenericPlatform/GenericPlatformMisc.h" "static CORE_API FString GetEnvironmentVariable(const TCHAR* VariableName);"
wfx_check "round6: TransformPosition expression (M_TornadoFunnel)" "Engine/Public/Materials/MaterialExpressionTransformPosition.h" "class UMaterialExpressionTransformPosition"
wfx_check "round6: TransformPosition world source" "Engine/Public/Materials/MaterialExpressionTransformPosition.h" "TRANSFORMPOSSOURCE_World"
wfx_check "round6: Time expression (M_TornadoFunnel)" "Engine/Public/Materials/MaterialExpressionTime.h" "class UMaterialExpressionTime"
# ------------------------------------------------------ END round6 --


# -- round-2b terrain-ocean (2026-11-09) -------------- BEGIN terrain-ocean --
# FlightSimGoogleTiles.cpp ApplyBeautyGround (beauty only: the haze the ground
# is read through, the open sea's cap) and the commandlet's camera-frame check.
# Each fixed string was grepped in the UE 5.7.4 headers/sources on the Mac.
to_check() {  # label, file (relative to $UE_ROOT/Engine), fixed-string pattern
    local f="$UE_ROOT/Engine/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- FlightSimGoogleTiles.cpp ApplyBeautyGround needs updating"
    fi
}
to_check "terrain-ocean: fog FogDensity" "Source/Runtime/Engine/Classes/Components/ExponentialHeightFogComponent.h" "float FogDensity;"
to_check "terrain-ocean: fog FogHeightFalloff" "Source/Runtime/Engine/Classes/Components/ExponentialHeightFogComponent.h" "float FogHeightFalloff;"
to_check "terrain-ocean: fog SecondFogData" "Source/Runtime/Engine/Classes/Components/ExponentialHeightFogComponent.h" "FExponentialHeightFogData SecondFogData;"
to_check "terrain-ocean: fog SetFogDensity" "Source/Runtime/Engine/Classes/Components/ExponentialHeightFogComponent.h" "ENGINE_API void SetFogDensity(float Value);"
to_check "terrain-ocean: fog SetSecondFogDensity" "Source/Runtime/Engine/Classes/Components/ExponentialHeightFogComponent.h" "ENGINE_API void SetSecondFogDensity(float Value);"
to_check "terrain-ocean: second fog FogHeightOffset" "Source/Runtime/Engine/Public/Rendering/ExponentialHeightFogData.h" "float FogHeightOffset = 0.0f;"
to_check "terrain-ocean: fog falloff per cm / 1000" "Source/Runtime/Renderer/Private/SceneCore.cpp" "FogData[0].HeightFalloff = State.FogHeightFalloff / 1000.0f;"
to_check "terrain-ocean: fog density exp2" "Shaders/Private/HeightFogCommon.ush" "exp2(-Exponent)"
to_check "terrain-ocean: Mie MieScatteringScale" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "float MieScatteringScale;"
to_check "terrain-ocean: Mie MieScattering" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "FLinearColor MieScattering;"
to_check "terrain-ocean: Mie MieAbsorptionScale" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "float MieAbsorptionScale;"
to_check "terrain-ocean: Mie MieAbsorption" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "FLinearColor MieAbsorption;"
to_check "terrain-ocean: Mie MieExponentialDistribution" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "float MieExponentialDistribution;"
to_check "terrain-ocean: SetMieScatteringScale" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "ENGINE_API void SetMieScatteringScale(float NewValue);"
to_check "terrain-ocean: SetMieAbsorptionScale" "Source/Runtime/Engine/Classes/Components/SkyAtmosphereComponent.h" "ENGINE_API void SetMieAbsorptionScale(float NewValue);"
to_check "terrain-ocean: SceneComponent IsVisible" "Source/Runtime/Engine/Classes/Components/SceneComponent.h" "ENGINE_API virtual bool IsVisible() const;"
to_check "terrain-ocean: SetCastShadow" "Source/Runtime/Engine/Classes/Components/PrimitiveComponent.h" "ENGINE_API void SetCastShadow(bool NewCastShadow);"
to_check "terrain-ocean: MID Create" "Source/Runtime/Engine/Public/Materials/MaterialInstanceDynamic.h" "static ENGINE_API UMaterialInstanceDynamic* Create( class UMaterialInterface* ParentMaterial, class UObject* InOuter, FName Name = NAME_None);"
to_check "terrain-ocean: TObjectIterator header" "Source/Runtime/CoreUObject/Public/UObject/UObjectIterator.h" "class TObjectIterator"
to_check "terrain-ocean: ProcMesh CreateMeshSection_LinearColor" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "void CreateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<int32>& Triangles, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FLinearColor>& VertexColors, const TArray<FProcMeshTangent>& Tangents, bool bCreateCollision"
to_check "terrain-ocean: FProcMeshTangent ctor" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "FProcMeshTangent(FVector InTangentX, bool bInFlipTangentY)"
to_check "terrain-ocean: GeoRef ProjectedToEngine" "Plugins/Runtime/GeoReferencing/Source/GeoReferencing/Public/GeoReferencingSystem.h" "void ProjectedToEngine(const FVector& ProjectedCoordinates, FVector& EngineCoordinates);"
to_check "terrain-ocean: GeoRef default ProjectedCRS 32631" "Plugins/Runtime/GeoReferencing/Source/GeoReferencing/Public/GeoReferencingSystem.h" "FString ProjectedCRS = FString(TEXT(\"EPSG:32631\"));"
# ---------------------------------------------------- END terrain-ocean --


# -- presets-colour (visual overhaul round 2b, 2026-11-09) -- BEGIN presets-colour --
# FlightSimBeautyLook.cpp's tonemap hue guard (core/scene/beauty_look.py
# TONEMAP_HUE): FPostProcessSettings::BlueCorrection, and the combine-LUT pass
# that applies it on every RHI. Fixed strings grepped in the UE 5.7.4 source.
pc_check() {  # label, file (relative to $UE_ROOT/Engine), fixed-string pattern
    local f="$UE_ROOT/Engine/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the presets-colour lane needs updating"
    fi
}
pc_check "colour: BlueCorrection" "Source/Runtime/Engine/Classes/Engine/Scene.h" "float BlueCorrection;"
pc_check "colour: bOverride_BlueCorrection" "Source/Runtime/Engine/Classes/Engine/Scene.h" "uint8 bOverride_BlueCorrection : 1;"
pc_check "colour: BlueCorrection's purpose" "Source/Runtime/Engine/Classes/Engine/Scene.h" "Bright blue desaturates instead of going to violet."
pc_check "colour: BlueCorrection default 0.6" "Source/Runtime/Engine/Private/Scene.cpp" "BlueCorrection = 0.6f;"
pc_check "colour: blue correct around the tone curve" "Shaders/Private/PostProcessCombineLUTs.usf" "ColorAP1 = lerp( ColorAP1, mul( BlueCorrectAP1, ColorAP1 ), BlueCorrection );"
pc_check "colour: blue correct undone after it" "Shaders/Private/PostProcessCombineLUTs.usf" "ColorAP1 = lerp( ColorAP1, mul( BlueCorrectInvAP1, ColorAP1 ), BlueCorrection );"
# ------------------------------------------------------ END presets-colour --

# -- round-1b hang (constrained GPU, 2026-11-10) ------ BEGIN constrained gpu --
# FlightSimRenderCommandlet.cpp RenderDrainGpu / RenderDeviceRemovedNote, the
# sky-capture restore (FlightSimBeautyFallback.cpp SuspendForSkyCapture,
# FlightSimGoogleTiles.cpp SuspendBeautyHaze) and the reasoning they rest on.
# Fixed strings grepped in the UE 5.7.4 source on the authoring Mac.
cg_check() {  # label, file (relative to $UE_ROOT/Engine/Source/Runtime), fixed-string pattern
    local f="$UE_ROOT/Engine/Source/Runtime/$2"
    if [ ! -f "$f" ]; then
        bad "$1" "file $2 not found in $UE_ROOT"
    elif grep -qF -- "$3" "$f"; then
        ok "$1" "present"
    else
        bad "$1" "not found in $2 -- the constrained-gpu safeguards need updating"
    fi
}
cg_check "constrained: RHIGetInterfaceType" "RHI/Public/DynamicRHI.h" "inline ERHIInterfaceType RHIGetInterfaceType()"
cg_check "constrained: RHIGetNativeDevice" "RHI/Public/DynamicRHI.h" "virtual void* RHIGetNativeDevice() = 0;"
cg_check "constrained: ERHIInterfaceType::D3D11" "RHI/Public/RHIDefinitions.h" "	D3D11,"
cg_check "constrained: D3D11 native device is the ID3D11Device" "Windows/D3D11RHI/Private/D3D11Device.cpp" "void* FD3D11DynamicRHI::RHIGetNativeDevice()"
cg_check "constrained: the unbounded GPU-idle poll" "Windows/D3D11RHI/Private/D3D11Commands.cpp" "void FD3D11DynamicRHI::RHIBlockUntilGPUIdle()"
cg_check "constrained: cube faces flush the GPU" "Renderer/Private/ReflectionEnvironmentCapture.cpp" "InRHICmdList.SubmitCommandsAndFlushGPU();"
cg_check "constrained: cube capture has no light shafts" "Renderer/Private/ReflectionEnvironmentCapture.cpp" "ViewFamily.EngineShowFlags.LightShafts = 0;"
cg_check "constrained: GetEnvironmentVariable" "Core/Public/GenericPlatform/GenericPlatformMisc.h" "static CORE_API FString GetEnvironmentVariable(const TCHAR* VariableName);"
cg_check "constrained: SetSecondFogDensity" "Engine/Classes/Components/ExponentialHeightFogComponent.h" "ENGINE_API void SetSecondFogDensity(float Value);"
cg_check "constrained: SetMieAbsorptionScale" "Engine/Classes/Components/SkyAtmosphereComponent.h" "ENGINE_API void SetMieAbsorptionScale(float NewValue);"
cg_check "constrained: float VolumetricScatteringIntensity;" "Engine/Classes/Components/LightComponentBase.h" "float VolumetricScatteringIntensity;"
# ---------------------------------------------------- END constrained gpu --

# -- lane A (2026-11-11) -- BEGIN lane A --
# FlightSimHeroLighting.cpp (-sky-cloud-ao=auto) and FlightSimRenderCommandlet.cpp
# (the subject meter: the aircraft's static meshes projected, hidden for one
# capture). tests/test_lane_a_aircraft_light.py pins the C++ side.
wfx_check "lane A: SkyLight bCloudAmbientOcclusion" "Engine/Classes/Components/SkyLightComponent.h" "uint32 bCloudAmbientOcclusion : 1;"
wfx_check "lane A: TInlineComponentArray(const AActor*)" "Engine/Classes/GameFramework/Actor.h" "TInlineComponentArray(const AActor* Actor, bool bIncludeFromChildActors = false);"
wfx_check "lane A: SceneComponent Bounds" "Engine/Classes/Components/SceneComponent.h" "FBoxSphereBounds Bounds;"
wfx_check "lane A: SceneComponent IsVisible" "Engine/Classes/Components/SceneComponent.h" "ENGINE_API virtual bool IsVisible() const;"
wfx_check "lane A: SceneCapture HiddenActors" "Engine/Classes/Components/SceneCaptureComponent.h" "TArray<TObjectPtr<AActor>> HiddenActors;"
wfx_check "lane A: FBox2D(EForceInit)" "Core/Public/Math/Box2D.h" "explicit TBox2<T>( EForceInit )"
wfx_check "lane A: FBox2D += point" "Core/Public/Math/Box2D.h" "inline TBox2<T>& operator+=( const TVector2<T> &Other );"
wfx_check "lane A: FBox2D bIsValid" "Core/Public/Math/Box2D.h" "bool bIsValid;"
wfx_check "lane A: BoxSphereBounds GetBox" "Core/Public/Math/BoxSphereBounds.h" "TBox<T> GetBox() const"
wfx_check "lane A: CeilToInt32(double)" "Core/Public/GenericPlatform/GenericPlatformMath.h" "static inline int32 CeilToInt32(double F)"
# ------------------------------------------------------------ END lane A --

# -- round 23 (2026-11-11) -- BEGIN aircraft probes --
# FlightSimAircraftFX.cpp -aircraft-probe= (the look masters' bisect).
wfx_check "probes: FParse::Value(FString, bShouldStopOnSeparator)" "Core/Public/Misc/Parse.h" "static CORE_API bool Value( const TCHAR* Stream, const TCHAR* Match, FString& Value, bool bShouldStopOnSeparator =true, const TCHAR** OptStreamGotTo = nullptr);"
wfx_check "probes: MaterialInterface GetBaseMaterial" "Engine/Public/Materials/MaterialInterface.h" "ENGINE_API UMaterial* GetBaseMaterial();"
wfx_check "probes: GetScalarParameterValue" "Engine/Public/Materials/MaterialInterface.h" "ENGINE_API bool GetScalarParameterValue(const FHashedMaterialParameterInfo& ParameterInfo, float& OutValue, bool bOveriddenOnly = false) const;"
wfx_check "probes: GetVectorParameterValue" "Engine/Public/Materials/MaterialInterface.h" "ENGINE_API bool GetVectorParameterValue(const FHashedMaterialParameterInfo& ParameterInfo, FLinearColor& OutValue, bool bOveriddenOnly = false) const;"
wfx_check "probes: GetTextureParameterValue" "Engine/Public/Materials/MaterialInterface.h" "ENGINE_API virtual bool GetTextureParameterValue(const FHashedMaterialParameterInfo& ParameterInfo, class UTexture*& OutValue, bool bOveriddenOnly = false) const;"
wfx_check "probes: FHashedMaterialParameterInfo(FName)" "Engine/Public/Materials/MaterialParameters.h" "FMemoryImageMaterialParameterInfo(const FName& InName, EMaterialParameterAssociation InAssociation = EMaterialParameterAssociation::GlobalParameter, int32 InIndex = INDEX_NONE)"
wfx_check "probes: MID SetTextureParameterValue" "Engine/Public/Materials/MaterialInstanceDynamic.h" "ENGINE_API void SetTextureParameterValue(FName ParameterName, class UTexture* Value);"
wfx_check "probes r24: MID CopyParameterOverrides" "Engine/Public/Materials/MaterialInstanceDynamic.h" "ENGINE_API void CopyParameterOverrides(UMaterialInstance* MaterialInstance);"
# round 25: the class masters' compile check (AircraftFxCompileProblem) and its fallback.
wfx_check "masters r25: Material GetMaterialResource(EShaderPlatform)" "Engine/Public/Materials/Material.h" "ENGINE_API virtual FMaterialResource* GetMaterialResource(EShaderPlatform InShaderPlatform, EMaterialQualityLevel::Type QualityLevel = EMaterialQualityLevel::Num) override;"
wfx_check "masters r25: MaterialInterface GetMaterial" "Engine/Public/Materials/MaterialInterface.h" "virtual class UMaterial* GetMaterial() PURE_VIRTUAL(UMaterialInterface::GetMaterial,return NULL;);"
wfx_check "masters r25: FMaterial FinishCompilation" "Engine/Public/MaterialShared.h" "ENGINE_API void FinishCompilation();"
wfx_check "masters r25: FMaterial GetCompileErrors" "Engine/Public/MaterialShared.h" "const TArray<FString>& GetCompileErrors() const { return CompileErrors; }"
wfx_check "masters r25: FMaterial GetGameThreadShaderMap" "Engine/Public/MaterialShared.h" "class FMaterialShaderMap* GetGameThreadShaderMap() const"
wfx_check "masters r25: GShaderPlatformForFeatureLevel" "RHI/Public/RHIGlobals.h" "#define GShaderPlatformForFeatureLevel"
wfx_check "panel r25: StaticMesh GetStaticMaterials" "Engine/Classes/Engine/StaticMesh.h" "const TArray<FStaticMaterial>& GetStaticMaterials() const"
# ---------------------------------------------------- END aircraft probes --


# -- visual push lane C (2026-11-11) -- BEGIN tornado-beauty --
# FlightSimTornadoBeauty.cpp (the beauty's funnel, wall cloud and puffs) and
# scripts/ue_create_materials.py (M_TornadoFunnel generation 3, M_TornadoPuff).
# tests/test_tornado_look.py pins this block.
to_check "tornado-beauty: ProceduralMesh ClearAllMeshSections" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "UE_API void ClearAllMeshSections();"
to_check "tornado-beauty: ProceduralMesh CreateMeshSection_LinearColor" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "void CreateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<int32>& Triangles, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FLinearColor>& VertexColors, const TArray<FProcMeshTangent>& Tangents, bool bCreateCollision, bool bSRGBConversion = false)"
to_check "tornado-beauty: MaterialBillboard AddElement" "Source/Runtime/Engine/Classes/Components/MaterialBillboardComponent.h" "ENGINE_API void AddElement("
to_check "tornado-beauty: SceneComponent SetupAttachment" "Source/Runtime/Engine/Classes/Components/SceneComponent.h" "ENGINE_API void SetupAttachment(USceneComponent* InParent, FName InSocketName = NAME_None);"
to_check "tornado-beauty: MID Create" "Source/Runtime/Engine/Public/Materials/MaterialInstanceDynamic.h" "static ENGINE_API UMaterialInstanceDynamic* Create( class UMaterialInterface* ParentMaterial, class UObject* InOuter, FName Name = NAME_None);"
to_check "tornado-beauty: RandomStream FRandRange" "Source/Runtime/Core/Public/Math/RandomStream.h" "FRandRange( FVector::FReal InMin, FVector::FReal InMax ) const"
to_check "tornado-beauty: Material OpacityMaskClipValue" "Source/Runtime/Engine/Public/Materials/Material.h" "float OpacityMaskClipValue;"
to_check "tornado-beauty: Material TranslucencyLightingMode" "Source/Runtime/Engine/Public/Materials/Material.h" "TEnumAsByte<ETranslucencyLightingMode> TranslucencyLightingMode;"
to_check "tornado-beauty: TLM_SurfacePerPixelLighting" "Source/Runtime/Engine/Classes/Engine/EngineTypes.h" "TLM_SurfacePerPixelLighting"
to_check "tornado-beauty: VertexNormalWS expression" "Source/Runtime/Engine/Public/Materials/MaterialExpressionVertexNormalWS.h" "class UMaterialExpressionVertexNormalWS"
to_check "tornado-beauty: CameraVectorWS expression" "Source/Runtime/Engine/Public/Materials/MaterialExpressionCameraVectorWS.h" "class UMaterialExpressionCameraVectorWS"
to_check "tornado-beauty: DepthFade expression" "Source/Runtime/Engine/Public/Materials/MaterialExpressionDepthFade.h" "class UMaterialExpressionDepthFade"
to_check "tornado-beauty: MID SetVectorParameterValue" "Source/Runtime/Engine/Public/Materials/MaterialInstanceDynamic.h" "ENGINE_API void SetVectorParameterValue(FName ParameterName, FLinearColor Value);"
to_check "tornado-beauty: CeilToDouble (the dust whirl)" "Source/Runtime/Core/Public/Math/UnrealMathUtility.h" "CeilToDouble"
# ---------------------------------------------- END tornado-beauty --

# -- plugin dependencies must be enabled in the uproject --------------------
PYBIN=$(pick_python) || { bad "python" "no working python (.venv, python3, python)"; PYBIN=false; }
MISSING=$("$PYBIN" - <<'PY'
import json
plugin = json.load(open("ue/Plugins/JSBSimFlightDynamicsModel/JSBSimFlightDynamicsModel.uplugin"))
project = json.load(open("ue/FlightSim.uproject"))
enabled = {p["Name"] for p in project.get("Plugins", []) if p.get("Enabled", True)}
required = {p["Name"] for p in plugin.get("Plugins", [])}
print(",".join(sorted(required - enabled)))
PY
)
if [ -z "$MISSING" ]; then
    ok "plugin dependencies" "all enabled in FlightSim.uproject"
else
    bad "plugin dependencies" "not enabled: $MISSING"
fi

echo
if [ "$STATUS" -eq 0 ]; then
    echo "API surface matches. This is NOT a compile -- it means the first build"
    echo "should fail on ordinary C++ errors, not on structural mismatches."
else
    echo "API surface has drifted. Fix before spending a build."
fi
exit "$STATUS"
