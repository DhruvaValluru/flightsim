"""The capture manifest: every frame's geometry, whether or not pixels exist.

``capture_manifest.json`` is written for EVERY captured run, on every
platform -- the headless half produces it from telemetry alone, and the
Windows render adds pixels beside it without touching it. A frame
without recorded geometry is unusable as labeled data; this file is the
label.

Schema (``manifest_version`` 6)
-------------------------------
Top level::

    manifest_version   6
    spec_digest        SHA-256 of the canonical spec (spec.digest())
    simulation_digest  SHA-256 of the spec with its CAMERAS REMOVED --
                       the "simulation identity": two runs that differ
                       only in cameras share it, which is what the
                       temporal-alignment check keys on (version 6 also
                       drops the taxonomy: a class list changes no flight)
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
    airframe           the labelled airframe (core.capture.airframe):
                       cited overall dimensions, the CG in JSBSim's
                       structural frame, the 3-D box in the body frame,
                       every keypoint with its body-frame position, its
                       SOURCE and its basis (fdm / fdm-approximation /
                       estimate), and the SHA-256 of the config and the
                       FDM XML the numbers came from
    label_conventions  how to read the per-frame ``labels`` (frames,
                       box model, corner order, horizon model)
    assets             SHA-256 of every asset behind the labels and the
                       pixels that exists on the producing machine:
                       aircraft config, FDM XML, mesh manifest (null
                       with a reason where no mesh is imported), imagery
                       sidecar; the terrain raster's is ``scene.
                       terrain_sha256`` as before
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
    objects            version 6: every labelled object of the scene,
                       composed ONCE from the spec (core.capture.objects):
                       {id, int_id, class, class_id, instance, role,
                       mesh_sha256, licence, in_scene, labelled}. The
                       primary airframe is first (int_id 1), traffic in
                       spec order, then the terrain; the ID image the
                       render writes holds exactly these integers, and
                       the same list rides on the run card
    taxonomy           version 6: the spec's ordered class list
                       (class_id = position + 1; 0 is sky / nothing)
    traffic            version 6: one block per scripted traffic
                       aircraft -- its object ids, spec fields, cited
                       airframe (as ``airframe`` below, for its own
                       type) and the solved track's digest (the track
                       itself rides on the card, as the cameras' do)
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

    sensor             version 5: {profile, angular_rate_rad_s,
                       labels_sensor} -- which sensor model this frame
                       is passed through (the full profile is on the
                       camera block), the camera's angular rate in
                       camera axes (rolling shutter), and the labels
                       mapped onto that sensor's pixels. For the ideal
                       pinhole they equal ``labels``.
    labels             version 5: the ground-truth labels computed from
                       the record above and the airframe block, on
                       every machine (core.capture.labels): bbox_2d and
                       its unclipped form, truncation, in_frame, the
                       3-D box in camera coordinates, every keypoint's
                       pixel and camera position, and the horizon line.
                       The engine's own per-frame outputs -- instance
                       and class masks, depth, occlusion fraction --
                       are written BESIDE the frame by the render
                       commandlet and read by the verifier; they are
                       never in this file, which exists without them.
                       Version 6 adds ``labels.objects[]``: one record
                       per labelled object (core.capture.labels.
                       object_label_record; contracts §3), the primary
                       first with the same values as ``labels``, then
                       each traffic aircraft, then the terrain. Its
                       engine-derived keys (bbox_2d_tight,
                       visible_fraction, occluded_by, depth_min_m,
                       depth_median_m) are null with a stated basis
                       here and are filled in place by
                       core.capture.labels.attach_engine_labels after a
                       render -- the one exception to "never in this
                       file", and it is a post-render step that names
                       the files each number came from.

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
import math
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .airframe import load_airframe
from .labels import (
    camera_axes, conventions as label_conventions, frame_labels,
    object_label_record, projection_matrices,
)
from .objects import (
    ROLE_PRIMARY, ROLE_TRAFFIC, compose_objects, mesh_manifest_path,
    objects_block, taxonomy_classes,
)
from .profile import load_profile, sensor_labels
from .landmarks import scene_landmarks
from .poses import PoseTrack, SceneFrame, aircraft_local_track, traffic_state
from .schedule import CaptureSchedule
from core.scenario.randomization import card_block as randomization_card_block

MANIFEST_VERSION = 6
#: Versions this build can READ. Every version here is fully
#: interpretable by the current verifier and the page: a version 3
#: manifest has no ``state`` on its frames, a version 4 no ``labels``
#: and no ``airframe``, a version 5 no ``objects`` and no per-object
#: label records. Anything else is a refusal, not a guess.
SUPPORTED_MANIFEST_VERSIONS = (3, 4, 5, 6)

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
    # Phase 10 (package 7): the randomisation block changes the sun, the
    # fog, the camera jitter and the livery -- what the frames LOOK like
    # -- and none of the physics; two runs differing only there flew
    # one simulation, and a dataset split keyed on this value keeps
    # them on one side.
    payload.pop("randomization", None)
    # Phase 2 (contracts §12): the taxonomy names the dataset's classes
    # and changes no flight either. Traffic STAYS in: a second aircraft
    # is in the scene the pixels show.
    payload.pop("taxonomy", None)
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


def camera_angular_rate(track: PoseTrack, index: int) -> List[float]:
    """The camera's angular rate at a sample, rad/s, in CAMERA axes
    (x right, y down, z forward) -- what the rolling-shutter model
    needs. From the solved track's neighbouring quaternions: the
    relative rotation q_i^-1 q_{i+1} as an axis-angle over dt, in the
    body frame (forward, right, down), then re-ordered to camera axes.
    The last sample uses the previous interval. A one-sample track
    turns at zero."""
    n = len(track.t)
    if n < 2:
        return [0.0, 0.0, 0.0]
    i0 = index if index + 1 < n else index - 1
    i1 = i0 + 1
    w0, x0, y0, z0 = track.quat[i0]
    w1, x1, y1, z1 = track.quat[i1]
    # q_rel = conj(q0) * q1
    rw = w0 * w1 + x0 * x1 + y0 * y1 + z0 * z1
    rx = w0 * x1 - x0 * w1 - y0 * z1 + z0 * y1
    ry = w0 * y1 + x0 * z1 - y0 * w1 - z0 * x1
    rz = w0 * z1 - x0 * y1 + y0 * x1 - z0 * w1
    if rw < 0.0:
        rw, rx, ry, rz = -rw, -rx, -ry, -rz
    sin_half = math.sqrt(rx * rx + ry * ry + rz * rz)
    dt = float(track.t[i1]) - float(track.t[i0])
    if sin_half < 1e-15 or dt <= 0.0:
        return [0.0, 0.0, 0.0]
    angle = 2.0 * math.atan2(sin_half, min(max(rw, -1.0), 1.0))
    body = (rx / sin_half * angle / dt, ry / sin_half * angle / dt,
            rz / sin_half * angle / dt)      # (forward, right, down)
    return [body[1], body[2], body[0]]      # (right, down, forward)


def _file_sha256(path) -> Optional[str]:
    import hashlib

    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset_digests(spec, airframe, scene: Optional[Dict]) -> Dict:
    """SHA-256 of every asset behind this run's labels and pixels that
    is on the producing machine. A missing one is null WITH A REASON,
    never a hash of nothing: the mesh manifest exists only where the
    asset pipeline has imported the model, and a headless machine has
    honestly not got one."""
    repo = Path(__file__).resolve().parents[2]
    aircraft = str(spec.aircraft.value)
    mesh_manifest = repo / "assets" / "generated" / aircraft / "mesh_manifest.json"
    imagery = (scene or {}).get("imagery")
    return {
        "aircraft_config": {"path": f"assets/aircraft_config/{aircraft}.json",
                            "sha256": airframe.config_sha256},
        "fdm_xml": {"path": airframe.fdm_xml_path,
                    "sha256": airframe.fdm_xml_sha256},
        "mesh_manifest": {
            "path": str(mesh_manifest.relative_to(repo)),
            "sha256": _file_sha256(mesh_manifest),
            "note": (None if mesh_manifest.is_file() else
                     "no mesh imported on the producing machine; the "
                     "render host's own manifest names the mesh it drew")},
        "imagery_sidecar": {
            "path": str(imagery) if imagery else None,
            "sha256": _file_sha256(imagery) if imagery else None},
    }


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
                           solve_source: str = SOLVE_PRE_RUN,
                           traffic_tracks: Optional[Sequence[PoseTrack]] = None,
                           mesh_manifests: Optional[Dict[str, Dict]] = None) -> Dict:
    """Assemble the manifest mapping (see the module docstring schema).

    ``tracks`` and ``schedules`` are parallel per-camera sequences from
    the solver and scheduler. Everything is taken verbatim -- this
    function derives no geometry of its own beyond pixel-unit focal
    lengths, which are pure arithmetic on the recorded intrinsics.
    ``cameras`` names the CameraSpecs that actually flew when they are
    not the spec's own (a camera-less spec captured with the documented
    default cameras); the digests stay the spec's.

    Version 6: ``traffic_tracks`` are the solved tracks of the spec's
    ``traffic[]`` entries, in spec order (``poses.solve_traffic_track``);
    a spec with traffic and no tracks refuses -- a traffic object with
    no track has no state to label. ``mesh_manifests`` (aircraft ->
    the converter's manifest dict) is for tests; by default the
    imported model's manifest is read from ``assets/generated`` where
    it exists, and the hull box is null with a basis where it does not.
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
    # The airframe the labels describe: refused by name (camera.labels)
    # when it has no cited geometry -- a manifest is never written with
    # labels that quietly describe a stand-in.
    airframe = load_airframe(str(spec.aircraft.value))
    flown = spec.cameras if cameras is None else list(cameras)
    cameras_by_id = {str(c.camera_id.value): c for c in flown}
    # Version 6: the scene's labelled objects, composed once (primary
    # first, int_id 1), and the traffic aircraft's own airframes and
    # tracks. A traffic airframe with no cited geometry refuses exactly
    # as the primary does.
    objects = compose_objects(spec)
    traffic_tracks = list(traffic_tracks or [])
    if len(traffic_tracks) != len(spec.traffic):
        raise ValueError(
            f"{len(traffic_tracks)} traffic tracks for {len(spec.traffic)} "
            f"traffic entries; every scripted aircraft needs exactly one "
            f"solved track or it has no state to label")
    traffic_objects = [o for o in objects if o.role == ROLE_TRAFFIC]
    traffic_airframes = [load_airframe(str(entry.aircraft.value))
                         for entry in spec.traffic]
    for track in traffic_tracks:
        if len(track) != len(columns["t"]):
            raise ValueError(
                f"traffic track {track.camera_id!r} has {len(track)} samples "
                f"where the telemetry has {len(columns['t'])}; refusing a "
                f"track solved over a different flight")
    randomization = randomization_card_block(spec)

    def mesh_manifest_for(name: str) -> Optional[Dict]:
        if mesh_manifests is not None:
            return mesh_manifests.get(name)
        path = mesh_manifest_path(name)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    primary_mesh = mesh_manifest_for(str(spec.aircraft.value))
    traffic_meshes = [mesh_manifest_for(str(e.aircraft.value)) for e in spec.traffic]

    camera_blocks: List[Dict] = []
    frames: List[Dict] = []
    for track, schedule in zip(tracks, schedules):
        if track.camera_id != schedule.camera_id:
            raise ValueError(
                f"pose track {track.camera_id!r} paired with schedule "
                f"{schedule.camera_id!r}; refusing a misattributed "
                f"manifest")
        camera = cameras_by_id.get(track.camera_id)
        profile = load_profile(str(camera.profile.value) if camera is not None
                               else "ideal_pinhole")
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
            # Phase 10: the sensor model, every parameter and its source.
            "profile": profile.to_dict(),
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
            # The projection as one matrix: K and P = K [R | t], from
            # this very record, so a consumer multiplies instead of
            # re-deriving the convention (the verifier checks the two
            # agree to a thousandth of a pixel on every frame).
            K, P = projection_matrices(frames[-1])
            frames[-1]["intrinsic_matrix"] = K
            frames[-1]["projection_matrix"] = P
            # Version 5: the labels, from this very record and the
            # cited airframe -- the same numbers a consumer reads.
            frames[-1]["labels"] = frame_labels(
                frames[-1], frames[-1]["aircraft"], airframe,
                terrain_elevation_m)
            # Version 6: one record per labelled object. The primary's
            # geometric values are COPIED from the labels above; each
            # traffic aircraft is projected from its own airframe at its
            # scripted state; the terrain carries nulls. Engine-derived
            # keys are null with a basis until attach_engine_labels.
            axes = camera_axes(frames[-1]["quaternion_wxyz"])
            frames[-1]["labels"]["objects"] = _object_records(
                objects, frames[-1], state, airframe, axes,
                terrain_elevation_m, randomization, primary_mesh,
                traffic_objects, traffic_airframes, traffic_tracks,
                traffic_meshes, sample_index)
            # The sensor model this frame was (or will be) passed
            # through: the profile's full parameters, the camera's
            # angular rate for the rolling shutter, and the labels
            # mapped onto that sensor. The ideal profile maps them onto
            # themselves.
            omega = camera_angular_rate(track, sample_index)
            frames[-1]["sensor"] = {
                "profile": profile.name,
                "angular_rate_rad_s": omega,
                "labels_sensor": sensor_labels(profile, frames[-1],
                                               frames[-1]["labels"], omega),
            }
            # Version 6: every OTHER object mapped onto the same sensor,
            # so an exporter of the sensor image has a box for each (the
            # primary's mapping is the block above). A scene object with
            # no 3-D box maps to null boxes -- stated, so the exporter
            # sees an entry that says "no box" rather than no entry.
            frames[-1]["sensor"]["labels_sensor"]["objects"] = [
                dict({"id": entry["id"], "int_id": entry["int_id"]},
                     **sensor_labels(
                         profile, frames[-1],
                         dict(entry, bbox_3d_camera=entry["bbox_3d_camera"] or {}),
                         omega))
                for entry in frames[-1]["labels"]["objects"]
                if entry["int_id"] != objects[0].int_id]

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
        "airframe": airframe.to_dict(),
        "label_conventions": label_conventions(),
        "assets": asset_digests(spec, airframe, scene),
        # Phase 10 (package 7): the sampled look and jitter the render
        # was given, or null when the block is off. Same dict as the
        # card's, so the two records cannot disagree.
        "randomization": randomization,
        # Version 6: the scene's labelled objects, the class list they
        # are labelled against, and the traffic aircraft's provenance.
        "objects": objects_block(objects),
        "taxonomy": taxonomy_classes(spec),
        "traffic": [
            {
                "id": obj.id, "int_id": obj.int_id,
                "aircraft": str(entry.aircraft.value),
                "track": str(entry.track.value),
                "range_m": float(entry.range_m.value),
                "livery": str(entry.livery.value),
                "spec": entry.to_dict(),
                "track_digest": track.digest(),
                "airframe": frame_.to_dict(),
                "attitude_basis": ("copied from the primary sample for "
                                   "sample" if str(entry.track.value) == "formation"
                                   else "wings level (roll = pitch = 0): a "
                                        "scripted actor has no dynamics to bank"),
            }
            for obj, entry, track, frame_
            in zip(traffic_objects, spec.traffic, traffic_tracks, traffic_airframes)
        ],
        "cameras": camera_blocks,
        "frames": frames,
    }


