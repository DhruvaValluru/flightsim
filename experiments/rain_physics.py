"""Rain physics -- what a stated rain rate does to the c172p (core/environment/rain.py).

Three tables, every number measured on JSBSim 1.2.4 here or computed by
the provider's own functions:

1. the water: liquid water content and mass-weighted fall speed per rate,
   with the wetted-wing factors and the drops' drag at 100 kt;
2. flight: 20 s from the same trimmed start at 1500 m / 100 kt, with and
   without the rain block, per rate -- the altitude and airspeed it costs;
3. the runway: a full-brake stop from 55 kt, dry / wet / standing water.

A null test in the Gate 3 sense (did the rain reach the equations of
motion?) and a magnitude check against the closed forms; not a
validation of any airframe's rain response (docs/VALIDITY.md).

    .venv/bin/python experiments/rain_physics.py
"""

from __future__ import annotations

import contextlib
import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment import rain as rn                              # noqa: E402
from core.environment.stack import EnvironmentStack                  # noqa: E402
from core.fdm.fdm import FlightDynamics                              # noqa: E402
from core.nl.compiler import compile_prompt                          # noqa: E402
from core.scenario.runner import run_spec                            # noqa: E402

RATES = (10.0, 50.0, 100.0, 300.0, 1000.0)
KT = 0.514444


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def water_table() -> None:
    print("1. the water (c172p: A_front 3.8 m^2, S 16.2 m^2; level at 100 kt)")
    print(f"   {'mm/h':>6} {'LWC g/m3':>9} {'v_m m/s':>8} {'lift f':>7} {'drag f':>7} "
          f"{'drops N':>8}")
    for rate in RATES:
        w = rn.water(rate)
        f = rn.roughness_factors(w["lwc_g_m3"], 0.15, 0.30)
        force = rn.momentum_force_body(w["lwc_g_m3"], w["fall_speed_mps"], (100 * KT, 0.0, 0.0),
                                       0.0, 0.0, 3.8, 16.2)
        print(f"   {rate:6.0f} {w['lwc_g_m3']:9.3f} {w['fall_speed_mps']:8.2f} {f['lift']:7.4f} "
              f"{f['drag']:7.4f} {-force[0]:8.1f}")


def flight_table(seconds: float = 20.0) -> None:
    print(f"\n2. flight: {seconds:g} s from the same start at 1500 m / 100 kt")
    print(f"   {'mm/h':>6} {'d alt m':>8} {'d TAS kt':>9}")
    for rate in RATES:
        ends = []
        for aero in (False, True):
            spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {seconds:g} seconds")
            spec.set("hold_state", False, frm="experiment")
            spec.set("precipitation_rate_mmh", rate, frm="experiment")
            if aero:
                spec.set("rain.aerodynamics", True, frm="experiment")
            run = quiet(run_spec, spec)
            ends.append((run.telemetry.series("altitude_m")[-1],
                         run.telemetry.series("tas_kt")[-1]))
        print(f"   {rate:6.0f} {ends[1][0] - ends[0][0]:8.2f} {ends[1][1] - ends[0][1]:9.2f}")


def stop(condition: str, tire_psi: float = 29.0, from_kt: float = 55.0):
    fdm = quiet(FlightDynamics, "c172p")
    fdm.set_initial_conditions({"h-agl-ft": 0.0, "theta-deg": 0.0, "psi-true-deg": 0.0,
                                "vg-kts": from_kt})
    effective = {"aerodynamics": rn.Stated(False), "runway_condition": rn.Stated(condition),
                 "lift_loss_at_ref": rn.Stated(0.15, "default"),
                 "drag_rise_at_ref": rn.Stated(0.30, "default"),
                 "tire_pressure_psi": rn.Stated(tire_psi)}
    provider = rn.RainProvider("c172p", None, effective, rate_hz=fdm.rate_hz)
    stack = EnvironmentStack([provider])
    stack.prepare(fdm)
    fdm.props.set_many({"fcs/throttle-cmd-norm": 0.0, "fcs/left-brake-cmd-norm": 1.0,
                        "fcs/right-brake-cmd-norm": 1.0})
    steps = 0
    while fdm.props.get("velocities/vg-fps") > 1.0 and steps < 120 * int(fdm.rate_hz):
        stack.apply(fdm)
        fdm.step()
        steps += 1
    return fdm.props.get("position/distance-from-start-mag-mt"), steps / fdm.rate_hz, provider


def runway_table() -> None:
    print("\n3. the runway: full brakes from 55 kt (c172p, 29 psi: V_p = "
          f"{rn.hydroplaning_speed_kt(29.0):.1f} kt)")
    print(f"   {'condition':>15} {'distance m':>11} {'time s':>7} {'min friction':>13} "
          f"{'hydroplaning s':>15}")
    for condition in rn.RUNWAY_WORDS:
        distance, seconds, provider = stop(condition)
        print(f"   {condition:>15} {distance:11.1f} {seconds:7.2f} "
              f"{provider.peaks['min_friction_factor']:13.3f} "
              f"{provider.peaks['steps_hydroplaning'] / provider.rate_hz:15.2f}")


if __name__ == "__main__":
    water_table()
    flight_table()
    runway_table()
