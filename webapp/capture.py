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
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]

#: Progress sink: one human-readable line per step.
Report = Callable[[str], None]

#: Previews are a convenience, not the data. A long run can schedule more
#: frames than a browser wants thumbnails for, so the page's runs cap the
#: image count and SAY SO -- the manifest always carries every frame.
MAX_PREVIEWS = 60


class CaptureError(RuntimeError):
    """A named capture refusal, carried to the run status verbatim."""

    def __init__(self, constraint: str, message: str) -> None:
        super().__init__(message)
        self.constraint = constraint
        self.message = message


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


def capture_run(spec, out: Path, scene: Dict,
                report: Report = lambda line: None) -> Dict:
    """Run the spec headlessly and write its capture artefacts.

    Writes into ``out/capture``: telemetry.json (this run's own),
    scenario.yaml, run.json, capture_manifest.json, verify.json and one
    geometry preview per scheduled frame (capped, and the cap is
    reported). Returns the summary the page renders.

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
    from core.capture.verify import verify_run
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
    result = run_spec(spec, terrain_ground=terrain_ground)
    columns = result.telemetry.columns

    cameras = spec.cameras or default_cameras(spec)
    tracks: List = []
    schedules: List = []
    try:
        for camera in cameras:
            tracks.append(solve_pose_track(columns, camera, frame))
            schedules.append(solve_schedule(columns, camera, frame))
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
        raise CaptureError(first.constraint, first.message)

    manifest = build_capture_manifest(
        spec, columns, frame, tracks, schedules,
        output_digest=result.output_digest,
        scene={"key": scene.get("key", "flat"),
               "terrain": scene.get("terrain")},
        terrain_sha256=heightfield.digest() if heightfield else None,
        cameras=cameras)
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
                               max_frames=MAX_PREVIEWS)
    capped = len(previews) < total
    report(f"captured {total} frame(s) across {len(cameras)} camera(s)")

    # Verify what was just written, with the SAME verifier the CLI runs
    # -- an independent reimplementation of the projection maths, so a
    # pass means the manifest reproduces itself, not that one code path
    # agrees with itself.
    verification = verify_run(capture_dir)
    # Built ONCE and used for both the file and the page: two
    # constructions of the same report are two chances for the download
    # and the screen to disagree about whether a run verified.
    verdict = {
        "ok": verification.ok,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                   for c in verification.checks],
    }
    (capture_dir / "verify.json").write_text(
        json.dumps(verdict, indent=1), encoding="utf-8")
    report(f"verification {'PASSED' if verification.ok else 'FAILED'} "
           f"({sum(c.ok for c in verification.checks)}/"
           f"{len(verification.checks)} checks)")

    return {
        "frames": total,
        "cameras": [{"camera_id": s.camera_id, "frames": len(s)}
                    for s in schedules],
        "previews": len(previews),
        "previews_capped": capped,
        "preview_cap": MAX_PREVIEWS if capped else None,
        "verification": verdict,
    }


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
    "capture/verify.json": "the five verification checks, as run",
    "capture/telemetry.json":
        "the headless flight the manifest describes",
    "capture/scenario.yaml": "the spec as captured",
    "capture/run.json": "spec and output digests of the capture run",
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
                 "render.log", "capture/capture_manifest.json",
                 "capture/verify.json", "capture/telemetry.json",
                 "capture/scenario.yaml", "capture/run.json"):
        path = out_dir / name
        if path.is_file():
            entries.append({"name": name, "bytes": path.stat().st_size,
                            "note": ARTIFACT_NOTES.get(name, "")})
    previews = out_dir / "capture" / "previews"
    if previews.is_dir():
        for camera_dir in sorted(p for p in previews.iterdir() if p.is_dir()):
            images = sorted(camera_dir.glob("*.png"))
            if images:
                entries.append({
                    "name": f"capture/previews/{camera_dir.name}",
                    "count": len(images),
                    "note": f"{len(images)} geometry preview(s) for "
                            f"camera '{camera_dir.name}'",
                    "images": [f"capture/previews/{camera_dir.name}/"
                               f"{p.name}" for p in images],
                })
    return entries
