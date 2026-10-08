"""The 3-D box's derived values (core/capture/labels.py box3d_extras):
the same box in pixels, its range, rotation, KITTI's camera-frame terms
and its world placement, checked against cases worked by hand."""

from __future__ import annotations

import math

import pytest

from core.capture.labels import box3d_camera, camera_axes

#: A level camera at 1000 m looking north (camera +x = east, +z = north).
RECORD = {"quaternion_wxyz": [1.0, 0.0, 0.0, 0.0], "position_north_m": 0.0,
          "position_east_m": 0.0, "position_alt_m": 1000.0,
          "principal_point_px": [640.0, 360.0], "fx_px": 1000.0, "fy_px": 1000.0,
          "width_px": 1280, "height_px": 720}
#: 20 m long, 30 m span, 5 m tall, the CG 0.5 m above the box centre.
BOX = {"forward": (-10.0, 10.0), "right": (-15.0, 15.0), "down": (-2.0, 3.0)}


def box_at(heading: float, east: float = 0.0):
    state = {"north_m": 100.0, "east_m": east, "alt_m": 1000.0,
             "heading_deg": heading, "pitch_deg": 0.0, "roll_deg": 0.0}
    return box3d_camera(RECORD, state, BOX, camera_axes(RECORD["quaternion_wxyz"]))


def test_the_box_in_pixels_range_size_and_world_placement():
    box = box_at(90.0)                         # 100 m ahead, nose to camera right
    assert box["centre_px"] == pytest.approx([640.0, 365.0])
    assert len(box["corners_px"]) == 8 and box["corners_in_frame"] == 8
    assert box["range_m"] == pytest.approx(100.00125, abs=1e-4)
    assert box["depth_m"] == pytest.approx(100.0)
    assert box["volume_m3"] == pytest.approx(3000.0)
    assert box["dimensions_hwl_m"] == pytest.approx([5.0, 30.0, 20.0])
    # KITTI's location is the bottom face's centre: 2.5 m below the box centre.
    assert box["location_bottom_m"] == pytest.approx([0.0, 3.0, 100.0], abs=1e-9)
    world = box["world"]
    assert (world["centre_north_m"], world["centre_east_m"]) == pytest.approx((100.0, 0.0))
    assert world["centre_alt_m"] == pytest.approx(999.5)
    assert (world["heading_deg"], world["pitch_deg"], world["roll_deg"]) == (90.0, 0.0, 0.0)


def test_kitti_rotation_y_and_alpha_follow_kitti_s_convention():
    assert box_at(90.0)["rotation_y_rad"] == pytest.approx(0.0, abs=1e-12)     # nose along +x
    assert box_at(0.0)["rotation_y_rad"] == pytest.approx(-math.pi / 2)         # nose along +z
    side = box_at(90.0, east=100.0)            # 45 deg to the right of the optical axis
    assert side["alpha_rad"] == pytest.approx(-math.pi / 4)


def test_the_rotation_matrix_and_quaternion_are_the_body_axes():
    box = box_at(90.0)
    rows = box["body_axes_in_camera"]
    matrix = box["rotation_camera"]
    for axis in range(3):
        assert [matrix[r][axis] for r in range(3)] == pytest.approx(rows[axis], abs=1e-12)
    w, x, y, z = box["quaternion_camera_wxyz"]
    assert math.sqrt(w * w + x * x + y * y + z * z) == pytest.approx(1.0)
    # Body forward (1, 0, 0) rotated by the quaternion lands on the first row.
    rotated = (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y))
    assert list(rotated) == pytest.approx(rows[0], abs=1e-9)
    assert w >= 0.0                                                             # one sign


def test_a_box_behind_the_camera_has_no_pixels_and_says_so():
    state = {"north_m": -100.0, "east_m": 0.0, "alt_m": 1000.0,
             "heading_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0}
    box = box3d_camera(RECORD, state, BOX, camera_axes(RECORD["quaternion_wxyz"]))
    assert box["centre_px"] is None and box["corners_in_frame"] == 0
    assert all(uv is None for uv in box["corners_px"])
