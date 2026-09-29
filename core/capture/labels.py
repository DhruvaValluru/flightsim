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

Manifest 6 (Phase 2, packages B + C) adds ``labels.objects[]`` beside
these keys: one record per labelled object of the frame in the same
shape (:func:`object_label_record`, contracts §3), the primary first
with exactly the values above, each traffic aircraft from its own
airframe and scripted track, the terrain with nulls. The engine-derived
keys of each record -- the tight box from the ID image, the visible
fraction from the alone pass, ``occluded_by``, the depth under the
mask -- are null WITH A BASIS here and are completed by
:func:`attach_engine_labels` from the render bundle, with numpy, after
a render; nothing in this module reads a pixel it cannot name a file
for, and nothing in it grades what it reads (that is the verifier's,
which re-derives every number from the same files).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
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


def _project_body_box(record: Dict, state: Dict, corners_body, axes):
    """Eight body-frame corners -> (clipped box, unclipped box,
    truncation, corners in camera coordinates). The boxes are None when
    a corner is behind the camera (a pinhole cannot bound a box that
    straddles its own plane); the clipped box is None when nothing of
    the unclipped one lies in the image."""
    width, height = float(record["width_px"]), float(record["height_px"])
    corners_cam = [to_camera(record, body_to_scene(c, state), axes)
                   for c in corners_body]
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
    return clipped, unclipped, truncation, corners_cam


def bbox_labels(record: Dict, state: Dict, airframe: Airframe, axes) -> Dict:
    corners_body = airframe.box_corners_body_m()
    clipped, unclipped, truncation, corners_cam = _project_body_box(
        record, state, corners_body, axes)
    cg_cam = to_camera(record, (float(state["north_m"]),
                                float(state["east_m"]),
                                float(state["alt_m"])), axes)
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
        # Manifest 6 (Phase 2, packages B + C): the per-object record and
        # the engine bundle it is completed from.
        "objects": "labels.objects[] lists every labelled object of the "
                   "frame, the primary airframe first with the same "
                   "bbox_2d / bbox_2d_unclipped / truncation / in_frame / "
                   "bbox_3d_camera / keypoints / horizon values as the "
                   "frame's labels; ids and int_ids resolve through the "
                   "manifest's objects[]",
        "id_mask": "frame_NNNN_mask.png is the ID image: an 8-bit grey PNG "
                   "whose pixel value is the object's int_id from "
                   "objects[] (0 = background); the primary airframe is "
                   "always int_id 1",
        "alone_pass": "frame_NNNN_alone_<int_id>.png is the ID pass "
                      "rendered with ONLY that object visible -- its "
                      "unoccluded footprint; one per aircraft object, none "
                      "for scene objects (terrain), whose visible_fraction "
                      "is therefore null",
        "depth_f32": "frame_NNNN_depth.f32 is raw little-endian float32, "
                     "row-major, width*height values, metres, +inf for "
                     "sky; the 16-bit PNG beside it is the same depth at "
                     "depth_scale_m",
        "visible_fraction": "pixels carrying the object's int_id in the ID "
                            "image / pixels in its alone pass -- geometric "
                            "occlusion only; atmospheric_transmittance is "
                            "analytic (Koschmieder along the CG ray) and is "
                            "never folded into it",
        "bbox_2d_tight": "[u0, v0, u1, v1] px around the pixels carrying the "
                         "object's int_id (pixel (x, y) covers [x, x+1) x "
                         "[y, y+1)); null when it has no pixels or no "
                         "engine bundle exists",
        "bbox_2d_hull": "the imported mesh's extent (mesh_manifest version "
                        ">= 3 mesh_extent_actor_m about the measured mesh "
                        "origin) as a body-frame box about the CG, "
                        "projected and clipped like bbox_2d; null with a "
                        "basis when no such manifest is on the producing "
                        "machine",
    }


# -- manifest 6: the per-object record (Phase 2, packages B + C) ----------
#
# Every labelled object of the frame gets a record of the same shape
# (contracts §3): the primary airframe first, with EXACTLY the values the
# frame's ``labels`` carries; each traffic aircraft from its own cited
# airframe and its scripted track; the terrain with nulls where a box
# has no meaning. The engine-derived keys -- ``bbox_2d_tight``,
# ``visible_fraction``, ``occluded_by``, ``depth_min_m``,
# ``depth_median_m`` -- are NULL WITH A BASIS at build time and are
# filled by :func:`attach_engine_labels` once a render bundle exists;
# a headless manifest never claims a pixel it has not seen.

#: Below this range the ID image's edges are not claimed to sub-pixel
#: accuracy: the stencil pass is aliasing-free but the mesh it draws is
#: the converter's decimated geometry, and beyond this range a pixel
#: spans more of the airframe than the converter's tolerance. A stated
#: claim boundary, not a tolerance (those live in verify.py).
NOT_CLAIMED_SUBPIXEL_RANGE_M = 8000.0
#: An object whose projected extent is under this many pixels is
#: recorded but its box/mask agreement is not claimed. Stated here as
#: 12 px; the verifier's own IoU schedule (core/capture/verify.py
#: BOX_IOU_MIN_PX) and contracts §3 stop at 16 px, so an object of 12
#: the verifier's IoU schedule (BOX_IOU_MIN_PX) and the export's
#: NOT_CLAIMED_EXTENT_PX stop at the same 16 px (contracts §3), so no
#: object is claimed by this record and graded by no check; a test pins
#: the three numbers to each other (the verifier stays independent: it
#: does not import this one).
NOT_CLAIMED_OBJECT_PX = 16
#: Koschmieder's constant: the extinction that leaves 2 % contrast at
#: the meteorological visibility, beta = 3.912 / V.
KOSCHMIEDER_K = 3.912
#: The keys :func:`attach_engine_labels` fills from the bundle.
ENGINE_LABEL_KEYS = ("bbox_2d_tight", "visible_fraction", "occluded_by",
                     "depth_min_m", "depth_median_m")
NO_BUNDLE_BASIS = ("no engine bundle read: bbox_2d_tight, visible_fraction, "
                   "occluded_by, depth_min_m and depth_median_m are null "
                   "until attach_engine_labels(run_dir) reads frames/<camera>/"
                   "render.json, the ID image, the depth .f32 and the alone "
                   "passes")

#: W4: what each aggregate object (core/capture/objects.py) gathers and
#: where its mask comes from -- the ``aggregate`` key of its label record
#: (:func:`aggregate_record` adds the legend codes from the taxonomy map).
AGGREGATE_RECORDS: Dict[str, Dict] = {
    "building:all": {
        "gathers": "every building of the scene as one object",
        "taxonomy": "building",
        "masks": ("the land-cover class image: the pixels whose WorldCover code the "
                  "taxonomy map calls building -> landcover_bbox_2d, landcover_pixels, "
                  "landcover_mask; the ID image carries its int_id only where an engine "
                  "drew a stated footprint set's LoD1 blocks (the stencil loop, W5)"),
        "per_instance_ids": ("none: the ID image is the 8-bit Custom Depth Stencil (at "
                             "most 255 ids) and a scene's buildings outnumber it; the "
                             "per-building ids of a footprint set live in its buildings "
                             "document"),
    },
    "vegetation:all": {
        "gathers": "every tree, shrub and mangrove of the scene as one object",
        "taxonomy": "vegetation",
        "masks": ("the land-cover class image: the pixels whose WorldCover code the "
                  "taxonomy map calls vegetation -> landcover_bbox_2d, landcover_pixels, "
                  "landcover_mask; the ID image carries its int_id only where an engine "
                  "drew foliage with the stencil (W5, Windows)"),
        "per_instance_ids": ("none: the 8-bit stencil cannot carry an id per tree, and no "
                             "tree has an identity in the land cover; no species, no season"),
    },
}


