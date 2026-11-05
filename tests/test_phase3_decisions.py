"""The code matches the decision log.

docs/phase3/decisions.md is the one place an owner call is recorded. These
tests pin the live values to it, so a pin or a default cannot drift from the
record without a test going red. The latest decision on a subject wins.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "docs" / "phase3" / "decisions.md"


def _decisions() -> str:
    if not DECISIONS.exists():
        pytest.skip("no decisions.md yet")
    return DECISIONS.read_text(encoding="utf-8")


def latest_engine_pin() -> str:
    """The last 'engine pin: X' in the log, numbered decisions only."""
    pins = re.findall(r"^\d+\.\s+\*\*[^*]*engine pin:\s*([0-9]+\.[0-9]+)", _decisions(), re.M)
    assert pins, "decisions.md records no engine pin"
    return pins[-1]


def test_toolchain_engine_matches_latest_pin_decision():
    tc = json.loads((ROOT / "toolchain.json").read_text(encoding="utf-8"))
    assert tc["engine"]["version"] == latest_engine_pin()


def test_google_tiles_default_on(monkeypatch):
    monkeypatch.delenv("FLIGHTSIM_GOOGLE_TILES", raising=False)
    from core.scenario import card
    assert card.google_tiles_requested(), "CLAUDE.md and decision 5: tiles are on unless FLIGHTSIM_GOOGLE_TILES=off"


def test_storm_weather_default_on(monkeypatch):
    monkeypatch.delenv("FLIGHTSIM_WEATHER_BACKEND", raising=False)
    from webapp import runs
    flags = runs.weather_backend_flags()
    assert flags, "CLAUDE.md and decision 4: the web app sends the storm weather by default"
    assert not any("off" in f for f in flags), flags


def test_control_surfaces_out_of_scope_recorded():
    assert re.search(r"control surfaces.*out of phase 3", _decisions(), re.I | re.S)
