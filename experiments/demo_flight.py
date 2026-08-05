"""Two runs that demonstrate what Phase 0 actually delivers.

Both are chosen to correspond to a documented failure of the previous build, so
that the output either shows the failure fixed or shows it is still there.

Run A -- elevator doublet
    Trim, fly hands-off, apply a brief symmetric elevator doublet, then release
    and fly hands-off again. If JSBSim is integrating real aerodynamics, two
    distinct modes appear without anything asking for them: a fast, heavily
    damped short period in pitch rate and angle of attack, and a slow phugoid in
    which altitude and airspeed exchange energy 180 degrees out of phase.

    The previous build applied "roll inertia, adverse yaw, pitch overshoot,
    energy bleed, stall buffet, g-onset limiting, spiral drift, wing rock" as
    post-hoc filters on the trajectory (§1.5). Every one of those is emergent
    from the aero coefficients and inertia tensor. This run is the evidence that
    they emerge here rather than being painted on -- nothing in this codebase
    knows what a phugoid is.

    Load factor is read from the accelerometer throughout. In the previous build
    it was finite-differenced and swung 0.5-1.5 g in air the HUD called dead
    calm, while the altitude trace stayed perfectly smooth -- arithmetically
    impossible (§1.3).

Run B -- crosswind step
    Trim in still air, then apply a 25 kt crosswind mid-run. Track separates
    from heading and the aircraft crabs.

    The previous build advertised WIND 270/25KT and never displayed track, so
    the wind was unverifiable from the output; an orographic lift model existed
    in the codebase and left no trace in the state (§1.6). Here the wind is a
    step change with a before and an after in the same trace, so its presence is
    a measurement rather than a claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fdm import FlightDynamics, TrimMode  # noqa: E402
from core.fdm import units as u  # noqa: E402
from core.telemetry.recorder import Recorder  # noqa: E402

LEVEL = {
    "gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
    "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
    "vw-mag-fps": 0.0, "vw-dir-deg": 0.0,
}

SURFACES = {
    "elevator_deg": lambda f: f.props.get("fcs/elevator-pos-rad") * 57.29577951,
    "aileron_deg": lambda f: f.props.get("fcs/left-aileron-pos-rad") * 57.29577951,
    "rudder_deg": lambda f: f.props.get("fcs/rudder-pos-rad") * 57.29577951,
    "elevator_cmd": lambda f: f.props.get("fcs/elevator-cmd-norm"),
    "throttle_cmd": lambda f: f.props.get("fcs/throttle-cmd-norm"),
}


def trimmed(aircraft: str, altitude_m: float, cas_kt: float) -> FlightDynamics:
    fdm = FlightDynamics(aircraft)
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL}
    )
    fdm.props.set_many(
        {"atmosphere/wind-north-fps": 0.0, "atmosphere/wind-east-fps": 0.0,
         "atmosphere/wind-down-fps": 0.0, "atmosphere/turb-type": 0.0}
    )
    fdm.start_engines()
    fdm.trim(TrimMode.LONGITUDINAL)
    # Mass held so the traces show aerodynamics rather than fuel burn, which is
    # otherwise the dominant slow trend (see docs/VALIDITY.md §2.3).
    fdm.hold_mass(True)
    return fdm


def run_doublet(
    aircraft: str = "B747",
    altitude_m: float = 6000.0,
    cas_kt: float = 280.0,
    settle_s: float = 20.0,
    pulse_s: float = 3.0,
    amplitude: float = 0.06,
    free_s: float = 260.0,
) -> Recorder:
    """Trim, settle, elevator doublet, then release and fly hands-off."""
    fdm = trimmed(aircraft, altitude_m, cas_kt)
    rec = Recorder(fdm, interval_s=0.1, extra=SURFACES)
    rec.sample(force=True)

    rec.mark("trimmed, hands-off")
    rec.run_for(settle_s)

    trim_elevator = fdm.props.get("fcs/elevator-cmd-norm")
    rec.mark("elevator doublet")
    fdm.set_controls(elevator=trim_elevator + amplitude)
    rec.run_for(pulse_s)
    fdm.set_controls(elevator=trim_elevator - amplitude)
    rec.run_for(pulse_s)

    # Back to the trimmed control position and left alone. Everything after
    # this point is the airframe, not the pilot.
    fdm.set_controls(elevator=trim_elevator)
    rec.mark("released, hands-off")
    rec.run_for(free_s)
    return rec


def run_crosswind(
    aircraft: str = "B747",
    altitude_m: float = 3000.0,
    cas_kt: float = 250.0,
    still_s: float = 20.0,
    wind_kt: float = 25.0,
    windy_s: float = 60.0,
) -> Recorder:
    """Trim in still air, then step in a pure crosswind."""
    fdm = trimmed(aircraft, altitude_m, cas_kt)
    rec = Recorder(fdm, interval_s=0.1, extra=SURFACES)
    rec.sample(force=True)

    rec.mark("still air")
    rec.run_for(still_s)

    # Heading is north, so an easterly wind vector is a pure crosswind.
    rec.mark(f"{wind_kt:.0f} kt crosswind applied")
    fdm.props.set("atmosphere/wind-east-fps", u.kt_to_fps(wind_kt))
    rec.run_for(windy_s)

    rec.mark("wind removed")
    fdm.props.set("atmosphere/wind-east-fps", 0.0)
    rec.run_for(still_s)
    return rec


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Run the Phase 0 demonstration flights")
    ap.add_argument("--aircraft", default="B747")
    ap.add_argument("--out", default="runs/demo")
    args = ap.parse_args(argv)

    out = Path(args.out)
    doublet = run_doublet(args.aircraft)
    crosswind = run_crosswind(args.aircraft)
    doublet.write_json(out / "doublet.json")
    crosswind.write_json(out / "crosswind.json")

    for name, rec in (("doublet", doublet), ("crosswind", crosswind)):
        print(f"\n=== {name}: {len(rec)} samples over {rec.series('t')[-1]:.0f} s ===")
        for ch in ("altitude_m", "cas_kt", "n_z", "alpha_deg", "crab_deg", "pitch_rate_dps"):
            lo, hi = rec.span(ch)
            print(f"  {ch:16s} {lo:9.3f} .. {hi:9.3f}   (range {hi - lo:.3f})")
        print(f"  events: {[e['label'] for e in rec.events]}")
    print(f"\nwrote {out}/doublet.json and {out}/crosswind.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
