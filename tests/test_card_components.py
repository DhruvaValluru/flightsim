"""Phase C3: the card carries the primary's components as objects.

Each ``labels.components[]`` entry of the A-4 config becomes one card
object with an ``int_id`` from the 64..127 band, a ``parent`` (the
aircraft's id), its ``class`` (payload | landing_gear), its ``mesh`` name
and its body-frame extent, all composed ONCE in core/capture/objects.py.
No engine, no render: the mesh manifest a converter would write is
fabricated into a temporary ``assets/generated`` and said so."""

import json

import pytest

import core.capture.objects as objects_module
from core.capture.airframe import load_airframe
from core.capture.labels import hull_box_body_m
from core.capture.manifest import build_capture_manifest
from core.capture.objects import (
    COMPONENT_BAND, COMPONENT_CLASSES, ROLE_COMPONENT, ROLE_PRIMARY,
    ObjectIdentityError, assign_int_ids, component_mesh_name,
    component_object_id, compose_objects, object_entries, objects_block,
)
from core.capture.poses import solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.schema import validate_manifest
from core.nl.compiler import compile_prompt
from core.scenario.blocks import TrafficSpec
from core.scenario.camera import CameraSpec
from core.scenario.card import check_component_ids, write_run_card

from tests.test_camera_poses import FRAME, make_columns

A4_COMPONENTS = ["store_sta2", "drop_tank_sta3", "store_sta4",
                 "nose_gear", "left_main_gear", "right_main_gear"]
A4_PAYLOADS = A4_COMPONENTS[:3]
A4_GEAR = A4_COMPONENTS[3:]
LOW, HIGH = COMPONENT_BAND
ORIGIN_CM = [-500.0, 0.0, 20.0]
# Actor-frame extents about the model origin (metres), the shapes
# decisions.md item 2 measured: a 4.85 x 0.82 x 0.61 m store on each inboard
# wing station at y = -/+1.9 m and a 4.22 x 0.61 m tank on the centreline.
ROWS = {
    "store_sta2": ("STA2", {"x": [-2.4, 2.45], "y": [-2.31, -1.49], "z": [-1.3, -0.69]}),
    "drop_tank_sta3": ("STA3", {"x": [-2.1, 2.12], "y": [-0.3, 0.31], "z": [-1.5, -0.89]}),
    "store_sta4": ("STA4", {"x": [-2.4, 2.45], "y": [1.49, 2.31], "z": [-1.3, -0.69]}),
}


def _spec(aircraft="A4", traffic=()):
    prompt = {"A4": "fly the A4 at 10000 ft and 300 kt",
              "B747": "fly the 747 at 10000 ft and 280 kt"}[aircraft]
    spec = compile_prompt(prompt)
    spec.traffic = [TrafficSpec.defaulted(name, kind) for name, kind in traffic]
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase", aircraft=aircraft)
    camera.set("capture_count", 4, frm="test")
    spec.cameras = [camera]
    return spec


def _mesh_manifest(part_of=None):
    """A version-4 mesh manifest as assets_pipeline/a4_mdl_convert.py writes
    it (C2): one ``components[]`` row per payload, none for the gear."""
    part_of = part_of or (lambda cid: f"SM_A4_{cid}")
    rows = []
    for cid, (station, extent) in ROWS.items():
        rows.append({"id": cid, "class": "payload", "station": station,
                     "part": part_of(cid), "asset_path": f"/Game/Aircraft/A4/{part_of(cid)}",
                     "triangles": 5612 if station == "STA3" else 5676,
                     "mesh_extent_actor_m": extent,
                     "mesh_origin_actor_cm": list(ORIGIN_CM), "mass_lb": 750.0})
    return {"magic": "flightsim-aircraft-mesh", "version": 4, "name": "A4",
            "parts": ["body"] + [row["part"] for row in rows],
            "mesh_origin_actor_cm": list(ORIGIN_CM),
            "mesh_origin_basis": "measured from vertices",
            "mesh_extent_actor_m": {"x": [-6.0, 6.0], "y": [-4.2, 4.2], "z": [-1.6, 2.0]},
            "components": rows}


