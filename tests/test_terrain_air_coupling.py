"""The terrain shapes the air in the headless host, where the aircraft is.

Four couplings, each one a gap measured on phase-2-testing:

* the headless runner never attached the orographic field (ridge lift, lee
  sink) or the lee-rotor turbulence over a raster; only the UE host did, so
  the same spec flew two different mountains;
* a position-coupled field (orographic over a baked raster, surface
  thermals) was sampled in the absolute ``latitude x 111320 m`` frame while
  the run card's blocks are about the spec origin, so thermals sat near
  (0 N, 0 E) whatever the spec's place was;
* a NAMED place with no bake on the machine flew the flat slab, or was moved
  onto the synthesised ridge (0.138 N, 10.649 E for Everest), instead of
  refusing terrain.unbaked the way stated coordinates do;
* Google's tiles could be drawn over the slab or a synthesised raster, so
  the picture showed mountains the aircraft never felt.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from core.environment.base import LocalFrame, Position
from core.nl.compiler import compile_prompt
from core.scenario.fields import Source
from core.terrain.ground import TerrainGround
from core.terrain.heightfield import Georeference, Heightfield

UTM = "EPSG:32633"


def ridge_ground() -> TerrainGround:
    """An east-west ridge 600 m above a 200 m plain, 16 km square in UTM 33N."""
    n, px = 161, 100.0
    rows = np.arange(n)
    z = 200.0 + 600.0 * np.exp(-((rows - 80) * px / 1500.0) ** 2)
    field = Heightfield.from_elevations(
        np.repeat(z[:, None], n, axis=1),
        Georeference(UTM, origin_x_m=400_000.0, origin_y_m=5_000_000.0 + n * px,
                     pixel_size_m=px),
        provenance={"producer": "dem ingestion"})
    return TerrainGround(field)


def spec_over(ground: TerrainGround, prompt: str, south_of_crest_m: float = 6000.0):
    lon0, lat0 = ground.centre_lonlat()
    spec = compile_prompt(prompt)
    spec.set("hold_state", False)
    spec.set("latitude", round(lat0 - south_of_crest_m / 111_320.0, 6))
    spec.set("longitude", round(lon0, 6))
    return spec


def name_place(spec, key: str):
    """What the compiler writes for a NAMED listed place: the place's
    origin, source inferred (core/nl/llm_compiler.py geography rules)."""
    from core.nl.llm_compiler import LOCATION_TERRAIN_ELEVATION_M
    from core.terrain.glo30 import LOCATIONS

    location = LOCATIONS[key]
    for name, value in (("latitude", location.origin_lat),
                        ("longitude", location.origin_lon),
                        ("terrain_elevation", LOCATION_TERRAIN_ELEVATION_M[key])):
        current = getattr(spec, name)
        setattr(spec, name, dataclasses.replace(
            current, value=value, source=Source.INFERRED, frm=f"named {key}"))
    return spec


# -- the local frame ----------------------------------------------------------


def test_local_frame_is_the_projected_offset_from_the_origin():
    from pyproj import Transformer

    frame = LocalFrame(UTM, 45.2, 13.8)
    assert frame.north_east(45.2, 13.8) == pytest.approx((0.0, 0.0), abs=1e-6)
    forward = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
    x0, y0 = forward.transform(13.8, 45.2)
    x1, y1 = forward.transform(13.81, 45.21)
    north, east = frame.north_east(45.21, 13.81)
    assert north == pytest.approx(y1 - y0, abs=1e-6)
    assert east == pytest.approx(x1 - x0, abs=1e-6)


def test_scene_frame_uses_the_raster_crs_over_terrain_and_utm_otherwise():
    from core.scenario.runner import scene_frame_for

    ground = ridge_ground()
    spec = spec_over(ground, "fly the 747 at 3000 m and 250 kt")
    assert scene_frame_for(spec, ground).crs == UTM
    flat = compile_prompt("fly the 747 at 3000 m and 250 kt")
    flat.set("latitude", 36.09)
    flat.set("longitude", -112.0)
    assert scene_frame_for(flat).crs == "EPSG:32612"


# -- the orographic field in the headless stack -------------------------------


def test_calm_air_over_terrain_attaches_no_orographic_field():
    from core.scenario.runner import environment_for

    ground = ridge_ground()
    spec = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360")
    names = [p.name for p in environment_for(spec, terrain_ground=ground).providers]
    assert "orographic" not in names
    assert "lee_rotor_turbulence" not in names


def test_wind_over_terrain_attaches_orographic_and_rotor():
    from core.scenario.runner import environment_for

    ground = ridge_ground()
    spec = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360 "
                             "with 25 kt wind from 180")
    stack = environment_for(spec, terrain_ground=ground)
    names = [p.name for p in stack.providers]
    assert "orographic" in names and "lee_rotor_turbulence" in names
    assert "dryden_turbulence" not in names
    # Without the raster the stack is what it always was.
    plain = [p.name for p in environment_for(spec).providers]
    assert "orographic" not in plain and "lee_rotor_turbulence" not in plain


def test_headless_orographic_uses_the_run_card_s_numbers(tmp_path):
    """One mountain for both hosts: the provider's decay height, wavelength
    and origin are the card block's (core.terrain.glo30)."""
    from core.scenario.runner import orographic_for
    from core.terrain.glo30 import orographic_card_block

    ground = ridge_ground()
    ground.heightfield.write(tmp_path / "ridge")
    spec = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360 "
                             "with 25 kt wind from 180")
    provider = orographic_for(spec, ground)
    block = orographic_card_block(tmp_path / "ridge", float(spec.latitude.value),
                                  float(spec.longitude.value), 25.0, 180)
    assert provider.decay_height_m == pytest.approx(block["decay_height_m"])
    assert provider.terrain.wavelength_m == pytest.approx(block["wavelength_m"])
    assert provider.frame.origin_x_m == pytest.approx(block["origin_x_m"])
    assert provider.frame.origin_y_m == pytest.approx(block["origin_y_m"])
    assert provider.wind_speed_mps == pytest.approx(block["wind_speed_mps"])
    assert provider.wind_from_deg == pytest.approx(block["wind_from_deg"])


