"""S1: the velocity-line motion blur -- the tap rule and the symmetric
window by hand, a moving synthetic edge blurring by |f| t_exp / dt within
0.25 px, exposure 0 leaving the frame identical (the null), the engine's
accumulation recorded and never blurred twice.

Measured here (2026-09-29), streak read off the line spread function's
variance with the tap factor removed: L 2.0 px -> 2.19, 3.85 -> 4.04,
5.0 -> 5.17, 6.0 -> 6.13, 10.0 -> 10.09 (edge at three sub-pixel
positions, largest error 0.19 px); below 2 px the three bilinear taps
are wider than the streak (0.5 -> 1.0 px, 1.0 -> 1.41 px), stated.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.capture import blur as B
from core.capture import optics as O
from core.capture.profile import apply_profile_detailed, load_profile
from core.records import AppliedVariable


def edge_frame(centre_x: float, width: int = 200, height: int = 8):
    """An anti-aliased 0..1 step edge (area-sampled) at centre_x."""
    return O.slanted_edge_image(width, height, 0.0, 0.0, 1.0, centre_x=centre_x, antialias=True)[
        ..., None].repeat(3, axis=2)


# -- the rule and the window by hand ------------------------------------------------------------

def test_the_tap_count_is_max_3_ceil_2l():
    assert B.tap_count(0.0) == 3 and B.tap_count(0.9) == 3 and B.tap_count(1.0) == 3
    assert B.tap_count(1.6) == 4 and B.tap_count(2.4) == 5 and B.tap_count(6.0) == 12
    assert B.tap_count(6.0) == max(3, math.ceil(2 * 6.0))
    with pytest.raises(B.MotionBlurError, match="sensing.motion_blur"):
        B.tap_count(1e5)
    with pytest.raises(B.MotionBlurError, match="sensing.motion_blur"):
        B.tap_count(-1.0)


def test_the_window_is_symmetric_and_spans_the_streak():
    offsets = B.tap_offsets(12, 6.0)
    assert len(offsets) == 12 and offsets[0] == -3.0 and offsets[-1] == 3.0
    assert all(a == pytest.approx(-b) for a, b in zip(offsets, reversed(offsets)))
    assert sum(offsets) == pytest.approx(0.0, abs=1e-12)
    assert max(b - a for a, b in zip(offsets, offsets[1:])) <= 6.0 / (2 * 6.0 - 1) + 1e-12   # L / (2L - 1)
    assert B.tap_offsets(3, 0.0) == (0.0, 0.0, 0.0)
    with pytest.raises(B.MotionBlurError):
        B.tap_offsets(1, 2.0)


def test_the_streak_length_is_flow_times_exposure_over_dt():
    assert B.blur_length_px(6.0, 0.1, 0.1) == pytest.approx(6.0)
    assert B.blur_length_px(-25.0, 0.02, 0.1) == pytest.approx(5.0)
    assert B.blur_length_px(3.3, 1 / 500, 0.1) == pytest.approx(0.066)
    with pytest.raises(B.MotionBlurError, match="sensing.motion_blur"):
        B.blur_length_px(1.0, 0.1, 0.0)
    with pytest.raises(B.MotionBlurError, match="sensing.motion_blur"):
        B.blur_length_px(1.0, -0.1, 0.1)


# -- measured, not asserted ---------------------------------------------------------------------------

@pytest.mark.parametrize("length_px", [2.0, 3.85, 5.0, 6.0, 10.0])
@pytest.mark.parametrize("edge_fraction", [0.0, 0.3, 0.5])
def test_a_moving_edge_blurs_by_the_streak_length_within_a_quarter_pixel(length_px, edge_fraction):
    frame = edge_frame(100.0 + edge_fraction)
    dt = 0.1
    exposure = 0.01
    flow = (length_px * dt / exposure, 0.0)                    # |f| t_exp / dt = length_px
    out, block = B.velocity_line_blur(frame, flow, exposure, dt)
    assert block["taps"] == B.tap_count(length_px) and block["blur_px_max"] == pytest.approx(length_px)
    measured = B.streak_length_px(out[4, :, 0], frame[4, :, 0], block["taps"])
    assert abs(measured - length_px) < 0.25, (length_px, edge_fraction, measured)
    # The streak's direction does not change its length.
    back, _ = B.velocity_line_blur(frame, (-flow[0], 0.0), exposure, dt)
    assert abs(B.streak_length_px(back[4, :, 0], frame[4, :, 0], block["taps"]) - measured) < 1e-9


def test_below_two_pixels_the_taps_are_wider_than_the_streak_and_say_so():
    frame = edge_frame(100.3)
    for length, apparent in ((0.5, 1.0), (1.0, 1.414)):
        out, block = B.velocity_line_blur(frame, (length, 0.0), 0.1, 0.1)
        assert block["sub_pixel_taps"] is True and block["taps"] == 3
        measured = B.streak_length_px(out[4, :, 0], frame[4, :, 0], 3)
        assert measured == pytest.approx(apparent, abs=0.05)
    assert B.MIN_STREAK_CLAIMED_PX == 2.0


def test_exposure_zero_leaves_the_frame_identical_the_null():
    frame = edge_frame(100.3)
    out, block = B.velocity_line_blur(frame, (6.0, 2.0), 0.0, 0.1)
    assert out is frame and block["taps"] == 3 and block["blur_px_max"] == 0.0
    assert block["applied_by"] == "python_velocity_line" and block["sub_pixel"] is True
    record = B.blur_record(block, float(np.abs(np.asarray(out) - frame).max()))
    assert record.null_test.ok and record.null_test.kind == "bounded" and record.null_test.with_value == 0.0
    assert record.readback.agrees and record.readback.value == 3.0
    assert AppliedVariable.from_dict(record.to_dict()).to_dict() == record.to_dict()
    # A zero flow at a non-zero exposure is the same null.
    still, block = B.velocity_line_blur(frame, (0.0, 0.0), 0.5, 0.1)
    assert still is frame and block["blur_px_max"] == 0.0


def test_a_flow_field_blurs_each_pixel_by_its_own_streak():
    frame = np.zeros((10, 60, 3))
    frame[:, 15:, :] = 1.0                     # an edge at x = 15
    frame[:, 45:, :] = 0.0                     # and another at x = 45
    field = np.zeros((10, 60, 2))
    field[:, 30:, 0] = 40.0                    # only the right half moves
    out, block = B.velocity_line_blur(frame, field, 0.01, 0.1)
    assert block["flow_source"] == "field" and block["blur_px_max"] == pytest.approx(4.0)
    assert np.array_equal(out[:, :25], frame[:, :25])            # the still half is untouched
    assert not np.array_equal(out[:, 40:50], frame[:, 40:50])     # the moving edge is smeared
    assert block["blur_px_mean"] == pytest.approx(2.0)
    with pytest.raises(B.MotionBlurError, match="sensing.motion_blur"):
        B.velocity_line_blur(frame, np.zeros((10, 61, 2)), 0.01, 0.1)
    with pytest.raises(B.MotionBlurError, match="sensing.motion_blur"):
        B.velocity_line_blur(frame, (float("nan"), 0.0), 0.01, 0.1)


def test_edges_are_clamped_not_darkened():
    frame = np.ones((6, 40, 3))
    out, _ = B.velocity_line_blur(frame, (100.0, 0.0), 0.01, 0.1)
    assert np.allclose(out, 1.0)


# -- the engine's accumulation (S4) ------------------------------------------------------------------

def test_an_engine_accumulation_is_recorded_and_never_blurred_twice(tmp_path):
    assert B.engine_accumulation_of({"accumulation": {"k": 4, "t0_s": 1.0, "t1_s": 1.002}}) == {
        "k": 4, "t0_s": 1.0, "t1_s": 1.002}
    assert B.engine_accumulation_of({"accumulation": {"k": 1}}) is None
    assert B.engine_accumulation_of({}) is None and B.engine_accumulation_of(None) is None
    block = B.engine_accumulation_block({"k": 4, "t0_s": 1.0, "t1_s": 1.002}, 0.002)
    assert block["applied_by"] == "engine_accumulation" and block["taps"] is None
    record = B.blur_record(block, 0.0)
    assert record.readback is None and record.parameters["k"] == 4
    # Through the profile: a motion_blur profile with an accumulation block
    # returns the frame untouched and records the engine's k.
    data = json.loads((Path(__file__).resolve().parents[1] / "assets/camera_profiles/ideal_pinhole.json")
                      .read_text(encoding="utf-8"))
    data["name"] = "blur_test"
    data["motion_blur"] = {"model": "velocity_line", "dt_s": 0.1}
    (tmp_path / "blur_test.json").write_text(json.dumps(data), encoding="utf-8")
    profile = load_profile("blur_test", profile_dir=tmp_path)
    rec = {"width_px": 60, "height_px": 10, "fx_px": 58.0, "fy_px": 58.0, "principal_point_px": [30.0, 5.0]}
    frame = edge_frame(30.3, 60, 10)
    out, blocks = apply_profile_detailed(frame, profile, rec, (0.0, 1.0, 0.0), 1, exposure_s=0.02,
                                         engine_accumulation={"k": 3, "t0_s": 0.0, "t1_s": 0.02})
    assert blocks["blur"]["applied_by"] == "engine_accumulation" and blocks["stages"] == ["blur", "adc"]
    assert np.array_equal(out, np.round(frame * 255.0) / 255.0)
    # Without an accumulation the camera's own yaw rate blurs the frame:
    # fx x w_y x dt = 58 x 1 x 0.1 = 5.8 px per dt; over 0.02 s that is 1.16 px.
    moved, blocks = apply_profile_detailed(frame, profile, rec, (0.0, 1.0, 0.0), 1, exposure_s=0.02)
    assert blocks["blur"]["flow_source"] == "camera_angular_rate"
    assert blocks["blur"]["blur_px_max"] == pytest.approx(58.0 * 1.0 * 0.1 * 0.02 / 0.1)
    assert not np.array_equal(moved, out)


@pytest.mark.parametrize("block, fragment", [
    ({"model": "box"}, "not modelled"),
    ({"model": "velocity_line", "dt_s": 0}, "positive"),
    ({"model": "velocity_line", "engine_accumulation": "yes"}, "true or false"),
    ({"model": "velocity_line", "taps": 5}, "unknown keys"),
    (7, "mapping"),
])
def test_a_malformed_motion_blur_block_refuses_sensing_motion_blur(block, fragment):
    with pytest.raises(B.MotionBlurError) as info:
        B.check_motion_blur_block(block)
    assert info.value.constraint == "sensing.motion_blur" and fragment in info.value.message
    assert B.check_motion_blur_block({"model": "velocity_line"}) == {
        "model": "velocity_line", "dt_s": 0.1, "engine_accumulation": False}
