"""The 3D camera placer: the page's terrain view and its exact placement.

The picker's presets and the sentence reader land a camera somewhere
sensible; the placer is how a user puts it at an EXACT x / y / z. These
tests pin the server half: the terrain grid is the scene raster sampled
in the pose solver's frame (not a second copy of the conventions), every
number the user moved is user-stated, and a camera under the ground is
refused by name before any engine time.
"""

import numpy as np
from fastapi.testclient import TestClient

from webapp.server import app


def compiled_spec(terrain_source=None):
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    if terrain_source:
        spec.set("scene.terrain_source", terrain_source)
    return spec.to_dict()


def flat():
    """A spec pinned to the datum slab, so the test does not depend on
    which bakes this machine happens to hold."""
    return compiled_spec("flat")


def values(spec):
    from core.scenario.spec import ScenarioSpec

    s = ScenarioSpec.from_dict(spec)
    return float(s.altitude.value), float(s.terrain_elevation.value)


def fields(camera):
    return {f["name"]: f for f in camera["fields"]}


def test_terrain_payload_states_the_scene_in_the_solver_frame():
    client = TestClient(app)
    spec = flat()
    alt, datum = values(spec)
    reply = client.post("/cameras/terrain", json={"spec": spec})
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["kind"] == "flat"
    grid = data["grid"]
    assert len(grid["heights_m"]) == grid["points"] ** 2
    assert set(grid["heights_m"]) == {datum}
    assert data["aircraft"]["alt_m"] == alt
    # The window is centred on the origin, where the aircraft starts.
    assert grid["south_m"] == grid["west_m"] < 0
    assert data["aircraft"]["north_m"] == data["aircraft"]["east_m"] == 0.0
    assert data["track"][0]["t_s"] == 0.0
    assert data["min_clearance_m"] > 0


def test_the_straight_line_track_follows_the_heading():
    from core.scenario.spec import ScenarioSpec
    from webapp.camera_placer import track_estimate

    spec = ScenarioSpec.from_dict(compiled_spec())
    spec.set("heading", 90.0)
    track = track_estimate(spec, 10.0)
    end = track[-1]
    assert abs(end["north_m"]) < 1e-6
    assert end["east_m"] > 0
    assert end["alt_m"] == float(spec.altitude.value)


def test_the_grid_is_the_raster_bilinear_sample():
    """The page's terrain must be the raster the capture stage queries:
    every grid node equals Heightfield.elevation_at at that point."""
    from core.capture.poses import SceneFrame
    from core.terrain.heightfield import Georeference, Heightfield
    from webapp.camera_placer import _sample_grid

    rng = np.random.default_rng(3)
    z = 1000.0 + rng.normal(0.0, 150.0, (200, 220))
    geo = Georeference(crs="EPSG:32633", origin_x_m=500000.0,
                       origin_y_m=5200000.0, pixel_size_m=30.0)
    field = Heightfield.from_elevations(z, geo)
    frame = SceneFrame("EPSG:32633", 0.0, 15.0, declared=False)
    # Put the frame origin inside the raster.
    frame.origin_x_m = 500000.0 + 110 * 30.0
    frame.origin_y_m = 5200000.0 - 100 * 30.0
    heights, step, points = _sample_grid(field, frame, 2000.0, 33)
    half = step * (points - 1) / 2
    assert half <= 2000.0 + 1e-6
    for r in (0, 7, 16, 32):
        for c in (0, 11, 32):
            x, y = frame.to_projected(-half + r * step, -half + c * step)
            assert abs(heights[r * points + c] - field.elevation_at(x, y)) < 0.06


