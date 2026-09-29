"""The failure schedule (core/telemetry/failures.py, work item P3): the
refusals by name, the write at the first step at or past the stated
time (V15), the read-back on the following step, the jam hold, the
hardover, the float, the authority loss and the engine-out -- the
mechanics on a fake FDM, every number on the installed JSBSim 1.2.4
with the c172p and the A320 (measured in this container; the numbers
asserted are the ones read here).

Not claimed: any of these is a statement about the JSBSim models'
tables and JSBSim's own malfunction and propulsion code, not about an
aeroplane; the spec block, the validator, the runner, the card and the
registry wiring are integration patches measured in
tests/test_failures_block.py on the patched tree.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.control.autopilot import Autopilot
from core.fdm import units as u
from core.fdm.fdm import FlightDynamics, TrimMode
from core.records import AppliedVariable
from core.telemetry import failures as module
from core.telemetry.failures import (
    ACTIVE_ENGINE, APPLIED_KEYS, AUTHORITY_HOLD_TOLERANCE, CARD_EVENT_KEYS, CARD_KEYS,
    CUTOFF_CMD, FLAG_COLUMN, JAM_HOLD_STEPS, JAM_HOLD_TOLERANCE_RAD, KINDS, MAGNETO_CMD,
    PISTON_SETTLE_S, SURFACE_KINDS, SURFACES, FailureError, FailureEvent, FailureSchedule,
    airframe_facts, engine_property, event_problems, failure_injections_for, hold_check,
    problems,
)
from core.telemetry.recorder import Recorder

REPO = Path(__file__).resolve().parents[1]
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
DT = 1.0 / 120.0
#: The runner's surface columns (core/scenario/runner.py SURFACES), read
#: here so the recorder carries what the runner's does.
SURFACE_EXTRAS = {
    "elevator_deg": lambda f: math.degrees(f.props.get("fcs/elevator-pos-rad")),
    "aileron_deg": lambda f: math.degrees(f.props.get("fcs/left-aileron-pos-rad")),
    "rudder_deg": lambda f: math.degrees(f.props.get("fcs/rudder-pos-rad")),
}


# -- a fake FDM for the mechanics ------------------------------------------------------

class FakeProps:
    def __init__(self, values, deaf=()):
        self.values = dict(values)
        self.deaf = set(deaf)          # properties whose writes do not latch
        self.log = []

    def has(self, name):
        return name in self.values

    def get(self, name):
        return self.values[name]

    def set(self, name, value):
        if name not in self.values:
            raise KeyError(name)
        self.log.append((name, float(value)))
        if name not in self.deaf:
            self.values[name] = float(value)


class FakeFDM:
    """A clock and a property store; ``step`` advances the clock. The
    schedule's hook is called the way FlightDynamics.step calls it: at
    the top of the step, before the clock moves."""

    def __init__(self, values, deaf=(), t0=4.875, dt=DT, name="fake"):
        self.props = FakeProps(values, deaf)
        self.sim_time = t0
        self.dt = dt
        self.aircraft_name = name
        self.hooks = []

    def step(self):
        for hook in self.hooks:
            hook(self)
        self.sim_time += self.dt


def surface_values(surface="elevator"):
    return {
        f"failure/{surface}/actuator/malfunction/fail_stuck": 0.0,
        f"failure/{surface}/actuator/malfunction/fail_hardover": 0.0,
        f"failure/{surface}/actuator/malfunction/fail_zero": 0.0,
        f"failure/{surface}/authority": 1.0,
        f"failure/{surface}/cmd-in": -0.2,
        f"fcs/{surface}-cmd-norm": -0.2,
        module.POSITION_PROPERTIES[surface]: 0.1,
    }


def turbine_values():
    return {"propulsion/engine/set-running": 1.0, "propulsion/engine/thrust-lbs": 5000.0,
            "propulsion/engine/n1": 80.0, CUTOFF_CMD: 0.0, ACTIVE_ENGINE: -1.0}


# -- refusals by name --------------------------------------------------------------------

@pytest.mark.parametrize("events, name, fragment", [
    ([{"kind": "wing_loss", "target": "elevator", "at_s": 1.0}], "failures.kind", "one of"),
    (["engine_out"], "failures.kind", "not a mapping"),
    ([{"kind": "control_jam", "target": "elevator", "at_s": 1.0, "when": 2}], "failures.kind",
     "unknown keys"),
    ([{"kind": "control_jam", "target": "flap", "at_s": 1.0}], "failures.target", "surface"),
    ([{"kind": "engine_out", "target": "left", "at_s": 1.0}], "failures.target", "engine index"),
    ([{"kind": "engine_out", "target": -1, "at_s": 1.0}], "failures.target", "engine index"),
    ([{"kind": "engine_out", "target": True, "at_s": 1.0}], "failures.target", "engine index"),
    ([{"kind": "hardover", "target": "rudder", "at_s": -0.5}], "failures.time", "negative"),
    ([{"kind": "hardover", "target": "rudder", "at_s": 11.0}], "failures.time", "beyond"),
    ([{"kind": "hardover", "target": "rudder", "at_s": "soon"}], "failures.time", "number"),
    ([{"kind": "hardover", "target": "rudder", "at_s": float("nan")}], "failures.time", "number"),
    ([{"kind": "float", "target": "aileron", "at_s": 2.0},
      {"kind": "engine_out", "target": 0, "at_s": 1.0}], "failures.time", "time order"),
    ([{"kind": "authority_loss", "target": "elevator", "at_s": 1.0, "value": 1.5}],
     "failures.value", "0..1"),
    ([{"kind": "authority_loss", "target": "elevator", "at_s": 1.0, "value": -0.1}],
     "failures.value", "0..1"),
    ([{"kind": "authority_loss", "target": "elevator", "at_s": 1.0}], "failures.value",
     "remaining authority"),
    ([{"kind": "authority_loss", "target": "elevator", "at_s": 1.0, "value": "half"}],
     "failures.value", "remaining authority"),
    ([{"kind": "control_jam", "target": "elevator", "at_s": 1.0, "value": 0.5}],
     "failures.value", "not read"),
    ("engine_out", "failures.kind", "list of events"),
])
def test_a_schedule_outside_the_build_is_refused_by_name(events, name, fragment):
    found = problems(events, duration_s=10.0)
    assert found and found[0].constraint == name, [str(p) for p in found]
    assert fragment in found[0].message
    with pytest.raises(FailureError) as exc:
        FailureSchedule(events, duration_s=10.0)
    assert exc.value.constraint == name


def test_a_well_formed_schedule_has_no_problems_and_reads_engine_targets():
    events = [{"kind": "engine_out", "target": "engine[1]", "at_s": 0.0},
              {"kind": "authority_loss", "target": "rudder", "at_s": 0.0, "value": 0.0},
              {"kind": "hardover", "target": "aileron", "at_s": 2.5},
              {"kind": "float", "target": "elevator", "at_s": 2.5},
              {"kind": "control_jam", "target": "rudder", "at_s": 10.0}]
    assert problems(events, duration_s=10.0) == []
    schedule = FailureSchedule(events, duration_s=10.0)
    assert [e.target for e in schedule.events] == [1, "rudder", "aileron", "elevator", "rudder"]
    assert schedule.needs_injection and len(schedule) == 5
    assert FailureEvent.from_mapping({"kind": "engine_out", "target": "engine", "at_s": 1}).target == 0
    assert problems([], duration_s=1.0) == [] and not FailureSchedule([]).needs_injection
    assert set(KINDS) == {"engine_out"} | set(SURFACE_KINDS)
    assert event_problems(0, {"kind": "engine_out", "target": 2.0, "at_s": 1.0}, None) == []


def test_the_airframe_facts_refuse_an_absent_engine_and_a_chain_that_cannot_anchor():
    """The validator's half: the stock XML's engine count and P2's own
    anchor test over its text -- the DHC6 (its FCS in a shared system
    file) and the f16 (a command read outside an <input>) refuse the
    failures injection (tests/test_derive_injections.py), so a surface
    failure on them is failures.actuator_missing before any flight."""
    facts = airframe_facts("c172p")
    assert facts["engine_count"] == 1 and facts["failures_anchor_refused"] is None
    assert facts["engine_types"] == ["piston"]
    assert airframe_facts("A320")["engine_count"] == 2
    assert airframe_facts("A320")["engine_types"] == ["turbine", "turbine"]
    # The card resolves a piston's write from the stock engine file before
    # any FDM exists; a turbine's stays the cutoff.
    card = FailureSchedule([{"kind": "engine_out", "target": 0, "at_s": 1.0}], 5.0, "c172p").card_block()
    assert card["events"][0]["property"] == MAGNETO_CMD and card["events"][0]["value"] == 0.0
    card = FailureSchedule([{"kind": "engine_out", "target": 1, "at_s": 1.0}], 5.0, "A320").card_block()
    assert card["events"][0]["property"] == CUTOFF_CMD and card["events"][0]["value"] == 1.0
    assert problems([{"kind": "engine_out", "target": 1, "at_s": 1.0}], 5.0, "c172p")[0].constraint == "failures.target"
    assert problems([{"kind": "engine_out", "target": 1, "at_s": 1.0}], 5.0, "A320") == []
    for aircraft in ("DHC6", "f16"):
        assert airframe_facts(aircraft)["failures_anchor_refused"] is not None
        found = problems([{"kind": "control_jam", "target": "elevator", "at_s": 1.0}], 5.0, aircraft)
        assert found and found[0].constraint == "failures.actuator_missing"
        assert problems([{"kind": "engine_out", "target": 0, "at_s": 1.0}], 5.0, aircraft) == []


# -- the mechanics on the fake ------------------------------------------------------------

def run_fake(fdm, events, steps):
    schedule = FailureSchedule(events)
    schedule.bind(fdm)
    fdm.hooks.append(schedule.apply)
    for _ in range(steps):
        fdm.step()
    return schedule


def test_v15_the_write_lands_at_the_first_step_at_or_past_the_stated_time():
    """The run clock starts at the first step (JSBSim's own clock does
    not: 4.875 s after a c172p engine start), an event at 0 s lands on
    the FIRST step (t >= at_s, not t > at_s), an event at 1 s lands
    within one step of it, and each is read back on the following
    step."""
    fdm = FakeFDM({**surface_values("elevator"), **surface_values("rudder")}, t0=4.875)
    schedule = run_fake(fdm, [{"kind": "control_jam", "target": "rudder", "at_s": 0.0},
                              {"kind": "hardover", "target": "elevator", "at_s": 1.0}], 130)
    applied = schedule.applied
    assert [list(a) for a in applied] == [list(APPLIED_KEYS)] * 2
    assert applied[0]["t_applied_s"] == 0.0 and applied[0]["agrees"] is True
    assert applied[0]["readback"] == 1.0 and applied[0]["written"] == 1.0
    lag = applied[1]["t_applied_s"] - 1.0
    assert 0.0 <= lag < DT, lag
    assert fdm.props.log[0] == ("failure/rudder/actuator/malfunction/fail_stuck", 1.0)
    record = {r.name: r for r in schedule.applied_variables()}
    hard = record["failures.hardover[1]"].parameters
    assert hard["within_one_step"] is True
    assert hard["step_applied"] == 120 and hard["sim_time_applied_s"] == pytest.approx(4.875 + 120 * DT)
    assert hard["run_clock_zero_sim_time_s"] == 4.875
    assert schedule.report()["applied_count"] == 2 and schedule.steps == 130


def test_an_event_beyond_the_steps_flown_is_never_applied_and_says_so():
    fdm = FakeFDM(surface_values("elevator"))
    schedule = run_fake(fdm, [{"kind": "float", "target": "elevator", "at_s": 5.0}], 10)
    assert schedule.applied == [] and not schedule.any_applied
    assert fdm.props.log == []
    record = {r.name: r for r in schedule.applied_variables()}["failures.float[0]"]
    assert record.readback is None and record.parameters["applied"] is False
    assert record.null_test is None                       # nothing measured, nothing claimed
    assert record.to_dict()["null_test"] is None


def test_the_readback_grades_the_property_store_not_the_intent():
    """A store that drops the write (the fake's ``deaf`` list) reads back
    0 for a 1 written: agrees is False on the applied entry and on the
    record's readback."""
    fdm = FakeFDM(surface_values("elevator"),
                  deaf=("failure/elevator/actuator/malfunction/fail_stuck",))
    schedule = run_fake(fdm, [{"kind": "control_jam", "target": "elevator", "at_s": 0.0}], 3)
    entry = schedule.applied[0]
    assert entry["readback"] == 0.0 and entry["written"] == 1.0 and entry["agrees"] is False
    record = {r.name: r for r in schedule.applied_variables()}["failures.control_jam[0]"]
    assert record.readback is not None and record.readback.agrees is False
    assert record.readback.tolerance == 0.0


def test_a_surface_failure_needs_the_injected_chain_and_an_engine_must_exist():
    stock = FakeFDM({"fcs/elevator-cmd-norm": 0.0, "fcs/elevator-pos-rad": 0.0, **turbine_values()})
    with pytest.raises(FailureError) as exc:
        FailureSchedule([{"kind": "hardover", "target": "elevator", "at_s": 0.0}]).bind(stock)
    assert exc.value.constraint == "failures.actuator_missing"
    with pytest.raises(FailureError) as exc:
        FailureSchedule([{"kind": "engine_out", "target": 1, "at_s": 0.0}]).bind(stock)
    assert exc.value.constraint == "failures.target"
    odd = FakeFDM({"propulsion/engine/set-running": 1.0, "propulsion/engine/thrust-lbs": 1.0})
    with pytest.raises(FailureError) as exc:
        FailureSchedule([{"kind": "engine_out", "target": 0, "at_s": 0.0}]).bind(odd)
    assert exc.value.constraint == "failures.target" and "neither" in exc.value.message
    unbound = FailureSchedule([{"kind": "engine_out", "target": 0, "at_s": 0.0}])
    with pytest.raises(FailureError) as exc:
        unbound.apply(stock)
    assert exc.value.constraint == "failures.actuator_missing"
    with pytest.raises(ValueError):
        unbound.applied_variables()


def test_the_turbine_write_brackets_the_cutoff_with_the_active_engine_and_restores_it():
    fdm = FakeFDM(turbine_values())
    schedule = run_fake(fdm, [{"kind": "engine_out", "target": 0, "at_s": 0.0}], 2)
    assert fdm.props.log[:3] == [(ACTIVE_ENGINE, 0.0), (CUTOFF_CMD, 1.0), (ACTIVE_ENGINE, -1.0)]
    # The readback re-selects the engine to read its own cutoff, then restores.
    assert fdm.props.log[3:] == [(ACTIVE_ENGINE, 0.0), (ACTIVE_ENGINE, -1.0)]
    assert fdm.props.values[ACTIVE_ENGINE] == -1.0
    entry = schedule.applied[0]
    assert entry["property"] == CUTOFF_CMD and entry["agrees"] is True
    assert schedule.card_block() == {"events": [{"kind": "engine_out", "target": 0, "at_s": 0.0,
                                                 "property": CUTOFF_CMD, "value": 1.0}],
                                     "count": 1}
    piston = FakeFDM({"propulsion/engine/set-running": 1.0, "propulsion/engine/thrust-lbs": 200.0,
                      "propulsion/engine/engine-rpm": 2300.0, MAGNETO_CMD: 3.0, ACTIVE_ENGINE: -1.0})
    schedule = run_fake(piston, [{"kind": "engine_out", "target": "engine", "at_s": 0.0}], 1)
    assert piston.props.log == [(ACTIVE_ENGINE, 0.0), (MAGNETO_CMD, 0.0), (ACTIVE_ENGINE, -1.0)]
    assert schedule.applied[0]["property"] == engine_property(0, "set-running")


def test_hold_check_grades_the_worst_drift_against_the_tolerance():
    ok = hold_check([0.1, 0.1, 0.1], 0.1, 0.0, JAM_HOLD_TOLERANCE_RAD, "q")
    assert ok["ok"] is True and ok["steps"] == 3 and ok["max_abs_drift"] == 0.0
    bad = hold_check([0.1, 0.10001], 0.1, 1e-5, JAM_HOLD_TOLERANCE_RAD, "q")
    assert bad["ok"] is False and bad["max_abs_drift"] == 1e-5 and bad["tolerance"] == 1e-6
    none = hold_check([], 0.1, None, JAM_HOLD_TOLERANCE_RAD, "q")
    assert none["ok"] is None and none["max_abs_drift"] is None
    assert JAM_HOLD_TOLERANCE_RAD == 1e-6 and JAM_HOLD_STEPS == 100
    assert AUTHORITY_HOLD_TOLERANCE == 1e-9


def test_the_card_block_keys_are_fixed_and_the_count_exact():
    events = [{"kind": "authority_loss", "target": "elevator", "at_s": 1.0, "value": 0.25},
              {"kind": "control_jam", "target": "rudder", "at_s": 2.0}]
    block = FailureSchedule(events).card_block()
    assert tuple(block) == CARD_KEYS and block["count"] == 2
    assert all(tuple(e) == CARD_EVENT_KEYS for e in block["events"])
    assert block["events"][0]["property"] == "failure/elevator/authority"
    assert block["events"][0]["value"] == 0.25
    assert block["events"][1]["property"] == "failure/rudder/actuator/malfunction/fail_stuck"
    assert block["events"][1]["value"] == 1.0
    assert json.dumps(block).isascii()


def test_failure_injections_for_selects_the_chain_only_when_a_surface_fails():
    def spec(events, hold):
        return SimpleNamespace(failures=SimpleNamespace(events=SimpleNamespace(value=events)),
                               hold_state=SimpleNamespace(value=hold))
    assert failure_injections_for(spec([], False)) == ()
    assert failure_injections_for(spec([{"kind": "engine_out", "target": 0, "at_s": 1.0}], True)) == ()
    assert failure_injections_for(spec([{"kind": "float", "target": "aileron", "at_s": 1.0}], False)) == ("failures",)
    assert failure_injections_for(spec([{"kind": "control_jam", "target": "aileron", "at_s": 1.0}], True)) == ("tecs", "failures")
    assert failure_injections_for(SimpleNamespace(hold_state=SimpleNamespace(value=True))) == ()


# -- the real thing --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def build(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("build") / "aircraft"


def trimmed(fdm, altitude_m, cas_kt):
    with contextlib.redirect_stdout(io.StringIO()):
        fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, **LEVEL})
        fdm.start_engines()
        fdm.trim(TrimMode.LONGITUDINAL)
        fdm.hold_mass(True)
    return fdm


