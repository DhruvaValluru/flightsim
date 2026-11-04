"""Phase C5: component label records, the parent rollup, manifest v8.

Everything here runs on hand-built cards and numpy masks: no engine, no
render bundle, no real aircraft."""

import copy
import json

import numpy as np
import pytest

from core.capture.labels import (
    GEAR_RETRACTED_BASIS, attach_engine_labels, camera_axes,
    component_label_record, conventions, measure_object, object_label_record,
    tight_box_basis,
)
from core.capture.verify import verify_component_boxes
from core.capture.manifest import (
    MANIFEST_VERSION, SUPPORTED_MANIFEST_VERSIONS, read_capture_manifest,
)
from core.capture.objects import (
    COMPONENT_CLASSES, SceneObject, children_of, class_id_of, resolve_ids,
)
from core.capture.schema import validate_manifest
from core.scenario.blocks import DEFAULT_CLASSES
from tests.test_camera_labels import level_camera_record, manifest_for

AIRCRAFT, PAYLOAD = 1, 64


def _mask(h, w, blobs):
    """A (h, w) uint8 ID image; ``blobs`` is [(id, x0, y0, x1, y1), ...]
    painted in order."""
    out = np.zeros((h, w), np.uint8)
    for value, x0, y0, x1, y1 in blobs:
        out[y0:y1, x0:x1] = value
    return out


def _hand_card_objects():
    return [
        {"id": "aircraft:primary", "int_id": AIRCRAFT, "class": "aircraft",
         "class_id": class_id_of(DEFAULT_CLASSES, "aircraft"), "parent": None},
        {"id": "payload:tank_centre", "int_id": PAYLOAD, "class": "payload",
         "class_id": class_id_of(DEFAULT_CLASSES, "payload"),
         "parent": "aircraft:primary"},
    ]


def test_children_of_and_the_taxonomy_order():
    assert children_of(_hand_card_objects()) == {AIRCRAFT: [PAYLOAD]}
    assert COMPONENT_CLASSES == ("payload", "landing_gear")
    assert DEFAULT_CLASSES[-2:] == COMPONENT_CLASSES
    assert class_id_of(DEFAULT_CLASSES, "aircraft") == 1     # nothing moved


def test_payload_blob_gives_a_tight_box_equal_to_the_blob():
    mask = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 30), (PAYLOAD, 20, 14, 30, 20)])
    out = measure_object(mask, None, PAYLOAD)
    assert out["bbox_2d_tight"] == [20.0, 14.0, 30.0, 20.0]
    assert out["pixels"] == 10 * 6


def test_out_of_frame_payload_is_null_with_the_out_of_frame_basis():
    record = level_camera_record()
    state = {"north_m": 1000.0, "east_m": 0.0, "alt_m": 1000.0,
             "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
    obj = SceneObject(id="payload:tank_centre", int_id=PAYLOAD, class_name="payload",
                      class_id=7, instance=0, role="component", mesh_sha256=None,
                      licence=None, in_scene=True, labelled=True,
                      parent="aircraft:primary")
    axes = camera_axes(record["quaternion_wxyz"])
    # 5 km to the right of the aircraft: far outside a 1280 px, 35 mm frame.
    far = {"forward": (-1.0, 1.0), "right": (5000.0, 5001.0), "down": (0.0, 1.0)}
    entry = object_label_record(obj, record, state, None, axes, 0.0, extent_body=far)
    assert entry["parent"] == "aircraft:primary" and entry["class"] == "payload"
    assert entry["bbox_2d_hull"] is None and entry["fraction_in_frame"] == 0.0
    measured = measure_object(_mask(40, 60, [(AIRCRAFT, 10, 10, 50, 30)]), None, PAYLOAD)
    entry["bbox_2d_tight"] = measured["bbox_2d_tight"]
    assert entry["bbox_2d_tight"] is None
    assert tight_box_basis(entry).startswith("out of frame")


def test_payload_behind_the_fuselage_is_invisible_and_occluded_by_the_aircraft():
    mask = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 30)])          # fuselage covers it all
    alone = _mask(40, 60, [(PAYLOAD, 20, 14, 30, 20)])
    out = measure_object(mask, None, PAYLOAD, alone)
    assert out["visible_fraction"] == 0 and out["bbox_2d_tight"] is None
    assert resolve_ids(out["occluded_by"], _hand_card_objects()) == ["aircraft:primary"]
    entry = {"bbox_2d_tight": None, "fraction_in_frame": 1.0, "visible_fraction": 0}
    assert tight_box_basis(entry).startswith("fully occluded")


