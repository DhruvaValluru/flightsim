"""The FDM-rate checks (core/telemetry/instruments_check.py check_allan,
check_lever_arm; R2) and the verifier clauses
(core/capture/verify.py's verify_applied_readback, verify_null_effect,
verify_instrument_allan, verify_instrument_lever_arm,
verify_uncertainty_present, each run by verify_run): the
overlapping Allan deviation written from the definition, the lever-arm
recovery from a rolling truth track, and the five record checks --
applied_readback, null_effect, instrument_allan, instrument_lever_arm,
uncertainty_present -- each PASS / FAIL by name / NOT RUN, with a
corruption test that fails by name.

Every statistic here is measured on a synthetic stream or on the real
c172p flight (the 30 s waypoint example with every instrument tactical);
the checks import nothing from the producer (asserted over both source
files).
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from core.scenario.spec import ScenarioSpec
from core.telemetry import instruments as I
from core.telemetry.instruments_check import (
    ALLAN_BK_RUN_MULTIPLE, ALLAN_TOL, FAIL, FAIL_ALLAN, FAIL_LEVER_ARM, LEVER_ARM_TOL_M, NOT_RUN,
    PASS, check_allan, check_lever_arm, overlapping_allan_deviation,
)

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
WAYPOINT = EXAMPLES / "cameras_waypoint.yaml"
ARMS = {"imu": [1.0, 0.0, 0.0], "gps": [-1.0, 0.0, -0.8],
        "pitot_static": [0.0, 2.0, 0.0], "magnetometer": [0.0, 0.0, 0.0]}


def fly(spec: ScenarioSpec):
    from core.scenario.runner import run_spec

    with contextlib.redirect_stdout(io.StringIO()):
        return run_spec(spec, assert_closure=False)


@pytest.fixture(scope="module")
def stated_run(tmp_path_factory):
    """The 30 s c172p flight with every instrument tactical, written to
    disk (telemetry.json, manifest.json, instruments.npz)."""
    spec = ScenarioSpec.read(WAYPOINT)
    for name, arm in ARMS.items():
        spec.set(f"instruments.{name}", {"profile": "tactical", "lever_arm_m": arm})
    result = fly(spec)
    out = tmp_path_factory.mktemp("stated")
    result.write(out)
    return result, out


def rewrite_npz(run_dir: Path, manifest: dict, edit, dest: Path) -> dict:
    """The file with one column edited, written to ``dest`` (never over
    the shared fixture's own file, which every other test grades against
    its sha256), and the manifest's sha256 put right (a corruption the
    digest alone would catch is not the point)."""
    with np.load(run_dir / I.INSTRUMENTS_FILE) as data:
        arrays = {name: np.array(data[name]) for name in data.files}
    edit(arrays)
    raw = I._deterministic_npz(arrays)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / I.INSTRUMENTS_FILE).write_bytes(raw)
    manifest = json.loads(json.dumps(manifest))
    manifest["instruments"]["sha256"] = hashlib.sha256(raw).hexdigest()
    return manifest


# -- the overlapping Allan deviation -----------------------------------------------------

def test_the_overlapping_allan_deviation_is_the_definition_and_recovers_n_within_25_pct():
    rng = np.random.default_rng(11)
    dt, density = 1.0 / 120.0, 0.125 / 60.0
    stream = rng.standard_normal(3601) * density / math.sqrt(dt)
    for m in (1, 2, 4, 8):
        adev, terms = overlapping_allan_deviation(stream, dt, m)
        assert terms == 3602 - 2 * m
        assert abs(adev / (density / math.sqrt(m * dt)) - 1.0) < ALLAN_TOL
        # ... and it is the formula, term by term, on a short series.
    short = np.array([1.0, -2.0, 0.5, 3.0, -1.0, 2.0])
    theta = np.concatenate([[0.0], np.cumsum(short) * 0.5])
    m = 1
    terms = [(theta[k + 2 * m] - 2.0 * theta[k + m] + theta[k]) ** 2 for k in range(len(theta) - 2 * m)]
    expected = math.sqrt(sum(terms) / (2.0 * (m * 0.5) ** 2 * len(terms)))
    assert overlapping_allan_deviation(short, 0.5, 1)[0] == pytest.approx(expected, rel=1e-12)
    # Six rates integrate to seven angles (theta_0 = 0), so m = 3 leaves
    # N - 2m = 1 term: two adjacent clusters of three, where the
    # overlapping and non-overlapping forms are the same number. m = 4
    # leaves none, and that is NaN.
    adev3, terms3 = overlapping_allan_deviation(short, 0.5, 3)
    assert terms3 == 1 and math.isfinite(adev3)
    assert adev3 == pytest.approx(I.allan_deviation(short, 0.5, 3)[0], rel=1e-12)
    adev4, terms4 = overlapping_allan_deviation(short, 0.5, 4)
    assert terms4 == -1 and math.isnan(adev4)
    # The two forms agree with each other on the same white stream (the
    # producer's non-overlapping one is core/telemetry/instruments.py's).
    for m in (1, 2, 4):
        own, _ = overlapping_allan_deviation(stream, dt, m)
        theirs, _ = I.allan_deviation(stream, dt, m)
        assert abs(own / theirs - 1.0) < 0.1


# -- check_allan ----------------------------------------------------------------------------

def test_check_allan_passes_the_real_run_and_says_b_and_k_are_not_run(stated_run):
    result, out = stated_run
    check = check_allan(result.manifest, out)
    assert check.status == PASS, check.detail
    assert "18 overlapping Allan points on 6 IMU residuals over 3601 samples at 120 Hz" in check.detail
    assert "B and K NOT RUN" in check.detail and "100" in check.detail
    assert f"within {ALLAN_TOL}" in check.detail
    worst = float(re.search(r"([0-9.]+) off\)", check.detail).group(1))
    assert worst < ALLAN_TOL


def test_check_allan_fails_a_file_whose_gyro_noise_was_doubled(stated_run, tmp_path):
    result, out = stated_run
    manifest = rewrite_npz(out, result.manifest, lambda a: a.__setitem__(
        "meas_p_dps", np.degrees(a["truth_p_rad_s"]) + 2.0 * (a["meas_p_dps"] - np.degrees(a["truth_p_rad_s"]))),
        tmp_path)
    check = check_allan(manifest, tmp_path)
    assert check.status == FAIL and check.failure == FAIL_ALLAN
    assert "meas_p_dps" in check.detail
    ratios = [float(m) for m in re.findall(r"\(([0-9.]+) off\)", check.detail)]
    assert ratios and all(0.7 < r < 1.3 for r in ratios)        # a doubled noise reads ~1.0 off
    # The edited file is graded against the sha256 the manifest recorded:
    # an edit without the manifest put right is a file failure by name,
    # while the fixture's own file still hashes to its manifest.
    check = check_allan(result.manifest, tmp_path)
    assert check.status == FAIL and check.failure == "instruments.file"
    assert check_allan(result.manifest, out).status == PASS


def test_check_allan_is_not_run_without_the_file_the_block_or_a_stated_imu(tmp_path):
    assert check_allan(None, None).status == NOT_RUN
    assert check_allan({}, tmp_path).status == NOT_RUN
    spec = ScenarioSpec.read(WAYPOINT)
    spec.set("duration", 2.0)
    default = fly(spec)
    out = tmp_path / "default"
    default.write(out)
    assert not (out / I.INSTRUMENTS_FILE).exists()
    check = check_allan(default.manifest, out)
    assert check.status == NOT_RUN and "ideal" in check.detail
    spec.set("instruments.gps", {"profile": "tactical", "lever_arm_m": [0.0, 0.0, 0.0]})
    gps_only = fly(spec)
    out = tmp_path / "gps_only"
    gps_only.write(out)
    check = check_allan(gps_only.manifest, out)
    assert check.status == NOT_RUN and "unstated" in check.detail


def test_check_allan_refuses_a_sample_spacing_off_the_manifests_rate(stated_run, tmp_path):
    result, out = stated_run
    manifest = rewrite_npz(out, result.manifest, lambda a: a.__setitem__("t", a["t"] * 2.0), tmp_path)
    check = check_allan(manifest, tmp_path)
    assert check.status == FAIL and check.failure == FAIL_ALLAN and "spacing" in check.detail


# -- check_lever_arm ------------------------------------------------------------------------

def test_check_lever_arm_recovers_both_arms_from_the_rolling_track(stated_run):
    result, out = stated_run
    check = check_lever_arm(result.manifest, out)
    assert check.status == PASS, check.detail
    gps = re.search(r"GPS arm recovered \[([^\]]+)\] m from (\d+) fixes.*?\|error\| ([0-9.]+) m", check.detail)
    imu = re.search(r"IMU arm recovered \[([^\]]+)\] m.*?\|error\| ([0-9.]+) m", check.detail)
    assert gps and int(gps.group(2)) == 151 and float(gps.group(3)) < 0.5     # measured 0.152 m
    assert imu and float(imu.group(2)) < 0.01                                  # measured 0.001 m
    recovered = [float(v) for v in imu.group(1).split(",")]
    assert recovered == pytest.approx(ARMS["imu"], abs=0.01)


def test_check_lever_arm_fails_when_the_manifest_declares_another_arm(stated_run, tmp_path):
    result, out = stated_run
    manifest = json.loads(json.dumps(result.manifest))
    manifest["instruments"]["instruments"]["imu"]["lever_arm_m"] = [0.0, 0.0, 0.0]
    check = check_lever_arm(manifest, out)
    assert check.status == FAIL and check.failure == FAIL_LEVER_ARM and "IMU arm" in check.detail
    manifest = json.loads(json.dumps(result.manifest))
    manifest["instruments"]["instruments"]["gps"]["lever_arm_m"] = [4.0, 0.0, -0.8]
    check = check_lever_arm(manifest, out)
    assert check.status == FAIL and check.failure == FAIL_LEVER_ARM and "GPS arm" in check.detail
    # A file whose GPS position lost its arm (the CG recorded as the antenna).
    # (Every GPS channel set to the CG's truth: the recovered arm is exactly
    # 0, |error| = |declared| = 1.28 m, beyond the 0.05 + 4 x 3 m / sqrt(151)
    # = 1.03 m the checker allows for the receiver's own noise.)
    manifest = rewrite_npz(out, result.manifest, lambda a: [
        a.__setitem__(f"meas_{k}", a[f"truth_{k}"]) for k in ("lat_deg", "lon_deg", "alt_m")], tmp_path)
    check = check_lever_arm(manifest, tmp_path)
    assert check.status == FAIL and check.failure == FAIL_LEVER_ARM and "GPS arm" in check.detail


def test_check_lever_arm_is_not_run_without_rotation_or_a_stated_instrument(stated_run, tmp_path):
    result, out = stated_run
    manifest = rewrite_npz(out, result.manifest, lambda a: [a.__setitem__(k, np.zeros_like(a[k]))
                                                             for k in ("truth_p_rad_s", "truth_q_rad_s", "truth_r_rad_s")],
                           tmp_path)
    manifest["instruments"]["instruments"]["gps"]["stated"] = False
    check = check_lever_arm(manifest, tmp_path)
    assert check.status == NOT_RUN and "no rotation" in check.detail
    assert check_lever_arm(None, None).status == NOT_RUN
    assert LEVER_ARM_TOL_M == 0.05 and ALLAN_BK_RUN_MULTIPLE == 100.0


def test_the_checks_import_nothing_from_the_producer():
    check_source = (REPO / "core/telemetry/instruments_check.py").read_text(encoding="utf-8")
    forbidden = re.compile(r"(from\s+\.?\S*instruments\s+import|import\s+\S*telemetry\.instruments\b"
                           r"|instruments\.(measure|load_profile|body_to_ned|first_order_lag|"
                           r"specific_force_body|rotational_terms|dipole_field_ned|InstrumentObserver))")
    assert not forbidden.search(check_source)
    assert not forbidden.search(_r2_verifier_source())
    assert "np.gradient" in check_source          # the checker's own omega_dot, not JSBSim's


# -- the verifier clauses (core/capture/verify.py) ---------------------------------------

R2_CHECKS = ("applied_readback", "null_effect", "instrument_allan", "instrument_lever_arm",
             "uncertainty_present")


def _verifier(name: str):
    """verify.py's own function of that name."""
    from core.capture import verify

    return getattr(verify, name)


