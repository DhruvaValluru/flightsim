"""The flight dynamics model: JSBSim, wrapped, with the guarantees §2 requires.

This is the only equations-of-motion implementation in the system and it is not
pluggable (§2.2). There is no second physics path, no Chaos rigid body carrying
aerodynamic forces, and no post-hoc motion filter between the integrator and
the observers.

The wrapper's whole job is to make four things impossible:

* running a different airframe than the one requested (§1.4) -- see
  :mod:`core.fdm.aircraft`;
* touching a property that does not exist (§1.6) -- see
  :mod:`core.fdm.properties`;
* proceeding past a failed trim (§1.1) -- see :mod:`core.fdm.trim`;
* observers writing back into state (§2.1) -- see :mod:`core.fdm.state`.

It has zero Unreal dependency and must keep it (§2.9): the same core runs in a
100-case parameter sweep and inside the engine, and if physics only existed
inside Unreal the research capability would die.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional

import jsbsim

from . import aircraft as ac
from .errors import SimulationError
from .properties import PropertyAccess
from .state import REQUIRED_PROPERTIES, SURFACE_PROPERTIES, AircraftState
from .trim import TrimMode, trim as _trim

#: Default integration rate. 120 Hz matches the fixed rate the official Epic
#: JSBSim UE plugin substeps at (§3.1), so the headless and embedded hosts
#: integrate identically by default rather than by coincidence. Phase 3's
#: timestep-convergence study (Gate 3) is what justifies keeping it.
DEFAULT_RATE_HZ = 120.0

# Note: JSBSim prints a three-line startup banner to stdout from C++ on every
# FGFDMExec construction. Measured on the pinned build, FGJSBBase.debug_lvl = 0
# does NOT suppress it (it only gates later diagnostics), so silencing it would
# require redirecting the OS-level file descriptor around construction. Left
# alone for now rather than shipping a suppression that does not suppress; it
# matters only for sweep log volume, which Phase 7 will address.

#: Initial conditions are order-dependent. Lower rank is applied first.
#:
#: Two dependencies were found by measurement, not by reading source, and both
#: silently produce a condition nobody asked for:
#:
#:   * ``ic/lat-geod-deg`` re-derives the velocity state and reinterprets an
#:     already-converted true airspeed as calibrated, so position must precede
#:     any speed. Requested 300 kt CAS at 10 km became Mach 1.28.
#:   * ``ic/beta-deg`` re-derives the velocity vector's orientation and resets
#:     true heading to zero, so sideslip must precede heading. Requested
#:     heading 270 became 000.
#:
#: The resulting order is verified as a whole rather than reasoned about: the
#: ordering test sets every field to a distinct non-default value and asserts
#: all of them are achieved simultaneously. Both alternative orderings that
#: seem equally reasonable fail it.
_IC_PRIORITY = {
    # geometry first
    "ic/lat-geod-deg": 0,
    "ic/lat-gc-deg": 0,
    "ic/long-gc-deg": 1,
    "ic/terrain-elevation-ft": 2,
    "ic/h-sl-ft": 3,
    "ic/h-agl-ft": 3,
    # attitude, with sideslip strictly before heading
    "ic/phi-deg": 4,
    "ic/beta-deg": 5,
    "ic/psi-true-deg": 6,
    # flight-path terms
    "ic/alpha-deg": 7,
    "ic/theta-deg": 7,
    "ic/gamma-deg": 7,
    "ic/roc-fpm": 7,
    # speed strictly last, so nothing can re-derive it
    "ic/vt-kts": 8,
    "ic/vc-kts": 8,
    "ic/mach": 8,
}
_IC_DEFAULT_RANK = 4


def _ic_rank(name: str) -> int:
    return _IC_PRIORITY.get(name, _IC_DEFAULT_RANK)


#: Initial conditions that live on a circle, where 0 and 360 are the same
#: value. Compared with wrapping rather than by subtraction.
IC_WRAPPED_360 = frozenset({"ic/psi-true-deg"})

#: Requested initial condition -> the state property that proves it took.
#: Used by :meth:`FlightDynamics._verify_initial_conditions`.
IC_ACHIEVED = {
    "ic/h-sl-ft": "position/h-sl-ft",
    "ic/h-agl-ft": "position/h-agl-ft",
    "ic/lat-geod-deg": "position/lat-geod-deg",
    "ic/long-gc-deg": "position/long-gc-deg",
    "ic/terrain-elevation-ft": "position/terrain-elevation-asl-ft",
    "ic/phi-deg": "attitude/phi-deg",
    "ic/theta-deg": "attitude/theta-deg",
    "ic/psi-true-deg": "attitude/psi-deg",
    "ic/alpha-deg": "aero/alpha-deg",
    "ic/beta-deg": "aero/beta-deg",
    "ic/gamma-deg": "flight-path/gamma-deg",
    "ic/vc-kts": "velocities/vc-kts",
    "ic/vt-kts": "velocities/vtrue-kts",
    "ic/mach": "velocities/mach",
}


class FlightDynamics:
    """A trimmed, fixed-step JSBSim instance with checked property access.

    Parameters
    ----------
    aircraft:
        Model name, resolved through :func:`core.fdm.aircraft.resolve`. No
        substitution occurs; an unknown name is an error.
    rate_hz:
        Integration rate. Fixed for the life of the instance -- a variable
        timestep would make runs irreproducible.
    root_dir:
        JSBSim data root. Defaults to the one shipped with the installed wheel.
    """

    def __init__(
        self,
        aircraft: str,
        rate_hz: float = DEFAULT_RATE_HZ,
        root_dir: Optional[Path] = None,
        debug_level: int = 0,
        engine_path: Optional[Path] = None,
        systems_path: Optional[Path] = None,
        derived: Optional[object] = None,
    ) -> None:
        if rate_hz <= 0.0:
            raise ValueError(f"rate_hz must be positive, got {rate_hz}")

        self.model = ac.resolve(aircraft, root_dir)
        self.rate_hz = float(rate_hz)
        self.dt = 1.0 / self.rate_hz
        #: Set when this instance runs a generated TECS-equipped airframe, so
        #: the manifest can name both the stock model and the derivation.
        self.derived = derived

        self._exec = jsbsim.FGFDMExec(root_dir=str(self.model.root_dir))
        self._exec.set_debug_level(debug_level)
        # A derived aircraft lives outside the JSBSim data root, so engines and
        # shared systems still have to be resolved against the stock tree.
        if engine_path is not None:
            self._exec.set_engine_path(str(engine_path))
        if systems_path is not None:
            self._exec.set_systems_path(str(systems_path))

        if not self._exec.load_model(self.model.name):
            raise SimulationError(
                f"JSBSim refused to load {self.model.name!r} from {self.model.xml_path}"
            )
        # The §1.4 guard: a successful load of the *wrong* airframe is the
        # failure mode, so compare what was loaded against what was asked for.
        ac.verify_loaded(self._exec, self.model)

        self._exec.set_dt(self.dt)

        self.props = PropertyAccess(self._exec)
        self.props.require(REQUIRED_PROPERTIES)
        # Resolve the articulation set once; models differ in which they define.
        self._surfaces = tuple(p for p in SURFACE_PROPERTIES if self.props.has(p))

        self._trimmed = False
        self._ic_applied = False
        self._engines_started = False
        self._frozen_tanks: Optional[Dict[str, float]] = None

    @classmethod
    def with_tecs(
        cls,
        base_aircraft: str,
        rate_hz: float = DEFAULT_RATE_HZ,
        root_dir: Optional[Path] = None,
        debug_level: int = 0,
    ) -> "FlightDynamics":
        """Load ``base_aircraft`` with the TECS controller attached.

        The stock model is never modified; a derived airframe is generated and
        both hashes are recorded (see :mod:`core.control.derive`).
        """
        from ..control.derive import derive

        spec = derive(base_aircraft, root_dir=root_dir)
        return cls(
            spec.name,
            rate_hz=rate_hz,
            root_dir=spec.aircraft_path.parent,
            debug_level=debug_level,
            engine_path=spec.engine_path,
            systems_path=spec.systems_path,
            derived=spec,
        )

    # -- identity ------------------------------------------------------

    @property
    def aircraft_name(self) -> str:
        return self.model.name

    @property
    def has_autopilot(self) -> bool:
        """True if the loaded model exposes the TECS control surface."""
        return self.props.has("ap/enable")

    @property
    def sim_time(self) -> float:
        return self._exec.get_sim_time()

    @property
    def is_trimmed(self) -> bool:
        return self._trimmed

    @property
    def surface_properties(self) -> tuple:
        """Control-surface position properties this airframe actually defines."""
        return self._surfaces

    # -- initial conditions --------------------------------------------

    def set_initial_conditions(
        self, ic: Dict[str, float], tolerance: float = 1e-3
    ) -> None:
        """Apply ``ic/*`` properties, latch them with ``run_ic``, and verify they took.

        Keys may be given with or without the ``ic/`` prefix. Every name is
        validated against the catalog before anything is written, so a typo
        cannot leave the aircraft half-initialised at a state nobody asked for.

        Ordering
        --------
        Initial conditions are *not* independent, and JSBSim applies them in the
        order written. Measured on the pinned build: setting ``ic/lat-geod-deg``
        after ``ic/vc-kts`` re-derives the velocity state and reinterprets the
        already-converted true airspeed as calibrated, so a requested 250 kt CAS
        at 3000 m silently becomes 288 kt -- and 300 kt at 10 km becomes Mach
        1.28, well outside any transport envelope. :data:`_IC_PRIORITY` fixes a
        safe order: geometry and environment first, velocity last.

        Verification
        ------------
        Ordering alone is a fix that can rot the moment a new IC key is added,
        so the result is also checked. Each requested condition is compared
        against the state actually achieved, and a mismatch is an error. This is
        the §1.1 guard at the initial-condition layer: the previous build began
        at 201 kt with 233 kt commanded and 290 m with 300 m commanded, and
        nothing anywhere noticed.
        """
        prefixed = {
            (k if k.startswith("ic/") else f"ic/{k}"): float(v) for k, v in ic.items()
        }
        ordered = dict(
            sorted(prefixed.items(), key=lambda kv: _ic_rank(kv[0]))
        )
        self.props.set_many(ordered)

        if not self._exec.run_ic():
            raise SimulationError(
                f"run_ic() failed for {self.model.name!r} with {ordered}"
            )
        # run_ic instantiates further nodes; the catalog must catch up or later
        # legitimate reads would be rejected as unknown.
        self.props.refresh()
        self._verify_initial_conditions(ordered, tolerance)
        self._ic_applied = True
        self._trimmed = False

    def _verify_initial_conditions(
        self, requested: Dict[str, float], tolerance: float
    ) -> None:
        """Compare each requested IC against the state actually achieved."""
        problems = []
        for name, wanted in requested.items():
            achieved_prop = IC_ACHIEVED.get(name)
            if achieved_prop is None or not self.props.has(achieved_prop):
                continue  # nothing to check this against; not an error
            got = self.props.get(achieved_prop)
            if name in IC_WRAPPED_360:
                # Headings wrap: a requested 0 achieved as 360 is the same
                # heading, and reporting it as a 360-degree error would abort a
                # perfectly good run. Surfaced by a scenario placed at a
                # non-zero longitude, where JSBSim returns 360.0 for north.
                error = abs((got - wanted + 180.0) % 360.0 - 180.0)
                scale = 1.0
            else:
                error = abs(got - wanted)
                scale = max(1.0, abs(wanted))
            if error > tolerance * scale:
                problems.append(
                    f"{name}: requested {wanted:.4f}, achieved "
                    f"{got:.4f} (via {achieved_prop})"
                )
        if problems:
            raise SimulationError(
                "Initial conditions did not take:\n  "
                + "\n  ".join(problems)
                + "\nInitial conditions are order-dependent in JSBSim; a later "
                  "one has overwritten an earlier one. Refusing to run: the "
                  "whole recording would be an initialisation transient."
            )

    # -- propulsion ----------------------------------------------------

    @property
    def engine_count(self) -> int:
        """Number of engines the loaded model defines."""
        return len(self._engine_running_properties())

    def _engine_running_properties(self) -> tuple:
        """``set-running`` property for each engine, index 0 unsubscripted."""
        names = []
        i = 0
        while True:
            name = "propulsion/engine/set-running" if i == 0 else f"propulsion/engine[{i}]/set-running"
            if not self.props.has(name):
                break
            names.append(name)
            i += 1
        return tuple(names)

    def _spool_property(self, index: int) -> Optional[str]:
        """The ``n1`` spool property for an engine, if it is a turbine."""
        name = "propulsion/engine/n1" if index == 0 else f"propulsion/engine[{index}]/n1"
        return name if self.props.has(name) else None

    def start_engines(self) -> None:
        """Start every engine and verify each one is actually turning.

        Explicit rather than automatic, and *verified* rather than assumed. An
        unstarted engine does not fail loudly: the trim solver reports
        ``Sorry, udot doesn't appear to be trimmable`` and, if it converges
        anyway, hands back a plausible-looking alpha and throttle attached to an
        unpowered glider that descends from the first step. That is a trim
        reporting success on an airframe that cannot hold altitude -- the §2.7
        pattern, one layer below the autopilot.

        Verification is by spool state (N1), not by thrust. A turbofan at zero
        throttle produces essentially no thrust whether it is running or not --
        measured on the pinned build, ``global5000`` idles at 12 lbf per engine
        at 3000 m and 0 lbf at 6000 m -- so thrust cannot distinguish a running
        engine from a stopped one. N1 goes 0 -> 30% on start and is unambiguous.
        """
        running = self._engine_running_properties()
        if not running:
            raise SimulationError(
                f"{self.model.name!r} defines no engines; it cannot be trimmed "
                f"for powered flight."
            )

        for name in running:
            self.props.set(name, 1.0)
        # Advance one step so the propulsion model evaluates at the new state.
        self.step()

        # A piston engine ignores a bare set-running: ignition and fuel gate
        # it, and the write silently fails to latch (measured on c172p --
        # set-running reads back 0.0 with no diagnostic). The real sequence
        # works headless: mixture rich, magnetos both, starter engaged,
        # ~2 s of cranking, after which the engine catches and set-running
        # latches by itself.
        if (any(self.props.get(n) < 0.5 for n in running)
                and self.props.has("propulsion/magneto_cmd")):
            self._crank_piston_engines(running)

        stopped = []
        for i, name in enumerate(running):
            if self.props.get(name) < 0.5:
                stopped.append(f"engine {i}: set-running did not latch")
                continue
            spool = self._spool_property(i)
            if spool is not None and self.props.get(spool) <= 0.0:
                stopped.append(f"engine {i}: N1 is {self.props.get(spool):.1f}% after start")

        if stopped:
            raise SimulationError(
                f"Engines on {self.model.name!r} did not start: {'; '.join(stopped)}. "
                f"The aircraft would trim as an unpowered glider."
            )
        self._engines_started = True

    def _crank_piston_engines(self, running: tuple,
                              crank_limit_s: float = 5.0) -> None:
        """Mixture rich, magnetos both, starter on, crank until it catches.

        The catch is observed, not assumed: cranking continues until
        engine-rpm clears 500 -- measured on c172p, breaking off the crank
        at 400 rpm leaves an engine that is still motoring on the starter
        and whose set-running write does NOT latch, while by ~530 rpm
        combustion is sustaining and it does. Mixture is swept rich to
        lean across attempts because full rich does not fire at altitude
        (measured: the same c172p that catches at 500 m with mixture 1.0
        never catches at 3600 m until leaned). If every setting fails the
        caller's verification reports the stopped engine -- this method
        never fakes a latch.
        """
        mixtures = []
        for i in range(len(running)):
            suffix = "" if i == 0 else f"[{i}]"
            name = f"fcs/mixture-cmd-norm{suffix}"
            if self.props.has(name):
                mixtures.append(name)
        self.props.set("propulsion/magneto_cmd", 3.0)

        rpm_props = [p for p in ("propulsion/engine/engine-rpm",)
                     if self.props.has(p)]

        def caught() -> bool:
            return bool(rpm_props) and all(self.props.get(p) > 500.0
                                           for p in rpm_props)

        for setting in (1.0, 0.8, 0.65, 0.5, 0.35):
            for name in mixtures:
                self.props.set(name, setting)
            self.props.set("propulsion/starter_cmd", 1.0)
            for _ in range(int(crank_limit_s * self.rate_hz)):
                self.step()
                if caught():
                    break
            if caught():
                # A catch on the starter is not sustained combustion: full
                # rich at 2600 m catches and then dies (measured -- it cost
                # four glider clips). Hold the setting for three seconds and
                # believe the rpm only if it is still there.
                for _ in range(int(3.0 * self.rate_hz)):
                    self.step()
                if caught():
                    break
        for name in running:
            self.props.set(name, 1.0)
        self.step()

    @property
    def engines_running(self) -> bool:
        """True if every engine reports both a latched start and, for turbines, spool."""
        for i, name in enumerate(self._engine_running_properties()):
            if self.props.get(name) < 0.5:
                return False
            spool = self._spool_property(i)
            if spool is not None and self.props.get(spool) <= 0.0:
                return False
        return True

    # -- trim ----------------------------------------------------------

    def trim(self, mode: TrimMode = TrimMode.LONGITUDINAL) -> None:
        """Trim the aircraft, raising :class:`TrimError` if it does not converge."""
        if not self._ic_applied:
            raise SimulationError(
                "set_initial_conditions() must be called before trim(); "
                "trimming from an unset initial state is meaningless."
            )
        if mode is not TrimMode.GROUND and not self.engines_running:
            raise SimulationError(
                f"Refusing to trim {self.model.name!r} for airborne flight with "
                f"engines stopped. Trim would solve for a throttle setting that "
                f"produces no thrust, and the aircraft would descend from the "
                f"first step. Call start_engines() first."
            )
        _trim(self._exec, mode)
        self.props.refresh()
        self._trimmed = True

    # -- integration ---------------------------------------------------

    def hold_mass(self, enabled: bool = True) -> None:
        """Freeze fuel state so gross mass stays constant.

        A fuel-burning aircraft has no equilibrium: mass falls about 1% per
        400 s at cruise thrust and the aircraft climbs at fixed controls.
        Measured on the pinned build, that accounts for the *entire* residual
        drift of a correctly trimmed transport -- 737 at 3000 m / 250 kt climbs
        +89.6 m over 400 s burning fuel, and +2.00 m with mass held.

        This is an experimental control for isolating trim and control-law
        quality from a known time-varying parameter. It is deliberately visible
        in :meth:`provenance` so that a mass-held run can never be reported as
        a realistic one.
        """
        if enabled:
            tanks = self.props.search("contents-lbs")
            if not tanks:
                raise SimulationError(
                    f"{self.model.name!r} exposes no fuel tank contents; mass "
                    f"cannot be held constant."
                )
            self._frozen_tanks = {n: self.props.get(n) for n in tanks}
        else:
            self._frozen_tanks = None

    @property
    def mass_held(self) -> bool:
        return self._frozen_tanks is not None

    def step(self) -> None:
        """Advance exactly one fixed timestep."""
        if self._frozen_tanks is not None:
            self.props.set_many(self._frozen_tanks)
        if not self._exec.run():
            raise SimulationError(
                f"JSBSim run() returned false at t={self.sim_time:.3f}s"
            )
        self._guard_finite()

    def run_for(self, seconds: float) -> int:
        """Advance for ``seconds`` of simulated time. Returns the step count.

        The step count is computed from the fixed rate rather than accumulated
        from wall time, so the same call always produces the same number of
        integration steps.
        """
        steps = int(round(seconds * self.rate_hz))
        for _ in range(steps):
            self.step()
        return steps

    def _guard_finite(self) -> None:
        """Fail fast on NaN. A NaN state propagates silently and reads as a crash."""
        alt = self._exec.get_property_value("position/h-sl-meters")
        vt = self._exec.get_property_value("velocities/vtrue-kts")
        if not (math.isfinite(alt) and math.isfinite(vt)):
            raise SimulationError(
                f"Non-finite state at t={self.sim_time:.3f}s "
                f"(h={alt}, vtrue={vt}). Refusing to continue."
            )

    # -- observation (read-only; §2.1) ---------------------------------

    def state(self) -> AircraftState:
        """An immutable snapshot of the current state."""
        return AircraftState.from_properties(self.props, self._surfaces)

    # -- controls ------------------------------------------------------

    def set_controls(self, **cmds: float) -> None:
        """Write ``fcs/*-cmd-norm`` commands.

        Accepts short names (``elevator``) or full property paths. Provided for
        open-loop tests and for the guidance layer; the closed-loop control laws
        themselves live in JSBSim's XML autopilot at FDM rate (§5 Phase 2), not
        here.
        """
        mapped = {}
        for key, value in cmds.items():
            if "/" in key:
                mapped[key] = value
            elif key == "throttle":
                mapped["fcs/throttle-cmd-norm"] = value
            else:
                mapped[f"fcs/{key}-cmd-norm"] = value
        self.props.set_many(mapped)

    # -- provenance ----------------------------------------------------

    def provenance(self) -> dict:
        """Everything about this FDM instance that belongs in a run manifest (§7.4)."""
        return {
            "jsbsim_version": jsbsim.FGJSBBase().get_version(),
            "rate_hz": self.rate_hz,
            "dt": self.dt,
            "aircraft": self.model.provenance(),
            # An experimental control, not a detail: a mass-held run is not a
            # realistic one and must never be reported as such.
            "mass_held_constant": self.mass_held,
        }

    def __repr__(self) -> str:
        return (
            f"FlightDynamics({self.model.name!r}, {self.rate_hz:g} Hz, "
            f"t={self.sim_time:.2f}s, trimmed={self._trimmed})"
        )
