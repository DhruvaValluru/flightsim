"""S2: the stereo rig -- a right camera derived from a stated camera.

``cameras[i].stereo = {baseline_m, side}`` on a stated camera asks for a
rectified stereo pair. The right camera is not stated by the user and is
not in ``spec.cameras`` (the spec digest is the user's); the capture
solver MATERIALISES it (:func:`with_stereo_right`) as a
:class:`~core.scenario.camera.CameraSpec` whose ``position_mode`` is
``stereo_right`` and appends it to the cameras that fly, so the card, the
render and the manifest carry it exactly like any other camera.

Rectified BY CONSTRUCTION, stated once:

* the right camera's centre is the left camera's centre moved
  ``baseline_m`` along the LEFT camera's right axis (the manifest's
  quaternion convention, :func:`core.capture.labels.camera_axes`), at
  every telemetry sample of the solved track;
* its orientation is the left camera's quaternion, sample for sample
  (parallel optical axes, the same roll), and its intrinsics are the
  left's (focal length per sample, sensor, pixels, near/far), so the
  principal points coincide and epipolar lines are image rows;
* its capture schedule is the left's (the same sample indices), so
  every left frame has its right frame at the same instant.

Hence a scene point at camera depth Z sits at the same Z and the same
row in both images, ``d = f_x B / Z`` pixels to the left in the right
image (core/capture/passes.py writes it). Nothing is estimated: a real
rig's calibration error, lens distortion and rolling shutter are not
modelled, and the disparity is not a stereo matcher's output.

Refusals, by name ``sensing.stereo``: a stereo block that is not a
mapping of exactly {baseline_m, side}; a baseline that is not a finite
number, is zero or negative, or is larger than
:data:`STEREO_MAX_BASELINE_M`; a side other than ``right``; a camera
whose derived right id would not fit the identifier rail or would
collide with a stated camera; a stereo block on a camera that is itself
a derived right camera.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List, Optional, Sequence

from ..scenario.camera import CameraSpec
from ..scenario.fields import Quantity, Source

#: The position mode of a materialised right camera (not a user mode:
#: core/scenario/camera.py POSITION_MODES does not list it, so a spec that
#: states it refuses camera.preset by the existing rule).
STEREO_RIGHT_MODE = "stereo_right"
#: The only side modelled: the derived camera sits to the RIGHT of the
#: stated one (KITTI's image_2 / image_3 convention: the stated camera is
#: the left, reference image).
STEREO_SIDES = ("right",)
STEREO_KEYS = ("baseline_m", "side")
#: The widest baseline a rig may state, metres. A stated rail, not a
#: physical limit: aerial stereo rigs span centimetres to a few metres
#: and a wide-baseline pair tens of metres; beyond 100 m the "pair" is
#: two cameras whose views share little of the aircraft at chase range,
#: and a rectified rig of that size is not a thing anyone builds.
STEREO_MAX_BASELINE_M = 100.0
#: The right camera's id: the stated camera's id with this suffix.
RIGHT_SUFFIX = "_right"
#: The identifier rail core/capture/validate.py enforces (restated here
#: to keep this module free of the validator; tests pin the two equal).
CAMERA_ID_MAX_LEN = 64


class StereoError(Exception):
    """A stereo block the rig cannot be built from; named, never guessed."""

    constraint = "sensing.stereo"

    def __init__(self, message: str):
        super().__init__(f"sensing.stereo: {message}")
        self.message = message


def stereo_problem(value) -> Optional[str]:
    """The one sentence a stated stereo block is refused with, or None.
    ``value`` is the Quantity's value (None = not stated)."""
    if value is None:
        return None
    if not isinstance(value, dict):
        return (f"the stereo block must be a mapping of baseline_m and side, "
                f"got {type(value).__name__}")
    unknown = sorted(set(value) - set(STEREO_KEYS))
    missing = [k for k in STEREO_KEYS if k not in value]
    if unknown or missing:
        return (f"the stereo block takes exactly {list(STEREO_KEYS)}; "
                + (f"unknown {unknown}" if unknown else "")
                + ("; " if unknown and missing else "")
                + (f"missing {missing}" if missing else ""))
    baseline = value["baseline_m"]
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) \
            or not math.isfinite(float(baseline)):
        return f"baseline_m must be a finite number of metres, got {baseline!r}"
    if float(baseline) <= 0.0:
        return (f"a baseline of {float(baseline):g} m is not a rig: the right "
                f"camera must sit a positive distance to the right")
    if float(baseline) > STEREO_MAX_BASELINE_M:
        return (f"a baseline of {float(baseline):g} m exceeds the "
                f"{STEREO_MAX_BASELINE_M:g} m bound a stereo rig may state")
    if value["side"] not in STEREO_SIDES:
        return (f"side {value['side']!r} is not modelled; the derived camera "
                f"sits to the right of the stated one (side: right)")
    return None


