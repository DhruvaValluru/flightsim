"""The full-rate Entity State PDU log a capture writes beside its
manifest (blueprint section 5, work item D2).

``dis_entity_state.bin`` is IEEE 1278.1-2012 Entity State PDUs
(protocol version 7, PDU type 1, 144 bytes each, big-endian, back to
back with no framing -- the batch-1 wire form of core/interop/dis.py)
and ``dis_entity_state.json`` beside it is the index: ``pdu_count``, the
``byte_offsets`` of every PDU, the ``sample_indices`` they were built
from, ``timestamp_mode`` and ``epoch``, the recording's ``interval_s``,
the ``emitter`` and its measured reconstruction, the entity ids, the
marking with its source, the entity type with its policy and basis (or
its absence), the datum handling, the dead-reckoning provenance, the
UDP report, and the ``dis.entity_state`` record (core/records.py,
record 2) that the capture manifest carries under ``applied_variables``
with the per-frame keys ``dis.pdu_index`` / ``dis.byte_offset``.

Where every value on the wire comes from (all of it RECORDED, none of
it a model's output): location = the recorded latitude, longitude and
D1's ``hae_m`` (orthometric altitude + the geoid undulation N, the
geoid applied at the export boundary; without that column the datum
block's N as batch 1 handles it) through the WGS 84 closed form;
velocity = the recorded NED ground velocity rotated at the sample's
place; orientation = the recorded heading, pitch, roll and the place
through the DIS Euler convention; dead reckoning DRM 4 (RVW) = the
central difference of the recorded ECEF velocity and the recorded body
rates (core/interop/dis.py ``rvw_vectors``); timestamp = the sample's
simulation time in the stated mode; marking = the spec's or the
airframe key; entity type = the standard table's septuplet, the
documented fallback, or 0 = Other with the absence recorded (by policy).

The emitter. ``full_rate`` writes one PDU per telemetry sample.
``thresholded`` writes a PDU when the RVW extrapolation from the last
PDU written (position + velocity dt + acceleration dt^2 / 2; attitude
turned by the body rates dt) misses the recorded sample by more than
the position or orientation threshold, or when the heartbeat has
elapsed -- IEEE 1278.1's dead-reckoning discipline, with the thresholds
and the heartbeat declared parameters of the record. Its measurable
claim, measured on every thresholded stream and written into the index:
the extrapolation from the thresholded stream reconstructs every
full-rate sample within the thresholds.

The UDP sender is OFF by default: the file is always written, and
datagrams go out only when a host and port are given -- never from a
campaign worker (a run directory under a campaign refuses
``dis.udp_in_campaign`` by name: a campaign is reproducible batch work,
not an exercise).

Refusals by name (``DisError.constraint``): ``dis.frame_without_geodetic``,
``dis.marking_too_long``, ``dis.timestamp_epoch_missing``,
``dis.timestamp_mode``, ``dis.entity_type_unknown``, ``dis.force_id``,
``dis.udp_in_campaign``, and batch 1's ``interop.dis.entity_id``,
``interop.dis.run``, ``interop.dis.stream``, ``interop.dis.airframe``.

What is NOT claimed: no live federation (one-way, one entity, Entity
State PDUs only; no other PDU kind is written or read, nothing is
received); appearance, capabilities and articulation are 0 and say
nothing about the airframe; no HLA / RPR FOM and no CIGI (the run card
is the documented offline image-generator interface); the SISO-REF-010
septuplets are not asserted (the standard table ships empty); no DIS
consumer has read the stream here -- Wireshark's DIS dissector or the
opendis package on a networked machine is the named independent
decoder; the dead-reckoning vectors are differences of recorded
quantities at the recording's sample rate, not the FDM's own; the
thresholded emitter's claim is reconstruction within the thresholds,
not that a consumer's own extrapolation does the same; the geoid is
applied at export only (JSBSim's own ECEF stays radially low by N).
Every text file is written ASCII (json.dumps escapes) with
encoding="utf-8".
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.records import AppliedVariable, Model, NullTest, Readback, records_block
from . import geodesy
from .dis import (
    DR_ALGORITHM_RVW, ENTITY_TYPE_POLICIES, ESPDU_LENGTH, FIELD_OFFSETS, FORCE_ID_OTHER,
    FRAME_COLUMNS, MARKING_MAX_CHARACTERS, PDU_TYPE_ENTITY_STATE, PROTOCOL_VERSION, RATE_COLUMNS,
    REFERENCES, TIMESTAMP_MODES, TIMESTAMP_RESOLUTION_S, TIMESTAMP_UNITS_PER_HOUR, DisError,
    EntityStatePdu, datum_for_run, decode, decode_stream, encode_stream, entity_type_row,
    marking_for, parse_epoch, read_telemetry, rvw_vectors, sample_frames, seconds_from_timestamp,
    timestamp_for,
)

#: The two files, beside the capture manifest.
STREAM_FILE = "dis_entity_state.bin"
INDEX_FILE = "dis_entity_state.json"
INDEX_VERSION = 1

#: The record every stream carries (core/records.py record 2).
RECORD_NAME = "dis.entity_state"
MODEL_FULL_RATE = ("full-rate Entity State PDU log (IEEE 1278.1-2012 layout, protocol "
                   "version 7)")
MODEL_THRESHOLDED = ("DR-thresholded Entity State PDU log (IEEE 1278.1-2012 layout, protocol "
                     "version 7; DRM 4 thresholds and heartbeat as declared)")

#: The emitters.
EMITTERS = ("full_rate", "thresholded")
#: The thresholded emitter's defaults: a STATED choice (1 m, 3 deg, 5 s --
#: the values IEEE 1278.1 exercises commonly use, as remembered; not
#: asserted from the standard), each a declared parameter of the record.
DEFAULT_POSITION_THRESHOLD_M = 1.0
DEFAULT_ORIENTATION_THRESHOLD_RAD = math.radians(3.0)
DEFAULT_HEARTBEAT_S = 5.0

#: The floor the record's null test is graded against: the branch's
#: altitude floor (core/record_null.py, 10 x the V9 noise), the same
#: metre a moved position is graded by everywhere else.
NULL_TEST_FLOOR_M = 0.5

#: The frame keys the record names (the per-frame record's ``dis`` block).
FRAME_KEYS = ("dis.pdu_index", "dis.byte_offset")

#: The campaign worker's layout (core/campaign/workers.py): a case runs in
#: ``<campaign>/runs/<case_id>`` and the campaign directory holds its record.
CAMPAIGN_RECORD = "campaign.json"
CAMPAIGN_RUNS_DIR = "runs"


@dataclass(frozen=True)
class StreamOptions:
    """Everything a stream is written with. The six spec-block fields
    first (site, application, entity, force_id, marking, timestamp_mode
    -- the ``dis`` block's), then the exporter's own: the epoch of
    absolute timestamps, the emitter and its thresholds, the entity-type
    policy and the exercise id."""

    site: int = 1
    application: int = 1
    entity: int = 1
    force_id: int = FORCE_ID_OTHER
    marking: str = ""
    timestamp_mode: str = "relative"
    epoch: Optional[str] = None
    emitter: str = "full_rate"
    position_threshold_m: float = DEFAULT_POSITION_THRESHOLD_M
    orientation_threshold_rad: float = DEFAULT_ORIENTATION_THRESHOLD_RAD
    heartbeat_s: float = DEFAULT_HEARTBEAT_S
    entity_type_policy: str = "standard"
    exercise_id: int = 1
    sources: Dict[str, str] = field(default_factory=dict)

    def block_values(self) -> Dict[str, Any]:
        return {"site": self.site, "application": self.application, "entity": self.entity,
                "force_id": self.force_id, "marking": self.marking,
                "timestamp_mode": self.timestamp_mode}


def dis_spec_problems(values: Optional[Dict[str, Any]]) -> List[DisError]:
    """The ``dis`` block's refusals, one list for the validator and the
    exporter, over ``{site, application, entity, force_id, marking,
    timestamp_mode}``: ``interop.dis.entity_id`` (an id outside 0..65535
    or not an integer), ``dis.force_id`` (outside 0..255), ``dis.marking_too_long``
    (over 11 ASCII characters), ``dis.timestamp_mode`` (not relative or
    absolute). None or an empty mapping is the default block: nothing."""
    out: List[DisError] = []
    if not values:
        return out

    def integer(name: str) -> Optional[int]:
        value = values.get(name)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                as_float = float(value)
            except (TypeError, ValueError):
                return None
            if not as_float.is_integer():
                return None
            return int(as_float)
        return int(value)

    for name in ("site", "application", "entity"):
        if name not in values:
            continue
        value = integer(name)
        if value is None or not 0 <= value <= 0xFFFF:
            out.append(DisError("interop.dis.entity_id",
                                f"dis.{name} {values.get(name)!r} is not an integer in 0..65535"))
    if "force_id" in values:
        value = integer("force_id")
        if value is None or not 0 <= value <= 0xFF:
            out.append(DisError("dis.force_id",
                                f"dis.force_id {values.get('force_id')!r} is not an integer in "
                                f"0..255 (0 Other, 1 Friendly, 2 Opposing, 3 Neutral per the "
                                f"standard's force-id enumeration, as remembered)"))
    marking = values.get("marking")
    if marking is not None and marking != "":
        text = str(marking)
        if len(text) > MARKING_MAX_CHARACTERS or not text.isascii():
            out.append(DisError("dis.marking_too_long",
                                f"dis.marking {text!r} ({len(text)} characters) does not fit "
                                f"the 11-byte ASCII marking field"))
    mode = values.get("timestamp_mode")
    if mode is not None and mode not in TIMESTAMP_MODES:
        out.append(DisError("dis.timestamp_mode",
                            f"dis.timestamp_mode {mode!r} is not one of {TIMESTAMP_MODES}"))
    return out


def options_from_spec(spec, **overrides: Any) -> StreamOptions:
    """StreamOptions from a ScenarioSpec's ``dis`` block (its six fields
    with their provenance sources recorded), the exporter's own settings
    from ``overrides``. A spec without the block (a build where it has
    not landed) gives the defaults."""
    block = getattr(spec, "dis", None)
    values: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    if block is not None:
        for name, quantity in block.quantities():
            values[name] = quantity.value
            sources[name] = str(quantity.source)
    for problem in dis_spec_problems(values):
        raise problem
    fields = dict(values)
    if fields.get("marking") is None:
        fields["marking"] = ""
    fields.update(overrides)
    fields["sources"] = sources
    return StreamOptions(**fields)


def preflight(aircraft: str, options: StreamOptions) -> Dict[str, Any]:
    """Everything a stream refuses that needs no recording, checked BEFORE
    a flight (the capture command calls it after reading the spec): the
    block's values (``dis_spec_problems``), the emitter word, the epoch
    when the mode is absolute (``dis.timestamp_epoch_missing``), the
    marking (``dis.marking_too_long``) and the entity type by policy
    (``dis.entity_type_unknown`` / ``interop.dis.airframe``). Returns
    what was resolved, so a refusal is printed before any flight time is
    spent and the write after the flight can refuse on nothing the user
    chose."""
    if options.emitter not in EMITTERS:
        raise ValueError(f"emitter {options.emitter!r} is not one of {EMITTERS}")
    for problem in dis_spec_problems(options.block_values()):
        raise problem
    if options.timestamp_mode not in TIMESTAMP_MODES:
        raise DisError("dis.timestamp_mode",
                       f"timestamp mode {options.timestamp_mode!r} is not one of {TIMESTAMP_MODES}")
    epoch_unix = parse_epoch(options.epoch) if options.timestamp_mode == "absolute" else None
    marking, marking_source = marking_for(options.marking, aircraft)
    entity = entity_type_row(aircraft, options.entity_type_policy)
    return {"epoch_unix_s": epoch_unix, "marking": marking.decode("ascii"),
            "marking_source": marking_source, "entity_type": entity["septuplet"],
            "entity_type_source": entity["source"]}


def in_campaign_worker(out_dir) -> bool:
    """Whether ``out_dir`` is a campaign case's run directory
    (``<campaign>/runs/<case>`` with the campaign's record beside the
    runs directory) -- the layout core/campaign/workers.py writes."""
    path = Path(out_dir).resolve()
    return (path.parent.name == CAMPAIGN_RUNS_DIR
            and (path.parent.parent / CAMPAIGN_RECORD).is_file())


# -- dead-reckoning extrapolation (the consumer's arithmetic, used for the
#    thresholded emitter and its reconstruction measurement) -----------------

def _rodrigues_passive(vector: Sequence[float]) -> geodesy.Mat3:
    """The passive rotation by axis-angle ``vector`` (radians): the matrix
    R with ``body_from_ecef(t + dt) = R . body_from_ecef(t)`` when the
    body turns at ``vector / dt`` in its own frame (the same sign
    rotation_vector_between measures; checked by the tests)."""
    angle = math.sqrt(sum(v * v for v in vector))
    if angle == 0.0:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    ux, uy, uz = (v / angle for v in vector)
    k = ((0.0, -uz, uy), (uz, 0.0, -ux), (-uy, ux, 0.0))
    k2 = geodesy.matmul(k, k)
    s, c = math.sin(angle), 1.0 - math.cos(angle)
    return tuple(tuple((1.0 if i == j else 0.0) - s * k[i][j] + c * k2[i][j]  # type: ignore[return-value]
                       for j in range(3)) for i in range(3))


def extrapolate(pdu: EntityStatePdu, dt_s: float) -> Tuple[Tuple[float, float, float], geodesy.Mat3]:
    """DRM 4 (RVW) from a PDU: location + velocity dt + acceleration
    dt^2 / 2 in ECEF; the body-from-ECEF attitude turned by the body
    rates dt. Returns (location, body_from_ecef)."""
    location = tuple(pdu.location[k] + pdu.linear_velocity[k] * dt_s
                     + 0.5 * pdu.linear_acceleration[k] * dt_s * dt_s for k in range(3))
    attitude = geodesy.body_from_ecef_via_dis(*pdu.orientation)
    turned = geodesy.matmul(_rodrigues_passive([w * dt_s for w in pdu.angular_velocity]), attitude)
    return location, turned  # type: ignore[return-value]


def _angle_between(a: geodesy.Mat3, b: geodesy.Mat3) -> float:
    return math.sqrt(sum(v * v for v in geodesy.rotation_vector_between(a, b)))


# -- building the stream -------------------------------------------------------------

@dataclass(frozen=True)
class StreamBuild:
    pdus: Tuple[EntityStatePdu, ...]
    sample_indices: Tuple[int, ...]
    frames: Tuple[Dict[str, Any], ...]
    entity_type: Dict[str, Any]
    marking: Dict[str, Any]
    timestamp: Dict[str, Any]
    datum: Dict[str, Any]
    dead_reckoning: Dict[str, Any]
    emitter: Dict[str, Any]
    options: StreamOptions


def _select_thresholded(pdus: Sequence[EntityStatePdu], frames: Sequence[Dict[str, Any]],
                        options: StreamOptions) -> List[int]:
    """The sample indices the thresholded emitter writes: the first, then
    every sample the RVW extrapolation from the last written PDU misses
    by more than a threshold, or that the heartbeat reaches."""
    if not pdus:
        return []
    chosen = [0]
    last = 0
    for i in range(1, len(pdus)):
        dt = frames[i]["t_s"] - frames[last]["t_s"]
        location, attitude = extrapolate(pdus[last], dt)
        position_error = math.dist(location, frames[i]["location"])
        orientation_error = _angle_between(attitude, frames[i]["body_from_ecef"])
        if (position_error > options.position_threshold_m
                or orientation_error > options.orientation_threshold_rad
                or dt >= options.heartbeat_s):
            chosen.append(i)
            last = i
    return chosen


def reconstruction(pdus: Sequence[EntityStatePdu], sample_indices: Sequence[int],
                   frames: Sequence[Dict[str, Any]], options: StreamOptions) -> Dict[str, Any]:
    """The thresholded emitter's claim, measured: from the written PDUs,
    the RVW extrapolation at every full-rate sample against the recorded
    one -- the worst position and orientation error and whether both
    sit within the thresholds."""
    worst_position = 0.0
    worst_orientation = 0.0
    k = 0
    for i, frame in enumerate(frames):
        while k + 1 < len(sample_indices) and sample_indices[k + 1] <= i:
            k += 1
        dt = frame["t_s"] - frames[sample_indices[k]]["t_s"]
        location, attitude = extrapolate(pdus[k], dt)
        worst_position = max(worst_position, math.dist(location, frame["location"]))
        worst_orientation = max(worst_orientation, _angle_between(attitude, frame["body_from_ecef"]))
    return {
        "samples": len(frames), "pdus": len(pdus),
        "position_error_max_m": worst_position,
        "orientation_error_max_rad": worst_orientation,
        "position_threshold_m": options.position_threshold_m,
        "orientation_threshold_rad": options.orientation_threshold_rad,
        "within_thresholds": (worst_position <= options.position_threshold_m
                              and worst_orientation <= options.orientation_threshold_rad),
        "arithmetic": "location + velocity dt + acceleration dt^2 / 2; attitude turned by the "
                      "body rates dt (passive Rodrigues); from the wire's float32 values",
    }


def build_stream(telemetry: Dict[str, Any], datum: Optional[Dict[str, Any]], aircraft: str,
                 options: StreamOptions = StreamOptions()) -> StreamBuild:
    """The PDUs of a recording (``telemetry.json``'s dict) under the
    options, with every provenance block the index carries. ``datum`` is
    the run's datum handling (:func:`core.interop.dis.datum_for_run`) or
    the run manifest's datum block, used only when the recording has no
    ``hae_m`` column."""
    if options.emitter not in EMITTERS:
        raise ValueError(f"emitter {options.emitter!r} is not one of {EMITTERS}")
    for problem in dis_spec_problems(options.block_values()):
        raise problem
    columns = telemetry.get("columns") if isinstance(telemetry, dict) else None
    if not isinstance(columns, dict) or "t" not in columns:
        raise DisError("interop.dis.run", "the recording carries no telemetry columns")
    handling = _datum_handling(datum)
    frames, height = sample_frames(columns, handling)
    if not frames:
        raise DisError("interop.dis.run", "the recording holds no samples")
    if options.timestamp_mode not in TIMESTAMP_MODES:
        raise DisError("dis.timestamp_mode",
                       f"timestamp mode {options.timestamp_mode!r} is not one of {TIMESTAMP_MODES}")
    epoch_unix = parse_epoch(options.epoch) if options.timestamp_mode == "absolute" else None
    marking, marking_source = marking_for(options.marking, aircraft)
    entity = entity_type_row(aircraft, options.entity_type_policy)
    reckoning, sources = rvw_vectors(frames, columns)
    pdus = []
    for frame, (accel, omega) in zip(frames, reckoning):
        pdus.append(EntityStatePdu(
            exercise_id=options.exercise_id,
            timestamp=timestamp_for(frame["t_s"], options.timestamp_mode, epoch_unix),
            site=options.site, application=options.application, entity=options.entity,
            force_id=options.force_id, entity_type=entity["type"],
            linear_velocity=frame["velocity"], location=frame["location"],
            orientation=frame["orientation"], linear_acceleration=accel,
            angular_velocity=omega, marking=marking).quantised())
    if options.emitter == "thresholded":
        indices = _select_thresholded(pdus, frames, options)
        emitted = [pdus[i] for i in indices]
        emitter = {"kind": "thresholded",
                   "position_threshold_m": options.position_threshold_m,
                   "orientation_threshold_rad": options.orientation_threshold_rad,
                   "heartbeat_s": options.heartbeat_s,
                   "emitted": len(indices), "suppressed": len(pdus) - len(indices),
                   "reconstruction": reconstruction(emitted, indices, frames, options)}
        pdus = emitted
    else:
        indices = list(range(len(pdus)))
        emitter = {"kind": "full_rate", "emitted": len(pdus), "suppressed": 0,
                   "position_threshold_m": None, "orientation_threshold_rad": None,
                   "heartbeat_s": None, "reconstruction": None}
    timestamp = {
        "mode": options.timestamp_mode,
        "lsb": 1 if options.timestamp_mode == "absolute" else 0,
        "units_per_hour": TIMESTAMP_UNITS_PER_HOUR, "resolution_s": TIMESTAMP_RESOLUTION_S,
        "epoch": options.epoch,
        "epoch_unix_s": epoch_unix,
        "meaning": ("units past the hour of the stated UTC epoch plus the sample's simulation "
                    "time, LSB 1" if options.timestamp_mode == "absolute" else
                    "units past the hour of the sample's simulation time (time 0 at the top of "
                    "the hour), LSB 0; wraps every 3600 s"),
        "first_pdu_time_past_hour_s": seconds_from_timestamp(pdus[0].timestamp)[0],
        "first_sample_t_s": frames[0]["t_s"],
    }
    return StreamBuild(
        pdus=tuple(pdus), sample_indices=tuple(indices), frames=tuple(frames),
        entity_type={"policy": entity["policy"], "source": entity["source"],
                     "septuplet": entity["septuplet"], "basis": entity["basis"],
                     "standard_row": entity["standard_row"],
                     "reason": (None if entity["septuplet"] is not None else
                                "the septuplet is absent (0 = Other on the wire): "
                                "entered from the standard, never guessed")},
        marking={"text": marking.decode("ascii"), "source": marking_source,
                 "character_set": "1 (ASCII)", "bytes": MARKING_MAX_CHARACTERS},
        timestamp=timestamp,
        datum={**handling, **height},
        dead_reckoning={"algorithm": DR_ALGORITHM_RVW, "name": "DRM_RVW", "source": sources},
        emitter=emitter, options=options)


def _datum_handling(datum: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The datum handling dict for ``sample_frames``: a handling dict as
    ``datum_for_run`` returns is taken as is; a manifest's datum block
    (``undulation_m`` numeric or null) is reduced to the three cases."""
    from .dis import DATUM_ABSENT, DATUM_APPLIED, DATUM_NULL

    if datum is None:
        return {"undulation_m": 0.0, "source_file": None, "geoid_model": None,
                "vertical_datum_of_heights": None, "handling": DATUM_ABSENT}
    if "handling" in datum:
        return dict(datum)
    n = datum.get("undulation_m")
    if isinstance(n, (int, float)) and not isinstance(n, bool):
        return {"undulation_m": float(n), "source_file": "run manifest",
                "geoid_model": datum.get("geoid_model"),
                "vertical_datum_of_heights": datum.get("vertical_datum_of_heights"),
                "u_model_m": datum.get("u_model_m"),
                "handling": DATUM_APPLIED.format(n=float(n), model=datum.get("geoid_model"))}
    return {"undulation_m": 0.0, "source_file": "run manifest",
            "geoid_model": datum.get("geoid_model"),
            "vertical_datum_of_heights": datum.get("vertical_datum_of_heights"),
            "u_model_m": datum.get("u_model_m"), "handling": DATUM_NULL}


# -- the null test, the readback, the record ---------------------------------------------

def location_null_test(data: bytes, build: StreamBuild) -> Dict[str, Any]:
    """The record's null test, measured on the written bytes: the first
    PDU decoded (batch 1's decoder over the file's bytes) against
    pyproj's EPSG:4979 -> EPSG:4978 of the first sample's (lat, lon)
    at the ellipsoidal height WITH the undulation applied and, for
    'without', at the orthometric height (what the export was before
    the geoid was applied at the boundary). Also the radial distances of
    both from the decoded point."""
    from pyproj import Transformer

    frame = build.frames[0]
    n = frame["undulation_m"] if frame["undulation_m"] is not None else float(
        build.datum.get("undulation_m") or 0.0)
    decoded = decode(data[:ESPDU_LENGTH]).location
    to_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    with_n = to_ecef.transform(frame["lon_deg"], frame["lat_deg"], frame["hae_m"])
    without_n = to_ecef.transform(frame["lon_deg"], frame["lat_deg"], frame["hae_m"] - n)
    return {
        "reference": "pyproj EPSG:4979 -> EPSG:4978 (independent of core/interop/geodesy)",
        "undulation_m": n,
        "first_sample": {"lat_deg": frame["lat_deg"], "lon_deg": frame["lon_deg"],
                         "hae_m": frame["hae_m"], "orthometric_m": frame["hae_m"] - n},
        "decoded_ecef_m": list(decoded),
        "error_with_n_m": math.dist(decoded, with_n),
        "error_without_n_m": math.dist(decoded, without_n),
        "radial_with_n_m": math.hypot(*decoded) - math.hypot(*with_n),
        "radial_without_n_m": math.hypot(*decoded) - math.hypot(*without_n),
    }


def stream_record(build: StreamBuild, data: bytes, null: Dict[str, Any],
                  stream_file: str = STREAM_FILE, index_file: str = INDEX_FILE,
                  udp: Optional[Dict[str, Any]] = None) -> AppliedVariable:
    """The ``dis.entity_state`` record (core/records.py record 2)."""
    options = build.options
    first = decode(data[:ESPDU_LENGTH])
    readback = Readback(
        property=f"{stream_file}: PDU 0 location x (m)", value=float(first.location[0]),
        written=float(build.pdus[0].location[0]), tolerance=0.0, tolerance_kind="absolute",
        basis="the first PDU's location read back from the written bytes by the batch-1 "
              "decoder against the value encoded; float64 on the wire, so exact (measured)")
    u_model = build.datum.get("u_model_m")
    uncertainty = {
        "u_input": (None if not isinstance(u_model, (int, float)) else
                    {"value": float(u_model), "unit": "m",
                     "rule": "the geoid model's declared spread (D1 u_model_m) carried into the "
                             "exported ellipsoidal height",
                     "sensitivity": {"location_radial_m": 1.0}}),
        "u_num": None,
    }
    thresholded = options.emitter == "thresholded"
    return AppliedVariable(
        name=RECORD_NAME, value=len(build.pdus), unit="PDU", source="derived",
        model=MODEL_THRESHOLDED if thresholded else MODEL_FULL_RATE,
        parameters={
            "timestamp_mode": options.timestamp_mode, "epoch": options.epoch,
            "pdu_count": len(build.pdus), "interval": build.timestamp.get("interval_s"),
            "emitter": build.emitter["kind"],
            "emitter_parameters": {k: v for k, v in build.emitter.items()
                                   if k not in ("kind", "reconstruction")},
            "reconstruction": build.emitter.get("reconstruction"),
            "entity_id": {"site": options.site, "application": options.application,
                          "entity": options.entity},
            "force_id": options.force_id, "exercise_id": options.exercise_id,
            "entity_type": build.entity_type["septuplet"],
            "entity_type_policy": build.entity_type["policy"],
            "entity_type_source": build.entity_type["source"],
            "entity_type_reason": build.entity_type["reason"],
            "marking": build.marking, "datum": build.datum,
            "dead_reckoning": build.dead_reckoning,
            "stream_file": stream_file, "index_file": index_file,
            "stream_sha256": hashlib.sha256(data).hexdigest(), "stream_bytes": len(data),
            "pdu_length_bytes": ESPDU_LENGTH, "protocol_version": PROTOCOL_VERSION,
            "pdu_type": PDU_TYPE_ENTITY_STATE,
            "spec_sources": dict(options.sources),
            "location_check": null,
            "udp": udp or {"sent": False, "note": "off by default: no datagram was sent"},
            "telemetry_columns_read": list(FRAME_COLUMNS) + list(RATE_COLUMNS)
                                      + ["hae_m", "undulation_m", "yaw_rate_dps"],
        },
        references=REFERENCES + (
            "IEEE Std 1278.1-2012 5.3.3 dead reckoning, DRM 4 (RVW): rotating, velocity, "
            "world acceleration (cited from memory)",),
        properties_written=(), telemetry_columns=(), frame_keys=FRAME_KEYS,
        null_test=NullTest(
            quantity="distance of the decoded first PDU's ECEF location from pyproj's "
                     "EPSG:4979->EPSG:4978 of the first sample: 'with' at the ellipsoidal "
                     "height (orthometric + N applied at export), 'without' at the "
                     "orthometric height",
            unit="m", with_value=float(null["error_with_n_m"]),
            without_value=float(null["error_without_n_m"]), threshold=NULL_TEST_FLOOR_M,
            kind="reached",
            note=(f"N = {null['undulation_m']:+.3f} m; 'with' is the export's own error against "
                  f"the independent reference and 'without' equals N by construction; the "
                  f"threshold is the branch's altitude floor (10 x the V9 noise); on a scene "
                  f"with no geoid N is 0 and the test measures 0, honestly not reached")),
        not_claimed=(
            "no live federation: one entity, one way, Entity State PDUs only; nothing is "
            "received and no other PDU kind is written",
            "appearance, capabilities and articulation are 0 and say nothing about the airframe",
            "the SISO-REF-010 septuplet is not asserted: the standard table ships empty, the "
            "fallback is from memory, the unspecified policy writes 0 = Other",
            "dead reckoning is differences of recorded quantities at the recording's sample "
            "rate, not the FDM's own accelerations and rates",
            "no DIS consumer has read the stream here; Wireshark's DIS dissector or the opendis "
            "package on a networked machine is the independent decoder",
            "the geoid is applied at the export boundary only; JSBSim's own ECEF stays "
            "radially low by N",
            "no HLA / RPR FOM, no CIGI: the run card is the documented offline image-generator "
            "interface",
        ),
        readback=readback,
        model_block=Model(
            name="Entity State PDU log", standard="IEEE 1278.1-2012",
            version=f"protocol version {PROTOCOL_VERSION}",
            parameters={"pdu_type": PDU_TYPE_ENTITY_STATE, "pdu_length_bytes": ESPDU_LENGTH,
                        "dead_reckoning_algorithm": DR_ALGORITHM_RVW,
                        "emitter": build.emitter["kind"],
                        "timestamp_mode": options.timestamp_mode},
            references=REFERENCES),
        uncertainty=uncertainty,
    )


# -- the UDP sender (off by default) ----------------------------------------------------

class UdpSender:
    """One datagram per PDU to ``host:port``. Created only when asked;
    never by default and never in a campaign worker (the caller checks
    :func:`in_campaign_worker` and refuses ``dis.udp_in_campaign``)."""

    def __init__(self, host: str, port: int) -> None:
        import socket

        self.host, self.port = str(host), int(port)
        if not 0 < self.port <= 0xFFFF:
            raise DisError("interop.dis.arguments", f"UDP port {port} is not in 1..65535")
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sent = 0
        self.bytes = 0

    def send(self, data: bytes) -> None:
        self._socket.sendto(data, (self.host, self.port))
        self.sent += 1
        self.bytes += len(data)

    def close(self) -> None:
        self._socket.close()

    def report(self) -> Dict[str, Any]:
        return {"sent": self.sent > 0, "host": self.host, "port": self.port,
                "datagrams": self.sent, "bytes": self.bytes,
                "note": "one Entity State PDU per datagram, after the file was written"}


def parse_udp_target(text: Optional[str]) -> Optional[Tuple[str, int]]:
    """``host:port`` -> (host, port), None for None; refuses
    ``interop.dis.arguments`` for anything else."""
    if text is None:
        return None
    host, sep, port = str(text).rpartition(":")
    if not sep or not host or not port.isdigit():
        raise DisError("interop.dis.arguments",
                       f"a UDP target is host:port, not {text!r}")
    return host, int(port)


# -- writing and reading -----------------------------------------------------------------

def write_stream(out_dir, telemetry: Optional[Dict[str, Any]] = None,
                 datum: Optional[Dict[str, Any]] = None, aircraft: Optional[str] = None,
                 options: StreamOptions = StreamOptions(),
                 udp: Optional[Tuple[str, int]] = None) -> Dict[str, Any]:
    """Write ``dis_entity_state.bin`` and its index into ``out_dir`` and
    return the index. ``telemetry`` / ``datum`` / ``aircraft`` default to
    the run directory's own (telemetry.json, the datum block of the
    capture manifest or card, the manifest's airframe), so a stream can
    be written after the fact as well as by the capture. ``udp`` is a
    (host, port) or None (the default: nothing is sent); a campaign
    worker's run directory refuses ``dis.udp_in_campaign`` before any
    socket exists. The file is written before any datagram goes out."""
    out_dir = Path(out_dir)
    if udp is not None and in_campaign_worker(out_dir):
        raise DisError("dis.udp_in_campaign",
                       f"{out_dir} is a campaign case's run directory; a campaign writes the "
                       f"stream file and sends nothing")
    if telemetry is None:
        telemetry = read_telemetry(out_dir)
    if datum is None:
        datum = datum_for_run(out_dir)
    if aircraft is None:
        from .dis import aircraft_of_run

        aircraft = aircraft_of_run(out_dir, telemetry)
    started = time.perf_counter()
    build = build_stream(telemetry, datum, str(aircraft), options)
    data = encode_stream(build.pdus)
    out_dir.mkdir(parents=True, exist_ok=True)
    stream_path = out_dir / STREAM_FILE
    stream_path.write_bytes(data)
    udp_report = None
    if udp is not None:
        sender = UdpSender(*udp)
        try:
            for pdu in build.pdus:
                sender.send(pdu.encode())
        finally:
            sender.close()
        udp_report = sender.report()
    null = location_null_test(data, build)
    build.timestamp["interval_s"] = telemetry.get("interval_s")
    record = stream_record(build, data, null, udp=udp_report)
    index = {
        "index_version": INDEX_VERSION,
        "format": f"IEEE 1278.1-2012 Entity State PDU stream: protocol version "
                  f"{PROTOCOL_VERSION}, PDU type {PDU_TYPE_ENTITY_STATE}, big-endian, "
                  f"{ESPDU_LENGTH} bytes per PDU back to back, no framing",
        "stream_file": STREAM_FILE, "stream_sha256": hashlib.sha256(data).hexdigest(),
        "stream_bytes": len(data),
        "pdu_count": len(build.pdus), "pdu_length_bytes": ESPDU_LENGTH,
        "byte_offsets": [i * ESPDU_LENGTH for i in range(len(build.pdus))],
        "sample_indices": list(build.sample_indices),
        "samples": len(build.frames),
        "timestamp_mode": options.timestamp_mode, "epoch": options.epoch,
        "interval_s": telemetry.get("interval_s"),
        "emitter": build.emitter,
        "timestamp": build.timestamp,
        "aircraft": str(aircraft),
        "exercise_id": options.exercise_id,
        "entity_id": {"site": options.site, "application": options.application,
                      "entity": options.entity},
        "force_id": options.force_id,
        "marking": build.marking,
        "entity_type": build.entity_type,
        "alternative_entity_type": "all zero",
        "appearance": 0, "capabilities": 0,
        "datum": build.datum,
        "dead_reckoning": build.dead_reckoning,
        "orientation": "IEEE 1278.1 Euler angles psi, theta, phi from ECEF to body "
                       "(Rx(phi).Ry(theta).Rz(psi)), from the recorded heading, pitch, roll "
                       "and the place (core/interop/geodesy.py)",
        "velocity": "recorded NED ground velocity rotated into ECEF, float32",
        "field_offsets": dict(FIELD_OFFSETS),
        "location_check": null,
        "udp": udp_report or {"sent": False, "note": "off by default: no datagram was sent"},
        "elapsed_s": time.perf_counter() - started,
        "applied_variables": records_block([record]),
        "not_claimed": list(record.not_claimed),
    }
    (out_dir / INDEX_FILE).write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index


def read_index(run_dir) -> Dict[str, Any]:
    """The index beside a stream, checked against the stream's bytes
    (sha256, length, the offsets against a walk by the PDU headers);
    ``interop.dis.stream`` by name otherwise."""
    run_dir = Path(run_dir)
    path = run_dir / INDEX_FILE
    stream = run_dir / STREAM_FILE
    if not path.is_file() or not stream.is_file():
        raise DisError("interop.dis.stream",
                       f"{run_dir} holds no {STREAM_FILE} with its {INDEX_FILE}")
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DisError("interop.dis.stream", f"{path} is not JSON: {exc}")
    data = stream.read_bytes()
    if (not isinstance(index, dict) or index.get("index_version") != INDEX_VERSION
            or index.get("stream_sha256") != hashlib.sha256(data).hexdigest()
            or index.get("stream_bytes") != len(data)):
        raise DisError("interop.dis.stream",
                       f"{path} does not describe the bytes of {stream} (version, sha256 or "
                       f"length differ)")
    pdus = decode_stream(data)
    offsets = [i * ESPDU_LENGTH for i in range(len(pdus))]
    if index.get("byte_offsets") != offsets or index.get("pdu_count") != len(pdus):
        raise DisError("interop.dis.stream",
                       f"{path} lists {index.get('pdu_count')} PDUs at {index.get('byte_offsets')!r}; "
                       f"the stream walks to {len(pdus)} at {offsets!r}")
    return index


def frame_keys_for(index: Dict[str, Any], sample_index: int) -> Dict[str, Any]:
    """The per-frame ``dis`` block for a telemetry sample: the index and
    byte offset of the PDU written for it (full-rate) or of the last PDU
    written at or before it (thresholded: the PDU a consumer extrapolates
    from). None for both when no PDU precedes the sample."""
    indices = index.get("sample_indices") or []
    offsets = index.get("byte_offsets") or []
    best = None
    for k, s in enumerate(indices):
        if int(s) <= int(sample_index):
            best = k
        else:
            break
    if best is None:
        return {"pdu_index": None, "byte_offset": None}
    return {"pdu_index": best, "byte_offset": int(offsets[best])}


def attach_frame_keys(manifest: Dict[str, Any], index: Dict[str, Any]) -> int:
    """Write ``dis {pdu_index, byte_offset}`` into every frame record of a
    capture manifest by its ``sample_index``; returns how many."""
    count = 0
    for record in manifest.get("frames", ()):
        if isinstance(record, dict) and isinstance(record.get("sample_index"), int):
            record["dis"] = frame_keys_for(index, record["sample_index"])
            count += 1
    return count
