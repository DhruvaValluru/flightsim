"""Capture a scenario: spec -> validate -> run -> solved geometry.

    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml \
        --out runs/demo [--terrain runs/terrain/matterhorn] [--max-previews N]

What happens, in order (each step refuses by name rather than
approximating):

1. the spec is read (spec_version 6 -- older versions refuse by name);
2. scene-free validation runs (the full validate(), cameras included);
3. world-anchored cameras are checked against the scene BEFORE the run
   (terrain clearance, scene bounds, the tornado core);
4. the scenario runs HEADLESSLY (core.scenario.runner.run_spec, the
   real flight dynamics -- with --terrain, over the real raster);
5. every camera's pose track is solved and its capture schedule
   computed from the recorded telemetry (a spec with no cameras gets
   the documented default camera);
6. the solved tracks are re-checked against the scene along the whole
   run;
7. capture_manifest.json, telemetry.json, scenario.yaml and one
   geometry preview per scheduled frame are written;
8. on a machine with the UE render half, pixels would render beside
   them; anywhere else rendering REFUSES BY NAME (ue.platform) while
   steps 1-7 stand -- the manifest and previews are the off-mac
   deliverable.

Exit codes: 0 = captured (even when rendering was refused by name);
2 = a named validation/schedule refusal; 1 = unexpected failure.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _tornado_hazard_block(spec):
    """The straight-line severe-event placement, in the scene frame:
    45% of the still-air run ahead along the heading, the recorded
    aim's abeam offset applied -- the same figures the headless
    runner's environment uses. (The webapp's terrain runs refine this
    onto the pre-flown banked track; the headless CLI flies straight
    and the straight-line point IS its track.)"""
    if str(spec.weather_event.value) != "tornado":
        return None
    from core.environment.tornado import FADE_TOP_M, R_CORE_M
    from core.fdm import units as u

    seconds = float(spec.duration.value)
    ahead = 0.45 * u.kt_to_mps(float(spec.airspeed.value)) * seconds
    heading = math.radians(float(spec.heading.value))
    aim = str(spec.weather_event.detail.get("aim", "abeam"))
    offset = 0.0 if aim == "core" else 2.5 * R_CORE_M
    return {
        "centre_north_m": (ahead * math.cos(heading)
                           + offset * math.cos(heading + math.pi / 2)),
        "centre_east_m": (ahead * math.sin(heading)
                          + offset * math.sin(heading + math.pi / 2)),
        "r_core_m": R_CORE_M, "fade_top_m": FADE_TOP_M,
    }


def _refuse(violations) -> int:
    print("REFUSED -- by name:")
    for v in violations:
        print(f"  {v.render() if hasattr(v, 'render') else v}")
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="validate, run headlessly, and capture a scenario's "
                    "camera geometry")
    parser.add_argument("spec", help="scenario spec YAML (spec_version 6)")
    parser.add_argument("--out", required=True, help="run directory")
    parser.add_argument("--terrain", default=None,
                        help="baked heightfield stem (<stem>.r16 + .json) "
                             "for real-raster physics and camera checks")
    parser.add_argument("--synth-terrain", action="store_true",
                        help="synthesise a raster CENTRED on the spec's "
                             "own origin and fly over that -- real "
                             "terrain physics and real raster camera "
                             "checks with no network and no account, "
                             "deterministic from its seed. Ignored when "
                             "--terrain names a bake.")
    parser.add_argument("--max-previews", type=int, default=8,
                        help="cap geometry preview images per run "
                             "(default 8; they are near-identical frame "
                             "to frame and each draws a full shaded "
                             "scene). 0 writes none.")
    parser.add_argument("--render", action="store_true",
                        help="also render the frames through the solved "
                             "poses (Windows with UE 5.5 and the bridge "
                             "built; refuses by name anywhere else). "
                             "Implies --card.")
    parser.add_argument("--card", action="store_true",
                        help="also write card.json carrying each camera's "
                             "solved pose track, for the UE commandlet's "
                             "consume-poses mode on a render-capable "
                             "machine (-camera-index=N, one pass per "
                             "camera)")
    args = parser.parse_args(argv)

    from core.capture.manifest import (
        build_capture_manifest, write_capture_manifest,
    )
    from core.capture.poses import SceneFrame, solve_pose_track
    from core.capture.preview import render_previews
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.capture.validate import (
        static_camera_violations, track_violations,
    )
    from core.scenario.camera import default_cameras
    from core.scenario.runner import run_spec
    from core.scenario.spec import ScenarioSpec
    from core.scenario.validate import validate

    try:
        spec = ScenarioSpec.read(args.spec)
    except ValueError as exc:
        print(f"REFUSED -- {exc}")
        return 2

    if args.render:
        # The render hosts have no autopilot, take only calibrated
        # airspeed, and hold mass for the clip. The webapp has projected
        # every spec through this before handing it to the commandlet
        # since Gate 8.3; --render did not, so a spec with the DEFAULT
        # hold_state (true) flew headlessly, solved every pose, launched
        # the engine, and only then hit the commandlet's named refusal.
        # Project first, say what moved, and solve the poses over the
        # flight the host will actually fly.
        from webapp.runs import project_for_ue_host

        # spec.quantities() yields (section, name, quantity).
        before = {name: q.value for _, name, q in spec.quantities()}
        project_for_ue_host(spec)
        moved = [f"{name}: {before[name]!r} -> {q.value!r}"
                 for _, name, q in spec.quantities()
                 if before.get(name) != q.value]
        if moved:
            print("projected for the render host (no autopilot; "
                  "calibrated airspeed only):")
            for line in moved:
                print(f"  {line}")

    heightfield = None
    terrain_ground = None
    terrain_stem = args.terrain
    if terrain_stem is None and args.synth_terrain:
        # Synthesised, not fetched: the same Heightfield a DEM bakes to,
        # centred on this spec's origin so the flight is actually over
        # it, deterministic from its seed, and available on a fresh
        # clone with no network. Real geography still comes from a real
        # bake through --terrain.
        from core.terrain.synthesis import ensure_ridge_for_origin

        terrain_stem = str(ensure_ridge_for_origin(
            REPO / "runs" / "terrain",
            float(spec.latitude.value), float(spec.longitude.value),
            name=f"synth_{spec.name or 'scene'}"))
        print(f"synthesised terrain: {terrain_stem} (deterministic; no "
              f"network)")
    if terrain_stem:
        from core.terrain.ground import TerrainGround
        from core.terrain.heightfield import Heightfield

        heightfield = Heightfield.read(Path(terrain_stem))
        terrain_ground = TerrainGround(heightfield)

    frame = SceneFrame.for_spec(spec, heightfield)
    tornado = _tornado_hazard_block(spec)

    report = validate(spec)
    if not report.ok:
        return _refuse(report.violations)
    static = static_camera_violations(
        spec, heightfield, frame, tornado,
        )
    if static:
        return _refuse(static)

    print(f"spec {spec.digest()[:16]} valid; running headlessly...")
    # A terrain impact or an untrimmable state is a NAMED outcome of the
    # scenario, not a bug in the tool: report it the way every other
    # refusal is reported instead of unwinding a stack trace at the
    # instructor. (Measured: flying a 1200 m example over a raster whose
    # ridge reaches 3043 m printed a traceback.)
    from core.fdm.errors import TrimError
    from core.terrain.contact import TerrainImpactError

    try:
        result = run_spec(spec, terrain_ground=terrain_ground)
    except TerrainImpactError as exc:
        print(f"REFUSED -- terrain.impact: {exc}")
        return 2
    except TrimError as exc:
        print(f"REFUSED -- trim: {exc}")
        return 2
    columns = result.telemetry.columns

    cameras = spec.cameras or default_cameras(spec)
    if not spec.cameras:
        print("no camera stated: capturing with the documented default "
              "camera (the chase view)")
    tracks = []
    schedules = []
    try:
        for camera in cameras:
            tracks.append(solve_pose_track(columns, camera, frame))
            schedules.append(solve_schedule(columns, camera, frame))
    except ScheduleError as exc:
        print(f"REFUSED -- {exc}")
        return 2

    terrain_datum = float(spec.terrain_elevation.value)
    solved_violations = []
    for track in tracks:
        solved_violations.extend(track_violations(
            track, heightfield=heightfield, scene_frame=frame,
            tornado=tornado, terrain_elevation_m=terrain_datum))
    if solved_violations:
        return _refuse(solved_violations)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = build_capture_manifest(
        spec, columns, frame, tracks, schedules,
        output_digest=result.output_digest,
        scene={"key": "terrain" if heightfield else "flat",
               "terrain": terrain_stem},
        terrain_sha256=heightfield.digest() if heightfield else None,
        # The cameras that actually flew (default_cameras for a
        # camera-less spec); the digests stay the spec's own.
        cameras=cameras,
        # The scene's own known landmarks ride into the manifest so the
        # verifier has off-axis points that are not the aircraft.
        heightfield=heightfield, terrain_elevation_m=terrain_datum)
    manifest_path = write_capture_manifest(manifest, out)
    result.telemetry.write_json(out / "telemetry.json")
    spec.write(out / "scenario.yaml")
    (out / "run.json").write_text(json.dumps({
        "spec_digest": result.spec_digest,
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
    }, indent=1), encoding="utf-8")

    if args.card or args.render:
        # The run-card projection with the cameras block: spec fields +
        # solved pose tracks, computed HERE, consumed verbatim by the
        # commandlet's consume-poses mode. The commandlet's own named
        # refusals still govern anything it cannot honour (hold_state,
        # airspeed_kind, a track that does not cover the run).
        from core.scenario.card import write_run_card

        write_run_card(
            spec, out / "card.json",
            cameras=[track.card_block(camera, schedule, frame)
                     for camera, track, schedule
                     in zip(cameras, tracks, schedules)],
            landmarks=manifest.get("landmarks"),
            scene_crs=frame.crs if frame.declared else None)
        print(f"  card:     {out / 'card.json'} (consume-poses; one "
              f"commandlet pass per camera via -camera-index=N)")

    previews = render_previews(manifest, out, heightfield=heightfield,
                               scene_frame=frame,
                               terrain_elevation_m=terrain_datum,
                               max_frames=args.max_previews)
    total = sum(len(s) for s in schedules)
    print(f"captured: {total} frames across {len(cameras)} camera(s)")
    print(f"  manifest: {manifest_path}")
    print(f"  previews: {len(previews)} geometry preview(s) under "
          f"{out / 'previews'}")

    from core.util.platform import (
        os_name, ue_available, ue_platform_refusal, ue_runner_command,
    )

    if not args.render:
        if ue_available():
            print(f"UE render half present on this {os_name()} machine: add "
                  f"--render to produce the frames through these solved "
                  f"poses, one commandlet pass per camera.")
        else:
            print(ue_platform_refusal())
            print("(pixels only; the manifest and every verification check "
                  "that does not need them are complete here)")
        return 0

    if not ue_available():
        print(ue_platform_refusal())
        print("(--render asked for pixels; everything else in this run "
              "completed and is on disk)")
        return 0

    import subprocess

    frames_dir = out / "frames"
    command = ue_runner_command(REPO, "render_ue_scenario")
    command += [str(out / "card.json"), str(frames_dir)]
    print(f"rendering {len(cameras)} camera pass(es) into {frames_dir} ...")
    completed = subprocess.run(command)
    if completed.returncode != 0:
        print(f"REFUSED -- the render wrapper exited {completed.returncode}; "
              f"the manifest and verification above still stand")
        return 1
    rendered = sorted(frames_dir.rglob("frame_*.png"))
    print(f"  frames:   {len(rendered)} rendered under {frames_dir}")

    from core.capture.overlay import draw_overlays

    overlays = draw_overlays(manifest, out, max_frames=args.max_previews)
    print(f"  overlays: {len(overlays)} under {out / 'overlays'} -- the "
          f"recorded geometry drawn ON the rendered pixels; the circle "
          f"(manifest) and the cross (engine) should coincide")
    print(f"  verify:   python -m flightsim.verify {out}")
    print("  (with pixels present, verification exercises the landmark "
          "reprojection and two-view checks that report NOT RUN without "
          "them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
