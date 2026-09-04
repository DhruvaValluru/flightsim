"""Geometry previews: what each scheduled frame would see, engine-free.

One PNG per scheduled capture, drawn with numpy + Pillow only
(matplotlib is not a dependency of this project), every element
projected through the frame's OWN recorded pose and intrinsics via
:func:`core.capture.verify.project_point` -- the independent
implementation, so the preview doubles as an eyeball check on the
recorded geometry: if the manifest were wrong, the pictures would point
the wrong way.

What is drawn, and where each number comes from
-----------------------------------------------
* **Terrain** (terrain scenes): the raster sampled on a lattice whose
  stride is the smallest multiple of four raster pixels giving at most
  TERRAIN_GRID samples per axis (1024 px at 30 m: stride 24 px, 720 m,
  43 x 43 samples), each sample joined to its row and column
  neighbour, plus a FINE lattice at a quarter of that stride within
  TERRAIN_NEAR_STEPS coarse steps of the camera's ground point so the
  near ground reads at the scale the aircraft is drawn; distance rings
  DRAPED on the raster (each ring point at the raster's elevation)
  around the camera's ground point. Every segment is clipped at the
  camera's near plane (``near_m``) and to the image, shaded by
  camera-space DEPTH: brightness = 32 + 208 x (1 - ln(z / ref) /
  ln(far_m / ref)) with ref the frame's subject range (camera to the
  recorded aircraft, never below near_m nor above far_m / 10) and far_m
  the record's far plane, so what the frame looks at is bright and the
  far ground dim. Segments are drawn far to near (painter's order) and
  HIDDEN behind nearer ground by a per-column skyline: walking the
  segments near to far, each image column keeps the highest point
  drawn so far and a farther sample that lies below it is behind a
  ridge and not drawn (:func:`skyline_cull`).
* **Ground grid** (flat scenes): the level plane at the spec's terrain
  elevation, two lattices whose origin is snapped to the grid step --
  a fine one whose step is the "nice" number at or above a quarter of
  the camera's height above the plane, and a coarse one at ten times
  that step whose extent is the smaller of ``far_m`` and the distance
  at which the plane sits within two pixels of the horizon (fy x
  height / 2): the grid always reaches the horizon or the far plane,
  whichever the record reaches first. Depth-shaded like the terrain.
  **Distance rings** at DISTANCE_RINGS_M around the camera's EXACT
  ground point (never the snapped lattice origin: a ring labelled
  "10 km" is 10 km from the camera), each labelled.
* **North arrow**: a world-space arrow on the ground, pointing north,
  its world length set so its PROJECTION spans NORTH_ARROW_PX, based
  where the ray through the pixel NORTH_ARROW_DROP_PX below the
  boresight meets the ground (flat: the plane; terrain: the raster,
  marched) -- clear of the aircraft an aimed camera centres -- or,
  when it does not, ahead of the camera / under the aircraft; its "N"
  label placed clear of other labels (a label landing within
  LABEL_CLEARANCE_PX of one already placed is shifted down). Drawn in
  EVERY scene.
* **Compass rose**: image-space, in the bottom-right corner, drawn in
  every scene from the camera's own yaw: the N/E/S/W spokes rotated so
  north sits at screen angle -yaw (clockwise from up), and the
  aircraft's recorded heading as a second needle at heading - yaw,
  both labelled with their numbers.
* **Horizon**: the image of the level plane at infinity for the
  camera's pitch and roll -- directions with zero vertical component,
  projected; for a level camera it is the row ``v = cy``, for pitch p
  it is ``cy + fy tan(p)`` (a camera pitched DOWN sees the horizon
  above its centre), and roll tilts it. Drawn in HORIZON_RGB.
* **Aircraft**: a three-axis body scaled from the manifest's
  ``aircraft_metrics`` (read ONCE from the configured FDM by the
  runner: span from ``metrics/bw-ft``, the longitudinal extent from
  the FDM's stated stations, the vertical extent from
  ``sqrt(metrics/Sv-sqft)``; the source of each is carried beside the
  number and the header prints the caveat that JSBSim states no
  fuselage length) -- nose-to-tail along the recorded heading and
  pitch, wing tips at +/- span/2 with the recorded roll, a fin up from
  the centre, the length x span x height BOX around it, a HEADING TICK
  beyond the nose along the recorded heading, and the flown TRACK: the
  run's telemetry decimated to TRACK_TARGET_HZ when the caller passes
  it (:func:`telemetry_track`), else the manifest's own scheduled
  instants, past solid and future dim split at the frame's t_s, with
  this camera's scheduled instants as dots on the line; the header
  states which. A manifest WITHOUT metrics gets a fixed cross and the
  header says "aircraft_metrics absent: body unscaled" -- never a
  silent guess.
* **Camera**: a boresight cross at ``principal_point_px``, the
  horizontal and vertical field of view (2 atan(sensor / 2 focal))
  printed at the frame edges, and the aircraft-to-camera bearing and
  range in the header.
* **Header**: camera id, frame index and count ("frame index 5 (6 of
  24)": the manifest's 0-based index a verifier greps for AND the
  human count), simulation time, position, look direction (yaw, pitch,
  roll), focal length and fx, the resolution; the aircraft's state;
  the body's dimensions with their sources; the ground (raster name,
  size, resolution and wireframe spacing, or the flat lattice); the
  track's source. Font and line height derive from the image height
  and lines longer than the image are wrapped, so the text fits at any
  size.

Full output resolution by default (``scale=1``: the record's own
``width_px`` x ``height_px``); ``scale=N`` draws at 1/N and the header
says so. Render time is MEASURED per call (``PreviewSet.seconds_per_
frame``) against RENDER_BUDGET_S_PER_FRAME.

Overlays (:func:`render_overlays`): for every frame record whose PNG
exists, the same geometry drawn as a translucent layer over the
rendered frame -- the verification made visible -- under
``overlays/<camera_id>/NNNN.png``, ALWAYS at the frame's own size: a
frame whose size differs from its record is drawn through the
record's intrinsics scaled per axis by the actual ratio (fx, cx by
width; fy, cy by height); the rendered pixels are never resampled.
The header band is no darker than OVERLAY_BAND_ALPHA. Contact sheets
(:func:`contact_sheet`): every preview of a camera as a tile DRAWN FOR
THE TILE from its record (``style="thumbnail"``: the same projection
at the tile's size, no text, the horizon, track and body at
THUMBNAIL_LINE_PX -- never the preview shrunk, which smears its one-
pixel lines and header to nothing), index and time under each, under
``contact_sheets/<camera_id>.png`` -- beside ``previews/``, never
inside it, so ``previews/`` holds exactly one PNG per drawn frame and
a count of it is a count of previews.

These are geometry previews, not renders: no lighting, no meshes, no
claim beyond "this is where the camera pointed".
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .verify import axes_from_euler, axes_from_quat, project_point

#: Default preview scale: 1 = the record's full output resolution.
PREVIEW_SCALE_DEFAULT = 1
#: The render budget the report states and the test grades against.
RENDER_BUDGET_S_PER_FRAME = 0.5
#: Terrain raster sampling per axis for the coarse wireframe (at most).
TERRAIN_GRID = 48
#: The fine terrain lattice: this many coarse steps around the camera's
#: ground point, at TERRAIN_NEAR_DENSITY times the coarse density.
TERRAIN_NEAR_STEPS = 10
TERRAIN_NEAR_DENSITY = 4
#: Distance rings (metres) around the camera's ground point.
DISTANCE_RINGS_M = (500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0)
#: "Nice" grid steps (metres) the flat lattice chooses from.
GRID_STEPS_M = (10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0,
                5000.0, 10000.0)
#: The world-space north arrow's on-screen length at its base's depth.
NORTH_ARROW_PX = 60.0
#: A label landing within this many pixels of another is shifted.
LABEL_CLEARANCE_PX = 20.0
#: The compass rose: radius and its inset from the bottom-right corner.
COMPASS_RADIUS_PX = 40
COMPASS_INSET_PX = (60, 98)
#: The flown track is the telemetry decimated to about this rate.
TRACK_TARGET_HZ = 10.0
#: The overlay's header band never darkens the frame by more than this.
OVERLAY_BAND_ALPHA = 96
#: A farther sample this close (px) to the skyline still counts as seen.
SKYLINE_TOLERANCE_PX = 1.0

BACKGROUND_RGB = (12, 16, 24)
HORIZON_RGB = (240, 230, 200)
TRACK_PAST_RGB = (80, 160, 255)
TRACK_FUTURE_RGB = (50, 80, 120)
BODY_RGB = (255, 200, 60)
BOX_RGB = (150, 120, 40)
HEADING_RGB = (80, 240, 240)
NORTH_RGB = (255, 150, 60)
RING_RGB = (120, 150, 190)
CAMERA_RGB = (255, 255, 255)
TEXT_RGB = (220, 220, 220)
COMPASS_RGB = (170, 170, 170)
NO_METRICS_RGB = (255, 80, 80)
TERRAIN_TINT = (0.55, 0.9, 0.6)
FLAT_TINT = (0.6, 0.7, 0.9)
CONTACT_THUMB_WIDTH_PX = 320
CONTACT_COLUMNS = 6
#: Line width of the horizon, track and body in a contact-sheet tile
#: (drawn for the tile, never a shrunk preview).
THUMBNAIL_LINE_PX = 2


class PreviewSet(list):
    """The written preview paths, plus what the run measured: the
    per-frame render time, the scale, the drawn resolution and the
    per-camera contact sheets."""

    seconds_per_frame: float = 0.0
    scale: int = PREVIEW_SCALE_DEFAULT
    resolution: Optional[Tuple[int, int]] = None
    contact_sheets: Dict[str, Path]
    track_source: str = ""

    def __init__(self, paths=()):
        super().__init__(paths)
        self.contact_sheets = {}


class OverlaySet(list):
    seconds_per_frame: float = 0.0
    sizes: Dict[Path, Tuple[int, int]]

    def __init__(self, paths=()):
        super().__init__(paths)
        self.sizes = {}


def validated_scale(scale) -> int:
    """A preview scale is a positive integer divisor of the resolution;
    anything else is refused by name (preview.scale), never rounded."""
    try:
        value = int(scale)
    except (TypeError, ValueError):
        value = None
    if value is None or value < 1 or float(scale) != float(value):
        raise ValueError(
            f"preview.scale: {scale!r} is not a positive integer; the "
            f"preview draws at 1/N of the record's resolution and never "
            f"rounds a scale")
    return value


def _axis_scale(scale) -> Tuple[float, float]:
    """(sx, sy): record pixels per drawn pixel on each axis. An int or
    float applies to both; a pair is per axis (an overlay over a frame
    whose size differs from its record)."""
    if isinstance(scale, (tuple, list)):
        return float(scale[0]), float(scale[1])
    return float(scale), float(scale)


# -- geometry ------------------------------------------------------------

def _camera_axes(record):
    return axes_from_quat(record["quaternion_wxyz"])


def _to_camera(record, points: np.ndarray, axes) -> np.ndarray:
    """World (north, east, alt) rows -> camera-space (x right, y down,
    z depth) rows, the manifest's documented model."""
    forward, right, up = axes
    d = points - np.array([record["position_north_m"],
                           record["position_east_m"],
                           record["position_alt_m"]], dtype=float)
    x = d @ np.asarray(right, dtype=float)
    y = -(d @ np.asarray(up, dtype=float))
    z = d @ np.asarray(forward, dtype=float)
    return np.stack([x, y, z], axis=1)


