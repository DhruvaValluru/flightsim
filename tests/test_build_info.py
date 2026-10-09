"""The server says which checkout it serves (GET /status ``build``).

Measured need (2026-10-09): a feature on one branch was "not there" on a
machine that had cloned the default branch, and the page could not say
which code it was showing. Now it prints branch@commit next to the
compiler state, read from git by the server process itself.
"""

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from webapp.server import app, build_info

REPO = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def test_build_info_is_this_checkouts_branch_and_commit():
    info = build_info()
    assert set(info) == {"branch", "commit"}
    assert info["commit"] == git("rev-parse", "--short", "HEAD")
    assert info["branch"] == git("rev-parse", "--abbrev-ref", "HEAD")


def test_status_carries_the_build_and_the_page_prints_it():
    payload = TestClient(app).get("/status").json()
    assert payload["build"] == build_info()
    page = (REPO / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="buildState"' in page
    assert "status.build" in page
