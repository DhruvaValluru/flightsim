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


# -- the beauty look instances (visual overhaul V7, aircraft lane) -------------
#
# For every MTL material a separate instance of its class master
# (scripts/aircraft_look.py plan_slots) at <asset root>/Look/MI_<slot>. The
# imported instances above -- the ones the mesh assets reference and every
# -quality=measure render draws -- are NOT touched: FlightSimAircraftFX.cpp
# swaps a slot to its look instance on a -quality=beauty render only, so the
# measured path stays byte-identical.

def create_look_instances(asset_root, mtl_dir, name, say=print):
    """Create or refresh the look instances of one aircraft and write its
    look manifest beside the converted model. Returns (made, problems). A
    missing master or look config is a PROBLEM line, not an exception: the
    import (and every measure render) does not depend on the look."""
    import unreal
    import aircraft_look as look

    problems = []
    try:
        config = look.load_config(name)
    except (OSError, ValueError) as exc:
        return 0, [f"look config: {exc}"]
    # j11-package lane: the converter's material_sources.json (when present)
    # lets a look config derive per-slot roughness from the FlightGear spec/shi.
    slots = look.plan_slots(look.read_mtl_dir(mtl_dir), config,
                            look.read_material_sources(mtl_dir))
    lib = unreal.MaterialEditingLibrary
    assets = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    folder = f"{asset_root}/{look.LOOK_INSTANCE_FOLDER}"
    made = 0
    for slot, row in sorted(slots.items()):
        if not assets.does_asset_exist(f"{asset_root}/{slot}"):
            continue    # never imported (a dropped glass shell): nothing draws it
        master = assets.load_asset(row["master"]) if assets.does_asset_exist(row["master"]) else None
        if master is None:
            problems.append(f"{row['master']} is not built (run scripts/ue_create_materials.py)")
            continue
        path = f"{folder}/{row['instance']}"
        instance = assets.load_asset(path) if assets.does_asset_exist(path) else tools.create_asset(
            row["instance"], folder, unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew())
        if instance is None:
            problems.append(f"{path}: could not be created")
            continue
        lib.set_material_instance_parent(instance, master)
        if row["texture"]:
            texture_path = f"{asset_root}/{row['texture']}"
            if not assets.does_asset_exist(texture_path):
                problems.append(f"{path}: its texture {texture_path} is not imported")
                continue
            lib.set_material_instance_texture_parameter_value(
                instance, "BaseColorMap", assets.load_asset(texture_path))
        lib.set_material_instance_vector_parameter_value(
            instance, "BaseColor", unreal.LinearColor(*row["base_color"]))
        lib.set_material_instance_scalar_parameter_value(instance, "BaseColorMapWeight", row["weight"])
        for key, value in row["scalars"].items():
            lib.set_material_instance_scalar_parameter_value(instance, key, float(value))
        for key, value in row["vectors"].items():
            lib.set_material_instance_vector_parameter_value(instance, key, unreal.LinearColor(*value))
        lib.update_material_instance(instance)
        assets.save_loaded_asset(instance, only_if_is_dirty=False)
        made += 1
        say(f"{path}: {row['class']} ({row['rule']})")
    try:
        written = look.write_manifest(name, generated_dir=mtl_dir)
        say(f"look manifest {written}")
    except (OSError, ValueError) as exc:
        problems.append(f"look manifest: {exc}")
    return made, problems
