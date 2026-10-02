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
* A :class:`GustProvider` (P6) is a wind-like contribution that goes into
  JSBSim's SEPARATE ``atmosphere/gust-*-fps`` channel rather than the
  ``wind-*`` one, plus an equivalent roll rate for the airframes that
  carry the ``gust/p-equivalent-rad_sec`` injection. It takes the
  aircraft's own state (:class:`OwnShipState`: position, velocity,
  attitude, span) because a gust field is sampled where the aircraft
  is and a roll moment depends on how wide it is. Contributions sum,
  and the stack writes the sum EVERY step including zero, because the
  gust channel persists in JSBSim until it is written again (measured
  on 1.2.4: 7 fps written once reads 7.0 after 11 steps; docs/
  JSBSIM_CORRECTIONS.md 17).

Every provider must also declare its vocabulary and the physical definition
behind it (§2.5). A provider that cannot say what "moderate" means, with a
citation and a range, is not finished.

NOT claimed by this module: any physics. It is the contract the providers
and the stack meet at; every existing class is byte-compatible with what
it was before ``GustProvider`` and ``OwnShipState`` were added.
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


@dataclass(frozen=True)
class OwnShipState:
    """The aircraft as a gust provider sees it (P6, blueprint correction 4):
    where it is, how it moves over the ground (NED, m/s), how it is
    pointed (degrees), how wide it is (span, m) and its true airspeed.

    Heading and span are what a rotational gust needs: a frozen field
    is convected along the heading, and an equivalent roll rate is a
    spanwise integral. Everything here is read from the FDM by the
    stack (``EnvironmentStack.own_ship_of``); a provider never writes it.
    """

    position: Position
    v_north_mps: float
    v_east_mps: float
    v_down_mps: float
    roll_deg: float
    pitch_deg: float
    heading_deg: float
    span_m: float
    tas_mps: float


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

    @abstractmethod
    def expected_sigma_w_mps(self, agl_m: float) -> float:
        """Predicted vertical RMS gust velocity, for the null test to check."""


class GustProvider(Provider):
    """Contributes a gust vector to JSBSim's ``atmosphere/gust-*-fps``
    channel and, for an airframe that carries the ``gust_rotation``
    injection (core/control/derive.py), an equivalent roll rate into
    ``gust/p-equivalent-rad_sec``.

    Why a separate class from :class:`WindProvider`: the gust channel is
    a different JSBSim slot with a different persistence rule (a value
    written once STAYS until written again, measured), it is summed by
    JSBSim beside the wind and the Dryden turbulence (``vTotalWind =
    wind + gust + cosineGust + turb``, FGWinds.cpp v1.2.4 L157), and a
    gust field is a function of the aircraft's own state, not of a
    point alone. Contributions from several providers sum; the stack
    writes the sum every step, zero included.
    """

    def gust_at(self, own_ship: OwnShipState, time_s: float) -> WindNED:
        """Gust contribution, NED m/s, at the aircraft's state and time.
        Zero by default so a provider that only rolls need not override."""
        return WindNED()

    def p_equivalent_at(self, own_ship: OwnShipState, time_s: float) -> float:
        """Equivalent roll rate in rad/s, delivered to
        ``gust/p-equivalent-rad_sec`` where that property exists (the
        derived airframe) and recorded as NOT delivered where it does
        not (a stock airframe). Zero by default."""
        return 0.0
