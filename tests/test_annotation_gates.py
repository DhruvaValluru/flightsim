"""The annotation gates (Phase 2, package D; contracts §4) against a
fabricated ground-truth bundle, and each brainstorm §3.6 mutation
failing the named check.

The run is a real manifest-6 solve over synthetic telemetry (a 747 with
an A320 crossing 400 m ahead; a long chase station and the wingman
slot) -- the producer's manifest, as every verifier test uses. The
BUNDLE is painted here, by the test's own arithmetic and nothing of the
producer's or the verifier's: the camera axes from the record's Euler
angles as three elementary rotations, the aircraft's box from the
airframe block placed by its recorded state, a ray through every pixel
centre through the recorded pinhole, the slab test against each box, a
z-buffer over the boxes and the ground plane. The ID image, the class
image, the float depth, the alone passes and render.json come out of
that and nothing else; ``attach_engine_labels`` then fills the record
as it would after a render. A consistency test pins the painted primary
against the producer's own bbox_2d so the arithmetic is shown to agree
before anything is graded against it.

The airframes are boxes here, so the hull IS the silhouette and the
tolerances are exercised only by the mutations. What a real render's
silhouette does inside the contract's tolerances is not measured in
this container (no engine): see the report section.

Each mutation below is applied to a copy of the clean run:

    mutation                              fails by name
    ----------------------------------    -------------------------
    mesh origin shifted 3 m (body x)      annotation.mask_offset
    two ids swapped (engine echo)         annotation.identity
    two ids swapped (pixels only)         annotation.mask_offset
    ID image blurred (blended values)     annotation.mask_blend
    an undeclared stencil value           annotation.mask_blend
    engine counted non-integer ids        annotation.mask_blend
    depth scaled 1.02                     annotation.depth_range
    the occluder hidden in the full pass  annotation.visibility
    FOV off by 1 deg                      annotation.intrinsics
    a declared alone pass missing         annotation.files

The mutation guards in scripts/mutation_check.sh disable each clause in
turn and confirm the matching test here goes red.
"""

from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.capture.labels import attach_engine_labels
from core.capture.manifest import (
    build_capture_manifest, read_capture_manifest, write_capture_manifest,
    write_frame_sidecars,
)
from core.capture.objects import compose_objects
from core.capture.poses import solve_pose_track, solve_traffic_track, traffic_state
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, NOT_RUN, PASS, Check, verify_applied_intrinsics, verify_box_vs_mask,
    verify_depth_range, verify_depth_vs_geometry, verify_identity_stable,
    verify_label_files, verify_mask_containment, verify_mask_integers_only,
    verify_mask_vs_geometry, verify_run, verify_visibility_vs_scene,
    write_verification,
)
from core.nl.compiler import compile_prompt
from core.scenario.blocks import TrafficSpec
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns

ANNOTATION_CHECKS = ("mask_integers_only", "mask_vs_geometry", "box_vs_mask",
                     "depth_vs_geometry", "visibility_vs_scene",
                     "identity_stable", "applied_intrinsics")

#: The chase station: 600 m behind, so that a 2 % depth scale (12 m at
#: the tail) exceeds the verifier's 1 % + 2 m; the default 110 m station
#: would put a 2 % scale inside the tolerance (stated on the check).
CHASE_STATION = (-600.0, 0.0, 12.0)
TRAFFIC_RANGE_M = 400.0
DEPTH_SCALE_M = 0.1
DEPTH_SATURATION_M = 6553.5


# -- the spec and its manifest (the producer's) --------------------------------

def fabricated_spec():
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.traffic = [TrafficSpec.defaulted("A320", "crossing")]
    spec.traffic[0].set("range_m", TRAFFIC_RANGE_M, frm="test: the crossing range")
    chase = CameraSpec.defaulted(camera_id="chase0", preset="chase", aircraft="B747")
    for name, value in zip(("offset_forward_m", "offset_right_m", "offset_up_m"),
                           CHASE_STATION):
        chase.set(name, value, frm="test: a long chase station")
    chase.set("capture_count", 3, frm="test")
    wing = CameraSpec.defaulted(camera_id="wing0", preset="wingman", aircraft="B747")
    wing.set("capture_count", 3, frm="test")
    spec.cameras = [chase, wing]
    return spec


def fabricated_manifest(spec):
    columns = make_columns(duration_s=12.0)
    objects = compose_objects(spec)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    traffic = [o for o in objects if o.role == "traffic"]
    traffic_tracks = [
        solve_traffic_track(columns, str(e.track.value), float(e.range_m.value),
                            FRAME, o.id)
        for e, o in zip(spec.traffic, traffic)]
    manifest = build_capture_manifest(
        spec, columns, FRAME, tracks, schedules, output_digest="0" * 64,
        scene={"key": "flat", "terrain": None}, traffic_tracks=traffic_tracks)
    return manifest, traffic_tracks


# -- the test's own geometry: three rotations, a pinhole, a slab test ---------

