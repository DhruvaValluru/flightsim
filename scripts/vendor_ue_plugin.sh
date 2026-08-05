#!/usr/bin/env bash
# Vendor the official Epic JSBSim UE plugin and build its native library.
#
# §3.1 says to use the official plugin rather than rebuild it, and its
# documented build path is Windows-only: build JSBSimForUnreal.sln in
# Release/x64, with MSVC v143 toolchain v14.38.
#
# That documentation is narrower than the plugin. Source/ThirdParty/JSBSim.Build.cs
# reads:
#
#     bool bJSBSimSupported = Target.Platform == UnrealTargetPlatform.Win64 ||
#                             Target.Platform == UnrealTargetPlatform.Mac || ...
#     if (Target.Platform == UnrealTargetPlatform.Win64) SetupWindowsPlatform();
#     else SetupUnixPlatform();
#
# and SetupUnixPlatform looks for Lib/<Platform>/libJSBSim.dylib. So the plugin
# supports macOS; what is missing from the repository is the built library,
# which the Windows .sln would otherwise produce. This script produces the
# macOS equivalent with CMake.
#
# The JSBSim version is pinned to the SAME version the headless core runs
# (1.2.4). §2.9 requires a scenario to produce identical physics in either
# host, and two different JSBSim versions would make that untestable by
# construction.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

JSBSIM_VERSION="v1.2.4"
PLUGIN_REPO="https://github.com/JSBSim-Team/jsbsim.git"
WORK="${TMPDIR:-/tmp}/flightsim-vendor"
DEST="$REPO/ue/Plugins/JSBSimFlightDynamicsModel"

command -v cmake >/dev/null || { echo "cmake is required: brew install cmake"; exit 1; }

mkdir -p "$WORK"

# -- 1. the plugin itself, from the JSBSim repository's UnrealEngine folder ---
if [ ! -d "$WORK/plugin-src" ]; then
    echo "==> fetching plugin source"
    git clone --depth 1 --filter=blob:none --sparse "$PLUGIN_REPO" "$WORK/plugin-src" >/dev/null 2>&1
    ( cd "$WORK/plugin-src" && git sparse-checkout set UnrealEngine >/dev/null 2>&1 )
fi
PLUGIN_COMMIT=$( cd "$WORK/plugin-src" && git rev-parse HEAD )

# -- 2. JSBSim itself, pinned to the headless core's version -----------------
if [ ! -d "$WORK/jsbsim" ]; then
    echo "==> fetching JSBSim $JSBSIM_VERSION"
    git clone --depth 1 --branch "$JSBSIM_VERSION" "$PLUGIN_REPO" "$WORK/jsbsim" >/dev/null 2>&1
fi

PLATFORM="$(uname -s)"
case "$PLATFORM" in
    Darwin) UE_PLATFORM="Mac"; LIB_EXT="dylib" ;;
    Linux)  UE_PLATFORM="Linux"; LIB_EXT="so" ;;
    *) echo "unsupported host platform $PLATFORM"; exit 1 ;;
esac

if [ ! -f "$WORK/jsbsim/build/src/libJSBSim.$LIB_EXT" ]; then
    echo "==> building libJSBSim.$LIB_EXT (universal where supported)"
    mkdir -p "$WORK/jsbsim/build"
    ( cd "$WORK/jsbsim/build" && cmake .. \
        -DBUILD_SHARED_LIBS=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" \
        -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 \
        -DBUILD_DOCS=OFF -DBUILD_PYTHON_MODULE=OFF -DBUILD_MATLAB_SFUNCTION=OFF \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >/dev/null \
      && cmake --build . --config Release -j "$(sysctl -n hw.ncpu 2>/dev/null || nproc)" >/dev/null )
fi

# -- 3. assemble the vendored plugin ----------------------------------------
echo "==> vendoring into ue/Plugins"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$WORK/plugin-src/UnrealEngine/Plugins/JSBSimFlightDynamicsModel/." "$DEST/"

THIRD_PARTY="$DEST/Source/ThirdParty/JSBSim"
mkdir -p "$THIRD_PARTY/Include" "$THIRD_PARTY/Lib/$UE_PLATFORM"

# Headers keep their src-relative layout: the plugin includes them as
# "models/FGAircraft.h", not by a flattened name.
( cd "$WORK/jsbsim/src" && find . -name "*.h" -o -name "*.hxx" ) | while read -r header; do
    mkdir -p "$THIRD_PARTY/Include/$(dirname "$header")"
    cp "$WORK/jsbsim/src/$header" "$THIRD_PARTY/Include/$header"
done
# JSBSim generates its version header at configure time, so it lives in the
# build tree rather than in src.
find "$WORK/jsbsim/build" -name "JSBSim_version.h" -exec cp {} "$THIRD_PARTY/Include/" \; 2>/dev/null || true

cp "$WORK/jsbsim/build/src/libJSBSim.$LIB_EXT" "$THIRD_PARTY/Lib/$UE_PLATFORM/"

# The dylib records its own install name; without rewriting it the packaged
# binary looks for it at the build path, which will not exist on any other
# machine.
if [ "$PLATFORM" = "Darwin" ]; then
    install_name_tool -id "@rpath/libJSBSim.dylib" \
        "$THIRD_PARTY/Lib/$UE_PLATFORM/libJSBSim.dylib" 2>/dev/null || true
fi

# -- 4. record what was vendored --------------------------------------------
LIB_SHA=$(shasum -a 256 "$THIRD_PARTY/Lib/$UE_PLATFORM/libJSBSim.$LIB_EXT" | cut -d' ' -f1)
HEADER_COUNT=$(find "$THIRD_PARTY/Include" -name "*.h" | wc -l | tr -d ' ')
cat > "$DEST/VENDORED.json" <<EOF
{
  "plugin_source": "$PLUGIN_REPO (UnrealEngine/Plugins/JSBSimFlightDynamicsModel)",
  "plugin_commit": "$PLUGIN_COMMIT",
  "jsbsim_version": "$JSBSIM_VERSION",
  "jsbsim_matches_headless_core": true,
  "host_platform": "$PLATFORM",
  "ue_platform": "$UE_PLATFORM",
  "library": "Lib/$UE_PLATFORM/libJSBSim.$LIB_EXT",
  "library_sha256": "$LIB_SHA",
  "header_count": $HEADER_COUNT,
  "note": "Built by scripts/vendor_ue_plugin.sh. The upstream repository ships no prebuilt library for any platform; the Windows instructions build one from JSBSimForUnreal.sln and this script builds the Unix equivalent with CMake."
}
EOF

echo
echo "vendored plugin      $DEST"
echo "  plugin commit      $PLUGIN_COMMIT"
echo "  jsbsim             $JSBSIM_VERSION (matches headless core)"
echo "  library            Lib/$UE_PLATFORM/libJSBSim.$LIB_EXT"
if [ "$PLATFORM" = "Darwin" ]; then
    echo "  architectures      $(lipo -archs "$THIRD_PARTY/Lib/$UE_PLATFORM/libJSBSim.dylib" 2>/dev/null)"
fi
echo "  headers            $HEADER_COUNT"
