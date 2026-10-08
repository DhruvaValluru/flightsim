"""Every material the render commandlet loads by path is one the
build-time material script creates.

Measured (Phase 2, packages B + C): the ID pass loads
/Game/FlightSim/M_CustomStencilID and refuses -labels by name when it is
absent, and the package that wrote the C++ could not edit the script
that builds the assets. A path loaded in C++ with no creator in the
script is a render that refuses on every fresh machine; this pins the
two lists to each other without an engine.
"""

import ast
import json
import re
from pathlib import Path

import pytest

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
NEW_MATERIAL = re.compile(r'(?<!_sky)(?<![A-Za-z_])new_material\("(M_[A-Za-z0-9_]+)"\)')
#: The physical sky's materials (-sky=, core/sky/plan.py), made by their own
#: helper so the W5 world list stays exactly the world's.
SKY_MATERIAL = re.compile(r'_sky_material\("(M_[A-Za-z0-9_]+)"\)')
#: The weather look's materials (FlightSimWeatherLook.cpp), their own helper too.
WEATHER_MATERIAL = re.compile(r'_weather_material\("(M_[A-Za-z0-9_]+)"\)')
#: The storm weather's materials (core/scene/storm_weather.py, FlightSimWeather.cpp),
#: their own helper as well.
STORM_MATERIAL = re.compile(r'_storm_material\("(M_[A-Za-z0-9_]+)"\)')


def loaded_in_cpp():
    names = set()
    for path in BRIDGE.rglob("*.cpp"):
        names.update(LOADED.findall(path.read_text(encoding="utf-8")))
    return names


def created_by_script():
    text = SCRIPT.read_text(encoding="utf-8")
    return (set(CREATED.findall(text)) | {name for _, name, _, _ in PASS_ROW.findall(text)}
            | {name for _, name, _ in LINEAR_ROW.findall(text)}
            | set(NEW_MATERIAL.findall(text)) | set(SKY_MATERIAL.findall(text))
            | set(WEATHER_MATERIAL.findall(text)) | set(STORM_MATERIAL.findall(text)))


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
               "M_AirframePaint", "M_Runway",
               # The physical sky (FlightSimSky.cpp).
               "M_Moon", "M_StarEmissive", "M_TerrainImageryNight",
               # The weather look (FlightSimWeatherLook.cpp).
               "M_Ground_Desert", "M_Ground_Forest", "M_Ground_Grassland", "M_Ground_Snow",
               "M_Ground_Bare", "M_Ground_City", "M_Ground_Ocean", "M_LensDrops",
               "M_RainShaft", "M_Lightning", "M_IceOverlay",
               # The 3-D rain (FlightSimRainParticles.cpp).
               "M_RainDrop",
               # The storm weather (FlightSimWeather.cpp).
               "M_RainDrops", "M_RainSplash", "M_LightningChannel", "M_StormCell",
               "M_WindshieldRain"}
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
    assert "after_tonemapping()" in streaks and "PPI_POST_PROCESS_INPUT0" in streaks
    # The screen-space looks run after the tonemapper (the tan-border report),
    # and a material built before the move is moved in place, not skipped.
    for name, body in (("M_RainStreaks", streaks), ("M_LensDrops", _body(text, "create_lens_drops"))):
        create = body.index("new_material(" if name == "M_RainStreaks" else "_weather_material(")
        assert body.index(f'move_after_tonemapping("{name}")') < create
        assert '"blendable_location", after_tonemapping()' in body
    assert '"BL_SCENE_COLOR_AFTER_DOF"' not in text
    assert 'getattr(unreal.BlendableLocation, "BL_SCENE_COLOR_AFTER_TONEMAPPING", None)' in text
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
    assert '"MP_CLEAR_COAT"' in paint and '"MP_CLEAR_COAT_ROUGHNESS"' in paint
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


