"""The capture manifest: every frame's geometry, whether or not pixels exist.

``capture_manifest.json`` is written for EVERY captured run, on every
platform -- the Linux/Windows half produces it from telemetry alone, and
the macOS render adds pixels beside it without touching it. A frame
without recorded geometry is unusable as labeled data; this file is the
label.

Schema (``manifest_version`` 4)
-------------------------------
Top level::

    manifest_version   4
    spec_digest        SHA-256 of the canonical spec (spec.digest())
    simulation_digest  SHA-256 of the spec with its CAMERAS REMOVED --
                       the "simulation identity": two runs that differ
                       only in cameras share it, which is what the
                       temporal-alignment check keys on
    output_digest      SHA-256 over the recorded telemetry columns
                       (core.scenario.runner._digest_telemetry) -- of
                       the flight named by ``solve_source``
    solve_source       WHICH FLIGHT the aircraft labels describe:
                       "host flight" when the UE host flew the card
                       first and the poses were solved over ITS
                       telemetry, "headless pre-run" when they were
                       solved over the Python-side flight. Version 2
                       could not say, and always meant the latter --
                       which on a rendered run put the labels 1.38 m
                       from the flight the pixels showed. A consumer
                       training on these images needs to know which it
                       has, so version 3 makes every manifest answer.
    seed               the spec's random seed
    aircraft           the airframe that flew
    scene              {key, terrain, terrain_sha256} -- terrain_sha256
                       is the SHA-256 of the raw .r16 samples
                       (Heightfield.digest()), null for flat scenes
    frame              SceneFrame.provenance(): the CRS every position
                       in this file is expressed in, and the projected
                       origin of the local north/east metres
    software_revision  git revision of the producing tree ("unknown"
                       outside a checkout; informational, in no digest)
    landmarks          known STATIC world points (the terrain raster's
                       corners and peak, or the documented flat ring --
                       core.capture.landmarks), each {name, north_m,
                       east_m, alt_m}. They exist so verification has
                       off-axis points that are not the aircraft, and
                       so the render commandlet can project the SAME
                       points through its own world-to-pixel helper for
                       the engine-parity comparison.
    conditions         the CONDITIONS THE RUN WAS ASKED FOR, as stated:
                       every field of the spec's ``initial`` and
                       ``environment`` sections (wind speed and
                       direction, turbulence, surface, weather date and
                       event, the initial altitude/airspeed/heading)
                       with its unit and its source. This is the
                       request; the per-frame ``state`` below is what
                       the flight actually measured at each instant.
    state_units        {channel: unit} for every key a frame's ``state``
                       carries, derived once from the recorder's naming
                       convention, so a consumer never has to guess
                       whether a number is metres or feet
    cameras            [per-camera blocks]
    frames             [per-frame records, all cameras, capture order]

Per camera: the full CameraSpec dict (fields + moves), the preset's
``horizon_stable`` flag, the capture schedule's basis string, and the
pose-track digest.

Per frame::

    index              frame number within ITS camera, 0-based
    camera_id
    file               relative image path, per-camera subdirectory
                       ("frames/<camera_id>/frame_0042.png") -- where
                       pixels were produced they land exactly there
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
                       heading_deg} at the same instant
    state              EVERY channel the flight recorder logged at that
                       instant -- the whole telemetry row at
                       ``sample_index``, keyed by channel name. Version
                       3 kept six numbers and dropped the rest on the
                       floor; the host's recorder logs about thirty per
                       sample (the wind vector, ground velocity, alpha
                       and beta, dynamic pressure, lift/drag/side force,
                       load factor, control surface positions, flight
                       path angle, height above ground, the geographic
                       position), all measured on the flight named by
                       ``solve_source``. Units per key are in the
                       top-level ``state_units``. Which channels are
                       present depends on which recorder flew (the
                       headless and host recorders overlap but are not
                       identical), so a consumer reads the keys rather
                       than assuming a fixed set.

A per-frame SIDECAR, ``frames/<camera_id>/frame_0042.json``, is written
beside each image (write_frame_sidecars): the frame's own record plus
the top-level context it is meaningless without. A PNG and its sidecar
together are a self-describing labelled sample; they are what the
per-view zip download packs.

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

from .landmarks import scene_landmarks
from .poses import PoseTrack, SceneFrame, aircraft_local_track
from .schedule import CaptureSchedule

MANIFEST_VERSION = 4
#: Versions this build can READ. Every version here is fully
#: interpretable by the current verifier and the page; a version 3
#: manifest simply has no ``state`` on its frames. Anything else is a
#: refusal, not a guess.
SUPPORTED_MANIFEST_VERSIONS = (3, 4)

#: Which flight the ``aircraft`` block in every frame record describes.
#: A v2 manifest could not say, and the answer matters more than any
#: other single field in the file: it is the difference between labels
#: that describe the flight the pixels show and labels that describe a
#: different, very similar flight.
SOLVE_PRE_RUN = "headless pre-run"
SOLVE_HOST_FLIGHT = "host flight"
SOLVE_SOURCES = (SOLVE_PRE_RUN, SOLVE_HOST_FLIGHT)


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


#: The recorder's naming convention, read back as a unit. Both recorders
#: (core.telemetry.recorder.DEFAULT_CHANNELS and the UE
#: FlightSimTelemetryRecorder) name a channel by its quantity and its
#: unit suffix -- ``wind_north_mps``, ``qbar_pa``, ``lift_n`` -- so the
#: unit is recoverable from the name alone. Longest suffix first, so
#: ``_mps`` is not read as ``_s``.
_UNIT_SUFFIXES = (
    ("_dps", "deg/s"), ("_mps", "m/s"), ("_rad", "rad"), ("_deg", "deg"),
    ("_kt", "kt"), ("_kg", "kg"), ("_pa", "Pa"), ("_m", "m"), ("_n", "N"),
    ("_s", "s"),
)
#: Channels whose name carries no unit because they have none.
_DIMENSIONLESS = frozenset({"t", "mach", "n_z", "throttle_cmd"})


def channel_unit(name: str) -> str:
    """The unit of a recorded channel, from its name.

    ``t`` is seconds; ``mach``, ``n_z`` (load factor, in g) and
    ``throttle_cmd`` (normalised 0..1) carry no suffix and are stated
    here. Anything unrecognised is reported as ``"?"`` rather than
    guessed, so a new channel with an unconventional name shows up as
    a question in the manifest instead of a silent wrong unit.
    """
    if name == "t":
        return "s"
    if name == "n_z":
        return "g"
    if name in _DIMENSIONLESS:
        return "1"
    for suffix, unit in _UNIT_SUFFIXES:
        if name.endswith(suffix):
            return unit
    return "?"


def frame_state(columns: Dict[str, Sequence[float]], index: int) -> Dict:
    """EVERY recorded channel at one sample: the whole telemetry row.

    Nothing is selected out. The six values the ``aircraft`` block
    carries are what the pose solver and the verifier consume; this is
    what the flight recorder measured, and a consumer training on the
    images decides what matters, not this function.
    """
    return {name: float(values[index]) for name, values in columns.items()}


def state_units(columns: Dict[str, Sequence[float]]) -> Dict[str, str]:
    return {name: channel_unit(name) for name in columns}


def stated_conditions(spec) -> Dict[str, Dict]:
    """The conditions the run was ASKED for, with unit and source.

    The spec's ``initial`` and ``environment`` sections, as stated --
    wind speed and direction, turbulence, surface, weather, the initial
    altitude/airspeed/heading. Per-frame ``state`` is what the flight
    measured; this is what it was commanded to fly in, and the source
    says whether a person stated it, the compiler inferred it, or it
    is the documented default.
    """
    out: Dict[str, Dict] = {}
    for section, name, quantity in spec.quantities():
        if section not in ("initial", "environment"):
            continue
        out[name] = {"value": quantity.value, "unit": quantity.unit,
                     "source": str(quantity.source),
                     "from": quantity.frm}
    return out


def frame_filename(camera_id: str, index: int) -> str:
    """Relative image path, per-camera subdirectory. The renderer that
    produces pixels writes THIS path; headless manifests carry it as
    the name the frame would have."""
    # frame_%04d matches what the render commandlet actually writes
    # (FlightSimRenderCommandlet.cpp) and what the existing gate scripts
    # glob for. The manifest promised a five-digit name no renderer ever
    # produced, so no manifest entry could name a real file.
    return f"frames/{camera_id}/frame_{index:04d}.png"


def build_capture_manifest(spec, columns: Dict[str, Sequence[float]],
                           frame: SceneFrame,
                           tracks: Sequence[PoseTrack],
                           schedules: Sequence[CaptureSchedule],
                           output_digest: str,
                           scene: Optional[Dict] = None,
                           terrain_sha256: Optional[str] = None,
                           cameras=None,
                           heightfield=None,
                           terrain_elevation_m: float = 0.0,
                           solve_source: str = SOLVE_PRE_RUN) -> Dict:
    """Assemble the manifest mapping (see the module docstring schema).

    ``tracks`` and ``schedules`` are parallel per-camera sequences from
    the solver and scheduler. Everything is taken verbatim -- this
    function derives no geometry of its own beyond pixel-unit focal
    lengths, which are pure arithmetic on the recorded intrinsics.
    ``cameras`` names the CameraSpecs that actually flew when they are
    not the spec's own (a camera-less spec captured with the documented
    default cameras); the digests stay the spec's.
    """
    if solve_source not in SOLVE_SOURCES:
        raise ValueError(
            f"solve_source {solve_source!r} is not one of "
            f"{SOLVE_SOURCES}; the manifest has to say which flight its "
            f"aircraft labels describe, and guessing is what version 2 "
            f"did")
    if len(tracks) != len(schedules):
        raise ValueError(
            f"{len(tracks)} pose tracks against {len(schedules)} "
            f"schedules; every camera needs exactly one of each")
    aircraft = aircraft_local_track(columns, frame)
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
                },
                # The whole recorded row at this instant. The six
                # above are the solver's; this is the recorder's.
                "state": frame_state(columns, sample_index),
            })

    return {
        "manifest_version": MANIFEST_VERSION,
        "spec_digest": spec.digest(),
        "simulation_digest": simulation_digest(spec),
        "output_digest": output_digest,
        # WHICH FLIGHT the aircraft labels describe. See
        # SOLVE_PRE_RUN / SOLVE_HOST_FLIGHT.
        "solve_source": solve_source,
        "seed": int(spec.seed.value),
        # Which airframe flew. The preview draws the real dimensions of
        # THIS aircraft rather than one silhouette scaled by eye, and a
        # downstream consumer needs it to know what the labels label.
        "aircraft": str(spec.aircraft.value),
        "scene": {
            "key": (scene or {}).get("key", "flat"),
            "terrain": (scene or {}).get("terrain"),
            "terrain_sha256": terrain_sha256,
        },
        "frame": frame.provenance(),
        "software_revision": software_revision(),
        "landmarks": scene_landmarks(
            frame, aircraft_track=aircraft, heightfield=heightfield,
            terrain_elevation_m=terrain_elevation_m),
        "conditions": stated_conditions(spec),
        "state_units": state_units(columns),
        "cameras": camera_blocks,
        "frames": frames,
    }


def write_capture_manifest(manifest: Dict, directory) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "capture_manifest.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path


#: What a frame's sidecar carries besides the frame's own record: the
#: top-level context the record is meaningless without. Not the
#: landmarks (tens of entries, identical in every sidecar -- the
#: per-camera manifest has them) and not the other cameras.
SIDECAR_CONTEXT_KEYS = (
    "manifest_version", "spec_digest", "simulation_digest",
    "output_digest", "solve_source", "seed", "aircraft", "scene",
    "frame", "software_revision", "conditions", "state_units",
)


def frame_sidecar_name(file: str) -> str:
    """``frames/<camera_id>/frame_0042.png`` -> ``.../frame_0042.json``."""
    if not file.endswith(".png"):
        raise ValueError(f"not a frame image path: {file!r}")
    return file[:-len(".png")] + ".json"


def frame_sidecar(manifest: Dict, record: Dict) -> Dict:
    """One frame, self-describing: its record plus the run context and
    ITS camera's block. A PNG and this file together are a labelled
    sample that needs nothing else."""
    cameras = {str(c.get("camera_id")): c
               for c in manifest.get("cameras", [])}
    return {
        "context": {key: manifest.get(key) for key in SIDECAR_CONTEXT_KEYS},
        "camera": cameras.get(str(record.get("camera_id"))),
        "frame": record,
    }


def write_frame_sidecars(manifest: Dict, directory) -> List[Path]:
    """One ``.json`` beside every frame the manifest names.

    Written whether or not the image exists yet -- the manifest is
    produced on every platform and the pixels only where an engine is
    -- so a headless run's sidecars describe the frames a render WOULD
    produce, exactly as the manifest does. Stale sidecars from an
    earlier render into the same directory are removed first, for the
    same reason the renderer removes stale PNGs: a file the current
    manifest does not name must not sit beside the ones it does.
    """
    directory = Path(directory)
    named = set()
    written: List[Path] = []
    for record in manifest.get("frames", []):
        path = directory / frame_sidecar_name(str(record["file"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(frame_sidecar(manifest, record), indent=1),
                        encoding="utf-8")
        named.add(path.resolve())
        written.append(path)
    for camera_dir in {p.parent for p in written}:
        for stale in camera_dir.glob("frame_*.json"):
            if stale.resolve() not in named:
                stale.unlink()
    return written


def read_capture_manifest(path) -> Dict:
    """Load and version-check a manifest; refuses unknown versions."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    version = manifest.get("manifest_version")
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        raise ValueError(
            f"capture manifest version {version!r} is not supported by "
            f"this build (reads {SUPPORTED_MANIFEST_VERSIONS}, writes "
            f"{MANIFEST_VERSION}); refusing to guess at the schema")
    return manifest
