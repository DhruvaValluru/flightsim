"""The storm airframe pixel gate: is the aircraft darker, and is it wetter?

Runs on the WINDOWS laptop on two rendered storm frames of the same shot
(base = HEAD without this lane, head = with it), each with its ID mask
(``frame_NNNN_mask.png``, non-zero = a labelled object; the measure-quality
twin of the shot supplies it). Never run on the Mac for a result: the Mac
has no frames. The Mac's test only feeds it synthetic arrays.

    python measure_aircraft_gate.py --base-frame B.png --base-mask B_mask.png \
        --head-frame H.png --head-mask H_mask.png [--aircraft-id N] [--out gate.json]

Metrics (sRGB luma 0..255, aircraft pixels only):

* ``dark_ratio``   = head median / base median.           PASS >= 0.97
  (the no-dark-aircraft gate: the lane may not darken the airframe)
* ``floor_ratio``  = head 5th percentile / base 5th.      PASS >= 0.90
  (its darkest panels may not sink either)
* ``sheen_gain``   = head (p99 - p50) / base (p99 - p50). PASS >= 1.10
  (the improvement: a wet clear coat throws a wider highlight)
* ``clip_share``   = head share of aircraft pixels >= 250. PASS <= 0.02

Exit 0 only when all four pass.
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

THRESHOLDS = {"dark_ratio_min": 0.97, "floor_ratio_min": 0.90, "sheen_gain_min": 1.10,
              "clip_share_max": 0.02}
MIN_PIXELS = 400


def luma(rgb):
    rgb = np.asarray(rgb, dtype=float)
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def aircraft_stats(rgb, mask, aircraft_id=None):
    mask = np.asarray(mask)
    if mask.shape != np.asarray(rgb).shape[:2]:
        raise ValueError(f"storm_pbr.gate: mask {mask.shape} does not match frame {np.asarray(rgb).shape[:2]}")
    sel = (mask == aircraft_id) if aircraft_id is not None else (mask > 0)
    if int(sel.sum()) < MIN_PIXELS:
        raise ValueError(f"storm_pbr.gate: {int(sel.sum())} aircraft pixels, need {MIN_PIXELS}")
    y = luma(rgb)[sel]
    p05, p50, p99 = (float(v) for v in np.percentile(y, [5, 50, 99]))
    return {"pixels": int(sel.sum()), "p05": p05, "p50": p50, "p99": p99,
            "sheen": p99 - p50, "clip_share": float((y >= 250).mean())}


def gate(base_rgb, base_mask, head_rgb, head_mask, aircraft_id=None):
    b = aircraft_stats(base_rgb, base_mask, aircraft_id)
    h = aircraft_stats(head_rgb, head_mask, aircraft_id)
    m = {"dark_ratio": h["p50"] / max(b["p50"], 1e-6),
         "floor_ratio": h["p05"] / max(b["p05"], 1e-6),
         "sheen_gain": h["sheen"] / max(b["sheen"], 1e-6),
         "clip_share": h["clip_share"]}
    checks = {"dark_ratio": m["dark_ratio"] >= THRESHOLDS["dark_ratio_min"],
              "floor_ratio": m["floor_ratio"] >= THRESHOLDS["floor_ratio_min"],
              "sheen_gain": m["sheen_gain"] >= THRESHOLDS["sheen_gain_min"],
              "clip_share": m["clip_share"] <= THRESHOLDS["clip_share_max"]}
    return {"base": b, "head": h, "metrics": m, "thresholds": THRESHOLDS, "checks": checks,
            "pass": bool(all(checks.values()))}


def main(argv=None):
    from PIL import Image

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    for name in ("base-frame", "base-mask", "head-frame", "head-mask"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--aircraft-id", type=int, default=None, help="default: every non-zero ID")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    def rgb(p):
        return np.asarray(Image.open(p).convert("RGB"))

    def ids(p):
        return np.asarray(Image.open(p).convert("L"))

    try:
        result = gate(rgb(a.base_frame), ids(a.base_mask), rgb(a.head_frame), ids(a.head_mask), a.aircraft_id)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    text = json.dumps(result, indent=2)
    if a.out:
        with open(a.out, "w") as handle:
            handle.write(text + "\n")
    print(text)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
