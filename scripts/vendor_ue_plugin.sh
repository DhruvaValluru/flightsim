#!/usr/bin/env bash
# Vendor the official Epic JSBSim UE plugin, using upstream's own build script.
#
# §3.1 says to use the official plugin rather than rebuild it. That extends to
# how it is built: this script runs upstream's JSBSimForUnrealMac.sh (or the
# Linux equivalent) rather than reimplementing its cmake invocation, so there is
# no parallel build recipe here to drift out of step with theirs.
#
# The one thing this adds is a version pin. Upstream's script builds whatever
# checkout it sits in; we run it inside a checkout of the SAME JSBSim version
# the headless core uses (1.2.4). §2.9 requires a scenario to produce identical
# physics in either host, and two JSBSim versions would make that untestable by
# construction. Conveniently the tag carries the plugin, the build script and
# the runtime aircraft data together, so plugin and library come from one commit.
#
# Two things the earlier hand-rolled version of this script got wrong, both
# found by reading upstream's README-Unix.md properly:
#
#   1. It never copied Resources/JSBSim -- the aircraft, engine and systems
#      data the plugin stages at runtime. The UE host would have had no
#      aircraft to load.
#   2. It did not notice that the plugin's Build.cs stages that data through a
#      Windows path literal. See the patch below.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

JSBSIM_VERSION="v1.2.4"
UPSTREAM="https://github.com/JSBSim-Team/jsbsim.git"
WORK="${TMPDIR:-/tmp}/flightsim-vendor"
DEST="$REPO/ue/Plugins/JSBSimFlightDynamicsModel"

command -v cmake >/dev/null || { echo "cmake is required: brew install cmake"; exit 1; }

case "$(uname -s)" in
    Darwin) UE_PLATFORM="Mac";   BUILD_SCRIPT="JSBSimForUnrealMac.sh";   LIB_EXT="dylib" ;;
    Linux)  UE_PLATFORM="Linux"; BUILD_SCRIPT="JSBSimForUnrealLinux.sh"; LIB_EXT="so" ;;
    *) echo "unsupported host platform $(uname -s)"; exit 1 ;;
esac

SRC="$WORK/jsbsim-$JSBSIM_VERSION"
if [ ! -d "$SRC" ]; then
    echo "==> fetching JSBSim $JSBSIM_VERSION (plugin, build script and data)"
    mkdir -p "$WORK"
    git clone --depth 1 --branch "$JSBSIM_VERSION" "$UPSTREAM" "$SRC" >/dev/null 2>&1
fi
COMMIT=$( cd "$SRC" && git rev-parse HEAD )

PLUGIN_SRC="$SRC/UnrealEngine/Plugins/JSBSimFlightDynamicsModel"
if [ ! -f "$PLUGIN_SRC/Source/ThirdParty/JSBSim/Lib/$UE_PLATFORM/libJSBSim.$LIB_EXT" ]; then
    echo "==> running upstream $BUILD_SCRIPT (builds the library, stages headers and data)"
    ( cd "$SRC" && chmod +x "$BUILD_SCRIPT" && ./"$BUILD_SCRIPT" >/dev/null 2>&1 )
fi

echo "==> vendoring into ue/Plugins"
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -R "$PLUGIN_SRC" "$DEST"

THIRD_PARTY="$DEST/Source/ThirdParty/JSBSim"
LIB="$THIRD_PARTY/Lib/$UE_PLATFORM/libJSBSim.$LIB_EXT"

# Upstream's script copies every produced dylib, including the versioned
# symlink targets. Keep the one the Build.cs actually links against.
if [ ! -f "$LIB" ]; then
    CANDIDATE=$(find "$THIRD_PARTY/Lib/$UE_PLATFORM" -name "libJSBSim*.$LIB_EXT" | head -1)
    [ -n "$CANDIDATE" ] && cp "$CANDIDATE" "$LIB"
fi
[ -f "$LIB" ] || { echo "no libJSBSim.$LIB_EXT produced"; exit 1; }

# ---------------------------------------------------------------- patch ----
# UPSTREAM BUG. JSBSimFlightDynamicsModel.Build.cs stages the runtime aircraft
# data with a Windows path literal:
#
#     Path.Combine(PluginDirectory, @"Resources\JSBSim\*")
#
# On macOS and Linux that yields a single filename containing backslashes,
# which matches nothing, so the aircraft/engine/systems data is silently not
# staged -- on the platforms upstream's own README lists as Supported. Patched
# here to a portable Path.Combine, and recorded in VENDORED.json so the
# deviation from upstream is visible rather than buried.
BUILD_CS="$DEST/Source/JSBSimFlightDynamicsModel/JSBSimFlightDynamicsModel.Build.cs"
PATCHED="no"
PATCHED_NODE="no"
if grep -q 'Resources\\JSBSim' "$BUILD_CS" 2>/dev/null; then
    python3 - "$BUILD_CS" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path).read()
