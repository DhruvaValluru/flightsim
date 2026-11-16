"""hl-fixes (2026-11-16): #10 (a C172 near a tornado under a storm, Windows round 1410)
rendered crushed (luma 0.018, 13% crushed) under the default -exposure-anchor=incident;
=frame (round 1421) gave 0.051. world_preset_for_card read only "thunderstorm" as a
storm, so the tornado card was a "clear" preset, under_deck False although its deck is
drawn: the sidecar's meter row said no deck, the host took the clear-sky incident anchor
(no meter) and scene_light kept the clear-sky light. Any storm word is a storm now, as
the host's world look reads it; clear frames keep incident."""
import pytest

from core.scene import beauty_look as bl
from core.scene import world_beauty as wb
from core.scene.weather_look import STORMS


@pytest.mark.parametrize("word", STORMS)
def test_every_storm_word_meters_under_its_deck(word):
    card = {"weather_look": {"storm": word}}
    preset = bl.world_preset_for_card(card)[0]
    assert preset == "storm" == wb.select_preset(wb.is_storm_word(word), 0.0, False, 0.0, 0.0)
    deck = bl.deck_drawn_for_card(card)
    assert deck is True
    row = bl.exposure_meter(preset, deck)
    assert row["deck"] is True and row["target_p90_luma"] == bl.EXPOSURE_METER_TARGET_P90["storm"]
    light = bl.scene_light(10.0, 600.0, world_preset=preset, deck=deck)
    assert light["stops"] < 0.0 and "cloud deck" in light["basis"]


def test_the_tornado_card_is_no_longer_a_clear_sky():
    card = {"weather_look": {"storm": "tornado"}}
    assert bl.under_deck(*[bl.world_preset_for_card(card)[0], bl.deck_drawn_for_card(card)])


@pytest.mark.parametrize("card", [{}, {"weather_look": {"storm": ""}}, {"weather_look": {"storm": "none"}}])
def test_clear_frames_keep_the_incident_anchor(card):
    preset = bl.world_preset_for_card(card)[0]
    row = bl.exposure_meter(preset, bl.deck_drawn_for_card(card))
    assert preset == "clear" and row["deck"] is False
    assert row["clear_no_lumen_gi"] == bl.DEFAULT_EXPOSURE_ANCHOR == "incident"


def test_overcast_still_meters():
    card = {"look": {"clouds": [{"base_m": 500.0, "top_m": 2000.0, "cover": 0.95}]}}
    preset = bl.world_preset_for_card(card)[0]
    assert preset == "overcast" and bl.exposure_meter(preset, bl.deck_drawn_for_card(card))["deck"] is True
