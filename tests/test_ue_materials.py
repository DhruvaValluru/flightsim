"""Every material the render commandlet loads by path is one the
build-time material script creates.

Measured (Phase 2, packages B + C): the ID pass loads
/Game/FlightSim/M_CustomStencilID and refuses -labels by name when it is
absent, and the package that wrote the C++ could not edit the script
that builds the assets. A path loaded in C++ with no creator in the
script is a render that refuses on every fresh machine; this pins the
two lists to each other without an engine.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ue_create_materials.py"
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"

LOADED = re.compile(r"/Game/FlightSim/(M_[A-Za-z0-9_]+)")
CREATED = re.compile(r'create_asset\("(M_[A-Za-z0-9_]+)"')
#: I6: the pass materials are created from a table, one row per pass
#: word: ("M_Name", "PPI_SCENE_TEXTURE", signed).
PASS_ROW = re.compile(r'"(normal|velocity|albedo)": \("(M_[A-Za-z0-9_]+)", "(PPI_[A-Z_]+)", (True|False)\)')
#: S4: the two unencoded post-process materials, one row per use:
#: ("M_Name", "PPI_SCENE_TEXTURE").
LINEAR_ROW = re.compile(r'"(normal_fallback|velocity_check)": \("(M_[A-Za-z0-9_]+)", "(PPI_[A-Z_]+)"\)')
#: W5: the world materials are created through new_material("M_Name").
NEW_MATERIAL = re.compile(r'new_material\("(M_[A-Za-z0-9_]+)"\)')


def loaded_in_cpp():
    names = set()
    for path in BRIDGE.rglob("*.cpp"):
        names.update(LOADED.findall(path.read_text(encoding="utf-8")))
    return names


def created_by_script():
    text = SCRIPT.read_text(encoding="utf-8")
    return (set(CREATED.findall(text)) | {name for _, name, _, _ in PASS_ROW.findall(text)}
            | {name for _, name, _ in LINEAR_ROW.findall(text)}
            | set(NEW_MATERIAL.findall(text)))


def test_every_material_the_commandlet_loads_is_created_by_the_script():
    loaded = loaded_in_cpp()
    assert "M_CustomStencilID" in loaded, "the ID pass's material moved"
    missing = loaded - created_by_script()
    assert not missing, (
        f"the commandlet loads {sorted(missing)} but "
        f"scripts/ue_create_materials.py never creates them: -labels (or "
        f"the terrain) would refuse by name on every fresh machine")


def test_the_stencil_material_is_a_tonemapper_replacing_post_process():
    """The three properties that make the readback an integer: post-
    process domain, replacing the tonemapper, CustomStencil into
    emissive. Anything else re-quantises or tone-maps the id."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = text[text.index("def create_custom_stencil_id"):]
    body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
    assert "MaterialDomain.MD_POST_PROCESS" in body
    assert "BlendableLocation.BL_REPLACING_TONEMAPPER" in body
    assert "SceneTextureId.PPI_CUSTOM_STENCIL" in body
    assert "MP_EMISSIVE_COLOR" in body
    # Called at import like the other three, so one editor run builds all.
    assert re.search(r"^create_custom_stencil_id\(\)", text, re.M)


# -- the wetness coupling: the name the C++ reads is the one the script exposes --

SCENE_CPP = BRIDGE / "Private" / "FlightSimVisualScene.cpp"


def _wetness_name_the_cpp_reads() -> str:
    """ApplyWetness looks the parameter up by a literal name; read it from
    the C++ rather than retyping it here."""
    match = re.search(r'FindScalarParameter\(Material, TEXT\("(\w+)"\)',
                      SCENE_CPP.read_text(encoding="utf-8"))
    assert match, "ApplyWetness no longer looks a scalar parameter up by name"
    return match.group(1)


def _body(text: str, name: str) -> str:
    body = text[text.index(f"def {name}"):]
    return body[:body.index("\n\n\n")] if "\n\n\n" in body else body


