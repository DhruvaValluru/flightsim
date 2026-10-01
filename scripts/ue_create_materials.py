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

* W5 (the world engine side) -- six more, each parameter under the name
  the C++ sets (pinned equal by tests/test_ue_world_source.py and
  tests/test_ue_materials.py):

  - /Game/FlightSim/M_Landscape: the scene level's Landscape material. A
    LandscapeLayerBlend over the land-cover layers (LANDSCAPE_LAYERS, the
    weight keys of core/terrain/landcover.py, weight-blended: the layers
    sum to 255 per texel), each a constant tint from the WorldCover legend
    colour (scene dressing, not a measurement), lerped toward the imagery
    drape ("Imagery" sampled across the whole Landscape by
    "LandscapeTexels", flipped by "ImageryFlipV" when the rows were written
    north-up, weighted by "ImageryWeight", 0 by default), then the
    "Wetness" coupling every terrain material has.
  - /Game/FlightSim/M_LandcoverID: the land-cover ID pass (post-process,
    replacing the tonemapper, the M_CustomStencilID shape). Each pixel's
    world position (reconstructed from depth) goes onto the bake grid by
    the registration the render measures -- col = (X - OriginX) / CellX,
    row = (Y - OriginY) / CellY, uv = (col / GridWidth, row / GridHeight),
    the cell FLOOR as the verifier's own unprojection takes it -- and the
    class-code raster "ClassMap" (8-bit, nearest, no mips, non-sRGB,
    imported by scripts/ue_build_scene.py) gives the code, emitted where
    the custom stencil is "TerrainStencil" and 0 elsewhere or off the grid.
  - /Game/FlightSim/M_Starfield: the starfield sphere (unlit, additive,
    two-sided): the direction from the sphere's centre, in the sphere's
    own frame, as right ascension / declination into the equirectangular
    "StarMap" (luminance in cd/m^2 per texel, built by the render), times
    "StarIntensity".
  - /Game/FlightSim/M_RainStreaks: the rain streaks (post-process, before
    the tonemapper, the BEAUTY capture only): screen-space columns across
    "StreakDirection", a streak of "StreakLengthPx" along it per occupied
    column, occupancy from "StreakDensity" (drops per m^3) through the
    stated STREAK_CELL_VOLUME_M3, moving with "StreakPhase" (seconds).
  - /Game/FlightSim/M_AirframePaint: a clear-coat paint (lit, the clear
    coat shading model, which Substrate converts to a slab with a coat):
    "PaintColour", "Roughness", "Metallic", "ClearCoat",
    "ClearCoatRoughness".
  - /Game/FlightSim/M_Runway: the runway plane: "Markings" (the Annex 14
    raster of core/scene/runway.py, row 0 at the threshold) lerps
    "SurfaceColour" to "PaintColour", then the "Wetness" coupling.

  /Game/FlightSim/T_LinearDefault is the one texture the script makes: the
  non-sRGB default the three linear samplers are created with (a texture
  parameter needs a default of its own sampler class to compile).
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

# -- W5: the world materials' names and parameters ----------------------------

#: Every world material, by name (one /Game/FlightSim path each).
WORLD_MATERIALS = ("M_Landscape", "M_LandcoverID", "M_Starfield", "M_RainStreaks",
                   "M_AirframePaint", "M_Runway")
#: The Landscape's paint layers: core/terrain/landcover.py WEIGHT_KEYS (the
#: legend's class keys, nodata last), pinned equal by test; the layer names
#: FlightSimBridgeEditor's ImportLandscape gives the layers.
LANDSCAPE_LAYERS = ("tree_cover", "shrubland", "grassland", "cropland", "built_up",
                    "bare_sparse", "snow_ice", "permanent_water", "herbaceous_wetland",
                    "mangroves", "moss_lichen", "nodata")
