"""D2, the ``dis`` block and the wiring this item does not own: the spec
block behind set()/plan() (absent-canonical, the committed examples'
digests pinned), the validator's refusals by name, the registry entries
with every null pair run for real, the capture command's --dis /
--dis-udp / --cigi / --hla, flightsim.verify's dis_roundtrip on a real
capture, the recorder's yaw rate. Every flight here is a real JSBSim
flight (c172p, 1 s; the B747 of examples/cameras_multi.yaml, 12 s).

These tests pass once D2's integration patches are applied on HEAD
ec655e2 (measured on a scratch copy); on a tree without them they fail
by construction, which is the point of returning them.
"""
from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.messages import name_of
from core.records import read_records
from core.registry import NO_NULL, REGISTRY
from core.scenario.blocks import DIS_TIMESTAMP_MODES, DisSpec
from core.scenario.fields import Source
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_dis
from core.telemetry.recorder import DEFAULT_CHANNELS
from tests.test_dis_stream import VERIFY_DIS_PATCH
from tests.test_registry import EXAMPLE_DIGESTS

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
EXAMPLE = REPO / "examples/cameras_multi.yaml"


def spec_for(seconds: int = 1, **dis) -> ScenarioSpec:
    from core.nl.compiler import compile_prompt

    spec = compile_prompt(f"fly the c172p at 1500 m and 100 kt for {seconds} seconds")
    spec.set("hold_state", False, frm="test")
    for name, value in dis.items():
        spec.set(f"dis.{name}", value, frm="test")
    return spec


# -- the spec block -----------------------------------------------------------------------

def test_the_default_block_is_absent_canonical_and_every_committed_example_keeps_its_digest():
    spec = spec_for()
    assert spec.dis.is_default() and "dis" not in spec.to_dict()
    assert DisSpec.FIELD_ORDER == ("site", "application", "entity", "force_id", "marking",
                                   "timestamp_mode")
    assert DIS_TIMESTAMP_MODES == ("relative", "absolute")
    defaults = {name: q.value for name, q in DisSpec.defaulted().quantities()}
    assert defaults == {"site": 1, "application": 1, "entity": 1, "force_id": 0, "marking": "",
                        "timestamp_mode": "relative"}
    for path, digest in EXAMPLE_DIGESTS.items():
        example = ScenarioSpec.read(REPO / path)
        assert example.digest() == digest, path
        assert "dis" not in example.to_dict() and example.dis.is_default()


def test_a_stated_block_is_behind_the_front_door_round_trips_and_changes_the_digest(tmp_path):
    spec = spec_for()
    before = spec.digest()
    spec.set("dis.site", 7, frm="declared")
    assert spec.dis.site.source is Source.USER and spec.digest() != before
    data = spec.to_dict()["dis"]
    assert list(data) == list(DisSpec.FIELD_ORDER)
    assert data["site"]["value"] == 7 and data["marking"]["value"] == ""
    assert data["timestamp_mode"]["source"] == "default"
    spec.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(tmp_path / "s.yaml")
    assert reread.digest() == spec.digest() and reread.dis.site.value == 7
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("dis.site", 8, frm="a planner")
    spec.plan("dis.marking", "N12345", frm="a planner")
    assert spec.dis.marking.source is Source.DERIVED
    assert "dis" in spec.render_table()
    with pytest.raises(ValueError, match="unknown fields"):
        DisSpec.from_dict(dict(data, extra={"value": 1, "source": "user", "from": "x"}))
    with pytest.raises(ValueError, match="missing required field"):
        DisSpec.from_dict({k: v for k, v in data.items() if k != "entity"})
    assert inspect.getsource(DisSpec).isascii()


@pytest.mark.parametrize("field, value, name", [
    ("site", 70000, "interop.dis.entity_id"),
    ("application", -1, "interop.dis.entity_id"),
    ("entity", "seven", "interop.dis.entity_id"),
    ("force_id", 300, "dis.force_id"),
    ("marking", "ABCDEFGHIJKL", "dis.marking_too_long"),
    ("timestamp_mode", "lunar", "dis.timestamp_mode"),
])
def test_the_validator_refuses_by_name(field, value, name):
    spec = spec_for(**{field: value})
    assert [v.constraint for v in validate_dis(spec)] == [name]
    report = validate(spec, check_feasibility=False)
    assert name in [v.constraint for v in report.violations]
    assert "record.unregistered" not in [v.constraint for v in report.violations]
    assert validate_dis(spec_for()) == []
    assert validate(spec_for(site=7, marking="N12345", timestamp_mode="absolute"),
                    check_feasibility=False).ok


# -- the registry and the null pairs, for real ----------------------------------------------

@pytest.fixture(scope="module")
def flat_run():
    from core.scenario.runner import run_spec

    return run_spec(spec_for())


