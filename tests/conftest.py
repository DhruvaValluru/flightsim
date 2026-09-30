import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    # The render-command pins (camera, quality) describe the MEASURED
    # configuration; a developer's own FLIGHTSIM_RENDER_QUALITY=beauty
    # must not turn them red. Tests that want beauty set it themselves.
    monkeypatch.delenv("FLIGHTSIM_RENDER_QUALITY", raising=False)