def _r2_verifier_source() -> str:
    from core.capture import verify

    return "".join(inspect.getsource(getattr(verify, name)) for name in (
        "_applied_records", *(f"verify_{n}" for n in R2_CHECKS)))


def test_the_verifier_names_its_five_checks_runs_each_and_fails_by_catalogued_names():
    from core.capture import verify
    from core.messages import is_catalogued

    source = _r2_verifier_source()
    assert source.isascii()
    run_source = inspect.getsource(verify.verify_run)
    for name in R2_CHECKS:
        assert f'Check("{name}"' in source
        assert re.search(rf'run\("{name}", verify_{name}, manifest', run_source), name
        assert is_catalogued(f"check.{name}"), name
    assert verify.FAIL_READBACK == "record.readback"
    assert verify.FAIL_NULL_EFFECT == "annotation.null_effect"
    assert verify.FAIL_UNCERTAINTY == "check.uncertainty_present"
    for name in (verify.FAIL_READBACK, verify.FAIL_NULL_EFFECT, verify.FAIL_UNCERTAINTY,
                 FAIL_ALLAN, FAIL_LEVER_ARM, "instruments.file"):
        assert is_catalogued(name), name


def test_applied_readback_regrades_the_numbers_and_fails_by_name(stated_run):
    result, _ = stated_run
    check = _verifier("verify_applied_readback")(result.manifest)
    assert check.status == PASS and "5 readback(s)" in check.detail      # the datum's and the four instruments'
    manifest = json.loads(json.dumps(result.manifest))
    record = next(r for r in manifest["applied_variables"]["applied_variables"] if r["name"] == "instruments.imu")
    record["readback"]["value"] = record["readback"]["written"] + 1.0     # off by 1 g, flag untouched
    check = _verifier("verify_applied_readback")(manifest)
    assert check.status == FAIL and check.failure == "record.readback" and "instruments.imu" in check.detail
    record["readback"]["value"] = record["readback"]["written"]
    record["readback"]["agrees"] = False                                  # the flag lies the other way
    check = _verifier("verify_applied_readback")(manifest)
    assert check.status == FAIL and "says it does not" in check.detail
    assert _verifier("verify_applied_readback")({}).status == NOT_RUN
    assert _verifier("verify_applied_readback")({"applied_variables": {"record_version": 1, "applied_variables": [
        {"name": "x", "null_test": None}]}}).status == NOT_RUN


