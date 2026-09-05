"""Verify a captured run's geometry: the phase's pass/fail report.

    .venv/bin/python -m flightsim.verify runs/demo [--against runs/demo_b]
        [--corrupt quaternion|aircraft|time|count|clock|flight|schedule|pose|lens|aim]
        [--json] [--brief]

Runs :mod:`core.capture.verify` over a run directory written by
``python -m flightsim.capture``: manifest schema, field finiteness,
geometry recovery (independent reprojection), cross-view consistency
(two-view triangulation, the rays cast from the poses recomputed from
the spec; SKIPPED by name for a single camera), count exactness,
flight, schedule, pose and aim fidelity (the records against
telemetry.json, the instants and the poses against what scenario.yaml
commands over it, the aircraft's pixel against the preset's promise)
and -- where the engine's consume-poses pass rendered frames
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

``--corrupt KIND`` is the instructor's switch: the manifest (with
telemetry.json and scenario.yaml) is copied to a SIBLING directory,
``<run>_corrupt_<kind>/`` (or ``--corrupt-dir DIR``) -- never inside the
run, which stays exactly what capture wrote, so nothing that zips,
lists or serves the run can pick a corrupted copy up -- and ONE named
edit applied (stated in the output), then the same verifier grades the
copy -- and must FAIL the named check with exit 1:

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
  (count_exactness: 23 against a declared 24);
* ``clock``      -- EVERY record's t_s += 0.5 s, sample_index untouched
  (flight_fidelity: the instants are not the telemetry's own at those
  samples; schedule_fidelity fails beside it);
* ``flight``     -- EVERY camera's every record: aircraft north += 50 m
  (flight_fidelity: the two views still agree with each other; since
  round 3 cross_view_consistency fails beside it, its rays cast from the
  recomputed poses meeting 50 m from the telemetry's aircraft, and from
  the records alone the manifest would pass -- only the telemetry
  tells);
* ``schedule``   -- one shared instant (the middle record of the first
  camera, and every other camera's record at that sample) moved ONE
  telemetry sample later with the flight's state AND the spec's solved
  pose at that sample copied in, so every per-record check passes
  (schedule_fidelity: the instant is not the one the spec's cameras
  schedule over this telemetry);
* ``pose``       -- the last camera's every record: the camera moved
  POSE_SHIFT_M east, quaternion and Euler angles untouched
  (pose_fidelity: the pose is not the one the spec's camera solves to
  over this telemetry; cross_view_consistency fails beside it on a
  two-camera run, the ray from the true pose through the moved
  record's label missing the aircraft);
* ``lens``       -- the first camera's every record: fx_px, fy_px and
  focal_length_mm scaled by LENS_SCALE (pose_fidelity: the lens is not
  the spec camera's; every record still projects the aircraft into the
  frame and its quaternion still agrees with its Euler angles, so
  geometry_recovery passes);
* ``aim``        -- the first camera's every record yawed AIM_TWIST_DEG
  with the quaternion and the Euler angles rotated TOGETHER, so
  geometry_recovery passes and the aircraft stays in frame
  (aim_fidelity: the aircraft's pixel is no longer where the preset's
  promise -- the lagged aim recomputed over the telemetry -- puts it;
  pose_fidelity and, on two cameras, cross_view_consistency fail
  beside it).

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

CORRUPT_KINDS = ("quaternion", "aircraft", "time", "count", "clock",
                 "flight", "schedule", "pose", "lens", "aim")
#: The check each corruption must fail, by name.
CORRUPT_FAILS = {"quaternion": "geometry_recovery",
                 "aircraft": "cross_view_consistency",
                 "time": "temporal_alignment",
                 "count": "count_exactness",
                 "clock": "flight_fidelity",
                 "flight": "flight_fidelity",
                 "schedule": "schedule_fidelity",
                 "pose": "pose_fidelity",
                 "lens": "pose_fidelity",
                 "aim": "aim_fidelity"}
#: Corruptions the judge's own demonstrations showed the verifier
#: passing (round 1: 5/5 on the clock and the flight; round 2: 7/7 on a
#: moved camera and a scaled lens): the edit each applies, stated so
#: the output can say it.
CLOCK_SHIFT_S = 0.5
FLIGHT_SHIFT_M = 50.0
POSE_SHIFT_M = 5.0
LENS_SCALE = 1.5
AIM_TWIST_DEG = 1.0


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
                        help="copy the manifest (with telemetry.json and "
                             "scenario.yaml) to a sibling directory "
                             "<run>_corrupt_<kind>/, apply ONE named edit "
                             "and verify the copy: the named check must "
                             "FAIL (exit 1); the run itself is untouched")
    parser.add_argument("--corrupt-dir", default=None, metavar="DIR",
                        help="where --corrupt writes its copy (default: "
                             "the sibling <run>_corrupt_<kind>/)")
    add_common_arguments(parser)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_command(_verify, build_parser(), argv, success_word="verified")


def corrupt_copy_dir(run_dir: Path, kind: str) -> Path:
    """Where the corrupted copy goes by default: a sibling of the run,
    ``<run>_corrupt_<kind>``, never a subdirectory of it."""
    run_dir = Path(run_dir)
    return run_dir.parent / f"{run_dir.name}_corrupt_{kind}"


def corrupt_manifest(run_dir: Path, kind: str,
                     copy_dir: Optional[Path] = None
                     ) -> Tuple[Path, str, Dict]:
    """Copy ``run_dir``'s manifest (with telemetry.json and scenario.yaml)
    to ``copy_dir`` (default :func:`corrupt_copy_dir`: the sibling
    ``<run>_corrupt_<kind>/``) with ONE named edit applied. Returns
    (copy_dir, the edit in words, the edit as data). Refuses by usage
    when the run cannot carry the edit (a second camera for
    ``aircraft``), or when the copy would land inside the run."""
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
    elif kind == "clock":
        count = 0
        for record in frames:
            record["t_s"] = float(record["t_s"]) + CLOCK_SHIFT_S
            count += 1
        words = (f"corrupted every record ({count} frames, both the "
                 f"sample_index and the aircraft state untouched): t_s += "
                 f"{CLOCK_SHIFT_S:g} s; the records still agree with each "
                 f"other, only the telemetry's clock says otherwise")
        edit = {"frames": count, "field": "t_s", "delta_s": CLOCK_SHIFT_S}
    elif kind == "flight":
        count = 0
        for record in frames:
            record["aircraft"]["north_m"] += FLIGHT_SHIFT_M
            count += 1
        words = (f"corrupted every camera's every record ({count} frames): "
                 f"aircraft north_m += {FLIGHT_SHIFT_M:g} m; the views still "
                 f"agree with EACH OTHER (cross_view_consistency passes), "
                 f"only the telemetry says the aircraft was elsewhere")
        edit = {"frames": count, "field": "aircraft.north_m",
                "delta_m": FLIGHT_SHIFT_M}
    elif kind == "schedule":
        from core.capture.verify import (
            read_telemetry_columns, telemetry_state_at,
        )

        columns = read_telemetry_columns(run_dir)
        if columns is None:
            raise UsageError(f"{run_dir}: --corrupt schedule needs "
                             f"telemetry.json beside the manifest to copy "
                             f"the flight's state from")
        own = [r for r in frames if r["camera_id"] == cameras[0]]
        target = own[len(own) // 2]
        sample = int(target["sample_index"])
        moved = sample + 1
        taken = {int(r["sample_index"]) for r in own}
        if moved >= len(columns["t"]) or moved in taken:
            raise UsageError(f"{run_dir}: camera {cameras[0]!r} has no free "
                             f"telemetry sample after sample {sample} to "
                             f"move its middle instant to")
        from core.capture.verify import (
            read_scenario_spec, recompute_pose_tracks, track_record,
        )

        spec = read_scenario_spec(run_dir)
        if spec is None:
            raise UsageError(f"{run_dir}: --corrupt schedule needs "
                             f"scenario.yaml beside the manifest to copy "
                             f"the spec's pose at the moved sample from")
        tracks, track_problems = recompute_pose_tracks(manifest, spec,
                                                       columns)
        if track_problems:
            raise UsageError(f"{run_dir}: the spec's pose tracks cannot be "
                             f"recomputed over this telemetry "
                             f"({track_problems[0]})")
        flight = telemetry_state_at(columns, manifest.get("frame"), moved)
        before_t = float(target["t_s"])
        touched = []
        for record in frames:
            if int(record["sample_index"]) != sample:
                continue
            pose = track_record(tracks.get(record["camera_id"]), moved)
            if pose is None:
                raise UsageError(f"{run_dir}: camera "
                                 f"{record['camera_id']!r} has no solved "
                                 f"pose at sample {moved} to copy")
            record["sample_index"] = moved
            record["t_s"] = flight["t_s"]
            for key in ("north_m", "east_m", "alt_m", "roll_deg",
                        "pitch_deg", "heading_deg"):
                if flight[key] is not None:
                    record["aircraft"][key] = flight[key]
            # The spec's own pose and lens at the new sample, so the
            # pose check and the cross-view rays see an honest record.
            for key in ("position_north_m", "position_east_m",
                        "position_alt_m", "quaternion_wxyz", "yaw_deg",
                        "pitch_deg", "roll_deg", "focal_length_mm",
                        "fx_px", "fy_px"):
                record[key] = pose[key]
            touched.append(f"{record['camera_id']} #{record['index']}")
        words = (f"corrupted the instant at sample {sample} "
                 f"(t={before_t:.3f} s -> sample {moved}, "
                 f"t={flight['t_s']:.3f} s) on {', '.join(touched)}: "
                 f"sample_index, t_s, the aircraft state and the camera "
                 f"pose moved one telemetry sample later, the flight's own "
                 f"state and the spec's own solved pose at that sample "
                 f"copied in, so every per-record check still passes; only "
                 f"the schedule recomputed from the spec says the instant "
                 f"is wrong")
        edit = {"frames": touched, "from_sample": sample, "to_sample": moved,
                "to_t_s": flight["t_s"]}
    elif kind == "pose":
        count = 0
        for record in frames:
            if record["camera_id"] == cameras[-1]:
                record["position_east_m"] += POSE_SHIFT_M
                count += 1
        words = (f"corrupted {cameras[-1]}: every record's camera "
                 f"position_east_m += {POSE_SHIFT_M:g} m ({count} frames); "
                 f"quaternion, Euler angles, lens and aircraft untouched, "
                 f"so the records agree with themselves and with the "
                 f"flight; only the pose recomputed from the spec says "
                 f"the camera was elsewhere")
        edit = {"camera_id": cameras[-1], "frames": count,
                "field": "position_east_m", "delta_m": POSE_SHIFT_M}
    elif kind == "lens":
        count = 0
        for record in frames:
            if record["camera_id"] == cameras[0]:
                record["fx_px"] *= LENS_SCALE
                record["fy_px"] *= LENS_SCALE
                record["focal_length_mm"] *= LENS_SCALE
                count += 1
        words = (f"corrupted {cameras[0]}: every record's fx_px, fy_px and "
                 f"focal_length_mm x {LENS_SCALE:g} ({count} frames); the "
                 f"pose and the aircraft untouched, the aircraft still in "
                 f"frame, so geometry_recovery passes; only the lens "
                 f"recomputed from the spec's camera says otherwise")
        edit = {"camera_id": cameras[0], "frames": count,
                "fields": ["fx_px", "fy_px", "focal_length_mm"],
                "scale": LENS_SCALE}
    elif kind == "aim":
        from core.capture.poses import euler_to_quat

        count = 0
        for record in frames:
            if record["camera_id"] == cameras[0]:
                record["yaw_deg"] = (float(record["yaw_deg"])
                                     + AIM_TWIST_DEG) % 360.0
                record["quaternion_wxyz"] = list(euler_to_quat(
                    float(record["roll_deg"]), float(record["pitch_deg"]),
                    float(record["yaw_deg"])))
                count += 1
        words = (f"corrupted {cameras[0]}: every record yawed "
                 f"{AIM_TWIST_DEG:g} deg with the quaternion and the Euler "
                 f"angles rotated together ({count} frames); position, "
                 f"lens and aircraft untouched, the aircraft still in "
                 f"frame, so geometry_recovery passes; only the promise "
                 f"recomputed over the telemetry says the camera looks "
                 f"the wrong way")
        edit = {"camera_id": cameras[0], "frames": count,
                "field": "yaw_deg + quaternion_wxyz",
                "delta_deg": AIM_TWIST_DEG}
    else:
        raise UsageError(f"unknown --corrupt kind {kind!r}")

    copy_dir = Path(copy_dir) if copy_dir is not None \
        else corrupt_copy_dir(run_dir, kind)
    if copy_dir.resolve() == Path(run_dir).resolve() or \
            Path(run_dir).resolve() in copy_dir.resolve().parents:
        raise UsageError(f"--corrupt-dir {copy_dir} lies inside the run "
                         f"{run_dir}; the run directory stays exactly what "
                         f"capture wrote (the default is the sibling "
                         f"{corrupt_copy_dir(run_dir, kind)})")
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
        graded, words, edit = corrupt_manifest(
            run_dir, args.corrupt,
            Path(args.corrupt_dir) if args.corrupt_dir else None)
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
