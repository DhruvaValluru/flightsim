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


# -- the settle captures: skipped when the close-only guard changed nothing ----

@pytest.mark.parametrize("close_only,opened,closed,reduced,frames,want", [
    (True, 0.0, False, False, 1, 0),      # clear sky, nothing clips: no settle
    (True, 0.0, False, False, 120, 0),    # a full-size clip: the history is the warm-up's
    (True, 0.0, False, True, 1, 0),       # reduced still: frame 0 is a camera cut
    (True, 0.0, False, True, 120, 4),     # reduced clip: the history must regrow at full size
    (True, -1.5, True, False, 1, 4),      # the guard closed a clipping frame
    (False, 0.0, False, False, 1, 4),     # any other meter keeps its settle
])
def test_the_settle_is_skipped_only_when_the_guard_changed_nothing(close_only, opened, closed,
                                                                  reduced, frames, want):
    assert bl.frame_meter_settle_captures(close_only, opened, closed, reduced, frames) == want


def test_the_settle_skip_host_matches_the_twin():
    assert f"constexpr int32 StormMeterSettleCaptures = {bl.FRAME_METER_SETTLE_CAPTURES};" in CMD_CPP
    assert f"constexpr int32 RenderBeautyStillMaxFrames = {bl.BEAUTY_STILL_MAX_FRAMES};" in CMD_CPP
    block = CMD_CPP[CMD_CPP.index("StormMeterOpened = Opened;"):]
    block = block[:block.index('UE_LOG(LogFlightSimRender, Display, TEXT("exposure meter: settled"));')]
    assert ("const bool bMeterUnchanged = bMeterCloseOnly && !bMeterClosed && "
            "FMath::IsNearlyZero(Opened);") in block
    assert "(!bStormMeterReduced || MeterDeliveredFrames <= RenderBeautyStillMaxFrames)" in block
    assert "i < (bSkipMeterSettle ? 0 : StormMeterSettleCaptures)" in block
    # full size is restored before the settle decision, whatever it is
    assert block.index('SetMeterRes(false, TEXT("the exposure meter\'s settle captures"));') < \
        block.index("bSkipMeterSettle")
    # a skipped reduced meter still flags the next capture a camera cut
    skip = block[block.index("if (bSkipMeterSettle && bStormMeterReduced)"):]
    assert skip.index("Capture->bCameraCutThisFrame = true;") < 120
    # the settle loop's own cut stays for a reduced meter that settles
    assert "if (bStormMeterReduced && i == 0)" in block
    # the frames path still restores full size and a still starts from a cut
    assert 'SetMeterRes(false, TEXT("the frames"));' in CMD_CPP
    assert "const bool bBeautyStill = bBeautyRaster && DeliveredFrames <= RenderBeautyStillMaxFrames;" in CMD_CPP
    assert 'MeterRow->SetNumberField(TEXT("settle_captures"), bSkipMeterSettle ? 0 : StormMeterSettleCaptures);' \
        in CMD_CPP


def test_the_settle_frame_count_is_delivered_frames():
    """MeterDeliveredFrames is DeliveredFrames' count, from the same inputs."""
    later = CMD_CPP[CMD_CPP.index("const int32 DeliveredFrames = bConsumePoses"):][:200]
    assert "? CaptureTimes.Num()" in later
    assert "(Steps + StepsPerFrame - 1) / StepsPerFrame" in later
    assert "const double Duration = SecondsOverride > 0.0" in CMD_CPP
    assert "? FMath::Min(SecondsOverride, Card.DurationSeconds)" in CMD_CPP
    assert "const int32 Steps = FMath::RoundToInt(Duration * Card.RateHz);" in CMD_CPP
    assert ("const int32 StepsPerFrame = FMath::Max(1, FMath::RoundToInt(Card.RateHz / FramesPerSecond));"
            in CMD_CPP)
    early = CMD_CPP[CMD_CPP.index("const int32 MeterDeliveredFrames = bConsumePoses"):][:500]
    assert "SecondsOverride > 0.0 ? FMath::Min(SecondsOverride, Card.DurationSeconds)" in early
    assert "* Card.RateHz)" in early
    assert early.count("FMath::Max(1, FMath::RoundToInt(Card.RateHz / FramesPerSecond))") == 2
