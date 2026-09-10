"""Solving the poses over the host's OWN flight, not a second one.

The capture pipeline used to fly the scenario twice: headlessly through
the ``jsbsim`` Python package, where every pose was solved, and again in
the Unreal host, where the pixels were taken. Two builds stepping one
scenario diverge -- 1.38 m worst, measured on the demo -- so the
``aircraft`` block in every frame record described a flight the frames
did not show. The camera was exactly where the label said; the thing in
front of it was up to a metre and a half away from where the label said.

The fix is to let the host fly the card FIRST (the telemetry-only
commandlet) and solve everything over that recording, then render. These
tests cover the half that can run without an engine: reading the host's
telemetry back, refusing it by name when it cannot be solved over,
digesting it the way the runner digests its own, and -- the one that
matters most -- the verifier's tolerance following the manifest's
declaration of WHICH flight it was solved over.
"""

import json

import pytest

from core.capture.hostflight import (
    HOST_FLIGHT_DIR, HostFlightError, REQUIRED_CHANNELS, digest_columns,
    host_telemetry_path, read_all_host_columns, read_host_columns,
)
from core.capture.manifest import (
    MANIFEST_VERSION, SOLVE_HOST_FLIGHT, SOLVE_PRE_RUN,
    build_capture_manifest,
)
from core.capture.poses import solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, HOST_FLIGHT_AGREEMENT_TOL_M, PASS, PRE_RUN_AGREEMENT_TOL_M,
    verify_flight_agreement,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_flight_agreement import write_host_telemetry
from tests.test_camera_poses import FRAME, make_columns


def host_payload(columns, **overrides):
    """What the UE recorder writes: every solver channel, nested under
    "columns" exactly as FlightSimTelemetryRecorder does."""
    payload = {name: [float(v) for v in columns[name]]
               for name in REQUIRED_CHANNELS}
    payload.update(overrides)
    return {"columns": payload}


@pytest.fixture
def flight():
    return make_columns(duration_s=14.0)


# -- reading the host's flight back -------------------------------------

def test_a_missing_host_flight_refuses_by_name(tmp_path):
    """Poses cannot be solved over a flight that does not exist, and the
    caller needs to know that is what happened rather than meeting a
    stack trace."""
    with pytest.raises(HostFlightError) as caught:
        read_host_columns(tmp_path / "nope.json")
    assert caught.value.constraint == "capture.host_flight"
    assert "recorded no telemetry" in caught.value.message


def test_the_recorder_s_own_shape_is_read(tmp_path, flight):
    """The UE recorder nests its columns under "columns"; a bare mapping
    is taken as the columns themselves. Both are accepted because both
    exist in this tree."""
    nested = tmp_path / "nested.json"
    nested.write_text(json.dumps(host_payload(flight)), encoding="utf-8")
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(host_payload(flight)["columns"]),
                    encoding="utf-8")
    assert read_host_columns(nested) == read_host_columns(bare)
    assert set(read_host_columns(nested)) == set(REQUIRED_CHANNELS)


@pytest.mark.parametrize("dropped", REQUIRED_CHANNELS)
def test_a_channel_the_solver_needs_is_refused_by_name(tmp_path, flight,
                                                       dropped):
    """Every one of these is a channel ``solve_pose_track`` indexes
    directly. Refusing here names the missing channel; not refusing
    means a KeyError from inside the solver on a Windows box halfway
    through a run."""
    payload = host_payload(flight)
    del payload["columns"][dropped]
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HostFlightError) as caught:
        read_host_columns(path)
    assert dropped in caught.value.message


def test_ragged_columns_are_refused(tmp_path, flight):
    """A short column would silently pair a state with the wrong
    instant."""
    payload = host_payload(flight)
    payload["columns"]["roll_deg"] = payload["columns"]["roll_deg"][:-3]
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HostFlightError, match="roll_deg"):
        read_host_columns(path)


def test_a_single_instant_is_not_a_flight(tmp_path, flight):
    payload = host_payload(flight)
    payload["columns"] = {k: v[:1] for k, v in payload["columns"].items()}
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HostFlightError, match="sample"):
        read_host_columns(path)


def test_the_host_flight_lives_where_the_verifier_looks(tmp_path):
    """``verify_host_determinism`` finds host flights by globbing for
    that filename, and ``flight_agreement`` keys them by the parent
    directory. Pin both halves of the path."""
    path = host_telemetry_path(tmp_path)
    assert path.parent.name == HOST_FLIGHT_DIR
    assert path.name == "host_telemetry.json"


