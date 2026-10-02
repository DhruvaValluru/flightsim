"""S2: the ground-truth passes as data -- optical flow with validity bits,
disparity, per-object point clouds, and ``passes.json``.

The engine writes the depth (``frame_NNNN_depth.f32``, camera z in
metres, +inf for sky), the ID image (``frame_NNNN_mask.png``, one
``int_id`` per pixel) and each aircraft's alone pass beside every
labelled frame (the ``-labels`` bundle). Everything here is DERIVED
from those files and the manifest's own geometry, in numpy, after the
render; the verifier re-derives every number from the same files with
its own projection (core/capture/verify.py ``flow_vs_keypoints``,
``flow_static_null``, ``disparity_vs_right_depth``, ``points_vs_depth``)
and imports nothing from here.

What a camera asks for is ``cameras[i].passes`` (a list of words,
:data:`PASS_WORDS`): the engine words (normal, velocity, albedo -- I6)
ride the ``-passes=`` flag; the derived words (flow, disparity, points,
amodal) are computed here (amodal by :mod:`core.capture.labels`).

Optical flow (Menze & Geiger 2015, "Object scene flow for autonomous
vehicles", CVPR -- rigid-object flow with a validity channel; Virtual
KITTI 2's forward and backward convention), per labelled frame at
telemetry sample i and for each direction (forward i -> i+1, backward
i -> i-1, the NEIGHBOURING 10 Hz TELEMETRY SAMPLES, not the neighbouring
captured frames: capture periods are seconds and chase presets lag):

1. every pixel CENTRE (u + 0.5, v + 0.5) with a finite depth is
   back-projected through the frame's pinhole and pose to a scene point
   (north, east, up) -- the manifest's documented model;
2. a pixel whose ID is an aircraft object with a state at both samples
   is moved RIGIDLY with that object: body = R_i^T (P - cg_i), P' =
   cg_j + R_j body (the aerospace Z-Y'-X'' rotation of the recorded
   roll, pitch and heading); every other pixel (terrain, id 0,
   anything that is not an aircraft object) is static world;
3. P' is projected through the camera's pose at sample j; the flow is
   (u' - (u + 0.5), v' - (v + 0.5)) pixels, +x right, +y down;
4. the validity bits (one uint8 per pixel, :data:`FLOW_VALID` 1,
   :data:`FLOW_OCCLUDED` 2, :data:`FLOW_OUT_OF_FRAME` 4; 0 = no surface
   (sky) or no neighbour sample): out of frame when P' is behind the
   camera or projects outside [0, W) x [0, H); otherwise the Z-TEST --
   every in-frame P' is splatted at its depth z' into the four pixels
   whose centres surround (u', v'), the z-buffer keeps the nearest and
   the object it belongs to, and the pixel is OCCLUDED when the nearest
   surface at the pixel that contains (u', v') belongs to ANOTHER object
   and lies nearer than z' by more than :data:`ZTEST_TOL_FRACTION` z +
   :data:`ZTEST_TOL_M` (the verifier's depth tolerance, 1 % + 2 m,
   restated and pinned equal by test), else VALID. (Another object's:
   at grazing incidence one surface's neighbouring pixels differ in
   depth by more than any fixed tolerance, and the four-pixel splat
   would mark a slanted ground as hiding itself -- measured, 43 % of the
   synthetic scene's surface pixels in one direction; so a surface's
   self-occlusion -- a ridge
   hiding a valley, a wing its own fuselage -- is not flagged.)

The last sample's forward flow (and the first's backward) has no
neighbour: zeros, bits 0, and a basis saying so.

Disparity (a stated rig only, core/capture/stereo.py): d = f_x B / Z
pixels for every finite-depth pixel of the LEFT camera, 0 for sky (a
point at infinity has no disparity). Rectified by construction.

Points: every finite-depth pixel back-projected to CAMERA coordinates
(x right, y down, z forward, metres), float32 N x 4 with the fourth
column the reflectance, 0 (no intensity model -- stated), row-major
over the pixels, and a sidecar ``_points_id.u8`` with the pixel's
``int_id``. The sky contributes none.

Files per frame (beside the frame, ``frames/<camera>/``), each named
with its sha256 in ``passes.json``: ``frame_NNNN_flow_fw.f32`` /
``_flow_bw.f32`` (little-endian float32 (du, dv) pairs, row-major, the
I6 flow layout), ``_flow_fw_valid.u8`` / ``_flow_bw_valid.u8`` (one
byte per pixel), ``_disparity.f32`` (float32 per pixel),
``_points.f32`` (float32 N x 4) and ``_points_id.u8`` (N bytes).
``frames/<camera>/passes.json`` holds per frame the files, the valid /
occluded / out-of-frame fractions, |flow| p50 / p95, the disparity
range and the points per object; the capture manifest's per-frame
``passes`` block names it and carries the same summary.

NOT claimed: flow is exact for RIGID bodies only (no control-surface
deflection, no propeller, no deformation); occlusion is decided among
the surfaces the SOURCE frame sees (a surface hidden at sample i cannot
occlude at j; the neighbour sample has no render); positions are the
manifest's projected-grid metres read flat, as the annotation gates
read them (the host's round-planet frame differs by the grid scale
factor, 0.097 % on the example scene); the engine's own velocity pass
on real pixels is S4's Windows step. Disparity is rectified by
construction. Points are depth back-projections with no beam model.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

PASSES_VERSION = 1
PASSES_FILE = "passes.json"

#: Every word ``cameras[i].passes`` may name. The first three are the
#: engine's (I6, core/render/flags.py PASS_NAMES, pinned equal by test);
#: the rest are derived here and in core/capture/labels.py (amodal).
ENGINE_PASS_WORDS = ("normal", "velocity", "albedo")
DERIVED_PASS_WORDS = ("flow", "disparity", "points", "amodal")
PASS_WORDS = ENGINE_PASS_WORDS + DERIVED_PASS_WORDS

#: The z-test's tolerance: a warped point is occluded when it lies more
#: than this fraction of the nearer depth plus this many metres behind
#: it. The verifier's DEPTH_TOL_FRACTION / DEPTH_TOL_M (contracts §3: 1 %
#: + 2 m), restated so the producer does not import the verifier.
ZTEST_TOL_FRACTION = 0.01
ZTEST_TOL_M = 2.0

#: The validity bits (one uint8 per pixel). 0 = no surface (sky) or no
#: neighbour sample.
FLOW_VALID = 1
FLOW_OCCLUDED = 2
FLOW_OUT_OF_FRAME = 4

#: (direction, sample step, file tag).
DIRECTIONS = (("forward", 1, "fw"), ("backward", -1, "bw"))

#: File suffixes by key (frame_NNNN + suffix).
PASS_SUFFIXES = {
    "flow_fw": "_flow_fw.f32", "flow_fw_valid": "_flow_fw_valid.u8",
    "flow_bw": "_flow_bw.f32", "flow_bw_valid": "_flow_bw_valid.u8",
    "disparity": "_disparity.f32",
    "points": "_points.f32", "points_id": "_points_id.u8",
}

#: The render.json frame-record keys S4's linear writers declare (the
#: ``.f32`` normal and base colour, 3 x float32 per pixel); until they
#: exist the I6 16-bit PNGs (``normal_png`` / ``albedo_png``) are read.
NORMAL_F32_KEY = "normal_f32"
BASECOLOR_F32_KEY = "basecolor_f32"

#: The refusal a derived pass takes when its bundle holds no depth.
NO_DEPTH_REFUSAL = {"flow": "annotation.flow", "disparity": "annotation.disparity",
                    "points": "annotation.points"}

CONVENTIONS = {
    "flow": ("float32 little-endian (du, dv) pairs per pixel, row-major, pixels, +x right, "
             "+y down: where the surface at this pixel centre is at the neighbouring "
             "telemetry sample (forward: sample + 1, backward: sample - 1), rigid "
             "motion of its aircraft object, static world otherwise"),
    "flow_valid": ("uint8 per pixel: 1 valid, 2 occluded (another object's surface nearer by "
                   "more than 1 % + 2 m in the splatted z-buffer), 4 out of frame, 0 no "
                   "surface or no neighbour"),
    "disparity": "float32 per pixel, d = f_x B / Z pixels, 0 for sky; the left camera of a rig",
    "points": ("float32 N x 4 (x right, y down, z forward metres in the camera frame, "
               "reflectance 0), row-major over the finite-depth pixels; ids in _points_id.u8"),
    "references": ["Menze & Geiger 2015, Object scene flow for autonomous vehicles (CVPR)",
                   "Cabon et al. 2020, Virtual KITTI 2 (forward and backward flow)",
                   "Geiger et al. 2013, Vision meets robotics: the KITTI dataset (IJRR)"],
}


class PassError(Exception):
    """A pass that cannot be derived; refused by name, never approximated."""

    def __init__(self, constraint: str, message: str):
        super().__init__(f"{constraint}: {message}")
        self.constraint = constraint
        self.message = message


# -- what a camera asks for -------------------------------------------------------

def requested_passes(camera) -> Tuple[str, ...]:
    """The words ``cameras[i].passes`` states, in :data:`PASS_WORDS` order
    (() when unstated)."""
    value = getattr(getattr(camera, "passes", None), "value", None)
    if not isinstance(value, list):
        return ()
    wanted = {str(w) for w in value}
    return tuple(w for w in PASS_WORDS if w in wanted)


def engine_words(cameras: Sequence) -> List[str]:
    """The engine pass words any camera asks for (for ``-passes=``)."""
    words = set()
    for camera in cameras:
        words.update(w for w in requested_passes(camera) if w in ENGINE_PASS_WORDS)
    return [w for w in ENGINE_PASS_WORDS if w in words]


def pass_violations(camera, index: int = 0) -> List:
    """``sensing.pass`` for one camera: the passes value must be a list of
    known words without repeats; ``disparity`` needs a stated stereo rig
    on the same camera."""
    from ..scenario.validate import Violation

    value = getattr(getattr(camera, "passes", None), "value", None)
    if value is None:
        return []
    who = f"camera[{index}] {str(camera.camera_id.value)!r}"
    if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
        return [Violation("sensing.pass", f"{who}: passes must be a list of pass words, "
                                          f"got {value!r}")]
    unknown = sorted(set(value) - set(PASS_WORDS))
    if unknown:
        return [Violation("sensing.pass", f"{who}: unknown pass word(s) {unknown}; the "
                                          f"passes are {list(PASS_WORDS)}")]
    if len(set(value)) != len(value):
        return [Violation("sensing.pass", f"{who}: a pass word is repeated in {value}")]
    if "disparity" in value and getattr(getattr(camera, "stereo", None), "value", None) is None:
        return [Violation("sensing.pass", f"{who}: disparity needs a stereo rig on the same "
                                          f"camera (state stereo with a baseline)")]
    return []


# -- the neighbour block (manifest build time) ------------------------------------

STATE_KEYS = ("north_m", "east_m", "alt_m", "roll_deg", "pitch_deg", "heading_deg")


def object_states_at(primary_int_id: int, aircraft_track: Sequence[Dict],
                     traffic: Sequence[Tuple[int, object]]) -> Callable[[int], Dict[str, Dict]]:
    """``states_at(j) -> {str(int_id): state}`` for every aircraft object:
    the primary from the manifest's aircraft track, each traffic aircraft
    from its solved track (``traffic``: (int_id, PoseTrack) pairs)."""
    from .poses import traffic_state

    def states_at(j: int) -> Dict[str, Dict]:
        out = {str(int(primary_int_id)): {k: float(aircraft_track[j][k]) for k in STATE_KEYS}}
        for int_id, track in traffic:
            state = traffic_state(track, j)
            out[str(int(int_id))] = {k: float(state[k]) for k in STATE_KEYS}
        return out

    return states_at


def camera_record_at(track, j: int) -> Dict:
    """The camera at telemetry sample ``j`` of its solved track, in the
    frame record's own keys and arithmetic (fx = focal x width / sensor)."""
    pose = track.sample(j)
    fx = track.width_px / track.sensor_width_mm
    fy = track.height_px / track.sensor_height_mm
    return {
        "sample_index": int(j), "t_s": pose["t_s"],
        "position_north_m": pose["position_north_m"],
        "position_east_m": pose["position_east_m"],
        "position_alt_m": pose["position_alt_m"],
        "quaternion_wxyz": list(pose["quaternion_wxyz"]),
        "fx_px": pose["focal_length_mm"] * fx, "fy_px": pose["focal_length_mm"] * fy,
        "principal_point_px": [track.width_px / 2.0, track.height_px / 2.0],
        "width_px": track.width_px, "height_px": track.height_px,
    }


