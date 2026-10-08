"""A vague prompt lands somewhere real, and the place decides the ground.

The language model may CHOOSE a place for a prompt that names none
("over the ocean", "over a jungle"); the GLO-30 land mask checks the
kind of place offline. Open ocean flies the flat slab at sea level (no
bake exists or is needed); land is held to the bake rule, which the page
answers with the on-demand bake.
"""

import hashlib
import json

import pytest

from core.nl.llm_compiler import compile_prompt_llm
from core.terrain import landmask
from tests.test_llm_compiler import entry, fake_client


def _pick(prompt, lat, lon, frm, **extra):
    fields = {"latitude": entry(lat, "model", frm), "longitude": entry(lon, "model", frm)}
    fields.update(extra)
    return compile_prompt_llm(prompt, client=fake_client(
        {"fields": fields, "notes": [], "questions": []})).spec


# -- the mask -----------------------------------------------------------------

def test_the_mask_is_what_its_sidecar_records():
    text = landmask.MASK_PATH.read_bytes()
    sidecar = json.loads(landmask.SIDECAR_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(text).hexdigest() == sidecar["mask_sha256"]
    assert len(landmask.land_cells()) == sidecar["land_cells"] == 26450


@pytest.mark.parametrize("lat, lon, land, ocean", [
    (45.98, 7.66, True, False),        # the Matterhorn
    (38.4, -96.5, True, False),        # Kansas
    (21.3, -157.9, True, False),       # Oahu
    (35.0, -45.0, False, True),        # the open North Atlantic
    (30.0, -150.0, False, True),       # the open North Pacific
    (-20.0, 75.0, False, True),        # the open Indian Ocean
    (-35.0, 179.9, False, True),       # beside the antimeridian
])
def test_known_places_read_as_land_or_open_ocean(lat, lon, land, ocean):
    assert landmask.has_land(lat, lon) is land
    assert landmask.open_ocean(lat, lon) is ocean


# -- the model's choice ---------------------------------------------------------

def test_an_ocean_prompt_keeps_an_open_ocean_pick_at_sea_level():
    spec = _pick("fly the 747 over the ocean", 40.0, -35.0, "over the ocean",
                 surface=entry("ocean", "inferred", "ocean"),
                 terrain_elevation=entry(150.0, "model", "over the ocean"))
    assert (spec.latitude.value, spec.longitude.value) == (40.0, -35.0)
    assert str(spec.latitude.source) == "model"
    assert float(spec.terrain_elevation.value) == 0.0      # sea level, not a guess


def test_an_ocean_prompt_drops_a_pick_on_or_near_land():
    spec = _pick("fly the 747 over the ocean", 21.3, -157.9, "over the ocean")
    assert str(spec.latitude.source) == "default"
    assert any("not open ocean" in note for note in spec.notes)


def test_a_land_prompt_keeps_a_land_pick_and_drops_a_sea_one():
    jungle = _pick("fly the c172p over a jungle", -3.4, -62.0, "over a jungle")
    assert (jungle.latitude.value, jungle.longitude.value) == (-3.4, -62.0)
    wet = _pick("fly the c172p over a jungle", 35.0, -45.0, "over a jungle")
    assert str(wet.latitude.source) == "default"
    assert any("no GLO-30 land" in note for note in wet.notes)


def test_a_pick_must_quote_scenery_the_prompt_asked_for():
    """Measured: the model staged "fly a 747" in the Sahara. A guess whose
    phrase names no kind of place, or is not in the prompt, is dropped."""
    placeless = _pick("fly the 747 at 3000 m", 23.0, 5.0, "747")
    assert str(placeless.latitude.source) == "default"
    assert any("names no kind of place" in note for note in placeless.notes)
    misquoted = _pick("fly the 747 at 3000 m", 23.0, 5.0, "over the desert")
    assert str(misquoted.latitude.source) == "default"


# -- the ground the place earns ---------------------------------------------------

@pytest.fixture
def runs(tmp_path, monkeypatch):
    import webapp.runs as runs_module

    monkeypatch.setattr(runs_module, "TERRAIN_DIR", tmp_path / "terrain")
    return runs_module


def test_open_ocean_needs_no_bake_and_the_tiles_accept_it(runs, monkeypatch):
    from core.scenario.card import google_tiles_terrain_refusal

    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "on")
    spec = _pick("fly the 747 over the ocean", 40.0, -35.0, "over the ocean")
    assert runs.needs_dynamic_bake(spec) is None
    scene = runs.pick_scene(spec)
    assert scene["terrain"] is None and "open ocean at 40.000, -35.000" in scene["label"]
    assert google_tiles_terrain_refusal(None, *runs._chosen_origin(spec)) is None


def test_a_land_pick_is_held_to_the_bake_rule(runs):
    """The page answers terrain.unbaked with POST /bake and runs again."""
    spec = _pick("fly the c172p over a jungle", -3.4, -62.0, "over a jungle")
    refusal = runs.needs_dynamic_bake(spec)
    assert refusal["constraint"] == "terrain.unbaked"
    assert (refusal["latitude"], refusal["longitude"]) == (-3.4, -62.0)


def test_the_default_origin_is_not_an_ocean_scene(runs, monkeypatch):
    """0, 0 is open water, but it is "no geography requested", not a place:
    a flat-ground prompt is never relabelled as the ocean."""
    from core.nl.compiler import compile_prompt
    from core.scenario.card import google_tiles_terrain_refusal

    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "on")
    spec = compile_prompt("fly the 747 over flat ground at 3000 m")
    assert not runs.open_ocean_scene(spec)
    assert "open ocean" not in runs.pick_scene(spec)["label"]
    assert google_tiles_terrain_refusal(None, *runs._chosen_origin(spec)) is not None
