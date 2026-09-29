"""The annotation gates (Phase 2, package D; contracts §4) against a
fabricated ground-truth bundle, and each brainstorm §3.6 mutation
failing the named check.

The run is a real manifest-6 solve over synthetic telemetry (a 747 with
an A320 crossing 400 m ahead; a long chase station and the wingman
slot) -- the producer's manifest, as every verifier test uses. The
BUNDLE is painted here, by the test's own arithmetic: the camera axes
from the record's Euler angles as three elementary rotations, the
primary's box from the airframe block placed by its recorded state, a
ray through every pixel centre through the recorded pinhole, the slab
test against each box, a z-buffer over the boxes and the ground plane.
The ID image, the class image, the float depth, the alone passes and
render.json come out of that and nothing else; ``attach_engine_labels``
then fills the record as it would after a render. A consistency test
pins the painted primary against the producer's own bbox_2d so the
arithmetic is shown to agree before anything is graded against it.

What is NOT the test's own, stated: the traffic aircraft's PLACEMENT.
The manifest records no per-frame traffic state, so the verifier takes
the record's ``bbox_3d_camera`` as the traffic placement (and says so
in every detail), and this fixture places the traffic box from the
same solved track (the producer's ``solve_traffic_track`` /
``traffic_state``). A placement error in that solver therefore moves
the painted pixels and the graded reference together and no gate here
can see it; the traffic's projection, pixels and depth are what is
graded independently. ``test_traffic_placement_is_producer_trusted``
pins that this is stated, not hidden.

The fixture is hermetic: the manifest cites no mesh manifest whatever
this machine has imported under ``assets/generated`` (the producer
cites one with its digest whenever the file exists, and the verifier
would then grade the painted airframe box against the mesh's extent).
The mesh branch of the verifier's hull is exercised deliberately by
``fabricated_mesh_manifest`` under a temporary repository root.

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
    a declared ID image deleted           annotation.files (each gate that reads it)
    render.json without objects[] echo    annotation.identity
    records the bundle never reached      annotation.box_mismatch / depth_range / visibility
    a camera with no applied lens         annotation.intrinsics
    a mesh 10 % taller than its label     annotation.mask_offset (the mesh branch)

A verification never ends in a traceback: a check that cannot read a
declared file, or breaks, is a FAIL by sentence and verification.json
is still written. The mutation guards in scripts/mutation_check.sh
disable each clause in turn and confirm the matching test here goes red.
"""

from __future__ import annotations

import copy
import hashlib
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
#: Where the producer cites the primary's mesh manifest (repo-relative);
#: the verifier resolves it under its own repository root.
MESH_PATH = "assets/generated/B747/mesh_manifest.json"


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


def fabricated_manifest(spec, mesh=None, citation=None):
    """The producer's manifest over the fixture's flight. Hermetic: the
    producer reads no mesh manifest from this machine's assets/generated
    (``mesh_manifests`` is the test's own -- ``mesh`` for the B747 or
    none), and the assets block cites exactly what the test says
    (``citation``, else no mesh with the reason)."""
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
        scene={"key": "flat", "terrain": None}, traffic_tracks=traffic_tracks,
        mesh_manifests={"B747": mesh} if mesh is not None else {})
    manifest["assets"]["mesh_manifest"] = citation or {
        "path": MESH_PATH, "sha256": None,
        "note": "fixture: the bundle is painted from the airframe block's box, "
                "so no mesh is cited whatever this machine has imported"}
    return manifest, traffic_tracks


