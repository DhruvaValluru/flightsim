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


def manifest(records, metrics=METRICS, preset="tower", count=None):
    cameras = {}
    for r in records:
        block = cameras.setdefault(r["camera_id"], {
            "camera_id": r["camera_id"], "preset": preset,
            "schedule_basis": "count 4 over the run", "capture_count": 0})
        block["capture_count"] += 1
    if count is not None:
        for block in cameras.values():
            block["capture_count"] = count
    return {"manifest_version": 1, "aircraft_metrics": metrics,
            "cameras": list(cameras.values()), "frames": list(records),
            "frame": {"crs": "EPSG:32631", "origin_lat_deg": 0.0,
                      "origin_lon_deg": 0.0, "declared_on_card": True}}


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
    assert [p[4] for p in track] == [0.0, 1.0, 2.0, 3.0]          # t_s per instant
    _, info = pv.draw_preview(recs[1], m, ("flat", None), track_points=track)
    assert info["segments"]["track"] == 3
    assert info["segments"]["track_dots"] == 4       # this camera's scheduled instants
    # Without telemetry the header says the track is the schedule's instants.
    _, words = pv._track_points(m, None, None)
    assert words == "track: scheduled instants only (no telemetry passed)"


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
    lines = pv.header_lines(rec, manifest([rec], count=24))
    text = "\n".join(lines)
    # The manifest's 0-based index a verifier greps for AND the human count.
    assert "cam0  frame index 5 (6 of 24)  t=2.683 s" in text
    assert pv.contact_label(5, 24, 2.683) == "#5 (6/24)  t=2.683 s"
    assert pv.contact_label(23, 24, 11.992) == "#23 (24/24)  t=11.992 s"
    assert "pos N +268.4 E +0.0 alt 3060.0 m" in text
    assert "look yaw 0.0 pitch -6.2 roll 0.0 deg" in text
    assert "f=35 mm (fx 1244 px)" in text and "1280x720" in text
    assert "FOV 54.4x32.3 deg" in text
    assert "aircraft->camera bearing 180.0 deg range 176.4 m" in text
    assert "span 64.0 m (metrics/bw-ft)" in text
    assert "1/2 scale" not in text
    assert "1/2 scale" in "\n".join(pv.header_lines(rec, manifest([rec]), scale=2))
    image, info = pv.draw_preview(rec, manifest([rec], count=24), ("flat", None))
    assert info["header"][:len(lines)] == lines
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


# -- round 2: depth order and the skyline ------------------------------------

