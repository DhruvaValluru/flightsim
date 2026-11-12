#!/usr/bin/env python3
"""Helpers that make the pixel gate runnable TODAY, with no shared file changed.

The exposure offsets are applied through a field the project already has,
``lighting.brightness_ev`` (stops on the calibrated exposure, positive =
brighter), on a spec that ``scripts/run_test_scenarios.py --spec-dir`` pinned
and replays. The eye's offset_ev is positive = closed = darker, so
brightness_ev = -offset_ev.

    gate_tool.py specs --pinned runs\\eye_gate\\reference\\06.json
        writes runs\\eye_gate\\<variant>\\06.json for each variant below

    gate_tool.py stash <name>
        copies the first frame of the last batch's run (runs/test_scenarios.json)
        to runs\\eye_gate\\<name>.png

Stdlib only. Renders nothing itself.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

REPO = Path(__file__).resolve().parents[5]
GATE_DIR = REPO / "runs" / "eye_gate"
SUMMARY = REPO / "runs" / "test_scenarios.json"
RUNS = REPO / "runs" / "webapp"

#: variant -> the eye's offset_ev it stands for (positive = closed = darker).
VARIANTS: Dict[str, float] = {
    "eye_closed": 0.25,       # the eye's close clamp
    "eye_open": -0.25,        # the eye's open clamp
    "bracket_dark": 0.3,      # the gate's edges
    "bracket_bright": -0.3,
}


def variant_spec(pinned: dict, offset_ev: float) -> dict:
    """The pinned record with lighting.brightness_ev set as a user edit
    (the shape scripts/run_test_scenarios.py apply_lighting writes)."""
    out = copy.deepcopy(pinned)
    entry = out["spec"]["lighting"]["brightness_ev"]
    base = float(entry.get("value") or 0.0)
    entry.update(value=round(base - offset_ev, 4), source="user",
                 **{"from": "swarm/lanes/lighting_exposure/eye_adaptation/night_ifr/gate_tool.py"})
    return out


def write_specs(pinned_path: Path, out_dir: Path) -> Dict[str, str]:
    pinned = json.loads(pinned_path.read_text(encoding="utf-8"))
    written = {}
    for name, offset in VARIANTS.items():
        target = out_dir / name / pinned_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(variant_spec(pinned, offset), indent=1, sort_keys=True),
                          encoding="utf-8")
        written[name] = str(target)
    return written


def first_frame(run_dir: Path) -> Optional[Path]:
    """The same pick as scripts/run_test_scenarios.py collect()."""
    frames = run_dir / "frames"
    for camera in sorted(d for d in frames.glob("*") if d.is_dir()) if frames.is_dir() else []:
        found = sorted(camera.glob("frame_*[0-9].png"))
        if found:
            return found[0]
    return None


def stash(name: str, summary: Path = SUMMARY, runs: Path = RUNS, out_dir: Path = GATE_DIR) -> Path:
    data = json.loads(summary.read_text(encoding="utf-8"))
    results = data.get("results", []) if isinstance(data, dict) else data
    done = [r for r in results if r.get("run_id")]
    if len(done) != 1:
        raise SystemExit(f"{summary}: expected exactly one run in the last batch, found {len(done)}")
    if done[0].get("outcome") in ("failed", "refused"):
        raise SystemExit(f"the last run {done[0].get('outcome')}: {done[0].get('why', '')}")
    frame = first_frame(runs / str(done[0]["run_id"]))
    if frame is None:
        raise SystemExit(f"no frame_*.png under {runs / str(done[0]['run_id'])}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}.png"
    shutil.copyfile(frame, target)
    return target


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("specs")
    s.add_argument("--pinned", required=True)
    s.add_argument("--out", default=str(GATE_DIR))
    t = sub.add_parser("stash")
    t.add_argument("name")
    a = p.parse_args(argv)
    if a.cmd == "specs":
        for name, path in write_specs(Path(a.pinned), Path(a.out)).items():
            print(f"{name}: {path}")
    else:
        print(stash(a.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
