"""Phase 2, packages B + C: object identity, the per-frame per-object
record, the engine bundle attached with numpy, and the second aircraft.

Every safeguard here is shown to FAIL when removed (scripts/
mutation_check.sh): the primary's int_id, the >255 refusal, the tight
box, the visible fraction. The bundle is FABRICATED to the declared
layout (an 8-bit ID png, a float32 depth file, alone pngs, a render.json
that names them) -- no engine exists in this container, and the test
says so rather than pretending a render happened.
"""

import copy
import json
import math

import numpy as np
import pytest
from PIL import Image

from core.capture.airframe import load_airframe
from core.capture.labels import (
    ENGINE_LABEL_KEYS, atmospheric_transmittance, attach_engine_labels,
    hull_box_body_m, measure_object, read_depth_f32,
)
from core.capture.manifest import (
    MANIFEST_VERSION, SIDECAR_CONTEXT_KEYS, SUPPORTED_MANIFEST_VERSIONS,
    build_capture_manifest, read_capture_manifest, simulation_digest,
    write_capture_manifest, write_frame_sidecars,
)
from core.capture.objects import (
    MAX_INT_ID, ObjectIdentityError, TaxonomyError, aircraft_objects,
    assign_int_ids, classes_sentence, compose_objects, object_entries,
    objects_block, resolve_ids,
)
from core.capture.poses import (
    PoseSolveError, aircraft_local_track, cg_actor_cm, solve_pose_track,
    solve_traffic_track, traffic_card_block, traffic_state,
)
from core.capture.schedule import solve_schedule
from core.capture.schema import validate_manifest
from core.nl.compiler import compile_prompt
from core.scenario.blocks import TrafficSpec
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


def spec_with(traffic=(), aircraft="B747", count=4):
    prompt = {"B747": "fly the 747 at 10000 ft and 280 kt",
              "c172p": "fly the c172p at 3000 ft and 100 kt",
              "A320": "fly the A320 at 10000 ft and 250 kt"}[aircraft]
    spec = compile_prompt(prompt)
    spec.traffic = [TrafficSpec.defaulted(name, kind) for name, kind in traffic]
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase",
                                  aircraft=aircraft)
    camera.set("capture_count", count, frm="test")
    spec.cameras = [camera]
    return spec


def manifest_with(spec, columns=None, **kwargs):
    columns = columns or make_columns(duration_s=6.0)
    objects = compose_objects(spec)
    traffic = [o for o in objects if o.role == "traffic"]
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    traffic_tracks = [
        solve_traffic_track(columns, str(e.track.value), float(e.range_m.value),
                            FRAME, o.id)
        for e, o in zip(spec.traffic, traffic)]
    return build_capture_manifest(
        spec, columns, FRAME, tracks, schedules, output_digest="0" * 64,
        scene={"key": "flat", "terrain": None}, traffic_tracks=traffic_tracks,
        **kwargs)


# -- identity ---------------------------------------------------------------

def test_composition_is_stable_and_the_primary_is_always_int_id_1():
    """The same spec composes the same list; a spec differing only in
    cameras, and a second composition, give identical ids (contracts
    §2.3). The primary is first with int_id 1 so every Phase 10 reader
    (verify.AIRCRAFT_INSTANCE_ID = 1) stays true."""
    spec = spec_with([("A320", "crossing"), ("c172p", "formation")])
    a = objects_block(compose_objects(spec))
    b = objects_block(compose_objects(spec))
    assert a == b
    other = spec_with([("A320", "crossing"), ("c172p", "formation")], count=9)
    other.cameras[0].set("focal_length_mm", 85.0, frm="test")
    assert objects_block(compose_objects(other)) == a
    assert [o["int_id"] for o in a] == [1, 2, 3, 4]
    assert [o["id"] for o in a] == ["aircraft:B747:0", "aircraft:A320:1",
                                    "aircraft:c172p:2", "terrain"]
    assert a[0]["role"] == "primary" and a[0]["int_id"] == 1
    assert [o["role"] for o in a] == ["primary", "traffic", "traffic", "scene"]
    assert [o["class_id"] for o in a] == [1, 1, 1, 2]
    assert a[0]["licence"] == "GPL-2.0" and a[-1]["licence"] is None
    assert all(o["labelled"] and o["in_scene"] for o in a)
    # A headless clone honestly has no mesh: null, never a hash of nothing.
    assert a[0]["mesh_sha256"] is None or len(a[0]["mesh_sha256"]) == 64
    for entry in a:
        assert set(entry) == {"id", "int_id", "class", "class_id", "instance",
                              "role", "mesh_sha256", "licence", "in_scene",
                              "labelled"}


