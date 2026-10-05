"""The 3-D box and which way each plane faces, rebuilt from the record alone.

Every aircraft's frame record carries ``bbox_3d_camera`` (core/capture/
labels.py ``bbox_labels``): the box centre, its three extents and the
airframe's body axes, all in CAMERA coordinates (x right, y down, z
forward along the view, metres), plus the eight corners the producer
projected. This module:

* rebuilds the eight corners from ``centre_m`` + ``extents_m`` +
  ``body_axes_in_camera`` ONLY (:func:`rebuild_corners`) and projects them
  with the frame's own ``intrinsic_matrix`` -- nothing from the scene, the
  telemetry or the airframe config -- and compares both with the
  recorded corners and their recorded projection (:func:`rebuild_check`),
  so each frame states, with a number, that the box can be rebuilt from
  its record;
* states which way the plane faces from the camera's point of view
  (:func:`facing`): yaw / pitch / roll of the airframe relative to the
  camera and a plain word ("away from the camera", "to the left", ...);
* draws a third version of each frame with the rebuilt box and a nose
  arrow on it (:func:`draw_box3d_frame`).

Corner order (the producer's, airframe.box_corners_body_m): for forward
in (aft, nose), for right in (left, right), for down in (top, bottom) --
so corner i has signs ((-1,+1)[i // 4], (-1,+1)[(i // 2) % 2],
(-1,+1)[i % 2]) on (forward, right, down).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]

#: The twelve edges of the box over the corner order above.
EDGES = [(0, 1), (2, 3), (4, 5), (6, 7),          # top-bottom
         (0, 2), (1, 3), (4, 6), (5, 7),          # left-right
         (0, 4), (1, 5), (2, 6), (3, 7)]          # aft-nose
#: The nose face (forward = +): corners 4..7.
NOSE_FACE = [(4, 5), (5, 7), (7, 6), (6, 4)]

#: Rebuild tolerances: the recorded numbers are floats written to JSON,
#: so a rebuild agrees to rounding, far inside these.
REBUILD_TOL_M = 0.01
REBUILD_TOL_PX = 0.05


def _signs(i: int) -> Vec:
    return ((-1.0, 1.0)[i // 4], (-1.0, 1.0)[(i // 2) % 2], (-1.0, 1.0)[i % 2])


def rebuild_corners(box: Dict) -> List[Vec]:
    """The eight corners from centre + extents + body axes (camera frame)."""
    c = [float(v) for v in box["centre_m"]]
    ext = [float(v) for v in box["extents_m"]]
    axes = [[float(v) for v in row] for row in box["body_axes_in_camera"]]
    out = []
    for i in range(8):
        s = _signs(i)
        out.append(tuple(c[k] + sum(s[a] * ext[a] / 2.0 * axes[a][k] for a in range(3))
                         for k in range(3)))
    return out


def project(K: Sequence[Sequence[float]], p: Sequence[float]) -> Optional[Tuple[float, float]]:
    """Camera point -> pixel through the frame's 3x3 intrinsic matrix."""
    if p[2] <= 0.0:
        return None
    u = K[0][0] * p[0] + K[0][1] * p[1] + K[0][2] * p[2]
    v = K[1][0] * p[0] + K[1][1] * p[1] + K[1][2] * p[2]
    w = K[2][0] * p[0] + K[2][1] * p[1] + K[2][2] * p[2]
    return (u / w, v / w)


def _intrinsics(record: Dict) -> Optional[List[List[float]]]:
    K = record.get("intrinsic_matrix")
    if isinstance(K, list) and len(K) == 3:
        return [[float(v) for v in row] for row in K]
    if record.get("fx_px") is not None and record.get("principal_point_px"):
        cx, cy = record["principal_point_px"]
        return [[float(record["fx_px"]), 0.0, float(cx)],
                [0.0, float(record["fy_px"]), float(cy)], [0.0, 0.0, 1.0]]
    return None


