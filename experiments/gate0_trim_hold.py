"""Gate 0 -- trim, then hold hands-off.

    Still air, flat terrain, no wind, no turbulence, no autopilot, no plugins.
    Trim, then run 60 s hands-off. Altitude must hold within a few metres and
    airspeed within a knot or two, with no growing oscillation.  (§5 Phase 0)

This gate would have failed in the previous build. Nothing downstream matters
until it passes, so it is the first thing built and the first thing run.

What is asserted, and why it is not simply the literal text
-----------------------------------------------------------
A fuel-burning aircraft has no equilibrium. Mass falls about 1% per 400 s at
cruise thrust, and a lighter aircraft at fixed controls climbs. Measured here,
that accounts for the entire residual drift of a correctly trimmed transport:
the 737 at 3000 m / 250 kt climbs +89.6 m over 400 s burning fuel and +2.00 m
with mass held constant. Asserting on the fuel-burning run would mean choosing
a tolerance loose enough to contain a known mass effect -- and a real trim
defect could then hide inside it.

So the pass/fail assertion is made on a **mass-held** run, which is a true
equilibrium test, and the realistic fuel-burning drift is measured and reported
alongside it rather than hidden.

Window length. §5 says 60 s; §6.5 asks for 3-5 phugoid periods, which at these
speeds is 230-520 s. A 60 s window is shorter than one phugoid period, so a
"growing oscillation" test over it measures the first quarter-cycle rising, not
divergence. The divergence window is therefore sized to three phugoid periods
(floor 60 s), and the literal 60 s numbers are reported too.

Envelope. Stock aero tables run out before the airframe does. Measured high-Mach
trim boundaries at 10 km: global5000 fails above M0.68, 737 above M0.79, B747
reaches M0.835. Test points are chosen inside every candidate's envelope so the
airframes are compared on equal terms, and the boundary is reported as data
rather than showing up as a mystery failure.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fdm import FlightDynamics, TrimError, TrimMode, verify_trim_holds  # noqa: E402
from core.fdm import units as u  # noqa: E402
from core.fdm.trim import TrimDrift  # noqa: E402


@dataclass(frozen=True)
class Gate0Tolerance:
    """Pass/fail thresholds, declared before the first run.

    These apply to the mass-held run. "A few metres" and "a knot or two" are
    read as 5 m and 2 kt of peak excursion from the trimmed state.
    """

    altitude_excursion_m: float = 5.0
    airspeed_excursion_kt: float = 2.0
    #: Symmetric longitudinal trim should introduce no roll at all. The
    #: previous build began banked 7 degrees with no roll command (§1.1).
    roll_excursion_deg: float = 1.0
    #: Second-half peak-to-peak minus first-half, over >= 3 phugoid periods.
    altitude_growth_m: float = 1.0
    #: Residual wind that still counts as "still air".
    still_air_mps: float = 1e-6
    #: Mass must actually be constant when it is supposed to be.
    mass_drift_kg: float = 1e-6


@dataclass(frozen=True)
class Gate0Condition:
    aircraft: str
    altitude_m: float
    cas_kt: float
    #: Literal §5 window, used for the reported realistic run.
    short_duration_s: float = 60.0
    rate_hz: float = 120.0
    #: Phugoid periods the divergence window must cover (§6.5).
    phugoid_periods: float = 3.0

    @property
    def label(self) -> str:
        return f"{self.aircraft} @ {self.altitude_m:.0f} m / {self.cas_kt:.0f} kt CAS"


@dataclass(frozen=True)
class Gate0Result:
    condition: Gate0Condition
    passed: bool
    failures: Sequence[str]
    #: Mass-held run -- what the gate asserts on.
    held: Optional[TrimDrift] = None
    #: Fuel-burning run over the literal 60 s window -- reported, not asserted.
    realistic: Optional[TrimDrift] = None
    trim_error: Optional[str] = None
    alpha_deg: float = math.nan
    throttle: float = math.nan
    mass_kg: float = math.nan
    mach: float = math.nan
    fuel_burn_kg: float = math.nan
    phugoid_period_s: float = math.nan
    held_duration_s: float = math.nan


def _configure(cond: Gate0Condition, tol: Gate0Tolerance) -> FlightDynamics:
    """Build a trimmed FDM in verified still air over flat terrain."""
    fdm = FlightDynamics(cond.aircraft, rate_hz=cond.rate_hz)
    fdm.set_initial_conditions(
        {
            "h-sl-ft": u.m_to_ft(cond.altitude_m),
            "vc-kts": cond.cas_kt,
            "gamma-deg": 0.0,
            "phi-deg": 0.0,
            "psi-true-deg": 0.0,
            "beta-deg": 0.0,
            "lat-geod-deg": 0.0,
            "long-gc-deg": 0.0,
            "terrain-elevation-ft": 0.0,   # flat terrain
            # IC wind is magnitude/direction: ic/vw-north-fps and friends are
            # read-only in JSBSim 1.2.4 despite being listed as settable ICs,
            # so writing them is silently ignored.
            "vw-mag-fps": 0.0,
            "vw-dir-deg": 0.0,
        }
    )
    # Still air is verified, not assumed. The previous build advertised
    # conditions the FDM never received (§1.6); the same mistake in the
    # opposite direction would invalidate this gate silently.
    s = fdm.state()
    total = math.sqrt(s.wind_north_mps ** 2 + s.wind_east_mps ** 2 + s.wind_down_mps ** 2)
    if total > tol.still_air_mps:
        raise AssertionError(
            f"Gate 0 requires still air but the FDM reports {total:.6f} m/s of "
            f"total wind. The gate would be measuring something other than what "
            f"it claims."
        )
    # Powered flight needs running engines, verified by spool state. An
    # unstarted engine trims as a glider and reports success.
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    return fdm


def phugoid_period_s(tas_kt: float) -> float:
    """Classical phugoid period, T = pi*sqrt(2)*V/g.

    Used only to size the divergence window; nothing is asserted against it.
    """
    return math.pi * math.sqrt(2.0) * (tas_kt * u.MPS_PER_KT) / u.G0


def run_condition(cond: Gate0Condition, tol: Gate0Tolerance = Gate0Tolerance()) -> Gate0Result:
    """Trim at ``cond``, then measure hands-off drift twice. Never raises on trim failure."""
    try:
        fdm = _configure(cond, tol)
    except TrimError as exc:
        return Gate0Result(
            condition=cond,
            passed=False,
            failures=[f"trim did not converge: {exc}"],
            trim_error=str(exc),
        )

    trimmed = fdm.state()
    period = phugoid_period_s(trimmed.tas_kt)
    held_duration = max(cond.short_duration_s, cond.phugoid_periods * period)

    # -- assertion run: mass held constant, >= 3 phugoid periods.
    fdm.hold_mass(True)
    held = verify_trim_holds(fdm, duration_s=held_duration)
    mass_drift = abs(fdm.state().weight_kg - trimmed.weight_kg)

    # -- reported run: realistic, fuel burning, literal 60 s window.
    fdm2 = _configure(cond, tol)
    start_mass = fdm2.state().weight_kg
    realistic = verify_trim_holds(fdm2, duration_s=cond.short_duration_s)
    fuel_burn = start_mass - fdm2.state().weight_kg

    failures: List[str] = []
    if held.altitude_excursion_m > tol.altitude_excursion_m:
        failures.append(
            f"altitude excursion {held.altitude_excursion_m:.2f} m "
            f"> {tol.altitude_excursion_m:.2f} m"
        )
    if held.airspeed_excursion_kt > tol.airspeed_excursion_kt:
        failures.append(
            f"airspeed excursion {held.airspeed_excursion_kt:.2f} kt "
            f"> {tol.airspeed_excursion_kt:.2f} kt"
        )
    if held.roll_excursion_deg > tol.roll_excursion_deg:
        failures.append(
            f"roll excursion {held.roll_excursion_deg:.2f} deg "
            f"> {tol.roll_excursion_deg:.2f} deg"
        )
    if held.altitude_growth_m > tol.altitude_growth_m:
        failures.append(
            f"oscillation growing over {held_duration:.0f}s "
            f"({cond.phugoid_periods:.0f} phugoid periods): second-half "
            f"peak-to-peak exceeds first-half by {held.altitude_growth_m:.2f} m "
            f"> {tol.altitude_growth_m:.2f} m"
        )
    if mass_drift > tol.mass_drift_kg:
        failures.append(
            f"mass was meant to be held constant but moved {mass_drift:.4f} kg; "
            f"the assertion run is not the experiment it claims to be"
        )

    return Gate0Result(
        condition=cond,
        passed=not failures,
        failures=failures,
        held=held,
        realistic=realistic,
        alpha_deg=trimmed.alpha_deg,
        throttle=fdm.props.get("fcs/throttle-cmd-norm"),
        mass_kg=trimmed.weight_kg,
        mach=trimmed.mach,
        fuel_burn_kg=fuel_burn,
        phugoid_period_s=period,
        held_duration_s=held_duration,
    )


def report(results: Sequence[Gate0Result]) -> bool:
    """Print a per-condition report. Returns True only if every condition passed."""
    print()
    print("=" * 96)
    print("GATE 0 -- trim, then hold hands-off in still air over flat terrain")
    print("assertion: mass held constant, >= 3 phugoid periods")
    print("reported:  realistic run, fuel burning, 60 s")
    print("=" * 96)
    for r in results:
        print(f"\n[{'PASS' if r.passed else 'FAIL'}] {r.condition.label}")
        if r.trim_error:
            print(f"        trim: {r.trim_error.splitlines()[0]}")
            continue
        print(
            f"        trimmed: alpha {r.alpha_deg:.2f} deg, M {r.mach:.3f}, "
            f"throttle {r.throttle:.3f}, mass {r.mass_kg:,.0f} kg"
        )
        print(
            f"        ASSERT (mass held, {r.held_duration_s:.0f}s "
            f"= {r.condition.phugoid_periods:.0f}x phugoid {r.phugoid_period_s:.0f}s): "
            f"{r.held.summary()}"
        )
        print(
            f"        REPORT (fuel burning, {r.condition.short_duration_s:.0f}s, "
            f"burned {r.fuel_burn_kg:.1f} kg): "
            f"alt drift {r.realistic.altitude_drift_m:+.2f} m, "
            f"IAS drift {r.realistic.airspeed_drift_kt:+.2f} kt"
        )
        for f in r.failures:
            print(f"        -> {f}")

    n_pass = sum(1 for r in results if r.passed)
    ok = n_pass == len(results)
    print()
    print("-" * 96)
    print(f"GATE 0: {n_pass}/{len(results)} conditions passed -- {'PASS' if ok else 'FAIL'}")
    print("-" * 96)
    return ok


DEFAULT_AIRCRAFT = ["global5000", "737", "B747"]
#: Chosen inside every candidate's measured trim envelope so the airframes are
#: compared on equal terms. The high-Mach boundary is reported separately by
#: experiments/envelope_probe.py rather than appearing here as a failure.
DEFAULT_POINTS = [(3000.0, 250.0), (6000.0, 280.0), (10000.0, 240.0)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 0: trim and hands-off hold")
    ap.add_argument("--aircraft", nargs="*", default=DEFAULT_AIRCRAFT)
    ap.add_argument("--duration", type=float, default=60.0,
                    help="literal reported window, seconds")
    ap.add_argument("--periods", type=float, default=3.0,
                    help="phugoid periods the assertion window must cover")
    ap.add_argument("--rate", type=float, default=120.0)
    args = ap.parse_args(argv)

    conditions = [
        Gate0Condition(ac, alt, cas, short_duration_s=args.duration,
                       rate_hz=args.rate, phugoid_periods=args.periods)
        for ac in args.aircraft
        for alt, cas in DEFAULT_POINTS
    ]
    results = [run_condition(c) for c in conditions]
    return 0 if report(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