def c172p(build, injections=("failures",)):
    with contextlib.redirect_stdout(io.StringIO()):
        fdm = (FlightDynamics.with_injections("c172p", injections, build_dir=build)
               if injections else FlightDynamics("c172p"))
    return trimmed(fdm, 1500.0, 100.0)


def a320(build, injections=()):
    with contextlib.redirect_stdout(io.StringIO()):
        fdm = (FlightDynamics.with_injections("A320", injections, build_dir=build)
               if injections else FlightDynamics("A320"))
    return trimmed(fdm, 1500.0, 250.0)


def fly(fdm, events, seconds, autopilot=False):
    """The runner's shape: the schedule bound after the trim, applied
    through the FDM's step hook, the recorder sampling after each step."""
    schedule = FailureSchedule(events)
    schedule.bind(fdm)
    fdm.register_step_hook(schedule.apply)
    pilot = None
    if autopilot:
        with contextlib.redirect_stdout(io.StringIO()):
            pilot = Autopilot(fdm)
            pilot.engage()
    recorder = Recorder(fdm, interval_s=0.1, extra={**SURFACE_EXTRAS, **schedule.recorder_extras()})
    recorder.sample(force=True)
    steps = int(round(seconds * fdm.rate_hz))
    every = max(1, int(round(0.5 * fdm.rate_hz)))
    for i in range(steps):
        fdm.step()
        if pilot is not None and i % every == 0:
            pilot.update()
        recorder.sample()
    return schedule, recorder


