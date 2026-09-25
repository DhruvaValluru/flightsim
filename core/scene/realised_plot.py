"""A picture of the realised distribution: one bar chart per sampled
leaf, requested bins on the axis, frames per bin as the bars, the
coverage in the title (contracts §5.5: "'varied' is then a number with
a picture").

    .venv/bin/python -m core.scene.realised_plot runs/campaign/runs/* \\
        --out realised.png [--json realised.json] [--k 1]

Reads each run's ``capture_manifest.json`` through
``core.scenario.randomization.realised_distribution`` -- the same
numbers the campaign report carries -- and draws them with Pillow (in
the venv). No numbers are computed here that the JSON does not also
state: the picture is a rendering of the record, not a second
analysis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BAR_W = 28
ROW_H = 150
MARGIN = 24
FONT_H = 12


def _font():
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=FONT_H)
    except TypeError:              # older Pillow: no size argument
        return ImageFont.load_default()


def draw_realised(realised: Dict[str, Any], out: Path) -> Path:
    """Write the PNG for a ``realised_distribution`` result."""
    from PIL import Image, ImageDraw

    fields: Dict[str, Any] = realised.get("fields", {})
    names: List[str] = sorted(fields)
    widest = max((len(f["histogram"]) for f in fields.values()), default=1)
    width = max(640, MARGIN * 2 + widest * (BAR_W + 6))
    height = MARGIN * 2 + max(1, len(names)) * ROW_H + FONT_H * 2
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
    draw.text((MARGIN, 4), f"realised distribution: {realised.get('runs', 0)} runs, "
                           f"{realised.get('frames', 0)} frames, coverage "
                           f"{realised.get('coverage')} (k={realised.get('k', 1)})",
              fill="black", font=font)
    y = MARGIN + FONT_H
    for name in names:
        entry = fields[name]
        hist: Dict[str, int] = entry["histogram"]
        peak = max(hist.values(), default=1) or 1
        draw.text((MARGIN, y), f"{name}: coverage {entry['coverage']} over "
                               f"{entry['bins']} bins, {entry['frames']} frames",
                  fill="black", font=font)
        base = y + ROW_H - FONT_H * 2
        x = MARGIN
        for label, count in hist.items():
            h = int((ROW_H - FONT_H * 4) * count / peak)
            colour = (70, 110, 180) if count >= realised.get("k", 1) else (200, 60, 60)
            draw.rectangle([x, base - h, x + BAR_W, base], fill=colour)
            draw.text((x, base + 2), label[:6], fill="black", font=font)
            draw.text((x, base - h - FONT_H), str(count), fill="black", font=font)
            x += BAR_W + 6
        y += ROW_H
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("runs", nargs="+", help="run directories")
    parser.add_argument("--out", required=True, help="PNG to write")
    parser.add_argument("--json", help="also write the numbers here")
    parser.add_argument("--k", type=int, default=1,
                        help="frames a bin needs to count as covered")
    args = parser.parse_args(argv)
    from core.scenario.randomization import realised_distribution

    realised = realised_distribution([Path(r) for r in args.runs], k=args.k)
    if args.json:
        Path(args.json).write_text(json.dumps(realised, indent=1, sort_keys=True),
                                   encoding="utf-8")
    path = draw_realised(realised, Path(args.out))
    print(f"realised: {realised['runs']} runs, {realised['frames']} frames, "
          f"coverage {realised['coverage']} -> {path}")
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
