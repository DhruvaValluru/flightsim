"""Environment providers: the one tier of the physics that is safely pluggable.

§2.4 is precise about why this seam exists and the aerodynamic ones do not.
Wind contributions compose because velocity fields superpose linearly: two
providers each returning a vector can simply be added, and the result is a
physically meaningful wind field. Aerodynamic forces do not compose that way --
air density appears once, as rho in dynamic pressure, and a "density plugin"
plus a "lift plugin" would double-count it and break energy conservation
silently.

So the contract here is narrow on purpose:

* A :class:`WindProvider` is a pure function of (position, time) returning a
  wind vector in NED. Contributions are summed.
* An :class:`AtmosphereProvider` perturbs the atmosphere state itself --
  temperature and pressure deviations -- of which there is exactly one.
* A :class:`TurbulenceProvider` configures a stochastic process that lives
  inside JSBSim and cannot be expressed as a summed vector.

Every provider must also declare its vocabulary and the physical definition
behind it (§2.5). A provider that cannot say what "moderate" means, with a
citation and a range, is not finished.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Position:
    """Where the aircraft is. Providers are pure functions of this and time."""

    latitude_deg: float
    longitude_deg: float
    altitude_m: float      #: MSL
    agl_m: float
    terrain_elevation_m: float


@dataclass(frozen=True)
class WindNED:
    """A wind contribution, in m/s, north/east/down.

    Down is positive downward, matching JSBSim's NED convention, so a positive
    ``down`` is sinking air and updraught is negative.
    """

    north: float = 0.0
    east: float = 0.0
    down: float = 0.0

    def __add__(self, other: "WindNED") -> "WindNED":
        return WindNED(self.north + other.north,
                       self.east + other.east,
                       self.down + other.down)

    @property
    def speed(self) -> float:
        return math.sqrt(self.north ** 2 + self.east ** 2 + self.down ** 2)

    @property
    def horizontal_speed(self) -> float:
        return math.hypot(self.north, self.east)

    @classmethod
    def from_meteorological(cls, speed_mps: float, from_deg: float,
                            down: float = 0.0) -> "WindNED":
        """Build from the bearing the wind blows *from*, which is how it is reported."""
        radians = math.radians(from_deg)
        return cls(-speed_mps * math.cos(radians),
                   -speed_mps * math.sin(radians),
                   down)


@dataclass(frozen=True)
class Term:
    """One entry in a provider's vocabulary (§2.5).

    A provider does not merely implement an effect. It declares the phrases it
    handles, what each resolves to numerically, the standard behind that
    mapping, and the range over which it is valid.
    """

    phrase: str
    value: Any
    unit: Optional[str]
    standard: str
    valid_range: Optional[Tuple[float, float]] = None
    note: Optional[str] = None

    def render(self) -> str:
        value = f"{self.value:g}" if isinstance(self.value, float) else str(self.value)
        unit = f" {self.unit}" if self.unit else ""
        rng = (f", valid {self.valid_range[0]:g}-{self.valid_range[1]:g}"
               if self.valid_range else "")
        note = f" -- {self.note}" if self.note else ""
        return f'"{self.phrase}" -> {value}{unit} [{self.standard}{rng}]{note}'


class Provider(ABC):
    """Base for everything in the environment tier."""

    #: Short stable identifier, used in manifests and null-test names.
    name: str = "provider"

    @abstractmethod
    def vocabulary(self) -> List[Term]:
        """The phrases this provider handles and what they resolve to (§2.5)."""

    def provenance(self) -> Dict[str, Any]:
        """What goes in the run manifest."""
        return {"name": self.name, "type": type(self).__name__}

    def describe(self) -> str:
        return f"{self.name} ({type(self).__name__})"


class WindProvider(Provider):
    """Contributes a wind vector. Contributions from several providers sum."""

    @abstractmethod
    def wind_at(self, position: Position, time_s: float) -> WindNED:
        """Wind contribution at a point in space and time. Must be pure."""


class AtmosphereProvider(Provider):
    """Perturbs the atmosphere state. There is exactly one of these."""

    @abstractmethod
    def properties(self, position: Position, time_s: float) -> Dict[str, float]:
        """JSBSim atmosphere properties to write, already in JSBSim units."""


class TurbulenceProvider(Provider):
    """Configures a stochastic process that lives inside JSBSim.

    Kept separate from :class:`WindProvider` because it is not a vector that can
    be summed: JSBSim integrates the Dryden filters internally and exposes the
    result through ``atmosphere/turb-*``. Modelling it as a contribution would
    mean reimplementing a filter that already exists and is already validated
    against the same standard.
    """

    @abstractmethod
    def configure(self) -> Dict[str, float]:
        """One-time JSBSim properties. Written at setup, NOT every step.

        Writing these repeatedly is not harmless. Re-writing
        ``atmosphere/randomseed`` on every step re-seeds the generator and
        destroys the correlated noise process: measured on the pinned build,
        peak turbulence went from 37.6 fps to 566 fps and peak load factor from
        0.40 g to 515 g. See docs/JSBSIM_CORRECTIONS.md.
        """

    def step_writes(self, position: Position, time_s: float) -> Dict[str, float]:
        """Per-step intensity writes, for providers whose intensity moves.

        Empty by default: a constant-intensity process needs nothing inside
        the loop. A provider that overrides this may write **W20 only** --
        never the seed (§9's 515 g failure) and never the POE severity, whose
        mid-run changes deliver 2-5x the commanded sigma_w (measured,
        docs/JSBSIM_CORRECTIONS.md §13).
        """
        return {}

    def observe(self, fdm) -> None:
        """Read what the process DELIVERED this step. Called after the
        step writes, every step, by the stack. Read-only: a provider that
        wants to know whether its intensity reached the FDM accumulates
        ``atmosphere/turb-*`` here and never writes anything."""

    @abstractmethod
    def expected_sigma_w_mps(self, agl_m: float) -> float:
        """Predicted vertical RMS gust velocity, for the null test to check."""
