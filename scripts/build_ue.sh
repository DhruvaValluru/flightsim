#!/usr/bin/env bash
# Build the Unreal host with a toolchain UE 5.5 accepts.
#
# DEVELOPER_DIR rather than `sudo xcode-select`: the override is per process, so
# the machine's default Xcode is untouched and no admin password is needed.

# This is the macOS/Linux shell wrapper. The maintained render platform is
# WINDOWS (the .ps1 twin of this script); a Mac builds the same sources but
# is not the tested path, and Linux has no engine half at all -- so off a
# Mac this refuses BY NAME with a pointer to the headless path.
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "REFUSED ue.platform: rendered clips currently require macOS."
  echo "The compiler, headless physics, telemetry and the webapp run on"
  echo "this OS -- see README \"Platform support\"."
  exit 3
fi

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
