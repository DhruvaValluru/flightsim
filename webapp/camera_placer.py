"""The 3D camera placer: terrain in, one exactly-placed camera out.

The picker's presets and the sentence reader both land a camera
somewhere sensible; neither lets the user put it at an EXACT spot and
see the result before anything runs. The placer is the page's 3D view
of the scene the spec will fly over -- the same raster pick_scene
chooses, in the same local north/east frame the pose solver uses -- with
the camera's x / y / z (east / north / altitude MSL) and aim as numbers
the user moves. This module is the server half:

* :func:`terrain_payload` samples the scene raster (or the flat datum)
  on a regular grid about the spec origin, plus the aircraft's start
  pose, its straight-line track estimate and any placed traffic, so the
  page draws the scene without a second copy of the frame conventions.
* :func:`place_camera` turns the numbers the page sends into a
  CameraSpec whose placement fields are USER-stated ("placed in the 3D
  camera placer") -- an ``explicit`` world-anchored camera, or a
  ``chase`` camera riding the aircraft at a stated offset -- and returns
  the scene refusals that name it, so a camera under the ground is
  refused by name here, not after the render queue.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.scenario.camera import (
    DEFAULT_FOCAL_MM,
    DEFAULT_SENSOR_H_MM,
    DEFAULT_SENSOR_W_MM,
    CameraSpec,
    plan_full_capture,
)
from core.scenario.spec import ScenarioSpec

#: Grid points per side the page draws: 129 x 129 = 33 k vertices, fast
#: in WebGL and fine enough to read a ridge line at a 10 km window.
GRID_POINTS = 129
#: Half-width of the window about the origin, metres: at least this,
#: grown to cover the clip's straight-line track, capped so the grid
#: spacing stays under ~230 m.
MIN_HALF_EXTENT_M = 3000.0
MAX_HALF_EXTENT_M = 15000.0

KT_TO_MPS = 0.514444

#: Provenance every placed field carries.
PLACED_FROM = "placed in the 3D camera placer"

MODES = ("world", "follow")
AIMS = ("aircraft", "bearing")


class PlacementError(ValueError):
    """A request the placer cannot turn into a camera, by name."""


def _airspeed_mps(spec: ScenarioSpec) -> float:
    value = float(spec.airspeed.value or 0.0)
    unit = str(spec.airspeed.unit or "").lower()
    if unit in ("m/s", "mps"):
        return value
    return value * KT_TO_MPS                          # the spec's knots


def track_estimate(spec: ScenarioSpec, seconds: float) -> List[Dict[str, float]]:
    """The aircraft's start pose carried straight along its heading for
    the clip: a guide for framing, not the flown track (that is JSBSim's
    and only exists after the run). Points every ~second."""
    heading = math.radians(float(spec.heading.value or 0.0))
    speed = _airspeed_mps(spec)
    alt = float(spec.altitude.value)
    steps = max(1, int(round(seconds)))
    return [{"t_s": seconds * k / steps,
             "north_m": speed * seconds * k / steps * math.cos(heading),
             "east_m": speed * seconds * k / steps * math.sin(heading),
             "alt_m": alt}
            for k in range(steps + 1)]


def _traffic(spec: ScenarioSpec) -> List[Dict[str, Any]]:
    """Placed traffic at t = 0 in the local frame (ahead/right/up are the
    heading-only frame, the same rotation the chase offsets use)."""
    from core.capture.poses import _heading_only

    out = []
    heading = float(spec.heading.value or 0.0)
    for index, entry in enumerate(spec.traffic):
        if not entry.placed():
            continue
        p = entry.placement()
        n, e, up = _heading_only(heading, p["ahead_m"], p["right_m"],
                                 p["up_m"])
        out.append({"index": index, "north_m": n, "east_m": e,
                    "alt_m": float(spec.altitude.value) + up,
                    "heading_deg": heading})
    return out


def _sample_grid(heightfield, frame, half_m: float,
                 points: int) -> Tuple[List[float], float, int]:
    """Elevations on a points x points grid about the origin, row-major
    from the SOUTH-WEST corner (row = north index, column = east index).
    The window is clipped to the raster so no row is a clamped edge."""
    import numpy as np

    min_x, min_y, max_x, max_y = heightfield.bounds_m()
    # Largest square about the origin the raster fully covers.
    room = min(frame.origin_x_m - min_x, max_x - frame.origin_x_m,
               frame.origin_y_m - min_y, max_y - frame.origin_y_m)
    half = max(min(half_m, room), 0.0)
    if half <= 0.0:
        raise PlacementError("the scene raster does not cover the spec "
                             "origin")
    step = 2.0 * half / (points - 1)
    g = heightfield.georeference
    offsets = -half + step * np.arange(points)
    east = frame.origin_x_m + offsets
    north = frame.origin_y_m + offsets
    col = (east - g.origin_x_m) / g.pixel_size_m
    row = (g.origin_y_m - north) / g.pixel_size_m
    col = np.clip(col, 0.0, heightfield.width - 1.0)
    row = np.clip(row, 0.0, heightfield.height - 1.0)
    # Bilinear, the same interpolation Heightfield.elevation_at does.
    rr, cc = np.meshgrid(row, col, indexing="ij")
    r0 = np.floor(rr).astype(int)
    c0 = np.floor(cc).astype(int)
    r1 = np.minimum(r0 + 1, heightfield.height - 1)
    c1 = np.minimum(c0 + 1, heightfield.width - 1)
    fr = rr - r0
    fc = cc - c0
    s = heightfield.samples.astype(np.float64)
    top = s[r0, c0] * (1.0 - fc) + s[r0, c1] * fc
    bottom = s[r1, c0] * (1.0 - fc) + s[r1, c1] * fc
    z = heightfield.offset_m + (top * (1.0 - fr) + bottom * fr) * heightfield.scale_m
    return [round(float(v), 1) for v in z.ravel()], step, points


def terrain_payload(spec: ScenarioSpec, scene: Dict,
                    clip_seconds: float) -> Dict[str, Any]:
    """Everything the page's 3D view draws, in the pose solver's frame:
    local north/east metres about the spec origin, altitude metres MSL."""
    from core.capture.poses import SceneFrame
    from core.capture.validate import CAMERA_MIN_CLEARANCE_M

    seconds = min(float(spec.duration.value), clip_seconds)
    track = track_estimate(spec, seconds)
    reach = max(math.hypot(p["north_m"], p["east_m"]) for p in track)
    half = min(max(MIN_HALF_EXTENT_M, reach * 1.25 + 1000.0),
               MAX_HALF_EXTENT_M)
    datum = float(spec.terrain_elevation.value)

    heightfield = None
    terrain = scene.get("terrain")
    if terrain:
        from core.terrain.heightfield import Heightfield
        from webapp.runs import baked

        if baked(Path(terrain)):
            heightfield = Heightfield.read(Path(terrain))
    if heightfield is not None:
        frame = SceneFrame.for_spec(spec, heightfield)
        heights, step, points = _sample_grid(heightfield, frame, half,
                                             GRID_POINTS)
        kind = "raster"
    else:
        # Flat: the datum IS the ground (static_camera_violations' rule).
        points = 2
        step = 2.0 * half
        heights = [datum] * 4
        kind = "flat"
    half_used = step * (points - 1) / 2.0
    return {
        "kind": kind,
        "scene": {"key": scene.get("key"), "label": scene.get("label"),
                  "refused": scene.get("refused")},
        "grid": {"points": points, "step_m": step,
                 "south_m": -half_used, "west_m": -half_used,
                 "heights_m": heights},
        "datum_m": datum,
        "aircraft": {"aircraft": str(spec.aircraft.value),
                     "north_m": 0.0, "east_m": 0.0,
                     "alt_m": float(spec.altitude.value),
                     "heading_deg": float(spec.heading.value or 0.0)},
        "track": track,
        "traffic": _traffic(spec),
        "lens": {"focal_length_mm": DEFAULT_FOCAL_MM,
                 "sensor_width_mm": DEFAULT_SENSOR_W_MM,
                 "sensor_height_mm": DEFAULT_SENSOR_H_MM},
        "clip_seconds": seconds,
        # The scene check's own floor, so the page warns at the same line
        # the placement endpoint refuses at.
        "min_clearance_m": CAMERA_MIN_CLEARANCE_M,
    }


def _number(request: Dict[str, Any], key: str,
            default: Optional[float] = None) -> float:
    value = request.get(key, default)
    if value is None:
        raise PlacementError(f"placer: {key} is required")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PlacementError(f"placer: {key} must be a number, got "
                             f"{value!r}") from None
    if not math.isfinite(number):
        raise PlacementError(f"placer: {key} must be finite")
    return number


def place_camera(spec: ScenarioSpec, request: Dict[str, Any]) -> int:
    """Add (or, with ``replace``, overwrite) the placed camera on
    ``spec``; returns its index. Every number the user moved is
    ``user``-sourced so no planner can move it afterwards."""
    mode = str(request.get("mode") or "world")
    if mode not in MODES:
        raise PlacementError(f"placer: mode must be one of {MODES}, got "
                             f"{mode!r}")
    replace = request.get("replace")
    if replace is not None:
        replace = int(replace)
        if not 0 <= replace < len(spec.cameras):
            raise PlacementError(
                f"camera[{replace}] does not exist; the spec states "
                f"{len(spec.cameras)}")

    taken = {str(c.camera_id.value) for i, c in enumerate(spec.cameras)
             if i != replace}
    if replace is not None:
        camera_id = str(spec.cameras[replace].camera_id.value)
    else:
        camera_id, suffix = "placed", 0
        while camera_id in taken:
            suffix += 1
            camera_id = f"placed{suffix}"

    preset = "explicit" if mode == "world" else "chase"
    camera = CameraSpec.defaulted(
        camera_id=camera_id, preset=preset,
        aircraft=str(spec.aircraft.value),
        terrain_elevation_m=float(spec.terrain_elevation.value),
        frm=f"added from the 3D camera placer ({preset} camera)")
    camera.set("preset", preset, frm=PLACED_FROM)
    if mode == "world":
        camera.set("position_mode", "scene", frm=PLACED_FROM)
        camera.set("position_east_m", _number(request, "east_m"),
                   frm=PLACED_FROM)
        camera.set("position_north_m", _number(request, "north_m"),
                   frm=PLACED_FROM)
        camera.set("position_alt_m", _number(request, "alt_m"),
                   frm=PLACED_FROM)
        aim = str(request.get("aim") or "aircraft")
        if aim not in AIMS:
            raise PlacementError(f"placer: aim must be one of {AIMS}, got "
                                 f"{aim!r}")
        camera.set("aim_mode", aim, frm=PLACED_FROM)
        if aim == "bearing":
            camera.set("aim_bearing_deg",
                       _number(request, "bearing_deg") % 360.0,
                       frm=PLACED_FROM)
            camera.set("aim_elevation_deg",
                       _number(request, "elevation_deg"), frm=PLACED_FROM)
    else:
        camera.set("offset_forward_m", _number(request, "forward_m"),
                   frm=PLACED_FROM)
        camera.set("offset_right_m", _number(request, "right_m"),
                   frm=PLACED_FROM)
        camera.set("offset_up_m", _number(request, "up_m"),
                   frm=PLACED_FROM)
    camera.set("focal_length_mm",
               _number(request, "focal_length_mm", DEFAULT_FOCAL_MM),
               frm=PLACED_FROM)
    plan_full_capture(
        camera, frm="a view placed from the page captures the whole clip")

    if replace is not None:
        spec.cameras[replace] = camera
        return replace
    spec.cameras.append(camera)
    return len(spec.cameras) - 1
