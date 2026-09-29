"""D2, the full-rate Entity State PDU log (core/interop/dis_stream.py):
the stream and its index, the thresholded emitter's measured claim, the
UDP sender off by default and refused in a campaign, the record, the
CLI on a real capture, and the verifier's independent round trip
(``VERIFY_DIS_PATCH`` below, executed here against the verifier's own
Check and pinned once integrated) with its corruption tests.

Every number asserted here was measured on fabricated recordings of
known geometry and on one real capture (examples/cameras_multi.yaml).
Not measured here: any DIS consumer reading the stream (Wireshark's
dissector or the opendis package is the networked step); the SISO
septuplets (the standard table ships empty).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import socket
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from pyproj import Transformer

from core.interop import dis_stream as S
from core.interop.dis import DisError, EntityStatePdu, decode, decode_stream
from core.records import RECORD_VERSION, AppliedVariable, read_records
from tests.test_dis import MATTERHORN_DATUM, independent_decode, make_telemetry, write_run

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
TO_ECEF = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)

FALLBACK = S.StreamOptions(entity_type_policy="fallback")


def geo_telemetry(n=12, n0=52.52, **kw):
    """A fabricated recording with D1's channels (undulation_m, hae_m)."""
    telemetry = make_telemetry(n=n, **kw)
    cols = telemetry["columns"]
    cols["undulation_m"] = [n0] * n
    cols["hae_m"] = [a + n0 for a in cols["altitude_m"]]
    return telemetry


def manoeuvre_telemetry(n=120, dt=0.1, n0=52.52):
    """A turning, accelerating, climbing recording for the thresholded
    emitter, kinematically consistent (the place integrated from the
    recorded velocity, the heading from the yaw rate, the rates the
    derivatives of the attitude): heading rate 6 deg/s, a north
    acceleration, a varying bank and pitch, so both thresholds are
    exercised."""
    from core.interop import geodesy

    cols = {k: [] for k in ("t", "lat_deg", "lon_deg", "altitude_m", "heading_deg",
                            "pitch_deg", "roll_deg", "v_north_mps", "v_east_mps",
                            "v_down_mps", "roll_rate_dps", "pitch_rate_dps",
                            "undulation_m", "hae_m")}
    lat, lon, hae = 46.0, 7.7, 3052.52
    for i in range(n):
        t = i * dt
        v_n, v_e, v_d = 60.0 + 0.8 * t, 10.0 + 30.0 * math.sin(0.3 * t), -4.0
        cols["t"].append(t)
        cols["lat_deg"].append(lat)
        cols["lon_deg"].append(lon)
        cols["hae_m"].append(hae)
        cols["altitude_m"].append(hae - n0)
        cols["undulation_m"].append(n0)
        cols["heading_deg"].append((30.0 + 6.0 * t) % 360.0)
        cols["pitch_deg"].append(3.0 + 2.0 * math.sin(0.7 * t))
        cols["roll_deg"].append(25.0 * math.sin(0.4 * t))
        cols["v_north_mps"].append(v_n)
        cols["v_east_mps"].append(v_e)
        cols["v_down_mps"].append(v_d)
        cols["roll_rate_dps"].append(25.0 * 0.4 * math.cos(0.4 * t))
        cols["pitch_rate_dps"].append(2.0 * 0.7 * math.cos(0.7 * t))
        # the next place: the velocity at the midpoint of the step
        tm = t + dt / 2.0
        vm = (60.0 + 0.8 * tm, 10.0 + 30.0 * math.sin(0.3 * tm), -4.0)
        rn = geodesy.prime_vertical_radius(math.radians(lat))
        rm = rn * (1.0 - geodesy.WGS84_E2) / (1.0 - geodesy.WGS84_E2 * math.sin(math.radians(lat)) ** 2)
        lat += math.degrees(vm[0] * dt / (rm + hae))
        lon += math.degrees(vm[1] * dt / ((rn + hae) * math.cos(math.radians(lat))))
        hae -= vm[2] * dt
    return {"provenance": {"aircraft": {"name": "c172p-tecs"}}, "interval_s": dt,
            "samples": n, "events": [], "derived": ["undulation_m", "hae_m"], "columns": cols}


# -- the stream and the index -----------------------------------------------------------

def test_the_stream_is_one_pdu_per_sample_with_an_index_the_reader_checks(tmp_path):
    telemetry = geo_telemetry(n=12)
    index = S.write_stream(tmp_path, telemetry=telemetry, aircraft="c172p", options=FALLBACK)
    data = (tmp_path / S.STREAM_FILE).read_bytes()
    assert len(data) == 12 * 144 == index["stream_bytes"]
    assert index["pdu_count"] == 12 and index["byte_offsets"] == [i * 144 for i in range(12)]
    assert index["sample_indices"] == list(range(12)) and index["samples"] == 12
    assert index["timestamp_mode"] == "relative" and index["epoch"] is None
    assert index["interval_s"] == 0.1 and index["emitter"]["kind"] == "full_rate"
    assert index["emitter"]["emitted"] == 12 and index["emitter"]["suppressed"] == 0
    assert index["stream_sha256"] == hashlib.sha256(data).hexdigest()
    assert index["marking"] == {"text": "c172p", "source": "derived", "character_set": "1 (ASCII)",
                                "bytes": 11}
    assert index["entity_type"]["source"] == "fallback"
    assert index["datum"]["hae_source"].startswith("hae_m:")
    assert index["udp"] == {"sent": False, "note": "off by default: no datagram was sent"}
    written = json.loads((tmp_path / S.INDEX_FILE).read_text(encoding="utf-8"))
    assert written == index
    assert (tmp_path / S.INDEX_FILE).read_text(encoding="utf-8").isascii()
    # Every PDU, read by the test's own decoder: the place is pyproj's of
    # (lat, lon, hae_m), the timestamp the sample's, the ids the options'.
    cols = telemetry["columns"]
    for i in range(12):
        mine = independent_decode(data[i * 144:(i + 1) * 144])
        expected = TO_ECEF.transform(cols["lon_deg"][i], cols["lat_deg"][i], cols["hae_m"][i])
        assert math.dist(mine["location"], expected) < 1e-3, i
        assert abs(mine["time_past_hour_s"] - cols["t"][i]) < 2e-6 and not mine["absolute"]
        assert (mine["site"], mine["application"], mine["entity"]) == (1, 1, 1)
        assert mine["dr_algorithm"] == 4 and mine["marking"] == b"c172p".ljust(11, b"\0")
    # The reader checks the index against the bytes and refuses a stale one.
    assert S.read_index(tmp_path)["pdu_count"] == 12
    (tmp_path / S.STREAM_FILE).write_bytes(data[:-144])
    with pytest.raises(DisError) as exc:
        S.read_index(tmp_path)
    assert exc.value.constraint == "interop.dis.stream"
    with pytest.raises(DisError) as exc:
        S.read_index(tmp_path / "nowhere")
    assert exc.value.constraint == "interop.dis.stream"


