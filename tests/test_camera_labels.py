"""Phase 10, package 2: ground-truth labels per frame, from geometry alone.

The label is what a model trains against; a label that describes a
different aircraft, or a different place in the image, is worse than no
label. So: the airframe numbers come from the flown FDM's own XML
wherever it has them (checked here against three figures from nowhere
near this code), every stated number carries a source, and the labels
are checked against hand arithmetic and against the verifier's own
independent reprojection -- and shown to FAIL when corrupted.
"""

import copy
import json
import math

import pytest

from core.capture.airframe import (
    KEYPOINT_NAMES, AirframeLabelError, load_airframe, structural_to_body,
)
from core.capture.labels import (
    EARTH_RADIUS_M, camera_axes, frame_labels, horizon_dip_deg,
)
from core.capture.manifest import (
    MANIFEST_VERSION, SUPPORTED_MANIFEST_VERSIONS, build_capture_manifest,
    read_capture_manifest, write_capture_manifest, write_frame_sidecars,
)
from core.capture.poses import euler_to_quat, solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, NOT_RUN, PASS, verify_keypoints_in_box, verify_label_files,
    verify_labels, verify_mask_containment, verify_depth_range,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


# -- the airframe: cited numbers, not copied ones ---------------------------

def test_structural_to_body_mapping_against_the_fdm_s_own_geometry():
    """Three figures that come from nowhere near this code: the c172p's
    wingtips must land at +-half its <wingspan>, the A320's likewise, and
    the A320's nose-to-tail must be its overall length."""
    c172 = load_airframe("c172p")
    assert c172.keypoints["left_wingtip"].body_m[1] == pytest.approx(
        -c172.span_m / 2.0, abs=0.02)
    assert c172.keypoints["right_wingtip"].body_m[1] == pytest.approx(
        c172.span_m / 2.0, abs=0.02)
    a320 = load_airframe("A320")
    assert a320.keypoints["left_wingtip"].body_m[1] == pytest.approx(
        -a320.span_m / 2.0, abs=0.02)
    nose_to_tail = (a320.keypoints["nose"].body_m[0]
                    - a320.keypoints["tail"].body_m[0])
    assert nose_to_tail == pytest.approx(37.5, abs=0.1)     # type: 37.57 m
    # Gear is below the CG (z down positive), tips near the wing.
    assert c172.keypoints["left_main_gear"].body_m[2] > 0.0
    assert a320.keypoints["nose_gear"].body_m[0] > 0.0        # ahead of CG


def test_structural_frame_conversion_is_the_documented_one():
    # x aft -> forward flips; y stays; z up -> down flips; inches -> m.
    body = structural_to_body((100.0, 39.3701, 0.0), (0.0, 0.0, 39.3701))
    assert body == pytest.approx((-2.54, 1.0, 1.0))


def test_every_keypoint_carries_a_source_and_a_basis():
    for aircraft in ("B747", "c172p", "A320"):
        airframe = load_airframe(aircraft)
        assert set(airframe.keypoints) == set(KEYPOINT_NAMES), aircraft
        for keypoint in airframe.keypoints.values():
            assert keypoint.source and keypoint.basis in (
                "fdm", "fdm-approximation", "estimate")
        assert airframe.dimensions_source
        assert airframe.config_sha256 and airframe.fdm_xml_sha256


def test_the_b747_s_nose_and_tail_are_labelled_estimates():
    """The B747 FDM carries no structural extremities, so its nose and
    tail are placed by an argument from a cited document -- and the
    manifest must say so rather than dress them as measured."""
    airframe = load_airframe("B747")
    assert airframe.keypoints["nose"].basis == "estimate"
    assert airframe.keypoints["tail"].basis == "estimate"
    assert airframe.keypoints["nose_gear"].basis == "fdm"
    assert airframe.keypoints["left_wingtip"].basis == "fdm-approximation"
    assert (airframe.keypoints["nose"].body_m[0]
            - airframe.keypoints["tail"].body_m[0]) == pytest.approx(
        airframe.length_m, abs=0.01)


def test_an_airframe_with_no_stated_geometry_refuses_by_name():
    with pytest.raises(AirframeLabelError, match="camera.labels") as info:
        load_airframe("DHC6")            # config exists, no labels block
    assert "labels" in str(info.value)
    with pytest.raises(AirframeLabelError, match="no aircraft config"):
        load_airframe("global5000")


