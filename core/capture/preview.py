"""Geometry previews: what each scheduled frame looks out at, engine-free.

The Phase 1 preview drew the scene as single pixels -- ``draw.point``
per terrain sample, a one-pixel track line, and an UNFILLED circle for
the aircraft. Measured on the committed two-camera example, one frame
carried 128 non-background pixels on a 640x360 canvas below its
caption: 64 track, 40 circle, ~24 ground. There was no horizon, no
surface and no attitude, so a viewer could not tell a correct pose from
a wrong one, which was the only job the picture had.

This draws a scene instead:

* **sky and ground** separated by the true horizon for the recorded
  pose, so which way the camera is pointing is legible at a glance;
* **the terrain as filled, depth-sorted, shaded quads** -- Lambert
  shading off each cell's own normal, painter's algorithm back to
  front -- so a ridge reads as a ridge (Phase 1 shaded by absolute
  elevation and called it relief);
* **the aircraft as an oriented body glyph** -- fuselage, wings and fin
  projected through its own recorded roll, pitch and heading -- so the
  one property the phase most wants to show, that only the cockpit
  preset inherits roll, is visible rather than merely recorded. A
  circle has no orientation; a cockpit view and a chase view drew the
  same circle;
* **the landmarks**, labelled, which are the points verification grades
  against.

Everything is projected through the frame's OWN recorded pose and
intrinsics (:func:`core.capture.verify.project_point`), so a wrong
manifest draws a wrong picture.

These remain geometry previews, not renders: no materials, no lighting
model beyond a single lambert term, no meshes. On Windows with the
engine built, the deliverable is the rendered frame with
:mod:`core.capture.overlay` drawn over it; this is what an
engine-less machine gets, and it is labelled as such on every frame.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .verify import axes_from_quat, project_point

#: Preview scale divisor: previews draw at 1/PREVIEW_SCALE of the
#: recorded resolution and say so in the caption.
PREVIEW_SCALE = 1

#: Ground mesh extent and cell size for a flat scene, metres. The extent
#: has to reach past where the haze has fully closed in, or the mesh's
#: own edge draws a false horizon partway up the frame.
FLAT_EXTENT_M = 26000.0
FLAT_CELL_M = 1000.0

#: Distance at which the ground has faded to the horizon colour. An
#: absolute scale, not "the furthest cell in this mesh": the latter made
#: near ground haze as hard as far ground whenever the mesh was small.
HAZE_SCALE_M = 42000.0

#: Terrain mesh resolution for a raster scene (cells per side).
TERRAIN_CELLS = 64

#: Sun direction for the lambert term (unit, north/east/up). A low
#: north-west sun so slopes separate instead of flattening out.
SUN = (-0.45, -0.55, 0.70)

SKY_TOP = (44, 78, 128)
SKY_HORIZON = (146, 174, 204)
#: What the ground fades TO. Fully hazed mesh must land on this exactly,
#: or the mesh's far edge shows as a seam against the fill behind it.
GROUND_HAZE = (138, 160, 182)


def _shade(base: Tuple[int, int, int], lambert: float,
           haze: float) -> Tuple[int, int, int]:
    """Lambert term, then distance haze toward the horizon colour."""
    lit = [c * (0.35 + 0.65 * max(0.0, lambert)) for c in base]
    haze = min(max(haze, 0.0), 1.0)
    return tuple(int(round(v * (1.0 - haze) + h * haze))
                 for v, h in zip(lit, GROUND_HAZE))


def _normal(a, b, c):
    """Unit normal of a triangle in (north, east, up)."""
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1],
         u[2] * v[0] - u[0] * v[2],
         u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(x * x for x in n)) or 1.0
    n = tuple(x / length for x in n)
    return n if n[2] >= 0 else tuple(-x for x in n)


def _flat_mesh(terrain_elevation_m: float, centre) -> List[Tuple]:
    """A ground plane as quads about the track centre, alternating shade
    so a flat surface still reads as a surface."""
    cells = []
    steps = int(FLAT_EXTENT_M / FLAT_CELL_M)
    for i in range(-steps, steps):
        for j in range(-steps, steps):
            n0 = centre[0] + i * FLAT_CELL_M
            e0 = centre[1] + j * FLAT_CELL_M
            n1, e1 = n0 + FLAT_CELL_M, e0 + FLAT_CELL_M
            corners = ((n0, e0, terrain_elevation_m),
                       (n1, e0, terrain_elevation_m),
                       (n1, e1, terrain_elevation_m),
                       (n0, e1, terrain_elevation_m))
            base = (118, 128, 96) if (i + j) % 2 else (100, 112, 84)
            cells.append((corners, base))
    return cells


def _terrain_mesh(heightfield, frame) -> List[Tuple]:
    """The raster as quads in the manifest's local frame."""
    import numpy as np

    z = heightfield.elevations()
    g = heightfield.georeference
    rows = np.linspace(0, heightfield.height - 1, TERRAIN_CELLS).astype(int)
    cols = np.linspace(0, heightfield.width - 1, TERRAIN_CELLS).astype(int)
    lo, hi = float(z.min()), float(z.max())
    span = (hi - lo) or 1.0

    def point(r, c):
        x = g.origin_x_m + c * g.pixel_size_m
        y = g.origin_y_m - r * g.pixel_size_m
        return (y - frame.origin_y_m, x - frame.origin_x_m, float(z[r, c]))

    cells = []
    for ri in range(len(rows) - 1):
        for ci in range(len(cols) - 1):
            corners = (point(rows[ri], cols[ci]),
                       point(rows[ri + 1], cols[ci]),
                       point(rows[ri + 1], cols[ci + 1]),
                       point(rows[ri], cols[ci + 1]))
            height = (sum(p[2] for p in corners) / 4.0 - lo) / span
            # Rock above, grass below -- a height ramp on TOP of the
            # lambert term, never instead of it.
            base = (int(88 + 90 * height), int(96 + 78 * height),
                    int(78 + 84 * height))
            cells.append((corners, base))
    return cells


