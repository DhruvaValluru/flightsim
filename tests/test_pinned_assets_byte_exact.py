"""Every text asset whose bytes a sha256 pin covers is checked out byte-exact
on Windows: git must not rewrite its line ends (round 5, f7232cc7)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _pinned_files():
    film = json.loads((ROOT / "assets/looks/film/film_luts.json").read_text(encoding="utf-8"))
    rows = film["luts"]
    paths = ["assets/looks/film/film_luts.json",
             "assets/looks/physically_based/materials.json",
             "assets/looks/physically_based/PIN.json",
             "assets/looks/physically_based/LICENSE"]
    paths += [str(p.relative_to(ROOT)) for p in (ROOT / "assets/looks/film").glob("*.cube")]
    paths += [str(p.relative_to(ROOT)) for p in (ROOT / "assets/aircraft_config/look").glob("*.json")]
    assert rows, "film_luts.json lists its stocks"
    return paths


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_pinned_text_assets_are_never_eol_converted():
    paths = _pinned_files()
    out = subprocess.run(["git", "check-attr", "text", "eol", "--", *paths], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    converted = [line for line in out.splitlines()
                 if line.endswith("text: set") or line.endswith("text: auto")
                 or (": eol: " in line and not line.endswith("unspecified"))]
    assert not converted, "pinned assets git may rewrite on checkout:\n" + "\n".join(converted)


def test_pinned_text_assets_are_committed_with_lf():
    for rel in _pinned_files():
        assert b"\r\n" not in (ROOT / rel).read_bytes(), rel
