"""Verify a captured run's geometry: the phase's pass/fail summary.

    .venv/bin/python -m flightsim.verify runs/demo [--against runs/demo2]

Runs :mod:`core.capture.verify` over a run directory written by
``python -m flightsim.capture``: manifest schema, field finiteness,
geometry recovery (independent reprojection), cross-view consistency
(two-view triangulation), count exactness and -- where the engine's
consume-poses pass rendered frames under ``frames/<camera_id>/`` --
engine parity (applied vs solved pose and time per frame, the PNG
named by index at the manifest's size, the aircraft reprojected
through the applied pose) -- plus, with ``--against``, temporal
alignment between two runs of the same simulation captured with
different cameras. With no engine frames the engine check prints
``[AWAITING] engine_parity: awaiting engine frames ...``: neither
passed nor failed, and never counted as passed.

Exit code 0 when every check that ran passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="verify a captured run's recorded geometry")
    parser.add_argument("run_dir", help="a directory holding "
                                        "capture_manifest.json")
    parser.add_argument("--against", default=None,
                        help="a second run of the SAME simulation with "
                             "different cameras, for the temporal-"
                             "alignment check")
    args = parser.parse_args(argv)

    from core.capture.verify import verify_run

    report = verify_run(args.run_dir, other_run_dir=args.against)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
