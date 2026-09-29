"""IEEE 1278.1-2012 Entity State PDUs from a run's telemetry.

The gap (docs/PHASE3_GAP_ANALYSIS.md I1): the branch spoke no
interoperability protocol. This module writes the one PDU every DIS
consumer reads, the Entity State PDU (protocol version 7, PDU type 1,
protocol family 1), one per telemetry sample, into a binary stream file
-- raw PDUs back to back, no framing: every PDU is 144 bytes (no
articulation parameters) and its header's ``length`` says so -- with a
JSON sidecar ``dis_manifest.json`` carrying the counts, the datum
handling, the entity type with what is and is not verified about it,
and the ``interop.dis`` AppliedVariable record (core/records.py).

The byte layout (every field big-endian, IEEE 1278.1-2012 clause 7.2.2
with the version-7 header of clause 6.2.66; offsets in bytes)::

      0  u8   protocol version (7)
      1  u8   exercise id
      2  u8   PDU type (1 = Entity State)
      3  u8   protocol family (1 = Entity Information/Interaction)
      4  u32  timestamp (31 bits of time units past the hour, LSB 1 =
              absolute, 0 = relative; 2^31 units per hour, see
              timestamp_from_seconds)
      8  u16  length (144)
     10  u8   PDU status (0)
     11  u8   padding
     12  u16  entity id: site
     14  u16  entity id: application
     16  u16  entity id: entity
     18  u8   force id
     19  u8   number of variable parameters (0)
     20  u8   entity type: kind        (1 = Platform)
     21  u8   entity type: domain      (2 = Air)
     22  u16  entity type: country
     24  u8   entity type: category
     25  u8   entity type: subcategory
     26  u8   entity type: specific
     27  u8   entity type: extra
     28  ..   alternative entity type, same eight bytes
     36  f32  linear velocity x, y, z   (ECEF, m/s)
     48  f64  location x, y, z          (ECEF, m)
     72  f32  orientation psi, theta, phi (radians, core/interop/geodesy)
     84  u32  appearance
     88  u8   dead reckoning algorithm  (4 = DRM_RVW)
     89  15s  dead reckoning other parameters (zero)
    104  f32  linear acceleration x, y, z (ECEF, m/s^2)
    116  f32  angular velocity p, q, r    (body, rad/s)
    128  u8   marking character set     (1 = ASCII)
    129  11s  marking (ASCII, NUL padded)
    140  u32  capabilities
    144  end

Provenance of every value in a PDU
----------------------------------
* location: the telemetry's geodetic latitude/longitude and its
  altitude made ELLIPSOIDAL by the run's datum block
  (``altitude_m + datum.undulation_m``; see :func:`datum_for_run` for
  the three cases) through :func:`geodesy.geodetic_to_ecef`;
* velocity: the recorded NED ground velocity rotated into ECEF;
* orientation: the recorded heading, pitch, roll and the place through
  :func:`geodesy.dis_euler_from_ned`;
* dead reckoning: DERIVED by forward differences between consecutive
  samples (the telemetry records p and q but not r, and no
  acceleration): linear acceleration from the ECEF velocities, angular
  velocity from the two orientations (the rotation between them over
  the interval, in the first body frame); the last sample repeats the
  previous interval's values, a lone sample carries zeros;
* timestamp: relative (LSB 0), the sample's simulation time past an
  hour boundary, rounded to the nearest unit (3600 / 2^31 s);
* entity type: the small table :data:`ENTITY_TYPES`, each row saying
  which of its numbers are verified and which are 'unverified here'
  (the SISO-REF-010 document could not be fetched in this container);
* marking: the airframe's name, ASCII, 11 bytes;
* force id, appearance, capabilities, alternative entity type: zero,
  and the sidecar says so.

What is NOT claimed
-------------------
* No network: nothing is sent; the stream is a file. No exercise
  management, no heartbeat, no dead-reckoning threshold logic, no
  Collision, Fire or Detonation PDUs.
* The entity-type enumerations beyond kind and domain are unverified
  here; the sidecar carries the per-field status and a consumer that
  needs the exact SISO row must check it.
* The appearance bits (0) say nothing about the airframe's state; a
  consumer must not read "no damage, no lights" from them.
* The dead-reckoning vectors are finite differences at the sample rate,
  not the FDM's own accelerations and rates; the sidecar says which
  columns they came from and the report measures how far the derived
  p and q sit from the recorded ones on a real run.
* Absolute (LSB 1) timestamps are decodable; the batch-1 ``feed`` never
  writes them (the D2 stream below does, with its epoch stated).

D2 (blueprint section 5, work item D2): what this module gained
-----------------------------------------------------------------
Everything above is batch 1 and keeps its names and its meaning
(``feed``, ``pdus_from_telemetry``, ``dead_reckoning_vectors`` are the
forward-difference feed the I5 contract describes). The full-rate
stream that a capture writes beside its manifest lives in
core/interop/dis_stream.py and is built from the pieces added here:

* the ENTITY TYPE has two tiers. :data:`ENTITY_TYPE_TABLE_PATH`
  (assets/dis_entity_types.yaml) is the STANDARD table: one row per
  configured airframe naming the SISO-REF-010 edition, UID and table
  the septuplet is to be copied from, shipped with every septuplet
  null and the reason 'entered from the standard, never guessed', so
  :func:`standard_entity_type` refuses ``dis.entity_type_unknown`` by
  name until someone with the standard fills a row. :data:`ENTITY_TYPES`
  above is retained as the DOCUMENTED FALLBACK (values from memory, per
  field 'unverified here'), reached only when a caller asks for the
  ``fallback`` policy; :func:`entity_type_row` resolves the three
  policies (``standard`` | ``fallback`` | ``unspecified``, the last
  writing the enumeration's own 0 = Other in every field and recording
  the septuplet's absence). The batch-1 ``feed`` keeps the fallback.
* the TIMESTAMP has two modes: ``relative`` (the in-tree 2^31 units per
  hour of simulation time, LSB 0) and ``absolute`` (LSB 1, the units
  past the hour of a stated UTC epoch plus the sample time; without an
  epoch :func:`parse_epoch` refuses ``dis.timestamp_epoch_missing``).
* the MARKING comes from the run: the spec's ``dis.marking`` when
  stated, else the airframe key derived at export; over 11 ASCII bytes
  refuses ``dis.marking_too_long``.
* the GEODETIC frame is checked per sample: a recording whose columns or
  values lack latitude, longitude or an ellipsoidal height refuses
  ``dis.frame_without_geodetic`` (:func:`sample_frames`); the geoid is
  applied at the export boundary -- ``hae_m`` = orthometric + N, D1's
  recorded channel when the run has it, else the datum block's N as
  :func:`datum_for_run` handles it.
* dead reckoning DRM 4 (RVW) from RECORDED quantities only
  (:func:`rvw_vectors`): p and q from ``roll_rate_dps`` /
  ``pitch_rate_dps``, r from ``yaw_rate_dps`` when the recording has it
  and otherwise the yaw component of the central difference of the
  recorded body-from-ECEF attitude; the world linear acceleration is the
  CENTRAL difference of the recorded ECEF velocity (one-sided at the
  ends), never a model's output.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.records import AppliedVariable, NullTest, records_block
from . import geodesy

#: The record every stream carries (core/records.py).
RECORD_NAME = "interop.dis"
MODEL = "IEEE 1278.1-2012 ESPDU"
REFERENCES = (
    "IEEE Std 1278.1-2012, Standard for Distributed Interactive Simulation -- "
    "Application Protocols: 6.2.66 PDU header, 7.2.2 Entity State PDU, "
    "6.2.8 timestamp, 1.4 world and entity coordinate systems (cited from memory; "
    "the standard could not be fetched here)",
    "SISO-REF-010 Enumerations for Simulation Interoperability (entity types; "
    "unverified here)",
    "NIMA TR8350.2 WGS 84 defining parameters (a = 6378137 m, 1/f = 298.257223563)",
)

#: The sidecar's own version; readers key on it.
DIS_MANIFEST_VERSION = 1

PROTOCOL_VERSION = 7
PDU_TYPE_ENTITY_STATE = 1
PROTOCOL_FAMILY_ENTITY_INFORMATION = 1
ESPDU_LENGTH = 144
DR_ALGORITHM_RVW = 4
MARKING_CHARSET_ASCII = 1
MARKING_LENGTH = 11
DR_OTHER_PARAMETERS_LENGTH = 15
FORCE_ID_OTHER = 0

#: The timestamp field: 31 bits of units past the hour, 2^31 per hour.
TIMESTAMP_UNITS_PER_HOUR = 2 ** 31
SECONDS_PER_HOUR = 3600.0
TIMESTAMP_RESOLUTION_S = SECONDS_PER_HOUR / TIMESTAMP_UNITS_PER_HOUR
TIMESTAMP_ABSOLUTE_BIT = 1

#: The whole PDU as one struct format, in the order of the layout above.
#: '>' is big-endian with no alignment padding, so calcsize is the wire
#: length exactly; the test measures it.
ESPDU_FORMAT = (">BBBBIHBB"      # header
                "HHH"            # entity id
                "BB"             # force id, number of variable parameters
                "BBHBBBB"        # entity type
                "BBHBBBB"        # alternative entity type
                "fff" "ddd" "fff"  # velocity, location, orientation
                "I"              # appearance
                "B15sffffff"     # dead reckoning
                "B11s"           # marking
                "I")             # capabilities

#: Field offsets in the wire form, for the sidecar and for a reader that
#: wants one field without decoding the PDU.
FIELD_OFFSETS = {
    "protocol_version": 0, "exercise_id": 1, "pdu_type": 2, "protocol_family": 3,
    "timestamp": 4, "length": 8, "pdu_status": 10, "padding": 11,
    "entity_id": 12, "force_id": 18, "number_of_variable_parameters": 19,
    "entity_type": 20, "alternative_entity_type": 28, "linear_velocity": 36,
    "location": 48, "orientation": 72, "appearance": 84,
    "dead_reckoning_algorithm": 88, "dead_reckoning_other_parameters": 89,
    "linear_acceleration": 104, "angular_velocity": 116,
    "marking_character_set": 128, "marking": 129, "capabilities": 140,
}


class DisError(ValueError):
    """Refused by name: ``constraint`` is the catalogue entry."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint
        self.message = message


