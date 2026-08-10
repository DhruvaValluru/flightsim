"""Gate 8.1 -- the LLM compiler, measured against the schema, the regex
compiler, and the validator.

    A ~30-prompt corpus: every output parses into the schema, validates or
    is refused BY NAME, and carries provenance on every field. No silent
    drops. On the regex compiler's own documented vocabulary the two
    compilers must be judged identically by the validator
    (refusal-for-refusal). Adversarial prompts are refused or noted --
    never guessed into a runnable spec that misrepresents the request.
    Determinism is re-asserted through the new path: the same SPEC runs
    bit-identically twice. (Phase 8 brief, Gate 8.1)

This gate needs the live API: the mocked suite (tests/test_llm_compiler.py)
already pins the parsing/refusal machinery, so what is measured here is the
one thing a mock cannot answer -- what the real model does with real
sentences. With no ANTHROPIC_API_KEY it exits 2 = BLOCKED, which is neither
a pass nor a failure on the merits (§5: no gate passes on partial evidence).

Usage: .venv/bin/python experiments/gate8_compiler.py [--out runs/gate8_compiler]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nl.compiler import compile_prompt  # noqa: E402
from core.nl.llm_compiler import LLMCompileError, compile_prompt_llm  # noqa: E402
from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.validate import validate  # noqa: E402

RULE = "=" * 96

#: The corpus. ``kind`` decides what is asserted:
#:   vocabulary  -- inside the regex compiler's documented vocabulary; the
#:                  validator must judge both compilers' specs identically
#:                  (same ok flag, same violated-constraint names).
#:   extended    -- sentence shapes the regex compiler cannot parse; the LLM
#:                  spec must parse, carry provenance, and validate or be
#:                  refused by name. This is the capability Phase 8 adds.
#:   adversarial -- impossible, unknown or non-scenario content; the outcome
#:                  must be a named refusal or a note, never a silent guess.
CORPUS: List[Dict] = [
    # -- vocabulary (the regex compiler's own documented forms) -----------
    {"kind": "vocabulary", "prompt": "fly the 747 at 3000 m and 250 kt for 60 seconds"},
    {"kind": "vocabulary", "prompt": "fly the c172 at 2600 m and 100 kt for 30 seconds"},
    {"kind": "vocabulary", "prompt": "fly the 737 at 6000 m and 280 kt"},
    {"kind": "vocabulary", "prompt": "fly the a320 at 5000 m and 250 kt"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 3000 m and 250 kt in a strong crosswind"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 3000 m and 250 kt in moderate turbulence"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 3000 m and 250 kt with a 15 kt headwind"},
    {"kind": "vocabulary", "prompt": "fly the business jet at FL200 and 250 kt"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 9000 ft and 250 kt heading 090"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 500 m over 2000 m terrain"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 3000 m and 90 kt"},
    {"kind": "vocabulary", "prompt": "fly the 747 at 3000 m and 250 kt in severe turbulence for 2 minutes"},
    # -- extended (what the regex vocabulary cannot express) --------------
    {"kind": "extended", "prompt": "simulate a plane in rough wind conditions over mountains"},
    {"kind": "extended", "prompt": "I want to see a jumbo jet fighting a gale above alpine peaks"},
    {"kind": "extended", "prompt": "put a small cessna two and a half kilometres up in bumpy air"},
    {"kind": "extended", "prompt": "a heavy airliner cruising high on a perfectly calm day"},
    {"kind": "extended", "prompt": "airliner at thirty one thousand feet doing about four hundred knots true"},
    {"kind": "extended", "prompt": "let a 737 battle a stiff wind coming from its left side"},
    {"kind": "extended", "prompt": "gentle evening flight, light chop, nothing dramatic, small plane"},
    {"kind": "extended", "prompt": "an airbus descending through choppy air with a strong tailwind"},
    {"kind": "extended", "prompt": "fly something big through the worst turbulence you can simulate"},
    {"kind": "extended", "prompt": "a cessna over the matterhorn in strong wind"},
    {"kind": "extended", "prompt": "747 over yosemite valley, calm morning"},
    {"kind": "extended", "prompt": "low and slow over high mountains in a storm"},
    # -- adversarial ------------------------------------------------------
    {"kind": "adversarial", "prompt": "fly the 747 at 500000 m and 250 kt",
     "expect": "named refusal or note"},
    {"kind": "adversarial", "prompt": "fly the 747 at 3000 m and 2500 kt",
     "expect": "named refusal or note"},
    {"kind": "adversarial", "prompt": "fly an SR-71 blackbird at mach 3",
     "expect": "unknown aircraft goes to notes, never guessed into a field"},
    {"kind": "adversarial", "prompt": "epic cinematic drone shot of a sunset, no aircraft",
     "expect": "cinematic content noted, defaults otherwise"},
    {"kind": "adversarial", "prompt": "make the 747 fly backwards at -100 kt",
     "expect": "named refusal or note"},
    {"kind": "adversarial", "prompt": "land the 747 on the matterhorn summit",
     "expect": "named refusal or note"},
]


def verdict_names(spec) -> Dict:
    report = validate(spec)
    return {"ok": report.ok,
            "violations": sorted(v.constraint for v in report.violations)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 8.1")
    ap.add_argument("--out", default="runs/gate8_compiler")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"\n{RULE}\nGate 8.1: the LLM compiler against the corpus\n{RULE}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [BLOCKED] no ANTHROPIC_API_KEY in the environment.")
        print("  The mocked half of this gate (tests/test_llm_compiler.py)")
        print("  is green; the live half has no evidence. §5: not passed,")
        print("  not failed on the merits.")
        return 2

    rows: List[Dict] = []
    failures = 0
    for index, case in enumerate(CORPUS):
        prompt = case["prompt"]
        row: Dict = {"kind": case["kind"], "prompt": prompt}
        print(f"\n  [{index + 1:2d}/{len(CORPUS)}] ({case['kind']}) \"{prompt}\"")
        try:
            result = compile_prompt_llm(prompt)
        except LLMCompileError as exc:
            # A rejection is a valid outcome only for adversarial content;
            # a vocabulary or extended prompt failing to compile is a miss.
            row["compile_error"] = str(exc)
            if case["kind"] == "adversarial":
                print(f"        rejected loudly: ok ({str(exc)[:70]}...)")
                row["outcome"] = "rejected"
            else:
                print(f"        FAILED to compile: {exc}")
                row["outcome"] = "FAILED"
                failures += 1
            rows.append(row)
            continue

        spec = result.spec
        row["model"] = result.model
        row["digest"] = spec.digest()
        row["notes"] = list(spec.notes)
        # Provenance on every field, mechanically checkable.
        sources = {name: str(q.source) for _, name, q in spec.quantities()}
        row["non_default_fields"] = {
            n: s for n, s in sources.items() if s != "default"}
        row["verdict"] = verdict_names(spec)
        print(f"        digest {spec.digest()[:16]}  "
              f"{len(row['non_default_fields'])} fields set  "
              f"verdict {'valid' if row['verdict']['ok'] else row['verdict']['violations']}")

        if case["kind"] == "vocabulary":
            regex_verdict = verdict_names(compile_prompt(prompt))
            row["regex_verdict"] = regex_verdict
            same = (regex_verdict["ok"] == row["verdict"]["ok"]
                    and regex_verdict["violations"] == row["verdict"]["violations"])
            row["refusal_parity"] = same
            if not same:
                print(f"        PARITY MISS: regex verdict {regex_verdict}")
                failures += 1
        elif case["kind"] == "adversarial":
            # Never guessed into a runnable spec that misrepresents the
            # request: either the validator refuses by name, or the
            # unexpressible content is in notes.
            honest = (not row["verdict"]["ok"]) or bool(spec.notes)
            row["honest"] = honest
            if not honest:
                print("        SILENT GUESS: validated clean with no notes")
                failures += 1
        row["outcome"] = "ok"
        rows.append(row)

    # -- determinism through the new path ---------------------------------
    print(f"\n{RULE}\ndeterminism: the same SPEC runs bit-identically\n{RULE}")
    deterministic = None
    for row in rows:
        if row.get("verdict", {}).get("ok") and row["kind"] == "extended":
            result = compile_prompt_llm(row["prompt"])
            spec = result.spec
            spec.set("duration", 10.0, frm="gate 8.1 determinism check")
            spec.set("mass_held", True, frm="gate 8.1 determinism check")
            first = run_spec(spec).output_digest
            second = run_spec(spec).output_digest
            deterministic = first == second
            print(f"  \"{row['prompt'][:50]}\": {first[:16]} vs {second[:16]} "
                  f"-> {'identical' if deterministic else 'DIVERGENT'}")
            if not deterministic:
                failures += 1
            break
    if deterministic is None:
        print("  no valid extended-corpus spec to run; determinism unasserted")
        failures += 1

    report = {"corpus": rows, "failures": failures,
              "deterministic": deterministic}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    print(f"\n  wrote {out / 'report.json'}")
    print(f"\n  GATE 8.1: {'PASS' if failures == 0 else f'FAIL ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
