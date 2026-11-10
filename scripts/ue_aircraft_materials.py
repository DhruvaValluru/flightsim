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


#: The characters UE replaces with "_" in an imported asset's name
#: (Engine/Source/Runtime/Core/Public/UObject/NameTypes.h, UE 5.7.4:
#: INVALID_OBJECTNAME_CHARACTERS and INVALID_LONGPACKAGE_CHARACTERS; the
#: Interchange task sanitises with both, InterchangeTaskImportObject.cpp
#: InternalGetPackageName). The J-11 package's panel.wcs.png imports as
#: TEX_panel_wcs, not TEX_panel.wcs (round 1 contact sheet, 2026-11-10).
INVALID_ASSET_NAME_CHARACTERS = "\"' ,/.:|&!~\n\r\t@#(){}[]=;^%$`\\*?<>"


def asset_object_name(name):
    """``name`` as UE names the imported asset (every invalid character
    replaced with "_")."""
    for character in INVALID_ASSET_NAME_CHARACTERS:
        name = name.replace(character, "_")
    return name


def texture_asset_name(file_name):
    """The imported texture asset's name for an MTL ``map_Kd`` file."""
    return asset_object_name(TEXTURE_PREFIX + os.path.splitext(os.path.basename(file_name))[0])


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
    # round 5 (L4): the look manifest is built FIRST, because its nozzle rows
    # (actor cm) become every paint / bare-metal instance's soot vectors
    # (local cm); it is written after the instances, as before.
    manifest, soot = None, {}
    try:
        manifest, _ = look.build_manifest_for(name, generated_dir=mtl_dir)
        soot = {key: tuple(value) for key, value in manifest["soot_nozzles_local_cm"].items()}
        for left_out in manifest.get("soot_nozzles_left_out", []):
            problems.append(f"nozzle {left_out!r}: past the fourth, no soot vector carries it")
    except (OSError, ValueError, KeyError) as exc:
        problems.append(f"look manifest: {exc}")
    lib = unreal.MaterialEditingLibrary
    assets = unreal.EditorAssetLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    folder = f"{asset_root}/{look.LOOK_INSTANCE_FOLDER}"
    made = 0

    def _instance(master_path, instance_name, texture, base_color, weight, scalars, vectors, what):
        """Create or refresh one Look/<instance>; True when made."""
        master = assets.load_asset(master_path) if assets.does_asset_exist(master_path) else None
        if master is None:
            problems.append(f"{master_path} is not built (run scripts/ue_create_materials.py)")
            return False
        path = f"{folder}/{instance_name}"
        instance = assets.load_asset(path) if assets.does_asset_exist(path) else tools.create_asset(
            instance_name, folder, unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew())
        if instance is None:
            problems.append(f"{path}: could not be created")
            return False
        lib.set_material_instance_parent(instance, master)
        if texture:
            texture_path = f"{asset_root}/{texture}"
            if not assets.does_asset_exist(texture_path):
                problems.append(f"{path}: its texture {texture_path} is not imported")
                return False
            lib.set_material_instance_texture_parameter_value(
                instance, "BaseColorMap", assets.load_asset(texture_path))
        lib.set_material_instance_vector_parameter_value(
            instance, "BaseColor", unreal.LinearColor(*base_color))
        lib.set_material_instance_scalar_parameter_value(instance, "BaseColorMapWeight", weight)
        for key, value in scalars.items():
            lib.set_material_instance_scalar_parameter_value(instance, key, float(value))
        for key, value in vectors.items():
            lib.set_material_instance_vector_parameter_value(instance, key, unreal.LinearColor(*value))
        lib.update_material_instance(instance)
        assets.save_loaded_asset(instance, only_if_is_dirty=False)
        say(f"{path}: {what}")
        return True

    for slot, row in sorted(slots.items()):
        if not assets.does_asset_exist(f"{asset_root}/{slot}"):
            continue    # never imported (a dropped glass shell): nothing draws it
        vectors = dict(row["vectors"])
        if row["class"] in ("paint", "bare_metal"):
            vectors.update(soot)
        if _instance(row["master"], row["instance"], row["texture"], row["base_color"], row["weight"],
                     row["scalars"], vectors, f"{row['class']} ({row['rule']})"):
            made += 1
        thin = row.get("thin")
        if thin and _instance(thin["master"], thin["instance"], row["texture"], row["base_color"],
                              row["weight"], thin["scalars"], thin["vectors"],
                              f"{look.THIN_CLASS} (the canopy on a render without -labels)"):
            made += 1
    if manifest is not None:
        try:
            written = look.write_manifest_dict(manifest, mtl_dir)
            say(f"look manifest {written}")
        except OSError as exc:
            problems.append(f"look manifest: {exc}")
    return made, problems


