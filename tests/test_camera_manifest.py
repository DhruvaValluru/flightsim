"""Camera Phase 1, package E: the capture manifest.

Written headlessly, with no engine present, on every platform: per
frame the full pose + intrinsics + aircraft state, per run the digests
that tie it to exactly one spec, one telemetry record and one terrain
raster. A consumer validates manifest_version before parsing.
"""

import json
import math

import pytest

from core.capture.manifest import (
    MANIFEST_VERSION, build_capture_manifest, read_capture_manifest,
    simulation_digest, write_capture_manifest,
)
from core.capture.poses import solve_pose_track
from core.capture.schedule import solve_schedule
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


def build(spec=None, columns=None):
    spec = spec or spec_with_cameras()
    columns = columns or make_columns(duration_s=10.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(
        spec, columns, FRAME, tracks, schedules,
        output_digest="0" * 64, scene={"key": "flat", "terrain": None})


def spec_with_cameras():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    chase = CameraSpec.defaulted(camera_id="chase0", preset="chase",
                                 aircraft="B747")
    chase.set("capture_count", 20, frm="stated")
    tower = CameraSpec.defaulted(camera_id="tower0", preset="tower",
                                 terrain_elevation_m=0.0)
    tower.set("capture_count", 20, frm="stated")
    spec.cameras = [chase, tower]
    return spec


def test_manifest_written_headlessly_with_no_engine(tmp_path):
    manifest = build()
    path = write_capture_manifest(manifest, tmp_path)
    assert path.name == "capture_manifest.json"
    reread = read_capture_manifest(path)
    assert reread == json.loads(json.dumps(manifest))


def test_unknown_manifest_version_refuses(tmp_path):
    manifest = build()
    manifest["manifest_version"] = 99
    path = write_capture_manifest(manifest, tmp_path)
    with pytest.raises(ValueError, match="not supported"):
        read_capture_manifest(path)


def test_every_frame_field_is_present_and_finite():
    manifest = build()
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert len(manifest["frames"]) == 40          # 20 per camera
    numeric = ("t_s", "position_north_m", "position_east_m",
               "position_alt_m", "yaw_deg", "pitch_deg", "roll_deg",
               "focal_length_mm", "sensor_width_mm", "sensor_height_mm",
               "near_m", "far_m", "fx_px", "fy_px")
    for record in manifest["frames"]:
        for key in numeric:
            assert math.isfinite(record[key]), key
        assert len(record["quaternion_wxyz"]) == 4
        assert all(math.isfinite(v) for v in record["quaternion_wxyz"])
        assert abs(sum(v * v for v in record["quaternion_wxyz"]) - 1.0) \
            < 1e-9
        assert record["width_px"] > 0 and record["height_px"] > 0
        assert record["principal_point_px"] == [record["width_px"] / 2.0,
                                                record["height_px"] / 2.0]
        aircraft = record["aircraft"]
        for key in ("north_m", "east_m", "alt_m", "roll_deg",
                    "pitch_deg", "heading_deg", "speed_mps"):
            assert math.isfinite(aircraft[key]), key
        assert record["file"].startswith(
            f"frames/{record['camera_id']}/")


def test_manifest_carries_the_fixed_step_grid_and_the_aircraft_speed():
    """The verifier's engine-parity clock tolerance and drawn-aircraft
    budget come from the MANIFEST: rate_hz (the spec's), step_s, and per
    frame the aircraft's speed with its basis stated -- the recorded
    tas_kt channel when the record has one, else the ground speed of the
    recorded track (the synthetic record: 100 m/s northbound in
    degrees, 99.43 m/s through the scene frame's own projection)."""
    from core.capture.schedule import off_grid_instants

    manifest = build()
    assert manifest["rate_hz"] == 120.0
    assert manifest["step_s"] == pytest.approx(1.0 / 120.0)
    assert manifest["speed_basis"] == ("ground speed of the recorded track "
                                       "(no tas_kt channel)")
    for record in manifest["frames"]:
        assert record["aircraft"]["speed_mps"] == pytest.approx(99.43, abs=0.01)
    assert off_grid_instants([r["t_s"] for r in manifest["frames"]],
                             manifest["rate_hz"]) == []

    columns = make_columns(duration_s=10.0)
    columns["tas_kt"] = [250.0] * len(columns["t"])
    manifest = build(columns=columns)
    assert manifest["speed_basis"] == ("true airspeed from the recorded "
                                       "tas_kt channel")
    assert manifest["frames"][0]["aircraft"]["speed_mps"] == pytest.approx(
        250.0 * 0.514444, abs=1e-3)


def test_manifest_refuses_a_schedule_off_the_fixed_step_grid():
    """A schedule whose instant is not on the spec's grid is refused by
    name before any manifest exists: the engine captures on fixed steps
    and never approximates an instant."""
    columns = make_columns(duration_s=10.0, dt=0.1)
    columns["t"][5] = 0.5 + 0.003          # 0.503 s: not a 1/120 s step
    spec = spec_with_cameras()
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    with pytest.raises(ValueError, match="camera.schedule.*off the 120 Hz "
                                          "fixed-step grid"):
        build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                               output_digest="0" * 64)


def test_frames_carry_per_camera_indices_and_paths():
    manifest = build()
    chase_frames = [f for f in manifest["frames"]
                    if f["camera_id"] == "chase0"]
    assert [f["index"] for f in chase_frames] == list(range(20))
    # Named by the manifest index, exactly the file the engine's
    # consume-poses pass writes for this record.
    assert chase_frames[3]["file"] == "frames/chase0/0003.png"


def test_digests_tie_the_manifest_to_its_run():
    spec = spec_with_cameras()
    manifest = build(spec)
    assert manifest["spec_digest"] == spec.digest()
    assert manifest["output_digest"] == "0" * 64
    assert manifest["seed"] == int(spec.seed.value)
    assert manifest["frame"]["crs"] == FRAME.crs


def test_simulation_digest_ignores_cameras_only():
    """The simulation identity: cameras out, everything else in."""
    spec = spec_with_cameras()
    bare = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    assert simulation_digest(spec) == simulation_digest(bare)
    assert spec.digest() != bare.digest()
    other = compile_prompt("fly the 747 at 9000 ft and 280 kt")
    assert simulation_digest(spec) != simulation_digest(other)


def test_camera_blocks_state_roll_inheritance():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    cockpit = CameraSpec.defaulted(camera_id="shoulder", preset="cockpit",
                                   aircraft="B747")
    cockpit.set("capture_count", 5, frm="stated")
    spec.cameras = [cockpit]
    manifest = build(spec)
    block = manifest["cameras"][0]
    assert block["horizon_stable"] is False
    assert block["inherits_roll"] is True
    assert block["pose_track_digest"]
    assert block["spec"]["preset"]["value"] == "cockpit"


def test_mismatched_track_and_schedule_refuse():
    spec = spec_with_cameras()
    columns = make_columns(duration_s=10.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME)
                 for c in reversed(spec.cameras)]
    with pytest.raises(ValueError, match="misattributed"):
        build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                               output_digest="0" * 64)