def test_null_effect_regrades_the_verdicts_and_fails_only_when_the_record_claims_otherwise(stated_run):
    result, _ = stated_run
    check = _verifier("verify_null_effect")(result.manifest)
    assert check.status == PASS, check.detail
    base = {"quantity": "q", "unit": "m", "with": 1.0, "without": 0.0, "difference": 1.0,
            "threshold": 0.5, "ok": True, "note": "", "kind": "reached"}

    def manifest_with(**null):
        return {"applied_variables": {"record_version": 1, "applied_variables": [
            {"name": "test.variable", "null_test": {**base, **null}}]}}

    verify_null_effect = _verifier("verify_null_effect")
    assert verify_null_effect(manifest_with()).status == PASS
    # An honest silence passes and is named.
    check = verify_null_effect(manifest_with(with_=None, **{"with": 0.1, "ok": False, "verdict": "silent"}))
    assert check.status == PASS and "honest silence" in check.detail and "test.variable" in check.detail
    # Silence the record contradicts: FAIL annotation.null_effect.
    check = verify_null_effect(manifest_with(**{"with": 1.0, "ok": True, "verdict": "silent"}))
    assert check.status == FAIL and check.failure == "annotation.null_effect" and "claims" in check.detail
    # ok against the arithmetic (either way), a reached verdict below threshold, a bounded kind.
    assert verify_null_effect(manifest_with(**{"with": 0.1, "ok": True})).status == FAIL
    assert verify_null_effect(manifest_with(**{"with": 1.0, "ok": False})).status == FAIL
    assert verify_null_effect(manifest_with(**{"with": 0.1, "ok": False, "verdict": "reached"})).status == FAIL
    assert verify_null_effect(manifest_with(**{"with": 0.1, "ok": True, "kind": "bounded"})).status == PASS
    assert verify_null_effect(manifest_with(**{"with": 0.1, "ok": True, "kind": "bounded",
                                               "verdict": "silent"})).status == PASS
    assert verify_null_effect(manifest_with(kind="sideways")).status == FAIL
    assert verify_null_effect({}).status == NOT_RUN


