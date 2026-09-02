"""Airframe performance, MEASURED from the flight model at a state.

Package D. Nothing in the repository knew how much aircraft the controller
was flying: the TECS throttle path applied a fixed gain to an energy-rate
error normalised by g*V -- physically a required thrust-to-weight
increment -- with the airframe's actual thrust-to-weight nowhere in it.
Measured (analysis/flight-dynamics-research-ledger.md 1.2): the same
tecs.xml drove the B747 to 17-54% of its excess power and the c172p to
98% throttle; a 300 m step took the 747 75 s.

The fix is the object this module provides, built the way the
repository already builds its lift curve (core.scenario.envelope): by
probing the FDM rather than by assuming a number. At the trimmed state,
on a throwaway instance:

    T_trim   thrust at trim          -- equals drag in level unaccelerated flight
    T_max    thrust at full throttle, engines spooled
    T_idle   thrust at idle

    Edot_max = (T_max  - T_trim) * V / W      specific excess power, m/s
    Edot_min = (T_idle - T_trim) * V / W      specific deficit, m/s (negative)
    gamma_max = asin(Edot_max / V)            steady climb angle at this speed
    thr_per_ste = dthr / ((T(thr+d) - T(thr-d)) / W)   throttle per unit (dT/W),
                                                        local secant about trim

``thr_per_ste`` is the normalisation the throttle loop needs: its error
is already dT/W, so multiplying by this gives the throttle increment
that produces exactly that thrust increment. ArduPilot's TECS does the
same through K_thr2STE = (STEdot_max - STEdot_min)/(THRmax - THRmin);
Lambregts scales by thrust-to-weight. With it, the same loop gains give
the same bandwidth on every airframe.

Everything here is measured, cached per (airframe, state), and recorded
in provenance. A constant would be a §2.7 failure: right for one
airframe, silently wrong for the next.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Tuple

from .fdm import units as u
from .fdm.errors import FDMError

#: Half-width of the throttle secant used for the local thrust slope.
LOCAL_THROTTLE_DELTA = 0.15
#: Seconds to let engines spool after a throttle step before reading thrust.
#: Turbofans take seconds (JSBSim models spool dynamics); pistons are
#: effectively instant. Measured: B747 N1 settles within 4 s.
SPOOL_SECONDS = 5.0


class PerformanceError(FDMError):
    """Performance could not be measured at this state."""

    constraint = "performance.measure"


@dataclass(frozen=True)
class Performance:
    aircraft: str
    altitude_m: float
    cas_kt: float
    tas_mps: float
    weight_n: float
    thrust_trim_n: float
    thrust_max_n: float
    thrust_idle_n: float
    thrust_up_n: float          #: at throttle_trim + LOCAL_THROTTLE_DELTA (clipped)
    thrust_down_n: float        #: at throttle_trim - LOCAL_THROTTLE_DELTA (clipped)
    throttle_trim: float
    edot_max_mps: float
    edot_min_mps: float
    gamma_max_deg: float
    thr_per_ste: float

    def as_properties(self) -> Dict[str, float]:
        """The controller-facing numbers, in the FDM's units."""
        return {
            "ap/tecs/thr-per-ste": self.thr_per_ste,
            "ap/tecs/stedot-max-fps": u.mps_to_fps(self.edot_max_mps),
            "ap/tecs/stedot-min-fps": u.mps_to_fps(self.edot_min_mps),
        }

    def provenance(self) -> Dict[str, float]:
        return asdict(self)


_CACHE: Dict[Tuple[str, int, int], Performance] = {}


def _engine_thrust_props(fdm) -> list:
    names = []
    i = 0
    while True:
        name = ("propulsion/engine/thrust-lbs" if i == 0
                else f"propulsion/engine[{i}]/thrust-lbs")
        if not fdm.props.has(name):
            break
        names.append(name)
        i += 1
    return names


def _throttle_props(fdm) -> list:
    names = []
    i = 0
    while True:
        name = ("fcs/throttle-cmd-norm" if i == 0
                else f"fcs/throttle-cmd-norm[{i}]")
        if not fdm.props.has(name):
            break
        names.append(name)
        i += 1
    return names


