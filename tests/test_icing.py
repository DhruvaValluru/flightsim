"""P5, the icing provider and the icing block: the severity ramp driving
P2's six injected axis factors and the stall-onset cue, written every
step and read back before the next write; the k-table per airframe; the
records; the card block; the null pairs.

Every number asserted here was measured in this container on
2026-09-29 against JSBSim 1.2.4 in .venv (120 Hz). The c172p carries the
DHC6 (Twin Otter) k-table as a NAMED PROXY; the DHC6 IS the Twin Otter
and is flown here too, through a stand-in for the derive patch this item
returns (the stock DHC6 keeps its engine, propeller and system files in
aircraft-local subdirectories, which core/control/derive.py does not copy,
so the derived DHC6 refuses to load at HEAD: "Could not open file:
Propeller", measured; the fixture copies them into the build directory
exactly as the patch makes derive do).

Measured: the trimmed c172p's lift on the first step after the provider
writes eta 0.2 is 0.982 x the un-iced first step (1872.5287 -> 1838.8232
lbf, 1.1e-16 relative: the whole LIFT axis scales, P2's form); the DHC6's
the same (10078.629 -> 9897.214 lbf); every one of the eight properties
reads back 0.0 from the value written on every one of 359 checked steps;
the pairs 0.2 against 0 diverge the trimmed flight (c172p 3 s: lift 100.4
N, pitch 0.134 deg, TAS 0.40 kt reached, altitude 0.25 m below the floor;
10 s: altitude 3.86 m, pitch 0.79 deg; DHC6 3 s: altitude 0.61 m, pitch
0.31 deg, TAS 0.24 kt; 10 s: altitude 6.80 m, pitch 1.08 deg); the alpha
shift of 2 deg at eta 0.2 moves the static lift peak -2.0 deg (P2's
sweep, through the provider's writes) and the flight by 17.7 m; a stated
eta 0 keeps every recorded column within 4.0e-10 of the stock run (the
five pre-trim re-latches; not bit-identical, said so); the committed
spec-8 examples keep their digests.

What is NOT claimed: any airframe's icing response (the k-table is a
transcription from memory, marked [unverified here]; the c172p's a
proxy); the factor form scales whole tables; no accretion, LWC / MVD or
temperature dependence; the envelope words are metadata; the engine side
(the card block is pinned, nothing applies it here).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import io
import json
import math
import shutil
from pathlib import Path

import pytest
import yaml

from core.capture.manifest import state_units
from core.control.derive import derive
from core.fdm import FlightDynamics
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.record_null import null_pairs_for_spec, run_null_pair
from core.records import read_records
from core.registry import NO_NULL, REGISTRY
from core.scenario.blocks import ICING_SEVERITY_WORDS, ICING_STANDARDS, IcingSpec
from core.scenario.card import icing_schedule_card_block, write_run_card
from core.scenario.fields import Source
from core.scenario.runner import configure_from_spec, fdm_at_initial_conditions, run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_icing
from core.environment import icing as ic
from core.environment.icing import (
    AXES, CARD_KEYS, ENVELOPE_WORDS, INJECTIONS, K_KEYS, PROPERTIES, PROPERTY_ETA,
    PROPERTY_SHIFT, SEVERITY_WORDS, TELEMETRY_COLUMNS, IcingError, IcingProvider, eta_at,
    icing_injections_for, load_k_table, parse_icing_config, problems, require_k_table,
)
from core.telemetry.recorder import DEFAULT_CHANNELS

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
#: The committed examples' digests, re-pinned at spec 9 (INT-final;
#: tests/test_registry.py pins the same eight): the block adds no key to a
#: spec that states none.
EXAMPLE_DIGESTS = {
    "examples/cameras_event_trigger.yaml": "cecfcf1a5882d34fd97bdd7cbdbc6a69710d9c7956f835a897fbf1c712ab2ccf",
    "examples/cameras_hazard_refusal.yaml": "bcd32ebe8fed244be2bd8f6761a879b3bbe965c6d3c884fbc65b3deb2b12e9ea",
    "examples/cameras_mountain_refusal.yaml": "d49cbc463d0f402ef39d95b86325d97d6fdfa4fb89ea414ab47e066b949cfe6c",
    "examples/cameras_multi.yaml": "995ec65631ba52092140458c7799eb3c7a6b82a9baa1807f9c017724ae4c5390",
    "examples/cameras_refusal.yaml": "04d38d5b97052b61181530e544df1cb56c3b6037e85e7ffd1ee0e663d398c055",
    "examples/cameras_terrain.yaml": "e57b408868065d75c99ca3711627601c199b43c3d50dd2675ac6e2b1c20b1325",
    "examples/cameras_waypoint.yaml": "aba90b44eae4644a139cf65d8f593cdadd9b78cc320c15f9642d79fb4fee2f00",
    "examples/randomized.yaml": "bc9982ba15a79c63a1c748eacb70efddc753c174532e80735019b48904309428",
}
#: The DHC6 row as configured (a transcription from memory of the Twin
#: Otter set, [unverified here]); the c172p carries the same numbers as a
#: named proxy.
DHC6_K = {"lift": -0.09, "drag": 0.34, "pitch": -0.20, "roll": -0.10, "yaw": -0.10, "side": -0.20}
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
ALT_M, CAS_KT = 1500.0, 100.0


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def spec_for(seconds=3, aircraft="c172p", altitude_m=1500.0, cas_kt=100.0, hold_state=False,
             **icing) -> ScenarioSpec:
    """A compiled spec with the icing fields stated through the spec's
    own front door (hold_state False: the autopilot's sign probe trims
    every airframe at 6000 m / 280 kt, outside the c172p's envelope)."""
    spec = compile_prompt(f"fly the {aircraft} at {altitude_m:g} m and {cas_kt:g} kt for "
                          f"{seconds} seconds")
    spec.set("hold_state", hold_state, frm="test")
    for name, value in icing.items():
        spec.set(f"icing.{name}", value, frm="test")
    return spec


def dhc6_spec(seconds=3, **icing) -> ScenarioSpec:
    """The DHC6 at 1500 m / 120 kt (the prompt compiler does not map it),
    from a committed example with the airframe set by hand."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_waypoint.yaml")
    spec.set("aircraft", "DHC6", frm="test")
    spec.set("altitude", 1500.0, frm="test")
    spec.set("airspeed", 120.0, frm="test")
    spec.set("hold_state", False, frm="test")
    spec.set("duration", float(seconds), frm="test")
    for name, value in icing.items():
        spec.set(f"icing.{name}", value, frm="test")
    return spec


def names(violations):
    return [v.constraint for v in violations]


def constraints(**icing):
    return names(validate_icing(spec_for(**icing)))


def icing_records(run):
    return {r["name"]: r for r in read_records(run.manifest["applied_variables"])
            if r["name"].startswith("icing.")}


def effects(pair):
    return {e.channel: e for e in pair.effects}


# -- the vocabulary, the ramp, the factor form ----------------------------------------

def test_the_severity_words_are_the_stated_mapping_and_the_envelope_words_are_metadata():
    assert SEVERITY_WORDS is ICING_SEVERITY_WORDS
    assert SEVERITY_WORDS == {"trace": 0.05, "light": 0.10, "moderate": 0.20, "severe": 0.30}
    assert "pilot" in ICING_STANDARDS["severity"] or "pilot-report" in ICING_STANDARDS["severity"]
    assert ENVELOPE_WORDS == ("appendix_c", "appendix_o")
    assert "applied nowhere" in ICING_STANDARDS["envelope"]
    block = IcingSpec.defaulted()
    assert block.is_default() and block.resolved()["eta_max"].value == 0.0
    block.set("severity", "moderate", frm="test")
    resolved = block.resolved()["eta_max"]
    assert resolved.value == 0.20 and resolved.source is Source.INFERRED
    assert resolved.frm == "severity: moderate"
    block.set("eta_max", 0.15, frm="test")          # a stated number wins over the word
    assert block.resolved()["eta_max"].value == 0.15
    assert block.resolved()["eta_max"].source is Source.USER


def test_the_eta_ramp_is_clamped_to_0_and_eta_max_and_a_zero_ramp_is_a_step():
    assert eta_at(-1.0, 0.2, 0.0, 2.0) == 0.0
    assert eta_at(0.0, 0.2, 0.0, 2.0) == 0.0
    assert eta_at(1.0, 0.2, 0.0, 2.0) == pytest.approx(0.1)
    assert eta_at(2.0, 0.2, 0.0, 2.0) == 0.2
    assert eta_at(100.0, 0.2, 0.0, 2.0) == 0.2            # clamped: never past eta_max
    assert eta_at(3.5, 0.2, 3.0, 1.0) == pytest.approx(0.1)
    assert eta_at(0.999, 0.2, 1.0, 0.0) == 0.0 and eta_at(1.0, 0.2, 1.0, 0.0) == 0.2
    assert eta_at(50.0, 0.3, 1.0, 0.0) == 0.3
    assert eta_at(5.0, 0.0, 0.0, 0.0) == 0.0


def test_the_factor_form_is_one_plus_eta_k_per_axis_and_the_dhc6_row_is_configured():
    table = load_k_table("DHC6")
    assert table is not None and not table.proxy and table.proxy_of is None
    assert table.values == DHC6_K
    assert all("unverified here" in table.sources[axis] for axis in AXES)
    assert "unverified here" in table.source and "2000-0360" in table.source
    assert table.factors(0.2) == {"lift": pytest.approx(0.982), "drag": pytest.approx(1.068),
                                  "pitch": pytest.approx(0.96), "roll": pytest.approx(0.98),
                                  "yaw": pytest.approx(0.98), "side": pytest.approx(0.96)}
    assert table.factors(0.0) == {axis: 1.0 for axis in AXES}
    assert table.factors(1.0)["drag"] == pytest.approx(1.34)
    assert table.config_path == "assets/aircraft_config/DHC6.json"
    raw = (REPO / "assets/aircraft_config/DHC6.json").read_bytes()
    assert table.config_sha256 == hashlib.sha256(raw).hexdigest()
    c172p = load_k_table("c172p")
    assert c172p.proxy is True and c172p.proxy_of == "DHC6" and c172p.values == DHC6_K
    assert c172p.source.startswith("PROXY")
    for name in ("A320", "B747", "p51d"):
        assert load_k_table(name) is None, name
        with pytest.raises(IcingError) as exc:
            require_k_table(name)
        assert exc.value.constraint == "icing.airframe_data"
    assert load_k_table("nothing_of_the_kind") is None


def test_a_malformed_k_table_refuses_airframe_data_by_name():
    good = json.loads((REPO / "assets/aircraft_config/DHC6.json").read_text(encoding="utf-8"))["icing"]
    parse_icing_config("DHC6", good)
    bad = [
        "not a mapping",
        {**good, "extra": 1},
        {**good, "source": ""},
        {**good, "proxy": "yes"},
        {**good, "proxy": True},                                        # no proxy_of
        {**good, "proxy_of": "DHC6"},                                   # not a proxy, names one
        {**good, "k_table": {k: v for k, v in good["k_table"].items() if k != "k_side"}},
        {**good, "k_table": {**good["k_table"], "k_side": {"value": "x", "source": "s"}}},
        {**good, "k_table": {**good["k_table"], "k_side": {"value": 0.1, "source": ""}}},
        {**good, "k_table": {**good["k_table"], "k_side": {"value": float("nan"), "source": "s"}}},
    ]
    for block in bad:
        with pytest.raises(IcingError) as exc:
            parse_icing_config("DHC6", block)
        assert exc.value.constraint == "icing.airframe_data"


def test_the_alpha_shift_is_a_linear_cue_in_eta_and_the_writes_cover_the_eight_properties():
    provider = IcingProvider.from_spec(spec_for(eta_max=0.2, alpha_shift_deg=2.0, ramp_s=2.0))
    assert provider.shift_rad_at(0.2) == pytest.approx(math.radians(2.0))
    assert provider.shift_rad_at(0.1) == pytest.approx(math.radians(1.0))
    assert provider.shift_rad_at(0.0) == 0.0
    writes = provider.writes_at(1.0)
    assert tuple(writes) == PROPERTIES and len(PROPERTIES) == 8
    assert writes[PROPERTY_ETA] == pytest.approx(0.1)
    assert writes["icing/lift-factor"] == pytest.approx(1.0 - 0.1 * 0.09)
    assert writes[PROPERTY_SHIFT] == pytest.approx(math.radians(1.0))
    assert provider.writes_at(-1.0) == provider.neutral_writes()
    clean = IcingProvider.from_spec(spec_for(eta_max=0.0, alpha_shift_deg=2.0))
    assert clean.shift_rad_at(0.0) == 0.0 and clean.writes_at(5.0) == clean.neutral_writes()
    assert IcingProvider.from_spec(spec_for()) is None
    assert icing_injections_for(spec_for()) == () and icing_injections_for(spec_for(severity="trace")) == INJECTIONS
    assert any(t.phrase == "moderate" and t.value == 0.2 for t in provider.vocabulary())
    with pytest.raises(ValueError, match="never called"):
        provider.applied_variables()


# -- the block --------------------------------------------------------------------------

def _canonical_digest(payload) -> str:
    payload = dict(payload)
    payload.pop("prompt", None)
    payload.pop("notes", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("name", sorted(EXAMPLE_DIGESTS))
def test_a_committed_spec_8_example_keeps_its_canonical_form_and_digest(name):
    """Absent is canonical: the block adds no key to a spec that states
    none of it, so every committed example's digest is HEAD's."""
    frozen = yaml.safe_load((REPO / name).read_text(encoding="utf-8"))
    assert "icing" not in frozen
    spec = ScenarioSpec.from_dict(copy.deepcopy(frozen))
    assert spec.icing.is_default()
    assert "icing" not in spec.to_dict()
    assert spec.digest() == _canonical_digest(frozen) == EXAMPLE_DIGESTS[name]


def test_a_stated_block_round_trips_changes_the_digest_and_sits_behind_the_front_door(tmp_path):
    spec = spec_for(severity="light", onset_s=2.0, ramp_s=5.0, envelope="appendix_o")
    assert spec.digest() != spec_for().digest()
    reread = ScenarioSpec.read(spec.write(tmp_path / "s.yaml"))
    assert reread.digest() == spec.digest()
    assert reread.icing.severity.value == "light" and reread.icing.severity.source is Source.USER
    assert list(reread.to_dict()["icing"]) == list(IcingSpec.FIELD_ORDER) == [
        "severity", "eta_max", "onset_s", "ramp_s", "alpha_shift_deg", "envelope"]
    assert reread.icing.eta_max.value is None and reread.icing.eta_max.std == ICING_STANDARDS["eta_max"]
    assert reread.icing.resolved()["eta_max"].value == 0.10
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("icing.severity", "severe", frm="planner")
    spec.plan("icing.eta_max", 0.05, frm="planner")
    assert spec.icing.eta_max.source is Source.DERIVED
    with pytest.raises(ValueError, match="not a icing field"):
        spec.set("icing.accretion_mm", 1.0)
    data = spec.to_dict()
    data["icing"]["accretion_mm"] = {"value": 1.0, "source": "user"}
    with pytest.raises(ValueError, match="unknown fields"):
        ScenarioSpec.from_dict(data)
    assert "[icing]" in spec.render_table()


# -- the refusals, by name -----------------------------------------------------------------

def test_refusals_by_name():
    assert constraints(severity="heavy") == ["icing.severity"]
    assert constraints(severity=0.2) == ["icing.severity"]
    assert constraints(eta_max=1.5) == ["icing.eta_range"]
    assert constraints(eta_max=-0.1) == ["icing.eta_range"]
    assert constraints(eta_max="lots") == ["icing.eta_range"]
    assert constraints(eta_max=1.0) == []                       # the closed range's ends
    assert constraints(eta_max=0.0) == []
    assert constraints(eta_max=0.2, onset_s=-1.0) == ["icing.eta_range"]
    assert constraints(eta_max=0.2, ramp_s=-0.5) == ["icing.eta_range"]
    assert constraints(eta_max=0.2, ramp_s="slow") == ["icing.eta_range"]
    assert constraints(eta_max=0.2, alpha_shift_deg=20.0) == ["icing.eta_range"]
    assert constraints(eta_max=0.2, alpha_shift_deg="two") == ["icing.eta_range"]
    assert constraints(eta_max=0.2, alpha_shift_deg=-10.0) == []
    assert constraints(envelope="appendix_x") == ["icing.envelope"]
    assert constraints(envelope="appendix_c") == []
    assert constraints(severity="heavy", eta_max=2.0, envelope="x") == [
        "icing.severity", "icing.eta_range", "icing.envelope"]
    assert constraints() == []                                  # the default block
    assert problems(None, 0.2, 0.0, 0.0, 0.0, None, "A320")[0].constraint == "icing.airframe_data"
    assert problems(None, 0.2, 0.0, 0.0, 0.0, None, "DHC6") == []
    for aircraft, altitude, cas in (("A320", 6000.0, 250.0), ("B747", 6000.0, 280.0)):
        assert names(validate_icing(spec_for(aircraft=aircraft, altitude_m=altitude, cas_kt=cas,
                                             severity="moderate"))) == ["icing.airframe_data"]
        assert names(validate_icing(spec_for(aircraft=aircraft, altitude_m=altitude, cas_kt=cas))) == []
    with pytest.raises(IcingError) as exc:
        IcingProvider.from_spec(spec_for(aircraft="A320", altitude_m=6000.0, cas_kt=250.0, severity="light"))
    assert exc.value.constraint == "icing.airframe_data"
    with pytest.raises(IcingError) as exc:
        IcingProvider.from_spec(spec_for(eta_max=3.0))
    assert exc.value.constraint == "icing.eta_range"
    report = quiet(validate, spec_for(severity="heavy"), check_feasibility=False)
    assert names(report.violations) == ["icing.severity"]
    assert "[icing.severity]" in report.render()
    report = quiet(validate, spec_for(eta_max=0.2, alpha_shift_deg=2.0))
    assert report.ok, report.render()


# -- the runner: the derived airframe, the trim of the un-iced aircraft ----------------------

def test_a_stated_block_flies_the_derived_airframe_and_the_default_block_the_stock_one():
    stock = quiet(fdm_at_initial_conditions, spec_for())
    assert stock.derived is None and not stock.props.has(PROPERTY_ETA)
    iced = quiet(fdm_at_initial_conditions, spec_for(severity="trace"))
    assert iced.derived.name == "c172p-ice-alpha" and iced.derived.suffix == "-ice-alpha"
    assert iced.derived.injection_names == INJECTIONS
    assert all(iced.props.has(p) for p in PROPERTIES)
    held = quiet(fdm_at_initial_conditions, spec_for(severity="trace", hold_state=True))
    assert held.derived.name == "c172p-tecs-ice-alpha"
    jammed = spec_for(severity="trace")
    jammed.set("failures.events", [{"kind": "control_jam", "target": "elevator", "at_s": 1.0}], frm="test")
    assert quiet(fdm_at_initial_conditions, jammed).derived.name == "c172p-fail-ice-alpha"


@pytest.fixture(scope="module")
def iced_run():
    """The demonstration run: c172p, 1500 m / 100 kt, eta 0.2 from the
    first step (the proxy row), 3 s."""
    return quiet(run_spec, spec_for(eta_max=0.2))


@pytest.fixture(scope="module")
def clean_run():
    """The same spec with eta_max 0 STATED: the derived airframe at
    neutral values (the null pair's 'without')."""
    return quiet(run_spec, spec_for(eta_max=0.0))


@pytest.fixture(scope="module")
def stock_run():
    return quiet(run_spec, spec_for())


def test_the_trim_is_of_the_un_iced_aircraft_and_eta_0_is_within_the_relatch_floor_of_stock(
        iced_run, clean_run, stock_run):
    """The trim sample (before any step) carries eta 0 and factors 1.0 on
    the iced run, and its trimmed elevator is the stock run's to 1e-12
    deg; the stated-eta-0 run keeps every recorded column within 4.0e-10
    of the stock run (measured 4.0e-10: the five pre-trim re-latches move
    the state at the floating-point floor, as P1's do; the digests differ
    and bit-identity is not claimed)."""
    for run in (iced_run, clean_run):
        assert run.telemetry.series("icing_eta")[0] == 0.0
        assert all(run.telemetry.series(f"icing_{axis}_factor")[0] == 1.0 for axis in AXES)
        assert run.telemetry.series("icing_alpha_shift_deg")[0] == 0.0
    assert iced_run.telemetry.series("elevator_deg")[0] == pytest.approx(
        stock_run.telemetry.series("elevator_deg")[0], abs=1e-12)
    assert iced_run.telemetry.series("elevator_deg")[0] == pytest.approx(4.30613, abs=1e-4)
    worst = max(abs(a - b) for column in stock_run.telemetry.columns if column != "t"
                for a, b in zip(clean_run.telemetry.series(column), stock_run.telemetry.series(column)))
    assert worst < 1e-8 and worst > 0.0                       # measured 4.0e-10
    assert clean_run.output_digest != stock_run.output_digest
    assert iced_run.output_digest != clean_run.output_digest
    assert iced_run.manifest["fdm"]["derivation"]["suffix"] == "-ice-alpha"
    assert "derivation" not in stock_run.manifest["fdm"]


def test_every_property_is_written_every_step_and_read_back_exactly_before_the_next_write(iced_run):
    block = iced_run.manifest["icing"]
    rb = block["per_step_readback"]
    assert rb["steps_written"] == 360 and rb["steps_checked"] == 359
    assert set(rb["max_abs_error"]) == set(PROPERTIES)
    assert all(e == 0.0 for e in rb["max_abs_error"].values())
    assert rb["last_written"][PROPERTY_ETA] == 0.2 and rb["last_read"][PROPERTY_ETA] == 0.2
    assert rb["last_read"]["icing/lift-factor"] == pytest.approx(0.982)
    assert all(v["agrees"] for v in rb["pre_trim_after_trim"].values())     # the neutral writes survived the trim
    assert block["schedule"] == {"first_step_eta": 0.2, "eta_at_end": 0.2, "t_first_ice_s": 0.0,
                                 "t_full_s": 0.0, "steps_with_ice": 360, "steps_at_full": 360,
                                 "steps_first_ice_to_full": 1, "first_ice_step": 0, "full_step": 0}
    assert block["run_clock_zero_sim_time_s"] == pytest.approx(4.875, abs=0.01)   # the c172p's crank
    assert block["applied"] is True and block["k_table"]["proxy"] is True
    columns = iced_run.telemetry.columns
    assert columns["icing_eta"][1:] == [0.2] * (len(iced_run.telemetry) - 1)
    assert columns["icing_lift_factor"][1] == pytest.approx(0.982)
    assert columns["icing_drag_factor"][-1] == pytest.approx(1.068)
    assert columns["icing_side_factor"][5] == pytest.approx(0.96)
    assert set(TELEMETRY_COLUMNS) <= set(DEFAULT_CHANNELS)
    for column in TELEMETRY_COLUMNS:
        values = columns[column]
        assert len(values) == len(iced_run.telemetry) and all(math.isfinite(v) for v in values)


def test_the_read_back_agreement_is_measured_not_assumed():
    """A property that came back other than written is reported: the
    provider's read-back keeps the largest error and the record's readback
    says agrees false. Fed a fake FDM whose store returns a wrong value."""
    provider = IcingProvider.from_spec(spec_for(eta_max=0.2))

    class Store:
        def __init__(self, values):
            self.values = values

        def get(self, name):
            return self.values[name]

        def has(self, name):
            return name in self.values

    class Fake:
        def __init__(self, values):
            self.props = Store(values)
            self.sim_time = 5.0

    provider.prepared = {"neutral_writes": {}, "readback": {}}
    writes = provider.properties(None, 5.0)
    wrong = dict(writes)
    wrong[PROPERTY_ETA] = 0.19                                   # a store that lost the last write
    provider.observe(Fake(wrong))
    assert provider.readback["steps_checked"] == 1
    assert provider.readback["max_abs_error"][PROPERTY_ETA] == pytest.approx(0.01)
    assert provider.readback["max_abs_error"]["icing/lift-factor"] == 0.0
    readback = provider._readback_of(PROPERTY_ETA)
    assert readback.agrees is False and readback.value == 0.19 and readback.written == 0.2
    provider.observe(Fake(dict(writes)))
    assert provider.readback["max_abs_error"][PROPERTY_ETA] == pytest.approx(0.01)   # the worst is kept


def test_the_first_step_lift_falls_by_exactly_the_factor_at_fixed_alpha():
    """P8's ladder row (eta 0 vs 0.2), measured at the step level: two
    identically trimmed c172p (1500 m / 100 kt), the provider's first-step
    writes made on each (eta 0.2 against eta 0), one step: 1872.5287 lbf
    un-iced, 1838.8232 lbf iced -- 0.982 x to 1.1e-16 relative, the same
    alpha on both (0.38578 deg). The claim is the factor form: the whole
    LIFT axis scales (P2); 'within 1 %' is met exactly."""
    def first_step(eta_max):
        spec = spec_for(eta_max=eta_max)
        fdm = quiet(configure_from_spec, spec)
        provider = IcingProvider.from_spec(spec)
        provider.observe(fdm)
        writes = provider.properties(None, fdm.sim_time)
        fdm.props.set_many(writes)
        fdm.step()
        return (fdm.props.get("forces/fwz-aero-lbs"), writes["icing/lift-factor"],
                fdm.props.get("aero/alpha-deg"))
    iced, factor, alpha_iced = first_step(0.2)
    clean, one, alpha_clean = first_step(0.0)
    assert one == 1.0 and factor == pytest.approx(0.982)
    assert clean == pytest.approx(1872.5287, abs=5e-4)
    assert iced == pytest.approx(1838.8232, abs=5e-4)
    assert iced / clean == pytest.approx(factor, rel=1e-12)
    assert alpha_iced == alpha_clean == pytest.approx(0.38578, abs=1e-4)


# -- the records --------------------------------------------------------------------------

def test_each_stated_field_and_each_factor_returns_its_record_2(iced_run):
    records = icing_records(iced_run)
    assert list(records) == ["icing.eta", "icing.lift_factor", "icing.drag_factor",
                             "icing.pitch_factor", "icing.roll_factor", "icing.yaw_factor",
                             "icing.side_factor"]
    eta = records["icing.eta"]
    assert eta["value"] == 0.2 and eta["unit"] == "1" and eta["source"] == "user"
    assert eta["readback"] == {"property": PROPERTY_ETA, "value": 0.2, "written": 0.2, "agrees": True,
                               "tolerance": 0.0, "tolerance_kind": "absolute",
                               "basis": eta["readback"]["basis"]}
    assert [w["property"] for w in eta["jsbsim_writes"]] == list(PROPERTIES)
    assert eta["properties_written"] == list(PROPERTIES)
    assert eta["telemetry_columns"] == list(TELEMETRY_COLUMNS) == eta["frame_keys"]
    model = eta["model"]
    assert model["name"] == "Bragg factor form with a severity ramp"
    assert "(1 + eta k_A)" in model["standard"] and "clamp" in model["standard"]
    assert model["parameters"]["k_table"] == {f"k_{a}": DHC6_K[a] for a in AXES}
    assert model["parameters"]["k_proxy"] is True and model["parameters"]["k_proxy_of"] == "DHC6"
    assert model["parameters"]["severity_words"] == SEVERITY_WORDS
    null = eta["null_test"]
    assert null["kind"] == "reached" and null["ok"] is True and null["unit"] == "N"
    # the pre-trim lift with the factors at eta_max against neutral, at the
    # initial conditions (alpha 0): 6566.15 -> 6449.44 N, ratio 0.98222
    # (0.982 with the one-relatch wander of 0.1 lbf, measured)
    assert null["without"] == pytest.approx(6566.15, abs=0.5)
    assert null["with"] == pytest.approx(6449.44, abs=0.5)
    assert null["with"] / null["without"] == pytest.approx(0.982, abs=5e-4)
    assert null["threshold"] == 1.0
    p = eta["parameters"]
    assert p["pre_trim"]["lift_ratio_with_factors"] == pytest.approx(0.982, abs=5e-4)
    assert p["pre_trim"]["relatches"] == 5 and p["derived_aircraft"] == "c172p-ice-alpha"
    assert p["per_step_readback"]["agrees"] is True and p["per_step_readback"]["steps_checked"] == 359
    assert p["pre_trim"]["readback"][PROPERTY_ETA]["agrees"] is True
    assert any("transcription" in n for n in eta["not_claimed"])
    assert any("WHOLE tables" in n for n in eta["not_claimed"])
    for axis in AXES:
        rec = records[f"icing.{axis}_factor"]
        assert rec["value"] == pytest.approx(1.0 + 0.2 * DHC6_K[axis]) and rec["source"] == "derived"
        assert rec["readback"]["property"] == f"icing/{axis}-factor" and rec["readback"]["agrees"]
        assert rec["readback"]["value"] == pytest.approx(rec["value"])
        assert rec["jsbsim_writes"] == [{"property": f"icing/{axis}-factor", "when": ic.WHEN_FACTOR}]
        assert rec["std"] == load_k_table("c172p").sources[axis] and "proxy" in rec["from"]
        assert rec["null_test"]["kind"] == "reached"
    assert records["icing.drag_factor"]["null_test"]["unit"] == "N"
    assert records["icing.drag_factor"]["null_test"]["ok"] is True          # 842.8 -> 900.1 N
    assert records["icing.pitch_factor"]["null_test"]["unit"] == "N m"
    assert records["icing.pitch_factor"]["null_test"]["without"] == pytest.approx(4048.35, abs=1.0)
    assert records["icing.pitch_factor"]["null_test"]["with"] == pytest.approx(3923.26, abs=1.0)
    side = records["icing.side_factor"]["null_test"]
    assert side["with"] == 0.0 and side["without"] == 0.0 and side["ok"] is False
    assert "honestly not reached" in side["note"]
    json.dumps(iced_run.manifest)
    assert json.dumps(iced_run.manifest).isascii()


def test_the_default_block_records_nothing_and_a_stock_airframe_reads_neutral_columns(stock_run):
    assert stock_run.manifest["icing"] is None and icing_records(stock_run) == {}
    assert [r["name"] for r in read_records(stock_run.manifest["applied_variables"])] == [
        "limits.monitor", "scene.geoid_undulation_m"]
    assert "icing" not in [p["name"] for p in stock_run.manifest["environment"]]
    columns = stock_run.telemetry.columns
    assert set(columns["icing_eta"]) == {0.0} and set(columns["icing_alpha_shift_deg"]) == {0.0}
    assert all(set(columns[f"icing_{axis}_factor"]) == {1.0} for axis in AXES)


def test_the_word_the_onset_the_ramp_the_shift_and_the_envelope_each_return_a_record():
    run = quiet(run_spec, spec_for(severity="light", onset_s=1.0, ramp_s=1.0, alpha_shift_deg=2.0,
                                   envelope="appendix_c"))
    records = icing_records(run)
    assert list(records)[:5] == ["icing.severity", "icing.onset_s", "icing.ramp_s",
                                 "icing.alpha_shift_rad", "icing.envelope"]
    assert "icing.eta" not in records                    # the word carries the write; no number stated
    word = records["icing.severity"]
    assert word["value"] == "light" and word["unit"] == "word" and word["source"] == "user"
    assert word["parameters"]["word_to_eta"] == 0.10 and word["readback"]["agrees"]
    assert word["readback"]["written"] == pytest.approx(0.10)
    assert word["null_test"]["ok"] is True and word["null_test"]["unit"] == "N"
    onset = records["icing.onset_s"]
    assert onset["value"] == 1.0 and onset["unit"] == "s"
    assert onset["null_test"]["with"] == pytest.approx(1.0, abs=1e-9)      # measured 1.0000000000000497
    assert onset["null_test"]["without"] == 0.0 and onset["null_test"]["threshold"] == pytest.approx(1 / 120)
    assert onset["null_test"]["ok"] is True
    ramp = records["icing.ramp_s"]
    assert ramp["null_test"] == {**ramp["null_test"], "with": 121.0, "without": 1.0, "unit": "steps", "ok": True}
    schedule = run.manifest["icing"]["schedule"]
    # the write is at the TOP of a step, t = step / 120 on the run clock; JSBSim's clock
    # accumulates dt, so step 120 sits at t = 1.00000000000005 s (P3 measured the same
    # 5e-14) and is the first iced step (eta 1e-15), full eta (t >= 2.0) is step 240
    assert schedule["first_ice_step"] == 120 and schedule["full_step"] == 240 and schedule["steps_first_ice_to_full"] == 121
    assert schedule["t_first_ice_s"] == pytest.approx(1.0, abs=1e-9) and schedule["t_first_ice_s"] > 1.0
    assert schedule["t_full_s"] == pytest.approx(2.0, abs=1e-9)
    shift = records["icing.alpha_shift_rad"]
    assert shift["value"] == pytest.approx(math.radians(2.0)) and shift["unit"] == "rad"
    assert shift["readback"]["property"] == PROPERTY_SHIFT and shift["readback"]["agrees"]
    assert shift["readback"]["written"] == pytest.approx(math.radians(2.0))      # full at the end (ramp done)
    assert shift["null_test"]["ok"] is True and shift["null_test"]["unit"] == "N"
    # the LIFT table at alpha 0 + 2 deg against alpha 0, at the initial conditions: 6566 -> 11378 N
    assert shift["null_test"]["with"] / shift["null_test"]["without"] == pytest.approx(1.733, abs=0.01)
    envelope = records["icing.envelope"]
    assert envelope["value"] == "appendix_c" and envelope["properties_written"] == []
    assert envelope["null_test"]["kind"] == "bounded" and envelope["null_test"]["ok"] is True
    assert envelope["parameters"]["applied"] is False and "readback" not in envelope
    columns = run.telemetry.columns
    # sample k is taken after the step that reaches run-clock 0.1 k (the write of that
    # step was made at its top, one step earlier): sample 10 still carries eta 0
    assert columns["icing_eta"][:11] == [0.0] * 11
    assert columns["icing_eta"][11] == pytest.approx(0.10 * (131 / 120 - 1.0), abs=1e-9)
    assert columns["icing_eta"][20] == pytest.approx(0.10 * (239 / 120 - 1.0), abs=1e-9)
    assert columns["icing_eta"][21] == 0.10 and columns["icing_eta"][-1] == 0.10
    assert columns["icing_alpha_shift_deg"][-1] == pytest.approx(2.0)
    assert columns["icing_alpha_shift_deg"][11] == pytest.approx(2.0 * (131 / 120 - 1.0), abs=1e-9)


def test_a_stated_number_wins_over_the_word_and_both_records_are_written():
    run = quiet(run_spec, spec_for(severity="severe", eta_max=0.1))
    records = icing_records(run)
    assert list(records)[:2] == ["icing.severity", "icing.eta"]
    assert records["icing.severity"]["parameters"]["number_stated_beside_it"] is True
    assert run.telemetry.series("icing_eta")[-1] == 0.1
    assert records["icing.eta"]["readback"]["written"] == 0.1


# -- the stall-onset cue: P2's static sweep through the provider's writes ----------------------

def lift_curve(shift_deg: float, eta_max: float = 0.2):
    fdm = FlightDynamics.with_injections("c172p", INJECTIONS)
    provider = IcingProvider.from_spec(spec_for(eta_max=eta_max, alpha_shift_deg=shift_deg))
    sweep = {k: v for k, v in LEVEL.items() if k != "gamma-deg"}
    writes = provider.writes_at(0.0)
    writes.update({p: 1.0 for p in ic.FACTOR_PROPERTIES.values()})    # the shift alone
    out = []
    alpha = 8.0
    while alpha <= 22.0 + 1e-9:
        fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(ALT_M), "vc-kts": CAS_KT,
                                    "alpha-deg": alpha, **sweep}, tolerance=5e-2)
        fdm.props.set_many(writes)
        fdm.step()
        cl = (fdm.props.get("forces/fwz-aero-lbs")
              / (fdm.props.get("aero/qbar-psf") * fdm.props.get("metrics/Sw-sqft")))
        out.append((round(alpha, 2), cl))
        alpha += 0.25
    return out