def test_the_registry_claims_every_dis_field_and_names_recorded_channels(flat_run):
    assert "dis" in REGISTRY.sections()
    assert {f"dis.{f}" for f in DisSpec.FIELD_ORDER} <= set(REGISTRY.spec_fields())
    for field in DisSpec.FIELD_ORDER:
        entry = REGISTRY.get(f"dis.{field}")
        assert entry.spec_path == f"dis.{field}" and entry.null_value is not NO_NULL
        assert entry.null_value == getattr(DisSpec.defaulted(), field).value
        assert not entry.jsbsim_writes and entry.readback_tolerance is None
        for channel in entry.effect_channels:
            assert channel.name in flat_run.telemetry.columns, channel.name
    data = spec_for(site=7).to_dict()
    assert REGISTRY.unregistered_fields(data) == []
    assert {n for n in REGISTRY.stated_variables(data) if n.startswith("dis.")} == {
        f"dis.{f}" for f in DisSpec.FIELD_ORDER}


@pytest.mark.timeout(300)
def test_every_dis_null_pair_measures_zero_for_real():
    """Each field stated off its null against the null: the same flight
    (output digests equal), peak 0.0 on every effect channel, verdict
    silent -- the bounded invariance the registry basis states: the block
    labels the export and reaches no equation of motion."""
    from core.record_null import run_null_pair
    from core.scenario.runner import run_spec

    runner = lambda spec: run_spec(spec, assert_closure=False)     # noqa: E731
    stated = {"site": 7, "application": 3, "entity": 42, "force_id": 1, "marking": "N12345",
              "timestamp_mode": "absolute"}
    for field, value in stated.items():
        pair = run_null_pair(spec_for(**{field: value}), f"dis.{field}", runner=runner)
        assert pair.applied_value == value and pair.null_value == REGISTRY.get(f"dis.{field}").null_value
        assert pair.with_spec_digest != pair.without_spec_digest
        assert not pair.digests_differ, field
        assert pair.verdict == "silent", field
        assert all(e.peak_abs == 0.0 and e.rms == 0.0 for e in pair.effects), field
        assert pair.null_test().ok is False


# -- the capture command ----------------------------------------------------------------------

def _capture(out: Path, *extra: str, spec: Path = EXAMPLE) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "flightsim.capture", str(spec), "--out", str(out), "--max-previews", "0",
         *extra], cwd=str(REPO), capture_output=True, text=True, timeout=600)