# -- the terrain surface: M_TerrainImagery, M_TerrainImageryNight, M_Landscape ------
# (the script's terrain section; UNCOMPILED here, pinned by reading the
# source. The sidecar side is core/xplane/drape.py, the C++ side
# FlightSimVisualScene.cpp ApplyDrapeMaterial; tests/test_ue_world_source.py
# pins both to the same two tables.)

DRAPE_INDEX = REPO / "assets" / "xplane" / "terrain" / "drape" / "drape_textures.json"
DRAPE_DIR = DRAPE_INDEX.parent
WEATHER_DIR = REPO / "assets" / "physical_renders" / "Resources" / "bitmaps" / "world" / "weather"
BUILD_SCENE = REPO / "scripts" / "ue_build_scene.py"
#: The per-role parameters terrain_role_samples creates through f"...{title}".
PER_ROLE = re.compile(r"^(DetailMetres|Detail|Normal|Roughness)(Valley|Scrub|Rock|Cliff|Snow)$")


def _table(text: str, name: str) -> dict:
    """A module-level literal dict NAME = {...}, its closing brace at column 0."""
    match = re.search(rf"^{name} = (\{{.*?\n\}})\n", text, re.M | re.S)
    assert match, name
    return ast.literal_eval(match.group(1))


def _camel(key: str) -> str:
    return "".join(part.capitalize() for part in key.split("_"))


def _linear_mean(png: Path):
    """The per-channel linear mean of an sRGB PNG, and that mean sRGB-encoded
    as a 0-255 texel."""
    import numpy as np
    from PIL import Image

    srgb = np.asarray(Image.open(png).convert("RGB"), dtype=np.float64) / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    mean = linear.reshape(-1, 3).mean(axis=0)
    encoded = np.where(mean <= 0.0031308, mean * 12.92, 1.055 * mean ** (1 / 2.4) - 0.055)
    return tuple(float(v) for v in mean), tuple(int(round(v * 255)) for v in encoded)


def test_the_terrain_tables_are_the_contract_the_drape_sidecar_writes():
    """The parameter NAMES are the contract between the material, the
    sidecar's "material" block (core/xplane/drape.py) and the C++ that sets
    them: the scalar table is the sidecar writer's, name for name, in its
    order and with its values (the slope cosines to a milli: the table
    carries them rounded); the texture table is every map, detail, normal
    and weather bitmap the block names, each with its sampler."""
    from core.xplane import drape

    text = SCRIPT.read_text(encoding="utf-8")
    scalars = _table(text, "TERRAIN_SCALAR_PARAMETERS")
    assert tuple(scalars) == drape.MATERIAL_SCALAR_NAMES
    written = drape.material_scalars(json.loads(DRAPE_INDEX.read_text(encoding="utf-8")))
    for name, default in scalars.items():
        assert default == pytest.approx(written[name], abs=1e-3), name
    # The scene's two are the scene's: a drape never resets them.
    assert set(drape.MATERIAL_SCENE_SCALARS) == {"Wetness", "NightLuminance"}
    assert not set(drape.MATERIAL_SCENE_SCALARS) & set(scalars)
    roles = _tuple(text, "TERRAIN_ROLES")
    assert roles == drape.ROLES
    textures = _table(text, "TERRAIN_TEXTURE_PARAMETERS")
    expected = {"Imagery", "SnowAlbedo", "SnowNormal", "Noise"}
    expected |= {_camel(name) for name in drape._MAP_TEXTURES.values()}    # Roles, SnowCover, WaterMask
    expected |= {f"{kind}{role.capitalize()}" for kind in ("Detail", "Normal") for role in roles}
    assert set(textures) == expected
    assert tuple(textures)[:4] == ("Imagery", "Roles", "SnowCover", "WaterMask")
    for role in roles:
        assert textures[f"Detail{role.capitalize()}"] == "srgb", role
        assert textures[f"Normal{role.capitalize()}"] == "normal", role
    for name in ("Roles", "SnowCover", "WaterMask", "Noise"):
        assert textures[name] == "linear", name
    assert textures["Imagery"] == textures["SnowAlbedo"] == "srgb"
    assert textures["SnowNormal"] == "normal"
    # Every name of both tables is created under that name (the per-role
    # ones through f"...{title}" in terrain_role_samples).
    for name in list(scalars) + list(textures):
        assert PER_ROLE.match(name) or f'"{name}"' in text, name