def test_segments_are_drawn_in_painter_s_order_far_first():
    """Two crossing segments given FAR-LAST: the near one's colour is
    what the crossing pixel carries, whatever the input order."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (40, 40), (0, 0, 0))
    near, far = (10, 200, 10), (200, 10, 10)
    segs = np.array([[0.0, 20.0, 40.0, 20.0, 100.0],      # near, horizontal
                     [20.0, 0.0, 20.0, 40.0, 5000.0]])    # far, vertical, listed last
    pv._draw_segments(ImageDraw.Draw(image), segs,
                      lambda depth: near if depth < 1000 else far)
    assert image.getpixel((20, 20)) == near
    assert image.getpixel((20, 5)) == far and image.getpixel((5, 20)) == near


def two_ridge_heightfield():
    """41 x 41 at 100 m: a NEAR ridge 300 m high along east at north
    -500 and a FAR ridge 150 m high at north +500, flat ground
    elsewhere."""
    from core.terrain.heightfield import Georeference, Heightfield

    samples = np.zeros((41, 41), dtype=np.uint16)
    samples[25, :] = 300                                  # north = 2000 - 25 x 100
    samples[15, :] = 150                                  # north = +500
    return Heightfield(
        samples=samples,
        georeference=Georeference(crs="EPSG:32631", origin_x_m=166021.0 - 2000.0,
                                  origin_y_m=2000.0, pixel_size_m=100.0),
        scale_m=1.0, offset_m=0.0, name="two_ridges")


def test_a_near_ridge_hides_the_far_ridge_behind_it():
    """Camera at north -1500, alt 400, looking north, pitch -5: the
    near crest (300 m at 1000 m) sits ABOVE the far crest (150 m at
    2000 m) on screen, so the far crest's row lies on the near ridge's
    face. The pixel where it crosses the near ridge's column line at
    east 0 carries the near (bright) colour, the far row is NOT drawn
    beside it, and the info counts the hidden segments."""
    from tests.test_camera_poses import FRAME

    hf = two_ridge_heightfield()
    ground = pv._ground(hf, FRAME)
    a, _ = ground.segments
    east0 = float(a[np.argmin(np.abs(a[:, 1])), 1])              # the column nearest east 0
    rec = record(camera=(-1500.0, east0, 400.0), look=(0.0, -5.0, 0.0),
                 aircraft=(-1300.0, east0 + 100.0, 450.0))
    cx, cy = rec["principal_point_px"]
    u_f, v_f, z_f = project_point(rec, (500.0, east0, 150.0))     # far crest
    u_n, v_n, z_n = project_point(rec, (-500.0, east0, 300.0))    # near crest
    assert abs(u_f - cx) < 1e-6 and abs(u_n - cx) < 1e-6
    assert v_n < v_f < HEIGHT                                     # far crest below near crest
    image, info = pv.draw_preview(rec, manifest([rec]), ground)
    assert info["segments"]["terrain_hidden"] > 0
    assert info["segments"]["terrain_visible"] < info["segments"]["terrain"]
    # Where the far crest's ROW crosses the near ridge's COLUMN line one
    # lattice column east of the camera (the centre column carries the
    # north arrow): intersect the two projected lines.
    e_n = east0 + 100.0
    P0 = np.array(project_point(rec, (-600.0, e_n, 0.0))[:2])
    P1 = np.array(project_point(rec, (-500.0, e_n, 300.0))[:2])
    Q0 = np.array(project_point(rec, (500.0, e_n, 150.0))[:2])
    Q1 = np.array(project_point(rec, (500.0, e_n + 400.0, 150.0))[:2])
    d1, d2 = P1 - P0, Q1 - Q0
    s_ = np.cross(Q0 - P0, d2) / np.cross(d1, d2)
    ui, vi = P0 + s_ * d1
    assert 0.0 < s_ < 1.0 and v_n < vi < HEIGHT                  # on the near face
    far_rgb = pv._shaded(rec)(z_f)
    near_floor = pv._shaded(rec)(z_n)
    window = [image.getpixel((int(round(ui)) + du, int(round(vi)) + dv))
              for du in (-1, 0, 1) for dv in (-1, 0, 1)]
    # The near column line's bright green is there; the far row's dim
    # green is nowhere in the window.
    assert any(p[1] >= near_floor[1] - 2 for p in window), (window, near_floor)
    assert all(p == pv.BACKGROUND_RGB or p[1] > far_rgb[1] + 8 for p in window), window
    # Beside the column line, on the near face, the far row is not
    # drawn: background, or a distance ring draped on the near face.
    for du in (-30, 30):
        vq = Q0[1] + (ui + du - Q0[0]) * d2[1] / d2[0]
        p = image.getpixel((int(round(ui)) + du, int(round(vq))))
        assert p in (pv.BACKGROUND_RGB, pv.RING_RGB), p
    # The crest is hidden ALONG the frame, not only at that column.
    u2, v2, _ = project_point(rec, (500.0, east0 + 400.0, 150.0))
    p = image.getpixel((int(round(u2)), int(round(v2))))
    assert p in (pv.BACKGROUND_RGB, pv.RING_RGB), p
    # The skyline cull alone: the same clipped segments with the cull
    # report the far crest as hidden.
    clipped, za, zb, _ = pv._project_clip(rec, *ground.segments, 1.0)
    visible, source, skyline = pv.skyline_cull(clipped, za, zb, WIDTH)
    assert len(visible) < len(clipped)
    assert skyline[int(round(cx))] <= v_n + 1.0


# -- round 2: the flown track from the telemetry -----------------------------

def arc_columns(points=200, dt=0.05, radius=1000.0, alt=1000.0):
    """A 200-point telemetry record flying a half circle of ``radius``
    about the origin at 20 Hz."""
    from tests.test_camera_poses import FRAME

    columns = {k: [] for k in ("t", "lat_deg", "lon_deg", "altitude_m")}
    for i in range(points):
        angle = math.pi * i / (points - 1)
        north, east = radius * math.cos(angle), radius * math.sin(angle)
        lat, lon = FRAME.to_geographic(north, east)
        columns["t"].append(round(i * dt, 6))
        columns["lat_deg"].append(lat)
        columns["lon_deg"].append(lon)
        columns["altitude_m"].append(alt)
    return columns


def test_the_drawn_track_follows_the_telemetry_not_the_chord(tmp_path):
    from tests.test_camera_poses import FRAME

    columns = arc_columns()
    track, words = pv.telemetry_track(columns, FRAME)
    assert words == "track: telemetry 20 Hz decimated to 10 Hz (101 points)"
    # The recorder's first sample sits one fixed step in: the rate is
    # the MEDIAN step, not the mean over the span.
    shifted = dict(columns, t=[0.008333] + columns["t"][1:])
    assert pv.telemetry_track(shifted, FRAME)[1] == words
    assert [p[3] for p in track][:3] == [0, 2, 4] and track[-1][3] == 199
    assert abs(track[50][4] - 5.0) < 1e-9                       # t_s carried
    # Five scheduled instants along the arc, the camera off to the south.
    recs = []
    for k, i in enumerate((0, 50, 100, 150, 199)):
        n, e = FRAME.to_local(columns["lat_deg"][i], columns["lon_deg"][i])
        recs.append(record(camera=(-3000.0, 0.0, 2500.0), look=(0.0, -25.0, 0.0),
                           aircraft=(n, e, 1000.0), index=k,
                           t_s=columns["t"][i], sample_index=i))
    m = manifest(recs)
    rec = recs[2]
    image, info = pv.draw_preview(rec, m, ("flat", None), track_points=track,
                                  track_words=words)
    assert info["segments"]["track_dots"] == 5
    assert words in info["header"]

    def has_colour(u, v, rgb, radius=2):
        return any(image.getpixel((int(round(u)) + du, int(round(v)) + dv)) == rgb
                   for du in range(-radius, radius + 1)
                   for dv in range(-radius, radius + 1))

    # Intermediate telemetry points (never scheduled) lie ON the drawn
    # track: past ones before t=5 s, future ones after.
    for i, rgb in ((25, pv.TRACK_PAST_RGB), (75, pv.TRACK_PAST_RGB),
                   (125, pv.TRACK_FUTURE_RGB), (175, pv.TRACK_FUTURE_RGB)):
        n, e = FRAME.to_local(columns["lat_deg"][i], columns["lon_deg"][i])
        u, v, z = project_point(rec, (n, e, 1000.0))
        assert z > 0 and has_colour(u, v, rgb), i
    # The chord between two scheduled instants is NOT the track: its
    # midpoint, 90 m inside the arc, is background.
    a = recs[0]["aircraft"]; b = recs[1]["aircraft"]
    mid = ((a["north_m"] + b["north_m"]) / 2, (a["east_m"] + b["east_m"]) / 2, 1000.0)
    u, v, _ = project_point(rec, mid)
    assert not has_colour(u, v, pv.TRACK_PAST_RGB) and not has_colour(u, v, pv.TRACK_FUTURE_RGB)
    # Through render_previews: the words reach the set and the header.
    written = pv.render_previews(m, tmp_path, telemetry=columns)
    assert written.track_source == words
    plain = pv.render_previews(m, tmp_path / "plain")
    assert plain.track_source == "track: scheduled instants only (no telemetry passed)"


# -- round 2: rings from the camera, the compass, the arrow ---------------

def test_distance_rings_are_centred_on_the_camera_s_exact_ground_point():
    """Camera N +268.4, alt 3060, pitch -4.8: the 10 km ring's
    forward-azimuth point is 10 km north of the CAMERA, so it projects
    at v = cy + fy tan(atan(3060 / 10000) - 4.8 deg), within 1 px --
    not at the lattice's snapped 10.27 km."""
    rec = record(camera=(268.4, 0.0, 3060.0), look=(0.0, -4.8, 0.0),
                 aircraft=(444.4, 0.0, 3048.0))
    cx, cy = rec["principal_point_px"]
    plan = pv.flat_ground_plan(rec, 0.0)
    assert plan["camera_north_m"] == 268.4 and plan["centre_north_m"] == 0.0
    pts = pv.ring_points(plan, 10000.0)
    assert abs(pts[0][0] - 10268.4) < 1e-9 and abs(pts[0][1]) < 1e-9
    u, v, z = project_point(rec, tuple(pts[0]))
    expected = cy + FY * math.tan(math.atan(3060.0 / 10000.0) - math.radians(4.8))
    assert abs(v - expected) < 1.0 and abs(u - cx) < 1e-6
    snapped = cy + FY * math.tan(math.atan(3060.0 / 10268.4) - math.radians(4.8))
    assert abs(expected - snapped) > 5.0
    image, info = draw(rec)
    assert info["segments"]["rings"] >= 2
    assert image.getpixel((int(round(cx)), int(round(expected)))) == pv.RING_RGB
    assert "rings centred on the camera's ground point" in "\n".join(info["header"])


