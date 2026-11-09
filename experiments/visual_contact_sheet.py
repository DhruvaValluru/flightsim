"""The visual overhaul's fixed baseline: four shots, one command, one sheet.

    python experiments/visual_contact_sheet.py --step v0            # render a b c d, compose the sheet
    python experiments/visual_contact_sheet.py --step v0 --skip-render   # compose from existing PNGs only
    python experiments/visual_contact_sheet.py --compare v0_before v0  # before/after sheet
    python experiments/visual_contact_sheet.py --step v0 --clip     # + a 15 s chase-cam beauty clip
    python experiments/visual_contact_sheet.py --step v0 --pathtrace --spp 512   # hero stills

The four shots (docs/VISUAL_FIDELITY_PLAN.md, the visual overhaul's
baseline; every later step renders the same four so the sheets compare
like with like):

  a  chase cam over real terrain at golden hour (the Matterhorn)
  b  low pass over the desert (the Phase 3 desert preset, Grand Canyon)
  c  the forest in heavy rain (the Phase 3 forest preset, Yosemite; the
     web app's storm weather is on by default and draws the rain)
  d  the cockpit-shoulder view (the "cockpit" camera preset, behind the
     windshield, the legacy shoulder view)

The subject is the J-11 (assets/aircraft_config/J11.json), the only one of
the Phase 3 J-35 / J-15 / J-11 subjects the repository has (owner decision
3, docs/phase3/decisions.md); J-35 and J-15 have no airframe here, and a
placeholder is never rendered in their place.

How a shot is rendered: through the web app's OWN handlers (POST /compile,
POST /run, POST /bake on terrain.unbaked, GET /runs/<id>), called in this
process with FastAPI's TestClient -- the same path the page takes, so the
Google Photorealistic 3D Tiles are the ground (CLAUDE.md: on unless
FLIGHTSIM_GOOGLE_TILES=off) and the storm weather is on by default
(webapp/runs.py weather_backend_flags). ``--quality`` sets
FLIGHTSIM_RENDER_QUALITY for this process. ``--still-samples N`` and
``--pathtrace`` add their commandlet tokens to the per-camera render
command only (the dataset pass, ``-camera-index=``), never to the
throw-away solve pass; shots.json records the exact tokens added.

Outputs, under ``runs/visual/<step>/``: ``a.png .. d.png`` (and
``<shot>_mask.png`` when the run wrote a label mask), ``shots.json``
(card, camera, quality, commit, run id, edge-aliasing number) and the
labelled grid ``sheet.png``. ``--compare A B`` writes
``runs/visual/compare_<A>_vs_<B>.png``. ``--clip`` writes
``runs/visual/<step>/clip.mp4`` (the web run's own encode, or the frames
through ffmpeg when it is on PATH).

Nothing here is a gate. The sheet is for a person to look at; the
edge-aliasing number (experiments/gate6_visual.py, visual plan V0
"Measure") is reported per shot where a label mask exists.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

#: Where every step's sheet lives.
VISUAL_ROOT = REPO / "runs" / "visual"
#: Sheet tile size (16:9) and caption bar height, pixels.
TILE_W, TILE_H = 960, 540
CAPTION_H = 44
GUTTER = 8
#: The --clip length, seconds (the brief asks for 10-20 s).
CLIP_SECONDS_DEFAULT = 15.0
#: How long one shot may take end to end before it is reported failed,
#: seconds (a beauty still with a terrain bake on a cold cache).
SHOT_TIMEOUT_S = 3 * 3600.0
#: Seconds between reads of the run's state while this process waits for
#: its own render subprocess (a local wait, not a scheduled check-in).
WAIT_STEP_S = 5.0
#: The commandlet token that turns ray tracing on for ONE process
#: (ue/Config/DefaultEngine.ini keeps r.RayTracing out, render-path lane).
RAY_TRACING_INI_TOKEN = "-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=True"
#: The run states the web app ends in.
DONE_STATES = ("done", "failed")


@dataclass(frozen=True)
class Shot:
    key: str
    title: str
    prompt: str
    environment: Optional[str]
    aircraft: str
    camera: str
    #: What the shot is for, in a word or two (the caption's second line).
    look: str


#: The four fixed shots. Prompts are compiled by the offline (regex)
#: interpreter so the table is reproducible without a model call; the
#: environment is the page's Phase 3 D4 picker (webapp.runs
#: ENVIRONMENT_PRESETS). tests/test_visual_contact_sheet.py compiles each.
SHOTS: Dict[str, Shot] = {
    "a": Shot("a", "chase cam, real terrain, golden hour",
              "chase view of the j11 at 3000 m over the matterhorn at golden hour, "
              "flying east, for 6 seconds",
              None, "J11", "chase", "golden hour, Google tiles"),
    "b": Shot("b", "low pass over the desert",
              "chase view of the j11 at 1600 m over the desert, flying southwest, "
              "for 6 seconds",
              "desert", "J11", "chase", "desert preset (Grand Canyon), noon"),
    "c": Shot("c", "forest in heavy rain (storm weather)",
              "chase view of the j11 at 1700 m over the forest in heavy rain for 6 seconds",
              "forest", "J11", "chase", "forest preset (Yosemite), storm rain"),
    "d": Shot("d", "cockpit-shoulder view",
              "cockpit view of the j11 at 3000 m over the matterhorn at 10:00 for 6 seconds",
              None, "J11", "cockpit", "behind the windshield"),
}
SHOT_ORDER = ("a", "b", "c", "d")


# -- provenance -------------------------------------------------------------


def git_commit(repo: Path = REPO) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def step_dir(step: str, root: Path = VISUAL_ROOT) -> Path:
    if not step or "/" in step or "\\" in step or step.startswith("."):
        raise ValueError(f"--step must be a plain name, not {step!r}")
    return root / step


def render_extra_tokens(quality: str, still_samples: Optional[int],
                        pathtrace: bool, spp: Optional[int]) -> List[str]:
    """The commandlet tokens this tool adds to the per-camera render pass
    (beyond what FLIGHTSIM_RENDER_QUALITY already makes the web app send).
    Refuses by name what the commandlet would refuse."""
    tokens: List[str] = []
    if pathtrace:
        if still_samples is not None:
            raise ValueError("render.still_samples: --still-samples is a beauty option; the path "
                             "tracer accumulates by --spp")
        tokens += ["-quality=pathtrace", RAY_TRACING_INI_TOKEN]
        if spp is not None:
            if not 1 <= int(spp) <= 16384:
                raise ValueError(f"render.pathtrace: --spp {spp} is not from 1 to 16384")
            tokens.append(f"-pathtrace-spp={int(spp)}")
        return tokens
    if spp is not None:
        raise ValueError("render.pathtrace: --spp needs --pathtrace")
    if still_samples is not None:
        if quality != "beauty":
            raise ValueError("render.still_samples: --still-samples needs --quality beauty")
        if not 1 <= int(still_samples) <= 64:
            raise ValueError(f"render.still_samples: --still-samples {still_samples} is not "
                             f"from 1 to 64")
        tokens.append(f"-still-samples={int(still_samples)}")
    return tokens


def rewrite_render_command(command: Sequence[str], tokens: Sequence[str]) -> List[str]:
    """``command`` with ``tokens`` applied, when it is the per-camera
    render-commandlet pass; anything else is returned unchanged.
    ``-quality=pathtrace`` replaces any ``-quality=`` already there."""
    command = [str(part) for part in command]
    is_render = any(part == "-run=FlightSimBridge.FlightSimRender" for part in command)
    per_camera = any(part.startswith("-camera-index=") for part in command)
    if not tokens or not is_render or not per_camera:
        return command
    if any(token.startswith("-quality=") for token in tokens):
        command = [part for part in command if not part.startswith("-quality=")]
    return command + [token for token in tokens if token not in command]


# -- composition (no engine needed; what the tests exercise) ---------------


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _tile(png: Optional[Path], caption: str, subcaption: str, missing: str):
    """One captioned tile: the PNG fitted (letterboxed) into TILE_W x TILE_H,
    or a grey tile saying why there is no picture."""
    from PIL import Image, ImageDraw

    tile = Image.new("RGB", (TILE_W, TILE_H + CAPTION_H), (24, 26, 30))
    if png is not None and Path(png).is_file():
        with Image.open(png) as source:
            picture = source.convert("RGB")
        scale = min(TILE_W / picture.width, TILE_H / picture.height)
        size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
        picture = picture.resize(size, Image.LANCZOS)
        tile.paste(picture, ((TILE_W - size[0]) // 2, (TILE_H - size[1]) // 2))
    else:
        draw = ImageDraw.Draw(tile)
        draw.rectangle([0, 0, TILE_W, TILE_H], fill=(60, 62, 66))
        draw.text((24, TILE_H // 2 - 10), missing, fill=(230, 200, 120), font=_font(22))
    draw = ImageDraw.Draw(tile)
    draw.text((10, TILE_H + 3), caption, fill=(235, 238, 242), font=_font(20))
    draw.text((10, TILE_H + 24), subcaption, fill=(150, 160, 170), font=_font(14))
    return tile


def _grid(tiles, columns: int, header: Optional[str] = None):
    from PIL import Image, ImageDraw

    rows = (len(tiles) + columns - 1) // columns
    head = 40 if header else 0
    width = columns * TILE_W + (columns + 1) * GUTTER
    height = head + rows * (TILE_H + CAPTION_H) + (rows + 1) * GUTTER
    sheet = Image.new("RGB", (width, height), (12, 13, 15))
    if header:
        ImageDraw.Draw(sheet).text((GUTTER + 4, 8), header, fill=(240, 240, 240), font=_font(24))
    for index, tile in enumerate(tiles):
        row, column = divmod(index, columns)
        sheet.paste(tile, (GUTTER + column * (TILE_W + GUTTER),
                           head + GUTTER + row * (TILE_H + CAPTION_H + GUTTER)))
    return sheet


def read_shots(directory: Path) -> dict:
    path = directory / "shots.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _caption(key: str, row: dict) -> tuple:
    shot = SHOTS[key]
    first = f"{key}  {shot.title}"
    bits = [row.get("aircraft") or shot.aircraft, row.get("quality") or "?",
            shot.look]
    aliasing = (row.get("edge_aliasing") or {}).get("energy")
    if aliasing is not None:
        bits.append(f"edge aliasing {aliasing:.3f}")
    if row.get("commit"):
        bits.append(str(row["commit"])[:12])
    return first, "  |  ".join(str(b) for b in bits)


def compose_sheet(directory: Path, out: Optional[Path] = None) -> Path:
    """The labelled 2 x 2 grid of a step's a..d PNGs (missing ones say so)."""
    shots = read_shots(directory).get("shots", {})
    tiles = []
    for key in SHOT_ORDER:
        row = shots.get(key, {})
        first, second = _caption(key, row)
        why = row.get("refused") or row.get("failed") or "not rendered"
        tiles.append(_tile(directory / f"{key}.png", first, second, f"{key}: {why}"))
    header = f"{directory.name}  --  visual overhaul baseline shots"
    sheet = _grid(tiles, 2, header)
    out = out or directory / "sheet.png"
    sheet.save(out)
    return out