def _horizon(draw, record, width, height):
    """Sky above, hazed ground below, split on the true horizon for this
    pose. The single most useful mark in the picture: it says which way
    the camera is pointing before anything else is drawn."""
    forward, right, up = axes_from_quat(record["quaternion_wxyz"])
    cx, cy = (c / PREVIEW_SCALE for c in record["principal_point_px"])
    fy = record["fy_px"] / PREVIEW_SCALE
    fx = record["fx_px"] / PREVIEW_SCALE

    def horizon_v(u_px: float) -> float:
        """Image row of the horizon at an image column: the ray through
        (u, v) is level when its up-component is zero."""
        x_cam = (u_px - cx) / fx
        direction_flat = tuple(f + x_cam * r for f, r in zip(forward, right))
        # v such that (forward + x*right - y*up) has zero vertical part.
        denom = up[2]
        if abs(denom) < 1e-9:
            return math.nan
        y_cam = direction_flat[2] / denom
        return cy + y_cam * fy

    for y in range(height):
        blend = y / max(height - 1, 1)
        draw.line([(0, y), (width, y)],
                  fill=tuple(int(a + (b - a) * blend)
                             for a, b in zip(SKY_TOP, SKY_HORIZON)))
    left, rightv = horizon_v(0.0), horizon_v(float(width))
    if math.isnan(left) or math.isnan(rightv):
        return
    draw.polygon([(0, left), (width, rightv), (width, height), (0, height)],
                 fill=GROUND_HAZE)
    draw.line([(0, left), (width, rightv)], fill=(190, 200, 210), width=1)


