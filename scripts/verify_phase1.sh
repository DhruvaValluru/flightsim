#!/usr/bin/env bash
# Camera Phase 1, one command: capture, verify, and run the camera tests.
#
# Everything here runs on macOS, Windows (scripts\verify_phase1.ps1) and
# Linux. Rendered photographic frames need the Windows host (the render
# platform) and are REFUSED BY NAME elsewhere -- that is the designed
# outcome, not a failure. The
# manifests, the geometry previews and every check below are complete on
# any platform.
#
#   ./scripts/verify_phase1.sh [--out runs/demo] [--terrain <bake stem>]
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "No .venv here. Run ./scripts/setup.sh first." >&2
  exit 1
fi

echo "== the camera test suite =="
"$PYTHON" -m pytest tests/test_camera_*.py -q

echo
echo "== capture + verify: alignment, recovery, consistency =="
"$PYTHON" -m flightsim.demo "$@"

echo
echo "== the committed refusal example (expected: REFUSED by name) =="
if "$PYTHON" -m flightsim.capture examples/cameras_refusal.yaml \
      --out runs/refusal_check > /tmp/flightsim_refusal.log 2>&1; then
  echo "FAIL: the refusal example did not refuse" >&2
  exit 1
fi
grep -E "camera\.(terrain_clearance|scene_bounds|hazard_intersection)" \
  /tmp/flightsim_refusal.log || {
    echo "FAIL: refused, but not by a camera constraint" >&2; exit 1; }
echo "  refused by name, as documented"

echo
echo "Phase 1 verification complete."