def test_the_compass_rose_puts_north_at_minus_yaw():
    for yaw in (0.0, 90.0, 231.3):
        rec = record(look=(yaw, -10.0, 0.0), attitude=(0.0, 0.0, 45.0))
        rose = pv.compass_rose(rec, WIDTH, HEIGHT)
        assert abs(rose["north_deg"] - (-yaw) % 360.0) < 1e-9
        assert abs(rose["heading_needle_deg"] - (45.0 - yaw) % 360.0) < 1e-9
        cx, cy = rose["centre"]
        tx, ty = rose["spokes"]["N"]["tip"]
        drawn = math.degrees(math.atan2(tx - cx, -(ty - cy))) % 360.0
        assert abs(drawn - (-yaw) % 360.0) < 1e-9
        assert abs(rose["spokes"]["E"]["angle_deg"] - (90.0 - yaw) % 360.0) < 1e-9
        image, info = draw(rec)
        assert info["compass"]["north_deg"] == rose["north_deg"]
        # The N spoke is painted along its angle, in the north colour.
        a = math.radians(rose["north_deg"])
        u, v = cx + 20 * math.sin(a), cy - 20 * math.cos(a)
        assert image.getpixel((int(round(u)), int(round(v)))) == pv.NORTH_RGB
        assert (cx, cy) == (WIDTH - pv.COMPASS_INSET_PX[0], HEIGHT - pv.COMPASS_INSET_PX[1])


def test_the_north_arrow_is_sixty_pixels_on_screen_in_flat_and_terrain_scenes():
    from tests.test_camera_poses import FRAME

    # Flat: the camera looks steeply down at the plane. The base sits
    # on the ray NORTH_ARROW_DROP_PX below the boresight, clear of the
    # aircraft an aimed camera centres.
    rec = record(camera=(0.0, 0.0, 800.0), look=(0.0, -60.0, 0.0),
                 aircraft=(300.0, 200.0, 600.0))
    cx, cy = rec["principal_point_px"]
    image, info = draw(rec)
    assert info["segments"]["north_arrow"] == 3
    assert abs(info["north_arrow"]["screen_px"] - pv.NORTH_ARROW_PX) < 1.0
    u, v, z = project_point(rec, info["north_arrow"]["tip"])
    assert abs(info["north_arrow"]["tip_px"][0] - u) < 1e-6
    bu, bv, _ = project_point(rec, info["north_arrow"]["base"])
    assert abs(bu - cx) < 1e-6 and abs(bv - (cy + pv.NORTH_ARROW_DROP_PX)) < 1e-6
    assert info["north_arrow"]["base"][2] == 0.0                     # on the plane
    # Terrain: the arrow is drawn where the boresight meets the raster.
    ground = pv._ground(synthetic_heightfield(), FRAME)
    rec = record(camera=(-400.0, 0.0, 700.0), look=(0.0, -35.0, 0.0),
                 aircraft=(0.0, 0.0, 600.0))
    image, info = draw(rec, ground=ground)
    assert info["segments"]["north_arrow"] == 3
    assert abs(info["north_arrow"]["screen_px"] - pv.NORTH_ARROW_PX) < 1.0
    base = info["north_arrow"]["base"]
    assert abs(base[2] - ground.elevation(base[0], base[1])) < 1e-6   # on the raster
    bu, bv, _ = project_point(rec, base)
    assert abs(bu - cx) < 1e-6 and abs(bv - (cy + pv.NORTH_ARROW_DROP_PX)) < 1.0


# -- round 2: overlays at the frame's own size -------------------------------

