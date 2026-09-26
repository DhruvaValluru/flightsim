"""The manifest must label the flight the frames actually show.

Poses are solved over a headless pre-run; the render host then flies the
scenario itself. The camera poses are consumed verbatim so those are
exact, but the AIRCRAFT states in the manifest come from the pre-run. If
the two flights diverge, every aircraft label is wrong by that much, and
nothing in the manifest can tell you -- it is internally consistent
either way.

So the check's reference is the host's OWN recorded telemetry, which
the render pass writes into the camera's own directory as
``frames/<camera_id>/host_telemetry.json``. These tests build a
manifest, write a host telemetry file that agrees or disagrees with it
by a known amount, and pin that the check says so.

That path is load-bearing and this fixture used to get it wrong. It
wrote the stand-in host flight to ``<run>/telemetry.json`` -- which on
a real run is the headless PRE-RUN, the very telemetry the manifest's
aircraft track was solved from. The check read it, compared the pre-run
against itself, and reported 0.00 m on every run that has ever been
made. The tests were green throughout, because the fixture and the
check agreed on the wrong file. A stand-in has to write what the
producer writes, where the producer writes it.
"""

import json

import pytest

from core.capture.manifest import build_capture_manifest
from core.capture.poses import solve_pose_track
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, NOT_RUN, PASS, verify_flight_agreement,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec

from tests.test_camera_poses import FRAME, make_columns


@pytest.fixture
def captured(tmp_path):
    """A manifest, plus the telemetry it was solved over."""
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase",
                                  aircraft="B747")
    camera.set("capture_count", 8, frm="test")
    spec.cameras = [camera]
    columns = make_columns(duration_s=14.0)
    manifest = build_capture_manifest(
        spec, columns, FRAME,
        [solve_pose_track(columns, camera, FRAME)],
        [solve_schedule(columns, camera, FRAME)],
        output_digest="digest", cameras=spec.cameras)
    return manifest, columns, tmp_path


def write_host_telemetry(run_dir, columns, north_shift_m=0.0,
                         camera_id="chase0"):
    """A host_telemetry.json where the render pass puts it, optionally
    flying a track shifted north of the one the manifest was solved
    over."""
    # Degrees of latitude per metre, near enough at this scale for a
    # test that measures tens of metres.
    shift_deg = north_shift_m / 111_320.0
    payload = {"columns": {
        "t": [float(v) for v in columns["t"]],
        "lat_deg": [float(v) + shift_deg for v in columns["lat_deg"]],
        "lon_deg": [float(v) for v in columns["lon_deg"]],
        "altitude_m": [float(v) for v in columns["altitude_m"]],
    }}
    directory = run_dir / "frames" / camera_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "host_telemetry.json").write_text(json.dumps(payload),
                                                   encoding="utf-8")


def test_not_run_without_host_telemetry(captured):
    """An unrendered capture has only one flight, so there is nothing to
    disagree. That is NOT RUN, not a pass."""
    manifest, _, run_dir = captured
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == NOT_RUN
    assert "recorded no flight of its own" in check.detail


def test_the_same_flight_agrees(captured):
    manifest, columns, run_dir = captured
    write_host_telemetry(run_dir, columns)
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == PASS, check.detail


def test_a_diverging_host_flight_is_caught(captured):
    """The defect this exists for: the manifest's aircraft track and the
    flight that produced the pixels are different flights, and every
    aircraft label is wrong by the difference."""
    manifest, columns, run_dir = captured
    write_host_telemetry(run_dir, columns, north_shift_m=120.0)
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == FAIL
    assert "different flight" in check.detail


def test_a_small_divergence_is_within_tolerance(captured):
    """Two hosts stepping the same JSBSim will not agree bit-for-bit.
    The check has to bound the error, not demand identity."""
    manifest, columns, run_dir = captured
    write_host_telemetry(run_dir, columns, north_shift_m=2.0)
    assert verify_flight_agreement(manifest, run_dir).status == PASS