def _object_records(objects, record, primary_state, primary_airframe, axes,
                    terrain_elevation_m, randomization, primary_mesh,
                    traffic_objects, traffic_airframes, traffic_tracks,
                    traffic_meshes, sample_index) -> List[Dict]:
    """``labels.objects[]`` for one frame, in composition order."""
    out: List[Dict] = []
    traffic_index = {o.int_id: i for i, o in enumerate(traffic_objects)}
    for obj in objects:
        if obj.role == ROLE_PRIMARY:
            out.append(object_label_record(
                obj, record, primary_state, primary_airframe, axes,
                terrain_elevation_m, randomization, primary_mesh,
                primary=True, base_labels=record["labels"]))
        elif obj.role == ROLE_TRAFFIC:
            i = traffic_index[obj.int_id]
            out.append(object_label_record(
                obj, record, traffic_state(traffic_tracks[i], sample_index),
                traffic_airframes[i], axes, terrain_elevation_m,
                randomization, traffic_meshes[i]))
        else:
            out.append(object_label_record(
                obj, record, None, None, axes, terrain_elevation_m,
                randomization))
    return out


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
    "airframe", "label_conventions", "assets", "randomization",
    # Version 6: the object list every per-object record resolves
    # through, the class list, and the traffic provenance.
    "objects", "taxonomy", "traffic",
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
