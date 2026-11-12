"""Pixel gate for the alpine physical-light-units lane. Run on the Windows
laptop against two rendered frames of scenario 11 (never on the Mac for a
result; the Mac only unit-tests the arithmetic on synthetic images).

    python swarm\\lanes\\lighting_exposure\\physical_light_units\\alpine\\measure_exposure.py ^
        --baseline <baseline frame> --baseline-ev100 <its EV100> ^
        --candidate <candidate frame> --target-ev100 <table EV100>

Metrics (printed as JSON, exit 0 on pass, 1 on fail):
  ev_error_stops       measured exposure shift minus the expected shift
                       (baseline EV100 - target EV100). Measured as the median
                       log2(candidate / baseline) of sRGB-decoded luminance
                       over pixels whose BASELINE luminance is mid-tone
                       (0.02..0.50 linear), where the filmic curve is close to
                       unit slope. Pass: |ev_error_stops| <= 0.3.
  snow_clip_fraction   share of pixels with every channel >= 250. Pass:
                       candidate <= 0.01 and candidate <= baseline.
The tonemapper's toe and shoulder compress the shift outside the mid-tones,
which is why they are masked out; the residual slope error is part of what
the Windows run measures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

GATE_EV = 0.3
CLIP_LEVEL = 250
CLIP_MAX_FRACTION = 0.01
MID_LO, MID_HI = 0.02, 0.50
MIN_MID_PIXELS = 1000


def linear_luma(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def clip_fraction(image: Image.Image) -> float:
    rgb = np.asarray(image.convert("RGB"))
    return float((rgb.min(axis=2) >= CLIP_LEVEL).mean())


def measure(baseline: Image.Image, candidate: Image.Image,
            baseline_ev100: float, target_ev100: float) -> dict:
    if baseline.size != candidate.size:
        candidate = candidate.resize(baseline.size, Image.BILINEAR)
    base, cand = linear_luma(baseline), linear_luma(candidate)
    mask = (base >= MID_LO) & (base <= MID_HI) & (cand > 1e-4)
    count = int(mask.sum())
    if count < MIN_MID_PIXELS:
        return {"pass": False, "refused": f"only {count} mid-tone pixels to compare (need {MIN_MID_PIXELS})"}
    # A higher EV100 is a darker frame: log2(cand/base) = baseline EV - candidate EV.
    measured = float(np.median(np.log2(cand[mask] / base[mask])))
    expected = float(baseline_ev100) - float(target_ev100)
    error = measured - expected
    base_clip, cand_clip = clip_fraction(baseline), clip_fraction(candidate)
    ev_ok = abs(error) <= GATE_EV
    clip_ok = cand_clip <= CLIP_MAX_FRACTION and cand_clip <= base_clip + 1e-9
    return {
        "measured_shift_stops": round(measured, 3),
        "expected_shift_stops": round(expected, 3),
        "ev_error_stops": round(error, 3),
        "ev_gate_stops": GATE_EV,
        "mid_tone_pixels": count,
        "snow_clip_fraction": {"baseline": round(base_clip, 5), "candidate": round(cand_clip, 5),
                               "max": CLIP_MAX_FRACTION},
        "ev_pass": ev_ok, "clip_pass": clip_ok, "pass": bool(ev_ok and clip_ok),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-ev100", type=float, required=True,
                        help="exposure.ev100 the baseline frame was rendered at (its beauty_look.json)")
    parser.add_argument("--target-ev100", type=float, required=True,
                        help="target_ev100 from alpine_plu.json for the shot's altitude and sun")
    args = parser.parse_args(argv)
    result = measure(Image.open(args.baseline), Image.open(args.candidate),
                     args.baseline_ev100, args.target_ev100)
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
