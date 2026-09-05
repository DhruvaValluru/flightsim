"""Capture a scenario: spec -> validate -> run -> solved geometry -> frames.

    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml \
        --out runs/demo [--render frames|clip|none] \
        [--terrain runs/terrain/matterhorn] [--max-previews N] \
        [--preview-scale N]

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
7. capture_manifest.json, telemetry.json, scenario.yaml, run.json (the
   digests and the render choice: word, label, the engine's
   availability and reason on this machine) and one geometry preview
   per scheduled frame are written, and the SAME verifier the
   instructor runs (flightsim.verify) grades what was just written --
   its table is printed in every mode and written as verify.json beside
   the manifest (the JSON the webapp serves), engine parity AWAITING
   until frames exist, and a manifest that fails its own verification
   FAILS the run by name (capture.verification, exit 1). Previews draw
   at the record's full resolution unless --preview-scale N asks for
   1/N; their measured render time per frame, the scale, the resolution
   and the per-camera contact sheets are recorded in run.json
   ("previews") and printed;
8. the render choice, the SAME three words the web page offers
   (--render, default: the richest this machine supports):

   * ``frames`` -- card.json carries every camera's solved pose track
     and capture instants; the render commandlet's consume-poses pass
     runs ONCE PER CAMERA (-camera-index=N, -frames=<out>/frames/<id>)
     through the same command builder the webapp uses, captures only
     at the scheduled instants and names each PNG by its manifest
     index; a short pass FAILS by name (render.frames); every rendered
     frame gets an OVERLAY (overlays/<camera_id>/NNNN.png: the
     reprojected aircraft body and box, terrain wireframe or ground
     grid, horizon and header drawn over the PNG, so the verification
     is visible to the eye); the verifier's engine-parity check then
     grades applied vs solved per frame; the clip is a by-product of
     camera 0's frames at their instants;
   * ``clip`` -- one preset pass and an fps clip, the manifest and
     previews beside it, nothing rendered as frames;
   * ``none`` -- steps 1-7 only. On a machine without the engine this
     is the only choice: the run states the engine's absence by reason
     ("engine absent: ...; frames not rendered") and is DONE, exit 0 --
     asking for frames or clip there REFUSES BY NAME (ue.platform) with
     the machine's reason, and REFUSED is exit 2's word only.

What is printed (flightsim.report, the surface flightsim.verify shares):
the header (digests, scene, flight, one line per camera), one line
naming where JSBSim's own console went (<out>/jsbsim.log, with the
number of model loads routed there -- never on stdout, never lost),
the per-camera table of scheduled instants (--brief collapses a uniform
schedule to one line), the previews, the verification table with each
check's measured value, tolerance, status and WHERE, and a verdict line
whose first word is the exit code's word. --json prints the same
document as data.

Exit codes (one table with flightsim.verify): 0 done (the verdict line
starts "done:"); 1 FAILED -- the verifier failed the artefact ("FAILED
capture.verification:", or a frames run whose rendered frames fail
engine parity); 2 REFUSED -- a named constraint refused ("REFUSED
<constraint>"), or the engine pass did not honour its contract ("FAILED
render.frames:" / "FAILED render.clip:", the frames written are not a
frame set); 3 USAGE; 4 UNEXPECTED (traceback on stderr).
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

from core.capture.render_pass import (  # noqa: E402
    HOST_PARITY_CONSTRAINT, LAST_FRAME_HOLD_S, RENDER_CHOICES,
    RENDER_FRAMES_CONSTRAINT, RENDER_WORDS, check_render_pass,
    encode_scheduled_clip, frames_host_parity_refusal, pass_stepping,
    render_choice_default, render_command, rendered_count, run_render_pass,
    scheduled_clip_seconds, stepping_words,
)
from core.fdm.console import jsbsim_console  # noqa: E402
from flightsim.report import (  # noqa: E402
    EXIT_DONE, EXIT_FAILED, EXIT_REFUSED, ReportParser, add_common_arguments,
    header, run_command, schedule_tables,
)


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


def _refuse(violations, doc: dict, console=None) -> int:
    """The named refusal: every violation on its own line, the JSBSim
    log named, and a verdict line that starts with REFUSED and lists
    the constraints (exit 2)."""
    names = []
    print("REFUSED -- by name:")
    for v in violations:
        print(f"  {v.render() if hasattr(v, 'render') else v}")
        names.append(getattr(v, "constraint", None) or str(v).split(":")[0])
    doc["refusals"] = [
        {"constraint": getattr(v, "constraint", None),
         "message": getattr(v, "message", str(v)),
         "actual": getattr(v, "actual", None),
         "limit": getattr(v, "limit", None),
         "unit": getattr(v, "unit", None)} for v in violations]
    _jsbsim_words(doc, console)
    print(f"REFUSED [{', '.join(names)}]: nothing produced (the run "
          f"directory holds jsbsim.log only)")
    return EXIT_REFUSED


def _jsbsim_words(doc: dict, console) -> None:
    """One line naming where JSBSim's console went and how many model
    constructions were routed there -- the number the sink counted."""
    if console is None:
        return
    doc["jsbsim"] = {"log": str(console.path),
                     "model_loads": int(console.loads)}
    print(f"JSBSim output: {console.path} ({console.loads} model loads; "
          f"nothing of JSBSim's on stdout)")


def build_parser() -> ReportParser:
    parser = ReportParser(
        prog="python -m flightsim.capture",
        description="validate, run headlessly, and capture a scenario's "
                    "camera geometry")
    parser.add_argument("spec", help="scenario spec YAML (spec_version 6)")
    parser.add_argument("--out", required=True, help="run directory")
    parser.add_argument("--terrain", default=None,
                        help="baked heightfield stem (<stem>.r16 + .json) "
                             "for real-raster physics and camera checks")
    parser.add_argument("--max-previews", type=int, default=None,
                        help="cap preview images per run (default: one "
                             "per scheduled frame)")
    parser.add_argument("--preview-scale", type=int, default=1,
                        metavar="N",
                        help="draw previews at 1/N of the record's "
                             "resolution (default 1: full resolution; "
                             "a non-positive N, or one that does not "
                             "divide a camera's resolution exactly, "
                             "refuses by name before the flight)")
    parser.add_argument("--card", action="store_true",
                        help="also write card.json carrying each camera's "
                             "solved pose track (always written by "
                             "--render frames), for the UE commandlet's "
                             "consume-poses mode (-camera-index=N, one "
                             "pass per camera)")
    parser.add_argument("--render", choices=RENDER_CHOICES, default=None,
                        help="what to produce: frames (engine, one "
                             "consume-poses pass per camera, clip as a "
                             "by-product), clip (one preset pass), none "
                             "(headless: manifest, previews, "
                             "verification). Default: the richest this "
                             "machine supports")
    add_common_arguments(parser)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse, run, and finish the report (flightsim.report.run_command:
    the verdict word, --json, usage exit 3, unexpected exit 4)."""
    return run_command(_capture, build_parser(), argv, success_word="done")


