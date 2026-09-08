"""The two checks that need pixels, exercised without an engine.

``landmark_reprojection`` and ``cross_view_consistency`` report NOT RUN
until a render.json carries the engine's own landmark pixels, which
means neither runs on CI, on Linux, or on any Windows machine before
Unreal is installed. Untested checks rot, so this file stands a
render.json in for the engine.

The substitution is only honest if the stand-in does not borrow the
producer's arithmetic. :func:`engine_style_pixel` therefore builds the
projection the way the commandlet does -- a world-to-camera basis and a
tangent-of-half-FOV image plane, taking its field of view from the
recorded focal length and sensor width exactly as
``FlightSimRenderCommandlet.cpp`` now does -- and imports nothing from
:mod:`core.capture.verify` or :mod:`core.capture.poses`. If the
manifest's documented projection and that construction disagree, these
tests fail, which is the whole point.

What this cannot do is prove the REAL engine agrees; only a Windows
render can. It proves the checks are wired, sensitive, and fail on a
disagreement of the size that matters.
"""

import json
import math
from pathlib import Path

import pytest

from core.capture.manifest import build_capture_manifest
from core.capture.poses import solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, NOT_RUN, PASS, verify_landmark_reprojection, verify_triangulation,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


def engine_style_pixel(record, point):
    """(px, py, visible) built from scratch, the commandlet's way.

    Basis from the recorded Euler angles (NOT the quaternion the
    verifier uses), image plane from tan(FOV/2) where FOV comes from
    focal length and sensor width -- the same route
    FlightSimRenderCommandlet takes now that its field of view follows
    the solved lens instead of a hardcoded constant.
    """
    yaw = math.radians(record["yaw_deg"])
    pitch = math.radians(record["pitch_deg"])
    roll = math.radians(record["roll_deg"])
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    # Body->NED rows, then flip Down to Up for the (north, east, up)
    # frame the manifest works in.
    forward = (cp * cy, cp * sy, sp)
    right = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    up = (-(cr * sp * cy + sr * sy), -(cr * sp * sy - sr * cy), cr * cp)

    delta = (point[0] - record["position_north_m"],
             point[1] - record["position_east_m"],
             point[2] - record["position_alt_m"])
    depth = sum(a * b for a, b in zip(forward, delta))
    if depth <= 0.0:
        return math.nan, math.nan, False
    lateral = sum(a * b for a, b in zip(right, delta))
    vertical = sum(a * b for a, b in zip(up, delta))

    width = float(record["width_px"])
    height = float(record["height_px"])
    half_fov = math.atan(record["sensor_width_mm"]
                         / (2.0 * record["focal_length_mm"]))
    half_width_tan = math.tan(half_fov)
    half_height_tan = half_width_tan * height / width
    px = width * 0.5 * (1.0 + (lateral / depth) / half_width_tan)
    py = height * 0.5 * (1.0 - (vertical / depth) / half_height_tan)
    return px, py, (0.0 <= px < width and 0.0 <= py < height)


def counted(preset, camera_id, count=10, **kwargs):
    camera = CameraSpec.defaulted(camera_id=camera_id, preset=preset,
                                  aircraft="B747", **kwargs)
    camera.set("capture_count", count, frm="test")
    return camera


@pytest.fixture
def manifest():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [counted("chase", "chase0"), counted("tower", "tower0")]
    columns = make_columns(duration_s=14.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                  output_digest="digest",
                                  cameras=spec.cameras)