# -- entity types ----------------------------------------------------------

@dataclass(frozen=True)
class EntityType:
    kind: int = 0
    domain: int = 0
    country: int = 0
    category: int = 0
    subcategory: int = 0
    specific: int = 0
    extra: int = 0

    def to_tuple(self) -> Tuple[int, int, int, int, int, int, int]:
        return (self.kind, self.domain, self.country, self.category,
                self.subcategory, self.specific, self.extra)

    def to_dict(self) -> Dict[str, int]:
        return {"kind": self.kind, "domain": self.domain, "country": self.country,
                "category": self.category, "subcategory": self.subcategory,
                "specific": self.specific, "extra": self.extra}

    @classmethod
    def from_tuple(cls, values: Sequence[int]) -> "EntityType":
        return cls(*[int(v) for v in values])


ENTITY_KIND_PLATFORM = 1
ENTITY_DOMAIN_AIR = 2

#: The airframes this build can name, with the per-field status. "kind"
#: and "domain" are the standard's own (IEEE 1278.1 Annex / SISO-REF-010
#: section 4: 1 Platform, 2 Air) and are the only fields marked verified;
#: the country codes and the Platform-Air categories/subcategories are
#: written from memory of SISO-REF-010 and marked 'unverified here'. A
#: subcategory this build does not know is 0 (the enumeration's own
#: "unspecified"), never a guess.
ENTITY_TYPES: Dict[str, Dict[str, Any]] = {
    "c172p": {
        "type": EntityType(1, 2, 225, 84, 1, 0, 0),
        "basis": {"kind": "verified: 1 Platform", "domain": "verified: 2 Air",
                  "country": "unverified here: 225 United States",
                  "category": "unverified here: 84 Civilian Fixed Wing Aircraft, Light",
                  "subcategory": "unverified here: 1 Single Piston Engine"},
    },
    "A320": {
        "type": EntityType(1, 2, 71, 86, 6, 0, 0),
        "basis": {"kind": "verified: 1 Platform", "domain": "verified: 2 Air",
                  "country": "unverified here: 71 France (Airbus rows as remembered)",
                  "category": "unverified here: 86 Civilian Fixed Wing Aircraft, Heavy",
                  "subcategory": "unverified here: 6 Twin Jet"},
    },
    "B747": {
        "type": EntityType(1, 2, 225, 86, 8, 0, 0),
        "basis": {"kind": "verified: 1 Platform", "domain": "verified: 2 Air",
                  "country": "unverified here: 225 United States",
                  "category": "unverified here: 86 Civilian Fixed Wing Aircraft, Heavy",
                  "subcategory": "unverified here: 8 Four Jet"},
    },
    "DHC6": {
        "type": EntityType(1, 2, 39, 85, 4, 0, 0),
        "basis": {"kind": "verified: 1 Platform", "domain": "verified: 2 Air",
                  "country": "unverified here: 39 Canada",
                  "category": "unverified here: 85 Civilian Fixed Wing Aircraft, Medium "
                              "(the DHC-6's 12,500 lb sits on the Light/Medium boundary)",
                  "subcategory": "unverified here: 4 Twin Engine Turboprop"},
    },
    "p51d": {
        "type": EntityType(1, 2, 225, 1, 0, 0, 0),
        "basis": {"kind": "verified: 1 Platform", "domain": "verified: 2 Air",
                  "country": "unverified here: 225 United States",
                  "category": "unverified here: 1 Fighter/Air Defense",
                  "subcategory": "not known here: 0 (unspecified)"},
    },
    "f16": {
        "type": EntityType(1, 2, 225, 1, 5, 0, 0),
        "basis": {"kind": "verified: 1 Platform", "domain": "verified: 2 Air",
                  "country": "unverified here: 225 United States",
                  "category": "unverified here: 1 Fighter/Air Defense",
                  "subcategory": "unverified here: 5 F-16 Fighting Falcon"},
    },
}


def entity_type_for(aircraft: str) -> Dict[str, Any]:
    """The table row for an airframe; refuses by name an airframe the
    table does not carry rather than inventing an enumeration."""
    row = ENTITY_TYPES.get(str(aircraft))
    if row is None:
        raise DisError("interop.dis.airframe",
                       f"no DIS entity type is tabulated for airframe {aircraft!r}; "
                       f"the table names {sorted(ENTITY_TYPES)}")
    return row


