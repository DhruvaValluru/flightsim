"""Gate 7 -- a sweep that survives interruption, and a manifest that reproduces.

    A full sweep runs, resumes after interruption, and produces a manifest from
    which the run reproduces bit-identically. The validation report exists and
    states limits honestly. (§5 Phase 7)

The resume test is done by actually killing a sweep, not by asserting that the
resume code path exists. A sweep is interrupted at a fixed case, restarted, and
the union of the two datasets is compared against an uninterrupted run of the
same design. That is the only version of this test that would have caught a
resume that silently re-ran everything, or one that paired new parameters with
old results.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.experiments.analysis import analyse, replicate_precision  # noqa: E402
from core.experiments.manifest import RunManifest, sha256_file, verify_reproduction  # noqa: E402
from core.experiments.seeds import derive  # noqa: E402
from core.experiments.sweep import (  # noqa: E402
    Case, Design, Factor, ResultLog, degenerate_replicates, run_sweep,
)
from core.nl.compiler import compile_prompt  # noqa: E402
from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.spec import ScenarioSpec  # noqa: E402
from core.validation.reference import (  # noqa: E402
    PART60, Comparison, Reference, ValidationReport, Verdict,
)
from core.validation.scorecard import Scorecard, SubsystemScore  # noqa: E402

RULE = "=" * 96

METRICS = ("mean_altitude_m", "altitude_excursion_m", "mean_tas_kt",
           "peak_load_factor", "closure_ok")


class Interrupted(RuntimeError):
    """Raised by the harness to simulate a killed sweep."""


def evaluate(spec: ScenarioSpec, case: Case) -> Dict[str, Any]:
    """Run one case and reduce its telemetry to metrics."""
    result = run_spec(spec, assert_closure=False)
    altitude = result.telemetry.series("altitude_m")
    tas = result.telemetry.series("tas_kt")
    load = result.telemetry.series("n_z")
    settled = altitude[len(altitude) // 2:]
    return {
        "mean_altitude_m": sum(settled) / len(settled),
        "altitude_excursion_m": max(altitude) - min(altitude),
        "mean_tas_kt": sum(tas) / len(tas),
        "peak_load_factor": max(load, key=lambda v: abs(v - 1.0)),
        "closure_ok": bool(result.closure.ok) if result.closure else None,
        "output_digest": result.output_digest,
    }


def build_design(replicates: int) -> Tuple[Design, ScenarioSpec]:
    base = compile_prompt("fly the 747 at 3000 m and 250 kt for 30 seconds")
    design = Design(
        factors=[
            Factor("turbulence", ["none", "light", "moderate"]),
            Factor("wind_speed", [0.0, 15.0, 30.0]),
        ],
        kind=Design.FACTORIAL,
        replicates=replicates,
        experiment_seed=20260805,
    )
    return design, base


# -- 1 and 2: the sweep, and surviving being killed ----------------------


def run_uninterrupted(design: Design, base: ScenarioSpec, out: Path):
    return run_sweep(design, base, evaluate, out / "full", resume=False)


def run_with_interruption(design: Design, base: ScenarioSpec, out: Path,
                          kill_after: int) -> Tuple[int, int]:
    """Kill a sweep part-way, then resume it, and report both counts."""
    directory = out / "interrupted"
    calls = {"n": 0}

    def failing_evaluate(spec: ScenarioSpec, case: Case) -> Dict[str, Any]:
        if calls["n"] >= kill_after:
            raise Interrupted("simulated kill")
        calls["n"] += 1
        return evaluate(spec, case)

    # The first pass dies. Cases are recorded as failures rather than dropped,
    # so they must be cleared before the resume, exactly as a real kill would
    # leave them absent.
    try:
        run_sweep(design, base, failing_evaluate, directory, resume=False)
    except Interrupted:
        pass

    log = ResultLog(directory / "dataset.jsonl")
    surviving = [r for r in log.rows() if r.get("ok")]
    log.path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                                for r in surviving), encoding="utf-8")
    first_pass = len(surviving)

    resumed = run_sweep(design, base, evaluate, directory, resume=True)
    return first_pass, resumed.skipped


def datasets_agree(a: Sequence[Dict[str, Any]], b: Sequence[Dict[str, Any]]
                   ) -> Tuple[bool, List[str]]:
    """Two datasets must agree case-for-case on every metric."""
    index_a = {r["case_id"]: r for r in a if r.get("ok")}
    index_b = {r["case_id"]: r for r in b if r.get("ok")}
    problems = []
    if set(index_a) != set(index_b):
        problems.append(
            f"different case sets: {len(index_a)} vs {len(index_b)}, "
            f"{len(set(index_a) ^ set(index_b))} not in common"
        )
    for case_id in sorted(set(index_a) & set(index_b)):
        for metric in METRICS:
            x, y = index_a[case_id].get(metric), index_b[case_id].get(metric)
            if isinstance(x, float) and isinstance(y, float):
                if not math.isclose(x, y, rel_tol=0.0, abs_tol=0.0):
                    problems.append(f"{case_id}.{metric}: {x} != {y}")
            elif x != y:
                problems.append(f"{case_id}.{metric}: {x!r} != {y!r}")
        if index_a[case_id].get("output_digest") != index_b[case_id].get("output_digest"):
            problems.append(f"{case_id}: telemetry digest differs")
    return not problems, problems


# -- 4: validation -------------------------------------------------------


def validation_report() -> ValidationReport:
    from core.scenario.envelope import reference_speeds

    report = ValidationReport("Validation report -- flightsim, phase 7")

    speeds = reference_speeds("B747", 250_000.0, 0.0)
    report.add(Comparison(
        quantity="B747 clean 1g stall speed at 250 t",
        simulation=speeds.vs_kt,
        unit="kt",
        reference=Reference(
            quantity="clean 1g stall speed",
            value=157.0,
            unit="kt",
            # Wide on purpose: this is a figure quoted from open literature for
            # a weight band, not a measurement with a stated error.
            uncertainty=12.0,
            source="published 747-400 performance summaries, open literature",
            pedigree="specification/typical figure, not flight-test data; "
                     "weight and configuration not exactly matched",
        ),
        numerical_uncertainty=1.0,
        input_uncertainty=3.0,
        tolerance=PART60["approach_airspeed"],
        note="derived from the model's own measured CLmax",
    ))

    # Everything below has no referent this build can defend. Saying so is the
    # result; inventing a datum to compare against would be worse than silence.
    for quantity, unit, note in (
        ("B747 takeoff ground roll", "m",
         "no flight-test reference; stock aero has no validated ground effect "
         "or thrust model to compare"),
        ("B747 engine spool time", "s",
         "the stock turbine model is generic; no manufacturer spool data"),
        ("Short-period damping ratio", "-",
         "requires linearisation this build does not perform (§6.5 margins "
         "are likewise unverified)"),
        ("Transport delay, input to response", "s",
         "meaningful only for the interactive host, which does not build here"),
    ):
        report.add(Comparison(quantity=quantity, simulation=math.nan,
                              unit=unit, reference=None, note=note))

    report.notes.append(
        "Stock JSBSim aircraft carry an explicit disclaimer that they are "
        "validated 'only to the extent that it seems to fly right' (§3.3). No "
        "claim of a validated transport model is supportable with stock data, "
        "and this report does not make one."
    )
    return report


# -- 5: credibility scorecard --------------------------------------------


def scorecard() -> Scorecard:
    card = Scorecard(
        title="Credibility assessment -- flightsim, phases 0-7",
        # Declared before scoring. Level 2 is what an internal research
        # instrument can reasonably be held to; level 3 requires independent
        # review, which has not happened.
        threshold=2,
        threshold_rationale=(
            "Level 2 (some formal process, partly documented) is the bar for "
            "an internal research instrument. Level 3+ requires independent "
            "review, which no part of this system has had."
        ),
    )

    card.add(SubsystemScore("aerodynamics")
             .set("verification", 2, "gate 0 trim-hold across 3 airframes x 3 "
                  "envelope points; lift curve measured, CLmax bracketed")
             .set("validation", 1, "one comparison against an open-literature "
                  "stall figure; everything else inconclusive")
             .set("input_pedigree", 1, "stock JSBSim tables, explicit "
                  "no-fidelity disclaimer (§3.3); B747 author 'Unknown'")
             .set("results_uncertainty", 1, "numerical uncertainty from "
                  "timestep convergence only; no input UQ")
             .set("results_robustness", 2, "timestep convergence 0.098 m at "
                  "1/60->1/120, 0.048 m at 1/120->1/240")
             .set("use_history", 0, "no results have been used for anything yet")
             .set("m_and_s_management", 2, "versioned, hashed, gated, "
                  "mutation-checked test suite")
             .set("people_qualification", 0, "not assessed"))

    card.add(SubsystemScore("control")
             .set("verification", 3, "gate 2 step-response characterisation "
                  "with declared acceptance criteria; TECS decoupling test")
             .set("validation", 0, "no flight-test data for any autopilot here")
             .set("input_pedigree", 1, "gains tuned by measured sweep on one "
                  "airframe at one condition, unscheduled")
             .set("results_uncertainty", 0, "no gain or phase margins measured; "
                  "§6.5's 6 dB / 45 deg criteria are unverified")
             .set("results_robustness", 1, "one airframe, one flight condition")
             .set("use_history", 0, "none")
             .set("m_and_s_management", 3, "controller versioned in-repo, "
                  "hashed into the run manifest, bumpless engage regression-tested")
             .set("people_qualification", 0, "not assessed"))

    card.add(SubsystemScore("atmosphere")
             .set("verification", 3, "gate 3 null-test ladder; crab angle "
                  "matches atan(w/V) to 0.01 deg")
             .set("validation", 2, "turbulence sigma_w reproduces "
                  "MIL-F-8785C's 0.1*W20 low-altitude relation (measured 0.107)")
             .set("input_pedigree", 3, "MIL-F-8785C Dryden via JSBSim's own "
                  "implementation; POE ladder measured, not assumed")
             .set("results_uncertainty", 1, "no UQ on turbulence realisations")
             .set("results_robustness", 2, "null tests permanent; seeds "
                  "derived per subsystem")
             .set("use_history", 0, "none")
             .set("m_and_s_management", 3, "providers declare vocabulary with "
                  "citations (§2.5)")
             .set("people_qualification", 0, "not assessed"))

    card.add(SubsystemScore("terrain")
             .set("verification", 3, "gate 4 round trip: 0.008 m max error, "
                  "relief and aspect preserved")
             .set("validation", 1, "ingestion checked against an analytic "
                  "surface, not against surveyed ground")
             .set("input_pedigree", 2, "real DEM path implemented; synthesised "
                  "terrain has prescribed statistics but models nowhere")
             .set("results_uncertainty", 2, "16-bit quantisation reported and "
                  "used to derive tolerances")
             .set("results_robustness", 2, "both producers through one interface")
             .set("use_history", 0, "none")
             .set("m_and_s_management", 3, "rasters hashed; integrity checked "
                  "on load")
             .set("people_qualification", 0, "not assessed"))

    card.add(SubsystemScore("sensors")
             .set("verification", 0, "not built")
             .set("validation", 0, "not built")
             .set("input_pedigree", 0, "not built")
             .set("results_uncertainty", 0, "not built")
             .set("results_robustness", 0, "not built")
             .set("use_history", 0, "not built")
             .set("m_and_s_management", 0, "not built")
             .set("people_qualification", 0, "not assessed"))

    card.notes.append(
        "'sensors' scores 0 across the board because no EO/IR modelling exists "
        "(§6.7). It is listed rather than omitted so the gap is visible in the "
        "same table as everything else."
    )
    card.notes.append(
        "Rendering is absent from this table entirely: phases 5-6 are blocked "
        "on the build toolchain, so there is nothing to score."
    )
    return card


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 7")
    ap.add_argument("--out", default="runs/gate7")
    ap.add_argument("--replicates", type=int, default=2)
    ap.add_argument("--kill-after", type=int, default=7)
    args = ap.parse_args(argv)
    out = Path(args.out)

    results: List[Tuple[str, bool]] = []
    design, base = build_design(args.replicates)

    print(f"\n{RULE}\n1. a full sweep runs\n{RULE}")
    print(f"  design: {design.kind}, {len(design.factors)} factors, "
          f"{design.size()} cases ({design.replicates} replicates)")
    full = run_uninterrupted(design, base, out)
    print(f"  completed {full.completed}, failed {full.failed}")
    ran = full.completed == design.size() and full.failed == 0
    results.append(("full sweep completes", ran))

    print(f"\n{RULE}\n2. it resumes after interruption\n{RULE}")
    first_pass, skipped = run_with_interruption(design, base, out,
                                                args.kill_after)
    interrupted_rows = ResultLog(out / "interrupted" / "dataset.jsonl").rows()
    agree, problems = datasets_agree(full.rows, interrupted_rows)
    print(f"  killed after {args.kill_after} cases -> {first_pass} survived")
    print(f"  resumed: skipped {skipped} already-done cases, "
          f"finished {len(interrupted_rows)}")
    for problem in problems[:5]:
        print(f"    -> {problem}")
    print(f"  interrupted+resumed dataset {'matches' if agree else 'DIFFERS FROM'} "
          f"the uninterrupted run, case for case")
    results.append(("resume produces an identical dataset",
                    agree and skipped == first_pass and first_pass > 0))

    print(f"\n{RULE}\n3. the manifest reproduces the run\n{RULE}")
    dataset = out / "full" / "dataset.jsonl"
    manifest = RunManifest(name="gate7-sweep")
    manifest.parameters = design.to_dict()
    manifest.seeds = derive(design.experiment_seed, 0).to_dict()
    manifest.add_input_text("base_spec", base.to_yaml())
    manifest.add_output("dataset", dataset)
    manifest_path = manifest.write(out / "manifest.json")

    replay = run_sweep(design, base, evaluate, out / "replay", resume=False)
    check = verify_reproduction(
        manifest_path, {"dataset": sha256_file(out / "replay" / "dataset.jsonl")})
    # The JSONL carries per-case wall-clock, which is not reproducible and is
    # not meant to be. Reproducibility is asserted on the physics.
    replay_agree, replay_problems = datasets_agree(full.rows, replay.rows)
    print(f"  manifest      {manifest_path}")
    print(f"  git commit    {check['git_commit']}  dirty={check['git_dirty']}")
    print(f"  dataset hash  {'matches' if check['ok'] else 'differs (wall-clock timings are in the file)'}")
    for problem in replay_problems[:5]:
        print(f"    -> {problem}")
    print(f"  physics       {'BIT-IDENTICAL' if replay_agree else 'DIVERGED'} "
          f"across all {len(full.rows)} cases")
    results.append(("run reproduces bit-identically from the manifest",
                    replay_agree))

    print(f"\n{RULE}\n4. analysis: what actually moved\n{RULE}")
    curves = analyse(full.rows, [m for m in METRICS if m != "closure_ok"])
    for curve in curves[:4]:
        print(curve.render())
    degenerate = degenerate_replicates(full.rows,
                                       [m for m in METRICS if m != "closure_ok"])
    print(f"\n  degenerate replicate groups: {len(degenerate)}")
    for item in degenerate[:3]:
        print(f"    {item['factors']} -- {item['note']}")
    precision = replicate_precision(full.rows, "altitude_excursion_m")
    print(f"  achieved precision on altitude_excursion_m: n={precision['n']}, "
          f"half-width {precision['half_width']:.4f} m")
    results.append(("analysis produces ranked, dispersed response curves",
                    bool(curves) and not math.isnan(curves[0].eta_squared)))

    print(f"\n{RULE}\n5. validation report\n{RULE}")
    report = validation_report()
    print(report.render())
    (out / "validation_report.txt").write_text(report.render(), encoding="utf-8")
    (out / "validation_report.json").write_text(json.dumps(report.to_dict(), indent=1), encoding="utf-8")
    # The report must exist AND state limits: a report with no inconclusive
    # rows, given this evidence base, would be overclaiming.
    honest = (report.counts()[Verdict.INCONCLUSIVE.value] > 0
              and len(report.notes) > 0)
    results.append(("validation report exists and states its limits", honest))

    print(f"\n{RULE}\n6. credibility scorecard\n{RULE}")
    card = scorecard()
    print(card.render())
    card.write(out / "scorecard.json")
    (out / "scorecard.txt").write_text(card.render(), encoding="utf-8")
    results.append(("scorecard published with a threshold declared in advance",
                    card.threshold is not None and bool(card.subsystems)))

    print(f"\n{RULE}\nGATE 7\n{RULE}")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    everything = all(ok for _, ok in results)
    print(f"\n  GATE 7: {'PASS' if everything else 'FAIL'}")
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