#: The legend colours (sRGB 0-255, core/terrain/landcover.py LEGEND), as the
#: layers' tints: scene dressing, not an albedo measurement.
LANDSCAPE_TINTS = {
    "tree_cover": (0, 100, 0), "shrubland": (255, 187, 34), "grassland": (255, 255, 76),
    "cropland": (240, 150, 255), "built_up": (250, 0, 0), "bare_sparse": (180, 180, 180),
    "snow_ice": (240, 240, 240), "permanent_water": (0, 100, 200),
    "herbaceous_wetland": (0, 150, 160), "mangroves": (0, 207, 117),
    "moss_lichen": (250, 230, 160), "nodata": (0, 0, 0),
}
LANDSCAPE_PARAMETERS = ("Imagery", "ImageryWeight", "LandscapeTexels", "ImageryFlipV", "Wetness")
#: M_LandcoverID's parameters, by the names FlightSimRenderCommandlet.cpp sets.
LANDCOVER_PARAMETERS = ("ClassMap", "OriginX", "OriginY", "CellX", "CellY", "GridWidth",
                        "GridHeight", "TerrainStencil")
#: M_Starfield's, by the names FlightSimVisualScene.cpp sets.
STARFIELD_MAP_PARAMETER = "StarMap"
STARFIELD_INTENSITY_PARAMETER = "StarIntensity"
#: M_RainStreaks's, by the names FlightSimVisualScene.cpp sets.
RAIN_PARAMETERS = ("StreakLengthPx", "StreakDirection", "StreakDensity", "StreakPhase")
#: The streak pattern's stated constants: one column every STREAK_SPACING_PX
#: across the fall, STREAK_WIDTH_FRACTION of it lit; a column holds a streak
#: with probability density x STREAK_CELL_VOLUME_M3 (the drops a column of the
#: view samples, a stated choice); each streak repeats every
#: STREAK_PERIOD_FACTOR lengths along the fall, moving STREAK_SPEED_PX_S; a lit
#: streak raises the scene colour by STREAK_GAIN (screen-space rain with a
#: physical length, nothing more).
STREAK_SPACING_PX = 6.0
STREAK_WIDTH_FRACTION = 0.25
STREAK_CELL_VOLUME_M3 = 0.5
STREAK_PERIOD_FACTOR = 4.0
STREAK_SPEED_PX_S = 600.0
STREAK_GAIN = 0.35
#: M_AirframePaint's.
AIRFRAME_PAINT_PARAMETERS = ("PaintColour", "Roughness", "Metallic", "ClearCoat",
                             "ClearCoatRoughness")
AIRFRAME_PAINT_DEFAULTS = {"Roughness": 0.35, "Metallic": 0.0, "ClearCoat": 1.0,
                           "ClearCoatRoughness": 0.1}
#: M_Runway's.
RUNWAY_PARAMETERS = ("Markings", "SurfaceColour", "PaintColour", "Wetness")
#: The non-sRGB default of the linear texture parameters (created below).
LINEAR_DEFAULT_TEXTURE = "T_LinearDefault"


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


# -- W5: the world materials -----------------------------------------------------

def new_material(name):
    """Create /Game/FlightSim/<name> once; None when it already exists."""
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return None
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit(f"could not create material asset {name}")
    return material


def finish(material, name):
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(f"{PATH}/{name}")
    print(f"MATERIAL-CREATED: {PATH}/{name}")


