"""Camera Phase 1, package I: the geometry preview, graded pixel by pixel.

Synthetic frame records with a KNOWN camera and aircraft pose, drawn
through core.capture.preview, and the drawn geometry checked against
the manifest's own projection (core.capture.verify.project_point):
the horizon row, the aircraft body centre, the wing-tip separation,
near-plane clipping, the default resolution, the header text, the
overlay, the contact sheet and the render time.
"""

import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.capture import preview as pv
from core.capture.poses import euler_to_quat
from core.capture.verify import axes_from_euler, axes_from_quat, project_point

WIDTH, HEIGHT = 1280, 720
FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM = 35.0, 36.0, 20.25
FX = FOCAL_MM * WIDTH / SENSOR_W_MM            # 1244.4 px
FY = FOCAL_MM * HEIGHT / SENSOR_H_MM           # 1244.4 px

METRICS = {"aircraft": "synthetic", "span_m": 64.0, "span_source": "metrics/bw-ft",
           "length_m": 40.0, "length_source": "test", "height_m": 8.0,
           "height_source": "test"}


def record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0),
           aircraft=(1000.0, 0.0, 1000.0), attitude=(0.0, 0.0, 0.0),
           index=0, camera_id="cam0", t_s=0.0, sample_index=0):
    """One manifest frame record. ``look`` is (yaw, pitch, roll) deg;
    ``attitude`` is the aircraft's (roll, pitch, heading) deg."""
    yaw, pitch, roll = look
    return {
        "index": index, "camera_id": camera_id,
        "file": f"frames/{camera_id}/{index:04d}.png",
        "t_s": t_s, "sample_index": sample_index,
        "position_north_m": camera[0], "position_east_m": camera[1],
        "position_alt_m": camera[2],
        "quaternion_wxyz": list(euler_to_quat(roll, pitch, yaw)),
        "yaw_deg": yaw, "pitch_deg": pitch, "roll_deg": roll,
        "focal_length_mm": FOCAL_MM, "sensor_width_mm": SENSOR_W_MM,
        "sensor_height_mm": SENSOR_H_MM, "width_px": WIDTH, "height_px": HEIGHT,
        "near_m": 0.1, "far_m": 100000.0,
        "principal_point_px": [WIDTH / 2.0, HEIGHT / 2.0],
        "fx_px": FX, "fy_px": FY,
        "aircraft": {"north_m": aircraft[0], "east_m": aircraft[1],
                     "alt_m": aircraft[2], "roll_deg": attitude[0],
                     "pitch_deg": attitude[1], "heading_deg": attitude[2],
                     "speed_mps": 100.0},
    }


def manifest(records, metrics=METRICS, preset="tower"):
    cameras = {}
    for r in records:
        block = cameras.setdefault(r["camera_id"], {
            "camera_id": r["camera_id"], "preset": preset,
            "schedule_basis": "count 4 over the run", "capture_count": 0})
        block["capture_count"] += 1
    return {"manifest_version": 1, "aircraft_metrics": metrics,
            "cameras": list(cameras.values()), "frames": list(records)}


def draw(rec, metrics=METRICS, ground=("flat", None), **kw):
    return pv.draw_preview(rec, manifest([rec], metrics), ground, **kw)


def test_the_quaternion_and_euler_axes_agree_for_the_synthetic_record():
    rec = record(look=(30.0, -10.0, 5.0))
    for a, b in zip(axes_from_quat(rec["quaternion_wxyz"]),
                    axes_from_euler(5.0, -10.0, 30.0)):
        assert np.allclose(a, b, atol=1e-9)


# -- horizon ----------------------------------------------------------------

def test_a_level_camera_s_horizon_is_the_principal_row():
    """Yaw 0, pitch 0, roll 0: the horizon is v = cy at both ends, drawn
    in the horizon colour through the principal point, and a ground
    point 5 km straight ahead projects BELOW it."""
    rec = record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0),
                 aircraft=(2000.0, 0.0, 1400.0))
    seg = pv.horizon_segment(rec)
    cx, cy = rec["principal_point_px"]
    assert seg is not None
    assert abs(seg[0][1] - cy) < 1.0 and abs(seg[1][1] - cy) < 1.0
    assert seg[0][0] <= 1.0 and seg[1][0] >= WIDTH - 1.0     # spans the frame
    image, info = draw(rec)
    assert image.size == (WIDTH, HEIGHT)
    assert image.getpixel((int(cx), int(cy))) == pv.HORIZON_RGB
    u, v, z = project_point(rec, (5000.0, 0.0, 0.0))
    assert z > 0 and v > cy + 100
    assert info["segments"]["grid"] > 0                     # the ground is drawn
    assert info["segments"]["rings"] > 0


