"""CPU resolver for the alpine capture ladder (runs on the laptop's CPU; no GPU).

Takes the pass PNGs one tier of alpine_capture_ladder.json asked for, drops
the gutters, averages the sub-pixel samples in linear light, stitches the
tiles, dithers to 8 bits with the baked blue-noise tile and writes the
delivered frame plus a Lanczos fit to the 1536x960 panel.

    python resolve_capture.py --tier 2 --passes runs\\alpine_ladder_t2 --out runs\\alpine_ladder_t2.png

Visual-only. A pass smaller than planned (tier 0 step-down) is Lanczos-resized
to the planned size first.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent


def srgb_to_linear(u8: np.ndarray) -> np.ndarray:
    c = u8.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)


def dither_to_u8(srgb: np.ndarray, noise: np.ndarray) -> np.ndarray:
    """Mean-preserving ordered dither: floor(v*255 + threshold), threshold in (0, 1)."""
    h, w = srgb.shape[:2]
    n = noise.shape[0]
    thr = (np.tile(noise, (h // n + 1, w // n + 1))[:h, :w].astype(np.float64) + 0.5) / 256.0
    return np.clip(np.floor(srgb * 255.0 + thr[..., None]), 0, 255).astype(np.uint8)


def resolve(tier: dict, load_pass, noise: np.ndarray) -> np.ndarray:
    """tier: one entry of plan['tiers']; load_pass(pass) -> HxWx3 uint8."""
    w, h = tier["delivered_px"]
    rw, rh = tier["pass_render_px"]
    pw, ph = tier["payload_px"]
    g = tier["gutter_px"]
    acc = np.zeros((h, w, 3))
    for p in tier["passes"]:
        img = np.asarray(load_pass(p))[..., :3]
        if img.shape[:2] != (rh, rw):
            from PIL import Image
            img = np.asarray(Image.fromarray(img).resize((rw, rh), Image.LANCZOS))
        x, y = p["paste_px"]
        acc[y:y + ph, x:x + pw] += p["weight"] * srgb_to_linear(img[g:g + ph, g:g + pw])
    return dither_to_u8(linear_to_srgb(acc), noise)


def sample_spread(tier: dict, load_pass) -> float:
    """Worst median |difference| of 8x8 block means between a tile's first pass
    and its other sub-pixel passes, in 8-bit levels. Sub-pixel shifts leave
    block means almost unchanged; a moving camera or drifting exposure do not."""
    def blocks(p):
        g = np.asarray(load_pass(p))[..., :3].astype(np.float64).mean(axis=2)
        h, w = g.shape[0] // 8 * 8, g.shape[1] // 8 * 8
        return g[:h, :w].reshape(h // 8, 8, w // 8, 8).mean(axis=(1, 3))

    worst, first = 0.0, {}
    for p in tier["passes"]:
        key = tuple(p["tile"])
        if key not in first:
            first[key] = blocks(p)
        else:
            worst = max(worst, float(np.median(np.abs(blocks(p) - first[key]))))
    return worst


def load_noise(lane: Path = LANE) -> np.ndarray:
    raw = np.frombuffer((lane / "blue_noise_64.r8").read_bytes(), np.uint8)
    n = int(round(raw.size ** 0.5))
    return raw.reshape(n, n)


def main() -> None:
    from PIL import Image
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, required=True)
    ap.add_argument("--passes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    plan = json.loads((LANE / "alpine_capture_ladder.json").read_text())
    tier = next(t for t in plan["tiers"] if t["tier"] == a.tier)
    missing = [p["file"] for p in tier["passes"] if not (a.passes / p["file"]).exists()]
    if missing:
        raise SystemExit(f"tier {a.tier}: missing passes {missing}; refusing to resolve a partial frame")
    load = lambda p: Image.open(a.passes / p["file"]).convert("RGB")
    out = resolve(tier, load, load_noise())
    report = {"tier": a.tier, "sample_spread_levels": sample_spread(tier, load)}
    a.out.with_suffix(".resolve.json").write_text(json.dumps(report) + "\n")
    Image.fromarray(out).save(a.out)
    fit = a.out.with_name(a.out.stem + "_display.png")
    Image.fromarray(out).resize(tuple(plan["target"]["display_px"]), Image.LANCZOS).save(fit)
    print(f"wrote {a.out} and {fit}")


if __name__ == "__main__":
    main()
