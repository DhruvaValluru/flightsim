"""Create the material assets the render commandlet loads. Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript -script=scripts/ue_create_materials.py

Build-time asset step, command-line only. The first three serve every
render; M_Moon, M_StarEmissive and M_TerrainImageryNight serve only the
physical sky (-sky=, see their docstrings). Existing assets are skipped,
so re-running after an update adds only what is new. The core assets:

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


def _new_material(name):
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return None, full
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit(f"could not create material asset {full}")
    return material, full


def _save(material, full):
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_moon():
    """Physical sky: the moon sphere. LIT, grey, fully rough -- the sun
    light shading it IS the phase, so it must not be unlit. "Albedo" is
    the plan's 0.12 (the moon's mean visual albedo)."""
    material, full = _new_material("M_Moon")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    albedo = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -400, 0)
    albedo.set_editor_property("parameter_name", "Albedo")
    albedo.set_editor_property("default_value", 0.12)
    lib.connect_material_property(albedo, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -400, 200)
    rough.set_editor_property("r", 1.0)
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    spec = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -400, 300)
    spec.set_editor_property("r", 0.0)
    lib.connect_material_property(spec, "",
                                  unreal.MaterialProperty.MP_SPECULAR)
    _save(material, full)


def create_star_emissive():
    """Physical sky: one star disc. UNLIT, OPAQUE: "Color" (max channel 1)
    times "Luminance" (cd/m^2, computed per magnitude bin by
    core/sky/plan.py) into emissive. Opaque so clouds and the
    atmosphere's aerial perspective apply to stars like to any surface."""
    material, full = _new_material("M_StarEmissive")
    if material is None:
        return
    material.set_editor_property("shading_model",
                                 unreal.MaterialShadingModel.MSM_UNLIT)
    lib = unreal.MaterialEditingLibrary
    colour = lib.create_material_expression(
        material, unreal.MaterialExpressionVectorParameter, -600, 0)
    colour.set_editor_property("parameter_name", "Color")
    colour.set_editor_property("default_value",
                               unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    lum = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -600, 200)
    lum.set_editor_property("parameter_name", "Luminance")
    lum.set_editor_property("default_value", 0.0)
    mul = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, -300, 100)
    lib.connect_material_expressions(colour, "", mul, "A")
    lib.connect_material_expressions(lum, "", mul, "B")
    lib.connect_material_property(mul, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    _save(material, full)


def create_terrain_imagery_night():
    """Physical sky: M_TerrainImagery plus emission. "NightLights" is the
    verified VIIRS drape (core/terrain/nightlights.py) on the SAME UV
    grid as "Imagery"; "NightLuminance" scales it to cd/m^2. A separate
    asset so the calibrated M_TerrainImagery renders stay untouched."""
    material, full = _new_material("M_TerrainImageryNight")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    texture = lib.create_material_expression(
        material, unreal.MaterialExpressionTextureSampleParameter2D, -500, 0)
    texture.set_editor_property("parameter_name", "Imagery")
    lib.connect_material_property(texture, "RGB",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -500, 250)
    rough.set_editor_property("r", 0.92)
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    lights = lib.create_material_expression(
        material, unreal.MaterialExpressionTextureSampleParameter2D, -700, 400)
    lights.set_editor_property("parameter_name", "NightLights")
    scale = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -700, 650)
    scale.set_editor_property("parameter_name", "NightLuminance")
    scale.set_editor_property("default_value", 0.0)
    mul = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, -350, 500)
    lib.connect_material_expressions(lights, "RGB", mul, "A")
    lib.connect_material_expressions(scale, "", mul, "B")
    lib.connect_material_property(mul, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    _save(material, full)


create_vertex_colour()
create_terrain_imagery()
create_vertex_colour_unlit()
create_moon()
create_star_emissive()
create_terrain_imagery_night()