def linear_default_texture():
    """The non-sRGB default of the linear texture parameters: a texture
    parameter compiles only with a default of its own sampler class."""
    full = f"{PATH}/{LINEAR_DEFAULT_TEXTURE}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        return unreal.load_asset(full)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    texture = tools.create_asset(LINEAR_DEFAULT_TEXTURE, PATH, unreal.Texture2D,
                                 unreal.Texture2DFactoryNew())
    texture.set_editor_property("srgb", False)
    texture.set_editor_property("compression_settings",
                                unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
    unreal.EditorAssetLibrary.save_asset(full)
    return texture


def scalar(material, lib, name, default, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionScalarParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", default)
    return node


def vector(material, lib, name, default, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionVectorParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", unreal.LinearColor(*default))
    return node


def texture_parameter(material, lib, name, linear, x, y):
    """A TextureSampleParameter2D: sRGB colour, or linear colour with the
    non-sRGB default (codes, markings and luminance are data, not colour)."""
    node = lib.create_material_expression(material, unreal.MaterialExpressionTextureSampleParameter2D,
                                          x, y)
    node.set_editor_property("parameter_name", name)
    if linear:
        node.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        node.set_editor_property("texture", linear_default_texture())
    return node


def binary(material, lib, kind, a, b, x, y, a_out="", b_out=""):
    node = lib.create_material_expression(material, kind, x, y)
    lib.connect_material_expressions(a, a_out, node, "A")
    lib.connect_material_expressions(b, b_out, node, "B")
    return node


def constant(material, lib, value, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionConstant, x, y)
    node.set_editor_property("r", value)
    return node


def mask(material, lib, source, channel, x, y, source_out=""):
    node = lib.create_material_expression(material, unreal.MaterialExpressionComponentMask, x, y)
    for flag in ("r", "g", "b", "a"):
        node.set_editor_property(flag, flag == channel)
    lib.connect_material_expressions(source, source_out, node, "")
    return node


def select_if(material, lib, a, b, greater, equal, less, x, y):
    """1/0 from an If node: A > B -> greater, A == B -> equal, A < B -> less."""
    node = lib.create_material_expression(material, unreal.MaterialExpressionIf, x, y)
    lib.connect_material_expressions(a, "", node, "A")
    lib.connect_material_expressions(b, "", node, "B")
    for pin, value in (("A>B", greater), ("A==B", equal), ("A<B", less)):
        lib.connect_material_expressions(constant(material, lib, value, x - 150, y), "", node, pin)
    return node


def in_unit_interval(material, lib, value, x, y):
    """1 where 0 <= value < 1, else 0 (off the grid is no class)."""
    zero = constant(material, lib, 0.0, x - 300, y)
    one = constant(material, lib, 1.0, x - 300, y + 60)
    low = select_if(material, lib, value, zero, 1.0, 1.0, 0.0, x, y)
    high = select_if(material, lib, value, one, 0.0, 0.0, 1.0, x, y + 120)
    return binary(material, lib, unreal.MaterialExpressionMultiply, low, high, x + 200, y)


def create_landscape():
    """W5: M_Landscape -- the land-cover layers weight-blended, each a legend
    tint, lerped toward the imagery drape, then the wetness coupling."""
    material = new_material("M_Landscape")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    blend = lib.create_material_expression(material, unreal.MaterialExpressionLandscapeLayerBlend,
                                           -900, 0)
    inputs = []
    for key in LANDSCAPE_LAYERS:
        layer = unreal.LayerBlendInput()
        layer.set_editor_property("layer_name", key)
        layer.set_editor_property("blend_type", unreal.LandscapeLayerBlendType.LB_WEIGHT_BLEND)
        inputs.append(layer)
    blend.set_editor_property("layers", inputs)
    for index, key in enumerate(LANDSCAPE_LAYERS):
        tint = lib.create_material_expression(material, unreal.MaterialExpressionConstant3Vector,
                                              -1200, index * 80)
        r, g, b = (float(c) / 255.0 for c in LANDSCAPE_TINTS[key])
        tint.set_editor_property("constant", unreal.LinearColor(r ** 2.2, g ** 2.2, b ** 2.2, 1.0))
        lib.connect_material_expressions(tint, "", blend, f"Layer {key}")
    coords = lib.create_material_expression(material, unreal.MaterialExpressionLandscapeLayerCoords,
                                            -1200, 1000)
    texels = scalar(material, lib, "LandscapeTexels", 1.0, -1200, 1100)
    uv = binary(material, lib, unreal.MaterialExpressionDivide, coords, texels, -1000, 1000)
    u = mask(material, lib, uv, "r", -850, 1000)
    v = mask(material, lib, uv, "g", -850, 1100)
    flip = scalar(material, lib, "ImageryFlipV", 0.0, -850, 1200)
    one_minus_v = lib.create_material_expression(material, unreal.MaterialExpressionOneMinus, -700, 1150)
    lib.connect_material_expressions(v, "", one_minus_v, "")
    v_used = lib.create_material_expression(material, unreal.MaterialExpressionLinearInterpolate,
                                            -550, 1100)
    lib.connect_material_expressions(v, "", v_used, "A")
    lib.connect_material_expressions(one_minus_v, "", v_used, "B")
    lib.connect_material_expressions(flip, "", v_used, "Alpha")
    drape_uv = binary(material, lib, unreal.MaterialExpressionAppendVector, u, v_used, -400, 1050)
    imagery = texture_parameter(material, lib, "Imagery", False, -250, 1000)
    lib.connect_material_expressions(drape_uv, "", imagery, "UVs")
    weight = scalar(material, lib, "ImageryWeight", 0.0, -250, 1200)
    colour = lib.create_material_expression(material, unreal.MaterialExpressionLinearInterpolate,
                                            -100, 400)
    lib.connect_material_expressions(blend, "", colour, "A")
    lib.connect_material_expressions(imagery, "RGB", colour, "B")
    lib.connect_material_expressions(weight, "", colour, "Alpha")
    add_wetness(material, lib, colour, "", 50)
    finish(material, "M_Landscape")


def create_landcover_id():
    """W5: M_LandcoverID -- the land-cover ID pass (see the module comment):
    post-process, replacing the tonemapper, the class code where the
    custom stencil is the terrain's, 0 elsewhere and off the grid."""
    material = new_material("M_LandcoverID")
    if material is None:
        return
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location",
                                 unreal.BlendableLocation.BL_REPLACING_TONEMAPPER)
    lib = unreal.MaterialEditingLibrary
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -1500, 0)
    wx = mask(material, lib, world, "r", -1350, 0)
    wy = mask(material, lib, world, "g", -1350, 100)
    origin_x = scalar(material, lib, "OriginX", 0.0, -1350, 200)
    origin_y = scalar(material, lib, "OriginY", 0.0, -1350, 300)
    cell_x = scalar(material, lib, "CellX", 1.0, -1350, 400)
    cell_y = scalar(material, lib, "CellY", 1.0, -1350, 500)
    width = scalar(material, lib, "GridWidth", 1.0, -1350, 600)
    height = scalar(material, lib, "GridHeight", 1.0, -1350, 700)
    col = binary(material, lib, unreal.MaterialExpressionDivide,
                 binary(material, lib, unreal.MaterialExpressionSubtract, wx, origin_x, -1200, 0),
                 cell_x, -1050, 0)
    row = binary(material, lib, unreal.MaterialExpressionDivide,
                 binary(material, lib, unreal.MaterialExpressionSubtract, wy, origin_y, -1200, 150),
                 cell_y, -1050, 150)
    u = binary(material, lib, unreal.MaterialExpressionDivide, col, width, -900, 0)
    v = binary(material, lib, unreal.MaterialExpressionDivide, row, height, -900, 150)
    uv = binary(material, lib, unreal.MaterialExpressionAppendVector, u, v, -750, 50)
    class_map = texture_parameter(material, lib, "ClassMap", True, -600, 0)
    lib.connect_material_expressions(uv, "", class_map, "UVs")
    code = lib.create_material_expression(material, unreal.MaterialExpressionRound, -300, 0)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, class_map,
               constant(material, lib, 255.0, -600, 250), -450, 0, a_out="R"), "", code, "")
    stencil = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -600, 500)
    stencil.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_CUSTOM_STENCIL)
    stencil_r = mask(material, lib, stencil, "r", -450, 500, source_out="Color")
    terrain = scalar(material, lib, "TerrainStencil", 2.0, -450, 600)
    is_terrain = select_if(material, lib, stencil_r, terrain, 0.0, 1.0, 0.0, -300, 500)
    on_grid = binary(material, lib, unreal.MaterialExpressionMultiply,
                     in_unit_interval(material, lib, u, -600, 800),
                     in_unit_interval(material, lib, v, -600, 1100), -200, 800)
    keep = binary(material, lib, unreal.MaterialExpressionMultiply, is_terrain, on_grid, -100, 600)
    out = binary(material, lib, unreal.MaterialExpressionMultiply, code, keep, 50, 200)
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_LandcoverID")


