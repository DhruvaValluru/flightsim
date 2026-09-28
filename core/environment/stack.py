"""The environment stack: sum the providers, write them to the FDM every step.

Three rules that are easy to get wrong and silent when you do.

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

**The gust channel must be written every step, ZERO INCLUDED.** JSBSim's
``atmosphere/gust-*-fps`` is never reset by the model (FGWinds.cpp v1.2.4
L145-L157: only ``vTurbulenceNED`` is zeroed; ``vGustNED`` is added as it
stands): a value written once stays until written again (7 fps read 7.0
after 11 steps, measured; docs/JSBSIM_CORRECTIONS.md 17). A provider whose
gust has passed and that stops writing would leave its last value blowing
for the rest of the flight. So the stack sums every gust provider and
writes the sum every step -- 0.0 when there is none -- reads each gust
property back before the next write, and delivers the equivalent roll rate
into ``gust/p-equivalent-rad_sec`` only where the loaded airframe declares
it (the ``gust_rotation`` injection), recording ``property`` or ``absent``.

So the stack does all three, does them differently, and the null tests check
that each one actually arrived.

NOT claimed: the physics of any provider (each states its own); that a gust
written into a stock airframe rolls it (the roll term needs the derived
airframe, and the record says ``absent``); the engine side.
"""

from __future__ import annotations

import inspect
import math
from typing import Any, Callable, Dict, List, Optional

from ..fdm import units as u
from .base import (
    AtmosphereProvider,
    GustProvider,
    OwnShipState,
    Position,
    Provider,
    TurbulenceProvider,
    WindNED,
    WindProvider,
)

#: The gust channel, NED order (RW on the 1.2.4 catalog, measured).
GUST_PROPERTIES = ("atmosphere/gust-north-fps", "atmosphere/gust-east-fps",
                   "atmosphere/gust-down-fps")
WIND_PROPERTIES = ("atmosphere/wind-north-fps", "atmosphere/wind-east-fps",
                   "atmosphere/wind-down-fps")
#: Declared by the gust_rotation injection only (core/control/derive.py).
P_EQUIVALENT_PROPERTY = "gust/p-equivalent-rad_sec"
#: The recorder columns the stack itself supplies (the wind profile's
#: layer report; not JSBSim's, so read through Recorder ``extra``).
STACK_CHANNELS = ("wind_layer_index", "shear_dv_dz_per_s")


class _Readback:
    """Per-property read-back bookkeeping: what was last written, what
    came back before the next write, the worst error, the running
    standard deviation of what came back (for the gust null test)."""

    def __init__(self, properties) -> None:
        self.properties = tuple(properties)
        self.last_written: Dict[str, float] = {}
        #: The writes the last read-back was checked against (the write
        #: before it; the very last write of a run is never read back).
        self.checked_written: Dict[str, float] = {}
        self.last_read: Dict[str, float] = {}
        self.max_abs_error: Dict[str, float] = {}
        self.steps_written = 0
        self.steps_checked = 0
        self._n = 0
        self._sum: Dict[str, float] = {p: 0.0 for p in self.properties}
        self._sumsq: Dict[str, float] = {p: 0.0 for p in self.properties}

    def observe(self, fdm) -> None:
        if not self.last_written:
            return
        self.checked_written = dict(self.last_written)
        for prop, written in self.last_written.items():
            read = fdm.props.get(prop)
            self.last_read[prop] = read
            self.max_abs_error[prop] = max(self.max_abs_error.get(prop, 0.0),
                                           abs(read - written))
            if prop in self._sum:
                self._sum[prop] += read
                self._sumsq[prop] += read * read
        self._n += 1
        self.steps_checked += 1

    def written(self, writes: Dict[str, float]) -> None:
        self.last_written = dict(writes)
        self.steps_written += 1

    def std_fps(self) -> Dict[str, float]:
        if self._n == 0:
            return {}
        out = {}
        for prop in self.properties:
            mean = self._sum[prop] / self._n
            out[prop] = math.sqrt(max(0.0, self._sumsq[prop] / self._n - mean * mean))
        return out

    def report(self) -> Dict[str, Any]:
        return {"properties": list(self.properties),
                "steps_written": self.steps_written, "steps_checked": self.steps_checked,
                "last_written": dict(self.checked_written), "last_read": dict(self.last_read),
                "final_write": dict(self.last_written),
                "max_abs_error": dict(self.max_abs_error),
                "agrees": all(e == 0.0 for e in self.max_abs_error.values())}


