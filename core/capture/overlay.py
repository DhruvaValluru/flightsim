"""Draw the recorded geometry ON TOP of the frames the engine rendered.

This is the Windows deliverable, and the reason the geometry preview is
only a fallback: a synthetic picture of where the camera pointed proves
that the manifest is self-consistent, and nothing else. An overlay on
the REAL frame proves the thing that matters -- that the labels land on
the pixels. If the crosshair sits on the rendered aircraft and the
landmark marks sit on the rendered ground features, the manifest is
usable as training data. If they sit anywhere else, it is not, and you
can see which at a glance instead of reading a tolerance.

Each overlaid frame carries:

* a **crosshair and box** at the aircraft's projected position, from the
  manifest's pose and intrinsics;
* the **aircraft's attitude**, drawn as an oriented body glyph, so a
  frame whose recorded roll disagrees with the rendered horizon is
  visible rather than merely out of tolerance;
* every **landmark** in frame, marked twice where the engine also
  reported it: a circle at the manifest's projection and a cross at the
  engine's own ``ProjectToPixel`` pixel out of ``render.json``. Two
  implementations, two marks. When they coincide there is one symbol;
  when they do not, the gap is the error, drawn at the scale it
  actually is;
* the **horizon** implied by the recorded pose, which should lie along
  the rendered horizon;
* a caption naming the camera, the frame, the simulation time and the
  lens the frame was taken through.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional

from .landmarks import landmark_point
from .verify import (_engine_landmark_pixels, _record_in_enu, axes_from_quat,
                     project_point, scene_to_enu)

#: Colours, chosen to stay legible over both sky and terrain.
AIRCRAFT = (255, 214, 64)
MANIFEST_MARK = (90, 220, 255)
ENGINE_MARK = (255, 96, 128)
HORIZON = (255, 255, 255)


def _body_glyph(record):
    """The aircraft's own axes as world segments (see preview._body_glyph;
    duplicated deliberately -- this module draws over real pixels and
    must not import the engine-less preview path)."""
    a = record["aircraft"]
    roll, pitch, yaw = (math.radians(a["roll_deg"]),
                        math.radians(a["pitch_deg"]),
                        math.radians(a["heading_deg"]))
    cr, sr, cp, sp, cy, sy = (math.cos(roll), math.sin(roll),
                              math.cos(pitch), math.sin(pitch),
                              math.cos(yaw), math.sin(yaw))

    def to_world(bx, by, bz):
        n = ((cp * cy) * bx + (sr * sp * cy - cr * sy) * by
             + (cr * sp * cy + sr * sy) * bz)
        e = ((cp * sy) * bx + (sr * sp * sy + cr * cy) * by
             + (cr * sp * sy - sr * cy) * bz)
        d = (-sp) * bx + (sr * cp) * by + (cr * cp) * bz
        return (a["north_m"] + n, a["east_m"] + e, a["alt_m"] - d)

    return [[to_world(24.0, 0.0, 0.0), to_world(-22.0, 0.0, 0.0)],
            [to_world(0.0, -28.0, 0.0), to_world(0.0, 28.0, 0.0)],
            [to_world(-20.0, 0.0, 0.0), to_world(-20.0, 0.0, -8.0)]]


def _horizon_points(record, width: int):
    """The two endpoints of the pose's horizon across the image."""
    forward, right, up = axes_from_quat(record["quaternion_wxyz"])
    cx, cy = record["principal_point_px"]
    if abs(up[2]) < 1e-9:
        return None
    points = []
    for u in (0.0, float(width)):
        x_cam = (u - cx) / record["fx_px"]
        vertical = forward[2] + x_cam * right[2]
        points.append((u, cy + (vertical / up[2]) * record["fy_px"]))
    return points