# -- the PDU -----------------------------------------------------------------

def timestamp_from_seconds(t_s: float, absolute: bool = False) -> int:
    """The 32-bit timestamp field: the time past the hour in units of
    3600 / 2^31 s in the upper 31 bits (rounded to the nearest unit,
    wrapping every hour), the absolute flag in the LSB."""
    units = int(round((float(t_s) % SECONDS_PER_HOUR) / SECONDS_PER_HOUR
                      * TIMESTAMP_UNITS_PER_HOUR)) % TIMESTAMP_UNITS_PER_HOUR
    return (units << 1) | (TIMESTAMP_ABSOLUTE_BIT if absolute else 0)


def seconds_from_timestamp(timestamp: int) -> Tuple[float, bool]:
    """(seconds past the hour, absolute?) from the field."""
    units = (int(timestamp) >> 1) & (TIMESTAMP_UNITS_PER_HOUR - 1)
    return (units * TIMESTAMP_RESOLUTION_S, bool(int(timestamp) & TIMESTAMP_ABSOLUTE_BIT))


def _f32(value: float) -> float:
    """The value as the wire's float32 will carry it."""
    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


@dataclass(frozen=True)
class EntityStatePdu:
    """One Entity State PDU, every wire field a Python value. Floats
    that the wire carries as float32 are stored as the float32 value
    (``quantised``) so that encode -> decode is the identity."""

    exercise_id: int = 1
    timestamp: int = 0
    site: int = 1
    application: int = 1
    entity: int = 1
    force_id: int = FORCE_ID_OTHER
    entity_type: EntityType = EntityType()
    alternative_entity_type: EntityType = EntityType()
    linear_velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    location: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    appearance: int = 0
    dead_reckoning_algorithm: int = DR_ALGORITHM_RVW
    dead_reckoning_other_parameters: bytes = bytes(DR_OTHER_PARAMETERS_LENGTH)
    linear_acceleration: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    marking_character_set: int = MARKING_CHARSET_ASCII
    marking: bytes = bytes(MARKING_LENGTH)
    capabilities: int = 0
    pdu_status: int = 0
    padding: int = 0
    number_of_variable_parameters: int = 0

    def quantised(self) -> "EntityStatePdu":
        """The same PDU with every float32 field rounded to float32 and
        every byte field padded to its wire length."""
        return replace(
            self,
            linear_velocity=tuple(_f32(v) for v in self.linear_velocity),
            orientation=tuple(_f32(v) for v in self.orientation),
            linear_acceleration=tuple(_f32(v) for v in self.linear_acceleration),
            angular_velocity=tuple(_f32(v) for v in self.angular_velocity),
            location=tuple(float(v) for v in self.location),
            dead_reckoning_other_parameters=bytes(self.dead_reckoning_other_parameters)
            .ljust(DR_OTHER_PARAMETERS_LENGTH, b"\0")[:DR_OTHER_PARAMETERS_LENGTH],
            marking=bytes(self.marking).ljust(MARKING_LENGTH, b"\0")[:MARKING_LENGTH],
        )

    def encode(self) -> bytes:
        q = self.quantised()
        for name in ("site", "application", "entity"):
            value = getattr(q, name)
            if not 0 <= int(value) <= 0xFFFF:
                raise DisError("interop.dis.entity_id",
                               f"entity id {name} {value} is outside 0..65535")
        if not 0 <= int(q.exercise_id) <= 0xFF:
            raise DisError("interop.dis.entity_id",
                           f"exercise id {q.exercise_id} is outside 0..255")
        data = struct.pack(
            ESPDU_FORMAT,
            PROTOCOL_VERSION, q.exercise_id, PDU_TYPE_ENTITY_STATE,
            PROTOCOL_FAMILY_ENTITY_INFORMATION, q.timestamp & 0xFFFFFFFF,
            ESPDU_LENGTH, q.pdu_status, q.padding,
            q.site, q.application, q.entity,
            q.force_id, q.number_of_variable_parameters,
            *q.entity_type.to_tuple(),
            *q.alternative_entity_type.to_tuple(),
            *q.linear_velocity, *q.location, *q.orientation,
            q.appearance,
            q.dead_reckoning_algorithm, q.dead_reckoning_other_parameters,
            *q.linear_acceleration, *q.angular_velocity,
            q.marking_character_set, q.marking,
            q.capabilities)
        assert len(data) == ESPDU_LENGTH, len(data)
        return data

    def to_dict(self) -> Dict[str, Any]:
        seconds, absolute = seconds_from_timestamp(self.timestamp)
        return {
            "exercise_id": self.exercise_id, "timestamp": self.timestamp,
            "time_past_hour_s": seconds, "timestamp_absolute": absolute,
            "entity_id": {"site": self.site, "application": self.application,
                          "entity": self.entity},
            "force_id": self.force_id,
            "entity_type": self.entity_type.to_dict(),
            "alternative_entity_type": self.alternative_entity_type.to_dict(),
            "linear_velocity_ecef_mps": list(self.linear_velocity),
            "location_ecef_m": list(self.location),
            "orientation_rad": list(self.orientation),
            "appearance": self.appearance,
            "dead_reckoning_algorithm": self.dead_reckoning_algorithm,
            "linear_acceleration_ecef_mps2": list(self.linear_acceleration),
            "angular_velocity_body_radps": list(self.angular_velocity),
            "marking_character_set": self.marking_character_set,
            "marking": self.marking.rstrip(b"\0").decode("ascii", errors="replace"),
            "capabilities": self.capabilities,
        }


def decode(data: bytes) -> EntityStatePdu:
    """One PDU from exactly its 144 bytes; refuses by name
    (``interop.dis.stream``) anything that is not a version-7 Entity
    State PDU of that length."""
    if len(data) != ESPDU_LENGTH:
        raise DisError("interop.dis.stream",
                       f"an Entity State PDU is {ESPDU_LENGTH} bytes; got {len(data)}")
    fields = struct.unpack(ESPDU_FORMAT, data)
    (version, exercise_id, pdu_type, family, timestamp, length, status, padding,
     site, application, entity, force_id, n_params) = fields[:13]
    if version != PROTOCOL_VERSION or pdu_type != PDU_TYPE_ENTITY_STATE:
        raise DisError("interop.dis.stream",
                       f"not a protocol-version-{PROTOCOL_VERSION} Entity State PDU "
                       f"(version {version}, type {pdu_type})")
    if length != ESPDU_LENGTH or family != PROTOCOL_FAMILY_ENTITY_INFORMATION:
        raise DisError("interop.dis.stream",
                       f"header says length {length}, family {family}; this reader "
                       f"takes {ESPDU_LENGTH} and {PROTOCOL_FAMILY_ENTITY_INFORMATION}")
    if n_params != 0:
        raise DisError("interop.dis.stream",
                       f"{n_params} variable parameter records; this build writes "
                       f"and reads none")
    entity_type = EntityType.from_tuple(fields[13:20])
    alternative = EntityType.from_tuple(fields[20:27])
    velocity = fields[27:30]
    location = fields[30:33]
    orientation = fields[33:36]
    appearance = fields[36]
    dr_algorithm, dr_other = fields[37], fields[38]
    acceleration = fields[39:42]
    angular = fields[42:45]
    charset, marking = fields[45], fields[46]
    capabilities = fields[47]
    return EntityStatePdu(
        exercise_id=exercise_id, timestamp=timestamp, site=site,
        application=application, entity=entity, force_id=force_id,
        entity_type=entity_type, alternative_entity_type=alternative,
        linear_velocity=tuple(velocity), location=tuple(location),
        orientation=tuple(orientation), appearance=appearance,
        dead_reckoning_algorithm=dr_algorithm,
        dead_reckoning_other_parameters=dr_other,
        linear_acceleration=tuple(acceleration), angular_velocity=tuple(angular),
        marking_character_set=charset, marking=marking, capabilities=capabilities,
        pdu_status=status, padding=padding, number_of_variable_parameters=n_params)