def _capture(args, doc: dict) -> int:
    render = args.render or render_choice_default()
    from core.capture.preview import validated_scale

    try:
        preview_scale = validated_scale(args.preview_scale)
    except ValueError as exc:
        # Refused before any flight: a scale the preview cannot draw at
        # exactly is never rounded to one it can.
        print(f"REFUSED -- {exc}")
        return EXIT_REFUSED

    from core.util.platform import (
        UE_PLATFORM_REFUSAL, ue_available, ue_unavailable_reason,
    )

    # The choice is checked BEFORE any editor time or headless flight: an
    # engine choice this machine cannot honour is refused by name here,
    # never degraded to the headless run.
    if render != "none" and not ue_available():
        print(UE_PLATFORM_REFUSAL)
        print(f"  --render {render} ({RENDER_WORDS[render]}) needs the "
              f"engine: {ue_unavailable_reason()}")
        print("  --render none runs the headless half on this machine")
        doc["refusals"] = [{"constraint": "ue.platform",
                            "message": ue_unavailable_reason()}]
        print(f"REFUSED [ue.platform]: --render {render} on a machine "
              f"without the engine; nothing produced")
        return EXIT_REFUSED

    # The run directory exists from here on: JSBSim's console (the
    # startup banner every model construction prints from C++) is routed
    # to <out>/jsbsim.log for the whole run -- validation, trim, the
    # flight, the card -- and counted, so the report is readable and
    # nothing is lost.
    out = Path(args.out)
    doc["artefacts"] = {"run_dir": str(out),
                        "jsbsim_log": str(out / "jsbsim.log")}
    # The directory appears with the first model load (the sink creates
    # it): a run refused before any FDM exists leaves nothing behind.
    with jsbsim_console(out / "jsbsim.log") as console:
        return _capture_in(args, doc, out, render, preview_scale, console)


