"""Pixel gate for the alpine aircraft PBR lane. Runs on the Windows laptop on
two finished, LABELLED beauty runs of the same card and seed:

    reference: -aircraft-materials=on -aircraft-probe=flat
    candidate: -aircraft-materials=on -aircraft-alpine-pbr=tier0

    .\\.venv\\Scripts\\python.exe swarm\\lanes\\aircraft_exterior\\pbr_materials\\alpine\\measure_gate.py ^
        --reference runs\\swarm\\alpine_pbr\\flat\\frames --candidate runs\\swarm\\alpine_pbr\\tier0\\frames

Per frame pair, inside the primary airframe's mask (frame_NNNN_mask.png,
int_id 1, eroded 2 px so the silhouette edge does not count):

  luminance_ratio  = mean Rec.709 luma (candidate) / mean luma (reference)
  dark_share       = share of mask pixels under 24/255 (candidate)
  detail_ratio     = variance of the 3x3 Laplacian of luma, candidate / reference

PASS when, on every frame: 0.85 <= luminance_ratio <= 1.15, dark_share is at
most the reference's + 0.02, and detail_ratio >= 1.10. Exit 0 pass, 1 fail,
3 refused (no masks, size mismatch, mask under 400 px). It measures encoded
pixels; it says nothing about realism beyond those three numbers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

LUMA_LO, LUMA_HI = 0.85, 1.15
DARK_LEVEL = 24.0
DARK_SHARE_SLACK = 0.02
DETAIL_MIN = 1.10
MIN_MASK_PX = 400
AIRFRAME_ID = 1


def luma(rgb):
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def erode(mask, px=2):
    m = mask.copy()
    for _ in range(px):
        n = m.copy()
        n[1:, :] &= m[:-1, :]
        n[:-1, :] &= m[1:, :]
        n[:, 1:] &= m[:, :-1]
        n[:, :-1] &= m[:, 1:]
        n[0, :] = n[-1, :] = False
        n[:, 0] = n[:, -1] = False
        m = n
    return m


def laplacian(y):
    out = np.zeros_like(y)
    out[1:-1, 1:-1] = (y[:-2, 1:-1] + y[2:, 1:-1] + y[1:-1, :-2] + y[1:-1, 2:]
                       - 4.0 * y[1:-1, 1:-1])
    return out


def measure(ref_rgb, cand_rgb, mask):
    """All arrays float/bool, images 0..255. Returns the metrics dict."""
    m = erode(mask)
    count = int(m.sum())
    if count < MIN_MASK_PX:
        raise ValueError(f"airframe mask is {count} px after erosion, under {MIN_MASK_PX}")
    yr, yc = luma(ref_rgb), luma(cand_rgb)
    inner = erode(m, 1)                      # Laplacian support stays in the mask
    var_r = float(laplacian(yr)[inner].var())
    var_c = float(laplacian(yc)[inner].var())
    out = {
        "mask_px": count,
        "reference_mean_luma": float(yr[m].mean()),
        "candidate_mean_luma": float(yc[m].mean()),
        "luminance_ratio": float(yc[m].mean() / max(yr[m].mean(), 1e-6)),
        "reference_dark_share": float((yr[m] < DARK_LEVEL).mean()),
        "dark_share": float((yc[m] < DARK_LEVEL).mean()),
        "detail_ratio": var_c / max(var_r, 1e-9),
    }
    out["pass_luminance"] = LUMA_LO <= out["luminance_ratio"] <= LUMA_HI
    out["pass_dark_share"] = out["dark_share"] <= out["reference_dark_share"] + DARK_SHARE_SLACK
    out["pass_detail"] = out["detail_ratio"] >= DETAIL_MIN
    out["pass"] = out["pass_luminance"] and out["pass_dark_share"] and out["pass_detail"]
    return out


def _frames(folder):
    return sorted(p for p in Path(folder).rglob("frame_*.png") if re.fullmatch(r"frame_\d+", p.stem))


def main(argv=None):
    from PIL import Image

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reference", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    ref, cand = _frames(args.reference), _frames(args.candidate)
    if not ref or len(ref) != len(cand):
        print(f"REFUSED gate.frames: {len(ref)} reference and {len(cand)} candidate frames")
        return 3
    rows, ok = [], True
    for r, c in zip(ref, cand):
        mask_path = r.with_name(r.stem + "_mask.png")
        if not mask_path.exists():
            print(f"REFUSED gate.mask: no {mask_path} (render the reference with labels on)")
            return 3
        a = np.asarray(Image.open(r).convert("RGB"), dtype=np.float64)
        b = np.asarray(Image.open(c).convert("RGB"), dtype=np.float64)
        mask = np.asarray(Image.open(mask_path).convert("L")) == AIRFRAME_ID
        if a.shape != b.shape or mask.shape != a.shape[:2]:
            print(f"REFUSED gate.size: {r.name} {a.shape} vs {b.shape} vs mask {mask.shape}")
            return 3
        try:
            row = measure(a, b, mask)
        except ValueError as exc:
            print(f"REFUSED gate.mask_small: {r.name}: {exc}")
            return 3
        row["frame"] = r.name
        rows.append(row)
        ok = ok and row["pass"]
        print(f"{r.name}: luma x{row['luminance_ratio']:.3f} dark {row['dark_share']:.3f} "
              f"(ref {row['reference_dark_share']:.3f}) detail x{row['detail_ratio']:.2f} "
              f"{'PASS' if row['pass'] else 'FAIL'}")
    report = {"gate": "aircraft_exterior.pbr_materials.alpine", "pass": ok, "frames": rows,
              "thresholds": {"luminance_ratio": [LUMA_LO, LUMA_HI], "dark_share_slack": DARK_SHARE_SLACK,
                             "detail_ratio_min": DETAIL_MIN, "dark_level": DARK_LEVEL}}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print("GATE PASS" if ok else "GATE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
