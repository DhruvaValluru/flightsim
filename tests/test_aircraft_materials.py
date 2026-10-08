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
