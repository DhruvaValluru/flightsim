"""Import converted aircraft OBJ parts as StaticMesh assets. Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript \
        -script="scripts/ue_import_aircraft.py <mesh_manifest.json> [...]"

Build-time, fully command-line (§ Phase 6B.1). Each part OBJ becomes
/Game/Aircraft/<name>/<part>; the render commandlet loads them by that
convention and refuses to run if any part is missing, so a failed import
cannot silently fall back to the placeholder boxes.

The script re-verifies each imported mesh by loading it back and printing its
bounds; an import that produced an empty mesh fails the run here, not at
render time.
"""

import json
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(
    globals().get("__file__") or sys.argv[0])))
from ue_aircraft_materials import fix_materials  # noqa: E402

FAILURES = []


def section_triangles(mesh):
    """Sum of real per-section triangle counts.

    ``StaticMesh.get_num_triangles(0)`` reports the Nanite fallback mesh when
    Nanite was built (measured: 3563 of 24471 on the 747 body), so a complete
    import can look 85% empty. The per-section extraction reads the actual
    LOD0 geometry.
    """
    total = 0
    for section in range(mesh.get_num_sections(0)):
        result = unreal.ProceduralMeshLibrary.get_section_from_static_mesh(
            mesh, 0, section)
        total += len(result[1]) // 3
    return total


def _set_if_present(struct, name, value):
    """Set a property the running engine version may not expose."""
    try:
        struct.set_editor_property(name, value)
    except Exception:
        pass


def import_part(obj_path, destination, part, expected_triangles):
    # Nanite must be OFF at import time, in the pipeline options. Interchange
    # builds Nanite by default and a scene capture then draws the coarse
    # fallback (measured: 3563 of 24471 triangles); flipping the flag after
    # import and re-saving instead leaves the asset's render data broken
    # (measured: the body stopped rendering entirely). These are low-poly
    # assets; Nanite buys nothing here.
    pipeline = unreal.InterchangeGenericAssetsPipeline()
    pipeline.get_editor_property("mesh_pipeline").set_editor_property(
        "build_nanite", False)
    override = unreal.InterchangePipelineStackOverride()
    override.add_pipeline(pipeline)
    # Straight to the Interchange manager, NOT AssetTools.import_asset_tasks:
    # on UE 5.7 AssetTools' import-completion callback syncs the content
    # browser, which asserts in a commandlet (no Slate application) right
    # after the first part is saved -- measured 2026-10-05, every aircraft,
    # even with an import that logged no error. The manager imports
    # synchronously and calls nothing in the content browser.
    params = unreal.ImportAssetParameters()
    params.set_editor_property("is_automated", True)
    params.set_editor_property(
        "override_pipelines", override.get_editor_property("override_pipelines"))
    _set_if_present(params, "replace_existing", True)
    _set_if_present(params, "destination_name", part)
    source = unreal.InterchangeManager.create_source_data(obj_path)
    manager = unreal.InterchangeManager.get_interchange_manager_scripted()
    if not manager.import_asset(destination, source, params):
        FAILURES.append(f"{destination}/{part}: Interchange refused {obj_path}")
        return
    unreal.EditorAssetLibrary.save_directory(
        destination, only_if_is_dirty=False, recursive=True)
    asset_path = f"{destination}/{part}"
    mesh = unreal.load_asset(asset_path)
    if mesh is None or not isinstance(mesh, unreal.StaticMesh):
        FAILURES.append(f"{asset_path}: import produced no StaticMesh")
        return
    if mesh.get_editor_property("nanite_settings").enabled:
        FAILURES.append(f"{asset_path}: Nanite still enabled after import; the "
                        f"capture would draw the coarse fallback mesh")
        return
    # MikkTSpace tangent generation fails on this geometry ("degenerate
    # tangent bases ... may result in mesh corruption", and the corruption is
    # real: the built body rendered nothing). The legacy tangent path builds
    # it correctly, and nothing here depends on MikkTSpace-exact tangents.
    build = unreal.EditorStaticMeshLibrary.get_lod_build_settings(mesh, 0)
    if build.use_mikk_t_space:
        build.use_mikk_t_space = False
        unreal.EditorStaticMeshLibrary.set_lod_build_settings(mesh, 0, build)
        unreal.EditorAssetLibrary.save_asset(asset_path)
    bounds = mesh.get_bounding_box()
    size = bounds.max - bounds.min
    triangles = section_triangles(mesh)
    print(f"IMPORTED {asset_path}  extent cm x={size.x:.0f} y={size.y:.0f} "
          f"z={size.z:.0f}  triangles={triangles}/{expected_triangles}")
    # A few degenerate triangles are legitimately dropped at build time; a
    # section that lost real geometry is not.
    if triangles < expected_triangles * 0.95:
        FAILURES.append(
            f"{asset_path}: {triangles} triangles imported of "
            f"{expected_triangles} converted")


def run():
    if len(sys.argv) < 2:
        FAILURES.append("usage: ue_import_aircraft.py <mesh_manifest.json> [...]")
        return
    for manifest_path in sys.argv[1:]:
        manifest = json.load(open(manifest_path, encoding="utf-8"))
        if manifest.get("magic") != "flightsim-aircraft-mesh":
            FAILURES.append(f"{manifest_path} is not a mesh manifest")
            continue
        source_dir = os.path.dirname(os.path.abspath(manifest_path))
        destination = manifest["asset_path_root"]
        for part in manifest["parts"]:
            obj_path = os.path.join(source_dir, f"{part}.obj")
            if not os.path.isfile(obj_path):
                FAILURES.append(f"missing {obj_path}")
                continue
            # One part's scripting error is that part's failure, by name;
            # the parts after it still import.
            try:
                import_part(obj_path, destination, part,
                            manifest["triangles"][part])
            except Exception as exc:
                FAILURES.append(f"{destination}/{part}: {exc!r}")
        # Interchange leaves every textured material black with its texture
        # unplugged (scripts/ue_aircraft_materials.py): wire each to the
        # colour and texture its MTL states, once all parts are in.
        try:
            fixed, problems = fix_materials(destination, source_dir)
            print(f"MATERIALS {destination}: {fixed} material(s) set")
            FAILURES.extend(f"{destination}: {p}" for p in problems)
        except Exception as exc:
            FAILURES.append(f"{destination}: material wiring failed: {exc!r}")


run()
if FAILURES:
    for failure in FAILURES:
        print(f"IMPORT-FAILED: {failure}")
    # A nonzero exit from the commandlet, so the calling script sees it.
    raise SystemExit(1)
print("IMPORT-OK")