def _capture_in(args, doc: dict, out: Path, render: str, preview_scale: int,
                console) -> int:
    from core.capture.manifest import (
        build_capture_manifest, write_capture_manifest,
    )
    from core.capture.poses import (
        SceneFrame, camera_card_blocks, solve_pose_track,
    )
    from core.util.platform import ue_available, ue_unavailable_reason
    from core.capture.preview import render_overlays, render_previews
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
        doc["refusals"] = [{"constraint": "spec", "message": str(exc)}]
        return EXIT_REFUSED

    # A preview scale the cameras' resolution cannot be drawn at exactly
    # (3 on 1280x720) is refused by name BEFORE the flight -- before any
    # model is even loaded -- never floored.
    from core.capture.preview import scale_refusal_for_cameras

    scale_refusal = scale_refusal_for_cameras(
        preview_scale, spec.cameras or default_cameras(spec))
    if scale_refusal is not None:
        print(f"REFUSED -- {scale_refusal}")
        return 2

    heightfield = None
    terrain_ground = None
    if args.terrain:
        from core.terrain.ground import TerrainGround
        from core.terrain.heightfield import Heightfield

        heightfield = Heightfield.read(Path(args.terrain))
        terrain_ground = TerrainGround(heightfield)

    frame = SceneFrame.for_spec(spec, heightfield)
    tornado = _tornado_hazard_block(spec)

    report = validate(spec)
    if not report.ok:
        return _refuse(report.violations, doc, console)
    static = static_camera_violations(
        spec, heightfield, frame, tornado,
        )
    if static:
        return _refuse(static, doc, console)
    # A frames pass whose labels could not match its pixels: host parity
    # is measured and refused for turbulence (docs/VALIDITY.md), so the
    # choice is refused by name here, before the flight -- never rendered
    # and then failed by the verifier.
    if render == "frames":
        parity = frames_host_parity_refusal(spec)
        if parity is not None:
            print(f"REFUSED {HOST_PARITY_CONSTRAINT}: {parity}")
            doc["refusals"] = [{"constraint": HOST_PARITY_CONSTRAINT,
                                "message": str(parity)}]
            return EXIT_REFUSED

    print(f"spec {spec.digest()[:16]} valid; running headlessly...")
    result = run_spec(spec, terrain_ground=terrain_ground)
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
            schedules.append(solve_schedule(
                columns, camera, frame, rate_hz=float(spec.rate.value)))
    except ScheduleError as exc:
        print(f"REFUSED -- {exc}")
        doc["refusals"] = [{"constraint": "camera.schedule",
                            "message": str(exc)}]
        return EXIT_REFUSED

    terrain_datum = float(spec.terrain_elevation.value)
    solved_violations = []
    for track in tracks:
        solved_violations.extend(track_violations(
            track, heightfield=heightfield, scene_frame=frame,
            tornado=tornado, terrain_elevation_m=terrain_datum))
    if solved_violations:
        return _refuse(solved_violations, doc, console)

    manifest = build_capture_manifest(
        spec, columns, frame, tracks, schedules,
        output_digest=result.output_digest,
        scene={"key": "terrain" if heightfield else "flat",
               "terrain": args.terrain},
        terrain_sha256=heightfield.digest() if heightfield else None,
        # The cameras that actually flew (default_cameras for a
        # camera-less spec); the digests stay the spec's own.
        cameras=cameras,
        # The airframe's extents, read once from the FDM by the runner.
        aircraft_metrics=result.manifest.get("aircraft_metrics"))
    manifest_path = write_capture_manifest(manifest, out)
    result.telemetry.write_json(out / "telemetry.json")
    spec.write(out / "scenario.yaml")
    # The run's own record: its digests AND the render choice, in the
    # word and the label the page uses, with the engine's availability
    # and reason as this machine stated them -- the same provenance the
    # webapp writes (provenance.json "render"), on the CLI's surface.
    (out / "run.json").write_text(json.dumps({
        "spec_digest": result.spec_digest,
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "render": {"choice": render, "label": RENDER_WORDS[render],
                   "engine_available": bool(ue_available()),
                   "engine_unavailable_reason": ue_unavailable_reason()},
        "jsbsim_log": str(out / "jsbsim.log"),
    }, indent=1), encoding="utf-8")

    # The header: digests, scene, flight, one line per camera -- the
    # same block flightsim.verify prints from the manifest alone.
    head_lines, head_data = header(
        manifest, out, aircraft=str(spec.aircraft.value),
        duration_s=float(spec.duration.value), samples=len(result.telemetry))
    for line in head_lines:
        print(line)
    doc["header"] = head_data
    doc["render"] = {"choice": render, "label": RENDER_WORDS[render],
                     "engine_available": bool(ue_available()),
                     "engine_unavailable_reason": ue_unavailable_reason()}

    card_path = None
    if args.card or render == "frames":
        # The run-card projection with the cameras block: spec fields +
        # solved pose tracks, computed HERE, consumed verbatim by the
        # commandlet's consume-poses mode. The commandlet's own named
        # refusals still govern anything it cannot honour (hold_state,
        # airspeed_kind, a track that does not cover the run).
        from core.scenario.card import write_run_card

        card_path = write_run_card(
            spec, out / "card.json",
            cameras=camera_card_blocks(cameras, tracks, schedules, frame),
            scene_crs=frame.crs if frame.declared else None)
        print(f"  card:     {card_path} (consume-poses; one "
              f"commandlet pass per camera via -camera-index=N)")
        doc["artefacts"]["card"] = str(card_path)
    # Every model construction so far (validation, trim, the flight, the
    # card's mixture search) went to the log; the count is the sink's.
    _jsbsim_words(doc, console)

    total = sum(len(s) for s in schedules)
    # Scheduled, in that word: nothing has been rendered yet.
    print(f"scheduled {total} frames across {len(cameras)} camera(s)")
    table_lines, table_data = schedule_tables(manifest, brief=args.brief)
    for line in table_lines:
        print(line)
    doc["schedule"] = table_data

    # The flown track comes from the run's own telemetry (decimated in
    # the preview module, never interpolated); the header says so.
    previews = render_previews(manifest, out, heightfield=heightfield,
                               scene_frame=frame,
                               terrain_elevation_m=terrain_datum,
                               max_frames=args.max_previews,
                               scale=preview_scale, telemetry=columns)
    _note_previews(out, previews)
    print(f"  manifest: {manifest_path}")
    print(f"  previews: {len(previews)} geometry preview(s)"
          f"{preview_words(previews)} under {out / 'previews'} (previews "
          f"are not frames; {previews.track_source})")
    if previews.contact_sheets:
        print(f"  contact sheets: {len(previews.contact_sheets)} "
              f"(contact_sheets/<camera_id>.png, one per camera)")
    doc["artefacts"].update({
        "manifest": str(manifest_path),
        "telemetry": str(out / "telemetry.json"),
        "scenario": str(out / "scenario.yaml"),
        "run_json": str(out / "run.json"),
        "verify_json": str(out / "verify.json"),
        "previews_dir": str(out / "previews"),
        "contact_sheets": {camera_id: str(path) for camera_id, path
                           in previews.contact_sheets.items()},
    })
    doc["previews"] = json.loads(
        (out / "run.json").read_text(encoding="utf-8"))["previews"]

    # Every mode verifies what it just wrote, with the verifier the
    # instructor runs (flightsim.verify), BEFORE the final line -- so
    # "verification" is never claimed for a check that did not run. The
    # table is printed here for none and clip (engine parity AWAITING,
    # in those words); frames prints the complete table once its passes
    # have given engine parity frames to grade, and refuses here, before
    # any editor time, when the manifest itself does not verify.
    report = _verify_and_record(out)
    doc["verification"] = report.to_dict()
    if render != "frames" or not report.ok:
        print(report.render())
    if not report.ok:
        print(f"FAILED capture.verification: the manifest just written did "
              f"not verify ({report.passed} of {report.ran} checks passed); "
              f"FAILED: {', '.join(c.name for c in report.failed)}; "
              f"nothing is rendered from geometry that fails its own check")
        return EXIT_FAILED

    if render == "none":
        # Done as chosen: the engine's absence is a stated fact with its
        # reason, in a non-refusal register -- REFUSED is exit 2's word.
        if ue_available():
            print("render: none (headless by choice; --render frames "
                  "would render the scheduled frames on this machine)")
        else:
            print(f"engine absent: {ue_unavailable_reason()}; frames not "
                  f"rendered (--render frames where the engine exists)")
        print(f"done: manifest, {len(previews)} previews and verification "
              f"for {total} scheduled frames under {out} (no pixels)")
        return EXIT_DONE

    scene = {"key": "terrain" if heightfield else "flat",
             "terrain": args.terrain, "imagery": None}
    if render == "frames":
        return _render_frames(spec, out, card_path, scene, cameras,
                              schedules, doc, overlay=lambda: render_overlays(
                                  manifest, out, heightfield=heightfield,
                                  scene_frame=frame,
                                  terrain_elevation_m=terrain_datum,
                                  telemetry=columns))
    return _render_clip(spec, out, scene, doc)


