#!/usr/bin/env bash
# Open the three Phase 3 progress windows on a Mac (Terminal.app).
# 1 progress bars · 2 Mac command stream · 3 Windows stream + messages.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
for mode in progress mac windows; do
  osascript -e "tell application \"Terminal\" to do script \"cd '$REPO' && python3 scripts/phase3_monitor.py $mode\""
done
