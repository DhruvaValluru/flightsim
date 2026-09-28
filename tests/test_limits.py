"""Operational and structural limit monitoring (core/telemetry/limits.py).

Gap P5: ``n_z``, ``cas_kt`` and ``mach`` were recorded and never compared
with a limit. These tests measure the monitor on synthetic columns
(exact flags), on real flights (the A320 at V_MO + 20 kt flags every
sample; the same model at cruise flags none), on the manifest (the block,
the record, the per-frame state) and on the table (every configured
airframe states a sourced table; a malformed one refuses by name).

Not claimed here: that the placard values are right (the table cites
each as verified or ``unverified here``); a c172p run beyond V_NE (the
model cannot be trimmed there -- measured below, not assumed).
"""
from __future__ import annotations

import io
import contextlib
import json

import pytest

from core.capture.hostflight import digest_columns
from core.capture.manifest import frame_state
from core.nl.compiler import compile_prompt
from core.records import AppliedVariable, read_records
from core.scenario.blocks import configured_airframes
from core.scenario.runner import attach_record, run_spec
from core.scenario.validate import validate
from core.telemetry.limits import (
    ANY_COLUMN, CHECKS, LIMIT_KEYS, LimitsConfigError, LimitsTable, annotate,
    applied_variable, load_limits, monitor, monitor_run, null_test, parse_limits,
)
from core.telemetry.recorder import Recorder

#: A well-formed block in the configs' own shape (a light transport).
BLOCK = {
    "category": {"value": "transport", "regulation": "14 CFR 25.337",
                 "source": "test"},
    "n_z_pos_g": {"value": 2.5, "source": "14 CFR 25.337(b)"},
    "n_z_neg_g": {"value": -1.0, "source": "14 CFR 25.337(c)"},
    "speed_limit_kt": {"value": 350.0, "kind": "V_MO", "source": "test placard"},
    "m_mo": {"value": 0.82, "source": "test placard"},
    "alpha_stall_deg": {"value": None, "reason": "the model states none"},
}


def table(**overrides) -> LimitsTable:
    block = json.loads(json.dumps(BLOCK))
    for key, value in overrides.items():
        block[key] = value
    return parse_limits("test", block, config_path="test.json", config_sha256="0" * 64)


def columns(**series):
    """Synthetic telemetry: t at 0.1 s plus the given channels."""
    n = max(len(v) for v in series.values())
    out = {"t": [round(0.1 * i, 3) for i in range(n)]}
    out.update({k: list(v) for k, v in series.items()})
    return out


class _NoFDM:
    """Stands where the FDM would: never stepped, never sampled."""
    sim_time = 0.0
    rate_hz = 120.0

    def provenance(self):
        return {"stub": "no FDM: columns written by the test"}


def recorder_from(cols) -> Recorder:
    """A Recorder holding these columns (never sampled: no FDM)."""
    rec = Recorder(fdm=_NoFDM(), interval_s=0.1, channels=tuple(cols))
    for name, values in cols.items():
        rec.columns[name].extend(values)
    return rec


# -- the flags on synthetic columns -----------------------------------------------

def test_monitor_flags_are_exact_on_synthetic_columns():
    cols = columns(
        n_z=[1.0, 2.6, 2.5, -1.2, 1.0],
        cas_kt=[300.0, 351.0, 350.0, 349.0, 360.0],
        mach=[0.5, 0.83, 0.82, 0.81, 0.9],
        alpha_deg=[2.0, 3.0, 4.0, 5.0, 6.0])
    result = monitor(cols, table())
    assert result.flags == {
        "exceed_nz_pos": [0, 1, 0, 0, 0],
        "exceed_nz_neg": [0, 0, 0, 1, 0],
        "exceed_vne_or_vmo": [0, 1, 0, 0, 1],
        "exceed_mmo": [0, 1, 0, 0, 1],
        ANY_COLUMN: [0, 1, 0, 1, 1],
    }
    s = result.summary
    assert s["samples"] == 5
    assert s["monitored"] == ["n_z_pos_g", "n_z_neg_g", "speed_limit_kt", "m_mo"]
    assert s["unmonitored"] == {"alpha_stall_deg": "the model states none"}
    assert "exceed_alpha_stall" not in result.flags
    nz = s["per_limit"]["n_z_pos_g"]
    assert nz["count"] == 1 and nz["first_exceedance_s"] == 0.1
    assert nz["worst_margin"] == pytest.approx(2.5 - 2.6)
    assert nz["worst_value"] == 2.6 and nz["worst_t_s"] == 0.1
    neg = s["per_limit"]["n_z_neg_g"]
    assert neg["count"] == 1 and neg["first_exceedance_s"] == pytest.approx(0.3)
    assert neg["worst_margin"] == pytest.approx(-1.2 - (-1.0))
    speed = s["per_limit"]["speed_limit_kt"]
    assert speed["count"] == 2 and speed["kind"] == "V_MO"
    assert speed["worst_margin"] == pytest.approx(-10.0) and speed["worst_t_s"] == pytest.approx(0.4)
    assert s["any_exceedance"] == {"column": ANY_COLUMN, "count": 3, "fraction": 0.6,
                                   "first_exceedance_s": 0.1}
    assert s["columns_added"] == list(result.flags)


