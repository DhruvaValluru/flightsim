"""The capture half of a webapp run: labeled geometry beside the pixels.

Camera Phase 1 landed the capture pipeline as a CLI (`flightsim.capture`,
`flightsim.verify`) and wired only its spec-and-refusal half into the
page. A webapp run therefore produced a CLIP -- while the phase's own
brief asked for "a defined number of images rather than a clip", with
every frame carrying enough geometry to be used as labeled data. This
module closes that gap: the same solver, scheduler, manifest, verifier
and previews the CLI drives, driven from a run instead, so the page can
hand every artefact back as a link (user request 2026-09-01: "i want the
web app the interface where they can access everything").

WHICH FLIGHT THE MANIFEST DESCRIBES. The capture is solved from its OWN
headless run of the spec -- core.scenario.runner.run_spec, the same
reference host the CLI uses -- and everything it produces is written
into a `capture/` SUBDIRECTORY carrying that run's own telemetry.json
beside the manifest. The run directory's top-level telemetry.json stays
the rendered flight's. Two hosts, two files, neither presented as the
other: a reader can always tell which flight a number came from, which
is the whole point of a manifest.

That also makes capture platform-independent. Rendering still refuses
`ue.platform` off a render-capable host; the capture half runs
everywhere, exactly as the CLI does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.fdm.console import JSBSimConsole, active_console, jsbsim_console

REPO = Path(__file__).resolve().parents[1]

#: Progress sink: one human-readable line per step.
Report = Callable[[str], None]

#: Previews are a convenience, not the data. A long run can schedule more
#: frames than a browser wants thumbnails for, so the page's runs cap the
#: image count and SAY SO -- the manifest always carries every frame.
MAX_PREVIEWS = 60


#: Closure tolerance for the paired closed-loop run (Package C). The
#: autopilot's own declared-before-the-run tolerances; a module constant so
#: a test can prove the pair FAILS when the tolerance cannot be met.
from core.control.autopilot import ClosureTolerance  # noqa: E402

CLOSURE_TOLERANCE = ClosureTolerance()


class CaptureError(RuntimeError):
    """A named capture refusal, carried to the run status verbatim.

    ``actual`` / ``limit`` / ``unit`` are the offending value and the
    bound it broke, when the refusal has them (a solved track's worst
    AGL against the clearance floor; the climb a terrain threat needs
    against the climb available): the SAME three fields
    core.scenario.validate.Violation carries, rendered in the same
    shape, so the pre-run verdict and a mid-run refusal read alike."""

    def __init__(self, constraint: str, message: str,
                 actual: Optional[float] = None,
                 limit: Optional[float] = None,
                 unit: Optional[str] = None) -> None:
        super().__init__(message)
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit

    def as_dict(self) -> Dict:
        """run.capture on a refused capture: the constraint under
        ``refused`` (the page's existing key), the message and the
        three value fields (None when the refusal has none)."""
        return {"refused": self.constraint, "message": self.message,
                "actual": self.actual, "limit": self.limit,
                "unit": self.unit}

    def render(self) -> str:
        return refused_words(self.as_dict())


def refused_words(refusal: Dict) -> str:
    """``[constraint] message (measured X unit, limit Y unit)`` -- the
    value clause only when both numbers exist, formatted as the
    validation verdict formats them."""
    words = f"[{refusal.get('refused')}] {refusal.get('message')}"
    actual, limit = refusal.get("actual"), refusal.get("limit")
    if actual is not None and limit is not None:
        unit = f" {refusal['unit']}" if refusal.get("unit") else ""
        words += (f" (measured {float(actual):g}{unit}, "
                  f"limit {float(limit):g}{unit})")
    return words


def _run_named(run_spec, spec, **kwargs):
    """run_spec, with the terrain refusals carried to the page by name.

    Package E: a closed-loop run over a raster refuses ``terrain.lookahead``
    when the projected track meets terrain the aircraft cannot out-climb,
    and the contact check refuses on an impact. Both reach the run status
    as a named constraint, never as a bare traceback.
    """
    from core.terrain.contact import TerrainImpactError
    from core.terrain.lookahead import TerrainLookaheadError

    try:
        return run_spec(spec, **kwargs)
    except TerrainLookaheadError as exc:
        threat = exc.threat
        raise CaptureError(exc.constraint, str(exc),
                           actual=float(threat.required_hdot_mps),
                           limit=float(threat.available_hdot_mps),
                           unit="m/s of climb") from exc
    except TerrainImpactError as exc:
        raise CaptureError("terrain.impact", str(exc),
                           actual=float(exc.impact.penetration_m), limit=0.0,
                           unit="m into the terrain") from exc


def run_console(capture_dir: Path):
    """The sink the capture and closure flights construct their models
    under. Inside a page run the manager has already entered the run's
    own sink (``<run>/jsbsim.log``, around the whole flow: planning,
    the flights, the card), so the flights simply write there, the
    load numbering continuous; a direct ``capture_run`` (a test, a
    script) with no sink active opens ``capture/jsbsim.log`` for
    itself. Either way JSBSim's banner never reaches the console."""
    import contextlib

    active = active_console()
    if active is not None:
        return contextlib.nullcontext(active)
    return jsbsim_console(Path(capture_dir) / "jsbsim.log")


def _log_words(console: JSBSimConsole, out: Path) -> str:
    """The sink's log named relative to the run (``jsbsim.log`` or
    ``capture/jsbsim.log``)."""
    try:
        return console.path.resolve().relative_to(Path(out).resolve()).as_posix()
    except ValueError:
        return str(console.path)


def scene_geometry(spec, scene: Dict):
    """(heightfield, scene frame, tornado block) for a webapp scene.

    The SAME trio camera_scene_violations refuses on, so the pre-run
    check and the solved capture cannot disagree about where the world
    is.
    """
    from core.capture.poses import SceneFrame
    from core.terrain.heightfield import Heightfield

    from webapp.runs import CLIP_SECONDS, tornado_axis

    heightfield = (Heightfield.read(Path(scene["terrain"]))
                   if scene.get("terrain") else None)
    frame = SceneFrame.for_spec(spec, heightfield)
    tornado = None
    if str(spec.weather_event.value) == "tornado":
        from core.environment.tornado import FADE_TOP_M, R_CORE_M

        seconds = min(float(spec.duration.value), CLIP_SECONDS)
        axis_n, axis_e = tornado_axis(spec, scene, seconds)
        tornado = {"centre_north_m": axis_n, "centre_east_m": axis_e,
                   "r_core_m": R_CORE_M, "fade_top_m": FADE_TOP_M}
    return heightfield, frame, tornado


@dataclass
class CaptureOutcome:
    """What one capture solved and wrote. ``summary`` is the mapping the
    page renders (run.capture); the solved objects ride beside it so the
    frames flow can hand the SAME tracks and schedules to the engine
    through the card -- never a second solve."""

    summary: Dict
    capture_dir: Path
    cameras: List = field(default_factory=list)
    tracks: List = field(default_factory=list)
    schedules: List = field(default_factory=list)
    frame: object = None
    manifest: Optional[Dict] = None
    #: The scene the previews were drawn over, kept so the overlays
    #: drawn after the engine passes use the SAME ground.
    heightfield: object = None
    terrain_elevation_m: float = 0.0
    #: The run's recorded telemetry columns: the flown track the
    #: previews drew, kept so the overlays draw the SAME track.
    telemetry: Optional[Dict] = None

    def card_blocks(self) -> List[Dict]:
        """The card's ``cameras`` block through the ONE shared builder
        (core.capture.poses.camera_card_blocks): spec fields, the solved
        per-sample track and the capture instants, verbatim."""
        from core.capture.poses import camera_card_blocks

        return camera_card_blocks(self.cameras, self.tracks,
                                  self.schedules, self.frame)


def camera_counts(schedules, verdict: Dict) -> List[Dict]:
    """Per-camera ``scheduled`` / ``rendered`` / ``verified``, the three
    words every status line and the page use. Scheduled is the
    schedule's length; rendered and verified come from the verifier's
    engine-parity data -- PNGs it counted on disk and frames it graded
    -- so the page never shows a count it cannot back with a file. A
    headless run reports rendered 0, verified 0. ``frames`` repeats
    scheduled for the page's existing readers."""
    return _counts([(s.camera_id, len(s)) for s in schedules], verdict)


def _counts(scheduled, verdict: Dict) -> List[Dict]:
    """camera_counts' arithmetic over (camera_id, scheduled) pairs --
    the same for a live schedule and for a manifest read back from
    disk, so a recovered card cannot count differently."""
    engine = {}
    for check in verdict.get("checks", []):
        if check.get("name") == "engine_parity":
            engine = (check.get("data") or {}).get("cameras") or {}
    counts = []
    for camera_id, length in scheduled:
        per = engine.get(camera_id, {})
        counts.append({
            "camera_id": camera_id,
            "frames": int(length),
            "scheduled": int(length),
            "rendered": int(per.get("rendered", 0)),
            "verified": int(per.get("verified", 0)),
        })
    return counts


def verify_capture(capture_dir: Path, report: Report = lambda line: None):
    """Run the verifier over ``capture_dir`` and (re)write verify.json --
    ONCE for the file and the page, so the download and the screen
    cannot disagree. Returns the verdict mapping."""
    from core.capture.verify import verify_run

    verification = verify_run(capture_dir)
    verdict = verification_verdict(verification)
    (Path(capture_dir) / "verify.json").write_text(
        json.dumps(verdict, indent=1), encoding="utf-8")
    report(verification_line(verification))
    return verdict


def refresh_after_render(outcome: "CaptureOutcome",
                         report: Report = lambda line: None) -> Dict:
    """After the engine passes: draw the reprojected-geometry overlay
    over every rendered frame (capture/overlays/<camera_id>/NNNN.png:
    the verification made visible), re-verify (engine parity now has
    frames to grade) and update the summary's counts and verification
    in place. Returns the summary."""
    from core.capture.preview import render_overlays

    overlays = []
    if outcome.manifest is not None:
        overlays = render_overlays(
            outcome.manifest, outcome.capture_dir,
            heightfield=outcome.heightfield, scene_frame=outcome.frame,
            terrain_elevation_m=outcome.terrain_elevation_m,
            telemetry=outcome.telemetry)
    outcome.summary["overlays"] = len(overlays)
    outcome.summary["overlay_s_per_frame"] = float(
        getattr(overlays, "seconds_per_frame", 0.0))
    # Recorded beside the previews' record, so a card rebuilt after a
    # server restart shows the same overlay count and timing.
    _update_run_record(outcome.capture_dir, overlays={
        "count": len(overlays),
        "s_per_frame": outcome.summary["overlay_s_per_frame"]})
    report(f"{len(overlays)} overlay(s): the manifest's aircraft box, "
           f"ground and horizon reprojected over the rendered frames "
           f"under capture/overlays")
    verdict = verify_capture(outcome.capture_dir, report)
    counts = camera_counts(outcome.schedules, verdict)
    outcome.summary["verification"] = verdict
    outcome.summary["cameras"] = counts
    outcome.summary["rendered"] = sum(c["rendered"] for c in counts)
    outcome.summary["verified"] = sum(c["verified"] for c in counts)
    return outcome.summary


def capture_run(spec, out: Path, scene: Dict,
                report: Report = lambda line: None,
                preview_scale: int = 1) -> CaptureOutcome:
    """Run the spec headlessly and write its capture artefacts.

    Writes into ``out/capture``: telemetry.json (this run's own),
    scenario.yaml, run.json, capture_manifest.json, verify.json, one
    geometry preview per scheduled frame (capped, and the cap is
    reported; full resolution unless ``preview_scale`` asks for 1/N)
    and a contact sheet per camera. Returns the outcome whose
    ``summary`` the page renders.

    Raises CaptureError -- named -- on a schedule or solved-track
    refusal, so a capture never half-succeeds into a manifest that
    describes geometry the scene refuses.
    """
    from core.capture.manifest import (
        build_capture_manifest, write_capture_manifest,
    )
    from core.capture.poses import solve_pose_track
    from core.capture.preview import render_previews
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.capture.validate import track_violations
    from core.scenario.camera import default_cameras
    from core.scenario.runner import run_spec

    from webapp.runs import CLIP_SECONDS

    heightfield, frame, tornado = scene_geometry(spec, scene)
    terrain_ground = None
    if heightfield is not None:
        from core.terrain.ground import TerrainGround

        terrain_ground = TerrainGround(heightfield)

    capture_dir = Path(out) / "capture"
    capture_dir.mkdir(parents=True, exist_ok=True)

    report("flying the spec headlessly for the capture geometry")
    # JSBSim's startup banner (C++, file descriptor 1) goes to the
    # run's log, stamped per model load, exactly as the CLI routes it
    # -- never to the server's console, never dropped.
    with run_console(capture_dir) as console:
        before = console.loads
        result = _run_named(run_spec, spec, terrain_ground=terrain_ground)
    routed = console.loads - before
    log_words = _log_words(console, out)
    report(f"JSBSim output: {log_words} ({routed} model loads routed there "
           f"for the capture flight; nothing of JSBSim's on the console)")
    columns = result.telemetry.columns

    cameras = spec.cameras or default_cameras(spec)
    tracks: List = []
    schedules: List = []
    try:
        for camera in cameras:
            tracks.append(solve_pose_track(columns, camera, frame))
            schedules.append(solve_schedule(
                columns, camera, frame, rate_hz=float(spec.rate.value)))
    except ScheduleError as exc:
        raise CaptureError("camera.schedule", str(exc)) from exc

    terrain_datum = float(spec.terrain_elevation.value)
    refusals = []
    for track in tracks:
        refusals.extend(track_violations(
            track, heightfield=heightfield, scene_frame=frame,
            tornado=tornado, terrain_elevation_m=terrain_datum))
    if refusals:
        first = refusals[0]
        # The offending value travels: the message alone never states
        # the AGL a terrain_clearance refusal measured.
        raise CaptureError(first.constraint, first.message,
                           actual=first.actual, limit=first.limit,
                           unit=first.unit)

    manifest = build_capture_manifest(
        spec, columns, frame, tracks, schedules,
        output_digest=result.output_digest,
        scene={"key": scene.get("key", "flat"),
               "terrain": scene.get("terrain")},
        terrain_sha256=heightfield.digest() if heightfield else None,
        cameras=cameras,
        aircraft_metrics=result.manifest.get("aircraft_metrics"))
    write_capture_manifest(manifest, capture_dir)
    result.telemetry.write_json(capture_dir / "telemetry.json")
    spec.write(capture_dir / "scenario.yaml")
    (capture_dir / "run.json").write_text(json.dumps({
        "spec_digest": result.spec_digest,
        "output_digest": result.output_digest,
        "samples": len(result.telemetry),
        "clip_seconds_cap": CLIP_SECONDS,
    }, indent=1), encoding="utf-8")

    total = sum(len(s) for s in schedules)
    previews = render_previews(manifest, capture_dir,
                               heightfield=heightfield, scene_frame=frame,
                               terrain_elevation_m=terrain_datum,
                               max_frames=MAX_PREVIEWS, scale=preview_scale,
                               telemetry=columns)
    capped = len(previews) < total
    contact_sheets = {camera_id: f"capture/contact_sheets/{camera_id}.png"
                      for camera_id in previews.contact_sheets}
    # The run's own record of what was drawn and what it measured.
    run_json = capture_dir / "run.json"
    run_record = json.loads(run_json.read_text(encoding="utf-8"))
    run_record["previews"] = {
        "count": len(previews), "scale": int(previews.scale),
        "resolution": list(previews.resolution) if previews.resolution else None,
        "s_per_frame": float(previews.seconds_per_frame),
        "track_source": str(previews.track_source),
        "contact_sheets": contact_sheets,
    }
    # Where JSBSim's console went and how many loads: the summary's own
    # two facts that live nowhere else, kept so the card survives a
    # server restart with the same numbers.
    run_record["jsbsim"] = {"log": log_words, "model_loads": int(routed)}
    run_json.write_text(json.dumps(run_record, indent=1), encoding="utf-8")
    # Scheduled, in that word: nothing has been rendered yet, and a
    # preview is not a capture.
    resolution = (f" at {previews.resolution[0]}x{previews.resolution[1]}"
                  + (f" (1/{previews.scale} scale)" if previews.scale != 1 else "")
                  + f", {previews.seconds_per_frame:.3f} s/frame"
                  if previews.resolution else "")
    report(f"scheduled {total} frame(s) across {len(cameras)} camera(s); "
           f"{len(previews)} geometry preview(s) written{resolution}; "
           f"{len(contact_sheets)} contact sheet(s)")

    # Verify what was just written, with the SAME verifier the CLI runs
    # -- an independent reimplementation of the projection maths, so a
    # pass means the manifest reproduces itself, not that one code path
    # agrees with itself. Built ONCE and used for both the file and the
    # page: two constructions of the same report are two chances for
    # the download and the screen to disagree about whether a run
    # verified.
    verdict = verify_capture(capture_dir, report)
    counts = camera_counts(schedules, verdict)

    summary = {
        "frames": total,
        "scheduled": total,
        "rendered": sum(c["rendered"] for c in counts),
        "verified": sum(c["verified"] for c in counts),
        "cameras": counts,
        "previews": len(previews),
        "previews_capped": capped,
        "preview_cap": MAX_PREVIEWS if capped else None,
        "preview_scale": int(previews.scale),
        "preview_resolution": (list(previews.resolution)
                               if previews.resolution else None),
        "preview_s_per_frame": float(previews.seconds_per_frame),
        "preview_track_source": str(previews.track_source),
        "contact_sheets": contact_sheets,
        "verification": verdict,
        "jsbsim_log": log_words,
        "jsbsim_model_loads": int(routed),
    }
    return CaptureOutcome(summary=summary, capture_dir=capture_dir,
                          cameras=list(cameras), tracks=tracks,
                          schedules=schedules, frame=frame,
                          manifest=manifest, heightfield=heightfield,
                          terrain_elevation_m=terrain_datum,
                          telemetry=columns)


def _update_run_record(capture_dir: Path, **fields) -> None:
    """Merge ``fields`` into capture/run.json (created if absent)."""
    path = Path(capture_dir) / "run.json"
    record = {}
    if path.is_file():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
    record.update(fields)
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")


def _read_json(path: Path) -> Optional[Dict]:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def recover_capture_summary(out_dir: Path) -> Optional[Dict]:
    """run.capture rebuilt from the files a finished run left: the
    manifest (scheduled per camera), verify.json (the verification and
    the rendered/verified counts, through the same arithmetic the live
    run used), capture/run.json (previews, overlays, the JSBSim log),
    closure.json and provenance.json (the engine passes and the
    by-product clip). Every number on a recovered card is therefore one
    of the files the page links. None when the manifest or verify.json
    is missing -- a refused capture wrote neither."""
    out_dir = Path(out_dir)
    capture_dir = out_dir / "capture"
    manifest = _read_json(capture_dir / "capture_manifest.json")
    verdict = _read_json(capture_dir / "verify.json")
    if manifest is None or verdict is None:
        return None
    order = [c.get("camera_id") for c in manifest.get("cameras", [])]
    lengths: Dict[str, int] = {camera_id: 0 for camera_id in order}
    for record in manifest.get("frames", []):
        camera_id = record.get("camera_id")
        if camera_id not in lengths:
            order.append(camera_id)
            lengths[camera_id] = 0
        lengths[camera_id] += 1
    counts = _counts([(camera_id, lengths[camera_id]) for camera_id in order],
                     verdict)
    total = sum(lengths.values())
    record = _read_json(capture_dir / "run.json") or {}
    previews = record.get("previews") or {}
    preview_count = int(previews.get("count", 0))
    capped = preview_count < total
    jsbsim = record.get("jsbsim") or {}
    summary = {
        "frames": total,
        "scheduled": total,
        "rendered": sum(c["rendered"] for c in counts),
        "verified": sum(c["verified"] for c in counts),
        "cameras": counts,
        "previews": preview_count,
        "previews_capped": capped,
        "preview_cap": MAX_PREVIEWS if capped else None,
        "preview_scale": int(previews.get("scale", 1)),
        "preview_resolution": previews.get("resolution"),
        "preview_s_per_frame": float(previews.get("s_per_frame", 0.0)),
        "preview_track_source": str(previews.get("track_source", "")),
        "contact_sheets": previews.get("contact_sheets") or {},
        "verification": verdict,
        "jsbsim_log": jsbsim.get("log"),
        "jsbsim_model_loads": jsbsim.get("model_loads"),
    }
    closure = _read_json(capture_dir / "closure.json")
    if closure is not None:
        summary["closure"] = closure
    overlays = record.get("overlays")
    if overlays is not None:
        summary["overlays"] = int(overlays.get("count", 0))
        summary["overlay_s_per_frame"] = float(overlays.get("s_per_frame", 0.0))
    provenance = _read_json(out_dir / "provenance.json") or {}
    passes = provenance.get("render_passes")
    if passes is not None:
        summary["render_passes"] = passes
        summary["clip"] = {
            "encoded": bool(provenance.get("clip_encoded")),
            "seconds": provenance.get("clip_seconds"),
            "by_product_of": passes[0]["camera_id"] if passes else None,
        }
    return summary


def verification_verdict(verification) -> Dict:
    """verify.json's content: the verifier's own report as data
    (VerificationReport.to_dict -- the ONE source the file, the page,
    flightsim.verify and --json all read). A check's ``ok`` is True,
    False or None (AWAITING -- the engine-parity check with no engine
    frames to grade -- or SKIPPED, with its reason: nothing to grade),
    and the report's ``ok`` is decided by the checks that ran, exactly
    as VerificationReport.ok is."""
    return verification.to_dict()


def verification_line(verification) -> str:
    """The status line: PASSED/FAILED over the checks that ran, the
    skipped ones named with their reason and the awaiting ones named as
    such -- neither counted as passed nor as ran."""
    line = (f"verification {'PASSED' if verification.ok else 'FAILED'} "
            f"({verification.passed}/{verification.ran} checks")
    if verification.skipped:
        line += ("; " + ", ".join(f"{c.name} skipped ({c.skipped})"
                                  for c in verification.skipped))
    if verification.awaiting:
        line += (f"; {', '.join(c.name for c in verification.awaiting)} "
                 f"awaiting engine frames")
    return line + ")"


def closure_run(spec, out: Path, scene: Dict,
                report: Report = lambda line: None,
                full_duration: bool = False) -> Dict:
    """The paired CLOSED-LOOP run, and its closure report (Package C).

    The render host has no controller, so every clip is open loop and the
    closure assertion -- this project's stated reason for existing ("a run
    that did not reach what it was commanded is not evidence of anything")
    -- could never run on the artefact a person looks at. This flies the
    SAME spec headlessly with the autopilot engaged, on the same scene
    raster, and writes capture/closure.json beside the clip: commanded vs
    achieved altitude, airspeed, heading and settledness over the settled
    half of the run, against tolerances declared before the run.

    The caller fails the run when the report is not ok. A failed closure
    is a named failure (``closure.<check>``), never a note.

    The pair grades the window the artefact shows: the clip's
    CLIP_SECONDS cap by default; ``full_duration`` for a frames run,
    whose schedule spans the whole flight the engine steps.
    """
    from core.scenario.runner import run_spec

    heightfield, _frame, _tornado = scene_geometry(spec, scene)
    terrain_ground = None
    if heightfield is not None:
        from core.terrain.ground import TerrainGround

        terrain_ground = TerrainGround(heightfield)

    from webapp.runs import CLIP_SECONDS

    pair = spec.__class__.from_dict(spec.to_dict())
    if not bool(pair.hold_state.value):
        pair.set("hold_state", True,
                 frm="closure pair: the same spec flown closed loop, so the "
                     "closure assertion reaches the rendered artefact")
    # The clip is capped at CLIP_SECONDS; the pair grades THAT flight, not
    # a longer one the artefact never shows. Measured on the user's
    # machine: a 22 s clip over the mountains passed capture, then its
    # 120 s closure pair refused terrain.lookahead on a ridge 59 s ahead
    # that the clip never reaches.
    seconds = min(float(pair.duration.value), CLIP_SECONDS)
    if full_duration:
        # A frames run steps the whole flight: the pair grades all of it.
        seconds = float(pair.duration.value)
    if seconds < float(pair.duration.value):
        pair.set("duration", seconds,
                 frm=f"closure pair: the clip's own window "
                     f"({CLIP_SECONDS:g} s cap)")
    report("flying the same spec closed loop for the closure report")
    # The same sink the capture flight wrote to (the run's, or
    # capture/jsbsim.log appended), the same stamps: the closure pair's
    # loads are named there too.
    with run_console(Path(out) / "capture") as console:
        before = console.loads
        result = _run_named(run_spec, pair, terrain_ground=terrain_ground,
                            assert_closure=False)
    report(f"JSBSim output: {_log_words(console, out)} "
           f"({console.loads - before} model loads routed there for the "
           f"closure flight)")
    if result.closure is None:
        raise CaptureError(
            "closure.unavailable",
            "the paired run produced no closure report: the autopilot did "
            "not engage")
    # Re-grade against the module tolerance (the run graded with the
    # autopilot's default; identical unless a test pins it), so what is
    # written is what was judged.
    checks = [{"name": c.name, "commanded": c.commanded, "achieved": c.achieved,
               "tolerance": c.tolerance, "unit": c.unit, "ok": c.ok}
              for c in result.closure.checks]
    # The window word names what was GRADED, not what the run shows:
    # "full duration" when the pair flew the whole flight (a frames
    # run), "capped" when it flew the first min(duration, cap) seconds
    # -- the window a clip covers, whether or not this run made one (a
    # headless run has no clip to name). spec_duration_s beside
    # duration_s says whether the cap actually shortened the flight.
    verdict = {"ok": all(c["ok"] for c in checks), "checks": checks,
               "duration_s": seconds, "clip_seconds_cap": CLIP_SECONDS,
               "spec_duration_s": float(spec.duration.value),
               "window": "full duration" if full_duration else "capped",
               "pair_spec_digest": pair.digest(),
               "output_digest": result.output_digest,
               "settle_fraction": CLOSURE_TOLERANCE.settle_fraction}
    capture_dir = Path(out) / "capture"
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "closure.json").write_text(
        json.dumps(verdict, indent=1), encoding="utf-8")
    report(f"closure {'PASSED' if verdict['ok'] else 'FAILED'} "
           f"({sum(c['ok'] for c in checks)}/{len(checks)} checks)")
    return verdict