def test_a_world_camera_is_an_explicit_scene_camera_the_user_stated():
    client = TestClient(app)
    spec = flat()
    alt, _ = values(spec)
    reply = client.post("/cameras/place", json={"spec": spec, "placement": {
        "mode": "world", "east_m": 120.5, "north_m": -340.0,
        "alt_m": alt + 50.0, "aim": "aircraft", "focal_length_mm": 85.0}})
    assert reply.status_code == 200, reply.json()
    payload = reply.json()
    camera = payload["cameras"][payload["placed_index"]]
    assert camera["camera_id"] == "placed"
    assert camera["preset"] == "explicit"
    f = fields(camera)
    assert f["position_mode"]["value"] == "scene"
    assert f["position_east_m"]["value"] == 120.5
    assert f["position_north_m"]["value"] == -340.0
    assert f["position_alt_m"]["value"] == alt + 50.0
    assert f["aim_mode"]["value"] == "aircraft"
    assert f["focal_length_mm"]["value"] == 85.0
    for name in ("position_mode", "position_east_m", "position_north_m",
                 "position_alt_m", "aim_mode", "focal_length_mm"):
        assert f[name]["source"] == "user", name
    # Like a picked view, it captures the whole clip.
    assert f["trigger"]["value"] == "continuous"


def test_a_fixed_direction_camera_keeps_its_bearing_and_elevation():
    client = TestClient(app)
    spec = flat()
    alt, _ = values(spec)
    reply = client.post("/cameras/place", json={"spec": spec, "placement": {
        "mode": "world", "east_m": 0, "north_m": -500, "alt_m": alt,
        "aim": "bearing", "bearing_deg": 365.0, "elevation_deg": -4.5}})
    assert reply.status_code == 200, reply.json()
    f = fields(reply.json()["cameras"][0])
    assert f["aim_mode"]["value"] == "bearing"
    assert f["aim_bearing_deg"]["value"] == 5.0
    assert f["aim_elevation_deg"]["value"] == -4.5


def test_a_follow_camera_is_a_chase_at_the_stated_offset():
    client = TestClient(app)
    reply = client.post("/cameras/place", json={
        "spec": flat(), "placement": {
            "mode": "follow", "forward_m": -150.0, "right_m": 40.0,
            "up_m": 22.0}})
    assert reply.status_code == 200, reply.json()
    camera = reply.json()["cameras"][0]
    assert camera["preset"] == "chase"
    f = fields(camera)
    assert f["position_mode"]["value"] == "offset"
    assert (f["offset_forward_m"]["value"], f["offset_right_m"]["value"],
            f["offset_up_m"]["value"]) == (-150.0, 40.0, 22.0)
    assert f["offset_forward_m"]["source"] == "user"


def test_a_camera_under_the_ground_is_refused_by_name():
    client = TestClient(app)
    spec = flat()
    _, datum = values(spec)
    reply = client.post("/cameras/place", json={"spec": spec, "placement": {
        "mode": "world", "east_m": 0, "north_m": -500,
        "alt_m": datum - 10.0}})
    assert reply.status_code == 409
    assert reply.json()["refused"] == "camera.terrain_clearance"


def test_replace_overwrites_the_camera_and_keeps_its_id():
    client = TestClient(app)
    spec = flat()
    alt, _ = values(spec)
    for preset in ("chase", "tower"):
        spec = client.post("/cameras", json={"spec": spec,
                                              "preset": preset}).json()["dict"]
    reply = client.post("/cameras/place", json={"spec": spec, "placement": {
        "mode": "world", "east_m": 10, "north_m": 20, "alt_m": alt,
        "replace": 1}})
    assert reply.status_code == 200, reply.json()
    cameras = reply.json()["cameras"]
    assert [c["camera_id"] for c in cameras] == ["chase", "tower"]
    assert cameras[1]["preset"] == "explicit"
    assert fields(cameras[1])["position_north_m"]["value"] == 20


def test_a_malformed_placement_is_named():
    client = TestClient(app)
    reply = client.post("/cameras/place", json={
        "spec": compiled_spec(), "placement": {"mode": "world",
                                               "east_m": "far"}})
    assert reply.status_code == 400
    assert "east_m" in reply.json()["error"]
    reply = client.post("/cameras/place", json={
        "spec": compiled_spec(), "placement": {"mode": "orbit"}})
    assert reply.status_code == 400


def test_the_page_loads_the_placer():
    from pathlib import Path

    static = Path(__file__).resolve().parents[1] / "webapp" / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    assert '<script src="/camera3d.js"></script>' in page
    assert "openCameraPlacer" in page
    reply = TestClient(app).get("/camera3d.js")
    assert reply.status_code == 200
    assert "window.CameraPlacer" in reply.text
