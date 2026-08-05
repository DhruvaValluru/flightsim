"""Discrete gusts: the 1-cosine shape from MIL-F-8785C.

Implemented as a wind contribution rather than through JSBSim's
``atmosphere/cosine-gust/*`` interface, for one reason: as a summed vector it
composes with everything else in the stack and is a pure function of time, so
the null test can predict its peak exactly and check it.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Position, Term, WindNED, WindProvider

#: Standard gust gradient distances, in metres. MIL-F-8785C specifies the
#: 1-cosine gust over a gradient distance; 25 chord lengths is the classic
#: discrete-gust case and 120 m is the reference length in the standard.
GRADIENT_M = {"short": 30.0, "standard": 120.0, "long": 350.0}
GUST_STANDARD = "MIL-F-8785C discrete 1-cosine gust"

#: Peak gust velocity for each intensity word, in m/s.
PEAK_MPS = {"light": 3.0, "moderate": 7.5, "severe": 15.0}


class DiscreteGust(WindProvider):
    """A single 1-cosine gust, in a chosen axis.

        V(t) = (Vm / 2) * (1 - cos(pi * t / T))   for 0 <= t <= 2T

    where T is the time to traverse the gradient distance. Zero before the
    start and after the gust has passed, so a run without one is bit-identical
    to a run whose gust has not begun.
    """

    name = "discrete_gust"

    def __init__(
        self,
        peak_mps: float,
        start_s: float,
        gradient_m: float = 120.0,
        airspeed_mps: float = 130.0,
        axis: str = "down",
    ) -> None:
        if axis not in ("north", "east", "down"):
            raise ValueError(f"gust axis must be north, east or down: {axis!r}")
        if gradient_m <= 0 or airspeed_mps <= 0:
            raise ValueError("gradient distance and airspeed must be positive")
        self.peak_mps = float(peak_mps)
        self.start_s = float(start_s)
        self.gradient_m = float(gradient_m)
        self.airspeed_mps = float(airspeed_mps)
        self.axis = axis
        #: Time to traverse the gradient distance at the reference airspeed.
        self.half_period_s = self.gradient_m / self.airspeed_mps

    def magnitude_at(self, time_s: float) -> float:
        """Gust velocity at a time, m/s. Exactly zero outside the window."""
        elapsed = time_s - self.start_s
        if elapsed < 0.0 or elapsed > 2.0 * self.half_period_s:
            return 0.0
        return 0.5 * self.peak_mps * (
            1.0 - math.cos(math.pi * elapsed / self.half_period_s)
        )

    @property
    def peak_time_s(self) -> float:
        return self.start_s + self.half_period_s

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        magnitude = self.magnitude_at(time_s)
        if magnitude == 0.0:
            return WindNED()
        return WindNED(**{self.axis: magnitude})

    def vocabulary(self) -> List[Term]:
        terms = [
            Term(phrase, value, "m/s peak", GUST_STANDARD, (0.0, 30.0))
            for phrase, value in PEAK_MPS.items()
        ]
        terms += [
            Term(f"{phrase} gradient", value, "m", GUST_STANDARD, (10.0, 500.0))
            for phrase, value in GRADIENT_M.items()
        ]
        return terms

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "peak_mps": self.peak_mps, "start_s": self.start_s,
                "gradient_m": self.gradient_m, "axis": self.axis,
                "half_period_s": self.half_period_s}