def frame_passes_block(camera, track, sample_index: int,
                       states_at: Callable[[int], Dict[str, Dict]]) -> Optional[Dict]:
    """The capture manifest frame's ``passes`` block at build time, or
    None when the camera asks for no pass (absent-canonical). With flow
    asked for, ``neighbours``: the objects' states at the frame's own
    sample (``current``) and the camera and objects at the neighbouring
    telemetry samples (``forward`` / ``backward``, null past either end
    of the track)."""
    words = requested_passes(camera)
    if not words:
        return None
    block: Dict = {"requested": list(words)}
    if "flow" in words:
        n = len(track)
        neighbours: Dict = {"current": {"sample_index": int(sample_index),
                                        "t_s": track.t[sample_index],
                                        "objects": states_at(sample_index)}}
        for direction, step, _ in DIRECTIONS:
            j = sample_index + step
            if 0 <= j < n:
                neighbours[direction] = {"camera": camera_record_at(track, j),
                                         "objects": states_at(j)}
            else:
                neighbours[direction] = None
        block["neighbours"] = neighbours
        block["neighbour_basis"] = ("the neighbouring telemetry samples of the solved "
                                    "tracks (not the neighbouring captured frames); null "
                                    "past either end of the recording")
    return block


# -- geometry (numpy) --------------------------------------------------------------

