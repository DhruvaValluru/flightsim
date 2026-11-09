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
aircraft_check "Custom CMOT_Float4" "$RE/Public/Materials/MaterialExpressionCustom.h" "CMOT_Float4"
aircraft_check "MaterialExpressionLocalPosition" "$RE/Public/Materials/MaterialExpressionLocalPosition.h" "class UMaterialExpressionLocalPosition"
aircraft_check "MaterialExpressionTransform" "$RE/Public/Materials/MaterialExpressionTransform.h" "TransformSourceType"
aircraft_check "ProcMesh CreateMeshSection_LinearColor" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "void CreateMeshSection_LinearColor(int32 SectionIndex, const TArray<FVector>& Vertices, const TArray<int32>& Triangles, const TArray<FVector>& Normals, const TArray<FVector2D>& UV0, const TArray<FLinearColor>& VertexColors"
aircraft_check "ProcMesh ClearMeshSection" "Plugins/Runtime/ProceduralMeshComponent/Source/ProceduralMeshComponent/Public/ProceduralMeshComponent.h" "void ClearMeshSection(int32 SectionIndex)"
aircraft_check "RotationMatrix MakeFromX" "Runtime/Core/Public/Math/RotationMatrix.h" "MakeFromX(TVector<T> const& XAxis)"
aircraft_check "Math UE_DOUBLE_PI" "Runtime/Core/Public/Math/UnrealMathUtility.h" "#define UE_DOUBLE_PI"
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
hl_check "hero: SetVolumetricScatteringIntensity" "$HLL" "ENGINE_API void SetVolumetricScatteringIntensity(float NewIntensity);"
hl_check "hero: ContactShadowLength" "$HLL" "float ContactShadowLength;"
hl_check "hero: ContactShadowLengthInWS" "$HLL" "uint32 ContactShadowLengthInWS : 1;"
hl_check "hero: ContactShadowCastingIntensity" "$HLL" "float ContactShadowCastingIntensity;"
hl_check "hero: ContactShadowNonCastingIntensity" "$HLL" "float ContactShadowNonCastingIntensity;"
hl_check "hero: SetCastVolumetricShadow" "$HLB" "ENGINE_API void SetCastVolumetricShadow(bool bNewValue);"
hl_check "hero: SkyLight IsRealTimeCaptureEnabled" "$HLS" "ENGINE_API bool IsRealTimeCaptureEnabled() const;"
hl_check "hero: SkyLight SetLowerHemisphereColor" "$HLS" "ENGINE_API void SetLowerHemisphereColor(const FLinearColor& InLowerHemisphereColor);"
hl_check "hero: SkyLight SetCaptureIsDirty" "$HLS" "ENGINE_API void SetCaptureIsDirty();"
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
