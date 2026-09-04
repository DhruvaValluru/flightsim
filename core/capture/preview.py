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
* **Terrain** (terrain scenes): the raster sampled on a TERRAIN_GRID x
  TERRAIN_GRID lattice and drawn as a WIREFRAME (each sample joined to
  its row and column neighbour), every segment clipped at the camera's
  near plane (``near_m``) and to the image, shaded by camera-space
  DEPTH: brightness = 32 + 208 x (1 - ln(z / ref) / ln(far_m / ref))
  with ref the frame's subject range (camera to the recorded aircraft,
  never below near_m nor above far_m / 10) and far_m the record's far
  plane, so what the frame looks at is bright and the far ground dim.
* **Ground grid** (flat scenes): the level plane at the spec's terrain
  elevation, two lattices centred on the ground point beneath the
  camera -- a fine one whose step is the "nice" number at or above a
  quarter of the camera's height above the plane, and a coarse one at
  ten times that step whose extent is the smaller of ``far_m`` and the
  distance at which the plane sits within two pixels of the horizon
  (fy x height / 2): the grid always reaches the horizon or the far
  plane, whichever the record reaches first. Depth-shaded like the
  terrain. **Distance rings** at DISTANCE_RINGS_M around that ground
  point, each labelled, and a **north arrow** on the plane, one grid
  step long, where the boresight meets the ground (or ahead of the
  camera when it does not).
* **Horizon**: the image of the level plane at infinity for the
  camera's pitch and roll -- directions with zero vertical component,
  projected; for a level camera it is the row ``v = cy``, for pitch p
  it is ``cy + fy tan(p)`` (a camera pitched DOWN sees the horizon
  above its centre), and roll tilts it. Drawn in HORIZON_RGB.
* **Aircraft**: a three-axis body scaled from the manifest's
  ``aircraft_metrics`` (read ONCE from the configured FDM by the
  runner: span from ``metrics/bw-ft``, the longitudinal extent from
  ``metrics/lh-ft`` + ``metrics/cbarw-ft``, the vertical extent from
  ``sqrt(metrics/Sv-sqft)``; the source of each is carried beside the
  number) -- nose-to-tail along the recorded heading and pitch, wing
  tips at +/- span/2 with the recorded roll, a fin up from the centre,
  the length x span x height BOX around it, a HEADING TICK beyond the
  nose along the recorded heading, and the flown TRACK (the manifest's
  own per-instant aircraft positions: the past solid, the future dim).
  A manifest WITHOUT metrics gets a fixed cross and the header says
  "aircraft_metrics absent: body unscaled" -- never a silent guess.
* **Camera**: a boresight cross at ``principal_point_px``, the
  horizontal and vertical field of view (2 atan(sensor / 2 focal))
  printed at the frame edges, and the aircraft-to-camera bearing and
  range in the header.
* **Header**: camera id, frame index / capture count, simulation time,
  position, look direction (yaw, pitch, roll), focal length and fx, the
  resolution; and the aircraft's state.

Full output resolution by default (``scale=1``: the record's own
``width_px`` x ``height_px``); ``scale=N`` draws at 1/N and the header
says so. Render time is MEASURED per call (``PreviewSet.seconds_per_
frame``) against RENDER_BUDGET_S_PER_FRAME.

Overlays (:func:`render_overlays`): for every frame record whose PNG
exists, the same geometry drawn as a translucent layer over the
rendered frame -- the verification made visible -- under
``overlays/<camera_id>/NNNN.png``. Contact sheets
(:func:`contact_sheet`): every preview of a camera as thumbnails with
index and time, under ``contact_sheets/<camera_id>.png`` -- beside
``previews/``, never inside it, so ``previews/`` holds exactly one PNG
per drawn frame and a count of it is a count of previews.

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
#: Terrain raster sampling per axis for the wireframe.
TERRAIN_GRID = 48
#: Flat-scene distance rings (metres) around the camera's ground point.
DISTANCE_RINGS_M = (500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0)
#: "Nice" grid steps (metres) the flat lattice chooses from.
GRID_STEPS_M = (10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0,
                5000.0, 10000.0)

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
NO_METRICS_RGB = (255, 80, 80)
CONTACT_THUMB_WIDTH_PX = 320
CONTACT_COLUMNS = 6