@pytest.mark.timeout(300)
def test_v15_hardover_and_jam_on_the_c172p_land_read_back_and_hold(build):
    """Measured on the c172p at 1500 m / 100 kt (120 Hz): the rudder jam
    at 0 s lands on the first step and holds the rudder within 0.0 rad
    over 100 steps; the elevator hardover at 1 s lands within one step,
    reads back 1.0, and moves the elevator from the trim-only position
    0.0751561 rad to the +23 deg stop 0.40135 rad on the next step."""
    fdm = c172p(build)
    schedule, recorder = fly(fdm, [{"kind": "control_jam", "target": "rudder", "at_s": 0.0},
                                   {"kind": "hardover", "target": "elevator", "at_s": 1.0}], 2.0)
    jam, hard = schedule.applied
    assert jam["t_applied_s"] == 0.0 and jam["agrees"] is True and jam["readback"] == 1.0
    assert 0.0 <= hard["t_applied_s"] - 1.0 < fdm.dt
    assert hard["agrees"] is True and hard["readback"] == 1.0
    records = {r.name: r for r in schedule.applied_variables(recorder)}
    assert set(records) == {"failures.control_jam[0]", "failures.hardover[1]", "failures.events"}
    hold = records["failures.control_jam[0]"].parameters["hold"]
    assert hold["steps"] == JAM_HOLD_STEPS and hold["max_abs_drift"] == 0.0 and hold["ok"] is True
    assert records["failures.control_jam[0]"].null_test.kind == "bounded"
    assert records["failures.control_jam[0]"].null_test.ok
    hardover = records["failures.hardover[1]"]
    assert hardover.parameters["before"]["position_rad"] == pytest.approx(0.07515610487503992, abs=1e-12)
    assert hardover.parameters["after"]["position_rad"] == pytest.approx(0.40135, abs=1e-12)
    assert hardover.null_test.ok and hardover.null_test.kind == "reached"
    assert hardover.readback.agrees and hardover.readback.property.endswith("fail_hardover")
    assert set(hardover.properties_written) == {"failure/elevator/actuator/malfunction/fail_hardover"}
    # The flag column: 0 until the first application, 1 from then on
    # (the rudder jam at 0 s is applied inside the first step).
    flag = recorder.columns[FLAG_COLUMN]
    assert flag[0] == 0.0 and set(flag[1:]) == {1.0}
    events = records["failures.events"]
    assert events.value == [e.to_dict() for e in schedule.events]
    assert events.readback.agrees and events.null_test.ok
    assert events.telemetry_columns == (FLAG_COLUMN, "engine0_thrust_n", "engine0_rpm")
    # Every record is a valid record-2 AppliedVariable with a model block.
    for record in records.values():
        assert isinstance(record, AppliedVariable) and record.model is not None
        assert record.null_test is not None and record.not_claimed
        AppliedVariable.from_dict(record.to_dict())


