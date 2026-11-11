"""Copy one visual-quality round's frames into the repo, small enough to commit.

After ``python scripts/run_test_scenarios.py --still`` has gathered every
scenario's first frame into ``runs/test_scenarios/``, this writes
``docs/visual/round_<N>/``: each frame as ``NN_<name>.jpg`` (1280 px wide),
``contact.jpg`` (every frame on one sheet, labelled), and ``summary.json``
(each scenario's prompt, outcome, run id). The run folders stay on the
render machine; these copies are what the other machine and the owner look at.

    python scripts/visual_round.py 0

Round 5 (L5): with ``FLIGHTSIM_BEAUTY_POST=on`` the post-render beauty
frame rides along as ``NN_<name>_post.jpg`` and ``contact_post.jpg``. A
gallery frame the web app already post-processed (``*_frame_beauty_post.png``,
copied by run_test_scenarios.py) is used as it is; one without is put
through scripts/beauty_post.py here, with the run's beauty_look.json
choosing the stock. The originals and the labels are never touched.
"""

from __future__ import annotations

import argparse
import json
import os
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


def _beauty_post_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("beauty_post", REPO / "scripts" / "beauty_post.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post_frame_for(frame: Path, run_id, off, run_root: Path = RUN_ROOT,
                   module=None, **kw) -> Path:
    """The post-processed twin of a gallery frame: the web app's
    ``<name>_frame_beauty_post.png`` beside it when run_test_scenarios.py
    copied one, else scripts/beauty_post.py run on the gallery frame with
    the run's beauty_look.json (the stock, the noisy flag, the grain). The
    record goes to ``<frame>.beauty_post.json`` (the gallery holds no
    render.json). Raises the pipeline's named refusal."""
    name = frame.name[: -len("_frame.png")]
    ready = frame.with_name(name + "_frame_beauty_post.png")
    if ready.is_file():
        return ready
    module = module or _beauty_post_module()
    sidecar = run_root / str(run_id or "-") / "beauty_look.json"
    plan = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    choice = module.look_choices(plan)
    record = module.post_frame(frame, cube=choice["cube"], noisy=choice["noisy"],
                               grain=choice["grain"], upscale="upscale" not in off, off=off, **kw)
    out = frame.with_name(record["output"])
    out.with_suffix(".beauty_post.json").write_text(
        json.dumps({**record, "look": {"stock": choice["stock"], "world_preset": plan.get("world_preset")}},
                   indent=1), encoding="utf-8")
    return out


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
    return {"render_json": True, "look_keys_missing": missing, "new_look_ran": not missing,
            "beauty_post": "beauty_post" in found}


def _contact_sheet(thumbs, path: Path) -> None:
    height = max(t.height for _, t in thumbs) + 22
    rows = (len(thumbs) + COLUMNS - 1) // COLUMNS
    sheet = Image.new("RGB", (COLUMNS * THUMB, rows * height), (16, 20, 24))
    draw = ImageDraw.Draw(sheet)
    for i, (name, thumb) in enumerate(thumbs):
        x, y = (i % COLUMNS) * THUMB, (i // COLUMNS) * height
        sheet.paste(thumb, (x, y + 22))
        draw.text((x + 4, y + 4), name[:60], fill=(220, 225, 230))
    sheet.save(path, quality=85)


def _copy(path: Path, target: Path):
    image = Image.open(path).convert("RGB")
    if image.width > WIDTH:
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)))
    image.save(target, quality=88)
    return image.resize((THUMB, round(image.height * THUMB / image.width)))


def write_round(number: int, gallery: Path = GALLERY, summary: Path = SUMMARY,
                out_root: Path = REPO / "docs" / "visual",
                run_root: Path = RUN_ROOT, post=None, **post_kw) -> Path:
    """``post``: the steps the post-render pipeline leaves out (a set) when
    it runs, None when it does not (the environment's FLIGHTSIM_BEAUTY_POST
    by default: scripts/beauty_post.py parse_switch). ``post_kw`` reach
    beauty_post.post_frame (tests: fake tools)."""
    out = out_root / f"round_{number}"
    out.mkdir(parents=True, exist_ok=True)
    found = frames(gallery)
    batch = json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else []
    if batch:
        # Only this batch: older batches leave frames in the same folder.
        wanted = {f"{int(r['number']):02d}_" for r in batch if r.get("outcome") == "done"}
        found = [p for p in found if p.name[:3] in wanted]
    if not found:
        raise SystemExit(f"no *_frame.png in {gallery}: run "
                         "scripts/run_test_scenarios.py --still first")
    if post is None and os.environ.get("FLIGHTSIM_BEAUTY_POST", "").strip():
        post = _beauty_post_module().wanted()
    run_ids = {f"{int(r['number']):02d}": r.get("run_id") for r in batch if "number" in r}
    thumbs, post_thumbs, posted = [], [], {}
    for path in found:
        name = path.name[: -len("_frame.png")]
        thumbs.append((name, _copy(path, out / f"{name}.jpg")))
        if post is not None:
            try:
                twin = post_frame_for(path, run_ids.get(name[:2]), post, run_root, **post_kw)
            except Exception as exc:  # the pipeline's named refusal: said, not hidden
                posted[name] = {"refused": getattr(exc, "constraint", type(exc).__name__),
                                "reason": str(exc)}
                continue
            post_thumbs.append((name + " (post)", _copy(twin, out / f"{name}_post.jpg")))
            posted[name] = {"post": f"{name}_post.jpg", "source": twin.name}
    _contact_sheet(thumbs, out / "contact.jpg")
    if post_thumbs:
        _contact_sheet(post_thumbs, out / "contact_post.jpg")
    if posted:
        (out / "beauty_post.json").write_text(json.dumps(
            {"steps_off": sorted(post), "frames": posted}, indent=1), encoding="utf-8")
    if summary.is_file():
        rows_out = [{**{k: r.get(k) for k in ("number", "name", "prompt", "outcome",
                                               "why", "run_id", "lighting", "seconds")},
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
