"""S2: the passes in the KITTI layout and in WebDataset, round-tripped
through INDEPENDENT readers.

Every read here is written from the KITTI devkit's own definitions --
flow_read (u = (R - 2^15) / 64, valid = B > 0), disp_read (d = value /
256, valid = value > 0), the velodyne binary (float32 N x 4) -- over
rasterio's libpng for the PNGs and numpy.fromfile for the binaries,
never through core/dataset/passes_export.py. The expected numbers come
from the pass files the producer wrote (read with numpy) and the
manifest read with json. The export ships a pass file only from a run
whose verdict has that pass's checks PASS (export.unverified_labels by
name otherwise), and the card names the consumer of every pass.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pytest

from core.capture import labels as producer
from core.capture import verify
from core.dataset import passes_export
from tests.test_passes import CAMERA, attach, build_run, load

S2_CHECKS = ("flow_vs_keypoints", "flow_static_null", "disparity_vs_right_depth",
             "points_vs_depth", "normals_vs_depth")


# -- the independent readers ------------------------------------------------------------

def read_png16(path: Path):
    """(h, w) or (h, w, c) uint16 through rasterio (libpng)."""
    import rasterio

    with rasterio.open(path) as dataset:
        planes = dataset.read()
    assert planes.dtype == np.uint16
    return planes[0] if planes.shape[0] == 1 else np.transpose(planes, (1, 2, 0))


def kitti_flow_read(path: Path):
    """The devkit's flow_read: u, v in pixels and the valid mask."""
    image = read_png16(path).astype(np.float64)
    u = (image[..., 0] - 2 ** 15) / 64.0
    v = (image[..., 1] - 2 ** 15) / 64.0
    return u, v, image[..., 2] > 0


def kitti_disp_read(path: Path):
    """The devkit's disp_read: d = value / 256, valid where value > 0."""
    image = read_png16(path).astype(np.float64)
    return image / 256.0, image > 0


def velodyne_read(path: Path):
    return np.fromfile(path, dtype="<f4").reshape(-1, 4)


# -- the encoders, one at a time ------------------------------------------------------------

def test_the_kitti_flow_encoding_round_trips_through_the_devkit_reading(tmp_path):
    rng = np.random.default_rng(3)
    flow = rng.uniform(-40.0, 40.0, (12, 16, 2)).astype(np.float32)
    flow[0, 0] = (600.0, 0.0)                              # beyond the encoding's +-512 px
    bits = rng.choice([0, 1, 2, 4], size=(12, 16)).astype(np.uint8)
    bits[0, 0] = 1
    for occ, expect in ((True, (bits == 1) | (bits == 2)), (False, bits == 1)):
        image, dropped = passes_export.kitti_flow_image(flow, bits, include_occluded=occ)
        passes_export.write_png16(tmp_path / "f.png", image)
        u, v, valid = kitti_flow_read(tmp_path / "f.png")
        expect = expect.copy()
        expect[0, 0] = False
        assert dropped == 1
        assert np.array_equal(valid, expect)
        assert np.abs(u[valid] - flow[..., 0][valid]).max() <= 1.0 / 128.0 + 1e-9
        assert np.abs(v[valid] - flow[..., 1][valid]).max() <= 1.0 / 128.0 + 1e-9


def test_the_kitti_disparity_encoding_round_trips_through_the_devkit_reading(tmp_path):
    d = np.array([[0.0, 0.001, 3.25, 17.8], [255.0, 300.0, 1.0 / 256.0, 64.5]], dtype=np.float32)
    image, dropped = passes_export.kitti_disparity_image(d, d > 0.0)
    passes_export.write_png16(tmp_path / "d.png", image)
    read, valid = kitti_disp_read(tmp_path / "d.png")
    assert dropped == 2                                   # 0.001 rounds to 0; 300 overflows
    assert valid.tolist() == [[False, False, True, True], [True, False, True, True]]
    assert np.abs(read[valid] - d[valid]).max() <= 1.0 / 512.0 + 1e-9


