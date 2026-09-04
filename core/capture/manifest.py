"""The capture manifest: every frame's geometry, whether or not pixels exist.

``capture_manifest.json`` is written for EVERY captured run, on every
platform -- the Linux/Windows half produces it from telemetry alone, and
the macOS render adds pixels beside it without touching it. A frame
without recorded geometry is unusable as labeled data; this file is the
label.

Schema (``manifest_version`` 1)
-------------------------------
Top level::

    manifest_version   1
    spec_digest        SHA-256 of the canonical spec (spec.digest())
    simulation_digest  SHA-256 of the spec with its CAMERAS REMOVED --
                       the "simulation identity": two runs that differ
                       only in cameras share it, which is what the
                       temporal-alignment check keys on
    output_digest      SHA-256 over the recorded telemetry columns
                       (core.scenario.runner._digest_telemetry)
    seed               the spec's random seed
    rate_hz            the spec's fixed-step rate (spec.rate): the grid
                       every capture instant lies on, and the engine's
                       step the verifier grades render.json's step_s
                       against -- the engine never declares its own
                       tolerance
    step_s             1 / rate_hz
    speed_basis        where each frame's aircraft.speed_mps came from
                       (the recorded tas_kt channel, or the ground speed
                       of the recorded track when no airspeed channel
                       exists)
    scene              {key, terrain, terrain_sha256} -- terrain_sha256
                       is the SHA-256 of the raw .r16 samples
                       (Heightfield.digest()), null for flat scenes
    frame              SceneFrame.provenance(): the CRS every position
                       in this file is expressed in, and the projected
                       origin of the local north/east metres
    software_revision  git revision of the producing tree ("unknown"
                       outside a checkout; informational, in no digest)
    cameras            [per-camera blocks]
    frames             [per-frame records, all cameras, capture order]

Per camera: the full CameraSpec dict (fields + moves), the preset's
``horizon_stable`` flag, the capture schedule's basis string, and the
pose-track digest.

Per frame::

    index              frame number within ITS camera, 0-based
    camera_id
    file               relative image path, per-camera subdirectory,
                       NAMED BY THE FRAME'S INDEX
                       ("frames/<camera_id>/0042.png") -- the render
                       commandlet's consume-poses pass writes exactly
                       this file for exactly this record, so a PNG and
                       its geometry are tied by name, never by a
                       running counter
    t_s                simulation time (the telemetry sample's own t)
    sample_index       index into the telemetry record
    position_north_m / position_east_m / position_alt_m
                       camera position, local scene metres + MSL
    quaternion_wxyz    camera orientation, NED frame
    yaw_deg / pitch_deg / roll_deg
                       the same orientation as aerospace Euler angles
    focal_length_mm / sensor_width_mm / sensor_height_mm
    width_px / height_px / near_m / far_m
    principal_point_px [cx, cy] = the image centre
    fx_px / fy_px      focal length in pixels (focal/sensor * pixels)
    aircraft           {north_m, east_m, alt_m, roll_deg, pitch_deg,
                       heading_deg, speed_mps} at the same instant --
                       speed_mps x step_s is one fixed step of this
                       run's travel, the unit of the engine-parity
                       drawn-aircraft budget

Projection (reconstructible, and reconstructed independently by the
verifier): world point P (north, east, alt) in this file's frame;
camera at C with unit axes forward/right/up from the quaternion
(or yaw/pitch/roll); camera coordinates::

    x_cam = right . (P - C)      # image x, rightward
    y_cam = -up . (P - C)        # image y, downward
    z_cam = forward . (P - C)    # depth

    u = cx + fx_px * x_cam / z_cam
    v = cy + fy_px * y_cam / z_cam

A consumer MUST check ``manifest_version`` before parsing; a version it
does not know is a refusal, not a guess (the Heightfield sidecar's own
convention).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .poses import PoseTrack, SceneFrame, aircraft_local_track
from .schedule import CaptureSchedule, off_grid_instants

MANIFEST_VERSION = 1


def software_revision(repo: Optional[Path] = None) -> str:
    """The producing tree's git revision; "unknown" outside a checkout.
    Informational provenance only -- it enters no digest."""
    repo = repo or Path(__file__).resolve().parents[2]
    try:
        probe = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if probe.returncode != 0:
        return "unknown"
    return probe.stdout.strip() or "unknown"


def simulation_digest(spec) -> str:
    """The spec digest with cameras EXCLUDED: the simulation identity.

    Two runs whose specs differ only in cameras command the same
    simulation; their telemetry digests must match, and the alignment
    verifier keys frame times on this value.
    """
    import hashlib

    payload = spec.to_dict()
    payload.pop("prompt", None)
    payload.pop("notes", None)
    payload.pop("cameras", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def frame_filename(camera_id: str, index: int) -> str:
    """Relative image path, per-camera subdirectory, named by the
    frame's manifest index (``0000.png`` ...). The renderer that
    produces pixels writes THIS path (the commandlet's consume-poses
    pass names its PNG by the same index); headless manifests carry it
    as the name the frame would have."""
    return f"frames/{camera_id}/{index:04d}.png"


def build_capture_manifest(spec, columns: Dict[str, Sequence[float]],
                           frame: SceneFrame,
                           tracks: Sequence[PoseTrack],
                           schedules: Sequence[CaptureSchedule],
                           output_digest: str,
                           scene: Optional[Dict] = None,
                           terrain_sha256: Optional[str] = None,
                           cameras=None) -> Dict:
    """Assemble the manifest mapping (see the module docstring schema).

    ``tracks`` and ``schedules`` are parallel per-camera sequences from
    the solver and scheduler. Everything is taken verbatim -- this
    function derives no geometry of its own beyond pixel-unit focal
    lengths, which are pure arithmetic on the recorded intrinsics.
    ``cameras`` names the CameraSpecs that actually flew when they are
    not the spec's own (a camera-less spec captured with the documented
    default cameras); the digests stay the spec's.
    """
    if len(tracks) != len(schedules):
        raise ValueError(
            f"{len(tracks)} pose tracks against {len(schedules)} "
            f"schedules; every camera needs exactly one of each")
    aircraft = aircraft_local_track(columns, frame)
    rate_hz = float(spec.rate.value)
    if not (rate_hz > 0.0):
        raise ValueError(f"spec rate {rate_hz!r} Hz is not a fixed-step "
                         f"grid; refusing a manifest with no clock")
    for schedule in schedules:
        off = off_grid_instants(schedule.times, rate_hz)
        if off:
            raise ValueError(
                f"camera.schedule: camera {schedule.camera_id!r} schedules "
                f"{len(off)} instant(s) off the {rate_hz:g} Hz fixed-step "
                f"grid (first: t={off[0]:.6f} s); the engine captures on "
                f"fixed steps only and never approximates an instant")
    flown = spec.cameras if cameras is None else list(cameras)
    cameras_by_id = {str(c.camera_id.value): c for c in flown}

    camera_blocks: List[Dict] = []
    frames: List[Dict] = []
    for track, schedule in zip(tracks, schedules):
        if track.camera_id != schedule.camera_id:
            raise ValueError(
                f"pose track {track.camera_id!r} paired with schedule "
                f"{schedule.camera_id!r}; refusing a misattributed "
                f"manifest")
        camera = cameras_by_id.get(track.camera_id)
        camera_blocks.append({
            "camera_id": track.camera_id,
            "preset": track.preset,
            "horizon_stable": track.horizon_stable,
            # The declared exception, stated per camera exactly as the
            # render manifest states it for the shoulder preset.
            "inherits_roll": not track.horizon_stable,
            "spec": camera.to_dict() if camera is not None else None,
            "schedule_basis": schedule.basis,
            "trigger": schedule.trigger,
            "capture_count": len(schedule),
            "pose_track_digest": track.digest(),
        })
        fx = (track.width_px / track.sensor_width_mm)
        fy = (track.height_px / track.sensor_height_mm)
        for number, sample_index in enumerate(schedule.indices):
            pose = track.sample(sample_index)
            state = aircraft[sample_index]
            frames.append({
                "index": number,
                "camera_id": track.camera_id,
                "file": frame_filename(track.camera_id, number),
                "t_s": pose["t_s"],
                "sample_index": sample_index,
                "position_north_m": pose["position_north_m"],
                "position_east_m": pose["position_east_m"],
                "position_alt_m": pose["position_alt_m"],
                "quaternion_wxyz": pose["quaternion_wxyz"],
                "yaw_deg": pose["yaw_deg"],
                "pitch_deg": pose["pitch_deg"],
                "roll_deg": pose["roll_deg"],
                "focal_length_mm": pose["focal_length_mm"],
                "sensor_width_mm": track.sensor_width_mm,
                "sensor_height_mm": track.sensor_height_mm,
                "width_px": track.width_px,
                "height_px": track.height_px,
                "near_m": track.near_m,
                "far_m": track.far_m,
                "principal_point_px": [track.width_px / 2.0,
                                       track.height_px / 2.0],
                "fx_px": pose["focal_length_mm"] * fx,
                "fy_px": pose["focal_length_mm"] * fy,
                "aircraft": {
                    "north_m": state["north_m"],
                    "east_m": state["east_m"],
                    "alt_m": state["alt_m"],
                    "roll_deg": state["roll_deg"],
                    "pitch_deg": state["pitch_deg"],
                    "heading_deg": state["heading_deg"],
                    "speed_mps": state["speed_mps"],
                },
            })

    return {
        "manifest_version": MANIFEST_VERSION,
        "spec_digest": spec.digest(),
        "simulation_digest": simulation_digest(spec),
        "output_digest": output_digest,
        "seed": int(spec.seed.value),
        "rate_hz": rate_hz,
        "step_s": 1.0 / rate_hz,
        "speed_basis": aircraft[0]["speed_basis"] if aircraft else None,
        "scene": {
            "key": (scene or {}).get("key", "flat"),
            "terrain": (scene or {}).get("terrain"),
            "terrain_sha256": terrain_sha256,
        },
        "frame": frame.provenance(),
        "software_revision": software_revision(),
        "cameras": camera_blocks,
        "frames": frames,
    }


def write_capture_manifest(manifest: Dict, directory) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "capture_manifest.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path


def read_capture_manifest(path) -> Dict:
    """Load and version-check a manifest; refuses unknown versions."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    version = manifest.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ValueError(
            f"capture manifest version {version!r} is not supported by "
            f"this build (expects {MANIFEST_VERSION}); refusing to "
            f"guess at the schema")
    return manifest
