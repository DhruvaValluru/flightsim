"""Reproduce docs/accuracy/FLIGHT_MODEL_CHECK.md: the flown models' stall
speed (lift-curve sweep) and top level speed at sea level (trim at rising
speeds until the throttle runs out), for comparison with published data.

    python scripts/flight_model_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fdm.fdm import FlightDynamics, TrimMode  # noqa: E402
from core.scenario.envelope import measure_lift_curve, reference_speeds  # noqa: E402


def top_level_speed(aircraft: str, speeds, clean: bool = False) -> float:
    """Highest speed that trims level on the available throttle at 1,500 ft
    (above core.fdm.gear.GEAR_UP_AGL_FT, so retractable gear is up -- at
    100 ft the gear stays down, which is what made the first version of
    this check read the A-4 30 % slow). ``clean`` empties the A-4's store
    stations (its stores drag area follows their weight)."""
    best = None
    for v in speeds:
        f = FlightDynamics(aircraft)
        ex = f._exec
        try:
            if clean:
                for i in range(1, 6):
                    ex[f"inertia/pointmass-weight-lbs[{i}]"] = 0.0
            f.set_initial_conditions({"h-sl-ft": 1500.0, "vt-kts": float(v), "gamma-deg": 0.0,
                                      "psi-true-deg": 0.0, "lat-geod-deg": 0.0,
                                      "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0})
            f.start_engines()
            f.trim(TrimMode.LONGITUDINAL)
            best = v
        except Exception:            # noqa: BLE001 -- no trim: past the top speed
            break
    return best


def main() -> None:
    c = measure_lift_curve("c172p", altitude_m=1000.0)
    print("c172p  Vs (2400 lb, SL):", round(reference_speeds("c172p", 1088.6, 0.0, c).vs_kt, 1),
          "kt  CLmax", round(c.cl_max, 3))
    print("c172p  top level speed (1500 ft):", top_level_speed("c172p", range(100, 160, 5)), "kt")
    a = measure_lift_curve("A4", altitude_m=1000.0)
    print("A4     Vs (8295 kg, SL):", round(reference_speeds("A4", 8295.0, 0.0, a).vs_kt, 1),
          "kt  CLmax", round(a.cl_max, 3))
    print("A4     top level speed (1500 ft, clean):", top_level_speed("A4", range(500, 650, 5), True), "kt")
    print("A4     top level speed (1500 ft, default stores):", top_level_speed("A4", range(400, 650, 5)), "kt")


if __name__ == "__main__":
    main()
