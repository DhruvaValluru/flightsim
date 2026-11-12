"""Frame-health pixel metrics for alpine captures. numpy + Pillow only, CPU only.

Visual-only validation. Every threshold here is an UNCALIBRATED starting value:
no alpine frame from the Windows laptop has been through this code yet.

The functions take arrays (H, W, 3 uint8 sRGB), so the arithmetic is checked
on the Mac with synthetic frames. That is a code check, never a visual result.

Checks on one frame:
  blank            luma std < 0.002 or mean < 0.003: the black / flat frame a
                   lost D3D11 device leaves behind.
  snow_clip        share of pixels with every channel >= 254      <= 0.02
  crushed          share of pixels with every channel <= 1        <= 0.05
  snow_chroma      mean (max-min)/max of linear RGB over the brightest 5 % of
                   unclipped pixels (sunlit snow must stay near neutral) <= 0.12
  mean_luma        mean linear luminance within [0.05, 0.60]
Against a reference frame of the same shot:
  ssim             mean 8x8-block SSIM of luma >= 0.35 (same shot, not a
                   different or torn frame)
  detail_ratio     mean |Laplacian| candidate / reference >= 0.95
  penalty          clip/0.02 + crushed/0.05 + chroma/0.12; candidate must be
                   <= reference + 0.05
Over a frame sequence (tiers 2-3):
  flicker          mean |delta mean_luma| between consecutive frames <= 0.02
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

LIMITS = {
    "blank_std_min": 0.002,
    "blank_mean_min": 0.003,
    "snow_clip_max": 0.02,
    "crushed_max": 0.05,
    "snow_chroma_max": 0.12,
    "mean_luma_min": 0.05,
    "mean_luma_max": 0.60,
    "ssim_min": 0.35,
    "detail_ratio_min": 0.95,
    "penalty_slack": 0.05,
    "flicker_max": 0.02,
}
TIER_WIDTH = {0: 640, 1: 1280, 2: 640, 3: 1280}
_LUMA = np.array([0.2126, 0.7152, 0.0722])


def srgb_to_linear(u8) -> np.ndarray:
    c = np.asarray(u8, dtype=np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def luma(u8) -> np.ndarray:
    return srgb_to_linear(u8) @ _LUMA.astype(np.float32)


def load(path, max_width: Optional[int] = None) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        if max_width and im.width > max_width:
            h = max(1, round(im.height * max_width / im.width))
            im = im.resize((max_width, h), Image.BOX)
        return np.asarray(im, dtype=np.uint8)


def laplacian_energy(lum: np.ndarray) -> float:
    lap = np.abs(4.0 * lum[1:-1, 1:-1] - lum[:-2, 1:-1] - lum[2:, 1:-1]
                 - lum[1:-1, :-2] - lum[1:-1, 2:])
    return float(lap.mean())


def frame_health(u8: np.ndarray) -> Dict[str, float]:
    lin = srgb_to_linear(u8)
    lum = lin @ _LUMA.astype(np.float32)
    clipped = (u8 >= 254).all(axis=2)
    crushed = (u8 <= 1).all(axis=2)
    usable = ~clipped
    chroma = 0.0
    if usable.any():
        cut = np.quantile(lum[usable], 0.95)
        sel = usable & (lum >= cut)
        px = lin[sel]
        mx = px.max(axis=1)
        chroma = float(((mx - px.min(axis=1)) / np.maximum(mx, 1e-6)).mean())
    out = {
        "mean_luma": float(lum.mean()),
        "std_luma": float(lum.std()),
        "snow_clip": float(clipped.mean()),
        "crushed": float(crushed.mean()),
        "snow_chroma": chroma,
        "laplacian": laplacian_energy(lum),
    }
    out["penalty"] = (out["snow_clip"] / LIMITS["snow_clip_max"]
                      + out["crushed"] / LIMITS["crushed_max"]
                      + out["snow_chroma"] / LIMITS["snow_chroma_max"])
    return out


def health_failures(h: Dict[str, float]) -> List[str]:
    bad = []
    if h["std_luma"] < LIMITS["blank_std_min"] or h["mean_luma"] < LIMITS["blank_mean_min"]:
        return ["blank"]  # nothing else means anything on a dead frame
    if h["snow_clip"] > LIMITS["snow_clip_max"]:
        bad.append("snow_clip")
    if h["crushed"] > LIMITS["crushed_max"]:
        bad.append("crushed")
    if h["snow_chroma"] > LIMITS["snow_chroma_max"]:
        bad.append("snow_chroma")
    if not LIMITS["mean_luma_min"] <= h["mean_luma"] <= LIMITS["mean_luma_max"]:
        bad.append("mean_luma")
    return bad


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


def compare(candidate: np.ndarray, reference: np.ndarray) -> Dict[str, object]:
    """Candidate against reference; both (H, W, 3) uint8 of the same shot."""
    hc, hr = frame_health(candidate), frame_health(reference)
    fails = health_failures(hc)
    out: Dict[str, object] = {"candidate": hc, "reference": hr}
    if candidate.shape != reference.shape:
        fails.append("shape_mismatch")
    elif "blank" not in fails:
        out["ssim"] = ssim(luma(candidate), luma(reference))
        out["detail_ratio"] = hc["laplacian"] / max(hr["laplacian"], 1e-9)
        out["penalty_delta"] = hc["penalty"] - hr["penalty"]
        if out["ssim"] < LIMITS["ssim_min"]:
            fails.append("ssim")
        if out["detail_ratio"] < LIMITS["detail_ratio_min"]:
            fails.append("detail_ratio")
        if out["penalty_delta"] > LIMITS["penalty_slack"]:
            fails.append("penalty")
    out["failures"] = fails
    out["pass"] = not fails
    return out


def sequence(healths: List[Dict[str, float]]) -> Dict[str, object]:
    """Blank-frame and flicker check over the per-frame health of one run."""
    blank = [i for i, h in enumerate(healths) if "blank" in health_failures(h)]
    means = np.array([h["mean_luma"] for h in healths])
    flicker = float(np.abs(np.diff(means)).mean()) if len(means) > 1 else 0.0
    fails = (["blank_frames"] if blank else []) + (["flicker"] if flicker > LIMITS["flicker_max"] else [])
    return {"frames": len(healths), "blank_frames": blank, "flicker": flicker, "failures": fails}


def frame_files(path) -> List[Path]:
    """A PNG, or a run directory: its beauty PNGs in name order."""
    p = Path(path)
    if p.is_file():
        return [p]
    return sorted(q for q in p.rglob("*.png")) if p.is_dir() else []