def encode_stream(pdus: Sequence[EntityStatePdu]) -> bytes:
    return b"".join(p.encode() for p in pdus)


def decode_stream(data: bytes) -> List[EntityStatePdu]:
    """Every PDU of a stream file, by the header's own length field;
    refuses by name a stream that does not divide into whole PDUs."""
    pdus: List[EntityStatePdu] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 12:
            raise DisError("interop.dis.stream",
                           f"{len(data) - offset} trailing bytes at offset {offset} "
                           f"are shorter than a PDU header")
        length = struct.unpack(">H", data[offset + 8:offset + 10])[0]
        if length == 0 or offset + length > len(data):
            raise DisError("interop.dis.stream",
                           f"PDU {len(pdus)} at offset {offset} declares {length} bytes; "
                           f"{len(data) - offset} remain")
        pdus.append(decode(data[offset:offset + length]))
        offset += length
    return pdus


def read_stream(path) -> List[EntityStatePdu]:
    path = Path(path)
    if not path.is_file():
        raise DisError("interop.dis.stream", f"no stream file at {path}")
    return decode_stream(path.read_bytes())


# -- the run -----------------------------------------------------------------

#: The telemetry columns a PDU is built from, by wire field.
REQUIRED_COLUMNS = ("t", "lat_deg", "lon_deg", "altitude_m",
                    "heading_deg", "pitch_deg", "roll_deg",
                    "v_north_mps", "v_east_mps", "v_down_mps")

DATUM_ABSENT = "datum: orthometric treated as ellipsoidal (no geoid block in this run)"
DATUM_NULL = ("datum: the run's datum block carries no undulation (undulation_m null: "
              "no georeferenced heights), so the JSBSim altitude, which is above the "
              "WGS 84 ellipsoid by JSBSim's definition, is the ellipsoidal height")
DATUM_APPLIED = ("datum: ellipsoidal height = JSBSim altitude + datum.undulation_m "
                 "({n:+.3f} m, {model})")


def datum_for_run(run_dir) -> Dict[str, Any]:
    """The undulation the feed adds to every altitude, and where it came
    from: ``datum.undulation_m`` from ``card.json`` or
    ``capture_manifest.json`` when either carries a datum block, else 0
    with the 'orthometric treated as ellipsoidal' note. A block whose
    undulation is null (a flat or synthesised scene) is 0 with its own
    note: absence of a geoid is not a geoid of zero."""
    run_dir = Path(run_dir)
    for name in ("capture_manifest.json", "card.json"):
        path = run_dir / name
        if not path.is_file():
            continue
        try:
            block = json.loads(path.read_text(encoding="utf-8")).get("datum")
        except (ValueError, OSError) as exc:
            raise DisError("interop.dis.run", f"{path} could not be read: {exc}")
        if not isinstance(block, dict) or "undulation_m" not in block:
            continue
        n = block.get("undulation_m")
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            return {"undulation_m": float(n), "source_file": name,
                    "geoid_model": block.get("geoid_model"),
                    "vertical_datum_of_heights": block.get("vertical_datum_of_heights"),
                    "handling": DATUM_APPLIED.format(n=float(n), model=block.get("geoid_model"))}
        return {"undulation_m": 0.0, "source_file": name,
                "geoid_model": block.get("geoid_model"),
                "vertical_datum_of_heights": block.get("vertical_datum_of_heights"),
                "handling": DATUM_NULL}
    return {"undulation_m": 0.0, "source_file": None, "geoid_model": None,
            "vertical_datum_of_heights": None, "handling": DATUM_ABSENT}


def read_telemetry(run_dir) -> Dict[str, Any]:
    path = Path(run_dir) / "telemetry.json"
    if not path.is_file():
        raise DisError("interop.dis.run",
                       f"{Path(run_dir)} holds no telemetry.json; a run directory "
                       f"written by flightsim.capture is needed")
    try:
        telemetry = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DisError("interop.dis.run", f"{path} is not JSON: {exc}")
    columns = telemetry.get("columns") if isinstance(telemetry, dict) else None
    if not isinstance(columns, dict):
        raise DisError("interop.dis.run", f"{path} carries no telemetry columns")
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise DisError("interop.dis.channels",
                       f"telemetry lacks the columns a PDU needs: {missing} "
                       f"(a run recorded before lat_deg/lon_deg were sampled)")
    lengths = {len(columns[c]) for c in REQUIRED_COLUMNS}
    if len(lengths) != 1:
        raise DisError("interop.dis.channels",
                       f"the required columns differ in length: {sorted(lengths)}")
    return telemetry


def aircraft_of_run(run_dir, telemetry: Dict[str, Any]) -> str:
    """The airframe name: the capture manifest's, else the scenario's,
    else the telemetry provenance's (minus the '-tecs' derivation suffix)."""
    run_dir = Path(run_dir)
    manifest = run_dir / "capture_manifest.json"
    if manifest.is_file():
        try:
            name = json.loads(manifest.read_text(encoding="utf-8")).get("aircraft")
            if isinstance(name, str) and name:
                return name
        except ValueError:
            pass
    scenario = run_dir / "scenario.yaml"
    if scenario.is_file():
        try:
            import yaml

            spec = yaml.safe_load(scenario.read_text(encoding="utf-8"))
            name = spec["aircraft"]["aircraft"]["value"]
            if isinstance(name, str) and name:
                return name
        except Exception:  # noqa: BLE001 -- any shape problem: fall through
            pass
    name = str(((telemetry.get("provenance") or {}).get("aircraft") or {}).get("name", ""))
    return name[:-5] if name.endswith("-tecs") else name


def _column(columns: Dict[str, Any], name: str, i: int) -> float:
    return float(columns[name][i])


def sample_geometry(columns: Dict[str, Any], i: int, undulation_m: float) -> Dict[str, Any]:
    """Location, velocity and orientation of sample ``i`` in the wire's
    frames, with the ellipsoidal height stated."""
    lat = _column(columns, "lat_deg", i)
    lon = _column(columns, "lon_deg", i)
    altitude_m = _column(columns, "altitude_m", i)
    h_ellipsoidal_m = altitude_m + undulation_m
    heading = _column(columns, "heading_deg", i)
    pitch = _column(columns, "pitch_deg", i)
    roll = _column(columns, "roll_deg", i)
    ned = (_column(columns, "v_north_mps", i), _column(columns, "v_east_mps", i),
           _column(columns, "v_down_mps", i))
    return {
        "t_s": _column(columns, "t", i),
        "lat_deg": lat, "lon_deg": lon, "h_ellipsoidal_m": h_ellipsoidal_m,
        "location": geodesy.geodetic_to_ecef(lat, lon, h_ellipsoidal_m),
        "velocity": geodesy.ned_to_ecef_vector(lat, lon, ned),
        "orientation": geodesy.dis_euler_from_ned(lat, lon, heading, pitch, roll),
        "body_from_ecef": geodesy.body_from_ecef_via_ned(lat, lon, heading, pitch, roll),
    }