def test_a_sample_exactly_at_the_limit_is_not_flagged():
    """Strict comparison: at the limit is at the limit. The guard flips
    ``>`` to ``>=`` (and ``<`` to ``<=``); either flip flags the samples
    that sit exactly on the placard."""
    cols = columns(n_z=[2.5, -1.0, 2.5 + 1e-9, -1.0 - 1e-9],
                   cas_kt=[350.0, 350.0, 350.0 + 1e-9, 0.0],
                   mach=[0.82, 0.82, 0.82 + 1e-9, 0.0])
    result = monitor(cols, table())
    assert result.flags["exceed_nz_pos"] == [0, 0, 1, 0]
    assert result.flags["exceed_nz_neg"] == [0, 0, 0, 1]
    assert result.flags["exceed_vne_or_vmo"] == [0, 0, 1, 0]
    assert result.flags["exceed_mmo"] == [0, 0, 1, 0]
    assert result.summary["per_limit"]["n_z_pos_g"]["worst_margin"] == pytest.approx(-1e-9)


def test_summary_count_is_the_number_of_flagged_samples():
    cols = columns(n_z=[3.0] * 7 + [1.0] * 3, cas_kt=[100.0] * 10, mach=[0.3] * 10)
    result = monitor(cols, table())
    assert result.summary["per_limit"]["n_z_pos_g"]["count"] == 7
    assert result.summary["any_exceedance"]["count"] == 7
    assert sum(result.flags["exceed_nz_pos"]) == 7


def test_an_unstated_limit_writes_no_column_and_says_why():
    """A flag column for a limit nobody stated would read 'not exceeded'
    about a limit that was never compared."""
    result = monitor(columns(n_z=[1.0], cas_kt=[100.0], mach=[0.3]),
                     table(m_mo={"value": None, "reason": "no Mach limit published"}))
    assert "exceed_mmo" not in result.flags
    assert result.summary["per_limit"]["m_mo"] == {
        "limit": None, "unit": "Mach", "kind": None, "channel": "mach",
        "column": None, "monitored": False, "reason": "no Mach limit published"}
    assert result.summary["unmonitored"]["m_mo"] == "no Mach limit published"


def test_a_missing_channel_is_reported_not_guessed():
    result = monitor(columns(n_z=[1.0, 3.0]), table())
    assert result.flags["exceed_nz_pos"] == [0, 1]
    assert "exceed_vne_or_vmo" not in result.flags
    assert result.summary["unmonitored"]["speed_limit_kt"] == "channel 'cas_kt' not recorded"
    assert result.summary["per_limit"]["speed_limit_kt"]["monitored"] is False
    assert result.summary["per_limit"]["speed_limit_kt"]["limit"] == 350.0


def test_ragged_columns_and_a_missing_clock_refuse():
    with pytest.raises(ValueError, match="samples where 't'"):
        monitor({"t": [0.0, 0.1], "n_z": [1.0]}, table())
    with pytest.raises(ValueError, match="'t' column"):
        monitor({"n_z": [1.0]}, table())


def test_the_check_table_covers_every_limit_key_once():
    assert tuple(k for k, *_ in CHECKS) == LIMIT_KEYS
    assert len({column for _, column, *_ in CHECKS}) == len(CHECKS)


# -- annotation ---------------------------------------------------------------------