def test_the_detail_neutrals_are_the_committed_textures_means():
    """TERRAIN_DETAIL_NEUTRAL is each role's per-channel linear mean of
    assets/xplane/terrain/drape/<role>.png: the texel at which the
    modulation detail / neutral is 1. (The design's constant 2, neutral at
    linear 0.5, would have multiplied the drape over valleys, whose texture
    averages 0.065, by lerp(1, 0.13, 0.6) = 0.48.) The flat fallback texel
    of each T_Detail<Role> is that mean sRGB-encoded, so a missing detail
    reads exactly neutral."""
    text = SCRIPT.read_text(encoding="utf-8")
    neutral = _table(text, "TERRAIN_DETAIL_NEUTRAL")
    defaults = _table(text, "TERRAIN_DEFAULT_TEXTURES")
    roles = _tuple(text, "TERRAIN_ROLES")
    assert tuple(neutral) == roles
    for role in roles:
        mean, texel = _linear_mean(DRAPE_DIR / f"{role}.png")
        assert neutral[role] == pytest.approx(mean, abs=5e-4), role
        committed, flat, is_srgb, is_normal = defaults[f"T_Detail{role.capitalize()}"]
        assert committed == f"assets/xplane/terrain/drape/{role}.png" and is_srgb and not is_normal
        assert flat == texel + (255,), role
    assert neutral["valley"][0] < 0.1       # the measurement that moved the design's 2
    surface = _body(text, "terrain_surface")
    assert "binary(material, lib, divide, detail, neutral" in surface
    assert "lerp(material, lib, constant(material, lib, 1.0" in surface


def test_the_detail_aspects_are_the_committed_textures_shapes():
    """TERRAIN_DETAIL_ASPECT is each role's width / height of
    assets/xplane/terrain/drape/<role>.png (scrub 512 x 256, cliff
    512 x 128), the ratio drape_textures.json's projected metres_x /
    metres_y carries too; DetailMetres<Role> stays the one scalar (the
    shorter axis) and the aspect widens the tile's U in detail_uv, so a
    2:1 tile is no longer squeezed square."""
    from PIL import Image

    text = SCRIPT.read_text(encoding="utf-8")
    aspect = _table(text, "TERRAIN_DETAIL_ASPECT")
    roles = _tuple(text, "TERRAIN_ROLES")
    assert tuple(aspect) == roles
    index = json.loads(DRAPE_INDEX.read_text(encoding="utf-8"))
    scalars = _table(text, "TERRAIN_SCALAR_PARAMETERS")
    for role in roles:
        width, height = Image.open(DRAPE_DIR / f"{role}.png").size
        assert aspect[role] == width / height, role
        assert aspect[role] == pytest.approx(index[role]["metres_x"] / index[role]["metres_y"]), role
        assert scalars[f"DetailMetres{role.capitalize()}"] == min(index[role]["metres_x"],
                                                                   index[role]["metres_y"]), role
    assert aspect["scrub"] == 2.0 and aspect["cliff"] == 4.0     # the two that were squeezed
    samples = _body(text, "terrain_role_samples")
    assert "detail_uv(material, lib, world_xy, metres, TERRAIN_DETAIL_ASPECT[role]" in samples
    assert "world_metres_uv(" not in samples
    tiling = _body(text, "detail_uv")
    assert "MaterialExpressionAppendVector" in tiling and tiling.count("MaterialExpressionDivide") == 2
    assert "constant(material, lib, 100.0" in tiling and "constant(material, lib, aspect" in tiling
    assert 'mask(material, lib, world_xy, "r"' in tiling and 'mask(material, lib, world_xy, "g"' in tiling
    assert "tile squarely" not in text


