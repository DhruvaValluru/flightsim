"""S2: the passes as data -- flow with validity bits, points, amodal masks,
passes.json and the records -- measured on synthetic bundles.

No engine runs in this container, so the bundles are painted by THIS
file's own ray caster: a camera (the manifest's pinhole, the aerospace
Euler rotation written here), a ground plane at altitude 0, a primary box
airframe and a traffic box crossing in front of it, each rigid, moving
between five telemetry samples 0.1 s apart. Per captured frame it writes
the depth (camera z, +inf for sky), the ID image and each aircraft's
alone pass -- the ``-labels`` bundle -- and the render.json record naming
them. The producer (core/capture/labels.py attach_engine_labels ->
core/capture/passes.py) derives the passes; the verifier
(core/capture/verify.py) grades them with its own readers and projection;
every corruption below fails by name.

What is NOT measured here: an engine writing any of these files (S4's
Windows step), flow on non-rigid parts, a real rig's calibration.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.capture import labels as producer
from core.capture import passes, stereo, verify
from core.capture.poses import PoseTrack, euler_to_quat
from core.scenario.camera import CameraSpec
from core.scenario.fields import Quantity

WIDTH, HEIGHT = 96, 64
FOCAL_MM, SENSOR_W_MM, SENSOR_H_MM = 30.0, 36.0, 24.0         # fx = fy = 80 px
SAMPLES = 5
DT = 0.1
CAMERA = "cam"
PRIMARY, TRAFFIC, TERRAIN = 1, 2, 3
PRIMARY_HALF = (10.0, 8.0, 2.0)                              # forward, right, down (m)
TRAFFIC_HALF = (4.0, 3.0, 1.5)
#: On the faces the camera sees (the primary's aft face and top, the
#: traffic's left side and top), body metres (forward, right, down).
PRIMARY_KEYPOINTS = {"tail_left": (-10.0, -5.0, 0.0), "tail_right": (-10.0, 5.0, 0.0),
                     "tail_top": (-10.0, 0.0, -1.5), "spine": (0.0, 0.0, -2.0),
                     "spine_left": (5.0, -4.0, -2.0), "nose": (10.0, 0.0, 0.0)}
TRAFFIC_KEYPOINTS = {"door": (0.0, -3.0, 0.0), "door_fwd": (2.5, -3.0, 0.5),
                     "roof": (0.0, 0.0, -1.5)}
CAPTURED = (0, 2, 4)
OBJECTS = [
    {"id": "aircraft:box:0", "int_id": PRIMARY, "class": "aircraft", "class_id": 1,
     "role": "primary", "labelled": True, "in_scene": True},
    {"id": "aircraft:small:1", "int_id": TRAFFIC, "class": "aircraft", "class_id": 1,
     "role": "traffic", "labelled": True, "in_scene": True},
    {"id": "terrain:0", "int_id": TERRAIN, "class": "terrain", "class_id": 2,
     "role": "scene", "labelled": True, "in_scene": True},
]


# -- the scene ------------------------------------------------------------------------

def camera_pose(i: int, still: bool = False) -> dict:
    if still:
        return {"north": 0.0, "east": 0.0, "alt": 110.0, "roll": 6.0, "pitch": -4.0, "yaw": 0.0}
    return {"north": 4.0 * i, "east": 0.5 * i, "alt": 110.0, "roll": 6.0,
            "pitch": -4.0 + 0.5 * i, "yaw": 2.0 * i}


def primary_state(i: int) -> dict:
    return {"north_m": 60.0 + 6.0 * i, "east_m": 2.0 - 0.5 * i, "alt_m": 100.0 + 0.3 * i,
            "roll_deg": 5.0 + 3.0 * i, "pitch_deg": 2.0 + 1.0 * i, "heading_deg": 3.0 + 2.0 * i}


def traffic_state(i: int) -> dict:
    return {"north_m": 35.0 + 4.5 * i, "east_m": 9.0 - 5.0 * i, "alt_m": 103.0,
            "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 270.0}


def dcm(roll: float, pitch: float, yaw: float):
    """(forward, right, up) in (north, east, up) of the aerospace
    Z-Y'-X'' rotation -- this file's own expansion."""
    r, p, y = (math.radians(roll), math.radians(pitch), math.radians(yaw))
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    forward = np.array([cp * cy, cp * sy, sp])
    right = np.array([sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp])
    up = np.array([-(cr * sp * cy + sr * sy), -(cr * sp * sy - sr * cy), cr * cp])
    return forward, right, up


def pixel_rays(record: dict, pose: dict):
    """The camera centre and, per pixel centre, the ray direction scaled so
    its component along the optical axis is 1 (the parameter IS depth)."""
    forward, right, up = dcm(pose["roll"], pose["pitch"], pose["yaw"])
    cx, cy = record["principal_point_px"]
    x = ((np.arange(WIDTH) + 0.5 - cx) / record["fx_px"])[None, :, None]
    y = ((np.arange(HEIGHT) + 0.5 - cy) / record["fy_px"])[:, None, None]
    d = forward[None, None, :] + x * right[None, None, :] - y * up[None, None, :]
    return np.array([pose["north"], pose["east"], pose["alt"]]), d


def hit_box(origin, d, state: dict, half):
    """Depth at which each ray enters the oriented box (+inf on a miss)."""
    forward, right, up = dcm(state["roll_deg"], state["pitch_deg"], state["heading_deg"])
    cg = np.array([state["north_m"], state["east_m"], state["alt_m"]])
    t_in = np.full(d.shape[:2], -np.inf)
    t_out = np.full(d.shape[:2], np.inf)
    hit = np.ones(d.shape[:2], dtype=bool)
    for axis, h in zip((forward, right, -up), half):
        o = float((origin - cg) @ axis)
        dd = d @ axis
        parallel = np.abs(dd) < 1e-12
        with np.errstate(divide="ignore", invalid="ignore"):
            t0, t1 = (-h - o) / dd, (h - o) / dd
        t_in = np.maximum(t_in, np.where(parallel, -np.inf, np.minimum(t0, t1)))
        t_out = np.minimum(t_out, np.where(parallel, np.inf, np.maximum(t0, t1)))
        hit &= ~(parallel & (abs(o) > h))
    hit &= (t_out >= t_in) & (t_in > 0.0)
    return np.where(hit, t_in, np.inf)


def render(record: dict, pose: dict, i: int, traffic: bool = True):
    """(depth, ID image, {int_id: alone pass}) of sample i seen from pose."""
    origin, d = pixel_rays(record, pose)
    with np.errstate(divide="ignore"):
        ground = np.where(d[..., 2] < 0.0, -origin[2] / d[..., 2], np.inf)
    prim = hit_box(origin, d, primary_state(i), PRIMARY_HALF)
    traf = hit_box(origin, d, traffic_state(i), TRAFFIC_HALF) if traffic else np.full(prim.shape, np.inf)
    stack = np.stack([ground, prim, traf])
    ids = np.array([TERRAIN, PRIMARY, TRAFFIC])
    depth = stack.min(axis=0)
    mask = np.where(np.isfinite(depth), ids[stack.argmin(axis=0)], 0).astype(np.uint8)
    alone = {PRIMARY: np.where(np.isfinite(prim), PRIMARY, 0).astype(np.uint8)}
    if traffic:
        alone[TRAFFIC] = np.where(np.isfinite(traf), TRAFFIC, 0).astype(np.uint8)
    return depth, mask, alone


def unclipped_box(record: dict, pose: dict, state: dict, half):
    """The projected corner box of an object (the labels' extents box)."""
    forward, right, up = dcm(state["roll_deg"], state["pitch_deg"], state["heading_deg"])
    cg = np.array([state["north_m"], state["east_m"], state["alt_m"]])
    f, r, u = dcm(pose["roll"], pose["pitch"], pose["yaw"])
    centre = np.array([pose["north"], pose["east"], pose["alt"]])
    us, vs = [], []
    for a in (-1, 1):
        for b in (-1, 1):
            for c in (-1, 1):
                p = cg + a * half[0] * forward + b * half[1] * right - c * half[2] * up - centre
                z = p @ f
                if z <= 0:
                    return None
                us.append(record["principal_point_px"][0] + record["fx_px"] * (p @ r) / z)
                vs.append(record["principal_point_px"][1] - record["fy_px"] * (p @ u) / z)
    return [min(us), min(vs), max(us), max(vs)]


def pose_track(camera_id: str, poses) -> PoseTrack:
    return PoseTrack(
        camera_id=camera_id, preset="explicit", horizon_stable=True,
        t=tuple(i * DT for i in range(SAMPLES)),
        north_m=tuple(p["north"] for p in poses), east_m=tuple(p["east"] for p in poses),
        alt_m=tuple(p["alt"] for p in poses),
        quat=tuple(euler_to_quat(p["roll"], p["pitch"], p["yaw"]) for p in poses),
        yaw_deg=tuple(p["yaw"] for p in poses), pitch_deg=tuple(p["pitch"] for p in poses),
        roll_deg=tuple(p["roll"] for p in poses), focal_length_mm=(FOCAL_MM,) * SAMPLES,
        sensor_width_mm=SENSOR_W_MM, sensor_height_mm=SENSOR_H_MM, width_px=WIDTH,
        height_px=HEIGHT, near_m=0.1, far_m=100000.0)


def traffic_track() -> PoseTrack:
    states = [traffic_state(i) for i in range(SAMPLES)]
    return pose_track("traffic", [{"north": s["north_m"], "east": s["east_m"], "alt": s["alt_m"],
                                   "roll": s["roll_deg"], "pitch": s["pitch_deg"],
                                   "yaw": s["heading_deg"]} for s in states])


def frame_record(camera_id: str, index: int, i: int, track: PoseTrack) -> dict:
    record = passes.camera_record_at(track, i)
    record.update({
        "index": index, "camera_id": camera_id,
        "file": f"frames/{camera_id}/frame_{index:04d}.png",
        "yaw_deg": track.yaw_deg[i], "pitch_deg": track.pitch_deg[i], "roll_deg": track.roll_deg[i],
        "focal_length_mm": FOCAL_MM, "sensor_width_mm": SENSOR_W_MM,
        "sensor_height_mm": SENSOR_H_MM, "near_m": 0.1, "far_m": 100000.0,
        "aircraft": primary_state(i)})
    return record


def build_run(tmp_path: Path, name: str = "run", *, still: bool = False,
              words=("flow", "points", "amodal"), baseline=None, right_yaw_error_deg: float = 0.0,
              alone: bool = True, traffic: bool = True, captured=CAPTURED) -> Path:
    """A synthetic manifest-6 run with its render bundle, before attach."""
    from PIL import Image

    run_dir = tmp_path / name
    camera = CameraSpec.defaulted(CAMERA, preset="explicit")
    words = list(words) + (["disparity"] if baseline else [])
    if words:
        camera.passes = Quantity.user(words, frm="test")
    if baseline:
        camera.stereo = Quantity.user({"baseline_m": float(baseline), "side": "right"}, frm="test")
    track = pose_track(CAMERA, [camera_pose(i, still) for i in range(SAMPLES)])
    states_at = passes.object_states_at(PRIMARY, [primary_state(i) for i in range(SAMPLES)],
                                        [(TRAFFIC, traffic_track())])
    rig = [(camera, track, 0.0)]
    if baseline:
        right = stereo.right_camera_spec(camera)
        rig.append((right, stereo.right_track(track, float(baseline), str(right.camera_id.value)),
                    right_yaw_error_deg))
    flown = [c for c, _, _ in rig]
    blocks, frames = [], []
    for cam, cam_track, yaw_error in rig:
        cid = str(cam.camera_id.value)
        block = {"camera_id": cid, "preset": "explicit", "spec": cam.to_dict()}
        stereo_block = stereo.manifest_stereo_block(cam, flown)
        if stereo_block:
            block["stereo"] = stereo_block
        blocks.append(block)
        folder = run_dir / "frames" / cid
        folder.mkdir(parents=True, exist_ok=True)
        records = []
        for index, i in enumerate(captured):
            record = frame_record(cid, index, i, cam_track)
            pose = {"north": cam_track.north_m[i], "east": cam_track.east_m[i],
                    "alt": cam_track.alt_m[i], "roll": cam_track.roll_deg[i],
                    "pitch": cam_track.pitch_deg[i], "yaw": cam_track.yaw_deg[i]}
            block_passes = passes.frame_passes_block(cam, cam_track, i, states_at)
            if block_passes is not None:
                record["passes"] = block_passes
            record["labels"] = {"objects": [
                {"id": o["id"], "int_id": o["int_id"], "class_id": o["class_id"],
                 "bbox_2d_unclipped": (unclipped_box(record, pose, primary_state(i), PRIMARY_HALF)
                                       if o["int_id"] == PRIMARY else
                                       unclipped_box(record, pose, traffic_state(i), TRAFFIC_HALF)
                                       if o["int_id"] == TRAFFIC else None),
                 "basis": {}} for o in OBJECTS]}
            frames.append(record)
            seen = dict(pose, yaw=pose["yaw"] + yaw_error)
            depth, mask, alones = render(record, seen, i, traffic)
            stem = f"frame_{index:04d}"
            Image.fromarray(mask, mode="L").save(folder / f"{stem}_mask.png")
            depth.astype("<f4").tofile(folder / f"{stem}_depth.f32")
            declared = []
            if alone:
                for int_id, image in alones.items():
                    Image.fromarray(image, mode="L").save(folder / f"{stem}_alone_{int_id}.png")
                    declared.append({"int_id": int_id, "alone_png": f"{stem}_alone_{int_id}.png"})
            records.append({"frame": f"{stem}.png",
                            "labels": {"mask": f"{stem}_mask.png", "depth_f32": f"{stem}_depth.f32",
                                       "objects": declared}})
        (folder / "render.json").write_text(json.dumps({"host": "synthetic", "frame_records": records}),
                                            encoding="utf-8")
    manifest = {
        "manifest_version": 6, "spec_digest": "synthetic", "simulation_digest": "synthetic",
        "output_digest": "synthetic", "seed": 0, "aircraft": "box",
        "objects": OBJECTS, "taxonomy": ["aircraft", "terrain"],
        "airframe": {"keypoints": [{"name": n, "body_m": list(b)} for n, b in PRIMARY_KEYPOINTS.items()]},
        "traffic": [{"id": "aircraft:small:1", "int_id": TRAFFIC,
                     "airframe": {"keypoints": [{"name": n, "body_m": list(b)}
                                                for n, b in TRAFFIC_KEYPOINTS.items()]}}],
        "cameras": blocks, "frames": frames,
    }
    (run_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def attach(run_dir: Path) -> dict:
    summary = producer.attach_engine_labels(run_dir)
    assert summary["attached"] == summary["frames"], summary
    return summary


def load(run_dir: Path) -> dict:
    return json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))