def test_the_velodyne_axes_and_the_calib_undo_each_other():
    rng = np.random.default_rng(5)
    camera = rng.uniform(-50.0, 50.0, (20, 4)).astype(np.float32)
    camera[:, 3] = 0.0
    velo = passes_export.velodyne_points(camera)
    assert np.array_equal(velo[:, 0], camera[:, 2])        # x forward = camera z
    assert np.array_equal(velo[:, 1], -camera[:, 0])       # y left = -camera x
    assert np.array_equal(velo[:, 2], -camera[:, 1])       # z up = -camera y
    line = passes_export.kitti_calib_velodyne()
    matrix = np.array([float(x) for x in line.split(":")[1].split()]).reshape(3, 4)
    back = velo[:, :3].astype(np.float64) @ matrix[:, :3].T + matrix[:, 3]
    assert np.allclose(back, camera[:, :3], atol=0.0)


def test_the_normal_encoding_round_trips(tmp_path):
    rng = np.random.default_rng(9)
    n = rng.normal(size=(6, 7, 3))
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    passes_export.write_png16(tmp_path / "n.png", passes_export.encode_normals16(n))
    back = read_png16(tmp_path / "n.png").astype(np.float64) / 65535.0 * 2.0 - 1.0
    assert np.abs(back - n).max() <= 1.0 / 65535.0 + 1e-12
    grey = np.arange(12, dtype=np.uint16).reshape(3, 4) * 5000
    passes_export.write_png16(tmp_path / "g.png", grey)
    assert np.array_equal(read_png16(tmp_path / "g.png"), grey)
    with pytest.raises(ValueError):
        passes_export.write_png16(tmp_path / "x.png", grey.astype(np.uint8))


# -- through the export -----------------------------------------------------------------------

def surface_normals(record: dict, i: int):
    """The scene-frame normal of the surface each pixel shows, from the same
    ray caster: up for the ground (and the sky), the entered face's outward
    normal for each box."""
    from tests import test_passes as scene

    pose = {"north": record["position_north_m"], "east": record["position_east_m"],
            "alt": record["position_alt_m"], "roll": record["roll_deg"],
            "pitch": record["pitch_deg"], "yaw": record["yaw_deg"]}
    origin, d = scene.pixel_rays(record, pose)
    with np.errstate(divide="ignore"):
        best = np.where(d[..., 2] < 0.0, -origin[2] / d[..., 2], np.inf)
    normals = np.zeros(d.shape)
    normals[..., 2] = 1.0
    for state, half in ((scene.primary_state(i), scene.PRIMARY_HALF),
                        (scene.traffic_state(i), scene.TRAFFIC_HALF)):
        forward, right, up = scene.dcm(state["roll_deg"], state["pitch_deg"], state["heading_deg"])
        axes = (forward, right, -up)
        cg = np.array([state["north_m"], state["east_m"], state["alt_m"]])
        los, his, dds = [], [], []
        for axis, h in zip(axes, half):
            o = float((origin - cg) @ axis)
            dd = d @ axis
            with np.errstate(divide="ignore", invalid="ignore"):
                t0, t1 = (-h - o) / dd, (h - o) / dd
            los.append(np.minimum(t0, t1))
            his.append(np.maximum(t0, t1))
            dds.append(dd)
        lo, hi = np.stack(los), np.stack(his)
        t_in, t_out = lo.max(axis=0), hi.min(axis=0)
        hit = (t_out >= t_in) & (t_in > 0.0) & (t_in < best)
        which = lo.argmax(axis=0)
        sign = -np.sign(np.take_along_axis(np.stack(dds), which[None], axis=0)[0])
        face = np.stack(axes)[which] * sign[..., None]
        normals[hit] = face[hit]
        best = np.where(hit, t_in, best)
    return normals


def _with_normals(run_dir: Path) -> None:
    """Every frame declares a normal image of the surfaces it shows."""
    manifest = load(run_dir)
    for camera_dir in (run_dir / "frames").iterdir():
        path = camera_dir / "render.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload["frame_records"]:
            frame = next(f for f in manifest["frames"] if f["camera_id"] == camera_dir.name
                         and Path(f["file"]).name == record["frame"])
            name = record["frame"].replace(".png", "_normal.png")
            producer.write_rgb16_png(camera_dir / name, producer.encode_normals(
                surface_normals(frame, int(frame["sample_index"]))))
            record["normal_png"] = name
        path.write_text(json.dumps(payload), encoding="utf-8")