def test_every_terrain_sampler_the_cpp_may_leave_unset_defaults_to_a_known_texture():
    """A texture parameter the C++ finds nothing for keeps its default, so
    the default must be KNOWN: the committed bitmap itself when the
    checkout has it, else one flat texel this script writes as a PNG and
    imports -- Roles valley everywhere, SnowCover and WaterMask 0, Noise
    0.5, every normal flat -- and of the sampler's own class, or the
    material does not compile. "Imagery" has none in the tile materials
    (the C++ always sets it) and the grey in M_Landscape."""
    text = SCRIPT.read_text(encoding="utf-8")
    textures = _table(text, "TERRAIN_TEXTURE_PARAMETERS")
    defaults = _table(text, "TERRAIN_TEXTURE_DEFAULTS")
    assets = _table(text, "TERRAIN_DEFAULT_TEXTURES")
    assert set(defaults) == set(textures) - {"Imagery"}
    for name, asset in defaults.items():
        committed, texel, is_srgb, is_normal = assets[asset]
        kind = textures[name]
        assert is_srgb == (kind == "srgb") and is_normal == (kind == "normal"), name
        assert len(texel) == 4 and all(0 <= v <= 255 for v in texel), name
        if committed is not None:
            assert (REPO / committed).is_file(), committed
    assert assets[defaults["Roles"]][1] == (255, 0, 0, 0)
    assert assets[defaults["SnowCover"]][1][0] == 0 and assets[defaults["WaterMask"]][1][0] == 0
    assert assets[defaults["Noise"]][1][0] == 128
    for role in _tuple(text, "TERRAIN_ROLES"):
        assert assets[defaults[f"Normal{role.capitalize()}"]] == (None, (128, 128, 255, 255), False, True), role
    assert assets["T_ImageryGrey"][2] is True
    # The committed bitmaps the defaults import are the sidecar's own.
    from core.xplane.drape import WEATHER_BITMAPS

    for asset, key in (("T_SnowAlbedo", "snow_albedo"), ("T_SnowNormal", "snow_normal"),
                       ("T_Noise", "noise")):
        assert assets[asset][0] == (WEATHER_DIR / WEATHER_BITMAPS[key]).relative_to(REPO).as_posix()
    # The flat PNG this script writes (standard library only, no engine)
    # decodes to the texel it was given.
    import numpy as np
    from PIL import Image

    namespace = {}
    exec(text[text.index("def _flat_png"):text.index("def _repo_file")], namespace)
    image = np.asarray(Image.open(namespace["_flat_png"]("probe", (79, 80, 54, 255))))
    assert image.shape == (4, 4, 4) and (image == (79, 80, 54, 255)).all()
    # The import: a normal map as TC_Normalmap, data uncompressed and non-sRGB,
    # a flat texel without mips; a failure is a RuntimeError the guard reports.
    helper = _body(text, "import_texture")
    for setting in ("TC_NORMALMAP", "TC_VECTOR_DISPLACEMENTMAP", "TMGS_NO_MIPMAPS",
                    '"srgb", bool(srgb)', "raise RuntimeError"):
        assert setting in helper, setting
    assert "SystemExit" not in helper
    # The zero-alpha flat texel (Roles: cliff = A = 0) is imported through a
    # TextureFactory with the engine's zero-alpha PNG fill off, or the
    # script says it could not be; untouched texels are the first Windows check.
    assert "unreal.TextureFactory()" in helper
    assert 'factory.set_editor_property("fill_png_zero_alpha", False)' in helper
    assert 'task.set_editor_property("factory", factory)' in helper and "MATERIAL-NOTE" in helper
    chooser = _body(text, "default_texture")
    assert "_repo_file(committed)" in chooser and "MATERIAL-NOTE" in chooser
    assert "zero_alpha=flat and texel[3] == 0" in chooser
    sampler = _body(text, "texture_parameter")
    assert "SAMPLERTYPE_NORMAL" in sampler and 'node.set_editor_property("texture", default)' in sampler


