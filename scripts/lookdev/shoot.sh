#!/bin/bash
# Look-dev still for one or more test scenes in the running editor:
#   MCP=<path to mcp.sh> scripts/lookdev/shoot.sh <tag> <scene> [scene ...]
# build(scene) + capture(scene, tag) through Monolith run_python, then waits
# for $FLIGHTSIM_LOOKDEV_DIR/<tag>/<scene>.png.status.json (Cesium streams
# while the editor ticks; up to 300 s per scene).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${FLIGHTSIM_LOOKDEV_DIR:-/private/tmp/claude-501/-Users-dhruva-flightsim/1ee4c848-46ef-47be-bb8c-91917a93ad66/scratchpad/lookdev}"
MCP="${MCP:-/private/tmp/claude-501/-Users-dhruva-flightsim/1ee4c848-46ef-47be-bb8c-91917a93ad66/scratchpad/tools/mcp.sh}"
TAG="$1"; shift
for SCENE in "$@"; do
  PNG="$OUT/$TAG/$SCENE.png"
  rm -f "$PNG.status.json"
  R=$("$MCP" editor_query "{\"action\":\"run_python\",\"params\":{\"command\":\"exec(open('$HERE/lookdev.py').read()); build($SCENE); capture($SCENE, '$TAG')\"}}" 2>&1)
  echo "$R" | grep -q '"success":true' || { echo "scene $SCENE: build failed: $(echo "$R" | grep -o 'RuntimeError[^"]*' | head -1)"; continue; }
  for i in $(seq 330); do [ -f "$PNG.status.json" ] && break; sleep 1; done
  echo "scene $SCENE: $(cat "$PNG.status.json" 2>/dev/null || echo 'no status after 330 s')"
done