def _camera_rows(record: Dict):
    """3 x 3 rows (right, -up, forward) in (north, east, up): cam = M d."""
    import numpy as np

    from .labels import camera_axes

    forward, right, up = camera_axes(record["quaternion_wxyz"])
    return np.array([right, [-c for c in up], forward], dtype=np.float64)


def _centre(record: Dict):
    import numpy as np

    return np.array([float(record["position_north_m"]), float(record["position_east_m"]),
                     float(record["position_alt_m"])], dtype=np.float64)


def body_matrix(state: Dict):
    """R with scene = cg + R body, body (forward, right, down), scene
    (north, east, up): the aerospace Z-Y'-X'' DCM of labels.body_to_scene,
    as a matrix (orthogonal; its inverse is its transpose)."""
    import numpy as np

    r = math.radians(float(state["roll_deg"]))
    p = math.radians(float(state["pitch_deg"]))
    y = math.radians(float(state["heading_deg"]))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p), math.sin(p),
                              math.cos(y), math.sin(y))
    return np.array([[cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy],
                     [cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy],
                     [sp, -sr * cp, -cr * cp]], dtype=np.float64)


def _cg(state: Dict):
    import numpy as np

    return np.array([float(state["north_m"]), float(state["east_m"]),
                     float(state["alt_m"])], dtype=np.float64)


def camera_points(record: Dict, depth):
    """(h, w, 3) camera coordinates of every pixel centre at its depth,
    and the (h, w) finite mask (sky and non-positive depths excluded)."""
    import numpy as np

    height, width = depth.shape
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    cx, cy = (float(c) for c in record["principal_point_px"])
    finite = np.isfinite(depth) & (depth > 0.0)
    z = np.where(finite, depth, 0.0).astype(np.float64)
    u = (np.arange(width, dtype=np.float64) + 0.5)[None, :]
    v = (np.arange(height, dtype=np.float64) + 0.5)[:, None]
    cam = np.stack([(u - cx) / fx * z, (v - cy) / fy * z, z], axis=2)
    return cam, finite


def scene_points(record: Dict, depth):
    """(h, w, 3) scene (north, east, up) points and the finite mask."""
    cam, finite = camera_points(record, depth)
    return _centre(record) + cam @ _camera_rows(record), finite


def warp_points(points, mask, finite, states_now: Dict, states_then: Dict):
    """Move every pixel's scene point rigidly with its aircraft object
    (keys are int_id strings or ints); every other pixel stays."""
    import numpy as np

    moved = points.copy()
    then = {int(k): v for k, v in (states_then or {}).items()}
    for key, state in (states_now or {}).items():
        int_id = int(key)
        if int_id not in then:
            continue
        sel = finite & (mask == int_id)
        if not np.any(sel):
            continue
        body = (points[sel] - _cg(state)) @ body_matrix(state)
        moved[sel] = _cg(then[int_id]) + body @ body_matrix(then[int_id]).T
    return moved


