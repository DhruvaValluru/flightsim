"""Package D measurement: altitude-step response per airframe, pre/post.

    .venv/bin/python experiments/airborne/tecs_step.py [--step 300] [--pre]

--pre reverts the normalisation for the run (thr-per-ste forced to 1.0 with
the old kt-p/kt-i) so the before/after table in docs/AIRBORNE_PHASE2_REPORT.md
reproduces from one script. Reports time to 90%, peak climb rate, throttle
peak, overshoot, CAS excursion and the fraction of excess thrust used.
"""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.control.autopilot import Autopilot
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.scenario.runner import configure_from_spec

CASES = {"B747": ("fly the 747 at 3000 m and 250 kt for 10 seconds", 3000.0),
         "c172p": ("fly the c172p at 600 m and 85 kt for 10 seconds", 600.0)}


def step_response(aircraft, step_m, pre=False, seconds=150):
    prompt, alt = CASES[aircraft]
    spec = compile_prompt(prompt)
    fdm = configure_from_spec(spec); fdm.hold_mass(True); p = fdm.props
    engines = [n for n in range(8) if p.has(f"propulsion/engine[{n}]/thrust-lbs")]
    thrust = lambda: sum(p.get(f"propulsion/engine[{n}]/thrust-lbs") for n in engines)
    ap = Autopilot(fdm); ap.engage()
    if pre:   # the pre-package controller: fixed gains, no normalisation, 40 fps demand cap
        p.set_many({"ap/tecs/thr-per-ste": 1.0, "ap/tecs/kt-p": 1.2, "ap/tecs/kt-i": 0.30,
                    "ap/tecs/hdot-max-fps": 40.0})
    perf = ap.performance
    t0, w = thrust(), p.get("inertia/weight-lbs")
    for _ in range(600): fdm.step()
    ap.command(altitude_m=alt + step_m)
    rows = []
    for i in range(int(seconds * 120)):
        fdm.step()
        if i % 60 == 0: ap.update()
        if i % 12 == 0:
            rows.append((fdm.sim_time, u.ft_to_m(p.get("position/h-sl-ft")),
                         u.fps_to_mps(p.get("velocities/h-dot-fps")), p.get("fcs/throttle-cmd-norm"),
                         p.get("velocities/vc-kts"), thrust()))
    t90 = next((r[0] for r in rows if r[1] >= alt + 0.9 * step_m), float("nan"))
    tmax = u.n_to_lbf(perf.thrust_max_n) if hasattr(u, "n_to_lbf") else perf.thrust_max_n / 4.4482216
    return dict(aircraft=aircraft, step_m=step_m, pre=pre,
                t_to_90pct_s=round(t90 - 5.0, 1), peak_hdot_mps=round(max(r[2] for r in rows), 2),
                throttle_trim=round(p.get("ap/trim/throttle"), 3), throttle_peak=round(max(r[3] for r in rows), 3),
                overshoot_m=round(max(r[1] for r in rows) - (alt + step_m), 1),
                cas_excursion_kt=round(max(r[4] for r in rows) - min(r[4] for r in rows), 1),
                fraction_of_excess_thrust_used=round((max(r[5] for r in rows) - t0) / (tmax - t0), 2),
                thr_per_ste=round(p.get("ap/tecs/thr-per-ste"), 3), hdot_max_fps=round(p.get("ap/tecs/hdot-max-fps"), 1),
                edot_max_mps=round(perf.edot_max_mps, 2), gamma_max_deg=round(perf.gamma_max_deg, 2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--step", type=float, default=300.0); ap.add_argument("--pre", action="store_true")
    ap.add_argument("--aircraft", nargs="*", default=list(CASES))
    a = ap.parse_args()
    print(json.dumps([step_response(ac, a.step, a.pre) for ac in a.aircraft], indent=1))
