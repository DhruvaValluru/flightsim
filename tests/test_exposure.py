"""core/capture/exposure.py: EV100 by hand, refusals by name, and the two
tables (this module's preset defaults, the spec's) meeting only here.

The C++ side (FFlightSimVisualScene::ExposureValue100) cannot be compiled
in this environment; the last test pins its source expression to the
same formula so a drift between the two is a test failure, not a
surprise on the Windows box.
"""

import math
import re
from pathlib import Path

import pytest

from core.capture import exposure
from core.capture.exposure import (
    EXPOSURE_MODE_PHYSICAL, ExposureError, PRESET_DEFAULTS, describe, ev100,
    ev100_for_preset, preset_default, shutter_for_ev100,
)

REPO = Path(__file__).resolve().parents[1]
SCENE_CPP = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
             / "FlightSimVisualScene.cpp")


# -- the formula, by hand -------------------------------------------------


def test_the_contracts_example_by_hand():
    """f/8, 1/500 s, ISO 100: N^2/t = 64 * 500 = 32000; log2(32000) = 14.966."""
    by_hand = math.log(64 * 500, 2)
    assert abs(by_hand - 14.9658) < 1e-3
    assert abs(ev100(8.0, 1.0 / 500.0, 100.0) - by_hand) < 1e-9


def test_iso_moves_the_value_by_whole_stops():
    """Doubling the ISO halves the exposure needed: one stop DOWN."""
    base = ev100(8.0, 1.0 / 500.0, 100.0)
    assert abs(ev100(8.0, 1.0 / 500.0, 200.0) - (base - 1.0)) < 1e-9
    assert abs(ev100(8.0, 1.0 / 500.0, 400.0) - (base - 2.0)) < 1e-9


def test_a_second_hand_computed_triple():
    """f/2.8, 1/60 s, ISO 400: 7.84 * 60 * 100 / 400 = 117.6; log2 = 6.878."""
    assert abs(ev100(2.8, 1.0 / 60.0, 400.0) - math.log2(117.6)) < 1e-9
    assert abs(ev100(2.8, 1.0 / 60.0, 400.0) - 6.878) < 1e-3


@pytest.mark.parametrize("triple", [
    (0.0, 1 / 500, 100), (8.0, 0.0, 100), (8.0, 1 / 500, 0.0),
    (-8.0, 1 / 500, 100), ("eight", 1 / 500, 100), (8.0, None, 100),
    (True, 1 / 500, 100), (8.0, float("nan"), 100), (8.0, float("inf"), 100),
])
def test_a_triple_that_cannot_expose_is_refused_by_name(triple):
    with pytest.raises(ExposureError) as caught:
        ev100(*triple)
    assert str(caught.value).startswith("camera.exposure: ")
    assert caught.value.name == "camera.exposure"


# -- the preset table -------------------------------------------------------


def test_the_preset_defaults_agree_with_the_spec_without_importing_them():
    """exposure.py RESTATES the table; camera.py is the spec's copy. They
    meet here and nowhere else."""
    from core.scenario.camera import CAMERA_PRESETS, EXPOSURE_DEFAULTS

    source = Path(exposure.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+core\.scenario", source, re.M)
    assert set(PRESET_DEFAULTS) == set(CAMERA_PRESETS)
    for preset in CAMERA_PRESETS:
        assert tuple(map(float, PRESET_DEFAULTS[preset])) == \
            tuple(map(float, EXPOSURE_DEFAULTS[preset]))


def test_every_preset_default_is_the_daylight_triple_today():
    for preset in PRESET_DEFAULTS:
        assert preset_default(preset) == (8.0, 1.0 / 500.0, 100.0)
        assert abs(ev100_for_preset(preset) - 14.9658) < 1e-3


def test_an_unknown_preset_refuses_rather_than_guessing_a_lens():
    with pytest.raises(ExposureError, match="camera.exposure: no exposure default"):
        preset_default("drone")


# -- the inverse (how a card's EV100 reaches the engine without a triple) --


def test_shutter_for_ev100_round_trips_through_the_formula():
    for value in (0.0, 3.5, 14.9658, 20.0, -2.0):
        t = shutter_for_ev100(value)
        assert abs(ev100(1.0, t, 100.0) - value) < 1e-9
    # And with a stated lens: same EV100, different t.
    t = shutter_for_ev100(10.0, aperture_f=4.0, iso=200.0)
    assert abs(ev100(4.0, t, 200.0) - 10.0) < 1e-9


def test_shutter_for_ev100_refuses_non_numbers():
    with pytest.raises(ExposureError):
        shutter_for_ev100("bright")
    with pytest.raises(ExposureError):
        shutter_for_ev100(float("nan"))


def test_describe_names_the_number_and_the_triple():
    line = describe(8.0, 1 / 500, 100)
    assert line.startswith("EV100 14.97 ")
    assert "f/8" in line and "ISO 100" in line
    assert EXPOSURE_MODE_PHYSICAL == "manual_ev100"


# -- the C++ mirror, pinned by source text (UNCOMPILED here) ---------------


def test_the_engine_computes_the_same_expression():
    """FFlightSimVisualScene::ExposureValue100 must be log2((N*N/t)*(100/ISO)),
    not an import of anything and not a different constant."""
    source = SCENE_CPP.read_text(encoding="utf-8")
    body = re.search(r"double FFlightSimVisualScene::ExposureValue100\((.*?)\n}\n",
                     source, re.S)
    assert body, "ExposureValue100 is not defined in FlightSimVisualScene.cpp"
    text = body.group(1)
    assert "FMath::Log2((ApertureF * ApertureF / ShutterSeconds) * (100.0 / Iso))" in text


def test_the_engine_pins_the_bias_to_zero_on_the_physical_path():
    """EV100 plus an 11-stop bias is neither number; the physical path
    must override the bias to 0 and turn the physical camera exposure on."""
    source = SCENE_CPP.read_text(encoding="utf-8")
    body = re.search(r"double FFlightSimVisualScene::ApplyPhysicalExposure\((.*?)\n}\n",
                     source, re.S)
    assert body
    text = body.group(1)
    assert "AutoExposureApplyPhysicalCameraExposure = 1.0f" in text
    assert "AutoExposureBias = 0.0f" in text
    assert "AutoExposureMethod = EAutoExposureMethod::AEM_Manual" in text
    assert "CameraShutterSpeed = static_cast<float>(1.0 / ShutterSeconds)" in text
