"""Package F measurement: what the lee-rotor coupling DELIVERS, by altitude.

Two measurements the Phase 2 report's Package F row is built from:

1. The POE severity-1 "floor" the provider used to claim above the 300 m
   AGL ceiling, measured from the FDM at several MSL altitudes (it is
   not a constant: MIL-F-8785C Fig. 7 is indexed by MSL, and the
   severity-1 curve is zero at ~3000 m).
2. The delivered sigma_w (RMS of atmosphere/turb-down-fps) over a 15 s
   track in the lee of the test ridge, at 150 m AGL (where the W20 route
   governs) and at 3000 m MSL / 700 m AGL (where every planner-produced
   mountain track flies).

    .venv/bin/python -m experiments.airborne.rotor_delivery
"""

from __future__ import annotations

import json
import math

from core.environment.rotor import ROTOR_ACTS_SIGMA_W_MPS, LeeRotorTurbulence
from core.environment.stack import EnvironmentStack
from core.environment.terrain_field import OrographicWind, TerrainField
from core.environment.turbulence import measure_poe_sigma_w_mps
from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u

RIDGE = TerrainField(
    lambda n, e: 400.0 * math.exp(-n * n / (2.0 * 600.0 ** 2)),
    wavelength_m=4000.0, name="gaussian_ridge")
WIND_MPS = 25.0


def rotor(seed=17):
    return LeeRotorTurbulence(OrographicWind(RIDGE, WIND_MPS, 180.0),
                              seed=seed, background_intensity="none")


def delivered_in_lee(msl_m: float, terrain_m: float, seconds: float = 15.0,
                     seed: int = 17, wind_mps: float = WIND_MPS) -> dict:
    """Fly east along the lee (900 m north of the crest) at msl_m over a
    flat physics slab at terrain_m, the rotor attached; report what the
    FDM delivered."""
    fdm = FlightDynamics("B747")
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(msl_m), "vc-kts": 250.0, "gamma-deg": 0.0,
         "phi-deg": 0.0, "psi-true-deg": 90.0, "beta-deg": 0.0,
         "lat-geod-deg": 900.0 / 111_320.0, "long-gc-deg": 0.0,
         "terrain-elevation-ft": u.m_to_ft(terrain_m)})
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    fdm.hold_mass(True)
    provider = LeeRotorTurbulence(OrographicWind(RIDGE, wind_mps, 180.0),
                                  seed=seed, background_intensity="none")
    stack = EnvironmentStack([provider])
    stack.configure(fdm)
    for _ in range(int(seconds * fdm.rate_hz)):
        stack.apply(fdm)
        fdm.step()
    return {"msl_m": msl_m, "agl_m": msl_m - terrain_m, "wind_mps": wind_mps,
            "delivered_sigma_w_mps": provider.delivered_sigma_w_mps(),
            "acts": provider.acts(), "word": provider.word(),
            "min_agl_observed_m": provider.min_agl_observed_m,
            "claimed_sigma_w_mps": provider.expected_sigma_w_mps(
                msl_m - terrain_m, msl_m=msl_m) if msl_m - terrain_m > 300
            else None}


def main() -> None:
    floor = {}
    for msl in (450.0, 1000.0, 1500.0, 2000.0, 3000.0, 3400.0, 5000.0):
        floor[f"{msl:.0f}"] = round(measure_poe_sigma_w_mps(
            msl, agl_m=msl, severity=1.0), 4)
    over_terrain = {}
    for msl, terrain in ((3000.0, 2300.0), (3384.0, 3000.0)):
        over_terrain[f"{msl:.0f}_over_{terrain:.0f}"] = round(
            measure_poe_sigma_w_mps(msl, agl_m=msl - terrain, severity=1.0),
            4)
    print(json.dumps({
        "poe_severity1_floor_sigma_w_mps_by_msl": floor,
        "poe_severity1_floor_over_terrain": over_terrain,
        "threshold_mps": ROTOR_ACTS_SIGMA_W_MPS,
        "lee_150m_agl_wind25": delivered_in_lee(150.0, 0.0),
        "lee_150m_agl_wind35": delivered_in_lee(150.0, 0.0, wind_mps=35.0),
        "lee_3000m_msl_700m_agl": delivered_in_lee(3000.0, 2300.0),
        "lee_3384m_msl_384m_agl": delivered_in_lee(3384.0, 3000.0),
    }, indent=1))


if __name__ == "__main__":
    main()