def test_the_frame_keys_name_the_pdu_of_a_sample():
    index = {"sample_indices": [0, 3, 7], "byte_offsets": [0, 144, 288]}
    assert S.frame_keys_for(index, 0) == {"pdu_index": 0, "byte_offset": 0}
    assert S.frame_keys_for(index, 2) == {"pdu_index": 0, "byte_offset": 0}
    assert S.frame_keys_for(index, 3) == {"pdu_index": 1, "byte_offset": 144}
    assert S.frame_keys_for(index, 9) == {"pdu_index": 2, "byte_offset": 288}
    manifest = {"frames": [{"sample_index": 4}, {"sample_index": 7}, {"other": 1}]}
    assert S.attach_frame_keys(manifest, index) == 2
    assert manifest["frames"][0]["dis"] == {"pdu_index": 1, "byte_offset": 144}
    assert manifest["frames"][1]["dis"] == {"pdu_index": 2, "byte_offset": 288}
    assert "dis" not in manifest["frames"][2]
    assert S.FRAME_KEYS == ("dis.pdu_index", "dis.byte_offset")


def test_options_and_the_spec_block_refuse_by_name():
    assert S.dis_spec_problems(None) == [] and S.dis_spec_problems({}) == []
    names = lambda values: [p.constraint for p in S.dis_spec_problems(values)]   # noqa: E731
    assert names({"site": 65536}) == ["interop.dis.entity_id"]
    assert names({"application": -1, "entity": "x"}) == ["interop.dis.entity_id"] * 2
    assert names({"entity": 7.0}) == []                    # an integral float is an integer
    assert names({"force_id": 256}) == ["dis.force_id"]
    assert names({"marking": "ABCDEFGHIJKL"}) == ["dis.marking_too_long"]
    assert names({"marking": "café"}) == ["dis.marking_too_long"]
    assert names({"timestamp_mode": "sidereal"}) == ["dis.timestamp_mode"]
    assert names({"site": 7, "force_id": 1, "marking": "N12345", "timestamp_mode": "absolute"}) == []
    telemetry = geo_telemetry(n=3)
    for options, name in ((S.StreamOptions(site=70000), "interop.dis.entity_id"),
                          (S.StreamOptions(force_id=300), "dis.force_id"),
                          (S.StreamOptions(marking="ABCDEFGHIJKL"), "dis.marking_too_long"),
                          (S.StreamOptions(timestamp_mode="absolute"), "dis.timestamp_epoch_missing"),
                          (S.StreamOptions(timestamp_mode="lunar"), "dis.timestamp_mode"),
                          (S.StreamOptions(), "dis.entity_type_unknown")):
        with pytest.raises(DisError) as exc:
            S.build_stream(telemetry, None, "c172p", options)
        assert exc.value.constraint == name, options
    with pytest.raises(ValueError):
        S.build_stream(telemetry, None, "c172p", S.StreamOptions(emitter="sometimes"))
    with pytest.raises(DisError) as exc:
        S.build_stream({"columns": {"t": []}}, None, "c172p", FALLBACK)
    assert exc.value.constraint == "dis.frame_without_geodetic"


def test_absolute_timestamps_and_the_stated_marking_reach_the_wire(tmp_path):
    options = S.StreamOptions(entity_type_policy="unspecified", timestamp_mode="absolute",
                              epoch="2026-09-29T10:15:30Z", marking="N12345", force_id=1,
                              site=7, application=3, entity=42, exercise_id=9)
    index = S.write_stream(tmp_path, telemetry=geo_telemetry(n=4), aircraft="c172p", options=options)
    data = (tmp_path / S.STREAM_FILE).read_bytes()
    for i in range(4):
        mine = independent_decode(data[i * 144:(i + 1) * 144])
        assert mine["absolute"]
        assert abs(mine["time_past_hour_s"] - (930.0 + 0.1 * i)) < 2e-6
        assert mine["marking"] == b"N12345".ljust(11, b"\0") and mine["force_id"] == 1
        assert mine["entity_type"] == (0,) * 7 and mine["exercise_id"] == 9
        assert (mine["site"], mine["application"], mine["entity"]) == (7, 3, 42)
    assert index["timestamp"]["lsb"] == 1 and index["timestamp"]["epoch_unix_s"] % 3600 == pytest.approx(930.0)
    assert index["marking"]["source"] == "user"
    assert index["entity_type"]["septuplet"] is None and "never guessed" in index["entity_type"]["reason"]
    record = read_records(index["applied_variables"])[0]
    assert record["parameters"]["entity_type"] is None
    assert record["parameters"]["timestamp_mode"] == "absolute"
    assert record["parameters"]["epoch"] == "2026-09-29T10:15:30Z"


# -- the thresholded emitter's measured claim ------------------------------------------