class PreviewSet(list):
    """The written preview paths, plus what the run measured: the
    per-frame render time, the scale, the drawn resolution and the
    per-camera contact sheets."""

    seconds_per_frame: float = 0.0
    scale: int = PREVIEW_SCALE_DEFAULT
    resolution: Optional[Tuple[int, int]] = None
    contact_sheets: Dict[str, Path]

    def __init__(self, paths=()):
        super().__init__(paths)
        self.contact_sheets = {}


class OverlaySet(list):
    seconds_per_frame: float = 0.0


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


def _clip_segments(record, a: np.ndarray, b: np.ndarray, scale: float,
                   axes=None):
    """Project world segments a->b through the record and return the
    (u0, v0, u1, v1, depth) rows that survive: clipped at the near plane
    in camera space (a segment crossing z = near_m is cut there, one
    wholly behind is dropped) and to the image rectangle in pixels
    (Liang-Barsky), in PREVIEW pixels (record pixels / scale)."""
    if len(a) == 0:
        return np.zeros((0, 5))
    axes = axes or _camera_axes(record)
    near = max(float(record.get("near_m", 0.1)), 1e-3)
    ca = _to_camera(record, np.asarray(a, dtype=float), axes)
    cb = _to_camera(record, np.asarray(b, dtype=float), axes)
    za, zb = ca[:, 2], cb[:, 2]
    keep = (za > near) | (zb > near)
    ca, cb, za, zb = ca[keep], cb[keep], za[keep], zb[keep]
    if len(ca) == 0:
        return np.zeros((0, 5))
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
    u0 = (cx + fx * ca[:, 0] / ca[:, 2]) / scale
    v0 = (cy + fy * ca[:, 1] / ca[:, 2]) / scale
    u1 = (cx + fx * cb[:, 0] / cb[:, 2]) / scale
    v1 = (cy + fy * cb[:, 1] / cb[:, 2]) / scale
    depth = 0.5 * (ca[:, 2] + cb[:, 2])
    w = float(record["width_px"]) / scale
    h = float(record["height_px"]) / scale
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
    return out[ok]


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
    for u0, v0, u1, v1, depth in segments:
        draw.line([(float(u0), float(v0)), (float(u1), float(v1))],
                  fill=colour_of(depth), width=width)


def _shaded(record, tint=(0.55, 0.9, 0.6)):
    def colour(depth):
        b = float(depth_brightness(depth, record))
        return tuple(int(b * t) for t in tint)
    return colour


def _solid(rgb):
    return lambda depth: rgb


def horizon_points(record, scale: float = 1.0, samples: int = 179):
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
        points.append(((cx + fx * x / z) / scale, (cy + fy * y / z) / scale))
    return points


def horizon_segment(record, scale: float = 1.0):
    """The horizon clipped to the image: ((u0, v0), (u1, v1)) in preview
    pixels, or None when no level direction lies in front of the camera
    inside the frame."""
    points = horizon_points(record, scale)
    if len(points) < 2:
        return None
    w = float(record["width_px"]) / scale
    h = float(record["height_px"]) / scale
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

