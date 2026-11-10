"""Round 2 of the visual overhaul, cockpit-airframe lane: the beauty body
(crease-angle normals and two-sided back faces), the slot check and import
record, the LF checkout, and the pilot-eye cockpit camera. All without the
engine."""

import json
import math
import subprocess
from pathlib import Path

import pytest

from assets_pipeline import importer
from assets_pipeline.acmodel import parse_ac
from assets_pipeline.smooth_normals import DEFAULT_CREASE_DEG, flipped, vertex_normals

ROOT = Path(__file__).resolve().parents[1]
FX_CPP = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
          "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")


def _hinge(angle_deg):
    """Two triangles sharing the edge (0,0,0)-(0,1,0), the second folded
    down by ``angle_deg`` about it; both counter-clockwise from +z."""
    a = math.radians(angle_deg)
    t1 = ((0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    t1 = (t1[0], t1[2], t1[1])     # CCW seen from +z: normal +z
    far = (math.cos(a), 0.0, -math.sin(a))
    t2 = ((0.0, 0.0, 0.0), far, (0.0, 1.0, 0.0))
    return [t1, t2]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


# -- smooth normals -----------------------------------------------------------


def test_faces_within_the_crease_share_one_normal():
    tris = _hinge(20.0)
    normals = vertex_normals(tris, [1, 1], [True, True], [30.0, 30.0])
    # The shared corner (0,0,0) has one normal on both triangles, between the two faces.
    assert normals[0][0] == pytest.approx(normals[1][0], abs=1e-9)
    assert normals[0][0][2] > 0.9 and normals[0][0][0] > 0.0
    assert all(abs(math.sqrt(_dot(n, n)) - 1.0) < 1e-9 for tri in normals for n in tri)


def test_faces_past_the_crease_keep_their_own_normals():
    tris = _hinge(60.0)
    normals = vertex_normals(tris, [1, 1], [True, True], [30.0, 30.0])
    assert normals[0][0] == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)
    assert normals[1][0] != pytest.approx(normals[0][0], abs=1e-3)


def test_flat_surfaces_and_other_objects_do_not_smooth():
    tris = _hinge(10.0)
    flat = vertex_normals(tris, [1, 1], [False, False], [180.0, 180.0])
    assert flat[0] == ((0.0, 0.0, 1.0),) * 3
    apart = vertex_normals(tris, [1, 2], [True, True], [180.0, 180.0])
    assert apart[0][0] == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)


def test_default_crease_and_degenerate_triangles():
    tris = _hinge(50.0) + [((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))]
    normals = vertex_normals(tris, [1, 1, 1], [True] * 3, [None] * 3)
    assert DEFAULT_CREASE_DEG > 50.0
    assert normals[0][0] == pytest.approx(normals[1][0], abs=1e-9)   # 50 < default crease
    assert all(math.isfinite(c) for c in normals[2][0])
    assert flipped((0.0, 1.0, 0.0)) == (0.0, -1.0, 0.0)
    with pytest.raises(ValueError):
        vertex_normals(tris, [1], [True], [None])


def test_the_ac_reader_keeps_crease_and_the_smooth_flag(tmp_path):
    ac = tmp_path / "t.ac"
    ac.write_text("AC3Db\nMATERIAL \"m\" rgb 1 1 1  amb 0.2 0.2 0.2  emis 0 0 0  spec 0 0 0  "
                  "shi 10  trans 0\nOBJECT world\nkids 1\nOBJECT poly\nname \"a\"\ncrease 45.0\n"
                  "numvert 3\n0 0 0\n1 0 0\n0 1 0\nnumsurf 2\nSURF 0x30\nmat 0\nrefs 3\n0 0 0\n"
                  "1 0 0\n2 0 0\nSURF 0x0\nmat 0\nrefs 3\n0 0 0\n2 0 0\n1 0 0\nkids 0\n",
                  encoding="utf-8")
    model = parse_ac(ac)
    obj = [o for o in model.objects() if o.name == "a"][0]
    assert obj.crease == 45.0
    assert obj.surfaces[0].smooth and obj.surfaces[0].two_sided
    assert not obj.surfaces[1].smooth and not obj.surfaces[1].two_sided