def test_aircraft_tight_box_includes_its_payload_pixels():
    mask = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 20), (PAYLOAD, 20, 20, 30, 28)])
    assert measure_object(mask, None, AIRCRAFT)["bbox_2d_tight"] == [10.0, 10.0, 50.0, 20.0]
    rolled = measure_object(mask, None, AIRCRAFT, children=[PAYLOAD])
    assert rolled["bbox_2d_tight"] == [10.0, 10.0, 50.0, 28.0]
    assert rolled["pixels"] == 40 * 10 + 10 * 8


def test_children_are_never_in_the_parents_occluded_by():
    mask = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 20), (PAYLOAD, 20, 20, 30, 28),
                          (2, 40, 12, 46, 18)])
    alone = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 28)])    # the aircraft drawn with its payload
    plain = measure_object(mask, None, AIRCRAFT, alone)
    assert PAYLOAD in plain["occluded_by"]    # without children the payload id is just another id
    rolled = measure_object(mask, None, AIRCRAFT, alone, children=[PAYLOAD])
    assert rolled["occluded_by"] == [2]
    assert PAYLOAD not in rolled["occluded_pixels"]
    assert rolled["visible_fraction"] == pytest.approx(
        (400 + 80 - 36) / 720)


def test_old_calls_without_children_are_unchanged():
    mask = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 20), (2, 40, 12, 46, 18)])
    alone = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 20)])
    assert measure_object(mask, None, AIRCRAFT, alone) == \
        measure_object(mask, None, AIRCRAFT, alone, children=())
    assert measure_object(mask, None, AIRCRAFT, alone)["occluded_by"] == [2]


