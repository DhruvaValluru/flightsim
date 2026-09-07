"""Verify a captured run's geometry: the phase's pass/fail summary.

    .venv/bin/python -m flightsim.verify runs/demo [--against runs/demo2]

Runs :mod:`core.capture.verify` over a run directory written by
``python -m flightsim.capture``:

* manifest schema and field finiteness;
* **intrinsics against the stated lens** and **the solved pose against
  the stated camera** -- the two checks whose independent reference is
  the specification, so they can fail with no engine present;
* geometry recovery (the aircraft in front of and inside the frames
  that claim to see it, and the two orientation encodings agreeing);
* **landmark reprojection** and **two-view triangulation** against the
  render host's own projection, which need rendered frames and report
  NOT RUN without them rather than passing on a tautology;
* count exactness against the number each camera's spec REQUESTED;
* temporal alignment, with ``--against``.

A check that could not run is named as NOT RUN and is not counted as a
pass. Exit code 0 when no check failed, 1 otherwise.
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
                             "alignment check (without it that check "
                             "reports NOT RUN rather than being silently "
                             "omitted)")
    args = parser.parse_args(argv)

    from core.capture.verify import verify_run

    report = verify_run(args.run_dir, other_run_dir=args.against)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
