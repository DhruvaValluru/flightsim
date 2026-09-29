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

* /Game/FlightSim/M_WorldNormalPass, M_VelocityPass, M_BaseColorPass --
  I6 (gap S3): the three ground-truth passes -passes=normal,velocity,
  albedo render through, built on the M_CustomStencilID pattern (post-
  process domain, replacing the tonemapper, one SceneTexture node into
  emissive). The SceneTexture ids are the UE 5.7 ESceneTextureId values
  PPI_WorldNormal, PPI_Velocity and PPI_BaseColor (Python enum spellings
  PPI_WORLD_NORMAL, PPI_VELOCITY, PPI_BASE_COLOR). The normal and the
  velocity are SIGNED, and whether a tonemapper-replacing emissive keeps
  a negative value through the FinalColorHDR readback is not established
  here, so both are offset in the material (value * 0.5 + 0.5,
  SIGNED_SCALE / SIGNED_OFFSET below) and decoded back in the commandlet;
  base colour is already in [0, 1]. What the Velocity node's output IS
  (the decoded clip-space delta, x right, y up, from the previous scene
  frame) is engine source reading, verified on Windows by the verifier's
  flow_vs_motion check on the first rendered bundle -- not here. The
  commandlet refuses each pass by name (labels.pass_material) when its
  asset is absent.

* /Game/FlightSim/M_WorldNormal, M_Velocity -- S4 (the sensing engine
  side): the same post-process shape (replacing the tonemapper, one
  SceneTexture node into emissive) with NO offset encoding, table
  LINEAR_MATERIALS. M_WorldNormal is the fallback normal source of the
  linear .f32 normal pass (-normal-source=material, when the box shows the
  SCS_Normal capture in neither encoding). M_Velocity is the velocity
  cross-check (-velocity-check): its capture keeps
  bAlwaysPersistRenderingState true in the commandlet (the previous view
  matrices live in the view state), and it is a READ-BACK beside the
  Python flow, never the truth. Whether a negative emissive survives the
  FinalColorHDR readback is exactly what its record's
  negative_raw_values count measures on Windows.

* /Game/FlightSim/M_GreyCard -- S4: the calibration frame's card (the
  -calibration flag). Lit, fully rough (1.0), non-metallic, specular 0 --
  a Lambertian -- with two scalar parameters the commandlet sets per quad
  through a dynamic instance: "Reflectance" into base colour (default
  0.18, the grey card) and "Luminance" into emissive, stated in cd/m^2
  (default 0). The emissive grey quad is Reflectance 0 / Luminance L; the
  white Lambertian quad Reflectance 0.9 / Luminance 0.
