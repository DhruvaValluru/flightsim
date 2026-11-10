"""Before and after, scene by scene: two visual rounds side by side.

Reads ``docs/visual/round_<A>/`` and ``round_<B>/`` (scripts/visual_round.py)
and writes ``docs/visual/compare_<A>_<B>/``: for every scene in both rounds
``NN_<name>.jpg`` (A left, B right, labelled), ``contact.jpg`` (every pair on
one sheet) and ``compare.json`` (per scene: mean absolute luminance change,
the share of pixels that moved more than 8 levels, and each round's mean
luminance, so "darker" or "brighter" is a number). A scene in one round only
is listed, never silently dropped.

    python scripts/visual_compare.py 0 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
VISUAL = REPO / "docs" / "visual"
PAIR_WIDTH = 640
MOVED = 8


def _scenes(folder: Path) -> dict:
    return {p.stem: p for p in sorted(folder.glob("[0-9]*.jpg"))}


def _luma(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=float)


def compare(a: int, b: int, root: Path = VISUAL) -> Path:
    left, right = _scenes(root / f"round_{a}"), _scenes(root / f"round_{b}")
    if not left or not right:
        raise SystemExit(f"round_{a} or round_{b} has no frames under {root}")
    out = root / f"compare_{a}_{b}"
    out.mkdir(parents=True, exist_ok=True)
    rows, pairs = [], []
    for name in sorted(set(left) | set(right)):
        if name not in left or name not in right:
            rows.append({"scene": name, "only_in": f"round_{a}" if name in left else f"round_{b}"})
            continue
        x, y = Image.open(left[name]).convert("RGB"), Image.open(right[name]).convert("RGB")
        if y.size != x.size:
            y = y.resize(x.size)
        lx, ly = _luma(x), _luma(y)
        delta = np.abs(lx - ly)
        rows.append({"scene": name, "mean_abs_change": round(float(delta.mean()), 2),
                     "moved_share": round(float((delta > MOVED).mean()), 4),
                     f"mean_luma_{a}": round(float(lx.mean()), 1),
                     f"mean_luma_{b}": round(float(ly.mean()), 1)})
        h = round(x.height * PAIR_WIDTH / x.width)
        pair = Image.new("RGB", (2 * PAIR_WIDTH + 8, h + 22), (16, 20, 24))
        pair.paste(x.resize((PAIR_WIDTH, h)), (0, 22))
        pair.paste(y.resize((PAIR_WIDTH, h)), (PAIR_WIDTH + 8, 22))
        draw = ImageDraw.Draw(pair)
        draw.text((4, 4), f"round {a}: {name[:50]}", fill=(220, 225, 230))
        draw.text((PAIR_WIDTH + 12, 4), f"round {b}", fill=(220, 225, 230))
        pair.save(out / f"{name}.jpg", quality=88)
        pairs.append(pair)
    if pairs:
        width = max(p.width for p in pairs)
        sheet = Image.new("RGB", (width, sum(p.height for p in pairs)), (16, 20, 24))
        y0 = 0
        for p in pairs:
            sheet.paste(p, (0, y0))
            y0 += p.height
        sheet.save(out / "contact.jpg", quality=82)
    (out / "compare.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("before", type=int)
    parser.add_argument("after", type=int)
    args = parser.parse_args()
    out = compare(args.before, args.after)
    for row in json.loads((out / "compare.json").read_text(encoding="utf-8")):
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