def _verdict(run_dir: Path, drop=()) -> None:
    """verification.json from the verifier's own S2 checks (each must PASS
    here); ``drop`` leaves a check out, as a verifier without it would."""
    manifest = load(run_dir)
    checks = []
    for name in S2_CHECKS:
        if name in drop:
            continue
        check = getattr(verify, f"verify_{name}")(manifest, run_dir)
        assert check.status == verify.PASS, (name, check.detail)
        checks.append(check.to_dict())
    (run_dir / verify.VERIFICATION_FILE).write_text(json.dumps(
        {"ok": True, "passed": len(checks), "failed": 0, "not_run": 0, "checks": checks}),
        encoding="utf-8")


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    from core.dataset.export import export

    base = tmp_path_factory.mktemp("export")
    run_dir = build_run(base, "rig", baseline=5.0)
    _with_normals(run_dir)
    attach(run_dir)
    _verdict(run_dir)
    card = export([run_dir], base / "out", "kitti", labels_only=True,
                  fractions=(1.0, 0.0, 0.0))
    return run_dir, base / "out", card


def _key(run_dir: Path, camera: str, index: int) -> str:
    return f"{run_dir.name}_{camera}_{index:04d}"


def test_kitti_flow_and_disparity_read_back_what_the_passes_hold(exported):
    run_dir, out, _ = exported
    root = out / "train"
    manifest = load(run_dir)
    for record in (f for f in manifest["frames"] if f["camera_id"] == CAMERA):
        key = _key(run_dir, CAMERA, record["index"])
        document = json.loads((run_dir / "frames" / CAMERA / "passes.json").read_text(encoding="utf-8"))
        entry = next(e for e in document["frames"] if e["frame"] == Path(record["file"]).name)
        folder = run_dir / "frames" / CAMERA
        flow = np.fromfile(folder / entry["files"]["flow_fw"]["file"], dtype="<f4").reshape(64, 96, 2)
        bits = np.fromfile(folder / entry["files"]["flow_fw_valid"]["file"], dtype=np.uint8).reshape(64, 96)
        u, v, valid = kitti_flow_read(root / "flow_noc" / f"{key}.png")
        assert np.array_equal(valid, bits == 1)
        if valid.any():
            assert np.abs(u[valid] - flow[..., 0][valid]).max() <= 1.0 / 128.0 + 1e-6
            assert np.abs(v[valid] - flow[..., 1][valid]).max() <= 1.0 / 128.0 + 1e-6
        _, _, valid_occ = kitti_flow_read(root / "flow_occ" / f"{key}.png")
        assert np.array_equal(valid_occ, (bits == 1) | (bits == 2))
        assert (root / "backward_flow_noc" / f"{key}.png").is_file()
        d = np.fromfile(folder / entry["files"]["disparity"]["file"], dtype="<f4").reshape(64, 96)
        read, ok = kitti_disp_read(root / "disp_occ_0" / f"{key}.png")
        assert np.array_equal(ok, np.rint(d * 256.0) >= 1)
        assert np.abs(read[ok] - d[ok]).max() <= 1.0 / 512.0 + 1e-6


def test_kitti_velodyne_points_ids_calib_and_normals_read_back(exported):
    run_dir, out, _ = exported
    root = out / "train"
    folder = run_dir / "frames" / CAMERA
    document = json.loads((folder / "passes.json").read_text(encoding="utf-8"))
    entry = document["frames"][0]
    key = _key(run_dir, CAMERA, 0)
    camera_points = np.fromfile(folder / entry["files"]["points"]["file"], dtype="<f4").reshape(-1, 4)
    velo = velodyne_read(root / "velodyne" / f"{key}.bin")
    ids = np.fromfile(root / "velodyne_id" / f"{key}.bin", dtype=np.uint8)
    assert velo.shape == camera_points.shape and ids.size == velo.shape[0]
    assert np.array_equal(ids, np.fromfile(folder / entry["files"]["points_id"]["file"], dtype=np.uint8))
    calib = (root / "calib" / f"{key}.txt").read_text(encoding="utf-8")
    line = next(l for l in calib.splitlines() if l.startswith("Tr_velo_to_cam:"))
    matrix = np.array([float(x) for x in line.split(":")[1].split()]).reshape(3, 4)
    back = velo[:, :3].astype(np.float64) @ matrix[:, :3].T + matrix[:, 3]
    assert np.array_equal(back.astype(np.float32), camera_points[:, :3])
    assert np.all(velo[:, 3] == 0.0)                            # reflectance 0, stated
    source = read_png16(folder / "frame_0000_normal.png")
    assert np.array_equal(read_png16(root / "normals" / f"{key}.png"), source)
    decoded = source.astype(np.float64) / 65535.0 * 2.0 - 1.0
    raw = np.fromfile(root / "normals" / f"{key}.f32", dtype="<f4").reshape(64, 96, 3)
    assert np.abs(raw - decoded).max() <= 1e-6