def test_the_alpha_shift_moves_the_stall_onset_alpha_by_the_stated_cue():
    """P2's measurement re-made through the provider's own writes: the
    c172p's static lift peak moves from 16.25 deg requested to 14.25 deg
    with the 2 deg cue at full eta (-2.0 deg, the sweep's resolution)."""
    plain = quiet(lift_curve, 0.0)
    shifted = quiet(lift_curve, 2.0)
    peak_plain = max(plain, key=lambda r: r[1])
    peak_shifted = max(shifted, key=lambda r: r[1])
    assert peak_plain[0] == 16.25 and peak_plain[1] == pytest.approx(1.44896, abs=1e-4)
    assert peak_shifted[0] == 14.25 and peak_shifted[1] == pytest.approx(1.44966, abs=1e-4)
    assert peak_shifted[0] - peak_plain[0] == pytest.approx(-2.0)


# -- the card ------------------------------------------------------------------------------

def test_the_card_block_carries_the_schedule_and_the_k_table_in_the_fixed_key_order(tmp_path):
    assert CARD_KEYS == ("eta_max", "onset_s", "ramp_s", "alpha_shift_deg", "k_table", "source")
    assert K_KEYS == ("k_lift", "k_drag", "k_pitch", "k_roll", "k_yaw", "k_side")
    assert icing_schedule_card_block(spec_for()) is None
    spec = spec_for(severity="moderate", onset_s=1.0, ramp_s=2.0, alpha_shift_deg=2.0)
    block = icing_schedule_card_block(spec)
    assert tuple(block) == CARD_KEYS and tuple(block["k_table"]) == K_KEYS
    assert block == {"eta_max": 0.2, "onset_s": 1.0, "ramp_s": 2.0, "alpha_shift_deg": 2.0,
                     "k_table": {f"k_{a}": DHC6_K[a] for a in AXES}, "source": block["source"]}
    assert block["source"].startswith("PROXY of DHC6:")
    dhc6 = icing_schedule_card_block(dhc6_spec(eta_max=0.3))
    assert dhc6["eta_max"] == 0.3 and not dhc6["source"].startswith("PROXY")
    path = quiet(write_run_card, spec, tmp_path / "card.json")
    card = json.loads(path.read_text(encoding="utf-8"))
    assert card["icing_schedule"] == block and list(card["icing_schedule"]) == list(CARD_KEYS)
    assert path.read_text(encoding="utf-8").isascii()
    plain = json.loads(quiet(write_run_card, spec_for(), tmp_path / "plain.json").read_text(encoding="utf-8"))
    assert "icing_schedule" not in plain
    with pytest.raises(IcingError) as exc:
        icing_schedule_card_block(spec_for(aircraft="A320", altitude_m=6000.0, cas_kt=250.0, severity="light"))
    assert exc.value.constraint == "icing.airframe_data"


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    assert (REPO / "core/environment/icing.py").read_text(encoding="utf-8").isascii()
    assert inspect.getsource(IcingSpec).isascii()
    for name in ("DHC6", "c172p"):
        text = (REPO / f"assets/aircraft_config/{name}.json").read_text(encoding="utf-8")
        assert text.isascii(), name
        assert json.dumps(load_k_table(name).to_dict()).isascii()
    provider = IcingProvider.from_spec(spec_for(severity="severe", envelope="appendix_o"))
    assert json.dumps(provider.card_block()).isascii()
    assert json.dumps(provider.provenance()).isascii()


