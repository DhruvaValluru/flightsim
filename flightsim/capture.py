"""Capture a scenario: spec -> validate -> run -> solved geometry.

    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml \
        --out runs/demo [--terrain runs/terrain/matterhorn] [--max-previews N]

What happens, in order (each step refuses by name rather than
approximating):

1. the spec is read (spec_version 8 -- older versions refuse by name);
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
import contextlib
import json
import math
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.capture.objects import compose_objects  # noqa: E402
from core.util.platform import UE_ENGINE_VERSION  # noqa: E402

#: The lines the JSBSim library prints from C++ on every FGFDMExec
#: construction (three banner lines and, once, a "startup beginning"
#: line, each wrapped in blank lines). Measured: 12 banners on the
#: two-camera example before the spec line, burying "spec ... valid"
#: and the refusal a non-technical reader is looking for.
#: FGJSBBase.debug_lvl = 0 does not gate them (core/fdm/fdm.py), so
#: they are filtered at the file-descriptor level by
#: quiet_library_banners below; --verbose keeps them.
LIBRARY_BANNER_PREFIXES = (
    b"JSBSim Flight Dynamics Model",
    b"[JSBSim-ML",
    b"JSBSim startup beginning",
)


def _is_library_banner(line: bytes) -> bool:
    return line.strip().startswith(LIBRARY_BANNER_PREFIXES)


def _relay_without_banners(read_end: int, out_fd: int) -> None:
    """Copy every line from the pipe to the real stdout except the
    library banner lines and the blank lines that frame them. Blank
    lines are held until the next line says whether they framed a
    banner, so a program's own blank line still arrives."""
    pending_blank = 0
    after_banner = False
    tail = b""

    def emit(line: bytes) -> None:
        nonlocal pending_blank, after_banner
        if _is_library_banner(line):
            pending_blank = 0
            after_banner = True
            return
        if not line.strip():
            if not after_banner:
                pending_blank += 1
            return
        os.write(out_fd, b"\n" * pending_blank + line)
        pending_blank = 0
        after_banner = False

    try:
        while True:
            chunk = os.read(read_end, 65536)
            if not chunk:
                break
            tail += chunk
            while b"\n" in tail:
                line, tail = tail.split(b"\n", 1)
                emit(line + b"\n")
        if tail:
            emit(tail)
        if pending_blank and not after_banner:
            os.write(out_fd, b"\n" * pending_blank)
    finally:
        os.close(read_end)


@contextlib.contextmanager
def quiet_library_banners(enabled: bool = True):
    """Run a block with the JSBSim startup banners kept off stdout.

    The banners are written by C++ straight to file descriptor 1, so
    no Python-level redirection sees them: fd 1 is pointed at a pipe
    for the block, a thread relays the pipe to the real stdout and
    drops exactly the banner lines (LIBRARY_BANNER_PREFIXES), and fd 1
    is restored before the block's caller prints again. Everything
    else -- the spec line, the refusals, a subprocess's own words --
    arrives in order. With ``enabled`` false (--verbose) the block runs
    untouched; so does a process with no usable stdout.
    """
    if not enabled:
        yield
        return
    try:
        sys.stdout.flush()
        saved = os.dup(1)
    except (OSError, ValueError, AttributeError):
        yield
        return
    read_end, write_end = os.pipe()
    os.dup2(write_end, 1)
    os.close(write_end)
    relay = threading.Thread(target=_relay_without_banners,
                             args=(read_end, saved), daemon=True)
    relay.start()
    try:
        yield
    finally:
        try:
            sys.stdout.flush()
        finally:
            os.dup2(saved, 1)  # the pipe's last writer closes: the relay ends
            relay.join()
            os.close(saved)


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


def _mesh_manifest_path(spec) -> Path:
    """Where the imported model's manifest lives for this spec's aircraft
    (the web app resolves the same path for its -mesh= argument)."""
    return (REPO / "assets" / "generated" / str(spec.aircraft.value)
            / "mesh_manifest.json")