def test_both_terrain_materials_expose_the_wetness_parameter_the_cpp_sets():
    """Measured before the fix: ApplyWetness -> FindScalarParameter(...,
    "Wetness") -> NAME_None on both terrain materials (they wired a
    constant 0.92 into roughness and exposed no parameter), so the rain
    look's wetness_parameter was "absent" on every frame. The script
    now exposes a ScalarParameter under exactly the name the C++ reads,
    in both terrain materials, and that parameter drives roughness
    (dry 0.92 -> wet 0.25) and darkens the base colour."""
    text = SCRIPT.read_text(encoding="utf-8")
    name = _wetness_name_the_cpp_reads()
    assert name == "Wetness"
    assert f'WETNESS_PARAMETER = "{name}"' in text
    helper = _body(text, "add_wetness")
    assert "MaterialExpressionScalarParameter" in helper
    assert 'set_editor_property("parameter_name", WETNESS_PARAMETER)' in helper
    assert 'set_editor_property("default_value", 0.0)' in helper
    assert "MaterialExpressionLinearInterpolate" in helper and "MP_ROUGHNESS" in helper
    assert "MaterialExpressionOneMinus" in helper and "MP_BASE_COLOR" in helper
    assert "ROUGHNESS_DRY = 0.92" in text and "ROUGHNESS_WET = 0.25" in text
    assert "WET_DARKENING = 0.3" in text
    for creator in ("create_vertex_colour", "create_terrain_imagery"):
        body = _body(text, creator)
        assert "add_wetness(material, lib, " in body, f"{creator} exposes no wetness"
        # The helper owns both outputs: nothing else in the creator wires
        # roughness or base colour, so the parameter is never shadowed.
        assert "MP_ROUGHNESS" not in body and "MP_BASE_COLOR" not in body, creator


# -- I6 (gap S3): the three ground-truth pass materials -----------------------

def test_the_pass_materials_are_the_three_the_commandlet_loads_with_their_scene_textures():
    """One table row per pass word: the UE 5.7 ESceneTextureId values
    PPI_WorldNormal / PPI_Velocity / PPI_BaseColor in the Python enum's
    spelling, the normal and the velocity flagged SIGNED (offset-encoded),
    the base colour not."""
    text = SCRIPT.read_text(encoding="utf-8")
    rows = {word: (name, ppi, signed == "True")
            for word, name, ppi, signed in PASS_ROW.findall(text)}
    assert rows == {
        "normal": ("M_WorldNormalPass", "PPI_WORLD_NORMAL", True),
        "velocity": ("M_VelocityPass", "PPI_VELOCITY", True),
        "albedo": ("M_BaseColorPass", "PPI_BASE_COLOR", False),
    }
    loaded = loaded_in_cpp()
    for name, _, _ in rows.values():
        assert name in loaded, f"the commandlet never loads {name}"