def test_the_terrain_graph_is_one_helper_under_both_drape_materials():
    """terrain_imagery_graph (the Roles map's weights over
    terrain_role_samples, then terrain_surface) is called by
    create_terrain_imagery and create_terrain_imagery_night alike; the
    night adds its emissive only. terrain_surface wires the normal and
    nothing else: add_wetness owns base colour and roughness (fed the
    surface's own roughness), specular stays the engine's."""
    text = SCRIPT.read_text(encoding="utf-8")
    graph = _body(text, "terrain_imagery_graph")
    assert "terrain_role_samples(material, lib, world_xy" in graph
    assert "return terrain_surface(" in graph
    for name in ("Imagery", "Roles", "SnowCover", "WaterMask"):
        assert f'terrain_texture(material, lib, "{name}"' in graph, name
    assert 'zip(TERRAIN_ROLES[:4], "rgba")' in graph                     # R, G, B, A -> the four
    # The Roles channels come off the sampler's RGBA pin: its default output
    # is RGB, a float3 the "a" mask has no A in (the one sampler connection
    # in the script that needs a named output).
    assert re.search(r'mask\(material, lib, roles, channel,[^)]*source_out="RGBA"\)', graph)
    assert "MaterialExpressionOneMinus" in graph and "MaterialExpressionSaturate" in graph  # 1 - sum
    assert "MaterialExpressionWorldPosition" in graph
    samples = _body(text, "terrain_role_samples")
    for fragment in ('f"DetailMetres{title}"', 'f"Detail{title}"', 'f"Normal{title}"',
                     'f"Roughness{title}"', "TERRAIN_DETAIL_NEUTRAL[role]", "detail_uv("):
        assert fragment in samples, fragment
    tiling = _body(text, "world_metres_uv")
    assert "constant(material, lib, 100.0" in tiling and "MaterialExpressionDivide" in tiling
    surface = _body(text, "terrain_surface")
    assert surface.count("world_metres_uv(") == 2        # the noise and the snow, square bitmaps
    for node in ("MaterialExpressionPixelDepth", "MaterialExpressionVertexNormalWS",
                 "MaterialExpressionNormalize", "MP_NORMAL"):
        assert node in surface, node
    for name in ("DetailFadeStartM", "DetailFadeEndM", "DetailStrength", "SnowSlopeLowCos",
                 "SnowSlopeHighCos", "NoiseMetres", "SnowBand", "SnowMetres", "RoughnessWater"):
        assert f'terrain_scalar(material, lib, "{name}"' in surface, name
    for name in ("Noise", "SnowAlbedo", "SnowNormal"):
        assert f'terrain_texture(material, lib, "{name}"' in surface, name
    assert 'samples["snow"]["roughness"]' in surface and 'b_out="A"' in surface   # SnowAlbedo.a
    assert "MP_ROUGHNESS" not in surface and "MP_BASE_COLOR" not in surface
    assert "MP_SPECULAR" not in surface
    for creator in ("create_terrain_imagery", "create_terrain_imagery_night"):
        body = _body(text, creator)
        assert "colour, roughness = terrain_imagery_graph(material, lib)" in body, creator
        assert 'add_wetness(material, lib, colour, "", 1200, dry_roughness=roughness)' in body, creator
    night = _body(text, "create_terrain_imagery_night")
    assert "NIGHT_LIGHTS_PARAMETER" in night and "NIGHT_LUMINANCE_PARAMETER" in night
    assert "MP_EMISSIVE_COLOR" in night and 'a_out="RGB"' in night
    assert 'NIGHT_LIGHTS_PARAMETER = "NightLights"' in text
    assert 'NIGHT_LUMINANCE_PARAMETER = "NightLuminance"' in text
    for name in ("Imagery", "NightLights", "NightLuminance"):
        assert f'TEXT("{name}")' in SCENE_CPP_TEXT, name
    wetness = _body(text, "add_wetness")
    assert "dry_roughness=None" in wetness
    assert 'lib.connect_material_expressions(dry_r, dry_output, rough, "A")' in wetness
    assert 'dry_r.set_editor_property("r", ROUGHNESS_DRY)' in wetness   # the constant when none is passed


