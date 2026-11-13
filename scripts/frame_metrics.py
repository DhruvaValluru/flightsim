"""Per-round pixel metrics for the visual fix rounds. A report, never a gate.

    python scripts/frame_metrics.py docs/visual/round_12
    python scripts/frame_metrics.py docs/visual/round_12 --compare-with docs/visual/round_11

Ported from the max-push lane validation.pixel_metrics.alpine
(alpine_metrics.py) and generalised beyond snow: every scene's frame in a
round folder (``NN_<name>.jpg``, the copy visual_round.py writes) gets

  blank      luma std < 0.002 or mean < 0.003: the black / flat frame a
             lost D3D11 device leaves behind
  clipped    share of pixels with every channel >= 254 (blown highlights)
  crushed    share of pixels with every channel <= 1 (crushed blacks)
  mean_luma  mean linear luminance, flagged outside [0.02, 0.80]

and, when ``--compare-with`` names the previous round's folder, against the
same scene's frame there (matched on the NN number):

  ssim       mean 8x8-block SSIM of luma (low: a different, torn or broken shot)
  flicker    |mean_luma delta| between the two rounds' frames

Every threshold is UNCALIBRATED (no round has been judged against them);
``flags`` name what crossed one and nothing fails. The frames are the
round's 1280-px JPEG copies (quality 88), not the engine's PNGs: JPEG
ringing moves the clipped / crushed shares a little, and both rounds are
read the same way, so a comparison is like with like.

Writes ``<round>/metrics.json`` and prints it; exit 0 unless the folder
cannot be read at all (exit 2). visual_fix_round.ps1 ignores the exit code.
numpy + Pillow only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

#: UNCALIBRATED starting values (alpine_metrics.py's, widened where snow-
#: specific: mean_luma's band covers night and storm scenes).
LIMITS = {
    "blank_std_min": 0.002,
    "blank_mean_min": 0.003,
    "clipped_max": 0.02,
    "crushed_max": 0.05,
    "mean_luma_min": 0.02,
    "mean_luma_max": 0.80,
    "ssim_min": 0.35,
    "flicker_max": 0.02,
}
CALIBRATION = "uncalibrated: report only, no threshold has been judged against real rounds"
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
FRAME = re.compile(r"^(\d{2})_.+\.(jpg|png)$", re.I)
#: visual_round.py's other files in the same folder
NOT_A_FRAME = ("_post.jpg", "_post.png", "contact.jpg", "contact_post.jpg")


def srgb_to_linear(u8) -> np.ndarray:
    c = np.asarray(u8, dtype=np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luma(u8) -> np.ndarray:
    return srgb_to_linear(u8) @ _LUMA


def load(path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def frame_health(u8: np.ndarray) -> Dict[str, float]:
    u8 = np.asarray(u8, dtype=np.uint8)[..., :3]
    lum = luma(u8)
    return {
        "mean_luma": round(float(lum.mean()), 5),
        "std_luma": round(float(lum.std()), 5),
        "clipped": round(float((u8 >= 254).all(axis=2).mean()), 5),
        "crushed": round(float((u8 <= 1).all(axis=2).mean()), 5),
    }


def health_flags(h: Dict[str, float]) -> List[str]:
    if h["std_luma"] < LIMITS["blank_std_min"] or h["mean_luma"] < LIMITS["blank_mean_min"]:
        return ["blank"]  # nothing else means anything on a dead frame
    flags = []
    if h["clipped"] > LIMITS["clipped_max"]:
        flags.append("clipped")
    if h["crushed"] > LIMITS["crushed_max"]:
        flags.append("crushed")
    if not LIMITS["mean_luma_min"] <= h["mean_luma"] <= LIMITS["mean_luma_max"]:
        flags.append("mean_luma")
    return flags


def ssim(a_lum: np.ndarray, b_lum: np.ndarray, block: int = 8) -> float:
    """Mean SSIM over non-overlapping blocks (Wang et al. 2004 constants, L=1)."""
    h = min(a_lum.shape[0], b_lum.shape[0]) // block * block
    w = min(a_lum.shape[1], b_lum.shape[1]) // block * block
    if h == 0 or w == 0:
        return 0.0

    def blocks(x):
        return x[:h, :w].astype(np.float64).reshape(h // block, block, w // block, block) \
                .transpose(0, 2, 1, 3).reshape(-1, block * block)

    a, b = blocks(a_lum), blocks(b_lum)
    ma, mb = a.mean(1), b.mean(1)
    va, vb = a.var(1), b.var(1)
    cov = ((a - ma[:, None]) * (b - mb[:, None])).mean(1)
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    s = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2))
    return float(s.mean())


def compare(current: np.ndarray, previous: np.ndarray) -> Dict[str, object]:
    """The same scene in two rounds: SSIM and the mean-luma step (flicker)."""
    hc, hp = frame_health(current), frame_health(previous)
    out: Dict[str, object] = {"flicker": round(abs(hc["mean_luma"] - hp["mean_luma"]), 5)}
    flags = []
    if current.shape != previous.shape:
        out["ssim"] = None
        flags.append("shape_mismatch")
    else:
        out["ssim"] = round(ssim(luma(current), luma(previous)), 4)
        if out["ssim"] < LIMITS["ssim_min"]:
            flags.append("ssim")
    if out["flicker"] > LIMITS["flicker_max"]:
        flags.append("flicker")
    out["flags"] = flags
    return out


def scene_frames(folder: Path) -> Dict[str, Path]:
    """{"NN": the scene's frame} in a round folder (the first by name)."""
    found: Dict[str, Path] = {}
    for p in sorted(Path(folder).iterdir()) if Path(folder).is_dir() else ():
        if not p.is_file() or p.name.lower().endswith(NOT_A_FRAME):
            continue
        m = FRAME.match(p.name)
        if m and m.group(1) not in found:
            found[m.group(1)] = p
    return found


def round_metrics(folder: Path, compare_with: Optional[Path] = None) -> Dict[str, object]:
    folder = Path(folder)
    previous = scene_frames(compare_with) if compare_with else {}
    scenes: Dict[str, object] = {}
    for number, path in scene_frames(folder).items():
        row: Dict[str, object] = {"frame": path.name}
        try:
            current = load(path)
            row["health"] = frame_health(current)
            row["flags"] = health_flags(row["health"])
            if compare_with is not None:
                if number in previous:
                    row["vs_previous"] = {"frame": previous[number].name,
                                          **compare(current, load(previous[number]))}
                else:
                    row["vs_previous"] = None   # the scene was not in that round
        except Exception as exc:   # a bad file is said, never fatal
            row["error"] = f"{type(exc).__name__}: {exc}"
        scenes[str(int(number))] = row
    return {"calibration": CALIBRATION, "limits": LIMITS, "gate": "report only; never fails the round",
            "compare_with": str(compare_with) if compare_with else None,
            "compare_with_found": bool(compare_with and Path(compare_with).is_dir()),
            "scenes": scenes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("round_dir", type=Path)
    ap.add_argument("--compare-with", type=Path, default=None,
                    help="the previous round's folder (same-scene frames matched on NN)")
    ap.add_argument("--out", type=Path, default=None, help="default: <round_dir>/metrics.json")
    a = ap.parse_args(argv)
    if not a.round_dir.is_dir():
        print(f"frame_metrics: no folder {a.round_dir}", file=sys.stderr)
        return 2
    result = round_metrics(a.round_dir, a.compare_with)
    text = json.dumps(result, indent=1)
    (a.out or a.round_dir / "metrics.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
