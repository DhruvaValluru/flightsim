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
RUN_ROOT = REPO / "runs" / "webapp"
#: Keys the visual overhaul's beauty look writes into render.json. All of them
#: present means the new look ran; any missing is a finding, not a pass.
LOOK_KEYS = ("beauty_look", "beauty_path", "world_beauty", "aircraft_look",
             "hero_lighting", "pixel_moving_effects")
SUMMARY = REPO / "runs" / "test_scenarios.json"
WIDTH = 1280
THUMB = 480
COLUMNS = 4


def frames(gallery: Path) -> list:
    return sorted(gallery.glob("*_frame.png"))


def _keys(node, found: set) -> set:
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            _keys(value, found)
    elif isinstance(node, list):
        for value in node:
            _keys(value, found)
    return found


def look_report(run_id, run_root: Path = RUN_ROOT) -> dict:
    """Which LOOK_KEYS the run's render.json carries, anywhere in it.

    A web-app run writes one render.json per camera, under
    frames/<camera>/render.json (round 1 found the top-level path empty);
    the run's own top-level render.json is read too if there is one. The keys
    of every file found are pooled."""
    run_dir = run_root / str(run_id or "-")
    renders = ([run_dir / "render.json"] if (run_dir / "render.json").is_file() else []) + \
        sorted(run_dir.glob("frames/*/render.json"))
    if not renders:
        return {"render_json": False}
    found: set = set()
    for render in renders:
        _keys(json.loads(render.read_text(encoding="utf-8")), found)
    missing = [k for k in LOOK_KEYS if k not in found]
    return {"render_json": True, "look_keys_missing": missing, "new_look_ran": not missing}


def write_round(number: int, gallery: Path = GALLERY, summary: Path = SUMMARY,
                out_root: Path = REPO / "docs" / "visual",
                run_root: Path = RUN_ROOT) -> Path:
    out = out_root / f"round_{number}"
    out.mkdir(parents=True, exist_ok=True)
    found = frames(gallery)
    if summary.is_file():
        # Only this batch: older batches leave frames in the same folder.
        batch = json.loads(summary.read_text(encoding="utf-8"))
        wanted = {f"{int(r['number']):02d}_" for r in batch if r.get("outcome") == "done"}
        found = [p for p in found if p.name[:3] in wanted]
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
        rows_out = [{**{k: r.get(k) for k in ("number", "name", "prompt", "outcome",
                                               "why", "run_id", "lighting")},
                     **(look_report(r.get("run_id"), run_root) if r.get("run_id") else {})}
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