def _rotation_body_to_ned(roll_deg, pitch_deg, yaw_deg):
    """Body -> NED as the product of the three elementary rotations:
    yaw about down, then pitch about the new right, then roll about the
    new forward. Columns are the body axes in NED."""
    r, p, y = (math.radians(roll_deg), math.radians(pitch_deg), math.radians(yaw_deg))
    rz = np.array([[math.cos(y), -math.sin(y), 0.0],
                   [math.sin(y), math.cos(y), 0.0],
                   [0.0, 0.0, 1.0]])
    ry = np.array([[math.cos(p), 0.0, math.sin(p)],
                   [0.0, 1.0, 0.0],
                   [-math.sin(p), 0.0, math.cos(p)]])
    rx = np.array([[1.0, 0.0, 0.0],
                   [0.0, math.cos(r), -math.sin(r)],
                   [0.0, math.sin(r), math.cos(r)]])
    return rz @ ry @ rx


def axes_enu(roll_deg, pitch_deg, yaw_deg):
    """(forward, right, up) unit vectors in (north, east, up)."""
    R = _rotation_body_to_ned(roll_deg, pitch_deg, yaw_deg)
    forward = np.array([R[0, 0], R[1, 0], -R[2, 0]])
    right = np.array([R[0, 1], R[1, 1], -R[2, 1]])
    down = np.array([R[0, 2], R[1, 2], -R[2, 2]])
    return forward, right, -down


def box_in_world(state, box_body, offset_body=(0.0, 0.0, 0.0)):
    """An airframe's extents box placed by its state: centre (ENU), the
    three box axes (forward, right, down in ENU), the half extents.
    ``offset_body`` moves the DRAWN box in the body frame (the
    mesh-origin mutation) while the state -- the label -- stays."""
    forward, right, up = axes_enu(state["roll_deg"], state["pitch_deg"],
                                  state["heading_deg"])
    cg = np.array([state["north_m"], state["east_m"], state["alt_m"]], dtype=float)
    lo = np.array([box_body["forward"][0], box_body["right"][0], box_body["down"][0]])
    hi = np.array([box_body["forward"][1], box_body["right"][1], box_body["down"][1]])
    centre_body = (lo + hi) / 2.0 + np.asarray(offset_body, dtype=float)
    down = -up
    centre = cg + centre_body[0] * forward + centre_body[1] * right + centre_body[2] * down
    return centre, (forward, right, down), (hi - lo) / 2.0


def pixel_rays(record):
    """Per pixel centre: the ray direction in ENU per unit camera depth."""
    w, h = int(record["width_px"]), int(record["height_px"])
    cx, cy = record["principal_point_px"]
    xs, ys = np.meshgrid(np.arange(w), np.arange(h))
    a = (xs + 0.5 - cx) / float(record["fx_px"])
    b = (ys + 0.5 - cy) / float(record["fy_px"])
    forward, right, up = axes_enu(record["roll_deg"], record["pitch_deg"],
                                  record["yaw_deg"])
    # x_cam right, y_cam DOWN, z_cam forward: a ray at (a, b, 1).
    d = (forward[None, None, :] + a[..., None] * right[None, None, :]
         - b[..., None] * up[None, None, :])
    return d


def box_depth(record, rays, centre, axes, half):
    """Camera depth at which each pixel's ray enters the box (inf where
    it misses): the slab test in the box's own frame."""
    cam = np.array([record["position_north_m"], record["position_east_m"],
                    record["position_alt_m"]], dtype=float)
    o = cam - centre
    t_enter = np.full(rays.shape[:2], -np.inf)
    t_exit = np.full(rays.shape[:2], np.inf)
    hit = np.ones(rays.shape[:2], dtype=bool)
    for axis, extent in zip(axes, half):
        oi = float(np.dot(axis, o))
        di = rays @ axis
        parallel = np.abs(di) < 1e-12
        with np.errstate(divide="ignore", invalid="ignore"):
            t0 = (-extent - oi) / di
            t1 = (extent - oi) / di
        lo, hi = np.minimum(t0, t1), np.maximum(t0, t1)
        lo = np.where(parallel, -np.inf, lo)
        hi = np.where(parallel, np.inf, hi)
        hit &= ~(parallel & (abs(oi) > extent))
        t_enter = np.maximum(t_enter, lo)
        t_exit = np.minimum(t_exit, hi)
    hit &= (t_exit >= t_enter) & (t_exit > 0.0)
    return np.where(hit, np.maximum(t_enter, 0.0), np.inf)


