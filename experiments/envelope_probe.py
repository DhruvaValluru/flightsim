"""Measure where each airframe can actually be trimmed.

Stock JSBSim aero tables run out before the real airframe would, and a trim
failure at the edge is correct behaviour rather than a bug. Recording the
boundary turns "the trim mysteriously failed" into a known property of the
model, and it is what lets Gate 0 choose test points that are inside every
candidate's envelope so the airframes are compared on equal terms.

This is measurement, not validation: the boundary reported here is a property
of the model's tables, and says nothing about the real aircraft. See
docs/VALIDITY.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fdm import FDMError, FlightDynamics, TrimMode  # noqa: E402
from core.fdm import units as u  # noqa: E402

LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
    "vw-mag-fps": 0.0, "vw-dir-deg": 0.0,
}


def try_trim(aircraft: str, altitude_m: float, cas_kt: float) -> Tuple[bool, float, str]:
    """Attempt a level trim. Returns (ok, mach, note)."""
    try:
        fdm = FlightDynamics(aircraft)
        fdm.set_initial_conditions(
            {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL}
        )
        mach = fdm.state().mach
        fdm.start_engines()
        fdm.trim(TrimMode.LONGITUDINAL)
        return True, mach, ""
    except FDMError as exc:
        return False, float("nan"), type(exc).__name__


def probe(
    aircraft: Sequence[str],
    altitudes_m: Sequence[float],
    speeds_kt: Sequence[float],
) -> None:
    for name in aircraft:
        print(f"\n=== {name} ===")
        header = "  alt_m  " + "".join(f"{c:>10.0f}" for c in speeds_kt)
        print(header + "   (kt CAS)")
        for alt in altitudes_m:
            cells = []
            for cas in speeds_kt:
                ok, mach, _ = try_trim(name, alt, cas)
                cells.append(f"{'M' + format(mach, '.3f'):>10}" if ok else f"{'--':>10}")
            print(f"  {alt:6.0f}  " + "".join(cells))
        # Report the boundary explicitly rather than leaving it to be read off.
        for alt in altitudes_m:
            trimmable = [c for c in speeds_kt if try_trim(name, alt, c)[0]]
            if trimmable:
                print(
                    f"    {alt:6.0f} m: trims {min(trimmable):.0f}-{max(trimmable):.0f} kt CAS"
                )
            else:
                print(f"    {alt:6.0f} m: no trimmable point in the tested range")


DEFAULT_AIRCRAFT = ["global5000", "737", "B747"]
DEFAULT_ALTITUDES = [3000.0, 6000.0, 10000.0]
DEFAULT_SPEEDS = [200.0, 220.0, 240.0, 260.0, 280.0, 300.0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Measure the trimmable envelope")
    ap.add_argument("--aircraft", nargs="*", default=DEFAULT_AIRCRAFT)
    ap.add_argument("--altitudes", nargs="*", type=float, default=DEFAULT_ALTITUDES)
    ap.add_argument("--speeds", nargs="*", type=float, default=DEFAULT_SPEEDS)
    args = ap.parse_args(argv)
    print("Trimmable envelope (level, still air, flat terrain).")
    print("'--' means trim did not converge: the model's tables end there.")
    probe(args.aircraft, args.altitudes, args.speeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
