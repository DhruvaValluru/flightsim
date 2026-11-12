#!/usr/bin/env python3
"""The pixel arithmetic of the weather_fx.rain_drops.storm gate.

``run_gate.py`` (same directory) is the one command: it renders the frames on
the WINDOWS laptop, picks them and calls this. On the Mac only the arithmetic is
tested, on synthetic input.

Two frames of the same card and frame number, rain drawn and rain not drawn.
D = luma(on) - luma(off), display-referred, split by a 15-pixel box blur into a
slow part (haze, exposure, anything that is not a streak) and a fast part F.
From F's structure tensor J = sum(grad F grad F^T):

    streak_angle_deg   the streaks' direction from the image vertical
    coherence          (l1 - l2) / (l1 + l2): 1 = parallel lines, 0 = noise
    rain_delta         mean |F|: how much the streaks changed the frame
    veil_delta         mean |slow part|: reported, not gated (a large value
                       says the two frames differ in more than streaks)

Metric, ``orientation_error_deg`` = |streak_angle_deg - expected| (mod 180),
where ``expected`` is the reference pair's own streak_angle_deg (the build's
particle rain on the same card), or a number the operator states. With neither
the orientation is NOT evaluated and the verdict is not a pass. PASS when the
error is at most 10 deg, coherence >= 0.35, rain_delta is in [0.004, 0.10], and
coherence is no more than 0.05 under the reference's. The thresholds are
STATED, not measured.

    .venv\\Scripts\\python.exe swarm\\lanes\\weather_fx\\rain_drops\\storm\\measure_frame.py ^
        --on ON.png --off OFF.png [--expected-deg N] [--reference-on REF_ON.png --reference-off REF_OFF.png]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, Optional, Sequence

import numpy as np

GATE_ANGLE_DEG = 10.0
GATE_COHERENCE = 0.35
GATE_DELTA = (0.004, 0.10)
REFERENCE_SLACK = 0.05
BLUR_PX = 15


def box_blur(a: np.ndarray, size: int = BLUR_PX) -> np.ndarray:
    """The mean over a size x size window, edges repeated (numpy only)."""
    r = size // 2
    p = np.pad(a, r, mode="edge")
    c = np.pad(p.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = a.shape
    return (c[size:size + h, size:size + w] - c[:h, size:size + w]
            - c[size:size + h, :w] + c[:h, :w]) / float(size * size)


def luma(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float64)[..., :3] / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def angle_error_deg(a: float, b: float) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def measure(on: np.ndarray, off: np.ndarray) -> Dict[str, float]:
    """``on`` / ``off``: (H, W, 3+) uint8 sRGB of the same size."""
    if on.shape[:2] != off.shape[:2]:
        raise ValueError(f"frames differ in size: {on.shape[:2]} and {off.shape[:2]}")
    d = luma(on) - luma(off)
    slow = box_blur(d)
    d = d - slow
    gy, gx = np.gradient(d)
    jxx, jyy, jxy = float((gx * gx).sum()), float((gy * gy).sum()), float((gx * gy).sum())
    root = math.hypot(jxx - jyy, 2.0 * jxy)
    total = jxx + jyy
    # The gradient's dominant direction from +x is the streaks' from the vertical.
    return {"streak_angle_deg": 0.5 * math.degrees(math.atan2(2.0 * jxy, jxx - jyy)),
            "coherence": root / total if total > 0.0 else 0.0,
            "rain_delta": float(np.abs(d).mean()),
            "veil_delta": float(np.abs(slow).mean())}


def verdict(candidate: Dict[str, float], expected_deg: Optional[float] = None,
            reference: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """``expected_deg`` None takes the reference's streak angle; with neither,
    the orientation check is None (not evaluated) and ``passed`` is False."""
    basis = "stated by the operator"
    if expected_deg is None and reference is not None:
        expected_deg, basis = reference["streak_angle_deg"], "the reference pair's streak angle"
    error = None if expected_deg is None else angle_error_deg(candidate["streak_angle_deg"], expected_deg)
    checks: Dict[str, Optional[bool]] = {
        "orientation": None if error is None else error <= GATE_ANGLE_DEG,
        "coherence": candidate["coherence"] >= GATE_COHERENCE,
        "delta": GATE_DELTA[0] <= candidate["rain_delta"] <= GATE_DELTA[1],
    }
    if reference is not None:
        checks["not_worse_than_reference"] = (
            candidate["coherence"] >= reference["coherence"] - REFERENCE_SLACK)
    return {"orientation_error_deg": error, "expected_deg": expected_deg,
            "expected_basis": basis if expected_deg is not None else "none: orientation NOT evaluated",
            "candidate": candidate, "reference": reference, "checks": checks,
            "complete": error is not None,
            "passed": all(v is True for v in checks.values())}


def _load(path: str) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--on", required=True)
    parser.add_argument("--off", required=True)
    parser.add_argument("--expected-deg", type=float, default=None,
                        help="the streaks' expected direction from the image vertical "
                             "(default: the reference pair's)")
    parser.add_argument("--reference-on")
    parser.add_argument("--reference-off")
    args = parser.parse_args(argv)
    if bool(args.reference_on) != bool(args.reference_off):
        parser.error("--reference-on and --reference-off go together")
    reference = measure(_load(args.reference_on), _load(args.reference_off)) if args.reference_on else None
    result = verdict(measure(_load(args.on), _load(args.off)), args.expected_deg, reference)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0 if result["passed"] else (1 if result["complete"] else 3)


if __name__ == "__main__":
    sys.exit(main())
