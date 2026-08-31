"""Geometry previews: what each scheduled frame would see, engine-free.

One PNG per scheduled capture, drawn with numpy + Pillow only
(matplotlib is not a dependency of this project): the scene's terrain
as shaded-relief points (or a flat reference grid), the aircraft's
whole flown track, and the aircraft's position at the capture instant,
all projected through the frame's OWN recorded pose and intrinsics
(:func:`core.capture.verify.project_point` -- the independent
implementation, so the preview doubles as an eyeball check on the
recorded geometry: if the manifest were wrong, the pictures would
point the wrong way).

These are geometry previews, not renders: no lighting, no meshes, no
claim beyond "this is where the camera pointed".
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .verify import project_point

#: Preview scale: the full output resolution is honest but slow to
#: write hundreds of; previews draw at 1/2 size and say so in the name.
PREVIEW_SCALE = 2


def _terrain_points(heightfield, frame, grid: int = 48):
    """A coarse (north, east, alt, shade) sampling of the raster in the
    scene frame's local coordinates."""
    import numpy as np

    z = heightfield.elevations()
    rows = np.linspace(0, heightfield.height - 1, grid).astype(int)
    cols = np.linspace(0, heightfield.width - 1, grid).astype(int)
    lo, hi = float(z.min()), float(z.max())
    span = (hi - lo) or 1.0
    g = heightfield.georeference
    points = []
    for r in rows:
        for c in cols:
            x = g.origin_x_m + c * g.pixel_size_m
            y = g.origin_y_m - r * g.pixel_size_m
            alt = float(z[r, c])
            shade = int(64 + 160 * (alt - lo) / span)
            points.append((y - frame.origin_y_m, x - frame.origin_x_m,
                           alt, shade))
    return points


def _flat_grid(terrain_elevation_m: float, extent_m: float = 4000.0,
               step_m: float = 500.0):
    points = []
    n = -extent_m
    while n <= extent_m:
        e = -extent_m
        while e <= extent_m:
            points.append((n, e, terrain_elevation_m, 90))
            e += step_m
        n += step_m
    return points


def render_previews(manifest: Dict, out_dir, heightfield=None,
                    scene_frame=None,
                    terrain_elevation_m: float = 0.0,
                    max_frames: Optional[int] = None) -> List[Path]:
    """Write one preview PNG per frame record; returns the paths.

    ``scene_frame`` is needed only when a heightfield is given (to
    express the raster in the manifest's local frame).
    """
    from PIL import Image, ImageDraw

    if heightfield is not None and scene_frame is not None:
        ground = _terrain_points(heightfield, scene_frame)
    else:
        ground = _flat_grid(terrain_elevation_m)

    # The aircraft's whole track, one point per recorded frame instant
    # (the manifest's own per-frame aircraft states, deduplicated).
    track = {}
    for record in manifest.get("frames", []):
        a = record["aircraft"]
        track[record["sample_index"]] = (a["north_m"], a["east_m"],
                                         a["alt_m"])
    track_points = [track[k] for k in sorted(track)]

    written: List[Path] = []
    frames = manifest.get("frames", [])
    if max_frames is not None:
        frames = frames[:max_frames]
    for record in frames:
        w = int(record["width_px"]) // PREVIEW_SCALE
        h = int(record["height_px"]) // PREVIEW_SCALE
        image = Image.new("RGB", (w, h), (12, 16, 24))
        draw = ImageDraw.Draw(image)

        def to_px(point):
            u, v, z = project_point(record, point)
            if z <= 0:
                return None
            return u / PREVIEW_SCALE, v / PREVIEW_SCALE

        for north, east, alt, shade in ground:
            px = to_px((north, east, alt))
            if px and 0 <= px[0] < w and 0 <= px[1] < h:
                draw.point(px, fill=(shade, shade, shade))
        previous = None
        for point in track_points:
            px = to_px(point)
            if px is not None and previous is not None:
                draw.line([previous, px], fill=(80, 160, 255), width=1)
            previous = px
        aircraft = record["aircraft"]
        px = to_px((aircraft["north_m"], aircraft["east_m"],
                    aircraft["alt_m"]))
        if px is not None:
            r = 4
            draw.ellipse([px[0] - r, px[1] - r, px[0] + r, px[1] + r],
                         outline=(255, 200, 60), width=2)
        draw.text((4, 4),
                  f"{record['camera_id']} #{record['index']:03d} "
                  f"t={record['t_s']:.1f}s (geometry preview, 1/"
                  f"{PREVIEW_SCALE} scale)",
                  fill=(220, 220, 220))

        path = (Path(out_dir) / "previews" / record["camera_id"]
                / f"preview_{record['index']:05d}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        written.append(path)
    return written
