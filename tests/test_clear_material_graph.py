"""Round 1456: an in-place material rebuild clears its graph completely.

UE 5.7's MaterialEditingLibrary.DeleteAllMaterialExpressions range-fors over
Material->GetExpressions() while removing from it, so about every other node
survives; a surviving VolumetricAdvancedMaterialOutput plus the rebuilt one
failed M_FlightSimCloudLayersLit's compile ("only one Volumetric Advanced
Output node"). Every in-place clear goes through clear_material_graph, which
deletes what the library call left and proves the graph empty, and
storm_scattering refuses a second advanced output."""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (REPO / "scripts/ue_create_materials.py").read_text(encoding="utf-8")


def _function(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SCRIPT, node)
    raise AssertionError(name)


def _literal(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def test_every_in_place_clear_goes_through_the_helper():
    calls = SCRIPT.count("delete_all_material_expressions(material)")
    helper = _function("clear_material_graph")
    # only the helper itself calls the library's (leaky) clear
    assert calls == helper.count("delete_all_material_expressions(material)") == 2
    for maker in ("_world_beauty_material", "_weather_material"):
        assert "clear_material_graph(material)" in _function(maker)
    impostor = SCRIPT[SCRIPT.index('name = "M_FlightSimCloudImpostor"'):]
    assert "clear_material_graph(material)" in impostor.split("tools = ", 1)[0]


def test_the_helper_deletes_the_leftovers_and_proves_the_graph_empty():
    helper = _function("clear_material_graph")
    assert "for node in material_expressions(material):" in helper
    assert "lib.delete_material_expression(material, node)" in helper
    assert "get_num_material_expressions(material)" in helper
    assert "raise RuntimeError" in helper
    walker = _function("material_expressions")
    assert "unreal.ObjectIterator(expression_class)" in walker
    assert "get_outer() == material and unreal.SystemLibrary.is_valid(node)" in walker


def test_storm_scattering_refuses_a_second_advanced_output():
    body = _function("storm_scattering")
    check = body.index("material_expressions(material, unreal.MaterialExpressionVolumetricAdvancedMaterialOutput)")
    assert check < body.index("lib.create_material_expression(")
    assert "raise RuntimeError" in body[check:body.index("lib.create_material_expression(")]


def test_the_lit_cloud_material_is_rebuilt_on_windows():
    assert _literal("WORLD_GENERATIONS")["M_FlightSimCloudLayersLit"] == "3"
