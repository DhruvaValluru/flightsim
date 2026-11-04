"""The A-4E exterior model: decoded, converted, and tied to the flight model.

The .mdl layout was worked out by measurement (assets_pipeline/mdl_scene.py),
so these tests pin the measured facts: if a decode assumption is wrong the
geometry stops agreeing with the cfg/FDM numbers and something here fails.
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest

from assets_pipeline import a4_mdl_convert, a4_mesh_check as mc, importer
from assets_pipeline.mdl_scene import REST_ENV, MdlScene, evaluate
from core.capture import objects
from core.capture.airframe import load_airframe
from core.capture.labels import hull_box_body_m

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "assets" / "aircraft_config" / "A4.json"

#: Triangles each loaded station adds over the rest environment, before the
#: converter's degenerate filter (decision 2, docs/phase3/decisions.md:
#: one variable at a time over REST_ENV). Not the plan's "+14,612".
STATION_DELTAS = {"STA2": 5676, "STA3": 5612, "STA4": 5676}
#: Where each store hangs, model x (right), metres (decision 2).
STATION_X_M = {"STA2": -1.9, "STA3": 0.0, "STA4": 1.9}
#: The body's triangle count after the degenerate filter (baseline run).
BODY_TRIANGLES = 266886


def component_mesh_name(aircraft: str, component_id: str) -> str:
    """C3's `core.capture.objects.component_mesh_name` when it exists, else
    the agreed convention it implements (Align agreement d)."""
    fn = getattr(objects, "component_mesh_name", None)
    expected = f"SM_{aircraft}_{component_id}"
    if fn is not None:
        assert fn(aircraft, component_id) == expected
    return expected


def _raw_triangles(parts) -> int:
    return sum(len(p.triangles) for p in parts)


def _obj_faces(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines()
               if line.startswith("f "))


@pytest.fixture(scope="module")
def scene():
    return MdlScene(mc.MDL)


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    """One conversion shared by the component tests (the decode is slow)."""
    path = a4_mdl_convert.convert(CONFIG, tmp_path_factory.mktemp("a4"), REPO)
    return path, json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def loadout():
    return json.loads(CONFIG.read_text(encoding="utf-8"))["loading"]["loadout"]


def test_scene_decodes_a_complete_visible_airframe(scene):
    parts = scene.parts()
    assert 100 < len(parts) < 200
    lo = np.min([p.positions.min(0) for p in parts], axis=0)
    hi = np.max([p.positions.max(0) for p in parts], axis=0)
    # x right, y up, z forward, metres: an 8.3 m span, ~13 m long, 4 m tall
    assert 8.0 < hi[0] - lo[0] < 8.6
    assert 12.5 < hi[2] - lo[2] < 13.5
    assert 3.5 < hi[1] - lo[1] < 4.5


def test_horizontal_tail_is_found_where_the_fdm_expects_it():
    tail = mc.horizontal_tail()
    assert tail["parts"] == 4                       # 2 stabilizer + 2 elevator
    assert 40 < tail["area_ft2"] < 47
    assert 14 < tail["arm_ft"] < 16.5


def test_fdm_tail_metrics_and_pitch_terms_follow_the_mesh():
    from core.fdm import FlightDynamics
    from assets_pipeline import a4_sync

    tail = mc.horizontal_tail()
    fdm = FlightDynamics("A4")
    assert abs(fdm.props.get("metrics/Sh-sqft") - tail["area_ft2"]) < 0.01
    assert abs(fdm.props.get("metrics/lh-ft") - tail["arm_ft"]) < 0.01
    text = (REPO / "assets/fdm_root/aircraft/A4/A4.xml").read_text(encoding="utf-8")
    volume = (tail["area_ft2"] * tail["arm_ft"]) / (
        a4_sync.STOCK_HTAIL_AREA_FT2 * a4_sync.STOCK_HTAIL_ARM_FT)
    stock_cmde_row = -0.5                            # Aeromatic Cmde, mach 0
    assert f"{stock_cmde_row * volume:.4f}" in text


def test_stores_are_hidden_and_gear_is_stowed_at_rest(scene):
    # nothing hangs below the wing in the rest configuration
    assert min(p.positions[:, 1].min() for p in scene.parts()) > -1.2


def test_visibility_expressions():
    assert evaluate("(L:CustomVisibility87, bool)", {}) is False
    assert evaluate("(L:CustomVisibility87, bool)",
                    {"CustomVisibility87": 1}) is True
    assert evaluate("(L:STA2_LOAD, enum) 4 ==", {"STA2_LOAD": 4}) is True
    assert evaluate("(L:ElecticalPowerAvailable, bool) !", {}) is True
    # control flow is not evaluated, and says so rather than guessing
    assert evaluate("(A:X, bool) if{ 1 } els{ 0 }", {}) is None


def test_conversion_writes_a_valid_manifest_and_obj(tmp_path):
    manifest_path = a4_mdl_convert.convert(CONFIG, tmp_path, REPO)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["magic"] == "flightsim-aircraft-mesh"
    assert manifest["fdm"] == "A4" and manifest["fdm_config_name"] == "A-4"
    assert manifest["parts"] == ["body", "SM_A4_store_sta2", "SM_A4_drop_tank_sta3",
                                 "SM_A4_store_sta4"]
    assert manifest["surfaces"] == []
    assert manifest["articulated"] is False
    assert manifest["source"]["license_first_line"].startswith("A-4 Skyhawk")

    root = manifest_path.parent
    v = vt = vn = 0
    max_face = 0
    faces = 0
    for line in (root / "body.obj").read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            v += 1
        elif line.startswith("vt "):
            vt += 1
        elif line.startswith("vn "):
            vn += 1
        elif line.startswith("f "):
            faces += 1
            max_face = max(max_face, *(int(t.split("/")[0])
                                       for t in line.split()[1:]))
    assert v == vt == vn and max_face == v
    assert faces == manifest["triangles"]["body"]
    for texture in manifest["textures"]:
        assert (root / texture).is_file()
    assert "map_Kd A4E_1.png" in (root / "body.mtl").read_text(encoding="utf-8")


def test_converted_bounds_agree_with_the_flight_models_geometry(tmp_path):
    """UE frame (+X fwd, +Y right, +Z up), cm, origin at the CG datum."""
    manifest = json.loads(
        a4_mdl_convert.convert(CONFIG, tmp_path, REPO).read_text(encoding="utf-8"))
    lo, hi = manifest["bounds_cm"]["min"], manifest["bounds_cm"]["max"]
    ref = mc.fdm_reference()
    ft = 30.48
    assert abs(hi[1] / ft - ref["half_span_ft"]) < 0.3        # right wingtip
    assert abs(lo[1] / ft + ref["half_span_ft"]) < 0.3        # left wingtip
    assert abs(hi[2] / ft - ref["top_ft"]) < 0.3              # fin top
    assert abs(lo[0] / ft - ref["tail_end_ft"]) < 1.0         # tail end
    assert hi[0] / ft > ref["nose_ft"]                        # nose + probe


def test_station_load_adds_one_part_each(scene):
    rest = {p.index for p in scene.parts()}
    for station, delta in STATION_DELTAS.items():
        added = scene.added_parts({f"{station}_LOAD": 1})
        assert len(added) == 1, station
        assert _raw_triangles(added) == delta, station
        assert added[0].index not in rest
        centre = added[0].positions.mean(0)
        assert abs(centre[0] - STATION_X_M[station]) < 0.3, station
        assert centre[1] < -1.0, station                # it hangs below the wing
    # a base the station is already in adds nothing
    assert scene.added_parts({"STA3_LOAD": 1}, {**REST_ENV, "STA3_LOAD": 1}) == []


def test_station_parts_sum_to_the_full_loadout_delta(scene, loadout):
    per_station = {}
    for station in loadout["stations"]:
        env = a4_mdl_convert._station_env(loadout, station)
        assert env == {**REST_ENV, f"{station}_LOAD": 1.0}
        per_station[station] = {p.index for p in scene.added_parts(env)}
    full = {p.index for p in scene.added_parts(loadout["model_vars"])}
    assert set.union(*per_station.values()) == full
    assert sum(len(s) for s in per_station.values()) == len(full) == 3
    assert _raw_triangles(scene.added_parts(loadout["model_vars"])) == sum(
        STATION_DELTAS.values())


def test_conversion_exports_one_payload_obj_per_loaded_station(scene, converted, loadout):
    manifest_path, manifest = converted
    root = manifest_path.parent
    assert manifest["version"] == a4_mdl_convert.A4_COMPONENTS_MANIFEST_VERSION == 4
    assert manifest["parts"][0] == "body"
    assert len(manifest["parts"]) == 1 + len(loadout["stations"]) == 4
    assert set(manifest["triangles"]) == set(manifest["parts"])
    assert manifest["triangles"]["body"] == BODY_TRIANGLES
    for part in manifest["parts"]:
        assert (root / f"{part}.obj").is_file() and (root / f"{part}.mtl").is_file()
        assert _obj_faces(root / f"{part}.obj") == manifest["triangles"][part]
        assert f"mtllib {part}.mtl" in (root / f"{part}.obj").read_text(encoding="utf-8")
    # each component's count is the station's own delta, same filter
    for row in manifest["components"]:
        parts = scene.added_parts(a4_mdl_convert._station_env(loadout, row["station"]))
        assert _raw_triangles(parts) == STATION_DELTAS[row["station"]]
        assert row["triangles"] == sum(a4_mdl_convert._filter_part(p) for p in parts)
        assert row["model_vars"] == {f"{row['station']}_LOAD": 1.0}
    # and the body is the rest environment only
    rest = scene.parts()
    assert sum(a4_mdl_convert._filter_part(p) for p in rest) == manifest["triangles"]["body"]


def test_component_ids_match_labels_components(converted):
    _, manifest = converted
    airframe = load_airframe("A4")
    payloads = {c.id: c for c in airframe.components if c.cls == "payload"}
    assert len(payloads) == 3
    rows = {row["id"]: row for row in manifest["components"]}
    assert set(rows) == set(payloads)              # the bare C1 id is the shared key
    assert all(row["class"] == "payload" for row in rows.values())
    for component in payloads.values():
        row = rows[component.id]
        mesh = component_mesh_name("A4", component.id)
        assert row["part"] == mesh
        assert mesh in manifest["parts"] and manifest["triangles"][mesh] == row["triangles"]
        assert row["asset_path"] == f"{manifest['asset_path_root']}/{mesh}"
        assert row["station"] == component.station
        assert row["mass_lb"] == component.mass_lb == 750.0
    # gear is stowed: no row, no OBJ (Align agreement f)
    assert [c.id for c in airframe.components if c.cls == "landing_gear"]
    assert not any(row["class"] == "landing_gear" for row in manifest["components"])


def test_component_extents_feed_hull_box_body_m(converted):
    _, manifest = converted
    airframe = load_airframe("A4")
    body_box, _ = hull_box_body_m(manifest, airframe)
    assert body_box is not None
    for row in manifest["components"]:
        assert row["mesh_origin_actor_cm"] == manifest["mesh_origin_actor_cm"]
        box, basis = hull_box_body_m({**manifest, **row}, airframe)
        assert box is not None and "version 4" in basis
        # a store is shorter than the fuselage and inside the span
        assert body_box["forward"][0] < box["forward"][0] < box["forward"][1] < body_box["forward"][1]
        assert body_box["right"][0] < box["right"][0] < box["right"][1] < body_box["right"][1]
        # and hangs below the body's lowest rest-pose vertex (down is +)
        assert box["down"][1] > body_box["down"][1]
        ex = row["mesh_extent_actor_m"]
        length = ex["x"][1] - ex["x"][0]
        if row["station"] == "STA3":
            assert 4.0 < length < 4.5                 # the 4.22 m centreline tank
            assert abs(sum(ex["y"])) < 0.1
        else:
            assert 4.6 < length < 5.1                 # the 4.85 m inboard stores
            assert (sum(ex["y"]) / 2) * (1 if row["station"] == "STA4" else -1) > 1.5


def test_old_a4_manifest_is_stale(tmp_path):
    def write(name, version, **extra):
        path = tmp_path / name / "mesh_manifest.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({
            "version": version, "name": name, "parts": [], "textures": [],
            "mesh_origin_actor_cm": [-100.0, 0.0, 10.0],
            importer.OBJ_FRAME_KEY: importer.OBJ_FRAME, **extra}), encoding="utf-8")
        return path

    reason = importer.stale_manifest_reason(write("A4", 3))
    assert reason is not None and "components" in reason and "STA3_LOAD" in reason
    assert "version 4" in reason
    # version 4 claimed without the list is equally stale
    assert "components" in importer.stale_manifest_reason(write("A4", 4))
    assert importer.stale_manifest_reason(write("A4", 4, components=[])) is None
    # an airframe without a loadout keeps the version-3 contract
    assert importer.stale_manifest_reason(write("B747", 3)) is None


def test_importer_builds_a_local_model_without_fetching(monkeypatch, tmp_path):
    assert "A4" in importer.configured_aircraft()
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(importer.subprocess, "run",
                        lambda cmd, **kw: calls.append([str(c) for c in cmd])
                        or Done())
    monkeypatch.setattr(importer, "GENERATED", tmp_path)
    manifest = tmp_path / "A4" / "mesh_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "A4", "parts": ["body"],
                                    "asset_path_root": "/Game/Aircraft/A4"}),
                        encoding="utf-8")
    importer.convert(CONFIG, report=lambda line: None)
    assert any("a4_mdl_convert.py" in part for cmd in calls for part in cmd)
    assert not any("git" in cmd[0] for cmd in calls)


def test_unreal_host_gear_list_matches_the_repo_owned_airframes():
    cpp = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
           "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    listed = set(re.findall(
        r'RepoOwnedAirframes\[\] = \{([^}]*)\}', cpp)[0].replace(
            "TEXT(", "").replace(")", "").replace('"', "").replace(
            " ", "").split(","))
    owned = {p.name for p in (REPO / "assets/fdm_root/aircraft").iterdir()
             if p.is_dir()}
    assert listed == owned


# -- decision 19: the OBJ is right-handed; the manifest stays in the actor frame --

def _obj_vertices_and_faces(path: Path):
    """``v`` lines as (x, y, z) floats, ``f`` lines as 0-based vertex indices."""
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            vertices.append(tuple(float(t) for t in line.split()[1:4]))
        elif line.startswith("f "):
            faces.append(tuple(int(t.split("/")[0]) - 1 for t in line.split()[1:]))
    return vertices, faces


def test_body_obj_is_right_handed_against_the_manifest_extents(converted):
    """The manifest's bounds_cm are the ACTOR frame; the OBJ's vertices are
    the same points with Y negated (what Unreal's right-handed OBJ import
    undoes), so the file's y range is the manifest's mirrored and x / z
    are untouched. The starboard refuelling probe (actor y +0.43..+0.54 m,
    the forward-most vertex) is the asymmetric feature that tells a mirror
    from the real thing: in the OBJ it sits at NEGATIVE y."""
    path, manifest = converted
    vertices, _ = _obj_vertices_and_faces(path.parent / "body.obj")
    xs, ys, zs = (np.array(c) for c in zip(*vertices))
    lo, hi = manifest["bounds_cm"]["min"], manifest["bounds_cm"]["max"]
    assert manifest[importer.OBJ_FRAME_KEY] == importer.OBJ_FRAME
    assert (xs.min(), xs.max()) == pytest.approx((lo[0], hi[0]), abs=0.01)
    assert (zs.min(), zs.max()) == pytest.approx((lo[2], hi[2]), abs=0.01)
    assert (ys.min(), ys.max()) == pytest.approx((-hi[1], -lo[1]), abs=0.01)
    probe = vertices[int(xs.argmax())]
    assert -60.0 < probe[1] < -30.0, probe


def test_store_objs_sit_on_the_obj_frame_s_other_side(converted):
    """Each component OBJ follows the same convention as the body: the
    port store (row extent y < 0 in the actor frame) is written at y > 0,
    the starboard one at y < 0 (the measured mirror of packet C4-1, now
    produced on purpose so the import lands it where the row says)."""
    path, manifest = converted
    for row in manifest["components"]:
        vertices, _ = _obj_vertices_and_faces(path.parent / f"{row['part']}.obj")
        ys = np.array([v[1] for v in vertices])
        side = sum(row["mesh_extent_actor_m"]["y"]) / 2.0
        if row["station"] == "STA3":
            assert abs(side) < 0.1 and abs(ys.mean()) < 10.0
        else:
            assert side * ys.mean() < 0, (row["part"], side, ys.mean())
            assert (ys > 0).all() if side < 0 else (ys < 0).all()


def test_a_hand_part_s_signed_volume_survives_the_obj_write(tmp_path):
    """One tetrahedron through _write_obj: every written vertex is the
    actor-frame point with Y negated, every face is the part's triangle
    rewound, and the signed volume the written file encloses has the SIGN
    of the actor-frame tetrahedron with its original winding (times 1e6:
    metres to centimetres). A mirror without the rewind would negate it."""
    from assets_pipeline.mdl_scene import Part
    from assets_pipeline.obj_frame import signed_volume

    # .mdl frame (x right, y up, z forward), metres; an outward-wound tetra.
    positions = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                          [0.0, 1.0, 0.0], [0.0, 0.0, 2.0]])
    triangles = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    part = Part(index=0, node=0, material=0, positions=positions,
                normals=np.tile([0.0, 1.0, 0.0], (4, 1)),
                uvs=np.zeros((4, 2)), triangles=triangles)
    actor = a4_mdl_convert._to_ue(positions) * a4_mdl_convert.CM_PER_M
    expected = signed_volume(actor.tolist(), triangles.tolist())
    assert expected != 0.0

    measured = a4_mdl_convert._write_obj([part], tmp_path, "tet")
    assert measured["triangles"] == 4 and measured["vertices"] == 4
    vertices, faces = _obj_vertices_and_faces(tmp_path / "tet.obj")
    assert np.allclose(vertices, actor * [1.0, -1.0, 1.0])
    assert faces == [tuple(reversed(tri)) for tri in triangles.tolist()]
    written = signed_volume(vertices, faces)
    assert written == pytest.approx(expected, rel=1e-9)
    assert written * expected > 0
    # The extents reported for the manifest are the ACTOR frame's.
    assert measured["lo_cm"] == pytest.approx(actor.min(0).tolist())
    assert measured["hi_cm"] == pytest.approx(actor.max(0).tolist())
    # And the normals ride the same mirror.
    vn = [tuple(float(t) for t in line.split()[1:4])
          for line in (tmp_path / "tet.obj").read_text(encoding="utf-8").splitlines()
          if line.startswith("vn ")]
    assert vn == [(0.0, 0.0, 1.0)] * 4         # .mdl +y (up) -> actor +Z, Y untouched


def test_a_manifest_from_a_left_handed_conversion_is_stale(tmp_path):
    """A manifest without the exact obj_frame stamp (every conversion
    before decision 19) is re-converted and re-imported by A7's rule."""
    path = tmp_path / "mesh_manifest.json"
    base = {"version": 4, "name": "A4", "parts": [], "textures": [], "components": [],
            "mesh_origin_actor_cm": [-100.0, 0.0, 10.0]}
    path.write_text(json.dumps(base), encoding="utf-8")
    reason = importer.stale_manifest_reason(path)
    assert reason and "mirror" in reason and "decision 19" in reason
    path.write_text(json.dumps({**base, importer.OBJ_FRAME_KEY: "left-handed"}),
                    encoding="utf-8")
    assert "mirror" in importer.stale_manifest_reason(path)
    path.write_text(json.dumps({**base, importer.OBJ_FRAME_KEY: importer.OBJ_FRAME}),
                    encoding="utf-8")
    assert importer.stale_manifest_reason(path) is None