def terrain_wireframe(heightfield, frame, grid: int = TERRAIN_GRID):
    """(a, b) arrays of world segments: the raster sampled on a grid x
    grid lattice in the scene frame's local metres, each sample joined
    to its row and column neighbour."""
    z = heightfield.elevations()
    rows = np.linspace(0, heightfield.height - 1, grid).astype(int)
    cols = np.linspace(0, heightfield.width - 1, grid).astype(int)
    g = heightfield.georeference
    east = (g.origin_x_m + cols * g.pixel_size_m) - frame.origin_x_m
    north = (g.origin_y_m - rows * g.pixel_size_m) - frame.origin_y_m
    alt = z[np.ix_(rows, cols)].astype(float)
    pts = np.stack([np.repeat(north[:, None], grid, axis=1),
                    np.repeat(east[None, :], grid, axis=0), alt], axis=2)
    along_rows = (pts[:, :-1, :].reshape(-1, 3), pts[:, 1:, :].reshape(-1, 3))
    along_cols = (pts[:-1, :, :].reshape(-1, 3), pts[1:, :, :].reshape(-1, 3))
    return (np.concatenate([along_rows[0], along_cols[0]]),
            np.concatenate([along_rows[1], along_cols[1]]))


def _nice_step(value_m: float) -> float:
    for step in GRID_STEPS_M:
        if step >= value_m:
            return step
    return GRID_STEPS_M[-1]


def flat_ground_plan(record, terrain_elevation_m: float) -> Optional[Dict]:
    """The flat lattice derived from the camera: step, extent, centre
    and rings, all in metres on the plane at ``terrain_elevation_m``.
    None when the camera is at or below the plane."""
    agl = float(record["position_alt_m"]) - float(terrain_elevation_m)
    if agl <= 0.0:
        return None
    step = _nice_step(agl / 4.0)
    fy = float(record["fy_px"])
    far = float(record.get("far_m", 1e5))
    extent = min(far, max(fy * agl / 2.0, 20.0 * step))
    centre_n = round(float(record["position_north_m"]) / step) * step
    centre_e = round(float(record["position_east_m"]) / step) * step
    return {"step_m": step, "coarse_step_m": 10.0 * step,
            "fine_extent_m": 10.0 * step, "extent_m": extent,
            "centre_north_m": centre_n, "centre_east_m": centre_e,
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


def ring_segments(plan: Dict, radius_m: float, samples: int = 72):
    cn, ce, alt = (float(plan["centre_north_m"]), float(plan["centre_east_m"]),
                   plan["alt_m"])
    theta = np.linspace(0.0, 2.0 * math.pi, samples + 1)
    pts = np.stack([cn + radius_m * np.cos(theta), ce + radius_m * np.sin(theta),
                    np.full(samples + 1, alt)], axis=1)
    return pts[:-1], pts[1:]


def _ring_label(text_m: float) -> str:
    return f"{text_m / 1000.0:g} km" if text_m >= 1000.0 else f"{text_m:g} m"


def north_arrow_base(record, plan: Dict):
    """Where the north arrow sits on the plane: the boresight's ground
    intersection when the camera looks down at the plane within the
    lattice, else three fine steps ahead of the camera's ground point."""
    forward, _, _ = _camera_axes(record)
    cam = (float(record["position_north_m"]), float(record["position_east_m"]))
    if forward[2] < -1e-6:
        t = plan["agl_m"] / -forward[2]
        if t <= plan["extent_m"]:
            return (cam[0] + forward[0] * t, cam[1] + forward[1] * t, plan["alt_m"])
    norm = math.hypot(forward[0], forward[1]) or 1.0
    ahead = 3.0 * plan["step_m"]
    return (cam[0] + forward[0] / norm * ahead, cam[1] + forward[1] / norm * ahead,
            plan["alt_m"])


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


# -- header ----------------------------------------------------------------

def _camera_block(manifest: Dict, camera_id: str) -> Dict:
    for block in manifest.get("cameras", []) or []:
        if block.get("camera_id") == camera_id:
            return block
    return {}


def header_lines(record: Dict, manifest: Dict, scale: int = 1,
                 tag: str = "geometry preview, not a render") -> List[str]:
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
        f"{record['camera_id']}  frame {record['index']}/{count}  "
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
    ]
    if metrics:
        lines.append(
            f"body span {float(metrics['span_m']):.1f} m "
            f"({metrics.get('span_source', '?')}), length "
            f"{float(metrics['length_m']):.1f} m, height "
            f"{float(metrics['height_m']):.1f} m (FDM metrics)")
    else:
        lines.append("aircraft_metrics absent: body unscaled (cross marker)")
    return lines


