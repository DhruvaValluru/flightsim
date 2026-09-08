"""The capture stage of a web run: images with geometry, not just a clip.

Camera Phase 1 built the camera as a spec element and the web page
learned to edit it -- but pressing Run mapped camera[0] back to the old
``-camera=<word>`` / ``-chase=`` preset flags and let C++ recompute the
pose per frame. Of the CameraSpec's 32 fields, four reached the
renderer. Focal length, sensor, resolution, aim mode, keyframed moves
and every capture trigger were accepted by the review table, entered
the digest, and changed nothing about the pixels. No web run wrote a
``capture_manifest.json``, so even the frames that were produced carried
no pose, no intrinsics and no aircraft state.

This module is the other half. For a spec that states cameras the web
run now does what ``flightsim.capture --render`` does:

1. fly the scenario HEADLESSLY to get a telemetry record;
2. solve each camera's pose track and capture schedule over it;
3. write the run card carrying those tracks, the intrinsics and the
   scene's landmarks;
4. render ONE COMMANDLET PASS PER CAMERA (``-camera-index=N``) into
   ``frames/<camera_id>/``, consuming the solved poses verbatim;
5. write ``capture_manifest.json``, the overlays, and the verification
   summary beside them.

The residual, stated rather than hidden: poses are solved over the
headless pre-run while the render host flies the scenario itself. The
camera poses are consumed verbatim so those are exact; the AIRCRAFT
states in the manifest come from the pre-run. ``verify_flight_agreement``
measures that divergence against the host's own recorded telemetry and
fails the run's verification when it matters, instead of leaving it to
be discovered downstream.

A spec with NO cameras keeps the legacy path exactly as it was --
byte-identical commandlet arguments, one clip -- because that argument
list is pinned by test and because a user who never mentioned a camera
should not have their run reshaped.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]


class CaptureError(RuntimeError):
    """The capture stage refused; named, never approximated."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


def wants_capture(spec) -> bool:
    """True when the user actually stated cameras. A camera-less spec is
    left on the legacy path."""
    return bool(getattr(spec, "cameras", None))


def solve(spec, scene: Dict, heightfield=None, terrain_ground=None,
          tornado: Optional[Dict] = None):
    """Fly headlessly, solve every camera, and return everything the
    render and the manifest need.

    Raises :class:`CaptureError` with the named camera constraint rather
    than rendering frames whose geometry was never validated.
    """
    from core.capture.poses import PoseSolveError, SceneFrame, solve_pose_track
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.capture.validate import track_violations
    from core.scenario.runner import run_spec

    frame = SceneFrame.for_spec(spec, heightfield)
    result = run_spec(spec, terrain_ground=terrain_ground)
    columns = result.telemetry.columns

    tracks, schedules = [], []
    try:
        for camera in spec.cameras:
            tracks.append(solve_pose_track(columns, camera, frame))
            schedules.append(solve_schedule(columns, camera, frame))
    except (ScheduleError, PoseSolveError) as exc:
        raise CaptureError(getattr(exc, "constraint", "camera.schedule"),
                           str(exc)) from exc

    datum = float(spec.terrain_elevation.value)
    violations = []
    for track in tracks:
        violations.extend(track_violations(
            track, heightfield=heightfield, scene_frame=frame,
            tornado=tornado, terrain_elevation_m=datum))
    if violations:
        first = violations[0]
        raise CaptureError(
            getattr(first, "constraint", "camera.track"),
            "; ".join(v.render() if hasattr(v, "render") else str(v)
                      for v in violations))
    return {"frame": frame, "columns": columns, "tracks": tracks,
            "schedules": schedules, "result": result,
            "terrain_elevation_m": datum}


def card_blocks(spec, solved: Dict) -> List[Dict]:
    """The card's ``cameras`` entries: spec fields plus the solved
    per-sample pose track, consumed verbatim by the commandlet."""
    return [track.card_block(camera, schedule, solved["frame"])
            for camera, track, schedule
            in zip(spec.cameras, solved["tracks"], solved["schedules"])]