def create_starfield():
    """W5: M_Starfield -- unlit, additive, two-sided: the direction from the
    sphere's centre in its own frame as (RA / 360, (90 - Dec) / 180) into
    StarMap, times StarIntensity."""
    material = new_material("M_Starfield")
    if material is None:
        return
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    material.set_editor_property("two_sided", True)
    lib = unreal.MaterialEditingLibrary
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -1400, 0)
    centre = lib.create_material_expression(material, unreal.MaterialExpressionObjectPositionWS,
                                            -1400, 150)
    offset = binary(material, lib, unreal.MaterialExpressionSubtract, world, centre, -1250, 0)
    direction = lib.create_material_expression(material, unreal.MaterialExpressionNormalize, -1100, 0)
    lib.connect_material_expressions(offset, "", direction, "")
    local = lib.create_material_expression(material, unreal.MaterialExpressionTransform, -950, 0)
    local.set_editor_property("transform_source_type",
                              unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
    local.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_LOCAL)
    lib.connect_material_expressions(direction, "", local, "")
    x = mask(material, lib, local, "r", -800, 0)
    y = mask(material, lib, local, "g", -800, 100)
    z = mask(material, lib, local, "b", -800, 200)
    ra = lib.create_material_expression(material, unreal.MaterialExpressionArctangent2, -650, 0)
    lib.connect_material_expressions(y, "", ra, "Y")
    lib.connect_material_expressions(x, "", ra, "X")
    u = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -350, 0)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionDivide, ra,
               constant(material, lib, 6.283185307179586, -650, 100), -500, 0), "", u, "")
    polar = lib.create_material_expression(material, unreal.MaterialExpressionArccosine, -650, 200)
    lib.connect_material_expressions(z, "", polar, "")
    v = binary(material, lib, unreal.MaterialExpressionDivide, polar,
               constant(material, lib, 3.141592653589793, -650, 300), -500, 200)
    uv = binary(material, lib, unreal.MaterialExpressionAppendVector, u, v, -250, 100)
    stars = texture_parameter(material, lib, STARFIELD_MAP_PARAMETER, True, -100, 0)
    lib.connect_material_expressions(uv, "", stars, "UVs")
    intensity = scalar(material, lib, STARFIELD_INTENSITY_PARAMETER, 1.0, -100, 300)
    out = binary(material, lib, unreal.MaterialExpressionMultiply, stars, intensity, 100, 100,
                 a_out="RGB")
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_Starfield")