def test_a_pitched_camera_s_horizon_moves_by_fy_tan_pitch():
    """Pitch -10 deg (looking down): the horizon RISES above the centre
    to cy + fy tan(-10 deg) = cy - 219 px, within a pixel; roll tilts
    it by the roll angle."""
    rec = record(look=(0.0, -10.0, 0.0))
    seg = pv.horizon_segment(rec)
    expected = HEIGHT / 2.0 + FY * math.tan(math.radians(-10.0))
    assert expected < HEIGHT / 2.0 - 200
    assert abs(seg[0][1] - expected) < 1.0 and abs(seg[1][1] - expected) < 1.0
    # Roll +20 (right wing down): the horizon rises to the right, so the
    # image slope dv/du is -tan(20 deg).
    rolled = pv.horizon_segment(record(look=(0.0, 0.0, 20.0)))
    assert abs((rolled[1][1] - rolled[0][1]) / (rolled[1][0] - rolled[0][0])
               + math.tan(math.radians(20.0))) < 0.01


def test_a_camera_looking_straight_up_has_no_horizon_in_frame():
    rec = record(look=(0.0, 75.0, 0.0), aircraft=(300.0, 0.0, 4000.0))
    assert pv.horizon_segment(rec) is None
    image, info = draw(rec)
    assert info["horizon"] is None
    assert info["segments"].get("grid", 0) == 0                # ground out of view


# -- the aircraft ----------------------------------------------------------

def test_the_body_centre_is_the_reprojected_aircraft_pixel():
    rec = record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0),
                 aircraft=(800.0, 60.0, 1030.0), attitude=(0.0, 0.0, 0.0))
    u, v, z = project_point(rec, (800.0, 60.0, 1030.0))
    image, info = draw(rec)
    assert abs(info["aircraft_px"][0] - u) < 1.0
    assert abs(info["aircraft_px"][1] - v) < 1.0
    # The wing passes through the centre: a body-coloured pixel there.
    window = [image.getpixel((int(round(u)) + du, int(round(v)) + dv))
              for du in (-1, 0, 1) for dv in (-1, 0, 1)]
    assert pv.BODY_RGB in window
    assert info["segments"]["body"] == 3 and info["segments"]["box"] == 12


def test_the_wing_tip_separation_is_fx_span_over_range():
    """Aircraft 1 km ahead, wings level and square to the camera: the
    tips sit fx x span / range apart, within a pixel."""
    rng = 1000.0
    rec = record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0),
                 aircraft=(rng, 0.0, 1000.0), attitude=(0.0, 0.0, 0.0))
    _, info = draw(rec)
    left, right = info["body"]["left_tip"], info["body"]["right_tip"]
    assert abs((right[0] - left[0]) - FX * METRICS["span_m"] / rng) < 1.0
    assert abs(right[1] - left[1]) < 1e-6
    # Twice the range: half the separation.
    _, far = draw(record(aircraft=(2.0 * rng, 0.0, 1000.0)))
    assert abs((far["body"]["right_tip"][0] - far["body"]["left_tip"][0])
               - FX * METRICS["span_m"] / (2.0 * rng)) < 1.0


def test_the_body_follows_the_recorded_attitude():
    """Heading 90 (east) puts the nose to the right of the centre; roll
    30 lifts the right wing by span/2 sin(30) in the image."""
    rec = record(aircraft=(1000.0, 0.0, 1000.0), attitude=(0.0, 0.0, 90.0))
    _, info = draw(rec)
    assert info["body"]["nose"][0] > info["aircraft_px"][0] + 10
    assert abs(info["body"]["nose"][1] - info["aircraft_px"][1]) < 1.0
    # The heading tick continues beyond the nose along the heading.
    assert info["body"]["heading_tick"][0] > info["body"]["nose"][0]
    rolled = record(aircraft=(1000.0, 0.0, 1000.0), attitude=(30.0, 0.0, 0.0))
    _, info = draw(rolled)
    drop = FY * (METRICS["span_m"] / 2.0) * math.sin(math.radians(30.0)) / 1000.0
    assert abs((info["body"]["right_tip"][1] - info["aircraft_px"][1]) - drop) < 1.0


