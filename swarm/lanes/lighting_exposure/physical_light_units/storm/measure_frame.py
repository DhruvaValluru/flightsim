#!/usr/bin/env python3
"""The pixel gate for lighting_exposure.physical_light_units.storm.

Runs on the WINDOWS laptop against frames it rendered (Pillow is in
requirements.txt). On the Mac only the arithmetic is tested.

Metric, ``ev_error``: display-referred stops between the frame's
90th-percentile sRGB luma and the calibrated look's target (0.40 for a storm
under a deck, the host's StormMeterTargetDefault and
beauty_look.EXPOSURE_METER_TARGET_P90["storm"]):

    ev_error = log2( eotf(p90) / eotf(target) )      eotf = sRGB decode

PASS when |ev_error| <= 0.3, the clipped fraction (luma >= 254/255) is at
most 1 %, and, with ``--reference``, the candidate is no further from the
target than the reference frame is. Exit 0 on pass, 1 on fail, 2 on usage.

    .venv\\Scripts\\python.exe swarm\\lanes\\lighting_exposure\\physical_light_units\\storm\\measure_frame.py ^
        --frame <candidate.png> --reference <reference.png>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, Optional, Sequence

GATE_EV = 0.3
TARGET_P90 = 0.40
MAX_CLIPPED_FRACTION = 0.01
PERCENTILE = 0.90


def srgb_eotf(v: float) -> float:
    v = min(max(v, 0.0), 1.0)
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def percentile_from_histogram(hist: Sequence[int], q: float = PERCENTILE) -> float:
    """The q-th percentile of an 8-bit histogram, 0..1."""
    total = sum(hist)
    if total <= 0:
        raise ValueError("empty histogram")
    want = q * total
    run = 0
    for level, n in enumerate(hist):
        run += n
        if run >= want:
            return level / 255.0
    return 1.0


def frame_stats(hist: Sequence[int], target: float = TARGET_P90) -> Dict[str, float]:
    p90 = percentile_from_histogram(hist)
    total = float(sum(hist))
    return {
        "p90_srgb_luma": round(p90, 4),
        "target_p90_srgb_luma": target,
        "ev_error": round(math.log2(max(srgb_eotf(p90), 1e-6) / srgb_eotf(target)), 3),
        "clipped_fraction": round(sum(hist[254:]) / total, 5),
    }


def verdict(candidate: Dict[str, float], reference: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    reasons = []
    if abs(candidate["ev_error"]) > GATE_EV:
        reasons.append(f"|ev_error| {abs(candidate['ev_error']):.3f} > {GATE_EV}")
    if candidate["clipped_fraction"] > MAX_CLIPPED_FRACTION:
        reasons.append(f"clipped {candidate['clipped_fraction']:.4f} > {MAX_CLIPPED_FRACTION}")
    if reference is not None and abs(candidate["ev_error"]) > abs(reference["ev_error"]):
        reasons.append("further from the target than the reference frame")
    return {"pass": not reasons, "reasons": reasons, "candidate": candidate, "reference": reference}


def luma_histogram(path: str) -> Sequence[int]:
    from PIL import Image  # the laptop's venv; not needed for the arithmetic

    with Image.open(path) as im:
        return im.convert("RGB").convert("L", matrix=(0.2126, 0.7152, 0.0722, 0.0)).histogram()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--frame", required=True, help="candidate beauty frame (PNG)")
    ap.add_argument("--reference", default=None, help="the reference frame of the same shot (PNG)")
    ap.add_argument("--target-p90", type=float, default=TARGET_P90,
                    help="the applied meter target (look_applied.storm_exposure target_p90_luma)")
    args = ap.parse_args(argv)
    cand = frame_stats(luma_histogram(args.frame), args.target_p90)
    ref = frame_stats(luma_histogram(args.reference), args.target_p90) if args.reference else None
    out = verdict(cand, ref)
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
