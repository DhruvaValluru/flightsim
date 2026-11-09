#!/usr/bin/env bash
# The visual overhaul's four baseline shots: the macOS / Linux twin of
# render_visual_sheet.ps1 (the Windows box is the maintained render host).
#
#     scripts/render_visual_sheet.sh --step v0                 # beauty a b c d + sheet.png
#     scripts/render_visual_sheet.sh --step v0 --skip-render   # compose from existing PNGs
#     scripts/render_visual_sheet.sh --compare v0_before v0    # before/after sheet
#
# Every argument goes to experiments/visual_contact_sheet.py unchanged (read
# its docstring). Composing (--skip-render, --compare, --list) runs anywhere;
# rendering needs the engine half, and off the render host the web app's
# own refusal (ue.platform) is recorded per shot in shots.json rather than
# a picture being faked. --pathtrace refuses by name off Windows in the
# commandlet itself (render.pathtrace).
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3 || true)"
fi
if [ -z "$PYTHON" ]; then
    echo "REFUSED python.venv: no .venv/bin/python and no python3 -- run scripts/setup.sh first"
    exit 3
fi
exec "$PYTHON" experiments/visual_contact_sheet.py "$@"