def dead_reckoning_vectors(samples: Sequence[Dict[str, Any]]
                           ) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
    """(linear acceleration ECEF, angular velocity body) per sample by
    forward differences; the last repeats the previous, a lone sample
    is zeros. A repeated time stamp (dt = 0) carries zeros too."""
    zero = (0.0, 0.0, 0.0)
    if len(samples) < 2:
        return [(zero, zero)] * len(samples)
    out = []
    for i in range(len(samples) - 1):
        a, b = samples[i], samples[i + 1]
        dt = b["t_s"] - a["t_s"]
        if dt <= 0.0:
            out.append((zero, zero))
            continue
        accel = tuple((b["velocity"][k] - a["velocity"][k]) / dt for k in range(3))
        rotation = geodesy.rotation_vector_between(a["body_from_ecef"], b["body_from_ecef"])
        omega = tuple(r / dt for r in rotation)
        out.append((accel, omega))  # type: ignore[arg-type]
    out.append(out[-1])
    return out


def pdus_from_telemetry(telemetry: Dict[str, Any], aircraft: str,
                        undulation_m: float = 0.0, site: int = 1,
                        application: int = 1, entity: int = 1,
                        exercise_id: int = 1, force_id: int = FORCE_ID_OTHER
                        ) -> List[EntityStatePdu]:
    """One PDU per telemetry sample, in sample order."""
    columns = telemetry["columns"]
    row = entity_type_for(aircraft)
    marking = str(aircraft).encode("ascii", errors="replace")[:MARKING_LENGTH]
    samples = [sample_geometry(columns, i, undulation_m)
               for i in range(len(columns["t"]))]
    reckoning = dead_reckoning_vectors(samples)
    pdus = []
    for s, (accel, omega) in zip(samples, reckoning):
        pdus.append(EntityStatePdu(
            exercise_id=exercise_id, timestamp=timestamp_from_seconds(s["t_s"]),
            site=site, application=application, entity=entity, force_id=force_id,
            entity_type=row["type"], linear_velocity=s["velocity"],
            location=s["location"], orientation=s["orientation"],
            linear_acceleration=accel, angular_velocity=omega,
            marking=marking).quantised())
    return pdus


def position_check(pdus: Sequence[EntityStatePdu], telemetry: Dict[str, Any],
                   undulation_m: float, tolerance_m: float = 1e-3) -> Dict[str, Any]:
    """The null test's numbers: the decoded first PDU's location against
    pyproj's EPSG:4979 -> EPSG:4978 of the telemetry's first geodetic
    sample at the ellipsoidal height; and, for 'without', the residual of
    the telemetry's own (lat, lon, alt) numbers read as ECEF metres --
    what a consumer had before the feed existed, since the branch spoke
    no ECEF at all."""
    if not pdus:
        raise DisError("interop.dis.run", "the telemetry holds no samples")
    from pyproj import Transformer

    columns = telemetry["columns"]
    lat, lon = _column(columns, "lat_deg", 0), _column(columns, "lon_deg", 0)
    h = _column(columns, "altitude_m", 0) + undulation_m
    reference = Transformer.from_crs("EPSG:4979", "EPSG:4978",
                                     always_xy=True).transform(lon, lat, h)
    decoded = decode(pdus[0].encode()).location
    residual = math.dist(decoded, reference)
    untransformed = math.dist((lat, lon, _column(columns, "altitude_m", 0)), reference)
    return {
        "reference": "pyproj EPSG:4979 -> EPSG:4978 (independent of core/interop/geodesy)",
        "first_sample_geodetic": {"lat_deg": lat, "lon_deg": lon, "h_ellipsoidal_m": h},
        "reference_ecef_m": list(reference), "decoded_ecef_m": list(decoded),
        "residual_m": residual, "tolerance_m": float(tolerance_m),
        "ok": residual <= tolerance_m,
        "untransformed_residual_m": untransformed,
    }


def applied_variable(check: Dict[str, Any], datum: Dict[str, Any],
                     entity_row: Dict[str, Any], pdu_count: int,
                     reckoning_note: str) -> AppliedVariable:
    """The ``interop.dis`` record (core/records.py)."""
    return AppliedVariable(
        name=RECORD_NAME,
        value=pdu_count,
        unit="PDU",
        source="derived",
        model=MODEL,
        parameters={
            "protocol_version": PROTOCOL_VERSION, "pdu_type": PDU_TYPE_ENTITY_STATE,
            "pdu_length_bytes": ESPDU_LENGTH,
            "dead_reckoning_algorithm": DR_ALGORITHM_RVW,
            "timestamp": {"kind": "relative", "units_per_hour": TIMESTAMP_UNITS_PER_HOUR,
                          "resolution_s": TIMESTAMP_RESOLUTION_S},
            "datum": dict(datum),
            "entity_type": entity_row["type"].to_dict(),
            "entity_type_basis": dict(entity_row["basis"]),
            "dead_reckoning": reckoning_note,
            # the columns the feed READS; it records none (telemetry_columns
            # is what a variable writes per step, and this one writes nothing)
            "telemetry_columns_read": list(REQUIRED_COLUMNS),
        },
        references=REFERENCES,
        properties_written=(),
        telemetry_columns=(),
        frame_keys=(),
        null_test=NullTest(
            quantity="distance between the decoded first PDU's ECEF location and pyproj's "
                     "EPSG:4979->EPSG:4978 of the telemetry's first geodetic sample at "
                     "the ellipsoidal height",
            unit="m",
            with_value=float(check["residual_m"]),
            without_value=float(check["untransformed_residual_m"]),
            threshold=float(check["tolerance_m"]),
            note="'with' is the feed's residual against pyproj and is asserted to be "
                 "0 within the 1e-3 m tolerance (position_check.ok in the sidecar); "
                 "'without' is the residual a consumer carried before the feed, reading "
                 "the telemetry's own (lat, lon, alt) numbers as ECEF metres -- the "
                 "branch spoke no ECEF at all"),
        not_claimed=(
            "no PDU is sent on any network; the stream is a file",
            "entity-type country, category and subcategory are unverified here "
            "(SISO-REF-010 not fetched); kind and domain are the standard's own",
            "appearance and capabilities are 0 and say nothing about the airframe's state",
            "dead-reckoning acceleration and rates are forward differences at the sample "
            "rate, not the FDM's own",
            "the ellipsoidal height is only as good as the run's datum block "
            "(EGM96 bilinear, its stated bounds); a run without one is orthometric "
            "treated as ellipsoidal",
        ),
    )


RECKONING_NOTE = ("derived: linear acceleration = forward difference of the ECEF velocity "
                  "between consecutive samples; angular velocity = the rotation between "
                  "consecutive body-from-ECEF matrices over the interval, in the first "
                  "body frame; the last sample repeats the previous interval; the "
                  "telemetry records roll_rate_dps and pitch_rate_dps but no yaw rate "
                  "and no acceleration, so none of the three is read from JSBSim")


