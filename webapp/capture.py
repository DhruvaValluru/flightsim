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

from core.capture.hostflight import HostFlightError
from core.capture.manifest import SOLVE_HOST_FLIGHT, SOLVE_PRE_RUN

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


def clip_columns(columns: Dict, duration_s: Optional[float]) -> Dict:
    """The recorded flight, cut to the window the host will actually fly.

    The web run caps its clip at CLIP_SECONDS while the SPEC keeps its
    own duration, and the headless pre-run flies the spec's. Solving
    capture schedules over the full flight therefore laid capture
    instants out past the end of the clip, and the render commandlet
    refused -- correctly, and only once it had flown:

        consume-poses: emitted 3 of the 4 scheduled images; the run
        ended before the schedule did, so the manifest would name
        frames that do not exist

    A manifest naming frames that cannot exist is the exact failure this
    phase is about, so the schedule is cut to fit the flight rather than
    the flight stretched to fit the schedule. The CLI never hit this
    because it caps nothing: its host flies the spec's own duration.
    """
    if duration_s is None:
        return columns
    times = [float(t) for t in columns["t"]]
    keep = sum(1 for t in times if t <= duration_s)
    if keep >= len(times) or keep < 2:
        return columns
    return {name: list(values)[:keep] for name, values in columns.items()}


def solve(spec, scene: Dict, heightfield=None, terrain_ground=None,
          tornado: Optional[Dict] = None,
          duration_s: Optional[float] = None):
    """Fly headlessly, solve every camera, and return everything the
    render and the manifest need.

    ``duration_s`` is the window the HOST will fly (the clip cap), which
    is not always the spec's own duration -- see :func:`clip_columns`.

    Raises :class:`CaptureError` with the named camera constraint rather
    than rendering frames whose geometry was never validated.
    """
    from core.capture.poses import PoseSolveError, SceneFrame, solve_pose_track
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.capture.validate import track_violations
    from core.scenario.runner import run_spec

    frame = SceneFrame.for_spec(spec, heightfield)
    result = run_spec(spec, terrain_ground=terrain_ground)
    columns = clip_columns(result.telemetry.columns, duration_s)
    datum = float(spec.terrain_elevation.value)
    tracks, schedules = _solve_cameras(
        spec, columns, frame, heightfield, tornado, datum)
    return {"frame": frame, "columns": columns, "tracks": tracks,
            "schedules": schedules, "result": result,
            "terrain_elevation_m": datum,
            "solve_source": SOLVE_PRE_RUN,
            "output_digest": result.output_digest}


def _solve_cameras(spec, columns, frame, heightfield, tornado, datum):
    """Pose tracks and schedules over ONE recorded flight, scene-checked.

    Pulled out of :func:`solve` so it can run twice: once over the
    headless pre-run as the cheap pre-flight gate, and once over the
    host's own flight for the labels that ship (:func:`resolve_over_host`).
    """
    from core.capture.poses import PoseSolveError, solve_pose_track
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.capture.validate import track_violations

    tracks, schedules = [], []
    try:
        for camera in spec.cameras:
            tracks.append(solve_pose_track(columns, camera, frame))
            schedules.append(solve_schedule(columns, camera, frame))
    except (ScheduleError, PoseSolveError) as exc:
        raise CaptureError(getattr(exc, "constraint", "camera.schedule"),
                           str(exc)) from exc

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
    return tracks, schedules