def test_annotate_writes_the_flags_beside_the_recorded_columns():
    cols = columns(n_z=[1.0, 2.6, 1.0], cas_kt=[100.0] * 3, mach=[0.3] * 3)
    rec = recorder_from(cols)
    result = monitor(rec.columns, table())
    added = annotate(rec, result)
    assert added == ["exceed_nz_pos", "exceed_nz_neg", "exceed_vne_or_vmo",
                     "exceed_mmo", ANY_COLUMN]
    assert rec.derived == added
    assert rec.columns["exceed_nz_pos"] == [0, 1, 0]
    assert rec.to_dict()["derived"] == added
    # The per-frame state copies every column, flags included, unchanged.
    assert frame_state(rec.columns, 1)["exceed_nz_pos"] == 1.0
    assert frame_state(rec.columns, 1)[ANY_COLUMN] == 1.0
    assert frame_state(rec.columns, 0)[ANY_COLUMN] == 0.0


def test_recorder_annotate_refuses_a_clash_and_a_wrong_length():
    rec = recorder_from(columns(n_z=[1.0, 1.0]))
    with pytest.raises(ValueError, match="already a column"):
        rec.annotate("n_z", [0, 0])
    with pytest.raises(ValueError, match="2 samples"):
        rec.annotate("flag", [0])
    assert rec.derived == [] and "flag" not in rec.columns


# -- the record's null test -------------------------------------------------------------

def test_null_test_measures_both_sides_of_the_limit_from_the_runs_own_samples():
    inside = null_test(columns(cas_kt=[300.0, 330.0, 320.0], n_z=[1.0] * 3), table())
    assert inside.quantity == "samples flagged exceed_vne_or_vmo"
    # Peak 330 -> pushed to 370: 300 -> 340 (inside), 330 -> 370, 320 -> 360.
    assert (inside.with_value, inside.without_value) == (2.0, 0.0)
    assert inside.ok and "flown inside" in inside.note and "+40.000" in inside.note
    beyond = null_test(columns(cas_kt=[360.0, 355.0, 340.0], n_z=[1.0] * 3), table())
    assert (beyond.with_value, beyond.without_value) == (2.0, 0.0)
    assert beyond.ok and "flown beyond" in beyond.note and "-30.000" in beyond.note
    # No speed limit stated: the positive load-factor limit is probed instead.
    # Peak 1.4 g -> pushed to 3.0 g (limit 2.5 + 0.5): 0.5 -> 2.1 (inside), 1.4 -> 3.0.
    by_g = null_test(columns(n_z=[0.5, 1.4]),
                     table(speed_limit_kt={"value": None, "reason": "none"}))
    assert by_g.quantity == "samples flagged exceed_nz_pos"
    assert (by_g.with_value, by_g.without_value) == (1.0, 0.0) and "+1.600" in by_g.note
    assert null_test(columns(alpha_deg=[1.0]), table()) is None


def test_the_record_is_a_valid_applied_variable():
    cols = columns(n_z=[1.0, 2.6], cas_kt=[100.0, 100.0], mach=[0.3, 0.3])
    result = monitor(cols, table())
    record = applied_variable(table(), result, null_test(cols, table()))
    assert isinstance(record, AppliedVariable)
    assert record.name == "limits.monitor" and record.source == "derived"
    assert record.model == "exceedance monitor against the certification envelope"
    assert record.properties_written == ()
    assert record.telemetry_columns == record.frame_keys == result.columns
    assert record.value == {"n_z_pos_g": 2.5, "n_z_neg_g": -1.0, "speed_limit_kt": 350.0,
                            "m_mo": 0.82, "alpha_stall_deg": None}
    assert any(r.startswith("14 CFR 23.337") for r in record.references)
    assert any(r.startswith("14 CFR 25.337") for r in record.references)
    assert record.null_test is not None and record.not_claimed
    json.dumps(record.to_dict())


# -- the table ----------------------------------------------------------------------------

EXPECTED = {
    # airframe: (category, n_z_pos, n_z_neg, speed, kind, m_mo)
    "c172p": ("normal", 3.8, -1.52, 163.0, "V_NE", None),
    "A320": ("transport", 2.5, -1.0, 350.0, "V_MO", 0.82),
    "B747": ("transport", 2.5, -1.0, 365.0, "V_MO", 0.92),
    "DHC6": ("normal", 3.8, -1.52, 170.0, "V_NE", None),
    "p51d": ("military", 6.0, -3.0, 439.0, "V_NE", None),
}


