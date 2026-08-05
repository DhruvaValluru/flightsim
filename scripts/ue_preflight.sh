#!/usr/bin/env bash
# Check whether this machine can build the Unreal host, and say exactly why not.
#
# Phase 5 is blocked on this machine and the reason is narrow, so it is worth
# diagnosing precisely rather than reporting "Unreal does not work". Every other
# element of the integration -- the plugin's macOS support, the native library,
# the bridge sources -- is in place. What is missing is a compiler version.
set -uo pipefail
cd "$(dirname "$0")/.."

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.5}"
STATUS=0

say() { printf '  %-34s %s\n' "$1" "$2"; }
fail() { printf '  %-34s %s\n' "$1" "$2"; STATUS=1; }

echo "Unreal host preflight"
echo

# -- engine -----------------------------------------------------------------
if [ -d "$UE_ROOT" ]; then
    VERSION=$(python3 -c "
import json,sys
d=json.load(open('$UE_ROOT/Engine/Build/Build.version'))
print(f\"{d['MajorVersion']}.{d['MinorVersion']}.{d['PatchVersion']}\")" 2>/dev/null || echo "unknown")
    say "engine" "UE $VERSION at $UE_ROOT"
else
    fail "engine" "not found at $UE_ROOT (set UE_ROOT)"
fi

# -- the vendored plugin ----------------------------------------------------
PLUGIN="ue/Plugins/JSBSimFlightDynamicsModel"
if [ -f "$PLUGIN/VENDORED.json" ]; then
    LIB=$(python3 -c "import json;print(json.load(open('$PLUGIN/VENDORED.json'))['library'])")
    if [ -f "$PLUGIN/Source/ThirdParty/JSBSim/$LIB" ]; then
        ARCHS=$(lipo -archs "$PLUGIN/Source/ThirdParty/JSBSim/$LIB" 2>/dev/null || echo "n/a")
        say "jsbsim plugin" "vendored, $LIB ($ARCHS)"
    else
        fail "jsbsim plugin" "vendored but $LIB is missing"
    fi
else
    fail "jsbsim plugin" "not vendored -- run scripts/vendor_ue_plugin.sh"
fi

# -- the bridge -------------------------------------------------------------
BRIDGE_SOURCES=$(find ue/Plugins/FlightSimBridge -name "*.cpp" 2>/dev/null | wc -l | tr -d ' ')
if [ "$BRIDGE_SOURCES" -gt 0 ]; then
    say "flightsim bridge" "$BRIDGE_SOURCES translation units (UNCOMPILED)"
else
    fail "flightsim bridge" "no sources"
fi

# -- the toolchain, which is the part that actually blocks ------------------
if ! command -v xcodebuild >/dev/null; then
    fail "xcode" "not installed"
else
    XCODE_VERSION=$(xcodebuild -version 2>/dev/null | head -1 | awk '{print $2}')
    MAJOR=${XCODE_VERSION%%.*}
    # UE 5.5 accepts Xcode 15.2 through 16.9; UBT reports this itself as
    # "Found Sdk Version=..., MinRequired=15.2.0, MaxRequired=16.9.0".
    if [ "$MAJOR" -ge 15 ] && [ "$MAJOR" -le 16 ]; then
        say "xcode" "$XCODE_VERSION (within UE 5.5's 15.2-16.9 range)"
    else
        fail "xcode" "$XCODE_VERSION is OUTSIDE UE 5.5's supported range 15.2-16.9"
        cat <<'EOF'

  This is the blocker. UnrealBuildTool refuses to register Mac as a buildable
  platform, so the project cannot compile and Gate 5 cannot run:

      Unable to find valid SDK(s) for Mac:
        Found Sdk Version=26.6, MinRequired=15.2.0, MaxRequired=16.9.0.
      Registering build platform: Mac - buildable: False

  It is a compiler-version check, not a macOS limitation and not a plugin
  limitation. The plugin's own JSBSim.Build.cs lists Mac as supported, and
  scripts/vendor_ue_plugin.sh has already built a universal arm64+x86_64
  libJSBSim.dylib for it.

  Neither -IgnoreSDKCheck on the command line nor bIgnoreSDKCheck in
  BuildConfiguration.xml is honoured by UBT 5.5; both were tried.

  Two ways forward, both of which are the operator's call because they cost
  disk and require an Apple ID:

    1. Install Xcode 16.x alongside the current one and point the build at it:
         sudo xcode-select -s /Applications/Xcode_16.app
       This is the conservative option: UE 5.5 is the version the Cesium and
       JSBSim plugin compatibility intersection was pinned to (§3).

    2. Move to a newer engine whose supported range includes this Xcode.
       That re-opens the plugin compatibility question §3 settled, so it should
       be a deliberate decision rather than a workaround.

EOF
    fi
fi

echo
if [ "$STATUS" -eq 0 ]; then
    echo "Preflight OK -- the Unreal host can be built."
else
    echo "Preflight FAILED -- see above. Gate 5 cannot be run on this machine."
fi
exit "$STATUS"