def test_host_telemetry_without_the_needed_columns_is_not_run(captured):
    """A telemetry file that cannot answer the question must say so
    rather than pass by default."""
    manifest, _, run_dir = captured
    directory = run_dir / "frames" / "chase0"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "host_telemetry.json").write_text(
        json.dumps({"columns": {"t": [0.0, 0.1]}}), encoding="utf-8")
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == NOT_RUN


def test_the_pre_run_telemetry_is_not_mistaken_for_the_host_flight(captured):
    """The defect this check was written to close, and then had itself.

    ``<run>/telemetry.json`` is the headless pre-run: the flight the
    manifest's aircraft track was SOLVED FROM. Grading the manifest
    against it compares the pre-run with itself and cannot fail -- it
    reported 0.00 m on every run ever made, which reads exactly like a
    passing check and is the same signature the vacuous triangulation
    had. The two files even carry the same four column names, so
    nothing complained.

    With only the pre-run present there is no host flight, and the
    honest answer is NOT RUN.
    """
    manifest, columns, run_dir = captured
    payload = {"columns": {
        "t": [float(v) for v in columns["t"]],
        "lat_deg": [float(v) for v in columns["lat_deg"]],
        "lon_deg": [float(v) for v in columns["lon_deg"]],
        "altitude_m": [float(v) for v in columns["altitude_m"]],
    }}
    (run_dir / "telemetry.json").write_text(json.dumps(payload),
                                            encoding="utf-8")
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == NOT_RUN, check.detail
    assert "recorded no flight of its own" in check.detail


def test_a_frame_outside_the_host_flight_is_not_quietly_dropped(captured):
    """A host that stopped flying before the run ended leaves frames
    nothing grades. Skipping them silently would shrink the check to
    whatever the host happened to cover."""
    manifest, columns, run_dir = captured
    half = len(columns["t"]) // 3
    write_host_telemetry(run_dir, {k: v[:half] for k, v in columns.items()})
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == FAIL, check.detail
    assert "outside the host's recorded flight" in check.detail


# -- host determinism ----------------------------------------------------

def write_host_flight(run_dir, columns, camera_id, last_bit_shift=0.0):
    """One camera's recorded host flight."""
    payload = {"columns": {
        "t": [float(v) for v in columns["t"]],
        "lat_deg": [float(v) + last_bit_shift for v in columns["lat_deg"]],
        "lon_deg": [float(v) for v in columns["lon_deg"]],
        "altitude_m": [float(v) for v in columns["altitude_m"]],
    }}
    directory = run_dir / "frames" / camera_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "host_telemetry.json").write_text(json.dumps(payload),
                                                   encoding="utf-8")


def test_determinism_is_not_run_with_one_flight(captured):
    """One pass measures nothing about repeatability."""
    from core.capture.verify import verify_host_determinism

    _, columns, run_dir = captured
    write_host_flight(run_dir, columns, "chase0")
    check = verify_host_determinism(run_dir)
    assert check.status == NOT_RUN
    assert "two flights" in check.detail


def test_identical_passes_prove_the_host_is_reproducible(captured):
    from core.capture.verify import verify_host_determinism

    _, columns, run_dir = captured
    write_host_flight(run_dir, columns, "chase0")
    write_host_flight(run_dir, columns, "tower0")
    check = verify_host_determinism(run_dir)
    assert check.status == PASS, check.detail
    assert "byte-identical" in check.detail


def test_a_host_that_flies_differently_each_pass_is_caught(captured):
    """The property that licenses re-flying instead of replaying. If it
    stops holding, the aircraft labels drift between cameras and only
    this check would notice.

    The divergence here is one part in 1e9 of a degree -- far below any
    tolerance flight_agreement would ever apply -- because the claim
    being checked is bit-determinism, not closeness.
    """
    from core.capture.verify import verify_host_determinism

    _, columns, run_dir = captured
    write_host_flight(run_dir, columns, "chase0")
    write_host_flight(run_dir, columns, "tower0", last_bit_shift=1e-9)
    check = verify_host_determinism(run_dir)
    assert check.status == FAIL, check.detail
    assert "not reproducible" in check.detail