def resolve_over_host(spec, solved: Dict, host_telemetry, heightfield=None,
                      tornado: Optional[Dict] = None,
                      duration_s: Optional[float] = None) -> Dict:
    """Re-solve everything over the flight the HOST actually flew.

    The web run used to solve its poses over the headless pre-run and
    then let the render host fly the scenario again -- two builds of
    JSBSim stepping one scenario, 1.38 m apart, so the aircraft states
    in every frame record described a flight the pixels did not show.
    The CLI closed that in 129f140 by flying the host first; this is the
    same move on the web path, and for the same reason: the web app is
    where these images are actually looked at.

    The pre-run is not wasted. It stays the cheap pre-flight gate, so a
    camera inside a mountain refuses BEFORE an engine pass is spent; it
    just stops being the source of the labels. The scene checks run
    again here, because the host's track is the flight the frames are
    taken on.
    """
    from core.capture.hostflight import (
        digest_columns, read_all_host_columns, read_host_record,
    )

    try:
        # The WHOLE record, not the solver's seven: every frame's
        # ``state`` is cut from these columns, and the wind, the
        # velocities and the aero forces the host logged at each
        # instant are the labels a consumer actually asked for.
        columns = clip_columns(read_host_record(host_telemetry), duration_s)
        digest = digest_columns(read_all_host_columns(host_telemetry))
    except HostFlightError as exc:
        raise CaptureError(exc.constraint, exc.message) from exc

    tracks, schedules = _solve_cameras(
        spec, columns, solved["frame"], heightfield, tornado,
        solved["terrain_elevation_m"])
    out = dict(solved)
    out.update({"columns": columns, "tracks": tracks,
                "schedules": schedules,
                "solve_source": SOLVE_HOST_FLIGHT,
                "output_digest": digest})
    return out


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
        # -telemetry= per camera, into the camera's OWN directory. The
        # web path used to hand every pass one shared path -- the
        # pre-run's telemetry.json -- so no per-camera host recording
        # existed and flight_agreement, which keys them by directory,
        # reported NOT RUN on every web run ever made.
        # -labels: the engine's masks, depth and occlusion beside every
        # frame (Phase 10). Only the camera path passes it; the
        # camera-less path's arguments stay pinned byte-identical.
        ok = render(card=card, frames=out,
                    extra=[f"-camera-index={index}", "-labels"],
                    telemetry=out / "host_telemetry.json", **render_kwargs)
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
        write_frame_sidecars,
    )

    manifest = build_capture_manifest(
        spec, solved["columns"], solved["frame"], solved["tracks"],
        solved["schedules"],
        # Of the flight the labels were actually solved over: the
        # host's own when it flew first, the headless pre-run when the
        # engine was absent. The manifest says which either way.
        output_digest=solved["output_digest"],
        solve_source=solved["solve_source"],
        scene={"key": scene.get("key", "flat"),
               "terrain": scene.get("terrain")},
        terrain_sha256=heightfield.digest() if heightfield else None,
        cameras=spec.cameras,
        heightfield=heightfield,
        terrain_elevation_m=solved["terrain_elevation_m"])
    path = write_capture_manifest(manifest, out)
    # One JSON beside every PNG, so a downloaded frame carries its own
    # labels and a zip of a view is a labelled set, not a folder of
    # pictures and a manifest to cross-reference by hand.
    write_frame_sidecars(manifest, out)
    return path


#: Everything a labelled set is, per view. The zip is rebuilt when any
#: of these is newer than it, so a re-render or a re-verify refreshes
#: the download and nothing else does.
_ARCHIVE_PATTERNS = ("frame_*.png", "frame_*.json")


