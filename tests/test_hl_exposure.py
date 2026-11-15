"""hl-exposure (2026-11-15): one physical exposure per shot and grain only at
high ISO (core/scene/beauty_look.py EXPOSURE_ANCHORS, film_grain_for model
iso; host FlightSimBeautyLook.cpp). Numeric checks on the Python, and
source-reading checks on the C++ twin (nothing renders on this machine)."""

import math
from pathlib import Path

import pytest

from core.capture.exposure import DAYLIGHT_TRIPLE, ev100
from core.scene import beauty_look as bl
from core.scene.beauty_look import BeautyLookError

REPO = Path(__file__).resolve().parents[1]
LOOK_CPP = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimBeautyLook.cpp"
            ).read_text(encoding="utf-8")


def plan(elevation=20.0, **kw):
    return bl.plan_beauty_look(elevation, fps=30.0, width_px=1920, **kw)


# -- the exposure anchor --------------------------------------------------------


def test_a_clear_frame_is_anchored_to_the_incident_meter_by_default():
    meter = plan(world_preset="clear")["exposure"]["meter"]
    assert meter["deck"] is False
    assert meter["clear_no_lumen_gi"] == bl.DEFAULT_EXPOSURE_ANCHOR == "incident"
    assert bl.EXPOSURE_ANCHORS == ("incident", "frame")
    assert "-exposure-anchor=frame" in meter["when"]


@pytest.mark.parametrize("preset", bl.DECK_PRESETS)
def test_a_deck_still_meters_its_own_darkness(preset):
    meter = plan(world_preset=preset)["exposure"]["meter"]
    assert meter["deck"] is True
    assert meter["target_p90_luma"] == bl.EXPOSURE_METER_TARGET_P90[preset]


def test_the_incident_exposure_puts_sunlit_white_paint_below_clipping():
    # ISO 12232: saturation 7.8x mid-grey. An 0.9-albedo white at the incident
    # exposure is 0.9/0.18 = 5x the grey card's scene-linear 0.18 -> ~0.9-1.0,
    # which the camera's filmic curve keeps under the subject meter's 0.94
    # highlight bound (round 199's #13 airframe read 0.82-0.87): the subject
    # meter need not close a correctly exposed white aircraft.
    srgb = lambda x: 1.055 * x ** (1 / 2.4) - 0.055
    white = srgb(bl.film_tone_curve(0.18 * 0.9 / 0.18))
    assert 0.84 < white < bl.SUBJECT_METER["highlight_p97"]
    assert srgb(bl.film_tone_curve(0.18)) == pytest.approx(0.461, abs=0.002)


def test_the_host_reads_the_anchor_and_its_switch():
    block = LOOK_CPP[LOOK_CPP.index("else if (!bLumenGi)"):]
    block = block[:block.index("MeterEcho->SetStringField(TEXT(\"runs\"), TEXT(\"no: no deck, and Lumen GI runs\"));")]
    assert 'TEXT("clear_no_lumen_gi")' in block
    assert 'TEXT("exposure-anchor=")' in block
    assert 'FString Anchor = TEXT("frame");' in block      # an older sidecar keeps the old meter
    assert 'State.MeterTrigger = TEXT("no_lumen_gi");' in block
    assert "-exposure-anchor=%s is not incident or frame" in block
    assert block.index('if (Anchor == TEXT("frame"))') < block.index("State.bMeter = true;")


# -- grain from ISO ---------------------------------------------------------------


def test_the_daylight_camera_is_base_iso_and_noise_free_in_sun():
    assert ev100(*DAYLIGHT_TRIPLE) == pytest.approx(14.966, abs=1e-3)
    assert bl.equivalent_iso(15.0) == bl.BASE_ISO
    assert bl.equivalent_iso(ev100(*DAYLIGHT_TRIPLE)) == pytest.approx(100.0)
    # 50,000 e- / 7.8 at mid-grey -> 1.25 % -> 0.69 of an 8-bit code.
    assert bl.grain_sigma_codes(100.0) == pytest.approx(0.685, abs=0.005)
    assert bl.ISO_GRAIN_VISIBLE == pytest.approx(213.0, abs=1.0)
    assert bl.iso_grain_factor(100.0) == 0.0
    assert bl.iso_grain_factor(bl.ISO_GRAIN_VISIBLE) == pytest.approx(0.0, abs=1e-6)


def test_noise_grows_as_the_square_root_of_iso():
    # Poisson shot noise: 4x the ISO, 2x the sigma.
    assert bl.grain_sigma_codes(1600.0) / bl.grain_sigma_codes(400.0) == pytest.approx(2.0)
    assert bl.equivalent_iso(14.966 - 4.0) == pytest.approx(1600.0, rel=1e-3)
    s = bl.grain_sigma_codes(1600.0)
    assert bl.iso_grain_factor(1600.0) == pytest.approx(math.sqrt(s * s - 1.0))
    assert bl.equivalent_iso(-5.0) == bl.ISO_GRAIN_CAP


def test_a_sunlit_frame_has_no_grain_and_a_storm_has_more_than_a_dim_dawn():
    clear = plan(60.0, world_preset="clear")["engine_look"]["film_grain"]["values"]
    assert clear["grain_model"] == "iso" and clear["equivalent_iso"] == 100.0
    assert clear["FilmGrainIntensity"] == 0.0
    assert clear["FilmGrainIntensityPreset"] == pytest.approx(bl.GRAIN_STRENGTH)
    storm = plan(20.0, world_preset="storm")["engine_look"]["film_grain"]["values"]
    assert storm["equivalent_iso"] > 400.0
    expected = bl.GRAIN_STRENGTH * bl.iso_grain_factor(storm["equivalent_iso"])
    assert storm["FilmGrainIntensity"] == pytest.approx(expected, abs=1e-5)
    assert storm["FilmGrainIntensity"] > 0.0


def test_no_exposure_target_keeps_the_preset_grain_and_bad_input_refuses():
    row = bl.film_grain_for("rain")
    assert row["grain_model"] == "preset"
    assert row["FilmGrainIntensity"] == pytest.approx(bl.GRAIN_STRENGTH * 1.3)
    assert bl.film_grain_for("rain", ev100=11.0, model="preset")["FilmGrainIntensity"] == \
        pytest.approx(bl.GRAIN_STRENGTH * 1.3)
    with pytest.raises(BeautyLookError):
        bl.film_grain_for("rain", ev100=11.0, model="film")
    with pytest.raises(BeautyLookError):
        bl.film_grain_for("rain", ev100=float("nan"))


def test_the_host_applies_the_preset_grain_under_its_switch():
    start = LOOK_CPP.index('BeautyLookEffect(TEXT("film_grain")')
    block = LOOK_CPP[start:LOOK_CPP.index('BeautyLookEffect(TEXT("volumetric_fog")')]
    assert 'TEXT("grain-model=")' in block
    assert 'TryGetNumberField(TEXT("FilmGrainIntensityPreset"), PresetGrain)' in block
    assert "Settings.FilmGrainIntensity = static_cast<float>(PresetGrain);" in block
    assert "-grain-model=%s is not iso or preset" in block
    # The ISO grain is applied first (the macro), the preset only on the switch.
    assert block.index("FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainIntensity)") < \
        block.index('if (GrainModel == TEXT("preset") && bHasPreset)')
