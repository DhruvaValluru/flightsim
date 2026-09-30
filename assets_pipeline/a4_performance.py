"""A4 climb performance by excess power, at the cfg's reference weight.

aircraft.cfg quotes performance for the "loaded weight" of 18,300 lb, clean.
Rate of climb here is V (Tmax - D) / W with D the trimmed level-flight thrust
at the same speed and Tmax the engine at full throttle; the service ceiling
is the altitude where the best rate of climb falls to 100 ft/min. This is
the steady-climb approximation (no acceleration correction), stated as such.
"""

from __future__ import annotations

from typing import Optional

from core.fdm import FlightDynamics

REFERENCE_GROSS_LB = 18300.0   # cfg "Loaded weight"
STORES_STATION = 3             # pointmass index: 3 = STA2... see a4_sync
SPEEDS_KT = (170, 200, 250, 300, 350, 400, 450, 500)


def loaded_fdm(alt_ft: float, cas_kt: float,
               gross_lb: float = REFERENCE_GROSS_LB) -> FlightDynamics:
    fdm = FlightDynamics("A4")
    fdm.set_initial_conditions({"h-sl-ft": alt_ft, "vc-kts": cas_kt,
                                "gamma-deg": 0.0})
    extra = gross_lb - fdm.props.get("inertia/weight-lbs")
    if extra > 0:
        fdm.props.set(f"inertia/pointmass-weight-lbs[{STORES_STATION}]", extra)
    fdm.start_engines()
    return fdm


def rate_of_climb(alt_ft: float, cas_kt: float,
                  gross_lb: float = REFERENCE_GROSS_LB) -> Optional[float]:
    """Steady rate of climb in ft/min, or None if level flight cannot trim."""
    fdm = loaded_fdm(alt_ft, cas_kt, gross_lb)
    try:
        fdm.trim()
    except Exception:
        return None
    g = fdm.props.get
    drag = g("propulsion/engine[0]/thrust-lbs")
    fdm.props.set("fcs/throttle-cmd-norm[0]", 1.0)
    fdm.run_for(4.0)
    t_max = g("propulsion/engine[0]/thrust-lbs")
    return g("velocities/vt-fps") * (t_max - drag) / g("inertia/weight-lbs") * 60


def best_rate_of_climb(alt_ft: float, gross_lb: float = REFERENCE_GROSS_LB):
    best = (None, -1e9)
    for kt in SPEEDS_KT:
        r = rate_of_climb(alt_ft, kt, gross_lb)
        if r is not None and r > best[1]:
            best = (kt, r)
    return best


def _roc_at(alt_ft: float, gross_lb: float) -> float:
    """Best rate of climb, with 'cannot trim at all' counted as no climb."""
    _, roc = best_rate_of_climb(alt_ft, gross_lb)
    return roc if roc > -1e8 else -1000.0


def service_ceiling_ft(gross_lb: float = REFERENCE_GROSS_LB,
                       tolerance_ft: float = 150.0) -> float:
    """Altitude where the best rate of climb is 100 ft/min (bisection)."""
    lo, hi = 30000.0, 60000.0
    if _roc_at(lo, gross_lb) < 100.0:
        return lo
    if _roc_at(hi, gross_lb) > 100.0:
        return hi
    while hi - lo > tolerance_ft:
        mid = 0.5 * (lo + hi)
        if _roc_at(mid, gross_lb) > 100.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


if __name__ == "__main__":
    for alt in (1000, 10000, 20000, 30000, 40000):
        print(alt, best_rate_of_climb(alt))
    print("service ceiling ft:", round(service_ceiling_ft()))