def preview_words(previews) -> str:
    """" at 1280x720, 0.048 s/frame" (", 1/2 scale" when not 1); empty
    when nothing was drawn -- the measured numbers, never a promise."""
    if not previews or previews.resolution is None:
        return ""
    w, h = previews.resolution
    words = f" at {w}x{h}"
    if previews.scale != 1:
        words += f", 1/{previews.scale} scale"
    return words + f", {previews.seconds_per_frame:.3f} s/frame"


def _note_previews(out: Path, previews) -> None:
    """run.json "previews": what was drawn and what it measured --
    count, scale, resolution, seconds per frame, the contact sheets."""
    run_json = out / "run.json"
    record = json.loads(run_json.read_text(encoding="utf-8"))
    record["previews"] = {
        "count": len(previews),
        "scale": int(previews.scale),
        "resolution": list(previews.resolution) if previews.resolution else None,
        "s_per_frame": float(previews.seconds_per_frame),
        "track_source": str(previews.track_source),
        # Relative paths in the record are POSIX on every host: a
        # run.json written on Windows must read the same on a mac (CI
        # measured 'contact_sheets\\chase0.png' against the documented
        # 'contact_sheets/chase0.png').
        "contact_sheets": {camera_id: path.relative_to(out).as_posix()
                           for camera_id, path in previews.contact_sheets.items()},
    }
    run_json.write_text(json.dumps(record, indent=1), encoding="utf-8")


