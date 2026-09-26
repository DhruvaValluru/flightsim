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

* /Game/FlightSim/M_VertexColorUnlit -- the tornado funnel marker (below).

Both terrain materials expose one scalar parameter, "Wetness" (default 0),
the name FlightSimVisualScene.cpp ApplyWetness sets from the card's
precipitation: the only wet-surface coupling. It lerps roughness from
0.92 (dry) toward 0.25 (wet) and darkens the base colour by up to 30 %;
dry (0) is the constant-roughness look the materials had before it. The
node and pin names below are the UE Python API's; nothing here is run
without an engine, so the Windows build is where they are checked.

* /Game/FlightSim/M_CustomStencilID -- Phase 2 (packages B + C): the
  post-process material the -labels ID pass renders through. It REPLACES
  the tonemapper and emits SceneTexture:CustomStencil as a flat float, so
  the render commandlet's SCS_FinalColorHDR capture reads each pixel's
  custom-stencil value (= the card's object int_id, set on every labelled
  mesh component) back as a raw number, anti-aliasing off. The commandlet
  refuses -labels by name when this asset is absent rather than writing
  an ID image it did not measure.
"""

import unreal

PATH = "/Game/FlightSim"

#: The parameter ApplyWetness looks up by this exact name
#: (FlightSimVisualScene.cpp FindScalarParameter(Material, TEXT("Wetness"))).
WETNESS_PARAMETER = "Wetness"
ROUGHNESS_DRY = 0.92
ROUGHNESS_WET = 0.25
WET_DARKENING = 0.3


def add_wetness(material, lib, base_colour_node, base_output, x):
    """The one wet-surface coupling: a scalar parameter "Wetness" (default
    0, the name FlightSimVisualScene.cpp ApplyWetness sets) lerps roughness
    from 0.92 (dry) toward 0.25 (wet) and darkens base colour by up to
    30 %. Wires MP_BASE_COLOR and MP_ROUGHNESS; the caller wires nothing
    else to those two."""
    wet = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, x, 400)
    wet.set_editor_property("parameter_name", WETNESS_PARAMETER)
    wet.set_editor_property("default_value", 0.0)
    dry_r = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, x, 250)
    dry_r.set_editor_property("r", ROUGHNESS_DRY)
    wet_r = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, x, 300)
    wet_r.set_editor_property("r", ROUGHNESS_WET)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionLinearInterpolate, x + 200, 250)
    lib.connect_material_expressions(dry_r, "", rough, "A")
    lib.connect_material_expressions(wet_r, "", rough, "B")
    lib.connect_material_expressions(wet, "", rough, "Alpha")
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    darken = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, x, 500)
    darken.set_editor_property("r", WET_DARKENING)
    scale = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, x + 200, 450)
    lib.connect_material_expressions(wet, "", scale, "A")
    lib.connect_material_expressions(darken, "", scale, "B")
    one_minus = lib.create_material_expression(
        material, unreal.MaterialExpressionOneMinus, x + 350, 450)
    lib.connect_material_expressions(scale, "", one_minus, "")
    colour = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, x + 500, 0)
    lib.connect_material_expressions(base_colour_node, base_output, colour, "A")
    lib.connect_material_expressions(one_minus, "", colour, "B")
    lib.connect_material_property(colour, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)


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
    add_wetness(material, lib, vertex, "", -350)
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
    add_wetness(material, lib, texture, "RGB", -400)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")




def create_vertex_colour_unlit():
    """The tornado funnel's material: a MARKER must read from every side
    under any sun, so it is UNLIT -- vertex colour straight into emissive.
    (Measured: the lit vertex-colour material rendered the funnel black
    whenever the camera faced its unlit side, i.e. most of every chase
    shot in the storm look's low sun.)"""
    full = f"{PATH}/M_VertexColorUnlit"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_VertexColorUnlit", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    material.set_editor_property("shading_model",
                                 unreal.MaterialShadingModel.MSM_UNLIT)
    lib = unreal.MaterialEditingLibrary
    vertex = lib.create_material_expression(
        material, unreal.MaterialExpressionVertexColor, -350, 0)
    lib.connect_material_property(vertex, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_custom_stencil_id():
    """The ID pass's post-process material (Phase 2, contracts section 1).

    Post-process domain, blendable location "Replacing the Tonemapper",
    one SceneTexture expression reading CustomStencil into emissive
    colour. Nothing else: no tonemapping, no exposure, no dither, so the
    value that reaches the RTF_R32f target is the stencil integer the
    commandlet assigned (verified on Windows by the first -labels frame:
    render.json labels.non_integer_id_pixels == 0 and numpy.unique of
    frame_0000_mask.png is a subset of the card's objects[].int_id + 0).
    """
    full = f"{PATH}/M_CustomStencilID"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_CustomStencilID", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    material.set_editor_property("material_domain",
                                 unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property(
        "blendable_location",
        unreal.BlendableLocation.BL_REPLACING_TONEMAPPER)
    lib = unreal.MaterialEditingLibrary
    stencil = lib.create_material_expression(
        material, unreal.MaterialExpressionSceneTexture, -400, 0)
    stencil.set_editor_property("scene_texture_id",
                                unreal.SceneTextureId.PPI_CUSTOM_STENCIL)
    lib.connect_material_property(stencil, "Color",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


create_vertex_colour()
create_terrain_imagery()
create_vertex_colour_unlit()
create_custom_stencil_id()
