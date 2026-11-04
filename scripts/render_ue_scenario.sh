#!/usr/bin/env bash
# Fly one scenario in the Unreal host with the renderer up, and write frames
# -- ONE COMMANDLET PASS PER CAMERA.
#
#     scripts/render_ue_scenario.sh <run-card.json> <frames-out-dir> [commandlet flags...]
#
# The macOS twin of render_ue_scenario.ps1, which is the maintained one:
# the two take the same arguments and run the same passes. A card carrying
# a `cameras` block is rendered once per camera (`-camera-index=N`), each
# pass writing into its own <frames-out-dir>/<camera_id>/ directory --
# exactly the layout capture_manifest.json names in every frame record's
# `file` field -- and recording the flight it flew (-telemetry=). A card
# with no cameras block renders as it always did: one pass, flat directory.
# Anything after the two positional arguments (-Visual, -terrain=,
# -GeorefTerrain, ...) goes to EVERY pass, so two cameras of one flight are
# never rendered in two different worlds.
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

# The maintained render platform is WINDOWS (the .ps1 twin); a Mac builds
# the same sources but is not the tested path, and Linux has no engine half
# at all -- so off a Mac this refuses BY NAME with a pointer to both.
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "REFUSED ue.platform: this wrapper drives the macOS engine build; on"
  echo "Windows run scripts\\render_ue_scenario.ps1, and on Linux there is no"
  echo "engine half. The compiler, headless physics, telemetry and the webapp"
  echo "run on this OS -- see README \"Platform support\"."
  exit 3
fi

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <run-card.json> <frames-out-dir> [commandlet flags...]" >&2
    exit 2
fi

# Both paths are the caller's, so they resolve BEFORE the move to the repo.
[ -f "$1" ] || { echo "no run card at $1" >&2; exit 1; }
CARD="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
mkdir -p "$2"
OUT="$(cd "$2" && pwd)"
shift 2
SCENE_ARGS=("$@")

cd "$(dirname "$0")/.."

UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.7}"
EDITOR="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor-Cmd"
PYTHON="${PYTHON:-.venv/bin/python}"

[ -x "$EDITOR" ] || { echo "no editor at $EDITOR (set UE_ROOT)" >&2; exit 1; }
[ -f "ue/Plugins/FlightSimBridge/Binaries/Mac/UnrealEditor-FlightSimBridge.dylib" ] || {
    echo "the bridge is not built -- run scripts/build_ue.sh" >&2; exit 1; }

# The camera ids on the card, in the order the commandlet indexes them.
# None means a card with no cameras block: the single pass, unchanged.
CAMERA_IDS=()
while IFS= read -r id; do
    [ -n "$id" ] && CAMERA_IDS+=("$id")
done < <("$PYTHON" -c '
import json, sys
card = json.load(open(sys.argv[1], encoding="utf-8"))
print("\n".join(str(c["camera_id"]) for c in card.get("cameras", [])))
' "$CARD")

if [ "${#SCENE_ARGS[@]}" -gt 0 ]; then
    echo "scene flags for every pass: ${SCENE_ARGS[*]}"
fi

render_pass() {
    local dir="$1"; shift
    mkdir -p "$dir"
    # Frames from an earlier run would be indistinguishable from this one's
    # if the commandlet failed part way through; a stale host telemetry
    # would be graded as if this pass had produced it.
    rm -f "$dir"/frame_*.png "$dir/render.json" "$dir/host_telemetry.json"

    # Keep the engine's own output: the commandlet's named refusal is the
    # one thing that says WHY a pass produced no frames.
    local log="$dir/render.log" status=0
    "$EDITOR" "$PWD/ue/FlightSim.uproject" \
        -run=FlightSimBridge.FlightSimRender \
        -scenario="$CARD" \
        -frames="$dir" \
        "$@" \
        -unattended -nopause -nosplash -stdout -FullStdOutLogOutput \
        -RenderOffScreen -AllowCommandletRendering > "$log" 2>&1 || status=$?

    if [ "$status" -ne 0 ] || [ ! -f "$dir/render.json" ]; then
        echo ""
        echo "---- the commandlet's last words ($log) ----"
        grep -E "LogFlightSimRender|consume-poses|cameras block|camera pose track|Error:|Fatal" \
            "$log" | tail -n 25 || tail -n 25 "$log"
        echo "-------------------------------------------"
        if [ "$status" -ne 0 ]; then
            echo "commandlet exited $status -- no frames in $dir" >&2
            exit "$status"
        fi
        echo "commandlet reported success but wrote no $dir/render.json" >&2
        exit 1
    fi
    PASS_FRAMES=$(find "$dir" -maxdepth 1 -name 'frame_*.png' | wc -l | tr -d ' ')
}

if [ "${#CAMERA_IDS[@]}" -eq 0 ]; then
    render_pass "$OUT" ${SCENE_ARGS[@]+"${SCENE_ARGS[@]}"}
    echo "wrote $PASS_FRAMES frames and $OUT/render.json"
else
    total=0
    for i in "${!CAMERA_IDS[@]}"; do
        id="${CAMERA_IDS[$i]}"
        dir="$OUT/$id"
        echo "camera $((i + 1))/${#CAMERA_IDS[@]}: $id -> $dir"
        # -telemetry= makes the host record the flight it ACTUALLY flew, the
        # one flight_agreement grades the manifest against.
        render_pass "$dir" "-camera-index=$i" "-telemetry=$dir/host_telemetry.json" \
            ${SCENE_ARGS[@]+"${SCENE_ARGS[@]}"}
        echo "  wrote $PASS_FRAMES frames"
        total=$((total + PASS_FRAMES))
    done
    echo "wrote $total frames across ${#CAMERA_IDS[@]} camera(s) under $OUT"
fi