def _font(size_px: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=max(8, int(size_px)))
    except TypeError:                          # Pillow < 10.1
        return ImageFont.load_default()


# -- one picture -------------------------------------------------------------

def draw_preview(record: Dict, manifest: Dict, ground, scale: int = 1,
                 image=None, alpha: int = 255, tag: str = "geometry preview, not a render",
                 track_points: Optional[Sequence] = None,
                 terrain_elevation_m: float = 0.0):
    """Draw one frame's geometry. ``ground`` is ``("terrain", (a, b))``
    world segments from :func:`terrain_wireframe` or ``("flat", None)``.
    Returns ``(image, info)``: info carries the header lines, the
    horizon segment, the aircraft centre pixel and the counts of
    segments drawn -- what the tests grade."""
    from PIL import Image, ImageDraw

    scale = validated_scale(scale)
    w = int(record["width_px"]) // scale
    h = int(record["height_px"]) // scale
    if image is None:
        image = Image.new("RGB", (w, h), BACKGROUND_RGB)
        layer = image
    else:
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        w, h = image.size
    draw = ImageDraw.Draw(layer)
    axes = _camera_axes(record)
    info: Dict = {"scale": scale, "size": (w, h), "segments": {}}

    def rgba(rgb):
        return rgb if layer is image else (rgb + (alpha,))

    def colour_shaded(tint):
        base = _shaded(record, tint)
        return lambda depth: rgba(base(depth))

    # 1. ground
    kind, segments = ground
    if kind == "terrain":
        clipped = _clip_segments(record, segments[0], segments[1], scale, axes)
        _draw_segments(draw, clipped, colour_shaded((0.55, 0.9, 0.6)))
        info["segments"]["terrain"] = int(len(clipped))
    else:
        plan = flat_ground_plan(record, terrain_elevation_m)
        info["ground_plan"] = plan
        if plan is not None:
            a, b = flat_ground_segments(plan)
            clipped = _clip_segments(record, a, b, scale, axes)
            _draw_segments(draw, clipped, colour_shaded((0.6, 0.7, 0.9)))
            info["segments"]["grid"] = int(len(clipped))
            rings = 0
            font = _font(14 / scale * 1.0 if scale == 1 else 11)
            for radius in plan["rings_m"]:
                ra, rb = ring_segments(plan, radius)
                clipped = _clip_segments(record, ra, rb, scale, axes)
                _draw_segments(draw, clipped, _solid(rgba(RING_RGB)))
                rings += int(len(clipped) > 0)
                # Label at the ring's point along the camera's forward azimuth.
                fwd = axes[0]
                norm = math.hypot(fwd[0], fwd[1]) or 1.0
                lp = (plan["centre_north_m"] + radius * fwd[0] / norm,
                      plan["centre_east_m"] + radius * fwd[1] / norm, plan["alt_m"])
                u, v, z = project_point(record, lp, axes)
                if z > 0 and 0 <= u / scale < w and 0 <= v / scale < h:
                    draw.text((u / scale + 3, v / scale - 12), _ring_label(radius),
                              fill=rgba(RING_RGB), font=font)
            info["segments"]["rings"] = rings
            base = north_arrow_base(record, plan)
            tip = (base[0] + plan["step_m"], base[1], base[2])
            head_l = (tip[0] - 0.25 * plan["step_m"], tip[1] - 0.15 * plan["step_m"], tip[2])
            head_r = (tip[0] - 0.25 * plan["step_m"], tip[1] + 0.15 * plan["step_m"], tip[2])
            arrow = _clip_segments(record, np.array([base, tip, tip]),
                                   np.array([tip, head_l, head_r]), scale, axes)
            _draw_segments(draw, arrow, _solid(rgba(NORTH_RGB)), width=2)
            info["segments"]["north_arrow"] = int(len(arrow))
            u, v, z = project_point(record, tip, axes)
            if z > 0 and 0 <= u / scale < w and 0 <= v / scale < h:
                draw.text((u / scale + 4, v / scale - 6), "N", fill=rgba(NORTH_RGB),
                          font=_font(16 if scale == 1 else 11))

    # 2. horizon
    horizon = horizon_segment(record, scale)
    info["horizon"] = horizon
    if horizon is not None:
        draw.line([horizon[0], horizon[1]], fill=rgba(HORIZON_RGB), width=1)

    # 3. track: past solid, future dim
    if track_points:
        pts = np.array([p[:3] for p in track_points], dtype=float)
        idx = np.array([p[3] for p in track_points])
        if len(pts) > 1:
            a, b = pts[:-1], pts[1:]
            past = idx[1:] <= record["sample_index"]
            for mask, rgb in ((past, TRACK_PAST_RGB), (~past, TRACK_FUTURE_RGB)):
                if mask.any():
                    clipped = _clip_segments(record, a[mask], b[mask], scale, axes)
                    _draw_segments(draw, clipped, _solid(rgba(rgb)))
                    info["segments"].setdefault("track", 0)
                    info["segments"]["track"] += int(len(clipped))

    # 4. the aircraft
    a = record["aircraft"]
    u, v, z = project_point(record, (a["north_m"], a["east_m"], a["alt_m"]), axes)
    centre = (u / scale, v / scale) if z > 0 else None
    info["aircraft_px"] = centre
    metrics = manifest.get("aircraft_metrics")
    if metrics:
        body = aircraft_body_points(record, metrics)
        info["body"] = {}
        for name in ("nose", "tail", "left_tip", "right_tip", "fin_top", "heading_tick"):
            bu, bv, bz = project_point(record, body[name], axes)
            info["body"][name] = (bu / scale, bv / scale) if bz > 0 else None
        box_a = np.array([body[e[0]] for e in BOX_EDGES])
        box_b = np.array([body[e[1]] for e in BOX_EDGES])
        clipped = _clip_segments(record, box_a, box_b, scale, axes)
        _draw_segments(draw, clipped, _solid(rgba(BOX_RGB)))
        info["segments"]["box"] = int(len(clipped))
        axes_a = np.array([body["tail"], body["left_tip"], body["centre"]])
        axes_b = np.array([body["nose"], body["right_tip"], body["fin_top"]])
        clipped = _clip_segments(record, axes_a, axes_b, scale, axes)
        _draw_segments(draw, clipped, _solid(rgba(BODY_RGB)), width=2)
        info["segments"]["body"] = int(len(clipped))
        tick = _clip_segments(record, np.array([body["nose"]]),
                              np.array([body["heading_tick"]]), scale, axes)
        _draw_segments(draw, tick, _solid(rgba(HEADING_RGB)), width=2)
        info["segments"]["heading_tick"] = int(len(tick))
    elif centre is not None:
        r = 8
        draw.line([(centre[0] - r, centre[1]), (centre[0] + r, centre[1])],
                  fill=rgba(NO_METRICS_RGB), width=2)
        draw.line([(centre[0], centre[1] - r), (centre[0], centre[1] + r)],
                  fill=rgba(NO_METRICS_RGB), width=2)

    # 5. the camera: boresight cross at the principal point, FOV at the edges
    cx, cy = (record["principal_point_px"][0] / scale,
              record["principal_point_px"][1] / scale)
    gap, arm = 4, 14
    for (x0, y0, x1, y1) in ((cx - arm, cy, cx - gap, cy), (cx + gap, cy, cx + arm, cy),
                             (cx, cy - arm, cx, cy - gap), (cx, cy + gap, cx, cy + arm)):
        draw.line([(x0, y0), (x1, y1)], fill=rgba(CAMERA_RGB), width=1)
    hfov, vfov = field_of_view_deg(record)
    small = _font(13 if scale == 1 else 10)
    draw.text((cx + arm + 2, cy + 2), "boresight", fill=rgba(CAMERA_RGB), font=small)
    draw.text((cx - 40, h - 18), f"HFOV {hfov:.1f} deg", fill=rgba(CAMERA_RGB), font=small)
    draw.text((4, cy - 14), f"VFOV\n{vfov:.1f}", fill=rgba(CAMERA_RGB), font=small)
    for (x0, y0, x1, y1) in ((cx, 0, cx, 6), (cx, h - 7, cx, h - 1), (0, cy, 6, cy),
                             (w - 7, cy, w - 1, cy)):
        draw.line([(x0, y0), (x1, y1)], fill=rgba(CAMERA_RGB), width=2)

    # 6. header
    lines = header_lines(record, manifest, scale, tag)
    info["header"] = lines
    font = _font(15 if scale == 1 else 11)
    line_h = (17 if scale == 1 else 12)
    draw.rectangle([0, 0, w, 4 + line_h * len(lines) + 2],
                   fill=rgba((0, 0, 0)) if layer is image else (0, 0, 0, min(alpha, 150)))
    for i, line in enumerate(lines):
        draw.text((4, 3 + line_h * i), line, fill=rgba(TEXT_RGB), font=font)
    legend = ("legend: ground wireframe depth-shaded (near bright) | horizon | "
              "track past/future | aircraft body + box | heading tick | "
              "boresight + FOV")
    draw.text((4, h - 52), legend, fill=rgba((160, 160, 160)), font=small)

    if layer is not image:
        image = Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
    return image, info


