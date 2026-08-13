#!/usr/bin/env bash
# Fly one scenario in the Unreal host, headlessly, and write its telemetry.
#
#     scripts/run_ue_scenario.sh <run-card.json> <telemetry-out.json>
#
# The run card is written from a ScenarioSpec by experiments/gate5_ue_parity.py.
# It is the spec, not a sentence and not a second set of numbers: the commandlet
# refuses any condition it cannot honour exactly rather than approximating it,
# so a card that runs here commands the same scenario the headless host ran.
#
# No Xcode is involved -- this runs an already-built editor. Building is
# scripts/build_ue.sh, and that is the only step with a toolchain constraint.

# The UE half is macOS-only for now: every render gotcha was measured on
# Metal/macOS. Off-mac, refuse BY NAME with a pointer to the headless path.
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "REFUSED ue.platform: rendered clips currently require macOS."
  echo "The compiler, headless physics, telemetry and the webapp run on"
  echo "this OS -- see README \"Platform support\"."
  exit 3
fi

set -euo pipefail
cd "$(dirname "$0")/.."

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.5}"
EDITOR="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor-Cmd"

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <run-card.json> <telemetry-out.json> [extra commandlet flags]" >&2
    echo "e.g. -AllowNonParityEnvironment for a turbulence measurement run" >&2
    exit 2
fi

CARD="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
OUT_DIR="$(cd "$(dirname "$2")" && pwd)"
OUT="$OUT_DIR/$(basename "$2")"
shift 2

[ -x "$EDITOR" ] || { echo "no editor at $EDITOR (set UE_ROOT)" >&2; exit 1; }
[ -f "$CARD" ] || { echo "no run card at $CARD" >&2; exit 1; }
[ -f "ue/Plugins/FlightSimBridge/Binaries/Mac/UnrealEditor-FlightSimBridge.dylib" ] || {
    echo "the bridge is not built -- run scripts/build_ue.sh" >&2; exit 1; }

# A stale file from an earlier run would be indistinguishable from a fresh one
# if the commandlet failed before writing.
rm -f "$OUT"

STATUS=0
"$EDITOR" "$PWD/ue/FlightSim.uproject" \
    -run=FlightSimBridge.FlightSimScenario \
    -scenario="$CARD" \
    -telemetry="$OUT" \
    -unattended -nopause -nosplash -nullrhi -stdout -FullStdOutLogOutput \
    "$@" || STATUS=$?

if [ "$STATUS" -ne 0 ]; then
    echo "commandlet exited $STATUS -- no telemetry" >&2
    exit "$STATUS"
fi
[ -f "$OUT" ] || { echo "commandlet reported success but wrote no $OUT" >&2; exit 1; }
echo "wrote $OUT"