def facing(box: Dict) -> Dict:
    """Which way the plane faces, seen from the camera.

    ``yaw_deg``: the nose's direction in the image's horizontal plane --
    0 = pointing straight away from the camera, +90 = to the image's
    right, -90 = to its left, 180 = straight at the camera.
    ``pitch_deg``: nose up (+) or down (-) relative to the camera's
    horizontal. ``roll_deg``: right wing down (+) about the nose axis, as
    seen in the camera frame. ``rotation_y`` is the KITTI convention
    (atan2(-f_z, f_x)) for readers who expect it.
    """
    f, r, _ = [[float(v) for v in row] for row in box["body_axes_in_camera"]]
    yaw = math.degrees(math.atan2(f[0], f[2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -f[1]))))
    # Roll: the right wing's drop below the plane through the nose axis
    # and the camera's up direction.
    up = (0.0, -1.0, 0.0)
    side = (f[1] * up[2] - f[2] * up[1], f[2] * up[0] - f[0] * up[2],
            f[0] * up[1] - f[1] * up[0])
    norm = math.sqrt(sum(v * v for v in side)) or 1.0
    side = tuple(v / norm for v in side)
    level_up = (side[1] * f[2] - side[2] * f[1], side[2] * f[0] - side[0] * f[2],
                side[0] * f[1] - side[1] * f[0])
    roll = math.degrees(math.atan2(-sum(a * b for a, b in zip(r, level_up)),
                                   sum(a * b for a, b in zip(r, side))))
    a = abs(yaw)
    if a <= 30.0:
        word = "away from the camera"
    elif a >= 150.0:
        word = "toward the camera"
    else:
        side_word = "right" if yaw > 0 else "left"
        word = (f"to the {side_word}" if 60.0 <= a <= 120.0 else
                f"away and to the {side_word}" if a < 60.0 else
                f"toward the camera and to the {side_word}")
    return {"yaw_deg": round(yaw, 3), "pitch_deg": round(pitch, 3),
            "roll_deg": round(roll, 3),
            "rotation_y": round(math.atan2(-f[2], f[0]), 6),
            "nose_direction_camera": [round(v, 6) for v in f],
            "facing": word}


def rebuild_check(box: Dict, record: Dict) -> Dict:
    """Rebuild the corners from the record alone and compare them (metres)
    and their projection (pixels) with the recorded corners."""
    rebuilt = rebuild_corners(box)
    recorded = box.get("corners_m") or []
    corner_err = (max(math.dist(a, b) for a, b in zip(rebuilt, recorded))
                  if len(recorded) == 8 else None)
    K = _intrinsics(record)
    pixel_err = None
    if K is not None and len(recorded) == 8:
        errs = []
        for a, b in zip(rebuilt, recorded):
            pa, pb = project(K, a), project(K, b)
            if pa is not None and pb is not None:
                errs.append(math.dist(pa, pb))
        pixel_err = max(errs) if errs else None
    ok = (corner_err is not None and corner_err <= REBUILD_TOL_M
          and (pixel_err is None or pixel_err <= REBUILD_TOL_PX))
    return {"max_corner_error_m": None if corner_err is None else round(corner_err, 9),
            "max_pixel_error_px": None if pixel_err is None else round(pixel_err, 9),
            "tolerance": {"m": REBUILD_TOL_M, "px": REBUILD_TOL_PX},
            "ok": bool(ok),
            "used": "centre_m, extents_m, body_axes_in_camera and the frame's "
                    "intrinsic_matrix only"}


