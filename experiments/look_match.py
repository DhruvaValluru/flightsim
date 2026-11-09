"""Match the realtime beauty to a path-traced reference of the same shot.

    python experiments/look_match.py --reference <pathtrace frame.png> --realtime <beauty frame.png>
    python experiments/look_match.py --steps head_pt head --shot a          # from two contact-sheet steps
    python experiments/look_match.py --steps head_pt head --shot a --preset storm --out runs/look_match/a

The reference is a ``-quality=pathtrace`` render (the path tracer with the
reference atmosphere and clouds and the denoiser: docs/visual/PROBE_LOG.md
"## reference-frames"), the realtime frame a ``-quality=beauty`` render of
the same card and pose. Regions come from the realtime run's label bundle
beside the frame (``frame_NNNN_mask.png``, ``frame_NNNN_depth.f32``,
``render.json``). The pure part, and every metric and constant, is
core/scene/look_match.py.

Writes, under ``--out`` (default ``runs/look_match/<shot or frame stem>``):

* ``look_match.json``: per-region luminance (stops), CIEDE2000, contrast
  and shadow depth, the far-ground haze band, and every suggestion with
  the metric that drove it;
* ``beauty_look.json``: the realtime run's ``-beauty-look=`` sidecar with
  the suggested ``exposure.ev100`` and ``color_grade`` (only when the plan
  was found: ``--beauty-look``, else the copy render.json echoes);
* ``world_beauty_overrides.json``: the ``-world-beauty-overrides=`` file
  (any overrides already in force, merged);
* and prints the ``-sky-light-scale=`` flag when the fill light moved.

Apply them as docs/visual/RENDER_RUNBOOK.md "Match the realtime beauty to
the reference" says, re-render the realtime beauty, and run this again
until it prints ``converged``. VISUAL ONLY: no label, no measure render and
no physics is touched.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.scene.look_match import LookMatchError, match, write_outputs  # noqa: E402

VISUAL_ROOT = REPO / "runs" / "visual"
OUT_ROOT = REPO / "runs" / "look_match"


def frame_of_step(step: str, shot: str, root: Optional[Path] = None) -> Path:
    """The original frame (inside its run, beside its labels) of a contact
    sheet step's shot, from that step's shots.json."""
    path = Path(root or VISUAL_ROOT) / step / "shots.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LookMatchError("look_match.inputs", f"{path} cannot be read ({exc})")
    rows = doc.get("shots", doc) if isinstance(doc, dict) else {}
    row = rows.get(shot) if isinstance(rows, dict) else None
    frame = row.get("frame") if isinstance(row, dict) else None
    if not frame:
        raise LookMatchError("look_match.inputs", f"step {step!r} has no rendered frame for shot {shot!r} "
                                                  f"in {path}")
    return Path(frame)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Match the realtime beauty to a path-traced reference.")
    parser.add_argument("--reference", type=Path, help="the -quality=pathtrace frame PNG")
    parser.add_argument("--realtime", type=Path, help="the -quality=beauty frame PNG of the same shot")
    parser.add_argument("--steps", nargs=2, metavar=("REFERENCE_STEP", "REALTIME_STEP"),
                        help="two runs/visual/<step> directories (with --shot)")
    parser.add_argument("--shot", help="the contact-sheet shot key (a, b, c, d) with --steps")
    parser.add_argument("--beauty-look", type=Path,
                        help="the realtime run's beauty_look.json (default: the plan render.json echoes)")
    parser.add_argument("--world-overrides", type=Path,
                        help="the world overrides in force on the realtime run (default: the file "
                             "render.json records, if it still exists)")
    parser.add_argument("--preset", help="the world preset (default: look_applied.world_beauty.preset)")
    parser.add_argument("--out", type=Path, help="output directory (default runs/look_match/<shot>)")
    args = parser.parse_args(argv)
    try:
        if args.steps:
            if not args.shot:
                parser.error("--steps needs --shot")
            reference = frame_of_step(args.steps[0], args.shot)
            realtime = frame_of_step(args.steps[1], args.shot)
        elif args.reference and args.realtime:
            reference, realtime = args.reference, args.realtime
        else:
            parser.error("give --reference and --realtime, or --steps and --shot")
        out = args.out or OUT_ROOT / (args.shot or Path(realtime).stem)
        report = match(reference, realtime, beauty_look_path=args.beauty_look,
                       world_overrides_path=args.world_overrides, preset=args.preset)
        written = write_outputs(report, out)
    except LookMatchError as exc:
        print(f"REFUSED -- {exc}")
        return 3
    for name, row in report["comparison"]["regions"].items():
        diff = row["diff"]
        print(f"[{name:8s}] {row['reference']['pixels']:8d} px  luminance {diff['luminance_stops']:+.2f} stops  "
              f"dE00 means {diff['delta_e00_of_means']:.2f} (per pixel {diff['delta_e00_per_pixel_mean']:.2f})  "
              f"contrast x{(diff['contrast_ratio'] or 0):.3f}  shadow depth {diff['shadow_depth_stops']:+.2f} stops")
    for name, why in report["comparison"]["skipped"].items():
        print(f"[{name:8s}] skipped: {why}")
    for row in report["suggestions"]:
        print(f"suggest {row['constant']}: {row['from']} -> {row['to']}  ({row['reason']})")
    for line in report["not_judged"]:
        print(f"not judged: {line}")
    if report["command_flags"]:
        print("add to the realtime render's command line: " + " ".join(report["command_flags"]))
    print("converged: every judged region is within tolerance" if report["converged"]
          else f"{len(report['suggestions'])} suggestion(s); apply, re-render the beauty, match again")
    for name, path in written.items():
        print(f"wrote {name}: {path or '(no beauty-look plan found; pass --beauty-look)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
