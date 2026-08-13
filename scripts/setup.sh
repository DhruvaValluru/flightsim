#!/usr/bin/env bash
# One-command setup for the Python side (physics, tests, compiler, web app).
# Rendering additionally needs a Mac with Unreal Engine 5.5 -- see README.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

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