src = src.replace(
    'Path.Combine(PluginDirectory, @"Resources\\JSBSim\\*")',
    'Path.Combine(PluginDirectory, "Resources", "JSBSim", "*")')
open(path, "w").write(src)
PYEOF
    PATCHED="yes"
fi

# UPSTREAM BUG 2. JSBSimMovementComponent.cpp declares the property node as
# FGPropertyNode*, a type that does not exist in JSBSim 1.2.4 -- the plugin is
# written against an older JSBSim than the library shipped beside it in the very
# same repository. FGPropertyManager::GetNode returns SGPropertyNode*, and
# upstream's own commented-out code in the same function already refers to
# SGPropertyNode::Attribute, so the intended type is not in doubt. Without this
# the plugin does not compile at all on the Unix path.
MOVEMENT_CPP="$DEST/Source/JSBSimFlightDynamicsModel/Private/JSBSimMovementComponent.cpp"
if grep -q 'FGPropertyNode\* node' "$MOVEMENT_CPP" 2>/dev/null; then
    python3 - "$MOVEMENT_CPP" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path).read()
src = src.replace("FGPropertyNode* node", "SGPropertyNode* node")
open(path, "w").write(src)
PYEOF
    PATCHED_NODE="yes"
fi

# The dylib records its own install name; without rewriting it a packaged build
# looks for the library at the machine it was built on.
if [ "$UE_PLATFORM" = "Mac" ]; then
    install_name_tool -id "@rpath/libJSBSim.dylib" "$LIB" 2>/dev/null || true
fi

# ------------------------------------------------------------ provenance ----
LIB_SHA=$(shasum -a 256 "$LIB" | cut -d' ' -f1)
HEADERS=$(find "$THIRD_PARTY/Include" -name "*.h" 2>/dev/null | wc -l | tr -d ' ')
AIRCRAFT=$(find "$DEST/Resources/JSBSim/aircraft" -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
cat > "$DEST/VENDORED.json" <<EOF
{
  "upstream": "$UPSTREAM",
  "tag": "$JSBSIM_VERSION",
  "commit": "$COMMIT",
  "built_with": "upstream $BUILD_SCRIPT (not a reimplementation)",
  "jsbsim_matches_headless_core": true,
  "ue_platform": "$UE_PLATFORM",
  "library": "Source/ThirdParty/JSBSim/Lib/$UE_PLATFORM/libJSBSim.$LIB_EXT",
  "library_sha256": "$LIB_SHA",
  "header_count": $HEADERS,
  "aircraft_staged": $((AIRCRAFT > 0 ? AIRCRAFT - 1 : 0)),
  "local_patches": [
    {
      "file": "Source/JSBSimFlightDynamicsModel/JSBSimFlightDynamicsModel.Build.cs",
      "applied": "$PATCHED",
      "reason": "upstream stages Resources/JSBSim via a Windows path literal (@\\"Resources\\\\JSBSim\\\\*\\"), which matches nothing on macOS or Linux, so the runtime aircraft data is silently not staged",
      "change": "portable Path.Combine(PluginDirectory, \\"Resources\\", \\"JSBSim\\", \\"*\\")"
    },
    {
      "file": "Source/JSBSimFlightDynamicsModel/Private/JSBSimMovementComponent.cpp",
      "applied": "$PATCHED_NODE",
      "reason": "declares FGPropertyNode*, a type absent from JSBSim 1.2.4; FGPropertyManager::GetNode returns SGPropertyNode*. The plugin is written against an older JSBSim than the library in the same repository, and does not compile without this.",
      "change": "FGPropertyNode* node -> SGPropertyNode* node (2 occurrences)"
    }
  ]
}
EOF

echo
echo "vendored             $DEST"
echo "  tag                $JSBSIM_VERSION @ ${COMMIT:0:12}"
echo "  built with         upstream $BUILD_SCRIPT"
echo "  library            libJSBSim.$LIB_EXT"
[ "$UE_PLATFORM" = "Mac" ] && echo "  architectures      $(lipo -archs "$LIB" 2>/dev/null)"
echo "  headers            $HEADERS"
echo "  aircraft staged    $((AIRCRAFT > 0 ? AIRCRAFT - 1 : 0))"
echo "  Build.cs patched   $PATCHED (Windows path literal -> portable)"
echo "  node type patched  $PATCHED_NODE (FGPropertyNode -> SGPropertyNode)"
