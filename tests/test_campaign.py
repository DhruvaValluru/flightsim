"""Phase 2, package G: campaign execution at scale (contracts §6.1).

A campaign is a prompt, a target and a seed run as content-addressed
cases by workers that pull slots BY INDEX; every draw is seeded from
``SeedSequence([index, campaign_seed])`` so the case set is the same
at any worker count -- the plan's exit criterion, measured here with
one and two spawned workers over the real headless pipeline. Progress
is computed from the ledger; a campaign never reports done below its
target; the disk budget, an exhausted slot and an illegal transition
refuse by name; pause and cancel go through control.json.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from core.campaign import STATES, TRANSITIONS, Campaign, CampaignError
from core.campaign.campaign import (
    CANCELLED, DONE, FAILED, MAX_ATTEMPTS, PAUSED, PLANNED, RUNNING,
    estimate_frames,
)
from core.campaign.ledger import STATUSES, Ledger, comparable, summarise
from core.campaign.report import render_report
from core.campaign.workers import (
    build_case, case_seed, run_with_watchdog, sampled_values,
)
from core.scenario.randomization import MAX_SEED
from core.scenario.spec import ScenarioSpec

PROMPT = ("fly the a320 at 3000 m for 10 seconds in varied weather at "
          "different times of day, chase view")
#: Three cases of ~96 frames each (one continuous camera over 10 s at
#: the recorder's 0.1 s cadence); the estimate says 101 per case, the
#: measured count decides the second round if there is one.
IMAGES = 250


# -- fakes the worker can name (module-level, importable by a spawned process)

def failing_capture(command, log, run_dir, stall_seconds):
    Path(log).write_text("the test broke this capture\n", encoding="utf-8")
    return 1, False


# -- fixtures ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def campaigns(tmp_path_factory):
    """The same campaign run with one worker and with two spawned
    workers: the exit-criterion measurement (real headless captures,
    no engine, no previews)."""
    root = tmp_path_factory.mktemp("campaigns")
    out = {}
    for workers in (1, 2):
        c = Campaign.create(PROMPT, images=IMAGES, seed=7, out=root / f"w{workers}",
                            workers=workers, stall_seconds=120)
        status = c.run(workers=workers, progress=lambda line: None)
        assert status["state"] == DONE, status
        out[workers] = c
    return out


# -- the state machine -----------------------------------------------------------------

def test_the_state_machine_admits_only_the_documented_transitions(tmp_path):
    assert set(TRANSITIONS) == set(STATES)
    assert TRANSITIONS[DONE] == frozenset() and TRANSITIONS[CANCELLED] == frozenset()
    assert RUNNING in TRANSITIONS[PLANNED] and RUNNING in TRANSITIONS[PAUSED]
    assert RUNNING in TRANSITIONS[FAILED] and DONE not in TRANSITIONS[PLANNED]
    c = Campaign.create(PROMPT, images=10, out=tmp_path / "c")
    assert c.state == PLANNED
    for illegal in (PAUSED, DONE, FAILED):
        with pytest.raises(CampaignError) as err:
            c._transition(illegal)
        assert err.value.constraint == "campaign.state"
    c._transition(RUNNING)
    c._transition(PAUSED)
    with pytest.raises(CampaignError):
        c.pause()                                   # only running can pause
    c._transition(RUNNING)
    c._transition(DONE)
    for illegal in STATES:
        with pytest.raises(CampaignError) as err:
            c._transition(illegal)
        assert err.value.constraint == "campaign.state"
    with pytest.raises(CampaignError) as err:
        c.resume()
    assert err.value.constraint == "campaign.state"
    # The record on disk says the same as the object.
    assert Campaign.open(tmp_path / "c").state == DONE
    # A planned campaign cancels here and now; a cancelled one is terminal.
    d = Campaign.create(PROMPT, images=10, out=tmp_path / "d")
    assert d.cancel()["state"] == CANCELLED
    with pytest.raises(CampaignError):
        d.run()


def test_create_and_plan_refuse_by_name_before_anything_runs(tmp_path):
    for kwargs, name in (
            ({"images": 0}, "campaign.arguments"),
            ({"images": 5, "workers": 0}, "campaign.arguments"),
            ({"images": 5, "seed": 0}, "campaign.arguments"),
            ({"images": 5, "seed": MAX_SEED + 1}, "campaign.arguments"),
            ({"images": 5, "format": "parquet"}, "export.format"),
            ({"images": 5, "tier": "oracle"}, "campaign.arguments"),
            ({"images": 5, "capture": {"laser": True}}, "campaign.arguments"),
            ({"images": 5, "disk_budget_bytes": 0}, "campaign.arguments")):
        with pytest.raises(CampaignError) as err:
            Campaign.create(PROMPT, out=tmp_path / "x", **kwargs)
        assert err.value.constraint == name, kwargs
        assert not (tmp_path / "x").exists()
    c = Campaign.create(PROMPT, images=5, out=tmp_path / "y")
    with pytest.raises(CampaignError) as err:
        Campaign.create(PROMPT, images=5, out=tmp_path / "y")   # already a campaign
    assert err.value.constraint == "campaign.arguments"
    with pytest.raises(CampaignError) as err:
        Campaign.open(tmp_path / "nowhere")
    assert err.value.constraint == "campaign.arguments"
    # A policy defect is refused by the sampler's name at plan time.
    v = Campaign.create("fly the 747 for 10 seconds and vary the moon phase",
                        images=5, out=tmp_path / "v")
    with pytest.raises(CampaignError) as err:
        v.plan()
    assert err.value.constraint == "randomization.vocabulary"
    assert Campaign.open(tmp_path / "v").state == PLANNED
    r = Campaign.create("fly the 747 across the rockies for 10 seconds",
                        images=5, out=tmp_path / "r")
    with pytest.raises(CampaignError) as err:
        r.plan()
    assert err.value.constraint == "randomization.location"
    # A spec that cannot fly is refused by the validator's own name.
    s = Campaign.create("fly the 747 at 10000 ft and 40 kt for 10 seconds",
                        images=5, out=tmp_path / "s")
    with pytest.raises(CampaignError) as err:
        s.plan()
    assert err.value.constraint.startswith("airspeed.")
    # A good plan records its estimate and the seed derivation.
    plan = c.plan()
    assert plan["cases_needed"] == 1 and plan["frames_per_case"]["measured"] is None
    assert plan["frames_per_case"]["estimate"] == estimate_frames(ScenarioSpec.from_dict(c.record["spec"]))
    assert plan["seed_derivation"] == "SeedSequence([index, campaign_seed])"
    assert plan["disk"]["within_budget"] is None          # unmeasured: no claim
    assert json.loads((tmp_path / "y" / "campaign.json").read_text(encoding="utf-8"))["plan"] == plan


# -- seeds by index -------------------------------------------------------------------------

def test_cases_are_seeded_by_index_and_identical_in_any_process(tmp_path):
    c = Campaign.create(PROMPT, images=IMAGES, seed=7, out=tmp_path / "c")
    # The verifier re-implements the derivation rather than importing it.
    for index in (0, 1, 2, 17):
        expected = 1 + int(np.random.SeedSequence(entropy=[index, 7])
                           .generate_state(1, dtype=np.uint64)[0]) % MAX_SEED
        assert case_seed(index, 7) == expected
    a, seed_a = build_case(1, c.record)
    b, seed_b = build_case(1, c.record)
    other, _ = build_case(2, c.record)
    assert a.digest() == b.digest() and seed_a == seed_b == case_seed(1, 7)
    assert a.digest() != other.digest()
    assert sampled_values(a) == sampled_values(b) and sampled_values(a) != sampled_values(other)
    assert set(sampled_values(a)) == {"cloud_cover", "visibility_km", "precipitation", "hour_local"}
    assert str(a.seed.source) == "derived" and "SeedSequence" in a.seed.frm
    assert int(a.randomization.seed.value) == 7          # the block's seed IS the campaign seed
    draws = a.randomization.policy_draws.value
    assert draws["draw_index"] == 1 and draws["campaign_seed"] == 7
    # A stated run seed is never moved.
    spec = ScenarioSpec.from_dict(c.record["spec"])
    spec.set("seed", 5, frm="stated in the test")
    stated = dict(c.record, spec=spec.to_dict())
    kept, seed = build_case(3, stated)
    assert seed == 5 and int(kept.seed.value) == 5 and str(kept.seed.source) == "user"


def test_sample_previews_slots_by_name_and_never_regresses_a_row(tmp_path):
    c = Campaign.create(PROMPT, images=IMAGES, seed=7, out=tmp_path / "c")
    drawn = c.sample(2)
    assert [x["index"] for x in drawn["cases"]] == [0, 1] and drawn["refused"] == []
    rows = c.ledger.rows()
    assert [r["status"] for r in rows] == ["sampled", "sampled"]
    assert drawn["cases"][0]["case_id"] == build_case(0, c.record)[0].digest()[:16]
    # A verified row is never overwritten by a later preview.
    c.ledger.append({"index": 0, "status": "verified", "case_id": rows[0]["case_id"],
                     "ok": True, "verified": True, "frames": 9, "yield": 9})
    c.sample(2, start=0)
    latest = c.ledger.latest()
    assert latest[0]["status"] == "verified" and latest[1]["status"] == "sampled"
    assert c.status()["frames_verified"] == 9
    assert c.sample(1, start=5, record=False)["cases"][0]["index"] == 5
    assert 5 not in c.ledger.latest()


# -- never done below target ------------------------------------------------------------------

def test_a_campaign_never_reports_done_below_target(tmp_path):
    c = Campaign.create(PROMPT, images=IMAGES, seed=7, out=tmp_path / "c",
                        stall_seconds=None)
    with pytest.raises(CampaignError) as err:
        c.run(workers=1, capture_runner="tests.test_campaign:failing_capture")
    assert err.value.constraint == "campaign.target_unreachable"
    assert "failed capture" in err.value.message
    fresh = Campaign.open(tmp_path / "c")
    assert fresh.state == FAILED
    assert fresh.record["reason"].startswith("campaign.target_unreachable")
    status = fresh.status()
    assert status["frames_verified"] == 0 and status["cases"]["verified"] == 0
    latest = fresh.ledger.latest()
    assert {r["status"] for r in latest.values()} == {"failed"}
    assert {r["attempt"] for r in latest.values()} == {MAX_ATTEMPTS}   # retried once, then left
    assert all(r["ok"] is False and r["capture_exit"] == 1 for r in latest.values())
    assert all("broke" in Path(r["run_dir"], "capture.log").read_text(encoding="utf-8") for r in latest.values())
    # Every dispatch is a row: sampled nothing, running then failed per attempt.
    statuses = [r["status"] for r in fresh.ledger.rows()]
    assert statuses.count("running") == statuses.count("failed") == 2 * len(latest)
    report = fresh.report()
    assert report["state"] == FAILED and report["yield"]["frames_verified"] == 0
    assert "failed" in render_report(report)


def test_progress_is_computed_from_the_ledger_a_restarted_process_reports_the_truth(tmp_path):
    c = Campaign.create(PROMPT, images=100, seed=7, out=tmp_path / "c")
    ledger = Ledger(tmp_path / "c" / "ledger.jsonl")
    ledger.append({"index": 0, "status": "running", "attempt": 1})
    ledger.append({"index": 0, "status": "verified", "case_id": "a" * 16, "run_dir": "x",
                   "ok": True, "verified": True, "frames": 40, "yield": 40, "bytes": 1000,
                   "refusals": ["randomization.sun_elevation_min_deg"], "wall_seconds": 1.5})
    ledger.append({"index": 1, "status": "refused", "refusals": ["randomization.infeasible"],
                   "ok": False, "verified": False, "frames": 0, "yield": 0})
    ledger.append({"index": 2, "status": "rendered", "case_id": "b" * 16,
                   "ok": True, "verified": False, "frames": 40, "yield": 0, "bytes": 3000})
    ledger.append({"index": 3, "status": "failed", "attempt": 1,
                   "ok": False, "verified": False, "frames": 0, "yield": 0})
    with (tmp_path / "c" / "ledger.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"index": 4, "status": "verified", "yield": 99')   # killed mid-write
    # Not the object that wrote it: a fresh open, nothing in memory.
    fresh = Campaign.open(tmp_path / "c")
    status = fresh.status()
    assert status["frames_verified"] == 40 and status["frames_captured"] == 80
    assert status["cases"] == {"sampled": 0, "refused": 1, "running": 0, "rendered": 1,
                               "verified": 1, "failed": 1}
    assert status["indices"] == 4 and status["fraction"] == 0.4
    assert status["refusals"] == {"randomization.infeasible": 1,
                                  "randomization.sun_elevation_min_deg": 1}
    summary = summarise(fresh.ledger.rows())
    assert summary["next_index"] == 4 and summary["bytes_per_case"] == 2000
    assert summary["failed_captures"] == 1 and summary["unverified"] == 1
    report = fresh.report()
    assert report["yield"]["frames_verified"] == 40
    assert report["refusals"]["slots"] == {"randomization.infeasible": 1}
    assert report["refusals"]["attempts_within_draws"] == {"randomization.sun_elevation_min_deg": 1}
    assert (tmp_path / "c" / "report.json").is_file()
    words = render_report(report)
    assert "40 verified frame(s) of 100" in words and "1 refused" in words
    # The plan built on that ledger measures 40 frames per case and needs 2 more.
    plan = fresh.plan()
    assert plan["frames_per_case"]["measured"] == 40 and plan["cases_needed"] == 2
    assert plan["disk"]["projected_bytes"] == 4000 and plan["disk"]["within_budget"] is True


# -- the disk budget ---------------------------------------------------------------------------

def test_the_disk_budget_is_refused_by_name_once_measured_and_again_before_a_resume(tmp_path):
    c = Campaign.create(PROMPT, images=IMAGES, seed=7, out=tmp_path / "c",
                        disk_budget_bytes=1_000_000, stall_seconds=120)
    with pytest.raises(CampaignError) as err:
        c.run(workers=1)
    assert err.value.constraint == "storage.budget_exceeded"
    assert "the stated budget" in err.value.message
    assert err.value.detail["projected_bytes"] > 1_000_000
    fresh = Campaign.open(tmp_path / "c")
    assert fresh.state == FAILED and fresh.record["reason"].startswith("storage.budget_exceeded")
    latest = fresh.ledger.latest()
    assert len(latest) == 1 and latest[0]["status"] == "verified"   # measured from ONE case
    rows_before = len(fresh.ledger.rows())
    # Resume: refused before any case starts, from the measured rows.
    with pytest.raises(CampaignError) as err:
        fresh.resume(workers=1)
    assert err.value.constraint == "storage.budget_exceeded"
    assert len(fresh.ledger.rows()) == rows_before
    assert fresh.plan()["disk"]["within_budget"] is False
    # Lift the budget: the same ledger resumes to done with the same cases.
    fresh.record["disk_budget_bytes"] = None
    fresh._save()
    status = fresh.resume(workers=1)
    assert status["state"] == DONE and status["cases"]["verified"] == 3


# -- the watchdog ------------------------------------------------------------------------------------

def test_the_watchdog_kills_a_silent_capture_and_spares_one_that_writes(tmp_path):
    silent = [sys.executable, "-c", "import time; time.sleep(30)"]
    started = time.monotonic()
    code, stalled = run_with_watchdog(silent, tmp_path / "silent.log", tmp_path, 0.6)
    assert stalled and code != 0 and time.monotonic() - started < 10
    busy = [sys.executable, "-c",
            "import time, pathlib, sys\n"
            "p = pathlib.Path(sys.argv[1])\n"
            "for i in range(8):\n"
            "    p.write_text(str(i), encoding='utf-8'); time.sleep(0.25)\n",
            str(tmp_path / "heartbeat.txt")]
    code, stalled = run_with_watchdog(busy, tmp_path / "busy.log", tmp_path, 0.6)
    assert (code, stalled) == (0, False)
    code, stalled = run_with_watchdog([sys.executable, "-c", "print('hi')"],
                                      tmp_path / "off.log", tmp_path, None)
    assert (code, stalled) == (0, False)


# -- pause / cancel ----------------------------------------------------------------------------------

def test_pause_and_cancel_are_honoured_between_cases_through_control_json(tmp_path, campaigns):
    out = tmp_path / "p"
    c = Campaign.create(PROMPT, images=IMAGES, seed=7, out=out, stall_seconds=120)
    seen = []

    def after_first(line):
        seen.append(line)
        if len(seen) == 1:
            c.pause()                        # the UI/CLI writes control.json

    status = c.run(workers=1, progress=after_first)
    assert status["state"] == PAUSED and status["cases"]["verified"] == 1
    assert not (out / "control.json").exists()
    with pytest.raises(CampaignError) as err:
        c.pause()                            # not running any more
    assert err.value.constraint == "campaign.state"
    resumed = c.resume(workers=1)
    assert resumed["state"] == DONE and resumed["cases"]["verified"] == 3
    # The same cases as the uninterrupted campaign: pausing moved nothing.
    reference = campaigns[1].ledger.latest()
    assert {r["case_id"] for r in c.ledger.latest().values()} == \
        {r["case_id"] for r in reference.values()}
    with pytest.raises(CampaignError):
        c.cancel()                           # done is terminal
    # Cancel between cases.
    d = Campaign.create(PROMPT, images=IMAGES, seed=7, out=tmp_path / "d", stall_seconds=120)
    calls = []

    def cancel_first(line):
        calls.append(line)
        if len(calls) == 1:
            d.cancel()

    status = d.run(workers=1, progress=cancel_first)
    assert status["state"] == CANCELLED and status["cases"]["verified"] == 1
    with pytest.raises(CampaignError):
        d.resume()


# -- the exit criterion: determinism across worker counts ---------------------------------

def test_the_same_campaign_at_one_and_two_workers_is_identical(campaigns):
    one, two = campaigns[1], campaigns[2]
    assert one.record["workers"] == 1 and two.record["workers"] == 2
    a, b = one.ledger.latest(), two.ledger.latest()
    assert sorted(a) == sorted(b) == [0, 1, 2]
    assert [a[i]["case_id"] for i in sorted(a)] == [b[i]["case_id"] for i in sorted(b)]
    assert [a[i]["seed"] for i in sorted(a)] == [b[i]["seed"] for i in sorted(b)]
    assert [a[i]["sampled"] for i in sorted(a)] == [b[i]["sampled"] for i in sorted(b)]
    assert len({a[i]["case_id"] for i in a}) == 3          # three distinct specs
    for i in a:
        ma = json.loads(Path(a[i]["run_dir"], "capture_manifest.json").read_text(encoding="utf-8"))
        mb = json.loads(Path(b[i]["run_dir"], "capture_manifest.json").read_text(encoding="utf-8"))
        assert ma["spec_digest"] == mb["spec_digest"] == a[i]["spec_digest"]
        assert ma["simulation_digest"] == mb["simulation_digest"] == a[i]["simulation_digest"]
        assert ma["output_digest"] == mb["output_digest"] == a[i]["output_digest"]
        assert ma["randomization"] == mb["randomization"]
        assert ma["randomization"]["policy_draws"]["draw_index"] == i
        assert ma["randomization"]["policy_draws"]["campaign_seed"] == 7
        assert a[i]["seed_derivation"].startswith("SeedSequence(entropy=[index, campaign_seed])")
    # The whole ledger, apart from timing and machine paths.
    assert comparable(one.ledger.rows()) == comparable(two.ledger.rows())
    # Rows were appended in completion order in the pool: the raw files
    # may differ, the comparable rows do not.
    assert one.status()["frames_verified"] == two.status()["frames_verified"] >= IMAGES
    assert one.state == two.state == DONE


def test_the_report_and_the_export_read_the_verified_cases(campaigns):
    c = campaigns[1]
    report = c.report()
    assert report["state"] == DONE and report["yield"]["frames_verified"] >= IMAGES
    assert report["yield"]["verified_cases"] == 3 and report["yield"]["drawn_cases"] == 0
    assert report["realised"]["runs"] == 3 and report["coverage"] is not None
    assert set(report["realised"]["fields"]) >= {"cloud_cover", "hour_local",
                                                  "precipitation", "visibility_km"}
    assert report["refusals"]["slots"] == {}
    assert report["timing"]["case_wall_seconds_mean"] > 0
    assert report["disk"]["bytes_per_case"] > 0 and report["disk"]["measured_over"] == 3
    words = render_report(report)
    assert "done" in words and "coverage:" in words and "not claimed" in words
    written = json.loads((c.dir / "report.json").read_text(encoding="utf-8"))
    assert written["yield"] == report["yield"]
    result = c.export("coco")
    assert result["labels_only"] is True and result["runs"] == 3
    assert Path(result["dataset_path"], "annotations", "instances_train.json").is_file()
    assert len(result["card"]["runs"]) == 3 and result["card"]["frames"] >= IMAGES
    assert all(r["verification"]["status"] == "passed" for r in result["card"]["runs"])


def test_a_prompt_with_nothing_to_vary_refuses_duplicate_slots_by_name(tmp_path):
    c = Campaign.create("fly the 747 at 10000 ft for 10 seconds, chase view",
                        images=150, seed=3, out=tmp_path / "c", stall_seconds=120,
                        max_refused_slots=2)
    spec = ScenarioSpec.from_dict(c.record["spec"])
    spec.set("seed", 5, frm="stated by the test")      # a stated seed, no policy
    c.record["spec"] = spec.to_dict()
    c._save()
    with pytest.raises(CampaignError) as err:
        c.run(workers=1)
    assert err.value.constraint == "campaign.target_unreachable"
    assert "campaign.duplicate_case" in err.value.message
    latest = Campaign.open(tmp_path / "c").ledger.latest()
    assert latest[0]["status"] == "verified"
    dupes = [r for r in latest.values() if r["status"] == "refused"]
    assert len(dupes) == 2 and all(r["refusals"] == ["campaign.duplicate_case"] for r in dupes)
    assert all(r["case_id"] == latest[0]["case_id"] for r in dupes)
    assert not any("run_dir" in r for r in dupes)        # refused before running


def test_duplicate_slots_are_refused_by_index_not_by_completion_order_at_two_workers(tmp_path):
    """The case the contract names (a stated seed, nothing to vary):
    slots 0 and 1 draw one spec and are dispatched together at two
    workers. The keeper is the LOWER INDEX, decided before slot 1 is
    handed to a worker, so slot 1 refuses itself before running (no run
    directory, no attempt) and the ledger is the one a single worker
    writes -- not whichever slot happened to return first."""
    prompt = "fly the 747 at 10000 ft for 10 seconds, chase view"
    ledgers = {}
    for workers in (1, 2):
        c = Campaign.create(prompt, images=150, seed=3, out=tmp_path / f"w{workers}",
                            stall_seconds=None, max_refused_slots=1)
        spec = ScenarioSpec.from_dict(c.record["spec"])
        spec.set("seed", 5, frm="stated by the test")      # a stated seed, no policy
        c.record["spec"] = spec.to_dict()
        c._save()
        with pytest.raises(CampaignError) as err:
            c.run(workers=workers, capture_runner="tests.test_campaign:failing_capture")
        assert err.value.constraint == "campaign.target_unreachable"
        assert "campaign.duplicate_case" in err.value.message
        latest = Campaign.open(tmp_path / f"w{workers}").ledger.latest()
        assert sorted(latest) == [0, 1]
        assert latest[0]["status"] == "failed", (workers, latest[0])      # the keeper ran
        assert latest[1]["status"] == "refused", (workers, latest[1])
        assert latest[1]["refusals"] == ["campaign.duplicate_case"]
        assert latest[1]["case_id"] == latest[0]["case_id"]
        assert "slot 0" in latest[1]["reason"]
        assert "run_dir" not in latest[1] and "capture_exit" not in latest[1]
        ledgers[workers] = c.ledger.rows()
    # The whole ledger apart from timing and machine paths (the failed
    # capture's error names its log by path).
    assert comparable(ledgers[1], drop=("error", "reason")) == \
        comparable(ledgers[2], drop=("error", "reason"))


def test_a_refused_slot_names_the_constraint_its_draws_hit(tmp_path):
    """A slot refused ``randomization.infeasible`` carries the constraint
    each of its draws hit; the campaign's totals, the unreachable
    message and the report name it too, so the person knows what to
    narrow the policy against -- not only that twenty draws failed."""
    c = Campaign.create("fly at 10000 ft and 280 kt for 60 seconds", images=100, seed=1,
                        out=tmp_path / "c", policy={"aircraft": {"choice": ["c172p"]}},
                        max_refused_slots=2, stall_seconds=None)
    with pytest.raises(CampaignError) as err:
        c.run(workers=1)
    assert err.value.constraint == "campaign.target_unreachable"
    assert "randomization.infeasible x2" in err.value.message
    assert "envelope.trim_feasible" in err.value.message
    assert "narrow the policy against envelope.trim_feasible" in err.value.message
    rows = list(c.ledger.latest().values())
    assert all(r["status"] == "refused" for r in rows) and len(rows) == 2
    hits = sum(len(r["refused_attempts"]) for r in rows)
    assert all(a["refusal_name"] == "envelope.trim_feasible"
               for r in rows for a in r["refused_attempts"])
    status = c.status()
    assert status["refusals"] == {"randomization.infeasible": 2}
    assert status["refused_attempt_names"] == {"envelope.trim_feasible": hits}
    summary = summarise(c.ledger.rows())
    assert summary["refused_attempt_names"] == {"envelope.trim_feasible": hits}
    report = c.report()
    assert report["refusals"]["slots"] == {"randomization.infeasible": 2}
    assert report["refusals"]["attempts_within_refused_slots"] == {"envelope.trim_feasible": hits}
    assert report["refusals"]["attempts_within_draws"] == {}
    words = render_report(report)
    assert f"envelope.trim_feasible x{hits}" in words and "narrow the policy" in words


# -- the CLI -------------------------------------------------------------------------------------

def test_the_campaign_cli_runs_reports_and_refuses_by_exit_code(tmp_path, capsys):
    from flightsim.campaign import main

    out = tmp_path / "cli"
    assert main([PROMPT, "--images", "0", "--out", str(out)]) == 2
    assert "REFUSED -- campaign.arguments" in capsys.readouterr().out
    assert main(["--out", str(out), "--status"]) == 2
    assert "REFUSED -- campaign.arguments" in capsys.readouterr().out
    assert main([PROMPT, "--images", str(IMAGES), "--seed", "7", "--out", str(out),
                 "--plan"]) == 0
    printed = capsys.readouterr().out
    assert "target 250 frame(s) ~ 3 case(s)" in printed and '"cases_needed": 3' in printed
    assert main(["--out", str(out), "--resume", "--workers", "1"]) == 0
    printed = capsys.readouterr().out
    assert "verified frames=96" in printed and "done" in printed
    assert main(["--out", str(out), "--status"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == DONE
    assert main(["--out", str(out), "--report"]) == 0
    printed = capsys.readouterr().out
    assert "coverage:" in printed and "written:" in printed
    assert main(["--out", str(out), "--pause"]) == 2          # done cannot pause
    assert "REFUSED -- campaign.state" in capsys.readouterr().out
    assert main(["--out", str(out), "--resume"]) == 2
    assert "REFUSED -- campaign.state" in capsys.readouterr().out
    # --sample previews without running; --cancel on a planned campaign.
    assert main([PROMPT, "--images", "10", "--out", str(tmp_path / "s"), "--sample", "2"]) == 0
    printed = capsys.readouterr().out
    assert "slot 0:" in printed and "slot 1:" in printed
    assert not (tmp_path / "s" / "ledger.jsonl").exists()
    assert main(["--out", str(tmp_path / "s"), "--cancel"]) == 0
    assert "cancelled" in capsys.readouterr().out


def test_the_cli_exports_a_done_campaign_later_on_its_out(tmp_path, capsys):
    """Measured at 7b0a39a: `--out DIR --export` alone on a done campaign
    was refused campaign.arguments (a new campaign needs a prompt), so the
    smoke path 'run, then export' could not be typed. --export on an
    existing --out is now an action like --report: a done campaign's
    verified runs land in <out>/datasets/<format> and the card names the
    format; a campaign that is not done is refused campaign.state, never
    resumed behind the caller's back."""
    from flightsim.campaign import main

    out = tmp_path / "later"
    # A 2-case headless campaign, run to done in one invocation.
    assert main([PROMPT, "--images", "100", "--seed", "7", "--out", str(out),
                 "--workers", "1"]) == 0
    printed = capsys.readouterr().out
    assert "done" in printed and not (out / "datasets").exists()
    assert Campaign.open(out).state == DONE
    cases = [r for r in Ledger(out / "ledger.jsonl").rows() if r.get("status") == "verified"]
    assert len(cases) >= 2
    # Later: export alone, on the same --out.
    assert main(["--out", str(out), "--export"]) == 0
    printed = capsys.readouterr().out
    assert "exported" in printed and "(labels only: no pixels were drawn)" in printed
    fmt = Campaign.open(out).record["format"]
    dataset = out / "datasets" / fmt
    assert dataset.is_dir() and (dataset / "DATASET_CARD.md").is_file()
    assert fmt in (dataset / "DATASET_CARD.md").read_text(encoding="utf-8")
    assert str(dataset) in printed
    # A campaign that is not done: refused by name, and not resumed.
    planned = tmp_path / "planned"
    assert main([PROMPT, "--images", "10", "--out", str(planned), "--plan"]) == 0
    capsys.readouterr()
    assert main(["--out", str(planned), "--export"]) == 2
    printed = capsys.readouterr().out
    assert printed.startswith("REFUSED -- campaign.state:"), printed
    assert not (planned / "ledger.jsonl").exists()
