#!/usr/bin/env bash
# Open ruflo's live views in separate Terminal.app windows (Mac), read-only:
#   1 system status (watch)        2 swarm: topology, agents, tasks
#   3 processes and daemon workers 4 daemon log (follow)
#   5 shared memory, namespace "visual" (the overhaul's probe records)
# Each window only displays local state; nothing here polls a PR or CI.
# Close a window (or Ctrl-C in it) to stop it.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
RF="npx -y ruflo@3.74.1"
open_window() {  # title, command
  osascript -e "tell application \"Terminal\" to do script \"printf '\\\\e]0;$1\\\\a'; cd '$REPO' && $2\""
}
open_window "ruflo status" "$RF status --watch -i 5"
open_window "ruflo swarm" "while true; do clear; $RF swarm status; $RF agent list 2>/dev/null; $RF task list 2>/dev/null; sleep 10; done"
open_window "ruflo processes" "$RF process monitor --watch"
open_window "ruflo daemon log" "tail -n 200 -f .claude-flow/daemon.log"
open_window "ruflo memory (visual)" "while true; do clear; $RF memory list --namespace visual; sleep 30; done"