@pytest.mark.timeout(300)
def test_authority_half_through_the_schedule_holds_half_the_command_on_100_steps(build):
    """P2's measurement re-made through the schedule: -0.3 written once
    before, authority 0.5 at 1 s -> the actuator writes -0.15 on the
    following step and on every one of the next 100 (drift 0.0), the
    elevator sits at 0.0149536 rad."""
    fdm = c172p(build)
    fdm.set_controls(elevator=-0.3)
    schedule, recorder = fly(fdm, [{"kind": "authority_loss", "target": "elevator", "at_s": 1.0,
                                    "value": 0.5}], 2.0)
    record = {r.name: r for r in schedule.applied_variables(recorder)}["failures.authority_loss[0]"]
    p = record.parameters
    assert p["before"]["cmd_in"] == -0.3 and p["after"]["cmd_in"] == -0.15
    assert p["after"]["position_rad"] == pytest.approx(0.01495360487503992, abs=1e-12)
    assert p["hold"]["steps"] == 100 and p["hold"]["max_abs_drift"] == 0.0 and p["hold"]["ok"]
    assert record.null_test.ok and record.value == 0.5 and record.readback.value == 0.5
    assert fdm.props.get("failure/elevator/cmd-in") == -0.15


@pytest.mark.timeout(300)
def test_a_float_writes_zero_and_a_zero_command_is_honestly_silent(build):
    fdm = c172p(build)
    fdm.set_controls(elevator=-0.3)
    schedule, recorder = fly(fdm, [{"kind": "float", "target": "elevator", "at_s": 0.5},
                                   {"kind": "float", "target": "aileron", "at_s": 0.5}], 1.0)
    records = {r.name: r for r in schedule.applied_variables(recorder)}
    elevator = records["failures.float[0]"].parameters
    assert elevator["before"]["cmd_in"] == -0.3 and elevator["after"]["cmd_in"] == 0.0
    assert elevator["after"]["position_rad"] == pytest.approx(0.07515610487503992, abs=1e-12)
    assert records["failures.float[0]"].null_test.ok
    aileron = records["failures.float[1]"]
    assert aileron.parameters["before"]["command"] == 0.0
    assert not aileron.null_test.ok            # nothing to float: 0 -> 0, said so
    assert aileron.readback.agrees


