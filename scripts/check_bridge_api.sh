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
beauty_check "premise: physical camera EV100" "Renderer/Private/PostProcess/PostProcessEyeAdaptation.cpp" \
    "FMath::Log2(FMath::Square(Settings.DepthOfFieldFstop) * Settings.CameraShutterSpeed * 100"
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