#: What each artefact IS, shown beside its link. A download list with no
#: labels makes the reader guess which file carries the geometry.
ARTIFACT_NOTES = {
    "clip.mp4": "the rendered clip",
    "card.json": "the run card: exactly what the engine was handed",
    "provenance.json": "prompt, compiler, model, spec digest, scene",
    "scenario.yaml": "the compiled spec, cameras included",
    "telemetry.json": "the rendered flight's recorded telemetry",
    "effect.json": "conditions effect against a still-air baseline",
    "render.log": "the editor's own output",
    "capture/capture_manifest.json":
        "per-frame pose, intrinsics and aircraft state -- the labeled data",
    "capture/verify.json": "the verification checks as run (engine parity awaits engine frames on a headless run)",
    "capture/closure.json":
        "the paired closed-loop run: commanded vs achieved, by name",
    "capture/telemetry.json":
        "the headless flight the manifest describes",
    "capture/scenario.yaml": "the spec as captured",
    "capture/run.json": "spec and output digests of the capture run",
    "status.json":
        "the run's own status log: every status line in order, and the "
        "verdict it ended on (read back after a server restart)",
    "jsbsim.log":
        "JSBSim's own console for the whole run (planning, the capture and "
        "closure flights, the card), one '# load N:' stamp per model "
        "construction",
    "capture/jsbsim.log":
        "JSBSim's own console for a direct capture (no page run), one "
        "'# load N:' stamp per model construction",
}
#: The overlay class: reprojected geometry drawn over a rendered frame.
OVERLAY_NOTE = ("reprojected geometry over the rendered frame: the manifest's "
                "aircraft body and box, ground and horizon drawn on the "
                "engine's pixels, so the verification is visible")