def _project_clip(record, a: np.ndarray, b: np.ndarray, scale, axes=None):
    """The clipped segments as (u0, v0, u1, v1, mean depth) rows, the
    two endpoint depths (after the near-plane cut) per row, and the
    input row index each surviving segment came from."""
    empty = (np.zeros((0, 5)), np.zeros(0), np.zeros(0), np.zeros(0, dtype=int))
    if len(a) == 0:
        return empty
    axes = axes or _camera_axes(record)
    sx, sy = _axis_scale(scale)
    near = max(float(record.get("near_m", 0.1)), 1e-3)
    ca = _to_camera(record, np.asarray(a, dtype=float), axes)
    cb = _to_camera(record, np.asarray(b, dtype=float), axes)
    idx = np.arange(len(ca))
    za, zb = ca[:, 2], cb[:, 2]
    keep = (za > near) | (zb > near)
    ca, cb, za, zb, idx = ca[keep], cb[keep], za[keep], zb[keep], idx[keep]
    if len(ca) == 0:
        return empty
    # Cut at the near plane.
    behind_a = za <= near
    if behind_a.any():
        t = (near - za[behind_a]) / (zb[behind_a] - za[behind_a])
        ca[behind_a] = ca[behind_a] + t[:, None] * (cb[behind_a] - ca[behind_a])
    behind_b = zb <= near
    if behind_b.any():
        t = (near - zb[behind_b]) / (za[behind_b] - zb[behind_b])
        cb[behind_b] = cb[behind_b] + t[:, None] * (ca[behind_b] - cb[behind_b])
    cx, cy = record["principal_point_px"]
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    u0 = (cx + fx * ca[:, 0] / ca[:, 2]) / sx
    v0 = (cy + fy * ca[:, 1] / ca[:, 2]) / sy
    u1 = (cx + fx * cb[:, 0] / cb[:, 2]) / sx
    v1 = (cy + fy * cb[:, 1] / cb[:, 2]) / sy
    depth = 0.5 * (ca[:, 2] + cb[:, 2])
    w = float(record["width_px"]) / sx
    h = float(record["height_px"]) / sy
    # Liang-Barsky against [0, w] x [0, h].
    dx, dy = u1 - u0, v1 - v0
    t0 = np.zeros(len(u0))
    t1 = np.ones(len(u0))
    ok = np.ones(len(u0), dtype=bool)
    for p, q in ((-dx, u0), (dx, w - u0), (-dy, v0), (dy, h - v0)):
        parallel = p == 0
        ok &= ~(parallel & (q < 0))
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(parallel, 0.0, q / np.where(parallel, 1.0, p))
        enter = (p < 0)
        t0 = np.where(enter, np.maximum(t0, t), t0)
        leave = (p > 0)
        t1 = np.where(leave, np.minimum(t1, t), t1)
    ok &= t0 <= t1
    out = np.stack([u0 + t0 * dx, v0 + t0 * dy,
                    u0 + t1 * dx, v0 + t1 * dy, depth], axis=1)
    za_cut = ca[:, 2] + t0 * (cb[:, 2] - ca[:, 2])
    zb_cut = ca[:, 2] + t1 * (cb[:, 2] - ca[:, 2])
    return out[ok], za_cut[ok], zb_cut[ok], idx[ok]


def _clip_segments(record, a: np.ndarray, b: np.ndarray, scale,
                   axes=None):
    """Project world segments a->b through the record and return the
    (u0, v0, u1, v1, depth) rows that survive: clipped at the near plane
    in camera space (a segment crossing z = near_m is cut there, one
    wholly behind is dropped) and to the image rectangle in pixels
    (Liang-Barsky), in PREVIEW pixels (record pixels / scale)."""
    return _project_clip(record, a, b, scale, axes)[0]


def subject_range_m(record) -> float:
    """The frame's subject distance: camera to the recorded aircraft."""
    a = record["aircraft"]
    return math.sqrt((a["north_m"] - record["position_north_m"]) ** 2
                     + (a["east_m"] - record["position_east_m"]) ** 2
                     + (a["alt_m"] - record["position_alt_m"]) ** 2)


def depth_brightness(depth, record) -> np.ndarray:
    """240 at or inside the frame's subject range (camera to aircraft,
    never below near_m) falling on a log scale to 32 at the record's
    far plane: near bright, far dim, referenced to what the frame is
    looking at rather than to a 100 km far plane that makes every
    scene "far"."""
    near = max(float(record.get("near_m", 0.1)), 1e-3)
    far = max(float(record.get("far_m", 1e5)), near * 10.0)
    reference = min(max(subject_range_m(record), near), far / 10.0)
    z = np.maximum(np.asarray(depth, dtype=float), reference)
    frac = np.log(z / reference) / math.log(far / reference)
    return np.clip(32.0 + 208.0 * (1.0 - frac), 32.0, 240.0)


def _draw_segments(draw, segments: np.ndarray, colour_of, width: int = 1):
    """Draw in painter's order: far first, so where two segments cross
    the nearer one's colour is the one left on the pixel."""
    segments = np.asarray(segments, dtype=float)
    if len(segments) == 0:
        return
    order = np.argsort(-segments[:, 4], kind="stable")
    for u0, v0, u1, v1, depth in segments[order]:
        draw.line([(float(u0), float(v0)), (float(u1), float(v1))],
                  fill=colour_of(depth), width=width)


def skyline_cull(segments: np.ndarray, za: np.ndarray, zb: np.ndarray,
                 width: int, tolerance_px: float = SKYLINE_TOLERANCE_PX):
    """Hide ground behind nearer ground. ``segments`` are clipped
    (u0, v0, u1, v1, depth) rows with their endpoint depths ``za``,
    ``zb``. Every segment is rasterised one sample per pixel along its
    longer axis; samples are ordered near to far per image column and a
    sample that lies BELOW (larger v than) the highest nearer sample in
    its column, by more than ``tolerance_px``, is behind a ridge. Returns
    ``(visible, source, skyline)``: the visible sub-segments as
    (u0, v0, u1, v1, depth) rows, the index of the input segment each
    came from, and the per-column skyline (min v seen; inf where
    nothing was drawn)."""
    segments = np.asarray(segments, dtype=float)
    n = len(segments)
    skyline = np.full(int(width) + 1, np.inf)
    if n == 0:
        return np.zeros((0, 5)), np.zeros(0, dtype=int), skyline
    u0, v0, u1, v1 = (segments[:, k] for k in range(4))
    counts = np.maximum(np.abs(u1 - u0), np.abs(v1 - v0)).astype(int) + 2
    total = int(counts.sum())
    seg = np.repeat(np.arange(n), counts)
    offsets = np.cumsum(counts) - counts
    k = np.arange(total) - np.repeat(offsets, counts)
    t = k / np.maximum(np.repeat(counts, counts) - 1, 1)
    u = np.repeat(u0, counts) + t * np.repeat(u1 - u0, counts)
    v = np.repeat(v0, counts) + t * np.repeat(v1 - v0, counts)
    z = np.repeat(za, counts) + t * np.repeat(zb - za, counts)
    col = np.clip(np.rint(u).astype(int), 0, int(width))
    # Per column, near to far: the running minimum v BEFORE each sample.
    order = np.lexsort((z, col))
    col_s, v_s = col[order], v[order]
    big = 1e9
    shifted = v_s - col_s * big
    running = np.minimum.accumulate(shifted)
    prev = np.empty_like(running)
    prev[0] = np.inf
    prev[1:] = running[:-1]
    first = np.ones(len(col_s), dtype=bool)
    first[1:] = col_s[1:] != col_s[:-1]
    prev[first] = np.inf
    prev_v = prev + col_s * big
    visible_s = v_s <= prev_v + tolerance_px
    visible = np.empty(total, dtype=bool)
    visible[order] = visible_s
    np.minimum.at(skyline, col, v)
    # Visible runs along each segment become sub-segments.
    run_start = visible & np.concatenate(
        [[True], (~visible[:-1]) | (seg[1:] != seg[:-1])])
    run_end = visible & np.concatenate(
        [(~visible[1:]) | (seg[1:] != seg[:-1]), [True]])
    starts = np.flatnonzero(run_start)
    ends = np.flatnonzero(run_end)
    if len(starts) == 0:
        return np.zeros((0, 5)), np.zeros(0, dtype=int), skyline
    out = np.stack([u[starts], v[starts], u[ends], v[ends],
                    0.5 * (z[starts] + z[ends])], axis=1)
    return out, seg[starts], skyline


def _shaded(record, tint=TERRAIN_TINT):
    def colour(depth):
        b = float(depth_brightness(depth, record))
        return tuple(int(b * t) for t in tint)
    return colour