def _track(manifest: Dict):
    """The aircraft's whole track: one point per recorded instant (the
    manifest's own per-frame aircraft states, deduplicated), with its
    sample index for the past/future split."""
    track = {}
    for record in manifest.get("frames", []):
        a = record["aircraft"]
        track[record["sample_index"]] = (a["north_m"], a["east_m"], a["alt_m"],
                                         record["sample_index"])
    return [track[k] for k in sorted(track)]


def _ground(heightfield, scene_frame):
    if heightfield is not None and scene_frame is not None:
        return ("terrain", terrain_wireframe(heightfield, scene_frame))
    return ("flat", None)


def render_previews(manifest: Dict, out_dir, heightfield=None,
                    scene_frame=None,
                    terrain_elevation_m: float = 0.0,
                    max_frames: Optional[int] = None,
                    scale: int = PREVIEW_SCALE_DEFAULT,
                    contact_sheets: bool = True) -> PreviewSet:
    """Write one preview PNG per frame record (full resolution by
    default; ``scale=N`` for 1/N) and a per-camera contact sheet;
    returns the paths as a :class:`PreviewSet` carrying the measured
    seconds per frame.

    ``scene_frame`` is needed only when a heightfield is given (to
    express the raster in the manifest's local frame).
    """
    scale = validated_scale(scale)
    ground = _ground(heightfield, scene_frame)
    track_points = _track(manifest)
    written = PreviewSet()
    written.scale = scale
    frames = manifest.get("frames", [])
    if max_frames is not None:
        frames = frames[:max_frames]
    per_camera: Dict[str, List[Path]] = {}
    started = time.perf_counter()
    for record in frames:
        image, info = draw_preview(record, manifest, ground, scale=scale,
                                   track_points=track_points,
                                   terrain_elevation_m=terrain_elevation_m)
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
                                     / f"{camera_id}.png", scale=scale)
            written.contact_sheets[camera_id] = sheet
    return written


