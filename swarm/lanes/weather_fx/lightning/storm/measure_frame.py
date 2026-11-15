#!/usr/bin/env python3
"""weather_fx.lightning.storm pixel gate (WX.5): does a stroke frame show the channel?

Runs on the Windows laptop on frames it rendered. On the Mac only its
arithmetic is tested, on synthetic images; that is not a visual result.

  measure_frame.py --frames <run>\\frames\\<camera> [--reference-frames <ref run>\\frames\\<camera>]

For each consecutive pair of frames it takes the linear-luma difference, removes
the frame-wide lift (median) and reads the 99.95th percentile: the brightest
thin structure that appeared. The stroke pair is the largest, the quiet pair the
median one.

  stroke_contrast = stroke pair's peak / quiet pair's peak     gate: >= 3.0
  halo_ratio      = mean residual 4..40 px from the channel / mean on it  (reported)

With --reference-frames the candidate must also keep the channel:
stroke_contrast >= 0.9 x the reference's. A clip with no cloud-to-ground stroke
(weather.lightning.flashes of the run's card says which frames have one) gives
NOT EXERCISED, exit 2: neither a pass nor a fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from PIL import Image

STROKE_CONTRAST_MIN = 3.0
KEEP_OF_REFERENCE = 0.9
SHOW_MIN_LINEAR = 0.02      # a stroke pair's peak below this is no channel at all
PEAK_PERCENTILE = 99.95
NEAR_PX, FAR_PX = 4, 40


def linear_luma(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def residual(lit: np.ndarray, dark: np.ndarray) -> np.ndarray:
    diff = lit - dark
    return diff - np.median(diff)


def peak(res: np.ndarray) -> float:
    return float(np.percentile(res, PEAK_PERCENTILE))


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Box dilation by an integral image (no SciPy on the laptop's venv assumed)."""
    h, w = mask.shape
    pad = np.zeros((h + 2 * radius + 1, w + 2 * radius + 1))
    pad[radius + 1:radius + 1 + h, radius + 1:radius + 1 + w] = mask
    integral = pad.cumsum(0).cumsum(1)
    k = 2 * radius + 1
    return (integral[k:, k:] - integral[:-k, k:] - integral[k:, :-k] + integral[:-k, :-k]) > 0.5


def halo_ratio(res: np.ndarray) -> Optional[float]:
    top = peak(res)
    if top <= 0.0:
        return None
    core = res >= 0.5 * top
    band = _dilate(core, FAR_PX) & ~_dilate(core, NEAR_PX)
    if not core.any() or not band.any():
        return None
    return float(res[band].mean() / res[core].mean())


def measure(frames: Sequence[np.ndarray]) -> Dict[str, Any]:
    if len(frames) < 3:
        return {"exercised": False, "why": "fewer than three frames"}
    peaks: List[float] = [peak(residual(frames[i], frames[i - 1])) for i in range(1, len(frames))]
    best = int(np.argmax(peaks))
    quiet = float(np.median(peaks))
    stroke = peaks[best]
    if stroke < SHOW_MIN_LINEAR:
        return {"exercised": False, "why": "no pair of frames differs by a bright thin structure",
                "stroke_peak_linear": stroke, "quiet_peak_linear": quiet}
    return {"exercised": True, "stroke_frame_index": best + 1,
            "stroke_peak_linear": stroke, "quiet_peak_linear": quiet,
            "stroke_contrast": stroke / max(quiet, 1.0e-6),
            "halo_ratio": halo_ratio(residual(frames[best + 1], frames[best]))}


def load(folder: Path) -> List[np.ndarray]:
    paths = sorted(p for p in folder.glob("frame_*.png") if p.stem.rsplit("_", 1)[-1].isdigit())
    return [linear_luma(Image.open(p)) for p in paths]


def verdict(candidate: Dict[str, Any], reference: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidate.get("exercised"):
        return {"result": "NOT EXERCISED", "exit": 2}
    ok = candidate["stroke_contrast"] >= STROKE_CONTRAST_MIN
    if reference is not None and reference.get("exercised"):
        ok = ok and candidate["stroke_contrast"] >= KEEP_OF_REFERENCE * reference["stroke_contrast"]
    return {"result": "PASS" if ok else "FAIL", "exit": 0 if ok else 1}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--frames", required=True, type=Path, help="the candidate run's frames/<camera>")
    ap.add_argument("--reference-frames", type=Path, default=None)
    args = ap.parse_args(argv)
    candidate = measure(load(args.frames))
    reference = measure(load(args.reference_frames)) if args.reference_frames else None
    out = {"candidate": candidate, "reference": reference, **verdict(candidate, reference),
           "gate": {"stroke_contrast_min": STROKE_CONTRAST_MIN, "keep_of_reference": KEEP_OF_REFERENCE}}
    print(json.dumps(out, indent=2))
    return int(out["exit"])


if __name__ == "__main__":
    sys.exit(main())
