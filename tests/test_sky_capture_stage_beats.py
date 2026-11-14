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


def test_constrained_sky_capture_sheds_weather_and_cloud_march():
    """r87: the iGPU hung (887a0006) inside the storm's sky capture. On a
    constrained GPU (auto) the weather actors are hidden for that capture and
    the cloud reflection march is capped, then both are put back."""
    assert 'TEXT("sky-capture-weather=")' in SRC and 'TEXT("sky-capture-cloud-samples=")' in SRC
    assert "const bool bSkyCaptureHideWeather = SwitchOn(SkyCaptureWeatherMode);" in SRC
    assert "constexpr int32 SkyCaptureCloudViewSamples = 32;" in SRC
    assert "constexpr int32 SkyCaptureCloudShadowSamples = 8;" in SRC
    _order('It->Tags.Contains(FName(TEXT("FlightSim.weather")))',
           'TEXT("r.VolumetricCloud.ReflectionRaySampleMaxCount")',
           'SetObjectField(TEXT("sky_capture_cost"), CostRow);',
           "USkyLightComponent::UpdateSkyCaptureContents(World);",
           'BeatWatchdog(TEXT("restoring the scene after the sky light capture"));',
           "Held.Key->Set(*Held.Value, ECVF_SetByCode);",
           "Component->SetVisibility(true);")
