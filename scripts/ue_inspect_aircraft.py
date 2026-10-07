"""Report what an imported aircraft will look like, without rendering. Runs
inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript \
        -script="scripts/ue_inspect_aircraft.py B747 [A320 ...]"

For every StaticMesh under /Game/Aircraft/<name> it prints, per section,
the material the section draws with (its class, its parent, its texture
and colour parameters) and which way the section's normals face: the
area-weighted share of triangles whose normal points AWAY from the mesh's
centre. A closed airframe imported right side out scores well above 0.5;
one imported inside out (normals inward, so the outer skin is culled and
the inner skin is lit from inside a closed hull) scores well below it and
renders as a black silhouette. Every texture's size is printed too, so a
texture that did not import (or imported black) shows by name.

Read-only for the project: nothing is saved. Every line starts with
INSPECT and goes to the log as a warning (a commandlet's console shows
nothing quieter, so a plain print never reaches it) and to
runs/inspect_aircraft.txt beside the repository.
"""

import os
import sys

import unreal

# The script's own path: __file__ where the engine sets it, else argv[0]
# (the -script= value's first word).
_SCRIPT = globals().get("__file__") or sys.argv[0]
REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(_SCRIPT))),
                      "runs", "inspect_aircraft.txt")
os.makedirs(os.path.dirname(REPORT), exist_ok=True)
open(REPORT, "w", encoding="utf-8").close()


def say(text):
    line = f"INSPECT {text}"
    unreal.log_warning(line)
    with open(REPORT, "a", encoding="utf-8") as out:
        out.write(line + "\n")


def _names(fn, material):
    try:
        return [str(n) for n in fn(material)]
    except Exception:
        return []


def describe_material(material):
    if material is None:
        return "NONE (the engine draws its default material)"
    parts = [f"{material.get_path_name()} ({material.get_class().get_name()})"]
    if isinstance(material, unreal.MaterialInstance):
        parent = material.get_editor_property("parent")
        parts.append(f"parent={parent.get_path_name() if parent else None}")
        lib = unreal.MaterialEditingLibrary
        for name in _names(lib.get_texture_parameter_names, material):
            texture = lib.get_material_instance_texture_parameter_value(material, name)
            parts.append(f"tex[{name}]={texture.get_path_name() if texture else None}")
        for name in _names(lib.get_vector_parameter_names, material):
            colour = lib.get_material_instance_vector_parameter_value(material, name)
            parts.append(f"vec[{name}]=({colour.r:.3f},{colour.g:.3f},{colour.b:.3f},"
                         f"{colour.a:.3f})")
        for name in _names(lib.get_scalar_parameter_names, material):
            value = lib.get_material_instance_scalar_parameter_value(material, name)
            parts.append(f"scalar[{name}]={value:.3f}")
    try:
        base = material.get_base_material()
        parts.append(f"blend={base.get_editor_property('blend_mode')}")
        parts.append(f"shading={base.get_editor_property('shading_model')}")
        parts.append(f"two_sided={base.get_editor_property('two_sided')}")
    except Exception:
        pass
    return "  ".join(parts)


def outward_share(sections):
    """Area-weighted share of triangles whose vertex normals point away
    from the centre of all the mesh's vertices."""
    points = [v for vertices, _, _ in sections for v in vertices]
    if not points:
        return None, []
    cx = sum(p.x for p in points) / len(points)
    cy = sum(p.y for p in points) / len(points)
    cz = sum(p.z for p in points) / len(points)
    shares = []
    for vertices, triangles, normals in sections:
        outward = total = 0.0
        for i in range(0, len(triangles) - 2, 3):
            a, b, c = (vertices[triangles[i + k]] for k in range(3))
            ux, uy, uz = b.x - a.x, b.y - a.y, b.z - a.z
            vx, vy, vz = c.x - a.x, c.y - a.y, c.z - a.z
            area = 0.5 * ((uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2
                          + (ux * vy - uy * vx) ** 2) ** 0.5
            if area <= 0.0 or not normals:
                continue
            n = [normals[triangles[i + k]] for k in range(3)]
            nx = sum(m.x for m in n)
            ny = sum(m.y for m in n)
            nz = sum(m.z for m in n)
            mx = (a.x + b.x + c.x) / 3.0 - cx
            my = (a.y + b.y + c.y) / 3.0 - cy
            mz = (a.z + b.z + c.z) / 3.0 - cz
            total += area
            if nx * mx + ny * my + nz * mz > 0.0:
                outward += area
        shares.append(outward / total if total > 0.0 else None)
    return (cx, cy, cz), shares


def inspect(name):
    root = f"/Game/Aircraft/{name}"
    assets = unreal.EditorAssetLibrary.list_assets(root, recursive=True)
    if not assets:
        say(f"{name}: nothing under {root} -- the aircraft is not imported")
        return
    for path in assets:
        asset = unreal.EditorAssetLibrary.load_asset(path.split(".")[0])
        if isinstance(asset, unreal.Texture2D):
            say(f"{name}: texture {asset.get_path_name()} "
                f"{asset.blueprint_get_size_x()}x{asset.blueprint_get_size_y()} "
                f"srgb={asset.get_editor_property('srgb')}")
    for path in assets:
        mesh = unreal.EditorAssetLibrary.load_asset(path.split(".")[0])
        if not isinstance(mesh, unreal.StaticMesh):
            continue
        sections = []
        for s in range(mesh.get_num_sections(0)):
            vertices, triangles, normals, _, _ = \
                unreal.ProceduralMeshLibrary.get_section_from_static_mesh(mesh, 0, s)
            sections.append((vertices, triangles, normals))
        _, shares = outward_share(sections)
        say(f"{name}: mesh {mesh.get_path_name()} sections={len(sections)}")
        for s, (vertices, triangles, _) in enumerate(sections):
            material = mesh.get_material(s)
            share = shares[s] if s < len(shares) else None
            say(f"{name}:   section {s}: {len(triangles) // 3} triangles, "
                f"normals outward {'n/a' if share is None else f'{share:.2f}'}, "
                f"material {describe_material(material)}")


for aircraft in sys.argv[1:] or ["B747"]:
    try:
        inspect(aircraft)
    except Exception as exc:
        say(f"{aircraft}: inspection failed: {exc!r}")
