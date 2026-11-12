"""Round 4 (2026-11-10): #02 "same, super bright preset" lit neutral.

Round 2's #02 (6816852c, the round-3 tint in) still rendered a blue/violet
cast, mean sRGB 96/102/157: neutral highlights (the sun) over shade and
midtones at R/B 0.2-0.4 (scene-linear), flat across the frame's rows. The
cast is the stated fill: super bright's x1.35 sky fill (x1.66 luminance
restore, x1.6 no-Lumen fallback) multiplied the captured 72-deg noon sky,
and round 3 only moved that colour 0.75 of the way to grey, keeping it blue
by design. A fill the preset states is now neutral, and the ground's lower
hemisphere is compensated so the neutral fill's tint does not turn it orange.

Pinned here on the planned lighting (what the host is handed): the fill as
the light stores it and the planned sun have bounded chroma, and the scenes
without a stated fill (#01, #04, #13) are untouched. What is NOT measured:
the frame (PROBE_LOG round 4, probe r4-neutral on the render machine).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.scene import hero_lighting as hl
from core.scene import lighting

from tests.test_presets_colour import DESERT, YOSEMITE, edited, write_sky

LUMA = (0.2126, 0.7152, 0.0722)


def _plan(tmp_path: Path, name: str, prompt: str = YOSEMITE, **edits):
    import webapp.runs as runs

    out = tmp_path / name
    out.mkdir()
    spec = edited(prompt, **edits)
    sky = write_sky(spec, out)
    look = runs.relight_sky_plan(spec, sky, None)
    beauty = runs.write_beauty_look_plan(spec, out, look, sky=sky, quality="beauty")
    hero = hl.write_sidecar_beside(spec, beauty)
    return {"look": look, "beauty": json.loads(beauty.read_text(encoding="utf-8")),
            "hero": json.loads(hero.read_text(encoding="utf-8"))}


def _chroma(rgb):
    """max / min channel: 1 is grey."""
    return max(rgb) / min(rgb)


def test_super_bright_fill_is_near_neutral(tmp_path):
    bright = _plan(tmp_path, "02", preset="super_bright")
    fill = bright["hero"]["sky_light"]
    assert fill["neutral_share"] == hl.STATED_FILL_NEUTRAL_SHARE == 0.0   # round 76 (1.0, then 0.5)
    colour, sky, scale = fill["color_linear_rgb"], fill["model_sky_rgb"], fill["intensity_scale"]
    # The colour is what the light can hold (8-bit sRGB), so the host draws it as planned.
    assert all(hl.srgb8_stored(c) == pytest.approx(c, abs=1e-6) for c in colour)
    assert max(colour) == 1.0 and min(colour) > 0.0
    # The fill the shade gets: the captured noon sky (very blue: R/B ~0.25) times the colour.
    assert sky[0] / sky[2] < 0.3
    lit = [s * c * scale for s, c in zip(sky, colour)]
    # Share 0 (round 76): the sky's own colour; share 1 turned #02 sepia once the
    # tiles' neutraliser drew, 0.5 left it warm.
    assert _chroma(lit) == pytest.approx(_chroma(sky), rel=1e-6)
    # Its luminance is the sky's (the preset's "how bright the shadows are" kept).
    assert sum(w * v for w, v in zip(LUMA, lit)) == pytest.approx(
        sum(w * v for w, v in zip(LUMA, sky)), rel=1e-6)


def test_the_neutral_fill_does_not_turn_the_ground_orange(tmp_path):
    bright = _plan(tmp_path, "02", preset="super_bright")
    ground, fill = bright["hero"]["ground"], bright["hero"]["sky_light"]
    drawn = [v * c * fill["intensity_scale"] for v, c in
             zip(ground["lower_hemisphere_luminance_rgb"], fill["color_linear_rgb"])]
    intended = ground["lower_hemisphere_luminance_rgb_drawn"]
    for d, i in zip(drawn, intended):
        assert d == pytest.approx(i, rel=1e-3)
    # albedo x E / pi: the ground's own colour, not the tint's.
    albedo = ground["albedo_rgb"]
    assert [i / intended[0] for i in intended] == pytest.approx(
        [a / albedo[0] for a in albedo], rel=1e-3)


def test_super_bright_sun_is_near_neutral():
    """The sun #02 is lit by: the atmosphere's per-pixel transmittance at the
    preset's 72 deg (core.xplane.atmosphere, the engine's constants) and the
    preset's colour temperature, both close to white."""
    import numpy as np

    from core.xplane.atmosphere import Atmosphere, sun_irradiance

    preset = lighting.PRESETS["super_bright"]
    atm = Atmosphere()
    sun = sun_irradiance(atm, 1200.0, preset["sun_elevation_deg"]) / np.asarray(atm.solar_irradiance)
    assert _chroma(list(sun)) <= 1.35                                # a high sun: barely reddened
    assert 6000.0 <= preset["color_temperature_k"] <= 7000.0         # daylight, not a warm or cool key
    assert preset["sky_fill"] > 1.0                                  # a stated fill: the neutral path


def test_scenes_without_a_stated_fill_are_unchanged(tmp_path):
    golden = _plan(tmp_path, "01")                                   # #01 (and #13): no lighting block
    desert = _plan(tmp_path, "04", prompt=DESERT,                    # #04: a stated sun only
                   sun_azimuth_deg=45.0, sun_elevation_deg=20.0)
    for scene in (golden, desert):
        assert "sky_light" not in scene["hero"]
        ground = scene["hero"]["ground"]
        assert "lower_hemisphere_luminance_rgb_drawn" not in ground
        assert "lower_hemisphere_fill_compensation" not in ground
        assert scene["hero"]["uncalibrated"] == ["GROUND_ALBEDO_RGB",
                                                 "OVERCAST_ILLUMINANCE_FRACTION"]


def test_measure_never_gets_a_sidecar():
    assert hl.write_sidecar_beside(edited(YOSEMITE, preset="super_bright"), None) is None
    assert hl.with_stated_fill_scale({"sky_light_scale": 1.35}, None) == {"sky_light_scale": 1.35}


def test_the_stated_fill_share_switch():
    assert hl.stated_fill_share("") == hl.STATED_FILL_NEUTRAL_SHARE
    assert hl.stated_fill_share("-gear=up -stated-fill-share=0.25") == 0.25
    assert hl.stated_fill_share("stated-fill-share=1") == 1.0
    for bad in ("-stated-fill-share=1.5", "-stated-fill-share=grey"):
        with pytest.raises(hl.HeroLightingError):
            hl.stated_fill_share(bad)
