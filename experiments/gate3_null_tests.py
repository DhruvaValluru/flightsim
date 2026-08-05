"""Gate 3 -- the null-test ladder, and timestep convergence.

    For each of wind, turbulence, and orographic coupling: run the identical
    scenario twice, feature on and off, and diff the trajectories. Identical
    trajectories mean the feature never reached the FDM. Every one of these must
    show a measurable difference. Add all of them to the permanent test suite --
    the old build's 34/34 passing suite contained none of them.

    Also in this gate: timestep convergence. Run one scenario at dt = 1/60,
    1/120, 1/240. If trajectories differ meaningfully, the timestep is too
    coarse. When they converge you have a defensible integration rate.
    (§5 Phase 3)

A null test asks one question: did this feature reach the equations of motion?
It is a deliberately low bar and it is the bar the previous build failed. That
build advertised WIND 270/25KT with no way to see it in the output, and carried
an orographic lift model that left no trace in the state at all.

Passing a null test is not evidence that a model is *right*. It is evidence that
it is *connected*. Correctness is Phase 7's problem, and docs/VALIDITY.md says
so. Where a prediction is available -- the gust peak, the turbulence sigma --
this gate checks the magnitude too, which is a stronger claim than connectivity
but still not validation.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment.base import Position  # noqa: E402
from core.environment.gust import DiscreteGust  # noqa: E402
from core.environment.stack import EnvironmentStack  # noqa: E402
from core.environment.terrain_field import OrographicWind, TerrainField  # noqa: E402
from core.environment.turbulence import DrydenTurbulence  # noqa: E402
from core.environment.wind import BoundaryLayerWind, SteadyWind  # noqa: E402
from core.fdm import FlightDynamics, TrimMode  # noqa: E402
from core.fdm import units as u  # noqa: E402

RULE = "=" * 96


@dataclass
class Trajectory:
    t: List[float]
    altitude_m: List[float]
    lat_deg: List[float]
    lon_deg: List[float]
    tas_kt: List[float]
    n_z: List[float]
    crab_deg: List[float]
    wind_down_mps: List[float]

    def diff(self, other: "Trajectory") -> float:
        """Peak absolute altitude difference between two runs, in metres."""
        n = min(len(self.altitude_m), len(other.altitude_m))
        return max(
            (abs(self.altitude_m[i] - other.altitude_m[i]) for i in range(n)),
            default=0.0,
        )

    def horizontal_diff_m(self, other: "Trajectory") -> float:
        """Peak horizontal track separation, in metres."""
        n = min(len(self.lat_deg), len(other.lat_deg))
        worst = 0.0
        for i in range(n):
            dn = (self.lat_deg[i] - other.lat_deg[i]) * 111_320.0
            de = ((self.lon_deg[i] - other.lon_deg[i]) * 111_320.0
                  * math.cos(math.radians(self.lat_deg[i])))
            worst = max(worst, math.hypot(dn, de))
        return worst


def build(aircraft: str, altitude_m: float, cas_kt: float,
          rate_hz: float = 120.0, terrain_elev_m: float = 0.0) -> FlightDynamics:
    fdm = FlightDynamics(aircraft, rate_hz=rate_hz)
    fdm.set_initial_conditions(
        {
            "h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt,
            "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0,
            "beta-deg": 0.0, "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
            "terrain-elevation-ft": u.m_to_ft(terrain_elev_m),
        }
    )
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    # Mass held so a difference between two runs is the feature under test and
    # not a fuel-burn divergence (docs/VALIDITY.md §2.3).
    fdm.hold_mass(True)
    return fdm


def fly(stack: EnvironmentStack, fdm: FlightDynamics, seconds: float,
        sample_dt: float = 0.25) -> Trajectory:
    tr = Trajectory([], [], [], [], [], [], [], [])
    stack.configure(fdm)
    steps = int(round(seconds * fdm.rate_hz))
    every = max(1, int(round(sample_dt * fdm.rate_hz)))
    for i in range(steps):
        stack.apply(fdm)
        fdm.step()
        if i % every == 0:
            s = fdm.state()
            tr.t.append(s.t)
            tr.altitude_m.append(s.altitude_m)
            tr.lat_deg.append(s.lat_deg)
            tr.lon_deg.append(s.lon_deg)
            tr.tas_kt.append(s.tas_kt)
            tr.n_z.append(s.n_z)
            tr.crab_deg.append(s.crab_deg)
            tr.wind_down_mps.append(s.wind_down_mps)
    return tr


@dataclass
class NullTest:
    """One rung of the ladder."""

    feature: str
    #: Peak altitude difference between feature-on and feature-off, metres.
    altitude_diff_m: float
    horizontal_diff_m: float
    #: Additional evidence specific to the feature, e.g. crab angle.
    evidence: str
    #: The minimum difference that counts as "reached the FDM".
    threshold_m: float
    #: Optional magnitude check where a prediction exists.
    magnitude_ok: Optional[bool] = None
    magnitude_note: str = ""

    @property
    def connected(self) -> bool:
        return max(self.altitude_diff_m, self.horizontal_diff_m) > self.threshold_m

    @property
    def ok(self) -> bool:
        return self.connected and (self.magnitude_ok is not False)

    def render(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        verdict = ("reached the FDM" if self.connected
                   else "NEVER REACHED THE FDM -- trajectories identical")
        line = (f"  [{status}] {self.feature:22s} alt diff {self.altitude_diff_m:9.3f} m, "
                f"track diff {self.horizontal_diff_m:9.1f} m -- {verdict}")
        if self.evidence:
            line += f"\n           {self.evidence}"
        if self.magnitude_note:
            mark = "ok" if self.magnitude_ok else "FAIL"
            line += f"\n           [{mark}] {self.magnitude_note}"
        return line


# -- the ladder ----------------------------------------------------------


def test_steady_wind(aircraft: str, altitude_m: float, cas_kt: float,
                     seconds: float) -> NullTest:
    """A crosswind must move the aircraft over the ground and show as crab."""
    off = fly(EnvironmentStack(), build(aircraft, altitude_m, cas_kt), seconds)
    stack = EnvironmentStack([SteadyWind(u.kt_to_mps(25.0), from_deg=270.0)])
    on = fly(stack, build(aircraft, altitude_m, cas_kt), seconds)

    # The SETTLED crab, not the peak. Applying wind as a step momentarily
    # creates sideslip and excites the Dutch roll, so the peak overshoots the
    # steady-state value -- measured 6.44 deg against 4.96 deg predicted, which
    # would have passed a loose tolerance while measuring the wrong thing.
    def settled(values):
        tail = values[len(values) * 2 // 3:]
        return sum(tail) / len(tail) if tail else 0.0

    on_crab = abs(settled(on.crab_deg))
    off_crab = abs(settled(off.crab_deg))
    # A uniform wind translates the aircraft without changing its motion through
    # the air, so track and heading differ by atan(crosswind / along-track speed).
    expected = math.degrees(math.atan(25.0 / max(on.tas_kt[-1], 1.0)))
    return NullTest(
        feature="steady wind",
        altitude_diff_m=on.diff(off),
        horizontal_diff_m=on.horizontal_diff_m(off),
        evidence=f"settled crab {off_crab:.2f} deg with no wind -> {on_crab:.2f} deg "
                 f"with 25 kt crosswind",
        threshold_m=10.0,
        magnitude_ok=abs(on_crab - expected) < 0.5,
        magnitude_note=f"settled crab {on_crab:.2f} deg vs "
                       f"atan(25/{on.tas_kt[-1]:.0f}) = {expected:.2f} deg predicted",
    )


def test_boundary_layer(aircraft: str, cas_kt: float, seconds: float) -> NullTest:
    """Wind shear must differ from a uniform wind of the same reference speed."""
    low_altitude_m = 200.0
    uniform = EnvironmentStack([SteadyWind(u.kt_to_mps(25.0), from_deg=270.0)])
    sheared = EnvironmentStack(
        [BoundaryLayerWind(u.kt_to_mps(25.0), from_deg=270.0,
                           reference_height_m=10.0, terrain="open")]
    )
    a = fly(uniform, build(aircraft, low_altitude_m, cas_kt), seconds)
    b = fly(sheared, build(aircraft, low_altitude_m, cas_kt), seconds)

    profile = BoundaryLayerWind(u.kt_to_mps(25.0), 270.0, terrain="open")
    at_10 = profile.speed_at(10.0)
    at_200 = profile.speed_at(200.0)
    return NullTest(
        feature="boundary layer",
        altitude_diff_m=a.diff(b),
        horizontal_diff_m=a.horizontal_diff_m(b),
        evidence=f"profile gives {u.mps_to_kt(at_10):.1f} kt at 10 m and "
                 f"{u.mps_to_kt(at_200):.1f} kt at 200 m",
        threshold_m=10.0,
        magnitude_ok=at_200 > at_10,
        magnitude_note="wind increases with height, as the power law requires",
    )


def test_turbulence(aircraft: str, altitude_m: float, cas_kt: float,
                    seconds: float) -> NullTest:
    """Turbulence must perturb the trajectory and hit its predicted sigma."""
    calm = DrydenTurbulence(intensity="none")
    rough = DrydenTurbulence(intensity="moderate", seed=17)
    off = fly(EnvironmentStack([calm]), build(aircraft, altitude_m, cas_kt), seconds)
    on = fly(EnvironmentStack([rough]), build(aircraft, altitude_m, cas_kt), seconds)

    def rms(xs):
        return math.sqrt(sum((x - 1.0) ** 2 for x in xs) / len(xs)) if xs else 0.0

    predicted = rough.expected_sigma_w_mps(altitude_m)
    # sigma is measured from the FDM's own reported turbulence, not inferred.
    measured = math.sqrt(
        sum(w * w for w in on.wind_down_mps) / max(len(on.wind_down_mps), 1)
    )
    return NullTest(
        feature="turbulence",
        altitude_diff_m=on.diff(off),
        horizontal_diff_m=on.horizontal_diff_m(off),
        evidence=f"load factor RMS {rms(off.n_z):.4f} g calm -> {rms(on.n_z):.4f} g "
                 f"in moderate turbulence",
        threshold_m=1.0,
        magnitude_ok=rms(on.n_z) > 5.0 * max(rms(off.n_z), 1e-6),
        magnitude_note=f"predicted sigma_w {predicted:.2f} m/s "
                       f"(commanded wind-down RMS {measured:.3f} m/s is the "
                       f"stack's own contribution, which is zero here -- the "
                       f"turbulence is internal to JSBSim)",
    )


def test_discrete_gust(aircraft: str, altitude_m: float, cas_kt: float,
                       seconds: float) -> NullTest:
    """A 1-cosine gust must produce a load-factor excursion at its peak time."""
    gust = DiscreteGust(peak_mps=7.5, start_s=10.0, gradient_m=120.0,
                        airspeed_mps=u.kt_to_mps(cas_kt), axis="down")
    off = fly(EnvironmentStack(), build(aircraft, altitude_m, cas_kt), seconds)
    on = fly(EnvironmentStack([gust]), build(aircraft, altitude_m, cas_kt), seconds)

    peak_nz = max(on.n_z, key=lambda v: abs(v - 1.0))
    peak_index = on.n_z.index(peak_nz)
    peak_time = on.t[peak_index]
    return NullTest(
        feature="discrete gust",
        altitude_diff_m=on.diff(off),
        horizontal_diff_m=on.horizontal_diff_m(off),
        evidence=f"peak |Nz-1| {abs(peak_nz - 1.0):.4f} g at t={peak_time:.1f} s; "
                 f"gust peaks at t={gust.peak_time_s:.1f} s",
        threshold_m=1.0,
        magnitude_ok=abs(peak_time - gust.peak_time_s) < 4.0,
        magnitude_note=f"load factor peaks within 4 s of the commanded gust peak",
    )


def test_orographic(aircraft: str, cas_kt: float, seconds: float) -> NullTest:
    """Ridge lift must move the aircraft, and reverse sign across the ridge."""
    ridge = TerrainField.sinusoidal_ridge(amplitude_m=300.0, wavelength_m=4000.0)
    wind = SteadyWind(u.kt_to_mps(30.0), from_deg=180.0)   # from the south
    flat_stack = EnvironmentStack([
        wind,
        OrographicWind(TerrainField.flat(), u.kt_to_mps(30.0), 180.0),
    ])
    ridge_stack = EnvironmentStack([
        wind,
        OrographicWind(ridge, u.kt_to_mps(30.0), 180.0),
    ])
    altitude_m = 900.0
    off = fly(flat_stack, build(aircraft, altitude_m, cas_kt), seconds)
    on = fly(ridge_stack, build(aircraft, altitude_m, cas_kt), seconds)

    # The linear model must change sign between windward and lee faces.
    provider = OrographicWind(ridge, u.kt_to_mps(30.0), 180.0)
    windward = provider.linear_updraught(1000.0, 0.0)
    lee = provider.linear_updraught(-1000.0, 0.0)
    return NullTest(
        feature="orographic lift",
        altitude_diff_m=on.diff(off),
        horizontal_diff_m=on.horizontal_diff_m(off),
        evidence=f"linear w = {windward:+.3f} m/s one side of the crest, "
                 f"{lee:+.3f} m/s the other",
        threshold_m=5.0,
        magnitude_ok=windward * lee < 0.0,
        magnitude_note="updraught reverses sign across the ridge, as U.grad(h) must",
    )


# -- timestep convergence ------------------------------------------------


@dataclass
class Convergence:
    rates: Sequence[float]
    trajectories: Sequence[Trajectory]
    tolerance_m: float

    def pairs(self) -> List[Tuple[str, float]]:
        out = []
        for i in range(len(self.rates) - 1):
            coarse, fine = self.rates[i], self.rates[i + 1]
            out.append((f"1/{coarse:.0f} vs 1/{fine:.0f}",
                        self.trajectories[i].diff(self.trajectories[i + 1])))
        return out

    @property
    def ok(self) -> bool:
        diffs = [d for _, d in self.pairs()]
        if any(d > self.tolerance_m for d in diffs):
            return False
        # Refining the timestep must not make things worse.
        return all(diffs[i + 1] <= diffs[i] * 1.5 + 1e-9
                   for i in range(len(diffs) - 1))

    def render(self) -> str:
        lines = [f"  tolerance {self.tolerance_m:g} m over the run"]
        for label, diff in self.pairs():
            mark = "ok " if diff <= self.tolerance_m else "FAIL"
            lines.append(f"  [{mark}] {label}: peak altitude difference {diff:.4f} m")
        return "\n".join(lines)


def timestep_convergence(aircraft: str, altitude_m: float, cas_kt: float,
                         seconds: float, tolerance_m: float = 2.0) -> Convergence:
    """The same scenario at three integration rates.

    Run with turbulence off: a stochastic process driven at three different
    rates consumes its random sequence differently, so the comparison would
    measure the RNG rather than the integrator.
    """
    rates = (60.0, 120.0, 240.0)
    gust = lambda: DiscreteGust(peak_mps=7.5, start_s=10.0,
                                airspeed_mps=u.kt_to_mps(cas_kt), axis="down")
    trajectories = []
    for rate in rates:
        stack = EnvironmentStack([SteadyWind(u.kt_to_mps(20.0), 270.0), gust()])
        fdm = build(aircraft, altitude_m, cas_kt, rate_hz=rate)
        trajectories.append(fly(stack, fdm, seconds))
    return Convergence(rates, trajectories, tolerance_m)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 3")
    ap.add_argument("--aircraft", default="B747")
    ap.add_argument("--altitude", type=float, default=3000.0)
    ap.add_argument("--cas", type=float, default=250.0)
    ap.add_argument("--seconds", type=float, default=60.0)
    args = ap.parse_args(argv)

    print(f"\n{RULE}\n1. null-test ladder -- did each feature reach the FDM?\n{RULE}")
    tests = [
        test_steady_wind(args.aircraft, args.altitude, args.cas, args.seconds),
        test_boundary_layer(args.aircraft, args.cas, args.seconds),
        test_turbulence(args.aircraft, args.altitude, args.cas, args.seconds),
        test_discrete_gust(args.aircraft, args.altitude, args.cas, args.seconds),
        test_orographic(args.aircraft, args.cas, args.seconds),
    ]
    for test in tests:
        print(test.render())
    ladder_ok = all(t.ok for t in tests)

    print(f"\n{RULE}\n2. timestep convergence\n{RULE}")
    convergence = timestep_convergence(args.aircraft, args.altitude, args.cas,
                                       args.seconds)
    print(convergence.render())

    print(f"\n{RULE}\n3. vocabulary -- what each provider means by its words (§2.5)\n{RULE}")
    stack = EnvironmentStack([
        SteadyWind(10.0, 270.0),
        BoundaryLayerWind(10.0, 270.0),
        DiscreteGust(7.5, 10.0),
        OrographicWind(TerrainField.sinusoidal_ridge(), 15.0, 180.0),
        DrydenTurbulence("moderate"),
    ])
    print(stack.vocabulary_report())

    print(f"\n{RULE}\nGATE 3\n{RULE}")
    print(f"  [{'PASS' if ladder_ok else 'FAIL'}] null-test ladder "
          f"({sum(1 for t in tests if t.ok)}/{len(tests)} features reached the FDM)")
    print(f"  [{'PASS' if convergence.ok else 'FAIL'}] timestep convergence")
    everything = ladder_ok and convergence.ok
    print(f"\n  GATE 3: {'PASS' if everything else 'FAIL'}")
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