CONTACT_SHEET_NOTE = ("contact sheet: every preview of this camera as a "
                      "thumbnail with its index and time")
#: Per-camera engine artefacts under capture/frames/<camera_id>/.
FRAME_DIR_NOTES = {
    "render.json": "the engine pass: applied pose and time per frame",
    "render.log": "the editor's own output for this camera's pass",
    "clip_playlist.ffconcat": "the by-product clip's frame timing",
}


def run_artifacts(out_dir: Path) -> List[Dict]:
    """Every file a finished run left behind, newest listing each time.

    Previews are summarised as one entry per camera rather than listed
    frame by frame -- 60 thumbnails is a gallery, not a download list.
    """
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        return []
    entries: List[Dict] = []
    for name in ("clip.mp4", "card.json", "provenance.json",
                 "scenario.yaml", "telemetry.json", "effect.json",
                 "render.log", "status.json", "jsbsim.log",
                 "capture/capture_manifest.json",
                 "capture/verify.json", "capture/closure.json",
                 "capture/telemetry.json",
                 "capture/scenario.yaml", "capture/run.json",
                 "capture/jsbsim.log"):
        path = out_dir / name
        if path.is_file():
            entries.append({"name": name, "bytes": path.stat().st_size,
                            "note": ARTIFACT_NOTES.get(name, "")})
    frames_root = out_dir / "capture" / "frames"
    if frames_root.is_dir():
        # Rendered frames FIRST: they are the deliverable; previews are
        # the fallback and are labelled as such below.
        for camera_dir in sorted(p for p in frames_root.iterdir()
                                 if p.is_dir()):
            images = sorted(camera_dir.glob("*.png"))
            if images:
                entries.append({
                    "name": f"capture/frames/{camera_dir.name}",
                    "count": len(images),
                    "note": f"{len(images)} rendered frame(s) for camera "
                            f"'{camera_dir.name}', named by manifest "
                            f"index",
                    "images": [f"capture/frames/{camera_dir.name}/"
                               f"{p.name}" for p in images],
                })
            for name, note in FRAME_DIR_NOTES.items():
                path = camera_dir / name
                if path.is_file():
                    entries.append({
                        "name": f"capture/frames/{camera_dir.name}/{name}",
                        "bytes": path.stat().st_size, "note": note})
    overlays_root = out_dir / "capture" / "overlays"
    if overlays_root.is_dir():
        for camera_dir in sorted(p for p in overlays_root.iterdir()
                                 if p.is_dir()):
            images = sorted(camera_dir.glob("*.png"))
            if images:
                entries.append({
                    "name": f"capture/overlays/{camera_dir.name}",
                    "count": len(images),
                    "note": f"{len(images)} overlay(s) for camera "
                            f"'{camera_dir.name}': {OVERLAY_NOTE}",
                    "images": [f"capture/overlays/{camera_dir.name}/"
                               f"{p.name}" for p in images],
                })
    sheets = out_dir / "capture" / "contact_sheets"
    if sheets.is_dir():
        for sheet in sorted(sheets.glob("*.png")):
            entries.append({
                "name": f"capture/contact_sheets/{sheet.name}",
                "bytes": sheet.stat().st_size,
                "note": f"{CONTACT_SHEET_NOTE} ('{sheet.stem}')",
                "sheet": True,
            })
    previews = out_dir / "capture" / "previews"
    if previews.is_dir():
        for camera_dir in sorted(p for p in previews.iterdir() if p.is_dir()):
            images = sorted(camera_dir.glob("preview_*.png"))
            if images:
                entries.append({
                    "name": f"capture/previews/{camera_dir.name}",
                    "count": len(images),
                    "note": f"{len(images)} geometry preview(s) for "
                            f"camera '{camera_dir.name}' (full resolution "
                            f"unless the run asked for a scale; not frames)",
                    "images": [f"capture/previews/{camera_dir.name}/"
                               f"{p.name}" for p in images],
                })
    return entries