def contact_sheet(manifest: Dict, camera_id: str, paths: Sequence[Path],
                  out_path, scale: int = 1,
                  thumb_width: int = CONTACT_THUMB_WIDTH_PX,
                  columns: int = CONTACT_COLUMNS):
    """A grid of every preview of one camera, index and time under each,
    a title row with camera id, preset, schedule basis and count.
    Returns ``(path, info)``; info["thumbnails"] is the count laid out."""
    from PIL import Image, ImageDraw

    block = _camera_block(manifest, camera_id)
    records = {r["index"]: r for r in manifest.get("frames", [])
               if r["camera_id"] == camera_id}
    paths = list(paths)
    count = len(paths)
    cols = max(1, min(columns, count))
    rows = max(1, math.ceil(count / cols))
    first = Image.open(paths[0]) if paths else None
    aspect = (first.height / first.width) if first else 9 / 16
    tw = thumb_width
    th = int(round(tw * aspect))
    margin, label_h, title_h = 6, 18, 28
    width = margin + cols * (tw + margin)
    height = title_h + margin + rows * (th + label_h + margin)
    sheet = Image.new("RGB", (width, height), BACKGROUND_RGB)
    draw = ImageDraw.Draw(sheet)
    font = _font(15)
    small = _font(12)
    thumb_scale = (first.width / tw) if first else 1.0
    total = block.get("capture_count", len(records))
    title = (f"{camera_id}  preset {block.get('preset', '?')}  schedule: "
             f"{block.get('schedule_basis', '?')}  {count} of {total} frames"
             f"  (thumbnails at 1/{thumb_scale * scale:g} of "
             f"{int(records[0]['width_px']) if records else '?'}x"
             f"{int(records[0]['height_px']) if records else '?'})")
    draw.text((margin, 6), title, fill=TEXT_RGB, font=font)
    for k, path in enumerate(paths):
        r, c = divmod(k, cols)
        x = margin + c * (tw + margin)
        y = title_h + margin + r * (th + label_h + margin)
        thumb = Image.open(path).convert("RGB")
        thumb.thumbnail((tw, th))
        sheet.paste(thumb, (x, y))
        index = int(path.stem.split("_")[-1])
        record = records.get(index)
        label = (f"#{index}  t={record['t_s']:.3f} s" if record else f"#{index}")
        draw.text((x, y + th + 2), label, fill=TEXT_RGB, font=small)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path, {"thumbnails": count, "columns": cols, "rows": rows,
                      "thumb_size": (tw, th), "size": (width, height)}