def entry_of(run_dir: Path, camera: str, frame: str) -> dict:
    document = json.loads((run_dir / "frames" / camera / "passes.json").read_text(encoding="utf-8"))
    return next(e for e in document["frames"] if e["frame"] == frame)


def rewrite(run_dir: Path, camera: str, frame: str, key: str, change) -> None:
    """Change one pass file (``change(array) -> array``) and re-state its
    sha256 in passes.json, so only the content is wrong."""
    path = run_dir / "frames" / camera / "passes.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    entry = next(e for e in document["frames"] if e["frame"] == frame)
    target = run_dir / "frames" / camera / entry["files"][key]["file"]
    dtype = "u1" if key.endswith(("_valid", "_id")) else "<f4"
    array = np.fromfile(target, dtype=dtype)
    np.ascontiguousarray(change(array.copy()), dtype=dtype).tofile(target)
    entry["files"][key]["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    run_dir = build_run(tmp_path_factory.mktemp("passes"))
    attach(run_dir)
    return run_dir


# -- the producer ---------------------------------------------------------------------

def test_every_requested_pass_is_derived_and_passes_json_names_each_file_by_sha(run):
    manifest = load(run)
    frames = [f for f in manifest["frames"] if f["camera_id"] == CAMERA]
    assert len(frames) == len(CAPTURED)
    document = json.loads((run / "frames" / CAMERA / "passes.json").read_text(encoding="utf-8"))
    assert document["passes_version"] == passes.PASSES_VERSION
    assert document["ztest"] == {"tolerance_fraction": 0.01, "tolerance_m": 2.0}
    for frame in frames:
        block = frame["passes"]
        assert block["file"] == f"frames/{CAMERA}/passes.json"
        assert block["sha256"] == hashlib.sha256(
            (run / "frames" / CAMERA / "passes.json").read_bytes()).hexdigest()
        entry = entry_of(run, CAMERA, Path(frame["file"]).name)
        assert set(entry["files"]) == {"flow_fw", "flow_fw_valid", "flow_bw", "flow_bw_valid",
                                       "points", "points_id"}
        for item in entry["files"].values():
            data = (run / "frames" / CAMERA / item["file"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert set(block["derived"]) == {"flow", "points"}
        for direction in ("forward", "backward"):
            stats = entry["flow"][direction]
            assert block["derived"]["flow"][direction]["valid_fraction"] == stats["valid_fraction"]
    # the ends of the recording: no neighbour, zeros, a basis
    first, last = frames[0], frames[-1]
    assert first["passes"]["neighbours"]["backward"] is None
    assert last["passes"]["neighbours"]["forward"] is None
    assert "no neighbouring" in entry_of(run, CAMERA, "frame_0000.png")["flow"]["backward"]["basis"]
    # the middle frame's neighbours are the telemetry samples 1 and 3, not captured frames
    middle = frames[1]["passes"]["neighbours"]
    assert middle["forward"]["camera"]["sample_index"] == 3
    assert middle["backward"]["camera"]["sample_index"] == 1


def test_the_flow_carries_valid_occluded_and_out_of_frame_bits(run):
    counts = {1: 0, 2: 0, 4: 0}
    for index in range(len(CAPTURED)):
        entry = entry_of(run, CAMERA, f"frame_{index:04d}.png")
        for tag in ("fw", "bw"):
            bits = np.fromfile(run / "frames" / CAMERA / entry["files"][f"flow_{tag}_valid"]["file"],
                               dtype=np.uint8)
            for value in counts:
                counts[value] += int(np.count_nonzero(bits == value))
    assert counts[1] > 1000 and counts[2] > 20 and counts[4] > 10, counts


def test_flow_vs_keypoints_passes_and_every_flow_corruption_fails_by_name(tmp_path):
    run_dir = build_run(tmp_path)
    attach(run_dir)
    check = verify.verify_flow_vs_keypoints(load(run_dir), run_dir)
    assert check.status == verify.PASS, check.detail
    assert float(check.detail.split("within ")[1].split(" px")[0]) < 1e-3, check.detail
    samples = int(check.detail.split(" keypoint samples")[0])
    assert samples >= verify.FLOW_MIN_KEYPOINTS

    def fails(change, key="flow_fw", frame="frame_0001.png"):
        broken = build_run(tmp_path, f"broken_{len(list(tmp_path.iterdir()))}")
        attach(broken)
        rewrite(broken, CAMERA, frame, key, change)
        result = verify.verify_flow_vs_keypoints(load(broken), broken)
        assert result.status == verify.FAIL and result.failure == "annotation.flow", result.detail
        return result.detail

    assert "checker's own projection" in fails(lambda a: a * 1.25)         # scaled
    assert "checker's own projection" in fails(lambda a: -a)                # negated
    assert "checker's own projection" in fails(lambda a: a + 0.3)           # shifted a third of a px
    # the dropped z-test: every occluded pixel marked valid
    detail = fails(lambda a: np.where(a == 2, 1, a), key="flow_fw_valid")
    assert "z-test" in detail and "marked valid" in detail
    # the validity bit itself wrong: out-of-frame pixels marked valid
    assert "z-test" in fails(lambda a: np.where(a == 4, 1, a), key="flow_bw_valid",
                             frame="frame_0002.png")


def test_a_file_that_is_not_the_one_passes_json_names_fails_by_name(tmp_path):
    run_dir = build_run(tmp_path)
    attach(run_dir)
    entry = entry_of(run_dir, CAMERA, "frame_0001.png")
    target = run_dir / "frames" / CAMERA / entry["files"]["flow_bw"]["file"]
    target.write_bytes(target.read_bytes()[:-8] + b"\x00" * 8)
    check = verify.verify_flow_vs_keypoints(load(run_dir), run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.flow"
    assert "not the file passes.json names" in check.detail


def test_a_neighbour_block_that_disagrees_with_the_manifest_fails_by_name(tmp_path):
    run_dir = build_run(tmp_path, captured=(0, 1, 2, 3, 4))       # every sample captured
    attach(run_dir)
    check = verify.verify_flow_vs_keypoints(load(run_dir), run_dir)
    assert check.status == verify.PASS, check.detail
    assert "neighbour cross-check" in check.detail and not check.detail.split(
        " neighbour cross-check")[0].endswith("; 0")
    manifest = load(run_dir)
    manifest["frames"][2]["passes"]["neighbours"]["forward"]["objects"]["1"]["north_m"] += 0.5
    (run_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    check = verify.verify_flow_vs_keypoints(load(run_dir), run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.flow"
    assert "differs from the manifest's own frame" in check.detail


def test_the_static_null_under_a_still_camera_and_the_camera_only_flow_under_a_moving_one(tmp_path, run):
    moving = verify.verify_flow_static_null(load(run), run)
    assert moving.status == verify.PASS, moving.detail
    assert moving.detail.startswith("0 still-camera") and "2 end-of-recording" in moving.detail
    still_dir = build_run(tmp_path, "still", still=True)
    attach(still_dir)
    still = verify.verify_flow_static_null(load(still_dir), still_dir)
    assert still.status == verify.PASS, still.detail
    assert still.detail.startswith("4 still-camera")
    # a static scene gives zero flow: a hundredth of a pixel on the terrain fails
    from PIL import Image

    manifest = load(still_dir)
    mask = np.asarray(Image.open(still_dir / "frames" / CAMERA / "frame_0001_mask.png"))
    terrain = np.repeat((mask == TERRAIN).ravel(), 2)
    rewrite(still_dir, CAMERA, "frame_0001.png", "flow_fw", lambda a: np.where(terrain, a + 0.01, a))
    broken = verify.verify_flow_static_null(manifest, still_dir)
    assert broken.status == verify.FAIL and broken.failure == "annotation.flow"
    assert "static scene gives zero flow" in broken.detail
    # the end of the recording is declared null: a moving pixel there fails
    rewrite(still_dir, CAMERA, "frame_0002.png", "flow_fw", lambda a: np.where(np.arange(a.size) == 7, 1.0, a))
    rewrite(still_dir, CAMERA, "frame_0001.png", "flow_fw", lambda a: np.where(terrain, a - 0.01, a))
    ends = verify.verify_flow_static_null(manifest, still_dir)
    assert ends.status == verify.FAIL and "declared null" in ends.detail


def test_the_camera_only_flow_of_the_static_world_is_graded_too(tmp_path):
    run_dir = build_run(tmp_path)
    attach(run_dir)
    manifest = load(run_dir)
    from PIL import Image

    mask = np.asarray(Image.open(run_dir / "frames" / CAMERA / "frame_0001_mask.png"))
    terrain = np.repeat((mask == TERRAIN).ravel(), 2)
    rewrite(run_dir, CAMERA, "frame_0001.png", "flow_bw", lambda a: np.where(terrain, a * 1.2, a))
    check = verify.verify_flow_static_null(manifest, run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.flow"
    assert "camera's own motion" in check.detail


def test_points_vs_depth_passes_and_the_sky_contributes_none(run):
    manifest = load(run)
    check = verify.verify_points_vs_depth(manifest, run)
    assert check.status == verify.PASS, check.detail
    entry = entry_of(run, CAMERA, "frame_0000.png")
    depth = np.fromfile(run / "frames" / CAMERA / "frame_0000_depth.f32", dtype="<f4")
    assert entry["points"]["total"] == int(np.count_nonzero(np.isfinite(depth)))
    assert entry["points"]["sky_pixels"] == int(np.count_nonzero(~np.isfinite(depth))) > 0
    assert set(entry["points"]["per_object"]) <= {"1", "2", "3"}
    assert "0" not in entry["points"]["per_object"]                # no sky id


def _slide_point_100_half_a_metre_along_its_ray(a):
    points = a.reshape(-1, 4).copy()
    points[100, :3] *= (points[100, 2] + 0.5) / points[100, 2]
    return points.ravel()


@pytest.mark.parametrize("change,words", [
    (_slide_point_100_half_a_metre_along_its_ray, "depth of its pixel"),
    (lambda a: np.concatenate([a, np.array([1.0, 1.0, 1.0, 0.0], dtype=np.float32)]), "points for"),
    (lambda a: np.where(np.arange(a.size) % 4 == 3, 0.5, a), "reflectance"),
])
def test_points_corruptions_fail_by_name(tmp_path, change, words):
    run_dir = build_run(tmp_path, words=("points",))
    attach(run_dir)
    rewrite(run_dir, CAMERA, "frame_0000.png", "points", change)
    if "points for" in words:
        rewrite(run_dir, CAMERA, "frame_0000.png", "points_id",
                lambda a: np.concatenate([a, np.array([3], dtype=np.uint8)]))
    check = verify.verify_points_vs_depth(load(run_dir), run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.points", check.detail
    assert words in check.detail


def test_a_wrong_point_id_or_count_fails_by_name(tmp_path):
    run_dir = build_run(tmp_path, words=("points",))
    attach(run_dir)
    rewrite(run_dir, CAMERA, "frame_0001.png", "points_id", lambda a: np.where(a == 1, 2, a))
    check = verify.verify_points_vs_depth(load(run_dir), run_dir)
    assert check.status == verify.FAIL and "point ids" in check.detail
    fresh = build_run(tmp_path, "counts", words=("points",))
    attach(fresh)
    path = fresh / "frames" / CAMERA / "passes.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["frames"][0]["points"]["per_object"]["3"] += 1
    path.write_text(json.dumps(document), encoding="utf-8")
    check = verify.verify_points_vs_depth(load(fresh), fresh)
    assert check.status == verify.FAIL and "per object" in check.detail


def test_amodal_is_the_alone_pass_and_its_ratio_is_one_over_the_visible_fraction(run):
    manifest = load(run)
    check = verify.verify_amodal_contains_visible(manifest, run)
    assert check.status == verify.PASS, check.detail
    ratios = []
    for frame in manifest["frames"]:
        for entry in frame["labels"]["objects"]:
            if entry["int_id"] == TERRAIN:
                assert "amodal_bbox_2d" not in entry          # aircraft only
                continue
            assert entry["basis"]["amodal"]["basis"] == "alone pass"
            assert entry["amodal_mask"]["file"].endswith(f"_alone_{entry['int_id']}.png")
            if entry["visible_fraction"]:
                assert entry["amodal_ratio"] == pytest.approx(1.0 / entry["visible_fraction"], rel=1e-12)
                ratios.append(entry["amodal_ratio"])
    assert max(ratios) > 1.05                        # the traffic hides part of the primary
    record = {r["name"]: r for r in manifest["applied_variables"]["applied_variables"]}["passes.amodal"]
    assert record["null_test"]["ok"] and record["null_test"]["kind"] == "bounded"


def test_amodal_corruptions_and_a_refusal_beside_an_alone_pass_fail_by_name(tmp_path):
    run_dir = build_run(tmp_path)
    attach(run_dir)
    manifest = load(run_dir)
    entry = manifest["frames"][1]["labels"]["objects"][0]
    entry["amodal_bbox_2d"] = [entry["amodal_bbox_2d"][0] + 1.0] + entry["amodal_bbox_2d"][1:]
    check = verify.verify_amodal_contains_visible(manifest, run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.amodal"
    assert "tight box of the alone pass" in check.detail
    manifest = load(run_dir)
    manifest["frames"][1]["labels"]["objects"][0]["amodal_ratio"] *= 1.01
    check = verify.verify_amodal_contains_visible(manifest, run_dir)
    assert check.status == verify.FAIL and "amodal_ratio" in check.detail
    manifest = load(run_dir)
    manifest["frames"][1]["labels"]["objects"][0]["basis"]["amodal"] = {
        "refused": "annotation.amodal", "reason": "claimed missing"}
    check = verify.verify_amodal_contains_visible(manifest, run_dir)
    assert check.status == verify.FAIL and "though the bundle declares its alone pass" in check.detail


def test_without_an_alone_pass_amodal_is_refused_by_name_never_inferred(tmp_path):
    run_dir = build_run(tmp_path, words=("amodal",), alone=False)
    summary = attach(run_dir)
    assert summary["amodal"]["objects"] == 0 and summary["amodal"]["refused"] > 0
    manifest = load(run_dir)
    for frame in manifest["frames"]:
        for entry in frame["labels"]["objects"]:
            if entry["int_id"] in (PRIMARY, TRAFFIC):
                assert entry["amodal_bbox_2d"] is None and entry["amodal_mask"] is None
                assert entry["basis"]["amodal"]["refused"] == "annotation.amodal"
    check = verify.verify_amodal_contains_visible(manifest, run_dir)
    assert check.status == verify.NOT_RUN and "refused annotation.amodal" in check.detail
    with pytest.raises(passes.PassError) as err:
        producer.amodal_labels(None, np.zeros((2, 2)), PRIMARY, None)
    assert err.value.constraint == "annotation.amodal"


def test_nothing_to_grade_is_not_run_never_a_pass(tmp_path):
    run_dir = build_run(tmp_path, words=())
    attach(run_dir)
    manifest = load(run_dir)
    assert all("passes" not in f for f in manifest["frames"])     # absent-canonical
    for name in ("flow_vs_keypoints", "flow_static_null", "disparity_vs_right_depth",
                 "points_vs_depth", "amodal_contains_visible"):
        check = getattr(verify, f"verify_{name}")(manifest, run_dir)
        assert check.status == verify.NOT_RUN, (name, check.detail)
    headless = verify.verify_flow_vs_keypoints(manifest, None)
    assert headless.status == verify.NOT_RUN


def test_a_bundle_without_depth_refuses_the_pass_by_name(tmp_path):
    run_dir = build_run(tmp_path, words=("points",))
    path = run_dir / "frames" / CAMERA / "render.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for record in payload["frame_records"]:
        del record["labels"]["depth_f32"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(passes.PassError) as err:
        passes.attach_passes(run_dir)
    assert err.value.constraint == "annotation.points"
    headless = build_run(tmp_path, "headless", words=("flow",))
    (headless / "frames" / CAMERA / "render.json").unlink()
    summary = passes.attach_passes(headless)
    assert summary["without_bundle"] == len(CAPTURED) and summary["derived"] == 0
    assert load(headless)["frames"][0]["passes"]["requested"] == ["flow"]


def test_the_records_carry_their_measured_null_tests(run):
    records = {r["name"]: r for r in load(run)["applied_variables"]["applied_variables"]}
    flow = records["passes.flow"]
    assert flow["null_test"]["ok"] and flow["null_test"]["kind"] == "bounded"
    assert flow["null_test"]["with"] < 1e-9                         # a static scene: zero flow
    assert flow["parameters"]["hidden_aircraft_control"]["terrain_p95_px"] > 0.05
    points = records["passes.points"]
    assert points["null_test"]["ok"] and points["null_test"]["with"] == 0.0   # the sky: none
    assert "passes.disparity" not in records                          # no rig on this run
    # the registry carries each as an observer
    from core.registry import REGISTRY

    for name in ("passes.flow", "passes.disparity", "passes.points", "passes.amodal"):
        assert REGISTRY.get(name).spec_path is None


def test_producer_and_verifier_state_the_same_numbers_independently():
    from core.dataset import passes_export
    from core.render.flags import PASS_NAMES

    assert passes.ZTEST_TOL_FRACTION == verify.DEPTH_TOL_FRACTION
    assert passes.ZTEST_TOL_M == verify.DEPTH_TOL_M
    assert (passes.FLOW_VALID, passes.FLOW_OCCLUDED, passes.FLOW_OUT_OF_FRAME) == (
        verify.FLOW_BIT_VALID, verify.FLOW_BIT_OCCLUDED, verify.FLOW_BIT_OUT_OF_FRAME)
    assert (passes_export.FLOW_VALID, passes_export.FLOW_OCCLUDED) == (1, 2)
    assert passes.ENGINE_PASS_WORDS == PASS_NAMES
    assert passes.PASSES_FILE == verify.PASSES_DOCUMENT
    assert stereo.CAMERA_ID_MAX_LEN == __import__("core.capture.validate", fromlist=["x"]).CAMERA_ID_MAX_LEN
    # the verifier imports nothing from the producers
    text = Path(verify.__file__).read_text(encoding="utf-8")
    assert "from .passes" not in text and "import passes" not in text


def test_the_linear_readers_take_s4s_files_and_fall_back_to_the_16_bit_png(tmp_path):
    normals = np.zeros((4, 6, 3), dtype=np.float32)
    normals[..., 2] = 1.0
    normals.astype("<f4").tofile(tmp_path / "n.f32")
    producer.write_rgb16_png(tmp_path / "n.png", producer.encode_normals(np.full((4, 6, 3), [0.0, 0.6, 0.8])))
    assert np.array_equal(passes.read_normal_f32(tmp_path / "n.f32", 6, 4), normals)
    assert np.array_equal(passes.read_normal_pass(tmp_path, {"normal_f32": "n.f32", "normal_png": "n.png"},
                                                  6, 4), normals)
    png = passes.read_normal_pass(tmp_path, {"normal_png": "n.png"}, 6, 4)
    assert png[0, 0, 1] == pytest.approx(0.6, abs=1e-4)
    assert passes.read_normal_pass(tmp_path, {}, 6, 4) is None
    with pytest.raises(passes.PassError):
        passes.read_basecolor_f32(tmp_path / "n.f32", 5, 4)
    albedo = np.full((4, 6, 3), 0.25, dtype=np.float32)
    albedo.tofile(tmp_path / "b.f32")
    assert np.array_equal(passes.read_basecolor_pass(tmp_path, {"basecolor_f32": "b.f32"}, 6, 4), albedo)


def test_the_passes_a_camera_asks_for_are_absent_canonical_and_refused_by_name():
    camera = CameraSpec.defaulted("c", preset="explicit")
    assert passes.requested_passes(camera) == () and passes.pass_violations(camera) == []
    track = pose_track("c", [camera_pose(i) for i in range(SAMPLES)])
    states_at = passes.object_states_at(PRIMARY, [primary_state(i) for i in range(SAMPLES)], [])
    assert passes.frame_passes_block(camera, track, 2, states_at) is None
    camera.passes = Quantity.user(["points", "normal"], frm="test")
    block = passes.frame_passes_block(camera, track, 2, states_at)
    assert block == {"requested": ["normal", "points"]}               # no flow: no neighbours
    assert passes.engine_words([camera]) == ["normal"]
    for value, words in ((["flw"], "unknown pass word"), (["flow", "flow"], "repeated"),
                         (["disparity"], "stereo rig"), ("flow", "list of pass words")):
        camera.passes = Quantity.user(value, frm="test")
        (violation,) = passes.pass_violations(camera)
        assert violation.constraint == "sensing.pass" and words in violation.message