def _solid(rgb):
    return lambda depth: rgb


def horizon_points(record, scale=1.0, samples: int = 179):
    """The horizon as projected points (preview pixels), the image of
    the level directions {d : d_up = 0} in front of the camera: the
    camera's horizontal forward rotated through -89..89 deg. Empty when
    the camera looks straight up or down."""
    forward, right, up = _camera_axes(record)
    fn, fe = forward[0], forward[1]
    norm = math.hypot(fn, fe)
    if norm < 1e-9:
        return []
    h = (fn / norm, fe / norm, 0.0)
    p = (-h[1], h[0], 0.0)
    cx, cy = record["principal_point_px"]
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    sx, sy = _axis_scale(scale)
    points = []
    for k in range(samples):
        theta = math.radians(-89.0 + 178.0 * k / (samples - 1))
        d = (h[0] * math.cos(theta) + p[0] * math.sin(theta),
             h[1] * math.cos(theta) + p[1] * math.sin(theta), 0.0)
        z = sum(a * b for a, b in zip(forward, d))
        if z <= 1e-9:
            continue
        x = sum(a * b for a, b in zip(right, d))
        y = -sum(a * b for a, b in zip(up, d))
        points.append(((cx + fx * x / z) / sx, (cy + fy * y / z) / sy))
    return points


def horizon_segment(record, scale=1.0):
    """The horizon clipped to the image: ((u0, v0), (u1, v1)) in preview
    pixels, or None when no level direction lies in front of the camera
    inside the frame."""
    points = horizon_points(record, scale)
    if len(points) < 2:
        return None
    sx, sy = _axis_scale(scale)
    w = float(record["width_px"]) / sx
    h = float(record["height_px"]) / sy
    best = None
    for (u0, v0), (u1, v1) in zip(points, points[1:]):
        seg = _clip_2d(u0, v0, u1, v1, w, h)
        if seg is None:
            continue
        best = (seg[0], seg[1]) if best is None else (best[0], seg[1])
    return best


def _clip_2d(u0, v0, u1, v1, w, h):
    dx, dy = u1 - u0, v1 - v0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, u0), (dx, w - u0), (-dy, v0), (dy, h - v0)):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    if t0 > t1:
        return None
    return ((u0 + t0 * dx, v0 + t0 * dy), (u0 + t1 * dx, v0 + t1 * dy))


def field_of_view_deg(record) -> Tuple[float, float]:
    """(horizontal, vertical) FOV: 2 atan(sensor / 2 focal)."""
    f = float(record["focal_length_mm"])
    return (math.degrees(2.0 * math.atan(float(record["sensor_width_mm"]) / (2.0 * f))),
            math.degrees(2.0 * math.atan(float(record["sensor_height_mm"]) / (2.0 * f))))


# -- ground: terrain wireframe or flat lattice --------------------------

def terrain_stride_px(size_px: int, grid: int = TERRAIN_GRID) -> int:
    """The coarse lattice's raster stride: the smallest multiple of
    TERRAIN_NEAR_DENSITY pixels giving at most ``grid`` samples per
    axis (a stride under the density is left as it is, the fine lattice
    then being the raster itself)."""
    raw = (size_px - 1) / max(grid - 1, 1)
    if raw <= 1.0:
        return 1
    d = TERRAIN_NEAR_DENSITY
    if raw < d:
        return int(math.ceil(raw))
    return int(d * math.ceil(raw / d))


def _lattice_segments(pts: np.ndarray):
    """Join every sample of a (rows, cols, 3) lattice to its row and
    column neighbour."""
    along_rows = (pts[:, :-1, :].reshape(-1, 3), pts[:, 1:, :].reshape(-1, 3))
    along_cols = (pts[:-1, :, :].reshape(-1, 3), pts[1:, :, :].reshape(-1, 3))
    return (np.concatenate([along_rows[0], along_cols[0]]),
            np.concatenate([along_rows[1], along_cols[1]]))


def _raster_lattice(heightfield, frame, rows: np.ndarray, cols: np.ndarray,
                    z: Optional[np.ndarray] = None):
    if z is None:
        z = heightfield.elevations()
    g = heightfield.georeference
    east = (g.origin_x_m + cols * g.pixel_size_m) - frame.origin_x_m
    north = (g.origin_y_m - rows * g.pixel_size_m) - frame.origin_y_m
    alt = z[np.ix_(rows, cols)].astype(float)
    return np.stack([np.repeat(north[:, None], len(cols), axis=1),
                     np.repeat(east[None, :], len(rows), axis=0), alt], axis=2)


def terrain_wireframe(heightfield, frame, grid: int = TERRAIN_GRID):
    """(a, b) arrays of world segments: the raster sampled every
    :func:`terrain_stride_px` pixels (at most ``grid`` samples per
    axis) in the scene frame's local metres, each sample joined to its
    row and column neighbour."""
    stride = max(terrain_stride_px(heightfield.height, grid),
                 terrain_stride_px(heightfield.width, grid))
    rows = np.arange(0, heightfield.height, stride)
    cols = np.arange(0, heightfield.width, stride)
    return _lattice_segments(_raster_lattice(heightfield, frame, rows, cols))


