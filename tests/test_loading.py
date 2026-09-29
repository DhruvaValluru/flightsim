"""P4, loading: payload stations, fuel, and the centre of gravity read
back against the hand calculation.

Every number asserted here was measured in the container on 2026-09-28
against JSBSim 1.2.4 in .venv: the hand CG over the XML's own arms
equals JSBSim's inertia/cg-x-in to 1e-12 in on the c172p, A320, B747,
DHC6 and p51d (V13, tolerance 0.1 in); the CG property is stale until
the initial conditions are re-latched; a write BEFORE the trim moves
the trimmed elevator and the loaded aircraft holds altitude, a write
AFTER the trim leaves the trim solved for the unloaded aircraft (the
c172p pitches to 9.7 deg and climbs 20 m in 5 s); the p51d's weapon
stations are rewritten by a system every pass; the null pairs on the
c172p move cg_x_m by 0.097 m (136 kg at the aft-most seat) and
weight_kg by 77.1 kg (full fuel); the committed spec-8 examples keep
their digests.

What is NOT claimed: any handbook number (arms, maxima, the polygon,
the maximum weights are from memory and marked so in the config); the
lateral and vertical CG; the engine side (the card block is pinned,
nothing applies it here).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import inspect
import io
import json
import math
from pathlib import Path

import pytest
import yaml

from core.fdm import FlightDynamics, TrimMode
from core.fdm import units as u
from core.fdm.state import KGM2_PER_SLUGFT2
from core.nl.compiler import compile_prompt
from core.record_null import null_pairs_for_spec, run_null_pair
from core.records import read_records
from core.registry import REGISTRY
from core.scenario import loading as ld
from core.scenario.blocks import LOADING_STANDARDS, LoadingSpec, configured_airframes
from core.scenario.card import loading_card_block, write_run_card
from core.scenario.fields import Source
from core.scenario.loading import (
    CARD_KEYS, CG_TOLERANCE_IN, TELEMETRY_COLUMNS, LoadingError, LoadingPlan, LoadingProvider,
    hand_cg_in, load_loading_config, parse_loading_config, point_in_polygon, station_key,
)
from core.scenario.runner import configure_from_spec, fdm_at_initial_conditions, run_spec
from core.scenario.spec import ScenarioSpec
from core.scenario.validate import validate, validate_loading
from core.telemetry.recorder import DEFAULT_CHANNELS

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
LEVEL = {"gamma-deg": 0.0, "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
#: The five configured airframes: (altitude m, CAS kt, a loading each admits).
AIRFRAMES = {
    "c172p": (1500.0, 100.0, {"payload": {"Right Passenger": 136.0}, "fuel_fraction": 1.0}),
    "A320": (6000.0, 250.0, {"fuel_fraction": 0.8}),
    "B747": (6000.0, 280.0, {"fuel_kg": 20000.0}),
    "DHC6": (1500.0, 120.0, {"payload": {"name": 100.0}, "fuel_fraction": 0.9}),
    "p51d": (1500.0, 200.0, {"payload": {"pilot": 100.0}, "fuel_fraction": 0.7}),
}
#: V13 measured: |hand - JSBSim| after the writes and a re-latch, inches.
V13_MEASURED_IN = {"c172p": 7.1e-15, "A320": 0.0, "B747": 6.9e-13, "DHC6": 2.9e-14, "p51d": 1.5e-14}


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def spec_for(aircraft="c172p", altitude_m=1500.0, cas_kt=100.0, seconds=3,
             hold_state=False, **loading) -> ScenarioSpec:
    """A compiled spec with the loading fields stated through the spec's
    own front door (hold_state False: the autopilot's sign probe trims
    every airframe at 6000 m / 280 kt, outside the c172p's envelope)."""
    spec = compile_prompt(f"fly the {aircraft} at {altitude_m:g} m and "
                          f"{cas_kt:g} kt for {seconds} seconds")
    spec.set("hold_state", hold_state, frm="test")
    for name, value in loading.items():
        spec.set(f"loading.{name}", value, frm="test")
    return spec


def spec_by_hand(aircraft: str, altitude_m: float, cas_kt: float, **loading) -> ScenarioSpec:
    """A spec for an airframe the prompt compiler does not map (DHC6,
    p51d), from a committed example with the airframe set by hand."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_waypoint.yaml")
    spec.set("aircraft", aircraft, frm="test")
    spec.set("altitude", altitude_m, frm="test")
    spec.set("airspeed", cas_kt, frm="test")
    spec.set("hold_state", False, frm="test")
    for name, value in loading.items():
        spec.set(f"loading.{name}", value, frm="test")
    return spec


def names(violations):
    return [v.constraint for v in violations]


def constraints(**loading):
    return names(validate_loading(spec_for(**loading)))


def prepared(aircraft: str):
    altitude_m, cas_kt, loading = AIRFRAMES[aircraft]
    spec = spec_by_hand(aircraft, altitude_m, cas_kt, **loading)
    provider = LoadingProvider.from_spec(spec)
    fdm = quiet(fdm_at_initial_conditions, spec)
    report = quiet(provider.prepare, fdm)
    return provider, fdm, report


# -- the configured airframes --------------------------------------------------------

def test_every_configured_airframe_carries_a_loading_block_that_parses():
    airframes = configured_airframes()
    assert set(airframes) == set(AIRFRAMES)
    for name in airframes:
        config = load_loading_config(name)
        assert config is not None, name
        assert config.tanks and config.empty_lb > 0.0 and config.max_takeoff_weight_kg > 0.0
        assert config.arm_comparison_status in ("inferred", "unverified")
        assert config.config_path == f"assets/aircraft_config/{name}.json"
        assert "unverified here" in config.max_takeoff_weight_source
        for station in config.stations:
            assert station.source and (station.loadable or station.reason)
        assert len(hashlib.sha256().hexdigest()) == len(config.config_sha256)


def test_the_arm_comparison_test_the_xml_half_on_every_airframe_and_the_handbook_half_on_the_c172p():
    """The XML half: every configured arm, default weight, empty weight
    and capacity is the loaded model's (through the cross-check prepare
    makes). The handbook half: only the c172p records handbook arms --
    36 / 70 / 95 in against 37 / 73 / 95 in, a 3 in inference, status
    inferred; the four others are unverified with the reason stated."""
    for name in AIRFRAMES:
        provider, fdm, report = prepared(name)
        checks = report["checks"]
        assert checks["empty_lb"]["configured"] == checks["empty_lb"]["live"]
        for key, entry in checks.items():
            if key.startswith("station:") or key.startswith("tank:"):
                assert entry["arm_in"]["configured"] == entry["arm_in"]["live"], (name, key)
            if key.startswith("tank:") and entry["capacity_lb"]["live_from_pct_full"] is not None:
                assert entry["capacity_lb"]["live_from_pct_full"] == pytest.approx(
                    entry["capacity_lb"]["configured"], rel=1e-9), (name, key)
    c172p = load_loading_config("c172p")
    comparison = c172p.datum["arm_comparison"]
    assert comparison["status"] == "inferred"
    assert comparison["stations_xml_in"] == {"Pilot": 36.0, "Co-Pilot": 36.0, "Left Passenger": 70.0,
                                            "Right Passenger": 70.0, "Baggage": 95.0}
    assert comparison["stations_poh_in"] == {"Pilot": 37.0, "Co-Pilot": 37.0, "Left Passenger": 73.0,
                                            "Right Passenger": 73.0, "Baggage": 95.0}
    assert comparison["max_station_difference_in"] == 3.0
    assert max(abs(comparison["stations_xml_in"][k] - comparison["stations_poh_in"][k])
               for k in comparison["stations_xml_in"]) == 3.0
    assert "3 in" in comparison["inference"] and "unverified here" in comparison["source"]
    assert {s.name: s.poh_arm_in for s in c172p.stations} == comparison["stations_poh_in"]
    for name in ("A320", "B747", "DHC6", "p51d"):
        config = load_loading_config(name)
        assert config.arm_comparison_status == "unverified"
        assert "loading.datum_unverified" in config.datum["arm_comparison"]["reason"]
        assert config.envelope_polygon is None and config.envelope_reason
        assert not config.envelope_admitted
    assert c172p.envelope_admitted and c172p.envelope_polygon is not None


def test_the_p51d_weapon_stations_are_rewritten_by_a_system_and_are_not_loadable():
    """Measured: 300 lb written to inertia/pointmass-weight-lbs[1] on the
    p51d reads 0.0 after one model pass (Systems/weapons-weight.xml
    writes it), while the pilot station holds its write."""
    fdm = quiet(FlightDynamics, "p51d")
    quiet(fdm.set_initial_conditions, {"h-sl-ft": u.m_to_ft(1500.0), "vc-kts": 200.0, **LEVEL})
    fdm.props.set("inertia/pointmass-weight-lbs[1]", 300.0)
    fdm.props.set("inertia/pointmass-weight-lbs", 100.0)
    fdm.relatch_initial_conditions()
    assert fdm.props.get("inertia/pointmass-weight-lbs[1]") == 0.0
    assert fdm.props.get("inertia/pointmass-weight-lbs") == 100.0
    config = load_loading_config("p51d")
    assert [s.name for s in config.stations if s.loadable] == ["pilot"]
    assert all("weapons-weight.xml" in s.reason for s in config.stations if not s.loadable)
    with pytest.raises(LoadingError) as exc:
        config.station("left bomb")
    assert exc.value.constraint == "loading.station_unknown"
    assert "cannot be loaded" in exc.value.message


def test_a_malformed_loading_block_refuses_loading_config_by_name():
    block = json.loads((REPO / "assets/aircraft_config/c172p.json").read_text(encoding="utf-8"))["loading"]
    parse_loading_config("c172p", block)
    cases = {
        "no source": lambda b: b.pop("source"),
        "station without max": lambda b: b["stations"][0].pop("max_kg"),
        "station without source": lambda b: b["stations"][0].update(source=""),
        "unloadable without reason": lambda b: b["stations"][0].update(loadable=False),
        "tank over capacity default": lambda b: b["tanks"][0].update(default_lb=1000.0),
        "tank index out of order": lambda b: b["tanks"][1].update(index=5),
        "polygon of two points": lambda b: b["cg_envelope"].update(polygon=[[35, 1500], [47, 1500]]),
        "null polygon without reason": lambda b: b["cg_envelope"].update(polygon=None),
        "policy station unknown": lambda b: b.update(policy_station="Nose"),
        "bad datum status": lambda b: b["datum"]["arm_comparison"].update(status="green"),
        "no max weight source": lambda b: b["max_takeoff_weight"].update(source=""),
    }
    for label, mutate in cases.items():
        bad = copy.deepcopy(block)
        mutate(bad)
        with pytest.raises(LoadingError) as exc:
            parse_loading_config("c172p", bad)
        assert exc.value.constraint == "loading.config", label
    assert load_loading_config("nonesuch") is None


# -- the geometry ----------------------------------------------------------------------

def test_the_hand_cg_and_the_point_in_polygon_test():
    assert hand_cg_in([1500.0, 180.0, 100.0, 100.0], [41.0, 36.0, 56.0, 56.0]) == pytest.approx(42.11702127659574)
    with pytest.raises(ValueError):
        hand_cg_in([0.0], [1.0])
    polygon = load_loading_config("c172p").envelope_polygon
    assert polygon == ((35.0, 1500.0), (35.0, 1950.0), (39.5, 2400.0), (47.3, 2400.0), (47.3, 1500.0))
    assert point_in_polygon(42.1, 1880.0, polygon)                 # the XML's own loading
    assert point_in_polygon(46.68, 2349.8, polygon)                # 136 kg at the rear seat, full fuel
    assert not point_in_polygon(49.39, 2180.0, polygon)            # 300 lb of baggage
    assert not point_in_polygon(36.0, 2300.0, polygon)             # ahead of the sloping forward limit
    assert not point_in_polygon(42.0, 2450.0, polygon)             # above the maximum weight
    assert point_in_polygon(47.3, 2000.0, polygon)                 # ON the aft limit: at it, not beyond
    assert point_in_polygon(35.0, 1700.0, polygon)                 # on the forward limit
    assert point_in_polygon(37.25, 2175.0, polygon)                # on the sloping edge
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert point_in_polygon(0.5, 0.5, square) and not point_in_polygon(1.5, 0.5, square)


def test_station_names_match_up_to_case_spaces_and_underscores():
    config = load_loading_config("c172p")
    for spelling in ("Right Passenger", "right_passenger", "RIGHT-PASSENGER", " right  passenger "):
        assert config.station(spelling).index == 3, spelling
    assert station_key("Left Passenger") == "left_passenger"
    with pytest.raises(LoadingError) as exc:
        config.station("Nose")
    assert exc.value.constraint == "loading.station_unknown"
    assert "['Pilot', 'Co-Pilot', 'Left Passenger', 'Right Passenger', 'Baggage']" in exc.value.message


# -- the spec block --------------------------------------------------------------------

def _canonical_digest(data: dict) -> str:
    payload = dict(data)
    payload.pop("prompt", None)
    payload.pop("notes", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _spec_examples():
    return sorted(p.name for p in EXAMPLES.glob("*.yaml")
                  if "spec_version" in yaml.safe_load(p.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", _spec_examples())
def test_a_committed_spec_8_example_keeps_its_canonical_form_and_digest(name):
    """Absent is canonical: the block adds no key to a spec that states
    none of it, so every committed example's digest is the digest of its
    own file (the rule re-implemented here) and unchanged."""
    frozen = yaml.safe_load(EXAMPLES.joinpath(name).read_text(encoding="utf-8"))
    assert "loading" not in frozen
    spec = ScenarioSpec.from_dict(copy.deepcopy(frozen))
    assert spec.loading.is_default()
    assert "loading" not in spec.to_dict()
    assert spec.digest() == _canonical_digest(frozen)


def test_a_stated_block_round_trips_changes_the_digest_and_sits_behind_the_front_door(tmp_path):
    spec = spec_for(payload={"Baggage": 20.0}, fuel_fraction=0.8)
    assert spec.digest() != spec_for().digest()
    reread = ScenarioSpec.read(spec.write(tmp_path / "s.yaml"))
    assert reread.digest() == spec.digest()
    assert reread.loading.payload.value == {"Baggage": 20.0}
    assert reread.loading.payload.source is Source.USER
    assert list(reread.to_dict()["loading"]) == list(LoadingSpec.FIELD_ORDER) == ["payload", "fuel_kg", "fuel_fraction"]
    assert reread.loading.fuel_kg.value is None and reread.loading.fuel_kg.std == LOADING_STANDARDS["fuel_kg"]
    with pytest.raises(ValueError, match="never silently moved"):
        spec.plan("loading.payload", {"Baggage": 1.0}, frm="planner")
    spec.plan("loading.fuel_kg", 50.0, frm="planner")
    assert spec.loading.fuel_kg.source is Source.DERIVED
    with pytest.raises(ValueError, match="not a loading field"):
        spec.set("loading.ballast", 1.0)
    data = spec.to_dict()
    data["loading"]["ballast"] = {"value": 1.0, "source": "user"}
    with pytest.raises(ValueError, match="unknown fields"):
        ScenarioSpec.from_dict(data)
    assert "[loading]" in spec.render_table()


# -- the refusals, by name ------------------------------------------------------------------

def test_refusals_by_name():
    assert constraints(payload={"Nose": 1.0}) == ["loading.station_unknown"]
    assert constraints(payload={"Right Passenger": -1.0}) == ["loading.station_mass"]
    assert constraints(payload={"Baggage": 136.0}) == ["loading.station_mass"]      # 120 lb max [unverified]
    assert constraints(payload={"Baggage": 54.4}) == []                              # at the maximum
    assert constraints(payload={"Baggage": "heavy"}) == ["loading.station_mass"]
    assert constraints(payload=["Baggage"]) == ["loading.station_unknown"]
    assert constraints(payload={"Baggage": 1.0, "baggage": 2.0}) == ["loading.station_unknown"]
    assert constraints(fuel_kg=-1.0) == ["loading.fuel_range"]
    assert constraints(fuel_kg=0.0) == ["loading.fuel_range"]
    assert constraints(fuel_kg=500.0) == ["loading.fuel_range"]                     # 167.8 kg capacity
    assert constraints(fuel_kg=167.8) == []
    assert constraints(fuel_fraction=1.5) == ["loading.fuel_range"]
    assert constraints(fuel_fraction=0.0) == ["loading.fuel_range"]
    assert constraints(fuel_fraction="full") == ["loading.fuel_range"]
    assert constraints(fuel_kg=100.0, fuel_fraction=0.5) == ["loading.fuel_range"]
    # four 150 kg seats and full fuel: 1448 kg over the 1088.6 kg maximum, and aft of 47.3 in
    heavy = constraints(payload={"Pilot": 150.0, "Co-Pilot": 150.0, "Left Passenger": 150.0,
                                 "Right Passenger": 150.0}, fuel_fraction=1.0)
    assert heavy == ["loading.max_weight", "loading.cg_envelope"]
    # inside the weight, outside the envelope: 120 lb of baggage and a 150 kg rear
    # passenger put the CG at 48.80 in with 2330.7 lb (aft limit 47.3 in)
    aft = validate_loading(spec_for(payload={"Baggage": 54.4, "Right Passenger": 150.0}))
    assert names(aft) == ["loading.cg_envelope"]
    assert aft[0].actual == pytest.approx(48.80, abs=0.01) and aft[0].unit == "in"
    assert "inferred" in aft[0].message
    assert constraints() == []


def test_the_whole_validator_names_the_loading_refusal_and_the_feasibility_trim_sees_the_loading():
    report = quiet(validate, spec_for(payload={"Baggage": 136.0}), check_feasibility=False)
    assert names(report.violations) == ["loading.station_mass"]
    assert "over its stated maximum" in report.render()
    spec = spec_for(payload={"Right Passenger": 136.0}, fuel_fraction=1.0)
    report = quiet(validate, spec)
    assert report.ok, report.render()
    # The feasibility probe trims the LOADED aircraft (configure_from_spec with
    # no stack builds one holding the two pre-trim providers): its CG after
    # the trim is the hand CG, not the XML loading's 42.12 in.
    fdm = quiet(configure_from_spec, spec)
    assert fdm.props.get("inertia/cg-x-in") == pytest.approx(46.679150890286564, abs=1e-3)
    assert fdm.props.get("propulsion/tank[1]/contents-lbs") == pytest.approx(185.0, abs=0.01)


def test_a_stated_loading_on_an_airframe_without_a_block_refuses_loading_config(tmp_path):
    spec = spec_for(fuel_fraction=0.5)
    with pytest.raises(LoadingError) as exc:
        LoadingPlan.from_spec(spec, config_dir=tmp_path)
    assert exc.value.constraint == "loading.config"
    assert LoadingPlan.from_spec(spec_for(), config_dir=tmp_path) is None


def test_the_envelope_is_refused_by_name_only_when_asked_for_and_the_flight_flies():
    """Lesson from wave 3: the user stated a fuel load on the A320, not an
    envelope. The runner records the check as not made (by name) and
    flies; require_envelope() -- the API asking -- refuses
    loading.datum_unverified."""
    plan = LoadingPlan.from_spec(spec_for("A320", 6000.0, 250.0, fuel_fraction=0.8))
    assert plan.problems() == []
    check = plan.envelope_check()
    assert check["checked"] is False and check["constraint"] == "loading.datum_unverified"
    assert plan.notes == [check]
    with pytest.raises(LoadingError) as exc:
        plan.require_envelope()
    assert exc.value.constraint == "loading.datum_unverified"
    assert "percent MAC" in exc.value.message
    c172p = LoadingPlan.from_spec(spec_for(payload={"Baggage": 20.0}))
    assert c172p.require_envelope()["inside"] is True and c172p.notes == []


# -- V13: the hand CG against JSBSim on five airframes -------------------------------------

@pytest.mark.parametrize("aircraft", sorted(AIRFRAMES))
def test_v13_the_hand_cg_equals_jsbsims_cg_x_in_within_the_tolerance(aircraft):
    """The writes land, the initial conditions are re-latched, and
    inertia/cg-x-in equals sum(m x)/sum(m) over the XML's own arms:
    measured c172p 7.1e-15, A320 0.0, B747 6.9e-13, DHC6 2.9e-14, p51d
    1.5e-14 in against the 0.1 in tolerance; every property written
    reads back to the bit."""
    provider, fdm, report = prepared(aircraft)
    cg = report["cg"]
    assert cg["agrees"] and cg["tolerance_in"] == CG_TOLERANCE_IN == 0.1
    assert cg["abs_error"] <= V13_MEASURED_IN[aircraft] + 1e-12, (aircraft, cg)
    assert cg["read"] == fdm.props.get("inertia/cg-x-in")
    assert all(r["agrees"] and r["abs_error"] == 0.0 for r in report["readback"].values())
    assert report["after"]["weight_lb"] == pytest.approx(
        provider.plan.gross_lb(report["before"]["stations_lb"], report["before"]["tanks_lb"]), abs=1e-6)
    assert report["iyy_kgm2"] == pytest.approx(report["after"]["iyy_slugft2"] * KGM2_PER_SLUGFT2)
    assert report["cg_x_m"] == pytest.approx(u.ft_to_m(cg["read"] / 12.0))


def test_the_cg_property_is_stale_until_the_initial_conditions_are_relatched():
    """Why prepare re-latches after every write: measured, cg-x-in reads
    its old 42.117 in immediately after a 300 lb write and 49.571 in
    after run_ic; the loading's read-back would otherwise compare the
    hand CG with a number JSBSim had not yet computed."""
    fdm = quiet(FlightDynamics, "c172p")
    quiet(fdm.set_initial_conditions, {"h-sl-ft": u.m_to_ft(1500.0), "vc-kts": 100.0, **LEVEL})
    before = fdm.props.get("inertia/cg-x-in")
    fdm.props.set("inertia/pointmass-weight-lbs[4]", 300.0)
    assert fdm.props.get("inertia/cg-x-in") == before == pytest.approx(42.11702127659574)
    fdm.relatch_initial_conditions()
    assert fdm.props.get("inertia/cg-x-in") == pytest.approx(49.394495412844036)
    assert fdm.sim_time == 0.0


def test_a_hand_cg_off_by_more_than_the_tolerance_is_refused_by_name():
    """The tolerance is a guard, not a formality: an empty-weight arm
    transcribed 0.2 in wrong makes the hand CG miss JSBSim's by 0.14 in
    and prepare refuses loading.config; 0.05 in wrong (0.036 in of CG)
    passes. Fails with the tolerance widened."""
    spec = spec_for(payload={"Baggage": 20.0})
    for arm_error_in, refused in ((0.2, True), (0.05, False)):
        config = load_loading_config("c172p")
        wrong = config.__class__(**{**config.__dict__, "empty_arm_in": config.empty_arm_in + arm_error_in})
        provider = LoadingProvider(LoadingPlan.from_spec(spec, config=wrong))
        fdm = quiet(fdm_at_initial_conditions, spec)
        if refused:
            with pytest.raises(LoadingError) as exc:
                quiet(provider.prepare, fdm)
            assert exc.value.constraint == "loading.config" and "hand calculation" in exc.value.message
        else:
            report = quiet(provider.prepare, fdm)
            assert 0.0 < report["cg"]["abs_error"] < CG_TOLERANCE_IN


def test_a_configured_arm_that_is_not_the_models_is_refused_by_name():
    """The cross-check before any write: a station arm transcribed 5 in
    wrong (the XML says 70) refuses loading.config, naming the station,
    before a hand CG over the wrong arm could be compared with anything."""
    spec = spec_for(payload={"Right Passenger": 20.0})
    config = load_loading_config("c172p")
    stations = tuple(s.__class__(**{**s.__dict__, "arm_in": 75.0}) if s.name == "Right Passenger" else s
                     for s in config.stations)
    wrong = config.__class__(**{**config.__dict__, "stations": stations})
    provider = LoadingProvider(LoadingPlan.from_spec(spec, config=wrong))
    fdm = quiet(fdm_at_initial_conditions, spec)
    with pytest.raises(LoadingError) as exc:
        quiet(provider.prepare, fdm)
    assert exc.value.constraint == "loading.config"
    assert "arm of station 'Right Passenger'" in exc.value.message and "(75)" in exc.value.message
    assert fdm.props.get("inertia/pointmass-weight-lbs[3]") == 0.0       # nothing was written


def test_the_fuel_is_shared_in_proportion_to_capacity_and_a_fraction_fills_every_tank():
    plan = LoadingPlan.from_spec(spec_by_hand("p51d", 1500.0, 200.0, fuel_kg=500.0))
    loads = plan.tank_loads()
    capacities = [t.capacity_lb for t in plan.config.tanks]
    assert capacities == [607.21, 607.21, 561.0, 495.0, 495.0]
    total = u.kg_to_lb(500.0)
    assert [tl.lb for tl in loads] == pytest.approx([total * c / sum(capacities) for c in capacities])
    assert sum(tl.lb for tl in loads) == pytest.approx(total)
    plan = LoadingPlan.from_spec(spec_by_hand("p51d", 1500.0, 200.0, fuel_fraction=0.7))
    assert [tl.lb for tl in plan.tank_loads()] == pytest.approx([0.7 * c for c in capacities])
    assert ld.FUEL_FILL_RULE in plan.to_dict()["fuel_fill_rule"]


# -- before the trim, not after ---------------------------------------------------------------

@pytest.mark.timeout(300)
def test_a_write_before_the_trim_moves_the_trim_and_a_write_after_it_does_not():
    """Measured on the c172p (1500 m / 100 kt, 300 lb at the baggage
    station, the trim held for 5 s with the mass frozen): written BEFORE
    the trim the elevator goes 4.306 -> 5.537 deg and the loaded
    aircraft holds altitude like the unloaded one (-0.29 m in 5 s);
    written AFTER the trim the elevator stays at 4.306 deg, the aircraft
    pitches 0.39 -> 9.72 deg and climbs 20.0 m in 5 s. The runner's path
    is the first; this is what the order guard protects."""
    def fdm_at():
        fdm = quiet(FlightDynamics, "c172p")
        quiet(fdm.set_initial_conditions, {"h-sl-ft": u.m_to_ft(1500.0), "vc-kts": 100.0, **LEVEL})
        return fdm

    def trim(fdm):
        quiet(fdm.start_engines)
        quiet(fdm.trim, TrimMode.LONGITUDINAL)

    def fly(fdm, seconds=5.0):
        fdm.hold_mass(True)
        altitudes, pitches = [], []
        for _ in range(int(seconds * fdm.rate_hz)):
            fdm.step()
            state = fdm.state()
            altitudes.append(state.altitude_m)
            pitches.append(state.pitch_deg)
        return altitudes, pitches

    station = "inertia/pointmass-weight-lbs[4]"
    base = fdm_at()
    trim(base)
    elevator_base = math.degrees(base.props.get("fcs/elevator-pos-rad"))
    alt_base, pitch_base = fly(base)
    before = fdm_at()
    before.props.set(station, 300.0)
    before.relatch_initial_conditions()
    trim(before)
    elevator_before = math.degrees(before.props.get("fcs/elevator-pos-rad"))
    alt_before, pitch_before = fly(before)
    after = fdm_at()
    trim(after)
    after.props.set(station, 300.0)
    elevator_after = math.degrees(after.props.get("fcs/elevator-pos-rad"))
    alt_after, pitch_after = fly(after)
    assert elevator_base == pytest.approx(4.306, abs=0.01)
    assert elevator_before == pytest.approx(5.537, abs=0.01)
    assert elevator_after == elevator_base
    assert abs(alt_before[-1] - alt_before[0]) < 1.0 and abs(alt_base[-1] - alt_base[0]) < 1.0
    assert alt_after[-1] - alt_after[0] > 15.0                       # measured +20.0 m
    assert max(pitch_after) > 8.0 and max(pitch_before) < 1.5        # measured 9.72 / 0.83 deg


def test_the_run_applies_the_loading_once_before_the_trim_after_the_atmosphere(loaded_run, isa_run):
    """The recorded flight's first sample carries the loaded CG (the
    hand value in metres), the trimmed elevator differs from the
    unloaded run's, and the manifest's environment lists the atmosphere
    before the loading. The order guard (the loading never attached)
    makes the loaded run's CG the unloaded one's."""
    block = loaded_run.manifest["loading"]
    hand_m = u.ft_to_m(block["prepared"]["cg"]["hand"] / 12.0)
    assert loaded_run.telemetry.series("cg_x_m")[0] == pytest.approx(hand_m, abs=1e-6)
    # the unloaded run's first sample sits 2e-6 m from the IC value: the crank's
    # 0.0055 lb of fuel (measured), so 1e-5 here
    assert isa_run.telemetry.series("cg_x_m")[0] == pytest.approx(u.ft_to_m(42.11702127659574 / 12.0), abs=1e-5)
    assert loaded_run.telemetry.series("cg_x_m")[0] - isa_run.telemetry.series("cg_x_m")[0] > 0.1
    assert loaded_run.telemetry.series("elevator_deg")[0] != isa_run.telemetry.series("elevator_deg")[0]
    assert block["prepared"]["writes"] == {"inertia/pointmass-weight-lbs[3]": pytest.approx(u.kg_to_lb(136.0)),
                                           "propulsion/tank/contents-lbs": 185.0,
                                           "propulsion/tank[1]/contents-lbs": 185.0}
    assert block["post_trim"]["cg_moved_by_trim_in"] == pytest.approx(0.0, abs=1e-3)   # the crank's 0.0055 lb
    assert 0.0 < block["prepared"]["after"]["fuel_lb"] - block["post_trim"]["fuel_lb"] < 0.01
    providers = [p["name"] for p in loaded_run.manifest["environment"]]
    assert providers.index("non_standard_atmosphere") < providers.index("loading")
    assert block["applied"] is True and block["envelope"]["checked"] is True
    assert block["envelope"]["inside"] is True


# -- the run: records, channels, card ------------------------------------------------------------

@pytest.fixture(scope="module")
def loaded_run():
    """The demonstration run: c172p, 136 kg at the aft-most seat, full
    fuel, on the hot day (so the two pre-trim providers are both in the
    stack and their order is measured)."""
    spec = spec_for(payload={"Right Passenger": 136.0}, fuel_fraction=1.0)
    spec.set("atmosphere.day", "hot_day", frm="test")
    return quiet(run_spec, spec)


@pytest.fixture(scope="module")
def isa_run():
    return quiet(run_spec, spec_for())


def loading_records(run):
    return {r["name"]: r for r in read_records(run.manifest["applied_variables"])
            if r["name"].startswith("loading.")}


def test_each_stated_field_returns_its_record_2_with_readback_writes_and_a_measured_null_test(loaded_run):
    records = loading_records(loaded_run)
    assert list(records) == ["loading.payload_kg", "loading.fuel_fraction"]
    payload = records["loading.payload_kg"]
    assert payload["value"] == {"Right Passenger": 136.0} and payload["source"] == "user"
    assert payload["unit"] == "kg per station"
    assert payload["readback"]["property"] == "inertia/cg-x-in"
    assert payload["readback"]["agrees"] and payload["readback"]["tolerance"] == 0.1
    assert payload["readback"]["written"] == pytest.approx(46.679150890286564)
    assert payload["readback"]["value"] == pytest.approx(46.679150890286564, abs=1e-9)
    assert payload["jsbsim_writes"] == [{"property": "inertia/pointmass-weight-lbs[3]", "when": ld.WHEN}]
    assert payload["properties_written"] == ["inertia/pointmass-weight-lbs[3]"]
    assert payload["telemetry_columns"] == list(TELEMETRY_COLUMNS) == payload["frame_keys"]
    assert payload["model"]["name"] == "hand W&B"
    assert payload["model"]["parameters"]["station_arms_in"]["Baggage"] == 95.0
    null = payload["null_test"]
    assert null["kind"] == "reached" and null["ok"] is True and null["unit"] == "in"
    assert null["without"] == pytest.approx(42.11702127659574)
    assert null["with"] == pytest.approx(45.95223855736711)         # the seat write alone, tanks after
    assert null["threshold"] == CG_TOLERANCE_IN
    assert payload["parameters"]["stations"][0]["readback"]["agrees"] is True
    assert payload["parameters"]["arm_comparison"]["status"] == "inferred"
    assert payload["parameters"]["envelope"]["inside"] is True
    assert "from" in payload and "std" in payload and payload["std"] == LOADING_STANDARDS["payload"]
    fuel = records["loading.fuel_fraction"]
    assert fuel["value"] == 1.0 and fuel["unit"] == "1"
    assert fuel["readback"] == {"property": "propulsion/tank/contents-lbs", "value": 185.0, "written": 185.0,
                                "agrees": True, "tolerance": 0.0, "tolerance_kind": "absolute",
                                "basis": fuel["readback"]["basis"]}
    assert [w["property"] for w in fuel["jsbsim_writes"]] == ["propulsion/tank/contents-lbs",
                                                              "propulsion/tank[1]/contents-lbs"]
    assert fuel["null_test"]["unit"] == "kg" and fuel["null_test"]["ok"] is True
    assert fuel["null_test"]["with"] == pytest.approx(u.lb_to_kg(370.0))
    assert fuel["null_test"]["without"] == pytest.approx(u.lb_to_kg(200.0))
    assert fuel["parameters"]["total_fuel_kg"] == pytest.approx(u.lb_to_kg(370.0))
    assert any("handbook" in n for n in fuel["not_claimed"])
    json.dumps(loaded_run.manifest)


def test_the_channels_are_recorded_finite_and_the_default_block_records_nothing(loaded_run, isa_run):
    assert set(TELEMETRY_COLUMNS) <= set(DEFAULT_CHANNELS)
    for run in (loaded_run, isa_run):
        for column in TELEMETRY_COLUMNS:
            values = run.telemetry.series(column)
            assert len(values) == len(run.telemetry) and all(math.isfinite(v) for v in values)
    assert loaded_run.telemetry.series("iyy_kgm2")[0] == pytest.approx(1460.51 * KGM2_PER_SLUGFT2, rel=1e-3)
    assert isa_run.telemetry.series("iyy_kgm2")[0] == pytest.approx(1384.2627 * KGM2_PER_SLUGFT2, rel=1e-3)
    assert KGM2_PER_SLUGFT2 == pytest.approx(1.3558179483, rel=1e-9)
    assert isa_run.manifest["loading"] is None
    assert loading_records(isa_run) == {}
    assert [r["name"] for r in read_records(isa_run.manifest["applied_variables"])] == [
        "limits.monitor", "scene.geoid_undulation_m"]
    assert "loading" not in [p["name"] for p in isa_run.manifest["environment"]]


def test_the_run_is_deterministic_and_differs_from_the_unloaded_one(loaded_run, isa_run):
    spec = spec_for(payload={"Right Passenger": 136.0}, fuel_fraction=1.0)
    spec.set("atmosphere.day", "hot_day", frm="test")
    again = quiet(run_spec, spec)
    assert again.output_digest == loaded_run.output_digest
    assert again.output_digest != isa_run.output_digest


def test_a_record_without_a_prepare_is_refused():
    provider = LoadingProvider.from_spec(spec_for(fuel_fraction=0.5))
    with pytest.raises(ValueError, match="never called"):
        provider.applied_variables()
    assert provider.properties(None, 0.0) == {}
    assert any(t.phrase == "fuel_fraction" for t in provider.vocabulary())


def test_the_card_block_carries_the_exact_writes_in_a_fixed_key_order(tmp_path):
    spec = spec_for(payload={"Right Passenger": 136.0}, fuel_fraction=1.0)
    block = loading_card_block(spec)
    assert tuple(block) == CARD_KEYS == ("stations", "tanks", "expected_cg_in", "tolerance_in", "datum")
    assert block["stations"] == [{"name": "Right Passenger", "property": "inertia/pointmass-weight-lbs[3]",
                                  "lbs": pytest.approx(u.kg_to_lb(136.0))}]
    assert block["tanks"] == [{"index": 0, "property": "propulsion/tank/contents-lbs", "lbs": 185.0},
                              {"index": 1, "property": "propulsion/tank[1]/contents-lbs", "lbs": 185.0}]
    assert block["expected_cg_in"] == pytest.approx(46.679150890286564)
    assert block["tolerance_in"] == 0.1
    assert block["datum"]["arm_comparison_status"] == "inferred" and block["datum"]["applied"] == ld.WHEN
    assert loading_card_block(spec_for()) is None
    path = quiet(write_run_card, spec, tmp_path / "card.json")
    card = json.loads(path.read_text(encoding="utf-8"))
    assert list(card["loading_properties"]) == list(CARD_KEYS)
    assert card["loading_properties"]["expected_cg_in"] == block["expected_cg_in"]
    assert path.read_text(encoding="utf-8").isascii()
    with pytest.raises(LoadingError) as exc:
        loading_card_block(spec_for(payload={"Baggage": 136.0}))
    assert exc.value.constraint == "loading.station_mass"
    assert "loading_properties" not in json.loads(
        quiet(write_run_card, spec_for(), tmp_path / "plain.json").read_text(encoding="utf-8"))


def test_everything_the_engine_or_a_reader_sees_is_ascii():
    assert (REPO / "core/scenario/loading.py").read_text(encoding="utf-8").isascii()
    assert inspect.getsource(LoadingSpec).isascii()
    for name in AIRFRAMES:
        text = (REPO / f"assets/aircraft_config/{name}.json").read_text(encoding="utf-8")
        assert text.isascii(), name
        assert json.dumps(load_loading_config(name).to_dict()).isascii()
    provider = LoadingProvider.from_spec(spec_for(payload={"Baggage": 20.0}, fuel_kg=100.0))
    assert json.dumps(provider.card_block()).isascii()
    assert json.dumps(provider.provenance()).isascii()


# -- the registry and the null pairs (integrated with R1) ---------------------------------------

def test_the_registry_claims_the_block_field_for_field_with_recorded_channels(isa_run):
    fields = {f"loading.{f}" for f in LoadingSpec.FIELD_ORDER}
    assert fields <= set(REGISTRY.spec_fields())
    assert "loading" in REGISTRY.sections()
    recorded = set(isa_run.telemetry.columns)
    for name in ("loading.payload_kg", "loading.fuel_kg", "loading.fuel_fraction"):
        entry = REGISTRY.get(name)
        assert entry.null_value is None and entry.jsbsim_writes
        missing = [c.name for c in entry.effect_channels if c.name not in recorded]
        assert missing == [], (name, missing)
        assert {"cg_x_m", "iyy_kgm2", "weight_kg"} <= {c.name for c in entry.effect_channels}
    assert REGISTRY.get("loading.payload_kg").spec_path == "loading.payload"
    assert REGISTRY.get("loading.payload_kg").readback_tolerance.value == CG_TOLERANCE_IN
    assert REGISTRY.get("loading.fuel_kg").readback_tolerance.value == 0.0
    assert REGISTRY.get("loading.payload_kg").channel_units()["iyy_kgm2"] == "kg m^2"
    assert REGISTRY.unregistered_fields(spec_for(fuel_fraction=0.5).to_dict()) == []


@pytest.mark.timeout(300)
def test_the_null_pair_of_136_kg_at_the_aft_most_seat_moves_the_cg_the_elevator_and_the_pitch():
    """0 vs 136 kg (300 lb) at the aft-most SEAT (Right Passenger, 70 in;
    the aft-most station, the 95 in baggage area, admits 120 lb by the
    handbook, so 136 kg there refuses loading.station_mass -- measured
    above). Measured on the c172p, 1500 m / 100 kt, 3 s: cg_x_m moves
    0.0974 m (below the 0.5 m altitude floor a metre channel carries;
    reported so), the trimmed elevator 0.223 deg and pitch 0.548 deg
    (both above the 0.05 deg floor), weight_kg 136 kg and iyy_kgm2 73
    kg m^2 (graded since integration against the stated 0.5 kg and
    1 kg m^2 floors, and the CG against its own 0.00254 m floor: the
    mass is the strongest channel relative to its floor, so the null
    test's unit is kg); the output digests differ."""
    pair = run_null_pair(spec_for(payload={"Right Passenger": 136.0}), "loading.payload_kg")
    d = pair.to_dict()
    assert pair.verdict == "reached" and pair.digests_differ and pair.null_test().ok
    assert pair.applied_value == {"Right Passenger": 136.0} and pair.null_value is None
    effect = d["effect"]
    assert effect["cg_x_m"]["peak_abs"] == pytest.approx(0.09742, abs=0.0005)
    assert effect["weight_kg"]["peak_abs"] == pytest.approx(136.0, abs=0.01)
    assert effect["iyy_kgm2"]["peak_abs"] == pytest.approx(73.1, abs=0.5)
    assert effect["elevator_deg"]["peak_abs"] == pytest.approx(0.2232, abs=0.002)
    assert effect["elevator_deg"]["reached"] is True
    assert effect["pitch_deg"]["peak_abs"] == pytest.approx(0.548, abs=0.005)
    assert effect["pitch_deg"]["reached"] is True
    assert effect["altitude_m"]["peak_abs"] < 0.05
    assert effect["weight_kg"]["reached"] is True and effect["cg_x_m"]["reached"] is True
    assert d["null_test"]["unit"] == "kg"          # 136 kg over a 0.5 kg floor: the strongest


@pytest.mark.timeout(300)
def test_the_null_pair_of_full_fuel_and_the_pairs_a_spec_states():
    """fuel_fraction 1.0 (370 lb) against the XML's 200 lb: weight_kg
    77.11 kg, cg_x_m 0.0292 m, the trimmed elevator 0.183 deg (measured;
    full against HALF fuel, flown by hand: 83.9 kg, 0.0321 m, 0.199 deg,
    pitch 0.354 deg). A spec stating both fields runs both pairs."""
    pair = run_null_pair(spec_for(fuel_fraction=1.0), "loading.fuel_fraction")
    effect = pair.to_dict()["effect"]
    assert pair.verdict == "reached" and pair.digests_differ
    assert effect["weight_kg"]["peak_abs"] == pytest.approx(77.11, abs=0.05)
    assert effect["cg_x_m"]["peak_abs"] == pytest.approx(0.02924, abs=0.0005)
    assert effect["elevator_deg"]["peak_abs"] == pytest.approx(0.1825, abs=0.002)
    assert effect["elevator_deg"]["reached"] is True
    pairs = null_pairs_for_spec(spec_for(payload={"Baggage": 54.4}, fuel_kg=150.0))
    assert list(pairs) == ["loading.payload_kg", "loading.fuel_kg"]
    assert all(p.verdict == "reached" for p in pairs.values())
    assert pairs["loading.fuel_kg"].to_dict()["effect"]["weight_kg"]["peak_abs"] == pytest.approx(59.28, abs=0.05)
    # the payload pair here flies both sides with the 150 kg of fuel stated beside it
    # (0.0743 m; with the XML's 200 lb the same station moves 0.0806 m, measured)
    assert pairs["loading.payload_kg"].to_dict()["effect"]["cg_x_m"]["peak_abs"] == pytest.approx(0.0743, abs=0.0005)


# -- the randomisation leaves ------------------------------------------------------------------

def test_the_policy_leaves_draw_the_fuel_fraction_and_the_payload_at_the_policy_station():
    from core.scenario.randomization import (
        POLICY_LEAVES, RandomizationError, card_block, realised_distribution, sample_randomization,
    )

    assert POLICY_LEAVES["fuel_fraction"]["target"] == "loading.fuel_fraction"
    assert POLICY_LEAVES["payload_kg"]["target"] == "loading.payload"
    spec = spec_for()
    spec.set("randomization.policy", {"fuel_fraction": {"uniform": [0.5, 1.0]},
                                      "payload_kg": {"uniform": [20.0, 100.0]}}, frm="test")
    spec.set("randomization.seed", 3, frm="test")
    quiet(sample_randomization, spec)
    fraction = spec.loading.fuel_fraction
    payload = spec.loading.payload
    assert fraction.source is Source.SAMPLED and 0.5 <= fraction.value <= 1.0
    assert payload.source is Source.SAMPLED and list(payload.value) == ["Co-Pilot"]
    assert 20.0 <= payload.value["Co-Pilot"] <= 100.0 and "front passenger seat" in payload.frm
    assert payload.detail["policy"] == "randomization.policy.payload_kg"
    block = card_block(spec)
    assert block["fuel_fraction"] == fraction.value and block["payload_kg"] == payload.value["Co-Pilot"]
    realised = realised_distribution([{"randomization": block, "frames": 4}])
    assert realised["fields"]["fuel_fraction"]["frames"] == 4
    assert realised["fields"]["payload_kg"]["frames"] == 4
    assert realised["fields"]["fuel_fraction"]["coverage"] > 0.0
    assert validate(spec, check_feasibility=False).ok
    # a stated field is never moved by a draw
    stated = spec_for(fuel_fraction=0.9)
    stated.set("randomization.policy", {"fuel_fraction": {"uniform": [0.5, 1.0]}}, frm="test")
    stated.set("randomization.seed", 3, frm="test")
    with pytest.raises(RandomizationError) as exc:
        quiet(sample_randomization, stated)
    assert exc.value.constraint == "randomization.policy" and "never moved" in exc.value.message
    # an airframe with no station refuses the payload leaf by name
    none = spec_for("A320", 6000.0, 250.0)
    none.set("randomization.policy", {"payload_kg": {"uniform": [20.0, 100.0]}}, frm="test")
    none.set("randomization.seed", 3, frm="test")
    with pytest.raises(RandomizationError) as exc:
        quiet(sample_randomization, none)
    assert exc.value.constraint == "randomization.policy" and "no payload station" in exc.value.message