def aggregate_record(object_id: str) -> Optional[Dict]:
    """The ``aggregate`` block of an aggregate object's label record, with
    the legend codes its taxonomy word covers; None for any other object."""
    base = AGGREGATE_RECORDS.get(str(object_id))
    if base is None:
        return None
    from ..terrain.weightmaps import CLASS_OF_COVER

    return {**base, "codes": sorted(c for c, word in CLASS_OF_COVER.items()
                                    if word == base["taxonomy"])}


def hull_box_body_m(mesh_manifest: Optional[Dict], airframe: Airframe
                    ) -> Tuple[Optional[Dict[str, Tuple[float, float]]], str]:
    """The imported mesh's axis-aligned extent as a body-frame box about
    the CG -- ``{"forward": (aft, fwd), "right": (left, right), "down":
    (top, bottom)}`` -- with its basis, or ``(None, why)``.

    From a version >= 3 mesh manifest (contracts §0.1): the vertices are
    about the model origin, which sits at ``mesh_origin_actor_cm`` in the
    actor frame (+X forward, +Y right, +Z up, cm), whose origin is the
    JSBSim structural datum; the CG sits at (-x, y, z) * 2.54 of its
    structural inches in that same frame (the plugin's own mapping).
    Body = actor - CG with z flipped to DOWN. Nothing is measured here:
    the extent is what the converter measured from the vertices, and
    this is the frame change that puts it beside the labels' box.
    """
    if not isinstance(mesh_manifest, dict):
        return None, ("no mesh manifest on the producing machine; the hull "
                      "box needs the converter's measured mesh_extent_actor_m")
    version = mesh_manifest.get("version")
    extent = mesh_manifest.get("mesh_extent_actor_m")
    origin = mesh_manifest.get("mesh_origin_actor_cm")
    if not isinstance(version, (int, float)) or version < 3 or not extent or not origin:
        return None, (f"mesh manifest version {version!r} carries no measured "
                      f"mesh_extent_actor_m / mesh_origin_actor_cm (needs "
                      f"version 3, origin measured from vertices)")
    try:
        ox, oy, oz = (float(v) / 100.0 for v in origin)
        ex = tuple(float(v) for v in extent["x"])
        ey = tuple(float(v) for v in extent["y"])
        ez = tuple(float(v) for v in extent["z"])
    except (KeyError, TypeError, ValueError):
        return None, "mesh manifest extent/origin fields are malformed"
    cx, cy, cz = airframe.cg_structural_in
    cg = (-cx * 0.0254, cy * 0.0254, cz * 0.0254)          # actor frame, m
    forward = (ox + ex[0] - cg[0], ox + ex[1] - cg[0])
    right = (oy + ey[0] - cg[1], oy + ey[1] - cg[1])
    # actor z is UP; body z is DOWN: top = -(max z), bottom = -(min z).
    down = (-(oz + ez[1] - cg[2]), -(oz + ez[0] - cg[2]))
    basis = (f"mesh_manifest version {int(version)} mesh_extent_actor_m about "
             f"mesh_origin_actor_cm ({mesh_manifest.get('mesh_origin_basis', '?')}), "
             f"re-based on the CG (-x, y, z) * 2.54 of cg_structural_in")
    return {"forward": forward, "right": right, "down": down}, basis


def _box_corners(box: Dict[str, Tuple[float, float]]) -> List[Vec]:
    return [(x, y, z) for x in box["forward"] for y in box["right"]
            for z in box["down"]]


def atmospheric_transmittance(range_m: float, randomization: Optional[Dict]
                              ) -> Tuple[float, str]:
    """Koschmieder transmittance exp(-beta * range) along the CG ray,
    with its basis. beta = 3.912 / (1000 * visibility_km) when the
    randomisation block states a visibility, else the block's
    ``fog_density`` (1/m, the existing randomisation unit), else 1.0 --
    stated as unmodelled, never assumed clear."""
    block = randomization or {}
    visibility = block.get("visibility_km")
    if isinstance(visibility, (int, float)) and visibility > 0:
        beta = KOSCHMIEDER_K / (1000.0 * float(visibility))
        basis = (f"Koschmieder exp(-3.912 / (1000 * visibility_km) * range) "
                 f"with visibility_km {float(visibility):g} from the "
                 f"randomisation block, range = |CG| in the camera frame")
    elif isinstance(block.get("fog_density"), (int, float)):
        beta = float(block["fog_density"])
        basis = (f"exp(-fog_density * range) with fog_density {beta:g} 1/m "
                 f"from the randomisation block, range = |CG| in the "
                 f"camera frame")
    else:
        return 1.0, ("no visibility or fog density stated by the spec: 1.0 "
                     "is NOT a measurement; the render host's default fog is "
                     "not modelled here")
    return math.exp(-beta * max(0.0, float(range_m))), basis


def not_claimed_for(obj_class: str, alone_pass: bool) -> List[str]:
    out = [f"subpixel_mask_accuracy_beyond_range_m: {NOT_CLAIMED_SUBPIXEL_RANGE_M:g}",
           f"objects_under_px: {NOT_CLAIMED_OBJECT_PX}"]
    if not alone_pass:
        out.append(f"visible_fraction: no alone pass for a {obj_class} "
                   f"object, so occlusion of it is not measured")
    out.append("atmospheric_transmittance: analytic (Koschmieder), never "
               "measured from pixels; clouds and precipitation are not in it")
    return out


def object_label_record(obj, record: Dict, state: Optional[Dict],
                        airframe: Optional[Airframe], axes,
                        terrain_elevation_m: float,
                        randomization: Optional[Dict] = None,
                        mesh_manifest: Optional[Dict] = None,
                        primary: bool = False,
                        base_labels: Optional[Dict] = None) -> Dict:
    """One ``labels.objects[]`` entry (contracts §3).

    For an aircraft object ``state`` is its CG state at the frame instant
    and ``airframe`` its cited geometry; the geometric keys are computed
    exactly as the frame's own labels are (for the primary they are
    COPIED from ``base_labels`` so the two can never disagree). For a
    scene object (terrain) both are None and every box is null.
    """
    entry: Dict = {"id": obj.id, "int_id": obj.int_id, "class_id": obj.class_id}
    aircraft = airframe is not None and state is not None
    basis: Dict[str, str] = {}
    if aircraft:
        labels = base_labels if (primary and base_labels is not None) else None
        if labels is None:
            labels = bbox_labels(record, state, airframe, axes)
            labels["keypoints"] = keypoint_labels(record, state, airframe, axes)
            labels["horizon"] = (horizon_labels(record, terrain_elevation_m, axes)
                                 if primary else None)
        entry.update({
            "bbox_2d": labels["bbox_2d"],
            "bbox_2d_unclipped": labels["bbox_2d_unclipped"],
            "truncation": labels["truncation"],
            "in_frame": labels["in_frame"],
        })
        hull, hull_basis = hull_box_body_m(mesh_manifest, airframe)
        basis["bbox_2d_hull"] = hull_basis
        if hull is not None:
            clipped, _, _, _ = _project_body_box(record, state, _box_corners(hull), axes)
            entry["bbox_2d_hull"] = list(clipped) if clipped else None
        else:
            entry["bbox_2d_hull"] = None
        cg = labels["bbox_3d_camera"]["cg_m"]
        range_m = math.sqrt(sum(float(c) * float(c) for c in cg))
        transmittance, t_basis = atmospheric_transmittance(range_m, randomization)
        basis["atmospheric_transmittance"] = t_basis
        entry["atmospheric_transmittance"] = transmittance
        entry["depth_projected_m"] = float(cg[2])
        entry["bbox_3d_camera"] = labels["bbox_3d_camera"]
        entry["keypoints"] = labels.get("keypoints", {})
        entry["horizon"] = labels.get("horizon") if primary else None
        entry["not_claimed"] = not_claimed_for(obj.class_name, alone_pass=True)
    else:
        entry.update({
            "bbox_2d": None, "bbox_2d_unclipped": None, "truncation": None,
            "in_frame": None, "bbox_2d_hull": None,
            "atmospheric_transmittance": None, "depth_projected_m": None,
            "bbox_3d_camera": None, "keypoints": {}, "horizon": None,
            "not_claimed": not_claimed_for(obj.class_name, alone_pass=False),
        })
        basis["bbox_2d_hull"] = "a scene object has no airframe hull"
        basis["atmospheric_transmittance"] = ("not computed for a scene "
                                              "object (no single range)")
        # W4: an aggregate (building:all, vegetation:all) says what it
        # gathers and where its mask comes from; absent on every other object.
        aggregate = aggregate_record(str(obj.id))
        if aggregate is not None:
            entry["aggregate"] = aggregate
    for key in ENGINE_LABEL_KEYS:
        entry[key] = [] if key == "occluded_by" else None
    basis["engine"] = NO_BUNDLE_BASIS
    entry["basis"] = basis
    return entry


