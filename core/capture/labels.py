"""Per-frame ground-truth labels from geometry alone -- on every machine.

What a perception model is trained against is not the picture but the
label beside it, and the label has to be recoverable from the same
record that placed the camera. Everything here is computed from three
things the manifest already carries per frame -- the camera pose and
intrinsics, the aircraft's state at that instant -- plus the cited
airframe geometry (:mod:`core.capture.airframe`). No engine, no pixels:
these labels exist on a machine that has never rendered, exactly as the
manifest does, and the engine half (masks, depth, occlusion) is added
BESIDE them by the render commandlet, never in place of them.

Per frame, per camera::

    bbox_2d            [u0, v0, u1, v1] px, the airframe's overall-extents
                       box projected and CLIPPED to the image; null when
                       nothing of it is in frame
    bbox_2d_unclipped  the same box before clipping (may exceed the
                       image, or be null when a corner is behind the
                       camera -- a pinhole cannot bound a box that
                       straddles its own plane)
    truncation         1 - clipped area / unclipped area (0 = wholly in
                       frame, 1 = wholly out); null when unclipped is null
    in_frame           the clipped box has area and the aircraft's CG has
                       positive depth
    bbox_3d_camera     the box in CAMERA coordinates (x right, y down,
                       z forward, metres): centre, extents (length,
                       width, height), the airframe's body axes as rows
                       of a 3x3 (forward, right, down in camera coords),
                       and the eight corners in the fixed order
                       :meth:`Airframe.box_corners_body_m` documents
    keypoints          {name: {u, v, depth_m, in_frame, camera_xyz_m}}
                       for every keypoint the airframe carries;
                       ``in_frame`` means inside the image with positive
                       depth -- NOT unoccluded (the airframe hides its
                       own far wingtip; only the engine's mask can say)
    horizon            the datum plane's tangent horizon: dip_deg, an
                       EXACT polyline solved per image column (the
                       image of a constant-depression cone is a conic,
                       not a line), a least-squares line (a, b, c) with
                       its worst deviation from the exact curve, the
                       line's endpoints clipped to the image, and
                       in_frame

Projection is the manifest's documented pinhole model -- world point
P, camera C with axes from the quaternion, x_cam = right.(P-C), y_cam =
-up.(P-C), z_cam = forward.(P-C), u = cx + fx*x/z, v = cy + fy*y/z --
implemented here on the producer side; ``core.capture.verify`` carries
its own, from scratch, and grades these labels against it.

The horizon model, stated once: a spherical Earth of IUGG mean radius
6 371 008.8 m, no refraction, the horizon of the SCENE DATUM plane
(``terrain_elevation_m``) seen from the camera's height h above it --
dip = acos(R / (R + h)). It is the geometric horizon of a flat scene,
not the skyline: terrain in the way is not modelled here (that, again,
is the engine's mask).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .airframe import Airframe

#: IUGG 1980 mean Earth radius, metres.
EARTH_RADIUS_M = 6_371_008.8

Vec = Tuple[float, float, float]


# -- rotation and projection (producer side) -----------------------------

def camera_axes(q: Sequence[float]) -> Tuple[Vec, Vec, Vec]:
    """(forward, right, up) in (north, east, up) from a (w, x, y, z) NED
    quaternion -- the manifest's stated convention."""
    w, x, y, z = q
    fwd = (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y + w * z),
           -(2.0 * (x * z - w * y)))
    rgt = (2.0 * (x * y - w * z), 1.0 - 2.0 * (x * x + z * z),
           -(2.0 * (y * z + w * x)))
    dwn = (2.0 * (x * z + w * y), 2.0 * (y * z - w * x),
           1.0 - 2.0 * (x * x + y * y))
    up = (-dwn[0], -dwn[1], dwn[2])
    return fwd, rgt, up


def body_to_scene(body: Vec, state: Dict) -> Vec:
    """A body-frame offset (forward, right, down; metres about the CG)
    -> scene (north, east, up) at the aircraft's recorded attitude and
    position. The aerospace Z-Y'-X'' DCM, the pose solver's own."""
    bx, by, bz = body
    r = math.radians(float(state["roll_deg"]))
    p = math.radians(float(state["pitch_deg"]))
    y = math.radians(float(state["heading_deg"]))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    n = (cp * cy) * bx + (sr * sp * cy - cr * sy) * by \
        + (cr * sp * cy + sr * sy) * bz
    e = (cp * sy) * bx + (sr * sp * sy + cr * cy) * by \
        + (cr * sp * sy - sr * cy) * bz
    d = (-sp) * bx + (sr * cp) * by + (cr * cp) * bz
    return (float(state["north_m"]) + n, float(state["east_m"]) + e,
            float(state["alt_m"]) - d)


