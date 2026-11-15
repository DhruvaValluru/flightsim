r"""Bake JangaFX's CC0 cloud VDBs into octahedral six-way impostor atlases (ONE-OFF, Blender).

Run on the render machine (never on the Mac; this is an offline Cycles render,
not Unreal), once, after scripts/fetch_cloud_vdbs.py. Blender is portable there
(5.2.3 LTS, not on PATH), so name it in full or through BLENDER:

    $env:BLENDER = "C:\Users\kanth\flightsim_assets\blender-5.2.3-windows-x64\blender.exe"
    & $env:BLENDER -b -P scripts\bake_cloud_impostors.py -- `
        --vdb-dir C:\Users\kanth\flightsim_assets\jangafx_clouds\CloudPack\CloudPackVDB `
        --out assets\looks\clouds\impostors --clouds 4 --views 8 --px 128

Written for Blender 4.x and 5.x: the VDB is loaded as a Volume datablock directly
(no operator), the Principled Volume's inputs are found by name with fallbacks, and
the depth shell (Volume to Mesh) is optional (depth offset 0.5 when it cannot be made,
said in the JSON).

Per cloud: the VDB imported and centred, a cloud volume shader (Principled Volume,
albedo ~0.99, forward-scattering anisotropy, many volume bounces for the multiple
scattering that gives clouds their glow), then for each of VIEWS x VIEWS
octahedral views an orthographic camera fitted to the bounding sphere and TWO
renders: the suns from +x, +y, +z coloured red, green, blue (pass "pos"), then
from -x, -y, -z (pass "neg"). Volume scattering is linear in the light and the
cloud is grey, so each colour channel is exactly that axis's render. The front
surface's depth offset is ray-cast against a Volume-to-Mesh shell of the density.
Atlases (<= 1024 px), one JSON per cloud, impostors.json and PIN.json land in
--out. The conventions are scripts/cloud_impostor_math.py's (the shader and the
C++ share them). Every amount is UNCALIBRATED until a render is judged.
"""

from __future__ import annotations

import argparse
import os
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cloud_impostor_math as cim  # noqa: E402

#: The cloud shader and Cycles settings (stated; UNCALIBRATED).
ALBEDO = 0.99
ANISOTROPY = 0.7
DENSITY_SCALE = 1.0
SAMPLES = 128
VOLUME_BOUNCES = 24
SUN_ANGLE_DEG = 0.53
SHELL_THRESHOLD = 0.05
CAMERA_DISTANCE_RADII = 3.0


def parse(argv):
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="bake_cloud_impostors.py")
    p.add_argument("--vdb-dir", type=Path, default=None,
                   help="the unpacked Cloud Pack (default: scripts/fetch_cloud_vdbs.py's cache, fetched if absent)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--clouds", type=int, default=cim.PILOT_CLOUDS)
    p.add_argument("--views", type=int, default=cim.DEFAULT_VIEWS)
    p.add_argument("--px", type=int, default=cim.DEFAULT_PX)
    p.add_argument("--samples", type=int, default=SAMPLES)
    return p.parse_args(argv)