# -- the engine bundle, read back with numpy ------------------------------

def _read_id_png(path: Path):
    """An 8-bit grey PNG as a (h, w) uint8 array (16-bit is read too;
    the values are the object ints either way)."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        array = np.asarray(image)
    if array.ndim != 2:
        raise ValueError(f"{path.name}: an ID image is single-channel, "
                         f"got shape {array.shape}")
    return array


def read_depth_f32(path: Path, width: int, height: int):
    """``frame_NNNN_depth.f32`` -> (h, w) float32 metres, +inf for sky.
    Refuses a file whose size is not width*height*4: a truncated depth
    image would silently label every pixel below the cut as sky."""
    import numpy as np

    raw = np.fromfile(path, dtype="<f4")
    if raw.size != width * height:
        raise ValueError(
            f"{path.name}: {raw.size} float32 values for a {width}x{height} "
            f"frame (expected {width * height}; file is {path.stat().st_size} "
            f"bytes, not {width * height * 4})")
    return raw.reshape(height, width)


def read_depth_png(path: Path, scale_m: float, saturation_m: float):
    """The viewer-friendly 16-bit depth as float metres, +inf where it
    saturated (the producer wrote 65535 for sky)."""
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        array = np.asarray(image).astype("float64")
    metres = array * float(scale_m)
    metres[array >= 65535] = float("inf")
    return metres


# -- I6 (gap S3): the ground-truth passes beside the label bundle --------------
#
# The commandlet's -passes=normal,velocity,albedo writes, per frame:
#
#   frame_NNNN_normal.png   16-bit RGBA PNG, R,G,B = (n * 0.5 + 0.5) * 65535
#                           for the unit normal n in the SCENE frame
#                           (north, east, up); A = 65535
#   frame_NNNN_flow.f32     little-endian float32 pairs (dx, dy), row-major,
#                           width*height pairs, PIXELS, screen +x right and
#                           +y down: the displacement of the surface at this
#                           pixel from the previous captured frame to this
#                           one; the first frame of a camera is all zeros and
#                           its record says flow_first_frame: true
#   frame_NNNN_albedo.png   16-bit RGBA PNG, R,G,B = linear base colour in
#                           [0, 1] * 65535; A = 65535
#
# and names them on the frame record (normal_png / flow_f32 / albedo_png,
# null when the pass is off) with the encodings under render.json's root
# "passes". The readers here decode exactly that and nothing else; the
# 16-bit PNGs go through rasterio because Pillow returns a 16-bit RGB PNG
# as 8-bit (measured here: mode RGB, uint8), which would throw away the
# low byte of every normal. What is NOT claimed: that any file was ever
# written by an engine -- the commandlet is uncompiled off Windows -- and
# that a value in a file is right; the verifier grades that
# (normals_vs_depth, flow_vs_motion, albedo_range) from its own readers.

#: The encoding of a signed unit vector in the normal PNG: stored =
#: (n * NORMAL_ENCODE_SCALE + NORMAL_ENCODE_OFFSET) * PNG16_MAX. The same
#: numbers as the commandlet's RenderPassNormalEncodeScale / Offset.
NORMAL_ENCODE_SCALE = 0.5
NORMAL_ENCODE_OFFSET = 0.5
PNG16_MAX = 65535

#: The record keys the passes add to a render.json frame record, by pass
#: word, and the file suffix each declares.
PASS_RECORD_KEYS = {"normal": "normal_png", "velocity": "flow_f32",
                    "albedo": "albedo_png"}
PASS_FILE_SUFFIXES = {"normal": "_normal.png", "velocity": "_flow.f32",
                      "albedo": "_albedo.png"}


def read_rgb16_png(path: Path):
    """A 16-bit RGB or RGBA PNG as an (h, w, 3) uint16 array (alpha
    dropped). Refuses a file that is not 16-bit or has fewer than three
    channels: an 8-bit file here is one that lost its low byte somewhere."""
    import numpy as np
    import rasterio
    from rasterio.errors import RasterioIOError

    try:
        with rasterio.open(path) as dataset:
            if dataset.count < 3:
                raise ValueError(f"{path.name}: {dataset.count} channel(s); a "
                                 f"normal or albedo image has three")
            if dataset.dtypes[0] != "uint16":
                raise ValueError(f"{path.name}: {dataset.dtypes[0]} samples; the "
                                 f"pass files are 16-bit")
            planes = dataset.read((1, 2, 3))
    except RasterioIOError as exc:
        raise OSError(f"{path.name}: {exc}") from exc
    return np.ascontiguousarray(np.transpose(planes, (1, 2, 0))).astype(np.uint16)


def write_rgb16_png(path: Path, rgb) -> Path:
    """An (h, w, 3) uint16 array as a 16-bit RGB PNG (filter 0, zlib) --
    the writer synthetic bundles and tests use; the engine writes its
    own through UE's PNG wrapper (RGBA). Round-trips through
    :func:`read_rgb16_png` bit for bit (measured here)."""
    import struct
    import zlib

    import numpy as np

    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint16:
        raise ValueError(f"write_rgb16_png wants an (h, w, 3) uint16 array, got "
                         f"{rgb.shape} {rgb.dtype}")
    height, width, _ = rgb.shape
    rows = rgb.astype(">u2").tobytes()
    stride = width * 6
    raw = b"".join(b"\x00" + rows[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))

    header = struct.pack(">IIBBBBB", width, height, 16, 2, 0, 0, 0)
    path = Path(path)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    return path


def encode_normals(normals):
    """(h, w, 3) float unit normals in [-1, 1] -> the uint16 the PNG
    stores, exactly the commandlet's rounding."""
    import numpy as np

    scaled = (np.asarray(normals, dtype=np.float64) * NORMAL_ENCODE_SCALE
              + NORMAL_ENCODE_OFFSET) * PNG16_MAX
    return np.clip(np.rint(scaled), 0, PNG16_MAX).astype(np.uint16)


def read_normal_png(path: Path):
    """``frame_NNNN_normal.png`` -> (h, w, 3) float32 normals in the
    scene frame (north, east, up), each channel v / 65535 * 2 - 1. Not
    re-normalised: a reader that wants unit length checks it (the
    verifier does, and reports the pixels that are not)."""
    import numpy as np

    stored = read_rgb16_png(Path(path)).astype(np.float32) / PNG16_MAX
    return (stored - NORMAL_ENCODE_OFFSET) / NORMAL_ENCODE_SCALE


def read_flow_f32(path: Path, width: int, height: int):
    """``frame_NNNN_flow.f32`` -> (h, w, 2) float32 (dx, dy) pixels.
    Refuses a file whose size is not width*height*8: a truncated flow
    would read as zero motion below the cut."""
    import numpy as np

    path = Path(path)
    raw = np.fromfile(path, dtype="<f4")
    if raw.size != width * height * 2:
        raise ValueError(
            f"{path.name}: {raw.size} float32 values for a {width}x{height} "
            f"flow (expected {width * height * 2}; file is "
            f"{path.stat().st_size} bytes, not {width * height * 8})")
    return raw.reshape(height, width, 2)


