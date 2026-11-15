"""The owner's four-frame sky compare: one camera, four cloud words, the old look.

Sky step 8 of the X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md step 8;
design docs/visual/XPLANE_SKY_DESIGN.md §10). scripts/sky_compare_round.ps1
renders four fix rounds of ONE scene on the Windows laptop, each under one
``-cloud-type=`` word (clear, cumulus, stratocumulus, overcast; the pinned
spec replays, so the camera is the same), then runs this to lay them out
against the previous round's frame of the same scene (the "old look"):

    python scripts/sky_contact_sheet.py --rounds 110,111,112,113 --scene 3 --old 95

Reads ``round_<R>/NN_<slug>.jpg`` (the 1280-px copy scripts/visual_round.py
writes; NN = the scene number, two digits) under the first ROOT that holds the
round's folder: ``docs/visual`` then ``runs/vis-windows-wt/docs/visual``, the
same two places and the same order as visual_fix_round.ps1 step 4b (round
folders are committed to branch vis-windows, not the code branch, so an old
round is often only in the worktree). Each round's ``summary.json`` run id ->
``runs/webapp/<run id>/render.json``, ``frames/render.json`` or
``frames/*/render.json`` -> ``look_applied.world_beauty.clouds`` (what the
host DREW: ``layers[0].cloud_type_applied`` / ``cloud_type_source``, the
``hidden_layers`` a clear word leaves, ``march.tier``, and
``plan.cloud_type_switch``: the word the host PARSED) and
``look_applied.world_beauty.atmosphere.multi_scattering_factor``. Writes
``docs/visual/sky_compare/round_<N>/``:

  sheet.jpg      row 1: the old frame, "round <M> (old look)"; row 2: the four
                 frames, each captioned with the word REQUESTED and the shape
                 APPLIED, its source, the march tier and the multi-scattering
                 factor; MISMATCH when the requested word's shape
                 (world_beauty.PLAN_CLOUD_SHAPES) is not the one applied;
                 "applied unknown" when the record names no shape (a host
                 before sky step 2, -beauty-clouds=engine, a material that did
                 not load); "-cloud-type= not parsed" when the record does not
                 carry the word asked (plan.cloud_type_switch).
  compare.json   per tile: round, word, frame, root, applied / source /
                 mismatch / switch_seen, scripts/visual_compare.py's
                 mean_abs_change, moved_share and mean luma against the old
                 frame, scripts/frame_metrics.py's health (blank / clipped /
                 crushed) and flags, the round's commit and switches
                 (ROUND.json), FLIGHTSIM_SKY as the ps1 recorded it; and the
                 lists mismatches, unknown, switch_not_seen, no_record and
                 missing. The owner's reading rule: ALL FIVE EMPTY and every
                 tile's applied a shape word or "no layer". A missing frame or
                 record is LISTED (found / record false), never dropped; the
                 tile on the sheet says MISSING.

A report, never a gate: nothing here fails a round, every threshold it
repeats is frame_metrics' UNCALIBRATED one, and no frame on the Mac exists,
so until the Windows laptop runs the ps1 every output named here is
UNMEASURED. Deterministic for the same inputs (no clock, no hostnames).
numpy + Pillow only; the two scripts it reuses sit beside it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
import frame_metrics  # noqa: E402
import visual_compare  # noqa: E402
from core.scene.world_beauty import CLOUD_TYPE_SWITCH, PLAN_CLOUD_SHAPES  # noqa: E402

VISUAL = REPO / "docs" / "visual"
#: Where visual_fix_round.ps1 step 4b looks for a previous round when the main
#: checkout has no docs/visual/round_M: its vis-windows worktree. Same order here.
FALLBACK_VISUAL = REPO / "runs" / "vis-windows-wt" / "docs" / "visual"
ROOTS = (VISUAL, FALLBACK_VISUAL)
RUN_ROOT = REPO / "runs" / "webapp"
#: The owner's four frames, in the order the ps1 renders them (brief step 8:
#: "clear, scattered cumulus, broken stratocumulus, overcast"). Each is a
#: -cloud-type= word the host accepts (world_beauty.PLAN_CLOUD_TYPES).
WORDS = ("clear", "cumulus", "stratocumulus", "overcast")
#: Where the ps1 and this script put a compare: docs/visual/sky_compare/round_<N>/,
#: N = the first of the four round numbers.
SKY_COMPARE_DIR = "sky_compare"
#: Layout, pixels: a 480-px tile, a 58-px caption band (three 14-px lines), an
#: 8-px gap. Report geometry, not look values; tests pin them by value.
TILE = 480
CAPTION_PX = 58
GAP = 8
BACKGROUND = (16, 20, 24)
INK = (220, 225, 230)
ALARM = (255, 140, 110)
#: What a clear (or cirrus) word applies: no volumetric layer (FlightSimClouds.cpp
#: CloudShapeForPlanType -> PlanCloudNoLayer; the layer lands in hidden_layers).
NO_LAYER = "no layer"
#: A record that exists but names no shape: layers without cloud_type_applied (a
#: host before sky step 2, such as fbcbaa5d), or no layers and no hidden_layers
#: at all (FlightSimClouds.cpp's early returns: -beauty-clouds=engine, or
#: M_FlightSimCloudLayers did not load; both write only clouds.drawn). Never a
#: match: the sheet cannot tell "switch honoured" from "switch never seen".
UNKNOWN = "unknown"
#: The caption's words for a record that does not carry the word asked.
NOT_PARSED = f"host predates sky step 2: {CLOUD_TYPE_SWITCH}= not parsed"
#: Caption text that turns a line to the alarm colour.
ALARM_WORDS = ("MISMATCH", "MISSING", "unknown", "not parsed", "host parsed")
#: The owner's reading rule, written into compare.json beside the lists it names.
READING_RULE = ("mismatches, unknown, switch_not_seen, no_record and missing must ALL be empty, "
                "and every tile's applied must be a shape word or 'no layer'; a round in unknown "
                "or switch_not_seen is also in mismatches")


def find_round(rnd: int, roots: Sequence[Path] = ROOTS) -> Optional[Path]:
    """The round's folder, from the first root that has it (visual_fix_round.ps1
    step 4b's order: docs/visual, then the vis-windows worktree); None when no
    root has the folder."""
    for root in roots:
        folder = Path(root) / f"round_{rnd}"
        if folder.is_dir():
            return folder
    return None


def frame_for(folder: Optional[Path], scene: int) -> Optional[Path]:
    """The round's plain frame for a scene: ``NN_<slug>.jpg``, not the ``_post``
    twin (frame_metrics reads the same one, so the numbers are like with like)."""
    if folder is None or not folder.is_dir():
        return None
    for path in sorted(folder.glob(f"{scene:02d}_*.jpg")):
        if not path.name.endswith(tuple(frame_metrics.NOT_A_FRAME)):
            return path
    return None


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_id_for(folder: Optional[Path], scene: int):
    if folder is None:
        return None
    rows = _json(folder / "summary.json")
    for row in rows or []:
        if isinstance(row, dict) and row.get("number") == scene:
            return row.get("run_id")
    return None


def render_record(run_id, run_root: Path = RUN_ROOT) -> Optional[dict]:
    """The run's first render.json carrying ``look_applied``: ``<run>/render.json``
    (scripts/visual_round.py reads it too), then the flat ``frames/render.json``
    a run without a clip camera writes (webapp/runs.py, the clip's manifest),
    then ``frames/<camera>/render.json`` per camera."""
    if not run_id:
        return None
    run_dir = run_root / str(run_id)
    candidates = ([run_dir / "render.json", run_dir / "frames" / "render.json"]
                  + sorted(run_dir.glob("frames/*/render.json")))
    for path in candidates:
        data = _json(path) if path.is_file() else None
        if isinstance(data, dict) and isinstance(data.get("look_applied"), dict):
            return data
    return None


def applied_from(record: Optional[dict], word: Optional[str] = None) -> Dict[str, object]:
    """What the beauty host drew, read off render.json. Every key present, None
    when the record is missing, so a reader can tell "not rendered" from "clear".

    ``applied`` is a shape word, NO_LAYER (a hidden layer: what clear asks for)
    or UNKNOWN (the record names no shape: a host before sky step 2, an engine-
    mode or material-missing early return); never None once a record exists.
    ``switch_seen`` is True only when ``clouds.plan.cloud_type_switch`` (the word
    the host PARSED from -cloud-type=, step 2) is present and, when ``word`` is
    given, equals it; False means the host never saw the switch, or saw another
    word."""
    out: Dict[str, object] = {"record": record is not None, "applied": None, "source": None,
                              "march_tier": None, "multi_scattering_factor": None,
                              "hidden_layers": None, "cloud_type_switch": None, "switch_seen": None}
    if not record:
        return out
    world = record.get("look_applied", {}).get("world_beauty", {}) or {}
    clouds = world.get("clouds", {}) or {}
    layers = [l for l in clouds.get("layers", []) or [] if isinstance(l, dict)]
    hidden = [h for h in clouds.get("hidden_layers", []) or [] if isinstance(h, dict)]
    out["hidden_layers"] = len(hidden)
    drawn = clouds.get("drawn")
    if layers and layers[0].get("cloud_type_applied") is not None:
        out["applied"] = layers[0].get("cloud_type_applied")
        out["source"] = layers[0].get("cloud_type_source")
    elif layers:
        out["applied"] = UNKNOWN
        out["source"] = drawn if drawn else "layers without cloud_type_applied"
    elif hidden:
        out["applied"] = NO_LAYER
        out["source"] = hidden[0].get("cloud_type_source")
    else:
        out["applied"] = UNKNOWN
        out["source"] = drawn if drawn else "no layers, no hidden_layers"
    march = clouds.get("march", {}) or {}
    out["march_tier"] = march.get("tier")
    plan = clouds.get("plan", {}) or {}
    switch = plan.get("cloud_type_switch")
    out["cloud_type_switch"] = switch
    out["switch_seen"] = switch is not None and switch != "" and (word is None or switch == word)
    atmosphere = world.get("atmosphere", {}) or {}
    out["multi_scattering_factor"] = atmosphere.get("multi_scattering_factor")
    return out


def expected_shape(word: str) -> str:
    """The shape a -cloud-type= word should apply: the CLOUDS row of the same
    name, or no volumetric layer (clear, cirrus)."""
    shape = PLAN_CLOUD_SHAPES.get(word)
    return NO_LAYER if shape is None else shape


def mismatch(word: str, applied) -> Optional[bool]:
    """True when the host drew something other than the word asks for, or when
    the record names no shape at all (UNKNOWN: never a match); None when there
    is no record to compare (missing is reported, not judged)."""
    if applied is None:
        return None
    if applied == UNKNOWN:
        return True
    return applied != expected_shape(word)


def _luma(image: Image.Image) -> np.ndarray:
    return visual_compare._luma(image)


def against_old(new: Image.Image, old: Optional[Image.Image]) -> Dict[str, object]:
    """visual_compare.py's numbers for one tile against the old frame."""
    out: Dict[str, object] = {"mean_luma": round(float(_luma(new).mean()), 1)}
    if old is None:
        return out
    if old.size != new.size:
        old = old.resize(new.size)
    delta = np.abs(_luma(new) - _luma(old))
    out["mean_abs_change"] = round(float(delta.mean()), 2)
    out["moved_share"] = round(float((delta > visual_compare.MOVED).mean()), 4)
    out["mean_luma_old"] = round(float(_luma(old).mean()), 1)
    return out


def health(image: Image.Image) -> Dict[str, object]:
    h = frame_metrics.frame_health(np.asarray(image.convert("RGB"), dtype=np.uint8))
    return {**h, "flags": frame_metrics.health_flags(h), "calibration": frame_metrics.CALIBRATION}


def _thumb(image: Image.Image) -> Image.Image:
    return image.resize((TILE, max(1, round(image.height * TILE / image.width))))


def _placeholder(height: int) -> Image.Image:
    tile = Image.new("RGB", (TILE, height), (40, 24, 24))
    ImageDraw.Draw(tile).text((TILE // 2 - 28, height // 2 - 6), "MISSING", fill=ALARM)
    return tile


def caption_lines(row: Dict[str, object]) -> List[str]:
    """The three caption lines of a tile: the round and the requested word; the
    applied shape, its source and MISMATCH (or "applied unknown"); the march tier
    and multi-scattering, or, when the record does not carry the word asked,
    why the switch was not seen."""
    first = f"round {row['round']}: {CLOUD_TYPE_SWITCH}={row['word']}"
    if not row["found"]:
        return [first, "MISSING: no frame for round %s in any root" % row["round"], ""]
    if not row["record"]:
        return [first, "no render.json record (applied unknown)", ""]
    if row["applied"] == UNKNOWN:
        second = f"applied unknown: no shape in the record ({row['source']})"
    else:
        second = f"applied {row['applied']} ({row['source']})"
        if row["mismatch"]:
            second += f"  MISMATCH: expected {expected_shape(row['word'])}"
    if row["switch_seen"]:
        third = f"march {row['march_tier']}  multi-scatter {row['multi_scattering_factor']}"
    elif not row["cloud_type_switch"]:
        third = NOT_PARSED
    else:
        third = f"host parsed {CLOUD_TYPE_SWITCH}={row['cloud_type_switch']}, not {row['word']}"
    return [first, second, third]


def compose(old: Optional[Image.Image], old_round: int, scene: int, tiles: List[Image.Image],
            rows: List[Dict[str, object]], flightsim_sky: str) -> Image.Image:
    """Row 1: the old frame; row 2: the four tiles with their captions. The row
    height is the tallest tile INCLUDING the old one (a head sweep's aspect
    differs from a still's), so nothing overflows into row 2."""
    old_tile = _thumb(old) if old is not None else None
    height = max([t.height for t in tiles] + ([old_tile.height] if old_tile is not None else []))
    if old_tile is None:
        old_tile = _placeholder(height)
    width = len(tiles) * TILE + (len(tiles) - 1) * GAP
    sheet = Image.new("RGB", (width, 2 * (height + CAPTION_PX) + GAP), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    head = f"round {old_round} (old look), scene {scene:02d}" if old is not None \
        else f"round {old_round} (old look): MISSING frame for scene {scene:02d}"
    draw.text((4, 4), head, fill=INK if old is not None else ALARM)
    draw.text((4, 18), f"FLIGHTSIM_SKY={flightsim_sky or '(unset)'}; every frame UNMEASURED until it exists",
              fill=INK)
    sheet.paste(old_tile, (0, CAPTION_PX))
    y = height + CAPTION_PX + GAP
    for i, (tile, row) in enumerate(zip(tiles, rows)):
        x = i * (TILE + GAP)
        for j, line in enumerate(caption_lines(row)):
            colour = ALARM if (j > 0 and any(w in line for w in ALARM_WORDS)) else INK
            draw.text((x + 4, y + 4 + 14 * j), line[:74], fill=colour)
        sheet.paste(tile, (x, y + CAPTION_PX))
    return sheet


def _rel(path: Optional[Path], root: Optional[Path]) -> Optional[str]:
    if path is None or root is None:
        return None
    return str(path.relative_to(root)).replace("\\", "/")


def compare(rounds: List[int], scene: int, old_round: int, out: Optional[Path] = None,
            words=WORDS, roots: Sequence[Path] = ROOTS, run_root: Path = RUN_ROOT,
            flightsim_sky: str = "", switches: str = "") -> Path:
    """Lay ``rounds`` (one per word, in order) out against ``old_round`` for one
    scene; write sheet.jpg and compare.json under ``out`` (default
    <roots[0]>/sky_compare/round_<rounds[0]>/). Every round folder, the old one
    included, is looked up in ``roots`` in order (visual_fix_round.ps1 step 4b's
    two places) and the root used is recorded. Never raises for a missing frame
    or record: that is a row with found/record false."""
    if len(rounds) != len(words):
        raise SystemExit(f"{len(rounds)} rounds for {len(words)} words: give one round per word")
    roots = [Path(r) for r in roots]
    if not roots:
        raise SystemExit("no root to look for round folders in")
    out = out or roots[0] / SKY_COMPARE_DIR / f"round_{rounds[0]}"
    out.mkdir(parents=True, exist_ok=True)
    old_folder = find_round(old_round, roots)
    old_path = frame_for(old_folder, scene)
    old = Image.open(old_path).convert("RGB") if old_path else None
    old_json = (_json(old_folder / "ROUND.json") if old_folder else None) or {}
    rows: List[Dict[str, object]] = []
    tiles: List[Optional[Image.Image]] = []
    for rnd, word in zip(rounds, words):
        folder = find_round(rnd, roots)
        root = folder.parent if folder else None
        path = frame_for(folder, scene)
        record = render_record(run_id_for(folder, scene), run_root)
        got = applied_from(record, word)
        round_json = (_json(folder / "ROUND.json") if folder else None) or {}
        row: Dict[str, object] = {
            "round": rnd, "word": word, "switch": f"{CLOUD_TYPE_SWITCH}={word}",
            "expected": expected_shape(word),
            "root": str(root) if root else None,
            "frame": _rel(path, root),
            "found": path is not None, **got,
            "mismatch": mismatch(word, got["applied"]),
            "commit": round_json.get("commit"), "switches": round_json.get("switches"),
        }
        if path:
            image = Image.open(path).convert("RGB")
            row["against_old"] = against_old(image, old)
            row["health"] = health(image)
            tiles.append(_thumb(image))
        else:
            tiles.append(None)  # sized once every present tile is known
        rows.append(row)
    height = max([t.height for t in tiles if t is not None] + ([_thumb(old).height] if old else [270]))
    sized = [t if t is not None else _placeholder(height) for t in tiles]
    compose(old, old_round, scene, sized, rows, flightsim_sky).save(out / "sheet.jpg", quality=86)
    report = {
        "scene": scene, "old_round": old_round,
        "roots": [str(r) for r in roots],
        "old_root": str(old_folder.parent) if old_folder else None,
        "old_frame": _rel(old_path, old_folder.parent if old_folder else None),
        "old_found": old_path is not None,
        "old_commit": old_json.get("commit"), "old_switches": old_json.get("switches"),
        "old_health": health(old) if old is not None else None,
        "rounds": rounds, "words": list(words), "flightsim_sky": flightsim_sky,
        "extra_switches": switches,
        "mismatches": [r["round"] for r in rows if r["mismatch"]],
        "unknown": [r["round"] for r in rows if r["applied"] == UNKNOWN],
        "switch_not_seen": [r["round"] for r in rows if r["record"] and not r["switch_seen"]],
        "no_record": [r["round"] for r in rows if r["found"] and not r["record"]],
        "missing": [r["round"] for r in rows if not r["found"]],
        "reading_rule": READING_RULE,
        "tiles": rows,
        "basis": ("sky step 8: a report, never a gate; metrics from scripts/visual_compare.py and "
                  "scripts/frame_metrics.py (UNCALIBRATED); applied shapes read off "
                  "look_applied.world_beauty.clouds; 'unknown' = the record names no shape (a host "
                  "before sky step 2, -beauty-clouds=engine, or the material did not load); "
                  "switch_not_seen = clouds.plan.cloud_type_switch is not the word asked (the host "
                  "never parsed -cloud-type=); every frame UNMEASURED until the Windows laptop "
                  "renders it"),
    }
    (out / "compare.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return out


def _ints(text: str) -> List[int]:
    return [int(t) for t in text.replace(";", ",").split(",") if t.strip()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--rounds", required=True,
                        help="the four rounds, in word order (110,111,112,113)")
    parser.add_argument("--scene", type=int, required=True, help="the scene number (3 or 13)")
    parser.add_argument("--old", type=int, required=True, help="the previous round: the old look")
    parser.add_argument("--out", type=Path, default=None,
                        help="default <root>/sky_compare/round_<first round>")
    parser.add_argument("--words", default=",".join(WORDS))
    parser.add_argument("--root", type=Path, default=VISUAL,
                        help="where round_<R> folders are looked for first (default docs/visual)")
    parser.add_argument("--fallback-root", type=Path, action="append", default=None,
                        help="looked in next when --root has no round_<R> (default "
                             "runs/vis-windows-wt/docs/visual, visual_fix_round.ps1's worktree); repeatable")
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--flightsim-sky", default="", help="FLIGHTSIM_SKY as the shell had it, recorded")
    parser.add_argument("--switches", default="", help="the extra switches every round carried, recorded")
    args = parser.parse_args(argv)
    words = tuple(w.strip() for w in args.words.split(",") if w.strip())
    for word in words:
        if word not in PLAN_CLOUD_SHAPES:
            raise SystemExit(f"{CLOUD_TYPE_SWITCH}={word} is not a word the host accepts: "
                             + ", ".join(PLAN_CLOUD_SHAPES))
    roots = [args.root] + (args.fallback_root if args.fallback_root is not None else [FALLBACK_VISUAL])
    out = compare(_ints(args.rounds), args.scene, args.old, args.out, words, roots,
                  args.run_root, args.flightsim_sky, args.switches)
    report = json.loads((out / "compare.json").read_text(encoding="utf-8"))
    print(f"old look: round {report['old_round']} "
          f"{'in ' + report['old_root'] if report['old_found'] else 'MISSING in every root'}")
    for tile in report["tiles"]:
        print(f"round {tile['round']} {tile['switch']}: "
              f"{'frame' if tile['found'] else 'MISSING'}, applied {tile['applied']}"
              f"{' MISMATCH' if tile['mismatch'] else ''}"
              f"{' SWITCH NOT SEEN' if tile['record'] and not tile['switch_seen'] else ''}")
    for key in ("mismatches", "unknown", "switch_not_seen", "no_record", "missing"):
        print(f"{key}: {report[key]}")
    print(f"reading rule: {READING_RULE}")
    print(f"sheet: {out / 'sheet.jpg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
