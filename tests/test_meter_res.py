"""#9 TDR, part 2 (2026-11-16): drained, every #9 capture still took 3.3-3.75 s
on the Windows iGPU and run 1431 hung inside the subject meter's second
(hidden-aircraft) capture. -meter-res=auto|full|half|quarter renders the meters'
metering captures at a reduced size (auto: half on the constrained GPU) and
puts the beauty target back to full size before any settle, re-warm or frame
capture. Numeric: the meters' percentiles over a reduced frame stay inside
their tolerance. Source: the switch, the record, the restore order."""
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

from core.scene.beauty_look import (METER_RES_DIVISORS, meter_luma_code, meter_percentile,
                                    subject_meter_step)

ROOT = Path(__file__).resolve().parents[1]
COMMANDLET = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp"
              ).read_text(encoding="utf-8")
CATALOG = yaml.safe_load((ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8"))
STORM_METER_TOLERANCE = 0.05   # the host's StormMeterTolerance (p90 luma)


# -- numeric: the percentile code over a full vs reduced synthetic frame ------

def _storm_frame(w=1280, h=720, seed=9):
    """A #9-like frame (sRGB codes): a dark storm sky with a brighter band and
    a lit cloud flank, rain-like noise, and a 747-ish body (grey fuselage, a
    sunlit top, a specular streak) over it. Returns (rgb uint8, aircraft mask)."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    sky = 30 + 50 * (1 - y / h) + 40 * np.exp(-(((x - 0.8 * w) / (0.15 * w)) ** 2 + ((y - 0.3 * h) / (0.2 * h)) ** 2))
    sky += rng.normal(0, 6, size=sky.shape)
    body = (np.abs(y - 0.55 * h) < 0.06 * h) & (np.abs(x - 0.5 * w) < 0.35 * w)
    wing = (np.abs(y - 0.6 * h - 0.25 * (x - 0.5 * w)) < 0.015 * h) & (np.abs(x - 0.5 * w) < 0.25 * w)
    mask = body | wing
    plane = 90 + 70 * np.clip((0.55 * h - y) / (0.06 * h) + 0.5, 0, 1) + rng.normal(0, 4, size=sky.shape)
    streak = mask & (np.abs(y - 0.51 * h) < 0.006 * h)
    plane = np.where(streak, 250, plane)
    luma = np.where(mask, plane, sky)
    rgb = np.clip(np.stack([luma * 0.95, luma, luma * 1.08], axis=-1), 0, 255)
    return rgb, mask


def _reduce(img, d, how):
    """What a capture at 1/d per axis sees: an area average (the AA'd render)
    or a point sample (no AA), both the same field of view."""
    if d == 1:
        return img
    h, w = img.shape[0] // d * d, img.shape[1] // d * d
    img = img[:h, :w]
    if how == "point":
        return img[d // 2::d, d // 2::d]
    shape = (h // d, d, w // d, d) + img.shape[2:]
    return img.reshape(shape).mean(axis=(1, 3))


def _codes(rgb):
    rgb = np.clip(rgb + 0.5, 0, 255).astype(np.int64)   # the capture's 8-bit sRGB
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    return np.clip((luma + 0.5).astype(np.int64), 0, 255)


def _meter(rgb, mask):
    codes = _codes(rgb)
    frame = codes.ravel().tolist()
    subj = codes[mask].ravel().tolist()
    return (meter_percentile(frame, 0.90), meter_percentile(subj, 0.50), meter_percentile(subj, 0.97))


def test_the_twin_bins_like_the_host():
    assert meter_luma_code(255, 255, 255) == 255 and meter_luma_code(0, 0, 0) == 0
    assert meter_percentile([0] * 9 + [255], 0.90) == 0.0
    assert meter_percentile([0] * 8 + [255] * 2, 0.90) == 1.0
    assert meter_percentile(list(range(256)), 0.5) == 127 / 255.0


@pytest.mark.parametrize("how", ["area", "point"])
@pytest.mark.parametrize("name", ["half", "quarter"])
def test_reduced_percentiles_stay_inside_the_meters_tolerance(name, how):
    d = METER_RES_DIVISORS[name]
    rgb, mask = _storm_frame()
    full = _meter(rgb, mask)
    small_mask = _reduce(mask.astype(np.float64), d, how) >= 0.5
    red = _meter(_reduce(rgb, d, how), small_mask)
    p90, p50, p97 = (abs(a - b) for a, b in zip(full, red))
    # the frame meter's p90 is held to +-StormMeterTolerance; a reduced frame moves it far less
    assert p90 <= STORM_METER_TOLERANCE / 5, (full, red)
    # the subject meter's median and highlight: within a few codes
    assert p50 <= 0.02 and p97 <= (0.03 if d == 2 else 0.06), (full, red)
    # and the step the subject meter takes differs by under a tenth of a stop
    # (half; quarter is the A/B arm): its own settle band is 0.05 stops
    s_full = subject_meter_step(full[1], full[2], full[0], 0.0)
    s_red = subject_meter_step(red[1], red[2], red[0], 0.0)
    assert abs(s_full - s_red) <= (0.1 if d == 2 else 0.25), (s_full, s_red)


def test_a_dark_subject_opens_the_same_at_full_and_half():
    rgb, mask = _storm_frame()
    rgb = rgb * 0.35   # the #9 case: the subject meter opens a dark 747
    full = _meter(rgb, mask)
    red = _meter(_reduce(rgb, 2, "area"), _reduce(mask.astype(np.float64), 2, "area") >= 0.5)
    s_full = subject_meter_step(full[1], full[2], full[0], 0.0)
    s_red = subject_meter_step(red[1], red[2], red[0], 0.0)
    assert s_full > 0 and abs(s_full - s_red) <= 0.1, (s_full, s_red)


# -- source: the switch, the record, the restore order ------------------------

def test_the_switch_refuses_by_name_and_is_recorded_and_logged():
    assert 'FString MeterResMode = TEXT("auto");' in COMMANDLET
    assert 'FParse::Value(*RenderSwitches, TEXT("meter-res="), MeterResMode);' in COMMANDLET
    assert 'TEXT("render.sky_capture_switch: -meter-res=%s takes auto, full, half or quarter")' in COMMANDLET
    assert "-meter-res" in CATALOG["render.sky_capture_switch"]["hint"]
    for key in ("meter_res_switch", "meter_res_divisor", "meter_resizes"):
        assert f'TEXT("{key}")' in COMMANDLET, key
    assert 'TEXT("meter-res %s (1/%d)")' in COMMANDLET
    i = COMMANDLET.index("const int32 MeterResDivisor = ")
    rule = COMMANDLET[i:COMMANDLET.index(";", i)]
    # measure never reduces; auto reduces on the constrained GPU only
    assert rule.index("!bBeautyRasterRun ? 1") < rule.index('TEXT("half") ? 2')
    assert '(MeterResMode == TEXT("auto") && bConstrainedGpu) ? 2' in rule
    assert {"full": 1, "half": 2, "quarter": 4} == METER_RES_DIVISORS


def _between(a, b, start=0):
    i = COMMANDLET.index(a, start)
    return COMMANDLET[i:COMMANDLET.index(b, i)]


def test_full_size_is_back_before_every_settle_rewarm_and_frame_capture():
    storm = _between("SetMeterRes(true, TEXT(\"the exposure meter's rounds\"));", 'TEXT("exposure meter: settled")')
    assert storm.index("SetMeterRes(false,") < storm.index('BeatWatchdog(TEXT("an exposure settle capture"))')
    subj = _between('SetMeterRes(true, TEXT("the subject meter\'s captures"));', 'TEXT("subject exposure: %d')
    restore = subj.index("SetMeterRes(false,")
    for beat in ("a subject meter settle capture", "a subject meter re-warm capture"):
        assert restore < subj.index(f'BeatWatchdog(TEXT("{beat}"))'), beat
    for beat in ("a subject meter capture", "a subject meter readback"):
        assert subj.index(f'BeatWatchdog(TEXT("{beat}"))') < restore, beat
    # the frames always start at full size, whatever meter ran
    tail = COMMANDLET.index('SetMeterRes(false, TEXT("the frames"));')
    assert tail < COMMANDLET.index('BeatWatchdog(TEXT("a beauty sub-frame capture"))')
    assert tail < COMMANDLET.index('BeatWatchdog(TEXT("a frame capture"))')
    # the sub-frames and the frame are never reduced: no SetMeterRes(true after the frames' restore
    assert "SetMeterRes(true" not in COMMANDLET[tail:]


def test_the_resize_touches_only_the_target_size():
    lam = _between("auto SetMeterRes = [&](bool bReduced, const TCHAR* Stage)", "\n\t};\n")
    assert "RenderTarget->ResizeTarget(MeterW, MeterH);" in lam
    assert "if (MeterResDivisor <= 1)" in lam
    for word in ("PostProcessSettings", "HiddenActors", "CaptureScene", "FOVAngle", "TdrDelay"):
        assert word not in lam, word
    assert not re.search(r"TdrDelay|TdrLevel|RegSetValue", COMMANDLET)


def test_reduced_mask_rules():
    assert "SubjCaptureRead(SubjHidden, bSubjectReduced ? 1 : 2, bSubjectReduced)" in COMMANDLET
    assert "SubjCaptureRead(SubjShown, 3, bSubjectReduced)" in COMMANDLET
    assert "SubjectMeterMinPixels / (MeterResDivisor * MeterResDivisor)" in COMMANDLET
    assert "SubjMaskPixels >= SubjMinPixels" in COMMANDLET
    # the settle after a reduced meter starts from a camera cut (history size changed)
    assert COMMANDLET.count("Capture->bCameraCutThisFrame = true;") >= 4
