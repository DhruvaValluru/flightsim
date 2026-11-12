"""Round 3 (2026-11-10): two beauty-look defects from the round-1 frames.

#02 "same, super bright preset" rendered DARKER than #01 (mean luma 76 vs 96)
under a heavy indigo cast (shadows sRGB 14/26/107). Two causes, both pinned
here by direction (brighter, not bluer):

* the relit sun's exposure: the preset moves the physical sky's sun from 6 to
  72 deg; the plan re-meters its incident EV100 on the horizontal (11.6 ->
  15.3) and the beauty exposure closed by all of it, for steep walls the high
  sun grazes. It now closes by RELIT_SUN_CLOSE_SHARE of the gain only;
* the stated fill's colour: the preset's sky fill x1.35 (x1.6 more from the
  no-Lumen fallback) multiplied the raw noon sky capture (R/B 0.25 on the
  model) with no GI bounce; the X-Plane ambient compensation the presets were
  chosen under is white in beauty since round 2b. A stated fill is now lit as
  a fill: the sky's blue moved toward grey, its luminance kept.

#06 "A320 over SFO, moderate rain": the rain world drew nimbostratus at its
default cover 0.98 (the card states no cloud): a solid sheet, no ground. A
rain world's unstated layer is now broken (RAIN_DEFAULT_COVER).

Measure renders never see any of it (no sidecar, no relight, the clouds are
the world lane's beauty redraw). What is NOT measured: how it looks on the
render machine (PROBE_LOG round 3 probes).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.scene import beauty_look as bl
from core.scene import hero_lighting as hl
from core.scene import lighting
from core.scene import world_beauty as wb
from core.sky import plan as sky_plan

from tests.test_presets_colour import YOSEMITE, edited, write_sky

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
HERO_CPP = (PRIVATE / "FlightSimHeroLighting.cpp").read_text(encoding="utf-8")
CLOUDS_CPP = (PRIVATE / "FlightSimClouds.cpp").read_text(encoding="utf-8")
API = (REPO / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
RUNS_PY = (REPO / "webapp/runs.py").read_text(encoding="utf-8")


def _plan_scene(tmp_path: Path, name: str, **edits):
    """The web app's beauty planning for one of round 1's Yosemite scenes on
    the physical sky: sky.json, the relight, the beauty look, hero lighting."""
    import webapp.runs as runs

    out = tmp_path / name
    out.mkdir()
    spec = edited(YOSEMITE, **edits)
    sky = write_sky(spec, out)
    instant = json.loads(sky.read_text(encoding="ascii"))
    look = runs.relight_sky_plan(spec, sky, None)
    beauty = runs.write_beauty_look_plan(spec, out, look, sky=sky, quality="beauty")
    hero = hl.write_sidecar_beside(spec, beauty)
    return {"instant": instant, "sky": json.loads(sky.read_text(encoding="ascii")),
            "beauty": json.loads(beauty.read_text(encoding="utf-8")),
            "hero": json.loads(hero.read_text(encoding="utf-8"))}


# -- #02: brighter -------------------------------------------------------------------


def test_super_bright_opens_back_part_of_the_relit_meter(tmp_path):
    golden = _plan_scene(tmp_path, "01")
    bright = _plan_scene(tmp_path, "02", preset="super_bright")
    preset = lighting.PRESETS["super_bright"]
    ex = bright["beauty"]["exposure"]
    gain = bright["sky"]["exposure"]["ev100"] - golden["sky"]["exposure"]["ev100"]
    assert gain > 3.0                                           # 6 -> 72 deg: about 3.7 stops
    assert bright["sky"]["exposure"]["relit_from_ev100"] == golden["sky"]["exposure"]["ev100"]
    opened = ex["relit_sun_open_stops"]
    assert opened == pytest.approx(gain * (1.0 - bl.RELIT_SUN_CLOSE_SHARE), abs=1e-3)
    assert 0.8 <= opened <= 1.5
    # The one owner's formula, with the open on its base: more light on the
    # sensor than the plain relit meter would have given (AutoExposureBias up).
    assert ex["ev100"] == pytest.approx(ex["base_ev100"] - opened - preset["brightness_ev"], abs=1e-3)
    plain = ex["base_ev100"] - preset["brightness_ev"]
    assert ex["AutoExposureBias"] == pytest.approx(ex["camera_ev100"] - ex["ev100"], abs=1e-3)
    assert ex["AutoExposureBias"] > ex["camera_ev100"] - plain
    # The closing share of the gain is still taken: a high sun is brighter light.
    assert ex["ev100"] > golden["beauty"]["exposure"]["ev100"]
    # #01 is not relit: its exposure is exactly the plan's meter, as before.
    assert "relit_sun_open_stops" not in golden["beauty"]["exposure"]
    assert "relit_from_ev100" not in golden["sky"]["exposure"]
    assert "RELIT_SUN_CLOSE_SHARE" in bl.UNCALIBRATED


def test_a_relight_to_a_lower_sun_opens_by_the_meter_in_full():
    block = {"ev100": 12.0, "relit_from_ev100": 14.5}
    assert bl.relit_sun_open_stops(block) == 0.0
    assert bl.relit_sun_open_stops({"ev100": 12.0}) == 0.0          # not relit
    assert bl.relit_sun_open_stops(None) == 0.0
    with pytest.raises(bl.BeautyLookError):
        bl.relit_sun_open_stops({"ev100": "x", "relit_from_ev100": 1.0})


def test_relight_keeps_the_instants_own_meter_once():
    plan = sky_plan.plan_sky("06:30", None, 37.74, -119.6, 1500.0, 1200.0)
    once = sky_plan.relight(plan, elevation_deg=72.0, azimuth_deg=None, basis="t")
    twice = sky_plan.relight(once, elevation_deg=40.0, azimuth_deg=None, basis="t")
    assert once["exposure"]["relit_from_ev100"] == plan["exposure"]["ev100"]
    assert twice["exposure"]["relit_from_ev100"] == plan["exposure"]["ev100"]
    assert "relit_from_ev100" not in plan["exposure"]                # pure: input untouched


# -- #02: not bluer ------------------------------------------------------------------


def _ratio(rgb):
    return rgb[0] / rgb[2]


def test_super_bright_lights_its_fill_as_a_fill_not_more_blue_sky(tmp_path):
    golden = _plan_scene(tmp_path, "01")
    bright = _plan_scene(tmp_path, "02", preset="super_bright")
    assert "sky_light" not in golden["hero"]                         # #01 untouched
    fill = bright["hero"]["sky_light"]
    sky, colour, scale = fill["model_sky_rgb"], fill["color_linear_rgb"], fill["intensity_scale"]
    assert colour[0] >= colour[1] >= colour[2] and max(colour) == 1.0   # 8-bit legal
    lit = [s * c * scale for s, c in zip(sky, colour)]
    # Round 76 (share 0): the fill keeps the sky's own colour; the tiles' shade
    # neutraliser removes the photograph's baked blue instead (round 4's neutral
    # fill and round 75's half turned #02 sepia once it drew).
    assert colour == [1.0, 1.0, 1.0] and _ratio(lit) == pytest.approx(_ratio(sky), rel=1e-6)
    luma = (0.2126, 0.7152, 0.0722)
    assert sum(w * v for w, v in zip(luma, lit)) == pytest.approx(
        sum(w * v for w, v in zip(luma, sky)), rel=1e-4)            # its brightness kept
    assert "STATED_FILL_NEUTRAL_SHARE" in bright["hero"]["uncalibrated"]


@pytest.mark.parametrize("elevation", [2.0, 6.0, 15.0, 35.0, 55.0, 72.0, 90.0])
def test_the_stated_fill_is_never_bluer_than_the_sky(elevation):
    fill = hl.stated_fill_tint(elevation, 1200.0)
    sky, colour = fill["model_sky_rgb"], fill["color_linear_rgb"]
    lit = [s * c for s, c in zip(sky, colour)]
    assert _ratio(lit) >= _ratio(sky)
    assert lit[2] / lit[1] <= sky[2] / sky[1]
    assert all(0.0 < c <= 1.0 for c in colour) and fill["intensity_scale"] >= 1.0


def test_no_tint_under_rain_or_without_a_stated_fill():
    rainy = hl.plan_sidecar(surface="forest", sun_elevation_deg=40.0, horizontal_lux=None,
                            raining=True, stated_fill=True)
    plain = hl.plan_sidecar(surface="forest", sun_elevation_deg=40.0, horizontal_lux=None,
                            raining=False)
    assert "sky_light" not in rainy and "sky_light" not in plain
    assert plain["uncalibrated"] == ["GROUND_ALBEDO_RGB", "OVERCAST_ILLUMINANCE_FRACTION"]


def test_the_host_applies_the_stated_fill_and_the_api_check_knows_it():
    body = HERO_CPP[HERO_CPP.index('TryGetObjectField(TEXT("sky_light"), SkyFill)'):]
    body = body[:body.index("Sky->SetCaptureIsDirty();")]
    assert 'HeroLightingReadRgb(*SkyFill, TEXT("color_linear_rgb"), FillColor)' in body
    assert "Sky->SetLightColor(FillColor);" in body
    assert "SetIntensity(" not in body          # the lane never changes an intensity
    assert 'SkyRecord->SetObjectField(TEXT("stated_fill"), FillRecord);' in body
    assert 'hl_check "hero: SkyLight SetLightColor"' in API


def test_the_fill_luminance_rides_the_lighting_blocks_sky_light_scale(tmp_path):
    from core.render.flags import lighting_flags

    import webapp.runs as runs

    bright = _plan_scene(tmp_path, "02", preset="super_bright")
    out = tmp_path / "02"
    look = runs.relight_sky_plan(edited(YOSEMITE, preset="super_bright"),
                                 write_sky(edited(YOSEMITE, preset="super_bright"), tmp_path), None)
    folded = hl.with_stated_fill_scale(look, out / "beauty_look.json")
    scale = bright["hero"]["sky_light"]["intensity_scale"]
    assert folded["sky_light_scale"] == pytest.approx(look["sky_light_scale"] * scale, abs=1e-5)
    assert f"-sky-light-scale={folded['sky_light_scale']:g}" in lighting_flags(folded)
    # Measure (no sidecar), and a run without a stated fill: the same look object.
    assert hl.with_stated_fill_scale(look, None) is look
    golden = _plan_scene(tmp_path, "01")
    assert "sky_light" not in golden["hero"]
    assert hl.with_stated_fill_scale(look, tmp_path / "01" / "beauty_look.json") is look
    render = RUNS_PY[RUNS_PY.index("    def _render(card: Path"):]
    render = render[:render.index("if sky is None:")]
    assert "look = with_stated_fill_scale(look, beauty_look)" in render


# -- #06: the ground reads under moderate rain ---------------------------------------


def test_a_rain_world_without_a_card_cover_draws_broken_cloud():
    card = {"weather_look": {"rain_rate_mmh": 4.0}}                 # #06: rain, no cloud stated
    inputs = wb.card_inputs(card)
    assert inputs["card_cover"] is None
    assert wb.card_preset(card) == "rain"
    # The physical sky's default 3 km layer, redrawn in the rain world.
    cover, shape = wb.layer_cover_and_shape(inputs["card_cover"], 3000.0, "rain", False)
    assert (cover, shape) == (wb.RAIN_DEFAULT_COVER, "nimbostratus")
    assert cover < wb.OVERCAST_COVER < wb.CLOUDS["nimbostratus"]["default_cover"]
    # A card that says overcast keeps its deck; a storm keeps its sheet.
    assert wb.layer_cover_and_shape(0.95, 3000.0, "rain", False)[0] == 0.95
    assert wb.layer_cover_and_shape(None, 3000.0, "storm", False)[0] == 0.98


def test_the_host_draws_the_same_rain_cover():
    assert "constexpr double RainDefaultCover = 0.72;" in CLOUDS_CPP   # lane D: was 0.6 (#06 puffs)
    assert wb.RAIN_DEFAULT_COVER == 0.72
    assert ("(bStated ? CardCover : (Preset == PresetRain ? RainDefaultCover : GuessDefault))"
            in CLOUDS_CPP)
    assert "RainDefaultCover: a rain world, the card states none" in CLOUDS_CPP
