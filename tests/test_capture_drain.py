"""#9 TDR (2026-11-16): 3 in 14 Windows iGPU runs lost the device (887a0006) on
Map(TempTexture2D, D3D11_MAP_READ), the first readback 17-21 s after "exposure
meter: settled": the storm meter's settle captures and the subject meter's
hidden/shown captures queued with no drain. -capture-drain=auto|on|off (auto:
the constrained GPU only) drains after each meter, settle, re-warm and frame
capture. A drain only waits, so pixels and labels do not move (source checks)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMMANDLET = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp"
              ).read_text(encoding="utf-8")
CATALOG = yaml.safe_load((ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8"))


def _after(beat):
    """The source between a capture's watchdog beat and the next statement block."""
    i = COMMANDLET.index(f'BeatWatchdog(TEXT("{beat}"));')
    return COMMANDLET[i:i + 200]


def test_the_switch_defaults_to_the_constrained_gpu_and_refuses_by_name():
    assert 'FString CaptureDrainMode = TEXT("auto");' in COMMANDLET
    assert 'FParse::Value(*RenderSwitches, TEXT("capture-drain="), CaptureDrainMode);' in COMMANDLET
    assert "const bool bCaptureDrain = SwitchOn(CaptureDrainMode);" in COMMANDLET
    assert 'TEXT("render.sky_capture_switch: -capture-drain=%s takes auto, on or off")' in COMMANDLET
    assert "-capture-drain" in CATALOG["render.sky_capture_switch"]["hint"]
    for key in ("capture_drain_switch", "capture_drain"):
        assert f'TEXT("{key}")' in COMMANDLET
    assert "capture-drain %s (%s)" in COMMANDLET


def test_every_meter_and_frame_capture_drains_before_its_readback():
    lam = COMMANDLET[COMMANDLET.index("auto DrainCapture = [&](const TCHAR* Stage, bool bQuiet)"):]
    assert "if (bCaptureDrain)" in lam[:lam.index("\n\t};\n")]
    for beat in ("an exposure meter capture", "an exposure settle capture", "a subject meter capture",
                 "a subject meter settle capture", "a subject meter re-warm capture",
                 "a beauty sub-frame capture", "a frame capture"):
        assert f'DrainCapture(TEXT("{beat}"), ' in _after(beat), beat
    # the subject meter's captures drain before its ReadPixels
    read = COMMANDLET[COMMANDLET.index("auto SubjCaptureRead = "):]
    read = read[:read.index("return bSubjRead")]
    assert read.index("DrainCapture(") < read.index("ReadPixels(SubjOut)")


def test_a_drain_changes_no_render_state():
    lam = COMMANDLET[COMMANDLET.index("auto DrainGpuNow = "):]
    lam = lam[:lam.index("\n\t};\n")]
    for word in ("PostProcessSettings", "HiddenActors", "CaptureScene", "TdrDelay", "RegSetValue"):
        assert word not in lam, word
    assert not re.search(r"TdrDelay|TdrLevel", COMMANDLET)