def stereo_of(camera) -> Optional[Dict[str, object]]:
    """``{baseline_m, side}`` of a camera's stated rig, or None. Refuses
    by name (:class:`StereoError`) a block that fails :func:`stereo_problem`."""
    q = getattr(camera, "stereo", None)
    value = getattr(q, "value", None)
    problem = stereo_problem(value)
    if problem:
        raise StereoError(problem)
    if value is None:
        return None
    return {"baseline_m": float(value["baseline_m"]), "side": str(value["side"])}


def right_camera_id(camera_id: str) -> str:
    return f"{camera_id}{RIGHT_SUFFIX}"


def is_stereo_right(camera) -> bool:
    """A materialised right camera (never a stated one)."""
    return str(getattr(getattr(camera, "position_mode", None), "value", "")) == STEREO_RIGHT_MODE


def stereo_violations(camera, index: int = 0,
                      stated_ids: Sequence[str] = ()) -> List:
    """``sensing.stereo`` for one stated camera, as validator Violations:
    the block's own shape and bound, and the derived id's fit (the
    identifier rail, no collision with a stated camera)."""
    from ..scenario.validate import Violation

    who = f"camera[{index}] {str(camera.camera_id.value)!r}"
    value = getattr(getattr(camera, "stereo", None), "value", None)
    if value is None:
        return []
    problem = stereo_problem(value)
    if problem:
        baseline = value.get("baseline_m") if isinstance(value, dict) else None
        return [Violation("sensing.stereo", f"{who}: {problem}",
                          actual=float(baseline) if isinstance(baseline, (int, float))
                          and not isinstance(baseline, bool) else None,
                          limit=STEREO_MAX_BASELINE_M, unit="m")]
    right = right_camera_id(str(camera.camera_id.value))
    if len(right) > CAMERA_ID_MAX_LEN:
        return [Violation("sensing.stereo",
                          f"{who}: the right camera's id {right!r} would be "
                          f"{len(right)} characters, over the {CAMERA_ID_MAX_LEN} a "
                          f"camera id may take; shorten the stated id")]
    if right in set(str(i) for i in stated_ids):
        return [Violation("sensing.stereo",
                          f"{who}: the right camera's id {right!r} is already a "
                          f"stated camera's; the rig's frames could not be told apart")]
    return []


def right_camera_spec(left: CameraSpec) -> CameraSpec:
    """The right camera of ``left``'s rig: the left's every field (the
    intrinsics, the schedule, the preset and aim it inherits the track
    of), its own id, ``position_mode`` ``stereo_right`` (source derived,
    the rig named), the left's stereo block (so the baseline travels
    with it), and the left's passes without ``disparity`` (the right
    camera has no right partner)."""
    rig = stereo_of(left)
    if rig is None:
        raise StereoError(f"camera {left.camera_id.value!r} states no stereo rig")
    if is_stereo_right(left):
        raise StereoError(f"camera {left.camera_id.value!r} is itself a derived right camera")
    frm = (f"stereo rig of camera {left.camera_id.value!r}: baseline "
           f"{rig['baseline_m']:g} m along its right axis, rectified by construction")
    right = CameraSpec.from_dict(left.to_dict())
    right.camera_id = Quantity(value=right_camera_id(str(left.camera_id.value)),
                               source=Source.DERIVED, frm=frm)
    right.position_mode = Quantity(value=STEREO_RIGHT_MODE, source=Source.DERIVED, frm=frm)
    words = getattr(left.passes, "value", None)
    if isinstance(words, list):
        kept = [w for w in words if w != "disparity"]
        right.passes = Quantity(value=kept or None, source=Source.DERIVED,
                                frm=f"{frm}; the left camera's passes without disparity")
    return right