# -- the digest ---------------------------------------------------------

def test_the_digest_matches_the_runner_s_own(flight):
    """The independent reference: ``run_spec`` digests its telemetry
    with ``core.scenario.runner._digest_telemetry``, and a manifest's
    ``output_digest`` has to mean the same thing whichever flight it
    describes. Two implementations, one answer, or the field is not
    comparable across runs.
    """
    from core.scenario.runner import _digest_telemetry

    class Stub:
        columns = {name: [float(v) for v in flight[name]]
                   for name in REQUIRED_CHANNELS}

    assert digest_columns(Stub.columns) == _digest_telemetry(Stub)


def test_the_digest_is_exact_not_rounded(flight):
    """A tolerance here would defeat the determinism claim it feeds."""
    columns = {name: [float(v) for v in flight[name]]
               for name in REQUIRED_CHANNELS}
    nudged = {k: list(v) for k, v in columns.items()}
    nudged["altitude_m"][3] = nudged["altitude_m"][3] * (1.0 + 1e-15)
    assert digest_columns(columns) != digest_columns(nudged)


def test_the_digest_covers_every_recorded_column(tmp_path, flight):
    """A manifest's ``output_digest`` is documented as covering "the
    recorded telemetry columns", and the headless pre-run's covers all
    of them. Digesting only the seven the SOLVER needs would give one
    field two meanings depending on solve_source.

    It did, and it showed: on the first host-solved run the capture
    printed fc328800... while verify_host_determinism, reading the same
    bytes, digested 1c8acba2... Same file, two numbers.
    """
    payload = host_payload(flight)
    # A column the solver never touches, of the kind the host records
    # thirty of.
    payload["columns"]["lift_n"] = [1.5 * i for i in range(len(flight["t"]))]
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    solver_only = read_host_columns(path)
    everything = read_all_host_columns(path)
    assert set(solver_only) == set(REQUIRED_CHANNELS)
    assert "lift_n" in everything
    assert digest_columns(everything) != digest_columns(solver_only), (
        "digesting the solver's subset is what made one field mean two "
        "things; the two must be distinguishable")


def test_the_full_digest_agrees_with_the_verifier_s(tmp_path, flight):
    """The independent reference for the fix: verify_host_determinism
    digests these files its own way, and the capture's digest of the
    same bytes has to be the same number or the inconsistency has only
    moved."""
    import hashlib

    payload = host_payload(flight)
    payload["columns"]["lift_n"] = [0.25 * i for i in range(len(flight["t"]))]
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    # verify_host_determinism's algorithm, written out here rather than
    # imported, so this compares two constructions and not one.
    columns = json.loads(path.read_text(encoding="utf-8"))["columns"]
    digest = hashlib.sha256()
    for key in sorted(columns):
        digest.update(key.encode("utf-8"))
        for value in columns[key]:
            digest.update(repr(float(value)).encode("utf-8"))

    assert digest_columns(read_all_host_columns(path)) == digest.hexdigest()


def test_a_host_file_with_no_numeric_columns_refuses(tmp_path):
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps({"columns": {"note": ["a", "b"]}}),
                    encoding="utf-8")
    with pytest.raises(HostFlightError, match="numeric"):
        read_all_host_columns(path)


# -- the manifest says which flight it describes ------------------------

def captured_manifest(columns, solve_source):
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase",
                                  aircraft="B747")
    camera.set("capture_count", 8, frm="test")
    spec.cameras = [camera]
    return build_capture_manifest(
        spec, columns, FRAME,
        [solve_pose_track(columns, camera, FRAME)],
        [solve_schedule(columns, camera, FRAME)],
        output_digest="digest", cameras=spec.cameras,
        solve_source=solve_source)


def test_the_manifest_declares_which_flight_it_labels(flight):
    manifest = captured_manifest(flight, SOLVE_HOST_FLIGHT)
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["solve_source"] == SOLVE_HOST_FLIGHT


def test_an_undeclarable_solve_source_is_refused(flight):
    """Version 2 could not say which flight its labels came from, and a
    consumer had to assume. A free-text field would be the same problem
    with extra steps."""
    with pytest.raises(ValueError, match="solve_source"):
        captured_manifest(flight, "whatever the caller felt like")


# -- the tolerance follows the declaration ------------------------------

