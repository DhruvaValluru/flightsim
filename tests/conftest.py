import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.util.platform import ue_available  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "mac_ue: requires a UE host (an installed Unreal editor -- the "
        "capability gate, not the OS name; see README 'Platform support')")


def pytest_runtest_setup(item):
    # The suite policy (Part B): green on every OS, with UE-host
    # coverage SKIPPING VISIBLY under this one named reason -- never
    # deleted, never loosened, never ad-hoc ifs. The gate is the same
    # capability check the webapp refuses with: is an editor actually
    # here (found, not assumed from the OS name).
    if item.get_closest_marker("mac_ue") and not ue_available():
        pytest.skip("requires an installed Unreal editor "
                    "(README 'Platform support')")