def read_albedo_png(path: Path):
    """``frame_NNNN_albedo.png`` -> (h, w, 3) float32 linear base colour
    in [0, 1] (v / 65535)."""
    import numpy as np

    return read_rgb16_png(Path(path)).astype(np.float32) / PNG16_MAX


def passes_declared(engine_record: Dict) -> Dict[str, Optional[str]]:
    """``{pass word: file name or None}`` from a render.json frame
    record's normal_png / flow_f32 / albedo_png keys. A record written
    before the passes existed has none of the keys and declares none."""
    out: Dict[str, Optional[str]] = {}
    for word, key in PASS_RECORD_KEYS.items():
        value = engine_record.get(key)
        out[word] = str(value) if isinstance(value, str) and value else None
    return out


def passes_record(files_per_frame: Sequence[int], words: Sequence[str]):
    """The ``AppliedVariable`` for the passes a bundle carried
    (ADVANCEMENTS_CONTRACTS rule 0), from what :func:`attach_engine_labels`
    counted: the pass words seen and the number of pass files each
    frame declared. The null test is with-versus-without as measured on
    this bundle: the mean pass files per frame the records declare
    against the zero a commandlet run without ``-passes=`` declares (the
    writes sit under the pass switches, pinned by source test; a record
    without the keys is what every pre-I6 bundle carries). Not claimed:
    that the files' contents are right (the verifier's three checks),
    or that any engine wrote them (uncompiled here)."""
    from ..records import AppliedVariable, NullTest

    frames = len(files_per_frame)
    mean_files = (sum(files_per_frame) / frames) if frames else 0.0
    return AppliedVariable(
        name="render.passes",
        value=list(words),
        unit="pass",
        source="user",
        model_name=("engine post-process passes: SceneTexture WorldNormal / Velocity / "
               "BaseColor through tonemapper-replacing materials, AA-free "
               "(FlightSimRenderCommandlet.cpp -passes=)"),
        parameters={
            "normal_encoding": "(n * 0.5 + 0.5) * 65535, scene frame (north, east, up)",
            "flow_encoding": "float32 (dx, dy) pixels, +x right, +y down, previous "
                             "captured frame to this one, first frame zeros",
            "albedo_encoding": "linear base colour [0, 1] * 65535",
            "frames_with_passes": int(sum(1 for n in files_per_frame if n > 0)),
            "frames": frames,
        },
        references=("UE 5.7 ESceneTextureId PPI_WorldNormal, PPI_Velocity, PPI_BaseColor",
                    "docs/PHASE3_GAP_ANALYSIS.md S3"),
        properties_written=("r.Velocity.ForceOutput=1 when velocity is on",),
        telemetry_columns=(),
        frame_keys=("labels.passes.normal", "labels.passes.velocity",
                    "labels.passes.albedo"),
        null_test=NullTest(
            quantity="ground-truth pass files declared per frame", unit="file",
            with_value=float(mean_files), without_value=0.0, threshold=1.0,
            note="without -passes= the record carries no normal_png / flow_f32 / "
                 "albedo_png key (the writes are under the pass switches; source "
                 "pin in tests/test_gate6_visual.py)"),
        not_claimed=("file contents (graded by verify.normals_vs_depth, "
                     "flow_vs_motion, albedo_range)",
                     "engine execution (the commandlet is uncompiled off Windows)",
                     "the velocity's time base equals the capture interval",
                     "sun invariance of the albedo (Gate 6 clause, Windows only)"),
    )


def measure_object(mask, depth, int_id: int, alone=None) -> Dict:
    """What the bundle says about ONE object: pixel counts, the tight
    box, the visible fraction, who occludes it and the depth under it.

    ``mask`` is the ID image, ``alone`` that object's alone pass (or
    None: no alone pass, so visible_fraction and occluded_by are not
    measured), ``depth`` float metres or None. Integers out are Python
    ints and floats, never numpy scalars, so the record serialises.
    """
    import numpy as np

    hit = mask == int_id
    pixels = int(np.count_nonzero(hit))
    out: Dict = {"pixels": pixels, "pixels_alone": None,
                 "bbox_2d_tight": None, "visible_fraction": None,
                 "occluded_by": [], "depth_min_m": None, "depth_median_m": None}
    if pixels:
        ys, xs = np.nonzero(hit)
        # Pixel (x, y) covers [x, x+1) x [y, y+1): the box's far edges
        # are one past the last pixel, in the same continuous pixel
        # units as bbox_2d.
        out["bbox_2d_tight"] = [float(xs.min()), float(ys.min()),
                                float(xs.max()) + 1.0, float(ys.max()) + 1.0]
        if depth is not None:
            under = depth[hit]
            finite = under[np.isfinite(under)]
            if finite.size:
                out["depth_min_m"] = float(finite.min())
                out["depth_median_m"] = float(np.median(finite))
    if alone is not None:
        footprint = alone == int_id
        pixels_alone = int(np.count_nonzero(footprint))
        out["pixels_alone"] = pixels_alone
        if pixels_alone > 0:
            out["visible_fraction"] = pixels / pixels_alone
            others = np.unique(mask[footprint])
            out["occluded_by"] = [int(v) for v in others
                                  if int(v) not in (0, int_id)]
    return out


# -- S2: the amodal box and mask, from the alone pass ------------------------------
#
# An aircraft object's AMODAL extent is its silhouette with nothing in
# front of it: exactly the engine's alone pass (the object drawn by
# itself from the frame's pose, AA-free). Per aircraft object of a frame
# whose camera asks for ``amodal`` (cameras[i].passes):
#
#   amodal_bbox_2d   the TIGHT box of the alone-pass pixels, [u0, v0, u1,
#                    v1] in the bbox_2d_tight convention (far edges one
#                    past the last pixel); null when the alone pass holds
#                    none of the object (wholly out of frame)
#   amodal_mask      {file, int_id, pixels, encoding}: the alone pass is
#                    the mask, its pixels equal to int_id
#   amodal_ratio     amodal pixels / visible pixels (= 1 / visible_fraction);
#                    null when nothing of it is visible
#   basis.amodal     "alone pass", the files, and what is not claimed
#
# A frame asking for amodal whose bundle has no alone pass for an
# aircraft object records the refusal ``annotation.amodal`` by name in
# that object's basis (the three keys null); nothing is inferred from the
# visible mask. Absent-canonical: a frame that does not ask carries none
# of the keys. Amodal masks are for aircraft only (the terrain has no
# alone pass); the verifier's amodal_contains_visible grades them.

AMODAL_BASIS = "alone pass"


def amodal_labels(alone, mask, int_id: int, alone_file: Optional[str]) -> Dict:
    """The amodal keys of one aircraft object from its alone pass;
    refuses ``annotation.amodal`` (:class:`core.capture.passes.PassError`)
    when there is no alone pass to take them from."""
    import numpy as np

    from .passes import PassError

    if alone is None or not alone_file:
        raise PassError("annotation.amodal",
                        f"object {int_id} has no alone pass in the bundle; its amodal box "
                        f"and mask are the alone pass and are not inferred from the "
                        f"visible pixels")
    footprint = alone == int_id
    pixels_alone = int(np.count_nonzero(footprint))
    pixels = int(np.count_nonzero(mask == int_id))
    box = None
    if pixels_alone:
        ys, xs = np.nonzero(footprint)
        box = [float(xs.min()), float(ys.min()), float(xs.max()) + 1.0, float(ys.max()) + 1.0]
    return {
        "amodal_bbox_2d": box,
        "amodal_mask": {"file": str(alone_file), "int_id": int(int_id), "pixels": pixels_alone,
                        "encoding": "the alone pass: pixels equal to int_id"},
        "amodal_ratio": (pixels_alone / pixels) if pixels else None,
        "basis": {"basis": AMODAL_BASIS, "files": {"alone": str(alone_file)},
                  "visible_pixels": pixels, "amodal_pixels": pixels_alone,
                  "not_claimed": "amodal extents of non-aircraft objects (no alone pass)"},
    }