def draw_overlays(manifest: Dict, run_dir, out_subdir: str = "overlays",
                  max_frames: Optional[int] = None) -> List[Path]:
    """Write one overlaid PNG per rendered frame; returns the paths.

    Frames that were not rendered are skipped silently -- the manifest
    names every frame it scheduled whether or not pixels exist, and this
    function's job is to annotate the ones that do.
    """
    from PIL import Image, ImageDraw

    run_dir = Path(run_dir)
    engine = _engine_landmark_pixels(run_dir)
    landmarks = manifest.get("landmarks") or []
    frames = manifest.get("frames", [])
    if max_frames is not None:
        # Per CAMERA, not per run. Slicing the flat list took the first
        # N records, which are all one camera's, so a two-camera run
        # produced overlays for the chase view and none at all for the
        # tower -- and the tower is the one whose geometry is least
        # obvious by eye. The cap is there to keep the count sane on a
        # long clip, not to pick a camera.
        seen: Dict[str, int] = {}
        kept = []
        for record in frames:
            camera = str(record.get("camera_id"))
            if seen.get(camera, 0) >= max_frames:
                continue
            seen[camera] = seen.get(camera, 0) + 1
            kept.append(record)
        frames = kept

    # These marks are drawn ON the host's pixels, so every world point
    # here has to be projected in the host's own frame -- otherwise the
    # circle and the cross are 0.6 px apart for no reason but the frame
    # each was computed in, which is exactly the disagreement the
    # overlay exists to make visible. See verify.scene_to_enu.
    to_enu = scene_to_enu(manifest)
    world = (lambda p: to_enu(*p)) if to_enu is not None else (lambda p: p)

    written: List[Path] = []
    for record in frames:
        source = run_dir / str(record.get("file", ""))
        if not source.is_file():
            continue
        placed = _record_in_enu(record, to_enu)
        image = Image.open(source).convert("RGB")
        draw = ImageDraw.Draw(image)
        width, height = image.size

        horizon = _horizon_points(record, width)
        if horizon is not None:
            draw.line(horizon, fill=HORIZON, width=1)

        measured = engine.get(str(record.get("file")), {})
        for landmark in landmarks:
            name = str(landmark["name"])
            u, v, z = project_point(placed, world(landmark_point(landmark)))
            if z > 0 and math.isfinite(u) and 0 <= u < width and 0 <= v < height:
                draw.ellipse([u - 5, v - 5, u + 5, v + 5],
                             outline=MANIFEST_MARK, width=2)
            entry = measured.get(name)
            if entry and entry[2]:
                px, py = entry[0], entry[1]
                if 0 <= px < width and 0 <= py < height:
                    draw.line([(px - 6, py), (px + 6, py)], fill=ENGINE_MARK)
                    draw.line([(px, py - 6), (px, py + 6)], fill=ENGINE_MARK)

        for segment in _body_glyph(record):
            pixels = []
            for point in segment:
                u, v, z = project_point(placed, world(point))
                pixels.append((u, v) if z > 0 and math.isfinite(u) else None)
            if all(p is not None for p in pixels):
                draw.line(pixels, fill=AIRCRAFT, width=2)

        u, v, z = project_point(placed, world(
            (record["aircraft"]["north_m"], record["aircraft"]["east_m"],
             record["aircraft"]["alt_m"])))
        if z > 0 and math.isfinite(u):
            draw.line([(u - 18, v), (u - 6, v)], fill=AIRCRAFT, width=2)
            draw.line([(u + 6, v), (u + 18, v)], fill=AIRCRAFT, width=2)
            draw.line([(u, v - 18), (u, v - 6)], fill=AIRCRAFT, width=2)
            draw.line([(u, v + 6), (u, v + 18)], fill=AIRCRAFT, width=2)

        caption = (f"{record['camera_id']}  #{record['index']:04d}  "
                   f"t={record['t_s']:.2f}s  "
                   f"{record['focal_length_mm']:.1f}mm on "
                   f"{record['sensor_width_mm']:.1f}mm  "
                   f"{int(record['width_px'])}x{int(record['height_px'])}")
        draw.rectangle([0, 0, width, 32], fill=(10, 12, 18))
        draw.text((6, 4), caption, fill=(235, 235, 235))
        draw.text((6, 17),
                  "circle = manifest projection   cross = engine "
                  "projection   they should coincide",
                  fill=(160, 170, 185))

        path = (run_dir / out_subdir / str(record["camera_id"])
                / f"overlay_{record['index']:04d}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        written.append(path)
    return written
