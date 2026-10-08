"""The ``lighting`` block: presets, exact sun degrees, brightness and the
engine knobs, from the spec through the look to the commandlet flags.

What is measured here: the block is absent-canonical (a spec that states
none keeps its digest and its render command), precedence is stated >
preset > the look underneath, exact compass degrees reach the commandlet
in its own azimuth convention, out-of-range values refuse by name, the
flags appear only when asked, and the uncompiled C++ parses every flag the
builder emits. What is NOT measured: how a preset looks on screen (the
engine side is uncompiled here, and the preset numbers are uncalibrated
against Gate 6 -- core/scene/lighting.py says so).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.nl.compiler import compile_prompt
from core.render.flags import DEFAULT_LOOK, LIGHTING_FLAGS, lighting_flags, render_flags
from core.scenario.blocks import LightingSpec
from core.scenario.randomization import engine_sun_azimuth
from core.scenario.spec import SPEC9_BLOCKS, ScenarioSpec, spec9_keys_in
from core.scenario.validate import validate
from core.scene import lighting

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
COMMANDLET = BRIDGE / "Private/FlightSimRenderCommandlet.cpp"
SCENE = BRIDGE / "Private/FlightSimVisualScene.cpp"
SCENE_H = BRIDGE / "Public/FlightSimVisualScene.h"


def plain_spec() -> ScenarioSpec:
    return compile_prompt("fly the 747 at 3000 m and 250 kt for 20 seconds")


def flags_for(look):
    return render_flags("card.json", "frames", scene=None, mesh=None, look=look,
                        camera_flags=None, width=1280, height=720, fps=30)


# -- the block ------------------------------------------------------------------

def test_an_unstated_block_is_absent_and_changes_nothing():
    import webapp.runs as runs

    spec = plain_spec()
    assert spec.lighting.is_default()
    assert "lighting" not in spec.to_dict()
    # The page's dict always carries the block; reading a default one back
    # is the same spec, same digest.
    data = spec.to_dict()
    data["lighting"] = LightingSpec.defaulted().to_dict()
    assert ScenarioSpec.from_dict(data).digest() == spec.digest()
    # And the render command is the one built before the block existed.
    assert runs.lighting_look(spec) is None
    assert runs.render_look_for(spec, None) is None
    assert flags_for(runs.render_look_for(spec, None)) == flags_for(None)


def test_a_stated_block_round_trips_moves_the_digest_and_is_a_version_9_key():
    spec = plain_spec()
    before = spec.digest()
    spec.set("lighting.preset", "golden_hour")
    spec.set("lighting.sun_azimuth_deg", 250.0)
    data = spec.to_dict()
    assert data["lighting"]["preset"]["value"] == "golden_hour"
    assert "lighting" in SPEC9_BLOCKS and "lighting" in spec9_keys_in(data)
    again = ScenarioSpec.from_dict(data)
    assert again.lighting.sun_azimuth_deg.value == 250.0
    assert str(again.lighting.preset.source) == "user"
    assert again.digest() == spec.digest() != before
    assert "lighting" in spec.render_table()


def test_out_of_range_values_and_unknown_presets_refuse_by_name():
    spec = plain_spec()
    spec.set("lighting.preset", "disco")
    spec.set("lighting.sun_elevation_deg", 1.0)        # under the render floor
    spec.set("lighting.color_temperature_k", 50000.0)
    found = {v.constraint for v in validate(spec, check_feasibility=False).violations}
    assert {"lighting.preset", "lighting.range"} <= found
    messages = [v.message for v in validate(spec, check_feasibility=False).violations
                if v.constraint == "lighting.range"]
    assert any("sun_elevation_deg" in m for m in messages)
    assert any("color_temperature_k" in m for m in messages)


def test_spoken_preset_words_are_accepted():
    assert lighting.canonical_preset("Super bright") == "super_bright"
    assert lighting.canonical_preset("golden hour") == "golden_hour"
    assert lighting.canonical_preset("cloudy") == "overcast"
    with pytest.raises(ValueError, match="not one of"):
        lighting.canonical_preset("neon")


def test_every_preset_names_only_knobs_and_stays_in_range():
    for name, table in lighting.PRESETS.items():
        assert set(table) <= set(lighting.KNOBS), name
        assert lighting.problems({"preset": name, **table}) == [], name


# -- precedence and the look ------------------------------------------------------

def test_a_preset_fills_every_knob_it_names_and_the_engine_keys_follow():
    import webapp.runs as runs

    spec = plain_spec()
    spec.set("lighting.preset", "super_bright")
    look = runs.render_look_for(spec, None)
    preset = lighting.PRESETS["super_bright"]
    assert look["sun_elev"] == preset["sun_elevation_deg"]
    assert look["sun_azim"] == DEFAULT_LOOK["sun_azim"]          # no preset names a direction
    noon_bias = runs.exposure_bias_for(preset["sun_elevation_deg"])[0]
    assert look["exposure_bias"] == pytest.approx(noon_bias + preset["brightness_ev"])
    assert look["fog_density"] == preset["haze"]
    assert look["sun_intensity_scale"] == preset["sun_intensity"]
    assert look["sky_light_scale"] == preset["sky_fill"]
    assert look["sun_temperature_k"] == preset["color_temperature_k"]
    assert look["sun_source_angle_deg"] == preset["shadow_softness_deg"]
    assert "VISUAL" in look["note"] and "uncalibrated" in look["note"]


def test_stated_degrees_beat_the_preset_and_reach_the_commandlet_in_its_convention():
    import webapp.runs as runs

    spec = plain_spec()
    spec.set("lighting.preset", "golden_hour")
    spec.set("lighting.sun_elevation_deg", 30.0)
    spec.set("lighting.sun_azimuth_deg", 90.0)       # light from the east
    spec.set("lighting.brightness_ev", -1.0)
    look = runs.render_look_for(spec, None)
    assert look["sun_elev"] == 30.0
    assert look["sun_azim"] == engine_sun_azimuth(90.0) == 0.0
    assert look["lighting"]["sun_azimuth_deg"] == 90.0
    # The stated brightness replaces the preset's stops; the calibrated
    # exposure follows the stated elevation.
    assert look["exposure_bias"] == pytest.approx(runs.exposure_bias_for(30.0)[0] - 1.0)
    command = flags_for(look)
    assert "-sun-elev=30.0" in command and "-sun-azim=0.0" in command
    assert "-sun-temperature=3300" in command


def test_the_natural_preset_with_one_stated_knob_moves_only_that_knob():
    import webapp.runs as runs

    spec = plain_spec()
    spec.set("lighting.sky_fill", 2.0)
    look = runs.render_look_for(spec, None)
    assert {k: look[k] for k in DEFAULT_LOOK} == DEFAULT_LOOK
    assert look["sky_light_scale"] == 2.0
    assert "sun_intensity_scale" not in look and "sun_temperature_k" not in look
    assert lighting_flags(look) == ["-sky-light-scale=2"]


def test_lighting_layers_on_the_storm_look_and_the_sampled_look_wins():
    import webapp.runs as runs

    spec = plain_spec()
    spec.set("lighting.color_temperature_k", 7000.0)
    stormy = runs.render_look_for(spec, "thunderstorm")
    assert {k: stormy[k] for k in DEFAULT_LOOK} == runs.STORM_LOOK
    assert stormy["sun_temperature_k"] == 7000.0
    spec.set("randomization.enabled", True)
    from core.scenario.randomization import sample_randomization

    sample_randomization(spec)
    sampled = runs.render_look_for(spec, None)
    assert "sun_temperature_k" not in sampled


def test_a_stated_time_of_day_sun_reaches_the_commandlet_as_an_engine_yaw():
    """sun_look passed NOAA's compass azimuth straight to -sun-azim, which
    takes the engine yaw toward the sun: a dawn sun in the east rendered in
    the north. The look now converts, like the randomised sun always did."""
    import webapp.runs as runs
    from core.environment.sun import resolve

    spec = compile_prompt("fly the c172 over yosemite at dawn")
    spec.set("latitude", 37.7456)
    spec.set("longitude", -119.5936)
    look = runs.sun_look(spec)
    compass = resolve("dawn", 37.7456, -119.5936).azimuth_deg
    assert 60.0 < compass < 120.0                                   # an eastern sun
    assert look["sun_azim"] == pytest.approx(engine_sun_azimuth(compass), abs=0.01)
    # Lighting on top of it keeps the time of day's direction when it states none.
    spec.set("lighting.preset", "soft")
    lit = runs.render_look_for(spec, None)
    assert lit["sun_azim"] == look["sun_azim"]
    assert lit["lighting"]["sun_azimuth_deg"] == pytest.approx(compass, abs=0.02)
    assert "on top of" in lit["note"]


# -- the flags -----------------------------------------------------------------------

def test_the_lighting_flags_follow_the_fog_flag_in_table_order_only_when_asked():
    look = dict(DEFAULT_LOOK, sun_source_angle_deg=2.5, sun_intensity_scale=1.5)
    command = flags_for(look)
    at = command.index(f"-fog-density={DEFAULT_LOOK['fog_density']}")
    assert command[at + 1:at + 3] == ["-sun-intensity-scale=1.5", "-sun-source-angle=2.5"]
    assert not any(t.startswith(("-sky-light-scale=", "-sun-temperature="))
                   for t in command)
    with pytest.raises(ValueError, match="non-negative"):
        lighting_flags({"sky_light_scale": -1.0})
    # The void tier has no sun, so no lighting either.
    void = render_flags("c", "f", scene=None, mesh=None, look=look, camera_flags=None,
                        void=True, width=1, height=1, fps=1)
    assert not any(t.startswith("-sun-") for t in void)


def test_the_commandlet_parses_every_flag_the_builder_emits_and_the_scene_applies_them():
    commandlet = COMMANDLET.read_text(encoding="utf-8")
    scene = SCENE.read_text(encoding="utf-8")
    header = SCENE_H.read_text(encoding="utf-8")
    fields = {"-sun-intensity-scale=": "SunIntensityScale",
              "-sky-light-scale=": "SkyLightScale",
              "-sun-temperature=": "SunTemperatureK",
              "-sun-source-angle=": "SunSourceAngleDeg"}
    assert set(fields) == {prefix for _, prefix in LIGHTING_FLAGS}
    for prefix, field in fields.items():
        assert f'TEXT("{prefix[1:]}"), SceneOptions.{field})' in commandlet, prefix
        assert f"double {field} =" in header, field
        assert f"Options.{field}" in scene, field
    for call in ("SetUseTemperature(true)", "SetTemperature(", "SetLightSourceAngle(",
                 'SetObjectField(TEXT("lighting")'):
        assert call in scene, call


# -- the web page --------------------------------------------------------------------

def test_the_page_gets_the_block_its_presets_and_a_dict_that_reads_back_unchanged():
    from webapp.server import app

    payload = TestClient(app).post("/compile", json={
        "prompt": "chase view of the 747 for 20 seconds", "compiler": "regex"}).json()
    spec = payload["spec"]
    assert [row["name"] for row in spec["lighting"]] == list(LightingSpec.FIELD_ORDER)
    assert set(spec["lighting_presets"]["presets"]) == set(lighting.PRESET_NAMES)
    assert spec["lighting_presets"]["ranges"]["sun_elevation_deg"] == [2.0, 90.0]
    assert set(spec["dict"]["lighting"]) == set(LightingSpec.FIELD_ORDER)
    assert ScenarioSpec.from_dict(spec["dict"]).digest() == spec["digest"]
    page = (REPO / "webapp/static/index.html").read_text(encoding="utf-8")
    for anchor in ('id="lightingPanel"', 'id="viewPanel"', "function renderLightingPanel",
                   "function renderViewPanel", 'data-block="lighting"'):
        assert anchor in page, anchor


def test_the_sun_dial_shows_the_camera_and_the_flight_direction_and_drags():
    """The owner asked for the camera on the sun dial (a draggable C) and
    an arrow for where the aircraft flies, and in the camera panel a
    horizontal zoom slider and a vertical camera-angle slider."""
    page = (REPO / "webapp/static/index.html").read_text(encoding="utf-8")
    for anchor in ("function attachSunDialDrag", "data-camera-marker", "function followingCamera",
                   "function cameraDialInner", 'data-vslider="zoom"', 'data-vslider="height"',
                   'data-vslider="distance"', "writing-mode:vertical-lr",
                   "const VIEW_MIN_MM = 4"):
        assert anchor in page, anchor
