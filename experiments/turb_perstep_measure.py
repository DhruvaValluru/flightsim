"""Measure-first: can severity / W20 be driven per step on the pinned build?

Both the lee-rotor coupling (turbulence intensity following the terrain under
the aircraft) and the evolving-conditions schedule (intensity following the
clock) need the same primitive: `atmosphere/turbulence/milspec/severity` and
`.../windspeed_at_20ft_AGL-fps` re-written inside the step loop while
`atmosphere/randomseed` is written exactly once. The catastrophic failure in
this neighbourhood is already measured — re-writing the *seed* per step
restarts the generator and turns 0.40 g into 515 g (docs/JSBSIM_CORRECTIONS.md
§9) — but nothing yet said whether the *intensity* parameters may move while
the process runs. This experiment measures it, in both intensity regimes,
before any provider is allowed to depend on it.

What is measured
----------------
1. **Rewrite-same**: re-writing the same severity/W20 every step must leave
   the realisation bit-identical to writing it once (max |Δ turb-down| = 0).
2. **Stepped schedule**: seed once, severity none → light → moderate → severe
   in 20 s blocks. Windowed σ_w per block, compared to a constant-intensity
   run of the same seed (factor bounds [0.5, 2.0] stated before measuring —
   a 16 s window of a correlated process is a noisy σ estimate, and the POE
   ladder spans 15× so even loose bounds discriminate levels).
3. **Continuous ramps** — what a position-coupled provider would actually
   write: W20 ramped 15 → 45 kt at 150 m AGL; severity ramped 2 → 4 at
   1000 m. Windowed σ_w against the closed-form expectation.
4. **Fractional severity**: does σ_w interpolate between POE indices?

Both regimes measured because the standard sets intensity two different ways
(§9): below ~300 m AGL W20 governs and severity is ignored; above, the POE
index governs and W20 is ignored. A provider that passed only one regime
would silently do nothing in the other.

Measured verdict (recorded in docs/JSBSIM_CORRECTIONS.md §13)
-------------------------------------------------------------
The W20 route is sane — steps and continuous ramps both deliver
σ_w ≈ 0.107·W20(t) with no overshoot. The POE route is NOT sane for mid-run
changes: a nonzero → nonzero severity change overshoots σ_w by 2–5× and takes
tens of seconds to settle, and fractional severity floors to the integer
index. Coupled turbulence must therefore drive W20 below the 300 m AGL
ceiling and refuse the POE regime.

Usage: .venv/bin/python experiments/turb_perstep_measure.py
Writes runs/turb_perstep/report.json. Exit 0 when the measurement completes;
the verdict lives in the report and the corrections doc, not the exit code.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.environment.turbulence import (  # noqa: E402
    TURB_TUSTIN, W20_KT, poe_index_for,
)
from core.fdm import units as u  # noqa: E402
from experiments.gate3_null_tests import build  # noqa: E402

RULE = "=" * 96

SEVERITY_PROP = "atmosphere/turbulence/milspec/severity"
W20_PROP = "atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps"
TURB_DOWN_PROP = "atmosphere/turb-down-fps"

#: The stepped schedule: (start_s, intensity word). 20 s per block.
SCHEDULE: Tuple[Tuple[float, str], ...] = (
    (0.0, "none"), (20.0, "light"), (40.0, "moderate"), (60.0, "severe"),
)
BLOCK_S = 20.0
SETTLE_S = 4.0
TOTAL_S = 80.0

#: Stated before measuring (see module docstring).
BLOWUP_LIMIT_G = 2.5
FAMILY_FACTOR = (0.5, 2.0)

#: The measured low-altitude relation, sigma_w = 0.107 * W20 (§9).
LOW_ALT_SIGMA_PER_W20 = 0.107


def intensity_at(t_s: float) -> str:
    word = SCHEDULE[0][1]
    for start, name in SCHEDULE:
        if t_s >= start:
            word = name
    return word


@dataclass
class Run:
    """One flown run: per-step time, turb-down (fps) and n_z."""

    t: List[float] = field(default_factory=list)
    turb_down_fps: List[float] = field(default_factory=list)
    n_z: List[float] = field(default_factory=list)

    def peak_nz_excursion(self) -> float:
        return max((abs(v - 1.0) for v in self.n_z), default=0.0)

    def sigma_between(self, t0: float, t1: float) -> float:
        xs = [w for t, w in zip(self.t, self.turb_down_fps) if t0 <= t < t1]
        if not xs:
            return 0.0
        return math.sqrt(sum(x * x for x in xs) / len(xs))


def fly(aircraft: str, altitude_m: float, cas_kt: float, seconds: float,
        seed: int, severity_fn: Callable[[float], float],
        w20_fps_fn: Callable[[float], float],
        write_each_step: bool = True) -> Run:
    """Fly with turbulence intensity driven by the two callables.

    The seed and turb-type are written exactly once in every mode. With
    ``write_each_step`` False the t=0 values are written once and never again
    (the write-once reference).
    """
    fdm = build(aircraft, altitude_m, cas_kt)
    # Turb-type stays TURB_TUSTIN even while intensity is zero, so a schedule
    # can raise intensity without touching the model mid-run; σ_w at
    # severity 0 / W20 0 is measured-zero.
    fdm.props.set("atmosphere/turb-type", float(TURB_TUSTIN))
    fdm.props.set("atmosphere/randomseed", float(seed))
    fdm.props.set(SEVERITY_PROP, severity_fn(0.0))
    fdm.props.set(W20_PROP, w20_fps_fn(0.0))

    run = Run()
    for _ in range(int(round(seconds * fdm.rate_hz))):
        if write_each_step:
            t = fdm.sim_time
            fdm.props.set(SEVERITY_PROP, severity_fn(t))
            fdm.props.set(W20_PROP, w20_fps_fn(t))
        fdm.step()
        s = fdm.state()
        run.t.append(s.t)
        run.turb_down_fps.append(fdm.props.get(TURB_DOWN_PROP))
        run.n_z.append(s.n_z)
    return run


def word_fns(word_fn: Callable[[float], str]):
    """Severity / W20 write functions following an intensity-word timeline."""
    return (lambda t: float(poe_index_for(word_fn(t))),
            lambda t: u.kt_to_fps(W20_KT[word_fn(t)]))


@dataclass
class RegimeVerdict:
    label: str
    aircraft: str
    altitude_m: float
    rewrite_max_delta_fps: float
    rewrite_peak_nz_ref: float
    rewrite_peak_nz_rewrite: float
    schedule_peak_nz: float
    block_sigmas: Dict[str, float]
    constant_sigmas: Dict[str, float]
    family_ratios: Dict[str, float]

    @property
    def rewrite_is_noop(self) -> bool:
        return self.rewrite_max_delta_fps == 0.0

    @property
    def no_blowup(self) -> bool:
        return self.schedule_peak_nz < BLOWUP_LIMIT_G

    @property
    def monotone(self) -> bool:
        ordered = [self.block_sigmas[w] for _, w in SCHEDULE]
        return all(a < b for a, b in zip(ordered, ordered[1:]))

    @property
    def in_family(self) -> bool:
        lo, hi = FAMILY_FACTOR
        return all(lo <= r <= hi for r in self.family_ratios.values())

    @property
    def sane(self) -> bool:
        return (self.rewrite_is_noop and self.no_blowup
                and self.monotone and self.in_family)

    def render(self) -> str:
        lines = [f"  regime: {self.label} ({self.aircraft} at {self.altitude_m:g} m)"]
        lines.append(
            f"  [{'ok ' if self.rewrite_is_noop else 'FAIL'}] rewrite-same is a "
            f"no-op: max |D turb-down| {self.rewrite_max_delta_fps:g} fps, peak "
            f"|n_z-1| {self.rewrite_peak_nz_ref:.3f} g once-written vs "
            f"{self.rewrite_peak_nz_rewrite:.3f} g re-written")
        lines.append(
            f"  [{'ok ' if self.no_blowup else 'FAIL'}] no blow-up: schedule peak "
            f"|n_z-1| {self.schedule_peak_nz:.3f} g (limit {BLOWUP_LIMIT_G} g; "
            f"the re-seed failure reached 515 g)")
        blocks = ", ".join(f"{w} {self.block_sigmas[w]:.3f}" for _, w in SCHEDULE)
        lines.append(
            f"  [{'ok ' if self.monotone else 'FAIL'}] windowed sigma_w rises "
            f"with severity: {blocks} fps")
        ratios = ", ".join(f"{w} {r:.2f}x" for w, r in self.family_ratios.items())
        lines.append(
            f"  [{'ok ' if self.in_family else 'FAIL'}] schedule blocks match "
            f"constant runs within {FAMILY_FACTOR}: {ratios}")
        return "\n".join(lines)

    def to_json(self) -> Dict:
        return {
            "label": self.label, "aircraft": self.aircraft,
            "altitude_m": self.altitude_m,
            "rewrite_max_delta_fps": self.rewrite_max_delta_fps,
            "rewrite_peak_nz_ref_g": self.rewrite_peak_nz_ref,
            "rewrite_peak_nz_rewrite_g": self.rewrite_peak_nz_rewrite,
            "schedule_peak_nz_g": self.schedule_peak_nz,
            "block_sigma_w_fps": self.block_sigmas,
            "constant_sigma_w_fps": self.constant_sigmas,
            "family_ratios": self.family_ratios,
            "checks": {
                "rewrite_is_noop": self.rewrite_is_noop,
                "no_blowup": self.no_blowup,
                "monotone": self.monotone,
                "in_family": self.in_family,
            },
            "sane": self.sane,
        }


def measure_regime(label: str, aircraft: str, altitude_m: float,
                   cas_kt: float, seed: int) -> RegimeVerdict:
    print(f"  measuring {label}: {aircraft} at {altitude_m:g} m, seed {seed}")
    constant_moderate = word_fns(lambda t: "moderate")

    # 1. rewrite-same vs write-once, constant moderate.
    ref = fly(aircraft, altitude_m, cas_kt, 40.0, seed, *constant_moderate,
              write_each_step=False)
    rewrite = fly(aircraft, altitude_m, cas_kt, 40.0, seed, *constant_moderate)
    n = min(len(ref.turb_down_fps), len(rewrite.turb_down_fps))
    max_delta = max((abs(ref.turb_down_fps[i] - rewrite.turb_down_fps[i])
                     for i in range(n)), default=0.0)

    # 2. the stepped schedule.
    sched = fly(aircraft, altitude_m, cas_kt, TOTAL_S, seed,
                *word_fns(intensity_at))
    block_sigmas: Dict[str, float] = {}
    for start, word in SCHEDULE:
        block_sigmas[word] = sched.sigma_between(start + SETTLE_S,
                                                 start + BLOCK_S)

    # 3. constant-intensity references, same seed, sigma over an equal window.
    constant_sigmas: Dict[str, float] = {}
    for _, word in SCHEDULE:
        if word == "none":
            constant_sigmas[word] = 0.0
            continue
        const = fly(aircraft, altitude_m, cas_kt, SETTLE_S + BLOCK_S, seed,
                    *word_fns(lambda t, w=word: w))
        constant_sigmas[word] = const.sigma_between(SETTLE_S, BLOCK_S)

    family = {}
    for _, word in SCHEDULE:
        if word == "none":
            continue
        expected = constant_sigmas[word]
        family[word] = (block_sigmas[word] / expected) if expected > 0 else 0.0

    return RegimeVerdict(
        label=label, aircraft=aircraft, altitude_m=altitude_m,
        rewrite_max_delta_fps=max_delta,
        rewrite_peak_nz_ref=ref.peak_nz_excursion(),
        rewrite_peak_nz_rewrite=rewrite.peak_nz_excursion(),
        schedule_peak_nz=sched.peak_nz_excursion(),
        block_sigmas=block_sigmas, constant_sigmas=constant_sigmas,
        family_ratios=family,
    )


def measure_w20_ramp(seed: int) -> Dict:
    """Continuous W20 ramp at 150 m AGL — the coupled provider's write pattern."""
    print("  measuring continuous W20 ramp at 150 m (the coupled write pattern)")

    def w20_fps(t: float) -> float:
        kt = 15.0 if t < 20.0 else 15.0 + 30.0 * min((t - 20.0) / 40.0, 1.0)
        return u.kt_to_fps(kt)

    run = fly("B747", 150.0, 250.0, 80.0, seed, lambda t: 3.0, w20_fps)
    windows = []
    for t0, t1 in ((10.0, 20.0), (25.0, 35.0), (40.0, 50.0), (65.0, 80.0)):
        expected = LOW_ALT_SIGMA_PER_W20 * w20_fps((t0 + t1) / 2.0)
        measured = run.sigma_between(t0, t1)
        windows.append({"window_s": [t0, t1], "sigma_w_fps": measured,
                        "expected_fps": expected,
                        "ratio": measured / expected if expected else 0.0})
    ratios = [w["ratio"] for w in windows]
    lo, hi = FAMILY_FACTOR
    return {
        "what": "W20 ramped 15->45 kt over (20,60) s at 150 m AGL, severity held",
        "windows": windows,
        "peak_nz_g": run.peak_nz_excursion(),
        "tracks": all(lo <= r <= hi for r in ratios),
    }


