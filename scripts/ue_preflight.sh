#!/usr/bin/env bash
# Check whether this machine can build the Unreal host, and say exactly why not.
#
# Phase 5 is blocked on this machine and the reason is narrow, so it is worth
# diagnosing precisely rather than reporting "Unreal does not work". Every other
# element of the integration -- the plugin's macOS support, the native library,
# the bridge sources -- is in place. What is missing is a compiler version.

# The UE half is macOS-only for now: every render gotcha was measured on
# Metal/macOS. Off-mac, refuse BY NAME with a pointer to the headless path.
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "REFUSED ue.platform: rendered clips currently require macOS."
  echo "The compiler, headless physics, telemetry and the webapp run on"
  echo "this OS -- see README \"Platform support\"."
  exit 3
fi

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
# Source only: Intermediate/ fills with generated .cpp once a build has run.
BRIDGE_SOURCES=$(find ue/Plugins/FlightSimBridge/Source -name "*.cpp" 2>/dev/null | wc -l | tr -d ' ')
if [ "$BRIDGE_SOURCES" -gt 0 ]; then
    say "flightsim bridge" "$BRIDGE_SOURCES translation units"
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

# -- the toolchain ----------------------------------------------------------
# UE 5.5 accepts Xcode 15.2 through 16.9 and hard-refuses anything else; UBT
# reports this itself as "Found Sdk Version=..., MaxRequired=16.9.0". macOS 26
# ships Xcode 26, which is outside that range, so a second Xcode is needed.
#
# It does NOT have to be the system default. DEVELOPER_DIR overrides the
# toolchain per process, so `sudo xcode-select` is unnecessary and the machine's
# default Xcode is left alone for everything else.
#
# Note also that macOS 26 refuses to LAUNCH Xcode 16.4's GUI ("not compatible
# with macOS Tahoe"). That dialog is irrelevant here: UE never launches Xcode,
# it invokes clang and xcodebuild, and those run fine.
USABLE=""
for candidate in "${DEVELOPER_DIR:-}" \
                 /Applications/Xcode_16.app/Contents/Developer \
                 "$(xcode-select -p 2>/dev/null)"; do
    [ -n "$candidate" ] && [ -x "$candidate/usr/bin/xcodebuild" ] || continue
    V=$("$candidate/usr/bin/xcodebuild" -version 2>/dev/null | head -1 | awk '{print $2}')
    MAJOR=${V%%.*}
    if [ -n "$MAJOR" ] && [ "$MAJOR" -ge 15 ] && [ "$MAJOR" -le 16 ]; then
        USABLE="$candidate"
        say "xcode (build toolchain)" "$V at $candidate"
        break
    fi
done

if [ -z "$USABLE" ]; then
    fail "xcode (build toolchain)" "no Xcode in UE 5.5's supported range 15.2-16.9"
    cat <<'EOF'

  Install Xcode 16.x alongside the system one -- it does not need to become the
  default. Then build with:

      export DEVELOPER_DIR=/Applications/Xcode_16.app/Contents/Developer

  A newer engine is NOT the easy way out: the plugin states "compatible with
  engine versions UE5.6 - UE5.0", and UE5.6 predates Xcode 26, so it almost
  certainly rejects it too.

EOF
else
    SYSTEM=$(xcodebuild -version 2>/dev/null | head -1 | awk '{print $2}')
    [ "$USABLE" = "$(xcode-select -p 2>/dev/null)" ] || \
        say "" "system default is still $SYSTEM; build with DEVELOPER_DIR=$USABLE"
fi

# -- did it actually build? -------------------------------------------------
BRIDGE_DYLIB="ue/Plugins/FlightSimBridge/Binaries/Mac/UnrealEditor-FlightSimBridge.dylib"
if [ -f "$BRIDGE_DYLIB" ]; then
    say "bridge binary" "built ($(lipo -archs "$BRIDGE_DYLIB" 2>/dev/null))"
else
    fail "bridge binary" "not built yet -- run scripts/build_ue.sh"
fi

echo
if [ "$STATUS" -eq 0 ]; then
    echo "Preflight OK -- the Unreal host can be built."
else
    echo "Preflight FAILED -- see above. Gate 5 cannot be run on this machine."
fi
exit "$STATUS"
