#!/usr/bin/env python3
"""The pixel gate for weather_fx.rain_drops.storm, as ONE command (Windows).

    .venv\\Scripts\\python.exe swarm\\lanes\\weather_fx\\rain_drops\\storm\\run_gate.py

UNMEASURED: this has never run on the laptop. VISUAL-ONLY.

What it does, with no path or frame for the operator to fill in:

1. Takes scenario 9's prompt from scripts/run_test_scenarios.py (SCENARIOS[8]).
2. Renders it four times, one after the other, with
   scripts/debug_storm_render.py (the commandlet directly, no web app, so the
   rain gain is this process's flag and not a server's environment):

       <out>/reference/off   -weather-backend=procedural -rain-gain=0   FLIGHTSIM_RAIN_TIER=3
       <out>/reference/on    -weather-backend=procedural -rain-gain=4   FLIGHTSIM_RAIN_TIER=3
       <out>/candidate/off   -weather-backend=procedural -rain-gain=0   FLIGHTSIM_RAIN_TIER=0
       <out>/candidate/on    -weather-backend=procedural -rain-gain=4   FLIGHTSIM_RAIN_TIER=0

   <out> is runs/swarm_gate/weather_fx_rain_drops_storm. Every leg writes its
   frames to <leg>/procedural/frames/frame_NNNN.png and its manifest to
   <leg>/procedural/frames/render.json (debug_storm_render.py's own layout).
   The off frame is the SAME backend at gain 0, so the clouds, fog and light
   are the same render path; by reading FlightSimWeather.cpp the procedural
   drops and splashes are drawn with Weight x RainGain = 0 (not verified on a
   frame: ``veil_delta`` in the output is the evidence either way).
3. Picks the last frame_NNNN.png present in BOTH legs of a pair.
4. Reference = the build's particle rain; its measured streak angle is the
   expected angle for the candidate (same card, same frame number, so the same
   camera roll and wind; nothing about scenario 9's pose is assumed here).
5. Candidate = this lane's baked layers. FLIGHTSIM_RAIN_TIER and the
   ``drawn_as: "baked_layers"`` record are PROPOSED in INTEGRATION.md and do not
   exist in the build yet. Until render.json says drawn_as = baked_layers the
   candidate is not measured: the verdict is NOT INTEGRATED, exit 3, and the
   reference numbers are still written (they are the baseline).

Exit: 0 PASS, 1 FAIL, 2 usage, 3 not measurable (not integrated, a leg did not
render, no common frame, or no expected angle). Only 0 is a pass. The result is
printed and written to <out>/gate.json.

    --only reference     the baseline alone (two renders)
    --reference-tier N   1 or 2 when 262,144 drops lose the device
    --expected-deg N     the operator's angle when no reference can be rendered
    --measure-only       no rendering: measure the frames already under <out>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[4]
OUT = REPO / "runs" / "swarm_gate" / "weather_fx_rain_drops_storm"
SCENARIO_NUMBER = 9
BACKEND = "procedural"
RAIN_GAIN_ON = 4.0            # the web app's default (webapp/runs.py WEATHER_DEFAULT_GAIN)
RAIN_STYLE = "cinematic"
SECONDS = 1.0                 # debug_storm_render.py renders at 5 fps: 5 frames a leg
TIER_ENV = "FLIGHTSIM_RAIN_TIER"   # PROPOSED (INTEGRATION.md step 4); the build ignores it today
CANDIDATE_TIER = 0
DRAWN_AS = "baked_layers"
FRAME = re.compile(r"frame_\d+\.png")
NOT_MEASURABLE = 3


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scenario_prompt() -> str:
    scenarios = _module("swarm_gate_scenarios", REPO / "scripts" / "run_test_scenarios.py").SCENARIOS
    return scenarios[SCENARIO_NUMBER - 1][1]


def leg_dir(out: Path, role: str, leg: str) -> Path:
    return Path(out) / role / leg


def frames_dir(out: Path, role: str, leg: str) -> Path:
    return leg_dir(out, role, leg) / BACKEND / "frames"


def leg_command(out: Path, role: str, leg: str, prompt: str) -> List[str]:
    gain = RAIN_GAIN_ON if leg == "on" else 0.0
    return [sys.executable, str(REPO / "scripts" / "debug_storm_render.py"),
            "--backend", BACKEND, "--prompt", prompt, "--seconds", f"{SECONDS:g}",
            "--rain-gain", f"{gain:g}", "--rain-style", RAIN_STYLE,
            "--out", str(leg_dir(out, role, leg))]


def render_leg(out: Path, role: str, leg: str, prompt: str, tier: int) -> int:
    env = dict(os.environ)
    env[TIER_ENV] = str(tier)
    return subprocess.run(leg_command(out, role, leg, prompt), cwd=str(REPO), env=env).returncode


def find_key(node: Any, key: str) -> List[Any]:
    """Every value stored under ``key`` anywhere in a JSON tree."""
    found: List[Any] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            found.extend(find_key(v, key))
    elif isinstance(node, list):
        for v in node:
            found.extend(find_key(v, key))
    return found


def manifest(out: Path, role: str, leg: str) -> Optional[dict]:
    path = frames_dir(out, role, leg) / "render.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def recorded_gain(man: Optional[dict]) -> Optional[float]:
    """The rain row's ``gain`` as the build recorded it, or None."""
    for row in find_key(man, "rain"):
        if isinstance(row, dict) and isinstance(row.get("gain"), (int, float)):
            return float(row["gain"])
    return None


