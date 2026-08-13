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


def import_part(obj_path, destination, part, expected_triangles):
    task = unreal.AssetImportTask()
    task.filename = obj_path
    task.destination_path = destination
    task.destination_name = part
    task.automated = True
    task.save = True
    task.replace_existing = True
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
    task.options = override
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
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
            import_part(obj_path, destination, part,
                        manifest["triangles"][part])


run()
if FAILURES:
    for failure in FAILURES:
        print(f"IMPORT-FAILED: {failure}")
    # A nonzero exit from the commandlet, so the calling script sees it.
    raise SystemExit(1)
print("IMPORT-OK")