def test_every_configured_airframe_states_a_sourced_table():
    assert sorted(EXPECTED) == configured_airframes()
    for aircraft, (category, nz_pos, nz_neg, speed, kind, m_mo) in EXPECTED.items():
        t = load_limits(aircraft)
        assert t is not None, aircraft
        assert t.category == category and t.regulation and t.category_source
        assert t.limit("n_z_pos_g").value == nz_pos
        assert t.limit("n_z_neg_g").value == nz_neg
        assert t.limit("speed_limit_kt").value == speed
        assert t.limit("speed_limit_kt").kind == kind
        assert t.limit("m_mo").value == m_mo
        assert t.limit("alpha_stall_deg").value is None
        for key in LIMIT_KEYS:
            limit = t.limit(key)
            if limit.monitored:
                assert limit.source and limit.reason is None, (aircraft, key)
            else:
                assert limit.reason and limit.source is None, (aircraft, key)
        # Placard speeds are from memory and say so; the load factors cite the rule.
        assert "unverified here" in t.limit("speed_limit_kt").source
        assert "CFR" in t.limit("n_z_pos_g").source
        assert t.config_path == f"assets/aircraft_config/{aircraft}.json"
        assert len(t.config_sha256) == 64
        json.dumps(t.to_dict())


@pytest.mark.parametrize("field, entry, fragment", [
    ("n_z_pos_g", {"value": "3.8", "source": "x"}, "finite number"),
    ("n_z_pos_g", {"value": 3.8}, "has no source"),
    ("n_z_pos_g", {"value": -3.8, "source": "x"}, "must be positive"),
    ("n_z_neg_g", {"value": 1.52, "source": "x"}, "must be negative"),
    ("n_z_neg_g", {"value": None}, "null without a reason"),
    ("speed_limit_kt", {"value": 163.0, "source": "x"}, "kind V_NE or V_MO"),
    ("speed_limit_kt", {"value": 163.0, "kind": "Vne", "source": "x"}, "kind V_NE or V_MO"),
    ("speed_limit_kt", {"value": 0.0, "kind": "V_NE", "source": "x"}, "must be positive"),
    ("m_mo", {"value": 1.2, "source": "x"}, "(0, 1)"),
    ("m_mo", {"value": True, "source": "x"}, "finite number"),
    ("m_mo", {"value": float("nan"), "source": "x"}, "finite number"),
    ("alpha_stall_deg", {"value": 95.0, "source": "x"}, "(0, 90)"),
    ("alpha_stall_deg", {"value": 12.0, "source": "x", "kind": "stall"}, "unknown keys"),
    ("alpha_stall_deg", 12.0, "mapping with a 'value'"),
    ("category", {"value": "acrobatic", "regulation": "r", "source": "s"}, "not one of"),
    ("category", {"value": "normal", "regulation": "", "source": "s"}, "regulation and a source"),
    ("vne_kt", {"value": 1.0, "source": "x"}, "unknown keys"),
])
def test_a_malformed_table_refuses_by_name(field, entry, fragment):
    with pytest.raises(LimitsConfigError) as err:
        table(**{field: entry})
    assert err.value.constraint == "limits.config"
    assert str(err.value).startswith("limits.config: test: ")
    assert fragment in err.value.message


def test_a_table_that_omits_a_limit_refuses_and_a_non_mapping_refuses():
    block = {k: v for k, v in BLOCK.items() if k != "m_mo"}
    with pytest.raises(LimitsConfigError, match="missing \\['m_mo'\\]"):
        parse_limits("test", block)
    with pytest.raises(LimitsConfigError, match="must be a mapping"):
        parse_limits("test", [1, 2])


def test_load_limits_refuses_a_malformed_file_by_name(tmp_path):
    bad = dict(BLOCK, n_z_pos_g={"value": 3.8})
    (tmp_path / "x.json").write_text(json.dumps({"name": "x", "limits": bad}), encoding="utf-8")
    with pytest.raises(LimitsConfigError) as err:
        load_limits("x", tmp_path)
    assert err.value.constraint == "limits.config" and err.value.aircraft == "x"
    rec = recorder_from(columns(n_z=[1.0]))
    with pytest.raises(LimitsConfigError):
        monitor_run(rec, "x", tmp_path)