def measure_severity_ramp(seed: int) -> Dict:
    """Continuous severity ramp at 1000 m — measured NOT sane; kept as evidence."""
    print("  measuring continuous severity ramp at 1000 m (the POE route)")

    def severity(t: float) -> float:
        return 2.0 if t < 20.0 else 2.0 + 2.0 * min((t - 20.0) / 40.0, 1.0)

    run = fly("B747", 1000.0, 250.0, 80.0, seed, severity,
              lambda t: u.kt_to_fps(30.0))
    # Expected from the measured POE ladder for the *commanded* (floored) index.
    from core.environment.turbulence import POE_SIGMA_W_FPS
    windows = []
    for t0, t1 in ((10.0, 20.0), (25.0, 40.0), (45.0, 60.0), (65.0, 80.0)):
        index = int(severity((t0 + t1) / 2.0))
        expected = POE_SIGMA_W_FPS[index]
        measured = run.sigma_between(t0, t1)
        windows.append({"window_s": [t0, t1], "sigma_w_fps": measured,
                        "commanded_index_floored": index,
                        "ladder_sigma_fps": expected,
                        "ratio": measured / expected if expected else 0.0})
    ratios = [w["ratio"] for w in windows]
    lo, hi = FAMILY_FACTOR
    return {
        "what": "severity ramped 2->4 over (20,60) s at 1000 m, W20 held 30 kt",
        "windows": windows,
        "peak_nz_g": run.peak_nz_excursion(),
        "tracks": all(lo <= r <= hi for r in ratios),
    }