def test_the_thresholded_stream_reconstructs_the_full_rate_one_within_the_thresholds(tmp_path):
    """On a turning, accelerating flight the thresholded emitter writes
    fewer PDUs than samples, and the RVW extrapolation from them (the
    consumer's arithmetic) lands within the thresholds at EVERY
    full-rate sample -- measured and written into the index; a tighter
    threshold emits more, the heartbeat bounds the gap."""
    telemetry = manoeuvre_telemetry()
    loose = S.StreamOptions(entity_type_policy="fallback", emitter="thresholded",
                            position_threshold_m=1.0, orientation_threshold_rad=math.radians(3.0),
                            heartbeat_s=5.0)
    index = S.write_stream(tmp_path, telemetry=telemetry, aircraft="c172p", options=loose)
    emitter = index["emitter"]
    assert emitter["kind"] == "thresholded" and emitter["emitted"] == index["pdu_count"]
    assert 1 < index["pdu_count"] < 120 and emitter["suppressed"] == 120 - index["pdu_count"]
    assert index["sample_indices"][0] == 0 and index["sample_indices"] == sorted(set(index["sample_indices"]))
    rec = emitter["reconstruction"]
    assert rec["within_thresholds"] is True and rec["samples"] == 120
    assert 0.0 < rec["position_error_max_m"] <= 1.0
    assert 0.0 < rec["orientation_error_max_rad"] <= math.radians(3.0)
    # The claim re-measured here from the WRITTEN bytes with the module's
    # own extrapolation, and independently: position by the kinematic
    # formula written out.
    pdus = decode_stream((tmp_path / S.STREAM_FILE).read_bytes())
    from core.interop.dis import sample_frames
    frames, _ = sample_frames(telemetry["columns"])
    worst = 0.0
    k = 0
    for i, frame in enumerate(frames):
        while k + 1 < len(pdus) and index["sample_indices"][k + 1] <= i:
            k += 1
        p = pdus[k]
        dt = frame["t_s"] - frames[index["sample_indices"][k]]["t_s"]
        predicted = [p.location[j] + p.linear_velocity[j] * dt + 0.5 * p.linear_acceleration[j] * dt * dt
                     for j in range(3)]
        worst = max(worst, math.dist(predicted, frame["location"]))
    assert worst == pytest.approx(rec["position_error_max_m"], abs=1e-9) and worst <= 1.0
    tight = S.StreamOptions(entity_type_policy="fallback", emitter="thresholded",
                            position_threshold_m=0.05, orientation_threshold_rad=math.radians(0.2),
                            heartbeat_s=5.0)
    tighter = S.write_stream(tmp_path / "tight", telemetry=telemetry, aircraft="c172p", options=tight)
    assert tighter["pdu_count"] > index["pdu_count"]
    assert tighter["emitter"]["reconstruction"]["position_error_max_m"] <= 0.05
    # Gaps never exceed the heartbeat.
    times = [telemetry["columns"]["t"][s] for s in index["sample_indices"]]
    assert max(b - a for a, b in zip(times, times[1:])) <= 5.0 + 1e-9
    record = read_records(index["applied_variables"])[0]
    assert record["model"].startswith("DR-thresholded")
    assert record["parameters"]["emitter"] == "thresholded"
    assert record["parameters"]["emitter_parameters"]["heartbeat_s"] == 5.0


def test_the_extrapolation_turns_the_attitude_the_way_the_rates_say():
    """A PDU with a pure yaw rate of 10 deg/s: after 1 s the extrapolated
    body-from-ECEF is the attitude at heading + 10 deg (the passive
    Rodrigues sign is the one rotation_vector_between measures)."""
    from core.interop import geodesy
    lat, lon = 45.0, 10.0
    psi, theta, phi = geodesy.dis_euler_from_ned(lat, lon, 30.0, 0.0, 0.0)
    pdu = EntityStatePdu(orientation=(psi, theta, phi), angular_velocity=(0.0, 0.0, math.radians(10.0)),
                         location=(1.0, 2.0, 3.0), linear_velocity=(1.0, 0.0, 0.0),
                         linear_acceleration=(0.0, 2.0, 0.0)).quantised()
    location, attitude = S.extrapolate(pdu, 1.0)
    assert location == pytest.approx((2.0, 3.0, 3.0))
    expected = geodesy.body_from_ecef_via_ned(lat, lon, 40.0, 0.0, 0.0)
    assert max(abs(attitude[i][j] - expected[i][j]) for i in range(3) for j in range(3)) < 1e-6


# -- the UDP sender: off by default, never in a campaign ------------------------------

def test_no_socket_is_opened_unless_a_target_is_given(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a socket was opened without --udp")

    monkeypatch.setattr(socket, "socket", forbidden)
    index = S.write_stream(tmp_path, telemetry=geo_telemetry(n=3), aircraft="c172p", options=FALLBACK)
    assert index["udp"]["sent"] is False
    assert read_records(index["applied_variables"])[0]["parameters"]["udp"]["sent"] is False


def test_a_target_receives_one_datagram_per_pdu_after_the_file_is_written(tmp_path):
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(5.0)
    port = receiver.getsockname()[1]
    try:
        index = S.write_stream(tmp_path, telemetry=geo_telemetry(n=5), aircraft="c172p",
                               options=FALLBACK, udp=("127.0.0.1", port))
        data = (tmp_path / S.STREAM_FILE).read_bytes()
        received = [receiver.recv(4096) for _ in range(5)]
    finally:
        receiver.close()
    assert index["udp"]["sent"] is True and index["udp"]["datagrams"] == 5
    assert index["udp"]["bytes"] == 5 * 144 and index["udp"]["port"] == port
    assert b"".join(received) == data              # the datagrams are the file's PDUs, in order
    assert all(len(d) == 144 for d in received)
    assert S.parse_udp_target("127.0.0.1:3000") == ("127.0.0.1", 3000)
    assert S.parse_udp_target(None) is None
    for bad in ("nohost", "host:", ":3000", "host:port"):
        with pytest.raises(DisError) as exc:
            S.parse_udp_target(bad)
        assert exc.value.constraint == "interop.dis.arguments"
    with pytest.raises(DisError) as exc:
        S.UdpSender("127.0.0.1", 0)
    assert exc.value.constraint == "interop.dis.arguments"


def test_a_campaign_case_refuses_udp_by_name_before_any_socket_exists(tmp_path, monkeypatch):
    campaign = tmp_path / "campaign"
    run_dir = campaign / "runs" / "case_0001"
    run_dir.mkdir(parents=True)
    (campaign / "campaign.json").write_text("{}", encoding="utf-8")
    assert S.in_campaign_worker(run_dir) and not S.in_campaign_worker(tmp_path / "plain")
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("socket")))
    with pytest.raises(DisError) as exc:
        S.write_stream(run_dir, telemetry=geo_telemetry(n=3), aircraft="c172p", options=FALLBACK,
                       udp=("127.0.0.1", 3000))
    assert exc.value.constraint == "dis.udp_in_campaign"
    assert not (run_dir / S.STREAM_FILE).exists()
    # The same case WITHOUT udp writes its file as any run does.
    index = S.write_stream(run_dir, telemetry=geo_telemetry(n=3), aircraft="c172p", options=FALLBACK)
    assert index["udp"]["sent"] is False and (run_dir / S.STREAM_FILE).is_file()