@pytest.mark.parametrize("size", [(640, 360), (1920, 1080)])
def test_overlays_are_drawn_at_the_frame_s_own_size_for_any_ratio(tmp_path, size):
    from PIL import Image, ImageDraw

    from tests.test_camera_verify import honest_frame

    rec = record(aircraft=(800.0, 60.0, 1030.0), camera_id="cam0")
    m = manifest([rec])
    frame_path = tmp_path / rec["file"]
    frame_path.parent.mkdir(parents=True)
    honest_frame(frame_path, *size)
    frame = Image.open(frame_path).convert("RGB")
    background = frame.getpixel((size[0] - 2, size[1] - 2))
    written = pv.render_overlays(m, tmp_path)
    overlay = Image.open(written[0])
    assert overlay.size == size == written.sizes[written[0]]
    # The body centre is project_point scaled by the ratio, within 1 px;
    # the intrinsics were scaled, the pixels never resampled.
    ratio = (size[0] / WIDTH, size[1] / HEIGHT)
    image, info = pv.draw_preview(rec, m, ("flat", None), image=frame, alpha=200,
                                  tag="overlay")
    u, v, _ = project_point(rec, (800.0, 60.0, 1030.0))
    assert abs(info["aircraft_px"][0] - u * ratio[0]) < 1.0
    assert abs(info["aircraft_px"][1] - v * ratio[1]) < 1.0
    assert info["axis_scale"] == (WIDTH / size[0], HEIGHT / size[1])
    assert overlay.getpixel((int(round(u * ratio[0])), int(round(v * ratio[1])))) != background
    # A corner pixel outside any geometry is the frame's own.
    assert overlay.getpixel((size[0] - 2, size[1] - 2)) == background
    # The header band darkens the frame by at most OVERLAY_BAND_ALPHA.
    band_px = overlay.getpixel((size[0] - 3, 3))
    floor = background[0] * (1.0 - pv.OVERLAY_BAND_ALPHA / 255.0) - 1.0
    assert band_px[0] >= floor
    assert pv.OVERLAY_BAND_ALPHA <= 96
    # No header line is wider than the frame; the size note is in it.
    draw_ = ImageDraw.Draw(overlay)
    font = pv._font(pv.header_font_px(size[1]))
    assert all(draw_.textlength(line, font=font) <= size[0] for line in info["header_drawn"])
    tag = pv.overlay_tag(rec, size)
    assert f"frame {size[0]}x{size[1]} differs from the record's 1280x720" in tag
    assert "pixels not resampled" in tag
    assert pv.overlay_tag(rec, (WIDTH, HEIGHT)) == \
        "overlay: reprojected geometry over the rendered frame"


# -- round 2: the terrain header, the vertex, the rings on the raster ----------

def test_the_terrain_header_names_the_raster_and_a_vertex_projects_at_its_pixel():
    from tests.test_camera_poses import FRAME

    hf = synthetic_heightfield()
    ground = pv._ground(hf, FRAME)
    assert ground.plan["spacing_m"] == 100.0 and ground.plan["samples"] == (9, 9)
    rec = record(camera=(-1500.0, 0.0, 800.0), look=(0.0, -10.0, 0.0),
                 aircraft=(0.0, 0.0, 600.0))
    image, info = draw(rec, ground=ground)
    text = "\n".join(info["header"])
    assert "terrain synthetic 9x9 @ 100 m, wireframe 9x9 (100 m)" in text
    # A known raster vertex (row 4, col 4: north 0, east ~0, alt 200+
    # 50x4... read from the raster itself) projects at project_point
    # and the pixel there is terrain-coloured.
    a, b = ground.segments
    vertex = (0.0, a[:, 1][np.argmin(np.abs(a[:, 1]))], None)
    z = ground.elevation(vertex[0], vertex[1])
    assert z is not None
    u, v, depth = project_point(rec, (vertex[0], vertex[1], z))
    assert depth > 0
    window = [image.getpixel((int(round(u)) + du, int(round(v)) + dv))
              for du in (-1, 0, 1) for dv in (-1, 0, 1)]
    assert any(p[1] > p[0] and p[1] > 60 for p in window)          # terrain green
    # Rings draped on the raster: the 500 m ring around a camera over
    # the raster's centre lies on it and is drawn.
    rec = record(camera=(0.0, 0.0, 900.0), look=(0.0, -45.0, 0.0),
                 aircraft=(300.0, 0.0, 600.0))
    ra, rb, radii = pv.terrain_rings(rec, ground, 1e5)
    assert set(radii.tolist()) == {500.0}                           # 1 km leaves the raster
    for point in ra[:5]:
        assert abs(point[2] - ground.elevation(point[0], point[1])) < 1e-9
    _, info = draw(rec, ground=ground)
    assert info["segments"]["rings"] == 1
    assert "rings on the terrain" in "\n".join(info["header"])


def test_the_fine_lattice_densifies_the_ground_near_the_camera():
    from core.terrain.heightfield import Georeference, Heightfield
    from tests.test_camera_poses import FRAME

    samples = (np.arange(97 * 97).reshape(97, 97) % 7).astype(np.uint16)
    hf = Heightfield(samples=samples,
                     georeference=Georeference(crs="EPSG:32631", origin_x_m=166021.0 - 4800.0,
                                               origin_y_m=4800.0, pixel_size_m=100.0),
                     scale_m=1.0, offset_m=0.0, name="fine")
    ground = pv._ground(hf, FRAME)
    # 96 px over 47 gaps is 2.04 px: a stride under the density is left
    # whole (3 px, 300 m) and the fine lattice is the raster itself.
    assert pv.terrain_stride_px(97) == 3 and pv.terrain_stride_px(1024) == 24
    assert ground.plan["stride_px"] == 3 and ground.plan["fine_stride_px"] == 1
    assert ground.plan["near_radius_m"] == 10 * 300.0
    rec = record(camera=(0.0, 0.0, 1500.0), look=(0.0, -40.0, 0.0),
                 aircraft=(500.0, 0.0, 600.0))
    na, nb = pv.terrain_near_wireframe(hf, FRAME, rec, ground.plan)
    mid = 0.5 * (na + nb)
    assert len(na) > 0 and np.hypot(mid[:, 0], mid[:, 1]).max() <= 3000.0
    assert np.allclose(np.linalg.norm((nb - na)[:, :2], axis=1), 100.0)
    # No fine segment lies on a coarse line (those are drawn once): a
    # row-wise segment's raster row and a column-wise one's raster
    # column are never multiples of the coarse stride.
    g = hf.georeference
    rows = np.rint((g.origin_y_m - (na[:, 0] + FRAME.origin_y_m)) / 100.0).astype(int)
    cols = np.rint(((na[:, 1] + FRAME.origin_x_m) - g.origin_x_m) / 100.0).astype(int)
    row_wise = np.abs(na[:, 0] - nb[:, 0]) < 1e-9
    assert np.all(rows[row_wise] % 3 != 0) and np.all(cols[~row_wise] % 3 != 0)
    _, info = draw(rec, ground=ground)
    assert info["segments"]["terrain_fine"] > 0
    assert "+ 100 m within 3 km of the camera" in "\n".join(info["header"])