def test_the_instrument_checks_wrap_the_checker_and_report_not_run_on_absence(stated_run, tmp_path):
    result, out = stated_run
    allan = _verifier("verify_instrument_allan")(result.manifest, out)
    arm = _verifier("verify_instrument_lever_arm")(result.manifest, out)
    assert allan.name == "instrument_allan" and allan.status == PASS
    assert arm.name == "instrument_lever_arm" and arm.status == PASS
    assert _verifier("verify_instrument_allan")({}, tmp_path).status == NOT_RUN
    assert _verifier("verify_instrument_lever_arm")({}, tmp_path).status == NOT_RUN
    manifest = json.loads(json.dumps(result.manifest))
    manifest["instruments"]["instruments"]["imu"]["lever_arm_m"] = [0.0, 0.0, 0.0]
    check = _verifier("verify_instrument_lever_arm")(manifest, out)
    assert check.status == FAIL and check.failure == "instrument.lever_arm"


def test_uncertainty_present_is_not_run_without_the_block_and_regrades_the_sums():
    from core.uncertainty import u_val, uncertainty_block

    verify_uncertainty_present = _verifier("verify_uncertainty_present")
    assert verify_uncertainty_present({}).status == NOT_RUN
    u_num = {"srq": {"altitude_m": {"value": 0.03, "unit": "m", "basis": "GCI"},
                     "tas_kt": {"value": None, "unit": "kt", "basis": "NOT RUN: no column"}}}
    u_input = {"atmosphere.temperature_deviation_c": {"value": 2.0, "unit": "degC", "rule": "r",
                                                      "sensitivity": {"altitude_m": 0.5, "tas_kt": None}}}
    block = uncertainty_block(u_num, u_input)
    assert block["u_val"]["altitude_m"]["value"] == pytest.approx(math.sqrt(0.03 ** 2 + 1.0 ** 2))
    check = verify_uncertainty_present({"uncertainty": block})
    assert check.status == PASS and "1 u_val(s)" in check.detail
    bent = json.loads(json.dumps(block))
    bent["u_val"]["altitude_m"]["value"] = 0.03                     # the terms no longer sum to it
    check = verify_uncertainty_present({"uncertainty": bent})
    assert check.status == FAIL and check.failure == "check.uncertainty_present" and "root sum square" in check.detail
    bent = json.loads(json.dumps(block))
    bent["u_num"]["srq"]["tas_kt"]["basis"] = "unknown"
    assert verify_uncertainty_present({"uncertainty": bent}).status == FAIL
    bent = json.loads(json.dumps(block))
    del bent["form"]
    assert verify_uncertainty_present({"uncertainty": bent}).status == FAIL
    assert u_val(u_num, u_input)["tas_kt"]["value"] is None


