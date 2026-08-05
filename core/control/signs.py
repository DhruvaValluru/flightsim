"""Measure each airframe's control-sign convention instead of assuming it.

JSBSim does not impose a sign convention on ``fcs/*-cmd-norm``. Each aircraft's
own ``<flight_control>`` section decides whether a positive elevator command
pitches the nose up or down, and stock models disagree. Measured on the B747:

    elevator +0.05  ->  pitch 2.60 -> 1.05 deg   (positive = nose DOWN)
    aileron  +0.05  ->  roll  0.00 -> 2.44 deg   (positive = roll RIGHT)
    rudder   +0.05  ->  yaw rate -0.25 deg/s     (positive = yaw LEFT)

A controller that hardcodes one convention does not fail loudly on an airframe
that uses the other. It closes the loop with positive feedback, and the aircraft
diverges -- which is what happened here before this module existed: the first
TECS run pitched down through 2676 m and hit NaN in 89 seconds.

So the sign is measured, once per airframe, on a throwaway instance, and written
into ``ap/sign/*`` for the XML controller to multiply through. If a control
produces no measurable response, that is an error rather than a default,
because a silent +1 would be a coin flip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ..fdm.errors import FDMError

#: Command perturbation used for the probe. Large enough to produce a clean
#: response, small enough to stay in the linear regime.
PROBE_DELTA = 0.05
#: Seconds to integrate before reading the response.
PROBE_SECONDS = 3.0
#: Response below this is treated as "no authority" rather than a sign.
MIN_RESPONSE_DPS = 0.05


class ControlSignError(FDMError):
    """A control's sign convention could not be determined."""


@dataclass(frozen=True)
class ControlSigns:
    """Sign that makes a positive command produce a positive body-axis rate.

    ``elevator = +1`` means a positive command pitches the nose up. The
    controller multiplies its output by this, so its own logic can always be
    written in the natural direction.
    """

    aircraft: str
    elevator: float
    aileron: float
    rudder: float

    def as_properties(self) -> Dict[str, float]:
        return {
            "ap/sign/elevator": self.elevator,
            "ap/sign/aileron": self.aileron,
            "ap/sign/rudder": self.rudder,
        }

    def summary(self) -> str:
        def word(sign, pos, neg):
            return pos if sign > 0 else neg
        return (
            f"{self.aircraft}: +elevator = {word(self.elevator, 'nose up', 'nose down')}, "
            f"+aileron = {word(self.aileron, 'roll right', 'roll left')}, "
            f"+rudder = {word(self.rudder, 'yaw right', 'yaw left')}"
        )


_CACHE: Dict[str, ControlSigns] = {}


def measure(
    aircraft: str,
    altitude_m: float = 6000.0,
    cas_kt: float = 280.0,
    use_cache: bool = True,
) -> ControlSigns:
    """Probe an airframe's control signs on a throwaway instance.

    The convention is a property of the model's flight control section, not of
    the flight condition, so the result is cached per aircraft.
    """
    if use_cache and aircraft in _CACHE:
        return _CACHE[aircraft]

    from ..fdm import units as u
    from ..fdm.fdm import FlightDynamics
    from ..fdm.trim import TrimMode

    def probe(control: str, rate_property: str) -> float:
        fdm = FlightDynamics(aircraft)
        fdm.set_initial_conditions(
            {
                "h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt,
                "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0,
                "beta-deg": 0.0, "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
                "terrain-elevation-ft": 0.0,
            }
        )
        fdm.props.set_many(
            {"atmosphere/wind-north-fps": 0.0, "atmosphere/wind-east-fps": 0.0,
             "atmosphere/turb-type": 0.0}
        )
        fdm.start_engines()
        fdm.trim(TrimMode.LONGITUDINAL)

        name = f"fcs/{control}-cmd-norm"
        fdm.props.set(name, fdm.props.get(name) + PROBE_DELTA)
        fdm.run_for(PROBE_SECONDS)

        import math
        response_dps = math.degrees(fdm.props.get(rate_property))
        if abs(response_dps) < MIN_RESPONSE_DPS:
            raise ControlSignError(
                f"{aircraft!r}: a {PROBE_DELTA:+.2f} {control} command produced "
                f"only {response_dps:+.4f} deg/s of {rate_property} after "
                f"{PROBE_SECONDS:.0f} s. The sign cannot be determined, and "
                f"guessing it would close the loop with positive feedback."
            )
        return 1.0 if response_dps > 0 else -1.0

    signs = ControlSigns(
        aircraft=aircraft,
        elevator=probe("elevator", "velocities/q-rad_sec"),
        aileron=probe("aileron", "velocities/p-rad_sec"),
        rudder=probe("rudder", "velocities/r-rad_sec"),
    )
    _CACHE[aircraft] = signs
    return signs
