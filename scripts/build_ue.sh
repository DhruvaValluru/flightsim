#!/usr/bin/env bash
# Build the Unreal host with a toolchain UE 5.5 accepts.
#
# DEVELOPER_DIR rather than `sudo xcode-select`: the override is per process, so
# the machine's default Xcode is untouched and no admin password is needed.
set -euo pipefail
cd "$(dirname "$0")/.."

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.5}"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode_16.app/Contents/Developer}"
TARGET="${1:-FlightSimEditor}"

[ -x "$DEVELOPER_DIR/usr/bin/xcodebuild" ] || {
    echo "no usable Xcode at $DEVELOPER_DIR -- see scripts/ue_preflight.sh"; exit 1; }

echo "building $TARGET with $("$DEVELOPER_DIR/usr/bin/xcodebuild" -version | head -1)"
"$UE_ROOT/Engine/Build/BatchFiles/Mac/Build.sh" "$TARGET" Mac Development \
    -project="$PWD/ue/FlightSim.uproject" -waitmutex