# -- W4: the land-cover label per frame ----------------------------------------------
#
# A frame's LAND-COVER IMAGE is the bake's WorldCover class grid seen
# through the frame's own depth: every pixel with a finite positive depth
# is carried back into the scene along its own ray (the pinhole above,
# pixel (u, v) through its centre (u + 0.5, v + 0.5), the depth planar
# along the camera's forward axis, as depth_f32 states it), the scene
# point is placed in the frame's projected CRS (x = origin_x + east,
# y = origin_y + north), and the pixel takes the class code of the bake
# cell holding that point: cell (row, col) = (floor((origin_y - y) / c),
# floor((x - origin_x) / c)) for the grid's upper-left origin and cell
# size c -- a cell is its area, as core/terrain/landcover.py counts it.
#
#   frame_NNNN_landcover.png   8-bit grey PNG beside the frame: the
#                              WorldCover legend code per pixel; 0 is
#                              NODATA -- sky (no finite depth), off the
#                              bake, a cell the source had no data for,
#                              or a pixel the ID image gives an aircraft
#                              (an airframe is not ground cover)
#
# The legend (codes, keys, titles, the taxonomy word of each) rides in the
# manifest's top-level ``landcover`` block (:func:`manifest_landcover_block`);
# per frame ``labels.landcover`` carries the file, its sha256, the fractions
# in view (per legend class and per taxonomy word, over all the frame's
# pixels, nodata stated beside them), the dominant class, and -- when the
# engine's land-cover ID pass exists (``labels.landcover_png`` on the
# render.json record; M_LandcoverID, W5, a Windows step) -- the fraction of
# this image's labelled pixels the engine pass agrees with. The aggregates
# (building:all, vegetation:all) take their box and mask from this image.
#
# Not claimed: no per-instance ids; no species or season; the classes are
# WorldCover's own (76.7 % overall accuracy per its manual), 2021, and
# not re-validated; the engine's pass is W5's, uncompiled here; a pixel
# carries the class of the bake cell under its surface point, not of what
# the engine draws there (the agreement measures that, when it exists).

#: The land-cover image's suffix beside a frame, and its nodata code.
LANDCOVER_SUFFIX = "_landcover.png"
LANDCOVER_NODATA = 0
#: The render.json frame record's ``labels`` key naming the engine's
#: land-cover ID pass (W5: M_LandcoverID, the class code per pixel from
#: the Landscape layers; 8-bit, the legend codes, 0 where no layer).
ENGINE_LANDCOVER_KEY = "landcover_png"
#: The agreement the engine pass must reach against this image (the
#: blueprint's Windows clause; graded by verify.landcover_vs_geometry).
LANDCOVER_AGREEMENT_MIN = 0.95
LANDCOVER_METHOD = ("the frame's depth carried back along each pixel's own ray into "
                    "the scene, placed on the bake's WorldCover class grid; nodata for "
                    "sky, off the bake, a nodata cell, or an aircraft pixel in the ID image")
LANDCOVER_NOT_CLAIMED = (
    "no per-instance ids: building:all and vegetation:all are one object each (the "
    "8-bit stencil)",
    "no species and no season: the WorldCover classes only",
    "the classes are the product's estimate (76.7 +/- 0.5 % overall accuracy per its "
    "manual), 2021, not re-validated here",
    "the engine's land-cover ID pass is W5's Windows step (M_LandcoverID), uncompiled here; "
    "an agreement is recorded only when a bundle carries that pass",
)


class LandcoverLabelError(Exception):
    """The land-cover image of a frame cannot be made or trusted; named
    ``annotation.landcover`` (a class map missing or changed since the
    manifest named it, a grid in another CRS than the frame, a code
    outside the legend)."""

    constraint = "annotation.landcover"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"annotation.landcover: {message}")


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def landcover_document_for(terrain) -> Optional[Path]:
    """The ``landcover.json`` beside a bake (core/terrain/landcover.py
    ``scene_dir_for``), or None for no terrain or no land cover."""
    if not terrain:
        return None
    from ..terrain.landcover import scene_dir_for

    path = scene_dir_for(Path(str(terrain))) / "landcover.json"
    return path if path.is_file() else None


def landcover_legend() -> List[Dict]:
    """The legend the image's codes resolve through: nodata first, then
    WorldCover's eleven classes, each with its taxonomy word."""
    from ..terrain.landcover import LEGEND
    from ..terrain.weightmaps import CLASS_OF_COVER

    return ([{"code": LANDCOVER_NODATA, "key": "nodata", "title": "No data", "taxonomy": None,
              "rgb": [0, 0, 0]}]
            + [{"code": c.code, "key": c.key, "title": c.title,
                "taxonomy": CLASS_OF_COVER[c.code], "rgb": list(c.rgb)} for c in LEGEND])


def manifest_landcover_block(document) -> Optional[Dict]:
    """The capture manifest's ``landcover`` block from a bake's
    ``landcover.json``: the dataset, tiles and digests, the class map
    (path + sha256) and grid the images are cut from, the legend, the
    image's encoding and cell rule, the aggregates' codes, the engine
    pass's key. None for no document (absent-canonical: a scene without
    land cover carries no key)."""
    if document is None:
        return None
    path = Path(str(document))
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    grid = doc.get("grid") or {}
    class_map = doc.get("class_map") or {}
    source = doc.get("source") or {}
    tiles = source.get("tiles") or {}
    return {
        "dataset": doc.get("dataset"),
        "license": doc.get("license"),
        "attribution": doc.get("attribution"),
        "citation": doc.get("citation"),
        "document": str(path),
        "document_sha256": _sha256_file(path),
        "source_sha256": doc.get("sha256"),
        "tiles": sorted(str(t) for t in tiles),
        "crop": source.get("crop"),
        "class_map": {"file": str(path.parent / str(class_map.get("file", "class_map.png"))),
                      "sha256": class_map.get("sha256"),
                      "encoding": class_map.get("encoding")},
        "grid": {key: grid.get(key) for key in ("crs", "origin_x_m", "origin_y_m",
                                                "cell_size_m", "width", "height",
                                                "bake_sha256")},
        "fractions": doc.get("fractions"),
        "dominant_class": doc.get("dominant_class"),
        "legend": landcover_legend(),
        "nodata": LANDCOVER_NODATA,
        "image": {"suffix": LANDCOVER_SUFFIX,
                  "encoding": "8-bit grey PNG beside the frame: the WorldCover legend code "
                              "per pixel (the legend above); 0 = nodata",
                  "method": LANDCOVER_METHOD,
                  "cell_rule": "a scene point (x, y) in the grid's CRS falls in cell (row, col) "
                               "= (floor((origin_y - y) / cell), floor((x - origin_x) / cell)); "
                               "the origin is the grid's upper-left corner",
                  "pixel_ray": "pixel (u, v) through its centre (u + 0.5, v + 0.5); the depth "
                               "is planar along the camera's forward axis"},
        "aggregates": {object_id: aggregate_record(object_id)["codes"]
                       for object_id in AGGREGATE_RECORDS},
        "engine_pass": {"key": ENGINE_LANDCOVER_KEY,
                        "agreement_min": LANDCOVER_AGREEMENT_MIN,
                        "status": "the engine's land-cover ID pass (M_LandcoverID) is W5's "
                                  "Windows step; agreement is recorded only where a bundle "
                                  "declares it"},
        "not_claimed": list(LANDCOVER_NOT_CLAIMED),
    }