def frame_set(files: List[Dict]) -> List[str]:
    """The frame set, by name: every rendered PNG the listing carries
    under capture/frames/<camera_id>/ and each camera's render.json (the
    applied pose and time per frame). Built from the SAME listing the
    download whitelist is built from, so frames.zip cannot carry a file
    the page does not list, nor list one it cannot serve."""
    names: List[str] = []
    for entry in files:
        if not entry["name"].startswith("capture/frames/"):
            continue
        if "images" in entry:
            names.extend(entry["images"])
        elif entry["name"].endswith("/render.json"):
            names.append(entry["name"])
    return names


def render_word(out_dir: Path) -> Optional[str]:
    """The run's recorded render choice ("frames" | "clip" | "none")
    from provenance.json, or None when the run left no provenance."""
    path = Path(out_dir) / "provenance.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("render")
    except (OSError, ValueError):
        return None


#: Why there is no frame set, by the run's own render word.
NO_FRAMES_WORDS = {
    "none": "no rendered frames: this was a headless run (no engine pass); "
            "the manifest and the previews are its deliverable",
    "clip": "no rendered frames: this was a clip-only run; choose "
            "'Render frames and clip' for the frame set",
    "frames": "no rendered frames: the engine pass wrote none (the run's "
              "status names the failure)",
}