def test_orographic_samples_the_raster_where_the_aircraft_is():
    """Windward slope lifts, the lee sinks, at the aircraft's real place on
    the raster (the absolute frame would sample metres nowhere near it)."""
    from core.scenario.runner import orographic_for

    ground = ridge_ground()
    spec = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360 "
                             "with 25 kt wind from 180")
    provider = orographic_for(spec, ground)
    lon0, lat0 = ground.centre_lonlat()

    def w_up(north_of_crest_m: float) -> float:
        lat = lat0 + north_of_crest_m / 111_320.0
        terrain = ground.elevation_at(lat, lon0)
        position = Position(lat, lon0, terrain + 100.0, 100.0, terrain)
        return -provider.wind_at(position, 0.0).down

    assert w_up(-1500.0) > 1.0          # windward (south) slope: lift
    assert w_up(+2500.0) < -0.5         # lee (north) side: sink
    assert abs(w_up(-7500.0)) < 0.05    # the flat plain upstream: nothing


def test_rotor_reads_the_orographic_frame():
    from core.environment.rotor import ROTOR_SIGMA_GAIN, LeeRotorTurbulence
    from core.scenario.runner import orographic_for

    ground = ridge_ground()
    spec = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360 "
                             "with 25 kt wind from 180")
    provider = orographic_for(spec, ground)
    rotor = LeeRotorTurbulence(provider, seed=1)
    lon0, lat0 = ground.centre_lonlat()
    lat = lat0 + 2500.0 / 111_320.0
    position = Position(lat, lon0, 400.0, 150.0, 250.0)
    north, east = provider.frame.north_east(lat, lon0)
    expected = ROTOR_SIGMA_GAIN * provider.lee_sink(north, east) * provider.decay(150.0)
    assert expected > 0.0
    assert rotor.rotor_sigma_w_mps(position) == pytest.approx(expected)