def create_rain_streaks():
    """W5: M_RainStreaks -- post-process before the tonemapper, the scene
    colour raised by STREAK_GAIN where a streak lies (see the constants)."""
    material = new_material("M_RainStreaks")
    if material is None:
        return
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    # Before tonemapping. UE 5.x renamed BL_BEFORE_TONEMAPPING to
    # BL_SCENE_COLOR_AFTER_DOF (measured on 5.7: AttributeError); the old
    # name is kept as the fallback for an engine that still has it.
    material.set_editor_property(
        "blendable_location",
        getattr(unreal.BlendableLocation, "BL_SCENE_COLOR_AFTER_DOF", None)
        or getattr(unreal.BlendableLocation, "BL_BEFORE_TONEMAPPING"))
    lib = unreal.MaterialEditingLibrary
    length, direction, density, phase = RAIN_PARAMETERS
    screen = lib.create_material_expression(material, unreal.MaterialExpressionScreenPosition, -1600, 0)
    size = lib.create_material_expression(material, unreal.MaterialExpressionViewSize, -1600, 150)
    pixel = binary(material, lib, unreal.MaterialExpressionMultiply, screen, size, -1450, 0,
                   a_out="ViewportUV")
    fall = vector(material, lib, direction, (0.0, 1.0, 0.0, 0.0), -1600, 300)
    dx = mask(material, lib, fall, "r", -1450, 300)
    dy = mask(material, lib, fall, "g", -1450, 400)
    px = mask(material, lib, pixel, "r", -1300, 0)
    py = mask(material, lib, pixel, "g", -1300, 100)
    along = binary(material, lib, unreal.MaterialExpressionAdd,
                   binary(material, lib, unreal.MaterialExpressionMultiply, px, dx, -1150, 0),
                   binary(material, lib, unreal.MaterialExpressionMultiply, py, dy, -1150, 100),
                   -1000, 0)
    across = binary(material, lib, unreal.MaterialExpressionSubtract,
                    binary(material, lib, unreal.MaterialExpressionMultiply, py, dx, -1150, 250),
                    binary(material, lib, unreal.MaterialExpressionMultiply, px, dy, -1150, 350),
                    -1000, 250)
    spacing = constant(material, lib, STREAK_SPACING_PX, -1000, 400)
    lanes = binary(material, lib, unreal.MaterialExpressionDivide, across, spacing, -850, 250)
    lane = lib.create_material_expression(material, unreal.MaterialExpressionFloor, -700, 250)
    lib.connect_material_expressions(lanes, "", lane, "")
    within = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -700, 350)
    lib.connect_material_expressions(lanes, "", within, "")
    lit_width = select_if(material, lib, within, constant(material, lib, STREAK_WIDTH_FRACTION, -700, 450),
                          0.0, 0.0, 1.0, -550, 350)
    # A per-lane hash: frac(sin(lane) * 43758.5453), twice.
    sine = lib.create_material_expression(material, unreal.MaterialExpressionSine, -550, 250)
    lib.connect_material_expressions(lane, "", sine, "")
    hash_one = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -250, 250)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, sine,
               constant(material, lib, 43758.5453, -550, 150), -400, 250), "", hash_one, "")
    hash_two = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -100, 150)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, hash_one,
               constant(material, lib, 7.13, -250, 150), -175, 150), "", hash_two, "")
    drops = scalar(material, lib, density, 0.0, -400, 500)
    occupancy = lib.create_material_expression(material, unreal.MaterialExpressionSaturate, -250, 500)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, drops,
               constant(material, lib, STREAK_CELL_VOLUME_M3, -400, 600), -325, 500), "", occupancy, "")
    occupied = select_if(material, lib, hash_two, occupancy, 0.0, 0.0, 1.0, -50, 400)
    streak = scalar(material, lib, length, 0.0, -1000, 600)
    period = binary(material, lib, unreal.MaterialExpressionMultiply, streak,
                    constant(material, lib, STREAK_PERIOD_FACTOR, -1000, 700), -850, 600)
    seconds = scalar(material, lib, phase, 0.0, -1000, 800)
    travel = binary(material, lib, unreal.MaterialExpressionMultiply, seconds,
                    constant(material, lib, STREAK_SPEED_PX_S, -1000, 900), -850, 800)
    position = binary(material, lib, unreal.MaterialExpressionAdd,
                      binary(material, lib, unreal.MaterialExpressionSubtract, along, travel, -700, 700),
                      binary(material, lib, unreal.MaterialExpressionMultiply, hash_one, period, -700, 800),
                      -550, 700)
    cycle = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -250, 700)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionDivide, position, period, -400, 700), "", cycle, "")
    on_streak = select_if(material, lib, cycle,
                          constant(material, lib, 1.0 / STREAK_PERIOD_FACTOR, -250, 800),
                          0.0, 0.0, 1.0, -100, 700)
    lit = binary(material, lib, unreal.MaterialExpressionMultiply,
                 binary(material, lib, unreal.MaterialExpressionMultiply, lit_width, occupied, 50, 400),
                 on_streak, 200, 500)
    gain = binary(material, lib, unreal.MaterialExpressionAdd,
                  constant(material, lib, 1.0, 200, 650),
                  binary(material, lib, unreal.MaterialExpressionMultiply, lit,
                         constant(material, lib, STREAK_GAIN, 200, 750), 350, 600), 500, 600)
    scene = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, 350, 0)
    scene.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    out = binary(material, lib, unreal.MaterialExpressionMultiply, scene, gain, 650, 200, a_out="Color")
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_RainStreaks")