def read_class_map(block: Dict, run_dir=None):
    """The class map the block names, checked against its sha256 and the
    grid's shape; refuses ``annotation.landcover`` otherwise."""
    import numpy as np

    where = (block.get("class_map") or {}).get("file")
    path = Path(str(where)) if where else None
    if (path is None or not path.is_file()) and run_dir is not None and where:
        candidate = Path(run_dir) / Path(str(where)).name
        path = candidate if candidate.is_file() else path
    if path is None or not path.is_file():
        raise LandcoverLabelError(f"the class map {where!r} the manifest names is not on this "
                                  f"machine; no land-cover image can be cut from it")
    digest = _sha256_file(path)
    if digest != (block.get("class_map") or {}).get("sha256"):
        raise LandcoverLabelError(f"{path.name}: sha256 {digest[:16]}... is not the manifest's "
                                  f"{str((block.get('class_map') or {}).get('sha256'))[:16]}...: "
                                  f"the land cover changed after the capture")
    codes = _read_id_png(path)
    grid = block.get("grid") or {}
    if codes.shape != (int(grid.get("height", -1)), int(grid.get("width", -1))):
        raise LandcoverLabelError(f"{path.name} is {codes.shape[1]}x{codes.shape[0]}, the grid "
                                  f"says {grid.get('width')}x{grid.get('height')}")
    return np.asarray(codes, dtype=np.uint8)


def landcover_class_from_depth(depth, record: Dict, grid: Dict, class_map,
                               frame_origin: Tuple[float, float], exclude=None):
    """The frame's land-cover image: (h, w) uint8 WorldCover codes, 0
    (nodata) where the depth is sky (not finite, not positive), the
    surface point is off the bake, the cell is nodata, or ``exclude``
    (a boolean mask: the aircraft pixels of the ID image) is set.

    ``depth`` is (h, w) metres, planar along the camera's forward axis;
    ``record`` the manifest frame record (pose and intrinsics); ``grid``
    the block's grid (``origin_x_m``, ``origin_y_m``, ``cell_size_m``,
    ``width``, ``height``); ``class_map`` the (height, width) code grid;
    ``frame_origin`` the manifest frame's projected ``(origin_x_m,
    origin_y_m)`` (the local north/east metres are about it)."""
    import numpy as np

    z = np.asarray(depth, dtype=np.float64)
    h, w = z.shape
    forward, right, up = camera_axes(record["quaternion_wxyz"])
    cx, cy = (float(v) for v in record["principal_point_px"])
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    d = ((np.arange(w, dtype=np.float64) + 0.5 - cx) / fx)[None, :]
    e = ((np.arange(h, dtype=np.float64) + 0.5 - cy) / fy)[:, None]
    valid = np.isfinite(z) & (z > 0.0)
    zv = np.where(valid, z, 0.0)
    north = float(record["position_north_m"]) + zv * (forward[0] + d * right[0] - e * up[0])
    east = float(record["position_east_m"]) + zv * (forward[1] + d * right[1] - e * up[1])
    x = float(frame_origin[0]) + east
    y = float(frame_origin[1]) + north
    cell = float(grid["cell_size_m"])
    col = np.floor((x - float(grid["origin_x_m"])) / cell)
    row = np.floor((float(grid["origin_y_m"]) - y) / cell)
    width, height = int(grid["width"]), int(grid["height"])
    inside = valid & (col >= 0) & (col < width) & (row >= 0) & (row < height)
    out = np.zeros((h, w), dtype=np.uint8)
    out[inside] = np.asarray(class_map)[row[inside].astype(np.int64), col[inside].astype(np.int64)]
    if exclude is not None:
        out[np.asarray(exclude, dtype=bool)] = LANDCOVER_NODATA
    return out


def landcover_fractions(image) -> Dict:
    """The fractions in view: per legend class and per taxonomy word, over
    ALL the frame's pixels (nodata stated beside them, so they sum to 1),
    the dominant class (most pixels, ties by legend order; None when
    nothing is labelled). A code outside the legend refuses
    ``annotation.landcover``: an unknown class is never counted."""
    import numpy as np

    from ..terrain.landcover import LEGEND
    from ..terrain.weightmaps import CLASS_OF_COVER, TAXONOMY

    counts = np.bincount(np.asarray(image, dtype=np.uint8).ravel(), minlength=256)
    known = {LANDCOVER_NODATA} | {c.code for c in LEGEND}
    stray = [int(c) for c in np.nonzero(counts)[0] if int(c) not in known]
    if stray:
        raise LandcoverLabelError(f"codes {stray} are not in the WorldCover legend")
    total = int(np.asarray(image).size)
    fractions = {c.key: float(counts[c.code]) / total for c in LEGEND}
    labelled = total - int(counts[LANDCOVER_NODATA])
    dominant = None
    if labelled:
        dominant = max(LEGEND, key=lambda c: (int(counts[c.code]), -LEGEND.index(c))).key
    taxonomy = {word: sum(float(counts[code]) for code, w in CLASS_OF_COVER.items()
                          if w == word) / total for word in TAXONOMY}
    return {"pixels": total, "labelled_pixels": labelled,
            "fractions": fractions,
            "nodata_fraction": float(counts[LANDCOVER_NODATA]) / total,
            "taxonomy_fractions": taxonomy, "dominant": dominant}


def landcover_agreement(image, engine) -> Dict:
    """The engine pass against this image over this image's LABELLED
    pixels: the fraction whose engine code equals it (the engine's 0
    where this image has a class counts as disagreement)."""
    import numpy as np

    image = np.asarray(image)
    engine = np.asarray(engine)
    if engine.shape != image.shape:
        raise LandcoverLabelError(f"the engine's land-cover pass is {engine.shape[1]}x"
                                  f"{engine.shape[0]}, the frame {image.shape[1]}x{image.shape[0]}")
    labelled = image != LANDCOVER_NODATA
    compared = int(np.count_nonzero(labelled))
    agreed = int(np.count_nonzero(labelled & (engine == image)))
    fraction = (agreed / compared) if compared else None
    return {"compared": compared, "agreed": agreed, "agreement": fraction,
            "min": LANDCOVER_AGREEMENT_MIN,
            "ok": None if fraction is None else bool(fraction >= LANDCOVER_AGREEMENT_MIN)}


def aggregate_from_landcover(image, codes: Sequence[int]) -> Dict:
    """An aggregate's box and pixel count from the land-cover image: the
    tight box (bbox_2d_tight's convention: far edges one past the last
    pixel) around the pixels whose code is one of ``codes``."""
    import numpy as np

    hit = np.isin(np.asarray(image), np.asarray(list(codes), dtype=np.uint8))
    pixels = int(np.count_nonzero(hit))
    box = None
    if pixels:
        ys, xs = np.nonzero(hit)
        box = [float(xs.min()), float(ys.min()), float(xs.max()) + 1.0, float(ys.max()) + 1.0]
    return {"landcover_bbox_2d": box, "landcover_pixels": pixels,
            "landcover_fraction": pixels / float(hit.size)}


def write_landcover_png(path: Path, image) -> Path:
    """The land-cover image as an 8-bit grey PNG (read back bit for bit
    by :func:`_read_id_png`)."""
    import numpy as np
    from PIL import Image

    Image.fromarray(np.ascontiguousarray(image, dtype=np.uint8)).save(path)
    return Path(path)


def frame_landcover(block: Dict, class_map, record: Dict, frame_origin, depth, mask,
                    aircraft_ids: Sequence[int], camera_dir: Path, engine_labels: Dict,
                    depth_file: str, write: bool = True):
    """One frame's land-cover image, written beside the frame, and its
    ``labels.landcover`` block; returns ``(block, image)``."""
    import numpy as np

    grid = block["grid"]
    exclude = np.isin(mask, np.asarray(list(aircraft_ids), dtype=mask.dtype)) \
        if mask is not None and aircraft_ids else None
    image = landcover_class_from_depth(depth, record, grid, class_map, frame_origin, exclude)
    stem = Path(str(record["file"])).name[:-len(".png")]
    name = f"{stem}{LANDCOVER_SUFFIX}"
    path = Path(camera_dir) / name
    if write:
        write_landcover_png(path, image)
    out = {"file": name, "sha256": _sha256_file(path) if path.is_file() else None,
           "depth": depth_file, **landcover_fractions(image),
           "method": LANDCOVER_METHOD, "agreement": None,
           "engine_pass": None}
    engine_file = engine_labels.get(ENGINE_LANDCOVER_KEY)
    if isinstance(engine_file, str) and engine_file:
        engine = _read_id_png(Path(camera_dir) / engine_file)
        out["engine_pass"] = engine_file
        out["agreement"] = landcover_agreement(image, engine)
    else:
        out["agreement_basis"] = ("no engine land-cover ID pass in this bundle (W5, Windows): "
                                  "no agreement is claimed")
    return out, image