def box3d_section(manifest: Dict, record: Dict) -> Dict:
    """The frame sidecar's ``box_3d`` section: per aircraft, the 3-D box,
    which way it faces, and the proof it rebuilds from the record."""
    class_of = {str(o.get("id")): str(o.get("class"))
                for o in manifest.get("objects") or [] if isinstance(o, dict)}
    labels = record.get("labels") or {}
    entries = labels.get("objects")
    if not isinstance(entries, list):
        entries = [{"id": f"aircraft:{manifest.get('aircraft')}:0",
                    "bbox_3d_camera": labels.get("bbox_3d_camera")}]
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        object_id = str(entry.get("id"))
        if class_of.get(object_id, "aircraft") != "aircraft":
            continue
        box = entry.get("bbox_3d_camera")
        if not isinstance(box, dict) or not box.get("body_axes_in_camera"):
            out.append({"id": object_id, "box": None,
                        "note": "no 3-D box recorded for this plane in this frame"})
            continue
        out.append({
            "id": object_id,
            "centre_m": box.get("centre_m"),
            "extents_m": {"length": box["extents_m"][0], "width": box["extents_m"][1],
                          "height": box["extents_m"][2]},
            "body_axes_in_camera": {"forward": box["body_axes_in_camera"][0],
                                    "right": box["body_axes_in_camera"][1],
                                    "down": box["body_axes_in_camera"][2]},
            "cg_m": box.get("cg_m"),
            "orientation": facing(box),
            "rebuild_check": rebuild_check(box, record),
        })
    return {
        "about": ("Per aircraft, in CAMERA coordinates (x right, y down, z forward "
                  "along the view; metres). To rebuild the box from this record "
                  "alone: corner_i = centre_m + sum over a in (forward, right, "
                  "down) of s_a(i) * extents_m[a] / 2 * body_axes_in_camera[a], "
                  "with s(i) = (+-1 for aft/nose, left/right, top/bottom; corner "
                  "order for forward in (aft, nose), right in (left, right), down "
                  "in (top, bottom)); pixel = K * corner / z with this frame's "
                  "intrinsic_matrix. rebuild_check does exactly that and states "
                  "the largest error against the recorded corners. orientation: "
                  "yaw 0 = nose away from the camera, +90 = to the image's right, "
                  "180 = toward it; pitch + = nose up; roll + = right wing down."),
        "intrinsic_matrix": _intrinsics(record),
        "aircraft": out,
    }


# -- the third picture -----------------------------------------------------

BOX_EDGE = (90, 200, 255)
NOSE_EDGE = (255, 90, 90)
ARROW = (255, 235, 80)


def draw_box3d_frame(record: Dict, source, target):
    """Write ``target``: ``source`` with each plane's 3-D box drawn from
    the REBUILT corners (record alone) and an arrow out of its nose."""
    from pathlib import Path

    from PIL import Image, ImageDraw

    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    K = _intrinsics(record)
    labels = record.get("labels") or {}
    entries = labels.get("objects")
    if not isinstance(entries, list):
        entries = [{"id": "aircraft", "bbox_3d_camera": labels.get("bbox_3d_camera")}]
    for entry in entries:
        box = entry.get("bbox_3d_camera") if isinstance(entry, dict) else None
        if K is None or not isinstance(box, dict) or not box.get("body_axes_in_camera"):
            continue
        corners = rebuild_corners(box)
        pixels = [project(K, c) for c in corners]
        for a, b in EDGES:
            if pixels[a] is not None and pixels[b] is not None:
                draw.line([pixels[a], pixels[b]], fill=BOX_EDGE, width=2)
        for a, b in NOSE_FACE:
            if pixels[a] is not None and pixels[b] is not None:
                draw.line([pixels[a], pixels[b]], fill=NOSE_EDGE, width=2)
        centre = [float(v) for v in box["centre_m"]]
        forward = [float(v) for v in box["body_axes_in_camera"][0]]
        length = float(box["extents_m"][0])
        tip = [centre[k] + forward[k] * length * 0.9 for k in range(3)]
        pc, pt = project(K, centre), project(K, tip)
        if pc is not None and pt is not None:
            draw.line([pc, pt], fill=ARROW, width=3)
            draw.ellipse([pt[0] - 4, pt[1] - 4, pt[0] + 4, pt[1] + 4], fill=ARROW)
        face = facing(box)
        visible = [p for p in pixels if p is not None]
        if visible:
            tx = max(0.0, min(min(p[0] for p in visible), width - 220))
            ty = max(0.0, min(p[1] for p in visible) - 14)
            tag = f"{entry.get('id')}  {face['facing']}  yaw {face['yaw_deg']:.0f}"
            draw.rectangle([tx, ty, tx + 6 * len(tag) + 6, ty + 12], fill=(10, 12, 18))
            draw.text((tx + 3, ty), tag, fill=ARROW)
    draw.rectangle([0, height - 16, width, height], fill=(10, 12, 18))
    draw.text((6, height - 14),
              "3-D box rebuilt from the record alone (blue; red = nose face), "
              "yellow arrow = where the nose points", fill=(220, 225, 232))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target
