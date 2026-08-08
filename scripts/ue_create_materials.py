"""Create the material assets the render commandlet loads. Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript -script=scripts/ue_create_materials.py

Build-time asset step, command-line only. Two assets:

* /Game/FlightSim/M_VertexColor -- vertex colour into base colour, constant
  high roughness. The georeferenced terrain writes its slope/altitude
  classification into vertex colours; this is the material that shows them,
  and the commandlet refuses to render classified terrain without it rather
  than falling back to the default material silently.

* /Game/FlightSim/M_TerrainImagery -- a texture parameter ("Imagery")
  sampled by UV0 into base colour, same constant roughness. The terrain
  mesh's UV0 is the raster grid normalised (col/width, row/height) and the
  draped texture shares the bake's CRS/origin/extent by construction
  (core/terrain/imagery.py), so this material has no registration
  parameters to get wrong: the alignment lives in the data, and the
  landmark-projection check on a rendered frame verifies it.
"""

import unreal

PATH = "/Game/FlightSim"


def create_vertex_colour():
    full = f"{PATH}/M_VertexColor"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_VertexColor", PATH, unreal.Material,
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
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_terrain_imagery():
    full = f"{PATH}/M_TerrainImagery"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_TerrainImagery", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    lib = unreal.MaterialEditingLibrary
    texture = lib.create_material_expression(
        material, unreal.MaterialExpressionTextureSampleParameter2D, -400, 0)
    texture.set_editor_property("parameter_name", "Imagery")
    lib.connect_material_property(texture, "RGB",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -400, 250)
    rough.set_editor_property("r", 0.92)
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


create_vertex_colour()
create_terrain_imagery()