def frames_zip_refusal(out_dir: Path, files: List[Dict]) -> Optional[str]:
    """The named reason there is no frames.zip to serve, or None when at
    least one rendered PNG is listed. A frames zip with nothing in it
    would be a frame set that is not there."""
    if any(name.endswith(".png") for name in frame_set(files)):
        return None
    return NO_FRAMES_WORDS.get(render_word(out_dir),
                               "no rendered frames in this run")


def run_galleries(out_dir: Path, files: Optional[List[Dict]] = None) -> List[Dict]:
    """One gallery per camera for the page: the manifest's records
    (index and t_s) matched against the files the listing carries.
    ``frames`` names only rendered PNGs on disk (each with its overlay
    when one exists), ``previews`` only preview PNGs on disk, so a
    count the page shows for either is the number of files it can
    open; ``scheduled`` is the manifest's record count for the camera.
    No manifest, no galleries."""
    out_dir = Path(out_dir)
    manifest_path = out_dir / "capture" / "capture_manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if files is None:
        files = run_artifacts(out_dir)
    on_disk = set()
    sheets = {}
    for entry in files:
        on_disk.update(entry.get("images") or ())
        if entry.get("sheet"):
            sheets[Path(entry["name"]).stem] = entry["name"]
    order = [c.get("camera_id") for c in manifest.get("cameras", [])]
    records: Dict[str, List[Dict]] = {}
    for record in manifest.get("frames", []):
        camera_id = record.get("camera_id")
        if camera_id not in order:
            order.append(camera_id)
        records.setdefault(camera_id, []).append(record)
    galleries = []
    for camera_id in order:
        frames, previews = [], []
        for record in records.get(camera_id, []):
            index = int(record["index"])
            frame = f"capture/frames/{camera_id}/{index:04d}.png"
            overlay = f"capture/overlays/{camera_id}/{index:04d}.png"
            preview = f"capture/previews/{camera_id}/preview_{index:05d}.png"
            if frame in on_disk:
                frames.append({"index": index, "t_s": float(record["t_s"]),
                               "file": frame,
                               "overlay": overlay if overlay in on_disk else None})
            if preview in on_disk:
                previews.append({"index": index, "t_s": float(record["t_s"]),
                                 "file": preview})
        galleries.append({"camera_id": camera_id,
                          "scheduled": len(records.get(camera_id, [])),
                          "frames": frames, "previews": previews,
                          "contact_sheet": sheets.get(camera_id)})
    return galleries


