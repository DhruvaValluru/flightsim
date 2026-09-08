"""The manifest must label the flight the frames actually show.

Poses are solved over a headless pre-run; the render host then flies the
scenario itself. The camera poses are consumed verbatim so those are
exact, but the AIRCRAFT states in the manifest come from the pre-run. If
the two flights diverge, every aircraft label is wrong by that much, and
nothing in the manifest can tell you -- it is internally consistent
either way.

So the check's reference is the host's OWN recorded telemetry, sitting
beside the manifest as telemetry.json. These tests build a manifest,
write a host telemetry file that agrees or disagrees with it by a known
amount, and pin that the check says so.
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


def write_host_telemetry(run_dir, columns, north_shift_m=0.0):
    """A host telemetry.json, optionally flying a track shifted north of
    the one the manifest was solved over."""
    # Degrees of latitude per metre, near enough at this scale for a
    # test that measures tens of metres.
    shift_deg = north_shift_m / 111_320.0
    payload = {"columns": {
        "t": [float(v) for v in columns["t"]],
        "lat_deg": [float(v) + shift_deg for v in columns["lat_deg"]],
        "lon_deg": [float(v) for v in columns["lon_deg"]],
        "altitude_m": [float(v) for v in columns["altitude_m"]],
    }}
    (run_dir / "telemetry.json").write_text(json.dumps(payload),
                                            encoding="utf-8")


def test_not_run_without_host_telemetry(captured):
    """An unrendered capture has only one flight, so there is nothing to
    disagree. That is NOT RUN, not a pass."""
    manifest, _, run_dir = captured
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == NOT_RUN
    assert "only one flight" in check.detail


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
    (run_dir / "telemetry.json").write_text(
        json.dumps({"columns": {"t": [0.0, 0.1]}}), encoding="utf-8")
    check = verify_flight_agreement(manifest, run_dir)
    assert check.status == NOT_RUN