def landcover_label_record(block: Dict, frames: Sequence[Dict]):
    """The ``labels.landcover`` record (record 2) over the frames that got
    a land-cover image. Null test: without a per-frame label a frame is
    read as the bake's dominant class (every in-view pixel); with it, the
    measured share of its labelled pixels in ANOTHER class -- a frame
    over forest reads forest, a frame over the lake reads water."""
    from ..records import AppliedVariable, Model, NullTest

    labelled = [f for f in frames if f.get("labelled_pixels")]
    total = sum(int(f["pixels"]) for f in frames) or 1
    keys = list((frames[0]["fractions"] if frames else {}).keys())
    in_view = {k: sum(f["fractions"][k] * f["pixels"] for f in frames) / total for k in keys}
    bake_dominant = block.get("dominant_class")
    others = [1.0 - (f["fractions"].get(bake_dominant, 0.0) * f["pixels"] / f["labelled_pixels"])
              for f in labelled]
    with_value = (sum(others) / len(others)) if others else 0.0
    agreements = [f["agreement"]["agreement"] for f in frames
                  if isinstance(f.get("agreement"), dict)
                  and f["agreement"].get("agreement") is not None]
    dominant = max(in_view, key=lambda k: (in_view[k], -keys.index(k))) if in_view else None
    references = ("ESA WorldCover 10 m 2021 v200 (product user manual v2.0)",
                  "core/capture/labels.py landcover_class_from_depth")
    return AppliedVariable(
        name="labels.landcover", value=dominant,
        unit="WorldCover legend class (dominant in view); fractions in parameters",
        source="derived",
        model_name="depth back-projection onto the bake's WorldCover class grid",
        parameters={
            "dataset": block.get("dataset"), "tiles": block.get("tiles"),
            "source_sha256": block.get("source_sha256"),
            "class_map_sha256": (block.get("class_map") or {}).get("sha256"),
            "document_sha256": block.get("document_sha256"),
            "frames": len(frames), "labelled_frames": len(labelled),
            "fractions_in_view": in_view,
            "nodata_fraction": sum(f["nodata_fraction"] * f["pixels"] for f in frames) / total,
            "frame_dominants": [f.get("dominant") for f in frames],
            "bake_dominant": bake_dominant,
            "agreement": ({"frames": len(agreements), "min": min(agreements),
                           "mean": sum(agreements) / len(agreements),
                           "threshold": LANDCOVER_AGREEMENT_MIN} if agreements else None),
            "license": block.get("license"), "attribution": block.get("attribution"),
        },
        references=references,
        frame_keys=("labels.landcover",),
        null_test=NullTest(
            quantity="share of a frame's labelled pixels outside the bake's dominant class",
            unit="fraction", with_value=float(with_value), without_value=0.0,
            threshold=0.05, kind="reached",
            note=(f"without = every in-view pixel read as the bake's dominant class "
                  f"({bake_dominant}); with = the per-frame land-cover image, mean over "
                  f"{len(labelled)} labelled frame(s): a frame over forest reads forest, "
                  f"a frame over the lake reads water")),
        model=Model(name="land-cover image from depth", standard="ESA WorldCover v200 legend",
                          version="W4", parameters={"nodata": LANDCOVER_NODATA,
                                                    "agreement_min": LANDCOVER_AGREEMENT_MIN},
                          references=references),
        frm="the frame's depth and pose, the bake's WorldCover class map",
        std="ESA WorldCover product user manual v2.0 (the legend, Table 3)",
        not_claimed=LANDCOVER_NOT_CLAIMED)


def _bundle_records(camera_dir: Path) -> Dict[str, Dict]:
    """``{frame name: render.json record}`` for the records that declare
    label outputs, or {} when this camera has no render.json."""
    path = camera_dir / "render.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("frame_records")
    if not isinstance(records, list):
        return {}
    return {str(r.get("frame")): r for r in records
            if isinstance(r, dict) and isinstance(r.get("labels"), dict)}


def _attach_record(manifest: Dict, record) -> None:
    """Put one ``AppliedVariable`` into the manifest's ``applied_variables``
    block (ADVANCEMENTS_CONTRACTS rule 0), creating the block when absent
    and REPLACING a record of the same name: attach is re-run after every
    render, and the passes record describes this bundle, not the last."""
    from ..records import RECORD_VERSION, read_records, records_block

    block = manifest.get("applied_variables")
    if not isinstance(block, dict) or not isinstance(block.get("applied_variables"), list):
        manifest["applied_variables"] = records_block([record])
        return
    if block.get("record_version") != RECORD_VERSION:
        # INT-final: a block written at record 1 is renamed to record 2
        # (or refused by name) before a record-2 dict joins it.
        block["applied_variables"] = list(read_records(block))
        block["record_version"] = RECORD_VERSION
    kept = [r for r in block["applied_variables"] if r.get("name") != record.name]
    block["applied_variables"] = kept + [record.to_dict()]