@pytest.fixture
def converted(tmp_path, monkeypatch):
    """Point the generated-assets directory at tmp_path and return a writer
    for the A-4 mesh manifest there."""
    monkeypatch.setattr(objects_module, "GENERATED_DIR", tmp_path)

    def write(manifest):
        folder = tmp_path / "A4"
        folder.mkdir(exist_ok=True)
        (folder / "mesh_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest
    return write


@pytest.fixture
def headless(tmp_path, monkeypatch):
    """No converted mesh on this machine (the honest headless case)."""
    monkeypatch.setattr(objects_module, "GENERATED_DIR", tmp_path)


def _components(objects):
    return [o for o in objects if o.role == ROLE_COMPONENT]


def _manifest(spec, **kwargs):
    columns = make_columns(duration_s=6.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(
        spec, columns, FRAME, tracks, schedules, output_digest="0" * 64,
        scene={"key": "flat", "terrain": None}, traffic_tracks=[], **kwargs)


# -- the band ---------------------------------------------------------------

def test_card_components_lists_the_a4_loadout_in_the_band(headless):
    objects = compose_objects(_spec())
    components = _components(objects)
    assert [o.id for o in components] == [
        component_object_id(cls, cid) for cls, cid in
        zip(["payload"] * 3 + ["landing_gear"] * 3, A4_COMPONENTS)]
    assert [o.int_id for o in components] == [64, 65, 66, 67, 68, 69]
    assert all(LOW <= o.int_id <= HIGH for o in components)
    assert all(o.parent == "aircraft:A4:0" for o in components)
    assert objects[0].role == ROLE_PRIMARY and objects[0].int_id == 1
    # Composition order: the components come last, after every scene object.
    assert objects[-6:] == components


def test_card_components_ids_are_unique_and_traffic_never_in_the_band(headless):
    objects = compose_objects(_spec(traffic=[("A320", "crossing"), ("B747", "formation")]))
    ints = [o.int_id for o in objects]
    assert len(set(ints)) == len(ints)
    others = [o for o in objects if o.role != ROLE_COMPONENT]
    assert all(o.int_id < LOW for o in others)
    assert [o.int_id for o in _components(objects)] == list(range(64, 70))


def test_card_components_traffic_aircraft_never_in_the_band(headless):
    objects = compose_objects(_spec(traffic=[("A320", "crossing")]))
    traffic = [o for o in objects if o.role == "traffic"]
    assert len(traffic) == 1 and traffic[0].int_id == 2 and traffic[0].int_id < LOW
    assert [o.int_id for o in _components(objects)] == [64, 65, 66, 67, 68, 69]
    assert not any(o.id.startswith("aircraft:") for o in _components(objects))


def test_card_components_non_component_ids_are_unchanged(headless):
    """Everything that is not a component is numbered exactly as it was
    before Phase C: 1.. in composition order."""
    entries = object_entries(_spec(traffic=[("A320", "crossing")]))
    before = assign_int_ids([e for e in entries if e["role"] != ROLE_COMPONENT])
    after = assign_int_ids(entries)
    others = [o for o in after if o.role != ROLE_COMPONENT]
    assert [(o.id, o.int_id) for o in others] == [(o.id, o.int_id) for o in before]
    assert [o.to_dict() for o in others] == [o.to_dict() for o in before]
    assert [o.int_id for o in others] == [1, 2, 3]


def test_card_components_absent_for_an_aircraft_without_components(headless):
    objects = compose_objects(_spec("B747", traffic=[("A320", "crossing")]))
    assert _components(objects) == []
    assert [o.int_id for o in objects] == [1, 2, 3]
    for entry in objects_block(objects):
        assert "parent" not in entry and "mesh" not in entry and "extent_body" not in entry


def test_card_components_refuse_past_the_band_by_name(headless):
    entries = object_entries(_spec())
    terrain = next(e for e in entries if e["id"] == "terrain")

    def fillers(n):
        return [{**terrain, "id": f"building:{i}"} for i in range(n)]
    others = [e for e in entries if e["role"] != ROLE_COMPONENT]
    components = [e for e in entries if e["role"] == ROLE_COMPONENT]
    # 63 non-components is the last list that fits beside the band ...
    fit = assign_int_ids(others + fillers(63 - len(others)) + components)
    assert max(o.int_id for o in fit if o.role != ROLE_COMPONENT) == 63
    assert [o.int_id for o in _components(fit)] == [64, 65, 66, 67, 68, 69]
    # ... one more would reach the band: refused by name.
    with pytest.raises(ObjectIdentityError, match="annotation.identity: .*band 64-127") as e:
        assign_int_ids(others + fillers(64 - len(others)) + components)
    assert e.value.constraint == "annotation.identity"
    # Without components the old limit (255) is the only one.
    assert len(assign_int_ids(others + fillers(255 - len(others)))) == 255
    # More components than the band holds: refused by name.
    many = [{**components[0], "id": f"payload:store_{i}:0"} for i in range(65)]
    with pytest.raises(ObjectIdentityError, match="band 64-127 carries at most 64"):
        assign_int_ids(others + many)
    # The card validates the composed list and never renumbers it.
    card = objects_block(assign_int_ids(entries))
    check_component_ids(card)
    bad = json.loads(json.dumps(card))
    bad[-1]["int_id"] = 200
    with pytest.raises(ObjectIdentityError, match="outside the component band"):
        check_component_ids(bad)
    bad = json.loads(json.dumps(card))
    bad[-1]["int_id"] = bad[-2]["int_id"]      # two gear entries on one integer
    with pytest.raises(ObjectIdentityError, match="carried by both"):
        check_component_ids(bad)
    bad = json.loads(json.dumps(card))
    bad[1]["int_id"] = 70
    with pytest.raises(ObjectIdentityError, match="inside the component band"):
        check_component_ids(bad)


# -- the entry's fields -----------------------------------------------------

def test_card_components_carry_parent_class_mesh_and_extent(tmp_path, converted):
    manifest = converted(_mesh_manifest())
    spec = _spec()
    objects = compose_objects(spec)
    path = write_run_card(spec, tmp_path / "card.json",
                          objects=objects_block(objects), taxonomy=["aircraft", "terrain"])
    card = json.loads(path.read_text(encoding="utf-8"))
    entries = [e for e in card["objects"] if e["role"] == ROLE_COMPONENT]
    assert len(entries) == 6
    airframe = load_airframe("A4")
    rows = {row["id"]: row for row in manifest["components"]}
    primary = card["objects"][0]
    for entry, cid in zip(entries, A4_COMPONENTS):
        assert entry["parent"] == primary["id"] == "aircraft:A4:0"
        assert entry["class"] in COMPONENT_CLASSES and entry["instance"] == 0
        assert entry["licence"] == primary["licence"] and entry["mesh_sha256"] is None
        assert entry["in_scene"] is True and entry["labelled"] is True
        assert entry["id"] == component_object_id(entry["class"], cid)
        if cid in A4_PAYLOADS:
            assert entry["class"] == "payload"
            assert entry["mesh"] == component_mesh_name("A4", cid) == f"SM_A4_{cid}"
            box, basis = hull_box_body_m({**manifest, **rows[cid]}, airframe)
            assert "version 4" in basis
            assert entry["extent_body"] == {axis: [pytest.approx(a), pytest.approx(b)]
                                            for axis, (a, b) in box.items()}
            assert entry["extent_body"]["down"][0] < entry["extent_body"]["down"][1]
        else:
            # Align agreement (f): the gear stays, with no OBJ and no extent.
            assert entry["class"] == "landing_gear"
            assert entry["mesh"] is None and entry["extent_body"] is None
    # The two wing stores sit mirrored about the centreline, the tank on it.
    by_id = {e["id"]: e for e in entries}
    sta2 = by_id["payload:store_sta2:0"]["extent_body"]["right"]
    sta4 = by_id["payload:store_sta4:0"]["extent_body"]["right"]
    assert sta2[0] == pytest.approx(-sta4[1]) and sta2[1] == pytest.approx(-sta4[0])
    tank = by_id["payload:drop_tank_sta3:0"]["extent_body"]["right"]
    assert tank[0] < 0 < tank[1]


def test_card_components_mesh_matches_the_mesh_manifest_parts(converted):
    manifest = converted(_mesh_manifest())
    objects = compose_objects(_spec())
    payloads = [o for o in _components(objects) if o.class_name == "payload"]
    assert len(payloads) == 3
    for obj in payloads:
        assert obj.mesh in manifest["parts"]
        assert obj.mesh == next(r["part"] for r in manifest["components"]
                                if component_object_id("payload", r["id"]) == obj.id)
    # A manifest whose part is not the card's mesh name is refused by name.
    converted(_mesh_manifest(part_of=lambda cid: f"SM_A4_{cid}_v2"))
    with pytest.raises(ObjectIdentityError, match="annotation.identity: .*SM_A4_store_sta2"):
        compose_objects(_spec())


def test_card_components_headless_machine_has_null_mesh_and_extent(headless):
    """No converted mesh here: the components are still composed (the
    ints, parent and class are Python's), with mesh and extent null."""
    for entry in objects_block(_components(compose_objects(_spec()))):
        assert entry["mesh"] is None and entry["extent_body"] is None
        assert entry["parent"] == "aircraft:A4:0"


# -- the manifest ----------------------------------------------------------

def test_manifest_labels_carry_a_component_record(converted):
    converted(_mesh_manifest())
    manifest = _manifest(_spec())
    roles = [o["role"] for o in manifest["objects"]]
    assert roles.count(ROLE_COMPONENT) == 6 and roles[0] == ROLE_PRIMARY
    for frame in manifest["frames"]:
        records = {r["id"]: r for r in frame["labels"]["objects"]}
        payload = records["payload:drop_tank_sta3:0"]
        assert payload["class"] == "payload" and payload["parent"] == "aircraft:A4:0"
        assert payload["int_id"] == 65
        assert payload["bbox_2d_hull"] is not None and len(payload["bbox_2d_hull"]) == 4
        assert "body-frame extent box" in payload["basis"]["bbox_2d_hull"]
        gear = records["landing_gear:nose_gear:0"]
        assert gear["bbox_2d_hull"] is None and "declares no extent" in gear["basis"]["bbox_2d_hull"]
    # One extent for the card and the manifest: the manifest's objects[]
    # entry carries the same body-frame box the record was projected from.
    entry = next(o for o in manifest["objects"] if o["id"] == "payload:drop_tank_sta3:0")
    assert entry["mesh"] == "SM_A4_drop_tank_sta3" and set(entry["extent_body"]) == {
        "forward", "right", "down"}


def test_card_components_validate_against_the_v8_schema(converted):
    converted(_mesh_manifest())
    manifest = _manifest(_spec())
    assert manifest["manifest_version"] == 8
    validate_manifest(manifest)
    assert {o["role"] for o in manifest["objects"]} == {"primary", "scene", "component"}
    # A component outside the band is not schema-clean either way, but the
    # role itself is in the enum: an entry with role component validates.
    assert all(LOW <= o["int_id"] <= HIGH for o in manifest["objects"]
               if o["role"] == ROLE_COMPONENT)
