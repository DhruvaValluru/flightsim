import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Pinned render commands must not depend on whether this machine has an
# X-Plane extraction (webapp.runs.xplane_lighting_flags); the X-Plane
# tests pass their own tables.
os.environ.setdefault("FLIGHTSIM_XPLANE_LIGHTING", "off")

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