def feed(run_dir, out_path, site: int = 1, application: int = 1, entity: int = 1,
         exercise_id: int = 1, force_id: int = FORCE_ID_OTHER) -> Dict[str, Any]:
    """Write the stream and its sidecar for a run directory; returns the
    sidecar's content."""
    run_dir = Path(run_dir)
    out_path = Path(out_path)
    telemetry = read_telemetry(run_dir)
    aircraft = aircraft_of_run(run_dir, telemetry)
    row = entity_type_for(aircraft)
    datum = datum_for_run(run_dir)
    pdus = pdus_from_telemetry(telemetry, aircraft, undulation_m=datum["undulation_m"],
                               site=site, application=application, entity=entity,
                               exercise_id=exercise_id, force_id=force_id)
    check = position_check(pdus, telemetry, datum["undulation_m"])
    data = encode_stream(pdus)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    telemetry_path = run_dir / "telemetry.json"
    record = applied_variable(check, datum, row, len(pdus), RECKONING_NOTE)
    manifest = {
        "dis_manifest_version": DIS_MANIFEST_VERSION,
        "format": f"IEEE 1278.1-2012 Entity State PDU stream: protocol version "
                  f"{PROTOCOL_VERSION}, PDU type {PDU_TYPE_ENTITY_STATE}, big-endian, "
                  f"{ESPDU_LENGTH} bytes per PDU back to back, no framing",
        "stream_file": out_path.name,
        "stream_sha256": hashlib.sha256(data).hexdigest(),
        "stream_bytes": len(data),
        "pdu_count": len(pdus),
        "pdu_length_bytes": ESPDU_LENGTH,
        "samples": len(telemetry["columns"]["t"]),
        "one_pdu_per_sample": len(pdus) == len(telemetry["columns"]["t"]),
        "run_dir": str(run_dir),
        "telemetry_sha256": hashlib.sha256(telemetry_path.read_bytes()).hexdigest(),
        "telemetry_columns_used": list(REQUIRED_COLUMNS),
        "aircraft": aircraft,
        "marking": pdus[0].marking.rstrip(b"\0").decode("ascii", errors="replace"),
        "exercise_id": exercise_id,
        "entity_id": {"site": site, "application": application, "entity": entity},
        "force_id": force_id,
        "entity_type": row["type"].to_dict(),
        "entity_type_basis": dict(row["basis"]),
        "alternative_entity_type": EntityType().to_dict(),
        "appearance": 0, "capabilities": 0,
        "timestamp": {"kind": "relative (LSB 0)", "units_per_hour": TIMESTAMP_UNITS_PER_HOUR,
                      "resolution_s": TIMESTAMP_RESOLUTION_S,
                      "epoch": "simulation time 0 is the top of the hour; wraps every 3600 s",
                      "first_pdu_time_past_hour_s": seconds_from_timestamp(pdus[0].timestamp)[0],
                      "first_sample_t_s": float(telemetry["columns"]["t"][0])},
        "datum": datum,
        "orientation": "IEEE 1278.1 Euler angles psi, theta, phi from ECEF to body "
                       "(Rx(phi).Ry(theta).Rz(psi)), derived from the recorded heading, "
                       "pitch, roll and the place (core/interop/geodesy.py)",
        "velocity": "recorded NED ground velocity rotated into ECEF, float32",
        "dead_reckoning": {"algorithm": DR_ALGORITHM_RVW, "name": "DRM_RVW",
                           "note": RECKONING_NOTE},
        "field_offsets": dict(FIELD_OFFSETS),
        "position_check": check,
        "applied_variables": records_block([record]),
        "not_claimed": list(record.not_claimed),
    }
    sidecar = out_path.parent / "dis_manifest.json"
    sidecar.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def describe(pdu: EntityStatePdu) -> Dict[str, Any]:
    """A decoded PDU back in the telemetry's own words: geodetic position
    (ellipsoidal height) and NED heading, pitch, roll."""
    lat, lon, h = geodesy.ecef_to_geodetic(*pdu.location)
    heading, pitch, roll = geodesy.ned_from_dis_euler(lat, lon, *pdu.orientation)
    d = pdu.to_dict()
    d.update({"lat_deg": lat, "lon_deg": lon, "h_ellipsoidal_m": h,
              "heading_deg": heading, "pitch_deg": pitch, "roll_deg": roll})
    return d


# ===========================================================================
# D2: the entity-type table, the timestamp modes, the marking, the geodetic
# frame check and the RVW dead reckoning from recorded quantities.
# ===========================================================================

#: The standard table: one row per configured airframe citing the
#: SISO-REF-010 edition, UID and table the septuplet is to be copied
#: from. It ships with every septuplet null (see the file's own
#: ``reason``); a septuplet appears there only when someone with the
#: standard enters it.
ENTITY_TYPE_TABLE_PATH = Path(__file__).resolve().parents[2] / "assets" / "dis_entity_types.yaml"
ENTITY_TYPE_TABLE_VERSION = 1
ENTITY_TYPE_FIELDS = ("kind", "domain", "country", "category", "subcategory", "specific", "extra")
#: The three ways a stream may fill the entity type field.
ENTITY_TYPE_POLICIES = ("standard", "fallback", "unspecified")
ENTITY_TYPE_REASON_EMPTY = "entered from the standard, never guessed"

#: The two timestamp modes (IEEE 1278.1-2012 6.2.8: the LSB says which).
TIMESTAMP_MODES = ("relative", "absolute")

#: The DIS entity marking: 11 bytes, character set 1 (ASCII).
MARKING_MAX_CHARACTERS = MARKING_LENGTH

#: The columns the D2 stream reads per sample, and the optional ones it
#: uses when the recording has them (D1's ellipsoidal height, the yaw rate).
FRAME_COLUMNS = ("t", "lat_deg", "lon_deg", "heading_deg", "pitch_deg", "roll_deg",
                 "v_north_mps", "v_east_mps", "v_down_mps")
RATE_COLUMNS = ("roll_rate_dps", "pitch_rate_dps")
OPTIONAL_COLUMNS = ("hae_m", "undulation_m", "altitude_m", "yaw_rate_dps")


def _yaml():
    import yaml

    return yaml


def load_entity_type_table(path=ENTITY_TYPE_TABLE_PATH) -> Dict[str, Any]:
    """assets/dis_entity_types.yaml as data: ``{table_version, standard
    {name, edition, uid, table, note}, reason, airframes {key: {...}}}``.
    A table that is absent, unreadable or not of this shape refuses
    ``dis.entity_type_unknown`` too: a stream cannot say what it does
    not have."""
    path = Path(path)
    if not path.is_file():
        raise DisError("dis.entity_type_unknown",
                       f"the entity-type table {path} is absent; no airframe's "
                       f"enumeration can be stated")
    try:
        table = _yaml().safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- any parse failure is the same refusal
        raise DisError("dis.entity_type_unknown",
                       f"the entity-type table {path} could not be read: {exc}")
    if (not isinstance(table, dict) or table.get("table_version") != ENTITY_TYPE_TABLE_VERSION
            or not isinstance(table.get("airframes"), dict)
            or not isinstance(table.get("standard"), dict)):
        raise DisError("dis.entity_type_unknown",
                       f"the entity-type table {path} is not a version-"
                       f"{ENTITY_TYPE_TABLE_VERSION} table with a standard block and "
                       f"an airframes mapping")
    return table