def _verify_and_record(out: Path):
    """Run the verifier the instructor runs (flightsim.verify) over
    ``out`` and write its report as ``verify.json`` beside the manifest
    -- the SAME JSON the webapp serves (webapp.capture.verification_verdict),
    written in every mode and rewritten after the engine passes, so the
    printed table and the run's own record cannot disagree."""
    from core.capture.verify import verify_run

    from webapp.capture import verification_verdict

    report = verify_run(out)
    (Path(out) / "verify.json").write_text(
        json.dumps(verification_verdict(report), indent=1), encoding="utf-8")
    return report


def _engine_prerequisites(spec, out: Path):
    """(editor, project, mesh) for an engine pass, or a named refusal
    (exit code) -- the owner's placeholder rule through the webapp's ONE
    implementation: an airframe without a real licensed model never
    renders, on any machine."""
    from core.util.platform import ue_editor_path

    from webapp.runs import refuse_placeholder_mesh

    refusal = refuse_placeholder_mesh(spec)
    if refusal is not None:
        print(f"REFUSED {refusal['constraint']}: {refusal['message']}")
        return None
    aircraft = str(spec.aircraft.value)
    mesh = REPO / "assets" / "generated" / aircraft / "mesh_manifest.json"
    project = REPO / "ue" / "FlightSim.uproject"
    return ue_editor_path(), project, mesh


