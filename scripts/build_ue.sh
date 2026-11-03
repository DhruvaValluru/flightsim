#!/usr/bin/env bash
# Build the Unreal host with a toolchain UE 5.7 accepts (the Xcode range
# below predates the 5.7 pin; 5.7's has not been checked on a Mac).
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

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.7}"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode_16.app/Contents/Developer}"
TARGET="${1:-FlightSimEditor}"

[ -x "$DEVELOPER_DIR/usr/bin/xcodebuild" ] || {
    echo "no usable Xcode at $DEVELOPER_DIR -- see scripts/ue_preflight.sh"; exit 1; }

echo "building $TARGET with $("$DEVELOPER_DIR/usr/bin/xcodebuild" -version | head -1)"
"$UE_ROOT/Engine/Build/BatchFiles/Mac/Build.sh" "$TARGET" Mac Development \
    -project="$PWD/ue/FlightSim.uproject" -waitmutex

# Phase 3 A4: the stamp every render checks (engine.binary_stale), written
# only after a clean editor build. Refuses (exit 2) an engine that is not
# the pinned patch (A3, engine.version_mismatch).
if [ "$TARGET" = "FlightSimEditor" ]; then
  PY="python3"; [ -x .venv/bin/python ] && PY=".venv/bin/python"
  "$PY" -m core.util.build_stamp write --ue-root "$UE_ROOT"
fi
