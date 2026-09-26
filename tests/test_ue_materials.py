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


def loaded_in_cpp():
    names = set()
    for path in BRIDGE.rglob("*.cpp"):
        names.update(LOADED.findall(path.read_text(encoding="utf-8")))
    return names


def created_by_script():
    return set(CREATED.findall(SCRIPT.read_text(encoding="utf-8")))


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