def test_run_spec_over_a_ridge_in_wind_feels_the_vertical_air():
    """The null pair: the same spec over the same raster, calm and in a
    25 kt cross-ridge wind. Calm records no vertical air; the wind records
    lift and sink, and the manifest names the orographic provider."""
    from core.scenario.runner import run_spec

    ground = ridge_ground()
    calm = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360 "
                             "for 40 seconds")
    windy = spec_over(ground, "fly the 747 at 1300 m and 250 kt heading 360 "
                              "for 40 seconds with 25 kt wind from 180")
    still = run_spec(calm, validate_first=False, terrain_ground=ground,
                     assert_closure=False)
    moving = run_spec(windy, validate_first=False, terrain_ground=ground,
                      assert_closure=False)
    assert max(abs(w) for w in still.telemetry.columns["wind_down_mps"]) < 1e-9
    down = moving.telemetry.columns["wind_down_mps"]
    assert min(down) < -0.5 and max(down) > 0.5
    names = [p["name"] for p in moving.manifest["environment"]]
    assert "orographic" in names and "lee_rotor_turbulence" in names


# -- thermals at the spec's place ---------------------------------------------


def test_thermals_are_placed_about_the_spec_origin():
    """A desert run at the Grand Canyon meets its thermals near the origin
    (the absolute frame put them ~4000 km away, at 0 N 0 E)."""
    from core.scenario.runner import environment_for

    spec = compile_prompt("fly the c172p at 2500 m and 100 kt over the desert")
    spec.set("latitude", 36.09)
    spec.set("longitude", -112.0)
    thermals = [p for p in environment_for(spec).wind if p.name == "allen_thermals"]
    assert thermals, "the desert class attaches thermals"
    provider = thermals[0]
    assert provider.frame is not None
    assert provider.frame.origin_lat_deg == pytest.approx(36.09)
    north, east = provider.positions[0]
    lat = 36.09 + north / 111_320.0
    lon = -112.0 + east / (111_320.0 * math.cos(math.radians(36.09)))
    position = Position(lat, lon, 1500.0, 500.0, 1000.0)
    assert -provider.wind_at(position, 0.0).down > 0.1      # inside an updraft


# -- named places hold the bake rule ------------------------------------------


@pytest.fixture
def no_bakes(tmp_path, monkeypatch):
    import webapp.runs as runs

    monkeypatch.setattr(runs, "TERRAIN_DIR", tmp_path / "terrain")
    return runs


@pytest.mark.parametrize("key", ["everest", "grand_canyon"])
def test_a_named_place_without_its_bake_refuses_by_name(no_bakes, key):
    spec = name_place(compile_prompt("fly the a320 at 9500 m and 250 kt"), key)
    refusal = no_bakes.needs_dynamic_bake(spec)
    assert refusal is not None and refusal["constraint"] == "terrain.unbaked"
    assert key in refusal["message"]
    assert f"scripts/bake_terrain.py {key}" in refusal["message"]


def test_a_named_place_is_never_moved_onto_the_synthesised_ridge(no_bakes, monkeypatch):
    spec = name_place(compile_prompt("fly the a320 at 9500 m and 250 kt"), "everest")
    monkeypatch.setattr(no_bakes, "pick_scene",
                        lambda s: {"key": "control", "terrain": "unused"})
    before = (spec.latitude.value, spec.longitude.value)
    no_bakes.place_on_scene(spec)
    assert (spec.latitude.value, spec.longitude.value) == before


def test_bake_on_a_named_place_bakes_the_curated_location(no_bakes, monkeypatch):
    from core.terrain.glo30 import LOCATIONS

    calls = []
    monkeypatch.setattr(no_bakes, "bake", lambda location, cache, out: calls.append(
        (location.key, out)))
    import core.terrain.imagery as imagery

    monkeypatch.setattr(imagery, "drape", lambda *a: (None, None))
    everest = LOCATIONS["everest"]
    entry = no_bakes.bake_on_demand(everest.origin_lat, everest.origin_lon)
    assert calls == [("everest", no_bakes.TERRAIN_DIR)]
    assert entry["key"] == "everest" and entry["imagery"] == "draped"


def test_a_staged_place_is_still_not_held_for_a_bake(no_bakes):
    """Scene-setting (source derived) is not a named place: unchanged."""
    spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
    no_bakes.plan_scene_setting(spec)
    assert no_bakes.scene_set(spec)
    assert no_bakes.needs_dynamic_bake(spec) is None


# -- Google tiles only over a real bake ---------------------------------------


