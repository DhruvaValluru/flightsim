"""Pixel gate for the coastal sun / time-of-day lane. Run on the Windows
laptop on two rendered frames of the same coastal shot (the Mac only
unit-tests the arithmetic on synthetic images; that is not a result).

    python swarm\\lanes\\lighting_exposure\\sun_time_of_day\\coastal\\measure_exposure.py ^
        --baseline <baseline frame> --baseline-ev100 <its EV100> ^
        --candidate <candidate frame> --target-ev100 <table EV100>

Metrics (JSON on stdout, exit 0 on pass, 1 on fail):
  ev_error_stops     median log2(candidate / baseline) of sRGB-decoded
                     luminance over pixels whose BASELINE luminance is
                     mid-tone (0.02..0.50 linear), minus the expected shift
                     (baseline EV100 - target EV100). Pass: |error| <= 0.3.
  clip_fraction      share of pixels with every channel >= 250 (sea glitter
                     and the sun disc clip by design). Pass: candidate
                     <= 0.03 and candidate <= baseline + 0.005.
  crush_fraction     share of pixels with every channel <= 4. Pass:
                     candidate <= 0.05.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

GATE_EV = 0.3
CLIP_LEVEL, CLIP_MAX, CLIP_RISE_MAX = 250, 0.03, 0.005
CRUSH_LEVEL, CRUSH_MAX = 4, 0.05
MID_LO, MID_HI = 0.02, 0.50
MIN_MID_PIXELS = 1000


def linear_luma(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def _fraction(image: Image.Image, clipped: bool) -> float:
    rgb = np.asarray(image.convert("RGB"))
    hit = rgb.min(axis=2) >= CLIP_LEVEL if clipped else rgb.max(axis=2) <= CRUSH_LEVEL
    return float(hit.mean())


def measure(baseline: Image.Image, candidate: Image.Image,
            baseline_ev100: float, target_ev100: float) -> dict:
    if baseline.size != candidate.size:
        candidate = candidate.resize(baseline.size, Image.BILINEAR)
    base, cand = linear_luma(baseline), linear_luma(candidate)
    mask = (base >= MID_LO) & (base <= MID_HI) & (cand > 1e-4)
    count = int(mask.sum())
    if count < MIN_MID_PIXELS:
        return {"pass": False,
                "refused": f"only {count} mid-tone pixels to compare (need {MIN_MID_PIXELS})"}
    measured = float(np.median(np.log2(cand[mask] / base[mask])))
    expected = float(baseline_ev100) - float(target_ev100)   # higher EV100 = darker
    error = measured - expected
    base_clip, cand_clip = _fraction(baseline, True), _fraction(candidate, True)
    crush = _fraction(candidate, False)
    ev_ok = abs(error) <= GATE_EV
    clip_ok = cand_clip <= CLIP_MAX and cand_clip <= base_clip + CLIP_RISE_MAX
    crush_ok = crush <= CRUSH_MAX
    return {
        "measured_shift_stops": round(measured, 3),
        "expected_shift_stops": round(expected, 3),
        "ev_error_stops": round(error, 3),
        "ev_gate_stops": GATE_EV,
        "mid_tone_pixels": count,
        "clip_fraction": {"baseline": round(base_clip, 5), "candidate": round(cand_clip, 5),
                          "max": CLIP_MAX},
        "crush_fraction": {"candidate": round(crush, 5), "max": CRUSH_MAX},
        "ev_pass": ev_ok, "clip_pass": clip_ok, "crush_pass": crush_ok,
        "pass": bool(ev_ok and clip_ok and crush_ok),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-ev100", type=float, required=True,
                        help="exposure.ev100 from the baseline run's beauty_look.json")
    parser.add_argument("--target-ev100", type=float, required=True,
                        help="exposure.ev100 from the candidate run's beauty_look.json "
                             "(the coastal table's target_ev100 for the shot's sun)")
    args = parser.parse_args(argv)
    result = measure(Image.open(args.baseline), Image.open(args.candidate),
                     args.baseline_ev100, args.target_ev100)
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
