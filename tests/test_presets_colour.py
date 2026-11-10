"""Round 2b, presets-colour: the "super bright" preset reaches a beauty
frame, and the blue-purple shadow cast is neutralised (round 0 scenes 01,
02, 08 and 13; docs/visual/PROBE_LOG.md "## round-2b presets-colour").

What is measured here, without an engine: (1) a beauty render on the
physical sky (the render machine's FLIGHTSIM_SKY=physical) takes the
lighting block -- the sun moves in sky.json and the knobs ride as flags --
where it was dropped whole (round 0: 02 byte-identical to 01, 05 to 04);
(2) the beauty exposure no longer meters a STATED or PRESET scale away
(super bright's +0.6 EV was cancelled by metering its sun x1.6), while the
rain look's scales stay metered; (3) a beauty render sends the X-Plane sun
and sky-light colours white (a clear sea-level compensation sent a blue
sun and a warm fill under a deck at a low sun: magenta); (4) the tonemap's
BlueCorrection guard is planned, applied by the host and grep-checked.
Measure renders are unchanged in every case. What is NOT measured: how
any of it looks on screen (probes pc-preset and pc-blue, PROBE_LOG).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core.nl.compiler import compile_prompt
from core.render.flags import lighting_flags
from core.scenario.spec import ScenarioSpec
from core.scene import beauty_look as bl
from core.scene import lighting
from core.sky import plan as sky_plan

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
SCENE_CPP = (PRIVATE / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
RUNS_PY = (REPO / "webapp/runs.py").read_text(encoding="utf-8")
API = (REPO / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")

#: Round 0 scenes 01/02 (scripts/run_test_scenarios.py on phase-2-final).
YOSEMITE = "chase view of the a4 at 1500 m over yosemite at golden hour, flying east, for 6 seconds"
#: Round 0 scenes 04/05.
DESERT = "chase view of the a4 at 2000 m over the desert at 17:30, flying southwest, for 6 seconds"


def edited(prompt: str, **lighting_edits) -> ScenarioSpec:
    """The compiled spec with run_test_scenarios.py's apply_lighting edits
    (the page's dict, lighting section included, as POST /run reads it)."""
    spec = compile_prompt(prompt)
    data = spec.to_dict()
    data["lighting"] = spec.lighting.to_dict()
    for name, value in lighting_edits.items():
        data["lighting"][name].update(value=value, source="user")
    return ScenarioSpec.from_dict(data)


def write_sky(spec: ScenarioSpec, out: Path) -> Path:
    plan = sky_plan.plan_sky(str(spec.time_of_day.value), None, float(spec.latitude.value),
                             float(spec.longitude.value), float(spec.altitude.value),
                             float(spec.terrain_elevation.value))
    path = out / "sky.json"
    path.write_text(json.dumps(plan, indent=1), encoding="ascii")
    return path


# -- (1) the lighting block over the physical sky, beauty only -----------------------


def test_super_bright_moves_the_physical_skys_sun_and_sends_its_knobs(tmp_path):
    import webapp.runs as runs

    spec = edited(YOSEMITE, preset="super_bright")
    sky = write_sky(spec, tmp_path)
    before = json.loads(sky.read_text(encoding="ascii"))
    look = runs.relight_sky_plan(spec, sky, None)
    after = json.loads(sky.read_text(encoding="ascii"))
    preset = lighting.PRESETS["super_bright"]
    assert after["sun"]["elevation_deg"] == preset["sun_elevation_deg"]
    assert after["sun"]["relit"]["from"]["elevation_deg"] == before["sun"]["elevation_deg"]
    assert after["exposure"]["ev100"] > before["exposure"]["ev100"]   # a higher sun meters brighter
    assert after["instant_utc"] == before["instant_utc"]              # only the sun moves
    assert look["sun_elev"] == preset["sun_elevation_deg"]
    assert look["lighting"]["over_physical_sky"] is True
    assert "applied over the physical sky" in look["note"]
    assert lighting_flags(look) == ["-sun-intensity-scale=1.6", "-sky-light-scale=1.35",
                                    "-sun-temperature=6300", "-sun-source-angle=0.45"]
    assert look["fog_density"] == preset["haze"]


def test_a_stated_azimuth_moves_the_physical_sun_scenes_04_and_05_differ(tmp_path):
    import webapp.runs as runs

    planned = {}
    for name, azimuth in (("behind", 45.0), ("backlit", 225.0)):
        spec = edited(DESERT, sun_azimuth_deg=azimuth, sun_elevation_deg=20.0)
        out = tmp_path / name
        out.mkdir()
        sky = write_sky(spec, out)
        runs.relight_sky_plan(spec, sky, None)
        planned[name] = json.loads(sky.read_text(encoding="ascii"))["sun"]
    assert planned["behind"]["azimuth_deg"] == 45.0
    assert planned["backlit"]["azimuth_deg"] == 225.0
    assert planned["behind"]["elevation_deg"] == planned["backlit"]["elevation_deg"] == 20.0


def test_a_default_lighting_block_leaves_the_physical_sky_untouched(tmp_path):
    import webapp.runs as runs

    spec = edited(YOSEMITE)
    sky = write_sky(spec, tmp_path)
    before = sky.read_bytes()
    assert runs.relight_sky_plan(spec, sky, None) is None
    assert sky.read_bytes() == before


def test_measure_on_the_physical_sky_still_drops_the_block(monkeypatch):
    """The relight is called for beauty only; render_look_for itself (the
    measure path's look) is unchanged under FLIGHTSIM_SKY=physical."""
    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_SKY", "physical")
    spec = edited(YOSEMITE, preset="super_bright")
    assert runs.render_look_for(spec, None) is None
    assert runs.render_look_for(spec, "storm") == runs.STORM_LOOK
    flow = RUNS_PY[RUNS_PY.index("        quality = run_render_quality(run.look)\n        # The look"):]
    flow = flow[:flow.index("beauty_look = write_beauty_look_plan(")]
    assert 'if quality == "beauty":' in flow and "relight_sky_plan(spec, sky, event_note)" in flow


def test_relight_is_pure_re_meters_and_drops_night_extras():
    plan = sky_plan.plan_sky("midnight", None, 46.0, 7.7, 3000.0, 1600.0)
    assert plan["stars"]["drawn"] is True
    plan["night_lights"] = {"sidecar": None}
    relit = sky_plan.relight(plan, elevation_deg=40.0, azimuth_deg=None, basis="test")
    assert plan["sun"]["elevation_deg"] < 0 and "night_lights" in plan     # input untouched
    assert relit["sun"]["elevation_deg"] == 40.0
    assert relit["sun"]["azimuth_deg"] == plan["sun"]["azimuth_deg"]
    assert relit["stars"]["drawn"] is False and relit["stars"]["batches"] == []
    assert "night_lights" not in relit
    lux = sky_plan.sun_horizontal_lux(40.0) + relit["moon"]["horizontal_illuminance_lux"] \
        + sky_plan.NIGHT_SKY_LUX
    assert relit["exposure"]["ev100"] == pytest.approx(sky_plan.ev100_for(lux), abs=1e-3)
    assert relit["exposure"]["bias"] == pytest.approx(
        sky_plan.CAMERA_EV100 - relit["exposure"]["ev100"], abs=1e-3)
    assert sky_plan.relight(plan, elevation_deg=None, azimuth_deg=None, basis="x") == plan
    assert json.dumps(sky_plan.relight(plan, elevation_deg=40.0, azimuth_deg=None, basis="test")) \
        == json.dumps(relit)
    with pytest.raises(ValueError, match="outside"):
        sky_plan.relight(plan, elevation_deg=1.0, azimuth_deg=None, basis="x")


# -- (2) the exposure keeps a stated look ----------------------------------------------


def test_super_bright_is_brighter_than_natural_in_the_beauty_exposure(tmp_path, monkeypatch):
    import webapp.runs as runs

    monkeypatch.delenv("FLIGHTSIM_SKY", raising=False)
    sidecars = {}
    for name, edits in (("natural", {}), ("super_bright", {"preset": "super_bright"})):
        spec = edited(YOSEMITE, **edits)
        out = tmp_path / name
        out.mkdir()
        path = runs.write_beauty_look_plan(spec, out, runs.render_look_for(spec, None),
                                           quality="beauty")
        sidecars[name] = json.loads(path.read_text(encoding="utf-8"))
    bright = sidecars["super_bright"]["exposure"]
    preset = lighting.PRESETS["super_bright"]
    # The preset's scales are applied and recorded, not metered away ...
    assert bright["scene_light_stops"] == 0.0
    assert bright["lighting_scales_unmetered"]["sun_intensity_scale"] == preset["sun_intensity"]
    assert bright["lighting_scales_unmetered"]["sky_light_scale"] == preset["sky_fill"]
    # ... so the EV100 opens by the preset's brightness on its band.
    band, _ = bl.ev100_band(preset["sun_elevation_deg"])
    assert bright["ev100"] == pytest.approx(band - preset["brightness_ev"], abs=1e-3)
    metered = bl.scene_light(preset["sun_elevation_deg"], 0.0,
                             sun_intensity_scale=preset["sun_intensity"],
                             sky_light_scale=preset["sky_fill"])["stops"]
    assert metered > preset["brightness_ev"] - 0.1   # the old meter cancelled the preset
    assert "lighting_scales_unmetered" not in sidecars["natural"]["exposure"]


def test_the_rain_looks_scales_stay_metered(tmp_path):
    import webapp.runs as runs

    spec = compile_prompt("chase view of the c172p over mount fuji at sunrise in light rain "
                          "for 6 seconds")
    look = runs.render_look_for(spec, None)
    assert look["sun_intensity_scale"] < 1.0                     # the rain look dims the sun
    path = runs.write_beauty_look_plan(spec, tmp_path, look, quality="beauty")
    exposure = json.loads(path.read_text(encoding="utf-8"))["exposure"]
    assert "lighting_scales_unmetered" not in exposure


def test_measure_writes_no_sidecar(tmp_path):
    import webapp.runs as runs

    spec = edited(YOSEMITE, preset="super_bright")
    assert runs.write_beauty_look_plan(spec, tmp_path, runs.render_look_for(spec, None),
                                       quality="measure") is None


# -- (3) the X-Plane colours in beauty ---------------------------------------------------


def test_beauty_sends_the_xplane_sun_and_sky_light_white(monkeypatch):
    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_XPLANE_LIGHTING", "on")
    sunrise = {"sun_elev": 3.18, "sun_azim": 357.55, "exposure_bias": 10.3, "fog_density": 0.0035}
    measure = runs.xplane_lighting_flags(sunrise, condition="ocast")
    if not measure:
        pytest.skip("no X-Plane lighting tables extracted on this machine")
    beauty = runs.xplane_lighting_flags(sunrise, condition="ocast", beauty=True)
    assert beauty[0] == "-xplane-condition=beauty:ocast"
    assert beauty[1] == "-xplane-direct=255:255:255"
    assert beauty[2] == "-xplane-ambient=255:255:255"
    assert beauty[3] == measure[3]                                   # the horizon stands
    # What it replaced: a deep-blue key under a warm fill (the purple cast).
    direct = [int(c) for c in measure[1].split("=", 1)[1].split(":")]
    ambient = [int(c) for c in measure[2].split("=", 1)[1].split(":")]
    assert direct[2] > 2 * direct[0] and ambient[0] > ambient[2]
    model = runs.xplane_lighting_flags(sunrise, condition="clean", beauty=True)
    assert model[0] == "-xplane-condition=beauty:clean/model"       # host's /model test holds
    assert runs.xplane_lighting_flags(sunrise, condition="ocast") == measure


def test_only_a_beauty_render_asks_for_white_and_the_host_records_it():
    render = RUNS_PY[RUNS_PY.index("    def _render(card: Path"):]
    render = render[:render.index("from core.scene.hero_lighting import flags_beside")]
    assert "beauty=beauty_look is not None" in render
    assert "elif beauty_look is not None:" in render and "lighting_flags(look)" in render
    assert 'XPlaneCondition.StartsWith(TEXT("beauty:"))' in SCENE_CPP


# -- (4) the tonemap's blue guard --------------------------------------------------------


def test_the_plan_carries_blue_correction_and_the_host_applies_it():
    tonemap = bl.plan_beauty_look(8.0, fps=30, width_px=1920)["tonemap"]
    assert tonemap["BlueCorrection"] == bl.TONEMAP_HUE["BlueCorrection"] == 1.0
    assert "ExpandGamut" not in tonemap                 # the engine's 1.0 stays
    assert {k: tonemap[k] for k in bl.TONEMAP} == bl.TONEMAP
    assert "FLIGHTSIM_BEAUTY_FLOAT(Tonemap, BlueCorrection)" in LOOK_CPP
    assert "TONEMAP_HUE" in bl.UNCALIBRATED


def test_the_engine_symbols_are_in_the_api_check():
    block = API[API.index("BEGIN presets-colour"):API.index("END presets-colour")]
    for needle in ("float BlueCorrection;", "uint8 bOverride_BlueCorrection : 1;",
                   "BlueCorrection = 0.6f;", "BlueCorrectAP1", "BlueCorrectInvAP1"):
        assert needle in block, needle


def test_a_sky_blue_fill_stays_blue_on_the_model():
    """The physical model's sky irradiance (the fill the engine captures) is
    sky blue at every renderable sun, never purple: R < G < B. A purple
    shadow is therefore added downstream (a tint, the tonemap), which is
    what this lane removes."""
    import numpy as np

    from core.xplane.atmosphere import Atmosphere, sky_irradiance

    atm = Atmosphere()
    white = np.asarray(atm.solar_irradiance)
    for elevation in (3.0, 6.0, 8.0, 15.0, 30.0, 60.0, 89.0):
        r, g, b = sky_irradiance(atm, 0.0, elevation, 180.0) / white
        assert r < g < b, elevation
        hue = math.degrees(math.atan2(math.sqrt(3) * (g - b), 2 * r - g - b)) % 360.0
        assert 195.0 <= hue <= 235.0, (elevation, hue)