def test_an_airframe_without_a_limits_block_never_refuses(tmp_path):
    (tmp_path / "y.json").write_text(json.dumps({"name": "y"}), encoding="utf-8")
    assert load_limits("y", tmp_path) is None
    assert load_limits("nobody", tmp_path) is None
    rec = recorder_from(columns(n_z=[1.0, 9.0], cas_kt=[900.0, 900.0]))
    block, record = monitor_run(rec, "y", tmp_path)
    assert block == {"monitored": False, "aircraft": "y",
                     "reason": "y.json has no 'limits' block: no limits stated for y"}
    assert record is None
    assert rec.derived == [] and ANY_COLUMN not in rec.columns
    block, record = monitor_run(rec, "nobody", tmp_path)
    assert block["monitored"] is False and "no aircraft config" in block["reason"]


def test_monitor_run_returns_the_block_and_the_record(tmp_path):
    (tmp_path / "z.json").write_text(json.dumps({"name": "z", "limits": BLOCK}),
                                     encoding="utf-8")
    rec = recorder_from(columns(n_z=[1.0, 2.7], cas_kt=[100.0, 100.0], mach=[0.3, 0.3]))
    block, record = monitor_run(rec, "z", tmp_path)
    assert block["monitored"] is True and block["aircraft"] == "z"
    assert block["table"]["limits"]["n_z_pos_g"]["value"] == 2.5
    assert block["summary"]["per_limit"]["n_z_pos_g"]["count"] == 1
    assert block["summary"]["columns_in_output_digest"] is False
    assert block["summary"]["interval_s"] == 0.1
    assert record.name == "limits.monitor"
    assert rec.columns["exceed_nz_pos"] == [0, 1]


# -- the manifest ---------------------------------------------------------------------------

def test_attach_record_creates_the_block_and_refuses_a_repeat():
    cols = columns(n_z=[1.0], cas_kt=[100.0], mach=[0.3])
    record = applied_variable(table(), monitor(cols, table()), None)
    manifest = {}
    attach_record(manifest, record)
    assert [r["name"] for r in read_records(manifest["applied_variables"])] == ["limits.monitor"]
    with pytest.raises(ValueError, match="already recorded"):
        attach_record(manifest, record)
    other = AppliedVariable(name="other.thing", value=1, unit="1", source="user", model="m")
    attach_record(manifest, other)
    assert [r["name"] for r in read_records(manifest["applied_variables"])] == [
        "limits.monitor", "other.thing"]


def _fly(prompt: str):
    spec = compile_prompt(prompt)
    spec.set("hold_state", False)          # open loop: the speed is the trim speed
    with contextlib.redirect_stdout(io.StringIO()):
        return run_spec(spec, assert_closure=False)


@pytest.fixture(scope="module")
def a320_beyond():
    """The JSBSim A320 trims and flies at V_MO + 20 kt (measured)."""
    return _fly("fly the A320 at 1500 m and 370 kt for 5 seconds")


@pytest.fixture(scope="module")
def a320_cruise():
    return _fly("fly the A320 at 1500 m and 250 kt for 5 seconds")


def test_a_real_run_beyond_v_mo_flags_every_sample_and_cruise_flags_none(a320_beyond, a320_cruise):
    """The contract's null test, flown: V_MO + 20 kt against cruise."""
    beyond = a320_beyond.manifest["limits"]
    cruise = a320_cruise.manifest["limits"]
    assert beyond["monitored"] and cruise["monitored"]
    n = beyond["summary"]["samples"]
    assert n == len(a320_beyond.telemetry) >= 40
    assert beyond["summary"]["per_limit"]["speed_limit_kt"]["count"] == n
    assert beyond["summary"]["any_exceedance"]["count"] == n
    assert beyond["summary"]["any_exceedance"]["first_exceedance_s"] == a320_beyond.telemetry.columns["t"][0]
    assert beyond["summary"]["per_limit"]["speed_limit_kt"]["worst_margin"] == pytest.approx(-20.0, abs=0.5)
    assert beyond["summary"]["per_limit"]["n_z_pos_g"]["count"] == 0
    assert beyond["summary"]["per_limit"]["m_mo"]["count"] == 0        # Mach 0.61 at 1500 m
    assert cruise["summary"]["any_exceedance"]["count"] == 0
    assert cruise["summary"]["any_exceedance"]["first_exceedance_s"] is None
    assert cruise["summary"]["per_limit"]["speed_limit_kt"]["worst_margin"] == pytest.approx(100.0, abs=0.5)
    assert set(a320_beyond.telemetry.columns["exceed_vne_or_vmo"]) == {1}
    assert set(a320_cruise.telemetry.columns["exceed_vne_or_vmo"]) == {0}


