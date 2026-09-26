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
#: to 16 px is claimed by this record and graded by no check -- the
#: two numbers are not yet one (the export's NOT_CLAIMED_EXTENT_PX is
#: also 16).
NOT_CLAIMED_OBJECT_PX = 12
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
            summary["objects"] += 1
        summary["attached"] += 1
    if write and summary["attached"]:
        write_capture_manifest(manifest, run_dir)
        write_frame_sidecars(manifest, run_dir)
        summary["written"] = True
    return summary
