"""Place words to coordinates (core/nl/geocode.py), through to real terrain.

The suite runs with FLIGHTSIM_GEOCODER=offline (conftest): the built-in
list answers, and OpenStreetMap is exercised only through a fake fetch,
so no test touches the network.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.nl import geocode
from core.nl.compiler import compile_prompt
from core.nl.llm_compiler import compile_prompt_llm
from core.scenario.altitude_guide import CHECKPOINTS_AGL, ask_for, guide
from core.scenario.validate import MIN_CLEARANCE_M, validate


# -- the built-in list ------------------------------------------------------

def test_list_finds_a_city_after_a_location_word():
    place = geocode.lookup_list("a c172p over new york at 500 m")
    assert place.name == "New York City"
    assert (place.latitude, place.longitude) == (40.7128, -74.0060)
    assert place.elevation_m == 10.0
    assert place.source == geocode.SOURCE_LIST
    assert place.phrase == "new york"


def test_list_needs_a_location_word():
    assert geocode.lookup_list("a Boston terrier on the runway") is None


def test_longest_name_wins_at_one_position():
    assert geocode.lookup_list("over new york city").phrase == "new york city"
    assert geocode.lookup_list("near the sydney opera house").name == \
        "Sydney Opera House"


def test_first_place_named_is_the_flight_origin():
    assert geocode.lookup_list("fly from boston to chicago").name == "Boston"


def test_a_qualified_name_is_left_to_openstreetmap():
    # "Paris, Texas" is not Paris, France.
    assert geocode.lookup_list("over Paris, Texas at 500 m") is None
    assert geocode.candidate_phrases("over Paris, Texas at 500 m") == \
        ["Paris, Texas"]


def test_skip_keeps_curated_words_out():
    assert geocode.lookup_list("over denver", skip=["denver"]) is None


def test_every_list_entry_is_a_real_coordinate():
    for name, lat, lon, elev, country, aliases in geocode.GAZETTEER:
        assert -90 <= lat <= 90 and -180 <= lon <= 180, name
        assert -500 <= elev <= 9000, name
        assert country, name


# -- free-text candidates ----------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "simulate a plane in rough wind conditions over mountains",
    "chase view to the right over the ocean in heavy turbulence",
    "fly the 747 at 9000 m and 250 kt",
    "in a thunderstorm at dusk",
    "fly over the c172p",
])
def test_scenery_and_weather_are_not_places(prompt):
    assert geocode.candidate_phrases(prompt) == []


def test_no_conditions_list_phrase_is_sent_to_openstreetmap():
    """Every phrase the page's conditions list adds to a prompt is either
    a curated place (resolved before any lookup) or not a place at all."""
    import re

    from core.nl.compiler import PLACE_WORDS

    source = (Path(__file__).resolve().parents[1] / "webapp" / "static" /
              "conditions_list.js").read_text(encoding="utf-8")
    phrases = re.findall(r'\["[^"]+",\s*"([^"]+)"\]', source)
    assert phrases
    curated = {p for p, _ in PLACE_WORDS}
    for phrase in phrases:
        prompt = f"fly the c172p {phrase}"
        assert geocode.lookup_list(prompt) is None, phrase
        for candidate in geocode.candidate_phrases(prompt):
            assert candidate.lower() in curated, (phrase, candidate)


def test_candidates_stop_at_the_next_clause_and_prefer_strong_words():
    assert geocode.candidate_phrases(
        "take off from springfield and fly over tulsa at 1000 ft") == \
        ["tulsa", "springfield"]


# -- OpenStreetMap, through a fake fetch --------------------------------------

def _hit(lat="36.15", lon="-95.99", importance=0.6, category="place",
         name="Tulsa, Oklahoma, United States"):
    return {"lat": lat, "lon": lon, "importance": importance,
            "category": category, "type": "city", "display_name": name}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path / "geocode_cache.json"
    monkeypatch.setenv(geocode.CACHE_ENV, str(path))
    return path


def test_online_hit_is_used_and_cached(cache):
    calls = []

    def fetch(query):
        calls.append(query)
        return [_hit()]

    place = geocode.lookup_online("tulsa", fetch=fetch)
    assert (place.latitude, place.longitude) == (36.15, -95.99)
    assert place.source == geocode.SOURCE_OSM
    assert place.elevation_m is None
    assert place.display.startswith("Tulsa")
    # Second time: from the cache, no request.
    again = geocode.lookup_online("Tulsa", fetch=fetch)
    assert (again.latitude, again.longitude) == (36.15, -95.99)
    assert calls == ["tulsa"]
    assert "tulsa" in json.loads(cache.read_text(encoding="utf-8"))


def test_obscure_or_non_geographic_hits_are_refused(cache):
    assert geocode.lookup_online(
        "heavy", fetch=lambda q: [_hit(importance=0.1)]) is None
    assert geocode.lookup_online(
        "pizza", fetch=lambda q: [_hit(category="amenity")]) is None
    # The refusal is cached too: the same words never re-query.
    assert json.loads(cache.read_text(encoding="utf-8"))["heavy"] is None


def test_network_failure_is_no_place_not_an_error(cache):
    def fetch(query):
        raise OSError("blocked")

    assert geocode.lookup_online("tulsa", fetch=fetch) is None
    # A failure is not cached: the next compile may be online.
    assert not cache.exists() or "tulsa" not in json.loads(cache.read_text(encoding="utf-8"))


def test_modes(cache, monkeypatch):
    calls = []

    def fetch(query):
        calls.append(query)
        return [_hit()]

    monkeypatch.setenv(geocode.GEOCODER_ENV, "off")
    assert geocode.find_place("over new york", fetch=fetch) is None
    monkeypatch.setenv(geocode.GEOCODER_ENV, "offline")
    assert geocode.find_place("over tulsa", fetch=fetch) is None
    assert calls == []
    monkeypatch.setenv(geocode.GEOCODER_ENV, "auto")
    # The list answers first, without a request ...
    assert geocode.find_place("over new york", fetch=fetch).name == \
        "New York City"
    assert calls == []
    # ... and OpenStreetMap answers what the list lacks.
    assert geocode.find_place("over tulsa", fetch=fetch).name == "Tulsa"
    assert calls == ["tulsa"]


# -- the compilers -----------------------------------------------------------

def test_regex_compiler_puts_a_named_city_on_the_spec():
    spec = compile_prompt("a c172p over new york at 500 m")
    assert str(spec.latitude.source) == "inferred"
    assert float(spec.latitude.value) == 40.7128
    assert float(spec.longitude.value) == -74.0060
    assert "new york" in spec.latitude.frm
    assert float(spec.terrain_elevation.value) == 10.0
    assert str(spec.terrain_elevation.source) == "inferred"
    # The stated altitude is the user's, never moved.
    assert float(spec.altitude.value) == 500.0
    assert str(spec.altitude.source) == "user"
    assert any("New York City" in note for note in spec.notes)


def test_curated_places_still_win():
    spec = compile_prompt("over the matterhorn")
    assert "matterhorn bake" in spec.latitude.frm
    assert not any("built-in place list" in note for note in spec.notes)


def test_a_longer_listed_name_beats_the_curated_word_inside_it():
    spec = compile_prompt("over kansas city")
    assert float(spec.latitude.value) == 39.0997       # not the Flint Hills


def test_mountains_near_a_named_place_are_that_place():
    spec = compile_prompt("mountains near denver")
    assert float(spec.latitude.value) == 39.7392
    assert float(spec.terrain_elevation.value) == 1609.0
    # Real terrain, not the synthesised ridge.
    assert str(spec.scene.terrain_source.value) == "auto"


def test_the_ground_height_makes_a_low_altitude_a_named_refusal():
    """'at 1000 m over Denver' is underground: refused by name before
    anything flies (what the altitude guide warns about)."""
    spec = compile_prompt("a c172p over denver at 1000 m")
    constraints = {v.constraint for v in validate(spec).violations}
    assert "altitude.terrain_clearance" in constraints


def _fake_llm(payload):
    text = json.dumps(payload)
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                               stop_reason="end_turn", model="claude-opus-5")

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.captured = captured
    return client


def test_llm_compiler_is_told_the_place_and_never_asks_for_it():
    client = _fake_llm({
        "fields": {}, "notes": [],
        "questions": [{"id": "location",
                       "question": "Where should the flight take place?",
                       "options": ["matterhorn", "a generic ridge"]}],
    })
    result = compile_prompt_llm("fly a cessna over new york", client=client)
    assert "40.7128" in client.captured["system"]
    assert float(result.spec.latitude.value) == 40.7128
    assert str(result.spec.latitude.source) == "inferred"
    assert not result.questions


def test_llm_compiler_that_sets_the_place_and_still_asks_is_not_asked():
    client = _fake_llm({
        "fields": {"latitude": {"value": 40.7128, "source": "inferred",
                                "from": "new york"},
                   "longitude": {"value": -74.006, "source": "inferred",
                                 "from": "new york"}},
        "notes": [],
        "questions": [{"id": "where", "question": "Which part of New York?",
                       "options": ["Manhattan", "Brooklyn"]}],
    })
    result = compile_prompt_llm("fly a cessna over new york", client=client)
    assert float(result.spec.latitude.value) == 40.7128
    assert not result.questions


def test_llm_compiler_keeps_stated_coordinates():
    client = _fake_llm({
        "fields": {"latitude": {"value": 51.5, "source": "user", "from": "51.5"},
                   "longitude": {"value": -0.1, "source": "user", "from": "-0.1"}},
        "notes": [], "questions": [],
    })
    result = compile_prompt_llm("fly at 51.5, -0.1 near new york", client=client)
    assert float(result.spec.latitude.value) == 51.5


# -- the terrain and its physics -----------------------------------------------

def test_a_looked_up_place_is_baked_then_flown_over_real_terrain(
        tmp_path, monkeypatch):
    """Unbaked: /run's check refuses terrain.unbaked (the page bakes and
    runs again). Baked (stubbed here with a small raster at the place):
    the scene is the on-demand bake, the ground model reads it under the
    aircraft, and wind over it makes the orographic lift/sink provider."""
    import webapp.runs as runs
    from core.terrain.glo30 import dynamic_location
    from core.terrain.ground import TerrainGround
    from core.terrain.heightfield import Heightfield
    from core.terrain.synthesis import ridge_for_origin

    monkeypatch.setattr(runs, "TERRAIN_DIR", tmp_path / "terrain")
    spec = compile_prompt("a c172p over new york at 1500 m in 25 kt wind")
    assert float(spec.wind_speed.value) > 0
    assert runs.names_real_place(spec)
    refusal = runs.needs_dynamic_bake(spec)
    assert refusal["constraint"] == "terrain.unbaked"
    assert "place the prompt names" in refusal["message"]
    assert refusal["latitude"] == 40.7128

    # What bake_on_demand writes, with a small synthesised raster standing
    # in for the downloaded GLO-30 tiles (no network in the suite).
    location = dynamic_location(40.7128, -74.0060)
    dynamic = tmp_path / "terrain" / "dynamic"
    ridge_for_origin(40.7128, -74.0060, name=location.key,
                     size=64).write(dynamic / location.key)
    (dynamic / f"{location.key}.scene.json").write_text(json.dumps({
        "key": location.key, "title": location.title,
        "origin_lat": location.origin_lat, "origin_lon": location.origin_lon,
        "crs": location.crs, "identity": "source-verified only"}),
        encoding="utf-8")

    assert runs.needs_dynamic_bake(spec) is None
    scene = runs.pick_scene(spec)
    assert "on-demand bake" in scene["kind"]
    ground = TerrainGround(Heightfield.read(Path(scene["terrain"])))
    assert ground.contains(40.7128, -74.0060)
    assert runs._orographic_provider(spec, scene) is not None


def test_curated_inferred_coordinates_keep_their_own_behaviour(tmp_path,
                                                               monkeypatch):
    import webapp.runs as runs

    monkeypatch.setattr(runs, "TERRAIN_DIR", tmp_path / "terrain")
    spec = compile_prompt("over the matterhorn")
    assert not runs.names_real_place(spec)
    assert runs.needs_dynamic_bake(spec) is None


# -- the altitude guide --------------------------------------------------------

def test_ask_for_never_falls_below_the_checkpoint():
    for ground in (0.0, 10.0, 413.0, 1609.0, 4720.0):
        for point in CHECKPOINTS_AGL:
            asked = ask_for(point["agl_m"], ground)
            assert asked >= ground + point["agl_m"]
            assert asked - (ground + point["agl_m"]) < 100.0
            feet = ask_for(point["agl_m"], ground, unit="ft")
            assert feet * 0.3048 >= ground + point["agl_m"] - 1e-6


def test_guide_checkpoints_climb_and_carry_the_validator_floor():
    data = guide(1609.0)
    heights = [c["agl_m"] for c in data["checkpoints"]]
    assert heights == sorted(heights)
    assert data["checkpoints"][0]["ask_m"] == 1700.0
    assert data["min_clearance_m"] == MIN_CLEARANCE_M
    assert {"c172p", "B747", "A320"} <= set(data["aircraft"])


def test_guide_endpoint_and_page():
    from webapp.server import app

    client = TestClient(app)
    response = client.get("/altitude-guide", params={"ground_m": 1609})
    assert response.status_code == 200
    assert response.json()["ground_m"] == 1609.0
    assert client.get("/altitude-guide",
                      params={"ground_m": 99999}).status_code == 400
    page = client.get("/").text
    assert 'id="altGuide"' in page and "/altitude-guide" in page