def test_a_manifest_without_metrics_says_the_body_is_unscaled():
    rec = record(aircraft=(1000.0, 100.0, 1050.0))      # off the boresight
    image, info = draw(rec, metrics=None)
    assert "body" not in info
    assert any("aircraft_metrics absent" in line for line in info["header"])
    u, v = info["aircraft_px"]
    assert image.getpixel((int(round(u)) + 4, int(round(v)))) == pv.NO_METRICS_RGB


def test_the_track_is_drawn_past_solid_future_dim():
    recs = [record(aircraft=(500.0 + 200.0 * k, 0.0, 1000.0), index=k,
                   t_s=float(k), sample_index=10 * k) for k in range(4)]
    m = manifest(recs)
    track = pv._track(m)
    assert [p[3] for p in track] == [0, 10, 20, 30]
    _, info = pv.draw_preview(recs[1], m, ("flat", None), track_points=track)
    assert info["segments"]["track"] == 3


# -- clipping ---------------------------------------------------------------

def test_a_segment_behind_the_camera_is_not_drawn_and_a_crossing_one_is_cut():
    rec = record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0))
    behind = pv._clip_segments(rec, np.array([[-100.0, -50.0, 900.0]]),
                               np.array([[-200.0, 50.0, 900.0]]), 1.0)
    assert len(behind) == 0
    # A segment behind the camera whose MIRRORED projection would land
    # in frame (z = -1000: u = cx -/+ 12 px, v = cy) is still not drawn.
    mirrored = pv._clip_segments(rec, np.array([[-1000.0, 10.0, 1000.0]]),
                                 np.array([[-1000.0, -10.0, 1000.0]]), 1.0)
    assert len(mirrored) == 0
    crossing = pv._clip_segments(rec, np.array([[-100.0, 0.0, 990.0]]),
                                 np.array([[100.0, 0.0, 990.0]]), 1.0)
    assert len(crossing) == 1
    u0, v0, u1, v1, depth = crossing[0]
    assert 0.0 <= u0 <= WIDTH and 0.0 <= v0 <= HEIGHT
    assert 0.0 <= u1 <= WIDTH and 0.0 <= v1 <= HEIGHT
    # Terrain wholly behind the camera draws nothing.
    a = np.array([[-500.0, -100.0, 0.0], [-500.0, 100.0, 0.0]])
    b = np.array([[-600.0, -100.0, 0.0], [-600.0, 100.0, 0.0]])
    _, info = draw(rec, ground=("terrain", (a, b)))
    assert info["segments"]["terrain"] == 0


def test_depth_shading_is_near_bright_far_dim():
    rec = record(aircraft=(500.0, 0.0, 1000.0))
    near, mid, far = pv.depth_brightness([500.0, 5000.0, 100000.0], rec)
    assert near == 240.0 and near > mid > far and far == 32.0


# -- terrain wireframe -------------------------------------------------------

def synthetic_heightfield():
    from core.terrain.heightfield import Georeference, Heightfield

    rows, cols = np.mgrid[0:9, 0:9]
    samples = (100.0 * np.sin(rows / 2.0) ** 2 + 50.0 * cols).astype(np.uint16)
    return Heightfield(
        samples=samples,
        georeference=Georeference(crs="EPSG:32631", origin_x_m=166021.0 - 400.0,
                                  origin_y_m=400.0, pixel_size_m=100.0),
        scale_m=1.0, offset_m=0.0, name="synthetic")


def test_the_terrain_wireframe_joins_every_sample_to_its_neighbours():
    from tests.test_camera_poses import FRAME

    a, b = pv.terrain_wireframe(synthetic_heightfield(), FRAME, grid=9)
    assert len(a) == len(b) == 2 * 9 * 8            # rows + columns
    lengths = np.linalg.norm(b[:, :2] - a[:, :2], axis=1)
    assert np.allclose(lengths, 100.0)               # neighbour to neighbour
    rec = record(camera=(-1500.0, 0.0, 800.0), look=(0.0, -10.0, 0.0),
                 aircraft=(0.0, 0.0, 600.0))
    image, info = draw(rec, ground=("terrain", (a, b)))
    assert info["segments"]["terrain"] > 100
    assert info["horizon"] is not None


