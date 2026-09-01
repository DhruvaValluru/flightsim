"""Camera validation: named refusals, the existing Violation surface.

Two layers, the same split the scenario validator states:

**Scene-free checks** (:func:`validate_cameras`) judge the camera spec
alone -- lens and sensor physicality, output resolution, near/far
ordering, vocabulary membership, schedule parameters. They are called
from :func:`core.scenario.validate.validate` so every entry point (the
webapp verdict, the CLI, run_spec's own gate) refuses identically.

**Scene-coupled checks** judge solved geometry against the scene:

* :func:`track_violations` -- the SOLVED pose track along the WHOLE
  run: ``camera.terrain_clearance`` (every sample against the raster,
  not the first frame), ``camera.scene_bounds`` (poses off the raster
  where terrain and imagery do not exist), ``camera.hazard_intersection``
  (poses inside the modelled tornado core, the funnel-camera failure
  measured on run c33db2c326e0).
* :func:`static_camera_violations` -- the same three constraints for
  world-anchored cameras (scene/geographic placement, keyframes
  included) evaluated WITHOUT telemetry, so the webapp's /run verdict
  can refuse a camera inside a mountain before any editor time is
  spent (the plan_terrain_flight pattern).

A user-stated camera field is never moved to pass any of these:
refusal by name is the only path. System-chosen placements may be
re-planned by callers through ``spec.plan`` with a recorded reason.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..scenario.camera import (
    AIM_MODES, CAMERA_PRESETS, EVENT_DIRECTIONS, POSITION_MODES,
    TRIGGER_KINDS, CameraSpec,
)
from ..scenario.validate import Violation

#: Minimum camera height above the terrain under it, metres. A camera
#: may honestly sit on a tripod; it may not sit inside the mountain.
CAMERA_MIN_CLEARANCE_M = 2.0

#: Output resolution cap. Not a render-hardware claim -- a sanity rail
#: against nonsense ("1e9 px") that would silently exhaust memory.
MAX_RESOLUTION_PX = 8192

#: Lens/sensor physicality rails, generous around real hardware.
MAX_FOCAL_MM = 2000.0
MAX_SENSOR_MM = 120.0


def _prefix(index: int, camera: CameraSpec) -> str:
    return f"camera[{index}] {str(camera.camera_id.value)!r}"


def intrinsics_violations(camera: CameraSpec,
                          index: int = 0) -> List[Violation]:
    """camera.intrinsics: non-physical lens/sensor values, unsupported
    resolutions, near/far ordering."""
    out: List[Violation] = []
    who = _prefix(index, camera)

    focal = float(camera.focal_length_mm.value)
    if not 0.0 < focal <= MAX_FOCAL_MM:
        out.append(Violation(
            "camera.intrinsics",
            f"{who}: focal length must lie in (0, {MAX_FOCAL_MM:g}] mm",
            actual=focal, limit=MAX_FOCAL_MM, unit="mm"))
    for name in ("sensor_width_mm", "sensor_height_mm"):
        value = float(getattr(camera, name).value)
        if not 0.0 < value <= MAX_SENSOR_MM:
            out.append(Violation(
                "camera.intrinsics",
                f"{who}: {name} must lie in (0, {MAX_SENSOR_MM:g}] mm",
                actual=value, limit=MAX_SENSOR_MM, unit="mm"))
    for name in ("width_px", "height_px"):
        value = getattr(camera, name).value
        if (isinstance(value, bool) or not isinstance(value, int)
                or not 0 < value <= MAX_RESOLUTION_PX):
            out.append(Violation(
                "camera.intrinsics",
                f"{who}: {name} must be a whole number of pixels in "
                f"(0, {MAX_RESOLUTION_PX}]",
                actual=float(value) if isinstance(value, (int, float))
                else None,
                limit=float(MAX_RESOLUTION_PX), unit="px"))
    near = float(camera.near_m.value)
    far = float(camera.far_m.value)
    if near <= 0.0:
        out.append(Violation(
            "camera.intrinsics", f"{who}: near plane must be positive",
            actual=near, limit=0.0, unit="m"))
    if far <= near:
        out.append(Violation(
            "camera.intrinsics",
            f"{who}: far plane must sit beyond the near plane",
            actual=far, limit=near, unit="m"))
    return out


def vocabulary_violations(camera: CameraSpec,
                          index: int = 0) -> List[Violation]:
    """camera.preset: words outside the modelled vocabulary refuse by
    name rather than rendering as the nearest-looking preset."""
    out: List[Violation] = []
    who = _prefix(index, camera)
    preset = str(camera.preset.value)
    if preset not in CAMERA_PRESETS:
        out.append(Violation(
            "camera.preset",
            f"{who}: unknown preset {preset!r}; modelled: "
            f"{', '.join(CAMERA_PRESETS)}"))
    mode = str(camera.position_mode.value)
    if mode not in POSITION_MODES:
        out.append(Violation(
            "camera.preset",
            f"{who}: unknown position mode {mode!r}; modelled: "
            f"{', '.join(POSITION_MODES)}"))
    aim = str(camera.aim_mode.value)
    if aim not in AIM_MODES:
        out.append(Violation(
            "camera.preset",
            f"{who}: unknown aim mode {aim!r}; modelled: "
            f"{', '.join(AIM_MODES)}"))
    return out


def schedule_violations(camera: CameraSpec,
                        index: int = 0) -> List[Violation]:
    """camera.schedule, the scene-free half: parameters that cannot
    schedule anything whatever the telemetry turns out to be. The
    telemetry-coupled half (count unreachable, trigger outside the
    window) lives in core.capture.schedule and refuses at solve time."""
    out: List[Violation] = []
    who = _prefix(index, camera)
    trigger = str(camera.trigger.value)
    count = camera.capture_count.value
    if trigger not in TRIGGER_KINDS:
        out.append(Violation(
            "camera.schedule",
            f"{who}: unknown trigger {trigger!r}; modelled: "
            f"{', '.join(TRIGGER_KINDS)}"))
        return out
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        out.append(Violation(
            "camera.schedule",
            f"{who}: capture count must be a non-negative whole number",
            actual=float(count) if isinstance(count, (int, float))
            else None, limit=0.0))
    if (trigger == "interval" and int(camera.capture_count.value or 0) == 0
            and float(camera.period_s.value) <= 0.0):
        out.append(Violation(
            "camera.schedule",
            f"{who}: an interval trigger needs a positive period or an "
            f"exact capture count",
            actual=float(camera.period_s.value), limit=0.0, unit="s"))
    if trigger in ("distance", "proximity") \
            and float(camera.distance_m.value) <= 0.0:
        out.append(Violation(
            "camera.schedule",
            f"{who}: the {trigger} trigger needs a positive distance",
            actual=float(camera.distance_m.value), limit=0.0, unit="m"))
    if trigger == "event" and str(camera.event_direction.value) \
            not in EVENT_DIRECTIONS:
        out.append(Violation(
            "camera.schedule",
            f"{who}: unknown event direction "
            f"{str(camera.event_direction.value)!r}; modelled: "
            f"{', '.join(EVENT_DIRECTIONS)}"))
    if float(camera.refractory_s.value) < 0.0:
        out.append(Violation(
            "camera.schedule",
            f"{who}: the refractory period cannot be negative",
            actual=float(camera.refractory_s.value), limit=0.0, unit="s"))
    return out


def validate_cameras(spec) -> List[Violation]:
    """Every scene-free camera check, for the core validator."""
    out: List[Violation] = []
    seen = set()
    for index, camera in enumerate(spec.cameras):
        out.extend(vocabulary_violations(camera, index))
        out.extend(intrinsics_violations(camera, index))
        out.extend(schedule_violations(camera, index))
        camera_id = str(camera.camera_id.value)
        if camera_id in seen:
            out.append(Violation(
                "camera.preset",
                f"camera id {camera_id!r} appears twice; frames could "
                f"not be attributed to one camera"))
        seen.add(camera_id)
    return out


# -- scene-coupled checks ------------------------------------------------

def track_violations(track, heightfield=None, scene_frame=None,
                     tornado: Optional[Dict[str, float]] = None,
                     terrain_elevation_m: float = 0.0) -> List[Violation]:
    """The SOLVED pose track against the scene, along the WHOLE track.

    ``track`` is a :class:`core.capture.poses.PoseTrack`; ``tornado``
    is the run card's own tornado block (centre in the same local
    frame), so the check and the render cannot model two different
    vortices.
    """
    out: List[Violation] = []
    who = f"camera {track.camera_id!r}"
    if heightfield is not None and scene_frame is not None:
        worst = None
        outside = 0
        for i in range(len(track)):
            x, y = scene_frame.to_projected(track.north_m[i],
                                            track.east_m[i])
            if not heightfield.contains(x, y):
                outside += 1
                continue
            clearance = track.alt_m[i] - heightfield.elevation_at(x, y)
            if worst is None or clearance < worst:
                worst = clearance
        if worst is not None and worst < CAMERA_MIN_CLEARANCE_M:
            out.append(Violation(
                "camera.terrain_clearance",
                f"{who}: the solved pose track descends into the scene's "
                f"terrain (checked every sample against the raster, not "
                f"the first frame)",
                actual=round(worst, 1), limit=CAMERA_MIN_CLEARANCE_M,
                unit="m AGL"))
        if outside:
            out.append(Violation(
                "camera.scene_bounds",
                f"{who}: {outside} of {len(track)} solved poses fall "
                f"outside the scene raster, where terrain and imagery "
                f"do not exist"))
    if tornado is not None:
        r_core = float(tornado.get("r_core_m", 150.0))
        fade_top = float(tornado.get("fade_top_m", 3000.0))
        centre_n = float(tornado["centre_north_m"])
        centre_e = float(tornado["centre_east_m"])
        inside = 0
        for i in range(len(track)):
            dn = track.north_m[i] - centre_n
            de = track.east_m[i] - centre_e
            agl = track.alt_m[i] - terrain_elevation_m
            if (dn * dn + de * de) ** 0.5 < r_core and agl < fade_top:
                inside += 1
        if inside:
            out.append(Violation(
                "camera.hazard_intersection",
                f"{who}: {inside} of {len(track)} solved poses sit "
                f"inside the modelled tornado core (radius "
                f"{r_core:g} m); frames from inside the funnel marker "
                f"are refused, not rendered blank",
                actual=float(inside), limit=0.0, unit="poses"))
    return out


def static_camera_violations(spec, heightfield=None, scene_frame=None,
                             tornado: Optional[Dict[str, float]] = None,
                             step_s: float = 1.0) -> List[Violation]:
    """Scene checks for world-anchored cameras, WITHOUT telemetry.

    A camera stated in scene metres or geographic coordinates (and its
    keyframed positions) is fixed geometry: it can be checked against
    the raster and the hazard volume before anything runs. Offset-mode
    cameras ride the aircraft, whose own track the flight planners
    already clear; their solved track is re-checked wherever telemetry
    exists (track_violations).
    """
    from .poses import _keyframe_value

    out: List[Violation] = []
    duration = float(spec.duration.value)
    terrain_datum = float(spec.terrain_elevation.value)
    for index, camera in enumerate(spec.cameras):
        mode = str(camera.position_mode.value)
        if mode not in ("scene", "geographic"):
            continue
        who = _prefix(index, camera)
        times = [k * step_s for k in range(int(duration / step_s) + 1)]
        worst = None
        outside = 0
        inside_hazard = 0
        for t in times:
            if mode == "geographic":
                if scene_frame is None:
                    break
                lat = _keyframe_value(camera.moves, "position_lat_deg",
                                      t, float(camera.position_lat_deg.value))
                lon = _keyframe_value(camera.moves, "position_lon_deg",
                                      t, float(camera.position_lon_deg.value))
                north, east = scene_frame.to_local(lat, lon)
            else:
                north = _keyframe_value(camera.moves, "position_north_m",
                                        t, float(camera.position_north_m.value))
                east = _keyframe_value(camera.moves, "position_east_m",
                                       t, float(camera.position_east_m.value))
            alt = _keyframe_value(camera.moves, "position_alt_m", t,
                                  float(camera.position_alt_m.value))
            if heightfield is not None and scene_frame is not None:
                x, y = scene_frame.to_projected(north, east)
                if not heightfield.contains(x, y):
                    outside += 1
                else:
                    clearance = alt - heightfield.elevation_at(x, y)
                    if worst is None or clearance < worst:
                        worst = clearance
            elif heightfield is None:
                # Flat scenes: the spec's own terrain datum IS the
                # ground; a camera stated under the slab refuses too.
                clearance = alt - terrain_datum
                if worst is None or clearance < worst:
                    worst = clearance
            if tornado is not None:
                dn = north - float(tornado["centre_north_m"])
                de = east - float(tornado["centre_east_m"])
                agl = alt - terrain_datum
                if ((dn * dn + de * de) ** 0.5
                        < float(tornado.get("r_core_m", 150.0))
                        and agl < float(tornado.get("fade_top_m", 3000.0))):
                    inside_hazard += 1
        if worst is not None and worst < CAMERA_MIN_CLEARANCE_M:
            out.append(Violation(
                "camera.terrain_clearance",
                f"{who}: the stated placement sits inside or on the "
                f"scene's terrain (checked over the whole run window)",
                actual=round(worst, 1), limit=CAMERA_MIN_CLEARANCE_M,
                unit="m AGL"))
        if outside:
            out.append(Violation(
                "camera.scene_bounds",
                f"{who}: the stated placement leaves the scene raster "
                f"for {outside} of {len(times)} checked instants; there "
                f"is no terrain or imagery there"))
        if inside_hazard:
            out.append(Violation(
                "camera.hazard_intersection",
                f"{who}: the stated placement sits inside the modelled "
                f"tornado core for {inside_hazard} of {len(times)} "
                f"checked instants"))
    return out
