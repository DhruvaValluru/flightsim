"""Offline generator (Mac): the alpine gate manifest and the calibration frames.

    python swarm/lanes/validation/pixel_metrics/alpine/build_gate_manifest.py

Writes, next to this file:
  alpine_gates.json     every alpine lane's gate script, its arguments (read
                        from the script's AST; no lane script is imported or
                        executed here) and the script's sha256.
  shot.template.json    the one file the Windows operator fills in.
  calib/*.png + calib/expected.json
                        tiny synthetic frames with the metric values this
                        code computes for them, so the laptop can prove its
                        numpy/Pillow give the same numbers before measuring.

Nothing here is a rendered or visual result.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Dict, List

import numpy as np

LANE = Path(__file__).resolve().parent
LANES_ROOT = LANE.parents[2]          # swarm/lanes
REPO = LANES_ROOT.parents[1]
SCENARIO = LANE.name                  # "alpine"
SELF_ID = "validation.pixel_metrics." + SCENARIO
GATE_GLOBS = ("measure_*.py", "*gate*.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args(source: str) -> Dict[str, object]:
    """Literal `add_argument("--name", ...)` calls. Anything built at run time
    (a loop, a concatenated name) is flagged `dynamic`, not guessed."""
    required: List[str] = []
    optional: List[str] = []
    flags: List[str] = []
    dynamic = False
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument" and node.args):
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            dynamic = True
            continue
        if not first.value.startswith("--"):
            dynamic = True  # positional: the runner cannot place it
            continue
        name = first.value[2:]
        kw = {k.arg: k.value for k in node.keywords}
        action = kw.get("action")
        if isinstance(action, ast.Constant) and action.value in ("store_true", "store_false"):
            flags.append(name)
        elif isinstance(kw.get("required"), ast.Constant) and kw["required"].value is True:
            required.append(name)
        else:
            optional.append(name)
    return {"required": required, "optional": optional, "flags": flags, "dynamic": dynamic}


def scan(lanes_root: Path = LANES_ROOT, scenario: str = SCENARIO) -> List[Dict[str, object]]:
    gates = []
    for lane_dir in sorted(lanes_root.glob(f"*/*/{scenario}")):
        lane_id = ".".join(lane_dir.relative_to(lanes_root).parts)
        if lane_id == SELF_ID:
            continue
        for script in sorted({p for g in GATE_GLOBS for p in lane_dir.glob(g)}):
            entry = {"lane": lane_id,
                     "script": script.relative_to(lanes_root.parents[1]).as_posix(),
                     "sha256": sha256(script)}
            entry.update(parse_args(script.read_text(encoding="utf-8")))
            gates.append(entry)
    return gates


def template(gates: List[Dict[str, object]]) -> Dict[str, object]:
    counts: Dict[str, int] = {}
    for g in gates:
        for a in g["required"]:
            counts[a] = counts.get(a, 0) + 1
    common = {a: None for a, n in sorted(counts.items()) if n > 1}
    lanes = {g["lane"]: {a: None for a in g["required"] if a not in common} for g in gates}
    return {
        "_help": "Fill every null. 'health' feeds this lane's own frame check; 'common' feeds any "
                 "gate that declares that argument; 'lanes' overrides or adds per lane (true = bare "
                 "flag). A gate with a null left in it is reported UNMEASURED, never skipped silently. "
                 "Check each lane's INTEGRATION.md: 'reference'/'candidate' are run DIRECTORIES for the "
                 "aircraft lanes and PNG files for the others, so set them per lane where they differ.",
        "health": {"reference": None, "candidate": None},
        "common": common,
        "lanes": lanes,
    }


# ---- calibration frames -------------------------------------------------

def calib_frames() -> Dict[str, np.ndarray]:
    h, w = 96, 160
    rng = np.random.default_rng(20261112)
    ramp = np.linspace(40, 235, w)[None, :, None].repeat(h, 0).repeat(3, 2)
    tex = np.clip(ramp + rng.normal(0, 6, (h, w, 1)), 2, 250).astype(np.uint8)
    clipped = tex.copy()
    clipped[:, : w // 10] = 255                       # 10 % blown snow
    blue = tex.astype(float)
    blue[..., 0] *= 0.70                              # snow gone blue
    blue[..., 1] *= 0.85
    crushed = tex.copy()
    crushed[: h // 4] = 0                             # 25 % crushed
    return {
        "neutral": tex,
        "black": np.zeros((h, w, 3), np.uint8),
        "clipped": clipped,
        "blue_snow": blue.astype(np.uint8),
        "crushed": crushed,
    }


def bake_calib(out: Path) -> Dict[str, object]:
    import sys
    from PIL import Image

    sys.path.insert(0, str(LANE))
    import alpine_metrics as am

    out.mkdir(parents=True, exist_ok=True)
    expected = {}
    for name, arr in calib_frames().items():
        path = out / f"{name}.png"
        Image.fromarray(arr).save(path, optimize=False)
        h = am.frame_health(am.load(path))
        expected[name] = {"pixels_sha256": hashlib.sha256(arr.tobytes()).hexdigest(),
                          "health": h, "failures": am.health_failures(h)}
    (out / "expected.json").write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n")
    return expected


def main() -> int:
    gates = scan()
    manifest = {
        "lane": SELF_ID,
        "label": "visual-only",
        "generator": "build_gate_manifest.py",
        "exit_codes": "0 pass, 1 fail, anything else = the gate could not measure",
        "gates": gates,
    }
    (LANE / "alpine_gates.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (LANE / "shot.template.json").write_text(json.dumps(template(gates), indent=1) + "\n")
    expected = bake_calib(LANE / "calib")
    print(json.dumps({"gates": len(gates), "calib_frames": len(expected)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
