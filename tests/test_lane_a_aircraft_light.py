"""Lane A (2026-11-11, "the planes are being too shadowed"): the aircraft's
light under a deck and its exposure in clear sun. Beauty only."""

import re
from pathlib import Path

import pytest

from core.scene import beauty_look as bl
from core.scene import hero_lighting as hl

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
HERO_CPP = (PRIVATE / "FlightSimHeroLighting.cpp").read_text(encoding="utf-8")
COMMANDLET_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")


# -- the sky light's cloud AO: counted once ---------------------------------------


def test_cloud_ao_is_off_when_the_capture_already_holds_the_clouds():
    assert hl.SKY_CLOUD_AO_DEFAULT == "auto"
    assert hl.sky_cloud_ao_applies() is False                      # the defaults: at the aircraft, clouds shown
    assert hl.sky_cloud_ao_applies("auto", capture_clouds=0) is True
    assert hl.sky_cloud_ao_applies("auto", capture_at="origin") is True
    assert hl.sky_cloud_ao_applies("on") is True
    assert hl.sky_cloud_ao_applies("off", capture_clouds=0) is False
    with pytest.raises(hl.HeroLightingError, match="render.sky_fill_probe"):
        hl.sky_cloud_ao_applies("maybe")


def test_the_host_decides_the_cloud_ao_as_the_twin_does():
    block = HERO_CPP[HERO_CPP.index('FString CloudAo = TEXT("auto");'):
                     HERO_CPP.index('Probe->SetStringField(TEXT("sky_cloud_ao"), CloudAo);')]
    assert 'FParse::Value(*Switches, TEXT("sky-capture-clouds="), CaptureClouds);' in block
    assert 'FParse::Value(*Switches, TEXT("sky-capture-at="), CaptureAt);' in block
    assert 'CaptureClouds != 0 && CaptureAt == TEXT("aircraft")' in block
    assert "Sky->bCloudAmbientOcclusion = false;" in block
    # the commandlet's own defaults are the ones the twin assumes
    assert "int32 SkyCaptureClouds = 1;" in COMMANDLET_CPP
    assert 'FString SkyCaptureAt = TEXT("aircraft");' in COMMANDLET_CPP
    assert hl.parse_diagnostic_switches("-sky-cloud-ao=auto") == {"sky-cloud-ao": "auto"}


# -- SSAO at the airframe's scale ---------------------------------------------------


@pytest.mark.parametrize("preset", bl.ENGINE_LOOK_PRESETS)
def test_ssao_radius_is_world_space_at_airframe_scale(preset):
    values = bl.engine_look_for(preset)["ssao"]["values"]
    assert values["AmbientOcclusionRadiusInWS"] is True
    assert values["AmbientOcclusionRadius"] == bl.AO_RADIUS_WS_CM
    assert 100.0 <= bl.AO_RADIUS_WS_CM <= 400.0
    assert "AO_RADIUS_WS_CM" in bl.UNCALIBRATED


# -- the subject meter ---------------------------------------------------------------


def test_the_host_constants_are_the_twins():
    pairs = {"SubjectMeterHighlightP97": "highlight_p97", "SubjectMeterHighlightTarget": "highlight_target_p97",
             "SubjectMeterMidFloorP50": "mid_floor_p50", "SubjectMeterMidTarget": "mid_target_p50",
             "SubjectMeterMaxCloseStops": "max_close_stops", "SubjectMeterMaxOpenStops": "max_open_stops",
             "SubjectMeterSaturatedStepStops": "saturated_step_stops",
             "SubjectMeterHighPercentile": "high_percentile", "SubjectMeterRounds": "rounds",
             "SubjectMeterMaskLumaDelta": "mask_luma_delta", "SubjectMeterMinPixels": "min_pixels"}
    for cpp, key in pairs.items():
        match = re.search(rf"constexpr (?:double|int32) {cpp} = ([0-9.]+);", COMMANDLET_CPP)
        assert match, cpp
        assert float(match.group(1)) == pytest.approx(float(bl.SUBJECT_METER[key])), cpp
    frame = re.search(r"constexpr double BeautyMeterHighlightP90 = ([0-9.]+);", COMMANDLET_CPP)
    assert float(frame.group(1)) == bl.FRAME_HIGHLIGHT_P90
    assert "SUBJECT_METER" in bl.UNCALIBRATED


def _settle(p50, p97, frame_p90, gain_per_stop=2 ** (1 / 2.2)):
    """Run the twin against a toy subject whose sRGB luma scales with exposure."""
    stops = 0.0
    for _ in range(int(bl.SUBJECT_METER["rounds"]) - 1):
        step = bl.subject_meter_step(p50, p97, frame_p90, stops)
        if step == 0.0:
            break
        stops += step
        k = gain_per_stop ** step
        p50, p97, frame_p90 = min(p50 * k, 1.0), min(p97 * k, 1.0), min(frame_p90 * k, 1.0)
    return stops, p50, p97


def test_a_clipped_white_airframe_is_closed_below_clipping():
    stops, p50, p97 = _settle(0.85, 1.0, 0.45)          # round 4's #13: the frame dark, the 747 blown
    assert stops < 0.0
    assert p97 <= bl.SUBJECT_METER["highlight_p97"] + 0.02
    assert stops >= -bl.SUBJECT_METER["max_close_stops"]


def test_a_black_airframe_under_a_bright_deck_is_opened():
    stops, p50, p97 = _settle(0.06, 0.15, 0.7)          # round 5's #06: the A320 black under the cloud base
    assert stops > 0.0
    assert stops <= bl.SUBJECT_METER["max_open_stops"]
    assert p97 <= bl.SUBJECT_METER["highlight_p97"]


def test_a_well_exposed_airframe_and_a_clipping_frame_are_left_alone():
    assert bl.subject_meter_step(0.5, 0.85, 0.6, 0.0) == 0.0
    assert bl.subject_meter_step(0.1, 0.3, 0.95, 0.0) == 0.0  # the frame clips: never opened further
    # a dark subject is never opened past its own highlight bound
    assert bl.subject_meter_step(0.2, 0.93, 0.5, 0.0) == pytest.approx(0.0, abs=0.05)


def test_the_subject_meter_is_beauty_only_and_owned_by_the_look():
    start = COMMANDLET_CPP.index("// -- lane A (2026-11-11): the subject meter")
    block = COMMANDLET_CPP[start:COMMANDLET_CPP.index("// -- Phase 8B.0: the real-time probe loop")]
    assert ("if (bVisual && bBeauty && !bPathTrace && !bAutoExposure && !bHideAircraft && "
            "Scenario.Aircraft != nullptr") in block
    assert "FFlightSimBeautyLook::OwnsExposure()" in block
    assert 'TEXT("subject-meter=")' in block and "render.subject_meter:" in block
    assert "Capture->HiddenActors.Remove(Scenario.Aircraft);" in block
    assert 'SetObjectField(TEXT("subject_exposure"), SubjectRow)' in block
    assert "return State.bApplied && State.bExposureApplied;" in LOOK_CPP
    catalog = (REPO / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    assert "render.subject_meter:" in catalog
