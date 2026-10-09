"""Say what a rendered run's label images actually hold, in text.

The annotation gates say THAT a mask is wrong (mask_integers_only,
mask_vs_geometry); this says what is in it, so a failure on the owner's
machine can be diagnosed from a paste instead of a guess: per camera, the
id values each ``frame_NNNN_mask.png`` carries and how many pixels each,
the ids no object owns, and what every ``_alone_<id>.png`` holds.

    .venv\\Scripts\\python.exe scripts\\label_diagnose.py RUN_DIR [--frames N]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


def histogram(path: Path) -> Counter:
    values, counts = np.unique(np.asarray(Image.open(path)), return_counts=True)
    return Counter({int(v): int(c) for v, c in zip(values, counts)})


def describe(counts: Counter) -> str:
    return ", ".join(f"{value}:{count}" for value, count in sorted(counts.items()))


def camera(render_json: Path, frames: int) -> None:
    directory = render_json.parent
    render = json.loads(render_json.read_text(encoding="utf-8"))
    owned = {int(o["int_id"]) for o in render.get("objects") or []
             if isinstance(o, dict) and "int_id" in o}
    settings = render.get("render_settings") or {}
    print(f"\n== {directory}")
    print(f"   rhi {settings.get('rhi')!r}, declared ids "
          f"{sorted(owned) or 'none recorded'}")
    masks = sorted(directory.glob("frame_*_mask.png"))
    if not masks:
        print("   no frame_*_mask.png here: the run was not rendered with labels")
        return
    stray_total: Counter = Counter()
    for index, mask in enumerate(masks):
        counts = histogram(mask)
        stray = Counter({v: c for v, c in counts.items() if v and v not in owned})
        stray_total.update(stray)
        if index < frames:
            print(f"   {mask.name}: {describe(counts)}"
                  + (f"   STRAY {describe(stray)}" if stray else ""))
            stem = mask.name[:-len("_mask.png")]
            for alone in sorted(directory.glob(f"{stem}_alone_*.png")):
                print(f"      {alone.name}: {describe(histogram(alone))}")
    print(f"   {len(masks)} mask(s); stray ids over the run: "
          f"{describe(stray_total) if stray_total else 'none'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--frames", type=int, default=3,
                        help="frames printed in full per camera (default 3)")
    args = parser.parse_args(argv)
    renders = sorted(args.run_dir.rglob("render.json"))
    if not renders:
        print(f"no render.json under {args.run_dir}: not a rendered run")
        return 2
    for render_json in renders:
        camera(render_json, args.frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