# -- the record ---------------------------------------------------------------------------

def test_the_record_carries_the_ids_the_septuplet_the_marking_and_the_measured_null_test(tmp_path):
    telemetry = geo_telemetry(n=6)
    index = S.write_stream(tmp_path, telemetry=telemetry, aircraft="c172p",
                           options=S.StreamOptions(entity_type_policy="fallback", site=7, entity=42))
    block = index["applied_variables"]
    assert block["record_version"] == RECORD_VERSION
    (record,) = read_records(block)
    assert record["name"] == "dis.entity_state" and record["unit"] == "PDU"
    assert record["value"] == 6 and record["source"] == "derived"
    assert record["model"] == "full-rate Entity State PDU log (IEEE 1278.1-2012 layout, protocol version 7)"
    p = record["parameters"]
    assert p["entity_id"] == {"site": 7, "application": 1, "entity": 42}
    assert p["entity_type"] == {"kind": 1, "domain": 2, "country": 225, "category": 84,
                                "subcategory": 1, "specific": 0, "extra": 0}
    assert p["entity_type_source"] == "fallback" and p["marking"]["text"] == "c172p"
    assert p["timestamp_mode"] == "relative" and p["epoch"] is None
    assert p["pdu_count"] == 6 and p["interval"] == 0.1 and p["emitter"] == "full_rate"
    assert p["dead_reckoning"]["algorithm"] == 4
    assert "central difference" in p["dead_reckoning"]["source"]["linear_acceleration"]
    assert record["frame_keys"] == ["dis.pdu_index", "dis.byte_offset"]
    assert record["telemetry_columns"] == [] and record["properties_written"] == []
    # The null test: with N ~ 0, without N = N0 (52.52 m here), reached
    # against the branch's 0.5 m altitude floor.
    null = record["null_test"]
    assert null["kind"] == "reached" and null["threshold"] == 0.5
    assert null["with"] < 1e-6 and abs(null["without"] - 52.52) < 1e-3
    assert null["ok"] is True
    assert abs(p["location_check"]["radial_without_n_m"] - 52.52) < 1e-3
    assert abs(p["location_check"]["radial_with_n_m"]) < 1e-6
    # Record 2: the readback of the written bytes, the model block, the uncertainty.
    assert record["readback"]["agrees"] and record["readback"]["property"].startswith("dis_entity_state.bin")
    assert record["model_block"]["standard"] == "IEEE 1278.1-2012"
    assert record["uncertainty"]["u_num"] is None
    assert record["uncertainty"]["u_input"] is None          # no u_model_m in this datum
    assert any("septuplet is not asserted" in s for s in record["not_claimed"])
    assert AppliedVariable.from_dict(record).readback.agrees
    assert json.dumps(record).isascii()
    # With the datum block's declared model uncertainty it rides as u_input.
    index = S.write_stream(tmp_path / "u", telemetry=telemetry, aircraft="c172p",
                           datum=dict(MATTERHORN_DATUM, u_model_m=0.10), options=FALLBACK)
    record = read_records(index["applied_variables"])[0]
    assert record["uncertainty"]["u_input"] == {
        "value": 0.10, "unit": "m",
        "rule": "the geoid model's declared spread (D1 u_model_m) carried into the exported "
                "ellipsoidal height",
        "sensitivity": {"location_radial_m": 1.0}}


def test_a_scene_with_no_geoid_measures_a_null_test_of_zero_and_says_so(tmp_path):
    telemetry = geo_telemetry(n=3, n0=0.0)
    index = S.write_stream(tmp_path, telemetry=telemetry, aircraft="c172p", options=FALLBACK)
    null = read_records(index["applied_variables"])[0]["null_test"]
    assert null["with"] == null["without"] == 0.0 and null["ok"] is False
    assert "honestly not reached" in null["note"]


# -- the CLI on a real capture -----------------------------------------------------------

