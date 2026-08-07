#!/usr/bin/env bash
# Fly one scenario in the Unreal host with the renderer up, and write frames.
#
#     scripts/render_ue_scenario.sh <run-card.json> <frames-out-dir>
#
# This is the other half of Gate 5: two of its three clauses are about what a
# viewer sees, and no number in a telemetry file can answer them.
#
# The two flags that matter, and why the run is worthless without them:
#
#   -AllowCommandletRendering   commandlets come up with a null RHI by default.
#                               Without this every capture writes a blank frame
#                               and the run reports success.
#   -RenderOffScreen            no window, no display needed. Not the same
#                               thing as -nullrhi, which is the opposite.
#
# The commandlet checks for the renderer itself and refuses to write anything
# rather than produce files that look like evidence.
set -euo pipefail
cd "$(dirname "$0")/.."

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.5}"
EDITOR="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor-Cmd"

if [ "$#" -ne 2 ]; then
    echo "usage: $0 <run-card.json> <frames-out-dir>" >&2
    exit 2
fi

CARD="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
mkdir -p "$2"
OUT="$(cd "$2" && pwd)"

[ -x "$EDITOR" ] || { echo "no editor at $EDITOR (set UE_ROOT)" >&2; exit 1; }
[ -f "$CARD" ] || { echo "no run card at $CARD" >&2; exit 1; }
[ -f "ue/Plugins/FlightSimBridge/Binaries/Mac/UnrealEditor-FlightSimBridge.dylib" ] || {
    echo "the bridge is not built -- run scripts/build_ue.sh" >&2; exit 1; }

# Frames from an earlier run would be indistinguishable from this one's if the
# commandlet failed part way through.
rm -f "$OUT"/frame_*.png "$OUT/render.json"

STATUS=0
"$EDITOR" "$PWD/ue/FlightSim.uproject" \
    -run=FlightSimBridge.FlightSimRender \
    -scenario="$CARD" \
    -frames="$OUT" \
    -unattended -nopause -nosplash -stdout -FullStdOutLogOutput \
    -RenderOffScreen -AllowCommandletRendering || STATUS=$?

if [ "$STATUS" -ne 0 ]; then
    echo "commandlet exited $STATUS -- no frames" >&2
    exit "$STATUS"
fi
[ -f "$OUT/render.json" ] || {
    echo "commandlet reported success but wrote no $OUT/render.json" >&2; exit 1; }
echo "wrote $(ls "$OUT"/frame_*.png | wc -l | tr -d ' ') frames and $OUT/render.json"