# -- resolution, header, timing --------------------------------------------

def test_previews_default_to_the_record_s_full_resolution(tmp_path):
    recs = [record(index=k, t_s=float(k), sample_index=k) for k in range(2)]
    m = manifest(recs)
    written = pv.render_previews(m, tmp_path)
    assert len(written) == 2 and written.scale == 1
    assert Image.open(written[0]).size == (WIDTH, HEIGHT)
    assert written[0].name == "preview_00000.png"
    half = pv.render_previews(m, tmp_path / "half", scale=2)
    assert Image.open(half[0]).size == (WIDTH // 2, HEIGHT // 2)
    for bad in (0, -1, 1.5, "x"):
        with pytest.raises(ValueError, match="preview.scale"):
            pv.render_previews(m, tmp_path / "bad", scale=bad)


def test_the_header_states_position_look_and_focal_length():
    rec = record(camera=(268.4, 0.0, 3060.0), look=(0.0, -6.2, 0.0),
                 aircraft=(444.4, 0.0, 3048.0), index=5, t_s=2.683)
    lines = pv.header_lines(rec, manifest([rec]))
    text = "\n".join(lines)
    assert "cam0  frame 5/1  t=2.683 s" in text
    assert "pos N +268.4 E +0.0 alt 3060.0 m" in text
    assert "look yaw 0.0 pitch -6.2 roll 0.0 deg" in text
    assert "f=35 mm (fx 1244 px)" in text and "1280x720" in text
    assert "FOV 54.4x32.3 deg" in text
    assert "aircraft->camera bearing 180.0 deg range 176.4 m" in text
    assert "span 64.0 m (metrics/bw-ft)" in text
    assert "1/2 scale" not in text
    assert "1/2 scale" in "\n".join(pv.header_lines(rec, manifest([rec]), scale=2))
    image, info = draw(rec)
    assert info["header"] == lines
    # The header band is painted: text pixels on the black band.
    band = np.asarray(image.crop((0, 0, 400, 20)))
    assert (band == pv.TEXT_RGB).all(axis=2).any()


def test_the_field_of_view_is_two_atan_sensor_over_two_focal():
    h, v = pv.field_of_view_deg(record())
    assert abs(h - math.degrees(2 * math.atan(SENSOR_W_MM / 70.0))) < 1e-9
    assert abs(v - math.degrees(2 * math.atan(SENSOR_H_MM / 70.0))) < 1e-9


def test_the_flat_ground_plan_reaches_the_horizon_or_the_far_plane():
    low = pv.flat_ground_plan(record(camera=(0.0, 0.0, 80.0)), 0.0)
    assert low["step_m"] == 20.0                     # nice number >= 80/4
    assert low["extent_m"] == min(100000.0, FY * 80.0 / 2.0)
    high = pv.flat_ground_plan(record(camera=(0.0, 0.0, 3060.0)), 0.0)
    assert high["step_m"] == 1000.0 and high["extent_m"] == 100000.0   # far_m
    assert pv.flat_ground_plan(record(camera=(0.0, 0.0, 0.0)), 0.0) is None
    assert 500.0 in low["rings_m"] and 20000.0 in high["rings_m"]


def test_full_resolution_render_time_is_under_budget(tmp_path):
    """48 frames at 1280x720 with the flat lattice, rings, track and
    body: the measured per-frame time stays under the 0.5 s budget."""
    recs = [record(camera=(-110.0 + 100.0 * k, 0.0, 3060.0), look=(0.0, -6.2, 0.0),
                   aircraft=(100.0 * k, 0.0, 3048.0), index=k, t_s=0.5 * k,
                   sample_index=60 * k, camera_id="chase0") for k in range(24)]
    recs += [record(camera=(900.0, -800.0, 80.0), look=(90.0, 60.0, 0.0),
                    aircraft=(100.0 * k, 0.0, 3048.0), index=k, t_s=0.5 * k,
                    sample_index=60 * k, camera_id="tower0") for k in range(24)]
    m = manifest(recs)
    started = time.perf_counter()
    written = pv.render_previews(m, tmp_path)
    wall = (time.perf_counter() - started) / len(written)
    assert len(written) == 48
    assert written.seconds_per_frame < pv.RENDER_BUDGET_S_PER_FRAME
    assert wall < pv.RENDER_BUDGET_S_PER_FRAME               # sheets included


# -- overlay and contact sheet ---------------------------------------------

def test_the_overlay_is_the_frame_s_size_with_the_body_at_the_reprojected_pixel(
        tmp_path):
    from tests.test_camera_verify import honest_frame

    rec = record(aircraft=(800.0, 60.0, 1030.0), camera_id="cam0")
    m = manifest([rec])
    frame_path = tmp_path / rec["file"]
    frame_path.parent.mkdir(parents=True)
    honest_frame(frame_path, WIDTH, HEIGHT)                   # a flat frame
    background = Image.open(frame_path).getpixel((10, 300))
    written = pv.render_overlays(m, tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in written] == \
        ["overlays/cam0/0000.png"]
    overlay = Image.open(written[0])
    assert overlay.size == Image.open(frame_path).size
    u, v, _ = project_point(rec, (800.0, 60.0, 1030.0))
    assert overlay.getpixel((int(round(u)), int(round(v)))) != background
    # Far from any geometry the frame shows through.
    assert overlay.getpixel((10, 300)) == background
    # No frame on disk: no overlay, no error.
    assert pv.render_overlays(m, tmp_path / "empty") == []


def test_every_camera_gets_a_contact_sheet_with_one_thumbnail_per_frame(tmp_path):
    recs = [record(index=k, t_s=0.25 * k, sample_index=k, camera_id="a") for k in range(7)]
    recs += [record(index=k, t_s=0.25 * k, sample_index=k, camera_id="b") for k in range(2)]
    m = manifest(recs)
    written = pv.render_previews(m, tmp_path)
    assert set(written.contact_sheets) == {"a", "b"}
    for camera_id, count in (("a", 7), ("b", 2)):
        sheet = written.contact_sheets[camera_id]
        assert sheet == tmp_path / "contact_sheets" / f"{camera_id}.png"
        assert sheet.is_file()
        # previews/ holds exactly the per-frame PNGs: the sheet is beside it.
        assert len(list((tmp_path / "previews" / camera_id).glob("*.png"))) == count
        paths = [p for p in written if p.parent.name == camera_id]
        _, info = pv.contact_sheet(m, camera_id, paths, tmp_path / f"{camera_id}.png")
        assert info["thumbnails"] == count == m["cameras"][0 if camera_id == "a" else 1]["capture_count"]
        cols = min(pv.CONTACT_COLUMNS, count)
        assert Image.open(sheet).size[0] == 6 + cols * (pv.CONTACT_THUMB_WIDTH_PX + 6)
    # A capped run (fewer previews than frames) draws what exists and says so.
    capped = pv.render_previews(m, tmp_path / "capped", max_frames=3)
    assert len(capped) == 3 and set(capped.contact_sheets) == {"a"}


def test_the_runner_reads_the_airframe_metrics_from_the_fdm_once():
    """span from metrics/bw-ft (B747: 211.5 ft), with every source
    named; the manifest carries the block verbatim."""
    from core.capture.manifest import build_capture_manifest
    from core.fdm import units
    from core.scenario.runner import aircraft_metrics, configure_from_spec
    from tests.test_camera_manifest import build, spec_with_cameras

    spec = spec_with_cameras()
    fdm = configure_from_spec(spec)
    metrics = aircraft_metrics(fdm)
    assert metrics["span_source"] == "metrics/bw-ft"
    assert abs(metrics["span_m"] - units.ft_to_m(fdm.props.get("metrics/bw-ft"))) < 1e-9
    assert abs(metrics["span_m"] - 64.4652) < 1e-3
    assert metrics["length_m"] > 0 and "metrics/lh-ft" in metrics["length_source"]
    assert metrics["height_m"] > 0 and "metrics/Sv-sqft" in metrics["height_source"]
    plain = build()
    assert plain["aircraft_metrics"] is None
    from core.capture.poses import solve_pose_track
    from core.capture.schedule import solve_schedule
    from tests.test_camera_poses import FRAME, make_columns

    columns = make_columns(duration_s=10.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    carried = build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                     output_digest="0" * 64,
                                     aircraft_metrics=metrics)
    assert carried["aircraft_metrics"] == metrics
    assert json.loads(json.dumps(carried))["aircraft_metrics"]["span_source"] == "metrics/bw-ft"
