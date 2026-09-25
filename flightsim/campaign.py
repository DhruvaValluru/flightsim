"""Run a campaign: a prompt, a number of images, a seed -- to the target
or to a named end (contracts §6.1).

    .venv/bin/python -m flightsim.campaign "fly the a320 at 3000 m in varied weather" \\
        --images 500 --out campaigns/demo --workers 2 --seed 7 --format coco
    .venv/bin/python -m flightsim.campaign --out campaigns/demo --resume
    .venv/bin/python -m flightsim.campaign --out campaigns/demo --pause     # or --cancel
    .venv/bin/python -m flightsim.campaign --out campaigns/demo --status
    .venv/bin/python -m flightsim.campaign --out campaigns/demo --report    # in words

``DIR/campaign.json`` is the record (state planned|running|paused|
failed|done|cancelled), ``DIR/ledger.jsonl`` one line per event per
slot, ``DIR/control.json`` the pause/cancel request, ``DIR/report.json``
the yield, coverage and refusals, ``DIR/runs/<case_id>/`` the runs.
Exit 0 when the campaign is done, 1 when it ended otherwise (paused,
cancelled, failed by name), 2 on a refusal before anything ran.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _answers(pairs):
    out = []
    for pair in pairs or []:
        key, sep, value = str(pair).partition("=")
        if not sep:
            raise ValueError(f"--answer takes id=text, got {pair!r}")
        out.append({"id": key.strip(), "answer": value.strip()})
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="run a campaign: a prompt, N images, a seed, a pool of workers")
    parser.add_argument("prompt", nargs="?", default=None,
                        help="the scenario prompt (omit with --resume/--pause/"
                             "--cancel/--status/--report)")
    parser.add_argument("--images", type=int, default=None,
                        help="the target number of verified frames")
    parser.add_argument("--out", required=True, help="campaign directory")
    parser.add_argument("--workers", type=int, default=None,
                        help="concurrent captures (spawned processes; default 1)")
    parser.add_argument("--seed", type=int, default=None,
                        help="campaign seed (default: the prompt's, else 1)")
    parser.add_argument("--format", default="coco",
                        help="export format recorded for the campaign (default coco)")
    parser.add_argument("--tier", default="regex", choices=("regex", "llm"),
                        help="compiler tier (llm falls back to regex, recorded)")
    parser.add_argument("--answer", action="append", default=[],
                        help="an answer to a clarifying question, id=text (repeatable)")
    parser.add_argument("--disk-budget-gb", type=float, default=None,
                        help="refuse storage.budget_exceeded above this many GB")
    parser.add_argument("--render", action="store_true",
                        help="ask each capture for pixels (needs an engine; "
                             "refused by name per case where there is none)")
    parser.add_argument("--stall-minutes", type=float, default=20.0,
                        help="watchdog: kill and re-queue a case whose capture "
                             "writes nothing for this long (default 20)")
    parser.add_argument("--plan", action="store_true",
                        help="compile, validate, estimate; run nothing")
    parser.add_argument("--sample", type=int, default=None, metavar="N",
                        help="draw the first N slots and print them; run nothing")
    parser.add_argument("--resume", action="store_true",
                        help="continue an existing campaign from its ledger")
    parser.add_argument("--pause", action="store_true", help="ask a running campaign to pause")
    parser.add_argument("--cancel", action="store_true", help="cancel the campaign")
    parser.add_argument("--status", action="store_true", help="print the ledger's numbers")
    parser.add_argument("--report", action="store_true",
                        help="write report.json and print it in words")
    parser.add_argument("--export", action="store_true",
                        help="after a done campaign, export the verified runs")
    args = parser.parse_args(argv)

    from core.campaign import Campaign, CampaignError
    from core.campaign.report import render_report
    from core.dataset.export import ExportError

    try:
        if args.resume or args.pause or args.cancel or args.status or args.report:
            campaign = Campaign.open(args.out)
            if args.pause:
                status = campaign.pause()
                print(f"pause requested for campaign {status['id']} (state {status['state']}); "
                      f"the running process stops after the cases in flight")
                return 0
            if args.cancel:
                status = campaign.cancel()
                print(f"campaign {status['id']}: {status['state']}"
                      + (" (cancel requested; the running process stops after the "
                         "cases in flight)" if status["state"] == "running" else ""))
                return 0
            if args.status:
                print(json.dumps(campaign.status(), indent=1))
                return 0
            if args.report:
                print(render_report(campaign.report()))
                print(f"  written: {campaign.dir / 'report.json'}")
                return 0
            status = campaign.resume(workers=args.workers,
                                     progress=lambda line: print("  " + line))
        else:
            if not args.prompt or args.images is None:
                print("REFUSED -- campaign.arguments: a new campaign needs a prompt "
                      "and --images N (or --resume/--pause/--cancel/--status/"
                      "--report on an existing --out)")
                return 2
            try:
                answers = _answers(args.answer)
            except ValueError as exc:
                print(f"REFUSED -- campaign.arguments: {exc}")
                return 2
            budget = (int(args.disk_budget_gb * 1024 ** 3)
                      if args.disk_budget_gb is not None else None)
            capture = {"max_previews": 0, "card": True}
            if args.render:
                capture["render"] = True
            campaign = Campaign.create(
                args.prompt, answers=answers, images=args.images, seed=args.seed,
                out=args.out, format=args.format, workers=args.workers or 1,
                disk_budget_bytes=budget, tier=args.tier, capture=capture,
                stall_seconds=args.stall_minutes * 60.0)
            plan = campaign.plan()
            fpc = plan["frames_per_case"]
            print(f"campaign {campaign.record['id']}: spec {plan['spec_digest'][:16]} "
                  f"(compiled by {campaign.record['tier']}), seed {campaign.record['seed']}, "
                  f"target {plan['images_target']} frame(s) ~ {plan['cases_needed']} case(s) "
                  f"at ~{fpc['estimate']} frame(s) each ({fpc['basis']}); "
                  f"policy {'over ' + ', '.join(plan['policy']) if plan['policy'] else 'none'}")
            if args.plan:
                print(json.dumps(plan, indent=1, default=str))
                return 0
            if args.sample is not None:
                drawn = campaign.sample(args.sample, record=False)
                for case in drawn["cases"]:
                    print(f"  slot {case['index']}: {case['case_id']} seed {case['seed']} "
                          f"{case['sampled']}"
                          + (f" (refused attempts: {case['refusals']})" if case["refusals"] else ""))
                for slot in drawn["refused"]:
                    print(f"  slot {slot['index']}: REFUSED {slot['refusals']} -- {slot['reason']}")
                return 0
            status = campaign.run(workers=args.workers,
                                  progress=lambda line: print("  " + line))
    except CampaignError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        try:
            state = Campaign.open(args.out).state
        except CampaignError:
            state = None
        return 1 if state in ("failed", "paused", "cancelled") else 2

    print(f"campaign {status['id']}: {status['state']}"
          + (f" -- {status['reason']}" if status.get("reason") else ""))
    print(f"  {status['frames_verified']} verified frame(s) of {status['images_target']}; "
          f"cases: " + ", ".join(f"{v} {k}" for k, v in status["cases"].items() if v))
    print(f"  ledger: {campaign.dir / 'ledger.jsonl'}")
    if status["state"] == "done" and args.export:
        try:
            result = campaign.export()
        except ExportError as exc:
            print(f"REFUSED -- {exc.constraint}: {exc.message}")
            return 1
        print(f"  exported {result['runs']} run(s) to {result['dataset_path']}"
              + (" (labels only: no pixels were drawn)" if result["labels_only"] else ""))
    return 0 if status["state"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