def measure_performance(aircraft: str, altitude_m: float, cas_kt: float,
                        use_cache: bool = True) -> Performance:
    """Probe an airframe's thrust range at a trimmed state.

    A throwaway instance of the STOCK airframe (the derived TECS airframe
    would fight the throttle probe) is trimmed at the state, then held at
    full throttle and at idle for :data:`SPOOL_SECONDS` each, thrust read
    from the propulsion model. Cached per (airframe, altitude, CAS) at
    10 m / 1 kt resolution.
    """
    key = (aircraft, int(round(altitude_m / 10.0)), int(round(cas_kt)))
    if use_cache and key in _CACHE:
        return _CACHE[key]

    from .fdm.fdm import FlightDynamics
    from .fdm.trim import TrimMode

    fdm = FlightDynamics(aircraft)
    fdm.set_initial_conditions({
        "h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt,
        "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0,
        "beta-deg": 0.0, "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
        "terrain-elevation-ft": 0.0,
    })
    fdm.props.set_many({"atmosphere/wind-north-fps": 0.0,
                        "atmosphere/wind-east-fps": 0.0,
                        "atmosphere/turb-type": 0.0})
    fdm.start_engines()
    try:
        fdm.trim(TrimMode.LONGITUDINAL)
    except FDMError as exc:
        raise PerformanceError(
            f"{aircraft!r}: cannot measure performance at {altitude_m:.0f} m "
            f"/ {cas_kt:.0f} kt CAS -- the probe could not trim ({exc})"
        ) from exc
    fdm.hold_mass(True)
    p = fdm.props
    thrust_props = _engine_thrust_props(fdm)
    throttle_props = _throttle_props(fdm)
    if not thrust_props or not throttle_props:
        raise PerformanceError(
            f"{aircraft!r} exposes no engine thrust or throttle properties")

    def total_thrust_n() -> float:
        return u.lbf_to_n(sum(p.get(n) for n in thrust_props))

    weight_n = u.lbf_to_n(p.get("inertia/weight-lbs"))
    tas_mps = u.fps_to_mps(p.get("velocities/vtrue-fps"))
    throttle_trim = p.get("fcs/throttle-cmd-norm")
    thrust_trim_n = total_thrust_n()

    def held(throttle: float) -> float:
        for n in throttle_props:
            p.set(n, throttle)
        for _ in range(int(SPOOL_SECONDS * fdm.rate_hz)):
            fdm.step()
        return total_thrust_n()

    # The loop gain needs the LOCAL thrust-per-throttle slope around trim,
    # not the full-range average: measured, JSBSim's turbofans deliver most
    # of their thrust in the top of the throttle range, so the full-range
    # secant under-commanded the B747 by ~2x. A central secant of
    # +/- LOCAL_THROTTLE_DELTA about the trimmed throttle, clipped to
    # [0, 1], each held for the spool time.
    up = min(1.0, throttle_trim + LOCAL_THROTTLE_DELTA)
    down = max(0.0, throttle_trim - LOCAL_THROTTLE_DELTA)
    thrust_up_n = held(up)
    thrust_down_n = held(down)
    thrust_max_n = held(1.0)
    thrust_idle_n = held(0.0)
    if thrust_max_n <= thrust_trim_n or thrust_up_n <= thrust_down_n:
        raise PerformanceError(
            f"{aircraft!r}: full throttle produced no more thrust than trim "
            f"({thrust_max_n:.0f} N vs {thrust_trim_n:.0f} N) at "
            f"{altitude_m:.0f} m / {cas_kt:.0f} kt -- no excess power to "
            f"measure")
    edot_max = (thrust_max_n - thrust_trim_n) * tas_mps / weight_n
    edot_min = (thrust_idle_n - thrust_trim_n) * tas_mps / weight_n
    gamma_max = math.degrees(math.asin(max(-1.0, min(1.0, edot_max / tas_mps))))
    thr_per_ste = (up - down) / ((thrust_up_n - thrust_down_n) / weight_n)
    perf = Performance(
        aircraft=aircraft, altitude_m=float(altitude_m), cas_kt=float(cas_kt),
        tas_mps=tas_mps, weight_n=weight_n, thrust_trim_n=thrust_trim_n,
        thrust_max_n=thrust_max_n, thrust_idle_n=thrust_idle_n,
        thrust_up_n=thrust_up_n, thrust_down_n=thrust_down_n,
        throttle_trim=throttle_trim, edot_max_mps=edot_max,
        edot_min_mps=edot_min, gamma_max_deg=gamma_max,
        thr_per_ste=thr_per_ste)
    _CACHE[key] = perf
    return perf
