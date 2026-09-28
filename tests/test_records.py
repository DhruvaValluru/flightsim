"""The per-variable record: one shape for every addition (core/records.py).

Record 2 under version 1 (R1): readback, jsbsim_writes, the structured
model block, the provenance text, the uncertainty block and the null
test's KIND -- each optional, each absent from the dict until set, so a
record-1 producer's dict is unchanged to the byte.
"""

import json

import pytest

from core.records import (
    NULL_KINDS, RECORD_VERSION, SOURCES, AppliedVariable, JsbsimWrite, Model, NullTest,
    Readback, check_uncertainty, read_records, records_block,
)


def _variable(**overrides):
    fields = dict(
        name="atmosphere.temperature_deviation_c", value=20.0, unit="degC", source="user",
        model="ISA deviation (US Standard Atmosphere 1976, graded)",
        parameters={"sea_level_delta_t_c": 20.0},
        references=("US Standard Atmosphere 1976", "JSBSim 1.2.4 atmosphere/delta-T"),
        properties_written=("atmosphere/delta-T",),
        telemetry_columns=("density_altitude_m",),
        frame_keys=("density_altitude_m",),
        null_test=NullTest("density altitude at sea level", "m", 693.7, 0.0, 10.0),
        not_claimed=("humidity", "lapse-rate change"),
    )
    fields.update(overrides)
    return AppliedVariable(**fields)


#: The record-1 keys, exactly: a record that sets no record-2 field emits these and no more.
RECORD_1_KEYS = {"name", "value", "unit", "source", "model", "parameters", "references",
                 "properties_written", "telemetry_columns", "frame_keys", "null_test",
                 "not_claimed"}


def test_a_record_1_producer_emits_the_record_1_keys_and_nothing_more():
    record = _variable().to_dict()
    assert set(record) == RECORD_1_KEYS
    assert record["null_test"]["difference"] == pytest.approx(693.7)
    assert record["null_test"]["ok"] is True
    assert record["null_test"]["kind"] == "reached"       # stated on every null test
    json.dumps(record)                                   # serialisable as written


def test_a_null_test_that_measures_nothing_is_not_ok():
    silent = NullTest("peak altitude", "m", 1000.0, 1000.0, 0.5)
    assert silent.difference == 0.0 and silent.ok is False


def test_the_bounded_kind_is_the_opposite_arithmetic():
    """An invariance ("the datum moves no pixel") is ok when the difference
    is AT MOST the bound; the same numbers as ``reached`` are not ok."""
    assert NULL_KINDS == ("reached", "bounded")
    still = NullTest("pixels moved", "px", 0.0, 0.0, 0.5, kind="bounded")
    assert still.ok is True
    moved = NullTest("pixels moved", "px", 2.0, 0.0, 0.5, kind="bounded")
    assert moved.ok is False
    at_bound = NullTest("pixels moved", "px", 0.5, 0.0, 0.5, kind="bounded")
    assert at_bound.ok is True
    reached = NullTest("pixels moved", "px", 2.0, 0.0, 0.5, kind="reached")
    assert reached.ok is True and reached.to_dict()["kind"] == "reached"
    with pytest.raises(ValueError, match="kind"):
        NullTest("x", "m", 1.0, 0.0, 0.5, kind="invariant")
    back = NullTest.from_dict(moved.to_dict())
    assert back == moved
    assert NullTest.from_dict({"quantity": "q", "unit": "m", "with": 1.0, "without": 0.0,
                               "threshold": 0.5}).kind == "reached"   # record 1 meant reached