def main(argv):
    import bpy                     # noqa: F401  (Blender only)
    import numpy as np
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree

    args = parse(argv)
    cim.atlas_px(args.views, args.px)
    vdb_dir = args.vdb_dir
    if vdb_dir is None:
        import fetch_cloud_vdbs
        vdb_dir = fetch_cloud_vdbs.fetch()
    vdbs = sorted(Path(vdb_dir).rglob("*.vdb"))[: args.clouds]
    if not vdbs:
        raise SystemExit(f"no .vdb under {vdb_dir}")
    # Absolute: Blender resolves a relative render.filepath against the drive root, not the cwd
    # (the render machine's first bake wrote its atlases to C:\assets\...).
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    index = []
    atlas_names = []

    for n, vdb in enumerate(vdbs):
        cloud_id = f"cloud{n:02d}"
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = args.samples
        scene.cycles.volume_bounces = VOLUME_BOUNCES
        scene.cycles.max_bounces = VOLUME_BOUNCES + 8
        scene.cycles.transparent_max_bounces = 32
        scene.render.film_transparent = True
        scene.render.resolution_x = args.px
        scene.render.resolution_y = args.px
        scene.render.resolution_percentage = 100
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.color_depth = "32"
        scene.render.image_settings.color_mode = "RGBA"
        world = bpy.data.worlds.new("black")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
        scene.world = world

        # The VDB as a Volume datablock (works on 4.x and 5.x; no import operator).
        vol_data = bpy.data.volumes.new(cloud_id)
        vol_data.filepath = str(vdb)
        vol = bpy.data.objects.new(cloud_id, vol_data)
        scene.collection.objects.link(vol)
        vol_data.grids.load()
        grid_names = [g.name for g in vol_data.grids]
        if "density" not in grid_names:
            raise SystemExit(f"{vdb.name}: no 'density' grid (grids: {grid_names})")
        bpy.context.view_layer.update()
        evaluated = vol.evaluated_get(bpy.context.evaluated_depsgraph_get())
        corners = [vol.matrix_world @ Vector(c) for c in evaluated.bound_box]
        lo = [min(c[i] for c in corners) for i in range(3)]
        hi = [max(c[i] for c in corners) for i in range(3)]
        centre = Vector([(lo[i] + hi[i]) / 2 for i in range(3)])
        vol.location -= centre
        bpy.context.view_layer.update()
        radius = 0.5 * math.sqrt(sum((hi[i] - lo[i]) ** 2 for i in range(3)))

        mat = bpy.data.materials.new(f"{cloud_id}_cloud")
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        pv = nodes.new("ShaderNodeVolumePrincipled")

        def set_input(names, value):
            for name in names:
                if name in pv.inputs:
                    pv.inputs[name].default_value = value
                    return name
            raise SystemExit(f"Principled Volume has none of {names} (inputs: {[i.name for i in pv.inputs]})")

        a = 1.0 - ALBEDO
        set_input(("Color",), (1.0, 1.0, 1.0, 1.0))
        set_input(("Density",), DENSITY_SCALE)
        set_input(("Anisotropy",), ANISOTROPY)
        set_input(("Absorption Color", "Absorption"), (a, a, a, 1.0))
        if "Density Attribute" in pv.inputs:
            pv.inputs["Density Attribute"].default_value = "density"
        outn = nodes.new("ShaderNodeOutputMaterial")
        links.new(pv.outputs[0], outn.inputs["Volume"])
        vol.data.materials.clear()
        vol.data.materials.append(mat)

        # The front-surface shell for the depth offset (not rendered).
        bvh = None
        shell_note = "Volume to Mesh shell at the threshold below"
        try:
            mesh = bpy.data.meshes.new(f"{cloud_id}_shell")
            shell = bpy.data.objects.new(f"{cloud_id}_shell", mesh)
            scene.collection.objects.link(shell)
            mod = shell.modifiers.new("shell", "VOLUME_TO_MESH")
            mod.object = vol
            mod.threshold = SHELL_THRESHOLD
            shell.hide_render = True
            bpy.context.view_layer.update()
            bvh = BVHTree.FromObject(shell, bpy.context.evaluated_depsgraph_get())
        except Exception as error:      # noqa: BLE001 (a missing modifier type on this Blender)
            shell_note = f"no depth shell ({error}); depth offset 0.5 everywhere"
            print(f"NOTE: {cloud_id}: {shell_note}")

        suns = {}
        for name, travel, colour in (("+x", (-1, 0, 0), (1, 0, 0)), ("+y", (0, -1, 0), (0, 1, 0)),
                                     ("+z", (0, 0, -1), (0, 0, 1)), ("-x", (1, 0, 0), (1, 0, 0)),
                                     ("-y", (0, 1, 0), (0, 1, 0)), ("-z", (0, 0, 1), (0, 0, 1))):
            data = bpy.data.lights.new(f"sun{name}", "SUN")
            data.energy = 1.0
            data.color = colour
            data.angle = math.radians(SUN_ANGLE_DEG)
            sun = bpy.data.objects.new(f"sun{name}", data)
            sun.rotation_euler = Vector(travel).to_track_quat("-Z", "Y").to_euler()
            scene.collection.objects.link(sun)
            suns[name] = sun

        cam_data = bpy.data.cameras.new("impostor")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = 2.0 * radius
        cam_data.clip_start = 0.001 * radius
        cam_data.clip_end = 10.0 * radius
        cam = bpy.data.objects.new("impostor", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam

        size = cim.atlas_px(args.views, args.px)
        pos = np.zeros((size, size, 4), np.float32)
        neg = np.zeros((size, size, 4), np.float32)
        tmp = out / f"_{cloud_id}_frame.exr"
        for j in range(args.views):
            for i in range(args.views):
                d = cim.frame_dir(i, j, args.views)
                right, up, forward = cim.frame_basis(d)
                eye = Vector(d) * (CAMERA_DISTANCE_RADII * radius)
                m = Matrix(((right[0], up[0], -forward[0], eye[0]),
                            (right[1], up[1], -forward[1], eye[1]),
                            (right[2], up[2], -forward[2], eye[2]),
                            (0.0, 0.0, 0.0, 1.0)))
                cam.matrix_world = m
                frames = {}
                for pass_name, on in (("pos", ("+x", "+y", "+z")), ("neg", ("-x", "-y", "-z"))):
                    for name, sun in suns.items():
                        sun.hide_render = name not in on
                    scene.render.filepath = str(tmp)
                    bpy.ops.render.render(write_still=True)
                    img = bpy.data.images.load(str(tmp), check_existing=False)
                    arr = np.array(img.pixels[:], np.float32).reshape(args.px, args.px, 4)[::-1]
                    bpy.data.images.remove(img)
                    alpha = arr[..., 3:4]
                    straight = np.where(alpha > 1e-4, arr[..., :3] / np.maximum(alpha, 1e-4), 0.0)
                    frames[pass_name] = (straight, arr[..., 3])
                depth = np.full((args.px, args.px), 0.5, np.float32)
                fwd = Vector(forward)
                for y in (range(args.px) if bvh is not None else ()):
                    for x in range(args.px):
                        su = (x + 0.5) / args.px - 0.5
                        sv = 0.5 - (y + 0.5) / args.px
                        origin = eye + Vector(right) * (su * 2 * radius) + Vector(up) * (sv * 2 * radius)
                        hit = bvh.ray_cast(origin, fwd, 10.0 * radius)
                        if hit[0] is not None:
                            offset = CAMERA_DISTANCE_RADII * radius - hit[3]
                            depth[y, x] = cim.encode_depth_offset(offset, radius)
                ox, oy = cim.frame_origin(i, j, args.px)
                pos[oy:oy + args.px, ox:ox + args.px, :3] = frames["pos"][0]
                pos[oy:oy + args.px, ox:ox + args.px, 3] = frames["pos"][1]
                neg[oy:oy + args.px, ox:ox + args.px, :3] = frames["neg"][0]
                neg[oy:oy + args.px, ox:ox + args.px, 3] = depth
        tmp.unlink(missing_ok=True)

        light_values = np.concatenate([pos[..., :3].ravel(), neg[..., :3].ravel()])
        nz = light_values[light_values > 0]
        light_scale = float(np.percentile(nz, cim.LIGHT_PERCENTILE)) if nz.size else 1.0
        enc = lambda v: np.clip(v / light_scale, 0.0, 1.0) ** (1.0 / cim.GAMMA)  # noqa: E731
        pos[..., :3] = enc(pos[..., :3])
        neg[..., :3] = enc(neg[..., :3])
        names = {}
        for pass_name, arr in (("pos", pos), ("neg", neg)):
            fname = f"{cloud_id}_{pass_name}.png"
            img = bpy.data.images.new(fname, size, size, alpha=True, float_buffer=False)
            img.colorspace_settings.name = "Non-Color"
            img.pixels = np.clip(arr[::-1], 0.0, 1.0).ravel().tolist()
            img.filepath_raw = str(out / fname)
            img.file_format = "PNG"
            img.save()
            names[pass_name] = fname
            atlas_names.append(fname)
        record = cim.cloud_record(
            cloud_id, vdb.name, cim.sha256_file(vdb), lo, hi, args.views, args.px, light_scale, names,
            {"engine": "Cycles CPU", "samples": args.samples, "volume_bounces": VOLUME_BOUNCES,
             "albedo": ALBEDO, "anisotropy": ANISOTROPY, "density_scale": DENSITY_SCALE,
             "sun_angle_deg": SUN_ANGLE_DEG, "shell_threshold": SHELL_THRESHOLD, "depth_shell": shell_note,
             "grids": grid_names,
             "blender": bpy.app.version_string})
        cim.write_json(out / f"{cloud_id}.json", record)
        index.append({"id": cloud_id, "json": f"{cloud_id}.json", "sphere_over_height": record["sphere_over_height"],
                      "light_scale": light_scale})
        print(f"BAKED: {cloud_id} from {vdb.name} (light_scale {light_scale:.4g}, radius {radius:.4g})")

    cim.write_json(out / "impostors.json", {"magic": "flightsim-cloud-impostors", "version": 1,
                                            "views": args.views, "px": args.px, "clouds": index,
                                            "licence": cim.LICENCE})
    cim.write_json(out / "PIN.json", cim.pin_json(out, atlas_names))
    total = sum((out / f).stat().st_size for f in atlas_names) / 1e6
    print(f"ATLASES: {len(atlas_names)} files, {total:.1f} MB in {out}")


if __name__ == "__main__":
    # blender -b exits 0 after an uncaught exception: fail the process by name instead.
    try:
        main(sys.argv)
    except BaseException as exc:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"BAKE-FAILED: {exc!r}", flush=True)
        os._exit(1)
    os._exit(0)