# -- round 2: the body's length caveat -----------------------------------

def test_the_body_line_carries_the_length_caveat():
    metrics = dict(METRICS, length_m=59.644, length_label="eyepoint to tail arm",
                   length_caveat="no fuselage length in JSBSim",
                   height_label="sqrt Sv")
    line = pv.body_words(metrics)
    assert ("length >= 59.6 m (eyepoint to tail arm; no fuselage length in "
            "JSBSim)") in line
    assert "fin 8.0 m (sqrt Sv)" in line and "span 64.0 m (metrics/bw-ft)" in line
    rec = record()
    assert line in pv.header_lines(rec, manifest([rec], metrics=metrics))


def test_the_runner_s_length_is_the_larger_stated_station_extent():
    """B747: eyepoint (308 in) to the tail arm (aero RP 1377 in +
    lh 106.6 ft) is 59.6 m, above arm + chord's 40.8 m, so it is the
    length, named, with the caveat and both candidates carried."""
    from core.scenario.runner import (
        aircraft_metrics, configure_from_spec, longitudinal_stations_in,
    )
    from tests.test_camera_manifest import spec_with_cameras

    fdm = configure_from_spec(spec_with_cameras())
    stations = longitudinal_stations_in(fdm)
    assert set(stations) == {"eyepoint", "VRP", "aero RP", "CG", "tail arm"}
    assert stations["eyepoint"] == 308.0 and abs(stations["tail arm"] - 2656.2) < 1e-6
    metrics = aircraft_metrics(fdm)
    assert abs(metrics["length_m"] - (2656.2 - 308.0) * 0.0254) < 1e-6
    assert abs(metrics["length_m"] - 59.644) < 1e-3
    assert metrics["length_label"] == "eyepoint to tail arm"
    assert metrics["length_caveat"] == "no fuselage length in JSBSim"
    assert abs(metrics["length_candidates_m"]["arm_chord"] - 40.816) < 1e-3
    assert "eyepoint 308 in" in metrics["length_source"]
    assert "metrics/lh-ft" in metrics["length_source"]


# -- round 3: the contact sheet is drawn for the tile ---------------------

def test_contact_sheet_tiles_are_drawn_for_the_tile_with_no_text(tmp_path):
    """Each tile is draw_preview at the tile's size in the thumbnail
    style, not the preview shrunk: the level camera's horizon is on
    the tile's row cy/4 (two rows: THUMBNAIL_LINE_PX), the body centre
    is at the reprojected pixel over 4, and NO text is drawn inside a
    tile (no header band, no legend, no compass, no labels); the index
    and time label sits under the tile."""
    recs = [record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0),
                   aircraft=(800.0 + 50.0 * k, 60.0, 1030.0), index=k,
                   t_s=0.5 * k, sample_index=k, camera_id="cam0") for k in range(3)]
    m = manifest(recs)
    written = pv.render_previews(m, tmp_path)
    paths = [p for p in written if p.parent.name == "cam0"]
    sheet_path, info = pv.contact_sheet(m, "cam0", paths, tmp_path / "sheet.png",
                                        track_points=pv._track(m))
    sheet = Image.open(sheet_path)
    assert info["thumb_size"] == (320, 180) == pv.thumbnail_size(WIDTH, HEIGHT)
    assert len(info["tiles"]) == 3
    full, full_info = pv.draw_preview(recs[0], m, ("flat", None))
    assert full_info["text_drawn"] > 10                       # the full preview has text
    tile = info["tiles"][0]
    x, y = tile["origin"]
    tw, th = tile["size"]
    ti = tile["info"]
    assert ti["style"] == "thumbnail" and ti["size"] == (tw, th)
    assert ti["text_drawn"] == 0 and ti["header_band_px"] == 0
    assert ti["header_drawn"] == []
    # The horizon: the same row as the full preview over 4, two rows thick.
    assert abs(ti["horizon"][0][1] - full_info["horizon"][0][1] / 4.0) < 1e-6
    v_h = int(round(ti["horizon"][0][1]))
    assert sheet.getpixel((x + 100, y + v_h)) == pv.HORIZON_RGB
    assert sheet.getpixel((x + 100, y + v_h + 1)) == pv.HORIZON_RGB   # width 2
    assert sheet.getpixel((x + 100, y + v_h - 1)) == pv.BACKGROUND_RGB
    assert sheet.getpixel((x + 100, y + v_h + 2)) == pv.BACKGROUND_RGB
    # The body centre: project_point over 4, a body pixel in its window.
    u, v, _ = project_point(recs[0], (800.0, 60.0, 1030.0))
    assert abs(ti["aircraft_px"][0] - u / 4.0) < 1e-6
    assert abs(ti["aircraft_px"][1] - v / 4.0) < 1e-6
    window = [sheet.getpixel((x + int(round(u / 4.0)) + du, y + int(round(v / 4.0)) + dv))
              for du in (-1, 0, 1) for dv in (-1, 0, 1)]
    assert pv.BODY_RGB in window
    # The ground, rings, arrow and the track are in the tile.
    assert ti["segments"]["grid"] > 0 and ti["segments"]["rings"] > 0
    assert ti["segments"]["north_arrow"] == 3 and ti["segments"]["track"] > 0
    # No text pixel inside any tile; no black band at its top.
    for t in info["tiles"]:
        tx, ty = t["origin"]
        pixels = np.asarray(sheet.crop((tx, ty, tx + tw, ty + th)))
        assert not (pixels == np.array(pv.TEXT_RGB)).all(axis=2).any()
        assert sheet.getpixel((tx + 2, ty + 2)) == pv.BACKGROUND_RGB
        assert t["info"]["text_drawn"] == 0
        # The label under the tile is drawn in the text colour.
        below = np.asarray(sheet.crop((tx, ty + th, tx + tw, ty + th + 18)))
        assert (below == np.array(pv.TEXT_RGB)).all(axis=2).any()
        assert t["label"] == pv.contact_label(t["index"], 3, recs[t["index"]]["t_s"])
    # The title names the tile size and the record's resolution.
    title = np.asarray(sheet.crop((0, 0, sheet.size[0], 28)))
    assert (title == np.array(pv.TEXT_RGB)).all(axis=2).any()
    # render_previews draws the same tiles (a fresh sheet is byte-identical).
    again, _ = pv.contact_sheet(m, "cam0", paths, tmp_path / "again.png",
                                track_points=pv._track(m))
    assert (tmp_path / "contact_sheets" / "cam0.png").read_bytes() == again.read_bytes()
    with pytest.raises(ValueError, match="preview.style"):
        pv.draw_preview(recs[0], m, ("flat", None), style="tiny")