def fabricated_mesh_manifest(airframe_block, taller=1.0):
    """A version-3 mesh manifest as the converter would write one whose
    measured extent is exactly the airframe block's box: the box
    re-based from the CG onto the structural datum (the actor frame's
    origin, +x forward, +y right, +z UP) with the origin at zero -- the
    inverse of the frame change the verifier's _hull_box_body makes,
    written here in the test's own words. ``taller`` scales the
    measured height so the mesh disagrees with the painted box."""
    box = airframe_block["box_body_m"]
    cx, cy, cz = (float(v) for v in airframe_block["cg_structural_in"])
    cg = (-cx * 0.0254, cy * 0.0254, cz * 0.0254)
    top, bottom = float(box["down"][0]) * taller, float(box["down"][1]) * taller
    return {
        "version": 3,
        "aircraft": "B747",
        "mesh_origin_actor_cm": [0.0, 0.0, 0.0],
        "mesh_origin_basis": "measured from vertices: nose keypoint (x), "
                             "main-gear contact (z) (fabricated by "
                             "tests/test_annotation_gates.py)",
        "mesh_extent_actor_m": {
            "x": [float(box["forward"][0]) + cg[0], float(box["forward"][1]) + cg[0]],
            "y": [float(box["right"][0]) + cg[1], float(box["right"][1]) + cg[1]],
            "z": [-bottom + cg[2], -top + cg[2]]},
    }


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


def fabricate_run(run_dir, offset_body=(0.0, 0.0, 0.0), attach=True,
                  mesh_file=None, mesh_path=MESH_PATH):
    """Write a complete manifest-6 run with its bundle under ``run_dir``.

    ``offset_body`` draws the PRIMARY's box that far from its label in
    its own body frame (the mesh-origin mutation). ``mesh_file`` is a
    mesh manifest the producer labels from and the manifest cites at
    ``mesh_path`` with the file's digest (the verifier finds it under
    its repository root); the primary is still painted from the
    airframe block's box. Returns the manifest as written (after
    attach_engine_labels when ``attach``)."""
    run_dir = Path(run_dir)
    spec = fabricated_spec()
    mesh = citation = None
    if mesh_file is not None:
        data = Path(mesh_file).read_bytes()
        mesh = json.loads(data)
        citation = {"path": mesh_path, "sha256": hashlib.sha256(data).hexdigest(),
                    "note": None}
    manifest, traffic_tracks = fabricated_manifest(spec, mesh=mesh, citation=citation)
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


@pytest.fixture(scope="module")
def shifted_run(tmp_path_factory):
    """The Phase 1 defect at a tenth of its size: the primary drawn 3 m
    from its label along its own axis."""
    run_dir = tmp_path_factory.mktemp("gates") / "shifted"
    fabricate_run(run_dir, offset_body=(3.0, 0.0, 0.0))
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


def manifest_of(run_dir):
    return read_capture_manifest(Path(run_dir) / "capture_manifest.json")


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
    # The PASS sentences say how many RECORDS were compared against the
    # files, not only how many object-frames were graded.
    assert "records' bbox_2d_tight re-counted" in by_name["box_vs_mask"].detail
    assert "records' depth_min_m / depth_median_m" in by_name["depth_vs_geometry"].detail
    assert "records' fractions and occluders re-counted" in by_name["visibility_vs_scene"].detail
    assert not by_name["box_vs_mask"].detail.startswith("0 ")
    # The clean fixture is hermetic: the hull graded is the airframe
    # block's box on every machine, whatever it has imported.
    assert manifest_of(clean_run)["assets"]["mesh_manifest"]["sha256"] is None
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

