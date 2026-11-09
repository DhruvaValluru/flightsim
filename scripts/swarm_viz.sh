#!/usr/bin/env bash
# Start the live swarm dashboard (scripts/swarm_viz/server.py) in the background and open it.
#
#   scripts/swarm_viz.sh            start (or reuse) the server on 127.0.0.1:8787 and open the page
#   scripts/swarm_viz.sh stop       stop the server this script started
#   SWARM_VIZ_PORT=8790 scripts/swarm_viz.sh
#
# The page reads local files only (workflow transcripts, git worktrees, ruflo state, the pytest
# log). It does not poll any pull request or CI.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PORT="${SWARM_VIZ_PORT:-8787}"
URL="http://127.0.0.1:${PORT}"
RUN_DIR="${REPO}/runs/swarm_viz"
PID_FILE="${RUN_DIR}/server.pid"
LOG_FILE="${RUN_DIR}/server.log"

PY="${REPO}/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

if [ "${1:-}" = "stop" ]; then
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" && echo "swarm-viz: stopped pid $(cat "$PID_FILE")"
  else
    echo "swarm-viz: not running"
  fi
  rm -f "$PID_FILE"
  exit 0
fi

mkdir -p "$RUN_DIR"
if curl -fsS -m 2 "${URL}/healthz" >/dev/null 2>&1; then
  echo "swarm-viz: already serving ${URL}"
else
  nohup "$PY" "${HERE}/swarm_viz/server.py" --port "$PORT" "$@" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  for _ in $(seq 1 50); do
    curl -fsS -m 1 "${URL}/healthz" >/dev/null 2>&1 && break
    sleep 0.1
  done
  echo "swarm-viz: serving ${URL} (pid $(cat "$PID_FILE"), log ${LOG_FILE}); stop with: scripts/swarm_viz.sh stop"
fi
open "$URL" 2>/dev/null || echo "open ${URL} in a browser"