def to_camera(record: Dict, point: Vec, axes=None) -> Vec:
    """Scene point -> camera coordinates (x right, y down, z forward)."""
    forward, right, up = axes or camera_axes(record["quaternion_wxyz"])
    d = (point[0] - record["position_north_m"],
         point[1] - record["position_east_m"],
         point[2] - record["position_alt_m"])
    return (sum(a * b for a, b in zip(right, d)),
            -sum(a * b for a, b in zip(up, d)),
            sum(a * b for a, b in zip(forward, d)))


def to_pixel(record: Dict, cam: Vec) -> Optional[Tuple[float, float]]:
    """Camera coordinates -> (u, v), or None behind the camera."""
    if cam[2] <= 0.0:
        return None
    cx, cy = record["principal_point_px"]
    return (cx + record["fx_px"] * cam[0] / cam[2],
            cy + record["fy_px"] * cam[1] / cam[2])


def projection_matrices(record: Dict) -> Tuple[List[List[float]], List[List[float]]]:
    """(K, P) for a frame record: K the 3x3 intrinsic matrix and P the
    3x4 projection over homogeneous scene points (north, east, up, 1)
    -- ``pixel = (P p) / (P p)_z``. Exactly what to_camera + to_pixel
    compute, written as one matrix a consumer can multiply."""
    forward, right, up = camera_axes(record["quaternion_wxyz"])
    rows = [list(right), [-u for u in up], list(forward)]        # x, y, z
    centre = (float(record["position_north_m"]),
              float(record["position_east_m"]),
              float(record["position_alt_m"]))
    translation = [-sum(r[k] * centre[k] for k in range(3)) for r in rows]
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    cx, cy = (float(v) for v in record["principal_point_px"])
    K = [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]
    extrinsic = [rows[i] + [translation[i]] for i in range(3)]
    P = [[sum(K[i][k] * extrinsic[k][j] for k in range(3)) for j in range(4)]
         for i in range(3)]
    return K, P


def project_with_matrix(P: Sequence[Sequence[float]], point: Vec
                        ) -> Optional[Tuple[float, float]]:
    """(u, v) through a 3x4 projection matrix, or None behind the camera."""
    h = [sum(P[i][k] * point[k] for k in range(3)) + P[i][3] for i in range(3)]
    if h[2] <= 0.0:
        return None
    return (h[0] / h[2], h[1] / h[2])


# -- boxes ---------------------------------------------------------------

def _clip_box(box, width: float, height: float):
    u0, v0, u1, v1 = box
    c = (max(u0, 0.0), max(v0, 0.0), min(u1, width), min(v1, height))
    if c[2] <= c[0] or c[3] <= c[1]:
        return None
    return c


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def bbox_labels(record: Dict, state: Dict, airframe: Airframe, axes) -> Dict:
    width, height = float(record["width_px"]), float(record["height_px"])
    corners_body = airframe.box_corners_body_m()
    corners_cam = [to_camera(record, body_to_scene(c, state), axes)
                   for c in corners_body]
    cg_cam = to_camera(record, (float(state["north_m"]),
                                float(state["east_m"]),
                                float(state["alt_m"])), axes)
    pixels = [to_pixel(record, c) for c in corners_cam]
    unclipped = None
    clipped = None
    truncation = None
    if all(p is not None for p in pixels):
        us = [p[0] for p in pixels]
        vs = [p[1] for p in pixels]
        unclipped = (min(us), min(vs), max(us), max(vs))
        clipped = _clip_box(unclipped, width, height)
        full = _area(unclipped)
        truncation = (1.0 - (_area(clipped) / full if clipped else 0.0)
                      if full > 0.0 else 1.0)
    # In frame when the clipped box has area. (The CG's depth is not a
    # second condition: the CG is inside the box, so eight corners in
    # front of the camera put it there too -- a mutation guard on a
    # separate CG test proved it could never fire, and it went.)
    in_frame = clipped is not None

    # The airframe's body axes in camera coordinates: rows forward,
    # right, down -- the rotation a consumer needs to orient the box.
    origin = body_to_scene((0.0, 0.0, 0.0), state)
    axes_cam = []
    for unit in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        tip = body_to_scene(unit, state)
        o = to_camera(record, origin, axes)
        t = to_camera(record, tip, axes)
        axes_cam.append([t[0] - o[0], t[1] - o[1], t[2] - o[2]])
    box = airframe.box_body_m()
    centre_body = tuple((lo + hi) / 2.0 for lo, hi in
                        (box["forward"], box["right"], box["down"]))
    centre_cam = to_camera(record, body_to_scene(centre_body, state), axes)
    return {
        "bbox_2d": list(clipped) if clipped else None,
        "bbox_2d_unclipped": list(unclipped) if unclipped else None,
        "truncation": truncation,
        "in_frame": bool(in_frame),
        "bbox_3d_camera": {
            "centre_m": list(centre_cam),
            "extents_m": [box["forward"][1] - box["forward"][0],
                          box["right"][1] - box["right"][0],
                          box["down"][1] - box["down"][0]],
            "body_axes_in_camera": axes_cam,
            "corners_m": [list(c) for c in corners_cam],
            "cg_m": list(cg_cam),
        },
    }