def test_component_hull_equals_the_hand_projected_box():
    record = level_camera_record()
    state = {"north_m": 1000.0, "east_m": 0.0, "alt_m": 1000.0,
             "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
    obj = SceneObject(id="payload:tank_centre", int_id=PAYLOAD, class_name="payload",
                      class_id=7, instance=0, role="component", mesh_sha256=None,
                      licence=None, in_scene=True, labelled=True,
                      parent="aircraft:primary")
    box = {"forward": (-2.0, 2.0), "right": (-1.0, 1.0), "down": (1.0, 2.0)}
    entry = component_label_record(obj, {"id": "aircraft:primary"}, record, state,
                                   None, camera_axes(record["quaternion_wxyz"]), box)
    fx = record["fx_px"]
    # Level camera, aircraft due north of it: depth = 1000 + forward; the
    # box's nearest face (forward -2) is widest, the far face narrower.
    near, far = 998.0, 1002.0
    u0 = 640.0 - 1.0 * fx / near
    u1 = 640.0 + 1.0 * fx / near
    v0 = 360.0 + 1.0 * fx / far          # down 1 m at the far face (smaller)
    v1 = 360.0 + 2.0 * fx / near         # down 2 m at the near face
    assert entry["bbox_2d_hull"] == pytest.approx([u0, v0, u1, v1], abs=0.01)
    assert entry["fraction_in_frame"] == 1.0
    assert entry["class_id"] == 7 and entry["bbox_2d_tight"] is None
    assert entry["occluded_by"] == []


def test_conventions_document_payload_landing_gear_and_the_rollup():
    text = conventions()
    for key in ("payload", "landing_gear", "component_rollup"):
        assert key in text
    assert "never appears in its parent's occluded_by" in text["component_rollup"]


def test_validate_manifest_accepts_v8_and_v7():
    manifest = manifest_for()
    assert manifest["manifest_version"] == MANIFEST_VERSION == 8
    assert validate_manifest(manifest) == []
    v7 = copy.deepcopy(manifest)
    v7["manifest_version"] = 7
    assert validate_manifest(v7) == []
    # a component entry in a frame's labels.objects[] validates under v8
    v8 = copy.deepcopy(manifest)
    labels = v8["frames"][0]["labels"]
    labels["objects"].append({
        "id": "payload:tank_centre", "int_id": 64, "class": "payload", "class_id": 7,
        "parent": labels["objects"][0]["id"], "bbox_2d_hull": None,
        "fraction_in_frame": 0.0, "bbox_2d_tight": None, "visible_fraction": None,
        "occluded_by": [], "not_claimed": [], "basis": {"bbox_2d_tight": "out of frame"}})
    assert validate_manifest(v8) == []


def test_read_capture_manifest_reads_3_to_8_and_refuses_9(tmp_path):
    assert SUPPORTED_MANIFEST_VERSIONS == (3, 4, 5, 6, 7, 8)
    for version in (3, 7, 8, 9):
        path = tmp_path / f"m{version}.json"
        path.write_text(json.dumps({"manifest_version": version}), encoding="utf-8")
        if version == 9:
            with pytest.raises(ValueError):
                read_capture_manifest(path)
        else:
            assert read_capture_manifest(path)["manifest_version"] == version


# ---------------------------------------------------------------------------
# C7: landing gear. Gear down is boxed like any component; retracted gear
# (gear/gear-pos-norm below 0.01) is null with the basis "gear retracted",
# never a zero-size box. The A-4's gear entries have no mesh at all.

GEAR = 65
_AIRCRAFT_STATE = {"north_m": 1000.0, "east_m": 0.0, "alt_m": 1000.0,
                   "roll_deg": 0.0, "pitch_deg": 0.0, "heading_deg": 0.0}
_GEAR_BOX = {"forward": (-1.0, 1.0), "right": (-1.0, 1.0), "down": (1.0, 2.0)}


def _gear_object(obj_id="landing_gear:landing_gear:0"):
    return SceneObject(id=obj_id, int_id=GEAR, class_name="landing_gear",
                       class_id=class_id_of(DEFAULT_CLASSES, "landing_gear"),
                       instance=0, role="component", mesh_sha256=None, licence=None,
                       in_scene=True, labelled=True, parent="aircraft:primary")


def _gear_entry(gear_pos, extent_body=_GEAR_BOX, obj_id="landing_gear:landing_gear:0",
                via_record=True):
    """A landing_gear record at gear position ``gear_pos``: the channel on
    the frame record's recorded row (the recorder's), or on the aircraft
    state dict when ``via_record`` is False."""
    record = level_camera_record()
    state = dict(_AIRCRAFT_STATE)
    if via_record:
        record["state"] = {"gear/gear-pos-norm": gear_pos, "alt_m": 1000.0}
    else:
        state["gear/gear-pos-norm"] = gear_pos
    return component_label_record(_gear_object(obj_id), {"id": "aircraft:primary"},
                                  record, state, None,
                                  camera_axes(record["quaternion_wxyz"]), extent_body)


def test_extended_gear_has_a_tight_box():
    entry = _gear_entry(1.0)
    assert entry["class"] == "landing_gear" and entry["parent"] == "aircraft:primary"
    assert entry["bbox_2d_hull"] is not None and entry["fraction_in_frame"] == 1.0
    assert "bbox_2d_tight" not in entry["basis"]
    assert not any(GEAR_RETRACTED_BASIS in s for s in entry["not_claimed"])
    mask = _mask(40, 60, [(AIRCRAFT, 10, 10, 50, 30), (GEAR, 25, 26, 35, 30)])
    entry["bbox_2d_tight"] = measure_object(mask, None, GEAR)["bbox_2d_tight"]
    assert entry["bbox_2d_tight"] == [25.0, 26.0, 35.0, 30.0]
    u0, v0, u1, v1 = entry["bbox_2d_tight"]
    assert u1 > u0 and v1 > v0                      # a real box, not a zero-size one
    assert tight_box_basis(entry) is None
    # No channel recorded (a fixed-gear row without it): the gear is down.
    record = level_camera_record()
    plain = component_label_record(_gear_object(), {"id": "aircraft:primary"}, record,
                                   dict(_AIRCRAFT_STATE), None,
                                   camera_axes(record["quaternion_wxyz"]), _GEAR_BOX)
    assert "bbox_2d_tight" not in plain["basis"]


def test_retracted_gear_is_null_with_gear_retracted_basis():
    assert GEAR_RETRACTED_BASIS == "gear retracted"
    entry = _gear_entry(0.0)
    assert entry["bbox_2d_tight"] is None
    assert entry["basis"]["bbox_2d_tight"] == GEAR_RETRACTED_BASIS
    assert any(GEAR_RETRACTED_BASIS in s for s in entry["not_claimed"])
    assert entry["bbox_2d_hull"] is not None        # where the card says the gear sits
    # The threshold: 0.009 is retracted, 0.01 is not.
    assert _gear_entry(0.009)["basis"]["bbox_2d_tight"] == GEAR_RETRACTED_BASIS
    assert "bbox_2d_tight" not in _gear_entry(0.01)["basis"]
    # C6's component_boxes skips a null tight box that carries a basis: the
    # retracted record alone grades nothing (NOT RUN, never FAIL), and beside
    # a gear-down record with a box it is skipped while that one passes.
    parent = {"id": "aircraft:primary", "int_id": AIRCRAFT, "class": "aircraft",
              "class_id": class_id_of(DEFAULT_CLASSES, "aircraft"), "parent": None,
              "bbox_2d_hull": [0.0, 0.0, 1280.0, 720.0],
              "bbox_2d_tight": [0.0, 0.0, 1280.0, 720.0]}

    def manifest_with(*records):
        return {"frames": [{"camera_id": "cam", "index": 0,
                            "labels": {"objects": [parent, *records]}}],
                "objects": _hand_card_objects()}

    check = verify_component_boxes(manifest_with(entry))
    assert check.status == "NOT RUN" and "no frame carries" in check.detail
    down = _gear_entry(1.0)
    u0, v0, u1, v1 = down["bbox_2d_hull"]
    cu, cv = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    down["bbox_2d_tight"] = [cu - 1.0, cv - 1.0, cu + 1.0, cv + 1.0]
    check = verify_component_boxes(manifest_with(entry, down))
    assert check.status == "PASS", check.detail


def test_components_a4_gear_has_no_mesh_and_is_retracted_airborne():
    """The A-4's three gear entries stay declared with ``mesh: null`` and
    ``extent_body: null`` (its mesh has no gear vertex); airborne the A-4
    retracts (gear/gear-pos-norm 0), so the record is null with the gear
    basis, never a box."""
    entry = _gear_entry(0.0, extent_body=None, obj_id="landing_gear:nose_gear:0",
                        via_record=False)
    assert entry["id"] == "landing_gear:nose_gear:0"
    assert entry["class"] == "landing_gear" and entry["parent"] == "aircraft:primary"
    assert entry["bbox_2d_hull"] is None and entry["fraction_in_frame"] is None
    assert "declares no extent" in entry["basis"]["bbox_2d_hull"]
    assert entry["bbox_2d_tight"] is None
    assert entry["basis"]["bbox_2d_tight"] == GEAR_RETRACTED_BASIS
    assert any(GEAR_RETRACTED_BASIS in s for s in entry["not_claimed"])
    # On the ground (gear down) the same mesh-less entry has no gear basis:
    # its null tight box is C5's "card declares no extent" case.
    down = _gear_entry(1.0, extent_body=None, obj_id="landing_gear:nose_gear:0",
                       via_record=False)
    assert down["bbox_2d_tight"] is None and "bbox_2d_tight" not in down["basis"]


def test_the_verifier_s_hiding_recount_excludes_the_record_s_children():
    """Packet C4-1: the aircraft record's occluded_pixels_by was {} (C5's
    measure_object excludes the record's own children) while the verifier
    recounted the stores as occluders (22/8/21 px). The recount now follows
    the measure's rule: the parent's footprint is its own id OR a child's,
    and a child is never an occluder. Synthetic pair: the parent's alone
    pass draws the aircraft whole (its store included, as the engine does),
    the ID image gives the store its own id and a traffic aircraft hides
    4 px of the airframe and 1 px of the store."""
    from core.capture.verify import _occluded_pixels_by

    alone = np.zeros((6, 8), dtype=np.uint8)
    alone[1:5, 1:7] = 1                      # the aircraft drawn alone, store included
    mask = alone.copy()
    mask[1:5, 5:7] = 64                      # the store's own id in the ID image (8 px)
    mask[1:3, 1:3] = 2                       # traffic over the airframe (4 px)
    mask[3, 5] = 2                           # traffic over the store (1 px)
    id_of = {1: "aircraft:A4:0", 2: "aircraft:traffic:0", 64: "payload:store_sta2:0"}

    mine = _occluded_pixels_by(mask, alone, 1, [64], id_of)
    assert mine == {"aircraft:traffic:0": 5}
    # The same rule as C5's measure, which the record was written from.
    record = measure_object(mask, None, 1, alone=alone, children=[64])
    assert {id_of[k]: v for k, v in record["occluded_pixels"].items()} == mine
    # Without the children the store is counted as an occluder: the FAIL.
    assert _occluded_pixels_by(mask, alone, 1, [], id_of) == {
        "aircraft:traffic:0": 5, "payload:store_sta2:0": 7}
    # The child's own recount: the traffic hides 1 px of it, nothing else.
    assert _occluded_pixels_by(mask, alone, 64, [], id_of) == {}
    alone_store = np.where(mask == 64, 64, 0).astype(np.uint8)
    alone_store[3, 5] = 64
    assert _occluded_pixels_by(mask, alone_store, 64, [], id_of) == {"aircraft:traffic:0": 1}
