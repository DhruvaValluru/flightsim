"""Trim, and verification that the trim is real.

The previous build never trimmed. Its clip began at 201 kt with 233 kt
commanded, 290 m with 300 m commanded, and 7 degrees of bank with no roll
command -- an airframe dropped into the sky with arbitrary control-surface
positions. The entire 12-second recording was the initialisation transient, the
segment research code exists to discard (§1.1).

Two rules follow, and both are enforced here.

1. **Trim failure is a hard error.** JSBSim logs ``Trim Failed!!!`` and carries
   on with partial state. That is a silent fallback (§2.7) and it is overridden.
2. **A converged solver is not a trimmed aircraft.** The trim algorithm can
   settle on a linearised approximation that is not an equilibrium of the full
   nonlinear model. :func:`verify_trim_holds` therefore integrates the real
   model forward at frozen controls and measures the drift, rather than
   trusting the solver's own report.

Version note (JSBSim 1.2.4, measured): ``FGFDMExec.SetGammaFallback`` is not
exposed by the Python bindings, so the gamma-fallback retry available in C++
cannot be used from the headless host. The only retry path here is relaxing the
initial condition toward a plausible envelope point, which the caller does
explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

import jsbsim

from .errors import TrimError


class TrimMode(IntEnum):
    """JSBSim trim modes.

    Values confirmed against the pinned 1.2.4 ``do_trim`` docstring:
    ``tLongitudinal=0 * tFull * tGround * tPullup * tCustom * tTurn * tNone``.
    """

    LONGITUDINAL = 0   #: symmetric straight-and-level flight
    FULL = 1           #: turns, crosswind starts -- solves lateral axes too
    GROUND = 2         #: on-ground starts
    PULLUP = 3
    CUSTOM = 4
    TURN = 5
    NONE = 6


#: Which mode a scenario needs, given what it asks for. Straight symmetric
#: flight is cheapest and most reliable; anything with bank, sideslip or a
#: crosswind component needs the lateral axes solved as well (§5 Phase 0).
def mode_for(on_ground: bool = False, banked: bool = False, crosswind: bool = False) -> TrimMode:
    if on_ground:
        return TrimMode.GROUND
    if banked or crosswind:
        return TrimMode.FULL
    return TrimMode.LONGITUDINAL


@dataclass(frozen=True)
class TrimDrift:
    """Measured drift over a hands-off verification run."""

    duration_s: float
    altitude_drift_m: float        # signed, end minus start
    altitude_excursion_m: float    # max absolute deviation from start
    airspeed_drift_kt: float
    airspeed_excursion_kt: float
    roll_excursion_deg: float
    max_abs_climb_rate_mps: float
    #: Peak-to-peak of the second half minus that of the first half. Positive
    #: means the oscillation is growing -- a divergent mode the solver hid.
    altitude_growth_m: float

    def summary(self) -> str:
        return (
            f"over {self.duration_s:.0f}s hands-off: "
            f"alt drift {self.altitude_drift_m:+.2f} m "
            f"(excursion {self.altitude_excursion_m:.2f} m, "
            f"growth {self.altitude_growth_m:+.2f} m), "
            f"IAS drift {self.airspeed_drift_kt:+.2f} kt "
            f"(excursion {self.airspeed_excursion_kt:.2f} kt), "
            f"roll excursion {self.roll_excursion_deg:.2f} deg, "
            f"peak |h-dot| {self.max_abs_climb_rate_mps:.3f} m/s"
        )


def trim(exec_, mode: TrimMode = TrimMode.LONGITUDINAL) -> None:
    """Trim the aircraft, or raise.

    Raises
    ------
    TrimError
        On non-convergence. There is deliberately no fallback: proceeding past
        a failed trim is what turned an entire recording into a transient.
    """
    try:
        exec_.do_trim(int(mode))
    except jsbsim.TrimFailureError as exc:
        raise TrimError(
            f"Trim failed in mode {mode.name} ({int(mode)}): {exc}. "
            f"JSBSim would continue from here with partial state; a research "
            f"run must not. Relax the initial condition toward a plausible "
            f"envelope point and retry, or choose a different trim mode."
        ) from exc


def verify_trim_holds(
    fdm,
    duration_s: float = 60.0,
    sample_interval_s: float = 0.5,
) -> TrimDrift:
    """Integrate forward at frozen controls and measure how far the state moves.

    This is the check the solver cannot do for itself. Controls are left exactly
    where trim put them; nothing is commanded during the run.

    Returns
    -------
    TrimDrift
        Measured drift. Interpreting it against a tolerance is the caller's job
        (see :mod:`experiments.gate0_trim_hold`), so that the same measurement
        can back both a pass/fail gate and a reported number.
    """
    start = fdm.state()
    alt0, ias0 = start.altitude_m, start.cas_kt

    altitudes = []
    ias_dev = 0.0
    roll_dev = 0.0
    max_hdot = 0.0

    next_sample = 0.0
    elapsed = 0.0
    while elapsed < duration_s:
        fdm.step()
        elapsed = fdm.sim_time - start.t
        if elapsed >= next_sample:
            s = fdm.state()
            altitudes.append(s.altitude_m)
            ias_dev = max(ias_dev, abs(s.cas_kt - ias0))
            roll_dev = max(roll_dev, abs(s.roll_deg - start.roll_deg))
            max_hdot = max(max_hdot, abs(s.climb_rate_mps))
            next_sample += sample_interval_s

    end = fdm.state()

    # Growing oscillation check: compare peak-to-peak across the two halves.
    # A converged-but-divergent mode shows up here even when the net drift over
    # the window happens to be small.
    half = max(1, len(altitudes) // 2)
    first, second = altitudes[:half], altitudes[half:]
    ptp = lambda xs: (max(xs) - min(xs)) if xs else 0.0

    return TrimDrift(
        duration_s=end.t - start.t,
        altitude_drift_m=end.altitude_m - alt0,
        altitude_excursion_m=max((abs(a - alt0) for a in altitudes), default=0.0),
        airspeed_drift_kt=end.cas_kt - ias0,
        airspeed_excursion_kt=ias_dev,
        roll_excursion_deg=roll_dev,
        max_abs_climb_rate_mps=max_hdot,
        altitude_growth_m=ptp(second) - ptp(first),
    )
