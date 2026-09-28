"""The per-variable record: one shape for every addition (core/records.py)."""

import json

import pytest

from core.records import (
    RECORD_VERSION, SOURCES, AppliedVariable, NullTest, read_records, records_block,
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


def test_a_record_carries_every_field_the_gap_analysis_asks_for():
    record = _variable().to_dict()
    assert set(record) == {"name", "value", "unit", "source", "model", "parameters",
                           "references", "properties_written", "telemetry_columns",
                           "frame_keys", "null_test", "not_claimed"}
    assert record["null_test"]["difference"] == pytest.approx(693.7)
    assert record["null_test"]["ok"] is True
    json.dumps(record)                                   # serialisable as written


def test_a_null_test_that_measures_nothing_is_not_ok():
    silent = NullTest("peak altitude", "m", 1000.0, 1000.0, 0.5)
    assert silent.difference == 0.0 and silent.ok is False


def test_the_block_round_trips_and_refuses_a_foreign_version():
    block = records_block([_variable(), _variable(name="mass.payload_kg", value=120.0,
                                                   unit="kg", null_test=None)])
    assert block["record_version"] == RECORD_VERSION
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
