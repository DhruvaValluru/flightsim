"""I1, the DIS entity-state feed: IEEE 1278.1-2012 Entity State PDUs
from a run's telemetry (core/interop/dis.py), the WGS 84 geodesy and
the DIS Euler convention under them (core/interop/geodesy.py), and the
CLI (flightsim/dis.py).

What is measured here, and how each measurement is independent of the
producer:

* the wire layout, by a decoder written out in this file field by field
  with ``struct.unpack`` at stated byte offsets -- it never calls
  ``dis.decode``;
* the ECEF conversion, against pyproj's EPSG:4979 -> EPSG:4978 at the six
  committed scene origins with the undulations measured on 2026-09-28
  (phase3_facts.md) as the ellipsoidal offsets;
* the orientation, by reconstructing the body axes in ECEF along two
  routes (NED attitude + place; DIS Euler angles alone) and by one case
  derived by hand in the comments;
* the timestamp, against the standard's own unit (3600 / 2^31 s);
* the ellipsoidal height, on a fabricated run carrying a datum block;
* the CLI, on a real short capture of examples/cameras_multi.yaml.

Not measured here: any DIS consumer reading the stream (none is
installed); the SISO-REF-010 enumerations beyond kind and domain.
"""
from __future__ import annotations

import json
import math
import random
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from pyproj import Transformer

from core.interop import dis, geodesy
from core.interop.dis import (
    DR_ALGORITHM_RVW, ENTITY_TYPES, ESPDU_FORMAT, ESPDU_LENGTH, FIELD_OFFSETS,
    TIMESTAMP_UNITS_PER_HOUR, DisError, EntityStatePdu, EntityType, datum_for_run,
    decode, decode_stream, encode_stream, feed, pdus_from_telemetry, read_stream,
    seconds_from_timestamp, timestamp_from_seconds,
)
from core.records import RECORD_VERSION, read_records

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

#: (lat, lon, EGM96 N) at the six committed scene origins, measured
#: 2026-09-28 from the GeographicLib egm96-15 grid (phase3_facts.md).
ORIGINS = {
    "matterhorn": (46.005, 7.72, 52.52),
    "yosemite": (37.7275, -119.61, -25.94),
    "fuji": (35.42, 138.7274, 41.47),
    "everest": (27.90, 86.87, -29.84),
    "grand_canyon": (36.09, -112.0, -23.40),
    "flint_hills": (38.43, -96.60, -30.54),
}

TO_ECEF = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)


def pyproj_ecef(lat, lon, h):
    return TO_ECEF.transform(lon, lat, h)


# -- fabricated telemetry ---------------------------------------------------

def make_telemetry(n=6, lat0=46.005, lon0=7.72, alt=3000.0, heading=30.0,
                   pitch=2.0, roll=-5.0, heading_rate_dps=0.0, dt=0.1,
                   v_north=60.0, v_east=10.0, v_down=-1.0, accel_north=0.0):
    """Columns in the recorder's shape (core/telemetry/recorder.py) with
    the geodetic and attitude channels the feed reads."""
    cols = {k: [] for k in ("t", "lat_deg", "lon_deg", "altitude_m", "heading_deg",
                            "pitch_deg", "roll_deg", "v_north_mps", "v_east_mps",
                            "v_down_mps", "roll_rate_dps", "pitch_rate_dps")}
    for i in range(n):
        t = i * dt
        cols["t"].append(t)
        cols["lat_deg"].append(lat0 + 1e-5 * i)
        cols["lon_deg"].append(lon0 + 2e-5 * i)
        cols["altitude_m"].append(alt + 0.5 * i)
        cols["heading_deg"].append((heading + heading_rate_dps * t) % 360.0)
        cols["pitch_deg"].append(pitch)
        cols["roll_deg"].append(roll)
        cols["v_north_mps"].append(v_north + accel_north * t)
        cols["v_east_mps"].append(v_east)
        cols["v_down_mps"].append(v_down)
        cols["roll_rate_dps"].append(0.0)
        cols["pitch_rate_dps"].append(0.0)
    return {"provenance": {"aircraft": {"name": "c172p-tecs"}}, "interval_s": dt,
            "samples": n, "events": [], "derived": [], "columns": cols}


def write_run(directory: Path, telemetry: dict, datum=None, aircraft="c172p",
              manifest=True) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "telemetry.json").write_text(json.dumps(telemetry), encoding="utf-8")
    if manifest:
        block = {"manifest_version": 6, "aircraft": aircraft}
        if datum is not None:
            block["datum"] = datum
        (directory / "capture_manifest.json").write_text(json.dumps(block), encoding="utf-8")
    return directory


MATTERHORN_DATUM = {
    "vertical_datum_of_heights": "EGM2008 orthometric (GLO-30)",
    "geoid_model": "EGM96 15-minute grid (GeographicLib egm96-15)",
    "origin_lat_deg": 46.005, "origin_lon_deg": 7.72,
    "undulation_m": 52.52, "bilinear_error_bound_m": 1.152,
}