def render_overlays(manifest: Dict, capture_dir, heightfield=None,
                    scene_frame=None, terrain_elevation_m: float = 0.0,
                    alpha: int = 200) -> OverlaySet:
    """For every frame record whose rendered PNG exists at
    ``capture_dir / record["file"]``, draw the reprojected geometry
    (terrain wireframe or grid, horizon, track, aircraft body and box,
    boresight, header) as a translucent layer over the frame and write
    ``capture_dir / overlays / <camera_id> / NNNN.png`` at the frame's
    own size. A frame whose size differs from its record is drawn at
    the record's intrinsics scaled to the PNG and says so in the header;
    the verifier, not the overlay, grades that mismatch."""
    from PIL import Image

    capture_dir = Path(capture_dir)
    ground = _ground(heightfield, scene_frame)
    track_points = _track(manifest)
    written = OverlaySet()
    started = time.perf_counter()
    for record in manifest.get("frames", []):
        frame_path = capture_dir / record["file"]
        if not frame_path.is_file():
            continue
        frame = Image.open(frame_path).convert("RGB")
        tag = "overlay: reprojected geometry over the rendered frame"
        scale = 1
        if frame.size != (int(record["width_px"]), int(record["height_px"])):
            ratio = int(record["width_px"]) / frame.size[0]
            scale = validated_scale(ratio) if float(ratio).is_integer() else 1
            tag += (f"; frame {frame.size[0]}x{frame.size[1]} differs from the "
                    f"record's {int(record['width_px'])}x{int(record['height_px'])}")
            if scale == 1 and frame.size != (int(record["width_px"]), int(record["height_px"])):
                frame = frame.resize((int(record["width_px"]), int(record["height_px"])))
        image, _ = draw_preview(record, manifest, ground, scale=scale,
                                image=frame, alpha=alpha, tag=tag,
                                track_points=track_points,
                                terrain_elevation_m=terrain_elevation_m)
        path = capture_dir / "overlays" / record["camera_id"] / f"{record['index']:04d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        written.append(path)
    elapsed = time.perf_counter() - started
    written.seconds_per_frame = elapsed / len(written) if written else 0.0
    return written
