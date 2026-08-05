"""Gate 5 -- the same scenario, both hosts, matching trajectories.

    Identical scenario run headless and in UE produces matching trajectories
    within stated numerical tolerance. Control surfaces visibly articulate.
    Commanded roll is visible on screen. (§5 Phase 5)

Status on this machine: **BLOCKED, not failed and certainly not passed.**

The Unreal host cannot be compiled here. The cause is narrow and is not Unreal,
not macOS and not the plugin: UnrealBuildTool refuses to register Mac as a
buildable platform because the installed Xcode is outside the range UE 5.5
accepts.

    Unable to find valid SDK(s) for Mac:
      Found Sdk Version=26.6, MinRequired=15.2.0, MaxRequired=16.9.0.
    Registering build platform: Mac - buildable: False

Run ``scripts/ue_preflight.sh`` for the full diagnosis and the two remediations.

What this harness does anyway
-----------------------------
The headless half is real and runs now: it produces the reference trajectory the
UE run will be compared against, from the same spec, and writes it where the
comparison expects it. The moment the toolchain is fixed, Gate 5 is one command.

What it will not do is report a pass without a UE trajectory to compare. §5 is
explicit -- "Do not mark a gate passed on partial evidence" -- and a gate that
passes when half its evidence is missing is precisely the §1.7 failure that let
a broken run ship against a green suite.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.nl.compiler import compile_prompt  # noqa: E402
from core.scenario.runner import run_spec  # noqa: E402
from core.scenario.spec import ScenarioSpec  # noqa: E402

RULE = "=" * 96

#: Stated numerical tolerance for host parity, declared before any comparison.
#:
#: Both hosts run the same JSBSim version -- the vendoring script pins it to the
#: headless core's 1.2.4 precisely so this comparison is about the integration
#: rather than about two different physics libraries. What can still differ is
#: the substep accumulator (the plugin's own README calls its fixed rate
#: "pseudo fixed") and the ECEF round trip the plugin performs every tick.
TOLERANCE = {
    "altitude_m": 5.0,
    "tas_kt": 2.0,
    "roll_deg": 1.0,
    "pitch_deg": 1.0,
    "heading_deg": 1.0,
    "n_z": 0.05,
}

#: Channels the UE recorder writes, matching core/telemetry/recorder.py.
COMPARED = tuple(TOLERANCE)


@dataclass
class Parity:
    channel: str
    max_difference: float
    tolerance: float
    samples: int

    @property
    def ok(self) -> bool:
        return self.max_difference <= self.tolerance

    def render(self) -> str:
        return (f"  [{'ok  ' if self.ok else 'FAIL'}] {self.channel:14s} "
                f"max difference {self.max_difference:10.4f} "
                f"(tolerance {self.tolerance:g}, {self.samples} samples)")


def reference_spec(prompt: str) -> ScenarioSpec:
    spec = compile_prompt(prompt)
    # Mass held, so a divergence between hosts is the integration and not a
    # fuel-burn difference compounding over the run.
    spec.set("mass_held", True, frm="host parity comparison")
    return spec


def write_reference(spec: ScenarioSpec, out_dir: Path) -> Path:
    """Run headless and write the trajectory the UE run is compared against."""
    result = run_spec(spec)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec.write(out_dir / "scenario.yaml")
    payload = {
        "host": "headless",
        "spec_digest": spec.digest(),
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "interval_s": result.telemetry.interval_s,
        "columns": result.telemetry.columns,
    }
    path = out_dir / "headless.json"
    path.write_text(json.dumps(payload, indent=1))
    return path


def compare(headless: Path, unreal: Path) -> List[Parity]:
    a = json.loads(headless.read_text())["columns"]
    b = json.loads(unreal.read_text())["columns"]
    results = []
    for channel in COMPARED:
        if channel not in a or channel not in b:
            results.append(Parity(channel, math.inf, TOLERANCE[channel], 0))
            continue
        n = min(len(a[channel]), len(b[channel]))
        worst = max((abs(a[channel][i] - b[channel][i]) for i in range(n)),
                    default=math.inf)
        results.append(Parity(channel, worst, TOLERANCE[channel], n))
    return results


def preflight() -> Tuple[bool, str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "ue_preflight.sh"
    if not script.is_file():
        return False, "scripts/ue_preflight.sh is missing"
    proc = subprocess.run([str(script)], capture_output=True, text=True)
    return proc.returncode == 0, proc.stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 5")
    ap.add_argument("--prompt",
                    default="fly the 747 at 3000 m and 250 kt for 60 seconds")
    ap.add_argument("--out", default="runs/gate5")
    ap.add_argument("--unreal-telemetry", default=None,
                    help="trajectory written by the UE host")
    args = ap.parse_args(argv)
    out = Path(args.out)

    print(f"\n{RULE}\n1. headless reference trajectory\n{RULE}")
    spec = reference_spec(args.prompt)
    reference = write_reference(spec, out)
    payload = json.loads(reference.read_text())
    print(f"  prompt      \"{args.prompt}\"")
    print(f"  spec digest {payload['spec_digest'][:16]}")
    print(f"  wrote       {reference} ({payload['samples']} samples)")

    print(f"\n{RULE}\n2. Unreal host\n{RULE}")
    can_build, diagnosis = preflight()
    for line in diagnosis.splitlines():
        print(f"  {line}" if line.strip() else "")

    unreal_path = Path(args.unreal_telemetry) if args.unreal_telemetry else None
    if unreal_path is None or not unreal_path.is_file():
        print(f"\n{RULE}\nGATE 5\n{RULE}")
        print("  [BLOCKED] no Unreal trajectory to compare against")
        print()
        print("  The headless half of this gate ran and is correct. The Unreal")
        print("  half cannot run on this machine, so there is no second")
        print("  trajectory and nothing to compare.")
        print()
        print("  GATE 5: BLOCKED -- not passed, and not failed on the merits.")
        print("  §5: do not mark a gate passed on partial evidence.")
        return 2

    print(f"\n{RULE}\n3. host parity\n{RULE}")
    results = compare(reference, unreal_path)
    for result in results:
        print(result.render())

    everything = all(r.ok for r in results)
    print(f"\n{RULE}\nGATE 5\n{RULE}")
    print(f"  [{'PASS' if everything else 'FAIL'}] trajectories match within tolerance")
    print(f"\n  GATE 5: {'PASS' if everything else 'FAIL'}")
    return 0 if everything else 1


if __name__ == "__main__":
    raise SystemExit(main())