def project_points(record: Dict, points):
    """(u, v, z) arrays of scene points through a record's pinhole (u, v
    continuous pixels; z the camera depth, <= 0 behind)."""
    import numpy as np

    cam = (points - _centre(record)) @ _camera_rows(record).T
    fx, fy = float(record["fx_px"]), float(record["fy_px"])
    cx, cy = (float(c) for c in record["principal_point_px"])
    z = cam[..., 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        safe = np.where(z > 0.0, z, 1.0)
        u = cx + fx * cam[..., 0] / safe
        v = cy + fy * cam[..., 1] / safe
    return u, v, z


def ztest_tolerance(front):
    """The depth a warped point may sit behind the nearest one and still
    count as the same surface: 1 % of the nearer depth + 2 m."""
    return ZTEST_TOL_FRACTION * front + ZTEST_TOL_M


def derive_flow(record: Dict, depth, mask, states_now: Dict,
                neighbour: Optional[Dict]):
    """(flow (h, w, 2) float32, bits (h, w) uint8, stats) for one frame and
    one direction. ``neighbour`` is the manifest block's
    ``{camera, objects}`` at the neighbouring sample, or None (no
    neighbour: zeros, bits 0)."""
    import numpy as np

    height, width = depth.shape
    flow = np.zeros((height, width, 2), dtype=np.float32)
    bits = np.zeros((height, width), dtype=np.uint8)
    finite = np.isfinite(depth) & (depth > 0.0)
    stats: Dict = {"surface_pixels": int(np.count_nonzero(finite))}
    if neighbour is None:
        stats.update({"sample_index": None, "t_s": None, "dt_s": None,
                      "valid_fraction": 0.0, "occluded_fraction": 0.0,
                      "out_of_frame_fraction": 0.0, "magnitude_p50_px": None,
                      "magnitude_p95_px": None,
                      "basis": ("no neighbouring telemetry sample in this direction (the "
                                "end of the recording): zeros with every bit 0")})
        return flow, bits, stats
    target = neighbour["camera"]
    points, finite = scene_points(record, depth)
    moved = warp_points(points, mask, finite, states_now, neighbour.get("objects") or {})
    u2, v2, z2 = project_points(target, moved)
    uc = (np.arange(width, dtype=np.float64) + 0.5)[None, :]
    vc = (np.arange(height, dtype=np.float64) + 0.5)[:, None]
    ahead = finite & (z2 > 0.0)
    du = np.where(ahead, u2 - uc, 0.0)
    dv = np.where(ahead, v2 - vc, 0.0)
    w2, h2 = int(target["width_px"]), int(target["height_px"])
    inside = ahead & (u2 >= 0.0) & (u2 < w2) & (v2 >= 0.0) & (v2 < h2)
    outside = finite & ~inside
    # The z-test: splat every in-frame warped point at its depth into the
    # four pixels whose centres surround it; the nearest wins.
    zs = z2[inside]
    us, vs = u2[inside], v2[inside]
    ids = np.asarray(mask)[inside].astype(np.int64)
    zbuf = np.full((h2, w2), np.inf)
    idbuf = np.full((h2, w2), -1, dtype=np.int64)
    i0 = np.floor(us - 0.5).astype(np.int64)
    j0 = np.floor(vs - 0.5).astype(np.int64)
    splats = []
    for di in (0, 1):
        for dj in (0, 1):
            ii, jj = i0 + di, j0 + dj
            ok = (ii >= 0) & (ii < w2) & (jj >= 0) & (jj < h2)
            np.minimum.at(zbuf, (jj[ok], ii[ok]), zs[ok])
            splats.append((jj[ok], ii[ok], zs[ok], ids[ok]))
    for jj, ii, z, owner in splats:              # the object the nearest splat belongs to
        nearest = z == zbuf[jj, ii]
        idbuf[jj[nearest], ii[nearest]] = owner[nearest]
    cj, ci = np.floor(vs).astype(np.int64), np.floor(us).astype(np.int64)
    front, front_id = zbuf[cj, ci], idbuf[cj, ci]
    occluded = (front_id != ids) & (zs > front + ztest_tolerance(front))
    bits[inside] = np.where(occluded, FLOW_OCCLUDED, FLOW_VALID).astype(np.uint8)
    bits[outside] = FLOW_OUT_OF_FRAME
    flow[..., 0] = du.astype(np.float32)
    flow[..., 1] = dv.astype(np.float32)
    surface = max(1, int(np.count_nonzero(finite)))
    valid = bits == FLOW_VALID
    magnitude = np.hypot(flow[..., 0], flow[..., 1])[valid].astype(np.float64)
    stats.update({
        "sample_index": target.get("sample_index"), "t_s": target.get("t_s"),
        "dt_s": (None if target.get("t_s") is None or record.get("t_s") is None
                 else float(target["t_s"]) - float(record["t_s"])),
        "valid_fraction": float(np.count_nonzero(valid)) / surface,
        "occluded_fraction": float(np.count_nonzero(bits == FLOW_OCCLUDED)) / surface,
        "out_of_frame_fraction": float(np.count_nonzero(bits == FLOW_OUT_OF_FRAME)) / surface,
        "magnitude_p50_px": float(np.percentile(magnitude, 50)) if magnitude.size else None,
        "magnitude_p95_px": float(np.percentile(magnitude, 95)) if magnitude.size else None,
        "basis": ("rigid motion of each aircraft object between the two samples, static "
                  "world otherwise; occlusion by the z-test at 1 % + 2 m against another "
                  "object's surface in the splatted z-buffer of the surfaces this frame sees"),
    })
    return flow, bits, stats


def derive_disparity(record: Dict, depth, baseline_m: float):
    """(disparity (h, w) float32 pixels, stats): d = f_x B / Z, 0 for sky."""
    import numpy as np

    finite = np.isfinite(depth) & (depth > 0.0)
    fx = float(record["fx_px"])
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(finite, fx * float(baseline_m) / np.where(finite, depth, 1.0), 0.0)
    d = d.astype(np.float32)
    values = d[finite]
    return d, {"baseline_m": float(baseline_m), "fx_px": fx,
               "pixels": int(values.size),
               "d_min_px": float(values.min()) if values.size else None,
               "d_max_px": float(values.max()) if values.size else None,
               "basis": "d = f_x B / Z of the left camera's depth; 0 for sky (Z infinite)"}


def derive_points(record: Dict, depth, mask):
    """(points (N, 4) float32, ids (N,) uint8, stats): every finite-depth
    pixel's camera-frame point, reflectance 0, row-major; the sky
    contributes none."""
    import numpy as np

    cam, finite = camera_points(record, depth)
    if mask.size and int(np.max(mask)) > 255:
        raise PassError("annotation.points",
                        f"the ID image holds {int(np.max(mask))}, beyond the one byte "
                        f"the point id sidecar stores")
    points = np.zeros((int(np.count_nonzero(finite)), 4), dtype=np.float32)
    points[:, :3] = cam[finite].astype(np.float32)
    ids = mask[finite].astype(np.uint8)
    per_object: Dict[str, int] = {}
    values, counts = np.unique(ids, return_counts=True)
    for value, count in zip(values, counts):
        per_object[str(int(value))] = int(count)
    return points, ids, {"total": int(points.shape[0]), "per_object": per_object,
                         "sky_pixels": int(np.count_nonzero(~finite)),
                         "reflectance": 0.0,
                         "basis": ("every finite-depth pixel back-projected through the "
                                   "pinhole, camera frame (x right, y down, z forward); "
                                   "reflectance 0 (no intensity model); the sky "
                                   "contributes none")}


# -- files --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path: Path, array, dtype: str) -> Dict[str, str]:
    import numpy as np

    np.ascontiguousarray(array, dtype=dtype).tofile(path)
    return {"file": path.name, "sha256": _sha256(path)}


def read_flow_file(path, width: int, height: int):
    """``_flow_fw.f32`` / ``_flow_bw.f32`` -> (h, w, 2) float32; refuses a
    wrong size (annotation.flow)."""
    import numpy as np

    raw = np.fromfile(Path(path), dtype="<f4")
    if raw.size != width * height * 2:
        raise PassError("annotation.flow", f"{Path(path).name}: {raw.size} float32 values "
                                           f"for a {width}x{height} flow")
    return raw.reshape(height, width, 2)


def read_valid_file(path, width: int, height: int):
    """``_flow_*_valid.u8`` -> (h, w) uint8 bits."""
    import numpy as np

    raw = np.fromfile(Path(path), dtype=np.uint8)
    if raw.size != width * height:
        raise PassError("annotation.flow", f"{Path(path).name}: {raw.size} bytes for a "
                                           f"{width}x{height} validity image")
    return raw.reshape(height, width)


def read_disparity_file(path, width: int, height: int):
    import numpy as np

    raw = np.fromfile(Path(path), dtype="<f4")
    if raw.size != width * height:
        raise PassError("annotation.disparity", f"{Path(path).name}: {raw.size} float32 "
                                                f"values for a {width}x{height} disparity")
    return raw.reshape(height, width)


def read_points_file(path):
    """``_points.f32`` -> (N, 4) float32."""
    import numpy as np

    raw = np.fromfile(Path(path), dtype="<f4")
    if raw.size % 4:
        raise PassError("annotation.points", f"{Path(path).name}: {raw.size} float32 values "
                                             f"is not N x 4")
    return raw.reshape(-1, 4)


def read_points_ids(path):
    import numpy as np

    return np.fromfile(Path(path), dtype=np.uint8)


def _read_f32_rgb(path, width: int, height: int, what: str):
    import numpy as np

    raw = np.fromfile(Path(path), dtype="<f4")
    if raw.size != width * height * 3:
        raise PassError("sensing.pass", f"{Path(path).name}: {raw.size} float32 values for a "
                                        f"{width}x{height} {what} (3 per pixel)")
    return raw.reshape(height, width, 3)


def read_normal_f32(path, width: int, height: int):
    """S4's linear normal file (3 x float32 per pixel, scene frame north,
    east, up) -> (h, w, 3) float32."""
    return _read_f32_rgb(path, width, height, "normal image")


def read_basecolor_f32(path, width: int, height: int):
    """S4's linear base colour file (3 x float32 per pixel) -> (h, w, 3)."""
    return _read_f32_rgb(path, width, height, "base colour image")


def read_normal_pass(folder, engine: Dict, width: int, height: int):
    """The frame's normals from whichever file the render record declares:
    S4's ``normal_f32`` when present, else I6's 16-bit ``normal_png``;
    None when neither is declared."""
    from .labels import read_normal_png

    folder = Path(folder)
    if engine.get(NORMAL_F32_KEY):
        return read_normal_f32(folder / str(engine[NORMAL_F32_KEY]), width, height)
    if engine.get("normal_png"):
        return read_normal_png(folder / str(engine["normal_png"]))
    return None


def read_basecolor_pass(folder, engine: Dict, width: int, height: int):
    """The frame's base colour: S4's ``basecolor_f32``, else I6's 16-bit
    ``albedo_png``; None when neither is declared."""
    from .labels import read_albedo_png

    folder = Path(folder)
    if engine.get(BASECOLOR_F32_KEY):
        return read_basecolor_f32(folder / str(engine[BASECOLOR_F32_KEY]), width, height)
    if engine.get("albedo_png"):
        return read_albedo_png(folder / str(engine["albedo_png"]))
    return None


# -- attach (after a render) -------------------------------------------------------

def _frame_summary(entry: Dict) -> Dict:
    """What the manifest's per-frame ``passes`` block repeats of the
    passes.json entry: the numbers, not the file table."""
    out: Dict = {}
    if "flow" in entry:
        out["flow"] = {d: {k: s.get(k) for k in ("sample_index", "valid_fraction",
                                                  "occluded_fraction", "out_of_frame_fraction",
                                                  "magnitude_p50_px", "magnitude_p95_px")}
                       for d, s in entry["flow"].items()}
    if "disparity" in entry:
        out["disparity"] = {k: entry["disparity"].get(k)
                            for k in ("baseline_m", "d_min_px", "d_max_px", "pixels")}
    if "points" in entry:
        out["points"] = {"total": entry["points"]["total"],
                         "per_object": dict(entry["points"]["per_object"])}
    return out


def attach_passes(run_dir, manifest: Optional[Dict] = None, write: bool = True) -> Dict:
    """Derive every requested flow / disparity / points pass from the
    render bundle beside the frames, write the files and each camera's
    ``passes.json``, fill the manifest frames' ``passes`` blocks and add
    the ``passes.*`` records. ``manifest`` given: it is updated in place
    and NOT written (the caller writes it, as attach_engine_labels does);
    else the run's manifest is read and written back with its sidecars.

    A frame whose camera asks for a derived pass and has no bundle keeps
    its block with ``derived: null`` and the reason (a headless run). A
    bundle without the depth (or, for flow and points, the ID image), a
    disparity asked of a camera that is not a rig's left, refuse by the
    pass's own name (:class:`PassError`)."""
    from .labels import _attach_record, _bundle_records, _read_id_png, read_depth_f32, read_depth_png
    from .manifest import read_capture_manifest, write_capture_manifest, write_frame_sidecars

    run_dir = Path(run_dir)
    own = manifest is None
    if own:
        manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    rigs = {str(b.get("camera_id")): b.get("stereo") for b in manifest.get("cameras", [])
            if isinstance(b, dict)}
    summary: Dict = {"frames": 0, "derived": 0, "without_bundle": 0, "cameras": [],
                     "written": False}
    documents: Dict[str, Dict] = {}
    bundles: Dict[str, Dict] = {}
    gathered: Dict[str, List[Dict]] = {"flow": [], "disparity": [], "points": []}
    for frame in manifest.get("frames", []):
        block = frame.get("passes")
        if not isinstance(block, dict):
            continue
        words = [w for w in block.get("requested") or [] if w in ("flow", "disparity", "points")]
        if not words:
            continue
        summary["frames"] += 1
        camera = str(frame["camera_id"])
        camera_dir = run_dir / "frames" / camera
        if camera not in bundles:
            bundles[camera] = _bundle_records(camera_dir)
        name = Path(str(frame["file"])).name
        engine = bundles[camera].get(name)
        if engine is None:
            summary["without_bundle"] += 1
            block["derived"] = None
            block["derived_basis"] = ("no engine bundle for this frame (no render.json record "
                                      "with labels): nothing to derive the passes from")
            continue
        labels = engine["labels"]
        width, height = int(frame["width_px"]), int(frame["height_px"])
        if labels.get("depth_f32"):
            depth = read_depth_f32(camera_dir / str(labels["depth_f32"]), width, height)
            depth_file = str(labels["depth_f32"])
        elif labels.get("depth"):
            depth = read_depth_png(camera_dir / str(labels["depth"]),
                                   float(labels.get("depth_scale_m", 0.1)),
                                   float(labels.get("depth_saturation_m", 6553.5)))
            depth_file = f"{labels['depth']} (16-bit at depth_scale_m)"
        else:
            raise PassError(NO_DEPTH_REFUSAL[words[0]],
                            f"{camera}/{name}: the bundle declares no depth; the {words[0]} "
                            f"pass is derived from it")
        mask = None
        if labels.get("mask"):
            mask = _read_id_png(camera_dir / str(labels["mask"]))
        stem = name[:-len(".png")]
        entry: Dict = {"frame": name, "t_s": frame.get("t_s"),
                       "sample_index": frame.get("sample_index"),
                       "inputs": {"depth": depth_file, "mask": labels.get("mask")},
                       "files": {}}
        if "flow" in words:
            if mask is None:
                raise PassError("annotation.flow", f"{camera}/{name}: the bundle declares no ID "
                                                   f"image; flow needs it to move each object")
            neighbours = block.get("neighbours") or {}
            current = (neighbours.get("current") or {}).get("objects") or {}
            entry["flow"] = {}
            for direction, _, tag in DIRECTIONS:
                flow, bits, stats = derive_flow(frame, depth, mask, current,
                                                neighbours.get(direction))
                entry["files"][f"flow_{tag}"] = _write(
                    camera_dir / f"{stem}{PASS_SUFFIXES[f'flow_{tag}']}", flow, "<f4")
                entry["files"][f"flow_{tag}_valid"] = _write(
                    camera_dir / f"{stem}{PASS_SUFFIXES[f'flow_{tag}_valid']}", bits, "u1")
                entry["flow"][direction] = stats
                gathered["flow"].append(stats)
        if "disparity" in words:
            rig = rigs.get(camera)
            if not isinstance(rig, dict) or rig.get("role") != "left":
                raise PassError("annotation.disparity",
                                f"{camera}/{name}: disparity is the left camera's of a stated "
                                f"stereo rig, and this camera is not one")
            d, stats = derive_disparity(frame, depth, float(rig["baseline_m"]))
            stats["right_camera_id"] = rig.get("right_camera_id")
            entry["files"]["disparity"] = _write(
                camera_dir / f"{stem}{PASS_SUFFIXES['disparity']}", d, "<f4")
            entry["disparity"] = stats
            gathered["disparity"].append(stats)
        if "points" in words:
            if mask is None:
                raise PassError("annotation.points", f"{camera}/{name}: the bundle declares no "
                                                     f"ID image; the point ids are read from it")
            points, ids, stats = derive_points(frame, depth, mask)
            entry["files"]["points"] = _write(
                camera_dir / f"{stem}{PASS_SUFFIXES['points']}", points, "<f4")
            entry["files"]["points_id"] = _write(
                camera_dir / f"{stem}{PASS_SUFFIXES['points_id']}", ids, "u1")
            entry["points"] = stats
            gathered["points"].append(stats)
        document = documents.setdefault(camera, {
            "passes_version": PASSES_VERSION, "camera_id": camera,
            "conventions": CONVENTIONS,
            "ztest": {"tolerance_fraction": ZTEST_TOL_FRACTION, "tolerance_m": ZTEST_TOL_M},
            "bits": {"valid": FLOW_VALID, "occluded": FLOW_OCCLUDED,
                     "out_of_frame": FLOW_OUT_OF_FRAME},
            "frames": []})
        document["frames"].append(entry)
        block["file"] = f"frames/{camera}/{PASSES_FILE}"
        block["derived"] = _frame_summary(entry)
        summary["derived"] += 1
    for camera, document in documents.items():
        path = run_dir / "frames" / camera / PASSES_FILE
        path.write_text(json.dumps(document, indent=1), encoding="utf-8")
        digest = _sha256(path)
        for frame in manifest.get("frames", []):
            block = frame.get("passes")
            if str(frame.get("camera_id")) == camera and isinstance(block, dict) \
                    and block.get("file"):
                block["sha256"] = digest
        summary["cameras"].append(camera)
    for record in pass_records(gathered):
        _attach_record(manifest, record)
    if own and write and summary["derived"]:
        write_capture_manifest(manifest, run_dir)
        write_frame_sidecars(manifest, run_dir)
        summary["written"] = True
    return summary


# -- the records (rule 0), each null test measured here --------------------------

def synthetic_scene(width: int = 24, height: int = 16):
    """A level camera at the origin looking north over a ground plane 20 m
    below (the upper rows are sky): the record and its depth. Used by
    the records' null tests; deterministic."""
    import numpy as np

    record = {"quaternion_wxyz": [1.0, 0.0, 0.0, 0.0], "position_north_m": 0.0,
              "position_east_m": 0.0, "position_alt_m": 0.0, "fx_px": 20.0, "fy_px": 20.0,
              "principal_point_px": [width / 2.0, height / 2.0], "width_px": width,
              "height_px": height, "t_s": 0.0}
    v = (np.arange(height, dtype=np.float64) + 0.5)[:, None]
    slope = (v - height / 2.0) / 20.0
    with np.errstate(divide="ignore"):
        depth = np.where(slope > 0.0, 20.0 / np.where(slope > 0.0, slope, 1.0), np.inf)
    depth = np.broadcast_to(depth, (height, width)).copy()
    return record, depth


def flow_null_tests() -> Dict:
    """Measured on :func:`synthetic_scene`: a static scene (the camera and
    every object where they were) gives zero flow; the hidden-aircraft
    control (no aircraft in the frame, the camera moved 1 m north) gives
    terrain flow."""
    import numpy as np

    record, depth = synthetic_scene()
    mask = np.zeros(depth.shape, dtype=np.uint8)
    still, _, _ = derive_flow(record, depth, mask, {}, {"camera": dict(record), "objects": {}})
    moved_camera = dict(record, position_north_m=1.0, t_s=0.1)
    terrain, bits, _ = derive_flow(record, depth, mask, {}, {"camera": moved_camera, "objects": {}})
    speed = np.hypot(terrain[..., 0], terrain[..., 1])[bits == FLOW_VALID]
    return {"static_max_px": float(np.abs(still).max()),
            "hidden_aircraft_terrain_p95_px": float(np.percentile(speed, 95)) if speed.size else 0.0}


def pass_records(gathered: Dict[str, List[Dict]]) -> List:
    """The ``passes.flow`` / ``passes.disparity`` / ``passes.points``
    AppliedVariables for what a bundle derived (none for a pass not
    derived), each null test measured here on the synthetic scene."""
    import numpy as np

    from ..records import AppliedVariable, NullTest

    out = []
    flows = gathered.get("flow") or []
    if flows:
        nulls = flow_null_tests()
        p95 = [s["magnitude_p95_px"] for s in flows if s.get("magnitude_p95_px") is not None]
        out.append(AppliedVariable(
            name="passes.flow", value=max(p95) if p95 else 0.0, unit="px", source="derived",
            model_name=("rigid-object optical flow, forward and backward to the neighbouring "
                   "telemetry samples, validity bits by the z-test (Menze & Geiger 2015)"),
            parameters={"directions": len(flows),
                        "valid_fraction_min": min(s["valid_fraction"] for s in flows),
                        "occluded_fraction_max": max(s["occluded_fraction"] for s in flows),
                        "ztest_tolerance": {"fraction": ZTEST_TOL_FRACTION, "m": ZTEST_TOL_M},
                        "hidden_aircraft_control": {
                            "terrain_p95_px": nulls["hidden_aircraft_terrain_p95_px"],
                            "basis": "no aircraft in the frame, the camera moved 1 m north: "
                                     "the terrain still flows (the control reaches)"}},
            references=tuple(CONVENTIONS["references"][:2]),
            frame_keys=("passes.derived.flow",),
            null_test=NullTest(
                quantity="largest |flow| on a static scene", unit="px",
                with_value=nulls["static_max_px"], without_value=0.0, threshold=1e-9,
                kind="bounded",
                note="the synthetic ground plane with the camera and every object where "
                     "they were: zero flow to the back-projection's float rounding "
                     "(measured 1.8e-15 px)"),
            not_claimed=("flow on non-rigid parts (control surfaces, propellers)",
                         "occluders the source frame does not see",
                         "a surface hiding itself (a ridge its valley, a wing its fuselage)",
                         "the engine's velocity pass on real pixels (S4, Windows)")))
    disparities = gathered.get("disparity") or []
    if disparities:
        record, depth = synthetic_scene()
        zero, _ = derive_disparity(record, depth, 0.0)
        stated, _ = derive_disparity(record, depth, float(disparities[0]["baseline_m"]))
        out.append(AppliedVariable(
            name="passes.disparity", value=float(disparities[0]["baseline_m"]), unit="m",
            source="user", model_name="d = f_x B / Z over a rig rectified by construction",
            parameters={"frames": len(disparities),
                        "d_min_px": min((s["d_min_px"] for s in disparities
                                         if s["d_min_px"] is not None), default=None),
                        "d_max_px": max((s["d_max_px"] for s in disparities
                                         if s["d_max_px"] is not None), default=None),
                        "synthetic_d_max_at_baseline_px": float(stated.max())},
            frame_keys=("passes.derived.disparity",),
            null_test=NullTest(
                quantity="largest disparity with the baseline at 0", unit="px",
                with_value=float(np.abs(zero).max()), without_value=0.0, threshold=0.0,
                kind="bounded", note="B -> 0 gives d -> 0 on the synthetic ground plane"),
            not_claimed=("a real rig's calibration (rectified by construction)",
                         "a stereo matcher's output")))
    points = gathered.get("points") or []
    if points:
        record, depth = synthetic_scene()
        mask = np.zeros(depth.shape, dtype=np.uint8)
        cloud, _, stats = derive_points(record, depth, mask)
        sky_points = int(cloud.shape[0]) - int(np.count_nonzero(np.isfinite(depth)))
        out.append(AppliedVariable(
            name="passes.points", value=int(sum(s["total"] for s in points)), unit="point",
            source="derived", model_name="depth back-projection per pixel, ids from the ID image",
            parameters={"frames": len(points), "reflectance": 0.0,
                        "per_object_total": _sum_counts(s["per_object"] for s in points)},
            frame_keys=("passes.derived.points",),
            null_test=NullTest(
                quantity="points contributed by sky pixels", unit="point",
                with_value=float(sky_points), without_value=0.0, threshold=0.0, kind="bounded",
                note=f"the synthetic scene's {stats['sky_pixels']} sky pixels contribute none"),
            not_claimed=("a beam model (no lidar returns, no range noise)",
                         "an intensity: the reflectance column is 0")))
    return out


def _sum_counts(dicts) -> Dict[str, int]:
    total: Dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            total[k] = total.get(k, 0) + int(v)
    return total


def amodal_null_test() -> Dict:
    """Measured on a synthetic mask pair: a 10 x 10 object with 4 columns
    covered by an occluder -- the amodal / visible pixel ratio equals
    1 / visible_fraction."""
    import numpy as np

    alone = np.zeros((12, 12), dtype=np.uint8)
    alone[1:11, 1:11] = 1
    mask = alone.copy()
    mask[1:11, 1:5] = 2
    visible = int(np.count_nonzero(mask == 1))
    amodal = int(np.count_nonzero(alone == 1))
    ratio = amodal / visible
    return {"ratio": ratio, "inverse_visible_fraction": 1.0 / (visible / amodal)}


def amodal_record(ratios: Sequence[float], refused: int):
    """The ``passes.amodal`` AppliedVariable: the mean amodal / visible
    ratio over the objects labelled, the null measured on a synthetic pair."""
    from ..records import AppliedVariable, NullTest

    null = amodal_null_test()
    finite = [r for r in ratios if r is not None]
    return AppliedVariable(
        name="passes.amodal", value=(sum(finite) / len(finite)) if finite else None, unit="1",
        source="derived",
        model_name="the tight box and footprint of each aircraft's alone pass (basis 'alone pass')",
        parameters={"objects": len(ratios), "refused": int(refused)},
        references=("Zhu et al. 2017, Semantic amodal segmentation (CVPR)",),
        frame_keys=("labels.objects[].amodal_bbox_2d", "labels.objects[].amodal_mask"),
        null_test=NullTest(
            quantity="amodal / visible ratio minus 1 / visible_fraction", unit="1",
            with_value=null["ratio"], without_value=null["inverse_visible_fraction"],
            threshold=1e-12, kind="bounded",
            note="a 10 x 10 object with 4 columns occluded: the ratio is 1 / visible_fraction"),
        not_claimed=("amodal masks for non-aircraft objects (the terrain has no alone pass)",))
