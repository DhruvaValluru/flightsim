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

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.5}"
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
for m in $(grep -oE '"[A-Za-z]+"' "$BRIDGE/Source/FlightSimBridge/FlightSimBridge.Build.cs" \
           | tr -d '"' | sort -u); do
    case "$m" in Core|CoreUObject|Engine) continue ;; esac
    if find "$UE_ROOT/Engine" "$PLUGIN" -name "$m.Build.cs" 2>/dev/null | grep -q .; then
        ok "module $m" "resolves"
    else
        bad "module $m" "no $m.Build.cs anywhere"
    fi
done

# -- plugin dependencies must be enabled in the uproject --------------------
MISSING=$(python3 - <<'PY'
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
