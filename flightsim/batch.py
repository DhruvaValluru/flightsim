"""Run a matrix of specs: every cell x seed captured and verified.

    .venv/bin/python -m flightsim.batch examples/batch_matrix.yaml --out runs/batch/demo
    .venv/bin/python -m flightsim.batch matrix.yaml --out DIR --workers 4 --no-resume

Each run lands in ``DIR/<spec digest[:16]>/`` (content-addressed: the
same spec never runs twice), captured by ``flightsim.capture`` as a
subprocess with the matrix's capture options, then verified, with
``verification.json`` written beside the manifest. ``DIR/ledger.jsonl``
gets one line per run as it completes, failures included; a resumed
batch skips runs already captured and retries failed captures. Exit 0
when every run captured and verified, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="run a matrix of specs")
    parser.add_argument("matrix", help="matrix YAML (base, factors, seeds, ...)")
    parser.add_argument("--out", required=True, help="batch directory")
    parser.add_argument("--workers", type=int, default=None,
                        help="concurrent captures (default: the matrix's)")
    parser.add_argument("--no-resume", action="store_true",
                        help="start fresh: discard the ledger instead of "
                             "skipping runs it records")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the runs the matrix commands and exit")
    args = parser.parse_args(argv)

    from core.dataset.batch import (
        BatchError, build_cases, read_matrix, run_batch,
    )

    try:
        matrix = read_matrix(args.matrix)
        cases = build_cases(matrix)
    except BatchError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    print(f"matrix {Path(args.matrix).name}: {len(cases)} run(s) = "
          f"{len(cases) // max(1, len(matrix.seeds))} cell(s) x "
          f"{len(matrix.seeds)} seed(s), base {matrix.base.name}")
    if args.dry_run:
        for case in cases:
            print(f"  {case.run_id}  seed {case.seed}  {case.overrides}")
        return 0
    result = run_batch(matrix, args.out, resume=not args.no_resume,
                       workers=args.workers, progress=lambda line: print("  " + line))
    print(f"batch {result.out_dir}: {result.completed} captured, "
          f"{result.skipped} skipped (already in the ledger), "
          f"{result.failed} failed, {result.unverified} captured but "
          f"NOT verified")
    print(f"  ledger: {result.out_dir / 'ledger.jsonl'}")
    return 0 if (result.failed == 0 and result.unverified == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