def test_a_scene_needing_more_than_255_ids_refuses_by_name():
    entries = [dict(object_entries(spec_with())[0], id=f"building:{i}",
                    class_name="building", class_id=3, instance=i, role="scene")
               for i in range(MAX_INT_ID + 1)]
    with pytest.raises(ObjectIdentityError, match="annotation.identity") as info:
        assign_int_ids(entries)
    assert info.value.constraint == "annotation.identity"
    assert "256" in str(info.value)
    # Exactly 255 is fine; the 8-bit stencil carries it.
    assert assign_int_ids(entries[:MAX_INT_ID])[-1].int_id == MAX_INT_ID
    # One id composed twice is refused under the same name.
    twice = [entries[0], dict(entries[0])]
    with pytest.raises(ObjectIdentityError, match="composed twice"):
        assign_int_ids(twice)


def test_a_class_the_taxonomy_does_not_name_refuses_by_name():
    spec = spec_with()
    spec.taxonomy.set("classes", ["terrain", "building"], frm="test")
    with pytest.raises(TaxonomyError, match="taxonomy.classes"):
        compose_objects(spec)
    spec.taxonomy.set("classes", ["terrain", "aircraft"], frm="test")
    objects = compose_objects(spec)
    assert objects[0].class_id == 2 and objects[-1].class_id == 1
    assert classes_sentence(["terrain", "aircraft"]) == "0 sky, 1 terrain, 2 aircraft"


def test_int_ids_resolve_to_ids_and_unknown_ones_stay_visible():
    objects = compose_objects(spec_with([("A320", "crossing")]))
    assert resolve_ids([3, 2], objects) == ["terrain", "aircraft:A320:1"]
    assert resolve_ids([7], objects) == ["int_id:7"]
    assert [o.id for o in aircraft_objects(objects)] == ["aircraft:B747:0",
                                                        "aircraft:A320:1"]


# -- the traffic track solver ------------------------------------------------