def terrain_plan(heightfield, frame, grid: int = TERRAIN_GRID) -> Dict:
    """What the wireframe is, for the header: the raster's name, size
    and resolution, the coarse stride and spacing, the fine stride and
    the radius it is drawn within."""
    stride = max(terrain_stride_px(heightfield.height, grid),
                 terrain_stride_px(heightfield.width, grid))
    px = float(heightfield.georeference.pixel_size_m)
    fine = max(1, stride // TERRAIN_NEAR_DENSITY)
    return {"name": heightfield.name, "width_px": int(heightfield.width),
            "height_px": int(heightfield.height), "pixel_size_m": px,
            "stride_px": int(stride), "spacing_m": stride * px,
            "samples": (len(range(0, heightfield.height, stride)),
                        len(range(0, heightfield.width, stride))),
            "fine_stride_px": int(fine), "fine_spacing_m": fine * px,
            "near_radius_m": TERRAIN_NEAR_STEPS * stride * px}


def terrain_near_wireframe(heightfield, frame, record, plan: Dict):
    """The fine lattice: raster rows and columns every
    ``plan['fine_stride_px']`` within ``plan['near_radius_m']`` of the
    camera's ground point (segments whose midpoint lies outside the
    radius, or that coincide with the coarse lattice, are dropped)."""
    g = heightfield.georeference
    x, y = frame.to_projected(float(record["position_north_m"]),
                              float(record["position_east_m"]))
    col_c = (x - g.origin_x_m) / g.pixel_size_m
    row_c = (g.origin_y_m - y) / g.pixel_size_m
    fine, stride = plan["fine_stride_px"], plan["stride_px"]
    if fine >= stride:
        return np.zeros((0, 3)), np.zeros((0, 3))
    r_px = plan["near_radius_m"] / g.pixel_size_m
    lo_r = max(0, int(math.floor((row_c - r_px) / fine)) * fine)
    hi_r = min(heightfield.height - 1, int(math.ceil((row_c + r_px) / fine)) * fine)
    lo_c = max(0, int(math.floor((col_c - r_px) / fine)) * fine)
    hi_c = min(heightfield.width - 1, int(math.ceil((col_c + r_px) / fine)) * fine)
    if hi_r <= lo_r or hi_c <= lo_c:
        return np.zeros((0, 3)), np.zeros((0, 3))
    rows = np.arange(lo_r, hi_r + 1, fine)
    cols = np.arange(lo_c, hi_c + 1, fine)
    pts = _raster_lattice(heightfield, frame, rows, cols, plan.get("elevations"))
    n_r, n_c = len(rows), len(cols)
    # Row-wise segments (along east) and column-wise (along north),
    # each tagged with whether it lies on a coarse line.
    a_rows = pts[:, :-1, :].reshape(-1, 3); b_rows = pts[:, 1:, :].reshape(-1, 3)
    on_coarse_rows = np.repeat(rows % stride == 0, n_c - 1)
    a_cols = pts[:-1, :, :].reshape(-1, 3); b_cols = pts[1:, :, :].reshape(-1, 3)
    on_coarse_cols = np.tile(cols % stride == 0, n_r - 1)
    a = np.concatenate([a_rows, a_cols]); b = np.concatenate([b_rows, b_cols])
    coarse = np.concatenate([on_coarse_rows, on_coarse_cols])
    mid = 0.5 * (a + b)
    cam_n, cam_e = float(record["position_north_m"]), float(record["position_east_m"])
    inside = np.hypot(mid[:, 0] - cam_n, mid[:, 1] - cam_e) <= plan["near_radius_m"]
    keep = inside & ~coarse
    return a[keep], b[keep]


def raster_elevations(heightfield, frame, north_m, east_m) -> np.ndarray:
    """The raster's elevation at local (north, east) points, bilinear
    exactly as ``Heightfield.elevation_at`` (the same weights on the
    same four samples), vectorised; NaN off the raster."""
    north = np.asarray(north_m, dtype=float)
    east = np.asarray(east_m, dtype=float)
    g = heightfield.georeference
    x = frame.origin_x_m + east
    y = frame.origin_y_m + north
    col = (x - g.origin_x_m) / g.pixel_size_m
    row = (g.origin_y_m - y) / g.pixel_size_m
    inside = ((col >= 0.0) & (col <= heightfield.width - 1)
              & (row >= 0.0) & (row <= heightfield.height - 1))
    col = np.clip(col, 0.0, heightfield.width - 1.0)
    row = np.clip(row, 0.0, heightfield.height - 1.0)
    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    c1 = np.minimum(c0 + 1, heightfield.width - 1)
    r1 = np.minimum(r0 + 1, heightfield.height - 1)
    fc = col - c0
    fr = row - r0
    smp = heightfield.samples
    top = smp[r0, c0] * (1.0 - fc) + smp[r0, c1] * fc
    bottom = smp[r1, c0] * (1.0 - fc) + smp[r1, c1] * fc
    z = heightfield.offset_m + (top * (1.0 - fr) + bottom * fr) * heightfield.scale_m
    return np.where(inside, z, np.nan)


def _terrain_elevation(heightfield, frame):
    def elevation(north_m: float, east_m: float) -> Optional[float]:
        z = float(raster_elevations(heightfield, frame, north_m, east_m))
        return None if math.isnan(z) else z
    return elevation


class Ground:
    """What the ground is for this run: ``kind`` "terrain" (the coarse
    wireframe segments, the heightfield and frame for the fine lattice,
    draped rings and elevation queries, the plan for the header) or
    "flat" (the plane at the spec's terrain elevation)."""

    def __init__(self, kind: str, segments=None, heightfield=None,
                 frame=None, plan: Optional[Dict] = None):
        self.kind = kind
        self.segments = segments
        self.heightfield = heightfield
        self.frame = frame
        self.plan = plan
        if plan is not None and heightfield is not None:
            # The raster in metres, converted once for every frame's
            # fine lattice (never re-read per frame).
            plan.setdefault("elevations", heightfield.elevations())
        self.elevation = (_terrain_elevation(heightfield, frame)
                          if heightfield is not None and frame is not None
                          else None)

    @classmethod
    def coerce(cls, ground) -> "Ground":
        if isinstance(ground, cls):
            return ground
        kind, segments = ground
        return cls(kind, segments)


def _nice_step(value_m: float) -> float:
    for step in GRID_STEPS_M:
        if step >= value_m:
            return step
    return GRID_STEPS_M[-1]


def flat_ground_plan(record, terrain_elevation_m: float) -> Optional[Dict]:
    """The flat lattice derived from the camera: step, extent, the
    lattice origin (the camera's ground point SNAPPED to the step) and
    the ring centre (the camera's EXACT ground point), all in metres
    on the plane at ``terrain_elevation_m``. None when the camera is at
    or below the plane."""
    agl = float(record["position_alt_m"]) - float(terrain_elevation_m)
    if agl <= 0.0:
        return None
    step = _nice_step(agl / 4.0)
    fy = float(record["fy_px"])
    far = float(record.get("far_m", 1e5))
    extent = min(far, max(fy * agl / 2.0, 20.0 * step))
    cam_n = float(record["position_north_m"])
    cam_e = float(record["position_east_m"])
    centre_n = round(cam_n / step) * step
    centre_e = round(cam_e / step) * step
    return {"step_m": step, "coarse_step_m": 10.0 * step,
            "fine_extent_m": 10.0 * step, "extent_m": extent,
            "centre_north_m": centre_n, "centre_east_m": centre_e,
            "camera_north_m": cam_n, "camera_east_m": cam_e,
            "agl_m": agl, "alt_m": float(terrain_elevation_m),
            "rings_m": [r for r in DISTANCE_RINGS_M if r <= extent]}


def _lattice(cn, ce, alt, step, extent):
    k = np.arange(-extent, extent + step * 0.5, step)
    a, b = [], []
    for offset in k:
        a.append((cn + offset, ce - extent, alt)); b.append((cn + offset, ce + extent, alt))
        a.append((cn - extent, ce + offset, alt)); b.append((cn + extent, ce + offset, alt))
    return np.array(a, dtype=float), np.array(b, dtype=float)


def flat_ground_segments(plan: Dict):
    cn, ce, alt = plan["centre_north_m"], plan["centre_east_m"], plan["alt_m"]
    fine = _lattice(cn, ce, alt, plan["step_m"], plan["fine_extent_m"])
    coarse = _lattice(cn, ce, alt, plan["coarse_step_m"], plan["extent_m"])
    return (np.concatenate([fine[0], coarse[0]]),
            np.concatenate([fine[1], coarse[1]]))


def ring_points(plan: Dict, radius_m: float, samples: int = 72) -> np.ndarray:
    """``samples + 1`` points (closed) of the ring of ``radius_m`` around
    the camera's exact ground point, on the flat plane."""
    cn, ce, alt = (float(plan["camera_north_m"]), float(plan["camera_east_m"]),
                   plan["alt_m"])
    theta = np.linspace(0.0, 2.0 * math.pi, samples + 1)
    return np.stack([cn + radius_m * np.cos(theta), ce + radius_m * np.sin(theta),
                     np.full(samples + 1, alt)], axis=1)


def ring_segments(plan: Dict, radius_m: float, samples: int = 72):
    pts = ring_points(plan, radius_m, samples)
    return pts[:-1], pts[1:]


def terrain_rings(record, ground: Ground, far_m: float, samples: int = 144):
    """Distance rings DRAPED on the raster around the camera's ground
    point: every ring point takes the raster's elevation there; a
    segment with an endpoint off the raster is dropped. Returns
    ``(a, b, radii)`` with the ring radius per segment."""
    cam_n, cam_e = float(record["position_north_m"]), float(record["position_east_m"])
    a_all, b_all, r_all = [], [], []
    theta = np.linspace(0.0, 2.0 * math.pi, samples + 1)
    for radius in DISTANCE_RINGS_M:
        if radius > far_m:
            continue
        n = cam_n + radius * np.cos(theta)
        e = cam_e + radius * np.sin(theta)
        alt = raster_elevations(ground.heightfield, ground.frame, n, e)
        pts = np.stack([n, e, alt], axis=1)
        ok = ~np.isnan(alt[:-1]) & ~np.isnan(alt[1:])
        if ok.any():
            a_all.append(pts[:-1][ok]); b_all.append(pts[1:][ok])
            r_all.append(np.full(int(ok.sum()), radius))
    if not a_all:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0)
    return np.concatenate(a_all), np.concatenate(b_all), np.concatenate(r_all)


def _ring_label(text_m: float) -> str:
    return f"{text_m / 1000.0:g} km" if text_m >= 1000.0 else f"{text_m:g} m"


#: The arrow's ray passes this many pixels BELOW the boresight, so its
#: base sits clear of the aircraft an aimed camera keeps at its centre.
NORTH_ARROW_DROP_PX = 90.0


def arrow_ray(record, axes=None) -> np.ndarray:
    """The unit world direction through the pixel NORTH_ARROW_DROP_PX
    below the principal point (the boresight itself would put the
    arrow on the aircraft an aimed camera centres)."""
    forward, right, up = (np.asarray(v, dtype=float) for v in (axes or _camera_axes(record)))
    d = forward - up * (NORTH_ARROW_DROP_PX / float(record["fy_px"]))
    return d / np.linalg.norm(d)


def north_arrow_base(record, plan: Dict):
    """Where the north arrow sits on the flat plane: where the arrow
    ray (:func:`arrow_ray`) meets the plane, when it does within the
    lattice, else three fine steps ahead of the camera's ground
    point."""
    ray = arrow_ray(record)
    forward, _, _ = _camera_axes(record)
    cam = (float(record["position_north_m"]), float(record["position_east_m"]))
    if ray[2] < -1e-6:
        t = plan["agl_m"] / -ray[2]
        if t <= plan["extent_m"]:
            return (cam[0] + ray[0] * t, cam[1] + ray[1] * t, plan["alt_m"])
    norm = math.hypot(forward[0], forward[1]) or 1.0
    ahead = 3.0 * plan["step_m"]
    return (cam[0] + forward[0] / norm * ahead, cam[1] + forward[1] / norm * ahead,
            plan["alt_m"])


def terrain_arrow_base(record, ground: Ground):
    """Where the north arrow sits on the terrain: the arrow ray
    (:func:`arrow_ray`) marched along the raster (steps of two raster
    pixels, to the far plane) until it passes below the surface; when
    it never does, the ground under the recorded aircraft; None when
    neither lies on the raster."""
    ray = arrow_ray(record)
    cam = np.array([record["position_north_m"], record["position_east_m"],
                    record["position_alt_m"]], dtype=float)
    step = 2.0 * float(ground.heightfield.georeference.pixel_size_m)
    far = float(record.get("far_m", 1e5))
    t = np.arange(step, far + step * 0.5, step)
    p = cam[None, :] + ray[None, :] * t[:, None]
    z = raster_elevations(ground.heightfield, ground.frame, p[:, 0], p[:, 1])
    off = np.isnan(z)
    stop = int(np.argmax(off)) if off.any() else len(t)
    below = np.flatnonzero(p[:stop, 2] <= z[:stop])
    if len(below):
        k = int(below[0])
        if k == 0:
            return (float(p[0, 0]), float(p[0, 1]), float(z[0]))
        # The crossing between the last sample above and the first
        # below: bisected on the raster (the surface is not linear over
        # a march step), to a twentieth of a raster pixel.
        lo, hi = t[k - 1], t[k]
        for _ in range(int(math.ceil(math.log2(step / (0.05 * step / 2.0))))):
            mid = 0.5 * (lo + hi)
            q = cam + ray * mid
            zq = float(raster_elevations(ground.heightfield, ground.frame, q[0], q[1]))
            if q[2] <= zq:
                hi = mid
            else:
                lo = mid
        hit = cam + ray * hi
        zh = float(raster_elevations(ground.heightfield, ground.frame, hit[0], hit[1]))
        return (float(hit[0]), float(hit[1]), zh)
    a = record["aircraft"]
    z = ground.elevation(float(a["north_m"]), float(a["east_m"]))
    if z is None:
        return None
    return (float(a["north_m"]), float(a["east_m"]), float(z))


#: The arrow never exceeds this fraction of its base's depth, however
#: foreshortened north is on screen there.
NORTH_ARROW_MAX_DEPTH_FRACTION = 0.3


