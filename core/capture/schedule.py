"""Capture scheduling: which telemetry samples become frames.

Triggers are evaluated over the RECORDED TELEMETRY ONLY -- never render
timing, never wall clock -- so the schedule exists identically whether
or not pixels were ever produced, and two runs of the same spec emit
frame sets that align exactly in time. Every capture is sample-aligned:
the schedule is a list of telemetry sample indices plus their recorded
sim times.

The count guarantee: when a camera states an exact image count, the
emitted schedule has EXACTLY that many captures, or the schedule
refuses BEFORE anything runs with the named ``camera.schedule`` reason
(count unreachable at this duration and sample rate, trigger outside
the run window, non-positive count). Nothing is rounded to "close
enough".

Trigger kinds (the spec's ``trigger`` field):

* ``interval`` -- ``capture_count`` > 0: exactly that many captures,
  evenly spread over the recorded span, ENDPOINTS INCLUDED (indices
  ``round(k * (N-1) / (count-1))``; a count of 1 captures the first
  sample). ``capture_count`` == 0: one capture every ``period_s``,
  starting at the first sample, each snapped to the nearest recorded
  sample time.
* ``distance`` -- one capture at the start, then one each time the
  flown ground track accumulates another ``distance_m`` metres
  (projected through the scene frame; drift and turns lengthen the
  track exactly as flown).
* ``proximity`` -- captures while within ``distance_m`` of the stated
  aim point (``aim_north_m`` / ``aim_east_m``, scene metres), one per
  entry, refractory-limited.
* ``event`` -- captures where the recorded channel
  ``event_channel`` crosses ``event_threshold`` in the stated
  ``event_direction`` (``rising`` / ``falling`` are edge crossings;
  ``above`` / ``below`` are level states, refractory-limited so a held
  exceedance is a capture per refractory period, not per sample).

The refractory period (``refractory_s``) applies to ``proximity`` and
``event`` captures: after a capture, further triggers are ignored until
it elapses -- one event is one capture, not a burst at the telemetry
rate.

For ``distance``, ``proximity`` and ``event``, a stated
``capture_count`` > 0 is a CONTRACT: if the trigger produces any other
number over this telemetry, the schedule refuses by name rather than
padding or truncating.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..scenario.camera import CameraSpec
from .poses import SceneFrame


class ScheduleError(Exception):
    """The requested capture schedule cannot be honoured; named."""

    constraint = "camera.schedule"

    def __init__(self, message: str) -> None:
        super().__init__(f"camera.schedule: {message}")


@dataclass(frozen=True)
class CaptureSchedule:
    """Sample-aligned capture times for one camera."""

    camera_id: str
    trigger: str
    indices: Tuple[int, ...]
    times: Tuple[float, ...]
    #: How the schedule was produced, for the manifest.
    basis: str

    def __len__(self) -> int:
        return len(self.indices)


#: Representation slack for "on the fixed-step grid": a sample instant
#: is k / rate_hz computed in floating point (measured on the example:
#: the worst instant is 2.1e-11 s off its step at 120 Hz).
GRID_SLACK_S = 1.0e-6


def off_grid_instants(times: Sequence[float], rate_hz: float
                      ) -> List[float]:
    """The instants in ``times`` that do not lie on the ``rate_hz``
    fixed-step grid (within GRID_SLACK_S). The engine captures on fixed
    steps only: the commandlet takes the step whose clock equals the
    instant and fails by name on any other, so an off-grid schedule is
    refused here, before any editor time, never rounded to a step."""
    step = 1.0 / float(rate_hz)
    return [float(t) for t in times
            if abs(float(t) / step - round(float(t) / step)) * step
            > GRID_SLACK_S]


def _series(columns, name: str, camera_id: str):
    if name not in columns:
        raise ScheduleError(
            f"camera {camera_id!r} triggers on channel {name!r}, which "
            f"the telemetry record does not carry; available channels "
            f"are the recorder's own")
    return [float(v) for v in columns[name]]


def solve_schedule(columns: Dict[str, Sequence[float]],
                   camera: CameraSpec,
                   frame: Optional[SceneFrame] = None,
                   rate_hz: Optional[float] = None) -> CaptureSchedule:
    """The capture schedule for one camera over one telemetry record.

    Raises :class:`ScheduleError` (named ``camera.schedule``) rather
    than emitting a schedule that differs from what was asked. With
    ``rate_hz`` (the spec's fixed-step rate) an instant off that grid is
    refused by name: the engine captures on fixed steps only and never
    rounds an instant to the nearest one.
    """
    camera_id = str(camera.camera_id.value)
    t = [float(v) for v in columns.get("t", ())]
    if len(t) < 1:
        raise ScheduleError("the telemetry record is empty; there is "
                            "nothing to schedule captures over")
    n = len(t)
    trigger = str(camera.trigger.value)
    count = int(camera.capture_count.value)
    if count < 0:
        raise ScheduleError(
            f"camera {camera_id!r} requests a negative capture count "
            f"({count})")
    refractory = float(camera.refractory_s.value)
    if refractory < 0:
        raise ScheduleError(
            f"camera {camera_id!r} states a negative refractory period")

    if trigger == "interval":
        indices, basis = _interval(camera_id, camera, t, count)
    elif trigger == "distance":
        indices, basis = _distance(camera_id, camera, columns, frame)
    elif trigger == "proximity":
        indices, basis = _proximity(camera_id, camera, columns, frame,
                                    refractory)
    elif trigger == "event":
        indices, basis = _event(camera_id, camera, columns, refractory)
    else:
        raise ScheduleError(
            f"camera {camera_id!r} names unknown trigger {trigger!r} "
            f"(interval | distance | proximity | event)")

    if trigger != "interval" and count > 0 and len(indices) != count:
        raise ScheduleError(
            f"camera {camera_id!r} requested exactly {count} captures "
            f"but the {trigger!r} trigger fires {len(indices)} times "
            f"over this telemetry; the count contract is refused, never "
            f"padded or truncated")

    times = tuple(t[i] for i in indices)
    if rate_hz is not None:
        off = off_grid_instants(times, rate_hz)
        if off:
            raise ScheduleError(
                f"camera {camera_id!r} schedules {len(off)} instant(s) off "
                f"the {float(rate_hz):g} Hz fixed-step grid (first: "
                f"t={off[0]:.6f} s); the engine captures on fixed steps "
                f"only and never approximates an instant to the nearest "
                f"step")
    return CaptureSchedule(
        camera_id=camera_id, trigger=trigger,
        indices=tuple(indices), times=times,
        basis=basis)


def _interval(camera_id, camera, t, count):
    n = len(t)
    if count > 0:
        if count > n:
            raise ScheduleError(
                f"camera {camera_id!r} requests {count} captures but the "
                f"run recorded only {n} samples; the count is unreachable "
                f"at this duration and sample rate")
        if count == 1:
            return [0], "count 1: the first recorded sample"
        # Spacing (n-1)/(count-1) >= 1 sample whenever count <= n, so
        # the rounded indices are strictly increasing: the count-
        # unreachable refusal above is the one guard, and it is
        # mutation-checked.
        indices = [round(k * (n - 1) / (count - 1)) for k in range(count)]
        return indices, (f"count {count} spread over [{t[0]:g}, "
                         f"{t[-1]:g}] s, endpoints included")
    period = float(camera.period_s.value)
    if period <= 0:
        raise ScheduleError(
            f"camera {camera_id!r} states no capture count and a "
            f"non-positive period ({period:g} s)")
    indices = []
    goal = t[0]
    i = 0
    while goal <= t[-1] + 1e-9:
        # Snap each period mark to the nearest recorded sample; i only
        # advances, so the scan is linear over the record.
        while i + 1 < len(t) and abs(t[i + 1] - goal) <= abs(t[i] - goal):
            i += 1
        if not indices or indices[-1] != i:
            indices.append(i)
        goal += period
    return indices, (f"every {period:g} s snapped to the recorded "
                     f"sample clock")


def _track_local(columns, frame, camera_id):
    if frame is None:
        raise ScheduleError(
            f"camera {camera_id!r} uses a ground-track trigger but no "
            f"scene frame was provided to project the track")
    lat = _series(columns, "lat_deg", camera_id)
    lon = _series(columns, "lon_deg", camera_id)
    return [frame.to_local(a, b) for a, b in zip(lat, lon)]


def _distance(camera_id, camera, columns, frame):
    spacing = float(camera.distance_m.value)
    if spacing <= 0:
        raise ScheduleError(
            f"camera {camera_id!r} states a non-positive waypoint "
            f"spacing ({spacing:g} m)")
    track = _track_local(columns, frame, camera_id)
    indices = [0]
    travelled = 0.0
    next_mark = spacing
    for i in range(1, len(track)):
        dn = track[i][0] - track[i - 1][0]
        de = track[i][1] - track[i - 1][1]
        travelled += (dn * dn + de * de) ** 0.5
        if travelled >= next_mark - 1e-9:
            indices.append(i)
            while next_mark <= travelled + 1e-9:
                next_mark += spacing
    return indices, (f"every {spacing:g} m along the flown ground "
                     f"track ({travelled:.0f} m total), start included")


def _proximity(camera_id, camera, columns, frame, refractory):
    radius = float(camera.distance_m.value)
    if radius <= 0:
        raise ScheduleError(
            f"camera {camera_id!r} states a non-positive proximity "
            f"radius ({radius:g} m)")
    point = (float(camera.aim_north_m.value),
             float(camera.aim_east_m.value))
    track = _track_local(columns, frame, camera_id)
    t = [float(v) for v in columns["t"]]
    indices = []
    last = None
    for i, (north, east) in enumerate(track):
        dn, de = north - point[0], east - point[1]
        if (dn * dn + de * de) ** 0.5 <= radius:
            if last is None or t[i] - last >= refractory:
                indices.append(i)
                last = t[i]
    if not indices:
        raise ScheduleError(
            f"camera {camera_id!r}: the flown track never comes within "
            f"{radius:g} m of the stated point "
            f"({point[0]:g} N, {point[1]:g} E); the trigger lies "
            f"outside the run window")
    return indices, (f"within {radius:g} m of ({point[0]:g} N, "
                     f"{point[1]:g} E), refractory {refractory:g} s")


def _event(camera_id, camera, columns, refractory):
    channel = str(camera.event_channel.value)
    threshold = float(camera.event_threshold.value)
    direction = str(camera.event_direction.value)
    values = _series(columns, channel, camera_id)
    t = [float(v) for v in columns["t"]]
    indices = []
    last = None

    def fire(i):
        nonlocal last
        if last is None or t[i] - last >= refractory:
            indices.append(i)
            last = t[i]

    for i, v in enumerate(values):
        if direction == "rising":
            if i > 0 and values[i - 1] < threshold <= v:
                fire(i)
        elif direction == "falling":
            if i > 0 and values[i - 1] > threshold >= v:
                fire(i)
        elif direction == "above":
            if v > threshold:
                fire(i)
        elif direction == "below":
            if v < threshold:
                fire(i)
        else:
            raise ScheduleError(
                f"camera {camera_id!r} names unknown event direction "
                f"{direction!r} (above | below | rising | falling)")
    if not indices:
        raise ScheduleError(
            f"camera {camera_id!r}: channel {channel!r} never goes "
            f"{direction} {threshold:g} over this telemetry; the event "
            f"trigger fires zero captures")
    return indices, (f"{channel} {direction} {threshold:g}, refractory "
                     f"{refractory:g} s")
