"""Bake JangaFX's CC0 "Tornado Looping" VDB into the tornado's flipbook atlas.

The owner's request (2026-11-14): the tornado's solid funnel replaced, in BEAUTY renders,
by a real volumetric simulation. The Windows laptop's integrated GPU cannot ray-march a
VDB live (no SM6, no heterogeneous volumes), so the volume is rendered OFFLINE, once, by
Blender (a free tool, not Unreal) into a flipbook: N frames of the looping sim, seen from
the side, packed into one atlas that M_TornadoFlipbook plays on a camera-facing card
(FlightSimTornadoBeauty.cpp). The raw VDB (~1.7 GB) never enters the repository; only the
atlas, its JSON and the PIN do.

Run on the render machine (Blender 4.x):

    blender -b -P scripts/bake_tornado_flipbook.py -- \
        --out assets/looks/tornado_vdb
    (no --vdb-dir: scripts/fetch_tornado_vdb.py fills <repo>/../flightsim_assets/jangafx_tornado
    first, or skips it when already there; --vdb-dir <folder> points at another copy)

The pure-python half (argument parsing, the frame plan, the atlas layout, the PNG codec,
the atlas packing, the JSON and the PIN) imports nothing from Blender and is what
tests/test_tornado_vdb_flipbook.py exercises; ``bpy`` is imported only inside
``bake_with_blender``.

Decisions, stated:
  * ALPHA is STRAIGHT (not premultiplied): Blender writes film-transparent PNGs straight,
    and the material uses the texel's colour as the smoke's shade and its alpha as its
    opacity (BLEND_TRANSLUCENT is a straight-alpha blend).
  * LIGHTING in the bake is NEUTRAL (a grey sky dome and a white sun at SUN_ELEVATION_DEG):
    the atlas carries the smoke's own self-shadowing and thickness; the scene's light
    colour comes from the engine (the material is lit translucent, per pixel), so the
    funnel takes the storm's light like the dust puffs beside it.
  * NO FIRE: a tornado is dust and condensation, so the temperature grid (if any) drives
    no emission (Blackbody Intensity 0, Emission Strength 0).
  * VIEW: an orthographic camera, horizontal, from the side, framing the union of the
    volume's bounds over the frames baked (an aircraft sees a tornado from the side).
  * Every number here is UNCALIBRATED (probe #10 on the render machine decides).
"""
from __future__ import annotations

import argparse
import os
import hashlib
import json
import math
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

#: Frames baked from the loop (evenly spaced), the frame size and the atlas cap.
DEFAULT_FRAMES = 64
DEFAULT_FRAME_W = 256
DEFAULT_FRAME_H = 512
ATLAS_MAX_SIDE = 4096
#: The sim's frame rate (EmberGen's default export), so the loop plays at its own speed.
DEFAULT_FPS = 24.0
#: The bake's light (neutral): the sun's elevation and the sky dome's grey.
SUN_ELEVATION_DEG = 35.0
SUN_STRENGTH = 3.0
SKY_GREY = 0.55
#: The smoke's albedo in the bake (a neutral grey; the engine tints it) and density scale.
SMOKE_ALBEDO = 0.62
DENSITY_SCALE = 1.0
DEFAULT_SAMPLES = 64
#: Margin around the volume's bounds in the frame (a share of the framed size).
FRAME_MARGIN = 0.04
ATLAS_NAME = "T_TornadoFlipbook.png"
JSON_NAME = "tornado_flipbook.json"
PIN_NAME = "PIN.json"
SOURCE = {
    "name": "JangaFX EmberGen free VDB: Tornado Looping",
    "author": "JangaFX",
    "url": "https://jangafx.com/software/embergen/download/free-vdb-animations",
    "licence": "CC0-1.0",
}


# -- the pure-python half (no bpy) -----------------------------------------------------

def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """The script's own arguments: everything after Blender's ``--``."""
    if "--" in argv:
        argv = list(argv)[list(argv).index("--") + 1:]
    ap = argparse.ArgumentParser(prog="bake_tornado_flipbook.py", description=__doc__.splitlines()[0])
    ap.add_argument("--vdb-dir", type=Path, default=None,
                    help="the unzipped VDB sequence; absent: scripts/fetch_tornado_vdb.py fills the cache first")
    ap.add_argument("--out", required=True, type=Path, help="assets/looks/tornado_vdb")
    ap.add_argument("--zip-sha256", default="",
                    help="the sha256 of the downloaded zip, recorded (default: fetch_tornado_vdb's pin)")
    ap.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    ap.add_argument("--frame-w", type=int, default=DEFAULT_FRAME_W)
    ap.add_argument("--frame-h", type=int, default=DEFAULT_FRAME_H)
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    ap.add_argument("--metres-per-unit", type=float, default=1.0,
                    help="the VDB's scale (recorded; the engine sizes the card from the funnel)")
    ap.add_argument("--grid", default="density", help="the density grid's name")
    ns = ap.parse_args(argv)
    if ns.frames < 2:
        ap.error("--frames must be at least 2 (a loop crossfades between frames)")
    atlas_layout(ns.frames, ns.frame_w, ns.frame_h)   # raises on an atlas over the cap
    return ns