@pytest.mark.timeout(300)
def test_engine_out_on_the_a320_turbine_is_zero_thrust_from_the_next_step_and_stays(build):
    """The engine-out thrust check: cutoff at 1 s, thrust 11943 lbf ->
    0.0 on the next step and on every one of the following 5 s, N1
    83.66 -> below 25 % at 5 s, engine 1 untouched; set-running reads 0;
    the active engine is restored to -1."""
    fdm = a320(build)
    schedule, recorder = fly(fdm, [{"kind": "engine_out", "target": 0, "at_s": 1.0}], 6.0)
    record = {r.name: r for r in schedule.applied_variables(recorder)}["failures.engine_out[0]"]
    p = record.parameters
    assert p["engine_type"] == "turbine" and 0.0 <= p["t_applied_s"] - 1.0 < fdm.dt
    assert p["before"]["thrust_lbf"] == pytest.approx(11943.05, abs=0.5)
    assert p["after"]["thrust_lbf"] == 0.0 and p["after"]["set_running"] == 0.0
    assert record.readback.property == CUTOFF_CMD and record.readback.agrees
    assert record.null_test.ok and record.null_test.with_value == 0.0
    assert record.null_test.without_value == pytest.approx(u.lbf_to_n(11943.05), abs=3.0)
    assert fdm.props.get("propulsion/engine/thrust-lbs") == 0.0
    assert fdm.props.get("propulsion/engine/n1") < 25.0 and p["before"]["n1_pct"] > 83.0
    assert fdm.props.get("propulsion/engine[1]/thrust-lbs") > 11900.0
    assert fdm.props.get(ACTIVE_ENGINE) == -1.0
    assert set(record.properties_written) == {ACTIVE_ENGINE, CUTOFF_CMD}
    assert "engine0_thrust_n" in record.telemetry_columns and "engine0_n1_pct" in record.telemetry_columns
    # Thrust stayed at 0 on every recorded sample after the write: the
    # schedule's own engine columns (thrust in N, N1 in %; the A320 has
    # no rpm column and no NaN anywhere).
    assert schedule.engine_columns_recorded == ("engine0_thrust_n", "engine0_n1_pct",
                                                "engine1_thrust_n", "engine1_n1_pct")
    t0 = recorder.columns["t"][0]
    after = [i for i, t in enumerate(recorder.columns["t"]) if t - t0 > 1.05]
    assert len(after) >= 45
    assert {recorder.columns["engine0_thrust_n"][i] for i in after} == {0.0}
    assert min(recorder.columns["engine1_thrust_n"][i] for i in after) > u.lbf_to_n(11900.0)
    assert recorder.columns["engine0_thrust_n"][0] > u.lbf_to_n(11900.0)
    assert recorder.columns["engine0_n1_pct"][-1] < 25.0 < 80.0 < recorder.columns["engine1_n1_pct"][-1]
    assert "engine0_rpm" not in recorder.columns
    # The R2 measured channels are NaN when no instruments are stated (not
    # measured); every other column is finite.
    assert all(math.isfinite(v) for name, c in recorder.columns.items()
               if not name.startswith("meas_") for v in c)
    assert all(math.isnan(v) for name, c in recorder.columns.items()
               if name.startswith("meas_") for v in c)