# -- the beauty body ----------------------------------------------------------


def test_the_beauty_body_keeps_positions_slots_and_adds_back_faces(tmp_path):
    from assets_pipeline.convert import BEAUTY_BODY_PART, ObjWriter, _write_beauty_mesh

    body = ObjWriter()
    rows = []
    tris = [[((0.0, 0.0, 0.0), (0, 0)), ((0.0, 100.0, 0.0), (1, 0)), ((100.0, 0.0, 0.0), (0, 1))],
            [((0.0, 0.0, 0.0), (0, 0)), ((0.0, 0.0, 100.0), (1, 0)), ((0.0, 100.0, 0.0), (0, 1))]]
    for i, (key, tri) in enumerate((("rgb_aaaaaa", tris[0]), ("mat_skin", tris[1]))):
        k = body.material_key(None if key.startswith("rgb") else "skin.png",
                              (0.666, 0.666, 0.666), 0.0)
        body.add_triangle(k, tri)
        rows.append((k, tri, 1, True, 30.0, i == 1))
    body.write(tmp_path / "body.obj")
    record = _write_beauty_mesh(rows, {"normals": "crease", "two_sided": True}, body, tmp_path)
    assert record["body"]["part"] == BEAUTY_BODY_PART
    assert record["body"]["back_faces"] == 1 and record["body"]["triangles"] == 3
    plain = (tmp_path / "body.obj").read_text(encoding="utf-8")
    beauty = (tmp_path / f"{BEAUTY_BODY_PART}.obj").read_text(encoding="utf-8")
    assert "vn " not in plain and all(len(l.split()[1].split("/")) == 2
                                      for l in plain.splitlines() if l.startswith("f "))
    assert beauty.count("\nvn ") == 9
    assert all(len(l.split()[1].split("/")) == 3 for l in beauty.splitlines() if l.startswith("f "))
    # Same material order (slot order) as the measured body.
    usemtl = lambda text: [l.split()[1] for l in text.splitlines() if l.startswith("usemtl")]
    assert usemtl(beauty) == usemtl(plain)
    # Same positions: the first triangles' vertices are the body's.
    verts = lambda text: [l for l in text.splitlines() if l.startswith("v ")]
    assert verts(beauty)[:6] == verts(plain)
    assert (tmp_path / f"{BEAUTY_BODY_PART}.mtl").read_text(encoding="utf-8") == \
        (tmp_path / "body.mtl").read_text(encoding="utf-8")


