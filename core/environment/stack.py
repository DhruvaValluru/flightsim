"""The environment stack: sum the providers, write them to the FDM every step.

Two rules that are easy to get wrong and silent when you do.

**Wind must be written inside the step loop.** JSBSim's atmosphere model
rewrites the wind properties as it runs, so a value set once at initialisation
is gone by the time the aircraft flies through it. That is the §1.6 failure
exactly: a condition that is configured, reported, and never reaches the FDM.

**Turbulence configuration must NOT be written inside the step loop.** It
configures a stochastic process with internal state. Re-writing
``atmosphere/randomseed`` every step re-seeds the generator and destroys the
correlated noise: measured on the pinned build, peak turbulence went from
37.6 fps to 566 fps and peak load factor from 0.40 g to 515 g, which reads as
violent turbulence rather than as a bug.

So the stack does both, and does them differently, and the null tests check that
each one actually arrived.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..fdm import units as u
from .base import (
    AtmosphereProvider,
    Position,
    Provider,
    TurbulenceProvider,
    WindNED,
    WindProvider,
)


class EnvironmentStack:
    """A set of providers, applied to an FDM instance every step."""

    def __init__(self, providers: Optional[List[Provider]] = None) -> None:
        self.wind: List[WindProvider] = []
        self.atmosphere: List[AtmosphereProvider] = []
        self.turbulence: List[TurbulenceProvider] = []
        for provider in providers or []:
            self.add(provider)

    def add(self, provider: Provider) -> "EnvironmentStack":
        if isinstance(provider, WindProvider):
            self.wind.append(provider)
        elif isinstance(provider, AtmosphereProvider):
            self.atmosphere.append(provider)
        elif isinstance(provider, TurbulenceProvider):
            if self.turbulence:
                raise ValueError(
                    "only one turbulence provider is meaningful: they configure "
                    "the same JSBSim process, so a second would silently "
                    "overwrite the first"
                )
            self.turbulence.append(provider)
        else:
            raise TypeError(f"{provider!r} is not an environment provider")
        return self

    @property
    def providers(self) -> List[Provider]:
        return [*self.wind, *self.atmosphere, *self.turbulence]

    def __len__(self) -> int:
        return len(self.providers)

    # -- evaluation -----------------------------------------------------

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        """Sum of every wind contribution. Velocity fields superpose (§2.4)."""
        total = WindNED()
        for provider in self.wind:
            total = total + provider.wind_at(position, time_s)
        return total

    @staticmethod
    def position_of(fdm) -> Position:
        state = fdm.state()
        return Position(
            latitude_deg=state.lat_deg,
            longitude_deg=state.lon_deg,
            altitude_m=state.altitude_m,
            agl_m=state.agl_m,
            terrain_elevation_m=state.terrain_elev_m,
        )

    # -- application ----------------------------------------------------

    def configure(self, fdm) -> None:
        """One-time setup. Call once, before stepping, after trim.

        Turbulence lands here rather than in :meth:`apply` because it seeds a
        stochastic process; see the module docstring.
        """
        writes: Dict[str, float] = {}
        for provider in self.turbulence:
            writes.update(provider.configure())
        if not self.turbulence:
            # An explicit "no turbulence" rather than whatever the model left.
            writes["atmosphere/turb-type"] = 0.0
        fdm.props.set_many(writes)

    def apply(self, fdm) -> WindNED:
        """Write the summed wind to the FDM. Call every step.

        Returns the wind written, so a caller can record what was commanded
        alongside what the FDM reports as total wind -- the two should agree
        except for the turbulence the FDM adds internally.
        """
        position = self.position_of(fdm)
        time_s = fdm.sim_time

        wind = self.wind_at(position, time_s)
        writes = {
            "atmosphere/wind-north-fps": u.mps_to_fps(wind.north),
            "atmosphere/wind-east-fps": u.mps_to_fps(wind.east),
            "atmosphere/wind-down-fps": u.mps_to_fps(wind.down),
        }
        for provider in self.atmosphere:
            writes.update(provider.properties(position, time_s))
        # Turbulence *intensity* writes only (W20). The seed and severity are
        # configure()-time and never appear here: see TurbulenceProvider.
        for provider in self.turbulence:
            writes.update(provider.step_writes(position, time_s))
        fdm.props.set_many(writes)
        # What the process delivered (Package F): read-only, after the
        # writes, so a provider can report the sigma_w the FDM actually
        # produced along the track rather than the one it claimed.
        for provider in self.turbulence:
            provider.observe(fdm)
        return wind

    def run_for(self, fdm, seconds: float, recorder=None) -> int:
        """Step the FDM with the environment applied every step."""
        steps = int(round(seconds * fdm.rate_hz))
        for _ in range(steps):
            self.apply(fdm)
            fdm.step()
            if recorder is not None:
                recorder.sample()
        return steps

    # -- reporting ------------------------------------------------------

    def provenance(self) -> List[Dict[str, Any]]:
        return [p.provenance() for p in self.providers]

    def vocabulary_report(self) -> str:
        """Every phrase this stack understands and what it resolves to (§2.5)."""
        lines = []
        for provider in self.providers:
            lines.append(f"{provider.describe()}:")
            for term in provider.vocabulary():
                lines.append(f"    {term.render()}")
        return "\n".join(lines)
