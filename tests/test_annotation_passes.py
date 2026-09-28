"""I6 (gap S3): the normal, motion-vector and albedo ground-truth passes,
measured here on synthetic bundles.

No engine runs in this container, so what is measured is the PYTHON half
against bundles painted by this file's own arithmetic:

* a depth image of a tilted plane through the record's pinhole and, beside
  it, the plane's exact normal encoded the way the commandlet encodes it
  -- ``normals_vs_depth`` passes; the same normals rotated 30 deg fail by
  name (annotation.normals); nothing to read -> NOT RUN;
* two frames of a box airframe translating in front of a fixed camera, the
  flow painted per pixel from where each visible surface point WAS in the
  previous frame -- ``flow_vs_motion`` passes; the flow scaled by 2 or
  negated fails by name (annotation.flow); a first frame that is not zeros
  fails; one frame -> NOT RUN;
* an albedo image beside a beauty frame -- unlike it passes; a copy of the
  beauty fails by name (annotation.albedo); absent -> NOT RUN;
* the readers round-trip what the writers wrote, bit for bit for the
  16-bit PNGs (rasterio; Pillow would hand them back as 8-bit);
* ``attach_engine_labels`` records which passes each frame declares and
  the ``render.passes`` AppliedVariable with its measured null test;
* the flags builder emits ``-passes=`` only when asked and leaves every
  list without it byte-identical.

What is NOT measured here: that an engine writes any of these files (the
commandlet is uncompiled off Windows; its source pins are in
tests/test_gate6_visual.py), the velocity's time base, sun invariance of
the albedo (Gate 6's clause, Windows only).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from core.capture import labels as producer
from core.capture import verify

WIDTH, HEIGHT = 320, 180
FX = FY = 400.0
CX, CY = 160.0, 90.0
CAMERA = "chase"
PRIMARY_ID = 1


# -- the synthetic run ---------------------------------------------------------

def _record(index: int, t_s: float, aircraft: dict) -> dict:
    """A manifest frame record: the camera at the scene origin looking
    north and level (identity quaternion: forward north, right east),
    the pinhole above, the aircraft state given."""
    return {
        "camera_id": CAMERA, "file": f"frames/{CAMERA}/frame_{index:04d}.png",
        "t_s": t_s, "width_px": WIDTH, "height_px": HEIGHT,
        "fx_px": FX, "fy_px": FY, "principal_point_px": [CX, CY],
        "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
        "position_north_m": 0.0, "position_east_m": 0.0, "position_alt_m": 0.0,
        "aircraft": aircraft,
        "labels": {"objects": [{"id": "aircraft:box:0", "int_id": PRIMARY_ID,
                                "class": "aircraft", "role": "primary"}]},
    }


def _aircraft(north: float, east: float, alt: float) -> dict:
    return {"north_m": north, "east_m": east, "alt_m": alt,
            "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}


#: The box airframe: half extents forward / right / down, and keypoints on
#: its faces (body metres about the CG, x forward, y right, z down).
HALF = (35.0, 30.0, 5.0)
KEYPOINTS = {"nose": (35.0, 0.0, 0.0), "tail": (-35.0, 0.0, 0.0),
             "wing_left": (0.0, -30.0, 0.0), "wing_right": (0.0, 30.0, 0.0),
             "belly": (0.0, 0.0, 4.0)}


def _manifest(records) -> dict:
    return {
        "manifest_version": 6, "spec_digest": "synthetic",
        "objects": [{"id": "aircraft:box:0", "int_id": PRIMARY_ID, "class": "aircraft",
                     "role": "primary", "labelled": True, "in_scene": True}],
        "airframe": {"keypoints": [{"name": n, "body_m": list(b)}
                                   for n, b in KEYPOINTS.items()]},
        "frames": list(records),
    }


def _rays():
    """Camera-frame ray directions through every pixel CENTRE (x right,
    y down, z forward = 1), and the same in the scene frame (north,
    east, up) for the identity camera."""
    u = (np.arange(WIDTH, dtype=np.float64) + 0.5)[None, :]
    v = (np.arange(HEIGHT, dtype=np.float64) + 0.5)[:, None]
    x = np.broadcast_to((u - CX) / FX, (HEIGHT, WIDTH))
    y = np.broadcast_to((v - CY) / FY, (HEIGHT, WIDTH))
    z = np.ones((HEIGHT, WIDTH))
    # identity camera: east = x, up = -y, north = z
    return x, y, z, np.stack([z, x, -y], axis=2)


def _write_bundle(run_dir: Path, frames: list, root_passes=None) -> Path:
    """frames: [(index, files dict, extra record keys)]; writes render.json
    and the manifest. ``files`` maps 'mask' / 'depth_f32' to names."""
    camera_dir = run_dir / "frames" / CAMERA
    camera_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, files, extra in frames:
        record = {"frame": f"frame_{index:04d}.png",
                  "labels": {"mask": files["mask"], "depth_f32": files["depth_f32"],
                             "objects": []}}
        record.update(extra)
        records.append(record)
    payload = {"host": "unreal", "frame_records": records}
    if root_passes:
        payload["passes"] = root_passes
    (camera_dir / "render.json").write_text(json.dumps(payload), encoding="utf-8")
    return camera_dir


def _write_mask_and_depth(camera_dir: Path, index: int, mask, depth) -> dict:
    from PIL import Image

    mask_name = f"frame_{index:04d}_mask.png"
    depth_name = f"frame_{index:04d}_depth.f32"
    Image.fromarray(mask.astype(np.uint8), mode="L").save(camera_dir / mask_name)
    depth.astype("<f4").tofile(camera_dir / depth_name)
    return {"mask": mask_name, "depth_f32": depth_name}


def _write_beauty(camera_dir: Path, index: int, rgb8) -> str:
    from PIL import Image

    name = f"frame_{index:04d}.png"
    Image.fromarray(rgb8.astype(np.uint8), mode="RGB").save(camera_dir / name)
    return name


# -- normals: a tilted plane -------------------------------------------------------

#: Tilted so the plane RISES going north (its horizon sits above the
#: image top): every pixel-centre ray meets it, at 20 m below the camera.
PLANE_NORMAL = np.array([-0.3, 0.1, 1.0]) / np.linalg.norm([-0.3, 0.1, 1.0])   # north, east, up
PLANE_POINT = np.array([0.0, 0.0, -20.0])


def plane_depth():
    """z_cam (= t, the ray's z is 1) where each pixel-centre ray meets the
    plane; +inf where it does not (the sky)."""
    _, _, _, d = _rays()
    denominator = d @ PLANE_NORMAL
    numerator = float(PLANE_NORMAL @ PLANE_POINT)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = numerator / denominator
    depth = np.where((denominator < 0) & (t > 0), t, np.inf)
    return depth


def _rotate_about_east(n, degrees: float):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    north, east, up = n
    return np.array([c * north - s * up, east, s * north + c * up])


def normals_run(tmp_path: Path, normal_world, declare=True) -> Path:
    run_dir = tmp_path / "normals"
    camera_dir = run_dir / "frames" / CAMERA
    camera_dir.mkdir(parents=True)
    depth = plane_depth()
    files = _write_mask_and_depth(camera_dir, 0, np.zeros(depth.shape), depth)
    extra = {}
    if declare:
        image = np.broadcast_to(np.asarray(normal_world), (HEIGHT, WIDTH, 3))
        producer.write_rgb16_png(camera_dir / "frame_0000_normal.png",
                                 producer.encode_normals(image))
        extra["normal_png"] = "frame_0000_normal.png"
    _write_bundle(run_dir, [(0, files, extra)])
    manifest = _manifest([_record(0, 0.0, _aircraft(600.0, 0.0, 0.0))])
    (run_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def test_the_planes_exact_normals_pass_normals_vs_depth(tmp_path):
    run_dir = normals_run(tmp_path, PLANE_NORMAL)
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    check = verify.verify_normals_vs_depth(manifest, run_dir)
    assert check.status == verify.PASS, check.detail
    median = float(check.detail.split("median of at most ")[1].split(" deg")[0])
    assert median < 0.5, check.detail            # measured: 0.01 deg on the plane


def test_normals_rotated_30_deg_fail_by_name(tmp_path):
    run_dir = normals_run(tmp_path, _rotate_about_east(PLANE_NORMAL, 30.0))
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    check = verify.verify_normals_vs_depth(manifest, run_dir)
    assert check.status == verify.FAIL
    assert check.failure == "annotation.normals"
    assert "30." in check.detail or "29." in check.detail, check.detail


def test_normals_rotated_by_less_than_the_tolerance_still_pass(tmp_path):
    """The threshold is a threshold: 5 deg off passes, so the 30 deg
    failure above is the tolerance refusing, not any rotation."""
    run_dir = normals_run(tmp_path, _rotate_about_east(PLANE_NORMAL, 5.0))
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    check = verify.verify_normals_vs_depth(manifest, run_dir)
    assert check.status == verify.PASS, check.detail


def test_normals_are_not_run_without_the_file(tmp_path):
    run_dir = normals_run(tmp_path, PLANE_NORMAL, declare=False)
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    check = verify.verify_normals_vs_depth(manifest, run_dir)
    assert check.status == verify.NOT_RUN and "normal_png" in check.detail


def test_a_declared_normal_image_that_is_missing_fails_files(tmp_path):
    run_dir = normals_run(tmp_path, PLANE_NORMAL)
    (run_dir / "frames" / CAMERA / "frame_0000_normal.png").unlink()
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    check = verify.verify_normals_vs_depth(manifest, run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.files"


# -- flow: a translating box -----------------------------------------------------------

CG0 = np.array([600.0, 0.0, 0.0])
CG1 = np.array([600.0, 6.0, 2.0])


def _box_hits(cg):
    """Per pixel: the ray parameter t of the first hit on the axis-aligned
    box about ``cg`` (half extents HALF in north/east/up), or +inf."""
    _, _, _, d = _rays()
    lo = cg - np.array([HALF[0], HALF[1], HALF[2]])
    hi = cg + np.array([HALF[0], HALF[1], HALF[2]])
    t_near = np.full((HEIGHT, WIDTH), -np.inf)
    t_far = np.full((HEIGHT, WIDTH), np.inf)
    for axis in range(3):
        with np.errstate(divide="ignore", invalid="ignore"):
            t1 = lo[axis] / d[:, :, axis]
            t2 = hi[axis] / d[:, :, axis]
        t_near = np.maximum(t_near, np.minimum(t1, t2))
        t_far = np.minimum(t_far, np.maximum(t1, t2))
    hit = (t_near <= t_far) & (t_near > 0)
    return np.where(hit, t_near, np.inf), d


def _project(point):
    """Scene (north, east, up) -> (u, v) through the identity camera."""
    north, east, up = point
    return CX + FX * east / north, CY + FY * (-up) / north


def flow_field():
    """The flow at frame 1 per pixel: where the surface point seen at the
    pixel centre projected in frame 0, subtracted from the centre. Zero
    off the box (nothing else is in the scene)."""
    t, d = _box_hits(CG1)
    flow = np.zeros((HEIGHT, WIDTH, 2), dtype=np.float32)
    hit = np.isfinite(t)
    for py, px in zip(*np.nonzero(hit)):
        surface = t[py, px] * d[py, px]
        previous = surface - CG1 + CG0            # pure translation
        u0, v0 = _project(previous)
        flow[py, px] = (px + 0.5 - u0, py + 0.5 - v0)
    return flow, hit, t


def flow_run(tmp_path: Path, scale: float = 1.0, first_frame_zeros=True,
             frames: int = 2) -> Path:
    run_dir = tmp_path / f"flow_{scale}_{first_frame_zeros}_{frames}"
    camera_dir = run_dir / "frames" / CAMERA
    camera_dir.mkdir(parents=True)
    bundle = []
    records = []
    t0, _ = _box_hits(CG0)
    files = _write_mask_and_depth(camera_dir, 0, np.isfinite(t0) * PRIMARY_ID,
                                  np.where(np.isfinite(t0), t0, np.inf))
    zeros = np.zeros((HEIGHT, WIDTH, 2), dtype=np.float32)
    if not first_frame_zeros:
        zeros[0, 0] = (1.0, 0.0)
    zeros.astype("<f4").tofile(camera_dir / "frame_0000_flow.f32")
    bundle.append((0, files, {"flow_f32": "frame_0000_flow.f32", "flow_first_frame": True}))
    records.append(_record(0, 0.0, _aircraft(*CG0)))
    if frames > 1:
        flow, hit, t1 = flow_field()
        files = _write_mask_and_depth(camera_dir, 1, hit * PRIMARY_ID,
                                      np.where(hit, t1, np.inf))
        (flow * scale).astype("<f4").tofile(camera_dir / "frame_0001_flow.f32")
        bundle.append((1, files, {"flow_f32": "frame_0001_flow.f32",
                                  "flow_first_frame": False}))
        records.append(_record(1, 0.2, _aircraft(*CG1)))
    _write_bundle(run_dir, bundle)
    (run_dir / "capture_manifest.json").write_text(json.dumps(_manifest(records)),
                                                   encoding="utf-8")
    return run_dir


def _check_flow(run_dir):
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    return verify.verify_flow_vs_motion(manifest, run_dir)


def test_the_painted_box_has_pixels_and_motion():
    flow, hit, _ = flow_field()
    assert hit.sum() > 200            # measured: 294 px (42 x 7) at 600 m
    magnitude = np.hypot(flow[hit, 0], flow[hit, 1])
    assert magnitude.min() > 3.0 and magnitude.max() < 6.0     # measured 4.2..4.6 px


def test_a_flow_consistent_with_the_keypoints_motion_passes(tmp_path):
    check = _check_flow(flow_run(tmp_path))
    assert check.status == verify.PASS, check.detail
    median = float(check.detail.split("median ")[1].split(" px")[0])
    assert median < 0.6, check.detail            # measured: parallax of an occluded nose


def test_a_flow_scaled_by_two_fails_by_name(tmp_path):
    check = _check_flow(flow_run(tmp_path, scale=2.0))
    assert check.status == verify.FAIL and check.failure == "annotation.flow"


def test_a_negated_flow_fails_by_name(tmp_path):
    check = _check_flow(flow_run(tmp_path, scale=-1.0))
    assert check.status == verify.FAIL and check.failure == "annotation.flow"


def test_a_first_frame_that_is_not_zeros_fails(tmp_path):
    check = _check_flow(flow_run(tmp_path, first_frame_zeros=False))
    assert check.status == verify.FAIL and check.failure == "annotation.flow"
    assert "first frame" in check.detail


def test_flow_is_not_run_with_one_frame(tmp_path):
    check = _check_flow(flow_run(tmp_path, frames=1))
    assert check.status == verify.NOT_RUN and "second" in check.detail


def test_flow_is_not_run_without_a_flow_file(tmp_path):
    run_dir = normals_run(tmp_path, PLANE_NORMAL)
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    check = verify.verify_flow_vs_motion(manifest, run_dir)
    assert check.status == verify.NOT_RUN and "flow_f32" in check.detail


def test_a_truncated_flow_file_fails_by_name(tmp_path):
    run_dir = flow_run(tmp_path)
    path = run_dir / "frames" / CAMERA / "frame_0001_flow.f32"
    path.write_bytes(path.read_bytes()[:-8])
    check = _check_flow(run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.flow"


# -- albedo ------------------------------------------------------------------------

def albedo_run(tmp_path: Path, kind: str) -> Path:
    run_dir = tmp_path / f"albedo_{kind}"
    camera_dir = run_dir / "frames" / CAMERA
    camera_dir.mkdir(parents=True)
    rng = np.random.default_rng(6)
    beauty = rng.integers(0, 256, (HEIGHT, WIDTH, 3))
    name = _write_beauty(camera_dir, 0, beauty)
    # The box's depth: sky everywhere else, so the sky note is exercised.
    t0, _ = _box_hits(CG0)
    files = _write_mask_and_depth(camera_dir, 0, np.isfinite(t0) * PRIMARY_ID,
                                  np.where(np.isfinite(t0), t0, np.inf))
    extra = {"frame": name}
    if kind == "identical":
        albedo = np.rint(beauty / 255.0 * 65535).astype(np.uint16)
    elif kind == "flat":
        albedo = np.full((HEIGHT, WIDTH, 3), 20000, dtype=np.uint16)
    else:
        albedo = None
    if albedo is not None:
        producer.write_rgb16_png(camera_dir / "frame_0000_albedo.png", albedo)
        extra["albedo_png"] = "frame_0000_albedo.png"
    _write_bundle(run_dir, [(0, files, extra)])
    manifest = _manifest([_record(0, 0.0, _aircraft(600.0, 0.0, 0.0))])
    (run_dir / "capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def _check_albedo(run_dir):
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    return verify.verify_albedo_range(manifest, run_dir)


def test_an_albedo_unlike_the_beauty_passes_and_reports_the_sky(tmp_path):
    check = _check_albedo(albedo_run(tmp_path, "flat"))
    assert check.status == verify.PASS, check.detail
    assert "sky pixels" in check.detail


def test_an_albedo_that_is_the_beauty_picture_fails_by_name(tmp_path):
    check = _check_albedo(albedo_run(tmp_path, "identical"))
    assert check.status == verify.FAIL and check.failure == "annotation.albedo"


def test_albedo_is_not_run_without_the_file(tmp_path):
    check = _check_albedo(albedo_run(tmp_path, "absent"))
    assert check.status == verify.NOT_RUN and "albedo_png" in check.detail


def test_an_8_bit_albedo_is_refused(tmp_path):
    from PIL import Image

    run_dir = albedo_run(tmp_path, "flat")
    path = run_dir / "frames" / CAMERA / "frame_0000_albedo.png"
    Image.fromarray(np.full((HEIGHT, WIDTH, 3), 77, dtype=np.uint8), mode="RGB").save(path)
    check = _check_albedo(run_dir)
    assert check.status == verify.FAIL and check.failure == "annotation.albedo"
    assert "16-bit" in check.detail


# -- the readers -------------------------------------------------------------------

def test_rgb16_png_round_trips_bit_for_bit(tmp_path):
    rng = np.random.default_rng(1)
    image = rng.integers(0, 65536, (HEIGHT, WIDTH, 3)).astype(np.uint16)
    path = producer.write_rgb16_png(tmp_path / "a.png", image)
    back = producer.read_rgb16_png(path)
    assert back.dtype == np.uint16 and np.array_equal(back, image)


def test_pillow_would_have_lost_the_low_byte(tmp_path):
    """The measured reason the readers go through rasterio: Pillow opens
    a 16-bit RGB PNG as 8-bit."""
    from PIL import Image

    image = np.full((4, 4, 3), 0x1234, dtype=np.uint16)
    path = producer.write_rgb16_png(tmp_path / "a.png", image)
    with Image.open(path) as opened:
        assert np.asarray(opened).dtype == np.uint8
    assert producer.read_rgb16_png(path)[0, 0, 0] == 0x1234


def test_normals_round_trip_within_one_count(tmp_path):
    rng = np.random.default_rng(2)
    normals = rng.normal(size=(HEIGHT, WIDTH, 3))
    normals /= np.linalg.norm(normals, axis=2, keepdims=True)
    path = producer.write_rgb16_png(tmp_path / "n.png", producer.encode_normals(normals))
    back = producer.read_normal_png(path)
    assert np.abs(back - normals).max() <= 2.0 / 65535 + 1e-6


def test_the_normal_encoding_is_the_stated_offset():
    assert producer.encode_normals(np.zeros((1, 1, 3)))[0, 0, 0] == 32768
    assert producer.encode_normals(np.ones((1, 1, 3)))[0, 0, 0] == 65535
    assert producer.encode_normals(-np.ones((1, 1, 3)))[0, 0, 0] == 0
    assert producer.read_normal_png.__doc__ and "2 - 1" in producer.read_normal_png.__doc__


def test_flow_round_trips_and_refuses_a_wrong_size(tmp_path):
    flow = np.random.default_rng(3).normal(size=(HEIGHT, WIDTH, 2)).astype(np.float32)
    path = tmp_path / "f.f32"
    flow.astype("<f4").tofile(path)
    assert np.array_equal(producer.read_flow_f32(path, WIDTH, HEIGHT), flow)
    with pytest.raises(ValueError, match="float32 values"):
        producer.read_flow_f32(path, WIDTH, HEIGHT - 1)


def test_albedo_reads_as_unit_range(tmp_path):
    image = np.array([[[0, 32768, 65535]]], dtype=np.uint16)
    path = producer.write_rgb16_png(tmp_path / "a.png", image)
    assert producer.read_albedo_png(path).tolist() == [[[0.0, pytest.approx(0.5, abs=1e-4), 1.0]]]


def test_a_two_channel_png_is_refused(tmp_path):
    from PIL import Image

    path = tmp_path / "g.png"
    Image.fromarray(np.zeros((4, 4), dtype=np.uint16), mode="I;16").save(path)
    with pytest.raises(ValueError, match="channel"):
        producer.read_rgb16_png(path)


# -- attach: which passes exist per frame, and the record --------------------------

def test_attach_records_the_passes_and_the_applied_variable(tmp_path):
    run_dir = flow_run(tmp_path)
    # Declare a normal and an albedo on frame 1 only (names, not files:
    # attach opens neither).
    render = run_dir / "frames" / CAMERA / "render.json"
    payload = json.loads(render.read_text(encoding="utf-8"))
    payload["frame_records"][1]["normal_png"] = "frame_0001_normal.png"
    payload["frame_records"][1]["albedo_png"] = "frame_0001_albedo.png"
    render.write_text(json.dumps(payload), encoding="utf-8")
    summary = producer.attach_engine_labels(run_dir)
    assert summary["attached"] == 2 and summary["passes"] == ["albedo", "normal", "velocity"]
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["frames"][0]["labels"]["passes"] == {
        "normal": None, "velocity": "frame_0000_flow.f32", "albedo": None}
    assert manifest["frames"][1]["labels"]["passes"] == {
        "normal": "frame_0001_normal.png", "velocity": "frame_0001_flow.f32",
        "albedo": "frame_0001_albedo.png"}
    from core.records import read_records
    records = read_records(manifest["applied_variables"])
    assert [r["name"] for r in records] == ["render.passes"]
    record = records[0]
    assert record["value"] == ["normal", "velocity", "albedo"]
    assert record["source"] == "user"
    null = record["null_test"]
    assert null["with"] == 2.0 and null["without"] == 0.0 and null["ok"]
    assert record["parameters"]["frames_with_passes"] == 2
    assert "engine execution" in " ".join(record["not_claimed"])
    # A second attach replaces the record instead of doubling it.
    producer.attach_engine_labels(run_dir)
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in manifest["applied_variables"]["applied_variables"]] == ["render.passes"]


def test_attach_without_passes_records_none_and_no_variable(tmp_path):
    run_dir = normals_run(tmp_path, PLANE_NORMAL, declare=False)
    summary = producer.attach_engine_labels(run_dir)
    assert summary["attached"] == 1 and "passes" not in summary
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["frames"][0]["labels"]["passes"] == {
        "normal": None, "velocity": None, "albedo": None}
    assert "applied_variables" not in manifest


# -- the flags builder ----------------------------------------------------------------

def _flags(**kw):
    from core.render.flags import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH, render_flags
    return render_flags(Path("/c/card.json"), Path("/c/frames"),
                        scene={"terrain": "ridge"}, mesh=Path("/c/mesh.json"), look=None,
                        camera_flags=None, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
                        fps=DEFAULT_FPS, **kw)


def test_the_builder_emits_passes_only_when_asked_and_in_order():
    from core.render.flags import PASS_NAMES, passes_flag
    assert PASS_NAMES == ("normal", "velocity", "albedo")
    without = _flags()
    assert without == _flags(passes=()) == _flags(passes=[])
    assert not [t for t in without if t.startswith("-passes")]
    with_all = _flags(passes=["albedo", "normal", "velocity", "normal"])
    assert [t for t in with_all if t.startswith("-passes")] == ["-passes=normal,velocity,albedo"]
    assert [t for t in with_all if not t.startswith("-passes")] == without
    assert with_all.index("-passes=normal,velocity,albedo") > with_all.index("-deterministic")
    assert with_all.index("-passes=normal,velocity,albedo") < with_all.index("-GeorefTerrain")
    assert passes_flag(["velocity"]) == "-passes=velocity" and passes_flag([]) is None
    with pytest.raises(ValueError, match="unknown render pass"):
        _flags(passes=["normals"])


def test_the_default_list_is_byte_identical_to_the_pre_passes_builder():
    """The exact list the builder made before ``passes`` existed, for the
    CLI's call shape (labels and deterministic on, terrain, mesh)."""
    from core.render.flags import DEFAULT_LOOK
    assert _flags() == [
        "-scenario=/c/card.json", "-frames=/c/frames", "-Visual", "-shot=showcase",
        "-fps=30", "-width=1280", "-height=720",
        f"-sun-elev={DEFAULT_LOOK['sun_elev']}", f"-sun-azim={DEFAULT_LOOK['sun_azim']}",
        f"-exposure-bias={DEFAULT_LOOK['exposure_bias']}",
        f"-fog-density={DEFAULT_LOOK['fog_density']}",
        "-unattended", "-nopause", "-nosplash", "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
        "-labels", "-deterministic", "-GeorefTerrain", "-terrain=ridge", "-mesh=/c/mesh.json",
    ]


def test_the_wrapper_forwards_the_passes_flag():
    from core.render.flags import for_wrapper
    assert "-passes=albedo" in for_wrapper(_flags(passes=["albedo"]))


# -- verify_run carries the three checks ----------------------------------------------

def test_verify_run_lists_the_three_checks_as_not_run_on_a_bare_manifest(tmp_path):
    from core.capture.verify import verify_run
    run_dir = tmp_path / "bare"
    run_dir.mkdir()
    (run_dir / "capture_manifest.json").write_text(json.dumps(_manifest([])), encoding="utf-8")
    report = verify_run(run_dir)
    by_name = {c.name: c for c in report.checks}
    for name in ("normals_vs_depth", "flow_vs_motion", "albedo_range"):
        assert by_name[name].status == verify.NOT_RUN, by_name[name]