def north_arrow_points(record, base, axes=None) -> Optional[Dict]:
    """The world-space arrow from ``base`` pointing north, its world
    length chosen so its PROJECTION spans NORTH_ARROW_PX on screen
    (the screen length of one metre of north at the base, measured by
    projecting base + 1 m north; capped at NORTH_ARROW_MAX_DEPTH_
    FRACTION of the base's depth when north is foreshortened to
    nothing): tip and the two head strokes, and the resulting screen
    length."""
    axes = axes or _camera_axes(record)
    u, v, z = project_point(record, base, axes)
    if not (z > 0):
        return None
    cap = NORTH_ARROW_MAX_DEPTH_FRACTION * z
    length = cap

    def screen(length_m):
        ut, vt, zt = project_point(record, (base[0] + length_m, base[1], base[2]), axes)
        return math.hypot(ut - u, vt - v) if zt > 0 else 0.0

    # The projection is not linear in the world length (the tip lies at
    # another depth): three secant steps from the 1 m rate settle it.
    per_metre = screen(1.0)
    if per_metre > 1e-12:
        length = min(NORTH_ARROW_PX / per_metre, cap)
        for _ in range(3):
            got = screen(length)
            if got <= 1e-9 or abs(got - NORTH_ARROW_PX) < 0.01 or length >= cap:
                break
            length = min(length * NORTH_ARROW_PX / got, cap)
    tip = (base[0] + length, base[1], base[2])
    head_l = (tip[0] - 0.25 * length, tip[1] - 0.15 * length, tip[2])
    head_r = (tip[0] - 0.25 * length, tip[1] + 0.15 * length, tip[2])
    ut, vt, zt = project_point(record, tip, axes)
    return {"base": tuple(base), "tip": tip, "head_l": head_l,
            "head_r": head_r, "length_m": length, "depth_m": z,
            "screen_px": math.hypot(ut - u, vt - v) if zt > 0 else None}


# -- the compass rose ---------------------------------------------------

def compass_rose(record, w: int, h: int) -> Dict:
    """Image-space compass in the bottom-right corner: north at screen
    angle -yaw (clockwise from up, so a camera yawed 90 deg east has
    north to its left), east/south/west 90 deg apart, and the
    aircraft's heading needle at heading - yaw. Returns the centre,
    radius, and each spoke's angle and tip pixel."""
    yaw = float(record["yaw_deg"])
    heading = float(record["aircraft"]["heading_deg"])
    r = COMPASS_RADIUS_PX
    cx, cy = w - COMPASS_INSET_PX[0], h - COMPASS_INSET_PX[1]

    def tip(angle_deg, radius):
        a = math.radians(angle_deg)
        return (cx + radius * math.sin(a), cy - radius * math.cos(a))

    spokes = {}
    for name, offset in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
        angle = (offset - yaw) % 360.0
        spokes[name] = {"angle_deg": angle, "tip": tip(angle, r)}
    needle = (heading - yaw) % 360.0
    return {"centre": (cx, cy), "radius": r, "spokes": spokes,
            "north_deg": spokes["N"]["angle_deg"],
            "heading_needle_deg": needle, "heading_tip": tip(needle, r - 6),
            "yaw_deg": yaw, "heading_deg": heading}


# -- the aircraft ----------------------------------------------------------

def aircraft_body_points(record, metrics: Dict) -> Dict[str, Tuple[float, float, float]]:
    """World points of the scaled three-axis body and its box, from the
    record's aircraft state and the manifest's metrics."""
    a = record["aircraft"]
    P = np.array([a["north_m"], a["east_m"], a["alt_m"]], dtype=float)
    f, r, u = (np.asarray(v, dtype=float) for v in axes_from_euler(
        a["roll_deg"], a["pitch_deg"], a["heading_deg"]))
    L = float(metrics["length_m"]); S = float(metrics["span_m"]); H = float(metrics["height_m"])
    hdg = math.radians(float(a["heading_deg"]))
    hdir = np.array([math.cos(hdg), math.sin(hdg), 0.0])
    pts = {
        "centre": P, "nose": P + f * L / 2, "tail": P - f * L / 2,
        "left_tip": P - r * S / 2, "right_tip": P + r * S / 2,
        "fin_top": P + u * H, "heading_tick": P + f * L / 2 + hdir * 0.3 * L,
    }
    for i, sf in enumerate((-1, 1)):
        for j, sr in enumerate((-1, 1)):
            for k, su in enumerate((-1, 1)):
                pts[f"box{i}{j}{k}"] = P + f * sf * L / 2 + r * sr * S / 2 + u * su * H / 2
    return {k: tuple(float(x) for x in v) for k, v in pts.items()}


BOX_EDGES = tuple((f"box{a}", f"box{b}") for a, b in (
    ("000", "001"), ("010", "011"), ("100", "101"), ("110", "111"),
    ("000", "010"), ("001", "011"), ("100", "110"), ("101", "111"),
    ("000", "100"), ("001", "101"), ("010", "110"), ("011", "111")))


# -- the track ---------------------------------------------------------------

def _track(manifest: Dict):
    """The aircraft's track from the manifest alone: one point per
    recorded instant (the manifest's own per-frame aircraft states,
    deduplicated) as (north, east, alt, sample_index, t_s)."""
    track = {}
    for record in manifest.get("frames", []):
        a = record["aircraft"]
        track[record["sample_index"]] = (a["north_m"], a["east_m"], a["alt_m"],
                                         record["sample_index"], float(record["t_s"]))
    return [track[k] for k in sorted(track)]


def telemetry_track(columns: Dict[str, Sequence[float]], frame,
                    target_hz: float = TRACK_TARGET_HZ):
    """The FLOWN track: the recorder's telemetry (``t``, ``lat_deg``,
    ``lon_deg``, ``altitude_m``) in the scene frame, decimated by the
    integer stride that brings its rate to at or below ``target_hz``
    (never interpolated), as (north, east, alt, sample_index, t_s)
    rows plus the words for the header."""
    t = [float(v) for v in columns["t"]]
    n = len(t)
    if n < 2:
        raise ValueError("telemetry_track: fewer than two telemetry samples")
    # The recorder's clock: its median step (the first sample sits one
    # fixed step in and the last on the run's end, so the mean lies).
    interval = float(np.median(np.diff(t)))
    rate = 1.0 / interval if interval > 0 else float("inf")
    stride = max(1, int(math.ceil(rate / target_hz - 1e-9)))
    indices = list(range(0, n, stride))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    points = []
    for i in indices:
        north, east = frame.to_local(float(columns["lat_deg"][i]),
                                     float(columns["lon_deg"][i]))
        points.append((north, east, float(columns["altitude_m"][i]), i, t[i]))
    decimated = rate / stride
    if stride == 1:
        words = f"track: telemetry {rate:g} Hz ({len(points)} points, no decimation)"
    else:
        words = (f"track: telemetry {rate:g} Hz decimated to {decimated:g} Hz "
                 f"({len(points)} points)")
    return points, words


def _track_points(manifest: Dict, telemetry, scene_frame):
    """The track for the run and its header words: the telemetry when
    the caller passed it (the frame rebuilt from the manifest's own
    provenance when no scene frame was given), else the manifest's
    scheduled instants, in those words."""
    if telemetry is not None:
        frame = scene_frame
        if frame is None:
            from .poses import SceneFrame

            p = manifest["frame"]
            frame = SceneFrame(p["crs"], p["origin_lat_deg"], p["origin_lon_deg"],
                               bool(p.get("declared_on_card", True)))
        return telemetry_track(telemetry, frame)
    return _track(manifest), "track: scheduled instants only (no telemetry passed)"


# -- header ----------------------------------------------------------------

def _camera_block(manifest: Dict, camera_id: str) -> Dict:
    for block in manifest.get("cameras", []) or []:
        if block.get("camera_id") == camera_id:
            return block
    return {}


def frame_words(index: int, count) -> str:
    """"frame index 5 (6 of 24)": the manifest's 0-based index a
    verifier greps for, and the human count."""
    return f"frame index {index} ({int(index) + 1} of {count})"


def body_words(metrics: Optional[Dict]) -> str:
    """The body line: each dimension with its source, and the length's
    caveat carried in the picture, not only in the manifest."""
    if not metrics:
        return "aircraft_metrics absent: body unscaled (cross marker)"
    length_label = metrics.get("length_label") or metrics.get("length_source", "?")
    caveat = metrics.get("length_caveat")
    length = (f"length >= {float(metrics['length_m']):.1f} m ({length_label}; {caveat})"
              if caveat else
              f"length {float(metrics['length_m']):.1f} m ({length_label})")
    height_label = metrics.get("height_label") or metrics.get("height_source", "?")
    return (f"body span {float(metrics['span_m']):.1f} m "
            f"({metrics.get('span_source', '?')}), {length}, "
            f"fin {float(metrics['height_m']):.1f} m ({height_label}) [FDM metrics]")


def ground_words(ground: Ground, plan: Optional[Dict],
                 terrain_elevation_m: float) -> str:
    if ground.kind == "terrain":
        tp = ground.plan
        if not tp:
            return "terrain: raster wireframe (metadata not passed)"
        return (f"terrain {tp['name']} {tp['width_px']}x{tp['height_px']} @ "
                f"{tp['pixel_size_m']:g} m, wireframe {tp['samples'][0]}x"
                f"{tp['samples'][1]} ({tp['spacing_m']:g} m) + {tp['fine_spacing_m']:g} m "
                f"within {tp['near_radius_m'] / 1000.0:g} km of the camera; rings on "
                f"the terrain")
    if plan is None:
        return (f"ground: flat plane at {terrain_elevation_m:g} m (camera at or "
                f"below it: no lattice)")
    return (f"ground: flat plane at {plan['alt_m']:g} m, lattice {plan['step_m']:g} m / "
            f"{plan['coarse_step_m']:g} m to {plan['extent_m'] / 1000.0:g} km; rings "
            f"centred on the camera's ground point")