def test_the_readback_grades_the_property_store_against_its_tolerance():
    exact = Readback("atmosphere/delta-T", value=36.0, written=36.0, tolerance=0.0,
                     basis="measured exact")
    assert exact.agrees is True and exact.difference == 0.0
    off = Readback("atmosphere/delta-T", value=36.5, written=36.0, tolerance=0.0,
                   basis="measured exact")
    assert off.agrees is False
    relative = Readback("atmosphere/RH", value=0.49999996684, written=0.5, tolerance=1e-6,
                        tolerance_kind="relative", basis="Magnus round trip")
    assert relative.agrees is True
    too_far = Readback("atmosphere/RH", value=0.5 + 1e-5, written=0.5, tolerance=1e-6,
                       tolerance_kind="relative", basis="Magnus round trip")
    assert too_far.agrees is False
    d = relative.to_dict()
    assert set(d) == {"property", "value", "written", "agrees", "tolerance", "tolerance_kind",
                      "basis"}
    assert Readback.from_dict(d) == relative
    with pytest.raises(ValueError, match="kind"):
        Readback("p", 1.0, 1.0, 0.0, tolerance_kind="fuzzy")
    with pytest.raises(ValueError, match="negative"):
        Readback("p", 1.0, 1.0, -1.0)


def test_record_2_fields_ride_only_when_set_and_round_trip():
    record = _variable(
        frm="hot day", std="MIL-HDBK-310 1 % hot column",
        readback=Readback("atmosphere/delta-T", 36.0, 36.0, 0.0, basis="exact"),
        jsbsim_writes=(JsbsimWrite("atmosphere/delta-T", "before trim and every step"),),
        model_block=Model("ISA deviation", standard="US Standard Atmosphere 1976",
                          version="bias route", parameters={"delta_t_c": 20.0},
                          references=("USSA 1976",)),
        uncertainty={"u_input": {"value": 2.89, "unit": "degC", "rule": "inferred",
                                 "sensitivity": {"altitude_m": 0.0}},
                     "u_num": {"srq": "altitude_m", "value": 0.01, "basis": "dt/2 twin"}},
    )
    d = record.to_dict()
    assert set(d) == RECORD_1_KEYS | {"from", "std", "readback", "jsbsim_writes", "model_block",
                                      "uncertainty"}
    assert d["model"] == "ISA deviation (US Standard Atmosphere 1976, graded)"   # the string stays
    assert d["model_block"]["name"] == "ISA deviation"
    assert d["jsbsim_writes"] == [{"property": "atmosphere/delta-T",
                                   "when": "before trim and every step"}]
    assert d["readback"]["agrees"] is True
    back = AppliedVariable.from_dict(json.loads(json.dumps(d)))
    assert back == record
    assert AppliedVariable.from_dict(_variable().to_dict()) == _variable()   # record 1 reads too


def test_a_jsbsim_write_must_be_a_property_the_record_says_it_wrote():
    with pytest.raises(ValueError, match="properties_written"):
        _variable(jsbsim_writes=(JsbsimWrite("atmosphere/P-sl-psf", "before trim"),))
    with pytest.raises(ValueError, match="when"):
        JsbsimWrite("atmosphere/delta-T", "")
    with pytest.raises(ValueError, match="name"):
        Model("")


def test_the_uncertainty_block_is_shape_checked():
    assert check_uncertainty({"u_input": None, "u_num": None}) == {"u_input": None, "u_num": None}
    with pytest.raises(ValueError, match="unknown"):
        check_uncertainty({"u_total": 1.0})
    with pytest.raises(ValueError, match="missing"):
        check_uncertainty({"u_num": {"value": 1.0}})
    with pytest.raises(ValueError, match="missing"):
        _variable(uncertainty={"u_input": {"value": 1.0}})


def test_the_block_round_trips_and_refuses_a_foreign_version():
    block = records_block([_variable(), _variable(name="mass.payload_kg", value=120.0,
                                                   unit="kg", null_test=None)])
    assert block["record_version"] == RECORD_VERSION == 1      # the integrator bumps, not R1
    names = [r["name"] for r in read_records(json.loads(json.dumps(block)))]
    assert names == ["atmosphere.temperature_deviation_c", "mass.payload_kg"]
    with pytest.raises(ValueError, match="record_version"):
        read_records({"record_version": RECORD_VERSION + 1, "applied_variables": []})


def test_a_record_needs_a_known_source_and_a_model():
    with pytest.raises(ValueError, match="source"):
        _variable(source="guessed")
    with pytest.raises(ValueError, match="model"):
        _variable(model="")
    with pytest.raises(ValueError, match="repeat"):
        records_block([_variable(), _variable()])
    assert SOURCES[0] == "user" and SOURCES[-1] == "default"