def ground_depth(record, rays, terrain_alt_m=0.0):
    du = rays[..., 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (terrain_alt_m - float(record["position_alt_m"])) / du
    return np.where((du < 0.0) & (t > 0.0), t, np.inf)


# -- the bundle, painted and declared ----------------------------------------

def _pinhole(record, point):
    forward, right, up = axes_enu(record["roll_deg"], record["pitch_deg"],
                                  record["yaw_deg"])
    d = np.asarray(point, dtype=float) - np.array(
        [record["position_north_m"], record["position_east_m"],
         record["position_alt_m"]])
    z = float(np.dot(forward, d))
    cx, cy = record["principal_point_px"]
    return (cx + record["fx_px"] * float(np.dot(right, d)) / z,
            cy - record["fy_px"] * float(np.dot(up, d)) / z, z)


def fabricate_run(run_dir, offset_body=(0.0, 0.0, 0.0), attach=True):
    """Write a complete manifest-6 run with its bundle under ``run_dir``.

    ``offset_body`` draws the PRIMARY's box that far from its label in
    its own body frame (the mesh-origin mutation). Returns the manifest
    as written (after attach_engine_labels when ``attach``)."""
    run_dir = Path(run_dir)
    spec = fabricated_spec()
    manifest, traffic_tracks = fabricated_manifest(spec)
    write_capture_manifest(manifest, run_dir)
    write_frame_sidecars(manifest, run_dir)
    objects = manifest["objects"]
    by_id = {o["id"]: o for o in objects}
    primary = next(o for o in objects if o["role"] == "primary")
    terrain = by_id["terrain"]
    traffic = [(o, manifest["traffic"][i]["airframe"]["box_body_m"], traffic_tracks[i])
               for i, o in enumerate(o for o in objects if o["role"] == "traffic")]
    per_camera = {}
    for record in manifest["frames"]:
        camera = record["camera_id"]
        folder = run_dir / "frames" / camera
        folder.mkdir(parents=True, exist_ok=True)
        name = Path(record["file"]).name
        stem = name[:-4]
        w, h = int(record["width_px"]), int(record["height_px"])
        rays = pixel_rays(record)
        # Each aircraft box: (int_id, class_id, depth image alone).
        drawn = []
        centre, axes, half = box_in_world(record["aircraft"],
                                          manifest["airframe"]["box_body_m"],
                                          offset_body)
        drawn.append((primary, box_depth(record, rays, centre, axes, half)))
        for obj, box_body, track in traffic:
            state = traffic_state(track, int(record["sample_index"]))
            centre, axes, half = box_in_world(state, box_body)
            drawn.append((obj, box_depth(record, rays, centre, axes, half)))
        depth = ground_depth(record, rays)
        ids = np.where(np.isfinite(depth), terrain["int_id"], 0).astype(np.uint8)
        classes = np.where(np.isfinite(depth), terrain["class_id"], 0).astype(np.uint8)
        for obj, own in drawn:
            nearer = own < depth
            depth = np.where(nearer, own, depth)
            ids = np.where(nearer, obj["int_id"], ids).astype(np.uint8)
            classes = np.where(nearer, obj["class_id"], classes).astype(np.uint8)
        Image.fromarray(ids, mode="L").save(folder / f"{stem}_mask.png")
        Image.fromarray(classes, mode="L").save(folder / f"{stem}_class.png")
        depth.astype("<f4").tofile(folder / f"{stem}_depth.f32")
        png = np.where(np.isfinite(depth),
                       np.minimum(depth / DEPTH_SCALE_M, 65535.0), 65535.0)
        Image.fromarray(png.astype(np.uint16), mode="I;16").save(folder / f"{stem}_depth.png")
        declared = []
        for obj in objects:
            entry = {"int_id": obj["int_id"], "pixels": int(np.count_nonzero(ids == obj["int_id"])),
                     "pixels_alone": None, "alone_png": None, "visible_fraction": None,
                     "occluded_by": [], "depth_min_m": None, "depth_median_m": None}
            under = depth[ids == obj["int_id"]]
            under = under[np.isfinite(under)]
            if under.size:
                entry["depth_min_m"] = float(under.min())
                entry["depth_median_m"] = float(np.median(under))
            own = next((d for o, d in drawn if o["int_id"] == obj["int_id"]), None)
            if own is not None:
                alone = np.where(np.isfinite(own), obj["int_id"], 0).astype(np.uint8)
                alone_name = f"{stem}_alone_{obj['int_id']}.png"
                Image.fromarray(alone, mode="L").save(folder / alone_name)
                footprint = alone == obj["int_id"]
                entry["pixels_alone"] = int(np.count_nonzero(footprint))
                entry["alone_png"] = alone_name
                if entry["pixels_alone"]:
                    entry["visible_fraction"] = entry["pixels"] / entry["pixels_alone"]
                    entry["occluded_by"] = sorted(
                        int(v) for v in np.unique(ids[footprint])
                        if int(v) not in (0, obj["int_id"]))
            declared.append(entry)
        first = declared[0]
        fov = math.degrees(2.0 * math.atan(float(record["sensor_width_mm"])
                                           / (2.0 * float(record["focal_length_mm"]))))
        per_camera.setdefault(camera, []).append({
            "frame": name,
            "labels": {
                "mask": f"{stem}_mask.png", "class_mask": f"{stem}_class.png",
                "depth": f"{stem}_depth.png", "depth_f32": f"{stem}_depth.f32",
                "depth_scale_m": DEPTH_SCALE_M, "depth_saturation_m": DEPTH_SATURATION_M,
                "silhouette_pixels": first["pixels_alone"],
                "visible_pixels": first["pixels"],
                "occlusion_fraction": (1.0 - first["visible_fraction"]
                                       if first["visible_fraction"] is not None else None),
                "classes": "0 sky, " + ", ".join(
                    f"{i + 1} {c}" for i, c in enumerate(manifest["taxonomy"])),
                "method": "custom-stencil ID pass, AA off; alone pass per aircraft "
                          "(fabricated by tests/test_annotation_gates.py)",
                "anti_aliasing": "none", "id_source": "card objects[]",
                "unlabelled_geometry_pixels": 0, "non_integer_id_pixels": 0,
                "objects": declared,
            },
            "applied_focal_length_mm": float(record["focal_length_mm"]),
            "applied_sensor_width_mm": float(record["sensor_width_mm"]),
            "applied_fov_deg": fov,
            "applied_width_px": w, "applied_height_px": h,
        })
    for camera, records in per_camera.items():
        payload = {
            "host": "unreal", "spec_digest": manifest["spec_digest"],
            "frames": len(records),
            "drawn": {"kind": "mesh", "mesh_origin_actor_cm": [-2979.8, 0.0, 13.9],
                      "manifest_version": 3,
                      "origin_basis": "measured from vertices (fabricated)"},
            "objects": [{"id": o["id"], "int_id": o["int_id"], "class": o["class"],
                         "class_id": o["class_id"], "role": o["role"],
                         "alone_pass": o["class"] == "aircraft"} for o in objects],
            "labels_id_source": "card objects[]",
            "frame_records": records,
        }
        (run_dir / "frames" / camera / "render.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")
    if attach:
        attach_engine_labels(run_dir)
    return read_capture_manifest(run_dir / "capture_manifest.json")


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    run_dir = tmp_path_factory.mktemp("gates") / "clean"
    fabricate_run(run_dir)
    return run_dir


@pytest.fixture
def run(clean_run, tmp_path):
    """A private copy of the clean run for a mutation."""
    target = tmp_path / "run"
    shutil.copytree(clean_run, target)
    return target


def checks_of(run_dir, other=None):
    report = verify_run(run_dir, other_run_dir=other)
    return {c.name: c for c in report.checks}, report


def _render_json(run_dir, camera):
    return run_dir / "frames" / camera / "render.json"


def _edit_render_json(run_dir, camera, edit):
    path = _render_json(run_dir, camera)
    payload = json.loads(path.read_text(encoding="utf-8"))
    edit(payload)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def _reattach(run_dir):
    """Re-derive every record from the (mutated) files -- render.json's
    per-object counts as an engine consistent with its own files would
    write them, then the manifest through attach_engine_labels -- so a
    mutation is judged on its geometry and not on a record that
    disagrees with its file."""
    for camera_dir in (Path(run_dir) / "frames").iterdir():
        path = camera_dir / "render.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload["frame_records"]:
            labels = record["labels"]
            mask = np.asarray(Image.open(camera_dir / labels["mask"]))
            depth = np.fromfile(camera_dir / labels["depth_f32"], dtype="<f4").reshape(mask.shape)
            for entry in labels["objects"]:
                int_id = entry["int_id"]
                visible = mask == int_id
                entry["pixels"] = int(np.count_nonzero(visible))
                under = depth[visible]
                under = under[np.isfinite(under)]
                entry["depth_min_m"] = float(under.min()) if under.size else None
                entry["depth_median_m"] = float(np.median(under)) if under.size else None
                if entry.get("alone_png"):
                    footprint = np.asarray(Image.open(camera_dir / entry["alone_png"])) == int_id
                    entry["pixels_alone"] = int(np.count_nonzero(footprint))
                    entry["visible_fraction"] = (entry["pixels"] / entry["pixels_alone"]
                                                 if entry["pixels_alone"] else None)
                    entry["occluded_by"] = sorted(int(v) for v in np.unique(mask[footprint])
                                                  if int(v) not in (0, int_id))
            first = labels["objects"][0]
            labels["silhouette_pixels"] = first["pixels_alone"]
            labels["visible_pixels"] = first["pixels"]
            labels["occlusion_fraction"] = (1.0 - first["visible_fraction"]
                                            if first["visible_fraction"] is not None else None)
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    attach_engine_labels(run_dir)


# -- the fabricated bundle agrees with the producer before it is graded ------

def test_the_painted_primary_lands_on_the_producers_box(clean_run):
    """The test's rotation + pinhole against the producer's labels: the
    painted primary's tight box is the manifest's bbox_2d to a pixel
    (a box drawn from its box, so the two extents coincide)."""
    manifest = read_capture_manifest(clean_run / "capture_manifest.json")
    compared = 0
    for record in manifest["frames"]:
        box = record["labels"]["bbox_2d"]
        if box is None:
            continue
        mask = np.asarray(Image.open(
            clean_run / "frames" / record["camera_id"] / f"{Path(record['file']).stem}_mask.png"))
        ys, xs = np.nonzero(mask == 1)
        tight = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        for mine, theirs in zip(tight, box):
            assert abs(mine - theirs) <= 1.5, (record["camera_id"], tight, box)
        compared += 1
    assert compared == len(manifest["frames"])


def test_the_scene_has_an_occlusion_to_grade(clean_run):
    """The crossing A320 passes behind the 747 for the chase camera on at
    least one frame, so visibility_vs_scene grades a real overlap."""
    manifest = read_capture_manifest(clean_run / "capture_manifest.json")
    occluded = [e for r in manifest["frames"] for e in r["labels"]["objects"]
                if e["int_id"] == 2 and e["visible_fraction"] is not None
                and e["visible_fraction"] < 1.0]
    assert occluded, "no frame occludes the traffic; the fixture lost its overlap"
    assert all(e["occluded_by"] == ["aircraft:B747:0"] for e in occluded)


# -- the clean run passes every gate -----------------------------------------

def test_the_clean_fabricated_run_passes_every_annotation_check(clean_run):
    by_name, report = checks_of(clean_run)
    for name in ANNOTATION_CHECKS:
        assert by_name[name].status == PASS, f"{name}: {by_name[name].detail}"
    assert by_name["label_files"].status == PASS
    # The version-5 checks are superseded on a manifest with objects[].
    assert by_name["mask_containment"].status == NOT_RUN
    assert "box_vs_mask" in by_name["mask_containment"].detail
    assert by_name["depth_range"].status == NOT_RUN
    assert "depth_vs_geometry" in by_name["depth_range"].detail
    assert report.ok, report.render()
    # Order on the page: after depth_range, before sensor_undistortion.
    names = [c.name for c in report.checks]
    assert names.index("depth_range") < names.index("mask_integers_only")
    assert names.index("applied_intrinsics") < names.index("sensor_undistortion")


def test_a_pass_carries_no_failure_name_and_a_fail_carries_its_own():
    assert "failure" not in Check("x", PASS, "d").to_dict()
    assert "failure" not in Check("x", NOT_RUN, "d", "annotation.files").to_dict()
    assert Check("x", FAIL, "d", "annotation.files").to_dict()["failure"] == "annotation.files"


# -- NOT RUN without the evidence ---------------------------------------------

def test_every_gate_is_not_run_without_a_bundle_or_objects(clean_run, tmp_path):
    manifest = read_capture_manifest(clean_run / "capture_manifest.json")
    bare = tmp_path / "bare"
    write_capture_manifest(manifest, bare)
    by_name, report = checks_of(bare)
    for name in ANNOTATION_CHECKS:
        assert by_name[name].status == NOT_RUN, name
    assert report.ok       # NOT RUN is not a failure, and not a pass
    old = copy.deepcopy(manifest)
    old["manifest_version"] = 5
    for key in ("objects", "taxonomy", "traffic"):
        old.pop(key)
    for record in old["frames"]:
        record["labels"].pop("objects")
        record["sensor"]["labels_sensor"].pop("objects")
    for check in (verify_mask_integers_only, verify_mask_vs_geometry,
                  verify_box_vs_mask, verify_depth_vs_geometry,
                  verify_visibility_vs_scene, verify_identity_stable):
        result = check(old, clean_run)
        assert result.status == NOT_RUN and "objects[]" in result.detail, result
    # ... while the version-5 checks run on the version-5 shape.
    assert verify_mask_containment(old, clean_run).status != NOT_RUN


# -- the mutations, each failing the named check -----------------------------

def test_a_mesh_drawn_3_m_from_its_label_fails_mask_vs_geometry(tmp_path):
    """The Phase 1 defect at a tenth of its size. A chase camera looks
    down the body axis and cannot see a shift along it (the first
    offender named is a wingman frame, every chase frame having
    passed); the wingman, abeam, sees 3 m as 3 % of the projected span."""
    fabricate_run(tmp_path / "shifted", offset_body=(3.0, 0.0, 0.0))
    check = verify_mask_vs_geometry(
        read_capture_manifest(tmp_path / "shifted" / "capture_manifest.json"),
        tmp_path / "shifted")
    assert check.status == FAIL, check.detail
    assert check.failure == "annotation.mask_offset"
    assert "centre of the mask's box" in check.detail
    assert check.detail.startswith("wing0/"), check.detail
    assert check.to_dict()["failure"] == "annotation.mask_offset"


def test_two_ids_swapped_in_the_engines_echo_fail_identity(run):
    """The engine reports it stencilled the primary as 2 and the traffic
    as 1: the card's list and the engine's disagree."""
    def swap(payload):
        a, b = payload["objects"][0], payload["objects"][1]
        a["int_id"], b["int_id"] = b["int_id"], a["int_id"]
    _edit_render_json(run, "chase0", swap)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_identity_stable(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.identity", check.detail
    assert "chase0" in check.detail


def test_two_ids_swapped_in_the_manifest_frames_fail_identity(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    entries = manifest["frames"][2]["labels"]["objects"]
    entries[0]["int_id"], entries[1]["int_id"] = entries[1]["int_id"], entries[0]["int_id"]
    check = verify_identity_stable(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.identity"


def test_an_id_the_engine_wrote_that_nobody_declared_fails_identity(run):
    def invent(payload):
        payload["frame_records"][0]["labels"]["objects"].append(
            {"int_id": 9, "pixels": 0, "pixels_alone": None, "alone_png": None})
    _edit_render_json(run, "wing0", invent)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_identity_stable(manifest, run)
    assert check.status == FAIL and "9" in check.detail


def test_two_ids_swapped_in_the_pixels_alone_are_caught_by_visibility(run):
    """A silent swap in the ID image (the engine's echo and the alone
    passes unchanged) is invisible to identity_stable -- the record is
    consistent -- and is caught where it shows: the primary's id now
    sits outside the primary's own alone footprint. With the swap in
    the alone passes too, the geometry check sees it instead (below)."""
    manifest = read_capture_manifest(run / "capture_manifest.json")
    for path in (run / "frames").glob("*/frame_*_mask.png"):
        mask = np.asarray(Image.open(path)).copy()
        swapped = np.where(mask == 1, 2, np.where(mask == 2, 1, mask)).astype(np.uint8)
        Image.fromarray(swapped, mode="L").save(path)
    assert verify_identity_stable(manifest, run).status == PASS
    check = verify_visibility_vs_scene(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.visibility", check.detail
    assert "outside its alone footprint" in check.detail


def test_two_ids_swapped_in_every_pass_are_caught_by_geometry(run):
    """The engine stencilled the two aircraft the other way round in
    every pass (a Populate order that is not the card's): the passes
    agree with each other and the geometry says the primary's silhouette
    is where the traffic is."""
    manifest = read_capture_manifest(run / "capture_manifest.json")
    for camera_dir in (run / "frames").iterdir():
        payload = json.loads((camera_dir / "render.json").read_text())
        for record in payload["frame_records"]:
            for path in [camera_dir / record["labels"]["mask"]] + [
                    camera_dir / d["alone_png"] for d in record["labels"]["objects"]
                    if d.get("alone_png")]:
                mask = np.asarray(Image.open(path)).copy()
                swapped = np.where(mask == 1, 2, np.where(mask == 2, 1, mask)).astype(np.uint8)
                Image.fromarray(swapped, mode="L").save(path)
            for d in record["labels"]["objects"]:
                if d.get("alone_png"):
                    d["alone_png"] = d["alone_png"].replace(
                        "_alone_1", "_alone_X").replace("_alone_2", "_alone_1").replace(
                        "_alone_X", "_alone_2")
        (camera_dir / "render.json").write_text(json.dumps(payload), encoding="utf-8")
    _reattach(run)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_mask_vs_geometry(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.mask_offset", check.detail


def test_a_blurred_id_image_fails_mask_integers_only(run):
    """A 3x3 mean over the ID image, rounded: blended edge values. Where
    the terrain (3) meets the sky (0) the blend lands on 1 and 2 --
    DECLARED ids, invisible to a histogram -- so the clause that sees it
    is the class image's disagreement with the id's class."""
    manifest = read_capture_manifest(run / "capture_manifest.json")
    path = run / "frames" / "chase0" / "frame_0000_mask.png"
    mask = np.asarray(Image.open(path)).astype(float)
    padded = np.pad(mask, 1, mode="edge")
    blurred = sum(padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
                  for dy in range(3) for dx in range(3)) / 9.0
    Image.fromarray(np.floor(blurred + 0.5).astype(np.uint8), mode="L").save(path)
    check = verify_mask_integers_only(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.mask_blend", check.detail
    assert "class" in check.detail


def test_an_undeclared_stencil_value_fails_mask_integers_only(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    path = run / "frames" / "wing0" / "frame_0001_mask.png"
    mask = np.asarray(Image.open(path)).copy()
    mask[10:14, 10:14] = 255
    Image.fromarray(mask, mode="L").save(path)
    check = verify_mask_integers_only(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.mask_blend"
    assert "255" in check.detail and "declares" in check.detail


def test_an_engine_that_counted_non_integer_ids_fails_mask_integers_only(run):
    def blended(payload):
        payload["frame_records"][1]["labels"]["non_integer_id_pixels"] = 7
    _edit_render_json(run, "chase0", blended)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_mask_integers_only(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.mask_blend"
    assert "7" in check.detail and "whole numbers" in check.detail


def test_a_depth_scaled_by_1_02_fails_depth_vs_geometry(run):
    """Every depth file scaled by 1.02 and the record re-derived from
    the scaled files, so the record agrees with its file and only the
    geometry can object: the nearest surface under the mask lands
    beyond the nearest keypoint (the tail, from behind) by more than
    1 % + 2 m."""
    for camera_dir in (run / "frames").iterdir():
        for record in json.loads((camera_dir / "render.json").read_text())["frame_records"]:
            f32 = camera_dir / record["labels"]["depth_f32"]
            depth = np.fromfile(f32, dtype="<f4") * 1.02
            depth.astype("<f4").tofile(f32)
            png = camera_dir / record["labels"]["depth"]
            values = np.asarray(Image.open(png)).astype(float)
            scaled = np.where(values >= 65535, 65535.0, np.minimum(values * 1.02, 65535.0))
            Image.fromarray(scaled.astype(np.uint16), mode="I;16").save(png)
    _reattach(run)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_depth_vs_geometry(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.depth_range", check.detail
    assert "keypoint" in check.detail


def test_a_record_that_disagrees_with_its_depth_file_fails_depth_vs_geometry(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    entry = manifest["frames"][0]["labels"]["objects"][0]
    entry["depth_median_m"] += 5.0
    check = verify_depth_vs_geometry(manifest, run)
    assert check.status == FAIL and "depth_median_m" in check.detail


def test_the_occluder_hidden_in_the_full_pass_fails_visibility(run):
    """The A320 crosses behind the 747. In the ID pass the 747's stencil
    is missing where the A320's footprint is -- the occluder hidden in
    the full pass -- so the A320 shows through in every overlap pixel
    while the depth capture (a separate pass) still holds the 747's
    surface there. Nothing is "hidden by nothing" (the depth explains
    every pixel), so only the overlap-ownership clause can see it: the
    farther object owns pixels the nearer one should."""
    for camera_dir in (run / "frames").iterdir():
        payload = json.loads((camera_dir / "render.json").read_text())
        for record in payload["frame_records"]:
            alone = next((camera_dir / d["alone_png"] for d in record["labels"]["objects"]
                          if d.get("alone_png") and d["int_id"] == 2), None)
            if alone is None:
                continue
            path = camera_dir / record["labels"]["mask"]
            mask = np.asarray(Image.open(path)).copy()
            footprint = np.asarray(Image.open(alone)) == 2
            mask[footprint] = 2
            Image.fromarray(mask, mode="L").save(path)
    _reattach(run)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_visibility_vs_scene(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.visibility", check.detail
    assert "overlapping footprint pixels" in check.detail, check.detail
    assert "nothing nearer" not in check.detail


def test_an_object_dropped_from_the_full_pass_fails_visibility(run):
    """The traffic erased from the ID pass where nothing hides it: sky
    behind, its footprint hidden by nothing."""
    manifest = read_capture_manifest(run / "capture_manifest.json")
    for camera_dir in (run / "frames").iterdir():
        for path in camera_dir.glob("frame_*_mask.png"):
            mask = np.asarray(Image.open(path)).copy()
            mask[mask == 2] = 0
            Image.fromarray(mask, mode="L").save(path)
    _reattach(run)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_visibility_vs_scene(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.visibility", check.detail
    assert "nothing nearer" in check.detail


def test_an_occluder_the_scene_does_not_declare_fails_visibility(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    record = next(r for r in manifest["frames"]
                  if r["labels"]["objects"][1]["occluded_by"])
    record["labels"]["objects"][1]["occluded_by"] = ["building:7"]
    check = verify_visibility_vs_scene(manifest, run)
    assert check.status == FAIL and "occluded_by" in check.detail


def test_a_render_at_a_field_of_view_one_degree_off_fails_applied_intrinsics(run):
    def widen(payload):
        payload["frame_records"][0]["applied_fov_deg"] += 1.0
    _edit_render_json(run, "wing0", widen)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_applied_intrinsics(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.intrinsics", check.detail
    assert "field of view" in check.detail and "wing0" in check.detail


def test_applied_intrinsics_is_not_run_without_the_engine_record(clean_run, tmp_path):
    manifest = read_capture_manifest(clean_run / "capture_manifest.json")
    assert verify_applied_intrinsics(manifest, None).status == NOT_RUN
    assert verify_applied_intrinsics(manifest, tmp_path).status == NOT_RUN


def test_a_declared_alone_pass_that_is_missing_fails_label_files(run):
    victim = run / "frames" / "chase0" / "frame_0002_alone_1.png"
    victim.unlink()
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_label_files(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.files"
    assert victim.name in check.detail


def test_a_tight_box_the_record_did_not_measure_fails_box_vs_mask(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    entry = manifest["frames"][0]["labels"]["objects"][0]
    entry["bbox_2d_tight"] = [v + 20.0 for v in entry["bbox_2d_tight"]]
    check = verify_box_vs_mask(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.box_mismatch"


def test_a_mask_half_the_size_of_its_hull_fails_box_vs_mask(run):
    """The IoU clause on its own: the primary's pixels cut to their left
    half in every pass (the record re-derived), so the tight box is
    half the projected hull's."""
    for path in list((run / "frames").glob("*/frame_*_mask.png")) + list(
            (run / "frames").glob("*/frame_*_alone_1.png")):
        mask = np.asarray(Image.open(path)).copy()
        ys, xs = np.nonzero(mask == 1)
        if xs.size:
            cut = (xs.min() + xs.max()) // 2
            hit = (mask == 1) & (np.arange(mask.shape[1])[None, :] > cut)
            mask[hit] = 0
        Image.fromarray(mask, mode="L").save(path)
    _reattach(run)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_box_vs_mask(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.box_mismatch", check.detail
    assert "IoU" in check.detail


def test_a_silhouette_smaller_than_its_hull_fails_mask_vs_geometry(run):
    """The extent clause on its own: the primary's silhouette shrunk to
    the central 80 % of its box in every pass, the centre unchanged --
    a mesh drawn at the right place at the wrong size."""
    for path in list((run / "frames").glob("*/frame_*_mask.png")) + list(
            (run / "frames").glob("*/frame_*_alone_1.png")):
        mask = np.asarray(Image.open(path)).copy()
        ys, xs = np.nonzero(mask == 1)
        if xs.size:
            u0, u1 = xs.min(), xs.max() + 1
            v0, v1 = ys.min(), ys.max() + 1
            du, dv = int(round((u1 - u0) * 0.1)), int(round((v1 - v0) * 0.1))
            keep = np.zeros(mask.shape, dtype=bool)
            keep[v0 + dv:v1 - dv, u0 + du:u1 - du] = True
            mask[(mask == 1) & ~keep] = 0
        Image.fromarray(mask, mode="L").save(path)
    _reattach(run)
    manifest = read_capture_manifest(run / "capture_manifest.json")
    check = verify_mask_vs_geometry(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.mask_offset", check.detail
    assert "mask extent" in check.detail


# -- across runs, and the CLI ---------------------------------------------------

def test_identity_holds_across_two_runs_of_one_spec_and_fails_when_it_does_not(
        run, clean_run, tmp_path):
    by_name, report = checks_of(run, other=clean_run)
    assert by_name["identity_stable"].status == PASS
    assert "same spec" in by_name["identity_stable"].detail
    other = tmp_path / "other"
    shutil.copytree(clean_run, other)
    manifest = read_capture_manifest(other / "capture_manifest.json")
    a, b = manifest["objects"][0], manifest["objects"][1]
    a["int_id"], b["int_id"] = b["int_id"], a["int_id"]
    write_capture_manifest(manifest, other)
    by_name, report = checks_of(run, other=other)
    assert by_name["identity_stable"].status == FAIL
    assert by_name["identity_stable"].failure == "annotation.identity"
    assert not report.ok


def test_the_cli_prints_the_gates_and_refuses_export_readiness_on_a_fail(
        run, tmp_path, capsys):
    from flightsim.verify import main

    assert main([str(run)]) == 0
    out = capsys.readouterr().out
    for name in ANNOTATION_CHECKS:
        assert f"[PASS] {name}:" in out
    recorded = json.loads((run / "verification.json").read_text(encoding="utf-8"))
    assert recorded["ok"] is True
    assert all("failure" not in c for c in recorded["checks"])

    fabricate_run(tmp_path / "shifted", offset_body=(3.0, 0.0, 0.0))
    assert main([str(tmp_path / "shifted")]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] mask_vs_geometry:" in out
    assert "refused by name: annotation.mask_offset (mask_vs_geometry)" in out
    recorded = json.loads((tmp_path / "shifted" / "verification.json").read_text())
    assert recorded["ok"] is False
    failed = {c["name"]: c for c in recorded["checks"] if c["status"] == "FAIL"}
    assert failed["mask_vs_geometry"]["failure"] == "annotation.mask_offset"


def test_write_verification_carries_the_failure_key(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    entries = manifest["frames"][0]["labels"]["objects"]
    entries[0]["int_id"], entries[1]["int_id"] = entries[1]["int_id"], entries[0]["int_id"]
    write_capture_manifest(manifest, run)
    _, report = checks_of(run)
    path = write_verification(report, run)
    recorded = json.loads(path.read_text(encoding="utf-8"))
    failed = [c for c in recorded["checks"] if c["status"] == "FAIL"]
    assert any(c.get("failure") == "annotation.identity" for c in failed)


def test_write_verification_is_atomic(run, monkeypatch):
    """A campaign's workers write verdicts while the campaign reads them:
    a crash mid-write must leave the previous complete verdict in place,
    not half a document. Simulated by a write that dies after the first
    bytes; the target must still parse as the earlier verdict."""
    from pathlib import Path as _Path

    _, report = checks_of(run)
    path = write_verification(report, run)
    before = path.read_text(encoding="utf-8")
    assert json.loads(before)["ok"] is True
    real = _Path.write_text

    def dies_half_way(self, text, *args, **kwargs):
        real(self, text[: len(text) // 2], *args, **kwargs)
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(_Path, "write_text", dies_half_way)
    with pytest.raises(OSError):
        write_verification(report, run)
    monkeypatch.undo()
    # The crash leaves its half-written temporary behind (a real one
    # would too); the verdict a reader opens is the earlier complete one.
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(before)


# -- the visual sheets ----------------------------------------------------------

def test_the_annotation_sheets_are_written_and_not_blank(clean_run, tmp_path):
    from tests.visual.annotation_sheets import SHEETS, write_sheets

    written = write_sheets(clean_run, tmp_path / "visual")
    assert sorted(written) == sorted(SHEETS)
    for name, path in written.items():
        assert path.is_file() and path.suffix == ".png", name
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"))
        assert pixels.shape[0] >= 64 and pixels.shape[1] >= 64, name
        assert pixels.std() > 10.0, f"{name} is blank"
        assert len(np.unique(pixels.reshape(-1, 3), axis=0)) > 16, f"{name} is flat"