# -- keypoints -----------------------------------------------------------

def keypoint_labels(record: Dict, state: Dict, airframe: Airframe,
                    axes) -> Dict[str, Dict]:
    width, height = float(record["width_px"]), float(record["height_px"])
    out: Dict[str, Dict] = {}
    for name, keypoint in airframe.keypoints.items():
        cam = to_camera(record, body_to_scene(keypoint.body_m, state), axes)
        pixel = to_pixel(record, cam)
        inside = (pixel is not None and 0.0 <= pixel[0] <= width
                  and 0.0 <= pixel[1] <= height)
        out[name] = {
            "u": pixel[0] if pixel else None,
            "v": pixel[1] if pixel else None,
            "depth_m": cam[2],
            "in_frame": bool(inside),
            "camera_xyz_m": list(cam),
        }
    return out


# -- horizon -------------------------------------------------------------

def horizon_dip_deg(height_above_datum_m: float,
                    radius_m: float = EARTH_RADIUS_M) -> float:
    h = max(0.0, float(height_above_datum_m))
    return math.degrees(math.acos(radius_m / (radius_m + h)))


def _clip_line_to_image(p, q, width, height):
    """Liang-Barsky clip of segment p-q to [0,w]x[0,h]; None if outside."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0), (dx, width - x0), (-dy, y0), (dy, height - y0)):
        if pk == 0.0:
            if qk < 0.0:
                return None
            continue
        t = qk / pk
        if pk < 0.0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    return ((x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy))


#: Image columns at which the horizon is solved exactly. The set of
#: directions at one depression angle is a CONE, and a pinhole's image
#: of a cone is a conic, not a line -- across a 54 deg lens at 1 km the
#: exact curve sags 2.7 px between the edges and the centre, and the
#: sag grows with altitude (dip goes as sqrt(h)). Nine columns give a
#: polyline a consumer can use as is; the fitted line and its worst
#: deviation are reported beside it so nobody mistakes one for the other.
HORIZON_COLUMNS = 9


def _horizon_v_at(record: Dict, axes, u: float, dip_deg: float) -> Optional[float]:
    """The image row where the ray through column ``u`` has elevation
    exactly -dip, or None when no ray in that column does.

    A ray through (u, v) points along f + x r - y u_ (camera forward,
    right, up in ENU; x = (u-cx)/fx, y = (v-cy)/fy). Its elevation is
    -dip when its up-component over its length equals -sin(dip):

        f_z + x r_z - y u_z = -s * sqrt(1 + x^2 + y^2),  s = sin(dip)

    which squares to a quadratic in y. The root kept is the one whose
    unsquared left side is <= 0 (the ray really points below level).
    """
    forward, right, up = axes
    cx, cy = record["principal_point_px"]
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    x = (u - cx) / fx
    s = math.sin(math.radians(dip_deg))
    A = forward[2] + x * right[2]
    B = -up[2]
    a = B * B - s * s
    b = 2.0 * A * B
    c = A * A - s * s * (1.0 + x * x)
    if abs(a) < 1e-12:
        if abs(b) < 1e-12:
            return None
        roots = [-c / b]
    else:
        disc = b * b - 4.0 * a * c
        if disc < 0.0:
            return None
        roots = [(-b - math.sqrt(disc)) / (2.0 * a),
                 (-b + math.sqrt(disc)) / (2.0 * a)]
    good = [y for y in roots if A + B * y <= 1e-12]
    if not good:
        return None
    # Two valid roots happen only when the camera looks nearly straight
    # down; take the one nearest the optical axis.
    y = min(good, key=abs)
    return cy + fy * y


def horizon_labels(record: Dict, terrain_elevation_m: float, axes) -> Dict:
    width, height = float(record["width_px"]), float(record["height_px"])
    h = float(record["position_alt_m"]) - float(terrain_elevation_m)
    dip = horizon_dip_deg(h)
    out = {"model": "spherical-earth datum-plane tangent horizon, "
                    "no refraction, no terrain; exact per column, the "
                    "fitted line is a convenience",
           "dip_deg": dip, "height_above_datum_m": h,
           "polyline_px": None, "line_abc": None,
           "line_max_deviation_px": None, "endpoints_px": None,
           "in_frame": False}
    columns = [width * i / (HORIZON_COLUMNS - 1) for i in range(HORIZON_COLUMNS)]
    points = []
    for u in columns:
        v = _horizon_v_at(record, axes, u, dip)
        if v is not None:
            points.append((u, v))
    if len(points) < 2:
        return out
    out["polyline_px"] = [list(p) for p in points]
    # Least-squares line v = m*u + k through the exact points, then
    # normalised to a*u + b*v + c = 0.
    n = len(points)
    su = sum(p[0] for p in points)
    sv = sum(p[1] for p in points)
    suu = sum(p[0] * p[0] for p in points)
    suv = sum(p[0] * p[1] for p in points)
    denom = n * suu - su * su
    if abs(denom) < 1e-9:
        return out
    m = (n * suv - su * sv) / denom
    k = (sv - m * su) / n
    norm = math.hypot(m, 1.0)
    out["line_abc"] = [m / norm, -1.0 / norm, k / norm]
    out["line_max_deviation_px"] = max(abs(m * u + k - v) for u, v in points)
    (u0, v0), (u1, v1) = points[0], points[-1]
    clipped = _clip_line_to_image((u0, v0), (u1, v1), width, height)
    if clipped is not None:
        out["endpoints_px"] = [list(clipped[0]), list(clipped[1])]
    out["in_frame"] = any(0.0 <= v <= height for u, v in points)
    return out


# -- the record ----------------------------------------------------------

def frame_labels(record: Dict, state: Dict, airframe: Airframe,
                 terrain_elevation_m: float) -> Dict:
    """Every headless label for one frame record."""
    axes = camera_axes(record["quaternion_wxyz"])
    labels = bbox_labels(record, state, airframe, axes)
    labels["keypoints"] = keypoint_labels(record, state, airframe, axes)
    labels["horizon"] = horizon_labels(record, terrain_elevation_m, axes)
    return labels


def conventions() -> Dict:
    """What a consumer needs to read these labels, in the manifest."""
    return {
        "camera_frame": "x right, y down, z forward, metres",
        "body_frame": "x forward, y right, z down, metres about the CG",
        "bbox_2d": "[u0, v0, u1, v1] px, top-left origin, clipped to the "
                   "image; the airframe's OVERALL extents box (nose-to-"
                   "tail x FDM wingspan x cited height from the gear "
                   "contacts up), not a tight hull",
        "truncation": "1 - clipped area / unclipped area",
        "keypoint_in_frame": "inside the image with positive depth; NOT "
                             "unoccluded",
        "corner_order": "for x in (aft, fwd), for y in (left, right), "
                        "for z in (top, bottom)",
        "horizon": f"spherical Earth R = {EARTH_RADIUS_M:.1f} m, no "
                   f"refraction, the scene datum plane's tangent horizon; "
                   f"terrain occlusion not modelled",
        "projection_matrix": "P = K [R | t], 3x4, over homogeneous scene "
                             "points (north, east, up, 1): pixel = (P p) / "
                             "(P p)_z; K = [[fx, 0, cx], [0, fy, cy], [0, 0, "
                             "1]]; the rows of R are the camera's right, "
                             "down and forward axes in scene coordinates; "
                             "t = -R c for the camera centre c. Per frame "
                             "as intrinsic_matrix and projection_matrix.",
        "projection": "u = cx + fx*x/z, v = cy + fy*y/z over the camera "
                      "frame above -- the manifest's documented model",
    }