def header_lines(record: Dict, manifest: Dict, scale: int = 1,
                 tag: str = "geometry preview, not a render",
                 ground: Optional[Ground] = None, plan: Optional[Dict] = None,
                 terrain_elevation_m: float = 0.0,
                 track_words: Optional[str] = None) -> List[str]:
    """The header text, line by line, every number from the record."""
    block = _camera_block(manifest, record["camera_id"])
    count = block.get("capture_count")
    if count is None:
        count = sum(1 for r in manifest.get("frames", [])
                    if r["camera_id"] == record["camera_id"])
    a = record["aircraft"]
    hfov, vfov = field_of_view_deg(record)
    dn = a["north_m"] - record["position_north_m"]
    de = a["east_m"] - record["position_east_m"]
    dz = a["alt_m"] - record["position_alt_m"]
    rng = math.sqrt(dn * dn + de * de + dz * dz)
    bearing = math.degrees(math.atan2(-de, -dn)) % 360.0
    metrics = manifest.get("aircraft_metrics")
    scale_note = "" if scale == 1 else f", 1/{scale} scale"
    lines = [
        f"{record['camera_id']}  {frame_words(record['index'], count)}  "
        f"t={record['t_s']:.3f} s  ({tag}{scale_note})",
        f"pos N {record['position_north_m']:+.1f} E "
        f"{record['position_east_m']:+.1f} alt {record['position_alt_m']:.1f} m  "
        f"look yaw {record['yaw_deg']:.1f} pitch {record['pitch_deg']:.1f} "
        f"roll {record['roll_deg']:.1f} deg  f={record['focal_length_mm']:g} mm "
        f"(fx {record['fx_px']:.0f} px)  {int(record['width_px'])}x"
        f"{int(record['height_px'])}  FOV {hfov:.1f}x{vfov:.1f} deg",
        f"aircraft N {a['north_m']:+.1f} E {a['east_m']:+.1f} alt "
        f"{a['alt_m']:.1f} m  hdg {a['heading_deg']:.1f} pitch "
        f"{a['pitch_deg']:.1f} roll {a['roll_deg']:.1f} deg  "
        f"aircraft->camera bearing {bearing:.1f} deg range {rng:.1f} m",
        body_words(metrics),
    ]
    if ground is not None:
        lines.append(ground_words(ground, plan, terrain_elevation_m))
    if track_words:
        lines.append(track_words)
    return lines


def _font(size_px: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=max(8, int(size_px)))
    except TypeError:                          # Pillow < 10.1
        return ImageFont.load_default()


def header_font_px(height_px: int) -> int:
    """The header's font size from the image height: 15 px at 720,
    8 at 360, 22 at 1080 -- so the text fits the frame it is on."""
    return int(min(24, max(8, round(height_px / 48.0))))


def _text_width(draw, text: str, font) -> float:
    try:
        return float(draw.textlength(text, font=font))
    except AttributeError:                     # Pillow < 8
        return float(draw.textsize(text, font=font)[0])


def wrap_lines(draw, lines: Sequence[str], font, max_width: float) -> List[str]:
    """Break every line wider than ``max_width`` at its double-space
    field separators (then single spaces), continuation lines
    indented, so no header line runs off the image."""
    out: List[str] = []
    for line in lines:
        if _text_width(draw, line, font) <= max_width:
            out.append(line)
            continue
        fields = [f for f in line.split("  ") if f]
        if len(fields) == 1:
            fields = line.split(" ")
            joiner = " "
        else:
            joiner = "  "
        # Each field measured once; a line's width is the sum of its
        # fields and joiners (kerning across a joiner is negligible).
        joiner_w = _text_width(draw, joiner, font)
        indent_w = _text_width(draw, "  ", font)
        current: List[str] = []
        width = 0.0
        for field in fields:
            fw = _text_width(draw, field, font)
            added = fw if not current else joiner_w + fw
            if current and width + added > max_width:
                out.append(joiner.join(current))
                current, width = ["  " + field], indent_w + fw
            else:
                current.append(field)
                width += added
        if current:
            out.append(joiner.join(current))
    return out


class _Labels:
    """Placed labels, so a new one landing within LABEL_CLEARANCE_PX
    of an existing one is shifted down until clear (bounded). With
    ``enabled`` False (a thumbnail) nothing is drawn or placed."""

    def __init__(self, enabled: bool = True):
        self.boxes: List[Tuple[float, float, float, float]] = []
        self.enabled = enabled
        self.drawn = 0

    def place(self, draw, xy, text, fill, font, w_img, h_img):
        if not self.enabled:
            return None
        self.drawn += 1
        tw = _text_width(draw, text, font)
        th = getattr(font, "size", 12)
        x, y = float(xy[0]), float(xy[1])
        x = min(max(0.0, x), max(0.0, w_img - tw))
        for _ in range(8):
            box = (x, y, x + tw, y + th)
            if not any(_near(box, other, LABEL_CLEARANCE_PX) for other in self.boxes):
                break
            y += th + 4
        y = min(max(0.0, y), max(0.0, h_img - th))
        box = (x, y, x + tw, y + th)
        self.boxes.append(box)
        draw.text((x, y), text, fill=fill, font=font)
        return box


def _near(a, b, clearance):
    return not (a[2] + clearance < b[0] or b[2] + clearance < a[0]
                or a[3] + clearance < b[1] or b[3] + clearance < a[1])


# -- one picture -------------------------------------------------------------

