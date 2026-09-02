"""Terrain look-ahead on the altitude setpoint (Package E).

The altitude hold is a state controller: it holds the altitude it was
given and knows nothing about what is in front of the aircraft. The
airframe-contact check (:mod:`core.terrain.contact`) ends a run the step a
span station enters the surface -- it is the crash detector, not the thing
that prevents the crash. Between those two sits this module: the forward-
looking terrain-avoidance function in the sense of DO-367 FLTA and the
Auto-GCAS escape projection, reduced to the one action the controller
exposes, the altitude setpoint.

Every guidance tick the projected ground track (the CURRENT inertial
velocity, held; there is no navigation in this phase, so the track is a
straight line) is sampled on the baked raster out to ``HORIZON_S`` at the
raster's own pixel pitch, at the airframe's span stations (the same
stations the contact check ends the run on, projected level). Two
questions are asked of the samples:

1. **Is there a threat?** Does the terrain plus the required terrain
   clearance (RTC = :data:`core.scenario.validate.MIN_CLEARANCE_M`, the
   same margin the validator demands at t = 0) rise above the altitude the
   controller is currently holding? If it does, the setpoint is raised to
   clear it. The setpoint is only ever RAISED here; a descent is a
   navigation decision this phase does not make.

2. **Can the aircraft make it?** An escape profile is projected from the
   present state: the current climb rate held for the controller's
   response time, then the controller's own climb-rate limit
   (``ap/tecs/hdot-max-fps``, which Package D caps at a fraction of the
   MEASURED specific excess power). A sample the escape profile cannot
   clear is an infeasible threat, and the run refuses BY NAME
   (``terrain.lookahead``) before the impact, naming the distance, the
   climb rate required and the climb rate available. Nothing is
   approximated to make it pass.

Nothing here writes ``position/*``, ``velocities/*`` or ``attitude/*``:
the one output is ``ap/altitude-setpoint-ft`` through
:meth:`core.control.autopilot.Autopilot.command`, and the only writer of
physical state remains ``fdm.step()``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..fdm import units as u
from ..performance import SPOOL_SECONDS
from ..scenario.validate import MIN_CLEARANCE_M
from .contact import station_offsets_ned
from .ground import TerrainGround

#: How far ahead along the projected track the raster is sampled, in
#: seconds of flight. Ninety seconds at 250 kt is about 11 km -- the FLTA
#: en-route look-ahead scale.
HORIZON_S = 90.0

#: Required terrain clearance en route: the validator's own floor.
RTC_M = MIN_CLEARANCE_M


class TerrainLookaheadError(RuntimeError):
    """The projected track meets terrain the aircraft cannot out-climb."""

    constraint = "terrain.lookahead"

    def __init__(self, threat: "Threat") -> None:
        self.threat = threat
        super().__init__(threat.describe())


@dataclass(frozen=True)
class Threat:
    """One raster sample ahead that the current path does not clear."""

    time_s: float                 # simulation time of the evaluation
    ahead_s: float                # time to reach the sample
    distance_m: float             # along-track distance to the sample
    station: str
    terrain_m: float
    required_altitude_m: float    # terrain + RTC
    altitude_m: float             # aircraft altitude at evaluation
    escape_altitude_m: float      # what the escape profile reaches there
    required_hdot_mps: float      # to be at required_altitude_m in time
    available_hdot_mps: float     # the controller's climb-rate limit
    feasible: bool

    def describe(self) -> str:
        verdict = ("the escape climb clears it" if self.feasible
                   else "the escape climb does NOT clear it")
        return (f"terrain.lookahead: {self.terrain_m:.0f} m terrain at the "
                f"{self.station} station {self.distance_m:.0f} m "
                f"({self.ahead_s:.0f} s) ahead needs {self.required_altitude_m:.0f} m "
                f"(terrain + {RTC_M:.0f} m); from {self.altitude_m:.0f} m that "
                f"is {self.required_hdot_mps:.1f} m/s of climb against "
                f"{self.available_hdot_mps:.1f} m/s available "
                f"(escape profile reaches {self.escape_altitude_m:.0f} m): "
                f"{verdict}")


@dataclass(frozen=True)
class LookaheadResult:
    time_s: float
    samples: int
    threat: Optional[Threat]
    setpoint_m: Optional[float]   # the raised setpoint, if one was issued


@dataclass
class TerrainLookahead:
    """Forward terrain sampling that raises the altitude setpoint in time."""

    ground: TerrainGround
    wingspan_m: float
    hdot_capability_mps: float
    response_s: float = SPOOL_SECONDS
    horizon_s: float = HORIZON_S
    rtc_m: float = RTC_M
    hold_tolerance_m: float = 0.0
    events: List[Dict[str, Any]] = field(default_factory=list)
    evaluations: int = 0
    samples_total: int = 0

    def __post_init__(self) -> None:
        if self.wingspan_m <= 0.0:
            raise ValueError("terrain look-ahead needs the airframe span")
        if self.hdot_capability_mps <= 0.0:
            raise ValueError(
                f"terrain look-ahead needs a positive climb capability, got "
                f"{self.hdot_capability_mps} m/s; an aircraft that cannot "
                f"climb cannot be guided over terrain")

    @classmethod
    def for_run(cls, ground: TerrainGround, fdm, autopilot,
                hold_tolerance_m: float) -> "TerrainLookahead":
        """From the run's own FDM and engaged autopilot: the span from
        metrics/bw-ft, the climb capability from the controller's limit
        that Package D set from the measured excess power."""
        return cls(
            ground=ground,
            wingspan_m=u.ft_to_m(fdm.props.get("metrics/bw-ft")),
            hdot_capability_mps=u.fps_to_mps(
                fdm.props.get("ap/tecs/hdot-max-fps")),
            hold_tolerance_m=float(hold_tolerance_m),
        )

    # -- projection -------------------------------------------------------

    def escape_altitude_m(self, altitude_m: float, hdot_now_mps: float,
                          ahead_s: float) -> float:
        """Altitude the escape profile reaches ``ahead_s`` from now: the
        present climb rate held through the response time, then the
        controller's climb-rate limit."""
        response = min(ahead_s, self.response_s)
        climbing = max(0.0, ahead_s - self.response_s)
        return altitude_m + hdot_now_mps * response \
            + self.hdot_capability_mps * climbing

    def evaluate(self, state, current_setpoint_m: float) -> LookaheadResult:
        """Sample the raster ahead; return the threat (if any) and the
        setpoint that clears it. Raises TerrainLookaheadError when the
        escape profile does not clear a sample."""
        self.evaluations += 1
        vn, ve = float(state.v_north_mps), float(state.v_east_mps)
        groundspeed = math.hypot(vn, ve)
        if groundspeed < 1.0:
            return LookaheadResult(state.t, 0, None, None)
        track_deg = math.degrees(math.atan2(ve, vn)) % 360.0
        x0, y0 = self.ground.project(state.lat_deg, state.lon_deg)
        pitch_m = float(self.ground.heightfield.georeference.pixel_size_m)
        # Half the raster pitch along the track: a bilinear lookup never
        # exceeds its neighbouring pixel centres, and a half-pitch stride
        # lands a sample within a quarter pixel of every centre crossed.
        step_s = 0.5 * pitch_m / groundspeed
        stations = list(station_offsets_ned(0.0, 0.0, track_deg,
                                            self.wingspan_m))
        hdot_now = float(state.climb_rate_mps)
        altitude = float(state.altitude_m)
        held = max(float(current_setpoint_m), altitude)

        worst_required = held          # highest terrain + RTC in the horizon
        worst: Optional[Threat] = None
        samples = 0
        n = int(self.horizon_s / step_s) if step_s > 0.0 else 0
        for k in range(1, n + 1):
            ahead_s = k * step_s
            distance = ahead_s * groundspeed
            cx = x0 + ve * ahead_s
            cy = y0 + vn * ahead_s
            for name, north, east, _down in stations:
                px, py = cx + east, cy + north
                if not self.ground.heightfield.contains(px, py):
                    continue
                samples += 1
                terrain = self.ground.heightfield.elevation_at(px, py)
                required = terrain + self.rtc_m
                if required <= held - self.hold_tolerance_m:
                    continue
                escape = self.escape_altitude_m(altitude, hdot_now, ahead_s)
                usable = max(ahead_s - self.response_s, 1e-3)
                required_hdot = (required - altitude
                                 - hdot_now * min(ahead_s, self.response_s)) / usable
                threat = Threat(
                    time_s=float(state.t), ahead_s=ahead_s,
                    distance_m=distance, station=name, terrain_m=terrain,
                    required_altitude_m=required, altitude_m=altitude,
                    escape_altitude_m=escape,
                    required_hdot_mps=required_hdot,
                    available_hdot_mps=self.hdot_capability_mps,
                    feasible=escape >= required)
                if not threat.feasible:
                    raise TerrainLookaheadError(threat)
                if required > worst_required:
                    worst_required = required
                    worst = threat
        self.samples_total += samples
        setpoint = None
        if worst is not None:
            # The hold keeps its altitude within a tolerance band; the
            # setpoint sits one band above the requirement so that a hold
            # at the BOTTOM of its band still carries the full RTC.
            setpoint = worst_required + self.hold_tolerance_m
        return LookaheadResult(float(state.t), samples, worst, setpoint)

    def guide(self, state, autopilot) -> LookaheadResult:
        """One guidance tick: evaluate, and raise the setpoint if needed.

        The only write is the altitude setpoint, through the autopilot's
        command surface, and only upward.
        """
        props = autopilot.fdm.props
        current = u.ft_to_m(props.get("ap/altitude-setpoint-ft"))
        result = self.evaluate(state, current)
        if result.setpoint_m is not None and result.setpoint_m > current:
            autopilot.command(altitude_m=result.setpoint_m)
            threat = result.threat
            self.events.append({
                "t": float(state.t),
                "setpoint_m": result.setpoint_m,
                "previous_setpoint_m": current,
                "terrain_m": threat.terrain_m,
                "station": threat.station,
                "distance_m": threat.distance_m,
                "ahead_s": threat.ahead_s,
                "required_hdot_mps": threat.required_hdot_mps,
                "available_hdot_mps": threat.available_hdot_mps,
            })
            return result
        return LookaheadResult(result.time_s, result.samples, result.threat,
                               None)

    # -- record -----------------------------------------------------------

    def provenance(self) -> Dict[str, Any]:
        return {
            "name": "terrain_lookahead",
            "horizon_s": self.horizon_s,
            "response_s": self.response_s,
            "rtc_m": self.rtc_m,
            "hold_tolerance_m": self.hold_tolerance_m,
            "wingspan_m": self.wingspan_m,
            "hdot_capability_mps": self.hdot_capability_mps,
            "evaluations": self.evaluations,
            "samples": self.samples_total,
            "raises": len(self.events),
            "events": list(self.events),
            "claim": "the altitude setpoint is raised, never lowered, to "
                     "terrain + RTC along the straight-line projection of "
                     "the current ground velocity, sampled at the raster "
                     "pitch at the span stations; a sample the escape "
                     "profile (current climb rate for the response time, "
                     "then the controller's climb limit) cannot clear "
                     "refuses the run by name",
        }
