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
if [ -f "$UE_ROOT/Engine/Content/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.uasset" ]; then
    ok "engine simple cloud material" "present"
else
    bad "engine simple cloud material" "missing: physical-sky renders draw no clouds (recorded, not fatal)"
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
if [ -f "$UE_ROOT/Engine/Content/EngineResources/WhiteSquareTexture.uasset" ]; then
    ok "engine WhiteSquareTexture" "present"
else
    bad "engine WhiteSquareTexture" "missing: the aircraft masters' BaseColorMap default"
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