# -- the slot check and the import record (round 2, cockpit-airframe lane) ----
#
# The render machine's first J-11 frames (2026-11-09) drew the airframe grey
# and untextured: render.json aircraft_look.materials said 7 slots on look
# instances and one on WorldGridMaterial, where the converted body has 25
# MTL materials, and the import had reported nothing. After every import of a
# manifest with beauty_parts, each imported mesh's slots are read back; a
# slot without one of the MTL's own materials is an import FAILURE, and the
# result goes to import_record.json beside the manifest, which
# assets_pipeline/importer.py reads (a manifest whose record is missing or
# names another manifest is not imported yet).

#: assets_pipeline/importer.py IMPORT_RECORD_NAME / IMPORT_RECORD_MAGIC
#: (pinned by tests/test_cockpit_airframe.py: this file runs inside UE,
#: where the assets_pipeline package is not importable).
IMPORT_RECORD_NAME = "import_record.json"
IMPORT_RECORD_MAGIC = "flightsim-aircraft-import-record"


def classify_slots(slots, mtl_names):
    """``slots``: (part, slot index, slot name, material asset name or None)
    rows; ``mtl_names``: the MTL materials. Returns {"bound": n,
    "unbound": ["part[slot] name -> material", ...], "slots": {part:
    [material names]}, "slot_names": {part: [slot names]}}. A slot is bound
    when its material is one of the MTL materials (the imported instance
    Interchange made from the MTL)."""
    names = set(mtl_names)
    report = {"bound": 0, "unbound": [], "slots": {}, "slot_names": {}}
    for part, index, slot_name, material in slots:
        report["slots"].setdefault(part, []).append(material)
        report["slot_names"].setdefault(part, []).append(slot_name)
        if material is not None and material in names:
            report["bound"] += 1
        else:
            report["unbound"].append(f"{part}[{index}] {slot_name} -> {material}")
    return report


def beauty_slot_mismatches(report, beauty_parts):
    """Each measured part whose beauty copy's slot names are not its own,
    name for name and in order: FlightSimAircraftFX.cpp keeps the measured
    mesh on a beauty render for such a pair, so the import is incomplete.
    ``report``: :func:`classify_slots`; ``beauty_parts``: the manifest's
    {part: {"part": copy, ...}}."""
    names = report.get("slot_names", {})
    out = []
    for part, row in sorted((beauty_parts or {}).items()):
        mine, theirs = names.get(part), names.get(row["part"])
        if mine is not None and theirs is not None and mine != theirs:
            out.append(f"{row['part']} slots {theirs} are not {part}'s {mine}")
    return out


def _mesh_slot_rows(asset_root, parts):
    import unreal

    rows = []
    for part in parts:
        mesh = unreal.load_asset(f"{asset_root}/{part}")
        if mesh is None:
            rows.append((part, 0, "(mesh)", None))
            continue
        for index, slot in enumerate(mesh.get_editor_property("static_materials")):
            material = slot.get_editor_property("material_interface")
            rows.append((part, index, str(slot.get_editor_property("material_slot_name")),
                         material.get_name() if material is not None else None))
    return rows


