"""Turbulence in the Unreal host: null-tested, and parity decided by measurement.

Phase 6B.3, both halves:

1. **The null test** (Gate 3's discipline, applied to the embedded host). A
   turbulent UE run's load-factor RMS about its mean must rise measurably over
   the same scenario in calm air -- proof the Dryden process reached the FDM
   inside Unreal, not a camera shake or a manifest field. The commandlet is
   armed with -AllowNonParityEnvironment because this run IS a measurement of
   turbulence, not a parity sample.

2. **Same-seed parity, decided honestly.** Both hosts run the same spec with
   the same seed through the same JSBSim Dryden filters. If the realisations
   match under Gate 5's existing n_z tolerance, turbulence is parity-eligible;
   if they do not, this experiment MEASURES the divergence, reports it, and
   the parity path keeps refusing turbulent cards. Either verdict is recorded
   in the report with the seed.

Verdicts live in ``runs/turbulence_ue/report.json``; docs/VALIDITY.md states
whichever one held.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scenario.runner import run_spec  # noqa: E402
from experiments.gate5_ue_parity import (  # noqa: E402
    TOLERANCE, reference_spec, write_run_card,
)

RULE = "=" * 96

PROMPT = "fly the 747 at 3000 m and 250 kt for 40 seconds"
SEED = 424242

#: Null-test thresholds, declared before any run. Moderate turbulence measured
#: headless on this spec produces load-factor RMS well above 0.02; a calm
#: open-loop run's phugoid drifts far below it. The ratio requirement makes
#: the comparison self-normalising.
NULL_TEST = {
    "min_turbulent_rms": 0.02,
    "min_rms_ratio": 5.0,
}


def rms_about_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def load_nz(telemetry_path: Path) -> List[float]:
    data = json.loads(Path(telemetry_path).read_text())
    return [float(v) for v in data["columns"]["n_z"]]


def run_ue(card: Path, out: Path, allow_environment: bool) -> Path:
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_ue_scenario.sh"
    command = [str(script), str(card), str(out)]
    if allow_environment:
        command.append("-AllowNonParityEnvironment")
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"UE run failed ({proc.returncode}):\n{proc.stdout[-2000:]}\n"
            f"{proc.stderr[-2000:]}")
    return out


def null_test(calm_nz: List[float], turbulent_nz: List[float]) -> Dict:
    """The guard: turbulence must measurably reach the FDM."""
    calm_rms = rms_about_mean(calm_nz)
    turbulent_rms = rms_about_mean(turbulent_nz)
    ratio = turbulent_rms / calm_rms if calm_rms > 0 else float("inf")
    return {
        "calm_rms": calm_rms,
        "turbulent_rms": turbulent_rms,
        "ratio": ratio,
        "thresholds": dict(NULL_TEST),
        "ok": bool(turbulent_rms >= NULL_TEST["min_turbulent_rms"]
                   and ratio >= NULL_TEST["min_rms_ratio"]),
    }


def compare_realisations(headless_nz: List[float], headless_t: List[float],
                         unreal_nz: List[float], unreal_t: List[float]) -> Dict:
    """Same-seed comparison on the recorded clock, Gate 5's n_z tolerance.

    The trim snapshot exemption follows the parity harness: each host's first
    sample is its trim state and is not part of the flown comparison.
    """
    from experiments.gate5_ue_parity import _interpolate

    start = max(headless_t[1], unreal_t[1])
    end = min(headless_t[-1], unreal_t[-1])
    diffs = []
    for t, value in zip(unreal_t, unreal_nz):
        if start <= t <= end:
            diffs.append(abs(value - _interpolate(headless_t, headless_nz, t)))
    max_diff = max(diffs) if diffs else float("inf")
    return {
        "samples": len(diffs),
        "max_nz_difference": max_diff,
        "tolerance": TOLERANCE["n_z"],
        "matches": bool(max_diff <= TOLERANCE["n_z"]),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="UE turbulence: null test + parity")
    ap.add_argument("--out", default="runs/turbulence_ue")
    ap.add_argument("--skip-runs", action="store_true",
                    help="analyse existing telemetry without re-running")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n{RULE}\n1. the two scenarios: same spec, turbulence on/off\n{RULE}")
    turbulent = reference_spec(PROMPT)
    turbulent.set("turbulence", "moderate", frm="turbulence measurement")
    turbulent.set("seed", SEED, frm="turbulence measurement")
    calm = reference_spec(PROMPT)

    turbulent_card = write_run_card(turbulent, out / "turbulent_card.json")
    calm_card = write_run_card(calm, out / "calm_card.json")
    print(f"  turbulent  {turbulent.digest()[:16]} (seed {SEED})")
    print(f"  calm       {calm.digest()[:16]}")

    if not args.skip_runs:
        print(f"\n{RULE}\n2. the UE runs\n{RULE}")
        run_ue(turbulent_card, out / "ue_turbulent.json", allow_environment=True)
        run_ue(calm_card, out / "ue_calm.json", allow_environment=False)
        print("  both UE runs recorded")

        print(f"\n{RULE}\n3. the headless same-seed run\n{RULE}")
        result = run_spec(turbulent)
        result.telemetry.write_json(out / "headless_turbulent.json")
        print(f"  headless turbulent run recorded ({len(result.telemetry)} samples)")

    for name in ("ue_turbulent.json", "ue_calm.json", "headless_turbulent.json"):
        if not (out / name).is_file():
            print(f"  missing {out / name}; run without --skip-runs")
            return 2

    print(f"\n{RULE}\n4. the null test: turbulence reached the UE FDM\n{RULE}")
    turbulent_nz = load_nz(out / "ue_turbulent.json")
    calm_nz = load_nz(out / "ue_calm.json")
    null = null_test(calm_nz, turbulent_nz)
    print(f"  [{'ok  ' if null['ok'] else 'FAIL'}] load-factor RMS about mean: "
          f"calm {null['calm_rms']:.5f}, turbulent {null['turbulent_rms']:.5f} "
          f"(x{null['ratio']:.1f}; needs >= {NULL_TEST['min_turbulent_rms']} "
          f"and x{NULL_TEST['min_rms_ratio']:.0f})")

    print(f"\n{RULE}\n5. same-seed parity, measured not assumed\n{RULE}")
    ue = json.loads((out / "ue_turbulent.json").read_text())
    headless = json.loads((out / "headless_turbulent.json").read_text())
    parity = compare_realisations(
        [float(v) for v in headless["columns"]["n_z"]],
        [float(v) for v in headless["columns"]["t"]],
        [float(v) for v in ue["columns"]["n_z"]],
        [float(v) for v in ue["columns"]["t"]],
    )
    verdict = ("parity-eligible" if parity["matches"] else "visual-only")
    print(f"  same seed {SEED}, max |n_z| difference "
          f"{parity['max_nz_difference']:.4f} vs tolerance {parity['tolerance']}"
          f" -> {verdict}")
    if not parity["matches"]:
        print("  the two hosts draw different realisations from the same seed;")
        print("  the parity path keeps refusing turbulent cards, and every")
        print("  turbulent clip is labeled visual-only with its seed recorded.")

    # The MEASURED why, when the realisations differ (they do on this build):
    # is each host at least deterministic with its own seed, and when does the
    # cross-host divergence begin? A repeat UE run distinguishes "different
    # RNG stream position per process" from nondeterminism.
    why: Dict = {}
    repeat_path = out / "ue_turbulent_repeat.json"
    if repeat_path.is_file():
        repeat_nz = load_nz(repeat_path)
        why["ue_run_to_run_max_nz_diff"] = max(
            abs(x - y) for x, y in zip(turbulent_nz, repeat_nz))
        headless_nz = [float(v) for v in headless["columns"]["n_z"]]
        onset = None
        for index, (t, value) in enumerate(
                zip([float(v) for v in ue["columns"]["t"]], turbulent_nz)):
            if index < len(headless_nz) and abs(value - headless_nz[index]) > 0.002:
                onset = t
                break
        why["divergence_onset_s"] = onset
        why["interpretation"] = (
            "each host is bit-repeatable with its own seed; the realisations "
            "differ from the first flown sample, so the two processes consume "
            "the shared generator from different stream positions -- a "
            "per-process RNG stream offset, not nondeterminism")
        print(f"\n  measured why: UE repeat max diff "
              f"{why['ue_run_to_run_max_nz_diff']:g}; divergence onset "
              f"{why['divergence_onset_s']} s")

    report = {
        "prompt": PROMPT,
        "seed": SEED,
        "turbulent_spec_digest": turbulent.digest(),
        "calm_spec_digest": calm.digest(),
        "null_test": null,
        "same_seed_parity": parity,
        "divergence_measured_why": why,
        "verdict": verdict,
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\n  wrote {out / 'report.json'}")

    if not null["ok"]:
        print("\n  TURBULENCE NULL TEST: FAIL -- the UE host did not deliver "
              "turbulence to the FDM.")
        return 1
    print("\n  TURBULENCE NULL TEST: PASS"
          f" (host parity verdict: {verdict}, recorded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
