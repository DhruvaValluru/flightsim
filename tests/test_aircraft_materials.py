"""scripts/ue_aircraft_materials.py: the plan that re-wires an imported
aircraft's materials to its MTL. Interchange's OBJ import left every
textured B747 material black with its texture unplugged (measured
2026-10-07, scripts/ue_inspect_aircraft.py); the plan is what puts the
livery back, so it is pinned here against the converter's own MTL."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ue_aircraft_materials import parse_mtl, plan, read_mtl_dir, texture_asset_name  # noqa: E402

from assets_pipeline.convert import ObjWriter  # noqa: E402


def test_a_textured_material_gets_its_texture_at_full_weight_and_white_base():
    materials = parse_mtl("newmtl mat_BOE\nKd 1.0000 1.0000 1.0000\nmap_Kd BOE.png\n\n"
                          "newmtl rgb_8c8c8c\nKd 0.5490 0.5490 0.5490\n")
    wired = plan(materials)
    assert wired["mat_BOE"] == {"texture": "TEX_BOE", "base_color": (1.0, 1.0, 1.0, 1.0),
                                "weight": 1.0}
    assert wired["rgb_8c8c8c"] == {"texture": None,
                                   "base_color": (0.549, 0.549, 0.549, 1.0), "weight": 0.0}


def test_texture_names_follow_interchange():
    assert texture_asset_name("747-400_engine.png") == "TEX_747-400_engine"
    assert texture_asset_name("textures/BOE.png") == "TEX_BOE"


def test_the_plan_reads_what_the_converter_writes(tmp_path):
    writer = ObjWriter()
    textured = writer.material_key("747-400_wingtop.png", (1.0, 1.0, 1.0), 0.0)
    plain = writer.material_key(None, (0.42, 0.42, 0.42), 0.0)
    tri = [((0.0, 0.0, 0.0), (0.0, 0.0)), ((1.0, 0.0, 0.0), (1.0, 0.0)),
           ((0.0, 1.0, 0.0), (0.0, 1.0))]
    writer.add_triangle(textured, tri)
    writer.add_triangle(plain, tri)
    writer.write(tmp_path / "body.obj")
    wired = plan(read_mtl_dir(tmp_path))
    assert textured == "mat_747_400_wingtop"
    assert wired[textured]["texture"] == "TEX_747-400_wingtop"
    assert wired[textured]["weight"] == 1.0
    assert wired[plain]["texture"] is None
    assert wired[plain]["base_color"][:3] == (0.42, 0.42, 0.42)


def test_every_import_wires_its_materials():
    source = (REPO / "scripts" / "ue_import_aircraft.py").read_text(encoding="utf-8")
    assert "from ue_aircraft_materials import fix_materials" in source
    assert "fix_materials(destination, source_dir)" in source


# -- create_look_instances: the measure path's instances are never written ----

class _Asset:
    def __init__(self, path):
        self.path = path


class _FakeUnreal:
    """Records every write create_look_instances makes (no engine)."""

    def __init__(self, existing):
        self.existing = set(existing)
        self.loaded = {}
        self.writes = []    # (call, asset path)
        fake = self

        class EditorAssetLibrary:
            @staticmethod
            def does_asset_exist(path):
                return path in fake.existing

            @staticmethod
            def load_asset(path):
                return fake.loaded.setdefault(path, _Asset(path))

            @staticmethod
            def save_loaded_asset(asset, only_if_is_dirty=True):
                fake.writes.append(("save_loaded_asset", asset.path))
                return True

        class MaterialEditingLibrary:
            pass

        for call in ("set_material_instance_parent", "set_material_instance_texture_parameter_value",
                     "set_material_instance_vector_parameter_value",
                     "set_material_instance_scalar_parameter_value", "update_material_instance"):
            setattr(MaterialEditingLibrary, call,
                    staticmethod(lambda instance, *rest, _call=call: fake.writes.append((_call, instance.path))))

        class Tools:
            @staticmethod
            def create_asset(name, folder, cls, factory):
                path = f"{folder}/{name}"
                fake.writes.append(("create_asset", path))
                fake.existing.add(path)
                return fake.loaded.setdefault(path, _Asset(path))

        class AssetToolsHelpers:
            @staticmethod
            def get_asset_tools():
                return Tools()

        self.EditorAssetLibrary = EditorAssetLibrary
        self.MaterialEditingLibrary = MaterialEditingLibrary
        self.AssetToolsHelpers = AssetToolsHelpers
        self.MaterialInstanceConstant = object
        self.MaterialInstanceConstantFactoryNew = lambda: None
        self.LinearColor = lambda *rgba: tuple(rgba)


_LOOK_MTL = """newmtl mat_BOE
Kd 0.8 0.8 0.8
map_Kd BOE.png