def _render_frames(spec, out: Path, card_path: Path, scene, cameras,
                   schedules, doc: Optional[dict] = None,
                   overlay=None) -> int:
    """--render frames: one consume-poses pass per camera, graded pass
    by pass, the reprojected-geometry overlays drawn over every
    rendered frame (``overlay``: the preview module's render_overlays
    bound to this run's manifest and scene), then the verifier's
    engine-parity check over the lot."""
    from experiments.showcase_matrix import FPS, HEIGHT, TIME_OF_DAY, \
        VISIBILITY, WIDTH

    doc = doc if doc is not None else {}
    prerequisites = _engine_prerequisites(spec, out)
    if prerequisites is None:
        return EXIT_REFUSED
    editor, project, mesh = prerequisites
    duration = float(spec.duration.value)
    passes = []
    for index, schedule in enumerate(schedules):
        camera_id = schedule.camera_id
        frames_dir = out / "frames" / camera_id
        print(f"engine pass {index + 1} of {len(schedules)}: camera "
              f"'{camera_id}', {len(schedule)} frames scheduled over the "
              f"{duration:g} s run (-camera-index={index})")
        command = render_command(
            editor, project, card_path, frames_dir, fps=FPS, width=WIDTH,
            height=HEIGHT, look=TIME_OF_DAY["noon"],
            fog_density=VISIBILITY["clear"], scene=scene, mesh=mesh,
            telemetry=(out / "engine_telemetry.json" if index == 0
                       else None),
            camera_index=index)
        ok = run_render_pass(command, frames_dir, frames_dir / "render.log")
        problem = (check_render_pass(frames_dir, len(schedule)) if ok
                   else f"the engine pass wrote no render.json; see "
                        f"{frames_dir / 'render.log'}")
        if problem is not None:
            print(f"FAILED {RENDER_FRAMES_CONSTRAINT}: camera '{camera_id}': "
                  f"{problem}")
            print(f"  rendered {rendered_count(frames_dir)} of "
                  f"{len(schedule)} scheduled frames; the frames written "
                  f"so far are not a frame set")
            doc["refusals"] = [{"constraint": RENDER_FRAMES_CONSTRAINT,
                                "message": f"camera '{camera_id}': {problem}"}]
            return EXIT_REFUSED
        stepping = pass_stepping(frames_dir)
        passes.append({"camera_id": camera_id, "camera_index": index,
                       "scheduled": len(schedule),
                       "rendered": rendered_count(frames_dir),
                       **(stepping or {})})
        print(f"  camera '{camera_id}': {rendered_count(frames_dir)} of "
              f"{len(schedule)} scheduled frames rendered under "
              f"{frames_dir}" + stepping_words(stepping))

    overlays = overlay() if overlay is not None else []
    if overlay is not None:
        print(f"  overlays: {len(overlays)} reprojected-geometry overlay(s) "
              f"over the rendered frames under {out / 'overlays'} "
              f"({overlays.seconds_per_frame:.3f} s/frame; the aircraft "
              f"box, wireframe and horizon the manifest predicts, drawn on "
              f"the engine's pixels)")

    first = schedules[0]
    clip = out / "clip.mp4"
    clip_seconds = scheduled_clip_seconds(list(first.times))
    try:
        from core.util.platform import find_ffmpeg

        encoded = encode_scheduled_clip(find_ffmpeg(),
                                        out / "frames" / first.camera_id,
                                        list(first.times), clip)
        if not encoded:
            print("  clip: ffmpeg could not encode the by-product clip; the "
                  "frames stand on their own")
    except Exception as exc:
        encoded = False
        print(f"  clip: not encoded ({type(exc).__name__}: {exc}); the "
              f"frames stand on their own")
    if encoded:
        print(f"  clip:     {clip} (by-product of camera "
              f"'{first.camera_id}', {len(first)} frames at their scheduled "
              f"instants; {clip_seconds:.3f} s = black to "
              f"t={float(first.times[0]):.3f} s, the flight to "
              f"t={float(first.times[-1]):.3f} s, a {LAST_FRAME_HOLD_S:g} s "
              f"hold)")
    # Recorded beside the run's digests: what each pass cost and what the
    # clip was expected to be, whether or not it encoded.
    run_json = out / "run.json"
    record = json.loads(run_json.read_text(encoding="utf-8"))
    record.update({"render_passes": passes, "clip_encoded": bool(encoded),
                   "clip_seconds": float(clip_seconds),
                   "overlays": {"count": len(overlays),
                                "s_per_frame": float(getattr(
                                    overlays, "seconds_per_frame", 0.0))}})
    run_json.write_text(json.dumps(record, indent=1), encoding="utf-8")
    doc["render_passes"] = passes
    doc.setdefault("artefacts", {}).update({
        "frames_dir": str(out / "frames"), "overlays_dir": str(out / "overlays"),
        "clip": str(clip) if encoded else None})

    report = _verify_and_record(out)
    doc["verification"] = report.to_dict()
    print(report.render())
    total = sum(len(s) for s in schedules)
    verified = 0
    for check in report.checks:
        if check.name == "engine_parity" and check.data:
            verified = sum(int(c.get("verified", 0))
                           for c in check.data["cameras"].values())
    if not report.ok:
        print(f"FAILED capture.verification: rendered {total} frames "
              f"across {len(cameras)} camera(s) but verification failed "
              f"({verified} verified by engine parity; FAILED: "
              f"{', '.join(c.name for c in report.failed)})")
        return EXIT_FAILED
    print(f"done: rendered {total} frames across {len(cameras)} camera(s) "
          f"({verified} verified by engine parity) under {out / 'frames'}")
    return EXIT_DONE


