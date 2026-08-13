"""Host parity across the envelope, not at a point.

Gate 5 compares the two hosts on one scenario: one airframe, one envelope point,
60 seconds, hands off. It passes by four orders of magnitude, and
``docs/VALIDITY.md`` says in as many words that it "says nothing about agreement
under wind, turbulence, terrain, manoeuvring, or over longer runs".

This is the breadth half of that. It runs the same nine conditions Gate 0 uses --
three airframes at three envelope points, chosen inside every candidate's
measured trim envelope so the airframes are compared on equal terms -- through
both hosts and compares every one against the tolerances Gate 5 declared.

This is **not** a gate. Gate 5 is the gate and its verdict is unchanged by
anything here. What this produces is the evidence that Gate 5's single-case
result was not a single-case coincidence: nine independent trims, nine
independent integrations, one table.

Why it can be trusted to be measuring the integration
------------------------------------------------------
The same three preconditions Gate 5 relies on hold for every case, and are
re-checked rather than assumed:

* both hosts run the same JSBSim commit (``scripts/ue_preflight.sh``);
* the aircraft and engine XML are byte-identical between the jsbsim wheel and
  the plugin's staged ``Resources/JSBSim`` -- checked here, per airframe,
  because a matrix that quietly compared two different 737s would look like a
  physics result;
* both hosts fly open loop from trim with mass held, so nothing is closing a
  loop that could pull them back together.

Anything left is the integration path: the plugin's substep accumulator and the
ECEF round trip it performs every tick.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.spec import ScenarioSpec  # noqa: E402
from core.scenario.validate import ValidationError  # noqa: E402
from experiments.gate5_ue_parity import (  # noqa: E402
    COMPARED, MIN_OVERLAP_FRACTION, TOLERANCE, compare, reference_spec,
    write_run_card,
)

RULE = "=" * 96

#: The Gate 0 matrix, unchanged. Reusing it rather than inventing a second one
#: means a case that fails here can be compared directly against the same case's
#: hands-off hold in Gate 0, instead of being a new unknown.
DEFAULT_AIRCRAFT = ("global5000", "737", "B747")

#: Gate 0's three points, plus one.
#:
#: Gate 0 reaches its points by building an FDM directly and never sees the
#: spec validator. This matrix goes through prompt -> spec -> validate -> run,
#: which refuses 10000 m / 240 kt for the 737 and the B747: both are below
#: 1.05 x their measured stall speed there (the B747 by 34 kt). That refusal is
#: correct and is reported rather than worked around -- but it would leave the
#: high-altitude end of the matrix covered by one airframe out of three, which
#: is a coverage gap dressed up as a result.
#:
#: 8000 m / 280 kt is the fourth point: measured to validate for all three, and
#: below the trim-feasibility boundary that stops the global5000 at 9000 m.
DEFAULT_POINTS = ((3000.0, 250.0), (6000.0, 280.0), (8000.0, 280.0),
                  (10000.0, 240.0))

#: Wind cases: (speed kt, from deg). Run for every airframe at the first
#: envelope point. A pure crosswind (from 270 for a north heading) and a
#: quartering headwind, both inside the Phase 3 null-test range. Directions
#: are whole degrees on purpose -- the UE card refuses fractions because the
#: plugin's wind IC is integral.
WIND_CASES = ((25.0, 270.0), (15.0, 30.0))

#: How the prompt is phrased. The spec is reached through the compiler rather
#: than constructed by hand, so the matrix exercises the same
#: prompt -> spec -> validate -> run path a user would (§2.6).
PROMPT = "fly the {aircraft} at {altitude:.0f} m and {airspeed:.0f} kt for {duration:.0f} seconds"


@dataclass(frozen=True)
class Case:
    aircraft: str
    altitude_m: float
    airspeed_kt: float
    duration_s: float
    #: Steady wind, meteorological convention. Zero speed is still air.
    wind_speed_kt: float = 0.0
    wind_from_deg: float = 0.0

    @property
    def name(self) -> str:
        base = f"{self.aircraft} {self.altitude_m:.0f}m {self.airspeed_kt:.0f}kt"
        if self.wind_speed_kt > 0.0:
            base += f" w{self.wind_speed_kt:.0f}@{self.wind_from_deg:.0f}"
        return base

    @property
    def slug(self) -> str:
        slug = f"{self.aircraft}_{self.altitude_m:.0f}_{self.airspeed_kt:.0f}"
        if self.wind_speed_kt > 0.0:
            slug += f"_w{self.wind_speed_kt:.0f}_{self.wind_from_deg:.0f}"
        return slug

    def prompt(self) -> str:
        return PROMPT.format(aircraft=self.aircraft, altitude=self.altitude_m,
                             airspeed=self.airspeed_kt, duration=self.duration_s)


@dataclass
class CaseResult:
    case: Case
    ok: bool
    note: str
    worst: Dict[str, float]
    overlap_fraction: float = 0.0
    spec_digest: str = ""
    #: The spec layer refused this condition before either host ran it. That is
    #: not a parity result and is not counted as one -- but it is not hidden
    #: either, because a matrix that quietly dropped the conditions it could not
    #: run would overstate its own coverage.
    refused: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_files_match(aircraft: str, wheel_root: Optional[Path] = None,
                      staged_root: Optional[Path] = None) -> Tuple[bool, str]:
    """Do the two hosts load byte-identical model XML for this airframe?

    Not a formality. ``scripts/ue_preflight.sh`` checks that both hosts run the
    same JSBSim *library*; nothing checks that they load the same aircraft, and
    the plugin stages its own copy of the data. Two different revisions of the
    same aircraft would produce a divergence that looks exactly like an
    integration defect.

    The roots are overridable so that the mismatch path can be exercised. On
    this machine the real files agree, so a test that only ever ran against
    them would pass with the comparison deleted.
    """
    import jsbsim

    if wheel_root is None:
        wheel_root = Path(jsbsim.get_default_root_dir()) / "aircraft"
    if staged_root is None:
        staged_root = (Path(__file__).resolve().parents[1] / "ue" / "Plugins" /
                       "JSBSimFlightDynamicsModel" / "Resources" / "JSBSim" /
                       "aircraft")
    wheel = Path(wheel_root) / aircraft
    staged = Path(staged_root) / aircraft
    if not wheel.is_dir():
        return False, f"{aircraft} is not in the jsbsim wheel"
    if not staged.is_dir():
        return False, f"{aircraft} is not staged in the plugin"

    differing = []
    for source in sorted(wheel.glob("*.xml")):
        target = staged / source.name
        if not target.is_file():
            differing.append(f"{source.name} missing from the plugin")
        elif _sha256(source) != _sha256(target):
            differing.append(f"{source.name} differs")
    if differing:
        return False, "; ".join(differing)
    return True, f"{len(list(wheel.glob('*.xml')))} XML files identical"


def spec_for(case: Case) -> ScenarioSpec:
    """The same spec treatment Gate 5 gives its scenario: open loop, mass held."""
    spec = reference_spec(case.prompt())
    # The compiler resolves the prompt's numbers; assert rather than trust,
    # because a prompt that parsed to a different condition would silently make
    # this a matrix of nine copies of one case.
    achieved = (str(spec.aircraft.value), float(spec.altitude.value),
                float(spec.airspeed.value))
    wanted = (case.aircraft, case.altitude_m, case.airspeed_kt)
    if achieved != wanted:
        raise ValueError(
            f"the prompt {case.prompt()!r} compiled to {achieved}, not {wanted}. "
            f"The matrix would not be running the condition it reports."
        )
    if case.wind_speed_kt > 0.0:
        spec.set("wind_speed", case.wind_speed_kt, frm="host parity wind case")
        spec.set("wind_direction", case.wind_from_deg, frm="host parity wind case")
    return spec


def run_case(case: Case, out_dir: Path, runner: Path) -> CaseResult:
    directory = out_dir / case.slug
    directory.mkdir(parents=True, exist_ok=True)

    try:
        spec = spec_for(case)
    except ValueError as exc:
        return CaseResult(case, False, str(exc), {})

    try:
        result = run_spec(spec)
    except ValidationError as exc:
        # The spec layer rejecting a condition is the spec layer working. Gate 0
        # reaches these same envelope points by building an FDM directly, which
        # never sees the stall-margin constraint; the prompt -> spec -> validate
        # path does. Reported by name, not swallowed.
        reasons = "; ".join(v.render() for v in exc.report.violations)
        return CaseResult(case, True, f"refused by the validator: {reasons}",
                          {}, spec_digest=spec.digest(), refused=True)

    headless = directory / "headless.json"
    headless.write_text(json.dumps({
        "host": "headless",
        "spec_digest": spec.digest(),
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "interval_s": result.telemetry.interval_s,
        "columns": result.telemetry.columns,
    }, indent=1), encoding="utf-8")
    spec.write(directory / "scenario.yaml")

    card = write_run_card(spec, directory / "ue_scenario.json")
    unreal = directory / "unreal.json"
    process = subprocess.run([str(runner), str(card), str(unreal)],
                             capture_output=True, text=True)
    if process.returncode != 0 or not unreal.is_file():
        tail = (process.stderr or process.stdout).strip().splitlines()
        return CaseResult(case, False,
                          f"the UE host exited {process.returncode}: "
                          f"{tail[-1] if tail else 'no output'}",
                          {}, spec_digest=spec.digest())

    parities, overlap = compare(headless, unreal)
    worst = {parity.channel: parity.max_difference for parity in parities}
    ok = overlap.ok and all(parity.ok for parity in parities)
    failed = [p.channel for p in parities if not p.ok]
    note = "" if ok else (
        "insufficient time overlap" if not overlap.ok
        else "outside tolerance: " + ", ".join(failed))
    return CaseResult(case, ok, note, worst, overlap.fraction, spec.digest())


def report(results: Sequence[CaseResult]) -> bool:
    print(f"\n{RULE}\nhost parity across the envelope\n{RULE}")
    header = f"  {'case':<26}" + "".join(f"{channel:>13}" for channel in COMPARED)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for result in results:
        if result.refused:
            cells = "".join(f"{'--':>13}" for _ in COMPARED)
            verdict = "not run"
        else:
            cells = "".join(
                f"{result.worst.get(channel, float('inf')):>13.4g}"
                for channel in COMPARED)
            verdict = "ok" if result.ok else "FAIL"
        print(f"  {result.case.name:<26}{cells}   {verdict}")
        if result.note:
            print(f"    {result.note}")
    print("  " + "-" * (len(header) - 2))
    print(f"  {'tolerance':<26}"
          + "".join(f"{TOLERANCE[channel]:>13g}" for channel in COMPARED))

    # The headline number: the worst any channel did anywhere in the matrix,
    # as a fraction of what it was allowed. Reporting the margin rather than
    # "all passed" keeps a result that is passing-but-barely visible.
    margins = []
    for result in results:
        if result.refused:
            continue
        for channel in COMPARED:
            value = result.worst.get(channel)
            if value is not None and value == value:  # not NaN
                margins.append((value / TOLERANCE[channel], channel, result.case.name))
    print()
    if margins:
        margins.sort(reverse=True)
        fraction, channel, name = margins[0]
        print(f"  worst channel anywhere: {channel} on {name}, at "
              f"{fraction * 100:.4f}% of its tolerance")

    compared = [r for r in results if not r.refused]
    refused = [r for r in results if r.refused]
    passed = sum(1 for r in compared if r.ok)
    # Two numbers, not one. "10/10 agree" on its own is true of a matrix that
    # only ever compared one condition.
    print(f"  ran in both hosts:                   "
          f"{len(compared)} of {len(results)}")
    print(f"  agree within the Gate 5 tolerances:  {passed} of {len(compared)}")
    if refused:
        # Stated as coverage lost, not as a footnote. The matrix claims nine
        # conditions; if it compared fewer, it says so on the same line as the
        # result.
        print(f"  never compared, refused by the spec layer: "
              f"{len(refused)} of {len(results)}")
        for result in refused:
            print(f"    {result.case.name}")
    return passed == len(compared) and bool(compared)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Host parity across the envelope")
    ap.add_argument("--aircraft", nargs="*", default=list(DEFAULT_AIRCRAFT))
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--out", default="runs/host_parity")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    runner = root / "scripts" / "run_ue_scenario.sh"
    if not runner.is_file():
        print(f"  {runner} is missing")
        return 1

    print(f"\n{RULE}\nmodel data, per airframe\n{RULE}")
    for aircraft in args.aircraft:
        ok, detail = model_files_match(aircraft)
        print(f"  [{'ok  ' if ok else 'FAIL'}] {aircraft:<14} {detail}")
        if not ok:
            print("\n  The two hosts would be flying different aircraft files. "
                  "Refusing to")
            print("  report a parity result that would be attributed to the "
                  "integration.")
            return 1

    cases = [Case(aircraft, altitude, airspeed, args.duration)
             for aircraft in args.aircraft
             for altitude, airspeed in DEFAULT_POINTS]
    # Wind for every airframe at the first envelope point. Position is in the
    # compared channels precisely for these rows: a host that quietly flew the
    # wind case in still air matches every attitude channel and misses the
    # other's ground track by hundreds of metres inside a minute.
    altitude, airspeed = DEFAULT_POINTS[0]
    cases += [Case(aircraft, altitude, airspeed, args.duration,
                   wind_speed_kt=speed, wind_from_deg=direction)
              for aircraft in args.aircraft
              for speed, direction in WIND_CASES]

    out_dir = Path(args.out)
    results = []
    for index, case in enumerate(cases, start=1):
        print(f"\n[{index}/{len(cases)}] {case.name}", flush=True)
        result = run_case(case, out_dir, runner)
        print(f"  spec {result.spec_digest[:16]}  "
              f"{'ok' if result.ok else 'FAIL ' + result.note}", flush=True)
        results.append(result)

    everything = report(results)
    print(f"\n{RULE}")
    print(f"  HOST PARITY MATRIX: {'PASS' if everything else 'FAIL'}")
    print("  Not a gate. Gate 5 is the gate; this is the breadth behind its")
    print("  single-case result. Flat terrain, hands off from trim; steady")
    print("  wind covered, turbulence and terrain not.")
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
