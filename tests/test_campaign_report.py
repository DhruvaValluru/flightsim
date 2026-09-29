"""R3: the campaign report at record 2 -- the variables, uncertainty and
instruments blocks over a two-case headless campaign, every number
checked against the cases' own files read here with json.

The campaign is the campaign tests' prompt at a two-second flight, its
compiled spec given the ISA deviation as a user edit (the prompt compiler
has no atmosphere phrase) so a numeric, user-sourced variable with a null
pair travels through the report, and each case asked for its null pairs
and its dt/2 twin (the capture options null_tests and uncertainty).
"""

import json
import statistics
from pathlib import Path

import numpy as np
import pytest

from core.campaign import Campaign
from core.campaign.campaign import DONE
from core.campaign.report import (
    NULL_VERDICTS, REPORT_RECORD_VERSION, render_report, uncertainty_summary,
    variables_block,
)
from core.records import RECORD_VERSION
from core.scenario.spec import ScenarioSpec

PROMPT = ("fly the a320 at 3000 m for 2 seconds in varied weather at "
          "different times of day, chase view")
ISA_DEVIATION_C = 10.0
VARIABLE = "atmosphere.temperature_deviation_c"


def two_case_campaign(out: Path) -> Campaign:
    """A two-case headless campaign (2 s flights, null pairs and dt/2
    twins flown) whose spec states the ISA deviation as a user edit.
    Shared with tests/test_datasheet.py (imported, run once per module)."""
    c = Campaign.create(PROMPT, images=30, seed=7, out=out, workers=1, stall_seconds=120,
                        capture={"null_tests": True, "uncertainty": True})
    spec = ScenarioSpec.from_dict(c.record["spec"])
    spec.set(VARIABLE, ISA_DEVIATION_C, frm="the test's user edit: a warm day")
    c.record["spec"] = spec.to_dict()
    c.record["spec_digest"] = spec.digest()
    c._save()
    status = c.run(workers=1, progress=lambda line: None)
    assert status["state"] == DONE, status
    return c


def case_dirs(campaign: Campaign):
    return sorted(campaign.verified_run_dirs())