def draw_preview(record: Dict, manifest: Dict, ground, scale: int = 1,
                 image=None, alpha: int = 255, tag: str = "geometry preview, not a render",
                 track_points: Optional[Sequence] = None,
                 terrain_elevation_m: float = 0.0,
                 track_words: Optional[str] = None,
                 size: Optional[Tuple[int, int]] = None,
                 style: str = "full"):
    """Draw one frame's geometry. ``ground`` is a :class:`Ground` or
    the tuple ``("terrain", (a, b))`` of world segments from
    :func:`terrain_wireframe` / ``("flat", None)``. With ``image`` the
    geometry is drawn as a translucent layer over it AT ITS OWN SIZE
    (the record's intrinsics scaled per axis); with ``size`` a fresh
    image of exactly that size is drawn the same way (a contact-sheet
    tile: the intrinsics scaled per axis, nothing resampled). ``style``
    "thumbnail" draws for a tile: no text of any kind (no header,
    legend, compass, FOV or labels) and the horizon, track and body at
    THUMBNAIL_LINE_PX. Returns ``(image, info)``: info carries the
    header lines, the horizon segment, the aircraft centre pixel, the
    compass, the arrow, the count of text items drawn and the counts
    of segments drawn -- what the tests grade."""
    from PIL import Image, ImageDraw

    ground = Ground.coerce(ground)
    scale = validated_scale(scale)
    if style not in ("full", "thumbnail"):
        raise ValueError(f"preview.style: {style!r} is neither 'full' nor 'thumbnail'")
    thumbnail = style == "thumbnail"
    if image is None and size is not None:
        w, h = int(size[0]), int(size[1])
        image = Image.new("RGB", (w, h), BACKGROUND_RGB)
        layer = image
        axis_scale: Tuple[float, float] = (float(record["width_px"]) / w,
                                           float(record["height_px"]) / h)
    elif image is None:
        w = int(record["width_px"]) // scale
        h = int(record["height_px"]) // scale
        image = Image.new("RGB", (w, h), BACKGROUND_RGB)
        layer = image
        axis_scale = (float(scale), float(scale))
    else:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        w, h = image.size
        axis_scale = (float(record["width_px"]) / w, float(record["height_px"]) / h)
    sx, sy = axis_scale
    draw = ImageDraw.Draw(layer)
    axes = _camera_axes(record)
    info: Dict = {"scale": scale, "axis_scale": axis_scale, "size": (w, h),
                  "style": style, "segments": {}, "text_drawn": 0}
    font_px = header_font_px(h)
    label_font = _font(round(font_px * 0.93))
    small = _font(round(font_px * 0.87))
    line_px = THUMBNAIL_LINE_PX if thumbnail else 1
    labels = _Labels(enabled=not thumbnail)

    def rgba(rgb):
        return rgb if layer is image else (rgb + (alpha,))

    def text(xy, string, fill, font):
        """Every piece of text goes through here: none in a thumbnail."""
        if thumbnail:
            return
        info["text_drawn"] += 1
        draw.text(xy, string, fill=fill, font=font)

    def colour_shaded(tint):
        base = _shaded(record, tint)
        return lambda depth: rgba(base(depth))

    def px(point):
        u, v, z = project_point(record, point, axes)
        return (u / sx, v / sy, z)

    def in_frame(u, v, z):
        return z > 0 and 0 <= u < w and 0 <= v < h

    # 1. ground
    plan = None
    arrow_base = None
    far = float(record.get("far_m", 1e5))
    if ground.kind == "terrain":
        a, b = ground.segments
        kinds = [np.zeros(len(a), dtype=int)]
        parts_a, parts_b = [a], [b]
        radii = [np.zeros(len(a))]
        if ground.heightfield is not None and ground.plan is not None:
            na, nb = terrain_near_wireframe(ground.heightfield, ground.frame,
                                            record, ground.plan)
            parts_a.append(na); parts_b.append(nb)
            kinds.append(np.ones(len(na), dtype=int)); radii.append(np.zeros(len(na)))
            ra, rb, rr = terrain_rings(record, ground, far)
            parts_a.append(ra); parts_b.append(rb)
            kinds.append(np.full(len(ra), 2, dtype=int)); radii.append(rr)
        all_a = np.concatenate(parts_a); all_b = np.concatenate(parts_b)
        kind_of = np.concatenate(kinds); radius_of = np.concatenate(radii)
        clipped, za, zb, survivors = _project_clip(
            record, all_a, all_b, axis_scale, axes)
        visible, source, skyline = skyline_cull(clipped, za, zb, w)
        src_kind = kind_of[survivors][source] if len(source) else np.zeros(0, dtype=int)
        src_radius = radius_of[survivors][source] if len(source) else np.zeros(0)
        clipped_kind = kind_of[survivors]
        # "terrain": the coarse segments in the frame (what the frame
        # contains); "terrain_visible": those left after the cull.
        info["segments"]["terrain"] = int((clipped_kind == 0).sum())
        info["segments"]["terrain_visible"] = int((src_kind == 0).sum())
        info["segments"]["terrain_fine"] = int((src_kind == 1).sum())
        info["segments"]["terrain_hidden"] = int(len(clipped) - len(visible))
        _draw_segments(draw, visible[src_kind == 0], colour_shaded(TERRAIN_TINT))
        _draw_segments(draw, visible[src_kind == 1], colour_shaded(TERRAIN_TINT))
        ring_rows = visible[src_kind == 2]
        ring_radii = src_radius[src_kind == 2]
        _draw_segments(draw, ring_rows, _solid(rgba(RING_RGB)))
        info["segments"]["rings"] = int(len(set(ring_radii.tolist())))
        # Label each ring on its visible piece nearest the centre column.
        for radius in sorted(set(ring_radii.tolist())):
            rows = ring_rows[ring_radii == radius]
            mid_u = 0.5 * (rows[:, 0] + rows[:, 2])
            k = int(np.argmin(np.abs(mid_u - w / 2.0)))
            labels.place(draw, (rows[k, 0] + 3, rows[k, 1] - 12), _ring_label(radius),
                         rgba(RING_RGB), label_font, w, h)
        if ground.heightfield is not None:
            arrow_base = terrain_arrow_base(record, ground)
    else:
        plan = flat_ground_plan(record, terrain_elevation_m)
        info["ground_plan"] = plan
        if plan is not None:
            a, b = flat_ground_segments(plan)
            clipped = _clip_segments(record, a, b, axis_scale, axes)
            _draw_segments(draw, clipped, colour_shaded(FLAT_TINT))
            info["segments"]["grid"] = int(len(clipped))
            rings = 0
            for radius in plan["rings_m"]:
                ra, rb = ring_segments(plan, radius)
                clipped = _clip_segments(record, ra, rb, axis_scale, axes)
                _draw_segments(draw, clipped, _solid(rgba(RING_RGB)))
                rings += int(len(clipped) > 0)
                # Label at the ring's point along the camera's forward
                # azimuth, measured from the camera's ground point.
                fwd = axes[0]
                norm = math.hypot(fwd[0], fwd[1]) or 1.0
                lp = (plan["camera_north_m"] + radius * fwd[0] / norm,
                      plan["camera_east_m"] + radius * fwd[1] / norm, plan["alt_m"])
                u, v, z = px(lp)
                if in_frame(u, v, z):
                    labels.place(draw, (u + 3, v - 12), _ring_label(radius),
                                 rgba(RING_RGB), label_font, w, h)
            info["segments"]["rings"] = rings
            arrow_base = north_arrow_base(record, plan)

    # 1b. the north arrow (every scene), NORTH_ARROW_PX on screen
    info["segments"]["north_arrow"] = 0
    if arrow_base is not None:
        arrow = north_arrow_points(record, arrow_base, axes)
        if arrow is not None:
            segs = _clip_segments(record,
                                  np.array([arrow["base"], arrow["tip"], arrow["tip"]]),
                                  np.array([arrow["tip"], arrow["head_l"], arrow["head_r"]]),
                                  axis_scale, axes)
            _draw_segments(draw, segs, _solid(rgba(NORTH_RGB)), width=2)
            info["segments"]["north_arrow"] = int(len(segs))
            u, v, z = px(arrow["tip"])
            info["north_arrow"] = {"base": arrow["base"], "tip": arrow["tip"],
                                   "length_m": arrow["length_m"],
                                   "screen_px": arrow["screen_px"],
                                   "tip_px": (u, v) if z > 0 else None}
            if in_frame(u, v, z):
                labels.place(draw, (u + 4, v - 6), "N", rgba(NORTH_RGB),
                             _font(font_px + 1), w, h)

    # 2. horizon
    horizon = horizon_segment(record, axis_scale)
    info["horizon"] = horizon
    if horizon is not None:
        draw.line([horizon[0], horizon[1]], fill=rgba(HORIZON_RGB), width=line_px)

    # 3. track: past solid, future dim, split at the frame's instant;
    #    this camera's scheduled instants as dots on the line
    if track_points:
        pts = np.array([p[:3] for p in track_points], dtype=float)
        when = np.array([p[4] if len(p) > 4 else p[3] for p in track_points], dtype=float)
        now = float(record["t_s"]) if len(track_points[0]) > 4 else float(record["sample_index"])
        if len(pts) > 1:
            a, b = pts[:-1], pts[1:]
            past = when[1:] <= now + 1e-9
            for mask, rgb in ((past, TRACK_PAST_RGB), (~past, TRACK_FUTURE_RGB)):
                if mask.any():
                    clipped = _clip_segments(record, a[mask], b[mask], axis_scale, axes)
                    _draw_segments(draw, clipped, _solid(rgba(rgb)), width=line_px)
                    info["segments"].setdefault("track", 0)
                    info["segments"]["track"] += int(len(clipped))
        dots = 0
        for other in manifest.get("frames", []):
            if other["camera_id"] != record["camera_id"]:
                continue
            oa = other["aircraft"]
            u, v, z = px((oa["north_m"], oa["east_m"], oa["alt_m"]))
            if in_frame(u, v, z):
                rgb = TRACK_PAST_RGB if float(other["t_s"]) <= record["t_s"] + 1e-9 else TRACK_FUTURE_RGB
                draw.ellipse([u - 2, v - 2, u + 2, v + 2], fill=rgba(rgb))
                dots += 1
        info["segments"]["track_dots"] = dots

    # 4. the aircraft
    a = record["aircraft"]
    u, v, z = px((a["north_m"], a["east_m"], a["alt_m"]))
    centre = (u, v) if z > 0 else None
    info["aircraft_px"] = centre
    metrics = manifest.get("aircraft_metrics")
    if metrics:
        body = aircraft_body_points(record, metrics)
        info["body"] = {}
        for name in ("nose", "tail", "left_tip", "right_tip", "fin_top", "heading_tick"):
            bu, bv, bz = px(body[name])
            info["body"][name] = (bu, bv) if bz > 0 else None
        box_a = np.array([body[e[0]] for e in BOX_EDGES])
        box_b = np.array([body[e[1]] for e in BOX_EDGES])
        clipped = _clip_segments(record, box_a, box_b, axis_scale, axes)
        _draw_segments(draw, clipped, _solid(rgba(BOX_RGB)), width=line_px)
        info["segments"]["box"] = int(len(clipped))
        axes_a = np.array([body["tail"], body["left_tip"], body["centre"]])
        axes_b = np.array([body["nose"], body["right_tip"], body["fin_top"]])
        clipped = _clip_segments(record, axes_a, axes_b, axis_scale, axes)
        _draw_segments(draw, clipped, _solid(rgba(BODY_RGB)), width=2)
        info["segments"]["body"] = int(len(clipped))
        tick = _clip_segments(record, np.array([body["nose"]]),
                              np.array([body["heading_tick"]]), axis_scale, axes)
        _draw_segments(draw, tick, _solid(rgba(HEADING_RGB)), width=2)
        info["segments"]["heading_tick"] = int(len(tick))
    elif centre is not None:
        r = 8
        draw.line([(centre[0] - r, centre[1]), (centre[0] + r, centre[1])],
                  fill=rgba(NO_METRICS_RGB), width=2)
        draw.line([(centre[0], centre[1] - r), (centre[0], centre[1] + r)],
                  fill=rgba(NO_METRICS_RGB), width=2)

    # 5. the camera: boresight cross at the principal point, FOV at the edges
    cx, cy = (record["principal_point_px"][0] / sx,
              record["principal_point_px"][1] / sy)
    gap, arm = 4, 14
    for (x0, y0, x1, y1) in ((cx - arm, cy, cx - gap, cy), (cx + gap, cy, cx + arm, cy),
                             (cx, cy - arm, cx, cy - gap), (cx, cy + gap, cx, cy + arm)):
        draw.line([(x0, y0), (x1, y1)], fill=rgba(CAMERA_RGB), width=1)
    hfov, vfov = field_of_view_deg(record)
    labels.place(draw, (cx + arm + 2, cy + 2), "boresight", rgba(CAMERA_RGB), small, w, h)
    text((cx - 40, h - 18), f"HFOV {hfov:.1f} deg", rgba(CAMERA_RGB), small)
    text((4, cy - 14), f"VFOV\n{vfov:.1f}", rgba(CAMERA_RGB), small)
    for (x0, y0, x1, y1) in ((cx, 0, cx, 6), (cx, h - 7, cx, h - 1), (0, cy, 6, cy),
                             (w - 7, cy, w - 1, cy)):
        draw.line([(x0, y0), (x1, y1)], fill=rgba(CAMERA_RGB), width=2)

    # 5b. the compass rose: image space, every scene but a thumbnail
    rose = compass_rose(record, w, h)
    info["compass"] = rose
    if not thumbnail:
        rcx, rcy, rr = rose["centre"][0], rose["centre"][1], rose["radius"]
        draw.ellipse([rcx - rr, rcy - rr, rcx + rr, rcy + rr], outline=rgba(COMPASS_RGB))
        for name, spoke in rose["spokes"].items():
            tip = spoke["tip"]
            colour = NORTH_RGB if name == "N" else COMPASS_RGB
            draw.line([(rcx, rcy), tip], fill=rgba(colour), width=3 if name == "N" else 1)
            ang = math.radians(spoke["angle_deg"])
            lx, ly = rcx + (rr + 9) * math.sin(ang), rcy - (rr + 9) * math.cos(ang)
            text((lx - 4, ly - 6), name, rgba(colour), small)
        draw.line([(rcx, rcy), rose["heading_tip"]], fill=rgba(BODY_RGB), width=2)
        text((rcx - rr - 12, rcy + rr + 20),
             f"cam yaw {rose['yaw_deg']:.1f}", rgba(COMPASS_RGB), small)
        text((rcx - rr - 12, rcy + rr + 20 + font_px),
             f"hdg {rose['heading_deg']:.1f}", rgba(BODY_RGB), small)

    # 6. header, wrapped to the image width, font from the image height
    lines = header_lines(record, manifest, scale, tag, ground=ground, plan=plan,
                         terrain_elevation_m=terrain_elevation_m,
                         track_words=track_words)
    info["header"] = lines
    font = _font(font_px)
    line_h = font_px + 2
    wrapped = wrap_lines(draw, lines, font, w - 8) if not thumbnail else []
    info["header_drawn"] = wrapped
    band_alpha = 255 if layer is image else min(alpha, OVERLAY_BAND_ALPHA)
    if not thumbnail:
        draw.rectangle([0, 0, w, 4 + line_h * len(wrapped) + 2],
                       fill=rgba((0, 0, 0)) if layer is image else (0, 0, 0, band_alpha))
    info["header_band_px"] = 4 + line_h * len(wrapped) + 2 if not thumbnail else 0
    for i, line in enumerate(wrapped):
        text((4, 3 + line_h * i), line, rgba(TEXT_RGB), font)
    legend = ("legend: ground wireframe depth-shaded (near bright, hidden behind "
              "ridges) | horizon | rings from the camera | N arrow | track past/future "
              "+ scheduled dots | aircraft body + box | heading tick | boresight + FOV | "
              "compass: N and heading")
    legend_lines = (wrap_lines(draw, [legend], small,
                               max(80, w - 2 * COMPASS_INSET_PX[0] - 20))
                    if not thumbnail else [])
    for i, line in enumerate(legend_lines):
        text((4, h - 22 - (len(legend_lines) - i) * (round(font_px * 0.87) + 2)),
             line, rgba((160, 160, 160)), small)
    info["text_drawn"] += labels.drawn

    if layer is not image:
        image = Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
    return image, info