# -- the registry and the null pairs (integrated with R1) -------------------------------------

def test_the_registry_claims_the_block_field_for_field_with_recorded_channels(iced_run):
    fields = {f"icing.{f}" for f in IcingSpec.FIELD_ORDER}
    claimed = {path for path in REGISTRY.spec_fields() if path.startswith("icing.")}
    assert claimed == fields and "icing" in REGISTRY.sections()
    assert REGISTRY.spec_fields()["icing.eta_max"] == "icing.eta"
    assert REGISTRY.spec_fields()["icing.alpha_shift_deg"] == "icing.alpha_shift_rad"
    assert REGISTRY.get("icing.eta").null_value == 0.0
    assert REGISTRY.get("icing.severity").null_value is None
    assert REGISTRY.get("icing.envelope").null_value is None
    assert REGISTRY.get("icing.onset_s").null_value == 0.0 and REGISTRY.get("icing.ramp_s").null_value == 0.0
    assert REGISTRY.get("icing.alpha_shift_rad").null_value == 0.0
    recorded = set(iced_run.telemetry.columns)
    for entry in REGISTRY:
        if not entry.name.startswith("icing."):
            continue
        missing = [c.name for c in entry.effect_channels if c.name not in recorded]
        assert missing == [], (entry.name, missing)
        assert entry.null_basis
        if entry.name != "icing.envelope":
            assert entry.jsbsim_writes and entry.readback_tolerance.value == 0.0
    for axis in AXES:
        entry = REGISTRY.get(f"icing.{axis}_factor")
        assert entry.spec_path is None and entry.null_value is NO_NULL
        assert entry.effect_channels[0].name == f"icing_{axis}_factor"
    assert REGISTRY.unregistered_fields(spec_for(severity="trace").to_dict()) == []
    units = state_units(iced_run.telemetry.columns)
    assert "?" not in {units[c] for c in recorded}
    assert units["icing_eta"] == "1" and units["icing_lift_factor"] == "1"
    assert units["icing_alpha_shift_deg"] == "deg"