def test_a_keypoint_naming_a_contact_the_fdm_lacks_refuses(tmp_path):
    import pathlib
    real = json.loads(pathlib.Path("assets/aircraft_config/c172p.json")
                      .read_text(encoding="utf-8"))
    real["labels"]["keypoints"]["tail"] = {"fdm_contact": "NO_SUCH_POINT"}
    (tmp_path / "c172p.json").write_text(json.dumps(real), encoding="utf-8")
    with pytest.raises(AirframeLabelError, match="NO_SUCH_POINT"):
        load_airframe("c172p", config_dir=tmp_path)


def test_a_stated_point_without_a_source_refuses(tmp_path):
    import pathlib
    real = json.loads(pathlib.Path("assets/aircraft_config/B747.json")
                      .read_text(encoding="utf-8"))
    del real["labels"]["keypoints"]["nose"]["source"]
    (tmp_path / "B747.json").write_text(json.dumps(real), encoding="utf-8")
    with pytest.raises(AirframeLabelError, match="no source"):
        load_airframe("B747", config_dir=tmp_path)


def test_the_box_is_the_overall_extents_from_the_gear_up():
    airframe = load_airframe("A320")
    box = airframe.box_body_m()
    assert box["forward"] == (airframe.keypoints["tail"].body_m[0],
                              airframe.keypoints["nose"].body_m[0])
    assert box["right"] == (-airframe.span_m / 2.0, airframe.span_m / 2.0)
    bottom = max(k.body_m[2] for n, k in airframe.keypoints.items()
                 if n.endswith("_gear"))
    assert box["down"] == (bottom - airframe.height_m, bottom)
    assert len(airframe.box_corners_body_m()) == 8


# -- the label geometry, by hand -------------------------------------------

def level_camera_record():
    """A level camera at the origin, 1000 m up, facing north; 35 mm on
    a 36 x 24 mm sensor at 1280 x 720."""
    return {"position_north_m": 0.0, "position_east_m": 0.0,
            "position_alt_m": 1000.0,
            "quaternion_wxyz": list(euler_to_quat(0.0, 0.0, 0.0)),
            "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0,
            "width_px": 1280, "height_px": 720,
            "fx_px": 1280.0 / 36.0 * 35.0, "fy_px": 1280.0 / 36.0 * 35.0,
            "principal_point_px": [640.0, 360.0]}