def slot_report(asset_root, mtl_dir, parts):
    """:func:`classify_slots` over the imported meshes ``parts`` under
    ``asset_root`` (inside UE)."""
    return classify_slots(_mesh_slot_rows(asset_root, parts), read_mtl_dir(mtl_dir).keys())


# -- binding every slot to its MTL material (round 1 contact sheet, 2026-11-10) --
#
# The first import of the full yanes19 package on the render machine refused
# aircraft.material_slots: body[5..24] on WorldGridMaterial, body[0..4] bound.
# The five bound slots are exactly the materials of the EARLIER J-11
# conversion (mat_Su_27_Flanker_P01, mat_Glass_Cockpit, mat_su_27gears,
# rgb_000000, rgb_878787), and the twenty unbound ones follow in body.obj's
# usemtl order with those five left out: Interchange imported over the
# existing body StaticMesh, kept its five name-matched slots and appended the
# new ones on UMaterial::GetDefaultMaterial (InterchangeMeshHelper.cpp
# InternalMeshFactorySetupAssetMaterialArray, UE 5.7.4: a slot whose
# material factory node resolves to no object), while body_beauty, imported
# after it, bound all 25. So, for a manifest with beauty_parts:
#   1. remove_stale_meshes: the parts' existing StaticMesh assets are deleted
#      before the import, so every part is a first import (the path that has
#      bound every slot of every airframe so far) and the body's slots come
#      in body.obj's order, which is body_beauty's (the beauty swap in
#      FlightSimAircraftFX.cpp needs the two name for name, in order);
#   2. after the import, import_missing_textures and bind_slots put every
#      slot whose NAME is an MTL material onto the asset of that name,
#      creating the instance (Interchange's own OBJ parent) when Interchange
#      made none; fix_materials then wires its colour and texture as for
#      every other material.
# Neither step runs for an airframe without beauty_parts.

#: The parent Interchange's OBJ translator gives an MTL material without an
#: ``illum`` line (InterchangeOBJTranslator.cpp, UE 5.7.4); the converters
#: write none.
INTERCHANGE_OBJ_PARENT = "/InterchangeAssets/Materials/PBRSurfaceMaterial_MR"


def plan_slot_bindings(rows, mtl_names):
    """``rows``: (part, slot index, slot name, material asset name or None).
    Returns [(part, index, material asset name)] for every slot whose name is
    an MTL material and whose material is not the asset of that name; a slot
    named for no MTL material is left to :func:`classify_slots`."""
    names = {asset_object_name(name) for name in mtl_names}
    out = []
    for part, index, slot_name, material in rows:
        wanted = asset_object_name(str(slot_name))
        if wanted in names and material != wanted:
            out.append((part, index, wanted))
    return out


def remove_stale_meshes(asset_root, parts, say=print):
    """Delete the existing StaticMesh of each part under ``asset_root`` so the
    import that follows is a first import. Returns the problems (a mesh that
    would not delete is imported over; bind_slots still binds it)."""
    import unreal

    assets = unreal.EditorAssetLibrary
    problems = []
    for part in parts:
        path = f"{asset_root}/{part}"
        if not assets.does_asset_exist(path):
            continue
        if assets.delete_asset(path):
            say(f"{path}: existing mesh deleted before its import (a first import)")
        else:
            problems.append(f"{path}: could not delete the existing mesh; imported over it")
    return problems


def _set_param(struct, name, value):
    try:
        struct.set_editor_property(name, value)
    except Exception:
        pass