@pytest.mark.timeout(600)
def test_the_null_pair_eta_0_2_against_0_diverges_the_trimmed_flight():
    """eta 0.2 against 0 on the c172p (proxy row), 1500 m / 100 kt: over
    3 s lift_n moves 100.4 N at the first sample after the trim (8329.3
    -> 8228.9 N, 0.988 x: twelve steps into the flight the alphas have
    parted; the exact first-step factor is the step-level test above),
    drag_n 75.5 N, pitch 0.134 deg and TAS 0.40 kt (reached), altitude
    0.25 m (below the 0.5 m floor); over 10 s altitude 3.86 m, pitch 0.79
    deg, TAS 0.51 kt. The eta and factor channels move by 0.2 / 0.018 /
    0.068 and carry no floor today (reported, not graded: patch 1 gives
    them one). The severity word's pair is the same flight."""
    pair = quiet(run_null_pair, spec_for(eta_max=0.2), "icing.eta")
    assert pair.verdict == "reached" and pair.digests_differ and pair.null_test().ok
    assert pair.applied_value == 0.2 and pair.null_value == 0.0
    e = effects(pair)
    assert e["icing_eta"].peak_abs == 0.2 and e["icing_lift_factor"].peak_abs == pytest.approx(0.018)
    assert e["icing_drag_factor"].peak_abs == pytest.approx(0.068)
    assert e["lift_n"].peak_abs == pytest.approx(100.41, abs=0.5) and e["lift_n"].peak_index == 1
    assert e["lift_n"].with_at_peak / e["lift_n"].without_at_peak == pytest.approx(0.98794, abs=1e-4)
    assert e["drag_n"].peak_abs == pytest.approx(75.53, abs=0.5)
    assert e["pitch_deg"].peak_abs == pytest.approx(0.1336, abs=0.003) and e["pitch_deg"].reached is True
    assert e["tas_kt"].peak_abs == pytest.approx(0.4005, abs=0.005) and e["tas_kt"].reached is True
    assert e["altitude_m"].peak_abs == pytest.approx(0.2497, abs=0.005) and e["altitude_m"].reached is False
    assert pair.null_test().unit == "N"
    long = quiet(run_null_pair, spec_for(10, eta_max=0.2), "icing.eta")
    e = effects(long)
    assert e["altitude_m"].peak_abs == pytest.approx(3.861, abs=0.05) and e["altitude_m"].reached is True
    assert e["pitch_deg"].peak_abs == pytest.approx(0.7908, abs=0.01)
    assert e["tas_kt"].peak_abs == pytest.approx(0.512, abs=0.01)
    word = quiet(run_null_pair, spec_for(severity="moderate"), "icing.severity")
    assert word.verdict == "reached" and word.null_value is None
    assert effects(word)["lift_n"].peak_abs == pytest.approx(100.41, abs=0.5)


