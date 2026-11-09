"""Copy one visual-quality round's frames into the repo, small enough to commit.

After ``python scripts/run_test_scenarios.py --still`` has gathered every
scenario's first frame into ``runs/test_scenarios/``, this writes
``docs/visual/round_<N>/``: each frame as ``NN_<name>.jpg`` (1280 px wide),
``contact.jpg`` (every frame on one sheet, labelled), and ``summary.json``
(each scenario's prompt, outcome, run id). The run folders stay on the
render machine; these copies are what the other machine and the owner look at.

    python scripts/visual_round.py 0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
GALLERY = REPO / "runs" / "test_scenarios"
SUMMARY = REPO / "runs" / "test_scenarios.json"
WIDTH = 1280
THUMB = 480
COLUMNS = 4


def frames(gallery: Path) -> list:
    return sorted(gallery.glob("*_frame.png"))


def write_round(number: int, gallery: Path = GALLERY, summary: Path = SUMMARY,
                out_root: Path = REPO / "docs" / "visual") -> Path:
    out = out_root / f"round_{number}"
    out.mkdir(parents=True, exist_ok=True)
    found = frames(gallery)
    if not found:
        raise SystemExit(f"no *_frame.png in {gallery}: run "
                         "scripts/run_test_scenarios.py --still first")
    thumbs = []
    for path in found:
        name = path.name[: -len("_frame.png")]
        image = Image.open(path).convert("RGB")
        if image.width > WIDTH:
            image = image.resize((WIDTH, round(image.height * WIDTH / image.width)))
        image.save(out / f"{name}.jpg", quality=88)
        thumb = image.resize((THUMB, round(image.height * THUMB / image.width)))
        thumbs.append((name, thumb))
    height = max(t.height for _, t in thumbs) + 22
    rows = (len(thumbs) + COLUMNS - 1) // COLUMNS
    sheet = Image.new("RGB", (COLUMNS * THUMB, rows * height), (16, 20, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (name, thumb) in enumerate(thumbs):
        x, y = (i % COLUMNS) * THUMB, (i // COLUMNS) * height
        sheet.paste(thumb, (x, y + 22))
        draw.text((x + 4, y + 4), name[:60], fill=(220, 225, 230))
    sheet.save(out / "contact.jpg", quality=85)
    if summary.is_file():
        rows_out = [{k: r.get(k) for k in ("number", "name", "prompt", "outcome",
                                            "why", "run_id", "lighting")}
                    for r in json.loads(summary.read_text(encoding="utf-8"))]
        (out / "summary.json").write_text(json.dumps(rows_out, indent=1), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("round", type=int)
    args = parser.parse_args()
    out = write_round(args.round)
    print(f"round {args.round}: {len(list(out.glob('[0-9]*.jpg')))} frames in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
