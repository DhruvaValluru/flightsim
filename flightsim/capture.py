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
   run -- steps 4-6 are the cheap pre-flight gate, so a camera inside
   a mountain refuses before any engine time is spent;
7. with --render, THE HOST FLIES THE CARD FIRST (the telemetry-only
   commandlet, no renderer) and steps 5-6 run again over the host's
   own telemetry. The labels then describe the flight the pixels will
   show rather than a second, very similar one -- see
   core.capture.hostflight. --no-host-flight keeps the old behaviour
   deliberately;
8. capture_manifest.json (carrying solve_source, which says WHICH of
   those flights the aircraft labels came from), telemetry.json,
   scenario.yaml and one geometry preview per scheduled frame;
9. on a machine with the UE render half, pixels render beside them,
   one commandlet pass per camera; anywhere else rendering REFUSES BY
   NAME (ue.platform) while steps 1-8 stand -- the manifest and
   previews are the engine-less deliverable.

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
    parser.add_argument("--void", action="store_true",
                        help="render in the black-void scene instead of "
                             "the visual one: no sky, no horizon, no "
                             "terrain, just the lit airframe. What the "
                             "silhouette measurements want, and nothing "
                             "else")
    parser.add_argument("--no-host-flight", action="store_true",
                        help="with --render, skip the host's own solve "
                             "flight and solve the poses over the "
                             "headless pre-run instead. Faster by one "
                             "commandlet pass, and the aircraft labels "
                             "then describe a DIFFERENT flight from the "
                             "one the pixels show (1.38 m measured). "
                             "Only for when you want the old behaviour "
                             "deliberately.")
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
    terrain_datum = float(spec.terrain_elevation.value)

    def solve_over(flight):
        """Pose tracks, schedules and their scene violations over one
        recorded flight. Runs twice when the host flies its own: once
        over the headless pre-run as the cheap pre-flight gate, once
        over the host's telemetry for the labels that ship."""
        tracks, schedules = [], []
        for camera in cameras:
            tracks.append(solve_pose_track(flight, camera, frame))
            schedules.append(solve_schedule(flight, camera, frame))
        violations = []
        for track in tracks:
            violations.extend(track_violations(
                track, heightfield=heightfield, scene_frame=frame,
                tornado=tornado, terrain_elevation_m=terrain_datum))
        return tracks, schedules, violations

    try:
        tracks, schedules, solved_violations = solve_over(columns)
    except ScheduleError as exc:
        print(f"REFUSED -- {exc}")
        return 2
    if solved_violations:
        return _refuse(solved_violations)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from core.capture.manifest import SOLVE_HOST_FLIGHT, SOLVE_PRE_RUN
    from core.util.platform import (
        os_name, ue_available, ue_platform_refusal, ue_runner_command,
    )

    def write_card(path, tracks, schedules, landmarks):
        """The card the hosts read: spec fields + solved pose tracks."""
        from core.scenario.card import write_run_card

        return write_run_card(
            spec, path,
            cameras=[track.card_block(camera, schedule, frame)
                     for camera, track, schedule
                     in zip(cameras, tracks, schedules)],
            landmarks=landmarks,
            scene_crs=frame.crs if frame.declared else None)

    solve_source = SOLVE_PRE_RUN
    solve_digest = result.output_digest

    # ------------------------------------------------------------------
    # ONE FLIGHT, NOT TWO.
    #
    # Everything above solved the poses over the HEADLESS pre-run -- the
    # jsbsim Python package. The host then flies the same card through
    # UE's vendored JSBSim, and two builds stepping one scenario do not
    # agree: 1.38 m worst, measured. The camera poses survive that (the
    # host consumes them verbatim) but the AIRCRAFT state in every frame
    # record described the pre-run while the pixels showed the host's
    # flight, which for labelled data is the defect that matters.
    #
    # So when there are pixels to take, the host flies FIRST -- the
    # telemetry-only commandlet, no renderer -- and everything is solved
    # again over ITS telemetry. The render passes then re-fly the same
    # card and, because the host is bit-deterministic, fly the identical
    # flight. Manifest and pixels describe one flight by construction.
    #
    # The pre-run is not wasted and is not skipped: it stays the cheap
    # pre-flight gate, so a camera inside a mountain still refuses
    # BEFORE a UE pass is spent rather than after one.
    # ------------------------------------------------------------------
    host_flight = args.render and not args.no_host_flight and ue_available()
    if host_flight:
        import subprocess

        from core.capture.hostflight import (
            HostFlightError, digest_columns, host_telemetry_path,
            read_host_columns,
        )

        host_dir = out / "host_flight"
        host_dir.mkdir(parents=True, exist_ok=True)
        # The card the SOLVE pass flies. It carries the pre-run's tracks;
        # the scenario commandlet ignores the cameras block entirely (it
        # renders nothing), and the card that the render passes consume
        # is rewritten below from the re-solved tracks.
        # No landmarks: this pass renders nothing and projects
        # nothing, so it has no use for them.
        write_card(host_dir / "card.json", tracks, schedules, None)
        host_telemetry = host_telemetry_path(out)
        command = ue_runner_command(REPO, "run_ue_scenario")
        command += [str(host_dir / "card.json"), str(host_telemetry)]
        # Physics-affecting flags only. -Visual builds the RENDER scene
        # and this pass has no renderer; the terrain is what the ground
        # callback reads, so it has to match what the render passes fly
        # over or the two flights differ for a reason that is not the
        # host's determinism. verify_host_determinism is precisely the
        # check that grades this choice: if it ever FAILs on a run whose
        # passes differ only in -Visual, then -Visual perturbs the
        # flight and this pass has to carry it too.
        if terrain_stem:
            command.append(f"-terrain={terrain_stem}")
            command.append("-GeorefTerrain")
        print("flying the card in the host first, so the labels "
              "describe the flight the pixels show ...")
        completed = subprocess.run(command)
        if completed.returncode != 0:
            print(f"REFUSED -- capture.host_flight: the scenario "
                  f"commandlet exited {completed.returncode} and recorded "
                  f"no flight; nothing was rendered. Re-run with "
                  f"--no-host-flight to solve over the pre-run instead, "
                  f"knowing the labels will describe a different flight")
            return 1
        try:
            host_columns = read_host_columns(host_telemetry)
            tracks, schedules, solved_violations = solve_over(host_columns)
        except HostFlightError as exc:
            print(f"REFUSED -- {exc.render()}")
            return 2
        except ScheduleError as exc:
            print(f"REFUSED -- {exc}")
            return 2
        # The host's flight is a different flight, so the scene checks
        # run again over it. A camera that cleared the ridge on the
        # pre-run and does not on the host's own track must refuse --
        # this is the flight the frames would be taken on.
        if solved_violations:
            return _refuse(solved_violations)
        columns = host_columns
        solve_source = SOLVE_HOST_FLIGHT
        solve_digest = digest_columns(host_columns)
        print(f"  host flight: {len(host_columns['t'])} samples, digest "
              f"{solve_digest[:16]} -- poses re-solved over it")

    manifest = build_capture_manifest(
        spec, columns, frame, tracks, schedules,
        output_digest=solve_digest,
        solve_source=solve_source,
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
        # The HEADLESS pre-run's, always -- run.json describes the
        # flight run_spec flew. When the host flew its own and the
        # manifest was solved over that, the manifest's output_digest
        # is the host's and these two differ ON PURPOSE, which is the
        # visible trace of P10's real size.
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "solve_source": solve_source,
        "solve_digest": solve_digest,
    }, indent=1), encoding="utf-8")

    if args.card or args.render:
        # The run-card projection with the cameras block: spec fields +
        # solved pose tracks, computed HERE, consumed verbatim by the
        # commandlet's consume-poses mode. The commandlet's own named
        # refusals still govern anything it cannot honour (hold_state,
        # airspeed_kind, a track that does not cover the run).
        #
        # After a host flight these are the RE-SOLVED tracks, so the
        # card the render passes consume and the manifest that labels
        # their output came out of one flight.
        write_card(out / "card.json", tracks, schedules,
                   manifest.get("landmarks"))
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
    # The scene the frames are taken in. Gate 5's tier is a black void
    # -- deliberately, because its silhouette measurements need one --
    # and the camera phase inherited it by never asking for anything
    # else. The result was a grey airframe on black: no sky, no
    # horizon, no ground. Correct geometry, and not a picture of a
    # camera view, which is the whole complaint the phase exists to
    # answer. -Visual builds the real scene (sun, sky, atmosphere, fog,
    # and terrain when a bake is present), and the aircraft is then IN
    # something. --void keeps the old tier for anyone measuring
    # silhouettes.
    if not args.void:
        command.append("-Visual")
        if terrain_stem:
            command.append(f"-terrain={terrain_stem}")
            command.append("-GeorefTerrain")
    print(f"rendering {len(cameras)} camera pass(es) into {frames_dir} "
          f"{'in the black void (--void)' if args.void else 'in the visual scene'} ...")
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
