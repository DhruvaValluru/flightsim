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
                    "pitch_deg", "heading_deg"):
            assert math.isfinite(aircraft[key]), key
        assert record["file"].startswith(
            f"frames/{record['camera_id']}/")


def test_frames_carry_per_camera_indices_and_paths():
    manifest = build()
    chase_frames = [f for f in manifest["frames"]
                    if f["camera_id"] == "chase0"]
    assert [f["index"] for f in chase_frames] == list(range(20))
    assert chase_frames[3]["file"] == "frames/chase0/frame_0003.png"


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


# -- version 4: the whole recorded row rides with every frame ------------
#
# "attached to each frame is like more data on wind conditions and
# aspects of the plane positioning, everything". Version 3 kept six
# numbers per frame -- the ones the pose solver and the verifier consume
# -- and dropped the other two dozen the recorder had logged at that
# same instant. Version 4 keeps the row.

def wide_columns(duration_s=4.0):
    """The solver's seven plus the kind of channels the recorders
    actually log, with values that identify their sample."""
    columns = make_columns(duration_s=duration_s)
    n = len(columns["t"])
    for name, scale in (("wind_north_mps", 1.0), ("wind_east_mps", 2.0),
                        ("wind_down_mps", 3.0), ("tas_kt", 4.0),
                        ("alpha_deg", 5.0), ("qbar_pa", 6.0),
                        ("lift_n", 7.0), ("n_z", 8.0), ("agl_m", 9.0),
                        ("elevator_deg", 10.0), ("throttle_cmd", 11.0)):
        columns[name] = [scale * i for i in range(n)]
    return columns


def test_every_frame_carries_the_whole_recorded_row():
    columns = wide_columns()
    manifest = build(columns=columns)
    assert manifest["manifest_version"] == MANIFEST_VERSION
    for record in manifest["frames"]:
        i = record["sample_index"]
        state = record["state"]
        # Every column, not a selection -- the recorder's row is the
        # label, and what matters is the consumer's call.
        assert set(state) == set(columns)
        for name in columns:
            assert state[name] == float(columns[name][i]), name
        # The six the solver uses are still where the verifier reads them.
        assert record["aircraft"]["alt_m"] == columns["altitude_m"][i]


def test_state_units_cover_every_channel_and_never_guess():
    from core.capture.manifest import channel_unit

    manifest = build(columns=wide_columns())
    units = manifest["state_units"]
    assert set(units) == set(manifest["frames"][0]["state"])
    assert units["wind_north_mps"] == "m/s"
    assert units["alpha_deg"] == "deg"
    assert units["qbar_pa"] == "Pa"
    assert units["lift_n"] == "N"
    assert units["agl_m"] == "m"
    assert units["tas_kt"] == "kt"
    assert units["t"] == "s"
    assert units["n_z"] == "g"
    assert units["throttle_cmd"] == "1"
    # A name that follows no convention is a question, not a wrong answer.
    assert channel_unit("something_odd") == "?"
    # Longest suffix wins: _mps is not _s.
    assert channel_unit("v_down_mps") == "m/s"
    assert channel_unit("pitch_rate_dps") == "deg/s"


def test_the_conditions_asked_for_ride_at_the_top_level():
    """The request beside the measurement: what the run was told to fly
    in, with its provenance, so 'moderate turbulence' is in the file a
    consumer opens and not only in the prompt that produced it."""
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt in "
                          "moderate turbulence with 20 kt wind")
    chase = CameraSpec.defaulted(camera_id="c", preset="chase",
                                 aircraft="B747")
    chase.set("capture_count", 4, frm="stated")
    spec.cameras = [chase]
    manifest = build(spec=spec)
    conditions = manifest["conditions"]
    assert conditions["turbulence"]["value"] == "moderate"
    assert conditions["turbulence"]["source"] == "inferred"
    assert conditions["wind_speed"]["value"] == 20.0
    assert conditions["wind_speed"]["unit"] == "kt"
    assert conditions["wind_speed"]["source"] == "user"
    assert conditions["altitude"]["unit"] == "m"
    # Only the conditions: the camera and run sections are elsewhere.
    assert "duration" not in conditions and "aircraft" not in conditions


def test_a_version_3_manifest_still_reads(tmp_path):
    """Version 3 is fully interpretable -- it simply has no state on
    its frames -- and every run made before this change is one."""
    manifest = build()
    manifest["manifest_version"] = 3
    for record in manifest["frames"]:
        del record["state"]
    path = write_capture_manifest(manifest, tmp_path)
    assert read_capture_manifest(path)["manifest_version"] == 3


def test_a_sidecar_is_written_beside_every_frame(tmp_path):
    from core.capture.manifest import (
        SIDECAR_CONTEXT_KEYS, frame_sidecar_name, write_frame_sidecars,
    )

    manifest = build(columns=wide_columns())
    written = write_frame_sidecars(manifest, tmp_path)
    assert len(written) == len(manifest["frames"])
    for record in manifest["frames"]:
        path = tmp_path / frame_sidecar_name(record["file"])
        assert path.is_file(), record["file"]
        sidecar = json.loads(path.read_text(encoding="utf-8"))
        # The frame's own record, verbatim.
        assert sidecar["frame"] == json.loads(json.dumps(record))
        # ITS camera, not the first one.
        assert sidecar["camera"]["camera_id"] == record["camera_id"]
        # And the context a record is meaningless without.
        for key in SIDECAR_CONTEXT_KEYS:
            assert key in sidecar["context"], key
        assert sidecar["context"]["state_units"]["wind_north_mps"] == "m/s"
        assert sidecar["context"]["conditions"]["turbulence"]["value"]


def test_stale_sidecars_are_removed_like_stale_frames(tmp_path):
    from core.capture.manifest import write_frame_sidecars

    manifest = build()
    camera_dir = tmp_path / "frames" / manifest["frames"][0]["camera_id"]
    camera_dir.mkdir(parents=True)
    stale = camera_dir / "frame_9999.json"
    stale.write_text("{}", encoding="utf-8")
    unrelated = camera_dir / "notes.json"
    unrelated.write_text("{}", encoding="utf-8")
    write_frame_sidecars(manifest, tmp_path)
    assert not stale.exists(), "a sidecar the manifest does not name"
    assert unrelated.exists(), "only frame_*.json is the manifest's"


def test_a_sidecar_name_only_comes_from_a_frame_image():
    from core.capture.manifest import frame_sidecar_name

    assert frame_sidecar_name("frames/c/frame_0042.png") == \
        "frames/c/frame_0042.json"
    with pytest.raises(ValueError):
        frame_sidecar_name("frames/c/frame_0042.jpg")