def common_frame(on_dir: Path, off_dir: Path) -> Optional[str]:
    names = lambda d: {p.name for p in Path(d).glob("frame_*.png") if FRAME.fullmatch(p.name)}
    both = sorted(names(on_dir) & names(off_dir))
    return both[-1] if both else None


def measure_pair(out: Path, role: str, measure_mod) -> Dict[str, Any]:
    """One role's on/off pair: the frames used, what the build recorded, the numbers."""
    on_dir, off_dir = frames_dir(out, role, "on"), frames_dir(out, role, "off")
    row: Dict[str, Any] = {"role": role, "on_dir": str(on_dir), "off_dir": str(off_dir),
                           "problems": []}
    on_man, off_man = manifest(out, role, "on"), manifest(out, role, "off")
    for leg, man in (("on", on_man), ("off", off_man)):
        if man is None:
            row["problems"].append(f"{leg}: no render.json (the leg did not render)")
    row["gain_recorded"] = {"on": recorded_gain(on_man), "off": recorded_gain(off_man)}
    if on_man is not None and row["gain_recorded"]["on"] not in (None, RAIN_GAIN_ON):
        row["problems"].append(f"on: the build recorded rain gain {row['gain_recorded']['on']}")
    if off_man is not None and row["gain_recorded"]["off"] not in (None, 0.0):
        row["problems"].append(f"off: the build recorded rain gain {row['gain_recorded']['off']}, not 0")
    row["drawn_as"] = sorted({str(v) for v in find_key(on_man, "drawn_as")})
    name = common_frame(on_dir, off_dir)
    row["frame"] = name
    if name is None:
        row["problems"].append("no frame_NNNN.png present in both legs")
    if row["problems"]:
        row["metrics"] = None
        return row
    try:
        row["metrics"] = measure_mod.measure(measure_mod._load(str(on_dir / name)),
                                             measure_mod._load(str(off_dir / name)))
    except (OSError, ValueError) as error:
        row["metrics"] = None
        row["problems"].append(f"frames not measurable: {error}")
    return row


def gate(out: Path, only: Optional[str] = None, reference_tier: int = 3,
         expected_deg: Optional[float] = None, measure_only: bool = False,
         render: Callable[..., int] = render_leg, prompt: Optional[str] = None,
         measure_mod=None) -> Dict[str, Any]:
    measure_mod = measure_mod or _module("swarm_gate_measure", LANE / "measure_frame.py")
    out = Path(out)
    roles = [only] if only else ["reference", "candidate"]
    tiers = {"reference": reference_tier, "candidate": CANDIDATE_TIER}
    result: Dict[str, Any] = {"item": "weather_fx.rain_drops.storm", "scenario": SCENARIO_NUMBER,
                              "out": str(out), "exit_codes": {}}
    if not measure_only:
        prompt = prompt or scenario_prompt()
        result["prompt"] = prompt
        for role in roles:
            for leg in ("off", "on"):
                # 0 RENDERED; 1 also covers RENDERED-DARK, which still wrote frames.
                result["exit_codes"][f"{role}/{leg}"] = render(out, role, leg, prompt, tiers[role])
    rows = {role: measure_pair(out, role, measure_mod) for role in roles}
    result.update(rows)
    reference = (rows.get("reference") or {}).get("metrics")
    if reference is None and only != "reference":
        saved = out / "reference.json"
        if saved.is_file() and "reference" not in rows:
            reference = json.loads(saved.read_text(encoding="utf-8"))
    if rows.get("reference", {}).get("metrics") is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "reference.json").write_text(json.dumps(rows["reference"]["metrics"], indent=1,
                                                       sort_keys=True), encoding="utf-8")
    if only == "reference":
        ok = reference is not None
        result["verdict"] = ("REFERENCE RECORDED (the build's particle rain; not this lane's layers)"
                             if ok else "REFERENCE NOT MEASURABLE")
        result["exit"] = 0 if ok else NOT_MEASURABLE
        return result
    candidate = rows["candidate"]
    if candidate["metrics"] is None:
        result["verdict"], result["exit"] = "CANDIDATE NOT MEASURABLE", NOT_MEASURABLE
    elif DRAWN_AS not in candidate["drawn_as"]:
        result["verdict"] = (f"NOT INTEGRATED: render.json does not record drawn_as = {DRAWN_AS!r}, so "
                             "the candidate frames are not this lane's layers and are not judged")
        result["exit"] = NOT_MEASURABLE
    else:
        judged = measure_mod.verdict(candidate["metrics"], expected_deg, reference)
        result["judged"] = judged
        if not judged["complete"]:
            result["verdict"] = "NO EXPECTED ANGLE: no reference pair and no --expected-deg"
            result["exit"] = NOT_MEASURABLE
        else:
            result["verdict"] = "PASS" if judged["passed"] else "FAIL"
            result["exit"] = 0 if judged["passed"] else 1
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--only", choices=("reference", "candidate"), default=None)
    parser.add_argument("--reference-tier", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--expected-deg", type=float, default=None)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args(argv)
    result = gate(args.out, args.only, args.reference_tier, args.expected_deg, args.measure_only)
    text = json.dumps(result, indent=1, sort_keys=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gate.json").write_text(text, encoding="utf-8")
    print(text)
    print(result["verdict"])
    return int(result["exit"])


if __name__ == "__main__":
    sys.exit(main())