def _traffic_mesh_refusal(spec):
    """The ``aircraft.mesh`` refusal for the first traffic airframe whose
    model is not imported on this machine, or None. The web app's own
    words where its refusal applies (no config, no upstream licence);
    the build command where the model can be built."""
    from assets_pipeline.importer import (
        configured_aircraft, is_imported, unavailable_reason,
    )

    for index, entry in enumerate(spec.traffic):
        aircraft = str(entry.aircraft.value)
        if is_imported(aircraft):
            continue
        reason = unavailable_reason(aircraft)
        if reason:
            message = (f"traffic[{index}] names the {aircraft}, which has "
                       f"flight physics but can never render: {reason}")
        elif aircraft not in configured_aircraft():
            message = (f"traffic[{index}] names the {aircraft}, for which no "
                       f"licensed 3-D model is configured; placeholder "
                       f"airframes never render, for traffic as for the "
                       f"primary")
        else:
            message = (f"traffic[{index}] names the {aircraft}, whose model "
                       f"is not imported on this machine (no current "
                       f"assets/generated/{aircraft}/mesh_manifest.json backed "
                       f"by its ue/Content assets). Build it once with "
                       f"`python scripts/import_aircraft.py {aircraft}`; a "
                       f"scripted traffic actor is drawn from the same "
                       f"imported mesh as a primary would be")
        return {"constraint": "aircraft.mesh", "message": message}
    return None


def _after_name(exc: Exception) -> str:
    """The text of an error whose str() begins with its own rule name
    (``ScheduleError``: "camera.schedule: ..."), without that head, so
    a REFUSED line prints the name once."""
    text = str(exc)
    head = f"{getattr(exc, 'constraint', '')}: "
    return text[len(head):] if head != ": " and text.startswith(head) else text