#: The artefact classes, in the order the page's download strip shows
#: them. One button per class the run actually wrote; a class whose
#: file is absent is absent from the strip, never a dead link.
DOWNLOAD_CLASSES = ("frames", "manifest", "verification", "telemetry", "clip",
                    "everything")


def run_downloads(out_dir: Path, files: Optional[List[Dict]] = None) -> List[Dict]:
    """One download per artefact class the run wrote, built from the
    listing the whitelist uses: frames.zip (only when a rendered PNG
    exists), the manifest, the verification report (verify.json: the
    checks the card's table and tally are rendered from), the telemetry
    the manifest describes, the clip, and everything. Each carries the route relative to
    /runs/<id>/, the label, and a note saying what it is and how much
    of it there is -- counted from the listing, never assumed."""
    out_dir = Path(out_dir)
    if files is None:
        files = run_artifacts(out_dir)
    by_name = {f["name"]: f for f in files}
    downloads: List[Dict] = []
    frames = [name for name in frame_set(files) if name.endswith(".png")]
    if frames:
        cameras = sorted({name.split("/")[2] for name in frames})
        downloads.append({
            "class": "frames", "label": "frames.zip", "href": "frames.zip",
            "note": f"{len(frames)} PNG(s) across {len(cameras)} camera(s) "
                    f"({', '.join(cameras)}), named by manifest index, "
                    f"with each camera's render.json"})
    manifest = "capture/capture_manifest.json"
    if manifest in by_name:
        downloads.append({
            "class": "manifest", "label": "manifest",
            "href": f"file/{manifest}",
            "note": f"{manifest}: {ARTIFACT_NOTES[manifest]}"})
    verification = "capture/verify.json"
    if verification in by_name:
        downloads.append({
            "class": "verification", "label": "verify.json",
            "href": f"file/{verification}",
            "note": f"{verification}: {ARTIFACT_NOTES[verification]}"})
    telemetry = "capture/telemetry.json"
    if telemetry in by_name:
        downloads.append({
            "class": "telemetry", "label": "telemetry",
            "href": f"file/{telemetry}",
            "note": f"{telemetry}: {ARTIFACT_NOTES[telemetry]}"})
    if "clip.mp4" in by_name:
        word = render_word(out_dir)
        if word == "frames":
            by_product = frames[0].split("/")[2] if frames else "camera 0"
            note = f"clip.mp4: by-product of '{by_product}' (the frame set is the deliverable)"
        elif word == "clip":
            note = "clip.mp4: the rendered clip (clip only: no frame set)"
        else:
            note = f"clip.mp4: {ARTIFACT_NOTES['clip.mp4']}"
        downloads.append({"class": "clip", "label": "clip.mp4",
                          "href": "file/clip.mp4", "note": note})
    total = sum(len(f["images"]) if "images" in f else 1 for f in files)
    if total:
        downloads.append({
            "class": "everything", "label": "everything (.zip)",
            "href": "bundle.zip",
            "note": f"{total} file(s): every artefact listed below"})
    return downloads