def standard_entity_type(aircraft: str, table: Optional[Dict[str, Any]] = None
                         ) -> Tuple[EntityType, Dict[str, Any]]:
    """The septuplet the STANDARD table holds for an airframe and its row,
    or ``dis.entity_type_unknown`` by name: no row, or a row whose
    septuplet is still null ('entered from the standard, never
    guessed'). A filled row must carry all seven fields in range."""
    table = load_entity_type_table() if table is None else table
    row = table["airframes"].get(str(aircraft))
    if not isinstance(row, dict):
        raise DisError("dis.entity_type_unknown",
                       f"airframe {aircraft!r} has no row in the entity-type table; the "
                       f"table names {sorted(table['airframes'])}")
    septuplet = row.get("entity_type")
    if septuplet is None:
        raise DisError("dis.entity_type_unknown",
                       f"the entity-type table's row for {aircraft!r} carries no "
                       f"septuplet ({row.get('reason') or table.get('reason')}); enter it "
                       f"from {row.get('siso_reference') or table['standard'].get('name')} "
                       f"or ask for the fallback or unspecified policy")
    if not isinstance(septuplet, dict) or set(septuplet) != set(ENTITY_TYPE_FIELDS):
        raise DisError("dis.entity_type_unknown",
                       f"the entity-type table's row for {aircraft!r} is not the seven "
                       f"fields {list(ENTITY_TYPE_FIELDS)}")
    values = []
    for name in ENTITY_TYPE_FIELDS:
        value = septuplet[name]
        limit = 0xFFFF if name == "country" else 0xFF
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
            raise DisError("dis.entity_type_unknown",
                           f"the entity-type table's {aircraft!r} {name} {value!r} is not an "
                           f"integer in 0..{limit}")
        values.append(int(value))
    return EntityType(*values), row


def entity_type_row(aircraft: str, policy: str = "standard",
                    table: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The entity type a stream writes for an airframe, by policy:

    * ``standard``: the standard table's septuplet (refuses
      ``dis.entity_type_unknown`` while the row is empty);
    * ``fallback``: the documented fallback :data:`ENTITY_TYPES` (values
      from memory, 'unverified here'; ``interop.dis.airframe`` outside it),
      with the standard row's citation beside it when the table has one;
    * ``unspecified``: the enumeration's own 0 (Other) in every field,
      the septuplet recorded as absent with the reason.

    Returns ``{type, septuplet, source, basis, standard_row, policy}``;
    ``septuplet`` is the seven-field dict or None (its absence)."""
    if policy not in ENTITY_TYPE_POLICIES:
        raise ValueError(f"entity type policy {policy!r} is not one of {ENTITY_TYPE_POLICIES}")
    table = load_entity_type_table() if table is None else table
    standard_row = table["airframes"].get(str(aircraft))
    standard_row = dict(standard_row) if isinstance(standard_row, dict) else None
    if policy == "standard":
        entity_type, row = standard_entity_type(aircraft, table)
        return {"type": entity_type, "septuplet": entity_type.to_dict(), "source": "standard",
                "basis": {name: f"{row.get('siso_reference')}: entered from the standard"
                          for name in ENTITY_TYPE_FIELDS},
                "standard_row": row, "policy": policy}
    if policy == "fallback":
        row = entity_type_for(aircraft)
        basis = dict(row["basis"])
        basis["fallback"] = ("the documented fallback table core/interop/dis.py ENTITY_TYPES, "
                             "values from memory; the standard table's row is "
                             + ("empty" if standard_row is not None else "absent"))
        return {"type": row["type"], "septuplet": row["type"].to_dict(), "source": "fallback",
                "basis": basis, "standard_row": standard_row, "policy": policy}
    return {"type": EntityType(), "septuplet": None, "source": "unspecified",
            "basis": {"all": "0 = Other in every field, the enumeration's own unspecified "
                             "value; the septuplet is absent: " + ENTITY_TYPE_REASON_EMPTY},
            "standard_row": standard_row, "policy": policy}


# -- the timestamp modes ---------------------------------------------------------

def parse_epoch(epoch: Optional[str]) -> float:
    """A stated UTC epoch (ISO 8601, e.g. ``2026-09-29T10:00:00Z``) as
    seconds since 1970-01-01T00:00:00Z. None, or a text that is not an
    instant, refuses ``dis.timestamp_epoch_missing``: an absolute
    timestamp without a stated epoch would be a guess."""
    if epoch is None or not str(epoch).strip():
        raise DisError("dis.timestamp_epoch_missing",
                       "absolute timestamps were asked for and no epoch was stated; give "
                       "the UTC instant of simulation time 0 (ISO 8601, e.g. "
                       "2026-09-29T10:00:00Z) or use relative timestamps")
    text = str(epoch).strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        raise DisError("dis.timestamp_epoch_missing",
                       f"the epoch {epoch!r} is not an ISO 8601 instant "
                       f"(e.g. 2026-09-29T10:00:00Z)") from None
    if instant.tzinfo is None:
        raise DisError("dis.timestamp_epoch_missing",
                       f"the epoch {epoch!r} carries no UTC offset; an instant without one "
                       f"is not an epoch")
    return instant.astimezone(timezone.utc).timestamp()


def timestamp_for(t_s: float, mode: str, epoch_unix_s: Optional[float] = None) -> int:
    """The timestamp field for a sample: ``relative`` is the in-tree
    units of simulation time past the hour (LSB 0); ``absolute`` is the
    units past the hour of epoch + t (LSB 1), the epoch's own seconds
    past its hour taken first so a 1.7e9 s epoch loses no precision to
    the 1.676 us unit."""
    if mode not in TIMESTAMP_MODES:
        raise DisError("dis.timestamp_mode",
                       f"timestamp mode {mode!r} is not one of {TIMESTAMP_MODES}")
    if mode == "relative":
        return timestamp_from_seconds(float(t_s))
    if epoch_unix_s is None:
        raise DisError("dis.timestamp_epoch_missing",
                       "absolute timestamps need an epoch; none was given")
    past_hour = (float(epoch_unix_s) % SECONDS_PER_HOUR) + float(t_s)
    return timestamp_from_seconds(past_hour, absolute=True)


# -- the marking --------------------------------------------------------------------

def marking_for(marking: Optional[str], aircraft: str) -> Tuple[bytes, str]:
    """The 11-byte ASCII marking and where it came from: the stated text
    (``user``) or, when none was stated, the airframe key (``derived``).
    More than 11 characters, or a character outside ASCII, refuses
    ``dis.marking_too_long`` (the wire field is 11 bytes of character
    set 1 = ASCII; nothing is truncated or replaced silently)."""
    text = "" if marking is None else str(marking)
    source = "user"
    if not text:
        text, source = str(aircraft), "derived"
    if len(text) > MARKING_MAX_CHARACTERS or not text.isascii():
        raise DisError("dis.marking_too_long",
                       f"the marking {text!r} ({len(text)} characters) does not fit the "
                       f"11-byte ASCII marking field"
                       + ("" if text.isascii() else "; it carries a non-ASCII character"))
    return text.encode("ascii"), source


# -- the geodetic frame per sample --------------------------------------------------

def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def sample_frames(columns: Dict[str, Any], datum: Optional[Dict[str, Any]] = None
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every sample's geodetic frame for the wire, and how the
    ellipsoidal height was formed: D1's recorded ``hae_m`` (orthometric
    + N, the geoid applied at export) when the recording carries it,
    else ``altitude_m`` + the datum block's N as :func:`datum_for_run`
    handles it (``datum`` is that handling dict, or None for 0 with the
    'no geoid block' note). Refuses ``dis.frame_without_geodetic`` for a
    recording without latitude, longitude or a height column, columns
    of unequal length, or a sample whose value is not a finite number:
    a PDU with a guessed place is worse than none."""
    missing = [c for c in ("lat_deg", "lon_deg") if c not in columns]
    if missing:
        raise DisError("dis.frame_without_geodetic",
                       f"the recording carries no {missing} column, so no sample has a "
                       f"geodetic place to put on the wire")
    if "hae_m" in columns:
        hae_source = ("hae_m: the recorded ellipsoidal height (altitude_m + undulation_m, "
                      "the geoid applied at export by core/scenario/runner.py datum_run)")
        heights = columns["hae_m"]
        n_column = columns.get("undulation_m")
    elif "altitude_m" in columns:
        handling = datum or {"undulation_m": 0.0, "handling": DATUM_ABSENT}
        n = float(handling.get("undulation_m") or 0.0)
        hae_source = f"altitude_m + {n:+.3f} m ({handling.get('handling')})"
        heights = [None if not _finite(h) else float(h) + n for h in columns["altitude_m"]]
        n_column = None
    else:
        raise DisError("dis.frame_without_geodetic",
                       "the recording carries neither hae_m nor altitude_m, so no sample "
                       "has an ellipsoidal height")
    others = [c for c in FRAME_COLUMNS if c not in columns]
    if others:
        raise DisError("dis.frame_without_geodetic",
                       f"the recording lacks the columns a PDU's attitude and velocity need: "
                       f"{others}")
    lengths = {len(columns[c]) for c in FRAME_COLUMNS} | {len(heights)}
    if len(lengths) != 1:
        raise DisError("dis.frame_without_geodetic",
                       f"the recording's columns differ in length: {sorted(lengths)}")
    frames: List[Dict[str, Any]] = []
    for i in range(len(columns["t"])):
        values = {c: columns[c][i] for c in FRAME_COLUMNS}
        values["hae_m"] = heights[i]
        bad = [c for c, v in values.items() if not _finite(v)]
        if bad:
            raise DisError("dis.frame_without_geodetic",
                           f"sample {i} has no finite {bad}; a PDU cannot be written for a "
                           f"frame without a geodetic place")
        lat, lon, h = float(values["lat_deg"]), float(values["lon_deg"]), float(values["hae_m"])
        heading, pitch, roll = (float(values["heading_deg"]), float(values["pitch_deg"]),
                                float(values["roll_deg"]))
        ned = (float(values["v_north_mps"]), float(values["v_east_mps"]), float(values["v_down_mps"]))
        frames.append({
            "index": i, "t_s": float(values["t"]),
            "lat_deg": lat, "lon_deg": lon, "hae_m": h,
            "undulation_m": (float(n_column[i]) if n_column is not None and _finite(n_column[i])
                             else None),
            "location": geodesy.geodetic_to_ecef(lat, lon, h),
            "velocity": geodesy.ned_to_ecef_vector(lat, lon, ned),
            "orientation": geodesy.dis_euler_from_ned(lat, lon, heading, pitch, roll),
            "body_from_ecef": geodesy.body_from_ecef_via_ned(lat, lon, heading, pitch, roll),
        })
    return frames, {"hae_source": hae_source, "samples": len(frames)}