def airframe_geometry(aircraft: str):
    """(faces, source) for an airframe: the REAL mesh the engine imports
    when its sources are on disk, else the parametric stand-in.

    Returned faces are (body-frame vertices, rgb). The caller says which
    source it drew, because "that is the real 747" and "that is a
    stand-in" are different claims.
    """
    from .aircraft_mesh import load_triangles

    real = load_triangles(aircraft)
    if real:
        return real, "source mesh"
    from .aircraft_model import body_faces

    return body_faces(aircraft), "parametric stand-in"


def _aircraft_faces(record, faces, camera):
    """The solid airframe for this frame, back-to-front, each face with
    its lambert term.

    No back-face culling: the wings, tailplane and fin are single-sided
    surfaces, and the mirrored (left) copies come out with reversed
    winding, so culling by normal sign deleted exactly half the
    aircraft. Shading uses |lambert| instead, which is right for a thin
    surface lit from either side and harmless for the fuselage.
    """
    from .aircraft_model import body_to_world, face_normal

    state = record["aircraft"]
    origin = (state["north_m"], state["east_m"], state["alt_m"])
    drawn = []
    for vertices, colour in faces:
        world = [body_to_world(v, state["roll_deg"], state["pitch_deg"],
                               state["heading_deg"], origin)
                 for v in vertices]
        normal = face_normal(world)
        centroid = tuple(sum(v[i] for v in world) / len(world)
                         for i in range(3))
        lambert = abs(sum(n * s for n, s in zip(normal, SUN)))
        drawn.append((math.dist(centroid, camera), world, colour, lambert))
    drawn.sort(key=lambda item: -item[0])
    return drawn


def _shadow_faces(record, faces, ground_alt: float):
    """The airframe flattened onto the ground. Untextured solids float
    without one -- the shadow is what says how high the aircraft is."""
    from .aircraft_model import body_to_world

    state = record["aircraft"]
    origin = (state["north_m"], state["east_m"], state["alt_m"])
    return [[(v[0], v[1], ground_alt)
             for v in (body_to_world(c, state["roll_deg"], state["pitch_deg"],
                                     state["heading_deg"], origin)
                       for c in vertices)]
            for vertices, _ in faces]