def test_google_tiles_refuse_over_the_slab_and_synthesised_terrain(monkeypatch):
    from core.scenario.card import google_tiles_terrain_refusal
    from core.terrain.synthesis import generate

    synthetic = generate(size=32, pixel_size_m=30.0, seed=1, name="synthetic")
    real = ridge_ground().heightfield
    monkeypatch.delenv("FLIGHTSIM_GOOGLE_TILES", raising=False)
    assert google_tiles_terrain_refusal(None) is None
    assert google_tiles_terrain_refusal(synthetic) is None
    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "on")
    assert "flat slab" in google_tiles_terrain_refusal(None)
    assert "not a real elevation bake" in google_tiles_terrain_refusal(synthetic)
    assert google_tiles_terrain_refusal(real) is None


def test_the_render_flow_and_the_cli_carry_the_google_tiles_refusal():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for path in (repo / "webapp" / "runs.py", repo / "flightsim" / "capture.py"):
        text = path.read_text(encoding="utf-8")
        assert "google_tiles_terrain_refusal(" in text, path
        assert ("GOOGLE_TILES_TERRAIN_CONSTRAINT" in text
                or '"google_tiles.terrain"' in text), path


# -- the stated wind direction ------------------------------------------------


@pytest.mark.parametrize("prompt,speed,direction", [
    ("fly the 747 heading 360 with 20 kt wind from 270", 20.0, 270.0),
    ("fly the 747 heading 360 with wind from 270 at 20 kt", 20.0, 270.0),
    ("fly the 747 heading 090 with a 15 kt wind out of the 045", 15.0, 45.0),
    ("fly the 747 heading 090 with winds from 300 degrees at 10 kts", 10.0, 300.0),
])
def test_the_stated_wind_direction_is_read(prompt, speed, direction):
    spec = compile_prompt(prompt)
    assert float(spec.wind_speed.value) == speed
    assert float(spec.wind_direction.value) == direction
    assert str(spec.wind_direction.source) == "user"


def test_a_relative_wind_word_still_follows_the_heading():
    spec = compile_prompt("fly the 747 heading 090 with a 20 kt crosswind")
    assert float(spec.wind_direction.value) == 180.0
    assert str(spec.wind_direction.source) == "inferred"


def test_google_tiles_accept_the_slab_only_on_an_open_ocean_point(monkeypatch):
    """Over open ocean the sea surface IS the flat slab at 0 m: the tiles
    and the physics ground are the same place (core.terrain.ocean)."""
    from core.scenario.card import google_tiles_terrain_refusal
    from core.terrain.ocean import OPEN_OCEAN

    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "on")
    for point in OPEN_OCEAN.values():
        assert google_tiles_terrain_refusal(None, point.lat, point.lon, 0.0) is None
    atlantic = OPEN_OCEAN["atlantic"]
    # Raised datum, or a point off the list (the Gulf of Guinea's 0, 0
    # default and Kansas alike), still refuses.
    assert "flat slab" in google_tiles_terrain_refusal(None, atlantic.lat, atlantic.lon, 400.0)
    assert "flat slab" in google_tiles_terrain_refusal(None, 0.0, 0.0, 0.0)
    assert "flat slab" in google_tiles_terrain_refusal(None, 38.4, -96.5, 0.0)


def test_a_vague_ocean_prompt_is_staged_at_a_real_open_ocean(no_bakes, monkeypatch):
    from core.terrain.ocean import OPEN_OCEAN

    monkeypatch.setenv("FLIGHTSIM_GOOGLE_TILES", "on")
    spec = compile_prompt("fly the 747 over the ocean while it is raining")
    no_bakes.plan_scene_setting(spec)
    assert (spec.latitude.value, spec.longitude.value) == (OPEN_OCEAN["atlantic"].lat,
                                                           OPEN_OCEAN["atlantic"].lon)
    assert str(spec.surface.value) == "ocean"
    assert no_bakes.needs_dynamic_bake(spec) is None       # staged, not named
    scene = no_bakes.pick_scene(spec)
    assert scene["terrain"] is None and "open North Atlantic" in scene["label"]
    pacific = compile_prompt("fly the a320 over the pacific ocean")
    no_bakes.plan_scene_setting(pacific)
    assert pacific.longitude.value == OPEN_OCEAN["pacific"].lon
    # A place the prompt states still wins.
    named = compile_prompt("fly the 747 over the ocean at 3000 m")
    named.set("latitude", 21.3, frm="stated")
    named.set("longitude", -157.9, frm="stated")
    no_bakes.plan_scene_setting(named)
    assert named.latitude.value == 21.3