def test_the_run_manifest_and_a_capture_style_manifest_carry_the_instruments_block(stated_run):
    result, out = stated_run
    block = result.manifest["instruments"]
    assert block["instruments_version"] == 1 and block["rate_basis"] == "fdm loop"
    assert block["recorded_rate_basis"] == "recorded telemetry, 10 Hz"
    assert block["file"] == I.INSTRUMENTS_FILE and len(block["sha256"]) == 64
    assert set(block["columns"]) == set(np.load(out / I.INSTRUMENTS_FILE).files)
    assert block["recorder_columns"] == list(I.MEASURED_CHANNEL_NAMES)
    assert set(block["seeds"]["streams"]) == set(I.OBSERVER_STREAMS)
    assert all(block["instruments"][n]["stated"] for n in ARMS)
    assert any("B and K" in n for n in block["not_claimed"])
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["instruments"]["sha256"] == block["sha256"]


def test_a_capture_of_a_stated_block_carries_the_file_and_the_verifier_grades_it(tmp_path, capsys):
    """End to end through flightsim/capture.py and verify_run: the stated
    instruments block writes instruments.npz beside the capture manifest,
    whose top-level instruments block names its sha256; the five R2
    checks run by name -- the Allan deviation and both lever arms PASS on
    the rolling track, every readback and null test re-grades, and the
    uncertainty block is NOT RUN (not asked for), never a pass."""
    from core.capture.manifest import SIDECAR_CONTEXT_KEYS
    from core.capture.verify import verify_run
    from flightsim.capture import main as capture_main

    spec = ScenarioSpec.read(WAYPOINT)
    for name, arm in ARMS.items():
        spec.set(f"instruments.{name}", {"profile": "tactical", "lever_arm_m": arm})
    path = tmp_path / "stated.yaml"
    spec.write(path)
    out = tmp_path / "capture"
    assert capture_main([str(path), "--out", str(out), "--max-previews", "0"]) == 0
    printed = capsys.readouterr().out
    assert "instruments at the FDM rate: 3601 steps at 120 Hz, 151 GPS fixes -> instruments.npz" in printed
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    block = manifest["instruments"]
    assert block["sha256"] == hashlib.sha256((out / I.INSTRUMENTS_FILE).read_bytes()).hexdigest()
    assert "instruments" in SIDECAR_CONTEXT_KEYS
    run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run_json["instruments"]["sha256"] == block["sha256"]
    names = {r["name"] for r in manifest["applied_variables"]["applied_variables"]}
    assert {f"instruments.{n}" for n in ARMS} <= names
    checks = {c.name: c for c in verify_run(out).checks}
    for name in ("instrument_allan", "instrument_lever_arm", "applied_readback", "null_effect"):
        assert checks[name].status == PASS, (name, checks[name].detail)
    assert checks["uncertainty_present"].status == NOT_RUN