def landmarks(spec, solved: Dict, heightfield=None) -> List[Dict]:
    from core.capture.landmarks import scene_landmarks
    from core.capture.poses import aircraft_local_track

    return scene_landmarks(
        solved["frame"],
        aircraft_track=aircraft_local_track(solved["columns"],
                                            solved["frame"]),
        heightfield=heightfield,
        terrain_elevation_m=solved["terrain_elevation_m"])


def render_passes(card: Path, frames_root: Path, camera_ids: List[str],
                  render: Callable[..., bool], **render_kwargs) -> List[str]:
    """One commandlet pass per camera, each into its own directory.

    ``render`` is the caller's own render function (the webapp's, so the
    engine flags, the scene arguments and the log all stay in one
    place); this only owns the per-camera loop and the directory layout
    the manifest names.
    """
    rendered = []
    for index, camera_id in enumerate(camera_ids):
        out = frames_root / camera_id
        out.mkdir(parents=True, exist_ok=True)
        for stale in out.glob("frame_*.png"):
            stale.unlink()
        (out / "render.json").unlink(missing_ok=True)
        ok = render(card=card, frames=out,
                    extra=[f"-camera-index={index}"], **render_kwargs)
        if not ok:
            raise CaptureError(
                "camera.render",
                f"the render commandlet produced no render.json for "
                f"camera {camera_id!r} (pass {index + 1} of "
                f"{len(camera_ids)}); see render.log")
        rendered.append(camera_id)
    return rendered


def write_manifest(spec, solved: Dict, out: Path, scene: Dict,
                   heightfield=None) -> Path:
    from core.capture.manifest import (
        build_capture_manifest, write_capture_manifest,
    )

    manifest = build_capture_manifest(
        spec, solved["columns"], solved["frame"], solved["tracks"],
        solved["schedules"],
        output_digest=solved["result"].output_digest,
        scene={"key": scene.get("key", "flat"),
               "terrain": scene.get("terrain")},
        terrain_sha256=heightfield.digest() if heightfield else None,
        cameras=spec.cameras,
        heightfield=heightfield,
        terrain_elevation_m=solved["terrain_elevation_m"])
    return write_capture_manifest(manifest, out)


def finish(out: Path, max_overlays: Optional[int] = 24) -> Dict:
    """Overlays over the rendered frames, then verification. Returns the
    summary the page shows."""
    from core.capture.manifest import read_capture_manifest
    from core.capture.overlay import draw_overlays
    from core.capture.verify import verify_run

    manifest = read_capture_manifest(out / "capture_manifest.json")
    overlays = draw_overlays(manifest, out, max_frames=max_overlays)
    report = verify_run(out)
    summary = {
        "ok": report.ok,
        "checks": [{"name": c.name, "status": c.status, "detail": c.detail}
                   for c in report.checks],
        "overlays": len(overlays),
    }
    (out / "verify.json").write_text(json.dumps(summary, indent=1),
                                     encoding="utf-8")
    return summary


def inventory(out: Path) -> Dict:
    """What images this run actually produced, per camera, for the page.

    Reads the DIRECTORIES, not the manifest: a frame the manifest names
    but the renderer never wrote must not appear as an image the page
    then fails to load.
    """
    def listing(root: Path) -> Dict[str, List[str]]:
        found: Dict[str, List[str]] = {}
        if not root.is_dir():
            return found
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                names = sorted(p.name for p in entry.glob("*.png"))
                if names:
                    found[entry.name] = names
            elif entry.suffix == ".png":
                found.setdefault("", []).append(entry.name)
        return found

    manifest_path = out / "capture_manifest.json"
    cameras: List[Dict] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        for block in manifest.get("cameras", []):
            cameras.append({
                "camera_id": str(block.get("camera_id", "")),
                "preset": str(block.get("preset", "")),
                "capture_count": int(block.get("capture_count", 0)),
                "trigger": str(block.get("trigger", "")),
                "schedule_basis": str(block.get("schedule_basis", "")),
            })
    return {
        "cameras": cameras,
        "frames": listing(out / "frames"),
        "overlays": listing(out / "overlays"),
        "previews": listing(out / "previews"),
        "has_manifest": manifest_path.is_file(),
        "has_verify": (out / "verify.json").is_file(),
    }