def measure_fractional_severity(seed: int) -> Dict:
    """Does sigma_w interpolate between POE indices? (Measured: it floors.)"""
    print("  measuring fractional severity at 1000 m")
    out = []
    for sev in (2.0, 2.5, 3.0):
        run = fly("B747", 1000.0, 250.0, 40.0, seed, lambda t, s=sev: s,
                  lambda t: u.kt_to_fps(30.0))
        out.append({"severity": sev,
                    "sigma_w_fps": run.sigma_between(20.0, 40.0)})
    interpolates = not math.isclose(out[0]["sigma_w_fps"],
                                    out[1]["sigma_w_fps"], rel_tol=0.05)
    return {"what": "constant fractional severity, sigma over (20,40) s",
            "runs": out, "interpolates": interpolates}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args(argv)

    print(f"{RULE}\nper-step severity/W20 writes on the pinned build -- "
          f"measured, not assumed\n{RULE}")
    # Both regimes on the B747: the W20/POE split is set by altitude, not by
    # airframe (docs/JSBSIM_CORRECTIONS.md §9), and the c172p cannot be
    # started headless (its piston engine's set-running does not latch --
    # measured; the showcase flies it only in the UE host).
    regimes = [
        measure_regime("low-altitude (W20 route)", "B747", 150.0, 250.0,
                       args.seed),
        measure_regime("medium-altitude (POE route)", "B747", 1000.0, 250.0,
                       args.seed),
    ]
    w20_ramp = measure_w20_ramp(args.seed)
    severity_ramp = measure_severity_ramp(args.seed)
    fractional = measure_fractional_severity(args.seed)

    print()
    for verdict in regimes:
        print(verdict.render())
        print()
    print(f"  [{'ok ' if w20_ramp['tracks'] else 'FAIL'}] continuous W20 ramp "
          f"tracks 0.107*W20(t): "
          + ", ".join(f"{w['sigma_w_fps']:.2f}/{w['expected_fps']:.2f}"
                      for w in w20_ramp["windows"]))
    print(f"  [{'ok ' if severity_ramp['tracks'] else 'FAIL'}] continuous "
          f"severity ramp tracks the POE ladder: "
          + ", ".join(f"{w['sigma_w_fps']:.2f}/{w['ladder_sigma_fps']:.2f}"
                      for w in severity_ramp["windows"]))
    print(f"  fractional severity interpolates: {fractional['interpolates']} "
          f"(" + ", ".join(f"{r['severity']:g}->{r['sigma_w_fps']:.2f}"
                           for r in fractional["runs"]) + " fps)")

    w20_route_sane = regimes[0].sane and w20_ramp["tracks"]
    poe_route_sane = (regimes[1].sane and severity_ramp["tracks"])

    out = Path(__file__).resolve().parents[1] / "runs" / "turb_perstep"
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "what": "per-step severity/W20 writes, seed written once (measure-first "
                "for lee-rotor coupling and the evolving-conditions schedule)",
        "bars": {
            "rewrite_same_max_delta_fps": 0.0,
            "blowup_limit_g": BLOWUP_LIMIT_G,
            "family_factor": FAMILY_FACTOR,
            "settle_skipped_s": SETTLE_S,
        },
        "schedule": [[t, w] for t, w in SCHEDULE],
        "regimes": [v.to_json() for v in regimes],
        "w20_continuous_ramp": w20_ramp,
        "severity_continuous_ramp": severity_ramp,
        "fractional_severity": fractional,
        "verdict": {
            "w20_route_sane": w20_route_sane,
            "poe_route_sane": poe_route_sane,
            "consequence": (
                "coupled/scheduled turbulence intensity must drive W20 below "
                "the 300 m AGL ceiling; mid-run severity changes in the POE "
                "regime overshoot sigma_w 2-5x and are refused"),
        },
    }
    path = out / "report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{RULE}\n  MEASURED: W20 route {'SANE' if w20_route_sane else 'NOT SANE'}; "
          f"POE route {'SANE' if poe_route_sane else 'NOT SANE'} -> {path}\n{RULE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
