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
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nl.compiler import compile_prompt  # noqa: E402
from core.nl.llm_compiler import LLMCompileError, compile_prompt_llm  # noqa: E402
from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.validate import validate  # noqa: E402
from core.terrain.glo30 import LOCATIONS  # noqa: E402
from webapp.runs import LOCATION_TOLERANCE_DEG  # noqa: E402

RULE = "=" * 96

#: The corpus. ``kind`` decides what is asserted:
#:   vocabulary  -- inside the regex compiler's documented vocabulary; the
#:                  validator must judge both compilers' specs identically
#:                  (same ok flag, same violated-constraint names). A
#:                  vocabulary prompt must never trigger a question (the
#:                  documented mapping is the answer).
#:   extended    -- sentence shapes the regex compiler cannot parse; the LLM
#:                  spec must parse, carry provenance, and validate or be
#:                  refused by name. This is the capability Phase 8 adds.
#:   adversarial -- impossible, unknown or non-scenario content; the outcome
#:                  must be a named refusal or a note, never a silent guess.
#:   clarify     -- ambiguous in a way that materially changes the scenario;
#:                  MUST trigger a question round, which the runner answers
#:                  from the entry's scripted ``answers`` (matched by
#:                  substring against the question text) and asserts the
#:                  final spec.
#:   determined  -- fully determined; must trigger ZERO questions.
#:   vague       -- fuzzy/evocative; graded coherent-and-declared, not
#:                  exact-match: every model-sourced (and claimed-user)
#:                  value must quote a phrase actually in the prompt, the
#:                  scene must fill >= ``min_filled`` non-default fields,
#:                  per-entry ``expect_fields`` pin coherence, and the spec
#:                  must validate after the webapp's own default planning.
#:                  A silent numeric guess or a contradictory fill fails.
#: Optional per-entry assertions: ``expect_questions`` (bool),
#: ``expect_location`` (a LOCATIONS key the final spec must land on, within
#: the run manager's tolerance window), ``answers`` (question-substring ->
#: scripted answer). Questions on entries without scripted answers are
#: answered with the question's first option, recorded in the report.
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
    # -- vague/holistic (the scene director: coherent-and-declared) --------
    # Graded on coherence and DECLARATION, not exact-match: every model-
    # sourced guess must quote a phrase that actually appears in the
    # prompt, claimed-user values must too (a fabricated "user" claim is
    # the silent guess in disguise), the scene must fill enough of itself
    # to be a scene, and the planned spec must fly.
    {"kind": "vague", "prompt": "storm chasing in a small plane over Kansas",
     "expect_location": "flint_hills",
     "expect_fields": {"aircraft": "c172p", "weather_event": "thunderstorm"},
     "min_filled": 5},
    {"kind": "vague",
     "prompt": "screaming along at treetop level over the desert",
     "expect_fields": {"surface": "desert"}, "min_filled": 3},
    {"kind": "vague",
     "prompt": "a lazy sightseeing loop over the Grand Canyon on a gusty "
               "afternoon",
     "expect_location": "grand_canyon", "min_filled": 4},
    {"kind": "vague",
     "prompt": "a jumbo jet plowing through violent air high over the "
               "Himalayas",
     "expect_location": "everest",
     "expect_fields": {"aircraft": "B747"}, "min_filled": 5},
    # -- clarify (must ask; scripted answers close the round) -------------
    {"kind": "clarify",
     "prompt": "simulate an aircraft under windy conditions on a mountain",
     "expect_questions": True,
     "answers": {"mountain": "Matterhorn", "aircraft": "c172p"},
     "expect_location": "matterhorn"},
    {"kind": "clarify", "prompt": "windy on a mountain",
     "expect_questions": True,
     "answers": {"mountain": "Matterhorn"},
     "expect_location": "matterhorn"},
    # -- determined (must NOT ask) ----------------------------------------
    {"kind": "determined",
     "prompt": "simulate a B747 at 250 kt over the Matterhorn in strong wind",
     "expect_questions": False,
     "expect_location": "matterhorn"},
    {"kind": "determined",
     "prompt": "a c172p at 2600 m and 100 kt over Yosemite, calm",
     "expect_questions": False,
     "expect_location": "yosemite"},
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
    from core.nl.llm_compiler import llm_available

    if not llm_available():
        print("  [BLOCKED] no LLM provider configured (ANTHROPIC_API_KEY or")
        print("  FLIGHTSIM_LLM=ollama in the environment).")
        print("  The mocked half of this gate (tests/test_llm_compiler.py)")
        print("  is green; the live half has no evidence. §5: not passed,")
        print("  not failed on the merits.")
        return 2
    provider = os.environ.get("FLIGHTSIM_LLM", "").strip() or "anthropic"
    print(f"  provider: {provider} -- the verdict below is a measurement of")
    print("  THIS provider's model; the machinery is provider-independent.")

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

        # A question round: answer from the entry's script (matched by
        # substring against the question text) or the first option, then
        # close the round. One round only -- the parser enforces it.
        asked = [dict(q) for q in result.questions]
        if asked:
            row["questions"] = [q["question"] for q in asked]
            scripted = case.get("answers", {})
            answers = []
            for q in asked:
                answer = next((text for needle, text in scripted.items()
                               if needle.lower() in q["question"].lower()),
                              q["options"][0])
                answers.append({"id": q["id"], "answer": answer})
            row["answers"] = answers
            print(f"        asked {len(asked)} question(s); answering: "
                  f"{[a['answer'] for a in answers]}")
            try:
                result = compile_prompt_llm(prompt, questions=asked,
                                            answers=answers)
            except LLMCompileError as exc:
                row["compile_error"] = str(exc)
                row["outcome"] = "FAILED (answer round)"
                print(f"        FAILED on the answer round: {exc}")
                failures += 1
                rows.append(row)
                continue

        # Question expectations: clarify entries MUST ask; determined and
        # vocabulary entries must not (the documented mapping is the
        # answer, not a question).
        expect_q = case.get("expect_questions")
        if expect_q is None and case["kind"] == "vocabulary":
            expect_q = False
        if expect_q is True and not asked:
            print("        EXPECTED a clarifying question; none came")
            row["question_miss"] = "expected, none asked"
            failures += 1
        elif expect_q is False and asked:
            print(f"        UNEXPECTED question(s): {row['questions']}")
            row["question_miss"] = "asked on a determined prompt"
            failures += 1

        spec = result.spec

        # Geography: the final spec must land on the named bake's origin
        # inside the run manager's tolerance window -- the property that
        # makes pick_scene choose the real terrain.
        target = case.get("expect_location")
        if target:
            location = LOCATIONS[target]
            on_bake = (
                abs(float(spec.latitude.value) - location.origin_lat)
                <= LOCATION_TOLERANCE_DEG
                and abs(float(spec.longitude.value) - location.origin_lon)
                <= LOCATION_TOLERANCE_DEG)
            row["on_bake"] = on_bake
            if not on_bake:
                print(f"        OFF-BAKE: spec at "
                      f"({float(spec.latitude.value):.4f}, "
                      f"{float(spec.longitude.value):.4f}) vs {target} "
                      f"origin ({location.origin_lat}, {location.origin_lon})")
                failures += 1
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
        elif case["kind"] == "vague":
            # 1. Every guess DECLARED with a fair quote: model rows (and
            #    claimed-user rows -- a fabricated "user" claim is a silent
            #    guess in disguise) must carry a phrase that appears in the
            #    prompt. Answer-round provenance is exempt by shape.
            unquoted = []
            for _, fname, q in spec.quantities():
                if str(q.source) not in ("user", "model"):
                    continue
                phrase = (q.frm or "").strip().strip('"').lower()
                if phrase.startswith("answer to"):
                    continue
                # A fair quote: the whole reason appears in the prompt, or
                # the reason carries a quoted segment that does.
                candidates = [phrase] + [s.lower() for s in
                                         re.findall(r"['\"]([^'\"]+)['\"]",
                                                    q.frm or "")]
                if not phrase or not any(c and c in prompt.lower()
                                         for c in candidates):
                    unquoted.append((fname, q.frm))
            row["unquoted"] = unquoted
            if unquoted:
                print(f"        UNDECLARED/UNFAITHFUL QUOTE: {unquoted}")
                failures += 1
            # 2. Coherence breadth: an evocative prompt must fill a scene,
            #    not two fields and defaults.
            filled = len(row["non_default_fields"])
            needed = case.get("min_filled", 3)
            row["filled"] = filled
            if filled < needed:
                print(f"        TOO SPARSE: {filled} fields filled, "
                      f"expected >= {needed}")
                failures += 1
            # 3. Specific coherence pins (contradiction check).
            for fname, expected in (case.get("expect_fields") or {}).items():
                actual = getattr(spec, fname).value
                if actual != expected:
                    print(f"        INCOHERENT: {fname} = {actual!r}, "
                          f"expected {expected!r}")
                    row.setdefault("incoherent", []).append(fname)
                    failures += 1
            # 4. The scene must FLY: grade the verdict after the same
            #    planning the webapp applies (declared guesses are
            #    plannable; physics keeps the last word).
            from webapp.runs import (apply_weather_event,
                                     plan_flyable_defaults,
                                     plan_trim_recovery)
            apply_weather_event(spec)
            plan_flyable_defaults(spec)
            plan_trim_recovery(spec)
            row["verdict"] = verdict_names(spec)
            if not row["verdict"]["ok"]:
                print(f"        UNFLYABLE after planning: "
                      f"{row['verdict']['violations']}")
                failures += 1
        row["outcome"] = "ok"
        rows.append(row)

    # -- determinism through the new path ---------------------------------
    print(f"\n{RULE}\ndeterminism: the same SPEC runs bit-identically\n{RULE}")
    deterministic = None
    # Extended specs first (the capability under test), vocabulary specs
    # as the fallback pool: model-guessed conditions increasingly carry
    # weather that legitimately defeats the closure check, and the claim
    # here is about the SPEC->run edge, not about any one prompt.
    candidates = ([r for r in rows if r["kind"] == "extended"]
                  + [r for r in rows if r["kind"] == "vocabulary"])
    for row in candidates:
        if not row.get("verdict", {}).get("ok"):
            continue
        result = compile_prompt_llm(row["prompt"])
        if result.questions:
            # A fresh compile of this prompt asked a question this time;
            # pick a spec that compiles straight through instead.
            continue
        spec = result.spec
        spec.set("duration", 10.0, frm="gate 8.1 determinism check")
        spec.set("mass_held", True, frm="gate 8.1 determinism check")
        try:
            first = run_spec(spec).output_digest
            second = run_spec(spec).output_digest
        except Exception as exc:
            # A spec that validates can still fail at runtime (e.g. the
            # closure check refuses a run that never reached its commanded
            # state -- correctly: such a run is not evidence). Recorded,
            # never swallowed; the next valid spec carries the check.
            print(f"  \"{row['prompt'][:50]}\": run refused "
                  f"({type(exc).__name__}); trying the next valid spec")
            row["determinism_run_refused"] = f"{type(exc).__name__}: {exc}"
            continue
        deterministic = first == second
        print(f"  \"{row['prompt'][:50]}\": {first[:16]} vs {second[:16]} "
              f"-> {'identical' if deterministic else 'DIVERGENT'}")
        if not deterministic:
            failures += 1
        break
    if deterministic is None:
        print("  no valid extended-corpus spec completed a run; determinism "
              "unasserted")
        failures += 1

    report = {"corpus": rows, "failures": failures,
              "deterministic": deterministic}
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n  wrote {out / 'report.json'}")
    print(f"\n  GATE 8.1: {'PASS' if failures == 0 else f'FAIL ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