def test_a_pass_material_replaces_the_tonemapper_and_offsets_a_signed_texture():
    """The M_CustomStencilID shape (post-process domain, replacing the
    tonemapper, SceneTexture into emissive) plus, for a signed texture,
    Color * SIGNED_SCALE + SIGNED_OFFSET through a Multiply and an Add;
    an unsigned one goes straight to emissive."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SIGNED_SCALE = 0.5\n" in text and "SIGNED_OFFSET = 0.5\n" in text
    body = _body(text, "create_pass_material")
    assert "MaterialDomain.MD_POST_PROCESS" in body
    assert "BlendableLocation.BL_REPLACING_TONEMAPPER" in body
    assert "getattr(unreal.SceneTextureId, scene_texture_id)" in body
    assert 'scale.set_editor_property("r", SIGNED_SCALE)' in body
    assert 'offset.set_editor_property("r", SIGNED_OFFSET)' in body
    assert "MaterialExpressionMultiply" in body and "MaterialExpressionAdd" in body
    assert body.count("MP_EMISSIVE_COLOR") == 2      # the signed and the plain branch
    assert 'lib.connect_material_expressions(texture, "Color", scaled, "A")' in body
    assert 'lib.connect_material_property(encoded, "",' in body
    # Called at import like the others, so one editor run builds all seven.
    for creator in ("create_world_normal_pass", "create_velocity_pass",
                    "create_base_colour_pass"):
        assert re.search(rf"^{creator}\(\)", text, re.M), creator


# -- S4 (the sensing engine side): M_WorldNormal, M_Velocity, M_GreyCard -------

#: Every /Game/FlightSim asset the script creates, by name: a material added
#: or dropped without this list moving is a render that refuses (or an asset
#: nothing loads) on a fresh machine.
ALL_CREATED = {"M_VertexColor", "M_TerrainImagery", "M_VertexColorUnlit", "M_CustomStencilID",
               "M_WorldNormalPass", "M_VelocityPass", "M_BaseColorPass",
               "M_WorldNormal", "M_Velocity", "M_GreyCard",
               # W5: the world materials.
               "M_Landscape", "M_LandcoverID", "M_Starfield", "M_RainStreaks",
               "M_AirframePaint", "M_Runway"}
COMMANDLET_CPP = BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp"


def test_every_game_path_the_script_creates_is_pinned_and_each_is_loaded():
    created = created_by_script()
    assert created == ALL_CREATED
    loaded = loaded_in_cpp()
    for name in ("M_WorldNormal", "M_Velocity", "M_GreyCard"):
        assert name in loaded, f"the commandlet never loads {name}"


def test_the_s4_post_process_materials_are_unencoded_scene_textures():
    """M_WorldNormal (the fallback normal source) and M_Velocity (the
    velocity cross-check) go through create_pass_material with the signed
    flag OFF: the texel straight into emissive, no offset, so the commandlet
    reads them as signed values. M_Velocity's capture keeps its view state
    (bAlwaysPersistRenderingState, set in the commandlet)."""
    text = SCRIPT.read_text(encoding="utf-8")
    rows = {use: (name, ppi) for use, name, ppi in LINEAR_ROW.findall(text)}
    assert rows == {"normal_fallback": ("M_WorldNormal", "PPI_WORLD_NORMAL"),
                    "velocity_check": ("M_Velocity", "PPI_VELOCITY")}
    for creator, use in (("create_world_normal_fallback", "normal_fallback"),
                         ("create_velocity_check", "velocity_check")):
        body = _body(text, creator)
        assert f'LINEAR_MATERIALS["{use}"]' in body, creator
        assert "create_pass_material(name, scene_texture_id, False)" in body, creator
        assert re.search(rf"^{creator}\(\)", text, re.M), creator
    cpp = COMMANDLET_CPP.read_text(encoding="utf-8")
    assert "VelocityCheck->bAlwaysPersistRenderingState = true;" in cpp


def test_the_grey_card_is_a_lambertian_with_the_two_parameters_the_commandlet_sets():
    text = SCRIPT.read_text(encoding="utf-8")
    body = _body(text, "create_grey_card")
    assert 'create_asset("M_GreyCard", PATH, unreal.Material,' in body
    assert "MaterialExpressionScalarParameter" in body
    assert 'reflectance.set_editor_property("parameter_name", GREY_CARD_REFLECTANCE_PARAMETER)' in body
    assert 'reflectance.set_editor_property("default_value", GREY_CARD_REFLECTANCE_DEFAULT)' in body
    assert 'luminance.set_editor_property("parameter_name", GREY_CARD_LUMINANCE_PARAMETER)' in body
    assert 'luminance.set_editor_property("default_value", 0.0)' in body
    assert "lib.connect_material_property(reflectance, \"\",\n                                  unreal.MaterialProperty.MP_BASE_COLOR)" in body
    assert "lib.connect_material_property(luminance, \"\",\n                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)" in body
    for constant, prop in (("GREY_CARD_ROUGHNESS", "MP_ROUGHNESS"), ("GREY_CARD_METALLIC", "MP_METALLIC"),
                           ("GREY_CARD_SPECULAR", "MP_SPECULAR")):
        assert f"({constant}, unreal.MaterialProperty.{prop}," in body, prop
    # Lit (no shading-model override) and not a post-process material.
    assert "MSM_UNLIT" not in body and "MD_POST_PROCESS" not in body
    assert "GREY_CARD_ROUGHNESS = 1.0\n" in text and "GREY_CARD_METALLIC = 0.0\n" in text
    assert "GREY_CARD_SPECULAR = 0.0\n" in text and "GREY_CARD_REFLECTANCE_DEFAULT = 0.18\n" in text
    # The parameter names are the ones the commandlet sets, read from its source.
    cpp = COMMANDLET_CPP.read_text(encoding="utf-8")
    for constant, cpp_name in (("GREY_CARD_LUMINANCE_PARAMETER", "RenderGreyCardLuminanceParameter"),
                               ("GREY_CARD_REFLECTANCE_PARAMETER", "RenderGreyCardReflectanceParameter")):
        value = re.search(rf'^{constant} = "(\w+)"$', text, re.M).group(1)
        assert f'{cpp_name} = TEXT("{value}");' in cpp, constant
    assert re.search(r"^create_grey_card\(\)", text, re.M)


# -- W5 (the world engine side): the six world materials ------------------------

SCENE_CPP_TEXT = SCENE_CPP.read_text(encoding="utf-8")
EDITOR = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridgeEditor"


def _tuple(text: str, name: str):
    match = re.search(rf"^{name} = \((.*?)\)\n", text, re.M | re.S)
    assert match, name
    return tuple(re.findall(r'"([A-Za-z_]+)"', match.group(1)))


def test_the_world_materials_are_created_once_each_and_called_at_import():
    text = SCRIPT.read_text(encoding="utf-8")
    world = _tuple(text, "WORLD_MATERIALS")
    assert world == ("M_Landscape", "M_LandcoverID", "M_Starfield", "M_RainStreaks",
                     "M_AirframePaint", "M_Runway")
    assert set(NEW_MATERIAL.findall(text)) == set(world)
    for name in world:
        assert text.count(f'new_material("{name}")') == 1, name
        assert f'finish(material, "{name}")' in text, name
    for creator in ("create_landscape", "create_landcover_id", "create_starfield",
                    "create_rain_streaks", "create_airframe_paint", "create_runway"):
        assert re.search(rf"^{creator}\(\)$", text, re.M), creator
    # Every /Game path the world C++ names (runtime and editor) is created.
    for path in list(BRIDGE.rglob("*.cpp")) + list(EDITOR.rglob("*.cpp")):
        for name in LOADED.findall(path.read_text(encoding="utf-8")):
            assert name in created_by_script(), (path.name, name)
    loaded = loaded_in_cpp()
    assert set(world) <= loaded, set(world) - loaded


def test_the_world_parameters_the_cpp_sets_are_the_ones_the_script_exposes():
    text = SCRIPT.read_text(encoding="utf-8")
    commandlet = COMMANDLET_CPP.read_text(encoding="utf-8")
    # M_LandcoverID: every parameter the commandlet sets is exposed, and back.
    exposed = _tuple(text, "LANDCOVER_PARAMETERS")
    set_in_cpp = set(re.findall(r'LandcoverInstance->Set(?:Scalar|Texture)ParameterValue\(TEXT\("(\w+)"\)',
                                commandlet))
    assert set_in_cpp == set(exposed)
    body = _body(text, "create_landcover_id")
    for name in exposed:
        assert f'"{name}"' in body or name == "ClassMap" and 'texture_parameter(material, lib, "ClassMap", True' in body
    assert "MaterialDomain.MD_POST_PROCESS" in body and "BL_REPLACING_TONEMAPPER" in body
    assert "SceneTextureId.PPI_CUSTOM_STENCIL" in body and "MaterialExpressionRound" in body
    # M_Starfield / M_RainStreaks: the names FlightSimVisualScene.cpp sets.
    for constant, cpp in (("STARFIELD_MAP_PARAMETER", "SceneStarMapParameter"),
                          ("STARFIELD_INTENSITY_PARAMETER", "SceneStarIntensityParameter")):
        value = re.search(rf'^{constant} = "(\w+)"$', text, re.M).group(1)
        assert f'{cpp} = TEXT("{value}");' in SCENE_CPP_TEXT, constant
    rain = _tuple(text, "RAIN_PARAMETERS")
    for value, cpp in zip(rain, ("SceneRainLengthParameter", "SceneRainDirectionParameter",
                                 "SceneRainDensityParameter", "SceneRainPhaseParameter")):
        assert f'{cpp} = TEXT("{value}");' in SCENE_CPP_TEXT, cpp
    streaks = _body(text, "create_rain_streaks")
    assert "BL_BEFORE_TONEMAPPING" in streaks and "PPI_POST_PROCESS_INPUT0" in streaks
    assert "length, direction, density, phase = RAIN_PARAMETERS" in streaks
    stars = _body(text, "create_starfield")
    assert "MSM_UNLIT" in stars and "BLEND_ADDITIVE" in stars and '"two_sided", True' in stars
    assert "MaterialExpressionArctangent2" in stars and "MaterialExpressionArccosine" in stars
    # M_Landscape: the layers are the weight keys (W1's layer names), wetness kept.
    from core.terrain.landcover import LEGEND, WEIGHT_KEYS

    assert _tuple(text, "LANDSCAPE_LAYERS") == WEIGHT_KEYS
    for entry in LEGEND:
        assert f'"{entry.key}": {tuple(entry.rgb)}' in text, entry.key
    landscape = _body(text, "create_landscape")
    assert "MaterialExpressionLandscapeLayerBlend" in landscape
    assert "LB_WEIGHT_BLEND" in landscape and 'f"Layer {key}"' in landscape
    assert "add_wetness(material, lib, colour" in landscape
    for name in ("LandscapeTexels", "ImageryFlipV", "ImageryWeight"):
        assert f'"{name}"' in landscape, name
    # M_AirframePaint: the clear-coat model and its five parameters.
    paint = _body(text, "create_airframe_paint")
    assert "MSM_CLEAR_COAT" in paint and "MP_CUSTOM_DATA0" in paint and "MP_CUSTOM_DATA1" in paint
    assert _tuple(text, "AIRFRAME_PAINT_PARAMETERS") == (
        "PaintColour", "Roughness", "Metallic", "ClearCoat", "ClearCoatRoughness")
    # M_Runway: the markings raster lerps the surface to the paint, then wetness.
    runway = _body(text, "create_runway")
    assert _tuple(text, "RUNWAY_PARAMETERS") == ("Markings", "SurfaceColour", "PaintColour", "Wetness")
    assert 'lib.connect_material_expressions(markings, "R", colour, "Alpha")' in runway
    assert "add_wetness(material, lib, colour" in runway
    # The linear samplers get a non-sRGB default of their own class.
    helper = _body(text, "texture_parameter")
    assert "SAMPLERTYPE_LINEAR_COLOR" in helper and "linear_default_texture()" in helper
