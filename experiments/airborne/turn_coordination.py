"""Package G measurement: turn coordination.

The B747 at 3000 m flies a +90 deg heading step under the autopilot at
230 and 300 kt CAS; over the steady 8 s segment at the 25 deg bank limit
the turn rate is compared with the coordinated-turn condition
psi_dot = g tan(phi) / V and the sideslip beta is read. ``--pre`` flies
the same steps with the beta-to-rudder coordinator switched off (the
yaw damper alone, the pre-Package-G yaw channel). The Dutch-roll check
is the same heading step's overshoot and settling, characterised by
core.control.response, before and after.

    .venv/bin/python -m experiments.airborne.turn_coordination
    .venv/bin/python -m experiments.airborne.turn_coordination --pre
"""

from __future__ import annotations

import argparse
import json
import math

from core.control.autopilot import Autopilot
from core.control.response import characterise
from core.fdm import FlightDynamics, mode_for
from core.fdm import units as u

G = 9.80665


def engaged(cas_kt: float, altitude_m: float = 3000.0, aircraft: str = "B747"):
    fdm = FlightDynamics.with_tecs(aircraft, rate_hz=120.0)
    fdm.set_initial_conditions({
        "h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, "gamma-deg": 0.0,
        "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
        "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0})
    fdm.props.set_many({"atmosphere/wind-north-fps": 0.0,
                        "atmosphere/wind-east-fps": 0.0,
                        "atmosphere/wind-down-fps": 0.0,
                        "atmosphere/turb-type": 0.0})
    fdm.start_engines()
    fdm.trim(mode_for(crosswind=False))
    fdm.hold_mass(True)
    ap = Autopilot(fdm)
    ap.engage()
    return fdm, ap


def damper_only(fdm) -> None:
    """The pre-Package-G yaw channel: the washed-out yaw-rate damper at
    its former gain of 1.5 and no sideslip loop."""
    fdm.props.set_many({"ap/yaw/k-beta": 0.0, "ap/yaw/ki-beta": 0.0,
                        "ap/yaw/k-r": 1.5})


def heading_step(cas_kt: float, pre: bool, step_deg: float = 90.0,
                 settle_s: float = 5.0, seconds: float = 120.0) -> dict:
    fdm, ap = engaged(cas_kt)
    if pre:
        damper_only(fdm)
    for i in range(int(settle_s * fdm.rate_hz)):
        fdm.step()
        if i % 60 == 0:
            ap.update()
    ap.command(heading_deg=step_deg)
    t0 = fdm.sim_time
    rows = []
    for i in range(int(seconds * fdm.rate_hz)):
        fdm.step()
        if i % 60 == 0:
            ap.update()
        if i % 12 == 0:
            p = fdm.props
            rows.append(dict(
                t=fdm.sim_time - t0,
                psi=p.get("attitude/psi-deg"), phi=p.get("attitude/phi-deg"),
                beta=p.get("aero/beta-deg"),
                psidot=math.degrees(p.get("velocities/psidot-rad_sec")),
                vt=u.fps_to_mps(p.get("velocities/vtrue-fps")),
                fy=p.get("forces/fby-aero-lbs"), w=p.get("inertia/weight-lbs"),
                rudder=p.get("fcs/rudder-cmd-norm")))
    # The steady segment at the bank limit: 8 s ending when the bank
    # starts to come off (heading capture begins).
    limit = math.degrees(fdm.props.get("ap/limits/bank-rad"))
    at_limit = [r for r in rows if abs(r["phi"]) > 0.97 * limit]
    end = at_limit[-1]["t"]
    seg = [r for r in rows if end - 8.0 <= r["t"] <= end]
    mean = lambda k: sum(r[k] for r in seg) / len(seg)
    phi = mean("phi")
    coordinated = math.degrees(G * math.tan(math.radians(phi)) / mean("vt"))
    measured = mean("psidot")
    times = [r["t"] for r in rows]
    response = characterise(times, [r["psi"] for r in rows], step_deg,
                            "heading", "deg", band=0.02)
    return {
        "cas_kt": cas_kt, "pre": pre,
        "bank_deg": phi, "tas_mps": mean("vt"),
        "turn_rate_deg_s": measured, "coordinated_deg_s": coordinated,
        "turn_rate_error_pct": 100.0 * (measured - coordinated) / coordinated,
        "beta_deg": mean("beta"), "beta_abs_max_deg": max(abs(r["beta"]) for r in seg),
        "side_force_over_weight": mean("fy") / mean("w"),
        "rudder_cmd": mean("rudder"),
        "heading_overshoot_pct": response.overshoot_pct,
        "heading_settling_s": response.settling_time_s,
        "heading_rise_s": response.rise_time_s,
        "k_beta": fdm.props.get("ap/yaw/k-beta"),
        "ki_beta": fdm.props.get("ap/yaw/ki-beta"),
        "yaw_authority": (ap.yaw_authority.provenance()
                          if getattr(ap, "yaw_authority", None) else None),
    }


def dutch_roll(cas_kt: float, pre: bool, pulse: float = 0.05,
               pulse_s: float = 1.0, seconds: float = 40.0) -> dict:
    """Excite the Dutch roll with a 1 s rudder pulse, wings held level,
    and measure how the sideslip rings down: the log-decrement damping
    ratio over successive |beta| peaks and the time to stay within
    0.05 deg. The coordinator must not degrade this."""
    fdm, ap = engaged(cas_kt)
    if pre:
        damper_only(fdm)
    ap.command(bank_deg=0.0)
    for i in range(int(5.0 * fdm.rate_hz)):
        fdm.step()
        if i % 60 == 0:
            ap.update()
    fdm.props.set("ap/yaw/rudder-bias", pulse)
    t0 = fdm.sim_time
    betas, times = [], []
    for i in range(int(seconds * fdm.rate_hz)):
        if fdm.sim_time - t0 >= pulse_s:
            fdm.props.set("ap/yaw/rudder-bias", 0.0)
        fdm.step()
        if i % 60 == 0:
            ap.update()
        times.append(fdm.sim_time - t0)
        betas.append(fdm.props.get("aero/beta-deg"))
    # Peaks of |beta| after the pulse ends.
    peaks = []
    for k in range(1, len(betas) - 1):
        if times[k] <= pulse_s + 0.5:
            continue
        a, b, c = abs(betas[k - 1]), abs(betas[k]), abs(betas[k + 1])
        if b > a and b >= c and b > 0.01:
            peaks.append((times[k], b))
    # Successive peaks of the same sign are one period apart; the ratio of
    # every other |peak| gives the log decrement per cycle.
    ratios = [peaks[i + 2][1] / peaks[i][1] for i in range(len(peaks) - 2)
              if peaks[i][1] > 0.02]
    zeta = None
    period = None
    if ratios:
        delta = -math.log(sum(ratios) / len(ratios))
        zeta = delta / math.sqrt(4.0 * math.pi ** 2 + delta ** 2)
        period = sum(peaks[i + 2][0] - peaks[i][0]
                     for i in range(len(peaks) - 2)) / (len(peaks) - 2)
    quiet = [t for t, b in zip(times, betas)
             if t > pulse_s and abs(b) > 0.05]
    return {"cas_kt": cas_kt, "pre": pre,
            "beta_peak_deg": max(abs(b) for b in betas),
            "peaks": len(peaks), "damping_ratio": zeta, "period_s": period,
            "settle_005deg_s": (quiet[-1] if quiet else 0.0),
            "beta_end_deg": betas[-1]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", action="store_true")
    parser.add_argument("--aircraft", default="B747")
    args = parser.parse_args()
    out = {f"{cas:.0f}kt": heading_step(cas, args.pre)
           for cas in (230.0, 300.0)}
    out["dutch_roll"] = {f"{cas:.0f}kt": dutch_roll(cas, args.pre)
                         for cas in (230.0, 300.0)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