#: What solving over the headless pre-run actually costs, measured on
#: examples/cameras_multi.yaml against the host's own recording.
MEASURED_PRE_RUN_DIVERGENCE_M = 1.38


def test_the_pre_run_gap_passes_as_a_pre_run_solve(flight, tmp_path):
    """1.38 m is what two JSBSim builds do, and a manifest that says it
    was solved over the pre-run is not lying about anything -- it is
    bounded, reported, and within tolerance."""
    manifest = captured_manifest(flight, SOLVE_PRE_RUN)
    write_host_telemetry(tmp_path, flight,
                         north_shift_m=MEASURED_PRE_RUN_DIVERGENCE_M)
    check = verify_flight_agreement(manifest, tmp_path)
    assert check.status == PASS, check.detail
    assert f"tol {PRE_RUN_AGREEMENT_TOL_M:g}" in check.detail
    assert SOLVE_PRE_RUN in check.detail


def test_the_same_gap_fails_a_manifest_claiming_a_host_solve(flight,
                                                             tmp_path):
    """THE REGRESSION GUARD.

    A manifest that says it was solved over the host's own flight is
    claiming the labels and the pixels are one flight. 1.38 m is exactly
    the signature of having solved over the pre-run instead -- the
    pipeline falling back, the host pass silently not running, someone
    passing --no-host-flight and the manifest not noticing. At the
    pre-run's 25 m tolerance that fallback is invisible. It must not be.
    """
    manifest = captured_manifest(flight, SOLVE_HOST_FLIGHT)
    write_host_telemetry(tmp_path, flight,
                         north_shift_m=MEASURED_PRE_RUN_DIVERGENCE_M)
    check = verify_flight_agreement(manifest, tmp_path)
    assert check.status == FAIL
    assert "check the host flight actually ran" in check.detail


def test_one_flight_passes_the_tight_bound(flight, tmp_path):
    """The whole point: solved over the host's flight, graded against
    that same flight, the gap is interpolation noise rather than
    divergence."""
    manifest = captured_manifest(flight, SOLVE_HOST_FLIGHT)
    write_host_telemetry(tmp_path, flight, north_shift_m=0.0)
    check = verify_flight_agreement(manifest, tmp_path)
    assert check.status == PASS, check.detail
    assert f"tol {HOST_FLIGHT_AGREEMENT_TOL_M:g}" in check.detail


def test_the_tight_bound_still_allows_interpolation_noise(flight, tmp_path):
    """Sensitive without being brittle. The host samples every 0.1 s and
    this check interpolates to the frame's own instant; the residual is
    the track's curvature over half a sample, far under a decimetre. A
    bound that fired on that would be measuring its own arithmetic."""
    manifest = captured_manifest(flight, SOLVE_HOST_FLIGHT)
    write_host_telemetry(tmp_path, flight, north_shift_m=0.05)
    assert verify_flight_agreement(manifest, tmp_path).status == PASS


# -- the whole record, not the solver's seven ----------------------------

def test_the_host_record_is_validated_and_whole(tmp_path, flight):
    """read_host_columns is what the solver needs; read_host_record is
    that, validated the same way, plus every other channel the host
    logged at the same sample count -- the wind vector, the forces,
    the control positions that every frame's ``state`` is cut from."""
    from core.capture.hostflight import read_host_record

    columns = dict(flight)
    n = len(columns["t"])
    columns["wind_north_mps"] = [0.5 * i for i in range(n)]
    columns["lift_n"] = [1000.0 + i for i in range(n)]
    columns["ragged"] = [1.0, 2.0]             # not the flight's
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps({"columns": columns}), encoding="utf-8")

    record = read_host_record(path)
    assert set(REQUIRED_CHANNELS) <= set(record)
    assert record["wind_north_mps"] == columns["wind_north_mps"]
    assert record["lift_n"] == columns["lift_n"]
    assert "ragged" not in record, (
        "a column of the wrong length is not the flight's, and is left "
        "out rather than misaligned")


def test_the_host_record_refuses_what_the_solver_would(tmp_path, flight):
    from core.capture.hostflight import read_host_record

    columns = dict(flight)
    del columns["heading_deg"]
    path = tmp_path / "host_telemetry.json"
    path.write_text(json.dumps({"columns": columns}), encoding="utf-8")
    with pytest.raises(HostFlightError, match="heading_deg"):
        read_host_record(path)
