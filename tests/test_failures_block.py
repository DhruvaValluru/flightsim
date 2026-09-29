"""The failure schedule's wiring (work item P3, the integration patches):
the ``failures`` spec block behind the front door and absent-canonical,
the validator's refusals by name, the registry's claim, the runner's
derivation and per-step application, the engine channels recorded per
airframe (never NaN), the card block, and the null pairs measured with
core.record_null.run_null_pair on the c172p and the A320.

Written against HEAD 5ca68f0 plus P3's integration patches (the file
lands with them); every number here was measured on the patched tree
in this container (JSBSim 1.2.4, 120 Hz). Not claimed: any statement
about an aeroplane; the engine side.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path

import pytest

from core.capture.manifest import state_units, suffix_unit
from core.nl.compiler import compile_prompt
from core.record_null import FLOORS_BY_UNIT, attach_null_pair, run_null_pair
from core.records import read_records
from core.registry import NO_NULL, REGISTRY
from core.scenario.blocks import FAILURE_KINDS, FailuresSpec
from core.scenario.card import failure_schedule_card_block, write_run_card
from core.scenario.runner import fdm_at_initial_conditions, run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_failures
from core.telemetry.failures import CARD_EVENT_KEYS, CARD_KEYS, FLAG_COLUMN, KINDS
from core.telemetry.recorder import DEFAULT_CHANNELS

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/cameras_waypoint.yaml"
#: The committed spec-8 examples' digests at HEAD (tests/test_registry.py
#: pins the same eight): the block adds no key to a spec that states none.
EXAMPLE_DIGESTS = {
    "examples/cameras_event_trigger.yaml": "cb2f5b5500584bd84c8aa84749c854a9c67f1c366db2ec97e9cb0c8ee150b8b0",
    "examples/cameras_hazard_refusal.yaml": "148f87bc37eab96c8f029e048dbf4f8328ad3247fa0596f10e71c81914d509de",
    "examples/cameras_mountain_refusal.yaml": "58a36aa0943b0dd895d79c89d7031525b6fc29e55ec47b927b4b3e7ccbfb2496",
    "examples/cameras_multi.yaml": "84e53a6931489f90fec8d0a750a1fd745bb630d0a2186befba659c68e2396f45",
    "examples/cameras_refusal.yaml": "d3565392215f6db2b66060c41554d10b4916779b9319e2c3a7063b3a04eb6a9a",
    "examples/cameras_terrain.yaml": "4b7b5dbdc8ba0a04cb3408f6e70c19be3d0e28c4053762ee30551c23d751acf3",
    "examples/cameras_waypoint.yaml": "9760294005e1efcae1777ad4a2035fe3733d219428c477c6c7caf2f0220b2372",
    "examples/randomized.yaml": "102d38250e4b7c9b4b6737af5e3e2886fad0748aa4e7af825ce8388e4fe7fda1",
}
HARDOVER = [{"kind": "hardover", "target": "elevator", "at_s": 1.0}]
JAM = [{"kind": "control_jam", "target": "elevator", "at_s": 1.0}]
ENGINE_OUT = [{"kind": "engine_out", "target": 0, "at_s": 1.0}]


def c172p_spec(events=None, duration=5.0) -> ScenarioSpec:
    """The committed c172p example (1200 m, 100 kt, open loop)."""
    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("duration", duration, frm="test")
    if events is not None:
        spec.set("failures.events", events, frm="test")
    return spec


def a320_spec(events=None, duration=6.0, hold=False, turbulence=None) -> ScenarioSpec:
    spec = compile_prompt("fly the A320 at 1500 m and 250 kt for 6 seconds")
    spec.set("hold_state", hold, frm="test")
    spec.set("duration", duration, frm="test")
    if turbulence is not None:
        spec.set("turbulence", turbulence, frm="test")
    if events is not None:
        spec.set("failures.events", events, frm="test")
    return spec


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# -- the block ---------------------------------------------------------------------

def test_the_block_defaults_to_no_events_and_every_committed_example_keeps_its_digest():
    assert FailuresSpec.FIELD_ORDER == ("events",) and FailuresSpec.BLOCK == "failures"
    assert FailuresSpec.defaulted().events.value == [] and FailuresSpec.defaulted().is_default()
    assert set(FAILURE_KINDS) == set(KINDS)
    for path, digest in EXAMPLE_DIGESTS.items():
        spec = ScenarioSpec.read(REPO / path)
        assert spec.digest() == digest, path
        assert "failures" not in spec.to_dict() and spec.failures.is_default()
        assert validate_failures(spec) == []


def test_a_stated_schedule_is_behind_the_front_door_round_trips_and_changes_the_digest(tmp_path):
    spec = c172p_spec(HARDOVER)
    before = c172p_spec().digest()
    data = spec.to_dict()
    assert list(data["failures"]) == ["events"]
    assert data["failures"]["events"]["value"] == HARDOVER
    assert data["failures"]["events"]["source"] == "user"
    assert spec.digest() != before
    spec.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(tmp_path / "s.yaml")
    assert reread.digest() == spec.digest() and reread.failures.events.value == HARDOVER
    assert "failures" in spec.render_table()
    with pytest.raises(ValueError):
        spec.set("failures.when", [], frm="test")


@pytest.mark.parametrize("events, name", [
    ([{"kind": "wing_loss", "target": "elevator", "at_s": 1.0}], "failures.kind"),
    ([{"kind": "control_jam", "target": "flap", "at_s": 1.0}], "failures.target"),
    ([{"kind": "engine_out", "target": 1, "at_s": 1.0}], "failures.target"),     # the c172p has one
    ([{"kind": "hardover", "target": "rudder", "at_s": -1.0}], "failures.time"),
    ([{"kind": "hardover", "target": "rudder", "at_s": 99.0}], "failures.time"),
    ([{"kind": "float", "target": "rudder", "at_s": 2.0},
      {"kind": "float", "target": "aileron", "at_s": 1.0}], "failures.time"),
    ([{"kind": "authority_loss", "target": "elevator", "at_s": 1.0, "value": 2.0}], "failures.value"),
    ([{"kind": "control_jam", "target": "elevator", "at_s": 1.0, "value": 1.0}], "failures.value"),
])
def test_the_validator_refuses_a_bad_schedule_by_name(events, name):
    spec = c172p_spec(events)
    report = quiet(validate, spec, check_feasibility=False)
    assert not report.ok
    assert [v.constraint for v in report.violations] == [name], report.render()


def test_a_surface_failure_on_an_airframe_the_chain_cannot_anchor_on_is_refused_before_any_flight():
    spec = c172p_spec(JAM)
    spec.set("aircraft", "DHC6", frm="test")
    report = quiet(validate, spec, check_feasibility=False)
    names = [v.constraint for v in report.violations]
    assert "failures.actuator_missing" in names, report.render()
    assert quiet(validate, c172p_spec(JAM), check_feasibility=False).ok
    assert quiet(validate, c172p_spec(ENGINE_OUT), check_feasibility=False).ok


# -- the registry ----------------------------------------------------------------------

def test_the_registry_claims_the_block_and_the_five_kinds():
    assert "failures" in REGISTRY.sections()
    assert REGISTRY.spec_fields()["failures.events"] == "failures.events"
    events = REGISTRY.get("failures.events")
    assert events.null_value == [] and events.unit == "events" and not events.jsbsim_writes
    for kind in KINDS:
        entry = REGISTRY.get(f"failures.{kind}")
        assert entry.spec_path is None and entry.null_value is NO_NULL
        assert entry.readback_tolerance is not None and entry.readback_tolerance.value == 0.0
        assert any(c.name == FLAG_COLUMN for c in entry.effect_channels)
    assert REGISTRY.unregistered_fields(c172p_spec(HARDOVER).to_dict()) == []
    assert quiet(validate, c172p_spec(HARDOVER), check_feasibility=False).ok
    assert FLOORS_BY_UNIT["rpm"] == 10.0


# -- the runner --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def c172p_run():
    """Hardover at 1 s and engine-out at 2 s on the open-loop c172p."""
    return quiet(run_spec, c172p_spec(HARDOVER + [{"kind": "engine_out", "target": 0, "at_s": 2.0}]),
                 assert_closure=False)


@pytest.fixture(scope="module")
def a320_run():
    return quiet(run_spec, a320_spec(ENGINE_OUT), assert_closure=False)


def test_the_runner_derives_the_chain_only_for_a_surface_failure(c172p_run, a320_run):
    assert c172p_run.manifest["fdm"]["derivation"]["suffix"] == "-fail"
    assert c172p_run.manifest["fdm"]["derivation"]["injections"][0]["name"] == "failures"
    assert "derivation" not in a320_run.manifest["fdm"]         # engine-out alone: stock
    fdm = quiet(fdm_at_initial_conditions, a320_spec(JAM, hold=True))
    assert fdm.derived.name == "A320-tecs-fail"
    fdm = quiet(fdm_at_initial_conditions, c172p_spec())
    assert fdm.derived is None


def test_the_run_manifest_carries_the_block_the_records_and_the_applied_list(c172p_run):
    block = c172p_run.manifest["failures"]
    assert block["count"] == 2 and block["applied_count"] == 2 and block["needs_injection"]
    hard, engine = block["applied"]
    assert list(hard) == ["kind", "target", "at_s", "t_applied_s", "property", "written",
                          "readback", "agrees"]
    assert 0.0 <= hard["t_applied_s"] - 1.0 < 1.0 / 120.0 and hard["agrees"] is True
    assert 0.0 <= engine["t_applied_s"] - 2.0 < 1.0 / 120.0 and engine["agrees"] is True
    assert engine["property"] == "propulsion/engine/set-running" and engine["readback"] == 0.0
    assert block["engine_types"] == [None, "piston"]
    names = [r["name"] for r in read_records(c172p_run.manifest["applied_variables"])]
    assert names == ["limits.monitor", "failures.hardover[0]", "failures.engine_out[1]",
                     "failures.events", "scene.geoid_undulation_m"]
    records = {r["name"]: r for r in read_records(c172p_run.manifest["applied_variables"])}
    assert records["failures.hardover[0]"]["readback"]["agrees"] is True
    assert records["failures.hardover[0]"]["null_test"]["ok"] is True
    assert records["failures.engine_out[1]"]["null_test"]["ok"] is True
    assert records["failures.events"]["null_test"]["ok"] is True
    assert records["failures.events"]["readback"]["agrees"] is True
    for record in records.values():
        assert "model_block" in record or record["name"] in ("limits.monitor", "scene.geoid_undulation_m")


def test_every_registered_effect_channel_is_a_recorded_column_with_a_unit(c172p_run):
    recorded = set(c172p_run.telemetry.columns)
    for name in ["failures.events"] + [f"failures.{k}" for k in KINDS]:
        entry = REGISTRY.get(name)
        missing = [c.name for c in entry.effect_channels if c.name not in recorded]
        assert missing == [], (name, missing)
    units = state_units(c172p_run.telemetry.columns)
    assert units[FLAG_COLUMN] == "1" and units["engine0_thrust_n"] == "N"
    assert units["engine0_rpm"] == "rpm" and suffix_unit("engine1_rpm") == "rpm"
    assert "?" not in {units[c] for c in recorded}
    assert FLAG_COLUMN not in DEFAULT_CHANNELS      # the schedule's extras, like the stack's
    assert not {c for c in recorded if c.startswith("engine")} & set(DEFAULT_CHANNELS)


def test_the_engine_channels_are_the_airframes_own_and_never_nan(c172p_run, a320_run, tmp_path):
    """The c172p (one piston): thrust and rpm, no N1 column, no engine 1
    column. The A320 (two turbines): thrust and N1 on both, no rpm
    column. A quantity the airframe lacks has no column -- never NaN
    (measured: a bare NaN token breaks the web app's JSON.parse of
    telemetry.json) and never 0 (a zero thrust is what an engine-out
    looks like)."""
    c = c172p_run.telemetry.columns
    assert {k for k in c if k.startswith("engine")} == {"engine0_thrust_n", "engine0_rpm"}
    a = a320_run.telemetry.columns
    assert {k for k in a if k.startswith("engine")} == {"engine0_thrust_n", "engine0_n1_pct",
                                                        "engine1_thrust_n", "engine1_n1_pct"}
    for run in (c172p_run, a320_run):
        assert all(math.isfinite(v) for col in run.telemetry.columns.values() for v in col)
    assert c172p_run.manifest["failures"]["engine_columns"] == ["engine0_thrust_n", "engine0_rpm"]
    c172p_run.write(tmp_path)
    text = (tmp_path / "telemetry.json").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    assert json.loads(text)["columns"]["engine0_rpm"] == c["engine0_rpm"]
    records = {r["name"]: r for r in read_records(c172p_run.manifest["applied_variables"])}
    assert records["failures.engine_out[1]"]["telemetry_columns"] == [
        FLAG_COLUMN, "engine0_thrust_n", "engine0_rpm", "altitude_m", "tas_kt", "heading_deg"]
    assert "NaN" not in json.dumps(c172p_run.manifest)


def test_the_engine_out_shows_in_the_columns_and_the_flag_flips_once(c172p_run, a320_run):
    a = a320_run.telemetry.columns
    t0 = a["t"][0]
    before = [v for t, v in zip(a["t"], a["engine0_thrust_n"]) if t - t0 < 0.95]
    after = [v for t, v in zip(a["t"], a["engine0_thrust_n"]) if t - t0 > 1.05]
    assert min(before) > 50000.0 and set(after) == {0.0}
    assert a["engine0_n1_pct"][-1] < 25.0 and a["engine1_n1_pct"][-1] > 80.0
    flag = a[FLAG_COLUMN]
    assert flag[0] == 0.0 and flag[-1] == 1.0 and flag == sorted(flag)
    c = c172p_run.telemetry.columns
    assert c["engine0_rpm"][0] > 2200.0 and c["engine0_rpm"][-1] < 1500.0
    assert c["elevator_deg"][-1] == pytest.approx(22.99566, abs=1e-3)   # the +23 deg stop


# -- the card ------------------------------------------------------------------------------

def test_the_card_carries_the_schedule_in_the_fixed_key_order(tmp_path):
    assert failure_schedule_card_block(c172p_spec()) is None
    spec = c172p_spec(HARDOVER + [{"kind": "engine_out", "target": 0, "at_s": 2.0},
                                  {"kind": "authority_loss", "target": "rudder", "at_s": 3.0, "value": 0.5}])
    block = failure_schedule_card_block(spec)
    assert tuple(block) == CARD_KEYS and block["count"] == 3
    assert [tuple(e) for e in block["events"]] == [CARD_EVENT_KEYS] * 3
    assert block["events"][1] == {"kind": "engine_out", "target": 0, "at_s": 2.0,
                                  "property": "propulsion/magneto_cmd", "value": 0.0}
    a320 = failure_schedule_card_block(a320_spec(ENGINE_OUT))
    assert a320["events"][0]["property"] == "propulsion/cutoff_cmd" and a320["events"][0]["value"] == 1.0
    assert block["events"][2]["value"] == 0.5
    quiet(write_run_card, spec, tmp_path / "card.json")
    card = json.loads((tmp_path / "card.json").read_text(encoding="utf-8"))
    assert card["failure_schedule"] == block
    quiet(write_run_card, c172p_spec(), tmp_path / "plain.json")
    assert "failure_schedule" not in json.loads((tmp_path / "plain.json").read_text(encoding="utf-8"))
    assert (tmp_path / "card.json").read_text(encoding="utf-8").isascii()


# -- the null pairs ------------------------------------------------------------------------

@pytest.mark.timeout(600)
def test_the_null_pairs_on_the_c172p_hardover_reaches_the_jam_is_honestly_silent_the_engine_out_reaches():
    """Measured: the elevator hardover moves altitude by 84.1 m, heading
    4.9 deg, pitch 53.3 deg, TAS 20.4 kt over 5 s against no schedule;
    the open-loop jam moves nothing (0.0 on every channel: the command
    never moves in an open-loop run, and the c172p cannot hold its
    state here -- the sign probe's 6000 m / 280 kt trim refuses it), so
    its verdict is silent and said so; the engine-out over 8 s moves
    altitude 1.9 m, heading 4.1 deg, TAS 14.8 kt."""
    hard = quiet(run_null_pair, c172p_spec(HARDOVER), "failures.events")
    assert hard.verdict == "reached" and hard.digests_differ and hard.null_value == []
    effect = {e.channel: e for e in hard.effects}
    assert effect["altitude_m"].peak_abs > 50.0 and effect["heading_deg"].peak_abs > 3.0
    assert effect["pitch_deg"].peak_abs > 40.0 and effect["tas_kt"].peak_abs > 10.0
    assert effect[FLAG_COLUMN].peak_abs == 1.0 and effect[FLAG_COLUMN].reached is None
    manifest = {"applied_variables": quiet(run_spec, c172p_spec(HARDOVER), assert_closure=False).manifest["applied_variables"]}
    assert attach_null_pair(manifest, hard)
    record = {r["name"]: r for r in manifest["applied_variables"]["applied_variables"]}["failures.events"]
    assert record["null_test"]["verdict"] == "reached" and record["null_test"]["ok"]
    jam = quiet(run_null_pair, c172p_spec(JAM), "failures.events")
    assert jam.verdict == "silent" and jam.digests_differ
    assert all(e.peak_abs == 0.0 for e in jam.effects if e.channel != FLAG_COLUMN)
    engine = quiet(run_null_pair, c172p_spec(ENGINE_OUT, duration=8.0), "failures.events")
    assert engine.verdict == "reached"
    effect = {e.channel: e for e in engine.effects}
    assert effect["altitude_m"].peak_abs > 1.0 and effect["heading_deg"].peak_abs > 2.0
    assert effect["tas_kt"].peak_abs > 5.0


@pytest.mark.timeout(600)
def test_the_null_pairs_on_the_a320_engine_out_open_loop_and_under_tecs_and_the_jam_under_tecs():
    """Measured: engine-out vs none, open loop 6 s: altitude 3.1 m,
    heading 0.82 deg, TAS 7.3 kt; under TECS: altitude 10.0 m, heading
    0.63 deg, TAS 3.0 kt (the energy loop reacts, the yaw is not
    compensated: TECS has no lateral loop -- stated, not fixed); the
    elevator jam under TECS in calm air is silent (0.02 m: the
    controller barely moves the elevator at cruise) and in moderate
    turbulence reaches (altitude 1.59 m, pitch 1.50 deg, TAS 0.27 kt)
    while the surface holds."""
    open_loop = quiet(run_null_pair, a320_spec(ENGINE_OUT), "failures.events")
    assert open_loop.verdict == "reached"
    effect = {e.channel: e for e in open_loop.effects}
    assert effect["altitude_m"].peak_abs > 2.0 and effect["heading_deg"].peak_abs > 0.5
    held = quiet(run_null_pair, a320_spec(ENGINE_OUT, hold=True), "failures.events")
    assert held.verdict == "reached"
    effect = {e.channel: e for e in held.effects}
    assert effect["heading_deg"].peak_abs > 0.3          # no yaw compensation
    calm = quiet(run_null_pair, a320_spec(JAM, hold=True), "failures.events")
    assert calm.verdict == "silent" and calm.digests_differ
    rough = quiet(run_null_pair, a320_spec(JAM, hold=True, turbulence="moderate"), "failures.events")
    assert rough.verdict == "reached"
    effect = {e.channel: e for e in rough.effects}
    assert effect["altitude_m"].peak_abs > 0.5 and effect["pitch_deg"].peak_abs > 0.5
    run = quiet(run_spec, a320_spec(JAM, hold=True, turbulence="moderate"), assert_closure=False)
    hold = run.manifest["failures"]["hold"][0]
    assert hold["steps"] == 100 and hold["max_abs_drift"] == 0.0 and hold["ok"] is True