def test_labels_match_hand_arithmetic():
    record = level_camera_record()
    state = {"north_m": 1000.0, "east_m": 0.0, "alt_m": 1000.0,
             "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
    airframe = load_airframe("B747")
    labels = frame_labels(record, state, airframe, terrain_elevation_m=0.0)
    fx = record["fx_px"]
    # The CG sits on the principal point at 1000 m.
    assert labels["bbox_3d_camera"]["cg_m"] == pytest.approx([0.0, 0.0, 1000.0])
    # The nose is 33.71 m further north: deeper, not displaced.
    nose = labels["keypoints"]["nose"]
    assert (nose["u"], nose["v"]) == pytest.approx((640.0, 360.0))
    assert nose["depth_m"] == pytest.approx(1000.0 + airframe.keypoints["nose"].body_m[0])
    # Wingtips +-span/2 abeam, 1.27 m aft: +-(32.23 * fx / 1001.27) px.
    half = airframe.span_m / 2.0
    # The tip sits 1.27 m AFT of the CG (body x negative): nearer.
    depth = 1000.0 + airframe.keypoints["left_wingtip"].body_m[0]
    assert labels["keypoints"]["left_wingtip"]["u"] == pytest.approx(
        640.0 - half * fx / depth, abs=0.01)
    assert labels["keypoints"]["right_wingtip"]["u"] == pytest.approx(
        640.0 + half * fx / depth, abs=0.01)
    # Wholly in frame: no truncation, and the clipped box IS the box.
    assert labels["in_frame"] and labels["truncation"] == 0.0
    assert labels["bbox_2d"] == labels["bbox_2d_unclipped"]
    # The gear hangs below the CG: below the image centre.
    assert labels["keypoints"]["nose_gear"]["v"] > 360.0
    # Body axes in camera coords: forward = camera z, right = camera x,
    # down = camera y.
    axes = labels["bbox_3d_camera"]["body_axes_in_camera"]
    assert axes[0] == pytest.approx([0.0, 0.0, 1.0], abs=1e-9)
    assert axes[1] == pytest.approx([1.0, 0.0, 0.0], abs=1e-9)
    assert axes[2] == pytest.approx([0.0, 1.0, 0.0], abs=1e-9)
    assert labels["bbox_3d_camera"]["extents_m"] == pytest.approx(
        [airframe.length_m, airframe.span_m, airframe.height_m])


def test_the_horizon_is_the_datum_plane_s_tangent_horizon():
    record = level_camera_record()
    state = {"north_m": 1000.0, "east_m": 0.0, "alt_m": 1000.0,
             "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
    labels = frame_labels(record, state, load_airframe("c172p"), 0.0)
    horizon = labels["horizon"]
    dip = math.degrees(math.acos(EARTH_RADIUS_M / (EARTH_RADIUS_M + 1000.0)))
    assert horizon["dip_deg"] == pytest.approx(dip)
    assert horizon["in_frame"]
    # A level camera: at the centre column the horizon ray has elevation
    # -dip exactly, so v = cy + fy*tan(dip). Off-centre the exact curve
    # is the conic y = tan(dip)*sqrt(1 + x^2) -- the image of the
    # constant-depression CONE -- which is what the polyline carries.
    fx = record["fx_px"]
    t = math.tan(math.radians(dip))
    for u, v in horizon["polyline_px"]:
        x = (u - 640.0) / fx
        assert v == pytest.approx(360.0 + fx * t * math.sqrt(1.0 + x * x),
                                  abs=1e-6)
    centre = [v for u, v in horizon["polyline_px"] if abs(u - 640.0) < 1e-9]
    assert centre and centre[0] == pytest.approx(360.0 + fx * t, abs=1e-6)
    # The fitted line is level (symmetric curve) and its stated worst
    # deviation is the conic's sag at the edges: fx*t*(sqrt(1+x^2)-1).
    a, b, c = horizon["line_abc"]
    assert abs(a) < 1e-9 and abs(b) == pytest.approx(1.0)
    edge = 640.0 / fx
    sag = fx * t * (math.sqrt(1.0 + edge * edge) - 1.0)
    assert 0.0 < horizon["line_max_deviation_px"] <= sag + 1e-6
    assert horizon["line_max_deviation_px"] > 0.5 * sag
    # From the datum itself there is no dip.
    assert horizon_dip_deg(0.0) == 0.0
    # Looking straight up, the horizon is out of frame and says so.
    up = dict(record, quaternion_wxyz=list(euler_to_quat(0.0, 89.0, 0.0)),
              pitch_deg=89.0)
    assert not frame_labels(up, state, load_airframe("c172p"), 0.0)[
        "horizon"]["in_frame"]


def test_truncation_and_out_of_frame():
    record = level_camera_record()
    airframe = load_airframe("B747")
    # Far off to the right: wholly out of frame.
    away = {"north_m": 1000.0, "east_m": 5000.0, "alt_m": 1000.0,
            "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
    labels = frame_labels(record, away, airframe, 0.0)
    assert labels["bbox_2d"] is None and not labels["in_frame"]
    assert labels["truncation"] == 1.0
    assert labels["bbox_2d_unclipped"] is not None
    # Straddling the right edge: partly truncated.
    # The CG on the right image edge: u = cx + fx * east / north -> east.
    edge_u = (1280.0 - 640.0) * 1000.0 / record["fx_px"]
    edge = dict(away, east_m=edge_u)
    labels = frame_labels(record, edge, airframe, 0.0)
    assert labels["in_frame"] and 0.0 < labels["truncation"] < 1.0
    assert labels["bbox_2d"][2] == 1280.0
    # Behind the camera: a pinhole cannot bound it, and the label says so.
    behind = dict(away, north_m=-1000.0, east_m=0.0)
    labels = frame_labels(record, behind, airframe, 0.0)
    assert labels["bbox_2d_unclipped"] is None and labels["truncation"] is None
    assert not labels["in_frame"]
    assert labels["keypoints"]["nose"]["u"] is None
    assert labels["keypoints"]["nose"]["depth_m"] < 0.0


def test_a_banked_aircraft_s_wingtips_move_in_v():
    record = level_camera_record()
    airframe = load_airframe("A320")
    level = {"north_m": 1000.0, "east_m": 0.0, "alt_m": 1000.0,
             "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
    banked = dict(level, roll_deg=30.0)
    a = frame_labels(record, level, airframe, 0.0)["keypoints"]
    b = frame_labels(record, banked, airframe, 0.0)["keypoints"]
    # Right wing down (positive roll): right tip lower in the image, left
    # tip higher; both narrower in u by cos(30).
    assert b["right_wingtip"]["v"] > a["right_wingtip"]["v"]
    assert b["left_wingtip"]["v"] < a["left_wingtip"]["v"]
    # Roll about body x takes (y, z) -> (y cos - z sin, ...): the tip's
    # small z-offset enters the lateral offset too, so the exact factor
    # is (y cos - z sin) / y, not cos alone.
    y, z = airframe.keypoints["right_wingtip"].body_m[1:]
    phi = math.radians(30.0)
    factor = (y * math.cos(phi) - z * math.sin(phi)) / y
    assert abs(b["right_wingtip"]["u"] - 640.0) == pytest.approx(
        abs(a["right_wingtip"]["u"] - 640.0) * factor, rel=1e-6)


def test_camera_axes_agree_with_the_verifier_s_independent_expansion():
    from core.capture.verify import axes_from_quat

    for angles in ((0.0, 0.0, 0.0), (10.0, -20.0, 135.0), (-45.0, 5.0, 300.0)):
        q = euler_to_quat(*angles)
        for mine, theirs in zip(camera_axes(q), axes_from_quat(q)):
            assert mine == pytest.approx(theirs, abs=1e-12)


# -- the manifest ---------------------------------------------------------

def counted(preset, camera_id, aircraft="B747", count=8):
    camera = CameraSpec.defaulted(camera_id=camera_id, preset=preset,
                                  aircraft=aircraft)
    camera.set("capture_count", count, frm="test")
    return camera


def manifest_for(aircraft="B747"):
    prompt = {"B747": "fly the 747 at 10000 ft and 280 kt",
              "c172p": "fly the c172p at 3000 ft and 100 kt",
              "A320": "fly the A320 at 10000 ft and 250 kt"}[aircraft]
    spec = compile_prompt(prompt)
    spec.cameras = [counted("chase", "chase0", aircraft),
                    counted("tower", "tower0", aircraft)]
    columns = make_columns(duration_s=10.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                  output_digest="0" * 64,
                                  scene={"key": "flat", "terrain": None})


@pytest.mark.parametrize("aircraft", ["B747", "c172p", "A320"])
def test_every_frame_of_every_labelled_airframe_carries_labels(aircraft):
    manifest = manifest_for(aircraft)
    assert manifest["manifest_version"] == MANIFEST_VERSION == 5
    assert manifest["airframe"]["aircraft"] == aircraft
    assert set(k["name"] for k in manifest["airframe"]["keypoints"]) == set(KEYPOINT_NAMES)
    assert manifest["label_conventions"]["body_frame"].startswith("x forward")
    for record in manifest["frames"]:
        labels = record["labels"]
        for key in ("bbox_2d", "bbox_2d_unclipped", "truncation", "in_frame",
                    "bbox_3d_camera", "keypoints", "horizon"):
            assert key in labels, key
        assert set(labels["keypoints"]) == set(KEYPOINT_NAMES)
        assert len(labels["bbox_3d_camera"]["corners_m"]) == 8
    # The chase camera looks at the aircraft: it is in frame throughout.
    chase = [f for f in manifest["frames"] if f["camera_id"] == "chase0"]
    assert all(f["labels"]["in_frame"] for f in chase)


def test_the_manifest_hashes_the_assets_behind_the_labels():
    manifest = manifest_for("c172p")
    assets = manifest["assets"]
    assert assets["aircraft_config"]["sha256"] == manifest["airframe"]["config_sha256"]
    assert assets["fdm_xml"]["sha256"] == manifest["airframe"]["fdm_xml_sha256"]
    assert len(assets["fdm_xml"]["sha256"]) == 64
    # No mesh imported on this machine: null WITH a reason, not a hash of nothing.
    if assets["mesh_manifest"]["sha256"] is None:
        assert "no mesh imported" in assets["mesh_manifest"]["note"]


def test_an_unlabelled_airframe_refuses_the_manifest_by_name():
    spec = compile_prompt("fly the 737 at 10000 ft and 280 kt")
    spec.cameras = [counted("chase", "chase0", "737")]
    columns = make_columns(duration_s=4.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    with pytest.raises(AirframeLabelError, match="camera.labels"):
        build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                               output_digest="0" * 64)


def test_version_4_still_reads_and_its_label_checks_say_not_run(tmp_path):
    manifest = manifest_for()
    manifest["manifest_version"] = 4
    for record in manifest["frames"]:
        del record["labels"]
    del manifest["airframe"]
    path = write_capture_manifest(manifest, tmp_path)
    reread = read_capture_manifest(path)
    assert reread["manifest_version"] == 4
    assert verify_labels(reread).status == NOT_RUN
    assert verify_keypoints_in_box(reread).status == NOT_RUN
    assert SUPPORTED_MANIFEST_VERSIONS == (3, 4, 5)


def test_sidecars_carry_the_airframe_and_the_labels(tmp_path):
    manifest = manifest_for()
    write_frame_sidecars(manifest, tmp_path)
    record = manifest["frames"][0]
    sidecar = json.loads((tmp_path / (record["file"][:-4] + ".json"))
                         .read_text(encoding="utf-8"))
    assert sidecar["frame"]["labels"]["keypoints"]["nose"]["depth_m"] == \
        record["labels"]["keypoints"]["nose"]["depth_m"]
    assert sidecar["context"]["airframe"]["aircraft"] == "B747"
    assert "corner_order" in sidecar["context"]["label_conventions"]


# -- the verifier: each label check shown to fail -----------------------------

@pytest.fixture
def labelled():
    return manifest_for("A320")


def test_the_clean_labels_pass_their_offline_checks(labelled):
    assert verify_labels(labelled).status == PASS
    assert verify_keypoints_in_box(labelled).status == PASS
    # No engine outputs on this machine: NOT RUN by name, never a pass.
    assert verify_label_files(labelled, None).status == NOT_RUN
    assert verify_mask_containment(labelled, None).status == NOT_RUN
    assert verify_depth_range(labelled, None).status == NOT_RUN


def test_a_shifted_box_is_caught(labelled):
    bad = copy.deepcopy(labelled)
    box = bad["frames"][3]["labels"]["bbox_2d_unclipped"]
    box[0] += 2.0; box[2] += 2.0
    check = verify_labels(bad)
    assert check.status == FAIL
    assert "bbox" in check.detail


def test_a_moved_keypoint_is_caught_twice(labelled):
    """Moved by ten pixels it disagrees with the reprojection AND, moved
    far enough, it leaves its own box."""
    bad = copy.deepcopy(labelled)
    bad["frames"][0]["labels"]["keypoints"]["nose"]["u"] += 10.0
    check = verify_labels(bad)
    assert check.status == FAIL and "nose u" in check.detail
    far = copy.deepcopy(labelled)
    far["frames"][0]["labels"]["keypoints"]["nose"]["u"] += 5000.0
    assert verify_keypoints_in_box(far).status == FAIL


def test_a_keypoint_dropped_from_the_labels_is_caught(labelled):
    bad = copy.deepcopy(labelled)
    del bad["frames"][0]["labels"]["keypoints"]["tail"]
    check = verify_labels(bad)
    assert check.status == FAIL and "tail" in check.detail


def test_an_airframe_block_that_disagrees_with_the_labels_is_caught(labelled):
    """The labels were made from one airframe; a manifest whose airframe
    block quietly describes another (a longer nose) cannot pass."""
    bad = copy.deepcopy(labelled)
    for keypoint in bad["airframe"]["keypoints"]:
        if keypoint["name"] == "nose":
            keypoint["body_m"][0] += 3.0
    assert verify_labels(bad).status == FAIL


def _engine_outputs(run_dir, manifest, camera, consistent=True,
                    depth_ok=True):
    """Fabricate what the render commandlet will write: an instance
    mask (aircraft = 1) and a 16-bit depth PNG per frame, declared in
    the camera's render.json. `consistent` puts the mask inside the
    label box; `depth_ok` puts the depth inside the 3-D box's span."""
    import numpy as np
    from PIL import Image

    folder = run_dir / "frames" / camera
    folder.mkdir(parents=True)
    scale = 0.1
    records = []
    for record in manifest["frames"]:
        if record["camera_id"] != camera:
            continue
        name = record["file"].split("/")[-1]
        w, h = int(record["width_px"]), int(record["height_px"])
        mask = np.zeros((h, w), dtype=np.uint8)
        depth = np.full((h, w), 65535, dtype=np.uint16)
        box = record["labels"]["bbox_2d"]
        zs = [c[2] for c in record["labels"]["bbox_3d_camera"]["corners_m"]]
        if box is not None:
            u0, v0 = int(math.ceil(box[0])), int(math.ceil(box[1]))
            u1, v1 = int(math.floor(box[2])) - 1, int(math.floor(box[3])) - 1
            if not consistent:
                # Paint the aircraft well outside its own box.
                u0, u1 = max(0, u0 - 300), max(1, u1 - 300)
            mask[v0:v1 + 1, u0:u1 + 1] = 1
            z = (sum(zs) / len(zs)) if depth_ok else (max(zs) + 500.0)
            depth[v0:v1 + 1, u0:u1 + 1] = int(z / scale)
        Image.fromarray(mask, mode="L").save(folder / f"{name[:-4]}_mask.png")
        Image.fromarray(mask, mode="L").save(folder / f"{name[:-4]}_class.png")
        Image.fromarray(depth, mode="I;16").save(folder / f"{name[:-4]}_depth.png")
        records.append({"frame": name, "labels": {
            "mask": f"{name[:-4]}_mask.png",
            "class_mask": f"{name[:-4]}_class.png",
            "depth": f"{name[:-4]}_depth.png",
            "depth_scale_m": scale}})
    (folder / "render.json").write_text(
        json.dumps({"frames": len(records), "frame_records": records}),
        encoding="utf-8")
    return folder


def test_consistent_engine_masks_and_depth_pass(tmp_path, labelled):
    write_capture_manifest(labelled, tmp_path)
    _engine_outputs(tmp_path, labelled, "chase0")
    assert verify_label_files(labelled, tmp_path).status == PASS
    assert verify_mask_containment(labelled, tmp_path).status == PASS
    assert verify_depth_range(labelled, tmp_path).status == PASS


def test_a_mask_outside_the_label_box_is_caught(tmp_path, labelled):
    _engine_outputs(tmp_path, labelled, "chase0", consistent=False)
    check = verify_mask_containment(labelled, tmp_path)
    assert check.status == FAIL, check.detail


def test_depth_outside_the_box_span_is_caught(tmp_path, labelled):
    _engine_outputs(tmp_path, labelled, "chase0", depth_ok=False)
    check = verify_depth_range(labelled, tmp_path)
    assert check.status == FAIL, check.detail


def test_a_declared_label_file_that_is_missing_is_caught(tmp_path, labelled):
    folder = _engine_outputs(tmp_path, labelled, "chase0")
    victim = next(folder.glob("*_depth.png"))
    victim.unlink()
    check = verify_label_files(labelled, tmp_path)
    assert check.status == FAIL and victim.name in check.detail


def test_an_engine_mask_where_the_label_says_nothing_is_in_frame(tmp_path,
                                                                labelled):
    """The mask shows an aircraft; the label says none is in frame. One
    of them is wrong, and the check must not average them away."""
    bad = copy.deepcopy(labelled)
    _engine_outputs(tmp_path, bad, "chase0")
    bad["frames"][0]["labels"]["bbox_2d"] = None
    bad["frames"][0]["labels"]["in_frame"] = False
    assert verify_mask_containment(bad, tmp_path).status == FAIL


def test_the_full_verification_runs_the_label_checks(tmp_path, labelled):
    from core.capture.verify import verify_run

    write_capture_manifest(labelled, tmp_path)
    names = [c.name for c in verify_run(tmp_path).checks]
    for name in ("label_geometry", "keypoints_in_box", "label_files",
                 "mask_containment", "depth_range"):
        assert name in names