def _refuse(violations) -> int:
    print("REFUSED -- by name:")
    for v in violations:
        print(f"  {v.render() if hasattr(v, 'render') else v}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="validate, run headlessly, and capture a scenario's "
                    "camera geometry")
    parser.add_argument("spec", help="scenario spec YAML (spec_version 8)")
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
                             "--terrain names a bake. Since spec 8 this "
                             "flag is an ALIAS for the spec's own "
                             "scene.terrain_source: synthesised, which "
                             "needs no flag.")
    parser.add_argument("--max-previews", type=int, default=8,
                        help="cap geometry preview images per run "
                             "(default 8; they are near-identical frame "
                             "to frame and each draws a full shaded "
                             "scene). 0 writes none.")
    parser.add_argument("--render", action="store_true",
                        help="also render the frames through the solved "
                             f"poses (Windows with UE {UE_ENGINE_VERSION} "
                             "and the bridge built; refuses by name "
                             "anywhere else). Implies --card.")
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
    parser.add_argument("--verbose", action="store_true",
                        help="keep the flight model's own startup lines "
                             "(the JSBSim banner it prints once per "
                             "flight model it builds) on the output. "
                             "Off by default so what this command says "
                             "-- the spec line, the results, a refusal "
                             "-- is not buried under them.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    with quiet_library_banners(enabled=not args.verbose):
        return _run(args)


def _run(args: argparse.Namespace) -> int:
    from core.capture.manifest import (
        build_capture_manifest, write_capture_manifest,
        write_frame_sidecars,
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
    from core.scenario.validate import Violation, validate

    try:
        spec = ScenarioSpec.read(args.spec)
    except ValueError as exc:
        # A file that is not a spec (unreadable YAML, a missing field,
        # a version this build does not read): named, so the catalogue
        # can put it into words like every other refusal.
        print(f"REFUSED -- spec.read: {exc}")
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
        from core.util.platform import ue_available
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

        # The MESH the frames will draw, checked here for the same reason
        # the projection is: before any flight. The web app has passed
        # -mesh= since the placeholder rule; this command never did, so a
        # CLI --render drew the placeholder boxes -- forbidden on any
        # machine (owner's rule 2026-08-31) -- under a manifest whose
        # assets block named the real mesh. Imported (a CURRENT manifest
        # AND its .uassets) -> the render pass gets -mesh=; otherwise
        # REFUSE by name, with the web app's own words where its refusal
        # applies (no config, no upstream license) and the build command
        # where the model can be built. Only where the engine is: off
        # Windows/Mac the render is refused later as ue.platform and the
        # manifest is the deliverable, exactly as before.
        if ue_available():
            from assets_pipeline.importer import is_imported
            from webapp.runs import refuse_placeholder_mesh

            aircraft = str(spec.aircraft.value)
            mesh_manifest = _mesh_manifest_path(spec)
            if not is_imported(aircraft):
                refusal = refuse_placeholder_mesh(spec)
                if refusal is None:
                    refusal = {
                        "constraint": "aircraft.mesh",
                        "message": (
                            f"the {aircraft} model is not imported on this "
                            f"machine (no current "
                            f"{mesh_manifest.relative_to(REPO)} backed by "
                            f"its ue/Content assets), and placeholder "
                            f"airframes never render. Build it once with "
                            f"`python scripts/import_aircraft.py "
                            f"{aircraft}` (fetch at the pinned commit, "
                            f"convert, import into the Unreal project), or "
                            f"render through the web app, which provisions "
                            f"it itself; a manifest older than version 2 "
                            f"(no mesh origin -- the mesh would be drawn at "
                            f"the structural datum, 25-30 m off its label) "
                            f"re-converts with `python "
                            f"assets_pipeline/convert.py "
                            f"assets/aircraft_config/{aircraft}.json`"),
                    }
                print(f"REFUSED -- {refusal['constraint']}: "
                      f"{refusal['message']}")
                print("(--render asked for pixels of a model this machine "
                      "does not have; refused before any flight, so "
                      "nothing was run or rendered)")
                return 2
            # Phase 2 (package B, contracts §2.2): every TRAFFIC airframe
            # is held to the same rule as the primary -- its mesh must be
            # imported on this machine or the render refuses aircraft.mesh
            # by name before any flight. A scripted actor drawn as boxes
            # under a label that names a type is the same lie.
            traffic_refusal = _traffic_mesh_refusal(spec)
            if traffic_refusal is not None:
                print(f"REFUSED -- {traffic_refusal['constraint']}: "
                      f"{traffic_refusal['message']}")
                print("(--render asked for pixels of a traffic model this "
                      "machine does not have; refused before any flight)")
                return 2

    heightfield = None
    terrain_ground = None
    terrain_stem = args.terrain
    # Spec 8: the spec's own scene.terrain_source names the terrain, so
    # a committed example refuses (or flies) AS ITS HEADER SAYS with no
    # flag. "auto" is exactly the flag behaviour this block always had;
    # the flags stay as aliases. A flag that CONTRADICTS a stated source
    # refuses by name (scene.terrain) rather than dropping either in
    # silence. Whether the value is one of the four is validate()'s
    # question (scene.terrain_source); here an unknown value falls
    # through to validation below, which refuses it.
    terrain_source = str(spec.scene.terrain_source.value)
    if terrain_source == "flat":
        if terrain_stem is not None or args.synth_terrain:
            return _refuse([Violation(
                "scene.terrain",
                "the spec states scene.terrain_source: flat, but "
                + ("--terrain names a bake" if terrain_stem is not None
                   else "--synth-terrain asks for a raster")
                + "; edit the spec or drop the flag -- neither is "
                  "dropped in silence")])
        print("terrain: flat at the spec's datum (scene.terrain_source: "
              "flat)")
    elif terrain_source == "baked":
        stated = spec.scene.terrain.value
        if terrain_stem is None and stated:
            terrain_stem = str(stated)
        if terrain_stem is None:
            return _refuse([Violation(
                "scene.terrain",
                "scene.terrain_source is baked but no bake is named: "
                "state scene.terrain (a <stem>.r16 + .json bake) or pass "
                "--terrain <stem>")])
        stem = Path(terrain_stem)
        if not (stem.with_suffix(".r16").is_file()
                and stem.with_suffix(".json").is_file()):
            return _refuse([Violation(
                "scene.terrain",
                f"scene.terrain_source is baked but {terrain_stem} is not "
                f"a whole bake on this machine (<stem>.r16 + .json; "
                f"scripts/bake_terrain.py fetches a curated one)")])
    elif terrain_source == "synthesised" and terrain_stem is not None:
        return _refuse([Violation(
            "scene.terrain",
            "the spec states scene.terrain_source: synthesised, but "
            "--terrain names a bake; edit the spec or drop the flag")])
    if terrain_stem is None and (args.synth_terrain
                                 or terrain_source == "synthesised"):
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
              f"network; scene.terrain_source: {terrain_source}"
              f"{' + --synth-terrain' if args.synth_terrain else ''})")
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
    # Phase 10: the randomisation block draws its values here too (the
    # web planners are not on this path); off by default -> no-op. A
    # window with no daylight refuses by name before any flight.
    from core.scenario.randomization import (
        RandomizationError, card_block as randomization_card_block,
        render_look, sample_randomization,
    )

    try:
        sample_randomization(spec)
    except RandomizationError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 2
    if spec.randomization.is_enabled():
        block = spec.randomization
        print(f"randomization: seed {int(block.seed.value)}, sun "
              f"{float(block.sun_elevation_deg.value):.1f} deg elevation / "
              f"{float(block.sun_azimuth_deg.value):.1f} deg azimuth, fog "
              f"{float(block.fog_density.value):g} 1/m, livery "
              f"{block.livery.value}")
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
    from core.control.autopilot import ClosureError
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
    except ClosureError as exc:
        # The held state was not reached (a 747 asked to hold altitude
        # in severe turbulence, measured): the runner's own refusal to
        # emit output, named, with its closure table -- not a traceback.
        print(f"REFUSED -- run.closure: {exc}")
        print("(the commanded state was not achieved within the declared "
              "tolerances, so no run was recorded; state hold_state: "
              "false for the open-loop flight, or ease the conditions)")
        return 2
    columns = result.telemetry.columns

    cameras = spec.cameras or default_cameras(spec)
    if not spec.cameras:
        print("no camera stated: capturing with the documented default "
              "camera (the chase view)")
    terrain_datum = float(spec.terrain_elevation.value)

    from core.capture.poses import solve_traffic_track

    traffic_objects = [o for o in compose_objects(spec) if o.role == "traffic"]

    def solve_traffic(flight):
        """The scripted traffic tracks over one recorded flight (Phase
        2, package B): solved beside the cameras, from the same
        telemetry, so the second aircraft's keyframes and the labels
        that describe it come out of one flight."""
        return [solve_traffic_track(flight, str(entry.track.value),
                                    float(entry.range_m.value), frame, obj.id)
                for entry, obj in zip(spec.traffic, traffic_objects)]

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
        traffic_tracks = solve_traffic(columns)
    except ScheduleError as exc:
        # The name once, at the head: str(exc) already begins with it.
        print(f"REFUSED -- {exc.constraint}: {_after_name(exc)}")
        return 2
    if solved_violations:
        return _refuse(solved_violations)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from core.capture.manifest import SOLVE_HOST_FLIGHT, SOLVE_PRE_RUN
    from core.util.platform import (
        os_name, ue_available, ue_platform_refusal, ue_runner_command,
    )

    def write_card(path, tracks, schedules, landmarks, traffic_tracks=()):
        """The card the hosts read: spec fields + solved pose tracks,
        the labelled objects and the scripted traffic tracks."""
        from core.capture.airframe import load_airframe
        from core.capture.objects import (
            mesh_manifest_path, objects_block, taxonomy_classes,
        )
        from core.capture.poses import traffic_card_block
        from core.scenario.card import write_run_card

        objects = compose_objects(spec)
        traffic_objs = [o for o in objects if o.role == "traffic"]
        traffic_blocks = []
        for entry, obj, track in zip(spec.traffic, traffic_objs, traffic_tracks):
            name = str(entry.aircraft.value)
            mesh = mesh_manifest_path(name)
            traffic_blocks.append(traffic_card_block(
                track, entry, obj, frame,
                load_airframe(name).cg_structural_in,
                str(mesh) if mesh.is_file() else None))
        return write_run_card(
            spec, path,
            cameras=[track.card_block(camera, schedule, frame)
                     for camera, track, schedule
                     in zip(cameras, tracks, schedules)],
            landmarks=landmarks,
            scene_crs=frame.crs if frame.declared else None,
            randomization=randomization_card_block(spec),
            objects=objects_block(objects),
            taxonomy=taxonomy_classes(spec),
            traffic=traffic_blocks)

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
            read_all_host_columns, read_host_record,
        )

        host_dir = out / "host_flight"
        host_dir.mkdir(parents=True, exist_ok=True)
        # The card the SOLVE pass flies. It carries the pre-run's tracks;
        # the scenario commandlet ignores the cameras block entirely (it
        # renders nothing), and the card that the render passes consume
        # is rewritten below from the re-solved tracks.
        # No landmarks: this pass renders nothing and projects
        # nothing, so it has no use for them.
        write_card(host_dir / "card.json", tracks, schedules, None,
                   traffic_tracks)
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
                  f"no flight; nothing was rendered. The wrapper printed "
                  f"its last words above and kept them in "
                  f"{host_telemetry.with_suffix('.log')}. Re-run with "
                  f"--no-host-flight to solve over the pre-run instead, "
                  f"knowing the labels will then describe a different "
                  f"flight from the one the pixels show")
            return 1
        try:
            # The whole record: every frame's ``state`` is cut from it.
            host_columns = read_host_record(host_telemetry)
            tracks, schedules, solved_violations = solve_over(host_columns)
            traffic_tracks = solve_traffic(host_columns)
        except HostFlightError as exc:
            print(f"REFUSED -- {exc.constraint}: {exc.message}")
            return 2
        except ScheduleError as exc:
            # The name once, at the head: str(exc) already begins with it.
            print(f"REFUSED -- {exc.constraint}: {_after_name(exc)}")
            return 2
        # The host's flight is a different flight, so the scene checks
        # run again over it. A camera that cleared the ridge on the
        # pre-run and does not on the host's own track must refuse --
        # this is the flight the frames would be taken on.
        if solved_violations:
            return _refuse(solved_violations)
        columns = host_columns
        solve_source = SOLVE_HOST_FLIGHT
        # Over EVERY column the host recorded, so output_digest means
        # the same thing whichever flight the manifest describes.
        solve_digest = digest_columns(read_all_host_columns(host_telemetry))
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
        heightfield=heightfield, terrain_elevation_m=terrain_datum,
        # Phase 2 (package B): the scripted traffic's solved tracks, so
        # every frame carries a label record for the second aircraft.
        traffic_tracks=traffic_tracks)
    manifest_path = write_capture_manifest(manifest, out)
    write_frame_sidecars(manifest, out)
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
                   manifest.get("landmarks"), traffic_tracks)
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
    from core.render.flags import (
        DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_WIDTH, for_wrapper, render_flags,
    )

    command = ue_runner_command(REPO, "render_ue_scenario")
    command += [str(out / "card.json"), str(frames_dir)]
    # Phase 2 (package A, contracts §9): the flags come from the ONE
    # builder the web app also uses, so the two render paths cannot
    # disagree by one of them forgetting a flag (measured: this command
    # never passed -mesh= until the placeholder rule, and neither path
    # passed -deterministic). The wrapper adds -scenario= -frames= per
    # run and -camera-index=N -telemetry= per camera pass, plus the
    # launcher tokens; for_wrapper() strips exactly those.
    #
    # The scene the frames are taken in. Gate 5's tier is a black void
    # -- deliberately, because its silhouette measurements need one --
    # and the camera phase inherited it by never asking for anything
    # else. The result was a grey airframe on black: no sky, no
    # horizon, no ground. -Visual builds the real scene (sun, sky,
    # atmosphere, fog, and terrain when a bake is present), and the
    # aircraft is then IN something. --void keeps the old tier for
    # anyone measuring silhouettes (no -Visual, no terrain, no look).
    #
    # The look: the sampled one when the randomisation block is on;
    # off, the builder's DEFAULT_LOOK (the harness's noon, the web
    # app's default since the showcase matrix). Before the builder this
    # command passed NO look when the block was off and the commandlet's
    # own defaults lit the frames (no sun override, fog 0.0025, bias
    # 11.0); one builder means one default, and the web app's is the
    # one pinned by test. render.json records the sun either way.
    #
    # -labels: the engine half of the labels beside every frame of
    # every camera pass (Phase 10). -deterministic: the texture/LOD
    # pins Gate 10-R proves the frame digests need. -mesh=: the
    # imported model checked above; the commandlet refuses a mesh/FDM
    # mismatch itself. The size and rate flags are the legacy path's;
    # every card this command writes carries cameras, so the commandlet
    # takes the size from the card's own camera and they are inert
    # (core/render/flags.py says what is and is not claimed).
    command += for_wrapper(render_flags(
        out / "card.json", frames_dir,
        scene={"terrain": terrain_stem},
        mesh=_mesh_manifest_path(spec),
        look=render_look(spec), camera_flags=None,
        labels=True, deterministic=True, void=bool(args.void),
        width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS))
    print(f"rendering {len(cameras)} camera pass(es) into {frames_dir} "
          f"{'in the black void (--void)' if args.void else 'in the visual scene'} ...")
    completed = subprocess.run(command)
    if completed.returncode != 0:
        # The renderer drew no pictures: the catalogue's camera.render.
        print(f"REFUSED -- camera.render: the render wrapper exited "
              f"{completed.returncode} and drew no pictures; the manifest "
              f"and verification above still stand")
        return 1
    rendered = sorted(p for p in frames_dir.rglob("frame_*.png")
                      if p.stem[-4:].isdigit())
    print(f"  frames:   {len(rendered)} rendered under {frames_dir}")

    # Phase 2 (package C): complete every frame's per-object records
    # from the bundle the engine just wrote -- the tight box from the
    # ID image, the visible fraction from the alone pass, occluded_by,
    # the depth under the mask -- and write the manifest and sidecars
    # back. A frame with no bundle keeps its nulls and says why.
    from core.capture.labels import attach_engine_labels

    attached = attach_engine_labels(out)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"  labels:   engine bundle attached on {attached['attached']} of "
          f"{attached['frames']} frames ({attached['objects']} object "
          f"records; {attached['without_bundle']} without a bundle)")

    # Phase 10: the sensor model as a seeded post-pass, for every camera
    # whose profile is not the ideal pinhole.
    from core.capture.profile import apply_profile_to_run

    sensor_written = apply_profile_to_run(out, manifest, int(spec.seed.value))
    if sensor_written:
        print("  sensor:   " + ", ".join(f"{cam} x{n} sensor frames"
                                        for cam, n in sorted(sensor_written.items())))

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
