"""Every bridge C++ file has balanced braces once comments and literals are
stripped: a merge that leaves one '}' too many (round 8, lane D, 562d806e)
broke the Windows build; this catches it on the Mac, before a build."""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "ue" / "Plugins"
FILES = sorted(p for p in SOURCE.rglob("*") if p.suffix in (".cpp", ".h") and "ThirdParty" not in p.parts)


def _strip(text):
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r'R"\((.*?)\)"', '""', text, flags=re.S)
    text = re.sub(r'"(\\.|[^"\\\n])*"', '""', text)
    return re.sub(r"'(\\.|[^'\\\n])'", "''", text)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_braces_balance(path):
    depth = lowest = 0
    for ch in _strip(path.read_text(encoding="utf-8", errors="replace")):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            lowest = min(lowest, depth)
    assert depth == 0 and lowest == 0, f"{path.name}: depth ends at {depth}, dips to {lowest}"
