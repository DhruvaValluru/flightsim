import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.util.platform import is_mac  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "mac_ue: requires the macOS UE host (rendered clips are "
        "macOS-only; see README 'Platform support')")


def pytest_runtest_setup(item):
    # The suite policy (Part B): green on every OS, with mac-only
    # coverage SKIPPING VISIBLY under this one named reason -- never
    # deleted, never loosened, never ad-hoc ifs.
    if item.get_closest_marker("mac_ue") and not is_mac():
        pytest.skip("requires macOS UE host (README 'Platform support')")
