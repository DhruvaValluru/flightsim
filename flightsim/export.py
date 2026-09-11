"""Export verified runs as a labelled dataset, with a card.

    .venv/bin/python -m flightsim.export runs/batch/demo --out datasets/demo --format coco
    .venv/bin/python -m flightsim.export runs/a runs/b --out datasets/ab --format kitti
    .venv/bin/python -m flightsim.export runs/batch/demo --out datasets/wds --format webdataset --image sensor

Inputs are run directories (capture_manifest.json inside) or batch
directories of them. Every run must carry a verification.json with no
failed check (``python -m flightsim.verify <run>`` writes it; the
batch runner writes it too) -- an unverified run refuses the export by
name. Frames are split by simulation digest (one flight, one side).
The card (DATASET_CARD.md + dataset.json) says what is in the dataset,
how it was split, the conventions each format uses, and what is NOT
claimed. Exit 0 on success, 2 on a named refusal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main(argv: Optional[Sequence[str]] = None) -> int:
    from core.dataset.export import DEFAULT_FRACTIONS, FORMATS

    parser = argparse.ArgumentParser(description="export verified runs as a dataset")
    parser.add_argument("runs", nargs="+", help="run directories or batch directories")
    parser.add_argument("--out", required=True, help="dataset directory")
    parser.add_argument("--format", choices=FORMATS, required=True)
    parser.add_argument("--split", default=",".join(str(f) for f in DEFAULT_FRACTIONS),
                        help="train,val,test fractions (sum to 1)")
    parser.add_argument("--split-seed", type=int, default=0,
                        help="seed of the simulation shuffle behind the split")
    parser.add_argument("--image", choices=("ideal", "sensor"), default="ideal",
                        help="which frame to export: the ideal render or the "
                             "sensor-model frame (with labels_sensor)")
    parser.add_argument("--labels-only", action="store_true",
                        help="export annotations for frames whose images are "
                             "absent (a headless capture), recorded in the card")
    parser.add_argument("--shard-size", type=int, default=1000,
                        help="webdataset samples per tar")
    args = parser.parse_args(argv)

    from core.dataset.export import ExportError, export

    try:
        fractions = tuple(float(f) for f in args.split.split(","))
        card = export(args.runs, args.out, args.format, fractions=fractions,
                      seed=args.split_seed, image=args.image,
                      labels_only=args.labels_only, shard_size=args.shard_size)
    except ExportError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    except ValueError as exc:
        print(f"REFUSED -- export.arguments: {exc}")
        return 2
    print(f"exported {card['frames']} frame(s) from {len(card['runs'])} run(s) "
          f"as {card['format']} into {args.out}")
    print("  splits: " + ", ".join(f"{s} {n}" for s, n in card["frames_per_split"].items())
          + f" (by simulation digest, seed {card['split']['seed']})")
    print(f"  card:   {Path(args.out) / 'DATASET_CARD.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