def test_webdataset_carries_every_pass_file_byte_for_byte(exported, tmp_path):
    from core.dataset.export import assign_splits, collect_samples, export_webdataset, load_run

    run_dir, _, _ = exported
    samples = collect_samples([load_run(run_dir)], labels_only=True)
    export_webdataset(samples, tmp_path / "wds", assign_splits(samples, (1.0, 0.0, 0.0)))
    members = {}
    for shard in sorted((tmp_path / "wds" / "train").glob("*.tar")):
        with tarfile.open(shard) as tar:
            for member in tar.getmembers():
                members[member.name] = tar.extractfile(member).read()
    key = _key(run_dir, CAMERA, 1)
    folder = run_dir / "frames" / CAMERA
    for suffix in ("flow_fw.f32", "flow_fw_valid.u8", "flow_bw.f32", "flow_bw_valid.u8",
                   "disparity.f32", "points.f32", "points_id.u8", "normal.png"):
        source = folder / ("frame_0001_" + suffix)
        assert members[f"{key}.{suffix}"] == source.read_bytes(), suffix
    sidecar = json.loads(members[f"{key}.json"])
    assert sidecar["frame"]["passes"]["file"] == f"frames/{CAMERA}/passes.json"


def test_the_card_names_the_consumer_of_each_pass_and_what_shipped(exported):
    run_dir, out, card = exported
    block = card["passes"]
    assert set(block["consumers"]) == {"flow", "disparity", "points", "normals", "amodal"}
    for item in block["consumers"].values():
        assert item["consumer"] and item["encoding"] and item["not_claimed"]
    assert "flow_occ / flow_noc" in block["kitti_directories"]
    assert set(block["shipped"][run_dir.name]) >= {"flow_fw.f32", "disparity.f32", "points.f32",
                                                   "normal.png"}
    written = json.loads((out / "dataset.json").read_text(encoding="utf-8"))
    assert written["passes"]["consumers"]["points"]["consumer"].startswith("3-D detection")


def test_a_pass_file_the_verifier_did_not_grade_refuses_the_export_by_name(tmp_path):
    from core.dataset.export import ExportError, export

    run_dir = build_run(tmp_path, "unverified", words=("points",))
    attach(run_dir)
    manifest = load(run_dir)
    check = verify.verify_points_vs_depth(manifest, run_dir)
    assert check.status == verify.PASS
    (run_dir / verify.VERIFICATION_FILE).write_text(json.dumps(
        {"ok": True, "passed": 0, "failed": 0, "not_run": 0, "checks": []}), encoding="utf-8")
    with pytest.raises(ExportError) as err:
        export([run_dir], tmp_path / "out", "kitti", labels_only=True, fractions=(1.0, 0.0, 0.0))
    assert err.value.constraint == "export.unverified_labels"
    assert "points_vs_depth" in err.value.message
    (run_dir / verify.VERIFICATION_FILE).write_text(json.dumps(
        {"ok": True, "passed": 1, "failed": 0, "not_run": 0, "checks": [check.to_dict()]}),
        encoding="utf-8")
    card = export([run_dir], tmp_path / "out2", "kitti", labels_only=True, fractions=(1.0, 0.0, 0.0))
    assert (tmp_path / "out2" / "train" / "velodyne").is_dir()
    assert card["passes"]["shipped"][run_dir.name] == ["points.f32", "points_id.u8"]