def import_missing_textures(asset_root, mtl_dir, say=print):
    """Import every MTL ``map_Kd`` file whose TEX_ asset is absent under
    ``asset_root`` (a material Interchange did not make brought no texture
    either). Returns the problems."""
    import unreal

    assets = unreal.EditorAssetLibrary
    problems = []
    for name, material in sorted(read_mtl_dir(mtl_dir).items()):
        if not material["map_kd"]:
            continue
        texture = texture_asset_name(material["map_kd"])
        if assets.does_asset_exist(f"{asset_root}/{texture}"):
            continue
        source_path = os.path.join(mtl_dir, material["map_kd"])
        if not os.path.isfile(source_path):
            problems.append(f"{name}: its texture file {source_path} is not beside the MTL")
            continue
        params = unreal.ImportAssetParameters()
        params.set_editor_property("is_automated", True)
        _set_param(params, "replace_existing", True)
        _set_param(params, "destination_name", texture)
        manager = unreal.InterchangeManager.get_interchange_manager_scripted()
        source = unreal.InterchangeManager.create_source_data(source_path)
        if not manager.import_asset(asset_root, source, params):
            problems.append(f"{name}: Interchange refused {source_path}")
            continue
        assets.save_directory(asset_root, only_if_is_dirty=True, recursive=False)
        if assets.does_asset_exist(f"{asset_root}/{texture}"):
            say(f"{asset_root}/{texture}: imported from {material['map_kd']}")
        else:
            problems.append(f"{name}: {material['map_kd']} imported, but {asset_root}/{texture} "
                            f"is not on disk")
    return problems


def _sibling_parent(asset_root, mtl_names):
    """The parent of an MTL material instance Interchange did make under
    ``asset_root``, or None: the fallback when INTERCHANGE_OBJ_PARENT (what
    the B747's imported instances measured, 2026-10-07) does not load."""
    import unreal

    assets = unreal.EditorAssetLibrary
    for name in sorted(asset_object_name(n) for n in mtl_names):
        path = f"{asset_root}/{name}"
        if not assets.does_asset_exist(path):
            continue
        material = assets.load_asset(path)
        if isinstance(material, unreal.MaterialInstanceConstant):
            parent = material.get_editor_property("parent")
            if parent is not None:
                return parent
    return None


def bind_slots(asset_root, mtl_dir, parts, say=print):
    """:func:`plan_slot_bindings` applied to the imported meshes ``parts``:
    each such slot gets the material asset of its name, created as an
    instance of Interchange's OBJ parent when absent. Returns (bound,
    created, problems)."""
    import unreal

    assets = unreal.EditorAssetLibrary
    lib = unreal.MaterialEditingLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    mtl_names = list(read_mtl_dir(mtl_dir).keys())
    rows = plan_slot_bindings(_mesh_slot_rows(asset_root, parts), mtl_names)
    bound, created, problems = 0, 0, []
    parent = None
    touched = set()
    for part, index, wanted in rows:
        path = f"{asset_root}/{wanted}"
        material = assets.load_asset(path) if assets.does_asset_exist(path) else None
        if material is None:
            if parent is None:
                parent = unreal.load_asset(INTERCHANGE_OBJ_PARENT) \
                    or _sibling_parent(asset_root, mtl_names)
            if parent is None:
                problems.append(f"{path}: absent, and {INTERCHANGE_OBJ_PARENT} did not load")
                continue
            material = tools.create_asset(wanted, asset_root, unreal.MaterialInstanceConstant,
                                          unreal.MaterialInstanceConstantFactoryNew())
            if material is None:
                problems.append(f"{path}: absent, and could not be created")
                continue
            lib.set_material_instance_parent(material, parent)
            assets.save_loaded_asset(material, only_if_is_dirty=False)
            created += 1
            say(f"{path}: created (an instance of {INTERCHANGE_OBJ_PARENT})")
        mesh = unreal.load_asset(f"{asset_root}/{part}")
        mesh.set_material(index, material)
        touched.add(part)
        bound += 1
        say(f"{asset_root}/{part}[{index}] -> {wanted}")
    for part in sorted(touched):
        assets.save_asset(f"{asset_root}/{part}", only_if_is_dirty=False)
    return bound, created, problems


def write_import_record(manifest_path, report):
    """import_record.json beside the manifest: the manifest's sha256 and the
    slot report. Returns the path written."""
    import hashlib
    import json

    with open(manifest_path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    path = os.path.join(os.path.dirname(os.path.abspath(manifest_path)), IMPORT_RECORD_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"magic": IMPORT_RECORD_MAGIC, "manifest_sha256": digest, **report},
                  handle, indent=1)
    return path
