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
* Absolute (LSB 1) timestamps are decodable, never written.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field, replace
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
