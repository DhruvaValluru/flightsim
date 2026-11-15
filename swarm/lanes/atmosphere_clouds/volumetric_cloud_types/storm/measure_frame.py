#!/usr/bin/env python3
"""The pixel gate for atmosphere_clouds.volumetric_cloud_types.storm.

Runs on the WINDOWS laptop against frames it rendered (Pillow is in
requirements.txt). On the Mac only the arithmetic is tested, on synthetic
images; that is not a visual result.

Regions: sky = rows above ``--horizon-row`` (a fraction of the height) less a
margin, ground = rows below it plus the margin. All values are sRGB-decoded
luma, so they are display-referred: the tone curve sits between them and the
scene.

    under_deck_error_ev = | log2(median sky / median ground) - expected |
        expected = baked gate.expected_sky_over_ground_stops (a Lambert ground
        of the shared albedo under the baked dome)
    sky_contrast_stops  = log2(p95 sky / p05 sky)
    black_fraction      = share of sky pixels under black_floor x median sky

PASS when under_deck_error_ev <= 1.0, black_fraction <= 0.02,
|sky_contrast_stops - expected contrast| <= 1.0 and, with ``--reference``,
under_deck_error_ev is no larger than the reference frame's. Exit 0 on pass,
1 on fail, 2 on usage.

    .venv\\Scripts\\python.exe swarm\\lanes\\atmosphere_clouds\\volumetric_cloud_types\\storm\\measure_frame.py ^
        --frame <candidate.png> --reference <reference.png> --horizon-row 0.5
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

GATE_JSON = Path(__file__).resolve().parent / "baked" / "storm_cloud_types.json"
MARGIN = 0.05


def srgb_eotf(v: float) -> float:
    v = min(max(v, 0.0), 1.0)
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


LINEAR = [srgb_eotf(i / 255.0) for i in range(256)]


def percentile(hist: Sequence[int], q: float) -> float:
    """Decoded luma at quantile q of a 256-bin histogram."""
    total = sum(hist)
    if total <= 0:
        raise ValueError("empty region")
    need, run = q * total, 0
    for i, c in enumerate(hist):
        run += c
        if run >= need and c:
            return LINEAR[i]
    return LINEAR[255]


def fraction_below(hist: Sequence[int], level: float) -> float:
    return sum(c for i, c in enumerate(hist) if LINEAR[i] < level) / float(sum(hist))


def load_gate() -> Dict[str, float]:
    return json.loads(GATE_JSON.read_text(encoding="utf-8"))["gate"]


def measure(image: Any, horizon_row: float, gate: Dict[str, float]) -> Dict[str, float]:
    """``image`` is a PIL image; returns the metrics of one frame."""
    luma = image.convert("L")
    w, h = luma.size
    sky_end = max(1, int((horizon_row - MARGIN) * h))
    ground_start = min(h - 1, int((horizon_row + MARGIN) * h))
    sky = luma.crop((0, 0, w, sky_end)).histogram()
    ground = luma.crop((0, ground_start, w, h)).histogram()
    sky_med, ground_med = percentile(sky, 0.5), percentile(ground, 0.5)
    floor = 1.0 / 255.0 / 12.92
    ratio = math.log2(max(sky_med, floor) / max(ground_med, floor))
    contrast = math.log2(max(percentile(sky, 0.95), floor) / max(percentile(sky, 0.05), floor))
    return {
        "sky_over_ground_stops": ratio,
        "under_deck_error_ev": abs(ratio - gate["expected_sky_over_ground_stops"]),
        "sky_contrast_stops": contrast,
        "sky_contrast_error_stops": abs(contrast - gate["expected_sky_contrast_stops"]),
        "black_fraction": fraction_below(sky, gate["black_floor_relative_to_sky_median"] * sky_med),
    }


def verdict(cand: Dict[str, float], ref: Optional[Dict[str, float]], gate: Dict[str, float]) -> Dict[str, Any]:
    tol = gate["tolerance_stops"]
    checks = {
        "under_deck_error_ev": cand["under_deck_error_ev"] <= tol,
        "black_fraction": cand["black_fraction"] <= gate["max_black_fraction"],
        "sky_contrast": cand["sky_contrast_error_stops"] <= tol,
    }
    if ref is not None:
        checks["not_worse_than_reference"] = cand["under_deck_error_ev"] <= ref["under_deck_error_ev"] + 1e-9
    return {"pass": all(checks.values()), "checks": checks, "candidate": cand, "reference": ref}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frame", required=True)
    ap.add_argument("--reference")
    ap.add_argument("--horizon-row", type=float, default=0.5)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if not 0.1 <= args.horizon_row <= 0.9:
        print("--horizon-row must be between 0.1 and 0.9", file=sys.stderr)
        return 2
    from PIL import Image

    gate = load_gate()
    cand = measure(Image.open(args.frame), args.horizon_row, gate)
    ref = measure(Image.open(args.reference), args.horizon_row, gate) if args.reference else None
    out = verdict(cand, ref, gate)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