def with_stereo_right(cameras: Sequence[CameraSpec]) -> List[CameraSpec]:
    """The cameras that fly: every stated camera, then the derived right
    camera of each stated rig, in stated order. A list without a rig is
    returned as a copy of itself (nothing appended)."""
    flown = list(cameras)
    present = {str(c.camera_id.value) for c in cameras}
    for camera in cameras:
        if is_stereo_right(camera):
            continue
        if stereo_of(camera) is not None and \
                right_camera_id(str(camera.camera_id.value)) not in present:
            flown.append(right_camera_spec(camera))
    return flown


def left_of(right: CameraSpec, cameras: Sequence[CameraSpec]) -> CameraSpec:
    """The stated camera a materialised right camera was derived from."""
    for camera in cameras:
        if not is_stereo_right(camera) and \
                right_camera_id(str(camera.camera_id.value)) == str(right.camera_id.value):
            return camera
    raise StereoError(f"no stated camera owns the right camera {right.camera_id.value!r}")


def right_track(left_track, baseline_m: float, camera_id: str):
    """The right camera's pose track: the left track's every sample with
    the centre moved ``baseline_m`` along that sample's right axis;
    orientation, Euler angles, focal length and every intrinsic
    unchanged. Pure arithmetic on the solved track."""
    from .labels import camera_axes

    north, east, alt = [], [], []
    for i in range(len(left_track)):
        _, right, _ = camera_axes(left_track.quat[i])
        north.append(left_track.north_m[i] + baseline_m * right[0])
        east.append(left_track.east_m[i] + baseline_m * right[1])
        alt.append(left_track.alt_m[i] + baseline_m * right[2])
    return replace(left_track, camera_id=str(camera_id), north_m=tuple(north),
                   east_m=tuple(east), alt_m=tuple(alt))


def right_schedule(left_schedule, camera_id: str):
    """The left schedule under the right camera's id: the same sample
    indices and times, so the pair is captured at one instant."""
    return replace(left_schedule, camera_id=str(camera_id),
                   basis=f"{left_schedule.basis} (the stereo rig's left schedule)")


def solve_rig(cameras: Sequence[CameraSpec], tracks: List, schedules: List) -> None:
    """Replace, in place, every materialised right camera's track and
    schedule with the ones derived from its left camera's (``tracks`` and
    ``schedules`` are parallel to ``cameras``; a right camera's entries
    may be anything -- they are overwritten)."""
    index = {str(c.camera_id.value): i for i, c in enumerate(cameras)}
    for i, camera in enumerate(cameras):
        if not is_stereo_right(camera):
            continue
        left = left_of(camera, cameras)
        j = index[str(left.camera_id.value)]
        rig = stereo_of(left)
        tracks[i] = right_track(tracks[j], float(rig["baseline_m"]), str(camera.camera_id.value))
        schedules[i] = right_schedule(schedules[j], str(camera.camera_id.value))


def manifest_stereo_block(camera, cameras: Sequence) -> Optional[Dict[str, object]]:
    """The capture manifest camera block's ``stereo`` key for a camera in a
    rig (left or right), or None (absent-canonical: a camera outside any
    rig gains no key)."""
    if camera is None:
        return None
    if is_stereo_right(camera):
        left = left_of(camera, cameras)
        role = "right"
    else:
        if stereo_of(camera) is None:
            return None
        flying = {str(c.camera_id.value) for c in cameras}
        if right_camera_id(str(camera.camera_id.value)) not in flying:
            return None             # a path that did not materialise the right camera
        left = camera
        role = "left"
    rig = stereo_of(left)
    return {
        "role": role,
        "left_camera_id": str(left.camera_id.value),
        "right_camera_id": right_camera_id(str(left.camera_id.value)),
        "baseline_m": float(rig["baseline_m"]),
        "side": str(rig["side"]),
        "rectified": ("by construction: the right centre is the left centre plus "
                      "baseline_m along the left camera's right axis at every sample; "
                      "the same quaternion, focal length, sensor, pixels and schedule"),
        "not_claimed": ["a real rig's calibration error, lens distortion and rolling "
                        "shutter", "a stereo matcher's disparity (the pass is geometric)"],
    }
