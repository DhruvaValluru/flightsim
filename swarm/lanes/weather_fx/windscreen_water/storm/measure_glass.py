"""Pixel gate for swarm lane weather_fx.windscreen_water.storm. Run on the
Windows laptop on two rendered storm cockpit clips: the reference (the current
M_WindshieldRain) and the candidate (the baked path). Reads PNG frames and the
render logs; renders nothing.

Metric: glass_bandpass_rms, the RMS of the luma (0..255) between a 1 px and an
8 px Gaussian blur, averaged over the frames. It is the contrast of drop-sized
structure. A drop that only shifts a fog-grey scene scores near the no-glass
frame; a drop with a refracted, inverted view and a dark rim scores higher.

Pass (all four):
  candidate >= 1.25 x reference   the water reads where it did not
  candidate <= 14.0               and is not noise over the frame
  |p90 luma difference| <= 8      the exposure did not move
  no device-loss line in either log
The thresholds are stated, not measured. The metric says the drops are visible;
it does not say they are photoreal. Look at the frames as well.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

RATIO_MIN = 1.25
RMS_MAX = 14.0
P90_TOL = 8.0
DEVICE_LOSS = re.compile(r"device (was )?(lost|removed)|DXGI_ERROR_DEVICE_(REMOVED|HUNG|RESET)", re.I)
FRAME = re.compile(r"frame_\d+\.png")


def bandpass_rms(image: Image.Image) -> float:
    luma = image.convert("L")
    fine = np.asarray(luma.filter(ImageFilter.GaussianBlur(1.0)), dtype=np.float64)
    coarse = np.asarray(luma.filter(ImageFilter.GaussianBlur(8.0)), dtype=np.float64)
    return float(np.sqrt(np.mean((fine - coarse) ** 2)))


def measure(run: Path) -> dict:
    frames = sorted(p for p in run.rglob("frame_*.png") if FRAME.fullmatch(p.name))
    if not frames:
        raise SystemExit(f"no frame_*.png under {run}")
    rms, p90 = [], []
    for path in frames:
        with Image.open(path) as image:
            rms.append(bandpass_rms(image))
            p90.append(float(np.percentile(np.asarray(image.convert("L")), 90)))
    lost = 0
    for log in list(run.rglob("*.log")) + list(run.rglob("*.txt")):
        lost += len(DEVICE_LOSS.findall(log.read_text(encoding="utf-8", errors="replace")))
    return {"frames": len(frames), "glass_bandpass_rms": float(np.mean(rms)),
            "p90_luma": float(np.mean(p90)), "device_loss_lines": lost}


def verdict(candidate: dict, reference: dict) -> dict:
    ratio = candidate["glass_bandpass_rms"] / max(reference["glass_bandpass_rms"], 1.0e-6)
    checks = {"ratio": ratio >= RATIO_MIN, "ceiling": candidate["glass_bandpass_rms"] <= RMS_MAX,
              "exposure": abs(candidate["p90_luma"] - reference["p90_luma"]) <= P90_TOL,
              "no_device_loss": candidate["device_loss_lines"] == 0
              and reference["device_loss_lines"] == 0}
    return {"ratio": ratio, "checks": checks, "pass": all(checks.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--candidate", type=Path, required=True, help="run directory (frames, logs)")
    ap.add_argument("--reference", type=Path, required=True)
    args = ap.parse_args(argv)
    cand, ref = measure(args.candidate), measure(args.reference)
    out = {"candidate": cand, "reference": ref, **verdict(cand, ref)}
    print(json.dumps(out, indent=2))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
