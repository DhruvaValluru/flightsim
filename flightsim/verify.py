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


def _capture(spec_path: Path, out: Path, render: bool) -> int:
    """One capture, as a subprocess of this interpreter."""
    import subprocess

    command = [sys.executable, "-m", "flightsim.capture",
               str(spec_path), "--out", str(out)]
    if render:
        command.append("--render")
    print(f"  capturing {out.name} ...")
    return subprocess.run(command, cwd=str(REPO)).returncode


def _camera_sets(args) -> int:
    """Capture one spec twice with different cameras, then align them.

    Temporal alignment is the property that the CAMERA SET does not
    perturb the simulation or the capture clock: state different
    cameras over the same scenario and the frame sets must land on the
    same instants. It has always been real, and it has almost never
    run, because exercising it meant remembering to capture twice by
    hand and then pass --against. In practice it reported NOT RUN,
    which is not a pass and was not being read as one either.

    The two sets come out of the spec's own camera list, split in half.
    That makes the two runs differ in exactly one thing -- which
    cameras were asked for -- rather than in whatever else two
    hand-written example files happen to disagree about.
    """
    from core.scenario.spec import ScenarioSpec

    spec_path = Path(args.camera_sets)
    try:
        spec = ScenarioSpec.read(spec_path)
    except ValueError as exc:
        print(f"REFUSED -- {exc}")
        return 2
    cameras = list(spec.cameras or [])
    if len(cameras) < 2:
        print(f"REFUSED -- verify.camera_sets: {spec_path} states "
              f"{len(cameras)} camera(s); two sets need at least two, "
              f"because the property under test is that the camera set "
              f"does not change the capture clock")
        return 2

    half = len(cameras) // 2
    sets = {"set_a": cameras[:half], "set_b": cameras[half:]}

    # A spurious red is worse than a NOT RUN. Alignment compares the
    # capture INSTANTS, so two sets that requested different schedules
    # legitimately do not align -- that is the spec's shape, not a
    # defect, and reporting it as a failure would teach people to
    # ignore the check. Say up front that this spec cannot answer the
    # question.
    def schedule_of(camera):
        return (str(camera.trigger.value),
                float(camera.capture_count.value),
                float(camera.period_s.value),
                float(camera.distance_m.value))

    requested = {name: {schedule_of(c) for c in group}
                 for name, group in sets.items()}
    if len(set().union(*requested.values())) > 1:
        print(f"REFUSED -- verify.camera_sets: the two camera sets ask "
              f"for different capture schedules "
              f"({sorted(requested['set_a'])} against "
              f"{sorted(requested['set_b'])}), so their frame sets are "
              f"not supposed to align and grading them against each "
              f"other would report a failure that is not one. Use "
              f"--against with two runs you intend to compare")
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    directories = {}
    for name, group in sets.items():
        spec.cameras = group
        written = out / f"{name}.yaml"
        spec.write(written)
        directories[name] = out / name
        code = _capture(written, directories[name], args.render)
        if code != 0:
            print(f"REFUSED -- the {name} capture exited {code}; "
                  f"alignment needs both")
            return code

    from core.capture.verify import verify_run

    report = verify_run(directories["set_a"],
                        other_run_dir=directories["set_b"])
    print(report.render())
    return 0 if report.ok else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="verify a captured run's recorded geometry")
    parser.add_argument("run_dir", nargs="?", default=None,
                        help="a directory holding capture_manifest.json")
    parser.add_argument("--against", default=None,
                        help="a second run of the SAME simulation with "
                             "different cameras, for the temporal-"
                             "alignment check (without it that check "
                             "reports NOT RUN rather than being silently "
                             "omitted)")
    parser.add_argument("--camera-sets", default=None, metavar="SPEC",
                        help="capture SPEC twice, with each half of its "
                             "camera list, and grade the alignment "
                             "automatically -- so the check runs instead "
                             "of reporting NOT RUN. Needs --out")
    parser.add_argument("--out", default=None, metavar="DIR",
                        help="where --camera-sets writes its two runs")
    parser.add_argument("--render", action="store_true",
                        help="with --camera-sets, render both captures "
                             "(Windows with the bridge built)")
    args = parser.parse_args(argv)

    if args.camera_sets:
        if args.run_dir or args.against:
            parser.error("--camera-sets captures its own two runs; do "
                         "not also pass a run directory or --against")
        if not args.out:
            parser.error("--camera-sets needs --out DIR to capture into")
        return _camera_sets(args)
    if not args.run_dir:
        parser.error("a run directory is required (or --camera-sets SPEC "
                     "--out DIR)")

    from core.capture.verify import verify_run, write_verification

    report = verify_run(args.run_dir, other_run_dir=args.against)
    print(report.render())
    # The run keeps its verdict: the dataset export (flightsim.export)
    # refuses a run that has no verification.json or a failed check.
    written = write_verification(report, args.run_dir)
    print(f"  recorded: {written}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