def _render_clip(spec, out: Path, scene, doc: Optional[dict] = None) -> int:
    """--render clip: the single preset pass (the SAME flags the webapp's
    clip flow builds) and an fps clip; nothing rendered as frames."""
    from core.scenario.card import write_run_card
    from experiments.showcase_matrix import FPS, HEIGHT, TIME_OF_DAY, \
        VISIBILITY, WIDTH, encode_clip

    from webapp.runs import camera_render_flags

    doc = doc if doc is not None else {}
    prerequisites = _engine_prerequisites(spec, out)
    if prerequisites is None:
        return EXIT_REFUSED
    editor, project, mesh = prerequisites
    try:
        camera_flags = camera_render_flags(spec)
    except ValueError as exc:
        print(f"REFUSED {exc}")
        return EXIT_REFUSED
    card_path = write_run_card(spec, out / "clip_card.json")
    frames_dir = out / "clip_frames"
    command = render_command(
        editor, project, card_path, frames_dir, fps=FPS, width=WIDTH,
        height=HEIGHT, look=TIME_OF_DAY["noon"],
        fog_density=VISIBILITY["clear"], scene=scene, mesh=mesh,
        telemetry=out / "engine_telemetry.json", camera_flags=camera_flags)
    print(f"engine pass: preset camera {camera_flags[0]}, {FPS} fps over "
          f"the {float(spec.duration.value):g} s run")
    if not run_render_pass(command, frames_dir, out / "clip_render.log"):
        print(f"FAILED render.clip: the engine pass wrote no render.json; "
              f"see {out / 'clip_render.log'}")
        return EXIT_REFUSED
    clip = out / "clip.mp4"
    if not encode_clip(frames_dir, clip):
        print("FAILED render.clip: ffmpeg could not encode the clip")
        return EXIT_REFUSED
    doc.setdefault("artefacts", {})["clip"] = str(clip)
    print(f"done: rendered clip: {clip} ({FPS} fps); 0 frames rendered as "
          f"a frame set (--render frames for that)")
    return EXIT_DONE


if __name__ == "__main__":
    sys.exit(main())
