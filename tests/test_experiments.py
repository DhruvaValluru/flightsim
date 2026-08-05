"""Sweeps, seeds, manifests, and the analysis that reads them.

The regression that matters most here is the seed saturation: JSBSim silently
collapses any seed at or above INT_MAX to 2147483647, so a sweep can record two
different seeds and run the same realisation twice.
"""

import json
import math

import pytest

from core.experiments.analysis import (
    analyse, eta_squared, replicate_precision, response_curve, stdev,
)
from core.experiments.manifest import RunManifest, sha256_text, verify_reproduction
from core.experiments.seeds import MAX_SEED, SUBSYSTEMS, derive, generator, stable_hash
from core.experiments.sweep import (
    Case, Design, Factor, ResultLog, degenerate_replicates, run_sweep,
)
from core.nl.compiler import compile_prompt


# -- seeds ---------------------------------------------------------------


def test_seeds_are_within_the_range_jsbsim_can_represent():
    """The regression. Anything at or above INT_MAX saturates.

    Measured on the pinned build: seeds 7173749350325947451 and
    4610176084448916245 both read back as 2147483647 and produced bit-identical
    turbulence, while the manifest faithfully recorded two different numbers.
    A sweep's replicates were therefore the same run, twice.
    """
    for replicate in range(8):
        for subsystem, seed in derive(12345, replicate).seeds.items():
            assert 0 < seed <= MAX_SEED, f"{subsystem} seed {seed} would saturate"
            assert seed < 2 ** 31 - 1


def test_turbulence_refuses_a_seed_it_cannot_represent():
    from core.environment.turbulence import DrydenTurbulence

    with pytest.raises(ValueError, match="saturate"):
        DrydenTurbulence("moderate", seed=2 ** 31)
    DrydenTurbulence("moderate", seed=MAX_SEED)      # the boundary is usable


def test_replicates_get_different_seeds():
    a = derive(999, replicate=0)
    b = derive(999, replicate=1)
    assert a.seeds != b.seeds
    for subsystem in SUBSYSTEMS:
        assert a.for_subsystem(subsystem) != b.for_subsystem(subsystem)


def test_subsystems_get_independent_streams():
    """Turbulence and sensor noise must not share a sequence."""
    seeds = derive(7, 0)
    values = [seeds.for_subsystem(s) for s in SUBSYSTEMS]
    assert len(set(values)) == len(values)


def test_derivation_is_stable_across_processes():
    """A salted hash would change the seed between runs of one experiment."""
    assert stable_hash("turbulence") == stable_hash("turbulence")
    assert derive(42, 3).seeds == derive(42, 3).seeds
    assert generator(42, "turbulence", 3).random() == \
        generator(42, "turbulence", 3).random()


def test_seed_none_is_refused():
    with pytest.raises(ValueError, match="explicit integer"):
        derive(None)


def test_unknown_subsystem_is_refused_rather_than_borrowed():
    with pytest.raises(KeyError):
        generator(1, "not_a_subsystem")
    with pytest.raises(KeyError):
        derive(1, 0).for_subsystem("not_a_subsystem")


# -- design and cases ----------------------------------------------------


def test_factorial_size_is_the_product_of_levels():
    design = Design([Factor("a", [1, 2, 3]), Factor("b", ["x", "y"])],
                    replicates=2)
    assert len(design.cells()) == 6
    assert design.size() == 12


def test_one_at_a_time_is_linear_in_factors():
    design = Design([Factor("a", [1, 2, 3]), Factor("b", [10, 20, 30])],
                    kind=Design.OAT)
    # centre, plus two off-centre levels per factor.
    assert len(design.cells()) == 5


def test_case_id_is_content_derived_not_positional():
    """Otherwise a resumed sweep pairs new parameters with old results."""
    seeds = derive(1, 0)
    a = Case({"wind_speed": 10.0}, 0, seeds)
    b = Case({"wind_speed": 10.0}, 0, seeds)
    c = Case({"wind_speed": 20.0}, 0, seeds)
    d = Case({"wind_speed": 10.0}, 1, derive(1, 1))
    assert a.case_id == b.case_id
    assert a.case_id != c.case_id
    assert a.case_id != d.case_id


def test_case_applies_overrides_and_its_seed_to_the_spec():
    base = compile_prompt("fly the 747 at 3000 m and 250 kt")
    case = Case({"altitude": 5000.0}, 2, derive(77, 2))
    spec = case.apply_to(base)
    assert spec.altitude.value == 5000.0
    assert spec.seed.value == case.seeds.for_subsystem("turbulence")
    assert base.altitude.value == 3000.0        # base untouched


# -- the crash-safe log --------------------------------------------------


def test_log_survives_a_truncated_final_line(tmp_path):
    """A process killed mid-append leaves a partial line."""
    path = tmp_path / "dataset.jsonl"
    path.write_text('{"case_id": "aaa", "ok": true}\n'
                    '{"case_id": "bbb", "ok": true}\n'
                    '{"case_id": "ccc", "ok"')
    log = ResultLog(path)
    assert log.completed_ids() == {"aaa", "bbb"}
    assert len(log.rows()) == 2


def test_sweep_resumes_and_does_not_recompute(tmp_path):
    design = Design([Factor("wind_speed", [0.0, 10.0, 20.0])], replicates=2)
    base = compile_prompt("fly the 747 at 3000 m and 250 kt")
    calls = []

    def evaluate(spec, case):
        calls.append(case.case_id)
        return {"metric": len(calls)}

    first = run_sweep(design, base, evaluate, tmp_path, resume=False)
    assert first.completed == design.size()
    before = len(calls)

    second = run_sweep(design, base, evaluate, tmp_path, resume=True)
    assert second.skipped == design.size()
    assert second.completed == 0
    assert len(calls) == before, "a resumed sweep recomputed completed cases"


