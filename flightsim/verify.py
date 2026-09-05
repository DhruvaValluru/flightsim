"""Verify a captured run's geometry: the phase's pass/fail report.

    .venv/bin/python -m flightsim.verify runs/demo [--against runs/demo_b]
        [--corrupt quaternion|aircraft|time|count] [--json] [--brief]

Runs :mod:`core.capture.verify` over a run directory written by
``python -m flightsim.capture``: manifest schema, field finiteness,
geometry recovery (independent reprojection), cross-view consistency
(two-view triangulation; SKIPPED by name for a single camera), count
exactness and -- where the engine's consume-poses pass rendered frames
under ``frames/<camera_id>/`` -- engine parity (applied vs solved pose
and time per frame, the PNG named by index at the manifest's size, the
aircraft reprojected through the applied pose) -- plus, with
``--against``, temporal alignment between two runs of the same
simulation captured with different cameras. With no engine frames the
engine check is ``AWAITING`` in those words: neither passed nor failed,
never counted as passed.

What is printed (flightsim.report, the surface flightsim.capture
shares): the header (digests, scene, flight, one line per camera), the
per-camera table of scheduled instants (``--brief`` collapses a uniform
schedule to one line), the verification table with each check's
measured value, tolerance, status and WHERE, the detail lines, the
summary, and a verdict line that starts with the exit code's word and
names the artefacts (the manifest graded, verify.json written beside
it). ``--json`` prints the same document as data. No FDM is ever
constructed here, so nothing of JSBSim's reaches stdout.

``--corrupt KIND`` is the instructor's switch: the manifest is copied
to ``<run>/corrupt_<kind>/`` and ONE named edit applied (stated in the
output), then the same verifier grades the copy -- and must FAIL the
named check with exit 1:

* ``quaternion`` -- the first camera's frame 3: quaternion y += 0.05
  (geometry_recovery: the quaternion and Euler encodings no longer
  project the aircraft to the same pixel);
* ``aircraft``   -- the second camera's every frame: aircraft north
  += 5 m (cross_view_consistency: the two views no longer triangulate
  to one point; needs a two-camera run);
* ``time``       -- the first camera's frame 3: t_s += one fixed step
  (temporal_alignment against ``--against``, which defaults to the
  original run: the instant sets differ);
* ``count``      -- the first camera's last frame record dropped
  (count_exactness: 23 against a declared 24).

Exit codes (one table with flightsim.capture): 0 verified ("verified:"
line); 1 FAILED (a check FAILED; "FAILED verification:" line); 2
REFUSED (unused here: verify refuses nothing, it grades); 3 USAGE (the
run directory holds no capture_manifest.json, a --corrupt kind the run
cannot carry); 4 UNEXPECTED.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from flightsim.report import (  # noqa: E402
    EXIT_DONE, EXIT_FAILED, ReportParser, UsageError, add_common_arguments,
    flight_words_from_run, header, run_command, schedule_tables,
)

CORRUPT_KINDS = ("quaternion", "aircraft", "time", "count")
#: The check each corruption must fail, by name.
CORRUPT_FAILS = {"quaternion": "geometry_recovery",
                 "aircraft": "cross_view_consistency",
                 "time": "temporal_alignment",
                 "count": "count_exactness"}


def build_parser() -> ReportParser:
    parser = ReportParser(
        prog="python -m flightsim.verify",
        description="verify a captured run's recorded geometry")
    parser.add_argument("run_dir", help="a directory holding "
                                        "capture_manifest.json")
    parser.add_argument("--against", default=None,
                        help="a second run of the SAME simulation with "
                             "different cameras, for the temporal-"
                             "alignment check")
    parser.add_argument("--corrupt", choices=CORRUPT_KINDS, default=None,
                        help="copy the manifest to <run>/corrupt_<kind>/, "
                             "apply ONE named edit and verify the copy: "
                             "the named check must FAIL (exit 1)")
    add_common_arguments(parser)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_command(_verify, build_parser(), argv, success_word="verified")


def corrupt_manifest(run_dir: Path, kind: str) -> Tuple[Path, str, Dict]:
    """Copy ``run_dir``'s manifest to ``run_dir/corrupt_<kind>/`` with
    ONE named edit applied. Returns (copy_dir, the edit in words, the
    edit as data). Refuses by usage when the run cannot carry the edit
    (a second camera for ``aircraft``)."""
    from core.capture.manifest import read_capture_manifest

    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    cameras = [b["camera_id"] for b in manifest.get("cameras", [])]
    if not cameras:
        raise UsageError(f"{run_dir}: the manifest carries no camera to "
                         f"corrupt")
    frames = manifest["frames"]

    def frame(camera_id: str, index: int) -> Dict:
        for record in frames:
            if record["camera_id"] == camera_id and record["index"] == index:
                return record
        raise UsageError(f"{run_dir}: camera {camera_id!r} has no frame "
                         f"{index} to corrupt (fewer than {index + 1} "
                         f"captures)")

    if kind == "quaternion":
        target = frame(cameras[0], 3)
        before = list(target["quaternion_wxyz"])
        target["quaternion_wxyz"][2] = before[2] + 0.05
        words = (f"corrupted {cameras[0]} frame 3 (t={target['t_s']:.3f} s) "
                 f"quaternion y += 0.05 ({before[2]:.6f} -> "
                 f"{target['quaternion_wxyz'][2]:.6f}); the Euler angles "
                 f"are untouched")
        edit = {"camera_id": cameras[0], "index": 3, "field":
                "quaternion_wxyz[2]", "delta": 0.05, "before": before[2]}
    elif kind == "aircraft":
        if len(cameras) < 2:
            raise UsageError(f"{run_dir}: --corrupt aircraft needs a "
                             f"two-camera run (cross-view consistency is "
                             f"SKIPPED for one camera; this run has "
                             f"{len(cameras)}); use "
                             f"examples/cameras_multi.yaml")
        count = 0
        for record in frames:
            if record["camera_id"] == cameras[1]:
                record["aircraft"]["north_m"] += 5.0
                count += 1
        words = (f"corrupted {cameras[1]}: every frame's recorded aircraft "
                 f"north_m += 5 m ({count} frames); {cameras[0]}'s records "
                 f"are untouched, so the two views disagree")
        edit = {"camera_id": cameras[1], "frames": count,
                "field": "aircraft.north_m", "delta_m": 5.0}
    elif kind == "time":
        target = frame(cameras[0], 3)
        step = float(manifest.get("step_s") or 1.0 / float(
            manifest.get("rate_hz") or 120.0))
        before = float(target["t_s"])
        target["t_s"] = before + step
        words = (f"corrupted {cameras[0]} frame 3 t_s += one fixed step "
                 f"({step:.6f} s: {before:.6f} -> {target['t_s']:.6f} s)")
        edit = {"camera_id": cameras[0], "index": 3, "field": "t_s",
                "delta_s": step, "before": before}
    elif kind == "count":
        own = [r for r in frames if r["camera_id"] == cameras[0]]
        if len(own) < 2:
            raise UsageError(f"{run_dir}: camera {cameras[0]!r} has only "
                             f"{len(own)} frame(s); nothing to drop")
        last = own[-1]
        manifest["frames"] = [r for r in frames if r is not last]
        words = (f"corrupted {cameras[0]}: frame record {last['index']} "
                 f"(t={last['t_s']:.3f} s) dropped; capture_count stays "
                 f"{len(own)}")
        edit = {"camera_id": cameras[0], "dropped_index": last["index"],
                "declared": len(own)}
    else:
        raise UsageError(f"unknown --corrupt kind {kind!r}")

    copy_dir = run_dir / f"corrupt_{kind}"
    if copy_dir.exists():
        shutil.rmtree(copy_dir)
    copy_dir.mkdir(parents=True)
    (copy_dir / "capture_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    for name in ("scenario.yaml", "telemetry.json"):
        if (run_dir / name).is_file():
            shutil.copy2(run_dir / name, copy_dir / name)
    return copy_dir, words, edit


def _verify(args, doc: dict) -> int:
    from core.capture.verify import verify_run

    run_dir = Path(args.run_dir)
    manifest_path = run_dir / "capture_manifest.json"
    if not manifest_path.is_file():
        raise UsageError(f"{run_dir} holds no capture_manifest.json; "
                         f"nothing to verify (python -m flightsim.capture "
                         f"<spec> --out {run_dir} writes one)")
    against = Path(args.against) if args.against else None
    if against is not None and not (against / "capture_manifest.json").is_file():
        raise UsageError(f"--against {against} holds no "
                         f"capture_manifest.json")

    graded = run_dir
    doc["artefacts"] = {"run_dir": str(run_dir), "manifest": str(manifest_path)}
    if args.corrupt:
        if against is None and args.corrupt == "time":
            # The alignment check needs a second run; the original,
            # uncorrupted one is the honest counterpart.
            against = run_dir
        graded, words, edit = corrupt_manifest(run_dir, args.corrupt)
        print(f"corrupt {args.corrupt}: manifest copied to {graded}; {words}")
        print(f"  expected: [FAIL] {CORRUPT_FAILS[args.corrupt]}, exit 1")
        doc["corrupt"] = {"kind": args.corrupt, "copy_dir": str(graded),
                          "edit": edit, "words": words,
                          "expected_fail": CORRUPT_FAILS[args.corrupt]}
        doc["artefacts"]["graded_manifest"] = str(
            graded / "capture_manifest.json")
    if against is not None:
        doc["artefacts"]["against"] = str(against / "capture_manifest.json")

    from core.capture.manifest import read_capture_manifest

    manifest = read_capture_manifest(graded / "capture_manifest.json")
    words = flight_words_from_run(graded)
    head_lines, head_data = header(manifest, graded, **words)
    for line in head_lines:
        print(line)
    doc["header"] = head_data
    if against is not None:
        print(f"against:     {against} (temporal alignment)")
    table_lines, table_data = schedule_tables(manifest, brief=args.brief)
    print(f"scheduled {len(manifest.get('frames', []))} frames across "
          f"{len(manifest.get('cameras', []))} camera(s)")
    for line in table_lines:
        print(line)
    doc["schedule"] = table_data

    report = verify_run(graded, other_run_dir=against)
    print(report.render())
    doc["verification"] = report.to_dict()
    verify_json = graded / "verify.json"
    verify_json.write_text(json.dumps(report.to_dict(), indent=1),
                           encoding="utf-8")
    doc["artefacts"]["verify_json"] = str(verify_json)

    frames = len(manifest.get("frames", []))
    cameras = len(manifest.get("cameras", []))
    if args.corrupt:
        expected = CORRUPT_FAILS[args.corrupt]
        failed = [c.name for c in report.failed]
        if expected in failed:
            print(f"FAILED verification: as expected for --corrupt "
                  f"{args.corrupt}, {expected} FAILED"
                  + (f" (also: {', '.join(n for n in failed if n != expected)})"
                     if len(failed) > 1 else "")
                  + f"; {graded / 'capture_manifest.json'} graded, report "
                    f"{verify_json}")
            return EXIT_FAILED
        print(f"UNEXPECTED: --corrupt {args.corrupt} did not fail "
              f"{expected} (FAILED: {', '.join(failed) or 'none'}); the "
              f"verifier cannot be trusted to catch this corruption")
        from flightsim.report import EXIT_UNEXPECTED

        return EXIT_UNEXPECTED
    if report.ok:
        print(f"verified: {manifest_path} ({frames} frame records, {cameras} "
              f"camera(s)); report {verify_json}")
        return EXIT_DONE
    print(f"FAILED verification: {manifest_path} ({frames} frame records, "
          f"{cameras} camera(s)); FAILED: "
          f"{', '.join(c.name for c in report.failed)}; report {verify_json}")
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