@pytest.mark.timeout(600)
def test_the_null_pairs_of_the_onset_the_ramp_the_shift_and_the_envelope():
    """Measured on the c172p at eta 0.2, 3 s: onset 1 s against 0 keeps
    the flight clean for 120 steps (lift 100.4 N at the first sample,
    pitch 0.082 deg, TAS 0.156 kt reached); ramp 2 s against a step (eta
    0.0092 on the first sample against 0.2; pitch 0.078 deg, TAS 0.144
    kt); the 2 deg shift against none moves alpha 0.72 deg, lift 3697 N,
    altitude 17.7 m, pitch 11.8 deg; the envelope word moves nothing
    (silent by construction, digests equal)."""
    onset = quiet(run_null_pair, spec_for(eta_max=0.2, onset_s=1.0), "icing.onset_s")
    assert onset.verdict == "reached"
    e = effects(onset)
    assert e["icing_eta"].with_at_peak == 0.0 and e["icing_eta"].without_at_peak == 0.2
    assert e["pitch_deg"].peak_abs == pytest.approx(0.0823, abs=0.003)
    assert e["tas_kt"].peak_abs == pytest.approx(0.1559, abs=0.005)
    ramp = quiet(run_null_pair, spec_for(eta_max=0.2, ramp_s=2.0), "icing.ramp_s")
    assert ramp.verdict == "reached"
    e = effects(ramp)
    # the peak difference is at sample 1 (taken after step 11, written at its top: t = 11/120)
    assert e["icing_eta"].peak_index == 1
    assert e["icing_eta"].with_at_peak == pytest.approx(0.2 * (11 / 120) / 2.0, abs=1e-9)
    assert e["pitch_deg"].peak_abs == pytest.approx(0.0776, abs=0.003)
    shift = quiet(run_null_pair, spec_for(eta_max=0.2, alpha_shift_deg=2.0), "icing.alpha_shift_rad")
    assert shift.verdict == "reached" and shift.applied_value == 2.0
    e = effects(shift)
    assert e["icing_alpha_shift_deg"].peak_abs == pytest.approx(2.0)
    assert e["alpha_deg"].peak_abs == pytest.approx(0.717, abs=0.01)
    assert e["lift_n"].peak_abs == pytest.approx(3697.0, abs=5.0)
    assert e["altitude_m"].peak_abs == pytest.approx(17.75, abs=0.1)
    assert e["pitch_deg"].peak_abs == pytest.approx(11.76, abs=0.1)
    envelope = quiet(run_null_pair, spec_for(envelope="appendix_c"), "icing.envelope")
    assert envelope.verdict == "silent" and not envelope.digests_differ
    assert all(x.peak_abs == 0.0 for x in envelope.effects)
    pairs = quiet(null_pairs_for_spec, spec_for(severity="light", onset_s=0.5))
    assert list(pairs) == ["icing.severity", "icing.onset_s"]
    assert all(p.verdict == "reached" for p in pairs.values())


