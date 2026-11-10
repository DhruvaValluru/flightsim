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
from ue_aircraft_materials import create_look_instances  # noqa: E402  (visual V7)
from ue_aircraft_materials import slot_report, write_import_record  # noqa: E402  (round 2)

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


def import_part(obj_path, destination, part, expected_triangles, keep_normals=False):
    # Nanite must be OFF at import time, in the pipeline options. Interchange
    # builds Nanite by default and a scene capture then draws the coarse
    # fallback (measured: 3563 of 24471 triangles); flipping the flag after
    # import and re-saving instead leaves the asset's render data broken
    # (measured: the body stopped rendering entirely). These are low-poly
    # assets; Nanite buys nothing here.
    #
    # Visual overhaul V7 (aircraft lane, 2026-11-09) re-decided this and
    # KEEPS Nanite off for every airframe, beauty included. The plan's "Nanite
    # on for VSM self-shadowing" does not hold: (1) the measured failure
    # above (the capture drew the fallback) is exactly what a beauty capture
    # would draw; (2) the mesh asset is shared by both quality paths, so a
    # Nanite airframe would change every -quality=measure frame Gate 6 passed
    # on; (3) virtual shadow maps shadow non-Nanite meshes too (beauty turns
    # r.Shadow.Virtual.Enable on), so self-shadowing does not need it; (4)
    # 3k-100k-triangle FlightGear meshes gain nothing from Nanite's cluster
    # LOD. Revisit only with a higher-detail (>1M triangle) airframe, as a
    # separate beauty-only asset, never by flipping this flag (gotcha 5).
    # The render commandlet's FAssetCompilingManager::FinishAllCompilation()
    # guard before the first capture (gotcha 4) stays as it is.
    pipeline = unreal.InterchangeGenericAssetsPipeline()
    pipeline.get_editor_property("mesh_pipeline").set_editor_property(
        "build_nanite", False)
    if keep_normals:
        # Round 2 (cockpit-airframe): the beauty body carries the converter's
        # crease-angle normals (vn). Interchange recomputes normals by default
        # (InterchangeGenericAssetsPipelineSharedSettings.h bRecomputeNormals
        # = true, UE 5.7.4), which on these unwelded triangles gives one
        # normal per face: the faceting this part exists to remove.
        _set_if_present(pipeline.get_editor_property("common_meshes_properties"),
                        "recompute_normals", False)
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
    rebuild = False
    if build.use_mikk_t_space:
        build.use_mikk_t_space = False
        rebuild = True
    if keep_normals and build.recompute_normals:
        build.recompute_normals = False
        rebuild = True
    if rebuild:
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
        # Round 2 (cockpit-airframe): the beauty-only copies (manifest
        # beauty_parts, e.g. body_beauty: the body with crease normals), after
        # the measured parts, normals kept.
        beauty = [(row["part"], row["triangles"], True)
                  for row in (manifest.get("beauty_parts") or {}).values()]
        for part, triangles, keep_normals in (
                [(p, manifest["triangles"][p], False) for p in manifest["parts"]] + beauty):
            obj_path = os.path.join(source_dir, f"{part}.obj")
            if not os.path.isfile(obj_path):
                FAILURES.append(f"missing {obj_path}")
                continue
            # One part's scripting error is that part's failure, by name;
            # the parts after it still import.
            try:
                import_part(obj_path, destination, part, triangles, keep_normals)
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
        # Visual overhaul V7 (aircraft lane): the beauty look instances
        # (<root>/Look/MI_<slot>) and assets/generated/<name>/look_manifest.json.
        # Never an import failure: the mesh and every -quality=measure render
        # are complete without them; a beauty render records what is absent.
        try:
            made, problems = create_look_instances(destination, source_dir,
                                                   manifest.get("name", ""))
            print(f"LOOK {destination}: {made} look instance(s)")
            for problem in problems:
                print(f"LOOK-PROBLEM {destination}: {problem}")
        except Exception as exc:
            print(f"LOOK-PROBLEM {destination}: look pass failed: {exc!r}")
        # Round 2 (cockpit-airframe): every slot of every imported mesh must
        # draw one of the MTL's own materials. The render machine's first
        # J-11 frames (2026-11-09, shot a render.json aircraft_look.materials)
        # had 7 slots on look instances and a slot on WorldGridMaterial where
        # the converted body has 25 MTL materials: an import that left slots
        # unbound draws grey and untextured, and nothing said so. Only for a
        # manifest with beauty_parts (the airframes this lane re-imports), so
        # no other airframe's import outcome changes.
        if manifest.get("beauty_parts"):
            try:
                parts = list(manifest["parts"]) + [row["part"] for row in manifest["beauty_parts"].values()]
                report = slot_report(destination, source_dir, parts)
                written = write_import_record(manifest_path, report)
                print(f"SLOTS {destination}: {report['bound']} bound, "
                      f"{len(report['unbound'])} unbound; record {written}")
                FAILURES.extend(f"{destination}: slot {row} is not bound to an MTL material"
                                for row in report["unbound"])
            except Exception as exc:
                FAILURES.append(f"{destination}: slot check failed: {exc!r}")


run()
if FAILURES:
    for failure in FAILURES:
        print(f"IMPORT-FAILED: {failure}")
    # A nonzero exit from the commandlet, so the calling script sees it.
    raise SystemExit(1)
print("IMPORT-OK")
