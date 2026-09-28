"""The null pair (core/record_null.py): the identical case at the null
value, the effect per channel against the V9 floors, the digests, the
verdict, the refusals by name -- on a fake runner for the arithmetic and
on the real c172p for one measured pair.
"""

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import pytest

from core.record_null import (
    FLOORS_BY_UNIT, KT_TO_MPS, NULL_FLOOR_ALTITUDE_M, NULL_FLOOR_ANGLE_DEG,
    NULL_FLOOR_REFERENCE, NULL_FLOOR_SPEED_KT, ChannelEffect, NullPair, attach_null_pair,
    floor_for_unit, null_pairs_block, null_pairs_for_spec, null_spec_dict, run_null_pair,
)
from core.records import JsbsimWrite
from core.registry import (
    NO_NULL, REGISTRY, EffectChannel, ReadbackTolerance, RecordError, Registry, VariableRecord,
)
from core.scenario.spec import ScenarioSpec

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/cameras_waypoint.yaml"


# -- a test registry over a spec-8 field, so the mechanics run today -------------

def wind_registry() -> Registry:
    """``environment.wind_speed`` stands in for a registered spec field:
    the atmosphere block's fields do not exist in spec 8 yet."""
    return Registry((VariableRecord(
        name="environment.wind_speed", spec_path="environment.wind_speed", unit="kt",
        jsbsim_writes=(JsbsimWrite("atmosphere/wind-north-fps", "every step"),
                       JsbsimWrite("atmosphere/wind-east-fps", "every step")),
        effect_channels=(EffectChannel("wind_speed_mps", "m/s"), EffectChannel("lat_deg", "deg"),
                         EffectChannel("altitude_m", "m"), EffectChannel("mach", "1")),
        null_value=0.0, null_basis="still air",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", "test entry")),))


@dataclass
class FakeResult:
    spec_digest: str
    output_digest: str
    telemetry: Any


class FakeTelemetry:
    def __init__(self, columns: Dict[str, list]) -> None:
        self.columns = columns


def fake_runner(spec):
    """Wind speed w kt -> wind_speed_mps = w x KT_TO_MPS on every sample,
    a latitude drift of 1e-5 deg per kt, altitude untouched."""
    w = float(spec.wind_speed.value)
    n = 5
    cols = {"t": [0.1 * i for i in range(n)],
            "wind_speed_mps": [w * KT_TO_MPS] * n,
            "lat_deg": [1e-5 * w * i for i in range(n)],
            "altitude_m": [1000.0] * n,
            "mach": [0.2] * n}
    return FakeResult(spec.digest(), f"out-{w:g}", FakeTelemetry(cols))


def spec_with_wind(kt: float) -> ScenarioSpec:
    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("duration", 1.0)
    spec.set("wind_speed", kt)
    return spec


# -- the floors ----------------------------------------------------------------------

def test_the_floors_are_ten_times_the_v9_noise_with_the_reference_stated():
    assert NULL_FLOOR_ALTITUDE_M == 0.5
    assert NULL_FLOOR_ANGLE_DEG == 0.05
    assert NULL_FLOOR_SPEED_KT == 0.1
    assert "V9" in NULL_FLOOR_REFERENCE and "0.098" in NULL_FLOOR_REFERENCE
    assert floor_for_unit("m") == 0.5 and floor_for_unit("deg") == 0.05
    assert floor_for_unit("kt") == 0.1
    assert floor_for_unit("m/s") == pytest.approx(0.1 * KT_TO_MPS)
    assert floor_for_unit("1") is None                # a ratio has no stated floor
    assert FLOORS_BY_UNIT["m"] == NULL_FLOOR_ALTITUDE_M
    # The atmosphere's own channels: a stated tenth of a unit, said so.
    assert floor_for_unit("K") == 0.1 and floor_for_unit("%") == 0.1
    assert floor_for_unit("hPa") == 0.1 and floor_for_unit("Pa") == 1.0
    assert "stated" in NULL_FLOOR_REFERENCE and "0.1 K" in NULL_FLOOR_REFERENCE


def test_an_effect_below_its_floor_is_not_reached_and_no_floor_is_ungraded():
    below = ChannelEffect("altitude_m", "m", peak_abs=0.3, rms=0.1, floor=0.5, samples=5,
                          peak_index=0, with_at_peak=1000.3, without_at_peak=1000.0)
    assert below.reached is False
    above = ChannelEffect("altitude_m", "m", 0.6, 0.2, 0.5, 5, 0, 1000.6, 1000.0)
    assert above.reached is True
    none = ChannelEffect("mach", "1", 0.6, 0.2, None, 5, 0, 0.8, 0.2)
    assert none.reached is None and none.to_dict()["reached"] is None


# -- the null spec ---------------------------------------------------------------------

def test_the_null_spec_sets_the_field_to_the_null_value_or_removes_it():
    reg = wind_registry()
    data = spec_with_wind(10.0).to_dict()
    null = null_spec_dict(data, reg.get("environment.wind_speed"))
    assert null["environment"]["wind_speed"]["value"] == 0.0
    assert null["environment"]["wind_speed"]["unit"] == "kt"
    assert null["environment"]["wind_speed"]["source"] == "derived"
    assert "null pair" in null["environment"]["wind_speed"]["from"]
    assert data["environment"]["wind_speed"]["value"] == 10.0        # the input is untouched
    ScenarioSpec.from_dict(null)                                        # still a spec
    # A null of None is the field UNSTATED (value null), not removed: every
    # provenanced block lists all its fields, so a removed key is not a spec.
    absent = Registry((VariableRecord(name="x.y", spec_path="x.y", unit="m", null_value=None,
                                      null_basis="absent is off"),))
    out = null_spec_dict({"x": {"y": {"value": 3.0, "unit": "m"}}}, absent.get("x.y"))
    assert out == {"x": {"y": {"value": None, "unit": "m", "source": "derived",
                               "from": "null pair: x.y unstated (absent is off)"}}}


def test_the_null_spec_refusals_by_name():
    reg = wind_registry()
    entry = reg.get("environment.wind_speed")
    with pytest.raises(RecordError) as err:            # the stated value IS the null
        null_spec_dict(spec_with_wind(0.0).to_dict(), entry)
    assert err.value.constraint == "record.null_value"
    with pytest.raises(RecordError) as err:            # the spec states no such field
        null_spec_dict({"environment": {}}, entry)
    assert err.value.constraint == "record.null_value"
    with pytest.raises(RecordError) as err:            # no spec field at all
        null_spec_dict({}, REGISTRY.get("limits.monitor"))
    assert err.value.constraint == "record.null_value"
    with pytest.raises(RecordError) as err:            # not registered
        run_null_pair(spec_with_wind(10.0), "environment.nothing", runner=fake_runner, registry=reg)
    assert err.value.constraint == "record.unregistered"


def test_a_pair_needs_effect_channels_the_run_recorded():
    no_channels = Registry((VariableRecord(
        name="environment.wind_speed", spec_path="environment.wind_speed", unit="kt",
        null_value=0.0, null_basis="still air"),))
    with pytest.raises(RecordError) as err:
        run_null_pair(spec_with_wind(10.0), "environment.wind_speed", runner=fake_runner,
                      registry=no_channels)
    assert err.value.constraint == "record.effect_channel"
    unrecorded = Registry((VariableRecord(
        name="environment.wind_speed", spec_path="environment.wind_speed", unit="kt",
        effect_channels=(EffectChannel("density_altitude_m", "m"),),
        null_value=0.0, null_basis="still air"),))
    with pytest.raises(RecordError) as err:
        run_null_pair(spec_with_wind(10.0), "environment.wind_speed", runner=fake_runner,
                      registry=unrecorded)
    assert err.value.constraint == "record.effect_channel"
    assert "did not record" in str(err.value)


# -- the pair on the fake runner -----------------------------------------------------

def test_the_pair_measures_each_channel_against_its_floor_and_carries_both_digests():
    reg = wind_registry()
    pair = run_null_pair(spec_with_wind(10.0), "environment.wind_speed", runner=fake_runner,
                         registry=reg)
    d = pair.to_dict()
    assert pair.applied_value == 10.0 and pair.null_value == 0.0
    assert pair.with_output_digest == "out-10" and pair.without_output_digest == "out-0"
    assert pair.digests_differ and d["digests"]["differ"] is True
    assert pair.with_spec_digest != pair.without_spec_digest
    wind = d["effect"]["wind_speed_mps"]
    assert wind["peak_abs"] == pytest.approx(10.0 * KT_TO_MPS)
    assert wind["rms"] == pytest.approx(10.0 * KT_TO_MPS)
    assert wind["floor"] == pytest.approx(0.1 * KT_TO_MPS) and wind["reached"] is True
    lat = d["effect"]["lat_deg"]
    assert lat["peak_abs"] == pytest.approx(4e-4) and lat["reached"] is False   # below 0.05 deg
    assert d["effect"]["altitude_m"]["peak_abs"] == 0.0
    assert d["effect"]["altitude_m"]["reached"] is False
    assert d["effect"]["mach"]["reached"] is None                              # no floor: ungraded
    assert pair.verdict == "reached" and d["verdict"] == "reached"
    assert pair.strongest.channel == "wind_speed_mps"
    null = pair.null_test()
    assert null.kind == "reached" and null.ok is True
    assert null.with_value == pytest.approx(10.0 * KT_TO_MPS) and null.without_value == 0.0
    assert d["floors"]["reference"] == NULL_FLOOR_REFERENCE
    assert d["null_test"]["ok"] is True


def test_a_silent_variable_reads_silent_and_the_strongest_is_relative_to_the_floor():
    """A runner that ignores the wind: every graded channel below its
    floor, the verdict silent, the null test not ok."""
    def deaf(spec):
        r = fake_runner(spec)
        r.telemetry.columns["wind_speed_mps"] = [0.0] * 5
        r.telemetry.columns["lat_deg"] = [0.0] * 5
        r.output_digest = "same"
        return r
    pair = run_null_pair(spec_with_wind(10.0), "environment.wind_speed", runner=deaf,
                         registry=wind_registry())
    assert pair.verdict == "silent" and not pair.digests_differ
    assert pair.null_test().ok is False
    ungraded = NullPair("v", "a.b", 1, 0, "s", "o", "s2", "o2",
                        (ChannelEffect("mach", "1", 0.3, 0.1, None, 5, 0, 0.5, 0.2),), 0.0)
    assert ungraded.verdict == "ungraded"
    assert ungraded.null_test().threshold == 0.0 and "no floor" in ungraded.null_test().note


def test_a_heading_difference_is_wrapped_and_ragged_lengths_are_noted():
    reg = Registry((VariableRecord(
        name="environment.wind_speed", spec_path="environment.wind_speed", unit="kt",
        effect_channels=(EffectChannel("heading_deg", "deg"),),
        null_value=0.0, null_basis="still air"),))

    def wrap(spec):
        w = float(spec.wind_speed.value)
        n = 5 if w else 4
        return FakeResult("s", f"o{w}", FakeTelemetry(
            {"t": [0.0] * n, "heading_deg": [359.0 if w else 1.0] * n}))
    pair = run_null_pair(spec_with_wind(10.0), "environment.wind_speed", runner=wrap, registry=reg)
    eff = pair.effects[0]
    assert eff.peak_abs == pytest.approx(2.0) and eff.samples == 4
    assert any("5 with vs 4 without" in n for n in pair.notes)


def test_pairs_for_a_spec_run_only_the_registered_fields_it_states_off_null():
    reg = wind_registry()
    assert null_pairs_for_spec(spec_with_wind(0.0), runner=fake_runner, registry=reg) == {}
    pairs = null_pairs_for_spec(spec_with_wind(10.0), runner=fake_runner, registry=reg)
    assert list(pairs) == ["environment.wind_speed"]
    block = null_pairs_block(pairs)
    assert block["environment.wind_speed"]["verdict"] == "reached"
    # The committed example against the REAL registry (W1 registered the
    # environment section): the 10 kt wind is the one field off its null,
    # so exactly the wind pair runs -- the fake runner records every
    # channel the real entry names (wind_speed_mps, lat_deg, altitude_m).
    assert list(null_pairs_for_spec(spec_with_wind(10.0), runner=fake_runner)) == [
        "environment.wind_speed"]


def test_attach_null_pair_writes_into_the_variables_record_or_says_it_could_not():
    reg = wind_registry()
    pair = run_null_pair(spec_with_wind(10.0), "environment.wind_speed", runner=fake_runner,
                         registry=reg)
    manifest = {"applied_variables": {"record_version": 1, "applied_variables": [
        {"name": "environment.wind_speed", "null_test": None},
        {"name": "limits.monitor", "null_test": {"ok": True}}]}}
    assert attach_null_pair(manifest, pair) is True
    written = manifest["applied_variables"]["applied_variables"][0]["null_test"]
    assert written["kind"] == "reached" and written["verdict"] == "reached"
    assert written["digests"]["differ"] is True and "wind_speed_mps" in written["effect"]
    assert manifest["applied_variables"]["applied_variables"][1]["null_test"] == {"ok": True}
    assert attach_null_pair({}, pair) is False


# -- one real pair on the c172p ----------------------------------------------------------

@pytest.mark.timeout(300)
def test_a_real_null_pair_on_the_c172p_reaches_the_wind_channel():
    """Two one-second flights of examples/cameras_waypoint.yaml, 10 kt wind
    against still air: the wind channel moves by 10 kt (5.14 m/s, far
    over the 0.05 m/s floor), the output digests differ, altitude moves
    0.80 m (measured: the wind is present at trim, so the trimmed state
    itself differs -- above the 0.5 m floor), and the pair costs seconds,
    not minutes (measured 2.2 s; the timing is printed for the report)."""
    spec = spec_with_wind(10.0)
    with contextlib.redirect_stdout(io.StringIO()):
        pair = run_null_pair(spec, "environment.wind_speed", registry=wind_registry())
    d = pair.to_dict()
    assert pair.verdict == "reached" and pair.digests_differ
    assert d["effect"]["wind_speed_mps"]["peak_abs"] == pytest.approx(10.0 * KT_TO_MPS, rel=1e-6)
    assert d["effect"]["wind_speed_mps"]["reached"] is True
    assert d["effect"]["altitude_m"]["unit"] == "m"
    assert pair.null_test().ok is True
    assert pair.elapsed_s < 60.0
    print(f"null pair c172p 1 s: {pair.elapsed_s:.2f} s; altitude peak "
          f"{d['effect']['altitude_m']['peak_abs']:.4f} m; lat peak "
          f"{d['effect']['lat_deg']['peak_abs']:.2e} deg")
