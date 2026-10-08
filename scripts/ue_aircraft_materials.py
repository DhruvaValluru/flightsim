"""Wire an imported aircraft's materials to the colours and textures its MTL
files state. Library for scripts/ue_import_aircraft.py (after every import)
and scripts/ue_fix_aircraft_materials.py (an aircraft already imported).

Why: Interchange's OBJ import on UE 5.7 makes each MTL material a
PBRSurfaceMaterial_MR instance but leaves a textured one with BaseColor
(0, 0, 0, 0), BaseColorMapWeight 0 and, for most, the engine's
DefaultTexture in BaseColorMap -- measured 2026-10-07 on the B747
(scripts/ue_inspect_aircraft.py): mat_BOE, the fuselage livery, and every
wing, engine and tail material rendered pure black although TEX_BOE and
the rest had imported. Untextured materials (rgb_xxxxxx) came through with
their Kd and are rewritten to the same values.

For every ``newmtl`` in the aircraft's MTL files: a ``map_Kd`` material
gets BaseColorMap = the imported TEX_<file stem>, BaseColorMapWeight 1 and
BaseColor white; a colour-only material gets BaseColor = Kd and weight 0.
The parsing is plain Python (tested without the engine); ``unreal`` is
imported only by the functions that touch assets.
"""

import os
import re

#: Interchange names an imported texture TEX_<file stem> (measured: the
#: B747's 747-400_engine.png -> /Game/Aircraft/B747/TEX_747-400_engine).
TEXTURE_PREFIX = "TEX_"


def parse_mtl(text):
    """{material name: {"kd": (r, g, b), "map_kd": file name or None}} for
    one MTL file's text."""
    materials = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        if word == "newmtl":
            current = {"kd": (0.8, 0.8, 0.8), "map_kd": None}
            materials[rest] = current
        elif current is None:
            continue
        elif word == "Kd":
            values = [float(v) for v in rest.split()[:3]]
            if len(values) == 3:
                current["kd"] = tuple(values)
        elif word == "map_Kd" and rest:
            # Options (-s, -o, ...) come before the file name; the name is last.
            current["map_kd"] = os.path.basename(rest.split()[-1].replace("\\", "/"))
    return materials


def texture_asset_name(file_name):
    """The imported texture asset's name for an MTL ``map_Kd`` file."""
    return TEXTURE_PREFIX + os.path.splitext(os.path.basename(file_name))[0]


def read_mtl_dir(directory):
    """Every material of every *.mtl in ``directory`` (later files win a
    repeated name -- they are the same material in every part)."""
    materials = {}
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".mtl"):
            with open(os.path.join(directory, name), encoding="utf-8") as handle:
                materials.update(parse_mtl(handle.read()))
    return materials


def plan(materials):
    """What each material's parameters are set to: {name: {"texture":
    texture asset name or None, "base_color": (r, g, b, a), "weight":
    0.0 | 1.0}}."""
    out = {}
    for name, material in materials.items():
        if material["map_kd"]:
            out[name] = {"texture": texture_asset_name(material["map_kd"]),
                         "base_color": (1.0, 1.0, 1.0, 1.0), "weight": 1.0}
        else:
            r, g, b = material["kd"]
            out[name] = {"texture": None, "base_color": (r, g, b, 1.0), "weight": 0.0}
    return out


def fix_materials(asset_root, mtl_dir, say=print):
    """Apply :func:`plan` to the material instances under ``asset_root``
    (e.g. /Game/Aircraft/B747) and save them. Returns (fixed, problems)."""
    import unreal

    lib = unreal.MaterialEditingLibrary
    assets = unreal.EditorAssetLibrary
    fixed, problems = 0, []
    for name, wanted in sorted(plan(read_mtl_dir(mtl_dir)).items()):
        path = f"{asset_root}/{name}"
        if not assets.does_asset_exist(path):
            # A material whose faces were all dropped (glass shells) was
            # never imported; nothing draws with it.
            continue
        material = assets.load_asset(path)
        if not isinstance(material, unreal.MaterialInstanceConstant):
            problems.append(f"{path} is a {material.get_class().get_name()}, not a "
                            f"material instance; left as imported")
            continue
        if wanted["texture"]:
            texture_path = f"{asset_root}/{wanted['texture']}"
            texture = (assets.load_asset(texture_path)
                       if assets.does_asset_exist(texture_path) else None)
            if texture is None:
                problems.append(f"{path}: its texture {texture_path} is not imported")
                continue
            lib.set_material_instance_texture_parameter_value(
                material, "BaseColorMap", texture)
        r, g, b, a = wanted["base_color"]
        lib.set_material_instance_vector_parameter_value(
            material, "BaseColor", unreal.LinearColor(r, g, b, a))
        lib.set_material_instance_scalar_parameter_value(
            material, "BaseColorMapWeight", wanted["weight"])
        lib.update_material_instance(material)
        assets.save_loaded_asset(material, only_if_is_dirty=False)
        fixed += 1
        say(f"{path}: "
            + (f"BaseColorMap {wanted['texture']}, weight 1" if wanted["texture"]
               else f"BaseColor ({r:.3f}, {g:.3f}, {b:.3f})"))
    return fixed, problems
