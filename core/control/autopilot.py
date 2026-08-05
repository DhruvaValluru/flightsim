"""The guidance layer: setpoints only.

Division of labour (§5 Phase 2). The control laws live in JSBSim XML and run at
FDM rate. This module runs at whatever rate the harness polls it and writes only
``ap/*-setpoint-*``. It never computes a control surface command, because a
Python loop closing an attitude loop would run at the harness's rate rather than
the integrator's, and would not exist at all in the embedded host.

The one genuinely slow-loop job it does own is the calibrated-to-true airspeed
conversion. A pilot commands CAS; energy is a function of TAS; and the ratio
between them changes as the aircraft climbs. Recomputing it each guidance tick
is exactly the sort of thing the outer loop is for.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..fdm import units as u
from ..fdm.errors import FDMError


class AutopilotError(FDMError):
    """The autopilot could not be engaged, or was asked for something it lacks."""


class ClosureError(FDMError):
    """The achieved state does not match the commanded state (§2.8).

    This is the assertion that would have caught the previous build: commanded
    300 m and 233 kt, achieved 248 m and still descending, 251 kt then decaying
    through the target -- and a clean video rendered anyway.
    """


@dataclass(frozen=True)
class ClosureTolerance:
    """Declared before the run, not fitted to it."""

    altitude_m: float = 15.0
    airspeed_kt: float = 3.0
    heading_deg: float = 3.0
    #: The state must also be *settled*: a run that happens to cross its target
    #: while still diverging has not achieved anything.
    climb_rate_mps: float = 1.0
    #: Fraction of the run discarded before measuring, to skip the transient.
    settle_fraction: float = 0.5


@dataclass(frozen=True)
class ClosureCheck:
    """One commanded/achieved comparison."""

    name: str
    commanded: float
    achieved: float
    tolerance: float
    unit: str

    @property
    def error(self) -> float:
        return self.achieved - self.commanded

    @property
    def ok(self) -> bool:
        return abs(self.error) <= self.tolerance

    def render(self) -> str:
        mark = "ok " if self.ok else "FAIL"
        return (
            f"{mark} {self.name:10s} commanded {self.commanded:9.2f} {self.unit}, "
            f"achieved {self.achieved:9.2f} ({self.error:+.2f}, "
            f"tol {self.tolerance:.2f})"
        )


@dataclass(frozen=True)
class ClosureReport:
    checks: List[ClosureCheck]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def render(self) -> str:
        head = "closure: PASS" if self.ok else "closure: FAIL"
        return "\n".join([head] + ["  " + c.render() for c in self.checks])

    def raise_if_failed(self) -> "ClosureReport":
        if not self.ok:
            raise ClosureError(
                "The achieved state does not match the commanded state.\n"
                + self.render()
                + "\nRefusing to emit output: a run that did not reach what it "
                  "was commanded is not evidence of anything."
            )
        return self


class Autopilot:
    """Engage/disengage TECS and write its setpoints."""

    #: Properties the controller must expose. Checked once, so a model without
    #: the controller fails loudly instead of silently ignoring every command.
    REQUIRED = (
        "ap/enable",
        "ap/altitude-setpoint-ft",
        "ap/tas-setpoint-fps",
        "ap/heading-setpoint-deg",
        "ap/trim/throttle",
        "ap/trim/pitch-rad",
    )

    def __init__(self, fdm) -> None:
        self.fdm = fdm
        if not fdm.props.has("ap/enable"):
            raise AutopilotError(
                f"{fdm.aircraft_name!r} has no TECS controller. Build the "
                f"aircraft with FlightDynamics.with_tecs()."
            )
        fdm.props.require(self.REQUIRED)
        self._cas_demand_kt: Optional[float] = None
        self._engaged = False

    # -- engage ---------------------------------------------------------

    @property
    def engaged(self) -> bool:
        return self._engaged

    def engage(self) -> None:
        """Capture the trimmed state as the controller's reference point.

        TECS commands *changes* from trim: the throttle and pitch PIDs add to
        the trimmed values rather than computing them from nothing. Engaging
        without capturing trim would step the controls to zero on the first
        frame, and the recording would be that transient (§1.1).
        """
        if not self.fdm.is_trimmed:
            raise AutopilotError(
                "refusing to engage on an untrimmed aircraft: the controller "
                "commands changes from trim, so an untrimmed reference makes "
                "every command wrong by the trim error"
            )
        props = self.fdm.props

        # Measure this airframe's control-sign convention rather than assuming
        # one. Hardcoding it does not fail loudly on a model that uses the
        # other convention; it closes the loop with positive feedback.
        from .signs import measure

        base = getattr(self.fdm.derived, "base_name", self.fdm.aircraft_name)
        self.signs = measure(base)
        props.set_many(self.signs.as_properties())

        props.set_many(
            {
                "ap/trim/throttle": props.get("fcs/throttle-cmd-norm"),
                "ap/trim/pitch-rad": props.get("attitude/theta-rad"),
                # The inner loops command a deviation from the trimmed surface
                # position. Capturing these is what makes engage bumpless.
                "ap/trim/elevator": props.get("fcs/elevator-cmd-norm"),
                "ap/trim/aileron": props.get("fcs/aileron-cmd-norm"),
                "ap/trim/rudder": props.get("fcs/rudder-cmd-norm"),
            }
        )
        # Hold the current state until told otherwise.
        state = self.fdm.state()
        self.command(
            altitude_m=state.altitude_m,
            cas_kt=state.cas_kt,
            heading_deg=state.heading_deg,
        )
        props.set("ap/enable", 1.0)
        self._engaged = True

    def disengage(self) -> None:
        self.fdm.props.set("ap/enable", 0.0)
        self._engaged = False

    # -- commands -------------------------------------------------------

    def command(
        self,
        altitude_m: Optional[float] = None,
        cas_kt: Optional[float] = None,
        tas_kt: Optional[float] = None,
        heading_deg: Optional[float] = None,
        bank_deg: Optional[float] = None,
    ) -> None:
        """Write setpoints. Only the arguments given are changed."""
        if cas_kt is not None and tas_kt is not None:
            raise AutopilotError("command either cas_kt or tas_kt, not both")
        if heading_deg is not None and bank_deg is not None:
            raise AutopilotError("command either heading_deg or bank_deg, not both")
        props = self.fdm.props
        if altitude_m is not None:
            props.set("ap/altitude-setpoint-ft", u.m_to_ft(altitude_m))
        if heading_deg is not None:
            props.set_many({"ap/heading-setpoint-deg": heading_deg % 360.0,
                            "ap/bank-mode": 0.0})
        if bank_deg is not None:
            # Bank hold, which is what §6.5's bank-tracking criterion commands.
            props.set_many({"ap/bank-setpoint-rad": math.radians(bank_deg),
                            "ap/bank-mode": 1.0})
        if tas_kt is not None:
            self._cas_demand_kt = None
            props.set("ap/tas-setpoint-fps", u.kt_to_fps(tas_kt))
        if cas_kt is not None:
            self._cas_demand_kt = cas_kt
            self.update()

    def update(self) -> None:
        """Guidance tick. Refreshes the TAS setpoint from a CAS demand.

        The controller works in true airspeed because that is what specific
        kinetic energy is a function of. A CAS demand therefore has to be
        re-converted as density changes, which is a slow-loop job and lives
        here rather than in the XML.
        """
        if self._cas_demand_kt is None:
            return
        props = self.fdm.props
        cas = props.get("velocities/vc-kts")
        tas = props.get("velocities/vtrue-kts")
        # Ratio measured at the current state rather than from a standard
        # atmosphere formula, so it stays correct in non-standard conditions.
        ratio = (tas / cas) if cas > 1.0 else 1.0
        props.set("ap/tas-setpoint-fps", u.kt_to_fps(self._cas_demand_kt * ratio))

    # -- tuning ---------------------------------------------------------

    def tune(self, **gains: float) -> None:
        """Set controller gains by short name, e.g. ``tune(tau=4.0)``."""
        mapping = {
            "tau": "ap/tecs/tau",
            "speed_weight": "ap/tecs/speed-weight",
            "kt_p": "ap/tecs/kt-p",
            "kt_i": "ap/tecs/kt-i",
            "ke_p": "ap/tecs/ke-p",
            "ke_i": "ap/tecs/ke-i",
            "roll_to_throttle": "ap/tecs/roll-to-throttle",
            "k_theta": "ap/pitch/k-theta",
            "kp_q": "ap/pitch/kp-q",
            "ki_q": "ap/pitch/ki-q",
            "k_hdg": "ap/lat/k-hdg",
            "k_phi": "ap/lat/k-phi",
            "kp_p": "ap/lat/kp-p",
            "ki_p": "ap/lat/ki-p",
            "k_r": "ap/yaw/k-r",
            "bank_limit_deg": "ap/limits/bank-rad",
            "hdot_max_fps": "ap/tecs/hdot-max-fps",
        }
        writes = {}
        for key, value in gains.items():
            if key not in mapping:
                raise AutopilotError(
                    f"unknown gain {key!r}; known: {sorted(mapping)}"
                )
            if key == "bank_limit_deg":
                value = math.radians(value)
            writes[mapping[key]] = value
        self.fdm.props.set_many(writes)

    #: Tuning knobs recorded in the manifest. Enumerated explicitly rather than
    #: discovered by prefix search: a search picks up the controller's own
    #: signals and JSBSim's write-only PID internals such as
    #: ``.../initial-integrator-value``, which are state, not configuration.
    GAIN_PROPERTIES = (
        "ap/tecs/tau",
        "ap/tecs/speed-weight",
        "ap/tecs/hdot-max-fps",
        "ap/tecs/vdot-max-fps2",
        "ap/tecs/kt-p",
        "ap/tecs/kt-i",
        "ap/tecs/ke-p",
        "ap/tecs/ke-i",
        "ap/tecs/roll-to-throttle",
        "ap/pitch/k-theta",
        "ap/pitch/kp-q",
        "ap/pitch/ki-q",
        "ap/lat/k-hdg",
        "ap/lat/k-phi",
        "ap/lat/kp-p",
        "ap/lat/ki-p",
        "ap/yaw/k-r",
        "ap/yaw/washout-c1",
        "ap/limits/bank-rad",
        "ap/limits/pitch-max-rad",
        "ap/limits/pitch-min-rad",
        "ap/limits/q-rad_sec",
        "ap/limits/p-rad_sec",
    )

    def gains(self) -> Dict[str, float]:
        """Every controller gain and limit, for the run manifest (§7.4)."""
        return {
            name: self.fdm.props.get(name)
            for name in self.GAIN_PROPERTIES
            if self.fdm.props.has(name)
        }

    # -- the closure assertion (§2.8) -----------------------------------

    def closure(
        self,
        altitudes_m: List[float],
        airspeeds_kt: List[float],
        headings_deg: List[float],
        climb_rates_mps: List[float],
        tolerance: ClosureTolerance = ClosureTolerance(),
    ) -> ClosureReport:
        """Compare the achieved state against what was commanded.

        Measured over the settled tail of the run, since the leading transient
        is the segment research code exists to discard.
        """
        props = self.fdm.props
        cut = int(len(altitudes_m) * tolerance.settle_fraction)
        tail = slice(cut, None)

        def mean(xs):
            xs = xs[tail]
            return sum(xs) / len(xs) if xs else float("nan")

        commanded_alt = u.ft_to_m(props.get("ap/altitude-setpoint-ft"))
        commanded_tas = u.fps_to_kt(props.get("ap/tas-setpoint-fps"))
        commanded_hdg = props.get("ap/heading-setpoint-deg")

        # Circular mean. Headings wrap at 360, so an aircraft holding north and
        # jittering either side of it produces samples near 359.8 and 0.2 whose
        # arithmetic mean is 180 -- a heading error of 180 degrees invented
        # entirely by the averaging. Calm air hides this, because the heading
        # sits exactly on 0; turbulence exposes it immediately.
        settled_headings = headings_deg[cut:]
        if settled_headings:
            n = len(settled_headings)
            sin_mean = sum(math.sin(math.radians(h)) for h in settled_headings) / n
            cos_mean = sum(math.cos(math.radians(h)) for h in settled_headings) / n
            achieved_hdg = math.degrees(math.atan2(sin_mean, cos_mean)) % 360.0
        else:
            achieved_hdg = commanded_hdg
        heading_error = (achieved_hdg - commanded_hdg + 180.0) % 360.0 - 180.0

        return ClosureReport(
            [
                ClosureCheck("altitude", commanded_alt, mean(altitudes_m),
                             tolerance.altitude_m, "m"),
                ClosureCheck("airspeed", commanded_tas, mean(airspeeds_kt),
                             tolerance.airspeed_kt, "kt TAS"),
                ClosureCheck("heading", commanded_hdg,
                             commanded_hdg + heading_error,
                             tolerance.heading_deg, "deg"),
                ClosureCheck("settled", 0.0, mean(climb_rates_mps),
                             tolerance.climb_rate_mps, "m/s"),
            ]
        )