def manifest_records(run_dir: Path):
    manifest = json.loads((run_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    return {r["name"]: r for r in manifest["applied_variables"]["applied_variables"]}


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    return two_case_campaign(tmp_path_factory.mktemp("report") / "c")


@pytest.fixture(scope="module")
def report(campaign):
    return campaign.report()


def test_the_report_states_record_version_2_the_record_constant(campaign, report):
    """R-REC-04: report.json says record_version 2 (the blocks it carries),
    which since the INT-final bump IS core.records.RECORD_VERSION."""
    assert REPORT_RECORD_VERSION == RECORD_VERSION == 2
    assert report["record_version"] == 2
    written = json.loads((campaign.dir / "report.json").read_text(encoding="utf-8"))
    assert written["record_version"] == 2
    assert set(written) >= {"variables", "uncertainty", "instruments"}
    assert report["yield"]["verified_cases"] == 2 and len(case_dirs(campaign)) == 2


def test_the_variables_block_is_the_cases_own_records(campaign, report):
    """R-REC-04: n, min, max, mean, sd, hist, sources, null verdicts and the
    null effect's median / p95 per variable, recomputed here from the two
    capture manifests."""
    dirs = case_dirs(campaign)
    per_case = [manifest_records(d) for d in dirs]
    variables = report["variables"]
    assert set(variables) == set().union(*per_case)
    v = variables[VARIABLE]
    assert v["kind"] == "numeric" and v["n"] == 2 and v["runs_without"] == 0
    assert v["min"] == v["max"] == v["mean"] == ISA_DEVIATION_C and v["sd"] == 0.0
    assert sum(v["hist"]["counts"]) == 2 and v["unit"] == per_case[0][VARIABLE]["unit"]
    assert v["sources"] == {"user": 2}
    # The null pair's verdict and effect, from each case's record.
    verdicts = [r[VARIABLE]["null_test"]["verdict"] for r in per_case]
    assert v["null_verdicts"] == {w: verdicts.count(w) for w in set(verdicts)}
    effects = [abs(r[VARIABLE]["null_test"]["with"] - r[VARIABLE]["null_test"]["without"])
               for r in per_case]
    assert v["effect_median"] == pytest.approx(statistics.median(effects), rel=1e-12)
    assert v["effect_p95"] == pytest.approx(float(np.percentile(effects, 95)), rel=1e-12)
    assert v["effect_unit"] == per_case[0][VARIABLE]["null_test"]["unit"]
    # Every variable's verdicts are named words and account for every case.
    for name, block in variables.items():
        assert set(block["null_verdicts"]) <= set(NULL_VERDICTS), name
        assert sum(block["null_verdicts"].values()) == block["n"], name
        assert sum(block["sources"].values()) == block["n"], name
    # A non-number is counted per value; a null-with-basis is counted as null.
    profile = variables["instruments.profile"]
    assert profile["kind"] == "categorical"
    assert profile["hist"]["values"] == {"ideal": 2} and profile["min"] is None
    # The function over the same directories says the same as the report.
    assert variables_block(dirs) == variables


def test_the_uncertainty_block_summarises_each_cases_twin(campaign, report):
    """R-REC-04: u_num per SRQ, u_input per variable and u_val over the
    cases, each case's value read here from its run.json."""
    u = report["uncertainty"]
    assert u["runs_with"] == 2 and u["runs_without"] == []
    assert u["form"] == ["ASME V&V 20; u_D absent per run"]
    runs = [json.loads((d / "run.json").read_text(encoding="utf-8"))["uncertainty"]
            for d in case_dirs(campaign)]
    for srq, block in u["u_num"].items():
        values = [r["u_num"]["srq"][srq]["value"] for r in runs]
        assert block["n"] == 2 and block["median"] == pytest.approx(statistics.median(values))
        assert block["min"] == min(values) and block["max"] == max(values)
    assert set(u["u_num"]) >= {"altitude_m", "north_m", "east_m", "tas_kt"}
    assert VARIABLE in u["u_input"] and u["u_input"][VARIABLE]["n"] == 2
    assert u["u_input"][VARIABLE]["max"] == 0.0          # user-stated, no tolerance: u_x 0
    assert u["u_val"]["altitude_m"]["n"] == 2


def test_a_case_without_the_twin_is_named_not_summarised(campaign, tmp_path):
    """R-REC-04: a case that flew no twin is listed by name; with none, the
    block says NOT RUN rather than zero."""
    import shutil

    source = case_dirs(campaign)[0]
    bare = tmp_path / "bare"
    shutil.copytree(source, bare)
    for name in ("run.json", "capture_manifest.json"):
        data = json.loads((bare / name).read_text(encoding="utf-8"))
        data.pop("uncertainty", None)
        (bare / name).write_text(json.dumps(data), encoding="utf-8")
    alone = uncertainty_summary([bare])
    assert alone["runs_with"] == 0 and alone["runs_without"] == ["bare"]
    assert alone["status"].startswith("NOT RUN") and alone["u_num"] == {}
    mixed = uncertainty_summary([source, bare])
    assert mixed["runs_with"] == 1 and mixed["runs_without"] == ["bare"]
    assert mixed["u_num"]["altitude_m"]["n"] == 1


def test_the_instruments_block_reads_each_cases_block(campaign, report):
    """R-REC-04: profiles, seeds, rate, rate basis and the Allan self-report
    over the cases, from each case's instruments block (R2)."""
    inst = report["instruments"]
    runs = {d.name: json.loads((d / "run.json").read_text(encoding="utf-8"))
            for d in case_dirs(campaign)}
    assert inst["runs"] == 2 and inst["runs_without"] == []
    blocks = {name: r.get("instruments") for name, r in runs.items()}
    if all(isinstance(b, dict) for b in blocks.values()):
        assert inst["sources"] == {"run.json instruments block": 2}
        assert inst["rate_basis"] == {str(next(iter(blocks.values()))["rate_basis"]): 2}
        for name, block in blocks.items():
            assert inst["seeds"][name]["experiment_seed"] == block["seeds"]["experiment_seed"]
        for instrument, profile in next(iter(blocks.values()))["profiles"].items():
            assert inst["profiles"][instrument] == {profile["name"]: 2}
    else:   # the recorded-rate record, when the case carries no block
        assert "instruments.profile record (recorded-rate path)" in inst["sources"]
    for channel, entry in inst["allan_self_report"].items():
        assert sum(entry["white_term"].values()) == entry["runs"], channel


def test_the_report_in_words_names_the_record_2_blocks(report):
    """R-REC-04: the words carry the variables, the uncertainty and the
    instruments lines."""
    words = render_report(report)
    assert f"{VARIABLE}: n 2" in words
    assert "uncertainty: summarised over 2 of 2 case(s)" in words
    assert "instruments: rate basis" in words


def test_the_card_carries_the_same_blocks_as_the_report(campaign, report):
    """R-REC-04: the campaign's dataset card states record_version 2 and
    carries the report's variables, uncertainty and instruments blocks over
    the same cases, plus a datasheet."""
    card = campaign.export("coco")["card"]
    assert card["record_version"] == 2
    assert card["variables"] == report["variables"]
    assert card["uncertainty"] == report["uncertainty"]
    assert card["instruments"] == report["instruments"]
    assert "sections" in card["datasheet"] and card["tabular"] is None
