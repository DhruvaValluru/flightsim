"""r87 (2026-11-14): a cockpit storm at beauty stalled "after the sky light
capture" with no finer name. Each blocking call in and after the sky light
capture now beats the watchdog BEFORE it runs, so a stall names that call."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
       "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")


def _order(*needles):
    at = [SRC.index(n) for n in needles]
    assert at == sorted(at), needles


def test_sky_capture_beats_before_update():
    _order('BeatWatchdog(TEXT("the sky light capture (UpdateSkyCaptureContents running)"));',
           "USkyLightComponent::UpdateSkyCaptureContents(World);",
           'BeatWatchdog(TEXT("the sky light capture"));')


def test_restore_and_post_sky_captures_beat_before_blocking():
    _order('DrainGpu(TEXT("the sky light capture"));',
           'BeatWatchdog(TEXT("restoring the scene after the sky light capture"));',
           "FFlightSimBeautyFallback::ResumeAfterSkyCapture(VisualScene);",
           'TEXT("%s (end-of-frame updates and flush)")',
           'TEXT("%s (CaptureScene and flush)")',
           'BeatWatchdog(TEXT("a capture after the sky light capture"));')