def test_the_landscape_paints_each_layer_with_a_drape_roles_texture():
    """M_Landscape: each paint layer -> a drape role's samples under its
    tint (LANDSCAPE_LAYER_ROLES), five LandscapeLayerBlends, the
    permanent_water layer as the water mask, ImageryWeight 0.0 by default
    (no drape: the layers alone; the scene script sets 1.0 with a drape)
    scaling the modulation too,
    the drape's grey default where the scene has none; the legend tints
    stay the ID pass's reference and are painted no more."""
    text = SCRIPT.read_text(encoding="utf-8")
    layer_roles = _table(text, "LANDSCAPE_LAYER_ROLES")
    assert tuple(layer_roles) == _tuple(text, "LANDSCAPE_LAYERS")
    roles = _tuple(text, "TERRAIN_ROLES")
    tints = _table(text, "LANDSCAPE_TINT_DEFAULTS")
    for key, (role, tint) in layer_roles.items():
        assert role in roles + ("water", "imagery"), key
        assert tint is None or tint in tints, key
    assert layer_roles["permanent_water"] == ("water", None)
    assert layer_roles["nodata"] == ("imagery", None)
    assert layer_roles["snow_ice"] == ("snow", None)
    assert layer_roles["tree_cover"] == ("scrub", "TintTreeCover")
    assert layer_roles["mangroves"] == layer_roles["herbaceous_wetland"] == ("scrub", "TintWetland")
    assert {tint for _, tint in layer_roles.values() if tint} == set(tints)
    for name, rgb in tints.items():
        assert len(rgb) == 3 and all(0.0 < v <= 1.5 for v in rgb), name
    parameters = _tuple(text, "LANDSCAPE_PARAMETERS")
    assert parameters[:5] == ("Imagery", "ImageryWeight", "LandscapeTexels", "ImageryFlipV", "Wetness")
    assert set(parameters[5:]) == set(tints)
    assert "LANDSCAPE_IMAGERY_WEIGHT = 0.0\n" in text
    body = _body(text, "create_landscape")
    assert 'scalar(material, lib, "ImageryWeight", LANDSCAPE_IMAGERY_WEIGHT' in body
    assert "terrain_role_samples(material, lib, world_xy" in body
    assert "colour, roughness = terrain_surface(" in body and "detail_scale=weight" in body
    assert '("albedo", "detail", "neutral", "normal", "roughness")' in body
    assert "MaterialExpressionLandscapeLayerSample" in body
    assert 'water.set_editor_property("parameter_name", "permanent_water")' in body
    assert 'terrain_texture(material, lib, "Imagery", -1200, 2600, default="T_ImageryGrey")' in body
    assert 'terrain_texture(material, lib, "SnowCover"' in body
    assert 'add_wetness(material, lib, colour, "", 2500, dry_roughness=roughness)' in body
    assert "LANDSCAPE_TINTS[" not in body
    assert "vector(material, lib, name, LANDSCAPE_TINT_DEFAULTS[name] + (1.0,)" in body
    scene = BUILD_SCENE.read_text(encoding="utf-8")
    assert 'set_material_instance_scalar_parameter_value(material, "ImageryWeight", 1.0)' in scene