def frames_archive(out: Path, camera_id: str) -> Optional[Path]:
    """A zip of ONE view: its frames, each frame's sidecar, the
    per-camera manifest and a README saying what is what.

    Built on disk under ``downloads/<camera_id>.zip`` and reused while
    it is newer than every file it packs. PNGs are STORED -- they are
    already compressed, and deflating 221 of them again would cost
    minutes for nothing -- and the JSON is deflated. Returns None when
    the view has no frames at all, so the route answers 404 rather
    than an empty archive.
    """
    import zipfile

    source = out / "frames" / camera_id
    if not source.is_dir():
        return None
    files = sorted(p for pattern in _ARCHIVE_PATTERNS
                   for p in source.glob(pattern))
    if not any(p.suffix == ".png" or p.suffix == ".json" for p in files):
        return None
    manifest_path = out / "capture_manifest.json"
    inputs = files + ([manifest_path] if manifest_path.is_file() else [])

    archive = out / "downloads" / f"{camera_id}.zip"
    if archive.is_file():
        newest = max(p.stat().st_mtime for p in inputs)
        if archive.stat().st_mtime >= newest:
            return archive
    archive.parent.mkdir(parents=True, exist_ok=True)

    camera_manifest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        camera_manifest = camera_view(manifest, camera_id)

    readme = (
        f"{camera_id}: one view of run {out.name}\n"
        f"\n"
        f"frame_NNNN.png   the rendered frame\n"
        f"frame_NNNN.json  that frame's labels: where the camera was, which\n"
        f"                 way it pointed, the lens; under 'state' every\n"
        f"                 channel the flight recorder logged at that instant\n"
        f"                 (units in context.state_units; the conditions the\n"
        f"                 run was asked for in context.conditions); and under\n"
        f"                 'labels' the ground truth: bbox_2d (px, clipped)\n"
        f"                 and bbox_2d_unclipped, truncation, in_frame, the\n"
        f"                 3-D box in camera coordinates, every keypoint's\n"
        f"                 pixel and camera position, and the horizon line.\n"
        f"                 context.airframe says where each keypoint's number\n"
        f"                 came from; context.label_conventions how to read\n"
        f"                 the frames and the corner order\n"
        f"frame_NNNN_mask.png / _class.png / _depth.png\n"
        f"                 when the render pass was run with -labels: the\n"
        f"                 engine's instance mask (aircraft = 1), class mask\n"
        f"                 (0 sky, 1 aircraft, 2 terrain/other) and 16-bit\n"
        f"                 depth (metres = value x depth_scale_m from that\n"
        f"                 camera's render.json)\n"
        f"manifest.json    this camera's block, all of its frames, the scene's\n"
        f"                 landmarks and the CRS the metres are expressed in\n"
        f"\n"
        f"Positions are local north/east metres about the origin named in\n"
        f"context.frame, altitude in metres MSL. A consumer checks\n"
        f"manifest_version before parsing.\n")

    partial = archive.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w") as zf:
        for path in files:
            method = (zipfile.ZIP_STORED if path.suffix == ".png"
                      else zipfile.ZIP_DEFLATED)
            zf.write(path, arcname=f"{camera_id}/{path.name}",
                     compress_type=method)
        if camera_manifest is not None:
            zf.writestr(f"{camera_id}/manifest.json",
                        json.dumps(camera_manifest, indent=1),
                        compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(f"{camera_id}/README.txt", readme,
                    compress_type=zipfile.ZIP_DEFLATED)
    partial.replace(archive)
    return archive


#: Top-level keys a per-camera view carries alongside its own block and
#: frames: the context the records are meaningless without.
CAMERA_VIEW_KEYS = (
    "manifest_version", "spec_digest", "simulation_digest",
    "output_digest", "solve_source", "seed", "aircraft", "scene",
    "frame", "landmarks", "software_revision", "conditions",
    "state_units",
)


def camera_view(manifest: Dict, camera_id: str) -> Optional[Dict]:
    """ONE camera's labels out of the whole-run manifest, or None when
    the run has no such camera. Shared by the manifest route and the
    zip, so the two cannot disagree about what a view contains."""
    blocks = [c for c in manifest.get("cameras", [])
              if str(c.get("camera_id")) == camera_id]
    if not blocks:
        return None
    frames = [f for f in manifest.get("frames", [])
              if str(f.get("camera_id")) == camera_id]
    shared = {key: manifest.get(key) for key in CAMERA_VIEW_KEYS}
    return {**shared, "camera": blocks[0], "frames": frames}


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

    # One mp4 per camera: that many seconds of THAT view. Read off the
    # directory like everything else here, so a clip the encoder failed
    # to make is simply absent rather than a broken <video> element.
    clips = (sorted(c.stem for c in (out / "clips").glob("*.mp4"))
             if (out / "clips").is_dir() else [])

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
        "clips": clips,
        "has_manifest": manifest_path.is_file(),
        "has_verify": (out / "verify.json").is_file(),
    }