def test_failed_cases_are_recorded_not_dropped(tmp_path):
    """A sweep that omits its failures reports a 100% success rate."""
    design = Design([Factor("wind_speed", [0.0, 10.0])])
    base = compile_prompt("fly the 747 at 3000 m and 250 kt")

    def evaluate(spec, case):
        if spec.wind_speed.value == 10.0:
            raise RuntimeError("boom")
        return {"metric": 1.0}

    result = run_sweep(design, base, evaluate, tmp_path, resume=False)
    assert result.completed == 1 and result.failed == 1
    rows = result.rows
    assert len(rows) == 2
    failed = [r for r in rows if not r["ok"]]
    assert len(failed) == 1 and "boom" in failed[0]["error"]


def test_degenerate_replicates_are_detected():
    rows = [
        {"ok": True, "factor.a": 1, "metric": 5.0},
        {"ok": True, "factor.a": 1, "metric": 5.0},     # identical: degenerate
        {"ok": True, "factor.a": 2, "metric": 5.0},
        {"ok": True, "factor.a": 2, "metric": 7.0},     # varies: informative
    ]
    degenerate = degenerate_replicates(rows, ["metric"])
    assert len(degenerate) == 1
    assert degenerate[0]["factors"] == {"factor.a": 1}


# -- analysis ------------------------------------------------------------


def test_eta_squared_is_one_when_groups_fully_separate():
    assert eta_squared([[1.0, 1.0], [5.0, 5.0]]) == pytest.approx(1.0)


def test_eta_squared_is_zero_when_groups_are_identical():
    assert eta_squared([[1.0, 5.0], [1.0, 5.0]]) == pytest.approx(0.0)


def test_eta_squared_is_nan_when_there_is_no_variance():
    """No variance to explain means the question has no answer."""
    assert math.isnan(eta_squared([[3.0, 3.0], [3.0, 3.0]]))


def test_stdev_of_one_sample_is_nan_not_zero():
    """Zero reads as 'no spread'; NaN reads as 'spread not measurable'."""
    assert math.isnan(stdev([4.0]))
    assert stdev([1.0, 3.0]) == pytest.approx(math.sqrt(2.0))


def test_response_curve_carries_dispersion_and_n():
    rows = [{"ok": True, "factor.w": w, "m": m}
            for w, m in [(0, 1.0), (0, 3.0), (10, 5.0), (10, 7.0)]]
    curve = response_curve(rows, "w", "m")
    assert [l.level for l in curve.levels] == [0, 10]
    assert all(l.n == 2 for l in curve.levels)
    assert all(not math.isnan(l.stdev) for l in curve.levels)


def test_analysis_ranks_by_variance_explained():
    rows = []
    for strong in (0, 1):
        for weak in (0, 1):
            for replicate in range(3):
                rows.append({"ok": True, "factor.strong": strong,
                             "factor.weak": weak,
                             "m": strong * 100.0 + weak * 0.1 + replicate * 0.01})
    curves = analyse(rows, ["m"])
    assert curves[0].factor == "strong"


def test_replicate_precision_reports_n_and_half_width():
    rows = [{"ok": True, "m": v} for v in (1.0, 1.1, 0.9, 1.05, 0.95)]
    result = replicate_precision(rows, "m")
    assert result["n"] == 5
    assert result["half_width"] > 0
    assert "multiplier" in result


# -- manifest ------------------------------------------------------------


def test_manifest_records_inputs_outputs_and_git(tmp_path):
    payload = tmp_path / "dataset.jsonl"
    payload.write_text('{"case_id": "a"}\n')
    manifest = RunManifest(name="test")
    manifest.add_input_text("spec", "hello").add_output("dataset", payload)
    data = manifest.write(tmp_path / "manifest.json")
    recorded = json.loads(data.read_text())
    assert recorded["inputs"]["spec"] == sha256_text("hello")
    assert "commit" in recorded["git"]
    assert recorded["host"]["jsbsim"]
    assert recorded["reproducibility"].startswith("bit-identical")


def test_verify_reproduction_detects_a_changed_output(tmp_path):
    """A manifest nobody has reproduced from is an assertion."""
    payload = tmp_path / "dataset.jsonl"
    payload.write_text("original\n")
    manifest = RunManifest(name="test").add_output("dataset", payload)
    path = manifest.write(tmp_path / "manifest.json")

    from core.experiments.manifest import sha256_file
    assert verify_reproduction(path, {"dataset": sha256_file(payload)})["ok"]

    payload.write_text("tampered\n")
    check = verify_reproduction(path, {"dataset": sha256_file(payload)})
    assert not check["ok"]
    assert check["mismatched"] == ["dataset"]

    missing = verify_reproduction(path, {})
    assert not missing["ok"] and missing["missing"] == ["dataset"]


def test_not_resuming_starts_fresh_rather_than_appending(tmp_path):
    """`resume=False` must discard the old dataset, not append to it.

    Otherwise a re-run leaves stale rows in the log, and because analysis
    groups by factor level rather than row position they are folded silently
    into every mean. Measured before the fix: an 18-case design re-run produced
    a 32-row dataset that still looked plausible.
    """
    design = Design([Factor("wind_speed", [0.0, 10.0, 20.0])], replicates=2)
    base = compile_prompt("fly the 747 at 3000 m and 250 kt")

    def evaluate(spec, case):
        return {"metric": 1.0}

    first = run_sweep(design, base, evaluate, tmp_path, resume=False)
    assert len(first.rows) == design.size()

    second = run_sweep(design, base, evaluate, tmp_path, resume=False)
    assert len(second.rows) == design.size(), "stale rows accumulated"
    assert second.duplicate_case_ids() == []
