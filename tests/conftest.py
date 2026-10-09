import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Pinned render commands and scenes must not change because the X-Plane
# extraction is committed (webapp.runs.xplane_lighting_flags,
# attach_xplane_drape); the X-Plane tests switch them on themselves.
os.environ.setdefault("FLIGHTSIM_XPLANE_LIGHTING", "off")
os.environ.setdefault("FLIGHTSIM_XPLANE_TERRAIN", "off")
# Place names resolve from the built-in list only: no test may reach
# OpenStreetMap (core/nl/geocode.py; tests/test_geocode.py fakes it).
os.environ.setdefault("FLIGHTSIM_GEOCODER", "offline")
# A compile naming a place must not start a terrain download in the
# background (webapp.runs.TerrainPrefetch); tests/test_terrain_prefetch.py
# switches it on with a stubbed bake.
os.environ.setdefault("FLIGHTSIM_TERRAIN_PREFETCH", "off")
# Google's tiles are the ground of every terrain render (the owner's rule,
# 2026-10-09: on by default on both sides); the suite has no key, no Cesium
# plugin, no bakes and no network, so it runs with them off. A test of the
# default deletes the variable (monkeypatch.delenv) and sees them on.
os.environ.setdefault("FLIGHTSIM_GOOGLE_TILES", "off")

from core.util.platform import ue_available  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ue_host: requires a built UE host (Windows is the render "
        "platform; see README 'Platform support')")


def pytest_runtest_setup(item):
    # The suite policy (Part B): green on every OS, with engine-only
    # coverage SKIPPING VISIBLY under this one named reason -- never
    # deleted, never loosened, never ad-hoc ifs.
    if item.get_closest_marker("ue_host") and not ue_available():
        pytest.skip("requires a built UE host (README 'Platform support')")


@pytest.fixture(autouse=True)
def _measured_render_quality(monkeypatch):
    # The render-command pins (camera, quality, sun flags) describe the
    # MEASURED configuration, so the suite runs under it: measure quality
    # and the legacy sky, whatever the app's defaults (beauty, physical)
    # or a developer's own environment say. Tests that want the defaults
    # delete these themselves.
    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    monkeypatch.setenv("FLIGHTSIM_SKY", "legacy")
