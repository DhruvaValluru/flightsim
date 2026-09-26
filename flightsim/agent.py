"""Run the agentic controller on a request (contracts §7):

    .venv/bin/python -m flightsim.agent "fly the a320 at 3000 m for 10 seconds in varied weather" \\
        --images 200 --out campaigns/agent-demo --format coco
    .venv/bin/python -m flightsim.agent "fly the a320 at 3000 m for 10 seconds" \\
        --images 200 --out campaigns/agent-demo --vary "varied weather at different times of day"

The controller interprets the prompt (the regex compiler; ``--tier
llm`` uses the configured language model for the prompt and falls
back, recorded), validates it, plans the campaign, previews slots,
runs them, runs the campaign to its target, reads the report and
exports -- every call checked by the authority policy and written to
``DIR/trace.jsonl`` with its reason in one sentence. Exit 0 when the
export exists, 1 when the loop escalated (the sentence says why, in
catalogue language), 2 on a bad argument.
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
        description="the agentic controller: a prompt, N images, a directory")
    parser.add_argument("prompt", help="the scenario prompt")
    parser.add_argument("--images", type=int, required=True,
                        help="the number of verified frames asked for")
    parser.add_argument("--out", required=True,
                        help="the campaign directory (trace.jsonl lives here)")
    parser.add_argument("--format", default="coco",
                        help="export format (coco, kitti, webdataset, yolo, voc)")
    parser.add_argument("--vary", default="",
                        help="policy words in the prompt vocabulary, e.g. 'varied weather'")
    parser.add_argument("--policy", default=None,
                        help="an explicit randomisation policy as JSON (contracts §5.2); "
                             "planned only when the prompt states none")
    parser.add_argument("--seed", type=int, default=None, help="campaign seed")
    parser.add_argument("--tier", default="regex", choices=("regex", "llm"),
                        help="compiler tier for the prompt (llm falls back, recorded)")
    parser.add_argument("--answer", action="append", default=[],
                        help="an answer to a clarifying question, id=text (repeatable)")
    parser.add_argument("--render", action="store_true",
                        help="ask each capture for pixels (needs an engine)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--preview", type=int, default=2,
                        help="slots run one at a time before the campaign runs to target")
    parser.add_argument("--max-calls", type=int, default=60, help="tool-call budget")
    parser.add_argument("--max-seconds", type=float, default=1800.0, help="wall-time budget")
    parser.add_argument("--max-resamples", type=int, default=3,
                        help="re-samples per slot before the loop escalates")
    parser.add_argument("--json", action="store_true", help="print the outcome as JSON")
    args = parser.parse_args(argv)

    from core.agent import Budget, Controller, Policy, Request, Tools

    if args.images < 1:
        print("REFUSED -- campaign.arguments: --images must be >= 1")
        return 2
    try:
        answers = _answers(args.answer)
    except ValueError as exc:
        print(f"REFUSED -- campaign.arguments: {exc}")
        return 2
    policy = None
    if args.policy is not None:
        try:
            policy = json.loads(args.policy)
        except ValueError as exc:
            print(f"REFUSED -- campaign.arguments: --policy is not JSON: {exc}")
            return 2
    budget = Budget(max_calls=args.max_calls, max_resamples_per_slot=args.max_resamples,
                    max_wall_seconds=args.max_seconds)
    tools = Tools(args.out, policy=Policy(budget), tier=args.tier, workers=args.workers)
    controller = Controller(tools, preview=args.preview)
    outcome = controller.run(Request(args.prompt, images=args.images, words=args.vary,
                                     format=args.format, seed=args.seed,
                                     answers=answers or None, render=args.render,
                                     policy=policy))
    if args.json:
        print(json.dumps(outcome.to_dict(), indent=1, default=str))
    else:
        for step in outcome.steps:
            print(f"  {step}")
        print(f"{outcome.state}: {outcome.sentence}")
        print(f"  trace: {outcome.trace_path}")
    return 0 if outcome.state == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