# -- round 3: header wrapping exercised on a frame the header exceeds ----

def test_header_lines_wider_than_the_frame_are_wrapped_with_an_indent():
    """A 400x225 record (font 8 px, 392 px of room) whose position
    line measures 440 px: the drawn header has MORE lines than the
    header, every drawn line fits in w - 8, continuation lines carry
    the two-space indent, and no text pixel lies in the rightmost 8
    columns of the band (without wrapping the line runs to the last
    column)."""
    from PIL import ImageDraw

    rec = record(camera=(268.4, 0.0, 3060.0), look=(0.0, -4.8, 0.0),
                 aircraft=(444.4, 0.0, 3048.0), index=5, t_s=2.683,
                 camera_id="ridge_survey_camera")
    rec = dict(rec, width_px=400, height_px=225, principal_point_px=[200.0, 112.5],
               fx_px=388.9, fy_px=388.9)
    m = manifest([rec], count=24)
    words = "track: telemetry 9.23 Hz decimated to 9.23 Hz (128 points)"
    image, info = pv.draw_preview(rec, m, ("flat", None), track_points=pv._track(m),
                                  track_words=words)
    w, h = info["size"]
    assert (w, h) == (400, 225) and pv.header_font_px(h) == 8
    draw_ = ImageDraw.Draw(image)
    font = pv._font(pv.header_font_px(h))
    # The header genuinely exceeds the frame before wrapping.
    assert max(draw_.textlength(line, font=font) for line in info["header"]) > w - 8
    assert len(info["header_drawn"]) > len(info["header"])
    assert all(draw_.textlength(line, font=font) <= w - 8 for line in info["header_drawn"])
    continuations = [line for line in info["header_drawn"] if line.startswith("  ")]
    assert len(continuations) == len(info["header_drawn"]) - len(info["header"])
    assert continuations                                   # at least one wrapped
    # Every field of every header line survives the wrap, in order.
    joined = " ".join(line.strip() for line in info["header_drawn"])
    for line in info["header"]:
        for field in line.split("  "):
            assert field.strip() in joined, field
    # The band is as tall as the drawn lines, and no text pixel (bright
    # on every channel) sits in its rightmost 8 columns.
    assert info["header_band_px"] == 4 + (8 + 2) * len(info["header_drawn"]) + 2
    band = np.asarray(image.crop((0, 0, w, info["header_band_px"]))).astype(int)
    bright = band.min(axis=2) > 100
    assert bright.any()                                    # text is on the band
    assert not bright[:, w - 8:].any()


# -- round 3: label placement ----------------------------------------------

RIDGE_RASTER = Path(__file__).resolve().parents[1] / "runs" / "terrain" / "control_ridge"
EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def example_scene(name, relocate=None):
    """One committed example as a capture manifest over SYNTHETIC
    telemetry (a straight northbound track at the spec's speed and
    altitude; no FDM flight, so the test runs in seconds): the spec's
    cameras (or the documented defaults), their solved pose tracks and
    schedules, the manifest, the ground (the control_ridge raster when
    ``relocate`` moves the spec over it) and the track points."""
    from core.capture.manifest import build_capture_manifest
    from core.capture.poses import SceneFrame, solve_pose_track
    from core.capture.schedule import solve_schedule
    from core.fdm import units
    from core.scenario.camera import default_cameras
    from core.scenario.spec import ScenarioSpec
    from tests.test_camera_poses import FRAME, make_columns

    spec = ScenarioSpec.read(EXAMPLES_DIR / name)
    heightfield, frame = None, FRAME
    if relocate:
        from core.terrain.heightfield import Heightfield

        heightfield = Heightfield.read(RIDGE_RASTER)
        for key, value in relocate.items():
            spec.set(key, value, frm="test: the example over the ridge raster")
        frame = SceneFrame.for_spec(spec, heightfield)
    cameras = spec.cameras or default_cameras(spec)
    columns = make_columns(duration_s=float(spec.duration.value),
                           speed_mps=units.kt_to_mps(float(spec.airspeed.value)),
                           altitude=lambda t: float(spec.altitude.value))
    if relocate:
        columns["lat_deg"] = [v + float(spec.latitude.value) for v in columns["lat_deg"]]
        columns["lon_deg"] = [v + float(spec.longitude.value) for v in columns["lon_deg"]]
    tracks = [solve_pose_track(columns, c, frame) for c in cameras]
    schedules = [solve_schedule(columns, c, frame) for c in cameras]
    m = build_capture_manifest(spec, columns, frame, tracks, schedules,
                               output_digest="0" * 64, aircraft_metrics=METRICS)
    ground = pv._ground(heightfield, frame)
    track, words = pv._track_points(m, columns, frame)
    return m, ground, float(spec.terrain_elevation.value), track, words