def test_a_crossing_track_crosses_at_the_stated_range():
    """At the run's midpoint the traffic sits exactly range_m ahead of
    the primary along its heading, heading 90 deg across it, at its
    altitude, and it moves at the primary's mean ground speed."""
    columns = make_columns(duration_s=10.0, speed_mps=120.0,
                           heading=lambda t: 30.0)
    primary = aircraft_local_track(columns, FRAME)
    track = solve_traffic_track(columns, "crossing", 400.0, FRAME, "aircraft:A320:1")
    assert track.digest() == solve_traffic_track(
        columns, "crossing", 400.0, FRAME, "aircraft:A320:1").digest()
    mid = len(primary) // 2
    p = primary[mid]
    dn = track.north_m[mid] - p["north_m"]
    de = track.east_m[mid] - p["east_m"]
    assert math.hypot(dn, de) == pytest.approx(400.0, abs=1e-6)
    # Straight AHEAD along the primary's heading (30 deg).
    assert math.degrees(math.atan2(de, dn)) == pytest.approx(30.0, abs=1e-6)
    assert track.alt_m[mid] == p["alt_m"]
    assert (track.yaw_deg[mid] - p["heading_deg"]) % 360.0 == pytest.approx(90.0)
    assert track.roll_deg[mid] == 0.0 and track.pitch_deg[mid] == 0.0
    # The traffic's own speed is the primary's mean ground speed IN THE
    # FRAME (the synthetic track's degrees-to-metres scale is not the
    # UTM frame's, so this is not exactly 120 m/s, and must not be
    # asserted as such).
    length = sum(math.hypot(b["north_m"] - a["north_m"], b["east_m"] - a["east_m"])
                 for a, b in zip(primary, primary[1:]))
    mean_speed = length / (primary[-1]["t_s"] - primary[0]["t_s"])
    dt = track.t[mid + 1] - track.t[mid]
    step = math.hypot(track.north_m[mid + 1] - track.north_m[mid],
                      track.east_m[mid + 1] - track.east_m[mid])
    assert step / dt == pytest.approx(mean_speed, rel=1e-6)
    assert mean_speed == pytest.approx(120.0, rel=0.01)
    # It moves ACROSS the heading: the along-heading distance stays 400.
    for i in (0, mid // 2, -1):
        n, e = track.north_m[i] - p["north_m"], track.east_m[i] - p["east_m"]
        along = n * math.cos(math.radians(30.0)) + e * math.sin(math.radians(30.0))
        assert along == pytest.approx(400.0, abs=1e-6)


def test_formation_flies_abeam_and_overtaking_passes_at_the_midpoint():
    columns = make_columns(duration_s=8.0, heading=lambda t: 0.0,
                           roll=lambda t: 12.0)
    primary = aircraft_local_track(columns, FRAME)
    formation = solve_traffic_track(columns, "formation", 250.0, FRAME, "f")
    for i in (0, 3, -1):
        assert formation.east_m[i] - primary[i]["east_m"] == pytest.approx(250.0)
        assert formation.north_m[i] == pytest.approx(primary[i]["north_m"])
        assert formation.roll_deg[i] == 12.0          # copies the attitude
    overtaking = solve_traffic_track(columns, "overtaking", 300.0, FRAME, "o")
    n = len(primary)
    assert overtaking.north_m[0] - primary[0]["north_m"] == pytest.approx(-300.0)
    assert overtaking.north_m[-1] - primary[-1]["north_m"] == pytest.approx(300.0)
    mid = n // 2
    assert abs(overtaking.north_m[mid] - primary[mid]["north_m"]) < 1.0
    assert overtaking.east_m[mid] - primary[mid]["east_m"] == pytest.approx(300.0)
    assert overtaking.roll_deg[mid] == 0.0
    with pytest.raises(PoseSolveError, match="camera.poses"):
        solve_traffic_track(columns, "loop", 300.0, FRAME, "x")
    with pytest.raises(PoseSolveError, match="not positive"):
        solve_traffic_track(columns, "crossing", 0.0, FRAME, "x")
    state = traffic_state(formation, 2)
    assert set(state) == {"north_m", "east_m", "alt_m", "roll_deg",
                          "pitch_deg", "heading_deg"}


def test_the_card_block_carries_the_track_and_the_cg_in_the_actor_frame():
    spec = spec_with([("A320", "crossing")])
    objects = compose_objects(spec)
    columns = make_columns(duration_s=4.0)
    track = solve_traffic_track(columns, "crossing", 400.0, FRAME, objects[1].id)
    airframe = load_airframe("A320")
    block = traffic_card_block(track, spec.traffic[0], objects[1], FRAME,
                               airframe.cg_structural_in, None)
    assert block["id"] == "aircraft:A320:1" and block["int_id"] == 2
    assert block["track"] == "crossing" and block["range_m"] == 400.0
    assert block["mesh_manifest"] is None
    assert set(block["poses"]) == {"t_s", "north_m", "east_m", "alt_m",
                                   "yaw_deg", "pitch_deg", "roll_deg"}
    assert len(block["poses"]["t_s"]) == len(columns["t"])
    # The plugin's own structural -> actor mapping: x negated, y and z
    # kept, inches to cm. The B747's CG (1327, 0, -24) in is the number
    # the plugin logs, (-3370.6, 0, -61.0) cm.
    assert cg_actor_cm((1327.0, 0.0, -24.0)) == pytest.approx([-3370.58, 0.0, -60.96])
    assert block["cg_actor_cm"] == cg_actor_cm(airframe.cg_structural_in)
    assert block["track_digest"] == track.digest()


def test_the_run_card_carries_objects_taxonomy_and_traffic(tmp_path):
    from core.scenario.card import write_run_card

    spec = spec_with([("A320", "crossing")])
    objects = compose_objects(spec)
    path = write_run_card(
        spec, tmp_path / "card.json",
        objects=objects_block(objects), taxonomy=["aircraft", "terrain"],
        traffic=[{"id": objects[1].id, "int_id": 2, "poses": {"t_s": [0.0, 1.0]}}])
    card = json.loads(path.read_text(encoding="utf-8"))
    assert [o["int_id"] for o in card["objects"]] == [1, 2, 3]
    assert card["taxonomy"] == ["aircraft", "terrain"]
    assert card["traffic"][0]["id"] == "aircraft:A320:1"
    # Absent blocks stay absent: a card with none is byte-identical to
    # the shape every earlier phase wrote.
    plain = write_run_card(spec_with(), tmp_path / "plain.json")
    text = plain.read_text(encoding="utf-8")
    assert "objects" not in text and "traffic" not in text and "taxonomy" not in text


# -- manifest 6: the record shapes -------------------------------------------

def test_manifest_6_carries_objects_and_a_record_per_object():
    spec = spec_with([("A320", "crossing")])
    manifest = manifest_with(spec)
    assert manifest["manifest_version"] == MANIFEST_VERSION == 6
    assert SUPPORTED_MANIFEST_VERSIONS == (3, 4, 5, 6)
    assert [o["id"] for o in manifest["objects"]] == [
        "aircraft:B747:0", "aircraft:A320:1", "terrain"]
    assert manifest["taxonomy"][:2] == ["aircraft", "terrain"]
    traffic = manifest["traffic"][0]
    assert traffic["airframe"]["aircraft"] == "A320" and len(traffic["track_digest"]) == 64
    assert "wings level" in traffic["attitude_basis"]
    for key in ("objects", "taxonomy", "traffic"):
        assert key in SIDECAR_CONTEXT_KEYS
    for record in manifest["frames"]:
        entries = record["labels"]["objects"]
        assert [e["int_id"] for e in entries] == [1, 2, 3]
        primary, other, terrain = entries
        # The primary's entry IS the frame's labels, key for key.
        for key in ("bbox_2d", "bbox_2d_unclipped", "truncation", "in_frame",
                    "bbox_3d_camera", "keypoints", "horizon"):
            assert primary[key] == record["labels"][key], key
        assert primary["depth_projected_m"] == record["labels"]["bbox_3d_camera"]["cg_m"][2]
        # The traffic aircraft has its own box from its own airframe, no horizon.
        assert other["bbox_3d_camera"]["extents_m"][0] == pytest.approx(37.5, abs=0.1)
        assert other["horizon"] is None and set(other["keypoints"])
        assert other["class_id"] == 1
        # The terrain: nulls where a box has no meaning, not zeros.
        assert terrain["bbox_2d"] is None and terrain["bbox_3d_camera"] is None
        assert terrain["in_frame"] is None and terrain["class_id"] == 2
        assert any("no alone pass" in n for n in terrain["not_claimed"])
        for entry in entries:
            for key in ENGINE_LABEL_KEYS:
                assert entry[key] == ([] if key == "occluded_by" else None), key
            assert "no engine bundle" in entry["basis"]["engine"]
            assert entry["basis"]["bbox_2d_hull"]
            assert any(n.startswith("subpixel_mask_accuracy_beyond_range_m")
                       for n in entry["not_claimed"])
        # 1.0 with a stated basis when no visibility is stated -- not clear air.
        assert primary["atmospheric_transmittance"] == 1.0
        assert "NOT a measurement" in primary["basis"]["atmospheric_transmittance"]
    assert validate_manifest(manifest) == []
    # A spec with traffic and no tracks refuses: nothing to label.
    with pytest.raises(ValueError, match="traffic tracks"):
        columns = make_columns(duration_s=6.0)
        build_capture_manifest(spec, columns, FRAME,
                               [solve_pose_track(columns, c, FRAME) for c in spec.cameras],
                               [solve_schedule(columns, c, FRAME) for c in spec.cameras],
                               output_digest="0" * 64)


def test_the_taxonomy_leaves_the_simulation_identity_alone():
    spec = spec_with()
    other = spec_with()
    other.taxonomy.set("classes", ["aircraft", "terrain", "water"], frm="test")
    assert simulation_digest(spec) == simulation_digest(other)
    assert spec.digest() != other.digest()
    with_traffic = spec_with([("A320", "crossing")])
    assert simulation_digest(with_traffic) != simulation_digest(spec)


def test_the_hull_box_comes_from_a_measured_mesh_manifest_or_says_why():
    airframe = load_airframe("B747")
    box, basis = hull_box_body_m(None, airframe)
    assert box is None and "no mesh manifest" in basis
    box, basis = hull_box_body_m({"version": 2, "mesh_origin_actor_cm": [0, 0, 0]}, airframe)
    assert box is None and "version 2" in basis
    # A version-3 manifest: the B747 numbers NEXT.md gotcha 31 states,
    # mesh nose +29.80 m / tail -41.14 m about an origin at -2979.8 cm.
    manifest = {"version": 3, "mesh_origin_actor_cm": [-2979.8, 0.0, 13.9],
                "mesh_origin_basis": "measured from vertices",
                "mesh_extent_actor_m": {"x": [-41.14, 29.80], "y": [-32.2, 32.2],
                                        "z": [-2.94, 14.35]}}
    box, basis = hull_box_body_m(manifest, airframe)
    assert "measured from vertices" in basis
    # Forward extreme = origin + 29.80 m, then re-based on the CG, which
    # sits 33.71 m aft of the datum: the mesh nose lands at the label's
    # nose to the residual the gotcha measured.
    cg_x = -airframe.cg_structural_in[0] * 0.0254
    assert box["forward"][1] == pytest.approx(-29.798 + 29.80 - cg_x, abs=1e-3)
    assert box["forward"][1] == pytest.approx(airframe.keypoints["nose"].body_m[0], abs=0.01)
    assert box["right"] == pytest.approx((-32.2, 32.2))
    # Body z is DOWN: the mesh top (actor +14.35) is the smaller number.
    assert box["down"][0] < box["down"][1]
    spec = spec_with()
    manifest6 = manifest_with(spec, mesh_manifests={"B747": manifest})
    entry = manifest6["frames"][0]["labels"]["objects"][0]
    assert entry["bbox_2d_hull"] is not None and len(entry["bbox_2d_hull"]) == 4
    assert "version 3" in entry["basis"]["bbox_2d_hull"]


def test_transmittance_is_koschmieder_from_visibility_or_fog_density():
    value, basis = atmospheric_transmittance(1000.0, {"visibility_km": 3.912})
    assert value == pytest.approx(math.exp(-1.0)) and "Koschmieder" in basis
    value, basis = atmospheric_transmittance(2000.0, {"fog_density": 0.0025})
    assert value == pytest.approx(math.exp(-5.0)) and "fog_density" in basis
    value, basis = atmospheric_transmittance(2000.0, None)
    assert value == 1.0 and "NOT a measurement" in basis


def test_a_version_5_manifest_still_reads_and_its_objects_are_absent(tmp_path):
    manifest = manifest_with(spec_with())
    old = copy.deepcopy(manifest)
    old["manifest_version"] = 5
    for key in ("objects", "taxonomy", "traffic"):
        del old[key]
    for record in old["frames"]:
        del record["labels"]["objects"]
        del record["sensor"]["labels_sensor"]["objects"]
    write_capture_manifest(old, tmp_path)
    reread = read_capture_manifest(tmp_path / "capture_manifest.json")
    assert reread["manifest_version"] == 5 and "objects" not in reread
    # attach_engine_labels leaves it alone and says so.
    summary = attach_engine_labels(tmp_path)
    assert summary["attached"] == 0 and "no per-object records" in summary["note"]
    from core.capture.verify import verify_json_schema, verify_labels, PASS, NOT_RUN
    assert verify_labels(reread).status == PASS
    # v5 still has its own published schema; a v4 has none and is NOT RUN.
    assert verify_json_schema(reread).status == PASS
    reread["manifest_version"] = 4
    assert verify_json_schema(reread).status == NOT_RUN


# -- the engine bundle, fabricated to the declared layout ---------------------

def fabricate_bundle(run_dir, manifest, camera="chase0", occluder_rect=None,
                     alone_extra=8):
    """The bundle the commandlet writes, drawn with numpy: per frame an
    8-bit ID png (1 the primary, 2 the traffic, 3 the terrain below a
    horizon row), a float32 depth file, one alone png per aircraft
    (the primary's footprint grown by ``alone_extra`` px on the side
    the traffic covers), and a render.json naming every file. Returns
    the painted primary rectangle per frame."""
    folder = run_dir / "frames" / camera
    folder.mkdir(parents=True, exist_ok=True)
    objects = manifest["objects"]
    ids = {o["id"]: o["int_id"] for o in objects}
    painted = {}
    records = []
    for record in manifest["frames"]:
        if record["camera_id"] != camera:
            continue
        name = record["file"].split("/")[-1]
        stem = name[:-4]
        w, h = int(record["width_px"]), int(record["height_px"])
        mask = np.zeros((h, w), dtype=np.uint8)
        depth = np.full((h, w), np.inf, dtype=np.float32)
        # Terrain: everything below the horizon row.
        horizon = h * 2 // 3
        mask[horizon:, :] = ids["terrain"]
        depth[horizon:, :] = 5000.0
        # The primary: a rectangle at the record's own box centre.
        u0, v0, u1, v1 = (int(round(v)) for v in record["labels"]["bbox_2d"])
        u0, v0 = max(u0, 0), max(v0, 0)
        u1, v1 = min(u1, w), min(v1, h)
        mask[v0:v1, u0:u1] = ids["aircraft:B747:0"]
        depth[v0:v1, u0:u1] = 150.0
        alone_primary = np.zeros((h, w), dtype=np.uint8)
        alone_primary[v0:v1, u0:min(u1 + alone_extra, w)] = ids["aircraft:B747:0"]
        # The traffic: a small rectangle covering the primary's right
        # margin (so it occludes the primary's grown footprint).
        traffic_id = ids.get("aircraft:A320:1")
        alone_traffic = None
        if traffic_id is not None:
            t0, t1 = u1, min(u1 + alone_extra, w)
            mask[v0:v1, t0:t1] = traffic_id
            depth[v0:v1, t0:t1] = 120.0
            alone_traffic = np.zeros((h, w), dtype=np.uint8)
            alone_traffic[v0:v1, t0:t1] = traffic_id
        painted[name] = (u0, v0, u1, v1)
        Image.fromarray(mask).save(folder / f"{stem}_mask.png")
        Image.fromarray(mask).save(folder / f"{stem}_class.png")
        depth.astype("<f4").tofile(folder / f"{stem}_depth.f32")
        Image.fromarray(alone_primary).save(folder / f"{stem}_alone_1.png")
        declared = [{"int_id": 1, "alone_png": f"{stem}_alone_1.png"}]
        if alone_traffic is not None:
            Image.fromarray(alone_traffic).save(folder / f"{stem}_alone_{traffic_id}.png")
            declared.append({"int_id": traffic_id,
                             "alone_png": f"{stem}_alone_{traffic_id}.png"})
        records.append({"frame": name, "labels": {
            "mask": f"{stem}_mask.png", "class_mask": f"{stem}_class.png",
            "depth": f"{stem}_depth.png", "depth_f32": f"{stem}_depth.f32",
            "depth_scale_m": 0.1, "anti_aliasing": "none",
            "objects": declared}})
    (folder / "render.json").write_text(
        json.dumps({"frames": len(records), "frame_records": records}),
        encoding="utf-8")
    return painted


def test_attach_engine_labels_computes_boxes_visibility_and_depth(tmp_path):
    spec = spec_with([("A320", "crossing")])
    manifest = manifest_with(spec)
    write_capture_manifest(manifest, tmp_path)
    write_frame_sidecars(manifest, tmp_path)
    painted = fabricate_bundle(tmp_path, manifest, alone_extra=8)
    summary = attach_engine_labels(tmp_path)
    assert summary["attached"] == len(manifest["frames"]) and summary["written"]
    assert summary["objects"] == 3 * len(manifest["frames"])
    attached = read_capture_manifest(tmp_path / "capture_manifest.json")
    for record in attached["frames"]:
        name = record["file"].split("/")[-1]
        u0, v0, u1, v1 = painted[name]
        primary, traffic, terrain = record["labels"]["objects"]
        # The tight box is the painted rectangle, far edges one past the
        # last pixel, in the same continuous units as bbox_2d.
        assert primary["bbox_2d_tight"] == [float(u0), float(v0), float(u1), float(v1)]
        assert traffic["bbox_2d_tight"] == [float(u1), float(v0), float(u1 + 8), float(v1)]
        # Visible fraction = pixels / alone pixels: the primary's grown
        # footprint has 8 px more per row, all covered by the traffic.
        rows = v1 - v0
        assert primary["visible_fraction"] == pytest.approx(
            rows * (u1 - u0) / (rows * (u1 - u0 + 8)))
        assert primary["occluded_by"] == ["aircraft:A320:1"]
        assert traffic["visible_fraction"] == pytest.approx(1.0)
        assert traffic["occluded_by"] == []
        # Depth under the mask: painted constants.
        assert primary["depth_min_m"] == 150.0 and primary["depth_median_m"] == 150.0
        assert traffic["depth_median_m"] == 120.0
        # The terrain: a tight box (the rows below the horizon), depth,
        # but NO visible fraction -- there is no alone pass for it.
        assert terrain["bbox_2d_tight"][1] == float(record["height_px"] * 2 // 3)
        assert terrain["depth_median_m"] == 5000.0
        assert terrain["visible_fraction"] is None and terrain["occluded_by"] == []
        # Provenance: which files each number came from, and the counts.
        engine = primary["basis"]["engine"]
        assert engine["files"]["mask"].endswith("_mask.png")
        assert engine["files"]["depth"].endswith("_depth.f32")
        assert engine["files"]["alone_1"].endswith("_alone_1.png")
        assert engine["pixels"] == rows * (u1 - u0)
        assert engine["pixels_alone"] == rows * (u1 - u0 + 8)
        # The sidecar carries the completed record and the object list.
        sidecar = json.loads((tmp_path / (record["file"][:-4] + ".json"))
                             .read_text(encoding="utf-8"))
        assert sidecar["frame"]["labels"]["objects"][0]["bbox_2d_tight"] == \
            primary["bbox_2d_tight"]
        assert [o["int_id"] for o in sidecar["context"]["objects"]] == [1, 2, 3]
    assert validate_manifest(attached) == []
    # Attaching again is idempotent.
    again = attach_engine_labels(tmp_path)
    assert again["attached"] == summary["attached"]
    assert read_capture_manifest(tmp_path / "capture_manifest.json") == attached


def test_a_frame_without_a_bundle_keeps_its_nulls_and_its_basis(tmp_path):
    manifest = manifest_with(spec_with())
    write_capture_manifest(manifest, tmp_path)
    summary = attach_engine_labels(tmp_path)
    assert summary["attached"] == 0 and summary["without_bundle"] == len(manifest["frames"])
    assert not summary["written"]
    reread = read_capture_manifest(tmp_path / "capture_manifest.json")
    entry = reread["frames"][0]["labels"]["objects"][0]
    assert entry["bbox_2d_tight"] is None and entry["visible_fraction"] is None
    assert "no engine bundle" in entry["basis"]["engine"]


def test_a_truncated_depth_file_refuses_rather_than_labelling_sky(tmp_path):
    manifest = manifest_with(spec_with())
    write_capture_manifest(manifest, tmp_path)
    fabricate_bundle(tmp_path, manifest)
    victim = next((tmp_path / "frames" / "chase0").glob("*_depth.f32"))
    victim.write_bytes(victim.read_bytes()[:-4])
    with pytest.raises(ValueError, match="float32 values"):
        attach_engine_labels(tmp_path)
    with pytest.raises(ValueError, match="float32 values"):
        read_depth_f32(victim, 1280, 720)


def test_measure_object_by_hand():
    mask = np.zeros((6, 8), dtype=np.uint8)
    mask[1:4, 2:5] = 1          # 3 x 3 primary
    mask[1:4, 5:6] = 2          # a 3 x 1 occluder beside it
    alone = np.zeros((6, 8), dtype=np.uint8)
    alone[1:4, 2:6] = 1         # the primary's footprint, 3 x 4
    depth = np.full((6, 8), np.inf, dtype=np.float32)
    depth[1:4, 2:5] = [[10.0, 12.0, 14.0]] * 3
    out = measure_object(mask, depth, 1, alone)
    assert out["pixels"] == 9 and out["pixels_alone"] == 12
    assert out["bbox_2d_tight"] == [2.0, 1.0, 5.0, 4.0]
    assert out["visible_fraction"] == pytest.approx(0.75)
    assert out["occluded_by"] == [2]
    assert out["depth_min_m"] == 10.0 and out["depth_median_m"] == 12.0
    nothing = measure_object(mask, depth, 9, alone)
    assert nothing["pixels"] == 0 and nothing["bbox_2d_tight"] is None
    assert nothing["visible_fraction"] is None
    # Without an alone pass nothing is said about visibility.
    assert measure_object(mask, depth, 1, None)["visible_fraction"] is None