def _ground(heightfield, scene_frame) -> Ground:
    if heightfield is not None and scene_frame is not None:
        return Ground("terrain", terrain_wireframe(heightfield, scene_frame),
                      heightfield=heightfield, frame=scene_frame,
                      plan=terrain_plan(heightfield, scene_frame))
    return Ground("flat", None)


def render_previews(manifest: Dict, out_dir, heightfield=None,
                    scene_frame=None,
                    terrain_elevation_m: float = 0.0,
                    max_frames: Optional[int] = None,
                    scale: int = PREVIEW_SCALE_DEFAULT,
                    contact_sheets: bool = True,
                    telemetry: Optional[Dict[str, Sequence[float]]] = None) -> PreviewSet:
    """Write one preview PNG per frame record (full resolution by
    default; ``scale=N`` for 1/N) and a per-camera contact sheet;
    returns the paths as a :class:`PreviewSet` carrying the measured
    seconds per frame.

    ``scene_frame`` is needed only when a heightfield is given (to
    express the raster in the manifest's local frame). ``telemetry``
    is the run's recorded columns (the Recorder's mapping): when given,
    the flown track is drawn from it (:func:`telemetry_track`); when
    not, the track is the manifest's scheduled instants and the header
    says so.
    """
    scale = validated_scale(scale)
    ground = _ground(heightfield, scene_frame)
    track_points, track_words = _track_points(manifest, telemetry, scene_frame)
    written = PreviewSet()
    written.scale = scale
    written.track_source = track_words
    frames = manifest.get("frames", [])
    if max_frames is not None:
        frames = frames[:max_frames]
    per_camera: Dict[str, List[Path]] = {}
    started = time.perf_counter()
    for record in frames:
        image, info = draw_preview(record, manifest, ground, scale=scale,
                                   track_points=track_points,
                                   terrain_elevation_m=terrain_elevation_m,
                                   track_words=track_words)
        written.resolution = info["size"]
        path = (Path(out_dir) / "previews" / record["camera_id"]
                / f"preview_{record['index']:05d}.png")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        written.append(path)
        per_camera.setdefault(record["camera_id"], []).append(path)
    elapsed = time.perf_counter() - started
    written.seconds_per_frame = elapsed / len(written) if written else 0.0
    if contact_sheets:
        for camera_id, paths in per_camera.items():
            sheet, _ = contact_sheet(manifest, camera_id, paths,
                                     Path(out_dir) / "contact_sheets"
                                     / f"{camera_id}.png", scale=scale,
                                     ground=ground, track_points=track_points,
                                     terrain_elevation_m=terrain_elevation_m)
            written.contact_sheets[camera_id] = sheet
    return written


def contact_label(index: int, total, t_s: Optional[float]) -> str:
    """"#5 (6/24)  t=2.683 s": the manifest index and the human count."""
    words = f"#{index} ({int(index) + 1}/{total})"
    return f"{words}  t={t_s:.3f} s" if t_s is not None else words


def thumbnail_size(width_px: int, height_px: int,
                   thumb_width: int = CONTACT_THUMB_WIDTH_PX) -> Tuple[int, int]:
    """The tile size for a record: ``thumb_width`` wide, the height at
    the record's own ratio rounded to a pixel (1280x720 -> 320x180)."""
    return (int(thumb_width),
            max(1, int(round(thumb_width * float(height_px) / float(width_px)))))


def contact_sheet(manifest: Dict, camera_id: str, paths: Sequence[Path],
                  out_path, scale: int = 1,
                  thumb_width: int = CONTACT_THUMB_WIDTH_PX,
                  columns: int = CONTACT_COLUMNS, ground=("flat", None),
                  track_points: Optional[Sequence] = None,
                  terrain_elevation_m: float = 0.0):
    """A grid of every preview of one camera, each tile DRAWN FOR THE
    TILE from its frame record (:func:`draw_preview` at the tile's
    size in the thumbnail style: horizon, ground, rings, arrow, track
    and body at THUMBNAIL_LINE_PX, no text of any kind) -- never the
    preview shrunk, whose one-pixel lines and header smear to nothing
    at a quarter size -- with index and time under each tile and a
    title row with camera id, preset, schedule basis and count.
    ``paths`` names the previews on the sheet (each tile's record is
    the manifest frame of the path's index). Returns ``(path, info)``;
    info["thumbnails"] is the count laid out, info["tiles"] each tile's
    origin, size and draw info."""
    from PIL import Image, ImageDraw

    ground = Ground.coerce(ground)
    block = _camera_block(manifest, camera_id)
    records = {r["index"]: r for r in manifest.get("frames", [])
               if r["camera_id"] == camera_id}
    paths = list(paths)
    count = len(paths)
    cols = max(1, min(columns, count))
    rows = max(1, math.ceil(count / cols))
    first = records[min(records)] if records else None
    if first is not None:
        tw, th = thumbnail_size(first["width_px"], first["height_px"], thumb_width)
    else:
        tw, th = thumbnail_size(16, 9, thumb_width)
    margin, label_h, title_h = 6, 18, 28
    width = margin + cols * (tw + margin)
    height = title_h + margin + rows * (th + label_h + margin)
    sheet = Image.new("RGB", (width, height), BACKGROUND_RGB)
    draw = ImageDraw.Draw(sheet)
    font = _font(15)
    small = _font(12)
    total = block.get("capture_count", len(records))
    scale_note = "" if scale == 1 else f" at 1/{scale}"
    title = (f"{camera_id}  preset {block.get('preset', '?')}  schedule: "
             f"{block.get('schedule_basis', '?')}  {count} of {total} frames"
             f"  (tiles {tw}x{th} drawn from the records; previews "
             f"{int(first['width_px']) if first else '?'}x"
             f"{int(first['height_px']) if first else '?'}{scale_note})")
    draw.text((margin, 6), title, fill=TEXT_RGB, font=font)
    tiles = []
    for k, path in enumerate(paths):
        r, c = divmod(k, cols)
        x = margin + c * (tw + margin)
        y = title_h + margin + r * (th + label_h + margin)
        index = int(Path(path).stem.split("_")[-1])
        record = records.get(index)
        tile_info = None
        if record is not None:
            tile, tile_info = draw_preview(record, manifest, ground, size=(tw, th),
                                           style="thumbnail", track_points=track_points,
                                           terrain_elevation_m=terrain_elevation_m)
            sheet.paste(tile, (x, y))
        label = contact_label(index, total, record["t_s"] if record else None)
        draw.text((x, y + th + 2), label, fill=TEXT_RGB, font=small)
        tiles.append({"index": index, "origin": (x, y), "size": (tw, th),
                      "info": tile_info, "label": label})
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path, {"thumbnails": count, "columns": cols, "rows": rows,
                      "thumb_size": (tw, th), "size": (width, height),
                      "tiles": tiles}


def overlay_tag(record: Dict, size: Tuple[int, int]) -> str:
    """The overlay's header tag; a frame whose size differs from its
    record says so and how it was handled."""
    tag = "overlay: reprojected geometry over the rendered frame"
    if tuple(size) != (int(record["width_px"]), int(record["height_px"])):
        tag += (f"; frame {size[0]}x{size[1]} differs from the record's "
                f"{int(record['width_px'])}x{int(record['height_px'])}: "
                f"intrinsics scaled to the frame, pixels not resampled")
    return tag


def render_overlays(manifest: Dict, capture_dir, heightfield=None,
                    scene_frame=None, terrain_elevation_m: float = 0.0,
                    alpha: int = 200,
                    telemetry: Optional[Dict[str, Sequence[float]]] = None) -> OverlaySet:
    """For every frame record whose rendered PNG exists at
    ``capture_dir / record["file"]``, draw the reprojected geometry
    (terrain wireframe or grid, horizon, track, aircraft body and box,
    boresight, compass, header) as a translucent layer over the frame
    and write ``capture_dir / overlays / <camera_id> / NNNN.png`` at
    the frame's OWN size, whatever it is: a frame whose size differs
    from its record is drawn through the record's intrinsics scaled
    per axis by the actual ratio and says so in the header; the
    rendered pixels are never resampled. The verifier, not the
    overlay, grades that mismatch."""
    from PIL import Image

    capture_dir = Path(capture_dir)
    ground = _ground(heightfield, scene_frame)
    track_points, track_words = _track_points(manifest, telemetry, scene_frame)
    written = OverlaySet()
    started = time.perf_counter()
    for record in manifest.get("frames", []):
        frame_path = capture_dir / record["file"]
        if not frame_path.is_file():
            continue
        frame = Image.open(frame_path).convert("RGB")
        image, _ = draw_preview(record, manifest, ground, scale=1,
                                image=frame, alpha=alpha,
                                tag=overlay_tag(record, frame.size),
                                track_points=track_points,
                                terrain_elevation_m=terrain_elevation_m,
                                track_words=track_words)
        path = capture_dir / "overlays" / record["camera_id"] / f"{record['index']:04d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        written.append(path)
        written.sizes[path] = image.size
    elapsed = time.perf_counter() - started
    written.seconds_per_frame = elapsed / len(written) if written else 0.0
    return written