def attach_engine_labels(run_dir, write: bool = True) -> Dict:
    """Complete a manifest-6 run's per-object records from the render
    bundle beside its frames, and write the manifest and every sidecar
    back.

    Reads, per frame the manifest names: ``frames/<camera>/render.json``
    (the record's ``labels`` block names the files; nothing is inferred
    from file names), the ID image (``labels.mask``), the depth
    (``labels.depth_f32``, else the 16-bit ``labels.depth`` at
    ``depth_scale_m`` -- stated in the basis) and each aircraft object's
    alone pass (``labels.objects[].alone_png``). Computes with numpy the
    tight box, the visible fraction, ``occluded_by`` (resolved to ids
    through ``objects[]``), and the depth under the mask, and records
    the files each number came from. A frame with no bundle keeps its
    nulls and the no-bundle basis; a manifest below version 6 has no
    per-object records and is left untouched (returned as such).

    I6: records under each frame's ``labels.passes`` which ground-truth
    passes the bundle declares (``{"normal": file|None, "velocity": ...,
    "albedo": ...}``) -- names only, nothing opened -- and, when any is
    declared, the ``render.passes`` AppliedVariable under the manifest's
    ``applied_variables`` (:func:`passes_record`).

    The producer of the numbers, not their judge: the verifier (package
    D) re-derives every one of them from the same files and grades them
    against the projected geometry; this function never imports it.
    """
    from .manifest import (
        SUPPORTED_MANIFEST_VERSIONS, read_capture_manifest,
        write_capture_manifest, write_frame_sidecars,
    )
    from .objects import resolve_ids

    run_dir = Path(run_dir)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    version = manifest.get("manifest_version")
    summary = {"manifest_version": version, "frames": 0, "attached": 0,
               "without_bundle": 0, "objects": 0, "written": False}
    if version not in SUPPORTED_MANIFEST_VERSIONS or version < 6:
        summary["note"] = (f"manifest version {version} carries no per-object "
                           f"records; nothing to attach (a version-6 manifest "
                           f"is written by this build)")
        return summary
    objects = manifest.get("objects") or []
    bundles: Dict[str, Dict[str, Dict]] = {}
    pass_files_per_frame: List[int] = []
    pass_words_seen: set = set()
    # S2: the aircraft objects an amodal extent is taken for, and what was taken.
    aircraft_ids = {int(o["int_id"]) for o in objects
                    if isinstance(o, dict) and o.get("class") == "aircraft"}
    amodal_ratios: List[Optional[float]] = []
    amodal_refused = 0
    # W4: the land-cover image per frame, when the manifest names land
    # cover (its top-level ``landcover`` block); the class map is read
    # once, checked against its digest, and a refusal is recorded by name.
    landcover_block = manifest.get("landcover") if isinstance(manifest.get("landcover"), dict) else None
    landcover_frames: List[Dict] = []
    class_map = None
    landcover_refusal: Optional[LandcoverLabelError] = None
    frame_block = manifest.get("frame") or {}
    if landcover_block is not None:
        try:
            if str((landcover_block.get("grid") or {}).get("crs")) != str(frame_block.get("crs")):
                raise LandcoverLabelError(
                    f"the land cover's grid is in {(landcover_block.get('grid') or {}).get('crs')}, "
                    f"the frame in {frame_block.get('crs')}; a surface point cannot be placed")
            class_map = read_class_map(landcover_block, run_dir)
        except LandcoverLabelError as exc:
            landcover_refusal = exc
            summary["landcover"] = {"refused": exc.constraint, "reason": exc.message}
    for frame in manifest.get("frames", []):
        summary["frames"] += 1
        camera = str(frame["camera_id"])
        camera_dir = run_dir / "frames" / camera
        if camera not in bundles:
            bundles[camera] = _bundle_records(camera_dir)
        engine = bundles[camera].get(Path(str(frame["file"])).name)
        entries = (frame.get("labels") or {}).get("objects")
        if engine is None or not isinstance(entries, list):
            summary["without_bundle"] += 1
            continue
        labels = engine["labels"]
        width, height = int(frame["width_px"]), int(frame["height_px"])
        files: Dict[str, str] = {}
        mask = _read_id_png(camera_dir / str(labels["mask"]))
        files["mask"] = str(labels["mask"])
        if mask.shape != (height, width):
            raise ValueError(
                f"{camera}/{labels['mask']}: ID image is {mask.shape[1]}x"
                f"{mask.shape[0]}, the record says {width}x{height}")
        depth = None
        if labels.get("depth_f32"):
            depth = read_depth_f32(camera_dir / str(labels["depth_f32"]), width, height)
            files["depth"] = str(labels["depth_f32"])
        elif labels.get("depth"):
            depth = read_depth_png(camera_dir / str(labels["depth"]),
                                   float(labels.get("depth_scale_m", 0.1)),
                                   float(labels.get("depth_saturation_m", 6553.5)))
            files["depth"] = f"{labels['depth']} (16-bit at depth_scale_m; no .f32 declared)"
        alone_by_id: Dict[int, str] = {}
        for declared in labels.get("objects") or []:
            if isinstance(declared, dict) and declared.get("alone_png"):
                alone_by_id[int(declared["int_id"])] = str(declared["alone_png"])
        for entry in entries:
            int_id = int(entry["int_id"])
            alone = None
            if int_id in alone_by_id:
                alone = _read_id_png(camera_dir / alone_by_id[int_id])
                files[f"alone_{int_id}"] = alone_by_id[int_id]
            measured = measure_object(mask, depth, int_id, alone)
            entry["bbox_2d_tight"] = measured["bbox_2d_tight"]
            entry["visible_fraction"] = measured["visible_fraction"]
            entry["occluded_by"] = resolve_ids(measured["occluded_by"], objects)
            entry["depth_min_m"] = measured["depth_min_m"]
            entry["depth_median_m"] = measured["depth_median_m"]
            basis = entry.setdefault("basis", {})
            basis["engine"] = {
                "files": dict(files),
                "pixels": measured["pixels"],
                "pixels_alone": measured["pixels_alone"],
                "method": ("numpy over the ID image (== int_id), the alone pass "
                           "and the depth under the mask; the verifier "
                           "re-derives these from the same files"),
            }
            # S2: the amodal box and mask, when this frame's camera asks.
            wants_amodal = "amodal" in ((frame.get("passes") or {}).get("requested") or [])
            if wants_amodal and int_id in aircraft_ids:
                from .passes import PassError

                try:
                    amodal = amodal_labels(alone, mask, int_id, alone_by_id.get(int_id))
                except PassError as exc:
                    entry["amodal_bbox_2d"] = entry["amodal_mask"] = entry["amodal_ratio"] = None
                    basis["amodal"] = {"refused": exc.constraint, "reason": exc.message}
                    amodal_refused += 1
                else:
                    entry["amodal_bbox_2d"] = amodal["amodal_bbox_2d"]
                    entry["amodal_mask"] = amodal["amodal_mask"]
                    entry["amodal_ratio"] = amodal["amodal_ratio"]
                    basis["amodal"] = amodal["basis"]
                    amodal_ratios.append(amodal["amodal_ratio"])
            summary["objects"] += 1
        # W4: the frame's land-cover image, its fractions in view and the
        # aggregates' boxes from it (needs the depth; recorded by name when
        # the land cover cannot be used).
        if landcover_block is not None and depth is not None:
            frame_labels_block = frame.setdefault("labels", {})
            if landcover_refusal is not None:
                frame_labels_block["landcover"] = {"refused": landcover_refusal.constraint,
                                                   "reason": landcover_refusal.message}
            else:
                try:
                    lc, lc_image = frame_landcover(
                        landcover_block, class_map, frame,
                        (float(frame_block["origin_x_m"]), float(frame_block["origin_y_m"])),
                        depth, mask, sorted(aircraft_ids), camera_dir, labels,
                        files["depth"], write=write)
                except LandcoverLabelError as exc:
                    frame_labels_block["landcover"] = {"refused": exc.constraint,
                                                       "reason": exc.message}
                else:
                    frame_labels_block["landcover"] = lc
                    landcover_frames.append(lc)
                    for entry in entries:
                        aggregate = aggregate_record(str(entry.get("id")))
                        if aggregate is None:
                            continue
                        entry.update(aggregate_from_landcover(lc_image, aggregate["codes"]))
                        entry["landcover_mask"] = {
                            "file": lc["file"], "codes": aggregate["codes"],
                            "encoding": "the land-cover image's pixels whose code is one of codes"}
        # I6: which ground-truth passes this frame's record declares, by
        # name (the files are not opened here; the verifier reads them).
        declared_passes = passes_declared(engine)
        frame.setdefault("labels", {})["passes"] = declared_passes
        pass_files_per_frame.append(sum(1 for v in declared_passes.values() if v))
        for word, value in declared_passes.items():
            if value:
                pass_words_seen.add(word)
        summary["attached"] += 1
    if pass_words_seen:
        record = passes_record(pass_files_per_frame,
                               [w for w in PASS_RECORD_KEYS if w in pass_words_seen])
        _attach_record(manifest, record)
        summary["passes"] = sorted(pass_words_seen)
    # S2: the amodal record, and the derived passes (flow, disparity,
    # points) with each camera's passes.json -- only for frames whose
    # camera asks (the manifest frame's ``passes`` block).
    if amodal_ratios or amodal_refused:
        from .passes import amodal_record

        _attach_record(manifest, amodal_record(amodal_ratios, amodal_refused))
        summary["amodal"] = {"objects": len(amodal_ratios), "refused": amodal_refused}
    # W4: the land-cover record over the frames that got an image.
    if landcover_frames:
        _attach_record(manifest, landcover_label_record(landcover_block, landcover_frames))
        summary["landcover"] = {"frames": len(landcover_frames),
                                "agreements": sum(1 for f in landcover_frames
                                                  if f.get("agreement") is not None)}
    if any(isinstance(f.get("passes"), dict) for f in manifest.get("frames", [])):
        from .passes import attach_passes

        summary["derived_passes"] = attach_passes(run_dir, manifest=manifest, write=False)
    if write and summary["attached"]:
        write_capture_manifest(manifest, run_dir)
        write_frame_sidecars(manifest, run_dir)
        summary["written"] = True
    return summary