def write_render_json(manifest, run_dir, jitter_px=0.0, only_camera=None):
    """A render.json in the commandlet's shape, one per camera
    directory, with every landmark projected the engine's way."""
    from core.capture.landmarks import landmark_point

    by_camera = {}
    for record in manifest["frames"]:
        by_camera.setdefault(record["camera_id"], []).append(record)
    for camera_id, records in by_camera.items():
        frames = []
        for record in records:
            landmarks = {}
            for landmark in manifest["landmarks"]:
                px, py, visible = engine_style_pixel(
                    record, landmark_point(landmark))
                if only_camera in (None, camera_id):
                    px += jitter_px
                landmarks[landmark["name"]] = {
                    "visible": bool(visible), "px": px, "py": py}
            # The engine records the BASENAME, because the commandlet only
            # knows the directory it was told to write into. This fixture
            # used to record the manifest's full relative path, which made
            # the lookup appear to work in tests while never matching a
            # real render.json -- so both engine checks reported NOT RUN
            # on a real run and these tests could not see it.
            frames.append({"frame": Path(record["file"]).name,
                           "landmarks": landmarks})
        path = run_dir / "frames" / camera_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "render.json").write_text(
            json.dumps({"frames": frames}), encoding="utf-8")


def test_landmark_reprojection_is_not_run_without_a_render(manifest, tmp_path):
    check = verify_landmark_reprojection(manifest, tmp_path)
    assert check.status == NOT_RUN


def test_the_manifest_projection_agrees_with_an_engine_style_one(
        manifest, tmp_path):
    """The independent reprojection the phase exit criterion asks for:
    two constructions of the same projection, landing on the same
    pixel."""
    write_render_json(manifest, tmp_path)
    check = verify_landmark_reprojection(manifest, tmp_path)
    assert check.status == PASS, check.detail
    assert "agree with the engine's own" in check.detail


def test_a_field_of_view_disagreement_is_caught(manifest, tmp_path):
    """The Phase 1 defect, made detectable. The commandlet rendered at a
    hardcoded 55 deg while the documented default lens is 54.43 deg --
    about 7 px 600 px off centre. Here the manifest keeps its lens and
    the engine's pixels come from a different one; the check must see
    it."""
    write_render_json(manifest, tmp_path)
    for record in manifest["frames"]:
        record["focal_length_mm"] *= 1.02          # ~0.6 deg of FOV
        record["fx_px"] = (record["focal_length_mm"]
                           / record["sensor_width_mm"] * record["width_px"])
        record["fy_px"] = (record["focal_length_mm"]
                           / record["sensor_height_mm"] * record["height_px"])
    check = verify_landmark_reprojection(manifest, tmp_path)
    assert check.status == FAIL
    assert "px between this projection" in check.detail


def test_a_small_pixel_disagreement_is_within_tolerance(manifest, tmp_path):
    """The check has to be sensitive without being brittle: a sub-pixel
    disagreement is rendering noise, not a geometry bug."""
    write_render_json(manifest, tmp_path, jitter_px=0.4)
    assert verify_landmark_reprojection(manifest, tmp_path).status == PASS


def test_a_displaced_camera_is_caught_against_the_engine(manifest, tmp_path):
    """Belt and braces with pose_matches_spec: when pixels exist, a
    camera in the wrong place also disagrees with the engine."""
    write_render_json(manifest, tmp_path)
    for record in manifest["frames"]:
        if record["camera_id"] == "chase0":
            record["position_east_m"] += 25.0
    assert verify_landmark_reprojection(manifest, tmp_path).status == FAIL


def test_two_view_triangulation_recovers_the_landmarks(manifest, tmp_path):
    """Cross-view consistency with a reference that is not the manifest:
    a static landmark seen from two cameras at one instant, back-
    projected through each camera's own pose, meets at where the scene
    says the landmark is.

    Phase 1 triangulated the AIRCRAFT, using each record's copy of one
    array, and could not fail. This can.
    """
    write_render_json(manifest, tmp_path)
    check = verify_triangulation(manifest, tmp_path)
    assert check.status == PASS, check.detail
    assert "two-view landmark sightings" in check.detail


def test_triangulation_catches_one_camera_in_the_wrong_place(
        manifest, tmp_path):
    """Move ONE camera's recorded pose after the pixels were measured:
    its ray now misses, and the two views no longer meet at the
    landmark."""
    write_render_json(manifest, tmp_path)
    for record in manifest["frames"]:
        if record["camera_id"] == "tower0":
            record["position_north_m"] += 40.0
    check = verify_triangulation(manifest, tmp_path)
    assert check.status == FAIL
    assert "triangulates" in check.detail
