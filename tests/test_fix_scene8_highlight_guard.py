"""fix-scene8 (2026-11-16): -exposure-anchor=incident skipped the no-Lumen
frame meter outright, and with it the meter's highlight guard, so #8 (C172
over Fuji, sunrise, light rain, no deck) rendered washed out in round 144
(mean luma 0.731 vs 0.595 in rounds 83/89). Under incident the meter now runs
close-only. Numeric checks on the Python twin, and source-reading checks on
the C++ (nothing renders on this machine)."""

import re
from pathlib import Path

import pytest

from core.scene import beauty_look as bl

REPO = Path(__file__).resolve().parents[1]
PRIV = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
LOOK_CPP = (PRIV / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
CMD_CPP = (PRIV / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
LOOKDEV_CPP = (PRIV / "FlightSimLookDev.cpp").read_text(encoding="utf-8")
NO_LUMEN = bl.EXPOSURE_METER_TARGET_P90["no_lumen_gi"]


def plan(elevation=5.0, **kw):
    return bl.plan_beauty_look(elevation, fps=30.0, width_px=1920, **kw)


def test_the_sidecar_states_the_guard_on_by_default():
    meter = plan(world_preset="clear")["exposure"]["meter"]
    assert meter["clear_no_lumen_gi"] == "incident"
    assert meter["clear_highlight_guard"] == bl.DEFAULT_CLEAR_HIGHLIGHT_GUARD == "on"
    assert meter["clear_highlight_guard_switch"] == "-clear-highlight-guard=on|off"
    assert bl.CLEAR_HIGHLIGHT_GUARDS == ("on", "off")


def test_a_clipping_clear_frame_closes_like_the_old_guard():
    # #8's haze: p90 ~0.97 (round 144 frame). Close-only and the old meter
    # take the same first step: toward 0.80, ~ -0.49 stops.
    old = bl.frame_meter_step(0.972, 0.0, NO_LUMEN, close_only=False)
    new = bl.frame_meter_step(0.972, 0.0, NO_LUMEN, close_only=True)
    assert new == pytest.approx(old)
    assert new == pytest.approx(2.2 * 0.8 * __import__("math").log2(0.80 / 0.972), abs=1e-12)
    assert new < -0.45
    # pinned at 255: at least the saturated step down
    assert bl.frame_meter_step(1.0, 0.0, NO_LUMEN, close_only=True) <= -2.0
    # never past the close cap
    assert bl.frame_meter_step(1.0, -5.5, NO_LUMEN, close_only=True) == pytest.approx(-0.5)


@pytest.mark.parametrize("p90", [0.05, 0.20, 0.48, 0.70, 0.92])
def test_a_frame_that_does_not_clip_keeps_the_incident_exposure(p90):
    # #13's dark sea (p90 0.48 with the layer, darker without) is not opened.
    assert bl.frame_meter_step(p90, 0.0, NO_LUMEN, close_only=True) == 0.0
    # once closed, an unclipped frame is left where the guard put it
    assert bl.frame_meter_step(p90, -0.6, NO_LUMEN, close_only=True) == 0.0


def test_the_old_frame_anchor_still_opens_a_dark_frame():
    assert bl.frame_meter_step(0.10, 0.0, NO_LUMEN, close_only=False) > 1.0


def _const(name):
    m = re.search(r"constexpr double %s = ([0-9.]+);" % name, CMD_CPP)
    assert m, name
    return float(m.group(1))


def test_the_python_twin_matches_the_host_constants():
    assert _const("BeautyMeterHighlightP90") == bl.FRAME_HIGHLIGHT_P90
    assert _const("BeautyMeterHighlightTarget") == bl.FRAME_HIGHLIGHT_TARGET_P90
    assert _const("BeautyMeterMaxCloseStops") == bl.FRAME_MAX_CLOSE_STOPS
    assert _const("BeautyMeterSaturatedStepStops") == bl.FRAME_SATURATED_STEP_STOPS
    assert _const("StormMeterTolerance") == bl.FRAME_METER_TOLERANCE
    assert _const("StormMeterMaxStops") == bl.FRAME_METER_MAX_STOPS


def test_the_host_runs_the_guard_under_incident():
    block = LOOK_CPP[LOOK_CPP.index('if (Anchor == TEXT("frame"))'):]
    block = block[:block.index('TEXT("no: no deck, and Lumen GI runs")')]
    assert 'TEXT("clear-highlight-guard=")' in block
    assert 'FString Guard = TEXT("on");' in block
    assert 'State.MeterTrigger = TEXT("clear_highlight_guard");' in block
    assert "-clear-highlight-guard=%s is not on or off" in block
    assert bl.CLEAR_HIGHLIGHT_GUARD_TRIGGER == "clear_highlight_guard"


def test_the_commandlet_meter_only_closes_for_the_guard():
    assert 'BeautyMeterTrigger == TEXT("clear_highlight_guard")' in CMD_CPP
    loop = CMD_CPP[CMD_CPP.index("const bool bBlown = bMeterMayClose && Bright > BeautyMeterHighlightP90;"):]
    loop = loop[:loop.index("const double Want = bBlown")]
    assert "if (bMeterCloseOnly && !bBlown)" in loop
    assert loop[loop.index("if (bMeterCloseOnly && !bBlown)"):].index("break;") < 400
    assert 'Guard->SetBoolField(TEXT("close_only"), bMeterCloseOnly);' in CMD_CPP
    assert 'MeterTrigger == TEXT("clear_highlight_guard")) { break; }' in LOOKDEV_CPP
