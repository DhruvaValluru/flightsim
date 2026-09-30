"""Fit the two A4 performance constants to the cfg's published figures.

Targets (aircraft.cfg text, loaded weight 18,300 lb, clean of everything
but the stores that weight implies): rate of climb 8,440 ft/min at sea level
and service ceiling 42,250 ft. Unknowns: STORES_DRAG_FT2_PER_LB (drag of the
2,263 lb of pylon load) and OSWALD_E (induced drag). The published maximum
speed (585 kn, clean) is NOT fitted; it is a check.

    python -m assets_pipeline.a4_calibrate
"""

from __future__ import annotations

from . import a4_performance as perf
from . import a4_sync

TARGET_ROC_FPM = 8440.0
TARGET_CEILING_FT = 42250.0
ROC_ALT_FT = 500.0   # sea level would put the aircraft on the ground


def measure():
    a4_sync.main([])
    roc = perf.best_rate_of_climb(ROC_ALT_FT)[1]
    ceiling = perf.service_ceiling_ft()
    return roc, ceiling


def main() -> None:
    ks, e = a4_sync.STORES_DRAG_FT2_PER_LB, a4_sync.OSWALD_E
    for round_ in range(8):
        a4_sync.STORES_DRAG_FT2_PER_LB, a4_sync.OSWALD_E = ks, e
        roc, ceiling = measure()
        print(f"round {round_}: ks={ks:.6f} e={e:.4f} -> roc {roc:.0f} "
              f"ceiling {ceiling:.0f}", flush=True)
        if abs(roc - TARGET_ROC_FPM) < 60 and \
                abs(ceiling - TARGET_CEILING_FT) < 250:
            break
        # roc falls with ks; ceiling rises with e.
        ks *= 1.0 + 1.0 * (roc - TARGET_ROC_FPM) / TARGET_ROC_FPM
        e *= 1.0 - 2.0 * (ceiling - TARGET_CEILING_FT) / TARGET_CEILING_FT
        e = min(max(e, 0.5), 0.92)   # beyond 0.92 is not credible for this wing
    print(f"STORES_DRAG_FT2_PER_LB = {ks:.6f}\nOSWALD_E = {e:.4f}")


if __name__ == "__main__":
    main()