@pytest.fixture(scope="module")
def real_run(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("dis_stream") / "run"
    result = subprocess.run(
        [PYTHON, "-m", "flightsim.capture", str(REPO / "examples/cameras_multi.yaml"),
         "--out", str(out), "--max-previews", "0"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_the_cli_writes_the_log_of_a_real_run_and_refuses_the_empty_standard_table(real_run):
    result = subprocess.run([PYTHON, "-m", "flightsim.dis", str(real_run), "--stream"],
                            cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- dis.entity_type_unknown:")
    assert not (real_run / S.STREAM_FILE).exists()
    result = subprocess.run(
        [PYTHON, "-m", "flightsim.dis", str(real_run), "--stream", "--entity-type", "fallback",
         "--site", "7", "--application", "3", "--entity", "42", "--marking", "N747XX"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    telemetry = json.loads((real_run / "telemetry.json").read_text(encoding="utf-8"))
    n = telemetry["samples"]
    index = S.read_index(real_run)
    assert index["pdu_count"] == n and index["stream_bytes"] == n * 144
    assert index["aircraft"] == "B747" and index["marking"]["text"] == "N747XX"
    assert index["entity_type"]["septuplet"]["category"] == 86
    assert index["datum"]["hae_source"].startswith("hae_m:")
    assert "yaw_rate_dps not recorded" in index["dead_reckoning"]["source"]["r"] or \
        index["dead_reckoning"]["source"]["r"].startswith("recorded yaw_rate_dps")
    assert f"wrote {n} Entity State PDU(s)" in result.stdout
    assert "udp: off" in result.stdout
    cols = telemetry["columns"]
    data = (real_run / S.STREAM_FILE).read_bytes()
    worst = 0.0
    for i in range(n):
        mine = independent_decode(data[i * 144:(i + 1) * 144])
        expected = TO_ECEF.transform(cols["lon_deg"][i], cols["lat_deg"][i], cols["hae_m"][i])
        worst = max(worst, math.dist(mine["location"], expected))
        assert abs(mine["time_past_hour_s"] - cols["t"][i]) < 2e-6
    assert worst < 1e-3
    # Absolute timestamps without an epoch: refused by name, exit 2.
    result = subprocess.run([PYTHON, "-m", "flightsim.dis", str(real_run), "--stream",
                             "--entity-type", "fallback", "--timestamp-mode", "absolute"],
                            cwd=str(REPO), capture_output=True, text=True, timeout=300)
    assert result.returncode == 2 and result.stdout.startswith("REFUSED -- dis.timestamp_epoch_missing:")


# =========================================================================
# The verifier: dis_roundtrip, the checker's OWN struct decode of the stream
# =========================================================================

#: The text returned to the integrator for core/capture/verify.py, verbatim,
#: executed here against the verifier's own Check / PASS / FAIL / NOT_RUN so
#: the clause is tested before the patch lands; once landed, the functions in
#: verify.py are used and pinned to this text.
VERIFY_DIS_PATCH = r'''
# -- D2: the DIS entity-state stream round trip ------------------------------

#: The full-rate Entity State PDU log a capture writes beside its manifest
#: with --dis (core/interop/dis_stream.py) and its index. The checker walks
#: the bytes with its own reading of IEEE 1278.1-2012 7.2.2 and imports
#: nothing from the producer package.
DIS_STREAM_FILE = "dis_entity_state.bin"
DIS_INDEX_FILE = "dis_entity_state.json"
DIS_RECORD_NAME = "dis.entity_state"
DIS_PDU_LENGTH = 144
DIS_TIMESTAMP_UNITS_PER_HOUR = 2 ** 31
#: Location: the wire's float64 ECEF against pyproj's EPSG:4979 -> EPSG:4978
#: of the recorded (lat, lon, hae_m). 0.05 m holds the export to the 3.4 cm
#: the JSBSim ECEF cross-check measured (blueprint section 5) while a PDU
#: moved 1 m, or a stale undulation (|N| >= 17 m at every committed scene),
#: fails. Euler: 1e-4 rad against the checker's own composition (the wire is
#: float32, ~1e-7 rad at pi); a flipped sign misses by 2|angle|. Timestamps:
#: strictly increasing after one hour unwrap.
DIS_LOCATION_TOL_M = 0.05
DIS_EULER_TOL_RAD = 1e-4
FAIL_DIS_ROUNDTRIP = "check.dis_roundtrip"


def _dis_walk(data: bytes):
    """The checker's OWN reading of the Entity State PDU (IEEE 1278.1-2012
    7.2.2 with the version-7 header): (offset, fields) per PDU, walking by
    the header's length field. Raises ValueError on anything that is not
    whole version-7 Entity State PDUs of 144 bytes."""
    import struct

    pdus = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError(f"{len(data) - offset} trailing bytes at {offset} are shorter "
                             f"than a PDU header")
        version, exercise, pdu_type, family = struct.unpack(">BBBB", data[offset:offset + 4])
        timestamp = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        length = struct.unpack(">H", data[offset + 8:offset + 10])[0]
        if version != 7 or pdu_type != 1 or family != 1:
            raise ValueError(f"PDU at {offset} is version {version}, type {pdu_type}, "
                             f"family {family}; not a version-7 Entity State PDU")
        if length != DIS_PDU_LENGTH or offset + length > len(data):
            raise ValueError(f"PDU at {offset} declares {length} bytes; {len(data) - offset} "
                             f"remain and this reader takes {DIS_PDU_LENGTH}")
        chunk = data[offset:offset + length]
        site, application, entity = struct.unpack(">HHH", chunk[12:18])
        force_id, n_params = struct.unpack(">BB", chunk[18:20])
        pdus.append((offset, {
            "exercise_id": exercise, "timestamp": timestamp,
            "site": site, "application": application, "entity": entity,
            "force_id": force_id, "variable_parameters": n_params,
            "entity_type": struct.unpack(">BBHBBBB", chunk[20:28]),
            "velocity": struct.unpack(">fff", chunk[36:48]),
            "location": struct.unpack(">ddd", chunk[48:72]),
            "orientation": struct.unpack(">fff", chunk[72:84]),
            "dr_algorithm": chunk[88], "marking": chunk[129:140],
            "time_past_hour_s": (timestamp >> 1) * 3600.0 / DIS_TIMESTAMP_UNITS_PER_HOUR,
            "absolute": bool(timestamp & 1),
        }))
        offset += length
    return pdus


def _dis_own_euler(lat_deg, lon_deg, heading_deg, pitch_deg, roll_deg):
    """The checker's own DIS orientation (psi, theta, phi, radians): the
    body-from-ECEF matrix composed as body-from-NED (passive yaw about
    down, pitch about the new right axis, roll about the new forward
    axis) times NED-from-ECEF (rows north, east, down at the place), the
    angles read off it as theta = asin(-r02), psi = atan2(r01, r00),
    phi = atan2(r12, r22). Written here from the definition, not taken
    from the producer."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sl, cl, so, co = math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon)
    ned_from_ecef = ((-sl * co, -sl * so, cl), (-so, co, 0.0), (-cl * co, -cl * so, -sl))
    h, p, r = (math.radians(heading_deg), math.radians(pitch_deg), math.radians(roll_deg))
    ch, sh, cp, sp, cr, sr = math.cos(h), math.sin(h), math.cos(p), math.sin(p), math.cos(r), math.sin(r)
    yaw = ((ch, sh, 0.0), (-sh, ch, 0.0), (0.0, 0.0, 1.0))
    pitch = ((cp, 0.0, -sp), (0.0, 1.0, 0.0), (sp, 0.0, cp))
    roll = ((1.0, 0.0, 0.0), (0.0, cr, sr), (0.0, -sr, cr))

    def mul(a, b):
        return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                     for i in range(3))

    m = mul(roll, mul(pitch, mul(yaw, ned_from_ecef)))
    theta = math.asin(max(-1.0, min(1.0, -m[0][2])))
    psi = math.atan2(m[0][1], m[0][0])
    phi = math.atan2(m[1][2], m[2][2])
    return psi, theta, phi


def _dis_hae(columns, datum):
    """The ellipsoidal height per sample the stream should carry: the
    recorded hae_m, else altitude_m plus the manifest datum's numeric
    undulation, else altitude_m (a scene with no geoid)."""
    if "hae_m" in columns:
        return [float(h) for h in columns["hae_m"]], "hae_m"
    n = (datum or {}).get("undulation_m") if isinstance(datum, dict) else None
    n = float(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else 0.0
    return [float(a) + n for a in columns["altitude_m"]], f"altitude_m + {n:+.3f} m"


def verify_dis_roundtrip(manifest: Dict, run_dir=None) -> Check:
    """The Entity State PDU log against the recording it was made from,
    by the checker's own decode: every PDU's location within
    DIS_LOCATION_TOL_M of pyproj's EPSG:4979 -> EPSG:4978 of the
    telemetry's (lat, lon, hae_m) at the PDU's sample, its orientation
    within DIS_EULER_TOL_RAD of the checker's own DIS Euler angles from
    the recorded heading, pitch, roll and place, the timestamps strictly
    increasing (one hour unwrap allowed) with the LSB the index's mode
    says, the ids and marking the index's, the index's offsets the walk's,
    every frame's dis keys pointing at a PDU of the stream. NOT RUN
    without a stream (no file, no index and no dis.entity_state record),
    without telemetry.json, or without pyproj; FAIL (check.dis_roundtrip)
    on a record without its files, a stream that does not walk, a PDU
    moved, an angle wrong, a stale undulation, a non-monotonic clock."""
    run_dir = Path(run_dir) if run_dir is not None else None
    records = ((manifest.get("applied_variables") or {}).get("applied_variables") or [])
    record = next((r for r in records if isinstance(r, dict) and r.get("name") == DIS_RECORD_NAME), None)
    stream_path = run_dir / DIS_STREAM_FILE if run_dir is not None else None
    index_path = run_dir / DIS_INDEX_FILE if run_dir is not None else None
    have_files = (stream_path is not None and stream_path.is_file()
                  and index_path is not None and index_path.is_file())
    if record is None and not have_files:
        return Check("dis_roundtrip", NOT_RUN,
                     "no Entity State PDU log: the run was captured without --dis "
                     "(no dis_entity_state.bin, no index, no dis.entity_state record)")
    if not have_files:
        return Check("dis_roundtrip", FAIL,
                     f"the manifest carries a {DIS_RECORD_NAME} record but {DIS_STREAM_FILE} "
                     f"or {DIS_INDEX_FILE} is absent from the run directory",
                     failure=FAIL_DIS_ROUNDTRIP)
    telemetry_path = run_dir / "telemetry.json"
    if not telemetry_path.is_file():
        return Check("dis_roundtrip", NOT_RUN,
                     "no telemetry.json beside the stream, so there is no recording to "
                     "compare it with")
    try:
        from pyproj import Transformer
    except ImportError:
        return Check("dis_roundtrip", NOT_RUN, "pyproj is not installed here")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        columns = json.loads(telemetry_path.read_text(encoding="utf-8"))["columns"]
        pdus = _dis_walk(stream_path.read_bytes())
    except (ValueError, KeyError, OSError) as exc:
        return Check("dis_roundtrip", FAIL,
                     f"the stream, its index or the telemetry could not be read as what it "
                     f"claims to be: {exc}", failure=FAIL_DIS_ROUNDTRIP)
    offsets = [offset for offset, _ in pdus]
    samples = index.get("sample_indices")
    if (index.get("byte_offsets") != offsets or index.get("pdu_count") != len(pdus)
            or not isinstance(samples, list) or len(samples) != len(pdus)):
        return Check("dis_roundtrip", FAIL,
                     f"the index lists {index.get('pdu_count')} PDUs over "
                     f"{len(samples) if isinstance(samples, list) else '?'} samples; the "
                     f"checker's walk finds {len(pdus)} at offsets {offsets[:3]}...",
                     failure=FAIL_DIS_ROUNDTRIP)
    needed = ("t", "lat_deg", "lon_deg", "heading_deg", "pitch_deg", "roll_deg")
    missing = [c for c in needed if c not in columns]
    if missing or ("hae_m" not in columns and "altitude_m" not in columns):
        return Check("dis_roundtrip", FAIL,
                     f"the telemetry lacks {missing or ['hae_m / altitude_m']}, so the "
                     f"stream cannot be checked against the recording",
                     failure=FAIL_DIS_ROUNDTRIP)
    heights, height_source = _dis_hae(columns, manifest.get("datum"))
    to_ecef = Transformer.from_crs("EPSG:4979", "EPSG:4978", always_xy=True)
    ids = index.get("entity_id") or {}
    mode = index.get("timestamp_mode")
    marking = str((index.get("marking") or {}).get("text", "")).encode("ascii", "replace")
    worst_location = 0.0
    worst_euler = 0.0
    previous = None
    for k, (offset, pdu) in enumerate(pdus):
        s = samples[k]
        if not isinstance(s, int) or not 0 <= s < len(columns["t"]):
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} names sample {s!r}, outside the recording's "
                         f"{len(columns['t'])} samples", failure=FAIL_DIS_ROUNDTRIP)
        lat, lon = float(columns["lat_deg"][s]), float(columns["lon_deg"][s])
        expected = to_ecef.transform(lon, lat, heights[s])
        distance = math.dist(pdu["location"], expected)
        worst_location = max(worst_location, distance)
        if distance > DIS_LOCATION_TOL_M:
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} (sample {s}) sits {distance:.3f} m from pyproj's ECEF of "
                         f"the recorded place at {height_source} (tolerance "
                         f"{DIS_LOCATION_TOL_M} m): a moved PDU or a stale undulation",
                         failure=FAIL_DIS_ROUNDTRIP)
        own = _dis_own_euler(lat, lon, float(columns["heading_deg"][s]),
                             float(columns["pitch_deg"][s]), float(columns["roll_deg"][s]))
        for name, mine, theirs in zip(("psi", "theta", "phi"), own, pdu["orientation"]):
            error = abs((float(theirs) - mine + math.pi) % (2.0 * math.pi) - math.pi)
            worst_euler = max(worst_euler, error)
            if error > DIS_EULER_TOL_RAD:
                return Check("dis_roundtrip", FAIL,
                             f"PDU {k} (sample {s}) {name} = {float(theirs):+.6f} rad; the "
                             f"checker's own composition gives {mine:+.6f} rad (tolerance "
                             f"{DIS_EULER_TOL_RAD} rad)", failure=FAIL_DIS_ROUNDTRIP)
        if (pdu["site"], pdu["application"], pdu["entity"]) != (
                ids.get("site"), ids.get("application"), ids.get("entity")):
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} carries entity id {pdu['site']}:{pdu['application']}:"
                         f"{pdu['entity']}; the index says {ids}", failure=FAIL_DIS_ROUNDTRIP)
        if pdu["marking"].rstrip(b"\0") != marking:
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k} is marked {pdu['marking']!r}; the index says {marking!r}",
                         failure=FAIL_DIS_ROUNDTRIP)
        if pdu["absolute"] != (mode == "absolute"):
            return Check("dis_roundtrip", FAIL,
                         f"PDU {k}'s timestamp LSB says {'absolute' if pdu['absolute'] else 'relative'}; "
                         f"the index says {mode!r}", failure=FAIL_DIS_ROUNDTRIP)
        seconds = pdu["time_past_hour_s"]
        if previous is not None:
            if seconds < previous - 1800.0:
                seconds += 3600.0                      # one wrap at the hour
            if seconds <= previous:
                return Check("dis_roundtrip", FAIL,
                             f"PDU {k}'s timestamp ({seconds:.6f} s past the hour) is not "
                             f"after PDU {k - 1}'s ({previous:.6f} s)", failure=FAIL_DIS_ROUNDTRIP)
        previous = seconds
    for f, frame in enumerate(manifest.get("frames") or []):
        keys = frame.get("dis") if isinstance(frame, dict) else None
        if not isinstance(keys, dict) or keys.get("pdu_index") is None:
            continue
        k = keys.get("pdu_index")
        if not isinstance(k, int) or not 0 <= k < len(pdus) or keys.get("byte_offset") != offsets[k]:
            return Check("dis_roundtrip", FAIL,
                         f"frame {f} names PDU {k!r} at byte {keys.get('byte_offset')!r}, which "
                         f"the stream does not hold at that offset", failure=FAIL_DIS_ROUNDTRIP)
    return Check("dis_roundtrip", PASS,
                 f"{len(pdus)} Entity State PDUs walked by the checker's own layout: location "
                 f"within {worst_location:.2e} m of pyproj at {height_source} (tolerance "
                 f"{DIS_LOCATION_TOL_M} m), orientation within {worst_euler:.2e} rad of the "
                 f"checker's own Euler composition (tolerance {DIS_EULER_TOL_RAD} rad), "
                 f"timestamps {mode} and strictly increasing, ids and marking as indexed")
'''


def _patch_namespace():
    from core.capture import verify

    namespace = {"Check": verify.Check, "PASS": verify.PASS, "FAIL": verify.FAIL,
                 "NOT_RUN": verify.NOT_RUN, "Path": Path, "math": math, "json": json,
                 "Dict": dict, "__file__": str(verify.__file__)}
    exec(compile(VERIFY_DIS_PATCH, "<verify_dis patch>", "exec"), namespace)
    return namespace


def _verifier():
    """verify.py's own ``verify_dis_roundtrip`` once the patch is applied,
    else the patch text executed against verify.py's Check."""
    from core.capture import verify

    if hasattr(verify, "verify_dis_roundtrip"):
        return verify.verify_dis_roundtrip
    return _patch_namespace()["verify_dis_roundtrip"]


def _run_with_stream(tmp_path: Path, telemetry=None, options=FALLBACK, n0=52.52):
    """A run directory: telemetry.json, the stream and its index, and a
    manifest carrying the record and frame keys as the capture writes them."""
    telemetry = telemetry or geo_telemetry(n=8, n0=n0)
    write_run(tmp_path, telemetry, datum=MATTERHORN_DATUM)
    index = S.write_stream(tmp_path, telemetry=telemetry, aircraft="c172p", options=options)
    manifest = {"datum": MATTERHORN_DATUM, "applied_variables": index["applied_variables"],
                "frames": [{"sample_index": i, "t_s": telemetry["columns"]["t"][i]} for i in (0, 3, 7)]}
    S.attach_frame_keys(manifest, index)
    return manifest, index


def test_the_verifier_imports_nothing_from_the_producer_and_is_pinned():
    from core.capture import verify

    for source in (VERIFY_DIS_PATCH, (REPO / "core/capture/verify.py").read_text(encoding="utf-8")):
        assert "import core.interop" not in source and "from core.interop" not in source
        assert "from ..interop" not in source and "import dis" not in source
        assert "geodesy" not in source
    assert VERIFY_DIS_PATCH.isascii()
    text = (REPO / "core/capture/verify.py").read_text(encoding="utf-8")
    if hasattr(verify, "verify_dis_roundtrip"):
        for name in ("_dis_walk", "_dis_own_euler", "_dis_hae", "verify_dis_roundtrip"):
            assert inspect.getsource(getattr(verify, name)) in VERIFY_DIS_PATCH, name
        assert verify.DIS_LOCATION_TOL_M == 0.05 and verify.DIS_EULER_TOL_RAD == 1e-4
        assert verify.FAIL_DIS_ROUNDTRIP == "check.dis_roundtrip"
        assert 'run("dis_roundtrip", verify_dis_roundtrip, manifest, run_dir)' in text


def test_the_verifier_passes_a_stream_it_decodes_itself(tmp_path):
    verify_dis_roundtrip = _verifier()
    manifest, index = _run_with_stream(tmp_path)
    check = verify_dis_roundtrip(manifest, tmp_path)
    assert check.status == "PASS", check.detail
    assert "8 Entity State PDUs" in check.detail and "strictly increasing" in check.detail
    # The thresholded emitter and absolute timestamps pass the same clause.
    manifest, index = _run_with_stream(
        tmp_path / "t", telemetry=manoeuvre_telemetry(),
        options=S.StreamOptions(entity_type_policy="fallback", emitter="thresholded",
                                timestamp_mode="absolute", epoch="2026-09-29T10:59:55Z"))
    check = verify_dis_roundtrip(manifest, tmp_path / "t")
    assert check.status == "PASS", check.detail
    assert index["pdu_count"] < 120 and "absolute" in check.detail


def test_the_verifier_is_not_run_without_a_stream_and_fails_a_record_without_its_files(tmp_path):
    verify_dis_roundtrip = _verifier()
    check = verify_dis_roundtrip({"frames": []}, tmp_path)
    assert check.status == "NOT RUN" and "without --dis" in check.detail
    manifest, _ = _run_with_stream(tmp_path)
    (tmp_path / S.STREAM_FILE).unlink()
    check = verify_dis_roundtrip(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "check.dis_roundtrip"
    assert "absent" in check.detail


def _corrupt(path: Path, pdu: int, offset: int, fmt: str, transform) -> None:
    data = bytearray(path.read_bytes())
    at = pdu * 144 + offset
    (value,) = struct.unpack(fmt, data[at:at + struct.calcsize(fmt)])
    data[at:at + struct.calcsize(fmt)] = struct.pack(fmt, transform(value))
    path.write_bytes(bytes(data))


def test_a_pdu_moved_one_metre_fails_by_name(tmp_path):
    verify_dis_roundtrip = _verifier()
    manifest, _ = _run_with_stream(tmp_path)
    _corrupt(tmp_path / S.STREAM_FILE, 5, 48, ">d", lambda x: x + 1.0)     # location x + 1 m
    check = verify_dis_roundtrip(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "check.dis_roundtrip"
    assert "PDU 5" in check.detail and "1.000 m" in check.detail
    # A move within the tolerance stays a PASS: the clause is 0.05 m, not 0.
    manifest, _ = _run_with_stream(tmp_path / "small")
    _corrupt(tmp_path / "small" / S.STREAM_FILE, 5, 48, ">d", lambda x: x + 0.02)
    assert verify_dis_roundtrip(manifest, tmp_path / "small").status == "PASS"


def test_a_flipped_euler_sign_fails_by_name(tmp_path):
    verify_dis_roundtrip = _verifier()
    manifest, _ = _run_with_stream(tmp_path)
    _corrupt(tmp_path / S.STREAM_FILE, 2, 80, ">f", lambda x: -x)          # phi negated
    check = verify_dis_roundtrip(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "check.dis_roundtrip"
    assert "PDU 2" in check.detail and "phi" in check.detail
    manifest, _ = _run_with_stream(tmp_path / "psi")
    _corrupt(tmp_path / "psi" / S.STREAM_FILE, 0, 72, ">f", lambda x: -x)  # psi negated
    check = verify_dis_roundtrip(manifest, tmp_path / "psi")
    assert check.status == "FAIL" and "psi" in check.detail


def test_a_stale_undulation_fails_by_name(tmp_path):
    """The stream written from a recording whose hae_m carried no N while
    the run's telemetry says +52.52 m: every PDU is 52.52 m low."""
    verify_dis_roundtrip = _verifier()
    telemetry = geo_telemetry(n=8, n0=52.52)
    stale = json.loads(json.dumps(telemetry))
    stale["columns"]["hae_m"] = list(stale["columns"]["altitude_m"])
    stale["columns"]["undulation_m"] = [0.0] * 8
    write_run(tmp_path, telemetry, datum=MATTERHORN_DATUM)
    index = S.write_stream(tmp_path, telemetry=stale, aircraft="c172p", options=FALLBACK)
    manifest = {"datum": MATTERHORN_DATUM, "applied_variables": index["applied_variables"], "frames": []}
    check = verify_dis_roundtrip(manifest, tmp_path)
    assert check.status == "FAIL" and check.failure == "check.dis_roundtrip"
    assert "52.5" in check.detail and "stale undulation" in check.detail


def test_a_non_monotonic_clock_a_wrong_id_and_a_bad_frame_key_fail_by_name(tmp_path):
    verify_dis_roundtrip = _verifier()
    manifest, _ = _run_with_stream(tmp_path)
    _corrupt(tmp_path / S.STREAM_FILE, 4, 4, ">I", lambda x: x - (100000 << 1))   # 0.17 s earlier
    check = verify_dis_roundtrip(manifest, tmp_path)
    assert check.status == "FAIL" and "not after" in check.detail
    manifest, _ = _run_with_stream(tmp_path / "id")
    _corrupt(tmp_path / "id" / S.STREAM_FILE, 1, 12, ">H", lambda x: x + 1)
    check = verify_dis_roundtrip(manifest, tmp_path / "id")
    assert check.status == "FAIL" and "entity id" in check.detail
    manifest, _ = _run_with_stream(tmp_path / "frame")
    manifest["frames"][0]["dis"] = {"pdu_index": 99, "byte_offset": 0}
    check = verify_dis_roundtrip(manifest, tmp_path / "frame")
    assert check.status == "FAIL" and "frame 0" in check.detail
    # A stream that does not walk: the header's length altered.
    manifest, _ = _run_with_stream(tmp_path / "walk")
    _corrupt(tmp_path / "walk" / S.STREAM_FILE, 3, 8, ">H", lambda x: 100)
    check = verify_dis_roundtrip(manifest, tmp_path / "walk")
    assert check.status == "FAIL" and check.failure == "check.dis_roundtrip"


def test_the_verifier_on_the_real_run(real_run):
    """The stream the CLI test wrote for the real capture, with the run's
    own capture manifest: PASS, decoded by the checker alone."""
    verify_dis_roundtrip = _verifier()
    manifest = json.loads((real_run / "capture_manifest.json").read_text(encoding="utf-8"))
    index = S.read_index(real_run)
    manifest["applied_variables"] = index["applied_variables"]
    S.attach_frame_keys(manifest, index)
    check = verify_dis_roundtrip(manifest, real_run)
    assert check.status == "PASS", check.detail
    assert all(f["dis"]["byte_offset"] == f["sample_index"] * 144 for f in manifest["frames"])