def boxes_intersect(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def test_labels_never_collide_and_stay_with_what_they_name():
    """Over every frame of the three example scenes (cameras_multi,
    cameras_waypoint, cameras_multi over the control_ridge raster: 100
    frames, 3 cameras' presets): no two label boxes intersect, none is
    reported colliding, every label is within 24 px of its anchor or
    has a leader line, no box lies on the header band or the compass,
    'boresight' is within 20 px of its cross, 'N' sits BESIDE the arrow
    head (its box centred on the tip's row, right or left of it) when
    the tip is clear of the band, and ring labels are anchored off the
    arrow's column (RING_LABEL_AZIMUTH_DEG round the ring, capped at a
    quarter of the FOV: 13.6 deg here, 290 px off)."""
    scenes = [example_scene("cameras_multi.yaml"), example_scene("cameras_waypoint.yaml"),
              example_scene("cameras_multi.yaml",
                            {"latitude": 0.138428, "longitude": 10.648732,
                             "altitude": 4200.0, "terrain_elevation": 2094.0})]
    assert scenes[2][1].kind == "terrain" and scenes[0][1].kind == "flat"
    frames = sum(len(m["frames"]) for m, *_ in scenes)
    assert frames == 100
    counted = {"labels": 0, "leaders": 0, "beside": 0, "rings_off_column": 0}
    for m, ground, datum, track, words in scenes:
        for rec in m["frames"]:
            _, info = pv.draw_preview(rec, m, ground, track_points=track,
                                      terrain_elevation_m=datum, track_words=words)
            labels = info["labels"]
            band = info["header_band_px"]
            rose = info["compass"]
            rcx, rcy, rr = rose["centre"][0], rose["centre"][1], rose["radius"]
            compass_zone = (rcx - rr - 14, rcy - rr - 16, rcx + rr + 16,
                            rcy + rr + 20 + 2 * pv.header_font_px(info["size"][1]) + 4)
            tip = (info.get("north_arrow") or {}).get("tip_px")
            for i, a in enumerate(labels):
                counted["labels"] += 1
                for b in labels[i + 1:]:
                    assert not boxes_intersect(a["box"], b["box"]), (rec["camera_id"], rec["index"], a, b)
                assert not a["collided"], (rec["camera_id"], rec["index"], a)
                assert a["distance_px"] <= 24.0 or a["leader"] is not None, a
                counted["leaders"] += a["leader"] is not None
                assert a["box"][1] >= band, (rec["camera_id"], rec["index"], a, band)
                assert not pv._near(a["box"], compass_zone, 0.0), a
                if a["text"] == "boresight":
                    cx, cy = rec["principal_point_px"]
                    assert a["anchor"] == (cx, cy) and a["distance_px"] <= 20.0
                if a["text"] == "N":
                    assert tip is not None and a["anchor"] == (tip[0], tip[1])
                    if tip[1] > band + 40:
                        centre_v = 0.5 * (a["box"][1] + a["box"][3])
                        assert abs(centre_v - tip[1]) <= 1.0, (a, tip)
                        assert a["side"] in ("right", "left") and a["shift"] == 0
                        counted["beside"] += 1
                if a["text"].endswith("km") or a["text"].endswith(" m"):
                    if tip is not None and ground.kind == "flat":
                        assert abs(a["anchor"][0] - tip[0]) > 100.0, (a, tip)
                        counted["rings_off_column"] += 1
    assert counted["labels"] > 150 and counted["beside"] >= 24
    assert counted["rings_off_column"] >= 8 and counted["leaders"] >= 20


def test_label_placement_tries_every_side_and_leads_to_a_far_label():
    """Eight labels on ONE anchor: right, left, above, below and then
    shifted outward, none intersecting, none colliding, every one
    within 24 px or with a leader (the far ones have leaders). A ring
    label whose anchor lies INSIDE the header band (camera pitched -18
    deg: the 20 km ring at row 39, band 91 px) is placed below the
    band with a leader; a label at its requested gap gets no leader."""
    from PIL import ImageDraw

    image = Image.new("RGB", (400, 300), pv.BACKGROUND_RGB)
    draw_ = ImageDraw.Draw(image)
    labels = pv._Labels()
    font = pv._font(14)
    for k in range(8):
        labels.request((200.0, 150.0), f"label {k}", (255, 255, 255), font, priority=k)
    placed = labels.place_all(draw_, 400, 300)
    assert len(placed) == 8 and not any(p["collided"] for p in placed)
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            assert not boxes_intersect(a["box"], b["box"]), (a, b)
        assert a["distance_px"] <= 24.0 or a["leader"] is not None, a
    sides = {p["side"] for p in placed}
    assert {"right", "left"} <= sides
    assert placed[0]["distance_px"] == pv.LABEL_GAP_PX and placed[0]["leader"] is None
    far = [p for p in placed if p["distance_px"] > 24.0]
    assert len(far) >= 4 and all(p["leader"] is not None for p in far)
    # The leader is drawn from the anchor to the box's nearest point.
    lead = far[0]["leader"]
    assert lead[0] == (200.0, 150.0)
    assert abs(math.hypot(lead[1][0] - 200.0, lead[1][1] - 150.0) - far[0]["distance_px"]) < 1e-9
    mid = ((lead[0][0] + lead[1][0]) / 2.0, (lead[0][1] + lead[1][1]) / 2.0)
    assert image.getpixel((int(round(mid[0])), int(round(mid[1])))) == (255, 255, 255)
    # A label anchored inside the band is moved below it, with a leader.
    rec = record(camera=(0.0, 0.0, 1200.0), look=(0.0, -18.0, 0.0),
                 aircraft=(28.0, 0.0, 1200.0))
    _, info = draw(rec)
    band = info["header_band_px"]
    ring = [p for p in info["labels"] if p["text"] == "20 km"][0]
    assert ring["anchor"][1] < band
    assert ring["box"][1] >= band and ring["leader"] is not None
    assert all(p["box"][1] >= band for p in info["labels"])
    # The boresight label: at its gap past the cross arm, no leader.
    bore = [p for p in info["labels"] if p["text"] == "boresight"][0]
    assert bore["distance_px"] == 18.0 and bore["leader"] is None


# -- round 3: the horizon behind the skyline ---------------------------------

def half_ridge_heightfield():
    """41 x 41 at 100 m: a 300 m ridge along east at north -500 on the
    EAST half only (east >= 0), flat ground elsewhere."""
    from core.terrain.heightfield import Georeference, Heightfield

    samples = np.zeros((41, 41), dtype=np.uint16)
    samples[25, 20:] = 300
    return Heightfield(
        samples=samples,
        georeference=Georeference(crs="EPSG:32631", origin_x_m=166021.0 - 2000.0,
                                  origin_y_m=2000.0, pixel_size_m=100.0),
        scale_m=1.0, offset_m=0.0, name="half_ridge")


def test_the_horizon_is_hidden_where_terrain_rises_above_it():
    """A level camera at 100 m, 1 km south of a 300 m ridge that fills
    the east half of the frame: the crest projects at row 111, above
    the horizon row 360. The horizon is solid HORIZON_RGB west of the
    point where the ridge's west slope crosses the horizon row
    (interpolated from the projected foot and crest: u = 557) and
    NEVER HORIZON_RGB east of it -- dashed HORIZON_HIDDEN_RGB over
    terrain or background -- and info counts the columns each way. A
    flat scene keeps the whole horizon; the judge's full-ridge scene
    hides all of it."""
    from tests.test_camera_poses import FRAME

    ground = pv._ground(half_ridge_heightfield(), FRAME)
    rec = record(camera=(-1500.0, 0.0, 100.0), look=(0.0, 0.0, 0.0),
                 aircraft=(-1300.0, 100.0, 150.0))
    cx, cy = rec["principal_point_px"]
    u_c, v_c, _ = project_point(rec, (-500.0, 0.0, 300.0))        # the crest's west end
    u_f, v_f, _ = project_point(rec, (-500.0, -100.0, 0.0))       # the slope's foot
    assert v_c < cy < v_f and u_f < u_c
    split = u_f + (v_f - cy) / (v_f - v_c) * (u_c - u_f)
    assert abs(split - 557.0) < 2.0
    image, info = pv.draw_preview(rec, manifest([rec]), ground)
    runs = info["horizon_runs"]
    assert [seen for _, _, seen in runs] == [True, False]
    assert abs(runs[0][1] - split) <= 2.0 and runs[1][1] == WIDTH
    assert abs(info["horizon_visible_px"] - split) <= 2.0
    assert abs(info["horizon_visible_px"] + info["horizon_hidden_px"] - WIDTH) < 1e-9
    row = int(round(cy))
    # West (past the VFOV text columns): every sampled pixel is horizon.
    west = [image.getpixel((x, row)) for x in range(48, int(split) - 40, 8)]
    assert len(west) > 50 and all(p == pv.HORIZON_RGB for p in west)
    # East: never HORIZON_RGB; dashes in the hidden colour over terrain
    # green, rings or background.
    east = [image.getpixel((x, row)) for x in range(int(cx) + 80, WIDTH - 8)]
    assert len(east) > 400 and not any(p == pv.HORIZON_RGB for p in east)
    # Dashes HORIZON_DASH_PX (4 on, 8 off): Pillow paints a line from u
    # to u + 4 as 5 pixels, so the dashes cover 5/12 of the hidden run.
    dashes = sum(p == pv.HORIZON_HIDDEN_RGB for p in east)
    on, off = pv.HORIZON_DASH_PX
    assert abs(dashes / len(east) - (on + 1) / (on + off)) < 0.03, dashes
    for p in east:
        assert (p in (pv.BACKGROUND_RGB, pv.HORIZON_HIDDEN_RGB, pv.RING_RGB)
                or (p[1] > p[0] and p[1] > p[2])), p
    # horizon_runs alone: a skyline below the row everywhere keeps it.
    clear = pv.horizon_runs(info["horizon"], np.full(WIDTH + 1, np.inf), WIDTH)
    assert clear == [(0.0, float(WIDTH), True)]
    # Flat scene: the whole horizon, one run, nothing hidden.
    _, flat = draw(record(camera=(0.0, 0.0, 1000.0), look=(0.0, 0.0, 0.0),
                          aircraft=(2000.0, 0.0, 1400.0)))
    assert flat["horizon_visible_px"] == WIDTH and flat["horizon_hidden_px"] == 0.0
    assert len(flat["horizon_runs"]) == 1
    # The judge's scene: the ridge across the whole frame hides all of it.
    full = pv._ground(two_ridge_heightfield(), FRAME)
    image, info = pv.draw_preview(rec, manifest([rec]), full)
    assert info["horizon_visible_px"] == 0.0 and info["horizon_hidden_px"] == WIDTH
    assert not any(image.getpixel((x, row)) == pv.HORIZON_RGB for x in range(48, WIDTH - 8, 8))
    # A tile draws the same split at a quarter of the columns.
    _, tile = pv.draw_preview(rec, manifest([rec]), ground, size=(320, 180),
                              style="thumbnail")
    assert abs(tile["horizon_visible_px"] - split / 4.0) <= 1.0
