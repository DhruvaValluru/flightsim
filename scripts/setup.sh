#!/usr/bin/env bash
# One-command setup for the Python side (physics, tests, compiler, web app).
# Rendering additionally needs the Windows host (Unreal Engine 5.7 + the built
# bridge; .\scripts\setup.ps1 there) -- see README 'Platform support'.
set -euo pipefail
cd "$(dirname "$0")/.."

# requirements.txt is the human-edited source; requirements.lock is its hashed
# resolution, made for one Python. --require-hashes installs exactly the bytes
# CI and scripts/deploy_windows.ps1 install, so any other Python stops here
# rather than installing loose.
PINNED_PYTHON=3.12
python=""
for candidate in "python$PINNED_PYTHON" python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       [ "$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "$PINNED_PYTHON" ]; then
        # The real binary: a venv made through a uv-managed symlink cannot
        # find its standard library.
        python="$("$candidate" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
        break
    fi
done
if [ -z "$python" ]; then
    echo "No Python $PINNED_PYTHON found: requirements.lock is pinned to Python $PINNED_PYTHON." >&2
    echo "Install Python $PINNED_PYTHON (for example: brew install python@$PINNED_PYTHON), then re-run this script." >&2
    exit 1
fi

"$python" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install --require-hashes -r requirements.lock

echo
echo "Running the test suite (should be all green)..."
.venv/bin/pytest -q

echo
echo "Setup complete. Start the app with:"
echo "  .venv/bin/uvicorn webapp.server:app --port 8008"
echo "then open http://127.0.0.1:8008"
echo
echo "Optional free local AI compiler:"
echo "  brew install ollama && ollama pull qwen2.5:14b"
echo "  echo 'export FLIGHTSIM_LLM=ollama' >> ~/.flightsim.env"
