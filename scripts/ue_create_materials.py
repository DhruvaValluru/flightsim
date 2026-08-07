"""Create the material assets the render commandlet loads. Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript -script=scripts/ue_create_materials.py

Build-time asset step, command-line only. Currently one asset:

* /Game/FlightSim/M_VertexColor -- vertex colour into base colour, constant
  high roughness. The georeferenced terrain writes its slope/altitude
  classification into vertex colours; this is the material that shows them,
  and the commandlet refuses to render classified terrain without it rather
  than falling back to the default material silently.
"""

import unreal

PATH = "/Game/FlightSim"
NAME = "M_VertexColor"
FULL = f"{PATH}/{NAME}"


def run():
    if unreal.EditorAssetLibrary.does_asset_exist(FULL):
        print(f"MATERIAL-EXISTS: {FULL}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(NAME, PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    lib = unreal.MaterialEditingLibrary
    vertex = lib.create_material_expression(
        material, unreal.MaterialExpressionVertexColor, -350, 0)
    lib.connect_material_property(vertex, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -350, 250)
    rough.set_editor_property("r", 0.92)
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(FULL)
    print(f"MATERIAL-CREATED: {FULL}")


run()