@pytest.mark.timeout(300)
def test_a_bare_set_running_zero_relights_a_turbine_in_flight_so_it_is_not_the_write(build):
    """The blueprint's ``set-running = 0``, measured: thrust 0 on the
    next step only; FGTurbine::Calculate L146-L147 enters tpStart while
    Cutoff is false and qbar > 30, and Start() L292-L309 relights the
    engine with N2 above idle -- 11942.99 lbf again on the second step."""
    fdm = a320(build)
    fdm.run_for(1.0)
    fdm.props.set("propulsion/engine/set-running", 0.0)
    fdm.step()
    first = fdm.props.get("propulsion/engine/thrust-lbs")
    fdm.step()
    second = fdm.props.get("propulsion/engine/thrust-lbs")
    assert first == 0.0 and second > 11900.0
    assert fdm.props.get("propulsion/engine/set-running") == 1.0


@pytest.mark.timeout(300)
def test_engine_out_on_the_c172p_piston_dies_off_over_seconds_and_a_bare_set_running_is_undone(build):
    """Magnetos off at 1 s: set-running reads 0 on the next step, the
    thrust is still 226.7 lbf there (the propeller's inertia), crosses
    zero within 2 s (measured 1.68 s) and the rpm is below 750 after
    7 s (2300 -> windmilling ~700). A bare set-running 0 reads 1.0 on
    the next step: FGPiston L595-L598 relatches Running while the
    propeller windmills above 0.8 x idle."""
    fdm = c172p(build, injections=())
    schedule, recorder = fly(fdm, [{"kind": "engine_out", "target": 0, "at_s": 1.0}], 8.0)
    record = {r.name: r for r in schedule.applied_variables(recorder)}["failures.engine_out[0]"]
    p = record.parameters
    assert p["engine_type"] == "piston" and p["property"] == "propulsion/engine/set-running"
    assert p["after"]["set_running"] == 0.0 and record.readback.agrees
    assert p["before"]["thrust_lbf"] == pytest.approx(226.7, abs=0.5)
    assert p["after"]["thrust_lbf"] == pytest.approx(226.7, abs=0.5)       # not yet: inertia
    assert p["settled"]["thrust_lbf"] < 0.0                                   # at PISTON_SETTLE_S
    assert PISTON_SETTLE_S == 2.0 and record.null_test.ok
    assert fdm.props.get("propulsion/engine/engine-rpm") < 750.0 and p["before"]["rpm"] > 2290.0
    assert set(record.properties_written) == {ACTIVE_ENGINE, MAGNETO_CMD}
    assert record.telemetry_columns == (FLAG_COLUMN, "engine0_thrust_n", "engine0_rpm",
                                        "altitude_m", "tas_kt", "heading_deg")
    assert schedule.engine_columns_recorded == ("engine0_thrust_n", "engine0_rpm")
    rpm = recorder.columns["engine0_rpm"]
    assert rpm[0] > 2290.0 and rpm[-1] < 750.0 and "engine1_thrust_n" not in recorder.columns
    thrust = recorder.columns["engine0_thrust_n"]
    assert thrust[0] > 1000.0 and thrust[-1] < 0.0
    stock = c172p(build, injections=())
    stock.props.set("propulsion/engine/set-running", 0.0)
    stock.step()
    assert stock.props.get("propulsion/engine/set-running") == 1.0