# -- DRM 4 (RVW) from recorded quantities only -------------------------------------

def central_difference(values: Sequence[Sequence[float]], times: Sequence[float],
                       i: int) -> Tuple[float, ...]:
    """d(values)/dt at sample ``i``: the central difference over the
    neighbours, one-sided at either end, zeros for a lone sample or a
    zero interval. Every operand is a recorded quantity."""
    n = len(values)
    if n < 2:
        return tuple(0.0 for _ in values[0]) if n else ()
    lo, hi = max(0, i - 1), min(n - 1, i + 1)
    dt = float(times[hi]) - float(times[lo])
    if dt <= 0.0:
        return tuple(0.0 for _ in values[i])
    return tuple((float(values[hi][k]) - float(values[lo][k])) / dt for k in range(len(values[i])))


def rvw_vectors(frames: Sequence[Dict[str, Any]], columns: Dict[str, Any]
                ) -> Tuple[List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]],
                           Dict[str, str]]:
    """(linear acceleration ECEF, angular velocity body) per sample for
    DRM 4, and the provenance of each component: the acceleration is the
    central difference of the recorded ECEF velocity (never a model's);
    p and q are the recorded ``roll_rate_dps`` / ``pitch_rate_dps``; r is
    the recorded ``yaw_rate_dps`` when the recording has it, else the
    yaw component of the central difference of the recorded
    body-from-ECEF attitude (rotation_vector_between over the
    neighbours, in the sample's own body frame)."""
    times = [f["t_s"] for f in frames]
    velocities = [f["velocity"] for f in frames]
    has_yaw = "yaw_rate_dps" in columns
    source = {
        "linear_acceleration": "central difference of the recorded ECEF velocity "
                               "(v_north_mps, v_east_mps, v_down_mps rotated at the sample's "
                               "place) over the neighbouring samples; one-sided at the ends",
        "p": "recorded roll_rate_dps (deg/s -> rad/s)",
        "q": "recorded pitch_rate_dps (deg/s -> rad/s)",
        "r": ("recorded yaw_rate_dps (deg/s -> rad/s)" if has_yaw else
              "yaw_rate_dps not recorded: the yaw component of the central difference of "
              "the recorded body-from-ECEF attitude over the neighbouring samples"),
    }
    out = []
    for i, frame in enumerate(frames):
        accel = central_difference(velocities, times, i) if frames else (0.0, 0.0, 0.0)
        if len(accel) != 3:
            accel = (0.0, 0.0, 0.0)
        p = math.radians(float(columns["roll_rate_dps"][i])) if "roll_rate_dps" in columns else 0.0
        q = math.radians(float(columns["pitch_rate_dps"][i])) if "pitch_rate_dps" in columns else 0.0
        if has_yaw:
            r = math.radians(float(columns["yaw_rate_dps"][i]))
        elif len(frames) >= 2:
            lo, hi = max(0, i - 1), min(len(frames) - 1, i + 1)
            dt = times[hi] - times[lo]
            rotation = geodesy.rotation_vector_between(frames[lo]["body_from_ecef"],
                                                       frames[hi]["body_from_ecef"])
            r = rotation[2] / dt if dt > 0.0 else 0.0
        else:
            r = 0.0
        out.append((tuple(accel), (p, q, r)))  # type: ignore[arg-type]
    if "roll_rate_dps" not in columns or "pitch_rate_dps" not in columns:
        source["p"] = source["q"] = "rate columns not recorded: 0"
    return out, source