newmtl rgb_6b6b6b
Kd 0.42 0.42 0.42
d 0.200

newmtl rgb_c0c0c0
Kd 0.75 0.75 0.75
"""


def _converted_model(tmp_path):
    import json
    (tmp_path / "body.mtl").write_text(_LOOK_MTL, encoding="utf-8")
    (tmp_path / "body.obj").write_text("mtllib body.mtl\nv 0 0 0\nv -10 5 0\nv -10 -5 0\n", encoding="utf-8")
    (tmp_path / "mesh_manifest.json").write_text(json.dumps({
        "magic": "flightsim-aircraft-mesh", "version": 3, "name": "J11", "parts": ["body"],
        "asset_path_root": "/Game/Aircraft/J11", "mesh_origin_actor_cm": [0.0, 0.0, 0.0]}),
        encoding="utf-8")


def _run_look(tmp_path, monkeypatch, masters_built=True):
    import aircraft_look as look
    from ue_aircraft_materials import create_look_instances
    root = "/Game/Aircraft/J11"
    existing = {f"{root}/mat_BOE", f"{root}/rgb_6b6b6b", f"{root}/rgb_c0c0c0", f"{root}/TEX_BOE"}
    if masters_built:
        existing |= {f"{look.MASTER_ROOT}/{m}" for m in look.CLASS_MASTERS.values()}
        existing.add(f"{look.MASTER_ROOT}/{look.THIN_GLASS_MASTER}")  # round 5 (L4)
    fake = _FakeUnreal(existing)
    monkeypatch.setitem(sys.modules, "unreal", fake)
    _converted_model(tmp_path)
    made, problems = create_look_instances(root, str(tmp_path), "J11", say=lambda *_: None)
    return fake, made, problems


def test_create_look_instances_writes_only_under_look_and_never_reparents_an_imported_instance(
        tmp_path, monkeypatch):
    fake, made, problems = _run_look(tmp_path, monkeypatch)
    # round 5 (L4): the glass slot gets its Thin Translucent twin too
    assert problems == [] and made == 4
    assert fake.writes
    for call, path in fake.writes:
        # every write is to <root>/Look/MI_<slot>: the imported <root>/<slot>
        # instances every measure render draws are never touched
        assert path.startswith("/Game/Aircraft/J11/Look/MI_"), (call, path)
    assert {p for c, p in fake.writes if c == "create_asset"} == {
        "/Game/Aircraft/J11/Look/MI_mat_BOE", "/Game/Aircraft/J11/Look/MI_rgb_6b6b6b",
        "/Game/Aircraft/J11/Look/MI_rgb_6b6b6b_thin", "/Game/Aircraft/J11/Look/MI_rgb_c0c0c0"}
    assert (tmp_path / "look_manifest.json").is_file()


def test_a_missing_master_is_a_problem_line_not_an_exception(tmp_path, monkeypatch):
    fake, made, problems = _run_look(tmp_path, monkeypatch, masters_built=False)
    assert made == 0 and problems
    assert all("is not built" in p for p in problems)
    assert fake.writes == []
    assert (tmp_path / "look_manifest.json").is_file()


# -- round 1 contact sheet (2026-11-10): every J-11 slot binds ----------------

#: The materials of the earlier J-11 conversion: the five slots the render
#: machine's body kept bound when the full package was imported over it.
_OLD_FIVE = ["mat_Su_27_Flanker_P01", "mat_Glass_Cockpit", "mat_su_27gears",
             "rgb_000000", "rgb_878787"]
#: body.obj's usemtl order for the full package (converted over the pinned files).
_PACKAGE = ["mat_PLAAF2Div", "mat_Glass_Cockpit", "mat_Su_27_Flanker_P01", "mat_su_27gears",
            "rgb_000000", "rgb_878787", "rgb_191919", "mat_panel_front_tex_2048_bevel",
            "rgb_040404", "mat_panel_wcs", "rgb_010600", "mat_grey_blue_flood", "mat_texture",
            "rgb_ff0000", "rgb_292c2d", "rgb_565656", "rgb_ffffff", "rgb_4784c0", "mat_K_36DM",
            "rgb_050505", "rgb_2c2b23", "rgb_557a3a", "rgb_2a2a2a", "mat_fighter_pilot",
            "mat_transp"]


def _round1_rows():
    """The body as the round-1 import left it: the old five bound, the twenty
    new ones appended on WorldGridMaterial."""
    order = _OLD_FIVE + [name for name in _PACKAGE if name not in _OLD_FIVE]
    return [("body", index, name, name if name in _OLD_FIVE else "WorldGridMaterial")
            for index, name in enumerate(order)]


def test_the_round1_refusal_is_the_old_conversion_slots_plus_the_new_ones():
    import ue_aircraft_materials as m

    report = m.classify_slots(_round1_rows(), _PACKAGE)
    assert report["bound"] == 5 and len(report["unbound"]) == 20
    # The refusal's own first rows (runs/visual/head2 shot a, 2026-11-10).
    assert report["unbound"][:3] == ["body[5] mat_PLAAF2Div -> WorldGridMaterial",
                                     "body[6] rgb_191919 -> WorldGridMaterial",
                                     "body[7] mat_panel_front_tex_2048_bevel -> WorldGridMaterial"]


def test_bind_slots_puts_every_unbound_slot_on_its_own_material():
    import ue_aircraft_materials as m

    plan_rows = m.plan_slot_bindings(_round1_rows(), _PACKAGE)
    assert len(plan_rows) == 20
    assert ("body", 5, "mat_PLAAF2Div") in plan_rows
    assert all(index >= 5 for _, index, _ in plan_rows)
    rebound = [(part, index, name, name) for part, index, name, _ in _round1_rows()]
    assert m.plan_slot_bindings(rebound, _PACKAGE) == []
    assert m.classify_slots(rebound, _PACKAGE)["unbound"] == []


def test_a_slot_named_for_no_mtl_material_is_left_to_the_slot_check():
    import ue_aircraft_materials as m

    rows = [("body", 0, "Material_1", None), ("body", 1, "mat_PLAAF2Div", None)]
    assert m.plan_slot_bindings(rows, _PACKAGE) == [("body", 1, "mat_PLAAF2Div")]


def test_a_beauty_copy_in_another_slot_order_is_an_incomplete_import():
    import ue_aircraft_materials as m

    stale = [row[2] for row in _round1_rows()]
    beauty = {"body": {"part": "body_beauty", "triangles": 1}}
    rows = ([("body", i, n, n) for i, n in enumerate(stale)]
            + [("body_beauty", i, n, n) for i, n in enumerate(_PACKAGE)])
    assert len(m.beauty_slot_mismatches(m.classify_slots(rows, _PACKAGE), beauty)) == 1
    fresh = ([("body", i, n, n) for i, n in enumerate(_PACKAGE)]
             + [("body_beauty", i, n, n) for i, n in enumerate(_PACKAGE)])
    assert m.beauty_slot_mismatches(m.classify_slots(fresh, _PACKAGE), beauty) == []


def test_texture_names_are_sanitised_as_ue_names_the_asset():
    import aircraft_look
    import ue_aircraft_materials as m

    # panel.wcs.png: "." is not allowed in an object name (NameTypes.h).
    assert texture_asset_name("panel.wcs.png") == "TEX_panel_wcs"
    assert texture_asset_name("panel-front-tex-2048-bevel.png") == "TEX_panel-front-tex-2048-bevel"
    assert aircraft_look.texture_asset_name("panel.wcs.png") == "TEX_panel_wcs"
    assert aircraft_look.INVALID_ASSET_NAME_CHARACTERS == m.INVALID_ASSET_NAME_CHARACTERS
    wired = plan(parse_mtl("newmtl mat_panel_wcs\nKd 1 1 1\nmap_Kd panel.wcs.png\n"))
    assert wired["mat_panel_wcs"]["texture"] == "TEX_panel_wcs"


def test_a_beauty_manifest_imports_fresh_and_binds_before_wiring():
    source = (REPO / "scripts" / "ue_import_aircraft.py").read_text(encoding="utf-8")
    run = source[source.index("def run():"):]
    assert run.index("remove_stale_meshes(") < run.index("import_part(")
    assert run.index("import_part(") < run.index("bind_slots(") < run.index("fix_materials(")
    assert run.index("import_missing_textures(") < run.index("bind_slots(")
    assert run.index("beauty_slot_mismatches(") < run.index("write_import_record(")
    # Only for a manifest with beauty_parts: no other airframe's import changes.
    for call in ("remove_stale_meshes(", "import_missing_textures("):
        head = run[:run.index(call)].splitlines()
        assert 'if manifest.get("beauty_parts"):' in "\n".join(head[-4:]), call