# -- the DHC6: the airframe the k-table was measured on ------------------------------------------

def _dhc6_loadable() -> None:
    """The stand-in for the derive patch this item returns: the derived
    DHC6 refuses to load at HEAD ("Could not open file: Propeller") because
    core/control/derive.py copies the stock model's sibling FILES only and
    the DHC6 keeps its engine, propeller and system files in aircraft-local
    subdirectories. Copy them into the build directory exactly as the patch
    makes derive do (a stock file never overwrites an injected system)."""
    derived = derive("DHC6", injections=INJECTIONS)
    stock_dir = Path(derive.__globals__["ac"].resolve("DHC6").xml_path).parent
    for inner in sorted(stock_dir.rglob("*")):
        if not inner.is_file() or inner.parent == stock_dir:
            continue
        target = derived.xml_path.parent / inner.relative_to(stock_dir)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inner, target)


@pytest.mark.timeout(600)
def test_the_dhc6_flies_its_own_row_the_first_step_lift_falls_by_the_factor_and_the_pair_diverges():
    """The Twin Otter row on the DHC6 at 1500 m / 120 kt: the pre-trim
    lift ratio is 0.982 exactly (40249.28 -> 39524.79 N at alpha 0; no
    crank, no re-latch wander); the first step after the provider's
    write 10078.629 -> 9897.214 lbf (0.982 to 1.1e-16); every read-back
    0.0 over 359 steps; the pair 0.2 against 0 over 3 s moves lift 725.7
    N, drag 349.8 N, altitude 0.61 m, pitch 0.31 deg, TAS 0.24 kt (all
    reached); the 2 deg shift at eta 0.2 moves alpha 0.84 deg, lift 11147
    N, altitude 7.9 m, pitch 3.7 deg."""
    _dhc6_loadable()
    run = quiet(run_spec, dhc6_spec(eta_max=0.2))
    assert run.manifest["fdm"]["aircraft"]["name"] == "DHC6-ice-alpha"
    block = run.manifest["icing"]
    assert block["k_table"]["proxy"] is False
    assert block["prepared"]["lift_ratio_with_factors"] == pytest.approx(0.982, abs=1e-6)
    assert block["prepared"]["baseline"]["lift"] == pytest.approx(40249.28, abs=0.5)
    assert block["per_step_readback"]["steps_checked"] == 359
    assert all(e == 0.0 for e in block["per_step_readback"]["max_abs_error"].values())
    records = icing_records(run)
    assert records["icing.eta"]["null_test"]["ok"] and records["icing.pitch_factor"]["null_test"]["ok"]
    assert records["icing.pitch_factor"]["null_test"]["without"] == pytest.approx(7101.2, abs=1.0)

    def first_step(eta_max):
        spec = dhc6_spec(eta_max=eta_max)
        fdm = quiet(configure_from_spec, spec)
        provider = IcingProvider.from_spec(spec)
        provider.observe(fdm)
        writes = provider.properties(None, fdm.sim_time)
        fdm.props.set_many(writes)
        fdm.step()
        return fdm.props.get("forces/fwz-aero-lbs"), writes["icing/lift-factor"]
    iced, factor = first_step(0.2)
    clean, _ = first_step(0.0)
    assert clean == pytest.approx(10078.629, abs=5e-3) and iced == pytest.approx(9897.214, abs=5e-3)
    assert iced / clean == pytest.approx(factor, rel=1e-12)
    pair = quiet(run_null_pair, dhc6_spec(eta_max=0.2), "icing.eta")
    assert pair.verdict == "reached" and pair.digests_differ
    e = effects(pair)
    assert e["lift_n"].peak_abs == pytest.approx(725.65, abs=2.0) and e["lift_n"].peak_index == 1
    assert e["drag_n"].peak_abs == pytest.approx(349.8, abs=2.0)
    assert e["altitude_m"].peak_abs == pytest.approx(0.607, abs=0.01) and e["altitude_m"].reached is True
    assert e["pitch_deg"].peak_abs == pytest.approx(0.313, abs=0.005)
    assert e["tas_kt"].peak_abs == pytest.approx(0.2389, abs=0.005) and e["tas_kt"].reached is True
    shift = quiet(run_null_pair, dhc6_spec(eta_max=0.2, alpha_shift_deg=2.0), "icing.alpha_shift_rad")
    e = effects(shift)
    assert e["alpha_deg"].peak_abs == pytest.approx(0.845, abs=0.01)
    assert e["lift_n"].peak_abs == pytest.approx(11147.0, abs=20.0)
    assert e["altitude_m"].peak_abs == pytest.approx(7.89, abs=0.1)


