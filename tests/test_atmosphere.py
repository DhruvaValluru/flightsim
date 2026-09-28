"""P1, the non-standard atmosphere and humidity: a stated day written
before the trim and every step, read back, recorded per variable, and
measured against the closed form transcribed from JSBSim's own source.

Every number asserted here was measured in the container on 2026-09-28
against JSBSim 1.2.4 in .venv (c172p at 1500 m, A320 at 6000 m): the
closed form reproduces the delivered density, temperature, pressure and
the density/pressure altitudes to about 1e-13 relative when the
atmosphere is recomputed between writes; the hot day moves the trimmed
throttle and the fixed-throttle climb rate; the properties read back
exactly on every step; the committed spec-8 examples keep their digests.

What is NOT claimed: that JSBSim's standard day equals the 1976 tables
(taken on the source's word); any MIL-HDBK-310 profile; the engine side
(the card block is pinned, nothing applies it here).
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from core.environment import atmosphere as atm
from core.environment.atmosphere import (
    CARD_KEYS, PROPERTY_DELTA_T, PROPERTY_DEW_POINT, PROPERTY_P_SL,
    TELEMETRY_COLUMNS, AtmosphereError, NonStandardAtmosphere, closed_form,
    expected_density_ratio,
)
from core.environment.stack import EnvironmentStack
from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u
from core.nl.compiler import compile_prompt
from core.record_null import null_pairs_for_spec, null_spec_dict, run_null_pair
from core.records import read_records
from core.registry import REGISTRY
from core.scenario.blocks import (
    ATMOSPHERE_RANGES, DAY_STANDARDS, DAY_WORDS, NAMED_PROFILES, AtmosphereSpec,
)
from core.scenario.card import atmosphere_card_block, write_run_card
from core.scenario.fields import Source
from core.scenario.runner import configure_from_spec, run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_atmosphere
from core.telemetry.recorder import DEFAULT_CHANNELS

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
#: The closed form must agree with the delivered atmosphere to this.
CLOSED_FORM_TOLERANCE = 0.005
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
#: (aircraft, altitude m, CAS kt): the two airframes the item measures on.
CASES = (("c172p", 1500.0, 100.0), ("A320", 6000.0, 250.0))
#: (temperature deviation, sea-level pressure, dew point, relative humidity).
#: Dew points sit below the modelled temperature at BOTH scene altitudes
#: (ISA -3.96 degC at 6000 m on the +20 day; -84 degC on the -60 day).
DAYS = ((30.0, None, None, None), (-40.0, None, None, None),
        (20.0, 990.0, -10.0, None), (0.0, None, None, 90.0),
        (45.0, 1085.0, None, None), (-60.0, 870.0, -90.0, None))


def spec_for(aircraft="c172p", altitude_m=1500.0, cas_kt=100.0, seconds=3,
             hold_state=False, **atmosphere) -> ScenarioSpec:
    """A compiled spec with the atmosphere fields stated through the
    spec's own front door. ``hold_state`` is False by default: the
    compiler's default (True) engages the autopilot, whose sign probe
    trims every airframe at a fixed 6000 m / 280 kt -- outside the
    c172p's envelope (measured: 'udot doesn't appear to be trimmable'
    at HEAD, independent of this item)."""
    spec = compile_prompt(f"fly the {aircraft} at {altitude_m:g} m and "
                          f"{cas_kt:g} kt for {seconds} seconds")
    spec.set("hold_state", hold_state, frm="test")
    for name, value in atmosphere.items():
        spec.set(f"atmosphere.{name}", value, frm="test")
    return spec


def fdm_at(aircraft, altitude_m, cas_kt) -> FlightDynamics:
    fdm = FlightDynamics(aircraft)
    fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(altitude_m),
                                "vc-kts": cas_kt, **LEVEL})
    return fdm


def names(violations):
    return [v.constraint for v in violations]


def constraints(**atmosphere):
    return names(validate_atmosphere(spec_for(**atmosphere)))


# -- the closed form against the installed JSBSim -----------------------------------

@pytest.mark.parametrize("aircraft,altitude_m,cas_kt", CASES)
@pytest.mark.parametrize("dt_c,p_sl_hpa,dew_c,rh_pct", DAYS)
def test_closed_form_reproduces_the_delivered_atmosphere(aircraft, altitude_m,
                                                         cas_kt, dt_c, p_sl_hpa,
                                                         dew_c, rh_pct):
    """The provider's own prepare on a real FDM: density, temperature,
    pressure, the two altitudes, humidity and vapour pressure agree with
    the transcribed equations to 0.5 % (measured: about 1e-13 relative).
    Measured, not asserted -- the tolerance is the claim."""
    fdm = fdm_at(aircraft, altitude_m, cas_kt)
    provider = NonStandardAtmosphere(dt_c, p_sl_hpa, dew_c, rh_pct,
                                     reference_altitude_m=altitude_m)
    report = provider.prepare(fdm)
    delivered, predicted = report["after"], report["predicted"]
    for key in ("density_kgm3", "temperature_k", "pressure_hpa", "rh_pct",
                "vapour_pressure_pa"):
        scale = max(1.0, abs(predicted[key]))
        assert abs(delivered[key] - predicted[key]) <= CLOSED_FORM_TOLERANCE * scale, key
    for key in ("density_altitude_m", "pressure_altitude_m"):
        assert abs(delivered[key] - predicted[key]) <= max(
            1.0, CLOSED_FORM_TOLERANCE * abs(predicted[key])), key
    # And the null pair is a real difference whenever a variable is stated.
    assert delivered["density_kgm3"] != report["before"]["density_kgm3"]


def test_expected_density_ratio_is_the_delivered_density_over_the_isa_sea_level():
    """The predicted side of the null test: sigma on the hot day equals
    JSBSim's delivered density over its standard sea-level density,
    within 0.5 % (measured 1e-13). JSBSim's own ``atmosphere/sigma``
    divides by the DAY's sea-level density (measured 1.0 at sea level
    on the hot day) and is deliberately not the number compared."""
    fdm = fdm_at("c172p", 1500.0, 100.0)
    provider = NonStandardAtmosphere(30.0, reference_altitude_m=1500.0)
    report = provider.prepare(fdm)
    rho_isa_sl = u.slugft3_to_kgm3(atm.P_SL_PSF / (atm.R_DRY * atm.T_SL_R))
    measured = report["after"]["density_kgm3"] / rho_isa_sl
    predicted = expected_density_ratio(30.0, altitude_m=1500.0)
    assert abs(measured - predicted) <= CLOSED_FORM_TOLERANCE * predicted
    assert predicted < expected_density_ratio(0.0, altitude_m=1500.0)
    assert closed_form(0.0)["sigma"] == pytest.approx(1.0)


def test_the_standard_day_of_the_closed_form_is_jsbsims():
    """ISA at three altitudes: the transcription reproduces JSBSim's own
    density, pressure and temperature to 1e-9 relative (JSBSim's tables
    are taken as the 1976 standard on the source's word: not compared
    with the published tables here, and said so)."""
    for altitude_m in (0.0, 3000.0, 11000.0):
        fdm = fdm_at("c172p", altitude_m, 100.0)
        g = fdm.props.get
        form = closed_form(altitude_m)
        assert form["density_kgm3"] == pytest.approx(
            u.slugft3_to_kgm3(g("atmosphere/rho-slugs_ft3")), rel=1e-9)
        assert form["pressure_pa"] == pytest.approx(u.psf_to_pa(g("atmosphere/P-psf")), rel=1e-9)
        assert form["temperature_k"] == pytest.approx(
            u.rankine_to_kelvin(g("atmosphere/T-R")), rel=1e-9)
        assert form["density_altitude_m"] == pytest.approx(altitude_m, abs=1e-6)


def test_magnus_constants_reproduce_jsbsims_saturated_vapour_pressure():
    """35.540351 psf at 518.67 R, as the live model reports it (the
    psf-to-Pa factor is JSBSim's own 47.88 there, not the exact one)."""
    fdm = fdm_at("c172p", 0.0, 100.0)
    assert atm.saturated_vapour_pressure_psf(518.67) == pytest.approx(
        fdm.props.get("atmosphere/saturated-vapor-pressure-psf"), rel=1e-9)
    assert fdm.props.get("atmosphere/saturated-vapor-pressure-psf") == pytest.approx(35.540351, abs=1e-6)


# -- JSBSim's silent caps, measured, and the refusals that replace them -------------

def test_jsbsim_caps_a_dew_point_above_the_temperature_and_prints():
    """The defect the refusal replaces: dew-point-R 540 written at ISA sea
    level (518.67 R) reads back 518.67, RH 100 %, and a line is printed
    to the C++ stderr (not raised, not recorded)."""
    fdm = fdm_at("c172p", 0.0, 100.0)
    fdm.props.set("atmosphere/dew-point-R", 540.0)
    fdm._exec.run_ic()
    assert fdm.props.get("atmosphere/dew-point-R") == pytest.approx(518.67, abs=1e-6)
    assert fdm.props.get("atmosphere/RH") == pytest.approx(100.0, abs=1e-6)


def test_a_dew_point_above_the_scene_temperature_is_refused_by_name():
    """ISA at 1500 m is 5.25 degC: a dew point of 20 degC there is refused
    atmosphere.dew_point at validation and by the provider; 5 degC is not."""
    assert constraints(dew_point_c=20.0) == ["atmosphere.dew_point"]
    assert constraints(dew_point_c=5.0) == []
    with pytest.raises(AtmosphereError) as caught:
        NonStandardAtmosphere(dew_point_c=20.0, reference_altitude_m=1500.0)
    assert caught.value.constraint == "atmosphere.dew_point"
    assert caught.value.limit == pytest.approx(5.25, abs=0.02)
    # With the hot day the scene is 35.25 degC and 20 degC is fine.
    assert constraints(dew_point_c=20.0, day="hot_day") == []


def test_a_dew_point_beyond_the_vapour_cap_is_refused_by_name():
    """+45 degC and 100 % humidity at sea level asks for about 153000 ppm
    of water by mass; JSBSim's table admits 35000 ppm there and would cap
    silently. Refused atmosphere.dew_point, with the cap's dew point as
    the limit."""
    refused = validate_atmosphere(spec_for(altitude_m=100.0, cas_kt=100.0,
                                           temperature_deviation_c=45.0,
                                           relative_humidity_pct=100.0))
    assert names(refused) == ["atmosphere.dew_point"]
    assert "ppm" in refused[0].message and refused[0].limit < refused[0].actual
    assert atm.max_vapour_mass_fraction(0.0) == pytest.approx(0.035)


def test_dew_point_and_humidity_together_are_refused_by_name():
    assert constraints(dew_point_c=2.0, relative_humidity_pct=50.0) == [
        "atmosphere.humidity_conflict"]
    with pytest.raises(AtmosphereError, match="humidity_conflict"):
        NonStandardAtmosphere(dew_point_c=2.0, relative_humidity_pct=50.0)


@pytest.mark.parametrize("field,value,name", [
    ("temperature_deviation_c", -60.5, "atmosphere.temperature_deviation"),
    ("temperature_deviation_c", 45.5, "atmosphere.temperature_deviation"),
    ("sea_level_pressure_hpa", 869.9, "atmosphere.sea_level_pressure"),
    ("sea_level_pressure_hpa", 1085.1, "atmosphere.sea_level_pressure"),
    ("relative_humidity_pct", -0.1, "atmosphere.dew_point"),
    ("relative_humidity_pct", 100.1, "atmosphere.dew_point"),
    ("dew_point_c", -90.5, "atmosphere.dew_point"),
    ("temperature_deviation_c", "hot", "atmosphere.temperature_deviation"),
])
def test_out_of_range_values_are_refused_by_name(field, value, name):
    refused = validate_atmosphere(spec_for(**{field: value}))
    assert names(refused) == [name]
    assert refused[0].actual == value


def test_the_range_bounds_are_inclusive_and_stated():
    assert ATMOSPHERE_RANGES == {
        "temperature_deviation_c": (-60.0, 45.0),
        "sea_level_pressure_hpa": (870.0, 1085.0),
        "relative_humidity_pct": (0.0, 100.0),
        "dew_point_c": (-90.0, 60.0)}
    assert constraints(temperature_deviation_c=-60.0, sea_level_pressure_hpa=870.0) == []
    assert constraints(temperature_deviation_c=45.0, sea_level_pressure_hpa=1085.0) == []
    assert constraints(relative_humidity_pct=100.0) == []
    assert constraints(relative_humidity_pct=0.0) == []
    # RH 0 is dry air: no dew point, nothing to write (the Magnus floor
    # is a pole; JSBSim's own floor reads back a different value).
    assert atm.dew_point_c_from_humidity(0.0, 15.0) is None
    dry = NonStandardAtmosphere(relative_humidity_pct=0.0, reference_altitude_m=1500.0)
    assert dry.dew_point_r is None and dry.writes_at(1500.0) == {}


@pytest.mark.parametrize("word", NAMED_PROFILES + ("banana",))
def test_a_named_profile_or_an_unknown_day_word_is_refused_by_name(word):
    refused = validate_atmosphere(spec_for(day=word))
    assert names(refused) == ["atmosphere.profile"]
    assert word in refused[0].message
    if word in NAMED_PROFILES:
        assert "not been transcribed" in refused[0].message


def test_every_day_word_validates_and_carries_its_citation():
    for word in DAY_WORDS:
        assert constraints(day=word) == [], word
        assert DAY_STANDARDS[word]
    assert DAY_WORDS["hot_day"] == {"temperature_deviation_c": 30.0}
    assert DAY_WORDS["cold_day"] == {"temperature_deviation_c": -40.0}
    assert DAY_WORDS["humid"] == {"relative_humidity_pct": 90.0}
    terms = {t.phrase for t in NonStandardAtmosphere(30.0).vocabulary()}
    assert set(DAY_WORDS) <= terms and set(NAMED_PROFILES) <= terms


def test_the_whole_validator_names_the_atmosphere_refusal_and_stays_feasible():
    report = validate(spec_for(dew_point_c=20.0), check_feasibility=False)
    assert names(report.violations) == ["atmosphere.dew_point"]
    assert validate(spec_for(day="hot_day")).ok


# -- the spec block -------------------------------------------------------------------

def _canonical_digest(payload) -> str:
    payload = dict(payload)
    payload.pop("prompt", None)
    payload.pop("notes", None)
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _spec_examples():
    """The committed examples that ARE specs (batch_matrix.yaml is a batch)."""
    return sorted(p.name for p in EXAMPLES.glob("*.yaml")
                  if "spec_version" in yaml.safe_load(p.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", _spec_examples())
def test_a_committed_spec_8_example_keeps_its_canonical_form_and_digest(name):
    """Absent is canonical: the block adds no key to a spec that states
    none of it, so every committed example's digest is the digest of its
    own file (the rule re-implemented here) and unchanged."""
    frozen = yaml.safe_load(EXAMPLES.joinpath(name).read_text(encoding="utf-8"))
    assert "atmosphere" not in frozen
    spec = ScenarioSpec.from_dict(copy.deepcopy(frozen))
    assert spec.atmosphere.is_default()
    assert "atmosphere" not in spec.to_dict()
    assert spec.digest() == _canonical_digest(frozen)


def test_a_stated_block_round_trips_and_changes_the_digest(tmp_path):
    spec = spec_for(day="hot_day", sea_level_pressure_hpa=1000.0)
    before = spec_for().digest()
    assert spec.digest() != before
    path = spec.write(tmp_path / "s.yaml")
    reread = ScenarioSpec.read(path)
    assert reread.digest() == spec.digest()
    assert reread.atmosphere.day.value == "hot_day"
    assert reread.atmosphere.sea_level_pressure_hpa.source is Source.USER
    assert reread.to_dict()["atmosphere"] == spec.to_dict()["atmosphere"]
    assert list(reread.to_dict()["atmosphere"]) == list(AtmosphereSpec.FIELD_ORDER)


def test_the_block_is_behind_the_specs_own_front_door():
    spec = spec_for()
    spec.set("atmosphere.temperature_deviation_c", 12.0, frm="stated")
    assert spec.atmosphere.temperature_deviation_c.source is Source.USER
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("atmosphere.temperature_deviation_c", 1.0, frm="planner")
    spec.plan("atmosphere.sea_level_pressure_hpa", 1000.0, frm="planner")
    assert spec.atmosphere.sea_level_pressure_hpa.source is Source.DERIVED
    with pytest.raises(ValueError, match="not a atmosphere field"):
        spec.set("atmosphere.lapse_rate", 1.0)
    data = spec.to_dict()
    data["atmosphere"]["lapse_rate"] = {"value": 1.0, "source": "user"}
    with pytest.raises(ValueError, match="unknown fields"):
        ScenarioSpec.from_dict(data)
    assert "temperature deviation c" in spec.render_table()


def test_a_day_word_fills_only_defaulted_fields_and_a_number_wins():
    block = spec_for(day="hot_day").atmosphere.resolved()
    assert block["temperature_deviation_c"].value == 30.0
    assert block["temperature_deviation_c"].source is Source.INFERRED
    assert block["temperature_deviation_c"].frm == "day: hot_day"
    assert block["temperature_deviation_c"].std == DAY_STANDARDS["hot_day"]
    stated = spec_for(day="hot_day", temperature_deviation_c=10.0).atmosphere.resolved()
    assert stated["temperature_deviation_c"].value == 10.0
    assert stated["temperature_deviation_c"].source is Source.USER
    humid = spec_for(day="humid").atmosphere.resolved()
    assert humid["relative_humidity_pct"].value == 90.0
    dew_stated = spec_for(day="humid", dew_point_c=2.0).atmosphere.resolved()
    assert dew_stated["relative_humidity_pct"].value is None
    assert dew_stated["dew_point_c"].value == 2.0
    assert constraints(day="humid", dew_point_c=2.0) == []
    assert NonStandardAtmosphere.from_spec(spec_for()) is None


# -- before the trim ------------------------------------------------------------------

@pytest.mark.parametrize("aircraft,altitude_m,cas_kt", CASES)
def test_the_trim_sees_the_hot_day(aircraft, altitude_m, cas_kt):
    """The trimmed throttle at delta-T +30 differs from ISA's: the write
    landed BEFORE the trim (measured c172p 0.7392 -> 0.7488 at 1500 m /
    100 kt, A320 0.9418 -> 0.9550 at 6000 m / 250 kt). With the pre-trim
    hook removed the two are identical, which is the mutation guard's
    failing test."""
    isa = configure_from_spec(spec_for(aircraft, altitude_m, cas_kt))
    hot = configure_from_spec(spec_for(aircraft, altitude_m, cas_kt, day="hot_day"))
    throttle_isa = isa.props.get("fcs/throttle-cmd-norm")
    throttle_hot = hot.props.get("fcs/throttle-cmd-norm")
    assert hot.props.get(PROPERTY_DELTA_T) == 54.0
    assert isa.props.get(PROPERTY_DELTA_T) == 0.0
    assert throttle_hot - throttle_isa > 0.005, (throttle_isa, throttle_hot)


@pytest.mark.parametrize("aircraft,altitude_m,cas_kt", CASES)
def test_the_hot_day_moves_the_climb_rate_at_fixed_throttle(aircraft, altitude_m, cas_kt):
    """The null pair: the ISA-trimmed aircraft held at its trim controls
    for 5 s in ISA air holds altitude; the same in +30 degC air does not
    (measured mean climb rate over 5 s: c172p -0.059 m/s in ISA against
    -1.516 m/s hot; A320 +0.011 against -0.810 m/s)."""
    def mean_climb(provider):
        fdm = fdm_at(aircraft, altitude_m, cas_kt)
        fdm.start_engines()
        fdm.trim(TrimMode.LONGITUDINAL)
        fdm.hold_mass(True)
        stack = EnvironmentStack([provider] if provider is not None else [])
        stack.configure(fdm)
        rates = []
        for _ in range(int(5.0 * fdm.rate_hz)):
            stack.apply(fdm)
            fdm.step()
            rates.append(fdm.state().climb_rate_mps)
        return sum(rates) / len(rates)
    isa = mean_climb(None)
    hot = mean_climb(NonStandardAtmosphere(30.0, reference_altitude_m=altitude_m))
    assert abs(isa) < 0.1
    assert hot < isa - 0.2, (isa, hot)


# -- every step, read back ---------------------------------------------------------------

@pytest.fixture(scope="module")
def hot_humid_run():
    """A 3 s c172p flight on the hot, humid, low-pressure day, through the
    runner exactly as a capture flies it."""
    return run_spec(spec_for(day="hot_day", sea_level_pressure_hpa=990.0,
                             relative_humidity_pct=60.0))


@pytest.fixture(scope="module")
def isa_run():
    return run_spec(spec_for())


def atmosphere_records(run):
    """The atmosphere.* records of a run (the c172p also carries the
    limits monitor's record, which is not this item's)."""
    return {r["name"]: r for r in read_records(run.manifest["applied_variables"])
            if r["name"].startswith("atmosphere.")}


def test_the_properties_are_written_and_read_back_every_step(hot_humid_run):
    """Three writes per step for 360 steps; each read back before the
    next write: zero error on delta-T and P-sl, and on the dew point the
    one-step pressure change JSBSim's conserved vapour mass fraction
    implies (measured 1.5e-6 R here, 2.3e-7 R on the A320 autopilot run;
    pinned under 1e-6 relative). Before the trim the dew point reads back
    exactly (measured 0)."""
    records = atmosphere_records(hot_humid_run)
    steps = int(round(3.0 * 120.0))
    for record in records.values():
        per_step = record["parameters"]["per_step_readback"]
        assert per_step["steps_written"] == steps
        assert per_step["steps_checked"] == steps
        assert per_step["dew_point_limited_steps"] == 0
        assert per_step["agrees"]
        errors = per_step["max_abs_error"]
        assert errors[PROPERTY_DELTA_T] == 0.0
        assert errors[PROPERTY_P_SL] == 0.0
        assert 0.0 < errors[PROPERTY_DEW_POINT] <= 1e-6 * 500.0
        readback = record["parameters"]["readback"]
        assert readback["agrees"] and readback["abs_error"] <= 1e-9 * max(1.0, abs(readback["written"]))
        assert readback["abs_error"] == 0.0
    assert set(records) == {"atmosphere.temperature_deviation_c",
                            "atmosphere.sea_level_pressure_hpa",
                            "atmosphere.relative_humidity_pct"}


def test_each_stated_variable_returns_its_record_with_a_measured_null_test(hot_humid_run):
    records = atmosphere_records(hot_humid_run)
    dt = records["atmosphere.temperature_deviation_c"]
    assert dt["value"] == 30.0 and dt["unit"] == "degC" and dt["source"] == "inferred"
    assert dt["properties_written"] == [PROPERTY_DELTA_T]
    assert dt["parameters"]["written"] == 54.0
    p = records["atmosphere.sea_level_pressure_hpa"]
    assert p["value"] == 990.0 and p["source"] == "user"
    assert p["parameters"]["written"] == pytest.approx(atm.hpa_to_psf(990.0))
    rh = records["atmosphere.relative_humidity_pct"]
    assert rh["value"] == 60.0 and rh["properties_written"] == [PROPERTY_DEW_POINT]
    assert rh["parameters"]["dew_point_c"] == pytest.approx(
        atm.dew_point_c_from_humidity(60.0, 35.25), abs=0.05)
    for record in records.values():
        null = record["null_test"]
        assert null["ok"], record["name"]
        assert null["unit"] == "kg/m3" and null["with"] != null["without"]
        assert null["threshold"] == pytest.approx(0.001 * null["without"])
        assert record["telemetry_columns"] == list(TELEMETRY_COLUMNS)
        assert record["frame_keys"] == list(TELEMETRY_COLUMNS)
        assert record["model"].startswith("JSBSim 1.2.4 FGStandardAtmosphere")
        assert any("FGStandardAtmosphere.cpp" in ref for ref in record["references"])
        assert record["not_claimed"]
        assert record["parameters"]["route"].startswith("bias")
    # The hot day lowers density, the low pressure lowers it, the water lowers it.
    assert dt["null_test"]["difference"] < 0
    assert p["null_test"]["difference"] < 0
    assert rh["null_test"]["difference"] < 0
    # Delivered against predicted, from the run's own record.
    delivered = dt["parameters"]["delivered"]
    predicted = dt["parameters"]["predicted"]
    assert delivered["density_kgm3"] == pytest.approx(predicted["density_kgm3"], rel=1e-9)
    assert delivered["rh_pct"] == pytest.approx(60.0, rel=1e-6)


def test_the_standard_day_records_no_variable_and_the_limits_record_stays(isa_run):
    block = isa_run.manifest.get("applied_variables")
    recorded = [] if block is None else [r["name"] for r in read_records(block)]
    assert not any(name.startswith("atmosphere.") for name in recorded)
    assert isa_run.manifest["environment"] == [
        p for p in isa_run.manifest["environment"] if p["name"] != "non_standard_atmosphere"]


def test_the_channels_are_recorded_finite_and_agree_with_the_closed_form(hot_humid_run, isa_run):
    assert set(TELEMETRY_COLUMNS) <= set(DEFAULT_CHANNELS)
    for run in (hot_humid_run, isa_run):
        for column in TELEMETRY_COLUMNS:
            values = run.telemetry.series(column)
            assert len(values) == len(run.telemetry)
            assert all(v == v and abs(v) < 1e12 for v in values), column
    first = {c: hot_humid_run.telemetry.series(c)[0] for c in TELEMETRY_COLUMNS}
    dew = atm.dew_point_c_from_humidity(60.0, 35.25)
    form = closed_form(hot_humid_run.telemetry.series("altitude_m")[0], 30.0, 990.0, dew)
    for column in TELEMETRY_COLUMNS:
        assert first[column] == pytest.approx(form[column], rel=2e-3, abs=1.0), column
    assert isa_run.telemetry.series("rh_pct")[0] == 0.0
    assert isa_run.telemetry.series("density_altitude_m")[0] == pytest.approx(1500.0, abs=0.5)
    assert first["density_altitude_m"] > 2300.0


def test_the_run_is_deterministic_and_differs_from_isa(hot_humid_run, isa_run):
    again = run_spec(spec_for(day="hot_day", sea_level_pressure_hpa=990.0,
                              relative_humidity_pct=60.0))
    assert again.output_digest == hot_humid_run.output_digest
    assert again.output_digest != isa_run.output_digest


def test_a_stated_standard_day_flies_the_default_flight_to_the_floating_point_floor(isa_run):
    """delta-T 0 stated by the user is written before the trim and the
    pre-trim measurement re-latches the initial conditions (run_ic runs
    the models one more pass), so the flight is NOT bit-identical to the
    default: measured, the largest difference in any recorded column is
    4.0e-10 N (lift), 3.5e-11 kg (weight), 1.6e-13 deg (pitch). Pinned
    at 1e-8 per column; bit-identity is not claimed and the digests differ."""
    stated = run_spec(spec_for(temperature_deviation_c=0.0))
    assert stated.output_digest != isa_run.output_digest
    for name, column in isa_run.telemetry.columns.items():
        other = stated.telemetry.columns[name]
        assert len(other) == len(column)
        assert max(abs(x - y) for x, y in zip(column, other)) < 1e-8, name
    assert "atmosphere.temperature_deviation_c" in atmosphere_records(stated)
    null = atmosphere_records(stated)["atmosphere.temperature_deviation_c"]["null_test"]
    assert null["difference"] == 0.0 and not null["ok"]   # a zero deviation reaches nothing


def test_a_record_without_a_prepare_is_refused():
    with pytest.raises(ValueError, match="never called"):
        NonStandardAtmosphere(30.0).applied_variables()


def test_the_dew_point_write_is_limited_to_what_the_air_admits():
    """Along a flight the stated dew point is written as the least of
    itself, the modelled temperature at the aircraft's altitude, JSBSim's
    last temperature and the vapour cap; each limit is named."""
    provider = NonStandardAtmosphere(dew_point_c=5.0, reference_altitude_m=1500.0)
    assert provider.dew_point_write_r(1500.0) == (atm.celsius_to_rankine(5.0), None)
    written, limit = provider.dew_point_write_r(3000.0)
    assert limit == "temperature"
    assert written == pytest.approx(atm.temperature_r(u.m_to_ft(3000.0)))
    lower = atm.celsius_to_rankine(4.0)
    assert provider.dew_point_write_r(1500.0, jsbsim_temperature_r=lower) == (lower, "temperature")
    # The vapour cap wins only where the air is warm and the table is
    # thin: +45 degC with a -68 degC dew point validates at 16 km (the cap
    # there is a -63 degC dew point) and is capped at 20 km (measured
    # -69.33 degC), while the temperature limit never bites (-11.5 degC).
    high = NonStandardAtmosphere(45.0, dew_point_c=-68.0, reference_altitude_m=16000.0)
    assert high.dew_point_write_r(16000.0) == (high.dew_point_r, None)
    written, limit = high.dew_point_write_r(20000.0)
    assert limit == "vapour_cap" and atm.rankine_to_celsius(written) == pytest.approx(-69.33, abs=0.01)
    with pytest.raises(AtmosphereError, match="more water than the model admits"):
        NonStandardAtmosphere(45.0, dew_point_c=-60.0, reference_altitude_m=16000.0)


# -- the card -------------------------------------------------------------------------

def test_the_card_block_carries_the_exact_writes_in_a_fixed_key_order(tmp_path):
    spec = spec_for(day="hot_day", sea_level_pressure_hpa=990.0, relative_humidity_pct=60.0)
    block = atmosphere_card_block(spec)
    assert list(block) == [PROPERTY_DELTA_T, PROPERTY_P_SL, PROPERTY_DEW_POINT,
                           "applied", "dew_point_rule", "stated"]
    assert list(block) == list(CARD_KEYS)
    provider = NonStandardAtmosphere.from_spec(spec)
    writes = provider.writes_at(1500.0)
    assert block[PROPERTY_DELTA_T] == writes[PROPERTY_DELTA_T] == 54.0
    assert block[PROPERTY_P_SL] == writes[PROPERTY_P_SL]
    assert block[PROPERTY_DEW_POINT] == writes[PROPERTY_DEW_POINT]
    assert block["stated"]["relative_humidity_pct"] == {"value": 60.0, "source": "user",
                                                       "from": "test"}
    assert block["stated"]["dew_point_c"] is None
    path = write_run_card(spec, tmp_path / "card.json")
    text = path.read_text(encoding="utf-8")
    assert text.isascii()
    card = json.loads(text)
    assert list(card["atmosphere_properties"]) == list(CARD_KEYS)
    assert card["atmosphere_properties"] == block
    dry = atmosphere_card_block(spec_for(day="hot_day"))
    assert dry[PROPERTY_DEW_POINT] is None and dry[PROPERTY_P_SL] is None
    assert atmosphere_card_block(spec_for()) is None
    assert "atmosphere_properties" not in json.loads(
        write_run_card(spec_for(), tmp_path / "isa.json").read_text(encoding="utf-8"))


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    for rel in ("core/environment/atmosphere.py", "tests/test_atmosphere.py"):
        assert (REPO / rel).read_text(encoding="utf-8").isascii(), rel
    import inspect

    blocks = (REPO / "core/scenario/blocks.py").read_text(encoding="utf-8")
    assert blocks[blocks.index("DAY_WORDS"):blocks.index("def configured_airframes")].isascii()
    assert inspect.getsource(AtmosphereSpec).isascii()
    provider = NonStandardAtmosphere(30.0, 990.0, None, 60.0, reference_altitude_m=1500.0)
    assert json.dumps(provider.card_block()).isascii()
    assert json.dumps(provider.provenance()).isascii()


# -- the registry and the null pair (integrated with R1) ----------------------------

def test_every_registered_atmosphere_field_names_channels_the_run_records(isa_run):
    """The registry claims the block's five fields, the day word among
    them, and every effect channel a spec-field entry names is a column
    the run recorded -- so a null pair can measure it rather than refuse
    record.effect_channel (the first population named ``sigma``, which
    no recorder writes; measured here, and pinned)."""
    recorded = set(isa_run.telemetry.columns)
    fields = {f"atmosphere.{f}" for f in AtmosphereSpec.FIELD_ORDER}
    assert set(REGISTRY.spec_fields()) == fields
    for name in fields:
        entry = REGISTRY.get(name)
        missing = [c.name for c in entry.effect_channels if c.name not in recorded]
        assert missing == [], (name, missing)
    assert "sigma" not in recorded          # the reason the first population was wrong


def test_the_day_word_is_the_variable_that_moved_and_its_null_pair_measures_the_hot_day():
    """``day: hot_day`` keeps the numeric fields at their defaults in the
    spec's dict (the provider expands the word), so the word is the one
    stated variable off its null and the one pair a worded spec runs.
    Measured on the c172p at 1500 m, 3 s: the hot day moves density
    altitude 847.60 m and the air temperature 30.000 K against the
    standard day; the humidity channel does not move (0 %, below its
    0.1 % floor, graded so)."""
    pairs = null_pairs_for_spec(spec_for(day="hot_day"))
    assert list(pairs) == ["atmosphere.day"]
    pair = pairs["atmosphere.day"]
    assert pair.verdict == "reached" and pair.digests_differ
    assert pair.applied_value == "hot_day" and pair.null_value == "isa"
    effect = pair.to_dict()["effect"]
    assert effect["density_altitude_m"]["peak_abs"] == pytest.approx(847.5997, abs=0.05)
    assert effect["temperature_k"]["peak_abs"] == pytest.approx(30.0, abs=1e-3)
    assert effect["temperature_k"]["reached"] is True
    assert effect["rh_pct"]["peak_abs"] == 0.0 and effect["rh_pct"]["reached"] is False
    assert pair.null_test().ok is True


def test_the_dew_point_null_is_the_unstated_field_and_its_pair_reaches_every_channel():
    """A null of None is the field unstated (``value: null``), the form
    the block reads back -- a removed key is not a spec. Measured: a 5 degC
    dew point at 1500 m on the standard day (the modelled air there is
    5.25 degC) gives 98.26 % humidity, 871.7 Pa of vapour and 39.30 m of
    density altitude against dry air, each above its floor."""
    spec = spec_for(dew_point_c=5.0)
    null = null_spec_dict(spec.to_dict(), REGISTRY.get("atmosphere.dew_point_c"))
    assert null["atmosphere"]["dew_point_c"]["value"] is None
    assert null["atmosphere"]["dew_point_c"]["source"] == "derived"
    assert "unstated" in null["atmosphere"]["dew_point_c"]["from"]
    assert ScenarioSpec.from_dict(null).atmosphere.dew_point_c.value is None
    pair = run_null_pair(spec, "atmosphere.dew_point_c")
    effect = pair.to_dict()["effect"]
    assert pair.verdict == "reached"
    assert effect["rh_pct"]["peak_abs"] == pytest.approx(98.26, abs=0.05)
    assert effect["vapour_pressure_pa"]["peak_abs"] == pytest.approx(871.7, abs=0.5)
    assert effect["density_altitude_m"]["peak_abs"] == pytest.approx(39.30, abs=0.05)
    assert all(v["reached"] is True for v in effect.values())