"""

import unreal

PATH = "/Game/FlightSim"

#: I6: a signed scene texture (world normal, velocity) is written to the
#: pass target as value * SIGNED_SCALE + SIGNED_OFFSET, so [-1, 1] lands
#: in [0, 1]; the commandlet inverts it (FlightSimRenderCommandlet.cpp
#: RenderPassSignedScale / RenderPassSignedOffset, pinned equal by test).
SIGNED_SCALE = 0.5
SIGNED_OFFSET = 0.5

#: The three pass materials and their scene texture, by pass word.
PASS_MATERIALS = {
    "normal": ("M_WorldNormalPass", "PPI_WORLD_NORMAL", True),
    "velocity": ("M_VelocityPass", "PPI_VELOCITY", True),
    "albedo": ("M_BaseColorPass", "PPI_BASE_COLOR", False),
}

#: S4: the two unencoded post-process materials, by what they serve:
#: ("M_Name", "PPI_SCENE_TEXTURE"). Built by create_pass_material with no
#: offset (the signed flag False: the texel goes straight to emissive).
LINEAR_MATERIALS = {
    "normal_fallback": ("M_WorldNormal", "PPI_WORLD_NORMAL"),
    "velocity_check": ("M_Velocity", "PPI_VELOCITY"),
}

#: S4: the calibration card's parameters, by the names the commandlet sets
#: (FlightSimRenderCommandlet.cpp RenderGreyCardLuminanceParameter /
#: RenderGreyCardReflectanceParameter, pinned equal by test).
GREY_CARD_LUMINANCE_PARAMETER = "Luminance"
GREY_CARD_REFLECTANCE_PARAMETER = "Reflectance"
GREY_CARD_REFLECTANCE_DEFAULT = 0.18
GREY_CARD_ROUGHNESS = 1.0
GREY_CARD_METALLIC = 0.0
GREY_CARD_SPECULAR = 0.0

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


def create_pass_material(name, scene_texture_id, signed):
    """One ground-truth pass material (I6): the M_CustomStencilID shape
    -- post-process domain, blendable location "Replacing the
    Tonemapper", one SceneTexture node into emissive colour -- with, for
    a SIGNED texture, the offset encoding value * SIGNED_SCALE +
    SIGNED_OFFSET wired through a Multiply and an Add so the readback
    never depends on a negative emissive surviving the chain. Nothing
    tone-maps, exposes or dithers the value. Not run without an engine:
    the node and pin names are the UE Python API's, checked on Windows.
    """
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    material.set_editor_property("material_domain",
                                 unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property(
        "blendable_location",
        unreal.BlendableLocation.BL_REPLACING_TONEMAPPER)
    lib = unreal.MaterialEditingLibrary
    texture = lib.create_material_expression(
        material, unreal.MaterialExpressionSceneTexture, -600, 0)
    texture.set_editor_property("scene_texture_id",
                                getattr(unreal.SceneTextureId, scene_texture_id))
    if signed:
        scale = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, -600, 200)
        scale.set_editor_property("r", SIGNED_SCALE)
        offset = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, -400, 200)
        offset.set_editor_property("r", SIGNED_OFFSET)
        scaled = lib.create_material_expression(
            material, unreal.MaterialExpressionMultiply, -400, 0)
        lib.connect_material_expressions(texture, "Color", scaled, "A")
        lib.connect_material_expressions(scale, "", scaled, "B")
        encoded = lib.create_material_expression(
            material, unreal.MaterialExpressionAdd, -200, 0)
        lib.connect_material_expressions(scaled, "", encoded, "A")
        lib.connect_material_expressions(offset, "", encoded, "B")
        lib.connect_material_property(encoded, "",
                                      unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    else:
        lib.connect_material_property(texture, "Color",
                                      unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_world_normal_pass():
    create_pass_material(*PASS_MATERIALS["normal"])


def create_velocity_pass():
    create_pass_material(*PASS_MATERIALS["velocity"])


def create_base_colour_pass():
    create_pass_material(*PASS_MATERIALS["albedo"])


def create_world_normal_fallback():
    """S4: M_WorldNormal, SceneTexture:WorldNormal straight into emissive."""
    name, scene_texture_id = LINEAR_MATERIALS["normal_fallback"]
    create_pass_material(name, scene_texture_id, False)


def create_velocity_check():
    """S4: M_Velocity, SceneTexture:Velocity straight into emissive."""
    name, scene_texture_id = LINEAR_MATERIALS["velocity_check"]
    create_pass_material(name, scene_texture_id, False)


def create_grey_card():
    """S4: the calibration frame's card. Lit (the default shading model),
    roughness 1, metallic 0, specular 0 -- a Lambertian with no specular
    lobe -- with the "Reflectance" scalar into base colour and the
    "Luminance" scalar (cd/m^2) into emissive. Not run without an engine:
    the node and pin names are the UE Python API's, checked on Windows."""
    full = f"{PATH}/M_GreyCard"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_GreyCard", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    lib = unreal.MaterialEditingLibrary
    reflectance = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -400, 0)
    reflectance.set_editor_property("parameter_name", GREY_CARD_REFLECTANCE_PARAMETER)
    reflectance.set_editor_property("default_value", GREY_CARD_REFLECTANCE_DEFAULT)
    lib.connect_material_property(reflectance, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    luminance = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -400, 200)
    luminance.set_editor_property("parameter_name", GREY_CARD_LUMINANCE_PARAMETER)
    luminance.set_editor_property("default_value", 0.0)
    lib.connect_material_property(luminance, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    for value, prop, y in ((GREY_CARD_ROUGHNESS, unreal.MaterialProperty.MP_ROUGHNESS, 400),
                           (GREY_CARD_METALLIC, unreal.MaterialProperty.MP_METALLIC, 500),
                           (GREY_CARD_SPECULAR, unreal.MaterialProperty.MP_SPECULAR, 600)):
        constant = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, -400, y)
        constant.set_editor_property("r", value)
        lib.connect_material_property(constant, "", prop)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


create_vertex_colour()
create_terrain_imagery()
create_vertex_colour_unlit()
create_custom_stencil_id()
create_world_normal_pass()
create_velocity_pass()
create_base_colour_pass()
create_world_normal_fallback()
create_velocity_check()
create_grey_card()