@pytest.fixture(scope="module")
def real_run(tmp_path_factory) -> Path:
    """A real short capture (examples/cameras_multi.yaml, 12 s, B747),
    headless, no previews: the run directory flightsim.dis reads."""
    out = tmp_path_factory.mktemp("dis") / "run"
    result = subprocess.run(
        [PYTHON, "-m", "flightsim.capture", str(REPO / "examples/cameras_multi.yaml"),
         "--out", str(out), "--max-previews", "0"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out / "telemetry.json").is_file()
    return out


# -- the wire ---------------------------------------------------------------

def test_wire_length_is_144_bytes_packed_big_endian():
    """The format packs to the Entity State PDU's length with no
    articulation parameters, and every offset in FIELD_OFFSETS is where
    the format puts that field (summed here from the format's pieces)."""
    assert struct.calcsize(ESPDU_FORMAT) == ESPDU_LENGTH == 144
    assert ESPDU_FORMAT.startswith(">")
    sizes = [("protocol_version", 1), ("exercise_id", 1), ("pdu_type", 1),
             ("protocol_family", 1), ("timestamp", 4), ("length", 2), ("pdu_status", 1),
             ("padding", 1), ("entity_id", 6), ("force_id", 1),
             ("number_of_variable_parameters", 1), ("entity_type", 8),
             ("alternative_entity_type", 8), ("linear_velocity", 12), ("location", 24),
             ("orientation", 12), ("appearance", 4), ("dead_reckoning_algorithm", 1),
             ("dead_reckoning_other_parameters", 15), ("linear_acceleration", 12),
             ("angular_velocity", 12), ("marking_character_set", 1), ("marking", 11),
             ("capabilities", 4)]
    offset = 0
    for name, size in sizes:
        assert FIELD_OFFSETS[name] == offset, name
        offset += size
    assert offset == 144


def distinctive_pdu() -> EntityStatePdu:
    return EntityStatePdu(
        exercise_id=9, timestamp=timestamp_from_seconds(1234.5678), site=7, application=3,
        entity=42, force_id=2, entity_type=EntityType(1, 2, 225, 86, 8, 3, 4),
        alternative_entity_type=EntityType(1, 2, 71, 1, 5, 6, 7),
        linear_velocity=(1.5, -2.25, 3.125), location=(4198765.4321, 561234.5678, -4725678.9),
        orientation=(0.5, -0.25, 1.75), appearance=0xDEADBEEF,
        dead_reckoning_algorithm=DR_ALGORITHM_RVW,
        dead_reckoning_other_parameters=bytes(range(1, 16)),
        linear_acceleration=(-0.5, 0.75, -1.0), angular_velocity=(0.125, -0.0625, 0.03125),
        marking=b"B747", capabilities=0x12345678, pdu_status=5, padding=0)


def test_encode_decode_round_trip_is_byte_exact_for_every_field():
    """decode(encode(p)) is p (after float32 quantisation, which the
    values above avoid by being exactly representable), and encoding
    the decoded PDU gives the same bytes."""
    p = distinctive_pdu()
    data = p.encode()
    assert len(data) == 144
    back = decode(data)
    assert back == p.quantised()
    assert back.encode() == data
    # every field, named, so a swapped pair cannot hide behind equality
    d = back.to_dict()
    assert d["entity_id"] == {"site": 7, "application": 3, "entity": 42}
    assert d["force_id"] == 2 and d["exercise_id"] == 9
    assert d["entity_type"] == {"kind": 1, "domain": 2, "country": 225, "category": 86,
                                "subcategory": 8, "specific": 3, "extra": 4}
    assert d["alternative_entity_type"]["country"] == 71
    assert d["linear_velocity_ecef_mps"] == [1.5, -2.25, 3.125]
    assert d["location_ecef_m"] == [4198765.4321, 561234.5678, -4725678.9]
    assert d["orientation_rad"] == [0.5, -0.25, 1.75]
    assert d["appearance"] == 0xDEADBEEF and d["capabilities"] == 0x12345678
    assert d["dead_reckoning_algorithm"] == 4
    assert back.dead_reckoning_other_parameters == bytes(range(1, 16))
    assert d["linear_acceleration_ecef_mps2"] == [-0.5, 0.75, -1.0]
    assert d["angular_velocity_body_radps"] == [0.125, -0.0625, 0.03125]
    assert d["marking"] == "B747" and d["marking_character_set"] == 1
    assert back.pdu_status == 5
    assert abs(d["time_past_hour_s"] - 1234.5678) < 2e-6


def independent_decode(data: bytes) -> dict:
    """The Entity State PDU layout written out, offset by offset, with
    struct.unpack -- IEEE 1278.1-2012 7.2.2 with the version-7 header.
    This function is the test's own reading of the standard and calls
    nothing in core/interop."""
    assert len(data) == 144
    u8 = lambda o: struct.unpack(">B", data[o:o + 1])[0]          # noqa: E731
    u16 = lambda o: struct.unpack(">H", data[o:o + 2])[0]         # noqa: E731
    u32 = lambda o: struct.unpack(">I", data[o:o + 4])[0]         # noqa: E731
    f32x3 = lambda o: struct.unpack(">fff", data[o:o + 12])       # noqa: E731
    f64x3 = lambda o: struct.unpack(">ddd", data[o:o + 24])       # noqa: E731
    entity_type = lambda o: struct.unpack(">BBHBBBB", data[o:o + 8])  # noqa: E731
    return {
        "protocol_version": u8(0), "exercise_id": u8(1), "pdu_type": u8(2),
        "protocol_family": u8(3), "timestamp": u32(4), "length": u16(8),
        "pdu_status": u8(10), "padding": u8(11),
        "site": u16(12), "application": u16(14), "entity": u16(16),
        "force_id": u8(18), "n_variable_parameters": u8(19),
        "entity_type": entity_type(20), "alternative_entity_type": entity_type(28),
        "linear_velocity": f32x3(36), "location": f64x3(48), "orientation": f32x3(72),
        "appearance": u32(84), "dr_algorithm": u8(88), "dr_other": data[89:104],
        "linear_acceleration": f32x3(104), "angular_velocity": f32x3(116),
        "marking_charset": u8(128), "marking": data[129:140], "capabilities": u32(140),
        # the timestamp's own units: 31 bits of 3600/2^31 s past the hour, LSB = absolute
        "time_past_hour_s": (u32(4) >> 1) * 3600.0 / 2 ** 31, "absolute": bool(u32(4) & 1),
    }


def test_independent_decoder_agrees_with_decode_on_a_distinctive_pdu():
    data = distinctive_pdu().encode()
    mine = independent_decode(data)
    theirs = decode(data)
    assert mine["protocol_version"] == 7 and mine["pdu_type"] == 1
    assert mine["protocol_family"] == 1 and mine["length"] == 144
    assert (mine["site"], mine["application"], mine["entity"]) == (7, 3, 42)
    assert mine["entity_type"] == theirs.entity_type.to_tuple() == (1, 2, 225, 86, 8, 3, 4)
    assert mine["alternative_entity_type"] == theirs.alternative_entity_type.to_tuple()
    assert mine["linear_velocity"] == theirs.linear_velocity
    assert mine["location"] == theirs.location == (4198765.4321, 561234.5678, -4725678.9)
    assert mine["orientation"] == theirs.orientation
    assert mine["appearance"] == theirs.appearance == 0xDEADBEEF
    assert mine["dr_algorithm"] == 4 and mine["dr_other"] == bytes(range(1, 16))
    assert mine["linear_acceleration"] == theirs.linear_acceleration
    assert mine["angular_velocity"] == theirs.angular_velocity
    assert mine["marking_charset"] == 1 and mine["marking"] == b"B747".ljust(11, b"\0")
    assert mine["capabilities"] == 0x12345678
    assert mine["timestamp"] == theirs.timestamp and not mine["absolute"]
    assert abs(mine["time_past_hour_s"] - 1234.5678) < 2e-6


def test_independent_decoder_agrees_with_decode_on_a_telemetry_stream(tmp_path):
    """Every PDU of a fabricated run: the independent reading of each
    field equals dis.decode's, and the location equals pyproj's ECEF of
    the sample (a swapped velocity/location pair would break both)."""
    telemetry = make_telemetry(n=5)
    run = write_run(tmp_path / "run", telemetry, datum=MATTERHORN_DATUM)
    feed(run, tmp_path / "out" / "entity_state.dis", site=7, application=3, entity=42)
    data = (tmp_path / "out" / "entity_state.dis").read_bytes()
    assert len(data) == 5 * 144
    cols = telemetry["columns"]
    for i in range(5):
        chunk = data[i * 144:(i + 1) * 144]
        mine = independent_decode(chunk)
        theirs = decode(chunk)
        assert mine["location"] == theirs.location
        assert mine["linear_velocity"] == theirs.linear_velocity
        assert mine["orientation"] == theirs.orientation
        assert mine["angular_velocity"] == theirs.angular_velocity
        assert mine["linear_acceleration"] == theirs.linear_acceleration
        assert (mine["site"], mine["application"], mine["entity"]) == (7, 3, 42)
        assert mine["marking"] == b"c172p".ljust(11, b"\0")
        expected = pyproj_ecef(cols["lat_deg"][i], cols["lon_deg"][i],
                               cols["altitude_m"][i] + 52.52)
        assert math.dist(mine["location"], expected) < 1e-3
        assert abs(mine["time_past_hour_s"] - cols["t"][i]) < 2e-6


# -- geodesy ------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(ORIGINS))
def test_ecef_matches_pyproj_at_the_committed_origins(key):
    """Within 1e-3 m of pyproj EPSG:4979 -> EPSG:4978 at each origin,
    at the ellipsoid, at the origin's measured undulation, and 5 km up."""
    lat, lon, n = ORIGINS[key]
    for h in (0.0, n, n + 5000.0, -100.0):
        mine = geodesy.geodetic_to_ecef(lat, lon, h)
        ref = pyproj_ecef(lat, lon, h)
        assert math.dist(mine, ref) < 1e-3, (key, h, mine, ref)
        back = geodesy.ecef_to_geodetic(*mine)
        assert abs(back[0] - lat) < 1e-10 and abs(back[1] - lon) < 1e-10
        assert abs(back[2] - h) < 1e-6


def test_ecef_round_trip_over_the_globe_and_at_the_poles():
    rng = random.Random(7)
    for _ in range(500):
        lat, lon, h = rng.uniform(-90, 90), rng.uniform(-180, 180), rng.uniform(-500, 20000)
        x, y, z = geodesy.geodetic_to_ecef(lat, lon, h)
        assert math.dist((x, y, z), pyproj_ecef(lat, lon, h)) < 1e-3
        blat, blon, bh = geodesy.ecef_to_geodetic(x, y, z)
        assert abs(blat - lat) < 1e-9 and abs(bh - h) < 1e-5
        if abs(lat) < 89.999:
            assert abs((blon - lon + 180) % 360 - 180) < 1e-9
    for lat in (90.0, -90.0):
        x, y, z = geodesy.geodetic_to_ecef(lat, 0.0, 100.0)
        assert abs(math.hypot(x, y)) < 1e-6
        blat, _, bh = geodesy.ecef_to_geodetic(x, y, z)
        assert abs(blat - lat) < 1e-9 and abs(bh - 100.0) < 1e-5


def test_orientation_the_two_routes_reconstruct_the_same_body_axes():
    """ROUTE 1 composes body-from-ECEF from the NED attitude and the
    place; ROUTE 2 uses only the DIS (psi, theta, phi) derived from it.
    The rows (body x, y, z in ECEF) agree to 1e-9 over 2000 random
    cases, and the inverse recovers heading, pitch, roll."""
    rng = random.Random(11)
    worst = 0.0
    for _ in range(2000):
        lat, lon = rng.uniform(-89, 89), rng.uniform(-180, 180)
        heading, pitch, roll = rng.uniform(0, 360), rng.uniform(-85, 85), rng.uniform(-180, 180)
        route1 = geodesy.body_from_ecef_via_ned(lat, lon, heading, pitch, roll)
        psi, theta, phi = geodesy.dis_euler_from_ned(lat, lon, heading, pitch, roll)
        route2 = geodesy.body_from_ecef_via_dis(psi, theta, phi)
        worst = max(worst, max(abs(route1[i][j] - route2[i][j])
                               for i in range(3) for j in range(3)))
        h2, p2, r2 = geodesy.ned_from_dis_euler(lat, lon, psi, theta, phi)
        assert abs((h2 - heading + 180) % 360 - 180) < 1e-8
        assert abs(p2 - pitch) < 1e-8
        assert abs((r2 - roll + 180) % 360 - 180) < 1e-8
        # the rows are the body axes: unit, orthogonal, right-handed
        for row in route1:
            assert abs(math.hypot(*row) - 1.0) < 1e-12
    assert worst < 1e-9, worst


def test_orientation_body_axes_are_the_ned_axes_turned_by_the_attitude():
    """The body x axis in ECEF from the DIS angles equals north (level,
    heading 0), east (heading 90) and the pitched-up direction, computed
    here from the place alone, without the module's NED matrix."""
    lat, lon = 46.005, 7.72
    sl, cl = math.sin(math.radians(lat)), math.cos(math.radians(lat))
    so, co = math.sin(math.radians(lon)), math.cos(math.radians(lon))
    north = (-sl * co, -sl * so, cl)
    east = (-so, co, 0.0)
    down = (-cl * co, -cl * so, -sl)
    for heading, pitch, expected_x in (
            (0.0, 0.0, north), (90.0, 0.0, east),
            (0.0, 30.0, tuple(math.cos(math.radians(30)) * n - math.sin(math.radians(30)) * d
                              for n, d in zip(north, down)))):
        psi, theta, phi = geodesy.dis_euler_from_ned(lat, lon, heading, pitch, 0.0)
        body_x = geodesy.body_from_ecef_via_dis(psi, theta, phi)[0]
        assert math.dist(body_x, expected_x) < 1e-12, (heading, pitch)
    # and the body z axis of a level aircraft is down, whatever its heading
    for heading in (0.0, 45.0, 200.0):
        psi, theta, phi = geodesy.dis_euler_from_ned(lat, lon, heading, 0.0, 0.0)
        assert math.dist(geodesy.body_from_ecef_via_dis(psi, theta, phi)[2], down) < 1e-12


def test_orientation_hand_derived_case_level_east_at_45n_10e():
    """Derived by hand: a level aircraft heading east at 45 N, 10 E.
    Its body x is East = (-sin lon, cos lon, 0); rotating the ECEF X axis
    by psi about Z gives (cos psi, sin psi, 0), so psi = lon + 90 deg =
    100 deg and theta = 0. After that yaw the intermediate y' is
    (-sin psi, cos psi, 0) and z' is (0, 0, 1); a roll phi about x' must
    turn them onto body y = South = (sin lat cos lon, sin lat sin lon,
    -cos lat) and body z = Down = (-cos lat cos lon, -cos lat sin lon,
    -sin lat), which cos phi = sin phi = -sqrt(1/2), i.e. phi = -135 deg
    = -(90 + lat), does. So (psi, theta, phi) = (100, 0, -135) deg."""
    psi, theta, phi = geodesy.dis_euler_from_ned(45.0, 10.0, 90.0, 0.0, 0.0)
    assert abs(math.degrees(psi) - 100.0) < 1e-9
    assert abs(theta) < 1e-9
    assert abs(math.degrees(phi) + 135.0) < 1e-9


def test_rotation_vector_between_orientations_is_the_body_rate():
    """A heading change at zero pitch is a yaw rate r; a pitch change is
    q; a roll change is p; a heading change at pitch theta splits into
    r = psi_dot cos(theta) and p = -psi_dot sin(theta)."""
    lat, lon = 45.0, 10.0
    a = geodesy.body_from_ecef_via_ned(lat, lon, 30.0, 0.0, 0.0)
    for (h, p, r), expected in (((30.3, 0.0, 0.0), (0.0, 0.0, 3.0)),
                                ((30.0, 0.2, 0.0), (0.0, 2.0, 0.0)),
                                ((30.0, 0.0, 0.2), (2.0, 0.0, 0.0))):
        b = geodesy.body_from_ecef_via_ned(lat, lon, h, p, r)
        rates = [math.degrees(v) / 0.1 for v in geodesy.rotation_vector_between(a, b)]
        assert all(abs(x - e) < 1e-6 for x, e in zip(rates, expected)), (rates, expected)
    a = geodesy.body_from_ecef_via_ned(lat, lon, 30.0, 5.0, 0.0)
    b = geodesy.body_from_ecef_via_ned(lat, lon, 30.3, 5.0, 0.0)
    p, q, r = [math.degrees(v) / 0.1 for v in geodesy.rotation_vector_between(a, b)]
    assert abs(r - 3.0 * math.cos(math.radians(5))) < 1e-6
    assert abs(p + 3.0 * math.sin(math.radians(5))) < 1e-6 and abs(q) < 1e-6


def test_ned_velocity_rotated_into_ecef():
    """At (0, 0): north is +Z, east is +Y, down is -X in ECEF."""
    assert geodesy.ned_to_ecef_vector(0.0, 0.0, (1.0, 2.0, 3.0)) == pytest.approx((-3.0, 2.0, 1.0))
    v = geodesy.ned_to_ecef_vector(46.005, 7.72, (60.0, 10.0, -1.0))
    assert abs(math.hypot(*v) - math.hypot(60.0, 10.0, -1.0)) < 1e-9


# -- the timestamp ------------------------------------------------------------

def test_timestamp_units_are_2_to_the_31_per_hour():
    """One second is 2^31 / 3600 = 596523.24 units, rounded; the LSB is
    the absolute flag; the field wraps at the hour; the resolution is
    3600 / 2^31 s = 1.676 us and a round trip stays within it."""
    assert TIMESTAMP_UNITS_PER_HOUR == 2 ** 31
    assert timestamp_from_seconds(1.0) >> 1 == 596523
    assert timestamp_from_seconds(1.0) & 1 == 0
    assert timestamp_from_seconds(1.0, absolute=True) & 1 == 1
    assert timestamp_from_seconds(3600.0) >> 1 == 0
    assert timestamp_from_seconds(1800.0) >> 1 == 2 ** 30
    for t in (0.0, 0.008333333, 12.7, 3599.999999, 5000.25):
        seconds, absolute = seconds_from_timestamp(timestamp_from_seconds(t))
        assert abs(seconds - (t % 3600.0)) < 3600.0 / 2 ** 31 or abs(seconds - (t % 3600.0) + 3600.0) < 3600.0 / 2 ** 31
        assert not absolute
    assert timestamp_from_seconds(3599.9999999) < 2 ** 32


# -- streams --------------------------------------------------------------------

def test_a_stream_of_n_pdus_decodes_to_n(tmp_path):
    telemetry = make_telemetry(n=37)
    pdus = pdus_from_telemetry(telemetry, "c172p")
    assert len(pdus) == 37
    data = encode_stream(pdus)
    assert len(data) == 37 * 144
    assert len(decode_stream(data)) == 37
    path = tmp_path / "s.dis"
    path.write_bytes(data)
    assert [p.encode() for p in read_stream(path)] == [p.encode() for p in pdus]
    assert decode_stream(b"") == []


def test_a_stream_that_is_not_whole_pdus_refuses_by_name(tmp_path):
    data = encode_stream(pdus_from_telemetry(make_telemetry(n=3), "c172p"))
    with pytest.raises(DisError) as exc:
        decode_stream(data[:-10])
    assert exc.value.constraint == "interop.dis.stream"
    with pytest.raises(DisError) as exc:
        decode_stream(data + b"\x07")
    assert exc.value.constraint == "interop.dis.stream"
    with pytest.raises(DisError) as exc:
        read_stream(tmp_path / "absent.dis")
    assert exc.value.constraint == "interop.dis.stream"


def test_a_pdu_of_another_version_or_type_refuses_by_name():
    data = bytearray(distinctive_pdu().encode())
    data[0] = 6
    with pytest.raises(DisError) as exc:
        decode(bytes(data))
    assert exc.value.constraint == "interop.dis.stream"
    data[0] = 7
    data[2] = 2                     # Fire PDU
    with pytest.raises(DisError) as exc:
        decode(bytes(data))
    assert exc.value.constraint == "interop.dis.stream"
    data[2] = 1
    data[19] = 1                    # one variable parameter record claimed
    with pytest.raises(DisError) as exc:
        decode(bytes(data))
    assert exc.value.constraint == "interop.dis.stream"
    with pytest.raises(DisError):
        decode(bytes(data)[:100])


def test_entity_id_outside_16_bits_refuses_by_name():
    for kw in ({"site": 65536}, {"application": -1}, {"entity": 70000}, {"exercise_id": 256}):
        with pytest.raises(DisError) as exc:
            EntityStatePdu(**kw).encode()
        assert exc.value.constraint == "interop.dis.entity_id"
    assert len(EntityStatePdu(site=65535, application=0, entity=65535).encode()) == 144


# -- entity types -------------------------------------------------------------------

def test_entity_type_table_is_platform_air_with_stated_basis():
    """Every tabulated airframe is kind 1 (Platform), domain 2 (Air);
    those two fields are the only ones marked verified, the others say
    'unverified here' or 'not known here', and an airframe outside the
    table refuses by name rather than getting a guessed row."""
    assert set(ENTITY_TYPES) == {"c172p", "A320", "B747", "DHC6", "p51d", "f16"}
    for name, row in ENTITY_TYPES.items():
        t = row["type"]
        assert (t.kind, t.domain) == (1, 2), name
        assert row["basis"]["kind"].startswith("verified") and row["basis"]["domain"].startswith("verified")
        for key in ("country", "category", "subcategory"):
            assert "unverified here" in row["basis"][key] or "not known here" in row["basis"][key], (name, key)
        assert all(0 <= v <= 255 for v in (t.kind, t.domain, t.category, t.subcategory, t.specific, t.extra))
        assert 0 <= t.country <= 65535
    with pytest.raises(DisError) as exc:
        dis.entity_type_for("f15")
    assert exc.value.constraint == "interop.dis.airframe"


# -- the datum ------------------------------------------------------------------

def test_ellipsoidal_height_adds_the_run_datum_undulation(tmp_path):
    """A run whose datum block says N = +52.52 m: the first PDU's location
    is pyproj's ECEF of (lat, lon, altitude + 52.52) within 1e-3 m, and
    52.52 m from the ECEF of the orthometric altitude."""
    telemetry = make_telemetry(n=3)
    run = write_run(tmp_path / "run", telemetry, datum=MATTERHORN_DATUM)
    manifest = feed(run, tmp_path / "out" / "entity_state.dis")
    cols = telemetry["columns"]
    first = decode(read_stream(tmp_path / "out" / "entity_state.dis")[0].encode())
    with_n = pyproj_ecef(cols["lat_deg"][0], cols["lon_deg"][0], cols["altitude_m"][0] + 52.52)
    without_n = pyproj_ecef(cols["lat_deg"][0], cols["lon_deg"][0], cols["altitude_m"][0])
    assert math.dist(first.location, with_n) < 1e-3
    assert abs(math.dist(first.location, without_n) - 52.52) < 1e-3
    assert manifest["datum"]["undulation_m"] == 52.52
    assert manifest["datum"]["source_file"] == "capture_manifest.json"
    assert manifest["datum"]["handling"].startswith("datum: ellipsoidal height = JSBSim altitude + datum.undulation_m (+52.520 m")
    assert manifest["position_check"]["ok"] and manifest["position_check"]["residual_m"] < 1e-3
    assert manifest["position_check"]["first_sample_geodetic"]["h_ellipsoidal_m"] == pytest.approx(3052.52)


def test_datum_handling_is_named_in_all_three_cases(tmp_path):
    telemetry = make_telemetry(n=2)
    absent = write_run(tmp_path / "absent", telemetry, manifest=False)
    assert datum_for_run(absent) == {
        "undulation_m": 0.0, "source_file": None, "geoid_model": None,
        "vertical_datum_of_heights": None,
        "handling": "datum: orthometric treated as ellipsoidal (no geoid block in this run)"}
    flat = write_run(tmp_path / "flat", telemetry, datum={
        "vertical_datum_of_heights": "flat slab, spec terrain_elevation",
        "geoid_model": None, "undulation_m": None, "terrain_elevation_m": 0.0})
    block = datum_for_run(flat)
    assert block["undulation_m"] == 0.0 and block["source_file"] == "capture_manifest.json"
    assert "undulation_m null" in block["handling"]
    applied = write_run(tmp_path / "applied", telemetry, datum=MATTERHORN_DATUM)
    assert datum_for_run(applied)["undulation_m"] == 52.52
    # card.json is read when the manifest carries no block
    card_run = write_run(tmp_path / "card", telemetry, manifest=False)
    (card_run / "card.json").write_text(json.dumps({"datum": dict(MATTERHORN_DATUM, undulation_m=-25.94)}), encoding="utf-8")
    block = datum_for_run(card_run)
    assert block["undulation_m"] == -25.94 and block["source_file"] == "card.json"
    # no manifest at all: the aircraft comes from the provenance name minus -tecs
    manifest = feed(card_run, tmp_path / "card_out" / "entity_state.dis")
    assert manifest["aircraft"] == "c172p" and manifest["datum"]["undulation_m"] == -25.94


# -- dead reckoning -----------------------------------------------------------------

def test_dead_reckoning_vectors_are_the_forward_differences():
    """A heading rate of 3 deg/s, level: angular velocity (0, 0, 3 deg/s)
    in the body frame; a north acceleration of 0.5 m/s^2: the ECEF
    acceleration is that vector rotated by the place; the last PDU
    repeats the previous interval; a lone sample carries zeros."""
    telemetry = make_telemetry(n=4, heading_rate_dps=3.0, pitch=0.0, roll=0.0,
                               accel_north=0.5, lat0=20.0, lon0=-30.0)
    # hold the place still so the only change is the attitude and speed
    for k in ("lat_deg", "lon_deg", "altitude_m"):
        telemetry["columns"][k] = [telemetry["columns"][k][0]] * 4
    pdus = pdus_from_telemetry(telemetry, "DHC6")
    assert all(p.dead_reckoning_algorithm == 4 for p in pdus)
    for p in pdus:
        px, qx, rx = (math.degrees(v) for v in p.angular_velocity)
        assert abs(px) < 1e-4 and abs(qx) < 1e-4 and abs(rx - 3.0) < 1e-4
        expected = geodesy.ned_to_ecef_vector(20.0, -30.0, (0.5, 0.0, 0.0))
        assert math.dist(p.linear_acceleration, expected) < 1e-4
    assert pdus[-1].linear_acceleration == pdus[-2].linear_acceleration
    assert pdus[-1].angular_velocity == pdus[-2].angular_velocity
    lone = pdus_from_telemetry(make_telemetry(n=1), "c172p")
    assert lone[0].linear_acceleration == (0.0, 0.0, 0.0)
    assert lone[0].angular_velocity == (0.0, 0.0, 0.0)


# -- refusals over a run --------------------------------------------------------------

def test_a_directory_without_telemetry_refuses_by_name(tmp_path):
    with pytest.raises(DisError) as exc:
        feed(tmp_path, tmp_path / "x.dis")
    assert exc.value.constraint == "interop.dis.run"
    assert not (tmp_path / "x.dis").exists()


def test_telemetry_without_geodetic_columns_refuses_by_name(tmp_path):
    telemetry = make_telemetry(n=3)
    del telemetry["columns"]["lat_deg"]
    del telemetry["columns"]["lon_deg"]
    run = write_run(tmp_path / "run", telemetry)
    with pytest.raises(DisError) as exc:
        feed(run, tmp_path / "x.dis")
    assert exc.value.constraint == "interop.dis.channels"
    assert "lat_deg" in exc.value.message


def test_an_airframe_outside_the_table_refuses_by_name(tmp_path):
    run = write_run(tmp_path / "run", make_telemetry(n=3), aircraft="Shuttle")
    with pytest.raises(DisError) as exc:
        feed(run, tmp_path / "x.dis")
    assert exc.value.constraint == "interop.dis.airframe"


# -- the CLI on a real run ------------------------------------------------------------

def test_cli_writes_one_pdu_per_sample_of_a_real_run(real_run, tmp_path):
    out = tmp_path / "feed" / "entity_state.dis"
    result = subprocess.run(
        [PYTHON, "-m", "flightsim.dis", str(real_run), "--out", str(out),
         "--site", "7", "--application", "3", "--entity", "42"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    telemetry = json.loads((real_run / "telemetry.json").read_text(encoding="utf-8"))
    n = len(telemetry["columns"]["t"])
    assert n > 1
    manifest = json.loads((out.parent / "dis_manifest.json").read_text(encoding="utf-8"))
    assert manifest["pdu_count"] == manifest["samples"] == n
    assert manifest["one_pdu_per_sample"] is True
    assert manifest["stream_bytes"] == n * 144 == out.stat().st_size
    assert manifest["aircraft"] == "B747" and manifest["marking"] == "B747"
    assert manifest["entity_id"] == {"site": 7, "application": 3, "entity": 42}
    assert manifest["entity_type"] == {"kind": 1, "domain": 2, "country": 225, "category": 86,
                                       "subcategory": 8, "specific": 0, "extra": 0}
    assert "unverified here" in manifest["entity_type_basis"]["country"]
    assert manifest["datum"]["source_file"] == "capture_manifest.json"
    assert manifest["datum"]["undulation_m"] == 0.0
    assert "undulation_m null" in manifest["datum"]["handling"]
    # the stream: every PDU independently decoded against the telemetry
    data = out.read_bytes()
    cols = telemetry["columns"]
    for i in range(n):
        mine = independent_decode(data[i * 144:(i + 1) * 144])
        expected = pyproj_ecef(cols["lat_deg"][i], cols["lon_deg"][i], cols["altitude_m"][i])
        assert math.dist(mine["location"], expected) < 1e-3, i
        assert abs(mine["time_past_hour_s"] - cols["t"][i]) < 2e-6, i
        assert (mine["site"], mine["application"], mine["entity"]) == (7, 3, 42)
        assert mine["dr_algorithm"] == 4 and mine["protocol_version"] == 7
        speed = math.hypot(cols["v_north_mps"][i], cols["v_east_mps"][i], cols["v_down_mps"][i])
        assert abs(math.hypot(*mine["linear_velocity"]) - speed) < 1e-3
    # the record
    records = read_records(manifest["applied_variables"])
    assert manifest["applied_variables"]["record_version"] == RECORD_VERSION
    (record,) = records
    assert record["name"] == "interop.dis" and record["source"] == "derived"
    assert record["model_name"] == "IEEE 1278.1-2012 ESPDU"
    assert record["value"] == n and record["unit"] == "PDU"
    assert record["null_test"]["with"] < 1e-3 and record["null_test"]["threshold"] == 1e-3
    assert record["null_test"]["ok"] is True
    assert record["null_test"]["without"] > 6e6
    assert manifest["position_check"]["ok"] is True
    assert record["not_claimed"]
    assert "one PDU" in result.stdout or "Entity State PDU" in result.stdout
    # decode: one line per PDU plus the count line
    result = subprocess.run([PYTHON, "-m", "flightsim.dis", "--decode", str(out)],
                            cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith(f"{n} Entity State PDU(s)")
    assert len(lines) == n + 1
    assert "id 7:3:42" in lines[1] and "B747" in lines[1]
    assert f"h {cols['altitude_m'][0]:.2f} m" in lines[1]
    assert f"hdg {cols['heading_deg'][0] % 360:.2f}" in lines[1]


def test_cli_refuses_by_name_and_exits_2(tmp_path):
    result = subprocess.run([PYTHON, "-m", "flightsim.dis", str(tmp_path), "--out",
                             str(tmp_path / "x.dis")],
                            cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- interop.dis.run:")
    garbage = tmp_path / "g.dis"
    garbage.write_bytes(b"not a pdu stream at all")
    result = subprocess.run([PYTHON, "-m", "flightsim.dis", "--decode", str(garbage)],
                            cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- interop.dis.stream:")
    result = subprocess.run([PYTHON, "-m", "flightsim.dis"],
                            cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- interop.dis.arguments:")


# -- the culture ------------------------------------------------------------------------

def test_the_producer_does_not_import_pyproj_for_its_own_geodesy():
    """pyproj is the independent reference (position_check and these
    tests); the conversion the PDUs carry is core/interop/geodesy.py,
    which imports nothing but math."""
    source = (REPO / "core/interop/geodesy.py").read_text(encoding="utf-8")
    imports = [line.strip() for line in source.splitlines()
               if line.startswith(("import ", "from "))]
    assert not any("pyproj" in line or "numpy" in line for line in imports), imports
    assert "import math" in imports


def test_docstrings_say_what_is_not_claimed():
    for rel in ("core/interop/dis.py", "core/interop/geodesy.py", "flightsim/dis.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "NOT claimed" in text or "not claimed" in text.lower(), rel
        assert all(ord(c) < 128 for c in text), f"{rel}: non-ASCII"


# =========================================================================
# D2: the entity-type table, the timestamp modes, the marking, the geodetic
# frame check and the RVW dead reckoning from recorded quantities
# (core/interop/dis.py, extended in place; the stream is tests/test_dis_stream.py).
# =========================================================================

import yaml

from core.interop.dis import (
    ENTITY_TYPE_FIELDS, ENTITY_TYPE_POLICIES, ENTITY_TYPE_TABLE_PATH, TIMESTAMP_MODES,
    central_difference, entity_type_row, load_entity_type_table, marking_for, parse_epoch,
    rvw_vectors, sample_frames, standard_entity_type, timestamp_for,
)
from core.scenario.blocks import configured_airframes


def _filled_table(tmp_path: Path, aircraft: str = "c172p", **fields) -> Path:
    table = yaml.safe_load(ENTITY_TYPE_TABLE_PATH.read_text(encoding="utf-8"))
    septuplet = {"kind": 1, "domain": 2, "country": 225, "category": 84, "subcategory": 1,
                 "specific": 0, "extra": 0}
    septuplet.update(fields)
    table["airframes"][aircraft]["entity_type"] = septuplet
    table["airframes"][aircraft]["reason"] = "test: a row filled as the standard's would be"
    path = tmp_path / "filled.yaml"
    path.write_text(yaml.safe_dump(table, sort_keys=False), encoding="utf-8")
    return path


# -- the standard table ships empty ---------------------------------------------------

def test_the_standard_table_has_a_row_per_configured_airframe_and_ships_empty():
    """One row per assets/aircraft_config airframe, each citing the
    standard and carrying a null septuplet with the reason, so the
    standard policy refuses dis.entity_type_unknown for every one of
    them until someone with the document fills a row; the file is ASCII."""
    table = load_entity_type_table()
    assert table["table_version"] == 1
    assert sorted(table["airframes"]) == configured_airframes()
    assert table["reason"] == "entered from the standard, never guessed"
    assert "SISO-REF-010" in table["standard"]["name"]
    assert "unverified here" in table["standard"]["edition"]
    for key, row in table["airframes"].items():
        assert row["entity_type"] is None, key
        assert row["reason"] == "entered from the standard, never guessed", key
        assert "SISO-REF-010" in row["siso_reference"], key
        with pytest.raises(DisError) as exc:
            standard_entity_type(key)
        assert exc.value.constraint == "dis.entity_type_unknown"
        assert "never guessed" in exc.value.message and key in exc.value.message
    assert ENTITY_TYPE_TABLE_PATH.read_text(encoding="utf-8").isascii()
    with pytest.raises(DisError) as exc:
        standard_entity_type("Shuttle")
    assert exc.value.constraint == "dis.entity_type_unknown"


def test_a_filled_row_is_read_from_the_standard_table_and_a_malformed_one_refuses(tmp_path):
    table = load_entity_type_table(_filled_table(tmp_path))
    entity_type, row = standard_entity_type("c172p", table)
    assert entity_type.to_tuple() == (1, 2, 225, 84, 1, 0, 0)
    assert row["reason"].startswith("test:")
    resolved = entity_type_row("c172p", "standard", table)
    assert resolved["source"] == "standard" and resolved["septuplet"]["country"] == 225
    assert all("entered from the standard" in b for b in resolved["basis"].values())
    # A field out of range, a missing field, a wrong shape: refused, never clipped.
    for bad in ({"country": 70000}, {"kind": 256}, {"extra": -1}, {"kind": True}):
        with pytest.raises(DisError) as exc:
            standard_entity_type("c172p", load_entity_type_table(_filled_table(tmp_path, **bad)))
        assert exc.value.constraint == "dis.entity_type_unknown"
    broken = yaml.safe_load(_filled_table(tmp_path).read_text(encoding="utf-8"))
    del broken["airframes"]["c172p"]["entity_type"]["extra"]
    with pytest.raises(DisError) as exc:
        standard_entity_type("c172p", broken)
    assert exc.value.constraint == "dis.entity_type_unknown"
    # An absent or unreadable table is the same refusal.
    with pytest.raises(DisError) as exc:
        load_entity_type_table(tmp_path / "absent.yaml")
    assert exc.value.constraint == "dis.entity_type_unknown"
    (tmp_path / "wrong.yaml").write_text("table_version: 2\nairframes: []\n", encoding="utf-8")
    with pytest.raises(DisError) as exc:
        load_entity_type_table(tmp_path / "wrong.yaml")
    assert exc.value.constraint == "dis.entity_type_unknown"


def test_the_three_policies_resolve_as_documented():
    """standard refuses while the table is empty; fallback is the
    documented in-tree ENTITY_TYPES row (from memory, 'unverified here',
    saying the standard row is empty); unspecified is 0 = Other in every
    field with the septuplet recorded as absent; an unknown policy is a
    programming error and an airframe outside the fallback refuses
    interop.dis.airframe as in batch 1."""
    assert ENTITY_TYPE_POLICIES == ("standard", "fallback", "unspecified")
    with pytest.raises(DisError) as exc:
        entity_type_row("B747", "standard")
    assert exc.value.constraint == "dis.entity_type_unknown"
    fallback = entity_type_row("B747", "fallback")
    assert fallback["source"] == "fallback"
    assert fallback["type"] == ENTITY_TYPES["B747"]["type"]
    assert fallback["septuplet"] == ENTITY_TYPES["B747"]["type"].to_dict()
    assert "unverified here" in fallback["basis"]["country"]
    assert "row is empty" in fallback["basis"]["fallback"]
    assert fallback["standard_row"]["entity_type"] is None
    f16 = entity_type_row("f16", "fallback")
    assert "row is absent" in f16["basis"]["fallback"] and f16["standard_row"] is None
    unspecified = entity_type_row("B747", "unspecified")
    assert unspecified["type"] == EntityType() and unspecified["septuplet"] is None
    assert unspecified["type"].to_tuple() == (0,) * 7
    assert "never guessed" in unspecified["basis"]["all"]
    with pytest.raises(DisError) as exc:
        entity_type_row("Shuttle", "fallback")
    assert exc.value.constraint == "interop.dis.airframe"
    with pytest.raises(ValueError):
        entity_type_row("B747", "guess")
    assert ENTITY_TYPE_FIELDS == ("kind", "domain", "country", "category", "subcategory",
                                  "specific", "extra")


# -- the timestamp modes -----------------------------------------------------------

def test_absolute_timestamps_carry_the_epoch_and_the_lsb_and_relative_stay_as_batch_1():
    """absolute: units past the hour of epoch + t with LSB 1, computed by
    hand here from the epoch's seconds past its hour; relative: exactly
    batch 1's field (LSB 0); the modulo rollover at the hour in both."""
    assert TIMESTAMP_MODES == ("relative", "absolute")
    epoch = parse_epoch("2026-09-29T10:15:30Z")           # 10:15:30 UTC: 930 s past the hour
    assert epoch % 3600.0 == pytest.approx(930.0)
    assert parse_epoch("2026-09-29T12:15:30+02:00") == epoch       # the same instant
    field = timestamp_for(12.5, "absolute", epoch)
    assert field & 1 == 1
    assert field >> 1 == int(round((930.0 + 12.5) / 3600.0 * 2 ** 31))
    assert timestamp_for(12.5, "relative") == timestamp_from_seconds(12.5)
    assert timestamp_for(12.5, "relative") & 1 == 0
    # Past the hour boundary: epoch 930 s + t 2670 s = 3600 s -> 0 units (the wrap).
    assert timestamp_for(2670.0, "absolute", epoch) >> 1 == 0
    assert timestamp_for(2670.0 + 3599.9999999, "absolute", epoch) < 2 ** 32
    # The epoch's own seconds are taken past ITS hour first: a 1.7e9 s
    # epoch loses nothing to the 1.676 us unit (the hand value above).
    seconds, absolute = seconds_from_timestamp(field)
    assert absolute and abs(seconds - 942.5) < 3600.0 / 2 ** 31


def test_absolute_without_an_epoch_refuses_by_name_and_a_bad_epoch_too():
    with pytest.raises(DisError) as exc:
        parse_epoch(None)
    assert exc.value.constraint == "dis.timestamp_epoch_missing"
    for bad in ("", "   ", "yesterday", "2026-09-29T10:00:00"):     # the last: no UTC offset
        with pytest.raises(DisError) as exc:
            parse_epoch(bad)
        assert exc.value.constraint == "dis.timestamp_epoch_missing", bad
    with pytest.raises(DisError) as exc:
        timestamp_for(1.0, "absolute", None)
    assert exc.value.constraint == "dis.timestamp_epoch_missing"
    with pytest.raises(DisError) as exc:
        timestamp_for(1.0, "sidereal")
    assert exc.value.constraint == "dis.timestamp_mode"


# -- the marking ----------------------------------------------------------------------

def test_the_marking_comes_from_the_run_and_over_eleven_ascii_refuses_by_name():
    assert marking_for("", "c172p") == (b"c172p", "derived")
    assert marking_for(None, "B747") == (b"B747", "derived")
    assert marking_for("N12345", "c172p") == (b"N12345", "user")
    assert marking_for("ABCDEFGHIJK", "x") == (b"ABCDEFGHIJK", "user")      # exactly 11
    for bad, aircraft in (("ABCDEFGHIJKL", "x"), ("", "an-airframe-key-too-long"),
                          ("café", "x")):
        with pytest.raises(DisError) as exc:
            marking_for(bad, aircraft)
        assert exc.value.constraint == "dis.marking_too_long"


# -- the geodetic frame per sample --------------------------------------------------------

def test_a_recorded_frame_without_a_geodetic_place_refuses_by_name():
    telemetry = make_telemetry(n=4)
    cols = telemetry["columns"]
    for missing in ("lat_deg", "lon_deg"):
        broken = {k: v for k, v in cols.items() if k != missing}
        with pytest.raises(DisError) as exc:
            sample_frames(broken)
        assert exc.value.constraint == "dis.frame_without_geodetic"
        assert missing in exc.value.message
    without_height = {k: v for k, v in cols.items() if k != "altitude_m"}
    with pytest.raises(DisError) as exc:
        sample_frames(without_height)
    assert exc.value.constraint == "dis.frame_without_geodetic"
    for value in (float("nan"), None, float("inf")):
        broken = {k: list(v) for k, v in cols.items()}
        broken["lat_deg"][2] = value
        with pytest.raises(DisError) as exc:
            sample_frames(broken)
        assert exc.value.constraint == "dis.frame_without_geodetic"
        assert "sample 2" in exc.value.message
    broken = {k: list(v) for k, v in cols.items()}
    broken["heading_deg"] = broken["heading_deg"][:-1]
    with pytest.raises(DisError) as exc:
        sample_frames(broken)
    assert exc.value.constraint == "dis.frame_without_geodetic"


def test_the_geoid_is_applied_at_export_from_the_recorded_hae_column():
    """With D1's hae_m column the location is pyproj's ECEF of (lat, lon,
    hae_m): the radial error with N is at floating point and without N
    equals N0 (52.52 m here) -- measured, the null test's two sides."""
    telemetry = make_telemetry(n=3)
    cols = telemetry["columns"]
    n0 = 52.52
    cols["undulation_m"] = [n0] * 3
    cols["hae_m"] = [a + n0 for a in cols["altitude_m"]]
    frames, height = sample_frames(cols)
    assert height["hae_source"].startswith("hae_m:")
    for i, frame in enumerate(frames):
        assert frame["hae_m"] == cols["altitude_m"][i] + n0 and frame["undulation_m"] == n0
        with_n = pyproj_ecef(cols["lat_deg"][i], cols["lon_deg"][i], cols["altitude_m"][i] + n0)
        without_n = pyproj_ecef(cols["lat_deg"][i], cols["lon_deg"][i], cols["altitude_m"][i])
        assert math.dist(frame["location"], with_n) < 1e-6
        assert abs(math.dist(frame["location"], without_n) - n0) < 1e-3
        assert abs((math.hypot(*frame["location"]) - math.hypot(*without_n)) - n0) < 1e-3
    # Without the column: altitude_m + the datum handling's N (batch 1's three cases).
    del cols["hae_m"], cols["undulation_m"]
    frames, height = sample_frames(cols, {"undulation_m": n0, "handling": "datum: test"})
    assert "+52.520 m" in height["hae_source"]
    assert frames[0]["hae_m"] == cols["altitude_m"][0] + n0 and frames[0]["undulation_m"] is None
    frames, height = sample_frames(cols, None)
    assert frames[0]["hae_m"] == cols["altitude_m"][0] and "no geoid block" in height["hae_source"]


# -- DRM 4 from recorded quantities only -----------------------------------------------

def test_the_rvw_acceleration_is_the_central_difference_of_the_recorded_ecef_velocity():
    """v_north = c t^2: the central difference is exactly 2 c t at every
    interior sample (a forward difference misses by c dt); one-sided at
    the ends; p and q are the recorded rates; r is the recorded yaw rate
    when present, else the attitude's central difference."""
    c, dt, n = 0.4, 0.1, 7
    telemetry = make_telemetry(n=n, dt=dt, heading_rate_dps=3.0, pitch=0.0, roll=0.0,
                               lat0=20.0, lon0=-30.0)
    cols = telemetry["columns"]
    for k in ("lat_deg", "lon_deg", "altitude_m"):
        cols[k] = [cols[k][0]] * n
    cols["v_north_mps"] = [60.0 + c * t * t for t in cols["t"]]
    cols["roll_rate_dps"] = [1.5] * n
    cols["pitch_rate_dps"] = [-2.5] * n
    frames, _ = sample_frames(cols)
    vectors, source = rvw_vectors(frames, cols)
    assert "central difference" in source["linear_acceleration"]
    assert source["r"].startswith("yaw_rate_dps not recorded")
    for i in range(1, n - 1):
        expected = geodesy.ned_to_ecef_vector(20.0, -30.0, (2.0 * c * cols["t"][i], 0.0, 0.0))
        assert math.dist(vectors[i][0], expected) < 1e-9, i
        forward = geodesy.ned_to_ecef_vector(20.0, -30.0, (2.0 * c * cols["t"][i] + c * dt, 0.0, 0.0))
        assert math.dist(vectors[i][0], forward) > 0.9 * c * dt          # not the forward difference
        p, q, r = vectors[i][1]
        assert math.degrees(p) == pytest.approx(1.5) and math.degrees(q) == pytest.approx(-2.5)
        assert math.degrees(r) == pytest.approx(3.0, abs=1e-4)
    first = geodesy.ned_to_ecef_vector(20.0, -30.0, (c * dt, 0.0, 0.0))        # one-sided
    assert math.dist(vectors[0][0], first) < 1e-9
    assert math.dist(central_difference([(0.0,), (1.0,), (4.0,)], [0.0, 1.0, 2.0], 1), (2.0,)) < 1e-12
    assert central_difference([(0.0,), (1.0,), (4.0,)], [0.0, 1.0, 2.0], 2) == (3.0,)
    assert central_difference([(5.0, 6.0)], [0.0], 0) == (0.0, 0.0)
    # A recorded yaw rate is taken as it is.
    cols["yaw_rate_dps"] = [7.0] * n
    vectors, source = rvw_vectors(frames, cols)
    assert source["r"].startswith("recorded yaw_rate_dps")
    assert all(math.degrees(v[1][2]) == pytest.approx(7.0) for v in vectors)


def test_d2_texts_are_ascii_and_say_what_is_not_claimed():
    for rel in ("core/interop/dis.py", "core/interop/dis_stream.py", "flightsim/dis.py",
                "assets/dis_entity_types.yaml"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert text.isascii(), rel
    assert "NOT claimed" in (REPO / "core/interop/dis_stream.py").read_text(encoding="utf-8")