def create_airframe_paint():
    """W5: M_AirframePaint -- a clear-coat paint, lit (Substrate converts
    the clear-coat model to a slab with a coat when r.Substrate is on)."""
    material = new_material("M_AirframePaint")
    if material is None:
        return
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
    lib = unreal.MaterialEditingLibrary
    paint, roughness, metallic, coat, coat_roughness = AIRFRAME_PAINT_PARAMETERS
    colour = vector(material, lib, paint, (0.8, 0.8, 0.8, 1.0), -400, 0)
    lib.connect_material_property(colour, "", unreal.MaterialProperty.MP_BASE_COLOR)
    # The clear-coat inputs: MP_CUSTOM_DATA0/1 on older engines; UE 5.7's
    # Python no longer exposes those names (measured on the owner's
    # machine), so the clear-coat names are tried too. A pin no name
    # reaches keeps its parameter node unconnected and the engine's default
    # coat (said so below), rather than failing the whole material.
    def material_property(*names):
        for candidate in names:
            value = getattr(unreal.MaterialProperty, candidate, None)
            if value is not None:
                return value
        return None

    pins = ((roughness, unreal.MaterialProperty.MP_ROUGHNESS),
            (metallic, unreal.MaterialProperty.MP_METALLIC),
            (coat, material_property("MP_CUSTOM_DATA0", "MP_CLEAR_COAT")),
            (coat_roughness, material_property("MP_CUSTOM_DATA1", "MP_CLEAR_COAT_ROUGHNESS")))
    for index, (name, prop) in enumerate(pins):
        node = scalar(material, lib, name, AIRFRAME_PAINT_DEFAULTS[name], -400, 150 + 100 * index)
        if prop is None:
            print(f"MATERIAL-NOTE: M_AirframePaint {name} has no material pin this engine's "
                  f"Python exposes; left unconnected (the engine's default coat)")
            continue
        lib.connect_material_property(node, "", prop)
    finish(material, "M_AirframePaint")