def test_a_mesh_drawn_3_m_from_its_label_fails_mask_vs_geometry(shifted_run):
    """The Phase 1 defect at a tenth of its size. A chase camera looks
    down the body axis and cannot see a shift along it (the first
    offender named is a wingman frame, every chase frame having
    passed); the wingman, abeam, sees 3 m as 3 % of the projected span."""
    check = verify_mask_vs_geometry(manifest_of(shifted_run), shifted_run)
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
        payload = json.loads((camera_dir / "render.json").read_text(encoding="utf-8"))
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
        for record in json.loads((camera_dir / "render.json").read_text(encoding="utf-8"))["frame_records"]:
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
        payload = json.loads((camera_dir / "render.json").read_text(encoding="utf-8"))
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
        run, shifted_run, tmp_path, capsys):
    from flightsim.verify import main

    assert main([str(run)]) == 0
    out = capsys.readouterr().out
    for name in ANNOTATION_CHECKS:
        assert f"[PASS] {name}:" in out
    recorded = json.loads((run / "verification.json").read_text(encoding="utf-8"))
    assert recorded["ok"] is True
    assert all("failure" not in c for c in recorded["checks"])

    shifted = tmp_path / "shifted"
    shutil.copytree(shifted_run, shifted)
    assert main([str(shifted)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] mask_vs_geometry:" in out
    assert "refused by name: annotation.mask_offset (mask_vs_geometry)" in out
    recorded = json.loads((shifted / "verification.json").read_text(encoding="utf-8"))
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

def _pixels(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def _count(pixels, colour):
    return int(np.count_nonzero(np.all(pixels == np.asarray(colour, dtype=np.uint8), axis=-1)))


def test_the_annotation_sheets_draw_what_each_check_measured(clean_run, tmp_path):
    """Each sheet holds the marks its docstring names, in the colours
    the drawing helpers define -- measured on the clean run: the hull
    wireframe and the mask edge, both boxes, the depth heatmap's stops,
    the alone footprints, one palette cell per object -- and the
    record beside them says every sheet was drawn. Before this test a
    sheet whose painter threw was a captioned placeholder that passed
    the old blankness test (measured: std 30-38, ~390 colours from the
    antialiased text alone)."""
    from tests.visual import draw
    from tests.visual.annotation_sheets import SHEETS, SHEETS_RECORD, write_sheets

    out = tmp_path / "visual"
    written = write_sheets(clean_run, out)
    assert sorted(written) == sorted(SHEETS)
    record = json.loads((out / SHEETS_RECORD).read_text(encoding="utf-8"))
    assert sorted(record) == sorted(SHEETS)
    for name, path in written.items():
        assert path.is_file() and path.suffix == ".png", name
        assert record[name]["drawn"] is True and record[name]["error"] is None, record[name]
        assert record[name]["verdict"] == f"[PASS] {name}", record[name]
        assert record[name]["file"] == path.name
        pixels = _pixels(path)
        assert pixels.shape[0] >= 64 and pixels.shape[1] >= 64, name
        assert pixels.std() > 10.0, f"{name} is blank"
    # mask_vs_geometry: the projected hull (yellow wire, hundreds of
    # pixels per box), the CG cross, the two box centres.
    pixels = _pixels(written["mask_vs_geometry"])
    assert _count(pixels, draw.YELLOW) > 200
    assert _count(pixels, draw.CYAN) > 20 and _count(pixels, draw.MAGENTA) > 20
    assert _count(pixels, draw.GREEN) > 20
    # box_vs_mask: the tight box (green) and the hull box (yellow).
    pixels = _pixels(written["box_vs_mask"])
    assert _count(pixels, draw.YELLOW) > 200 and _count(pixels, draw.GREEN) > 200
    # depth_vs_geometry: the heatmap's colour range is the aircraft's
    # band, so the ground 3 km below saturates to the far stop (measured
    # 231 219 px) and the airframes sit in the band's blue-to-cyan half
    # (measured 22 701 px with b > 100 and r < 60; no pixel is nearer
    # than the band, the scene being flown at 3 048 m over a flat datum).
    pixels = _pixels(written["depth_vs_geometry"])
    assert _count(pixels, (230, 40, 30)) > 500, "no far-stop pixels: no heatmap"
    bluish = (pixels[..., 2].astype(int) > 100) & (pixels[..., 0].astype(int) < 60)
    assert int(np.count_nonzero(bluish)) > 1000, "no in-band pixels: no heatmap"
    # visibility_vs_scene: on the occluded frame the traffic's alone
    # footprint hidden by the 747 is painted red (measured 184 px) and
    # the 747's own footprint in its palette colour (47 500 px).
    pixels = _pixels(written["visibility_vs_scene"])
    assert _count(pixels, draw.RED) > 20, "no hidden footprint pixels drawn"
    assert _count(pixels, draw.colour_of(1)) > 500
    # identity_stable: one 31x31 palette cell per object per column (six
    # frames and two engine echoes).
    pixels = _pixels(written["identity_stable"])
    for int_id in (1, 2, 3):
        assert _count(pixels, draw.colour_of(int_id)) >= 8 * 31 * 31, f"no cells for id {int_id}"
    # mask_integers_only: the ID image colourised by id.
    pixels = _pixels(written["mask_integers_only"])
    assert _count(pixels, draw.colour_of(1)) > 500 and _count(pixels, draw.colour_of(3)) > 5000


def test_the_sheets_carry_the_verdict_of_a_shifted_run(shifted_run, tmp_path):
    from tests.visual.annotation_sheets import SHEETS_RECORD, write_sheets

    out = tmp_path / "shifted"
    write_sheets(shifted_run, out)
    record = json.loads((out / SHEETS_RECORD).read_text(encoding="utf-8"))
    assert record["mask_vs_geometry"]["verdict"] == (
        "[FAIL] mask_vs_geometry -- annotation.mask_offset")
    assert record["mask_vs_geometry"]["failure"] == "annotation.mask_offset"
    assert record["mask_vs_geometry"]["drawn"] is True
    assert "centre of the mask's box" in record["mask_vs_geometry"]["detail"]


def test_a_painter_that_throws_is_recorded_as_not_drawn(clean_run, tmp_path, monkeypatch):
    """A sheet never hides the verdict: the PNG is still written with
    the caption, and the record says the sheet was not drawn and why,
    so the CLI exits 1 and a test cannot mistake the placeholder for
    the picture."""
    import tests.visual.annotation_sheets as sheets

    def boom(manifest, run_dir):
        raise RuntimeError("painter broke")

    monkeypatch.setattr(sheets, "sheet_box_vs_mask", boom)
    out = tmp_path / "broken"
    written = sheets.write_sheets(clean_run, out)
    record = json.loads((out / sheets.SHEETS_RECORD).read_text(encoding="utf-8"))
    assert written["box_vs_mask"].is_file()
    assert record["box_vs_mask"]["drawn"] is False
    assert "painter broke" in record["box_vs_mask"]["error"]
    assert record["box_vs_mask"]["verdict"] == "[PASS] box_vs_mask"
    assert all(record[n]["drawn"] for n in sheets.SHEETS if n != "box_vs_mask")
    assert sheets.main([str(clean_run), "--out", str(tmp_path / "cli")]) == 1


# -- a bundle file the record declares and the disk does not hold ---------------

def test_a_declared_id_image_that_is_missing_fails_by_name_never_by_traceback(
        run, capsys):
    """Measured before the fix: deleting one declared mask ended
    ``flightsim.verify`` in a FileNotFoundError traceback (verify.py
    _read_gray_png), exit 1 for the wrong reason, no 'refused by name'
    line and no verification.json -- a run with no verdict. Now every
    gate that would have opened the file is annotation.files naming
    it, and the verdict is on disk."""
    from flightsim.verify import main

    (run / "frames" / "chase0" / "frame_0001_mask.png").unlink()
    by_name, report = checks_of(run)
    assert by_name["label_files"].status == FAIL
    assert by_name["label_files"].failure == "annotation.files"
    for name in ("mask_integers_only", "mask_vs_geometry", "box_vs_mask",
                 "depth_vs_geometry", "visibility_vs_scene"):
        check = by_name[name]
        assert check.status == FAIL, (name, check.detail)
        assert check.failure == "annotation.files", (name, check.detail)
        assert "chase0/frame_0001_mask.png is missing" in check.detail, check.detail
        assert "Traceback" not in check.detail and "Error" not in check.detail
    assert not report.ok
    assert main([str(run)]) == 1
    out = capsys.readouterr().out
    assert "Traceback" not in out
    assert "refused by name: annotation.files (label_files)" in out
    recorded = json.loads((run / "verification.json").read_text(encoding="utf-8"))
    assert recorded["ok"] is False


def test_a_declared_depth_file_that_is_missing_fails_by_name(run):
    (run / "frames" / "wing0" / "frame_0000_depth.f32").unlink()
    by_name, report = checks_of(run)
    for name in ("depth_vs_geometry", "visibility_vs_scene", "label_files"):
        check = by_name[name]
        assert check.status == FAIL and check.failure == "annotation.files", (name, check.detail)
        assert "frame_0000_depth.f32" in check.detail
    assert by_name["mask_vs_geometry"].status == PASS       # it reads no depth
    assert not report.ok


def test_a_check_that_breaks_is_a_fail_in_a_sentence_and_the_verdict_is_written(
        run, monkeypatch, capsys):
    """A defect in the checker itself must not leave the run without a
    verdict: the broken check is a FAIL that says so, every other check
    still reports, and verification.json is written."""
    from core.capture import verify as verify_module
    from flightsim.verify import main

    def broken(manifest, run_dir):
        raise RuntimeError("simulated defect in the checker")

    monkeypatch.setattr(verify_module, "verify_applied_intrinsics", broken)
    by_name, report = checks_of(run)
    check = by_name["applied_intrinsics"]
    assert check.status == FAIL and check.failure is None
    assert "could not" in check.detail or "did not expect" in check.detail
    assert "simulated defect in the checker" in check.detail
    assert by_name["mask_vs_geometry"].status == PASS
    assert not report.ok
    assert main([str(run)]) == 1
    assert "Traceback" not in capsys.readouterr().out
    assert (run / "verification.json").is_file()


def test_a_manifest_that_is_not_an_object_is_a_named_fail(run):
    (run / "capture_manifest.json").write_text("[]", encoding="utf-8")
    by_name, report = checks_of(run)
    assert by_name["manifest_version"].status == FAIL and not report.ok


# -- --against a directory with no usable manifest --------------------------------

def test_against_without_a_manifest_is_a_named_fail_not_a_traceback(
        run, tmp_path, capsys):
    """Measured before the fix: ``--against /nonexistent`` ended in a
    FileNotFoundError traceback with no verification.json. The first
    run's manifest already had manifest_present / manifest_version
    checks; the second now has the same, and the cross-run clauses
    report NOT RUN."""
    from flightsim.verify import main

    by_name, report = checks_of(run, other=tmp_path / "nonexistent")
    assert by_name["against_manifest_present"].status == FAIL
    assert "nonexistent" in by_name["against_manifest_present"].detail
    assert by_name["temporal_alignment"].status == NOT_RUN
    assert "against" in by_name["temporal_alignment"].detail
    assert by_name["identity_stable"].status == PASS
    assert "same spec" not in by_name["identity_stable"].detail
    assert not report.ok
    assert main([str(run), "--against", str(tmp_path / "nonexistent")]) == 1
    out = capsys.readouterr().out
    assert "Traceback" not in out and "[FAIL] against_manifest_present" in out
    assert (run / "verification.json").is_file()

    other = tmp_path / "wrong_version"
    other.mkdir()
    (other / "capture_manifest.json").write_text(
        json.dumps({"manifest_version": 99}), encoding="utf-8")
    by_name, report = checks_of(run, other=other)
    assert by_name["against_manifest_version"].status == FAIL
    assert "99" in by_name["against_manifest_version"].detail
    assert by_name["temporal_alignment"].status == NOT_RUN and not report.ok

    # A usable second run says so, and the cross-run clauses run.
    by_name, report = checks_of(run, other=run)
    assert by_name["against_manifest_version"].status == PASS
    assert by_name["temporal_alignment"].status == PASS
    assert "same spec" in by_name["identity_stable"].detail


# -- the summary: superseded checks apart from those waiting for evidence -------

def test_the_summary_tells_superseded_checks_from_those_waiting_for_evidence(clean_run):
    """mask_containment and depth_range are NOT RUN on a manifest-6 run
    because box_vs_mask and depth_vs_geometry replaced them, not because
    any evidence is missing; a reader counting 'not run' must not take
    them for pending engine checks. The status word and the counts in
    verification.json are unchanged (a contract other readers hold)."""
    from core.capture.verify import is_superseded

    by_name, report = checks_of(clean_run)
    assert is_superseded(by_name["mask_containment"])
    assert is_superseded(by_name["depth_range"])
    assert not is_superseded(by_name["temporal_alignment"])
    text = report.render()
    summary = next(line for line in text.splitlines() if line.startswith("verification "))
    assert summary.endswith("2 superseded)"), summary
    waiting = next(line for line in text.splitlines() if line.startswith("  NOT RUN ("))
    assert "mask_containment" not in waiting and "depth_range" not in waiting
    assert "temporal_alignment" in waiting
    superseded = next(line for line in text.splitlines() if line.startswith("  SUPERSEDED"))
    assert "mask_containment" in superseded and "depth_range" in superseded
    not_run = [c for c in report.checks if c.status == NOT_RUN]
    assert f"{len(not_run) - 2} not run" in summary
    assert report.to_dict()["not_run"] == len(not_run)


# -- identity_stable: a render.json with no objects[] echo is not evidence ----

def test_a_render_json_with_no_objects_echo_never_counts_as_the_engines_word(run):
    """Measured before the fix: with the root objects[] deleted from
    both cameras' render.json the check PASSed saying 'the engine's
    render.json echoes the same list' -- the engine's half of the
    evidence, absent, counted as present."""
    manifest = manifest_of(run)
    _edit_render_json(run, "chase0", lambda payload: payload.pop("objects"))
    check = verify_identity_stable(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.identity", check.detail
    assert "chase0" in check.detail and "objects[] echo" in check.detail
    _edit_render_json(run, "wing0", lambda payload: payload.pop("objects"))
    check = verify_identity_stable(manifest, run)
    assert check.status == NOT_RUN, check.detail
    assert "echoes the same list" not in check.detail
    assert "objects[] echo" in check.detail and "half of the evidence" in check.detail
    # An empty echo is no echo.
    _edit_render_json(run, "chase0", lambda payload: payload.__setitem__("objects", []))
    _edit_render_json(run, "wing0", lambda payload: payload.__setitem__("objects", []))
    assert verify_identity_stable(manifest, run).status == NOT_RUN


# -- records the bundle was never attached to ------------------------------------

def test_records_the_bundle_never_reached_fail_by_name(tmp_path):
    """Measured before the fix: a manifest whose bbox_2d_tight,
    depth_min_m, depth_median_m and visible_fraction were all null
    (attach_engine_labels never ran) PASSed box_vs_mask ('8
    object-frames ...') and depth_vs_geometry while the bundle on disk
    showed pixels for every object -- a null was skipped, not graded.
    The export then ships null tight boxes."""
    run_dir = tmp_path / "unattached"
    fabricate_run(run_dir, attach=False)
    manifest = manifest_of(run_dir)
    for record in manifest["frames"]:
        for entry in record["labels"]["objects"]:
            assert entry["bbox_2d_tight"] is None and entry["depth_min_m"] is None
            for key in ("bbox_2d_tight", "depth_min_m", "depth_median_m", "visible_fraction"):
                entry[key] = None
            entry["occluded_by"] = []
    for check, failure, key in (
            (verify_box_vs_mask, "annotation.box_mismatch", "bbox_2d_tight"),
            (verify_depth_vs_geometry, "annotation.depth_range", "depth_min_m"),
            (verify_visibility_vs_scene, "annotation.visibility", "visible_fraction")):
        result = check(manifest, run_dir)
        assert result.status == FAIL, (check.__name__, result.detail)
        assert result.failure == failure, (check.__name__, result.detail)
        assert key in result.detail and "never completed from the bundle" in result.detail
    # A frame whose labels.objects[] has no record for an object with
    # pixels is the same finding, said differently.
    manifest = manifest_of(run_dir)
    del manifest["frames"][0]["labels"]["objects"][0]
    result = verify_box_vs_mask(manifest, run_dir)
    assert result.status == FAIL and "no record for it" in result.detail


# -- applied_intrinsics: a camera the engine did not record ----------------------

def test_a_camera_that_recorded_no_applied_intrinsics_is_named_not_skipped(run):
    """Measured before the fix: with every applied_* key stripped from
    wing0's render.json the check PASSed '3 frames rendered at the
    record's lens' over a 6-frame manifest, never naming wing0."""
    manifest = manifest_of(run)

    def strip(payload):
        for record in payload["frame_records"]:
            for key in [k for k in record if k.startswith("applied_")]:
                del record[key]

    _edit_render_json(run, "wing0", strip)
    check = verify_applied_intrinsics(manifest, run)
    assert check.status == FAIL and check.failure == "annotation.intrinsics", check.detail
    assert "wing0" in check.detail and "chase0" in check.detail
    # A camera with no render at all is not the engine's omission: it is
    # named as not graded in the PASS sentence.
    (run / "frames" / "wing0" / "render.json").unlink()
    check = verify_applied_intrinsics(manifest, run)
    assert check.status == PASS, check.detail
    assert "['wing0'] not rendered, not graded" in check.detail
    assert "3 frames of ['chase0']" in check.detail


# -- the hull: the airframe block, or the cited mesh when it is on this machine --

def test_the_hull_is_the_cited_mesh_extent_when_that_mesh_is_on_this_machine(
        tmp_path, monkeypatch):
    """The mesh branch of the verifier's hull, exercised deliberately:
    a version-3 mesh manifest whose measured extent IS the airframe
    box passes; one 10 % taller than the painted box fails
    mask_vs_geometry naming the mesh as its basis (the extent clause:
    measured 11 % off against a 5 % tolerance). The manifest cites the
    mesh with its digest and the verifier resolves the citation under a
    temporary repository root, so nothing is written into this clone."""
    from core.capture import verify as verify_module

    repo = tmp_path / "repo"
    airframe = fabricated_manifest(fabricated_spec())[0]["airframe"]
    monkeypatch.setattr(verify_module, "_REPO", repo)
    for label, taller in (("exact", 1.0), ("taller", 1.1)):
        mesh_file = repo / MESH_PATH
        mesh_file.parent.mkdir(parents=True, exist_ok=True)
        mesh_file.write_text(json.dumps(fabricated_mesh_manifest(airframe, taller=taller)),
                             encoding="utf-8")
        run_dir = tmp_path / label
        fabricate_run(run_dir, mesh_file=mesh_file)
        manifest = manifest_of(run_dir)
        cited = manifest["assets"]["mesh_manifest"]
        assert cited["sha256"] == hashlib.sha256(mesh_file.read_bytes()).hexdigest()
        check = verify_mask_vs_geometry(manifest, run_dir)
        if taller == 1.0:
            assert check.status == PASS, check.detail
        else:
            assert check.status == FAIL and check.failure == "annotation.mask_offset", check.detail
            assert "mask extent" in check.detail
            assert "mesh manifest version 3 measured extent" in check.detail
            assert MESH_PATH in check.detail
    # Without the file under the verifier's root the citation is not
    # honoured and the airframe block is the hull (the run above passes
    # again, and says so in the basis).
    monkeypatch.setattr(verify_module, "_REPO", tmp_path / "elsewhere")
    check = verify_mask_vs_geometry(manifest_of(tmp_path / "taller"), tmp_path / "taller")
    assert check.status == PASS, check.detail


# -- what is NOT claimed, pinned ----------------------------------------------------

def test_traffic_placement_is_producer_trusted_and_says_so(clean_run):
    """The traffic aircraft's placement is the record's bbox_3d_camera
    (the producer's solved track) both in this fixture's paint and in
    the verifier's reference, so a placement error moves both together
    and no gate sees it. That is stated in the geometry's basis, on
    every traffic detail, rather than claimed away."""
    from core.capture.verify import _object_geometry, axes_from_quat

    manifest = manifest_of(clean_run)
    record = manifest["frames"][0]
    entry = next(o for o in manifest["objects"] if o["role"] == "traffic")
    geometry, why = _object_geometry(manifest, record, entry,
                                     axes_from_quat(record["quaternion_wxyz"]))
    assert geometry is not None, why
    assert "bbox_3d_camera" in geometry["basis"]
    assert "not independently re-derived" in geometry["basis"]
    primary = next(o for o in manifest["objects"] if o["role"] == "primary")
    geometry, _ = _object_geometry(manifest, record, primary,
                                   axes_from_quat(record["quaternion_wxyz"]))
    assert "the frame's aircraft state through the verifier's own rotation" in geometry["basis"]