def test_the_j11_and_c172p_configs_ask_for_the_beauty_body_and_no_other_airframe_does():
    for path in sorted((ROOT / "assets/aircraft_config").glob("*.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        if path.stem == "J11":
            assert config["beauty_mesh"] == {**config["beauty_mesh"], "normals": "crease",
                                             "two_sided": True}
        elif path.stem == "c172p":
            # Round 1 web scene 12: the inner glass shells, flipped; nothing two-sided.
            assert config["beauty_mesh"] == {**config["beauty_mesh"], "normals": "crease",
                                             "two_sided": False}
            assert "glas_interior" in config["beauty_mesh"]["flip_objects"]
        else:
            assert "beauty_mesh" not in config, path.name


def test_flip_objects_face_the_other_way_with_no_back_face(tmp_path):
    from assets_pipeline.convert import BEAUTY_BODY_PART, ObjWriter, _write_beauty_mesh

    body = ObjWriter()
    tri = [((0.0, 0.0, 0.0), (0, 0)), ((0.0, 100.0, 0.0), (1, 0)), ((100.0, 0.0, 0.0), (0, 1))]
    key = body.material_key("glass-alpha.png", (1.0, 1.0, 1.0), 0.66)
    rows = []
    for serial, name in ((1, "glas_interior"), (2, "Panel_0")):
        body.add_triangle(key, tri)
        rows.append((key, tri, serial, True, 30.0, True, name))
    body.write(tmp_path / "body.obj")
    record = _write_beauty_mesh(rows, {"normals": "crease", "two_sided": True,
                                       "flip_objects": ["glas_interior"]}, body, tmp_path)
    # The flipped shell: no back face; the other two-sided surface keeps its back face.
    assert record["body"]["flipped_faces"] == 1 and record["body"]["back_faces"] == 1
    assert record["body"]["triangles"] == 3
    beauty = (tmp_path / f"{BEAUTY_BODY_PART}.obj").read_text(encoding="utf-8")
    vs = [tuple(map(float, l.split()[1:])) for l in beauty.splitlines() if l.startswith("v ")]
    vns = [tuple(map(float, l.split()[1:])) for l in beauty.splitlines() if l.startswith("vn ")]
    faces = [[tuple(int(i) for i in c.split("/")) for c in l.split()[1:]]
             for l in beauty.splitlines() if l.startswith("f ")]

    def winding_normal(face):
        a, b, c = (vs[corner[0] - 1] for corner in face)
        u = [b[i] - a[i] for i in range(3)]
        w = [c[i] - a[i] for i in range(3)]
        return (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])

    flipped_face, kept_face = faces[0], faces[1]
    # Same positions, opposite winding, and the corner normals turned with it.
    assert sorted(vs[c[0] - 1] for c in flipped_face) == sorted(vs[c[0] - 1] for c in kept_face)
    assert _dot(winding_normal(flipped_face), winding_normal(kept_face)) < 0
    assert _dot(vns[flipped_face[0][2] - 1], vns[kept_face[0][2] - 1]) < 0
    # One slot, as the measured body has.
    usemtl = lambda text: [l.split()[1] for l in text.splitlines() if l.startswith("usemtl")]
    assert usemtl(beauty) == usemtl((tmp_path / "body.obj").read_text(encoding="utf-8"))


def test_flip_objects_must_be_name_patterns():
    from assets_pipeline.convert import ConvertError, _beauty_mesh_config

    assert _beauty_mesh_config({"beauty_mesh": {"normals": "crease", "flip_objects": ["a.*"]}})
    with pytest.raises(ConvertError, match="flip_objects"):
        _beauty_mesh_config({"beauty_mesh": {"normals": "crease", "flip_objects": "glas"}})


def test_the_c172p_cockpit_camera_is_at_its_model_s_left_seat_eye(monkeypatch, tmp_path):
    """Round 1 web scene 12: the FDM EYEPOINT (y 0) plus COCKPIT_EYE_NUDGE_M
    put the c172p camera in the right seat, 0.25 m ahead of the modelled
    pilot's eye (c172p-views.xml view 0, now the config's views.pilot_eye)."""
    import core.scenario.camera as camera

    monkeypatch.setattr(camera, "_COCKPIT_CACHE", {})
    monkeypatch.setattr(camera, "_COCKPIT_BASIS", {})
    monkeypatch.setattr(camera, "_MESH_GENERATED_DIR", tmp_path)
    config = json.loads((ROOT / "assets/aircraft_config/c172p.json").read_text(encoding="utf-8"))
    assert config["views"]["pilot_eye"]["model_m"] == [0.36, -0.21, 0.273]
    # No manifest: the model origin is taken at the FDM's VRP (c172p.xml 42.6, 0, 38.5 in).
    vrp_actor = (-42.6 * 0.0254, 0.0, 38.5 * 0.0254)
    cg_actor = (-41.0 * 0.0254, 0.0, 36.5 * 0.0254)
    no_manifest = camera.derive_cockpit_offset("c172p")
    assert no_manifest == pytest.approx(
        (-0.36 + vrp_actor[0] - cg_actor[0], -0.21, 0.273 + vrp_actor[2] - cg_actor[2]
         + camera.PILOT_EYE_NUDGE_M[2]), abs=1e-3)
    assert "VRP" in camera.cockpit_offset_basis("c172p")
    # With the converted manifest (the measured origin, -118.309, 0, 97.422 cm
    # from the pinned c172-common.ac): the eye the convert writes.
    monkeypatch.setattr(camera, "_COCKPIT_CACHE", {})
    (tmp_path / "c172p").mkdir()
    (tmp_path / "c172p" / "mesh_manifest.json").write_text(json.dumps(
        {"views": {"pilot_eye": {"actor_cm": [-154.31, -21.0, 124.72]}}}), encoding="utf-8")
    offset = camera.derive_cockpit_offset("c172p")
    assert offset == pytest.approx((-0.502, -0.21, 0.35), abs=2e-3)
    assert "mesh manifest" in camera.cockpit_offset_basis("c172p")
    # The left seat, aft of the round-1 station (-0.248, +0.3, +0.392).
    assert offset[1] < 0 and offset[0] < -0.248 - 0.2


# -- import record and slots --------------------------------------------------


def test_the_import_record_names_match_the_ue_side():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ue_aircraft_materials", ROOT / "scripts/ue_aircraft_materials.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.IMPORT_RECORD_NAME == importer.IMPORT_RECORD_NAME
    assert module.IMPORT_RECORD_MAGIC == importer.IMPORT_RECORD_MAGIC
    report = module.classify_slots(
        [("body", 0, "mat_PLAAF2Div", "mat_PLAAF2Div"), ("body", 1, "x", "WorldGridMaterial"),
         ("body", 2, "y", None)], ["mat_PLAAF2Div", "rgb_000000"])
    assert report["bound"] == 1 and len(report["unbound"]) == 2
    assert "WorldGridMaterial" in report["unbound"][0]


def _manifest(tmp_path, beauty=True):
    manifest = {"name": "J11", "parts": ["body"], "asset_path_root": "/Game/Aircraft/J11",
                "triangles": {"body": 1}}
    if beauty:
        manifest["beauty_parts"] = {"body": {"part": "body_beauty", "triangles": 2}}
    path = tmp_path / "mesh_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_a_manifest_with_beauty_parts_needs_its_own_finished_import_record(tmp_path):
    import hashlib

    path, manifest = _manifest(tmp_path)
    assert importer.imported_parts(manifest) == ["body", "body_beauty"]
    assert "no import record" in importer.import_record_reason(path)
    record = tmp_path / importer.IMPORT_RECORD_NAME
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    record.write_text(json.dumps({"magic": importer.IMPORT_RECORD_MAGIC,
                                  "manifest_sha256": "0" * 64, "unbound": []}), encoding="utf-8")
    assert "another conversion" in importer.import_record_reason(path)
    record.write_text(json.dumps({"magic": importer.IMPORT_RECORD_MAGIC,
                                  "manifest_sha256": digest, "unbound": ["body[3] a -> None"]}),
                      encoding="utf-8")
    assert "without their MTL material" in importer.import_record_reason(path)
    assert importer.unbound_slots(path) == ["body[3] a -> None"]
    record.write_text(json.dumps({"magic": importer.IMPORT_RECORD_MAGIC,
                                  "manifest_sha256": digest, "unbound": []}), encoding="utf-8")
    assert importer.import_record_reason(path) is None


def test_a_beauty_slot_mismatch_reimports_and_refuses(tmp_path):
    import hashlib

    path, _ = _manifest(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    row = "body_beauty slots ['b', 'a'] are not body's ['a', 'b']"
    (tmp_path / importer.IMPORT_RECORD_NAME).write_text(json.dumps(
        {"magic": importer.IMPORT_RECORD_MAGIC, "manifest_sha256": digest, "unbound": [],
         "slot_mismatches": [row]}), encoding="utf-8")
    assert "beauty part" in importer.import_record_reason(path)
    assert importer.unbound_slots(path) == [row]


def test_other_airframes_are_not_held_to_the_import_record(tmp_path):
    path, manifest = _manifest(tmp_path, beauty=False)
    assert importer.import_record_reason(path) is None
    assert importer.imported_parts(manifest) == ["body"]


def test_the_material_slots_refusal_is_catalogued():
    from core.messages import is_catalogued

    assert is_catalogued("aircraft.material_slots")
    assert '"aircraft.material_slots"' in (ROOT / "assets_pipeline/importer.py").read_text(
        encoding="utf-8")


def test_a_crlf_checkout_is_rewritten_with_lf(tmp_path):
    repo = tmp_path / "src"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@example.invalid")
    run("config", "user.name", "t")
    (repo / "a.xml").write_bytes(b"<a>\n<b/>\n</a>\n")
    run("add", "a.xml")
    run("commit", "-q", "-m", "x")
    run("config", "core.autocrlf", "true")
    (repo / "a.xml").unlink()
    run("checkout", "--", "a.xml")
    assert b"\r\n" in (repo / "a.xml").read_bytes()
    lines = []
    assert importer._rewrite_checkout_lf(repo, lines.append)
    assert (repo / "a.xml").read_bytes() == b"<a>\n<b/>\n</a>\n"
    assert not importer._rewrite_checkout_lf(repo, lines.append)   # already LF: once only


# -- the engine side ----------------------------------------------------------


def test_the_beauty_swap_is_in_the_look_path_only():
    apply = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::ApplyMaterials"):]
    apply = apply[:apply.index("\nvoid FFlightSimAircraftFX::", 10)]
    assert "SetStaticMesh(BeautyMesh)" in apply
    assert "MaterialSlotName == To[Slot].MaterialSlotName" in apply
    assert 'TEXT("beauty_meshes")' in apply and 'TEXT("slots_without_material")' in apply
    assert 'TEXT("beauty_parts")' in FX_CPP
    check = (ROOT / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
    assert "# -- cockpit-airframe (visual overhaul round 2" in check
    assert "ENGINE_API virtual bool SetStaticMesh(class UStaticMesh* NewMesh);" in check


def test_the_import_script_imports_the_beauty_part_with_its_normals():
    text = (ROOT / "scripts/ue_import_aircraft.py").read_text(encoding="utf-8")
    assert '"recompute_normals", False' in text
    assert "build.recompute_normals = False" in text
    assert 'manifest.get("beauty_parts")' in text
    assert "write_import_record(manifest_path, report)" in text


# -- the cockpit camera -------------------------------------------------------


def test_the_j11_cockpit_camera_is_at_the_model_s_pilot_eye(monkeypatch, tmp_path):
    import core.scenario.camera as camera

    monkeypatch.setattr(camera, "_COCKPIT_CACHE", {})
    monkeypatch.setattr(camera, "_COCKPIT_BASIS", {})
    monkeypatch.setattr(camera, "_MESH_GENERATED_DIR", tmp_path)
    (tmp_path / "J11").mkdir()
    (tmp_path / "J11" / "mesh_manifest.json").write_text(json.dumps(
        {"views": {"pilot_eye": {"actor_cm": [-522.99, 0.0, 134.43]}}}), encoding="utf-8")
    offset = camera.derive_cockpit_offset("J11")
    cg_actor = (-517.35 * 0.0254, 0.0, -21.56 * 0.0254)
    assert offset == pytest.approx((-5.2299 - cg_actor[0] + camera.PILOT_EYE_NUDGE_M[0],
                                    camera.PILOT_EYE_NUDGE_M[1],
                                    1.3443 - cg_actor[2] + camera.PILOT_EYE_NUDGE_M[2]), abs=1e-3)
    assert "mesh manifest" in camera.cockpit_offset_basis("J11")
    # Aft of and above the round-1 station (FDM EYEPOINT + nudge: 8.41 fwd, 1.61 up).
    assert offset[0] < 8.41 - 0.4 and offset[2] > 1.61 + 0.2