def compose_compare(before: Path, after: Path, out: Path) -> Path:
    """Before | after, one row per shot, each tile captioned with its step."""
    before_rows = read_shots(before).get("shots", {})
    after_rows = read_shots(after).get("shots", {})
    tiles = []
    for key in SHOT_ORDER:
        for directory, rows in ((before, before_rows), (after, after_rows)):
            first, second = _caption(key, rows.get(key, {}))
            tiles.append(_tile(directory / f"{key}.png", f"{directory.name}: {first}",
                               second, f"{directory.name}/{key}: not rendered"))
    sheet = _grid(tiles, 2, f"before: {before.name}    after: {after.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def shot_aliasing(directory: Path, key: str) -> Optional[dict]:
    """The edge-aliasing row for a shot with a label mask beside it."""
    png, mask = directory / f"{key}.png", directory / f"{key}_mask.png"
    if not png.is_file() or not mask.is_file():
        return None
    import numpy as np
    from PIL import Image

    from experiments.gate6_visual import measure_edge_aliasing

    with Image.open(png) as image:
        rgb = np.moveaxis(np.asarray(image.convert("RGB"), dtype=np.int64), 2, 0)
    with Image.open(mask) as image:
        silhouette = np.asarray(image.convert("L")) > 0
    if silhouette.shape != rgb.shape[1:]:
        return None
    return measure_edge_aliasing(rgb, silhouette)


# -- rendering through the web app's own handlers --------------------------


class ShotRefused(Exception):
    """A named refusal from the pipeline (kept, printed, recorded)."""


def _client():
    from fastapi.testclient import TestClient

    import webapp.server as server

    return TestClient(server.app), server


def render_shot(shot: Shot, *, still: bool = True, clip_seconds: Optional[float] = None,
                tokens: Sequence[str] = (), client_factory: Callable = _client,
                timeout_s: float = SHOT_TIMEOUT_S) -> dict:
    """Run one shot through /compile and /run and wait for it; returns the
    run's state dict plus ``run_dir``. Raises ShotRefused by name."""
    import core.render.headless as headless

    client, server = client_factory()
    body = {"prompt": shot.prompt, "compiler": "regex"}
    if shot.environment:
        body["environment"] = shot.environment
    if still:
        body["still"] = True
    elif clip_seconds is not None:
        body["clip_seconds"] = float(clip_seconds)
    reply = client.post("/compile", json=body)
    payload = reply.json()
    if reply.status_code != 200 or "spec" not in payload:
        raise ShotRefused(f"compile: {payload}")
    if not payload.get("validation", {}).get("ok", False):
        raise ShotRefused(f"validation: {payload.get('validation')}")
    run_body = {"spec": payload["spec"]["dict"],
                "provenance": {"compiler": payload.get("compiler"),
                               "tool": "experiments/visual_contact_sheet.py"}}

    original = headless.run_headless

    def patched(command, log, *args, **kwargs):
        return original(rewrite_render_command(command, tokens), log, *args, **kwargs)

    headless.run_headless = patched
    try:
        reply = client.post("/run", json=run_body)
        started = reply.json()
        if reply.status_code == 409 and started.get("refused") == "terrain.unbaked":
            baked = client.post("/bake", json={"latitude": started["latitude"],
                                               "longitude": started["longitude"]})
            if baked.status_code != 200:
                raise ShotRefused(f"terrain: {baked.json()}")
            reply = client.post("/run", json=run_body)
            started = reply.json()
        if reply.status_code != 200 or "run_id" not in started:
            raise ShotRefused(f"run: {started}")
        run_id = started["run_id"]
        begun = time.monotonic()
        while True:
            state = client.get(f"/runs/{run_id}").json()
            if state.get("status") in DONE_STATES:
                break
            if time.monotonic() - begun > timeout_s:
                raise ShotRefused(f"render.timeout: run {run_id} not done after {timeout_s:g} s")
            time.sleep(WAIT_STEP_S)
    finally:
        headless.run_headless = original
    state["run_dir"] = str(server.manager.out_root / run_id)
    state["run_id"] = run_id
    return state


def first_frame(run_dir: Path, camera: str) -> tuple:
    """(frame PNG, its label mask or None) of a finished web run."""
    frames = run_dir / "frames"
    candidates = [frames / camera] + sorted(d for d in frames.glob("*") if d.is_dir()) \
        if frames.is_dir() else []
    for directory in candidates:
        found = sorted(p for p in directory.glob("frame_*.png")
                       if p.stem.split("_")[-1].isdigit())
        if found:
            mask = found[0].with_name(f"{found[0].stem}_mask.png")
            return found[0], (mask if mask.is_file() else None)
    return None, None


def card_summary(run_dir: Path) -> dict:
    try:
        card = json.loads((run_dir / "card.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"aircraft": card.get("aircraft"), "latitude_deg": card.get("latitude_deg"),
            "longitude_deg": card.get("longitude_deg"),
            "google_tiles": card.get("google_tiles")}


def render_summary(frame: Optional[Path]) -> dict:
    if frame is None:
        return {}
    try:
        manifest = json.loads((frame.parent / "render.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    settings = manifest.get("render_settings", {})
    return {"render_quality": manifest.get("scene", {}).get("render_quality"),
            "beauty_path": settings.get("beauty_path"),
            "anti_aliasing": settings.get("anti_aliasing")}


def encode_clip(frames_dir: Path, out: Path, fps: float = 30.0) -> Optional[Path]:
    try:
        from core.util.platform import find_ffmpeg

        ffmpeg = find_ffmpeg()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    pattern = frames_dir / "frame_%04d.png"
    result = subprocess.run([str(ffmpeg), "-y", "-framerate", f"{fps:g}", "-i", str(pattern),
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", str(out)],
                            capture_output=True)
    return out if result.returncode == 0 and out.is_file() else None


# -- the command ------------------------------------------------------------


def write_shots(directory: Path, rows: dict, meta: dict) -> Path:
    path = directory / "shots.json"
    payload = {**meta, "shots": rows}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def shot_table() -> List[dict]:
    return [asdict(SHOTS[key]) for key in SHOT_ORDER]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="visual overhaul baseline contact sheet")
    ap.add_argument("--step", help="the step name: runs/visual/<step>/")
    ap.add_argument("--shots", default=",".join(SHOT_ORDER),
                    help="which of a,b,c,d to render (default all)")
    ap.add_argument("--quality", choices=("measure", "beauty"), default="beauty",
                    help="FLIGHTSIM_RENDER_QUALITY for this process (default beauty)")
    ap.add_argument("--still-samples", type=int, default=None, metavar="N",
                    help="beauty: N captures of each still's pose (-still-samples=N)")
    ap.add_argument("--pathtrace", action="store_true",
                    help="path-traced hero stills (Windows, hardware RT): -quality=pathtrace "
                         "plus the one-process r.RayTracing ini override")
    ap.add_argument("--spp", type=int, default=None, help="--pathtrace samples per pixel")
    ap.add_argument("--skip-render", action="store_true",
                    help="compose sheet.png from the PNGs already in the step directory")
    ap.add_argument("--compare", nargs=2, metavar=("STEP_A", "STEP_B"),
                    help="write runs/visual/compare_<A>_vs_<B>.png and stop")
    ap.add_argument("--clip", action="store_true",
                    help="also render a chase-cam beauty clip of shot a (--clip-seconds)")
    ap.add_argument("--clip-seconds", type=float, default=CLIP_SECONDS_DEFAULT)
    ap.add_argument("--root", default=str(VISUAL_ROOT), help=argparse.SUPPRESS)
    ap.add_argument("--list", action="store_true", help="print the shot table and stop")
    args = ap.parse_args(argv)
    root = Path(args.root)

    if args.list:
        print(json.dumps(shot_table(), indent=2))
        return 0
    if args.compare:
        before, after = (step_dir(name, root) for name in args.compare)
        out = compose_compare(before, after,
                              root / f"compare_{before.name}_vs_{after.name}.png")
        print(f"wrote {out}")
        return 0
    if not args.step:
        ap.error("--step is required (or --compare / --list)")
    directory = step_dir(args.step, root)
    directory.mkdir(parents=True, exist_ok=True)
    keys = [key.strip() for key in args.shots.split(",") if key.strip()]
    unknown = [key for key in keys if key not in SHOTS]
    if unknown:
        ap.error(f"unknown shot(s) {unknown}; the shots are {list(SHOT_ORDER)}")
    if not 10.0 <= args.clip_seconds <= 20.0:
        ap.error("--clip-seconds must be from 10 to 20")
    try:
        tokens = render_extra_tokens(args.quality, args.still_samples, args.pathtrace, args.spp)
    except ValueError as exc:
        print(f"REFUSED {exc}")
        return 2
    quality = "pathtrace" if args.pathtrace else args.quality

    previous = read_shots(directory)
    rows: dict = dict(previous.get("shots", {}))
    if args.skip_render and previous:
        # Composing only: the render's own record stands; nothing is re-stamped.
        meta = {k: v for k, v in previous.items() if k != "shots"}
        meta["composed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        meta = {"step": args.step, "commit": git_commit(), "quality": quality,
                "render_tokens_added": tokens, "shot_table": shot_table(),
                "written": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "rendered": not args.skip_render}
    if not args.skip_render:
        os.environ["FLIGHTSIM_RENDER_QUALITY"] = args.quality if not args.pathtrace else "beauty"
        for key in keys:
            shot = SHOTS[key]
            row = {"card_prompt": shot.prompt, "environment": shot.environment,
                   "camera": shot.camera, "aircraft": shot.aircraft, "quality": quality,
                   "commit": meta["commit"], "render_tokens_added": tokens}
            print(f"[{key}] {shot.title}: rendering ({quality})")
            try:
                state = render_shot(shot, tokens=tokens)
            except ShotRefused as exc:
                row["refused"] = str(exc)
                print(f"[{key}] REFUSED {exc}")
                rows[key] = row
                continue
            run_dir = Path(state["run_dir"])
            row.update(run_id=state["run_id"], status=state.get("status"),
                       detail=state.get("detail"), run_dir=str(run_dir),
                       card=card_summary(run_dir))
            frame, mask = first_frame(run_dir, shot.camera)
            if state.get("status") != "done" or frame is None:
                row["failed"] = state.get("detail") or "the run wrote no frame"
                print(f"[{key}] FAILED {row['failed']}")
            else:
                shutil.copy2(frame, directory / f"{key}.png")
                if mask is not None:
                    shutil.copy2(mask, directory / f"{key}_mask.png")
                row.update(frame=str(frame), render=render_summary(frame))
                print(f"[{key}] {directory / f'{key}.png'}")
            rows[key] = row
        if args.clip:
            shot = SHOTS["a"]
            print(f"[clip] {shot.title}: {args.clip_seconds:g} s beauty clip")
            try:
                state = render_shot(shot, still=False, clip_seconds=args.clip_seconds,
                                    tokens=[t for t in tokens if t.startswith("-still")])
                run_dir = Path(state["run_dir"])
                clip = Path(state["clip"]) if state.get("clip") else None
                target = directory / "clip.mp4"
                if clip is not None and clip.is_file():
                    shutil.copy2(clip, target)
                else:
                    frame, _ = first_frame(run_dir, shot.camera)
                    if frame is None or encode_clip(frame.parent, target) is None:
                        target = None
                meta["clip"] = {"run_id": state["run_id"], "seconds": args.clip_seconds,
                                "file": str(target) if target else None,
                                "note": None if target else "no clip: no web encode and no ffmpeg"}
                print(f"[clip] {target or 'not written (no encode, no ffmpeg)'}")
            except ShotRefused as exc:
                meta["clip"] = {"refused": str(exc)}
                print(f"[clip] REFUSED {exc}")
    for key in SHOT_ORDER:
        row = rows.setdefault(key, {})
        aliasing = shot_aliasing(directory, key)
        if aliasing is not None:
            row["edge_aliasing"] = aliasing
    write_shots(directory, rows, meta)
    sheet = compose_sheet(directory)
    print(f"wrote {directory / 'shots.json'}\nwrote {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
