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
    # The path in VENDORED.json is relative to the plugin root.
    LIB=$(python3 -c "import json;print(json.load(open('$PLUGIN/VENDORED.json'))['library'])")
    TAG=$(python3 -c "import json;print(json.load(open('$PLUGIN/VENDORED.json'))['tag'])")
    if [ -f "$PLUGIN/$LIB" ]; then
        ARCHS=$(lipo -archs "$PLUGIN/$LIB" 2>/dev/null || echo "n/a")
        say "jsbsim plugin" "vendored $TAG ($ARCHS)"
    else
        fail "jsbsim plugin" "vendored but $LIB is missing"
    fi
    AIRCRAFT=$(python3 -c "import json;print(json.load(open('$PLUGIN/VENDORED.json'))['aircraft_staged'])")
    if [ "$AIRCRAFT" -gt 0 ]; then
        say "jsbsim runtime data" "$AIRCRAFT aircraft staged in Resources/JSBSim"
    else
        fail "jsbsim runtime data" "Resources/JSBSim is empty -- the host would have no aircraft to load"
    fi
    # Both hosts must run the same JSBSim, or §2.9's parity claim is untestable.
    CORE=$(.venv/bin/python -c "import jsbsim,re;print(re.search(r'commit ([0-9a-f]+)', jsbsim.FGJSBBase().get_version()).group(1))" 2>/dev/null)
    VENDORED_COMMIT=$(python3 -c "import json;print(json.load(open('$PLUGIN/VENDORED.json'))['commit'])")
    if [ "$CORE" = "$VENDORED_COMMIT" ]; then
        say "jsbsim parity" "both hosts at ${CORE:0:12}"
    else
        fail "jsbsim parity" "headless ${CORE:0:12} != plugin ${VENDORED_COMMIT:0:12}"
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

# -- the bridge's API assumptions, checkable without a compiler -------------
if [ -x scripts/check_bridge_api.sh ]; then
    if scripts/check_bridge_api.sh >/dev/null 2>&1; then
        say "bridge API surface" "matches the vendored plugin (not a compile)"
    else
        fail "bridge API surface" "drifted -- run scripts/check_bridge_api.sh"
    fi
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

    2. A newer engine is NOT the easy way out. The plugin's own README states
       "compatible with engine versions UE5.6 - UE5.0", so UE5.6 is the ceiling
       -- and UE5.6 predates Xcode 26, so it almost certainly rejects it for
       the same reason. Escaping the check means UE5.7+, which is outside the
       range the plugin supports at all.

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
