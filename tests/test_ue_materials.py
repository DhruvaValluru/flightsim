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
