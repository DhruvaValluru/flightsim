"""Gate 1 -- prompt to spec to validated, reproducible run.

    Prompt -> spec -> human-readable table -> edit -> validated spec ->
    identical run twice, bit-identical outputs. A physically impossible request
    (landing at 400 kt, 300 m altitude over 3000 m terrain) is rejected at
    validation with a clear message naming the violated constraint. (§5 Phase 1)

Four things are checked, in the order a user would meet them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nl.compiler import compile_prompt  # noqa: E402
from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.spec import ScenarioSpec  # noqa: E402
from core.scenario.validate import validate  # noqa: E402

RULE = "=" * 78

#: The impossible request named in §5, plus variants that must each be caught
#: for a specific, named reason rather than by a general "it failed" path.
IMPOSSIBLE = (
    (
        "land the 747 at 400 kt at 300 m altitude over 3000 m terrain",
        "altitude.terrain_clearance",
    ),
    (
        "fly the 747 at 60 kt at 3000 m",
        "airspeed.stall_margin",
    ),
    (
        "cruise the global5000 at 10000 m at 300 kt",
        "envelope.trim_feasible",
    ),
)


def _headline(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def check_prompt_to_table(prompt: str) -> Tuple[bool, ScenarioSpec]:
    _headline("1. prompt -> spec -> human-readable table")
    print(f'prompt: "{prompt}"\n')
    spec = compile_prompt(prompt)
    print(spec.render_table())

    ok = True
    sources = {str(q.source) for _, _, q in spec.quantities()}
    if not {"user", "inferred", "default"} & sources:
        print("\n  -> FAIL: no provenance recorded")
        ok = False
    # Every field must carry a unit or be categorical; a bare number with no
    # unit is how 233 kt and 233 m get confused.
    unitless = [
        n for _, n, q in spec.quantities()
        if q.unit is None and isinstance(q.value, (int, float))
        and not isinstance(q.value, bool)
    ]
    if unitless:
        print(f"\n  -> FAIL: numeric fields with no unit: {unitless}")
        ok = False
    return ok, spec


def check_edit_and_roundtrip(spec: ScenarioSpec, tmp: Path) -> Tuple[bool, ScenarioSpec]:
    _headline("2. spec is editable, and survives a round trip to disk")
    before = spec.digest()
    path = spec.write(tmp / "scenario.yaml")
    reloaded = ScenarioSpec.read(path)
    ok = reloaded.digest() == before
    print(f"  written to {path}")
    print(f"  digest before {before[:16]}  after reload {reloaded.digest()[:16]}  "
          f"{'match' if ok else 'MISMATCH'}")

    original_altitude = reloaded.altitude.value
    reloaded.set("altitude", 4500.0, frm="operator raised the cruise altitude")
    changed = reloaded.digest() != before
    print(f"  edited altitude {original_altitude} -> {reloaded.altitude.value} m; "
          f"source is now '{reloaded.altitude.source}'")
    print(f"  digest changed: {changed}")
    if not changed:
        print("  -> FAIL: editing a field did not change the digest")
    # An edit must be visibly a human decision, not an inference.
    if str(reloaded.altitude.source) != "user":
        print("  -> FAIL: an edited field must be attributed to the user")
        ok = False
    return ok and changed, reloaded


def check_reproducibility(spec: ScenarioSpec) -> bool:
    _headline("3. the same spec runs bit-identically twice")
    first = run_spec(spec)
    second = run_spec(spec)
    ok = first.output_digest == second.output_digest
    print(f"  spec digest    {spec.digest()}")
    print(f"  run 1 output   {first.output_digest}")
    print(f"  run 2 output   {second.output_digest}")
    print(f"  {first.telemetry.__len__()} samples over "
          f"{first.telemetry.series('t')[-1]:.0f} s")
    print(f"  -> {'identical' if ok else 'DIFFERENT -- run is not reproducible'}")
    return ok


def check_impossible_rejected() -> bool:
    _headline("4. impossible requests are rejected, naming the constraint")
    ok = True
    for prompt, expected in IMPOSSIBLE:
        spec = compile_prompt(prompt)
        report = validate(spec)
        names = [v.constraint for v in report.violations]
        hit = expected in names
        print(f'\n  prompt: "{prompt}"')
        if report.ok:
            print("    -> FAIL: accepted a scenario that cannot be flown")
            ok = False
            continue
        for v in report.violations:
            print(f"    {v.render()}")
        if not hit:
            print(f"    -> FAIL: expected constraint {expected!r}, got {names}")
            ok = False
    return ok


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 1")
    ap.add_argument(
        "--prompt",
        default="fly the 747 at 10000 ft and 280 kt into a strong crosswind "
                "for 90 seconds, heading 270",
    )
    ap.add_argument("--out", default="runs/gate1")
    args = ap.parse_args(argv)
    tmp = Path(args.out)

    results: List[Tuple[str, bool]] = []
    ok, spec = check_prompt_to_table(args.prompt)
    results.append(("prompt -> spec -> table", ok))

    ok, edited = check_edit_and_roundtrip(spec, tmp)
    results.append(("editable + round trip", ok))

    results.append(("bit-identical reruns", check_reproducibility(edited)))
    results.append(("impossible rejected", check_impossible_rejected()))

    _headline("GATE 1")
    for name, passed in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    everything = all(p for _, p in results)
    print(f"\n  GATE 1: {'PASS' if everything else 'FAIL'}")
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