def test_the_run_manifest_carries_the_block_the_record_and_the_flags_per_frame(a320_beyond, tmp_path):
    manifest = a320_beyond.manifest
    assert manifest["limits"]["config_path"] == "assets/aircraft_config/A320.json"
    assert manifest["limits"]["table"]["category"]["value"] == "transport"
    records = read_records(manifest["applied_variables"])
    assert [r["name"] for r in records] == ["limits.monitor", "scene.geoid_undulation_m"]
    record = records[0]
    assert record["source"] == "derived"
    assert record["model"] == "exceedance monitor against the certification envelope"
    assert record["telemetry_columns"] == manifest["limits"]["summary"]["columns_added"]
    assert record["null_test"]["ok"] is True
    assert record["null_test"]["with"] == len(a320_beyond.telemetry)
    assert record["null_test"]["without"] == 0
    assert "flown beyond" in record["null_test"]["note"]
    # Every per-frame state carries the flags (core.capture.manifest.frame_state, unchanged).
    state = frame_state(a320_beyond.telemetry.columns, 3)
    assert state["exceed_vne_or_vmo"] == 1.0 and state[ANY_COLUMN] == 1.0
    assert state["exceed_nz_pos"] == 0.0
    json.dumps(manifest)
    written = a320_beyond.write(tmp_path / "run")
    telemetry = json.loads((written / "telemetry.json").read_text(encoding="utf-8"))
    # The flags are derived columns; D1's datum channels (undulation_m,
    # hae_m) are derived too and precede them.
    assert telemetry["derived"] == ["undulation_m", "hae_m"] + record["telemetry_columns"]
    assert telemetry["columns"]["exceed_vne_or_vmo"][0] == 1


def test_the_output_digest_covers_the_recorded_telemetry_not_the_flags(a320_cruise):
    """A placard value must not change the digest of a flight it did not
    touch: the digest is taken before the monitor annotates."""
    cols = a320_cruise.telemetry.columns
    derived = set(a320_cruise.telemetry.derived)
    recorded = {k: v for k, v in cols.items() if k not in derived}
    assert derived == {"exceed_nz_pos", "exceed_nz_neg", "exceed_vne_or_vmo",
                       "exceed_mmo", ANY_COLUMN, "undulation_m", "hae_m"}
    assert digest_columns(recorded) == a320_cruise.output_digest
    assert digest_columns(cols) != a320_cruise.output_digest


def test_the_c172p_cannot_be_flown_beyond_v_ne_here_and_says_so():
    """Why the flown null test is the A320's: the c172p aero tables do
    not trim at V_NE + 20 (or + 7), and the refusal is the validator's
    own ``envelope.trim_feasible`` -- nothing in the validator knows
    V_NE. The table's note states this; the test measures it."""
    for kt in (183, 170):
        spec = compile_prompt(f"fly the c172p at 1500 m and {kt} kt for 5 seconds")
        with contextlib.redirect_stdout(io.StringIO()):
            report = validate(spec)
        assert [v.constraint for v in report.violations] == ["envelope.trim_feasible"], kt
    assert "cannot be trimmed above V_NE" in load_limits("c172p").note
    cruise = _fly("fly the c172p at 1500 m and 110 kt for 5 seconds")
    limits = cruise.manifest["limits"]
    assert limits["summary"]["monitored"] == ["n_z_pos_g", "n_z_neg_g", "speed_limit_kt"]
    assert limits["summary"]["any_exceedance"]["count"] == 0
    assert "exceed_mmo" not in cruise.telemetry.columns
    record = read_records(cruise.manifest["applied_variables"])[0]
    assert record["null_test"]["ok"] is True and "flown inside" in record["null_test"]["note"]