def plan_frames(vdb_count: int, frames: int) -> List[int]:
    """Indices into the VDB sequence, evenly spaced over ONE loop (the last baked frame is
    one step before the first again, so the flipbook loops without a repeated frame)."""
    if vdb_count < 1:
        raise ValueError("no VDB frames")
    frames = min(frames, vdb_count)
    return [int(math.floor(i * vdb_count / frames)) for i in range(frames)]


def atlas_layout(frames: int, frame_w: int, frame_h: int,
                 max_side: int = ATLAS_MAX_SIDE) -> Tuple[int, int, int, int]:
    """(cols, rows, atlas width, atlas height): the squarest grid of whole frames whose
    atlas fits max_side on both axes. A ValueError when none fits."""
    best = None
    for cols in range(1, frames + 1):
        rows = -(-frames // cols)
        w, h = cols * frame_w, rows * frame_h
        if w > max_side or h > max_side:
            continue
        score = abs(math.log(w / h))
        if best is None or score < best[0]:
            best = (score, cols, rows, w, h)
    if best is None:
        raise ValueError(f"{frames} frames of {frame_w}x{frame_h} do not fit a {max_side}px atlas")
    return best[1], best[2], best[3], best[4]


def png_encode(rgba) -> bytes:
    """An 8-bit RGBA, non-interlaced PNG of an (h, w, 4) uint8 array (filter 0 rows)."""
    import numpy as np

    a = np.ascontiguousarray(rgba, dtype=np.uint8)
    h, w, c = a.shape
    if c != 4:
        raise ValueError("RGBA only")
    raw = b"".join(b"\x00" + a[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_decode(data: bytes):
    """An (h, w, 4) uint8 array from an 8-bit RGB or RGBA non-interlaced PNG (all five
    filters), which is what Blender writes; anything else is a ValueError by name."""
    import numpy as np

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    if ihdr is None:
        raise ValueError("PNG without IHDR")
    w, h, depth, colour, _, _, interlace = ihdr
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        raise ValueError(f"PNG depth {depth} colour type {colour} interlace {interlace}: only 8-bit RGB/RGBA")
    bpp = 4 if colour == 6 else 3
    raw = zlib.decompress(idat)
    stride = w * bpp
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=y * (stride + 1) + 1).astype(np.int32)
        cur = np.zeros(stride, dtype=np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 0xFF
        else:
            for x in range(stride):
                left = cur[x - bpp] if x >= bpp else 0
                up = prev[x]
                ul = prev[x - bpp] if x >= bpp else 0
                if f == 1:
                    v = left
                elif f == 3:
                    v = (left + up) >> 1
                elif f == 4:
                    p = left + up - ul
                    pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                    v = left if pa <= pb and pa <= pc else (up if pb <= pc else ul)
                else:
                    raise ValueError(f"PNG filter {f}")
                cur[x] = (line[x] + v) & 0xFF
        out[y] = cur
        prev = cur
    img = out.reshape(h, w, bpp)
    if bpp == 3:
        img = np.concatenate([img, np.full((h, w, 1), 255, dtype=np.uint8)], axis=2)
    return img


def pack_atlas(frames, cols: int, rows: int):
    """The frames (each (h, w, 4) uint8, top row first) in reading order on a cols x rows
    grid; unused cells transparent black."""
    import numpy as np

    if not frames:
        raise ValueError("no frames")
    h, w = frames[0].shape[:2]
    if len(frames) > cols * rows:
        raise ValueError(f"{len(frames)} frames on a {cols}x{rows} grid")
    atlas = np.zeros((rows * h, cols * w, 4), dtype=np.uint8)
    for i, frame in enumerate(frames):
        if frame.shape[:2] != (h, w):
            raise ValueError(f"frame {i} is {frame.shape[1]}x{frame.shape[0]}, not {w}x{h}")
        r, c = divmod(i, cols)
        atlas[r * h:(r + 1) * h, c * w:(c + 1) * w] = frame
    return atlas


def flipbook_record(*, frames: int, cols: int, rows: int, frame_w: int, frame_h: int,
                    vdb_count: int, used: Sequence[int], fps: float,
                    bounds_min: Sequence[float], bounds_max: Sequence[float],
                    metres_per_unit: float, grid: str, zip_sha256: str) -> Dict:
    """tornado_flipbook.json: what the material script reads (cols, rows, frames,
    loop_seconds, frame_aspect) and what the record states (source, licence, bounds)."""
    loop_seconds = vdb_count / fps if fps > 0 else 0.0
    return {
        "asset": "tornado_vdb",
        "source": dict(SOURCE, zip_sha256=zip_sha256 or None),
        "frames": frames, "cols": cols, "rows": rows,
        "frame_px": [frame_w, frame_h], "atlas_px": [cols * frame_w, rows * frame_h],
        "frame_aspect": frame_w / frame_h,
        "vdb_frame_count": vdb_count, "vdb_frames_used": list(used), "fps": fps,
        "loop_seconds": loop_seconds,
        "grid": grid,
        "bounds_units": {"min": list(bounds_min), "max": list(bounds_max)},
        "metres_per_unit": metres_per_unit,
        "bounds_m": {"min": [v * metres_per_unit for v in bounds_min],
                     "max": [v * metres_per_unit for v in bounds_max]},
        "view": "orthographic, horizontal, from the side, framing the union of the bounds",
        "light": {"sun_elevation_deg": SUN_ELEVATION_DEG, "sun_strength": SUN_STRENGTH,
                  "sky_grey": SKY_GREY, "basis": "neutral: the engine lights the card"},
        "smoke": {"albedo": SMOKE_ALBEDO, "density_scale": DENSITY_SCALE, "fire": "none"},
        "alpha": "straight (not premultiplied): colour is the smoke's shade, alpha its opacity",
        "status": "UNCALIBRATED: baked offline by Blender, no frame rendered in the engine yet",
    }


def write_json(path: Path, record: Dict) -> None:
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def pin_record(out: Path, zip_sha256: str) -> Dict:
    """PIN.json for the committed bake: each file's repo path, bytes and sha256 (the row
    format pinned_texture in scripts/ue_create_materials.py checks before import)."""
    files = {}
    for name in (ATLAS_NAME, JSON_NAME):
        p = out / name
        data = p.read_bytes()
        files[name] = {"path": f"assets/looks/tornado_vdb/{name}", "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()}
    return {"asset": "tornado_vdb", "title": "Tornado flipbook baked from JangaFX's CC0 Tornado Looping VDB",
            "source": SOURCE, "source_zip_sha256": zip_sha256 or None,
            "baker": "scripts/bake_tornado_flipbook.py (Blender, offline)", "licence": "CC0-1.0",
            "licence_file": "LICENSE", "visual_only": True,
            "status": "UNMEASURED: no engine frame rendered yet", "files": files}


# -- the Blender half ------------------------------------------------------------------

def resolve_vdb_dir(ns: argparse.Namespace, fetcher=None) -> Path:
    """--vdb-dir, else the asset cache filled by scripts/fetch_tornado_vdb.py (which skips
    the download when the cache is already complete); the zip's pinned sha256 is recorded
    when --zip-sha256 is not given."""
    if ns.vdb_dir is not None:
        return Path(ns.vdb_dir)
    if fetcher is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import fetch_tornado_vdb as fetcher
    found = fetcher.fetch()
    if not ns.zip_sha256:
        ns.zip_sha256 = fetcher.PIN.get("zip_sha256") or ""
    return Path(found)


def bake_with_blender(ns: argparse.Namespace) -> int:   # pragma: no cover (needs Blender)
    import bpy
    from mathutils import Vector

    ns.vdb_dir = resolve_vdb_dir(ns)

    vdbs = sorted(p for p in Path(ns.vdb_dir).iterdir() if p.suffix.lower() == ".vdb")
    if not vdbs:
        print(f"BAKE-FAILED: no .vdb in {ns.vdb_dir}")
        return 2
    used = plan_frames(len(vdbs), ns.frames)
    cols, rows, aw, ah = atlas_layout(len(used), ns.frame_w, ns.frame_h)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.object.volume_import(filepath=str(vdbs[0]), directory=str(ns.vdb_dir),
                                 files=[{"name": p.name} for p in vdbs], use_sequence_detection=True)
    vol = bpy.context.selected_objects[0]
    vol.data.sequence_mode = "REPEAT"
    vol.data.frame_start = 1
    vol.data.frame_duration = len(vdbs)
    grids = [g.name for g in vol.data.grids] if vol.data.grids.load() else []
    print(f"BAKE: {len(vdbs)} VDB frames, grids {grids}")
    if ns.grid not in grids:
        print(f"BAKE-FAILED: grid {ns.grid!r} not in {grids} (pass --grid)")
        return 2
    # The smoke: Principled Volume on the density grid; no fire.
    mat = bpy.data.materials.new("TornadoSmoke")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    pv.inputs["Color"].default_value = (SMOKE_ALBEDO, SMOKE_ALBEDO, SMOKE_ALBEDO, 1.0)
    pv.inputs["Density"].default_value = DENSITY_SCALE
    if "Density Attribute" in pv.inputs:
        pv.inputs["Density Attribute"].default_value = ns.grid
    for name in ("Blackbody Intensity", "Emission Strength"):
        if name in pv.inputs:
            pv.inputs[name].default_value = 0.0
    nt.links.new(pv.outputs["Volume"], out.inputs["Volume"])
    vol.data.materials.append(mat)
    # Bounds over the frames baked (the evaluated volume's box per frame).
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for i in used:
        scene.frame_set(i + 1)
        ev = vol.evaluated_get(bpy.context.evaluated_depsgraph_get())
        for corner in ev.bound_box:
            p = ev.matrix_world @ Vector(corner)
            for k in range(3):
                lo[k], hi[k] = min(lo[k], p[k]), max(hi[k], p[k])
    centre = [(a + b) / 2.0 for a, b in zip(lo, hi)]
    size_x, size_z = hi[0] - lo[0], hi[2] - lo[2]
    aspect = ns.frame_w / ns.frame_h
    ortho = max(size_z, size_x / aspect) * (1.0 + 2.0 * FRAME_MARGIN)
    # World: a grey sky dome; a white sun from the camera's side at SUN_ELEVATION_DEG.
    world = bpy.data.worlds.new("Sky")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (SKY_GREY, SKY_GREY, SKY_GREY, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = SUN_STRENGTH
    sun.rotation_euler = (math.radians(90.0 - SUN_ELEVATION_DEG), 0.0, math.radians(30.0))
    scene.collection.objects.link(sun)
    # Camera: orthographic, horizontal, looking along +Y at the bounds' centre.
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = ortho * max(1.0, aspect)   # Blender's ortho_scale spans the longer side
    cam.location = (centre[0], lo[1] - 4.0 * max(size_x, size_z), centre[2])
    cam.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    cam.data.clip_end = 20.0 * max(size_x, size_z, 1.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    r = scene.render
    r.engine = "CYCLES"
    scene.cycles.samples = ns.samples
    r.film_transparent = True
    r.resolution_x, r.resolution_y, r.resolution_percentage = ns.frame_w, ns.frame_h, 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    r.image_settings.color_depth = "8"
    scene.view_settings.view_transform = "Standard"
    # Absolute: Blender resolves a relative render.filepath against the drive root, not the cwd.
    ns.out = Path(ns.out).resolve()
    frames_dir = ns.out / "_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    pngs = []
    for n, i in enumerate(used):
        scene.frame_set(i + 1)
        r.filepath = str(frames_dir / f"frame_{n:03d}.png")
        bpy.ops.render.render(write_still=True)
        pngs.append(png_decode(Path(r.filepath).read_bytes()))
        print(f"BAKE: frame {n + 1}/{len(used)} (VDB {i})")
    out_dir = Path(ns.out)
    (out_dir / ATLAS_NAME).write_bytes(png_encode(pack_atlas(pngs, cols, rows)))
    write_json(out_dir / JSON_NAME, flipbook_record(
        frames=len(used), cols=cols, rows=rows, frame_w=ns.frame_w, frame_h=ns.frame_h,
        vdb_count=len(vdbs), used=used, fps=ns.fps, bounds_min=lo, bounds_max=hi,
        metres_per_unit=ns.metres_per_unit, grid=ns.grid, zip_sha256=ns.zip_sha256))
    write_json(out_dir / PIN_NAME, pin_record(out_dir, ns.zip_sha256))
    print(f"BAKE-DONE: {out_dir / ATLAS_NAME} ({aw}x{ah}, {len(used)} frames, {cols}x{rows}); "
          f"delete {frames_dir} before committing")
    return 0


def main(argv: Sequence[str]) -> int:   # pragma: no cover (needs Blender)
    return bake_with_blender(parse_args(argv))


if __name__ == "__main__":   # pragma: no cover
    # blender -b exits 0 after an uncaught exception: fail the process by name instead.
    try:
        code = main(sys.argv)
    except BaseException as exc:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"BAKE-FAILED: {exc!r}", flush=True)
        os._exit(1)
    os._exit(int(code or 0))