def create_runway():
    """W5: M_Runway -- the markings raster lerps the surface colour to the
    paint colour, then the wetness coupling."""
    material = new_material("M_Runway")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    markings_name, surface_name, paint_name, _ = RUNWAY_PARAMETERS
    markings = texture_parameter(material, lib, markings_name, True, -700, 0)
    surface = vector(material, lib, surface_name, (0.05, 0.05, 0.05, 1.0), -700, 250)
    paint = vector(material, lib, paint_name, (0.75, 0.75, 0.75, 1.0), -700, 400)
    colour = lib.create_material_expression(material, unreal.MaterialExpressionLinearInterpolate,
                                            -450, 200)
    lib.connect_material_expressions(surface, "", colour, "A")
    lib.connect_material_expressions(paint, "", colour, "B")
    lib.connect_material_expressions(markings, "R", colour, "Alpha")
    add_wetness(material, lib, colour, "", -300)
    finish(material, "M_Runway")


# -- physical sky (-sky=, FLIGHTSIM_SKY=physical; core/sky/plan.py) --------

def _sky_material(name):
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
    material, full = _sky_material("M_Moon")
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
    material, full = _sky_material("M_StarEmissive")
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
    material, full = _sky_material("M_TerrainImageryNight")
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


# One material that fails (an engine API rename, measured on 5.7) must not
# stop the ones after it: every creator runs, each failure is printed with
# its traceback, and the script exits non-zero at the end if any failed.
_FAILED = []


def _guard(creator):
    def run():
        try:
            creator()
        except Exception:   # reported below, never swallowed
            import traceback
            traceback.print_exc()
            print(f"MATERIAL-FAILED: {creator.__name__}")
            _FAILED.append(creator.__name__)
    return run


import inspect  # noqa: E402

# Only the top-level creators (no parameters); helpers such as
# create_pass_material(name, ...) are called by them and stay unwrapped.
for _name in [n for n in list(globals()) if n.startswith("create_")
              and callable(globals()[n])
              and not inspect.signature(globals()[n]).parameters]:
    globals()[_name] = _guard(globals()[_name])


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
create_landscape()
create_landcover_id()
create_starfield()
create_rain_streaks()
create_airframe_paint()
create_runway()
create_moon()
create_star_emissive()
create_terrain_imagery_night()
if _FAILED:
    raise SystemExit(f"materials not created: {', '.join(_FAILED)}")