class EnvironmentStack:
    """A set of providers, applied to an FDM instance every step."""

    def __init__(self, providers: Optional[List[Provider]] = None) -> None:
        #: What the runner decided NOT to attach, and why (W1: a roughness
        #: inference the land-cover map could not make); carried into the
        #: manifest's environment provenance beside the providers.
        self.notes: List[Dict[str, Any]] = []
        self.wind: List[WindProvider] = []
        self.atmosphere: List[AtmosphereProvider] = []
        self.turbulence: List[TurbulenceProvider] = []
        self.gust: List[GustProvider] = []
        self._wind_readback = _Readback(WIND_PROPERTIES)
        self._gust_readback = _Readback(GUST_PROPERTIES + (P_EQUIVALENT_PROPERTY,))
        self._p_equivalent: Optional[bool] = None
        self._span_m: Optional[float] = None
        for provider in providers or []:
            self.add(provider)

    def add(self, provider: Provider) -> "EnvironmentStack":
        if isinstance(provider, GustProvider):
            self.gust.append(provider)
        elif isinstance(provider, WindProvider):
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
        return [*self.wind, *self.atmosphere, *self.turbulence, *self.gust]

    def __len__(self) -> int:
        return len(self.providers)

    # -- evaluation -----------------------------------------------------

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        """Sum of every wind contribution. Velocity fields superpose (§2.4)."""
        total = WindNED()
        for provider in self.wind:
            total = total + provider.wind_at(position, time_s)
        return total

    def gust_at(self, own_ship: OwnShipState, time_s: float) -> WindNED:
        """Sum of every gust contribution (the separate JSBSim channel)."""
        total = WindNED()
        for provider in self.gust:
            total = total + provider.gust_at(own_ship, time_s)
        return total

    def p_equivalent_at(self, own_ship: OwnShipState, time_s: float) -> float:
        return sum(provider.p_equivalent_at(own_ship, time_s) for provider in self.gust)

    @property
    def profile_providers(self) -> List[WindProvider]:
        """The wind providers that carry the whole horizontal wind (P6's
        layered / milspec / NWP profiles)."""
        return [p for p in self.wind if getattr(p, "carries_base_wind", False)]

    def profile_wind_at(self, position: Position) -> Optional[WindNED]:
        """The profile's wind at a position (for the trim), or None when
        no profile provider is in the stack."""
        profiles = self.profile_providers
        if not profiles:
            return None
        total = WindNED()
        for provider in profiles:
            total = total + provider.wind_at(position, 0.0)
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

    def own_ship_of(self, fdm) -> OwnShipState:
        """The aircraft's own state for the gust providers: position, NED
        velocity, attitude, span (``metrics/bw-ft``, read once) and TAS."""
        state = fdm.state()
        if self._span_m is None:
            self._span_m = u.ft_to_m(fdm.props.get("metrics/bw-ft"))
        return OwnShipState(
            position=Position(state.lat_deg, state.lon_deg, state.altitude_m,
                              state.agl_m, state.terrain_elev_m),
            v_north_mps=state.v_north_mps, v_east_mps=state.v_east_mps,
            v_down_mps=state.v_down_mps, roll_deg=state.roll_deg,
            pitch_deg=state.pitch_deg, heading_deg=state.heading_deg,
            span_m=self._span_m, tas_mps=u.kt_to_mps(state.tas_kt))

    # -- application ----------------------------------------------------

    def prepare(self, fdm) -> Dict[str, Any]:
        """The pre-trim hook. Call once, after the initial conditions and
        BEFORE the trim (gap P1).

        ``configure`` runs after the trim, so anything written there is
        invisible to the trim solver: a hot day applied that way trims the
        aircraft in ISA air and then flies it in hot air (measured: the
        trimmed throttle differs). Atmosphere providers are written here,
        through their own ``prepare(fdm)`` when they have one (which also
        measures the with/without pair for the record) and through
        ``properties`` otherwise. Gust providers with a ``prepare`` hook
        run AFTER the atmosphere (P6: the von Karman table is built from
        the true airspeed the stated day gives). Returns each provider's
        report by name.
        """
        report: Dict[str, Any] = {}
        for provider in self.atmosphere:
            hook = getattr(provider, "prepare", None)
            if hook is not None:
                report[provider.name] = hook(fdm)
            else:
                writes = provider.properties(self.position_of(fdm), fdm.sim_time)
                fdm.props.set_many(writes)
                report[provider.name] = {"writes": writes}
        for provider in self.gust:
            hook = getattr(provider, "prepare", None)
            if hook is not None:
                report[provider.name] = hook(fdm)
        return report

    def applied_variables(self) -> List[Any]:
        """Every ``AppliedVariable`` the providers return (those that
        define ``applied_variables``), in provider order. A hook that
        takes an argument is given the stack's delivery report (the
        per-step read-back of the wind and gust channels)."""
        out: List[Any] = []
        report = self.delivery_report()
        for provider in self.providers:
            hook = getattr(provider, "applied_variables", None)
            if hook is None:
                continue
            if inspect.signature(hook).parameters:
                out.extend(hook(report))
            else:
                out.extend(hook())
        return out

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

    def p_equivalent_available(self, fdm) -> bool:
        """Whether the loaded airframe declares ``gust/p-equivalent-rad_sec``
        (the derived airframe with the gust_rotation injection; a stock
        airframe does not), probed once on the catalog."""
        if self._p_equivalent is None:
            self._p_equivalent = bool(fdm.props.has(P_EQUIVALENT_PROPERTY))
        return self._p_equivalent

    def apply(self, fdm) -> WindNED:
        """Write the summed wind and the summed gust to the FDM. Call every step.

        Returns the wind written, so a caller can record what was commanded
        alongside what the FDM reports as total wind -- the two should agree
        except for the turbulence the FDM adds internally and the gust
        channel, which is written beside it.
        """
        position = self.position_of(fdm)
        time_s = fdm.sim_time

        # The atmosphere read-back: what the previous step was given is read
        # back BEFORE this step's write, so the record says whether a JSBSim
        # step overwrote it (it does not, measured; recorded, not assumed).
        for provider in self.atmosphere:
            observe = getattr(provider, "observe", None)
            if observe is not None:
                observe(fdm)
        # The same for the wind and gust channels (P6).
        self._wind_readback.observe(fdm)
        self._gust_readback.observe(fdm)

        wind = self.wind_at(position, time_s)
        writes = {
            WIND_PROPERTIES[0]: u.mps_to_fps(wind.north),
            WIND_PROPERTIES[1]: u.mps_to_fps(wind.east),
            WIND_PROPERTIES[2]: u.mps_to_fps(wind.down),
        }
        self._wind_readback.written(writes)
        for provider in self.atmosphere:
            writes.update(provider.properties(position, time_s))
        # Turbulence *intensity* writes only (W20). The seed and severity are
        # configure()-time and never appear here: see TurbulenceProvider.
        for provider in self.turbulence:
            writes.update(provider.step_writes(position, time_s))
        # The gust sum, EVERY step, zero included: the channel persists.
        gust = WindNED()
        p_equivalent = 0.0
        if self.gust:
            own_ship = self.own_ship_of(fdm)
            gust = self.gust_at(own_ship, time_s)
            p_equivalent = self.p_equivalent_at(own_ship, time_s)
        gust_writes = {
            GUST_PROPERTIES[0]: u.mps_to_fps(gust.north),
            GUST_PROPERTIES[1]: u.mps_to_fps(gust.east),
            GUST_PROPERTIES[2]: u.mps_to_fps(gust.down),
        }
        if self.p_equivalent_available(fdm):
            gust_writes[P_EQUIVALENT_PROPERTY] = p_equivalent
        self._gust_readback.written(gust_writes)
        writes.update(gust_writes)
        fdm.props.set_many(writes)
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

    def recorder_extras(self) -> Dict[str, Callable[[Any], float]]:
        """The stack's own recorder columns (``Recorder(extra=...)``): the
        wind profile's layer index and vertical speed gradient at the
        last evaluation, 0 when no profile provider is in the stack."""
        def value(key: str) -> Callable[[Any], float]:
            def read(_fdm) -> float:
                total = 0.0
                for provider in self.profile_providers:
                    total += float(provider.last.get(key, 0.0))
                return total
            return read

        return {"wind_layer_index": value("layer_index"),
                "shear_dv_dz_per_s": value("dv_dz_per_s")}

    def delivery_report(self) -> Dict[str, Any]:
        """What the stack wrote and read back: the wind channel, the gust
        channel (with the std of each gust property as read back, m/s)
        and whether the roll gust had a property to go to."""
        gust = self._gust_readback.report()
        std = self._gust_readback.std_fps()
        gust["channel_std_mps"] = {
            axis: u.fps_to_mps(std[prop]) for axis, prop in
            zip(("north", "east", "down"), GUST_PROPERTIES) if prop in std}
        gust["p_equivalent"] = ("unknown" if self._p_equivalent is None
                                else "property" if self._p_equivalent else "absent")
        gust["p_equivalent_property"] = P_EQUIVALENT_PROPERTY
        gust["providers"] = [p.name for p in self.gust]
        return {"wind": self._wind_readback.report(), "gust": gust}

    def provenance(self) -> List[Dict[str, Any]]:
        return [p.provenance() for p in self.providers] + [dict(n) for n in self.notes]

    def vocabulary_report(self) -> str:
        """Every phrase this stack understands and what it resolves to (§2.5)."""
        lines = []
        for provider in self.providers:
            lines.append(f"{provider.describe()}:")
            for term in provider.vocabulary():
                lines.append(f"    {term.render()}")
        return "\n".join(lines)
