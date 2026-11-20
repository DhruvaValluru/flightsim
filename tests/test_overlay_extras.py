"""The second wave of the 3-D pictures: the clip's physics over time (CSV
and graphs), landmark names placed through the run's own frame CRS and
the depth image, the weather block, and the estimated surface pressure."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.capture.flight_physics import (SERIES_COLUMNS, clip_series, series_csv,
                                         surface_pressure)
from core.capture.scene_overlay import geodetic_to_scene, landmarks_in_view, scene_geometry

BUNDLE = Path(__file__).parent / "fixtures" / "engine_bundle_min"
FRAME = BUNDLE / "frames" / "chase" / "frame_0000.png"


@pytest.fixture(scope="module")
def manifest():
    return json.loads((BUNDLE / "capture_manifest.json").read_text(encoding="utf-8"))


def test_the_series_is_one_row_per_frame_with_every_column(manifest):
    rows = clip_series(manifest, "chase")
    assert len(rows) == len([r for r in manifest["frames"] if r["camera_id"] == "chase"])
    text = series_csv(rows).splitlines()
    assert text[0].split(",") == [c for c, _ in SERIES_COLUMNS]
    assert text[1].split(",")[2] == "m" and len(text) == 2 + len(rows)
    assert rows[0]["lift_kn"] == pytest.approx(manifest["frames"][0]["state"]["lift_n"] / 1000, abs=1e-3)


def test_the_tangent_plane_conversion_is_metric():
    n, e = geodetic_to_scene(40.7580 + 0.01, -73.9855, 40.7580, -73.9855)
    assert n == pytest.approx(1111.0, rel=0.01) and abs(e) < 1.0
    n, e = geodetic_to_scene(40.7580, -73.9855 + 0.01, 40.7580, -73.9855)
    assert e == pytest.approx(1111.0 * math.cos(math.radians(40.758)), rel=0.01)


def test_a_landmark_is_named_only_where_the_depth_shows_it(manifest, monkeypatch):
    import core.capture.scene_overlay as so

    frame = manifest.get("frame") or {}
    lat0, lon0 = frame.get("origin_lat_deg", 36.09), frame.get("origin_lon_deg", -112.0)
    geo = scene_geometry(manifest, manifest["frames"][0], FRAME)
    # A synthetic landmark at the visible ground point nearest the image centre.
    north, east, alt, horiz = so.world_fields(manifest["frames"][0],
                                              so._depth_grid(FRAME, 320, 180))
    n0, e0 = float(north[120, 160]), float(east[120, 160])
    # Invert the frame's own conversion numerically (small offsets).
    to = so.landmarks_in_view.__globals__["geodetic_to_scene"]
    lat = lat0 + n0 / 111000.0
    lon = lon0 + e0 / (111000.0 * math.cos(math.radians(lat0)))
    monkeypatch.setattr(so, "_landmarks", lambda: [
        {"name": "Here", "lat": lat, "lon": lon, "kind": "area", "height_m": None},
        {"name": "Far away", "lat": lat0 + 5.0, "lon": lon0, "kind": "area", "height_m": None}])
    named = landmarks_in_view(manifest, (north, east, alt, horiz))
    names = [x["name"] for x in named]
    assert "Far away" not in names
    if frame.get("crs") is None:             # the fixture's frame is the tangent plane
        assert "Here" in names


def test_weather_and_the_wind_sun_block_ride_in_the_environment(manifest):
    env = scene_geometry(manifest, manifest["frames"][0], FRAME)["environment"]
    assert "weather" in env and "gust_now_mps" in env["weather"]


def test_surface_pressure_is_highest_where_the_surface_faces_the_flow():
    # A sphere seen head-on, moving toward the camera: stagnation at the
    # centre (Cp ~ 1), suction toward the rim (negative).
    h = w = 81
    K = [[100.0, 0.0, 40.5], [0.0, 100.0, 40.5], [0.0, 0.0, 1.0]]
    yy, xx = np.mgrid[0:h, 0:w]
    x = (xx + 0.5 - 40.5) / 100.0
    y = (yy + 0.5 - 40.5) / 100.0
    R, D = 0.35, 10.0
    # Ray-sphere hit for a sphere of radius R*D at distance D.
    a = x * x + y * y + 1.0
    b = -2.0 * D
    c = D * D - (R * D) ** 2
    disc = b * b - 4 * a * c
    t = np.where(disc > 0, (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a), np.nan)
    depth = t
    mask = np.isfinite(depth)
    # The aircraft moves toward the camera: the air flows away from it (+z).
    cp = surface_pressure(depth, mask, K, [0.0, 0.0, 1.0], mach=0.0)
    assert cp is not None
    assert cp[40, 40] == pytest.approx(1.0, abs=0.1)
    # At 28 px out the surface is ~34.7 deg from the flow: Cp = 1 - 9/4 sin^2
    # = 0.27 (worked by hand); it keeps falling toward the rim.
    assert cp[40, 68] == pytest.approx(0.27, abs=0.06)
    profile = [cp[40, 40 + i] for i in range(0, 33, 4)]
    assert all(a >= b for a, b in zip(profile, profile[1:]))
    assert profile[-1] < 0.0


def test_the_vortex_lattice_loads_a_wing_like_theory():
    from core.capture.flight_physics import vortex_lattice

    flat = vortex_lattice(10.0, 1.0, 0.0, 0.0, 16)
    shape, edges = flat["shape"], flat["edges_m"]
    assert float(np.sum(shape * np.diff(edges))) == pytest.approx(1.0)
    assert shape[7] > shape[0] and shape[8] > shape[-1]          # most load at the root
    assert np.allclose(shape, shape[::-1], rtol=1e-6)             # symmetric
    swept = vortex_lattice(10.0, 1.0, 0.0, -2.5, 16)
    # Sweeping back moves load outboard (the classic swept-wing tip loading).
    assert swept["shape"][8] < shape[8] and swept["shape"][1] > shape[1]
    assert swept["sweep_quarter_chord_deg"] == pytest.approx(26.57, abs=0.05)


def test_the_viewer_page_and_its_frame_json(tmp_path, monkeypatch):
    import shutil

    from fastapi.testclient import TestClient

    import webapp.server as server

    shutil.copytree(BUNDLE, tmp_path / "vw1")
    monkeypatch.setattr(server.manager, "out_root", tmp_path)
    c = TestClient(server.app)
    page = c.get("/viewer.html")
    assert page.status_code == 200 and "/box3d/${index}.json" in page.text
    data = c.get("/runs/vw1/cameras/chase/box3d/0.json").json()
    for key in ("panels", "flight_physics", "overlay", "scene_overlay"):
        assert key in data
    assert data["overlay"]["detailed"]["aircraft"][0]["arrows"]
    again = c.get("/runs/vw1/cameras/chase/box3d/0.json")          # cached
    assert again.status_code == 200
    assert c.get("/runs/vw1/cameras/chase/box3d/9.json").status_code == 404


def test_the_overlay_video_is_encoded_at_the_clip_rate(tmp_path, monkeypatch):
    import shutil
    import subprocess

    import webapp.capture as capture

    run = tmp_path / "vid"
    shutil.copytree(BUNDLE, run)
    manifest = json.loads((run / "capture_manifest.json").read_text(encoding="utf-8"))
    first = manifest["frames"][0]
    second = dict(first, index=1, t_s=float(first["t_s"]) + 0.1,
                  file=first["file"].replace("frame_0000", "frame_0001"))
    manifest["frames"].append(second)
    (run / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for suffix in (".png", "_mask.png", "_depth.f32"):
        shutil.copyfile(run / first["file"].replace(".png", suffix),
                        run / second["file"].replace(".png", suffix))
    seen = {}

    def fake_run(command, capture_output=True, text=True):
        seen["command"] = command
        Path(command[-1]).write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(capture.subprocess, "run", fake_run)
    monkeypatch.setattr("core.util.platform.find_ffmpeg", lambda: Path("ffmpeg"))
    video = capture.box3d_video(run, "chase", "detailed")
    assert video is not None and video.is_file() and video.name == "chase_box3d_detailed.mp4"
    cmd = seen["command"]
    assert float(cmd[cmd.index("-framerate") + 1]) == pytest.approx(10.0, rel=1e-3)
    assert "libx264" in cmd