@pytest.fixture(scope="module")
def dis_run(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("dis_block") / "run"
    result = _capture(out, "--dis", "--dis-entity-type", "fallback")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "  dis:      " in result.stdout
    return out


def test_the_capture_writes_the_log_the_record_and_the_frame_keys(dis_run):
    from core.interop.dis_stream import INDEX_FILE, STREAM_FILE, read_index

    index = read_index(dis_run)
    telemetry = json.loads((dis_run / "telemetry.json").read_text(encoding="utf-8"))
    n = telemetry["samples"]
    assert index["pdu_count"] == n and (dis_run / STREAM_FILE).stat().st_size == n * 144
    assert index["aircraft"] == "B747" and index["marking"] == {
        "text": "B747", "source": "derived", "character_set": "1 (ASCII)", "bytes": 11}
    assert index["entity_type"]["source"] == "fallback"
    assert index["datum"]["hae_source"].startswith("hae_m:")
    assert index["udp"]["sent"] is False
    manifest = json.loads((dis_run / "capture_manifest.json").read_text(encoding="utf-8"))
    records = {r["name"]: r for r in read_records(manifest["applied_variables"])}
    assert "dis.entity_state" in records
    record = records["dis.entity_state"]
    assert record["value"] == n and record["frame_keys"] == ["dis.pdu_index", "dis.byte_offset"]
    assert record["parameters"]["stream_file"] == STREAM_FILE
    assert record["parameters"]["index_file"] == INDEX_FILE
    assert record["readback"]["agrees"]
    for frame in manifest["frames"]:
        assert frame["dis"] == {"pdu_index": frame["sample_index"],
                                "byte_offset": frame["sample_index"] * 144}
    run = json.loads((dis_run / "run.json").read_text(encoding="utf-8"))
    assert "dis.entity_state" in [r["name"] for r in read_records(run["applied_variables"])]
    # The per-frame sidecar carries the keys with the frame record.
    sidecar = json.loads((dis_run / (manifest["frames"][0]["file"][:-4] + ".json")).read_text(encoding="utf-8"))
    assert sidecar["frame"]["dis"]["pdu_index"] == manifest["frames"][0]["sample_index"]
    # D2's recorder channel: the yaw rate is recorded, so r is a recorded rate.
    assert "yaw_rate_dps" in telemetry["columns"]
    assert index["dead_reckoning"]["source"]["r"].startswith("recorded yaw_rate_dps")


def test_the_verifier_reports_dis_roundtrip_pass_on_the_capture(dis_run):
    result = subprocess.run([PYTHON, "-m", "flightsim.verify", str(dis_run)],
                            cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    verification = json.loads((dis_run / "verification.json").read_text(encoding="utf-8"))
    (check,) = [c for c in verification["checks"] if c["name"] == "dis_roundtrip"]
    assert check["status"] == "PASS", check
    assert "Entity State PDUs walked by the checker's own layout" in check["detail"]
    assert "[PASS] dis_roundtrip" in result.stdout


def test_a_capture_without_dis_reports_the_clause_not_run(tmp_path):
    out = tmp_path / "plain"
    assert _capture(out).returncode == 0
    result = subprocess.run([PYTHON, "-m", "flightsim.verify", str(out)],
                            cwd=str(REPO), capture_output=True, text=True, timeout=600)
    assert result.returncode == 0
    verification = json.loads((out / "verification.json").read_text(encoding="utf-8"))
    (check,) = [c for c in verification["checks"] if c["name"] == "dis_roundtrip"]
    assert check["status"] == "NOT RUN" and "without --dis" in check["detail"]
    manifest = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    assert "dis" not in manifest["frames"][0]
    assert "dis.entity_state" not in [r["name"] for r in read_records(manifest["applied_variables"])]


def test_the_empty_standard_table_and_a_missing_epoch_refuse_before_any_flight(tmp_path):
    out = tmp_path / "standard"
    result = _capture(out, "--dis")
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- dis.entity_type_unknown:")
    assert not (out / "telemetry.json").exists()          # nothing flew
    assert "running headlessly" not in result.stdout       # refused BEFORE the flight
    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("dis.timestamp_mode", "absolute", frm="test")
    spec.write(tmp_path / "absolute.yaml")
    result = _capture(tmp_path / "absolute", "--dis", "--dis-entity-type", "fallback",
                      spec=tmp_path / "absolute.yaml")
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- dis.timestamp_epoch_missing:")
    assert not (tmp_path / "absolute" / "telemetry.json").exists()
    assert "running headlessly" not in result.stdout
    result = _capture(tmp_path / "epoch", "--dis", "--dis-entity-type", "unspecified",
                      "--dis-epoch", "2026-09-29T10:00:00Z", spec=tmp_path / "absolute.yaml")
    assert result.returncode == 0, result.stdout + result.stderr
    from core.interop.dis_stream import read_index
    index = read_index(tmp_path / "epoch")
    assert index["timestamp_mode"] == "absolute" and index["timestamp"]["lsb"] == 1
    assert index["entity_type"]["septuplet"] is None


def test_cigi_and_hla_are_refused_by_name_before_anything_runs(tmp_path):
    for flag, name in (("--cigi", "interop.cigi_not_implemented"),
                       ("--hla", "interop.hla_not_implemented")):
        out = tmp_path / flag.strip("-")
        result = _capture(out, flag)
        assert result.returncode == 2
        assert result.stdout.startswith(f"REFUSED -- {name}:"), result.stdout
        assert not out.exists()


def test_dis_udp_in_a_campaign_case_refuses_before_the_flight(tmp_path):
    campaign = tmp_path / "campaign"
    (campaign / "runs").mkdir(parents=True)
    (campaign / "campaign.json").write_text("{}", encoding="utf-8")
    out = campaign / "runs" / "case_0001"
    result = _capture(out, "--dis-udp", "127.0.0.1:3000", "--dis-entity-type", "fallback")
    assert result.returncode == 2
    assert result.stdout.startswith("REFUSED -- dis.udp_in_campaign:")
    assert not (out / "telemetry.json").exists()
    # The campaign's own command builder never emits the option.
    from core.dataset.batch import capture_command
    command = capture_command(Path("s.yaml"), out, {"dis_udp": "127.0.0.1:3000", "dis": True})
    assert "--dis-udp" not in command and "--dis" not in command


# -- the verifier text, integrated and pinned ------------------------------------------------

def test_the_verifier_clause_is_integrated_and_pinned_to_the_returned_text():
    from core.capture import verify

    for name in ("_dis_walk", "_dis_own_euler", "_dis_hae", "verify_dis_roundtrip"):
        assert inspect.getsource(getattr(verify, name)) in VERIFY_DIS_PATCH, name
    assert verify.DIS_LOCATION_TOL_M == 0.05 and verify.DIS_EULER_TOL_RAD == 1e-4
    text = (REPO / "core/capture/verify.py").read_text(encoding="utf-8")
    assert 'run("dis_roundtrip", verify_dis_roundtrip, manifest, run_dir)' in text
    assert "from core.interop" not in text and "from ..interop" not in text


def test_the_recorder_carries_the_yaw_rate():
    assert "yaw_rate_dps" in DEFAULT_CHANNELS
    from core.capture.manifest import channel_unit
    assert channel_unit("yaw_rate_dps") == "deg/s"


def test_d2_texts_in_the_patched_files_are_ascii():
    from core.scenario import validate as v

    assert inspect.getsource(v.validate_dis).isascii()
    assert inspect.getsource(DisSpec).isascii()
    for name in ("dis.site", "dis.marking", "dis.timestamp_mode"):
        assert json.dumps(REGISTRY.get(name).to_dict()).isascii()
