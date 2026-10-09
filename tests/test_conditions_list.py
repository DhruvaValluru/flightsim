"""The conditions list (webapp/static/conditions_list.js): the clickable
weather and environment phrases beside both prompt boxes.

The list is only honest while every phrase it offers is one the offline
compiler turns into a stated spec field; a phrase that compiled to nothing
would be a condition advertised and silently dropped. Each phrase is
compiled here and must move at least one field off the bare prompt's
value. Both pages must mount the list, and the server must serve it.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.nl.compiler import compile_prompt
from webapp.server import app

STATIC = Path(__file__).resolve().parents[1] / "webapp" / "static"
SCRIPT = (STATIC / "conditions_list.js").read_text(encoding="utf-8")
BASE_PROMPT = "fly the c172p at 1500 m and 100 kt"


def _groups_block() -> str:
    match = re.search(r"const GROUPS = \[(.*?)\n\];", SCRIPT, re.S)
    assert match, "GROUPS missing from conditions_list.js"
    return match.group(1)


PHRASES = re.findall(r'\["[^"]+", "([^"]+)"\]', _groups_block())


def _flat(data, prefix=""):
    out = {}
    for key, value in data.items():
        if isinstance(value, dict) and "value" in value and "source" in value:
            out[prefix + key] = value["value"]
        elif isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
    return out


def test_the_list_offers_the_weather_groups():
    titles = re.findall(r'title: "([^"]+)"', _groups_block())
    for title in ("Wind", "Turbulence", "Storms", "Time of day", "Ground below"):
        assert title in titles
    assert len(PHRASES) >= 40


@pytest.mark.parametrize("phrase", PHRASES)
def test_every_phrase_compiles_to_a_stated_condition(phrase):
    base = _flat(compile_prompt(BASE_PROMPT).to_dict())
    spec = _flat(compile_prompt(f"{BASE_PROMPT} {phrase}").to_dict())
    moved = {k for k, v in spec.items() if base.get(k) != v and k != "prompt"}
    assert moved, f"{phrase!r} compiles to no condition"


def test_both_pages_mount_the_list_and_the_server_serves_it():
    for page in ("index.html", "generate.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        assert '<script src="/conditions_list.js"></script>' in html
        assert 'ConditionsList.mount(document.getElementById("conditionsList"), ' \
               'document.getElementById("prompt"))' in html
    response = TestClient(app).get("/conditions_list.js")
    assert response.status_code == 200
    assert "ConditionsList" in response.text