@pytest.mark.timeout(300)
def test_a_jam_under_tecs_holds_the_elevator_while_the_controller_moves_the_command(build):
    """The A320 with TECS and the failure chain: the elevator jams at
    1 s and holds within 0.0 rad over the 100 steps that follow while
    TECS keeps writing a moving command (the command differs across
    those steps). The c172p cannot fly this here: the sign probe trims
    at 6000 m / 280 kt, which the c172p refuses (measured TrimError)."""
    fdm = a320(build, injections=("tecs", "failures"))
    assert fdm.derived.name == "A320-tecs-fail"
    schedule = FailureSchedule([{"kind": "control_jam", "target": "elevator", "at_s": 1.0}])
    schedule.bind(fdm)
    fdm.register_step_hook(schedule.apply)
    with contextlib.redirect_stdout(io.StringIO()):
        pilot = Autopilot(fdm)
        pilot.engage()
    commands, positions = [], []
    for i in range(int(2.0 * fdm.rate_hz)):
        fdm.step()
        if i % 60 == 0:
            pilot.update()
        if schedule.any_applied:
            commands.append(fdm.props.get("fcs/elevator-cmd-norm"))
            positions.append(fdm.props.get("fcs/elevator-pos-rad"))
    hold = schedule.hold_result(0)
    assert hold["steps"] == 100 and hold["max_abs_drift"] == 0.0 and hold["ok"] is True
    assert max(positions) - min(positions) == 0.0
    assert max(commands) - min(commands) > 0.0          # the controller moved the command
    assert schedule.applied[0]["agrees"] is True