# -- the randomisation leaves ------------------------------------------------------------------

def test_the_policy_leaves_draw_eta_max_and_the_onset_and_the_realised_distribution_counts_them():
    from core.scenario.randomization import (
        POLICY_LEAVES, RandomizationError, card_block, realised_distribution, sample_randomization,
    )

    assert POLICY_LEAVES["icing_eta_max"]["target"] == "icing.eta_max"
    assert POLICY_LEAVES["icing_onset_s"]["target"] == "icing.onset_s"
    spec = spec_for()
    spec.set("randomization.policy", {"icing_eta_max": {"uniform": [0.05, 0.3]},
                                      "icing_onset_s": {"uniform": [0.0, 2.0]}}, frm="test")
    spec.set("randomization.seed", 3, frm="test")
    quiet(sample_randomization, spec)
    eta, onset = spec.icing.eta_max, spec.icing.onset_s
    assert eta.source is Source.SAMPLED and 0.05 <= eta.value <= 0.3 and eta.unit == "1"
    assert onset.source is Source.SAMPLED and 0.0 <= onset.value <= 2.0 and onset.unit == "s"
    assert eta.detail["policy"] == "randomization.policy.icing_eta_max"
    assert spec.icing.resolved()["eta_max"].value == eta.value
    block = card_block(spec)
    assert block["icing_eta_max"] == eta.value and block["icing_onset_s"] == onset.value
    realised = realised_distribution([{"randomization": block, "frames": 4}])
    assert realised["fields"]["icing_eta_max"]["frames"] == 4
    assert realised["fields"]["icing_onset_s"]["frames"] == 4
    assert realised["fields"]["icing_eta_max"]["coverage"] > 0.0
    assert validate(spec, check_feasibility=False).ok
    assert icing_schedule_card_block(spec)["eta_max"] == eta.value
    stated = spec_for(eta_max=0.2)
    stated.set("randomization.policy", {"icing_eta_max": {"uniform": [0.05, 0.3]}}, frm="test")
    stated.set("randomization.seed", 3, frm="test")
    with pytest.raises(RandomizationError) as exc:
        quiet(sample_randomization, stated)
    assert exc.value.constraint == "randomization.policy" and "never moved" in exc.value.message
    none = spec_for(aircraft="A320", altitude_m=6000.0, cas_kt=250.0)
    none.set("randomization.policy", {"icing_eta_max": {"uniform": [0.05, 0.3]}}, frm="test")
    none.set("randomization.seed", 3, frm="test")
    with pytest.raises(RandomizationError) as exc:
        quiet(sample_randomization, none)
    assert exc.value.constraint == "randomization.policy" and "no icing table" in exc.value.message