def render_previews(manifest: Dict, out_dir, heightfield=None,
                    scene_frame=None,
                    terrain_elevation_m: float = 0.0,
                    max_frames: Optional[int] = None) -> List[Path]:
    """Write one preview PNG per frame record; returns the paths."""
    from PIL import Image, ImageDraw

    from .landmarks import landmark_point

    frames = manifest.get("frames", [])
    if max_frames is not None:
        frames = frames[:max_frames]
    if not frames:
        return []

    track = {}
    for record in manifest.get("frames", []):
        a = record["aircraft"]
        track[record["sample_index"]] = (a["north_m"], a["east_m"],
                                         a["alt_m"])
    track_points = [track[k] for k in sorted(track)]
    centre = (sum(p[0] for p in track_points) / len(track_points),
              sum(p[1] for p in track_points) / len(track_points))

    if heightfield is not None and scene_frame is not None:
        mesh = _terrain_mesh(heightfield, scene_frame)
    else:
        mesh = _flat_mesh(terrain_elevation_m, centre)
    # Precompute each cell's lambert term once: the sun does not move.
    shaded = [(corners, base,
               sum(n * s for n, s in zip(_normal(*corners[:3]), SUN)))
              for corners, base in mesh]

    landmarks = manifest.get("landmarks") or []
    aircraft = str(manifest.get("aircraft") or "B747")
    ground_alt = float(terrain_elevation_m)
    # Once per run: parsing the 747's .ac parts is not per-frame work.
    airframe, airframe_source = airframe_geometry(aircraft)
    written: List[Path] = []
    for record in frames:
        width = max(int(record["width_px"]) // PREVIEW_SCALE, 16)
        height = max(int(record["height_px"]) // PREVIEW_SCALE, 16)
        image = Image.new("RGB", (width, height), SKY_HORIZON)
        draw = ImageDraw.Draw(image)
        _horizon(draw, record, width, height)

        camera = (record["position_north_m"], record["position_east_m"],
                  record["position_alt_m"])

        near = max(float(record.get("near_m", 0.1)), 0.1)
        limit = 40.0 * max(width, height)

        def to_px(point):
            u, v, z = project_point(record, point)
            # Near-plane reject, not just "behind the camera": a vertex a
            # few centimetres in front projects to an enormous pixel and
            # Pillow happily fills the frame with the resulting polygon.
            if z <= near or not math.isfinite(u):
                return None
            x, y = u / PREVIEW_SCALE, v / PREVIEW_SCALE
            if abs(x) > limit or abs(y) > limit:
                return None
            return x, y

        # Painter's algorithm: furthest cell first, so nearer ground
        # covers what is behind it instead of stippling through it.
        visible = []
        for corners, base, lambert in shaded:
            centroid = tuple(sum(c[i] for c in corners) / 4.0
                             for i in range(3))
            depth = math.dist(centroid, camera)
            visible.append((depth, corners, base, lambert))
        visible.sort(key=lambda item: -item[0])
        for depth, corners, base, lambert in visible:
            pixels = [to_px(c) for c in corners]
            if any(p is None for p in pixels):
                continue          # any corner behind the camera: skip
            if all(p[0] < 0 for p in pixels) or all(p[0] > width for p in pixels):
                continue
            if all(p[1] < 0 for p in pixels) or all(p[1] > height for p in pixels):
                continue
            draw.polygon(pixels,
                         fill=_shade(base, lambert,
                                     1.0 - math.exp(-depth / HAZE_SCALE_M)))

        previous = None
        for point in track_points:
            pixel = to_px(point)
            if pixel is not None and previous is not None:
                draw.line([previous, pixel], fill=(90, 170, 255), width=2)
            previous = pixel

        for landmark in landmarks:
            pixel = to_px(landmark_point(landmark))
            if pixel is None:
                continue
            if not (0 <= pixel[0] < width and 0 <= pixel[1] < height):
                continue
            x, y = pixel
            draw.line([(x - 4, y), (x + 4, y)], fill=(255, 120, 120))
            draw.line([(x, y - 4), (x, y + 4)], fill=(255, 120, 120))

        # The aircraft's shadow first: it lands on the ground, so the
        # solid is drawn over it, and the ground is already down.
        for shadow in _shadow_faces(record, airframe, ground_alt):
            pixels = [to_px(v) for v in shadow]
            if any(p is None for p in pixels):
                continue
            draw.polygon(pixels, fill=(58, 66, 52))

        for _, vertices, colour, lambert in _aircraft_faces(
                record, airframe, camera):
            pixels = [to_px(v) for v in vertices]
            if any(p is None for p in pixels):
                continue
            lit = 0.30 + 0.70 * max(0.0, lambert)
            draw.polygon(pixels,
                         fill=tuple(int(min(255, c * lit)) for c in colour))

        caption = (f"{record['camera_id']}  #{record['index']:03d}  "
                   f"t={record['t_s']:.1f}s  {aircraft}  "
                   f"{record['focal_length_mm']:.0f}mm  "
                   f"{int(record['width_px'])}x{int(record['height_px'])}  "
                   f"roll {record['aircraft']['roll_deg']:+.1f} "
                   f"pitch {record['aircraft']['pitch_deg']:+.1f}")
        draw.rectangle([0, 0, width, 30], fill=(12, 16, 24))
        draw.text((6, 4), caption, fill=(230, 230, 230))
        draw.text((6, 16),
                  f"SOLID-SHADED PREVIEW -- no engine, no textures, no "
                  f"materials. Airframe: {airframe_source}. Photographic "
                  f"frames come from the Unreal host on Windows "
                  f"(--render).",
                  fill=(150, 160, 175))

        path = (Path(out_dir) / "previews" / record["camera_id"]
                / f"preview_{record['index']:04d}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        written.append(path)
    return written