def test_a_stock_airframe_refuses_a_surface_failure_by_name_at_bind(build):
    fdm = c172p(build, injections=())
    with pytest.raises(FailureError) as exc:
        FailureSchedule([{"kind": "control_jam", "target": "elevator", "at_s": 1.0}]).bind(fdm)
    assert exc.value.constraint == "failures.actuator_missing"
    assert "with_injections" in exc.value.message
    with pytest.raises(FailureError) as exc:
        FailureSchedule([{"kind": "engine_out", "target": 1, "at_s": 1.0}]).bind(fdm)
    assert exc.value.constraint == "failures.target"


def test_the_step_hook_runs_once_per_step_in_registration_order(build):
    fdm = c172p(build, injections=())
    calls = []
    fdm.register_step_hook(lambda f: calls.append(("a", f.sim_time)))
    fdm.register_step_hook(lambda f: calls.append(("b", f.sim_time)))
    assert len(fdm.step_hooks) == 2
    steps = fdm.run_for(0.1)
    assert steps == 12 and len(calls) == 24
    assert [c[0] for c in calls[:2]] == ["a", "b"]
    assert calls[0][1] == calls[1][1]                    # both see the pre-step clock
    assert calls[2][1] > calls[0][1]
    with pytest.raises(TypeError):
        fdm.register_step_hook("not callable")


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    source = (REPO / "core/telemetry/failures.py").read_text(encoding="utf-8")
    assert source.isascii()
    fdm = FakeFDM({**surface_values("elevator"), **turbine_values()})
    schedule = run_fake(fdm, [{"kind": "engine_out", "target": 0, "at_s": 0.0},
                              {"kind": "authority_loss", "target": "elevator", "at_s": 0.0,
                               "value": 0.5}], 3)
    assert json.dumps(schedule.card_block()).isascii()
    assert json.dumps(schedule.report()).isascii()
    for record in schedule.applied_variables():
        assert json.dumps(record.to_dict()).isascii()
    assert SURFACES == ("elevator", "aileron", "rudder")
