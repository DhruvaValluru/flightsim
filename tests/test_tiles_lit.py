"""r147 golden hour (#01 / #02): the Google tiles lit by the frame's own sun.

Cesium draws KHR_materials_unlit tiles with the ellipsoid's up as every normal
and no tile shadow, so a 6 deg sun lit every cliff at N.L 0.10 and no ridge cast
a shadow. The beauty look now calls ACesium3DTileset::SetIgnoreKhrMaterialsUnlit
(default on, -tiles-lit=off the A/B). Pinned: the twin's laws, the host's call,
switch and record, and that only the beauty path makes it. NOT measured here:
the frame (Windows, scenes 1 and 2 with and without -tiles-lit=off).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from core.scene import lighting
from core.scene import tiles_lit as tl

REPO = Path(__file__).resolve().parents[1]
PRIV = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
TILES = (PRIV / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")


def _apply_beauty_look_body() -> str:
    start = TILES.index("TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyLook(")
    end = TILES.index("\n}\n", start)
    return TILES[start:end]


@pytest.mark.parametrize("text,value", [
    ("", "on"), ("-tiles-lit=on", "on"), ("-tiles-lit=off", "off"), ("tiles-lit=off", "off"),
    ("-quality=beauty -tiles-lit=off -x", "off"), ("-tiles-lit=OFF", "off"), ("-tiles-lit=", "on"),
    ("-tiles-lit=off,x", "off"), ("-TILES-LIT=off", "off"),
])
def test_the_switch_reads_like_the_host(text, value):
    assert tl.parse_switch(text) == value


def test_the_command_line_wins_over_the_environment():
    assert tl.parse_switch("-tiles-lit=on", "-tiles-lit=off") == "on"
    assert tl.parse_switch("", "-tiles-lit=off") == "off"


def test_default_is_lit():
    assert tl.SWITCH_DEFAULT == "on" and tl.ignore_unlit() is True
    assert tl.ignore_unlit("off") is False
    assert tl.record()["ignore_khr_materials_unlit"] is True
    assert tl.record("off")["basis"] == tl.BASIS_OFF


def test_unlit_tiles_light_every_face_alike_at_a_golden_hour_sun():
    """The round-146 defect: every face gets sin(elevation), whatever it faces."""
    west_wall = (-1.0, 0.0, 0.0)            # a cliff facing the setting sun
    east_wall = (1.0, 0.0, 0.0)
    sun_from_west = (-1.0, 0.0)
    off = [tl.lit_fraction(6.0, n, sun_from_west, "off") for n in (west_wall, east_wall, (0, 0, 1))]
    assert all(abs(v - math.sin(math.radians(6.0))) < 1e-12 for v in off)
    assert off[0] < 0.11


def test_lit_tiles_give_the_sun_facing_wall_the_golden_key_and_the_far_wall_none():
    west_wall = (-1.0, 0.0, 0.0)
    east_wall = (1.0, 0.0, 0.0)
    sun_from_west = (-1.0, 0.0)
    lit = tl.lit_fraction(6.0, west_wall, sun_from_west)
    assert lit > 0.99                       # ~9.5x the unlit tiles' key on the wall that faces it
    assert tl.lit_fraction(6.0, east_wall, sun_from_west) == 0.0   # the shade side: sky only
    # a high sun no longer hits a vertical wall flat on (#02's over-lit violet walls)
    assert tl.lit_fraction(72.0, west_wall, sun_from_west) < 0.32 < tl.lit_fraction(72.0, west_wall, sun_from_west, "off")


def test_the_host_sets_it_in_the_beauty_look_only_and_records_it():
    body = _apply_beauty_look_body()
    assert f"Tiles->{tl.CESIUM_SETTER}(true);" in body
    assert 'TEXT("tiles-lit=")' in body
    assert 'FString TilesLitSwitch = TEXT("on");' in body
    assert 'TilesLitSwitch != TEXT("off")' in body
    assert 'FLIGHTSIM_RENDER_SWITCHES' in body
    assert f'Out->SetObjectField(TEXT("{tl.RECORD_KEY}"), Lit);' in body
    assert tl.BASIS_ON in body and tl.BASIS_OFF in body
    # set before the refresh that reloads the tiles with it
    assert body.index(f"{tl.CESIUM_SETTER}(true)") < body.index("Tiles->RefreshTileset();")
    # nowhere else: the measure path keeps Cesium's unlit tiles
    hits = [p.name for p in PRIV.glob("*.cpp") if tl.CESIUM_SETTER in p.read_text(encoding="utf-8")]
    assert hits == ["FlightSimGoogleTiles.cpp"]
    assert TILES.count(f"{tl.CESIUM_SETTER}(") == 1


def test_super_bright_keeps_a_daylight_key_a_touch_warm_not_cold():
    preset = lighting.PRESETS["super_bright"]
    # Unreal's temperature: below 6500 K is warmer than white.
    assert 6000.0 <= preset["color_temperature_k"] < 6300.0
    assert lighting.PRESETS["golden_hour"]["color_temperature_k"] < preset["color_temperature_k"]
